#
# iamProvisioner.py - Provisions IAM users for developer access to a dev EC2
# instance via SSM Session Manager.
#
# Background work follows the same shape as vmms/ecrBuilder.py: the caller gets
# a job id immediately, a daemon thread does the slow SSM work, and the caller
# polls for status. boto3 clients are built lazily so that importing this module
# never touches AWS or blocks server startup.
#

import logging
import re
import shlex
import threading
import time
import uuid
from collections import OrderedDict

import boto3

from config import Config

log = logging.getLogger("IamProvisioner")

# Status ids, matching the convention used by vmms/ecrBuilder.py
STATUS_RUNNING = 1
STATUS_SUCCEEDED = 2
STATUS_FAILED = 255

# Most jobs to retain in memory. Oldest terminal jobs are evicted first.
MAX_JOBS = 256

# Most provisioning threads allowed to run at once. Each one can sleep for up
# to SSM_TIMEOUT_SECS waiting on Run Command.
MAX_CONCURRENT_PROVISIONS = 4

# SSM Run Command polling
SSM_POLL_INTERVAL_SECS = 2
SSM_POLL_ATTEMPTS = 30
SSM_TIMEOUT_SECS = SSM_POLL_INTERVAL_SECS * SSM_POLL_ATTEMPTS

# IAM allows [A-Za-z0-9+=,.@_-] up to 64 chars.
IAM_USERNAME_RE = re.compile(r"^[A-Za-z0-9+=,.@_-]{1,64}$")

# Linux accounts are stricter: must not start with a digit or a dash, and must
# stay within the 32 char limit useradd enforces.
OS_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

INSTANCE_ID_RE = re.compile(r"^i-[0-9a-f]{8,17}$")


class IamValidationError(Exception):
    """Raised when a caller-supplied value fails validation."""


class IamCapacityError(Exception):
    """Raised when too many provisioning jobs are already in flight."""


class IamJobNotFound(Exception):
    """Raised when a status read names a job id that is not in the table."""


class IamUserNotFound(Exception):
    """Raised when an operation names an IAM user that does not exist."""


##
# Configuration
##


def _validate_iam_runtime_config():
    """Validate required IAM configuration and return it as a tuple.

    Mirrors Ec2SSH._validate_ec2_runtime_config: fail loudly with the full list
    of what is missing rather than one value at a time.
    """
    missing = []

    region = str(getattr(Config, "IAM_REGION", "")).strip()
    if not region:
        missing.append("IAM_REGION")

    path = str(getattr(Config, "IAM_USER_PATH", "")).strip()
    if not path:
        missing.append("IAM_USER_PATH")

    group = str(getattr(Config, "IAM_GROUP", "")).strip()
    if not group:
        missing.append("IAM_GROUP")

    allowed = getattr(Config, "IAM_ALLOWED_INSTANCES", None) or []
    if not allowed:
        missing.append("IAM_ALLOWED_INSTANCES")

    if missing:
        raise ValueError(
            "Missing required IAM configuration: %s" % ", ".join(missing)
        )

    if not path.startswith("/") or not path.endswith("/"):
        raise ValueError(
            "Invalid IAM_USER_PATH (must start and end with '/'): %s" % path
        )

    return region, path, group, list(allowed)


##
# Lazy boto3 clients
##

_clients = {}
_clients_lock = threading.Lock()


def _client(service):
    """Build (once) and return a boto3 client for the given service.

    Built on first use rather than at import so that a bad region or a missing
    credential chain surfaces on the request that needs it, instead of
    preventing the Tango server from starting.
    """
    with _clients_lock:
        if service not in _clients:
            region, _, _, _ = _validate_iam_runtime_config()
            _clients[service] = boto3.client(service, region_name=region)
        return _clients[service]


def _iam():
    return _client("iam")


def _ssm():
    return _client("ssm")


##
# Validation
##


def validate_iam_username(iam_username):
    """Validate an IAM user name against the IAM charset."""
    if not isinstance(iam_username, str) or not IAM_USERNAME_RE.match(iam_username):
        raise IamValidationError(
            "Invalid iam_username: must match %s" % IAM_USERNAME_RE.pattern
        )
    return iam_username


def validate_os_username(os_username):
    """Validate a Linux account name.

    Stricter than the IAM charset on purpose: this value is passed to useradd
    and must not be able to look like an option or overflow the 32 char limit.
    """
    if not isinstance(os_username, str) or not OS_USERNAME_RE.match(os_username):
        raise IamValidationError(
            "Invalid os_username: must match %s" % OS_USERNAME_RE.pattern
        )
    return os_username


