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

Ended (--infolog): an opening that no longer applied was ended before its last
  step (``opening.as``, EndOpening), and BARb took over. The log says when,
  why (`reason`: "step", a commander step not finished in time; "time", past
  the opening window; "contact", the team's first contact) and how many
  commander steps and factory units were done by then; only those are
  compared in the ways above.

Model (--infolog): a team whose builders' next orders the model decided (the
  AI option builder_orders=model, ADR 0019) plays no opening, so none is
  compared. Its log says, per team, how often an idle builder needed an order
  and what came of it (`reason8.bot.next_order.summary`): an order the model
  chose and that was carried out, chosen but not carried out, no answer of at
  least 10%, nothing the builder could carry out, or no answer at all; how
  often the order was left to BARb, by kind of builder and by game minute;
  where extractors went; and when and why the model's orders ended. The team
  passes when the model decided orders for it.

Log (--infolog): whether the AI loaded, which version and scripts, and script
  errors. An AI that fails to load or compile does not stop the game: its team
  stands still. With our BARb library (`reason8 bot build`), also the command
  governor of each team (`reason8.bot.budget`): that the library was built for
  the engine it ran in, that every command the AI gave was sent, replaced by a
  newer order to the same unit, or still held at the end (none dropped), and
  that the actions it sent kept every window of the budget of ADR 0008.

Budget in the replay (always): each team's commands in the replay, counted as
  actions the way a player's are, and the most in each window of the budget.
  A cross-check of the governor's own count, not part of the verdict: a
  headless game's replay records a command 12 to 30 frames after the AI
  gave it.

Prints one JSON object. The exit code is non-zero when a team did not play its
opening, no team was played by the AI, or the log shows the AI did not load
cleanly.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path

from reason8.analysis.apm import ActionCounter
from reason8.bot import budget, live_state, next_order
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
    openings: list[dict],
    side: str,
    map_name: str | None,
    start: tuple[float, float] | None,
    variant: int = 0,
    position: str | None = None,
) -> dict | None:
    """The opening the AI plays, chosen as ``opening.as`` does: of the openings for the side
    and map, those of the position whose start is nearest to the team's, and of them the
    `variant`-th (the script picks it at random and logs it); without one for the map, the
    first for the side and any map. The script finds its position from where its commander
    stands, which is not always the start in the replay; the `position` it logged wins."""
    for_map = [o for o in openings if o["side"] == side and o.get("map", "") == map_name]
    logged = [o for o in for_map if position is not None and o.get("position") == position]
    if logged:
        return logged[variant] if variant < len(logged) else logged[0]
    if for_map and start is not None:
        nearest = min(
            for_map,
            key=lambda o: (o["start"][0] - start[0]) ** 2 + (o["start"][1] - start[1]) ** 2,
        )
        at_position = [o for o in for_map if o.get("position") == nearest.get("position")]
        return at_position[variant] if variant < len(at_position) else nearest
    if for_map:
        return for_map[0]
    return next((o for o in openings if o["side"] == side and not o.get("map")), None)


def replay_budget(replay: Replay, team: int, band: str = budget.DEFAULT_BAND) -> dict:
    """One team's commands in the replay, counted as actions, against the band's windows."""
    counter = ActionCounter()
    commands = 0
    for event in replay.events:
        if event.get("type") == "cmd" and event.get("team") == team:
            commands += 1
            counter.command(event["frame"], event.get("units") or ())
    return {
        "commands": commands,
        "actions": len(counter.frames),
        "windows": budget.windows_kept(counter.frames, band),
    }


# The side of a unit, from the prefix of its name.
SIDE_OF_PREFIX = {"arm": "armada", "cor": "cortex", "leg": "legion"}


def ordered_side(replay: Replay, team: int) -> str | None:
    """The side of the first unit the team ordered, or None when it ordered nothing."""
    for order in replay.build_orders(team=team):
        if side := SIDE_OF_PREFIX.get((order.unit or "")[:3]):
            return side
    return None


