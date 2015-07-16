#!/usr/bin/python
from __future__ import print_function
import sys
import os
import pwd
import shutil
import subprocess
#print("Running "+ str(sys.argv))

for f in os.listdir("mount"):
    src=os.path.join("mount", f)
    dst=os.path.join("autolab", f)
    shutil.copy(src, dst)

autolabuser=pwd.getpwnam("autolab")
pid=os.fork()
if pid == 0:
    os.setgroups([])
    os.setgid(autolabuser.pw_gid)
    os.setuid(autolabuser.pw_uid)
    outfile=open("output/feedback", "w")
    args=["autodriver"]
    args.extend(sys.argv[1:])
    args.append("autolab")
    print("Executing "+str(args), file=outfile)
    sys.exit(subprocess.call(args, stdout=outfile, stderr=outfile, close_fds=True))
(np, status)=os.waitpid(pid, 0)
# if core, exit -1, else pass through code.
if status & 0xff:
    status=-1
else:
    status>>=8;
shutil.copy("output/feedback", "mount/feedback")
sys.exit(status)
