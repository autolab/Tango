#
# tashiSSH.py - Implements the Tango VMMS interface.
#
# This implementation uses Tashi to manage the virtual machines and
# ssh and scp to access them. The following excecption are raised back
# to the caller:
#
#   TashiException - Tashi raises this if it encounters any problem
#   tashiCallError - raised by tashiCall() function
#
# TODO: this currently probably does not work on Python 3 yet
from builtins import object
from builtins import str
import random
import subprocess
import os
import re
import time
import logging
import threading
import os
import sys

import config
from tashi.rpycservices.rpyctypes import *
from tashi.util import getConfig, createClient
from tangoObjects import *


def timeout(command, time_out=1):
    """ timeout - Run a unix command with a timeout. Return -1 on
    timeout, otherwise return the return value from the command, which
    is typically 0 for success, 1-255 for failure.
    """
    # Launch the command
    p = subprocess.Popen(command,
                         stdout=open('/dev/null', 'w'),
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
    if (config.Config.LOGLEVEL is logging.DEBUG) and (
            "ssh" in command or "scp" in command):
        out = sys.stdout
        err = sys.stderr
    else:
        out = open("/dev/null", 'w')
        err = sys.stdout

    # Launch the command
    p = subprocess.Popen(command,
                         stdout=open('/dev/null', 'w'),
                         stderr=subprocess.STDOUT)

    t = 0.0
    while t < time_out:
        ret = p.poll()
        if ret is None:
            time.sleep(config.Config.TIMER_POLL_INTERVAL)
            t += config.Config.TIMER_POLL_INTERVAL
        elif ret == returnValue:
            return ret
        else:
            p = subprocess.Popen(command,
                                 stdout=open('/dev/null', 'w'),
                                 stderr=subprocess.STDOUT)
    return ret

#
# User defined exceptions
#
# tashiCall() exception
class tashiCallError(Exception):
    pass


class TashiSSH(object):
    _SSH_FLAGS = ["-q", "-i", os.path.dirname(__file__) + "/id_rsa",
                  "-o", "StrictHostKeyChecking=no",
                  "-o", "GSSAPIAuthentication=no"]

    TASHI_IMAGE_PATH = '/raid/tashi/images'

    def __init__(self):
        self.config = getConfig(["Client"])[0]
        self.client = createClient(self.config)
        self.log = logging.getLogger("TashiSSH")

    #
    # VMMS helper functions
    #
    def tashiCall(self, function, args):
        """ tashiCall - call Tashi function
        """
        fun = getattr(self.client, function, None)
        if fun is None:
            raise tashiCallError("No function %s" % function)
        return fun(*args)

    def instanceName(self, id, name):
        """ instanceName - Construct a VM instance name. Always use
        this function when you need a VM instance name. Never generate
        instance names manually.
        """
        return "%s-%s-%s" % (config.Config.PREFIX, id, name)

    def domainName(self, id, name):
        """ Construct a VM domain name. Always use this function when
         you need a domain name for an instance. Never generate them
         manually.
         """
        return "%s.vmnet" % (self.instanceName(id, name))

    def tangoMachineToInstance(self, vm):
        """ tangoMachineToInstance - convert a tango machine to a
        Tashi instance.
        """
        instance = Instance()
        instance.cores = vm.cores
        instance.memory = vm.memory
        instance.disks = [DiskConfiguration(
            d={'uri': vm.image, 'persistent': False})]
        instance.name = self.instanceName(vm.id, vm.name)
        instance.userId = 42  # ???

        # This VMMS requires a network card to use SSH, so we put one on
        # regardless of what the user asked for.
        mac = "52:54:00:%2.2x:%2.2x:%2.2x" % \
            (random.randint(0, 255), random.randint(0, 255),
             random.randint(0, 255))
        instance.nics = [NetworkConfiguration(d={'mac': mac, 'network': 1})]
        firewall = FirewallConfiguration()

        if vm.network and vm.network.firewall:
            if vm.network.firewall.allow:
                for a in vm.network.firewall.allow:
                    firewall.allow.append(PortConfiguration(
                        d={'protocol': a.protocol, 'port': a.port}))
            if vm.network.firewall.deny:
                for d in vm.network.firewall.deny:
                    firewall.allow.append(PortConfiguration(
                        d={'protocol': d.protocol, 'port': d.port}))
            if vm.network.firewall.forward:
                for f in vm.network.firewall.forward:
                    firewall.allow.append(PortConfiguration(
                        d={'protocol': f.protocol, 'port': f.port}))
        instance.firewall = firewall

        if vm.disk:
            # TODO: do we even need this?
            pass

        if vm.resume:
            instance.hints = {"resume_source": vm.image + ".suspend"}
        else:
            instance.hints = {}
        return instance

    #
    # VMMS API functions
    #
    def initializeVM(self, vm):
        """ initializeVM - Ask Tashi to create a new VM instance
        """
        # Create the instance
        instance = self.tangoMachineToInstance(vm)
        tashiInst = self.tashiCall("createVm", [instance])
        vm.instance_id = tashiInst.id
        return tashiInst

    def waitVM(self, vm, max_secs):
        """ waitVM - Wait at most max_secs for a VM to become
        ready. Return error if it takes too long.
        """
        domain_name = self.domainName(vm.id, vm.name)
        instance_name = self.instanceName(vm.id, vm.name)

        # First, wait for ping to the vm instance to work
        instance_down = 1
        start_time = time.time()
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
        self.log.debug("VM %s: ping completed" % (domain_name))
        while (True):

            elapsed_secs = time.time() - start_time

            # Give up if the elapsed time exceeds the allowable time
            if elapsed_secs > max_secs:
                self.log.info("VM %s: SSH timeout after %d secs" %
                              (domain_name, elapsed_secs))
                return -1

            # If the call to ssh returns timeout (-1) or ssh error
            # (255), then success. Otherwise, keep trying until we run
            # out of time.
            ret = timeout(["ssh"] + TashiSSH._SSH_FLAGS +
                          ["autolab@%s" % (domain_name),
                           "(:)"], max_secs - elapsed_secs)
            self.log.debug("VM %s: ssh returned with %d" %
                           (instance_name, ret))
            if (ret != -1) and (ret != 255):
                return 0

            # Sleep a bit before trying again
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

    def copyIn(self, vm, inputFiles):
        """ copyIn - Copy input files to VM
        """
        domain_name = self.domainName(vm.id, vm.name)
        self.log.debug("Creating autolab directory on VM")
        # Create a fresh input directory
        ret = subprocess.call(["ssh"] + TashiSSH._SSH_FLAGS +
                              ["autolab@%s" % (domain_name),
                               "(rm -rf autolab; mkdir autolab)"])
        self.log.debug("Autolab directory created on VM")
        # Copy the input files to the input directory
        for file in inputFiles:
            self.log.debug("Copying file %s to VM %s" %
                           (file.localFile, domain_name))

            ret = timeout(["scp",
                           "-vvv"] + TashiSSH._SSH_FLAGS + [file.localFile,
                                                            "autolab@%s:autolab/%s" % (domain_name,
                                                                                       file.destFile)],
                          config.Config.COPYIN_TIMEOUT)

            if ret == 0:
                self.log.debug(
                    "Success: copied file %s to VM %s with status %s" %
                    (file.localFile, domain_name, str(ret)))
            else:
                self.log.debug(
                    "Error: failed to copy file %s to VM %s with status %s" %
                    (file.localFile, domain_name, str(ret)))
                return ret
        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize):
        """ runJob - Run the make command on a VM using SSH and
        redirect output to file "output".
        """
        domain_name = self.domainName(vm.id, vm.name)
        self.log.debug("runJob: Running job on VM %s" % domain_name)
        # Setting ulimits for VM and running job
        runcmd = "/usr/bin/time --output=time.out autodriver -u %d -f %d -t \
            %d -o %d autolab &> output" % (config.Config.VM_ULIMIT_USER_PROC,
                                           config.Config.VM_ULIMIT_FILE_SIZE,
                                           runTimeout,
                                           config.Config.MAX_OUTPUT_FILE_SIZE)
        ret = timeout(["ssh", "-vvv"] + TashiSSH._SSH_FLAGS +
                      ["autolab@%s" % (domain_name), runcmd], runTimeout * 2)
        # runTimeout * 2 is a temporary hack. The driver will handle the timout

        return ret

    def copyOut(self, vm, destFile):
        """ copyOut - Copy the file output on the VM to the file
        outputFile on the Tango host.
        """
        domain_name = self.domainName(vm.id, vm.name)

        # Optionally log finer grained runtime info. Adds about 1 sec
        # to the job latency, so we typically skip this.
        if config.Config.LOG_TIMING:
            try:
                # regular expression matcher for error message from cat
                no_file = re.compile('No such file or directory')

                time_info = subprocess.check_output(
                    ['ssh'] +
                    TashiSSH._SSH_FLAGS +
                    [
                        'autolab@%s' %
                        (domain_name),
                        'cat time.out']).decode('utf-8').rstrip('\n')

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

        ret = timeout(["scp", "-vvv"] + TashiSSH._SSH_FLAGS +
                      ["autolab@%s:output" % (domain_name), destFile],
                      config.Config.COPYOUT_TIMEOUT)

        return ret

    def destroyVM(self, vm):
        """ destroyVM - Removes a VM from the system
        """
        ret = self.tashiCall("destroyVm", [vm.instance_id])
        return ret

    def safeDestroyVM(self, vm):
        """ safeDestroyVM - More robust version of destroyVM.

        Make sure a VM has a valid instance_id. Make sure a VM exists
        before asking Tashi to destroy it. Make sure that Tashi has
        really killed it before returning to the caller. We still keep
        the original destroyVM because we don't want n^2 calls to
        existsVM().
        """
        self.instance_name = self.instanceName(vm.id, vm.name)

        if self.existsVM(vm):
            self.log.debug("Destroying VM %s" % (self.instance_name))
            if vm.instance_id is not None:
                self.destroyVM(vm)
                self.secs = 0
                # Give Tashi time to delete the instance
                while self.existsVM(
                        vm) and self.secs < config.Config.DESTROY_SECS:
                    self.secs += 1
                    time.sleep(1)

                # Something is really screwy, give up and log the event
                if self.secs >= config.Config.DESTROY_SECS:
                    self.log.error("Tashi never destroyed VM %s" %
                                   (self.instance_name))

            # The instance exist to Tashi but Tango has no instance
            # ID. If we were really ambitious we would use getVMs to
            # determine the instance_id. For now, we give up.
            else:
                self.log.error("VM %s exists but has no instance_id" %
                               (self.instance_name))

        # This is the case where Tango thinks there is an instance but for
        # some reason it has vanished from Tashi
        else:
            self.log.debug("VM %s vanished" % self.instance_name)

    def getVMs(self):
        """ getVMs - Returns the complete list of VMs on this machine. Each
        list entry is a TangoMachine.
        """
        # Get the list of Tashi instances
        instances = self.client.getInstances()

        # Convert it to a list of TangoMachines
        machines = []
        for instance in instances:
            machine = TangoMachine()
            machine.id = instance.id
            machine.instance_id = instance.id
            machine.name = instance.name
            machine.cores = instance.cores
            machine.memory = instance.memory
            machine.image = instance.disks[0].uri
            machine.vmms = 'tashiSSH'
            machines.append(machine)
        return machines

    def existsVM(self, vm):
        """ existsVM - Checks whether a VM exists in the vmms.
        """
        instances = self.client.getInstances()
        for instance in instances:
            if vm.instance_id == instance.id:
                return True
        return False

    def getImages(self):
        """ getImages - Lists all images in TASHI_IMAGE_PATH that have the
        .img extension
        """
        return [img for img in os.listdir(Config.TASHI_IMAGE_PATH) if img.endswith('.img')]
