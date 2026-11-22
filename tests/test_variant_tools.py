"""Tests for tools/variant and the files in ai/Reason8 (no engine needed)."""

import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

from reason8.replay import BuildOrder

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "variant"))

import build  # noqa: E402
import check_opening  # noqa: E402

SOURCE = REPO_ROOT / "ai" / "Reason8"
OPENINGS = json.loads((SOURCE / "openings.json").read_text(encoding="utf-8"))
TASKS = OPENINGS["tasks"]
ARMADA = next(opening for opening in OPENINGS["openings"] if opening["side"] == "armada")


def test_ai_identity_of_our_ai():
    # the AI interface version in the same file must not be mistaken for the AI's
    assert build.ai_identity((SOURCE / "AIInfo.lua").read_text(encoding="utf-8")) == (
        "Reason8",
        "0.1",
    )


def test_ai_identity_needs_both_keys():
    with pytest.raises(SystemExit):
        build.ai_identity("return { { key = 'shortName', value = 'X' } }")


def test_opening_table_of_our_openings():
    table = build.opening_table(OPENINGS)
    assert "array<SOpening> MakeOpenings()" in table
    assert 'SOpening("armada", array<SStep> = {' in table
    assert 'SStep("armmex", Task::BuildType::MEX)' in table
    assert 'SFactoryOpening("armlab", array<string> = {"armrectr", "armjeth", "armjeth"' in table
    assert table.count("{") == table.count("}")


def test_opening_table_without_openings():
    table = build.opening_table({"openings": []})
    assert "return array<SOpening>();" in table


def test_opening_table_empty_lists():
    table = build.opening_table({"openings": [{"side": "armada"}]})
    assert 'SOpening("armada", array<SStep>(), array<SFactoryOpening>())' in table


@pytest.mark.parametrize(
    "opening",
    [
        {"side": "armada", "commander": ["armfus"]},  # no task for the unit
        {"side": "armada", "commander": ["armgeo"]},  # a task type the script cannot make
        {"side": "armada", "commander": ['armwin"); Evil(']},
        {"side": "armada", "factories": {"armlab": ["Arm Peewee"]}},
        {"side": "Not A Side"},
    ],
)
def test_opening_table_rejects_bad_input(opening):
    tasks = {"armwin": "energy", "armgeo": "geo", 'armwin"); Evil(': "energy"}
    with pytest.raises(SystemExit):
        build.opening_table({"tasks": tasks, "openings": [opening]})


def test_every_commander_structure_has_a_task():
    for opening in OPENINGS["openings"]:
        for unit in opening["commander"]:
            assert TASKS[unit] in build.TASK_TYPES


def write_rapid_package(data_dir: Path, game: str, files: dict[str, bytes]) -> None:
    """A fake installed game: rapid index, package and pool, in the engine's layout."""
    package_hash = "0123456789abcdef0123456789abcdef"
    index = b""
    for name, content in files.items():
        digest = hashlib.md5(content).digest()
        encoded_name = name.encode()
        index += bytes([len(encoded_name)]) + encoded_name + digest
        index += struct.pack(">II", 0, len(content))
        pooled = data_dir / "pool" / digest.hex()[:2] / f"{digest.hex()[2:]}.gz"
        pooled.parent.mkdir(parents=True, exist_ok=True)
        pooled.write_bytes(gzip.compress(content))
    (data_dir / "packages").mkdir(parents=True)
    (data_dir / "packages" / f"{package_hash}.sdp").write_bytes(gzip.compress(index))
    versions = data_dir / "rapid" / "host" / "byar" / "versions.gz"
    versions.parent.mkdir(parents=True)
    lines = f"byar:test,ffff,,Other Game 1\nbyar:test,{package_hash},,{game}\n"
    versions.write_bytes(gzip.compress(lines.encode()))


