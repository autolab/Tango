from future import standard_library
standard_library.install_aliases()
import tornado.web
import urllib.request, urllib.parse, urllib.error
import sys
import os
from tempfile import NamedTemporaryFile
import hashlib
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
import asyncio

import tangoREST
from config import Config

tangoREST = tangoREST.TangoREST()
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Regex for the resources
SHA1_KEY = ".+"  # So that we can have better error messages
COURSELAB = ".+"
OUTPUTFILE = ".+"
IMAGE = ".+"
NUM = "[0-9]+"
JOBID = "[0-9]+"
DEADJOBS = ".+"


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

@tornado.web.stream_request_body
class UploadHandler(tornado.web.RequestHandler):

    def prepare(self):
        """ set up the temporary file"""
        tempdir="%s/tmp" % (Config.COURSELABS,)
        if not os.path.exists(tempdir):
           os.mkdir(tempdir, 0o700)
        if os.path.exists(tempdir) and not os.path.isdir(tempdir):
           tangoREST.log("Cannot process uploads, %s is not a directory" % (tempdir,))
           return self.send_error()
        self.tempfile = NamedTemporaryFile(prefix='upload', dir=tempdir,
                                           delete=False)
        self.hasher = hashlib.md5()

    def data_received(self, chunk):
        self.hasher.update(chunk)
        self.tempfile.write(chunk)
        
    @unblock
    def post(self, key, courselab):
        """ post - Handles the post request to upload."""
        name = self.tempfile.name
        self.tempfile.close()
        return tangoREST.upload(
            key,
            courselab,
            self.request.headers['Filename'],
            name, self.hasher.hexdigest())

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
        return tangoREST.poll(key, courselab, urllib.parse.unquote(outputFile))


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
    def get(self, key):
        """ get - Handles the get request to pool."""
        image = ''
        if '/' in key:
            key_l = key.split('/')
            key = key_l[0]
            image = key_l[1]
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
    (r"/poll/(%s)/(%s)/(%s)/" %
     (SHA1_KEY, COURSELAB, OUTPUTFILE), PollHandler),
    (r"/info/(%s)/" % (SHA1_KEY), InfoHandler),
    (r"/jobs/(%s)/(%s)/" % (SHA1_KEY, DEADJOBS), JobsHandler),
    (r"/pool/(%s)/" % (SHA1_KEY), PoolHandler),
    (r"/prealloc/(%s)/(%s)/(%s)/" % (SHA1_KEY, IMAGE, NUM), PreallocHandler),
])


if __name__ == "__main__":

    port = Config.PORT
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    tangoREST.tango.resetTango(tangoREST.tango.preallocator.vmms)
    application.listen(port, max_buffer_size=Config.MAX_INPUT_FILE_SIZE)
    asyncio.set_event_loop(asyncio.new_event_loop())
    tornado.ioloop.IOLoop.instance().start()
