/* Test program that exceeds the memory on the VM */
#include <stdio.h>
#include<unistd.h>

int main()
{
   int i;

   for (i=0; i<10; i++){
        printf("Any text %d", i);
        fflush(stdout);
        sleep(1);
   }
   return 0;
}
