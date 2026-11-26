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


def test_built_units(tmp_path):
    from reason8.evaluation.openings import built_units
    from tests.openings.test_contact import hit, state_lines, write_state

    names = {"armcom": 1, "corcom": 2, "armflea": 3, "cormex": 4, "corak": 5}

    def finished(frame, team, unit):
        return {
            "t": "finished",
            "f": frame,
            "u": 100 + frame,
            "d": names[unit],
            "team": team,
            "x": 0,
            "z": 0,
        }

    events = [
        finished(30, 0, "armcom"),  # the commander: left out
        finished(900, 0, "armflea"),
        finished(950, 2, "cormex"),
        hit(1000, 0, "armcom", 2, "corak"),  # team 0 meets the enemy
        finished(1200, 0, "armflea"),  # after contact: left out
        finished(1300, 2, "corak"),  # team 2 has no contact: kept
    ]
    built = built_units(write_state(tmp_path / "s.jsonl.gz", state_lines(events)))
    assert built == {0: ["armflea"], 2: ["cormex", "corak"]}
