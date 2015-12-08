# Start with empty ubuntu machine
FROM ubuntu:14.04

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variable
ENV HOME /root

# Change to working directory
WORKDIR /opt

# Move all code into Tango directory
ADD . TangoService/Tango/

# Install dependancies
# supervisor installed and works


RUN apt-get update && apt-get install -y \
	nginx \
	curl \
    supervisor \
    build-essential \
    tcl8.5 \
    wget \
    libgcrypt11-dev \ 
    zlib1g-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

ENV PATH /usr/local/nginx/sbin/ngnix:$PATH

# DONE

RUN wget http://download.redis.io/releases/redis-stable.tar.gz && tar xzf redis-stable.tar.gz
WORKDIR /opt/redis-stable
RUN make && make install 
WORKDIR /

# Move custom config file to proper location
RUN cp /opt/TangoService/Tango/docker/config/nginx.conf /etc/nginx/nginx.conf
RUN cp /opt/TangoService/Tango/docker/config/supervisord.conf /etc/supervisor/supervisord.conf

# Reload new config scripts
RUN service nginx restart
RUN service supervisor stop && service supervisor start


