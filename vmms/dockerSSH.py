#
# dockerSSH.py - Implements the Tango VMMS interface to run Tango jobs in 
#                docker containers. In this context, VMs are docker containers.
#
import random, subprocess, re, time, logging, threading, os, sys, shutil
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
        subprocess.call(["/bin/kill", "-9", str(p.pid)])
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

#
# User defined exceptions
#

class DockerSSH:
    _OS_X = 'darwin'
    LOCALHOST = '127.0.0.1'

    def __init__(self):
        """ Checks if the machine is ready to run docker containers.
        Initialize boot2docker if running on OS X.
        """
        try:
            self.log = logging.getLogger("DockerSSH")
            # If running on OS X, create a boot2docker VM
            if sys.platform == self._OS_X:
                # boot2docker initialization will be part of initial
                # set up with Tango.
                self.docker_host_ip = subprocess.check_output(['boot2docker', 'ip']).strip('\n')
            else:
                self.docker_host_ip = self.LOCALHOST

            # Check import docker constants are defined in config
            if len(config.Config.DOCKER_VOLUME_PATH) == 0:
                raise Exception('DOCKER_VOLUME_PATH not defined in config.')

            if len(config.Config.DOCKER_IMAGE) == 0:
                raise Exception('DOCKER_IMAGE not defined in config.')

            self.log.info("Docker host IP is %s" % self.docker_host_ip)

        except Exception as e:
            self.log.error(str(e))
            exit(1)

    def instanceName(self, id, name):
        """ instanceName - Constructs a VM instance name. Always use
        this function when you need a VM instance name. Never generate
        instance names manually.
        """
        return "%s-%s-%s" % (config.Config.PREFIX, id, name)

    def domainName(self, vm):
        """ Returns the domain name that is stored in the vm
        instance.
        """
        return vm.domain_name

    #
    # VMMS API functions
    #
    def initializeVM(self, vm):
        """ initializeVM -  Nothing to do for initializeVM
        """
        return vm

    def waitVM(self, vm, max_secs):
        """ waitVM - Nothing to do for waitVM
        """
        return

    def copyIn(self, vm, inputFiles):
        """ copyIn - Create a directory to be mounted as a volume
        for the docker containers. Copy input files to this directory.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        # Create a fresh volume
        volume_path = config.Config.DOCKER_VOLUME_PATH + instanceName +'/'
        os.makedirs(volume_path)
        for file in inputFiles:
            shutil.copy(file.localFile, volume_path + file.destFile)
            self.log.info('Copied in file %s to %s' % (file.localFile, volume_path + file.destFile))
        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize):
        """ runJob - Run a docker container by doing the follows:
        - mount directory corresponding to this job to /home/autolab
          in the container
        - run autodriver with corresponding ulimits and timeout as
          autolab user
        """
        instanceName = self.instanceName(vm.id, vm.image)
        args = ['docker', 'run', '--name', instanceName, '-v']
        args = args + ['%s:%s' % 
                (config.Config.DOCKER_VOLUME_PATH + instanceName, '/home/mount')]
        args = args + [config.Config.DOCKER_IMAGE]
        args = args + ['sh', '-c']

        autodriverCmd = 'autodriver -u %d -f %d -t %d -o %d autolab &> output/feedback' % \
                        (config.Config.VM_ULIMIT_USER_PROC, 
                        config.Config.VM_ULIMIT_FILE_SIZE,
                        runTimeout, config.Config.MAX_OUTPUT_FILE_SIZE)

        args = args + ['cp -r mount/* autolab/; su autolab -c "%s"; \
                        cp output/feedback mount/feedback' % autodriverCmd]

        self.log.info('Running job: %s' % str(args))

        return timeout(args, runTimeout)


    def copyOut(self, vm, destFile):
        """ copyOut - Copy the autograder feedback from container to
        destFile on the Tango host.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volume_path = config.Config.DOCKER_VOLUME_PATH + instanceName
        print os.listdir(volume_path)
        print volume_path + '/feedback'
        shutil.move(volume_path + '/feedback', destFile)
        self.log.info('Copied feedback file to %s' % destFile)
        
        # Must always clean up containers in order to maintain statelessness.
        # A solution with `docker attach` could be explored.
        self.destroyVM(vm)

        return 0

    def destroyVM(self, vm):
        """ destroyVM - Delete the docker container.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        # Do a hard kill on corresponding docker container.
        # Return status does not matter.
        timeout(['docker', 'rm', '-f', instanceName],
            config.Config.DOCKER_RM_TIMEOUT)
        # Destroy corresponding volume if it exists.
        if instanceName in os.listdir(config.Config.DOCKER_VOLUME_PATH):
            shutil.rmtree(config.Config.DOCKER_VOLUME_PATH + instanceName)
            self.log.debug('Deleted volume %s' % instanceName)
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
        """ getVMs - Executes and parses `docker ps`
        """
        # Get all volumes of docker containers
        machines = []
        for volume in os.listdir(config.Config.DOCKER_VOLUME_PATH):
            machine = TangoMachine()
            machine.vmms = 'dockerSSH'
            machine.name = volume
            volume_l = volume.split('-')
            machine.id = volume_l[1]
            machine.image = volume_l[2]
            machines.append(machine)
        return machines

    def existsVM(self, vm):
        """ existsVM - Executes `docker inspect CONTAINER`, which returns
        a non-zero status upon not finding a container.
        """
        instanceName = self.instanceName(vm.id, vm.name)
        ret = timeout(['docker', 'inspect', instanceName])
        return (ret is 0)
