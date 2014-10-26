#!/usr/local/bin/python2.7
#
# Tango is a job management service that manages requests for jobs to
# be run in virtual machines. Tango consists of four main components:
#
# 1. The Tango Server: This is a thrift interface that receives
#    requests from clients. This interface is defined in
#    thrift/tango.thrift. Job requests are validated and placed in a
#    job queue. (tangod.py)
#
# 2. The Job Manager: This thread runs continuously. It watches the job
#    queue for new job requests. When it finds one it creates a new
#    worker thread to handle the job, and assigns a preallocated or new VM
#    to the job. (jobQueue.py)
#
# 3. Workers: Worker threads do the actual work of running a job. The
#    process of running a job is broken down into the following steps:
#    (1) initializeVM, (2) waitVM, (3) copyIn, (4) runJob, (5)
#    copyOut, (6) destroyVM. The actual process involved in
#    each of those steps is handled by a virtual machine management
#    system (VMMS) such as Tashi or Eucalyptus.  Each job request
#    specifies the VMMS to use.  The worker thread dynamically loads
#    and uses the module written for that particular VMSS. (worker.py
#    and vmms/*.py)
#
# 4. Preallocator: Virtual machines can preallocated in a pool in
#    order to reduce response time. Each virtual machine image has its
#    own pool.  Users control the size of each pool via an external rpc
#    call.  Each time a machine is assigned to a job and removed from
#    the pool, the preallocator creates another instance and adds it
#    to the pool. (preallocator.py)

import threading, time, logging, sys, signal, re, gc
import shlex, subprocess, random, string, os, urllib, stat
from collections import deque

# Thrift is installed in this directory for each python release, however,
# python 2.7 is installed in /usr/local/bin, so by default it looks for it in
# /usr/local/lib, which is incorrect

sys.path.append('/usr/lib/python2.7/site-packages/')

from config import *
from preallocator import *
from jobQueue import *
from vmms.tashiSSH import *

from pythonThrift.tango import Tango
from pythonThrift.tango.ttypes import *

from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol
from thrift.server import TServer

