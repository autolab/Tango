#
# ec2SSH.py - Implements the Tango VMMS interface to run Tango jobs on Amazon EC2.
#
# ssh and scp to access them.

import subprocess
import os
import re
import time
import logging

import config
from tangoObjects import TangoMachine

import boto3
from botocore.exceptions import ClientError

### added to suppress boto XML output -- Jason Boles
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)

def timeout(command, time_out=1):
    """ timeout - Run a unix command with a timeout. Return -1 on
    timeout, otherwise return the return value from the command, which
    is typically 0 for success, 1-255 for failure.
    """

    # Launch the command
    p = subprocess.Popen(command,
                         stdout=open("/dev/null", 'w'),
                         stderr=subprocess.STDOUT)

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
    """ timeoutWithReturnStatus - Run a Unix command with a timeout,
    until the expected value is returned by the command; On timeout,
    return last error code obtained from the command.
    """
    p = subprocess.Popen(
        command, stdout=open("/dev/null", 'w'), stderr=subprocess.STDOUT)
    t = 0.0
    while (t < time_out):
        ret = p.poll()
        if ret is None:
            time.sleep(config.Config.TIMER_POLL_INTERVAL)
            t += config.Config.TIMER_POLL_INTERVAL
        elif ret == returnValue:
            return ret
        else:
            p = subprocess.Popen(command,
                                 stdout=open("/dev/null", 'w'),
                                 stderr=subprocess.STDOUT)
            return ret

