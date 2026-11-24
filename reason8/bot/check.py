"""Check from a replay that an AI played the opening it was built with.

    uv run reason8 bot check RUN/demos/GAME.sdfz \\
        --infolog RUN/infolog.txt [--state STATE.jsonl]

Every team played by the AI (--ai, by short name) is compared with its opening
in ai/Reason8/openings.json, in up to three ways:

Ordered (always): the replay is parsed with reason8.replays.parse. The commander
  is the builder of the team's first build order, and the first factory is the
  second builder to give one. The commander's first orders must be the
  opening's commander steps, and the factory's first orders the opening's
  units for that factory, in order. A commander order repeated for the same
  unit at the same place is counted once, because BARb re-sends orders.

Built (--state): the state file comes from playing the replay again with
  `reason8 headless run --snapshots`. It tells what was really built: the
  units the commander and the first factory started that were also finished.
  An order is only an intention, and a re-sent factory order cannot be told
  from a second unit of the same type, so when the state is given it decides.
  "in_order" without "matches" means the opening was followed but not finished
  before the state file ends.

Log (--infolog): whether the AI loaded, which version and scripts, and script
  errors. An AI that fails to load or compile does not stop the game: its team
  stands still.

Prints one JSON object. The exit code is non-zero when a team did not play its
opening, no team was played by the AI, or the log shows the AI did not load
cleanly.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from reason8.headless.state import read_records
from reason8.paths import REPO_ROOT
from reason8.replays.parse import default_parser, parse_replay
from reason8.replays.replay import BuildOrder, Replay

DEFAULT_OPENINGS = REPO_ROOT / "ai" / "Reason8" / "openings.json"

# What CircuitAI logs when an AngelScript file fails to load, compile or run
SCRIPT_ERRORS = (
    "Script: Fix compilation errors!",
    "Script: Unable to add section!",
    "Script: Unrecoverable error",
    " : ERR ",
    "Exception:",
    "is missing!",
)
# What the engine logs when it cannot load the AI at all. The game still runs,
# and the AI's team stands still.
ENGINE_ERRORS = ("[FetchSkirmishAILibrary]", "[StoreSkirmishAILibInfo]")


def expected_builds(opening: dict, tasks: dict) -> tuple[list[str], str | None, list[str]]:
    """(commander's structures, name of the first factory, that factory's units).

    `tasks` is the openings file's map from a unit to the BARb task that builds it.
    """
    structures = opening.get("commander", [])
    factory_name = next((unit for unit in structures if tasks.get(unit) == "factory"), None)
    factory_units = opening.get("factories", {}).get(factory_name, [])
    return structures, factory_name, factory_units


def distinct_orders(orders: list[BuildOrder]) -> list[BuildOrder]:
    """Structure orders without the repeats of the same unit at the same place.

    Not for factory orders: an AI's factory orders all carry the factory's own
    position, so two units of one type in a row would look like a repeat.
    """
    seen: set[tuple[str | None, float | None, float | None]] = set()
    distinct = []
    for order in orders:
        key = (order.unit, order.x, order.z)
        if key not in seen:
            seen.add(key)
            distinct.append(order)
    return distinct


def orders_by_builder(orders: list[BuildOrder]) -> dict[tuple[int, ...], list[BuildOrder]]:
    """Build orders grouped by who was told to build, in order of first appearance."""
    grouped: dict[tuple[int, ...], list[BuildOrder]] = {}
    for order in orders:
        if order.builders:
            grouped.setdefault(order.builders, []).append(order)
    return grouped


def check_ordered(orders: list[BuildOrder], opening: dict, tasks: dict) -> dict:
    """Compare one team's build orders with its opening."""
    expected_commander, _, expected_factory = expected_builds(opening, tasks)
    builders = list(orders_by_builder(orders).values())
    commander_orders = distinct_orders(builders[0]) if builders else []
    factory_orders = builders[1] if len(builders) > 1 else []
    commander = commander_orders[: len(expected_commander)]
    factory = factory_orders[: len(expected_factory)]
    commander_units = [order.unit for order in commander]
    factory_units = [order.unit for order in factory]
    return {
        "commander": commander_units,
        "commander_frames": [order.frame for order in commander],
        "factory": factory_units,
        "factory_frames": [order.frame for order in factory],
        "matches": commander_units == expected_commander and factory_units == expected_factory,
    }


