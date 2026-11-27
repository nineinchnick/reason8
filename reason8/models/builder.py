"""Train, export and score the builder model of ADR 0019.

Usage::

    uv run reason8 model train                      # both models -> data/models/
    uv run reason8 model score --split test         # the numbers of docs/results.md
    uv run reason8 model vectors                    # tests/models/builder_vectors.json

`train` fits gradient-boosted trees on the decision table (``context_v2``,
`reason8.context.table`) that answer what a builder does next, a unit to build or a job,
from the inputs of ADR 0019 (`Config`), and writes each model in the file the game library
evaluates (``reason8.builder-trees/1``, `reason8.models.trees`,
``docs/reference/builder-model.md``) with its config, seed and the table's manifest. It
trains two models, with and without skill: the in-game measures choose between them
(ADR 0019). Each file is checked against XGBoost's own predictions on the held-out rows
before it is kept.

`score` scores model files with the protocol of ADR 0013 against the n-gram baselines,
from the files alone through the reference evaluator, with the mask of ADR 0019.

`vectors` writes test vectors for the library: a small model trained on synthetic rows,
synthetic inputs, and the probabilities and answers the reference evaluator gives.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import multiprocessing
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import xgboost

from reason8 import markdown
from reason8.context import builders
from reason8.context.builder_measure import (
    TREE_PARAMETERS,
    BuilderSteps,
    Scored,
    history_features,
    load_builder_steps,
    score_tree,
)
from reason8.context.measure import (
    EARLY_STOPPING_ROUNDS,
    MIN_CLASS_STEPS,
    PARAMETERS,
    TreeModel,
    _loss,
    _percent,
    default_device,
)
from reason8.context.table import PLAYER, dataset_dir
from reason8.game.versions import build_number
from reason8.models import trees
from reason8.models.evaluate import (
    BOOTSTRAP_ROUNDS,
    SCORED_STEPS,
    Scores,
    paired_difference,
    summarize,
)
from reason8.models.ngram import UNKNOWN, NgramModel, OpeningSteps, RepeatModel, chain, models_dir
from reason8.openings.dataset import _code_version
from reason8.paths import data_dir

NAME = "builder_v1"
#: The context groups of ADR 0019 besides the order history.
GROUPS = ("builder", "time", "economy", "own_units", "build_power", "skill")
#: The rounds of the shipped model. The boosting does not stop by itself within 400 rounds
#: (2.1 million nodes, a 293 MB file); the first 100 rounds keep most of the fit at a
#: quarter of the size, better than fewer classes or shallower trees of the same size
#: (docs/reference/builder-model.md).
SHIPPED_ROUNDS = 100
CHOICE_THRESHOLD = 0.10  # ADR 0019: the bot samples among answers of at least 10%
VECTORS = Path(__file__).resolve().parents[2] / "tests" / "models" / "builder_vectors.json"


@dataclass
class Config:
    """What a builder model is trained on and how; recorded in its file.

    The defaults are the model of ADR 0019 as measured in ``docs/research/context.md``:
    the history of one step (it repeats the previous answer less and predicts as well),
    trained on the order view, with the trees' settings that keep the boosting from
    diverging on the whole sample.
    """

    name: str = NAME
    groups: tuple[str, ...] = GROUPS
    history: int = 1
    view: str = "order"  # "order": one row per step; "builder": one per builder
    drop: tuple[str, ...] = ()  # columns left out of the inputs
    parameters: dict[str, Any] = field(default_factory=lambda: PARAMETERS | TREE_PARAMETERS)
    min_class_steps: int = MIN_CLASS_STEPS
    max_rounds: int = SHIPPED_ROUNDS
    early_stopping_rounds: int = EARLY_STOPPING_ROUNDS

    @property
    def seed(self) -> int:
        return int(self.parameters["seed"])

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> Config:
        values = dict(document)
        for key in ("groups", "drop"):
            if key in values:
                values[key] = tuple(values[key])
        if "parameters" in values:
            values["parameters"] = PARAMETERS | TREE_PARAMETERS | dict(values["parameters"])
        return cls(**values)

    def without_skill(self) -> Config:
        return dataclasses.replace(
            self,
            name=f"{self.name}_no_skill",
            groups=tuple(group for group in self.groups if group != "skill"),
        )


def _load_and_write(directory: Path, groups: tuple[str, ...], path: Path) -> BuilderSteps:
    steps = load_builder_steps(directory, groups)
    steps.frame.write_parquet(path)
    return dataclasses.replace(steps, frame=pl.DataFrame())


@contextmanager
def steps_file(directory: Path, groups: Sequence[str]) -> Iterator[tuple[BuilderSteps, Path]]:
    """`load_builder_steps` in a child process, which writes the rows to a file: the steps
    without their rows, and that file. Each model then reads only its own columns of the
    rows it trains on, and nothing the loading allocated stays with the training."""
    context = multiprocessing.get_context("spawn")
    scratch_dir = data_dir() / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_dir) as scratch:
        path = Path(scratch) / "steps.parquet"
        with ProcessPoolExecutor(1, mp_context=context) as pool:
            steps = pool.submit(_load_and_write, directory, tuple(groups), path).result()
        yield steps, path


def features_of(config: Config, steps: BuilderSteps) -> list[str]:
    roles = steps.manifest["unit_roles"]["roles"]
    found = history_features(roles, history=config.history)
    found += [column for group in config.groups for column in steps.groups[group]]
    return [name for name in dict.fromkeys(found) if name not in config.drop]


def view_rows(frame: pl.DataFrame, view: str) -> pl.DataFrame:
    return frame.filter(pl.col("builder_index") == 0) if view == "order" else frame


# --- training


def rows_of(path: Path, split: str, view: str, columns: Sequence[str]) -> pl.DataFrame:
    """The rows of one split in one view, with some columns, from a `steps_file`."""
    rows = pl.scan_parquet(path).filter(pl.col("split") == split)
    if view == "order":
        rows = rows.filter(pl.col("builder_index") == 0)
    return rows.select(columns).collect()


def fit(config: Config, steps: BuilderSteps, path: Path, threads: int, device: str) -> TreeModel:
    """Fit one model on the training rows, stopped on the validation rows, reading only its
    columns; the rows are freed once they are binned."""
    features = features_of(config, steps)
    columns = list(dict.fromkeys(["unit", *features]))
    return TreeModel(
        config.name,
        features,
        threads,
        device,
        steps.categorical,
        config.parameters,
        min_class_steps=config.min_class_steps,
        max_rounds=config.max_rounds,
        early_stopping_rounds=config.early_stopping_rounds,
    ).fit(
        rows_of(path, "train", config.view, columns),
        rows_of(path, "validation", config.view, columns),
    )


def training_rows(path: Path, config: Config) -> dict[str, Any]:
    """How many rows and games the model was trained on, and the skill of its rows."""
    train = rows_of(path, "train", config.view, ["match_id", "skill"])
    skill = train["skill"].drop_nulls()
    return {
        "rows": {"train": train.height, "games": int(train["match_id"].n_unique())},
        "skill_quantiles": {str(q): float(skill.quantile(q)) for q in (0.1, 0.5, 0.9, 0.99)},
    }


# --- the file


def booster_trees(booster: xgboost.Booster, rounds: int) -> tuple[list[float], list[dict]]:
    """The base score per class and the trees of the first `rounds` rounds, in the file's
    layout, from XGBoost's own JSON model."""
    model = json.loads(booster.save_raw("json"))
    learner = model["learner"]
    classes = int(learner["learner_model_param"]["num_class"]) or 1
    base = json.loads(learner["learner_model_param"]["base_score"])
    base_score = [float(value) for value in (base if isinstance(base, list) else [base])]
    if len(base_score) == 1:
        base_score *= classes
    booster_model = learner["gradient_booster"]["model"]
    if int(booster_model["gbtree_model_param"]["num_parallel_tree"]) != 1:
        raise ValueError("one tree per class and round expected")
    found = []
    for tree, class_index in zip(
        booster_model["trees"][: rounds * classes],
        booster_model["tree_info"][: rounds * classes],
        strict=True,
    ):
        leaves = [child == -1 for child in tree["left_children"]]
        categories = {}
        for node, start, size in zip(
            tree["categories_nodes"],
            tree["categories_segments"],
            tree["categories_sizes"],
            strict=True,
        ):
            categories[node] = tree["categories"][start : start + size]
        found.append(
            {
                "class": int(class_index),
                "feature": [
                    trees.LEAF if leaf else int(index)
                    for leaf, index in zip(leaves, tree["split_indices"], strict=True)
                ],
                "threshold": [
                    0.0 if leaf or node in categories else _float32(value)
                    for node, (leaf, value) in enumerate(
                        zip(leaves, tree["split_conditions"], strict=True)
                    )
                ],
                "left": [max(child, 0) for child in tree["left_children"]],
                "right": [max(child, 0) for child in tree["right_children"]],
                "default_left": [int(bool(value)) for value in tree["default_left"]],
                "value": [
                    _float32(value) if leaf else 0.0
                    for leaf, value in zip(leaves, tree["split_conditions"], strict=True)
                ],
                "categories": [[node, sorted(codes)] for node, codes in categories.items()],
            }
        )
    return base_score, found