class tangoServer:
    """ tangoServer - Defines the RPC calls that the server accepts
    """
    def __init__(self, jobQueue, preallocator, vmms):
        self.daemon = True
        self.jobQueue = jobQueue
        self.preallocator = preallocator
        self.vmms = vmms
        self.log = logging.getLogger("Tangod")
        self.log.info("Starting Tango server on port %d" % (Config.PORT))

    def addJob(self, job):
        """ addJob - Add a job to the job queue
        """
        Config.job_requests += 1
        self.log.debug("Received addJob request")
        ret = validateJob(job, self.vmms);
        self.log.info("Done validating job")
        if ret == 0:
            return self.jobQueue.add(job)
        else:
            self.jobQueue.addDead(job)
            return -1

    def delJob(self, id, deadjob):
        """ delJob - Delete a job
        @param id: Id of job to delete
        @param deadjob - If 0, move the job from the live queue to the
        dead queue. If non-zero, remove the job from the dead queue
        and discard. Use with caution!
        """
        self.log.debug("Received delJob(%d, %d) request" % (id, deadjob))
        return self.jobQueue.delJob(id, deadjob)

    def getJobs(self, item):
        """ getJobs - Return the list of live jobs (item == 0) or the
        list of dead jobs (item == -1).
        """
        try:
            self.log.debug("Received getJobs(%s) request" % (item))

            if item == -1: # return the list of dead jobs
                return self.jobQueue.deadJobs.values()

            elif item == 0: # return the list of live jobs
                return self.jobQueue.jobQueue.values()

            else: # invalid parameter
                return []
        except Exception as e:
            self.log.debug("getJobs: %s" % str(e))

    def preallocVM(self, vm, num):
        """ preallocVM - Set the pool size for VMs of type vm to num
        """
        self.log.debug("Received preallocVM(%s,%d)request"
                       % (vm.name, num))
        try:
            if not vm or num < 0:
                return -1;
            self.preallocator.update(vm, num)
            return 0
        except Exception, err:
            self.log.error("preallocVM failed: %s" % err);
            return -1

    def getVMs(self, vmms_name):
        """ getVMs - return the list of VMs managed by the service vmms_name
        """
        self.log.debug("Received getVMs request(%s)" % vmms_name)
        try:
            if vmms_name in self.vmms:
                vmms_inst = self.vmms[vmms_name]
                return vmms_inst.getVMs()
            else:
                return []
        except Exception, err:
            self.log.error("getVMs request failed: %s" % err)
            return []

    def delVM(self, vmName, id):
        """ delVM - delete a specific VM instance from a pool
        """
        self.log.debug("Received delVM request(%s, %d)" % (vmName, id))
        try:
            if not vmName or vmName == "" or not id:
                return -1
            return self.preallocator.destroyVM(vmName, id)
        except Exception, err:
            self.log.error("delVM request failed: %s" % err)
            return -1

    def getPool(self, vmName):
        """ getPool - Return the current members of a pool and its free list
        """
        self.log.debug("Received getPool request(%s)" % (vmName))
        try:
            if not vmName or vmName == "":
                return []
            result = self.preallocator.getPool(vmName)
            return ["pool_size=%d" % len(result["pool"]),
                    "free_size=%d" % len(result["free"]),
                    "pool=%s" % result["pool"],
                    "free=%s" % result["free"]]

        except Exception, err:
            self.log.error("getPool request failed: %s" % err)
            return []


    def getInfo(self):
        """ getInfo - return various statistics about the Tango daemon
        """
        stats = []
        stats.append("elapsed_secs=%d" % (time.time() - Config.start_time))
        stats.append("job_requests=%d" % Config.job_requests)
        stats.append("job_retries=%d" % Config.job_retries)
        stats.append("waitvm_timeouts=%d" % Config.waitvm_timeouts)
        stats.append("runjob_timeouts=%d" % Config.runjob_timeouts)
        stats.append("copyin_errors=%d" % Config.copyin_errors)
        stats.append("runjob_errors=%d" % Config.runjob_errors)
        stats.append("copyout_errors=%d" % Config.copyout_errors)
        stats.append("num_threads=%d" % threading.activeCount())
        return stats

    #
    # Helper functions
    #
    def resetTango(self,vmms):
        """ resetTango - resets Tango to a clean predictable state and
        ensures that it has a working virtualization environment. A side
        effect is that also checks that each supported VMMS is actually
        running.
        """
        log = logging.getLogger('Server')

        try:
        # For each supported VMM system, get the instances it knows about,
        # and kill those in the current Tango name space.
            for vmms_name in vmms:
                vobj = vmms[vmms_name]
            	vms = vobj.getVMs()
            	log.debug("Pre-existing VMs: %s" % vms)
            	namelist = []
            	for vm in vms:
                	if re.match("%s-" % Config.PREFIX, vm.name):
                  	    vobj.destroyVM(vm)
                            # Need a consistent abstraction for a vm between interfaces
                            namelist.append(vm.name)
            	if namelist:
                	log.warning("Killed these %s VMs on restart: %s" %
                           		(vmms_name, namelist))

    	except Exception as err:
        	print("resetTango: Call to VMMS %s failed: %s" % (vmms_name, err))
        	log.error("resetTango: Call to VMMS %s failed: %s" % (vmms_name, err))
        	os._exit(1)


