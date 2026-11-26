"""Tests for `reason8 analysis reactions` (no engine or replay needed)."""

import json

import polars as pl

from reason8.analysis.reactions import (
    IDLE_SCHEMA,
    game_reactions,
    idle_records,
    reactions,
    report,
    unit_commands,
)
from reason8.replays.replay import Replay


def replay(events):
    return Replay({"header": {}, "players": [], "ais": [], "events": events, "statistics": {}})


def test_unit_commands_follow_the_selection():
    commands = unit_commands(
        replay(
            [
                {"type": "select", "frame": 10, "player": 1, "units": [7, 8]},
                {"type": "cmd", "frame": 20, "player": 1, "via": "COMMAND", "cmd": "MOVE"},
                {
                    "type": "cmd",
                    "frame": 25,
                    "player": 1,
                    "via": "AICOMMAND",
                    "ai": 255,
                    "units": [8],
                    "cmd": "BUILD",
                },
                {
                    "type": "cmd",
                    "frame": 30,
                    "player": 2,
                    "via": "AICOMMAND",
                    "ai": 3,
                    "units": [8],
                    "cmd": "MOVE",
                },  # an AI's command, not the player's
            ]
        )
    )
    assert commands == {7: [(20, "clicked")], 8: [(20, "clicked"), (25, "widget")]}


def write_state(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def test_idle_records_need_format_4(tmp_path):
    idle = {"t": "idle", "f": 95, "u": 5, "d": 12, "team": 0}
    current = write_state(
        tmp_path / "current.jsonl", [{"t": "header", "v": 4, "unitdefs": {"12": "armlab"}}, idle]
    )
    old = write_state(tmp_path / "old.jsonl", [{"t": "header", "v": 3, "unitdefs": {}}, idle])
    assert idle_records(current) == ({"12": "armlab"}, [idle])
    assert idle_records(old) == ({}, [])


def test_game_reactions_skip_an_unparsed_replay(tmp_path):
    state = write_state(
        tmp_path / "game.jsonl",
        [{"t": "header", "v": 4, "unitdefs": {}}, {"t": "idle", "f": 9, "u": 5, "d": 1, "team": 0}],
    )
    assert game_reactions(state, tmp_path / "game.json.zst") is None


def test_reactions():
    commands = {5: [(90, "widget"), (100, "widget"), (130, "clicked"), (5000, "clicked")]}
    idle = [{"u": 5, "f": 95}, {"u": 5, "f": 3000}, {"u": 6, "f": 10}]
    # the first widget command after going idle, the first click; none within 60 s; none
    assert reactions(idle, commands) == [(130, 100), (None, None), (None, None)]


def test_report():
    rows = [
        {
            "replay": "g",
            "team": 0,
            "unit_id": 1,
            "unit": "armlab",
            "kind": "factory",
            "frame": 600,
            "skill": 35.0,
            "clicked_frame": 690,
            "any_frame": 690,
        },
        {
            "replay": "g",
            "team": 0,
            "unit_id": 2,
            "unit": "armck",
            "kind": "builder",
            "frame": 6000,
            "skill": 35.0,
            "clicked_frame": None,
            "any_frame": None,
        },
    ]
    text = report(pl.DataFrame(rows, schema=IDLE_SCHEMA))
    factory_rows = text.split("### Factory, by skill")[1].split("###")[0]
    row = next(line for line in factory_rows.splitlines() if line.startswith("| 30-40"))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[:4] == ["30-40", "1", "100%", "3.0"]  # answered after 90 frames
    builder_rows = text.split("### Builder, by skill")[1].split("###")[0]
    assert "| 0%" in builder_rows.replace("  ", " ") or " 0% " in builder_rows
    assert "1 games, 2 idle events" in text
