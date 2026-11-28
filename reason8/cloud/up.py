"""Create or update the stack of the cloud workers, and say how many the spot quota allows.

    export REASON8_S3_URI=s3://<bucket>[/<prefix>]     # or pass --s3-uri
    uv run reason8 cloud up
    uv run reason8 cloud up --max-instances 20 --engines 5 --commit <sha>

Deploys ``reason8/cloud/stack.yaml`` (ADR 0020) as the stack ``--stack`` in the region of the
AWS configuration, waits until it is done and prints its outputs. The instances start in the
default VPC's subnets. They check out ``--commit`` of the repository's ``origin``: by default
the current HEAD, which must have been pushed, since the instances clone it from there.

Nothing runs after this: the group is empty until `reason8 cloud run`. Updating a stack keeps
the group's desired capacity, and instances already running keep the commit they started with.

Also prints the account's spot vCPU quota ("All Standard (A, C, D, H, I, M, R, T, Z) Spot
Instance Requests") and how many instances of the first instance type it allows, with a
warning when that is fewer than ``--max-instances``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

from botocore.exceptions import ClientError, WaiterError

from reason8.cloud import stack
from reason8.data import storage
from reason8.paths import REPO_ROOT

DEFAULT_INSTANCE_TYPES = "m7a.2xlarge,m7i.2xlarge,m6a.2xlarge,m6i.2xlarge"
WAITER_CONFIG = {"Delay": 10, "MaxAttempts": 180}
NO_UPDATES = "No updates are to be performed"


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *arguments], capture_output=True, text=True, check=True
    ).stdout.strip()


def https_url(remote: str) -> str:
    """A remote's URL as an instance clones it, without credentials: ``git@host:owner/repo``
    and ``ssh://git@host/owner/repo`` become ``https://host/owner/repo``."""
    scp_like = re.fullmatch(r"[^@/]+@([^:/]+):(.+)", remote)
    if scp_like:
        return f"https://{scp_like.group(1)}/{scp_like.group(2)}"
    ssh = re.fullmatch(r"ssh://(?:[^@/]+@)?([^:/]+)(?::\d+)?/(.+)", remote)
    if ssh:
        return f"https://{ssh.group(1)}/{ssh.group(2)}"
    return re.sub(r"^https://[^@/]+@", "https://", remote)


def pushed_commit(requested: str | None) -> str:
    """The full hash of `requested` (default: HEAD); exits unless origin has it."""
    commit = git("rev-parse", "--verify", f"{requested or 'HEAD'}^{{commit}}")
    branches = git("branch", "--remotes", "--contains", commit).splitlines()
    if not any(branch.strip().startswith("origin/") for branch in branches):
        raise SystemExit(
            f"commit {commit[:12]} is not on any branch of origin: push it first, "
            "since the instances clone it from there"
        )
    return commit


def default_subnets(ec2: Any) -> tuple[str, list[str]]:
    """The default VPC and its subnets."""
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise SystemExit("this region has no default VPC")
    vpc_id = vpcs[0]["VpcId"]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
    if not subnets:
        raise SystemExit(f"the default VPC {vpc_id} has no subnets")
    return vpc_id, sorted(subnet["SubnetId"] for subnet in subnets)


def stack_parameters(values: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "ParameterKey": key,
            "ParameterValue": ",".join(value) if isinstance(value, list) else str(value),
        }
        for key, value in values.items()
    ]


def deploy(cloudformation: Any, stack_name: str, parameters: list[dict[str, str]]) -> str:
    """Create the stack or update it, and wait; ``created``, ``updated`` or ``unchanged``."""
    request = {
        "StackName": stack_name,
        "TemplateBody": stack.template_text(),
        "Parameters": parameters,
        "Capabilities": ["CAPABILITY_IAM"],
    }
    if stack.describe_stack(cloudformation, stack_name) is None:
        # a stack that failed to be created is deleted, so `cloud up` can simply be repeated
        stack_id = cloudformation.create_stack(**request, OnFailure="DELETE")["StackId"]
        waiter, outcome = "stack_create_complete", "created"
    else:
        try:
            stack_id = cloudformation.update_stack(**request)["StackId"]
        except ClientError as error:
            if NO_UPDATES in str(error):
                return "unchanged"
            raise
        waiter, outcome = "stack_update_complete", "updated"
    print(f"waiting for the stack {stack_name} to be {outcome} ...", file=sys.stderr)
    try:
        cloudformation.get_waiter(waiter).wait(StackName=stack_id, WaiterConfig=WAITER_CONFIG)
    except WaiterError as error:
        for reason in failure_reasons(cloudformation, stack_id):
            print(reason, file=sys.stderr)
        raise SystemExit(f"the stack {stack_name} was not {outcome}: {error}") from error
    return outcome


