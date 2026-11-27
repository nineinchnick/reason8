"""Check the decision table against the state it was joined from.

Usage::

    uv run reason8 context check                  # 20 games of context_v1
    uv run reason8 context check --games 100 --seed 1

For some games of the table, every row is compared with the state tables directly:

- the resources of a row are those of the line of the order's second: the last line written
  up to `state_frame`, with the same values;
- the units of the team and of its allies equal what `reason8.headless.standing.standing_units()`
  gives for `state_frame`, counted by type;

and over the same games, what players ordered shows up afterwards: a structure order is
matched with a unit of the same type created by the player's team on the same spot, and a
factory order with units of that type the team's factories created after it.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from reason8 import markdown
from reason8.context.table import (
    OTHER,
    PLAYER,
    RESOURCES,
    dataset_dir,
    role_expression,
    state_dir,
    state_stem,
    unit_counts_columns,
)
from reason8.game.versions import UNIT_RENAMES
from reason8.headless import standing
from reason8.headless import tables as state_tables
from reason8.openings.dataset import SPLITS, step_index
from reason8.replays.replay import GAME_SPEED

SPOT_DISTANCE = 16  # map units between an order's spot and the unit created for it


def load_rows(directory: Path, match_ids: Sequence[int] | None = None) -> pl.DataFrame:
    frames = [pl.scan_parquet(directory / f"{split}.parquet") for split, _ in SPLITS]
    rows = pl.concat(frames, how="diagonal_relaxed")
    if match_ids is not None:
        rows = rows.filter(pl.col("match_id").is_in(list(match_ids)))
    if "answer" not in rows.collect_schema().names():  # a table without builders
        return (
            rows.sort(*PLAYER, "order_index")
            .with_columns(step_index(PLAYER).alias("step_idx"))
            .collect()
        )
    steps = (
        rows.filter(pl.col("builder_index") == 0)
        .sort(*PLAYER, "decision_index")
        .select(
            *PLAYER,
            "decision_index",
            step_index(PLAYER, answer="answer", decides=pl.col("answer").is_not_null()).alias(
                "step_idx"
            ),
        )
    )
    return (
        rows.join(steps, on=[*PLAYER, "decision_index"])
        .sort(*PLAYER, "decision_index", "builder_index")
        .collect()
    )


def builders_and_creators(rows: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    """Per build order that adds a unit and has a builder: whether the unit that then
    built the thing is one of the order's builders.

    A structure order is matched with the unit of its type the player's team created on
    its spot after it (as `ordered_and_created`), whose ``created`` line names the builder
    that started it. A factory order is matched with the units of its type that its
    builder (the factory) created after it. Returns one row per order: ``kind``,
    ``builders``, ``builder_kind`` (of the order's first builder), ``matched`` (something
    was created for it) and ``by_builder`` (by one of its builders)."""
    decision = [*PLAYER, "decision_index"]
    orders = rows.filter(
        pl.col("kind").is_in(["structure", "factory"]),
        pl.col("count") > 0,
        pl.col("builder_id").is_not_null(),
    )
    builder_sets = orders.group_by(decision).agg(pl.col("builder_id").alias("builder_ids"))
    first = orders.filter(pl.col("builder_index") == 0).join(builder_sets, on=decision)
    created = events.filter(pl.col("kind") == "created").select(
        pl.col("replay").cast(pl.String),
        pl.col("team").cast(pl.Int32),
        pl.col("unit_def").cast(pl.String).replace(UNIT_RENAMES).alias("unit"),
        pl.col("frame").alias("created_frame"),
        pl.col("x").alias("created_x"),
        pl.col("z").alias("created_z"),
        pl.col("builder").alias("created_by"),
    )
    structure_orders = first.filter(pl.col("kind") == "structure")
    structures = (
        structure_orders.with_columns(pl.col("player_slot").cast(pl.Int32).alias("team"))
        .join(created, on=["replay", "team", "unit"], how="left")
        .filter(
            pl.col("created_frame").is_null()
            | (
                (pl.col("created_frame") >= pl.col("frame"))
                & ((pl.col("created_x") - pl.col("x")).abs() <= SPOT_DISTANCE)
                & ((pl.col("created_z") - pl.col("z")).abs() <= SPOT_DISTANCE)
            )
        )
        .sort("created_frame", nulls_last=True)
        .group_by(decision, maintain_order=True)
        .agg(
            pl.col("kind", "builders", "builder_kind", "builder_ids").first(),
            pl.col("created_frame").first(),
            pl.col("created_by").first(),
        )
        .select(
            *decision,
            "kind",
            "builders",
            "builder_kind",
            pl.col("created_frame").is_not_null().alias("matched"),
            pl.col("builder_ids")
            .list.contains(pl.col("created_by"))
            .fill_null(False)
            .alias("by_builder"),
        )
    )
    # orders whose type the team made only elsewhere were filtered out above: not matched
    structures = (
        structure_orders.select(*decision, "kind", "builders", "builder_kind")
        .join(
            structures.select(*decision, "matched", "by_builder"),
            on=decision,
            how="left",
            maintain_order="left",
        )
        .with_columns(pl.col("matched", "by_builder").fill_null(False))
    )
    factories = (
        first.filter(pl.col("kind") == "factory")
        .join(
            created.rename({"created_by": "builder_id"}).drop("team"),
            on=["replay", "builder_id", "unit"],
            how="left",
        )
        .group_by(decision, maintain_order=True)
        .agg(
            pl.col("kind", "builders", "builder_kind").first(),
            (pl.col("created_frame") >= pl.col("frame")).any().alias("by_builder"),
        )
        .with_columns(pl.col("by_builder").fill_null(False))
        .select(
            *decision,
            "kind",
            "builders",
            "builder_kind",
            pl.col("by_builder").alias("matched"),
            "by_builder",
        )
    )
    return pl.concat([structures, factories], how="vertical_relaxed")


def standing_counts(
    events: pl.DataFrame, frames: Sequence[int], roles: Sequence[str], teams: pl.DataFrame
) -> pl.DataFrame:
    """Units per team and type at each of `frames`, from `standing_units()`: one row per
    frame and team, with the columns of the table's ``own`` and ``allies`` groups."""
    names = unit_counts_columns("own", roles)
    found = []
    for frame in sorted(set(frames)):
        units = standing.standing_units(events, frame)
        if units.is_empty():
            continue
        found.append(
            units.with_columns(
                pl.concat_str(
                    pl.lit("own_"),
                    pl.when("finished").then(pl.lit("done")).otherwise(pl.lit("building")),
                    pl.lit("_"),
                    role_expression("unit_def", roles),
                ).alias("column"),
                pl.lit(frame, dtype=pl.Int32).alias("state_frame"),
                pl.col("team").cast(pl.Int32),
            )
            .group_by("state_frame", "team", "column")
            .len()
        )
    long = pl.concat(found)
    wide = long.pivot(on="column", index=["state_frame", "team"], values="len")
    wide = wide.with_columns(
        pl.lit(0).alias(name) for name in names if name not in wide.columns
    ).with_columns(pl.col(names).fill_null(0).cast(pl.Int32))
    side = (
        wide.join(teams, on="team")
        .group_by("state_frame", "ally_team")
        .agg(pl.col(names).sum())
        .rename({name: name.replace("own_", "side_", 1) for name in names})
    )
    return (
        wide.join(teams, on="team")
        .join(side, on=["state_frame", "ally_team"])
        .with_columns(
            (pl.col(name.replace("own_", "side_", 1)) - pl.col(name))
            .cast(pl.Int32)
            .alias(name.replace("own_", "allies_", 1))
            for name in names
        )
        .select("state_frame", "team", *names, *[n.replace("own_", "allies_", 1) for n in names])
    )


