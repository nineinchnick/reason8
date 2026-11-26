import math
from collections import Counter
from datetime import date
from pathlib import Path

from reason8.analysis import opening_shift
from reason8.analysis.opening_shift import (
    NextUnitModel,
    accuracy,
    accuracy_difference_interval,
    feature_distance,
    group_of,
    held_out_scores,
    shuffled,
    total_variation,
    transfer_scores,
)
from reason8.openings.extract import Opening, first_factory, openings
from reason8.replays.replay import Replay, load_replay
from tests import synthetic

BOTS = ("armmex", "armmex", "armwin", "armwin", "armlab", "armck")
AIR = ("cormex", "corwin", "corwin", "corap", "corca")


def opening(match, team=0, units=BOTS, faction="Armada", side=0, start=None):
    return Opening(str(match), team, side, faction, start, tuple(units))


def test_total_variation():
    assert total_variation(Counter(a=1, b=1), Counter(a=5, b=5)) == 0
    assert total_variation(Counter(a=1), Counter(b=1)) == 1
    assert total_variation(Counter(a=3, b=1), Counter(a=1, b=3)) == 0.5
    assert math.isnan(total_variation(Counter(), Counter(a=1)))


def test_next_unit_model_backs_off():
    model = NextUnitModel().fit([opening(1), opening(2), opening(3, units=AIR, faction="Cortex")])
    assert model.predict(opening(9, units=()), 0) == "armmex"
    assert model.predict(opening(9, units=("armwin", "armwin")), 2) == "armlab"
    # an unseen pair falls back to what follows the last unit alone
    assert model.predict(opening(9, units=("armlab", "armwin")), 2) == "armwin"
    assert model.predict(opening(9, units=(), faction="Cortex"), 0) == "cormex"
    assert model.predict(opening(9, units=(), faction="Legion"), 0) is None
    assert model.score([opening(4)]) == (6, 6)
    assert model.score([opening(4, units=("armmex", "armlab"))]) == (1, 2)


def test_transfer_and_held_out_scores():
    bots = [opening(match) for match in range(4)]
    air = [opening(10 + match, units=AIR, faction="Cortex") for match in range(4)]
    assert accuracy(transfer_scores(bots, bots)) == 1
    assert accuracy(transfer_scores(bots, air)) == 0
    assert accuracy(held_out_scores(bots)) == 1
    # one training match is enough here, and extra games of the other kind do not hurt
    assert accuracy(held_out_scores(bots, training_matches=1)) == 1
    assert accuracy(held_out_scores(bots, extra=air)) == 1
    assert accuracy(held_out_scores(bots[:1], extra=air)) == 0
    low, high = accuracy_difference_interval(
        transfer_scores(bots, bots), held_out_scores(bots), rounds=100
    )
    assert (low, high) == (0, 0)


def test_shuffled_tells_a_real_difference_from_noise():
    def statistic(first, second):
        return feature_distance(first, second, lambda o: first_factory(o.units))

    bots = [opening(match, team) for match in range(10) for team in range(4)]
    air = [
        opening(match, team, units=AIR, faction="Cortex")
        for match in range(10, 20)
        for team in range(4)
    ]
    assert statistic(bots, air) == 1
    mean, high, p_value = shuffled(bots, air, statistic, rounds=200)
    assert mean < high < 1
    assert p_value < 0.01

    mixed = [
        opening(match, team, units=AIR if (match + team) % 2 else BOTS)
        for match in range(20)
        for team in range(4)
    ]
    assert statistic(mixed[:40], mixed[40:]) == 0
    assert shuffled(mixed[:40], mixed[40:], statistic, rounds=200)[2] == 1


def test_group_of():
    assert group_of(29100) == "before Season 3"
    assert group_of(30000) is None
    assert group_of(30236) == "May patch"
    assert group_of(32018) == "since August patch"


def test_load_sample_reads_the_sample_from_the_tables(tmp_path, monkeypatch):
    fixture = Path(__file__).parents[1] / "fixtures" / "replay.json"
    replay = Replay(synthetic.with_own_starts_recommended(load_replay(fixture).doc))
    out = tmp_path / "tables"
    names = [f"2026-11-0{day}_10-00-00-000_x" for day in (1, 2, 3, 4)]
    # names[2] is a build of no group, names[3] is not parsed
    synthetic.write_tables(out, dict.fromkeys(names[:3], replay))
    builds = {names[0]: 32018, names[1]: 31000, names[2]: 30000, names[3]: 32018}
    monkeypatch.setattr(
        opening_shift, "sample_matches", lambda: {f"{n}.sdfz": b for n, b in builds.items()}
    )
    found, matches = opening_shift.load_sample(tables_dir=out)
    expected = openings(replay)
    assert found == expected + expected
    assert matches == {
        expected[0].match: opening_shift.SampleMatch(31000, {"naval_balance_tweaks": "1"})
    }
    found, _ = opening_shift.load_sample(tables_dir=out, until=date(2026, 11, 2))
    assert found == expected
