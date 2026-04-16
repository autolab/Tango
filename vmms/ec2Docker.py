#
# ec2Docker.py - Implements the Tango VMMS interface to run Tango Docker jobs on Amazon EC2.
#

import logging
import os
import re
import stat
import subprocess
import threading
import time

import backoff
import boto3
from botocore.exceptions import ClientError

import config
from tangoObjects import TangoMachine
from typing import Optional, Literal, List, Sequence
from mypy_boto3_ec2 import EC2ServiceResource
from mypy_boto3_ec2.service_resource import Instance
from mypy_boto3_ec2.type_defs import FilterTypeDef

from vmms.interface import VMMSInterface

# Suppress verbose boto logging
logging.getLogger("boto3").setLevel(logging.CRITICAL)
logging.getLogger("botocore").setLevel(logging.CRITICAL)
logging.getLogger("urllib3.connectionpool").setLevel(logging.CRITICAL)


def timeout(command, time_out=1):
    """timeout - Run a unix command with a timeout. Return -1 on
    timeout, otherwise return the return value from the command, which
    is typically 0 for success, 1-255 for failure.
    """

    # Launch the command
    p = subprocess.Popen(
        command, stdout=open("/dev/null", "w"), stderr=subprocess.STDOUT
    )

    # Wait for the command to complete
    t = 0.0
    while t < time_out and p.poll() is None:
        time.sleep(config.Config.TIMER_POLL_INTERVAL)
        t += config.Config.TIMER_POLL_INTERVAL
    if t >= time_out:
        print("ERROR: timeout trying ", command)
    # Determine why the while loop terminated
    if p.poll() is None:
        try:
            os.kill(p.pid, 9)
        except OSError:
            pass
        returncode = -1
    else:
        returncode = p.poll()
    return returncode


def timeout_with_retries(command, time_out=1, retries=3, retry_delay=2):
    """timeout - Run a unix command with a timeout. Return -1 on
    timeout, otherwise return the return value from the command, which
    is typically 0 for success, 1-255 for failure.
    """
    for attempt in range(retries + 1):
        # Launch the command
        p = subprocess.Popen(
            command, stdout=open("/dev/null", "w"), stderr=subprocess.STDOUT
        )

        # Wait for the command to complete
        t = 0.0
        while t < time_out and p.poll() is None:
            time.sleep(config.Config.TIMER_POLL_INTERVAL)
            t += config.Config.TIMER_POLL_INTERVAL
        if t >= time_out:
            print("ERROR: timeout trying ", command)

        # Determine why the while loop terminated
        if p.poll() is None:
            try:
                os.kill(p.pid, 9)
            except OSError:
                pass
            returncode = -1
        else:
            returncode = p.poll()

        # try to retry the command on a timeout
        if returncode == -1:
            if attempt < retries:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                # attempt == retries -> failure
                print("All retries exhausted.")
                return -1
        else:
            return returncode


@backoff.on_exception(backoff.expo, ClientError, max_tries=3, jitter=None)
def try_load_instance(newInstance):
    newInstance.load()


#
# User defined exceptions
#
# ec2Call() exception


class ec2CallError(Exception):
    pass


