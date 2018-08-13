# tangoREST.py
#
# Implements objects used to pass state within Tango.
#
import os
import redis
import pickle
import Queue
import logging
from datetime import datetime
from config import Config

redisConnection = None

# Pass in an existing connection to redis, sometimes necessary for testing.
def getRedisConnection(connection=None):
    global redisConnection
    if redisConnection is None:
        if connection:
            redisConnection = connection
            return redisConnection

        redisConnection = redis.StrictRedis(
            host=Config.REDIS_HOSTNAME, port=Config.REDIS_PORT, db=0)

    return redisConnection


class InputFile():

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


class TangoMachine():

    """
        TangoMachine - A description of the Autograding Virtual Machine
    """

    def __init__(self, image=None, vmms=None,
                 network=None, cores=None, memory=None, disk=None,
                 domain_name=None):
        self.image = image
        self.vmms = vmms
        self.network = network
        self.cores = cores
        self.memory = memory
        self.disk = disk
        self.domain_name = domain_name

        self.ec2_id = None
        self.resume = None
        self.id = None
        self.instance_id = None
        self.instance_type = None
        self.notes = None

        # The following attributes can instruct vmms to set the test machine
        # aside for further investigation.
        self.keepForDebugging = False

        # The "name" property is vmms dependent.  It doesn't mean the name of
        # vm.  It's derived from the image name and used as the vm pool name
        # The actual vm name is constructed by the instanceName method in each vmms.
        self.name = None

        # The image may contain instance type if vmms is ec2.  Example:
        # course101+t2.small.
        if image:
            imageParts = image.split('+')
            if len(imageParts) == 2:
                self.image = imageParts[0]
                self.instance_type = imageParts[1]
            (name, ext) = os.path.splitext(self.image)
            self.name = name + ("+" + self.instance_type if self.instance_type else "")

    def __repr__(self):
        return "TangoMachine(image: %s, vmms: %s, id: %s)" % (self.image, self.vmms, self.id)


class TangoJob():

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
        self.tm = datetime.now()

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
        # trace attached to the object can be retrived and sent to rest api caller
        self.syncRemote()
        self.trace.append("%s|%s" % (datetime.now().ctime(), trace_str))
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


class TangoRemoteIntValue():

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


class TangoNativeIntValue():

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
        return Queue.Queue()


class TangoRemoteQueue():

    """Simple Queue with Redis Backend"""

    def __init__(self, name, namespace="queue"):
        """The default connection parameters are: host='localhost', port=6379, db=0"""
        self.__db = getRedisConnection()
        self.key = '%s:%s' % (namespace, name)

    # for debugging.  return a readable string representation
    def dump(self):
        unpickled_obj = self.__db.lrange(self.key, 0, -1)
        objs = []
        for obj in unpickled_obj:
            objs.append(pickle.loads(obj))
        return objs

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

    def make_empty(self):
        while True:
            item = self.__db.lpop(self.key)
            if item is None:
                break

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


class TangoRemoteDictionary():

    def __init__(self, object_name):
        self.r = getRedisConnection()
        self.hash_name = object_name
        self.log = logging.getLogger("TangoRemoteDictionary")

    def set(self, id, obj):
        pickled_obj = pickle.dumps(obj)

        if hasattr(obj, '_remoteLocation'):
            obj._remoteLocation = self.hash_name + ":" + str(id)

        self.r.hset(self.hash_name, str(id), pickled_obj)
        return str(id)

    def get(self, id):
        if str(id) in self.r.hkeys(self.hash_name):
            unpickled_obj = self.r.hget(self.hash_name, str(id))
            obj = pickle.loads(unpickled_obj)
            return obj
        else:
            return None

    def keys(self):
        return self.r.hkeys(self.hash_name)

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

    def iteritems(self):
        # find all non-empty spots in the job id spectrum (actual jobs) and sort
        # by the time of creation to prevent starvation of jobs with larger ids

        return iter(sorted([(i, self.get(i)) for i in xrange(1,Config.MAX_JOBID+1)
                            if self.get(i) != None], key=lambda x: x[1].tm))


class TangoNativeDictionary():

    def __init__(self):
        self.dict = {}

    def set(self, id, obj):
        self.dict[str(id)] = obj

    def get(self, id):
        if str(id) in self.dict.keys():
            return self.dict[str(id)]
        else:
            return None

    def keys(self):
        return self.dict.keys()

    def values(self):
        return self.dict.values()

    def delete(self, id):
        if str(id) in self.dict.keys():
            del self.dict[str(id)]

    def iteritems(self):
        return iter(sorted([(i, self.get(i)) for i in xrange(1,Config.MAX_JOBID+1)
                            if self.get(i) != None], key=lambda x: x[1].tm))

    def _clean(self):
        # only for testing
        return
