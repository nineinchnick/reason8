"""Tests for the pure-Python parts of tools/headless (no engine needed)."""

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "headless"))

import demo  # noqa: E402
import run  # noqa: E402
import state  # noqa: E402

SCRIPT = "[game]\n{\n\tgametype=Some Game test-1-abc;\n\tmapname=Some Map v1;\n}\n"


def demo_bytes(script: str = SCRIPT, engine: bytes = b"2026.09.03", game_seconds: int = 780):
    header = demo.HEADER.pack(
        demo.MAGIC,
        5,
        demo.HEADER.size,
        engine,
        bytes(range(16)),
        1795362080,
        len(script.encode()),  # scriptSize
        0,  # demoStreamSize
        game_seconds,
        928,  # wallclockTime
        14,  # numPlayers
        0,
        0,
        2,  # numTeams
        0,
        0,
        0,
        0,
    )
    return header + script.encode() + b"\x01\x02\x03"


def test_parse_header():
    header = demo.parse_header(demo_bytes())
    assert header.engine_version == "2026.09.03"
    assert header.engine_tag == "2026.09.03"
    assert header.game == "Some Game test-1-abc"
    assert header.map == "Some Map v1"
    assert header.game_seconds == 780
    assert header.frames == 780 * 30
    assert header.num_players == 14
    assert header.num_teams == 2
    assert header.game_id == bytes(range(16)).hex()


def test_engine_tag_drops_branch_suffix():
    header = demo.parse_header(demo_bytes(engine=b"105.1.1-2590-gb9462a0 BAR105"))
    assert header.engine_tag == "105.1.1-2590-gb9462a0"


def test_read_header_from_gzip(tmp_path):
    path = tmp_path / "replay.sdfz"
    path.write_bytes(gzip.compress(demo_bytes()))
    assert demo.read_header(path).map == "Some Map v1"


def test_bad_magic():
    with pytest.raises(demo.DemoError):
        demo.parse_header(b"x" * 400)


def test_with_speed_existing_modoptions():
    script = "[GAME]\n{\n\t[MODOPTIONS]\n\t{\n\t\tdeathmode=neverend;\n\t}\n}\n"
    result = run.with_speed(script, 100)
    assert "MinSpeed=100;" in result and "MaxSpeed=100;" in result
    assert result.index("MinSpeed") < result.index("deathmode")


def test_with_speed_no_modoptions():
    result = run.with_speed("[GAME]\n{\n\tMapName=x;\n}\n", 20)
    assert "[MODOPTIONS]" in result and "MaxSpeed=20;" in result


def test_sim_window(tmp_path):
    log = tmp_path / "infolog.txt"
    log.write_text(
        "[t=00:00:00.500000] starting\n"
        "[t=00:00:10.000000][f=-000001] loading\n"
        "[t=00:00:12.000000][f=0000000] ingame\n"
        "[t=00:00:20.000000][f=0000900] something\n"
        "[t=00:01:12.000000][f=0018000] quit\n"
        "[t=00:01:15.000000][f=0018000] shutdown\n"
    )
    load_seconds, sim_seconds, frames = run.sim_window(log)
    assert load_seconds == 12.0
    assert sim_seconds == 60.0
    assert frames == 18000


def test_state_summary(tmp_path):
    records = [
        {
            "t": "header",
            "game": "G",
            "map": "M",
            "engine": "E",
            "snapshot_frames": 150,
            "teams": [{"team": 0, "gaia": False}, {"team": 1, "gaia": True}],
            "unitdefs": {"7": "armmex"},
        },
        {"t": "created", "f": 10, "u": 1, "d": 7, "team": 0, "x": 1, "z": 2},
        {"t": "finished", "f": 300, "u": 1, "d": 7, "team": 0, "x": 1, "z": 2},
        {
            "t": "s",
            "f": 300,
            "teams": [[0, 1, 2, 3, 4, 5, 6, 7, 8]],
            "units": [[1, 7, 0, 1, 2, 100, 100]],
        },
        {"t": "end", "f": 1800, "reason": "gameover", "winners": [0]},
    ]
    path = tmp_path / "state.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    summary = state.summarise(path, builds=5)
    assert summary["snapshots"] == 1
    assert summary["max_units"] == 1
    assert summary["teams"] == 1
    assert summary["game_minutes"] == 1.0
    assert summary["winners"] == [0]
    assert summary["events"]["finished"] == 1
    assert summary["first_finished"] == {0: ["10s armmex"]}
    assert summary["complete"] is True
    assert [record["t"] for record in state.read_lines(path)] == [
        "header",
        "created",
        "finished",
        "s",
        "end",
    ]


def test_state_summary_tolerates_a_cut_off_last_line(tmp_path):
    path = tmp_path / "state.jsonl"
    path.write_text('{"t":"header","teams":[],"unitdefs":{}}\n{"t":"s","f":150,"teams":[],"uni')
    summary = state.summarise(path)
    assert summary["complete"] is False
    assert summary["snapshots"] == 0


def test_widget_config_enables_our_widget():
    config = run.widget_config([run.STATE_WIDGET])
    assert '["Reason8 state export"] = 1' in config
    assert "allowUserWidgets = true" in config
