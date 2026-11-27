"""Tests for the Parquet tables of a game's state and for rebuilding units from events."""

import gzip
import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from reason8.headless import standing, tables
from reason8.headless.state import read_records

COMMANDER, EXTRACTOR, BOT = 3, 7, 9
UNIT_DEFS = {str(COMMANDER): "armcom", str(EXTRACTOR): "armmex", str(BOT): "armpw"}
TEAMS = [
    {"team": 0, "ally": 0, "ai": False, "side": "Armada", "gaia": False},
    {"team": 1, "ally": 1, "ai": False, "side": "Cortex", "gaia": False},
    {"team": 2, "ally": 2, "ai": False, "side": "", "gaia": True},
]


def header(version: int) -> dict:
    record = {
        "t": "header",
        "v": version,
        "game": "Beyond All Reason test-1",
        "map": "M",
        "engine": "E",
        "mapx": 8192,
        "mapz": 8192,
        "replay": True,
        "snapshot_frames": 60,
        "wind_min": 0.0,
        "wind_max": 25.0,
        "tidal": 20.0,
        "teams": TEAMS,
        "unitdefs": UNIT_DEFS,
    }
    if version >= 5:
        record["resource_frames"] = 30
        record["static"] = [EXTRACTOR]
    return record


def event(kind: str, frame: int, unit: int, unit_def: int, team: int, x: int, z: int, **extra):
    return {"t": kind, "f": frame, "u": unit, "d": unit_def, "team": team, "x": x, "z": z, **extra}


def resources(frame: int, wind: float) -> dict:
    return {
        "t": "r",
        "f": frame,
        "wind": wind,
        "teams": [
            [0, 100 + frame, 500, 2.5, 1.2, 900, 1000, 25, 10],
            [1, 200, 500, 1.5, 0.0, 800, 1000, 20, 0],
            [2, 0, 0, 0.0, 0.0, 0, 0, 0, 0],
        ],
    }


# what happens in the game, the same for both formats:
#   the commanders (unit 1, 2) are there from the start; team 0 builds an extractor (unit
#   10) and a bot (unit 11), gives the extractor to team 1, loses the bot, and its id is
#   used again for a new extractor of team 1 that is not finished when the game ends
LIFE = [
    event("created", 0, 1, COMMANDER, 0, 100, 100),
    event("finished", 0, 1, COMMANDER, 0, 100, 100),
    event("created", 0, 2, COMMANDER, 1, 900, 900),
    event("finished", 0, 2, COMMANDER, 1, 900, 900),
    event("created", 10, 10, EXTRACTOR, 0, 120, 140, by=1),
    event("finished", 40, 10, EXTRACTOR, 0, 120, 140),
    event("created", 70, 11, BOT, 0, 100, 110, by=1),
    event("finished", 80, 11, BOT, 0, 100, 110),
    event("idle", 80, 1, COMMANDER, 0, 100, 100),
    event("given", 90, 10, EXTRACTOR, 1, 120, 140, **{"from": 0}),
    event(
        "hit",
        100,
        11,
        BOT,
        0,
        400,
        400,
        by=2,
        by_d=COMMANDER,
        by_team=1,
        damage=60,
        paralyzer=False,
    ),
    event("destroyed", 125, 11, BOT, 0, 410, 400, built=True, by_team=1),
    event("created", 130, 11, EXTRACTOR, 1, 700, 720, by=2),
]
DAMAGE = {"t": "damage", "f": 120, "team": 0, "by_team": 1, "hits": 3, "damage": 160}
END = {"t": "end", "f": 180, "reason": "maxframe", "winners": [], "attackers": "last_attacker"}


def snapshot_units(frame: int, everything: bool) -> list[list]:
    """The snapshot units at `frame`: format 5 leaves out finished extractors."""
    units = [[1, COMMANDER, 0, 100 + frame, 100, 100, 100], [2, COMMANDER, 1, 900, 900, 100, 100]]
    if frame >= 60 and everything:
        units.append([10, EXTRACTOR, 0 if frame < 90 else 1, 120, 140, 100, 100])
    if frame == 120:
        units.append([11, BOT, 0, 400, 400, 80, 100])
    if frame >= 180:
        units.append([11, EXTRACTOR, 1, 700, 720, 100, 40])
    return sorted(units)


