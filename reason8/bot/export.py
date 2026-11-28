"""Export the next-build model's openings for the in-game AI: ai/Reason8/openings.json.

Usage::

    uv run reason8 bot export --data-dir data/bar \\
        --game "Beyond All Reason test-32018-ad135b9"

The model (`reason8 baseline`, ADR 0013) gives the probability of the next step of an
opening; the AI needs fixed build orders per map, start position and faction. Taking the
most likely step again and again does not give one: after a few wind generators another one
is always the most likely step, so the decoded opening never ends. Instead, for every map,
position and faction, the export scores the human openings of the training split by how
likely the model finds their first `SCORED_STEPS` steps, and keeps the most likely one and
`VARIANTS` - 1 more drawn at random from the more likely half; the AI picks one per game.
They are typical openings of the position, and real ones: each ends at its player's first
contact, and its drags and factory queues have real lengths. One opening per position played
every game was easy to tell from human openings (docs/reference/evaluation.md).

The opening is turned into what the AI plays (`reason8/bot/build.py`, ``opening.as``):

- every structure, in order, for the commander; a drag of five extractors is five steps;
- the units of the first factory it builds, in order, a factory order with shift (five
  units) being five units. Units of a second factory, units that factory cannot make, and
  structures no BARb task builds (walls, mines) are dropped and counted in ``dropped``;
- the BARb task type of each structure, from the game's unit files
  (`reason8.game.unitdefs`);
- the start position: where the players of that position started, the median of the starts
  on its spot, so the AI can tell its own position from its commander's place. An opening
  whose first places are further than ``BUILT_AWAY_DISTANCE`` from it is not exported for
  the position (`is_near_start`).

Only Armada and Cortex are exported: BARb's configs open Legion games with Armada's
extractor.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from reason8.game.unitdefs import UnitDef, build_task, game_unit_defs
from reason8.models.ngram import NgramModel, OpeningSteps, load_model, models_dir
from reason8.openings.dataset import (
    BUILT_AWAY_DISTANCE,
    FIRST_PLACES,
    INCLUDED,
    step_starts,
)
from reason8.paths import REPO_ROOT, data_dir

DEFAULT_OUT = REPO_ROOT / "ai" / "Reason8" / "openings.json"
EXPORTED_FACTIONS = ("Armada", "Cortex")
# How many steps of a candidate opening are scored. Shorter openings are not candidates.
SCORED_STEPS = 15
# At most this many candidates per map, position and faction are scored, drawn at random:
# enough to find a typical opening, and the whole training split would take half an hour.
MAX_CANDIDATES = 2000
# Openings per map, position and faction. Humans at one position rarely play the same
# opening twice; one opening per position made the bot easy to tell from them.
VARIANTS = 5
# The bot's reaction delays (ADR 0008): the 30-40 skill band, quantiles of the measured
# delays, and the least events of the band a phase needs before every band's are used.
SKILL_LOW, SKILL_HIGH = 30.0, 40.0
REACTION_QUANTILES = 19
MIN_REACTIONS = 200
# The commander builds at most this many structures of the opening, its first factory
# among them: when the factory comes later, it follows the first ones. Humans share long
# openings with their first constructors (a tech position drags lines of 100 wind
# generators); the AI's constructors are BARb's, so the commander keeps the start of it.
MAX_COMMANDER_STRUCTURES = 30
# Unit name prefixes of the exported factions: an opening that orders another faction's
# units belongs to a player whose faction was told wrong, and is not a candidate.
FACTION_PREFIXES = {"Armada": "arm", "Cortex": "cor"}


@dataclass(frozen=True)
class Step:
    """One step of an opening: a unit and how many of it (buildings of a drag, or units
    of a factory order)."""

    unit: str
    kind: str
    amount: int
    # where each building of a structure step was placed, in map units
    places: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class Candidate:
    match_id: int
    player_slot: int
    steps: tuple[Step, ...]


def with_steps(rows: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    """Order rows that add units, numbered by step (`reason8.openings.dataset.step_starts`):
    the orders of one step share its number."""
    return (
        rows.lazy()
        .sort("match_id", "player_slot", "seq_idx")
        .with_columns(step=step_starts().cast(pl.Int32).cum_sum().over("match_id", "player_slot"))
    )


def opening_steps(rows: pl.DataFrame) -> tuple[Step, ...]:
    """The steps of one opening from its order rows that add units, in order: a drag of
    buildings is one step of several, a factory order with shift one step of five units."""
    one_opening = rows.with_columns(
        match_id=pl.lit(0), player_slot=pl.lit(0), seq_idx=pl.int_range(pl.len())
    )
    numbered = with_steps(one_opening).collect()
    return tuple(_steps_of(numbered).row(0, named=True)["steps"])


def _steps_of(numbered: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame:
    """One row per opening with its steps as a list of Step."""
    added = (
        pl.when(pl.col("kind") == "factory")
        .then(pl.col("count").fill_null(1).clip(lower_bound=1))
        .otherwise(1)
    )
    grouped = (
        numbered.lazy()
        .with_columns(added=added)
        .group_by("match_id", "player_slot", "step", maintain_order=True)
        .agg(pl.col("unit", "kind").first(), pl.col("added").sum(), pl.col("x", "z"))
        .group_by("match_id", "player_slot", maintain_order=True)
        .agg(pl.col("unit"), pl.col("kind"), pl.col("added"), pl.col("x"), pl.col("z"))
        .collect()
    )

    def places(xs: list | None, zs: list | None) -> tuple[tuple[float, float], ...]:
        return tuple(
            (float(x), float(z)) for x, z in zip(xs or [], zs or [], strict=True) if x is not None
        )

    steps = [
        [
            Step(unit, kind, int(amount), places(step_xs, step_zs) if kind != "factory" else ())
            for unit, kind, amount, step_xs, step_zs in zip(
                units, kinds, amounts, xs, zs, strict=True
            )
        ]
        for units, kinds, amounts, xs, zs in zip(
            *(grouped[column].to_list() for column in ("unit", "kind", "added", "x", "z")),
            strict=True,
        )
    ]
    return grouped.select("match_id", "player_slot").with_columns(
        steps=pl.Series(steps, dtype=pl.Object)
    )


def load_candidates(
    dataset: Path, seed: int = 0
) -> tuple[dict[tuple[str, str, str], list[Candidate]], dict]:
    """Up to `MAX_CANDIDATES` training openings of each (map, position, faction), and the
    median start point of each (map, position) on its spot."""
    games = pl.read_parquet(dataset / "games.parquet", columns=["match_id", "map"])
    openings = (
        pl.read_parquet(dataset / "openings.parquet")
        .filter(
            pl.col("status") == INCLUDED,
            pl.col("split") == "train",
            pl.col("faction").is_in(EXPORTED_FACTIONS),
            pl.col("position").is_not_null(),
        )
        .join(games, on="match_id")
    )
    starts = (
        openings.filter(pl.col("on_spot"))
        .group_by("map", "position")
        .agg(pl.col("start_x").median(), pl.col("start_z").median())
    )
    start_points = {
        (row["map"], row["position"]): (row["start_x"], row["start_z"])
        for row in starts.iter_rows(named=True)
    }
    chosen = (
        openings.sample(fraction=1.0, shuffle=True, seed=seed)
        .with_columns(rank=pl.int_range(pl.len()).over("map", "position", "faction"))
        .filter(pl.col("rank") < MAX_CANDIDATES)
        .select("match_id", "player_slot", "map", "position", "faction")
    )
    rows = (
        pl.scan_parquet(dataset / "train.parquet")
        .select(
            "match_id",
            "player_slot",
            "seq_idx",
            "frame",
            "unit",
            "kind",
            "count",
            "x",
            "z",
        )
        .filter(pl.col("seq_idx").is_not_null())
        .join(chosen.lazy().select("match_id", "player_slot"), on=("match_id", "player_slot"))
    )
    by_opening = _steps_of(with_steps(rows)).join(chosen, on=("match_id", "player_slot"))
    candidates: dict[tuple[str, str, str], list[Candidate]] = {}
    for row in by_opening.sort("match_id", "player_slot").iter_rows(named=True):
        prefix = FACTION_PREFIXES[row["faction"]]
        if not all(step.unit.startswith(prefix) for step in row["steps"]):
            continue
        key = (row["map"], row["position"], row["faction"])
        candidates.setdefault(key, []).append(
            Candidate(int(row["match_id"]), int(row["player_slot"]), tuple(row["steps"]))
        )
    return candidates, start_points


def log_likelihood(
    model: NgramModel, map_name: str, position: str, faction: str, units: Sequence[str]
) -> float:
    """Log-probability of the first `SCORED_STEPS` steps under the model."""
    opening = OpeningSteps(0, faction, map_name, position, None, None, None, tuple(units))
    total = 0.0
    for index, unit in enumerate(units[:SCORED_STEPS]):
        probabilities = model.distribution(opening, index)
        total += math.log(probabilities[model.index.get(unit, len(model.vocabulary) - 1)])
    return total


def typical_openings(
    model: NgramModel,
    key: tuple[str, str, str],
    candidates: Sequence[Candidate],
    count: int = VARIANTS,
    seed: int = 0,
) -> tuple[list[tuple[Candidate, float]], int]:
    """`count` candidates drawn at random from the half the model finds most likely, with
    their log-likelihoods (the most likely first), and how many were scored."""
    scored = [
        (log_likelihood(model, *key, [step.unit for step in candidate.steps]), candidate)
        for candidate in candidates
        if len(candidate.steps) >= SCORED_STEPS
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1].match_id, pair[1].player_slot))
    likely = scored[: max(len(scored) // 2, 1)] if scored else []
    generator = random.Random(f"{seed}:{':'.join(key)}")
    drawn = (
        [likely[0]] + generator.sample(likely[1:], min(count - 1, len(likely) - 1))
        if likely
        else []
    )
    return [(candidate, score) for score, candidate in drawn], len(scored)


def ai_opening(steps: Sequence[Step], unit_defs: Mapping[str, UnitDef]) -> dict:
    """What the AI plays for one opening: the commander's structures, the first factory's
    units, the task type of each structure and what was dropped."""
    commander: list[str] = []
    places: list[list[int] | None] = []
    tasks: dict[str, str] = {}
    first_factory: str | None = None
    factory_units: list[str] = []
    dropped = {
        "no task": 0,
        "not in the first factory": 0,
        "unknown unit": 0,
        "after the commander's last structure": 0,
    }
    for step in steps:
        unit = unit_defs.get(step.unit)
        if unit is None:
            dropped["unknown unit"] += step.amount
            continue
        if step.kind == "factory":
            if first_factory is not None and step.unit in unit_defs[first_factory].build_options:
                factory_units += [step.unit] * step.amount
            else:
                dropped["not in the first factory"] += step.amount
            continue
        task = build_task(unit)
        if task is None:
            dropped["no task"] += step.amount
            continue
        is_first_factory = task == "factory" and first_factory is None
        if is_first_factory:
            first_factory = step.unit
        # the first factory always gets a place: the structures before it leave one for it
        limit = MAX_COMMANDER_STRUCTURES - (0 if first_factory else 1)
        room = max(limit - len(commander), 1 if is_first_factory else 0)
        if room <= 0:
            dropped["after the commander's last structure"] += step.amount
            continue
        tasks[step.unit] = task
        taken = min(step.amount, room)
        commander += [step.unit] * taken
        places += [[round(x), round(z)] for x, z in step.places[:taken]] + [None] * (
            taken - len(step.places[:taken])
        )
        dropped["after the commander's last structure"] += max(step.amount - room, 0)
    return {
        "commander": commander,
        "places": places,
        "factories": {first_factory: factory_units} if first_factory else {},
        "tasks": tasks,
        "dropped": {reason: count for reason, count in dropped.items() if count},
    }


def first_places_distance(
    places: Sequence[Sequence[float] | None], start: Sequence[float]
) -> float | None:
    """From `start` to the nearest of the first `FIRST_PLACES` known places of an opening's
    commander structures; None when none is known."""
    known = [place for place in places if place][:FIRST_PLACES]
    return min((math.dist(place, start) for place in known), default=None)


def is_near_start(played: Mapping, start: Sequence[float]) -> bool:
    """Whether an opening the AI plays (`ai_opening`) starts where it is exported for: its
    first places are within `BUILT_AWAY_DISTANCE` of the position's start."""
    distance = first_places_distance(played["places"], start)
    return distance is None or distance <= BUILT_AWAY_DISTANCE


