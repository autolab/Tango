#
# JobManager - Thread that assigns jobs to worker threads
#
# The job manager thread wakes up every so often, scans the job list
# for new unassigned jobs, and tries to assign them.
#
# Assigning a job will try to get a preallocated VM that is ready,
# otherwise will pass 'None' as the preallocated vm.  A worker thread
# is launched that will handle things from here on. If anything goes
# wrong, the job is made dead with the error.
#
import time, threading, logging

from config import Config
from worker import Worker

from jobQueue import JobQueue
from preallocator import Preallocator

class JobManager:
    
    def __init__(self, queue, vmms, preallocator):
        self.daemon = True
        self.jobQueue = queue
        self.vmms = vmms
        self.preallocator = preallocator
        self.log = logging.getLogger("JobManager")
        threading.Thread(target=self.__manage).start()


    def __manage(self):
        while True:
            if Config.REUSE_VMS:
                id,vm  = self.jobQueue.getNextPendingJobReuse()
            else:
                id = self.jobQueue.getNextPendingJob()

            if id:
                job = self.jobQueue.get(id)
                try:
                    # Mark the job assigned
                    self.jobQueue.assignJob(job.id)

                    # Try to find a vm on the free list and allocate it to
                    # the worker if successful.
                    if Config.REUSE_VMS:
                        preVM = vm
                    else:
                        preVM = self.preallocator.allocVM(job.vm.name)

                    # Now dispatch the job to a worker
                    self.log.info("Dispatched job %s:%d to %s [try %d]" %
                                  (job.name, job.id, preVM.name, job.retries))
                    job.appendTrace("%s|Dispatched job %s:%d [try %d]" %
                                     (time.ctime(time.time()+time.timezone), job.name, job.id,
                                      job.retries))
                    vmms = self.vmms[job.vm.vmms] # Create new vmms object
                    Worker(job, vmms, self.jobQueue, self.preallocator, preVM).start()

                except Exception, err:
                    self.jobQueue.makeDead(job.id, str(err))


            # Sleep for a bit and then check again
            time.sleep(Config.DISPATCH_PERIOD)


if __name__ == "__main__":

    if not Config.USE_REDIS:
        print("You need to have Redis running to be able to initiate stand-alone\
         JobManager")
    else:
        vmms = None

        if Config.VMMS_NAME == "localSSH":
            from vmms.localSSH import LocalSSH
            vmms = LocalSSH()
        elif Config.VMMS_NAME == "tashiSSH":
            from vmms.tashiSSH import TashiSSH
            vmms = TashiSSH()
        elif Config.VMMS_NAME == "ec2SSH":
            from vmms.ec2SSH import Ec2SSH
            vmms = Ec2SSH()
        elif Config.VMMS_NAME == "localDocker":
            from vmms.localDocker import LocalDocker
            vmms = LocalDocker()

        vmms = {Config.VMMS_NAME: vmms}
        preallocator = Preallocator(vmms)
        queue = JobQueue(preallocator)

        JobManager(queue, vmms, preallocator)

        print("Starting the stand-alone Tango JobManager")

