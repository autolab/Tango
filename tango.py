#
# Tango is a job management service that manages requests for jobs to
# be run in virtual machines. Tango consists of five main components:
#
# 1. The Restful API: This is the interface for Tango that receives
#    requests from clients via HTTP. AddJob requests are converted
#    into a form that the tangoServer understands and then passed on
#    to an instance of the tangoServer class. (restful_tango/*)
#
# 2. The TangoServer Class: This is a class that accepts addJob requests
#    from the restful server. Job requests are validated and placed in
#    a job queue. This class also implements various administrative
#    functions to manage instances of tangoServer. (tango.py)
#
# 3. The Job Manager: This thread runs continuously. It watches the job
#    queue for new job requests. When it finds one it creates a new
#    worker thread to handle the job, and assigns a preallocated or new VM
#    to the job. (jobQueue.py)
#
# 4. Workers: Worker threads do the actual work of running a job. The
#    process of running a job is broken down into the following steps:
#    (1) initializeVM, (2) waitVM, (3) copyIn, (4) runJob, (5)
#    copyOut, (6) destroyVM. The actual process involved in
#    each of those steps is handled by a virtual machine management
#    system (VMMS) such as Local or Amazon EC2.  Each job request
#    specifies the VMMS to use.  The worker thread dynamically loads
#    and uses the module written for that particular VMMS. (worker.py
#    and vmms/*.py)
#
# 5. The Preallocator: Virtual machines can preallocated in a pool in
#    order to reduce response time. Each virtual machine image has its
#    own pool.  Users control the size of each pool via an external HTTP
#    call.  Each time a machine is assigned to a job and removed from
#    the pool, the preallocator creates another instance and adds it
#    to the pool. (preallocator.py)

import threading
import logging
import time
import stat
import re
import os

from datetime import datetime

from jobManager import JobManager
from preallocator import Preallocator
from jobQueue import JobQueue
from tangoObjects import TangoJob
from config import Config


