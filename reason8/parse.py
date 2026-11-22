"""Parse `.sdfz` replays into compact JSON with the pinned sdfz-demo-parser.

Usage::

    parser/fetch.sh                      # once: download the pinned parser binary
    uv run python -m reason8.parse       # data/replays/*.sdfz -> data/parsed/*.json.zst
    uv run python -m reason8.parse DIR_OR_FILE ... --out OUT --jobs 4

Each replay becomes one zstd-compressed JSON document (see docs/replay-format.md).
A replay that fails to parse gets an entry with the error in `<out>/_index.jsonl`
instead of stopping the run. Already parsed replays are skipped unless `--force`.
Default paths are under the data directory (``REASON8_DATA_DIR``, or ``data/`` in the repo).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from compression import zstd
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from reason8.match_dumps import data_dir
from reason8.sdfz import RawCommandPacket, read_command_packets_file

#: Parsed replays are written once and read many times, so compress hard: level 19
#: is about 30% smaller than gzip and decompresses twice as fast, at about 4 s of
#: CPU per replay. Lower levels (9: 13% smaller, 0.1 s) suit quick experiments.
ZSTD_LEVEL = 19
PARSED_SUFFIX = ".json.zst"

PARSER_VERSION = "5.15.1"
FORMAT = "reason8.replay/1"
GAME_SPEED = 30  # sim frames per second
INDEX_NAME = "_index.jsonl"

# Packet types we ask the parser for. Everything else (frame/sync/ping noise,
# system/log messages, setup text containing names) is dropped at the source.
INCLUDE_PACKETS = [
    "STARTPLAYING",
    "CHAT",
    "COMMAND",
    "SELECT",
    "PAUSE",
    "AICOMMAND",
    "AICOMMANDS",
    "AISHARE",
    "SHARE",
    "SETSHARE",
    "GAMEOVER",
    "MAPDRAW_OLD",
    "MAPDRAW",
    "STARTPOS",
    "PLAYERLEFT",
    "TEAM",
    "QUIT",
    "LUAMSG",  # needed for the UNITDEFS table and the faction picker; not kept
]

# BAR custom commands (Beyond-All-Reason modules/customcommands.lua, Nov 2026).
# The engine's own commands are named by the parser.
BAR_CUSTOM_COMMANDS = {
    13921: "FACTORY_GUARD",
    13922: "AREA_GUARD",
    13923: "STOP_PRODUCTION",
    18200: "BLUEPRINT_PLACE",
    18201: "BLUEPRINT_CREATE",
    23000: "QUOTA_BUILD_TOGGLE",
    30100: "AREA_MEX",
    30101: "SELL_UNIT",
    30102: "SHARE_UNIT",
    31200: "CARRIER_SPAWN_ONOFF",
    31210: "MORPH",
    31300: "USER_FIRESTATE",
    32102: "MANUAL_LAUNCH",
    34569: "LAND_AT",
    34571: "PRIORITY",
    34922: "UNIT_SET_TARGET_NO_GROUND",
    34923: "UNIT_SET_TARGET",
    34924: "UNIT_CANCEL_TARGET",
    34925: "UNIT_SET_TARGET_RECTANGLE",
    37382: "WANT_CLOAK",
    37383: "HOUND_WEAPON_TOGGLE",
    37384: "SMART_TOGGLE",
    39812: "RAW_MOVE",
    39954: "AREA_ATTACK_GROUND",
}

# Engine command ids (rts/Sim/Units/CommandAI/Command.h), for nested INSERT commands.
ENGINE_COMMANDS = {
    0: "STOP",
    1: "INSERT",
    2: "REMOVE",
    5: "WAIT",
    6: "TIMEWAIT",
    7: "DEATHWAIT",
    8: "SQUADWAIT",
    9: "GATHERWAIT",
    10: "MOVE",
    15: "PATROL",
    16: "FIGHT",
    20: "ATTACK",
    21: "AREA_ATTACK",
    25: "GUARD",
    35: "GROUPSELECT",
    36: "GROUPADD",
    37: "GROUPCLEAR",
    40: "REPAIR",
    45: "FIRE_STATE",
    50: "MOVE_STATE",
    55: "SETBASE",
    60: "INTERNAL",
    65: "SELFD",
    75: "LOAD_UNITS",
    76: "LOAD_ONTO",
    80: "UNLOAD_UNITS",
    81: "UNLOAD_UNIT",
    85: "ONOFF",
    90: "RECLAIM",
    95: "CLOAK",
    100: "STOCKPILE",
    105: "MANUALFIRE",
    110: "RESTORE",
    115: "REPEAT",
    120: "TRAJECTORY",
    125: "RESURRECT",
    130: "CAPTURE",
    135: "AUTOREPAIRLEVEL",
    145: "IDLEMODE",
    150: "FAILED",
}

# Command option bits (rts/Sim/Units/CommandAI/Command.h).
OPTION_BITS = [
    (4, "meta"),
    (8, "internal"),
    (16, "right"),
    (32, "shift"),
    (64, "ctrl"),
    (128, "alt"),
]

MAPDRAW_ACTIONS = {0: "point", 1: "erase", 2: "line"}
TEAM_ACTIONS = {
    1: "giveaway",
    2: "resign",
    3: "join_team",
    4: "team_died",
    5: "ai_created",
    6: "ai_destroyed",
}
LUAUI_AI_ID = 255  # AICOMMAND(S) with this aiId come from a player's LuaUI widget, not a bot


class ParseError(Exception):
    pass


def command_name(cmd_id: int) -> str:
    if cmd_id < 0:
        return "BUILD"
    return ENGINE_COMMANDS.get(cmd_id) or BAR_CUSTOM_COMMANDS.get(cmd_id) or f"CMD_{cmd_id}"


def option_names(bits: int) -> list[str]:
    return [name for bit, name in OPTION_BITS if bits & bit]


def _round_number(value: Any) -> Any:
    """Round floats for compactness; command params are float32 anyway."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if value.is_integer():
            return int(value)
        return round(value, 2)
    return value