def _float32(value: float) -> float:
    """A float32 value as the shortest decimal that reads back to the same float32."""
    return float(np.format_float_positional(np.float32(value), unique=True, trim="-"))


def builder_answers(types: pl.DataFrame, answers: Sequence[str]) -> tuple[str, dict]:
    """Per builder type, from the newest game version that has it: its kind, whether it
    moves, its build power and the indices of the answers it can give."""
    index = {answer: position for position, answer in enumerate(answers)}
    ranked = types.with_columns(
        pl.col("game").map_elements(lambda game: build_number(game) or 0, pl.Int64).alias("_b")
    ).sort("_b", descending=True)
    newest = ranked["game"][0]
    found = {}
    for row in (
        ranked.unique("builder_unit", keep="first").sort("builder_unit").iter_rows(named=True)
    ):
        options = list(row["build_options"]) + [job for job in builders.JOBS if row[f"can_{job}"]]
        found[row["builder_unit"]] = {
            "kind": row["builder_kind"],
            "moves": bool(row["builder_moves"]),
            "build_power": float(row["build_power"]),
            "answers": sorted(index[option] for option in options if option in index),
        }
    return newest, found


def file_document(
    tree: TreeModel,
    name: str,
    groups: Mapping[str, str],
    builder_entries: Mapping[str, Any],
    training: Mapping[str, Any],
) -> dict[str, Any]:
    """A fitted `TreeModel` as the file ``reason8.builder-trees/1``; `groups` names the
    group of each input, `builder_entries` the mask per builder type (`builder_answers`)."""
    assert tree.booster is not None
    base_score, found = booster_trees(tree.booster, tree.rounds)
    classes = []
    for row in tree.spread:
        members = np.flatnonzero(row)
        classes.append({"answers": members.tolist(), "weights": [float(row[i]) for i in members]})
    features = []
    for feature in tree.features:
        entry: dict[str, Any] = {"name": feature, "group": groups.get(feature, "history")}
        if feature in tree.categories:
            codes = tree.categories[feature]
            entry |= {"type": trees.CATEGORICAL, "categories": sorted(codes, key=codes.get)}
        else:
            entry["type"] = trees.NUMERIC
        features.append(entry)
    return {
        "format": trees.FORMAT,
        "name": name,
        "answers": list(tree.vocabulary),
        "features": features,
        "classes": classes,
        "base_score": base_score,
        "trees": found,
        "builders": dict(builder_entries),
        "choice": {"threshold": CHOICE_THRESHOLD, "unknown": UNKNOWN},
        "training": dict(training),
    }


