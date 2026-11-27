"""The state of a game as Parquet tables, converted from the widget's JSON lines.

    uv run reason8 headless tables --state-dir data/state [--since D] [--until D]
    uv run reason8 headless tables STATE.jsonl.gz ...
    uv run reason8 headless tables --state-dir data/state --check

The widget can only write text, so it writes JSON lines and this module turns them into
tables after the run. A state file ``<name>.jsonl.gz`` gets its tables next to it, one file
per table, ``<name>.<table>.parquet``; in ``state/`` that is the date partition of the
replay (``state/date=2026-11-21/<name>.events.parquet``), in an evaluation game
``<game>/state.events.parquet``. The JSON lines stay: they are what the engine wrote, and
the tables can be made again from them when the layout changes, while making the JSON lines
again means playing the game again. A file is converted once; ``--force`` converts it again.

Every table has the replay's name in ``replay``. Events, hits and damage are in the order
of the game (by frame, and in a frame in the order the engine reported them); resources are
by team and frame, snapshot units by unit and frame, which compresses best. Unit types are
by name, not by the game version's numbers, and every table is zstd-compressed. Tables
(`TABLE_SCHEMAS` has the columns):

``game``
    one row: format, game version, map, engine, map size, wind range, how often resources
    and snapshots were written, the teams, the unit types (with the ones that cannot move
    marked ``static``), the last frame and how the game ended;
``resources``
    per team and resource line: metal and energy (stored, storage, income, expense) and the
    wind; every second from format 5, with every snapshot (5 s) before;
``events``
    units ``created`` (with the builder, and from format 6 the feature a resurrected unit
    came from), ``finished``, ``destroyed`` (whether it was finished, by which team; from
    format 6 also the attacking unit, the engine's weapon number and whether it was
    reclaimed), ``given`` (from which team) and ``idle``, with position;
``units``
    per snapshot, every unit that can move or is being built, with position, health and
    build progress; up to format 4 every unit (`reason8.headless.standing` rebuilds the
    rest from the events);
``hits``
    the first hit of a unit by each enemy team, with the attacker;
``damage``
    hits and damage per damaged team and attacking team, per second;
``features`` (from format 6)
    one row per reclaimable feature (wreck, heap, rock, tree): type, position, metal and
    energy when it appeared (frame 0: the map's own), the unit type it can be resurrected
    as, and when it went, with what it had left and how it went (reclaimed away,
    resurrected or destroyed);
``reclaim`` (from format 6)
    metal and energy a team took from a feature, per stretch of reclaiming it;
``work`` (from format 6)
    what a builder worked on, each time it changed: build (assist, when someone else
    started the unit), repair, reclaim, resurrect, capture, restore or none, and the unit
    or feature it worked on. Sampled every ``work_frames`` frames.

Games written before format 6 have no ``features``, ``reclaim`` and ``work`` files, and
their ``events`` lack the format 6 columns: `scan()` and `read_game()` give them empty
tables and empty columns.

`scan()` reads one table of many games as a lazy Polars frame; `read_records()` in
`reason8.headless.state` reads a game's tables as if they were its JSON lines.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path

import polars as pl

from reason8.headless.state import read_lines
from reason8.paths import find_files

STATE_SUFFIXES = (".jsonl.gz", ".jsonl")
TABLE_SUFFIX = ".parquet"
#: The name of the state file of an evaluation game (`reason8.evaluation.games`).
GAME_STATE_STEM = "state"

UNIT_EVENT_KINDS = ("created", "finished", "destroyed", "given", "idle")
WORK_TASKS = ("none", "build", "repair", "reclaim", "resurrect", "capture", "restore")
FEATURE_ENDS = ("reclaimed", "resurrected", "destroyed")
#: The format that added features, reclaim and builders' work.
FEATURES_FORMAT = 6
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 19  # 13% smaller than 9; a game takes 0.07 s to write

_TEAM = pl.Struct(
    {
        "team": pl.Int16,
        "ally_team": pl.Int16,
        "ai": pl.Boolean,
        "side": pl.String,
        "gaia": pl.Boolean,
    }
)
_UNIT_DEF = pl.Struct({"unit_def_id": pl.Int32, "name": pl.String, "static": pl.Boolean})
_FEATURE_DEF = pl.Struct(
    {
        "feature_def_id": pl.Int32,
        "name": pl.String,
        "metal": pl.Float32,
        "energy": pl.Float32,
        "reclaim_time": pl.Float32,
    }
)
_TEAM_RECLAIMED = pl.Struct({"team": pl.Int16, "metal": pl.Float32, "energy": pl.Float32})

TABLE_SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "game": {
        "replay": pl.String,
        "version": pl.Int16,  # the widget's FORMAT_VERSION
        "game": pl.String,
        "map": pl.String,
        "engine": pl.String,
        "map_x": pl.Int32,
        "map_z": pl.Int32,
        "from_replay": pl.Boolean,  # a replay played back, not a game played by AIs
        "snapshot_frames": pl.Int32,
        "resource_frames": pl.Int32,
        "wind_min": pl.Float32,
        "wind_max": pl.Float32,
        "tidal": pl.Float32,
        "teams": pl.List(_TEAM),
        "unit_defs": pl.List(_UNIT_DEF),  # static: empty up to format 4
        "work_frames": pl.Int32,  # how often builders' work was sampled (format 6)
        "builder_types": pl.List(pl.String),  # the unit types whose work was sampled
        "feature_defs": pl.List(_FEATURE_DEF),  # the feature types written (format 6)
        "last_frame": pl.Int32,  # the end line's frame, or the last frame written
        "complete": pl.Boolean,  # the end line is there
        "end_reason": pl.String,  # gameover, maxframe, shutdown
        "winners": pl.List(pl.Int16),  # ally teams
        "attackers": pl.String,  # how the widget told who hit whom
        "sampled": pl.String,  # frame_end (format 5) or frame_start
        # per team, metal and energy reclaimed as the game counts it (game versions from
        # late 2026 only)
        "game_reclaimed": pl.List(_TEAM_RECLAIMED),
    },
    "resources": {
        "replay": pl.Categorical,
        "frame": pl.Int32,
        "team": pl.Int16,
        "metal": pl.Int32,
        "metal_storage": pl.Int32,
        "metal_income": pl.Float32,
        "metal_expense": pl.Float32,
        "energy": pl.Int32,
        "energy_storage": pl.Int32,
        "energy_income": pl.Float32,
        "energy_expense": pl.Float32,
        "wind": pl.Float32,
    },
    "events": {
        "replay": pl.Categorical,
        "frame": pl.Int32,
        "kind": pl.Enum(UNIT_EVENT_KINDS),
        "unit_id": pl.Int32,
        "unit_def": pl.Categorical,
        "team": pl.Int16,
        "x": pl.Int32,
        "z": pl.Int32,
        "builder": pl.Int32,  # created: the unit that started it
        "from_team": pl.Int16,  # given
        "built": pl.Boolean,  # destroyed: it was finished
        "by_team": pl.Int16,  # destroyed: the attacker's team (-1: none)
        "attacker": pl.Int32,  # destroyed: the attacking unit (-1: none); format 6
        "weapon_def": pl.Int32,  # destroyed: the engine's weapon number (< 0: no weapon)
        "reclaimed": pl.Boolean,  # destroyed: reclaimed by the attacker, a builder
        "resurrected_from": pl.Int32,  # created: the feature it was resurrected from
    },
    "units": {
        "replay": pl.Categorical,
        "frame": pl.Int32,
        "unit_id": pl.Int32,
        "unit_def": pl.Categorical,
        "team": pl.Int16,
        "x": pl.Int32,
        "z": pl.Int32,
        "health_pct": pl.Int16,
        "build_pct": pl.Int16,
    },
    "hits": {
        "replay": pl.Categorical,
        "frame": pl.Int32,
        "unit_id": pl.Int32,
        "unit_def": pl.Categorical,
        "team": pl.Int16,
        "x": pl.Int32,
        "z": pl.Int32,
        "by": pl.Int32,
        "by_def": pl.Categorical,
        "by_team": pl.Int16,
        "damage": pl.Float32,
        "paralyzer": pl.Boolean,
    },
    "damage": {
        "replay": pl.Categorical,
        "frame": pl.Int32,
        "team": pl.Int16,
        "by_team": pl.Int16,
        "hits": pl.Int32,
        "damage": pl.Float32,
    },
    "features": {
        "replay": pl.Categorical,
        "feature_id": pl.Int32,
        "feature_def": pl.Categorical,
        "x": pl.Int32,
        "z": pl.Int32,
        "created_frame": pl.Int32,
        "metal": pl.Float32,
        "energy": pl.Float32,
        "resurrect_as": pl.Categorical,  # the unit type of a wreck
        "destroyed_frame": pl.Int32,  # null: still there at the end
        "metal_left": pl.Float32,
        "energy_left": pl.Float32,
        "reclaim_left": pl.Float32,  # 0: reclaimed away
        "end": pl.Enum(FEATURE_ENDS),  # how it went
    },
    "reclaim": {
        "replay": pl.Categorical,
        "frame": pl.Int32,
        "feature_id": pl.Int32,
        "team": pl.Int16,
        "from_frame": pl.Int32,
        "metal": pl.Float32,
        "energy": pl.Float32,
    },
    "work": {
        "replay": pl.Categorical,
        "frame": pl.Int32,
        "unit_id": pl.Int32,
        "team": pl.Int16,
        "task": pl.Enum(WORK_TASKS),
        "target_unit": pl.Int32,
        "target_feature": pl.Int32,
    },
}
TABLES = tuple(TABLE_SCHEMAS)
#: Written last, so that a game whose ``game`` table is there is converted completely.
LAST_TABLE = "game"
RESOURCE_FIELDS = tuple(TABLE_SCHEMAS["resources"])[3:11]
UNIT_FIELDS = ("unit_id", "unit_def", "team", "x", "z", "health_pct", "build_pct")


def state_stem(path: str | Path) -> Path:
    """The path a game's state files share: ``<dir>/<name>`` for ``<dir>/<name>.jsonl.gz``
    or any of its tables ``<dir>/<name>.<table>.parquet``."""
    path = Path(path)
    name = path.name
    for suffix in STATE_SUFFIXES:
        if name.endswith(suffix):
            return path.with_name(name.removesuffix(suffix))
    if name.endswith(TABLE_SUFFIX):
        stem, _, table = name.removesuffix(TABLE_SUFFIX).rpartition(".")
        if table in TABLE_SCHEMAS:
            return path.with_name(stem)
    raise ValueError(f"{path} is neither a state file nor a state table")


def table_path(path: str | Path, table: str) -> Path:
    """Where `table` of the game of `path` (a state file, a table or the stem) is kept."""
    if table not in TABLE_SCHEMAS:
        raise ValueError(f"no table {table!r}; the tables are {', '.join(TABLES)}")
    try:
        stem = state_stem(path)
    except ValueError:
        stem = Path(path)
    return stem.with_name(f"{stem.name}.{table}{TABLE_SUFFIX}")


def replay_name(path: str | Path) -> str:
    """The name in the ``replay`` column: the replay's name for ``state/``, and
    ``<run>/<game>`` for an evaluation game (whose file is ``state.jsonl.gz``)."""
    stem = state_stem(path)
    if stem.name == GAME_STATE_STEM:
        return f"{stem.parent.parent.name}/{stem.parent.name}"
    return stem.name


def converted(path: str | Path) -> bool:
    """Whether the tables of a state file are all there."""
    return table_path(path, LAST_TABLE).is_file()


# --- converting


def _game_row(
    header: dict, end: dict | None, last_frame: int, replay: str, feature_defs: list[dict]
) -> dict:
    static = set(header.get("static", ()))
    version = header.get("v", 1)
    unit_defs = header.get("unitdefs", {})
    return {
        "replay": replay,
        "version": version,
        "game": header.get("game"),
        "map": header.get("map"),
        "engine": header.get("engine"),
        "map_x": header.get("mapx"),
        "map_z": header.get("mapz"),
        "from_replay": header.get("replay"),
        "snapshot_frames": header.get("snapshot_frames"),
        "resource_frames": header.get("resource_frames", header.get("snapshot_frames")),
        "wind_min": header.get("wind_min"),
        "wind_max": header.get("wind_max"),
        "tidal": header.get("tidal"),
        "teams": [
            {
                "team": team["team"],
                "ally_team": team.get("ally"),
                "ai": team.get("ai"),
                "side": team.get("side"),
                "gaia": team.get("gaia"),
            }
            for team in header.get("teams", [])
        ],
        "unit_defs": [
            {
                "unit_def_id": int(unit_def_id),
                "name": name,
                "static": (int(unit_def_id) in static) if "static" in header else None,
            }
            for unit_def_id, name in sorted(
                header.get("unitdefs", {}).items(), key=lambda item: int(item[0])
            )
        ],
        "work_frames": header.get("work_frames"),
        "builder_types": [
            unit_defs[str(unit_def_id)]
            for unit_def_id in header["builders"]
            if str(unit_def_id) in unit_defs
        ]
        if "builders" in header
        else None,
        "feature_defs": feature_defs if version >= FEATURES_FORMAT else None,
        "last_frame": end["f"] if end else last_frame,
        "complete": end is not None,
        "end_reason": end.get("reason") if end else None,
        "winners": end.get("winners") if end else None,
        "attackers": end.get("attackers") if end else None,
        "sampled": end.get("sampled", "frame_start") if end else None,
        "game_reclaimed": [
            {"team": team, "metal": metal, "energy": energy}
            for team, metal, energy in end["game_reclaimed"]
        ]
        if end and "game_reclaimed" in end
        else None,
    }


def to_tables(records: Iterable[dict], replay: str) -> dict[str, pl.DataFrame]:
    """The tables of one game from the lines of its state file (`reason8.headless.state`)."""
    rows: dict[str, list[tuple]] = {table: [] for table in TABLES if table != "game"}
    header: dict = {}
    end: dict | None = None
    names: dict[str, str] = {}
    last_frame = 0
    resources: dict[int, list[tuple]] = {}
    units: dict[int, list[tuple]] = {}
    feature_defs: dict[int, dict] = {}
    features: list[list] = []  # one per feature, as in TABLE_SCHEMAS["features"]
    standing_features: dict[int, list] = {}  # feature id -> its row, while it is there
    resurrected: set[tuple[int, int]] = set()  # (feature id, frame its unit was made)

    def name(unit_def_id: int | None) -> str | None:
        return names.get(str(unit_def_id)) if unit_def_id is not None else None

    for record in records:
        kind = record["t"]
        frame = record.get("f")
        if frame is not None:
            last_frame = max(last_frame, frame)
        if kind == "header":
            header = record
            names = record.get("unitdefs", {})
        elif kind in UNIT_EVENT_KINDS:
            rows["events"].append(
                (
                    frame,
                    kind,
                    record["u"],
                    name(record.get("d")),
                    record.get("team"),
                    record.get("x"),
                    record.get("z"),
                    record.get("by") if kind == "created" else None,
                    record.get("from") if kind == "given" else None,
                    record.get("built") if kind == "destroyed" else None,
                    record.get("by_team") if kind == "destroyed" else None,
                    record.get("by") if kind == "destroyed" else None,
                    record.get("weapon") if kind == "destroyed" else None,
                    (record.get("reclaimed", False) if "by" in record else None)
                    if kind == "destroyed"
                    else None,
                    record.get("rez") if kind == "created" else None,
                )
            )
            if kind == "created" and "rez" in record:
                resurrected.add((record["rez"], frame))
        elif kind == "hit":
            rows["hits"].append(
                (
                    frame,
                    record["u"],
                    name(record.get("d")),
                    record.get("team"),
                    record.get("x"),
                    record.get("z"),
                    record.get("by"),
                    name(record.get("by_d")),
                    record.get("by_team"),
                    record.get("damage"),
                    record.get("paralyzer"),
                )
            )
        elif kind == "damage":
            rows["damage"].append(
                (frame, record["team"], record["by_team"], record["hits"], record["damage"])
            )
        elif kind == "fdef":
            feature_defs[record["d"]] = {
                "feature_def_id": record["d"],
                "name": record["name"],
                "metal": record["metal"],
                "energy": record["energy"],
                "reclaim_time": record["reclaim_time"],
            }
        elif kind == "fcreated":
            feature_def = feature_defs.get(record["d"])
            row = [
                record["id"],
                feature_def["name"] if feature_def else None,
                record["x"],
                record["z"],
                frame,
                record["metal"],
                record["energy"],
                name(record.get("rez")),
                None,
                None,
                None,
                None,
                None,
            ]
            features.append(row)
            standing_features[record["id"]] = row
        elif kind == "fdestroyed":
            row = standing_features.pop(record["id"], None)
            if row is not None:
                row[8:12] = [frame, record["metal"], record["energy"], record["reclaim_left"]]
        elif kind == "reclaim":
            rows["reclaim"].append(
                (
                    frame,
                    record["id"],
                    record["team"],
                    record["from"],
                    record["metal"],
                    record["energy"],
                )
            )
        elif kind == "work":
            rows["work"].append(
                (
                    frame,
                    record["u"],
                    record["team"],
                    record["task"],
                    record.get("unit"),
                    record.get("feature"),
                )
            )
        elif kind in ("r", "s"):
            # up to format 4 a run stopped at a snapshot frame wrote that snapshot twice:
            # the last one of a frame counts
            if "teams" in record:  # every "r" line, and the snapshots up to format 4
                wind = record.get("wind")
                resources[frame] = [(frame, *team, wind) for team in record["teams"]]
            if kind == "s":
                units[frame] = [
                    (frame, unit_id, name(unit_def_id), team, x, z, health, build)
                    for unit_id, unit_def_id, team, x, z, health, build in record["units"]
                ]
        elif kind == "end":
            end = record

    rows["resources"] = [row for frame_rows in resources.values() for row in frame_rows]
    rows["units"] = [row for frame_rows in units.values() for row in frame_rows]
    for row in features:
        row[12] = _feature_end(row, resurrected)
    rows["features"] = [tuple(row) for row in features]
    game_row = _game_row(header, end, last_frame, replay, list(feature_defs.values()))
    tables = {"game": pl.DataFrame([game_row], schema=TABLE_SCHEMAS["game"])}
    for table, table_rows in rows.items():
        schema = TABLE_SCHEMAS[table]
        columns = [column for column in schema if column != "replay"]
        frame = pl.DataFrame(table_rows, schema=columns, orient="row", infer_schema_length=None)
        tables[table] = frame
    # a unit's rows, and a team's, next to each other: they repeat each other's values, so
    # the units table compresses to three quarters of what it does by frame
    tables["resources"] = tables["resources"].sort("team", "frame", maintain_order=True)
    tables["units"] = tables["units"].sort("unit_id", "frame", maintain_order=True)
    tables["work"] = tables["work"].sort("unit_id", "frame", maintain_order=True)
    # events, hits, damage, features and reclaim stay in the order they were written: by
    # frame, and in a frame in the order the engine reported them
    return {
        table: frame.with_columns(pl.lit(replay).alias("replay")).select(
            [pl.col(column).cast(dtype) for column, dtype in TABLE_SCHEMAS[table].items()]
        )
        for table, frame in tables.items()
    }


def _feature_end(row: list, resurrected: set[tuple[int, int]]) -> str | None:
    """How a feature went: resurrected (a unit was made from it while it was there),
    reclaimed away, or destroyed otherwise (blown up, crushed, burnt); None while it is
    there."""
    feature_id, created_frame, destroyed_frame, reclaim_left = row[0], row[4], row[8], row[11]
    if destroyed_frame is None:
        return None
    if any(
        made == feature_id and created_frame <= frame <= destroyed_frame
        for made, frame in resurrected
    ):
        return "resurrected"
    if reclaim_left == 0:
        return "reclaimed"
    return "destroyed"


def write_tables(tables: dict[str, pl.DataFrame], stem: Path) -> dict[str, Path]:
    """Write the tables of a game next to its state file; the ``game`` table last."""
    paths = {}
    for table in sorted(tables, key=lambda table: table == LAST_TABLE):
        path = table_path(stem, table)
        partial = path.with_name(path.name + ".part")
        tables[table].write_parquet(
            partial, compression=COMPRESSION, compression_level=COMPRESSION_LEVEL, statistics=True
        )
        partial.rename(path)
        paths[table] = path
    return paths


def convert(path: str | Path, replay: str | None = None, force: bool = False) -> dict:
    """Convert a state file to tables next to it, unless that was done; what was done."""
    path = Path(path)
    if converted(path) and not force:
        return {"state_file": str(path), "skipped": True}
    tables = to_tables(read_lines(path, snapshots=True), replay or replay_name(path))
    paths = write_tables(tables, state_stem(path))
    return {
        "state_file": str(path),
        "rows": {table: frame.height for table, frame in tables.items()},
        "bytes": {table: path.stat().st_size for table, path in paths.items()},
        "state_bytes": path.stat().st_size,
    }


# --- reading


def scan(
    directory: str | Path, table: str, *, since: date | None = None, until: date | None = None
) -> pl.LazyFrame:
    """One table of every game in `directory`, lazily, in name order.

    With `since` (inclusive) and `until` (exclusive) only the games of the date partitions in
    that range (`reason8.paths.find_files`).
    """
    if table not in TABLE_SCHEMAS:
        raise ValueError(f"no table {table!r}; the tables are {', '.join(TABLES)}")
    paths = find_files(Path(directory), f"*.{table}{TABLE_SUFFIX}", since=since, until=until)
    return scan_files(paths, table)


def scan_files(paths: list[Path], table: str) -> pl.LazyFrame:
    """One table of the games of `paths` (that table's files), lazily, with every column of
    `TABLE_SCHEMAS`: the columns a game's format did not have yet are null."""
    if not paths:
        return pl.LazyFrame(schema=TABLE_SCHEMAS[table])
    return pl.scan_parquet(paths, schema=TABLE_SCHEMAS[table], missing_columns="insert")


def read_game(path: str | Path) -> dict[str, pl.DataFrame]:
    """Every table of one game (`path`: its state file, one of its tables or their stem).

    A table its format did not have is empty, and so are the columns it did not have."""
    game = {}
    for table in TABLES:
        file = table_path(path, table)
        game[table] = (
            scan_files([file], table).collect()
            if file.is_file()
            else pl.DataFrame(schema=TABLE_SCHEMAS[table])
        )
    return game


def read_table_records(path: str | Path, snapshots: bool = False) -> Iterator[dict]:
    """A game's tables as the lines of its state file would read (`read_lines`).

    Each frame gives its unit events, features (appeared, reclaim, went), hits, damage,
    resource line, snapshot and builders' work, in that order; floats come back rounded as
    the widget wrote them. Use
    `reason8.headless.state.read_records`, which makes snapshots whole as well.
    """
    tables = read_game(path)
    game = tables["game"].row(0, named=True)
    version = game["version"]
    ids = {unit_def["name"]: unit_def["unit_def_id"] for unit_def in game["unit_defs"]}
    header = {
        "t": "header",
        "v": version,
        "game": game["game"],
        "map": game["map"],
        "engine": game["engine"],
        "mapx": game["map_x"],
        "mapz": game["map_z"],
        "replay": game["from_replay"],
        "snapshot_frames": game["snapshot_frames"],
        "wind_min": _round(game["wind_min"], 1),
        "wind_max": _round(game["wind_max"], 1),
        "tidal": _round(game["tidal"], 1),
        "teams": [
            {
                "team": team["team"],
                "ally": team["ally_team"],
                "ai": team["ai"],
                "side": team["side"],
                "gaia": team["gaia"],
            }
            for team in game["teams"]
        ],
        "unitdefs": {
            str(unit_def["unit_def_id"]): unit_def["name"] for unit_def in game["unit_defs"]
        },
    }
    if version >= 5:
        header["resource_frames"] = game["resource_frames"]
        header["static"] = [
            unit_def["unit_def_id"] for unit_def in game["unit_defs"] if unit_def["static"]
        ]
    if version >= FEATURES_FORMAT:
        header["work_frames"] = game["work_frames"]
        header["builders"] = [ids[name] for name in game["builder_types"] or [] if name in ids]
    yield header

    def unit_def_id(name: str | None) -> int:
        return ids.get(name, -1) if name is not None else -1

    by_frame: dict[int, list[dict]] = {}
    for row in tables["events"].iter_rows(named=True):
        record = {
            "t": row["kind"],
            "f": row["frame"],
            "u": row["unit_id"],
            "d": unit_def_id(row["unit_def"]),
            "team": row["team"],
            "x": row["x"],
            "z": row["z"],
        }
        if row["kind"] == "created" and row["builder"] is not None:
            record["by"] = row["builder"]
            if row["resurrected_from"] is not None:
                record["rez"] = row["resurrected_from"]
        elif row["kind"] == "given":
            record["from"] = row["from_team"]
        elif row["kind"] == "destroyed":
            record["built"] = row["built"]
            record["by_team"] = row["by_team"]
            if row["attacker"] is not None:
                record["by"] = row["attacker"]
            if row["weapon_def"] is not None:
                record["weapon"] = row["weapon_def"]
            if row["reclaimed"]:
                record["reclaimed"] = True
        by_frame.setdefault(row["frame"], []).append(record)
    feature_lines(game, tables, ids, by_frame)
    for row in tables["hits"].iter_rows(named=True):
        by_frame.setdefault(row["frame"], []).append(
            {
                "t": "hit",
                "f": row["frame"],
                "u": row["unit_id"],
                "d": unit_def_id(row["unit_def"]),
                "team": row["team"],
                "x": row["x"],
                "z": row["z"],
                "by": row["by"],
                "by_d": unit_def_id(row["by_def"]),
                "by_team": row["by_team"],
                "damage": _round(row["damage"], 0),
                "paralyzer": row["paralyzer"],
            }
        )
    for row in tables["damage"].iter_rows(named=True):
        by_frame.setdefault(row["frame"], []).append(
            {
                "t": "damage",
                "f": row["frame"],
                "team": row["team"],
                "by_team": row["by_team"],
                "hits": row["hits"],
                "damage": _round(row["damage"], 0),
            }
        )
    work: dict[int, list[dict]] = {}
    for row in tables["work"].sort("frame", "unit_id", maintain_order=True).iter_rows(named=True):
        record = {
            "t": "work",
            "f": row["frame"],
            "u": row["unit_id"],
            "team": row["team"],
            "task": row["task"],
        }
        if row["target_unit"] is not None:
            record["unit"] = row["target_unit"]
        if row["target_feature"] is not None:
            record["feature"] = row["target_feature"]
        work.setdefault(row["frame"], []).append(record)
    if snapshots:
        resources: dict[int, list[list]] = {}
        wind: dict[int, float | None] = {}
        for row in tables["resources"].iter_rows(named=True):
            resources.setdefault(row["frame"], []).append(
                [row["team"]] + [_resource(row, field) for field in RESOURCE_FIELDS]
            )
            wind[row["frame"]] = _round(row["wind"], 2)
        units: dict[int, list[list]] = {}
        for row in tables["units"].iter_rows(named=True):
            units.setdefault(row["frame"], []).append(
                [
                    row["unit_id"],
                    unit_def_id(row["unit_def"]),
                    row["team"],
                    row["x"],
                    row["z"],
                    row["health_pct"],
                    row["build_pct"],
                ]
            )
        snapshot_frames = set(units)
        if version < 5:
            snapshot_frames |= set(resources)
        for frame in sorted(set(resources) | snapshot_frames):
            lines = by_frame.setdefault(frame, [])
            if version >= 5 and frame in resources:
                lines.append({"t": "r", "f": frame, "wind": wind[frame], "teams": resources[frame]})
            if frame in snapshot_frames:
                snapshot: dict = {"t": "s", "f": frame}
                if version < 5:
                    snapshot["wind"] = wind.get(frame)
                    snapshot["teams"] = resources.get(frame, [])
                snapshot["units"] = units.get(frame, [])
                lines.append(snapshot)
    for frame in work:
        by_frame.setdefault(frame, [])
    for frame in sorted(by_frame):
        yield from by_frame[frame]
        yield from work.get(frame, ())
    if game["complete"]:
        end = {
            "t": "end",
            "f": game["last_frame"],
            "reason": game["end_reason"],
            "winners": list(game["winners"] or []),
            "attackers": game["attackers"],
            **({"sampled": game["sampled"]} if version >= 5 else {}),
        }
        if game.get("game_reclaimed") is not None:
            end["game_reclaimed"] = [
                [team["team"], _round(team["metal"], 1), _round(team["energy"], 1)]
                for team in game["game_reclaimed"]
            ]
        yield end


def feature_lines(
    game: dict, tables: dict[str, pl.DataFrame], unit_def_ids: dict, by_frame: dict
) -> None:
    """Add a game's feature, reclaim and feature type lines to `by_frame` (frame -> lines),
    as the widget writes them: a feature type before the first feature of that type, and in
    a frame the features that appeared, then the reclaim, then the features that went."""
    feature_defs = {feature_def["name"]: feature_def for feature_def in game["feature_defs"] or []}
    written: set[str] = set()
    appeared: dict[int, list[dict]] = {}
    went: dict[int, list[dict]] = {}
    for row in tables["features"].iter_rows(named=True):
        lines = appeared.setdefault(row["created_frame"], [])
        feature_def = feature_defs.get(row["feature_def"], {})
        if row["feature_def"] not in written:
            written.add(row["feature_def"])
            lines.append(
                {
                    "t": "fdef",
                    "d": feature_def.get("feature_def_id"),
                    "name": row["feature_def"],
                    "metal": _round(feature_def.get("metal"), 0),
                    "energy": _round(feature_def.get("energy"), 0),
                    "reclaim_time": _round(feature_def.get("reclaim_time"), 0),
                }
            )
        record = {
            "t": "fcreated",
            "f": row["created_frame"],
            "id": row["feature_id"],
            "d": feature_def.get("feature_def_id"),
            "x": row["x"],
            "z": row["z"],
            "metal": _round(row["metal"], 1),
            "energy": _round(row["energy"], 1),
        }
        if row["resurrect_as"] is not None:
            record["rez"] = unit_def_ids.get(row["resurrect_as"], -1)
        lines.append(record)
        if row["destroyed_frame"] is not None:
            went.setdefault(row["destroyed_frame"], []).append(
                {
                    "t": "fdestroyed",
                    "f": row["destroyed_frame"],
                    "id": row["feature_id"],
                    "metal": _round(row["metal_left"], 1),
                    "energy": _round(row["energy_left"], 1),
                    "reclaim_left": _round(row["reclaim_left"], 3),
                }
            )
    reclaimed: dict[int, list[dict]] = {}
    for row in tables["reclaim"].iter_rows(named=True):
        reclaimed.setdefault(row["frame"], []).append(
            {
                "t": "reclaim",
                "f": row["frame"],
                "id": row["feature_id"],
                "team": row["team"],
                "from": row["from_frame"],
                "metal": _round(row["metal"], 1),
                "energy": _round(row["energy"], 1),
            }
        )
    for frame in sorted(set(appeared) | set(reclaimed) | set(went)):
        by_frame.setdefault(frame, []).extend(
            appeared.get(frame, []) + reclaimed.get(frame, []) + went.get(frame, [])
        )


def _round(value: float | None, digits: int) -> float | int | None:
    if value is None:
        return None
    rounded = round(value, digits)
    return int(rounded) if digits == 0 else rounded


_RESOURCE_DIGITS = {"metal_income": 1, "metal_expense": 1, "energy_income": 0, "energy_expense": 0}


def _resource(row: dict, field: str) -> float | int | None:
    digits = _RESOURCE_DIGITS.get(field)
    return row[field] if digits is None else _round(row[field], digits)


# --- the command


def state_files(paths: Iterable[Path]) -> list[Path]:
    """The state files among `paths`, and in the directories among them."""
    found = []
    for path in paths:
        if path.is_dir():
            found += [
                file
                for suffix in STATE_SUFFIXES
                for file in find_files(path, "*" + suffix)
                if suffix != ".jsonl" or not file.name.endswith(".jsonl.gz")
            ]
        else:
            found.append(path)
    return found


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="*", type=Path, help="state files or directories")
    parser.add_argument("--state-dir", type=Path, help="a directory of date partitions")
    parser.add_argument("--since", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--until", type=date.fromisoformat, help="day after the last")
    parser.add_argument("--force", action="store_true", help="convert again")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the state instead: the units rebuilt from the events against every "
        "snapshot, and the features, reclaim and builders' work",
    )


def check_file(path: str | Path) -> dict:
    """The checks of a state file, converted in memory (nothing is written): the units
    rebuilt from the events against the snapshots (`reason8.headless.standing`) and, from
    format 6, the features, reclaim and builders' work (`reason8.headless.features`)."""
    from reason8.headless import features, standing

    game_tables = to_tables(read_lines(path, snapshots=True), replay_name(path))
    result = {"state_file": str(path), **standing.check(game_tables)}
    feature_checks = features.check(game_tables)
    if feature_checks:
        result["features"] = feature_checks
    return result


def run(args: argparse.Namespace) -> int:
    paths = list(args.paths)
    if args.state_dir:
        paths += find_files(args.state_dir, "*.jsonl.gz", since=args.since, until=args.until)
    ok = True
    for path in state_files(paths):
        try:
            if args.check:
                result = check_file(path)
            else:
                result = convert(path, force=args.force)
        except (OSError, ValueError, pl.exceptions.PolarsError) as error:
            ok = False
            print(f"{path}: {error}", file=sys.stderr, flush=True)
            continue
        print(json.dumps(result), flush=True)
    return 0 if ok else 1
