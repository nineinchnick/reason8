"""Score next-build models on held-out games, and choose the baseline to keep.

Usage::

    uv run reason8 baseline                  # train on train, score validation
    uv run reason8 baseline --split test     # the final numbers (docs/results.md)

The protocol is ADR 0013: a model predicts the unit of the next step of an opening, the
first `SCORED_STEPS` steps of every held-out opening are scored by top-1, top-3 and
log-loss, and the intervals come from resampling whole games. `reason8 baseline` fits the
candidate models of `reason8.models.ngram` on the training split, chooses the n-gram with
the lowest validation log-loss, prints the tables of docs/results.md and saves the chosen
model.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from reason8 import markdown
from reason8.game.positions import position_order
from reason8.game.versions import BALANCE_PATCHES
from reason8.models.ngram import (
    UNKNOWN,
    Model,
    NgramModel,
    OpeningSteps,
    RepeatModel,
    candidate_models,
    chain,
    load_openings,
    models_dir,
    save_model,
)
from reason8.openings.dataset import dataset_dir, load_sequences

# Steps scored per opening. The first 30 hold the first factory and its first units, and
# keep long openings from outweighing the others; an opening that ends at first contact
# before that is scored whole.
SCORED_STEPS = 30
STEP_BUCKETS = ((0, 1), (1, 5), (5, 10), (10, 20), (20, 30))
BOOTSTRAP_ROUNDS = 1000


@dataclass
class Scores:
    """Per scored step: the game, the opening's groups, and how the model did."""

    match_ids: np.ndarray
    step_indices: np.ndarray
    top1: np.ndarray
    top3: np.ndarray
    log_loss: np.ndarray  # natural log
    groups: dict[str, np.ndarray]  # map, position, faction, era per step


