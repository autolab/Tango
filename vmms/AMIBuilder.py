import boto3
import time
import docker
import uuid

# Basic config
REGION = "us-east-1"
BASE_AMI_ID = "ami-02c5d1279f155f781"
INSTANCE_PROFILE = "EC2InstanceProfileForImageBuilder"  # must exist in IAM

# Returns Amazon Resource Name of the image that it started building
def start_build_ami(username, packages):
  client = boto3.client("imagebuilder", region_name=REGION)
  unique_id = f"{username}-{str(uuid.uuid4())[:8]}"
  recipe_name = f"custom-ubuntu-recipe-{unique_id}"
  infra_name = f"infra-{unique_id}"
  pipeline_name = f"pipeline-{unique_id}"

  # if not validate_packages_docker(packages):
  #   print("Invalid!")
  #   return

  component_arn = create_component(client, packages, unique_id)  
  recipe_arn = create_image_recipe(client, recipe_name, component_arn)
  infra_arn = create_infra_config(client, infra_name)
  pipeline_arn = create_pipeline(client, pipeline_name, recipe_arn, infra_arn)

  print("Starting build...")
  build_resp = client.start_image_pipeline_execution(imagePipelineArn=pipeline_arn)
  execution_arn = build_resp["imageBuildVersionArn"]
  print("Build started:", execution_arn)
  return {
    "execution_arn": execution_arn,
    "pipeline_arn": pipeline_arn,
    "recipe_arn": recipe_arn,
    "component_arn": component_arn
  }

def clean_build_ami(pipeline_arn, recipe_arn, component_arn):
  client = boto3.client("imagebuilder", region_name=REGION)
  client.delete_image_pipeline(pipeline_arn)
  client.delete_image_recipe(recipe_arn)
  client.delete_component(component_arn)

### Helper Functions

def validate_packages_docker(packages, ubuntu_version="22.04"):
  client = docker.from_env()

  # Pull image if not cached
  image_name = f"ubuntu:{ubuntu_version}"
  client.images.pull(image_name)

  # Build validation command
  cmd = [
    "bash", "-c",
    "apt-get update -qq && apt-get install -s -y --no-install-recommends "
    + " ".join(packages)
  ]

  print(f"Validating {len(packages)} packages on Ubuntu {ubuntu_version}...")
  container = client.containers.run(
    image=image_name,
    command=cmd,
    remove=True,        # like --rm
    detach=True,
    stderr=True,
    stdout=True,
  )

  logs = container.logs(stream=True)
  for line in logs:
    print(line.decode().rstrip())

  exit_code = container.wait()["StatusCode"]

  if exit_code == 0:
    print(f"✅ All packages are valid for Ubuntu {ubuntu_version}")
    return True
  else:
    print(f"❌ Some packages failed validation on Ubuntu {ubuntu_version}")
    return False

def create_component(client, packages, unique_id):
  apt_pkgs = []
  deb_commands = ["mkdir /tmp/debs",
                  "command -v curl >/dev/null 2>&1 || apt-get install -y curl"]
  for pkg in packages:
    if pkg["install_type"] == "apt":
      if pkg["version"] == "latest" or pkg["version"] == "":
        apt_pkgs.append(f"{pkg["name"]}")
      else:
        apt_pkgs.append(f"{pkg["name"]}={pkg["version"]}")
    if pkg["install_type"] == "deb":
      if pkg["deb_url"] == "":
        print("deb_url doesn't exist.")
        continue
      else:
        deb_commands.append(f"curl -fsSL \"{pkg["deb_url"]}\" -o \"/tmp/debs/{pkg["name"]}.deb\"")
        deb_commands.append(f"apt-get -y install \"/tmp/debs/{pkg["name"]}.deb\"")
        deb_commands.append(f"rm \"/tmp/debs{pkg["name"]}\"")
  
  yaml_commands = "\n".join([f"            - {c}" for c in deb_commands])

  component_name = f"install-apt-{unique_id}"
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
            - apt-get install -y {' '.join(apt_pkgs)}
{yaml_commands}
"""
  print(component_data)

  print("Creating component...")
  component_resp = client.create_component(
      name=component_name,
      semanticVersion="1.0.0",
      platform="Linux",
      data=component_data,
  )
  component_arn = component_resp["componentBuildVersionArn"]
  print("Component created:", component_arn)
  return component_arn

def create_image_recipe(client, recipe_name, component_arn):
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
  return recipe_arn

def create_infra_config(client, infra_name):
  print("Creating infrastructure configuration...")
  infra_resp = client.create_infrastructure_configuration(
    name=infra_name,
    instanceTypes=["t3.micro"],
    instanceProfileName=INSTANCE_PROFILE,
  )
  infra_arn = infra_resp["infrastructureConfigurationArn"]
  print("Infrastructure config created:", infra_arn)
  return infra_arn

def create_pipeline(client, pipeline_name, recipe_arn, infra_arn):
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
  return pipeline_arn

if __name__ == "__main__":
  start_build_ami("soma", ["minicom", "invalid"])