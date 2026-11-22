"""BAR's map metadata: recommended start positions and default start boxes per map.

Usage::

    uv run python -m reason8.map_metadata     # fetch the pinned map list into the data dir

BAR keeps a list of its maps in the `maps-metadata` repository (``map_list.yaml``). For each
map it holds the start positions the game recommends, with a role each, for one or more
layouts (a number of teams and a team size), whether the game shows them by default, and
the default start boxes per number of teams. The lobby sends the same data to every game
in lobby options (``mapmetadata_startpos``, ``mapmetadata_startboxes_set``,
``mapmetadata_startbox_override``), so a replay records what its game used.

The list is not kept in this repository: it is fetched at a pinned commit into
``<data dir>/maps-metadata/`` and read from there, which keeps it current and every run
reproducible. See docs/adr/0015-take-positions-from-the-map-metadata.md.
"""

from __future__ import annotations

import base64
import binascii
import functools
import json
import os
import sys
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from reason8.match_dumps import data_dir

REPOSITORY = "beyond-all-reason/maps-metadata"
#: The commit of maps-metadata we read. Move it on purpose: recommended positions and
#: default boxes change (Supreme Isthmus got new default boxes in November 2026).
COMMIT = "7953bf6e00180061f65db8255a579453fc0870c1"
MAP_LIST_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/map_list.yaml"
DIRECTORY = "maps-metadata"
#: Start boxes are drawn on a grid of this many units per map side.
BOX_GRID = 200

Point = tuple[float, float]  # (x, z) in map units (elmos)


@dataclass(frozen=True)
class SpawnPoint:
    """One recommended start position."""

    id: str  # the list's name for the point, e.g. "P2"
    x: float
    z: float
    role: str | None  # front, tech, air, sea, or two of them such as front/tech


@dataclass(frozen=True)
class Layout:
    """The recommended start positions for one number of teams and one team size."""

    team_count: int
    players_per_team: int
    sides: tuple[tuple[SpawnPoint, ...], ...]  # one tuple of spawn points per team


@dataclass(frozen=True)
class StartPositions:
    """The layouts of recommended start positions of one map."""

    layouts: tuple[Layout, ...]

    def layout_for(self, team_count: int, players_per_team: int) -> Layout | None:
        """The layout for a game of this shape, chosen as the game chooses it: exact match."""
        for layout in self.layouts:
            if layout.team_count == team_count and layout.players_per_team == players_per_team:
                return layout
        return None


#: A start box: the corner points of a polygon on the box grid, each with the strength of
#: the curve through it (None for a plain corner). Two points are the corners of a rectangle.
Box = tuple[tuple[float, float, float | None], ...]


@dataclass(frozen=True)
class MapMetadata:
    """What the map list says about the starts of one map."""

    start_positions: StartPositions | None
    overlay_default: bool | None  # the game shows the recommended positions by default
    start_boxes: Mapping[int, tuple[Box, ...]]  # default boxes by number of teams


def parse_start_positions(document: Any) -> StartPositions | None:
    """Read ``startPos`` of the map list, or a decoded ``mapmetadata_startpos`` option."""
    if not isinstance(document, Mapping):
        return None
    points = document.get("positions") or {}
    layouts = []
    for entry in document.get("team") or []:
        sides = []
        for side in entry.get("sides") or []:
            spawn_points = []
            for start in side.get("starts") or []:
                point = points.get(start.get("spawnPoint"))
                if point is None:
                    continue
                # the list calls the second map axis y; it is the engine's z
                spawn_points.append(
                    SpawnPoint(start["spawnPoint"], point["x"], point["y"], start.get("role"))
                )
            sides.append(tuple(spawn_points))
        layouts.append(Layout(entry["teamCount"], entry["playersPerTeam"], tuple(sides)))
    return StartPositions(tuple(layouts)) if layouts else None


def parse_boxes(arrangement: Any) -> tuple[Box, ...] | None:
    """Read one arrangement of start boxes (``{"startboxes": [{"poly": [...]}, ...]}``)."""
    if not isinstance(arrangement, Mapping) or not arrangement.get("startboxes"):
        return None
    return tuple(
        tuple((point["x"], point["y"], point.get("strength")) for point in box["poly"])
        for box in arrangement["startboxes"]
    )


def parse_box_sets(document: Any) -> dict[int, tuple[Box, ...]]:
    """Default boxes by number of teams, from the map list or the lobby option.

    The map list keys its arrangements by an opaque id; the number of teams is the number
    of boxes. The ``mapmetadata_startboxes_set`` option keys them by the number of teams.
    """
    found: dict[int, tuple[Box, ...]] = {}
    if isinstance(document, Mapping):
        for key, arrangement in document.items():
            boxes = parse_boxes(arrangement)
            if boxes:
                found[int(key) if str(key).isdigit() else len(boxes)] = boxes
    return found


def bounding_box(box: Box) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) of a box, as fractions of the map."""
    xs = [point[0] / BOX_GRID for point in box]
    ys = [point[1] / BOX_GRID for point in box]
    return (min(xs), min(ys), max(xs), max(ys))


def decode_option(value: str | None) -> Any:
    """A lobby option in the game's ``base64url(zlib(json))`` format; None when it is not."""
    if not value:
        return None
    try:
        packed = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        return json.loads(zlib.decompress(packed))
    except binascii.Error, zlib.error, ValueError:
        return None


def encode_option(document: Any) -> str:
    """The inverse of `decode_option`."""
    packed = zlib.compress(json.dumps(document, separators=(",", ":")).encode("utf-8"))
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def map_list_path(directory: Path | None = None) -> Path:
    """Where the pinned map list is cached."""
    return (directory or data_dir() / DIRECTORY) / f"map_list-{COMMIT[:12]}.yaml"


def fetch_map_list(directory: Path | None = None, client: httpx.Client | None = None) -> Path:
    """Download the pinned map list unless it is already cached; return its path."""
    from reason8.download import make_client

    path = map_list_path(directory)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".part")
    with client or make_client() as http:
        response = http.get(MAP_LIST_URL)
        response.raise_for_status()
        temporary_path.write_bytes(response.content)
    os.replace(temporary_path, path)
    return path


def parse_map_list(text: str) -> dict[str, MapMetadata]:
    """The start data of every map of a map list, by the map's engine name."""
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    document = yaml.load(text, Loader=loader) or {}
    maps = {}
    for entry in document.values():
        name = entry.get("springName")
        if name:
            maps[name] = MapMetadata(
                start_positions=parse_start_positions(entry.get("startPos")),
                overlay_default=entry.get("startPosActive"),
                start_boxes=parse_box_sets(entry.get("startboxesSet")),
            )
    return maps


@functools.lru_cache(maxsize=4)
def _load(path: Path) -> dict[str, MapMetadata]:
    return parse_map_list(path.read_text(encoding="utf-8"))


def load_map_list(path: Path | None = None) -> dict[str, MapMetadata]:
    """The cached map list; empty when it has not been fetched.

    Reading never touches the network: run ``python -m reason8.map_metadata`` once.
    """
    path = path or map_list_path()
    return _load(path) if path.exists() else {}


def main(argv: Sequence[str] | None = None) -> int:
    path = fetch_map_list()
    maps = load_map_list(path)
    with_positions = sum(metadata.start_positions is not None for metadata in maps.values())
    print(f"{path}: {len(maps)} maps, {with_positions} with recommended start positions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
