import unittest
from unittest.mock import MagicMock, Mock
from subprocess import Popen
from multiprocessing import Process, Pool
from tangoObjects import TangoJob
from vmms.localDocker import LocalDocker
import tango 
import importlib
import concurrent.futures
import time
import redis
import threading
from config import Config

# Start up the redis-server
redisServer = Popen(["redis-server"])

# Import the tango server
server = importlib.import_module("restful-tango.server")

# Import the tangoREST module 
tangoREST = importlib.import_module("restful-tango.tangoREST")


class SampleTest(unittest.TestCase):
    isSetUp = False
    redisConnection = None

    def getRedisConnection(self):
        if self.__class__.redisConnection is None:
            self.__class__.redisConnection = redis.StrictRedis(
                host=Config.REDIS_HOSTNAME, port=Config.REDIS_PORT, db=0)

        return self.__class__.redisConnection


    def createNewJob(self):
        self.jobsName += 1
        return TangoJob(
            name= str(self.jobsName),
            vm=self.vm,
            outputFile="sample_job_1_output",
            input=[],
            timeout=30,
            maxOutputFileSize=4096)

    def setUp(self):
       if not self.isSetUp:
           self.mysetup()
           self.__class__.isSetUp = True


    # Do this set up only once
    def mysetup(self):
        unittest.TestCase.setUp(self)

        # Set the POOL_SIZE config to be equals to 2
        Config.POOL_SIZE = 2
        # Set the config such that the mock vmms we create later on will 
        # be used instead 
        Config.VMMS_NAME = "mock"

        # Set jobsName to start from 0, this will be used to create new jobs
        self.jobsName = 0
        # tango rest api
        # In future, we can use this to "fake" requests and test what we expect
        self.tREST = tangoREST.TangoREST()

        # This is the tango machine to be requested in the test tango jobs 
        self.vm=self.tREST.createTangoMachine(image="autograding_image")

        # Spin up a thread pool
        # I have tried and failed to use a process pool instead. There seems 
        # to be something wrong with the imports, so now we have to resort to 
        # using threads instead. 
        # 
        # The idea here is to model what happens in o
        # production where we have one process running the server and one 
        # process running the jobManager. 
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)


        # Create a mock instance of a vmms. 
        # We want to be checking now how many times vms are created/ initialized 
        self.mockVMMS = LocalDocker()
        self.mockVMMS.initializeVM = Mock()

        # Pass the mock vm into the tango server for it to use instead
        self.tangoServer = tango.TangoServer(mock_vmms=self.mockVMMS)

        # We flush the redis cache 
        self.r = self.getRedisConnection()
        self.r.flushdb()

        # Spin up a thread that runs the server
        self.p1 = self.executor.submit(server.RunServer.run, self.mockVMMS)
        # Spin up a thread that runs the job manager
        self.p2 = self.executor.submit(tango.JobManager.runJobManager, self.mockVMMS)

        # Tried but failed attemps to use async process calls
        # self.pJobManager = self.pool.apply_async(func=tango.JobManager.runJobManager, args=[self.mockVMMS], error_callback=lambda e : print("exception"))
        # self.pServer = self.pool.apply_async(server.RunServer.run, [self.mockVMMS])
 
    def shutdownExecutor(self):
        self.executor.shutdown(wait=False)
        self.executor._threads.clear()

    def test__initializeVMCount(self):
        # We add 5 jobs to the server
        for i in range(5):
            self.tangoServer.addJob(self.createNewJob(), True)

        # Give the jobs sometime to run
        time.sleep(8) 

        # Shutdown the executor forcefully
        self.shutdownExecutor()

        # The number of times a vm is initialized or 'created' should be 
        # equals to the config size. 
        self.assertEqual(self.mockVMMS.initializeVM.call_count, 2)
        return True


if __name__ == '__main__':
    unittest.main()
    redisServer.terminate()