def export(
    tree: TreeModel,
    config: Config,
    steps: BuilderSteps,
    types: pl.DataFrame,
    rows: Mapping[str, Any],
) -> dict[str, Any]:
    """The model as its file, with what it was trained on (`training_rows`) and how."""
    newest, builder_entries = builder_answers(types, tree.vocabulary)
    manifest = steps.manifest
    training = {
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": _code_version(),
        "xgboost": xgboost.__version__,
        "config": config.to_json(),
        "seed": config.seed,
        "rounds": tree.rounds,
        "seconds": round(tree.seconds),
        **rows,
        "mask_game_version": newest,
        "dataset": {
            key: manifest.get(key)
            for key in ("name", "format", "built_at", "code", "source", "sample", "counts")
        },
    }
    groups = {column: group for group, columns in steps.groups.items() for column in columns}
    return file_document(tree, config.name, groups, builder_entries, training)


def write_model(document: Mapping[str, Any], path: Path) -> int:
    """Write the file compactly; its size in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, separators=(",", ":")) + "\n"
    path.write_text(text)
    return len(text.encode())


def size_summary(model: trees.TreeFile, size: int) -> dict[str, Any]:
    leaves = sum(int((tree.feature == trees.LEAF).sum()) for tree in model.trees)
    return {
        "bytes": size,
        "trees": len(model.trees),
        "nodes": model.nodes,
        "leaves": leaves,
        "classes": len(model.classes.spread),
        "answers": len(model.answers),
        "features": len(model.features),
    }


# --- evaluating a file on the table


def encode_frame(model: trees.TreeFile, frame: pl.DataFrame) -> np.ndarray:
    """The rows of `frame` encoded as `TreeFile.encode` encodes the inputs of one decision."""
    columns = []
    for feature in model.features:
        if feature.type == trees.CATEGORICAL:
            codes = {name: code for code, name in enumerate(feature.categories)}
            values = (
                frame[feature.name]
                .cast(pl.String)
                .replace_strict(codes, default=None, return_dtype=pl.Float32)
            )
        else:
            values = frame[feature.name].cast(pl.Float32)
        columns.append(values.fill_null(np.nan).to_numpy())
    return np.column_stack(columns).astype(np.float32)


class FileModel:
    """A model file in the shape `score_tree` scores: answers and unmasked probabilities."""

    def __init__(self, model: trees.TreeFile) -> None:
        self.model = model
        self.vocabulary = model.answers

    def probabilities(self, frame: pl.DataFrame) -> np.ndarray:
        margins = self.model.margins(encode_frame(self.model, frame))
        return self.model.class_probabilities(margins) @ self.model.classes.spread


def check_file(
    model: trees.TreeFile, tree: TreeModel, frame: pl.DataFrame, one_by_one: int = 200
) -> dict[str, Any]:
    """How far the file's probabilities are from XGBoost's on the rows of `frame`: all
    rows with the vectorised evaluator, the first `one_by_one` also one at a time."""
    expected = tree.probabilities(frame)
    found = FileModel(model).probabilities(frame)
    sample = frame.head(one_by_one)
    matrix = encode_frame(model, sample)
    single = np.array([model.margins_one(row.tolist()) for row in matrix])
    single = model.class_probabilities(single) @ model.classes.spread
    return {
        "rows": frame.height,
        "max_difference": float(np.abs(found - expected).max()),
        "one_by_one_rows": sample.height,
        "one_by_one_max_difference": float(np.abs(single - expected[: sample.height]).max()),
    }


def train(
    directory: Path,
    out: Path,
    configs: Sequence[Config],
    threads: int,
    device: str,
    log=lambda message: print(message, file=sys.stderr, flush=True),
) -> list[Path]:
    groups = sorted({group for config in configs for group in config.groups} | {"skill"})
    types = pl.read_parquet(directory / "builder_types.parquet")
    written = []
    with steps_file(directory, groups) as (steps, steps_path):
        log(f"steps written to {steps_path}")
        for config in configs:
            tree = fit(config, steps, steps_path, threads, device)
            log(f"{config.name}: {tree.rounds} rounds, {tree.seconds:.0f} s")
            document = export(tree, config, steps, types, training_rows(steps_path, config))
            model = trees.from_document(document)
            held_out = (
                pl.scan_parquet(steps_path)
                .filter(pl.col("split") == "test", pl.col("step_idx") < SCORED_STEPS)
                .collect()
            )
            started = time.monotonic()
            check = check_file(model, tree, held_out)
            del held_out
            log(f"{config.name}: checked against XGBoost in {time.monotonic() - started:.0f} s")
            if check["max_difference"] > 1e-4 or check["one_by_one_max_difference"] > 1e-4:
                raise RuntimeError(f"{config.name}: the file does not match XGBoost: {check}")
            document["training"]["check"] = check
            path = out / f"{config.name}.json"
            size = write_model(document, path)
            document["training"]["size"] = size_summary(model, size)
            size = write_model(document, path)
            assert tree.booster is not None
            tree.booster.save_model(out / f"{config.name}.xgb.ubj")
            log(f"{config.name}: {path} ({size / 1e6:.1f} MB), {document['training']['size']}")
            written.append(path)
            del tree, model, document  # a large model's trees as Python lists take GBs
            gc.collect()
    return written


# --- scoring


def openings_of(frame: pl.DataFrame) -> dict[tuple[int, int], OpeningSteps]:
    """Each player's steps (answers) in the order view, as the n-grams read them."""
    grouped = (
        frame.filter(pl.col("builder_index") == 0)
        .sort(*PLAYER, "step_idx")
        .group_by(PLAYER, maintain_order=True)
        .agg(pl.col("faction", "map", "position", "role").first(), pl.col("unit").alias("steps"))
    )
    return {
        (row["match_id"], row["player_slot"]): OpeningSteps(
            row["match_id"],
            row["faction"],
            row["map"],
            row["position"],
            row["role"],
            None,
            None,
            tuple(row["steps"]),
        )
        for row in grouped.iter_rows(named=True)
    }


