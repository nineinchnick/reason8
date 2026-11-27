"""Tests for the builders of the decision table, on made-up units, commands and events."""

import polars as pl
import pytest

from reason8.context import builders
from reason8.game.unitdefs import UnitDef
from reason8.headless import tables

REPLAY = "2026-11-01_10-00-00-000_Test Valley 1.0_2026.09.03"
GAME = "Test 1"


def unit(name, **fields):
    return UnitDef(name, fields)


UNIT_DEFS = {
    "armcom": unit(
        "armcom",
        workertime=300,
        speed=37.5,
        buildoptions=["armmex", "armlab"],
        customparams={"iscommander": True},
    ),
    "armlab": unit("armlab", workertime=150, buildoptions=["armpw", "armck"]),
    "armck": unit("armck", workertime=80, speed=36, buildoptions=["armmex"]),
    "armnanotc": unit("armnanotc", workertime=200, canreclaim=True),
    "armrectr": unit("armrectr", workertime=200, speed=78, canassist=False, canresurrect=True),
    "armpw": unit("armpw", speed=80),
    "armmex": unit("armmex", extractsmetal=0.001),
}


def types() -> pl.DataFrame:
    return pl.DataFrame(
        builders.builder_type_rows(GAME, UNIT_DEFS), schema=builders.BUILDER_TYPE_SCHEMA
    )


def test_builder_kinds_and_jobs():
    rows = {row["unit_def"]: row for row in types().iter_rows(named=True)}
    assert {name: row["builder_kind"] for name, row in rows.items()} == {
        "armcom": "commander",
        "armlab": "factory",
        "armck": "construction",
        "armnanotc": "tower",
        "armrectr": "other",
    }
    assert rows["armlab"]["builder_moves"] is False and rows["armck"]["builder_moves"] is True
    assert rows["armcom"]["build_power"] == 300
    jobs = {name: [job for job in builders.JOBS if row[f"can_{job}"]] for name, row in rows.items()}
    assert jobs == {
        "armcom": ["assist", "reclaim", "repair"],
        "armlab": [],  # factories do no jobs
        "armck": ["assist", "reclaim", "repair"],
        "armnanotc": ["assist", "reclaim", "repair"],
        "armrectr": ["reclaim", "repair", "resurrect"],
    }
    answers = dict(builders.answers_of(types()).select("builder_unit", "answers").rows())
    assert answers["armlab"] == ["armck", "armpw"]
    assert answers["armrectr"] == ["reclaim", "repair", "resurrect"]


def test_command_units_follow_the_selection():
    selections = pl.DataFrame(
        {"replay": [REPLAY] * 3, "player": [0, 0, 1], "seq": [1, 4, 2], "units": [[1], [5, 6], [9]]}
    )
    commands = pl.DataFrame(
        {
            "replay": [REPLAY] * 4,
            "player": [0, 0, 0, 1],
            "seq": [3, 5, 6, 7],
            "via": ["COMMAND", "COMMAND", "AICOMMAND", "COMMAND"],
            "units": [None, None, [7], None],
        }
    )
    found = builders.command_units(commands.lazy(), selections.lazy()).collect().sort("seq")
    assert found["targets"].to_list() == [[1], [5, 6], [7], [9]]


def event(frame, kind, unit_id, unit_def, team, **extra):
    return {
        "replay": REPLAY,
        "frame": frame,
        "kind": kind,
        "unit_id": unit_id,
        "unit_def": unit_def,
        "team": team,
        **extra,
    }


EVENTS = [
    event(0, "created", 1, "armcom", 0),
    event(0, "finished", 1, "armcom", 0),
    event(10, "created", 2, "armlab", 0, builder=1),
    event(40, "finished", 2, "armlab", 0),
    event(50, "created", 3, "armpw", 0, builder=2),
    event(60, "finished", 3, "armpw", 0),
    event(70, "created", 4, "armck", 0, builder=2),
    event(80, "finished", 4, "armck", 0),
    event(90, "idle", 4, "armck", 0),
    event(100, "destroyed", 3, "armpw", 0, built=True, by_team=1),
    event(110, "created", 3, "armnanotc", 0, builder=4),  # unit id 3 used again
    event(130, "idle", 1, "armcom", 0),
    event(150, "given", 4, "armck", 1, from_team=0),
]


def events() -> pl.DataFrame:
    return pl.DataFrame(EVENTS, schema=tables.TABLE_SCHEMAS["events"])


def test_units_at_follow_each_life():
    lives = builders.unit_lives(events()).collect()
    wanted = pl.DataFrame(
        {"replay": [REPLAY] * 5, "frame": [55, 105, 115, 20, 160], "unit_id": [3, 3, 3, 2, 4]}
    )
    found = builders.units_at(wanted, lives)
    assert found["unit_def"].to_list() == ["armpw", "armpw", "armnanotc", "armlab", "armck"]
    assert found["alive"].to_list() == [True, False, True, True, True]
    assert found["finished"].to_list() == [False, True, False, False, True]
    assert found["owner"].to_list() == [0, 0, 0, 0, 1]


