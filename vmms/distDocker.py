#
# distDocker.py
#
# Implements the Tango VMMS interface to run Tango jobs in 
# docker containers on a list of host machines. This list of
# host machines must be able to run docker and be accessible
# by SSH. The IP address of the host machine is stored in the
# `domain_name` attribtue of TangoMachine.
#

from builtins import object
from builtins import str
import random, subprocess, re, time, logging, threading, os, sys, shutil
import tempfile
import socket
import config
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

def timeoutWithReturnStatus(command, time_out, returnValue = 0):
    """ timeoutWithReturnStatus - Run a Unix command with a timeout,
    until the expected value is returned by the command; On timeout,
    return last error code obtained from the command.
    """
    p = subprocess.Popen(command, 
                        stdout=open("/dev/null", 'w'), 
                        stderr=subprocess.STDOUT)
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

class DistDocker(object):

    _SSH_FLAGS = ["-q", "-o", "BatchMode=yes" ]
    _SSH_AUTH_FLAGS = [ "-i", os.path.join(os.path.dirname(__file__), "id_rsa"),
              "-o", "StrictHostKeyChecking=no",
              "-o", "GSSAPIAuthentication=no"]
    _SSH_MASTER_FLAGS = ["-o", "ControlMaster=yes",
                         "-o", "ControlPersist=600"]
    _SSH_MASTER_CHECK_FLAG = ["-O", "check"]
    _SSH_MASTER_EXIT_FLAG = ["-O", "exit"]
    HOSTS_FILE = 'hosts'

    def __init__(self):
        """ Checks if the machine is ready to run docker containers.
        Initialize boot2docker if running on OS X.
        """
        try:
            self.log = logging.getLogger("DistDocker")
            self.hostDNSPoolname=config.Config.HOST_ALIAS
            self.hostUser = "ubuntu"

            if len(config.Config.DOCKER_HOST_USER) > 0:
                self.hostUser = config.Config.DOCKER_HOST_USER

            # Check import docker constants are defined in config
            if len(config.Config.DOCKER_VOLUME_PATH) == 0:
                raise Exception('DOCKER_VOLUME_PATH not defined in config.')

        except Exception as e:
            self.log.error(str(e))
            exit(1)

    def instanceName(self, id, name):
        """ instanceName - Constructs a Docker instance name. Always use
        this function when you need a Docker instance name. Never generate
        instance names manually.
        """
        return "%s-%s-%s" % (config.Config.PREFIX, id, name)

    def getVolumePath(self, instanceName):
        volumePath = config.Config.DOCKER_VOLUME_PATH
        if '*' in volumePath:
            volumePath = os.getcwd() + '/' + 'volumes/'
        volumePath = volumePath + instanceName + '/'
        return volumePath

    #
    # VMMS API functions
    #
    def initializeVM(self, vm):
        """ initializeVM -  Assign a host machine for this container to 
        run on.
        """
        return vm

    def waitVM(self, vm, max_secs):
        """ waitVM - Wait at most max_secs for a VM to become
        ready. Return error if it takes too long.
        """
        start_time = time.time()
        vm.ssh_control_dir = tempfile.mkdtemp(prefix="tango-docker-ssh")
        vm.ssh_flags = ['-o', 'ControlPath=' + os.path.join(vm.ssh_control_dir, "control")]
        vm.use_ssh_master = True

        # Wait for SSH to work before declaring that the VM is ready
        while (True):
            try:
                addr=socket.gethostbyname(self.hostDNSPoolname)
                host=socket.gethostbyaddr(addr)[0]
            except EnvironmentError:
                self.log.exception("DNS lookup failed while setting up vm %s." % (vm.name))
                return -1

            vm.domain_name = host
            self.log.info("(Re)assigned host %s to VM %s." % (host, vm.name))

            elapsed_secs = time.time() - start_time

            # Give up if the elapsed time exceeds the allowable time
            if elapsed_secs > max_secs:
                self.log.info("VM %s: SSH timeout after %d secs" %
                              (vm.domain_name, elapsed_secs))
                return -1

            # If the call to ssh returns timeout (-1) or ssh error
            # (255), then success. Otherwise, keep trying until we run
            # out of time.
            ret = timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                          DistDocker._SSH_AUTH_FLAGS +
                          DistDocker._SSH_MASTER_FLAGS +
                          ["%s@%s" % (self.hostUser, vm.domain_name),
                           "(:)"], max_secs - elapsed_secs)
            self.log.debug("VM %s: ssh returned with %d" %
                           (vm.domain_name, ret))
            if (ret != -1) and (ret != 255):
                return 0

            # Sleep a bit before trying again
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

    def copyIn(self, vm, inputFiles):
        """ copyIn - Create a directory to be mounted as a volume
        for the docker containers on the host machine for this VM.
        Copy input files to this directory on the host machine.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)

        if vm.use_ssh_master:
            ret = timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                          DistDocker._SSH_MASTER_CHECK_FLAG +
                          ["%s@%s" % (self.hostUser, vm.domain_name)])
            if ret != 0:
                self.log.debug("Lost persistent SSH connection")
                return ret

        # Create a fresh volume
        ret = timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                        ["%s@%s" % (self.hostUser, vm.domain_name),
                        "(rm -rf %s; mkdir %s)" % (volumePath, volumePath)],
                        config.Config.COPYIN_TIMEOUT)
        if ret == 0:
            self.log.debug("Volume directory created on VM.")
        else:
            return ret
        
        for file in inputFiles:
            ret = timeout(["scp"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                            [file.localFile] + ["%s@%s:%s/%s" % \
                            (self.hostUser, vm.domain_name, volumePath, file.destFile)],
                            config.Config.COPYIN_TIMEOUT)
            if ret == 0:
                self.log.debug('Copied in file %s to %s' % 
                    (file.localFile, volumePath + file.destFile))
            else:
                self.log.error(
                    "Error: failed to copy file %s to VM %s with status %s" %
                    (file.localFile, vm.domain_name, str(ret)))
                return ret

        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize):
        """ runJob - Run a docker container by doing the follows:
        - mount directory corresponding to this job to /home/autolab
          in the container
        - run autodriver with corresponding ulimits and timeout as
          autolab user
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)

        if vm.use_ssh_master:
            ret = timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                          DistDocker._SSH_MASTER_CHECK_FLAG +
                          ["%s@%s" % (self.hostUser, vm.domain_name)])
            if ret != 0:
                self.log.debug("Lost persistent SSH connection")
                return ret

        autodriverCmd = 'autodriver -u %d -f %d -t %d -o %d autolab &> output/feedback' % \
                        (config.Config.VM_ULIMIT_USER_PROC, 
                        config.Config.VM_ULIMIT_FILE_SIZE,
                        runTimeout, config.Config.MAX_OUTPUT_FILE_SIZE)

        # IMPORTANT: The single and double quotes are important, since we
        #            are switching to the autolab user and then running
        #            bash commands.
        setupCmd = 'cp -r mount/* autolab/; su autolab -c "%s"; \
                cp output/feedback mount/feedback' % autodriverCmd

        args = "(docker run --name %s -v %s:/home/mount %s sh -c '%s')" % \
                (instanceName, volumePath, vm.image, setupCmd)

        self.log.debug('Running job: %s' % args)

        ret = timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                        ["%s@%s" % (self.hostUser, vm.domain_name), args],
                        runTimeout * 2)

        self.log.debug('runJob return status %d' % ret)

        return ret


    def copyOut(self, vm, destFile):
        """ copyOut - Copy the autograder feedback from container to
        destFile on the Tango host. Then, destroy that container.
        Containers are never reused.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)

        if vm.use_ssh_master:
            ret = timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                          DistDocker._SSH_MASTER_CHECK_FLAG +
                          ["%s@%s" % (self.hostUser, vm.domain_name)])
            if ret != 0:
                self.log.debug("Lost persistent SSH connection")
                return ret

        ret = timeout(["scp"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                      ["%s@%s:%s" % 
                      (self.hostUser, vm.domain_name, volumePath + 'feedback'), 
                      destFile],
                      config.Config.COPYOUT_TIMEOUT)
        
        self.log.debug('Copied feedback file to %s' % destFile)
        self.destroyVM(vm)

        return 0

    def destroyVM(self, vm):
        """ destroyVM - Delete the docker container.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)
        if vm.use_ssh_master:
            ret = timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                          DistDocker._SSH_MASTER_CHECK_FLAG +
                          ["%s@%s" % (self.hostUser, vm.domain_name)])
            if ret != 0:
                self.log.debug("Lost persistent SSH connection")
                vm.use_ssh_master = False
                shutil.rmtree(vm.ssh_control_dir, ignore_errors=True)
                vm.ssh_flags = DistDocker._SSH_AUTH_FLAGS

        # Do a hard kill on corresponding docker container.
        # Return status does not matter.
        args = '(docker rm -f %s)' % (instanceName)
        timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                ["%s@%s" % (self.hostUser, vm.domain_name), args],
                config.Config.DOCKER_RM_TIMEOUT)
        # Destroy corresponding volume if it exists.
        timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                ["%s@%s" % (self.hostUser, vm.domain_name),
                "(rm -rf %s)" % (volumePath)],
                config.Config.DOCKER_RM_TIMEOUT)
        self.log.debug('Deleted volume %s' % instanceName)
        if vm.use_ssh_master:
            timeout(["ssh"] + DistDocker._SSH_FLAGS + vm.ssh_flags +
                    DistDocker._SSH_MASTER_EXIT_FLAG +
                    ["%s@%s" % (self.hostUser, vm.domain_name)])
            shutil.rmtree(vm.ssh_control_dir, ignore_errors=True)
        return

    def safeDestroyVM(self, vm):
        """ safeDestroyVM - Delete the docker container and make
        sure it is removed.
        """
        start_time = time.time()
        while self.existsVM(vm):
            if (time.time()-start_time > config.Config.DESTROY_SECS):
                self.log.error("Failed to safely destroy container %s"
                    % vm.name)
                return
            self.destroyVM(vm)
        return

    def getVMs(self):
        """ getVMs - Get all volumes of docker containers
        """
        machines = []
        try:
            hosts=socket.gethostbyname_ex(self.hostDNSPoolname)[2]
        except EnvironmentError:
            return machines
        volumePath = self.getVolumePath('')
        for host in hosts:
            volumes = subprocess.check_output(["ssh"] + DistDocker._SSH_FLAGS +
                                                DistDocker._SSH_AUTH_FLAGS +
                                                ["%s@%s" % (self.hostUser, host),
                                                "(ls %s)" % volumePath]).decode('utf-8').split('\n')
            for volume in volumes:
                if re.match("%s-" % config.Config.PREFIX, volume):
                    machine = TangoMachine()
                    machine.vmms = 'distDocker'
                    machine.name = volume
                    machine.domain_name = host
                    machine.ssh_flags = DistDocker._SSH_AUTH_FLAGS
                    machine.use_ssh_master = False
                    volume_l = volume.split('-')
                    machine.id = volume_l[1]
                    machine.image = volume_l[2]
                    machines.append(machine)
        return machines

    def existsVM(self, vm):
        """ existsVM - Returns true if volume exists for corresponding
        container.
        """
        vms = self.getVMs()
        vmnames = [vm.name for vm in vms]
        return (vm.name in vmnames)

    def getImages(self):
        """ getImages - Executes `docker images` on every host and 
        returns a list of images that can be used to boot a docker 
        container with. This function is a lot of parsing and so 
        can break easily.
        """
        result = set()
        try:
            hosts=socket.gethostbyname_ex(self.hostDNSPoolname)[2]
        except EnvironmentError:
            return result
        for host in hosts:
            o = subprocess.check_output(["ssh"] + DistDocker._SSH_FLAGS +
                                        DistDocker._SSH_AUTH_FLAGS +
                                        ["%s@%s" % (self.hostUser, host),
                                        "(docker images)"]).decode('utf-8')
            o_l = o.split('\n')
            o_l.pop()
            o_l.reverse()
            o_l.pop()
            for row in o_l:
                row_l = row.split(' ')
                result.add(re.sub(r".*/([^/]*)", r"\1", row_l[0]))

        return list(result)
