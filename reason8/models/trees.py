"""The builder model's file and its reference evaluator, in plain Python and NumPy.

The game library evaluates the model of ADR 0019 with its own code, without XGBoost, from
the file this module reads (``reason8.builder-trees/1``, described in
``docs/reference/builder-model.md``). This module is the reference the library is tested
against. It does not import XGBoost; `reason8.models.builder` writes the file from a
trained booster and checks this module against XGBoost's own predictions.

Deciding the next order of an idle builder, step by step (`TreeFile.decide`):

1. **Encode** every input (`TreeFile.encode`): a number as a 32-bit float, a name as the
   index of its category, anything unknown or absent as missing (NaN).
2. **Margins**: each class starts at its ``base_score`` and adds the leaf value each of
   its trees reaches. A node sends a missing input to its ``default_left`` side, a number
   below its ``threshold`` left and the rest right, and a category in its set right and
   any other category left.
3. **Class probabilities**: the softmax of the margins.
4. **Answer probabilities**: a class stands for one answer, or for several rare answers
   that share its probability by fixed weights (`Classes`). This is what the library's
   model gives the bot: a probability per answer (``AnswerModel::Predict`` in
   ``ai/native/Model.h``).

The bot then masks and chooses (``ai/native/Choice.h``); `mask` and `choose` do the same,
so that the test vectors cover the whole decision:

5. **Mask**: the answers the builder the order is for cannot give, and those of
   probability zero, are removed, the rest rescaled to sum to one and sorted, most likely
   first (ties keep the order of ``answers``). The unknown answer is never one a builder
   can give.
6. **Choose**: the answers of at least ``choice.threshold`` (10%) are the candidates; a
   uniform number u in [0, 1) times their total probability picks the first candidate,
   most likely first, at which the running sum exceeds it. No candidate leaves the order
   to BARb.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

FORMAT = "reason8.builder-trees/1"
NUMERIC = "numeric"
CATEGORICAL = "categorical"
LEAF = -1


@dataclass(frozen=True)
class Feature:
    """One input of the model: how the library encodes it."""

    name: str
    group: str
    type: str  # NUMERIC or CATEGORICAL
    categories: tuple[str, ...] = ()

    def encode(self, value: Any) -> float:
        """The value as the trees see it: a 32-bit float, or NaN when missing."""
        if value is None:
            return math.nan
        if self.type == CATEGORICAL:
            try:
                return float(self.categories.index(str(value)))
            except ValueError:
                return math.nan  # a name not seen in training goes the missing way
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        number = float(value)
        return math.nan if math.isnan(number) else float(np.float32(number))


@dataclass
class Tree:
    """One regression tree: parallel arrays over its nodes, node 0 the root."""

    class_index: int
    feature: np.ndarray  # int32, LEAF for leaves
    threshold: np.ndarray  # float32: numeric splits
    left: np.ndarray  # int32
    right: np.ndarray  # int32
    default_left: np.ndarray  # bool: where a missing input goes
    value: np.ndarray  # float32: the leaf values
    categories: dict[int, frozenset[int]] = field(default_factory=dict)  # node -> right set
    _table: tuple[np.ndarray, np.ndarray] | None = field(default=None, repr=False)

    @property
    def nodes(self) -> int:
        return len(self.feature)

    def leaf(self, row: Sequence[float]) -> int:
        """The leaf one encoded row reaches."""
        node = 0
        while self.feature[node] != LEAF:
            value = row[self.feature[node]]
            if math.isnan(value):
                node = self.left[node] if self.default_left[node] else self.right[node]
            elif node in self.categories:
                inside = value >= 0 and value == int(value) and int(value) in self.categories[node]
                node = self.right[node] if inside else self.left[node]
            else:
                node = self.left[node] if value < self.threshold[node] else self.right[node]
        return int(node)

    def leaves(self, matrix: np.ndarray) -> np.ndarray:
        """The leaf each row of an encoded matrix reaches (the same as `leaf`, for many)."""
        node = np.zeros(len(matrix), dtype=np.int32)
        rows = np.arange(len(matrix))
        active = self.feature[node] != LEAF
        while active.any():
            current = node[active]
            values = matrix[rows[active], self.feature[current]]
            missing = np.isnan(values)
            go_left = values < self.threshold[current]
            if self.categories:
                table, row_of = self._category_table()
                split = row_of[current]
                categorical = split >= 0
                codes = np.nan_to_num(values[categorical], nan=-1.0).astype(np.int64)
                valid = (codes >= 0) & (codes < table.shape[1])
                inside = np.zeros(len(codes), dtype=bool)
                inside[valid] = table[split[categorical][valid], codes[valid]]
                go_left[categorical] = ~inside
            go_left = np.where(missing, self.default_left[current], go_left)
            node[active] = np.where(go_left, self.left[current], self.right[current])
            active = self.feature[node] != LEAF
        return node

    def _category_table(self) -> tuple[np.ndarray, np.ndarray]:
        """The categorical splits as a lookup: ``table[row_of[node], code]`` is whether the
        code goes right at that node (``row_of`` is -1 for other nodes)."""
        if self._table is None:
            row_of = np.full(self.nodes, -1, dtype=np.int64)
            width = 1 + max(max(codes, default=0) for codes in self.categories.values())
            table = np.zeros((len(self.categories), width), dtype=bool)
            for row, (node, codes) in enumerate(sorted(self.categories.items())):
                row_of[node] = row
                table[row, list(codes)] = True
            self._table = (table, row_of)
        return self._table


@dataclass
class Classes:
    """Which answers each class stands for: ``spread[c, a]`` is the share of class c's
    probability that answer a gets (1 for a class of one answer)."""

    spread: np.ndarray  # (classes, answers)


@dataclass
class TreeFile:
    """A builder model read from its file."""

    name: str
    answers: list[str]
    unknown: str
    features: list[Feature]
    classes: Classes
    base_score: np.ndarray  # (classes,) float32
    trees: list[Tree]
    builders: dict[str, dict[str, Any]]  # builder type -> kind, moves, build power, answers
    threshold: float
    document: dict[str, Any]

    @property
    def nodes(self) -> int:
        return sum(tree.nodes for tree in self.trees)

    # --- inputs

    def encode(self, inputs: Mapping[str, Any]) -> np.ndarray:
        """The inputs of one decision, by feature name, as the row the trees read (an
        absent input is missing)."""
        return np.array(
            [feature.encode(inputs.get(feature.name)) for feature in self.features],
            dtype=np.float32,
        )

    # --- the trees

    def margins(self, matrix: np.ndarray) -> np.ndarray:
        """(rows, classes): the base score plus the leaf values of each class's trees."""
        matrix = np.atleast_2d(np.asarray(matrix, dtype=np.float32))
        total = np.tile(self.base_score.astype(np.float64), (len(matrix), 1))
        for tree in self.trees:
            total[:, tree.class_index] += tree.value[tree.leaves(matrix)]
        return total

    def margins_one(self, row: Sequence[float]) -> list[float]:
        """The margins of one encoded row, tree by tree without NumPy: what the library
        does for one decision."""
        total = [float(score) for score in self.base_score]
        for tree in self.trees:
            total[tree.class_index] += float(tree.value[tree.leaf(row)])
        return total

    def class_probabilities(self, margins: np.ndarray) -> np.ndarray:
        shifted = margins - margins.max(axis=-1, keepdims=True)
        exponents = np.exp(shifted)
        return exponents / exponents.sum(axis=-1, keepdims=True)

    # --- answers

    def answer_probabilities(self, margins: np.ndarray) -> np.ndarray:
        """Steps 3 and 4 for the margins of some rows: (rows, answers)."""
        return self.class_probabilities(margins) @ self.classes.spread

    def can_give(self, builder_unit: str | None) -> set[str]:
        """The answers a builder of this type can give, by the file's ``builders`` (the
        unit files the model was trained with); every answer but the unknown one for a
        type the file does not list. In the game the bot reads the unit definitions as
        the game loaded them instead (``CanGive`` in ``ai/native/NextOrder.cpp``)."""
        found = self.builders.get(builder_unit) if builder_unit is not None else None
        if found is None:
            return {answer for answer in self.answers if answer != self.unknown}
        return {self.answers[index] for index in found["answers"]}

    def mask(self, probabilities: Sequence[float], can_give: set[str]) -> list[tuple[str, float]]:
        """Step 5, as ``Mask`` in ``Choice.h``: the possible answers, rescaled, most likely
        first."""
        kept = [
            (answer, float(probability))
            for answer, probability in zip(self.answers, probabilities, strict=True)
            if probability > 0 and answer in can_give
        ]
        total = sum(probability for _, probability in kept)
        if total <= 0:
            return []
        rescaled = [(answer, probability / total) for answer, probability in kept]
        return sorted(rescaled, key=lambda item: -item[1])  # stable: ties keep their order

    def choose(self, possible: Sequence[tuple[str, float]], uniform: float) -> str | None:
        """Step 6, as ``Choose`` in ``Choice.h``: the answer drawn, or None when no possible
        answer reaches the threshold (the order is left to BARb)."""
        candidates = [(answer, p) for answer, p in possible if p >= self.threshold]
        if not candidates:
            return None
        target = min(max(uniform, 0.0), 1.0) * sum(p for _, p in candidates)
        running = 0.0
        chosen = candidates[-1][0]
        for answer, probability in candidates:
            running += probability
            if target < running:
                chosen = answer
                break
        return chosen

    def decide(
        self, inputs: Mapping[str, Any], uniform: float, can_give: set[str] | None = None
    ) -> Decision:
        """The next order of one idle builder: the inputs by name (``builder_unit`` names
        its type, for the mask unless `can_give` is given) and a uniform number for the
        draw. Walks the trees one by one, as the library does."""
        row = self.encode(inputs)
        margins = np.array([self.margins_one(row.tolist())])
        probabilities = self.answer_probabilities(margins)[0]
        allowed = can_give if can_give is not None else self.can_give(inputs.get("builder_unit"))
        possible = self.mask(probabilities, allowed)
        return Decision(row, probabilities, allowed, possible, self.choose(possible, uniform))


