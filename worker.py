#
# worker.py - Thread that shepherds a job through it execution sequence
#
import threading, time, logging, tempfile, requests, subprocess

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
class Worker( threading.Thread ):
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
        if return_vm:
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
        self.job.trace.append("%s|Job %s:%d failed: %s" % (time.ctime(time.time()+time.timezone),
                                                           self.job.name, self.job.id, err))

        # Try a few times before giving up
        if self.job.retries < Config.JOB_RETRIES:
            subprocess.call("rm -f %s" % (hdrfile), shell=True)
            self.detachVM(return_vm=False, replace_vm=True)
            self.jobQueue.unassignJob(self.job)

        # Here is where we give up
        else:
            self.jobQueue.makeDead(self.job.id, err)
            self.appendMsg(hdrfile, "Internal error: Unable to complete job after %d tries. Pleae resubmit"  % (Config.JOB_RETRIES))
            self.appendMsg(hdrfile, "Job status: waitVM=%s copyIn=%s runJob=%s copyOut=%s" % (ret["waitvm"], ret["copyin"], ret["runjob"], ret["copyout"]))
            self.catFiles(hdrfile, self.job.outputFile)
            self.detachVM(return_vm=False, replace_vm=True)
            self.notifyServer(self.job)

    def appendMsg(self, filename, msg):
        """ appendMsg - Append a timestamped Tango message to a file
        """
        f = open(filename, "a")
        f.write("Autograder [%s]: %s\n" % (time.ctime(time.time()+time.timezone), msg))
        f.close

    def catFiles(self, f1, f2):
        """ catFiles - cat f1 f2 > f2, where f1 is the Tango header
        and f2 is the output from the Autodriver
        """
        self.appendMsg(f1, "Here is the output from the autograder:\n---")
        tmpname = tempfile.mktemp()
        subprocess.call("touch %s" % f2, shell=True) # in case no autograder output
        subprocess.call("cat %s %s > %s" % (f1, f2, tmpname), shell=True)
        subprocess.call("mv -f %s %s" % (tmpname, f2), shell=True)
        subprocess.call("rm -f %s %s" % (f1, tmpname), shell=True)


    def notifyServer(self, job):
        try:
            if job.notifyURL:
                outputFileName = job.outputFile.split("/")[-1] # get filename from path
                fh = open(job.outputFile, 'rb')
                files = {'file': unicode(fh.read(), errors='ignore')}
                hdrs = {'Filename': outputFileName}
                self.log.debug("Sending request to %s" % job.notifyURL)
                response = requests.post(job.notifyURL, files = files, headers = hdrs, verify=False)
                self.log.info("Response from callback to %s:%s" % (job.notifyURL, response.content))
                fh.close()
        except Exception as e:
            self.log.debug("Error in notifyServer: %s" % str(e))

    #
    # Main worker function
    #
    def run (self):
        """run - Step a job through its execution sequence
        """
        try:
            # Hash of return codes for each step
            ret = {}
            ret["waitvm"] = None
            ret["copyin"] = None
            ret["runjob"] = None
            ret["copyout"] = None

            # Header message for user
            hdrfile = tempfile.mktemp()
            self.appendMsg(hdrfile, "Received job %s:%d" %
                           (self.job.name, self.job.id))

            vm = None

            # Assigning job to a preallocated VM
            if self.preVM: #self.preVM:
                self.job.vm = self.preVM
                self.log.info("Assigned job %s:%d existing VM %s" %
                              (self.job.name, self.job.id,
                               self.vmms.instanceName(self.preVM.id,
                                                      self.preVM.name)))
                self.job.trace.append("%s|Assigned job %s:%d existing VM %s" %
                                      (time.ctime(time.time()+time.timezone),
                                       self.job.name, self.job.id,
                                       self.vmms.instanceName(self.preVM.id,
                                                              self.preVM.name)))
            # Assigning job to a new VM
            else:
                self.job.vm.id = self.job.id
                self.log.info("Assigned job %s:%d new VM %s" %
                              (self.job.name, self.job.id,
                               self.vmms.instanceName(self.job.vm.id,
                                                      self.job.vm.name)))
                self.job.trace.append("%s|Assigned job %s:%d new VM %s" %
                                      (time.ctime(time.time()+time.timezone),
                                       self.job.name, self.job.id,
                                       self.vmms.instanceName(self.job.vm.id,
                                                              self.job.vm.name)))

                # Host name returned from EC2 is stored in the vm object
                self.vmms.initializeVM(self.job.vm)

            vm = self.job.vm

            # Wait for the instance to be ready
            self.log.debug("Job %s:%d waiting for VM %s" %
                           (self.job.name, self.job.id,
                            self.vmms.instanceName(vm.id, vm.name)))
            self.job.trace.append("%s|Job %s:%d waiting for VM %s" %
                                  (time.ctime(time.time()+time.timezone), 
                                   self.job.name, self.job.id,
                                   self.vmms.instanceName(vm.id, vm.name)))
            ret["waitvm"] = self.vmms.waitVM(vm,
                                             Config.WAITVM_TIMEOUT)

            # If the instance did not become ready in a reasonable
            # amount of time, then reschedule the job, detach the VM,
            # and exit worker
            if ret["waitvm"] == -1:
                Config.waitvm_timeouts += 1
                self.rescheduleJob(hdrfile, ret, "Internal error: waitVM timeout after %d secs" %
                                   Config.WAITVM_TIMEOUT)

                # Thread Exit after waitVM timeout
                return

            self.log.info("VM %s ready for job %s:%d" %
                          (self.vmms.instanceName(vm.id, vm.name),
                           self.job.name, self.job.id))
            self.job.trace.append("%s|VM %s ready for job %s:%d" %
                                  (time.ctime(time.time()+time.timezone),
                                   self.vmms.instanceName(vm.id, vm.name),
                                   self.job.name, self.job.id))

            # Copy input files to VM
            ret["copyin"] = self.vmms.copyIn(vm, self.job.input)
            if ret["copyin"] != 0:
                Config.copyin_errors += 1
            self.log.info("Input copied for job %s:%d [status=%d]" %
                          (self.job.name, self.job.id, ret["copyin"]))
            self.job.trace.append("%s|Input copied for job %s:%d [status=%d]" %
                                  (time.ctime(time.time()+time.timezone),
                                   self.job.name,
                                   self.job.id, ret["copyin"]))

            # Run the job on the virtual machine
            ret["runjob"] = self.vmms.runJob(vm, self.job.timeout, self.job.maxOutputFileSize)
            if ret["runjob"] != 0:
                Config.runjob_errors += 1
                if ret["runjob"] == -1:
                    Config.runjob_timeouts += 1
            self.log.info("Job %s:%d executed [status=%s]" %
                          (self.job.name, self.job.id, ret["runjob"]))
            self.job.trace.append("%s|Job %s:%d executed [status=%s]" %
                                  (time.ctime(time.time()+time.timezone),
                                   self.job.name, self.job.id,
                                   ret["runjob"]))

            # Copy the output back.
            ret["copyout"] = self.vmms.copyOut(vm, self.job.outputFile)
            if ret["copyout"] != 0:
                Config.copyout_errors += 1
            self.log.info("Output copied for job %s:%d [status=%d]" %
                          (self.job.name, self.job.id, ret["copyout"]))
            self.job.trace.append("%s|Output copied for job %s:%d [status=%d]"
                                  % (time.ctime(time.time()+time.timezone),
                                     self.job.name,
                                     self.job.id, ret["copyout"]))

            # Abnormal job termination (Autodriver encountered an OS
            # error).  Assume that the VM is damaged. Destroy this VM
            # and retry the job on another VM.
            if (ret["runjob"] == 3): # EXIT_OSERROR in Autodriver
                self.rescheduleJob(hdrfile, ret, "OS error while running job on VM")

                # Thread exit after abnormal termination
                return

            # Normal job termination. Notice that Tango considers
            # things like runjob timeouts and makefile errors to be
            # normal termination and doesn't reschedule the job.
            else:
                self.log.info("Success: job %s:%d finished" %
                              (self.job.name, self.job.id))

                # Move the job from the live queue to the dead queue
                # with an explanatory message
                msg = "Success: Autodriver returned normally"
                if ret["copyin"] != 0:
                    msg = "Error: Copy in to VM failed (status=%d)" % (ret["copyin"])
                elif ret["runjob"] != 0:
                    if ret["runjob"] == 1: # This should never happen
                        msg = "Error: Autodriver usage error (status=%d)" % (ret["runjob"])
                    elif ret["runjob"] == 2:
                        msg = "Error: Job timed out after %d seconds" % (self.job.timeout)
                    else: # This should never happen
                        msg = "Error: Unknown autodriver error (status=%d)" % (ret["runjob"])
                elif ret["copyout"] != 0:
                    msg += "Error: Copy out from VM failed (status=%d)" % (ret["copyout"])

                self.jobQueue.makeDead(self.job.id, msg)

                # Update the text that users see in the autograder output file
                self.appendMsg(hdrfile, msg)
                self.catFiles(hdrfile, self.job.outputFile)

                # Thread exit after normal termination
                self.detachVM(return_vm=True, replace_vm=False)
                self.notifyServer(self.job)
                return

        #
        # Exception: ec2CallError - Raised by ec2Call()
        #
        except Exception as err:
            self.log.debug("Internal Error: %s" % err)
            self.appendMsg(self.job.outputFile,
                           "Internal Error: %s" % err)

