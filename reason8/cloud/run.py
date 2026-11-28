"""Queue the games of a replay list and start the cloud workers.

    uv run reason8 cloud run --list data/workers/context.txt --instances 10 \\
        --max-frame 36000 --out-area state-v7
    uv run reason8 cloud run --list FILE --instances 10 --dry-run

The list is the one `reason8 headless batch --list` reads and `reason8 headless list` writes:
one replay path per line, ``#`` lines skipped. Only the file names count: each game's replay is
taken from its date partition of the bucket's ``replays`` area (push the replays there first
with `reason8 sync push replays`). Games whose result (their ``game`` table) is already in the
out area of the bucket are left out, and so are games whose replay is not in the bucket.

Each game becomes one message of the queue, with the batch's settings (`reason8.cloud.messages`),
and the batch is recorded in ``cloud/batches/<time>.json`` for `reason8 cloud status`. Then the
group's desired capacity is raised to the smallest of ``--instances``, the stack's cap, what
the spot vCPU quota allows and the instances the games can keep busy. Workers stop by
themselves when the queue is empty; `reason8 cloud down` stops them earlier.

A game queued twice is played twice (the second time to the same result), so run a list once,
or empty the queue with `reason8 cloud down --purge` before queueing it again.

``--out-area`` is the area of the bucket the results go to: ``state``, or ``state-<name>``
for a batch in a state format of its own, so that two formats never mix.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reason8.cloud import stack
from reason8.cloud.messages import (
    BATCHES_DIRECTORY,
    DEFAULT_OUT_AREA,
    BatchSettings,
    GameMessage,
    MessageError,
    plan_batch,
)
from reason8.data.download import REPLAYS_DIRECTORY
from reason8.data.storage import Bucket
from reason8.headless.batch import read_list

#: The most messages one SendMessageBatch request takes.
SEND_BATCH_SIZE = 10


def send_messages(sqs: Any, queue_url: str, messages: list[GameMessage]) -> None:
    """Put the messages on the queue, ten per request; raises if any of them was refused."""
    for start in range(0, len(messages), SEND_BATCH_SIZE):
        entries = [
            {"Id": str(index), "MessageBody": message.to_json()}
            for index, message in enumerate(messages[start : start + SEND_BATCH_SIZE])
        ]
        response = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        if response.get("Failed"):
            raise RuntimeError(f"the queue refused messages: {response['Failed'][:3]}")


def desired_capacity(
    requested: int, cap: int, quota_allows: int, games: int, engines: int, current: int
) -> int:
    """The instances to run: no more than asked for, the cap or the quota allow, nor than the
    games can keep busy; never fewer than already run (another batch may be running)."""
    busy = math.ceil(games / max(1, engines))
    return max(current, min(requested, cap, quota_allows, busy))


def batch_record(
    list_file: Path, batch: BatchSettings, messages: list[GameMessage], started_at: datetime
) -> dict:
    return {
        "started_at": started_at.isoformat(timespec="seconds"),
        "list": list_file.name,
        "out_area": batch.out_area,
        "max_frame": batch.max_frame,
        "snapshot_seconds": batch.snapshot_seconds,
        "timeout": batch.timeout,
        "settings": list(batch.settings),
        "games": [message.replay for message in messages],
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    stack.add_stack_argument(parser)
    parser.add_argument("--list", type=Path, required=True, help="the replay list of the batch")
    parser.add_argument("--instances", type=int, required=True, help="instances to run at most")
    parser.add_argument(
        "--max-frame", type=int, default=0, help="stop at this frame (0: play the whole game)"
    )
    parser.add_argument(
        "--out-area",
        default=DEFAULT_OUT_AREA,
        help=f"area of the bucket for the results: state or state-<name> "
        f"(default {DEFAULT_OUT_AREA})",
    )
    parser.add_argument("--snapshot-seconds", type=float, default=5)
    parser.add_argument("--timeout", type=float, default=3600, help="kill an engine after this")
    parser.add_argument(
        "--set", action="append", default=[], metavar="KEY=VALUE", help="engine setting"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="count the games, queue nothing, start nothing"
    )


def run(args: argparse.Namespace) -> int:
    try:
        batch = BatchSettings(
            out_area=args.out_area,
            max_frame=args.max_frame,
            snapshot_seconds=args.snapshot_seconds,
            timeout=args.timeout,
            settings=tuple(args.set),
        )
    except MessageError as error:
        print(error, file=sys.stderr)
        return 2
    outputs = stack.read_outputs(stack.client("cloudformation"), args.stack)
    bucket = Bucket(outputs.bucket_uri)
    plan = plan_batch(
        read_list(args.list),
        batch,
        results=bucket.list_files(batch.out_area),
        replays_in_bucket=bucket.list_files(REPLAYS_DIRECTORY),
    )
    quota = stack.spot_quota(
        stack.client("service-quotas"), stack.client("ec2"), outputs.instance_types[0]
    )
    autoscaling = stack.client("autoscaling")
    (group,) = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[outputs.group_name])[
        "AutoScalingGroups"
    ]
    current = group["DesiredCapacity"]
    wanted = (
        desired_capacity(
            args.instances,
            outputs.max_instances,
            quota.instances,
            len(plan.messages),
            outputs.engines_per_instance,
            current,
        )
        if plan.messages
        else current
    )
    summary = {
        "to_queue": len(plan.messages),
        "done": plan.done,
        "missing_replay": plan.missing_replay,
        "repeated": plan.repeated,
        "out_area": batch.out_area,
        "instances": wanted,
        "instances_before": current,
        "cap": outputs.max_instances,
        "instances_the_quota_allows": quota.instances,
    }
    if args.dry_run:
        print(json.dumps({**summary, "dry_run": True}, indent=2))
        return 0
    if plan.messages:
        started_at = datetime.now(UTC)
        send_messages(stack.client("sqs"), outputs.queue_url, plan.messages)
        record = batch_record(args.list, batch, plan.messages, started_at)
        record_name = started_at.strftime("%Y-%m-%dT%H-%M-%SZ") + ".json"
        bucket.write(f"{BATCHES_DIRECTORY}/{record_name}", json.dumps(record, indent=1).encode())
        if wanted != current:
            autoscaling.set_desired_capacity(
                AutoScalingGroupName=outputs.group_name, DesiredCapacity=wanted, HonorCooldown=False
            )
    print(json.dumps(summary, indent=2))
    if wanted < args.instances and plan.messages:
        print(
            f"running {wanted} instances, not {args.instances}: the cap is "
            f"{outputs.max_instances}, the spot quota allows {quota.instances}, and "
            f"{len(plan.messages)} games keep {outputs.engines_per_instance} engines each busy "
            f"on {math.ceil(len(plan.messages) / outputs.engines_per_instance)} instances",
            file=sys.stderr,
        )
    return 0
