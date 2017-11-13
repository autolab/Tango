import os, re, glob, datetime, time

from config_for_run_jobs import Config
from util import Cmd
from util import CommandLine
from util import Lab
import util

# drive student submissions to Tango.  See ./util.py for preset configuratons.
# the script finds course and labs at a specified location and submits work
# from the handin directory.
# It then waits for all output files to have newer modification time.

cfg = Config()
cmdLine = CommandLine(cfg)
cmd = Cmd(cfg, cmdLine)

if cmdLine.args.jobs:
  cmd.jobs()
  exit()


startTime = time.mktime(datetime.datetime.now().timetuple())
outputFiles = []

for labIndex in cmdLine.args.indecies:
  if labIndex >= len(cfg.labs):
    print("lab index %d is out of range" % labIndex)
    exit(-1)

# run list of labs in sequence given on command line
for labIndex in cmdLine.args.indecies:
  lab = Lab(cfg, cmdLine, labIndex)

  students = []
  student2file = {}

  # get student handin files, the last submission for each student,
  # and make a map from email to useful attrbutes

  # if the handin dir also has the output files from the past, use them
  # as baseline.  A crude test is to see if the number of output files is
  # close to the number of handin files (within 10% difference).
  nOutputFiles = len(glob.glob(lab.handinOutputFileQuery))
  nHandinFiles = len(glob.glob(lab.handinFileQuery))
  checkHandinOutput = True if abs(nOutputFiles / float(nHandinFiles) - 1.0) < 0.1 else False

  for file in sorted(glob.glob(lab.handinFileQuery)):
    baseName = file.split("/").pop()
    matchObj = re.match(r'(.*)_([0-9]+)_(.*)', baseName, re.M|re.I)
    email = matchObj.group(1)
    versionStr = matchObj.group(2)
    version = int(versionStr)
    
    withoutSuffix = baseName.replace(lab.handinSuffix, "")
    outputFile = withoutSuffix + "_" + lab.name + ".txt"
    jobName = lab.courseLab + "_" + withoutSuffix

    handinOutput = None
    passed = None
    if checkHandinOutput:
      handinOutput = lab.handinDir + "/" + email + "_" + versionStr + lab.handinOutputFileSuffix
      if os.path.isfile(handinOutput):
        passed = True if util.outputOK(handinOutput) else False
      else:
        handinOutput = None

    # add newly seen student
    if email not in students:
      students.append(email)

    # if previous output is available, only use the submission that has matching output
    if checkHandinOutput:
      if email not in student2file or \
         (version > student2file[email]["version"] and \
          (handinOutput and student2file[email]["existingOutput"]) or
          (not handinOutput and not student2file[email]["existingOutput"])) or \
         (not student2file[email]["existingOutput"] and handinOutput):
        studentFile = {"result": passed, "existingOutput": handinOutput,  # previous outcome
                       "version": version, "full": file, "base": baseName, "job": jobName,
                       "stripped": matchObj.group(3), "output": outputFile}
        student2file[email] = studentFile
    elif email not in student2file or version > student2file[email]["version"]:
      studentFile = {"version": version, "full": file, "base": baseName, "job": jobName,
                     "stripped": matchObj.group(3), "output": outputFile}
      student2file[email] = studentFile
  # end of for loop in handin files

  # report pre-existing failures and missing output files
  knownFailures = []
  outcomeUnknown = []
  if checkHandinOutput:
    for student in students:
      if student2file[student]["result"] == None:
        outcomeUnknown.append(student)
      elif not student2file[student]["result"]:
        knownFailures.append(student)
    if knownFailures:
      print "#", len(knownFailures), "known failures"
      for student in knownFailures:
        print student, student2file[student]["existingOutput"]
    if outcomeUnknown:
      print "#", len(outcomeUnknownn), "students without existing output files"
      for student in outcomeUnknown:
        print student

  # print the students and the indices
  if cmdLine.args.list_students:
    i = 0
    print ("# %d student handin for lab %s from %s" %
           (len(student2file), lab.name, lab.handinFileQuery))
    for student in students:
      print i, student, student2file[student]
      i += 1
    exit()

  # submit all student works or a given range, or given student list,
  # or all failed students
  studentIndexList = []
  studentsToRun = []
  studentList = cmdLine.args.students

  firstStudentNum = cfg.firstStudentNum
  totalStudents = cfg.totalStudents

  # look for failures from output or from lab's handin (with "-H" option)
  if cmdLine.args.re_run or cmdLine.args.failures:
    studentList = util.getRerunList(cfg, lab)

  if studentList or cmdLine.args.re_run or cmdLine.args.failures:
    for studentToRun in studentList:
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

  # run students in a given order
  studentIndexList.sort()
  studentsToRun.sort()

  print ("# Found total %d student submissions for lab %s" % (len(students), lab.name))
  if cmdLine.args.failures:
    print ("# %d failed submissions for lab %s from %s" %
           (len(studentIndexList), lab.name, lab.outputFileQuery))
    for index in studentIndexList:
      print ("%3d: %s" % (index, students[index]))
    continue  # move onto next lab

  if cmdLine.args.verbose:
    print ("# Students submissions: %d" % len(studentIndexList))
    for index in studentIndexList:
      print ("%3d: %s" % (index, students[index]))
  else:
    print ("# Students to run: %d" % (len(studentIndexList)))

  if len(studentIndexList) == 0:
    print ("# No student submissions for lab %s" % lab.name)
    continue  # move onto next lab

  cmd.info()
  cmd.open(lab)

  # load lab files
  cmd.upload(lab, lab.makefile)
  cmd.upload(lab, lab.autogradeTar)

  # load and run student submission
  for i in studentIndexList:
    print ("\n# Submit %s for lab %s" % (students[i], lab.name))
    cmd.upload(lab, student2file[students[i]]["full"])
    cmd.addJob(lab, student2file[students[i]])
    outputFiles.append(lab.outputDir + "/" + student2file[students[i]]["output"])
