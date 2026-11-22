import math

import numpy as np
import pytest

from reason8.baseline import (
    START,
    UNKNOWN,
    NgramModel,
    OpeningSteps,
    RepeatModel,
    chain,
    check_model,
    choose_model,
    fit_models,
    load_model,
    merge_repeats,
    report,
    save_model,
    score,
    summarize,
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


def test_merge_repeats():
    units = ["armmex", "armwin", "armwin", "armwin", "armmex", "armmex"]
    repeats = [False, False, True, True, False, False]
    assert merge_repeats(units, repeats) == ("armmex", "armwin", "armmex", "armmex")


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


def test_trivial_models():
    training = [opening(1), opening(2, ("armmex", "armmex", "armmex", "armlab"))]
    uniform = NgramModel("uniform", ()).fit(training)
    scores = score(uniform, [opening(3)])
    assert np.allclose(scores.log_loss, math.log(len(uniform.vocabulary)))
    assert not scores.top1.any()  # every unit ties, and ties count against the model

    repeat = RepeatModel().fit(training)
    assert repeat.repeat_share == pytest.approx(3 / 7)
    probabilities = repeat.distribution(opening(3, ("armlab", "armlab")), 1)
    assert repeat.vocabulary[int(np.argmax(probabilities))] == "armlab"
    assert math.isclose(probabilities.sum(), 1.0)


def test_score_and_summarize():
    training = [opening(match_id) for match_id in range(5)]
    model = NgramModel("bigram", chain(2)).fit(training)
    held_out = [opening(10), opening(11, ("armmex", "armgone"))]
    scores = score(model, held_out, steps=4)
    assert len(scores.top1) == 4 + 2
    # after armmex the bigram has seen armmex and armwin equally often: a tie, no credit
    assert scores.top1[:4].tolist() == [True, True, False, True]
    assert scores.top3[:4].all()
    assert not scores.top1[5] and not scores.top3[5]  # a unit the model has never seen
    assert scores.groups["era"][0] == "July balance patch"
    summary = summarize(scores, rounds=50)
    assert summary.games == 2 and summary.steps == 6
    assert summary.top1 == pytest.approx(4 / 6)
    low, high = summary.top1_interval
    assert low <= summary.top1 <= high
    only_first = summarize(scores, scores.match_ids == 10, rounds=50)
    assert only_first.top1 == 0.75 and only_first.top1_interval == (0.75, 0.75)


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


def test_choose_and_report():
    training = [opening(n) for n in range(6)] + [opening(n, AIR, "Cortex", "P2") for n in range(6)]
    held_out = [opening(10), opening(11, AIR, "Cortex", "P2")]
    fitted = fit_models(training)
    assert set(fitted) >= {"uniform", "trigram, faction", "trigram, faction, map and position"}
    best = choose_model(fitted, held_out)
    assert isinstance(fitted[best], NgramModel) and best != "uniform"
    text = report(fitted, held_out, "validation", best, (training, held_out), rounds=20)
    assert "## All models" in text
    assert "### Test Valley 1.0" in text
    assert "| P2 |" in text
