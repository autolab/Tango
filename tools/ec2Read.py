import os, sys, time, re, json, pprint, datetime
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
import pytz
import argparse

# Read aws instances, Tango preallocator pools, etc.
# Also serve as sample code for quick testing of Tango/VMMS functionalities.

class CommandLine():
  def __init__(self):
    parser = argparse.ArgumentParser(
      description='List AWS vms and preallocator pools')
    parser.add_argument('-a', '--accessIdKeyUser',
                        help="aws access id, key and user, space separated")
    parser.add_argument('-c', '--createVMs', action='store_true',
                        dest='createVMs', help="add a VM for each pool")
    parser.add_argument('-C', '--createInstance', action='store_true',
                        dest='createInstance', help="create an instance without adding to a pool")
    parser.add_argument('-d', '--destroyVMs', action='store_true',
                        dest='destroyVMs', help="destroy VMs and empty pools")
    parser.add_argument('-D', '--instanceNameTags', nargs='+',
                        help="destroy instances by name tags or AWS ids (can be partial).  \"None\" (case insensitive) deletes all instances without a \"Name\" tag")
    parser.add_argument('-l', '--list', action='store_true',
                        dest='listVMs', help="list and ping live vms")
    parser.add_argument('-L', '--listAll', action='store_true',
                        dest='listInstances', help="list all instances")
    self.args = parser.parse_args()

cmdLine = CommandLine()
argDestroyInstanceByNameTags = cmdLine.args.instanceNameTags
argListVMs = cmdLine.args.listVMs
argListAllInstances = cmdLine.args.listInstances
argDestroyVMs = cmdLine.args.destroyVMs
argCreateVMs = cmdLine.args.createVMs
argCreateInstance = cmdLine.args.createInstance
argAccessIdKeyUser = cmdLine.args.accessIdKeyUser

def destroyVMs():
  vms = ec2.getVMs()
  print "number of Tango VMs:", len(vms)
  for vm in vms:
    if vm.id:
      print "destroy", nameToPrint(vm.name)
      ec2.destroyVM(vm)
    else:
      print "VM not in Tango naming pattern:", nameToPrint(vm.name)

def pingVMs():
  vms = ec2.getVMs()
  print "number of Tango VMs:", len(vms)
  for vm in vms:
    if vm.id:
      print "ping", nameToPrint(vm.name)
      # Note: following call needs the private key file for aws to be
      # at wherever SECURITY_KEY_PATH in config.py points to.
      # For example, if SECURITY_KEY_PATH = '/root/746-autograde.pem',
      # then the file should exist there.
      ec2.waitVM(vm, Config.WAITVM_TIMEOUT)
    else:
      print "VM not in Tango naming pattern:", nameToPrint(vm.name)

local_tz = pytz.timezone(Config.AUTODRIVER_LOGGING_TIME_ZONE)
def utc_to_local(utc_dt):
  local_dt = utc_dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
  return local_dt.strftime("%Y%m%d-%H:%M:%S")

# to test destroying instances without "Name" tag
def deleteNameTagForAllInstances():
  instances = listInstances()
  for instance in instances:
    boto3connection.delete_tags(Resources=[instance["Instance"].id],
                                Tags=[{"Key": "Name"}])
  print "Afterwards"
  print "----------"
  listInstances()

# to test changing tags to keep the vm after test failure
def changeTagForAllInstances():
  instances = listInstances()
  for inst in instances:
    instance = inst["Instance"]
    name = inst["Name"]
    notes = "tag " + name + " deleted"
    boto3connection.delete_tags(Resources=[instance["InstanceId"]],
                                Tags=[{"Key": "Name"}])
    boto3connection.create_tags(Resources=[instance["InstanceId"]],
                                Tags=[{"Key": "Name", "Value": "failed-" + name},
                                      {"Key": "Notes", "Value": notes}])

  print "Afterwards"
  print "----------"
  listInstances()

