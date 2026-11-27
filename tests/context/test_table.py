"""Tests for the decision table: the join of opening orders with the state, on made-up games."""

import json

import polars as pl
import pytest

from reason8.context import check, table
from reason8.headless import standing, tables
from reason8.openings.dataset import ORDER_COLUMNS
from tests.headless.test_tables import lines_v5, write_state

REPLAY = "2026-11-01_10-00-00-000_Test Valley 1.0_2026.09.03"
ROLES = ["mex", "pw", "com", "other"]
TEAMS = [
    {"team": 0, "ally_team": 0, "ai": False, "side": "armada", "gaia": False},
    {"team": 1, "ally_team": 0, "ai": False, "side": "armada", "gaia": False},
    {"team": 2, "ally_team": 1, "ai": False, "side": "cortex", "gaia": False},
]


def test_unit_roles():
    units = ["armwin"] * 6 + ["corwin"] * 2 + ["armmex"] * 2 + ["armlab"]
    assert table.unit_roles(units, coverage=0.8) == ["win", "mex", "com", "other"]
    assert table.unit_roles(units, coverage=1.0) == ["win", "mex", "lab", "com", "other"]


def test_unit_changes_sum_to_the_standing_units(tmp_path):
    """Summed up to any frame, the changes give what standing_units() rebuilds."""
    path = write_state(tmp_path / "game.jsonl.gz", lines_v5())
    tables.convert(path)
    events = tables.read_game(path)["events"]
    roles = ["mex", "pw", "com", "other"]
    changes = table.unit_changes(events).collect()
    counts = table.running_counts(changes, "team", "own", roles)
    names = table.unit_counts_columns("own", roles)
    for frame in range(0, 200, 5):
        for team in (0, 1):
            expected = dict.fromkeys(names, 0)
            for row in standing.standing_units(events, frame, team).iter_rows(named=True):
                role = str(row["unit_def"])[3:]
                state = "done" if row["finished"] else "building"
                expected[f"own_{state}_{role}"] += 1
            found = counts.filter(pl.col("team") == team, pl.col("frame") <= frame)
            rebuilt = found.select(names).tail(1).to_dicts()
            assert (rebuilt[0] if rebuilt else dict.fromkeys(names, 0)) == expected, (frame, team)


def event(frame, kind, unit_id, unit_def, team, **extra):
    return {
        "replay": REPLAY,
        "frame": frame,
        "kind": kind,
        "unit_id": unit_id,
        "unit_def": unit_def,
        "team": team,
        "x": 100 * unit_id,
        "z": 100,
        **extra,
    }


def state_tables() -> dict[str, pl.DataFrame]:
    """A made-up game: teams 0 and 1 are allies, team 2 is the enemy."""
    events = [
        event(0, "created", 1, "armcom", 0),
        event(0, "finished", 1, "armcom", 0),
        event(0, "created", 2, "armcom", 1),
        event(0, "finished", 2, "armcom", 1),
        event(0, "created", 3, "corcom", 2),
        event(0, "finished", 3, "corcom", 2),
        event(40, "created", 10, "armmex", 0, builder=1),
        event(50, "created", 11, "armmex", 1, builder=2),
        event(50, "created", 12, "cormex", 2, builder=3),
        event(95, "finished", 10, "armmex", 0),
        event(120, "created", 13, "armpw", 0, builder=1),
        event(130, "given", 11, "armmex", 0, from_team=1),
        event(150, "destroyed", 10, "armmex", 0, built=True, by_team=2),
    ]
    resources = [
        {
            "replay": REPLAY,
            "frame": frame,
            "team": team,
            "metal": 1000 - frame - team,
            "metal_storage": 1000,
            "metal_income": 1.0 + team,
            "metal_expense": 0.5,
            "energy": 900 + team,
            "energy_storage": 1000,
            "energy_income": 20.0,
            "energy_expense": 10.0,
            "wind": 5.0 + frame / 30,
        }
        for frame in range(0, 181, 30)
        for team in range(3)
    ]
    game = {
        "replay": REPLAY,
        "version": 5,
        "last_frame": 180,
        "complete": True,
        "end_reason": "maxframe",
        "wind_min": 0.0,
        "wind_max": 20.0,
        "teams": TEAMS,
    }
    schemas = tables.TABLE_SCHEMAS
    return {
        "events": pl.DataFrame(events, schema=schemas["events"]),
        "resources": pl.DataFrame(resources, schema=schemas["resources"]),
        "game": pl.DataFrame([game]).with_columns(
            pl.col("teams").cast(schemas["game"]["teams"]),
            pl.col("version").cast(pl.Int16),
            pl.col("last_frame").cast(pl.Int32),
            pl.col("wind_min", "wind_max").cast(pl.Float32),
        ),
    }


