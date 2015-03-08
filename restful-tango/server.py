from flask import Flask
from flask import request

app = Flask(__name__)

import sys, time, urllib
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps

import tangoREST
from config import Config

tangoREST = tangoREST.TangoREST()
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Regex for the resources
SHA1_KEY = ".+" # So that we can have better error messages
COURSELAB = ".+"
OUTPUTFILE = ".+"
IMAGE = ".+"
NUM = "[0-9]+"
JOBID = "[0-9]+"
DEADJOBS=".+"


@app.route('/')
def MainHandler():
    """ get - Default route to check if RESTful Tango is up."""
    return ("Hello, world! RESTful Tango here!\n")


@app.route('/open/<key>/<courselab>/')
def OpenHandler(key, courselab):
    """ get - Handles the get request to open."""
    return tangoREST.open(key, courselab)


@app.route('/upload/<key>/<courselab>/', methods=['POST'])
def UploadHandler(key, courselab):
    """ post - Handles the post request to upload."""
    return tangoREST.upload(key, courselab, self.request.headers['Filename'], self.request.body)


@app.route('/addJob/<key>/<courselab>/', methods=['POST'])
def AddJobHandler(key, courselab):
    """ post - Handles the post request to add a job."""
    return tangoREST.addJob(key, courselab, self.request.body)


@app.route('/poll/<key>/<courselab>/<outputFile>/')
def PollHandler(key, courselab, outputFile):
    """ get - Handles the get request to poll."""
    self.set_header('Content-Type', 'application/octet-stream')
    return tangoREST.poll(key, courselab, urllib.unquote(outputFile))


@app.route('/info/<key>/')
def InfoHandler(key):
    """ get - Handles the get request to info."""
    return tangoREST.info(key)


@app.route('/jobs/<key>/<int:deadJobs>/')
def JobsHandler(key, deadJobs):
    """ get - Handles the get request to jobs."""
    return tangoREST.jobs(key, deadJobs)


@app.route('/pool/<key>/<image>/')
def PoolHandler(key, image):
    """ get - Handles the get request to pool."""
    return tangoREST.pool(key, image)


@app.route('/prealloc/<key>/<image>/<num>/', methods=['POST'])
def PreallocHandler(key, image, num):
    """ post - Handles the post request to prealloc."""
    return tangoREST.prealloc(key, image, num, self.request.body)



if __name__ == "__main__":

	port = Config.PORT
	if len(sys.argv) > 0:
		port = int(sys.argv[1])

	tangoREST.resetTango()
    app.run(port=port, debug=True)

	print("Starting the RESTful Tango server on port %d..." % (port))
