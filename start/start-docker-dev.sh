#!/usr/bin/env sh
dockerd &
docker build -t autograding_image $APP_PATH/vmms
python restful-tango/server.py &
python jobManager.py
