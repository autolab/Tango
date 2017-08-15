import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vmms.ec2SSH import Ec2SSH

# test vmms.ec2SSH's image extraction code
# also serve as a template of accessing the ec2SSH vmms

vmms = Ec2SSH()
for key in vmms.img2ami:
  image = vmms.img2ami[key]
  print image["Name"], image["ImageId"], key

     
      
