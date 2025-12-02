from __future__ import annotations
# tangoREST.py
#
# Implements objects used to pass state within Tango.
#
from config import Config
from queue import Queue
import pickle
import redis
from typing import Optional, Protocol, TypeVar, Union
from abc import abstractmethod

redisConnection = None


def getRedisConnection():
    global redisConnection
    if redisConnection is None:
        redisConnection = redis.StrictRedis(
            host=Config.REDIS_HOSTNAME, port=Config.REDIS_PORT, db=0
        )

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
        return "InputFile(localFile: %s, destFile: %s)" % (
            self.localFile,
            self.destFile,
        )


class TangoMachine(object):

    """
    TangoMachine - A description of the Autograding Virtual Machine
    """

    def __init__(
        self,
        name="DefaultTestVM",
        image=None,
        vmms=None,
        network=None,
        cores=None,
        memory=None,
        disk=None,
        domain_name=None,
        ec2_id=None,
        resume=None,
        id=None,
        instance_id=None,
        instance_type=None,
        ec2_vmms=False,
    ):
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
        self.instance_type = instance_type
        self.keep_for_debugging = False
        self.notes = None
        self.ec2_vmms = ec2_vmms

    def __repr__(self):
        return "TangoMachine(image: %s, vmms: %s)" % (self.image, self.vmms)


class TangoJob(object):

    """
    TangoJob - A job that is to be run on a TangoMachine
    """

    # TODO: do we really want all of these default values?
    def __init__(
        self,
        vm: TangoMachine,
        outputFile=None,
        name=None,
        input=None,
        notifyURL=None,
        timeout=0,
        maxOutputFileSize=Config.MAX_OUTPUT_FILE_SIZE,
        accessKeyId=None,
        accessKey=None,
        disableNetwork=None,
        stopBefore="",
    ):
        self._assigned = False
        self._retries: int = 0

        self._vm: TangoMachine = vm
        if input is None:
            self._input = []
        else:
            self._input = input

        self._outputFile = outputFile
        self._name = name
        self._notifyURL = notifyURL
        self._timeout = timeout # How long to run the autodriver on the job for before timing out.
        self._trace: list[str] = []
        self._maxOutputFileSize = maxOutputFileSize
        self._remoteLocation: Optional[str] = None
        self._accessKeyId = accessKeyId
        self._accessKey = accessKey
        self._disableNetwork = disableNetwork
        self._stopBefore = stopBefore
        self._id: Optional[int] = None # uninitialized until it gets added to either the live or dead queue

    def __repr__(self):
        self.syncRemote()
        return f"ID: {self._id} - Name: {self.name}"
    
    # TODO: reduce code size/duplication by setting TangoJob as a dataclass
    # Getters for private variables
    @property
    def assigned(self):
        self.syncRemote() # Is it necessary to sync here?
        return self._assigned
    
    @property
    def retries(self):
        self.syncRemote()
        return self._retries

    @property
    def vm(self):
        self.syncRemote()
        return self._vm
    
    @property
    def input(self):
        self.syncRemote()
        return self._input
    
    @property
    def outputFile(self):
        self.syncRemote()
        return self._outputFile
    
    @property
    def name(self):
        self.syncRemote()
        return self._name
    
    @property
    def notifyURL(self):
        self.syncRemote()
        return self._notifyURL
    
    @property
    def timeout(self):
        self.syncRemote()
        return self._timeout
    
    @property
    def trace(self):
        self.syncRemote()
        return self._trace
    
    @property
    def maxOutputFileSize(self):
        self.syncRemote()
        return self._maxOutputFileSize
    
    @property
    def remoteLocation(self):
        self.syncRemote()
        return self._remoteLocation
    
    @property
    def accessKeyId(self):
        self.syncRemote()
        return self._accessKeyId
    
    @property
    def accessKey(self):
        self.syncRemote()
        return self._accessKey
    
    @property
    def disableNetwork(self):
        self.syncRemote()
        return self._disableNetwork
    
    @property
    def stopBefore(self):
        self.syncRemote()
        return self._stopBefore
    
    @property
    def id(self) -> int:
        self.syncRemote()
        assert self._id is not None, "Job ID is not set, add it to the job queue first"
        return self._id

    def makeAssigned(self):
        self.syncRemote()
        self._assigned = True
        self.updateRemote()

    def resetRetries(self):
        self.syncRemote()
        self._retries = 0
        self.updateRemote()
        
    def incrementRetries(self):
        self.syncRemote()
        self._retries += 1
        self.updateRemote()

    def makeVM(self, vm: TangoMachine) -> None:
        self.syncRemote()
        self._vm = vm
        self.updateRemote()

    def makeUnassigned(self):
        self.syncRemote()
        self._assigned = False
        self.updateRemote()

    def isNotAssigned(self):
        self.syncRemote()
        return not self._assigned

    def appendTrace(self, trace_str):
        self.syncRemote()
        self._trace.append(trace_str)
        self.updateRemote()

    def setId(self, new_id: int) -> None:
        self._id = new_id
        if self._remoteLocation is not None:
            dict_hash = self._remoteLocation.split(":")[0]
            key = self._remoteLocation.split(":")[1]
            dictionary: TangoDictionary[TangoJob] = TangoDictionary.create(dict_hash)
            dictionary.delete(key)
            self._remoteLocation = dict_hash + ":" + str(new_id)
            self.updateRemote()
            
    def setTimeout(self, new_timeout):
        self.syncRemote()
        self._timeout = new_timeout
        self.updateRemote()

    def setKeepForDebugging(self, keep_for_debugging: bool):
        if (self._vm is not None):
            self.syncRemote()
            self._vm.keep_for_debugging = keep_for_debugging
            self.updateRemote()

    # Private method
    def __updateSelf(self, other_job):
        self._assigned = other_job._assigned
        self._retries = other_job._retries
        self._vm = other_job._vm
        self._input = other_job._input
        self._outputFile = other_job._outputFile
        self._name = other_job._name
        self._notifyURL = other_job._notifyURL
        self._timeout = other_job._timeout
        self._trace = other_job._trace
        self._maxOutputFileSize = other_job._maxOutputFileSize
        self._id = other_job._id


    def syncRemote(self) -> None:
        if Config.USE_REDIS and self._remoteLocation is not None:
            dict_hash = self._remoteLocation.split(":")[0]
            key = self._remoteLocation.split(":")[1]
            dictionary: TangoDictionary[TangoJob] = TangoDictionary.create(dict_hash)
            temp_job = dictionary.get(key) # Key should be in dictionary
            if temp_job is None:
                print(f"Job {key} not found in dictionary {dict_hash}") # TODO: add better error handling for TangoJob
                return
            self.__updateSelf(temp_job)

    def updateRemote(self) -> None:
        if Config.USE_REDIS and self._remoteLocation is not None:
            dict_hash = self._remoteLocation.split(":")[0]
            key = self._remoteLocation.split(":")[1]
            dictionary: TangoDictionary[TangoJob] = TangoDictionary.create(dict_hash)
            dictionary.set(key, self)
            
    def deleteFromDict(self, dictionary : TangoDictionary) -> None:
        assert self._id is not None
        dictionary.delete(self._id)
        self._remoteLocation = None
        
    def addToDict(self, dictionary : TangoDictionary) -> None:
        assert self._id is not None
        dictionary.set(self._id, self)
        assert self._remoteLocation is None, "Job already has a remote location"
        if Config.USE_REDIS:
            self._remoteLocation = dictionary.hash_name + ":" + str(self._id)
            self.updateRemote()
        


