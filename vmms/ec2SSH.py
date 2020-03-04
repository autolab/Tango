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
from builtins import object
from builtins import str
import subprocess
import os
import re
import time
import logging

import config

import boto
from boto import ec2
from tangoObjects import TangoMachine


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


class Ec2SSH(object):
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
        self.ssh_flags = Ec2SSH._SSH_FLAGS
        if accessKeyId:
            self.connection = ec2.connect_to_region(config.Config.EC2_REGION,
                    aws_access_key_id=accessKeyId, aws_secret_access_key=accessKey)
            self.useDefaultKeyPair = False
        else:
            self.connection = ec2.connect_to_region(config.Config.EC2_REGION)
            self.useDefaultKeyPair = True
        self.log = logging.getLogger("Ec2SSH")

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

        ec2instance['ami'] = config.Config.DEFAULT_AMI

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

    #
    # VMMS API functions
    #
    def initializeVM(self, vm):
        """ initializeVM - Tell EC2 to create a new VM instance.

        Returns a boto.ec2.instance.Instance object.
        """
        # Create the instance and obtain the reservation
        try:
            instanceName = self.instanceName(vm.id, vm.name)
            ec2instance = self.tangoMachineToEC2Instance(vm)
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

            # Wait for instance to reach 'running' state
            state = -1
            start_time = time.time()
            while state is not config.Config.INSTANCE_RUNNING:

                for inst in self.connection.get_all_instances():
                    if inst.id == reservation.id:
                        newInstance = inst.instances.pop()

                state = newInstance.state_code
                self.log.debug(
                    "VM %s: Waiting to reach 'running' state. Current state: %s (%d)" %
                    (instanceName, newInstance.state, state))
                time.sleep(config.Config.TIMER_POLL_INTERVAL)
                elapsed_secs = time.time() - start_time
                if (elapsed_secs > config.Config.INITIALIZEVM_TIMEOUT):
                    self.log.debug(
                        "VM %s: Did not reach 'running' state before timeout period of %d" %
                        (instanceName, config.Config.TIMER_POLL_INTERVAL))

            self.log.info(
                "VM %s | State %s | Reservation %s | Public DNS Name %s | Public IP Address %s" %
                (instanceName,
                 newInstance.state,
                 reservation.id,
                 newInstance.public_dns_name,
                 newInstance.ip_address))

            # Save domain and id ssigned by EC2 in vm object
            vm.domain_name = newInstance.ip_address
            vm.ec2_id = newInstance.id
            # Assign name to EC2 instance
            self.connection.create_tags(
                [newInstance.id], {"Name": instanceName})
            self.log.debug("VM %s: %s" % (instanceName, newInstance))
            return vm

        except Exception as e:
            self.log.debug("initializeVM Failed: %s" % e)

            return None

    def waitVM(self, vm, max_secs):
        """ waitVM - Wait at most max_secs for a VM to become
        ready. Return error if it takes too long.

        VM is a boto.ec2.instance.Instance object.
        """

        # First, wait for ping to the vm instance to work
        instance_down = 1
        instanceName = self.instanceName(vm.id, vm.name)
        start_time = time.time()
        domain_name = self.domainName(vm)
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
                    return -1

        # The ping worked, so now wait for SSH to work before
        # declaring that the VM is ready
        self.log.debug("VM %s: ping completed" % (vm.name))
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
                %d -o %d autolab &> output" % (config.Config.VM_ULIMIT_USER_PROC,
                                               config.Config.VM_ULIMIT_FILE_SIZE,
                                               runTimeout,
                                               maxOutputFileSize)
        ret = timeout(["ssh"] + self.ssh_flags +
                       ["%s@%s" % (config.Config.EC2_USER_NAME, domain_name), runcmd], runTimeout * 2)
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
        ret = self.connection.terminate_instances(instance_ids=[vm.ec2_id])
        # delete dynamically created key
        if not self.useDefaultKeyPair:
            self.deleteKeyPair()
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
            if inst.instances[0].id is vm.ec2_id:
                return True
        return False

    def getImages(self):
        """ getImages - return a constant; actually use the ami specified in config 
        """
        return ["default.img"]
