# Autolab - autograding docker image

FROM ubuntu:14.04
MAINTAINER Mihir Pandya <mihir.m.pandya@gmail.com>

RUN apt-get update && apt-get install -y build-essential wget

# Install autodriver
WORKDIR /home
RUN useradd autolab && useradd autograde
RUN mkdir autolab autograde output && chown autolab:autolab autolab output && chown autograde:autograde autograde
ADD . /home/autodriver
WORKDIR /home/autodriver
RUN make clean && make && install -c -o root -g root -m 4755 autodriver /usr/bin/autodriver && install -c -m 755 autograde_wrapper.py /usr/bin/autograde_wrapper
ENTRYPOINT ["/usr/bin/autograde_wrapper"]

# Install C0
WORKDIR /home
RUN wget http://c0.typesafety.net/dist/cc0-v0440-linux3.18.1-64bit-bin.tgz
RUN tar -xvzf cc0-*
WORKDIR /home/cc0
RUN bin/cc0 -d doc/src/exp.c0 doc/src/exp-test.c0
#RUN ./a.out
RUN cp bin/cc0 /usr/bin/cc0

# Clean up
WORKDIR /home
RUN apt-get remove -y wget && apt-get -y autoremove
RUN rm -rf autodriver cc0*

# Check installation
RUN ls -l /home && which autodriver && which cc0
