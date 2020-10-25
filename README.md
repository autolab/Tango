# Autolab Docker Deployment

## Setup Instructions
First ensure that you have Docker installed on your machine.

1. Clone this repository and its submodules: `git clone --recurse-submodules -j8 git://github.com/autolab/docker.git autolab-docker`
2. Enter the project directory: `cd autolab-docker`
3. Update submodules: `make update`
4. Create initial configs: `make`
5. Build the Dockerfiles: `docker-compose build`
6. Run the containers: `docker-compose up`
7. Ensure that the newly created config files have the right permissions: `make set-perms`
8. Perform migrations: `make db-migrate`
9. Create initial root user: `make create-user`
