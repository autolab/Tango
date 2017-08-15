import os, re, glob, datetime, time

from util import Config
from util import Cmd
from util import CommandLine
from util import Lab

# drive student submissions to Tango.  See ./util.py for preset configuratons.
# the script finds course and labs at a specified location and submits work
# from the handin directory.
# It then waits for all output files to have newer modification time.

cfg = Config()
cmdLine = CommandLine(cfg)
cmd = Cmd(cfg)

startTime = time.mktime(datetime.datetime.now().timetuple())
outputFiles = []

# if either is None, then all student works are submitted.
firstStudentNum = 1
totalStudents = 2

for labIndex in cmdLine.args.indecies:
  if labIndex >= len(cfg.labs):
    print("lab index %d is out of range" % labIndex)
    exit(-1)

for labIndex in cmdLine.args.indecies:
  lab = Lab(cfg, labIndex)
  cmd.info()
  cmd.open(lab)

  students = []
  student2fileFullPath = {}
  student2file = {}

  # get student handin files, the last submission for each student,
  # and make a map from email to useful attrbutes
  
  for file in sorted(glob.glob(lab.handinFilesQuery)):
    baseName = file.split("/").pop()
    matchObj = re.match(r'(.*)_[0-9]+_(.*)', baseName, re.M|re.I)
    email = matchObj.group(1)
    
    withoutSuffix = baseName.replace(lab.handinSuffix, "")
    outputFile = withoutSuffix + "_" + lab.name + ".txt"
    jobName = lab.courseLab + "_" + withoutSuffix
    
    if email not in students:
      students.append(email)
    studentFile = {"full": file, "base": baseName, "job": jobName,
                   "stripped": matchObj.group(2), "output": outputFile}
    student2file[email] = studentFile

  # submit all student works or a given range
  if not (firstStudentNum and totalStudents):
    firstStudentNum = 0
    totalStudents = len(students)

  print ("# Found %d students for lab %s" % (len(students), lab.name))
  print ("# Students index range %d..%d" % (firstStudentNum, totalStudents))

  # load lab files
  cmd.upload(lab, lab.makefile)
  cmd.upload(lab, lab.autogradeTar)

  # load and run student submission
  for i in range (firstStudentNum, firstStudentNum + totalStudents):
    print ("\n# Submit for %s @ %s" % (students[i], lab.name))
    cmd.upload(lab, student2file[students[i]]["full"])
    cmd.addJob(lab, student2file[students[i]])
    outputFiles.append(lab.outputDir + "/" + student2file[students[i]]["output"])
# end of main loop "cmdLine.args.indecies"

print "\nNow waiting for output files..."
remainingFiles = list(outputFiles)
numberRemaining = len(remainingFiles)
loopDelay = 5

while True:
  time.sleep(loopDelay)

  finishedFiles = []
  for file in remainingFiles:
    if os.path.getmtime(file) > startTime:
      print("Output %s is ready" % file)
      finishedFiles.append(file)

  remainingFiles = set(remainingFiles) - set(finishedFiles)
  nFinished = numberRemaining - len(remainingFiles)
  print("%d jobs finished in the last %d seconds" % (nFinished, loopDelay))
  now = time.mktime(datetime.datetime.now().timetuple())
  print("%s has passed\n" % (str(datetime.timedelta(seconds = now - startTime))))

  numberRemaining = len(remainingFiles)
  if numberRemaining == 0:
    print "All output files are counted for :))"
    break