class SequenceModel:
    """An n-gram fitted on the order view's steps, scored on rows of the table."""

    def __init__(self, model: NgramModel | RepeatModel, openings: Mapping) -> None:
        self.model = model
        self.openings = openings
        self.vocabulary = model.vocabulary

    def probabilities(self, frame: pl.DataFrame) -> np.ndarray:
        rows = frame.select(*PLAYER, "step_idx").iter_rows()
        return np.stack(
            [
                self.model.distribution(self.openings[(match, slot)], int(step))
                for match, slot, step in rows
            ]
        )


BASELINES = (
    ("repeat the previous step", lambda: RepeatModel()),
    ("trigram, faction", lambda: NgramModel("trigram, faction", chain(3))),
    (
        "4-gram, faction, map and position",
        lambda: NgramModel(
            "4-gram, faction, map and position", chain(4, condition=("map", "position"))
        ),
    ),
)
BASELINE = "4-gram, faction, map and position"


def _cells(scores: Scores, mask: np.ndarray, rounds: int) -> list[str]:
    summary = summarize(scores, mask, rounds)
    return [
        _percent(summary.top1, summary.top1_interval),
        _percent(summary.top3, summary.top3_interval),
        _loss(summary.log_loss, summary.log_loss_interval),
    ]


def _difference(first: Scores, second: Scores, mask: np.ndarray, rounds: int, metric: str) -> str:
    if not mask.any():
        return "-"
    value = float(getattr(first, metric)[mask].mean() - getattr(second, metric)[mask].mean())
    low, high = paired_difference(first, second, mask, rounds, metric=metric)
    if metric == "log_loss":
        return f"{value:+.3f} ({low:+.3f} to {high:+.3f})"
    return f"{100 * value:+.1f} ({100 * low:+.1f} to {100 * high:+.1f})"