def validate_instance_id(instance_id):
    """Validate an instance id and check it against the configured allowlist."""
    if not isinstance(instance_id, str) or not INSTANCE_ID_RE.match(instance_id):
        raise IamValidationError(
            "Invalid instance_id: must match %s" % INSTANCE_ID_RE.pattern
        )

    _, _, _, allowed = _validate_iam_runtime_config()
    if instance_id not in allowed:
        raise IamValidationError(
            "instance_id %s is not in IAM_ALLOWED_INSTANCES" % instance_id
        )
    return instance_id


def resolve_usernames(iam_username, os_username=None):
    """Validate the pair and default os_username to iam_username.

    When os_username is omitted, iam_username has to satisfy the Linux rule too,
    since it is what ends up being created on the instance.
    """
    validate_iam_username(iam_username)

    if os_username is None or os_username == "":
        validate_os_username(iam_username)
        return iam_username, iam_username

    validate_os_username(os_username)
    return iam_username, os_username


##
# Job records
##

iam_jobs = OrderedDict()
iam_jobs_lock = threading.RLock()

_provision_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_PROVISIONS)


def _evict_jobs_if_needed():
    """Drop the oldest terminal jobs once the table is full.

    Called with iam_jobs_lock held. Running jobs are never evicted; if every
    retained job is still running the table is allowed to exceed MAX_JOBS
    rather than lose a job that someone is polling.
    """
    while len(iam_jobs) >= MAX_JOBS:
        evictable = [
            job_id
            for job_id, job in iam_jobs.items()
            if job["statusId"] != STATUS_RUNNING
        ]
        if not evictable:
            return
        del iam_jobs[evictable[0]]


def _create_job(job_id, iam_username, os_username, instance_id):
    with iam_jobs_lock:
        _evict_jobs_if_needed()
        iam_jobs[job_id] = {
            "jobId": job_id,
            "statusId": STATUS_RUNNING,
            "statusMsg": "Provisioning IAM user",
            "iamUsername": iam_username,
            "osUsername": os_username,
            "instanceId": instance_id,
            "steps": [],
            "createdAt": time.time(),
        }


def _update_job(job_id, status_id, status_msg, result=None, access_key=None):
    with iam_jobs_lock:
        job = iam_jobs.get(job_id)
        if job is None:
            return
        job["statusId"] = status_id
        job["statusMsg"] = status_msg
        if result is not None:
            job["result"] = result
        if access_key is not None:
            # Held only until the first status read, then discarded.
            job["accessKey"] = access_key


def _append_step(job_id, message):
    """Record a progress line. Never called with secret material."""
    with iam_jobs_lock:
        job = iam_jobs.get(job_id)
        if job is not None:
            job["steps"].append(message)


##
# SSM helper
##


def run_on_instance(commands, instance_id):
    """Run shell commands on the instance as root and wait for the result.

    Blocking: callers must be on a worker thread, never the Tornado event loop.
    """
    ssm = _ssm()
    command_id = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
    )["Command"]["CommandId"]

    # send_command returns immediately; poll until the invocation finishes.
    for _ in range(SSM_POLL_ATTEMPTS):
        time.sleep(SSM_POLL_INTERVAL_SECS)
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id, InstanceId=instance_id
            )
        except ssm.exceptions.InvocationDoesNotExist:
            continue  # invocation not registered yet, keep waiting
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            return result

    raise TimeoutError(
        "command %s did not finish in %ss" % (command_id, SSM_TIMEOUT_SECS)
    )


##
# Provisioning steps
##


def _assert_managed_user(iam, iam_username, path):
    """Refuse to touch an IAM user that lives outside IAM_USER_PATH.

    Real people's IAM users live at "/" in this account. Matching on name alone
    would let a request reach them, so an existing user is only ever modified
    when it sits under the configured path.
    """
    try:
        user = iam.get_user(UserName=iam_username)["User"]
    except iam.exceptions.NoSuchEntityException:
        raise IamUserNotFound("No IAM user named %s" % iam_username)

    if user.get("Path") != path:
        raise IamValidationError(
            "IAM user %s exists at path %s, outside IAM_USER_PATH (%s)"
            % (iam_username, user.get("Path"), path)
        )
    return user