GAME_FILES = {
    "luarules/configs/barb/stable/script/define.as": b"// define\n",
    "luarules/configs/barb/stable/script/hard/main.as": b"// hard main\n",
    "luarules/configs/barb/stable/script/hard/manager/factory.as": b"// stock factory\n",
    "luarules/configs/barb/stable/script/easy/main.as": b"// easy main\n",
    "luarules/configs/barb/stable/config/behaviour.json": b"{}\n",
    "luarules/configs/barb/stable/config/hard/behaviour.json": b"{}\n",
    "units/armcom.lua": b"return {}\n",
}


def test_read_installed_game(tmp_path):
    write_rapid_package(tmp_path, "Some Game test-1", GAME_FILES)
    package = build.find_game_package(tmp_path, "Some Game test-1")
    game_side = build.read_package(tmp_path, package, build.GAME_SIDE_PREFIX)
    assert game_side["script/hard/main.as"] == b"// hard main\n"
    assert "units/armcom.lua" not in game_side and len(game_side) == 6
    assert sorted(build.profile_files(game_side, "hard")) == [
        "config/behaviour.json",
        "config/hard/behaviour.json",
        "script/define.as",
        "script/hard/main.as",
        "script/hard/manager/factory.as",
    ]


def test_game_not_installed(tmp_path):
    write_rapid_package(tmp_path, "Some Game test-1", GAME_FILES)
    with pytest.raises(SystemExit):
        build.find_game_package(tmp_path, "Some Game test-2")


def make_inputs(tmp_path: Path, stock_factory_hash: str) -> dict:
    """Arguments for build.assemble(): a fake engine BARb, game files and our source."""
    base_ai_dir = tmp_path / "BARb" / "stable"
    base_ai_dir.mkdir(parents=True)
    (base_ai_dir / "libSkirmishAI.so").write_bytes(b"library")
    (base_ai_dir / "AIInfo.lua").write_text("stock info")
    (base_ai_dir / "config").mkdir()
    source_dir = tmp_path / "source"
    (source_dir / "script" / "hard" / "manager").mkdir(parents=True)
    (source_dir / "AIInfo.lua").write_bytes((SOURCE / "AIInfo.lua").read_bytes())
    (source_dir / "script" / "hard" / "manager" / "factory.as").write_text("// ours\n")
    (source_dir / "openings.json").write_text(json.dumps(OPENINGS))
    replaced = {"script/hard/manager/factory.as": stock_factory_hash}
    (source_dir / "base.json").write_text(json.dumps({"replaced": replaced}))
    prefix = build.GAME_SIDE_PREFIX
    game_side = {
        name.removeprefix(prefix): content
        for name, content in GAME_FILES.items()
        if name.startswith(prefix)
    }
    return {
        "base_ai_dir": base_ai_dir,
        "game_side": game_side,
        "source_dir": source_dir,
        "profile": "hard",
    }


def test_assemble(tmp_path):
    stock_hash = hashlib.sha256(b"// stock factory\n").hexdigest()
    files, facts = build.assemble(**make_inputs(tmp_path, stock_hash))
    assert files["libSkirmishAI.so"] == b"library"
    assert files["AIInfo.lua"] == (SOURCE / "AIInfo.lua").read_bytes()  # ours, not stock
    assert files["script/hard/manager/factory.as"] == b"// ours\n"
    assert files["script/hard/main.as"] == b"// hard main\n"
    assert b"MakeOpenings" in files["script/hard/reason8/opening_table.as"]
    assert "script/easy/main.as" not in files
    assert "base.json" not in files and "openings.json" not in files
    assert facts["short_name"] == "Reason8" and facts["version"] == "0.1"
    assert facts["library"] == ["libSkirmishAI.so"]
    assert facts["replaced"] == ["script/hard/manager/factory.as"]
    assert facts["base_drift"] == []


