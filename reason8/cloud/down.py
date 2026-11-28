"""Stop the cloud workers, and optionally empty the queue or delete the stack.

    uv run reason8 cloud down             # no more instances; the queue keeps its games
    uv run reason8 cloud down --purge     # also drop the games still waiting
    uv run reason8 cloud down --delete    # delete the whole stack (queues included)

Sets the group's desired capacity to 0, so its instances are terminated; the games they were
playing show up in the queue again, and a later `reason8 cloud run` (or a raised capacity)
plays them. ``--purge`` empties the queue (not the dead-letter queue). ``--delete`` deletes the
stack and waits: the queues with their messages, the role, the group. Nothing in the bucket is
deleted: results, failure records and logs stay.
"""

from __future__ import annotations

import argparse
import json
import sys

from botocore.exceptions import WaiterError

from reason8.cloud import stack
from reason8.cloud.up import WAITER_CONFIG


def add_arguments(parser: argparse.ArgumentParser) -> None:
    stack.add_stack_argument(parser)
    parser.add_argument("--purge", action="store_true", help="empty the queue too")
    parser.add_argument("--delete", action="store_true", help="delete the stack")


def run(args: argparse.Namespace) -> int:
    cloudformation = stack.client("cloudformation")
    outputs = stack.read_outputs(cloudformation, args.stack)
    stack.client("autoscaling").set_desired_capacity(
        AutoScalingGroupName=outputs.group_name, DesiredCapacity=0, HonorCooldown=False
    )
    done = {"desired_capacity": 0, "purged": False, "deleted": False}
    if args.purge:
        stack.client("sqs").purge_queue(QueueUrl=outputs.queue_url)
        done["purged"] = True
    if args.delete:
        cloudformation.delete_stack(StackName=args.stack)
        print(f"waiting for the stack {args.stack} to be deleted ...", file=sys.stderr)
        try:
            cloudformation.get_waiter("stack_delete_complete").wait(
                StackName=args.stack, WaiterConfig=WAITER_CONFIG
            )
        except WaiterError as error:
            raise SystemExit(f"the stack {args.stack} was not deleted: {error}") from error
        done["deleted"] = True
    print(json.dumps(done, indent=2))
    return 0
