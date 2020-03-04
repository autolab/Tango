from __future__ import print_function
# tangoREST.py
#
# Implements open, upload, addJob, and poll to be used for the RESTful
# interface of Tango.
#

from builtins import object
from builtins import str
import sys
import os
import inspect
import hashlib
import json
import logging

currentdir = os.path.dirname(
        os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0, parentdir)

from tango import TangoServer
from tangoObjects import TangoJob, TangoMachine, InputFile

from config import Config


class Status(object):

    def __init__(self):
        self.found_dir = self.create(0, "Found directory")
        self.made_dir = self.create(0, "Created directory")
        self.file_uploaded = self.create(0, "Uploaded file")
        self.file_exists = self.create(0, "File exists")
        self.job_added = self.create(0, "Job added")
        self.obtained_info = self.create(0, "Found info successfully")
        self.obtained_jobs = self.create(0, "Found list of jobs")
        self.preallocated = self.create(0, "VMs preallocated")
        self.obtained_pool = self.create(0, "Found pool")
        self.obtained_all_pools = self.create(0, "Found all pools")

        self.wrong_key = self.create(-1, "Key not recognized")
        self.wrong_courselab = self.create(-1, "Courselab not found")
        self.out_not_found = self.create(-1, "Output file not found")
        self.invalid_image = self.create(-1, "Invalid image name")
        self.invalid_prealloc_size = self.create(-1, "Invalid prealloc size")
        self.pool_not_found = self.create(-1, "Pool not found")
        self.prealloc_failed = self.create(-1, "Preallocate VM failed")

    def create(self, id, msg):
        """ create - Constructs a dict with the given ID and message
        """
        result = {}
        result["statusId"] = id
        result["statusMsg"] = msg
        return result


