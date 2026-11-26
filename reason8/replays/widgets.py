"""Read the user widgets each player had installed from the replays.

Usage::

    uv run reason8 widgets                             # data/replays -> data/widgets/
    uv run reason8 widgets --since 2026-11-01 --out OUT --jobs 24

Since November 2025 BAR's "Analytics - Widgets" widget (``luaui/Widgets/ana_report_widgets.lua``)
sends, one second into the game, a list of the player's *user* widgets: those installed in
the player's own ``LuaUI/Widgets`` folder, not the ones that ship with the game. It goes out
as a LuaUI message (``NETMSG_LUAMSG``) ``complex-match-event:<base64 JSON>`` with
``eventtype`` ``widgets_report``, so every replay keeps it. A player with no user widgets
sends no report. Each widget has a ``name``, ``author``, ``desc`` (cut at 100 characters),
the MD5 ``hash`` of its file and a ``state``: 1 enabled and running, 0 disabled, -1 enabled
but not running. At most 50 widgets are listed (``truncated`` says when there were more).
The message also holds the player's name, which is not kept.

sdfz-demo-parser drops these messages with the other Lua messages, so they are read
straight from the demo stream. The output, in ``<data dir>/widgets/``:

``replays.parquet``
    One row per replay read: the lobby options that restrict user widgets, the number of
    reports, and the error if the replay could not be read.
``reports.parquet``
    One row per report of a player (spectators' reports are left out): the player and their
    team, the game frame of the report, and the widgets.

The widgets that automate build orders are named in `AUTOMATION_WIDGETS`; see
docs/research/automation-widgets.md.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import json
import re
import struct
import sys
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from reason8.paths import data_dir, find_files
from reason8.replays.parse import default_jobs
from reason8.replays.sdfz import DemoError, iter_packets, parse_header, script_value

PACKET_LUAMSG = 50
# id u8, size u16, player u8, script u16, mode u8, then the message
LUAMSG_HEADER = struct.Struct("<BHBHB")
MATCH_EVENT_PREFIX = b"complex-match-event:"
WIDGETS_REPORT = "widgets_report"
_URL_SAFE = bytes.maketrans(b"-_", b"+/")

REPLAYS_FILE = "replays.parquet"
REPORTS_FILE = "reports.parquet"
ENABLED = 1  # the widget's state when it is enabled and running

# Lobby options that restrict user widgets (BAR's doc/RestrictedUserWidgets.md):
# `allowuserwidgets` 0 loads none, `allowunitcontrolwidgets` 0 keeps user widgets from
# giving orders, and an anonymous team-colour mode turns user widgets off.
WIDGET_OPTIONS = ("allowuserwidgets", "allowunitcontrolwidgets", "teamcolors_anonymous_mode")


def unit_control_allowed(options: Mapping[str, Any]) -> bool:
    """Whether a game's lobby options let user widgets give orders.

    Both options default to on; the anonymous team-colour modes turn user widgets off.
    """

    def is_on(name: str) -> bool:
        return str(options.get(name, "1")).strip().lower() not in ("0", "false")

    anonymous = str(options.get("teamcolors_anonymous_mode", "disabled")).strip().lower()
    return (
        is_on("allowuserwidgets")
        and is_on("allowunitcontrolwidgets")
        and anonymous in ("disabled", "")
    )


# User widgets that give build orders for the player, by the name they report. See
# docs/research/automation-widgets.md for how they were picked.
AUTOMATION_WIDGETS: frozenset[str] = frozenset(
    {
        # take over constructors and build an economy or a build order
        "Build Orders",
        "OP Macro",
        "Economy Assist V2 (Rebuild)",
        "Macro Copilot (Safe)",
        "Build Order Practice Bot",
        "BAR Front Macro",
        "Apex Copilot",
        "EcoPilot Adaptive (experimental)",
        # copy or spread the player's build orders over more constructors
        "Constructors copy queue of Constructors",
        "\N{CLIPBOARD} Copy Queue v2",
        "Build Split",
        "Build Split - alternative",
        # move factory orders to the front of the queue
        "Factory Always-Alt Queue",
    }
)


@dataclass(frozen=True)
class Widget:
    name: str
    author: str | None
    hash: str | None
    state: int
    description: str | None


@dataclass(frozen=True)
class WidgetReport:
    player_id: int
    frame: int | None
    widget_count: int
    truncated: bool
    widgets: tuple[Widget, ...]


def decode_match_event(message: bytes) -> dict[str, Any] | None:
    """The JSON of a ``complex-match-event:`` message, or None for any other message."""
    if not message.startswith(MATCH_EVENT_PREFIX):
        return None
    encoded = message[len(MATCH_EVENT_PREFIX) :].strip()
    encoded += b"=" * (-len(encoded) % 4)
    try:
        # BAR encodes with the standard alphabet; accept the URL-safe one too.
        event = json.loads(base64.b64decode(encoded.translate(_URL_SAFE), validate=True))
    except binascii.Error, ValueError, UnicodeDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def widget_report(player_id: int, event: Mapping[str, Any]) -> WidgetReport | None:
    """The report of a ``widgets_report`` event, without the player's name."""
    if event.get("eventtype") != WIDGETS_REPORT or not isinstance(event.get("widgets"), list):
        return None
    widgets = tuple(
        Widget(
            name=str(entry.get("name")),
            author=_optional_string(entry.get("author")),
            hash=_optional_string(entry.get("hash")),
            state=int(entry.get("state") or 0),
            description=_optional_string(entry.get("desc")),
        )
        for entry in event["widgets"]
        if isinstance(entry, dict)
    )
    frame = event.get("frame")
    widget_count = event.get("widgetCount")
    return WidgetReport(
        player_id=player_id,
        frame=frame if isinstance(frame, int) else None,
        widget_count=widget_count if isinstance(widget_count, int) else len(widgets),
        truncated=bool(event.get("truncated")),
        widgets=widgets,
    )


