"""Build the decision table: every order of an opening given to builders, build orders
and jobs, with the builders that got it and the game state at its frame.

Usage::

    uv run reason8 context build        # the re-simulated games of the sample -> context_v2/
    uv run reason8 context build --out data/datasets/context_try --sample other.parquet

The build orders are the rows of the opening dataset (`reason8.openings.dataset`,
``openings_v2``) of the games of the context sample (``<data dir>/logs/context-sample.
parquet``) that have been re-simulated: the same orders and the same splits. The job
orders of builders (assist, reclaim, repair, resurrect) up to the end of each opening come
from the replay tables, and every order goes to the builders the command reached
(`reason8.context.builders`): one row per order and builder. Each row gets the state of
the player's team and of its allies as the game wrote it just before the order
(`state_frame`, the frame before the order's): what the bot can read for its own team and
its allies through the engine's AI interface (ADR 0007). Nothing about the enemy and
nothing about what anyone could see is used.

The state comes from the Parquet tables of the re-simulated games
(`reason8.headless.tables`, format 5: resources every second), and the joins are Polars
joins: resources by ``join_asof`` on the frame, units standing by summing the changes the
unit events make (`unit_changes`), the same units `reason8.headless.standing` rebuilds,
and build power the same way. Building again reads whatever games are re-simulated by
then and rewrites the table. docs/reference/context-dataset.md describes every column.

The output, in ``<data dir>/datasets/context_v2/``:

``train.parquet``, ``validation.parquet``, ``test.parquet``
    One row per order and builder (``decision_index``, ``builder_index``): the columns of
    the opening dataset, the answer, the builder, ``replay``, ``state_frame``,
    ``resources_frame`` and the context columns. Which orders start a step is not stored:
    the measurement numbers the steps when it loads the rows
    (`reason8.openings.dataset.step_index` with the answer), as the opening models do.
``builder_types.parquet``
    The unit types with build power of the game versions used: kind, build power, build
    list and jobs, from which the models' mask is made.
``games.parquet``
    One row per game of the sample, with why a game is not in the table yet.
``splits/<split>.txt``
    The match ids of each split.
``manifest.json``
    The sample, the source dataset, the context groups and their columns, the counts and
    the code version.

The context columns come in groups (`GROUPS`) that a model can switch on and off:
``time``, ``pace``, ``economy``, ``wind``, ``own_units`` and ``allies`` (the state, the
same for every builder of an order; `STATE_GROUPS`), ``builder`` (its kind, type,
whether it moves and its previous answer), ``build_power`` (the builder's, and the team's
finished and idle builders' by kind) and ``skill``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from reason8.context import builders
from reason8.headless import tables as state_tables
from reason8.headless.state import RESOURCE_LINES_FORMAT
from reason8.openings import dataset as openings
from reason8.openings.extract import unit_role
from reason8.paths import data_dir, partition
from reason8.replays import tables as replay_tables
from reason8.replays.replay import GAME_SPEED

NAME = "context_v2"
FORMAT = "reason8.context/2"
SOURCE_DATASET = openings.NAME

# Why a game of the sample is not in the table (games.parquet, column `status`).
INCLUDED = "ok"
NOT_SIMULATED = "not re-simulated yet"
OLD_FORMAT = "state before format 5"
SHORT_STATE = "state ends before the opening does"
NOT_IN_DATASET = "no openings in the opening dataset"
NOT_PARSED = "replay not in the replay tables"

RESOURCES = state_tables.RESOURCE_FIELDS  # metal, metal_storage, ... energy_expense
COMMANDER = "com"
OTHER = "other"
ROLE_COVERAGE = 0.99
GAMES_PER_CHUNK = 50

LIFE_KINDS = ("created", "finished", "destroyed", "given")
PLAYER = ["match_id", "player_slot"]


def unit_counts_columns(prefix: str, roles: Sequence[str]) -> list[str]:
    return [f"{prefix}_{state}_{role}" for role in roles for state in ("done", "building")]


def groups(roles: Sequence[str]) -> dict[str, list[str]]:
    """The context columns of each group, for the unit types `roles` (`OTHER` included)."""
    return {
        "time": ["time_s"],
        "pace": ["since_previous_s"],
        "economy": list(RESOURCES),
        "wind": ["wind", "wind_min", "wind_max"],
        "own_units": unit_counts_columns("own", roles),
        "allies": [f"allies_{name}" for name in RESOURCES] + unit_counts_columns("allies", roles),
        "builder": ["builder_kind", "builder_role", "builder_moves", "builder_previous"],
        "build_power": [
            "builder_build_power",
            "team_build_power",
            *builders.power_columns("team_build_power"),
            "idle_build_power",
            *builders.power_columns("idle_build_power"),
        ],
        "skill": ["skill"],
    }


#: The context columns that hold names, not numbers.
CATEGORICAL = ("builder_kind", "builder_role", "builder_previous")


GROUPS = tuple(groups([]))
#: The groups `join_state` adds: the state of the game, the same for every builder.
STATE_GROUPS = ("time", "pace", "economy", "wind", "own_units", "allies")


def sample_file() -> Path:
    return data_dir() / "logs" / "context-sample.parquet"


def state_dir() -> Path:
    return data_dir() / "state"


# --- the unit types


def unit_roles(units: Iterable[str], coverage: float = ROLE_COVERAGE) -> list[str]:
    """The unit types (names without faction prefix) that make up `coverage` of `units`,
    most frequent first, then the commander and `OTHER`."""
    counts = Counter(unit_role(unit) for unit in units)
    total = sum(counts.values())
    roles: list[str] = []
    covered = 0
    for role, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if covered >= coverage * total:
            break
        roles.append(role)
        covered += count
    return [role for role in roles if role not in (COMMANDER, OTHER)] + [COMMANDER, OTHER]


def role_expression(column: str, roles: Sequence[str]) -> pl.Expr:
    """The type of the units in `column` (unit names) as one of `roles`; `OTHER` for the rest."""
    prefix = pl.col(column).cast(pl.String).str.slice(0, 3)
    role = (
        pl.when(prefix.is_in(["arm", "cor", "leg"]))
        .then(pl.col(column).cast(pl.String).str.slice(3))
        .otherwise(pl.col(column).cast(pl.String))
    )
    return pl.when(role.is_in(list(roles))).then(role).otherwise(pl.lit(OTHER))


# --- what stands: the changes the unit events make


def unit_changes(events: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Every change to the units a team has: replay, frame, team, unit_def, finished, change.

    `events` is the ``events`` table of one or more games, in the order it was written.
    A unit counts for its team from its ``created`` line, as unfinished until its
    ``finished`` line, for the new team after ``given``, and no more after ``destroyed``.
    A unit id used again starts a new life. Summed up to a frame, the changes give the
    units `reason8.headless.standing.standing_units()` rebuilds for that frame.
    """
    unit = ["replay", "unit_id", "life"]
    kind = pl.col("kind")
    life = (
        events.lazy()
        .with_row_index("order")
        .with_columns(pl.col("replay").cast(pl.String), kind.cast(pl.String))
        .filter(kind.is_in(LIFE_KINDS))
        .with_columns(
            (kind == "created").cast(pl.Int32).cum_sum().over("replay", "unit_id").alias("life")
        )
        .filter(pl.col("life") > 0)
        .with_columns(
            pl.when(kind.is_in(["created", "given"]))
            .then(pl.col("team"))
            .forward_fill()
            .over(unit)
            .alias("owner"),
            ((kind == "finished").cast(pl.Int32).cum_sum().over(unit) > 0).alias("finished_now"),
            ((kind == "destroyed").cast(pl.Int32).cum_sum().over(unit) > 0).alias("gone"),
        )
        .with_columns(
            pl.col("owner").shift(1).over(unit).alias("owner_before"),
            pl.col("finished_now").shift(1).over(unit).fill_null(False).alias("finished_before"),
            pl.col("gone").shift(1).over(unit).fill_null(False).alias("gone_before"),
        )
        # nothing changes for a unit that is gone, or that is finished again
        .filter(~pl.col("gone_before"))
        .filter(~((kind == "finished") & pl.col("finished_before")))
    )
    columns = ["replay", "frame", "team", "unit_def", "finished", "change"]

    def change(condition: pl.Expr, team: str, finished: pl.Expr, amount: int) -> pl.LazyFrame:
        return life.filter(condition).select(
            "replay",
            "frame",
            pl.col(team).alias("team"),
            pl.col("unit_def").cast(pl.String),
            finished.alias("finished"),
            pl.lit(amount, dtype=pl.Int32).alias("change"),
        )

    return pl.concat(
        [
            change(kind == "created", "team", pl.lit(False), 1),
            change(kind == "finished", "owner_before", pl.lit(False), -1),
            change(kind == "finished", "owner_before", pl.lit(True), 1),
            change(kind == "given", "owner_before", pl.col("finished_before"), -1),
            change(kind == "given", "team", pl.col("finished_before"), 1),
            change(kind == "destroyed", "owner_before", pl.col("finished_before"), -1),
        ]
    ).select(
        pl.col("replay"),
        pl.col("frame").cast(pl.Int32),
        pl.col("team").cast(pl.Int32),
        *columns[3:],
    )


