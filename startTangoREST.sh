#!/bin/bash
#
# TangoREST dependencies have to be added to the PATH.
#
source $PWD/scripts/sourcelib;

while [ 1 ]; do
	$PWD/tangoREST/server.py
done
