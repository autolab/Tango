#!/usr/local/bin/python

from tornado.ioloop import IOLoop
import tornado.web
import sys, time
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps

import tangoREST
from config import Config

tangoREST = tangoREST.TangoREST()
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Regex for the resources
SHA1_KEY = ".+" # So that we can have better error messages
COURSELAB = ".+"
OUTPUTFILE = "[0-9a-zA-z\.\-\_]+"
IMAGE = ".+"
NUM = "[0-9]+"
JOBID = "[0-9]+"
DEADJOBS=".+"

def unblock(f):
	@tornado.web.asynchronous
	@wraps(f)
	def wrapper(*args, **kwargs):
		self = args[0]

		def callback(future):
			self.write(future.result())
			self.finish()

		EXECUTOR.submit(
			partial(f, *args, **kwargs)
		).add_done_callback(
			lambda future: 
			tornado.ioloop.IOLoop.instance().add_callback(
				partial(callback, future)
			)
		)

	return wrapper

class MainHandler(tornado.web.RequestHandler):
	@unblock
	def get(self):
		""" get - Default route to check if RESTful Tango is up."""
		return ("Hello, world! RESTful Tango here!\n")

class OpenHandler(tornado.web.RequestHandler):
	@unblock
	def get(self, key, courselab):
		""" get - Handles the get request to open."""
		return tangoREST.open(key, courselab)

class UploadHandler(tornado.web.RequestHandler):
	@unblock
	def post(self, key, courselab):
		""" post - Handles the post request to upload."""
		return tangoREST.upload(key, courselab, self.request.headers['Filename'], self.request.body)

class AddJobHandler(tornado.web.RequestHandler):
	@unblock
	def post(self, key, courselab):
		""" post - Handles the post request to add a job."""
		return tangoREST.addJob(key, courselab, self.request.body)

class PollHandler(tornado.web.RequestHandler):
	@unblock
	def get(self, key, courselab, outputFile):
		""" get - Handles the get request to poll."""
		self.set_header('Content-Type', 'application/octet-stream')
		return tangoREST.poll(key, courselab, outputFile)

class InfoHandler(tornado.web.RequestHandler):
	@unblock
	def get(self, key):
		""" get - Handles the get request to info."""
		return tangoREST.info(key)

class JobsHandler(tornado.web.RequestHandler):
	@unblock
	def get(self, key, deadJobs):
		""" get - Handles the get request to jobs."""
		return tangoREST.jobs(key, deadJobs)

class PoolHandler(tornado.web.RequestHandler):
	@unblock
	def get(self, key, image):
		""" get - Handles the get request to pool."""
		return tangoREST.pool(key, image)

class PreallocHandler(tornado.web.RequestHandler):
	@unblock
	def post(self, key, image, num):
		""" post - Handles the post request to prealloc."""
		return tangoREST.prealloc(key, image, num, self.request.body)

# Routes
application = tornado.web.Application([
	(r"/", MainHandler),
	(r"/open/(%s)/(%s)/" % (SHA1_KEY, COURSELAB), OpenHandler),
	(r"/upload/(%s)/(%s)/" % (SHA1_KEY, COURSELAB), UploadHandler),
	(r"/addJob/(%s)/(%s)/" % (SHA1_KEY, COURSELAB), AddJobHandler),
	(r"/poll/(%s)/(%s)/(%s)/" % (SHA1_KEY, COURSELAB, OUTPUTFILE), PollHandler),
	(r"/info/(%s)/" % (SHA1_KEY), InfoHandler),
	(r"/jobs/(%s)/(%s)/" % (SHA1_KEY, DEADJOBS), JobsHandler),
	(r"/pool/(%s)/(%s)/" % (SHA1_KEY, IMAGE), PoolHandler),
	(r"/prealloc/(%s)/(%s)/(%s)/" % (SHA1_KEY, IMAGE, NUM), PreallocHandler),
	])

if __name__ == "__main__":
	port = Config.PORT
	tangoREST.resetTango()
	print("Starting the RESTful Tango server on port %d..." % (port))
	application.listen(port)
	tornado.ioloop.IOLoop.instance().start() 