def listInstances(all=None):
  nameAndInstances = []

  filters=[]
  instanceType = "all"
  if not all:
    filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
    instanceType = "running"

  instances = boto3resource.instances.filter(Filters=filters)
  for instance in boto3resource.instances.filter(Filters=filters):
    nameAndInstances.append({"Name": ec2.getTag(instance.tags, "Name"),
                          "Instance": instance})

  nameAndInstances.sort(key=lambda x: x["Name"])
  print "number of", instanceType, "AWS instances:", len(nameAndInstances)

  for item in nameAndInstances:
    instance = item["Instance"]
    launchTime = utc_to_local(instance.launch_time)
    if instance.public_ip_address:
      print("%s: %s %s %s %s" %
            (nameToPrint(item["Name"]), instance.id,
             launchTime, instance.state["Name"],
             instance.public_ip_address))
    else:
      print("%s: %s %s %s" %
            (nameToPrint(item["Name"]), instance.id,
             launchTime, instance.state["Name"]))

    if instance.tags:
      for tag in instance.tags:
        if (tag["Key"] != "Name"):
          print("\t tag {%s: %s}" % (tag["Key"], tag["Value"]))
    else:
      print("\t No tags")

    print "\t InstanceType:", instance.instance_type
    """ useful sometimes
    image = boto3resource.Image(instance.image_id)
    print "\t ImageId:", image.image_id
    for tag in image.tags:
      print("\t\t image tag {%s: %s}" % (tag["Key"], tag["Value"]))
    """

  return nameAndInstances

def listPools():
  print "known AWS images:", ec2.img2ami.keys()
  knownPools = server.preallocator.machines.keys()
  print "Tango VM pools:", "" if knownPools else "None"

  for key in knownPools:
    pool = server.preallocator.getPool(key)
    totalPool = pool["total"]
    freePool = pool["free"]
    totalPool.sort()
    freePool.sort()
    print "pool", nameToPrint(key), "total", len(totalPool), totalPool, freePool

def nameToPrint(name):
    return "[" + name + "]" if name else "[None]"

# allocate "num" vms for each and every pool (image)
def addVMs():
  # Add a vm for each image and a vm for the first image plus instance type
  instanceTypeTried = False
  for key in ec2.img2ami.keys():
    vm = TangoMachine(vmms="ec2SSH", image=key)
    pool = server.preallocator.getPool(vm.pool)
    currentCount = len(pool["total"]) if pool else 0
    print "adding a vm into pool", nameToPrint(vm.pool), "current size", currentCount
    server.preallocVM(vm, currentCount + 1)

    if instanceTypeTried:
      continue
    else:
      instanceTypeTried = True

    vm = TangoMachine(vmms="ec2SSH", image=key+"+t2.small")
    pool = server.preallocator.getPool(vm.pool)
    currentCount = len(pool["total"]) if pool else 0
    print "adding a vm into pool", nameToPrint(vm.pool), "current size", currentCount
    server.preallocVM(vm, currentCount + 1)

def destroyRedisPools():
  for key in server.preallocator.machines.keys():
    print "clean up pool", key
    server.preallocator.machines.set(key, [[], TangoQueue(key)])
    server.preallocator.machines.get(key)[1].make_empty()

# END of function definitions #

# When a host has two Tango containers (for experiment), there are two
# redis servers, too.  They differ by the forwarding port number, which
# is defined in config_for_run_jobs.py.  To select the redis server,
# We get the connection here and pass it into tangoObjects
redisConnection = redis.StrictRedis(
  host=Config.REDIS_HOSTNAME, port=config_for_run_jobs.Config.redisHostPort, db=0)
tangoObjects.getRedisConnection(connection=redisConnection)
boto3connection = boto3.client("ec2", Config.EC2_REGION)
boto3resource = boto3.resource("ec2", Config.EC2_REGION)

server = TangoServer()
ec2 = server.preallocator.vmms["ec2SSH"]
pools = ec2.img2ami

