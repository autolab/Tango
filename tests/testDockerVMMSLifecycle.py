import time
from tangoObjects import TangoMachine, InputFile
from vmms.ec2Docker import Ec2Docker

def run_lifecycle_test():
    print("🚀 Initializing Ec2Docker VMMS Integration Test...")
    vmms = Ec2Docker()
    
    # Mock the Autolab Machine Object
    vm = TangoMachine()
    vm.id = 999
    vm.name = "test-ec2docker-instance"
    
    # REPLACE THIS with an actual URI from ECR dashboard
    vm.image = "992382617910.dkr.ecr.us-east-2.amazonaws.com/15-122-env:real-autograder" 

    try:
        # Provisioning
        print(f"\n[1/5] Spinning up Spot instance for {vm.name}...")
        init_status = vmms.initializeVM(vm)
        if init_status != 0:
            print("❌ Failed to initialize VM. Check AWS credentials and base AMI.")
            return
        print(f"✅ EC2 Provisioned! Instance ID: {vm.instance_id}")

        # Initialization
        print("\n[2/5] Waiting for OS and SSH to boot (approx 60 seconds)...")
        wait_status = vmms.waitVM(vm, max_secs=300)
        if wait_status != 0:
            print("❌ VM failed to boot or SSH timed out.")
            return
        print("✅ SSH is responsive!")

        # File Transfer (copyIn)
        print("\n[3/5] Copying test payload (hello.c and Makefile) to EC2...")
        payload_files = [
            InputFile(localFile="hello.c", destFile="hello.c"),
            InputFile(localFile="Makefile", destFile="Makefile")
        ]
        
        copy_status = vmms.copyIn(vm, payload_files)
        if copy_status != 0:
            print("❌ Failed to SCP files.")
            return
        print("✅ Files copied successfully!")

        # Docker Execution
        print(f"\n[4/5] Pulling {vm.image} from ECR and executing...")
        run_status = vmms.runJob(vm, runTimeout=60, maxOutputFileSize=1024, disableNetwork=True)
        print(f"✅ Execution returned status code: {run_status}")

        # Retrieval (copyOut)
        print("\n[5/5] Retrieving feedback...")
        copyout_status = vmms.copyOut(vm, "local_feedback.txt")
        if copyout_status == 0:
            print("✅ Feedback successfully downloaded to local_feedback.txt")
        else:
            print("⚠️ Feedback retrieval failed (container may have crashed).")

    finally:
        # Teardown
        if vm.instance_id:
            print("\n🧹 Tearing down EC2 instance...")
            vmms.destroyVM(vm)
            print("✅ VM Terminated. End-to-End Test complete.")

if __name__ == "__main__":
    run_lifecycle_test()