SCORED_CHUNK = 20_000  # rows scored at a time: a chunk's probabilities take about 70 MB


def _concatenate(parts: Sequence[Scored]) -> Scored:
    """The scores of consecutive chunks of rows as one."""

    def scores(field_name: str) -> Scores:
        found = [getattr(part, field_name) for part in parts]
        return Scores(
            np.concatenate([part.match_ids for part in found]),
            np.concatenate([part.step_indices for part in found]),
            np.concatenate([part.top1 for part in found]),
            np.concatenate([part.top3 for part in found]),
            np.concatenate([part.log_loss for part in found]),
            {
                name: np.concatenate([part.groups[name] for part in found])
                for name in found[0].groups
            },
        )

    return Scored(
        masked=scores("masked"),
        unmasked=scores("unmasked"),
        job_probability=np.concatenate([part.job_probability for part in parts]),
        removed=np.concatenate([part.removed for part in parts]),
        truth_masked_out=np.concatenate([part.truth_masked_out for part in parts]),
        top_answer=np.concatenate([part.top_answer for part in parts]),
    )


def score_in_chunks(model: Any, rows: pl.DataFrame, answers: pl.DataFrame) -> Scored:
    """`score_tree` a chunk of rows at a time, so that only one chunk's probabilities are
    in memory."""
    return _concatenate(
        [
            score_tree(model, rows.slice(start, SCORED_CHUNK), answers)
            for start in range(0, rows.height, SCORED_CHUNK)
        ]
    )


def score(
    directory: Path,
    paths: Sequence[Path],
    split: str,
    rounds: int,
    reference: str | None = None,
    log=lambda message: print(message, file=sys.stderr, flush=True),
) -> str:
    """Score model files on a split; the files are read one at a time and the rows of the
    split only, with the columns the files' inputs need."""
    summaries: dict[str, dict[str, Any]] = {}
    groups: set[str] = set()
    for path in paths:
        document = json.loads(path.read_text())
        groups |= {feature["group"] for feature in document["features"]} - {"history"}
        summaries[path.stem] = {
            "inputs": len(document["features"]),
            "training": document["training"],
        }
        del document
    steps = load_builder_steps(directory, sorted(groups), splits=[split])
    held_out = steps.frame.filter(pl.col("step_idx") < SCORED_STEPS)
    order_rows = (held_out["builder_index"] == 0).to_numpy()
    log(f"{held_out.height} rows scored on {split}")

    # the n-grams read the answers of whole openings: those of the training split to learn
    # from, those of the scored split as the history of each scored step
    openings = openings_of(steps.frame)
    train_openings = list(
        openings_of(load_builder_steps(directory, [], splits=["train"]).frame).values()
    )
    steps = dataclasses.replace(steps, frame=pl.DataFrame())
    scored: dict[str, Scored] = {}
    for name, make in BASELINES:
        model = make().fit(train_openings)
        scored[name] = score_in_chunks(SequenceModel(model, openings), held_out, steps.answers)
        log(f"{name}: scored")
    del train_openings
    for path in paths:
        started = time.monotonic()
        model = trees.load(path)
        scored[path.stem] = score_in_chunks(FileModel(model), held_out, steps.answers)
        del model
        gc.collect()
        log(f"{path.stem}: scored in {time.monotonic() - started:.0f} s")
    return score_report(steps, split, held_out, order_rows, summaries, scored, rounds, reference)