@dataclass
class Decision:
    """One decision: the encoded row, the probability of every answer (what the model
    gives the bot), the answers the builder can give, the possible answers after the mask
    (most likely first) and the chosen one (None: left to BARb)."""

    row: np.ndarray
    probabilities: np.ndarray
    can_give: set[str]
    possible: list[tuple[str, float]]
    answer: str | None


def from_document(document: Mapping[str, Any]) -> TreeFile:
    """A model from its parsed file."""
    if document.get("format") != FORMAT:
        raise ValueError(f"not a builder model file: format {document.get('format')!r}")
    answers = list(document["answers"])
    features = [
        Feature(
            name=entry["name"],
            group=entry["group"],
            type=entry["type"],
            categories=tuple(entry.get("categories", ())),
        )
        for entry in document["features"]
    ]
    spread = np.zeros((len(document["classes"]), len(answers)), dtype=np.float64)
    for position, entry in enumerate(document["classes"]):
        spread[position, entry["answers"]] = entry["weights"]
    trees = []
    for entry in document["trees"]:
        trees.append(
            Tree(
                class_index=int(entry["class"]),
                feature=np.array(entry["feature"], dtype=np.int32),
                threshold=np.array(entry["threshold"], dtype=np.float32),
                left=np.array(entry["left"], dtype=np.int32),
                right=np.array(entry["right"], dtype=np.int32),
                default_left=np.array(entry["default_left"], dtype=bool),
                value=np.array(entry["value"], dtype=np.float32),
                categories={
                    int(node): frozenset(int(code) for code in codes)
                    for node, codes in entry.get("categories", [])
                },
            )
        )
    return TreeFile(
        name=document["name"],
        answers=answers,
        unknown=document["choice"]["unknown"],
        features=features,
        classes=Classes(spread),
        base_score=np.array(document["base_score"], dtype=np.float32),
        trees=trees,
        builders={
            unit: {**entry, "answers": list(entry["answers"])}
            for unit, entry in document["builders"].items()
        },
        threshold=float(document["choice"]["threshold"]),
        document={key: value for key, value in document.items() if key != "trees"},
    )


def load(path: Path) -> TreeFile:
    return from_document(json.loads(path.read_text()))
