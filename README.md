# Autolab Docker Deployment

## Setup Instructions
First ensure that you have Docker installed on your machine.

1. Clone this repository and its submodules: `git clone --recurse-submodules -j8 git://github.com/autolab/docker.git autolab-docker`
2. Enter project directory: `cd autolab-docker`
3. Build the Dockerfiles: `docker-compose build`
4. Run the initial setup script: `./setup.sh`
5. Run the containers: `docker-compose up`
