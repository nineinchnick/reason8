"""Tests for the CloudFormation template of the cloud workers (no AWS involved)."""

import re
import shutil
import subprocess

import pytest

from reason8.cloud import stack


@pytest.fixture(scope="module")
def template():
    return stack.load_template()


def resources_of_type(template, resource_type):
    return {
        name: resource["Properties"]
        for name, resource in template["Resources"].items()
        if resource["Type"] == resource_type
    }


def test_the_group_is_capped_starts_empty_and_runs_spot_only(template):
    (group,) = resources_of_type(template, "AWS::AutoScaling::AutoScalingGroup").values()
    assert template["Parameters"]["MaxInstances"]["Default"] == 10
    assert group["MaxSize"] == {"Ref": "MaxInstances"}
    assert group["MinSize"] == "0"
    # left out so that a stack update never resets what `cloud run` set
    assert "DesiredCapacity" not in group
    distribution = group["MixedInstancesPolicy"]["InstancesDistribution"]
    assert distribution["OnDemandBaseCapacity"] == 0
    assert distribution["OnDemandPercentageAboveBaseCapacity"] == 0
    assert distribution["SpotAllocationStrategy"] == "price-capacity-optimized"
    assert template["Parameters"]["InstanceTypes"]["Default"] == "m7a.2xlarge"


def test_nothing_can_reach_the_instances(template):
    (group,) = resources_of_type(template, "AWS::EC2::SecurityGroup").values()
    assert "SecurityGroupIngress" not in group
    assert not resources_of_type(template, "AWS::EC2::SecurityGroupIngress")
    (launch_template,) = resources_of_type(template, "AWS::EC2::LaunchTemplate").values()
    data = launch_template["LaunchTemplateData"]
    assert "KeyName" not in data
    assert data["MetadataOptions"]["HttpTokens"] == "required"


def test_failed_games_go_to_the_dead_letter_queue_after_three_tries(template):
    queue = template["Resources"]["GameQueue"]["Properties"]
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 3


def test_the_workers_write_only_results_failures_and_logs(template):
    role = template["Resources"]["WorkerRole"]["Properties"]
    (policy,) = role["Policies"]
    statements = {
        statement["Sid"]: statement for statement in policy["PolicyDocument"]["Statement"]
    }
    written = [
        resource["Fn::Sub"].rpartition("${BucketPrefix}")[2]
        for resource in statements["WriteResultsFailuresAndLogs"]["Resource"]
    ]
    assert written == ["state/*", "state-*", "cloud/failures/*", "cloud/logs/*"]
    assert statements["ReadReplaysAndContent"]["Action"] == "s3:GetObject"
    readable = [item["Fn::Sub"] for item in statements["ReadReplaysAndContent"]["Resource"]]
    assert [path.split("${BucketPrefix}")[1] for path in readable] == [
        "replays/*",
        "cloud/content/*",
    ]


def test_the_user_data_is_a_valid_shell_script(template, tmp_path):
    launch_template = template["Resources"]["WorkerLaunchTemplate"]["Properties"]
    script = launch_template["LaunchTemplateData"]["UserData"]["Fn::Base64"]["Fn::Sub"]
    assert "reason8 cloud worker" in script
    path = tmp_path / "user-data.sh"
    path.write_text(re.sub(r"\$\{[A-Za-z:]+\}", "value", script))
    if shutil.which("bash") is None:
        pytest.skip("no bash")
    subprocess.run(["bash", "-n", str(path)], check=True)
