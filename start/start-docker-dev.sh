#!/usr/bin/env sh
dockerd &
docker pull autolabproject/autograding_image
python restful-tango/server.py 3001 &
python jobManager.py