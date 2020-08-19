#
# worker.py - Thread that shepherds a job through it execution sequence
#
from builtins import str
import threading
import time
import logging
import tempfile
import requests
import os
import shutil

from datetime import datetime
from config import Config

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


class Worker(threading.Thread):

    def __init__(self, job, vmms, jobQueue, preallocator, preVM):
        threading.Thread.__init__(self)
        self.daemon = True
        self.job = job
        self.vmms = vmms
        self.jobQueue = jobQueue
        self.preallocator = preallocator
        self.preVM = preVM
        threading.Thread.__init__(self)
        self.log = logging.getLogger("Worker")

    #
    # Worker helper functions
    #
    def detachVM(self, return_vm=False, replace_vm=False):
        """ detachVM - Detach the VM from this worker. The options are
        to return it to the pool's free list (return_vm), destroy it
        (not return_vm), and if destroying it, whether to replace it
        or not in the pool (replace_vm). The worker must always call
        this function before returning.
        """
        # job-owned instance, simply destroy after job is completed
        if self.job.accessKeyId:
            self.vmms.safeDestroyVM(self.job.vm)
        elif return_vm:
            self.preallocator.freeVM(self.job.vm)
        else:
            self.vmms.safeDestroyVM(self.job.vm)
            if replace_vm:
                self.preallocator.createVM(self.job.vm)

            # Important: don't remove the VM from the pool until its
            # replacement has been created. Otherwise there is a
            # potential race where the job manager thinks that the
            # pool is empty and creates a spurious vm.
            self.preallocator.removeVM(self.job.vm)

    def rescheduleJob(self, hdrfile, ret, err):
        """ rescheduleJob - Reschedule a job that has failed because
        of a system error, such as a VM timing out or a connection
        failure.
        """
        self.log.error("Job %s:%d failed: %s" %
                       (self.job.name, self.job.id, err))
        self.job.appendTrace(
            "%s|Job %s:%d failed: %s" %
            (datetime.now().ctime(),
             self.job.name,
             self.job.id,
             err))

        # Try a few times before giving up
        if self.job.retries < Config.JOB_RETRIES:
            try:
                os.remove(hdrfile)
            except OSError:
                pass
            self.detachVM(return_vm=False, replace_vm=True)
            self.jobQueue.unassignJob(self.job.id)

        # Here is where we give up
        else:
            self.jobQueue.makeDead(self.job.id, err)

            self.appendMsg(
                hdrfile,
                "Internal error: Unable to complete job after %d tries. Pleae resubmit" %
                (Config.JOB_RETRIES))
            self.appendMsg(
                hdrfile,
                "Job status: waitVM=%s copyIn=%s runJob=%s copyOut=%s" %
                (ret["waitvm"],
                 ret["copyin"],
                    ret["runjob"],
                    ret["copyout"]))

            self.catFiles(hdrfile, self.job.outputFile)
            self.detachVM(return_vm=False, replace_vm=True)
            self.notifyServer(self.job)

    def appendMsg(self, filename, msg):
        """ appendMsg - Append a timestamped Tango message to a file
        """
        f = open(filename, "a")
        f.write("Autograder [%s]: %s\n" % (datetime.now().ctime(), msg))
        f.close()

    def catFiles(self, f1, f2):
        """ catFiles - cat f1 f2 > f2, where f1 is the Tango header
        and f2 is the output from the Autodriver
        """
        self.appendMsg(f1, "Here is the output from the autograder:\n---")
        (wfd, tmpname)=tempfile.mkstemp(dir=os.path.dirname(f2))
        wf=os.fdopen(wfd, "ab")
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

    def notifyServer(self, job):
        try:
            if job.notifyURL:
                outputFileName = job.outputFile.split(
                    "/")[-1]  # get filename from path
                fh = open(job.outputFile, 'rb')
                files = {'file': str(fh.read(), errors='ignore')}
                hdrs = {'Filename': outputFileName}
                self.log.debug("Sending request to %s" % job.notifyURL)
                response = requests.post(
                    job.notifyURL, files=files, headers=hdrs, verify=False)
                self.log.info("Response from callback to %s:%s" %
                              (job.notifyURL, response.content))
                fh.close()
        except Exception as e:
            self.log.debug("Error in notifyServer: %s" % str(e))

    #
    # Main worker function
    #
    def run(self):
        """run - Step a job through its execution sequence
        """
        try:
            # Hash of return codes for each step
            ret = {}
            ret["waitvm"] = None
            ret["copyin"] = None
            ret["runjob"] = None
            ret["copyout"] = None

            self.log.debug("Run worker")
            vm = None

            # Header message for user
            hdrfile = tempfile.mktemp()
            self.appendMsg(hdrfile, "Received job %s:%d" %
                           (self.job.name, self.job.id))

            # Assigning job to a preallocated VM
            if self.preVM:  # self.preVM:
                self.log.debug("Assigning job to preallocated VM")
                self.job.vm = self.preVM
                self.job.updateRemote()
                self.log.info("Assigned job %s:%d existing VM %s" %
                              (self.job.name, self.job.id,
                               self.vmms.instanceName(self.preVM.id,
                                                      self.preVM.name)))
                self.job.appendTrace("%s|Assigned job %s:%d existing VM %s" %
                                     (datetime.now().ctime(),
                                      self.job.name, self.job.id,
                                      self.vmms.instanceName(self.preVM.id,
                                                             self.preVM.name)))
                self.log.debug("Assigned job to preallocated VM")
            # Assigning job to a new VM
            else:
                self.log.debug("Assigning job to a new VM")
                self.job.vm.id = self.job.id
                self.job.updateRemote()

                self.log.info("Assigned job %s:%d new VM %s" %
                              (self.job.name, self.job.id,
                               self.vmms.instanceName(self.job.vm.id,
                                                      self.job.vm.name)))
                self.job.appendTrace(
                    "%s|Assigned job %s:%d new VM %s" %
                    (datetime.now().ctime(),
                     self.job.name,
                     self.job.id,
                     self.vmms.instanceName(
                        self.job.vm.id,
                        self.job.vm.name)))

                # Host name returned from EC2 is stored in the vm object
                self.vmms.initializeVM(self.job.vm)
                self.log.debug("Asigned job to a new VM")

            vm = self.job.vm

            # Wait for the instance to be ready
            self.log.debug("Job %s:%d waiting for VM %s" %
                           (self.job.name, self.job.id,
                            self.vmms.instanceName(vm.id, vm.name)))
            self.job.appendTrace("%s|Job %s:%d waiting for VM %s" %
                                 (datetime.now().ctime(),
                                  self.job.name, self.job.id,
                                  self.vmms.instanceName(vm.id, vm.name)))
            self.log.debug("Waiting for VM")
            ret["waitvm"] = self.vmms.waitVM(vm,
                                             Config.WAITVM_TIMEOUT)

            self.log.debug("Waited for VM")

            # If the instance did not become ready in a reasonable
            # amount of time, then reschedule the job, detach the VM,
            # and exit worker
            if ret["waitvm"] == -1:
                Config.waitvm_timeouts += 1
                self.rescheduleJob(
                    hdrfile,
                    ret,
                    "Internal error: waitVM timeout after %d secs" %
                    Config.WAITVM_TIMEOUT)

                # Thread Exit after waitVM timeout
                return

            self.log.info("VM %s ready for job %s:%d" %
                          (self.vmms.instanceName(vm.id, vm.name),
                           self.job.name, self.job.id))
            self.job.appendTrace("%s|VM %s ready for job %s:%d" %
                                 (datetime.now().ctime(),
                                  self.vmms.instanceName(vm.id, vm.name),
                                  self.job.name, self.job.id))

            # Copy input files to VM
            ret["copyin"] = self.vmms.copyIn(vm, self.job.input)
            if ret["copyin"] != 0:
                Config.copyin_errors += 1
            self.log.info("Input copied for job %s:%d [status=%d]" %
                          (self.job.name, self.job.id, ret["copyin"]))
            self.job.appendTrace("%s|Input copied for job %s:%d [status=%d]" %
                                 (datetime.now().ctime(),
                                  self.job.name,
                                  self.job.id, ret["copyin"]))

            # Run the job on the virtual machine
            ret["runjob"] = self.vmms.runJob(
                vm, self.job.timeout, self.job.maxOutputFileSize)
            if ret["runjob"] != 0:
                Config.runjob_errors += 1
                if ret["runjob"] == -1:
                    Config.runjob_timeouts += 1
            self.log.info("Job %s:%d executed [status=%s]" %
                          (self.job.name, self.job.id, ret["runjob"]))
            self.job.appendTrace("%s|Job %s:%d executed [status=%s]" %
                                 (datetime.now().ctime(),
                                  self.job.name, self.job.id,
                                  ret["runjob"]))

            # Copy the output back.
            ret["copyout"] = self.vmms.copyOut(vm, self.job.outputFile)
            if ret["copyout"] != 0:
                Config.copyout_errors += 1
            self.log.info("Output copied for job %s:%d [status=%d]" %
                          (self.job.name, self.job.id, ret["copyout"]))
            self.job.appendTrace("%s|Output copied for job %s:%d [status=%d]"
                                 % (datetime.now().ctime(),
                                     self.job.name,
                                     self.job.id, ret["copyout"]))

            # Job termination. Notice that Tango considers
            # things like runjob timeouts and makefile errors to be
            # normal termination and doesn't reschedule the job.
            self.log.info("Success: job %s:%d finished" %
                          (self.job.name, self.job.id))

            # Move the job from the live queue to the dead queue
            # with an explanatory message
            msg = "Success: Autodriver returned normally"
            (returnVM, replaceVM) = (True, False)
            if ret["copyin"] != 0:
                msg = "Error: Copy in to VM failed (status=%d)" % (
                    ret["copyin"])
            elif ret["runjob"] != 0:
                if ret["runjob"] == 1:  # This should never happen
                    msg = "Error: Autodriver usage error (status=%d)" % (
                        ret["runjob"])
                elif ret["runjob"] == 2:
                    msg = "Error: Job timed out after %d seconds" % (
                        self.job.timeout)
                elif (ret["runjob"] == 3):  # EXIT_OSERROR in Autodriver
                    # Abnormal job termination (Autodriver encountered an OS
                    # error).  Assume that the VM is damaged. Destroy this VM
                    # and do not retry the job since the job may have damaged
                    # the VM.
                    msg = "Error: OS error while running job on VM"
                    (returnVM, replaceVM) = (False, True)
                else:  # This should never happen
                    msg = "Error: Unknown autodriver error (status=%d)" % (
                        ret["runjob"])

            elif ret["copyout"] != 0:
                msg += "Error: Copy out from VM failed (status=%d)" % (
                    ret["copyout"])

            self.jobQueue.makeDead(self.job.id, msg)

            # Update the text that users see in the autograder output file
            self.appendMsg(hdrfile, msg)
            self.catFiles(hdrfile, self.job.outputFile)

            # Thread exit after termination
            self.detachVM(return_vm=returnVM, replace_vm=replaceVM)
            self.notifyServer(self.job)
            return

        #
        # Exception: ec2CallError - Raised by ec2Call()
        #
        except Exception as err:
            self.log.exception("Internal Error")
            self.appendMsg(self.job.outputFile,
                           "Internal Error: %s" % err)
            # if vm is set, then the normal job assignment completed,
            # and detachVM can be run
            # if vm is not set but self.preVM is set, we still need
            # to return the VM, but have to initialize self.job.vm first
            if self.preVM and not vm:
               vm = self.job.vm = self.preVM
            if vm:
               self.detachVM(return_vm=False, replace_vm=True)
