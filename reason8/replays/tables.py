"""Parquet tables of the parsed replays: commands, games, players and a few other events.

Usage::

    uv run reason8 tables                     # data/parsed/date=* -> data/tables/date=*
    uv run reason8 tables --since 2026-11-01 --until 2026-11-08 --jobs 4
    uv run reason8 tables --force             # rebuild days that are up to date

The parsed JSON documents (`reason8.replays.parse`) stay the archival copy; these tables are
derived from them, without parsing the replays again, so that a pass over many games reads the
columns it needs instead of decoding whole documents (see docs/reference/replay-format.md#tables
and ADR 0005). `reason8 parse` keeps them current for the replays it parses.

Each day of the parsed area (``parsed/date=YYYY-MM-DD/``) becomes one file per table in the same
partition of the ``tables`` area: ``tables/date=YYYY-MM-DD/YYYY-MM-DD.<table>.parquet``. A day is
up to date when its ``games`` table lists exactly the parsed files of that day with their sizes,
and is written by the current version of this module; other days are brought up to date by
converting only the replays that are new or changed. Every file is written to a temporary name
and renamed into place, ``games`` last, so a run that stops halfway leaves the day to be redone.

Read the tables with `scan` (a lazy Polars frame with ``since``/``until``), and the build orders
with `build_orders`, which returns what `Replay.build_orders` returns. A pass over the parsed
replays opens them with `open_source`, which adds the parsed replays that the tables lack by
converting their JSON, and `replay_headers` makes a `Replay` of everything but the events
from the games and players tables.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from reason8.paths import (
    PARTITION_PREFIX,
    data_dir,
    partition,
    partition_in_range,
    require_partitioned,
)
from reason8.replays.parse import OPTION_BITS, PARSED_SUFFIX
from reason8.replays.replay import (
    CTRL_MULTIPLIER,
    FORMAT,
    SHIFT_MULTIPLIER,
    BuildOrder,
    Replay,
    Team,
    load_replay,
)

#: The area of the data directory the tables are kept in.
AREA = "tables"
#: Written into every file; a day written by another version is rebuilt.
VERSION = "reason8.tables/1"
VERSION_KEY = "reason8"
SUFFIX = ".parquet"
#: Rows of single replays wait here (``<area>/_staging/<day>/``) until their day is written.
STAGING = "_staging"
#: Row groups of about two minutes of an 8v8 game, so a scan of the opening skips the rest.
ROW_GROUP_SIZE = 16_384
ZSTD_LEVEL = 9

COMMANDS = "commands"
SELECTIONS = "selections"
EVENTS = "events"
PLAYERS = "players"
GAMES = "games"
#: Written in this order: `GAMES` records what a day holds, so it goes last.
TABLES = (COMMANDS, SELECTIONS, EVENTS, PLAYERS, GAMES)

VIA = pl.Enum(["COMMAND", "AICOMMAND", "AICOMMANDS"])
#: The events other than commands and selections that get a row in `EVENTS`.
EVENT_TYPES = ("start", "gameover", "team", "playerleft", "pause", "quit")
OPTION = {name: bit for bit, name in OPTION_BITS}
SHIFT, CTRL, RIGHT, INTERNAL = OPTION["shift"], OPTION["ctrl"], OPTION["right"], OPTION["internal"]
NAMED_VALUE = pl.Struct({"name": pl.String, "value": pl.String})

SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    COMMANDS: {
        "replay": pl.String(),  # the replay file name without .sdfz; rows in stream order
        "frame": pl.Int32(),
        "player": pl.Int16(),
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
        "seq": pl.Int32(),  # index of the event in the replay's events
        "commands_before": pl.Int32(),  # commands of the replay that came before it
        "frame": pl.Int32(),
        "player": pl.Int16(),
        "units": pl.List(pl.Int32()),
    },
    EVENTS: {
        "replay": pl.String(),
        "seq": pl.Int32(),
        "commands_before": pl.Int32(),
        "frame": pl.Int32(),
        "type": pl.Enum(list(EVENT_TYPES)),
        "player": pl.Int16(),
        "action": pl.String(),  # team: giveaway, resign, join_team, team_died, ...
        "param": pl.Int32(),  # team: its param; playerleft: the reason; pause: 1 or 0
    },
    PLAYERS: {
        "replay": pl.String(),
        "slot": pl.Int16(),  # order in the document: players first, then AIs
        "team_id": pl.Int16(),
        "ally_team_id": pl.Int16(),
        "player_id": pl.Int16(),  # null for an AI
        "ai_id": pl.Int16(),  # null for a player
        "is_ai": pl.Boolean(),
        "user_id": pl.Int64(),  # for the join with the match dumps; names are not kept
        "faction": pl.String(),
        "rank": pl.Int8(),
        "skill": pl.String(),  # as the replay writes it, e.g. "[45.67]"
        "skill_uncertainty": pl.Float32(),
        "start_x": pl.Float64(),
        "start_y": pl.Float64(),
        "start_z": pl.Float64(),
        "ai_short_name": pl.String(),
        "ai_version": pl.String(),
    },
    GAMES: {
        "replay": pl.String(),
        "parsed_bytes": pl.Int64(),  # size of the .json.zst the rows come from
        "sdfz_bytes": pl.Int64(),
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
                    "left": pl.Float64(),
                    "top": pl.Float64(),
                    "right": pl.Float64(),
                    "bottom": pl.Float64(),
                }
            )
        ),
        "modoptions": pl.List(NAMED_VALUE),
        "mapoptions": pl.List(NAMED_VALUE),
        "restrictions": pl.List(NAMED_VALUE),
        "unitdefs": pl.List(pl.String()),
    },
}


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


def _string(value: Any) -> str | None:
    return None if value is None else str(value)


def _named_values(values: Mapping[str, Any] | None) -> list[dict[str, str | None]]:
    return [{"name": str(name), "value": _string(value)} for name, value in (values or {}).items()]


def _skill_uncertainty(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except ValueError:
        return None


def replay_tables(
    replay: Replay, name: str, parsed_bytes: int | None = None
) -> dict[str, pl.DataFrame]:
    """The rows of one parsed replay in every table, ``name`` being its key (``replay``)."""
    columns: dict[str, dict[str, list[Any]]] = {
        table: {column: [] for column in schema} for table, schema in SCHEMAS.items()
    }
    selections, events = columns[SELECTIONS], columns[EVENTS]
    command_rows: list[tuple[Any, ...]] = []
    for seq, event in enumerate(replay.events):
        kind = event["type"]
        if kind == "cmd":
            command = event
            inserted = event.get("cmd") == "INSERT" and "inner" in event
            if inserted:
                command = event["inner"]
            params = raw_params(command)
            build = command.get("cmd") == "BUILD" and len(params) >= 3
            command_rows.append(
                (
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
            )
        elif kind == "select":
            for column, value in (
                ("replay", name),
                ("seq", seq),
                ("commands_before", len(command_rows)),
                ("frame", event.get("frame")),
                ("player", event.get("player")),
                ("units", event.get("units")),
            ):
                selections[column].append(value)
        elif kind in EVENT_TYPES:
            if kind == "pause":
                param = int(bool(event.get("paused")))
            elif kind == "playerleft":
                param = event.get("reason")
            else:
                param = event.get("param")
            action = event.get("action")
            for column, value in (
                ("replay", name),
                ("seq", seq),
                ("commands_before", len(command_rows)),
                ("frame", event.get("frame")),
                ("type", kind),
                ("player", event.get("player")),
                ("action", None if action is None else str(action)),
                ("param", param),
            ):
                events[column].append(value)

    command_columns = list(SCHEMAS[COMMANDS])[1:]
    transposed = zip(*command_rows, strict=True) if command_rows else [()] * len(command_columns)
    columns[COMMANDS] = {"replay": [name] * len(command_rows)} | {
        column: list(values) for column, values in zip(command_columns, transposed, strict=True)
    }
    players = columns[PLAYERS]
    for slot, (record, is_ai) in enumerate(
        [(player, False) for player in replay.players] + [(ai, True) for ai in replay.ais]
    ):
        start = record.get("startPos") or {}
        values = {
            "replay": name,
            "slot": slot,
            "team_id": record.get("teamId"),
            "ally_team_id": record.get("allyTeamId"),
            "player_id": None if is_ai else record.get("playerId"),
            "ai_id": record.get("aiId") if is_ai else None,
            "is_ai": is_ai,
            "user_id": _integer(record.get("userId")),
            "faction": record.get("faction"),
            "rank": record.get("rank"),
            "skill": _string(record.get("skill")),
            "skill_uncertainty": _skill_uncertainty(record.get("skillUncertainty")),
            "start_x": start.get("x") if record.get("startPos") else None,
            "start_y": start.get("y"),
            "start_z": start.get("z") if record.get("startPos") else None,
            "ai_short_name": record.get("shortName") if is_ai else None,
            "ai_version": record.get("version") if is_ai else None,
        }
        for column, value in values.items():
            players[column].append(value)

    meta = replay.meta
    document = replay.doc
    source = document.get("source") or {}
    game = {
        "replay": name,
        "parsed_bytes": parsed_bytes,
        "sdfz_bytes": source.get("bytes"),
        "parser": source.get("parser"),
        "match_id": _integer(meta.get("serverMatchId")),
        "game_id": meta.get("gameId"),
        "engine": meta.get("engine"),
        "game": meta.get("game"),
        "map": meta.get("map"),
        "start_time": meta.get("startTime"),
        "duration_ms": meta.get("durationMs"),
        "full_duration_ms": meta.get("fullDurationMs"),
        "winning_ally_teams": meta.get("winningAllyTeamIds"),
        "start_pos_type": meta.get("startPosType"),
        "demo_version": meta.get("demoVersion"),
        "game_time": meta.get("gameTime"),
        "wallclock_time": meta.get("wallclockTime"),
        "start_frame": meta.get("startFrame"),
        "end_frame": meta.get("endFrame"),
        "ally_teams": [
            {
                "ally_team_id": ally_team.get("allyTeamId"),
                "player_count": ally_team.get("playerCount"),
                **{
                    side: (ally_team.get("startBox") or {}).get(side)
                    for side in ("left", "top", "right", "bottom")
                },
            }
            for ally_team in document.get("allyTeams") or []
        ],
        "modoptions": _named_values(document.get("modoptions")),
        "mapoptions": _named_values(document.get("mapoptions")),
        "restrictions": _named_values(document.get("restrictions")),
        "unitdefs": document.get("unitdefs"),
    }
    for column, value in game.items():
        columns[GAMES][column].append(value)
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
    """A column from Python values; lists of numbers are built in bulk, which is much faster."""
    if not (isinstance(dtype, pl.List) and dtype.inner.is_numeric()) or len(values) < 2:
        return pl.Series(name, values, dtype=dtype, strict=False)
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
                "value": pl.Series(flat, dtype=dtype.inner, strict=False),
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
    groups (about two minutes of a game each) they rule out.
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


def _round(value: float | None) -> float | None:
    """A float32 parameter back to the value the JSON keeps (2 decimals)."""
    return None if value is None else round(value, 2)


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
        teams = by_replay[row["replay"]]
        previous = teams.get(row["team_id"])
        player_ids = () if row["is_ai"] else (previous.player_ids if previous else ())
        has_start = row["start_x"] is not None
        teams[row["team_id"]] = Team(
            team_id=row["team_id"],
            ally_team_id=row["ally_team_id"],
            faction=row["faction"],
            is_ai=row["is_ai"],
            player_ids=player_ids if row["is_ai"] else player_ids + (row["player_id"],),
            start_pos=(row["start_x"], row["start_z"]) if has_start else None,
        )
    return {replay: dict(sorted(teams.items())) for replay, teams in by_replay.items()}


def options_dict(options: Iterable[Mapping[str, str | None]] | None) -> dict[str, str | None]:
    """A ``modoptions``/``mapoptions`` column value as the dict the JSON has."""
    return {option["name"]: option["value"] for option in options or ()}


def _start_pos(row: Mapping[str, Any]) -> dict[str, float | None] | None:
    if row["start_x"] is None:
        return None
    return {"x": row["start_x"], "y": row["start_y"], "z": row["start_z"]}


def replay_headers(games: pl.DataFrame, players: pl.DataFrame) -> dict[str, Replay]:
    """Replay -> a `Replay` of everything but its events, from rows of the games and players.

    What the parsed document says about the game and its players: ``meta``, ``players``,
    ``ais``, ``allyTeams``, ``modoptions``, ``mapoptions``, ``restrictions``, ``unitdefs`` and
    ``source``, so that `Replay.teams()`, the positions of `reason8.game.positions` and the
    like work as on the document. Names, ``spectators`` and ``statistics`` are not in the
    tables, and ``events`` is left out: read the commands from their table. A player's
    ``skillUncertainty`` is the float32 of the table.
    """
    by_replay: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"players": [], "ais": []}
    )
    for row in players.sort("replay", "slot").iter_rows(named=True):
        if row["is_ai"]:
            record = {"aiId": row["ai_id"], "shortName": row["ai_short_name"]}
            record["version"] = row["ai_version"]
        else:
            record = {"playerId": row["player_id"]}
        record |= {
            "teamId": row["team_id"],
            "allyTeamId": row["ally_team_id"],
            "userId": row["user_id"],
            "faction": row["faction"],
            "rank": row["rank"],
            "skill": row["skill"],
            "skillUncertainty": row["skill_uncertainty"],
            "startPos": _start_pos(row),
        }
        by_replay[row["replay"]]["ais" if row["is_ai"] else "players"].append(record)
    headers = {}
    for row in games.iter_rows(named=True):
        meta = {
            "gameId": row["game_id"],
            "engine": row["engine"],
            "game": row["game"],
            "map": row["map"],
            "startTime": row["start_time"],
            "durationMs": row["duration_ms"],
            "fullDurationMs": row["full_duration_ms"],
            "winningAllyTeamIds": row["winning_ally_teams"],
            "startPosType": row["start_pos_type"],
            "demoVersion": row["demo_version"],
            "gameTime": row["game_time"],
            "wallclockTime": row["wallclock_time"],
            "startFrame": row["start_frame"],
            "endFrame": row["end_frame"],
            "serverMatchId": None if row["match_id"] is None else str(row["match_id"]),
        }
        ally_teams = []
        for ally_team in row["ally_teams"] or ():
            box = {side: ally_team[side] for side in ("left", "top", "right", "bottom")}
            ally_teams.append(
                {
                    "allyTeamId": ally_team["ally_team_id"],
                    "playerCount": ally_team["player_count"],
                    "startBox": box if any(value is not None for value in box.values()) else None,
                }
            )
        records = by_replay.get(row["replay"], {"players": [], "ais": []})
        headers[row["replay"]] = Replay(
            {
                "format": FORMAT,
                "source": {"bytes": row["sdfz_bytes"], "parser": row["parser"]},
                "meta": meta,
                "allyTeams": ally_teams,
                "players": records["players"],
                "ais": records["ais"],
                "modoptions": options_dict(row["modoptions"]),
                "mapoptions": options_dict(row["mapoptions"]),
                "restrictions": options_dict(row["restrictions"]),
                "unitdefs": row["unitdefs"],
            }
        )
    return headers


@dataclass
class Source:
    """The rows of the replays of some days, as `open_source` found them.

    The rows of most replays come from the day files of the tables; those of the parsed
    replays that the tables lack (new, changed, or in a day written by another version) were
    converted from their JSON. `unreadable` holds the parsed replays that could not be read,
    with the error.
    """

    files: dict[str, list[Path]]  # table -> the day files to read
    stored: frozenset[str] = frozenset()  # the replays whose rows are read from those files
    converted: dict[str, dict[str, pl.DataFrame]] = field(default_factory=dict)
    unreadable: dict[str, str] = field(default_factory=dict)

    def scan(self, table: str, replays: Iterable[str] | None = None) -> pl.LazyFrame:
        """A lazy frame of one table: the stored rows, then those of the converted replays.

        With `replays`, only theirs, read from the files of their days only.
        """
        wanted = None if replays is None else set(replays)
        names = self.stored if wanted is None else self.stored & wanted
        files = self.files.get(table) or []
        if wanted is not None:
            days = {partition(name) for name in names}
            files = [path for path in files if path.parent.name in days]
        frames = []
        if files:
            stored = pl.scan_parquet(files, hive_partitioning=False)
            frames.append(stored.filter(pl.col("replay").is_in(sorted(names))))
        frames += [
            rows[table].lazy()
            for name, rows in self.converted.items()
            if table in rows and (wanted is None or name in wanted)
        ]
        if not frames:
            return pl.LazyFrame(schema=SCHEMAS[table])
        return pl.concat(frames)

    def by_day(self) -> list[Source]:
        """The source split into its days, oldest first: a pass can read each in a process."""
        days: dict[str, set[str]] = defaultdict(set)
        for name in [*self.stored, *self.converted, *self.unreadable]:
            days[partition(name)].add(name)
        return [
            Source(
                files={
                    table: [path for path in paths if path.parent.name == day]
                    for table, paths in self.files.items()
                },
                stored=frozenset(self.stored & names),
                converted={
                    name: self.converted[name] for name in sorted(names & set(self.converted))
                },
                unreadable={
                    name: self.unreadable[name] for name in sorted(names & set(self.unreadable))
                },
            )
            for day, names in sorted(days.items())
        ]


def open_source(
    parsed_dir: Path | None,
    directory: Path | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
    replays: Iterable[str] | None = None,
    tables: Iterable[str] = TABLES,
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> Source:
    """The replays of the days ``since`` (inclusive) .. ``until`` (exclusive) for a pass.

    These are the replays in the tables of ``directory`` and the parsed replays in
    ``parsed_dir``, or only those of ``replays`` (names without ``.sdfz``). A parsed replay
    that the tables lack or hold for an older parsed file is converted from its JSON here,
    one at a time, and only its rows of ``tables`` are kept; `reason8 tables` stores them
    instead, so that the next pass does not convert them again.
    """
    directory = directory or tables_dir()
    tables = tuple(tables)
    wanted = None if replays is None else frozenset(replays)
    files: dict[str, list[Path]] = {table: [] for table in tables}
    kept: set[str] = set()
    to_convert: list[tuple[str, Path, int]] = []
    stored_days: dict[str, dict[str, int] | None] = {}
    partitions = sorted(
        path
        for path in directory.glob(PARTITION_PREFIX + "*")
        if path.is_dir() and partition_in_range(path.name, since, until)
    )
    for partition_directory in partitions:
        day = partition_directory.name.removeprefix(PARTITION_PREFIX)
        stored = stored_replays(partition_directory, day)
        stored_days[day] = stored
        if stored is None:  # incomplete, or written by another version: read from the JSON
            continue
        # the replays the day's games table lists: a day being rewritten may hold more
        kept |= {name for name in stored if wanted is None or name in wanted}
        for table in tables:
            files[table].append(partition_directory / table_name(day, table))
    parsed_partitions = parsed_days(parsed_dir, since, until) if parsed_dir else []
    for parsed_partition in parsed_partitions:
        day = parsed_partition.name.removeprefix(PARTITION_PREFIX)
        stored = stored_days.get(day) or {}
        for path in sorted(parsed_partition.glob("*" + PARSED_SUFFIX)):
            name = replay_key(path)
            if wanted is not None and name not in wanted:
                continue
            size = path.stat().st_size
            if stored.get(name) != size:
                to_convert.append((name, path, size))
                kept.discard(name)
    source = Source(files, frozenset(kept))
    if to_convert:
        log(
            f"{len(to_convert)} parsed replays are not in the tables or changed since: "
            "reading them from the JSON (`reason8 tables` stores them)"
        )
    for name, path, size in to_convert:
        try:
            rows = replay_tables(load_replay(path), name, size)
        except Exception as error:  # reported by the pass, as a replay it could not read
            source.unreadable[name] = str(error)
            continue
        source.converted[name] = {table: rows[table] for table in tables}
    return source


def add_source_arguments(parser: argparse.ArgumentParser) -> None:
    """The options of a pass that reads the replays with `open_source`."""
    parser.add_argument(
        "--parsed",
        type=Path,
        default=data_dir() / "parsed",
        help="parsed replays, read for those the tables lack",
    )
    parser.add_argument(
        "--tables", type=Path, default=data_dir() / AREA, help="the tables (reason8 tables)"
    )
    parser.add_argument("--since", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--until", type=date.fromisoformat, help="day after the last (YYYY-MM-DD)")


# --- writing


def file_version(path: Path) -> str | None:
    try:
        return pl.read_parquet_metadata(path).get(VERSION_KEY)
    except Exception:  # a missing, partial or foreign file: rebuild
        return None


def staging_dir(out_dir: Path, day: str) -> Path:
    """Where the rows of single replays wait until their day is written."""
    return out_dir / STAGING / day


def convert_replay(path: Path, staging: Path) -> str | None:
    """Convert one parsed replay into staged files, one per table; return an error or None."""
    name = replay_key(path)
    try:
        rows = replay_tables(load_replay(path), name, path.stat().st_size)
    except Exception as error:  # one bad file must not stop the day; it is retried next time
        return f"{path.name}: {type(error).__name__}: {error}"[:500]
    staging.mkdir(parents=True, exist_ok=True)
    for table, frame in rows.items():
        frame.write_parquet(
            staging / f"{name}.{table}{SUFFIX}", compression="zstd", compression_level=1
        )
    return None


@dataclass
class DayPlan:
    """What a day needs: the parsed replays, the ones to convert and the ones to keep."""

    day: str
    parsed: dict[str, Path]  # replay -> parsed file
    sizes: dict[str, int]
    kept: set[str]
    up_to_date: bool

    @property
    def to_convert(self) -> list[Path]:
        return [path for name, path in self.parsed.items() if name not in self.kept]


def plan_day(parsed_partition: Path, tables_partition: Path, force: bool = False) -> DayPlan:
    day = parsed_partition.name.removeprefix(PARTITION_PREFIX)
    parsed = {replay_key(path): path for path in sorted(parsed_partition.glob("*" + PARSED_SUFFIX))}
    sizes = {name: path.stat().st_size for name, path in parsed.items()}
    stored = None if force else stored_replays(tables_partition, day)
    kept = {name for name, size in (stored or {}).items() if sizes.get(name) == size}
    return DayPlan(day, parsed, sizes, kept, up_to_date=stored == sizes)


def write_day(plan: DayPlan, tables_partition: Path, staging: Path) -> DayResult:
    """Write the tables of a day from its kept rows and its staged replays, in replay order.

    Each table is streamed into a temporary file and renamed into place, `GAMES` last.
    """
    result = DayResult(plan.day, replays=len(plan.parsed))
    result.parsed_bytes = sum(plan.sizes.values())
    staged = {name for name in plan.parsed if (staging / f"{name}.{GAMES}{SUFFIX}").exists()}
    # runs of consecutive kept replays are read with one scan
    pieces: list[list[str] | str] = []
    for name in plan.parsed:
        if name in plan.kept:
            if not pieces or isinstance(pieces[-1], str):
                pieces.append([])
            pieces[-1].append(name)
        elif name in staged:
            pieces.append(name)
    tables_partition.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        existing = tables_partition / table_name(plan.day, table)
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
    result.converted = len(staged)
    for path in staging.glob("*"):
        path.unlink()
    if staging.is_dir():
        staging.rmdir()
    return result


@dataclass
class DayResult:
    day: str
    replays: int = 0
    converted: int = 0
    seconds: float = 0.0  # CPU time of the conversions and the writing, in one process
    parsed_bytes: int = 0
    table_bytes: dict[str, int] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    up_to_date: bool = False


def replay_key(path: Path) -> str:
    return path.name.removesuffix(PARSED_SUFFIX)


def stored_replays(directory: Path, day: str) -> dict[str, int] | None:
    """Replay -> parsed size, as the day's games table records them, or None to rebuild."""
    paths = [directory / table_name(day, table) for table in TABLES]
    if any(file_version(path) != VERSION for path in paths):
        return None
    games = pl.read_parquet(directory / table_name(day, GAMES), columns=["replay", "parsed_bytes"])
    return dict(games.iter_rows())


