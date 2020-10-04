# Autolab Docker Deployment

## Setup Instructions
First ensure that you have Docker installed on your machine.

1. Clone this repository and its submodules: `git clone --recurse-submodules -j8 git://github.com/autolab/docker.git autolab-docker`
2. Enter the project directory: `cd autolab-docker`
3. Create initial configs: `make`
4. Build the Dockerfiles: `docker-compose build`
5. Run the containers: `docker-compose up`
6. Perform migrations: `make db-migrate`
7. Create initial root user: `make create-root`