def running_counts(
    changes: pl.DataFrame, key: str, prefix: str, roles: Sequence[str]
) -> pl.DataFrame:
    """Units per `key` (team or ally team) after each frame with a change, as columns
    ``<prefix>_done_<role>`` and ``<prefix>_building_<role>``, one row per replay, key and
    frame."""
    names = unit_counts_columns(prefix, roles)
    if changes.is_empty():
        return pl.DataFrame(
            schema={"replay": pl.String, key: pl.Int32, "frame": pl.Int32}
            | dict.fromkeys(names, pl.Int32)
        )
    long = (
        changes.with_columns(
            pl.concat_str(
                pl.lit(prefix + "_"),
                pl.when("finished").then(pl.lit("done")).otherwise(pl.lit("building")),
                pl.lit("_"),
                role_expression("unit_def", roles),
            ).alias("column")
        )
        .group_by("replay", key, "frame", "column")
        .agg(pl.col("change").sum())
    )
    wide = long.pivot(on="column", index=["replay", key, "frame"], values="change")
    missing = [name for name in names if name not in wide.columns]
    return (
        wide.with_columns(pl.lit(0, dtype=pl.Int32).alias(name) for name in missing)
        .select("replay", key, "frame", *names)
        .sort("replay", key, "frame")
        .with_columns(pl.col(names).fill_null(0).cum_sum().over("replay", key).cast(pl.Int32))
    )