@pytest.mark.parametrize(
    ("command", "params", "finished", "job", "target"),
    [
        ("GUARD", [2.0], True, "assist", "unit"),
        ("REPAIR", [3.0], False, "assist", "unit"),  # helping to build it
        ("REPAIR", [3.0], True, "repair", "unit"),
        ("REPAIR", [1.0, 0.0, 2.0, 300.0], None, "repair", "area"),
        ("RECLAIM", [32005.0], None, "reclaim", "feature"),
        ("RECLAIM", [1.0, 0.0, 2.0, 300.0], None, "reclaim", "area"),
        ("RECLAIM", [3.0], True, "reclaim", "unit"),
        ("RESURRECT", [32005.0], None, "resurrect", "feature"),
        ("MOVE", [1.0, 0.0, 2.0], None, None, "spot"),
    ],
)
def test_jobs(command, params, finished, job, target):
    frame = pl.DataFrame(
        {"command": [command], "params": [params], "finished": [finished]},
        schema={"command": pl.String, "params": pl.List(pl.Float32), "finished": pl.Boolean},
    )
    found = frame.select(
        builders.job_of(pl.col("command"), pl.col("params"), pl.col("finished")).alias("job"),
        builders.job_target(pl.col("command"), pl.col("params")).alias("target"),
    ).row(0)
    assert found == (job, target)


def decisions() -> pl.DataFrame:
    """Orders of player 0: a mex to the commander and an army unit, a bot to the factory,
    a reclaim to the commander, the factory and the bot, a mex to a unit of another team."""
    return pl.DataFrame(
        {
            "match_id": [7] * 4,
            "player_slot": [0] * 4,
            "decision_index": [0, 1, 2, 3],
            "replay": [REPLAY] * 4,
            "frame": [60, 61, 85, 160],
            "unit": ["armmex", "armpw", None, "armmex"],
            "kind": ["structure", "factory", "job", "structure"],
            "job": [None, None, "reclaim", None],
            "targets": [[1, 3], [2], [1, 2, 4], [4]],
        }
    )


def test_order_builders():
    lives = builders.unit_lives(events()).collect()
    games = pl.DataFrame({"replay": [REPLAY], "game": [GAME]})
    rows = builders.order_builders(decisions(), lives, types(), games)
    found = rows.select(
        "decision_index", "builder_index", "builder_id", "builder_kind", "builders", "other_units"
    ).rows()
    assert found == [
        (0, 0, 1, "commander", 1, 1),
        (1, 0, 2, "factory", 1, 0),
        # the factory cannot reclaim; the commander has more build power than the ck
        (2, 0, 1, "commander", 2, 0),
        (2, 1, 4, "construction", 2, 0),
        # the ck was given to team 1 at frame 150: not the player's any more
        (3, 0, None, None, 0, 0),
    ]
    assert rows["builder_role"].to_list()[:2] == ["com", "lab"]


def test_builder_history():
    rows = pl.DataFrame(
        {
            "match_id": [7] * 4,
            "player_slot": [0] * 4,
            "decision_index": [0, 1, 2, 3],
            "builder_id": [1, 2, 1, None],
            "answer": ["armmex", "armpw", "reclaim", "armmex"],
        }
    )
    found = builders.with_builder_history(rows)
    assert found["builder_previous"].to_list() == ["<start>", "<start>", "armmex", None]


def test_build_power_and_idle_builders():
    from reason8.context.table import unit_changes

    lives = builders.unit_lives(events()).collect()
    games = pl.DataFrame({"replay": [REPLAY], "game": [GAME]})
    power = builders.team_build_power(unit_changes(events()).collect(), types(), games)
    at = {
        frame: row
        for frame, row in zip(power["frame"], power.iter_rows(named=True), strict=True)
        if row["team"] == 0
    }
    assert at[0]["team_build_power_commander"] == 300
    assert at[40]["team_build_power_factory"] == 150
    assert at[80]["team_build_power_construction"] == 80
    assert at[150]["team_build_power_construction"] == 0  # given away

    commands = pl.DataFrame(
        {
            "replay": [REPLAY, REPLAY],
            "frame": [95, 120],
            "command": ["MOVE", "FIRE_STATE"],
            "targets": [[4], [1]],
        }
    )
    transitions = builders.transitions_of(
        commands, events(), builders.builder_unit_ids(lives, types(), games)
    )
    assert transitions.select("unit_id", "frame", "idle").rows() == [
        (1, 130, True),
        (3, 100, False),  # the bot that had id 3 before the tower was destroyed
        (4, 90, True),
        (4, 95, False),  # moved
        (4, 150, False),  # given away
    ]
    idle = builders.idle_build_power(transitions, lives, types(), games)
    values = {
        (row["team"], row["frame"]): row["idle_build_power_construction"]
        + row["idle_build_power_commander"]
        for row in idle.iter_rows(named=True)
    }
    assert values == {(0, 90): 80, (0, 95): 0, (0, 130): 300}
    rows = pl.DataFrame(
        {
            "replay": [REPLAY] * 4,
            "builder_id": [4, 4, 1, 1],
            "state_frame": [92, 100, 100, 140],
        }
    )
    assert builders.builder_idle(rows, transitions).to_list() == [True, False, None, True]
