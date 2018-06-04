# Start with empty ubuntu machine
FROM ubuntu:16.04

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variable
ENV HOME /root

# Change to working directory
WORKDIR /opt

# Move all code into Tango directory
ADD . TangoService/Tango/
WORKDIR /opt/TangoService/Tango
RUN mkdir volumes

WORKDIR /opt
#RUN sed -i -re 's/([a-z]{2}\.)?archive.ubuntu.com|security.ubuntu.com/old-releases.ubuntu.com/g' /etc/apt/sources.list
# Install dependancies
RUN apt-get update && apt-get dist-upgrade -y && DEBIAN_FRONTEND=nointeractive apt-get install -y \
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

# Install Redis
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

# Create virtualenv to link dependancies 
RUN pip install virtualenv && virtualenv .
# Install python dependancies 
RUN pip install -r requirements.txt

RUN mkdir -p /var/log/docker /var/log/supervisor

# Move custom config file to proper location
RUN cp /opt/TangoService/Tango/deployment/config/nginx.conf /etc/nginx/nginx.conf
RUN cp /opt/TangoService/Tango/deployment/config/supervisord.conf /etc/supervisor/supervisord.conf
RUN cp /opt/TangoService/Tango/deployment/config/redis.conf /etc/redis.conf

# Reload new config scripts
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]

CMD ["/usr/bin/supervisord"]
# TODO: 
# volumes dir in root dir, supervisor only starts after calling start once , nginx also needs to be started
# Different log numbers for two different tangos
# what from nginx forwards requests to tango
# why does it still start on 3000
