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
#include <pthread.h>

int filedes[2];

void childFunc() {
  int i;
  char j;
  char buffer[10000];
  for (i = 0; i < 1000; i++) {
    for (j = '0'; j <= '9'; j++) {
      buffer[ i * 10 + (j - '0') ] = j;
    }
  }
  buffer[9999] = '\0';
  printf("%s", buffer);
    
  /*
  for (i = 0; i < 5; i++) {
    system("date");
    fprintf(stdout, "stdout in child\n");
    int eol = rand() % 2;  // boolean
    if (eol) {
      fprintf(stderr, "stderr with eol in child\n");
    } else {
      fprintf(stderr, "stderr without eol in child");
    }
    //sleep(3);
  }
  */
  
  _exit(1);
}

void* readFunc() {
  char buffer[70];

  int timestampAfterNextRead = 1;  // boolean
  while (1) {
    memset(&buffer[0], 0, sizeof(buffer));
    ssize_t count = read(filedes[0], buffer, sizeof(buffer) - 1);

    
    if (count == -1) {
      if (errno == EINTR) {
        continue;
      } else {
        perror("read");
        exit(1);
      }
    } else if (count == 0) {
      fprintf(stderr, "exit \n");      
      break;
    } else {
      // int insertNull = rand() % 2;  // boolean
      // int insertIndex = rand() % count;
      int processedCount = 0;
      int addTimestamp = timestampAfterNextRead;

      fprintf(stderr, "\n====================================\n");
      fprintf(stderr, "### read %lu bytes: \"%s\"\n", count, buffer);
      timestampAfterNextRead = (buffer[count - 1] == '\n');  // boolean

      /*
      fprintf(stderr, "### random insert index %d %d, \"%s\", \"%s\"\n",
             insertNull, insertIndex, buffer, &buffer[insertIndex]);
      if (insertNull) {
        buffer[insertIndex] = '\0';
      }
      */
      
      char *result = strtok(buffer, "\n");
      while (1) {
        if (!result) {
          if (processedCount < count) {  // must have seen a NULL
            if (!buffer[processedCount]) {
              processedCount++;
            }
            addTimestamp = 1;  // null is dealt like \n
            result = strtok(&buffer[processedCount], "\n");
            fprintf(stderr, "### processed after null \"%s\"\n", &buffer[processedCount]);
            continue;
          }
          break;
        }

        fprintf(stderr, "### result \"%s\" %lu, \"%s\"\n", result, strlen(result),
                &buffer[processedCount]);
        processedCount += strlen(result) + 1;
        char *eol = (processedCount >= count && !timestampAfterNextRead) ? "" : "\n";
        fprintf(stderr, (eol[0] == '\n') ? "Add eol\n" : "Not add eol\n");

        assert(processedCount <= count + 1);
      
        time_t ltime = time(NULL);
        struct tm* tmInfo = localtime(&ltime);
        char timeStr[100];
        if (addTimestamp) {
          strftime(timeStr, 100, "%Y%m%d-%H:%M:%S", tmInfo);
          printf("%s: \"%s\"%s", timeStr, result, eol);
        } else {
          printf("\"%s\"%s", result, eol);
        }

        addTimestamp = 1;
        result = strtok(NULL, "\n");
      }

      addTimestamp = (buffer[count - 1] == '\n');  // boolean
    }
  }
  return NULL;
}

int main() {
  putenv("TZ=America/New_York");
  tzset();
  
  if (pipe(filedes) == -1) {
    perror("pipe");
    exit(1);
  }

  pid_t pid = fork();
  if (pid == -1) {
    perror("fork");
    exit(1);
  } else if (pid == 0) {
    setvbuf(stdout, NULL, _IONBF, 0);
    while ((dup2(filedes[1], STDOUT_FILENO) == -1) && (errno == EINTR)) {}
    while ((dup2(filedes[1], STDERR_FILENO) == -1) && (errno == EINTR)) {}    
    close(filedes[1]);
    close(filedes[0]);
    childFunc();
  }

  // parent process comes here
  pthread_t readThread;

  /* create a second thread which executes inc_x(&x) */
  if(pthread_create(&readThread, NULL, readFunc, NULL)) {
    perror("create thread");
    exit(1);
  }

  /*
    result = waitpid(pid, &status, WNOHANG);
    if (result == 0) {
      printf("child done\n");
      break;
    } else if (result < 0) {
      perror("waitpid");
      exit(1);
    }
    printf("wait pid %d\n", result);
  */

  {
    int status;
    wait(&status);

    sleep(10);
    
    status = pthread_cancel(readThread);
    close(filedes[0]);
  }
}
