"""Frequency and n-gram baselines for the next build of an opening.

Usage::

    uv run python -m reason8.baseline                  # train on train, score validation
    uv run python -m reason8.baseline --split test     # the final numbers (docs/results.md)

Before any learned model we need to know what counting scores. Every model here predicts
the unit of the next step of an opening from the steps before it and what is known before
the game: the player's faction, the map and the start position. A step is one decision:
the orders of one drag (the same unit in the same frame) are merged into one step. The
evaluation protocol is ADR 0018; the dataset is `reason8.opening_dataset` (ADR 0017 and
ADR 0019: an opening ends at the player's first contact with the enemy).

The n-gram models interpolate from specific contexts to general ones with Witten-Bell
smoothing: a context's counts are trusted as much as it has seen different next units,
and the rest of the probability goes to the next, more general context, down to every
unit being equally likely. So every model gives every unit a probability, and log-loss
is defined for all of them.

The chosen model is saved as JSON with what it was trained on (`TrainedOn`), and
`load_model()` plus `check_model()` tell whether it fits a given game version.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from reason8 import match_dumps
from reason8.game_versions import BALANCE_PATCHES, Compatibility, TrainedOn, check_game_version
from reason8.opening_dataset import dataset_dir, load_sequences
from reason8.positions import position_order

FORMAT = "reason8.ngram/1"
START = "<start>"
UNKNOWN = "<unknown>"
# Steps scored per opening. The first 30 hold the first factory and its first units, and
# keep long openings from outweighing the others; an opening that ends at first contact
# before that is scored whole.
SCORED_STEPS = 30
STEP_BUCKETS = ((0, 1), (1, 5), (5, 10), (10, 20), (20, 30))
BOOTSTRAP_ROUNDS = 1000


@dataclass(frozen=True)
class OpeningSteps:
    """One player's opening as a sequence of steps, with what is known before the game."""

    match_id: int
    faction: str | None
    map: str | None
    position: str | None
    role: str | None
    build: int | None
    opening_era: int | None
    steps: tuple[str, ...]


def merge_repeats(units: Sequence[str], repeats: Sequence[bool]) -> tuple[str, ...]:
    """The steps of an opening: an order that repeats the one before it in the same frame
    (one drag or click) is part of the same step."""
    return tuple(unit for unit, repeat in zip(units, repeats, strict=True) if not repeat)


def load_openings(
    directory: Path, split: str, merge: bool = True, frame: pl.DataFrame | None = None
) -> list[OpeningSteps]:
    """The openings of one split of the dataset, as steps (or as raw orders without `merge`)."""
    sequences = load_sequences(directory, [split]) if frame is None else frame
    openings = []
    for row in sequences.iter_rows(named=True):
        units = row["units"]
        steps = merge_repeats(units, row["repeats"]) if merge else tuple(units)
        openings.append(
            OpeningSteps(
                match_id=row["match_id"],
                faction=row["faction"],
                map=row["map"],
                position=row["position"],
                role=row["role"],
                build=row["build"],
                opening_era=row["opening_era"],
                steps=steps,
            )
        )
    return openings


# A level of a model is the game features it is told and how many previous steps it sees.
Level = tuple[tuple[str, ...], int]


def chain(
    order: int, features: Sequence[str] = ("faction",), condition: Sequence[str] = ()
) -> tuple[Level, ...]:
    """Levels from the most specific context to the most general one.

    An n-gram of `order` sees ``order - 1`` previous steps and the `features`. With a
    `condition` (e.g. map and position) every history length is first tried with it and
    then without it: (condition, 2), (features, 2), (condition, 1), (features, 1), ...
    The last level knows nothing: the frequency of each unit.
    """
    levels: list[Level] = []
    told = tuple(features)
    conditioned = tuple(dict.fromkeys((*told, *condition)))
    for history in range(order - 1, -1, -1):
        if condition:
            levels.append((conditioned, history))
        levels.append((told, history))
    if told:
        levels.append(((), 0))
    return tuple(levels)