def score_report(
    steps: BuilderSteps,
    split: str,
    held_out: pl.DataFrame,
    order_rows: np.ndarray,
    models: Mapping[str, Mapping[str, Any]],
    scored: Mapping[str, Scored],
    rounds: int,
    reference: str | None,
) -> str:
    """The report of `score`; `models` holds each file's number of inputs and its
    ``training`` record."""
    every = np.ones(held_out.height, dtype=bool)
    clicked = (held_out["via"] == "COMMAND").to_numpy()
    kinds = held_out["builder_kind"].to_numpy()
    base = scored[BASELINE].masked
    reference = reference or next(iter(models))
    manifest = steps.manifest
    lines = [
        f"Decision table `{manifest['name']}` built {manifest['built_at']}. Scored on the "
        f"{split} split: {held_out['match_id'].n_unique()} games, {int(order_rows.sum())} "
        f"steps (the first {SCORED_STEPS} of each opening), {held_out.height} rows in the "
        "builder view. "
        f"Intervals are 95%, from {rounds} draws of whole games; differences are paired. "
        "Every model masked (ADR 0019). The n-grams are trained on the answers of the "
        "table's training games, in the order view.",
        "",
    ]
    for view, view_mask in (("order view", order_rows), ("builder view", every)):
        lines += [f"## Models, {view}", ""]
        rows = []
        for name, found in scored.items():
            for label, part in (("all", view_mask), ("clicked", view_mask & clicked)):
                rows.append(
                    [
                        name,
                        label,
                        int(part.sum()),
                        *_cells(found.masked, part, rounds),
                        _difference(found.masked, base, part, rounds, "top1"),
                        _difference(found.masked, base, part, rounds, "log_loss"),
                    ]
                )
        lines += markdown.table(
            [
                "model",
                "orders",
                "rows",
                "top-1",
                "top-3",
                "log-loss",
                "top-1 vs 4-gram",
                "log-loss vs 4-gram",
            ],
            rows,
        )
        lines += [""]

    kind_names = [kind for kind in (*builders.BUILDER_KINDS, "none") if (kinds == kind).any()]
    for metric, title in (("top1", "top-1"), ("log_loss", "log-loss")):
        lines += [f"## By kind of builder, order view: {title}", ""]
        rows = []
        for name, found in scored.items():
            cells = []
            for kind in kind_names:
                part = order_rows & (kinds == kind)
                summary = _cells(found.masked, part, rounds)
                cells.append(summary[0] if metric == "top1" else summary[2])
            rows.append([name, *cells])
        lines += markdown.table(
            [
                "model",
                *[f"{kind} ({int((order_rows & (kinds == kind)).sum())})" for kind in kind_names],
            ],
            rows,
        )
        lines += [""]

    others = [name for name in models if name != reference]
    if others:
        lines += [f"## Against `{reference}`, order view", ""]
        rows = []
        for name in others:
            for label, part in (("all", order_rows), ("clicked", order_rows & clicked)):
                rows.append(
                    [
                        name,
                        label,
                        _difference(
                            scored[name].masked, scored[reference].masked, part, rounds, "top1"
                        ),
                        _difference(
                            scored[name].masked, scored[reference].masked, part, rounds, "log_loss"
                        ),
                        *[
                            _difference(
                                scored[name].masked,
                                scored[reference].masked,
                                part & (kinds == kind),
                                rounds,
                                "top1",
                            )
                            for kind in kind_names
                        ],
                    ]
                )
        lines += markdown.table(
            ["model", "orders", "top-1", "log-loss", *[f"top-1, {kind}" for kind in kind_names]],
            rows,
        )
        lines += [""]

    lines += ["## The files", ""]
    rows = []
    for name, model in models.items():
        size = model["training"].get("size", {})
        check = model["training"].get("check", {})
        rows.append(
            [
                name,
                model["inputs"],
                model["training"]["rounds"],
                size.get("classes"),
                size.get("trees"),
                size.get("nodes"),
                f"{size.get('bytes', 0) / 1e6:.1f} MB",
                f"{check.get('max_difference', float('nan')):.1e}",
            ]
        )
    lines += markdown.table(
        ["model", "inputs", "rounds", "classes", "trees", "nodes", "size", "max diff vs XGBoost"],
        rows,
    )
    removed = {name: found.removed[order_rows].mean() for name, found in scored.items()}
    lines += ["", "Probability the mask removes, order view, mean:", ""]
    lines += markdown.table(
        ["model", "removed"], [[name, f"{100 * value:.2f}%"] for name, value in removed.items()]
    )
    return "\n".join(lines)


# --- test vectors


