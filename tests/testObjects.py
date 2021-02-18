from __future__ import print_function
from builtins import range
from builtins import str
import unittest
import redis

from tangoObjects import TangoDictionary, TangoJob, TangoQueue
from config import Config


class TestDictionary(unittest.TestCase):
    def setUp(self):
        if Config.USE_REDIS:
            __db = redis.StrictRedis(Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
            __db.flushall()

        self.test_entries = {
            "key": "value",
            0: "0_value",
            123: 456,
        }

    def runDictionaryTests(self):
        test_dict = TangoDictionary("test")
        self.assertEqual(test_dict.keys(), [])
        self.assertEqual(test_dict.values(), [])

        for key in self.test_entries:
            test_dict.set(key, self.test_entries[key])

        for key in self.test_entries:
            self.assertTrue(key in test_dict)
            self.assertEqual(test_dict.get(key), self.test_entries[key])

        for (key, val) in test_dict.items():
            self.assertEqual(self.test_entries.get(key), val)

        self.assertEqual(
            test_dict.keys(), [str(key) for key in self.test_entries.keys()]
        )
        self.assertEqual(test_dict.values(), list(self.test_entries.values()))
        self.assertTrue("key_not_present" not in test_dict)
        self.assertEqual(test_dict.get("key_not_present"), None)

        test_dict.set("key", "new_value")
        self.assertEqual(test_dict.get("key"), "new_value")

        test_dict.delete("key")
        self.assertTrue("key" not in test_dict)

    def test_nativeDictionary(self):
        Config.USE_REDIS = False
        self.runDictionaryTests()

    def test_remoteDictionary(self):
        Config.USE_REDIS = True
        self.runDictionaryTests()


class TestQueue(unittest.TestCase):
    def setUp(self):
        if Config.USE_REDIS:
            __db = redis.StrictRedis(Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
            __db.flushall()
        self.test_entries = [i for i in range(10)]

    def addAllToQueue(self):
        # Add all items into the queue
        for x in self.test_entries:
            self.testQueue.put(x)
            self.expectedSize += 1
            self.assertEqual(self.testQueue.qsize(), self.expectedSize)

    def runQueueTests(self):
        self.testQueue = TangoQueue("self.testQueue")
        self.expectedSize = 0
        self.assertEqual(self.testQueue.qsize(), self.expectedSize)
        self.assertTrue(self.testQueue.empty())

        self.addAllToQueue()

        # Test the blocking get
        for x in self.test_entries:
            item = self.testQueue.get()
            self.expectedSize -= 1
            self.assertEqual(self.testQueue.qsize(), self.expectedSize)
            self.assertEqual(item, x)

        self.addAllToQueue()

        # Test the blocking get
        for x in self.test_entries:
            item = self.testQueue.get_nowait()
            self.expectedSize -= 1
            self.assertEqual(self.testQueue.qsize(), self.expectedSize)
            self.assertEqual(item, x)

        self.addAllToQueue()

        # Remove all the even entries
        for x in self.test_entries:
            if x % 2 == 0:
                self.testQueue.remove(x)
                self.expectedSize -= 1
                self.assertEqual(self.testQueue.qsize(), self.expectedSize)

        # Test that get only returns odd keys in order
        for x in self.test_entries:
            if x % 2 == 1:
                item = self.testQueue.get_nowait()
                self.expectedSize -= 1
                self.assertEqual(self.testQueue.qsize(), self.expectedSize)
                self.assertEqual(item, x)

    def test_nativeQueue(self):
        Config.USE_REDIS = False
        self.runQueueTests()

    def test_remoteQueue(self):
        Config.USE_REDIS = True
        self.runQueueTests()


if __name__ == "__main__":
    unittest.main()
