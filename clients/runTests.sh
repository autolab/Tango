#!/bin/bash

./tango.py --addjob --jobname job1 --makefile autograde-Makefile --infiles hello.sh
./tango.py --addjob --jobname job2 --makefile autograde-Makefile --infiles hello.sh
./tango.py --addjob --jobname job4 --makefile autograde-Makefile --infiles hello.sh
./tango.py --addjob --jobname job5 --makefile autograde-Makefile --infiles hello.sh
./tango.py --addjob --jobname job6 --makefile autograde-Makefile --infiles hello.sh
./tango.py --addjob --jobname job7 --makefile autograde-Makefile --infiles bug