def played_part(opening: dict, ended: Mapping | None) -> dict:
    """The part of `opening` the AI played: all of it, or when the opening was ended early
    (`ended`, from the log), the commander steps and factory units done by then."""
    if not ended:
        return opening
    steps, units = ended["commander_steps_done"], ended["factory_units_done"]
    return {
        **opening,
        "commander": opening.get("commander", [])[:steps],
        "factories": {name: made[:units] for name, made in opening.get("factories", {}).items()},
    }


def check_replay(
    replay: Replay,
    openings: dict,
    ai_short_name: str,
    state_records: list[dict] | None = None,
    variants: Mapping[int, int] | None = None,
    positions: Mapping[int, str | None] | None = None,
    sides: Mapping[int, str | None] | None = None,
    ended: Mapping[int, Mapping | None] | None = None,
    model_orders: Mapping[int, Mapping] | None = None,
) -> list[dict]:
    """One result per team that the AI played. `variants`, `positions` and `sides` are the
    opening, position and side each team chose, from the engine log (`check_infolog`);
    without them, the first opening of the position nearest to its start, for the side in
    the replay. `ended` says, per team, when its opening was ended early and how much of it
    was done (`check_infolog`); only that part is compared. A team in `model_orders` (the
    `reason8.bot.next_order.summary` of its log) had the model decide its builders' next
    orders instead of playing an opening: it matches when the model decided some.

    A lobby that leaves an AI's faction on random writes ``Random`` into the replay, and the
    game picks the side at the start. The side the AI logged is then used, or else the side
    of the first unit the team ordered."""
    tasks = openings.get("tasks", {})
    teams = replay.teams()
    map_name = replay.meta.get("map")
    results = []
    for ai in sorted(replay.ais, key=lambda ai: ai["teamId"]):
        if ai.get("shortName") != ai_short_name:
            continue
        side = (ai.get("faction") or "").lower()
        if side not in SIDE_OF_PREFIX.values():
            side = (sides or {}).get(ai["teamId"]) or ordered_side(replay, ai["teamId"]) or side
        result = {"team": ai["teamId"], "side": side, "version_in_replay": ai.get("version")}
        result["replay_budget"] = replay_budget(replay, ai["teamId"])
        if team_orders := (model_orders or {}).get(ai["teamId"]):
            result.update({"mode": "model", "next_order": dict(team_orders)})
            result["matches"] = team_orders["idle_builders"] > 0
            results.append(result)
            continue
        team = teams.get(ai["teamId"])
        opening = choose_opening(
            openings.get("openings", []),
            side,
            map_name,
            team.start_pos if team else None,
            (variants or {}).get(ai["teamId"], 0),
            (positions or {}).get(ai["teamId"]),
        )
        if opening is None:
            result.update({"matches": False, "error": f"no opening for side {side!r}"})
            results.append(result)
            continue
        if opening.get("position"):
            result["position"] = opening["position"]
        if team_ended := (ended or {}).get(ai["teamId"]):
            result["ended"] = dict(team_ended)
            opening = played_part(opening, team_ended)
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
CHOSEN = re.compile(r"position (\S+) .*?(?:, opening (\d+) of \d+)?, (\d+) commander steps")
LOGGED_SIDE = re.compile(r"side '([^']*)'")
ENDED = re.compile(
    r"opening ended at frame (\d+), (\w+): (.*); commander steps done (\d+) of \d+, "
    r"factory units done (\d+) of \d+"
)


def count_opening_line(teams: dict[int, dict], message: str) -> None:
    """Add one ``Reason8 opening: team N: ...`` log line to its team's counts."""
    match = OPENING_LINE.match(message)
    if not match:
        return
    team = teams.setdefault(
        int(match.group(1)),
        {
            "position": None,
            "side": None,
            "commander_steps": None,
            "variant": 0,
            "steps_finished": 0,
            "steps_skipped": 0,
            "factory_units_done": 0,
            "factory_units_skipped": 0,
            "ended": None,
        },
    )
    text = match.group(2)
    if chosen := CHOSEN.search(text):
        team["position"], team["commander_steps"] = chosen.group(1), int(chosen.group(3))
        team["variant"] = int(chosen.group(2)) - 1 if chosen.group(2) else 0
        if logged_side := LOGGED_SIDE.search(text):
            team["side"] = logged_side.group(1)
    elif text.startswith("step ") and ": finished," in text:
        team["steps_finished"] += 1
    elif text.startswith("step ") and text.endswith(": skipped"):
        team["steps_skipped"] += 1
    elif text.startswith("factory unit ") and ": done," in text:
        team["factory_units_done"] += 1
    elif text.startswith("factory unit ") and text.endswith(": skipped"):
        team["factory_units_skipped"] += 1
    elif ended := ENDED.match(text):
        team["ended"] = {
            "frame": int(ended.group(1)),
            "reason": ended.group(2),
            "detail": ended.group(3),
            "commander_steps_done": int(ended.group(4)),
            "factory_units_done": int(ended.group(5)),
        }


