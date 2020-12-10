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


    def test_nativeDictionary(self):
        Config.USE_REDIS = False
        test_dict = TangoDictionary("test")
        test_dict.set("key", "value")
        assert "key" in test_dict
        assert test_dict.get("key") == "value"

    def test_removeDictionary(self):
        Config.USE_REDIS = True
        test_dict = TangoDictionary("test")
        test_dict.set("key", "value")
        assert "key" in test_dict
        assert test_dict.get("key") == "value"

if __name__ == '__main__':
    unittest.main()