def ensure_iam_user(iam_username, os_username):
    """Create the IAM user if needed, then tag and group it.

    Idempotent: an existing user under IAM_USER_PATH is tagged and added to the
    group as well, so a user created by hand still ends up correct.
    """
    iam = _iam()
    _, path, group, _ = _validate_iam_runtime_config()

    try:
        iam.create_user(UserName=iam_username, Path=path)
        created = True
    except iam.exceptions.EntityAlreadyExistsException:
        _assert_managed_user(iam, iam_username, path)
        created = False

    # Tag outside the try so users created manually can also get tagged.
    iam.tag_user(
        UserName=iam_username,
        Tags=[{"Key": "SSMSessionRunAs", "Value": os_username}],
    )
    iam.add_user_to_group(GroupName=group, UserName=iam_username)
    return created


def ensure_linux_user(os_username, instance_id):
    """Create the matching Linux account on the instance if it is missing.

    An account that already exists is only accepted when it is an unprivileged
    one: a system or sudo-capable account would otherwise let the
    SSMSessionRunAs tag map a developer onto a privileged session.
    """
    quoted = shlex.quote(os_username)
    result = run_on_instance(
        [
            "set -e",
            "u=%s" % quoted,
            'if id -u -- "$u" >/dev/null 2>&1; then',
            '  uid=$(id -u -- "$u")',
            '  if [ "$uid" -lt 1000 ]; then',
            '    echo "refusing: $u has uid $uid (<1000)" >&2',
            "    exit 1",
            "  fi",
            "  # Ask sudo itself rather than checking group membership: ssm-user",
            "  # is granted passwordless sudo through /etc/sudoers.d with an",
            "  # ordinary uid and no privileged group, so it passes both. Any",
            "  # output other than an explicit denial is treated as privileged,",
            "  # so a missing sudo or an unexpected error fails closed.",
            '  sudo_out=$(LC_ALL=C sudo -n -l -U "$u" 2>&1) || true',
            '  case "$sudo_out" in',
            '    *"not allowed to run sudo"*) : ;;',
            "    *)",
            '      echo "refusing: $u may have sudo access" >&2',
            "      exit 1",
            "      ;;",
            "  esac",
            "else",
            '  useradd -m -s /bin/bash -- "$u"',
            "fi",
        ],
        instance_id,
    )
    if result["Status"] != "Success":
        raise RuntimeError(
            "linux account setup %s: %s"
            % (result["Status"], result.get("StandardErrorContent", "").strip())
        )
    return result["Status"]


def verify(iam_username, os_username, instance_id):
    """Read back what was provisioned. Returns access key ids, never secrets."""
    iam = _iam()

    user = iam.get_user(UserName=iam_username)["User"]
    tags = {
        t["Key"]: t["Value"] for t in iam.list_user_tags(UserName=iam_username)["Tags"]
    }
    groups = [
        g["GroupName"]
        for g in iam.list_groups_for_user(UserName=iam_username)["Groups"]
    ]
    key_ids = [
        k["AccessKeyId"]
        for k in iam.list_access_keys(UserName=iam_username)["AccessKeyMetadata"]
    ]
    linux = run_on_instance(
        ["id -- %s" % shlex.quote(os_username)], instance_id
    )

    return {
        "arn": user["Arn"],
        "runAsTag": tags.get("SSMSessionRunAs"),
        "groups": groups,
        "accessKeyIds": key_ids,
        "linuxAccount": linux.get("StandardOutputContent", "").strip(),
    }


def regenerate_access_key(iam_username):
    """Delete the user's existing access keys, then create and return a new one.

    Blocking: callers must be on a worker thread. The returned secret is shown
    once and is never logged or stored in a job record by this function.
    """
    validate_iam_username(iam_username)
    iam = _iam()
    _, path, _, _ = _validate_iam_runtime_config()
    _assert_managed_user(iam, iam_username, path)

    existing = iam.list_access_keys(UserName=iam_username)["AccessKeyMetadata"]
    for key in existing:
        iam.delete_access_key(UserName=iam_username, AccessKeyId=key["AccessKeyId"])

    key = iam.create_access_key(UserName=iam_username)["AccessKey"]
    log.info(
        "Regenerated access key %s for %s (replaced %d)",
        key["AccessKeyId"],
        iam_username,
        len(existing),
    )
    return {
        "accessKeyId": key["AccessKeyId"],
        "secretAccessKey": key["SecretAccessKey"],
    }


##
# Public API
##


