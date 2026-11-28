"""Tests for `reason8 cloud up|run|status|down` with stubbed AWS clients (no AWS access)."""

import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.stub import Stubber

from reason8 import cli
from reason8.cloud import run as cloud_run
from reason8.cloud import stack, status, up
from reason8.cloud.messages import BatchSettings, GameMessage, result_path

QUEUE_URL = "https://sqs.eu-central-1.amazonaws.com/000000000000/games"
START = datetime(2026, 11, 28, 10, tzinfo=UTC)


def stubbed_client(service):
    return boto3.client(
        service,
        region_name="eu-central-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@github.com:owner/reason8.git", "https://github.com/owner/reason8.git"),
        ("ssh://git@github.com/owner/reason8.git", "https://github.com/owner/reason8.git"),
        ("https://token@github.com/owner/reason8", "https://github.com/owner/reason8"),
        ("https://github.com/owner/reason8.git", "https://github.com/owner/reason8.git"),
    ],
)
def test_instances_clone_over_https_without_credentials(remote, expected):
    assert up.https_url(remote) == expected


def test_the_default_vpc_and_its_subnets():
    ec2 = stubbed_client("ec2")
    with Stubber(ec2) as stubber:
        stubber.add_response(
            "describe_vpcs",
            {"Vpcs": [{"VpcId": "vpc-1"}]},
            {"Filters": [{"Name": "is-default", "Values": ["true"]}]},
        )
        stubber.add_response(
            "describe_subnets",
            {"Subnets": [{"SubnetId": "subnet-b"}, {"SubnetId": "subnet-a"}]},
            {"Filters": [{"Name": "vpc-id", "Values": ["vpc-1"]}]},
        )
        assert up.default_subnets(ec2) == ("vpc-1", ["subnet-a", "subnet-b"])


def test_parameters_join_lists():
    assert up.stack_parameters({"Subnets": ["a", "b"], "MaxInstances": 10}) == [
        {"ParameterKey": "Subnets", "ParameterValue": "a,b"},
        {"ParameterKey": "MaxInstances", "ParameterValue": "10"},
    ]


def test_every_parameter_of_up_is_in_the_template():
    keys = {
        "BucketName", "BucketPrefix", "MaxInstances", "InstanceTypes", "EnginesPerInstance",
        "IdleMinutes", "RepositoryUrl", "Commit", "VpcId", "Subnets", "VolumeGiB",
    }  # fmt: skip
    parameters = stack.load_template()["Parameters"]
    # all but the image, which keeps its default
    assert set(parameters) - keys == {"ImageId"}


@pytest.mark.parametrize("changed", [True, False])
def test_the_spot_quota_in_instances(changed):
    service_quotas, ec2 = stubbed_client("service-quotas"), stubbed_client("ec2")
    request = {"ServiceCode": "ec2", "QuotaCode": "L-34B43A08"}
    with Stubber(service_quotas) as quotas_stub, Stubber(ec2) as ec2_stub:
        if changed:
            quotas_stub.add_response("get_service_quota", {"Quota": {"Value": 68.0}}, request)
        else:
            quotas_stub.add_client_error(
                "get_service_quota", "NoSuchResourceException", expected_params=request
            )
            quotas_stub.add_response(
                "get_aws_default_service_quota", {"Quota": {"Value": 68.0}}, request
            )
        ec2_stub.add_response(
            "describe_instance_types",
            {"InstanceTypes": [{"VCpuInfo": {"DefaultVCpus": 8}}]},
            {"InstanceTypes": ["m7a.2xlarge"]},
        )
        quota = stack.spot_quota(service_quotas, ec2, "m7a.2xlarge")
    assert (quota.vcpus, quota.instances) == (68.0, 8)


@pytest.mark.parametrize(
    ("requested", "cap", "quota", "games", "current", "expected"),
    [
        (10, 10, 50, 1000, 0, 10),
        (20, 10, 50, 1000, 0, 10),  # the cap
        (10, 10, 4, 1000, 0, 4),  # the quota
        (10, 10, 50, 12, 0, 3),  # 12 games keep 3 instances of 5 engines busy
        (10, 10, 50, 12, 6, 6),  # never lower than what runs
    ],
)
def test_desired_capacity(requested, cap, quota, games, current, expected):
    assert cloud_run.desired_capacity(requested, cap, quota, games, 5, current) == expected


def test_messages_are_sent_ten_at_a_time():
    sqs = stubbed_client("sqs")
    messages = [
        GameMessage(f"date=2026-11-01/2026-11-01_10-00-{second:02d}-000_Map.sdfz")
        for second in range(12)
    ]
    with Stubber(sqs) as stubber:
        for batch in (messages[:10], messages[10:]):
            entries = [
                {"Id": str(index), "MessageBody": message.to_json()}
                for index, message in enumerate(batch)
            ]
            stubber.add_response(
                "send_message_batch",
                {"Successful": [], "Failed": []},
                {"QueueUrl": QUEUE_URL, "Entries": entries},
            )
        cloud_run.send_messages(sqs, QUEUE_URL, messages)
        stubber.assert_no_pending_responses()


