# Start with empty ubuntu machine
FROM ubuntu

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variable
ENV HOME /root

RUN mkdir -p /opt/TangoFiles/volumes /opt/TangoFiles/courselabs /opt/TangoFiles/output

# Install dependancies
RUN apt-get update && apt-get install -y \
	nginx \
	curl \
	git \
    iputils-ping \
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
WORKDIR /opt
RUN wget http://download.redis.io/releases/redis-stable.tar.gz && tar xzf redis-stable.tar.gz
WORKDIR /opt/redis-stable
RUN make && make install

# Install the magic wrapper.
ADD ./wrapdocker /usr/local/bin/wrapdocker
RUN chmod +x /usr/local/bin/wrapdocker

# Define additional metadata for our image.
VOLUME /var/lib/docker

# Install python dependancies
ADD ./requirements.txt /opt/TangoFiles/requirements.txt
WORKDIR /opt/TangoFiles
RUN pip install virtualenv && virtualenv .
RUN pip install -r requirements.txt
RUN pip install pytz

RUN mkdir -p /var/log/docker /var/log/supervisor

# Move custom config file to proper location
ADD ./deployment/config/nginx.conf /etc/nginx/nginx.conf
ADD ./deployment/config/supervisord.conf /etc/supervisor/supervisord.conf
ADD ./deployment/config/redis.conf /etc/redis.conf

#JMB added for EC2 config
ADD ./deployment/config/boto.cfg /etc/boto.cfg
ADD ./deployment/config/746-autograde.pem /root/746-autograde.pem
RUN chmod 600 /root/746-autograde.pem

# Reload new config scripts
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]

# TODO:
# volumes dir in root dir, supervisor only starts after calling start once , nginx also needs to be started
# Different log numbers for two different tangos
# what from nginx forwards requests to tango
# why does it still start on 3000
