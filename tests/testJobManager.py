import unittest
import redis
from mock import MagicMock, patch

from jobManager import JobManager
from jobQueue import JobQueue
from tangoObjects import TangoJob, TangoMachine
from config import Config
from preallocator import *


class TestJobManager(unittest.TestCase):
    def createTangoMachine(self, image, vmms, vmObj={"cores": 1, "memory": 512}):
        """createTangoMachine - Creates a tango machine object from image"""
        return TangoMachine(
            name=image,
            vmms=vmms,
            image="%s" % (image),
            cores=vmObj["cores"],
            memory=vmObj["memory"],
            disk=None,
            network=None,
        )

    def setUp(self):

        if Config.USE_REDIS:
            __db = redis.StrictRedis(Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
            __db.flushall()

        if Config.VMMS_NAME == "ec2SSH":
            from vmms.ec2SSH import Ec2SSH

            vmms = Ec2SSH()
            self.preallocator = Preallocator({"ec2SSH": vmms})

        elif Config.VMMS_NAME == "localDocker":
            from vmms.localDocker import LocalDocker

            vmms = LocalDocker()
            self.preallocator = Preallocator({"localDocker": vmms})

        elif Config.VMMS_NAME == "distDocker":
            from vmms.distDocker import DistDocker

            vmms = DistDocker()
            self.preallocator = Preallocator({"distDocker": vmms})
        else:
            vmms = None
            self.preallocator = Preallocator({"default": vmms})

        self.job1 = TangoJob(
            name="sample_job_1",
            vm="ilter.img",
            outputFile="sample_job_1_output",
            input=[],
            timeout=30,
            notifyURL="notifyMeUrl",
            maxOutputFileSize=4096,
        )

        self.job2 = TangoJob(
            name="sample_job_2",
            vm="ilter.img",
            outputFile="sample_job_2_output",
            input=[],
            timeout=30,
            notifyURL="notifyMeUrl",
            maxOutputFileSize=4096,
        )

        self.jobQueue = JobQueue(self.preallocator)
        self.jobQueue.reset()
        self.jobManager = JobManager(self.jobQueue)
        self.vm = self.createTangoMachine(image="autograding_image", vmms=vmms)

    def test_start(self):
        self.jobManager.start()
        self.assertTrue(self.jobManager.running)

    def test__getNextID(self):
        init_id = self.jobManager.nextId
        for i in range(1, Config.MAX_JOBID + 100):
            id = self.jobManager._getNextID()
            self.assertEqual(init_id + i - 1, id)
        self.jobManager.nextId = init_id

    def test_manage_worker_works(self):
        def mock_getNextPendingJob():
            time.sleep(0.2)
            self.job1.setId(1)
            return self.job1

        def mock_reuseVM(job):
            job.assigned = True
            job.vm = self.vm
            self.preallocator.vmms[job.vm.vmms] = self.jobManager.vmms
            return self.vm

        def mock_worker_init(job, vmms, jobQueue, preallocator, preVM):
            pass

        self.jobQueue.assignJob = MagicMock()
        with patch(
            "jobQueue.JobQueue.getNextPendingJob", side_effect=mock_getNextPendingJob
        ), patch("jobQueue.JobQueue.reuseVM", side_effect=mock_reuseVM), patch(
            "worker.Worker.__init__", side_effect=mock_worker_init
        ):
            self.jobManager.start()
            time.sleep(2)
            self.jobQueue.assignJob.assert_called()

    def test_manage_worker_fails(self):
        def mock_getNextPendingJob():
            time.sleep(2)
            self.job1.setId(1)
            return self.job1

        def mock_reuseVM(job):
            job.assigned = True
            job.vm = self.vm
            self.preallocator.vmms[job.vm.vmms] = self.jobManager.vmms
            return self.vm

        def mock_worker_init(job, vmms, jobQueue, preallocator, preVM):
            raise RuntimeError("Job failed")

        self.jobQueue.assignJob = MagicMock()
        self.jobQueue.makeDead = MagicMock()

        with patch(
            "jobQueue.JobQueue.getNextPendingJob", side_effect=mock_getNextPendingJob
        ), patch("jobQueue.JobQueue.reuseVM", side_effect=mock_reuseVM), patch(
            "worker.Worker.__init__", side_effect=mock_worker_init
        ):
            self.jobManager.start()
            time.sleep(4)
            self.jobQueue.makeDead.assert_called_once()


if __name__ == "__main__":
    unittest.main()
