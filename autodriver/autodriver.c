/**
 * @file autodriver.c
 *
 * @brief Autograding driver program
 *
 * Autodriver handles the task of running autograded labs. It should be
 * configured to be a setuid binary owned by root, and called by a regular
 * user. It forks a child process.
 *
 * The child configures various system limits and then drops its root
 * privileges and executes the job.
 *
 * The parent keeps its root privileges. It waits for the job process to
 * finish, optionally using a timeout to kill the process if it continues too
 * long. It then exits, returning a status code of 2 if the job timed out or
 * 0 otherwise
 *
 * @author Steven Fackler <sfackler@andrew.cmu.edu>
 */

// For setresuid and setresgid
#define _GNU_SOURCE
#include <argp.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <limits.h>
#include <pwd.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <time.h>
#include <pthread.h>

#define min(x, y)       ((x) < (y) ? (x) : (y))

char timestampStr[100];
char * getTimestamp(time_t t) {
  time_t ltime = t ? t : time(NULL);
  struct tm* tmInfo = localtime(&ltime);
  strftime(timestampStr, 100, "%Y%m%d-%H:%M:%S", tmInfo);
  return timestampStr;  // return global variable for conveniece
}

#define ERROR_ERRNO(format, ...)  \
  printf("Autodriver@%s: ERROR " format " at line %d: %s\n", \
         getTimestamp(0), ##__VA_ARGS__, __LINE__, strerror(errno))

#define ERROR(format, ...)  \
  printf("Autodriver@%s: ERROR " format " at line %d\n", \
         getTimestamp(0), ##__VA_ARGS__, __LINE__)

#define MESSAGE(format, ...)  \
  printf("Autodriver@%s: " format "\n", getTimestamp(0), ##__VA_ARGS__)

#define EXIT__BASE     1

/* Exit codes for use after errors */
#define EXIT_USAGE      (EXIT__BASE + 0)
#define EXIT_TIMEOUT    (EXIT__BASE + 1)
#define EXIT_OSERROR    (EXIT__BASE + 2)

/* Name of file to redirect output to */
#define OUTPUT_FILE     "output.log"

/* User to grade as */
#define GRADING_USER    "autograde"

/* Size of buffers */
#define BUFSIZE         1024

/* Number of time we'll try to kill the grading user's processes */
#define MAX_KILL_ATTEMPTS   5

/* Number of seconds to wait in between pkills */
#define SHUTDOWN_GRACE_TIME 3

/**
 * @brief A structure containing all of the user-configurable settings
 */
struct arguments {
    unsigned nproc;
    unsigned fsize;
    unsigned timeout;
    unsigned osize;
    struct passwd user_info;
    char *passwd_buf;
    char *directory;
    char *timezone;
    unsigned timestamp_interval;
} args;

unsigned long startTime = 0;

typedef struct {
  time_t time;
  size_t offset;
  int offsetJumped;
} timestamp_map_t;

#define TIMESTAMP_MAP_CHUNK_SIZE 1024

timestamp_map_t *timestampMap = NULL;  // remember time@offset of output file
unsigned timestampCount = 0;

size_t outputFileSize = 0;
int child_output_fd;  // OUTPUT_FILE created/opened by main process, used by child
int parent_output_fd;  // OUTPUT_FILE created/opened by main process, used by parent

/**
 * @brief Parses a string into an unsigned integer.
 *
 * The string must be _just_ an integer. On parse failure, num is not modified.
 *
 * @arg str String to parse
 * @arg num Pointer to store result in
 *
 * @return 0 on success, -1 on parse failure
 */
static int parse_uint(char *str, unsigned *num) {
    char *end;

    errno = 0;
    unsigned long result = strtoul(str, &end, 0);

    // Check for a parse error
    if (errno != 0 || *end != '\0') {
        return -1;
    }

    // Check for overflow
    if (result > UINT_MAX) {
        return -1;
    }

    *num = (unsigned) result;
    return 0;
}

/**
 * @brief Parses a username into a uid and gid
 *
 * uid and gid are not modified no failure
 *
 * @arg name Username
 * @arg user_info Passwd struct to store info in
 * @arg buf Pointer to allocate buffer for user_info to
 *
 * @return 0 on success, -1 on unknown user
 */
static int parse_user(char *name, struct passwd *user_info, char **buf) {
    struct passwd *result;
    long bufsize;
    int s;

    if ((bufsize = sysconf(_SC_GETPW_R_SIZE_MAX)) < 0) {
        ERROR_ERRNO("Unable to get buffer size");
        exit(EXIT_OSERROR);
    }

    if ((*buf = malloc(bufsize)) == NULL) {
        ERROR("Unable to malloc buffer");
        exit(EXIT_OSERROR);
    }

    s = getpwnam_r(name, user_info, *buf, bufsize, &result);
    if (result == NULL) {
        if (s != 0) {
            errno = s;
            ERROR_ERRNO("Unable to get user info");
            exit(EXIT_OSERROR);
        } else {
            return -1;
        }
    }

    return 0;
}

// pthread function, keep a map of timestamp and user's output file offset
void *timestampFunc() {
  // time_t lastIntervalStamp = time(NULL);
  while (1) {
    // allocate/reallocate space to create/grow the map
    if (timestampCount % TIMESTAMP_MAP_CHUNK_SIZE == 0) {
      timestamp_map_t *newBuffer =
        realloc(timestampMap,
                sizeof(timestamp_map_t) * (TIMESTAMP_MAP_CHUNK_SIZE + timestampCount));
      if (!newBuffer){
        ERROR_ERRNO("Failed to allocate timestamp map. Current map size %d",
                    timestampCount);
        continue;  // continue without allocation
      }
      timestampMap = newBuffer;
      newBuffer += timestampCount;
      memset(newBuffer, 0, sizeof(timestamp_map_t) * TIMESTAMP_MAP_CHUNK_SIZE);
    }

    struct stat buf;
    if (parent_output_fd <= 0 || fstat(parent_output_fd, &buf) < 0) {
      ERROR_ERRNO("Error statting output file to read offset");
      continue;  // simply skip this time
    }

    /*
    time_t currentTime = time(NULL);
    int addStamp = 0;
    if (currentTime - lastIntervalStamp >= args.timestamp_interval) {
      addStamp = 1;
      lastIntervalStamp = currentTime;
    }
    */

    timestampMap[timestampCount].time = time(NULL);
    timestampMap[timestampCount].offset = buf.st_size;
    timestampCount++;

    /*
    printf("current time %lu\n", time(NULL));
    sleep(1);
    */

    sleep(args.timestamp_interval);
  }

  return NULL;
}

int writeBuffer(char *buffer, size_t nBytes) {  // nBytes can be zero (no-op)
  ssize_t nwritten = 0;
  size_t  write_rem = nBytes;
  char *write_base = buffer;

  while (write_rem > 0) {
    if ((nwritten = write(STDOUT_FILENO, write_base, write_rem)) < 0) {
      ERROR_ERRNO("Error writing output");
      return -1;
    }
    write_rem -= nwritten;
    write_base += nwritten;
  }
  return 0;
}

#define WRITE_BUFFER(buffer, nBytes)  \
  if (writeBuffer(buffer, nBytes)) return -1

/**
 * @brief Dumps a specified number of bytes from a file to standard out
 *
 * @arg fd File to read from
 * @arg bytes Number of bytes to read
 * @arg offset Offset to start from
 *
 * @return 0 on success, -1 on failure
 */
static int dump_file(int fd, size_t bytes, off_t offset) {
    static unsigned currentStamp = 0;
    size_t read_rem = bytes;
    size_t nextOffset = offset;

    if (offset) {  // second part of output file, after truncating in the middle
        char *msg = "\n...[excess bytes elided by autodriver]...\n";
        WRITE_BUFFER(msg, strlen(msg));
    }

    // Flush stdout so our writes here don't race with buffer flushes
    if (fflush(stdout) != 0) {
        ERROR_ERRNO("Error flushing standard out");
        return -1;
    }

    if (lseek(fd, offset, SEEK_SET) < 0) {
        ERROR_ERRNO("Error seeking in output file");
        return -1;
    }

    while (read_rem > 0) {
      char buffer[BUFSIZE];
      ssize_t nread;
      size_t bufferOffset = nextOffset;

      memset(buffer, 0, BUFSIZE);
      if ((nread = read(fd, buffer, min(read_rem, BUFSIZE))) < 0) {
        ERROR_ERRNO("Error reading from output file");
        return -1;
      }
      read_rem -= nread;
      nextOffset += nread;  // offset of currently read buffer in the file
      char *scanCursor = buffer;
      size_t eolOffset = 0;

      // pace through timestamps that fall into the buffer
      while (currentStamp < timestampCount &&
             timestampMap[currentStamp].offset < nextOffset) {

        // there might be unused timestamps from last read buffer or before last eol
        if (timestampMap[currentStamp].offset < bufferOffset ||
            timestampMap[currentStamp].offset <= eolOffset) {
          currentStamp++;
          continue;
        }

        char *eolSearchStart = timestampMap[currentStamp].offset - bufferOffset + buffer;
        char *nextEol = strchr(eolSearchStart, '\n');
        if (!nextEol) {  // no line break found in read buffer to insert timestamp
          break;
        }

        // write the stuff up to the line break
        WRITE_BUFFER(scanCursor, nextEol - scanCursor + 1);  // write up to \n
        scanCursor = nextEol + 1;

        // no timestamp at EOF, because the test scores are on the last line
        eolOffset = bufferOffset + (nextEol - buffer);
        if (eolOffset + 1 >= outputFileSize) {
          break;
        }

        // write the timestamp
        char stampInsert[200];
        sprintf(stampInsert,
                "...[timestamp %s inserted by autodriver at offset ~%lu. Maybe out of sync with output's own timestamps.]...\n",
                getTimestamp(timestampMap[currentStamp].time),
                timestampMap[currentStamp].offset);
        WRITE_BUFFER(stampInsert, strlen(stampInsert));
        currentStamp++;
      }  // while loop through the stamps falling into read buffer's range

      WRITE_BUFFER(scanCursor, nread - (scanCursor - buffer));
    }  // while loop finish reading

    return 0;
}

/**
 * @brief Argument parsing callback function for argp_parse
 */
static error_t parse_opt(int key, char *arg, struct argp_state *state) {
    struct arguments *arguments = state->input;

    switch (key) {
    case 'u':
        if (parse_uint(arg, &arguments->nproc) < 0) {
            argp_failure(state, EXIT_USAGE, 0, 
                "The argument to nproc must be a nonnegative integer");
        }
        break;
    case 'f':
        if (parse_uint(arg, &arguments->fsize) < 0) {
            argp_failure(state, EXIT_USAGE, 0, 
                "The argument to fsize must be a nonnegative integer");
        }
        break;
    case 't':
        if (parse_uint(arg, &arguments->timeout) < 0) {
            argp_failure(state, EXIT_USAGE, 0, 
                "The argument to timeout must be a nonnegative integer");
        }
        break;
    case 'o':
        if (parse_uint(arg, &arguments->osize) < 0) {
            argp_failure(state, EXIT_USAGE, 0, 
                "The argument to osize must be a nonnegative integer");
        }
        break;
    case 'i':
        if (parse_uint(arg, &arguments->timestamp_interval) < 0) {
            argp_failure(state, EXIT_USAGE, 0,
                "The argument to timestamp-interval must be a nonnegative integer");
        }
        break;
    case 'z':
        args.timezone = arg;
        break;
    case ARGP_KEY_ARG:
        switch (state->arg_num) {
        case 0:
            arguments->directory = arg;
            break;
        default:
            argp_error(state, "Too many arguments");
            break;
        }
        break;
    case ARGP_KEY_END:
        if (state->arg_num < 1) {
            argp_error(state, "Too few arguments");
        }
        break;
    default:
        return ARGP_ERR_UNKNOWN;
    }

    return 0;
}

/**
 * @brief Calls an external program
 *
 * Since this is a setuid binary, we shouldn't use system()
 *
 * @arg path Path to program to run
 * @arg argv NULL terminated array of arguments
 */
static int call_program(char *path, char *argv[]) {
    pid_t pid;
    int status;
    
    if ((pid = fork()) < 0) {
        ERROR_ERRNO("Unable to fork");
        exit(EXIT_OSERROR);
    } else if (pid == 0) {
        execv(path, argv);
        ERROR_ERRNO("Unable to exec");
        exit(EXIT_OSERROR);
    }

    // TODO: Timeouts?
    waitpid(pid, &status, 0);
    return WEXITSTATUS(status);
}

/**
 * @brief Sets up the directory the job will be graded in and sets it as the
 *  current directory
 */
static void setup_dir(void) {
    // Move the directory over to the user we're running as's home directory
    char *mv_args[] = {"/bin/mv", "-f", args.directory, 
        args.user_info.pw_dir, NULL};
    if (call_program("/bin/mv", mv_args) != 0) {
        ERROR("Error moving directory");
        exit(EXIT_OSERROR);
    }

    // And switch over to that directory
    if (chdir(args.user_info.pw_dir) < 0) {
        ERROR_ERRNO("Error changing directories");
        exit(EXIT_OSERROR);
    }

    // And change the ownership of the directory we copied
    char owner[100];
    sprintf(owner, "%d:%d", args.user_info.pw_uid, args.user_info.pw_gid);
    char *chown_args[] = {"/bin/chown", "-R", owner, args.directory, NULL};
    if (call_program("/bin/chown", chown_args) != 0) {
        ERROR("Error chowining directory");
        exit(EXIT_OSERROR);
    }
}

/**
 * @brief Dumps the output of the job, truncating if necessary
 */
static void dump_output(void) {
    int outfd;
    if ((outfd = open(OUTPUT_FILE, O_RDONLY)) < 0) {
        ERROR_ERRNO("Error opening output file at the end of test");
        exit(EXIT_OSERROR);
    }

    struct stat stat;
    if (fstat(outfd, &stat) < 0) {
        ERROR_ERRNO("Error statting output file");
        exit(EXIT_OSERROR);
    }
    outputFileSize = stat.st_size;

    // Truncate output if we have to
    if (args.osize > 0 && stat.st_size > args.osize) {
        MESSAGE("Output size %lu > limit %u -- will elide in the middle",
                stat.st_size, args.osize);
        unsigned part_size = args.osize / 2;
        if (dump_file(outfd, part_size, 0) < 0) {
            exit(EXIT_OSERROR);
        }
        if (dump_file(outfd, part_size, stat.st_size - part_size) < 0) {
            exit(EXIT_OSERROR);
        }
    } else {
        if (dump_file(outfd, stat.st_size, 0) < 0) {
            exit(EXIT_OSERROR);
        }
    }
    if (close(outfd) < 0) {
        ERROR_ERRNO("Error closing output file at the end of test");
        exit(EXIT_OSERROR);
    }
}

/**
 * @brief Wraps pkill(1) to send a signal to the grading user's processes
 *
 * @arg sig Signal to send (argument format e.g "-KILL", "-INT")
 *
 * @return Same as pkill, 0 on success, 1 on no processes found
 */
static int kill_processes(char *sig) {
    int ret;
    char *pkill_args[] = {"/usr/bin/pkill", sig, "-u",
        GRADING_USER, NULL};

    if ((ret = call_program("/usr/bin/pkill", pkill_args)) > 1) {
        ERROR("Error killing user processes");
        // don't quit.  Let the caller decide
    }
    return ret;
}

/**
 * @brief Clean up the grading user's state.
 *
 * Kills all processes and deletes all files
 */
static void cleanup(void) {
    if (parent_output_fd <= 0 || close(parent_output_fd) < 0) {
      ERROR_ERRNO("Error closing output file before cleanup");
    }

    // Kill all of the user's processes
    int ret;
    int try = 0;
    // Send a SIGINT first, and give it a couple of seconds
    ret = kill_processes("-INT");
    while (ret == 0) {
        sleep(SHUTDOWN_GRACE_TIME);
        if (try > MAX_KILL_ATTEMPTS) {
            ERROR("Gave up killing user processes");
            break;  // continue to cleanup with best effort
        }
        ret = kill_processes("-KILL");
        try++;
    }

    // Delete all of the files owned by the user in ~user, /tmp, /var/tmp
    // We are currently in ~user.
    // (Note by @mpandya: the find binary is in /bin in RHEL but in /usr/bin
    // in Ubuntu)
    char *find_args[] = {"find", "/usr/bin/find", ".", "/tmp", "/var/tmp", "-user", 
        args.user_info.pw_name, "-delete", NULL};
    if (call_program("/usr/bin/env", find_args) != 0) {
        ERROR("Error deleting user's files");
        exit(EXIT_OSERROR);
    }
}

/**
 * @brief Monitors the progression of the child
 *
 * SIGCHLD must be blocked when this function is called.
 *
 * @arg child PID of the child process
 * @arg arguments Pointer to argument struct
 *
 * @return Does not return
 */
static int monitor_child(pid_t child) {
    int killed = 0;
    int status;

    // create a thread for for file size tracking by time interval
    pthread_t timestampThread = 0;  // this thread needs no cancellation
    if (args.timestamp_interval) {
      if (pthread_create(&timestampThread, NULL, timestampFunc, NULL)) {
        ERROR_ERRNO("Failed to create timestamp thread");
        exit(EXIT_OSERROR);
      }
    }

    // Handle the timeout if we have to
    if (args.timeout != 0) {
        struct timespec timeout;
        timeout.tv_sec = args.timeout;
        timeout.tv_nsec = 0;

        sigset_t sigset;
        sigemptyset(&sigset);
        sigaddset(&sigset, SIGCHLD);

        if (sigtimedwait(&sigset, NULL, &timeout) < 0) {
            // Child timed out
            ERROR_ERRNO("Job timed out after %d seconds\n", args.timeout);
            assert(errno == EAGAIN);
            kill(child, SIGKILL);
            killed = 1;
        }
    }

    if (waitpid(child, &status, 0) < 0) {
        ERROR_ERRNO("Error reaping child");
        exit(EXIT_OSERROR);
    }

    MESSAGE("Duration of test is %lu seconds", time(NULL) - startTime);

    if (!killed) {
        MESSAGE("Job exited with status %d", WEXITSTATUS(status));
    }

    if (args.timestamp_interval > 0) {
      MESSAGE("Timestamps inserted at %d-second or larger intervals, depending output rates",
              args.timestamp_interval);
    }
    dump_output();
    cleanup();
    exit(killed ? EXIT_TIMEOUT : EXIT_SUCCESS);
}

/**
 * @brief Sets up the environment for the autograding job and then runs it.
 *
 * Permission dropping method adaped from http://tinyurl.com/6wgacq6
 *
 * @arg arguments Pointer to struct containing arguments
 *
 * @return Does not return
 */
static void run_job(void) {
    // Unblock signals
    sigset_t sigset;
    sigemptyset(&sigset);
    sigaddset(&sigset, SIGCHLD);
    sigprocmask(SIG_UNBLOCK, &sigset, NULL);

    // Set ulimits
    if (args.nproc != 0) {
        struct rlimit rlimit = {args.nproc, args.nproc};
        if (setrlimit(RLIMIT_NPROC, &rlimit) < 0) {
            perror("Error setting process limit");
            exit(EXIT_OSERROR);
        }
    }

    if (args.fsize != 0) {
        struct rlimit rlimit = {args.fsize, args.fsize};
        if (setrlimit(RLIMIT_FSIZE, &rlimit) < 0) {
            ERROR_ERRNO("Error setting filesize limit");
            exit(EXIT_OSERROR);
        }
    }

    // Drop permissions
    if (initgroups(args.user_info.pw_name, args.user_info.pw_gid) < 0) {
        ERROR_ERRNO("Error setting supplementary group IDs");
        exit(EXIT_OSERROR);
    }

    if (setresgid(args.user_info.pw_gid, args.user_info.pw_gid,
            args.user_info.pw_gid) < 0) {
        ERROR_ERRNO("Error setting group ID");
        exit(EXIT_OSERROR);
    }

    if (setresuid(args.user_info.pw_uid, args.user_info.pw_uid,
            args.user_info.pw_uid) < 0) {
        ERROR_ERRNO("Error setting user ID");
        exit(EXIT_OSERROR);
    }

    // Redirect output
    int fd = child_output_fd;

    if (dup2(fd, STDOUT_FILENO) < 0) {
        ERROR_ERRNO("Error redirecting standard output");
        exit(EXIT_OSERROR);
    }

    if (dup2(fd, STDERR_FILENO) < 0) {
        ERROR_ERRNO("Error redirecting standard error");
        exit(EXIT_OSERROR);
    }

    if (close(fd) < 0) {
        ERROR_ERRNO("Error closing output file by child process");
        exit(EXIT_OSERROR);
    }

    // Switch into the folder
    if (chdir(args.directory) < 0) {
        ERROR_ERRNO("Error changing directory");
        exit(EXIT_OSERROR);
    }

    // Finally exec job
    execl("/usr/bin/make", "make", NULL);
    ERROR_ERRNO("Error executing make");
    exit(EXIT_OSERROR);
}

int main(int argc, char **argv) {
    // Argument defaults
    args.nproc = 0;
    args.fsize = 0;
    args.timeout = 0;
    args.osize = 0;
    args.timestamp_interval = 0;
    args.timezone = NULL;
    startTime = time(NULL);

    // Make sure this isn't being run as root
    if (getuid() == 0) {
        ERROR("Autodriver should not be run as root");
        exit(EXIT_USAGE);
    }

    // Pull info for grading user
    if (parse_user(GRADING_USER, &args.user_info, &args.passwd_buf) < 0) {
        ERROR("Invalid grading user");
        exit(EXIT_OSERROR);
    }
    if (args.user_info.pw_uid == getuid()) {
        ERROR("This should not be run as the grading user " GRADING_USER);
        exit(EXIT_USAGE);
    }

    struct argp_option options[] = {
        {"nproc", 'u', "number", 0, 
            "Limit the number of processes the user is allowed", 0},
        {"fsize", 'f', "size", 0,
            "Limit the maximum file size a user can create (bytes)", 0},
        {"timeout", 't', "time", 0,
            "Limit the amount of time a job is allowed to run (seconds)", 0},
        {"osize", 'o', "size", 0,
            "Limit the amount of output returned (bytes)", 0},
        {"timestamp-interval", 'i', "interval", 0,
            "Interval (seconds) for placing timestamps in user output file", 0},
        {"timezone", 'z', "timezone", 0,
            "Timezone setting. Default is UTC", 0},
        {0, 0, 0, 0, 0, 0}
    };

    struct argp parser = {options, parse_opt, "DIRECTORY", 
        "Manages autograding jobs", NULL, NULL, NULL};

    argp_parse(&parser, argc, argv, 0, NULL, &args);

    // set time zone preference: -z argument, TZ environment variable, system wide
    if (args.timezone) {
      char tz[100];
      strcpy(tz, "TZ=");
      strcat(tz, args.timezone);
      putenv(tz);
    }
    tzset();
    MESSAGE("Time zone %s:%s", tzname[0], tzname[1]);

    setup_dir();

    // Block SIGCHLD to make sure monitor_child recieves it.
    sigset_t sigset;
    sigemptyset(&sigset);
    sigaddset(&sigset, SIGCHLD);
    sigprocmask(SIG_BLOCK, &sigset, NULL);

    if ((child_output_fd = open(OUTPUT_FILE, O_WRONLY | O_CREAT | O_TRUNC | O_SYNC,
                   S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH)) < 0) {
        ERROR_ERRNO("Error creating output file");
        exit(EXIT_OSERROR);
    }

    pid_t pid = fork();
    if (pid < 0) {
        ERROR_ERRNO("Unable to fork");
        exit(EXIT_OSERROR);
    } else if (pid == 0) {
        run_job();
    } else {
        if (close(child_output_fd) < 0) {
            ERROR_ERRNO("Error closing output file by parent process");
            // don't quit for this type of error
        }

        // open output file read only to build timestamp:offset map
        if ((parent_output_fd = open(OUTPUT_FILE, O_RDONLY)) < 0) {
          ERROR_ERRNO("Error opening output file by parent process");
          // don't quit for this type of error
        }

        monitor_child(pid);
    }

    return 0;
}