def export(
    model: NgramModel,
    candidates: Mapping[tuple[str, str, str], list[Candidate]],
    start_points: Mapping[tuple[str, str], tuple[float, float]],
    unit_defs: Mapping[str, UnitDef],
) -> dict:
    """The openings file."""
    tasks: dict[str, str] = {}
    openings = []
    for key in sorted(candidates):
        map_name, position, faction = key
        if (map_name, position) not in start_points:
            continue
        start_x, start_z = start_points[(map_name, position)]
        # an opening built at another place than the position's start is not one of it
        near = [
            candidate
            for candidate in candidates[key]
            if is_near_start(ai_opening(candidate.steps, unit_defs), (start_x, start_z))
        ]
        chosen, scored = typical_openings(model, key, near)
        for variant, (candidate, score) in enumerate(chosen):
            played = ai_opening(candidate.steps, unit_defs)
            tasks.update(played.pop("tasks"))
            openings.append(
                {
                    "side": faction.lower(),
                    "map": map_name,
                    "position": position,
                    "variant": variant,
                    "start": [round(start_x), round(start_z)],
                    "candidates": scored,
                    "log_likelihood": round(score, 3),
                    **played,
                }
            )
    return {
        "comment": (
            "Generated by `reason8 bot export`: per map, start position and faction, "
            f"{VARIANTS} training openings from the half the next-build model finds most "
            "likely, the most likely first. The AI picks one per game. Do not edit."
        ),
        "model": model.name,
        "tasks": dict(sorted(tasks.items())),
        "openings": openings,
    }


