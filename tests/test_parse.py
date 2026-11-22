"""Tests for the raw command reader and the compaction step, on synthetic input.

No parser binary or network needed: the parser's JSON is written by hand in the
shape sdfz-demo-parser 5.15.1 emits, and the demo file is built byte by byte.
"""

import gzip
import json
import struct
from compression import zstd

import pytest

from reason8.parse import (
    FORMAT,
    ParseError,
    command_name,
    compact,
    failures_by,
    option_names,
    output_path,
    summarize,
    write_json_zst,
)
from reason8.replay import Replay
from reason8.sdfz import RawCommand, RawCommandPacket, read_command_packets_file

UNITDEFS = ["", "armcom", "armlab", "armmex", "armpw"]


def command_packet(cmd_id, options, params):
    body = struct.pack("<BiiBI", 0, cmd_id, -1, options, len(params))
    body += struct.pack(f"<{len(params)}f", *params)
    return struct.pack("<BH", 11, 3 + len(body)) + body


def aicommand_packet(unit_id, cmd_id, options, params):
    body = struct.pack("<BBBhiiBI", 0, 255, 0, unit_id, cmd_id, -1, options, len(params))
    body += struct.pack(f"<{len(params)}f", *params)
    return struct.pack("<BH", 14, 3 + len(body)) + body


def aicommands_packet(unit_ids, ref_id, commands):
    """AICOMMANDS with a shared id/options/size when given, else per command."""
    body = struct.pack("<BBBiBHH", 0, 255, 1, ref_id, 0xFF, 0xFFFF, len(unit_ids))
    body += struct.pack(f"<{len(unit_ids)}h", *unit_ids)
    body += struct.pack("<H", len(commands))
    for command_id, options, params in commands:
        if ref_id == 0:
            body += struct.pack("<i", command_id)
        body += struct.pack("<BH", options, len(params)) + struct.pack(f"<{len(params)}f", *params)
    return struct.pack("<BH", 15, 3 + len(body)) + body


def demo_bytes(packets, script=b"[game]{}"):
    stream = b"".join(
        struct.pack("<fI", 1.0, len(packet_bytes)) + packet_bytes for packet_bytes in packets
    )
    header = b"spring demofile\0" + struct.pack("<ii", 5, 352)
    header += b"2026.09.03".ljust(256, b"\0") + b"\0" * 16 + struct.pack("<q", 0)
    header += struct.pack("<ii", len(script), len(stream))
    header = header.ljust(352, b"\0")
    return header + script + stream


def test_raw_reader(tmp_path):
    packets = [
        bytes([2]),  # NEWFRAME: ignored
        command_packet(-2, 32, [100.0, 0.0, 200.0, 1.0]),
        aicommand_packet(7, 34571, 0, [1.0]),
        aicommands_packet([7, 8], -3, [(-3, 32, [1.0, 2.0, 3.0, 0.0]), (-3, 32, [4, 5, 6, 0])]),
        aicommands_packet([9], 0, [(10, 16, [1.0, 2.0, 3.0]), (0, 0, [])]),
    ]
    path = tmp_path / "demo.sdfz"
    path.write_bytes(gzip.compress(demo_bytes(packets)))
    raw_packets = read_command_packets_file(path)
    assert [raw_packet.packet_id for raw_packet in raw_packets] == [11, 14, 15, 15]
    assert raw_packets[0].commands == (RawCommand(-2, 32, (100.0, 0.0, 200.0, 1.0)),)
    assert raw_packets[1].commands[0].cmd_id == 34571
    assert [command.cmd_id for command in raw_packets[2].commands] == [-3, -3]
    assert raw_packets[2].commands[1].params == (4.0, 5.0, 6.0, 0.0)
    assert [(command.cmd_id, command.options) for command in raw_packets[3].commands] == [
        (10, 16),
        (0, 0),
    ]


def test_raw_reader_rejects_other_files(tmp_path):
    path = tmp_path / "x.sdfz"
    path.write_bytes(gzip.compress(b"not a demo"))
    with pytest.raises(ValueError):
        read_command_packets_file(path)


