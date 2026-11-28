import math

import polars as pl

from reason8.analysis.apm import FRAMES_PER_MINUTE
from reason8.analysis.orders import (
    BOT,
    BUILDINGS,
    CLICKED,
    DIFFERENT,
    LINE,
    ONE_ORDER,
    TARGETS,
    WIDGET,
    Command,
    OrderCounter,
    bot_orders,
    category,
    count_commands,
    measure,
    ratio_interval,
    report,
)
from reason8.replays.replay import FORMAT, Replay
from tests import synthetic

MINUTE = FRAMES_PER_MINUTE
COMMAND_IDS = {"MOVE": 10, "FIGHT": 16, "PRIORITY": 34571, "REMOVE": 2, "BUILD": -3}


def player(player_id, skill="[25.0]"):
    return {
        "playerId": player_id,
        "teamId": player_id,
        "allyTeamId": player_id,
        "skill": skill,
        "skillUncertainty": "3.5",
    }


def select(frame, player_id, *units):
    return {"frame": frame, "type": "select", "player": player_id, "units": list(units)}


def command(frame, player_id, name="MOVE", params=(100.0, 0.0, 100.0), opts=None, **fields):
    event = {
        "frame": frame,
        "type": "cmd",
        "player": player_id,
        "team": player_id,
        "via": "COMMAND",
        "cmd": name,
        "cmd_id": COMMAND_IDS[name],
        "params": list(params),
        **fields,
    }
    if name == "BUILD":
        event["unit"] = "armmex"
    if opts:
        event["opts"] = list(opts)
    return event


def widget(frame, player_id, unit, name="MOVE", params=(100.0, 0.0, 100.0), ai=255):
    return command(frame, player_id, name, params, via="AICOMMAND", ai=ai, units=[unit])


def make_replay(events, players=None, ais=()):
    return Replay(
        {
            "format": FORMAT,
            "meta": {"endFrame": 3 * MINUTE, "winningAllyTeamIds": [0], "game": "test"},
            "players": players or [player(0, "[45.5]"), player(1, "[12.0]")],
            "ais": list(ais),
            "unitdefs": ["", "armcom", "armmex", "armmex"],
            "events": events,
        }
    )


def test_category():
    assert category(orders=1, kinds=1, structures=0, commands=5) == ONE_ORDER
    assert category(orders=6, kinds=1, structures=6, commands=6) == LINE
    assert category(orders=6, kinds=1, structures=0, commands=6) == TARGETS
    assert category(orders=3, kinds=2, structures=3, commands=3) == BUILDINGS
    assert category(orders=3, kinds=2, structures=1, commands=3) == DIFFERENT


def frames_of(commands):
    counter = OrderCounter()
    for item in commands:
        counter.add(item)
    return counter.finish()


def test_one_click_to_a_selection_is_one_order_and_a_line_is_many():
    counter = frames_of(
        [
            Command(10, CLICKED, (1, 2, 3), order=7, kind=1, structure=False, command="MOVE"),
            *(
                Command(100, CLICKED, (1,), order=20 + spot, kind=2, structure=True, command="B")
                for spot in range(5)
            ),
        ]
    )
    click, line = counter.frames
    assert (click["unit_orders"], click["orders"], click["category"]) == (3, 1, ONE_ORDER)
    assert (line["commands"], line["orders"], line["kinds"]) == (5, 5, 1)
    assert line["category"] == LINE and line["action"] and line["clicked_action"]
    assert line["clicked_orders"] == 5 and line["names"] == "B"


def test_spans_hold_the_commands_the_7_frame_rule_lets_through():
    counter = frames_of(
        [
            Command(10, WIDGET, (1,), order=1, kind=1, structure=False, command="MOVE"),
            Command(14, WIDGET, (1,), order=2, kind=1, structure=False, command="MOVE"),
            Command(16, WIDGET, (1,), order=1, kind=1, structure=False, command="MOVE"),
            Command(30, WIDGET, (1,), order=3, kind=3, structure=False, command="FIGHT"),
        ]
    )
    assert [frame["action"] for frame in counter.frames] == [True, False, False, True]
    assert not any(frame["clicked_action"] for frame in counter.frames)
    first, second = counter.spans
    assert (first["frames"], first["length"], first["commands"], first["orders"]) == (3, 7, 3, 2)
    assert (second["frame"], second["commands"]) == (30, 1)


