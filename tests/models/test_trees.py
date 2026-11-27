"""The builder model's file and its reference evaluator (`reason8.models.trees`)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from reason8.models import builder, trees


@pytest.fixture(scope="module")
def synthetic():
    document = builder.synthetic_model()
    tree = document.pop("_booster")
    return document, tree, trees.from_document(json.loads(json.dumps(document)))


def test_the_file_matches_xgboost(synthetic):
    _, tree, model = synthetic
    entries = builder.synthetic_inputs(model, 400, seed=7)
    matrix = np.stack([model.encode(entry["inputs"]) for entry in entries])
    expected = tree.booster.inplace_predict(matrix, iteration_range=(0, tree.rounds))
    margins = tree.booster.inplace_predict(
        matrix, iteration_range=(0, tree.rounds), predict_type="margin"
    )
    assert np.abs(model.margins(matrix) - margins).max() < 1e-5
    assert np.abs(model.class_probabilities(model.margins(matrix)) - expected).max() < 1e-6
    one_by_one = np.array([model.margins_one(row.tolist()) for row in matrix])
    assert np.abs(model.class_probabilities(one_by_one) - expected).max() < 1e-6


def test_the_file_has_categorical_splits_and_a_shared_class(synthetic):
    _, _, model = synthetic
    assert any(tree.categories for tree in model.trees)
    assert any((row > 0).sum() > 1 for row in model.classes.spread)
    assert np.allclose(model.classes.spread.sum(axis=1), 1.0)


def test_encoding():
    feature = trees.Feature("kind", "builder", trees.CATEGORICAL, ("factory", "commander"))
    assert feature.encode("commander") == 1.0
    assert math.isnan(feature.encode("never seen"))
    assert math.isnan(feature.encode(None))
    number = trees.Feature("metal", "economy", trees.NUMERIC)
    assert number.encode(True) == 1.0
    assert number.encode(0.1) == float(np.float32(0.1))
    assert math.isnan(number.encode(None))


def test_the_mask_and_the_choice(synthetic):
    """The same as ``Mask`` and ``Choose`` in ``ai/native/Choice.h``."""
    _, _, model = synthetic
    assert model.can_give("armlab") == {"ck", "flash"}
    assert model.unknown not in model.can_give("not a builder")
    assert model.can_give(None) == set(model.answers) - {model.unknown}
    inputs = {"builder_kind": "factory", "time_s": 400.0, "builder_unit": "armlab"}
    decision = model.decide(inputs, 0.5)
    assert decision.probabilities.sum() == pytest.approx(1.0)
    assert {answer for answer, _ in decision.possible} <= {"ck", "flash"}
    assert sum(p for _, p in decision.possible) == pytest.approx(1.0)
    probabilities = np.zeros(len(model.answers))
    probabilities[model.answers.index("ck")] = 0.3
    probabilities[model.answers.index("flash")] = 0.6
    probabilities[model.answers.index("mex")] = 0.09  # below the threshold: never drawn
    probabilities[model.answers.index(model.unknown)] = 0.01  # never possible
    possible = model.mask(probabilities, {"ck", "flash", "mex"})
    assert [answer for answer, _ in possible] == ["flash", "ck", "mex"]  # most likely first
    assert sum(p for _, p in possible) == pytest.approx(1.0)
    # candidates most likely first: flash 2/3, ck 1/3
    assert model.choose(possible, 0.0) == "flash"
    assert model.choose(possible, 0.66) == "flash"
    assert model.choose(possible, 0.67) == "ck"
    assert model.choose(possible, 0.999) == "ck"
    assert model.mask(probabilities, {"lab"}) == []
    flat = [(f"unit{index}", 1 / 11) for index in range(11)]
    assert model.choose(flat, 0.5) is None  # no answer reaches 10%


def test_the_committed_vectors_hold():
    """The library is tested against these vectors; the evaluator must still give them."""
    vectors = json.loads(builder.VECTORS.read_text())
    model = trees.from_document(vectors["model"])
    assert len(vectors["decisions"]) >= 20
    for entry in vectors["decisions"]:
        decision = model.decide(entry["inputs"], entry["uniform"], set(entry["can_give"]))
        encoded = [None if math.isnan(value) else float(value) for value in decision.row]
        assert encoded == entry["encoded"]
        assert np.abs(decision.probabilities - entry["probabilities"]).max() < vectors["tolerance"]
        assert [answer for answer, _ in decision.possible] == [a for a, _ in entry["possible"]]
        found = np.array([p for _, p in decision.possible])
        assert np.abs(found - [p for _, p in entry["possible"]]).max() < vectors["tolerance"]
        assert decision.answer == entry["answer"]


def test_config_round_trips():
    config = builder.Config().without_skill()
    assert "skill" not in config.groups
    again = builder.Config.from_json(json.loads(json.dumps(config.to_json())))
    assert again == config
    assert again.parameters["min_child_weight"] == 50
    assert again.seed == 0