def read_widget_reports(data: bytes) -> list[WidgetReport]:
    """The widget reports of an uncompressed demo, in order, spectators' included."""
    reports = []
    for _, packet in iter_packets(data):
        if packet[0] != PACKET_LUAMSG or len(packet) < LUAMSG_HEADER.size:
            continue
        _, _, player_id, _, _ = LUAMSG_HEADER.unpack_from(packet)
        message = bytes(packet[LUAMSG_HEADER.size :])
        event = decode_match_event(message)
        report = widget_report(player_id, event) if event else None
        if report is not None:
            reports.append(report)
    return reports


_SECTION = re.compile(r"^\s*\[(player|team)(\d+)\]\s*\{(.*?)^\s*\}", re.I | re.M | re.S)


def script_teams(script: str) -> dict[int, int]:
    """Player id -> team id of the players in a start script, spectators left out."""
    teams = {}
    for match in _SECTION.finditer(script):
        if match.group(1).lower() != "player":
            continue
        body = match.group(3)
        team = script_value(body, "team")
        if script_value(body, "spectator") == "1" or not team.isdigit():
            continue
        teams[int(match.group(2))] = int(team)
    return teams


REPLAY_SCHEMA = {
    "replay_file_name": pl.String,
    "allowuserwidgets": pl.String,
    "allowunitcontrolwidgets": pl.String,
    "teamcolors_anonymous_mode": pl.String,
    "reports": pl.Int32,
    "error": pl.String,
}
WIDGET_STRUCT = pl.Struct(
    {
        "name": pl.String,
        "author": pl.String,
        "hash": pl.String,
        "state": pl.Int8,
        "description": pl.String,
    }
)
REPORT_SCHEMA = {
    "replay_file_name": pl.String,
    "player_id": pl.Int32,
    "team_id": pl.Int32,
    "frame": pl.Int32,
    "widget_count": pl.Int32,
    "truncated": pl.Boolean,
    "widgets": pl.List(WIDGET_STRUCT),
}


