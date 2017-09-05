import subprocess, os, argparse, glob, re

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
                        help="student emails (can be partial)")
    parser.add_argument('-f', '--failures', action='store_true',
                        help="exam failures")
    parser.add_argument('-r', '--re_run', action='store_true',
                        help="re-run failed jobs")
    parser.add_argument('-H', '--handin_records', action='store_true',
                        help="exam failures or re-run jobs from handin records")
    parser.add_argument('-l', '--list_students', action='store_true',
                        help="list student submissions")
    parser.add_argument('-d', '--dry_run', action='store_true',
                        help="dry_run")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="more info")
    self.args = parser.parse_args()
# end of class CmdLine

# represent attributes associated to a given lab
class Lab:
  def __init__(self, cfg, cmdLine, labIndex):
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
    self.outputDir = "/".join([cfg.tangoFileRoot,
                               "test-" + self.courseLab,
                               "output"])
    self.outputFileQuery = self.outputDir + "/*" + self.name + ".txt"
    if cmdLine.args.handin_records:
      self.outputFileQuery = self.courseLabDir + "/handin/*" + self.name + "_autograde.txt"
    print "EXAM FAILURES from", self.outputFileQuery
# end of class Lab
  
class Cmd:
  def __init__(self, cfg, cmdLine):
    self.cfg = cfg
    self.cmdLine = cmdLine
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

    self.basic = "python " + cfg.tangoDir + "/clients/tango-cli.py"
    self.basic += " -s " + cfg.tangoIP + " -P 8600" + " -k test"

    print "CMD BASE:", self.basic
  #end of __init__

  def run(self, cmd):  # an internal util function
    if self.cmdLine.args.dry_run:
      print "DRY-RUN tango-cli", cmd
    else:
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
# end of class Cmd

# =================== stand alone functions ======================

# get student handin files or output files, assuming file names start with student email
def getStudent2file(lab, fileQuery):
  files = sorted(glob.glob(lab.outputFileQuery))  # files are sorted by student email
  students = []
  student2file = {}
  student2version = {}

  for f in files:
    baseName = f.split("/").pop()
    matchObj = re.match(r'(.*)_([0-9]+)_(.*)', baseName, re.M|re.I)
    (email, version) = (matchObj.group(1), matchObj.group(2))
    if email not in students:
      students.append(email)
    if email not in student2version or version > student2version[email]:
      student2version[email] = version
      student2file[email] = f
  return (students, student2file)

def getRerunList(cfg, lab):
  (students, student2file) = getStudent2file(lab, lab.outputFileQuery)

  failedStudents = []
  for s in students:
    if "\"scores\":" not in open(student2file[s]).read():
      failedStudents.append(s)

  return failedStudents
