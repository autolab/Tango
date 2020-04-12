# tangoREST.py
#
# Implements objects used to pass state within Tango.
#
from builtins import range
from builtins import object
from future import standard_library
standard_library.install_aliases()
from builtins import str
import redis
import pickle
import queue
from config import Config

redisConnection = None


def getRedisConnection():
    global redisConnection
    if redisConnection is None:
        redisConnection = redis.StrictRedis(
            host=Config.REDIS_HOSTNAME, port=Config.REDIS_PORT, db=0)

    return redisConnection


class InputFile(object):

    """
        InputFile - Stores pointer to the path on the local machine and the
        name of the file on the destination machine
    """

    def __init__(self, localFile, destFile):
        self.localFile = localFile
        self.destFile = destFile

    def __repr__(self):
        return "InputFile(localFile: %s, destFile: %s)" % (self.localFile, 
                self.destFile)


class TangoMachine(object):

    """
        TangoMachine - A description of the Autograding Virtual Machine
    """

    def __init__(self, name="DefaultTestVM", image=None, vmms=None,
                 network=None, cores=None, memory=None, disk=None,
                 domain_name=None, ec2_id=None, resume=None, id=None,
                 instance_id=None):
        self.name = name
        self.image = image
        self.network = network
        self.cores = cores
        self.memory = memory
        self.disk = disk
        self.vmms = vmms
        self.domain_name = domain_name
        self.ec2_id = ec2_id
        self.resume = resume
        self.id = id
        self.instance_id = id

    def __repr__(self):
        return "TangoMachine(image: %s, vmms: %s)" % (self.image, self.vmms)


class TangoJob(object):

    """
        TangoJob - A job that is to be run on a TangoMachine
    """

    def __init__(self, vm=None,
                 outputFile=None, name=None, input=None,
                 notifyURL=None, timeout=0,
                 maxOutputFileSize=Config.MAX_OUTPUT_FILE_SIZE,
                 accessKeyId=None, accessKey=None):
        self.assigned = False
        self.retries = 0

        self.vm = vm
        if input is None:
            self.input = []
        else:
            self.input = input

        self.outputFile = outputFile
        self.name = name
        self.notifyURL = notifyURL
        self.timeout = timeout
        self.trace = []
        self.maxOutputFileSize = maxOutputFileSize
        self._remoteLocation = None
        self.accessKeyId = accessKeyId
        self.accessKey = accessKey

    def makeAssigned(self):
        self.syncRemote()
        self.assigned = True
        self.updateRemote()

    def makeUnassigned(self):
        self.syncRemote()
        self.assigned = False
        self.updateRemote()

    def isNotAssigned(self):
        self.syncRemote()
        return not self.assigned

    def appendTrace(self, trace_str):
        self.syncRemote()
        self.trace.append(trace_str)
        self.updateRemote()

    def setId(self, new_id):
        self.id = new_id
        if self._remoteLocation is not None:
            dict_hash = self._remoteLocation.split(":")[0]
            key = self._remoteLocation.split(":")[1]
            dictionary = TangoDictionary(dict_hash)
            dictionary.delete(key)
            self._remoteLocation = dict_hash + ":" + str(new_id)
            self.updateRemote()

    def syncRemote(self):
        if Config.USE_REDIS and self._remoteLocation is not None:
            dict_hash = self._remoteLocation.split(":")[0]
            key = self._remoteLocation.split(":")[1]
            dictionary = TangoDictionary(dict_hash)
            temp_job = dictionary.get(key)
            self.updateSelf(temp_job)

    def updateRemote(self):
        if Config.USE_REDIS and self._remoteLocation is not None:
            dict_hash = self._remoteLocation.split(":")[0]
            key = self._remoteLocation.split(":")[1]
            dictionary = TangoDictionary(dict_hash)
            dictionary.set(key, self)

    def updateSelf(self, other_job):
        self.assigned = other_job.assigned
        self.retries = other_job.retries
        self.vm = other_job.vm
        self.input = other_job.input
        self.outputFile = other_job.outputFile
        self.name = other_job.name
        self.notifyURL = other_job.notifyURL
        self.timeout = other_job.timeout
        self.trace = other_job.trace
        self.maxOutputFileSize = other_job.maxOutputFileSize


def TangoIntValue(object_name, obj):
    if Config.USE_REDIS:
        return TangoRemoteIntValue(object_name, obj)
    else:
        return TangoNativeIntValue(object_name, obj)


