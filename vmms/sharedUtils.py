import subprocess
import time
import os
from typing import List
import config


class VMMSUtils:
    @staticmethod
    def constructInstanceName(id: int, name: str) -> str:
        """instanceName - Constructs a VM instance name. Always use
        this function when you need a VM instance name. Never generate
        instance names manually.
        """
        return "%s-%d-%s" % (config.Config.PREFIX, id, name)

    @staticmethod
    def timeout(command: List[str], time_out: float = 1) -> int:
        """timeout - Run a unix command with a timeout. Return -1 on
        timeout, otherwise return the return value from the command, which
        is typically 0 for success, 1-255 for failure.
        """

        # Launch the command
        p = subprocess.Popen(
            command, stdout=open("/dev/null", "w"), stderr=subprocess.STDOUT
        )

        # Wait for the command to complete
        t = 0.0
        while t < time_out and p.poll() is None:
            time.sleep(config.Config.TIMER_POLL_INTERVAL)
            t += config.Config.TIMER_POLL_INTERVAL

        # Determine why the while loop terminated
        returncode: int
        poll_result = p.poll()
        if poll_result is None:
            try:
                os.kill(p.pid, 9)
            except OSError:
                pass
            returncode = -1
        else:
            returncode = poll_result
        return returncode
