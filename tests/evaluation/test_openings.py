"""Tests for `reason8 eval openings` (no game or dataset needed)."""

import polars as pl

from reason8.evaluation.openings import (
    SEPARATE,
    accuracy_interval,
    balanced,
    classify,
    collapse,
    distinct_openings,
    features,
)


def test_collapse():
    assert collapse(["armmex", "armmex", "armwin", "armmex"]) == ["armmex", "armwin", "armmex"]


def test_features():
    found = features(["armmex", "armmex", "armwin", "armck"], "P3")
    assert found == {
        "u:armmex": 1,
        "u:armwin": 1,
        "u:armck": 1,
        "b:armmex>armwin": 1,
        "b:armwin>armck": 1,
        "p:P3": 1.0,
    }
    separate = features(
        ["armmex", "armck", "armwin", "armck"], "P3", {"armmex", "armwin"}, SEPARATE
    )
    # the factory units' run is collapsed once structures are taken out
    assert separate["sb:armmex>armwin"] == 1 and separate["fu:armck"] == 1
    assert "fb:armck>armck" not in separate


def test_distinct_openings():
    assert distinct_openings([["a", "b"], ["a", "a", "b"], ["b", "a"]]) == 2


def openings(source, sequence, count, position="P1"):
    return [
        {
            "group": f"{source}-{index}",
            "source": source,
            "position": position,
            "faction": "Armada",
            "units": list(sequence),
        }
        for index in range(count)
    ]


def test_classify_tells_different_openings_apart():
    rows = openings("bot", ["armmex", "armwin", "armlab"], 20)
    rows += openings("human", ["armmex", "armsolar", "armvp"], 20)
    classified = classify(pl.DataFrame(rows))
    share, low, high = accuracy_interval(classified)
    assert share == 1.0 and low == 1.0


def test_balanced_draws_as_many_humans_per_position():
    bot = pl.DataFrame(openings("bot", ["a"], 3, "P1") + openings("bot", ["a"], 1, "P2"))
    human = pl.DataFrame(openings("human", ["b"], 10, "P1") + openings("human", ["b"], 10, "P2"))
    both = balanced(bot, human)
    counts = both.group_by("source", "position").len().sort("source", "position")
    assert counts["len"].to_list() == [3, 1, 3, 1]
