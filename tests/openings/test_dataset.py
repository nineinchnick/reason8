import copy
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import polars as pl

from reason8.openings.contact import BY_POSITION, MEASURED, WINDOW
from reason8.openings.dataset import (
    BUILT_AWAY,
    INCLUDED,
    NOT_A_RELEASE,
    REMOVED_UNIT,
    SPLITS,
    UNIT_TWEAKS,
    UNTIL_CONTACT,
    WATER_LEVEL,
    WHOLE_WINDOW,
    WITH_BOTS,
    WRONG_SHAPE,
    build_dataset,
    extract_game,
    first_places_distances,
    game_exclusion,
    load_sequences,
    ordered_faction,
    removed_units,
    split_of,
    stats,
    step_index,
    step_starts,
)
from reason8.openings.extract import opening_orders
from reason8.replays import widgets
from reason8.replays.replay import Replay, load_replay
from tests import synthetic

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay.json"


def fixture_document() -> dict:
    """The fixture replay with recommended positions made from its own starts."""
    return synthetic.with_own_starts_recommended(load_replay(FIXTURE).doc)


def test_split_of_is_a_fixed_function_of_the_match_id():
    assert split_of(12345) == split_of("12345") == split_of(12345)
    counts = Counter(split_of(match_id) for match_id in range(20000))
    for name, share in SPLITS:
        assert abs(counts[name] / 20000 - share / 100) < 0.01


def test_game_exclusion():
    document = fixture_document()
    assert game_exclusion(Replay(document)) is None

    def changed(change):
        changed_document = copy.deepcopy(document)
        change(changed_document)
        return game_exclusion(Replay(changed_document))

    assert changed(lambda d: d["ais"].append({"teamId": 99, "allyTeamId": 0})) == WITH_BOTS
    assert changed(lambda d: d["meta"].update(game="Beyond All Reason pr-1-2-abc")) == NOT_A_RELEASE
    assert changed(lambda d: d["modoptions"].update(tweakdefs1="abc")) == UNIT_TWEAKS
    assert changed(lambda d: d["modoptions"].update(multiplier_metal="2")) == UNIT_TWEAKS
    assert changed(lambda d: d["modoptions"].update(multiplier_metal="1")) is None
    assert changed(lambda d: d["modoptions"].update(map_waterlevel="-50")) == WATER_LEVEL
    assert changed(lambda d: d["players"].pop()) == WRONG_SHAPE


def test_extract_game_has_a_row_per_order():
    replay = Replay(fixture_document())
    extract = extract_game(replay, 77, map_list={}, cutoff=WHOLE_WINDOW)
    assert extract.game["status"] == INCLUDED
    assert extract.game["split"] == split_of(77)
    assert extract.game["build"] == 32018
    assert extract.game["factions"] == "arm cor"
    assert extract.game["positions_shown"] is True
    assert json.loads(extract.game["balance_options"]) == {"naval_balance_tweaks": "1"}
    assert len(extract.players) == 16
    assert {player["position"] for player in extract.players} == {f"P{n}" for n in range(1, 17)}
    assert all(player["on_spot"] for player in extract.players)
    assert {player["won"] for player in extract.players} == {True, False}
    assert {player["cutoff_frame"] for player in extract.players} == {8 * 60 * 30}
    assert {player["cutoff_source"] for player in extract.players} == {WINDOW}
    assert all(player["orders"] == player["orders_in_window"] for player in extract.players)

    orders = opening_orders(replay)
    rows = extract.orders
    assert rows.height == sum(len(team_orders) for team_orders in orders.values())
    for (slot,), player_rows in rows.group_by("player_slot"):
        expected = orders[slot]
        assert player_rows["order_index"].to_list() == list(range(len(expected)))
        assert player_rows["unit"].to_list() == [order.unit for order in expected]
        added = player_rows.filter(pl.col("count") > 0)
        assert added["seq_idx"].to_list() == list(range(added.height))
        assert player_rows.filter(pl.col("count") < 0)["seq_idx"].null_count() == (
            player_rows.height - added.height
        )
        repeats = player_rows["repeat"].to_list()
        frames, units = player_rows["frame"].to_list(), player_rows["unit"].to_list()
        assert repeats[0] is False
        for index in range(1, len(repeats)):
            same = (frames[index], units[index]) == (frames[index - 1], units[index - 1])
            assert repeats[index] == same

    excluded = copy.deepcopy(replay.doc)
    excluded["modoptions"]["map_waterlevel"] = "100"
    extract = extract_game(Replay(excluded), 78, map_list={})
    assert extract.game["status"] == WATER_LEVEL
    assert not extract.players and extract.orders.is_empty()


