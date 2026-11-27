import math

import numpy as np
import pytest

from reason8.models.ngram import (
    START,
    UNKNOWN,
    NgramModel,
    OpeningSteps,
    chain,
    check_model,
    load_model,
    merge_steps,
    save_model,
)

BOTS = ("armmex", "armmex", "armwin", "armlab", "armck")
AIR = ("cormex", "corwin", "corap", "corca")


def opening(match_id, steps=BOTS, faction="Armada", position="P1", build=31000):
    return OpeningSteps(
        match_id=match_id,
        faction=faction,
        map="Test Valley 1.0",
        position=position,
        role="front",
        build=build,
        opening_era=30755,
        steps=tuple(steps),
    )


def test_merge_steps():
    units = ["armmex", "armwin", "armwin", "armwin", "armmex", "armmex"]
    starts = [True, True, False, False, True, True]
    assert merge_steps(units, starts) == ("armmex", "armwin", "armmex", "armmex")


def test_chain():
    assert chain(1) == ((("faction",), 0), ((), 0))
    assert chain(2, features=()) == (((), 1), ((), 0))
    assert chain(2, condition=("map", "position")) == (
        (("faction", "map", "position"), 1),
        (("faction",), 1),
        (("faction", "map", "position"), 0),
        (("faction",), 0),
        ((), 0),
    )


def test_ngram_predicts_and_backs_off():
    training = [opening(1), opening(2), opening(3, AIR, "Cortex")]
    model = NgramModel("trigram", chain(3)).fit(training)
    assert model.vocabulary[-1] == UNKNOWN
    assert NgramModel.context(model.levels[0], opening(9), 0) == ("Armada", START, START)

    def top(test_opening, index):
        probabilities = model.distribution(test_opening, index)
        assert math.isclose(probabilities.sum(), 1.0)
        assert (probabilities > 0).all()
        return model.vocabulary[int(np.argmax(probabilities))]

    assert top(opening(9), 0) == "armmex"
    assert top(opening(9), 2) == "armwin"
    assert top(opening(9, AIR, "Cortex"), 2) == "corap"
    # an unseen pair falls back to what follows the last step
    assert top(opening(9, ("armlab", "armwin", "armlab")), 2) == "armlab"
    # a faction never seen falls back to the frequencies of all units
    assert top(opening(9, faction="Legion"), 0) == "armmex"
    assert model.trained_on.first_build == model.trained_on.last_build == 31000
    assert model.trained_on.units == frozenset(BOTS + AIR)


def test_most_likely_reads_the_counts_by_back_off():
    training = [opening(1), opening(2, ("armmex", "armlab")), opening(3, AIR, "Cortex")]
    model = NgramModel("trigram", chain(3)[:-1]).fit(training)
    assert model.most_likely(opening(9), 0) == "armmex"
    # the longest context seen decides (after one armmex alone it would be armmex)
    assert model.most_likely(opening(9, ("armmex", "armmex")), 2) == "armwin"
    # a tie goes to the unit counted first
    assert model.most_likely(opening(9), 1) == "armmex"
    assert model.most_likely(opening(9, ("armwin", "armwin")), 2) == "armlab"
    # without a level that ignores the faction, an unseen faction gets nothing
    assert model.most_likely(opening(9, faction="Legion"), 0) is None


def test_save_load_and_check(tmp_path):
    training = [opening(1, build=31400), opening(2, AIR, "Cortex", build=31900)]
    model = NgramModel("trigram", chain(3, condition=("map", "position"))).fit(training)
    path = tmp_path / "model.json"
    save_model(model, path, {"name": "openings_v1", "built_at": "now", "counts": {}})
    loaded = load_model(path)
    assert loaded.levels == model.levels
    assert loaded.vocabulary == model.vocabulary
    assert loaded.trained_on == model.trained_on
    for test_opening in (opening(3), opening(4, AIR, "Cortex", position="P2")):
        for index in range(4):
            assert np.allclose(
                loaded.distribution(test_opening, index), model.distribution(test_opening, index)
            )
    game_units = ["armcom", "corcom", *BOTS, *AIR]
    assert check_model(loaded, "Beyond All Reason test-31900-abcdef0", game_units).level == "ok"
    assert check_model(loaded, "Beyond All Reason test-31900-abcdef0", game_units[:-1]).level == (
        "refuse"
    )
    assert check_model(loaded, "Beyond All Reason test-35000-abcdef0").level == "refuse"
    with pytest.raises(ValueError):
        NgramModel.from_json({"format": "something else"})