def test_command_names_and_options():
    assert command_name(-5) == "BUILD"
    assert command_name(10) == "MOVE"
    assert command_name(115) == "REPEAT"
    assert command_name(23000) == "QUOTA_BUILD_TOGGLE"
    assert command_name(99999) == "CMD_99999"
    assert option_names(32 + 128) == ["shift", "alt"]
    assert option_names(0) == []


def option_flags(bits):
    names = ["META_KEY", "INTERNAL_ORDER", "RIGHT_MOUSE_KEY", "SHIFT_KEY", "CONTROL_KEY"]
    flags = {name: bool(bits & (4 << i)) for i, name in enumerate(names)}
    flags["ALT_KEY"] = bool(bits & 128)
    return flags


def packet(name, game_time, data):
    return {"name": name, "fullGameTime": game_time, "actualGameTime": 0, "data": data}


def parsed_doc():
    """A tiny game in the shape of sdfz-demo-parser output."""
    unnamed = {"unitId": 7, "options": option_flags(0), "params": [1], "data": {}}  # no cmdName
    return {
        "header": {"version": 5, "gameTime": 60, "wallclockTime": 70},
        "info": {
            "meta": {"map": "Test Map", "game": "BAR test", "engine": "2026.09.03"},
            "hostSettings": {"server_match_id": "42", "hostip": "10.0.0.1"},
            "gameSettings": {"deathmode": "com"},
            "allyTeams": [{"allyTeamId": 0}, {"allyTeamId": 1}],
            "players": [
                {"playerId": 0, "teamId": 0, "allyTeamId": 0, "name": "A", "faction": "Armada"},
                {"playerId": 1, "teamId": 1, "allyTeamId": 1, "name": "B", "faction": "Cortex"},
            ],
            "ais": [],
            "spectators": [{"playerId": 2, "name": "S", "countryCode": "XX"}],
        },
        "statistics": {"winningAllyTeamIds": [0], "playerStats": [], "teamStats": {}},
        "packets": [
            packet("CHAT", 1.0, {"fromId": 0, "toId": 252, "message": "gl hf"}),
            packet(
                "LUAMSG",
                1.0,
                {"playerNum": 0, "data": {"name": "UNITDEFS", "data": UNITDEFS}, "dataRaw": ""},
            ),
            packet("STARTPLAYING", 2.0, {"countdown": 0}),
            packet(
                "COMMAND",
                3.0,
                {
                    "playerNum": 0,
                    "command": {
                        "cmdName": "BUILD",
                        "unitDefId": "armlab",
                        "options": option_flags(32),
                        "params": [100, 50.123, 200, 1],
                    },
                },
            ),
            packet(
                "AICOMMANDS",
                3.5,
                {
                    "playerNum": 1,
                    "aiId": 255,
                    "pairwise": 0,
                    "refCmdId": 2**32 - 3,  # the parser reads the shared id unsigned
                    "unitIds": [11, 12],
                    "commands": [
                        {"unitId": 11, "options": option_flags(32), "params": [1, 2, 3, 0]},
                    ],
                },
            ),
            packet("AICOMMAND", 4.0, {"playerNum": 1, "aiId": 255, "command": unnamed}),
            packet("SELECT", 4.5, {"playerNum": 0, "selectedUnitIds": [5]}),
            packet(
                "COMMAND",
                5.0,
                {
                    "playerNum": 0,
                    "command": {
                        "cmdName": "INSERT",
                        "options": option_flags(128),
                        "params": [0, -4, 0],
                    },
                },
            ),
            packet(
                "SHARE",
                6.0,
                {
                    "playerNum": 1,
                    "shareTeam": 0,
                    "shareUnits": True,
                    "shareMetal": 10.0,
                    "shareEnergy": 0.0,
                },
            ),  # fmt: skip
            packet("GAMEOVER", 62.0, {"playerNum": 0, "winningAllyTeams": [0]}),
        ],
    }


def raw_for_doc():
    return [
        RawCommandPacket(11, (RawCommand(-2, 32, (100.0, 50.123, 200.0, 1.0)),)),
        RawCommandPacket(15, (RawCommand(-3, 32, (1.0, 2.0, 3.0, 0.0)),)),
        RawCommandPacket(14, (RawCommand(34923, 0, (1.0,)),)),
        RawCommandPacket(11, (RawCommand(1, 128, (0.0, -4.0, 0.0)),)),
    ]


