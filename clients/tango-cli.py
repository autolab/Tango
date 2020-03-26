#!/usr/local/bin/python
#
#
# tango-cli.py - Command line client for the RESTful Tango.
#

from __future__ import print_function
from builtins import range
from future import standard_library
standard_library.install_aliases()
from builtins import map
from builtins import str
import os
import sys

sys.path.append('/usr/lib/python2.7/site-packages/')

import argparse
import requests
import json
import urllib.request, urllib.parse, urllib.error

#
#
# Set up the command line parser
#
parser = argparse.ArgumentParser(description='')
parser.add_argument('-s', '--server', default='localhost',
                    help='Tango server endpoint (default = http://localhost)')
parser.add_argument('-P', '--port', default=3000, type=int,
                    help='Tango server port number (default = 3000)')
parser.add_argument('-k', '--key',
                    help='Key of client')
parser.add_argument('-l', '--courselab',
                    help='Lab of client')

open_help = 'Opens directory for lab. Creates new one if it does not exist. Must specify key with -k and courselab with -l.'
parser.add_argument('-o', '--open', action='store_true', help=open_help)
upload_help = 'Uploads a file. Must specify key with -k, courselab with -l, and filename with --filename.'
parser.add_argument('-u', '--upload', action='store_true', help=upload_help)
addJob_help = 'Submit a job. Must specify key with -k, courselab with -l, and input files with --infiles. Modify defaults with --image (autograding_image), --outputFile (result.out), --jobname (test_job), --maxsize(0), --timeout (0).'
parser.add_argument('-a', '--addJob', action='store_true', help=addJob_help)
poll_help = 'Poll a given output file. Must specify key with -k, courselab with -l. Modify defaults with --outputFile (result.out).'
parser.add_argument('-p', '--poll', action='store_true', help=poll_help)
info_help = 'Obtain basic stats about the service such as uptime, number of jobs, number of threads etc. Must specify key with -k.'
parser.add_argument('-i', '--info', action='store_true', help=info_help)
jobs_help = 'Obtain information of live jobs (deadJobs == 0) or dead jobs (deadJobs == 1). Must specify key with -k. Modify defaults with --deadJobs (0).'
parser.add_argument('-j', '--jobs', action='store_true', help=jobs_help)
pool_help = 'Obtain information about a pool of VMs spawned from a specific image. Must specify key with -k. Modify defaults with --image (autograding_image).'
parser.add_argument('--pool', action='store_true', help=pool_help)
prealloc_help = 'Create a pool of instances spawned from a specific image. Must specify key with -k. Modify defaults with --image (autograding_image), --num (2), --vmms (localDocker), --cores (1), and --memory (512).'
parser.add_argument('--prealloc', action='store_true', help=prealloc_help)

parser.add_argument('--runJob', help='Run a job from a specific directory')
parser.add_argument(
    '--numJobs', type=int, default=1, help='Number of jobs to run')

parser.add_argument('--vmms', default='localDocker',
                    help='Choose vmms between ec2SSH, tashiSSH, localDocker, and distDocker')
parser.add_argument('--image', default='',
                    help='VM image name (default "autograding_image")')
parser.add_argument(
    '--infiles',
    nargs='+',
    type=json.loads,
    help='Input files must be a list of maps with localFile and destFile, as follows:\n \'{"localFile": "<string>", "destFile": "<string>"}\', \'{"localFile" : "<string>", "destFile" : "<string>"}\'')
parser.add_argument('--maxsize', default=0, type=int,
                    help='Max output filesize [KBytes] (default none)')
parser.add_argument('--timeout', default=0, type=int,
                    help='Job timeout [secs] (default none)')
parser.add_argument('--filename',
                    help='Name of file that is being uploaded')
parser.add_argument('--outputFile', default='result.out',
                    help='Name of output file to copy output into')
parser.add_argument(
    '--deadJobs',
    default=0,
    type=int,
    help='If deadJobs == 0, live jobs are obtained. If deadJobs == 1, dead jobs are obtained')
parser.add_argument('--num', default=2, type=int,
                    help='Number of instances to preallocate')
parser.add_argument('--cores', default=1, type=int,
                    help='Number of cores to allocate on machine')
parser.add_argument('--memory', default=512, type=int,
                    help='Amount of memory to allocate on machine')
parser.add_argument('--jobname', default='test_job',
                    help='Job name')