class NgramModel:
    """Witten-Bell interpolated n-gram over the steps of openings."""

    def __init__(self, name: str, levels: Sequence[Level]) -> None:
        self.name = name
        self.levels = tuple((tuple(features), history) for features, history in levels)
        self.vocabulary: list[str] = []
        self.index: dict[str, int] = {}
        # per level: context -> (unit indices, counts, total, distinct units)
        self.tables: list[dict[tuple, tuple[np.ndarray, np.ndarray, float, int]]] = []
        self.trained_on: TrainedOn | None = None
        self.training: dict[str, Any] = {}
        self._cache: dict[tuple, np.ndarray] = {}

    @staticmethod
    def context(level: Level, opening: OpeningSteps, index: int) -> tuple:
        features, history = level
        before = (START,) * history + opening.steps[:index]
        return (
            *(getattr(opening, feature) for feature in features),
            *before[len(before) - history :],
        )

    def fit(self, openings: Iterable[OpeningSteps], steps: int | None = None) -> NgramModel:
        """Count every step of every opening (the first `steps` only, when given)."""
        openings = list(openings)
        counts: list[dict[tuple, Counter]] = [defaultdict(Counter) for _ in self.levels]
        units: Counter = Counter()
        for opening in openings:
            for index, unit in enumerate(opening.steps[:steps]):
                units[unit] += 1
                for level, table in zip(self.levels, counts, strict=True):
                    table[self.context(level, opening, index)][unit] += 1
        self.vocabulary = sorted(units) + [UNKNOWN]
        self.index = {unit: position for position, unit in enumerate(self.vocabulary)}
        self.tables = [
            {
                context: (
                    np.array([self.index[unit] for unit in seen], dtype=np.int32),
                    np.array(list(seen.values()), dtype=np.float64),
                    float(sum(seen.values())),
                    len(seen),
                )
                for context, seen in table.items()
            }
            for table in counts
        ]
        builds = [opening.build for opening in openings if opening.build is not None]
        if builds:
            self.trained_on = TrainedOn(min(builds), max(builds), frozenset(units))
        self.training = {
            "openings": len(openings),
            "games": len({opening.match_id for opening in openings}),
            "steps": sum(units.values()),
        }
        self._cache = {}
        return self

    def distribution(self, opening: OpeningSteps, index: int) -> np.ndarray:
        """Probability of every unit of the vocabulary (the last is any unseen unit)."""
        contexts = tuple(self.context(level, opening, index) for level in self.levels)
        cached = self._cache.get(contexts)
        if cached is not None:
            return cached
        probabilities = np.full(len(self.vocabulary), 1.0 / len(self.vocabulary))
        for table, context in zip(reversed(self.tables), reversed(contexts), strict=True):
            seen = table.get(context)
            if seen is None:
                continue
            indices, counts, total, distinct = seen
            mixed = distinct * probabilities
            mixed[indices] += counts
            probabilities = mixed / (total + distinct)
        self._cache[contexts] = probabilities
        return probabilities

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "name": self.name,
            "levels": [[list(features), history] for features, history in self.levels],
            "vocabulary": self.vocabulary,
            "tables": [
                [
                    [list(context), indices.tolist(), counts.astype(int).tolist()]
                    for context, (indices, counts, _, _) in table.items()
                ]
                for table in self.tables
            ],
            "trained_on": self.trained_on.to_json() if self.trained_on else None,
            "training": self.training,
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> NgramModel:
        if document.get("format") != FORMAT:
            raise ValueError(f"not an n-gram model: {document.get('format')!r}")
        model = cls(document["name"], [(tuple(f), h) for f, h in document["levels"]])
        model.vocabulary = list(document["vocabulary"])
        model.index = {unit: position for position, unit in enumerate(model.vocabulary)}
        model.tables = []
        for table in document["tables"]:
            loaded = {}
            for context, indices, counts in table:
                counts_array = np.array(counts, dtype=np.float64)
                loaded[tuple(context)] = (
                    np.array(indices, dtype=np.int32),
                    counts_array,
                    float(counts_array.sum()),
                    len(indices),
                )
            model.tables.append(loaded)
        trained_on = document.get("trained_on")
        model.trained_on = TrainedOn.from_json(trained_on) if trained_on else None
        model.training = dict(document.get("training") or {})
        return model


