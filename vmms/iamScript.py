"""
For each username:
  1. create the IAM user (under a dedicated path)
  2. tag it with SSMSessionRunAs so Session Manager knows which OS user to be
  3. add it to the group that carries specific SSM permissions
  4. optionally create an access key so the person can run `aws configure`
  5. create the matching Linux account on the instance via SSM Run Command
  6. read everything back and print

Usage:
    python script.py --dry-run
    python script.py
    python script.py --create-key
    python script.py --delete
"""

import argparse
import time
import boto3

USERS = ["test-user", "test2"]
PATH = "/autolab-dev/" # IAM path, can change
GROUP = "instructors" # has AmazonSSMFullAccess
INSTANCE_ID = "i-0eaa70d55994df42a" # relevant instance
REGION = "us-east-2"

iam = boto3.client("iam")
ssm = boto3.client("ssm", region_name=REGION)

# ssm helper

def run_on_instance(commands, dry_run=False):
    """Run shell commands on the instance as root and wait for the result."""
    if dry_run:
        print(f"  [dry-run] would run on {INSTANCE_ID}: {commands}")
        return None

    command_id = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
    )["Command"]["CommandId"]

    # send_command returns immediately; poll until the invocation finishes.
    for _ in range(30):
        time.sleep(2)
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id, InstanceId=INSTANCE_ID
            )
        except ssm.exceptions.InvocationDoesNotExist:
            continue  # invocation not registered yet, keep waiting
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            return result

    raise TimeoutError(f"command {command_id} did not finish in 60s")


# provisioning

def ensure_iam_user(username, dry_run=False):
    if dry_run:
        print(f"  [dry-run] would create/tag/group {username}")
        return

    try:
        iam.create_user(UserName=username, Path=PATH)
        print(f"  created IAM user {username}")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"  IAM user {username} already exists")

    # Tag outside the try so users created manually can also get tagged
    iam.tag_user(
        UserName=username,
        Tags=[{"Key": "SSMSessionRunAs", "Value": username}],
    )
    iam.add_user_to_group(GroupName=GROUP, UserName=username)
    print(f"  tagged SSMSessionRunAs={username}, added to {GROUP}")


def ensure_access_key(username, dry_run=False):
    if dry_run:
        print(f"  [dry-run] would create an access key for {username}")
        return

    existing = iam.list_access_keys(UserName=username)["AccessKeyMetadata"]
    if existing:
        print(f"  access key already exists ({existing[0]['AccessKeyId']}), skipping")
        return

    key = iam.create_access_key(UserName=username)["AccessKey"]
    print(f"  access key id     : {key['AccessKeyId']}")
    print(f"  secret access key : {key['SecretAccessKey']}  <- shown once only.")


def ensure_linux_user(username, dry_run=False):
    result = run_on_instance(
        [f"id -u {username} >/dev/null 2>&1 || useradd -m -s /bin/bash {username}"],
        dry_run=dry_run,
    )
    if result:
        print(f"  useradd status: {result['Status']}")
        if result["Status"] == "Failed":
            print(f"  stderr: {result['StandardErrorContent'].strip()}")


# verification

def verify(username):
    user = iam.get_user(UserName=username)["User"]
    tags = {t["Key"]: t["Value"] for t in iam.list_user_tags(UserName=username)["Tags"]}
    groups = [g["GroupName"] for g in
              iam.list_groups_for_user(UserName=username)["Groups"]]
    keys = [k["AccessKeyId"] for k in
            iam.list_access_keys(UserName=username)["AccessKeyMetadata"]]
    linux = run_on_instance([f"id {username}"])

    print(f"  arn         : {user['Arn']}")
    print(f"  runas tag   : {tags.get('SSMSessionRunAs', 'MISSING')}")
    print(f"  groups      : {', '.join(groups) or 'none'}")
    print(f"  access keys : {', '.join(keys) or 'none'}")
    print(f"  linux acct  : {linux['StandardOutputContent'].strip() or linux['Status']}")


# deleting everything

def delete_user(username):
    for key in iam.list_access_keys(UserName=username)["AccessKeyMetadata"]:
        iam.delete_access_key(UserName=username, AccessKeyId=key["AccessKeyId"])
    for group in iam.list_groups_for_user(UserName=username)["Groups"]:
        iam.remove_user_from_group(GroupName=group["GroupName"], UserName=username)
    iam.delete_user(UserName=username)
    run_on_instance([f"userdel -r {username} || true"])
    print(f"  deleted {username} (IAM + Linux)")


# main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would happen, change nothing")
    parser.add_argument("--create-key", action="store_true",
                        help="also create an access key and print the secret")
    parser.add_argument("--delete", action="store_true",
                        help="tear down the users in USERS instead of creating them")
    args = parser.parse_args()

    for username in USERS:
        print(f"\n== {username}")

        if args.delete:
            delete_user(username)
            continue

        ensure_iam_user(username, args.dry_run)
        if args.create_key:
            ensure_access_key(username, args.dry_run)
        ensure_linux_user(username, args.dry_run)

        if not args.dry_run:
            print("  --- verify ---")
            verify(username)


if __name__ == "__main__":
    main()