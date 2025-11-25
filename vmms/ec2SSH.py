#
# ec2SSH.py - Implements the Tango VMMS interface to run Tango jobs on Amazon EC2.
#
# This implementation uses the AWS EC2 SDK to manage the virtual machines and
# ssh and scp to access them. The following excecption are raised back
# to the caller:
#
#   Ec2Exception - EC2 raises this if it encounters any problem
#   ec2CallError - raised by ec2Call() function
#

import logging
import os
import re
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


# suppress most boto logging
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


def timeoutWithReturnStatus(command, time_out, returnValue=0):
    """timeoutWithReturnStatus - Run a Unix command with a timeout,
    until the expected value is returned by the command; On timeout,
    return last error code obtained from the command.
    """
    p = subprocess.Popen(
        command, stdout=open("/dev/null", "w"), stderr=subprocess.STDOUT
    )
    t = 0.0
    while t < time_out:
        ret = p.poll()
        if ret is None:
            time.sleep(config.Config.TIMER_POLL_INTERVAL)
            t += config.Config.TIMER_POLL_INTERVAL
        elif ret == returnValue:
            return ret
        else:
            p = subprocess.Popen(
                command, stdout=open("/dev/null", "w"), stderr=subprocess.STDOUT
            )
            return ret


@backoff.on_exception(backoff.expo, ClientError, max_tries=3, jitter=None)
def try_load_instance(newInstance):
    newInstance.load()


#
# User defined exceptions
#
# ec2Call() exception


class ec2CallError(Exception):
    pass


