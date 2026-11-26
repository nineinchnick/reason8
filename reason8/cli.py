"""The ``reason8`` command line: one command, a subcommand for each step."""

from __future__ import annotations

import argparse
import sys
from types import ModuleType

from reason8.analysis import apm, map_meta, opening_shift
from reason8.bot import build, check, export, game
from reason8.data import download, migrate, sync
from reason8.evaluation import games as evaluation_games
from reason8.evaluation import openings as evaluation_openings
from reason8.evaluation import report as evaluation_report
from reason8.game import maps, positions
from reason8.headless import batch, run, setup, state
from reason8.models import evaluate
from reason8.openings import contact, dataset
from reason8.paths import LayoutError
from reason8.replays import fixture, parse, sdfz, tables, widgets

# (name, module, summary): each module has `run(args)` and, when it takes arguments,
# `add_arguments(parser)`. A group is (name, summary, [commands]).
Command = tuple[str, ModuleType, str]
COMMANDS: list[Command | tuple[str, str, list[Command]]] = [
    ("download", download, "download replays of the selected matches"),
    ("sync", sync, "copy the data directory to or from the S3 bucket"),
    (
        "storage",
        "the layout of the data directory and the S3 bucket",
        [("migrate-layout", migrate, "move flat data files into the date partitions")],
    ),
    ("parse", parse, "parse replays into compact JSON"),
    ("tables", tables, "build the Parquet tables of the parsed replays"),
    ("header", sdfz, "print which engine, game and map a replay needs"),
    ("widgets", widgets, "read the user widgets of each player from the replays"),
    ("make-fixture", fixture, "make the anonymised test fixture from a parsed replay"),
    (
        "maps",
        "BAR's map metadata and start positions",
        [
            ("fetch", maps, "fetch the pinned map list"),
            ("check", positions, "how far real starts are from the recommended positions"),
        ],
    ),
    (
        "headless",
        "run games and replays in a headless engine",
        [
            ("setup", setup, "fetch the engine, game and map a run needs"),
            ("run", run, "run a start script or play back a replay"),
            ("batch", batch, "play many replays and keep their state"),
            ("state", state, "summarise a state file"),
        ],
    ),
    ("contact", contact, "measure first contact in re-simulated replays"),
    ("dataset", dataset, "build the opening dataset from parsed replays"),
    ("baseline", evaluate, "fit, score and save the next-build baselines"),
    (
        "bot",
        "the Reason8 AI, a BARb variant",
        [
            ("build", build, "build the AI folder from BARb and ai/Reason8"),
            ("export", export, "export the model's openings for the AI"),
            ("game", game, "write the start script of an 8v8 AI game"),
            ("check", check, "check from a replay that the AI played its opening"),
        ],
    ),
    (
        "eval",
        "play evaluation games and compare the AIs (ADR 0003)",
        [
            ("games", evaluation_games, "play paired 8v8 games and measure each team"),
            ("report", evaluation_report, "compare the evaluated AI with its opponent"),
            ("openings", evaluation_openings, "tell the bot's openings from human ones"),
        ],
    ),
    (
        "analysis",
        "measurements behind the research docs",
        [
            ("opening-shift", opening_shift, "how openings shift between groups of games"),
            ("map-meta", map_meta, "the opening meta of each start position"),
            ("apm", apm, "how many actions per minute people take, by phase and skill"),
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
    try:
        return args.run(args)
    except LayoutError as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
