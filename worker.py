#
# worker.py - Thread that shepherds a job through it execution sequence
#
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
        self.log = logging.getLogger("Worker-" + str(os.getpid()))

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
            # put vm into free pool.  may destroy it if free pool is over low water mark
            self.preallocator.freeVM(self.job.vm)
        else:
            self.vmms.safeDestroyVM(self.job.vm)
            if replace_vm:
                self.preallocator.createVM(self.job.vm)

            # Important: don't remove the VM from the pool until its
            # replacement has been created. Otherwise there is a
            # potential race where the job manager thinks that the
            # pool is empty and creates a spurious vm.
            self.log.info("removeVM %s" % self.job.vm.id);
            self.preallocator.removeVM(self.job.vm)

    def rescheduleJob(self, hdrfile, ret, err):
        """ rescheduleJob - Reschedule a job that has failed because
        of a system error, such as a VM timing out or a connection
        failure.
        """

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
        f.write("Autolab [%s]: %s\n" % (datetime.now().ctime(), msg))
        f.close()

    def catFiles(self, f1, f2):
        """ catFiles - cat f1 f2 > f2, where f1 is the Tango header
        and f2 is the output from the Autodriver
        """
        self.appendMsg(f1, "Output of autodriver from grading VM:\n")
        (wfd, tmpname)=tempfile.mkstemp(dir=os.path.dirname(f2))
        wf=os.fdopen(wfd, "a")
        with open(f1, "rb") as f1fd:
            shutil.copyfileobj(f1fd, wf)
        # f2 may not exist if autodriver failed
        try:
            with open(f2, "rb") as f2fd:
                shutil.copyfileobj(f2fd, wf)
        except IOError:
            wf.write("NO OUTPUT FILE\n")

        wf.close()
        os.rename(tmpname, f2)
        os.remove(f1)

    def notifyServer(self, job):
        try:
            if job.notifyURL:
                outputFileName = job.outputFile.split(
                    "/")[-1]  # get filename from path
                fh = open(job.outputFile, 'rb')
                files = {'file': unicode(fh.read(), errors='ignore')}
                hdrs = {'Filename': outputFileName}
                self.log.debug("Sending request to %s" % job.notifyURL)
                response = requests.post(
                    job.notifyURL, files=files, headers=hdrs, verify=False)
                self.log.info("Response from callback to %s:%s" %
                              (job.notifyURL, response.content))
                fh.close()
        except Exception as e:
            self.log.debug("Error in notifyServer: %s" % str(e))

    def afterJobExecution(self, hdrfile, msg, vmHandling):
      (returnVM, replaceVM) = vmHandling
      self.jobQueue.makeDead(self.job.id, msg)

      # Update the text that users see in the autodriver output file
      self.appendMsg(hdrfile, msg)
      self.catFiles(hdrfile, self.job.outputFile)

      # Thread exit after termination
      self.detachVM(return_vm=returnVM, replace_vm=replaceVM)
      self.notifyServer(self.job)
      return

    def jobLogAndTrace(self, stageMsg, vm, status=None):
      msg = stageMsg + " %s for job %s:%d" % (self.vmms.instanceName(vm.id, vm.name),
                                              self.job.name, self.job.id)
      if (status != None):
        if (status == 0):
          msg = "done " + msg
        else:
          msg = "failed " + msg + " (status=%d)" % status
      self.log.info(msg)
      self.job.appendTrace(msg)

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
                self.job.vm = self.preVM
                self.job.updateRemote()
                self.jobLogAndTrace("assigned VM (preallocated)", self.preVM)

            # Assigning job to a new VM
            else:
                self.job.vm.id = self.job.id
                self.job.updateRemote()

                # Host name returned from EC2 is stored in the vm object
                self.vmms.initializeVM(self.job.vm)
                self.jobLogAndTrace("assigned VM (just initialized)", self.job.vm)

            vm = self.job.vm
            (returnVM, replaceVM) = (True, False)

            # Wait for the instance to be ready
            self.jobLogAndTrace("waiting for VM", vm)
            ret["waitvm"] = self.vmms.waitVM(vm,
                                             Config.WAITVM_TIMEOUT)
            self.jobLogAndTrace("waiting for VM", vm, ret["waitvm"])

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

            # Copy input files to VM
            self.jobLogAndTrace("copying to VM", vm)
            ret["copyin"] = self.vmms.copyIn(vm, self.job.input)
            self.jobLogAndTrace("copying to VM", vm, ret["copyin"])
            if ret["copyin"] != 0:
                Config.copyin_errors += 1
                msg = "Error: Copy in to VM failed (status=%d)" % (ret["copyin"])
                self.afterJobExecution(hdrfile, msg, (returnVM, replaceVM))
                return

            # Run the job on the virtual machine
            self.jobLogAndTrace("running on VM", vm)
            ret["runjob"] = self.vmms.runJob(
                vm, self.job.timeout, self.job.maxOutputFileSize)
            self.jobLogAndTrace("running on VM", vm, ret["runjob"])
            # runjob may have failed. but go on with copyout to get the output if any

            # Copy the output back, even if runjob has failed
            self.jobLogAndTrace("copying from VM", vm)
            ret["copyout"] = self.vmms.copyOut(vm, self.job.outputFile)
            self.jobLogAndTrace("copying from VM", vm, ret["copyout"])

            # handle failure(s) of runjob and/or copyout.  runjob error takes priority.
            if ret["runjob"] != 0:
                Config.runjob_errors += 1
                if ret["runjob"] == 1:  # This should never happen
                    msg = "Error: Autodriver usage error"
                elif ret["runjob"] == -1 or ret["runjob"] == 2:  # both are timeouts
                    Config.runjob_timeouts += 1
                    msg = "Error: Job timed out. timeout setting: %d seconds" % (
                        self.job.timeout)
                elif ret["runjob"] == 3:  # EXIT_OSERROR in Autodriver
                    # Abnormal job termination (Autodriver encountered an OS
                    # error).  Assume that the VM is damaged. Destroy this VM
                    # and do not retry the job since the job may have damaged
                    # the VM.
                    msg = "Error: OS error while running job on VM"
                    (returnVM, replaceVM) = (False, True)
                    # doNotDestroy, combined with KEEP_VM_AFTER_FAILURE, will sent
                    # the vm aside for further investigation after failure.
                    self.job.vm.keepForDebugging = True
                    self.job.vm.notes = str(self.job.id) + "_" + self.job.name
                else:  # This should never happen
                    msg = "Error: Unknown autodriver error (status=%d)" % (
                        ret["runjob"])
            elif ret["copyout"] != 0:
                Config.copyout_errors += 1
                msg += "Error: Copy out from VM failed (status=%d)" % (ret["copyout"])
            else:
                msg = "Success: Autodriver returned normally"

            self.afterJobExecution(hdrfile, msg, (returnVM, replaceVM))
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
