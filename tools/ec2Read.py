import os, sys, time, re, json, pprint
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
import boto3

# test vmms.ec2SSH's image extraction code, etc
# also serve as a template of accessing the ec2SSH vmms

def destroyInstances():
  vms = ec2.getVMs()
  for vm in vms:
    if re.match("%s-" % Config.PREFIX, vm.name):
      print "destroy", vm.name
      ec2.destroyVM(vm)

def listInstancesLong():
  nameInstances = []
  response = ec2client.describe_instances()
  for reservation in response["Reservations"]:
    for instance in reservation["Instances"]:
      if instance["State"]["Name"] != "running":
        continue
      nameTag = (item for item in instance["Tags"] if item["Key"] == "Name").next()
      nameInstances.append({"Name": nameTag["Value"] if nameTag else "None",
                            "Instance": instance})

  print len(nameInstances), "instances:"
  for item in sorted(nameInstances, key=lambda x: x["Name"]):
    # pp = pprint.PrettyPrinter(indent=2)
    # pp.pprint(instance)
    instance = item["Instance"]
    print("%s: %s %s %s" %
          (item["Name"], instance["InstanceId"], instance["PublicIpAddress"], instance["LaunchTime"]))
    for tag in instance["Tags"]:
      print("\t tag {%s: %s}" % (tag["Key"], tag["Value"]))

  """ useful sometimes
    print "ImageId:", instance["ImageId"]
    print "PublicDnsName:", instance["PublicDnsName"]
    print "InstanceType:", instance["InstanceType"]
    print "State:", instance["State"]["Name"]
    print "SecurityGroups:", instance["SecurityGroups"]
    image = ec2resource.Image(instance["ImageId"])
    print "Image:", image.image_id
    for tag in image.tags:
    print("\t tag {%s: %s}" % (tag["Key"], tag["Value"]))
  """

def listInstances():
  """
  vms = ec2.getVMs()
  print "aws instances", len(vms)
  for vm in sorted(vms, key=lambda x: x.name):
    print "vm", vm.name, vm.ec2_id
  """
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
ec2client = boto3.client("ec2", Config.EC2_REGION)
ec2resource = boto3.resource("ec2", Config.EC2_REGION)

server = TangoServer()
ec2 = server.preallocator.vmms["ec2SSH"]
pools = ec2.img2ami

listInstancesLong()
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

