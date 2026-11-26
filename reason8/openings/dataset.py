"""Build the opening dataset: one row per build order of every player's opening.

Usage::

    uv run reason8 maps fetch         # once: the pinned map list
    uv run reason8 contact            # once: re-simulated games -> contact
    uv run reason8 dataset            # tables of the parsed replays -> openings_v2/
    uv run reason8 dataset --since 2026-11-01 --out data/datasets/november    # a part of it
    uv run reason8 dataset --stats    # the tables of docs/reference/openings-dataset.md

The games are the training slice (`reason8.data.matches.select_matches()` over the pinned
window of docs/reference/dataset.md) whose replays are parsed in ``<data dir>/parsed/``;
``--since`` and ``--until`` narrow the window to the date partitions of those days. Building
again reads whatever is parsed by then and rewrites the dataset: the split of a game
depends only on its match id, so games never move between splits as more replays are
parsed. The replays are read from their Parquet tables (`reason8.replays.tables`): the game
and its players from the games and players tables, the orders from the build commands of
the opening window, as Polars frames.

An opening is a player's build orders until their first contact with the enemy, and at
most the first 8 minutes (`reason8.openings.contact`): the measured contact when the game
was re-simulated, and otherwise the usual one of the map and start position. Where an
opening ends and how the games are split is ADR 0012; which games and openings are left
out follows ADR 0015 (balance patches) and ADR 0011 (positions). The output, in
``<data dir>/datasets/openings_v2/``:

``train.parquet``, ``validation.parquet``, ``test.parquet``
    One row per build order of an opening, with the columns of the game and the player.
``openings.parquet``
    One row per player of every game used, with the split and why an opening was dropped.
``games.parquet``
    One row per parsed game of the slice, with the split and why a game was left out.
``splits/<split>.txt``
    The match ids of each split.
``manifest.json``
    What went in, the counts and the code version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from reason8 import markdown
from reason8.data import matches
from reason8.game.maps import COMMIT as MAP_LIST_COMMIT
from reason8.game.maps import MapMetadata, load_map_list
from reason8.game.positions import game_shape, position_order, replay_positions, start_setup
from reason8.game.versions import (
    UNIT_RENAMES,
    balance_options,
    build_number,
    current_unit_name,
    loaded_factions,
    opening_era,
)
from reason8.openings import contact
from reason8.openings.extract import (
    FACTION_PREFIXES,
    FACTIONS,
    OPENING_SECONDS,
    first_factory,
    unit_role,
)
from reason8.paths import (
    REPO_ROOT,
    data_dir,
    partition,
    partition_in_range,
    require_partitioned,
)
from reason8.replays import tables, widgets
from reason8.replays.parse import PARSED_SUFFIX
from reason8.replays.replay import GAME_SPEED, Replay

NAME = "openings_v2"
FORMAT = "reason8.openings/2"
# Where an opening ends: at the player's first contact with the enemy (ADR 0012), or only
# at the end of the opening window, as in openings_v1.
UNTIL_CONTACT = "contact"
WHOLE_WINDOW = "window"
CUTOFFS = (UNTIL_CONTACT, WHOLE_WINDOW)
# The slice window of docs/reference/dataset.md, pinned so the selection does not move with
# the dumps.
SLICE_SINCE = datetime(2026, 5, 23)
SLICE_UNTIL = datetime(2026, 11, 22)
TEAM_COUNT, TEAM_SIZE = 2, 8

# A game's split is decided by a hash of its match id alone: sha256 of SPLIT_SALT and the
# id, the first 8 bytes as a number, modulo 100. The shares are in percent.
SPLIT_SALT = "reason8-openings-split"
SPLITS = (("train", 80), ("validation", 10), ("test", 10))

# Why a game is left out (games.parquet, column `status`).
INCLUDED = "ok"
WITH_BOTS = "bots in the game"
NOT_A_RELEASE = "not a released game version"
UNIT_TWEAKS = "custom unit tweaks or stat multipliers"
WATER_LEVEL = "changed water level"
WRONG_SHAPE = "not two teams of 8"
UNREADABLE = "unreadable replay"
# Why an opening is dropped (openings.parquet, column `status`).
REMOVED_UNIT = "orders a removed unit"

_TWEAK_PREFIXES = ("tweakdefs", "tweakunits", "multiplier_")
_GAMES_PER_PART = 250
FACTION_NAMES = dict(zip(FACTION_PREFIXES, FACTIONS, strict=True))


def split_of(match_id: int | str) -> str:
    """The split of a match: a fixed function of its id (see `SPLIT_SALT`)."""
    digest = hashlib.sha256(f"{SPLIT_SALT}/{match_id}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    for name, share in SPLITS:
        if bucket < share:
            return name
        bucket -= share
    raise AssertionError("split shares must add up to 100")


def game_exclusion(replay: Replay) -> str | None:
    """Why a game is left out of the dataset, or None when it is used."""
    if replay.ais:
        return WITH_BOTS
    if build_number(replay.meta.get("game")) is None:
        return NOT_A_RELEASE
    options = balance_options(replay.doc.get("modoptions") or {})
    if any(name.startswith(_TWEAK_PREFIXES) for name in options):
        return UNIT_TWEAKS
    if str((replay.doc.get("modoptions") or {}).get("map_waterlevel", "0")) not in ("0", ""):
        return WATER_LEVEL
    team_sizes = Counter(team.ally_team_id for team in replay.teams().values())
    if sorted(team_sizes.values()) != [TEAM_SIZE] * TEAM_COUNT:
        return WRONG_SHAPE
    return None


@dataclass
class GameExtract:
    """What one replay gives the dataset: the game, its players and their orders.

    `game_and_players` makes the game and its players up to their cutoffs, and
    `player_openings` adds the players' orders, for many games at once.
    """

    game: dict[str, Any]
    players: list[dict[str, Any]] = field(default_factory=list)
    orders: pl.DataFrame = field(default_factory=lambda: pl.DataFrame(schema=ORDER_COLUMNS))


ORDER_COLUMNS = {
    "match_id": pl.Int64,
    "player_slot": pl.Int32,
    "order_index": pl.Int32,  # every build order of the opening, removals included
    "seq_idx": pl.Int32,  # orders that add a unit only; null for removals
    "frame": pl.Int32,
    "unit": pl.String,
    "kind": pl.String,  # structure (placed) or factory (unit production)
    "count": pl.Int32,  # units added; negative: taken out of a factory queue
    "via": pl.String,
    "queued": pl.Boolean,
    "inserted": pl.Boolean,
    "quota": pl.Boolean,
    "repeat": pl.Boolean,  # same unit, same frame as the order before: one drag or click
    "x": pl.Float32,
    "z": pl.Float32,
}


def game_and_players(
    replay: Replay,
    match_id: int,
    map_list: Mapping[str, MapMetadata] | None = None,
    seconds: int = OPENING_SECONDS,
    cutoff: str = UNTIL_CONTACT,
    measured: Mapping[int, int | None] | None = None,
    position_cutoffs: Mapping[str, Mapping[str, int]] | None = None,
) -> GameExtract:
    """The game record, and for a game that is used its players with their cutoffs.

    `seconds` is the opening window. With the `UNTIL_CONTACT` cutoff an opening ends
    earlier, at the player's first contact: `measured` (player -> frame) when the game was
    re-simulated, and otherwise the usual one of the map and position (`position_cutoffs`,
    by default `reason8.openings.contact.POSITION_CUTOFF_SECONDS`). The replay's events
    are not needed: a header of `reason8.replays.tables.replay_headers` will do. The
    columns that come from the orders are added by `player_openings`.
    """
    game_version = replay.meta.get("game")
    build = build_number(game_version)
    era = opening_era(build) if build is not None else None
    setup = start_setup(replay, map_list)
    team_count, team_size = game_shape(replay)
    status = game_exclusion(replay)
    game = {
        "match_id": match_id,
        "split": split_of(match_id),
        "status": status or INCLUDED,
        "map": replay.meta.get("map"),
        "team_count": team_count,
        "team_size": team_size,
        "game_version": game_version,
        "build": build,
        "opening_era": era.first_build if era else None,
        "opening_era_name": era.name if era else None,
        "balance_options": json.dumps(balance_options(replay.doc.get("modoptions") or {})),
        "factions": " ".join(sorted(loaded_factions(replay.doc.get("unitdefs") or []))),
        "positions_source": setup.positions_source,
        "positions_shown": setup.overlay,
        "default_boxes": setup.default_boxes,
        "parser": (replay.doc.get("source") or {}).get("parser"),
        "contact_measured": cutoff == UNTIL_CONTACT and measured is not None,
        "unit_control_widgets": widgets.unit_control_allowed(replay.doc.get("modoptions") or {}),
    }
    extract = GameExtract(game)
    if status is not None:
        return extract
    winners = set(replay.winning_ally_teams)
    positions = replay_positions(replay, map_list)
    users = {player["teamId"]: player.get("userId") for player in replay.players}
    window_frames = seconds * GAME_SPEED
    for team in replay.teams().values():
        position = positions.get(team.team_id)
        cutoff_frame, cutoff_source = window_frames, contact.WINDOW
        if cutoff == UNTIL_CONTACT:
            cutoff_frame, cutoff_source = contact.opening_cutoff(
                replay.meta.get("map"),
                position.spawn_point if position else None,
                window_frames,
                measured,
                team.team_id,
                position_cutoffs,
            )
        extract.players.append(
            {
                "match_id": match_id,
                "player_slot": team.team_id,
                "user_id": users.get(team.team_id),
                "ally_team": team.ally_team_id,
                "faction_picked": team.faction,
                "start_x": team.start_pos[0] if team.start_pos else None,
                "start_z": team.start_pos[1] if team.start_pos else None,
                "position": position.spawn_point if position else None,
                "role": position.role if position else None,
                "position_side": position.side if position else None,
                "position_index": position.index if position else None,
                "position_distance": position.distance if position else None,
                "on_spot": position.on_spot if position else None,
                "won": team.ally_team_id in winners if winners else None,
                "cutoff_frame": cutoff_frame,
                "cutoff_source": cutoff_source,
            }
        )
    return extract


def player_openings(
    commands: pl.LazyFrame, players: pl.DataFrame, seconds: int = OPENING_SECONDS
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The opening orders of the players, and the players with the columns of their orders.

    `commands` are rows of the commands table (`reason8.replays.tables`), and `players` the
    players of `game_and_players` with a ``replay`` column that names their rows there. An
    opening is the build orders of the opening window (`seconds`) that have a unit, up to
    the player's ``cutoff_frame``, with today's unit names (`current_unit_name`). Returns
    the orders with `ORDER_COLUMNS`, by player and in stream order, and `players` in their
    order with `PLAYER_SCHEMA`.
    """
    player = ["match_id", "player_slot"]
    players = players.with_columns(
        pl.col("match_id").cast(pl.Int64),
        pl.col("player_slot").cast(pl.Int32),
        pl.col("cutoff_frame").cast(pl.Int32),
    )
    renames = {unit: current_unit_name(unit) for unit in UNIT_RENAMES}
    window = (
        tables.build_order_frame(commands, until_frame=seconds * GAME_SPEED)
        .filter(pl.col("team").is_not_null(), pl.col("unit").is_not_null(), pl.col("unit") != "")
        .select(
            "replay",
            pl.col("team").cast(pl.Int32).alias("player_slot"),
            "frame",
            pl.col("unit").alias("ordered_unit"),
            "kind",
            "count",
            pl.col("via").cast(pl.String),
            "queued",
            "inserted",
            "quota",
            "x",
            "z",
        )
        .join(
            players.lazy().select("replay", *player, "cutoff_frame"),
            on=["replay", "player_slot"],
            maintain_order="left",
        )
        .sort(player, maintain_order=True)
        .collect()
    )
    added = pl.col("count") > 0
    orders = (
        window.filter(pl.col("frame") <= pl.col("cutoff_frame"))
        .with_columns(
            unit=pl.col("ordered_unit").replace(renames),
            order_index=pl.int_range(pl.len()).over(player),
            seq_idx=pl.when(added).then(added.cast(pl.Int32).cum_sum().over(player) - 1),
            repeat=(
                (pl.col("frame") == pl.col("frame").shift(1).over(player))
                & (pl.col("ordered_unit") == pl.col("ordered_unit").shift(1).over(player))
            ).fill_null(False),
        )
        .select([pl.col(name).cast(dtype) for name, dtype in ORDER_COLUMNS.items()])
    )
    in_window = window.group_by(player).agg(pl.len().alias("orders_in_window"))
    kept = orders.group_by(player).agg(
        pl.len().alias("orders"),
        added.sum().alias("added"),
        pl.col("unit").unique().sort().alias("units"),
        pl.col("unit").alias("ordered"),
    )
    found = (
        players.join(in_window, on=player, how="left", maintain_order="left")
        .join(kept, on=player, how="left", maintain_order="left")
        .with_columns(
            pl.col("orders_in_window", "orders", "added").fill_null(0),
            pl.col("units").fill_null([]),
        )
    )
    factions = [
        picked if picked in FACTIONS else ordered_faction(ordered or [])
        for picked, ordered in found.select("faction_picked", "ordered").iter_rows()
    ]
    found = found.with_columns(pl.Series("faction", factions, dtype=pl.String))
    return orders, found.select([pl.col(name).cast(dtype) for name, dtype in PLAYER_SCHEMA.items()])


