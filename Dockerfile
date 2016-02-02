# Start with empty ubuntu machine
FROM ubuntu:15.04

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variable
ENV HOME /root

# Change to working directory
WORKDIR /opt

# Move all code into Tango directory
ADD . TangoService/Tango/
RUN mkdir /volumes

# Install dependancies
# supervisor installed and works


RUN apt-get update && apt-get install -y \
	nginx \
	curl \
	git \
    vim \
    supervisor \
    python-pip \
    python-dev \
    build-essential \
    tcl8.5 \
    wget \
    libgcrypt11-dev \ 
    zlib1g-dev \
	apt-transport-https \
    ca-certificates \
    lxc \
    iptables \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

ENV PATH /usr/local/nginx/sbin/ngnix:$PATH

RUN wget http://download.redis.io/releases/redis-stable.tar.gz && tar xzf redis-stable.tar.gz
WORKDIR /opt/redis-stable
RUN make && make install 
WORKDIR /opt/TangoService/Tango/

# Install Docker from Docker Inc. repositories.
RUN curl -sSL https://get.docker.com/ | sh

# Install the magic wrapper.
ADD ./wrapdocker /usr/local/bin/wrapdocker
RUN chmod +x /usr/local/bin/wrapdocker

# Define additional metadata for our image.
VOLUME /var/lib/docker
CMD ["wrapdocker"]

# Create virtualenv to link dependancies 
RUN pip install virtualenv && virtualenv .
# Install python dependancies 
RUN pip install -r requirements.txt

# Move custom config file to proper location
RUN cp /opt/TangoService/Tango/deployment/config/nginx.conf /etc/nginx/nginx.conf
RUN cp /opt/TangoService/Tango/deployment/config/supervisord.conf /etc/supervisor/supervisord.conf
RUN cp /opt/TangoService/Tango/deployment/config/redis.conf /etc/redis.conf


# Reload new config scripts
RUN service nginx start
RUN service supervisor start


# TODO: 
# volumes dir in root dir, supervisor only starts after calling start once , nginx also needs to be started
# Different log numbers for two different tangos
# what from nginx forwards requests to tango
# why does it still start on 3000