def _round_numbers(values: Any) -> list[Any]:
    return [_round_number(value) for value in values]


def run_parser(parser: Path, replay: Path, *, header_only: bool = False, timeout: float = 600):
    command = [str(parser), str(replay), "--compact"]
    if header_only:
        command.append("--header-only")
    else:
        command += ["--include-packets", ",".join(INCLUDE_PACKETS)]
    process = subprocess.run(command, capture_output=True, timeout=timeout)
    if process.returncode != 0:
        message = (
            process.stderr.decode("utf-8", "replace").strip() or f"exit code {process.returncode}"
        )
        raise ParseError(f"sdfz-demo-parser: {message}")
    return process.stdout


def _command_record(
    command_id: int, options: int, params: list[float], unitdefs: list[str]
) -> dict[str, Any]:
    record: dict[str, Any] = {"cmd": command_name(command_id), "cmd_id": command_id}
    if command_id < 0:
        unitdef_index = -command_id
        record["unit"] = unitdefs[unitdef_index] if unitdef_index < len(unitdefs) else None
    option_labels = option_names(options)
    if option_labels:
        record["opts"] = option_labels
    if command_id == 1 and len(params) >= 3:  # INSERT: [queuePos, cmdId, options, *params]
        record["pos"] = _round_number(params[0])
        record["inner"] = _command_record(int(params[1]), int(params[2]), params[3:], unitdefs)
    else:
        record["params"] = _round_numbers(params)
    return record