def check_game(rows: pl.DataFrame, stem: Path, roles: Sequence[str]) -> dict[str, Any]:
    """Compare the rows of one game with its state tables; counts of rows that differ."""
    game = {
        name: pl.read_parquet(state_tables.table_path(stem, name))
        for name in ("game", "events", "resources")
    }
    events = game["events"].drop("replay")
    teams = (
        game["game"]
        .select("teams")
        .explode("teams")
        .unnest("teams")
        .select(pl.col("team").cast(pl.Int32), pl.col("ally_team").cast(pl.Int32))
    )
    resources = game["resources"].drop("replay").with_columns(pl.col("team").cast(pl.Int32))
    rows = rows.with_columns(
        pl.col("player_slot").cast(pl.Int32).alias("team"),
        (pl.col("state_frame") // GAME_SPEED * GAME_SPEED).alias("second_frame"),
    )
    counts: Counter[str] = Counter(rows=rows.height)
    counts["resources_frame_differs"] = int((rows["resources_frame"] != rows["second_frame"]).sum())
    expected = rows.select("team", "second_frame").join(
        resources.rename({"frame": "second_frame"}),
        on=["team", "second_frame"],
        how="left",
        maintain_order="left",
    )
    differs = np.zeros(rows.height, dtype=bool)
    for name in (*RESOURCES, "wind"):
        differs |= ~(rows[name] == expected[name]).fill_null(False).to_numpy()
    counts["resources_differ"] = int(differs.sum())

    names = unit_counts_columns("own", roles) + unit_counts_columns("allies", roles)
    rebuilt = standing_counts(events, rows["state_frame"].to_list(), roles, teams)
    compared = rows.select("team", "state_frame", *names).join(
        rebuilt, on=["team", "state_frame"], how="left", suffix="_rebuilt", maintain_order="left"
    )
    own_differs = np.zeros(rows.height, dtype=bool)
    allies_differ = np.zeros(rows.height, dtype=bool)
    for name in names:
        same = (compared[name] == compared[name + "_rebuilt"].fill_null(0)).to_numpy()
        if name.startswith("own_"):
            own_differs |= ~same
        else:
            allies_differ |= ~same
    counts["own_units_differ"] = int(own_differs.sum())
    counts["allies_units_differ"] = int(allies_differ.sum())
    counts["rows_with_other_units"] = int(
        (
            rows.select(
                pl.sum_horizontal(pl.col(f"own_done_{OTHER}", f"own_building_{OTHER}"))
            ).to_series()
            > 0
        ).sum()
    )
    return dict(counts)


def ordered_and_created(rows: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    """Per structure order that adds a unit: whether the team created a unit of that type on
    the spot afterwards (within the simulated part), and after how many seconds."""
    created = events.filter(pl.col("kind") == "created").select(
        pl.col("replay").cast(pl.String),
        pl.col("team").cast(pl.Int32),
        pl.col("unit_def").cast(pl.String).alias("unit"),
        pl.col("frame").alias("created_frame"),
        pl.col("x").alias("created_x"),
        pl.col("z").alias("created_z"),
    )
    orders = rows.filter(pl.col("kind") == "structure", pl.col("count") > 0).select(
        "replay",
        "match_id",
        pl.col("player_slot").cast(pl.Int32).alias("team"),
        "order_index",
        "step_idx",
        "unit",
        "frame",
        "x",
        "z",
    )
    matched = (
        orders.join(created, on=["replay", "team", "unit"], how="left")
        .filter(
            pl.col("created_frame").is_null()
            | (
                (pl.col("created_frame") >= pl.col("frame"))
                & ((pl.col("created_x") - pl.col("x")).abs() <= SPOT_DISTANCE)
                & ((pl.col("created_z") - pl.col("z")).abs() <= SPOT_DISTANCE)
            )
        )
        .group_by("replay", "team", "order_index", maintain_order=True)
        .agg(pl.col("step_idx").first(), pl.col("frame").first(), pl.col("created_frame").min())
    )
    return orders.select("replay", "team", "order_index").join(
        matched, on=["replay", "team", "order_index"], how="left", maintain_order="left"
    )


def factory_orders_and_units(rows: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    """Per team and unit type ordered from a factory: units ordered in the opening, and units
    of that type the team created from its first such order to the end of the state."""
    ordered = (
        rows.filter(pl.col("kind") == "factory", pl.col("count") > 0)
        .group_by("replay", pl.col("player_slot").cast(pl.Int32).alias("team"), "unit")
        .agg(pl.col("count").sum().alias("ordered"), pl.col("frame").min().alias("first_order"))
    )
    created = events.filter(pl.col("kind") == "created").select(
        pl.col("replay").cast(pl.String),
        pl.col("team").cast(pl.Int32),
        pl.col("unit_def").cast(pl.String).alias("unit"),
        "frame",
    )
    return (
        ordered.join(created, on=["replay", "team", "unit"], how="left")
        .group_by("replay", "team", "unit", "ordered", "first_order")
        .agg((pl.col("frame") >= pl.col("first_order")).sum().alias("created"))
    )


def check(directory: Path, states: Path, games: int, seed: int) -> str:
    manifest = json.loads((directory / "manifest.json").read_text())
    roles = manifest["unit_roles"]["roles"]
    table_games = pl.read_parquet(directory / "games.parquet").filter(pl.col("status") == "ok")
    chosen = sorted(
        random.Random(seed).sample(
            table_games["match_id"].to_list(), min(games, table_games.height)
        )
    )
    rows = load_rows(directory, chosen)
    with_builders = "builder_index" in rows.columns
    totals: Counter[str] = Counter()
    structure_parts, factory_parts, builder_parts = [], [], []
    for match_id in chosen:
        all_rows = rows.filter(pl.col("match_id") == match_id)
        # one row per decision, and only build orders, for the checks of the first table
        game_rows = (
            all_rows.filter(pl.col("builder_index") == 0, pl.col("kind") != "job")
            if with_builders
            else all_rows
        )
        replay = game_rows["replay"][0]
        stem = state_stem(states, replay)
        totals.update(check_game(game_rows, stem, roles))
        events = pl.read_parquet(state_tables.table_path(stem, "events"))
        structure_parts.append(ordered_and_created(game_rows, events))
        factory_parts.append(factory_orders_and_units(game_rows, events))
        if with_builders:
            builder_parts.append(builders_and_creators(all_rows, events))

    lines = [
        f"{len(chosen)} games of `{manifest['name']}` (built {manifest['built_at']}), "
        f"{totals['rows']} rows.",
        "",
        "## The join",
        "",
    ]
    lines += markdown.table(
        ["check", "rows that differ"],
        [
            [
                "resources line is the one of the second before the order",
                totals["resources_frame_differs"],
            ],
            ["resources and wind equal that line", totals["resources_differ"]],
            ["own units equal `standing_units()`", totals["own_units_differ"]],
            ["allies' units equal `standing_units()`", totals["allies_units_differ"]],
        ],
    )
    lines += [
        "",
        f"Rows where the team has a unit of a type outside the table's types (`{OTHER}`): "
        f"{totals['rows_with_other_units']}.",
    ]

    structures = pl.concat(structure_parts)
    lines += ["", "## Ordered and created", ""]
    rows_out = []
    for label, part in (
        ("all structure orders", structures),
        ("orders that start one of the first 30 steps", structures.filter(pl.col("step_idx") < 30)),
    ):
        found = part.filter(pl.col("created_frame").is_not_null())
        part_delays = (found["created_frame"] - found["frame"]) / GAME_SPEED
        rows_out.append(
            [
                label,
                part.height,
                f"{100 * found.height / max(part.height, 1):.1f}%",
                f"{part_delays.median():.0f} s" if found.height else "-",
                f"{part_delays.quantile(0.9):.0f} s" if found.height else "-",
            ]
        )
    lines += markdown.table(
        ["orders", "count", "created on the spot", "median delay", "p90 delay"], rows_out
    )
    factories = pl.concat(factory_parts)
    ordered = int(factories["ordered"].sum())
    created = int(factories["created"].sum())
    lines += [
        "",
        f"Factory orders: {ordered} units ordered in the openings, {created} units of the "
        f"ordered types created by the same teams from the first such order to the end of the "
        f"simulated 10 minutes ({100 * created / max(ordered, 1):.0f}%; quota and repeat "
        "orders can order more than gets built, and later orders add to what is created).",
    ]
    if builder_parts:
        lines += builder_lines(pl.concat(builder_parts, how="vertical_relaxed"))
    return "\n".join(lines)


def builder_lines(found: pl.DataFrame) -> list[str]:
    """The table of `builders_and_creators` over some games."""
    lines = ["", "## The builders", ""]
    rows = []
    for (kind, builder_kind), part in sorted(
        found.group_by("kind", "builder_kind"), key=lambda item: str(item[0])
    ):
        matched = part.filter("matched")
        single = matched.filter(pl.col("builders") == 1)
        rows.append(
            [
                kind,
                builder_kind,
                part.height,
                f"{100 * matched.height / max(part.height, 1):.1f}%",
                f"{100 * matched['by_builder'].mean():.1f}%" if matched.height else "-",
                f"{100 * single['by_builder'].mean():.1f}%" if single.height else "-",
            ]
        )
    lines += markdown.table(
        [
            "order",
            "builder",
            "orders",
            "something built for it",
            "built by one of its builders",
            "the same, orders to one builder",
        ],
        rows,
    )
    lines += [
        "",
        "A structure counts as built for an order when the team created a unit of its type "
        f"within {SPOT_DISTANCE} map units of the order's spot after it; the unit that "
        "started it is in its `created` line. A factory order counts when its factory "
        "created a unit of that type after it.",
    ]
    return lines


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--table", type=Path, default=dataset_dir(), help="the decision table")
    parser.add_argument("--state-dir", type=Path, default=state_dir())
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)


def run(args: argparse.Namespace) -> int:
    print(check(args.table, args.state_dir, args.games, args.seed))
    return 0