def test_compact():
    document = compact(parsed_doc(), raw_for_doc(), {"file": "x.sdfz"})
    assert document["format"] == "reason8.replay/1"
    assert document["meta"]["serverMatchId"] == "42"
    assert document["meta"]["endFrame"] == 60 * 30
    assert document["unitdefs"] == UNITDEFS
    assert "hostip" not in str(document)
    assert "countryCode" not in str(document)

    events = document["events"]
    assert [event["type"] for event in events] == [
        "chat", "start", "cmd", "cmd", "cmd", "select", "cmd", "share", "gameover",
    ]  # fmt: skip
    chat, start = events[0], events[1]
    assert chat["frame"] == -30 and chat["to"] == 252
    assert start["frame"] == 0

    build = events[2]
    assert build["unit"] == "armlab" and build["opts"] == ["shift"] and build["team"] == 0
    assert build["params"] == [100, 50.12, 200, 1]
    assert "units" not in build  # COMMAND applies to the current selection

    widget_build = events[3]  # recovered from the raw reader
    assert widget_build["cmd"] == "BUILD" and widget_build["unit"] == "armmex"
    assert widget_build["units"] == [11, 12] and widget_build["team"] == 1

    custom = events[4]
    assert custom["cmd"] == "UNIT_SET_TARGET" and custom["cmd_id"] == 34923

    insert = events[6]
    assert insert["pos"] == 0
    assert insert["inner"] == {"cmd": "BUILD", "cmd_id": -4, "unit": "armpw", "params": []}


def test_compact_feeds_the_reader():
    replay = Replay(compact(parsed_doc(), raw_for_doc(), {"file": "x.sdfz"}))
    orders = replay.build_orders()
    assert [(order.unit, order.kind, order.team) for order in orders] == [
        ("armlab", "structure", 0),
        ("armmex", "structure", 1),
        ("armpw", "factory", 0),
    ]
    assert orders[2].inserted and not orders[2].quota


def test_compact_detects_misaligned_commands():
    raw_packets = raw_for_doc()
    with pytest.raises(ParseError):
        compact(parsed_doc(), raw_packets[:-1], {})
    raw_packets[0] = RawCommandPacket(11, (RawCommand(-2, 32, (1.0, 2.0, 3.0, 4.0)),))
    with pytest.raises(ParseError):
        compact(parsed_doc(), raw_packets, {})


def test_failures_by_version_and_engine():
    entries = [
        {
            "status": "ok",
            "game": "test-2",
            "engine": "2026.07.04",
            "seconds": 1.0,
            "sdfz_bytes": 2e6,
            "parser_json_bytes": 2e7,
            "json_bytes": 7e6,
            "compressed_bytes": 5e5,
        },
        {"status": "error", "game": "test-2", "engine": "2026.07.04", "error": "boom"},
        {"status": "error", "game": "test-1", "engine": "2025.06.24", "error": "boom"},
        {"status": "error", "error": "not a demo"},
    ]
    assert failures_by(entries, ("engine",)) == {
        ("2025.06.24",): (1, 1),
        ("2026.07.04",): (1, 2),
        ("None",): (1, 1),
    }
    assert failures_by(entries, ("game",))[("test-2",)] == (1, 2)
    summary = summarize(entries)
    assert summary.splitlines()[0] == "1 ok, 3 failed"
    assert "failures per engine:" in summary
    assert "  2026.07.04: 1/2 failed" in summary


def test_write_json_zst_round_trip(tmp_path):
    document = {"format": FORMAT, "events": [{"frame": 1, "type": "start"}]}
    path = output_path(tmp_path, tmp_path / "game.sdfz")
    uncompressed = write_json_zst(document, path)
    assert path.name == "game.json.zst"
    assert json.loads(zstd.decompress(path.read_bytes())) == document
    assert uncompressed == len(json.dumps(document, separators=(",", ":")))
    assert not list(tmp_path.glob("*.tmp"))
