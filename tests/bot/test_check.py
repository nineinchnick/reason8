"""Tests for `reason8 bot check` (no engine needed)."""

from pathlib import Path

from reason8.bot import check
from reason8.replays.replay import BuildOrder
from tests.bot.test_build import ARMADA, TASKS


def order(frame: int, unit: str, builder: int, x: float = 0.0, z: float = 0.0) -> BuildOrder:
    return BuildOrder(
        frame=frame,
        team=0,
        player=255,
        unit=unit,
        kind="structure",
        via="AICOMMAND",
        builders=(builder,),
        x=x,
        z=z,
    )


def armada_game(factory_units: list[str]) -> list[BuildOrder]:
    """Orders as BARb sends them: one repeated, factory orders all at the factory's place."""
    commander, factory = 100, 200
    orders = [
        order(46, "armwin", commander, 10, 10),
        order(318, "armwin", commander, 20, 10),
        order(598, "armmex", commander, 30, 10),
        order(600, "armmex", commander, 30, 10),  # re-sent
        order(864, "armrad", commander, 40, 10),
        order(1059, "armlab", commander, 50, 10),
    ]
    orders += [
        order(1700 + index, unit, factory, 50, 10) for index, unit in enumerate(factory_units)
    ]
    orders.insert(8, order(1702, "armmex", commander, 60, 10))  # BARb took over
    return orders