def TangoIntValue(object_name, obj):
    if Config.USE_REDIS:
        return TangoRemoteIntValue(object_name, obj)
    else:
        return TangoNativeIntValue(object_name, obj)


class TangoRemoteIntValue(object):
    def __init__(self, name, value, namespace="intvalue"):
        """The default connection parameters are: host='localhost', port=6379, db=0"""
        self.__db = getRedisConnection()
        self.key = "%s:%s" % (namespace, name)
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
        self.key = "%s:%s" % (namespace, name)
        self.val = value

    def increment(self):
        self.val = self.val + 1
        return self.val

    def get(self):
        return self.val

    def set(self, val):
        self.val = val
        return val
    

QueueElem = TypeVar('QueueElem')
class TangoQueue(Protocol[QueueElem]):
    @staticmethod
    def create(key_name: str) -> TangoQueue[QueueElem]:
        if Config.USE_REDIS:
            return TangoRemoteQueue(key_name)
        else:
            return ExtendedQueue()

    @abstractmethod
    def qsize(self) -> int:
        ...
    def empty(self) -> bool:
        ...
    def put(self, item: QueueElem) -> None:
        ...
    def get(self, block=True, timeout=None) -> Optional[QueueElem]:
        ...
    def get_nowait(self) -> Optional[QueueElem]:
        ...
    def remove(self, item: QueueElem) -> None:
        ...
    def make_empty(self) -> None:
        ...

class ExtendedQueue(Queue, TangoQueue[QueueElem]):
    """Python Thread safe Queue with the remove and clean function added"""

    def test(self):
        print(self.queue)

    def __repr__(self):
        return str(list(self.queue))
        # with self.mutex:
        #     return str(list(self.queue))

    def remove(self, value):
        with self.mutex:
            self.queue.remove(value)

    def make_empty(self):
        with self.mutex:
            self.queue.clear()
            
