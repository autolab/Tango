# This is a config file for run_jobs.py.
# Change the file to fit your environment.
# Please do NOT commit your changes unless
# 1. There is a need for more configuration settings and
# 2. You have made it known to Xiaolin Charlene Zang.

class Config:
  # The settings are listed in the order of most-likly a changed is needed
  # to the least-likely.

  # YOUR course name
  course = "your-name-experiment"
  course = "czang-exp"
  
  # YOUR root dir for course/lab definitions and handin (student submissions)
  courseRoot = "/n/scratch/czang/f16/"
  #courseRoot = "/n/scratch/czang/f17/"
  courseRoot = "/mnt/data/f16/"

  # YOUR lab definitions. The index of the lab is given to run_job.py
  labs = [
    {"name": "cloudfscheckpoint2dedup", "handinSuffix": ".tar", "image": "penndot.img"},
    {"name": "myftlcheckpoint1", "handinSuffix": ".cpp", "image": "penndot.img"},
    {"name": "myftlcheckpoint2", "handinSuffix": ".cpp", "image": "746.img"},
    {"name": "myftlcheckpoint3", "handinSuffix": ".cpp", "image": "746.img"},
    {"name": "myftlcheckpoint1", "handinSuffix": ".cpp", "image": "xyz.img"},
    {"name": "myftlcheckpoint3", "handinSuffix": ".cpp", "image": "xyz.img"},
    {"name": "cloudfscheckpoint1fuse", "handinSuffix": ".tar", "image": "xyz.img"}]

  # Range of student submissions to run (sorted by student emails)
  # If either is None, all student submissions are run, unless
  # -r, -f, or -s is given to run_jobs.
  firstStudentNum = 3 # start from index 3 (set to None for all students)
  totalStudents = 1 # number of students to submit

  firstStudentNum = None # set to None for all students
  
  # YOUR Tango container's root dir for submissions and output
  tangoFileRoot = "/root/autolab-oneclick/server/tango_courselabs"

  # YOUR Tango repo root (cloned from xyzisinus' Autolab github)
  tangoDir = "/h/myname/Tango"
  tangoDir = "/root/autolab-oneclick/server/Tango"

  # IP of the tango container is usually computed automatically
  tangoIP = ""

  # INFO: Where tango and redis ports are defined
  # In docker-compose.yml file (under parent dir of Tango), there can be:
  '''
    tango:
      ports:
      - '8600:8600'
      - '6380:6379'
  '''
  # The first port pair is for tango. The port before ":" is on the host and
  # the other (optional) inside the container if tango/redis are run in a
  # container.  The second line is for redis.
  # Sometimes we run multiple tango/redis containers on the same host for
  # separate experiments.  To access different tango/redis, we can give them
  # different on-host port numbers, hence the need for the HostPort variables.
  # A util script can reach the desirable entity using those varialbes.

  # Note: This variable is used by tools/util.py (run_jobs.py) only so far.
  tangoHostPort = "host-port 8600"

  # Note: This variable is used by tools/ec2Read.py only so far.
  redisHostPort = 6379  # default
  redisHostPort = 6380  

# end of class Config
