# Start with empty ubuntu machine
FROM ubuntu:18.04

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variable
ENV HOME /root

# Change to working directory
WORKDIR /opt

# To avoid having a prompt on tzdata setup during installation
ENV DEBIAN_FRONTEND=noninteractive 

RUN chmod 1777 /tmp

# Install dependancies
RUN apt-get update && apt-get install -y \
	nginx \
	curl \
	git \
	vim \
	supervisor \
	python3 \
	python3-pip \
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

WORKDIR /opt/TangoService/Tango/

# Install Docker from Docker Inc. repositories.
RUN curl -sSL https://get.docker.com/ | sh

# Install the magic wrapper.
ADD ./wrapdocker /usr/local/bin/wrapdocker
RUN chmod +x /usr/local/bin/wrapdocker

# Define additional metadata for our image.
VOLUME /var/lib/docker

WORKDIR /opt

# Move all code into Tango directory
ADD . TangoService/Tango/
WORKDIR /opt/TangoService/Tango
RUN mkdir -p volumes

# Create virtualenv to link dependancies
RUN pip3 install virtualenv && virtualenv .
# Install python dependancies
RUN pip3 install -r requirements.txt

RUN mkdir -p /var/log/docker /var/log/supervisor

# Move custom config file to proper location
RUN cp /opt/TangoService/Tango/deployment/config/nginx.conf /etc/nginx/nginx.conf
RUN cp /opt/TangoService/Tango/deployment/config/supervisord.conf /etc/supervisor/supervisord.conf

# Reload new config scripts
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