class RepeatModel:
    """Predicts that a player does again what they just did.

    The previous step's unit gets the share of training steps that repeat the step before;
    the rest follows the faction's unit frequencies. The first step has no previous one.
    """

    def __init__(self, name: str = "repeat the previous step") -> None:
        self.name = name
        self.frequencies = NgramModel("faction frequency", chain(1))
        self.repeat_share = 0.0

    @property
    def vocabulary(self) -> list[str]:
        return self.frequencies.vocabulary

    @property
    def index(self) -> dict[str, int]:
        return self.frequencies.index

    def fit(self, openings: Iterable[OpeningSteps], steps: int | None = None) -> RepeatModel:
        openings = list(openings)
        self.frequencies.fit(openings, steps)
        repeated = total = 0
        for opening in openings:
            sequence = opening.steps[:steps]
            for index in range(1, len(sequence)):
                total += 1
                repeated += sequence[index] == sequence[index - 1]
        self.repeat_share = repeated / total if total else 0.0
        return self

    def distribution(self, opening: OpeningSteps, index: int) -> np.ndarray:
        probabilities = self.frequencies.distribution(opening, index)
        previous = self.index.get(opening.steps[index - 1]) if index else None
        if previous is None:
            return probabilities
        mixed = (1 - self.repeat_share) * probabilities
        mixed[previous] += self.repeat_share
        return mixed


def candidate_models() -> list[NgramModel | RepeatModel]:
    """The trivial baselines, then the n-grams, most general first."""
    return [
        NgramModel("uniform", ()),
        NgramModel("unit frequency", chain(1, features=())),
        NgramModel("unit frequency per faction", chain(1)),
        RepeatModel(),
        NgramModel("bigram, faction", chain(2)),
        NgramModel("trigram, faction", chain(3)),
        NgramModel("4-gram, faction", chain(4)),
        NgramModel("trigram, faction and map", chain(3, condition=("map",))),
        NgramModel("trigram, faction, map and role", chain(3, condition=("map", "role"))),
        NgramModel("trigram, faction, map and position", chain(3, condition=("map", "position"))),
        NgramModel("4-gram, faction, map and position", chain(4, condition=("map", "position"))),
    ]


# --- evaluation


@dataclass
class Scores:
    """Per scored step: the game, the opening's groups, and how the model did."""

    match_ids: np.ndarray
    step_indices: np.ndarray
    top1: np.ndarray
    top3: np.ndarray
    log_loss: np.ndarray  # natural log
    groups: dict[str, np.ndarray]  # map, position, faction, era per step


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


def _table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


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


Model = NgramModel | RepeatModel
REFERENCE_MODEL = "trigram, faction"


def fit_models(
    training: Sequence[OpeningSteps], models: Sequence[Model] | None = None
) -> dict[str, Model]:
    """The candidate models fitted on the training openings, by name."""
    models = candidate_models() if models is None else list(models)
    return {model.name: model.fit(training) for model in models}


