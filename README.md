# Autolab Docker Deployment

## Setup Instructions
First ensure that you have Docker installed on your machine.

1. Clone this repository and its submodules: `git clone --recurse-submodules -j8 git://github.com/autolab/docker.git autolab-docker`
2. Enter the project directory: `cd autolab-docker`
3. Update submodules: `make update`
4. Create initial configs: `make`
5. Build the Dockerfiles: `docker-compose build`
6. Run the containers: `docker-compose up -d`
7. Ensure that the newly created config files have the right permissions: `make set-perms`
8. Perform migrations: `make db-migrate`
9. Create initial root user: `make create-user`
10. Perform SSL setup. 
11a. Option 1 with Let's Encrypt:
    1. Ensure that your DNS record points towards the IP address of your server
    2. Ensure that port 443 is exposed on your server (i.e checking your firewall, AWS security group settings, etc)
    3.  Get initial SSL setup script: `make ssl`
    4. In `ssl/init-letsencrypt.sh`, change `domains=(example.com)` to the list of domains that your host is associated with, and change `email` to be your email address so that Let's Encrypt will be able to email you when your certificate is about to expire
    5. If necessary, change `staging=0` to `staging=1` to avoid being rate-limited by Let's Encrypt since there is a limit of 20 certificates/week. Setting this is helpful if you have an experimental setup.
    6. Stop your containers: `docker-compose stop`
    7. Run your modified script: `sudo sh ./ssl/init-letsencrypt.sh`
11b. Option 2 with your own SSL certificate:
    1. Copy your private key to ./ssl/privkey.pem
    2. Copy your certificate to ./ssl/fullchain.pem
    3. Uncomment the following lines in `docker-compose.yml`:
      > # - ./ssl/fullchain.pem:/etc/letsencrypt/live/test.autolab.io/fullchain.pem;
      > # - ./ssl/privkey.pem:/etc/letsencrypt/live/test.autolab.io/privkey.pem;
12. Start up everything: `docker-compose up -d`

## Future Start-up Instructions
After you have done your initial set-up, you can start your containers up again by simply running `docker-compose up -d`. 

