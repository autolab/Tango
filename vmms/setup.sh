#!/bin/bash
#
# This script is to set up a shark machine to host docker
# containers for autograding. System must be running ubuntu 
# kernel version 3.13 or higher. Check with `uname -r`
#
# Run as root

wget -qO- https://get.docker.com/ | sh
adduser autolab
usermod -aG docker autolab
mkdir /home/autolab/volumes/
mkdir /home/autolab/.ssh
# Append greatwhite:/usr/share/mpandyaAutolab/Tango/vmms/id_rsa.pub to
# host:/home/autolab/.ssh/authorized_keys
# Make docker image called `rhel`
