"""Tests for `reason8 bot build` and the files in ai/Reason8 (no engine needed)."""

import gzip
import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

from reason8.bot import build
from reason8.bot import library as native
from reason8.game import package as game_package
from reason8.paths import REPO_ROOT

SOURCE = REPO_ROOT / "ai" / "Reason8"
# Openings no human or stock BARb would play, so a game shows whether they were played.
OPENINGS = json.loads(
    (REPO_ROOT / "tests" / "fixtures" / "bot" / "unusual_openings.json").read_text(encoding="utf-8")
)
EXPORTED = json.loads((SOURCE / "openings.json").read_text(encoding="utf-8"))
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
    assert (
        'SOpening("armada", "", "", 0.0f, 0.0f, "armwin ENERGY -1 -1;armwin ENERGY -1 -1;' in table
    )
    assert "armmex MEX -1 -1;" in table
    assert '"armlab:armrectr,armjeth,armjeth,armck,armham")' in table
    assert table.count("{") == table.count("}")


def test_opening_table_without_openings():
    table = build.opening_table({"openings": []})
    assert "return array<SOpening>();" in table


def test_opening_table_empty_lists():
    table = build.opening_table({"openings": [{"side": "armada"}]})
    assert 'SOpening("armada", "", "", 0.0f, 0.0f, "", "")' in table


def test_opening_table_with_map_and_position():
    opening = {"side": "cortex", "map": "Supreme Isthmus v2.1", "position": "P4", "start": [1, 2]}
    table = build.opening_table({"openings": [opening]})
    assert 'SOpening("cortex", "Supreme Isthmus v2.1", "P4", 1.0f, 2.0f, "", "")' in table


@pytest.mark.parametrize(
    "opening",
    [
        {"side": "armada", "commander": ["armfus"]},  # no task for the unit
        {"side": "armada", "commander": ["armgeo"]},  # a task type the script cannot make
        {"side": "armada", "commander": ['armwin"); Evil(']},
        {"side": "armada", "factories": {"armlab": ["Arm Peewee"]}},
        {"side": "Not A Side"},
        {"side": "armada", "map": 'Map"); Evil('},
    ],
)
def test_opening_table_rejects_bad_input(opening):
    tasks = {"armwin": "energy", "armgeo": "geo", 'armwin"); Evil(': "energy"}
    with pytest.raises(SystemExit):
        build.opening_table({"tasks": tasks, "openings": [opening]})


def test_every_commander_structure_has_a_task():
    for openings in (OPENINGS, EXPORTED):
        for opening in openings["openings"]:
            for unit in opening["commander"]:
                assert openings["tasks"][unit] in build.TASK_TYPES


def test_exported_openings_build():
    table = build.opening_table(EXPORTED)
    assert table.count("SOpening(") == len(EXPORTED["openings"]) > 0
    for opening in EXPORTED["openings"]:
        assert opening["side"] in ("armada", "cortex") and opening["map"] and opening["position"]
        # the first factory is the commander's and its units are listed for it
        assert set(opening["factories"]) <= set(opening["commander"])


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
    package = game_package.find_game_package(tmp_path, "Some Game test-1")
    game_side = game_package.read_package(tmp_path, package, build.GAME_SIDE_PREFIX)
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
        game_package.find_game_package(tmp_path, "Some Game test-2")


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
    assert facts["library"] == {"source": "stock"}
    assert facts["engine_files"] == ["libSkirmishAI.so"]
    live_state = files["script/hard/reason8/live_state.as"].decode()
    assert "const bool LIVE_STATE = false;" in live_state
    assert "Reason8CurrentWind" not in live_state  # the stock library has no such binding
    assert facts["replaced"] == ["script/hard/manager/factory.as"]
    assert facts["base_drift"] == []


def test_assemble_limits_only(tmp_path):
    stock_hash = hashlib.sha256(b"// stock factory\n").hexdigest()
    files, facts = build.assemble(**make_inputs(tmp_path, stock_hash), limits_only=True)
    assert facts["short_name"] == build.LIMITS_ONLY_NAME and facts["openings"] == 0
    assert facts["limits_only"]
    assert b"array<SOpening>()" in files["script/hard/reason8/opening_table.as"]


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


def test_opening_table_with_reactions():
    reactions = {"builder": [{"until_seconds": 180, "answered": 0.9, "quantiles": [1.0, 2.5]}]}
    table = build.opening_table({"openings": [], "reactions": reactions})
    assert '\t"builder 180 0.9 1.0 2.5"\n};' in table
    assert "const array<string> REACTIONS;" in build.opening_table({"openings": []})


def test_assemble_with_our_library(tmp_path):
    stock_hash = hashlib.sha256(b"// stock factory\n").hexdigest()
    ours = tmp_path / "ours.so"
    ours.write_bytes(b"our library")
    library = native.Library(ours, {"source": "build", "engine_tag": "2026.09.03"})
    files, facts = build.assemble(**make_inputs(tmp_path, stock_hash), library=library)
    assert files["libSkirmishAI.so"] == b"our library"
    assert facts["library"]["source"] == "build"
    live_state = files["script/hard/reason8/live_state.as"].decode()
    assert "const bool LIVE_STATE = true;" in live_state
    for binding in ("Reason8CurrentWind", "Reason8Resource", "Reason8UnitCount", "Reason8Standing"):
        assert binding + "(" in live_state


def test_live_state_scripts_declare_the_same_functions():
    def declarations(script: str) -> list[str]:
        return re.findall(r"^((?:float|int|string) \w+)\(", script, re.M)

    ours = build.live_state_script(True)
    stock = build.live_state_script(False)
    assert ours.count("{") == ours.count("}") and stock.count("{") == stock.count("}")
    assert declarations(ours) == declarations(stock) and len(declarations(ours)) == 4


def test_assemble_under_another_short_name(tmp_path):
    stock_hash = hashlib.sha256(b"// stock factory\n").hexdigest()
    files, facts = build.assemble(**make_inputs(tmp_path, stock_hash), short_name="Reason8Stock")
    assert facts["short_name"] == "Reason8Stock" and facts["openings"] > 0
    with pytest.raises(SystemExit):
        build.set_short_name("x", "Not a name")
