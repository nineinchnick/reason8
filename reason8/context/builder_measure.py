"""Measure the builder model's decision table (``context_v2``): what each group adds, per
kind of builder, with the answers a builder cannot give masked.

Usage::

    uv run reason8 context measure                  # validation
    uv run reason8 context measure --split test     # the numbers of docs/research/context.md

The protocol is ADR 0013 on the rows of the table (`reason8.context.table`): a decision is
a build order or a job given to builders, the steps are formed from the decisions of each
player by the rule of the opening models (`reason8.openings.dataset.step_index`, with the
answer: the unit or the job), and the first `SCORED_STEPS` steps of each opening of the
held-out split are scored, with intervals from resampling whole games.

A step is scored in two views:

``ask``
    one row per builder the step's order went to: what the bot does, where every builder
    asks;
``order``
    one row per step, the builder with the most build power standing for it: what the
    player decided once for all the builders they had selected.

The trees (`reason8.context.measure.TreeModel`) are trained on the ask view of the
training games and stopped on that of the validation games. Every model is scored with
the mask of ADR 0019 (`mask_matrix`): the answers the asking builder can never give are
removed and the rest rescaled; the unmasked scores and the probability the mask removes
are reported next to them.

The models (`variants`): the order history alone; with the builder (its kind, its type,
whether it moves, the answer it got before), the reference for the groups; the reference
with each context group added; the inputs of ADR 0019 (`MODEL_GROUPS`), the same without
skill, and the same with a history of one step instead of three. Skill is checked as ADR
0019 asks (`skill_report`), and the risk of repeating the model's own answers by the
model with the shorter history.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from reason8 import markdown
from reason8.context import builders
from reason8.context.measure import CATEGORICAL as HISTORY_CATEGORICAL
from reason8.context.measure import TreeModel, _loss, _percent, default_device
from reason8.context.table import PLAYER, dataset_dir, role_expression
from reason8.models.evaluate import (
    BOOTSTRAP_ROUNDS,
    SCORED_STEPS,
    Scores,
    paired_difference,
    ranks,
    summarize,
)
from reason8.models.ngram import START, UNKNOWN
from reason8.openings.dataset import SPLITS, step_index

HISTORY = 3
GAMES_PER_CHUNK = 300
HISTORY_GROUP = "history"
REFERENCE_GROUPS = ("builder",)
#: The inputs of the first model (ADR 0019) besides the order history and the builder.
MODEL_GROUPS = ("time", "economy", "own_units", "build_power", "skill")
#: The groups added one at a time to the reference.
ADDED_GROUPS = ("time", "economy", "own_units", "build_power", "skill", "allies", "wind", "pace")
VIEWS = ("ask", "order")
SKILL_QUANTILES = (0.1, 0.9)
SKILL_BANDS = 3
TOP_ANSWER_SHARE = 0.10  # ADR 0019: the bot samples among answers of at least 10%
#: The trees' settings that differ from the first table's measurement: on the 1.9 million
#: training rows of the whole sample, leaves of a few rows on splits of the categorical
#: history columns made the boosting diverge from the second round (the training loss
#: rose); leaves of at least 50 rows' weight train as on smaller tables.
TREE_PARAMETERS = {"min_child_weight": 50}


@dataclass
class BuilderSteps:
    """The steps of the table in the ask view (one row per step and builder), with their
    features; `groups` maps each group to its columns."""

    frame: pl.DataFrame
    groups: dict[str, list[str]]
    categorical: tuple[str, ...]
    manifest: dict[str, Any]
    answers: pl.DataFrame  # game, builder_unit, answers
    extra: dict[str, Any] = field(default_factory=dict)


def history_features(roles: Sequence[str], history: int = HISTORY) -> list[str]:
    """The order history: what the n-grams know, the step number, and how many units of
    each type and jobs of each kind the player ordered before."""
    return [
        "faction",
        "map",
        "position",
        "role",
        "step_idx",
        "decision_index",
        *[f"previous_{k}" for k in range(1, history + 1)],
        *[f"ordered_{role}" for role in roles],
        *[f"ordered_{job}" for job in builders.JOBS],
    ]


def load_builder_steps(
    directory: Path,
    groups: Sequence[str] | None = None,
    splits: Sequence[str] | None = None,
    games_per_chunk: int = GAMES_PER_CHUNK,
) -> BuilderSteps:
    """The steps of a ``context_v2`` table, one row per builder an order went to, with the
    columns of the context `groups` (default: all of them) and the rows of the `splits`
    (default: all); the order history is always there. The games are read a chunk at a
    time: joining all their decisions with the context columns at once took 13 GB, for 3 GB
    of steps."""
    manifest = json.loads((directory / "manifest.json").read_text())
    roles = manifest["unit_roles"]["roles"]
    loaded = {
        name: list(columns)
        for name, columns in manifest["groups"].items()
        if groups is None or name in groups
    }
    loaded = {HISTORY_GROUP: history_features(roles), **loaded}
    frames = []
    for split, _ in SPLITS:
        if splits is not None and split not in splits:
            continue
        scan = pl.scan_parquet(directory / f"{split}.parquet")
        games = scan.select(pl.col("match_id").unique().sort()).collect()["match_id"].to_list()
        for start in range(0, len(games), games_per_chunk):
            chunk = scan.filter(pl.col("match_id").is_in(games[start : start + games_per_chunk]))
            frames.append(
                _steps_of(chunk.with_columns(pl.lit(split).alias("split")), roles, loaded)
            )
    frame = pl.concat(frames, how="diagonal_relaxed").sort(*PLAYER, "step_idx", "builder_index")
    del frames
    categorical = tuple(dict.fromkeys([*HISTORY_CATEGORICAL, *manifest.get("categorical", [])]))
    types = pl.read_parquet(directory / "builder_types.parquet")
    return BuilderSteps(frame, loaded, categorical, manifest, builders.answers_of(types))


def _steps_of(
    rows: pl.LazyFrame, roles: Sequence[str], loaded: Mapping[str, Sequence[str]]
) -> pl.DataFrame:
    """The steps of some games' rows, with their order history and the `loaded` columns."""
    decides = pl.col("answer").is_not_null()
    decisions = (
        rows.filter(pl.col("builder_index") == 0)
        .sort(*PLAYER, "decision_index")
        .with_columns(step_index(PLAYER, answer="answer", decides=decides).alias("step_idx"))
    )
    answer_role = role_expression("answer", roles)
    is_job = pl.col("kind") == builders.JOB_KIND
    counted = [(role, (answer_role == role) & ~is_job & (pl.col("count") > 0)) for role in roles]
    counted += [(job, pl.col("answer") == job) for job in builders.JOBS]
    ordered = (
        decisions.select(*PLAYER, "decision_index", "answer", "kind", "count", "step_idx")
        .with_columns(
            (
                condition.fill_null(False).cast(pl.Int32).cum_sum().over(PLAYER)
                - condition.fill_null(False).cast(pl.Int32)
            ).alias(f"ordered_{name}")
            for name, condition in counted
        )
        .filter(pl.col("step_idx").is_not_null())
        .with_columns(
            pl.col("answer").shift(k).over(PLAYER).fill_null(START).alias(f"previous_{k}")
            for k in range(1, HISTORY + 1)
        )
        .select(
            *PLAYER,
            "decision_index",
            "step_idx",
            *[f"previous_{k}" for k in range(1, HISTORY + 1)],
            *[f"ordered_{name}" for name, _ in counted],
        )
    )
    # only what the models and the report read, numbers as 32-bit, to keep the steps of
    # every split in memory at once
    wanted = [
        *PLAYER,
        "split",
        "decision_index",
        "builder_index",
        "answer",
        "kind",
        "map",
        "faction",
        "position",
        "role",
        "game_version",
        "builder_unit",
        "builder_kind",
        "builder_previous",
        "builder_idle",
        "builders",
        "via",
        *[
            column
            for name, columns in loaded.items()
            if name != HISTORY_GROUP
            for column in columns
        ],
    ]
    schema = rows.collect_schema()
    wanted = list(dict.fromkeys(name for name in wanted if name in schema))
    narrow = [
        pl.col(name).cast(pl.Float32)
        for name in wanted
        if schema[name] in (pl.Float64, pl.Int64) and name not in (*PLAYER, "decision_index")
    ]
    return (
        rows.select(wanted)
        .with_columns(narrow)
        .join(ordered, on=[*PLAYER, "decision_index"])
        .with_columns(
            pl.col("answer").alias("unit"),  # the label, under the name the models use
            is_job.alias("is_job"),
            pl.col("builder_kind").fill_null("none"),
        )
        .collect(engine="streaming")
    )


