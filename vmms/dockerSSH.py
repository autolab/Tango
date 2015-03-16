#
# dockerSSH.py - Implements the Tango VMMS interface to run Tango jobs in 
#                docker containers. In this context, VMs are docker containers.
#
import random, subprocess, re, time, logging, threading, os, sys

import config

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

def dockerExec(container, cmd, time_out=1):
    """ docerExec - Executes `docker exec container cmd` and
        returns output. Container is the name of the docker
        container and cmd is a list of commands to run.
    """
    command = ['docker', 'exec', container, 'sh', '-c'] + cmd
    return timeout(command, time_out)

#
# User defined exceptions
#

class DockerSSH:
    _SSH_FLAGS = ["-o", "StrictHostKeyChecking no", "-o", 
                    "GSSAPIAuthentication no"]
    _OS_X = 'darwin'
    LOCALHOST = '127.0.0.1'

    def __init__(self):
        """
			Checks if the machine is ready to run docker containers.
            Initialize boot2docker if running on OS X.
        """
        self.log = logging.getLogger("DockerSSH")
        try:
            # If running on OS X, create a boot2docker VM
            if sys.platform is self._OS_X:
                self.boot2dockerVM()
                self.docker_host_ip = subprocess.check_output(['boot2docker', 'ip']).strip('\n')
            else:
                self.docker_host_ip = self.LOCALHOST

            self.log.info("Docker host IP is %s" & self.docker_host_ip)

        except Exception as e:
            self.log.error(e)
            exit(1)

    def boot2dockerVM(self):
        """ boot2dockerVM - Initializes and starts a boot2docker 
            VM and sets its environment variables. If boot2docker
            VM has already been set up on the machine, these steps
            will simply exit gracefully.
        """
        init_ret = -1
        start_ret = -1
        env_ret = -1
        image_ret = -1

        self.log.debug("Initializing boot2docker VM.")
        init_ret = timeout(['boot2docker', 'init'], 
                            config.Config.BOOT2DOCKER_INIT_TIMEOUT)
        
        self.log.debug("Starting boot2docker VM.")
        if init_ret == 0:
            start_ret = timeout(['boot2docker', 'start'], 
                        config.Config.BOOT2DOCKER_START_TIMEOUT)
        
        self.log.debug("Setting environment variables for boot2docker VM.")
        if start_ret == 0:
            env_ret = timeout(['$(boot2docker shellinit)'],
                        config.Config.BOOT2DOCKER_ENV_TIMEOUT)
        
        self.log.debug("Pulling the autolab docker image from docker hub.")
        if env_ret == 0:
            image_ret = timeout(['docker', 'pull', 'mihirpandya/autolab'],
                        config.Config.DOCKER_IMAGE_TIMEOUT)

        if init_ret != 0:
            raise Exception('Could not initialize boot2docker.')
        if start_ret != 0:
            raise Exception('Could not start boot2docker VM.')
        if env_ret != 0:
            raise Exception('Could not set environment variables \
                of boot2docker VM.')
        if image_ret != 0:
            raise Exception('Could not pull autolab docker image \
                from docker hub.')

    def instanceName(self, id, name):
        """ instanceName - Constructs a VM instance name. Always use
        this function when you need a VM instance name. Never generate
        instance names manually.
        """
        return "%s-%d-%s" % (config.Config.PREFIX, id, name)

    def domainName(self, vm):
        """ Returns the domain name that is stored in the vm
        instance.
        """
        return vm.domain_name

    #
    # VMMS API functions
    #
    def initializeVM(self, vm):
        """ initializeVM -  Start dockerized autograding container by 
        running a trivially long-running process so that the container
        continues to run. Otherwise, the container will stop running 
        once the program has come to completion.
        """
        instanceName = self.instanceName(vm.id, vm.name)
        args = ['docker', 'run', '-d']
        args.append('--name')
        args.append(instanceName)
        args.append(config.Config.DOCKER_IMAGE)
        args.append('/bin/bash')
        args.append('-c')
        args.append('while true; do sleep 1; done')
        ret = timeout(args, config.Config.INITIALIZEVM_TIMEOUT)
        if ret != 0:
            self.log.error("Failed to create container %s", instanceName)
            return None
        return vm

    def waitVM(self, vm, max_secs):
        """ waitVM - Wait at most max_secs for a docker container to become
        ready. Return error if it takes too long. This should be immediate 
        since the container is already initialized in initializeVM.
        """

        instanceName = self.instanceName(vm.id, vm.name)
        start_time = time.time()

        while(True):

            elapsed_secs = time.time() - start_time

            # Give up if the elapsed time exceeds the allowable time
            if elapsed_secs > max_secs:
                self.log.info("Docker %s: Could not reach container \
                    after %d seconds." % (instanceName, elapsed_secs))
                return -1

            # Give the docker container a string to echo back to us.
            ret = dockerExec(instanceName, ['/bin/echo', echo_string])

            self.log.debug("Docker %s: echo returned with \
                %d" % (instanceName, echo))

            if ret == 0:
                return 0

            # Sleep a bit before trying again
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

    def copyIn(self, vm, inputFiles):
        """ copyIn - Copy input files to the docker container. This is
        a little hacky because it actually does:

        `cat FILE | docker exec -i CONTAINER 'sh -c cat > FILE'`

        This is because there is no direct way to copy files to a container
        unless the container is mounted to a specific directory on the host.
        The other option is to set up an ssh server on the container. This
        option should be pursued in future.
        """
        instanceName = self.instanceName(vm.id, vm.name)

        # Create a fresh input directory
        mkdir = dockerExec(instanceName, ['(cd /home; \
                            rm -rf autolab; mkdir autolab \
                            chown autolab autolab; chown :autolab autolab \
                            rm -rf output; mkdir output \
                            chown autolab output; chown :autolab output)'])
        
        if mkdir != 0:
            self.log.error("Failed to create directory in container %s"
                % instanceName)
            return -1

        # Copy the input files to the input directory
        for file in inputFiles:
            ret = timeout(['cat', file.localFile, '|',
                            'docker', 'exec', '-i', instanceName,
                            'sh', '-c', 'cat > /home/autolab/' + file.destFile],
                            config.Config.COPYIN_TIMEOUT)
            if ret != 0:
                self.log.error("Failed to copy file %s to container %s"
                    % (file.localFile, instanceName))
                return ret
        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize):
        """ runJob - Run the make command on a VM using SSH and
        redirect output to file "output".
        """
        domain_name = self.domainName(vm)
        instanceName = self.instanceName(vm.id, vm.name)
        self.log.debug("runJob: Running job on VM %s" % instanceName)
        # Setting ulimits for VM and running job
        runcmd = '"cd /home/; autodriver -u %d -f %d -t %d -o %d \
                    autolab &> output/feedback.out"' % (config.Config.VM_ULIMIT_USER_PROC, 
                        config.Config.VM_ULIMIT_FILE_SIZE, runTimeout, 1000 * 1024)
        args = ['su autolab -c ' + runcmd]
        return dockerExec(instanceName, args, runTimeout * 2)
        # runTimeout * 2 is a temporary hack. The driver will handle the timout

    def copyOut(self, vm, destFile):
        """ copyOut - Copy the autograder feedback from container to
        destFile on the Tango host.
        """
        instanceName = self.instanceName(vm.id, vm.name)

        cmd = ['docker', 'cp']
        cmd.append('%s:/home/output/feedback.out' % instanceName)
        cmd.append(destFile)
        ret = timeout(cmd, config.Config.COPYOUT_TIMEOUT)

        return ret

    def destroyVM(self, vm):
        """ destroyVM - Stop and delete the docker.
        """
        instanceName = self.instanceName(vm.id, vm.name)
        ret = timeout(['docker', 'stop', instanceName], 
            config.Config.DOCKER_STOP_TIMEOUT)
        if ret != 0:
            self.log.error("Failed to stop container %s" % instanceName)
        ret = timeout(['docker', 'run', instanceName],
            config.Config.DOCKER_RM_TIMEOUT)
        if ret != 0:
            self.log.error("Failed to destroy container %s" % instanceName)
        return

    def safeDestroyVM(self, vm):
        start_time = time.time()
        instanceName = self.instanceName(vm.id, vm.name)
        while self.existsVM(vm):
            if (time.time()-start_time > config.Config.DESTROY_SECS):
                self.log.error("Failed to safely destroy container %s"
                    % instanceName)
                return
            self.destroyVM(vm)
        return

    def getVMs(self):
        """ getVMs - Executes and parses `docker ps`
        """
        # Get all docker containers
        machines = []
        containers_str = subprocess.check_output(['docker', 'ps'])
        containers_l = containers_str.split('\n')
        for container in containers_l:
            machine = TangoMachine()
            machine.vmms = 'dockerSSH'
            c = container.split(' ')
            machine.id = c[0]
            c.reverse()
            for el in c:
                if len(el) > 0:
                    machine.name = el
            machines.append(machine)
        return machines

    def existsVM(self, vm):
        """ existsVM - Executes `docker inspect CONTAINER`, which returns
        a non-zero status upon not finding a container.
        """
        instanceName = self.instanceName(vm.id, vm.name)
        p = subprocess.Popen(['docker', 'inspect', instanceName],
                            stdout=open('/dev/null'),
                            stderr=open('/dev/null'))
        return (p.poll() is 0)