class Ec2SSH:
    _SSH_FLAGS = ["-i", config.Config.SECURITY_KEY_PATH,
                  "-o", "StrictHostKeyChecking no",
                  "-o", "GSSAPIAuthentication no"]
    _SECURITY_KEY_PATH_INDEX_IN_SSH_FLAGS = 1

    def __init__(self, accessKeyId=None, accessKey=None, ec2User=None):
        """ log - logger for the instance
        connection - EC2Connection object that stores the connection
        info to the EC2 network
        instance - Instance object that stores information about the
        VM created
        """

        self.log = logging.getLogger("Ec2SSH-" + str(os.getpid()))
        self.log.info("init Ec2SSH")

        self.ssh_flags = Ec2SSH._SSH_FLAGS
        self.ec2User = ec2User if ec2User else config.Config.EC2_USER_NAME
        self.useDefaultKeyPair = False if accessKeyId else True

        self.img2ami = {}
        images = []

        try:
            self.boto3client = boto3.client("ec2", config.Config.EC2_REGION,
                                            aws_access_key_id=accessKeyId,
                                            aws_secret_access_key=accessKey)
            self.boto3resource = boto3.resource("ec2", config.Config.EC2_REGION)

            images = self.boto3resource.images.filter(Owners=["self"])
        except Exception as e:
            self.log.error("Ec2SSH init Failed: %s"% e)
            raise  # serious error

        # Note: By convention, all usable images to Tango must have "Name" tag
        # whose value is the image name, such as xyz or xyz.img (older form).
        # xyz is also the preallocator pool name for vms using this image, if
        # instance type is not specified.

        for image in images:
            if image.tags:
                for tag in image.tags:
                    if tag["Key"] == "Name":
                        if tag["Value"]:
                            if tag["Value"] in self.img2ami:
                                self.log.info("Ignore %s for duplicate name tag %s" %
                                              (image.id, tag["Value"]))
                            else:
                                self.img2ami[tag["Value"]] = image
                                self.log.info("Found image: %s with name tag %s" %
                                              (image.id, tag["Value"]))

        imageAMIs = [item.id for item in images]
        taggedAMIs = [self.img2ami[key].id for key in self.img2ami]
        ignoredAMIs = list(set(imageAMIs) - set(taggedAMIs))
        if (len(ignoredAMIs) > 0):
            self.log.info("Ignored images %s for lack of or ill-formed name tag" %
                          str(ignoredAMIs))

    #
    # VMMS helper methods
    #

    def instanceName(self, id, pool):
        """ instanceName - Constructs a VM instance name. Always use
        this function when you need a VM instance name, or use vm.name
        """
        return "%s-%d-%s" % (config.Config.PREFIX, id, pool)

    def keyPairName(self, id, name):
        """ keyPairName - Constructs a unique key pair name.
        """
        return "%s-%d-%s" % (config.Config.PREFIX, id, name)

    def domainName(self, vm):
        """ Returns the domain name that is stored in the vm
        instance.
        """
        return vm.domain_name

    def tangoMachineToEC2Instance(self, vm):
        """ tangoMachineToEC2Instance - returns an object with EC2 instance
        type and AMI. Only general-purpose instances are used. Defalt AMI
        is currently used.
        """
        ec2instance = dict()

        # Note: Unlike other vmms backend, instance type is chosen from
        # the optional instance type attached to image name as
        # "image+instance_type", such as my_course_mage+t2.small.

        ec2instance['instance_type'] = config.Config.DEFAULT_INST_TYPE
        if vm.instance_type:
            ec2instance['instance_type'] = vm.instance_type

        ec2instance['ami'] = self.img2ami[vm.image].id
        self.log.info("tangoMachineToEC2Instance: %s" % str(ec2instance))

        return ec2instance

    def createKeyPair(self):
        # try to delete the key to avoid collision
        self.key_pair_path = "%s/%s.pem" % \
                             (config.Config.DYNAMIC_SECURITY_KEY_PATH,
                              self.key_pair_name)
        self.deleteKeyPair()
        response = self.boto3client.create_key_pair(KeyName=self.key_pair_name)
        keyFile = open(self.key_pair_path, "w+")
        keyFile.write(response["KeyMaterial"])
        os.chmod(self.key_pair_path, 0o600)  # read only by owner
        keyFile.close()

        # change the SSH_FLAG accordingly
        self.ssh_flags[Ec2SSH._SECURITY_KEY_PATH_INDEX_IN_SSH_FLAGS] = self.key_pair_path
        return self.key_pair_path

    def deleteKeyPair(self):
        self.boto3client.delete_key_pair(KeyName=self.key_pair_name)
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
                Description="Autolab security group - allowing all traffic")
            security_group_id = response['GroupId']
            self.boto3resource.authorize_security_group_ingress(
              GroupId=security_group_id)
        except ClientError as e:
            # security group may have been created already
            pass

    #
    # VMMS API functions
    #

    def initializeVM(self, vm):
        """ initializeVM - Tell EC2 to create a new VM instance.  return None on failure

        Returns a boto.ec2.instance.Instance object.
        """
        # Create the instance and obtain the reservation
        newInstance = None
        try:
            vm.name = self.instanceName(vm.id, vm.pool)
            ec2instance = self.tangoMachineToEC2Instance(vm)
            self.log.info("initializeVM: %s %s" % (vm.name, str(ec2instance)))
            # ensure that security group exists
            self.createSecurityGroup()
            if self.useDefaultKeyPair:
                self.key_pair_name = config.Config.SECURITY_KEY_NAME
                self.key_pair_path = config.Config.SECURITY_KEY_PATH
            else:
                self.key_pair_name = self.keyPairName(vm.id, vm.name)
                self.key_pair_path = self.createKeyPair()

            reservation = self.boto3resource.create_instances(ImageId=ec2instance['ami'],
                                                           InstanceType=ec2instance['instance_type'],
                                                           KeyName=self.key_pair_name,
                                                           SecurityGroups=[
                                                             config.Config.DEFAULT_SECURITY_GROUP],
                                                           MaxCount=1,
                                                           MinCount=1)

            # Sleep for a while to prevent random transient errors observed
            # when the instance is not available yet
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

            newInstance = reservation[0]
            if newInstance:
                # Assign name to EC2 instance
                self.boto3resource.create_tags(Resources=[newInstance.id],
                                            Tags=[{"Key": "Name", "Value": vm.name}])
                self.log.info("new instance %s created with name tag %s" %
                              (newInstance.id, vm.name))
            else:
                raise ValueError("cannot find new instance for %s" % vm.name)

            # Wait for instance to reach 'running' state
            start_time = time.time()
            while True:
                # Note: You'd think we should be able to read the state from the
                # instance but that turns out not working.  So we round up all
                # running intances and find our instance by instance id
              
                filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
                instances = self.boto3resource.instances.filter(Filters=filters)
                instanceRunning = False

                newInstance.load()  # reload the state of the instance
                for inst in instances.filter(InstanceIds=[newInstance.id]):
                    self.log.debug("VM %s: is running %s" % (vm.name, newInstance.id))
                    instanceRunning = True

                if instanceRunning:
                    break

                if time.time() - start_time > config.Config.INITIALIZEVM_TIMEOUT:
                    raise ValueError("VM %s: timeout (%d seconds) before reaching 'running' state" %
                                     (vm.name, config.Config.TIMER_POLL_INTERVAL))

                self.log.debug("VM %s: Waiting to reach 'running' from 'pending'" % vm.name)
                time.sleep(config.Config.TIMER_POLL_INTERVAL)
            # end of while loop

            self.log.info(
                "VM %s | State %s | Reservation %s | Public DNS Name %s | Public IP Address %s" %
                (vm.name,
                 newInstance.state,
                 reservation,
                 newInstance.public_dns_name,
                 newInstance.public_ip_address))

            # Save domain and id ssigned by EC2 in vm object
            vm.domain_name = newInstance.public_ip_address
            vm.instance_id = newInstance.id
            self.log.debug("VM %s: %s" % (vm.name, newInstance))
            return vm

        except Exception as e:
            self.log.error("initializeVM Failed: %s" % e)
            if newInstance:
                self.boto3resource.instances.filter(InstanceIds=[newInstance.id]).terminate()
            return None

    def waitVM(self, vm, max_secs):
        """ waitVM - Wait at most max_secs for a VM to become
        ready. Return error if it takes too long.

        VM is a boto.ec2.instance.Instance object.
        """

        self.log.info("WaitVM: %s %s" % (vm.name, vm.instance_id))

        # test if the vm is still an instance
        if not self.existsVM(vm):
            self.log.info("VM %s: no longer an instance" % vm.name)
            return -1

        # First, wait for ping to the vm instance to work
        instance_down = 1
        start_time = time.time()
        domain_name = self.domainName(vm)
        self.log.info("WaitVM: pinging %s %s" % (domain_name, vm.name))
        while instance_down:
            instance_down = subprocess.call("ping -c 1 %s" % (domain_name),
                                            shell=True,
                                            stdout=open('/dev/null', 'w'),
                                            stderr=subprocess.STDOUT)

            # Wait a bit and then try again if we haven't exceeded
            # timeout
            if instance_down:
                time.sleep(config.Config.TIMER_POLL_INTERVAL)
                elapsed_secs = time.time() - start_time
                if (elapsed_secs > max_secs):
                    self.log.debug("WAITVM_TIMEOUT: %s" % vm.id)
                    return -1

        # The ping worked, so now wait for SSH to work before
        # declaring that the VM is ready
        self.log.debug("VM %s: ping completed" % (vm.name))
        while(True):

            elapsed_secs = time.time() - start_time

            # Give up if the elapsed time exceeds the allowable time
            if elapsed_secs > max_secs:
                self.log.info(
                    "VM %s: SSH timeout after %d secs" % (vm.name, elapsed_secs))
                return -1

            # If the call to ssh returns timeout (-1) or ssh error
            # (255), then success. Otherwise, keep trying until we run
            # out of time.

            ret = timeout(["ssh"] + self.ssh_flags +
                          ["%s@%s" % (self.ec2User, domain_name),
                           "(:)"], max_secs - elapsed_secs)

            self.log.debug("VM %s: ssh returned with %d" % (vm.name, ret))

            if (ret != -1) and (ret != 255):
                return 0

            # Sleep a bit before trying again
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

    def copyIn(self, vm, inputFiles):
        """ copyIn - Copy input files to VM
        """
        domain_name = self.domainName(vm)

        # Create a fresh input directory
        ret = subprocess.call(["ssh"] + self.ssh_flags +
                              ["%s@%s" % (config.Config.EC2_USER_NAME, domain_name),
                               "(rm -rf autolab; mkdir autolab)"])

        # Copy the input files to the input directory
        for file in inputFiles:
            ret = timeout(["scp"] +
                          self.ssh_flags +
                          [file.localFile, "%s@%s:autolab/%s" %
                           (config.Config.EC2_USER_NAME, domain_name, file.destFile)],
                            config.Config.COPYIN_TIMEOUT)
            if ret != 0:
                return ret

        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize):
        """ runJob - Run the make command on a VM using SSH and
        redirect output to file "output".
        """
        domain_name = self.domainName(vm)
        self.log.debug("runJob: Running job on VM %s" % vm.name)

        # Setting arguments for VM and running job
        runcmd = "/usr/bin/time --output=time.out autodriver \
        -u %d -f %d -t %d -o %d " % (
          config.Config.VM_ULIMIT_USER_PROC,
          config.Config.VM_ULIMIT_FILE_SIZE,
          runTimeout,
          maxOutputFileSize)
        if hasattr(config.Config, 'AUTODRIVER_LOGGING_TIME_ZONE') and \
           config.Config.AUTODRIVER_LOGGING_TIME_ZONE:
            runcmd = runcmd + ("-z %s " % config.Config.AUTODRIVER_LOGGING_TIME_ZONE)
        if hasattr(config.Config, 'AUTODRIVER_TIMESTAMP_INTERVAL') and \
           config.Config.AUTODRIVER_TIMESTAMP_INTERVAL:
            runcmd = runcmd + ("-i %d " % config.Config.AUTODRIVER_TIMESTAMP_INTERVAL)
        runcmd = runcmd + "autolab &> output"

        # runTimeout * 2 is a conservative estimate.
        # autodriver handles timeout on the target vm.
        ret = timeout(["ssh"] + self.ssh_flags +
                       ["%s@%s" % (config.Config.EC2_USER_NAME, domain_name), runcmd], runTimeout * 2)
        return ret

    def copyOut(self, vm, destFile):
        """ copyOut - Copy the file output on the VM to the file
        outputFile on the Tango host.
        """
        domain_name = self.domainName(vm)

        # Optionally log finer grained runtime info. Adds about 1 sec
        # to the job latency, so we typically skip this.
        if config.Config.LOG_TIMING:
            try:
                # regular expression matcher for error message from cat
                no_file = re.compile('No such file or directory')

                time_info = subprocess.check_output(
                    ['ssh'] +
                    self.ssh_flags +
                    [
                        "%s@%s" % (config.Config.EC2_USER_NAME, domain_name),
                        'cat time.out']).rstrip('\n')

                # If the output is empty, then ignore it (timing info wasn't
                # collected), otherwise let's log it!
                if no_file.match(time_info):
                    # runJob didn't produce an output file
                    pass

                else:
                    # remove newline character printed in timing info
                    # replaces first '\n' character with a space
                    time_info = re.sub('\n', ' ', time_info, count=1)
                    self.log.info('Timing (%s): %s' % (domain_name, time_info))

            except subprocess.CalledProcessError as xxx_todo_changeme:
                # Error copying out the timing data (probably runJob failed)
                re.error = xxx_todo_changeme
                # Error copying out the timing data (probably runJob failed)
                pass

        return timeout(["scp"] + self.ssh_flags +
                       ["%s@%s:output" % (config.Config.EC2_USER_NAME, domain_name), destFile],
                       config.Config.COPYOUT_TIMEOUT)

    def destroyVM(self, vm):
        """ destroyVM - Removes a VM from the system
        """

        self.log.info("destroyVM: %s %s %s %s" %
                      (vm.instance_id, vm.name, vm.keepForDebugging, vm.notes))

        try:
            # Keep the vm and mark with meaningful tags for debugging
            if hasattr(config.Config, 'KEEP_VM_AFTER_FAILURE') and \
               config.Config.KEEP_VM_AFTER_FAILURE and vm.keepForDebugging:
                self.log.info("Will keep VM %s for further debugging" % vm.name)
                instance = self.boto3resource.Instance(vm.instance_id)
                # delete original name tag and replace it with "failed-xyz"
                # add notes tag for test name
                tag = self.boto3resource.Tag(vm.instance_id, "Name", vm.name)
                if tag:
                    tag.delete()
                instance.create_tags(Tags=[{"Key": "Name", "Value": "failed-" + vm.name}])
                instance.create_tags(Tags=[{"Key": "Notes", "Value": vm.notes}])
                return

            self.boto3resource.instances.filter(InstanceIds=[vm.instance_id]).terminate()
            # delete dynamically created key
            if not self.useDefaultKeyPair:
                self.deleteKeyPair()

        except Exception as e:
            self.log.error("destroyVM init Failed: %s for vm %s" % (e, vm.instance_id))
            pass

    def safeDestroyVM(self, vm):
        return self.destroyVM(vm)

    # return None or tag value if key exists
    def getTag(self, tagList, tagKey):
        if tagList:
            for tag in tagList:
                if tag["Key"] == tagKey:
                    return tag["Value"]
        return None

    def getVMs(self):
        """ getVMs - Returns the running or pending VMs on this account. Each
        list entry is a boto.ec2.instance.Instance object.
        """

        try:
            vms = list()
            filters=[{'Name': 'instance-state-name', 'Values': ['running', 'pending']}]

            for inst in self.boto3resource.instances.filter(Filters=filters):
                vm = TangoMachine()  # make a Tango internal vm structure
                vm.instance_id = inst.id
                vm.id = None  # the serial number as in inst name PREFIX-serial-IMAGE
                vm.domain_name = None

                instName = self.getTag(inst.tags, "Name")
                # Name tag is the standard form of prefix-serial-image
                if not (instName and re.match("%s-" % config.Config.PREFIX, instName)):
                    self.log.debug('getVMs: Instance id %s skipped' % vm.instance_id)
                    continue  # instance without name tag or proper prefix

                vm.id = int(instName.split("-")[1])
                vm.pool = instName.split("-")[2]
                vm.name = instName
                if inst.public_ip_address:
                    vm.domain_name = inst.public_ip_address
                vms.append(vm)

                self.log.debug('getVMs: Instance id %s, name %s' %
                               (vm.instance_id, vm.name))
            return vms

        except Exception as e:
            self.log.debug("getVMs Failed: %s" % e)

    def existsVM(self, vm):
        """ existsVM - Checks whether a VM exists in the vmms. Internal use.
        """

        filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
        instances = self.boto3resource.instances.filter(Filters=filters)
        for inst in instances.filter(InstanceIds=[vm.instance_id]):
            self.log.debug("VM %s %s: exists and running" % (vm.instance_id, vm.name))
            return True
        return False

    def getImages(self):
        """ getImages - return a constant; actually use the ami specified in config
        """
        self.log.info("getImages: %s" % str(list(self.img2ami.keys())))
        return list(self.img2ami.keys())
