import threading
import tempfile
import random
import os
import docker
import boto3
import base64
import json
import time
from config import Config

# In-memory dictionary to track build status
build_jobs = {}
build_jobs_lock = threading.RLock()

def create_build_job(job_id, status_id, status_msg):
    with build_jobs_lock:
        build_jobs[str(job_id)] = {
            "statusMsg": status_msg,
            "statusId": status_id,
            "jobId": int(job_id),
            "logs": [],
            "logCursor": 0,
        }

def update_build_job(job_id, status_id, status_msg, uri=None, log_cursor=None):
    with build_jobs_lock:
        build_jobs[str(job_id)]["statusId"] = status_id
        build_jobs[str(job_id)]["statusMsg"] = status_msg
        if uri != None:
            build_jobs[str(job_id)]["ecrImageUri"] = uri
        if log_cursor != None:
            build_jobs[str(job_id)]["logCursor"] = log_cursor

def append_build_log(job_id, message):
    with build_jobs_lock:
        build_jobs[str(job_id)]["logs"].append(message)

def start_ecr_build(course_id, job_id, image_name, dockerfile_content, base_tag, base_uri):
    print("Starting build with job_id=%s" % job_id)
    
    create_build_job(
        job_id=int(job_id),
        status_id=1,
        status_msg="Building image in ECR"
    )

    # Spin up background thread to avoid blocking the API
    thread = threading.Thread(
        target=_build_and_push_task,
        args=(job_id, course_id, image_name, dockerfile_content, base_tag, base_uri)
    )
    thread.daemon = True
    thread.start()

    return int(job_id)

def _build_and_push_task(job_id, course_id, image_name, dockerfile_content, base_tag, base_uri):
    course_id = course_id.lower()
    image_name = image_name.lower()
    if course_id is "public":
        ecr_tag = image_name
    else:
        ecr_tag = f"{image_name}-{int(time.time())}"
    stable_tag = image_name
    try:
        # Authenticate with AWS ECR
        ecr_client = boto3.client('ecr', region_name=Config.EC2_REGION)
        
        print("Connecting to ECR repository")
        try:
            ecr_client.describe_repositories(repositoryNames=[course_id])
        except ecr_client.exceptions.RepositoryNotFoundException:
            print("Creating ECR repository")
            ecr_client.create_repository(repositoryName=course_id)
            
            # Apply Lifecycle Policy to automatically expire old images
            policy_text = json.dumps({
                "rules": [
                    {
                        "rulePriority": 1,
                        "description": "Expire images older than 180 days",
                        "selection": {
                            "tagStatus": "any",
                            "countType": "sinceImagePushed",
                            "countUnit": "days",
                            "countNumber": 180
                        },
                        "action": {
                            "type": "expire"
                        }
                    }
                ]
            })
            
            ecr_client.put_lifecycle_policy(
                repositoryName=course_id,
                lifecyclePolicyText=policy_text
            )

        auth_response = ecr_client.get_authorization_token()
        auth_data = auth_response['authorizationData'][0]
        auth_token = base64.b64decode(auth_data['authorizationToken']).decode('utf-8')
        username, password = auth_token.split(':')
        registry = auth_data['proxyEndpoint'].replace('https://', '')

        # Authenticate local Docker daemon with ECR
        docker_client = docker.from_env()
        docker_client.login(username=username, password=password, registry=registry)

        print("Pulling remote docker image %s" % base_tag)
        if base_tag is not None and base_uri is not None:
            docker_client.images.pull(base_uri)
            docker_client.images.get(base_uri).tag(base_tag)

        # Write Dockerfile to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            print("Copying dockerfile %s" % image_name)
            dockerfile_path = os.path.join(tmpdir, 'Dockerfile')
            with open(dockerfile_path, 'w') as f:
                f.write(dockerfile_content)

            apt_preferences_content = """Package: fakeroot
Pin: release *
Pin-Priority: -1
"""

            apt_preferences_path = os.path.join(tmpdir, 'apt-preferences')
            with open(apt_preferences_path, 'w') as f:
                f.write(apt_preferences_content)

            full_image_name = f"{registry}/{course_id}:{ecr_tag}"
            repository = f"{registry}/{course_id}"

            # Build the image locally
            print("Building the docker image %s" % image_name)
            logs = docker_client.api.build(path=tmpdir, tag=full_image_name, decode=True)
            for chunk in logs:
                if "stream" in chunk:
                    print(chunk["stream"], end="")
                    append_build_log(job_id, chunk["stream"])
                if "error" in chunk:
                    print("BUILD ERROR:", chunk["error"])
                    append_build_log(job_id, chunk["error"])
                    raise Exception(chunk["error"])
                if "message" in chunk:
                    print(chunk["message"], end="")
                    append_build_log(job_id, chunk["message"])
                    if "dockerfile parse error" in chunk["message"].lower():
                        raise Exception(chunk["message"])

            print("Pushing docker image %s to ECR" % image_name)
            # Push to ECR
            push_logs = docker_client.images.push(repository=repository, tag=ecr_tag, stream=True, decode=True)
            for log in push_logs:
                if 'error' in log:
                    raise Exception(log['error'])

        print("Build all done!")
        # On Success
        update_build_job(
            job_id=job_id,
            status_id=2,
            status_msg="Image built successfully",
            uri=full_image_name
        )

    except Exception as e:
        print(("Build failed: %s" % e))
        # On Failure
        update_build_job(
            job_id=job_id,
            status_id=255,
            status_msg=f"Build failed: {str(e)}",
        )
    finally:
        print("Cleaning up local Docker storage...")
        try:
            # Remove the final built image from the EC2 drive
            if 'full_image_name' in locals():
                docker_client.images.remove(image=full_image_name, force=True)
            
            # Remove the base template image (if it was pulled)
            if base_uri is not None:
                docker_client.images.remove(image=base_uri, force=True)
            if base_tag is not None:
                docker_client.images.remove(image=base_tag, force=True)
            
            #  Prune intermediate `<none>:<none>` dangling layers
            prune_result = docker_client.images.prune(filters={'dangling': True})
            reclaimed = prune_result.get('SpaceReclaimed', 0) / (1024 * 1024) # Convert bytes to MB
            print(f"Cleanup successful. Reclaimed {reclaimed:.2f} MB of dangling cache.")
            
        except Exception as cleanup_error:
            # We catch exceptions here so a cleanup failure doesn't crash the Tango daemon
            print(f"Cleanup warning: {cleanup_error}")

def get_build_status(job_id):
    with build_jobs_lock:
        job = build_jobs.get(str(job_id))
        if job is None:
            return {
                "statusId": 255,
                "statusMsg": "Job not found",
                "logs": []
            }

        # Retrieve the FULL log history
        logs = list(job.get("logs", []))

        res = {
            "statusId": int(job["statusId"]),
            "statusMsg": job["statusMsg"],
            "logs": logs,
        }

        if "ecrImageUri" in job:
            res["ecrImageUri"] = job["ecrImageUri"]

        # mark terminal jobs
        if job["statusId"] in (2, 255):
            job["done"] = True

        return res

def get_all_build_status():
    all_jobs = {}
    for job in build_jobs.values():
        all_jobs[str(job["jobId"])] = get_build_status(int(job["jobId"]))
    return {
        "images": all_jobs
    }