def compact(parsed: dict[str, Any], raw: list[RawCommandPacket], source: dict[str, Any]):
    """Turn sdfz-demo-parser output (plus raw command ids) into our compact document."""
    info = parsed["info"]
    header = parsed["header"]
    packets = parsed.get("packets", [])

    unitdefs: list[str] = []
    for packet in packets:
        packet_data = packet.get("data") or {}
        if packet["name"] == "LUAMSG" and isinstance(packet_data.get("data"), dict):
            if packet_data["data"].get("name") == "UNITDEFS":
                unitdefs = packet_data["data"]["data"]
                break

    start_time = None
    for packet in packets:
        if packet["name"] == "STARTPLAYING" and packet["data"]["countdown"] == 0:
            start_time = packet["fullGameTime"]
            break

    def packet_frame(packet: dict[str, Any]) -> int | None:
        if start_time is None:
            return None
        return round((packet["fullGameTime"] - start_time) * GAME_SPEED)

    player_team = {player["playerId"]: player["teamId"] for player in info.get("players", [])}
    ai_team = {ai["aiId"]: ai["teamId"] for ai in info.get("ais", [])}

    command_packets = [
        packet for packet in packets if packet["name"] in ("COMMAND", "AICOMMAND", "AICOMMANDS")
    ]
    if len(command_packets) != len(raw):
        raise ParseError(
            f"command packet count mismatch: parser {len(command_packets)}, raw reader {len(raw)}"
        )
    raw_packets = iter(raw)

    events: list[dict[str, Any]] = []
    for packet in packets:
        name = packet["name"]
        packet_data = packet.get("data") or {}
        frame = packet_frame(packet)
        if name in ("COMMAND", "AICOMMAND", "AICOMMANDS"):
            raw_packet = next(raw_packets)
            parsed_commands = (
                packet_data["commands"] if name == "AICOMMANDS" else [packet_data["command"]]
            )
            if len(parsed_commands) != len(raw_packet.commands) or any(
                _round_numbers(parsed_command["params"]) != _round_numbers(raw_command.params)
                for parsed_command, raw_command in zip(
                    parsed_commands, raw_packet.commands, strict=True
                )
            ):
                raise ParseError(f"command packet mismatch at t={packet['fullGameTime']}")
            player = packet_data["playerNum"]
            base: dict[str, Any] = {"frame": frame, "type": "cmd", "player": player, "via": name}
            if name == "COMMAND":
                team = player_team.get(player)
            else:
                ai_id = packet_data["aiId"]
                base["ai"] = ai_id
                if ai_id == LUAUI_AI_ID:
                    team = player_team.get(player)
                else:
                    team = packet_data.get("aiTeamId", ai_team.get(ai_id))
            base["team"] = team
            if name == "AICOMMAND":
                unit_lists = [[packet_data["command"]["unitId"]]]
            elif name == "AICOMMANDS":
                unit_ids = packet_data["unitIds"]
                if packet_data["pairwise"]:
                    unit_lists = [unit_ids[i : i + 1] for i in range(len(parsed_commands))]
                else:
                    unit_lists = [unit_ids] * len(parsed_commands)
            else:
                unit_lists = [None]  # current selection, see "select" events
            for raw_command, units in zip(raw_packet.commands, unit_lists, strict=True):
                event = dict(base)
                if units is not None:
                    event["units"] = units
                event.update(
                    _command_record(
                        raw_command.cmd_id, raw_command.options, list(raw_command.params), unitdefs
                    )
                )
                events.append(event)
        elif name == "SELECT":
            events.append(
                {
                    "frame": frame,
                    "type": "select",
                    "player": packet_data["playerNum"],
                    "units": packet_data["selectedUnitIds"],
                }
            )
        elif name == "STARTPLAYING":
            if packet_data["countdown"] == 0:
                events.append({"frame": frame, "type": "start"})
        elif name == "STARTPOS":
            events.append(
                {
                    "frame": frame,
                    "type": "startpos",
                    "player": packet_data["playerNum"],
                    "team": packet_data["teamId"],
                    "ready": packet_data["readyState"],
                    "x": _round_number(packet_data["x"]),
                    "z": _round_number(packet_data["z"]),
                }
            )
        elif name == "CHAT":
            events.append(
                {
                    "frame": frame,
                    "type": "chat",
                    "player": packet_data["fromId"],
                    "to": packet_data["toId"],
                    "message": packet_data["message"],
                }
            )
        elif name in ("MAPDRAW", "MAPDRAW_OLD"):
            event = {
                "frame": frame,
                "type": "mapdraw",
                "player": packet_data["playerNum"],
                "action": MAPDRAW_ACTIONS.get(
                    packet_data["mapDrawAction"], packet_data["mapDrawAction"]
                ),
                "x": packet_data["x"],
                "z": packet_data["z"],
            }
            for key in ("x2", "z2", "label"):
                if packet_data.get(key) is not None:
                    event[key] = packet_data[key]
            if packet_data.get("fromLua"):
                event["from_lua"] = True
            events.append(event)
        elif name == "SHARE":
            events.append(
                {
                    "frame": frame,
                    "type": "share",
                    "player": packet_data["playerNum"],
                    "to_team": packet_data["shareTeam"],
                    "units": packet_data["shareUnits"],
                    "metal": _round_number(packet_data["shareMetal"]),
                    "energy": _round_number(packet_data["shareEnergy"]),
                }
            )
        elif name == "SETSHARE":
            events.append(
                {
                    "frame": frame,
                    "type": "setshare",
                    "player": packet_data["playerNum"],
                    "team": packet_data["teamId"],
                    "metal": _round_number(packet_data["metalShareFraction"]),
                    "energy": _round_number(packet_data["energyShareFraction"]),
                }
            )
        elif name == "AISHARE":
            events.append(
                {
                    "frame": frame,
                    "type": "aishare",
                    "player": packet_data["playerNum"],
                    "ai": packet_data["aiId"],
                    "from_team": packet_data["sourceTeam"],
                    "to_team": packet_data["destTeam"],
                    "metal": _round_number(packet_data["metal"]),
                    "energy": _round_number(packet_data["energy"]),
                    "units": packet_data["unitIds"],
                }
            )
        elif name == "GAMEOVER":
            events.append(
                {
                    "frame": frame,
                    "type": "gameover",
                    "player": packet_data["playerNum"],
                    "winners": packet_data["winningAllyTeams"],
                }
            )
        elif name == "PLAYERLEFT":
            events.append(
                {
                    "frame": frame,
                    "type": "playerleft",
                    "player": packet_data["playerNum"],
                    "reason": packet_data["reason"],
                }
            )
        elif name == "TEAM":
            events.append(
                {
                    "frame": frame,
                    "type": "team",
                    "player": packet_data["playerNum"],
                    "action": TEAM_ACTIONS.get(packet_data["action"], packet_data["action"]),
                    "param": packet_data["param"],
                }
            )
        elif name == "PAUSE":
            events.append(
                {
                    "frame": frame,
                    "type": "pause",
                    "player": packet_data["playerNum"],
                    "paused": packet_data["paused"],
                }
            )
        elif name == "QUIT":
            events.append({"frame": frame, "type": "quit"})

    gameover_frame = next((event["frame"] for event in events if event["type"] == "gameover"), None)
    meta = dict(info["meta"])
    meta.update(
        {
            "demoVersion": header["version"],
            "gameTime": header["gameTime"],
            "wallclockTime": header["wallclockTime"],
            "startFrame": 0 if start_time is not None else None,
            "endFrame": gameover_frame,
            "serverMatchId": info.get("hostSettings", {}).get("server_match_id"),
        }
    )

    def pick(record: dict[str, Any], keys: list[str]) -> dict[str, Any]:
        return {key: record[key] for key in keys if key in record}

    player_keys = [
        "playerId",
        "teamId",
        "allyTeamId",
        "name",
        "userId",
        "faction",
        "rank",
        "skill",
        "skillUncertainty",
        "startPos",
    ]
    ai_keys = [
        "aiId",
        "teamId",
        "allyTeamId",
        "name",
        "shortName",
        "version",
        "faction",
        "startPos",
    ]
    return {
        "format": FORMAT,
        "source": source,
        "meta": meta,
        "allyTeams": info.get("allyTeams", []),
        "players": [pick(player, player_keys) for player in info.get("players", [])],
        "ais": [pick(ai, ai_keys) for ai in info.get("ais", [])],
        "spectators": [
            pick(spectator, ["playerId", "name", "userId"])
            for spectator in info.get("spectators", [])
        ],
        "modoptions": info.get("gameSettings", {}),
        "mapoptions": info.get("mapSettings", {}),
        "restrictions": info.get("restrictions", {}),
        "unitdefs": unitdefs,
        "statistics": parsed.get("statistics"),
        "events": events,
    }