class Ec2SSH(VMMSInterface):
    _SSH_FLAGS = [
        "-i",
        config.Config.SECURITY_KEY_PATH,
        "-o",
        "StrictHostKeyChecking no",
        "-o",
        "GSSAPIAuthentication no",
    ]

    # limit max number of VMS runnning per config
    _vm_semaphore = threading.Semaphore(config.Config.MAX_EC2_VMS)

    @staticmethod
    def acquire_vm_semaphore():
        """Blocks until a VM is available to limit load"""
        Ec2SSH._vm_semaphore.acquire()  # This blocks until a slot is available

    @staticmethod
    def release_vm_semaphore():
        """Releases the VM sempahore"""
        Ec2SSH._vm_semaphore.release()

    # TODO: the arguments accessKeyId and accessKey don't do anything
    def __init__(self, accessKeyId=None, accessKey=None):
        """log - logger for the instance
        connection - EC2Connection object that stores the connection
        info to the EC2 network
        instance - Instance object that stores information about the
        VM created
        """
        # do not do anything until we acquire a vm semaphore
        Ec2SSH.acquire_vm_semaphore()

        self.appName = os.path.basename(__file__).strip(".py")
        # Setup logger
        self.log = logging.getLogger("Ec2SSH-" + str(os.getpid()))
        self.log.info("init Ec2SSH in program %s" % (self.appName))

        # initialize EC2 USER
        # PDL gets a ec2user in the parameter, just use the default
        # user for now
        self.ssh_flags = Ec2SSH._SSH_FLAGS
        self.ec2User = config.Config.EC2_USER_NAME
        self.useDefaultKeyPair = True

        # key pair settings, for now, use default security key
        if self.useDefaultKeyPair:
            self.key_pair_name: str = config.Config.SECURITY_KEY_NAME
            self.key_pair_path: str = config.Config.SECURITY_KEY_PATH
        else:
            # TODO: SUPPORT. Know that this if/else block used to be under initializeVM, using vm for a unique identifier
            raise
            # self.key_pair_name = self.keyPairName(vm.id, vm.name)
            # self.createKeyPair()
        # create boto3resource

        self.img2ami = {} # this is a bad name, should really be img_name to img
        self.images = []
        try:
            # This is a service resource
            self.boto3resource: EC2ServiceResource = boto3.resource("ec2", config.Config.EC2_REGION) # TODO: rename this ot self.ec2resource
            self.boto3client = boto3.client("ec2", config.Config.EC2_REGION)

            # Get images from ec2
            images = self.boto3resource.images.filter(Owners=["self"])
        except Exception as e:
            self.log.error("EC2SSH failed initialization: %s" % (e))
            raise

        for image in images:
            if image.tags:
                for tag in image.tags:
                    if tag["Key"] == "Name" and tag["Value"]:
                        if tag["Value"] in self.img2ami:
                            self.log.info(
                                "Ignore %s for duplicate name tag %s"
                                % (image.id, tag["Value"])
                            )
                        else:
                            self.img2ami[tag["Value"]] = image
                            self.log.info(
                                "Found image: %s with name tag %s"
                                % (image.id, tag["Value"])
                            )

        imageAMIs = [item.id for item in images]
        taggedAMIs = [self.img2ami[key].id for key in self.img2ami]
        ignoredAMIs = list(set(imageAMIs) - set(taggedAMIs))

        if len(ignoredAMIs) > 0:
            self.log.info(
                "Ignored images %s for lack of or ill-formed name tag"
                % str(ignoredAMIs)
            )

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

    def tangoMachineToEC2Instance(self, vm: TangoMachine) -> dict:
        """tangoMachineToEC2Instance - returns an object with EC2 instance
        type and AMI. Only general-purpose instances are used. Defalt AMI
        is currently used.
        """
        ec2instance = dict()

        # Note: Unlike other vmms backend, instance type is chosen from
        # the optional instance type attached to image name as
        # "image+instance_type", such as my_course_mage+t2.small.

        # for now , can only do default inst type
        # TODO: choose instance type
        if vm.instance_type is not None:
            ec2instance["instance_type"] = vm.instance_type
        else:
            ec2instance["instance_type"] = config.Config.DEFAULT_INST_TYPE

        # for now, ami is config default
        ec2instance["ami"] = self.img2ami[vm.image].id

        self.log.info("tangoMachineToEC2Instance: %s" % str(ec2instance))
        return ec2instance

    def createKeyPair(self):
        # TODO: SUPPORT
        raise
        # # try to delete the key to avoid collision
        # self.key_pair_path: str = "%s/%s.pem" % (
        #     config.Config.DYNAMIC_SECURITY_KEY_PATH,
        #     self.key_pair_name,
        # )
        # self.deleteKeyPair()
        # key = self.connection.create_key_pair(self.key_pair_name)
        # key.save(config.Config.DYNAMIC_SECURITY_KEY_PATH)
        # # change the SSH_FLAG accordingly
        # self.ssh_flags[1] = self.key_pair_path

    def deleteKeyPair(self):
        # TODO: SUPPORT
        raise
        # self.boto3client.delete_key_pair(self.key_pair_name)
        # # try to delete may not exist key file
        # try:
        #     os.remove(self.key_pair_path)
        # except OSError:
        #     pass

    def createSecurityGroup(self):
        try:
            # Check if the security group already exists
            response = self.boto3client.describe_security_groups(
                Filters=[
                    {
                        "Name": "group-name",
                        "Values": [config.Config.DEFAULT_SECURITY_GROUP],
                    }
                ]
            )
            if response["SecurityGroups"]:
                security_group_id = response["SecurityGroups"][0]["GroupId"]
                return
        except Exception as e:
            self.log.debug("ERROR checking for existing security group: %s", e)

        try:
            response = self.boto3resource.create_security_group(
                GroupName=config.Config.DEFAULT_SECURITY_GROUP,
                Description="Autolab security group - allowing all traffic",
            )
            security_group_id = response["GroupId"]
            self.boto3resource.authorize_security_group_ingress(
                GroupId=security_group_id
            )
        except Exception as e:
            self.log.debug("ERROR in creating security group: %s", e)

    #
    # VMMS API functions
    #
    def initializeVM(self, vm: TangoMachine) -> Literal[0, -1]:
        """initializeVM - Tell EC2 to create a new VM instance.

        Returns a boto.ec2.instance.Instance object.
        Reads from vm's id and name, writes to vm's instance_id and domain_name
        """
        newInstance: Optional[Instance] = None
        # Create the instance and obtain the reservation
        try:
            instanceName = self.instanceName(vm.id, vm.name)
            ec2instance = self.tangoMachineToEC2Instance(vm)
            self.log.debug("instanceName: %s" % instanceName)
            # ensure that security group exists
            self.createSecurityGroup()


            reservation: List[Instance] = self.boto3resource.create_instances(
                ImageId=ec2instance["ami"],
                KeyName=self.key_pair_name,
                SecurityGroups=[config.Config.DEFAULT_SECURITY_GROUP],
                InstanceType=ec2instance["instance_type"],
                MaxCount=1,
                MinCount=1,
                InstanceMarketOptions=
                        {
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
                # TODO: when does this happen?
                raise ValueError("Cannot find new instance for %s" % vm.name)

            # Wait for instance to reach 'running' state
            start_time = time.time()
            while True:

                filters: Sequence[FilterTypeDef] = [
                    {"Name": "instance-state-name", "Values": ["running"]}
                ]
                instances = self.boto3resource.instances.filter(Filters=filters)
                instanceRunning = False

                # reload the state of the new instance
                try_load_instance(newInstance)
                for inst in instances.filter(InstanceIds=[newInstance.id]):
                    self.log.debug(
                        "VM %s %s: is running" % (vm.name, newInstance.id)
                    )
                    instanceRunning = True

                if instanceRunning:
                    break

                if (
                    time.time() - start_time
                    > config.Config.INITIALIZEVM_TIMEOUT
                ):
                    raise ValueError(
                        "VM %s %s: timeout (%d seconds) before reaching 'running' state"
                        % (
                            vm.name,
                            newInstance.id,
                            config.Config.TIMER_POLL_INTERVAL,
                        )
                    )

                self.log.debug(
                    "VM %s %s: Waiting to reach 'running' from 'pending'"
                    % (vm.name, newInstance.id)
                )
                time.sleep(config.Config.TIMER_POLL_INTERVAL)

            # Assign name to EC2 instance
            self.boto3resource.create_tags(
                Resources=[newInstance.id],
                Tags=[{"Key": "Name", "Value": vm.name}],
            )

            self.log.info(
                "VM %s | State %s | Reservation %s | Public DNS Name %s | Public IP Address %s"
                % (
                    instanceName,
                    newInstance.state,
                    reservation,
                    newInstance.public_dns_name,
                    newInstance.public_ip_address,
                )
            )

            # Save domain and id ssigned by EC2 in vm object
            vm.domain_name = newInstance.public_ip_address
            vm.instance_id = newInstance.id
            self.log.debug("VM %s: %s" % (instanceName, newInstance))
            return 0

        except Exception as e:
            self.log.debug("initializeVM Failed: %s" % e)

            # if the new instance exists, terminate it
            if newInstance is not None:
                try:
                    self.boto3resource.instances.filter(
                        InstanceIds=[newInstance.id]
                    ).terminate()
                except Exception as e:
                    self.log.error(
                        "Exception handling failed for %s: %s" % (vm.name, e)
                    )
                    return -1
            return -1

    def waitVM(self, vm, max_secs) -> Literal[0, -1]:
        """waitVM - Wait at most max_secs for a VM to become
        ready. Return error if it takes too long.

        VM is a boto.ec2.instance.Instance object.
        """
        self.log.info("WaitVM: %s %s" % (vm.name, vm.instance_id))

        # test if the vm is still an instance
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
                "ping -c 1 %s" % (domain_name),
                shell=True,
                stdout=open("/dev/null", "w"),
                stderr=subprocess.STDOUT,
            )

            # Wait a bit and then try again if we haven't exceeded
            # timeout
            if instance_down:
                time.sleep(config.Config.TIMER_POLL_INTERVAL)
                elapsed_secs = time.time() - start_time
                if elapsed_secs > max_secs:
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
                ["ssh"]
                + self.ssh_flags
                + ["%s@%s" % (self.ec2User, domain_name), "(:)"],
                max_secs - elapsed_secs,
            )

            self.log.debug("VM %s: ssh returned with %d" % (vm.name, ret))

            if (ret != -1) and (ret != 255):
                return 0

            # Sleep a bit before trying again
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

    def copyIn(self, vm, inputFiles, job_id=None):
        """copyIn - Copy input files to VM
        Args:
        - vm is a TangoMachine object
        - inputFiles is a list of objects with attributes localFile and destFile. 
            localFile is the file on the host, destFile is the file on the VM.
        - job_id is the job id of the job being run on the VM. 
            It is used for logging purposes only.
        """
        self.log.info(
            "copyIn %s - writing files" % self.instanceName(vm.id, vm.name)
        )

        domain_name = self.domainName(vm)

        # Creates directory and add permissions
        result = subprocess.run(
            ["ssh"]
            + self.ssh_flags
            + [
                "%s@%s" % (self.ec2User, domain_name),
                "(mkdir -p autolab && chmod 775 autolab)",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,  # To capture output as strings instead of bytes
        )

        # Print the output and error
        for line in result.stdout:
            self.log.info("%s for job %s" % (line, job_id))
        self.log.info("Return Code: %s, job: %s" % (result.returncode, job_id))
        if result.stderr != 0:
            self.log.info(
                "Standard Error: %s, job: %s" % (result.stderr, job_id)
            )

        # Validate inputFiles structure
        if not inputFiles or not all(
            hasattr(file, "localFile") and hasattr(file, "destFile")
            for file in inputFiles
        ):
            self.log.info(
                "Error: Invalid inputFiles Structure, job: %s" % job_id
            )

        for file in inputFiles:
            self.log.info("%s - %s" % (file.localFile, file.destFile))
            ret = timeout_with_retries(
                ["scp"]
                + self.ssh_flags
                + [
                    file.localFile,
                    "%s@%s:~/autolab/%s"
                    % (self.ec2User, domain_name, file.destFile),
                ],
                config.Config.COPYIN_TIMEOUT,
            )
            if ret != 0:
                self.log.info("Copy-in Error: SCP failure, job: %s" % job_id)
                return ret

        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize, disableNetwork):
        """runJob - Run the make command on a VM using SSH and
        redirect output to file "output".
        """

        domain_name = self.domainName(vm)
        self.log.debug(
            "runJob: Running job on VM %s" % self.instanceName(vm.id, vm.name)
        )
        # Setting ulimits for VM and running job
        runcmd = (
            "/usr/bin/time --output=time.out autodriver \
                -u %d -f %d -t %d -o %d autolab > output 2>&1 "
            % (
                config.Config.VM_ULIMIT_USER_PROC,
                config.Config.VM_ULIMIT_FILE_SIZE,
                runTimeout,
                maxOutputFileSize,
            )
        )
        # no logging for now

        ret = timeout(
            ["ssh"]
            + self.ssh_flags
            + ["%s@%s" % (self.ec2User, domain_name), runcmd],
            runTimeout * 2,
        )

        # runTimeout * 2 is a temporary hack. The driver will handle the timout
        return ret

    def copyOut(self, vm, destFile):
        """copyOut - Copy the file output on the VM to the file
        outputFile on the Tango host.
        """
        self.log.info(
            "copyOut %s - writing to %s",
            self.instanceName(vm.id, vm.name),
            destFile,
        )
        domain_name = self.domainName(vm)

        # Optionally log finer grained runtime info. Adds about 1 sec
        # to the job latency, so we typically skip this.
        if config.Config.LOG_TIMING:
            try:
                # regular expression matcher for error message from cat
                no_file = re.compile("No such file or directory")

                time_info = (
                    subprocess.check_output(
                        ["ssh"]
                        + self.ssh_flags
                        + [
                            "%s@%s" % (self.ec2User, domain_name),
                            "cat time.out",
                        ]
                    )
                    .decode("utf-8")
                    .rstrip("\n")
                )

                # If the output is empty, then ignore it (timing info wasn't
                # collected), otherwise let's log it!
                if no_file.match(time_info):
                    # runJob didn't produce an output file
                    pass

                else:
                    # remove newline character printed in timing info
                    # replaces first '\n' character with a space
                    time_info = re.sub("\n", " ", time_info, count=1)
                    self.log.info("Timing (%s): %s" % (domain_name, time_info))

            except subprocess.CalledProcessError as xxx_todo_changeme:
                # Error copying out the timing data (probably runJob failed)
                re.error = xxx_todo_changeme
                # Error copying out the timing data (probably runJob failed)
                pass

        return timeout(
            ["scp"]
            + self.ssh_flags
            + [
                "%s@%s:output" % (config.Config.EC2_USER_NAME, domain_name),
                destFile,
            ],
            config.Config.COPYOUT_TIMEOUT,
        )

    def destroyVM(self, vm):
        """destroyVM - Removes a VM from the system"""
        self.log.info(
            "destroyVM: %s %s %s %s"
            % (vm.instance_id, vm.name, vm.keep_for_debugging, vm.notes)
        )

        try:
            instances = self.boto3resource.instances.filter(
                InstanceIds=[vm.instance_id]
            )
            if not instances:
                self.log.debug(
                    "no instances found with instance id %s", vm.instance_id
                )
            # Keep the vm and mark with meaningful tags for debugging
            if (
                hasattr(config.Config, "KEEP_VM_AFTER_FAILURE")
                and config.Config.KEEP_VM_AFTER_FAILURE
                and vm.keep_for_debugging
            ):
                self.log.info("Will keep VM %s for further debugging" % vm.name)
                # delete original name tag and replace it with "failed-xyz"
                # add notes tag for test name
                tag = self.boto3resource.Tag(vm.instance_id, "Name", vm.name)
                if tag:
                    tag.delete()
                self.boto3resource.create_tags(
                    Resources=[vm.instance_id],
                    Tags=[
                        {"Key": "Name", "Value": "failed-" + vm.name},
                        {"Key": "Notes", "Value": vm.notes},
                    ],
                )
                return

            instances.terminate()
            # delete dynamically created key
            if not self.useDefaultKeyPair:
                self.deleteKeyPair()
        except Exception as e:
            self.log.error(
                "destroyVM failed: %s for vm %s" % (e, vm.instance_id)
            )

        Ec2SSH.release_vm_semaphore()

    def safeDestroyVM(self, vm):
        return self.destroyVM(vm)

    def getVMs(self):
        """getVMs - Returns the complete list of VMs on this account. Each
        list entry is a boto.ec2.instance.Instance object.
        """
        try:
            vms = list()
            filters = [
                {
                    "Name": "instance-state-name",
                    "Values": ["running", "pending"],
                }
            ]
            # gets all running instances
            instances = self.boto3resource.instances.filter(Filters=filters)
            for instance in instances:
                self.log.debug("instance_id: %s" % instance)

                vm = TangoMachine()
                vm.instance_id = instance.id
                # don't use domain_name for now
                vm.domain_name = None
                vm.id = None

                instName = self.getTag(
                    instance.tags, "Name"
                )  # inst name PREFIX-serial-IMAGE
                # Name tag is the standard form of prefix-serial-image
                if not (
                    instName
                    and re.match("%s-" % config.Config.PREFIX, instName)
                ):
                    self.log.debug(
                        "getVMs: Instance id %s skipped" % vm.instance_id
                    )
                    continue  # instance without name tag or proper prefix

                vm.name = instName
                vm.id = int(instName.split("-")[1])
                vm.pool = instName.split("-")[2]
                vm.name = instName

                # needed for SSH
                if instance.public_ip_address:
                    vm.domain_name = instance.public_ip_address

                vms.append(vm)
                self.log.debug(
                    "getVMs: Instance id %s, name %s"
                    % (vm.instance_id, vm.name)
                )
        except Exception as e:
            self.log.debug("getVMs Failed: %s" % e)

        return vms

    def existsVM(self, vm):
        """existsVM - Checks whether a VM exists in the vmms."""
        # https://boto3.amazonaws.com/v1/documentation/api/latest/guide/migrationec2.html
        filters = [{"Name": "instance-state-name", "Values": ["running"]}]
        # gets all running instances
        instances = self.boto3resource.instances.filter(Filters=filters)
        for instance in instances:
            if instance.instance_id == vm.instance_id:
                self.log.debug(
                    "Found matching instance_id: %s" % (instance.instance_id)
                )
                return True
        # for instance in instances.filter(InstanceIds)
        return False

    def getImages(self):
        """getImages - return a constant; actually use the ami specified in config"""
        return [key for key in self.img2ami]

    # getTag: to do later
    def getTag(self, tagList, tagKey):
        if tagList:
            for tag in tagList:
                if tag["Key"] == tagKey:
                    return tag["Value"]
        return None

    def getPartialOutput(self, vm):
        domain_name = self.domainName(vm)

        runcmd = "head -c %s /home/autograde/output.log" % (
            config.Config.MAX_OUTPUT_FILE_SIZE
        )

        sshcmd = (
            ["ssh"]
            + self.ssh_flags
            + ["%s@%s" % (self.ec2User, domain_name), runcmd]
        )

        output = subprocess.check_output(
            sshcmd, stderr=subprocess.STDOUT
        ).decode("utf-8")

        return output