def reaction_table(idle: pl.DataFrame, low: float = SKILL_LOW, high: float = SKILL_HIGH) -> dict:
    """The bot's reaction delays (ADR 0008): per kind of unit and phase of the game, the share
    of idle events players of the skill band answered with a click within the horizon, and
    `REACTION_QUANTILES` quantiles of those delays in seconds (`reason8 analysis reactions`).
    A phase with fewer than `MIN_REACTIONS` events of the band takes every band's."""
    from reason8.analysis.reactions import KINDS, PHASES

    idle = idle.with_columns(
        delay=(pl.col("clicked_frame") - pl.col("frame")) / 30, seconds=pl.col("frame") / 30
    )
    shares = [index / (REACTION_QUANTILES + 1) for index in range(1, REACTION_QUANTILES + 1)]
    table: dict[str, list[dict]] = {}
    for kind in KINDS:
        rows = []
        for _, first, end in PHASES:
            part = idle.filter(
                pl.col("kind") == kind, pl.col("seconds") >= first, pl.col("seconds") < end
            )
            band = part.filter(pl.col("skill") >= low, pl.col("skill") < high)
            if band.height >= MIN_REACTIONS:
                part = band
            answered = part.filter(pl.col("delay").is_not_null())["delay"]
            rows.append(
                {
                    "until_seconds": end,
                    "events": part.height,
                    "answered": round(answered.len() / part.height, 3) if part.height else 0.0,
                    "quantiles": [
                        round(float(answered.quantile(share, interpolation="linear")), 1)
                        for share in shares
                    ]
                    if answered.len()
                    else [],
                }
            )
        table[kind] = rows
    return table