def default_parser() -> Path:
    """The pinned parser binary that ``parser/fetch.sh`` downloads into the data directory."""
    return data_dir() / "tools" / f"sdfz-demo-parser-{PARSER_VERSION}" / "sdfz-demo-parser"


def parse_replay(parser: Path, replay: Path) -> tuple[dict[str, Any], int]:
    """Parse one replay. Returns the compact document and the size of the parser's JSON."""
    parser_output = run_parser(parser, replay)
    parsed = json.loads(parser_output)
    raw = read_command_packets_file(replay)
    source = {
        "file": replay.name,
        "bytes": replay.stat().st_size,
        "parser": f"sdfz-demo-parser {PARSER_VERSION}",
    }
    return compact(parsed, raw, source), len(parser_output)


def output_path(out_dir: Path, replay: Path) -> Path:
    return out_dir / (replay.stem + PARSED_SUFFIX)


def write_json_zst(document: Any, path: Path, level: int = ZSTD_LEVEL) -> int:
    """Write compact JSON compressed with zstd; return the uncompressed size."""
    temporary_path = path.with_name(path.name + ".tmp")
    data = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    temporary_path.write_bytes(zstd.compress(data, level=level))
    os.replace(temporary_path, path)
    return len(data)


def process_one(
    parser: Path, replay: Path, out_dir: Path, zstd_level: int = ZSTD_LEVEL
) -> dict[str, Any]:
    entry: dict[str, Any] = {"file": replay.name, "sdfz_bytes": replay.stat().st_size}
    start_time = time.perf_counter()
    try:
        document, parser_json_bytes = parse_replay(parser, replay)
        json_bytes = write_json_zst(document, output_path(out_dir, replay), zstd_level)
        meta = document["meta"]
        entry.update(
            status="ok",
            game=meta.get("game"),
            engine=meta.get("engine"),
            map=meta.get("map"),
            gameId=meta.get("gameId"),
            events=len(document["events"]),
            parser_json_bytes=parser_json_bytes,
            json_bytes=json_bytes,
            compressed_bytes=output_path(out_dir, replay).stat().st_size,
        )
    except Exception as error:  # record any failure per file, keep going
        entry.update(status="error", error=f"{type(error).__name__}: {error}"[:2000])
        try:  # still try to learn the game version, for failure stats
            meta = json.loads(run_parser(parser, replay, header_only=True))["info"]["meta"]
            entry.update(game=meta.get("game"), engine=meta.get("engine"), map=meta.get("map"))
        except Exception:
            pass
    entry["seconds"] = round(time.perf_counter() - start_time, 3)
    return entry


