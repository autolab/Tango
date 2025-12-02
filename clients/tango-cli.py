#!/usr/bin/env python3
#
#
# tango-cli.py - Command line client for the RESTful Tango.
#

import urllib.error
import urllib.parse
import urllib.request
import json
import requests
import argparse
import sys
import os
from dataclasses import dataclass, asdict
from typing import Optional

sys.path.append("/usr/lib/python2.7/site-packages/")


def get_arg(name, default=None):
    """Helper function to safely get arguments using dictionary .get() method"""
    return vars(args).get(name, default)


@dataclass
class RequestObj:
    """Dataclass for job request objects"""
    image: str
    files: str
    timeout: int
    max_kb: int
    output_file: str
    jobName: str
    accessKeyId: str
    accessKey: str
    disable_network: bool
    instanceType: str
    stopBefore: str
    notifyURL: Optional[str] = None
    callback_url: Optional[str] = None


@dataclass
class VmObj:
    """Dataclass for VM allocation objects"""
    vmms: str
    cores: int
    memory: int


#
#
# Set up the command line parser
#
parser = argparse.ArgumentParser(description="")
parser.add_argument(
    "-s",
    "--server",
    default="localhost",
    help="Tango server endpoint (default = localhost)",
)
parser.add_argument(
    "-P",
    "--port",
    default=3000,
    type=int,
    help="Tango server port number (default = 3000)",
)
parser.add_argument(
    "-S",
    "--ssl",
    default=False,
    action="store_true",
    help="Use ssl to communicate with tango (and change port to 443)",
)
parser.add_argument("-k", "--key", help="Key of client")
parser.add_argument("-l", "--courselab", help="Lab of client")

open_help = "Opens directory for lab. Creates new one if it does not exist. Must specify key with -k and courselab with -l."
parser.add_argument("-o", "--open", action="store_true", help=open_help)
upload_help = "Uploads a file. Must specify key with -k, courselab with -l, and filename with --filename."
parser.add_argument("-u", "--upload", action="store_true", help=upload_help)
addJob_help = "Submit a job. Must specify key with -k, courselab with -l, and input files with --infiles. Modify defaults with --image (autograding_image), --outputFile (result.out), --jobname (test_job), --maxsize(0), --timeout (0)."
parser.add_argument("-a", "--addJob", action="store_true", help=addJob_help)
poll_help = "Poll a given output file. Must specify key with -k, courselab with -l. Modify defaults with --outputFile (result.out)."
parser.add_argument("-p", "--poll", action="store_true", help=poll_help)
info_help = "Obtain basic stats about the service such as uptime, number of jobs, number of threads etc. Must specify key with -k."
parser.add_argument("-i", "--info", action="store_true", help=info_help)
jobs_help = "Obtain information of live jobs (deadJobs == 0) or dead jobs (deadJobs == 1). Must specify key with -k. Modify defaults with --deadJobs (0)."
parser.add_argument("-j", "--jobs", action="store_true", help=jobs_help)
pool_help = "Obtain information about a pool of VMs spawned from a specific image. Must specify key with -k. Modify defaults with --image (autograding_image)."
parser.add_argument("--pool", action="store_true", help=pool_help)
prealloc_help = "Create a pool of instances spawned from a specific image. Must specify key with -k. Modify defaults with --image (autograding_image), --num (2), --vmms (localDocker), --cores (1), and --memory (512)."
parser.add_argument("--prealloc", action="store_true", help=prealloc_help)
build_help = "Build a docker image. Must specify key with -k, image filename with --filename, and image name with --imageName."
parser.add_argument("--build", action="store_true", help=build_help)

parser.add_argument(
    "--getPartialOutput", action="store_true", help="Get partial output"
)
parser.add_argument("--jobid", help="Job ID")

parser.add_argument("--runJob", help="Run a job from a specific directory")
parser.add_argument("--numJobs", type=int, default=1, help="Number of jobs to run")

