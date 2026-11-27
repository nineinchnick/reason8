"""Checks that the features, reclaim and builders' work of a game's state add up.

From format 6 the state has the reclaimable features (wrecks, heaps, rocks, trees), the
metal and energy each team reclaimed from them and what every builder worked on, sampled
(`reason8.headless.tables`). `check()` compares them with each other and with the rest of
the state, on the tables of one game:

``reclaim``
    the metal and energy each team reclaimed, against what the game itself counts (only
    game versions from late 2026 count it, in the ``game_reclaimed`` of the ``game`` row);
    and per feature, what the teams took against what it lost: all of it for one reclaimed
    away, at most what it lost for one destroyed
``features``
    how the features went (reclaimed, resurrected, destroyed, still there), how many
    wrecks match a unit of their type destroyed near them before, how many destroyed
    wrecks left a heap in the same frame
``resurrected``
    units made from a feature: the feature went as resurrected and its type is the unit's
``work``
    the units finished that a builder other than a factory made: how many of them a sampled
    ``work`` line shows being built, by their builder and by others (assisting), and the
    units reclaimed that a ``work`` line shows their reclaimer on

`reason8 headless tables --check` runs it with the check of the units
(`reason8.headless.standing`).
"""

from __future__ import annotations

import polars as pl

#: A wreck appears where its unit died, after the death animation: how far and how many
#: frames after the death to look for the unit.
WRECK_DISTANCE = 64
WRECK_FRAMES = 300
#: How much a team's reclaim may differ from the game's count before it is a difference:
#: the game credits a step at the next step on the feature, a frame later.
RECLAIM_TOLERANCE = 0.01


def check(game_tables: dict[str, pl.DataFrame]) -> dict:
    """The checks of the module docstring on the tables of one game; empty before format 6."""
    game = game_tables["game"].row(0, named=True)
    if game["work_frames"] is None:
        return {}
    features = game_tables["features"].drop("replay")
    reclaim = game_tables["reclaim"].drop("replay")
    work = game_tables["work"].drop("replay")
    events = game_tables["events"].drop("replay")
    return {
        "work_frames": game["work_frames"],
        "reclaim": _reclaim(game, features, reclaim),
        "features": _features(features, events),
        "resurrected": _resurrected(features, events),
        "work": _work(game, work, events),
    }


def _reclaim(game: dict, features: pl.DataFrame, reclaim: pl.DataFrame) -> dict:
    by_team = reclaim.group_by("team").agg(pl.col("metal").sum(), pl.col("energy").sum())
    total = by_team.select(pl.col("metal").sum(), pl.col("energy").sum()).row(0)
    result: dict = {"metal": round(total[0] or 0, 1), "energy": round(total[1] or 0, 1)}
    if game["game_reclaimed"] is not None:
        counted = pl.DataFrame(
            game["game_reclaimed"],
            schema={"team": pl.Int16, "metal": pl.Float32, "energy": pl.Float32},
            orient="row",
        )
        joined = counted.join(
            by_team, on="team", how="full", suffix="_ours", coalesce=True
        ).fill_null(0)
        differences = []
        largest = {"metal": 0.0, "energy": 0.0}
        for row in joined.iter_rows(named=True):
            for resource in ("metal", "energy"):
                game_value, ours = row[resource], row[f"{resource}_ours"]
                largest[resource] = max(largest[resource], abs(ours - game_value))
                if abs(ours - game_value) > max(1.0, RECLAIM_TOLERANCE * game_value):
                    differences.append(
                        {
                            "team": row["team"],
                            resource: round(ours, 1),
                            "game": round(game_value, 1),
                        }
                    )
        result["game_metal"] = round(counted.get_column("metal").sum(), 1)
        result["game_energy"] = round(counted.get_column("energy").sum(), 1)
        result["largest_team_difference"] = {
            resource: round(value, 1) for resource, value in largest.items()
        }
        result["teams_differing_from_game"] = differences
    # per feature: what the teams took, against what it lost
    taken = reclaim.group_by("feature_id").agg(
        pl.col("metal").sum().alias("taken_metal"), pl.col("energy").sum().alias("taken_energy")
    )
    # a feature id is used again only after the feature is gone: the last life of an id
    # gets the reclaim of all its lives, which is rare enough to count as a difference
    per_feature = features.join(taken, on="feature_id", how="left").with_columns(
        pl.col("taken_metal").fill_null(0), pl.col("taken_energy").fill_null(0)
    )
    lost = (pl.col("metal") - pl.col("metal_left").fill_null(pl.col("metal"))).alias("lost")
    reclaimed_away = per_feature.filter(pl.col("end") == "reclaimed")
    result["features_reclaimed_away"] = reclaimed_away.height
    result["reclaimed_away_not_all_taken"] = reclaimed_away.filter(
        ((pl.col("taken_metal") - pl.col("metal")).abs() > 0.5)
        | ((pl.col("taken_energy") - pl.col("energy")).abs() > 0.5)
    ).height
    others = per_feature.filter(pl.col("end") != "reclaimed").with_columns(lost)
    result["others_taken_more_than_lost"] = others.filter(
        pl.col("taken_metal") > pl.col("lost") + 0.5
    ).height
    return result