def test_assemble_stops_when_the_stock_script_changed(tmp_path):
    inputs = make_inputs(tmp_path, "0" * 64)
    with pytest.raises(SystemExit, match="factory.as"):
        build.assemble(**inputs)
    _, facts = build.assemble(**inputs, allow_base_drift=True)
    assert facts["base_drift"] == ["script/hard/manager/factory.as"]


def test_assemble_unknown_profile(tmp_path):
    inputs = make_inputs(tmp_path, "0" * 64) | {"profile": "medium"}
    with pytest.raises(SystemExit, match="medium"):
        build.assemble(**inputs)


def test_replaced_scripts_are_listed_with_their_base():
    base = json.loads((SOURCE / "base.json").read_text(encoding="utf-8"))
    for name, digest in base["replaced"].items():
        assert (SOURCE / name).is_file()
        assert len(digest) == 64
        assert "Reason8:" in (SOURCE / name).read_text(encoding="utf-8")


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
    result = check_opening.check_ordered(armada_game(ARMADA["factories"]["armlab"]), ARMADA, TASKS)
    assert result["matches"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["commander_frames"] == [46, 318, 598, 864, 1059]
    # two of the same unit in a row are two orders, not a repeat
    assert result["factory"][1:3] == ["armjeth", "armjeth"]


def test_check_ordered_other_factory_units():
    result = check_opening.check_ordered(armada_game(["armck", "armflea", "armpw"]), ARMADA, TASKS)
    assert not result["matches"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["factory"] == ["armck", "armflea", "armpw"]


def test_check_ordered_without_orders():
    result = check_opening.check_ordered([], ARMADA, TASKS)
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
    result = check_opening.check_built(
        state_records(COMMANDER_BUILDS + factory_builds), 0, ARMADA, TASKS
    )
    assert result["matches"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["factory"] == ["armrectr", "armjeth", "armjeth", "armck", "armham"]
    assert result["factory_finished_frames"][0] == 650


def test_check_built_missing_unit():
    units = ("armrectr", "armjeth", "armck", "armham")
    factory_builds = [(unit, FACTORY_ID, True) for unit in units]
    result = check_opening.check_built(
        state_records(COMMANDER_BUILDS + factory_builds), 0, ARMADA, TASKS
    )
    assert not result["matches"] and not result["in_order"]
    assert result["commander"] == ["armwin", "armwin", "armmex", "armrad", "armlab"]
    assert result["factory"] == ["armrectr", "armjeth", "armck", "armham"]


def test_check_built_unfinished_opening():
    factory_builds = [("armrectr", FACTORY_ID, True), ("armjeth", FACTORY_ID, True)]
    result = check_opening.check_built(
        state_records(COMMANDER_BUILDS + factory_builds), 0, ARMADA, TASKS
    )
    assert result["in_order"] and not result["matches"]
    assert result["factory"] == ["armrectr", "armjeth"]


def test_check_built_other_team():
    result = check_opening.check_built(state_records(COMMANDER_BUILDS, team=1), 0, ARMADA, TASKS)
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
            "Skirmish AI <Reason8-0.1>: Reason8 opening: step 1 armwin: task queued, frame 25",
            "Skirmish AI <BARbarIAn-stable>: /x/main.as (1, 1) : ERR  : not ours",
        ],
    )
    result = check_opening.check_infolog(log, "Reason8")
    assert result["versions_loaded"] == ["0.1"]
    assert result["scripts_loaded"] == ["/engine/Reason8/0.1/script/hard/main.as"]
    assert result["opening_log_lines"] == 1
    assert result["errors"] == []


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
    assert len(check_opening.check_infolog(log, "Reason8")["errors"]) == 2


def test_check_infolog_ai_not_loaded(tmp_path):
    log = write_log(tmp_path, ["Error: [FetchSkirmishAILibrary] unknown skirmish AI   specified"])
    errors = check_opening.check_infolog(log, "Reason8")["errors"]
    assert any("unknown skirmish AI" in error for error in errors)
    assert any("no script loaded" in error for error in errors)
