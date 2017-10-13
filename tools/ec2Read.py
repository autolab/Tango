import os, sys, time, re
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vmms.ec2SSH import Ec2SSH
from preallocator import Preallocator
from tangoObjects import TangoQueue
from tangoObjects import TangoMachine
from tango import TangoServer
from config import Config
import tangoObjects
import config_for_run_jobs
import redis

# test vmms.ec2SSH's image extraction code, etc
# also serve as a template of accessing the ec2SSH vmms

def destroyInstances():
  vms = ec2.getVMs()
  for vm in vms:
    if re.match("%s-" % Config.PREFIX, vm.name):
      print "destroy", vm.name
      ec2.destroyVM(vm)

def listInstances():
  vms = ec2.getVMs()
  print "aws instances", len(vms)
  for vm in sorted(vms, key=lambda x: x.name):
    print "vm", vm.name
  print "pools", ec2.img2ami.keys()
  for key in server.preallocator.machines.keys():
    pool = server.preallocator.getPool(key)
    totalPool = pool["total"]
    freePool = pool["free"]
    totalPool.sort()
    freePool.sort()
    print "pool", key, "total", len(totalPool), totalPool, freePool

def createInstances(num):
  for imageName in pools:
    (poolName, ext) = os.path.splitext(imageName)
    print "creating", num, "for pool", poolName
    vm = TangoMachine(vmms="ec2SSH", image=imageName)
    server.preallocVM(vm, num)

def shrinkPools():
  for imageName in pools:
    (poolName, ext) = os.path.splitext(imageName)
    vm = TangoMachine(vmms="ec2SSH", image=imageName)
    vm.name = poolName
    print "shrink pool", vm.name
    server.preallocator.decrementPoolSize(vm)

def destroyRedisPools():
  for key in server.preallocator.machines.keys():
    print "clean up pool", key
    server.preallocator.machines.set(key, [[], TangoQueue(key)])
    server.preallocator.machines.get(key)[1].make_empty()

def allocateVMs():
  freeList = []
  for key in server.preallocator.machines.keys():
    server.preallocator.allocVM(key)
    total = server.preallocator.getPool(key)["total"]
    free = server.preallocator.getPool(key)["free"]
    print "after allocation", key, total, free


# When a host has two Tango containers (for experiment), there are two
# redis servers, too.  They differ by the forwarding port number, which
# is defined in config_for_run_jobs.py.  To select the redis server,
# We get the connection here and pass it into tangoObjects
redisConnection = redis.StrictRedis(
  host=Config.REDIS_HOSTNAME, port=config_for_run_jobs.Config.redisPort, db=0)
tangoObjects.getRedisConnection(connection=redisConnection)

server = TangoServer()
ec2 = server.preallocator.vmms["ec2SSH"]
pools = ec2.img2ami

listInstances()
exit()
destroyInstances()
destroyRedisPools()
createInstances(2)
shrinkPools()
exit()

allocateVMs()
exit()
server.resetTango(server.preallocator.vmms)
listInstances()

