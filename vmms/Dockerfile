# Autolab - autograding docker image

FROM ubuntu:14.04
MAINTAINER Mihir Pandya <mihir.m.pandya@gmail.com>

RUN apt-get update
RUN apt-get install -y gcc
RUN apt-get install -y make
RUN apt-get install -y build-essential
RUN apt-get install -y wget

# Install autodriver
WORKDIR /home
RUN useradd autolab
RUN useradd autograde
RUN mkdir autolab autograde output
RUN chown autolab:autolab autolab
RUN chown autolab:autolab output
RUN chown autograde:autograde autograde
RUN apt-get install -y git
RUN git clone https://github.com/autolab/Tango.git
WORKDIR Tango/autodriver
RUN make clean && make
RUN cp autodriver /usr/bin/autodriver
RUN chmod +s /usr/bin/autodriver

# Install C0
WORKDIR /home
RUN wget http://c0.typesafety.net/dist/cc0-v0440-linux3.18.1-64bit-bin.tgz
RUN tar -xvzf cc0-*
WORKDIR /home/cc0
RUN bin/cc0 -d doc/src/exp.c0 doc/src/exp-test.c0
RUN ./a.out
RUN cp bin/cc0 /usr/bin/cc0

# Clean up
WORKDIR /home
RUN apt-get remove -y git
RUN apt-get remove -y wget
RUN apt-get -y autoremove
RUN rm -rf Tango/
RUN rm -f cc0-*
RUN rm -rf cc0/

# Check installation
RUN ls -l /home
RUN which autodriver
RUN which cc0