def synthetic_model(seed: int = 0) -> dict[str, Any]:
    """A small model file trained on synthetic rows: categorical and numeric inputs,
    missing values, a class shared by rare answers, and two builder types to mask."""
    generator = np.random.default_rng(seed)
    rows = 3000
    kinds = generator.choice(["commander", "factory", "construction"], rows)
    previous = generator.choice(["<start>", "mex", "win", "lab", "assist"], rows)
    time_s = generator.uniform(0, 600, rows)
    metal = generator.uniform(0, 1000, rows)
    metal[generator.random(rows) < 0.1] = np.nan
    skill = generator.normal(25, 8, rows)
    answer = np.where(
        kinds == "factory",
        np.where(time_s > 300, "ck", "flash"),
        np.where(
            (previous == "mex") & (np.nan_to_num(metal) < 500),
            "win",
            np.where(time_s < 120, "mex", np.where(skill > 28, "reclaim", "lab")),
        ),
    )
    noise = generator.random(rows) < 0.15
    answer = np.where(noise, generator.choice(["mex", "win", "assist", "ck"], rows), answer)
    rare = generator.random(rows) < 0.01
    answer = np.where(rare, generator.choice(["nanotc", "rad"], rows), answer)
    frame = pl.DataFrame(
        {
            "match_id": np.arange(rows) // 100,
            "builder_kind": kinds,
            "builder_previous": previous,
            "time_s": time_s.astype(np.float32),
            "metal": metal.astype(np.float32),
            "skill": skill.astype(np.float32),
            "builder_moves": kinds != "factory",
            "unit": answer,
        }
    )
    train, validation = frame.head(2400), frame.tail(600)
    features = ["builder_kind", "builder_previous", "time_s", "metal", "skill", "builder_moves"]
    tree = TreeModel(
        "synthetic",
        features,
        threads=1,
        device="cpu",
        categorical=("builder_kind", "builder_previous"),
        parameters={"max_depth": 3, "min_child_weight": 1, "eta": 0.3},
        min_class_steps=20,
        max_rounds=8,
        early_stopping_rounds=8,
    ).fit(train, validation)
    index = {answer: position for position, answer in enumerate(tree.vocabulary)}

    def allowed(*options: str) -> dict[str, Any]:
        return {"answers": sorted(index[option] for option in options if option in index)}

    builder_entries = {
        "armcom": {"kind": "commander", "moves": True, "build_power": 300.0}
        | allowed("mex", "win", "lab", "nanotc", "rad", "assist", "reclaim"),
        "armlab": {"kind": "factory", "moves": False, "build_power": 100.0}
        | allowed("ck", "flash"),
    }
    groups = {"time_s": "time", "metal": "economy", "skill": "skill"}
    groups |= {name: "builder" for name in features if name not in groups}
    document = file_document(
        tree, "synthetic", groups, builder_entries, {"synthetic": True, "seed": seed}
    )
    return document | {
        "_booster": tree,  # removed before writing; used to check the vectors
    }


def synthetic_inputs(model: trees.TreeFile, count: int, seed: int = 1) -> list[dict[str, Any]]:
    """Random inputs of decisions over every input of `model`: categories seen and unseen,
    numbers across the trees' thresholds, missing values, and builder types with and
    without a mask."""
    generator = np.random.default_rng(seed)
    thresholds: dict[int, list[float]] = {}
    for tree in model.trees:
        for node in np.flatnonzero(tree.feature != trees.LEAF):
            if int(node) not in tree.categories:
                thresholds.setdefault(int(tree.feature[node]), []).append(
                    float(tree.threshold[node])
                )
    builder_types = [*sorted(model.builders), "not-a-builder", None]
    entries = []
    for _ in range(count):
        inputs: dict[str, Any] = {}
        for position, feature in enumerate(model.features):
            if generator.random() < 0.05:
                inputs[feature.name] = None
            elif feature.type == trees.CATEGORICAL:
                options = [*feature.categories, "never-seen"]
                inputs[feature.name] = options[generator.integers(len(options))]
            else:
                # thresholds near the float limit (a split above every value) bound no range
                found = [t for t in thresholds.get(position, []) if abs(t) < 1e30] or [0.0, 1.0]
                low, high = min(found), max(found)
                spread = (high - low) or 1.0
                value = float(
                    np.float32(generator.uniform(low - 0.1 * spread, high + 0.1 * spread))
                )
                if generator.random() < 0.2 and found:
                    value = float(found[generator.integers(len(found))])  # exactly on a split
                inputs[feature.name] = value
        inputs["builder_unit"] = builder_types[generator.integers(len(builder_types))]
        entries.append({"inputs": inputs, "uniform": float(generator.random())})
    return entries


BOUNDARY_MARGIN = 1e-4  # keep draws this far from where the choice changes


def _clear_of_boundaries(model: trees.TreeFile, possible: list, uniform: float) -> float:
    """`uniform`, moved until it is clear of every point where `choose` changes its answer,
    so that the library's 32-bit sums draw the same answer."""
    candidates = [p for _, p in possible if p >= model.threshold]
    total = sum(candidates)
    edges = np.cumsum(candidates) / total if candidates else np.array([])
    while edges.size and np.abs(edges - uniform).min() < BOUNDARY_MARGIN:
        uniform = (uniform + 0.37) % 1.0
    return uniform