# --- the join


def with_times(orders: pl.DataFrame) -> pl.DataFrame:
    """Add ``state_frame``, ``time_s`` and ``since_previous_s`` (the time since the
    player's last build order in an earlier frame)."""
    # the player's last order in an earlier frame: the orders of one frame are given at once,
    # and an order in the frame of the step before it starts a new step only if its unit
    # differs, so the time since an order of the same frame would give the unit away
    previous = pl.col("frame").shift(1)
    earlier_frame = pl.when(pl.col("frame") != previous).then(previous).forward_fill().over(PLAYER)
    order = "decision_index" if "decision_index" in orders.columns else "order_index"
    return orders.sort(*PLAYER, order).with_columns(
        pl.max_horizontal(pl.col("frame") - 1, pl.lit(0)).cast(pl.Int32).alias("state_frame"),
        (pl.col("frame") / GAME_SPEED).cast(pl.Float32).alias("time_s"),
        ((pl.col("frame") - earlier_frame) / GAME_SPEED).cast(pl.Float32).alias("since_previous_s"),
    )


def join_state(
    orders: pl.DataFrame,
    games: pl.DataFrame,
    resources: pl.LazyFrame | pl.DataFrame,
    events: pl.LazyFrame | pl.DataFrame,
    roles: Sequence[str],
) -> pl.DataFrame:
    """The orders of some games with the state of their team and allies before each order.

    `orders` are rows of the opening dataset with ``replay`` (the state's name for the
    game), after `with_times`; `games` has a row per game of the state's ``game`` table
    (``replay``, ``wind_min``, ``wind_max``, ``teams``); `resources` and `events` are those
    tables of the same games. The state of an order is the one written at the end of
    ``state_frame``, the frame before the order's: the last resources line up to it (at
    most a second old; its frame is ``resources_frame``) and the units after its events.
    Returns the rows in the order of `orders` with the columns of `groups(roles)`.
    """
    teams = (
        games.select("replay", "teams")
        .explode("teams")
        .unnest("teams")
        .select("replay", pl.col("team").cast(pl.Int32), pl.col("ally_team").cast(pl.Int32))
    )
    decisions = (
        orders.with_row_index("_row")
        .with_columns(pl.col("player_slot").cast(pl.Int32).alias("team"))
        .join(teams.rename({"ally_team": "state_ally_team"}), on=["replay", "team"], how="left")
        .join(games.select("replay", "wind_min", "wind_max"), on="replay", how="left")
        .sort("state_frame")
    )

    resources = (
        resources.lazy()
        .select(
            pl.col("replay").cast(pl.String),
            pl.col("frame").cast(pl.Int32),
            pl.col("team").cast(pl.Int32),
            *[pl.col(name) for name in RESOURCES],
            "wind",
        )
        .collect()
    )
    own_resources = resources.rename({"frame": "resources_frame"}).sort("resources_frame")
    side_resources = (
        resources.join(teams, on=["replay", "team"])
        .group_by("replay", "ally_team", "frame")
        .agg(pl.col(name).sum().alias(f"side_{name}") for name in RESOURCES)
        .rename({"ally_team": "state_ally_team", "frame": "side_resources_frame"})
        .sort("side_resources_frame")
    )

    changes = unit_changes(events).collect()
    own_units = running_counts(changes, "team", "own", roles).rename({"frame": "units_frame"})
    side_changes = changes.join(teams, on=["replay", "team"]).drop("team")
    side_units = running_counts(side_changes, "ally_team", "side", roles).rename(
        {"ally_team": "state_ally_team", "frame": "side_units_frame"}
    )
    own_names = unit_counts_columns("own", roles)
    side_names = unit_counts_columns("side", roles)

    def asof(left: pl.DataFrame, right: pl.DataFrame, by: list[str], on: str) -> pl.DataFrame:
        return left.join_asof(
            right.sort(on),
            left_on="state_frame",
            right_on=on,
            by=by,
            strategy="backward",
            check_sortedness=False,
        )

    joined = asof(decisions, own_resources, ["replay", "team"], "resources_frame")
    joined = asof(joined, side_resources, ["replay", "state_ally_team"], "side_resources_frame")
    joined = asof(joined, own_units, ["replay", "team"], "units_frame")
    joined = asof(joined, side_units, ["replay", "state_ally_team"], "side_units_frame")
    joined = joined.with_columns(pl.col(own_names + side_names).fill_null(0))
    allies = [
        (pl.col(f"side_{name}") - pl.col(name)).alias(f"allies_{name}") for name in RESOURCES
    ] + [
        (pl.col(side) - pl.col(own)).cast(pl.Int32).alias(f"allies{own.removeprefix('own')}")
        for own, side in zip(own_names, side_names, strict=True)
    ]
    found = groups(roles)
    context = [name for group in STATE_GROUPS for name in found[group]]
    return (
        joined.with_columns(allies)
        .sort("_row")
        .select(
            *[name for name in orders.columns if name not in context],
            "resources_frame",
            *context,
        )
    )