def test_extract_game_ends_openings_at_first_contact():
    replay = Replay(fixture_document())
    orders = opening_orders(replay)  # players 0, 7 and 8 give orders until frame 5,700
    whole = extract_game(replay, 77, map_list={}, cutoff=WHOLE_WINDOW)
    position_of = {player["player_slot"]: player["position"] for player in whole.players}
    map_name = replay.meta["map"]
    position_cutoffs = {map_name: {position_of[8]: 100}}

    # player 0 was hit at frame 3,000, player 7 not at all; player 8 is not in the state
    # file and has a cutoff for the position; the others have neither
    extract = extract_game(
        replay,
        77,
        map_list={},
        cutoff=UNTIL_CONTACT,
        measured={0: 3000, 7: None},
        position_cutoffs=position_cutoffs,
    )
    assert extract.game["contact_measured"] is True
    players = {player["player_slot"]: player for player in extract.players}
    assert (players[0]["cutoff_frame"], players[0]["cutoff_source"]) == (3000, MEASURED)
    assert (players[7]["cutoff_frame"], players[7]["cutoff_source"]) == (14400, MEASURED)
    assert (players[8]["cutoff_frame"], players[8]["cutoff_source"]) == (3000, BY_POSITION)
    assert (players[1]["cutoff_frame"], players[1]["cutoff_source"]) == (14400, WINDOW)
    rows = extract.orders
    for slot in (0, 7, 8):
        cutoff_frame = players[slot]["cutoff_frame"]
        expected = [order for order in orders[slot] if order.frame <= cutoff_frame]
        player_rows = rows.filter(pl.col("player_slot") == slot)
        assert player_rows["frame"].to_list() == [order.frame for order in expected]
        assert player_rows["order_index"].to_list() == list(range(len(expected)))
        assert players[slot]["orders"] == len(expected)
        assert players[slot]["orders_in_window"] == len(orders[slot])
    assert 0 < players[0]["orders"] < players[0]["orders_in_window"]
    assert players[7]["orders"] == players[7]["orders_in_window"]

    # without measurements and cutoffs nothing is known: the whole window
    extract = extract_game(replay, 77, map_list={}, position_cutoffs={})
    assert extract.game["contact_measured"] is False
    assert {player["cutoff_source"] for player in extract.players} == {WINDOW}


def starts_of(*orders: tuple[int, str, bool]) -> list[bool | None]:
    """`step_starts` of one player's orders, given as (frame, unit, adds units)."""
    rows = pl.DataFrame(
        {
            "match_id": [1] * len(orders),
            "player_slot": [0] * len(orders),
            "frame": [frame for frame, _, _ in orders],
            "unit": [unit for _, unit, _ in orders],
            "added": [added for _, _, added in orders],
        }
    ).with_columns(
        seq_idx=pl.when("added").then(pl.col("added").cast(pl.Int32).cum_sum() - 1),
    )
    return rows.select(step_starts()).to_series().to_list()


def test_step_starts_merges_orders_of_one_frame():
    """One drag of buildings: the same unit in the same frame is one step."""
    assert starts_of((0, "armmex", True), (0, "armmex", True), (0, "armwin", True)) == [
        True,
        False,
        True,
    ]


def test_step_starts_merges_quick_clicks_up_to_six_frames():
    assert starts_of((0, "armpw", True), (6, "armpw", True)) == [True, False]
    assert starts_of((0, "armpw", True), (7, "armpw", True)) == [True, True]


def test_step_starts_chains_runs_of_clicks():
    """Each order is compared with the one before it, not with the first of the run."""
    clicks = [(4 * index, "armpw", True) for index in range(5)]
    assert starts_of(*clicks) == [True, False, False, False, False]
    assert starts_of((0, "armpw", True), (6, "armpw", True), (13, "armpw", True)) == [
        True,
        False,
        True,
    ]


