import copy
import json
from collections import Counter
from compression import zstd
from datetime import datetime
from pathlib import Path

import polars as pl

from reason8.openings.contact import BY_POSITION, MEASURED, WINDOW
from reason8.openings.dataset import (
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
    game_exclusion,
    load_sequences,
    ordered_faction,
    removed_units,
    split_of,
    stats,
)
from reason8.openings.extract import opening_orders
from reason8.replays import widgets
from reason8.replays.parse import output_path
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
    rows = pl.DataFrame(dict(extract.orders))
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
    assert not extract.players and not extract.orders


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
    rows = pl.DataFrame(dict(extract.orders))
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


def test_ordered_faction_and_removed_units():
    assert ordered_faction(["cormex", "corwin", "armmex"]) == "Cortex"
    assert ordered_faction(["legmex"]) == "Legion"
    assert ordered_faction([]) is None
    assert removed_units(["legmex", "legmext15", "legmext15"], ["legmex"]) == ["legmext15"]
    assert removed_units(["armmex"], ["armmex"]) == []


def write_parsed(directory: Path, name: str, document: dict) -> None:
    data = json.dumps(document).encode()
    path = output_path(directory, Path(f"{name}.sdfz"))
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(zstd.compress(data))


def test_build_dataset(tmp_path):
    parsed = tmp_path / "parsed"
    parsed.mkdir()
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
    for index in range(12):
        match_id = 1000 + index
        name = f"game{index}"
        if index == 0:
            write_parsed(parsed, name, tweaked)
        elif index == 1:
            write_parsed(parsed, name, older)
        elif index < 11:
            write_parsed(parsed, name, document)
        # the last game is not parsed
        games[match_id] = name
        match_ids.append(match_id)
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
    manifest = build_dataset(parsed, out, selection, match_players, jobs=2, **settings)

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
    # of the 159 openings kept: players 0 and 7 of the re-simulated game, and player 8 of
    # each of the 10 games through the position
    assert manifest["counts"]["openings_by_cutoff_source"] == {
        WINDOW: 147,
        BY_POSITION: 10,
        MEASURED: 2,
    }
    assert manifest["counts"]["games_by_status"] == {INCLUDED: 10, UNIT_TWEAKS: 1}
    assert manifest["counts"]["openings_by_status"] == {INCLUDED: 159, REMOVED_UNIT: 1}
    assert manifest["vocabulary"]["arm cor"]["build"] == 32018
    assert manifest["code"]["commit"]

    games_frame = pl.read_parquet(out / "games.parquet")
    assert games_frame.height == 11
    assert games_frame["replay_file_name"].to_list()[0] == "game0.sdfz"
    openings_frame = pl.read_parquet(out / "openings.parquet")
    assert openings_frame.height == 160
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
    again = build_dataset(parsed, out, selection, match_players, jobs=1, **settings)
    assert again["counts"] == manifest["counts"]

    # the whole opening window, as before openings ended at first contact
    window = build_dataset(
        parsed, tmp_path / "window", selection, match_players, cutoff=WHOLE_WINDOW, **settings
    )
    assert window["opening"]["cutoff"] == WHOLE_WINDOW
    assert window["opening"]["measured_games"] == 0
    assert window["opening"]["position_cutoff_seconds"] is None
    assert window["counts"]["openings_by_cutoff_source"] == {WINDOW: 159}
    assert sum(window["counts"]["rows"].values()) > total_rows
