import sys, os
# search parent dirs for importable packages
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tangoObjects import TangoDictionary

# list all "machines" pools and get the total and free sets for each pool
# it also serves as a template of extracting contents from redis

machines = TangoDictionary("machines")
print "pools", machines.keys()

for poolName in machines.keys():
  print "pool:", poolName
  print "total:", machines.get(poolName)[0]
  print "free:", machines.get(poolName)[1].qsize(), machines.get(poolName)[1].dump()
