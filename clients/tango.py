#!/usr/bin/python

#
# tango.py - The Tango command line client
#


import os, sys, time

sys.path.append('/usr/lib/python2.7/site-packages/')
sys.path.append('gen-py')

import argparse
import thrift
from pythonThrift.tango import Tango
from pythonThrift.tango.ttypes import *
from thrift import Thrift
from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol

#
# Helper functions
#
def connect(port):
    """ connect - establishes a connection with the Tango server
    """
    transport = TSocket.TSocket('localhost', port)
    transport = TTransport.TBufferedTransport(transport)
    protocol = TBinaryProtocol.TBinaryProtocol(transport)
    client = Tango.Client(protocol)
    transport.open()
    return (transport, client)

#
# Set up the command line parser
#
parser = argparse.ArgumentParser(description='')
parser.add_argument('-p','--port', default=8080, type=int,
                    help='Tango server port number (default = 8080)')

parser.add_argument('-a', '--addjob', action='store_true',
                    help='Submit a job (modify defaults with --image, --infiles, --jobname, --makefile --image, --maxsize, --timeout)')
parser.add_argument('--vmms', default='ec2SSH',
                    help='Choose vmms between ec2SSH and tashiSSH')
parser.add_argument('--image', default='rhel',
                    help='VM image name (default "rhel")')
parser.add_argument('--infiles', default=['hello.sh'], nargs='*',
                    help='Input files (default "hello.sh")')
parser.add_argument('--jobname', default='job1',
                    help='Job directory (default "job1")')
parser.add_argument('--makefile', default='autograde-Makefile',
                    help='Makefile name (default "autograde-Makefile")')
parser.add_argument('--maxsize', default=0, type=int,
                    help='Max output filesize [KBytes] (default none)')
parser.add_argument('--timeout', default=0, type=int,
                    help='Job timeout [secs] (default none)')

parser.add_argument('-i','--info', action='store_true',
                    help='Display Tango backend info')
parser.add_argument('-j','--jobs', action='store_true',
                    help='Display active jobs')
parser.add_argument('-d', '--deadjobs', action='store_true',
                    help='Display dead jobs')

parser.add_argument('--pool', action='store_true',
                    help='Display VM pool (modify default with --image)')

parser.add_argument('--prealloc', action='store_true',
                    help='Preallocate VM pool (modify defaults with --cores, --image, --memory, --num)')
parser.add_argument('--cores', default=1, type=int,
                    help='Cores per VM (default 1)')
parser.add_argument('--memory', default=512, type=int,
                    help='Memory size (Kytes) of VM (default 512)')
parser.add_argument('--num', default=2, type=int,
                    help='Number of VMs to preallocate (default 2)')

parser.add_argument('--deljob', action='store_true',
                    help='Remove job from queue (requires --jobid)')
parser.add_argument('--jobid', nargs='+', type=int,
                    help='List of job IDs')

#
# Parse the command line arguments
#
args = parser.parse_args()
if (not args.info and not args.jobs and not args.deadjobs
    and not args.pool and not args.prealloc and not args.addjob
    and not args.deljob):
    parser.print_help()
    sys.exit(0)

#
# Create the connection to the Tango server
#
try:
    transport, client = connect(args.port)
except:
    print 'Tango is not listening on port %d!\n' % args.port
    sys.exit(0)

####
# Now make the requested RPC call to the Tango server over the
# connection we just set up
#

#
# getInfo RPC
#
if (args.info):
    for item in client.getInfo():
        print item

#
# getJobs RPC (current)
#
if (args.jobs):
    active = client.getJobs(0)
    if len(active) > 0:
        for job in active:
            print job
if (args.deadjobs):
    dead = client.getJobs(-1)
    if len(dead) > 0:
        for job in dead:
            print job

#
# getPool RPC
#
if (args.pool):
    print client.getPool(args.image)

#
# preallocVM RPC
#
if (args.prealloc):
    vm = TangoMachine(
        name=args.image,
        vmms=args.vmms,
        image='%s.img' % (args.image),
        cores=args.cores,
        memory=args.memory,
        resume=0,
        disk=None,
        network=None)
    print vm
    print 'Requesting %d images' % args.num
    print client.preallocVM(vm, args.num)

#
# The workhorse addJob RPC
#
if (args.addjob):

    client_dir = os.getcwd()
    pid = os.getpid()
    outputFile = '%s/%s-%d.out' % (client_dir, args.jobname, pid)

    # Print a brief summary for the user
    print 'jobDir: %s' % (args.jobname)
    print 'makeFile: %s/%s/%s' % (client_dir, args.jobname, args.makefile)
    print 'inputFiles: %s/%s/%s' % (client_dir, args.jobname, args.infiles)
    print 'outputFile: %s' % (outputFile)

    #
    # Construct the job hash that will be passed as an argument
    #
    job = TangoJob()

    # Basic arguments
    job.name = args.jobname
    job.outputFile = outputFile
    job.timeout = args.timeout
    job.maxOutputFileSize = args.maxsize


    # List of input files
    job.input = []
    makefile = InputFile(
        localFile = '%s/%s/%s' % (client_dir, args.jobname, args.makefile),
        destFile = 'Makefile')
    job.input.append(makefile)

    for file in args.infiles:
        handinfile = InputFile(
            localFile = "%s/%s/%s" % (client_dir, args.jobname, file),
            destFile = file)
        job.input.append(handinfile)

    # Virtual machine
    vm = TangoMachine(
        name = args.image,
        vmms = 'tashiSSH', # hardcoded for now
        image = '%s.img' % (args.image),
        cores = args.cores,
        memory = args.memory,
        disk = None,
        network = None)
    job.vm = vm

    # The actual RPC
    print "jobID: %s" % (client.addJob(job))

#
# delJob RPC
#
if args.deljob:
    if args.jobid == None:
        print 'Error: must supply a job id to --deljob'
        sys.exit(0)

    for id in args.jobid:
        print 'deleting job %d from job queue' % (id)
        print client.delJob(id, 0)

#
# Close the connection to the server before exiting
#
transport.close()

