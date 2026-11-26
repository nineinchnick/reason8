"""Tests for `reason8 analysis reactions` (no engine or replay needed)."""

import gzip
import json
from datetime import date

import polars as pl

from reason8.analysis.apm import event_rows
from reason8.analysis.reactions import (
    IDLE_SCHEMA,
    idle_records,
    measure,
    reactions,
    report,
    unit_commands,
)
from tests import synthetic
from tests.analysis.test_apm import click, make_replay, select, widget


def test_unit_commands_follow_the_selection():
    commands = unit_commands(
        event_rows(
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
    created = {"t": "created", "f": 40, "u": 9, "d": 13, "team": 0, "by": 5}
    current = write_state(
        tmp_path / "current.jsonl",
        [{"t": "header", "v": 4, "unitdefs": {"12": "armlab"}}, created, created, idle, idle],
    )
    old = write_state(tmp_path / "old.jsonl", [{"t": "header", "v": 3, "unitdefs": {}}, idle])
    # the units the idle unit started since its previous idle event
    assert idle_records(current) == (
        {"12": "armlab"},
        [{**idle, "started": 2}, {**idle, "started": 0}],
    )
    assert idle_records(old) == ({}, [])


def test_measure_reads_the_replays_from_the_tables(tmp_path):
    parsed, state = tmp_path / "parsed", tmp_path / "state"
    events = [select(0, 0, 5), click(100, 0), widget(40, 1, 6), click(200, 0)]
    synthetic.write_parsed(parsed, "2026-11-01_game", make_replay(events))
    synthetic.write_tables(parsed)
    # parsed after the tables were written; a game whose replay is not parsed; one
    # without idle events
    synthetic.write_parsed(parsed, "2026-11-02_game", make_replay(events))
    header = {"t": "header", "v": 4, "unitdefs": {"12": "armlab"}}
    idle = [
        {"t": "idle", "f": 30, "u": 5, "d": 12, "team": 0},
        {"t": "idle", "f": 30, "u": 6, "d": 12, "team": 1},
    ]
    for name, records in (
        ("2026-11-01_game", [header, *idle]),
        ("2026-11-02_game", [header, *idle]),
        ("2026-11-02_unparsed", [header, *idle]),
        ("2026-11-03_quiet", [header]),
    ):
        directory = state / f"date={name[:10]}"
        directory.mkdir(parents=True, exist_ok=True)
        with gzip.open(directory / f"{name}.jsonl.gz", "wt") as file:
            file.write("".join(json.dumps(record) + "\n" for record in records))
    frame = measure(state, parsed, {}, jobs=2)
    assert frame.select("replay", "unit_id", "clicked_frame", "any_frame").rows() == [
        ("2026-11-01_game", 5, 100, 100),
        ("2026-11-01_game", 6, None, 40),
        ("2026-11-02_game", 5, 100, 100),
        ("2026-11-02_game", 6, None, 40),
    ]
    assert frame["unit"].unique().to_list() == ["armlab"]
    assert frame["skill"].null_count() == 0
    one_day = measure(state, parsed, {}, jobs=1, since=date(2026, 11, 2))
    assert one_day["replay"].unique().to_list() == ["2026-11-02_game"]


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
