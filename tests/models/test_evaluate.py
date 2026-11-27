import math

import numpy as np
import pytest

from reason8.models.evaluate import (
    choose_model,
    fit_models,
    fit_raw,
    paired_difference,
    report,
    score,
    score_probabilities,
    summarize,
)
from reason8.models.ngram import UNKNOWN, NgramModel, RepeatModel, chain
from tests.models.test_ngram import AIR, opening


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


def test_choose_and_report():
    training = [opening(n) for n in range(6)] + [opening(n, AIR, "Cortex", "P2") for n in range(6)]
    held_out = [opening(10), opening(11, AIR, "Cortex", "P2")]
    fitted = fit_models(training)
    assert set(fitted) >= {"uniform", "trigram, faction", "trigram, faction, map and position"}
    best = choose_model(fitted, held_out)
    assert isinstance(fitted[best], NgramModel) and best != "uniform"
    text = report(fitted, held_out, "validation", best, (fit_raw(training), held_out), rounds=20)
    assert "## All models" in text
    assert "### Test Valley 1.0" in text
    assert "| P2 |" in text


def test_score_probabilities_scores_like_score():
    training = [opening(match_id) for match_id in range(5)]
    model = NgramModel("bigram", chain(2)).fit(training)
    held_out = [opening(10), opening(11, ("armmex", "armgone"))]
    expected = score(model, held_out, steps=4)
    rows = [(opening, index) for opening in held_out for index in range(len(opening.steps[:4]))]
    unknown = model.index[UNKNOWN]
    scores = score_probabilities(
        np.array([model.distribution(opening, index) for opening, index in rows]),
        np.array([model.index.get(opening.steps[index], unknown) for opening, index in rows]),
        unknown,
        expected.match_ids,
        expected.step_indices,
        expected.groups,
    )
    for name in ("top1", "top3", "log_loss"):
        assert np.allclose(getattr(scores, name), getattr(expected, name))
    assert paired_difference(scores, expected, np.ones(len(rows), dtype=bool), 20) == (0.0, 0.0)
    low, high = paired_difference(
        scores, expected, np.ones(len(rows), dtype=bool), 20, metric="log_loss"
    )
    assert low == high == 0.0