def test_instance_hours_count_each_instance_from_launch_to_termination():
    activities = [
        # launched before the batch, terminated during it: counted from the start of the batch
        {"Description": "Launching a new EC2 instance: i-0a", "StatusCode": "Successful",
         "StartTime": START - timedelta(hours=1)},
        {"Description": "Terminating EC2 instance: i-0a", "StatusCode": "Successful",
         "StartTime": START + timedelta(minutes=29), "EndTime": START + timedelta(minutes=30)},
        # still running
        {"Description": "Launching a new EC2 instance: i-0b", "StatusCode": "Successful",
         "StartTime": START + timedelta(hours=1)},
        # no spot capacity: never ran
        {"Description": "Launching a new EC2 instance.  Status Reason: no capacity",
         "StatusCode": "Failed", "StartTime": START},
    ]  # fmt: skip
    hours = status.instance_hours(activities, START, START + timedelta(hours=3))
    assert hours == pytest.approx(0.5 + 2)


def test_the_rough_cost_takes_the_median_of_the_newest_prices():
    history = [
        {"InstanceType": "m7a.2xlarge", "AvailabilityZone": "a", "SpotPrice": "0.30",
         "Timestamp": START - timedelta(hours=2)},
        {"InstanceType": "m7a.2xlarge", "AvailabilityZone": "a", "SpotPrice": "0.20",
         "Timestamp": START},
        {"InstanceType": "m7a.2xlarge", "AvailabilityZone": "b", "SpotPrice": "0.25",
         "Timestamp": START},
        {"InstanceType": "m6a.2xlarge", "AvailabilityZone": "a", "SpotPrice": "0.40",
         "Timestamp": START},
    ]  # fmt: skip
    prices = status.current_prices(history)
    assert prices[("m7a.2xlarge", "a")] == 0.20
    assert status.rough_cost(10, prices) == pytest.approx(2.5)
    assert status.rough_cost(10, {}) is None


def test_results_of_a_batch():
    games = [f"date=2026-11-0{day}/2026-11-0{day}_10-00-00-000_Map.sdfz" for day in (1, 2, 3)]
    record = {"out_area": "state-v7", "games": games}
    done = [
        result_path("state-v7", GameMessage(games[0]).replay_name).removeprefix("state-v7/"),
        "date=2026-11-02/2026-11-02_10-00-00-000_Map.jsonl.gz",  # state file only: not done
    ]
    assert status.results_of(record, done) == 1


class FakeAutoScaling:
    def __init__(self, desired=0):
        self.desired = desired
        self.set_to = []

    def describe_auto_scaling_groups(self, AutoScalingGroupNames):
        return {"AutoScalingGroups": [{"DesiredCapacity": self.desired, "MaxSize": 10}]}

    def set_desired_capacity(self, AutoScalingGroupName, DesiredCapacity, HonorCooldown):
        self.set_to.append(DesiredCapacity)


class FakeSqs:
    def __init__(self):
        self.bodies = []

    def send_message_batch(self, QueueUrl, Entries):
        self.bodies += [entry["MessageBody"] for entry in Entries]
        return {"Successful": Entries}


def test_cloud_run_queues_the_games_records_the_batch_and_starts_instances(
    bucket, tmp_path, monkeypatch, capsys
):
    names = [f"2026-11-0{day}_10-00-00-000_Map_2026.09.03.sdfz" for day in (1, 2, 3)]
    for name in names:
        bucket.write(f"replays/{GameMessage(f'date={name[:10]}/{name}').replay}", b"replay")
    done = GameMessage(f"date=2026-11-02/{names[1]}", BatchSettings(out_area="state-v7"))
    bucket.write(done.result_path, b"game table")
    listed = tmp_path / "list.txt"
    listed.write_text("# a list\n" + "".join(f"/elsewhere/{name}\n" for name in names))

    outputs = stack.StackOutputs(
        queue_url=QUEUE_URL,
        dead_letter_queue_url=QUEUE_URL + "-dead",
        group_name="reason8-cloud-workers",
        max_instances=10,
        instance_types=["m7a.2xlarge"],
        engines_per_instance=1,
        bucket_uri=f"s3://{bucket.name}/{bucket.prefix}",
        commit="0" * 40,
    )
    autoscaling, sqs = FakeAutoScaling(), FakeSqs()
    monkeypatch.setattr(stack, "read_outputs", lambda client, name: outputs)
    monkeypatch.setattr(stack, "spot_quota", lambda quotas, ec2, kind: stack.SpotQuota(68, kind, 8))
    clients = {"autoscaling": autoscaling, "sqs": sqs}
    monkeypatch.setattr(stack, "client", lambda service: clients.get(service))

    arguments = ["cloud", "run", "--list", str(listed), "--instances", "5"]
    assert cli.main([*arguments, "--out-area", "state-v7", "--max-frame", "36000"]) == 0

    summary = json.loads(capsys.readouterr().out)
    assert (summary["to_queue"], summary["done"], summary["instances"]) == (2, 1, 2)
    queued = [GameMessage.from_json(body) for body in sqs.bodies]
    assert [message.replay_name for message in queued] == [names[0], names[2]]
    assert all(message.batch.max_frame == 36000 for message in queued)
    assert autoscaling.set_to == [2]
    (record_name,) = bucket.list_files("cloud/batches")
    record = json.loads(bucket.read(f"cloud/batches/{record_name}"))
    assert record["list"] == "list.txt" and len(record["games"]) == 2