def test_step_starts_needs_the_same_unit_directly_before():
    assert starts_of((0, "armpw", True), (2, "armck", True), (4, "armpw", True)) == [
        True,
        True,
        True,
    ]


def test_step_starts_skips_orders_that_add_nothing():
    """A removal from a factory queue is no step and does not break a run."""
    orders = ((0, "armpw", True), (2, "armck", False), (4, "armpw", True))
    assert starts_of(*orders) == [True, None, False]


def test_step_index_counts_steps_per_player():
    rows = pl.DataFrame(
        {
            "match_id": [1, 1, 1, 1, 1],
            "player_slot": [0, 0, 0, 1, 1],
            "seq_idx": [0, 1, None, 0, 1],
            "frame": [0, 3, 5, 0, 30],
            "unit": ["armpw", "armpw", "armpw", "cormex", "cormex"],
        }
    )
    assert rows.select(step_index()).to_series().to_list() == [0, None, None, 0, 1]


def test_step_starts_with_jobs_as_answers():
    """In the decision table a job is a decision too: it breaks a run of one unit, and
    quick repeats of one job are one step."""
    rows = pl.DataFrame(
        {
            "match_id": [1] * 5,
            "player_slot": [0] * 5,
            "frame": [0, 2, 4, 30, 32],
            "answer": ["armpw", "reclaim", "armpw", "assist", "assist"],
        }
    )
    decides = pl.col("answer").is_not_null()
    starts = rows.select(step_starts(answer="answer", decides=decides)).to_series()
    assert starts.to_list() == [True, True, True, True, False]
    steps = rows.select(step_index(answer="answer", decides=decides)).to_series()
    assert steps.to_list() == [0, 1, 2, 3, None]


def test_first_places_distances_take_the_nearest_of_the_first_three_structures():
    orders = pl.DataFrame(
        {
            "match_id": [1] * 6 + [2, 3],
            "player_slot": [0] * 6 + [0, 0],
            "seq_idx": [0, None, 1, 2, 3, 4, 0, 0],
            "kind": ["factory", "structure", "structure", "structure", "structure", "structure"]
            + ["factory", "structure"],
            "x": [None, 0.0, 900.0, 0.0, 800.0, 0.0, None, 30.0],
            "z": [None, 0.0, 0.0, 1000.0, 0.0, 0.0, None, 40.0],
        }
    )
    starts = pl.DataFrame(
        {
            "match_id": [1, 2, 3],
            "player_slot": [0, 0, 0],
            "start_x": [0.0, 0.0, 0.0],
            "start_z": [0.0, 0.0, 0.0],
        }
    )
    distances = first_places_distances(orders, starts).collect().sort("match_id")
    # a factory unit and a removal do not count, nor the structure after the first three
    assert distances.rows() == [(1, 0, 800.0), (3, 0, 50.0)]


def test_ordered_faction_and_removed_units():
    assert ordered_faction(["cormex", "corwin", "armmex"]) == "Cortex"
    assert ordered_faction(["legmex"]) == "Legion"
    assert ordered_faction([]) is None
    assert removed_units(["legmex", "legmext15", "legmext15"], ["legmex"]) == ["legmext15"]
    assert removed_units(["armmex"], ["armmex"]) == []


