#!/bin/bash
#
# TangoREST dependencies have to be added to the PATH.
#
source $PWD/scripts/sourcelib;

while [ 1 ]; do
	python $PWD/restful-tango/server.py
done