class TangoREST(object):

    COURSELABS = Config.COURSELABS
    OUTPUT_FOLDER = Config.OUTPUT_FOLDER
    LOGFILE = Config.LOGFILE

    # Replace with choice of key store and override validateKey.
    # This key is just for testing.
    KEYS = Config.KEYS

    def __init__(self):

        logging.basicConfig(
            filename = self.LOGFILE,
            format = "%(levelname)s|%(asctime)s|%(name)s|%(message)s",
            level = Config.LOGLEVEL
        )
        self.log = logging.getLogger("TangoREST")
        self.log.info("Starting RESTful Tango server")
        
        self.tango = TangoServer()
        self.status = Status()

    def validateKey(self, key):
        """ validateKey - Validates key provided by client
        """
        result = False
        for el in self.KEYS:
            if el == key:
                result = True
        return result

    def getDirName(self, key, courselab):
        """ getDirName - Computes directory name
        """
        return "%s-%s" % (key, courselab)

    def getDirPath(self, key, courselab):
        """ getDirPath - Computes directory path
        """
        labName = self.getDirName(key, courselab)
        return "%s/%s" % (self.COURSELABS, labName)

    def getOutPath(self, key, courselab):
        """ getOutPath - Computes output directory path
        """
        labPath = self.getDirPath(key, courselab)
        return "%s/%s" % (labPath, self.OUTPUT_FOLDER)

    def checkFileExists(self, directory, filename, fileMD5):
        """ checkFileExists - Checks if a file exists in a
            directory
        """
        for elem in os.listdir(directory):
            if elem == filename:
                try:
                    body = open("%s/%s" % (directory, elem)).read()
                    md5hash = hashlib.md5(body).hexdigest()
                    return md5hash == fileMD5
                except IOError:
                    continue

    def createTangoMachine(self, image, vmms=Config.VMMS_NAME,
                           vmObj={'cores': 1, 'memory': 512}):
        """ createTangoMachine - Creates a tango machine object from image
        """
        return TangoMachine(
            name=image,
            vmms=vmms,
            image="%s" % (image),
            cores=vmObj["cores"],
            memory=vmObj["memory"],
            disk=None,
            network=None)

    def convertJobObj(self, dirName, jobObj):
        """ convertJobObj - Converts a dictionary into a TangoJob object
        """

        name = jobObj['jobName']
        outputFile = "%s/%s/%s/%s" % (self.COURSELABS,
                                      dirName,
                                      self.OUTPUT_FOLDER,
                                      jobObj['output_file'])
        timeout = jobObj['timeout']
        notifyURL = None
        maxOutputFileSize = Config.MAX_OUTPUT_FILE_SIZE
        if 'callback_url' in jobObj:
            notifyURL = jobObj['callback_url']

        # List of input files
        input = []
        for file in jobObj['files']:
            inFile = file['localFile']
            vmFile = file['destFile']
            handinfile = InputFile(
                localFile="%s/%s/%s" % (self.COURSELABS, dirName, inFile),
                destFile=vmFile)
            input.append(handinfile)

        # VM object
        vm = self.createTangoMachine(jobObj["image"])

        # for backward compatibility
        accessKeyId = None
        accessKey = None
        if "accessKey" in jobObj and len(jobObj["accessKey"]) > 0:
            accessKeyId = jobObj["accessKeyId"]
            accessKey = jobObj["accessKey"]

        job = TangoJob(
            name=name,
            vm=vm,
            outputFile=outputFile,
            input=input,
            timeout=timeout,
            notifyURL=notifyURL,
            maxOutputFileSize=maxOutputFileSize,
            accessKey=accessKey,
            accessKeyId=accessKeyId
        )

        self.log.debug("inputFiles: %s" % [file.localFile for file in input])
        self.log.debug("outputFile: %s" % outputFile)
        return job

    def convertTangoMachineObj(self, tangoMachine):
        """ convertVMObj - Converts a TangoMachine object into a dictionary
        """
        # May need to convert instance_id
        vm = dict()
        vm['network'] = tangoMachine.network
        vm['resume'] = tangoMachine.resume
        vm['image'] = tangoMachine.image
        vm['memory'] = tangoMachine.memory
        vm['vmms'] = tangoMachine.vmms
        vm['cores'] = tangoMachine.cores
        vm['disk'] = tangoMachine.disk
        vm['id'] = tangoMachine.id
        vm['name'] = tangoMachine.name
        return vm

    def convertInputFileObj(self, inputFile):
        """ convertInputFileObj - Converts an InputFile object into a dictionary
        """
        input = dict()
        input['destFile'] = inputFile.destFile
        input['localFile'] = inputFile.localFile
        return input

    def convertTangoJobObj(self, tangoJobObj):
        """ convertTangoJobObj - Converts a TangoJob object into a dictionary
        """
        job = dict()
        # Convert scalar attribtues first
        job['retries'] = tangoJobObj.retries
        job['outputFile'] = tangoJobObj.outputFile
        job['name'] = tangoJobObj.name
        job['notifyURL'] = tangoJobObj.notifyURL
        job['maxOutputFileSize'] = tangoJobObj.maxOutputFileSize
        job['assigned'] = tangoJobObj.assigned
        job['timeout'] = tangoJobObj.timeout
        job['id'] = tangoJobObj.id
        job['trace'] = tangoJobObj.trace

        # Convert VM object
        job['vm'] = self.convertTangoMachineObj(tangoJobObj.vm)

        # Convert InputFile objects
        inputFiles = list()
        for inputFile in tangoJobObj.input:
            inputFiles.append(self.convertInputFileObj(inputFile))
        job['input'] = inputFiles

        return job
    ##
    # Tango RESTful API
    ##

    def open(self, key, courselab):
        """ open - Return a dict of md5 hashes for each input file in the
        key-courselab directory and make one if the directory doesn't exist
        """
        self.log.debug("Received open request(%s, %s)" % (key, courselab))
        if self.validateKey(key):
            labPath = self.getDirPath(key, courselab)
            try:
                if os.path.exists(labPath):
                    self.log.info(
                        "Found directory for (%s, %s)" % (key, courselab))
                    statusObj = self.status.found_dir
                    statusObj['files'] = {}
                    return statusObj
                else:
                    outputPath = self.getOutPath(key, courselab)
                    os.makedirs(outputPath)
                    self.log.info(
                        "Created directory for (%s, %s)" % (key, courselab))
                    statusObj = self.status.made_dir
                    statusObj["files"] = {}
                    return statusObj
            except Exception as e:
                self.log.error("open request failed: %s" % str(e))
                return self.status.create(-1, str(e))
        else:
            self.log.info("Key not recognized: %s" % key)
            return self.status.wrong_key

    def upload(self, key, courselab, file, tempfile, fileMD5):
        """ upload - Upload file as an input file in key-courselab if the
        same file doesn't exist already
        """
        self.log.debug("Received upload request(%s, %s, %s)" %
                       (key, courselab, file))
        if (self.validateKey(key)):
            labPath = self.getDirPath(key, courselab)
            try:
                if os.path.exists(labPath):
                    if self.checkFileExists(labPath, file, fileMD5):
                        self.log.info(
                            "File (%s, %s, %s) exists" % (key, courselab, file))
                        os.unlink(tempfile)
                        return self.status.file_exists
                    absPath = "%s/%s" % (labPath, file)
                    os.rename(tempfile, absPath)
                    self.log.info(
                        "Uploaded file to (%s, %s, %s)" %
                        (key, courselab, file))
                    return self.status.file_uploaded
                else:
                    self.log.info(
                        "Courselab for (%s, %s) not found" % (key, courselab))
                    os.unlink(tempfile)
                    return self.status.wrong_courselab
            except Exception as e:
                self.log.error("upload request failed: %s" % str(e))
                os.unlink(tempfile)
                return self.status.create(-1, str(e))
        else:
            self.log.info("Key not recognized: %s" % key)
            os.unlink(tempfile)
            return self.status.wrong_key

    def addJob(self, key, courselab, jobStr):
        """ addJob - Add the job to be processed by Tango
        """
        self.log.debug("Received addJob request(%s, %s, %s)" %
                       (key, courselab, jobStr))
        if (self.validateKey(key)):
            labName = self.getDirName(key, courselab)
            try:
                jobObj = json.loads(jobStr)
                job = self.convertJobObj(labName, jobObj)
                jobId = self.tango.addJob(job)
                self.log.debug("Done adding job")
                if (jobId == -1):
                    self.log.info("Failed to add job to tango")
                    return self.status.create(-1, job.trace)
                self.log.info("Successfully added job ID: %s to tango" % str(jobId))
                result = self.status.job_added
                result['jobId'] = jobId
                return result
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print((exc_type, fname, exc_tb.tb_lineno))
                self.log.error("addJob request failed: %s" % str(e))
                return self.status.create(-1, str(e))
        else:
            self.log.info("Key not recognized: %s" % key)
            return self.status.wrong_key

    def poll(self, key, courselab, outputFile):
        """ poll - Poll for the output file in key-courselab
        """
        self.log.debug("Received poll request(%s, %s, %s)" %
                       (key, courselab, outputFile))
        if (self.validateKey(key)):
            outputPath = self.getOutPath(key, courselab)
            outfilePath = "%s/%s" % (outputPath, outputFile)
            if os.path.exists(outfilePath):
                self.log.info("Output file (%s, %s, %s) found" %
                              (key, courselab, outputFile))
                output = open(outfilePath)
                result = output.read()
                output.close()
                return result
            self.log.info("Output file (%s, %s, %s) not found" %
                          (key, courselab, outputFile))
            return self.status.out_not_found
        else:
            self.log.info("Key not recognized: %s" % key)
            return self.status.wrong_key

    def info(self, key):
        """ info - Returns basic status for the Tango service such as uptime, number of jobs etc
        """
        self.log.debug("Received info request (%s)" % (key))
        if (self.validateKey(key)):
            info = self.tango.getInfo()
            result = self.status.obtained_info
            result['info'] = info
            return result
        else:
            self.log.info("Key not recognized: %s" % key)
            return self.status.wrong_key

    def jobs(self, key, deadJobs):
        """ jobs - Returns the list of live jobs (deadJobs == 0) or the list of dead jobs (deadJobs == 1)
        """
        self.log.debug("Received jobs request (%s, %s)" % (key, deadJobs))
        if (self.validateKey(key)):
            jobs = list()
            result = self.status.obtained_jobs
            if (int(deadJobs) == 0):
                jobs = self.tango.getJobs(0)
                self.log.debug(
                    "Retrieved live jobs (deadJobs = %s)" % deadJobs)
            elif (int(deadJobs) == 1):
                jobs = self.tango.getJobs(-1)
                self.log.debug(
                    "Retrieved dead jobs (deadJobs = %s)" % deadJobs)
            result['jobs'] = list()
            for job in jobs:
                result['jobs'].append(self.convertTangoJobObj(job))

            return result
        else:
            self.log.info("Key not recognized: %s" % key)
            return self.status.wrong_key

    def pool(self, key, image):
        """ pool - Get information about pool(s) of VMs
        """
        self.log.debug("Received pool request(%s, %s)" % (key, image))
        if self.validateKey(key):
            pools = self.tango.preallocator.getAllPools()
            self.log.info("All pools found")
            if image == "":
                result = self.status.obtained_all_pools
            else:
                if image in pools:
                    pools = {image: pools[image]}
                    self.log.info("Pool image found: %s" % image)
                    result = self.status.obtained_pool
                else:
                    self.log.info("Invalid image name: %s" % image)
                    result = self.status.pool_not_found
            
            result["pools"] = pools
            return result
        else:
            self.log.info("Key not recognized: %s" % key)
            return self.status.wrong_key

    def prealloc(self, key, image, num, vmStr):
        """ prealloc - Create a pool of num instances spawned from image
        """
        self.log.debug("Received prealloc request(%s, %s, %s)" %
                       (key, image, num))
        if self.validateKey(key):
            if vmStr != "":
                vmObj = json.loads(vmStr)
                vm = self.createTangoMachine(image, vmObj=vmObj)
            else:
                vm = self.createTangoMachine(image)

            ret = self.tango.preallocVM(vm, int(num))

            if ret == -1:
                self.log.error("Prealloc failed")
                return self.status.prealloc_failed
            if ret == -2:
                self.log.error("Invalid prealloc size")
                return self.status.invalid_prealloc_size
            if ret == -3:
                self.log.error("Invalid image name")
                return self.status.invalid_image
            self.log.info("Successfully preallocated VMs")
            return self.status.preallocated
        else:
            self.log.info("Key not recognized: %s" % key)
            return self.status.wrong_key
