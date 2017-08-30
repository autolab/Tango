import subprocess, os, argparse

class Config:
  # tangoDir = "/root/autolab-oneclick/server/Tango"
  tangoDir = "/nfs/autolab/pdl.cmu.edu/Tango"
  cliCmd = "python " + tangoDir + "/clients/tango-cli.py"
  tangoHostPort = "host-port 8600"
  tangoIP = ""
  # output dir used by Tango for submissions
  # tangoFileRoot = "/root/autolab-oneclick/server/tango_courselabs"
  tangoFileRoot = "/nfs/autolab/pdl.cmu.edu/tango_courselabs"
  
  # course definition and handin files location  
  course = "czang-exp"
  # courseRoot = "/n/scratch/czang/f16/"
  courseRoot = "/mnt/autolab/"
  labs = [
    # same test with different images, to test multiple pool (per image) handling
    {"name": "myftlcheckpoint1", "handinSuffix": ".cpp", "image": "746.img"},
    {"name": "myftlcheckpoint1", "handinSuffix": ".cpp", "image": "newPool.img"},
    {"name": "myftlcheckpoint3", "handinSuffix": ".cpp", "image": "newPool.img"},
    {"name": "cloudfscheckpoint1fuse", "handinSuffix": ".tar", "image": "newPool.img"}]

  # when "list failures" is requested, the failed tests are listed from the output dir
  # for the course/lab, unless the following is true.  The the lab's handin from courseRoot
  # is used.
  examFailuresFromCourseRoot = False

class CommandLine():
  def printLabs(self, name=None):
    print ("available tests:")
    print ("index\ttest")
    i = 0
    for lab in self.cfg.labs:
      print ("%d\t%s" % (i, lab["name"]))
      i += 1
    print
  
  def __init__(self, cfg):
    self.cfg = cfg
    parser = argparse.ArgumentParser(description='Drive jobs to Tango',
                                     usage=self.printLabs())
    parser.add_argument('indecies', metavar='index', type=int, nargs='+',
                        help="index of a test")
    parser.add_argument('-s', '--students', metavar='student', nargs='+',
                        help="student email")
    parser.add_argument('-f', '--failures', action='store_true',
                        help="list failures")
    parser.add_argument('-r', '--re_run', action='store_true',
                        help="re-run failed jobs")
    self.args = parser.parse_args()

# represent attributes associated to a given lab
class Lab:
  def __init__(self, cfg, labIndex):
    self.cfg = cfg
    self.name = cfg.labs[labIndex]["name"]
    self.handinSuffix = cfg.labs[labIndex]["handinSuffix"]
    self.image = cfg.labs[labIndex]["image"]
    self.courseLab = cfg.course + "." + self.name
    self.courseLabDir = cfg.courseRoot + "/" + self.name
    self.makefile = self.courseLabDir + "/" + "autograde-Makefile"
    self.autogradeTar = self.courseLabDir + "/" + "autograde.tar"
    self.handinFilesQuery = "/".join([self.courseLabDir,
                                      "handin",
                                      "*" + self.handinSuffix])
    self.outputDir = None
    if cfg.tangoFileRoot:
      self.outputDir = "/".join([cfg.tangoFileRoot,
                                      "test-" + self.courseLab,
                                      "output"])
  
class Cmd:
  def __init__(self, cfg):
    self.cfg = cfg
    outBytes = subprocess.check_output(["ps", "-auxw"])
    for line in outBytes.decode("utf-8").split("\n"):
      if cfg.tangoHostPort in line:
        argList = line.split()
        for index, token in enumerate(argList):
          if token == "-container-ip":
            cfg.tangoIP = argList[index + 1]
    if cfg.tangoIP == "":
      print "ERROR: Cannot find tango server IP"
      exit(-1)

    self.basic = cfg.cliCmd
    self.basic += " -s " + cfg.tangoIP + " -P 8600" + " -k test"

    print "CMD BASE:", self.basic
  #end of __init__

  def run(self, cmd):  # an internal util function
    print "EXEC tango-cli", cmd
    os.system(self.basic + cmd)
    print "======================================="    

  def info(self):
    self.run(" --info")

  def open(self, lab):
    self.run(" --open -l " + lab.courseLab)

  def upload(self, lab, file):
    self.run(" --upload --filename " + file + " -l " + lab.courseLab)

  def addJob(self, lab, studentFile):
    myCmd = " --addJob --image " + lab.image + " -l " + lab.courseLab
    myCmd += " --jobname job_" + studentFile["job"]
    myCmd += " --outputFile " + studentFile["output"]
    myCmd += " --infiles"
    myCmd += " '{\"localFile\": \"%s\", \"destFile\": \"%s\"}' " % \
             (studentFile["base"], studentFile["stripped"])
    myCmd += " '{\"localFile\": \"autograde-Makefile\", \"destFile\": \"Makefile\"}' "
    myCmd += " '{\"localFile\": \"autograde.tar\", \"destFile\": \"autograde.tar\"}' "
    self.run(myCmd)

  def poll(self, lab, studentFile):
    myCmd = " --poll -l " + lab.courseLab
    self.run(myCmd + " --outputFile " + studentFile["output"])
