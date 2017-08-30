import os, sys, time, re
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vmms.ec2SSH import Ec2SSH
from preallocator import Preallocator
from tangoObjects import TangoQueue
from tangoObjects import TangoMachine
from tango import TangoServer
from config import Config

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
  print "aws instances"
  for vm in vms:
    print "vm", vm.name
  print "list instances", len(vms)
  for key in server.preallocator.machines.keys():
    pool = server.preallocator.getPool(key)
    print "pool", key, pool["total"], pool["free"]

def createInstances(num):
  for imageName in pools:
    (poolName, ext) = os.path.splitext(imageName)
    print "creating", num, "for pool", poolName
    vm = TangoMachine(vmms="ec2SSH", image=imageName)
    server.preallocVM(vm, num)

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

server = TangoServer()
ec2 = server.preallocator.vmms["ec2SSH"]
pools = ec2.img2ami

listInstances()
destroyInstances()
destroyRedisPools()
createInstances(2)
allocateVMs()
server.resetTango(server.preallocator.vmms)
listInstances()

exit()
