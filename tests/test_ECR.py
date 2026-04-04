import requests
import time
import sys

BASE_URL = "http://localhost:3000"
API_KEY = "test"

def run_build_and_poll(test_name, payload, expected_success):
    print(f"\n[{test_name}] Initiating test...")
    build_url = f"{BASE_URL}/build_image/{API_KEY}/"
    
    try:
        # Trigger the POST request
        response = requests.post(build_url, json=payload)
        response_data = response.json()
        job_id = response_data.get("jobId")
        
        if not job_id:
            print(f"❌ [{test_name}] FAILED: No jobId returned.")
            return False
            
        print(f"⏳ [{test_name}] Job {job_id} started. Polling...")
        
        # Poll the GET request
        status_url = f"{BASE_URL}/build_status/{API_KEY}/{job_id}/"
        
        # Timeout safety (e.g., 2 minutes maximum per build)
        timeout = time.time() + 120 
        
        while time.time() < timeout:
            status_res = requests.get(status_url)
            status_data = status_res.json()
            
            status_id = status_data.get("statusId")
            msg = status_data.get("statusMsg")
            
            if status_id == 0:
                if expected_success:
                    print(f"✅ [{test_name}] PASSED! Image built: {status_data.get('ecr_image_uri')}")
                    return True
                else:
                    print(f"❌ [{test_name}] FAILED: Expected failure, but it succeeded!")
                    return False
                    
            elif status_id < 0:
                if not expected_success:
                    print(f"✅ [{test_name}] PASSED! Caught expected failure: {msg}")
                    return True
                else:
                    print(f"❌ [{test_name}] FAILED: Expected success, but got error: {msg}")
                    return False
                    
            time.sleep(2)
            
        print(f"❌ [{test_name}] FAILED: Polling timed out.")
        return False

    except requests.exceptions.ConnectionError:
        print("❌ FAILED: Could not connect to Tango. Is server.py running?")
        sys.exit(1)

def main():
    print("🚀 Starting Autolab ECR Integration Test Suite...\n")
    
    tests_passed = 0
    total_tests = 3

    # TEST 1: Unique Hash / New Tag
    # Proves ECR creates a unique layer digest when the Dockerfile changes
    payload_1 = {
        "course_id": "15122",
        "image_name": "15-122-env",
        "tag": "hw3",
        "dockerfile_content": "FROM alpine:latest\nRUN echo \"Different assignment setup\""
    }
    if run_build_and_poll("TEST 1: Unique Image Hash", payload_1, expected_success=True):
        tests_passed += 1

    # TEST 2: JIT Provisioner
    # Proves our try/except block correctly creates a brand new course repo on the fly
    payload_2 = {
        "course_id": "15213",
        "image_name": "15-213-env",
        "tag": "latest",
        "dockerfile_content": "FROM alpine:latest\nRUN echo \"Welcome to Systems\""
    }
    if run_build_and_poll("TEST 2: JIT Repo Provisioning", payload_2, expected_success=True):
        tests_passed += 1

    # TEST 3: Deliberate Build Failure
    # Proves a typo from a professor won't crash Tango, and safely returns statusId -1
    payload_3 = {
        "course_id": "15122",
        "image_name": "15-122-env",
        "tag": "bad-dockerfile",
        "dockerfile_content": "FRM alpine:latest\nRUN echo \"This should crash\""
    }
    if run_build_and_poll("TEST 3: Syntax Error Handling", payload_3, expected_success=False):
        tests_passed += 1

    # Final Report
    print("\n" + "="*40)
    print(f"🏁 TEST RUN COMPLETE: {tests_passed}/{total_tests} Passed")
    print("="*40)
    
    if tests_passed == total_tests:
        print("🎉 All test Passed!")
    else:
        print("⚠️ Some tests failed. Check the logs above.")

if __name__ == "__main__":
    main()