def order(team, index, frame, unit, seq_idx, repeat=False, count=1, kind="structure"):
    return {
        "match_id": 7,
        "player_slot": team,
        "order_index": index,
        "seq_idx": seq_idx,
        "frame": frame,
        "unit": unit,
        "kind": kind,
        "count": count,
        "via": "COMMAND",
        "queued": False,
        "inserted": False,
        "quota": False,
        "repeat": repeat,
        "x": 100.0 * (10 + index) if kind == "structure" else None,
        "z": 100.0,
    }


ORDERS = [
    order(0, 0, 0, "armmex", 0),
    order(0, 1, 0, "armmex", 1, repeat=True),
    order(0, 2, 60, "armpw", 2, kind="factory"),
    order(0, 3, 61, "armpw", None, count=-1, kind="factory"),
    order(0, 4, 121, "armmex", 3),
    order(0, 5, 151, "armlab", 4),
    order(1, 0, 30, "armmex", 0),
]


def orders_frame() -> pl.DataFrame:
    return pl.DataFrame(ORDERS, schema=ORDER_COLUMNS).with_columns(
        pl.lit(REPLAY).alias("replay"), pl.lit("armada").alias("faction")
    )


def test_with_steps():
    rows = table.with_steps(orders_frame()).filter(pl.col("player_slot") == 0)
    assert rows["step_idx"].to_list() == [0, None, 1, None, 2, 3]
    assert rows["state_frame"].to_list() == [0, 0, 59, 60, 120, 150]
    assert rows["since_previous_s"].to_list() == pytest.approx(
        [None, None, 2.0, 1 / 30, 2.0, 1.0], nan_ok=True
    )


def test_join_state():
    state = state_tables()
    joined = table.join_state(
        table.with_steps(orders_frame()),
        state["game"],
        state["resources"],
        state["events"],
        ROLES,
    )
    assert joined.height == len(ORDERS)
    assert joined.select("player_slot", "order_index").rows() == [
        (row["player_slot"], row["order_index"]) for row in ORDERS
    ]
    rows = {(row["player_slot"], row["order_index"]): row for row in joined.iter_rows(named=True)}
    # the resources line of the second before the order, never one after it
    assert [rows[0, index]["resources_frame"] for index in range(6)] == [0, 0, 30, 60, 120, 150]
    assert rows[0, 4]["metal"] == 1000 - 120
    assert rows[0, 4]["allies_metal"] == 1000 - 120 - 1  # team 1, not the enemy
    assert rows[0, 4]["wind"] == pytest.approx(9.0)
    assert (rows[0, 4]["wind_min"], rows[0, 4]["wind_max"]) == (0.0, 20.0)
    # units after the events of the frame before the order
    assert rows[0, 2]["own_building_mex"] == 1 and rows[0, 2]["own_done_mex"] == 0
    assert rows[0, 2]["allies_building_mex"] == 1  # the enemy's cormex is not counted
    assert rows[0, 4]["own_done_mex"] == 1
    assert rows[0, 4]["own_building_pw"] == 1  # created in frame 120, the order is in 121
    assert rows[0, 4]["own_building_mex"] == 0
    # at 150: armmex 10 destroyed in that frame, armmex 11 given by team 1 at 130
    assert rows[0, 5]["own_done_mex"] == 0 and rows[0, 5]["own_building_mex"] == 1
    assert rows[0, 5]["allies_building_mex"] == 0
    assert rows[0, 5]["own_building_pw"] == 1 and rows[0, 5]["own_done_com"] == 1
    assert rows[1, 0]["own_done_com"] == 1 and rows[1, 0]["allies_done_com"] == 1


