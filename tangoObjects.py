# tangoREST.py
#
# Implements objects used to pass state within Tango.
#
import redis
import pickle
from config import Config


class InputFile():
    """
        InputFile - Stores pointer to the path on the local machine and the
        name of the file on the destination machine
    """
    def __init__(self, localFile, destFile):
        self.localFile = localFile
        self.destFile = destFile

class TangoMachine():
    """
        TangoMachine - A description of the Autograding Virtual Machine
    """
    def __init__(self, name = "DefaultTestVM", image = None, vmms = None,
                network = None, cores = None, memory = None, disk = None, 
                domain_name = None, ec2_id = None, resume = None, id = None,
                instance_id = None):
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

class TangoJob():
    """
        TangoJob - A job that is to be run on a TangoMachine
    """
    def __init__(self, assigned = False, retries = 0, vm = None,
                outputFile = None, name = None, input = [],
                notifyURL = None, timeout = 0, trace = [], 
                maxOutputFileSize = 4096):
        self.assigned = assigned
        self.retries = retries
        self.vm = vm
        self.input = input
        self.outputFile = outputFile
        self.name = name
        self.notifyURL = notifyURL
        self.timeout = timeout
        self.trace = trace
        self.maxOutputFileSize = maxOutputFileSize
        self._remoteLocation = None

    def appendTrace(self, trace_str):
        if Config.USE_REDIS and self._remoteLocation is not None:
            __db= redis.StrictRedis(Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
            dict_hash = self._remoteLocation.split(:)[0]
            key = self._remoteLocation.split(:)[1]
            dictionary = TangoDictionary(dict_hash)
            self.trace.append(trace_str)
            dictionary.set(key, self)

        else:
            self.trace.append(trace_str)


def TangoIntValue(object_name, obj):
    if Config.USE_REDIS:
        return TangoRemoteIntValue(object_name, obj)
    else:
        return TangoNativeIntValue()


class TangoRemoteIntValue():
    def __init__(self, name, value, namespace="intvalue"):
        """The default connection parameters are: host='localhost', port=6379, db=0"""
        self.__db= redis.StrictRedis(Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
        self.key = '%s:%s' %(namespace, name)
        self.set(value)

    def increment(self):
        return self.__db.incr(self.key)

    def get(self):
        return int(self.__db.get(self.key))

    def set(self, val):
        return self.__db.set(self.key, val)


class TangoNativeIntValue():
    def __init__(self, name, value, namespace="intvalue"):
        self.key = '%s:%s' %(namespace, name)
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
        self.__db= redis.StrictRedis(Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
        self.key = '%s:%s' %(namespace, name)

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
        self.__db= redis.StrictRedis(Config.REDIS_HOSTNAME, Config.REDIS_PORT, db=0)
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
        self.r = redis.StrictRedis(host=Config.REDIS_HOSTNAME, port=Config.REDIS_PORT, db=0)
        self.hash_name = object_name
    
    def set(self, id, obj):
        pickled_obj = pickle.dumps(obj)

        if hasattr(obj, '_remoteLocation'):
            obj._remoteLocation = self.hash_name + ":" + str(id)

        self.r.hset(self.hash_name, str(id), pickled_obj)
        return str(id)

    def get(self, id):
        unpickled_obj = self.r.hget(self.hash_name, str(id))
        obj = pickle.loads(unpickled_obj)
        return obj

    def keys(self):
        return self.r.hkeys(self.hash_name)

    def values(self):
        vals = self.r.hvals(self.hash_name)
        valslist = []
        for val in vals:
            valslist.append(pickle.loads(val))
        return valslist

    def delete(self, id):
        self.r.hdel(self.hash_name, id)

    def _clean(self):
        # only for testing
        self.r.delete(self.hash_name)

    def iteritems(self):
        keys = self.r.hkeys(self.hash_name)
        keyvals = []
        for key in keys:
            tup = (key, pickle.loads(self.r.hget(self.hash_name, key)))
            keyvals.append(tup)

        return keyvals


class TangoNativeDictionary():

    def __init__(self):
        self.dict = {}

    def set(self, id, obj):
        self.dict[str(id)] = obj

    def get(self, id):
        return self.dict[str(id)]

    def keys(self):
        return self.dict.keys()

    def values(self):
        return self.dict.values()

    def delete(self, id):
        del self.dict[id]

    def iteritems(self):
        return self.dict.iteritems()

    def _clean(self):
        # only for testing
        return

