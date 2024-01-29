import os
import sys
import inspect
import hashlib

import urllib.error
import urllib.parse
import urllib.request

import tornado.web
from tempfile import NamedTemporaryFile
from tangoREST import TangoREST
import asyncio

currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)

from config import Config

tangoREST = TangoREST()

# Regex for the resources
SHA1_KEY = ".+"  # So that we can have better error messages
COURSELAB = ".+"
OUTPUTFILE = ".+"
IMAGE = ".+"
NUM = "[0-9]+"
JOBID = "[0-9]+"
DEADJOBS = ".+"


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        """get - Default route to check if RESTful Tango is up."""
        self.write("Hello, world! RESTful Tango here!\n")


class OpenHandler(tornado.web.RequestHandler):
    def get(self, key, courselab):
        """get - Handles the get request to open."""
        self.write(tangoREST.open(key, courselab))


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
        self.write(
            tangoREST.upload(
                key,
                courselab,
                self.request.headers["Filename"],
                name,
                self.hasher.hexdigest(),
            )
        )


class AddJobHandler(tornado.web.RequestHandler):
    def post(self, key, courselab):
        """post - Handles the post request to add a job."""
        self.write(tangoREST.addJob(key, courselab, self.request.body))


class PollHandler(tornado.web.RequestHandler):
    def get(self, key, courselab, outputFile):
        """get - Handles the get request to poll."""
        self.set_header("Content-Type", "application/octet-stream")
        pollResults = tangoREST.poll(key, courselab, urllib.parse.unquote(outputFile))
        self.write(pollResults)


class GetPartialHandler(tornado.web.RequestHandler):
    def get(self, key, jobId):
        """get - Handles the get request to partialOutput"""
        self.set_header("Content-Type", "application/octet-stream")
        self.write(tangoREST.getPartialOutput(key, jobId))


class InfoHandler(tornado.web.RequestHandler):
    def get(self, key):
        """get - Handles the get request to info."""
        self.write(tangoREST.info(key))


class JobsHandler(tornado.web.RequestHandler):
    def get(self, key, deadJobs):
        """get - Handles the get request to jobs."""
        self.write(tangoREST.jobs(key, deadJobs))


class PoolHandler(tornado.web.RequestHandler):
    def get(self, key):
        """get - Handles the get request to pool."""
        image = ""
        if "/" in key:
            key_l = key.split("/")
            key = key_l[0]
            image = key_l[1]
        self.write(tangoREST.pool(key, image))


class PreallocHandler(tornado.web.RequestHandler):
    async def post(self, key, image, num):
        """post - Handles the post request to prealloc."""
        instances = await tangoREST.prealloc(key, image, num, self.request.body)
        self.write(instances)


@tornado.web.stream_request_body
class BuildHandler(tornado.web.RequestHandler):
    def prepare(self):
        """set up the temporary file"""
        tempdir = "dockerTmp"
        if not os.path.exists(tempdir):
            os.mkdir(tempdir, 0o700)
        if os.path.exists(tempdir) and not os.path.isdir(tempdir):
            tangoREST.log("Cannot process uploads, %s is not a directory" % (tempdir,))
            return self.send_error()
        self.tempfile = NamedTemporaryFile(prefix="docker", dir=tempdir, delete=False)

    def data_received(self, chunk):
        self.tempfile.write(chunk)

    def post(self, key):
        """post - Handles the post request to build."""
        name = self.tempfile.name
        self.tempfile.close()
        self.write(tangoREST.build(key, name, self.request.headers["imageName"]))


async def main(port: int):
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
            (r"/build/(%s)/" % (SHA1_KEY), BuildHandler),
        ]
    )
    application.listen(port, max_buffer_size=Config.MAX_INPUT_FILE_SIZE)
    await asyncio.Event().wait()


if __name__ == "__main__":
    port = Config.PORT
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    tangoREST.tango.resetTango(tangoREST.tango.preallocator.vmms)
    asyncio.run(main(port))
