#!/usr/bin/env python3
"""Check from a replay that an AI played the opening it was built with.

    uv run python tools/variant/check_opening.py RUN/demos/GAME.sdfz \\
        --infolog RUN/infolog.txt [--state STATE.jsonl]

Every team played by the AI (--ai, by short name) is compared with its opening
in ai/Reason8/openings.json, in up to three ways:

Ordered (always): the replay is parsed with reason8.parse. The commander is
  the builder of the team's first build order, and the first factory is the
  second builder to give one. The commander's first orders must be the
  opening's commander steps, and the factory's first orders the opening's
  units for that factory, in order. A commander order repeated for the same
  unit at the same place is counted once, because BARb re-sends orders.

Built (--state): the state file comes from playing the replay again with
  `tools/headless/run.py --snapshots`. It tells what was really built: the
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
import sys
from pathlib import Path

from reason8.parse import default_parser, parse_replay
from reason8.replay import BuildOrder, Replay

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "headless"))
import state as state_file  # noqa: E402

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

    `records` are the lines of a state file (tools/headless/state.py). A unit
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


def check_replay(
    replay: Replay, openings: dict, ai_short_name: str, state_records: list[dict] | None = None
) -> list[dict]:
    """One result per team that the AI played."""
    by_side = {opening["side"]: opening for opening in openings.get("openings", [])}
    tasks = openings.get("tasks", {})
    results = []
    for ai in sorted(replay.ais, key=lambda ai: ai["teamId"]):
        if ai.get("shortName") != ai_short_name:
            continue
        side = (ai.get("faction") or "").lower()
        result = {"team": ai["teamId"], "side": side, "version_in_replay": ai.get("version")}
        if side not in by_side:
            result.update({"matches": False, "error": f"no opening for side {side!r}"})
            results.append(result)
            continue
        opening = by_side[side]
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


def check_infolog(infolog: Path, ai_short_name: str) -> dict:
    """Loaded version and scripts of the AI, and its errors, from the engine log."""
    prefix = re.compile(rf"Skirmish AI <{re.escape(ai_short_name)}-([^>]*)>: (.*)")
    versions: set[str] = set()
    scripts: list[str] = []
    errors: list[str] = []
    opening_lines = 0
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
            if any(needle in message for needle in SCRIPT_ERRORS):
                errors.append(message[:300])
    if not scripts:
        errors.append(f"the log has no script loaded by {ai_short_name}")
    return {
        "versions_loaded": sorted(versions),
        "scripts_loaded": sorted(set(scripts)),
        "opening_log_lines": opening_lines,
        "errors": errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    argument_parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    argument_parser.add_argument("replay", type=Path, help="the recorded game (.sdfz)")
    argument_parser.add_argument("--openings", type=Path, default=DEFAULT_OPENINGS)
    argument_parser.add_argument("--ai", default="Reason8", help="short name of the AI to check")
    argument_parser.add_argument("--infolog", type=Path, help="the run's infolog.txt")
    argument_parser.add_argument(
        "--state", type=Path, help="state file of the replay (run.py --snapshots --out)"
    )
    argument_parser.add_argument("--parser", type=Path, help="sdfz-demo-parser binary")
    return argument_parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    openings = json.loads(args.openings.read_text(encoding="utf-8"))
    document, _ = parse_replay(args.parser or default_parser(), args.replay)
    state_records = list(state_file.read_lines(args.state)) if args.state else None
    result: dict = {"teams": check_replay(Replay(document), openings, args.ai, state_records)}
    ok = bool(result["teams"]) and all(team["matches"] for team in result["teams"])
    if args.infolog:
        result["log"] = check_infolog(args.infolog, args.ai)
        ok = ok and not result["log"]["errors"]
    result["ok"] = ok
    print(json.dumps(result, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
