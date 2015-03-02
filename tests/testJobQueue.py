import sys, os, hashlib, time, json, random
import unittest
# from tangod import *
from jobQueue import *



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
        self.jobId1 = self.jobQueue.add(self.job1)
        self.jobId2 = self.jobQueue.add(self.job2)


    def test_add(self):
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


        self.jobQueue.delJob(self.jobId2, 1)
        info = self.jobQueue.getInfo()
        self.assertEqual(info['size'], 0)

        return False


    def get(self):
        ret_job_1 = self.jobQueue.get(self.jobId1)
        self.assertEqual(ret_job_1.__dict__, self.job1.__dict__)

        ret_job_2 = self.jobQueue.get(self.jobId2)
        self.assertEqual(ret_job_2.__dict__, self.job2.__dict__)


    def getNextPendingJob(self):
        return False


    def getNextPendingJobReuse(self):
        return False


    def assignJob(self):
        return False


    def unassignJob(self):
        return False


    def makeDead(self):
        return False


if __name__ == '__main__':
    unittest.main()