def start_iam_provision(iam_username, os_username, instance_id, create_key=False):
    """Validate the request, start a background provision, return the job id.

    Raises IamValidationError on a bad request and IamCapacityError when too
    many provisions are already running.
    """
    iam_username, os_username = resolve_usernames(iam_username, os_username)
    validate_instance_id(instance_id)

    if not _provision_semaphore.acquire(blocking=False):
        raise IamCapacityError(
            "Too many provisioning jobs in flight (limit %d)"
            % MAX_CONCURRENT_PROVISIONS
        )

    job_id = str(uuid.uuid4())
    _create_job(job_id, iam_username, os_username, instance_id)

    try:
        thread = threading.Thread(
            target=_provision_task,
            args=(job_id, iam_username, os_username, instance_id, bool(create_key)),
        )
        thread.daemon = True
        thread.start()
    except Exception:
        _provision_semaphore.release()
        _update_job(job_id, STATUS_FAILED, "Could not start provisioning thread")
        raise

    log.info(
        "Started IAM provision job %s for %s on %s", job_id, iam_username, instance_id
    )
    return job_id


def _provision_task(job_id, iam_username, os_username, instance_id, create_key):
    """Background worker. Every failure lands in the job record as terminal."""
    try:
        # The Linux account is vetted before any IAM state is written.
        # ensure_iam_user tags SSMSessionRunAs and grants the SSM group, so
        # running it first would leave a usable IAM user mapped onto an account
        # this check is about to refuse.
        status = ensure_linux_user(os_username, instance_id)
        _append_step(job_id, "linux account ready (%s)" % status)

        created = ensure_iam_user(iam_username, os_username)
        _append_step(
            job_id,
            "created IAM user" if created else "IAM user already existed",
        )
        _append_step(job_id, "tagged SSMSessionRunAs and added to group")

        result = verify(iam_username, os_username, instance_id)

        # Created last, once everything else has succeeded. A key made before a
        # later failure would be unrecoverable: the job would end FAILED without
        # storing the secret, and a retry would skip creation because a key now
        # exists.
        access_key = None
        if create_key:
            iam = _iam()
            existing = iam.list_access_keys(UserName=iam_username)[
                "AccessKeyMetadata"
            ]
            if existing:
                # Not silently rotated here: the secret for an existing key
                # cannot be recovered, and deleting it would break whoever is
                # using it. Regeneration is an explicit call.
                _append_step(
                    job_id,
                    "access key already exists (%s), not replaced"
                    % existing[0]["AccessKeyId"],
                )
            else:
                key = iam.create_access_key(UserName=iam_username)["AccessKey"]
                access_key = {
                    "accessKeyId": key["AccessKeyId"],
                    "secretAccessKey": key["SecretAccessKey"],
                }
                result["accessKeyIds"].append(key["AccessKeyId"])
                _append_step(job_id, "created access key %s" % key["AccessKeyId"])

        _update_job(
            job_id,
            STATUS_SUCCEEDED,
            "IAM user provisioned",
            result=result,
            access_key=access_key,
        )
        log.info("IAM provision job %s succeeded", job_id)

    except Exception as e:
        # Deliberately logs the exception only, never the request payload,
        # since a secret may have been created before the failure.
        log.error("IAM provision job %s failed: %s", job_id, e)
        _update_job(job_id, STATUS_FAILED, "Provisioning failed: %s" % e)

    finally:
        _provision_semaphore.release()


def get_provision_status(job_id):
    """Return the job's status.

    A newly created access key is included on the first successful read only,
    then dropped from the job record. Callers must send this response with
    Cache-Control: no-store.

    Raises IamJobNotFound for an unknown job id, so that the caller can answer
    404 rather than reporting a real job that failed.
    """
    with iam_jobs_lock:
        job = iam_jobs.get(str(job_id))
        if job is None:
            raise IamJobNotFound("No IAM job with id %s" % job_id)

        res = {
            "jobId": job["jobId"],
            "statusId": int(job["statusId"]),
            "statusMsg": job["statusMsg"],
            "iamUsername": job["iamUsername"],
            "osUsername": job["osUsername"],
            "instanceId": job["instanceId"],
            "steps": list(job["steps"]),
        }

        if "result" in job:
            res["result"] = job["result"]

        # Hand the secret over exactly once.
        access_key = job.pop("accessKey", None)
        if access_key is not None:
            res["accessKey"] = access_key

        return res