def lines_v5() -> list[dict]:
    """A state file of format 5: resources every 30 frames, snapshots every 60, written at
    the end of the frame (after its unit lines), without finished extractors."""
    lines = [header(5)]
    life = [dict(line) for line in LIFE]  # tests change lines in place
    for frame in range(0, 181, 30):
        while life and life[0]["f"] <= frame:
            lines.append(life.pop(0))
        if frame == 120:
            lines.append(DAMAGE)
        lines.append(resources(frame, 10.0 + frame / 100))
        if frame % 60 == 0:
            lines.append({"t": "s", "f": frame, "units": snapshot_units(frame, False)})
    return [*lines, {**END, "sampled": "frame_end"}]


def lines_v4() -> list[dict]:
    """The same game in format 4: resources only in the snapshots, every unit in them."""
    lines = [header(4)]
    life = [dict(line) for line in LIFE]  # tests change lines in place
    for frame in range(0, 181, 60):
        while life and life[0]["f"] <= frame:
            lines.append(life.pop(0))
        if frame == 120:
            lines.append(DAMAGE)
        row = resources(frame, 10.0 + frame / 100)
        units = snapshot_units(frame, True)
        lines.append(
            {"t": "s", "f": frame, "wind": row["wind"], "teams": row["teams"], "units": units}
        )
    return [*lines, END]


ROCK, WRECK = 40, 41
#: The order of a frame's lines as `tables.read_table_records` gives them.
LINE_ORDER = {
    **dict.fromkeys(tables.UNIT_EVENT_KINDS, 0),
    "fdef": 1,
    "fcreated": 1,
    "reclaim": 2,
    "fdestroyed": 3,
    "hit": 4,
    "damage": 5,
    "r": 6,
    "s": 7,
    "work": 8,
}


def lines_v6() -> list[dict]:
    """The game of format 5 in format 6, with features and builders' work: commander 1
    builds the extractor and the bot and reclaims a rock of the map; the bot leaves a wreck
    when it dies, which commander 2 resurrects."""
    lines = lines_v5()
    lines[0] = {**header(6), "work_frames": 10, "builders": [COMMANDER]}
    for line in lines:
        if line["t"] == "destroyed":
            line.update(by=2, weapon=17)
        if line["t"] == "s" and line["f"] == 180:
            line["units"] = sorted([*line["units"], [12, BOT, 1, 500, 500, 100, 100]])
    rock = {"t": "fdef", "d": ROCK, "name": "rock1", "metal": 50, "energy": 0, "reclaim_time": 600}
    wreck = {"t": "fdef", "d": WRECK, "name": "armpw_dead", "metal": 30, "energy": 0}
    wreck["reclaim_time"] = 900
    added = [
        rock,
        {
            "t": "fcreated",
            "f": 0,
            "id": 5,
            "d": ROCK,
            "x": 300,
            "z": 300,
            "metal": 50.0,
            "energy": 0.0,
        },
        {"t": "work", "f": 10, "u": 1, "team": 0, "task": "build", "unit": 10},
        {"t": "work", "f": 40, "u": 1, "team": 0, "task": "reclaim", "feature": 5},
        {"t": "reclaim", "f": 60, "id": 5, "team": 0, "from": 50, "metal": 50.0, "energy": 0.0},
        {"t": "fdestroyed", "f": 60, "id": 5, "metal": 0.0, "energy": 0.0, "reclaim_left": 0.0},
        {"t": "work", "f": 60, "u": 1, "team": 0, "task": "none"},
        {"t": "work", "f": 70, "u": 1, "team": 0, "task": "build", "unit": 11},
        {"t": "work", "f": 80, "u": 1, "team": 0, "task": "none"},
        wreck,
        {
            "t": "fcreated",
            "f": 125,
            "id": 6,
            "d": WRECK,
            "x": 410,
            "z": 400,
            "metal": 30.0,
            "energy": 0.0,
            "rez": BOT,
        },
        {"t": "work", "f": 150, "u": 2, "team": 1, "task": "resurrect", "feature": 6},
        event("created", 170, 12, BOT, 1, 410, 400, by=2, rez=6),
        event("finished", 170, 12, BOT, 1, 410, 400),  # a resurrected unit is finished
        {"t": "fdestroyed", "f": 171, "id": 6, "metal": 30.0, "energy": 0.0, "reclaim_left": 1.0},
        {"t": "work", "f": 180, "u": 2, "team": 1, "task": "repair", "unit": 12},
    ]
    # a feature type has no frame: it comes right before the first feature of its type
    keyed = [(line["f"], LINE_ORDER[line["t"]], line) for line in lines[1:-1]]
    keyed += [
        (line["f"] if "f" in line else added[i + 1]["f"], LINE_ORDER[line["t"]], line)
        for i, line in enumerate(added)
    ]
    body = [line for *_, line in sorted(keyed, key=lambda item: item[:2])]
    end = {**lines[-1], "game_reclaimed": [[0, 50.0, 0.0], [1, 0.0, 0.0]]}
    return [lines[0], *body, end]


