"""Build the Reason8 in-game AI: BARb under its own short name, with our library and openings.

    # a copy of the engine with Reason8 installed, for headless runs (--engine-dir)
    uv run reason8 bot build --data-dir data/bar \\
        --game "Beyond All Reason test-32018-ad135b9" \\
        --engine-copy data/bar/engine-variants/reason8
    # only the AI folder, to install into an existing AI/Skirmish folder
    uv run reason8 bot build --data-dir data/bar --game "..." \\
        --skirmish-dir "<BAR install>/data/engine/<engine>/AI/Skirmish"

The AI folder <shortName>/<version>/ is put together from four sources:

  1. the engine's own BARb (AI/Skirmish/BARb/stable): its library and the
     files that come with it;
  2. our build of BARb's library in place of the engine's (--library,
     `reason8.bot.library`): BARb with the command governor of ADR 0008 and
     the live state the scripts read. It is built for the engine's tag and
     platform (Linux, or Windows when the engine's BARb has SkirmishAI.dll)
     with ai/native/build.sh, which runs on Linux x86-64; `--library stock`
     keeps the engine's library;
  3. the game's BARb scripts and configs (luarules/configs/BARb/stable in the
     game archive), for one profile;
  4. this repo's ai/Reason8: AIInfo.lua (short name and version),
     AIOptions.lua, the scripts we changed or added, and openings.json, which
     is turned into the AngelScript table script/<profile>/reason8/opening_table.as.
     script/<profile>/reason8/live_state.as is generated for the library: it
     reads the live state from ours, and says "unknown" (-1) with the stock one.

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
import hashlib
import json
import re
import shutil
from pathlib import Path

from reason8.bot import library as native
from reason8.game.package import find_game_package, read_package
from reason8.headless.run import find_engine
from reason8.paths import REPO_ROOT

DEFAULT_SOURCE = REPO_ROOT / "ai" / "Reason8"
BASE_AI = Path("AI") / "Skirmish" / "BARb" / "stable"
GAME_SIDE_PREFIX = "luarules/configs/barb/stable/"
OPENINGS_NAME = "openings.json"
BASE_NAME = "base.json"
MANIFEST_NAME = "reason8_build.json"
OPENING_TABLE = "reason8/opening_table.as"
LIVE_STATE = "reason8/live_state.as"
LIMITS_ONLY_NAME = "BARbLimited"
HEADLESS_NAMES = ("spring-headless", "spring-headless.exe")  # Linux, Windows

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
MAP_TEXT = re.compile(r"^[A-Za-z0-9 ._()\-]*$")  # map and position names, quoted as they are


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
    """openings.json as the AngelScript function Reason8::MakeOpenings().

    Each opening's steps and factory units are one string each (``unit TYPE x z;...`` and
    ``factory:unit,unit;...``), decoded by ``opening.as`` only for the opening it plays:
    an AI with hundreds of openings as nested AngelScript arrays took minutes to compile.
    """

    def check_unit(name: object) -> str:
        if not isinstance(name, str) or not UNIT_NAME.match(name):
            raise SystemExit(f"{OPENINGS_NAME}: bad unit name {name!r}")
        return name

    tasks = openings.get("tasks", {})
    entries = []
    for opening in openings.get("openings", []):
        side = opening.get("side")
        if not isinstance(side, str) or not UNIT_NAME.match(side):
            raise SystemExit(f"{OPENINGS_NAME}: bad side {side!r}")
        steps = []
        places = opening.get("places") or []
        for index, unit in enumerate(opening.get("commander", [])):
            task = tasks.get(check_unit(unit))
            if task not in TASK_TYPES:
                known = ", ".join(sorted(TASK_TYPES))
                raise SystemExit(
                    f'{OPENINGS_NAME}: "tasks" has {task!r} for {unit} (known: {known})'
                )
            place = places[index] if index < len(places) and places[index] else (-1, -1)
            steps.append(f"{unit} {TASK_TYPES[task]} {round(place[0])} {round(place[1])}")
        factories = [
            f"{check_unit(factory)}:" + ",".join(check_unit(unit) for unit in units)
            for factory, units in opening.get("factories", {}).items()
        ]
        map_name = opening.get("map", "")
        position = opening.get("position", "")
        for text in (map_name, position):
            if not isinstance(text, str) or not MAP_TEXT.match(text):
                raise SystemExit(f"{OPENINGS_NAME}: bad map or position {text!r}")
        start_x, start_z = opening.get("start", (0, 0))
        entries.append(
            f'SOpening("{side}", "{map_name}", "{position}", {float(start_x)}f, '
            f'{float(start_z)}f, "{";".join(steps)}", "{";".join(factories)}")'
        )
    reaction_rows = [
        f'"{kind} {row["until_seconds"]} {row["answered"]} '
        + " ".join(str(value) for value in row["quantiles"])
        + '"'
        for kind, rows in sorted((openings.get("reactions") or {}).items())
        for row in rows
        if kind.isalpha()
    ]
    reactions = (
        "const array<string> REACTIONS = {"
        + ",".join(f"\n\t{row}" for row in reaction_rows)
        + "\n};\n"
        if reaction_rows
        else "const array<string> REACTIONS;\n"
    )
    batch_rows = [
        f'"{kind} {float(size)}"'
        for kind, size in sorted((openings.get("batches") or {}).items())
        if kind.isalpha()
    ]
    batches = (
        "const array<string> BATCHES = {" + ",".join(f"\n\t{row}" for row in batch_rows) + "\n};\n"
        if batch_rows
        else "const array<string> BATCHES;\n"
    )
    body = "".join(f"\n\t\t{entry}," for entry in entries).rstrip(",")
    openings_array = f"array<SOpening> = {{{body}\n\t}}" if entries else "array<SOpening>()"
    return (
        f"// Generated by `reason8 bot build` from ai/Reason8/{OPENINGS_NAME}. Do not edit.\n"
        "\n"
        "namespace Reason8 {\n"
        "\n"
        '// Reaction delays: "<kind> <until second> <answered> <quantiles of seconds>".\n'
        + reactions
        + '// Units started between two looks: "<kind> <mean>".\n'
        + batches
        + "\n"
        "array<SOpening> MakeOpenings()\n"
        "{\n"
        f"\treturn {openings_array};\n"
        "}\n"
        "\n"
        "}  // namespace Reason8\n"
    )


def live_state_script(available: bool) -> str:
    """script/<profile>/reason8/live_state.as: the live state as the scripts read it.

    With our library the functions read the engine through the library's bindings
    (``ai/native/LiveState.h``); with the stock library, which has none, they say "unknown",
    so that the same scripts compile with either.
    """
    header = "// Generated by `reason8 bot build` for the library it installed. Do not edit.\n\n"
    if available:
        body = (
            "const bool LIVE_STATE = true;\n"
            "float CurrentWind() { return Reason8CurrentWind(); }\n"
            "float Resource(const string& in resource, const string& in what)\n"
            "{ return Reason8Resource(resource, what); }\n"
            "int UnitCount(const string& in unitName) { return Reason8UnitCount(unitName); }\n"
            "string Standing() { return Reason8Standing(); }\n"
            "int FirstContactFrame() { return Reason8FirstContactFrame(); }\n"
            "string FirstContact() { return Reason8FirstContact(); }\n"
        )
    else:
        body = (
            "const bool LIVE_STATE = false;  // the engine's own library has no live state\n"
            "float CurrentWind() { return -1.f; }\n"
            "float Resource(const string& in, const string& in) { return -1.f; }\n"
            "int UnitCount(const string& in) { return -1; }\n"
            'string Standing() { return ""; }\n'
            "int FirstContactFrame() { return -1; }  // never: no contact without our library\n"
            'string FirstContact() { return ""; }\n'
        )
    return header + "namespace Reason8 {\n\n" + body + "\n}  // namespace Reason8\n"


def set_short_name(ai_info: str, short_name: str) -> str:
    """AIInfo.lua with another short name."""
    if not UNIT_NAME.match(short_name.lower()):
        raise SystemExit(f"bad short name {short_name!r}")
    return re.sub(
        r"(key\s*=\s*'shortName'\s*,\s*value\s*=\s*')[^']+'",
        rf"\g<1>{short_name}'",
        ai_info,
    )


def assemble(
    *,
    base_ai_dir: Path,
    game_side: dict[str, bytes],
    source_dir: Path,
    profile: str,
    allow_base_drift: bool = False,
    limits_only: bool = False,
    library: native.Library | None = None,
    short_name: str | None = None,
) -> tuple[dict[str, bytes], dict]:
    """(files of the AI folder by relative path, facts about the build).

    With `limits_only` the AI is stock BARb's decisions under Reason8's human-like limits
    (ADR 0008) and no openings, installed under the short name `LIMITS_ONLY_NAME`: the fair
    opponent for Reason8 (ADR 0003). `library` replaces the engine's library (None keeps
    it); `short_name` installs the AI under another name.
    """
    files: dict[str, bytes] = {}

    # 1. the engine's BARb: everything but its own identity, configs and scripts
    for path in sorted(base_ai_dir.iterdir()):
        if path.is_file() and path.name not in ("AIInfo.lua", "AIOptions.lua"):
            files[path.name] = path.read_bytes()
    library_files = sorted(files)
    if not library_files:
        raise SystemExit(f"no AI library in {base_ai_dir}")
    if library is not None and library.path is not None:
        name = native.LIBRARY_NAMES[library.platform]
        if name not in files:
            raise SystemExit(f"{base_ai_dir} has no {name} to replace")
        files[name] = library.path.read_bytes()

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
    if limits_only:
        openings = {**openings, "openings": []}
        short_name = short_name or LIMITS_ONLY_NAME
    if short_name:
        files["AIInfo.lua"] = set_short_name(
            files["AIInfo.lua"].decode("utf-8"), short_name
        ).encode("utf-8")
    files[f"script/{profile}/{OPENING_TABLE}"] = opening_table(openings).encode("utf-8")
    live_state = library is not None and library.live_state
    files[f"script/{profile}/{LIVE_STATE}"] = live_state_script(live_state).encode("utf-8")

    short_name, version = ai_identity(files["AIInfo.lua"].decode("utf-8"))
    facts = {
        "short_name": short_name,
        "version": version,
        "profile": profile,
        "library": library.facts if library is not None else {"source": native.STOCK},
        "engine_files": library_files,
        "stock_files": len(stock),
        "replaced": replaced,
        "base_drift": drifted,
        "openings": len(openings.get("openings", [])),
        "limits_only": limits_only,
        "openings_sha256": sha256((source_dir / OPENINGS_NAME).read_bytes()),
    }
    return files, facts


def build(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data_dir).resolve()
    engine_dir = find_engine(data_dir, args.engine)
    package = find_game_package(data_dir, args.game)
    library = native.find_library(
        args.library,
        engine_dir,
        cache_dir=Path(args.library_cache).resolve() if args.library_cache else None,
        engine_commit=args.engine_commit,
    )
    files, facts = assemble(
        base_ai_dir=engine_dir / BASE_AI,
        game_side=read_package(data_dir, package, GAME_SIDE_PREFIX),
        source_dir=Path(args.source).resolve(),
        profile=args.profile,
        allow_base_drift=args.allow_base_drift,
        limits_only=args.limits_only,
        library=library,
        short_name=args.short_name,
    )
    facts = {"engine": engine_dir.name, "game": args.game, **facts}

    if args.engine_copy:
        engine_copy = Path(args.engine_copy).resolve()
        if not any((engine_copy / name).is_file() for name in HEADLESS_NAMES):
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


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir", required=True, help="content dir: engine/ pool/ packages/ rapid/"
    )
    parser.add_argument("--game", required=True, help="installed game version, by name")
    parser.add_argument("--engine", help="engine version (default: the newest)")
    parser.add_argument("--profile", default="hard", help="BARb profile to build on")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="our AI files")
    parser.add_argument(
        "--limits-only",
        action="store_true",
        help=f"build {LIMITS_ONLY_NAME}: BARb's decisions under Reason8's limits, no openings",
    )
    parser.add_argument(
        "--library",
        default=native.BUILD,
        help="BARb's library: 'build' (ours, built or taken from the cache for the engine's "
        "tag and platform, Linux or Windows), 'stock' (the engine's own) or the folder of a "
        "build.sh build (or the library in it)",
    )
    parser.add_argument(
        "--library-cache", help="where 'build' keeps its builds (default: <data dir>/native)"
    )
    parser.add_argument(
        "--engine-commit",
        help="commit of the engine's tag, for an engine build.sh has no commit for",
    )
    parser.add_argument("--short-name", help="install the AI under this short name")
    parser.add_argument(
        "--allow-base-drift",
        action="store_true",
        help="build even when the game's BARb scripts differ from the ones ours replace",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--engine-copy", help="copy the engine here (once) and install the AI into the copy"
    )
    target.add_argument("--skirmish-dir", help="an AI/Skirmish folder to install the AI into")


def run(args: argparse.Namespace) -> int:
    print(json.dumps(build(args), indent=1))
    return 0
