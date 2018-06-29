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
import tzlocal
import argparse

# Read aws instances, Tango preallocator pools, etc.
# Also serve as sample code for quick testing of Tango/VMMS functionalities.

class CommandLine():
  def __init__(self):
    parser = argparse.ArgumentParser(description='List AWS vms and preallocator pools')
    parser.add_argument('-d', '--destroyVMs', action='store_true', dest='destroyVMs', help="destroy VMs and empty pools")
    parser.add_argument('-D', '--instanceNameTags', metavar='instance', nargs='+',
                        help="destroy instances by name tags or AWS ids (can be partial).  \"None\" (case insensitive) deletes all instances without a \"Name\" tag")
    parser.add_argument('-l', '--list', action='store_true', dest='listVMs', help="list and ping live vms")
    parser.add_argument('-L', '--listAll', action='store_true', dest='listInstances', help="list all instances")
    self.args = parser.parse_args()

cmdLine = CommandLine()
argDestroyInstanceNameTags = cmdLine.args.instanceNameTags
argListVMs = cmdLine.args.listVMs
argListAllInstances = cmdLine.args.listInstances
argDestroyVMs = cmdLine.args.destroyVMs

local_tz = pytz.timezone("EST")
def utc_to_local(utc_dt):
  local_dt = utc_dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
  return local_tz.normalize(local_dt)

def destroyVMs():
  vms = ec2.getVMs()
  print "number of Tango VMs:", len(vms)
  for vm in vms:
    print "destroy", vm.name
    ec2.destroyVM(vm)

def pingVMs():
  vms = ec2.getVMs()
  print "number of Tango VMs:", len(vms)
  for vm in vms:
    if vm.id:
      print "ping", vm.name, vm.id
      # Note: following call needs the private key file for aws to be
      # at wherever SECURITY_KEY_PATH in config.py points to.
      # For example, if SECURITY_KEY_PATH = '/root/746-autograde.pem',
      # then the file should exist there.
      ec2.waitVM(vm, Config.WAITVM_TIMEOUT)
    else:
      print "VM not in Tango naming pattern:", vm.name

# END of function definitions #

local_tz = pytz.timezone("EST")

def utc_to_local(utc_dt):
  local_dt = utc_dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
  return local_dt.strftime("%Y%m%d-%H:%M:%S")

# to test destroying instances without "Name" tag
def deleteNameTag():
  response = boto3connection.describe_instances()
  for reservation in response["Reservations"]:
    for instance in reservation["Instances"]:
      boto3connection.delete_tags(Resources=[instance["InstanceId"]],
                                  Tags=[{"Key": "Name"}])

# to test changing tags to keep the vm after test failure
def changeTags(instanceId, name, notes):
  print "change tags for", instanceId
  instance = boto3resource.Instance(instanceId)
  tag = boto3resource.Tag(instanceId, "Name", name)
  if tag:
    tag.delete()
  instance.create_tags(Tags=[{"Key": "Name", "Value": "failed-" + name}])
  instance.create_tags(Tags=[{"Key": "Notes", "Value": notes}])

def instanceNameTag(instance):
  name = "None"
  if "Tags" in instance:
    for tag in instance["Tags"]:
      if tag["Key"] == "Name":
        name = tag["Value"]
  return name

def listInstances(all=None):
  sortedInstances = []
  nameInstances = []
  instanceType = "all"
  response = boto3connection.describe_instances()
  for reservation in response["Reservations"]:
    for instance in reservation["Instances"]:
      if not all and instance["State"]["Name"] != "running":
        instanceType = "running"
        continue
      nameInstances.append({"Name": instanceNameTag(instance),
                            "Instance": instance})

  sortedInstances = sorted(nameInstances, key=lambda x: x["Name"])
  print "number of", instanceType, "AWS instances:", len(sortedInstances)

  for item in sortedInstances:
    instance = item["Instance"]
    launchTime = utc_to_local(instance["LaunchTime"])
    if "PublicIpAddress" in instance:
      print("%s: %s %s %s %s" %
            (item["Name"], instance["InstanceId"],
             launchTime, instance["State"]["Name"],
             instance["PublicIpAddress"]))
    else:
      print("%s: %s %s %s" %
            (item["Name"], instance["InstanceId"],
             launchTime, instance["State"]["Name"]))
    if "Tags" in instance:
      for tag in instance["Tags"]:
        if (tag["Key"] != "Name"):
          print("\t tag {%s: %s}" % (tag["Key"], tag["Value"]))
    else:
      print("\t No tags")

  """ useful sometimes
    print "ImageId:", instance["ImageId"]
    print "PublicDnsName:", instance["PublicDnsName"]
    print "InstanceType:", instance["InstanceType"]
    print "State:", instance["State"]["Name"]
    print "SecurityGroups:", instance["SecurityGroups"]
    image = boto3resource.Image(instance["ImageId"])
    print "Image:", image.image_id
    for tag in image.tags:
    print("\t tag {%s: %s}" % (tag["Key"], tag["Value"]))
  """

  return sortedInstances

def listPools():
  print "Tango VM pools by AWS image", ec2.img2ami.keys()
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
  host=Config.REDIS_HOSTNAME, port=config_for_run_jobs.Config.redisHostPort, db=0)
tangoObjects.getRedisConnection(connection=redisConnection)
boto3connection = boto3.client("ec2", Config.EC2_REGION)
boto3resource = boto3.resource("ec2", Config.EC2_REGION)

server = TangoServer()
ec2 = server.preallocator.vmms["ec2SSH"]
pools = ec2.img2ami

if argDestroyInstanceNameTags:
  sortedInstances = listInstances()
  totalTerminated = []

  for partialStr in argDestroyInstanceNameTags:
    matchingInstances = []
    if partialStr.lower() == "NoNameTag".lower():  # without "Name" tag
      for item in sortedInstances:
        if "None" == instanceNameTag(item["Instance"]):
          matchingInstances.append(item)
    elif partialStr.startswith("i-"):  # match instance id
      for item in sortedInstances:
        if item["Instance"]["InstanceId"].startswith(partialStr):
          matchingInstances.append(item)
    else:
      for item in sortedInstances:  # match a "Name" tag that is not None
        if instanceNameTag(item["Instance"]).startswith(partialStr) or \
           instanceNameTag(item["Instance"]).endswith(partialStr):
          matchingInstances.append(item)

    # remove the items already terminated
    instancesToTerminate = []
    for item in matchingInstances:
      if not any(x["Instance"]["InstanceId"] == item["Instance"]["InstanceId"] for x in totalTerminated):
        instancesToTerminate.append(item)
        totalTerminated.append(item)

    if instancesToTerminate:
      print "terminate %d instances matching query string \"%s\"" % (len(instancesToTerminate), partialStr)
      listInstances(instancesToTerminate)
      for item in instancesToTerminate:
        boto3connection.terminate_instances(InstanceIds=[item["Instance"]["InstanceId"]])
    else:
      print "no instances matching query string \"%s\"" % partialStr
  # end of for loop partialStr

  print "Afterwards"
  print "----------"
  listInstances('all')
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

# Start of main actions

listInstances()
listPools()
createInstances(1)
listInstances()
listPools()
exit()

