# Start with empty ubuntu machine
FROM ubuntu:14.04

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variable
ENV HOME /root

RUN mkdir /opt/TangoService

ADD . /opt/TangoService
