"""Build the opening dataset: one row per build order of every player's opening.

Usage::

    uv run python -m reason8.map_metadata              # once: the pinned map list
    uv run python -m reason8.opening_dataset           # parsed replays -> openings_v1/
    uv run python -m reason8.opening_dataset --stats   # the tables of docs/openings-dataset.md

The games are the training slice (`reason8.match_dumps.select_matches()` over the pinned
window of docs/dataset.md) whose replays are parsed in ``<data dir>/parsed/``. Building
again reads whatever is parsed by then and rewrites the dataset: the split of a game
depends only on its match id, so games never move between splits as more replays are
parsed.

What an opening is and how the games are split is ADR 0017; which games and openings are
left out follows ADR 0012 (balance patches) and ADR 0015 (positions). The output, in
``<data dir>/datasets/openings_v1/``:

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
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from reason8 import match_dumps
from reason8.game_versions import (
    balance_options,
    build_number,
    current_unit_name,
    loaded_factions,
    opening_era,
)
from reason8.map_metadata import COMMIT as MAP_LIST_COMMIT
from reason8.map_metadata import MapMetadata, load_map_list
from reason8.openings import (
    FACTION_PREFIXES,
    OPENING_SECONDS,
    first_factory,
    opening_orders,
    unit_role,
)
from reason8.parse import output_path
from reason8.positions import game_shape, position_order, replay_positions, start_setup
from reason8.replay import Replay, load_replay

NAME = "openings_v1"
FORMAT = "reason8.openings/1"
# The slice window of docs/dataset.md, pinned so the selection does not move with the dumps.
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
FACTIONS = ("Armada", "Cortex", "Legion")
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
    """What one replay gives the dataset: the game, its players and their orders."""

    game: dict[str, Any]
    players: list[dict[str, Any]] = field(default_factory=list)
    orders: dict[str, list[Any]] = field(default_factory=lambda: defaultdict(list))


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


def extract_game(
    replay: Replay,
    match_id: int,
    map_list: Mapping[str, MapMetadata] | None = None,
    seconds: int = OPENING_SECONDS,
) -> GameExtract:
    """The game record, and for a game that is used its players and opening orders."""
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
    }
    extract = GameExtract(game)
    if status is not None:
        return extract
    winners = set(replay.winning_ally_teams)
    positions = replay_positions(replay, map_list)
    users = {player["teamId"]: player.get("userId") for player in replay.players}
    orders_by_team = opening_orders(replay, seconds)
    for team in replay.teams().values():
        position = positions.get(team.team_id)
        orders = orders_by_team.get(team.team_id, [])
        units = [current_unit_name(order.unit) for order in orders]
        faction = team.faction if team.faction in FACTIONS else ordered_faction(units)
        extract.players.append(
            {
                "match_id": match_id,
                "player_slot": team.team_id,
                "user_id": users.get(team.team_id),
                "ally_team": team.ally_team_id,
                "faction": faction,
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
                "orders": len(orders),
                "added": sum(order.count > 0 for order in orders),
                "units": sorted(set(units)),
            }
        )
        added = 0
        previous = None
        columns = extract.orders
        for index, (order, unit) in enumerate(zip(orders, units, strict=True)):
            columns["match_id"].append(match_id)
            columns["player_slot"].append(team.team_id)
            columns["order_index"].append(index)
            columns["seq_idx"].append(added if order.count > 0 else None)
            added += order.count > 0
            columns["frame"].append(order.frame)
            columns["unit"].append(unit)
            columns["kind"].append(order.kind)
            columns["count"].append(order.count)
            columns["via"].append(order.via)
            columns["queued"].append(order.queued)
            columns["inserted"].append(order.inserted)
            columns["quota"].append(order.quota)
            columns["repeat"].append(
                previous is not None
                and (previous.frame, previous.unit) == (order.frame, order.unit)
            )
            columns["x"].append(order.x)
            columns["z"].append(order.z)
            previous = order
    return extract


_worker_map_list: Mapping[str, MapMetadata] | None = None


def _start_worker(map_list: Mapping[str, MapMetadata] | None) -> None:
    global _worker_map_list
    _worker_map_list = map_list


def _extract_file(task: tuple[str, int]) -> GameExtract:
    path, match_id = task
    try:
        replay = load_replay(path)
    except (OSError, ValueError) as error:
        return GameExtract(
            {
                "match_id": match_id,
                "split": split_of(match_id),
                "status": UNREADABLE,
                "error": str(error),
            }
        )
    return extract_game(replay, match_id, _worker_map_list)


def ordered_faction(units: Iterable[str]) -> str | None:
    """The faction whose units a player ordered most: for players who picked Random."""
    prefixes = Counter(unit[:3] for unit in units if unit[:3] in FACTION_NAMES)
    return FACTION_NAMES[prefixes.most_common(1)[0][0]] if prefixes else None


def removed_units(units: Iterable[str], reference: Iterable[str]) -> list[str]:
    """The units that are not among the reference unit names.

    The reference is the unit names of the newest game in the dataset that has the same
    factions loaded as the opening's game (ADR 0012).
    """
    known = set(reference)
    return sorted(unit for unit in set(units) if unit not in known)


def slice_selection() -> pl.DataFrame:
    """The games of the slice over the pinned window, with their replay file names."""
    return match_dumps.select_matches(
        match_dumps.scan_dump("matches"),
        match_dumps.scan_dump("match_players"),
        since=SLICE_SINCE,
        until=SLICE_UNTIL,
    )


def _code_version() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]

    def git(*arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=root, capture_output=True, text=True, check=True
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
    "error": pl.String,
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
)


def build_dataset(
    parsed_dir: Path,
    out_dir: Path,
    selection: pl.DataFrame,
    match_players: pl.LazyFrame | pl.DataFrame,
    *,
    jobs: int = 1,
    map_list: Mapping[str, MapMetadata] | None = None,
) -> dict[str, Any]:
    """Build the dataset from the parsed replays of `selection` and return its manifest.

    `selection` has a row per game (``match_id``, ``replay_file_name``, ``start_time``,
    ``avg_skill``), as `select_matches()` returns it; games whose replay is not parsed
    are skipped. `match_players` gives each player's skill before the game.
    """
    map_list = load_map_list() if map_list is None else map_list
    tasks = []
    for row in selection.select("match_id", "replay_file_name").iter_rows(named=True):
        path = output_path(parsed_dir, Path(row["replay_file_name"]))
        if path.exists():
            tasks.append((str(path), int(row["match_id"])))
    tasks.sort(key=lambda task: task[1])

    work_dir = out_dir.with_name(out_dir.name + ".building")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    (work_dir / "parts").mkdir(parents=True)
    games: list[dict[str, Any]] = []
    players: list[dict[str, Any]] = []
    part_orders: list[pl.DataFrame] = []
    part_files: list[Path] = []

    def flush() -> None:
        if part_orders:
            part = work_dir / "parts" / f"part-{len(part_files):05d}.parquet"
            pl.concat(part_orders).write_parquet(part)
            part_files.append(part)
            part_orders.clear()

    with ProcessPoolExecutor(
        max_workers=max(1, jobs), initializer=_start_worker, initargs=(map_list,)
    ) as pool:
        for count, extract in enumerate(pool.map(_extract_file, tasks, chunksize=8), start=1):
            games.append(extract.game)
            players += extract.players
            if extract.orders:
                part_orders.append(pl.DataFrame(dict(extract.orders), schema=ORDER_COLUMNS))
            if len(part_orders) >= _GAMES_PER_PART:
                flush()
            if count % 500 == 0:
                print(f"{count} of {len(tasks)} replays read", file=sys.stderr)
    flush()

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

    # The vocabulary is the unit names of the newest build in the dataset (ADR 0012), taken
    # from a game with the same factions loaded: a game with Legion has 244 more names.
    references: dict[str, dict[str, Any]] = {}
    for factions in sorted(included["factions"].unique().to_list()):
        newest = included.filter(pl.col("factions") == factions).sort("build", "match_id").tail(1)
        file_name = newest["replay_file_name"].item()
        unit_definitions = load_replay(output_path(parsed_dir, Path(file_name))).doc["unitdefs"]
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
        _frame(players, PLAYER_SCHEMA)
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
            "seconds": OPENING_SECONDS,
            "definition": "docs/adr/0017-define-openings-by-time-and-split-games-by-match-id.md",
        },
        "selection": {
            "since": SLICE_SINCE.date().isoformat(),
            "until": SLICE_UNTIL.date().isoformat(),
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


def _counts_by_split(frame: pl.DataFrame) -> dict[str, int]:
    counts = Counter(frame["split"].to_list())
    return {split: counts[split] for split, _ in SPLITS}


def _readme(manifest: Mapping[str, Any]) -> str:
    counts = manifest["counts"]
    lines = [
        f"# {manifest['name']}",
        "",
        "Opening build orders of the training slice, one row per build order.",
        "Built by `uv run python -m reason8.opening_dataset`; see",
        "docs/openings-dataset.md and docs/adr/0017 in the repository.",
        "",
        f"- built: {manifest['built_at']}, code {manifest['code']['commit']}"
        + (" (with uncommitted changes)" if manifest["code"]["dirty"] else ""),
        f"- slice games: {manifest['selection']['games']}, parsed: "
        f"{manifest['selection']['parsed']}",
        f"- games by status: {counts['games_by_status']}",
        f"- openings by status: {counts['openings_by_status']}",
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


def dataset_dir(name: str = NAME) -> Path:
    return match_dumps.data_dir() / "datasets" / name


# --- statistics for docs/openings-dataset.md

FIRST_ORDERS = 6  # an opening, for the top-openings tables: its first six orders
TOP_OPENINGS = 20


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


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
    """The tables of docs/openings-dataset.md, from a built dataset."""
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
    lines += _table(["map", *[f"{split} games" for split, _ in SPLITS], "openings"], rows)
    lines += ["", "Rows (build orders) per split:", ""]
    lines += _table(
        ["split", "games", "openings", "rows"],
        [
            [split, manifest["counts"]["games"][split], manifest["counts"]["openings"][split]]
            + [manifest["counts"]["rows"][split]]
            for split, _ in SPLITS
        ],
    )
    lines += ["", "Games of the slice that were parsed, by status:", ""]
    lines += _table(
        ["status", "games"], sorted(Counter(games["status"].to_list()).items(), key=str)
    )
    lines += ["", "Openings of the games used, by status:", ""]
    lines += _table(
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
    lines += _table(
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
    lines += _table(["faction", "unit names ordered", "names for 99% of orders", "orders"], rows)

    lines += ["", "## Sequence lengths", ""]
    rows = []
    for map_name in sorted(sequences["map"].unique().to_list()):
        group = sequences.filter(pl.col("map") == map_name)
        lengths = [len(units) for units in group["units"].to_list()]
        steps = [sum(not repeat for repeat in repeats) for repeats in group["repeats"].to_list()]
        rows.append([map_name, group.height, *_quantiles(lengths), *_quantiles(steps)])
    lines += _table(
        ["map", "openings", "orders p10", "median", "p90", "steps p10", "median", "p90"], rows
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
    lines += _table(
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
        lines += _table(
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


def main(argv: list[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    argument_parser.add_argument("--parsed", type=Path, default=match_dumps.data_dir() / "parsed")
    argument_parser.add_argument("--out", type=Path, default=dataset_dir())
    argument_parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    argument_parser.add_argument(
        "--stats", action="store_true", help="print the tables of a built dataset"
    )
    args = argument_parser.parse_args(argv)
    if args.stats:
        print(stats(args.out))
        return 0
    if not load_map_list():
        print("no map list: run `python -m reason8.map_metadata` first", file=sys.stderr)
        return 1
    manifest = build_dataset(
        args.parsed,
        args.out,
        slice_selection(),
        match_dumps.scan_dump("match_players"),
        jobs=args.jobs,
    )
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
