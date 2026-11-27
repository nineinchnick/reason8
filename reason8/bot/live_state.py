"""The live state the opening script logged, compared with the state export of the same game.

With our BARb library the opening script reads the game as it is (``ai/native/LiveState.h``)
and logs it at every commander step and every 30 s of game time::

    Reason8 opening: team 0: state at frame 673: wind 13.2594, metal 533.997 of 1100 +2
    -20.0029, energy 559.982 of 1100 +30 -38.0055, standing armcom 1, armlab 1

The state export (`reason8 headless run --snapshots`) writes the wind and every team's
resources once a second and the units every 5 seconds. `compare` puts each logged line next
to the last resource line at or before its frame (within a second), and the standing units
next to the last snapshot, so that a run shows the script reads what the game holds.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable

STATE_LINE = re.compile(
    r"state at frame (\d+): wind (\S+), metal (\S+) of (\S+) \+(\S+) -(\S+), "
    r"energy (\S+) of (\S+) \+(\S+) -(\S+), standing ?(.*)"
)
#: Logged fields, and their place in a team's row of a resource line
#: ([team, metal, metal storage, metal income, metal expense, energy, ...]).
FIELDS = {
    "metal": 1,
    "metal_storage": 2,
    "metal_income": 3,
    "metal_expense": 4,
    "energy": 5,
    "energy_storage": 6,
    "energy_income": 7,
    "energy_expense": 8,
}
#: A resource line is written every second; a logged line is compared with one this close.
NEAREST_FRAMES = 30


def parse_standing(text: str) -> dict[str, int]:
    """``armcom 1, armmex 3`` as a dict."""
    standing = {}
    for part in text.split(", "):
        if part.strip():
            name, count = part.rsplit(" ", 1)
            standing[name] = int(count)
    return standing


def parse_line(text: str) -> dict | None:
    """One ``state at frame ...`` message (after ``team N: ``), or None."""
    match = STATE_LINE.fullmatch(text.strip())
    if not match:
        return None
    values = [float(value) for value in match.groups()[1:10]]
    names = ("wind", *FIELDS)
    return {
        "frame": int(match.group(1)),
        **dict(zip(names, values, strict=True)),
        "standing": parse_standing(match.group(11)),
    }


def compare(lines: list[dict], records: Iterable[dict], team: int) -> dict:
    """How the logged values of one team differ from the export at the nearest earlier line.

    `records` are the state file's records with snapshots (`reason8.headless.state`
    ``read_records(path, snapshots=True)``).
    """
    resources: list[dict] = []
    snapshots: list[tuple[int, Counter]] = []
    names: dict[str, str] = {}
    for record in records:
        if record["t"] == "header":
            names = record["unitdefs"]
        elif record["t"] == "r":
            resources.append(record)
        elif record["t"] == "s":
            finished = Counter(
                names.get(str(unit[1]), str(unit[1]))
                for unit in record["units"]
                if unit[2] == team and unit[6] is not None and unit[6] >= 100
            )
            snapshots.append((record["f"], finished))
    differences: dict[str, list[float]] = {name: [] for name in ("wind", *FIELDS)}
    compared = standing_equal = standing_compared = 0
    for line in lines:
        before = [record for record in resources if record["f"] <= line["frame"]]
        if before and line["frame"] - before[-1]["f"] < NEAREST_FRAMES:
            record = before[-1]
            row = next((row for row in record["teams"] if row[0] == team), None)
            if row is not None:
                compared += 1
                differences["wind"].append(abs(line["wind"] - record["wind"]))
                for name, index in FIELDS.items():
                    differences[name].append(abs(line[name] - row[index]))
        earlier = [counts for frame, counts in snapshots if frame <= line["frame"]]
        if earlier:
            standing_compared += 1
            standing_equal += dict(earlier[-1]) == line["standing"]
    return {
        "lines": len(lines),
        "compared": compared,
        "median_difference": {
            name: round(statistics.median(values), 3) if values else None
            for name, values in differences.items()
        },
        "standing_compared": standing_compared,
        # the same units as the last snapshot (written every 5 s, so not always)
        "standing_equal": standing_equal,
    }
