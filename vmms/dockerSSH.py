#
# dockerSSH.py - Implements the Tango VMMS interface to run Tango jobs in 
#                docker containers.
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
    p = subprocess.Popen(command, stdout=open("/dev/null", 'w'), stderr=subprocess.STDOUT)
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
    _SSH_FLAGS = ["-o", "StrictHostKeyChecking no", "-o", "GSSAPIAuthentication no"]
    _OS_X = 'darwin'
    LOCALHOST = '127.0.0.1'
    DOCKER_IMAGE = 'mihirpandya/autolab'

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
        """
            Initializes and starts a boot2docker VM and sets its environment
            variables. If boot2docker VM has already been set up on the machine,
            these steps will simply exit gracefully.
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
            raise Exception('Could not set environment variables of boot2docker VM.')
        if image_ret != 0:
            raise Exception('Could not pull autolab docker image from docker hub.')


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
        """ initializeVM - Start running a dockerized autograding container.
        """
        args = ['docker', 'run', '-d']
        args.append('--name')
        args.append(self.instanceName(vm.id, vm.name))
        args.append(self.DOCKER_IMAGE)
        args.append('/bin/bash')
        args.append('-c')
        args.append('while true; do sleep 1; done')
        subprocess.Popen(args)
        return vm

    def waitVM(self, vm, max_secs):
        """ waitVM - Wait at most max_secs for a VM to become
        ready. Return error if it takes too long. This should
        be immediate since the VM is localhost.
        """

        instanceName = self.instanceName(vm.id, vm.name)
        start_time = time.time()
        domain_name = self.domainName(vm)
        echo_string = 'docker ready'

        while(True):

            elapsed_secs = time.time() - start_time

            # Give up if the elapsed time exceeds the allowable time
            if elapsed_secs > max_secs:
                self.log.info("Docker %s: Could not reach container after %d seconds." % (instanceName, elapsed_secs))
                return -1

            # Give the docker container a string to echo back to us.
            echo_args = ['docker', 'exec', instanceName]
            echo_args.append('/bin/echo')
            echo_args.append(echo_string)
            echo = subprocess.check_output(echo_args).strip('\n')

            self.log.debug("Docker %s: echo returned with %d" % (instanceName, echo))

            if echo is echo_string:
                return 0

            # Sleep a bit before trying again
            time.sleep(config.Config.TIMER_POLL_INTERVAL)

    def copyIn(self, vm, inputFiles):
        """ copyIn - Copy input files to VM
        """
        domain_name = self.domainName(vm)

        # Create a fresh input directory
        ret = subprocess.call(["ssh"] + LocalSSH._SSH_FLAGS +
                               ["%s" % (domain_name),
                               "(rm -rf autolab; mkdir autolab)"])
        
        # Copy the input files to the input directory
        for file in inputFiles:
            ret = timeout(["scp"] + LocalSSH._SSH_FLAGS +
                           [file.localFile, "%s:autolab/%s" %
                           (domain_name, file.destFile)], config.Config.COPYIN_TIMEOUT)
            if ret != 0:
                return ret
        return 0

    def runJob(self, vm, runTimeout, maxOutputFileSize):
        """ runJob - Run the make command on a VM using SSH and
        redirect output to file "output".
        """
        print "IN RUN JOB!!!"
        domain_name = self.domainName(vm)
        self.log.debug("runJob: Running job on VM %s" % self.instanceName(vm.id, vm.name))
        # Setting ulimits for VM and running job
        runcmd = "/usr/bin/time --output=time.out autodriver -u %d -f %d -t \
            %d -o %d autolab &> output" % (
            config.Config.VM_ULIMIT_USER_PROC, config.Config.VM_ULIMIT_FILE_SIZE,
            runTimeout, maxOutputFileSize) 
        return timeout(["ssh"] + LocalSSH._SSH_FLAGS +
                        ["%s" % (domain_name), runcmd], runTimeout * 2)
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
                
                time_info = subprocess.check_output(['ssh'] + LocalSSH._SSH_FLAGS +
                                                     ['%s' % (domain_name),
                                                     'cat time.out']).rstrip('\n')

                # If the output is empty, then ignore it (timing info wasn't
                # collected), otherwise let's log it!
                if no_file.match(time_info):
                    # runJob didn't produce an output file
                    pass
                
                else:
                    # remove newline character printed in timing info
                    # replaces first '\n' character with a space
                    time_info = re.sub('\n', ' ', time_info, count = 1)
                    self.log.info('Timing (%s): %s' % (domain_name, time_info))
                    
            except subprocess.CalledProcessError, re.error:
                # Error copying out the timing data (probably runJob failed)
                pass
    
        return timeout(["scp"] + LocalSSH._SSH_FLAGS +
                        ["%s:output" % (domain_name), destFile],
                       config.Config.COPYOUT_TIMEOUT)

    def destroyVM(self, vm):
        """ destroyVM - Nothing to destroy for local.
        """
        return

    def safeDestroyVM(self, vm):
        return self.destroyVM(vm)

    def getVMs(self):
        """ getVMs - Nothing to return for local.
        """
        return []

    def existsVM(self, vm):
        """ existsVM - VM is simply localhost which exists.
        """
        return True

