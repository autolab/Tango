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
  
  # YOUR root dir for course/lab definitions and handin (student submissions)
  courseRoot = "/n/scratch/czang/f16/"

  # YOUR lab definitions. The index of the lab is given to run_job.py
  labs = [
    {"name": "myftlcheckpoint1", "handinSuffix": ".cpp", "image": "746.img"},
    {"name": "myftlcheckpoint3", "handinSuffix": ".cpp", "image": "newPool.img"},
    {"name": "cloudfscheckpoint1fuse", "handinSuffix": ".tar", "image": "newPool.img"}]

  # Range of student submissions to run (sorted by student emails)
  # If either is None, all student submissions are run, unless
  # -r, -f, or -s is given to run_jobs.
  firstStudentNum = 3 # start from index 3 (set to None for all students)
  totalStudents = 1 # run one student

  # YOUR Tango container's root dir for submissions and output
  tangoFileRoot = "/root/autolab-oneclick/server/tango_courselabs"
  
  # YOUR Tango repo root (cloned from xyzisinus' Autolab github)
  tangoDir = "/h/myname/Tango"

  # Sometimes multiple experimental Tango containers are run on one machine.
  # They are identified by different ports.
  tangoHostPort = "host-port 8600"

  # IP of the tango container is usually computed automatically
  tangoIP = ""
  
# end of class Config