# --- the build


def state_stem(directory: Path, replay: str) -> Path:
    return directory / partition(replay) / replay


def game_states(directory: Path, replays: Iterable[str]) -> pl.DataFrame:
    """The ``game`` row of each replay that has state tables, as far as needed here."""
    paths = [state_tables.table_path(state_stem(directory, replay), "game") for replay in replays]
    paths = [path for path in paths if path.is_file()]
    schema = {
        "replay": pl.String,
        "version": pl.Int16,
        "last_frame": pl.Int32,
        "complete": pl.Boolean,
        "end_reason": pl.String,
        "wind_min": pl.Float32,
        "wind_max": pl.Float32,
        "teams": state_tables.TABLE_SCHEMAS["game"]["teams"],
        "game": pl.String,
    }
    if not paths:
        return pl.DataFrame(schema=schema)
    return pl.concat(
        [pl.read_parquet(path, columns=list(schema)) for path in paths], how="vertical_relaxed"
    ).cast(schema)


def source_rows(source: Path, match_ids: Iterable[int]) -> pl.LazyFrame:
    """The rows of the opening dataset of these games, with their split."""
    wanted = pl.Series(sorted(set(match_ids)), dtype=pl.Int64).implode()
    return pl.concat(
        [
            pl.scan_parquet(source / f"{split}.parquet")
            .filter(pl.col("match_id").is_in(wanted))
            .with_columns(pl.lit(split).alias("split"))
            for split, _ in openings.SPLITS
        ]
    )