parser.add_argument(
    '--notifyURL',
    help='Complete URL for Tango to give callback to once job is complete.')

# add for aws student accounts
parser.add_argument(
    '--accessKeyId', default='',
    help='AWS account access key ID')

parser.add_argument(
    '--accessKey', default='',
    help='AWS account access key content')


def checkKey():
    if (args.key is None):
        print("Key must be specified with -k")
        return -1
    return 0


def checkCourselab():
    if (args.courselab is None):
        print("Courselab must be specified with -l")
        return -1
    return 0


def checkFilename():
    if (args.filename is None):
        print("Filename must be specified with --filename")
        return -1
    return 0


def checkInfiles():
    if (args.infiles is None):
        print("Input files must be specified with --infiles")
        return -1
    return 0


def checkDeadjobs():
    if (args.deadJobs is None):
        print("Deadjobs must be specified with --deadJobs")
        return -1
    return 0

# open


def tango_open():
    try:
        res = checkKey() + checkCourselab()
        if res != 0:
            raise Exception("Invalid usage: [open] " + open_help)

        response = requests.get(
            'http://%s:%d/open/%s/%s/' %
            (args.server, args.port, args.key, args.courselab))
        print("Sent request to %s:%d/open/%s/%s/" % (args.server, args.port, args.key, args.courselab))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/open/%s/%s/" % (args.server, args.port, args.key, args.courselab))
        print (str(err))
        sys.exit(0)

# upload


def tango_upload():
    try:
        res = checkKey() + checkCourselab() + checkFilename()
        if res != 0:
            raise Exception("Invalid usage: [upload] " + upload_help)

        f = open(args.filename)
        dirs = args.filename.split("/")
        filename = dirs[len(dirs) - 1]
        header = {'Filename': filename}

        response = requests.post(
            'http://%s:%d/upload/%s/%s/' %
            (args.server,
             args.port,
             args.key,
             args.courselab),
            data=f.read(),
            headers=header)
        f.close()
        print("Sent request to %s:%d/upload/%s/%s/ filename=%s" % (args.server, args.port, args.key, args.courselab, args.filename))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/upload/%s/%s/ filename=%s" % (args.server, args.port, args.key, args.courselab, args.filename))
        print (str(err))
        sys.exit(0)

# addJob


def tango_addJob():
    try:
        requestObj = {}
        res = checkKey() + checkCourselab() + checkInfiles()
        if res != 0:
            raise Exception("Invalid usage: [addJob] " + addJob_help)

        requestObj['image'] = args.image
        requestObj['files'] = args.infiles
        requestObj['timeout'] = args.timeout
        requestObj['max_kb'] = args.maxsize
        requestObj['output_file'] = args.outputFile
        requestObj['jobName'] = args.jobname
        
        if (args.notifyURL):
            requestObj['notifyURL'] = args.notifyURL
        
        requestObj['accessKeyId'] = args.accessKeyId
        requestObj['accessKey'] = args.accessKey

        response = requests.post(
            'http://%s:%d/addJob/%s/%s/' %
            (args.server,
             args.port,
             args.key,
             args.courselab),
            data=json.dumps(requestObj))
        print("Sent request to %s:%d/addJob/%s/%s/ \t jobObj=%s" % (args.server, args.port, args.key, args.courselab, json.dumps(requestObj)))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/addJob/%s/%s/ \t jobObj=%s" % (args.server, args.port, args.key, args.courselab, json.dumps(requestObj)))
        print (str(err))
        sys.exit(0)

# poll


def tango_poll():
    try:
        res = checkKey() + checkCourselab()
        if res != 0:
            raise Exception("Invalid usage: [poll] " + poll_help)

        response = requests.get(
            'http://%s:%d/poll/%s/%s/%s/' %
            (args.server,
             args.port,
             args.key,
             args.courselab,
             urllib.parse.quote(
                 args.outputFile)))
        print("Sent request to %s:%d/poll/%s/%s/%s/" % (args.server, args.port, args.key, args.courselab, urllib.parse.quote(args.outputFile)))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/poll/%s/%s/%s/" % (args.server, args.port, args.key, args.courselab, urllib.parse.quote(args.outputFile)))
        print (str(err))
        sys.exit(0)

# info


def tango_info():
    try:
        res = checkKey()
        if res != 0:
            raise Exception("Invalid usage: [info] " + info_help)

        response = requests.get(
            'http://%s:%d/info/%s/' % (args.server, args.port, args.key))
        print("Sent request to %s:%d/info/%s/" % (args.server, args.port, args.key))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/info/%s/" % (args.server, args.port, args.key))
        print (str(err))
        sys.exit(0)

