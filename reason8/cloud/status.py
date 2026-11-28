"""How far the cloud batch is, and roughly what it cost so far.

    uv run reason8 cloud status

Prints one JSON object: the games waiting in the queue, in flight (being played) and
dead-lettered (failed three times; their failure records are in ``cloud/failures/``), the
group's instances, and for the latest batch (`reason8 cloud run`) how many of its games have
their results in the bucket. The cost is rough: the instance hours since the batch started,
from the group's launch and terminate activities, times the median of the current spot prices
of the stack's instance types. Storage, requests and the volumes are left out.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from reason8.cloud import stack
from reason8.cloud.messages import BATCHES_DIRECTORY, GameMessage, result_path
from reason8.data.storage import Bucket

LAUNCH_PATTERN = re.compile(r"Launching a new EC2 instance: (i-[0-9a-f]+)")
TERMINATE_PATTERN = re.compile(r"Terminating EC2 instance: (i-[0-9a-f]+)")
SPOT_PRODUCT = "Linux/UNIX"


def instance_hours(activities: Iterable[dict], since: datetime, now: datetime) -> float:
    """Hours the group's instances ran between `since` and `now`, from its scaling activities:
    from each instance's launch to its termination, or to now while it runs."""
    launched: dict[str, datetime] = {}
    terminated: dict[str, datetime] = {}
    for activity in activities:
        description = activity.get("Description", "")
        launch = LAUNCH_PATTERN.search(description)
        if launch and activity.get("StatusCode") == "Successful":
            launched[launch.group(1)] = activity["StartTime"]
        terminate = TERMINATE_PATTERN.search(description)
        if terminate:
            terminated[terminate.group(1)] = activity.get("EndTime") or activity["StartTime"]
    seconds = 0.0
    for instance, start in launched.items():
        end = min(terminated.get(instance, now), now)
        seconds += max(0.0, (end - max(start, since)).total_seconds())
    return seconds / 3600


def current_prices(history: Iterable[dict]) -> dict[tuple[str, str], float]:
    """The newest spot price of each instance type and availability zone, in USD per hour."""
    newest: dict[tuple[str, str], tuple[datetime, float]] = {}
    for entry in history:
        key = (entry["InstanceType"], entry["AvailabilityZone"])
        if key not in newest or entry["Timestamp"] > newest[key][0]:
            newest[key] = (entry["Timestamp"], float(entry["SpotPrice"]))
    return {key: price for key, (_, price) in newest.items()}


def rough_cost(hours: float, prices: dict[tuple[str, str], float]) -> float | None:
    """`hours` at the median of `prices`; ``None`` without prices."""
    if not prices:
        return None
    return hours * statistics.median(prices.values())


def latest_batch(bucket: Bucket) -> dict | None:
    """The record of the newest batch (`reason8 cloud run`), or ``None``."""
    names = [name for name in bucket.list_files(BATCHES_DIRECTORY) if name.endswith(".json")]
    if not names:
        return None
    contents = bucket.read(f"{BATCHES_DIRECTORY}/{max(names)}")
    return json.loads(contents) if contents else None


def results_of(record: dict, results: Iterable[str]) -> int:
    """How many games of a batch have their result among `results` (paths in the out area)."""
    present = set(results)
    out_area = record["out_area"]
    return sum(
        result_path(out_area, GameMessage(replay).replay_name).removeprefix(out_area + "/")
        in present
        for replay in record["games"]
    )


def queue_counts(sqs: Any, queue_url: str) -> dict[str, int]:
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return {
        "waiting": int(attributes["ApproximateNumberOfMessages"]),
        "in_flight": int(attributes["ApproximateNumberOfMessagesNotVisible"]),
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    stack.add_stack_argument(parser)


def run(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    outputs = stack.read_outputs(stack.client("cloudformation"), args.stack)
    sqs = stack.client("sqs")
    games = queue_counts(sqs, outputs.queue_url)
    games["dead_lettered"] = queue_counts(sqs, outputs.dead_letter_queue_url)["waiting"]
    autoscaling = stack.client("autoscaling")
    (group,) = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[outputs.group_name])[
        "AutoScalingGroups"
    ]
    states: dict[str, int] = {}
    for instance in group["Instances"]:
        states[instance["LifecycleState"]] = states.get(instance["LifecycleState"], 0) + 1
    summary: dict[str, Any] = {
        "games": games,
        "instances": {"desired": group["DesiredCapacity"], "cap": group["MaxSize"], **states},
        "commit": outputs.commit,
    }
    bucket = Bucket(outputs.bucket_uri)
    record = latest_batch(bucket)
    if record is not None:
        since = datetime.fromisoformat(record["started_at"])
        activities = [
            activity
            for page in autoscaling.get_paginator("describe_scaling_activities").paginate(
                AutoScalingGroupName=outputs.group_name
            )
            for activity in page["Activities"]
        ]
        hours = instance_hours(activities, since, now)
        history = stack.client("ec2").describe_spot_price_history(
            InstanceTypes=outputs.instance_types,
            ProductDescriptions=[SPOT_PRODUCT],
            StartTime=now,
        )["SpotPriceHistory"]
        cost = rough_cost(hours, current_prices(history))
        summary["batch"] = {
            "started_at": record["started_at"],
            "list": record["list"],
            "out_area": record["out_area"],
            "games": len(record["games"]),
            "results": results_of(record, bucket.list_files(record["out_area"])),
            "instance_hours": round(hours, 2),
            "rough_cost_usd": round(cost, 2) if cost is not None else None,
        }
    print(json.dumps(summary, indent=2))
    return 0