def choose_model(fitted: Mapping[str, Model], validation: Sequence[OpeningSteps]) -> str:
    """The n-gram with the lowest log-loss on the validation openings (ADR 0018)."""
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
    raw: tuple[Sequence[OpeningSteps], Sequence[OpeningSteps]] | None = None,
    rounds: int = BOOTSTRAP_ROUNDS,
) -> str:
    """The tables of docs/results.md for fitted models scored on `held_out`.

    `best` is the model the detailed tables are about, compared with `REFERENCE_MODEL`.
    `raw` is (training, held-out) openings of raw orders, for one comparison row.
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
    lines += _table(["model", "top-1", "top-3", "log-loss"], rows)
    chosen = all_scores[best]
    plain = all_scores[REFERENCE_MODEL]
    lines += [
        "",
        f"{len(chosen.top1)} steps scored per model. Chosen on validation log-loss: `{best}`.",
    ]

    if raw is not None:
        raw_model = NgramModel(REFERENCE_MODEL, chain(3)).fit(raw[0])
        summary = summarize(score(raw_model, raw[1]), rounds=rounds)
        lines += [
            "",
            f"`{REFERENCE_MODEL}` on raw orders (drags not merged), for comparison with the "
            "measurements in docs/game-versions.md and docs/maps/: "
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
    lines += _table(["step", *header], rows)

    for group in ("map", "faction", "era"):
        lines += ["", f"## By {group}", ""]
        rows = [
            [value, *compared(chosen.groups[group] == value)]
            for value in sorted(set(chosen.groups[group].tolist()), key=str)
        ]
        lines += _table([group, *header], rows)

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
        lines += _table(["position", "openings", *header[1:]], rows)
    return "\n".join(lines)


def paired_difference(
    first: Scores, second: Scores, mask: np.ndarray, rounds: int = BOOTSTRAP_ROUNDS, seed: int = 0
) -> tuple[float, float]:
    """95% interval of top-1(first) - top-1(second) over the same steps, resampling games."""
    games, game_of_step = np.unique(first.match_ids[mask], return_inverse=True)
    if not len(games):
        return math.nan, math.nan
    steps = np.bincount(game_of_step, minlength=len(games)).astype(np.float64)
    difference = np.bincount(
        game_of_step,
        weights=first.top1[mask].astype(np.float64) - second.top1[mask].astype(np.float64),
        minlength=len(games),
    )
    draws = np.random.default_rng(seed).multinomial(
        len(games), np.full(len(games), 1 / len(games)), size=rounds
    )
    values = np.sort((draws @ difference) / (draws @ steps))
    return float(values[int(0.025 * rounds)]), float(values[int(0.975 * rounds) - 1])


# --- the saved model


def models_dir() -> Path:
    return match_dumps.data_dir() / "models"


def save_model(model: NgramModel, path: Path, dataset: Mapping[str, Any]) -> None:
    """Write the model with what it was trained on: the builds, units and dataset."""
    document = model.to_json()
    document["saved_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    document["dataset"] = {
        key: dataset.get(key) for key in ("name", "format", "built_at", "code", "counts")
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, separators=(",", ":")) + "\n")


def load_model(path: Path) -> NgramModel:
    return NgramModel.from_json(json.loads(path.read_text()))


def check_model(
    model: NgramModel, game_version: str | None, unit_definitions: Iterable[str] | None = None
) -> Compatibility:
    """Whether the model may be used with a game version (ADR 0012)."""
    if model.trained_on is None:
        raise ValueError(f"model {model.name!r} does not record what it was trained on")
    return check_game_version(model.trained_on, game_version, unit_definitions)


def main(argv: list[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    argument_parser.add_argument("--dataset", type=Path, default=dataset_dir())
    argument_parser.add_argument(
        "--train-dataset",
        type=Path,
        default=None,
        help="train on another build of the dataset, to compare definitions of an opening",
    )
    argument_parser.add_argument("--split", default="validation", choices=["validation", "test"])
    argument_parser.add_argument("--rounds", type=int, default=BOOTSTRAP_ROUNDS)
    argument_parser.add_argument(
        "--save", type=Path, default=None, help="where to save the chosen model"
    )
    args = argument_parser.parse_args(argv)
    manifest = json.loads((args.dataset / "manifest.json").read_text())
    train_dataset = args.train_dataset or args.dataset
    fitted = fit_models(load_openings(train_dataset, "train"))
    validation = load_openings(args.dataset, "validation")
    best = choose_model(fitted, validation)
    held_out = validation if args.split == "validation" else load_openings(args.dataset, "test")
    raw = (
        load_openings(train_dataset, "train", merge=False),
        load_openings(args.dataset, args.split, merge=False),
    )
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


if __name__ == "__main__":
    sys.exit(main())
