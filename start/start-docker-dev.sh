#!/usr/bin/env sh
dockerd &
docker build -t autograding_image $APP_PATH/vmms
python restful-tango/server.py 3001 &
python jobManager.py
