/* Test program that exceeds the memory on the VM */

/* 1GB array */
#define SIZE 1000*1024*1024

char array[SIZE];

int main() 
{
   int i;

   for (i=0; i<SIZE; i++)
       array[i] = 0; 
   return 0;
}
