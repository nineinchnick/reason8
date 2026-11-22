#!/usr/bin/env python3
"""Build the Reason8 in-game AI: stock BARb under its own short name, with our openings.

    # a copy of the engine with Reason8 installed, for headless runs (--engine-dir)
    python tools/variant/build.py --data-dir data/bar \\
        --game "Beyond All Reason test-32018-ad135b9" \\
        --engine-copy data/bar/engine-variants/reason8
    # only the AI folder, to install into an existing AI/Skirmish folder
    python tools/variant/build.py --data-dir data/bar --game "..." \\
        --skirmish-dir "<BAR install>/data/engine/<engine>/AI/Skirmish"

The AI folder <shortName>/<version>/ is put together from three sources:

  1. the engine's own BARb (AI/Skirmish/BARb/stable): the library, unchanged,
     so it always matches the engine it is installed into;
  2. the game's BARb scripts and configs (luarules/configs/BARb/stable in the
     game archive), for one profile;
  3. this repo's ai/Reason8: AIInfo.lua (short name and version),
     AIOptions.lua, the scripts we changed or added, and openings.json, which
     is turned into the AngelScript table script/<profile>/reason8/opening_table.as.

A script of ours that replaces a BARb script was made from one version of that
script; ai/Reason8/base.json records its SHA-256. When the game's file differs
the build stops (--allow-base-drift builds anyway), because our copy would
silently drop the game's changes.

Nothing in the shared engine folder is changed. Prints one JSON object that
says what was built from what; the same is written next to the library as
reason8_build.json.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "headless"))
import run  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "ai" / "Reason8"
BASE_AI = Path("AI") / "Skirmish" / "BARb" / "stable"
GAME_SIDE_PREFIX = "luarules/configs/barb/stable/"
OPENINGS_NAME = "openings.json"
BASE_NAME = "base.json"
MANIFEST_NAME = "reason8_build.json"
OPENING_TABLE = "reason8/opening_table.as"

# openings.json "tasks" values -> BARb's Task::BuildType (script/task.as). Types that
# need more than a unit and a position (geothermal spots, pylons) are left out.
TASK_TYPES = {
    "factory": "FACTORY",
    "nano": "NANO",
    "store": "STORE",
    "energy": "ENERGY",
    "defence": "DEFENCE",
    "radar": "RADAR",
    "sonar": "SONAR",
    "convert": "CONVERT",
    "mex": "MEX",
}
UNIT_NAME = re.compile(r"^[a-z0-9_]+$")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ai_identity(ai_info: str) -> tuple[str, str]:
    """(short name, version) from the text of an AIInfo.lua."""
    values = {}
    for key in ("shortName", "version"):
        match = re.search(rf"key\s*=\s*'{key}'\s*,\s*value\s*=\s*'([^']+)'", ai_info)
        if not match:
            raise SystemExit(f"AIInfo.lua has no '{key}'")
        values[key] = match.group(1)
    return values["shortName"], values["version"]


def find_game_package(data_dir: Path, game: str) -> Path:
    """The rapid package (.sdp) of an installed game version, looked up by its name."""
    for versions in sorted(data_dir.glob("rapid/*/*/versions.gz")):
        with gzip.open(versions, "rt", encoding="utf-8") as file:
            for line in file:
                # tag, package hash, dependencies, name
                fields = line.rstrip("\n").split(",", 3)
                if len(fields) == 4 and fields[3] == game:
                    package = data_dir / "packages" / f"{fields[1]}.sdp"
                    if package.is_file():
                        return package
    raise SystemExit(f"game {game!r} is not installed under {data_dir} (tools/headless/setup.py)")


def read_package(data_dir: Path, package: Path, prefix: str) -> dict[str, bytes]:
    """Files of a rapid package under `prefix` (compared in lower case), keyed by the rest
    of their path.

    A package is a gzipped list of entries: name length (1 byte), name, MD5 (16),
    CRC32 (4), size (4). The content is in pool/<first two hex digits>/<the rest>.gz.
    """
    index = gzip.decompress(package.read_bytes())
    files: dict[str, bytes] = {}
    offset = 0
    while offset < len(index):
        name_length = index[offset]
        name = index[offset + 1 : offset + 1 + name_length].decode("utf-8")
        digest = index[offset + 1 + name_length : offset + 17 + name_length].hex()
        offset += 1 + name_length + 16 + 4 + 4
        if name.lower().startswith(prefix):
            pooled = data_dir / "pool" / digest[:2] / f"{digest[2:]}.gz"
            files[name[len(prefix) :]] = gzip.decompress(pooled.read_bytes())
    return files


def profile_files(game_side: dict[str, bytes], profile: str) -> dict[str, bytes]:
    """The shared files and one profile's files out of the game's BARb folder."""
    kept = {}
    for name, content in game_side.items():
        parts = name.split("/")
        if parts[0] not in ("config", "script"):
            continue
        if len(parts) == 2 or parts[1] == profile:
            kept[name] = content
    return kept


def opening_table(openings: dict) -> str:
    """openings.json as the AngelScript function Reason8::MakeOpenings()."""

    def check_unit(name: object) -> str:
        if not isinstance(name, str) or not UNIT_NAME.match(name):
            raise SystemExit(f"{OPENINGS_NAME}: bad unit name {name!r}")
        return name

    def array(element_type: str, items: list[str], indent: str) -> str:
        if not items:
            return f"array<{element_type}>()"
        body = "".join(f"\n{indent}\t{item}," for item in items).rstrip(",")
        return f"array<{element_type}> = {{{body}\n{indent}}}"

    tasks = openings.get("tasks", {})
    entries = []
    for opening in openings.get("openings", []):
        side = opening.get("side")
        if not isinstance(side, str) or not UNIT_NAME.match(side):
            raise SystemExit(f"{OPENINGS_NAME}: bad side {side!r}")
        steps = []
        for unit in opening.get("commander", []):
            task = tasks.get(check_unit(unit))
            if task not in TASK_TYPES:
                known = ", ".join(sorted(TASK_TYPES))
                raise SystemExit(
                    f'{OPENINGS_NAME}: "tasks" has {task!r} for {unit} (known: {known})'
                )
            steps.append(f'SStep("{unit}", Task::BuildType::{TASK_TYPES[task]})')
        factories = []
        for factory, units in opening.get("factories", {}).items():
            names = ", ".join(f'"{check_unit(unit)}"' for unit in units)
            unit_list = f"array<string> = {{{names}}}" if units else "array<string>()"
            factories.append(f'SFactoryOpening("{check_unit(factory)}", {unit_list})')
        entries.append(
            f'SOpening("{side}", {array("SStep", steps, "\t\t")}, '
            f"{array('SFactoryOpening', factories, '\t\t')})"
        )
    return (
        f"// Generated by tools/variant/build.py from ai/Reason8/{OPENINGS_NAME}. Do not edit.\n"
        "\n"
        "namespace Reason8 {\n"
        "\n"
        "array<SOpening> MakeOpenings()\n"
        "{\n"
        f"\treturn {array('SOpening', entries, '\t')};\n"
        "}\n"
        "\n"
        "}  // namespace Reason8\n"
    )


def assemble(
    *,
    base_ai_dir: Path,
    game_side: dict[str, bytes],
    source_dir: Path,
    profile: str,
    allow_base_drift: bool = False,
) -> tuple[dict[str, bytes], dict]:
    """(files of the AI folder by relative path, facts about the build)."""
    files: dict[str, bytes] = {}

    # 1. the engine's BARb: everything but its own identity, configs and scripts
    for path in sorted(base_ai_dir.iterdir()):
        if path.is_file() and path.name not in ("AIInfo.lua", "AIOptions.lua"):
            files[path.name] = path.read_bytes()
    library = sorted(files)
    if not library:
        raise SystemExit(f"no AI library in {base_ai_dir}")

    # 2. the game's BARb scripts and configs for the profile
    stock = profile_files(game_side, profile)
    if f"script/{profile}/main.as" not in stock:
        raise SystemExit(f"the game has no BARb profile {profile!r}")
    files.update(stock)

    # 3. ours on top
    base = json.loads((source_dir / BASE_NAME).read_text(encoding="utf-8"))
    replaced, drifted = [], []
    for path in sorted(source_dir.rglob("*")):
        name = path.relative_to(source_dir).as_posix()
        if not path.is_file() or name in (BASE_NAME, OPENINGS_NAME):
            continue
        if name in stock:
            replaced.append(name)
            expected = base.get("replaced", {}).get(name)
            if expected != sha256(stock[name]):
                drifted.append(name)
        files[name] = path.read_bytes()
    if drifted and not allow_base_drift:
        raise SystemExit(
            "the game's BARb changed these files since our copies were made: "
            + ", ".join(drifted)
            + f". Carry the changes over and update {BASE_NAME} (or pass --allow-base-drift)."
        )
    openings = json.loads((source_dir / OPENINGS_NAME).read_text(encoding="utf-8"))
    files[f"script/{profile}/{OPENING_TABLE}"] = opening_table(openings).encode("utf-8")

    short_name, version = ai_identity(files["AIInfo.lua"].decode("utf-8"))
    facts = {
        "short_name": short_name,
        "version": version,
        "profile": profile,
        "library": library,
        "stock_files": len(stock),
        "replaced": replaced,
        "base_drift": drifted,
        "openings": [opening["side"] for opening in openings.get("openings", [])],
        "openings_sha256": sha256((source_dir / OPENINGS_NAME).read_bytes()),
    }
    return files, facts


def build(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data_dir).resolve()
    engine_dir = run.find_engine(data_dir, args.engine)
    package = find_game_package(data_dir, args.game)
    files, facts = assemble(
        base_ai_dir=engine_dir / BASE_AI,
        game_side=read_package(data_dir, package, GAME_SIDE_PREFIX),
        source_dir=Path(args.source).resolve(),
        profile=args.profile,
        allow_base_drift=args.allow_base_drift,
    )
    facts = {"engine": engine_dir.name, "game": args.game, **facts}

    if args.engine_copy:
        engine_copy = Path(args.engine_copy).resolve()
        if not (engine_copy / "spring-headless").is_file():
            shutil.copytree(engine_dir, engine_copy, symlinks=True, dirs_exist_ok=True)
        skirmish_dir = engine_copy / "AI" / "Skirmish"
        facts["engine_dir"] = str(engine_copy)
    else:
        skirmish_dir = Path(args.skirmish_dir).resolve()
    ai_dir = skirmish_dir / facts["short_name"] / facts["version"]
    if ai_dir.exists():
        shutil.rmtree(ai_dir)
    files[MANIFEST_NAME] = (json.dumps(facts, indent=1) + "\n").encode("utf-8")
    for name, content in files.items():
        path = ai_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    facts["ai_dir"] = str(ai_dir)
    return facts


def parse_args(argv: list[str]) -> argparse.Namespace:
    argument_parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    argument_parser.add_argument(
        "--data-dir", required=True, help="content dir: engine/ pool/ packages/ rapid/"
    )
    argument_parser.add_argument("--game", required=True, help="installed game version, by name")
    argument_parser.add_argument("--engine", help="engine version (default: the newest)")
    argument_parser.add_argument("--profile", default="hard", help="BARb profile to build on")
    argument_parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="our AI files")
    argument_parser.add_argument(
        "--allow-base-drift",
        action="store_true",
        help="build even when the game's BARb scripts differ from the ones ours replace",
    )
    target = argument_parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--engine-copy", help="copy the engine here (once) and install the AI into the copy"
    )
    target.add_argument("--skirmish-dir", help="an AI/Skirmish folder to install the AI into")
    return argument_parser.parse_args(argv)


def main(argv: list[str]) -> int:
    print(json.dumps(build(parse_args(argv)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