def as_of(
    rows: pl.DataFrame, sums: pl.DataFrame, names: Sequence[str], key: str = "team"
) -> pl.DataFrame:
    """`rows` (with ``replay``, ``team`` and ``state_frame``) with the running `sums`
    (`reason8.context.builders.running_sums`) as of their ``state_frame``; 0 before the
    first change."""
    return (
        rows.with_row_index("_row")
        .sort("state_frame")
        .join_asof(
            sums.rename({"frame": "_sums_frame"}).sort("_sums_frame"),
            left_on="state_frame",
            right_on="_sums_frame",
            by=["replay", key],
            strategy="backward",
            check_sortedness=False,
        )
        .sort("_row")
        .drop("_row", "_sums_frame")
        .with_columns(pl.col(list(names)).fill_null(0.0))
    )


def join_chunk(
    orders: pl.DataFrame,
    games: pl.DataFrame,
    commands: pl.DataFrame,
    resources: pl.LazyFrame | pl.DataFrame,
    events: pl.DataFrame,
    types: pl.DataFrame,
    roles: Sequence[str],
    counts: Counter[str] | None = None,
) -> pl.DataFrame:
    """The rows of the decision table of some games: their decisions (build orders and
    jobs), one row per builder, with the state before each.

    `orders` are rows of the opening dataset with ``replay``; `games` the state's ``game``
    rows of the same games (with ``game``, the version); `commands` their commands with
    ``targets`` (`reason8.context.builders.command_units`); `resources` and `events` the
    state's tables; `types` the builder types of the versions
    (`reason8.context.builders.builder_types`). `counts` gets the number of job orders
    left out because they reached no builder (``jobs_to_army_units_only``).
    """
    lives = builders.unit_lives(events).collect()
    decisions = builders.opening_decisions(orders, commands, lives)
    joined = join_state(with_times(decisions), games, resources, events, roles)
    rows = builders.order_builders(joined, lives, types, games)
    # a job that went to no builder is an order to army units: not a decision of a builder
    if counts is not None:
        counts["jobs_to_army_units_only"] += rows.filter(
            pl.col("kind") == builders.JOB_KIND, pl.col("builders") == 0
        ).height
    rows = rows.filter((pl.col("kind") != builders.JOB_KIND) | (pl.col("builders") > 0))
    rows = rows.with_columns(
        (pl.col("decision_index").rank("dense").over(PLAYER) - 1)
        .cast(pl.Int32)
        .alias("decision_index")
    )
    rows = builders.with_builder_history(rows)
    rows = rows.with_columns(pl.col("player_slot").cast(pl.Int32).alias("team"))

    team_power = builders.power_columns("team_build_power")
    idle_power = builders.power_columns("idle_build_power")
    changes = unit_changes(events).collect()
    rows = as_of(rows, builders.team_build_power(changes, types, games), team_power)
    transitions = builders.transitions_of(
        commands, events, builders.builder_unit_ids(lives, types, games)
    )
    rows = as_of(rows, builders.idle_build_power(transitions, lives, types, games), idle_power)
    return rows.with_columns(
        pl.sum_horizontal(team_power).alias("team_build_power"),
        pl.sum_horizontal(idle_power).alias("idle_build_power"),
        builders.builder_idle(rows, transitions),
    ).drop("team")


