"""Tests for the decision table: the join of opening orders with the state, on made-up games."""

import json

import polars as pl
import pytest

from reason8.context import builders, check, table
from reason8.game.maps import parse_map_list
from reason8.headless import standing, tables
from reason8.openings.dataset import ORDER_COLUMNS
from tests import synthetic
from tests.headless.test_tables import lines_v5, write_state
from tests.synthetic import write_tables

MAP_LIST = parse_map_list(synthetic.MAP_LIST_YAML)

REPLAY = "2026-11-01_10-00-00-000_Test Valley 1.0_2026.09.03"
ROLES = ["mex", "pw", "com", "other"]
GAME = "Test 1"
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
        event(0, "created", 20, "armlab", 0),
        event(0, "finished", 20, "armlab", 0),
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
        "game": GAME,
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


def test_with_spawn_positions_take_the_start_from_the_commander():
    events = pl.DataFrame(
        [
            event(0, "created", 1, "armcom", 0),
            event(0, "created", 2, "armcom", 1),
            event(0, "created", 20, "armlab", 0),
            event(900, "created", 5, "armcom", 1),  # a second commander, later
        ]
    ).with_columns(
        pl.when(pl.col("unit_id") == 2).then(900).otherwise(pl.col("x")).alias("x"),
        pl.when(pl.col("unit_id") == 2).then(9100).otherwise(pl.col("z")).alias("z"),
    )
    games = pl.DataFrame({"replay": [REPLAY], "game": [GAME]})
    spawns = table.commander_spawns(events, builder_types(), games)
    assert sorted(spawns.rows()) == [(REPLAY, 0, 100.0, 100.0), (REPLAY, 1, 900.0, 9100.0)]

    # both players were labelled P1 from their replay starts; player 1's commander was
    # created at P2, player 2 has no commander in the state
    orders = pl.DataFrame(
        {
            "replay": [REPLAY] * 3,
            "match_id": [7] * 3,
            "player_slot": [0, 1, 2],
            "map": [synthetic.MAP] * 3,
            "team_size": [2] * 3,
            "start_x": [3000.0] * 3,
            "start_z": [7000.0] * 3,
            "position": ["P1"] * 3,
            "role": ["front"] * 3,
            "position_index": [0] * 3,
            "on_spot": [True] * 3,
        },
        schema_overrides={
            "player_slot": pl.Int32,
            "team_size": pl.Int32,
            "start_x": pl.Float32,
            "start_z": pl.Float32,
            "position_index": pl.Int32,
        },
    )
    moved = table.with_spawn_positions(orders, spawns, MAP_LIST)
    assert moved.select(*table.START_COLUMNS).rows() == [
        (100.0, 100.0, "P1", "front", 0, False),
        (900.0, 9100.0, "P2", "air", 1, True),
        (3000.0, 7000.0, "P1", "front", 0, True),
    ]
    assert table.with_spawn_positions(orders, spawns, {}).equals(orders)


def test_with_times():
    rows = table.with_times(orders_frame()).filter(pl.col("player_slot") == 0)
    assert rows["state_frame"].to_list() == [0, 0, 59, 60, 120, 150]
    assert rows["since_previous_s"].to_list() == pytest.approx(
        [None, None, 2.0, 1 / 30, 2.0, 1.0], nan_ok=True
    )


