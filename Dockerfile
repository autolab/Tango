# Start with empty ubuntu machine
FROM ubuntu:20.04

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variables
ENV HOME=/root
ENV DEBIAN_FRONTEND=noninteractive

# Change to working directory
WORKDIR /opt

RUN chmod 1777 /tmp

# Install dependencies
# Bootstrap CA certs over HTTPS without verification once, then use normal verified HTTPS
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/*passenger*; \
    sed -i 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list; \
    sed -i 's|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' /etc/apt/sources.list; \
    apt-get -o Acquire::https::Verify-Peer=false -o Acquire::https::Verify-Host=false update; \
    apt-get -o Acquire::https::Verify-Peer=false -o Acquire::https::Verify-Host=false install -y --no-install-recommends ca-certificates; \
    update-ca-certificates; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        sqlite3 \
        tzdata \
        shared-mime-info \
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
        lxc \
        iptables \
        iputils-ping \
        openssh-client \
        gnupg; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/TangoService/Tango/

# Install Docker from Docker Inc. repositories.
RUN set -eux; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    . /etc/os-release; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      docker-ce \
      docker-ce-cli \
      containerd.io \
      docker-buildx-plugin \
      docker-compose-plugin; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Install the magic wrapper.
ADD ./wrapdocker /usr/local/bin/wrapdocker
RUN chmod +x /usr/local/bin/wrapdocker

# Define additional metadata for our image.
VOLUME /var/lib/docker

WORKDIR /opt

# Create virtualenv to link dependencies
RUN pip3 install virtualenv && virtualenv .

WORKDIR /opt/TangoService/Tango

# Add in requirements
COPY requirements.txt .

# Install python dependencies
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
ENV PYTHONPATH=/opt/TangoService/Tango

# Reload new config scripts
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]