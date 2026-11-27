"""Measure what the game state adds to predicting the next build, on the decision table.

Usage::

    uv run reason8 context measure                  # validation
    uv run reason8 context measure --split test     # the numbers of docs/research/context.md
    uv run reason8 context measure --table data/datasets/context_v1

This module measures a table of the first format (``context_v1``: build orders only,
without builders); a table with builders and jobs (``context_v2``) is measured by
`reason8.context.builder_measure`, which uses the trees of this module.

The protocol is ADR 0013, on the rows of the decision table (`reason8.context.table`):
each model predicts the unit of the next step of an opening, the first `SCORED_STEPS`
steps of every opening of the held-out split are scored by top-1, top-3 and log-loss, and
the intervals come from resampling whole games. The models:

- the n-gram baselines of `reason8.models.ngram`, trained on the openings of the table's
  training games, and the saved model trained on the whole opening dataset
  (``models/ngram_v2.json``), whose training games include the table's but none of its
  held-out games: the difference between the two is what the smaller training set costs;
- gradient-boosted trees (XGBoost) trained on every step of the training games, with the
  order history only (`history_features`), then with each group of context columns of the
  table added on its own, and with all of them but the pace of the orders (`NOT_IN_ALL`).
  The validation split stops the boosting (`EARLY_STOPPING_ROUNDS`).

The trees predict one class per unit seen at least `MIN_CLASS_STEPS` times in training;
the other units share one class, split between them by their training counts (plus one, so
that units never seen get a share too), so that every unit has a probability and log-loss
is defined as for the n-grams.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import xgboost

from reason8 import markdown
from reason8.context.table import GROUPS, PLAYER, dataset_dir, role_expression
from reason8.models.evaluate import (
    BOOTSTRAP_ROUNDS,
    SCORED_STEPS,
    Scores,
    Summary,
    paired_difference,
    score,
    score_probabilities,
    summarize,
)
from reason8.models.ngram import (
    START,
    UNKNOWN,
    NgramModel,
    OpeningSteps,
    chain,
    load_model,
    models_dir,
)
from reason8.openings.dataset import SPLITS, step_index

HISTORY = 3  # previous steps the trees see, as the 4-gram does
MIN_CLASS_STEPS = 20
MAX_ROUNDS = 400
EARLY_STOPPING_ROUNDS = 20
PARAMETERS = {
    "objective": "multi:softprob",
    "eval_metric": "mlogloss",
    "tree_method": "hist",
    "max_depth": 6,
    "eta": 0.15,
    "min_child_weight": 5,
    "subsample": 0.8,
    "colsample_bynode": 0.8,
    "max_bin": 64,
    "max_cat_to_onehot": 1,
    "seed": 0,
}
CATEGORICAL = ("faction", "map", "position", "role", *[f"previous_{k}" for k in range(1, 4)])
HISTORY_GROUP = "history"
# Groups left out of the model with all context: the time since the player's previous order
# says how the order being predicted was given (one step split over quick clicks, or orders
# of one frame), not what the game looked like (docs/research/context.md).
NOT_IN_ALL = ("pace",)
NGRAM_NAME = "4-gram, faction, map and position"


def default_device() -> str:
    """``cuda`` when XGBoost can train on a GPU here, otherwise ``cpu``."""
    if not xgboost.build_info().get("USE_CUDA"):
        return "cpu"
    try:
        data = xgboost.DMatrix(np.zeros((2, 1), dtype=np.float32), label=[0, 1])
        xgboost.train({"device": "cuda", "tree_method": "hist"}, data, num_boost_round=1)
    except xgboost.core.XGBoostError:
        return "cpu"
    return "cuda"


@dataclass
class Steps:
    """The steps of the decision table: one row per step with its features, and the
    openings as `OpeningSteps` in the same order."""

    frame: pl.DataFrame
    groups: dict[str, list[str]]
    manifest: dict[str, Any]
    openings: dict[str, list[OpeningSteps]] = field(default_factory=dict)


def history_features(roles: Sequence[str]) -> list[str]:
    """What the n-grams know, and the counts of what the player ordered so far."""
    return [
        *CATEGORICAL[:4],
        "step_idx",
        "order_index",
        *[f"previous_{k}" for k in range(1, HISTORY + 1)],
        *[f"ordered_{role}" for role in roles],
    ]


def load_steps(directory: Path) -> Steps:
    """The steps of every split of the table, with the order history of each."""
    manifest = json.loads((directory / "manifest.json").read_text())
    roles = manifest["unit_roles"]["roles"]
    groups = {name: list(columns) for name, columns in manifest["groups"].items()}
    scans = [
        pl.scan_parquet(directory / f"{split}.parquet").with_columns(pl.lit(split).alias("split"))
        for split, _ in SPLITS
    ]
    rows = (
        pl.concat(scans, how="diagonal_relaxed")
        .sort(*PLAYER, "order_index")
        .with_columns(step_index(PLAYER).alias("step_idx"))
    )
    added = pl.col("count") > 0
    ordered = (
        rows.select(*PLAYER, "order_index", "unit", "count", "step_idx")
        .sort(*PLAYER, "order_index")
        .with_columns(role_expression("unit", roles).alias("_role"))
        .with_columns(
            (
                ((pl.col("_role") == role) & added).cast(pl.Int32).cum_sum().over(PLAYER)
                - ((pl.col("_role") == role) & added).cast(pl.Int32)
            ).alias(f"ordered_{role}")
            for role in roles
        )
        .filter(pl.col("step_idx").is_not_null())
        .select(*PLAYER, "order_index", *[f"ordered_{role}" for role in roles])
    )
    context = [name for columns in groups.values() for name in columns]
    frame = (
        rows.filter(pl.col("step_idx").is_not_null())
        .select(
            *PLAYER,
            "split",
            "order_index",
            "step_idx",
            "unit",
            "faction",
            "map",
            "position",
            "role",
            "build",
            "opening_era",
            *context,
        )
        .join(ordered, on=[*PLAYER, "order_index"])
        .sort(*PLAYER, "step_idx")
        .with_columns(
            pl.col("unit").shift(k).over(PLAYER).fill_null(START).alias(f"previous_{k}")
            for k in range(1, HISTORY + 1)
        )
        .collect()
    )
    groups = {HISTORY_GROUP: history_features(roles), **groups}
    steps = Steps(frame, groups, manifest)
    for split, _ in SPLITS:
        steps.openings[split] = openings_of(frame.filter(pl.col("split") == split))
    return steps


def openings_of(frame: pl.DataFrame) -> list[OpeningSteps]:
    """The openings of some steps, in the order of (match_id, player_slot)."""
    grouped = (
        frame.sort(*PLAYER, "step_idx")
        .group_by(PLAYER, maintain_order=True)
        .agg(
            pl.col("faction", "map", "position", "role", "build", "opening_era").first(),
            pl.col("unit").alias("steps"),
        )
    )
    return [
        OpeningSteps(
            match_id=row["match_id"],
            faction=row["faction"],
            map=row["map"],
            position=row["position"],
            role=row["role"],
            build=row["build"],
            opening_era=row["opening_era"],
            steps=tuple(row["steps"]),
        )
        for row in grouped.iter_rows(named=True)
    ]


def scored_steps(frame: pl.DataFrame, split: str) -> pl.DataFrame:
    return frame.filter(pl.col("split") == split, pl.col("step_idx") < SCORED_STEPS).sort(
        *PLAYER, "step_idx"
    )


def score_groups(frame: pl.DataFrame) -> dict[str, np.ndarray]:
    return {
        name: np.array(frame[name].to_list(), dtype=object)
        for name in ("map", "position", "faction")
    }


# --- the trees


class TreeModel:
    """Gradient-boosted trees over the order history and the chosen context groups."""

    def __init__(
        self,
        name: str,
        features: Sequence[str],
        threads: int,
        device: str = "cpu",
        categorical: Sequence[str] = CATEGORICAL,
        parameters: Mapping[str, Any] | None = None,
        min_class_steps: int = MIN_CLASS_STEPS,
        max_rounds: int = MAX_ROUNDS,
        early_stopping_rounds: int = EARLY_STOPPING_ROUNDS,
    ) -> None:
        self.name = name
        self.features = list(features)
        self.threads = threads
        self.device = device
        self.categorical = tuple(categorical)
        self.parameters = PARAMETERS | dict(parameters or {})
        self.min_class_steps = min_class_steps
        self.max_rounds = max_rounds
        self.early_stopping_rounds = early_stopping_rounds
        self.categories: dict[str, dict[str, int]] = {}
        self.classes: list[str] = []
        self.vocabulary: list[str] = []
        self.spread = np.zeros((0, 0))
        self.booster: xgboost.Booster | None = None
        self.rounds = 0
        self.seconds = 0.0

    def matrix(self, frame: pl.DataFrame) -> np.ndarray:
        columns = []
        for name in self.features:
            if name in self.categories:
                codes = self.categories[name]
                values = (
                    frame[name]
                    .cast(pl.String)
                    .replace_strict(codes, default=None, return_dtype=pl.Float32)
                )
                columns.append(values.fill_null(np.nan).to_numpy())
            else:
                columns.append(frame[name].cast(pl.Float32).fill_null(np.nan).to_numpy())
        return np.column_stack(columns).astype(np.float32)

    def dmatrix(
        self,
        frame: pl.DataFrame,
        labels: np.ndarray | None = None,
        reference: xgboost.QuantileDMatrix | None = None,
    ) -> xgboost.QuantileDMatrix:
        """The steps as XGBoost data, binned (`reference`: the training data's bins)."""
        return xgboost.QuantileDMatrix(
            self.matrix(frame),
            ref=reference,
            max_bin=self.parameters["max_bin"],
            label=labels,
            feature_names=self.features,
            feature_types=["c" if name in self.categories else "q" for name in self.features],
            enable_categorical=True,
            nthread=self.threads,
        )

    def fit(self, train: pl.DataFrame, validation: pl.DataFrame) -> TreeModel:
        started = time.monotonic()
        for name in self.features:
            if name in self.categorical:
                values = sorted(set(train[name].cast(pl.String).drop_nulls().to_list()))
                self.categories[name] = {value: code for code, value in enumerate(values)}
        counts = Counter(train["unit"].to_list())
        self.classes = sorted(
            unit for unit, count in counts.items() if count >= self.min_class_steps
        )
        self.vocabulary = sorted(counts) + [UNKNOWN]
        index = {unit: position for position, unit in enumerate(self.vocabulary)}
        other = len(self.classes)
        self.spread = np.zeros((other + 1, len(self.vocabulary)), dtype=np.float64)
        for position, unit in enumerate(self.classes):
            self.spread[position, index[unit]] = 1.0
        rare = [unit for unit in self.vocabulary if unit not in set(self.classes)]
        weights = np.array([counts.get(unit, 0) + 1 for unit in rare], dtype=np.float64)
        self.spread[other, [index[unit] for unit in rare]] = weights / weights.sum()

        def labels(frame: pl.DataFrame) -> np.ndarray:
            class_index = {unit: position for position, unit in enumerate(self.classes)}
            return np.array([class_index.get(unit, other) for unit in frame["unit"].to_list()])

        parameters = self.parameters | {
            "num_class": other + 1,
            "nthread": self.threads,
            "device": self.device,
        }
        training = self.dmatrix(train, labels(train))
        stopping = self.dmatrix(validation, labels(validation), reference=training)
        self.booster = xgboost.train(
            parameters,
            training,
            num_boost_round=self.max_rounds,
            evals=[(stopping, "validation")],
            early_stopping_rounds=self.early_stopping_rounds,
            verbose_eval=False,
        )
        self.rounds = self.booster.best_iteration + 1
        self.booster.set_param({"device": "cpu"})  # predict on the frames in memory
        self.seconds = time.monotonic() - started
        return self

    def probabilities(self, frame: pl.DataFrame) -> np.ndarray:
        """One row per step of `frame`: the probability of every unit of `vocabulary`."""
        assert self.booster is not None
        data = self.matrix(frame)
        classes = self.booster.inplace_predict(data, iteration_range=(0, self.rounds))
        return classes.astype(np.float64) @ self.spread

    def score(self, frame: pl.DataFrame) -> Scores:
        unknown = len(self.vocabulary) - 1
        index = {unit: position for position, unit in enumerate(self.vocabulary)}
        truth = np.array([index.get(unit, unknown) for unit in frame["unit"].to_list()])
        return score_probabilities(
            self.probabilities(frame),
            truth,
            unknown,
            frame["match_id"].to_numpy(),
            frame["step_idx"].to_numpy(),
            score_groups(frame),
        )

    def gain_by_feature(self) -> dict[str, float]:
        assert self.booster is not None
        return {
            name: float(value)
            for name, value in self.booster.get_score(importance_type="total_gain").items()
        }


def variants(groups: Mapping[str, Sequence[str]]) -> list[tuple[str, list[str]]]:
    """(name, features) of each tree model: the history alone, with each context group, and
    with all groups but those of `NOT_IN_ALL`."""
    history = list(groups[HISTORY_GROUP])
    context = [name for name in GROUPS if name in groups]
    found = [("trees: history", history)]
    found += [(f"trees: history + {name}", history + list(groups[name])) for name in context]
    everything = [column for name in context if name not in NOT_IN_ALL for column in groups[name]]
    found.append(("trees: history + all context", history + everything))
    return found


# --- the report


def _percent(value: float, interval: tuple[float, float] | None = None) -> str:
    text = f"{100 * value:.1f}%"
    if interval is not None:
        text += f" ({100 * interval[0]:.1f}–{100 * interval[1]:.1f})"
    return text


def _loss(value: float, interval: tuple[float, float] | None = None) -> str:
    text = f"{value:.3f}"
    if interval is not None:
        text += f" ({interval[0]:.3f}–{interval[1]:.3f})"
    return text


def _summary_cells(summary: Summary) -> list[str]:
    return [
        _percent(summary.top1, summary.top1_interval),
        _percent(summary.top3, summary.top3_interval),
        _loss(summary.log_loss, summary.log_loss_interval),
    ]


def _difference(first: Scores, second: Scores, mask: np.ndarray, rounds: int, metric: str) -> str:
    value = float(getattr(first, metric)[mask].mean() - getattr(second, metric)[mask].mean())
    low, high = paired_difference(first, second, mask, rounds, metric=metric)
    if metric == "log_loss":
        return f"{value:+.3f} ({low:+.3f} to {high:+.3f})"
    return f"{100 * value:+.1f} ({100 * low:+.1f} to {100 * high:+.1f})"


def report(
    steps: Steps,
    split: str,
    scores: Mapping[str, Scores],
    trained_on: Mapping[str, str],
    trees: Mapping[str, TreeModel],
    reference: str,
    rounds: int,
) -> str:
    manifest = steps.manifest
    counts = manifest["counts"]
    held_out = scored_steps(steps.frame, split)
    lines = [
        f"Decision table `{manifest['name']}` built {manifest['built_at']} "
        f"(code {manifest['code']['commit']}) from {sum(counts['games'].values())} "
        f"re-simulated games: {counts['games']['train']} train, "
        f"{counts['games']['validation']} validation, {counts['games']['test']} test.",
        f"Scored on the {split} split: {held_out['match_id'].n_unique()} games, "
        f"{held_out.select(PLAYER).n_unique()} openings, {held_out.height} steps (the first "
        f"{SCORED_STEPS} of each). Intervals are 95%, from {rounds} draws of whole games; the "
        f"differences are paired, against `{reference}`.",
        "",
        "## Models",
        "",
    ]
    base = scores[reference]
    everything = np.ones(len(base.top1), dtype=bool)
    rows = []
    for name, found in scores.items():
        rows.append(
            [
                name,
                trained_on[name],
                *_summary_cells(summarize(found, rounds=rounds)),
                _difference(found, base, everything, rounds, "top1"),
                _difference(found, base, everything, rounds, "log_loss"),
            ]
        )
    lines += markdown.table(
        ["model", "trained on", "top-1", "top-3", "log-loss", "top-1 vs ref.", "log-loss vs ref."],
        rows,
    )

    lines += ["", "## By map", ""]
    for map_name in sorted(set(base.groups["map"].tolist()), key=str):
        mask = base.groups["map"] == map_name
        lines += [
            "",
            f"### {map_name}",
            "",
            f"{len(set(base.match_ids[mask].tolist()))} games, {int(mask.sum())} steps.",
            "",
        ]
        rows = []
        for name, found in scores.items():
            summary = summarize(found, mask, rounds)
            rows.append(
                [
                    name,
                    *_summary_cells(summary),
                    _difference(found, base, mask, rounds, "top1"),
                    _difference(found, base, mask, rounds, "log_loss"),
                ]
            )
        lines += markdown.table(
            ["model", "top-1", "top-3", "log-loss", "top-1 vs ref.", "log-loss vs ref."], rows
        )

    lines += ["", "## The trees", ""]
    lines += markdown.table(
        ["model", "features", "classes", "rounds", "seconds"],
        [
            [name, len(tree.features), len(tree.classes) + 1, tree.rounds, f"{tree.seconds:.0f}"]
            for name, tree in trees.items()
        ],
    )
    everything_tree = list(trees.values())[-1]
    gains = everything_tree.gain_by_feature()
    total = sum(gains.values()) or 1.0
    lines += [
        "",
        f"## What `{everything_tree.name}` uses",
        "",
        "Share of the total gain of its splits, by group and for the top features.",
        "",
    ]
    by_group = []
    used = set(everything_tree.features)
    for group, columns in steps.groups.items():
        if not used & set(columns):
            continue
        share = sum(gains.get(column, 0.0) for column in columns) / total
        by_group.append([group, len(columns), _percent(share)])
    lines += markdown.table(["group", "columns", "share of gain"], by_group)
    lines += [""]
    group_of = {column: group for group, columns in steps.groups.items() for column in columns}
    top = sorted(gains.items(), key=lambda item: -item[1])[:20]
    lines += markdown.table(
        ["feature", "group", "share of gain"],
        [[f"`{name}`", group_of.get(name, "?"), _percent(gain / total)] for name, gain in top],
    )
    return "\n".join(lines)


def measure(
    directory: Path,
    split: str,
    saved_model: Path | None,
    threads: int,
    rounds: int,
    device: str = "cpu",
    log=lambda message: print(message, file=sys.stderr, flush=True),
) -> str:
    steps = load_steps(directory)
    held_out = scored_steps(steps.frame, split)
    held_out_openings = steps.openings[split]
    log(f"{steps.frame.height} steps, {held_out.height} scored on {split}")

    scores: dict[str, Scores] = {}
    trained_on: dict[str, str] = {}
    train_openings = steps.openings["train"]
    for name, levels in (
        ("trigram, faction", chain(3)),
        (NGRAM_NAME, chain(4, condition=("map", "position"))),
    ):
        model = NgramModel(name, levels).fit(train_openings)
        scores[f"n-gram: {name}"] = score(model, held_out_openings)
        trained_on[f"n-gram: {name}"] = f"{model.training['games']} table games"
    if saved_model is not None and saved_model.is_file():
        model = load_model(saved_model)
        scores[f"n-gram: {model.name}, saved"] = score(model, held_out_openings)
        trained_on[f"n-gram: {model.name}, saved"] = f"{model.training.get('games')} dataset games"
    for found in scores.values():
        assert np.array_equal(found.match_ids, held_out["match_id"].to_numpy())
        assert np.array_equal(found.step_indices, held_out["step_idx"].to_numpy())

    train = steps.frame.filter(pl.col("split") == "train")
    validation = steps.frame.filter(pl.col("split") == "validation")
    trees: dict[str, TreeModel] = {}
    for name, features in variants(steps.groups):
        tree = TreeModel(name, features, threads, device).fit(train, validation)
        trees[name] = tree
        scores[name] = tree.score(held_out)
        trained_on[name] = f"{train['match_id'].n_unique()} table games"
        log(f"{name}: {tree.rounds} rounds, {tree.seconds:.0f} s")
    return report(steps, split, scores, trained_on, trees, "trees: history", rounds)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--table", type=Path, default=dataset_dir(), help="the decision table")
    parser.add_argument("--split", default="validation", choices=["validation", "test"])
    parser.add_argument(
        "--saved-model",
        type=Path,
        default=models_dir() / "ngram_v2.json",
        help="the n-gram trained on the whole opening dataset",
    )
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument(
        "--device", default=None, help="cpu or cuda (default: cuda when XGBoost can use a GPU)"
    )
    parser.add_argument("--rounds", type=int, default=BOOTSTRAP_ROUNDS)
    parser.add_argument("--out", type=Path, default=None, help="also write the report here")


def run(args: argparse.Namespace) -> int:
    device = args.device or default_device()
    manifest = json.loads((args.table / "manifest.json").read_text())
    if manifest.get("format") == "reason8.context/1":
        text = measure(args.table, args.split, args.saved_model, args.threads, args.rounds, device)
    else:
        from reason8.context.builder_measure import measure_builders

        text = measure_builders(args.table, args.split, args.threads, args.rounds, device)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0
