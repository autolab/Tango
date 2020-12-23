# Autolab - autograding docker image

FROM ubuntu:18.04
MAINTAINER Autolab Team <autolab-dev@andrew.cmu.edu>

RUN apt-get update && apt-get install -y \
  build-essential \
  gcc \
  git \
  make \
  sudo \
  && rm -rf /var/lib/apt/lists/*

# Install autodriver
WORKDIR /home
RUN useradd autolab
RUN useradd autograde
RUN mkdir autolab autograde output
RUN chown autolab:autolab autolab
RUN chown autolab:autolab output
RUN chown autograde:autograde autograde
RUN git clone --depth 1 https://github.com/autolab/Tango.git
WORKDIR Tango/autodriver
RUN make clean && make
RUN cp autodriver /usr/bin/autodriver
RUN chmod +s /usr/bin/autodriver

# Clean up
WORKDIR /home
RUN apt-get remove -y git && apt-get -y autoremove && rm -rf Tango/

# Check installation
RUN ls -l /home
RUN which autodriver
