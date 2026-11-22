import math
from collections import Counter
from pathlib import Path

import synthetic

from reason8.opening_shift import (
    NextUnitModel,
    Opening,
    accuracy,
    accuracy_difference_interval,
    feature_distance,
    first_factory,
    group_of,
    held_out_scores,
    opening_shape,
    openings,
    shuffled,
    total_variation,
    transfer_scores,
)
from reason8.positions import replay_positions
from reason8.replay import Replay, load_replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay.json"

BOTS = ("armmex", "armmex", "armwin", "armwin", "armlab", "armck")
AIR = ("cormex", "corwin", "corwin", "corap", "corca")


def opening(match, team=0, units=BOTS, faction="Armada", side=0, start=None):
    return Opening(str(match), team, side, faction, start, tuple(units))


def test_openings_from_replay():
    replay = load_replay(FIXTURE)
    found = openings(replay)
    assert len(found) == 16
    assert {o.side for o in found} == {0, 1}
    assert found[0].units
    orders = replay.build_orders(team=found[0].team, until_frame=8 * 60 * 30)
    assert list(found[0].units) == [order.unit for order in orders if order.count > 0]
    assert len(openings(replay, seconds=60)[0].units) < len(found[0].units)


def test_openings_carry_position_role_and_skill():
    replay = Replay(synthetic.with_own_starts_recommended(load_replay(FIXTURE).doc))
    found = openings(replay, map_list={})
    expected = replay_positions(replay, {})
    assert [o.position for o in found] == [expected[o.team].spawn_point for o in found]
    assert len({o.position for o in found}) == 16
    assert {o.role for o in found} == {"front"}
    skills = {player["teamId"]: player["skill"] for player in replay.players}
    assert all(o.skill is not None and str(o.skill) in skills[o.team] for o in found)


def test_openings_off_the_recommended_positions_have_no_position():
    stray = (4300.0, 6000.0)
    replay = synthetic.replay(
        {0: [stray, (1000.0, 9000.0)], 1: [(7000.0, 3000.0), (9000.0, 1000.0)]},
        options=synthetic.start_options(),
    )
    found = openings(replay, map_list={})
    assert [(o.position, o.role) for o in found] == [
        (None, None),
        ("P2", "air"),
        ("P3", "front"),
        ("P4", "air"),
    ]
    # without recommended positions nobody has one
    plain = synthetic.replay({0: [stray], 1: [(7000.0, 3000.0)]})
    assert [o.position for o in openings(plain, map_list={})] == [None, None]


def test_first_factory_and_shape():
    assert first_factory(BOTS) == "bot lab"
    assert first_factory(AIR) == "aircraft plant"
    assert first_factory(["legmex", "legvp"]) == "vehicle plant"
    assert first_factory(["armmex", "armwin"]) == "none"
    assert opening_shape(BOTS) == ("mex", "win", "lab", "ck")
    assert opening_shape(AIR, length=3) == ("mex", "win", "ap")
    assert opening_shape([]) == ()


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
