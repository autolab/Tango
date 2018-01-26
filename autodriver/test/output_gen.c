#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>

int main() {
  putenv("TZ=America/New_York");
  tzset();

  int i, k;
  char timeStr[100];
  for (k = 0; k < 100; k++) {  
    for (i = 0; i < 200; i++) {
      time_t ltime = time(NULL);
      struct tm* tmInfo = localtime(&ltime);
      strftime(timeStr, 100, "%Y%m%d-%H:%M:%S", tmInfo);
      printf("TIME: \"%s\"\n", timeStr);
      int j;
      for (j = 0; j < 10; j++) {
        printf("=%1d-0123456789", j);
      }
      printf("\n");
    }
    sleep(1);
  }
  sleep(5);
  exit(0);
}
