import json
from compression import zstd

import polars as pl

from reason8.analysis.apm import (
    FRAMES_PER_MINUTE,
    INCLUDED,
    WITH_BOTS,
    ActionCounter,
    end_frames,
    game_apm,
    measure,
    most_in_window,
    parse_skill,
    per_minute,
    player_actions,
    report,
)
from reason8.replays.replay import FORMAT, Replay

MINUTE = FRAMES_PER_MINUTE


def player(player_id, ally_team, skill="[25.0]"):
    return {
        "playerId": player_id,
        "teamId": player_id,
        "allyTeamId": ally_team,
        "skill": skill,
        "skillUncertainty": "3.5",
    }


def select(frame, player_id, *units):
    return {"frame": frame, "type": "select", "player": player_id, "units": list(units)}


def click(frame, player_id, command="MOVE"):
    return {"frame": frame, "type": "cmd", "player": player_id, "via": "COMMAND", "cmd": command}


def widget(frame, player_id, *units, command="MOVE"):
    return {
        "frame": frame,
        "type": "cmd",
        "player": player_id,
        "via": "AICOMMANDS",
        "ai": 255,
        "units": list(units),
        "cmd": command,
    }


def make_replay(events, end_frame=3 * MINUTE, players=None, ais=()):
    return Replay(
        {
            "format": FORMAT,
            "meta": {"endFrame": end_frame, "winningAllyTeamIds": [0], "game": "test"},
            "players": players or [player(0, 0, "[45.5]"), player(1, 1, "[12.0]")],
            "ais": list(ais),
            "events": events,
        }
    )


def test_action_counter_follows_bar_rules():
    counter = ActionCounter()
    assert counter.command(10, [1, 2])
    assert not counter.command(10, [3])  # one action per frame
    assert not counter.command(14, [1])  # unit 1 got a command 4 frames ago
    assert not counter.command(20, [1])  # ...and that one marked it again
    assert counter.command(20 + 7, [1])  # 7 frames later it counts
    assert counter.command(28, [5])  # another unit counts right away
    assert not counter.command(40, [])  # a command to no unit is no action
    assert counter.frames == [10, 27, 28]


def test_held_move_and_dragged_line_are_one_action():
    events = [
        select(-30, 0, 100),  # pregame selection still applies
        *(click(frame, 0) for frame in range(100, 200, 4)),  # right button held
        select(300, 0, 101),
        *(click(300, 0, "BUILD") for _ in range(6)),  # a line of buildings in one frame
    ]
    actions = player_actions(make_replay(events))
    assert actions[0]["clicked"] == [100, 300]
    assert actions[0]["clicked_raw"] == [*range(100, 200, 4), 300]
    assert actions[1]["clicked"] == []


def test_widget_and_clicked_commands_are_counted_apart():
    events = [
        select(5, 0, 100),
        click(10, 0),
        widget(10, 0, 100, 101),  # same frame as the click: one action in `all`
        widget(30, 0, 200),
        {**widget(40, 0, 300), "ai": 3},  # a bot's command is not the player's
    ]
    actions = player_actions(make_replay(events))
    assert actions[0]["clicked"] == [10]
    assert actions[0]["widget"] == [10, 30]
    assert actions[0]["all"] == [10, 30]


def test_most_in_window():
    frames = [0, 5, 10, 29, 30, 31, 100]
    assert most_in_window(frames, 30) == 5  # 5, 10, 29, 30, 31
    assert most_in_window(frames, 1) == 1
    assert most_in_window(frames, 30, start=90) == 1
    assert most_in_window(frames, 30, start=0, end=5) == 4  # only the window from frame 0
    assert most_in_window([], 30) == 0


def test_per_minute_keeps_whole_minutes():
    assert per_minute([0, 10, MINUTE, 2 * MINUTE + 5], 2) == [2, 1]


def test_end_frames():
    players = [player(0, 0), player(1, 0), player(2, 1), player(3, 1)]
    events = [
        {"frame": -100, "type": "playerleft", "player": 3, "reason": 1},
        {"frame": 500, "type": "team", "player": 0, "action": "resign", "param": 0},
        {"frame": 700, "type": "playerleft", "player": 1, "reason": 0},  # came back
        click(800, 1),
        {"frame": 900, "type": "playerleft", "player": 2, "reason": 1},  # left for good
        {"frame": 950, "type": "team", "player": 1, "action": "team_died", "param": 3},
    ]
    ends = end_frames(make_replay(events, end_frame=1000, players=players))
    assert ends == {0: 500, 1: 1000, 2: 900, 3: 950}


def test_parse_skill():
    assert parse_skill("[45.67]") == 45.67
    assert parse_skill("(-1.5)") == -1.5
    assert parse_skill(None) is None
    assert parse_skill(12) == 12.0


def test_game_apm_rows():
    events = [select(0, 0, 100)] + [
        click(minute * MINUTE + 30 * i, 0) for minute in (0, 2) for i in range(3)
    ]
    result = game_apm(make_replay(events, end_frame=3 * MINUTE + 10), "game")
    assert result.game["status"] == INCLUDED and result.game["team_size"] == 1
    first = result.players[0]
    assert (first["skill"], first["minutes"], first["clicked"], first["won"]) == (45.5, 3, 6, True)
    assert first["clicked_max_1s"] == 1 and first["clicked_max_5s"] == 3
    assert result.minutes["clicked"][:3] == [3, 0, 3]
    assert result.minutes["clicked_max_1s"][:3] == [1, 0, 1]
    assert len(result.minutes["minute"]) == 6  # two players, three whole minutes each

    with_bots = game_apm(make_replay(events, ais=[{"teamId": 5}]), "bots")
    assert with_bots.game["status"] == WITH_BOTS and not with_bots.players


def test_measure_and_report(tmp_path):
    parsed = tmp_path / "parsed" / "date=2026-11-01"
    parsed.mkdir(parents=True)
    events = [select(0, 0, 100), select(0, 1, 200)]
    events += [click(frame, 0) for frame in range(0, 3 * MINUTE, 200)]
    events += [widget(frame, 1, 200) for frame in range(0, 3 * MINUTE, 400)]
    document = make_replay(events).doc
    (parsed / "2026-11-01_game.json.zst").write_bytes(zstd.compress(json.dumps(document).encode()))
    counts = measure(tmp_path / "parsed", tmp_path / "apm")
    assert counts == {"replays": 1, "games": 1, "players": 2}
    minutes = pl.read_parquet(tmp_path / "apm" / "minutes.parquet")
    assert minutes.height == 6 and minutes["clicked"].sum() == 27
    text = report(tmp_path / "apm")
    assert "## Actions per minute, `clicked`, by game phase" in text
    assert "| 40 and up | 3 |" in text