# jobs


def tango_jobs():
    try:
        res = checkKey() + checkDeadjobs()
        if res != 0:
            raise Exception("Invalid usage: [jobs] " + jobs_help)

        response = requests.get(
            'http://%s:%d/jobs/%s/%d/' %
            (args.server, args.port, args.key, args.deadJobs))
        print("Sent request to %s:%d/jobs/%s/%d/" % (args.server, args.port, args.key, args.deadJobs))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/jobs/%s/%d/" % (args.server, args.port, args.key, args.deadJobs))
        print (str(err))
        sys.exit(0)

# pool


def tango_pool():
    try:
        res = checkKey()
        if res != 0:
            raise Exception("Invalid usage: [pool] " + pool_help)

        response = requests.get('http://%s:%d/pool/%s/%s/' %
                                (args.server, args.port, args.key, args.image))
        print("Sent request to %s:%d/pool/%s/%s/" % (args.server, args.port, args.key, args.image))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/pool/%s/%s/" % (args.server, args.port, args.key, args.image))
        print (str(err))
        sys.exit(0)

# prealloc


def tango_prealloc():
    try:
        vmObj = {}
        res = checkKey()
        if res != 0:
            raise Exception("Invalid usage: [prealloc] " + prealloc_help)

        vmObj['vmms'] = args.vmms
        vmObj['cores'] = args.cores
        vmObj['memory'] = args.memory

        response = requests.post(
            'http://%s:%d/prealloc/%s/%s/%s/' %
            (args.server,
             args.port,
             args.key,
             args.image,
             args.num),
            data=json.dumps(vmObj))
        print("Sent request to %s:%d/prealloc/%s/%s/%s/ \t vmObj=%s" % (args.server, args.port, args.key, args.image, args.num, json.dumps(vmObj)))
        print(response.content)

    except Exception as err:
        print("Failed to send request to %s:%d/prealloc/%s/%s/%s/ \t vmObj=%s" % (args.server, args.port, args.key, args.image, args.num, json.dumps(vmObj)))
        print (str(err))
        sys.exit(0)


def file_to_dict(file):
    if "Makefile" in file:
        return {"localFile": file, "destFile": "Makefile"}
    elif "handin.tgz" in file:
        return {"localFile": file, "destFile": "handin.tgz"}
    else:
        return {"localFile": file, "destFile": file}

# runJob


def tango_runJob():
    if args.runJob is None:
        print("Invalid usage: [runJob]")
        sys.exit(0)

    dir = args.runJob
    infiles = [file for file in os.listdir(
        dir) if os.path.isfile(os.path.join(dir, file))]
    files = [os.path.join(dir, file) for file in infiles]
    args.infiles = list(map(file_to_dict, infiles))

    args.jobname += "-0"
    args.outputFile += "-0"
    for i in range(1, args.numJobs + 1):
        print("----------------------------------------- STARTING JOB " + str(i) + " -----------------------------------------")
        print("----------- OPEN")
        tango_open()
        print("----------- UPLOAD")
        for file in files:
            args.filename = file
            tango_upload()
        print("----------- ADDJOB")
        length = len(str(i - 1))
        args.jobname = args.jobname[:-length] + str(i)
        args.outputFile = args.outputFile[:-length] + str(i)
        tango_addJob()
        print("--------------------------------------------------------------------------------------------------\n")


def router():
    if (args.open):
        tango_open()
    elif (args.upload):
        tango_upload()
    elif (args.addJob):
        tango_addJob()
    elif (args.poll):
        tango_poll()
    elif (args.info):
        tango_info()
    elif (args.jobs):
        tango_jobs()
    elif (args.pool):
        tango_pool()
    elif (args.prealloc):
        tango_prealloc()
    elif (args.runJob):
        tango_runJob()

#
# Parse the command line arguments
#
args = parser.parse_args()
if (not args.open and not args.upload and not args.addJob
        and not args.poll and not args.info and not args.jobs
        and not args.pool and not args.prealloc and not args.runJob):
    parser.print_help()
    sys.exit(0)

try:
    response = requests.get('http://%s:%d/' % (args.server, args.port))
except:
    print('Tango not reachable on %s:%d!\n' % (args.server, args.port))
    sys.exit(0)

router()
