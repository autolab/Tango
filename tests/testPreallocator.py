import unittest
import random

import redis
from preallocator import *

from config import Config
from tangoObjects import TangoMachine


class TestPreallocator(unittest.TestCase):

    def createTangoMachine(self, image, vmms,
                           vmObj={'cores': 1, 'memory': 512}):
        """ createTangoMachine - Creates a tango machine object from image
        """
        return TangoMachine(
            name=image,
            vmms=vmms,
            image="%s" % (image),
            cores=vmObj["cores"],
            memory=vmObj["memory"],
            disk=None,
            network=None)

    def setUp(self):
        # Add more machine types to test here in future
        self.testMachines = ["localDocker"]

    def createVM(self):
        if Config.USE_REDIS:
            __db = redis.StrictRedis(
                Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
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
        self.vm = self.createTangoMachine(
            image="autograding_image", vmms=Config.VMMS_NAME)

    def test_poolSize(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()
            # VM with empty pool
            self.assertEqual(self.preallocator.poolSize(self.vm.name), 0)

            # VM post pool update
            self.preallocator.update(self.vm, 5)
            self.assertEqual(self.preallocator.poolSize(self.vm.name), 5)

    def test_update(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()

            # Addition of machines (delta > 0)
            self.preallocator.update(self.vm, 10)
            self.assertEqual(self.preallocator.poolSize(self.vm.name), 10)

            # Deletion of machines (delta < 0)
            self.preallocator.update(self.vm, 5)
            self.assertEqual(self.preallocator.poolSize(self.vm.name), 5)

    def test_allocVM(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()

            # No machines to allocate in pool
            self.preallocator.update(self.vm, 0)
            vm = self.preallocator.allocVM(self.vm.name)
            self.assertIsNone(vm)

            # Regular behavior
            self.preallocator.update(self.vm, 5)
            vm = self.preallocator.allocVM(self.vm.name)
            self.assertIsNotNone(vm)

    def test_freeVM(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()
            # Allocating single, free machine
            self.preallocator.update(self.vm, 1)
            vm = self.preallocator.allocVM(self.vm.name)
            self.preallocator.freeVM(vm)
            free = self.preallocator.getPool(self.vm.name)['free']
            self.assertFalse(free == [])

            # Revert pool for other tests
            self.preallocator.update(self.vm, 5)

    def test_getNextID(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()

            # Obtain valid machine id during creation/update
            idx = self.preallocator._getNextID()
            self.assertGreaterEqual(idx, 1000)
            self.assertLessEqual(idx, 9999)

    def test_createVMPool(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()

            # Create single VM
            self.preallocator.update(self.vm, 1)
            allPools = self.preallocator.getAllPools()
            self.assertIn(self.vm.name, allPools.keys())

    def test_destroyVM(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()

            # Destroy non existent VM
            res = self.preallocator.destroyVM("nonExistent", 1001)
            self.assertEqual(res, -1)

            # Destroy existent VM
            self.preallocator.update(self.vm, 1)
            prevPool = self.preallocator.getPool(self.vm.name)
            rand = random.choice(prevPool['total'])
            res = self.preallocator.destroyVM(self.vm.name, rand)
            self.assertEqual(res, 0)

    def test_getPool(self):
        for machine in self.testMachines:
            Config.VMMS_NAME = machine
            self.createVM()

            # Empty pool
            self.preallocator.update(self.vm, 0)
            pool = self.preallocator.getPool(self.vm.name)
            self.assertEqual(pool["total"], [])
            self.assertEqual(pool["free"], [])


if __name__ == '__main__':
    unittest.main()
