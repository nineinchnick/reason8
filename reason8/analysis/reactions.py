"""How long players take to give a new order to a factory or builder that went idle.

Usage::

    uv run reason8 analysis reactions                 # re-simulated games -> <data dir>/reactions/
    uv run reason8 analysis reactions --report        # the tables of docs/research/reactions.md

A factory that finished its queue, or a builder that finished its last task, goes idle; BAR's
interface lists idle units, and a player who notices gives it new orders. The time from going
idle to the next order is the player's reaction, and the bot waits as long (ADR 0008).

Going idle is only known from a re-simulated game: the state export writes an ``idle`` line
when a factory or builder runs out of orders (format 4 and later, `reason8 headless batch`).
The orders come from the commands and selections of the parsed replay, read from its
tables (`reason8.replays.tables.open_source`; games whose replay is not parsed are
skipped): a ``COMMAND`` packet goes to the player's current selection, an ``AICOMMAND``
packet from the player's widgets to the units it lists, as in `reason8.analysis.apm`. The
reaction to an idle event is the first command the unit's player gives it at or after that
frame, if one comes within `HORIZON_SECONDS`.

Two reactions are kept per idle event: ``clicked`` (``COMMAND``: what the player did) and
``any`` (with the widgets' commands, some of which follow a click, some run on their own).

The output, in ``<data dir>/reactions/``:

``idle.parquet``
    One row per idle event of a human player: game, team, unit, unit name, its kind (``factory``,
    ``turret`` for a construction turret, ``builder`` for a mobile builder),
    frame, the player's skill, and the frame of each reaction (empty: none within the
    horizon).
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import polars as pl

from reason8.analysis.apm import (
    EVENT_FIELDS,
    SKILL_BANDS,
    WIDGET_AI,
    EventRow,
    event_stream,
    skill_band,
)
from reason8.game.unitdefs import UnitDef, game_unit_defs
from reason8.headless.state import STATE_SUFFIX, read_records
from reason8.markdown import table
from reason8.paths import data_dir, partition, partition_in_range
from reason8.replays import tables
from reason8.replays.replay import GAME_SPEED, Replay, parse_skill

HORIZON_SECONDS = 60
FACTORY, TURRET, BUILDER = "factory", "turret", "builder"
KINDS = (FACTORY, BUILDER, TURRET)
#: The first state format with idle events.
IDLE_FORMAT = 4
IDLE_SCHEMA = {
    "replay": pl.String,
    "team": pl.Int32,
    "unit_id": pl.Int32,
    "unit": pl.String,
    "kind": pl.String,  # factory, turret (a static builder) or builder (a mobile one)
    "frame": pl.Int32,
    "skill": pl.Float64,
    "clicked_frame": pl.Int32,
    "any_frame": pl.Int32,
}
#: Game phases of the report, in game seconds: (name, first, end).
PHASES = (("0:00-3:00", 0, 180), ("3:00-6:00", 180, 360), ("6:00-10:00", 360, 600))
QUANTILES = (0.25, 0.5, 0.75, 0.9)


def unit_commands(events: Iterable[EventRow]) -> dict[int, list[tuple[int, str]]]:
    """Unit id -> (frame, "clicked" or "widget") of every command a player gave it, in order.

    `events` are the selections and commands of a replay in stream order, as tuples of
    `reason8.analysis.apm.EVENT_FIELDS`.
    """
    selections: dict[int, Sequence[int]] = {}
    commands: dict[int, list[tuple[int, str]]] = {}
    for event_type, frame, player, via, ai, event_units, *_ in events:
        if event_type == "select":
            selections[player] = event_units or ()
            continue
        if event_type != "cmd" or frame is None or frame < 0:
            continue
        if via == "COMMAND":
            units, kind = selections.get(player, ()), "clicked"
        elif ai == WIDGET_AI:
            units, kind = event_units or (), "widget"
        else:
            continue
        for unit in units:
            commands.setdefault(unit, []).append((frame, kind))
    return commands


def reactions(
    idle_events: Sequence[dict], commands: Mapping[int, list[tuple[int, str]]]
) -> list[tuple[int | None, int | None]]:
    """Per idle event, the frame of the first clicked command and of the first command of
    any kind to its unit at or after it, within the horizon (None: none)."""
    horizon = HORIZON_SECONDS * GAME_SPEED
    found = []
    for event in idle_events:
        clicked = any_kind = None
        for frame, kind in commands.get(event["u"], ()):
            if frame < event["f"]:
                continue
            if frame > event["f"] + horizon:
                break
            if any_kind is None:
                any_kind = frame
            if kind == "clicked":
                clicked = frame
                break
        found.append((clicked, any_kind))
    return found


def idle_records(state_path: Path) -> tuple[dict[str, str], list[dict]]:
    """Unit def id -> name, and the idle events of a state file; none if its format has none."""
    records = read_records(state_path)
    header = next(records, None)
    if not header or header.get("t") != "header" or header.get("v", 1) < IDLE_FORMAT:
        return {}, []
    return header["unitdefs"], [record for record in records if record["t"] == "idle"]


def game_reactions(
    replay_name: str,
    names: Mapping[str, str],
    idle: Sequence[dict],
    replay: Replay,
    events: Iterable[EventRow],
) -> list[dict]:
    """The idle events of human players in one re-simulated game, with their reactions.

    `names` and `idle` are the game's `idle_records`, `replay` its header
    (`reason8.replays.tables.replay_headers`) and `events` its selections and commands.
    """
    humans = {team.team_id for team in replay.teams().values() if not team.is_ai}
    skill_of = {
        player["teamId"]: parse_skill(player.get("skill"))
        for player in replay.players
        if not player.get("spectator")
    }
    idle = [event for event in idle if event["team"] in humans]
    rows = []
    for event, (clicked, any_kind) in zip(
        idle, reactions(idle, unit_commands(events)), strict=True
    ):
        rows.append(
            {
                "replay": replay_name,
                "team": event["team"],
                "unit_id": event["u"],
                "unit": names.get(str(event["d"])),
                "kind": None,
                "frame": event["f"],
                "skill": skill_of.get(event["team"]),
                "clicked_frame": clicked,
                "any_frame": any_kind,
            }
        )
    return rows


def replay_name_of(state_path: Path) -> str:
    return state_path.name.removesuffix(STATE_SUFFIX)


def day_reactions(source: tables.Source, state_paths: Sequence[Path]) -> tuple[list[dict], int]:
    """The rows of `game_reactions` for the state files of one day, and how many games with
    idle events were skipped because their replay is not in the source."""
    idle_of = {}
    for state_path in state_paths:
        try:
            names, idle = idle_records(state_path)
        except (OSError, ValueError, KeyError) as error:
            print(f"{state_path}: {error}", flush=True)
            continue
        if idle:
            idle_of[replay_name_of(state_path)] = names, idle
    headers = tables.replay_headers(
        source.scan(tables.GAMES, idle_of).collect(),
        source.scan(tables.PLAYERS, idle_of).collect(),
    )
    stream = event_stream(source, sorted(headers)).collect()
    events_of = {
        name: list(zip(*(rows[field].to_list() for field in EVENT_FIELDS), strict=True))
        for (name,), rows in stream.group_by("replay", maintain_order=True)
    }
    rows = []
    for replay_name in sorted(headers):
        names, idle = idle_of[replay_name]
        rows += game_reactions(
            replay_name, names, idle, headers[replay_name], events_of.get(replay_name, ())
        )
    return rows, len(idle_of) - len(headers)


def measure(
    state_dir: Path,
    parsed_dir: Path,
    unit_defs: Mapping[str, UnitDef],
    jobs: int,
    *,
    tables_dir: Path | None = None,
    since: date | None = None,
    until: date | None = None,
) -> pl.DataFrame:
    """The idle events of every state file with them (format 4 and later) whose replay is
    parsed; the games whose replay is not are skipped.

    The replays are read from their tables (`reason8.replays.tables.open_source`, by
    default next to `parsed_dir`), a day per process.
    """
    state_paths_of: dict[str, list[Path]] = defaultdict(list)
    for state_path in sorted(state_dir.glob(f"date=*/*{STATE_SUFFIX}")):
        if partition_in_range(state_path.parent.name, since, until):
            state_paths_of[partition(state_path.name)].append(state_path)
    source = tables.open_source(
        parsed_dir,
        parsed_dir.parent / tables.AREA if tables_dir is None else tables_dir,
        since=since,
        until=until,
        replays=[
            replay_name_of(state_path)
            for state_paths in state_paths_of.values()
            for state_path in state_paths
        ],
        tables=(tables.GAMES, tables.PLAYERS, tables.COMMANDS, tables.SELECTIONS),
    )
    for name, error in source.unreadable.items():
        print(f"{name}: {error}", flush=True)
    sources = {
        partition(next(iter(names))): day
        for day in source.by_day()
        if (names := day.stored | set(day.converted))
    }
    rows = []
    unparsed = 0
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        days = sorted(state_paths_of)
        for day_rows, day_unparsed in pool.map(
            day_reactions,
            [sources.get(day, tables.Source({})) for day in days],
            [state_paths_of[day] for day in days],
        ):
            rows += day_rows
            unparsed += day_unparsed
    if unparsed:
        print(f"skipped {unparsed} games whose replay is not parsed", flush=True)
    frame = pl.DataFrame(rows, schema=IDLE_SCHEMA)
    kinds = unit_kinds(unit_defs)
    return frame.with_columns(
        kind=pl.col("unit").replace_strict(kinds, default=BUILDER, return_dtype=pl.String)
    )


def unit_kinds(unit_defs: Mapping[str, UnitDef]) -> dict[str, str]:
    """Factory or turret, by unit name, for the static units that build; every other unit
    that goes idle is a (mobile) builder."""
    kinds = {}
    for name, unit in unit_defs.items():
        if unit.is_static and unit.build_options:
            kinds[name] = FACTORY
        elif unit.is_static and unit.number("workertime") > 0:
            kinds[name] = TURRET
    return kinds


def phase_of(column: str = "frame") -> pl.Expr:
    expression = pl.lit(None, dtype=pl.String)
    for name, first, end in reversed(PHASES):
        seconds = pl.col(column) / GAME_SPEED
        expression = (
            pl.when((seconds >= first) & (seconds < end)).then(pl.lit(name)).otherwise(expression)
        )
    return expression.alias("phase")


def delay_rows(
    idle: pl.DataFrame, group: str, order: Sequence[str], reaction: str
) -> list[list[str]]:
    """Per value of `group`: events, share answered within the horizon, and quantiles of the
    delay in seconds of those answered."""
    delays = idle.with_columns(delay=(pl.col(f"{reaction}_frame") - pl.col("frame")) / GAME_SPEED)
    rows = []
    for value in order:
        part = delays.filter(pl.col(group) == value) if value != "all" else delays
        if part.is_empty():
            continue
        answered = part.filter(pl.col("delay").is_not_null())
        quantiles = [
            f"{answered['delay'].quantile(share, interpolation='nearest'):.1f}"
            if answered.height
            else ""
            for share in QUANTILES
        ]
        rows.append(
            [value, str(part.height), f"{100 * answered.height / part.height:.0f}%", *quantiles]
        )
    return rows


def report(idle: pl.DataFrame) -> str:
    idle = idle.with_columns(
        skill_band(),
        phase_of(),
    )
    header_tail = ["events", "answered", *[f"p{round(100 * share)} (s)" for share in QUANTILES]]
    bands = [name for name, _, _ in SKILL_BANDS] + ["all"]
    lines = [
        f"{idle['replay'].n_unique()} games, {idle.height} idle events of human players' "
        f"factories and builders; answered: an order within {HORIZON_SECONDS} s.",
        "",
    ]
    for reaction, title in (("clicked", "Clicked orders"), ("any", "Any order, widgets included")):
        lines += [f"## {title}", ""]
        for kind in KINDS:
            part = idle.filter(pl.col("kind") == kind)
            lines += [f"### {kind.capitalize()}, by skill", ""]
            lines += table(
                ["skill band", *header_tail], delay_rows(part, "skill_band", bands, reaction)
            )
            lines += ["", f"### {kind.capitalize()}, by phase", ""]
            lines += table(
                ["phase", *header_tail],
                delay_rows(part, "phase", [name for name, _, _ in PHASES] + ["all"], reaction),
            )
            lines.append("")
    return "\n".join(lines)


def out_path(out_dir: Path) -> Path:
    return out_dir / "idle.parquet"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", type=Path, help="default: <data dir>/state")
    tables.add_source_arguments(parser)
    parser.add_argument("--out", type=Path, help="default: <data dir>/reactions")
    parser.add_argument("--data-dir", default="data/bar", help="content dir with the game")
    parser.add_argument(
        "--game",
        default="Beyond All Reason test-32018-ad135b9",
        help="a game version whose unit files tell factories from builders",
    )
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--report", action="store_true", help="print the tables of a run")


def run(args: argparse.Namespace) -> int:
    out_dir = args.out or data_dir() / "reactions"
    if args.report:
        print(report(pl.read_parquet(out_path(out_dir))))
        return 0
    unit_defs = game_unit_defs(Path(args.data_dir).resolve(), args.game)
    idle = measure(
        args.state_dir or data_dir() / "state",
        args.parsed,
        unit_defs,
        args.jobs,
        tables_dir=args.tables,
        since=args.since,
        until=args.until,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    idle.write_parquet(out_path(out_dir))
    print(f"{idle.height} idle events from {idle['replay'].n_unique()} games -> {out_dir}")
    return 0