def test_join_state():
    state = state_tables()
    joined = table.join_state(
        table.with_times(orders_frame()),
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
            pl.lit(2, dtype=pl.Int32).alias("team_size"),
            pl.lit(100.0, dtype=pl.Float32).alias("start_x"),
            pl.lit(100.0, dtype=pl.Float32).alias("start_z"),
            pl.lit(0, dtype=pl.Int32).alias("position_index"),
            pl.lit(True).alias("on_spot"),
            pl.lit(31000, dtype=pl.Int32).alias("build"),
            pl.lit(None, dtype=pl.Int32).alias("opening_era"),
            pl.lit(GAME).alias("game_version"),
            pl.lit(180, dtype=pl.Int32).alias("cutoff_frame"),
            (20.0 + pl.col("player_slot")).cast(pl.Float32).alias("skill"),
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


def builder_types() -> pl.DataFrame:
    rows = [
        {
            "game": GAME,
            "unit_def": "armcom",
            "builder_unit": "armcom",
            "builder_kind": "commander",
            "builder_moves": True,
            "build_power": 300.0,
            "can_assist": True,
            "can_reclaim": True,
            "can_repair": True,
            "can_resurrect": False,
            "build_options": ["armlab", "armmex"],
        },
        {
            "game": GAME,
            "unit_def": "armlab",
            "builder_unit": "armlab",
            "builder_kind": "factory",
            "builder_moves": False,
            "build_power": 150.0,
            "can_assist": False,
            "can_reclaim": False,
            "can_repair": False,
            "can_resurrect": False,
            "build_options": ["armpw"],
        },
    ]
    return pl.DataFrame(rows, schema=builders.BUILDER_TYPE_SCHEMA)


def write_replay_tables(directory):
    """The commands of ORDERS, with the selections they go to, and two jobs: a reclaim of
    an area by player 0's commander, and a guard order to an army unit only."""

    def select(frame, player, units):
        return {"frame": frame, "type": "select", "player": player, "units": units}

    def build(frame, player, unit, opts=(), params=()):
        record = {
            "frame": frame,
            "type": "cmd",
            "player": player,
            "via": "COMMAND",
            "team": player,
            "cmd": "BUILD",
            "cmd_id": -1,
            "unit": unit,
            "params": list(params),
        }
        return record | ({"opts": list(opts)} if opts else {})

    def job(frame, player, command, params):
        return {
            "frame": frame,
            "type": "cmd",
            "player": player,
            "via": "COMMAND",
            "team": player,
            "cmd": command,
            "cmd_id": 1,
            "params": params,
        }

    events = [
        {"frame": 0, "type": "start"},
        select(0, 0, [1]),
        build(0, 0, "armmex", params=[1000, 0, 100, 0]),
        build(0, 0, "armmex", ["shift"], [1100, 0, 100, 0]),
        select(10, 1, [2]),
        build(30, 1, "armmex", params=[1000, 0, 100, 0]),
        select(50, 0, [20]),
        build(60, 0, "armpw"),
        build(61, 0, "armpw", ["right"]),
        select(80, 0, [1]),
        job(90, 0, "RECLAIM", [500.0, 0.0, 500.0, 200.0]),
        build(121, 0, "armmex", params=[1400, 0, 100, 0]),
        select(130, 0, [13]),
        job(140, 0, "GUARD", [1.0]),
        select(145, 0, [1]),
        build(151, 0, "armlab", params=[1500, 0, 100, 0]),
    ]
    players = [
        {"playerId": team, "teamId": team, "allyTeamId": 0 if team < 2 else 1} for team in range(3)
    ]
    document = {
        "format": "reason8.replay/1",
        "meta": {"map": "Test Valley 1.0", "game": GAME, "serverMatchId": "7"},
        "allyTeams": [],
        "players": players,
        "ais": [],
        "modoptions": {},
        "events": events,
    }
    return write_tables(directory, {REPLAY: document})


def build(tmp_path, sample):
    write_source(tmp_path / "source", {7: "train"})
    write_state_tables(tmp_path / "state")
    write_replay_tables(tmp_path / "tables")
    out = tmp_path / "context"
    manifest = table.build_table(
        out,
        sample,
        source=tmp_path / "source",
        states=tmp_path / "state",
        tables=tmp_path / "tables",
        types=builder_types(),
        map_list=MAP_LIST,
        log=lambda _: None,
    )
    return out, manifest


def test_build_table_and_check(tmp_path):
    sample = pl.DataFrame(
        {
            "match_id": [7, 8],
            "replay_file_name": [REPLAY + ".sdfz", "2026-11-02_x.sdfz"],
            "map": ["Test Valley 1.0"] * 2,
            "split": ["train", "test"],
        }
    )
    out, manifest = build(tmp_path, sample)
    assert manifest["counts"]["games_by_status"] == {"ok": 1, table.NOT_SIMULATED: 1}
    # the build orders and the reclaim; the guard order went to an army unit only
    assert manifest["counts"]["rows"] == {"train": len(ORDERS) + 1, "validation": 0, "test": 0}
    assert manifest["counts"]["decisions_by_kind"] == {"structure": 5, "factory": 2, "job": 1}
    assert manifest["counts"]["steps"] == 6
    assert set(manifest["groups"]) == set(table.GROUPS)
    rows = check.load_rows(out)
    for columns in manifest["groups"].values():
        assert set(columns) <= set(rows.columns)
    assert (out / "splits" / "train.txt").read_text() == "7\n"
    games = pl.read_parquet(out / "games.parquet")
    assert games.filter(pl.col("match_id") == 8)["status"].item() == table.NOT_SIMULATED

    # player 1's start is where its commander was created (P0 of player 0 is no position
    # of the map, so player 0 keeps the start of the opening dataset)
    starts = rows.group_by("player_slot").agg(pl.col("start_x", "position").first())
    assert sorted(starts.rows()) == [(0, 100.0, "P0"), (1, 200.0, "P1")]

    first = rows.filter(pl.col("player_slot") == 0)
    assert first["answer"].to_list() == [
        "armmex",
        "armmex",
        "armpw",
        None,  # taken out of the factory's queue
        "reclaim",
        "armmex",
        "armlab",
    ]
    assert (
        first["builder_kind"].to_list() == ["commander"] * 2 + ["factory"] * 2 + ["commander"] * 3
    )
    assert first["builder_previous"].to_list() == [
        "<start>",
        "armmex",
        "<start>",
        None,
        "armmex",
        "reclaim",
        "armmex",
    ]
    assert first["builder_build_power"].to_list() == [300, 300, 150, 150, 300, 300, 300]
    assert first["team_build_power"].to_list() == [450] * 7
    assert first["skill"].to_list() == [20.0] * 7
    assert first["step_idx"].to_list() == [0, None, 1, None, 2, 3, 4]

    roles = manifest["unit_roles"]["roles"]
    first_rows = rows.filter(pl.col("kind") != "job")
    result = check.check_game(first_rows, tmp_path / "state" / "date=2026-11-01" / REPLAY, roles)
    assert result["rows"] == len(ORDERS)
    for name in ("resources_frame_differs", "resources_differ", "own_units_differ"):
        assert result[name] == 0, name
    assert result["allies_units_differ"] == 0

    created = check.ordered_and_created(first_rows, state_tables()["events"])
    assert created.height == 5  # structure orders that add a unit
    # the order on the spot of armmex 10 (x 1000), made 40 frames later; nothing on the others
    assert created["created_frame"].to_list() == [40, None, None, None, None]
    by_builder = check.builders_and_creators(rows, state_tables()["events"])
    matched = by_builder.filter("matched")
    # armmex 10 started by the commander that got the order; armpw 13 not by the factory
    assert matched.select("kind", "by_builder").rows() == [("structure", True)]


def test_load_builder_steps(tmp_path):
    from reason8.context import builder_measure

    sample = pl.DataFrame(
        {"match_id": [7], "replay_file_name": [REPLAY + ".sdfz"], "map": ["M"], "split": ["train"]}
    )
    out, _ = build(tmp_path, sample)
    steps = builder_measure.load_builder_steps(out)
    first = steps.frame.filter(pl.col("player_slot") == 0)
    assert first["unit"].to_list() == ["armmex", "armpw", "reclaim", "armmex", "armlab"]
    assert first["previous_1"].to_list() == ["<start>", "armmex", "armpw", "reclaim", "armmex"]
    # two mex orders (one drag) before the fourth step, none counting the step itself
    assert first["ordered_mex"].to_list() == [0, 2, 2, 2, 3]
    assert first["ordered_reclaim"].to_list() == [0, 0, 0, 1, 1]
    assert set(steps.groups) == {"history", *table.GROUPS}
    mask = builder_measure.mask_matrix(
        first, ["armlab", "armmex", "armpw", "reclaim", "<unknown>"], steps.answers
    )
    assert mask.tolist()[:2] == [
        [True, True, False, True, True],  # the commander
        [False, False, True, False, True],  # the factory
    ]


def test_time_since_an_earlier_frame():
    """Orders of one frame all get the time since the last order before that frame."""
    orders = pl.DataFrame(
        [order(0, 0, 30, "armmex", 0), order(0, 1, 60, "armmex", 1), order(0, 2, 60, "armwin", 2)],
        schema=ORDER_COLUMNS,
    )
    rows = table.with_times(orders)
    assert rows["since_previous_s"].to_list() == [None, 1.0, 1.0]


def test_sample_drawn_reads_how_the_sample_was_drawn(tmp_path):
    sample_path = tmp_path / "sample.parquet"
    assert table.sample_drawn(sample_path) is None  # drawn by hand: nothing to say
    assert table.sample_drawn(None) is None
    description = {"rule": "a rule", "seed": 48, "counts": {"Map A": 3}, "source": {}}
    (tmp_path / "sample.json").write_text(json.dumps({**description, "excluded_match_ids": ["1"]}))
    assert table.sample_drawn(sample_path) == {**description, "drawn_at": None}
