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

import copy
import logging
import threading
import time
import traceback
from datetime import datetime

import tango  # Written this way to avoid circular imports
from config import Config
from jobQueue import JobQueue
from tangoObjects import TangoJob, TangoQueue, TangoMachine
from typing import List, Tuple
from worker import Worker



class JobManager(object):
    def __init__(self, queue: JobQueue):
        self.daemon = True
        self.jobQueue: JobQueue = queue
        self.preallocator = self.jobQueue.preallocator
        self.vmms = self.preallocator.vmms
        self.log = logging.getLogger("JobManager")
        # job-associated instance id
        self.nextId = 10000
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        thread = threading.Thread(target=self.__manage)
        thread.daemon = True
        thread.start()

    def run(self):
        if self.running:
            return
        self.__manage()

    def _getNextID(self):
        """_getNextID - returns next ID to be used for a job-associated
        VM.  Job-associated VM's have 5-digit ID numbers between 10000
        and 99999.
        """
        id = self.nextId
        self.nextId += 1
        if self.nextId > 99999:
            self.nextId = 10000
        return id

    def __manage(self) -> None:
        self.running = True
        while True:
            # Blocks until we get a next job
            job: TangoJob = self.jobQueue.getNextPendingJob()
            if not job.accessKey and Config.REUSE_VMS:
                self.log.info(f"job has access key {job.accessKey} and is calling reuseVM")
                vm = None
                while vm is None:
                    vm = self.jobQueue.reuseVM(job)
                    # Sleep for a bit and then check again
                    time.sleep(Config.DISPATCH_PERIOD)

            try:
                # if the job is a ec2 vmms job
                # spin up an ec2 instance for that job
                if Config.VMMS_NAME == "ec2SSH":
                    from vmms.ec2SSH import Ec2SSH

                    vmms = Ec2SSH(job.accessKeyId, job.accessKey)

                    newVM = copy.deepcopy(job.vm)
                    newVM.id = self._getNextID()
                    try:
                        vmms.initializeVM(newVM)
                        preVM = newVM
                    except Exception as e:
                        self.log.error("ERROR initialization VM: %s", e)
                        self.log.error(traceback.format_exc())
                    if preVM is None:
                        raise Exception(
                            "EC2 SSH VM initialization failed: see log"
                        )
                else:
                    self.log.info(f"job {job.id} is not an ec2 vmms job")
                    # Try to find a vm on the free list and allocate it to
                    # the worker if successful.
                    if Config.REUSE_VMS:
                        preVM = vm
                    else:
                        preVM = self.preallocator.allocVM(job.vm.name)
                    vmms = self.vmms[job.vm.vmms]  # Create new vmms object

                if preVM.name is not None:
                    self.log.info(
                        "Dispatched job %s:%d to %s [try %d]"
                        % (job.name, job.id, preVM.name, job.retries)
                    )
                else:
                    self.log.info(
                        "Unable to pre-allocate a vm for job job %s:%d [try %d]"
                        % (job.name, job.id, job.retries)
                    )

                job.appendTrace(
                    "%s|Dispatched job %s:%d [try %d]"
                    % (datetime.utcnow().ctime(), job.name, job.id, job.retries)
                )
                # Mark the job assigned
                self.jobQueue.assignJob(job.id, preVM)
                Worker(
                    job, vmms, self.jobQueue, self.preallocator, preVM
                ).start()

            except Exception as err:
                if job is None:
                    self.log.info("job_manager: job is None")
                else:
                    self.log.error("job failed during creation %d %s" % (job.id, str(err)))
                    self.jobQueue.makeDead(job, str(err))


if __name__ == "__main__":

    if not Config.USE_REDIS:
        print(
            "You need to have Redis running to be able to initiate stand-alone\
         JobManager"
        )
    else:
        tango_server = tango.TangoServer()
        tango_server.log.debug("Resetting Tango VMs")
        tango_server.resetTango(tango_server.preallocator.vmms)
        for key in tango_server.preallocator.machines.keys():
            machine: Tuple[List[TangoMachine], TangoQueue] = ([], TangoQueue.create(key))
            machine[1].make_empty()
            tango_server.preallocator.machines.set(key, machine)

            # The above call sets the total pool empty.  But the free pool which
            # is a queue in redis, may not be empty.  When the job manager restarts,
            # resetting the free queue using the key doesn't change its content.
            # Therefore we empty the queue, thus the free pool, to keep it consistent
            # with the total pool.
        jobs = JobManager(tango_server.jobQueue)

        tango_server.log.info("Starting the stand-alone Tango JobManager")
        jobs.run()
