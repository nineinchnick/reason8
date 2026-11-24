"""Tests for reading the players' widget reports from a demo, on synthetic input."""

import base64
import gzip
import json
import struct

import polars as pl

from reason8.replays import widgets
from tests.replays.test_parse import command_packet, demo_bytes

SCRIPT = b"""[game]
{
[player0]
{
team=0;
name=Someone;
spectator=0;
}
[player1]
{
name=Watcher;
spectator=1;
}
[team0]
{
allyteam=0;
teamleader=0;
}
[player2]
{
team=1;
spectator=0;
}
[modoptions]
{
allowuserwidgets=1;
allowunitcontrolwidgets=0;
teamcolors_anonymous_mode=disabled;
}
}
"""


def widget_entry(name, state=1):
    """A widget as the report lists it."""
    return {"name": name, "author": "someone", "hash": "abc==", "state": state, "desc": "d"}


def stored_widget(name, state=1):
    """A widget as `reports.parquet` keeps it."""
    return {"name": name, "author": "someone", "hash": "abc==", "state": state, "description": "d"}


def report_event(entries, frame=31):
    return {
        "eventtype": "widgets_report",
        "username": "Someone",
        "frame": frame,
        "widgetCount": len(entries),
        "truncated": False,
        "widgets": entries,
    }


def luamsg_packet(player_id, message, script=2000, mode=0):
    size = widgets.LUAMSG_HEADER.size + len(message)
    return struct.pack("<BHBHB", widgets.PACKET_LUAMSG, size, player_id, script, mode) + message


def match_event(event):
    return widgets.MATCH_EVENT_PREFIX + base64.b64encode(json.dumps(event).encode())


def test_decode_match_event_accepts_both_alphabets_and_missing_padding():
    event = {"eventtype": "x", "text": "??>>"}  # encodes to '+' and '/'
    encoded = base64.b64encode(json.dumps(event).encode())
    assert widgets.decode_match_event(widgets.MATCH_EVENT_PREFIX + encoded) == event
    url_safe = encoded.replace(b"+", b"-").replace(b"/", b"_").rstrip(b"=")
    assert widgets.decode_match_event(widgets.MATCH_EVENT_PREFIX + url_safe) == event
    assert widgets.decode_match_event(b"unitdefs:...") is None
    assert widgets.decode_match_event(widgets.MATCH_EVENT_PREFIX + b"not json") is None


def test_read_widget_reports_drops_the_name():
    packets = [
        command_packet(-2, 32, [1.0, 0.0, 2.0, 0.0]),
        luamsg_packet(0, b"some other message"),
        luamsg_packet(0, match_event({"eventtype": "selfd_mass_allowed"})),
        luamsg_packet(0, match_event(report_event([widget_entry("A"), widget_entry("B", 0)]))),
        luamsg_packet(1, match_event(report_event([widget_entry("C")], frame=40))),
    ]
    reports = widgets.read_widget_reports(demo_bytes(packets))
    assert [(report.player_id, report.frame) for report in reports] == [(0, 31), (1, 40)]
    assert reports[0].widget_count == 2
    assert [(widget.name, widget.state) for widget in reports[0].widgets] == [("A", 1), ("B", 0)]
    assert "Someone" not in repr(reports)


def test_script_teams_leaves_out_spectators():
    assert widgets.script_teams(SCRIPT.decode()) == {0: 0, 2: 1}


def test_read_replay(tmp_path):
    packets = [
        luamsg_packet(0, match_event(report_event([widget_entry("A")]))),
        luamsg_packet(1, match_event(report_event([widget_entry("C")]))),  # a spectator
        luamsg_packet(2, match_event(report_event([widget_entry("D", -1)]))),
    ]
    path = tmp_path / "game.sdfz"
    path.write_bytes(gzip.compress(demo_bytes(packets, script=SCRIPT)))
    replay, rows = widgets.read_replay(path)
    assert replay == {
        "replay_file_name": "game.sdfz",
        "reports": 2,
        "allowuserwidgets": "1",
        "allowunitcontrolwidgets": "0",
        "teamcolors_anonymous_mode": "disabled",
    }
    assert [(row["player_id"], row["team_id"]) for row in rows] == [(0, 0), (2, 1)]
    assert rows[0]["widgets"][0]["name"] == "A"
    frame = pl.from_dicts(rows, schema=widgets.REPORT_SCHEMA)
    assert frame.height == 2


def test_read_replay_records_unreadable_files(tmp_path):
    path = tmp_path / "broken.sdfz"
    path.write_bytes(b"not gzip")
    replay, rows = widgets.read_replay(path)
    assert rows == []
    assert replay["error"]


def test_player_widgets_merges_reports_and_keeps_enabled_widgets(monkeypatch):
    monkeypatch.setattr(widgets, "AUTOMATION_WIDGETS", frozenset({"Auto"}))
    reports = pl.from_dicts(
        [
            {
                "replay_file_name": "a.sdfz",
                "player_id": 0,
                "team_id": 0,
                "frame": 31,
                "widget_count": 2,
                "truncated": False,
                "widgets": [stored_widget("Auto", 0), stored_widget("Show")],
            },
            {
                "replay_file_name": "a.sdfz",
                "player_id": 0,
                "team_id": 0,
                "frame": 900,
                "widget_count": 1,
                "truncated": False,
                "widgets": [stored_widget("Auto")],
            },
            {
                "replay_file_name": "a.sdfz",
                "player_id": 3,
                "team_id": 2,
                "frame": 31,
                "widget_count": 1,
                "truncated": False,
                "widgets": [stored_widget("Off", -1)],
            },
        ],
        schema=widgets.REPORT_SCHEMA,
    )
    per_player = player_rows(widgets.player_widgets(reports))
    assert per_player == {
        0: (["Auto", "Show"], ["Auto"]),
        2: ([], []),
    }


def player_rows(frame):
    return {
        row["team_id"]: (row["widgets"], row["automation_widgets"])
        for row in frame.iter_rows(named=True)
    }


def test_unit_control_allowed():
    assert widgets.unit_control_allowed({})
    assert widgets.unit_control_allowed({"allowunitcontrolwidgets": "1"})
    assert not widgets.unit_control_allowed({"allowunitcontrolwidgets": "0"})
    assert not widgets.unit_control_allowed({"allowuserwidgets": "0"})
    assert not widgets.unit_control_allowed({"teamcolors_anonymous_mode": "allred"})
