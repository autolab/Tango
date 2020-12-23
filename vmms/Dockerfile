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
RUN useradd autolab \
  && useradd autograde \
  && mkdir autolab autograde output \
  && chown autolab:autolab autolab \
  && chown autolab:autolab output \
  && chown autograde:autograde autograde

RUN git clone --depth 1 https://github.com/autolab/Tango.git
WORKDIR /home/Tango/autodriver
RUN make clean && make
RUN cp autodriver /usr/bin/autodriver
RUN chmod +s /usr/bin/autodriver

# Clean up
WORKDIR /home
RUN apt-get remove -y git && apt-get -y autoremove && rm -rf Tango/

# Check installation
RUN ls -l /home
RUN which autodriver
