import os, re, glob, datetime, time, json, string
from dateutil import parser
import smtplib
from email.mime.text import MIMEText

from config_for_run_jobs import Config
from util import Cmd
from util import CommandLine
from util import Lab
import util

# This script is run as a cron job every minute to detect potentially
# stuck jobs and send email to the administrator.
# It asks Tango for the live jobs.  Then it looks at the last-seen
# timestamp in each job's trace to determine if it's a "slow" job.
# It keeps the questionable jobs in a file so that they are not
# reported again by the next execution of this script.
# Potential false negative:  Suppose Tango dies and is restarted,
# then the jobIds stored in the "reported jobs" file from Tango's last
# incarnation may overlap with the current jobIds.  In such case,
# the overlapping jobIds will not be reported.  However, when Tango
# is stuck there usually will be more stuck jobs to be reported for
# the admin's attention.

cfg = Config()
cmd = Cmd(cfg, None)

REPORTED_JOBS_PATH = "/var/log/tango/lastSeenSlowJobsBy_check_jobs"

jsonResult = {}
reportedJobs = []  # trouble jobs found in last execution
troubleJobs = []  # trouble jobs found in this execution
writeFailure = ""
mailbodyP1 = ""
mailbodyP2 = ""

def sendmail():
    global mailbodyP1, mailbodyP2

    if not mailbodyP1 and not writeFailure:
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
                writeFailure + mailbodyP1 + mailbodyP2
                ), "\r\n")
    server = smtplib.SMTP(HOST)
    server.sendmail(FROM, ["czang@cmu.edu", "jboles@cmu.edu"], BODY)
    # server.sendmail(FROM, ["czang@cmu.edu"], BODY)
    server.quit()

def report(jobId, msg):
    global mailbodyP1, mailbodyP2
    email = ""

    # add into trouble list but may not report this time
    troubleJobs.append(jobId)
    if jobId in reportedJobs:
        return

    # go through the job list to find the job by jobId
    for job in jsonResult["jobs"]:
        if job["id"] != jobId: continue
        if not mailbodyP1:
            mailbodyP1 = "\nTrouble jobs:\n"
            mailbodyP2 = "\nJob details:\n"
        matchObj = re.match(r'(.*)_[0-9]+_(.*)', job["name"], re.M|re.I)
        email = matchObj.group(2)
        mailbodyP1 += "job %s, student %s: %s\n" % (jobId, email, msg)
        mailbodyP2 += json.dumps(job, indent=2, sort_keys=True)

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

# write troubled jobs found in this execution to file
try:
    with open(REPORTED_JOBS_PATH, 'w') as outfile:
        json.dump(troubleJobs, outfile)
except Exception as e:
    writeFailure = "Failed to write to %s: %s\n" % (REPORTED_JOBS_PATH, e)

# report trouble jobs AND maybe failure of writing to file
sendmail()

exit()