def extract_game(
    replay: Replay,
    match_id: int,
    map_list: Mapping[str, MapMetadata] | None = None,
    seconds: int = OPENING_SECONDS,
    cutoff: str = UNTIL_CONTACT,
    measured: Mapping[int, int | None] | None = None,
    position_cutoffs: Mapping[str, Mapping[str, int]] | None = None,
) -> GameExtract:
    """The game record, and for a game that is used its players and opening orders.

    For one parsed replay with its events, through the steps of `build_dataset`:
    `game_and_players`, then `player_openings` on the replay's rows of the commands table.
    """
    extract = game_and_players(
        replay, match_id, map_list, seconds, cutoff, measured, position_cutoffs
    )
    if not extract.players:
        return extract
    commands = tables.replay_tables(replay, "replay")[tables.COMMANDS].lazy()
    players = pl.from_dicts(extract.players, schema=PLAYER_INPUT_SCHEMA)
    players = players.with_columns(replay=pl.lit("replay"))
    extract.orders, found = player_openings(commands, players, seconds)
    extract.players = found.to_dicts()
    return extract


def ordered_faction(units: Iterable[str]) -> str | None:
    """The faction whose units a player ordered most: for players who picked Random."""
    prefixes = Counter(unit[:3] for unit in units if unit[:3] in FACTION_NAMES)
    return FACTION_NAMES[prefixes.most_common(1)[0][0]] if prefixes else None


