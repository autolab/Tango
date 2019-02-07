#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <time.h>
#include <string.h>

int main() {
  srand((unsigned)time(NULL));
  putenv("TZ=America/New_York");
  tzset();

  int i, k;
  char timeStr[100];
  for (k = 0; k < 100; k++) {  
    for (i = 0; i < 200; i++) {
      time_t ltime = time(NULL);
      struct tm* tmInfo = localtime(&ltime);
      strftime(timeStr, 100, "%Y%m%d-%H:%M:%S", tmInfo);
      printf("TIME: \"%s\" followed by 3 lines of random lenth\n", timeStr);
      int j;
      for (j = 0; j < 3; j++) {
        int lineLength = rand() % 2000;  // longer than autodriver's buf size
        int count = 0;
        char line[81];
        memset(line, 0, 81);
        while (count < lineLength) {
          line[count] = '0' + count % 10;
          count++;
        }
        printf("%s\n", line);
      }
    }
    sleep(1);
  }
  sleep(5);
  exit(0);
}