class TangoRemoteIntValue(object):

    def __init__(self, name, value, namespace="intvalue"):
        """The default connection parameters are: host='localhost', port=6379, db=0"""
        self.__db = getRedisConnection()
        self.key = '%s:%s' % (namespace, name)
        cur_val = self.__db.get(self.key)
        if cur_val is None:
            self.set(value)

    def increment(self):
        return self.__db.incr(self.key)

    def get(self):
        return int(self.__db.get(self.key))

    def set(self, val):
        return self.__db.set(self.key, val)


class TangoNativeIntValue(object):

    def __init__(self, name, value, namespace="intvalue"):
        self.key = '%s:%s' % (namespace, name)
        self.val = value

    def increment(self):
        self.val = self.val + 1
        return self.val

    def get(self):
        return self.val

    def set(self, val):
        self.val = val
        return val


def TangoQueue(object_name):
    if Config.USE_REDIS:
        return TangoRemoteQueue(object_name)
    else:
        return queue.Queue()


class TangoRemoteQueue(object):

    """Simple Queue with Redis Backend"""

    def __init__(self, name, namespace="queue"):
        """The default connection parameters are: host='localhost', port=6379, db=0"""
        self.__db = getRedisConnection()
        self.key = '%s:%s' % (namespace, name)

    def qsize(self):
        """Return the approximate size of the queue."""
        return self.__db.llen(self.key)

    def empty(self):
        """Return True if the queue is empty, False otherwise."""
        return self.qsize() == 0

    def put(self, item):
        """Put item into the queue."""
        pickled_item = pickle.dumps(item)
        self.__db.rpush(self.key, pickled_item)

    def get(self, block=True, timeout=None):
        """Remove and return an item from the queue.

        If optional args block is true and timeout is None (the default), block
        if necessary until an item is available."""
        if block:
            item = self.__db.blpop(self.key, timeout=timeout)
        else:
            item = self.__db.lpop(self.key)

        # if item:
        #     item = item[1]

        item = pickle.loads(item)
        return item

    def get_nowait(self):
        """Equivalent to get(False)."""
        return self.get(False)

    def __getstate__(self):
        ret = {}
        ret['key'] = self.key
        return ret

    def __setstate__(self, dict):
        self.__db = getRedisConnection()
        self.__dict__.update(dict)


# This is an abstract class that decides on
# if we should initiate a TangoRemoteDictionary or TangoNativeDictionary
# Since there are no abstract classes in Python, we use a simple method
def TangoDictionary(object_name):
    if Config.USE_REDIS:
        return TangoRemoteDictionary(object_name)
    else:
        return TangoNativeDictionary()


class TangoRemoteDictionary(object):

    def __init__(self, object_name):
        self.r = getRedisConnection()
        self.hash_name = object_name

    def set(self, id, obj):
        pickled_obj = pickle.dumps(obj)

        if hasattr(obj, '_remoteLocation'):
            obj._remoteLocation = self.hash_name + ":" + str(id)

        self.r.hset(self.hash_name, str(id), pickled_obj)
        return str(id)

    def get(self, id):
        if self.r.hexists(self.hash_name, str(id)):
            unpickled_obj = self.r.hget(self.hash_name, str(id))
            obj = pickle.loads(unpickled_obj)
            return obj
        else:
            return None

    def keys(self):
        keys = map(lambda key : key.decode(), self.r.hkeys(self.hash_name))
        return list(keys)

    def values(self):
        vals = self.r.hvals(self.hash_name)
        valslist = []
        for val in vals:
            valslist.append(pickle.loads(val))
        return valslist

    def delete(self, id):
        self._remoteLocation = None
        self.r.hdel(self.hash_name, id)

    def _clean(self):
        # only for testing
        self.r.delete(self.hash_name)

    def items(self):
        return iter([(i, self.get(i)) for i in range(1,Config.MAX_JOBID+1)
                if self.get(i) != None])

class TangoNativeDictionary(object):

    def __init__(self):
        self.dict = {}

    def set(self, id, obj):
        self.dict[str(id)] = obj

    def get(self, id):
        if str(id) in list(self.dict.keys()):
            return self.dict[str(id)]
        else:
            return None

    def keys(self):
        return list(self.dict.keys())

    def values(self):
        return list(self.dict.values())

    def delete(self, id):
        if str(id) in list(self.dict.keys()):
            del self.dict[str(id)]

    def items(self):
        return iter([(i, self.get(i)) for i in range(1,Config.MAX_JOBID+1)
                if self.get(i) != None])

    def _clean(self):
        # only for testing
        return
