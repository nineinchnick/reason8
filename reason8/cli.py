"""The ``reason8`` command line: one command, a subcommand for each step."""

from __future__ import annotations

import argparse
import sys
from types import ModuleType

from reason8.analysis import apm, map_meta, opening_shift, play_quality, reactions
from reason8.bot import build, check, export, game, next_order
from reason8.context import check as context_check
from reason8.context import measure as context_measure
from reason8.context import sample as context_sample
from reason8.context import table as context_table
from reason8.data import download, sync
from reason8.evaluation import games as evaluation_games
from reason8.evaluation import openings as evaluation_openings
from reason8.evaluation import report as evaluation_report
from reason8.game import maps, positions
from reason8.headless import batch, batch_list, run, setup, state
from reason8.headless import tables as state_tables
from reason8.models import evaluate
from reason8.openings import contact, dataset
from reason8.paths import LayoutError
from reason8.replays import fixture, parse, sdfz, widgets

# (name, module, summary): each module has `run(args)` and, when it takes arguments,
# `add_arguments(parser)`. A group is (name, summary, [commands]).
Command = tuple[str, ModuleType, str]
COMMANDS: list[Command | tuple[str, str, list[Command]]] = [
    ("download", download, "download replays of the selected matches"),
    ("sync", sync, "copy the data directory to or from the S3 bucket"),
    ("parse", parse, "parse replays into the Parquet tables"),
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
            ("list", batch_list, "write the replay list of a batch from a sample"),
            ("state", state, "summarise a state file"),
            ("tables", state_tables, "convert state files to Parquet tables"),
        ],
    ),
    ("contact", contact, "measure first contact in re-simulated replays"),
    ("dataset", dataset, "build the opening dataset from parsed replays"),
    ("baseline", evaluate, "fit, score and save the next-build baselines"),
    (
        "context",
        "the decision table: opening orders with the game state (docs/research/context.md)",
        [
            ("sample", context_sample, "draw the games the decision table is built from"),
            ("build", context_table, "join the orders of re-simulated games with their state"),
            ("check", context_check, "check the joined state against the state tables"),
            ("measure", context_measure, "measure what each kind of context adds"),
        ],
    ),
    (
        "bot",
        "the Reason8 AI, a BARb variant",
        [
            ("build", build, "build the AI folder from BARb and ai/Reason8"),
            ("export", export, "export the model's openings for the AI"),
            (
                "export-next-order",
                next_order,
                "export what the bot uses when the model decides orders",
            ),
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
            ("reactions", reactions, "how long people take to give an idle unit new orders"),
            ("play-quality", play_quality, "scores of how well a player played the opening"),
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
