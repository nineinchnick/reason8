"""The CloudFormation stack of the cloud workers and what the commands read from it.

The template (``stack.yaml`` next to this module) holds everything a run needs: the queue of
games and its dead-letter queue, the workers' role, a launch template that sets an instance up
with cloud-init, and an Auto Scaling group of spot instances that is empty until
`reason8 cloud run` raises its desired capacity.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import yaml
from botocore.exceptions import ClientError

TEMPLATE_PATH = Path(__file__).with_name("stack.yaml")


class TemplateLoader(yaml.SafeLoader):
    """Reads CloudFormation's short forms (``!Ref``, ``!Sub``, ...) as ``{"Fn::Name": ...}``."""


def _intrinsic_function(loader: TemplateLoader, tag_suffix: str, node: yaml.Node) -> dict:
    name = "Ref" if tag_suffix == "Ref" else f"Fn::{tag_suffix}"
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
        if tag_suffix == "GetAtt":
            value = value.split(".", 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {name: value}


TemplateLoader.add_multi_constructor("!", _intrinsic_function)


def template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def load_template() -> dict:
    """The template as a dictionary, short forms written out."""
    return yaml.load(template_text(), Loader=TemplateLoader)


DEFAULT_STACK_NAME = "reason8-cloud"
#: Service Quotas: "All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests", in vCPUs.
SPOT_QUOTA_SERVICE = "ec2"
SPOT_QUOTA_CODE = "L-34B43A08"


@dataclass(frozen=True)
class StackOutputs:
    """What the commands need of a deployed stack (its outputs)."""

    queue_url: str
    dead_letter_queue_url: str
    group_name: str
    max_instances: int
    #: The first one is the default, by which the quota and the cost are reckoned.
    instance_types: list[str]
    engines_per_instance: int
    bucket_uri: str
    commit: str

    @classmethod
    def from_outputs(cls, outputs: dict[str, str]) -> StackOutputs:
        return cls(
            queue_url=outputs["QueueUrl"],
            dead_letter_queue_url=outputs["DeadLetterQueueUrl"],
            group_name=outputs["GroupName"],
            max_instances=int(outputs["MaxInstances"]),
            instance_types=outputs["InstanceTypes"].split(","),
            engines_per_instance=int(outputs["EnginesPerInstance"]),
            bucket_uri=outputs["BucketUri"],
            commit=outputs["Commit"],
        )


def client(service: str) -> Any:
    """A boto3 client; region and credentials come from the usual AWS configuration."""
    return boto3.client(service)


def describe_stack(cloudformation: Any, stack_name: str) -> dict | None:
    """The stack's description, or ``None`` when there is no such stack."""
    try:
        return cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
    except ClientError as error:
        if "does not exist" in str(error):
            return None
        raise


def outputs_of(description: dict) -> dict[str, str]:
    return {output["OutputKey"]: output["OutputValue"] for output in description.get("Outputs", [])}


def read_outputs(cloudformation: Any, stack_name: str) -> StackOutputs:
    description = describe_stack(cloudformation, stack_name)
    if description is None:
        raise SystemExit(f"no stack {stack_name!r}: create it with `reason8 cloud up`")
    return StackOutputs.from_outputs(outputs_of(description))


def add_stack_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--stack",
        default=DEFAULT_STACK_NAME,
        help=f"CloudFormation stack name (default {DEFAULT_STACK_NAME})",
    )


@dataclass(frozen=True)
class SpotQuota:
    #: The account's quota of running spot vCPUs (standard instance families) in the region.
    vcpus: float
    instance_type: str
    vcpus_per_instance: int

    @property
    def instances(self) -> int:
        """How many instances of the type the quota allows."""
        return int(self.vcpus // self.vcpus_per_instance)


def spot_quota(service_quotas: Any, ec2: Any, instance_type: str) -> SpotQuota:
    """The spot vCPU quota and how many instances of `instance_type` it allows."""
    try:
        quota = service_quotas.get_service_quota(
            ServiceCode=SPOT_QUOTA_SERVICE, QuotaCode=SPOT_QUOTA_CODE
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "NoSuchResourceException":
            raise
        # never changed: only the default is known
        quota = service_quotas.get_aws_default_service_quota(
            ServiceCode=SPOT_QUOTA_SERVICE, QuotaCode=SPOT_QUOTA_CODE
        )
    described = ec2.describe_instance_types(InstanceTypes=[instance_type])["InstanceTypes"][0]
    return SpotQuota(
        vcpus=float(quota["Quota"]["Value"]),
        instance_type=instance_type,
        vcpus_per_instance=int(described["VCpuInfo"]["DefaultVCpus"]),
    )
