#!/usr/bin/env python3
"""Read a state file written by reason8_state_export.lua and summarise it.

    python tools/headless/state.py STATE.jsonl[.gz] [--builds]

The file is JSON lines (see the widget for the fields):
    {"t":"header", ...}                         game, map, wind range, teams, unitDefID -> name
    {"t":"s","f":frame,"wind":strength,"teams":[...],"units":[...]}   one snapshot
    {"t":"created"|"finished"|"destroyed"|"given", "f":frame, "u":unitID, ...}
    {"t":"hit","f":frame,"u":unitID,...,"by":unitID,"by_team":team}   first hit by an enemy
    {"t":"damage","f":frame,"team":team,"by_team":team,"hits":n,"damage":sum}   per second
    {"t":"end","f":frame,"reason":...,"winners":[allyTeam,...],"attackers":...}

Prints sizes (raw and gzip) and counts as JSON. With --builds it also prints,
per team, the first units that were *finished* (not just ordered), which is
what a replay's command stream alone cannot tell.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

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
EVENT_KINDS = ("created", "finished", "destroyed", "given", "hit", "damage")
SNAPSHOT_UNIT_FIELDS = ("unit_id", "unit_def_id", "team", "x", "z", "health_pct", "build_pct")


def read_lines(path: str | Path) -> Iterator[dict]:
    """Yield every record of a state file (plain or .gz)."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                yield json.loads(line)


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


def main(argv: list[str]) -> int:
    argument_parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    argument_parser.add_argument("state")
    argument_parser.add_argument("--builds", type=int, nargs="?", const=10, default=0, metavar="N")
    args = argument_parser.parse_args(argv)
    print(json.dumps(summarise(args.state, args.builds), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
