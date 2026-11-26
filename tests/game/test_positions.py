import math
from datetime import date
from pathlib import Path

import pytest

from reason8.game.maps import parse_map_list, parse_start_positions
from reason8.game.positions import (
    FROM_GAME,
    FROM_MAP_LIST,
    check,
    default_boxes,
    game_headers,
    game_shape,
    position_order,
    recommended_positions,
    replay_layout,
    replay_positions,
    spot_radii,
    start_setup,
    team_sides,
)
from reason8.replays import tables
from reason8.replays.replay import Replay, load_replay
from tests import synthetic

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay.json"
MAP_LIST = parse_map_list(synthetic.MAP_LIST_YAML)
NO_MAP_LIST = {}

# Near the made-up spawn points P1 (3000, 7000) and P2 (1000, 9000), and their side-two
# counterparts P3 (7000, 3000) and P4 (9000, 1000).
BOTTOM_LEFT = [(3100.0, 6900.0), (950.0, 9050.0)]
TOP_RIGHT = [(7040.0, 2970.0), (9000.0, 1200.0)]
BOXES = {0: synthetic.BOTTOM_LEFT, 1: synthetic.TOP_RIGHT}


def game(sides=None, **arguments):
    arguments.setdefault("options", synthetic.start_options())
    arguments.setdefault("boxes", BOXES)
    return synthetic.replay(sides or {0: BOTTOM_LEFT, 1: TOP_RIGHT}, **arguments)


def test_game_shape_counts_teams_and_the_largest_team():
    assert game_shape(game()) == (2, 2)
    assert game_shape(game({0: BOTTOM_LEFT, 1: TOP_RIGHT[:1]})) == (2, 2)
    assert game_shape(game({0: BOTTOM_LEFT[:1], 1: TOP_RIGHT[:1]})) == (2, 1)


def test_positions_are_the_nearest_spawn_points_of_the_teams_side():
    positions = replay_positions(game(), NO_MAP_LIST)
    assert [positions[team].spawn_point for team in range(4)] == ["P1", "P2", "P3", "P4"]
    # the two sides' spawn points are different positions, at the same places of their lists
    assert [positions[team].index for team in range(4)] == [0, 1, 0, 1]
    assert [positions[team].role for team in range(4)] == ["front", "air", "front", "air"]
    assert [positions[team].side for team in range(4)] == [0, 0, 1, 1]
    assert positions[0].distance == pytest.approx(math.hypot(100, 100))
    assert all(position.on_spot for position in positions.values())


def test_positions_do_not_depend_on_ally_team_ids():
    swapped = replay_positions(game({0: TOP_RIGHT, 1: BOTTOM_LEFT}), NO_MAP_LIST)
    assert [swapped[team].spawn_point for team in range(4)] == ["P3", "P4", "P1", "P2"]
    assert [swapped[team].side for team in range(4)] == [1, 1, 0, 0]


def test_a_far_start_keeps_its_nearest_spawn_point_but_is_not_on_the_spot():
    layout, _ = replay_layout(game(), NO_MAP_LIST)
    # P1 and P2 are 2,828 map units apart; the other side is further
    assert spot_radii(layout)["P1"] == pytest.approx(math.hypot(2000, 2000) / 2)
    stray = (4300.0, 6000.0)  # across the middle of nowhere, 1,640 units from P1
    positions = replay_positions(game({0: [stray, BOTTOM_LEFT[1]], 1: TOP_RIGHT}), NO_MAP_LIST)
    assert (positions[0].spawn_point, positions[0].on_spot) == ("P1", False)
    assert positions[0].distance == pytest.approx(math.hypot(1300, 1000))
    # two players on one spot both get it
    doubled = replay_positions(
        game({0: [BOTTOM_LEFT[0], (3000.0, 7100.0)], 1: TOP_RIGHT}), NO_MAP_LIST
    )
    assert [doubled[team].spawn_point for team in (0, 1)] == ["P1", "P1"]


def test_team_side_comes_from_the_whole_team():
    layout, _ = replay_layout(game(), NO_MAP_LIST)
    # one player starts across the middle of the map; his team is still the bottom-left one
    starts = {0: [(1000.0, 9000.0), (5200.0, 4800.0)], 1: [(9000.0, 1000.0), (7000.0, 3000.0)]}
    assert team_sides(layout, starts) == {0: 0, 1: 1}
    # each side is taken once, even when both teams are nearer the same one
    assert team_sides(layout, {0: [(1000.0, 9000.0)], 1: [(4000.0, 6000.0)]}) == {0: 0, 1: 1}
    assert team_sides(layout, {}) == {}


