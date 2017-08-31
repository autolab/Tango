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
firstStudentNum = None
totalStudents = 1

for labIndex in cmdLine.args.indecies:
  if labIndex >= len(cfg.labs):
    print("lab index %d is out of range" % labIndex)
    exit(-1)

for labIndex in cmdLine.args.indecies:
  lab = Lab(cfg, labIndex)

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

  # print the students and the indices
  if False:
    i = 0
    for student in students:
      print i, student
      i += 1
    exit()

  # submit all student works or a given range, or given student list
  studentIndexList = []
  studentsToRun = []
  if cmdLine.args.students:
    for studentToRun in cmdLine.args.students:
      studentIndex = None
      nMatches = 0
      index = 0
      for student in students:
        if student.startswith(studentToRun):
          studentIndex = index
          nMatches += 1
        index += 1
      if nMatches != 1:
        print "ERROR: no match or multiple matchs found for", studentToRun
        exit()
      studentIndexList.append(studentIndex)
      studentsToRun.append(studentToRun)

  else:
    if firstStudentNum is None or totalStudents is None:
      firstStudentNum = 0
      totalStudents = len(students)
    studentIndexList = list(index for index in range (firstStudentNum, firstStudentNum + totalStudents))


  print ("# Found %d students for lab %s" % (len(students), lab.name))
  if studentsToRun:
    print ("# Students submissions %s" % studentsToRun)
  else:
    print ("# Students index starts at %d and total %d" % (firstStudentNum, totalStudents))

  cmd.info()
  cmd.open(lab)

  # load lab files
  cmd.upload(lab, lab.makefile)
  cmd.upload(lab, lab.autogradeTar)

  # load and run student submission
  for i in studentIndexList:
    print ("\n# Submit for %s @ %s" % (students[i], lab.name))
    cmd.upload(lab, student2file[students[i]]["full"])
    cmd.addJob(lab, student2file[students[i]])
    outputFiles.append(lab.outputDir + "/" + student2file[students[i]]["output"])
# end of main loop "cmdLine.args.indecies"

print "\nNow waiting for output files..."
remainingFiles = list(outputFiles)
numberRemaining = len(remainingFiles)
loopDelay = 5
badOutputFiles = []

while True:
  time.sleep(loopDelay)

  finishedFiles = []
  for file in remainingFiles:
    if os.path.exists(file) and os.path.getmtime(file) > startTime:
      finishedFiles.append(file)
      if "\"scores\":" not in open(file).read():
        badOutputFiles.append(file)
        print("BAD output %s" % file)
        os.system("tail -5 %s" % file)
      else:
        print("Output %s is ready" % file)

  remainingFiles = set(remainingFiles) - set(finishedFiles)
  nFinished = numberRemaining - len(remainingFiles)
  print("%d jobs finished in the last %d seconds" % (nFinished, loopDelay))
  print("%d unfinished out of %d" % (len(remainingFiles), len(outputFiles)))
  now = time.mktime(datetime.datetime.now().timetuple())
  print("%s has passed\n" % (str(datetime.timedelta(seconds = now - startTime))))

  numberRemaining = len(remainingFiles)
  if numberRemaining == 0:
    print "All output files are counted for :))"
    break

if badOutputFiles:
  print("Found %d bad output files" % len(badOutputFiles))
  for f in badOutputFiles:
    print("bad output: %s" % f)
