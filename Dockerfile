# Start with empty ubuntu machine
FROM ubuntu:24.04

MAINTAINER Autolab Development Team "autolab-dev@andrew.cmu.edu"

# Setup correct environment variable
ENV HOME /root

# Change to working directory
WORKDIR /opt

# To avoid having a prompt on tzdata setup during installation
ENV DEBIAN_FRONTEND=noninteractive

RUN chmod 1777 /tmp

# Install dependencies
RUN apt-get update && apt-get install -y \
	nginx \
	curl \
	git \
	vim \
	supervisor \
	python3 \
	python3-venv \
	build-essential \
	tcl \
	wget \
	libgcrypt20-dev \
	zlib1g-dev \
	apt-transport-https \
	ca-certificates \
	lxc \
	iptables \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/TangoService/Tango/

# Install Docker from Docker Inc. repositories.
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

# Install the Docker daemon launcher.
COPY --chmod=0755 wrapdocker /usr/local/bin/wrapdocker

# Define additional metadata for our image.
VOLUME /var/lib/docker

RUN python3 -m venv /opt/tango-venv
ENV PATH="/opt/tango-venv/bin:${PATH}"

WORKDIR /opt/TangoService/Tango

# Add in requirements
COPY requirements.txt .

# Install Python dependencies in the same environment Supervisor will use.
RUN python -m pip install --no-cache-dir --upgrade pip==26.3 \
 && python -m pip install --no-cache-dir -r requirements.txt

# Move all code into Tango directory
COPY . .
RUN mkdir -p volumes

RUN mkdir -p /var/log/docker /var/log/supervisor

# Move custom config file to proper location
RUN cp /opt/TangoService/Tango/deployment/config/nginx.conf /etc/nginx/nginx.conf
RUN cp /opt/TangoService/Tango/deployment/config/supervisord.conf /etc/supervisor/supervisord.conf

# Reload new config scripts
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