def check_infolog(infolog: Path, ai_short_name: str) -> dict:
    """Loaded version and scripts of the AI, and its errors, from the engine log."""
    prefix = re.compile(rf"Skirmish AI <{re.escape(ai_short_name)}-([^>]*)>: (.*)")
    versions: set[str] = set()
    scripts: list[str] = []
    errors: list[str] = []
    opening_lines = 0
    teams: dict[int, dict] = {}
    governor_messages: list[str] = []
    state_lines: dict[int, list[dict]] = {}
    model_teams: dict[int, dict] = {}
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
            if message.startswith(("Reason8 governor:", "Reason8 library:")):
                governor_messages.append(message)
            if message.startswith("Reason8 next order:"):
                text = message.removeprefix("Reason8 next order: ")
                if team_line := OPENING_LINE.match(text):
                    next_order.count_line(model_teams, int(team_line.group(1)), team_line.group(2))
            if message.startswith("Reason8 opening:"):
                team_line = OPENING_LINE.match(message.removeprefix("Reason8 opening: "))
                if team_line and (state := live_state.parse_line(team_line.group(2))):
                    state_lines.setdefault(int(team_line.group(1)), []).append(state)
                    continue
                opening_lines += 1
                count_opening_line(teams, message.removeprefix("Reason8 opening: "))
            if any(needle in message for needle in SCRIPT_ERRORS):
                errors.append(message[:300])
    if not scripts:
        errors.append(f"the log has no script loaded by {ai_short_name}")
    governor = budget.governor_log(governor_messages)
    for team, checked in governor.items():
        errors += [f"governor of team {team}: {problem}" for problem in checked["problems"]]
    return {
        "versions_loaded": sorted(versions),
        "scripts_loaded": sorted(set(scripts)),
        "opening_log_lines": opening_lines,
        "opening_by_team": dict(sorted(teams.items())),
        "governor_by_team": governor,
        "live_state_by_team": dict(sorted(state_lines.items())),
        "next_order_by_team": {
            team: next_order.summary(counts) for team, counts in sorted(model_teams.items())
        },
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
    log = check_infolog(args.infolog, args.ai) if args.infolog else None
    chosen = (log or {}).get("opening_by_team", {})
    variants = {team: counts["variant"] for team, counts in chosen.items()}
    positions = {team: counts["position"] for team, counts in chosen.items()}
    sides = {team: counts["side"] for team, counts in chosen.items()}
    ended = {team: counts["ended"] for team, counts in chosen.items()}
    model_orders = (log or {}).get("next_order_by_team", {})
    teams = check_replay(
        Replay(document),
        openings,
        args.ai,
        state_records,
        variants,
        positions,
        sides,
        ended,
        model_orders,
    )
    result: dict = {"teams": teams}
    ok = bool(teams) and all(team["matches"] for team in teams)
    if log is not None:
        state_lines = log.pop("live_state_by_team")
        if args.state:
            log["live_state_by_team"] = {
                team: live_state.compare(lines, read_records(args.state, snapshots=True), team)
                for team, lines in state_lines.items()
            }
        else:
            log["live_state_lines"] = {team: len(lines) for team, lines in state_lines.items()}
        result["log"] = log
        ok = ok and not log["errors"]
    result["ok"] = ok
    print(json.dumps(result, indent=1))
    return 0 if ok else 1