class TangoRemoteQueue(TangoQueue):

    """Simple Queue with Redis Backend"""

    def __init__(self, name, namespace="queue"):
        """The default connection parameters are: host='localhost', port=6379, db=0"""
        self.__db = getRedisConnection()
        self.key = "%s:%s" % (namespace, name)

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

        if item is None:
            return None

        if block and item:
            item = item[1]

        item = pickle.loads(item)
        return item

    def get_nowait(self):
        """Equivalent to get(False)."""
        return self.get(False)

    def __getstate__(self):
        ret = {}
        ret["key"] = self.key
        return ret

    def __setstate__(self, dict):
        self.__db = getRedisConnection()
        self.__dict__.update(dict)

    def remove(self, item):
        items = self.__db.lrange(self.key, 0, -1)
        pickled_item = pickle.dumps(item)
        return self.__db.lrem(self.key, 0, pickled_item)

    def make_empty(self) -> None:
        self.__db.delete(self.key)

T = TypeVar('T')
KeyType = Union[str, int]
# Dictionary from string to T
class TangoDictionary(Protocol[T]):

    @staticmethod
    def create(dictionary_name: str) -> TangoDictionary[T]:
        if Config.USE_REDIS:
            return TangoRemoteDictionary(dictionary_name)
        else:
            return TangoNativeDictionary()
        
    @property
    @abstractmethod
    def hash_name(self) -> str:
        ...
        
    @abstractmethod
    def __contains__(self, id: KeyType) -> bool:
        ...
    @abstractmethod
    def set(self, id: KeyType, obj: T) -> str:
        ...
    @abstractmethod
    def get(self, id: KeyType) -> Optional[T]:
        ...
    @abstractmethod
    def getExn(self, id: KeyType) -> T:
        ...
    @abstractmethod
    def keys(self) -> list[str]:
        ...
    @abstractmethod
    def values(self) -> list[T]:
        ...
    @abstractmethod
    def delete(self, id: KeyType) -> None:
        ...
    @abstractmethod
    def make_empty(self) -> None:
        ...
    @abstractmethod
    def items(self) -> list[tuple[str, T]]:
        ...


# This is an abstract class that decides on
# if we should initiate a TangoRemoteDictionary or TangoNativeDictionary
# Since there are no abstract classes in Python, we use a simple method


# def TangoDictionary(object_name):
#     if Config.USE_REDIS:
#         return TangoRemoteDictionary(object_name)
#     else:
#         return TangoNativeDictionary()




class TangoRemoteDictionary(TangoDictionary[T]):
    def __init__(self, object_name):
        self.r = getRedisConnection()
        self._hash_name = object_name

    @property
    def hash_name(self) -> str:
        return self._hash_name

    def __contains__(self, id):
        return self.r.hexists(self.hash_name, str(id))

    def set(self, id, obj):
        pickled_obj = pickle.dumps(obj)

        self.r.hset(self.hash_name, str(id), pickled_obj)
        return str(id)

    def get(self, id):
        if id in self:
            unpickled_obj = self.r.hget(self.hash_name, str(id))
            obj = pickle.loads(unpickled_obj)
            return obj
        else:
            return None

    def getExn(self, id):
        job = self.get(id)
        assert job is not None, f"ID {id} does not exist in this remote dictionary"
        return job

    def keys(self):
        keys = map(lambda key: key.decode(), self.r.hkeys(self.hash_name))
        return list(keys)

    def values(self):
        vals = self.r.hvals(self.hash_name)
        valslist = []
        for val in vals:
            valslist.append(pickle.loads(val))
        return valslist

    def delete(self, id):
        self.r.hdel(self.hash_name, id)

    def make_empty(self):
        # only for testing
        self.r.delete(self.hash_name)

    def items(self):
        return iter(
            [
                (i, self.get(i))
                for i in range(1, Config.MAX_JOBID + 1)
                if self.get(i) is not None
            ]
        )


class TangoNativeDictionary(TangoDictionary[T]):
    def __init__(self):
        self.dict = {}

    @property
    def hash_name(self) -> str:
        raise ValueError("TangoNativeDictionary does not have a hash name")

    def __repr__(self):
        return str(self.dict)

    def __contains__(self, id):
        return str(id) in self.dict

    def set(self, id, obj):
        self.dict[str(id)] = obj

    def get(self, id):
        if id in self:
            return self.dict[str(id)]
        else:
            return None

    def getExn(self, id):
        job = self.get(id)
        assert job is not None, f"ID {id} does not exist in this native dictionary"
        return job

    def keys(self):
        return list(self.dict.keys())

    def values(self):
        return list(self.dict.values())

    def delete(self, id):
        if str(id) in list(self.dict.keys()):
            del self.dict[str(id)]

    def items(self):
        return iter(
            [
                (i, self.get(i))
                for i in range(1, Config.MAX_JOBID + 1)
                if self.get(i) is not None
            ]
        )

    def make_empty(self):
        # only for testing
        return
