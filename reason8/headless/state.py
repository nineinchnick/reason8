"""Read a state file written by reason8_state_export.lua and summarise it.

    uv run reason8 headless state STATE.jsonl[.gz] [--builds]

The file is JSON lines (see the widget for the fields):
    {"t":"header", ...}           game, map, wind range, teams, unitDefID -> name, static types
    {"t":"r","f":frame,"wind":strength,"teams":[...]}   resources, every second (format 5)
    {"t":"s","f":frame,"units":[...]}   one snapshot (to format 4 also "wind" and "teams")
    {"t":"created"|"finished"|"destroyed"|"given"|"idle", "f":frame, "u":unitID, ...}
    {"t":"hit","f":frame,"u":unitID,...,"by":unitID,"by_team":team}   first hit by an enemy
    {"t":"damage","f":frame,"team":team,"by_team":team,"hits":n,"damage":sum}   per second
    {"t":"fdef","d":featureDefID,"name":...}   a feature type, before its first feature (format 6)
    {"t":"fcreated"|"fdestroyed","f":frame,"id":featureID,...}   a reclaimable feature
    {"t":"reclaim","f":frame,"id":featureID,"team":team,"metal":m,"energy":e}   reclaimed
    {"t":"work","f":frame,"u":unitID,"team":team,"task":...}   a builder's work changed
    {"t":"los"|"radar","f":frame,"u":unitID,"ally":allyTeam,"in":bool,"x":x,"z":z}   an
        enemy unit entered or left an ally team's sight or radar (format 7)
    {"t":"end","f":frame,"reason":...,"winners":[allyTeam,...],"attackers":...}

`read_records()` reads every format the same way, from the JSON lines or from the Parquet
tables of a game (`reason8.headless.tables`).

Prints sizes (raw and gzip) and counts as JSON. With --builds it also prints,
per team, the first units that were *finished* (not just ordered), which is
what a replay's command stream alone cannot tell.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from reason8.paths import partitioned_path

#: The state of a replay is kept as date=<date>/<replay name>.jsonl.gz (see `reason8 headless
#: batch`).
STATE_SUFFIX = ".jsonl.gz"
SNAPSHOT_TEAM_FIELDS = (
    "team",
    "metal",
    "metal_storage",
    "metal_income",
    "metal_expense",
    "energy",
    "energy_storage",
    "energy_income",
    "energy_expense",
)
EVENT_KINDS = (
    "created",
    "finished",
    "destroyed",
    "given",
    "idle",
    "hit",
    "damage",
    "fcreated",
    "fdestroyed",
    "reclaim",
    "work",
    "los",
    "radar",
)
#: From this format on resources are lines of their own ("r") and snapshots leave out
#: finished units that cannot move (the header lists their types as "static").
RESOURCE_LINES_FORMAT = 5
SNAPSHOT_KINDS = ("s", "r")
SNAPSHOT_UNIT_FIELDS = ("unit_id", "unit_def_id", "team", "x", "z", "health_pct", "build_pct")


def state_path(out_dir: Path, replay: Path) -> Path:
    """Where the state of a replay is kept: the replay's name, as JSON lines, gzipped, in the
    date partition of the replay (`reason8.paths.partitioned_path`)."""
    return partitioned_path(out_dir, replay.stem + STATE_SUFFIX)


def read_lines(path: str | Path, snapshots: bool = False) -> Iterator[dict]:
    """The lines of a state file (plain or .gz) as they were written.

    Snapshot and resource lines are most of a file and are skipped unless asked for. A
    last line that was cut off (the engine was killed) is left out.
    """
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as file:
        for line in file:
            if not snapshots and line.startswith(('{"t":"s"', '{"t":"r"')):
                continue
            if not line.endswith("}\n"):
                return
            yield json.loads(line)


def read_records(path: str | Path, snapshots: bool = False) -> Iterator[dict]:
    """The records of a game's state, in the same shape for every format.

    `path` is a state file (.jsonl or .jsonl.gz) or one of the Parquet tables of a game
    (`reason8.headless.tables`). With `snapshots`, every snapshot has the wind, the
    resources of every team and every unit, as up to format 4: from format 5 on the wind
    and resources come from the resource line of the same frame, and the finished units
    that cannot move from the unit lines before it, with an unknown health (None). The
    resource lines themselves ("r") come too.
    """
    if str(path).endswith(".parquet"):
        from reason8.headless import tables

        records = tables.read_table_records(path, snapshots)
    else:
        records = read_lines(path, snapshots)
    header = next(records, None)
    if header is None:
        return
    yield header
    if not snapshots or header.get("v", 1) < RESOURCE_LINES_FORMAT:
        yield from records
        return
    yield from complete_snapshots(header, records)


def complete_snapshots(header: dict, records: Iterator[dict]) -> Iterator[dict]:
    """Records of format 5 and later, with each snapshot made whole (see `read_records`)."""
    static = set(header.get("static", ()))
    buildings: dict[int, list] = {}  # unit id -> [unit, type, team, x, z, finished]
    resources: dict | None = None
    for record in records:
        kind = record["t"]
        if kind == "created":
            if record["d"] in static:
                buildings[record["u"]] = [
                    record["u"],
                    record["d"],
                    record["team"],
                    record["x"],
                    record["z"],
                    False,
                ]
            else:
                buildings.pop(record["u"], None)  # a unit id is used again
        elif kind == "finished" and record["u"] in buildings:
            buildings[record["u"]][5] = True
        elif kind == "given" and record["u"] in buildings:
            buildings[record["u"]][2] = record["team"]
        elif kind == "destroyed":
            buildings.pop(record["u"], None)
        elif kind == "r":
            resources = record
        elif kind == "s":
            listed = {unit[0] for unit in record["units"]}
            units = list(record["units"]) + [
                [unit_id, unit_def_id, team, x, z, None, 100]
                for unit_id, unit_def_id, team, x, z, done in buildings.values()
                if done and unit_id not in listed
            ]
            units.sort(key=lambda unit: unit[0])
            same_frame = resources is not None and resources["f"] == record["f"]
            record = {
                "t": "s",
                "f": record["f"],
                "wind": resources["wind"] if same_frame else None,
                "teams": resources["teams"] if same_frame else [],
                "units": units,
            }
        yield record


def summarise(path: str | Path, builds: int = 0) -> dict:
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    counts: Counter[str] = Counter()
    bytes_by_kind: Counter[str] = Counter()
    header: dict = {}
    end: dict = {}
    max_units = 0
    unit_rows = 0
    finished: dict[int, list[tuple[int, int]]] = {}
    truncated = False
    lines = [line for line in raw.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        try:
            record = json.loads(line)
        except ValueError:
            if i < len(lines) - 1:
                raise
            truncated = True  # the engine was killed while writing the last line
            break
        kind = record["t"]
        counts[kind] += 1
        bytes_by_kind[kind] += len(line) + 1
        if kind == "header":
            header = record
        elif kind == "end":
            end = record
        elif kind == "s":
            max_units = max(max_units, len(record["units"]))
            unit_rows += len(record["units"])
        elif kind == "finished":
            finished.setdefault(record["team"], []).append((record["f"], record["d"]))

    frames = end.get("f", 0)
    summary = {
        "game": header.get("game"),
        "map": header.get("map"),
        "engine": header.get("engine"),
        "teams": len([team for team in header.get("teams", []) if not team.get("gaia")]),
        "frames": frames,
        "game_minutes": round(frames / 1800, 2),
        "complete": bool(end) and not truncated,
        "end_reason": end.get("reason"),
        "winners": end.get("winners"),
        "snapshots": counts["s"],
        "resource_lines": counts["r"],
        "snapshot_frames": header.get("snapshot_frames"),
        "max_units": max_units,
        "unit_rows": unit_rows,
        "events": {kind: counts[kind] for kind in EVENT_KINDS},
        "attackers": end.get("attackers"),
        "bytes": len(raw),
        "bytes_gzip": len(gzip.compress(raw, 6)),
        "bytes_by_kind": dict(bytes_by_kind),
    }
    if frames:
        summary["bytes_gzip_per_game_minute"] = round(summary["bytes_gzip"] / (frames / 1800))
    if builds:
        names = header.get("unitdefs", {})
        summary["first_finished"] = {
            team: [
                f"{frame / 30:.0f}s {names.get(str(unit_def_id), unit_def_id)}"
                for frame, unit_def_id in rows[:builds]
            ]
            for team, rows in sorted(finished.items())
        }
    return summary


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("state", help="a state file (.jsonl or .jsonl.gz)")
    parser.add_argument(
        "--builds",
        type=int,
        nargs="?",
        const=10,
        default=0,
        metavar="N",
        help="also print the first N finished units per team (default 10)",
    )


def run(args: argparse.Namespace) -> int:
    print(json.dumps(summarise(args.state, args.builds), indent=1))
    return 0
