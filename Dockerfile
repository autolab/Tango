# Autolab - autograding docker image

FROM ubuntu:14.04
MAINTAINER Mihir Pandya <mihir.m.pandya@gmail.com>

RUN apt-get update
RUN apt-get install -y gcc
RUN apt-get install -y make
RUN apt-get install -y build-essential

# Install autodriver
WORKDIR /home
RUN useradd autolab
RUN mkdir autolab
RUN chown autolab autolab
RUN chown :autolab autolab
RUN mkdir output
RUN chown autolab output
RUN chown :autolab output
RUN useradd autograde
RUN mkdir autograde
RUN chown autograde autograde
RUN chown :autograde autograde
RUN apt-get install -y git
RUN git clone https://github.com/autolab/Tango.git
WORKDIR Tango/autodriver
RUN make clean && make
RUN cp autodriver /usr/bin/autodriver
RUN chmod +s /usr/bin/autodriver

# Clean up
WORKDIR /home
RUN apt-get remove -y git
RUN apt-get -y autoremove
RUN rm -rf Tango/

# Check installation
RUN ls -l /home
RUN which autodriver