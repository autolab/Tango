import boto3
import time
import uuid

# Load package list from text file
packages = ["minicom"]

# Basic config
REGION = "us-east-1"
BASE_AMI_ID = "ami-01e13770dd8d2097e"
INSTANCE_PROFILE = "EC2InstanceProfileForImageBuilder"  # must exist in IAM

client = boto3.client("imagebuilder", region_name=REGION)

unique_id = str(uuid.uuid4())[:8]
component_name = f"install-apt-{unique_id}"
recipe_name = f"custom-ubuntu-recipe-{unique_id}"
infra_name = f"infra-{unique_id}"
pipeline_name = f"pipeline-{unique_id}"

# 1️. Create component (shell script installer)
component_data = f"""name: InstallAptPackages
description: Install apt packages
schemaVersion: 1.0
phases:
  - name: build
    steps:
      - name: Install
        action: ExecuteBash
        inputs:
          commands:
            - apt-get update -y
            - apt-get install -y {' '.join(packages)}
"""

print("Creating component...")
component_resp = client.create_component(
    name=component_name,
    semanticVersion="1.0.0",
    platform="Linux",
    data=component_data,
)
component_arn = component_resp["componentBuildVersionArn"]
print("Component created:", component_arn)

# 2️. Create image recipe
print("Creating image recipe...")
recipe_resp = client.create_image_recipe(
    name=recipe_name,
    semanticVersion="1.0.0",
    components=[{"componentArn": component_arn}],
    parentImage=BASE_AMI_ID,
    blockDeviceMappings=[],
)
recipe_arn = recipe_resp["imageRecipeArn"]
print("Recipe created:", recipe_arn)

iam = boto3.client("iam")

print("\nListing available instance profiles...")
profiles = iam.list_instance_profiles()["InstanceProfiles"]

if not profiles:
    print("No instance profiles found in your account.")
else:
    for p in profiles:
        name = p["InstanceProfileName"]
        roles = [r["RoleName"] for r in p["Roles"]]
        print(f" - {name} (roles: {roles})")

# 3️. Create infrastructure configuration
print("Creating infrastructure configuration...")
infra_resp = client.create_infrastructure_configuration(
    name=infra_name,
    instanceTypes=["t3.micro"],
    instanceProfileName=INSTANCE_PROFILE,
)
infra_arn = infra_resp["infrastructureConfigurationArn"]
print("Infrastructure config created:", infra_arn)

# 4️. Create pipeline
print("Creating image pipeline...")
pipeline_resp = client.create_image_pipeline(
    name=pipeline_name,
    imageRecipeArn=recipe_arn,
    infrastructureConfigurationArn=infra_arn,
    imageTestsConfiguration={
        "imageTestsEnabled": False
    },
)
pipeline_arn = pipeline_resp["imagePipelineArn"]
print("Pipeline created:", pipeline_arn)

# 5️. Start build
print("Starting build...")
build_resp = client.start_image_pipeline_execution(imagePipelineArn=pipeline_arn)
execution_arn = build_resp["imageBuildVersionArn"]
print("Build started:", execution_arn)

# 6. Wait for image completion
# Probably make this not a blocking process
print("Waiting for build to finish (this can take 10–20 minutes)...")
while True:
    resp = client.get_image(imageBuildVersionArn=execution_arn)
    state = resp["image"]["state"]["status"]
    if state in ["AVAILABLE", "FAILED"]:
        break
    print(f"⏳ Status: {state}")
    time.sleep(60)

if state == "AVAILABLE":
    ami_id = resp["image"]["outputResources"]["amis"][0]["image"]
    print(f"AMI created successfully: {ami_id}")
else:
    print("Build failed:", resp["image"]["state"].get("reason", "Unknown"))