def vectors_of(model: trees.TreeFile, entries: Sequence[Mapping[str, Any]]) -> list[dict]:
    """The expected decision for each entry: the encoded row, the probability of every
    answer, the answers the builder can give, the possible answers and the chosen one."""
    found = []
    for entry in entries:
        decision = model.decide(entry["inputs"], entry["uniform"])
        uniform = _clear_of_boundaries(model, decision.possible, entry["uniform"])
        decision = model.decide(entry["inputs"], uniform)
        found.append(
            {
                "inputs": entry["inputs"],
                "uniform": uniform,
                "encoded": [None if np.isnan(value) else float(value) for value in decision.row],
                "probabilities": [round(float(value), 9) for value in decision.probabilities],
                "can_give": sorted(decision.can_give),
                "possible": [
                    [answer, round(probability, 9)] for answer, probability in decision.possible
                ],
                "answer": decision.answer,
            }
        )
    return found


def write_vectors(path: Path, model_path: Path | None, count: int) -> dict[str, Any]:
    """Test vectors: with `model_path`, synthetic decisions of that model; without, a synthetic
    model with them, all in one file."""
    if model_path is None:
        document = synthetic_model()
        booster = document.pop("_booster")
        model = trees.from_document(document)
        entries = synthetic_inputs(model, count)
        frame_check = np.stack([model.encode(entry["inputs"]) for entry in entries])
        expected = booster.booster.inplace_predict(frame_check, iteration_range=(0, booster.rounds))
        found = model.class_probabilities(model.margins(frame_check))
        if np.abs(found - expected).max() > 1e-5:
            raise RuntimeError("the synthetic model's file does not match XGBoost")
        result = {"model": document, "tolerance": 1e-6, "decisions": vectors_of(model, entries)}
    else:
        model = trees.load(model_path)
        result = {
            "model_file": model_path.name,
            "tolerance": 1e-6,
            "decisions": vectors_of(model, synthetic_inputs(model, count)),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1) + "\n")
    return result


# --- the command


def add_arguments(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="action", required=True)
    trainer = commands.add_parser("train", help="train the builder models and write their files")
    trainer.add_argument("--table", type=Path, default=dataset_dir())
    trainer.add_argument("--out", type=Path, default=models_dir())
    trainer.add_argument("--config", type=Path, default=None, help="a JSON config (`Config`)")
    trainer.add_argument("--name", default=None)
    trainer.add_argument("--max-depth", type=int, default=None)
    trainer.add_argument("--max-rounds", type=int, default=None)
    trainer.add_argument("--min-class-steps", type=int, default=None)
    trainer.add_argument("--drop", nargs="*", default=None, help="columns to leave out")
    trainer.add_argument(
        "--only", choices=["skill", "no-skill"], default=None, help="train one of the two"
    )
    trainer.add_argument("--threads", type=int, default=6)
    trainer.add_argument("--device", default=None)
    scorer = commands.add_parser("score", help="score model files on the table (ADR 0013)")
    scorer.add_argument("models", type=Path, nargs="+")
    scorer.add_argument("--table", type=Path, default=dataset_dir())
    scorer.add_argument("--split", default="validation", choices=["validation", "test"])
    scorer.add_argument("--rounds", type=int, default=BOOTSTRAP_ROUNDS)
    scorer.add_argument("--reference", default=None, help="the model the others are compared to")
    scorer.add_argument("--out", type=Path, default=None)
    vectors = commands.add_parser("vectors", help="write test vectors for the library")
    vectors.add_argument(
        "--model", type=Path, default=None, help="a model file (default: synthetic)"
    )
    vectors.add_argument("--out", type=Path, default=None)
    vectors.add_argument("--decisions", type=int, default=None)


def run(args: argparse.Namespace) -> int:
    if args.action == "train":
        config = Config.from_json(json.loads(args.config.read_text())) if args.config else Config()
        if args.name:
            config.name = args.name
        if args.max_depth is not None:
            config.parameters = config.parameters | {"max_depth": args.max_depth}
        if args.max_rounds is not None:
            config.max_rounds = args.max_rounds
        if args.min_class_steps is not None:
            config.min_class_steps = args.min_class_steps
        if args.drop is not None:
            config.drop = tuple(args.drop)
        configs = [config, config.without_skill()]
        if args.only == "skill":
            configs = configs[:1]
        elif args.only == "no-skill":
            configs = configs[1:]
        train(args.table, args.out, configs, args.threads, args.device or default_device())
        return 0
    if args.action == "score":
        text = score(args.table, args.models, args.split, args.rounds, args.reference)
        print(text)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n")
        return 0
    if args.model is None:
        out = args.out or VECTORS
        write_vectors(out, None, args.decisions or 40)
    else:
        out = args.out or args.model.with_suffix(".vectors.json")
        write_vectors(out, args.model, args.decisions or 100)
    print(out)
    return 0
