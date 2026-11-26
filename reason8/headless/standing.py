"""What stands on the map at a given frame, rebuilt from the unit events of the state.

Buildings do not move, and every unit has a line when it is created (with its type, team and
position), finished, given to another team and destroyed. So the units of a team at any
frame follow from those lines alone, at every frame and not only at the snapshots:
`standing_units()` does that on the ``events`` table (`reason8.headless.tables`). The
position is where the unit was created: where a building stands, and for a unit that can
move the factory or builder that made it (the ``units`` table has where it went).

`check()` compares the rebuilt units with every snapshot of a game. A snapshot of format 5
is written at the end of its frame and must equal the units after that frame's events
(those that can move or are not finished; the others are left out of it). Up to format 4 a
snapshot was written at the start of its frame, after the events of earlier frames but also
after what the game's own scripts did at the start of that frame (see
``docs/research/state-extraction.md``), so it is compared with the units after the previous
frame and units the game made or removed at the start of the frame show up as differences;
only the last snapshot of a game that ended in a game over or a shutdown was written at the
end of its frame. Up to format 4 a snapshot also lists units that were destroyed and are still dying
(their death animation); `check()` counts them as ``dying_in_snapshot``.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import polars as pl

from reason8.headless import tables
from reason8.headless.state import RESOURCE_LINES_FORMAT

EXAMPLES_PER_DIFFERENCE = 5
LIFE_KINDS = ("created", "finished", "destroyed", "given")
STANDING_SCHEMA = {
    "unit_id": pl.Int32,
    "unit_def": pl.Categorical,
    "team": pl.Int16,
    "x": pl.Int32,
    "z": pl.Int32,
    "created_frame": pl.Int32,
    "finished": pl.Boolean,
}


def standing_units(
    events: pl.DataFrame | pl.LazyFrame, frame: int, team: int | None = None
) -> pl.DataFrame:
    """The units that stand after the events of `frame` (of every team, or of `team`).

    `events` is the ``events`` table of one or more games (in the order it was written);
    with a ``replay`` column the units are per replay. One row per unit: its type, team now,
    where it was created and when, and whether it is finished. Sorted by replay and unit.
    """
    events = events.lazy()
    keys = ["replay", "unit_id"] if "replay" in events.collect_schema() else ["unit_id"]
    life = (
        events.with_row_index("order")
        .filter(pl.col("frame") <= frame, pl.col("kind").cast(pl.String).is_in(LIFE_KINDS))
        .select(
            *keys, "order", pl.col("kind").cast(pl.String), "frame", "unit_def", "team", "x", "z"
        )
    )
    # a unit id is used again after its unit is gone: only the last life of each id counts
    created = (
        life.filter(pl.col("kind") == "created")
        .group_by(keys)
        .agg(pl.all().sort_by("order").last())
        .rename({"order": "created_order", "frame": "created_frame"})
    )
    later = life.join(created.select(*keys, "created_order"), on=keys).filter(
        pl.col("order") > pl.col("created_order")
    )
    destroyed = later.filter(pl.col("kind") == "destroyed").select(keys).unique()
    finished = (
        later.filter(pl.col("kind") == "finished")
        .select(keys)
        .unique()
        .with_columns(pl.lit(True).alias("finished"))
    )
    owner = (
        later.filter(pl.col("kind") == "given")
        .group_by(keys)
        .agg(pl.col("team").sort_by("order").last().alias("owner"))
    )
    standing = (
        created.join(destroyed, on=keys, how="anti")
        .join(finished, on=keys, how="left")
        .join(owner, on=keys, how="left")
        .with_columns(
            pl.coalesce("owner", "team").alias("team"), pl.col("finished").fill_null(False)
        )
    )
    if team is not None:
        standing = standing.filter(pl.col("team") == team)
    columns = [*keys[:-1], *STANDING_SCHEMA]
    return (
        standing.select(columns)
        .with_columns([pl.col(column).cast(dtype) for column, dtype in STANDING_SCHEMA.items()])
        .sort(keys)
        .collect()
    )


def static_names(game: dict) -> set[str] | None:
    """The unit types that cannot move, from a game's ``game`` row; None up to format 4."""
    if game["version"] < RESOURCE_LINES_FORMAT:
        return None
    return {unit_def["name"] for unit_def in game["unit_defs"] if unit_def["static"]}