def find_replays(inputs: list[Path]) -> list[Path]:
    found: list[Path] = []
    for input_path in inputs:
        if input_path.is_dir():
            found += sorted(input_path.rglob("*.sdfz"))
        elif input_path.suffix == ".sdfz":
            found.append(input_path)
    return found


def read_index(out_dir: Path) -> dict[str, dict[str, Any]]:
    path = out_dir / INDEX_NAME
    if not path.exists():
        return {}
    return parse_index(path.read_text())


def parse_index(text: str) -> dict[str, dict[str, Any]]:
    """Index entries by replay file name, from the text of an index file."""
    entries = (json.loads(line) for line in text.splitlines() if line.strip())
    return {entry["file"]: entry for entry in entries}


def write_index(out_dir: Path, index: dict[str, dict[str, Any]]) -> None:
    path = out_dir / INDEX_NAME
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(index_text(index))
    os.replace(temporary_path, path)


def index_text(index: dict[str, dict[str, Any]]) -> str:
    """The text of an index file: one JSON line per replay, sorted by file name."""
    return "".join(json.dumps(entry) + "\n" for entry in sorted(index.values(), key=_file_key))


def merge_indexes(destination: bytes, source: bytes) -> bytes | None:
    """Entries of both index files, the ``source`` entry winning for a replay in both.

    Returns ``None`` when ``destination`` already holds every entry of the result.
    """
    entries = parse_index(destination.decode())
    merged = entries | parse_index(source.decode())
    return index_text(merged).encode() if merged != entries else None