def test_the_layout_matches_the_games_teams_and_team_size():
    duel = game({0: BOTTOM_LEFT[:1], 1: TOP_RIGHT[:1]})
    positions = replay_positions(duel, NO_MAP_LIST)
    assert [positions[team].spawn_point for team in (0, 1)] == ["P1", "P3"]
    # no layout for 3 against 3: no positions, and the game shows none
    larger = game({0: [*BOTTOM_LEFT, (2000.0, 8000.0)], 1: [*TOP_RIGHT, (8000.0, 2000.0)]})
    assert replay_positions(larger, NO_MAP_LIST) == {}
    assert start_setup(larger, NO_MAP_LIST).overlay is False


def test_the_games_own_positions_win_over_the_map_list():
    moved = {
        "positions": {**synthetic.START_POSITIONS["positions"], "P1": {"x": 3500, "y": 6500}},
        "team": synthetic.START_POSITIONS["team"],
    }
    own = game(options=synthetic.start_options(positions=moved))
    found, source = recommended_positions(own, MAP_LIST)
    assert source == FROM_GAME
    assert found == parse_start_positions(moved)
    assert replay_positions(own, MAP_LIST)[0].distance == pytest.approx(math.hypot(400, 400))

    without = game(options=synthetic.start_options(positions=None))
    assert recommended_positions(without, MAP_LIST)[1] == FROM_MAP_LIST
    assert replay_positions(without, MAP_LIST)[0].spawn_point == "P1"
    assert recommended_positions(without, NO_MAP_LIST) == (None, None)
    assert replay_positions(without, NO_MAP_LIST) == {}
    # an empty option is how the lobby sends "no recommended positions"
    empty = game(options={"mapmetadata_startpos": ""})
    assert recommended_positions(empty, MAP_LIST)[1] == FROM_MAP_LIST
    unknown_map = game(map_name="No Such Map 1.0", options={})
    assert replay_positions(unknown_map, MAP_LIST) == {}


def test_start_setup_tells_whether_the_game_showed_the_positions():
    shown = start_setup(game(), MAP_LIST)
    assert (shown.positions_source, shown.overlay) == (FROM_GAME, True)
    hidden = start_setup(game(options=synthetic.start_options(positions=None)), MAP_LIST)
    assert (hidden.positions_source, hidden.overlay) == (FROM_MAP_LIST, False)
    nothing = start_setup(game(options={}), NO_MAP_LIST)
    assert (nothing.positions_source, nothing.overlay) == (None, False)
    assert (nothing.default_boxes, nothing.boxes_source) == (None, None)


def test_default_boxes_against_the_games_own_set():
    assert default_boxes(game(), NO_MAP_LIST) == (True, FROM_GAME)
    # which team has which box does not matter
    swapped = game(boxes={0: synthetic.TOP_RIGHT, 1: synthetic.BOTTOM_LEFT})
    assert default_boxes(swapped, NO_MAP_LIST) == (True, FROM_GAME)
    moved = game(boxes={0: {**synthetic.BOTTOM_LEFT, "right": 0.6}, 1: synthetic.TOP_RIGHT})
    assert default_boxes(moved, NO_MAP_LIST) == (False, FROM_GAME)
    # a third box of a team without players is ignored
    spare = game(boxes={**BOXES, 2: {"left": 0.4, "top": 0.4, "right": 0.6, "bottom": 0.6}})
    assert default_boxes(spare, NO_MAP_LIST) == (True, FROM_GAME)
    assert default_boxes(game(boxes={}), NO_MAP_LIST) == (None, None)


def test_a_box_override_counts_only_when_it_changes_the_boxes():
    same = game(options=synthetic.start_options(override=synthetic.BOX_SETS["2"]))
    assert default_boxes(same, NO_MAP_LIST) == (True, FROM_GAME)
    custom = {
        "startboxes": [
            {"poly": [{"x": 0, "y": 100}, {"x": 100, "y": 200}]},
            {"poly": [{"x": 100, "y": 0}, {"x": 180, "y": 100, "strength": 0.5}]},
        ]
    }
    changed = game(options=synthetic.start_options(override=custom))
    assert default_boxes(changed, NO_MAP_LIST) == (False, FROM_GAME)
    # a value that is no arrangement is no override
    not_one = game(options={**synthetic.start_options(), "mapmetadata_startbox_override": "0"})
    assert default_boxes(not_one, NO_MAP_LIST) == (True, FROM_GAME)