class TangoServer(object):

    """TangoServer - Implements the API functions that the server accepts"""

    def __init__(self):
        self.daemon = True

        vmms = None
        if Config.VMMS_NAME == "tashiSSH":
            from vmms.tashiSSH import TashiSSH

            vmms = TashiSSH()
        elif Config.VMMS_NAME == "ec2SSH":
            from vmms.ec2SSH import Ec2SSH

            vmms = Ec2SSH()
        elif Config.VMMS_NAME == "localDocker":
            from vmms.localDocker import LocalDocker

            vmms = LocalDocker()
        elif Config.VMMS_NAME == "distDocker":
            from vmms.distDocker import DistDocker

            vmms = DistDocker()

        self.preallocator = Preallocator({Config.VMMS_NAME: vmms})
        self.jobQueue = JobQueue(self.preallocator)
        if not Config.USE_REDIS:
            # creates a local Job Manager if there is no persistent
            # memory between processes. Otherwise, JobManager will
            # be initiated separately
            JobManager(self.jobQueue).start()

        logging.basicConfig(
            filename=Config.LOGFILE,
            format="%(levelname)s|%(asctime)s|%(name)s|%(message)s",
            level=Config.LOGLEVEL,
        )
        self.start_time = time.time()
        self.log = logging.getLogger("TangoServer")
        self.log.info("Starting Tango server")

    def addJob(self, job):
        """addJob - Add a job to the job queue"""
        Config.job_requests += 1
        self.log.debug("Received addJob request")
        ret = self.__validateJob(job, self.preallocator.vmms)
        self.log.info("Done validating job %s" % (job.name))
        if ret == 0:
            return self.jobQueue.add(job)
        else:
            self.jobQueue.addDead(job)
            return -1

    def delJob(self, id, deadjob):
        """delJob - Delete a job
        @param id: Id of job to delete
        @param deadjob - If 0, move the job from the live queue to the
        dead queue. If non-zero, remove the job from the dead queue
        and discard. Use with caution!
        """
        self.log.debug("Received delJob(%d, %d) request" % (id, deadjob))
        return self.jobQueue.delJob(id, deadjob)

    def getJobs(self, item):
        """getJobs - Return the list of live jobs (item == 0) or the
        list of dead jobs (item == -1).
        """
        try:
            self.log.debug("Received getJobs(%s) request" % (item))

            if item == -1:  # return the list of dead jobs
                return self.jobQueue.deadJobs.values()

            elif item == 0:  # return the list of live jobs
                return self.jobQueue.liveJobs.values()

            else:  # invalid parameter
                return []
        except Exception as e:
            self.log.debug("getJobs: %s" % str(e))

    def preallocVM(self, vm, num):
        """preallocVM - Set the pool size for VMs of type vm to num"""
        self.log.debug("Received preallocVM(%s,%d)request" % (vm.name, num))
        try:
            vmms = self.preallocator.vmms[vm.vmms]
            if not vm or num < 0:
                return -2
            if vm.image not in vmms.getImages():
                self.log.error("Invalid image name")
                return -3
            (name, ext) = os.path.splitext(vm.image)
            vm.name = name
            self.preallocator.update(vm, num)
            return 0
        except Exception as err:
            self.log.error("preallocVM failed: %s" % err)
            return -1

    def getVMs(self, vmms_name):
        """getVMs - return the list of VMs managed by the service vmms_name"""
        self.log.debug("Received getVMs request(%s)" % vmms_name)
        try:
            if vmms_name in self.preallocator.vmms:
                vmms_inst = self.preallocator.vmms[vmms_name]
                return vmms_inst.getVMs()
            else:
                return []
        except Exception as err:
            self.log.error("getVMs request failed: %s" % err)
            return []

    def delVM(self, vmName, id):
        """delVM - delete a specific VM instance from a pool"""
        self.log.debug("Received delVM request(%s, %d)" % (vmName, id))
        try:
            if not vmName or vmName == "" or not id:
                return -1
            return self.preallocator.destroyVM(vmName, id)
        except Exception as err:
            self.log.error("delVM request failed: %s" % err)
            return -1

    def getPool(self, vmName):
        """getPool - Return the current members of a pool and its free list"""
        self.log.debug("Received getPool request(%s)" % (vmName))
        try:
            if not vmName or vmName == "":
                return []
            result = self.preallocator.getPool(vmName)
            return [
                "pool_size=%d" % len(result["pool"]),
                "free_size=%d" % len(result["free"]),
                "pool=%s" % result["pool"],
                "free=%s" % result["free"],
            ]

        except Exception as err:
            self.log.error("getPool request failed: %s" % err)
            return []

    def getInfo(self):
        """getInfo - return various statistics about the Tango daemon"""
        stats = {}
        stats["elapsed_secs"] = time.time() - self.start_time
        stats["job_requests"] = Config.job_requests
        stats["job_retries"] = Config.job_retries
        stats["waitvm_timeouts"] = Config.waitvm_timeouts
        stats["runjob_timeouts"] = Config.runjob_timeouts
        stats["copyin_errors"] = Config.copyin_errors
        stats["runjob_errors"] = Config.runjob_errors
        stats["copyout_errors"] = Config.copyout_errors
        stats["num_threads"] = threading.activeCount()

        return stats

    def getPartialOutput(self, jobid):
        """getPartialOutput - Return the partial output of a job"""
        try:
            jobInfo = self.jobQueue.liveJobs.get(jobid)

            if jobInfo is None:
                raise Exception("Invalid job id")

            vm = jobInfo.vm

            if not jobInfo.assigned or vm is None:
                self.log.info(
                    "job %s %d is assigned %d, job dict: %s ID: %s]"
                    % (
                        jobInfo.name,
                        jobInfo.id,
                        jobInfo.assigned,
                        str(jobInfo.__dict__),
                        jobInfo.vm.id,
                    )
                )
                raise Exception("Job %s is not running yet" % jobid)
            elif vm.id is None:
                raise Exception("Job %s does not have a vm id set" % jobid)

            vmms = self.preallocator.vmms[Config.VMMS_NAME]
            return vmms.getPartialOutput(vm)
        except Exception as err:
            self.log.error("getPartialOutput request failed: %s" % err)
            raise Exception("getPartialOutput request failed: %s" % err)

    #
    # Helper functions
    #
    def resetTango(self, vmms):
        """resetTango - resets Tango to a clean predictable state and
        ensures that it has a working virtualization environment. A side
        effect is that also checks that each supported VMMS is actually
        running.
        """
        self.log.debug("Received resetTango request.")

        try:
            # For each supported VMM system, get the instances it knows about,
            # and kill those in the current Tango name space.
            for vmms_name in vmms:
                vobj = vmms[vmms_name]
                vms = vobj.getVMs()
                self.log.debug("Pre-existing VMs: %s" % [vm.name for vm in vms])
                namelist = []
                for vm in vms:
                    if re.match("%s-" % Config.PREFIX, vm.name):
                        vobj.destroyVM(vm)
                        # Need a consistent abstraction for a vm between
                        # interfaces
                        namelist.append(vm.name)
                if namelist:
                    self.log.warning(
                        "Killed these %s VMs on restart: %s" % (vmms_name, namelist)
                    )

            for _, job in self.jobQueue.liveJobs.items():
                if not job.isNotAssigned():
                    job.makeUnassigned()
                self.log.debug(
                    "job: %s, assigned: %s" % (str(job.name), str(job.assigned))
                )
        except Exception as err:
            self.log.error("resetTango: Call to VMMS %s failed: %s" % (vmms_name, err))
            os._exit(1)

    def __validateJob(self, job, vmms):
        """validateJob - validate the input arguments in an addJob request."""
        errors = 0

        # If this isn't a Tango job then bail with an error
        if not isinstance(job, TangoJob):
            return -1

        # Every job must have a name
        if not job.name:
            self.log.error("validateJob: Missing job.name")
            job.appendTrace(
                "%s|validateJob: Missing job.name" % (datetime.utcnow().ctime())
            )
            errors += 1

        # Check the virtual machine field
        if not job.vm:
            self.log.error("validateJob: Missing job.vm")
            job.appendTrace(
                "%s|validateJob: Missing job.vm" % (datetime.utcnow().ctime())
            )
            errors += 1
        else:
            if not job.vm.image:
                self.log.error("validateJob: Missing job.vm.image")
                job.appendTrace(
                    "%s|validateJob: Missing job.vm.image" % (datetime.utcnow().ctime())
                )
                errors += 1
            else:
                vobj = vmms[Config.VMMS_NAME]
                imgList = vobj.getImages()
                if job.vm.image not in imgList:
                    self.log.error("validateJob: Image not found: %s" % job.vm.image)
                    job.appendTrace(
                        "%s|validateJob: Image not found: %s"
                        % (datetime.utcnow().ctime(), job.vm.image)
                    )
                    errors += 1
                else:
                    (name, ext) = os.path.splitext(job.vm.image)
                    job.vm.name = name

            if not job.vm.vmms:
                self.log.error("validateJob: Missing job.vm.vmms")
                job.appendTrace(
                    "%s|validateJob: Missing job.vm.vmms" % (datetime.utcnow().ctime())
                )
                errors += 1
            else:
                if job.vm.vmms not in vmms:
                    self.log.error("validateJob: Invalid vmms name: %s" % job.vm.vmms)
                    job.appendTrace(
                        "%s|validateJob: Invalid vmms name: %s"
                        % (datetime.utcnow().ctime(), job.vm.vmms)
                    )
                    errors += 1

        # Check the output file
        if not job.outputFile:
            self.log.error("validateJob: Missing job.outputFile")
            job.appendTrace(
                "%s|validateJob: Missing job.outputFile" % (datetime.utcnow().ctime())
            )
            errors += 1
        else:
            if not os.path.exists(os.path.dirname(job.outputFile)):
                self.log.error("validateJob: Bad output path: %s", job.outputFile)
                job.appendTrace(
                    "%s|validateJob: Bad output path: %s"
                    % (datetime.utcnow().ctime(), job.outputFile)
                )
                errors += 1

        # Check for max output file size parameter
        if not job.maxOutputFileSize:
            self.log.debug(
                "validateJob: Setting job.maxOutputFileSize "
                "to default value: %d bytes",
                Config.MAX_OUTPUT_FILE_SIZE,
            )
            job.maxOutputFileSize = Config.MAX_OUTPUT_FILE_SIZE

        # Check the list of input files
        hasMakefile = False
        for inputFile in job.input:
            if not inputFile.localFile:
                self.log.error("validateJob: Missing inputFile.localFile")
                job.appendTrace(
                    "%s|validateJob: Missing inputFile.localFile"
                    % (datetime.utcnow().ctime())
                )
                errors += 1
            else:
                if not os.path.exists(os.path.dirname(job.outputFile)):
                    self.log.error("validateJob: Bad output path: %s", job.outputFile)
                    job.appendTrace(
                        "%s|validateJob: Bad output path: %s"
                        % (datetime.utcnow().ctime(), job.outputFile)
                    )
                    errors += 1

            if inputFile.destFile == "Makefile":
                hasMakefile = True

        # Check if input files include a Makefile
        if not hasMakefile:
            self.log.error("validateJob: Missing Makefile in input files.")
            job.appendTrace(
                "%s|validateJob: Missing Makefile in input files."
                % (datetime.utcnow().ctime())
            )
            errors += 1

        # Check if job timeout has been set; If not set timeout to default
        if not job.timeout or job.timeout <= 0:
            self.log.debug(
                "validateJob: Setting job.timeout to" " default config value: %d secs",
                Config.RUNJOB_TIMEOUT,
            )
            job.timeout = Config.RUNJOB_TIMEOUT

        # Any problems, return an error status
        if errors > 0:
            self.log.error("validateJob: Job rejected: %d errors" % errors)
            job.appendTrace(
                "%s|validateJob: Job rejected: %d errors"
                % (datetime.utcnow().ctime(), errors)
            )
            return -1
        else:
            return 0
