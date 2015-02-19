#!/usr/local/bin/python
#
#
# tango-rest.py - Command line client for the RESTful Tango.
#


import os, sys, time

sys.path.append('/usr/lib/python2.7/site-packages/')
sys.path.append('gen-py')
sys.path.append('/usr/share/Tango-prod/lib/requests-2.2.1/')

import argparse, requests, json, urllib

#
#
# Set up the command line parser
#
parser = argparse.ArgumentParser(description='')
parser.add_argument('-s', '--server', default='http://localhost',
		help='Tango server endpoint (default = http://localhost)')
parser.add_argument('-P','--port', default=8080, type=int,
		help='Tango server port number (default = 8080)')
parser.add_argument('-k', '--key',
		help='Key of client') 
parser.add_argument('-l', '--courselab',
		help='Lab of client')

parser.add_argument('-o', '--open', action='store_true',
		help='Opens directory for lab. Creates new one if it does not exist. Must specify key with -k and courselab with -l. (modify default host with --server)')
parser.add_argument('-u', '--upload', action='store_true',
		help='Uploads a file with given filename. Must be supplied with --filename.')
parser.add_argument('-a', '--addjob', action='store_true',
		help='Submit a job (modify defaults with --image, --infiles, --jobname, --maxsize, --timeout)')
parser.add_argument('-p', '--poll', action='store_true',
		help='Poll a given output file (output file name must be supplied with --outputFile)')
parser.add_argument('-i', '--info', action='store_true',
		help='Obtain basic stats about the service such as uptime, number of jobs, number of threads etc')
parser.add_argument('-j', '--jobs', action='store_true',
		help='Obtain information of live jobs (deadJobs == 0) or dead jobs (deadJobs == 1). Must specify --deadJobs.')
parser.add_argument('--pool', action='store_true', 
		help='Obtain information about a pool of VMs spawned from a specific image. Must specify --image.')
parser.add_argument('--prealloc', action='store_true',
		help='Create a pool of instances spawned from a specific image (change defaults with --image --num --vmms --cores --memory)')

parser.add_argument('--vmms', default='tashiSSH',
		help='Choose vmms between localSSH, ec2SSH, tashiSSH')
parser.add_argument('--image', default='rhel.img',
		help='VM image name (default "rhel.img")')
parser.add_argument('--infiles', default=[], nargs='*',
		help='Input files must be a list of maps with localFile and destFile, as follows:\n [{"localFile": <string>, "destFile": <string>}, ...]')
parser.add_argument('--maxsize', default=0, type=int,
		help='Max output filesize [KBytes] (default none)')
parser.add_argument('--timeout', default=0, type=int,
		help='Job timeout [secs] (default none)')
parser.add_argument('--filename',
		help='Name of file that is being uploaded')
parser.add_argument('--outputFile', default='result.out',
		help='Name of output file to copy output into')
parser.add_argument('--deadJobs', default=0, type=int,
		help='If deadJobs == 0, live jobs are obtained. If deadJobs == 1, dead jobs are obtained')
parser.add_argument('--num', default=2, type=int,
		help='Number of instances to preallocate')
parser.add_argument('--cores', default=1, type=int,
		help='Number of cores to allocate on machine')
parser.add_argument('--memory', default=512, type=int,
		help='Amount of memory to allocate on machine')
parser.add_argument('--jobname', default='test_job',
		help='Job name')
parser.add_argument('--notifyURL',
		help='Complete URL for Tango to give callback to once job is complete.')

def checkKey():
	if (args.key is None):
		print "Failed to send request. Key must be specified with -k"
		sys.exit(0)

def checkCourselab():
	if (args.courselab is None):
		print "Failed to send request. Courselab must be specified with -l"
		sys.exit(0)

#
# Parse the command line arguments
#
args = parser.parse_args()
if (not args.open and not args.upload and not args.addjob
		and not args.poll and not args.info and not args.jobs
		and not args.pool and not args.prealloc):
	parser.print_help()
	sys.exit(0)

try:
	requests.get('%s:%d/' % (args.server, args.port))
except:
	print 'Tango not reachable on %s:%d!\n' % (args.server, args.port)
	sys.exit(0)

#
# Now make the requested HTTP call to the Tango server.
#

# open
if (args.open):
	try:
		checkKey()
		checkCourselab()
		response = requests.get('%s:%d/open/%s/%s/' % (args.server, args.port, args.key, args.courselab)) 
		print (response.content)

	except Exception as err:
		print "Failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

# upload
if (args.upload):
	try:
		checkKey()
		checkCourselab()

		if (args.filename is None):
			print "Must supply file to upload with --filename"
			sys.exit(0)

		f = open(args.filename)
		dirs = args.filename.split("/")
		filename = dirs[len(dirs)-1]
		header = {'Filename': filename}
		response = requests.post('%s:%d/upload/%s/%s/' % (args.server, args.port, args.key, args.courselab), data = f.read(), headers=header)
		f.close()
		print (response.content)

	except Exception as err:
		print "failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

# addJob
if (args.addjob):
	try:
		checkKey()
		checkCourselab()
		requestObj = {}
		requestObj['image'] = args.image
		requestObj['files'] = args.infiles
		requestObj['timeout'] = args.timeout
		requestObj['max_kb'] = args.maxsize
		requestObj['output_file'] = args.outputFile
		requestObj['jobName'] = args.jobname
		if (args.notifyURL):
			requestObj['notifyURL'] = args.notifyURL
		print "Adding job"
		for key in requestObj:
			print "%s: %s" % (key, requestObj[key])

		response = requests.post('%s:%d/addJob/%s/%s/' % (args.server, args.port, args.key, args.courselab), data = json.dumps(requestObj))
		print (response.content)

	except Exception as err:
		print "Failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

# poll
if (args.poll):
	try:
		checkKey()
		checkCourselab()
		if (args.outputFile is None):
			print "Must supply name of output file with --outputFile"
			sys.exit(0)

		response = requests.get('%s:%d/poll/%s/%s/%s/' % (args.server, args.port, args.key, args.courselab, urllib.quote(args.outputFile)))
		print (response.content)

	except Exception as err:
		print "Failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

# info
if (args.info):
	try:
		checkKey()
		response = requests.get('%s:%d/info/%s/' % (args.server, args.port, args.key))
		print (response.content)

	except Exception as err:
		print "Failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

# jobs
if (args.jobs):
	try:
		checkKey()
		response = requests.get('%s:%d/jobs/%s/%d/' % (args.server, args.port, args.key, args.deadJobs))
		print (response.content)

	except Exception as err:
		print "Failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

# pool
if (args.pool):
	try:
		checkKey()
		response = requests.get('%s:%d/pool/%s/%s/' % (args.server, args.port, args.key, args.image))
		print (response.content)

	except Exception as err:
		print "Failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

# prealloc
if (args.prealloc):
	try:
		checkKey()
		vmObj = {}
		vmObj['vmms'] = args.vmms
		vmObj['cores'] = args.cores
		vmObj['memory'] = args.memory
		print "Preallocating"
		print "name: %s" % args.image
		print "num: %d" % args.num
		for key in vmObj:
			print "%s: %s" % (key, vmObj[key])
		response = requests.post('%s:%d/prealloc/%s/%s/%s/' % (args.server, args.port, args.key, args.image, args.num), data=json.dumps(vmObj))
		print (response.content)

	except Exception as err:
		print "Failed to send request to %s:%d" % (args.server, args.port)
		print ("\t" + str(err))
		sys.exit(0)