def test_build_dataset(tmp_path):
    document = fixture_document()
    # a player who picked Random, and one who orders a unit the newest build does not have
    document["players"][0]["faction"] = "Random"
    tweaked = copy.deepcopy(document)
    tweaked["modoptions"]["tweakunits"] = "abc"
    older = copy.deepcopy(document)
    older["meta"]["game"] = "Beyond All Reason test-31000-abcdef0"
    removed_team = 7  # one of the teams with build orders in the trimmed fixture
    for event in older["events"]:
        if event.get("team") == removed_team and event.get("cmd") == "BUILD":
            event["unit"] = "armgone"
            break
    games = {}
    match_ids = []
    parsed = {}
    for index in range(12):
        match_id = 1000 + index
        name = f"game{index}"
        if index < 11:  # game 11 is not parsed
            parsed[name] = tweaked if index == 0 else older if index == 1 else document
        games[match_id] = name
        match_ids.append(match_id)
    out_tables = synthetic.write_tables(tmp_path / "tables", parsed)
    selection = pl.DataFrame(
        {
            "match_id": match_ids,
            "replay_file_name": [f"{games[m]}.sdfz" for m in match_ids],
            "map": [document["meta"]["map"]] * len(match_ids),
            "start_time": [datetime(2026, 6, 1)] * len(match_ids),
            "game_duration": [1200] * len(match_ids),
            "avg_skill": [25.0] * len(match_ids),
        }
    )
    match_players = pl.DataFrame(
        {"match_id": [1002], "user_id": [5], "old_skill": [30.0], "old_uncertainty": [2.0]}
    )
    out = tmp_path / "datasets" / "openings_v2"
    position_of = {
        player["player_slot"]: player["position"]
        for player in extract_game(Replay(document), 1, map_list={}).players
    }
    settings = {
        "map_list": {},
        "measured": {"game2": {0: 3000, 7: None}, "game11": {0: 1}},
        "position_cutoffs": {document["meta"]["map"]: {position_of[8]: 100}},
    }
    # widget reports: game2 was read, player 3 had an automation widget and player 5 only
    # a disabled one; game3 could not be read; the other games were not read at all
    widgets_dir = tmp_path / "widgets"
    widgets_dir.mkdir()
    pl.from_dicts(
        [
            {"replay_file_name": "game2.sdfz", "reports": 2},
            {"replay_file_name": "game3.sdfz", "reports": 0, "error": "EOFError"},
        ],
        schema=widgets.REPLAY_SCHEMA,
    ).write_parquet(widgets_dir / widgets.REPLAYS_FILE)
    automation_widget = sorted(widgets.AUTOMATION_WIDGETS)[0]

    def widget(name, state):
        return {"name": name, "author": "a", "hash": "h", "state": state, "description": "d"}

    pl.from_dicts(
        [
            {
                "replay_file_name": "game2.sdfz",
                "player_id": 30,
                "team_id": 3,
                "frame": 31,
                "widget_count": 2,
                "truncated": False,
                "widgets": [widget(automation_widget, 1), widget("Some Display", 1)],
            },
            {
                "replay_file_name": "game2.sdfz",
                "player_id": 50,
                "team_id": 5,
                "frame": 31,
                "widget_count": 1,
                "truncated": False,
                "widgets": [widget(automation_widget, 0)],
            },
        ],
        schema=widgets.REPORT_SCHEMA,
    ).write_parquet(widgets_dir / widgets.REPORTS_FILE)
    settings["widgets_dir"] = widgets_dir
    settings["tables_dir"] = out_tables
    manifest = build_dataset(out, selection, match_players, **settings)

    assert manifest["selection"] == {
        "since": "2026-05-23",
        "until": "2026-11-22",
        "maps": [document["meta"]["map"]],
        "games": 12,
        "parsed": 11,
    }
    assert manifest["opening"] == {
        "definition": "docs/decisions/0012-end-openings-at-first-contact.md",
        "window_seconds": 480,
        "cutoff": UNTIL_CONTACT,
        "contact": "a unit of the player other than a scout is hit by an enemy unit",
        "measured_games": 1,
        "position_cutoff_quantile": 0.5,
        "position_cutoff_seconds": settings["position_cutoffs"],
    }
    # of the 149 openings kept: players 0 and 7 of the re-simulated game, and player 8 of
    # each of the 10 games through the position
    assert manifest["counts"]["openings_by_cutoff_source"] == {
        WINDOW: 137,
        BY_POSITION: 10,
        MEASURED: 2,
    }
    assert manifest["counts"]["games_by_status"] == {INCLUDED: 10, UNIT_TWEAKS: 1}
    # player 13 of the fixture places its first extractor 1,011 units from its start
    assert manifest["counts"]["openings_by_status"] == {
        INCLUDED: 149,
        BUILT_AWAY: 10,
        REMOVED_UNIT: 1,
    }
    assert manifest["vocabulary"]["arm cor"]["build"] == 32018
    assert manifest["code"]["commit"]

    games_frame = pl.read_parquet(out / "games.parquet")
    assert games_frame.height == 11
    assert games_frame["replay_file_name"].to_list()[0] == "game0.sdfz"
    openings_frame = pl.read_parquet(out / "openings.parquet")
    assert openings_frame.height == 160
    built_away = openings_frame.filter(pl.col("status") == BUILT_AWAY)
    assert set(built_away["player_slot"]) == {13}
    assert built_away["first_places_distance"].min() > 1000
    assert set(openings_frame.filter(pl.col("faction_picked") == "Random")["faction"]) <= {
        "Armada",
        "Cortex",
    }
    assert openings_frame.filter(pl.col("status") == REMOVED_UNIT)["removed_units"].to_list() == [
        ["armgone"]
    ]
    measured_game = openings_frame.filter(pl.col("match_id") == 1002)
    widget_columns = ["widgets_reported", "widgets", "automation_widgets"]
    by_slot = {row["player_slot"]: row for row in measured_game.iter_rows(named=True)}
    assert [by_slot[3][name] for name in widget_columns] == [
        True,
        sorted([automation_widget, "Some Display"]),
        [automation_widget],
    ]
    assert [by_slot[5][name] for name in widget_columns] == [True, [], []]
    assert [by_slot[0][name] for name in widget_columns] == [False, [], []]
    not_read = openings_frame.filter(pl.col("match_id") != 1002)
    assert not_read.select(widget_columns).null_count().row(0) == (not_read.height,) * 3
    assert manifest["counts"]["openings_with_widget_reports"] == 2
    assert manifest["counts"]["openings_with_automation_widgets"] == 1
    # the fixture game was played with unit control widgets off
    assert not games_frame["unit_control_widgets"].any()
    assert Counter(measured_game["cutoff_source"]) == {MEASURED: 2, BY_POSITION: 1, WINDOW: 13}
    assert measured_game.filter(pl.col("player_slot") == 0)["cutoff_frame"].item() == 3000
    assert 0 < measured_game.filter(pl.col("player_slot") == 0)["orders"].item() < 47
    assert games_frame.filter(pl.col("contact_measured"))["match_id"].to_list() == [1002]

    listed = []
    total_rows = 0
    for split, _ in SPLITS:
        ids = [int(line) for line in (out / "splits" / f"{split}.txt").read_text().split()]
        assert all(split_of(match_id) == split for match_id in ids)
        listed += ids
        rows = pl.read_parquet(out / f"{split}.parquet")
        assert set(rows["match_id"].unique().to_list()) <= set(ids)
        assert rows.height == manifest["counts"]["rows"][split]
        assert rows.filter(pl.col("frame") > pl.col("cutoff_frame")).height == 0
        assert set(rows["cutoff_source"].unique().to_list()) <= {MEASURED, BY_POSITION, WINDOW}
        total_rows += rows.height
    assert sorted(listed) == list(range(1001, 1011))
    assert (
        "armgone"
        not in pl.concat(pl.read_parquet(out / f"{split}.parquet") for split, _ in SPLITS)[
            "unit"
        ].to_list()
    )
    assert total_rows > 0
    assert json.loads((out / "manifest.json").read_text()) == manifest
    assert not out.with_name("openings_v2.building").exists()

    sequences = load_sequences(out)
    with_orders = openings_frame.filter(pl.col("status") == INCLUDED, pl.col("added") > 0)
    assert sequences.height == with_orders.height > 0
    assert all(len(units) > 0 for units in sequences["units"].to_list())
    report = stats(out)
    assert "## Top 20 openings" in report
    assert "## Where openings end" in report
    assert "Supreme Isthmus" in report

    # building again gives the same rows
    again = build_dataset(out, selection, match_players, **settings)
    assert again["counts"] == manifest["counts"]

    # the whole opening window, as before openings ended at first contact
    window = build_dataset(
        tmp_path / "window", selection, match_players, cutoff=WHOLE_WINDOW, **settings
    )
    assert window["opening"]["cutoff"] == WHOLE_WINDOW
    assert window["opening"]["measured_games"] == 0
    assert window["opening"]["position_cutoff_seconds"] is None
    assert window["counts"]["openings_by_cutoff_source"] == {WINDOW: 149}
    assert sum(window["counts"]["rows"].values()) > total_rows