parser.add_argument(
    "--image", default="", help='VM image name (default "autograding_image")'
)
parser.add_argument("--imageName", help="Name for new VM image to be built")
parser.add_argument(
    "--infiles",
    nargs="+",
    type=json.loads,
    help='Input files must be a list of maps with localFile and destFile, as follows:\n \'{"localFile": "<string>", "destFile": "<string>"}\', \'{"localFile" : "<string>", "destFile" : "<string>"}\'',
)
parser.add_argument(
    "--maxsize", default=0, type=int, help="Max output filesize [KBytes] (default none)"
)
parser.add_argument(
    "--timeout", default=0, type=int, help="Job timeout [secs] (default none)"
)
parser.add_argument("--filename", help="Name of file that is being uploaded")
parser.add_argument(
    "--outputFile", default="result.out", help="Name of output file to copy output into"
)
parser.add_argument(
    "--deadJobs",
    default=0,
    type=int,
    help="If deadJobs == 0, live jobs are obtained. If deadJobs == 1, dead jobs are obtained",
)
parser.add_argument(
    "--num", default=2, type=int, help="Number of instances to preallocate"
)
parser.add_argument(
    "--cores", default=1, type=int, help="Number of cores to allocate on machine"
)
parser.add_argument(
    "--memory", default=512, type=int, help="Amount of memory to allocate on machine"
)
parser.add_argument("--jobname", default="test_job", help="Job name")
parser.add_argument(
    "--notifyURL",
    help="Complete URL for Tango to give callback to once job is complete.",
)
parser.add_argument(
    "--callbackURL",
    help="Complete URL for Tango to give callback to once job is complete.",
)
parser.add_argument(
    "--disableNetwork",
    action="store_true",
    default=False,
    help="Disable network access for autograding containers.",
)

# add for aws student accounts
parser.add_argument("--accessKeyId", default="", help="AWS account access key ID")
parser.add_argument("--accessKey", default="", help="AWS account access key content")
parser.add_argument("--instanceType", default="", help="AWS EC2 instance type")
parser.add_argument("--stopBefore", default="", help="Stops the worker before a function is executed")

def checkKey():
    if get_arg('key') is None:
        print("Key must be specified with -k")
        return -1
    return 0


def checkCourselab():
    if get_arg('courselab') is None:
        print("Courselab must be specified with -l")
        return -1
    return 0


def checkFilename():
    if get_arg('filename') is None:
        print("Filename must be specified with --filename")
        return -1
    return 0


def checkInfiles():
    if get_arg('infiles') is None:
        print("Input files must be specified with --infiles")
        return -1
    return 0


def checkDeadjobs():
    if get_arg('deadJobs') is None:
        print("Deadjobs must be specified with --deadJobs")
        return -1
    return 0


def checkImageName():
    if get_arg('imageName') is None:
        print("Image name must be specified with --imageName")
        return -1
    return 0


_tango_protocol = "http"

# open


def tango_open():
    try:
        res = checkKey() + checkCourselab()
        if res != 0:
            raise Exception("Invalid usage: [open] " + open_help)

        response = requests.get(
            "%s://%s:%d/open/%s/%s/"
            % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab'))
        )
        print(
            "Sent request to %s:%d/open/%s/%s/"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab'))
        )
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/open/%s/%s/"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab'))
        )
        print(str(err))
        sys.exit(0)


# upload


def tango_upload():
    try:
        res = checkKey() + checkCourselab() + checkFilename()
        if res != 0:
            raise Exception("Invalid usage: [upload] " + upload_help)

        dirs = get_arg('filename').split("/")
        filename = dirs[len(dirs) - 1]
        header = {"Filename": filename}

        f = open(get_arg('filename'), 'rb')
        response = requests.post(
            "%s://%s:%d/upload/%s/%s/"
            % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab')),
            data=f.read(),
            headers=header,
        )
        f.close()
        print(
            "Sent request to %s:%d/upload/%s/%s/ filename=%s"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab'), get_arg('filename'))
        )
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/upload/%s/%s/ filename=%s"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab'), get_arg('filename'))
        )
        print(str(err))
        sys.exit(0)


# addJob


