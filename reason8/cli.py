"""The ``reason8`` command line: one command, a subcommand for each step."""

from __future__ import annotations

import argparse
import sys
from types import ModuleType

from reason8.data import download, sync
from reason8.game import maps, positions
from reason8.replays import fixture, parse, sdfz

# (name, module, summary): each module has `run(args)` and, when it takes arguments,
# `add_arguments(parser)`. A group is (name, summary, [commands]).
Command = tuple[str, ModuleType, str]
COMMANDS: list[Command | tuple[str, str, list[Command]]] = [
    ("download", download, "download replays of the selected matches"),
    ("sync", sync, "copy the data directory to or from the S3 bucket"),
    ("parse", parse, "parse replays into compact JSON"),
    ("header", sdfz, "print which engine, game and map a replay needs"),
    ("make-fixture", fixture, "make the anonymised test fixture from a parsed replay"),
    (
        "maps",
        "BAR's map metadata and start positions",
        [
            ("fetch", maps, "fetch the pinned map list"),
            ("check", positions, "how far real starts are from the recommended positions"),
        ],
    ),
]


def add_command(commands: argparse._SubParsersAction, command: Command) -> None:
    name, module, summary = command
    parser = commands.add_parser(
        name,
        help=summary,
        description=module.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    if hasattr(module, "add_arguments"):
        module.add_arguments(parser)
    parser.set_defaults(run=module.run)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reason8", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for entry in COMMANDS:
        if isinstance(entry[1], ModuleType):
            add_command(commands, entry)
            continue
        name, summary, group = entry
        group_parser = commands.add_parser(name, help=summary, description=summary)
        subcommands = group_parser.add_subparsers(dest="subcommand", required=True)
        for command in group:
            add_command(subcommands, command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
