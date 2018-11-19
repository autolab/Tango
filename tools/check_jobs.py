import os, re, glob, datetime, time, json, string
from dateutil import parser
import smtplib
from email.mime.text import MIMEText

from config_for_run_jobs import Config
from util import Cmd
from util import CommandLine
from util import Lab
import util

# Drive exiting student submissions to Tango.
# Find course/lab at specified location and submits work from the handin directory.
# Then wait for job output files.
#
# Use -h to show usage.
# See config_for_run_jobs.py for configuration options.

cfg = Config()
cmd = Cmd(cfg, None)

REPORTED_JOBS_PATH = "/var/run/tango/check_jobs.json"

jsonResult = {}
reportedJobs = []
mailbodyP1 = ""
mailbodyP2 = "\nDetails:\n"

def sendmail():
    global mailbodyP1, mailbodyP2

    if not mailbodyP1:
        print "No error to report @ %s" % datetime.datetime.now()
        return

    print "email report @ %s" % datetime.datetime.now()
    HOST = "smtp.pdl.local.cmu.edu"
    SUBJECT = "Autolab trouble @ %s" % datetime.datetime.now()
    FROM = "czang@cmu.edu"
    TO = "czang@cmu.edu"    
    BODY = string.join((
                "From: %s" % FROM,
                "To: %s" % TO,
                "Subject: %s" % SUBJECT ,
                "",
                mailbodyP1 + mailbodyP2
                ), "\r\n")
    server = smtplib.SMTP(HOST)
    server.sendmail(FROM, ["czang@cmu.edu", "jboles@cmu.edu"], BODY)
    # server.sendmail(FROM, ["czang@cmu.edu"], BODY)
    server.quit()

def report(jobId, msg):
    global mailbodyP1, mailbodyP2
    email = ""
    
    if jobId in reportedJobs:
        return

    reportedJobs.append(jobId)
    for job in jsonResult["jobs"]:    
        if job["id"] == jobId:
            mailbodyP2 += json.dumps(job, indent=2, sort_keys=True)
            matchObj = re.match(r'(.*)_[0-9]+_(.*)', job["name"], re.M|re.I)
            email = matchObj.group(2)
    mailbodyP1 += "job " + str(jobId) + ", student " + email + ": "  + msg + "\n"

# use a dump file for testing
if 0:
    with open('./testData') as jsonData:
        jsonResult = json.load(jsonData)

# read the jobs that have been reported
try:
    with open(REPORTED_JOBS_PATH) as jsonData:
        reportedJobs = json.load(jsonData)
except:
    reportedJobs = []
    
jsonResult = cmd.returnLiveJobs()  # comment out this line to use test data
    
for job in jsonResult["jobs"]:
    jobId = job["id"]
    if "trace" not in job:
        report(jobId, "Can't find trace for the job")
        continue

    lastLineOfTrace = job["trace"][-1]
    (timeStr, msg) = lastLineOfTrace.split("|")
    timestamp = parser.parse(timeStr)
    action = msg.split()[0]
    jobTimeout = job["timeout"]

    now = datetime.datetime.now()
    elapsed = (now - timestamp).total_seconds()
    if action == "running":
        if elapsed > (jobTimeout + 120):
            report(jobId, "Job should be timed out")
    elif elapsed > 120:
        report(jobId, "It's been too long since last trace")
# end of for loop

sendmail()
with open(REPORTED_JOBS_PATH, 'w') as outfile:
    json.dump(reportedJobs, outfile)

exit()

