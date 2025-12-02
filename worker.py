#
# worker.py - Thread that shepherds a job through it execution sequence
#
import threading
import time
import logging
import tempfile
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import os
import shutil
from enum import Enum

from datetime import datetime
from config import Config
from jobQueue import JobQueue
from tangoObjects import TangoMachine, TangoJob
from typing import Dict, Optional
from vmms.interface import VMMSInterface
from preallocator import Preallocator
#
# Worker - The worker class is very simple and very dumb. The goal is
# to walk through the VMMS interface, track the job's progress, and if
# anything goes wrong, recover cleanly from it.
#
# The issue is that these VMMS functions can block, taking a
# significant amount of time. By running each worker as a thread, each
# worker can spend as much time necessary on its job without blocking
# anything else in the system.
#

class DetachMethod(Enum):
    RETURN_TO_POOL = "return_to_pool"
    DESTROY_WITHOUT_REPLACEMENT = "destroy_without_replacement"
    DESTROY_AND_REPLACE = "replace"


# We always preallocate a VM for the worker to use
class Worker(threading.Thread):
    def __init__(self, job: TangoJob, vmms: VMMSInterface, jobQueue: JobQueue, preallocator: Preallocator, preVM: TangoMachine):
        threading.Thread.__init__(self)
        self.daemon = True
        self.job = job
        self.vmms: VMMSInterface = vmms
        self.jobQueue : JobQueue = jobQueue
        self.preallocator = preallocator
        self.preVM = preVM
        threading.Thread.__init__(self)
        self.log = logging.getLogger("Worker")
        self.cleanupStatus = False

    #
    # Worker helper functions
    #
    def __del__(self):
        assert self.cleanupStatus, "Worker must call detachVM before returning"
    
    
    def detachVM(self, detachMethod: DetachMethod):
        """detachVM - Detach the VM from this worker. The options are
        to return it to the pool's free list (return_vm), destroy it
        (not return_vm), and if destroying it, whether to replace it
        or not in the pool (replace_vm). The worker must always call
        this function before returning.
        """
        # job-owned instance, simply destroy after job is completed
        self.cleanupStatus = True
        if Config.VMMS_NAME == "ec2SSH":
            self.vmms.safeDestroyVM(self.job.vm)
            # EC2 doesn't use the preallocator
        else:
            if detachMethod == DetachMethod.RETURN_TO_POOL:
                self.preallocator.freeVM(self.job.vm)
            elif detachMethod == DetachMethod.DESTROY_WITHOUT_REPLACEMENT:
                self.vmms.safeDestroyVM(self.job.vm)
                self.preallocator.removeVM(self.job.vm)
            elif detachMethod == DetachMethod.DESTROY_AND_REPLACE:
                self.vmms.safeDestroyVM(self.job.vm)
                self.preallocator.createVM(self.job.vm)
                # Important: don't remove the VM from the pool until its
                # replacement has been created. Otherwise there is a
                # potential race where the job manager thinks that the
                # pool is empty and creates a spurious vm.
                self.preallocator.removeVM(self.job.vm)
            else:
                raise ValueError(f"Invalid detach method: {detachMethod}")

    def rescheduleJob(self, hdrfile: str, ret: Dict[str, int], err: str) -> None:
        """rescheduleJob - Reschedule a job that has failed because
        of a system error, such as a VM timing out or a connection
        failure.
        """
        self.log.error("Job %s:%d failed: %s" % (self.job.name, self.job.id, err))
        self.job.appendTrace(
            "%s|Job %s:%d failed: %s"
            % (datetime.now().ctime(), self.job.name, self.job.id, err)
        )

        # Try a few times before giving up
        if self.job.retries < Config.JOB_RETRIES:
            self.log.error("Retrying job %s:%d, retries: %d" % (self.job.name, self.job.id, self.job.retries))
            self.job.appendTrace(
                "%s|Retrying job %s:%d, retries: %d"
                % (datetime.now().ctime(), self.job.name, self.job.id, self.job.retries)
            )
            try:
                os.remove(hdrfile)
            except OSError:
                pass
            self.detachVM(DetachMethod.DESTROY_AND_REPLACE)
            self.jobQueue.unassignJob(self.job.id)

        # Here is where we give up
        else:
            full_err = f"Internal Error: {err}. Unable to complete job after {Config.JOB_RETRIES} tries. Please resubmit.\nJob status: waitVM={ret['waitvm']} initializeVM={ret['initializevm']} copyIn={ret['copyin']} runJob={ret['runjob']} copyOut={ret['copyout']}"
            self.log.error(f"Giving up on job %s:%d. %s" % (self.job.name, self.job.id, full_err))
            self.job.appendTrace(
                "%s|Giving up on job %s:%d. %s"
                % (datetime.now().ctime(), self.job.name, self.job.id, full_err)
            )
            self.afterJobExecution(hdrfile, full_err, DetachMethod.DESTROY_AND_REPLACE)

    def appendMsg(self, filename: str, msg: str) -> None:
        """appendMsg - Append a timestamped Tango message to a file"""
        f = open(filename, "a")
        f.write("Autograder [%s]: %s\n" % (datetime.now().ctime(), msg))
        f.close()

    def catFiles(self, f1: str, f2: str) -> None:
        """catFiles - cat f1 f2 > f2, where f1 is the Tango header
        and f2 is the output from the Autodriver
        """
        self.appendMsg(f1, "Here is the output from the autograder:\n---")
        (wfd, tmpname) = tempfile.mkstemp(dir=os.path.dirname(f2))
        wf = os.fdopen(wfd, "ab")
        with open(f1, "rb") as f1fd:
            shutil.copyfileobj(f1fd, wf)
        # f2 may not exist if autograder failed
        try:
            with open(f2, "rb") as f2fd:
                shutil.copyfileobj(f2fd, wf)
        except OSError:
            pass
        wf.close()
        os.rename(tmpname, f2)
        os.remove(f1)

    def notifyServer(self, job: TangoJob) -> None:
        try:
            if job.notifyURL:
                outputFileName = job.outputFile.split("/")[-1]  # get filename from path
                fh = open(job.outputFile, "rb")
                files = {"file": str(fh.read(), errors="ignore")}
                hdrs = {"Filename": outputFileName}
                self.log.debug("Sending request to %s" % job.notifyURL)
                with requests.session() as s:
                    # urllib3 retry, allow POST to be retried, use backoffs
                    r = Retry(total=10, allowed_methods=None, backoff_factor=1)
                    s.mount("http://", HTTPAdapter(max_retries=r))
                    s.mount("https://", HTTPAdapter(max_retries=r))
                    response = s.post(
                        job.notifyURL, files=files, headers=hdrs, verify=False
                    )
                self.log.info(
                    "Response from callback to %s:%s"
                    % (job.notifyURL, response.content.decode())
                )
                fh.close()
            else:
                self.log.info("No callback URL for job %s:%d" % (self.job.name, self.job.id))
        except Exception as e:
            self.log.debug("Error in notifyServer: %s" % str(e))

    def afterJobExecution(self, hdrfile: str, msg: str, detachMethod: DetachMethod) -> None: 
        self.jobQueue.makeDead(self.job, msg)
        
        # Update the text that users see in the autodriver output file
        self.appendMsg(hdrfile, msg)
        self.catFiles(hdrfile, self.job.outputFile)
        os.chmod(self.job.outputFile, 0o644)
        
        # Thread exit after termination
        self.detachVM(detachMethod)
        self.notifyServer(self.job)
        return

    #
    # Main worker function
    #
    def run(self) -> None:
        """run - Step a job through its execution sequence"""
        try:
            # Hash of return codes for each step
            ret: Dict[str, int] = {}
            self.log.debug("Run worker")
            vm = None

            # Header message for user
            hdrfile = tempfile.mktemp()
            self.appendMsg(hdrfile, "Received job %s:%d" % (self.job.name, self.job.id))

            # Assigning job to the preallocated VM
            self.log.debug("Assigning job to preallocated VM")
            self.job.makeVM(self.preVM)
            self.log.info(
                "Assigned job %s:%d existing VM %s"
                % (
                    self.job.name,
                    self.job.id,
                    self.vmms.instanceName(self.preVM.id, self.preVM.name),
                )
            )
            self.job.appendTrace(
                "%s|Assigned job %s:%d existing VM %s"
                % (
                    datetime.now().ctime(),
                    self.job.name,
                    self.job.id,
                    self.vmms.instanceName(self.preVM.id, self.preVM.name),
                )
            )
            self.log.debug("Assigned job to preallocated VM")
            ret["initializevm"] = 0 # Vacuous success since it doesn't happen

            vm = self.job.vm

            # Wait for the instance to be ready
            self.log.debug(
                "Job %s:%d waiting for VM %s"
                % (self.job.name, self.job.id, self.vmms.instanceName(vm.id, vm.name))
            )
            self.job.appendTrace(
                "%s|Job %s:%d waiting for VM %s"
                % (
                    datetime.now().ctime(),
                    self.job.name,
                    self.job.id,
                    self.vmms.instanceName(vm.id, vm.name),
                )
            )
            self.log.debug("Waiting for VM")
            if self.job.stopBefore == "waitvm":
                msg = "Execution stopped before %s" % self.job.stopBefore
                self.job.setKeepForDebugging(True)
                self.afterJobExecution(hdrfile, msg, detachMethod=DetachMethod.DESTROY_AND_REPLACE)
                return
            ret["waitvm"] = self.vmms.waitVM(vm, Config.WAITVM_TIMEOUT)

            self.log.debug("Waited for VM")

            # If the instance did not become ready in a reasonable
            # amount of time, then reschedule the job, detach the VM,
            # and exit worker
            if ret["waitvm"] == -1:
                Config.waitvm_timeouts += 1
                self.rescheduleJob(
                    hdrfile,
                    ret,
                    "Internal error: waitVM timeout after %d secs"
                    % Config.WAITVM_TIMEOUT,
                )

                # Thread Exit after waitVM timeout
                return

            self.log.info(
                "VM %s ready for job %s:%d"
                % (self.vmms.instanceName(vm.id, vm.name), self.job.name, self.job.id)
            )
            self.job.appendTrace(
                "%s|VM %s ready for job %s:%d"
                % (
                    datetime.now().ctime(),
                    self.vmms.instanceName(vm.id, vm.name),
                    self.job.name,
                    self.job.id,
                )
            )
            if (self.job.stopBefore == "copyin"):
                msg = "Execution stopped before %s" % self.job.stopBefore
                self.job.setKeepForDebugging(True)
                self.afterJobExecution(hdrfile, msg, detachMethod=DetachMethod.DESTROY_AND_REPLACE)
                self.log.debug(msg)
                return
            # Copy input files to VM
            ret["copyin"] = self.vmms.copyIn(vm, self.job.input, self.job.id)
            self.log.debug(f"After copyIn: ret[copyin] = {ret['copyin']}, job_id: {str(self.job.id)}")

            if ret["copyin"] != 0:
                Config.copyin_errors += 1
                msg = "Copy in to VM failed (status=%d)" % (ret["copyin"])
                self.job.vm.notes = str(self.job.id) + "_" + self.job.name
                self.job.setKeepForDebugging(True)
                self.log.debug(msg)
                self.rescheduleJob(
                    hdrfile,
                    ret,
                    msg
                )
                return

            self.log.info(
                "Input copied for job %s:%d [status=%d]"
                % (self.job.name, self.job.id, ret["copyin"])
            )
            self.job.appendTrace(
                "%s|Input copied for job %s:%d [status=%d]"
                % (datetime.now().ctime(), self.job.name, self.job.id, ret["copyin"])
            )

            if (self.job.stopBefore == "runjob"):
                msg = "Execution stopped before %s" % self.job.stopBefore
                self.job.setKeepForDebugging(True)
                self.afterJobExecution(hdrfile, msg, detachMethod=DetachMethod.DESTROY_AND_REPLACE)
                return
            # Run the job on the virtual machine
            ret["runjob"] = self.vmms.runJob(
                vm,
                self.job.timeout,
                self.job.maxOutputFileSize,
                self.job.disableNetwork,
            )
            if ret["runjob"] != 0:
                if ret["runjob"] == 1:  # This should never happen
                    msg = "RunJob: Autodriver usage error (status=%d)" % (ret["runjob"])
                elif ret["runjob"] == 2:
                    msg = "RunJob: Job timed out after %d seconds" % (self.job.timeout)
                elif ret["runjob"] == 3:  # EXIT_OSERROR in Autodriver
                    # Abnormal job termination (Autodriver encountered an OS
                    # error).  Assume that the VM is damaged. Destroy this VM
                    # and do not retry the job since the job may have damaged
                    # the VM.
                    msg = "RunJob: OS error while running job on VM"
                    # TODO: do we need to not reschedule the job?
                    self.job.vm.notes = str(self.job.id) + "_" + self.job.name
                    self.job.setKeepForDebugging(True)
                elif ret["runjob"] == -1:
                    Config.runjob_timeouts += 1
                    # TODO: difference between 2 and -1?
                else:  # This should never happen
                    msg = "RunJob: Unknown autodriver error (status=%d)" % (
                        ret["runjob"]
                    )
                Config.runjob_errors += 1
                self.rescheduleJob(
                    hdrfile,
                    ret,
                    msg
                )
                return
            
            self.log.info(
                "Job %s:%d executed [status=%s]"
                % (self.job.name, self.job.id, ret["runjob"])
            )
            self.job.appendTrace(
                "%s|Job %s:%d executed [status=%s]"
                % (datetime.now().ctime(), self.job.name, self.job.id, ret["runjob"])
            )

            if (self.job.stopBefore == "copyout"):
                msg = "Execution stopped before %s" % self.job.stopBefore
                self.job.setKeepForDebugging(True)
                self.afterJobExecution(hdrfile, msg, detachMethod=DetachMethod.DESTROY_AND_REPLACE)
                return
            # Copy the output back.
            ret["copyout"] = self.vmms.copyOut(vm, self.job.outputFile)
            if ret["copyout"] != 0:
                Config.copyout_errors += 1
                self.rescheduleJob(
                    hdrfile,
                    ret,
                    f"Internal error: copyOut failed (status={ret['copyout']})"
                )
                return
            
            self.log.info(
                "Output copied for job %s:%d [status=%d]"
                % (self.job.name, self.job.id, ret["copyout"])
            )
            self.job.appendTrace(
                "%s|Output copied for job %s:%d [status=%d]"
                % (datetime.now().ctime(), self.job.name, self.job.id, ret["copyout"])
            )

            # Job termination. Notice that Tango considers
            # things like runjob timeouts and makefile errors to be
            # normal termination and doesn't reschedule the job.
            self.log.info("Success: job %s:%d finished" % (self.job.name, self.job.id))

            for status in ret.values():
                assert status == 0, "Should not get to the success point if any stage failed"
                # TODO: test this, then remove everything below this point
                
            # Move the job from the live queue to the dead queue
            # with an explanatory message
            msg = "Success: Autodriver returned normally"
            self.afterJobExecution(hdrfile, msg, detachMethod=DetachMethod.RETURN_TO_POOL)
            return

        #
        # Exception: ec2CallError - Raised by ec2Call()
        #
        except Exception as err:
            self.log.exception("Internal Error")
            self.appendMsg(self.job.outputFile, "Internal Error: %s" % err)
            # if vm is set, then the normal job assignment completed,
            # and detachVM can be run
            # if vm is not set but self.preVM is set, we still need
            # to return the VM, but have to initialize self.job.vm first
            # TODO: move self.job.makeVM to the start of the try block, so it should be an error if vm fails to be set
            if self.preVM and not vm:
                self.job.makeVM(self.preVM)
                vm = self.preVM 
            if vm:
                self.detachVM(DetachMethod.DESTROY_AND_REPLACE)