def update_day(parsed_partition: Path, tables_partition: Path, force: bool = False) -> DayResult:
    """Bring the tables of one day up to date with its parsed replays, in this process."""
    return update([parsed_partition], tables_partition.parent, jobs=0, force=force)[0]


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


def update(
    days: Iterable[Path],
    out_dir: Path,
    *,
    jobs: int = 1,
    force: bool = False,
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> list[DayResult]:
    """Bring the tables of the given parsed partitions up to date.

    Replays are converted in parallel, oldest day first, and a day is written as soon as its
    replays are converted, so only the days in progress are staged. ``jobs=0`` runs everything
    in this process.
    """
    plans = [plan_day(day, out_dir / day.name, force) for day in days]
    results = {plan.day: DayResult(plan.day, replays=len(plan.parsed)) for plan in plans}
    by_day = {plan.day: plan for plan in plans}
    pending: dict[str, int] = {}
    conversions: list[tuple[str, Path]] = []
    for plan in plans:
        if plan.up_to_date:
            results[plan.day].up_to_date = True
            results[plan.day].parsed_bytes = sum(plan.sizes.values())
            continue
        staging = staging_dir(out_dir, plan.day)
        for path in staging.glob("*") if staging.is_dir() else ():
            path.unlink()  # left by a run that stopped
        pending[plan.day] = len(plan.to_convert)
        conversions += [(plan.day, path) for path in plan.to_convert]
    conversions.reverse()  # popped from the end: oldest day first
    executor = _InProcess() if jobs <= 0 else ProcessPoolExecutor(max_workers=jobs)
    with executor as pool:
        futures: dict[Future[Any], tuple[str, str]] = {}

        def submit_write(day: str) -> None:
            arguments = (by_day[day], out_dir / partition_of(day), staging_dir(out_dir, day))
            futures[pool.submit(_timed, write_day, *arguments)] = ("write", day)

        for day, count in pending.items():
            if count == 0:
                submit_write(day)
        while futures or conversions:
            # a few conversions queued at a time, so that a finished day is written next
            while conversions and len(futures) < 2 * max(1, jobs):
                day, path = conversions.pop()
                future = pool.submit(_timed, convert_replay, path, staging_dir(out_dir, day))
                futures[future] = ("convert", day)
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                kind, day = futures.pop(future)
                value, seconds = future.result()
                result = results[day]
                result.seconds += seconds
                if kind == "convert":
                    if value is not None:
                        result.errors.append(value)
                    pending[day] -= 1
                    if pending[day] == 0:
                        submit_write(day)
                    continue
                value.seconds, value.errors = result.seconds, result.errors
                results[day] = value
                log(
                    f"{day}: {value.converted} of {value.replays} replays converted, "
                    f"{sum(value.table_bytes.values()) / 1e6:.1f} MB"
                )
                for error in value.errors:
                    log(f"  {error}")
    if (out_dir / STAGING).is_dir() and not any((out_dir / STAGING).iterdir()):
        (out_dir / STAGING).rmdir()
    for result in results.values():
        if result.up_to_date:
            log(f"{result.day}: up to date ({result.replays} replays)")
    return sorted(results.values(), key=lambda result: result.day)


def partition_of(day: str) -> str:
    return PARTITION_PREFIX + day


def parsed_days(
    parsed_dir: Path, since: date | None = None, until: date | None = None
) -> list[Path]:
    """The partitions of the parsed area in the range, oldest first."""
    return sorted(
        path
        for path in parsed_dir.glob(PARTITION_PREFIX + "*")
        if path.is_dir() and partition_in_range(path.name, since, until)
    )


def default_jobs() -> int:
    """A quarter of the CPU threads: each process holds one parsed replay, 0.3 to 2 GB."""
    return max(1, (os.cpu_count() or 1) // 4)


def summarize(results: list[DayResult]) -> str:
    built = [result for result in results if not result.up_to_date]
    converted = sum(result.converted for result in built)
    lines = [
        f"{len(results)} days, {len(results) - len(built)} up to date, "
        f"{converted} replays converted"
    ]
    if converted:
        seconds = sum(result.seconds for result in built)
        parsed_bytes = sum(result.parsed_bytes for result in built)
        table_bytes = sum(sum(result.table_bytes.values()) for result in built)
        lines.append(
            f"{seconds / converted:.2f} s of CPU per replay, tables "
            f"{table_bytes / 1e6:.1f} MB = {table_bytes / parsed_bytes:.0%} of the parsed JSON"
        )
        for table in TABLES:
            size = sum(result.table_bytes.get(table, 0) for result in built)
            rows = sum(result.rows.get(table, 0) for result in built)
            lines.append(f"  {table}: {rows:,} rows, {size / 1e6:.1f} MB")
    errors = sum(len(result.errors) for result in results)
    if errors:
        lines.append(f"{errors} replays could not be read")
    return "\n".join(lines)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--parsed", type=Path, default=data_dir() / "parsed")
    parser.add_argument("--out", type=Path, default=data_dir() / AREA)
    parser.add_argument(
        "--jobs",
        type=int,
        default=default_jobs(),
        help="replays converted in parallel (default: a quarter of the CPU threads)",
    )
    parser.add_argument("--force", action="store_true", help="rebuild days that are up to date")
    parser.add_argument("--since", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--until", type=date.fromisoformat, help="day after the last (YYYY-MM-DD)")


def run(args: argparse.Namespace) -> int:
    require_partitioned(args.parsed, "*" + PARSED_SUFFIX)
    days = parsed_days(args.parsed, args.since, args.until)
    print(f"{len(days)} days of parsed replays", file=sys.stderr)
    results = update(days, args.out, jobs=args.jobs, force=args.force)
    print(summarize(results), file=sys.stderr)
    return 0