def write_source(directory, splits):
    """A made-up opening dataset with the given split of match 7."""
    directory.mkdir(parents=True)
    rows = (
        orders_frame()
        .drop("replay")
        .with_columns(
            pl.lit("Test Valley 1.0").alias("map"),
            pl.format("P{}", pl.col("player_slot")).alias("position"),
            pl.lit("front").alias("role"),
            pl.lit(31000, dtype=pl.Int32).alias("build"),
            pl.lit(None, dtype=pl.Int32).alias("opening_era"),
        )
    )
    for split in ("train", "validation", "test"):
        part = rows if splits.get(7) == split else rows.clear()
        part.write_parquet(directory / f"{split}.parquet")
    manifest = {
        "name": "openings_test",
        "built_at": "2026-11-01T00:00:00+00:00",
        "code": {"commit": "abc", "dirty": False},
        "split": {"rule": "made up"},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))


def write_state_tables(directory):
    stem = directory / "date=2026-11-01" / REPLAY
    stem.parent.mkdir(parents=True)
    for name, frame in state_tables().items():
        frame.write_parquet(tables.table_path(stem, name))


def test_build_table_and_check(tmp_path):
    write_source(tmp_path / "source", {7: "train"})
    write_state_tables(tmp_path / "state")
    sample = pl.DataFrame(
        {
            "match_id": [7, 8],
            "replay_file_name": [REPLAY + ".sdfz", "2026-11-02_x.sdfz"],
            "map": ["Test Valley 1.0"] * 2,
            "split": ["train", "test"],
        }
    )
    out = tmp_path / "context"
    manifest = table.build_table(
        out, sample, source=tmp_path / "source", states=tmp_path / "state", log=lambda _: None
    )
    assert manifest["counts"]["games_by_status"] == {"ok": 1, table.NOT_SIMULATED: 1}
    assert manifest["counts"]["rows"] == {"train": len(ORDERS), "validation": 0, "test": 0}
    assert manifest["counts"]["steps"] == 5
    assert set(manifest["groups"]) == set(table.GROUPS)
    rows = pl.read_parquet(out / "train.parquet")
    for columns in manifest["groups"].values():
        assert set(columns) <= set(rows.columns)
    assert (out / "splits" / "train.txt").read_text() == "7\n"
    games = pl.read_parquet(out / "games.parquet")
    assert games.filter(pl.col("match_id") == 8)["status"].item() == table.NOT_SIMULATED

    roles = manifest["unit_roles"]["roles"]
    result = check.check_game(rows, tmp_path / "state" / "date=2026-11-01" / REPLAY, roles)
    assert result["rows"] == len(ORDERS)
    for name in ("resources_frame_differs", "resources_differ", "own_units_differ"):
        assert result[name] == 0, name
    assert result["allies_units_differ"] == 0

    created = check.ordered_and_created(rows, state_tables()["events"])
    assert created.height == 5  # structure orders that add a unit
    # the order on the spot of armmex 10 (x 1000), made 40 frames later; nothing on the others
    assert created["created_frame"].to_list() == [40, None, None, None, None]


def test_time_since_an_earlier_frame():
    """Orders of one frame all get the time since the last order before that frame."""
    orders = pl.DataFrame(
        [order(0, 0, 30, "armmex", 0), order(0, 1, 60, "armmex", 1), order(0, 2, 60, "armwin", 2)],
        schema=ORDER_COLUMNS,
    )
    rows = table.with_steps(orders)
    assert rows["step_idx"].to_list() == [0, 1, 2]
    assert rows["since_previous_s"].to_list() == [None, 1.0, 1.0]