def check_built(records: list[dict], team: int, opening: dict, tasks: dict) -> dict:
    """Compare what one team really built with its opening.

    `records` are the lines of a state file (reason8.headless.state). A unit
    counts when its builder started it ("created" with the builder in "by") and
    it was finished before the state file ends.
    """
    expected_commander, factory_name, expected_factory = expected_builds(opening, tasks)
    unit_names: dict[str, str] = {}
    finished: dict[int, int] = {}  # unit id -> frame
    started: list[dict] = []
    for record in records:
        if record["t"] == "header":
            unit_names = record["unitdefs"]
        elif record["t"] == "finished":
            finished[record["u"]] = record["f"]
        elif record["t"] == "created" and record.get("team") == team and "by" in record:
            started.append(record)

    def name(record: dict) -> str:
        return unit_names.get(str(record["d"]), str(record["d"]))

    built = [record for record in started if record["u"] in finished]
    commander_id = started[0]["by"] if started else None
    commander = [record for record in built if record["by"] == commander_id]
    factory_id = next((record["u"] for record in commander if name(record) == factory_name), None)
    factory = [record for record in built if record["by"] == factory_id]
    commander = commander[: len(expected_commander)]
    factory = factory[: len(expected_factory)]
    commander_units = [name(record) for record in commander]
    factory_units = [name(record) for record in factory]
    return {
        "commander": commander_units,
        "commander_finished_frames": [finished[record["u"]] for record in commander],
        "factory": factory_units,
        "factory_finished_frames": [finished[record["u"]] for record in factory],
        # nothing out of order so far; without "matches" the opening was not finished in time
        "in_order": expected_commander[: len(commander_units)] == commander_units
        and expected_factory[: len(factory_units)] == factory_units,
        "matches": commander_units == expected_commander and factory_units == expected_factory,
    }


def choose_opening(
    openings: list[dict], side: str, map_name: str | None, start: tuple[float, float] | None
) -> dict | None:
    """The opening the AI plays, chosen as ``opening.as`` does: of the openings for the side
    and map, the one whose start is nearest to the team's; without one for the map, the
    first for the side and any map."""
    for_map = [o for o in openings if o["side"] == side and o.get("map", "") == map_name]
    if for_map and start is not None:
        return min(
            for_map,
            key=lambda o: (o["start"][0] - start[0]) ** 2 + (o["start"][1] - start[1]) ** 2,
        )
    if for_map:
        return for_map[0]
    return next((o for o in openings if o["side"] == side and not o.get("map")), None)


def check_replay(
    replay: Replay, openings: dict, ai_short_name: str, state_records: list[dict] | None = None
) -> list[dict]:
    """One result per team that the AI played."""
    tasks = openings.get("tasks", {})
    teams = replay.teams()
    map_name = replay.meta.get("map")
    results = []
    for ai in sorted(replay.ais, key=lambda ai: ai["teamId"]):
        if ai.get("shortName") != ai_short_name:
            continue
        side = (ai.get("faction") or "").lower()
        result = {"team": ai["teamId"], "side": side, "version_in_replay": ai.get("version")}
        team = teams.get(ai["teamId"])
        opening = choose_opening(
            openings.get("openings", []), side, map_name, team.start_pos if team else None
        )
        if opening is None:
            result.update({"matches": False, "error": f"no opening for side {side!r}"})
            results.append(result)
            continue
        if opening.get("position"):
            result["position"] = opening["position"]
        expected_commander, factory_name, expected_factory = expected_builds(opening, tasks)
        result["expected"] = {
            "commander": expected_commander,
            "factory_name": factory_name,
            "factory": expected_factory,
        }
        orders = replay.build_orders(team=ai["teamId"])
        result["ordered"] = check_ordered(orders, opening, tasks)
        result["matches"] = result["ordered"]["matches"]
        if state_records is not None:
            result["built"] = check_built(state_records, ai["teamId"], opening, tasks)
            result["matches"] = result["built"]["matches"]
        results.append(result)
    return results


