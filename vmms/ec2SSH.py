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
# TODO: this currently probably does not work on Python 3 yet

import subprocess
import os
import re
import time
import logging

import config

import boto3

import pytz

from tangoObjects import TangoMachine


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


#
# User defined exceptions
#
# ec2Call() exception


class ec2CallError(Exception):
    pass


class Ec2SSH(object):
    _SSH_FLAGS = [
        "-i",
        config.Config.SECURITY_KEY_PATH,
        "-o",
        "StrictHostKeyChecking no",
        "-o",
        "GSSAPIAuthentication no",
    ]

    def __init__(self, accessKeyId=None, accessKey=None):
        """log - logger for the instance
        connection - EC2Connection object that stores the connection
        info to the EC2 network
        instance - Instance object that stores information about the
        VM created
        """
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

        # create boto3resource

        self.img2ami = {}
        self.images = []
        try:
            self.boto3resource = boto3.resource("ec2", config.Config.EC2_REGION)
            # idk if works
            self.boto3client = boto3.client("ec2", config.Config.EC2_REGION)

            # Get images from ec2
            images = self.boto3resource.images.filter(Owners=["self"])
            self.log.debug("IMAGES: ")
            for image in images:
                self.log.debug("Image ID: %s", image.id)
                self.log.debug("Name: %s", image.name)
                self.log.debug("State: %s", image.state)
                self.log.debug("Creation Date: %s", image.creation_date)
                self.log.debug("Public: %s", str(image.public))
                self.log.debug("Architecture: %s", image.architecture)
                self.log.debug("Description: %s", image.description)
                self.log.debug("Tags: %s", str(image.tags))
                self.log.debug("Root Device Type: %s", image.root_device_type)
                self.log.debug("Virtualization Type: %s", image.virtualization_type)
                self.log.debug("------------------------------------------------")
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
        self.log.info("imageAMIs")
        self.log.info(imageAMIs)
        self.log.info("taggedAMIs")
        self.log.info(taggedAMIs)
        self.log.info("ignoredAMIs")
        self.log.info(ignoredAMIs)
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

    def tangoMachineToEC2Instance(self, vm):
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
        ec2instance["instance_type"] = config.Config.DEFAULT_INST_TYPE

        # for now, ami is config default
        ec2instance["ami"] = config.Config.DEFAULT_AMI

        self.log.info("tangoMachineToEC2Instance: %s" % str(ec2instance))
        return ec2instance

    def createKeyPair(self):
        # TODO: SUPPORT
        raise
        # try to delete the key to avoid collision
        self.key_pair_path = "%s/%s.pem" % (
            config.Config.DYNAMIC_SECURITY_KEY_PATH,
            self.key_pair_name,
        )
        self.deleteKeyPair()
        key = self.connection.create_key_pair(self.key_pair_name)
        key.save(config.Config.DYNAMIC_SECURITY_KEY_PATH)
        # change the SSH_FLAG accordingly
        self.ssh_flags[1] = self.key_pair_path

    def deleteKeyPair(self):
        # TODO: SUPPORT
        raise
        self.boto3client.delete_key_pair(self.key_pair_name)
        # try to delete may not exist key file
        try:
            os.remove(self.key_pair_path)
        except OSError:
            pass

    def createSecurityGroup(self):
        # Create may-exist security group
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
    def initializeVM(self, vm):
        """initializeVM - Tell EC2 to create a new VM instance.

        Returns a boto.ec2.instance.Instance object.
        """
        newInstance = None
        # Create the instance and obtain the reservation
        try:
            instanceName = self.instanceName(vm.id, vm.name)
            ec2instance = self.tangoMachineToEC2Instance(vm)
            self.log.debug("instanceName: %s" % instanceName)
            # ensure that security group exists
            self.createSecurityGroup()
            if self.useDefaultKeyPair:
                self.key_pair_name = config.Config.SECURITY_KEY_NAME
                self.key_pair_path = config.Config.SECURITY_KEY_PATH
            else:
                # TODO: SUPPORT
                raise
                self.key_pair_name = self.keyPairName(vm.id, vm.name)
                self.createKeyPair()

            reservation = self.boto3resource.create_instances(
                ImageId=ec2instance["ami"],
                KeyName=self.key_pair_name,
                SecurityGroups=[config.Config.DEFAULT_SECURITY_GROUP],
                InstanceType=ec2instance["instance_type"],
                MaxCount=1,
                MinCount=1,
            )

            # Sleep for a while to prevent random transient errors observed
            # when the instance is not available yet
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

            # reservation is a list of instances created. there is only
            # one instance created so get index 0.
            newInstance = reservation[0]
            if not newInstance:
                raise ValueError("Cannot find new instance for %s" % vm.name)

            # Wait for instance to reach 'running' state
            start_time = time.time()
            while True:

                filters = [{"Name": "instance-state-name", "Values": ["running"]}]
                instances = self.boto3resource.instances.filter(Filters=filters)
                instanceRunning = False

                # reload the state of the new instance
                newInstance.load()
                for inst in instances.filter(InstanceIds=[newInstance.id]):
                    self.log.debug("VM %s %s: is running" % (vm.name, newInstance.id))
                    instanceRunning = True

                if instanceRunning:
                    break

                if time.time() - start_time > config.Config.INITIALIZEVM_TIMEOUT:
                    raise ValueError(
                        "VM %s %s: timeout (%d seconds) before reaching 'running' state"
                        % (vm.name, newInstance.id, config.Config.TIMER_POLL_INTERVAL)
                    )

                self.log.debug(
                    "VM %s %s: Waiting to reach 'running' from 'pending'"
                    % (vm.name, newInstance.id)
                )
                time.sleep(config.Config.TIMER_POLL_INTERVAL)

            # Assign name to EC2 instance
            self.boto3resource.create_tags(
                Resources=[newInstance.id], Tags=[{"Key": "Name", "Value": vm.name}]
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
            return vm

        except Exception as e:
            self.log.debug("initializeVM Failed: %s" % e)

            # if the new instance exists, terminate it
            if newInstance:
                try:
                    self.boto3resource.instances.filter(
                        InstanceIds=[newInstance.id]
                    ).terminate()
                except Exception as e:
                    self.log.error(
                        "Exception handling failed for %s: %s" % (vm.name, e)
                    )
                    return None
            return None

    def waitVM(self, vm, max_secs):
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

    def copyIn(self, vm, inputFiles):
        """copyIn - Copy input files to VM"""
        self.log.info("copyIn %s - writing files" % self.instanceName(vm.id, vm.name))

        domain_name = self.domainName(vm)

        result = subprocess.run(
            ["ssh"]
            + self.ssh_flags
            + [
                "%s@%s" % (self.ec2User, domain_name),
                "(mkdir autolab)",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,  # To capture output as strings instead of bytes
        )

        # Print the output and error
        for line in result.stdout:
            self.log.info("%s" % line)
        self.log.info("Standard Error: %s" % result.stderr)
        self.log.info("Return Code: %s" % result.returncode)

        # Copy the input files to the input directory
        for file in inputFiles:
            self.log.info("%s - %s" % (file.localFile, file.destFile))
            ret = timeout(
                ["scp"]
                + self.ssh_flags
                + [
                    file.localFile,
                    "%s@%s:~/autolab/%s" % (self.ec2User, domain_name, file.destFile),
                ],
                config.Config.COPYIN_TIMEOUT,
            )
            if ret != 0:
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
            ["ssh"] + self.ssh_flags + ["%s@%s" % (self.ec2User, domain_name), runcmd],
            runTimeout * 2,
        )

        # runTimeout * 2 is a temporary hack. The driver will handle the timout
        return ret

    def copyOut(self, vm, destFile):
        """copyOut - Copy the file output on the VM to the file
        outputFile on the Tango host.
        """
        self.log.info(
            "copyOut %s - writing to %s", self.instanceName(vm.id, vm.name), destFile
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
            + ["%s@%s:output" % (config.Config.EC2_USER_NAME, domain_name), destFile],
            config.Config.COPYOUT_TIMEOUT,
        )

    def destroyVM(self, vm):
        """destroyVM - Removes a VM from the system"""
        self.log.info("destroyVM: %s %s" % (vm.instance_id, vm.name))

        try:
            instances = self.boto3resource.instances.filter(
                InstanceIds=[vm.instance_id]
            )
            if not instances:
                self.log.debug("no instances found with instance id %s", vm.instance_id)
            instances.terminate()
            # delete dynamically created key
            if not self.useDefaultKeyPair:
                self.deleteKeyPair()
        except Exception as e:
            self.log.error("destroyVM failed: %s for vm %s" % (e, vm.instance_id))

    def safeDestroyVM(self, vm):
        return self.destroyVM(vm)

    def getVMs(self):
        """getVMs - Returns the complete list of VMs on this account. Each
        list entry is a boto.ec2.instance.Instance object.
        """
        try:
            vms = list()
            filters = [
                {"Name": "instance-state-name", "Values": ["running", "pending"]}
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
                if not (instName and re.match("%s-" % config.Config.PREFIX, instName)):
                    self.log.debug("getVMs: Instance id %s skipped" % vm.instance_id)
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
                    "getVMs: Instance id %s, name %s" % (vm.instance_id, vm.name)
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
        return ["autograding_image"]

    # getTag: to do later
    def getTag(self, tagList, tagKey):
        if tagList:
            for tag in tagList:
                if tag["Key"] == tagKey:
                    return tag["Value"]
        return None
    
    def getPartialOutput(self, vm):
        domain_name = self.domainName(vm)

        runcmd = "head -c %s /home/autograde/output.log" % (config.Config.MAX_OUTPUT_FILE_SIZE)

        sshcmd = ["ssh"] + self.ssh_flags + ["%s@%s" % (self.ec2User, domain_name), runcmd]

        output = subprocess.check_output(
            sshcmd, stderr=subprocess.STDOUT
        ).decode("utf-8")

        self.log.debug(output)

        return output

