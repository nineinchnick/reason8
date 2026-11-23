"""Tests for reading state files (no engine needed)."""

import gzip
import json
from pathlib import Path

from reason8.headless import state


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
        {"t": "hit", "f": 900, "u": 1, "d": 7, "team": 0, "x": 1, "z": 2, "by": 9, "by_team": 1},
        {"t": "damage", "f": 930, "team": 0, "by_team": 1, "hits": 4, "damage": 60},
        {"t": "end", "f": 1800, "reason": "gameover", "winners": [0], "attackers": "attacker"},
    ]
    path = tmp_path / "state.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    packed = tmp_path / "state.jsonl.gz"
    packed.write_bytes(gzip.compress(path.read_bytes()))
    assert state.summarise(packed) == state.summarise(path)
    summary = state.summarise(path, builds=5)
    assert summary["snapshots"] == 1
    assert summary["max_units"] == 1
    assert summary["teams"] == 1
    assert summary["game_minutes"] == 1.0
    assert summary["winners"] == [0]
    assert summary["events"]["finished"] == 1
    assert summary["events"]["hit"] == 1 and summary["events"]["damage"] == 1
    assert summary["attackers"] == "attacker"
    assert summary["first_finished"] == {0: ["10s armmex"]}
    assert summary["complete"] is True
    assert [record["t"] for record in state.read_records(path, snapshots=True)] == [
        "header",
        "created",
        "finished",
        "s",
        "hit",
        "damage",
        "end",
    ]


def test_state_summary_tolerates_a_cut_off_last_line(tmp_path):
    path = tmp_path / "state.jsonl"
    path.write_text('{"t":"header","teams":[],"unitdefs":{}}\n{"t":"s","f":150,"teams":[],"uni')
    summary = state.summarise(path)
    assert summary["complete"] is False
    assert summary["snapshots"] == 0


def test_state_path():
    replay = Path("replays/2026-07-09_17-35-45-882_Some Map v1.2_2025.06.24.sdfz")
    assert state.state_path(Path("state"), replay) == Path(
        "state/2026-07-09_17-35-45-882_Some Map v1.2_2025.06.24.jsonl.gz"
    )
