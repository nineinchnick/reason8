"""Frequency and n-gram baselines for the next build of an opening.

Before any learned model we need to know what counting scores. Every model here predicts
the unit of the next step of an opening from the steps before it and what is known before
the game: the player's faction, the map and the start position. A step is one decision:
the orders of one drag (the same unit in the same frame) are merged into one step. The
dataset is `reason8.openings.dataset` (ADR 0012: an opening ends at the player's first
contact with the enemy); how the models are scored is
`reason8.models.evaluate` (ADR 0013).

The n-gram models interpolate from specific contexts to general ones with Witten-Bell
smoothing: a context's counts are trusted as much as it has seen different next units,
and the rest of the probability goes to the next, more general context, down to every
unit being equally likely. So every model gives every unit a probability, and log-loss
is defined for all of them.

The chosen model is saved as JSON with what it was trained on (`TrainedOn`), and
`load_model()` plus `check_model()` tell whether it fits a given game version.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from reason8.game.versions import Compatibility, TrainedOn, check_game_version
from reason8.openings.dataset import load_sequences
from reason8.paths import data_dir

FORMAT = "reason8.ngram/1"
START = "<start>"
UNKNOWN = "<unknown>"


@dataclass(frozen=True)
class OpeningSteps:
    """One player's opening as a sequence of steps, with what is known before the game."""

    match_id: int | str  # the dataset's match id; a replay's match name in the measurements
    faction: str | None
    map: str | None
    position: str | None
    role: str | None
    build: int | None
    opening_era: int | None
    steps: tuple[str, ...]


def merge_steps(units: Sequence[str], starts: Sequence[bool]) -> tuple[str, ...]:
    """The steps of an opening: the units of the orders that start a step
    (`reason8.openings.dataset.step_starts`)."""
    return tuple(unit for unit, start in zip(units, starts, strict=True) if start)


def load_openings(
    directory: Path, split: str, merge: bool = True, frame: pl.DataFrame | None = None
) -> list[OpeningSteps]:
    """The openings of one split of the dataset, as steps (or as raw orders without `merge`)."""
    sequences = load_sequences(directory, [split]) if frame is None else frame
    openings = []
    for row in sequences.iter_rows(named=True):
        units = row["units"]
        steps = merge_steps(units, row["starts"]) if merge else tuple(units)
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

    def most_likely(self, opening: OpeningSteps, index: int) -> str | None:
        """The unit counted most often after the most specific context seen in training.

        This reads the counts by back-off instead of interpolating them: the first level
        whose context was seen decides, ties go to the unit counted first. None when no
        level has seen its context. It is the plain frequency baseline of the measurements
        in docs/research/.
        """
        for level, table in zip(self.levels, self.tables, strict=True):
            seen = table.get(self.context(level, opening, index))
            if seen is not None:
                indices, counts, _, _ = seen
                return self.vocabulary[indices[int(np.argmax(counts))]]
        return None

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


Model = NgramModel | RepeatModel


# --- the saved model


def models_dir() -> Path:
    return data_dir() / "models"


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
    """Whether the model may be used with a game version (ADR 0015)."""
    if model.trained_on is None:
        raise ValueError(f"model {model.name!r} does not record what it was trained on")
    return check_game_version(model.trained_on, game_version, unit_definitions)
