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
                notifyURL = None, timeout = 0, trace = None, 
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



class TangoQueue(object):
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
        self.__db.rpush(self.key, item)

    def get(self, block=True, timeout=None):
        """Remove and return an item from the queue. 

        If optional args block is true and timeout is None (the default), block
        if necessary until an item is available."""
        if block:
            item = self.__db.blpop(self.key, timeout=timeout)
        else:
            item = self.__db.lpop(self.key)

        if item:
            item = item[1]
        return item

    def get_nowait(self):
        """Equivalent to get(False)."""
        return self.get(False)


# This is an abstract class that decides on 
# if we should initiate a TangoRemoteDictionary or TangoNativeDictionary
# Since there are no abstract classes in Python, we use a simple method
def TangoDictionary(object_name):
    if Config.USE_REDIS:
        return TangoRemoteDictionary(Config.REDIS_HOSTNAME, Config.REDIS_PORT, object_name)
    else:
        return TangoNativeDictionary()


class TangoRemoteDictionary():
    def __init__(self, hostname, port, object_name):
        self.r = redis.StrictRedis(host=hostname, port=port, db=0)
        self.hash_name = object_name
    
    def set(self, id, obj):
        pickled_obj = pickle.dumps(obj)
        self.r.hset(self.hash_name, id, pickled_obj)
        return id

    def get(self, id):
        unpickled_obj = self.r.hget(self.hash_name, id)
        obj = pickle.loads(unpickled_obj)
        return obj

    def keys(self):
        return self.r.hkeys(self.hash_name)

    def values(self):
        return self.r.hvals(self.hash_name)

    def delete(self, id):
        self.r.hdel(self.hash_name, id)

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
        self.dict[id] = obj

    def get(self, id):
        return self.dict[id]

    def keys(self):
        return self.dict.keys()

    def values(self):
        return self.dict.values()

    def delete(self, id):
        del self.dict[id]

    def iteritems(self):
        return self.dict.iteritems()