def batch_sizes(idle: pl.DataFrame, low: float = SKILL_LOW, high: float = SKILL_HIGH) -> dict:
    """Per kind of unit, how many units a player's idle unit started between two idle
    events, on average: how much one look at it keeps it busy (ADR 0008, queue ahead)."""
    from reason8.analysis.reactions import KINDS

    sizes = {}
    for kind in KINDS:
        part = idle.filter(pl.col("kind") == kind)
        band = part.filter(pl.col("skill") >= low, pl.col("skill") < high)
        part = band if band.height >= MIN_REACTIONS else part
        mean = part["started"].mean() if part.height else None
        sizes[kind] = round(max(float(mean), 1.0), 2) if mean is not None else 1.0
    return sizes


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir", required=True, help="content dir with the game (reason8 headless setup)"
    )
    parser.add_argument("--game", required=True, help="the game version the AI will play")
    parser.add_argument("--model", type=Path, default=None, help="default: models/ngram_v2.json")
    parser.add_argument("--dataset", type=Path, default=None, help="default: openings_v2")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--reactions",
        type=Path,
        help="idle events (reason8 analysis reactions); default: <data dir>/reactions/idle.parquet",
    )


def run(args: argparse.Namespace) -> int:
    model = load_model(args.model or models_dir() / "ngram_v2.json")
    if not isinstance(model, NgramModel):
        raise SystemExit("the export needs an n-gram model")
    dataset = args.dataset or data_dir() / "datasets" / "openings_v2"
    candidates, start_points = load_candidates(dataset)
    unit_defs = game_unit_defs(Path(args.data_dir).resolve(), args.game)
    document = export(model, candidates, start_points, unit_defs)
    reactions = args.reactions or data_dir() / "reactions" / "idle.parquet"
    if reactions.is_file():
        idle = pl.read_parquet(reactions)
        document["reactions"] = reaction_table(idle)
        document["batches"] = batch_sizes(idle)
        document["reactions_band"] = [SKILL_LOW, SKILL_HIGH]
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"{len(document['openings'])} openings -> {args.out}")
    return 0