def tango_addJob():
    try:
        requestObj = {}
        res = checkKey() + checkCourselab() + checkInfiles()
        if res != 0:
            raise Exception("Invalid usage: [addJob] " + addJob_help)

        requestObj = RequestObj(
            image=get_arg('image'),
            files=get_arg('infiles'),
            timeout=get_arg('timeout'),
            max_kb=get_arg('maxsize'),
            output_file=get_arg('outputFile'),
            jobName=get_arg('jobname'),
            accessKeyId=get_arg('accessKeyId'),
            accessKey=get_arg('accessKey'),
            disable_network=get_arg('disableNetwork'),
            instanceType=get_arg('instanceType'),
            stopBefore=get_arg('stopBefore'),
            notifyURL=get_arg('notifyURL'),
            callback_url=get_arg('callbackURL'),
        )

        response = requests.post(
            "%s://%s:%d/addJob/%s/%s/"
            % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab')),
            data=json.dumps(asdict(requestObj)),
        )
        print(
            "Sent request to %s:%d/addJob/%s/%s/ \t jobObj=%s"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab'), json.dumps(asdict(requestObj)))
        )
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/addJob/%s/%s/ \t jobObj=%s"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('courselab'), json.dumps(asdict(requestObj)) if 'requestObj' in locals() else 'N/A')
        )
        print(str(err))
        sys.exit(0)


# getPartialOutput


def tango_getPartialOutput():
    try:
        response = requests.get(
            "%s://%s:%d/getPartialOutput/%s/%s/"
            % (
                _tango_protocol,
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('jobid'),
            )
        )
        print(
            "Sent request to %s:%d/getPartialOutput/%s/%s/"
            % (
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('jobid'),
            )
        )
        print(response.text)
    except Exception as err:
        print(
            "Failed to send request to %s:%d/getPartialOutput/%s/%s/"
            % (
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('jobid'),
            )
        )
        print(str(err))
        sys.exit(0)


# poll


def tango_poll():
    try:
        res = checkKey() + checkCourselab()
        if res != 0:
            raise Exception("Invalid usage: [poll] " + poll_help)

        response = requests.get(
            "%s://%s:%d/poll/%s/%s/%s/"
            % (
                _tango_protocol,
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('courselab'),
                urllib.parse.quote(get_arg('outputFile')),
            )
        )
        print(
            "Sent request to %s:%d/poll/%s/%s/%s/"
            % (
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('courselab'),
                urllib.parse.quote(get_arg('outputFile')),
            )
        )
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/poll/%s/%s/%s/"
            % (
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('courselab'),
                urllib.parse.quote(get_arg('outputFile')),
            )
        )
        print(str(err))
        sys.exit(0)


# info


def tango_info():
    try:
        res = checkKey()
        if res != 0:
            raise Exception("Invalid usage: [info] " + info_help)

        response = requests.get(
            "%s://%s:%d/info/%s/" % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key'))
        )
        print("Sent request to %s:%d/info/%s/" % (get_arg('server'), get_arg('port'), get_arg('key')))
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/info/%s/"
            % (get_arg('server'), get_arg('port'), get_arg('key'))
        )
        print(str(err))
        sys.exit(0)


# jobs


def tango_jobs():
    try:
        res = checkKey() + checkDeadjobs()
        if res != 0:
            raise Exception("Invalid usage: [jobs] " + jobs_help)

        response = requests.get(
            "%s://%s:%d/jobs/%s/%d/"
            % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key'), get_arg('deadJobs'))
        )
        print(
            "Sent request to %s:%d/jobs/%s/%d/"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('deadJobs'))
        )
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/jobs/%s/%d/"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('deadJobs'))
        )
        print(str(err))
        sys.exit(0)


# pool


def tango_pool():
    try:
        res = checkKey()
        if res != 0:
            raise Exception("Invalid usage: [pool] " + pool_help)

        response = requests.get(
            "%s://%s:%d/pool/%s/%s/"
            % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key'), get_arg('image'))
        )
        print(
            "Sent request to %s:%d/pool/%s/%s/"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('image'))
        )
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/pool/%s/%s/"
            % (get_arg('server'), get_arg('port'), get_arg('key'), get_arg('image'))
        )
        print(str(err))
        sys.exit(0)


# prealloc


