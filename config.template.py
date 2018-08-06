#
# config.py - Global configuration constants and runtime info
#

import logging, time

# Config - defines


class Config:
    #####
    # Part 1: Tango constants for developers
    #
    # These allow developers to run test versions of Tango on the same
    # server as the production Tango

    # Unique prefix that defines VM name space for this Tango
    # version. When working in development, this prefix should be your
    # unique identifier. The "prod" prefix is reserved for production
    PREFIX = "local"

    # Default port for the RESTful server to listen on.
    PORT = 3000

    # Log file. Setting this to None sends the server output to stdout
    # Strongly suggest setting up a log file
    LOGFILE = None

    # Logging level
    LOGLEVEL = logging.DEBUG

    # Courselabs directory. Must be created before starting Tango
    COURSELABS = "courselabs"
    
    # Directory within each courselab where Tango will copy the output 
    # for jobs of that courselab
    OUTPUT_FOLDER = "output"

    # VMMS to use. Must be set to a VMMS implemented in vmms/ before
    # starting Tango.  Options are: "localDocker", "distDocker",
    # "tashiSSH", and "ec2SSH"
    VMMS_NAME = "localDocker"

    #####
    # Part 2: Constants that shouldn't need to change very often.
    #

    # Keys for Tango to authenticate client requests
    KEYS = ["test"]

    # Queue manager checks for new work every so many seconds
    DISPATCH_PERIOD = 0.2

    # Timer polling interval used by timeout() function
    TIMER_POLL_INTERVAL = 1

    # Number of server threads
    NUM_THREADS = 20

    # We have the option to reuse VMs or discard them after each use
    # xxxXXX??? strongly suspect the code path for the False case
    # not working, after a failed experiment. -- czang@cmu.edu
    REUSE_VMS = True

    # Worker waits this many seconds for functions waitvm, copyin (per
    # file), runjob, and copyout (per file) functions to finish.
    INITIALIZEVM_TIMEOUT = 180
    WAITVM_TIMEOUT = 60
    COPYIN_TIMEOUT = 30
    RUNJOB_TIMEOUT = 60
    COPYOUT_TIMEOUT = 30

    # time zone and timestamp report interval for autodriver execution
    # both are optional.
    AUTODRIVER_LOGGING_TIME_ZONE = "UTC"  # e.g. "America/New_York".
    AUTODRIVER_TIMESTAMP_INTERVAL = 0  # in seconds. 0 => no timestamp insersion

    # Docker constants
    BOOT2DOCKER_INIT_TIMEOUT = 5
    BOOT2DOCKER_START_TIMEOUT = 30
    BOOT2DOCKER_ENV_TIMEOUT = 5
    DOCKER_IMAGE_BUILD_TIMEOUT = 300
    DOCKER_RM_TIMEOUT = 5
    # Must be absolute path with trailing slash
    # Default value of '*'' points this path to /path/to/Tango/volumes/
    DOCKER_VOLUME_PATH = '*'
    DOCKER_HOST_USER = ''

    # Maximum size for input files in bytes
    MAX_INPUT_FILE_SIZE = 250 * 1024 * 1024 # 250MB

    # Maximum size for output file in bytes
    MAX_OUTPUT_FILE_SIZE = 1000 * 1024

    # VM ulimit values
    VM_ULIMIT_FILE_SIZE = 100 * 1024 * 1024
    VM_ULIMIT_USER_PROC = 100

    # How many times to reschedule a failed job
    JOB_RETRIES = 2

    # How many times to attempt an SSH connection
    SSH_RETRIES = 5

    # Frequency of retrying SSH connections (in seconds)
    SSH_INTERVAL = 0.5

    # Give VMMS this many seconds to destroy a VM before giving up
    DESTROY_SECS = 5

    # When set to True, put the vm aside for debugging after OS ERROR by autodriver
    KEEP_VM_AFTER_FAILURE = None

    # Time to wait between creating VM instances to give DNS time to cool down
    CREATEVM_SECS = 1

    # Default vm pool size
    POOL_SIZE = 10

    # vm pool reserve size.  If set, free pool size is maintained at the level.
    POOL_SIZE_LOW_WATER_MARK = 5  # optional, can be None

    # Increment step when enlarging vm pool
    POOL_ALLOC_INCREMENT = 2  # can be None, which is treated as 1, the default

    # Optionally log finer-grained timing information
    LOG_TIMING = False

    # Largest job ID
    MAX_JOBID = 1000

    ######
    # Part 3: Runtime info that you can retrieve using the /info route
    #
    start_time = time.time()
    job_requests = 0
    job_retries = 0
    waitvm_timeouts = 0
    copyin_errors = 0
    runjob_timeouts = 0
    runjob_errors = 0
    copyout_errors = 0

    ######
    # Part 4: Settings for shared memory
    #
    USE_REDIS = True
    REDIS_HOSTNAME = "127.0.0.1"
    REDIS_PORT = 6379

    ######
    # Part 5: EC2 Constants
    #

    # Special instructions to admin: Tango finds usable images from aws
    # in the following fashion:
    # It examines every ami (Amazon Image) owned by the EC2_USER_NAME,
    # looks for a tag with the key "Name" (case sensitive), and use the value
    # of the tag as the image name for the ami, for example, ubuntu.img or
    # myImage.img.  If an ami doesn't have such tag, it is ignored (watch
    # for a log message).
    #
    # The lab author, when specifying an image to use, should specify one
    # of those image names available.

    EC2_REGION = ''
    EC2_USER_NAME = ''
    KEEP_VM_AFTER_FAILURE = False
    OVERRIDE_INST_TYPE = ''  # force instance type, if defined
    DEFAULT_INST_TYPE = ''
    DEFAULT_SECURITY_GROUP = ''
    SECURITY_KEY_PATH = ''
    DYNAMIC_SECURITY_KEY_PATH = ''  # key file placed at root "/" by default
    SECURITY_KEY_NAME = ''
    TANGO_RESERVATION_ID = ''
    INSTANCE_RUNNING = 16  # Status code of a instance that is running