def _features(features: pl.DataFrame, events: pl.DataFrame) -> dict:
    ends = features.group_by("end").len()
    result: dict = {
        "features": features.height,
        "at_start": features.filter(pl.col("created_frame") == 0).height,
        "ends": {
            str(row["end"]) if row["end"] is not None else "there_at_end": row["len"]
            for row in ends.iter_rows(named=True)
        },
    }
    wrecks = features.filter(pl.col("resurrect_as").is_not_null())
    deaths = events.filter(pl.col("kind") == "destroyed").select(
        pl.col("frame").alias("death_frame"),
        pl.col("unit_def").cast(pl.String).alias("unit_type"),
        pl.col("x").alias("death_x"),
        pl.col("z").alias("death_z"),
    )
    matched = (
        wrecks.with_row_index("wreck")
        .with_columns(pl.col("resurrect_as").cast(pl.String).alias("unit_type"))
        .join(deaths, on="unit_type")
        .filter(
            pl.col("death_frame").is_between(
                pl.col("created_frame") - WRECK_FRAMES, pl.col("created_frame")
            ),
            ((pl.col("x") - pl.col("death_x")) ** 2 + (pl.col("z") - pl.col("death_z")) ** 2)
            <= WRECK_DISTANCE**2,
        )
        .select("wreck")
        .unique()
    )
    result["wrecks"] = wrecks.height
    result["wrecks_matching_a_death"] = matched.height
    # a wreck blown up leaves a heap in its place, in the same frame
    destroyed = features.filter(pl.col("end") == "destroyed").select(
        "feature_id", "x", "z", pl.col("destroyed_frame").alias("frame")
    )
    heaps = features.select(
        pl.col("feature_id").alias("heap"),
        pl.col("x").alias("heap_x"),
        pl.col("z").alias("heap_z"),
        pl.col("created_frame").alias("frame"),
    )
    left_heap = (
        destroyed.join(heaps, on="frame")
        .filter(
            ((pl.col("x") - pl.col("heap_x")) ** 2 + (pl.col("z") - pl.col("heap_z")) ** 2)
            <= WRECK_DISTANCE**2
        )
        .select("feature_id")
        .unique()
    )
    result["destroyed_leaving_a_feature"] = left_heap.height
    return result


def _resurrected(features: pl.DataFrame, events: pl.DataFrame) -> dict:
    made = events.filter(pl.col("resurrected_from").is_not_null()).select(
        pl.col("unit_id"),
        pl.col("unit_def").cast(pl.String),
        pl.col("resurrected_from").alias("feature_id"),
        "frame",
    )
    joined = made.join(
        features.select(
            "feature_id",
            pl.col("resurrect_as").cast(pl.String),
            "end",
            "created_frame",
            "destroyed_frame",
        ),
        on="feature_id",
        how="left",
    ).filter(
        pl.col("created_frame").is_null()
        | pl.col("frame").is_between(
            pl.col("created_frame"), pl.col("destroyed_frame").fill_null(2**31 - 1)
        )
    )
    return {
        "units": made.height,
        "feature_resurrected": joined.filter(pl.col("end") == "resurrected").height,
        "same_type": joined.filter(pl.col("unit_def") == pl.col("resurrect_as")).height,
        "features_resurrected": features.filter(pl.col("end") == "resurrected").height,
    }


def _work(game: dict, work: pl.DataFrame, events: pl.DataFrame) -> dict:
    sampled = set(game["builder_types"] or [])
    created = events.filter(pl.col("kind") == "created")
    types = created.select(
        pl.col("unit_id").alias("builder"), pl.col("unit_def").cast(pl.String).alias("builder_type")
    ).unique("builder", keep="last")
    finished = events.filter(pl.col("kind") == "finished").select(
        "unit_id", pl.col("frame").alias("finished_frame")
    )
    # units built over time (not made finished, as commanders are) by a unit; the work of
    # factories is not sampled, that of every other builder is
    built = (
        created.select("unit_id", "builder", pl.col("frame").alias("created_frame"))
        .join(finished, on="unit_id")
        .filter(pl.col("finished_frame") > pl.col("created_frame"), pl.col("builder").is_not_null())
        .unique("unit_id", keep="last")
        .join(types, on="builder", how="left")
    )
    by_builders = built.filter(pl.col("builder_type").is_in(list(sampled)))
    building = (
        work.filter(pl.col("task") == "build")
        .select(pl.col("unit_id").alias("helper"), pl.col("target_unit").alias("unit_id"))
        .unique()
    )
    seen = by_builders.join(
        building.rename({"helper": "builder"}), on=["unit_id", "builder"], how="semi"
    )
    assisted = building.join(built.select("unit_id", "builder"), on="unit_id").filter(
        pl.col("helper") != pl.col("builder")
    )
    reclaimed_units = events.filter(pl.col("reclaimed").fill_null(False)).select(
        "unit_id", "attacker"
    )
    reclaim_seen = reclaimed_units.join(
        work.filter(pl.col("task") == "reclaim").select(
            pl.col("unit_id").alias("attacker"), pl.col("target_unit").alias("unit_id")
        ),
        on=["unit_id", "attacker"],
        how="semi",
    )
    return {
        "lines": work.height,
        "builders": work.get_column("unit_id").n_unique(),
        "tasks": {
            row["task"]: row["len"]
            for row in work.group_by("task").len().sort("task").iter_rows(named=True)
        },
        "built_by_builders": by_builders.height,
        "built_by_builders_seen_building": seen.height,
        "built_by_factories": built.height - by_builders.height,
        "units_assisted": assisted.get_column("unit_id").n_unique(),
        "units_reclaimed": reclaimed_units.height,
        "units_reclaimed_seen": reclaim_seen.height,
    }
