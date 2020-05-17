CC = gcc
CFLAGS = -W -Wall -Wextra

OBJS = autodriver.o

all: autodriver

autodriver: $(OBJS)
	$(CC) -o autodriver $(OBJS) $(LDFLAGS)

autodriver.o: autodriver.c

clean:
	rm -f *.o autodriver

.PHONY: clean
