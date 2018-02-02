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
import subprocess
import os
import re
import time
import logging

import config

import boto
from boto import ec2
import boto3

from tangoObjects import TangoMachine

### added to suppress boto XML output -- Jason Boles
logging.getLogger('boto').setLevel(logging.CRITICAL)
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

#
# User defined exceptions
#
# ec2Call() exception


class ec2CallError(Exception):
    pass


class Ec2SSH:
    _SSH_FLAGS = ["-i", config.Config.SECURITY_KEY_PATH,
                  "-o", "StrictHostKeyChecking no",
                  "-o", "GSSAPIAuthentication no"]

    def __init__(self, accessKeyId=None, accessKey=None):
        """ log - logger for the instance
        connection - EC2Connection object that stores the connection
        info to the EC2 network
        instance - Instance object that stores information about the
        VM created
        """

        self.log = logging.getLogger("Ec2SSH-" + str(os.getpid()))

        self.log.info("init Ec2SSH")

        self.ssh_flags = Ec2SSH._SSH_FLAGS
        if accessKeyId:
            self.connection = ec2.connect_to_region(config.Config.EC2_REGION,
                    aws_access_key_id=accessKeyId, aws_secret_access_key=accessKey)
            self.useDefaultKeyPair = False
        else:
            self.connection = ec2.connect_to_region(config.Config.EC2_REGION)
            self.useDefaultKeyPair = True

        self.boto3connection = boto3.client("ec2", config.Config.EC2_REGION)
        self.boto3resource = boto3.resource("ec2", config.Config.EC2_REGION)

        # Use boto3 to read images.  Find the "Name" tag and use it as key to
        # build a map from "Name tag" to boto3's image structure.
        # The code is currently using boto 2 for most of the work and we don't
        # have the energy to upgrade it yet.  So boto and boto3 are used together.

        client = boto3.client("ec2", config.Config.EC2_REGION)
        images = client.describe_images(Owners=["self"])["Images"]
        self.img2ami = {}
        for image in images:
            if "Tags" not in image:
                continue
            tags = image["Tags"]
            for tag in tags:
                if "Key" in tag and tag["Key"] == "Name":
                    if not (tag["Value"] and tag["Value"].endswith(".img")):
                        self.log.info("Ignore %s for ill-formed name tag %s" %
                                      (image["ImageId"], tag["Value"]))
                        continue
                    if tag["Value"] in self.img2ami:
                        self.log.info("Ignore %s for duplicate name tag %s" %
                                      (image["ImageId"], tag["Value"]))
                        continue

                    self.img2ami[tag["Value"]] = image
                    self.log.info("Found image: %s %s %s" % (tag["Value"], image["ImageId"], image["Name"]))

        imageAmis = [item["ImageId"] for item in images]
        taggedAmis = [self.img2ami[key]["ImageId"] for key in self.img2ami]
        ignoredAmis = list(set(imageAmis) - set(taggedAmis))
        if (len(ignoredAmis) > 0):
            self.log.info("Ignored amis %s due to lack of proper name tag" % str(ignoredAmis))

        # preliminary code for auto scaling group (configured by EC2_AUTO_SCALING_GROUP_NAME)
        # Here we get the pointer to the group, if any.
        # When an instance is created, it's attached to the group.
        # When an instance is terminated, it's detached.
        self.asg = None
        self.auto_scaling_group = None
        self.auto_scaling_group_name = None
        if hasattr(config.Config, 'EC2_AUTO_SCALING_GROUP_NAME') and config.Config.EC2_AUTO_SCALING_GROUP_NAME:
            self.asg = boto3.client("autoscaling", config.Config.EC2_REGION)
            groups = self.asg.describe_auto_scaling_groups(AutoScalingGroupNames=[config.Config.EC2_AUTO_SCALING_GROUP_NAME])
            if len(groups['AutoScalingGroups']) == 1:
                self.auto_scaling_group = groups['AutoScalingGroups'][0]
                self.auto_scaling_group_name = config.Config.EC2_AUTO_SCALING_GROUP_NAME
                self.log.info("Use aws auto scaling group %s" % self.auto_scaling_group_name)

                instances = self.asg.describe_auto_scaling_instances()['AutoScalingInstances']
            else:
                self.log.info("Cannot find auto scaling group %s" % config.Config.EC2_AUTO_SCALING_GROUP_NAME)

    def instanceName(self, id, name):
        """ instanceName - Constructs a VM instance name. Always use
        this function when you need a VM instance name. Never generate
        instance names manually.
        """
        return "%s-%d-%s" % (config.Config.PREFIX, id, name)

    def keyPairName(self, id, name):
        """ keyPairName - Constructs a unique key pair name.
        """
        return "%s-%d-%s" % (config.Config.PREFIX, id, name)

    def domainName(self, vm):
        """ Returns the domain name that is stored in the vm
        instance.
        """
        return vm.domain_name
    #
    # VMMS helper methods
    #

    def tangoMachineToEC2Instance(self, vm):
        """ tangoMachineToEC2Instance - returns an object with EC2 instance
        type and AMI. Only general-purpose instances are used. Defalt AMI
        is currently used.
        """
        ec2instance = dict()

        memory = vm.memory  # in Kbytes
        cores = vm.cores

        if (cores == 1 and memory <= 613 * 1024):
            ec2instance['instance_type'] = 't2.micro'
        elif (cores == 1 and memory <= 1.7 * 1024 * 1024):
            ec2instance['instance_type'] = 'm1.small'
        elif (cores == 1 and memory <= 3.75 * 1024 * 1024):
            ec2instance['instance_type'] = 'm3.medium'
        elif (cores == 2):
            ec2instance['instance_type'] = 'm3.large'
        elif (cores == 4):
            ec2instance['instance_type'] = 'm3.xlarge'
        elif (cores == 8):
            ec2instance['instance_type'] = 'm3.2xlarge'
        else:
            ec2instance['instance_type'] = config.Config.DEFAULT_INST_TYPE

        ec2instance['ami'] = self.img2ami[vm.name + ".img"]["ImageId"]
        self.log.info("tangoMachineToEC2Instance: %s" % str(ec2instance))

        return ec2instance

    def createKeyPair(self):
        # try to delete the key to avoid collision
        self.key_pair_path = "%s/%s.pem" % \
            (config.Config.DYNAMIC_SECURITY_KEY_PATH, self.key_pair_name)
        self.deleteKeyPair()
        key = self.connection.create_key_pair(self.key_pair_name)
        key.save(config.Config.DYNAMIC_SECURITY_KEY_PATH)
        # change the SSH_FLAG accordingly
        self.ssh_flags[1] = self.key_pair_path

    def deleteKeyPair(self):
        self.connection.delete_key_pair(self.key_pair_name)
        # try to delete may not exist key file
        try:
            os.remove(self.key_pair_path)
        except OSError:
            pass

    def createSecurityGroup(self):
        # Create may-exist security group
        try:
            security_group = self.connection.create_security_group(
                config.Config.DEFAULT_SECURITY_GROUP,
                "Autolab security group - allowing all traffic")
            # All ports, all traffics, all ips
            security_group.authorize(from_port=None,
                to_port=None, ip_protocol='-1', cidr_ip='0.0.0.0/0')
        except boto.exception.EC2ResponseError:
            pass

    def getInstanceByReservationId(self, reservationId):
        for inst in self.connection.get_all_instances():
            if inst.id == reservationId:
                return inst.instances.pop()
        return None

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
            instanceName = self.instanceName(vm.id, vm.name)
            ec2instance = self.tangoMachineToEC2Instance(vm)
            self.log.info("initializeVM: %s %s" % (instanceName, str(ec2instance)))
            # ensure that security group exists
            self.createSecurityGroup()
            if self.useDefaultKeyPair:
                self.key_pair_name = config.Config.SECURITY_KEY_NAME
                self.key_pair_path = config.Config.SECURITY_KEY_PATH
            else:
                self.key_pair_name = self.keyPairName(vm.id, vm.name)
                self.createKeyPair()

            reservation = self.connection.run_instances(
                ec2instance['ami'],
                key_name=self.key_pair_name,
                security_groups=[
                    config.Config.DEFAULT_SECURITY_GROUP],
                instance_type=ec2instance['instance_type'])

            # Sleep for a while to prevent random transient errors observed
            # when the instance is not available yet
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

            newInstance = self.getInstanceByReservationId(reservation.id)
            if newInstance:
                # Assign name to EC2 instance
                self.connection.create_tags([newInstance.id], {"Name": instanceName})
                self.log.info("new instance created %s" % newInstance)
            else:
                raise ValueError("cannot find new instance for %s" % instanceName)

            # Wait for instance to reach 'running' state
            start_time = time.time()
            while True:
                elapsed_secs = time.time() - start_time

                newInstance = self.getInstanceByReservationId(reservation.id)
                if not newInstance:
                    raise ValueError("cannot obtain aws instance for %s" % instanceName)

                if newInstance.state == "pending":
                    if elapsed_secs > config.Config.INITIALIZEVM_TIMEOUT:
                        raise ValueError("VM %s: timeout (%d seconds) before reaching 'running' state" %
                                         (instanceName, config.Config.TIMER_POLL_INTERVAL))

                    self.log.debug("VM %s: Waiting to reach 'running' from 'pending'" % instanceName)
                    time.sleep(config.Config.TIMER_POLL_INTERVAL)
                    continue

                if newInstance.state == "running":
                    self.log.debug("VM %s: has reached 'running' state in %d seconds" %
                                   (instanceName, elapsed_secs))
                    break

                raise ValueError("VM %s: quit waiting when seeing state '%s' after %d seconds" %
                                 (instanceName, newInstance.state, elapsed_secs))
            # end of while loop

            self.log.info(
                "VM %s | State %s | Reservation %s | Public DNS Name %s | Public IP Address %s" %
                (instanceName,
                 newInstance.state,
                 reservation.id,
                 newInstance.public_dns_name,
                 newInstance.ip_address))

            if self.auto_scaling_group:
                self.asg.attach_instances(InstanceIds=[newInstance.id],
                                          AutoScalingGroupName=self.auto_scaling_group_name)
                self.log.info("attach new instance %s to auto scaling group" % newInstance.id)

            # Save domain and id ssigned by EC2 in vm object
            vm.domain_name = newInstance.ip_address
            vm.ec2_id = newInstance.id
            self.log.debug("VM %s: %s" % (instanceName, newInstance))
            return vm

        except Exception as e:
            self.log.debug("initializeVM Failed: %s" % e)
            if newInstance:
                self.connection.terminate_instances(instance_ids=[newInstance.id])
            return None

    def waitVM(self, vm, max_secs):
        """ waitVM - Wait at most max_secs for a VM to become
        ready. Return error if it takes too long.

        VM is a boto.ec2.instance.Instance object.
        """

        self.log.info("WaitVM: %s, ec2_id: %s" % (vm.id, vm.ec2_id))

        # test if the vm is still an instance
        if not self.existsVM(vm):
            self.log.info("VM %s: no longer an instance" % vm.id)
            return -1

        # First, wait for ping to the vm instance to work
        instance_down = 1
        instanceName = self.instanceName(vm.id, vm.name)
        start_time = time.time()
        domain_name = self.domainName(vm)
        self.log.info("WaitVM: pinging %s" % domain_name)
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
        self.log.debug("VM %s: ping completed" % (vm.id))
        while(True):

            elapsed_secs = time.time() - start_time

            # Give up if the elapsed time exceeds the allowable time
            if elapsed_secs > max_secs:
                self.log.info(
                    "VM %s: SSH timeout after %d secs" %
                    (instanceName, elapsed_secs))
                return -1

            # If the call to ssh returns timeout (-1) or ssh error
            # (255), then success. Otherwise, keep trying until we run
            # out of time.
            ret = timeout(["ssh"] + self.ssh_flags +
                          ["%s@%s" % (config.Config.EC2_USER_NAME, domain_name),
                           "(:)"], max_secs - elapsed_secs)

            self.log.debug("VM %s: ssh returned with %d" %
                           (instanceName, ret))

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
        self.log.debug("runJob: Running job on VM %s" %
                       self.instanceName(vm.id, vm.name))
        # Setting ulimits for VM and running job
        runcmd = "/usr/bin/time --output=time.out autodriver -u %d -f %d -t \
                %d -o %d -z %s -i %d autolab &> output" % (
                  config.Config.VM_ULIMIT_USER_PROC,
                  config.Config.VM_ULIMIT_FILE_SIZE,
                  runTimeout,
                  maxOutputFileSize,
                  config.Config.AUTODRIVER_LOGGING_TIME_ZONE,
                  config.Config.AUTODRIVER_TIMESTAMP_INTERVAL)
        ret = timeout(["ssh"] + self.ssh_flags +
                       ["%s@%s" % (config.Config.EC2_USER_NAME, domain_name), runcmd], runTimeout * 2)
        # return 3 # xxx inject error to test KEEP_VM_AFTER_FAILURE
        return ret
        # runTimeout * 2 is a temporary hack. The driver will handle the timout

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

        # test if the instance still exists
        reservations = self.connection.get_all_instances(instance_ids=[vm.ec2_id])
        if not reservations:
            self.log.info("destroyVM: instance non-exist %s %s" % (vm.ec2_id, vm.name))
            return []

        self.log.info("destroyVM: %s %s %s %s" % (vm.ec2_id, vm.name, vm.doNotDestroy, vm.notes))

        if hasattr(config.Config, 'KEEP_VM_AFTER_FAILURE') and \
           config.Config.KEEP_VM_AFTER_FAILURE and vm.doNotDestroy:
          iName = self.instanceName(vm.id, vm.name)
          self.log.info("Will keep VM %s for further debugging" % iName)
          instance = self.boto3resource.Instance(vm.ec2_id)
          # delete original name tag and replace it with "failed-xxx"
          # add notes tag for test name
          tag = self.boto3resource.Tag(vm.ec2_id, "Name", iName)
          if tag:
            tag.delete()
          instance.create_tags(Tags=[{"Key": "Name", "Value": "failed-" + iName}])
          instance.create_tags(Tags=[{"Key": "Notes", "Value": vm.notes}])
          return

        ret = self.connection.terminate_instances(instance_ids=[vm.ec2_id])
        # delete dynamically created key
        if not self.useDefaultKeyPair:
            self.deleteKeyPair()

        if self.auto_scaling_group:
            response = self.asg.describe_auto_scaling_instances(InstanceIds=[vm.ec2_id],
                                                                MaxRecords=1)
            if len(response['AutoScalingInstances']) == 1:
                self.asg.detach_instances(InstanceIds=[vm.ec2_id],
                                          AutoScalingGroupName=self.auto_scaling_group_name,
                                          ShouldDecrementDesiredCapacity=True)
                self.log.info("detach instance %s %s from auto scaling group" % (vm.ec2_id, vm.name))
            else:
                self.log.info("instance %s %s not in auto scaling group" % (vm.ec2_id, vm.name))

        return ret

    def safeDestroyVM(self, vm):
        return self.destroyVM(vm)

    def getVMs(self):
        """ getVMs - Returns the complete list of VMs on this account. Each
        list entry is a boto.ec2.instance.Instance object.
        """
        # TODO: Find a way to return vm objects as opposed ec2 instance
        # objects.
        instances = list()
        for i in self.connection.get_all_instances():
            if i.id is not config.Config.TANGO_RESERVATION_ID:
                inst = i.instances.pop()
                if inst.state_code is config.Config.INSTANCE_RUNNING:
                    instances.append(inst)

        vms = list()
        for inst in instances:
            vm = TangoMachine()
            vm.ec2_id = inst.id
            vm.name = str(inst.tags.get('Name'))
            self.log.debug('getVMs: Instance - %s, EC2 Id - %s' %
                           (vm.name, vm.ec2_id))
            vms.append(vm)

        return vms

    def existsVM(self, vm):
        """ existsVM - Checks whether a VM exists in the vmms.
        """
        instances = self.connection.get_all_instances()

        for inst in instances:
            if inst.instances[0].id == vm.ec2_id and inst.instances[0].state == "running":
                return True
        return False

    def getImages(self):
        """ getImages - return a constant; actually use the ami specified in config 
        """
        self.log.info("getImages: %s" % str(list(self.img2ami.keys())))
        return list(self.img2ami.keys())