def check(game_tables: dict[str, pl.DataFrame]) -> dict:
    """Compare the units rebuilt from the events with every snapshot of one game.

    Per snapshot the units in one and not the other, and the units in both whose type,
    team, being finished or (for units that cannot move) position differ. Returns counts,
    and the first few of each kind of difference as examples.
    """
    game = game_tables["game"].row(0, named=True)
    static = static_names(game)
    at_frame_end = game["sampled"] in ("frame_end", None) and static is not None
    events = game_tables["events"].drop("replay")
    snapshots = game_tables["units"].drop("replay")
    # whose position must not change: up to format 4 the header doesn't say which types
    # cannot move, so those of which a unit was seen in several snapshots and none moved
    static_types = static if static is not None else _never_moved(snapshots)
    destroyed = events.filter(pl.col("kind") == "destroyed")
    counts: Counter[str] = Counter()
    examples: list[dict] = []
    frames = snapshots.get_column("frame").unique().sort().to_list()
    for frame in frames:
        after_frame = (
            at_frame_end
            or frame == 0
            # the last snapshot: written at game over or shutdown, not in GameFrame
            or (frame == game["last_frame"] and game["end_reason"] in ("gameover", "shutdown"))
        )
        rebuilt = standing_units(events, frame if after_frame else frame - 1)
        if static is not None:
            rebuilt = rebuilt.filter(
                ~(pl.col("unit_def").cast(pl.String).is_in(static) & pl.col("finished"))
            )
        snapshot = snapshots.filter(pl.col("frame") == frame).with_columns(
            (pl.col("build_pct") >= 100).alias("finished")
        )
        joined = rebuilt.join(snapshot, on="unit_id", how="full", suffix="_snapshot")
        counts["snapshots"] += 1
        counts["units"] += snapshot.height
        dying = set(destroyed.filter(pl.col("frame") <= frame).get_column("unit_id").to_list())
        for row in joined.iter_rows(named=True):
            difference = _difference(row, static_types)
            if difference == "only_in_snapshot" and row["unit_id_snapshot"] in dying:
                difference = "dying_in_snapshot"
            if difference:
                counts[difference] += 1
                if counts[difference] <= EXAMPLES_PER_DIFFERENCE:
                    examples.append({"frame": frame, "difference": difference, **_short(row)})
    return {
        "version": game["version"],
        "sampled": game["sampled"],
        "compared_with": "same frame" if at_frame_end else "previous frame",
        "counts": dict(counts),
        "examples": examples,
    }


def _never_moved(snapshots: pl.DataFrame) -> set[str]:
    per_unit = snapshots.group_by("unit_def", "unit_id").agg(
        pl.struct("x", "z").n_unique().alias("positions"), pl.len().alias("seen")
    )
    return set(
        per_unit.group_by("unit_def")
        .agg(((pl.col("positions").max() == 1) & (pl.col("seen").max() >= 2)).alias("static"))
        .filter("static")
        .get_column("unit_def")
        .cast(pl.String)
        .to_list()
    )


def _difference(row: dict, static_types: set[str]) -> str | None:
    if row["unit_id"] is None:
        return "only_in_snapshot"
    if row["unit_id_snapshot"] is None:
        return "only_rebuilt"
    unit_def = row["unit_def"]
    if unit_def != row["unit_def_snapshot"]:
        return "type"
    if row["team"] != row["team_snapshot"]:
        return "team"
    if row["finished"] != row["finished_snapshot"]:
        return "finished"
    if unit_def in static_types and (row["x"], row["z"]) != (row["x_snapshot"], row["z_snapshot"]):
        return "position"
    return None


def _short(row: dict) -> dict:
    return {
        key: (str(value) if key.startswith("unit_def") and value is not None else value)
        for key, value in row.items()
        if key
        in (
            "unit_id",
            "unit_id_snapshot",
            "unit_def",
            "unit_def_snapshot",
            "team",
            "team_snapshot",
            "finished",
            "finished_snapshot",
            "created_frame",
        )
    }


def check_file(path: str | Path) -> dict:
    """`check()` on a state file, converted in memory (nothing is written)."""
    from reason8.headless.state import read_lines

    return check(tables.to_tables(read_lines(path, snapshots=True), tables.replay_name(path)))