def test_check_ordered_matches():
    result = check.check_ordered(armada_game(ARMADA["factories"]["armlab"]), ARMADA, TASKS)
    assert result["matches"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["commander_frames"] == [46, 318, 598, 864, 1059]
    # two of the same unit in a row are two orders, not a repeat
    assert result["factory"][1:3] == ["armjeth", "armjeth"]


def test_check_ordered_other_factory_units():
    result = check.check_ordered(armada_game(["armck", "armflea", "armpw"]), ARMADA, TASKS)
    assert not result["matches"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["factory"] == ["armck", "armflea", "armpw"]


def test_check_ordered_without_orders():
    result = check.check_ordered([], ARMADA, TASKS)
    assert not result["matches"] and result["commander"] == []


UNIT_DEFS = {"1": "armcom", "2": "armwin", "3": "armmex", "4": "armrad", "5": "armlab"}
UNIT_DEFS |= {"6": "armrectr", "7": "armjeth", "8": "armck", "9": "armham"}
DEF_IDS = {name: int(def_id) for def_id, name in UNIT_DEFS.items()}


def state_records(builds: list[tuple[str, int, bool]], team: int = 0) -> list[dict]:
    """State file lines for units started in this order: (unit, builder id, finished?)."""
    records: list[dict] = [{"t": "header", "unitdefs": UNIT_DEFS}]
    records.append({"t": "created", "f": 0, "u": 100, "d": DEF_IDS["armcom"], "team": team})
    records.append({"t": "finished", "f": 0, "u": 100, "d": DEF_IDS["armcom"], "team": team})
    for index, (unit, builder, is_finished) in enumerate(builds):
        unit_id, frame = 200 + index, 100 * (index + 1)
        created = {"t": "created", "f": frame, "u": unit_id, "d": DEF_IDS[unit], "team": team}
        records.append(created | {"by": builder})
        if is_finished:
            finished = {"t": "finished", "f": frame + 50, "u": unit_id, "d": DEF_IDS[unit]}
            records.append(finished | {"team": team})
        else:
            records.append({"t": "destroyed", "f": frame + 3, "u": unit_id, "built": False})
    return records


COMMANDER_BUILDS = [
    (unit, 100, True) for unit in ("armwin", "armwin", "armmex", "armrad", "armlab")
]
FACTORY_ID = 204  # the armlab above


def test_check_built_matches():
    factory_builds = [(unit, FACTORY_ID, True) for unit in ARMADA["factories"]["armlab"]]
    factory_builds.insert(1, ("armrectr", FACTORY_ID, False))  # started by a re-sent order
    result = check.check_built(state_records(COMMANDER_BUILDS + factory_builds), 0, ARMADA, TASKS)
    assert result["matches"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["factory"] == ["armrectr", "armjeth", "armjeth", "armck", "armham"]
    assert result["factory_finished_frames"][0] == 650


def test_check_built_missing_unit():
    units = ("armrectr", "armjeth", "armck", "armham")
    factory_builds = [(unit, FACTORY_ID, True) for unit in units]
    result = check.check_built(state_records(COMMANDER_BUILDS + factory_builds), 0, ARMADA, TASKS)
    assert not result["matches"] and not result["in_order"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["factory"] == ["armrectr", "armjeth", "armck", "armham"]


def test_check_built_unfinished_opening():
    factory_builds = [("armrectr", FACTORY_ID, True), ("armjeth", FACTORY_ID, True)]
    result = check.check_built(state_records(COMMANDER_BUILDS + factory_builds), 0, ARMADA, TASKS)
    assert result["in_order"] and not result["matches"]
    assert result["factory"] == ["armrectr", "armjeth"]


def test_check_built_other_team():
    result = check.check_built(state_records(COMMANDER_BUILDS, team=1), 0, ARMADA, TASKS)
    assert not result["matches"] and result["commander"] == []


LOG_PREFIX = "[t=00:00:21.306333][f=-000001] "


def write_log(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "infolog.txt"
    path.write_text("".join(LOG_PREFIX + line + "\n" for line in lines), encoding="utf-8")
    return path


def test_check_infolog_clean(tmp_path):
    log = write_log(
        tmp_path,
        [
            "Skirmish AI <Reason8-0.1>: Load script: /engine/Reason8/0.1/script/hard/main.as",
            "Skirmish AI <Reason8-0.1>: Script: 'void AiLuaMessage(const string& in)' not found!",
            "Skirmish AI <Reason8-0.1>: Reason8 opening: team 0: step 1 armwin: task queued, "
            "frame 25",
            "Skirmish AI <BARbarIAn-stable>: /x/main.as (1, 1) : ERR  : not ours",
        ],
    )
    result = check.check_infolog(log, "Reason8")
    assert result["versions_loaded"] == ["0.1"]
    assert result["scripts_loaded"] == ["/engine/Reason8/0.1/script/hard/main.as"]
    assert result["opening_log_lines"] == 1
    assert result["errors"] == []


def test_check_infolog_counts_per_team(tmp_path):
    lines = [
        "team 3: side 'armada', map 'M', start 1 2: position P4 (start 1 2), 3 commander steps, "
        "1 factories",
        "team 3: step 1 armmex: BARb's extractor task, frame 30",
        "team 3: step 1: finished, frame 300",
        "team 3: step 2 armmex: skipped",
        "team 3: step 3: task failed, frame 400",
        "team 3: step 3: finished, frame 500",
        "team 3: factory unit 1: done, frame 900",
        "team 3: factory unit 2 armpw: skipped",
        "team 5: side 'armada', map 'M', start 9 9: no opening, BARb plays its own",
        "team 6: side 'armada', map 'M', start 1 2: position P2 (start 1 2), opening 3 of 5, "
        "4 commander steps, 1 factories",
    ]
    log = write_log(tmp_path, [f"Skirmish AI <Reason8-0.1>: Reason8 opening: {x}" for x in lines])
    teams = check.check_infolog(log, "Reason8")["opening_by_team"]
    assert teams[3] == {
        "position": "P4",
        "commander_steps": 3,
        "variant": 0,
        "steps_finished": 2,
        "steps_skipped": 1,
        "factory_units_done": 1,
        "factory_units_skipped": 1,
    }
    assert teams[5]["position"] is None
    assert teams[6]["position"] == "P2" and teams[6]["variant"] == 2
    assert teams[6]["commander_steps"] == 4


def test_check_infolog_compile_error(tmp_path):
    log = write_log(
        tmp_path,
        [
            "Skirmish AI <Reason8-0.1>: Load script: /engine/script/hard/main.as",
            "Skirmish AI <Reason8-0.1>: /engine/script/hard/reason8/opening.as (60, 25) : ERR  : "
            "Unexpected token '<identifier>'",
            "Skirmish AI <Reason8-0.1>: Script: Fix compilation errors!",
        ],
    )
    assert len(check.check_infolog(log, "Reason8")["errors"]) == 2


def test_check_infolog_ai_not_loaded(tmp_path):
    log = write_log(tmp_path, ["Error: [FetchSkirmishAILibrary] unknown skirmish AI   specified"])
    errors = check.check_infolog(log, "Reason8")["errors"]
    assert any("unknown skirmish AI" in error for error in errors)
    assert any("no script loaded" in error for error in errors)


def test_check_infolog_governor(tmp_path):
    prefix = "Skirmish AI <Reason8-0.1>: Reason8 governor: team 2: "
    tally = (
        "seen 5, sent at once 3, sent later 1, deferred 2, collapsed 1, dropped {dropped}, "
        "failed 0, actions 2, worst delay 9 frames, held 0"
    )
    lines = [
        "Skirmish AI <Reason8-0.1>: Load script: /engine/Reason8/0.1/script/hard/main.as",
        "Skirmish AI <Reason8-0.1>: Reason8 library: team 2: built for engine 2026.09.03, "
        "running in engine 2026.09.03",
        prefix + "mode defer, band 30-40",
        prefix + "minute 1 (part): " + tally.format(dropped=0),
        prefix + "minute 1 (part) action frames: 25 400",
        prefix + "total to frame 900: " + tally.format(dropped=0),
    ]
    result = check.check_infolog(write_log(tmp_path, lines), "Reason8")
    assert result["governor_by_team"][2]["ok"] and result["errors"] == []
    lines[-3] = prefix + "minute 1 (part): " + tally.format(dropped=1)
    lines[-1] = prefix + "total to frame 900: " + tally.format(dropped=1)
    result = check.check_infolog(write_log(tmp_path, lines), "Reason8")
    assert any("dropped" in error for error in result["errors"])


def test_replay_budget():
    class Events:
        events = [
            {"type": "cmd", "frame": 30, "team": 1, "units": [5]},
            {"type": "cmd", "frame": 30, "team": 1, "units": [6]},  # one action a frame
            {"type": "cmd", "frame": 33, "team": 1, "units": [5]},  # within its 7 frames
            {"type": "cmd", "frame": 40, "team": 1, "units": [7]},
            {"type": "cmd", "frame": 40, "team": 0, "units": [8]},  # another team
            {"type": "startpos", "frame": 0},
        ]

    result = check.replay_budget(Events(), team=1)
    assert result["commands"] == 4 and result["actions"] == 2
    assert result["windows"]["ok"] and result["windows"]["1 s"]["most"] == 2