def removed_units(units: Iterable[str], reference: Iterable[str]) -> list[str]:
    """The units that are not among the reference unit names.

    The reference is the unit names of the newest game in the dataset that has the same
    factions loaded as the opening's game (ADR 0015).
    """
    known = set(reference)
    return sorted(unit for unit in set(units) if unit not in known)


def slice_selection() -> pl.DataFrame:
    """The games of the slice over the pinned window, with their replay file names."""
    return matches.select_matches(
        matches.scan_dump("matches"),
        matches.scan_dump("match_players"),
        since=SLICE_SINCE,
        until=SLICE_UNTIL,
    )


def _code_version() -> dict[str, Any]:
    def git(*arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=REPO_ROOT, capture_output=True, text=True, check=True
            )
        except OSError, subprocess.CalledProcessError:
            return None
        return result.stdout.strip()

    status = git("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def _frame(records: Sequence[Mapping[str, Any]], schema: Mapping[str, Any]) -> pl.DataFrame:
    return pl.from_dicts(list(records), schema=dict(schema))


GAME_SCHEMA = {
    "match_id": pl.Int64,
    "split": pl.String,
    "status": pl.String,
    "map": pl.String,
    "team_count": pl.Int32,
    "team_size": pl.Int32,
    "game_version": pl.String,
    "build": pl.Int32,
    "opening_era": pl.Int32,
    "opening_era_name": pl.String,
    "balance_options": pl.String,
    "factions": pl.String,
    "positions_source": pl.String,
    "positions_shown": pl.Boolean,
    "default_boxes": pl.Boolean,
    "parser": pl.String,
    "contact_measured": pl.Boolean,
    "unit_control_widgets": pl.Boolean,  # the lobby lets user widgets give orders
    "error": pl.String,
}
# The players as `game_and_players` makes them; `player_openings` adds the other columns.
PLAYER_INPUT_SCHEMA = {
    "match_id": pl.Int64,
    "player_slot": pl.Int32,
    "user_id": pl.Int64,
    "ally_team": pl.Int32,
    "faction_picked": pl.String,
    "start_x": pl.Float32,
    "start_z": pl.Float32,
    "position": pl.String,
    "role": pl.String,
    "position_side": pl.Int32,
    "position_index": pl.Int32,
    "position_distance": pl.Float32,
    "on_spot": pl.Boolean,
    "won": pl.Boolean,
    "cutoff_frame": pl.Int32,
    "cutoff_source": pl.String,
}
PLAYER_SCHEMA = {
    "match_id": pl.Int64,
    "player_slot": pl.Int32,
    "user_id": pl.Int64,
    "ally_team": pl.Int32,
    "faction": pl.String,
    "faction_picked": pl.String,
    "start_x": pl.Float32,
    "start_z": pl.Float32,
    "position": pl.String,
    "role": pl.String,
    "position_side": pl.Int32,
    "position_index": pl.Int32,
    "position_distance": pl.Float32,
    "on_spot": pl.Boolean,
    "won": pl.Boolean,
    "cutoff_frame": pl.Int32,  # the last frame of the opening
    "cutoff_source": pl.String,  # reason8.openings.contact: measured, position or window
    "orders_in_window": pl.Int32,  # build orders of the whole opening window
    "orders": pl.Int32,
    "added": pl.Int32,
    "units": pl.List(pl.String),
}
# Columns of the game and the player repeated on every order row, after the order's own.
GAME_COLUMNS_ON_ROWS = (
    "map",
    "team_size",
    "start_time",
    "game_version",
    "build",
    "opening_era",
    "balance_options",
    "positions_shown",
    "default_boxes",
)
PLAYER_COLUMNS_ON_ROWS = (
    "ally_team",
    "faction",
    "start_x",
    "start_z",
    "position",
    "role",
    "position_index",
    "on_spot",
    "won",
    "skill",
    "cutoff_frame",
    "cutoff_source",
)


def build_dataset(
    parsed_dir: Path,
    out_dir: Path,
    selection: pl.DataFrame,
    match_players: pl.LazyFrame | pl.DataFrame,
    *,
    tables_dir: Path | None = None,
    map_list: Mapping[str, MapMetadata] | None = None,
    seconds: int = OPENING_SECONDS,
    cutoff: str = UNTIL_CONTACT,
    measured: Mapping[str, Mapping[int, int | None]] | None = None,
    position_cutoffs: Mapping[str, Mapping[str, int]] | None = None,
    since: date | None = None,
    until: date | None = None,
    widgets_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the dataset from the parsed replays of `selection` and return its manifest.

    `selection` has a row per game (``match_id``, ``replay_file_name``, ``start_time``,
    ``avg_skill``), as `select_matches()` returns it; games whose replay is not parsed
    are skipped. `match_players` gives each player's skill before the game. `seconds` is
    the opening window and `cutoff` says whether openings end at first contact: `measured`
    is the first contacts of the re-simulated games (`contact.load_measured()`), and
    `position_cutoffs` the cutoffs of the others (`contact.POSITION_CUTOFF_SECONDS`).
    `since` (inclusive) and `until` (exclusive) keep only the games in the date partitions of
    those days. `widgets_dir` holds the players' user widgets (`reason8.replays.widgets`);
    without it, or for a replay it has not read, the widget columns are empty.
    """
    if cutoff not in CUTOFFS:
        raise ValueError(f"cutoff must be one of {CUTOFFS}, not {cutoff!r}")
    until_contact = cutoff == UNTIL_CONTACT
    measured = measured if until_contact and measured is not None else {}
    if position_cutoffs is None:
        position_cutoffs = contact.POSITION_CUTOFF_SECONDS
    map_list = load_map_list() if map_list is None else map_list
    if since is not None or until is not None:
        selection = selection.filter(
            pl.col("replay_file_name").map_elements(
                lambda name: partition_in_range(partition(name), since, until),
                return_dtype=pl.Boolean,
            )
        )
    names = {
        int(match_id): Path(file_name).stem
        for match_id, file_name in selection.select("match_id", "replay_file_name").iter_rows()
    }
    source = tables.open_source(
        parsed_dir,
        parsed_dir.parent / tables.AREA if tables_dir is None else tables_dir,
        since=since,
        until=until,
        replays=names.values(),
        tables=(tables.GAMES, tables.PLAYERS, tables.COMMANDS),
    )
    stored_games = source.scan(tables.GAMES).collect()
    headers = tables.replay_headers(stored_games, source.scan(tables.PLAYERS).collect())
    tasks = sorted(
        (match_id, name)
        for match_id, name in names.items()
        if name in headers or name in source.unreadable
    )

    work_dir = out_dir.with_name(out_dir.name + ".building")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    (work_dir / "parts").mkdir(parents=True)
    games: list[dict[str, Any]] = []
    player_parts: list[pl.DataFrame] = []
    part_files: list[Path] = []
    for start in range(0, len(tasks), _GAMES_PER_PART):
        players: list[dict[str, Any]] = []
        for match_id, name in tasks[start : start + _GAMES_PER_PART]:
            if name in source.unreadable:
                error = source.unreadable[name]
                games.append(
                    {
                        "match_id": match_id,
                        "split": split_of(match_id),
                        "status": UNREADABLE,
                        "error": error,
                    }
                )
                continue
            extract = game_and_players(
                headers[name],
                match_id,
                map_list,
                seconds,
                cutoff,
                measured.get(name),
                position_cutoffs,
            )
            games.append(extract.game)
            players += [player | {"replay": name} for player in extract.players]
        if players:
            frame = pl.from_dicts(players, schema=PLAYER_INPUT_SCHEMA | {"replay": pl.String})
            replays = frame["replay"].unique().to_list()
            orders, found = player_openings(source.scan(tables.COMMANDS, replays), frame, seconds)
            player_parts.append(found)
            if not orders.is_empty():
                part_files.append(work_dir / "parts" / f"part-{len(part_files):05d}.parquet")
                orders.write_parquet(part_files[-1])
        done = min(start + _GAMES_PER_PART, len(tasks))
        if done % 500 < _GAMES_PER_PART or done == len(tasks):
            print(f"{done} of {len(tasks)} replays read", file=sys.stderr)

    game_frame = _frame(games, GAME_SCHEMA).join(
        selection.select(
            pl.col("match_id").cast(pl.Int64),
            "replay_file_name",
            "start_time",
            "game_duration",
            "avg_skill",
        ),
        on="match_id",
        how="left",
    )
    included = game_frame.filter(pl.col("status") == INCLUDED)

    # The vocabulary is the unit names of the newest build in the dataset (ADR 0015), taken
    # from a game with the same factions loaded: a game with Legion has 244 more names.
    unit_names = dict(stored_games.select("replay", "unitdefs").iter_rows())
    references: dict[str, dict[str, Any]] = {}
    for factions in sorted(included["factions"].unique().to_list()):
        newest = included.filter(pl.col("factions") == factions).sort("build", "match_id").tail(1)
        unit_definitions = unit_names[Path(newest["replay_file_name"].item()).stem]
        references[factions] = {
            "build": newest["build"].item(),
            "match_id": newest["match_id"].item(),
            "units": sorted(name for name in unit_definitions if name),
        }
    game_factions = dict(included.select("match_id", "factions").iter_rows())

    skills = (
        match_players.lazy()
        .select(
            pl.col("match_id").cast(pl.Int64),
            pl.col("user_id").cast(pl.Int64),
            pl.col("old_skill").cast(pl.Float32).alias("skill"),
            pl.col("old_uncertainty").cast(pl.Float32).alias("skill_uncertainty"),
        )
        .join(included.lazy().select("match_id"), on="match_id")
        .collect()
    )
    player_frame = (
        (pl.concat(player_parts) if player_parts else pl.DataFrame(schema=PLAYER_SCHEMA))
        .join(skills, on=["match_id", "user_id"], how="left")
        .drop("user_id")
        .with_columns(
            pl.struct("match_id", "units")
            .map_elements(
                lambda opening: removed_units(
                    opening["units"], references[game_factions[opening["match_id"]]]["units"]
                ),
                return_dtype=pl.List(pl.String),
            )
            .alias("removed_units")
        )
        .with_columns(
            pl.when(pl.col("removed_units").list.len() > 0)
            .then(pl.lit(REMOVED_UNIT))
            .otherwise(pl.lit(INCLUDED))
            .alias("status")
        )
        .join(included.select("match_id", "split"), on="match_id")
        .sort("match_id", "player_slot")
    )
    player_frame = _with_widgets(
        player_frame, included.select("match_id", "replay_file_name"), widgets_dir
    )

    kept_players = player_frame.filter(pl.col("status") == INCLUDED)
    rows = pl.scan_parquet(part_files) if part_files else pl.LazyFrame(schema=ORDER_COLUMNS)
    rows = (
        rows.join(
            kept_players.lazy().select("match_id", "player_slot", "split", *PLAYER_COLUMNS_ON_ROWS),
            on=["match_id", "player_slot"],
            maintain_order="left",
        )
        .join(
            included.lazy().select("match_id", *GAME_COLUMNS_ON_ROWS),
            on="match_id",
            maintain_order="left",
        )
        .select(
            "match_id",
            "player_slot",
            *GAME_COLUMNS_ON_ROWS,
            *PLAYER_COLUMNS_ON_ROWS,
            *[name for name in ORDER_COLUMNS if name not in ("match_id", "player_slot")],
            "split",
        )
    )
    row_counts = {}
    for split, _ in SPLITS:
        target = work_dir / f"{split}.parquet"
        rows.filter(pl.col("split") == split).drop("split").sink_parquet(target)
        row_counts[split] = pl.scan_parquet(target).select(pl.len()).collect().item()

    (work_dir / "splits").mkdir()
    for split, _ in SPLITS:
        match_ids = included.filter(pl.col("split") == split)["match_id"].sort().to_list()
        (work_dir / "splits" / f"{split}.txt").write_text(
            "".join(f"{match_id}\n" for match_id in match_ids)
        )
    game_frame.sort("match_id").write_parquet(work_dir / "games.parquet")
    player_frame.drop("units").write_parquet(work_dir / "openings.parquet")

    manifest = {
        "format": FORMAT,
        "name": out_dir.name,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": _code_version(),
        "opening": {
            "definition": "docs/decisions/0012-end-openings-at-first-contact.md",
            "window_seconds": seconds,
            "cutoff": cutoff,
            "contact": contact.MEASURES[contact.CONTACT] if until_contact else None,
            "measured_games": int(included["contact_measured"].sum()),
            "position_cutoff_quantile": contact.CUTOFF_QUANTILE if until_contact else None,
            "position_cutoff_seconds": position_cutoffs if until_contact else None,
        },
        "selection": {
            "since": max(SLICE_SINCE.date(), since or date.min).isoformat(),
            "until": min(SLICE_UNTIL.date(), until or date.max).isoformat(),
            "maps": sorted(selection["map"].unique().to_list()) if "map" in selection else None,
            "games": selection.height,
            "parsed": len(tasks),
        },
        "split": {
            "rule": f'sha256("{SPLIT_SALT}/<match_id>"), first 8 bytes big-endian, mod 100',
            "percent": dict(SPLITS),
        },
        "map_list_commit": MAP_LIST_COMMIT,
        "vocabulary": {
            factions: {
                "build": reference["build"],
                "match_id": reference["match_id"],
                "unit_names": len(reference["units"]),
            }
            for factions, reference in references.items()
        },
        "builds": {"first": included["build"].min(), "last": included["build"].max()},
        "parsers": sorted(parser for parser in included["parser"].unique().to_list() if parser),
        "counts": {
            "games_by_status": dict(Counter(game_frame["status"].to_list()).most_common()),
            "openings_by_status": dict(Counter(player_frame["status"].to_list()).most_common()),
            "openings_by_cutoff_source": dict(
                Counter(kept_players["cutoff_source"].to_list()).most_common()
            ),
            "openings_with_widget_reports": int(kept_players["widgets_reported"].sum()),
            "openings_with_automation_widgets": int(
                (kept_players["automation_widgets"].list.len() > 0).sum()
            ),
            "games": _counts_by_split(included),
            "openings": _counts_by_split(kept_players),
            "rows": row_counts,
        },
    }
    (work_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (work_dir / "README.md").write_text(_readme(manifest))

    shutil.rmtree(work_dir / "parts")
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(work_dir.rglob("*")):
        if path.is_file():
            target = out_dir / path.relative_to(work_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
    shutil.rmtree(work_dir)
    return manifest


def _with_widgets(
    player_frame: pl.DataFrame, replay_files: pl.DataFrame, widgets_dir: Path | None
) -> pl.DataFrame:
    """The openings with the player's user widgets (`reason8.replays.widgets`).

    `widgets_reported` says whether the player sent a widget report: players without user
    widgets send none. `widgets` are the user widgets that were enabled and
    `automation_widgets` those of them that give build orders. All three are empty when the
    replay's widgets were not read.
    """
    replays = pl.DataFrame(schema={"replay_file_name": pl.String})
    per_player = widgets.player_widgets(pl.DataFrame(schema=widgets.REPORT_SCHEMA))
    if widgets_dir is not None and (widgets_dir / widgets.REPLAYS_FILE).exists():
        replays = (
            pl.read_parquet(widgets_dir / widgets.REPLAYS_FILE)
            .filter(pl.col("error").is_null())
            .select("replay_file_name")
        )
        per_player = widgets.player_widgets(pl.read_parquet(widgets_dir / widgets.REPORTS_FILE))
    read = replay_files.join(replays, on="replay_file_name", how="semi")
    return (
        player_frame.join(replay_files, on="match_id", how="left")
        .join(
            per_player.rename({"team_id": "player_slot"}),
            on=["replay_file_name", "player_slot"],
            how="left",
        )
        .with_columns(
            pl.col("match_id").is_in(read["match_id"].implode()).alias("_read"),
        )
        .with_columns(
            pl.when("_read").then(pl.col("widgets").is_not_null()).alias("widgets_reported"),
            *[
                pl.when("_read").then(pl.col(name).fill_null([])).alias(name)
                for name in ("widgets", "automation_widgets")
            ],
        )
        .drop("replay_file_name", "_read")
    )


def _counts_by_split(frame: pl.DataFrame) -> dict[str, int]:
    counts = Counter(frame["split"].to_list())
    return {split: counts[split] for split, _ in SPLITS}


def _readme(manifest: Mapping[str, Any]) -> str:
    counts = manifest["counts"]
    lines = [
        f"# {manifest['name']}",
        "",
        "Opening build orders of the training slice, one row per build order.",
        "Built by `uv run reason8 dataset`; see",
        "docs/reference/openings-dataset.md and docs/decisions/0012 in the repository.",
        "",
        f"- openings end: {_cutoff_text(manifest['opening'])}",
        f"- built: {manifest['built_at']}, code {manifest['code']['commit']}"
        + (" (with uncommitted changes)" if manifest["code"]["dirty"] else ""),
        f"- slice games: {manifest['selection']['games']}, parsed: "
        f"{manifest['selection']['parsed']}",
        f"- games by status: {counts['games_by_status']}",
        f"- openings by status: {counts['openings_by_status']}",
        f"- openings by where their end comes from: {counts['openings_by_cutoff_source']}",
        "",
        "| split | games | openings | rows |",
        "| --- | --- | --- | --- |",
    ]
    for split, _ in SPLITS:
        lines.append(
            f"| {split} | {counts['games'][split]} | {counts['openings'][split]} "
            f"| {counts['rows'][split]} |"
        )
    return "\n".join(lines) + "\n"


def _cutoff_text(opening: Mapping[str, Any]) -> str:
    window = f"after {opening['window_seconds'] // 60} minutes"
    if opening["cutoff"] != UNTIL_CONTACT:
        return window
    return (
        f"at the player's first contact with the enemy, at the latest {window} "
        f"({opening['measured_games']} games with a measured contact)"
    )


def dataset_dir(name: str = NAME) -> Path:
    return data_dir() / "datasets" / name


# --- statistics for docs/reference/openings-dataset.md

FIRST_ORDERS = 6  # an opening, for the top-openings tables: its first six orders
TOP_OPENINGS = 20


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "-"


def _quantiles(values: Sequence[int]) -> tuple[int, int, int]:
    ordered = sorted(values)
    if not ordered:
        return 0, 0, 0

    def at(share: float) -> int:
        return ordered[min(len(ordered) - 1, math.floor(share * len(ordered)))]

    return at(0.1), at(0.5), at(0.9)


def load_sequences(out_dir: Path, splits: Sequence[str] | None = None) -> pl.DataFrame:
    """One row per opening: its columns and `units`, the units it added, in order."""
    names = [split for split, _ in SPLITS] if splits is None else list(splits)
    return (
        pl.concat(
            [
                pl.scan_parquet(out_dir / f"{split}.parquet").with_columns(split=pl.lit(split))
                for split in names
            ]
        )
        .filter(pl.col("seq_idx").is_not_null())
        .sort("match_id", "player_slot", "seq_idx")
        .group_by("match_id", "player_slot", maintain_order=True)
        .agg(
            pl.col("split", "map", "faction", "position", "role", "on_spot", "skill").first(),
            pl.col("opening_era", "build").first(),
            pl.col("unit").alias("units"),
            pl.col("repeat").alias("repeats"),
            pl.col("frame").alias("frames"),
        )
        .collect()
    )


def stats(out_dir: Path) -> str:
    """The tables of docs/reference/openings-dataset.md, from a built dataset."""
    manifest = json.loads((out_dir / "manifest.json").read_text())
    games = pl.read_parquet(out_dir / "games.parquet")
    players = pl.read_parquet(out_dir / "openings.parquet")
    sequences = load_sequences(out_dir)
    lines = [f"Built {manifest['built_at']} from code {manifest['code']['commit']}.", ""]

    lines += ["## Size", ""]
    included = games.filter(pl.col("status") == INCLUDED)
    kept = players.filter(pl.col("status") == INCLUDED)
    rows = []
    for map_name in sorted(included["map"].unique().to_list()):
        cells = [map_name]
        for split, _ in SPLITS:
            cells.append(
                included.filter(pl.col("map") == map_name, pl.col("split") == split).height
            )
        cells.append(kept.join(included.filter(pl.col("map") == map_name), on="match_id").height)
        rows.append(cells)
    lines += markdown.table(["map", *[f"{split} games" for split, _ in SPLITS], "openings"], rows)
    lines += ["", "Rows (build orders) per split:", ""]
    lines += markdown.table(
        ["split", "games", "openings", "rows"],
        [
            [split, manifest["counts"]["games"][split], manifest["counts"]["openings"][split]]
            + [manifest["counts"]["rows"][split]]
            for split, _ in SPLITS
        ],
    )
    lines += ["", "Games of the slice that were parsed, by status:", ""]
    lines += markdown.table(
        ["status", "games"], sorted(Counter(games["status"].to_list()).items(), key=str)
    )
    lines += ["", "Openings of the games used, by status:", ""]
    lines += markdown.table(
        ["status", "openings"], sorted(Counter(players["status"].to_list()).items(), key=str)
    )
    flags = kept.join(
        included.select("match_id", "positions_shown", "default_boxes"), on="match_id"
    )
    lines += [
        "",
        f"- starts on the spot: {flags['on_spot'].sum()} of {flags.height} "
        f"({_percent(flags['on_spot'].sum(), flags.height)})",
        f"- games that showed the recommended positions: {included['positions_shown'].sum()} "
        f"of {included.height}",
        "- start boxes: "
        + ", ".join(
            f"{label} {count}"
            for label, count in sorted(
                Counter(
                    {True: "default", False: "changed", None: "cannot tell"}[value]
                    for value in included["default_boxes"].to_list()
                ).items()
            )
        ),
        "- games with a balance-changing lobby option: "
        f"{included.filter(pl.col('balance_options') != '{}').height} of {included.height}",
    ]
    eras = Counter(
        (era_build or 0, era_name or "before the table")
        for era_build, era_name in included.select("opening_era", "opening_era_name").iter_rows()
    )
    lines += ["", "Games per opening era:", ""]
    lines += markdown.table(
        ["opening era", "first build", "games"],
        [[name, build or "-", count] for (build, name), count in sorted(eras.items())],
    )

    lines += ["", "## Vocabulary per faction", ""]
    rows = []
    for faction in FACTIONS:
        units = Counter(
            unit
            for sequence in sequences.filter(pl.col("faction") == faction)["units"].to_list()
            for unit in sequence
        )
        total = sum(units.values())
        covered, needed = 0, 0
        for _, count in units.most_common():
            if covered >= 0.99 * total:
                break
            covered += count
            needed += 1
        rows.append([faction, len(units), needed, total])
    lines += markdown.table(
        ["faction", "unit names ordered", "names for 99% of orders", "orders"], rows
    )

    lines += ["", "## Sequence lengths", ""]
    rows = []
    for map_name in sorted(sequences["map"].unique().to_list()):
        group = sequences.filter(pl.col("map") == map_name)
        lengths = [len(units) for units in group["units"].to_list()]
        steps = [sum(not repeat for repeat in repeats) for repeats in group["repeats"].to_list()]
        rows.append([map_name, group.height, *_quantiles(lengths), *_quantiles(steps)])
    lines += markdown.table(
        ["map", "openings", "orders p10", "median", "p90", "steps p10", "median", "p90"], rows
    )

    lines += ["", "## Where openings end", ""]
    opening = manifest["opening"]
    lines += [f"Openings end {_cutoff_text(opening)}.", ""]
    rows = []
    with_map = kept.join(included.select("match_id", "map"), on="match_id")
    for map_name in sorted(with_map["map"].unique().to_list()):
        group = with_map.filter(pl.col("map") == map_name)
        sources = Counter(group["cutoff_source"].to_list())
        rows.append(
            [map_name, group.height]
            + [sources[source] for source in (contact.MEASURED, contact.BY_POSITION)]
            + [sources[contact.WINDOW]]
            + [markdown.clock(frame) for frame in _quantiles(group["cutoff_frame"].to_list())]
            + [_percent(group["orders"].sum(), group["orders_in_window"].sum())]
        )
    lines += markdown.table(
        ["map", "openings", "measured contact", "by position", "whole window"]
        + ["end p10", "median", "p90", "orders of the window kept"],
        rows,
    )

    lines += ["", f"## Top {TOP_OPENINGS} openings (first {FIRST_ORDERS} orders)", ""]
    with_text = sequences.with_columns(
        pl.col("units")
        .map_elements(
            lambda units: " ".join(unit_role(unit) for unit in units[:FIRST_ORDERS]),
            return_dtype=pl.String,
        )
        .alias("opening"),
        pl.col("units")
        .map_elements(lambda units: first_factory(list(units)), return_dtype=pl.String)
        .alias("first_factory"),
    )
    counts = Counter(with_text["opening"].to_list())
    lines += markdown.table(
        ["opening", "openings", "share"],
        [
            [f"`{text or '(nothing)'}`", count, _percent(count, with_text.height)]
            for text, count in counts.most_common(TOP_OPENINGS)
        ],
    )

    lines += ["", "## Per map and position", ""]
    lines += [
        "Openings from a start on the spot only. Factions count every opening of the",
        "position.",
    ]
    position_frame = kept.join(included.select("match_id", "map"), on="match_id")
    on_spot = with_text.filter(pl.col("on_spot"))
    for map_name in sorted(position_frame["map"].unique().to_list()):
        lines += ["", f"### {map_name}", ""]
        rows = []
        here = position_frame.filter(pl.col("map") == map_name)
        for (position,), group in sorted(
            here.group_by("position"), key=lambda item: _position_key(map_name, item[0][0])
        ):
            factions = Counter(group["faction"].to_list())
            played = on_spot.filter(pl.col("map") == map_name, pl.col("position") == position)
            factory, factory_count = _most_common(played["first_factory"].to_list())
            opening, opening_count = _most_common(played["opening"].to_list())
            rows.append(
                [position or "none", group["role"][0] or "-", group.height, played.height]
                + [factions[faction] for faction in FACTIONS]
                + [factory, _percent(factory_count, played.height)]
                + [f"`{opening}`", _percent(opening_count, played.height)]
            )
        lines += markdown.table(
            ["position", "role", "openings", "on the spot", *FACTIONS]
            + ["first factory", "share", f"first {FIRST_ORDERS} orders", "share"],
            rows,
        )
    return "\n".join(lines)


def _most_common(values: Sequence[str]) -> tuple[str, int]:
    found = Counter(values).most_common(1)
    return found[0] if found else ("-", 0)


def _position_key(map_name: str | None, position: str | None) -> tuple[str, int, str]:
    number, name = position_order(position or "")
    return (map_name or "", number if position else 10**6, name)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    tables.add_source_arguments(parser)
    parser.add_argument("--out", type=Path, default=dataset_dir())
    parser.add_argument(
        "--cutoff",
        choices=CUTOFFS,
        default=UNTIL_CONTACT,
        help="where openings end: at first contact, or only with the opening window",
    )
    parser.add_argument(
        "--window-seconds", type=int, default=OPENING_SECONDS, help="the opening window"
    )
    parser.add_argument(
        "--contact",
        type=Path,
        default=contact.contact_dir() / contact.TABLE_NAME,
        help="first contacts of the re-simulated games (reason8 contact)",
    )
    parser.add_argument(
        "--widgets",
        type=Path,
        default=data_dir() / "widgets",
        help="the players' user widgets (reason8 widgets)",
    )
    parser.add_argument("--stats", action="store_true", help="print the tables of a built dataset")


def run(args: argparse.Namespace) -> int:
    if args.stats:
        print(stats(args.out))
        return 0
    if not load_map_list():
        print("no map list: run `reason8 maps fetch` first", file=sys.stderr)
        return 1
    require_partitioned(args.parsed, "*" + PARSED_SUFFIX)
    manifest = build_dataset(
        args.parsed,
        args.out,
        slice_selection(),
        matches.scan_dump("match_players"),
        tables_dir=args.tables,
        seconds=args.window_seconds,
        cutoff=args.cutoff,
        measured=contact.load_measured(args.contact),
        since=args.since,
        until=args.until,
        widgets_dir=args.widgets,
    )
    print(json.dumps(manifest["counts"], indent=2))
    return 0
