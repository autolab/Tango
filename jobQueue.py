#
# jobQueue.py - Code that manipulates and manages the job queue
#
# JobQueue: Class that creates the job queue and provides functions
# for manipulating it.
#
# JobManager: Class that creates a thread object that looks for new
# work on the job queue and assigns it to workers.
#
import time, threading, logging

from config import *
from tangoObjects import *
from worker import Worker

 
#
# JobQueue - This class defines the job queue and the functions for
# manipulating it. The actual queue is made up of two smaller
# sub-lists:
#
# - The active list is a dictionary, keyed off job ID, that holds all
#   jobs that are active, including those not yet assigned to a worker
#   thread.  The trace attribute of a job being None indicates that
#   the job is not yet assigned.  Only the JobManager thread can
#   assign jobs to Workers.
#
# - The dead list is a dictionary of the jobs that have completed.
#
class JobQueue:
    def __init__(self, preallocator):
        self.jobQueue = TangoDictionary("jobQueue")
        self.deadJobs = TangoDictionary("deadJobs")
        self.queueLock = threading.Lock()
        self.preallocator = preallocator
        self.log = logging.getLogger("JobQueue")
        self.nextID= 1

    def _getNextID(self):
        """_getNextID - updates and returns the next ID to be used for a job

        Jobs have ID's between 1 and MAX_JOBID.
        """
        self.log.debug("_getNextID|Acquiring lock to job queue.")
        self.queueLock.acquire()
        self.log.debug("_getNextID|Acquired lock to job queue.")
        id = self.nextID

        # If a job already exists in the queue at nextID, then try to find
        # an empty ID. If the queue is full, then return -1.
        keys = self.jobQueue.keys()
        if (id in keys):
            id = -1
            for i in xrange(1, Config.MAX_JOBID + 1):
                if (i not in keys):
                    id = i
                    break

        self.nextID += 1
        if self.nextID > Config.MAX_JOBID:
            self.nextID = 1
        self.queueLock.release()
        self.log.debug("_getNextID|Released lock to job queue.")
        return id

    def add(self, job):
        """add - add job to live queue

        This function assigns an ID number to a job and then adds it
        to the queue of live jobs.
        """
        if (not isinstance(job,TangoJob)):
            return -1
        self.log.debug("add|Getting next ID")
        job.id = self._getNextID()
        if (job.id == -1):
            self.log.debug("add|JobQueue is full")
            return -1
        self.log.debug("add|Gotten next ID")
        job.assigned = False
        job.retries = 0
        job.trace = []

        # Add the job to the queue. Careful not to append the trace until we
        # know the job has actually been added to the queue.
        self.log.debug("add|Acquiring lock to job queue.")
        self.queueLock.acquire()
        self.jobQueue.set(job.id, job)
        job.trace.append("%s|Added job %s:%d to queue" %
                (time.ctime(time.time()+time.timezone), job.name, job.id))
        self.queueLock.release()
        self.log.debug("add|Releasing lock to job queue.")

        self.log.info("Added job %s:%d to queue" % (job.name, job.id))
        return job.id

    def addDead(self, job):
        """ addDead - add a job to the dead queue.

        Called by validateJob when a job validation fails.
        """
        if (not isinstance(job,TangoJob)):
            return -1
        job.id = self._getNextID()
        job.assigned = False
        job.retries = 0
        if not job.trace:
            job.trace = []
        self.queueLock.acquire()
        self.deadJobs.set(job.id, job)
        self.queueLock.release()
        return job.id

    def remove(self, id):
        """remove - Remove job from live queue
        """
        status = -1
        self.queueLock.acquire()
        if str(id) in self.jobQueue.keys():
            self.jobQueue.delete(id)
            status = 0
        self.queueLock.release()

        if status == 0:
            self.log.debug("Removed job %d from queue" % id)
        else:
            self.log.error("Job %d not found in queue" % id)
        return status

    def delJob(self, id, deadjob):
        """ delJob - Implements delJob() interface call
        @param id - The id of the job to remove
        @param deadjob - If 0, move the job from the live queue to the
        dead queue. If non-zero, remove the job from the dead queue
        and discard.
        """
        if deadjob == 0:
            return self.makeDead(id, "Requested by operator")
        else:
            status = -1
            self.queueLock.acquire()
            if str(id) in self.deadJobs.keys():
                self.deadJobs.delete(id)
                status = 0
            self.queueLock.release()

            if status == 0:
                self.log.debug("Removed job %d from dead queue" % id)
            else:
                self.log.error("Job %d not found in dead queue" % id)
            return status


    def get(self, id):
        """get - retrieve job from live queue
        @param id - the id of the job to retrieve
        """
        self.queueLock.acquire()
        if str(id) in self.jobQueue.keys():
            job = self.jobQueue.get(id)
        else:
            job = None
        self.queueLock.release()
        return job

    def getNextPendingJob(self):
        """getNextPendingJob - Returns ID of next pending job from queue.
        Called by JobManager when Config.REUSE_VMS==False
        """
        self.queueLock.acquire()
        for id,job in self.jobQueue.iteritems():
            if job.assigned == False:
                self.queueLock.release()
                return id
        self.queueLock.release()
        return None

    def getNextPendingJobReuse(self):
        """getNextPendingJobReuse - Returns ID of next pending job and its VM.
        Called by JobManager when Config.REUSE_VMS==True
        """
        self.queueLock.acquire()
        for id, job in self.jobQueue.iteritems():

            # Create a pool if necessary
            if self.preallocator.poolSize(job.vm.name) == 0:
                self.preallocator.update(job.vm, Config.POOL_SIZE)

            # If the job hasn't been assigned to a worker yet, see if there
            # is a free VM
            if (job.assigned == False):
                vm = self.preallocator.allocVM(job.vm.name)
                if vm:
                    self.queueLock.release()
                    return (id, vm)

        self.queueLock.release()
        return (None, None)

    def assignJob(self, job):
        """ assignJob - marks a job to be assigned
        """
        self.queueLock.acquire()
        job.assigned = True
        self.queueLock.release()

    def unassignJob(self, job):
        """ assignJob - marks a job to be unassigned
        """
        self.queueLock.acquire()
        job.assigned = False;
        if job.retries is None:
            job.retries = 0
        else:
            job.retries += 1
            Config.job_retries += 1
        self.queueLock.release()

    def makeDead(self, id, reason):
        """ makeDead - move a job from live queue to dead queue
        """
        self.queueLock.acquire()
        status = -1
        if str(id) in self.jobQueue.keys():
            status = 0
            job = self.jobQueue.get(id)
            self.jobQueue.delete(id)
            if job.trace is None:
                job.trace = []
            job.trace.append("%s|%s" %  (time.ctime(time.time()+time.timezone), reason))
            self.log.info("Terminated job %s:%d: %s" %
                          (job.name, job.id, reason))
            self.deadJobs.set(id, job)
        self.queueLock.release()
        return status

    def getInfo(self):

        info = {}
        info['size'] = len(self.jobQueue.keys())
        info['size_deadjobs'] = len(self.deadJobs.keys())

        return info
