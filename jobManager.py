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
import threading, logging, time, copy

from datetime import datetime
from tango import *
from jobQueue import JobQueue
from preallocator import Preallocator
from worker import Worker

from tangoObjects import TangoQueue
from config import Config

class JobManager:

    def __init__(self, queue):
        self.daemon = True
        self.jobQueue = queue
        self.preallocator = self.jobQueue.preallocator
        self.vmms = self.preallocator.vmms
        self.log = logging.getLogger("JobManager")
        self.running = False

    def start(self):
        if self.running:
            return
        thread = threading.Thread(target=self.__manage)
        thread.daemon = True
        thread.start()

    def run(self):
        if self.running:
            return
        self.__manage()

    def __manage(self):
        self.running = True
        # job-associated instance id
        nextId = 10000
        while True:
            id = self.jobQueue.getNextPendingJob()

            if id:
                job = self.jobQueue.get(id)
                if not job.accessKey and Config.REUSE_VMS:
                    id, vm = self.jobQueue.getNextPendingJobReuse(id)
                    job = self.jobQueue.get(id)

                try:
                    # Mark the job assigned
                    self.jobQueue.assignJob(job.id)
                    # if the has specified an account
                    # create an VM on the account and run on that instance
                    if job.accessKeyId:
                        from vmms.ec2SSH import Ec2SSH
                        vmms = Ec2SSH(job.accessKeyId, job.accessKey)
                        newVM = copy.deepcopy(job.vm)
                        newVM.id = nextId
                        preVM = vmms.initializeVM(newVM)
                        if nextId > 99999:
                            nextId = 1000
                        else:
                            nextId += 1
                    else:
                        # Try to find a vm on the free list and allocate it to
                        # the worker if successful.
                        if Config.REUSE_VMS:
                            preVM = vm
                        else:
                            preVM = self.preallocator.allocVM(job.vm.name)
                        vmms = self.vmms[job.vm.vmms]  # Create new vmms object

                    # Now dispatch the job to a worker
                    self.log.info("Dispatched job %s:%d to %s [try %d]" %
                                  (job.name, job.id, preVM.name, job.retries))
                    job.appendTrace(
                        "%s|Dispatched job %s:%d [try %d]" %
                        (datetime.utcnow().ctime(), job.name, job.id, job.retries))

                    Worker(
                        job,
                        vmms,
                        self.jobQueue,
                        self.preallocator,
                        preVM
                    ).start()

                except Exception as err:
                    self.jobQueue.makeDead(job.id, str(err))

            # Sleep for a bit and then check again
            time.sleep(Config.DISPATCH_PERIOD)


if __name__ == "__main__":

    if not Config.USE_REDIS:
        print("You need to have Redis running to be able to initiate stand-alone\
         JobManager")
    else:
        tango = TangoServer()
        tango.log.debug("Resetting Tango VMs")
        tango.resetTango(tango.preallocator.vmms)
        for key in tango.preallocator.machines.keys():
            tango.preallocator.machines.set(key, [[], TangoQueue(key)])
        jobs = JobManager(tango.jobQueue)

        print("Starting the stand-alone Tango JobManager")
        jobs.run()
