CC = gcc
CFLAGS = -W -Wall -Wextra

OBJS = output_gen.o

all: output_gen run_output_gen

output_gen: $(OBJS)
	$(CC) $(LDFLAGS) -o output_gen $(OBJS)

clean:
	rm -f *.o output_gen

.PHONY: clean

run_output_gen:
	output_gen
