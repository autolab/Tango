# Autolab - autograding docker image

FROM ubuntu:16.04
MAINTAINER David Dobmeier <daviddob@buffalo.edu>

#C++ Setup
RUN apt-get update
RUN apt-get install -y gcc
RUN apt-get install -y make
RUN apt-get install -y build-essential

#Python Setup
RUN apt-get install -y python
RUN apt-get install -y python3

#Java Setup
RUN apt-get update --fix-missing
RUN apt-get install -y default-jdk

#Valgrind Setup
RUN apt-get update
RUN apt-get install -y valgrind

#SML Setup
RUN mkdir -p /usr/local/bin/sml
WORKDIR /usr/local/bin/sml
RUN apt-get install -y gcc-multilib g++-multilib lib32z1 lib32ncurses5 wget
RUN wget http://www.smlnj.org/dist/working/110.78/config.tgz
RUN tar -xzvf config.tgz
RUN config/install.sh
RUN ln -s /usr/local/bin/sml/bin/sml /usr/local/sbin/sml

#Utility setup
RUN apt-get install -y unzip

# Install autodriver
WORKDIR /home
RUN useradd autolab
RUN useradd autograde
RUN mkdir autolab autograde output
RUN chown autolab:autolab autolab
RUN chown autolab:autolab output
RUN chown autograde:autograde autograde
RUN apt-get update && apt-get install -y sudo 
RUN apt-get install -y git
RUN git clone https://github.com/autolab/Tango.git
WORKDIR Tango/autodriver
RUN make clean && make
RUN cp autodriver /usr/bin/autodriver
RUN chmod +s /usr/bin/autodriver

# Clean up
WORKDIR /home
RUN apt-get -y autoremove
RUN rm -rf Tango/

# Check installation
RUN ls -l /home
RUN which autodriver
RUN which javac
RUN which sml
RUN g++ --version
RUN echo 'export _JAVA_OPTIONS="-Xmx1024m -XX:ParallelGCThreads=1"' >> ~/.bashrc
