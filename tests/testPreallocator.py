import unittest
import random

from preallocator import *

from config import Config
from tangoObjects import TangoMachine

class TestPreallocator(unittest.TestCase):

    def setUp(self):
        if Config.VMMS_NAME == "tashiSSH":
            from vmms.tashiSSH import TashiSSH
            vmms = TashiSSH()
            self.preallocator = Preallocator({"tashiSSH": vmms})
        
        elif Config.VMMS_NAME == "ec2SSH":
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
       
        self.vm = TangoMachine()

    def test_poolSize(self):
        self.assertEqual(self.preallocator.poolSize("nonExistent"), 0)
       
        self.assertEqual(self.preallocator.poolSize(self.vm.name), 0)
        
        self.preallocator.update(self.vm, 5)
        self.assertEqual(self.preallocator.poolSize(self.vm.name), 5)

    def test_update(self):
        self.preallocator.update(self.vm, 10)
        self.assertEqual(self.preallocator.poolSize(self.vm.name), 10)

        self.preallocator.update(self.vm, 5)
        self.assertEqual(self.preallocator.poolSize(self.vm.name), 5)

    def test_allocVM(self):
        vm = self.preallocator.allocVM(self.vm.name)
        self.assertIsNotNone(vm)

        self.preallocator.update(self.vm, 0)
        vm = self.preallocator.allocVM(self.vm.name)
        self.assertIsNone(vm)

        self.preallocator.update(self.vm, 5)

    def test_freeVM(self):
        self.preallocator.update(self.vm, 1)
        vm = self.preallocator.allocVM(self.vm.name)
        self.preallocator.freeVM(vm)
        free = self.preallocator.getPool(self.vm.name)['free']
        self.assertFalse(free == [])

        self.preallocator.update(self.vm, 5)

    def test_addVM(self):
        prevSize = self.preallocator.poolSize(self.vm)
        self.preallocator.addVM(self.vm)
        self.assertEqual(self.preallocator.poolSize(self.vm), prevSize + 1)

    def test_removeVM(self):
        prevSize = self.preallocator.poolSize(self.vm)
        self.preallocator.removeVM(self.vm)
        self.assertEqual(self.preallocator.poolSize(self.vm), prevSize - 1)

    def test_getNextID(self):
        idx = self.preallocator._getNextID()
        self.assertGreaterEqual(idx, 1000)
        self.assertLessEqual(idx, 9999)

    def test_create(self):
        prevSize = self.preallocator.poolSize(self.vm)
        self.preallocator.__create(self.vm, 7)
        self.assertEqual(self.preallocator.poolSize(self.vm), prevSize + 7)

    def test_destroy(self):
        self.preallocator.__destroy(self.vm)
        allPools = self.preallocator.getAllPools()
        self.assertNotIn(self.vm, allPools)

    def test_createVM(self):
        self.preallocator.createVM(self.vm)
        allPools = self.preallocator.getAllPools()
        self.assertIn(self.vm, allPools)

    def test_destroyVM(self):
        res = self.preallocator.destroyVM("nonExistent", 1001)
        self.assertEqual(res, -1)

        prevPool = self.preallocator.getPool(self.vm.name)
        rand = random.choice(prevPool["total"])
        res = self.preallocator.destroyVM(self.vm, rand)
        self.assertEqual(res, 0)
        
        postPool = self.preallocator.getPool(self.vm.name)
        self.assertTrue(rand not in postPool["total"])

        randNew = rand
        for i in range(1, 10):
            if (rand + i) not in postPool["total"]:
                randNew = rand + i
                break
        
        res = self.preallocator.destroyVM(self.vm, randNew)
        self.assertEqual(res, -1)

    def test_getPool(self):
        self.vm = TangoMachine()
        pool = self.preallocator.getPool(self.vm.name)
        self.assertTrue(pool["total"] == [])
        self.assertTrue(pool["free"] == [])

        self.preallocator.__create(self.vm, 5)
        vm1 = self.preallocator.allocVM(self.vm.name)
        vm2 = self.preallocator.allocVM(self.vm.name)

        pool = self.preallocator.getPool(self.vm.name)
        self.assertTrue(len(pool["total"]) == 5)
        self.assertTrue(len(pool["free"]) == 3)

if __name__ == '__main__':
    unittest.main()
