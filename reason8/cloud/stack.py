"""The CloudFormation stack of the cloud workers and what the commands read from it.

The template (``stack.yaml`` next to this module) holds everything a run needs: the queue of
games and its dead-letter queue, the workers' role, a launch template that sets an instance up
with cloud-init, and an Auto Scaling group of spot instances that is empty until
`reason8 cloud run` raises its desired capacity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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
