import os
import sys
import inspect
import hashlib

import urllib.error
import urllib.parse
import urllib.request

import tornado.web

from functools import partial, wraps
from concurrent.futures import ThreadPoolExecutor
from tempfile import NamedTemporaryFile
from tangoREST import TangoREST

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)

from config import Config

tangoREST = TangoREST()
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Regex for the resources
SHA1_KEY = ".+"  # So that we can have better error messages
COURSELAB = ".+"
OUTPUTFILE = ".+"
IMAGE = ".+"
NUM = "[0-9]+"
JOBID = "[0-9]+"
DEADJOBS = ".+"
io_loop_current = None

def unblock(f):
    @tornado.gen.coroutine
    @wraps(f)
    def wrapper(*args, **kwargs):
        self = args[0]

        def callback(future):
            self.write(future.result())
            self.finish()

        EXECUTOR.submit(partial(f, *args, **kwargs)).add_done_callback(
            lambda future: tornado.ioloop.IOLoop.instance().add_callback(
                partial(callback, future)
            )
        )

    return wrapper


class MainHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def get(self):
        """get - Default route to check if RESTful Tango is up."""
        self.write("Hello, world! RESTful Tango here!\n")
        self.finish()


class OpenHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def get(self, key, courselab):
        """get - Handles the get request to open."""
        self.write(tangoREST.open(key, courselab))
        self.finish()


@tornado.web.stream_request_body
class UploadHandler(tornado.web.RequestHandler):
    def prepare(self):
        """set up the temporary file"""
        tempdir = "%s/tmp" % (Config.COURSELABS,)
        if not os.path.exists(tempdir):
            os.mkdir(tempdir, 0o700)
        if os.path.exists(tempdir) and not os.path.isdir(tempdir):
            tangoREST.log("Cannot process uploads, %s is not a directory" % (tempdir,))
            return self.send_error()
        self.tempfile = NamedTemporaryFile(prefix="upload", dir=tempdir, delete=False)
        self.hasher = hashlib.md5()

    def data_received(self, chunk):
        self.hasher.update(chunk)
        self.tempfile.write(chunk)

    def post(self, key, courselab):
        """post - Handles the post request to upload."""
        name = self.tempfile.name
        self.tempfile.close()
        self.write(tangoREST.upload(
            key,
            courselab,
            self.request.headers["Filename"],
            name,
            self.hasher.hexdigest(),
        ))
        self.finish()


class AddJobHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def post(self, key, courselab):
        """post - Handles the post request to add a job."""
        self.write(tangoREST.addJob(key, courselab, self.request.body))
        self.finish()


class PollHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def get(self, key, courselab, outputFile):
        """get - Handles the get request to poll."""
        self.set_header("Content-Type", "application/octet-stream")
        self.write(tangoREST.poll(key, courselab, urllib.parse.unquote(outputFile)))


class GetPartialHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def get(self, key, jobId):
        """get - Handles the get request to partialOutput"""
        self.set_header("Content-Type", "application/octet-stream")
        self.write(tangoREST.getPartialOutput(key, jobId))


class InfoHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def get(self, key):
        """get - Handles the get request to info."""
        self.write(tangoREST.info(key))
        self.finish()


class JobsHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def get(self, key, deadJobs):
        """get - Handles the get request to jobs."""
        self.write(tangoREST.jobs(key, deadJobs))
        self.finish()


class PoolHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def get(self, key):
        """get - Handles the get request to pool."""
        image = ""
        if "/" in key:
            key_l = key.split("/")
            key = key_l[0]
            image = key_l[1]
        self.write(tangoREST.pool(key, image))
        self.finish()


class PreallocHandler(tornado.web.RequestHandler):
    @tornado.gen.coroutine
    def post(self, key, image, num):
        """post - Handles the post request to prealloc."""
        self.write(tangoREST.prealloc(key, image, num, self.request.body))
        self.finish()


# Routes
application = tornado.web.Application(
    [
        (r"/", MainHandler),
        (r"/open/(%s)/(%s)/" % (SHA1_KEY, COURSELAB), OpenHandler),
        (r"/upload/(%s)/(%s)/" % (SHA1_KEY, COURSELAB), UploadHandler),
        (r"/addJob/(%s)/(%s)/" % (SHA1_KEY, COURSELAB), AddJobHandler),
        (r"/poll/(%s)/(%s)/(%s)/" % (SHA1_KEY, COURSELAB, OUTPUTFILE), PollHandler),
        (r"/getPartialOutput/(%s)/(%s)/" % (SHA1_KEY, JOBID), GetPartialHandler),
        (r"/info/(%s)/" % (SHA1_KEY), InfoHandler),
        (r"/jobs/(%s)/(%s)/" % (SHA1_KEY, DEADJOBS), JobsHandler),
        (r"/pool/(%s)/" % (SHA1_KEY), PoolHandler),
        (r"/prealloc/(%s)/(%s)/(%s)/" % (SHA1_KEY, IMAGE, NUM), PreallocHandler),
    ]
)


if __name__ == "__main__":

    port = Config.PORT
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    tangoREST.tango.resetTango(tangoREST.tango.preallocator.vmms)
    application.listen(port, max_buffer_size=Config.MAX_INPUT_FILE_SIZE)
    io_loop_current = tornado.ioloop.IOLoop.current()
    tornado.ioloop.IOLoop.current().start()