def ranks(probabilities: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """The rank of the true unit in each row of `probabilities` (0: the most likely).

    Ties are broken against the truth: a model that cannot tell gets no credit.
    """
    truth_probability = probabilities[np.arange(len(truth)), truth][:, None]
    better = np.count_nonzero(probabilities > truth_probability, axis=1)
    ties = np.count_nonzero(probabilities == truth_probability, axis=1) - 1
    return better + ties


def score_probabilities(
    probabilities: np.ndarray,
    truth: np.ndarray,
    unknown: int,
    match_ids: np.ndarray,
    step_indices: np.ndarray,
    groups: dict[str, np.ndarray],
) -> Scores:
    """`Scores` of a model that gives each scored step a distribution over its vocabulary:
    one row of `probabilities` per step, `truth` the index of the true unit in it, `unknown`
    the index of the entry for units the model never saw. Scored as `score` does."""
    rank = ranks(probabilities, truth)
    known = truth != unknown
    return Scores(
        np.asarray(match_ids, dtype=np.int64),
        np.asarray(step_indices, dtype=np.int32),
        (rank < 1) & known,
        (rank < 3) & known,
        -np.log(probabilities[np.arange(len(truth)), truth].astype(np.float64)),
        groups,
    )


def score(
    model: NgramModel | RepeatModel,
    openings: Sequence[OpeningSteps],
    steps: int = SCORED_STEPS,
) -> Scores:
    """Top-1, top-3 and log-loss of every scored step of every opening."""
    match_ids, step_indices, top1, top3, log_loss = [], [], [], [], []
    groups: dict[str, list] = defaultdict(list)
    unknown = model.index[UNKNOWN]
    for opening in openings:
        for index, unit in enumerate(opening.steps[:steps]):
            probabilities = model.distribution(opening, index)
            truth = model.index.get(unit, unknown)
            truth_probability = probabilities[truth]
            better = int(np.count_nonzero(probabilities > truth_probability))
            # ties are broken against the truth: a model that cannot tell gets no credit
            ties = int(np.count_nonzero(probabilities == truth_probability)) - 1
            rank = better + ties
            match_ids.append(opening.match_id)
            step_indices.append(index)
            top1.append(rank < 1 and truth != unknown)
            top3.append(rank < 3 and truth != unknown)
            log_loss.append(-math.log(truth_probability))
            groups["map"].append(opening.map)
            groups["position"].append(opening.position)
            groups["faction"].append(opening.faction)
            groups["era"].append(_era_name(opening.opening_era))
    return Scores(
        np.array(match_ids, dtype=np.int64),
        np.array(step_indices, dtype=np.int32),
        np.array(top1, dtype=bool),
        np.array(top3, dtype=bool),
        np.array(log_loss, dtype=np.float64),
        {name: np.array(values, dtype=object) for name, values in groups.items()},
    )


def _era_name(first_build: int | None) -> str:
    for patch in BALANCE_PATCHES:
        if patch.first_build == first_build:
            return patch.name
    return "before the table"


@dataclass(frozen=True)
class Summary:
    games: int
    steps: int
    top1: float
    top3: float
    log_loss: float
    top1_interval: tuple[float, float]
    top3_interval: tuple[float, float]
    log_loss_interval: tuple[float, float]


def summarize(
    scores: Scores, mask: np.ndarray | None = None, rounds: int = BOOTSTRAP_ROUNDS, seed: int = 0
) -> Summary:
    """Means over the selected steps, with 95% intervals from resampling whole games.

    The steps of one game are not independent (16 players, one lobby), so the bootstrap
    draws games, not steps.
    """
    if mask is None:
        mask = np.ones(len(scores.top1), dtype=bool)
    match_ids = scores.match_ids[mask]
    games, game_of_step = np.unique(match_ids, return_inverse=True)
    if not len(games):
        nan = (math.nan, math.nan)
        return Summary(0, 0, math.nan, math.nan, math.nan, nan, nan, nan)
    steps_per_game = np.bincount(game_of_step, minlength=len(games)).astype(np.float64)
    sums = {
        name: np.bincount(game_of_step, weights=values[mask].astype(np.float64))
        for name, values in (
            ("top1", scores.top1),
            ("top3", scores.top3),
            ("log_loss", scores.log_loss),
        )
    }
    generator = np.random.default_rng(seed)
    draws = generator.multinomial(len(games), np.full(len(games), 1 / len(games)), size=rounds)
    drawn_steps = draws @ steps_per_game
    intervals = {}
    for name, per_game in sums.items():
        values = np.sort((draws @ per_game) / drawn_steps)
        intervals[name] = (
            float(values[int(0.025 * rounds)]),
            float(values[int(0.975 * rounds) - 1]),
        )
    total = steps_per_game.sum()
    return Summary(
        games=len(games),
        steps=int(total),
        top1=float(sums["top1"].sum() / total),
        top3=float(sums["top3"].sum() / total),
        log_loss=float(sums["log_loss"].sum() / total),
        top1_interval=intervals["top1"],
        top3_interval=intervals["top3"],
        log_loss_interval=intervals["log_loss"],
    )


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


REFERENCE_MODEL = "trigram, faction"


def fit_models(
    training: Sequence[OpeningSteps], models: Sequence[Model] | None = None
) -> dict[str, Model]:
    """The candidate models fitted on the training openings, by name."""
    models = candidate_models() if models is None else list(models)
    return {model.name: model.fit(training) for model in models}


def choose_model(fitted: Mapping[str, Model], validation: Sequence[OpeningSteps]) -> str:
    """The n-gram with the lowest log-loss on the validation openings (ADR 0013)."""
    losses = {
        name: float(score(model, validation).log_loss.mean())
        for name, model in fitted.items()
        if isinstance(model, NgramModel)
    }
    return min(losses, key=lambda name: (losses[name], name))


def report(
    fitted: Mapping[str, Model],
    held_out: Sequence[OpeningSteps],
    split: str,
    best: str,
    raw: tuple[NgramModel, Sequence[OpeningSteps]] | None = None,
    rounds: int = BOOTSTRAP_ROUNDS,
) -> str:
    """The tables of docs/results.md for fitted models scored on `held_out`.

    `best` is the model the detailed tables are about, compared with `REFERENCE_MODEL`.
    `raw` is `REFERENCE_MODEL` fitted on raw orders (`fit_raw`) and the held-out openings
    as raw orders, for one comparison row.
    """
    any_model = next(iter(fitted.values()))
    trained = any_model.frequencies if isinstance(any_model, RepeatModel) else any_model
    games = len({opening.match_id for opening in held_out})
    lines = [
        f"Trained on {trained.training['games']} games ({trained.training['openings']} "
        f"openings), scored on the {split} split: {games} games, {len(held_out)} openings, "
        f"the first {SCORED_STEPS} steps of each. Intervals are 95%, from resampling games.",
        "",
        "## All models",
        "",
    ]
    all_scores = {name: score(model, held_out) for name, model in fitted.items()}
    rows = [
        [name, *_summary_cells(summarize(scores, rounds=rounds))]
        for name, scores in all_scores.items()
    ]
    lines += markdown.table(["model", "top-1", "top-3", "log-loss"], rows)
    chosen = all_scores[best]
    plain = all_scores[REFERENCE_MODEL]
    lines += [
        "",
        f"{len(chosen.top1)} steps scored per model. Chosen on validation log-loss: `{best}`.",
    ]

    if raw is not None:
        raw_model, raw_held_out = raw
        summary = summarize(score(raw_model, raw_held_out), rounds=rounds)
        lines += [
            "",
            f"`{REFERENCE_MODEL}` on raw orders (drags not merged), for comparison with the "
            "measurements in docs/research/game-versions.md and docs/research/maps/: "
            + ", ".join(_summary_cells(summary))
            + f" over {summary.steps} orders.",
        ]

    def compared(mask: np.ndarray) -> list[object]:
        summary = summarize(chosen, mask, rounds)
        plain_summary = summarize(plain, mask, rounds)
        low, high = paired_difference(chosen, plain, mask, rounds)
        return [
            summary.games,
            int(mask.sum()),
            *_summary_cells(summary),
            f"{100 * (summary.top1 - plain_summary.top1):+.1f} "
            f"({100 * low:+.1f} to {100 * high:+.1f})",
        ]

    header = ["games", "steps", "top-1", "top-3", "log-loss", "top-1 vs reference"]
    lines += [
        "",
        f"The tables below are for `{best}`. The last column is its top-1 minus that of",
        f"`{REFERENCE_MODEL}` on the same steps, in points, with a paired interval.",
    ]
    lines += ["", "## By step of the opening", ""]
    rows = []
    for first, last in STEP_BUCKETS:
        mask = (chosen.step_indices >= first) & (chosen.step_indices < last)
        label = f"{first + 1}" if last == first + 1 else f"{first + 1}–{last}"
        rows.append([label, *compared(mask)])
    lines += markdown.table(["step", *header], rows)

    for group in ("map", "faction", "era"):
        lines += ["", f"## By {group}", ""]
        rows = [
            [value, *compared(chosen.groups[group] == value)]
            for value in sorted(set(chosen.groups[group].tolist()), key=str)
        ]
        lines += markdown.table([group, *header], rows)

    lines += ["", "## By map and position", ""]
    for map_name in sorted(set(chosen.groups["map"].tolist()), key=str):
        lines += ["", f"### {map_name}", ""]
        on_map = chosen.groups["map"] == map_name
        positions = set(chosen.groups["position"][on_map].tolist())
        rows = []
        for position in sorted(positions, key=lambda name: position_order(name or "")):
            mask = on_map & (chosen.groups["position"] == position)
            openings = sum(
                1
                for opening in held_out
                if opening.map == map_name and opening.position == position
            )
            cells = compared(mask)
            rows.append([position, openings, *cells[1:]])
        lines += markdown.table(["position", "openings", *header[1:]], rows)
    return "\n".join(lines)


def paired_difference(
    first: Scores,
    second: Scores,
    mask: np.ndarray,
    rounds: int = BOOTSTRAP_ROUNDS,
    seed: int = 0,
    metric: str = "top1",
) -> tuple[float, float]:
    """95% interval of metric(first) - metric(second) over the same steps, resampling games.

    `metric` is ``top1``, ``top3`` or ``log_loss``.
    """
    games, game_of_step = np.unique(first.match_ids[mask], return_inverse=True)
    if not len(games):
        return math.nan, math.nan
    steps = np.bincount(game_of_step, minlength=len(games)).astype(np.float64)
    first_values = getattr(first, metric)[mask].astype(np.float64)
    second_values = getattr(second, metric)[mask].astype(np.float64)
    difference = np.bincount(
        game_of_step, weights=first_values - second_values, minlength=len(games)
    )
    draws = np.random.default_rng(seed).multinomial(
        len(games), np.full(len(games), 1 / len(games)), size=rounds
    )
    values = np.sort((draws @ difference) / (draws @ steps))
    return float(values[int(0.025 * rounds)]), float(values[int(0.975 * rounds) - 1])


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", type=Path, default=dataset_dir())
    parser.add_argument(
        "--train-dataset",
        type=Path,
        default=None,
        help="train on another build of the dataset, to compare definitions of an opening",
    )
    parser.add_argument("--split", default="validation", choices=["validation", "test"])
    parser.add_argument("--rounds", type=int, default=BOOTSTRAP_ROUNDS)
    parser.add_argument("--save", type=Path, default=None, help="where to save the chosen model")


def fit_raw(training: Sequence[OpeningSteps]) -> NgramModel:
    """`REFERENCE_MODEL` fitted on openings of raw orders, for the comparison row of
    `report`."""
    return NgramModel(REFERENCE_MODEL, chain(3)).fit(training)


def run(args: argparse.Namespace) -> int:
    manifest = json.loads((args.dataset / "manifest.json").read_text())
    train_dataset = args.train_dataset or args.dataset
    # The training split is read once for both the steps and the raw orders: each read
    # of it briefly takes several GB.
    training = load_sequences(train_dataset, ["train"])
    raw_model = fit_raw(load_openings(train_dataset, "train", merge=False, frame=training))
    fitted = fit_models(load_openings(train_dataset, "train", frame=training))
    del training
    validation = load_openings(args.dataset, "validation")
    best = choose_model(fitted, validation)
    held_out = validation if args.split == "validation" else load_openings(args.dataset, "test")
    raw = (raw_model, load_openings(args.dataset, args.split, merge=False))
    print(
        f"Dataset `{manifest['name']}` built {manifest['built_at']} "
        f"(code {manifest['code']['commit']}).\n"
    )
    if args.train_dataset:
        trained_on = json.loads((train_dataset / "manifest.json").read_text())
        print(f"Trained on `{trained_on['name']}` built {trained_on['built_at']}.\n")
    print(report(fitted, held_out, args.split, best, raw, args.rounds))
    if args.train_dataset:
        return 0  # a comparison, not the model to keep
    chosen = fitted[best]
    assert isinstance(chosen, NgramModel)
    target = args.save or models_dir() / "ngram_v2.json"
    save_model(chosen, target, manifest)
    print(f"\nsaved {chosen.name!r} to {target}", file=sys.stderr)
    return 0
