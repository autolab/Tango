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
		self.jobQueue = {}
		self.deadJobs = {}
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
		if (id in self.jobQueue):
			id = -1
			for i in xrange(1, Config.MAX_JOBID + 1):
				if (i not in self.jobQueue):
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
		self.jobQueue[job.id] = job
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
		self.deadJobs[job.id] = job
		self.queueLock.release()
		return job.id

	def remove(self, id):
		"""remove - Remove job from live queue
		"""
		status = -1
		self.queueLock.acquire()
		if id in self.jobQueue:
			del self.jobQueue[id]
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
			return makeDead(id, "Requested by operator")
		else:
			status = -1
			self.queueLock.acquire()
			if id in self.deadJobs:
				del self.deadJobs[id]
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
		if id in self.jobQueue:
			job = self.jobQueue[id]
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
		if id in self.jobQueue:
			status = 0
			job = self.jobQueue[id]
			del self.jobQueue[id]
			if job.trace is None:
				job.trace = []
			job.trace.append("%s|%s" %  (time.ctime(time.time()+time.timezone), reason))
			self.log.info("Terminated job %s:%d: %s" %
						  (job.name, job.id, reason))
			self.deadJobs[id] = job
		self.queueLock.release()
		return status

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
					self.jobQueue.assignJob(job)

					# Try to find a vm on the free list and allocate it to
					# the worker if successful.
					if Config.REUSE_VMS:
						preVM = vm
					else:
						preVM = self.preallocator.allocVM(job.vm.name)

					# Now dispatch the job to a worker
					self.log.info("Dispatched job %s:%d [try %d]" %
								  (job.name, job.id, job.retries))
					job.trace.append("%s|Dispatched job %s:%d [try %d]" %
									 (time.ctime(time.time()+time.timezone), job.name, job.id,
									  job.retries))
					vmms = self.vmms[job.vm.vmms] # Create new vmms object
					worker = Worker(job, vmms, self.jobQueue, self.preallocator, preVM).start()

				except Exception, err:
					self.jobQueue.makeDead(job.id, str(err))


			# Sleep for a bit and then check again
			time.sleep(Config.DISPATCH_PERIOD)