def write_state(path: Path, lines: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as file:
        for line in lines:
            file.write(json.dumps(line, separators=(",", ":")) + "\n")
    return path


def test_read_records_makes_format_5_snapshots_whole(tmp_path):
    path = write_state(tmp_path / "game.jsonl.gz", lines_v5())
    snapshots = [record for record in read_records(path, snapshots=True) if record["t"] == "s"]
    at_60 = snapshots[1]
    assert at_60["f"] == 60
    assert at_60["wind"] == 10.6
    assert at_60["teams"][0] == [0, 160, 500, 2.5, 1.2, 900, 1000, 25, 10]
    # the finished extractor comes from the unit lines, with an unknown health
    assert at_60["units"] == [
        [1, COMMANDER, 0, 160, 100, 100, 100],
        [2, COMMANDER, 1, 900, 900, 100, 100],
        [10, EXTRACTOR, 0, 120, 140, None, 100],
    ]
    at_120 = snapshots[2]
    assert [10, EXTRACTOR, 1, 120, 140, None, 100] in at_120["units"]  # given
    assert snapshots[3]["units"][-1] == [11, EXTRACTOR, 1, 700, 720, 100, 40]
    # without snapshots, neither snapshot nor resource lines come
    kinds = {record["t"] for record in read_records(path)}
    assert kinds == {
        "header",
        "created",
        "finished",
        "idle",
        "given",
        "hit",
        "destroyed",
        "damage",
        "end",
    }


def test_format_5_reads_like_format_4(tmp_path):
    """Made whole, the snapshots of format 5 hold what those of format 4 did."""
    new = write_state(tmp_path / "new.jsonl.gz", lines_v5())
    old = write_state(tmp_path / "old.jsonl.gz", lines_v4())

    def units(path):
        return [
            [unit[:5] + [unit[6]] for unit in record["units"]]
            for record in read_records(path, snapshots=True)
            if record["t"] == "s"
        ]

    assert units(new) == units(old)


@pytest.mark.parametrize("make_lines", [lines_v6, lines_v5, lines_v4])
def test_tables_read_like_the_state_file(tmp_path, make_lines):
    path = write_state(tmp_path / "date=2026-11-21" / "2026-11-21_game.jsonl.gz", make_lines())
    result = tables.convert(path)
    assert result["rows"]["game"] == 1
    assert tables.converted(path)
    assert tables.convert(path) == {"state_file": str(path), "skipped": True}
    events_path = tables.table_path(path, "events")
    assert events_path.name == "2026-11-21_game.events.parquet"
    for snapshots in (False, True):
        assert list(read_records(events_path, snapshots)) == list(read_records(path, snapshots))


def test_table_types_and_order(tmp_path):
    path = write_state(tmp_path / "2026-11-21_game.jsonl.gz", lines_v5())
    tables.convert(path)
    game = tables.read_game(path)
    for table, schema in tables.TABLE_SCHEMAS.items():
        assert dict(game[table].schema) == schema, table
    row = game["game"].row(0, named=True)
    assert row["replay"] == "2026-11-21_game"
    assert row["version"] == 5 and row["sampled"] == "frame_end" and row["complete"]
    assert [unit_def["name"] for unit_def in row["unit_defs"] if unit_def["static"]] == ["armmex"]
    resources = game["resources"]
    assert resources.height == 7 * 3  # every 30 frames, three teams
    assert resources.get_column("team").is_sorted()
    assert resources.filter(pl.col("team") == 0).get_column("frame").is_sorted()
    events = game["events"]
    assert events.get_column("kind").to_list()[:2] == ["created", "finished"]
    assert events.filter(pl.col("kind") == "given").row(0, named=True)["from_team"] == 0
    destroyed = events.filter(pl.col("kind") == "destroyed").row(0, named=True)
    assert destroyed["built"] is True and destroyed["by_team"] == 1
    hit = game["hits"].row(0, named=True)
    assert hit["by_def"] == "armcom" and hit["damage"] == 60
    units = game["units"]
    assert units.filter(pl.col("frame") == 60).get_column("unit_id").to_list() == [1, 2]


def test_scan_by_date(tmp_path):
    state_dir = tmp_path / "state"
    for day in ("2026-11-20", "2026-11-21"):
        tables.convert(write_state(state_dir / f"date={day}" / f"{day}_game.jsonl.gz", lines_v5()))
    every = tables.scan(state_dir, "events").collect()
    assert every.get_column("replay").cast(pl.String).unique().sort().to_list() == [
        "2026-11-20_game",
        "2026-11-21_game",
    ]
    one = tables.scan(state_dir, "game", since=date(2026, 11, 21)).collect()
    assert one.get_column("replay").to_list() == ["2026-11-21_game"]
    none = tables.scan(state_dir, "units", until=date(2026, 11, 1)).collect()
    assert none.height == 0 and dict(none.schema) == tables.TABLE_SCHEMAS["units"]


def test_paths_and_names():
    assert tables.state_stem("d/x.jsonl.gz") == Path("d/x")
    assert tables.state_stem("d/x.v1.2.units.parquet") == Path("d/x.v1.2")
    assert tables.table_path("d/x.jsonl", "damage") == Path("d/x.damage.parquet")
    assert tables.replay_name("state/date=2026-11-21/x.jsonl.gz") == "x"
    assert tables.replay_name("eval/barb-vs-barb/001-a/state.jsonl.gz") == "barb-vs-barb/001-a"
    with pytest.raises(ValueError):
        tables.state_stem("d/x.txt")


def test_standing_units(tmp_path):
    path = write_state(tmp_path / "game.jsonl.gz", lines_v5())
    tables.convert(path)
    events = tables.scan(tmp_path, "events")

    def rebuilt(frame, team=None):
        units = standing.standing_units(events, frame, team)
        return [
            (row["unit_id"], row["unit_def"], row["team"], row["finished"])
            for row in units.iter_rows(named=True)
        ]

    assert rebuilt(20) == [
        (1, "armcom", 0, True),
        (2, "armcom", 1, True),
        (10, "armmex", 0, False),
    ]
    assert rebuilt(90, team=1) == [(2, "armcom", 1, True), (10, "armmex", 1, True)]
    assert rebuilt(124, team=0) == [(1, "armcom", 0, True), (11, "armpw", 0, True)]
    assert rebuilt(125, team=0) == [(1, "armcom", 0, True)]
    assert rebuilt(130)[-1] == (11, "armmex", 1, False)  # the id used again
    position = standing.standing_units(events, 200).filter(pl.col("unit_id") == 11)
    assert position.select("x", "z", "created_frame").row(0) == (700, 720, 130)
    assert standing.standing_units(events, 200).columns[0] == "replay"


@pytest.mark.parametrize("make_lines", [lines_v5, lines_v4])
def test_check_finds_no_difference(tmp_path, make_lines):
    lines = make_lines()
    if make_lines is lines_v4:
        # a format 4 snapshot is taken at the start of its frame: the events of that frame
        # come after it
        for line in lines:
            if line["t"] in tables.UNIT_EVENT_KINDS and line["f"] > 0:
                line["f"] -= 1
    result = standing.check_file(write_state(tmp_path / "game.jsonl.gz", lines))
    assert result["counts"]["snapshots"] == 4
    assert set(result["counts"]) == {"snapshots", "units"}, result["examples"]


def test_check_reports_differences(tmp_path):
    lines = lines_v5()
    for line in lines:
        if line["t"] == "s" and line["f"] == 120:
            line["units"] = [unit for unit in line["units"] if unit[0] != 11]  # bot missing
            line["units"].append([99, BOT, 0, 0, 0, 100, 100])  # never created
    result = standing.check_file(write_state(tmp_path / "game.jsonl.gz", lines))
    assert result["counts"]["only_rebuilt"] == 1
    assert result["counts"]["only_in_snapshot"] == 1


def test_a_doubled_snapshot_counts_once(tmp_path):
    """Up to format 4 a run stopped at a snapshot frame wrote that snapshot twice."""
    lines = lines_v4()
    lines.insert(-1, lines[-2])
    path = write_state(tmp_path / "game.jsonl.gz", lines)
    game = tables.read_game(tables.convert(path)["state_file"])
    assert game["units"].filter(pl.col("frame") == 180).height == 4
    assert game["resources"].filter(pl.col("frame") == 180).height == 3


def test_features_reclaim_and_work(tmp_path):
    path = write_state(tmp_path / "2026-11-21_game.jsonl.gz", lines_v6())
    tables.convert(path)
    game = tables.read_game(path)
    for table, schema in tables.TABLE_SCHEMAS.items():
        assert dict(game[table].schema) == schema, table
    row = game["game"].row(0, named=True)
    assert row["version"] == 6 and row["work_frames"] == 10
    assert [feature_def["name"] for feature_def in row["feature_defs"]] == ["rock1", "armpw_dead"]
    assert row["game_reclaimed"][0] == {"team": 0, "metal": 50.0, "energy": 0.0}
    features = game["features"].select(
        "feature_id", "feature_def", "created_frame", "resurrect_as", "destroyed_frame", "end"
    )
    assert [
        tuple(str(value) if value is not None else None for value in row) for row in features.rows()
    ] == [
        ("5", "rock1", "0", None, "60", "reclaimed"),
        ("6", "armpw_dead", "125", "armpw", "171", "resurrected"),
    ]
    reclaim = game["reclaim"].row(0, named=True)
    assert (reclaim["feature_id"], reclaim["team"], reclaim["from_frame"], reclaim["metal"]) == (
        5,
        0,
        50,
        50.0,
    )
    work = game["work"]
    assert work.get_column("unit_id").is_sorted()
    assert work.filter(pl.col("task") == "reclaim").row(0, named=True)["target_feature"] == 5
    events = game["events"]
    made = events.filter(pl.col("unit_id") == 12).row(0, named=True)
    assert (made["builder"], made["resurrected_from"]) == (2, 6)
    destroyed = events.filter(pl.col("kind") == "destroyed").row(0, named=True)
    assert (destroyed["attacker"], destroyed["weapon_def"], destroyed["reclaimed"]) == (
        2,
        17,
        False,
    )


def test_format_5_tables_read_with_format_6(tmp_path):
    """Tables written before format 6 have no feature, reclaim and work files and fewer
    event columns; they read with the tables of format 6 games as empty ones."""
    state_dir = tmp_path / "state"
    old = write_state(state_dir / "date=2026-11-20" / "2026-11-20_old.jsonl.gz", lines_v5())
    new = write_state(state_dir / "date=2026-11-21" / "2026-11-21_new.jsonl.gz", lines_v6())
    tables.convert(old)
    tables.convert(new)
    for table in ("features", "reclaim", "work"):
        tables.table_path(old, table).unlink()
    events_path = tables.table_path(old, "events")
    pl.read_parquet(events_path).drop(
        "attacker", "weapon_def", "reclaimed", "resurrected_from"
    ).write_parquet(events_path)
    game = tables.read_game(old)
    assert game["features"].height == 0
    assert dict(game["events"].schema) == tables.TABLE_SCHEMAS["events"]
    events = tables.scan(state_dir, "events").collect()
    assert events.get_column("replay").cast(pl.String).unique().len() == 2
    assert events.filter(pl.col("resurrected_from").is_not_null()).height == 1
    assert list(read_records(events_path, True)) == list(read_records(old, True))