def failure_reasons(cloudformation: Any, stack_id: str, limit: int = 10) -> list[str]:
    """Why the resources of a stack failed, newest first (a deleted stack keeps its events)."""
    events = cloudformation.describe_stack_events(StackName=stack_id)["StackEvents"]
    return [
        f"{event['LogicalResourceId']}: {event.get('ResourceStatusReason', '')}"
        for event in events
        if event["ResourceStatus"].endswith("FAILED")
    ][:limit]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    stack.add_stack_argument(parser)
    storage.add_uri_argument(parser)
    parser.add_argument(
        "--max-instances", type=int, default=10, help="the most instances at once (default 10)"
    )
    parser.add_argument(
        "--instance-types",
        default=DEFAULT_INSTANCE_TYPES,
        help=f"spot types of the same shape, the default first (default {DEFAULT_INSTANCE_TYPES})",
    )
    parser.add_argument("--engines", type=int, default=5, help="games per instance (default 5)")
    parser.add_argument(
        "--idle-minutes",
        type=int,
        default=5,
        help="an instance stops when the queue was empty this long (default 5)",
    )
    parser.add_argument("--volume-gib", type=int, default=100, help="root volume (default 100)")
    parser.add_argument("--commit", help="the commit to run (default: HEAD, pushed to origin)")


def run(args: argparse.Namespace) -> int:
    bucket = storage.configured_bucket(args.s3_uri)
    if bucket is None:
        print(f"no S3 location: pass --s3-uri or set {storage.S3_URI_VARIABLE}", file=sys.stderr)
        return 2
    commit = pushed_commit(args.commit)
    repository_url = https_url(git("remote", "get-url", "origin"))
    ec2 = stack.client("ec2")
    vpc_id, subnets = default_subnets(ec2)
    instance_types = [name.strip() for name in args.instance_types.split(",") if name.strip()]
    parameters = stack_parameters(
        {
            "BucketName": bucket.name,
            "BucketPrefix": bucket.prefix,
            "MaxInstances": args.max_instances,
            "InstanceTypes": instance_types,
            "EnginesPerInstance": args.engines,
            "IdleMinutes": args.idle_minutes,
            "RepositoryUrl": repository_url,
            "Commit": commit,
            "VpcId": vpc_id,
            "Subnets": subnets,
            "VolumeGiB": args.volume_gib,
        }
    )
    cloudformation = stack.client("cloudformation")
    outcome = deploy(cloudformation, args.stack, parameters)
    description = stack.describe_stack(cloudformation, args.stack)
    quota = stack.spot_quota(stack.client("service-quotas"), ec2, instance_types[0])
    summary = {
        "stack": args.stack,
        "outcome": outcome,
        "outputs": stack.outputs_of(description or {}),
        "spot_quota_vcpus": quota.vcpus,
        "instances_the_quota_allows": quota.instances,
        "instance_type": quota.instance_type,
    }
    print(json.dumps(summary, indent=2))
    if quota.instances < args.max_instances:
        print(
            f"warning: the spot quota of {quota.vcpus:g} vCPUs allows only {quota.instances} "
            f"{quota.instance_type} ({quota.vcpus_per_instance} vCPUs each), fewer than "
            f"--max-instances {args.max_instances}; ask for more in Service Quotas "
            f"({stack.SPOT_QUOTA_SERVICE}, {stack.SPOT_QUOTA_CODE})",
            file=sys.stderr,
        )
    return 0
