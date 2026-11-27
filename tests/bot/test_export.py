"""Tests for `reason8 bot export` (no game or dataset needed)."""

import polars as pl

from reason8.bot.check import choose_opening
from reason8.bot.export import Step, ai_opening, opening_steps
from reason8.game.unitdefs import UnitDef

UNIT_DEFS = {
    "armmex": UnitDef("armmex", {"extractsmetal": 0.001}),
    "armwin": UnitDef("armwin", {"windgenerator": 25}),
    "armdrag": UnitDef("armdrag", {"health": 3000}),
    "armlab": UnitDef("armlab", {"buildoptions": ["armck", "armpw"], "workertime": 150}),
    "armap": UnitDef("armap", {"buildoptions": ["armca"], "workertime": 150}),
    "armck": UnitDef("armck", {"speed": 40}),
    "armpw": UnitDef("armpw", {"speed": 80}),
    "armca": UnitDef("armca", {"speed": 120}),
}


def test_opening_steps_merges_drags_and_counts_factory_units():
    rows = pl.DataFrame(
        {
            "unit": ["armmex", "armmex", "armmex", "armlab", "armpw", "armwin", "armwin"],
            "kind": ["structure"] * 4 + ["factory"] + ["structure"] * 2,
            "count": [1, 1, 1, 1, 5, 1, 1],
            "frame": [0, 0, 0, 90, 300, 400, 600],
            "repeat": [False, True, True, False, False, False, False],
            "x": [10.0, 20.0, 30.0, 40.0, 40.0, 50.0, 60.0],
            "z": [1.0, 2.0, 3.0, 4.0, 4.0, 5.0, 6.0],
        }
    )
    assert opening_steps(rows) == (
        Step("armmex", "structure", 3, ((10.0, 1.0), (20.0, 2.0), (30.0, 3.0))),
        Step("armlab", "structure", 1, ((40.0, 4.0),)),
        Step("armpw", "factory", 5),
        Step("armwin", "structure", 1, ((50.0, 5.0),)),
        Step("armwin", "structure", 1, ((60.0, 6.0),)),
    )


def test_ai_opening():
    steps = [
        Step("armmex", "structure", 3, ((1.0, 2.0), (3.0, 4.0), (5.0, 6.0))),
        Step("armck", "factory", 1),  # before any factory
        Step("armlab", "structure", 1),  # no place known
        Step("armdrag", "structure", 4),
        Step("armpw", "factory", 2),
        Step("armap", "structure", 1),
        Step("armca", "factory", 1),  # the second factory's
        Step("armnuke", "structure", 1),
    ]
    played = ai_opening(steps, UNIT_DEFS)
    assert played["commander"] == ["armmex", "armmex", "armmex", "armlab", "armap"]
    assert played["places"] == [[1, 2], [3, 4], [5, 6], None, None]
    assert played["factories"] == {"armlab": ["armpw", "armpw"]}
    assert played["tasks"] == {"armmex": "mex", "armlab": "factory", "armap": "factory"}
    assert played["dropped"] == {"no task": 4, "not in the first factory": 2, "unknown unit": 1}


def test_choose_opening():
    openings = [
        {"side": "armada", "map": "Isthmus", "position": "P1", "start": [100, 100]},
        {"side": "armada", "map": "Isthmus", "position": "P2", "start": [900, 100]},
        {"side": "cortex", "map": "Isthmus", "position": "P1", "start": [100, 100]},
        {"side": "armada", "commander": []},
    ]
    assert choose_opening(openings, "armada", "Isthmus", (850, 150))["position"] == "P2"
    assert choose_opening(openings, "cortex", "Isthmus", (850, 150))["position"] == "P1"
    assert choose_opening(openings, "armada", "Glitters", (850, 150)) is openings[3]
    assert choose_opening(openings, "cortex", "Glitters", None) is None
    # several openings per position: the variant the AI chose
    variants = [{**openings[0], "variant": index} for index in range(3)]
    assert choose_opening(variants, "armada", "Isthmus", (90, 90), variant=2)["variant"] == 2
    assert choose_opening(variants, "armada", "Isthmus", (90, 90), variant=7)["variant"] == 0


def test_ai_opening_keeps_the_first_factory_past_the_cap():
    steps = [Step("armwin", "structure", 40), Step("armlab", "structure", 1)]
    steps += [Step("armmex", "structure", 3)]
    played = ai_opening(steps, UNIT_DEFS)
    assert played["commander"] == ["armwin"] * 29 + ["armlab"]
    assert played["dropped"] == {"after the commander's last structure": 11 + 3}


def test_typical_openings_keeps_the_most_likely_and_draws_the_rest():
    from reason8.bot.export import Candidate, typical_openings
    from reason8.models.ngram import NgramModel, OpeningSteps, chain

    key = ("Isthmus", "P1", "Armada")
    common = ["armmex"] * 3 + ["armwin"] * 12
    training = [
        OpeningSteps(index, "Armada", *key[:2], None, None, None, tuple(common))
        for index in range(20)
    ]
    model = NgramModel("bigram", chain(2)).fit(training)
    candidates = [
        Candidate(index, 0, tuple(Step(unit, "structure", 1) for unit in common[:-1] + [unit]))
        for index, unit in enumerate(["armwin", "armmex", "armsolar", "armlab", "armrad", "armllt"])
    ]
    chosen, scored = typical_openings(model, key, candidates, count=3)
    assert scored == 6 and len(chosen) == 3
    assert chosen[0][0].match_id == 0  # the one the model finds most likely comes first
    assert chosen[0][1] >= max(score for _, score in chosen[1:])
    assert typical_openings(model, key, candidates, count=3)[0] == chosen  # reproducible


def test_reaction_table():
    from reason8.analysis.reactions import IDLE_SCHEMA
    from reason8.bot.export import reaction_table

    rows = []
    for index in range(10):  # builders of the band, early: 8 answered after 1..8 s, 2 not
        rows.append(
            {
                "replay": "g",
                "team": 0,
                "unit_id": index,
                "unit": "armck",
                "kind": "builder",
                "frame": 300,
                "skill": 35.0,
                "clicked_frame": 300 + 30 * (index + 1) if index < 8 else None,
                "any_frame": None,
            }
        )
    table = reaction_table(pl.DataFrame(rows, schema=IDLE_SCHEMA))
    early = table["builder"][0]
    assert early["until_seconds"] == 180 and early["events"] == 10 and early["answered"] == 0.8
    assert len(early["quantiles"]) == 19 and early["quantiles"][9] == 4.5
    assert table["factory"][0] == {
        "until_seconds": 180,
        "events": 0,
        "answered": 0.0,
        "quantiles": [],
    }


def test_choose_opening_at_the_logged_position():
    openings = [
        {"side": "armada", "map": "Isthmus", "position": "P1", "start": [100, 100], "variant": 0},
        {"side": "armada", "map": "Isthmus", "position": "P2", "start": [900, 100], "variant": 0},
        {"side": "armada", "map": "Isthmus", "position": "P2", "start": [900, 100], "variant": 1},
    ]
    # the replay's start is near P1, but the AI's commander stood at P2 and it said so
    chosen = choose_opening(openings, "armada", "Isthmus", (100, 100), variant=1, position="P2")
    assert chosen is openings[2]
    assert choose_opening(openings, "armada", "Isthmus", (100, 100), position="P9") is openings[0]
