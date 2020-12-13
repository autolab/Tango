from __future__ import print_function
from builtins import range
from builtins import str
import unittest
import redis

from tangoObjects import TangoDictionary, TangoJob
from config import Config


class TestObjects(unittest.TestCase):

    def setUp(self):
        if Config.USE_REDIS:
            __db = redis.StrictRedis(
                Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
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

        self.assertEqual(test_dict.keys(), [str(key) for key in self.test_entries.keys()])
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


if __name__ == '__main__':
    unittest.main()