def test_default_boxes_against_the_map_list_cannot_prove_a_change():
    older = synthetic.start_options(box_sets=None)
    assert default_boxes(game(options=older), MAP_LIST) == (True, FROM_MAP_LIST)
    moved = game(
        options=older, boxes={0: {**synthetic.BOTTOM_LEFT, "right": 0.6}, 1: synthetic.TOP_RIGHT}
    )
    # the list may have changed since the game was played
    assert default_boxes(moved, MAP_LIST) == (None, FROM_MAP_LIST)
    assert default_boxes(game(options=older), NO_MAP_LIST) == (None, None)


def test_a_curved_default_box_is_compared_by_its_bounding_box():
    curved = {
        "2": {
            "startboxes": [
                {
                    "poly": [
                        {"x": 0, "y": 100},
                        {"x": 60, "y": 110, "strength": 0.5},
                        {"x": 100, "y": 200},
                        {"x": 0, "y": 200},
                    ]
                },
                {"poly": [{"x": 100, "y": 0}, {"x": 200, "y": 100}]},
            ]
        }
    }
    replay = game(options=synthetic.start_options(box_sets=curved))
    assert default_boxes(replay, NO_MAP_LIST) == (True, FROM_GAME)


def test_positions_of_a_real_replay():
    document = synthetic.with_own_starts_recommended(load_replay(FIXTURE).doc)
    replay = Replay(document)
    positions = replay_positions(replay, NO_MAP_LIST)
    teams = replay.teams()
    assert set(positions) == set(teams)
    assert all(position.on_spot and position.distance == 0 for position in positions.values())
    for ally_team_id in (0, 1):
        side = [positions[team] for team in teams if teams[team].ally_team_id == ally_team_id]
        assert len({position.side for position in side}) == 1
        # eight players on the eight spawn points of their side
        assert len({position.spawn_point for position in side}) == 8
        assert sorted(position.index for position in side) == list(range(8))
    assert len({position.spawn_point for position in positions.values()}) == 16
    removed = document["players"][0]
    del removed["startPos"]
    assert removed["teamId"] not in replay_positions(Replay(document), NO_MAP_LIST)


def test_position_order_is_numeric():
    assert sorted(["P10", "P2", "P1 sea"], key=position_order) == ["P1 sea", "P2", "P10"]


def test_check_reports_setup_and_distances():
    replays = [
        game(),
        game({0: TOP_RIGHT, 1: [(4300.0, 6000.0), BOTTOM_LEFT[1]]}),
        game(options=synthetic.start_options(positions=None, box_sets=None)),
    ]
    text = check(replays, MAP_LIST)
    assert f"## {synthetic.MAP}" in text and "3 games" in text
    assert "- positions from: game: 2, map list: 1" in text
    assert "- positions shown in the game: False: 1, True: 2" in text
    assert "- default start boxes: True: 3" in text
    assert "starts on a spot: 11 of 12 (91.7%)" in text
    assert "- positions not shown: 4 of 4 (100.0%)" in text
    assert "| P1 | front | 3 | 66.7% |" in text
    assert "| P3 | front | 3 | 100.0% |" in text
    assert "no recommended positions" in check([game(options={})], NO_MAP_LIST)


def test_game_headers_read_the_games_from_the_tables(tmp_path):
    parsed = tmp_path / "parsed"
    replays = {
        "2026-11-01_00-00-00-000_a": game(),
        "2026-11-01_01-00-00-000_b": game({0: TOP_RIGHT, 1: [(4300.0, 6000.0), BOTTOM_LEFT[1]]}),
        "2026-11-02_00-00-00-000_c": game(options=synthetic.start_options(positions=None)),
        "2026-11-02_01-00-00-000_d": game(map_name="Elsewhere 1.0"),
    }
    with_ai = game()
    with_ai.doc["ais"] = [{"aiId": 0, "teamId": 9, "allyTeamId": 1, "shortName": "BARb"}]
    replays["2026-11-02_02-00-00-000_e"] = with_ai
    for name, replay in replays.items():
        synthetic.write_parsed(parsed, name, replay)
    out = synthetic.write_tables(parsed)
    # parsed after the tables were written: read from its JSON
    late = "2026-11-02_03-00-00-000_f"
    replays[late] = game()
    synthetic.write_parsed(parsed, late, replays[late])

    headers = game_headers(tables.open_source(parsed, out), [synthetic.MAP])
    kept = [name for name in replays if name[-1] in "abcf"]
    assert [header.teams() for header in headers] == [replays[name].teams() for name in kept]
    assert check(headers, MAP_LIST) == check([replays[name] for name in kept], MAP_LIST)
    source = tables.open_source(parsed, out, since=date(2026, 11, 2))
    assert len(game_headers(source, [synthetic.MAP])) == 2
