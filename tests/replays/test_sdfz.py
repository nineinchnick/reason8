"""Tests for reading the header of a replay (no engine needed)."""

import gzip

import pytest

from reason8.replays import sdfz

SCRIPT = "[game]\n{\n\tgametype=Some Game test-1-abc;\n\tmapname=Some Map v1;\n}\n"


def demo_bytes(script: str = SCRIPT, engine: bytes = b"2026.09.03", game_seconds: int = 780):
    header = sdfz.HEADER.pack(
        sdfz.MAGIC,
        5,
        sdfz.HEADER.size,
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
    header = sdfz.parse_header(demo_bytes())
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
    header = sdfz.parse_header(demo_bytes(engine=b"105.1.1-2590-gb9462a0 BAR105"))
    assert header.engine_tag == "105.1.1-2590-gb9462a0"


def test_read_header_from_gzip(tmp_path):
    path = tmp_path / "replay.sdfz"
    path.write_bytes(gzip.compress(demo_bytes()))
    assert sdfz.read_header(path).map == "Some Map v1"


def test_bad_magic():
    with pytest.raises(sdfz.DemoError):
        sdfz.parse_header(b"x" * 400)
