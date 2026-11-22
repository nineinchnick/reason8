from pathlib import Path

import synthetic

from reason8.openings import first_factory, opening_shape, openings
from reason8.positions import replay_positions
from reason8.replay import Replay, load_replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay.json"

BOTS = ("armmex", "armmex", "armwin", "armwin", "armlab", "armck")
AIR = ("cormex", "corwin", "corwin", "corap", "corca")


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