class Ec2Docker(VMMSInterface):
    _SSH_FLAGS = [
        "-i", config.Config.SECURITY_KEY_PATH,
        "-o", "StrictHostKeyChecking no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "BatchMode yes",
        "-o", "IdentitiesOnly yes",
        "-o", "PreferredAuthentications publickey",
        "-o", "ConnectTimeout 5",
        "-o", "GSSAPIAuthentication no",
    ]

    _vm_semaphore = threading.Semaphore(config.Config.MAX_EC2_VMS)

    @staticmethod
    def acquire_vm_semaphore():
        """Blocks until a VM is available to limit load"""
        Ec2Docker._vm_semaphore.acquire()  # This blocks until a slot is available

    @staticmethod
    def release_vm_semaphore():
        """Releases the VM sempahore"""
        Ec2Docker._vm_semaphore.release()

    @staticmethod
    def _validate_ec2_runtime_config() -> str:
        """Validate required EC2 configuration and return normalized key path."""
        missing = []

        if not str(config.Config.EC2_REGION).strip():
            missing.append("EC2_REGION")
        if not str(config.Config.EC2_USER_NAME).strip():
            missing.append("EC2_USER_NAME")
        if not str(config.Config.SECURITY_KEY_PATH).strip():
            missing.append("SECURITY_KEY_PATH")

        if missing:
            raise ValueError(
                "Missing required EC2 configuration: %s"
                % ", ".join(missing)
            )

        key_path = os.path.expanduser(str(config.Config.SECURITY_KEY_PATH).strip())
        if not os.path.isfile(key_path):
            raise ValueError(
                "Invalid SECURITY_KEY_PATH (file does not exist): %s" % key_path
            )
        if not os.access(key_path, os.R_OK):
            raise ValueError(
                "Invalid SECURITY_KEY_PATH (file is not readable): %s" % key_path
            )

        key_mode = stat.S_IMODE(os.stat(key_path).st_mode)
        if key_mode & 0o077:
            # Try to auto-fix common container mount permission issue.
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass

            key_mode = stat.S_IMODE(os.stat(key_path).st_mode)
            if key_mode & 0o077:
                raise ValueError(
                    "Invalid SECURITY_KEY_PATH permissions for private key %s (mode %o). "
                    "Expected chmod 600 (or stricter)." % (key_path, key_mode)
                )

        return key_path

    def refresh_ecr_images(self):
        self.ecrImages = {}
        try:
            ecrClient = boto3.client("ecr", self.ec2Region)

            for repo_page in ecrClient.get_paginator("describe_repositories").paginate():
                for repo in repo_page["repositories"]:
                    repo_name = repo["repositoryName"]
                    repo_uri = repo["repositoryUri"]

                    for image_page in ecrClient.get_paginator("list_images").paginate(
                        repositoryName=repo_name,
                        filter={"tagStatus": "TAGGED"}
                    ):
                        for image_id in image_page.get("imageIds", []):
                            tag = image_id.get("imageTag")
                            if tag:
                                self.ecrImages[f"{repo_uri}:{tag}"] = tag
        except Exception as e:
            self.log.error("Ec2Docker failed retrieving ECR images: %s" % (e))
            raise

    def __init__(self, accessKeyId=None, accessKey=None):
        """log - logger for the instance
        connection - EC2Connection object that stores the connection
        info to the EC2 network
        instance - Instance object that stores information about the
        VM created
        """
        # do not do anything until we acquire a vm semaphore
        Ec2Docker.acquire_vm_semaphore()
        validated_key_path = Ec2Docker._validate_ec2_runtime_config()

        self.appName = os.path.basename(__file__).strip(".py")
        # Setup logger
        self.log = logging.getLogger("Ec2Docker-" + str(os.getpid()))
        self.log.info("init Ec2Docker in program %s" % (self.appName))

        # initialize EC2 USER
        # PDL gets a ec2user in the parameter, just use the default
        # user for now
        self.ssh_flags = Ec2Docker._SSH_FLAGS.copy()
        self.ssh_flags[1] = validated_key_path
        self.ec2User = str(config.Config.EC2_USER_NAME).strip()
        self.ec2Region = str(config.Config.EC2_REGION).strip()
        self.useDefaultKeyPair = True

        if self.useDefaultKeyPair:
            self.key_pair_name: str = config.Config.SECURITY_KEY_NAME
            self.key_pair_path: str = validated_key_path
        else:
            raise

        self.img2ami = {} 
        try:
            self.boto3resource: EC2ServiceResource = boto3.resource("ec2", self.ec2Region)
            self.boto3client = boto3.client("ec2", self.ec2Region)
            images = self.boto3resource.images.filter(Owners=["self"])
        except Exception as e:
            self.log.error("Ec2Docker failed initialization: %s" % (e))
            raise

        for image in images:
            if image.tags:
                for tag in image.tags:
                    if tag["Key"] == "Name" and tag["Value"]:
                        if tag["Value"] in self.img2ami:
                            self.log.info("Ignore %s for duplicate name tag %s" % (image.id, tag["Value"]))
                        else:
                            self.img2ami[tag["Value"]] = image
                            self.log.info("Found image: %s with name tag %s" % (image.id, tag["Value"]))

        imageAMIs = [item.id for item in images]
        taggedAMIs = [self.img2ami[key].id for key in self.img2ami]
        ignoredAMIs = list(set(imageAMIs) - set(taggedAMIs))

        if len(ignoredAMIs) > 0:
            self.log.info(
                "Ignored images %s for lack of or ill-formed name tag"
                % str(ignoredAMIs)
            )
        
        self.refresh_ecr_images()

    def instanceName(self, id, name):
        """instanceName - Constructs a VM instance name. Always use
        this function when you need a VM instance name. Never generate
        instance names manually.
        """
        return "%s-%d-%s" % (config.Config.PREFIX, id, name)

    def keyPairName(self, id, name):
        """keyPairName - Constructs a unique key pair name."""
        return "%s-%d-%s" % (config.Config.PREFIX, id, name)

    def domainName(self, vm):
        """Returns the domain name that is stored in the vm
        instance.
        """
        return vm.domain_name

    #
    # VMMS helper methods
    #

    def tangoMachineToEC2Instance(self, vm: TangoMachine):
        """Returns instance type and base AMI. Defers to a universal Docker base image."""
        ec2instance = dict()

        # Note: Unlike other vmms backend, instance type is chosen from
        # the optional instance type attached to image name as
        # "image+instance_type", such as my_course_mage+t2.small.

        if vm.instance_type is not None:
            ec2instance["instance_type"] = vm.instance_type
        else:
            ec2instance["instance_type"] = config.Config.DEFAULT_INST_TYPE

        # Use universal base AMI for all Docker executions
        ec2instance["ami"] = self.img2ami["autolab-docker-base"].id
        self.log.info("tangoMachineToEC2Instance: %s" % str(ec2instance))
        return ec2instance

    def createKeyPair(self):
        raise

    def deleteKeyPair(self):
        raise

    def createSecurityGroup(self):
        try:
            response = self.boto3client.describe_security_groups(
                Filters=[{"Name": "group-name", "Values": [config.Config.DEFAULT_SECURITY_GROUP]}]
            )
            if response["SecurityGroups"]: return
        except Exception as e:
            self.log.debug("ERROR checking for existing security group: %s", e)

        try:
            response = self.boto3resource.create_security_group(
                GroupName=config.Config.DEFAULT_SECURITY_GROUP,
                Description="Autolab security group - allowing all traffic",
            )
            self.boto3resource.authorize_security_group_ingress(GroupId=response["GroupId"])
        except Exception as e:
            self.log.debug("ERROR in creating security group: %s", e)

    def initializeVM(self, vm: TangoMachine) -> Literal[0, -1]:
        """Provisions a new Spot Instance and attaches the ECR Role."""
        newInstance: Optional[Instance] = None
        try:
            instanceName = self.instanceName(vm.id, vm.name)
            ec2instance = self.tangoMachineToEC2Instance(vm)
            self.log.debug("instanceName: %s" % instanceName)
            self.createSecurityGroup()

            reservation: List[Instance] = self.boto3resource.create_instances(
                ImageId=ec2instance["ami"],
                KeyName=self.key_pair_name,
                SecurityGroups=[config.Config.DEFAULT_SECURITY_GROUP],
                InstanceType=ec2instance["instance_type"],
                IamInstanceProfile={'Name': 'AutolabEC2ECRRole'}, # Grants ECR access
                MaxCount=1,
                MinCount=1,
                InstanceMarketOptions={
                    "MarketType": "spot",
                    "SpotOptions": {
                        "SpotInstanceType": "one-time",
                        "InstanceInterruptionBehavior": "terminate"
                    }
                },
            )

            # Sleep for a while to prevent random transient errors observed
            # when the instance is not available yet
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

            # reservation is a list of instances created. there is only
            # one instance created so get index 0.
            newInstance = reservation[0]
            if not newInstance:
                raise ValueError("Cannot find new instance for %s" % vm.name)

            start_time = time.time()
            while True:
                filters: Sequence[FilterTypeDef] = [{"Name": "instance-state-name", "Values": ["running"]}]
                instances = self.boto3resource.instances.filter(Filters=filters)
                instanceRunning = False

                try_load_instance(newInstance)
                for inst in instances.filter(InstanceIds=[newInstance.id]):
                    self.log.debug("VM %s %s: is running" % (vm.name, newInstance.id))
                    instanceRunning = True

                if instanceRunning: break

                if time.time() - start_time > config.Config.INITIALIZEVM_TIMEOUT:
                    raise ValueError("VM %s %s: timeout" % (vm.name, newInstance.id))
                time.sleep(config.Config.TIMER_POLL_INTERVAL)

            self.boto3resource.create_tags(
                Resources=[newInstance.id], Tags=[{"Key": "Name", "Value": vm.name}],
            )

            vm.domain_name = newInstance.public_ip_address
            vm.instance_id = newInstance.id
            return 0

        except Exception as e:
            self.log.debug("initializeVM Failed: %s" % e)
            if newInstance is not None:
                try: self.boto3resource.instances.filter(InstanceIds=[newInstance.id]).terminate()
                except Exception as e:
                    self.log.error("Exception handling failed for %s: %s" % (vm.name, e))
                    return -1
            return -1

    def waitVM(self, vm, max_secs) -> Literal[0, -1]:
        """Polls the instance until network and SSH drivers are responsive."""
        self.log.info("WaitVM: %s %s" % (vm.name, vm.instance_id))
        if not self.existsVM(vm):
            self.log.info("VM %s: no longer an instance", vm.name)
            return -1
        
        # First, wait for ping to the vm instance to work
        instance_down = 1
        start_time = time.time()
        domain_name = self.domainName(vm)
        
        self.log.info("WaitVM: pinging %s %s" % (domain_name, vm.name))
        while instance_down:
            instance_down = subprocess.call(
                "ping -c 1 %s" % (domain_name), shell=True,
                stdout=open("/dev/null", "w"), stderr=subprocess.STDOUT,
            )
            if instance_down:
                time.sleep(config.Config.TIMER_POLL_INTERVAL)
                if (time.time() - start_time) > max_secs:
                    self.log.debug("WAITVM_TIMEOUT: %s", vm.id)
                    return -1

        # The ping worked, so now wait for SSH to work before
        # declaring that the VM is ready
        self.log.debug("VM %s: ping completed" % (vm.name))
        while True:
            elapsed_secs = time.time() - start_time

            # Give up if the elapsed time exceeds the allowable time
            if elapsed_secs > max_secs:
                self.log.info(
                    "VM %s: SSH timeout after %d secs" % (vm.name, elapsed_secs)
                )
                return -1
            
            # If the call to ssh returns timeout (-1) or ssh error
            # (255), then success. Otherwise, keep trying until we run
            # out of time.
            ret = timeout(
                ["ssh"] + self.ssh_flags + ["%s@%s" % (self.ec2User, domain_name), "(:)"],
                max_secs - elapsed_secs,
            )

            self.log.debug("VM %s: ssh returned with %d" % (vm.name, ret))

            if (ret != -1) and (ret != 255):
                return 0
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

    def copyIn(self, vm, inputFiles, job_id=None):
        """Creates the staging directory and securely copies grading files to EC2."""
        self.log.info("copyIn %s - writing files" % self.instanceName(vm.id, vm.name))
        domain_name = self.domainName(vm)

        subprocess.run(
            ["ssh"] + self.ssh_flags + ["%s@%s" % (self.ec2User, domain_name), "(mkdir -p autolab && chmod 775 autolab)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        for file in inputFiles:
            ret = timeout_with_retries(
                ["scp"] + self.ssh_flags + [file.localFile, "%s@%s:~/autolab/%s" % (self.ec2User, domain_name, file.destFile)],
                config.Config.COPYIN_TIMEOUT,
            )
            if ret != 0: return ret
        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize, disableNetwork):
        """Authenticates with ECR, pulls the requested course image, and executes the grader."""
        domain_name = self.domainName(vm)
        self.log.debug("runJob: Running Docker job on VM %s" % self.instanceName(vm.id, vm.name))
        
        network_flag = "--network none " if disableNetwork else ""
        
        # Parse the ECR Registry domain from the provided image URI
        registry_url = vm.image.split('/')[0] if '/' in vm.image else ""
        region = self.ec2Region
        
        # ECR Auth -> Docker Run
        runcmd = (
            f"aws ecr get-login-password --region {region} | "
            f"docker login --username AWS --password-stdin {registry_url} && "
            f"docker run --rm {network_flag}-v /home/%s/autolab:/home/mount -w /home {vm.image} "
            "sh -c \"cd /home && mkdir -p output && chown autolab:autolab output && "
            "cp -a mount/. autolab/ && chown -R autolab:autolab autolab/ && "
            "su autolab -c \\\"autodriver "
            "-u %d -f %d -t %d -o %d autolab > output/feedback 2>&1\\\" ; touch output/time.out ;"
            "cp output/feedback mount/ ; cp output/time.out mount/\""
            % (
                self.ec2User,
                config.Config.VM_ULIMIT_USER_PROC,
                config.Config.VM_ULIMIT_FILE_SIZE,
                runTimeout,
                maxOutputFileSize,
            )
        )

        print("running command:")
        print(runcmd)

        ret = timeout(["ssh"] + self.ssh_flags + ["%s@%s" % (self.ec2User, domain_name), runcmd], runTimeout * 2)
        return ret

    def copyOut(self, vm, destFile):
        """Retrieves the completed feedback log back to the Tango host."""
        domain_name = self.domainName(vm)
        if config.Config.LOG_TIMING:
            try:
                no_file = re.compile("No such file or directory")
                time_info = (
                    subprocess.check_output(["ssh"] + self.ssh_flags + ["%s@%s" % (self.ec2User, domain_name), "cat autolab/time.out"])
                    .decode("utf-8").rstrip("\n")
                )
                if not no_file.match(time_info):
                    time_info = re.sub("\n", " ", time_info, count=1)
                    self.log.info("Timing (%s): %s" % (domain_name, time_info))
            except subprocess.CalledProcessError: pass

        return timeout(
            ["scp"] + self.ssh_flags + ["%s@%s:autolab/feedback" % (self.ec2User, domain_name), destFile],
            config.Config.COPYOUT_TIMEOUT,
        )

    def destroyVM(self, vm):
        """Terminates the EC2 instance to preserve costs."""
        try:
            instances = self.boto3resource.instances.filter(InstanceIds=[vm.instance_id])
            if (hasattr(config.Config, "KEEP_VM_AFTER_FAILURE") and config.Config.KEEP_VM_AFTER_FAILURE and vm.keep_for_debugging):
                tag = self.boto3resource.Tag(vm.instance_id, "Name", vm.name)
                if tag: tag.delete()
                self.boto3resource.create_tags(
                    Resources=[vm.instance_id],
                    Tags=[{"Key": "Name", "Value": "failed-" + vm.name}, {"Key": "Notes", "Value": vm.notes}],
                )
                return
            instances.terminate()
        except Exception as e:
            self.log.error("destroyVM failed: %s for vm %s" % (e, vm.instance_id))
        Ec2Docker.release_vm_semaphore()

    def safeDestroyVM(self, vm):
        return self.destroyVM(vm)

    def getVMs(self):
        try:
            vms = list()
            filters = [{"Name": "instance-state-name", "Values": ["running", "pending"]}]
            instances = self.boto3resource.instances.filter(Filters=filters)
            for instance in instances:
                vm = TangoMachine()
                vm.instance_id = instance.id
                vm.domain_name = None
                vm.id = None
                instName = self.getTag(instance.tags, "Name")
                if not (instName and re.match("%s-" % config.Config.PREFIX, instName)): continue
                vm.name = instName
                vm.id = int(instName.split("-")[1])
                vm.pool = instName.split("-")[2]
                if instance.public_ip_address: vm.domain_name = instance.public_ip_address
                vms.append(vm)
        except Exception: pass
        return vms

    def existsVM(self, vm):
        filters = [{"Name": "instance-state-name", "Values": ["running"]}]
        instances = self.boto3resource.instances.filter(Filters=filters)
        for instance in instances:
            if instance.instance_id == vm.instance_id: return True
        return False

    def getImages(self):
        self.refresh_ecr_images()
        return [key for key in self.ecrImages]

    def getTag(self, tagList, tagKey):
        if tagList:
            for tag in tagList:
                if tag["Key"] == tagKey: return tag["Value"]
        return None

    def getPartialOutput(self, vm):
        domain_name = self.domainName(vm)
        runcmd = "head -c %s autolab/feedback" % (config.Config.MAX_OUTPUT_FILE_SIZE)
        sshcmd = (["ssh"] + self.ssh_flags + ["%s@%s" % (self.ec2User, domain_name), runcmd])
        return subprocess.check_output(sshcmd, stderr=subprocess.STDOUT).decode("utf-8")
