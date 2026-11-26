"""The parsed replays, as Parquet tables: the one copy of everything the parser keeps.

`reason8 parse` (`reason8.replays.parse`) turns each replay into rows of these tables and
writes them, a file per table and day, into the ``tables`` area of the data directory:
``tables/date=YYYY-MM-DD/YYYY-MM-DD.<table>.parquet``. The tables, their rows and how they join
are described in docs/reference/replay-format.md#tables; the decision to keep only them is
ADR 0005. Player and spectator names are left out; nothing else the parser keeps is.

`replay_tables` turns one parsed document (`reason8.replays.replay.Replay`) into its rows, and
refuses a document with a field it has no column for, so that nothing is dropped unnoticed.
`replay_documents` gives the documents back from the rows (without the names), and
`replay_headers` the part of them that the games and players tables hold, for the passes that
read a game's setup through `Replay`.

A pass reads the tables of some days with `open_source` (or one table with `scan`). Every
file holds the layout `VERSION` in its metadata; a day whose files hold another one is not
read, and is rebuilt when its replays are parsed again.

Writing: the rows of each replay are staged in ``tables/_staging/<day>/`` until the day's
replays are done (`update_days`); then every table of the day is streamed into a temporary
file and renamed into place, ``games`` last, from the staged rows and the rows already there.
A run that stops halfway leaves the day as it was, or with some tables ahead of ``games``,
which lists what the day holds.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from reason8.paths import PARTITION_PREFIX, data_dir, partition, partition_in_range
from reason8.replays.codes import OPTION_BITS, command_record
from reason8.replays.replay import (
    CTRL_MULTIPLIER,
    FORMAT,
    SHIFT_MULTIPLIER,
    BuildOrder,
    Replay,
    Team,
)

#: The area of the data directory the tables are kept in.
AREA = "tables"
#: Written into every file; a day written with another layout is not read, and rebuilt.
VERSION = "reason8.tables/2"
VERSION_KEY = "reason8"
SUFFIX = ".parquet"
#: Rows of single replays wait here (``<area>/_staging/<day>/``) until their day is written.
STAGING = "_staging"
#: Row groups of about two minutes of an 8v8 game, so a scan of the opening skips the rest.
ROW_GROUP_SIZE = 16_384
ZSTD_LEVEL = 9
#: The bookkeeping file of `reason8 parse`: one line per replay it tried, failures included.
INDEX_NAME = "_index.jsonl"

GAMES = "games"
PLAYERS = "players"
COMMANDS = "commands"
SELECTIONS = "selections"
EVENTS = "events"
CHAT = "chat"
DRAWINGS = "drawings"
START_PICKS = "start_picks"
SHARES = "shares"
TEAM_STATISTICS = "team_statistics"
PLAYER_STATISTICS = "player_statistics"
#: Written in this order: `GAMES` records what a day holds, so it goes last.
TABLES = (
    COMMANDS,
    SELECTIONS,
    EVENTS,
    CHAT,
    DRAWINGS,
    START_PICKS,
    SHARES,
    TEAM_STATISTICS,
    PLAYER_STATISTICS,
    PLAYERS,
    GAMES,
)
#: The tables with a row per event of the replay's stream, ordered by ``seq``.
EVENT_TABLES = (COMMANDS, SELECTIONS, EVENTS, CHAT, DRAWINGS, START_PICKS, SHARES)

VIA = pl.Enum(["COMMAND", "AICOMMAND", "AICOMMANDS"])
ROLES = ("player", "ai", "spectator")
#: The event types of `EVENTS`; the other types have a table of their own.
EVENT_TYPES = ("start", "gameover", "team", "playerleft", "pause", "quit")
SHARE_TYPES = ("share", "setshare", "aishare")
#: The table of each event type.
EVENT_TABLE = {
    "cmd": COMMANDS,
    "select": SELECTIONS,
    "chat": CHAT,
    "mapdraw": DRAWINGS,
    "startpos": START_PICKS,
    **dict.fromkeys(EVENT_TYPES, EVENTS),
    **dict.fromkeys(SHARE_TYPES, SHARES),
}
OPTION = {name: bit for bit, name in OPTION_BITS}
SHIFT, CTRL, RIGHT, INTERNAL = OPTION["shift"], OPTION["ctrl"], OPTION["right"], OPTION["internal"]
NAMED_VALUE = pl.Struct({"name": pl.String, "value": pl.String})

#: ``teamStats`` fields of the parsed document -> columns of `TEAM_STATISTICS`.
TEAM_STATISTICS_FIELDS = {
    "frame": "frame",
    "metalUsed": "metal_used",
    "energyUsed": "energy_used",
    "metalProduced": "metal_produced",
    "energyProduced": "energy_produced",
    "metalExcess": "metal_excess",
    "energyExcess": "energy_excess",
    "metalReceived": "metal_received",
    "energyReceived": "energy_received",
    "metalSent": "metal_sent",
    "energySent": "energy_sent",
    "damageDealt": "damage_dealt",
    "damageReceived": "damage_received",
    "unitsProduced": "units_produced",
    "unitsDied": "units_died",
    "unitsReceived": "units_received",
    "unitsSent": "units_sent",
    "unitsCaptured": "units_captured",
    "unitsOutCaptured": "units_out_captured",
    "unitsKilled": "units_killed",
}
#: The columns of `TEAM_STATISTICS` that hold whole numbers.
TEAM_STATISTICS_COUNTS = frozenset(
    column
    for column in TEAM_STATISTICS_FIELDS.values()
    if column == "frame" or column.startswith("units")
)
#: ``playerStats`` fields of the parsed document -> columns of `PLAYER_STATISTICS`.
PLAYER_STATISTICS_FIELDS = {
    "playerId": "player_id",
    "numCommands": "num_commands",
    "unitCommands": "unit_commands",
    "mousePixels": "mouse_pixels",
    "mouseClicks": "mouse_clicks",
    "keyPresses": "key_presses",
}
#: ``meta`` fields of the parsed document -> columns of `GAMES`.
META_FIELDS = {
    "gameId": "game_id",
    "engine": "engine",
    "game": "game",
    "map": "map",
    "startTime": "start_time",
    "durationMs": "duration_ms",
    "fullDurationMs": "full_duration_ms",
    "winningAllyTeamIds": "winning_ally_teams",
    "startPosType": "start_pos_type",
    "demoVersion": "demo_version",
    "gameTime": "game_time",
    "wallclockTime": "wallclock_time",
    "startFrame": "start_frame",
    "endFrame": "end_frame",
    "serverMatchId": "match_id",
}
START_BOX = ("left", "top", "right", "bottom")

SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    GAMES: {
        "replay": pl.String(),  # the replay's file name without .sdfz: the key of every table
        "sdfz_bytes": pl.Int64(),  # size of the replay file the rows come from
        "parser": pl.String(),
        "match_id": pl.Int64(),  # meta.serverMatchId
        "game_id": pl.String(),
        "engine": pl.String(),
        "game": pl.String(),  # the BAR version
        "map": pl.String(),
        "start_time": pl.String(),
        "duration_ms": pl.Int64(),
        "full_duration_ms": pl.Int64(),
        "winning_ally_teams": pl.List(pl.Int16()),
        "start_pos_type": pl.Int8(),
        "demo_version": pl.Int16(),
        "game_time": pl.Int32(),
        "wallclock_time": pl.Int32(),
        "start_frame": pl.Int32(),
        "end_frame": pl.Int32(),
        "ally_teams": pl.List(
            pl.Struct(
                {
                    "ally_team_id": pl.Int16(),
                    "player_count": pl.Int16(),
                    **{side: pl.Float64() for side in START_BOX},  # the start box
                }
            )
        ),
        "modoptions": pl.List(NAMED_VALUE),
        "mapoptions": pl.List(NAMED_VALUE),
        "restrictions": pl.List(NAMED_VALUE),
        "unitdefs": pl.List(pl.String()),  # unit names by the index BUILD commands use
        # the end-of-game statistics: the teams they list (null: the replay has none) and
        # the winners they name; their rows are in TEAM_STATISTICS and PLAYER_STATISTICS
        "statistics_teams": pl.List(pl.Int16()),
        "statistics_winning_ally_teams": pl.List(pl.Int16()),
    },
    PLAYERS: {
        "replay": pl.String(),
        "slot": pl.Int16(),  # order in the replay: players, then AIs, then spectators
        "role": pl.Enum(list(ROLES)),
        "player_id": pl.Int16(),  # null for an AI; what the events' `player` refers to
        "ai_id": pl.Int16(),  # null but for an AI
        "team_id": pl.Int16(),  # null for a spectator
        "ally_team_id": pl.Int16(),  # null for a spectator
        "user_id": pl.Int64(),  # for the join with the match dumps; names are not kept
        "faction": pl.String(),
        "rank": pl.Int8(),
        "skill": pl.String(),  # as the replay writes it, e.g. "[45.67]"
        "skill_uncertainty": pl.Float64(),
        "start_x": pl.Float64(),  # where the team started
        "start_y": pl.Float64(),
        "start_z": pl.Float64(),
        "ai_name": pl.String(),  # an AI's name in the lobby, e.g. "BARb(1)"
        "ai_short_name": pl.String(),
        "ai_version": pl.String(),
    },
    COMMANDS: {
        "replay": pl.String(),
        "seq": pl.Int32(),  # position in the replay's event stream, shared by EVENT_TABLES
        "frame": pl.Int32(),  # game frame (30 a second) from the start; null before it
        "player": pl.Int16(),  # the player who sent the packet
        "team": pl.Int16(),
        "via": VIA,
        "ai": pl.Int16(),  # 255: a LuaUI widget of the player
        "units": pl.List(pl.Int32()),  # null for COMMAND: the player's current selection
        "command": pl.String(),  # for an INSERT, the inserted command
        "command_id": pl.Int32(),
        "unit": pl.String(),  # BUILD: the unit ordered
        "options": pl.UInt8(),  # bits of OPTION_BITS
        "params": pl.List(pl.Float32()),
        "x": pl.Float32(),  # BUILD of a structure: params[0], params[2] and params[3]
        "z": pl.Float32(),
        "facing": pl.Int8(),
        "inserted": pl.Boolean(),  # from an INSERT: the columns above describe what it inserts
        "insert_options": pl.UInt8(),  # the INSERT's own options
        "insert_position": pl.Float64(),  # queue index with alt, otherwise a command tag
    },
    SELECTIONS: {
        "replay": pl.String(),
        "seq": pl.Int32(),
        "frame": pl.Int32(),
        "player": pl.Int16(),
        "units": pl.List(pl.Int32()),  # the player's new selection
    },
    EVENTS: {
        "replay": pl.String(),
        "seq": pl.Int32(),
        "frame": pl.Int32(),
        "type": pl.Enum(list(EVENT_TYPES)),
        "player": pl.Int16(),  # null for start and quit
        "action": pl.String(),  # team: giveaway, resign, join_team, team_died, ...
        "param": pl.Int32(),  # team: the action's parameter, e.g. the team that died
        "reason": pl.Int16(),  # playerleft: 0 lost connection, 1 left, 2 kicked
        "paused": pl.Boolean(),  # pause
        "winners": pl.List(pl.Int16()),  # gameover: the winning ally teams
    },
    CHAT: {
        "replay": pl.String(),
        "seq": pl.Int32(),
        "frame": pl.Int32(),
        "player": pl.Int16(),
        "to": pl.Int16(),  # a player id, or 252 allies, 253 spectators, 254 everyone
        "message": pl.String(),
    },
    DRAWINGS: {
        "replay": pl.String(),
        "seq": pl.Int32(),
        "frame": pl.Int32(),
        "player": pl.Int16(),
        "action": pl.String(),  # point, erase or line
        "x": pl.Int32(),
        "z": pl.Int32(),
        "x2": pl.Int32(),  # line: the other end
        "z2": pl.Int32(),
        "label": pl.String(),  # point: its text
        "from_lua": pl.Boolean(),  # drawn by a widget
    },
    START_PICKS: {
        "replay": pl.String(),
        "seq": pl.Int32(),
        "frame": pl.Int32(),  # null: before the game started
        "player": pl.Int16(),
        "team": pl.Int16(),
        "ready": pl.Int8(),
        "x": pl.Float64(),
        "z": pl.Float64(),
    },
    SHARES: {
        "replay": pl.String(),
        "seq": pl.Int32(),
        "frame": pl.Int32(),
        "type": pl.Enum(list(SHARE_TYPES)),
        "player": pl.Int16(),
        "ai": pl.Int16(),  # aishare: the AI giving
        "team": pl.Int16(),  # setshare: the team whose share levels are set
        "from_team": pl.Int16(),  # aishare
        "to_team": pl.Int16(),  # share, aishare
        "selected_units": pl.Boolean(),  # share: the player's selected units go too
        "units": pl.List(pl.Int32()),  # aishare: the units given
        "metal": pl.Float64(),  # share, aishare: the amount given; setshare: the share level
        "energy": pl.Float64(),
    },
    TEAM_STATISTICS: {
        "replay": pl.String(),
        "team_id": pl.Int16(),
        **{
            column: pl.Int32() if column in TEAM_STATISTICS_COUNTS else pl.Float64()
            for column in TEAM_STATISTICS_FIELDS.values()
        },
    },
    PLAYER_STATISTICS: {
        "replay": pl.String(),
        **{
            column: pl.Int16() if column == "player_id" else pl.Int64()
            for column in PLAYER_STATISTICS_FIELDS.values()
        },
    },
}

#: The fields each part of the parsed document may have, all of which the tables hold but
#: the names of players and spectators.
FIELDS: dict[str, frozenset[str]] = {
    "document": frozenset(
        {
            "format",
            "source",
            "meta",
            "allyTeams",
            "players",
            "ais",
            "spectators",
            "modoptions",
            "mapoptions",
            "restrictions",
            "unitdefs",
            "statistics",
            "events",
        }
    ),
    # trimmed: a note of the test fixture (`reason8 make-fixture`) only, not kept
    "source": frozenset({"file", "bytes", "parser", "trimmed"}),
    "meta": frozenset(META_FIELDS),
    "allyTeams": frozenset({"allyTeamId", "playerCount", "startBox"}),
    "startBox": frozenset(START_BOX),
    "players": frozenset(
        {
            "playerId",
            "teamId",
            "allyTeamId",
            "name",
            "userId",
            "faction",
            "rank",
            "skill",
            "skillUncertainty",
            "startPos",
        }
    ),
    "ais": frozenset(
        {"aiId", "teamId", "allyTeamId", "name", "shortName", "version", "faction", "startPos"}
    ),
    "spectators": frozenset({"playerId", "name", "userId"}),
    "startPos": frozenset({"x", "y", "z"}),
    "statistics": frozenset({"winningAllyTeamIds", "playerStats", "teamStats"}),
    "teamStats": frozenset(TEAM_STATISTICS_FIELDS),
    "playerStats": frozenset(PLAYER_STATISTICS_FIELDS),
    "cmd": frozenset(
        {"frame", "type", "player", "via", "ai", "team", "units"}
        | {"cmd", "cmd_id", "unit", "opts", "params", "pos", "inner"}
    ),
    "command": frozenset({"cmd", "cmd_id", "unit", "opts", "params", "pos", "inner"}),
    "select": frozenset({"frame", "type", "player", "units"}),
    "start": frozenset({"frame", "type"}),
    "quit": frozenset({"frame", "type"}),
    "gameover": frozenset({"frame", "type", "player", "winners"}),
    "playerleft": frozenset({"frame", "type", "player", "reason"}),
    "team": frozenset({"frame", "type", "player", "action", "param"}),
    "pause": frozenset({"frame", "type", "player", "paused"}),
    "chat": frozenset({"frame", "type", "player", "to", "message"}),
    "mapdraw": frozenset(
        {"frame", "type", "player", "action", "x", "z", "x2", "z2", "label", "from_lua"}
    ),
    "startpos": frozenset({"frame", "type", "player", "team", "ready", "x", "z"}),
    "share": frozenset({"frame", "type", "player", "to_team", "units", "metal", "energy"}),
    "setshare": frozenset({"frame", "type", "player", "team", "metal", "energy"}),
    "aishare": frozenset(
        {"frame", "type", "player", "ai", "from_team", "to_team", "metal", "energy", "units"}
    ),
}


class UnknownField(ValueError):
    """The parsed document has a field the tables have no column for."""


def _check(part: str, record: Mapping[str, Any] | None) -> None:
    if record and not record.keys() <= FIELDS[part]:
        unknown = sorted(set(record) - FIELDS[part])
        raise UnknownField(f"{part} has fields the tables do not hold: {unknown}")


# --- from a parsed replay to rows


def option_bits(labels: Iterable[str] | None) -> int:
    if not labels:
        return 0
    return sum(OPTION[label] for label in labels)


def option_labels(bits: int | None) -> tuple[str, ...]:
    """The option names of `bits`, in the order the parsed JSON lists them."""
    return tuple(name for bit, name in OPTION_BITS if (bits or 0) & bit)


def raw_params(command: Mapping[str, Any]) -> list[Any]:
    """The parameters of a command (None for NaN); for an INSERT, as the replay holds them."""
    if "inner" in command:
        inner = command["inner"]
        _check("command", inner)
        return [
            command.get("pos"),
            inner.get("cmd_id"),
            option_bits(inner.get("opts")),
            *raw_params(inner),
        ]
    return command.get("params") or []


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _string(value: Any) -> str | None:
    return None if value is None else str(value)


def _named_values(values: Mapping[str, Any] | None) -> list[dict[str, str | None]]:
    return [{"name": str(name), "value": _string(value)} for name, value in (values or {}).items()]


def _event_row(kind: str, event: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The table of an event other than a command, and its columns but ``replay`` and ``seq``."""
    if kind not in EVENT_TABLE:
        raise UnknownField(f"events of type {kind!r} have no table")
    _check(kind, event)
    table = EVENT_TABLE[kind]
    row: dict[str, Any] = {"frame": event.get("frame")}
    if table == SELECTIONS:
        return table, row | {"player": event.get("player"), "units": event.get("units")}
    if table == EVENTS:
        action = event.get("action")
        return table, row | {
            "type": kind,
            "player": event.get("player"),
            "action": _string(action),
            "param": event.get("param"),
            "reason": event.get("reason"),
            "paused": event.get("paused"),
            "winners": event.get("winners"),
        }
    if table == CHAT:
        return table, row | {key: event.get(key) for key in ("player", "to", "message")}
    if table == DRAWINGS:
        return table, row | {
            "player": event.get("player"),
            "action": _string(event.get("action")),
            **{key: event.get(key) for key in ("x", "z", "x2", "z2", "label")},
            "from_lua": bool(event.get("from_lua")),
        }
    if table == START_PICKS:
        return table, row | {
            "player": event.get("player"),
            "team": event.get("team"),
            "ready": event.get("ready"),
            "x": _float(event.get("x")),
            "z": _float(event.get("z")),
        }
    return table, row | {  # SHARES
        "type": kind,
        **{key: event.get(key) for key in ("player", "ai", "team", "from_team", "to_team")},
        "selected_units": event.get("units") if kind == "share" else None,
        "units": event.get("units") if kind == "aishare" else None,
        "metal": _float(event.get("metal")),
        "energy": _float(event.get("energy")),
    }