def read_replay(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The replay row and the report rows of one replay file (players only)."""
    name = Path(path).name
    replay: dict[str, Any] = {"replay_file_name": name, "reports": 0}
    try:
        with gzip.open(path, "rb") as file:
            data = file.read()
        header = parse_header(data)
        reports = read_widget_reports(data)
    except (OSError, EOFError, DemoError, struct.error) as error:
        replay["error"] = f"{type(error).__name__}: {error}"
        return replay, []
    for option in WIDGET_OPTIONS:
        replay[option] = script_value(header.script, option) or None
    teams = script_teams(header.script)
    rows = []
    for report in reports:
        team_id = teams.get(report.player_id)
        if team_id is None:
            continue
        rows.append(
            {
                "replay_file_name": name,
                "player_id": report.player_id,
                "team_id": team_id,
                "frame": report.frame,
                "widget_count": report.widget_count,
                "truncated": report.truncated,
                "widgets": [vars(widget) for widget in report.widgets],
            }
        )
    replay["reports"] = len(rows)
    return replay, rows


def player_widgets(reports: pl.DataFrame) -> pl.DataFrame:
    """Per replay and team: the enabled user widgets and those that automate build orders.

    A player can send more than one report; a widget counts when any of them has it enabled.
    """
    if reports.is_empty():
        return pl.DataFrame(
            schema={
                "replay_file_name": pl.String,
                "team_id": pl.Int32,
                "widgets": pl.List(pl.String),
                "automation_widgets": pl.List(pl.String),
            }
        )
    return (
        reports.select("replay_file_name", "team_id", "widgets")
        .explode("widgets")
        .unnest("widgets")
        .group_by("replay_file_name", "team_id")
        .agg(pl.col("name").filter(pl.col("state") == ENABLED).unique().sort().alias("widgets"))
        .with_columns(
            pl.col("widgets")
            .list.eval(pl.element().filter(pl.element().is_in(list(AUTOMATION_WIDGETS))))
            .alias("automation_widgets")
        )
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "inputs", nargs="*", type=Path, help=f"files or dirs (default {data_dir() / 'replays'})"
    )
    parser.add_argument("--out", type=Path, default=data_dir() / "widgets")
    parser.add_argument("--jobs", type=int, default=default_jobs(), help="parallel readers")
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="read only the partitions of directories from this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        help="read only the partitions of directories before this date (YYYY-MM-DD)",
    )


def run(args: argparse.Namespace) -> int:
    replays: list[Path] = []
    for input_path in args.inputs or [data_dir() / "replays"]:
        if input_path.is_dir():
            replays += find_files(input_path, "*.sdfz", since=args.since, until=args.until)
        elif input_path.suffix == ".sdfz":
            replays.append(input_path)
    print(f"{len(replays)} replays", file=sys.stderr)
    replay_rows: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for count, (replay, rows) in enumerate(
            pool.map(read_replay, replays, chunksize=16), start=1
        ):
            replay_rows.append(replay)
            report_rows += rows
            if count % 1000 == 0:
                print(f"{count} of {len(replays)} replays read", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    replay_frame = pl.from_dicts(replay_rows, schema=REPLAY_SCHEMA).sort("replay_file_name")
    report_frame = pl.from_dicts(report_rows, schema=REPORT_SCHEMA).sort(
        "replay_file_name", "player_id", "frame"
    )
    replay_frame.write_parquet(args.out / REPLAYS_FILE)
    report_frame.write_parquet(args.out / REPORTS_FILE)
    failed = replay_frame["error"].is_not_null().sum()
    with_reports = (replay_frame["reports"] > 0).sum()
    print(
        f"{replay_frame.height} replays ({failed} unreadable), {with_reports} with reports, "
        f"{report_frame.height} reports of players, in {args.out}",
        file=sys.stderr,
    )
    return 0
