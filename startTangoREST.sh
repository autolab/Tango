#!/bin/bash
#
# TangoREST dependencies have to be added to the PATH.
#
source $PWD/scripts/sourcelib;
pid=`ps -A -o pid,cmd| grep server | grep -v grep |head -n 1 | awk '{print $1}'`
kill $pid
python $PWD/restful-tango/server.py &
