import os
import sys
import inspect
import hashlib
import json 
import html

import urllib.error
import urllib.parse
import urllib.request

import tornado.ioloop
import tornado.web
from tempfile import NamedTemporaryFile
from restful_tango.tangoREST import TangoREST, IamAuthError
import asyncio

from config import Config
from vmms import ecrBuilder 

tangoREST = TangoREST()

# Regex for the resources
SHA1_KEY = ".+"  # So that we can have better error messages
COURSELAB = ".+"
OUTPUTFILE = ".+"
IMAGE = ".+"
NUM = "[0-9]+"
JOBID = "[0-9]+"
DEADJOBS = ".+"

# IAM routes: a UUID4 job id, and the IAM charset rather than ".+" so that a
# username cannot smuggle path segments.
IAM_JOBID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
IAM_USERNAME = "[A-Za-z0-9+=,.@_-]{1,64}"

# The /iam routes take their key from a header, not the path, and it is
# Config.IAM_ADMIN_KEYS rather than Config.KEYS.
IAM_KEY_HEADER = "X-Tango-Key"


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

class BuildImageHandler(tornado.web.RequestHandler):
    def post(self, key):
        """post - Trigger the ECR Docker build."""
        try:
            payload = json.loads(self.request.body.decode('utf-8'))
            course_id = payload.get("course_id")
            job_id = payload.get("job_id")
            image_name = payload.get("image_name")
            dockerfile_content = payload.get("dockerfile_content")
            is_public = payload.get("is_public")
            base_tag = payload.get("base_tag")
            base_uri = payload.get("base_uri")

            if any(x is None for x in [job_id, image_name, dockerfile_content, is_public]):
                self.set_status(400)
                print([job_id, image_name, dockerfile_content, is_public, course_id])
                self.write({"statusMsg": "Missing required parameters", "statusId": -1})
                return
            
            if not is_public and course_id is None:
                self.set_status(400)
                self.write({"statusMsg": "Requires course_id if image is private.", "statusId": -1})
                return
            
            if base_tag is not None and base_uri is None:
                self.set_status(400)
                self.write({"statusMsg": "Requires the URI to pull from a base docker image", "statusId": -1})
                return
            
            if is_public:
                course_id = "public"

            # Trigger background build
            assert(tangoREST.buildImage(key, course_id, job_id, image_name, dockerfile_content, base_tag, base_uri) == job_id)

            safe_job_id = html.escape(str(job_id), quote=True)
            response = {
                "statusMsg": "Building image in ECR",
                "statusId": 1,
                "jobId": safe_job_id
            }
            self.write(response)
            
        except Exception as e:
            self.set_status(500)
            self.write({"statusMsg": f"Server Error: {str(e)}", "statusId": -1})

class BuildStatusHandler(tornado.web.RequestHandler):
    def get(self, key, jobId):
        """get - Poll for the status of an ECR build."""
        status_data = tangoREST.buildStatus(key, job_id=jobId)
        self.write(status_data)

class AllBuildStatusHandler(tornado.web.RequestHandler):
    def get(self, key):
        """get - Poll for the status of an ECR build."""
        status_data = tangoREST.allBuildStatus(key)
        self.write(status_data)

class IamBaseHandler(tornado.web.RequestHandler):
    """Shared auth, cache and error handling for the /iam routes."""

    def iamKey(self):
        """Read the admin key from the request header."""
        return self.request.headers.get(IAM_KEY_HEADER, "")

    def noStore(self):
        """Keep responses that can carry a secret out of caches."""
        self.set_header("Cache-Control", "no-store")

    def writeIamError(self, status, msg):
        self.set_status(status)
        self.write({"statusId": -1, "statusMsg": msg})

    def handleIamError(self, e):
        """Map a provisioning exception onto an HTTP status code."""
        from vmms.iamProvisioner import (
            IamCapacityError,
            IamJobNotFound,
            IamUserNotFound,
            IamValidationError,
        )

        if isinstance(e, IamAuthError):
            self.writeIamError(403, "Key not recognized")
        elif isinstance(e, IamValidationError):
            self.writeIamError(400, str(e))
        elif isinstance(e, (IamJobNotFound, IamUserNotFound)):
            self.writeIamError(404, str(e))
        elif isinstance(e, IamCapacityError):
            self.set_header("Retry-After", "30")
            self.writeIamError(503, str(e))
        else:
            # Logged rather than returned: an AWS error can name account
            # internals the caller has no business seeing.
            tangoREST.log.error("IAM request failed: %s" % str(e))
            self.writeIamError(500, "Server error")


class IamProvisionHandler(IamBaseHandler):
    def post(self):
        """post - Start provisioning an IAM user, return a job id."""
        try:
            payload = json.loads(self.request.body.decode("utf-8") or "{}")
        except ValueError:
            return self.writeIamError(400, "Body must be valid JSON")

        if not isinstance(payload, dict):
            return self.writeIamError(400, "Body must be a JSON object")

        iam_username = payload.get("iam_username")
        instance_id = payload.get("instance_id")

        missing = [
            field
            for field, value in (
                ("iam_username", iam_username),
                ("instance_id", instance_id),
            )
            if value is None
        ]
        if missing:
            return self.writeIamError(
                400, "Missing required parameters: %s" % ", ".join(missing)
            )

        create_key = payload.get("create_key", False)
        if not isinstance(create_key, bool):
            return self.writeIamError(400, "create_key must be a boolean")

        try:
            result = tangoREST.iamProvision(
                self.iamKey(),
                iam_username,
                payload.get("os_username"),
                instance_id,
                create_key,
            )
        except Exception as e:
            return self.handleIamError(e)

        self.set_status(202)
        self.write(result)


class IamJobStatusHandler(IamBaseHandler):
    def get(self, jobId):
        """get - Poll the status of an IAM provisioning job."""
        # Set before writing: this response can carry a one-time access key.
        self.noStore()
        try:
            self.write(tangoREST.iamJobStatus(self.iamKey(), jobId))
        except Exception as e:
            self.handleIamError(e)


class IamAccessKeyHandler(IamBaseHandler):
    async def post(self, iamUsername):
        """post - Replace the user's access keys with a fresh one."""
        # This response returns a secret.
        self.noStore()
        key = self.iamKey()

        # Checked here as well as in iamCreateKey so that an unauthorized
        # request does not occupy an executor thread.
        try:
            tangoREST.requireIamAdminKey(key)
        except Exception as e:
            return self.handleIamError(e)

        try:
            # Blocking IAM calls, kept off the event loop. run_in_executor
            # rather than asyncio.to_thread, which needs Python 3.9.
            result = await tornado.ioloop.IOLoop.current().run_in_executor(
                None, tangoREST.iamCreateKey, key, iamUsername
            )
        except Exception as e:
            return self.handleIamError(e)

        self.write(result)


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
            (r"/build_image/(%s)/" % (SHA1_KEY), BuildImageHandler), 
            (r"/build_status/(%s)/(%s)/" % (SHA1_KEY, JOBID), BuildStatusHandler), 
            (r"/all_build_status/(%s)/" % (SHA1_KEY), AllBuildStatusHandler),
            # IAM developer access. Key comes from the X-Tango-Key header, so
            # these paths carry no key segment.
            (r"/iam/users/?", IamProvisionHandler),
            (r"/iam/jobs/(%s)/?" % (IAM_JOBID), IamJobStatusHandler),
            (r"/iam/users/(%s)/key/?" % (IAM_USERNAME), IamAccessKeyHandler),
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