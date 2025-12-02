# Start with empty ubuntu machine
FROM ubuntu:20.04

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
	tcl8.6 \
	wget \
	libgcrypt20-dev \
	zlib1g-dev \
	apt-transport-https \
	ca-certificates \
	lxc \
	iptables \
	iputils-ping \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/TangoService/Tango/

# Install Docker
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    . /etc/os-release; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; \
    apt-get clean; rm -rf /var/lib/apt/lists/*

# Install the magic wrapper.
ADD ./wrapdocker /usr/local/bin/wrapdocker
RUN chmod +x /usr/local/bin/wrapdocker

# Define additional metadata for our image.
VOLUME /var/lib/docker

WORKDIR /opt

# Create virtualenv to link dependancies
RUN pip3 install virtualenv && virtualenv .

WORKDIR /opt/TangoService/Tango

# Add in requirements
COPY requirements.txt .

# Install python dependancies
RUN pip3 install -r requirements.txt

# Move all code into Tango directory
COPY . .
RUN mkdir -p volumes

RUN mkdir -p /var/log/docker /var/log/supervisor

# Move custom config file to proper location
RUN cp /opt/TangoService/Tango/deployment/config/nginx.conf /etc/nginx/nginx.conf
RUN cp /opt/TangoService/Tango/deployment/config/supervisord.conf /etc/supervisor/supervisord.conf
RUN if [ -f /opt/TangoService/Tango/boto.cfg ]; then cp /opt/TangoService/Tango/boto.cfg ~/.boto; fi

# Set up PYTHONPATH
ENV PYTHONPATH="/opt/TangoService/Tango"

# Reload new config scripts
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
