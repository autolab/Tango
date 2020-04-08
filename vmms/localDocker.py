#
# localDocker.py - Implements the Tango VMMS interface to run Tango jobs in 
#                docker containers. In this context, VMs are docker containers.
#
from builtins import object
from builtins import str
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

#
# User defined exceptions
#

class LocalDocker(object):

    def __init__(self):
        """ Checks if the machine is ready to run docker containers.
        Initialize boot2docker if running on OS X.
        """
        try:
            self.log = logging.getLogger("LocalDocker")

            # Check import docker constants are defined in config
            if len(config.Config.DOCKER_VOLUME_PATH) == 0:
                raise Exception('DOCKER_VOLUME_PATH not defined in config.')

        except Exception as e:
            self.log.error(str(e))
            exit(1)

    def instanceName(self, id, name):
        """ instanceName - Constructs a VM instance name. Always use
        this function when you need a VM instance name. Never generate
        instance names manually.
        """
        return "%s-%s-%s" % (config.Config.PREFIX, id, name)

    def getVolumePath(self, instanceName):
        volumePath = config.Config.DOCKER_VOLUME_PATH
        if '*' in volumePath:
            volumePath = os.getcwd() + '/' + 'volumes/'
        volumePath = volumePath + instanceName + '/'
        return volumePath

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
        volumePath = self.getVolumePath(instanceName)

        # Create a fresh volume
        os.makedirs(volumePath)
        for file in inputFiles:
            shutil.copy(file.localFile, volumePath + file.destFile)
            self.log.debug('Copied in file %s to %s' % (file.localFile, volumePath + file.destFile))
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
        args = ['docker', 'run', '--name', instanceName, '-v']
        args = args + ['%s:%s' % (volumePath, '/home/mount')]
        args = args + [vm.image]
        args = args + ['sh', '-c']

        autodriverCmd = 'autodriver -u %d -f %d -t %d -o %d autolab &> output/feedback' % \
                        (config.Config.VM_ULIMIT_USER_PROC, 
                        config.Config.VM_ULIMIT_FILE_SIZE,
                        runTimeout, config.Config.MAX_OUTPUT_FILE_SIZE)

        args = args + ['cp -r mount/* autolab/; su autolab -c "%s"; \
                        cp output/feedback mount/feedback' % 
                        autodriverCmd]

        self.log.debug('Running job: %s' % str(args))
        ret = timeout(args, runTimeout * 2)
        self.log.debug('runJob returning %d' % ret)

        return ret


    def copyOut(self, vm, destFile):
        """ copyOut - Copy the autograder feedback from container to
        destFile on the Tango host. Then, destroy that container.
        Containers are never reused.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)
        shutil.move(volumePath + 'feedback', destFile)
        self.log.debug('Copied feedback file to %s' % destFile)
        self.destroyVM(vm)

        return 0

    def destroyVM(self, vm):
        """ destroyVM - Delete the docker container.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath('')
        # Do a hard kill on corresponding docker container.
        # Return status does not matter.
        timeout(['docker', 'rm', '-f', instanceName],
            config.Config.DOCKER_RM_TIMEOUT)
        # Destroy corresponding volume if it exists.
        if instanceName in os.listdir(volumePath):
            shutil.rmtree(volumePath + instanceName)
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
        """ getVMs - Executes and parses `docker ps`. This function
        is a lot of parsing and can break easily.
        """
        # Get all volumes of docker containers
        machines = []
        volumePath = self.getVolumePath('')
        for volume in os.listdir(volumePath):
            if re.match("%s-" % config.Config.PREFIX, volume):
                machine = TangoMachine()
                machine.vmms = 'localDocker'
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

    def getImages(self):
        """ getImages - Executes `docker images` and returns a list of
        images that can be used to boot a docker container with. This 
        function is a lot of parsing and so can break easily.
        """
        import ipdb; ipdb.set_trace()
        result = set()
        cmd = "docker images"
        o = subprocess.check_output("docker images", shell=True).decode('utf-8')
        o_l = o.split('\n')
        o_l.pop()
        o_l.reverse()
        o_l.pop()
        for row in o_l:
            row_l = row.split(' ')
            result.add(re.sub(r".*/([^/]*)", r"\1", row_l[0]))
        return list(result)


