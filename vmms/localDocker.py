#
# localDocker.py - Implements the Tango VMMS interface to run Tango jobs in
#                docker containers. In this context, VMs are docker containers.
#
import random
import subprocess
import re
import time
import logging
import threading
import os
import sys
import shutil
import config
from tangoObjects import TangoMachine, InputFile
from typing import List, Literal, Optional
from vmms.interface import VMMSInterface
from vmms.sharedUtils import VMMSUtils


#
# User defined exceptions
#


class LocalDocker(VMMSInterface, VMMSUtils):
    def __init__(self):
        """Checks if the machine is ready to run docker containers.
        Initialize boot2docker if running on OS X.
        """
        try:
            self.log = logging.getLogger("LocalDocker")

            # Check import docker constants are defined in config
            if len(config.Config.DOCKER_VOLUME_PATH) == 0:
                raise Exception("DOCKER_VOLUME_PATH not defined in config.")

        except Exception as e:
            self.log.error(str(e))
            exit(1)

    def instanceName(self, id: int, name: str) -> str:
        return VMMSUtils.constructInstanceName(id, name)

    def getVolumePath(self, instanceName: str) -> str:
        volumePath = config.Config.DOCKER_VOLUME_PATH
        # Last empty string to cause trailing '/'
        volumePath = os.path.join(volumePath, instanceName, "")
        return volumePath

    def getDockerVolumePath(self, dockerPath: str, instanceName: str) -> str:
        # Last empty string to cause trailing '/'
        volumePath = os.path.join(dockerPath, instanceName, "")
        return volumePath

    def domainName(self, vm: TangoMachine) -> str:
        """Returns the domain name that is stored in the vm
        instance.
        """
        return vm.domain_name

    #
    # VMMS API functions
    #
    def initializeVM(self, vm: TangoMachine) -> Literal[0, -1]:
        """initializeVM -  Nothing to do for initializeVM"""
        return 0

    def waitVM(self, vm: TangoMachine, max_secs: int) -> Literal[0, -1]:
        """waitVM - Nothing to do for waitVM"""
        return 0

    def copyIn(
        self,
        vm: TangoMachine,
        inputFiles: List[InputFile],
        job_id: Optional[int] = None,
    ) -> int:
        """copyIn - Create a directory to be mounted as a volume
        for the docker containers. Copy input files to this directory.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)

        # Create a fresh volume
        os.makedirs(volumePath)
        for file in inputFiles:
            # Create output directory if it does not exist
            os.makedirs(os.path.dirname(volumePath), exist_ok=True)

            shutil.copy(file.localFile, volumePath + file.destFile)
            self.log.debug(
                "Copied in file %s to %s" % (file.localFile, volumePath + file.destFile)
            )
        return 0

    def runJob(
        self,
        vm: TangoMachine,
        runTimeout: int,
        maxOutputFileSize: int,
        disableNetwork: bool,
    ) -> int:
        """runJob - Run a docker container by doing the follows:
        - mount directory corresponding to this job to /home/autolab
          in the container
        - run autodriver with corresponding ulimits and timeout as
          autolab user
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)
        host_volume_path = os.getenv("DOCKER_TANGO_HOST_VOLUME_PATH")
        if host_volume_path:
            volumePath = self.getDockerVolumePath(host_volume_path, instanceName)
        args = ["docker", "run", "--name", instanceName, "-v"]
        args = args + ["%s:%s" % (volumePath, "/home/mount")]
        if vm.cores:
            args = args + [f"--cpus={vm.cores}"]
        if vm.memory:
            args = args + ["-m", f"{vm.memory}m"]
        if disableNetwork:
            args = args + ["--network", "none"]
        args = args + [vm.image]
        args = args + ["sh", "-c"]

        autodriverCmd = (
            "autodriver -u %d -f %d -t %d -o %d autolab > output/feedback 2>&1"
            % (
                config.Config.VM_ULIMIT_USER_PROC,
                config.Config.VM_ULIMIT_FILE_SIZE,
                runTimeout,
                config.Config.MAX_OUTPUT_FILE_SIZE,
            )
        )

        args = args + [
            'cp -r mount/* autolab/; su autolab -c "%s"; \
                        cp output/feedback mount/feedback'
            % autodriverCmd
        ]

        self.log.debug("Running job: %s" % str(args))
        ret = VMMSUtils.timeout(args, runTimeout * 2)
        self.log.debug("runJob returning %d" % ret)

        return ret

    def copyOut(self, vm: TangoMachine, destFile: str) -> int:
        """copyOut - Copy the autograder feedback from container to
        destFile on the Tango host. Then, destroy that container.
        Containers are never reused.
        """
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath(instanceName)
        shutil.move(volumePath + "feedback", destFile)
        self.log.debug("Copied feedback file to %s" % destFile)
        self.destroyVM(vm)

        return 0

    def destroyVM(self, vm: TangoMachine) -> None:
        """destroyVM - Delete the docker container."""
        instanceName = self.instanceName(vm.id, vm.image)
        volumePath = self.getVolumePath("")
        # Do a hard kill on corresponding docker container.
        # Return status does not matter.
        VMMSUtils.timeout(
            ["docker", "rm", "-f", instanceName], config.Config.DOCKER_RM_TIMEOUT
        )
        # Destroy corresponding volume if it exists.
        if instanceName in os.listdir(volumePath):
            shutil.rmtree(volumePath + instanceName)
            self.log.debug("Deleted volume %s" % instanceName)
        return

    def safeDestroyVM(self, vm: TangoMachine) -> None:
        """safeDestroyVM - Delete the docker container and make
        sure it is removed.
        """
        start_time = time.time()
        while self.existsVM(vm):
            if time.time() - start_time > config.Config.DESTROY_SECS:
                self.log.error("Failed to safely destroy container %s" % vm.name)
                return
            self.destroyVM(vm)
        return

    def getVMs(self) -> List[TangoMachine]:
        """getVMs - Executes and parses `docker ps`. This function
        is a lot of parsing and can break easily.
        """
        # Get all volumes of docker containers
        machines = []
        volumePath = self.getVolumePath("")
        for volume in os.listdir(volumePath):
            if re.match("%s-" % config.Config.PREFIX, volume):
                machine = TangoMachine()
                machine.vmms = "localDocker"
                machine.name = volume
                volume_l = volume.split("-")
                machine.id = volume_l[1]
                machine.image = volume_l[2]
                machines.append(machine)
        return machines

    def existsVM(self, vm: TangoMachine) -> bool:
        """existsVM - Executes `docker inspect CONTAINER`, which returns
        a non-zero status upon not finding a container.
        """
        instanceName = self.instanceName(vm.id, vm.name)
        ret = VMMSUtils.timeout(["docker", "inspect", instanceName])
        return ret == 0

    def getImages(self) -> List[str]:
        """getImages - Executes `docker images` and returns a list of
        images that can be used to boot a docker container with. This
        function is a lot of parsing and so can break easily.
        """
        result = set()
        cmd = "docker images"
        o = subprocess.check_output(cmd, shell=True).decode("utf-8")
        o_l = o.split("\n")
        o_l.pop()
        o_l.reverse()
        o_l.pop()
        for row in o_l:
            row_l = row.split(" ")
            result.add(re.sub(r".*/([^/]*)", r"\1", row_l[0]))
        return list(result)

    def getPartialOutput(self, vm: TangoMachine) -> str:
        """getPartialOutput - Get the partial output of a job.
        It does not check if the docker container exists before executing
        as the command will not fail even if the container does not exist.
        Gets the first MAX_OUTPUT_FILE_SIZE bytes of the feedback file
        """

        instanceName = self.instanceName(vm.id, vm.image)
        cmd = "docker exec %s head -c %s autograde/output.log" % (
            instanceName,
            config.Config.MAX_OUTPUT_FILE_SIZE,
        )
        output = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT, shell=True
        ).decode("utf-8")

        return output
