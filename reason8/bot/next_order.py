"""What the in-game AI needs when the model decides builders' next orders (ADR 0019).

Usage::

    uv run reason8 bot export-next-order --data-dir data/bar \\
        --game "Beyond All Reason test-32018-ad135b9"

With the AI option ``builder_orders=model`` the bot, as one player, consults the model
about the next order of every idle builder during the opening (``ai/native/NextOrder.cpp``,
``script/hard/reason8/next_order.as``), as a person notices an idle builder and gives it
something to do. The export writes two files for it, all measured on the training split:

``ai/Reason8/next_order.json``, which stays:

- **The usual metal spots** (``metal_spots``): for each map and start position, the
  metal spots its players usually take, in the order they usually take them
  (`usual_metal_spots`), from the extractor orders of the openings (``openings_v2``).
  Openings whose first buildings are further than ``BUILT_AWAY_DISTANCE`` from their
  player's start are left out (`near_their_start`): their players started at another
  place than the replay says, so their spots are another position's. Extractors the
  model orders go there; where there is none, BARb places them.
- **BARb's task for each structure** (``tasks``), from the game's unit files
  (`reason8.game.unitdefs.build_task`): an order with no task cannot be carried out.

``ai/Reason8/stand_in.json``, which goes when the learned model is in:

- **The stand-in model** (``rows``): NOT the learned model. For each builder unit and
  minute of the opening window, how often the players' builders of that unit got each
  answer in that minute (`stand_in_rows`), from the decision table (``context_v2``). It
  knows nothing of the game state; it stands in for the trees of ADR 0019 until they are
  in, so that the next orders, the mask and the choice can be played.

Every number is an aggregate over many players; nothing names a player or a game.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.neighbors import KDTree

from reason8.game.unitdefs import UnitDef, build_task, game_unit_defs
from reason8.openings.dataset import BUILT_AWAY_DISTANCE, INCLUDED, first_places_distances
from reason8.paths import REPO_ROOT, data_dir

DEFAULT_OUT_DIR = REPO_ROOT / "ai" / "Reason8"
NEXT_ORDER_NAME = "next_order.json"
STAND_IN_NAME = "stand_in.json"  # temporary: until the learned model is in
# The opening window of ADR 0012: the stand-in answers for each of its minutes.
MINUTES = 8
# A builder unit's minute with fewer rows takes the builder's answers over the whole
# window; a builder unit with fewer rows in the whole window gets no answers (BARb decides).
MIN_ROWS = 200
# The stand-in keeps at most this many answers per row, each at least this likely: the
# rest could not be chosen at the threshold of 10% anyway, and only rescaling needs them.
MAX_ANSWERS = 12
MIN_PROBABILITY = 0.01
# Extractor orders closer than this are on one metal spot: spots are hundreds of units
# apart, and the game snaps an extractor to its spot.
SPOT_RADIUS = 64.0
CELL = 16.0  # the grid the orders are counted on before they are merged into spots
# A spot is usual for a position when at least this share of its openings take it.
USUAL_SHARE = 0.25
# Positions with fewer openings get no usual spots.
MIN_OPENINGS = 20


def stand_in_rows(rows: pl.DataFrame | pl.LazyFrame) -> list[dict]:
    """The stand-in's table from decision table rows (``builder_unit``, ``answer``,
    ``time_s``): per builder unit and minute of the opening window, the share of its rows
    with each answer, at most `MAX_ANSWERS` of at least `MIN_PROBABILITY`, most likely first.
    A minute with fewer than `MIN_ROWS` rows takes the builder unit's whole window."""
    answered = (
        rows.lazy()
        .filter(pl.col("answer").is_not_null(), pl.col("builder_unit").is_not_null())
        .select(
            "builder_unit",
            "answer",
            minute=(pl.col("time_s") // 60).cast(pl.Int32).clip(0, MINUTES - 1),
        )
        .collect()
    )
    per_minute = answered.group_by("builder_unit", "minute", "answer").len()
    whole = answered.group_by("builder_unit", "answer").len()
    totals = whole.group_by("builder_unit").agg(pl.col("len").sum().alias("total"))
    kept_units = sorted(totals.filter(pl.col("total") >= MIN_ROWS)["builder_unit"].to_list())

    def shares(counts: pl.DataFrame) -> dict[str, float]:
        total = counts["len"].sum()
        ordered = counts.with_columns(share=pl.col("len") / total).sort(
            ["share", "answer"], descending=[True, False]
        )
        return {
            row["answer"]: round(row["share"], 4)
            for row in ordered.head(MAX_ANSWERS).iter_rows(named=True)
            if row["share"] >= MIN_PROBABILITY
        }

    table = []
    for unit in kept_units:
        unit_whole = whole.filter(pl.col("builder_unit") == unit)
        for minute in range(MINUTES):
            counts = per_minute.filter(pl.col("builder_unit") == unit, pl.col("minute") == minute)
            rows_in_minute = int(counts["len"].sum())
            source = counts if rows_in_minute >= MIN_ROWS else unit_whole
            table.append(
                {
                    "builder": unit,
                    "minute": minute,
                    "rows": int(source["len"].sum()),
                    "whole_window": rows_in_minute < MIN_ROWS,
                    "answers": shares(source),
                }
            )
    return table


def _spot_centres(points: pl.DataFrame) -> list[tuple[float, float]]:
    """Metal spots of one map from extractor orders (``x``, ``z``).

    The grid cells with the most orders come first: each joins a spot within `SPOT_RADIUS`
    or starts one. Then, twice, every order goes to its nearest spot, a spot moves to the
    median of its orders, and of two spots closer than `SPOT_RADIUS` the one with fewer
    orders is dropped: players place an extractor a little off its spot's centre, and
    the first spots can lie between two such places."""
    cells = (
        points.select(
            cell_x=(pl.col("x") / CELL).round().cast(pl.Int32),
            cell_z=(pl.col("z") / CELL).round().cast(pl.Int32),
        )
        .group_by("cell_x", "cell_z")
        .len()
        .sort(["len", "cell_x", "cell_z"], descending=[True, False, False])
    )
    spots = _apart([(cell_x * CELL, cell_z * CELL) for cell_x, cell_z, _ in cells.iter_rows()])
    for _ in range(2):
        moved = (
            _nearest_spot(points, spots)
            .filter(pl.col("spot").is_not_null())
            .group_by("spot")
            .agg(pl.len(), pl.col("x").median(), pl.col("z").median())
            .sort(["len", "spot"], descending=[True, False])
        )
        spots = _apart([(float(x), float(z)) for x, z in moved.select("x", "z").iter_rows()])
    return spots


def _apart(candidates: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The candidates, in order, without those within `SPOT_RADIUS` of one kept before."""
    kept: list[tuple[float, float]] = []
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}  # by SPOT_RADIUS square
    for x, z in candidates:
        bucket_x, bucket_z = int(x // SPOT_RADIUS), int(z // SPOT_RADIUS)
        near = (
            spot
            for dx in (-1, 0, 1)
            for dz in (-1, 0, 1)
            for spot in buckets.get((bucket_x + dx, bucket_z + dz), ())
        )
        if not any((x - sx) ** 2 + (z - sz) ** 2 < SPOT_RADIUS**2 for sx, sz in near):
            kept.append((x, z))
            buckets.setdefault((bucket_x, bucket_z), []).append((x, z))
    return kept


def _nearest_spot(points: pl.DataFrame, spots: list[tuple[float, float]]) -> pl.DataFrame:
    """`points` with ``spot``: the index of the nearest of `spots`, null beyond
    `SPOT_RADIUS` (and when there are none)."""
    if not spots or points.height == 0:
        return points.with_columns(spot=pl.lit(None, dtype=pl.Int32))
    distances, nearest = KDTree(np.array(spots, dtype=np.float64)).query(
        points.select("x", "z").to_numpy().astype(np.float64), k=1
    )
    return points.with_columns(
        spot=pl.Series(np.where(distances[:, 0] <= SPOT_RADIUS, nearest[:, 0], -1)).cast(pl.Int32)
    ).with_columns(spot=pl.when(pl.col("spot") >= 0).then(pl.col("spot")))


def usual_metal_spots(
    orders: pl.DataFrame,
    openings: pl.DataFrame,
    starts: Mapping[tuple[str, str], tuple[float, float]],
) -> list[dict]:
    """Per map and position, the metal spots taken in at least `USUAL_SHARE` of its
    openings, in the order they are usually taken: by the median of the rank each opening
    took them at (the first spot an opening put an extractor on is rank 1), then by how
    many take them.

    `orders` are the extractor orders of the openings (``match_id``, ``player_slot``,
    ``seq_idx``, ``x``, ``z``, ``map``, ``position``), `openings` every opening counted
    (``match_id``, ``player_slot``, ``map``, ``position``), `starts` the start point of each
    (map, position)."""
    counted = openings.group_by("map", "position").agg(pl.len().alias("openings"))
    result = []
    for map_name in sorted(orders["map"].unique().to_list()):
        on_map = orders.filter(pl.col("map") == map_name, pl.col("x").is_not_null())
        centres = _spot_centres(on_map)
        visits = (
            _nearest_spot(on_map, centres)
            .filter(pl.col("spot").is_not_null())
            .sort("match_id", "player_slot", "seq_idx")
            .unique(["match_id", "player_slot", "spot"], keep="first", maintain_order=True)
            .with_columns(rank=pl.int_range(1, pl.len() + 1).over("match_id", "player_slot"))
        )
        for row in counted.filter(pl.col("map") == map_name).sort("position").iter_rows(named=True):
            position, total = row["position"], row["openings"]
            if total < MIN_OPENINGS or (map_name, position) not in starts:
                continue
            spots = (
                visits.filter(pl.col("position") == position)
                .group_by("spot")
                .agg(pl.len().alias("taken"), pl.col("rank").median().alias("median_rank"))
                .with_columns(share=pl.col("taken") / total)
                .filter(pl.col("share") >= USUAL_SHARE)
                .sort(["median_rank", "share", "spot"], descending=[False, True, False])
            )
            if spots.height == 0:
                continue
            start_x, start_z = starts[(map_name, position)]
            result.append(
                {
                    "map": map_name,
                    "position": position,
                    "start": [round(start_x), round(start_z)],
                    "openings": total,
                    "spots": [
                        {
                            "x": round(centres[spot["spot"]][0]),
                            "z": round(centres[spot["spot"]][1]),
                            "share": round(spot["share"], 3),
                            "median_rank": spot["median_rank"],
                        }
                        for spot in spots.iter_rows(named=True)
                    ],
                }
            )
    return result


def structure_tasks(unit_defs: Mapping[str, UnitDef]) -> dict[str, str]:
    """BARb's task type for every structure a task builds, by unit name."""
    return {name: task for name, unit in sorted(unit_defs.items()) if (task := build_task(unit))}


def extractor_names(unit_defs: Mapping[str, UnitDef]) -> list[str]:
    return sorted(name for name, unit in unit_defs.items() if build_task(unit) == "mex")


def near_their_start(
    openings: pl.DataFrame, distances: pl.DataFrame | pl.LazyFrame | None = None
) -> pl.DataFrame:
    """The openings whose first buildings are within `BUILT_AWAY_DISTANCE` of their own
    start, by ``first_places_distance`` (`reason8.openings.dataset.first_places_distances`):
    the column of `openings`, or from `distances` for a dataset built before it had one. An
    opening without the distance (no placed structure) is kept, as the dataset keeps it."""
    if "first_places_distance" not in openings.columns:
        if distances is None:
            raise ValueError("the openings have no first_places_distance and none was given")
        openings = openings.join(
            distances.lazy().collect(), on=["match_id", "player_slot"], how="left"
        )
    distance = pl.col("first_places_distance")
    return openings.filter(distance.is_null() | (distance <= BUILT_AWAY_DISTANCE))


def load_openings(
    dataset: Path, extractors: Iterable[str]
) -> tuple[pl.DataFrame, pl.DataFrame, dict, int]:
    """(extractor orders, openings, start points, openings left out as built away from
    their start) of the training split of the openings dataset, as `usual_metal_spots`
    takes them."""
    games = pl.read_parquet(dataset / "games.parquet", columns=["match_id", "map"])
    included = (
        pl.read_parquet(dataset / "openings.parquet")
        .filter(
            pl.col("status") == INCLUDED,
            pl.col("split") == "train",
            pl.col("position").is_not_null(),
        )
        .join(games, on="match_id")
    )
    distances = None
    if "first_places_distance" not in included.columns:  # a dataset built before it had them
        distances = first_places_distances(
            pl.scan_parquet(dataset / "train.parquet").select(
                "match_id", "player_slot", "seq_idx", "kind", "x", "z"
            ),
            included.select("match_id", "player_slot", "start_x", "start_z"),
        )
    openings = near_their_start(included, distances)
    starts = (
        openings.filter(pl.col("on_spot"))
        .group_by("map", "position")
        .agg(pl.col("start_x").median(), pl.col("start_z").median())
    )
    start_points = {
        (row["map"], row["position"]): (row["start_x"], row["start_z"])
        for row in starts.iter_rows(named=True)
    }
    counted = openings.select("match_id", "player_slot", "map", "position")
    orders = (
        pl.scan_parquet(dataset / "train.parquet")
        .filter(pl.col("unit").is_in(list(extractors)), pl.col("kind") != "factory")
        .select("match_id", "player_slot", "seq_idx", "order_index", "x", "z")
        .collect()
        .join(counted, on=("match_id", "player_slot"))
        .with_columns(seq_idx=pl.coalesce("seq_idx", "order_index"))
        .drop("order_index")
    )
    return orders, counted, start_points, included.height - openings.height


def export_next_order(
    orders: pl.DataFrame,
    openings: pl.DataFrame,
    starts: Mapping[tuple[str, str], tuple[float, float]],
    unit_defs: Mapping[str, UnitDef],
) -> dict:
    """next_order.json: what stays when the learned model is in."""
    return {
        "comment": (
            "Generated by `reason8 bot export-next-order` from the training split: what the "
            "bot uses when the model decides builders' next orders (builder_orders=model). "
            "Do not edit."
        ),
        "metal_spots": usual_metal_spots(orders, openings, starts),
        "tasks": structure_tasks(unit_defs),
    }


def export_stand_in(decision_rows: pl.LazyFrame | pl.DataFrame) -> dict:
    """stand_in.json: the stand-in model, which goes when the learned model is in."""
    return {
        "comment": (
            "Generated by `reason8 bot export-next-order` from the training split. NOT the "
            "learned model: per builder unit and minute, how often players' builders of that "
            "unit got each answer in that minute. It stands in for the trees of ADR 0019 "
            "until they are in, and this file goes then. Do not edit."
        ),
        "rows": stand_in_rows(decision_rows),
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir", required=True, help="content dir with the game (reason8 headless setup)"
    )
    parser.add_argument("--game", required=True, help="the game version the AI will play")
    parser.add_argument("--context", type=Path, default=None, help="default: context_v2")
    parser.add_argument("--dataset", type=Path, default=None, help="default: openings_v2")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"where {NEXT_ORDER_NAME} and {STAND_IN_NAME} go (default: ai/Reason8)",
    )


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    context = args.context or data_dir() / "datasets" / "context_v2"
    dataset = args.dataset or data_dir() / "datasets" / "openings_v2"
    unit_defs = game_unit_defs(Path(args.data_dir).resolve(), args.game)
    orders, openings, starts, built_away = load_openings(dataset, extractor_names(unit_defs))
    next_order = export_next_order(orders, openings, starts, unit_defs)
    rows = pl.scan_parquet(context / "train.parquet").select("builder_unit", "answer", "time_s")
    stand_in = export_stand_in(rows)
    write(args.out_dir / NEXT_ORDER_NAME, next_order)
    write(args.out_dir / STAND_IN_NAME, stand_in)
    print(
        f"{built_away} openings built away from their start left out; "
        f"{len(next_order['metal_spots'])} positions with usual metal spots, "
        f"{len(next_order['tasks'])} structures -> {args.out_dir / NEXT_ORDER_NAME}; "
        f"{len(stand_in['rows'])} stand-in rows -> {args.out_dir / STAND_IN_NAME}"
    )
    return 0


# --- the log of a game in which the model decided builders' orders (`reason8 bot check`)

DECIDED = re.compile(
    r"frame (\d+): (\w+) (\d+) (\w+): "
    r"(model chose|below threshold|nothing possible|no answers)(?: (\w+) [\d.]+)?"
)
NOT_CARRIED_OUT = re.compile(
    r"frame (\d+): (\w+) (\d+) (\w+): cannot carry out (\w+): (.*); left to BARb"
)
ON_SPOT = re.compile(r"frame \d+: \w+ \d+: \w+ on (usual spot|BARb's metal spot)")
MODEL = re.compile(r"model (\S+) .*?, (\d+) rows for (\d+) builder units")
POSITION = re.compile(r"position (\S+) \(start .*?\), (\d+) usual metal spots")
ENDED = re.compile(r"model orders ended at frame (\d+), (\w+): (.*); BARb takes over")
UNFINISHED = "its task ended unfinished"
FRAMES_PER_MINUTE = 30 * 60
OUTCOMES = ("model chose", "below threshold", "nothing possible", "no answers")


def new_team() -> dict:
    return {
        "model": None,
        "model_rows": None,
        "position": None,
        "usual_spots": 0,
        "idle_builders": 0,  # times an idle builder needed an order and the model was consulted
        "outcomes": dict.fromkeys(OUTCOMES, 0),
        "not_given": 0,  # chosen, but no task could be made for it
        "unfinished": 0,  # chosen and given, but its task ended unfinished
        "not_given_reasons": {},
        "by_kind": {},
        "by_minute": [],
        "orders_chosen": {},
        "extractors": {"usual spot": 0, "BARb's metal spot": 0},
        "ended": None,
    }


def count_line(teams: dict[int, dict], team: int, text: str) -> None:
    """Add one ``Reason8 next order: team N: <text>`` log line to its team's counts."""
    counts = teams.setdefault(team, new_team())
    if decided := DECIDED.match(text):
        frame, kind, outcome, order = (
            int(decided.group(1)),
            decided.group(4),
            decided.group(5),
            decided.group(6),
        )
        counts["idle_builders"] += 1
        counts["outcomes"][outcome] += 1
        by_kind = counts["by_kind"].setdefault(kind, {"idle_builders": 0, "model_chose": 0})
        by_kind["idle_builders"] += 1
        minute = frame // FRAMES_PER_MINUTE
        while len(counts["by_minute"]) <= minute:
            counts["by_minute"].append({"idle_builders": 0, "left_to_barb": 0})
        counts["by_minute"][minute]["idle_builders"] += 1
        if outcome == "model chose":
            by_kind["model_chose"] += 1
            counts["orders_chosen"][order] = counts["orders_chosen"].get(order, 0) + 1
        else:
            counts["by_minute"][minute]["left_to_barb"] += 1
    elif failed := NOT_CARRIED_OUT.match(text):
        reason = failed.group(6)
        if reason == UNFINISHED:
            counts["unfinished"] += 1
            return
        counts["not_given"] += 1
        counts["not_given_reasons"][reason] = counts["not_given_reasons"].get(reason, 0) + 1
        minute = int(failed.group(1)) // FRAMES_PER_MINUTE
        if minute < len(counts["by_minute"]):
            counts["by_minute"][minute]["left_to_barb"] += 1
    elif spot := ON_SPOT.match(text):
        counts["extractors"][spot.group(1)] += 1
    elif model := MODEL.match(text):
        counts["model"], counts["model_rows"] = model.group(1), int(model.group(2))
    elif position := POSITION.search(text):
        counts["position"], counts["usual_spots"] = position.group(1), int(position.group(2))
    elif ended := ENDED.match(text):
        counts["ended"] = {
            "frame": int(ended.group(1)),
            "reason": ended.group(2),
            "detail": ended.group(3),
        }


def summary(counts: Mapping) -> dict:
    """One team's counts with the shares a reader looks for: of the idle builders, how many
    got an order the model decided and that was carried out, and how many were left to
    BARb."""
    idle = counts["idle_builders"]
    chosen = counts["outcomes"]["model chose"]
    left = idle - chosen + counts["not_given"]

    def share(part: int) -> float | None:
        return round(part / idle, 3) if idle else None

    return {
        **counts,
        "orders_chosen": dict(
            sorted(counts["orders_chosen"].items(), key=lambda item: (-item[1], item[0]))
        ),
        "decided_by_model": chosen - counts["not_given"],
        "decided_by_model_share": share(chosen - counts["not_given"]),
        "left_to_barb": left,
        "left_to_barb_share": share(left),
    }
