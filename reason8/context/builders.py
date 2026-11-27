"""Who got each order: the builders of the decision table, their kind and their build power.

The decision table (`reason8.context.table`) gives every order of an opening to the units
it went to. A ``COMMAND`` packet goes to the player's current selection (the last
``select`` event of the player before it in the replay's stream), an ``AICOMMAND`` or
``AICOMMANDS`` packet to the units it lists, as in `reason8.analysis.apm`
(`command_units`). The re-simulated game says what each unit id is at the order's frame
(`unit_lives`), and the game version's unit files say what each unit type can do
(`builder_types`):

- its **kind**: ``commander``, ``factory``, ``construction`` (a mobile unit with a build
  list), ``tower`` (a structure with build power and no build list: construction turrets)
  or ``other`` (a mobile unit with build power and no build list: resurrection bots);
- whether it **moves**, and its **build power** (``workertime``);
- its **answers**: the units of its build list, and the jobs it can do
  (`JOBS`: ``assist``, ``reclaim``, ``repair``, ``resurrect``).

The builders of an order are the units it went to that can carry it out: a build order
goes to the units whose build list has the unit, a job to the units that can do the job.
The others in the selection ignore it, as the game does.

The unit files are read as written (`reason8.game.unitdefs`): what the game changes when it
loads them (``alldefs_post``) is not applied. Which jobs a unit can do follows the
engine's defaults for the ``can*`` fields: a builder can assist, reclaim and repair unless
its file says otherwise, only units that say so can resurrect, and factories do none of
them.

The idle state of a builder (`idle_transitions`) comes from the ``idle`` lines of the
state export (format 4 and later): a unit that runs out of orders writes one. It is idle
from that line until the next command it gets that gives it something to do
(`BUSY_COMMANDS`), or until it is destroyed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import polars as pl

from reason8.game.unitdefs import UnitDef, game_unit_defs
from reason8.game.versions import UNIT_RENAMES, current_unit_name
from reason8.openings.extract import OPENING_SECONDS, unit_role
from reason8.replays import tables as replay_tables
from reason8.replays.replay import GAME_SPEED

COMMANDER, FACTORY, CONSTRUCTION, TOWER, OTHER_BUILDER = (
    "commander",
    "factory",
    "construction",
    "tower",
    "other",
)
BUILDER_KINDS = (COMMANDER, FACTORY, CONSTRUCTION, TOWER, OTHER_BUILDER)

ASSIST, RECLAIM, REPAIR, RESURRECT = "assist", "reclaim", "repair", "resurrect"
#: The jobs a builder can be given without a target: the answers of the model besides units.
JOBS = (ASSIST, RECLAIM, REPAIR, RESURRECT)
#: The commands that give a builder a job (`job_of`).
JOB_COMMANDS = ("GUARD", "REPAIR", "RECLAIM", "RESURRECT")
#: Commands that give a unit something to do, so that it is no longer idle. State toggles
#: (fire state, priority, repeat, ...) and queue edits (``REMOVE``) are not among them.
BUSY_COMMANDS = (
    "BUILD",
    "MOVE",
    "FIGHT",
    "PATROL",
    "ATTACK",
    "AREA_ATTACK",
    "MANUALFIRE",
    "GUARD",
    "REPAIR",
    "RECLAIM",
    "RESURRECT",
    "RESTORE",
    "CAPTURE",
    "LOAD_UNITS",
    "LOAD_ONTO",
    "UNLOAD_UNITS",
    "UNLOAD_UNIT",
    "LAND_AT",
    "AREA_MEX",
)
#: Feature ids in commands are offset by the engine's unit limit.
MAX_UNITS = 32000

BUILDER_TYPE_SCHEMA = {
    "game": pl.String,
    "unit_def": pl.String,  # the name in that game version, as the state tables have it
    "builder_unit": pl.String,  # today's name (`current_unit_name`)
    "builder_kind": pl.String,
    "builder_moves": pl.Boolean,
    "build_power": pl.Float32,
    "can_assist": pl.Boolean,
    "can_reclaim": pl.Boolean,
    "can_repair": pl.Boolean,
    "can_resurrect": pl.Boolean,
    "build_options": pl.List(pl.String),  # today's names
}


def builder_kind(unit: UnitDef) -> str | None:
    """The kind of a unit with build power (see the module docs), or None without it."""
    if unit.number("workertime") <= 0:
        return None
    if unit.custom.get("iscommander"):
        return COMMANDER
    if unit.is_static:
        return FACTORY if unit.build_options else TOWER
    return CONSTRUCTION if unit.build_options else OTHER_BUILDER


def _flag(unit: UnitDef, key: str, default: bool) -> bool:
    value = unit.fields.get(key)
    return bool(value) if isinstance(value, bool | int) else default


def builder_type_rows(game: str, unit_defs: Mapping[str, UnitDef]) -> list[dict]:
    """One row per unit type with build power of one game version (`BUILDER_TYPE_SCHEMA`)."""
    rows = []
    for name, unit in sorted(unit_defs.items()):
        kind = builder_kind(unit)
        if kind is None:
            continue
        does_jobs = kind != FACTORY
        rows.append(
            {
                "game": game,
                "unit_def": name,
                "builder_unit": current_unit_name(name),
                "builder_kind": kind,
                "builder_moves": not unit.is_static,
                "build_power": unit.number("workertime"),
                "can_assist": does_jobs and _flag(unit, "canassist", True),
                "can_reclaim": does_jobs and _flag(unit, "canreclaim", True),
                "can_repair": does_jobs and _flag(unit, "canrepair", True),
                "can_resurrect": does_jobs and _flag(unit, "canresurrect", False),
                "build_options": sorted(
                    {current_unit_name(option) for option in unit.build_options}
                ),
            }
        )
    return rows


def builder_types(games: Iterable[str], content_dir: Path) -> pl.DataFrame:
    """The unit types with build power of each game version (`BUILDER_TYPE_SCHEMA`), from
    the unit files of the versions installed in `content_dir` (``data/bar``)."""
    rows = []
    for game in sorted(set(games)):
        rows += builder_type_rows(game, game_unit_defs(content_dir, game))
    return pl.DataFrame(rows, schema=BUILDER_TYPE_SCHEMA)


def answers_of(types: pl.DataFrame) -> pl.DataFrame:
    """Per game version and builder type, the answers it can give: its build list and the
    jobs it can do, as a list column ``answers``."""
    jobs = pl.concat_list(
        [pl.when(pl.col(f"can_{job}")).then(pl.lit([job])).otherwise(pl.lit([])) for job in JOBS]
    )
    return types.select(
        "game", "builder_unit", pl.concat_list("build_options", jobs).alias("answers")
    ).unique(["game", "builder_unit"], keep="first")


# --- the units each command went to


def command_units(commands: pl.LazyFrame, selections: pl.LazyFrame) -> pl.LazyFrame:
    """The commands with ``targets``: the unit ids each went to.

    A ``COMMAND`` goes to the player's selection of the last ``select`` event before it in
    the stream (`seq`), an ``AICOMMAND``/``AICOMMANDS`` to its own ``units``.
    """
    chosen = (
        selections.select(
            pl.col("replay"),
            pl.col("player"),
            pl.col("seq"),
            pl.col("units").alias("selection"),
        )
        .sort("seq")
        .collect()
    )
    found = (
        commands.sort("seq")
        .collect()
        .join_asof(
            chosen, on="seq", by=["replay", "player"], strategy="backward", check_sortedness=False
        )
    )
    return found.lazy().with_columns(
        pl.when(pl.col("via") == "COMMAND")
        .then(pl.col("selection"))
        .otherwise(pl.col("units"))
        .fill_null([])
        .alias("targets")
    )


# --- what each unit id is


def unit_lives(events: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """The state of every unit after each of its life events: replay, unit_id, frame,
    unit_def, owner (its team then), alive, finished; one row per event, by frame.

    `events` are the ``events`` tables of some games. A unit id used again starts a new
    life. Joined as of a frame, the last row up to it says what the unit id was then."""
    kind = pl.col("kind").cast(pl.String)
    unit = ["replay", "unit_id"]
    return (
        events.lazy()
        .with_row_index("_order")
        .with_columns(pl.col("replay").cast(pl.String), kind.alias("kind"))
        .filter(pl.col("kind").is_in(["created", "finished", "given", "destroyed"]))
        .with_columns(
            (pl.col("kind") == "created").cast(pl.Int32).cum_sum().over(unit).alias("life")
        )
        .filter(pl.col("life") > 0)
        .with_columns(
            ((pl.col("kind") == "finished").cast(pl.Int32).cum_sum().over(*unit, "life") > 0).alias(
                "finished"
            ),
            (
                (pl.col("kind") == "destroyed").cast(pl.Int32).cum_sum().over(*unit, "life") == 0
            ).alias("alive"),
        )
        .select(
            "replay",
            "unit_id",
            pl.col("frame").cast(pl.Int32),
            pl.col("unit_def").cast(pl.String),
            pl.col("team").cast(pl.Int32).alias("owner"),
            "alive",
            "finished",
            "_order",
        )
        .sort("frame", "_order")
        .drop("_order")
    )


def units_at(
    wanted: pl.DataFrame, lives: pl.DataFrame, frame: str = "frame", unit: str = "unit_id"
) -> pl.DataFrame:
    """`wanted` with what its unit ids were at its frames: ``unit_def``, ``owner``,
    ``alive``, ``finished`` (null where the id names no unit up to then)."""
    return (
        wanted.with_columns(pl.col(unit).cast(pl.Int32))
        .with_row_index("_row")
        .sort(frame)
        .join_asof(
            lives.rename({"unit_id": unit, "frame": "_life_frame"}).sort("_life_frame"),
            left_on=frame,
            right_on="_life_frame",
            by=["replay", unit],
            strategy="backward",
            check_sortedness=False,
        )
        .sort("_row")
        .drop("_row", "_life_frame")
    )


# --- jobs


def job_of(command: pl.Expr, params: pl.Expr, target_finished: pl.Expr) -> pl.Expr:
    """The job a command gives a builder, or null: ``GUARD`` is assist; ``REPAIR`` of a
    unit still being built is assist (helping to build it), any other ``REPAIR`` (of a
    finished unit, or of an area) is repair; ``RECLAIM`` (of a feature, a unit or an area)
    is reclaim and ``RESURRECT`` is resurrect. `target_finished` says, for a command on one
    unit, whether that unit was finished then."""
    single = params.list.len() == 1
    return (
        pl.when(command == "GUARD")
        .then(pl.lit(ASSIST))
        .when((command == "REPAIR") & single & target_finished.not_().fill_null(False))
        .then(pl.lit(ASSIST))
        .when(command == "REPAIR")
        .then(pl.lit(REPAIR))
        .when(command == "RECLAIM")
        .then(pl.lit(RECLAIM))
        .when(command == "RESURRECT")
        .then(pl.lit(RESURRECT))
    )


def job_target(command: pl.Expr, params: pl.Expr) -> pl.Expr:
    """What a job command points at: ``unit``, ``feature`` or ``area``."""
    first = params.list.first()
    return (
        pl.when(params.list.len() >= 4)
        .then(pl.lit("area"))
        .when(params.list.len() >= 3)
        .then(pl.lit("spot"))
        .when(first >= MAX_UNITS)
        .then(pl.lit("feature"))
        .when(command.is_in(JOB_COMMANDS))
        .then(pl.lit("unit"))
    )


# --- idle and build power over time


def idle_transitions(
    idle_events: pl.DataFrame, busy: pl.DataFrame, gone: pl.DataFrame
) -> pl.DataFrame:
    """Per unit, every change of whether it is idle: replay, unit_id, frame, idle.

    `idle_events` are the ``idle`` lines (replay, unit_id, frame), `busy` the frames of
    commands that gave the unit something to do (`BUSY_COMMANDS`), `gone` the frames the
    unit was destroyed or given away. A command in the frame of an idle line comes after
    it: a command is carried out after the frame it is recorded in has been simulated."""
    columns = ["replay", "unit_id", "frame"]
    parts = [
        idle_events.select(*columns).with_columns(
            pl.lit(True).alias("idle"), pl.lit(0).alias("_k")
        ),
        busy.select(*columns).with_columns(pl.lit(False).alias("idle"), pl.lit(1).alias("_k")),
        gone.select(*columns).with_columns(pl.lit(False).alias("idle"), pl.lit(2).alias("_k")),
    ]
    return (
        pl.concat(
            [
                part.cast({"replay": pl.String, "unit_id": pl.Int32, "frame": pl.Int32})
                for part in parts
            ]
        )
        .sort("replay", "unit_id", "frame", "_k")
        .unique(["replay", "unit_id", "frame"], keep="last", maintain_order=True)
        .drop("_k")
    )


# --- the decisions of an opening: its build orders and its jobs

#: The columns of a row of the opening dataset that are about one order; the others are
#: about the game and the player.
ORDER_ONLY = (
    "order_index",
    "seq_idx",
    "frame",
    "unit",
    "kind",
    "count",
    "via",
    "queued",
    "inserted",
    "quota",
    "repeat",
    "x",
    "z",
)
JOB_KIND = "job"
START = "<start>"
COMMAND_COLUMNS = (
    "replay",
    "seq",
    "frame",
    "player",
    "team",
    "via",
    "units",
    "command",
    "unit",
    "options",
    "params",
    "facing",
    "inserted",
    "insert_options",
)


class OrdersNotFound(ValueError):
    """The commands do not hold the build orders of the opening dataset."""


def opening_decisions(
    orders: pl.DataFrame, commands: pl.DataFrame, lives: pl.DataFrame
) -> pl.DataFrame:
    """The build orders and the job orders of the openings, in the order they were given.

    `orders` are rows of the opening dataset with ``replay``; `commands` the commands of
    the same games with ``targets`` (`command_units`), `lives` their `unit_lives`. Each
    build order is found again among the commands (the opening dataset numbers a player's
    build orders in stream order), which gives it its ``seq`` and ``targets``. The job
    orders (`JOB_COMMANDS`) of each player up to the end of their opening are added with
    kind ``job``, their ``job``, ``job_command`` and ``job_target``, and the columns of the
    player. ``decision_index`` numbers a player's rows, ``answer`` is the unit an order adds
    or the job (null for orders that take units out of a factory queue).
    """
    build = (
        replay_tables.build_order_frame(commands.lazy(), until_frame=OPENING_SECONDS * GAME_SPEED)
        .filter(
            pl.col("team").is_not_null(),
            pl.col("unit").is_not_null(),
            pl.col("unit") != "",
            pl.col("frame").is_not_null(),
        )
        .sort("replay", "team", "seq")
        .select(
            "replay",
            pl.col("team").cast(pl.Int32).alias("player_slot"),
            pl.int_range(pl.len()).over("replay", "team").cast(pl.Int32).alias("order_index"),
            "seq",
            pl.col("frame").alias("_frame"),
            pl.col("unit").replace(UNIT_RENAMES).alias("_unit"),
            "targets",
        )
        .collect()
    )
    found = orders.join(build, on=["replay", "player_slot", "order_index"], how="left")
    missing = found.filter(
        pl.col("seq").is_null()
        | (pl.col("_frame") != pl.col("frame"))
        | (pl.col("_unit").replace(UNIT_RENAMES) != pl.col("unit").replace(UNIT_RENAMES))
    )
    if missing.height:
        raise OrdersNotFound(
            f"{missing.height} of {orders.height} build orders not found in the commands, "
            f"e.g. {missing.select('replay', 'player_slot', 'order_index').row(0)}"
        )
    found = found.drop("_frame", "_unit")

    player_columns = [name for name in orders.columns if name not in ORDER_ONLY]
    players = orders.group_by("replay", "player_slot").agg(
        pl.col(name).first() for name in player_columns if name not in ("replay", "player_slot")
    )
    jobs = (
        commands.filter(
            pl.col("command").is_in(JOB_COMMANDS),
            pl.col("frame").is_not_null(),
            pl.col("team").is_not_null(),
        )
        .with_columns(pl.col("team").cast(pl.Int32).alias("player_slot"))
        .join(players, on=["replay", "player_slot"])
        .filter(pl.col("frame") <= pl.col("cutoff_frame"))
        .with_columns(
            pl.when(pl.col("params").list.len() == 1)
            .then(pl.col("params").list.first().cast(pl.Int32))
            .alias("_target")
        )
    )
    targets = units_at(
        jobs.select("replay", "frame", pl.col("_target").alias("unit_id")).filter(
            pl.col("unit_id") < MAX_UNITS
        ),
        lives,
    )
    jobs = jobs.with_columns(
        pl.when(pl.col("_target") < MAX_UNITS)
        .then(
            jobs.select("replay", "frame", pl.col("_target").alias("unit_id")).join(
                targets.unique(["replay", "frame", "unit_id"]),
                on=["replay", "frame", "unit_id"],
                how="left",
                maintain_order="left",
            )["finished"]
        )
        .alias("_target_finished")
    )
    shift = pl.col("options").cast(pl.Int32) & replay_tables.SHIFT != 0
    structure = pl.col("params").list.len() >= 3
    jobs = jobs.select(
        *player_columns,
        pl.lit(None, dtype=pl.Int32).alias("order_index"),
        pl.lit(None, dtype=pl.Int32).alias("seq_idx"),
        "frame",
        pl.lit(None, dtype=pl.String).alias("unit"),
        pl.lit(JOB_KIND).alias("kind"),
        pl.lit(None, dtype=pl.Int32).alias("count"),
        pl.col("via").cast(pl.String),
        shift.alias("queued"),
        pl.col("inserted").fill_null(False),
        pl.lit(False).alias("quota"),
        pl.lit(False).alias("repeat"),
        pl.when(structure).then(pl.col("params").list.get(0, null_on_oob=True)).alias("x"),
        pl.when(structure).then(pl.col("params").list.get(2, null_on_oob=True)).alias("z"),
        "seq",
        "targets",
        job_of(pl.col("command"), pl.col("params"), pl.col("_target_finished")).alias("job"),
        pl.col("command").alias("job_command"),
        job_target(pl.col("command"), pl.col("params")).alias("job_target"),
    )
    found = found.with_columns(
        pl.lit(None, dtype=pl.String).alias("job"),
        pl.lit(None, dtype=pl.String).alias("job_command"),
        pl.lit(None, dtype=pl.String).alias("job_target"),
    )
    decisions = pl.concat([found, jobs.select(found.columns)], how="vertical_relaxed")
    return decisions.sort("match_id", "player_slot", "seq").with_columns(
        pl.int_range(pl.len())
        .over("match_id", "player_slot")
        .cast(pl.Int32)
        .alias("decision_index"),
        pl.when(pl.col("kind") == JOB_KIND)
        .then(pl.col("job"))
        .when(pl.col("count") > 0)
        .then(pl.col("unit"))
        .alias("answer"),
    )


#: The columns `order_builders` adds about the builder of a row.
BUILDER_COLUMNS = (
    "builder_index",
    "builder_id",
    "builder_unit",
    "builder_role",
    "builder_kind",
    "builder_moves",
    "builder_build_power",
)


def order_builders(
    decisions: pl.DataFrame, lives: pl.DataFrame, types: pl.DataFrame, games: pl.DataFrame
) -> pl.DataFrame:
    """One row per decision and builder that got it, with the builder (`BUILDER_COLUMNS`).

    `decisions` come from `opening_decisions`, `lives` from `unit_lives`, `types` from
    `builder_types`, and `games` has the ``game`` version of each ``replay``. A builder of
    an order is a unit the order went to that was the player's and alive in its frame and
    can carry the order out: a build order a unit of its build list, a job a job it can
    do. Each decision also gets ``targets`` (how many units the command went to),
    ``builders`` (how many of them are its builders) and ``other_units`` (units without
    build power among them). A decision without a builder keeps one row with the builder
    columns null. ``builder_index`` numbers the builders of a decision by build power,
    most first, then by unit id; the row with ``builder_index`` 0 stands for the decision.
    """
    key = ["match_id", "player_slot", "decision_index"]
    targets = (
        decisions.select(*key, "replay", "frame", "unit", "kind", "job", "targets")
        .explode("targets")
        .rename({"targets": "unit_id"})
        .filter(pl.col("unit_id").is_not_null())
        .with_columns(pl.col("unit_id").cast(pl.Int32))
    )
    targets = (
        units_at(targets, lives)
        .join(games.select("replay", "game"), on="replay", how="left")
        .join(
            types.select(
                "game",
                "unit_def",
                "builder_unit",
                "builder_kind",
                "builder_moves",
                pl.col("build_power").alias("builder_build_power"),
                "build_options",
                *[f"can_{job}" for job in JOBS],
            ),
            on=["game", "unit_def"],
            how="left",
        )
        .join(decisions.select(*key), on=key)
    )
    able = pl.col("build_options").list.contains(pl.col("unit"))
    for job in JOBS:
        able = pl.when(pl.col("job") == job).then(pl.col(f"can_{job}")).otherwise(able)
    targets = targets.with_columns(
        (
            pl.col("alive").fill_null(False)
            & (pl.col("owner") == pl.col("player_slot"))
            & pl.col("builder_kind").is_not_null()
            & able.fill_null(False)
        ).alias("_builder")
    )
    counts = targets.group_by(key).agg(
        pl.len().cast(pl.Int32).alias("targets"),
        pl.col("_builder").sum().cast(pl.Int32).alias("builders"),
        (pl.col("builder_kind").is_null() & pl.col("alive").fill_null(False))
        .sum()
        .cast(pl.Int32)
        .alias("other_units"),
    )
    chosen = (
        targets.filter("_builder")
        .sort(
            *key, pl.col("builder_build_power"), "unit_id", descending=[False] * 3 + [True, False]
        )
        .with_columns(pl.int_range(pl.len()).over(key).cast(pl.Int32).alias("builder_index"))
        .select(
            *key,
            "builder_index",
            pl.col("unit_id").alias("builder_id"),
            "builder_unit",
            pl.col("builder_unit")
            .map_elements(unit_role, return_dtype=pl.String)
            .alias("builder_role"),
            "builder_kind",
            "builder_moves",
            pl.col("builder_build_power").cast(pl.Float32),
        )
    )
    rows = (
        decisions.drop("targets")
        .join(counts, on=key, how="left")
        .with_columns(pl.col("targets", "builders", "other_units").fill_null(0))
        .join(chosen, on=key, how="left")
        .with_columns(pl.col("builder_index").fill_null(0))
    )
    return rows.sort(*key, "builder_index")


def with_builder_history(rows: pl.DataFrame) -> pl.DataFrame:
    """Add ``builder_previous``: the answer of the decision before this one that went to
    the same builder (`START` for its first), null for rows without a builder."""
    with_builder = rows.filter(pl.col("builder_id").is_not_null(), pl.col("answer").is_not_null())
    previous = with_builder.sort("match_id", "player_slot", "decision_index").select(
        "match_id",
        "player_slot",
        "decision_index",
        "builder_id",
        pl.col("answer")
        .shift(1)
        .over("match_id", "builder_id")
        .fill_null(START)
        .alias("builder_previous"),
    )
    return rows.join(
        previous,
        on=["match_id", "player_slot", "decision_index", "builder_id"],
        how="left",
        maintain_order="left",
    )


# --- build power and idle builders over time


def running_sums(
    amounts: pl.DataFrame, key: str, names: Sequence[str], column: str = "column"
) -> pl.DataFrame:
    """Sums of ``amount`` per replay and `key` after each frame with a change, one column
    per value of `column` (each of `names`), one row per replay, key and frame."""
    if amounts.is_empty():
        return pl.DataFrame(
            schema={"replay": pl.String, key: pl.Int32, "frame": pl.Int32}
            | dict.fromkeys(names, pl.Float32)
        )
    wide = (
        amounts.group_by("replay", key, "frame", column)
        .agg(pl.col("amount").sum())
        .pivot(on=column, index=["replay", key, "frame"], values="amount")
    )
    missing = [name for name in names if name not in wide.columns]
    return (
        wide.with_columns(pl.lit(0.0, dtype=pl.Float32).alias(name) for name in missing)
        .select("replay", key, "frame", *names)
        .sort("replay", key, "frame")
        .with_columns(pl.col(names).fill_null(0).cum_sum().over("replay", key).cast(pl.Float32))
    )


def power_columns(prefix: str) -> list[str]:
    return [f"{prefix}_{kind}" for kind in BUILDER_KINDS]


def team_build_power(
    changes: pl.DataFrame, types: pl.DataFrame, games: pl.DataFrame
) -> pl.DataFrame:
    """The build power of each team's finished builders after each frame with a change, by
    kind (``team_build_power_<kind>``); `changes` are those of
    `reason8.context.table.unit_changes`."""
    amounts = (
        changes.filter("finished")
        .join(games.select("replay", "game"), on="replay")
        .join(
            types.select("game", "unit_def", "builder_kind", "build_power"), on=["game", "unit_def"]
        )
        .select(
            "replay",
            "team",
            "frame",
            (pl.lit("team_build_power_") + pl.col("builder_kind")).alias("column"),
            (pl.col("change") * pl.col("build_power")).alias("amount"),
        )
    )
    return running_sums(amounts, "team", power_columns("team_build_power"))


def idle_build_power(
    transitions: pl.DataFrame, lives: pl.DataFrame, types: pl.DataFrame, games: pl.DataFrame
) -> pl.DataFrame:
    """The build power of each team's idle builders after each frame with a change, by kind
    (``idle_build_power_<kind>``), from `idle_transitions`."""
    steps = (
        transitions.sort("replay", "unit_id", "frame")
        .with_columns(
            (
                pl.col("idle").cast(pl.Int32)
                - pl.col("idle").shift(1).over("replay", "unit_id").fill_null(False).cast(pl.Int32)
            ).alias("_delta")
        )
        .filter(pl.col("_delta") != 0)
    )
    # whose and what the unit was just before each change: a unit given away or destroyed
    # leaves the team it idled in
    steps = (
        units_at(steps.with_columns((pl.col("frame") - 1).alias("_before")), lives, "_before")
        .drop("_before")
        .with_columns(
            pl.col("owner").forward_fill().over("replay", "unit_id"),
            pl.col("unit_def").forward_fill().over("replay", "unit_id"),
        )
        .join(games.select("replay", "game"), on="replay")
        .join(
            types.select("game", "unit_def", "builder_kind", "build_power"), on=["game", "unit_def"]
        )
    )
    amounts = steps.select(
        "replay",
        pl.col("owner").alias("team"),
        "frame",
        (pl.lit("idle_build_power_") + pl.col("builder_kind")).alias("column"),
        (pl.col("_delta") * pl.col("build_power")).alias("amount"),
    ).filter(pl.col("team").is_not_null())
    return running_sums(amounts, "team", power_columns("idle_build_power"))


def builder_unit_ids(lives: pl.DataFrame, types: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    """The replay and unit id of every unit that was ever of a type with build power."""
    return (
        lives.join(games.select("replay", "game"), on="replay")
        .join(types.select("game", "unit_def"), on=["game", "unit_def"])
        .select("replay", "unit_id")
        .unique()
    )


def transitions_of(
    commands: pl.DataFrame, events: pl.DataFrame, builder_ids: pl.DataFrame
) -> pl.DataFrame:
    """`idle_transitions` of the builders (`builder_ids`) of some games, from their
    commands (with ``targets``) and their state's ``events``."""
    events = events.with_columns(pl.col("replay").cast(pl.String), pl.col("kind").cast(pl.String))
    idle_lines = events.filter(pl.col("kind") == "idle").select("replay", "unit_id", "frame")
    gone = events.filter(pl.col("kind").is_in(["destroyed", "given"])).select(
        "replay", "unit_id", "frame"
    )
    busy = (
        commands.filter(pl.col("command").is_in(BUSY_COMMANDS), pl.col("frame").is_not_null())
        .select("replay", "frame", pl.col("targets").alias("unit_id"))
        .explode("unit_id")
        .filter(pl.col("unit_id").is_not_null())
        .with_columns(pl.col("unit_id").cast(pl.Int32))
        .join(builder_ids, on=["replay", "unit_id"], how="semi")
        .unique()
    )
    return idle_transitions(
        idle_lines.join(builder_ids, on=["replay", "unit_id"], how="semi"),
        busy,
        gone.join(builder_ids, on=["replay", "unit_id"], how="semi"),
    )


def builder_idle(rows: pl.DataFrame, transitions: pl.DataFrame) -> pl.Series:
    """Whether the builder of each row was idle at the row's ``state_frame``: it had gone
    idle and got nothing to do since. Null for a builder that never went idle before and
    for rows without a builder."""
    found = (
        rows.select("replay", pl.col("builder_id").cast(pl.Int32).alias("unit_id"), "state_frame")
        .with_row_index("_row")
        .sort("state_frame")
        .join_asof(
            transitions.sort("frame"),
            left_on="state_frame",
            right_on="frame",
            by=["replay", "unit_id"],
            strategy="backward",
            check_sortedness=False,
        )
        .sort("_row")
    )
    return found["idle"].alias("builder_idle")
