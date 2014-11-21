# tangoREST.py
#
# Implements objects used to pass state within Tango.
#

class InputFile():
	"""
		InputFile - Stores pointer to the path on the local machine and the
		name of the file on the destination machine
	"""
	def __init__(self, localFile, destFile):
		self.localFile = localFile
		self.destFile = destFile

class TangoMachine():
	"""
		TangoMachine - A description of the Autograding Virtual Machine
	"""
	def __init__(self, name = "LocalVM", image = None, vmms = "localSSH",
				network = None, cores = None, memory = None, disk = None, 
				domain_name = None, ec2_id = None):
		self.name = name
		self.image = image
		self.network = network
		self.cores = cores
		self.memory = memory
		self.disk = disk
		self.vmms = vmms
		self.domain_name = domain_name
		self.ec2_id = ec2_id

class TangoJob():
	"""
		TangoJob - A job that is to be run on a TangoMachine
	"""
	def __init__(self, assigned = False, retries = 0, vm = None,
				outputFile = None, name = None, input = [],
				notifyURL = None, timeout = 0, trace = None, 
				maxOutputFileSize = 512):
		self.assigned = assigned
		self.retries = retries
		self.vm = vm
		self.input = input
		self.outputFile = outputFile
		self.name = name
		self.notifyURL = notifyURL
		self.timeout = timeout
		self.trace = trace
		self.maxOutputFileSize = maxOutputFileSize