if argDestroyInstanceByNameTags:
  nameAndInstances = listInstances()
  totalTerminated = []

  matchingInstances = []
  for partialStr in argDestroyInstanceByNameTags:
    if partialStr.startswith("i-"):  # match instance id
      for item in nameAndInstances:
        if item["Instance"].id.startswith(partialStr):
          matchingInstances.append(item)
    else:
      # part of "Name" tag or None to match instances without name tag
      for item in nameAndInstances:
        nameTag = ec2.getTag(item["Instance"].tags, "Name")
        if nameTag and \
           (nameTag.startswith(partialStr) or nameTag.endswith(partialStr)):
          matchingInstances.append(item)
        elif not nameTag and partialStr == "None":
          matchingInstances.append(item)

  # the loop above may generate duplicates in matchingInstances
  terminatedInstances = []
  for item in matchingInstances:
    if item["Instance"].id not in terminatedInstances:
      boto3connection.terminate_instances(InstanceIds=[item["Instance"].id])
      terminatedInstances.append(item["Instance"].id)

  if terminatedInstances:
    print "terminate %d instances matching query string \"%s\":" % \
      (len(terminatedInstances), argDestroyInstanceByNameTags)
    for id in terminatedInstances:
      print id
    print "Afterwards"
    print "----------"
    listInstances()
  else:
    print "no instances matching query string \"%s\"" % argDestroyInstanceByNameTags

  exit()

if argListAllInstances:
  listInstances("all")
  exit()

if argListVMs:
  listInstances()
  listPools()
  pingVMs()
  exit()

if argDestroyVMs:
  destroyVMs()
  destroyRedisPools()
  print "Afterwards"
  print "----------"
  listInstances()
  listPools()
  exit()

if argCreateVMs:
  listInstances()
  listPools()
  addVMs()  # add 1 vm for each image and each image plus instance type
  listInstances()
  listPools()
  exit()

# Create number of instances (no pool), some of them without name tag
# to test untagged stale machine cleanup ability in Tango.
# watch tango.log for the cleanup actions.
if argCreateInstance:
    # The cleanup function is not active unless the application is
    # jobManager.  Therefore we start it manually here.
    if hasattr(ec2, 'setTimer4cleanup'):
        print "start setTimer4cleanup function in vmms"
        ec2.setTimer4cleanup()

    i = 0
    while True:
        vm = TangoMachine(vmms="ec2SSH")
        vm.id = int(datetime.datetime.utcnow().strftime('%s'))
        vm.image = '746'
        vm.pool = '746'
        vm.name = ec2.instanceName(vm.id, vm.pool)
        result = ec2.initializeVM(vm)
        if result:
            print "created: ", result.name, result.instance_id
        else:
            print "failed to create"
            break

        # delete name tage for half of instances
        if i % 2 == 0:
            boto3connection.delete_tags(Resources=[result.instance_id],
                                        Tags=[{"Key": "Name"}])
        i += 1
        time.sleep(30)

        if i > 20:
            break

    time.sleep(10000)
    exit()

# ec2WithKey can be used to test the case that tango_cli uses
# non-default aws access id and key
if argAccessIdKeyUser:
  if len(argAccessIdKeyUser.split()) != 3:
    print "access id, key and user must be quoted and space separated"
    exit()
  (id, key, user) = argAccessIdKeyUser.split()
  ec2WithKey = Ec2SSH(accessKeyId=id, accessKey=key, ec2User=user)
  vm = TangoMachine(vmms="ec2SSH")
  vm.id = int(2000)  # a high enough number to avoid collision
  # to test non-default access id/key, the aws image must have the key manually
  # installed or allows the key to be installed by the aws service.
  # the following assumes we have such image with a "Name" tag "test01.img"
  vm.pool = "test01"
  ec2WithKey.initializeVM(vm)
  ec2WithKey.waitVM(vm, Config.WAITVM_TIMEOUT)
  listInstances()

# Write combination of ops not provided by the command line options here:
