"""Tests for the measurement on the decision table, on made-up steps."""

import numpy as np
import polars as pl

from reason8.context import measure
from reason8.models.ngram import UNKNOWN


def steps(games: int, seed: int) -> pl.DataFrame:
    """Openings of two steps per player: a mex, then a wind turbine when the wind is strong
    and a solar collector when it is weak; one rare unit."""
    generator = np.random.default_rng(seed)
    rows = []
    for match_id in range(games):
        for player in range(4):
            wind = float(generator.uniform(0, 20))
            second = "armwin" if wind > 10 else "armsolar"
            if match_id == 0 and player == 0:
                second = "armrare"
            for step, unit in enumerate(("armmex", second)):
                rows.append(
                    {
                        "match_id": match_id,
                        "player_slot": player,
                        "step_idx": step,
                        "order_index": step,
                        "unit": unit,
                        "faction": "Armada",
                        "map": "Test Valley 1.0",
                        "position": f"P{player}",
                        "role": "front",
                        "previous_1": "<start>" if step == 0 else "armmex",
                        "wind": wind,
                    }
                )
    return pl.DataFrame(rows)


def test_tree_model_learns_from_context(monkeypatch):
    monkeypatch.setattr(measure, "MIN_CLASS_STEPS", 5)
    history = ["faction", "map", "position", "role", "step_idx", "previous_1"]
    train, validation, held_out = steps(40, 0), steps(10, 1), steps(10, 2)
    plain = measure.TreeModel("history", history, threads=1).fit(train, validation)
    windy = measure.TreeModel("wind", [*history, "wind"], threads=1).fit(train, validation)
    assert windy.classes == ["armmex", "armsolar", "armwin"]
    assert windy.vocabulary == ["armmex", "armrare", "armsolar", "armwin", UNKNOWN]
    probabilities = windy.probabilities(held_out)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert (probabilities > 0).all()  # the rare unit and unknown units share the last class
    plain_scores, wind_scores = plain.score(held_out), windy.score(held_out)
    second = held_out["step_idx"].to_numpy() == 1
    assert wind_scores.top1[second].mean() > 0.9
    assert wind_scores.log_loss.mean() < plain_scores.log_loss.mean()
    assert "wind" in windy.gain_by_feature()


def test_variants():
    groups = {
        "history": ["previous_1"],
        "time": ["time_s"],
        "pace": ["since_previous_s"],
        "economy": ["metal"],
        "own_units": ["own_done_mex"],
    }
    assert measure.variants(groups) == [
        ("trees: history", ["previous_1"]),
        ("trees: history + time", ["previous_1", "time_s"]),
        ("trees: history + pace", ["previous_1", "since_previous_s"]),
        ("trees: history + economy", ["previous_1", "metal"]),
        ("trees: history + own_units", ["previous_1", "own_done_mex"]),
        ("trees: history + all context", ["previous_1", "time_s", "metal", "own_done_mex"]),
    ]


def test_mask_rescales_what_a_builder_can_give():
    from reason8.context import builder_measure

    probabilities = np.array([[0.5, 0.3, 0.2], [0.5, 0.3, 0.2]])
    mask = np.array([[True, False, True], [True, True, True]])
    masked, removed = builder_measure.apply_mask(probabilities, mask)
    assert np.allclose(masked, [[0.5 / 0.7, 0.0, 0.2 / 0.7], [0.5, 0.3, 0.2]])
    assert np.allclose(removed, [0.3, 0.0])


def test_builder_variants():
    from reason8.context import builder_measure

    groups = {
        "history": builder_measure.history_features(["mex"]),
        "builder": ["builder_kind"],
        **{name: [f"{name}_column"] for name in builder_measure.ADDED_GROUPS},
    }
    found = dict(builder_measure.variants(groups, ["mex"]))
    reference = found[builder_measure.REFERENCE]
    assert reference == [*groups["history"], "builder_kind"]
    model = found[builder_measure.MODEL]
    assert [column for column in model if column not in reference] == [
        f"{name}_column" for name in builder_measure.MODEL_GROUPS
    ]
    assert "skill_column" not in found[builder_measure.WITHOUT_SKILL]
    short = found[builder_measure.SHORT_HISTORY]
    assert "previous_1" in short and "previous_2" not in short