# --- the mask


def mask_matrix(
    frame: pl.DataFrame, vocabulary: Sequence[str], answers: pl.DataFrame
) -> np.ndarray:
    """One row per row of `frame`: which entries of `vocabulary` its builder can give
    (ADR 0019). Rows without a builder, and the entry for unknown answers, are not masked."""
    index = {answer: position for position, answer in enumerate(vocabulary)}
    allowed: dict[tuple[str, str], np.ndarray] = {}
    for game, unit, options in answers.iter_rows():
        row = np.zeros(len(vocabulary), dtype=bool)
        row[[index[option] for option in options if option in index]] = True
        row[index[UNKNOWN]] = True
        allowed[game, unit] = row
    everything = np.ones(len(vocabulary), dtype=bool)
    keys = frame.select("game_version", "builder_unit").rows()
    return (
        np.stack([allowed.get(key, everything) for key in keys])
        if keys
        else np.zeros((0, len(vocabulary)), dtype=bool)
    )


def apply_mask(probabilities: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The masked and rescaled probabilities, and the probability the mask removed."""
    kept = np.where(mask, probabilities, 0.0)
    total = kept.sum(axis=1)
    removed = 1.0 - total
    safe = np.where(total > 0, total, 1.0)
    return kept / safe[:, None], removed


# --- scoring


@dataclass
class Scored:
    """A model's predictions on the scored rows: scores with and without the mask, the
    probability of a job, and what the mask removed."""

    masked: Scores
    unmasked: Scores
    job_probability: np.ndarray
    removed: np.ndarray
    truth_masked_out: np.ndarray
    top_answer: np.ndarray
    probabilities: np.ndarray | None = None


def score_tree(
    tree: TreeModel, frame: pl.DataFrame, answers: pl.DataFrame, keep: bool = False
) -> Scored:
    vocabulary = tree.vocabulary
    unknown = len(vocabulary) - 1
    index = {unit: position for position, unit in enumerate(vocabulary)}
    truth = np.array([index.get(unit, unknown) for unit in frame["unit"].to_list()])
    raw = tree.probabilities(frame)
    mask = mask_matrix(frame, vocabulary, answers)
    masked, removed = apply_mask(raw, mask)
    truth_masked_out = ~mask[np.arange(len(truth)), truth]
    # an answer the unit files say the builder cannot give, but it was given: keep a floor
    floor = np.finfo(np.float64).tiny
    masked[np.arange(len(truth)), truth] = np.maximum(masked[np.arange(len(truth)), truth], floor)
    groups = {
        "map": frame["map"].to_numpy(),
        "kind": frame["builder_kind"].to_numpy(),
    }

    def scores(probabilities: np.ndarray) -> Scores:
        rank = ranks(probabilities, truth)
        known = truth != unknown
        return Scores(
            frame["match_id"].to_numpy().astype(np.int64),
            frame["step_idx"].to_numpy().astype(np.int32),
            (rank < 1) & known,
            (rank < 3) & known,
            -np.log(probabilities[np.arange(len(truth)), truth].astype(np.float64)),
            groups,
        )

    jobs = np.array([answer in builders.JOBS for answer in vocabulary])
    return Scored(
        masked=scores(masked),
        unmasked=scores(raw),
        job_probability=masked[:, jobs].sum(axis=1),
        removed=removed,
        truth_masked_out=truth_masked_out,
        top_answer=np.array(vocabulary, dtype=object)[masked.argmax(axis=1)],
        probabilities=masked if keep else None,
    )


def variants(
    groups: Mapping[str, Sequence[str]], roles: Sequence[str]
) -> list[tuple[str, list[str]]]:
    """(name, features) of each tree model; see the module docs."""
    history = list(groups[HISTORY_GROUP])
    reference = history + [column for name in REFERENCE_GROUPS for column in groups[name]]
    found = [("history", history), ("history + builder", reference)]
    found += [
        (f"history + builder + {name}", reference + list(groups[name]))
        for name in ADDED_GROUPS
        if name in groups
    ]
    model = reference + [column for name in MODEL_GROUPS for column in groups[name]]
    found.append(("ADR 0019 inputs", model))
    found.append(("ADR 0019 inputs without skill", [c for c in model if c not in groups["skill"]]))
    short = [c for c in model if c not in history] + history_features(roles, history=1)
    found.append(("ADR 0019 inputs, history of one step", short))
    return found


REFERENCE = "history + builder"
MODEL = "ADR 0019 inputs"
WITHOUT_SKILL = "ADR 0019 inputs without skill"
SHORT_HISTORY = "ADR 0019 inputs, history of one step"


def _difference(first: Scores, second: Scores, mask: np.ndarray, rounds: int, metric: str) -> str:
    if not mask.any():
        return "-"
    value = float(getattr(first, metric)[mask].mean() - getattr(second, metric)[mask].mean())
    low, high = paired_difference(first, second, mask, rounds, metric=metric)
    if metric == "log_loss":
        return f"{value:+.3f} ({low:+.3f} to {high:+.3f})"
    return f"{100 * value:+.1f} ({100 * low:+.1f} to {100 * high:+.1f})"


def _cells(scores: Scores, mask: np.ndarray | None, rounds: int) -> list[str]:
    summary = summarize(scores, mask, rounds)
    return [
        _percent(summary.top1, summary.top1_interval),
        _percent(summary.top3, summary.top3_interval),
        _loss(summary.log_loss, summary.log_loss_interval),
    ]


def measure_builders(
    directory: Path,
    split: str,
    threads: int,
    rounds: int,
    device: str,
    log=lambda message: print(message, file=sys.stderr, flush=True),
) -> str:
    steps = load_builder_steps(directory)
    frame = steps.frame
    roles = steps.manifest["unit_roles"]["roles"]
    train = frame.filter(pl.col("split") == "train")
    validation = frame.filter(pl.col("split") == "validation")
    held_out = frame.filter(pl.col("split") == split, pl.col("step_idx") < SCORED_STEPS)
    order_rows = (held_out["builder_index"] == 0).to_numpy()
    log(f"{frame.height} rows, {train.height} in training, {held_out.height} scored on {split}")

    trees: dict[str, TreeModel] = {}
    scored: dict[str, Scored] = {}
    for name, features in variants(steps.groups, roles):
        tree = TreeModel(name, features, threads, device, steps.categorical, TREE_PARAMETERS).fit(
            train, validation
        )
        trees[name] = tree
        scored[name] = score_tree(tree, held_out, steps.answers, keep=name == MODEL)
        log(f"{name}: {tree.rounds} rounds, {tree.seconds:.0f} s")
    # the model of ADR 0019 trained on the order view, for the comparison of the views
    order_name = f"{MODEL}, trained on the order view"
    model_features = dict(variants(steps.groups, roles))[MODEL]
    tree = TreeModel(
        order_name, model_features, threads, device, steps.categorical, TREE_PARAMETERS
    ).fit(
        train.filter(pl.col("builder_index") == 0),
        validation.filter(pl.col("builder_index") == 0),
    )
    trees[order_name] = tree
    scored[order_name] = score_tree(tree, held_out, steps.answers)
    log(f"{order_name}: {tree.rounds} rounds, {tree.seconds:.0f} s")

    skill = skill_report(trees[MODEL], trees[WITHOUT_SKILL], train, held_out, steps, scored, rounds)
    return report(steps, split, held_out, order_rows, trees, scored, skill, rounds)


# --- skill


def skill_report(
    model: TreeModel,
    without: TreeModel,
    train: pl.DataFrame,
    held_out: pl.DataFrame,
    steps: BuilderSteps,
    scored: Mapping[str, Scored],
    rounds: int,
) -> list[str]:
    """ADR 0019's test of skill: do the predictions change between low and high skill, and
    does the fit per skill band improve over the same model without skill?"""
    low, high = (float(train["skill"].quantile(q)) for q in SKILL_QUANTILES)
    at_low = score_tree(
        model, held_out.with_columns(pl.lit(low).alias("skill")), steps.answers, True
    )
    at_high = score_tree(
        model, held_out.with_columns(pl.lit(high).alias("skill")), steps.answers, True
    )
    assert at_low.probabilities is not None and at_high.probabilities is not None
    variation = 0.5 * np.abs(at_low.probabilities - at_high.probabilities).sum(axis=1)
    same_top = at_low.top_answer == at_high.top_answer
    lines = [
        f"Skill set to the 10th and 90th percentile of the training rows ({low:.1f} and "
        f"{high:.1f}) for every held-out row, the masked predictions of `{MODEL}` differ by "
        f"a total variation of {variation.mean():.3f} on average (median "
        f"{np.median(variation):.3f}, 90th percentile {np.quantile(variation, 0.9):.3f}); "
        f"the most likely answer is the same in {100 * same_top.mean():.1f}% of the rows. "
        f"The share of jobs among the predictions: {100 * at_low.job_probability.mean():.1f}% "
        f"at low skill, {100 * at_high.job_probability.mean():.1f}% at high skill.",
        "",
    ]
    edges = [float(held_out["skill"].quantile(q)) for q in np.linspace(0, 1, SKILL_BANDS + 1)]
    skills = held_out["skill"].to_numpy()
    rows = []
    first, second = scored[MODEL].masked, scored[WITHOUT_SKILL].masked
    for band in range(SKILL_BANDS):
        upper = skills <= edges[band + 1] if band == SKILL_BANDS - 1 else skills < edges[band + 1]
        mask = (skills >= edges[band]) & upper
        rows.append(
            [
                f"{edges[band]:.1f} to {edges[band + 1]:.1f}",
                len(set(first.match_ids[mask].tolist())),
                int(mask.sum()),
                _cells(first, mask, rounds)[0],
                _difference(first, second, mask, rounds, "top1"),
                _difference(first, second, mask, rounds, "log_loss"),
            ]
        )
    lines += markdown.table(
        [
            "skill band",
            "games",
            "rows",
            "top-1 with skill",
            "top-1 vs without skill",
            "log-loss vs without skill",
        ],
        rows,
    )
    return lines


# --- the report


def report(
    steps: BuilderSteps,
    split: str,
    held_out: pl.DataFrame,
    order_rows: np.ndarray,
    trees: Mapping[str, TreeModel],
    scored: Mapping[str, Scored],
    skill: list[str],
    rounds: int,
) -> str:
    manifest = steps.manifest
    counts = manifest["counts"]
    every = np.ones(held_out.height, dtype=bool)
    kinds = held_out["builder_kind"].to_numpy()
    is_job = held_out["is_job"].to_numpy()
    idle = held_out["builder_idle"].fill_null(False).to_numpy()
    reference = scored[REFERENCE].masked
    lines = [
        f"Decision table `{manifest['name']}` built {manifest['built_at']} "
        f"(code {manifest['code']['commit']}) from {sum(counts['games'].values())} "
        f"re-simulated games: {counts['games']['train']} train, "
        f"{counts['games']['validation']} validation, {counts['games']['test']} test.",
        f"Scored on the {split} split: {held_out['match_id'].n_unique()} games, "
        f"{int(order_rows.sum())} steps (the first {SCORED_STEPS} of each opening), "
        f"{held_out.height} rows in the ask view. Intervals are 95%, from {rounds} draws of "
        "whole games; differences are paired. Masked unless said otherwise.",
        "",
        "## Models, ask view",
        "",
    ]
    rows = []
    for name, found in scored.items():
        rows.append(
            [
                name,
                len(trees[name].features),
                trees[name].rounds,
                *_cells(found.masked, every, rounds),
                _difference(found.masked, reference, every, rounds, "top1"),
                _difference(found.masked, reference, every, rounds, "log_loss"),
            ]
        )
    lines += markdown.table(
        [
            "model",
            "features",
            "rounds",
            "top-1",
            "top-3",
            "log-loss",
            f"top-1 vs {REFERENCE}",
            f"log-loss vs {REFERENCE}",
        ],
        rows,
    )

    lines += ["", "## What each group adds, by kind of builder (top-1, ask view)", ""]
    kind_names = [kind for kind in (*builders.BUILDER_KINDS, "none") if (kinds == kind).any()]
    header = ["model", *[f"{kind} ({int((kinds == kind).sum())})" for kind in kind_names]]
    rows = []
    for name, found in scored.items():
        if name == REFERENCE:
            rows.append(
                [name, *[_cells(found.masked, kinds == kind, rounds)[0] for kind in kind_names]]
            )
            continue
        rows.append(
            [
                name,
                *[
                    _difference(found.masked, reference, kinds == kind, rounds, "top1")
                    for kind in kind_names
                ],
            ]
        )
    lines += [
        f"The row of `{REFERENCE}` has its top-1; the others the difference to it.",
        "",
    ]
    lines += markdown.table(header, rows)
    lines += ["", "Log-loss, the same way:", ""]
    rows = []
    for name, found in scored.items():
        if name == REFERENCE:
            rows.append(
                [name, *[_cells(found.masked, kinds == kind, rounds)[2] for kind in kind_names]]
            )
            continue
        rows.append(
            [
                name,
                *[
                    _difference(found.masked, reference, kinds == kind, rounds, "log_loss")
                    for kind in kind_names
                ],
            ]
        )
    lines += markdown.table(header, rows)

    lines += ["", "## Build or job", ""]
    rows = []
    for name in ("history", REFERENCE, MODEL):
        found = scored[name]
        predicted = found.job_probability >= 0.5
        cells = [name]
        for kind in kind_names:
            mask = kinds == kind
            accuracy = (predicted[mask] == is_job[mask]).mean() if mask.any() else float("nan")
            cells.append(f"{100 * accuracy:.1f}%")
        accuracy = (predicted == is_job).mean()
        probability = np.clip(
            np.where(is_job, found.job_probability, 1 - found.job_probability), 1e-12, 1
        )
        cells += [f"{100 * accuracy:.1f}%", f"{-np.log(probability).mean():.3f}"]
        rows.append(cells)
    share = (
        ["share of jobs"]
        + [f"{100 * is_job[kinds == kind].mean():.1f}%" for kind in kind_names]
        + [f"{100 * is_job.mean():.1f}%", ""]
    )
    majority = (
        ["always the more common one"]
        + [
            f"{100 * max(is_job[kinds == kind].mean(), 1 - is_job[kinds == kind].mean()):.1f}%"
            for kind in kind_names
        ]
        + [f"{100 * max(is_job.mean(), 1 - is_job.mean()):.1f}%", ""]
    )
    lines += [
        "Whether the answer is a job: the masked probability of the four jobs together, "
        "a job when it is at least one half. Accuracy per kind of builder, then overall, "
        "and the log-loss of that yes or no.",
        "",
    ]
    lines += markdown.table(["model", *kind_names, "all", "log-loss"], [share, majority, *rows])

    lines += ["", "## The mask", ""]
    found = scored[MODEL]
    rows = []
    for kind in kind_names:
        mask = kinds == kind
        rows.append(
            [
                kind,
                int(mask.sum()),
                f"{100 * found.removed[mask].mean():.2f}%",
                f"{100 * np.quantile(found.removed[mask], 0.9):.2f}%",
                int(found.truth_masked_out[mask].sum()),
                _cells(found.unmasked, mask, rounds)[0],
                _cells(found.masked, mask, rounds)[0],
                _difference(found.masked, found.unmasked, mask, rounds, "log_loss"),
            ]
        )
    lines += [
        f"For `{MODEL}`, per kind of builder: the probability the mask takes away (mean "
        "and 90th percentile over the rows), the rows whose true answer the unit files say "
        "the builder cannot give, and the scores without and with the mask.",
        "",
    ]
    lines += markdown.table(
        [
            "kind",
            "rows",
            "removed, mean",
            "removed, p90",
            "true answer masked",
            "top-1 unmasked",
            "top-1 masked",
            "log-loss masked vs unmasked",
        ],
        rows,
    )
    removed_job = held_out.filter(pl.Series(found.truth_masked_out))
    if removed_job.height:
        lines += ["", "True answers the mask removes, most common:", ""]
        lines += markdown.table(
            ["builder", "answer", "rows"],
            removed_job.group_by("builder_unit", "unit")
            .len()
            .sort("len", descending=True)
            .head(10)
            .rows(),
        )

    lines += ["", "## The two views", ""]
    rows = []
    for name in (MODEL, f"{MODEL}, trained on the order view"):
        found = scored[name]
        rows.append([name, "ask", *_cells(found.masked, every, rounds)])
        rows.append([name, "order", *_cells(found.masked, order_rows, rounds)])
    several = held_out.with_columns(pl.Series(order_rows).alias("_order")).filter(pl.col("_order"))
    lines += [
        f"{int(order_rows.sum())} scored steps, {held_out.height} asks: "
        f"{100 * (several['builders'] > 1).mean():.1f}% of the steps went to more than one "
        f"builder, {100 * (several['builders'] >= 5).mean():.1f}% to five or more.",
        "",
    ]
    lines += markdown.table(["model", "scored on", "top-1", "top-3", "log-loss"], rows)

    lines += ["", "## Skill", ""]
    lines += skill

    lines += ["", "## Repeating the previous answer", ""]
    previous = held_out["previous_1"].to_numpy()
    builder_previous = held_out["builder_previous"].fill_null("").to_numpy()
    truth = held_out["unit"].to_numpy()
    rows = [
        [
            "the players",
            f"{100 * (truth == previous).mean():.1f}%",
            f"{100 * (truth == builder_previous).mean():.1f}%",
            "",
        ]
    ]
    for name in (MODEL, SHORT_HISTORY):
        found = scored[name]
        rows.append(
            [
                name,
                f"{100 * (found.top_answer == previous).mean():.1f}%",
                f"{100 * (found.top_answer == builder_previous).mean():.1f}%",
                _cells(found.masked, every, rounds)[0],
            ]
        )
    lines += [
        "How often the answer is the previous step's answer (of the player) and the "
        "previous answer of the asking builder: for the players, and for the most likely "
        "answer of the models.",
        "",
    ]
    lines += markdown.table(
        ["", "same as the previous step", "same as the builder's previous", "top-1"], rows
    )
    lines += [
        "",
        _difference(scored[SHORT_HISTORY].masked, scored[MODEL].masked, every, rounds, "top1")
        + " points of top-1 and "
        + _difference(scored[SHORT_HISTORY].masked, scored[MODEL].masked, every, rounds, "log_loss")
        + " nats for the history of one step against three.",
    ]

    lines += ["", "## Clicked and sent by widgets", ""]
    clicked = (held_out["via"] == "COMMAND").to_numpy()
    rows = []
    for label, part in (("clicked", clicked), ("sent by a widget", ~clicked)):
        jobs_part = part & is_job
        rows.append(
            [
                label,
                int(part.sum()),
                f"{100 * is_job[part].mean():.1f}%" if part.any() else "-",
                *_cells(scored[MODEL].masked, part, rounds)[:1],
                *_cells(scored[MODEL].masked, jobs_part, rounds)[:1],
            ]
        )
    lines += [
        "Orders a player clicked (``COMMAND``) and orders their widgets sent (``AICOMMAND``): "
        f"`{MODEL}`'s top-1 on each, and on the jobs among them.",
        "",
    ]
    lines += markdown.table(["orders", "asks", "jobs", "top-1", "top-1 on jobs"], rows)

    lines += ["", "## Asks of idle builders", ""]
    lines += [
        f"{int(idle.sum())} of the {held_out.height} asks went to a builder that was idle "
        "(it had written an idle line and got nothing to do since), the situation in which "
        "the bot asks.",
        "",
    ]
    rows = [
        [name, *_cells(scored[name].masked, idle, rounds)] for name in ("history", REFERENCE, MODEL)
    ]
    lines += markdown.table(["model", "top-1", "top-3", "log-loss"], rows)

    tree = trees[MODEL]
    gains = tree.gain_by_feature()
    total = sum(gains.values()) or 1.0
    lines += ["", f"## What `{MODEL}` uses", ""]
    rows = []
    for group, columns in steps.groups.items():
        if not set(tree.features) & set(columns):
            continue
        rows.append(
            [group, len(columns), _percent(sum(gains.get(c, 0.0) for c in columns) / total)]
        )
    lines += markdown.table(["group", "columns", "share of gain"], rows)
    group_of = {column: group for group, columns in steps.groups.items() for column in columns}
    top = sorted(gains.items(), key=lambda item: -item[1])[:20]
    lines += [""]
    lines += markdown.table(
        ["feature", "group", "share of gain"],
        [[f"`{name}`", group_of.get(name, "?"), _percent(gain / total)] for name, gain in top],
    )
    return "\n".join(lines)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--table", type=Path, default=dataset_dir(), help="the decision table")
    parser.add_argument("--split", default="validation", choices=["validation", "test"])
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--device", default=None)
    parser.add_argument("--rounds", type=int, default=BOOTSTRAP_ROUNDS)
    parser.add_argument("--out", type=Path, default=None)


def run(args: argparse.Namespace) -> int:
    text = measure_builders(
        args.table, args.split, args.threads, args.rounds, args.device or default_device()
    )
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0