def _command_row(seq: int, event: Mapping[str, Any]) -> tuple[Any, ...]:
    """The columns of `COMMANDS` but ``replay`` for a command event."""
    if not event.keys() <= FIELDS["cmd"]:
        _check("cmd", event)
    command = event
    inserted = event.get("cmd") == "INSERT" and "inner" in event
    if inserted:
        command = event["inner"]
        _check("command", command)
    params = raw_params(command)
    build = command.get("cmd") == "BUILD" and len(params) >= 3
    return (
        seq,
        event.get("frame"),
        event.get("player"),
        event.get("team"),
        event.get("via"),
        event.get("ai"),
        event.get("units"),
        command.get("cmd"),
        command.get("cmd_id"),
        command.get("unit"),
        option_bits(command.get("opts")),
        params,
        _number(params[0]) if build else None,
        _number(params[2]) if build else None,
        int(params[3]) if build and len(params) > 3 else None,
        inserted,
        option_bits(event.get("opts")) if inserted else None,
        _number(event.get("pos")) if inserted else None,
    )


def _person_row(role: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """The columns of `PLAYERS` but ``replay`` and ``slot`` for a player, AI or spectator."""
    _check({"player": "players", "ai": "ais", "spectator": "spectators"}[role], record)
    start = record.get("startPos")
    _check("startPos", start)
    is_ai = role == "ai"
    return {
        "role": role,
        "player_id": None if is_ai else record.get("playerId"),
        "ai_id": record.get("aiId") if is_ai else None,
        "team_id": record.get("teamId"),
        "ally_team_id": record.get("allyTeamId"),
        "user_id": _integer(record.get("userId")),
        "faction": record.get("faction"),
        "rank": record.get("rank"),
        "skill": _string(record.get("skill")),
        "skill_uncertainty": _float(record.get("skillUncertainty")),
        **{f"start_{key}": _float(start.get(key)) if start else None for key in ("x", "y", "z")},
        "ai_name": record.get("name") if is_ai else None,
        "ai_short_name": record.get("shortName") if is_ai else None,
        "ai_version": record.get("version") if is_ai else None,
    }


def _game_row(document: Mapping[str, Any]) -> dict[str, Any]:
    """The columns of `GAMES` but ``replay``."""
    meta = document.get("meta") or {}
    _check("meta", meta)
    source = document.get("source") or {}
    _check("source", source)
    ally_teams = []
    for ally_team in document.get("allyTeams") or ():
        _check("allyTeams", ally_team)
        box = ally_team.get("startBox")
        _check("startBox", box)
        ally_teams.append(
            {
                "ally_team_id": ally_team.get("allyTeamId"),
                "player_count": ally_team.get("playerCount"),
                **{side: _float((box or {}).get(side)) for side in START_BOX},
            }
        )
    statistics = document.get("statistics")
    _check("statistics", statistics)
    return (
        {"sdfz_bytes": source.get("bytes"), "parser": source.get("parser")}
        | {column: meta.get(key) for key, column in META_FIELDS.items()}
        | {
            "match_id": _integer(meta.get("serverMatchId")),
            "ally_teams": ally_teams,
            "modoptions": _named_values(document.get("modoptions")),
            "mapoptions": _named_values(document.get("mapoptions")),
            "restrictions": _named_values(document.get("restrictions")),
            "unitdefs": document.get("unitdefs"),
            "statistics_teams": None
            if statistics is None
            else [int(team) for team in statistics.get("teamStats") or {}],
            "statistics_winning_ally_teams": (statistics or {}).get("winningAllyTeamIds"),
        }
    )


def replay_tables(replay: Replay | Mapping[str, Any], name: str) -> dict[str, pl.DataFrame]:
    """The rows of one parsed replay in every table, ``name`` being its key (``replay``).

    Raises `UnknownField` for a field of the document that no column holds (names aside),
    and a `TypeError` for a value its column cannot hold exactly.
    """
    document = replay.doc if isinstance(replay, Replay) else replay
    _check("document", document)
    columns: dict[str, dict[str, list[Any]]] = {
        table: {column: [] for column in schema} for table, schema in SCHEMAS.items()
    }

    def add(table: str, values: Mapping[str, Any]) -> None:
        table_columns = columns[table]
        table_columns["replay"].append(name)
        for column, value in values.items():
            table_columns[column].append(value)

    command_rows: list[tuple[Any, ...]] = []
    for seq, event in enumerate(document.get("events") or ()):
        kind = event["type"]
        if kind == "cmd":
            command_rows.append(_command_row(seq, event))
        else:
            table, row = _event_row(kind, event)
            add(table, {"seq": seq} | row)
    command_columns = list(SCHEMAS[COMMANDS])[1:]
    transposed = zip(*command_rows, strict=True) if command_rows else [()] * len(command_columns)
    columns[COMMANDS] = {"replay": [name] * len(command_rows)} | {
        column: list(values) for column, values in zip(command_columns, transposed, strict=True)
    }

    people = (
        [("player", record) for record in document.get("players") or ()]
        + [("ai", record) for record in document.get("ais") or ()]
        + [("spectator", record) for record in document.get("spectators") or ()]
    )
    for slot, (role, record) in enumerate(people):
        add(PLAYERS, {"slot": slot} | _person_row(role, record))

    statistics = document.get("statistics") or {}
    for team_id, samples in (statistics.get("teamStats") or {}).items():
        for sample in samples:
            _check("teamStats", sample)
            add(
                TEAM_STATISTICS,
                {"team_id": int(team_id)}
                | {
                    column: sample.get(key)
                    if column in TEAM_STATISTICS_COUNTS
                    else _float(sample.get(key))
                    for key, column in TEAM_STATISTICS_FIELDS.items()
                },
            )
    for sample in statistics.get("playerStats") or ():
        _check("playerStats", sample)
        add(
            PLAYER_STATISTICS,
            {column: sample.get(key) for key, column in PLAYER_STATISTICS_FIELDS.items()},
        )
    add(GAMES, _game_row(document))
    return {
        table: pl.DataFrame(
            [
                _series(column, values, SCHEMAS[table][column])
                for column, values in table_columns.items()
            ]
        )
        for table, table_columns in columns.items()
    }


def _series(name: str, values: list[Any], dtype: pl.DataType) -> pl.Series:
    """A column from Python values; lists of numbers are built in bulk, which is much faster.

    A value the column cannot hold exactly raises a `TypeError` instead of becoming null.
    """
    if not (isinstance(dtype, pl.List) and dtype.inner.is_numeric()) or len(values) < 2:
        return pl.Series(name, values, dtype=dtype, strict=True)
    rows: list[int] = []
    flat: list[Any] = []
    for row, value in enumerate(values):
        if value:
            rows.extend([row] * len(value))
            flat.extend(value)
    lists = (
        pl.DataFrame(
            {
                "row": pl.Series(rows, dtype=pl.UInt32),
                "value": pl.Series(flat, dtype=dtype.inner, strict=True),
            }
        )
        .group_by("row", maintain_order=True)
        .agg("value")
    )
    missing = pl.Series([value is None for value in values])
    return (
        pl.DataFrame({"row": pl.arange(0, len(values), eager=True, dtype=pl.UInt32)})
        .join(lists, on="row", how="left", maintain_order="left")
        .select(
            pl.when(missing)
            .then(None)
            .otherwise(pl.col("value").fill_null(pl.lit([], dtype=dtype)))
            .cast(dtype)
            .alias(name)
        )
        .to_series()
    )


# --- from rows back to the parsed documents


def _json_number(value: float | None) -> int | float | None:
    """A number as the parsed document writes it: whole numbers as integers."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _round(value: float | None) -> float | None:
    """A float32 parameter back to the value the JSON keeps (2 decimals)."""
    return None if value is None else round(value, 2)


def _action(value: str | None) -> str | int | None:
    """An action as the document has it: its name, or the number of one without a name."""
    if value is not None and value.lstrip("-").isdigit():
        return int(value)
    return value


def options_dict(options: Iterable[Mapping[str, str | None]] | None) -> dict[str, str | None]:
    """A ``modoptions``/``mapoptions`` column value as the dict the JSON has."""
    return {option["name"]: option["value"] for option in options or ()}


def _start_pos(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row["start_x"] is None:
        return None
    return {key: _json_number(row[f"start_{key}"]) for key in ("x", "y", "z")}


def _without_nulls(record: dict[str, Any], *keys: str) -> dict[str, Any]:
    """The record without those of ``keys`` that are null: the parser leaves them out."""
    return {key: value for key, value in record.items() if key not in keys or value is not None}


def _person(row: Mapping[str, Any]) -> dict[str, Any]:
    """A record of ``players``, ``ais`` or ``spectators`` from its row, without the name."""
    if row["role"] == "spectator":
        return _without_nulls({"playerId": row["player_id"], "userId": row["user_id"]}, "userId")
    if row["role"] == "ai":
        return _without_nulls(
            {
                "aiId": row["ai_id"],
                "teamId": row["team_id"],
                "allyTeamId": row["ally_team_id"],
                "name": row["ai_name"],
                "shortName": row["ai_short_name"],
                "version": row["ai_version"],
                "faction": row["faction"],
                "startPos": _start_pos(row),
            },
            "startPos",
        )
    return _without_nulls(
        {
            "playerId": row["player_id"],
            "teamId": row["team_id"],
            "allyTeamId": row["ally_team_id"],
            "userId": row["user_id"],
            "faction": row["faction"],
            "rank": row["rank"],
            "skill": row["skill"],
            "skillUncertainty": _json_number(row["skill_uncertainty"]),
            "startPos": _start_pos(row),
        },
        "startPos",
    )


def _command(row: Mapping[str, Any], unitdefs: Sequence[str]) -> dict[str, Any]:
    event: dict[str, Any] = {"frame": row["frame"], "type": "cmd", "player": row["player"]}
    event["via"] = row["via"]
    if row["ai"] is not None:
        event["ai"] = row["ai"]
    event["team"] = row["team"]
    if row["units"] is not None:
        event["units"] = list(row["units"])
    params = list(row["params"] or ())
    if row["inserted"]:
        insert = [row["insert_position"], row["command_id"], row["options"], *params]
        record = command_record(1, row["insert_options"] or 0, insert, unitdefs)
        command = record["inner"]
    else:
        record = command = command_record(row["command_id"], row["options"], params, unitdefs)
    if "unit" in command:  # a BUILD: the unit as the parser named it
        command["unit"] = row["unit"]
    return event | record


def _event(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """The event of the parsed document that a row of an event table (not commands) holds."""
    event: dict[str, Any] = {"frame": row["frame"]}
    if table == SELECTIONS:
        return event | {"type": "select", "player": row["player"], "units": row["units"]}
    if table == CHAT:
        return event | {"type": "chat"} | {key: row[key] for key in ("player", "to", "message")}
    if table == START_PICKS:
        return event | {
            "type": "startpos",
            **{key: row[key] for key in ("player", "team", "ready")},
            "x": _json_number(row["x"]),
            "z": _json_number(row["z"]),
        }
    if table == DRAWINGS:
        event |= {"type": "mapdraw", "player": row["player"], "action": _action(row["action"])}
        event |= {"x": row["x"], "z": row["z"]}
        event |= {key: row[key] for key in ("x2", "z2", "label") if row[key] is not None}
        return event | ({"from_lua": True} if row["from_lua"] else {})
    kind = row["type"]
    event["type"] = kind
    if table == SHARES:
        event["player"] = row["player"]
        amounts = {"metal": _json_number(row["metal"]), "energy": _json_number(row["energy"])}
        if kind == "share":
            return event | {"to_team": row["to_team"], "units": row["selected_units"]} | amounts
        if kind == "setshare":
            return event | {"team": row["team"]} | amounts
        event |= {key: row[key] for key in ("ai", "from_team", "to_team")}
        return event | amounts | {"units": row["units"]}
    if kind in ("start", "quit"):
        return event
    event["player"] = row["player"]
    if kind == "gameover":
        return event | {"winners": row["winners"]}
    if kind == "playerleft":
        return event | {"reason": row["reason"]}
    if kind == "pause":
        return event | {"paused": row["paused"]}
    return event | {"action": _action(row["action"]), "param": row["param"]}


def _by_replay(frame: pl.DataFrame | None) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in frame.iter_rows(named=True) if frame is not None else ():
        rows[row["replay"]].append(row)
    return rows


def _statistics(
    game: Mapping[str, Any],
    team_rows: Iterable[Mapping[str, Any]],
    player_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if game["statistics_teams"] is None:
        return None
    samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in team_rows:
        samples[row["team_id"]].append(
            {key: _json_number(row[column]) for key, column in TEAM_STATISTICS_FIELDS.items()}
        )
    return {
        "winningAllyTeamIds": game["statistics_winning_ally_teams"],
        "playerStats": [
            {key: row[column] for key, column in PLAYER_STATISTICS_FIELDS.items()}
            for row in player_rows
        ],
        "teamStats": {str(team): samples.get(team, []) for team in game["statistics_teams"]},
    }


def replay_documents(frames: Mapping[str, pl.DataFrame]) -> dict[str, dict[str, Any]]:
    """Replay -> its parsed document, from the rows of some tables of its replays.

    The document of every replay in the rows of `GAMES`, with what the other tables given
    hold: `PLAYERS` gives ``players``, ``ais`` and ``spectators``; `TEAM_STATISTICS` with
    `PLAYER_STATISTICS` give ``statistics``; the event tables give ``events``, in stream
    order. Names are not in the tables, so the documents have none. Numbers come back as the
    document writes them; command parameters went through float32, as in the replay. A start
    box, a start position or a spectator's user id that is null is left out, as the parser
    leaves it out.
    """
    players = _by_replay(frames.get(PLAYERS))
    team_statistics = _by_replay(frames.get(TEAM_STATISTICS))
    player_statistics = _by_replay(frames.get(PLAYER_STATISTICS))
    event_rows = {table: _by_replay(frames.get(table)) for table in EVENT_TABLES}
    has_events = any(table in frames for table in EVENT_TABLES)
    documents = {}
    for row in frames[GAMES].iter_rows(named=True):
        name = row["replay"]
        meta = {key: row[column] for key, column in META_FIELDS.items()}
        meta["serverMatchId"] = _string(row["match_id"])
        ally_teams = []
        for ally_team in row["ally_teams"] or ():
            box = {side: _json_number(ally_team[side]) for side in START_BOX}
            ally_teams.append(
                _without_nulls(
                    {
                        "allyTeamId": ally_team["ally_team_id"],
                        "startBox": box if any(side is not None for side in box.values()) else None,
                        "playerCount": ally_team["player_count"],
                    },
                    "startBox",
                )
            )
        document: dict[str, Any] = {
            "format": FORMAT,
            "source": {"file": f"{name}.sdfz", "bytes": row["sdfz_bytes"], "parser": row["parser"]},
            "meta": meta,
            "allyTeams": ally_teams,
        }
        if PLAYERS in frames:
            people = sorted(players.get(name, ()), key=lambda person: person["slot"])
            for role, key in (("player", "players"), ("ai", "ais"), ("spectator", "spectators")):
                document[key] = [_person(person) for person in people if person["role"] == role]
        document |= {
            "modoptions": options_dict(row["modoptions"]),
            "mapoptions": options_dict(row["mapoptions"]),
            "restrictions": options_dict(row["restrictions"]),
            "unitdefs": row["unitdefs"],
        }
        if TEAM_STATISTICS in frames and PLAYER_STATISTICS in frames:
            document["statistics"] = _statistics(
                row, team_statistics.get(name, ()), player_statistics.get(name, ())
            )
        if has_events:
            unitdefs = row["unitdefs"] or []
            events = [
                (event["seq"], table, event)
                for table, rows in event_rows.items()
                for event in rows.get(name, ())
            ]
            events.sort(key=lambda item: item[0])
            document["events"] = [
                _command(event, unitdefs) if table == COMMANDS else _event(table, event)
                for _, table, event in events
            ]
        documents[name] = document
    return documents


def replay_headers(games: pl.DataFrame, players: pl.DataFrame) -> dict[str, Replay]:
    """Replay -> a `Replay` of its setup, from rows of the games and players tables.

    What the parsed document says about the game and its players (`replay_documents` of
    these two tables): ``meta``, ``players``, ``ais``, ``spectators``, ``allyTeams``,
    ``modoptions``, ``mapoptions``, ``restrictions``, ``unitdefs`` and ``source``, so that
    `Replay.teams()`, the positions of `reason8.game.positions` and the like work as on the
    document. ``events`` and ``statistics`` are left out: read them from their tables.
    """
    documents = replay_documents({GAMES: games, PLAYERS: players})
    return {name: Replay(document) for name, document in documents.items()}


# --- reading


def table_name(day: str, table: str) -> str:
    """The file of a table in a partition, e.g. ``2026-11-01.commands.parquet``."""
    return f"{day}.{table}{SUFFIX}"


def tables_dir() -> Path:
    return data_dir() / AREA


def table_files(
    table: str,
    directory: Path | None = None,
    since: date | None = None,
    until: date | None = None,
) -> list[Path]:
    directory = directory or tables_dir()
    if not directory.is_dir():
        return []
    return sorted(
        path
        for partition_directory in directory.glob(PARTITION_PREFIX + "*")
        if partition_directory.is_dir()
        and partition_in_range(partition_directory.name, since, until)
        for path in partition_directory.glob(f"*.{table}{SUFFIX}")
    )


def scan(
    table: str,
    directory: Path | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
) -> pl.LazyFrame:
    """A lazy frame of one table over the days ``since`` (inclusive) .. ``until`` (exclusive).

    The frame has a ``date`` column from the partitions. Filters on ``frame`` skip the row
    groups (about two minutes of a game each) they rule out. Unlike `open_source`, it does
    not check the layout version of the files.
    """
    files = table_files(table, directory, since, until)
    if not files:
        return pl.LazyFrame(schema={**SCHEMAS[table], "date": pl.Date()})
    return pl.scan_parquet(files, hive_partitioning=True, hive_schema={"date": pl.Date()})


def build_order_frame(commands: pl.LazyFrame, until_frame: int | None = None) -> pl.LazyFrame:
    """The BUILD commands of a commands frame with the columns of `BuildOrder`.

    `count`, `queued` and `quota` follow `Replay.build_orders`; ``until_frame`` keeps the
    orders up to that frame (all of them in a game that never started).
    """
    build = commands.filter(pl.col("command") == "BUILD")
    if until_frame is not None:
        build = build.filter(pl.col("frame").is_null() | (pl.col("frame") <= until_frame))
    options = pl.col("options")
    structure = pl.col("params").list.len() >= 3
    count = (
        pl.when(options & SHIFT != 0).then(SHIFT_MULTIPLIER).otherwise(1)
        * pl.when(options & CTRL != 0).then(CTRL_MULTIPLIER).otherwise(1)
        * pl.when(options & RIGHT != 0).then(-1).otherwise(1)
    )
    return build.with_columns(
        kind=pl.when(structure).then(pl.lit("structure")).otherwise(pl.lit("factory")),
        count=pl.when(structure).then(1).otherwise(count).cast(pl.Int32),
        queued=options & SHIFT != 0,
        quota=pl.col("inserted")
        & (options & INTERNAL != 0)
        & (pl.col("insert_options").fill_null(0) & CTRL != 0),
    )


def build_orders_from(frame: pl.DataFrame) -> dict[str, list[BuildOrder]]:
    """`BuildOrder`s per replay from the rows of `build_order_frame`, in stream order."""
    orders: dict[str, list[BuildOrder]] = defaultdict(list)
    for row in frame.sort("replay", maintain_order=True).iter_rows(named=True):
        structure = row["kind"] == "structure"
        orders[row["replay"]].append(
            BuildOrder(
                frame=row["frame"],
                team=row["team"],
                player=row["player"],
                unit=row["unit"],
                kind=row["kind"],
                via=row["via"],
                builders=tuple(row["units"]) if row["units"] is not None else None,
                x=_round(row["params"][0]) if structure else None,
                z=_round(row["params"][2]) if structure else None,
                facing=row["facing"],
                count=row["count"],
                queued=row["queued"],
                inserted=row["inserted"],
                quota=row["quota"],
                opts=option_labels(row["options"]),
            )
        )
    return dict(orders)


def build_orders(
    directory: Path | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
    replays: Iterable[str] | None = None,
    team: int | None = None,
    until_frame: int | None = None,
) -> dict[str, list[BuildOrder]]:
    """Replay -> its build orders, equal to ``Replay.build_orders(team, until_frame)``.

    Replays without build orders are left out.
    """
    commands = scan(COMMANDS, directory, since=since, until=until)
    if replays is not None:
        commands = commands.filter(pl.col("replay").is_in(list(replays)))
    if team is not None:
        commands = commands.filter(pl.col("team") == team)
    frame = build_order_frame(commands, until_frame).collect()
    return build_orders_from(frame)


def teams_from(players: pl.DataFrame) -> dict[str, dict[int, Team]]:
    """Replay -> team id -> `Team`, from rows of the players table, as `Replay.teams()`."""
    by_replay: dict[str, dict[int, Team]] = defaultdict(dict)
    for row in players.sort("replay", "slot").iter_rows(named=True):
        if row["role"] == "spectator":
            continue
        is_ai = row["role"] == "ai"
        teams = by_replay[row["replay"]]
        previous = teams.get(row["team_id"])
        player_ids = () if is_ai else (previous.player_ids if previous else ())
        has_start = row["start_x"] is not None
        teams[row["team_id"]] = Team(
            team_id=row["team_id"],
            ally_team_id=row["ally_team_id"],
            faction=row["faction"],
            is_ai=is_ai,
            player_ids=player_ids if is_ai else player_ids + (row["player_id"],),
            start_pos=(row["start_x"], row["start_z"]) if has_start else None,
        )
    return {replay: dict(sorted(teams.items())) for replay, teams in by_replay.items()}


@dataclass
class Source:
    """The replays of some days in the tables, as `open_source` found them."""

    files: dict[str, list[Path]]  # table -> the day files to read
    stored: frozenset[str] = frozenset()  # the replays to read from those files

    def scan(self, table: str, replays: Iterable[str] | None = None) -> pl.LazyFrame:
        """A lazy frame of one table: the rows of the source's replays, or of `replays`
        only (then read from the files of their days only)."""
        names = self.stored if replays is None else self.stored & set(replays)
        files = self.files.get(table) or []
        if replays is not None:
            days = {partition(name) for name in names}
            files = [path for path in files if path.parent.name in days]
        if not files:
            return pl.LazyFrame(schema=SCHEMAS[table])
        stored = pl.scan_parquet(files, hive_partitioning=False)
        return stored.filter(pl.col("replay").is_in(sorted(names)))

    def by_day(self) -> list[Source]:
        """The source split into its days, oldest first: a pass can read each in a process."""
        days: dict[str, set[str]] = defaultdict(set)
        for name in self.stored:
            days[partition(name)].add(name)
        return [
            Source(
                files={
                    table: [path for path in paths if path.parent.name == day]
                    for table, paths in self.files.items()
                },
                stored=frozenset(names),
            )
            for day, names in sorted(days.items())
        ]


def open_source(
    directory: Path | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
    replays: Iterable[str] | None = None,
    tables: Iterable[str] = TABLES,
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> Source:
    """The replays in the tables of ``directory`` of the days ``since`` (inclusive) ..
    ``until`` (exclusive), or only those of ``replays`` (names without ``.sdfz``), for a
    pass that reads ``tables``.

    A day whose files lack a table or hold another layout version is left out, with a
    message: its replays are parsed again by `reason8 parse`.
    """
    directory = directory or tables_dir()
    tables = tuple(tables)
    wanted = None if replays is None else frozenset(replays)
    files: dict[str, list[Path]] = {table: [] for table in tables}
    kept: set[str] = set()
    partitions = sorted(
        path
        for path in directory.glob(PARTITION_PREFIX + "*")
        if path.is_dir() and partition_in_range(path.name, since, until)
    )
    for partition_directory in partitions:
        day = partition_directory.name.removeprefix(PARTITION_PREFIX)
        stored = stored_replays(partition_directory, day)
        if stored is None:
            log(f"{partition_directory.name}: tables missing or not of {VERSION}, left out")
            continue
        # the replays the day's games table lists: a day being rewritten may hold more
        kept |= {name for name in stored if wanted is None or name in wanted}
        for table in tables:
            files[table].append(partition_directory / table_name(day, table))
    return Source(files, frozenset(kept))


def add_source_arguments(parser: argparse.ArgumentParser) -> None:
    """The options of a pass that reads the replays with `open_source`."""
    parser.add_argument(
        "--tables", type=Path, default=data_dir() / AREA, help="the tables of the parsed replays"
    )
    parser.add_argument("--since", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--until", type=date.fromisoformat, help="day after the last (YYYY-MM-DD)")


# --- writing


def file_version(path: Path) -> str | None:
    try:
        return pl.read_parquet_metadata(path).get(VERSION_KEY)
    except Exception:  # a missing, partial or foreign file: rebuild
        return None


def stored_replays(directory: Path, day: str) -> dict[str, int | None] | None:
    """Replay -> size of its replay file, as the day's games table records them; None when a
    table of the day is missing or holds another layout version."""
    paths = [directory / table_name(day, table) for table in TABLES]
    if any(file_version(path) != VERSION for path in paths):
        return None
    games = pl.read_parquet(directory / table_name(day, GAMES), columns=["replay", "sdfz_bytes"])
    return dict(games.iter_rows())


def staging_dir(out_dir: Path, day: str) -> Path:
    """Where the rows of single replays wait until their day is written."""
    return out_dir / STAGING / day


def stage(rows: Mapping[str, pl.DataFrame], staging: Path, name: str) -> None:
    """Keep the rows of one replay in ``staging`` until its day is written, `GAMES` last."""
    staging.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        rows[table].write_parquet(
            staging / f"{name}.{table}{SUFFIX}", compression="zstd", compression_level=1
        )


@dataclass
class DayPlan:
    """The replays of a day to stage, and what its tables hold now.

    Each task is the arguments of the function that stages one replay (`update_days`).
    """

    day: str
    tasks: list[tuple[Any, ...]]
    stored: dict[str, int | None] = field(default_factory=dict)  # replay -> sdfz size


@dataclass
class DayResult:
    day: str
    replays: int = 0
    converted: int = 0  # replays staged and written
    seconds: float = 0.0  # CPU time of the staging and the writing, in one process
    table_bytes: dict[str, int] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    up_to_date: bool = False


def write_day(day: str, stored: Iterable[str], tables_partition: Path, staging: Path) -> DayResult:
    """Write the tables of a day from its staged replays and the ``stored`` ones, in name
    order; a staged replay replaces the stored rows of the same replay.

    Each table is streamed into a temporary file and renamed into place, `GAMES` last.
    """
    suffix = f".{GAMES}{SUFFIX}"
    staged = {path.name.removesuffix(suffix) for path in staging.glob("*" + suffix)}
    names = sorted(set(stored) | staged)
    result = DayResult(day, replays=len(names), converted=len(staged))
    # runs of consecutive stored replays are read with one scan
    pieces: list[list[str] | str] = []
    for name in names:
        if name in staged:
            pieces.append(name)
        else:
            if not pieces or isinstance(pieces[-1], str):
                pieces.append([])
            pieces[-1].append(name)
    tables_partition.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        existing = tables_partition / table_name(day, table)
        sources = [
            pl.scan_parquet(staging / f"{piece}.{table}{SUFFIX}")
            if isinstance(piece, str)
            else pl.scan_parquet(existing).filter(pl.col("replay").is_in(piece))
            for piece in pieces
        ]
        frame = pl.concat(sources) if sources else pl.LazyFrame(schema=SCHEMAS[table])
        temporary_path = existing.with_name(existing.name + ".tmp")
        frame.sink_parquet(
            temporary_path,
            compression="zstd",
            compression_level=ZSTD_LEVEL,
            statistics=True,
            row_group_size=ROW_GROUP_SIZE,
            metadata={VERSION_KEY: VERSION},
            maintain_order=True,
        )
        os.replace(temporary_path, existing)
        result.table_bytes[table] = existing.stat().st_size
        result.rows[table] = pl.scan_parquet(existing).select(pl.len()).collect().item()
    for path in staging.glob("*"):
        path.unlink()
    if staging.is_dir():
        staging.rmdir()
    return result


def _timed(function: Callable[..., Any], *arguments: Any) -> tuple[Any, float]:
    started = time.process_time()
    value = function(*arguments)
    return value, time.process_time() - started


class _InProcess:
    """An executor that runs each task when it is submitted (``jobs=0``: no processes)."""

    def __enter__(self) -> _InProcess:
        return self

    def __exit__(self, *exception: object) -> None:
        return None

    def submit(self, function: Callable[..., Any], *arguments: Any) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(function(*arguments))
        return future


def update_days(
    plans: Iterable[DayPlan],
    out_dir: Path,
    task: Callable[..., dict[str, Any]],
    *,
    jobs: int = 1,
    on_entry: Callable[[dict[str, Any]], None] = lambda entry: None,
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> list[DayResult]:
    """Stage the replays of each plan with ``task(*arguments, staging)``, and write each day.

    ``task`` returns an entry for its replay (``file``, and ``status`` "ok" when it staged
    the rows, otherwise an ``error``), given to ``on_entry`` as it comes. The replays are
    staged in parallel, oldest day first, and a day is written as soon as its replays are
    done, so only the days in progress are staged. A day without replays to stage is left
    as it is. ``jobs=0`` runs everything in this process.
    """
    plans = list(plans)
    results = {plan.day: DayResult(plan.day, replays=len(plan.stored)) for plan in plans}
    by_day = {plan.day: plan for plan in plans}
    pending: dict[str, int] = {}
    tasks: list[tuple[str, tuple[Any, ...]]] = []
    for plan in plans:
        if not plan.tasks:
            results[plan.day].up_to_date = True
            continue
        staging = staging_dir(out_dir, plan.day)
        for path in staging.glob("*") if staging.is_dir() else ():
            path.unlink()  # left by a run that stopped
        pending[plan.day] = len(plan.tasks)
        tasks += [(plan.day, arguments) for arguments in plan.tasks]
    tasks.reverse()  # popped from the end: oldest day first
    executor = _InProcess() if jobs <= 0 else ProcessPoolExecutor(max_workers=jobs)
    with executor as pool:
        futures: dict[Future[Any], tuple[str, str]] = {}

        def submit_write(day: str) -> None:
            arguments = (
                day,
                list(by_day[day].stored),
                out_dir / partition_of(day),
                staging_dir(out_dir, day),
            )
            futures[pool.submit(_timed, write_day, *arguments)] = ("write", day)

        while futures or tasks:
            # a few tasks queued at a time, so that a finished day is written next
            while tasks and len(futures) < 2 * max(1, jobs):
                day, arguments = tasks.pop()
                future = pool.submit(_timed, task, *arguments, staging_dir(out_dir, day))
                futures[future] = ("stage", day)
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                kind, day = futures.pop(future)
                value, seconds = future.result()
                result = results[day]
                result.seconds += seconds
                if kind == "stage":
                    if value.get("status") != "ok":
                        result.errors.append(f"{value.get('file')}: {value.get('error')}")
                    on_entry(value)
                    pending[day] -= 1
                    if pending[day] == 0:
                        submit_write(day)
                    continue
                value.seconds, value.errors = result.seconds, result.errors
                results[day] = value
                log(
                    f"{day}: {value.converted} of {value.replays} replays written, "
                    f"{sum(value.table_bytes.values()) / 1e6:.1f} MB"
                )
    if (out_dir / STAGING).is_dir() and not any((out_dir / STAGING).iterdir()):
        (out_dir / STAGING).rmdir()
    return sorted(results.values(), key=lambda result: result.day)


def partition_of(day: str) -> str:
    return PARTITION_PREFIX + day


def summarize(results: list[DayResult]) -> str:
    built = [result for result in results if not result.up_to_date]
    converted = sum(result.converted for result in built)
    lines = [
        f"{len(results)} days, {len(results) - len(built)} up to date, {converted} replays written"
    ]
    if converted:
        table_bytes = sum(sum(result.table_bytes.values()) for result in built)
        replays = sum(result.replays for result in built)
        lines.append(
            f"{sum(result.seconds for result in built) / converted:.2f} s of CPU per replay "
            f"written; the days written hold {replays} replays in {table_bytes / 1e6:.1f} MB"
        )
        for table in TABLES:
            size = sum(result.table_bytes.get(table, 0) for result in built)
            rows = sum(result.rows.get(table, 0) for result in built)
            lines.append(f"  {table}: {rows:,} rows, {size / 1e6:.1f} MB")
    errors = sum(len(result.errors) for result in results)
    if errors:
        lines.append(f"{errors} replays failed")
    return "\n".join(lines)