def tango_prealloc():
    try:
        vmObj = {}
        res = checkKey()
        if res != 0:
            raise Exception("Invalid usage: [prealloc] " + prealloc_help)

        vmObj["vmms"] = get_arg('vmms')
        vmObj["cores"] = get_arg('cores')
        vmObj["memory"] = get_arg('memory')

        response = requests.post(
            "%s://%s:%d/prealloc/%s/%s/%s/"
            % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key'), get_arg('image'), get_arg('num')),
            data=json.dumps(vmObj),
        )
        print(
            "Sent request to %s:%d/prealloc/%s/%s/%s/ \t vmObj=%s"
            % (
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('image'),
                get_arg('num'),
                json.dumps(vmObj),
            )
        )
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/prealloc/%s/%s/%s/ \t vmObj=%s"
            % (
                get_arg('server'),
                get_arg('port'),
                get_arg('key'),
                get_arg('image'),
                get_arg('num'),
                json.dumps(vmObj),
            )
        )
        print(str(err))
        sys.exit(0)


def file_to_dict(file):
    if "Makefile" in file:
        return {"localFile": file, "destFile": "Makefile"}
    elif "handin.tgz" in file:
        return {"localFile": file, "destFile": "handin.tgz"}
    else:
        return {"localFile": file, "destFile": file}


# build


def tango_build():
    try:
        res = checkKey() + checkFilename() + checkImageName()
        if res != 0:
            raise Exception("Invalid usage: [build] " + build_help)

        f = open(get_arg('filename'), "rb")
        header = {"imageName": get_arg('imageName')}
        response = requests.post(
            "%s://%s:%d/build/%s/"
            % (_tango_protocol, get_arg('server'), get_arg('port'), get_arg('key')),
            data=f.read(),
            headers=header,
        )
        print("Sent request to %s:%d/build/%s/" % (get_arg('server'), get_arg('port'), get_arg('key')))
        print(response.text)

    except Exception as err:
        print(
            "Failed to send request to %s:%d/build/%s/"
            % (get_arg('server'), get_arg('port'), get_arg('key'))
        )
        print(str(err))
        sys.exit(0)


# runJob


def tango_runJob():
    if get_arg('runJob') is None:
        print("Invalid usage: [runJob]")
        sys.exit(0)

    dir = get_arg('runJob')
    infiles = [
        file for file in os.listdir(dir) if os.path.isfile(os.path.join(dir, file))
    ]
    files = [os.path.join(dir, file) for file in infiles]
    args.infiles = list(map(file_to_dict, infiles))

    args.jobname += "-0"
    args.outputFile += "-0"
    for i in range(1, get_arg('numJobs') + 1):
        print(
            "----------------------------------------- STARTING JOB "
            + str(i)
            + " -----------------------------------------"
        )
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
        print(
            "--------------------------------------------------------------------------------------------------\n"
        )


def router():
    if get_arg('open'):
        tango_open()
    elif get_arg('upload'):
        tango_upload()
    elif get_arg('addJob'):
        tango_addJob()
    elif get_arg('poll'):
        tango_poll()
    elif get_arg('info'):
        tango_info()
    elif get_arg('jobs'):
        tango_jobs()
    elif get_arg('pool'):
        tango_pool()
    elif get_arg('prealloc'):
        tango_prealloc()
    elif get_arg('runJob'):
        tango_runJob()
    elif get_arg('getPartialOutput'):
        tango_getPartialOutput()
    elif get_arg('build'):
        tango_build()


#
# Parse the command line arguments
#
args = parser.parse_args()
if (
    not get_arg('open')
    and not get_arg('upload')
    and not get_arg('addJob')
    and not get_arg('poll')
    and not get_arg('info')
    and not get_arg('jobs')
    and not get_arg('pool')
    and not get_arg('prealloc')
    and not get_arg('runJob')
    and not get_arg('getPartialOutput')
    and not get_arg('build')
):
    parser.print_help()
    sys.exit(0)

if get_arg('ssl'):
    _tango_protocol = "https"
    if get_arg('port') == 3000:
        args.port = 443


try:
    response = requests.get("%s://%s:%d/" % (_tango_protocol, get_arg('server'), get_arg('port')))
    response.raise_for_status()
except BaseException:
    print("Tango not reachable on %s:%d!\n" % (get_arg('server'), get_arg('port')))
    sys.exit(0)

router()