def build_table(
    out_dir: Path,
    sample: pl.DataFrame,
    *,
    source: Path,
    states: Path,
    tables: Path | None = None,
    content: Path | None = None,
    types: pl.DataFrame | None = None,
    sample_path: Path | None = None,
    log=lambda message: print(message, file=sys.stderr),
) -> dict[str, Any]:
    """Build the decision table of the re-simulated games of `sample`; return its manifest.

    `sample` has a row per game (``match_id``, ``replay_file_name``, ``map``, ``split``);
    `source` is the opening dataset whose rows are used, `states` the directory of the
    state tables, in date partitions, `tables` that of the replay tables (commands and
    selections) and `content` the game's content directory with the installed game
    versions, whose unit files say what each builder is (or `types`, the builder types
    already read, `reason8.context.builders.builder_types`).
    """
    tables = tables or replay_tables.tables_dir()
    content = content or data_dir() / "bar"
    sample = sample.with_columns(
        pl.col("match_id").cast(pl.Int64),
        pl.col("replay_file_name").str.replace(r"\.sdfz$", "").alias("replay"),
    )
    states_found = game_states(states, sample["replay"].to_list())
    in_dataset = (
        source_rows(source, sample["match_id"].to_list())
        .group_by("match_id")
        .agg(pl.col("frame").max().alias("last_order_frame"))
        .collect()
    )
    replay_source = replay_tables.open_source(
        tables,
        replays=states_found["replay"].to_list(),
        tables=(replay_tables.COMMANDS, replay_tables.SELECTIONS),
        log=log,
    )
    games = (
        sample.join(states_found, on="replay", how="left")
        .join(in_dataset, on="match_id", how="left")
        .with_columns(
            pl.when(pl.col("version").is_null())
            .then(pl.lit(NOT_SIMULATED))
            .when(pl.col("version") < RESOURCE_LINES_FORMAT)
            .then(pl.lit(OLD_FORMAT))
            .when(pl.col("last_order_frame").is_null())
            .then(pl.lit(NOT_IN_DATASET))
            .when(pl.col("last_frame") < pl.col("last_order_frame"))
            .then(pl.lit(SHORT_STATE))
            .when(~pl.col("replay").is_in(sorted(replay_source.stored)))
            .then(pl.lit(NOT_PARSED))
            .otherwise(pl.lit(INCLUDED))
            .alias("status")
        )
    )
    included = games.filter(pl.col("status") == INCLUDED).sort("match_id")

    source_manifest = json.loads((source / "manifest.json").read_text())
    roles = unit_roles(
        pl.scan_parquet(source / "train.parquet")
        .filter(pl.col("seq_idx").is_not_null())
        .select("unit")
        .collect()["unit"]
    )
    if types is None:
        types = builders.builder_types(included["game"].to_list(), content)

    work_dir = out_dir.with_name(out_dir.name + ".building")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    (work_dir / "parts").mkdir(parents=True)
    parts = []
    left_out: Counter[str] = Counter()
    replays = included["replay"].to_list()
    for start in range(0, len(replays), GAMES_PER_CHUNK):
        chunk = included.slice(start, GAMES_PER_CHUNK)
        names = chunk["replay"].to_list()
        stems = [state_stem(states, name) for name in names]
        orders = (
            source_rows(source, chunk["match_id"].to_list())
            .join(chunk.lazy().select("match_id", "replay"), on="match_id")
            .collect()
        )
        last_frame = builders.OPENING_SECONDS * GAME_SPEED
        commands = builders.command_units(
            replay_source.scan(replay_tables.COMMANDS, names)
            .filter(pl.col("frame").is_null() | (pl.col("frame") <= last_frame))
            .select(builders.COMMAND_COLUMNS),
            replay_source.scan(replay_tables.SELECTIONS, names).filter(
                pl.col("frame").is_null() | (pl.col("frame") <= last_frame)
            ),
        ).collect()
        # games of different formats have different event columns
        events = (
            state_tables.scan_files(
                [state_tables.table_path(stem, "events") for stem in stems], "events"
            )
            .with_columns(pl.col("replay").cast(pl.String))
            .collect()
        )
        joined = join_chunk(
            orders,
            chunk,
            commands,
            state_tables.scan_files(
                [state_tables.table_path(stem, "resources") for stem in stems], "resources"
            ),
            events,
            types,
            roles,
            left_out,
        )
        parts.append(work_dir / "parts" / f"part-{len(parts):05d}.parquet")
        joined.drop("seq").write_parquet(parts[-1])
        log(f"{min(start + GAMES_PER_CHUNK, len(replays))} of {len(replays)} games joined")

    rows = pl.scan_parquet(parts) if parts else None
    row_counts = {}
    for split, _ in openings.SPLITS:
        target = work_dir / f"{split}.parquet"
        if rows is None:
            pl.DataFrame().write_parquet(target)
            row_counts[split] = 0
            continue
        rows.filter(pl.col("split") == split).drop("split").sink_parquet(target)
        row_counts[split] = pl.scan_parquet(target).select(pl.len()).collect().item()

    (work_dir / "splits").mkdir()
    for split, _ in openings.SPLITS:
        match_ids = included.filter(pl.col("split") == split)["match_id"].sort().to_list()
        (work_dir / "splits" / f"{split}.txt").write_text(
            "".join(f"{match_id}\n" for match_id in match_ids)
        )
    games.select(
        "match_id", "replay_file_name", "map", "split", "status", "version", "last_frame", "game"
    ).sort("match_id").write_parquet(work_dir / "games.parquet")
    types.write_parquet(work_dir / "builder_types.parquet")

    counts = row_counts_of(parts)
    manifest = {
        "format": FORMAT,
        "name": out_dir.name,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": openings._code_version(),
        "source": {
            "dataset": source_manifest.get("name"),
            "built_at": source_manifest.get("built_at"),
            "code": source_manifest.get("code"),
        },
        "sample": {
            "file": str(sample_path) if sample_path else None,
            "sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest() if sample_path else None,
            "games": sample.height,
            "games_by_map": dict(sorted(Counter(sample["map"].to_list()).items())),
        },
        "split": source_manifest.get("split"),
        "state": {
            "format": f"at least {RESOURCE_LINES_FORMAT}",
            "frame": "the state written at the end of the frame before the order's",
        },
        "unit_roles": {
            "coverage": ROLE_COVERAGE,
            "of": f"the added orders of the train split of {source_manifest.get('name')}",
            "roles": list(roles),
        },
        "answers": {
            "jobs": list(builders.JOBS),
            "job_commands": list(builders.JOB_COMMANDS),
            "builder_kinds": list(builders.BUILDER_KINDS),
            "steps": "step_index(answer='answer', decides=answer is not null)",
        },
        "groups": groups(roles),
        "categorical": list(CATEGORICAL),
        "counts": {
            "games_by_status": dict(Counter(games["status"].to_list()).most_common()),
            "games": openings._counts_by_split(included),
            "games_by_map": dict(sorted(Counter(included["map"].to_list()).items())),
            "rows": row_counts,
            **counts,
            "jobs_to_army_units_only": left_out["jobs_to_army_units_only"],
        },
    }
    (work_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (work_dir / "README.md").write_text(_readme(manifest))
    shutil.rmtree(work_dir / "parts")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    os.replace(work_dir, out_dir)
    return manifest


DECISION = ["match_id", "player_slot", "decision_index"]


def row_counts_of(parts: Sequence[Path]) -> dict[str, Any]:
    """Openings, decisions, steps and builder rows of the parts of a build, by split."""
    if not parts:
        return {"openings": {}, "decisions": {}, "steps": 0, "decisions_by_kind": {}}
    rows = pl.scan_parquet(parts)
    first = rows.filter(pl.col("builder_index") == 0)
    openings_kept = rows.select(*PLAYER, "split").unique().collect()
    decisions = first.select("split", "kind").collect()
    steps = (
        first.sort(*PLAYER, "decision_index")
        .select(
            openings.step_starts(
                PLAYER, answer="answer", decides=pl.col("answer").is_not_null()
            ).sum()
        )
        .collect()
        .item()
    )
    by_builders = (
        first.group_by(pl.col("builders").clip(0, 3)).agg(pl.len()).sort("builders").collect()
    )
    return {
        "openings": openings._counts_by_split(openings_kept),
        "decisions": openings._counts_by_split(decisions),
        "decisions_by_kind": dict(Counter(decisions["kind"].to_list()).most_common()),
        "decisions_by_builders": {
            ("3 or more" if count == 3 else str(count)): number
            for count, number in by_builders.iter_rows()
        },
        "steps": steps,
    }


def _readme(manifest: Mapping[str, Any]) -> str:
    counts = manifest["counts"]
    lines = [
        f"# {manifest['name']}",
        "",
        "Opening build orders and builders' jobs of the re-simulated games of the context",
        "sample, one row per order and builder that got it, with the state of the player's",
        "team and allies before it. Built by",
        "`uv run reason8 context build`; see docs/reference/context-dataset.md in the",
        "repository.",
        "",
        f"- built: {manifest['built_at']}, code {manifest['code']['commit']}"
        + (" (with uncommitted changes)" if manifest["code"]["dirty"] else ""),
        f"- rows from: {manifest['source']['dataset']} built {manifest['source']['built_at']}",
        f"- games by status: {counts['games_by_status']}",
        "",
        "| split | games | openings | decisions | rows |",
        "| --- | --- | --- | --- | --- |",
    ]
    for split, _ in openings.SPLITS:
        lines.append(
            f"| {split} | {counts['games'][split]} | {counts['openings'].get(split, 0)} "
            f"| {counts['decisions'].get(split, 0)} | {counts['rows'][split]} |"
        )
    return "\n".join(lines) + "\n"


def dataset_dir(name: str = NAME) -> Path:
    return data_dir() / "datasets" / name


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, default=dataset_dir())
    parser.add_argument("--sample", type=Path, default=sample_file(), help="the games to use")
    parser.add_argument(
        "--source", type=Path, default=openings.dataset_dir(), help="the opening dataset"
    )
    parser.add_argument("--state-dir", type=Path, default=state_dir())
    parser.add_argument(
        "--tables", type=Path, default=None, help="the replay tables (default: <data dir>/tables)"
    )
    parser.add_argument(
        "--content",
        type=Path,
        default=None,
        help="the game's content directory with the game versions (default: <data dir>/bar)",
    )


def run(args: argparse.Namespace) -> int:
    manifest = build_table(
        args.out,
        pl.read_parquet(args.sample),
        source=args.source,
        states=args.state_dir,
        tables=args.tables,
        content=args.content,
        sample_path=args.sample,
    )
    print(json.dumps(manifest["counts"], indent=2))
    return 0
