/* Test program that sleeps for a while and then prints a message. */
#include <stdio.h>
#include<unistd.h>

int main()
{
   int i;

   for (i=0; i<30; i++){
        printf("This is line number %d \n", i);
        fflush(stdout);
        sleep(1);
   }
   return 0;
}
