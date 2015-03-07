import sys, os, hashlib, time, json, random
import unittest

from jobQueue import *

from config import Config

class TestJobQueue(unittest.TestCase):
    def setUp(self):
        self.job1 = TangoJob(
                    name = "sample_job_1",
                    vm = "ilter.img",
                    outputFile = "sample_job_1_output",
                    input = [],
                    timeout = 30,
                    notifyURL = "notifyMeUrl",
                    maxOutputFileSize = 4096)

        self.job2 = TangoJob(
                    name = "sample_job_2",
                    vm = "ilter.img",
                    outputFile = "sample_job_2_output",
                    input = [],
                    timeout = 30,
                    notifyURL = "notifyMeUrl",
                    maxOutputFileSize = 4096)


        self.jobQueue = JobQueue(None)
        self.jobQueue.jobQueue._clean()
        self.jobQueue.deadJobs._clean()
        self.jobId1 = self.jobQueue.add(self.job1)
        self.jobId2 = self.jobQueue.add(self.job2)


    def test_add(self):
        print self.jobQueue.jobQueue.keys()
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size'], 2)


    def test_addDead(self):
        return self.assertEqual(1,1)

    def test_remove(self):
        self.jobQueue.remove(self.jobId1)
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size'], 1)

        self.jobQueue.remove(self.jobId2)
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size'], 0)

    def test_delJob(self):
        self.jobQueue.delJob(self.jobId1, 0)
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size'], 1)
        self.assertEqual(info['size_deadjobs'], 1)


        self.jobQueue.delJob(self.jobId1, 1)
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size_deadjobs'], 0)

        return False


    def test_get(self):
        ret_job_1 = self.jobQueue.get(self.jobId1)
        self.assertEqual(str(ret_job_1.id), self.jobId1)

        ret_job_2 = self.jobQueue.get(self.jobId2)
        self.assertEqual(str(ret_job_2.id), self.jobId2)


    def test_getNextPendingJob(self):
        self.jobQueue.assignJob(self.jobId2)
        self.jobQueue.unassignJob(self.jobId1)
        exp_id = self.jobQueue.getNextPendingJob()
        self.assertMultiLineEqual(exp_id, self.jobId1)


    def test_getNextPendingJobReuse(self):
        return False


    def test_assignJob(self):
        self.jobQueue.assignJob(self.jobId1)
        job = self.jobQueue.get(self.jobId1)
        return self.assertTrue(job.assigned)


    def test_unassignJob(self):
        self.jobQueue.assignJob(self.jobId1)
        job = self.jobQueue.get(self.jobId1)
        self.assertTrue(job.assigned)

        self.jobQueue.unassignJob(self.jobId1)
        job = self.jobQueue.get(self.jobId1)
        return self.assertEqual(job.assigned, False)


    def test_makeDead(self):
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size_deadjobs'], 0)
        self.jobQueue.makeDead(self.jobId1, "test")
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size_deadjobs'], 1)

    def test__getNextID(self):

        init_id = self.jobQueue.nextID
        for i in xrange(1, Config.MAX_JOBID + 100):
            id = self.jobQueue._getNextID()
            self.assertNotEqual(str(id), self.jobId1)

        self.jobQueue.nextID = init_id

if __name__ == '__main__':
    unittest.main()