OPENING_LINE = re.compile(r"team (\d+): (.*)")
CHOSEN = re.compile(r"position (\S+) .*?, (\d+) commander steps")


def count_opening_line(teams: dict[int, dict], message: str) -> None:
    """Add one ``Reason8 opening: team N: ...`` log line to its team's counts."""
    match = OPENING_LINE.match(message)
    if not match:
        return
    team = teams.setdefault(
        int(match.group(1)),
        {
            "position": None,
            "commander_steps": None,
            "steps_finished": 0,
            "steps_skipped": 0,
            "factory_units_done": 0,
            "factory_units_skipped": 0,
        },
    )
    text = match.group(2)
    if chosen := CHOSEN.search(text):
        team["position"], team["commander_steps"] = chosen.group(1), int(chosen.group(2))
    elif text.startswith("step ") and ": finished," in text:
        team["steps_finished"] += 1
    elif text.startswith("step ") and text.endswith(": skipped"):
        team["steps_skipped"] += 1
    elif text.startswith("factory unit ") and ": done," in text:
        team["factory_units_done"] += 1
    elif text.startswith("factory unit ") and text.endswith(": skipped"):
        team["factory_units_skipped"] += 1


def check_infolog(infolog: Path, ai_short_name: str) -> dict:
    """Loaded version and scripts of the AI, and its errors, from the engine log."""
    prefix = re.compile(rf"Skirmish AI <{re.escape(ai_short_name)}-([^>]*)>: (.*)")
    versions: set[str] = set()
    scripts: list[str] = []
    errors: list[str] = []
    opening_lines = 0
    teams: dict[int, dict] = {}
    with infolog.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            if any(needle in line for needle in ENGINE_ERRORS):
                errors.append(line.split("] ", 1)[-1].strip()[:300])
            match = prefix.search(line)
            if not match:
                continue
            versions.add(match.group(1))
            message = match.group(2).rstrip()
            if message.startswith("Load script: "):
                scripts.append(message.removeprefix("Load script: "))
            if message.startswith("Reason8 opening:"):
                opening_lines += 1
                count_opening_line(teams, message.removeprefix("Reason8 opening: "))
            if any(needle in message for needle in SCRIPT_ERRORS):
                errors.append(message[:300])
    if not scripts:
        errors.append(f"the log has no script loaded by {ai_short_name}")
    return {
        "versions_loaded": sorted(versions),
        "scripts_loaded": sorted(set(scripts)),
        "opening_log_lines": opening_lines,
        "opening_by_team": dict(sorted(teams.items())),
        "errors": errors,
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("replay", type=Path, help="the recorded game (.sdfz)")
    parser.add_argument("--openings", type=Path, default=DEFAULT_OPENINGS)
    parser.add_argument("--ai", default="Reason8", help="short name of the AI to check")
    parser.add_argument("--infolog", type=Path, help="the run's infolog.txt")
    parser.add_argument(
        "--state",
        type=Path,
        help="state file of the replay (reason8 headless run --snapshots --out)",
    )
    parser.add_argument("--parser", type=Path, help="sdfz-demo-parser binary")


def run(args: argparse.Namespace) -> int:
    openings = json.loads(args.openings.read_text(encoding="utf-8"))
    document, _ = parse_replay(args.parser or default_parser(), args.replay)
    state_records = list(read_records(args.state)) if args.state else None
    result: dict = {"teams": check_replay(Replay(document), openings, args.ai, state_records)}
    ok = bool(result["teams"]) and all(team["matches"] for team in result["teams"])
    if args.infolog:
        result["log"] = check_infolog(args.infolog, args.ai)
        ok = ok and not result["log"]["errors"]
    result["ok"] = ok
    print(json.dumps(result, indent=1))
    return 0 if ok else 1
