FROM ubuntu:24.04

# Install compilation tools and the 'time' utility Tango uses
RUN apt-get update && apt-get install -y build-essential time

RUN useradd -m autolab
RUN useradd -m autograde

# Copy local autodriver source code into the container
COPY . /opt/autodriver

# Compile the autodriver directly, bypassing the legacy Makefile
RUN cd /opt/autodriver && gcc -W -Wall -Wextra -o /usr/bin/autodriver autodriver.c

RUN chown root:root /usr/bin/autodriver
RUN chmod +s /usr/bin/autodriver