def _file_key(entry: dict[str, Any]) -> str:
    return entry["file"]


def summarize(entries: list[dict[str, Any]]) -> str:
    succeeded = [entry for entry in entries if entry["status"] == "ok"]
    lines = [f"{len(succeeded)} ok, {len(entries) - len(succeeded)} failed"]
    if succeeded:

        def mean(field_name: str) -> float:
            return sum(entry[field_name] for entry in succeeded) / len(succeeded)

        lines.append(
            f"per replay: {mean('seconds'):.2f} s, sdfz {mean('sdfz_bytes') / 1e6:.2f} MB, "
            f"parser JSON {mean('parser_json_bytes') / 1e6:.1f} MB, "
            f"ours {mean('json_bytes') / 1e6:.2f} MB "
            f"({mean('compressed_bytes') / 1e6:.2f} MB compressed)"
        )
    for title, fields in (
        ("failures per game version", ("game",)),
        ("failures per engine", ("engine",)),
    ):
        lines.append(title + ":")
        for version, (failed_count, replay_count) in failures_by(entries, fields).items():
            lines.append(f"  {' / '.join(version)}: {failed_count}/{replay_count} failed")
    return "\n".join(lines)


def failures_by(
    entries: list[dict[str, Any]], fields: tuple[str, ...]
) -> dict[tuple[str, ...], tuple[int, int]]:
    """``(failed, total)`` replay counts per value of ``fields`` (e.g. ``("engine",)``)."""
    totals: Counter[tuple[str, ...]] = Counter()
    failed: Counter[tuple[str, ...]] = Counter()
    for entry in entries:
        key = tuple(str(entry.get(field_name)) for field_name in fields)
        totals[key] += 1
        if entry["status"] != "ok":
            failed[key] += 1
    return {key: (failed[key], totals[key]) for key in sorted(totals)}


def main(argv: list[str] | None = None) -> int:
    argument_parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    argument_parser.add_argument(
        "inputs", nargs="*", type=Path, help=f"files or dirs (default {data_dir() / 'replays'})"
    )
    argument_parser.add_argument("--out", type=Path, default=data_dir() / "parsed")
    argument_parser.add_argument("--parser", type=Path, default=default_parser())
    argument_parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    argument_parser.add_argument(
        "--zstd-level",
        type=int,
        default=ZSTD_LEVEL,
        help=f"compression level (default {ZSTD_LEVEL}: about 4 s per replay; 9 for quick runs)",
    )
    argument_parser.add_argument(
        "--force", action="store_true", help="re-parse replays already done"
    )
    args = argument_parser.parse_args(argv)

    if not args.parser.exists():
        print(f"parser not found at {args.parser}; run parser/fetch.sh first", file=sys.stderr)
        return 2
    replays = find_replays(args.inputs or [data_dir() / "replays"])
    args.out.mkdir(parents=True, exist_ok=True)
    index = read_index(args.out)
    replays_to_parse = [
        replay
        for replay in replays
        if args.force
        or index.get(replay.name, {}).get("status") != "ok"
        or not output_path(args.out, replay).exists()
    ]
    print(f"{len(replays)} replays, {len(replays_to_parse)} to parse", file=sys.stderr)

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [
            pool.submit(process_one, args.parser, replay, args.out, args.zstd_level)
            for replay in replays_to_parse
        ]
        for future in as_completed(futures):
            entry = future.result()
            results.append(entry)
            index[entry["file"]] = entry
            status = entry["status"] if entry["status"] == "ok" else entry["error"]
            print(f"{entry['seconds']:7.2f}s {entry['file']}: {status}", file=sys.stderr)
            if len(results) % 50 == 0:
                write_index(args.out, index)
    write_index(args.out, index)
    if results:
        print(summarize(results), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
