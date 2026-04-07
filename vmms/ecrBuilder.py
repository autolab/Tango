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

def start_ecr_build(course_id, job_id, image_name, dockerfile_content):
    print("Starting build with job_id=%s" % job_id)
    
    build_jobs[str(job_id)] = {
        "statusMsg": "Building image in ECR",
        "statusId": 1,
        "jobId": int(job_id)
    }

    # Spin up background thread to avoid blocking the API
    thread = threading.Thread(
        target=_build_and_push_task,
        args=(job_id, course_id, image_name, dockerfile_content)
    )
    thread.daemon = True
    thread.start()

    return int(job_id)

def _build_and_push_task(job_id, course_id, image_name, dockerfile_content):
    version_tag = f"{image_name}-{int(time.time())}"
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


        # Write Dockerfile to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            print("Creating docker image %s" % image_name)
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

            full_image_name = f"{registry}/{course_id}:{version_tag}"

            # Build the image locally
            _, logs = docker_client.images.build(path=tmpdir, tag=full_image_name)
            for chunk in logs:
                if "stream" in chunk:
                    print(chunk["stream"], end="")
                if "error" in chunk:
                    print("BUILD ERROR:", chunk["error"])

            print("Pushing docker image %s to ECR" % image_name)
            # Push to ECR
            push_logs = docker_client.images.push(full_image_name, stream=True, decode=True)
            for log in push_logs:
                if 'error' in log:
                    raise Exception(log['error'])
            # Tag it with the stable image name
            docker_client.images.get(full_image_name) \
                .tag(f"{registry}/{course_id}:{stable_tag}")

        # On Success
        build_jobs[job_id]["statusId"] = 2
        build_jobs[job_id]["statusMsg"] = "Image built successfully"
        build_jobs[job_id]["ecrImageUri"] = full_image_name

    except Exception as e:
        print(("Build failed: %s" % e))
        # On Failure
        build_jobs[job_id]["statusId"] = 255
        build_jobs[job_id]["statusMsg"] = f"Build failed: {str(e)}"

def get_build_status(job_id):
    print(build_jobs)
    return build_jobs.get(str(job_id), {"statusId": 255, "statusMsg": "Job not found"})