def test_frames_before_the_first_action_pay_for_no_span():
    counter = frames_of(
        [Command(5, BOT, (), order=1, kind=1, structure=False, command="MOVE")]
    )  # a command to no unit is never an action
    assert counter.frames[0]["action"] is False and counter.spans == []


def test_count_commands_resolves_selections_and_sources():
    rows = [
        (0, "select", -10, None, None, [100, 101], None, None, None, None),
        (0, "cmd", 50, "COMMAND", None, None, 1, 1, False, "MOVE"),
        (0, "cmd", 50, "AICOMMAND", 255, [100], 2, 2, False, "PRIORITY"),
        (1, "cmd", 60, "COMMAND", None, None, 1, 1, False, "MOVE"),  # nothing selected
        (2, "cmd", 70, "AICOMMAND", 3, [500], 1, 1, False, "MOVE"),
        (0, "cmd", -5, "COMMAND", None, None, 1, 1, False, "MOVE"),  # before the start
    ]
    counters = count_commands(rows)
    assert sorted(counters) == [0, 2]
    (frame,) = counters[0].frames
    assert (frame["clicked"], frame["widget"], frame["unit_orders"]) == (1, 1, 3)
    assert (frame["sources"], frame["category"], frame["names"]) == (
        "both",
        DIFFERENT,
        "MOVE PRIORITY",
    )
    assert counters[2].frames[0]["sources"] == BOT


def test_ratio_interval_resamples_games():
    value, low, high = ratio_interval(["a", "a", "b", "c"], [1, 1, 0, 1], [1, 1, 1, 1])
    assert value == 0.75 and 0 <= low <= value <= high <= 1
    assert all(math.isnan(value) for value in ratio_interval([], [], []))


def test_bot_orders_counts_the_ais_own_commands():
    ais = [{"aiId": 0, "teamId": 1, "allyTeamId": 1, "shortName": "Reason8"}]
    events = [
        widget(30, 0, 900, ai=0),
        widget(30, 0, 901, "FIGHT", ai=0),
        widget(30, 0, 902, params=(200.0, 0.0, 200.0), ai=0),
        widget(40, 0, 903),  # the player's widget, not the bot
    ]
    for event in events[:3]:
        event["team"] = 1
    frames, spans = bot_orders(make_replay(events, ais=ais), "game")
    (row,) = frames.to_dicts()
    assert (row["team"], row["ai_name"], row["commands"], row["orders"]) == (1, "Reason8", 3, 3)
    assert (row["kinds"], row["category"], row["bot"]) == (2, DIFFERENT, 3)
    assert spans["commands"].to_list() == [3]


def test_measure_and_report(tmp_path):
    events = [select(0, 0, 100, 101), select(0, 1, 200)]
    events += [command(frame, 0) for frame in range(30, 2 * MINUTE, 90)]
    events += [  # a dragged line of three mexes
        command(2 * MINUTE, 0, "BUILD", (x, 0.0, 500.0, 0), ("shift",)) for x in (100, 200, 300)
    ]
    events += [  # a widget's formation move: one MOVE to each unit, each to its own spot
        widget(2 * MINUTE + 100, 1, unit, params=(float(unit), 0.0, 10.0))
        for unit in (200, 201, 202)
    ]
    out = synthetic.write_tables(
        tmp_path / "tables",
        {"2026-11-01_game": make_replay(events), "2026-11-02_game": make_replay(events[:3])},
    )
    counts = measure(tmp_path / "orders", tables_dir=out, jobs=1, every=2)
    assert counts["days"] == 1
    frames = pl.read_parquet(tmp_path / "orders" / "frames" / "2026-11-01.parquet")
    line = frames.filter(pl.col("frame") == 2 * MINUTE).to_dicts()[0]
    assert (line["player"], line["orders"], line["category"], line["skill"]) == (0, 3, LINE, 45.5)
    formation = frames.filter(pl.col("player") == 1).to_dicts()[0]
    assert (formation["orders"], formation["kinds"], formation["category"]) == (3, 1, TARGETS)
    text = report(tmp_path / "orders", widgets_dir=tmp_path / "no-widgets")
    assert "## Per counted action, players" in text
    assert "| line of one building |" in text