def validateJob(job, vmms):
    """ validateJob - validate the input arguments in an addJob request.
    """
    log = logging.getLogger('Server')
    errors = 0

    # If this isn't a Tango job then bail with an error
    if (not isinstance(job, TangoJob)):
        return -1

    # Create an empty trace in case we need to append any error
    # messages there
    if not job.trace:
        job.trace = []

    # Every job must have a name
    if not job.name:
        log.error("validateJob: Missing job.name")
        job.trace.append("%s|validateJob: Missing job.name" %
                         (time.asctime()))
        errors += 1

    # Check the virtual machine field
    if not job.vm:
        log.error("validateJob: Missing job.vm")
        job.trace.append("%s|validateJob: Missing job.vm" %
                         (time.asctime()))
        errors += 1
    else:
        if not job.vm.image:
            log.error("validateJob: Missing job.vm.image")
            job.trace.append("%s|validateJob: Missing job.vm.image" %
                             (time.asctime()))
            errors += 1

       else:
            Check if VM name exists in Tashi directory
           imgList = os.listdir(Config.TASHI_IMAGE_PATH)
           imgPath = Config.TASHI_IMAGE_PATH + job.vm.image
           if job.vm.image not in imgList:
               log.error("validateJob: Image not found: %s" % job.vm.image)
               job.trace.append("%s|validateJob: Image not found: %s" %
                                (time.asctime(), job.vm.image))
               errors += 1
            Check if image has read permissions
           elif not (os.stat(imgPath).st_mode & stat.S_IRUSR):
               log.error("validateJob: Not readable: %s" % job.vm.image)
               job.trace.append("%s|validateJob: Not readable: %s" %
                                (time.asctime(), job.vm.image))
               errors += 1
           else:
               (base, ext) = os.path.splitext(job.vm.image)
               job.vm.name = base;

        if not job.vm.vmms:
            log.error("validateJob: Missing job.vm.vmms")
            job.trace.append("%s|validateJob: Missing job.vm.vmms" %
                             (time.asctime()))
            errors += 1
        else:
            if job.vm.vmms not in vmms:
                log.error("validateJob: Invalid vmms name: %s" % job.vm.vmms)
                job.trace.append("%s|validateJob: Invalid vmms name: %s" %
                                 (time.asctime(), job.vm.vmms))
                errors += 1

    # Check the output file
    if not job.outputFile:
        log.error("validateJob: Missing job.outputFile")
        job.trace.append("%s|validateJob: Missing job.outputFile" %
                         (time.asctime()))
        errors += 1
    else:
        if not os.path.exists(os.path.dirname(job.outputFile)):
            log.error("validateJob: Bad output path: %s", job.outputFile)
            job.trace.append("%s|validateJob: Bad output path: %s" %
                             (time.asctime(), job.outputFile))
            errors += 1

    # Check for max output file size parameter
    if not job.maxOutputFileSize:
        log.debug("validateJob: Setting job.maxOutputFileSize "
                  "to default value: %d bytes", Config.MAX_OUTPUT_FILE_SIZE)
        job.maxOutputFileSize = Config.MAX_OUTPUT_FILE_SIZE

    # Check the list of input files
    for inputFile in job.input:
        if not inputFile.localFile:
            log.error("validateJob: Missing inputFile.localFile")
            job.trace.append("%s|validateJob: Missing inputFile.localFile" %
                             (time.asctime()))
            errors += 1
        else:
            if not os.path.exists(inputFile.localFile):
                log.error("validateJob: Input file %s not found" %
                          (inputFile.localFile))
                job.trace.append("%s|validateJob: Input file %s not found" %
                                 (time.asctime(), inputFile.localFile))
                errors += 1

    # Check if job timeout has been set; If not set timeout to default
    if not job.timeout or job.timeout <= 0:
        log.debug("validateJob: Setting job.timeout to"
                  " default config value: %d secs", Config.RUNJOB_TIMEOUT)
        job.timeout = Config.RUNJOB_TIMEOUT

    # Any problems, return an error status
    if errors > 0:
        log.error("validateJob: Job rejected: %d errors" % errors)
        job.trace.append("%s|validateJob: Job rejected: %d errors" %
                         (time.asctime(), errors))
        return -1
    else:
        return 0


def main():
    """ main - control starts here
    """
    # Parse optional port argument
    if len(sys.argv) > 1:
        Config.PORT = int(sys.argv[1])

    # Record the start time for later throughput calculations
    Config.start_time = time.time()

    # Set up the system logger
    logging.basicConfig(
        filename = Config.LOGFILE,
        format = "%(levelname)s|%(asctime)s|%(name)s|%(message)s",
        #level = logging.INFO
        level = logging.DEBUG
        )

    # Set AWS logging level to INFO
    logging.getLogger('boto').setLevel(logging.INFO)

    # Initialize the hash of supported VMM systems.
    # vmms = {'tashiSSH':TashiSSH()}
    vmms = {'tashiSSH':TashiSSH()}

    # Instantiate the main components in the service
    preallocator = Preallocator(vmms)
    jobQueue = JobQueue(preallocator)
    jobManager = JobManager(jobQueue, vmms, preallocator)

    # Reset the service into a clean starting state
    # resetTango(vmms);

    # Start the service
    handler = tangoServer(jobQueue, preallocator, vmms)
    handler.resetTango(vmms)
    processor = Tango.Processor(handler)
    transport = TSocket.TServerSocket(port=Config.PORT)
    tfactory = TTransport.TBufferedTransportFactory()
    pfactory = TBinaryProtocol.TBinaryProtocolFactory()
    server = TServer.TThreadPoolServer(processor, transport, tfactory, pfactory)

    # Set the size of the server thread pool
    server.setNumThreads(Config.NUM_THREADS);

    print "Starting the Tango server on port %d..." % (Config.PORT)
    server.serve()

if __name__ == "__main__":
    main()
