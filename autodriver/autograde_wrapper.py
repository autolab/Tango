#!/usr/bin/python
from __future__ import print_function
import sys
import os
import pwd
import shutil
import threading
#print("Running "+ str(sys.argv))

# Wait for all processes, since we are pid 1 in the container,
# exit thread (which is blocking the main thread) once the
# interesting process exits
class WaitLoop(object):
    def __init__(self, pid=None):
        self.waitfor = pid
        self.status = None
    def __call__(self):
        try:
            (nextpid, self.status) = os.wait()
            while nextpid is None or nextpid != self.waitfor:
                (nextpid, self.status) = os.wait()
        except OSError:
            if nextpid:
                print("Chld process {} never exited, but no more children left".
                      format(self.waitfor))
                self.status = -1

def main():
    for copyfile in os.listdir("mount"):
        src = os.path.join("mount", copyfile)
        dst = os.path.join("autolab", copyfile)
        shutil.copy(src, dst)

    autolabuser = pwd.getpwnam("autolab")
    (r_p, w_p) = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r_p)
        os.setgroups([])
        os.setgid(autolabuser.pw_gid)
        os.setuid(autolabuser.pw_uid)
        args = ["autodriver"]
        args.extend(sys.argv[1:])
        args.append("autolab")
        if w_p != 1:
            os.dup2(w_p, 1)
        if w_p != 2:
            os.dup2(w_p, 2)
        if w_p > 2:
            os.close(w_p)
        os.execvp(args[0], args)
    os.close(w_p)
    waiter = WaitLoop(pid)
    thr = threading.Thread(target=waiter)
    thr.start()
    rpf = os.fdopen(r_p)
    shutil.copyfileobj(rpf, open("mount/feedback", "w"))
    #print("Copied output")
    rpf.close()
    thr.join()
    # if core, exit -1, else pass through code.
    if os.WIFSIGNALED(waiter.status):
        status = -1
    else:
        status = os.WEXITSTATUS(waiter.status)
    #print("Status is {}".format(status))
    sys.exit(status)

if __name__ == '__main__':
    main()