# end of main loop "cmdLine.args.indecies"

if cmdLine.args.dry_run:
  print "\nDry run done"
  exit()

print("\nNow waiting for %d output files..." % len(outputFiles))
remainingFiles = list(outputFiles)
numberRemaining = len(remainingFiles)
loopDelay = 5
badOutputFiles = []
justFinishedFiles = []

while True and len(outputFiles) > 0:
  time.sleep(loopDelay)

  # if we check the output file for scores as soon as it shows up,
  # the file may not fulled copied.  So we check the files found in
  # the last round.
  for file in justFinishedFiles:
    if "\"scores\":" not in open(file).read():
      badOutputFiles.append(file)
      print("output missing scores: %s" % file)
    else:
      print("Output ready: %s" % file)

  justFinishedFiles = []
  for file in remainingFiles:
    if os.path.exists(file) and os.path.getmtime(file) > startTime:
      justFinishedFiles.append(file)
  remainingFiles = set(remainingFiles) - set(justFinishedFiles)
  nFinished = numberRemaining - len(remainingFiles)
  print("%d jobs finished in the last %d seconds" % (nFinished, loopDelay))
  print("%d unfinished out of %d" % (len(remainingFiles), len(outputFiles)))
  now = time.mktime(datetime.datetime.now().timetuple())
  print("elapsed time: %s\n" % (str(datetime.timedelta(seconds = now - startTime))))

  numberRemaining = len(remainingFiles)
  if numberRemaining == 0 and not justFinishedFiles:
    print "All output files are counted for :))"
    break

if badOutputFiles:
  # not all bad files are really bad because the file copying may not
  # be done when the error is reported, particularly if the file is long
  realBadFiles = []
  for f in badOutputFiles:
    if "\"scores\":" not in open(f).read():
      realBadFiles.append(f)

  print("Found %d bad output files" % len(realBadFiles))
  for f in realBadFiles:
    print("bad output: %s" % f)
