"""Start positions: which recommended start position a player took, and how the game began.

Usage::

    uv run reason8 maps fetch    # once: fetch the pinned map list
    uv run reason8 maps check    # how far real starts are from the recommended positions,
                                 # and how the games were set up
    uv run reason8 maps check --since 2026-10-14 --until 2026-10-28    # some days

The check reads the games and players tables of the parsed replays (`reason8 parse`).

BAR's map metadata recommends start positions per map, each with a role, and the game shows
them before the start. A player's *position* is the nearest recommended start position of
their team's side, taken from the game's own ``mapmetadata_startpos`` lobby option or, when
the game has none, from the pinned map list (`reason8.game.maps`). See
docs/decisions/0011-take-positions-from-the-map-metadata.md and docs/research/maps/.

`replay_positions()` is the one definition of a player's position, and `start_setup()` says
whether the game showed the recommended positions and used the map's default start boxes.
The dataset builder takes its columns from them.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from reason8.data.matches import DEFAULT_MAPS
from reason8.game.maps import (
    Box,
    Layout,
    MapMetadata,
    Point,
    StartPositions,
    bounding_box,
    decode_option,
    load_map_list,
    parse_box_sets,
    parse_boxes,
    parse_start_positions,
)
from reason8.replays import tables
from reason8.replays.replay import Replay

FROM_GAME = "game"  # the game's own lobby options
FROM_MAP_LIST = "map list"  # the pinned map list; the game may have used an older one


@dataclass(frozen=True)
class Position:
    """Where one player started, in terms of the recommended start positions."""

    spawn_point: str  # the position: the nearest recommended start position, e.g. "P10"
    role: str | None  # its role in the map metadata
    side: int  # which side of the layout the player's team is on
    index: int  # the spawn point's place in that side's list
    distance: float  # from the start to the spawn point, in map units
    on_spot: bool  # the start is nearer than half the way to the next spawn point


@dataclass(frozen=True)
class StartSetup:
    """How the start of one game was set up."""

    positions_source: str | None  # FROM_GAME, FROM_MAP_LIST, or None without positions
    overlay: bool  # the game showed the recommended start positions to the players
    default_boxes: bool | None  # the team areas are the map's default; None: cannot tell
    boxes_source: str | None  # where the default boxes come from


def game_shape(replay: Replay) -> tuple[int, int]:
    """(number of teams, size of the largest team), counted as the game counts them."""
    sizes = Counter(team.ally_team_id for team in replay.teams().values())
    return len(sizes), max(sizes.values(), default=0)


def _options(replay: Replay) -> Mapping[str, str]:
    return replay.doc.get("modoptions") or {}


def _map_metadata(replay: Replay, map_list: Mapping[str, MapMetadata] | None) -> MapMetadata | None:
    known = load_map_list() if map_list is None else map_list
    return known.get(replay.meta.get("map"))


def recommended_positions(
    replay: Replay, map_list: Mapping[str, MapMetadata] | None = None
) -> tuple[StartPositions | None, str | None]:
    """The recommended start positions of a replay's map, and where they come from.

    The game's own lobby option wins: it is what the players saw. `map_list` defaults to
    the cached pinned map list.
    """
    own = parse_start_positions(decode_option(_options(replay).get("mapmetadata_startpos")))
    if own is not None:
        return own, FROM_GAME
    metadata = _map_metadata(replay, map_list)
    if metadata is not None and metadata.start_positions is not None:
        return metadata.start_positions, FROM_MAP_LIST
    return None, None


def replay_layout(
    replay: Replay, map_list: Mapping[str, MapMetadata] | None = None
) -> tuple[Layout | None, str | None]:
    """The layout of recommended positions for this game's number of teams and team size."""
    positions, source = recommended_positions(replay, map_list)
    if positions is None:
        return None, None
    layout = positions.layout_for(*game_shape(replay))
    return (layout, source) if layout is not None else (None, None)


def _mean(points: Sequence[Point]) -> Point:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def team_sides(layout: Layout, starts: Mapping[int, Sequence[Point]]) -> dict[int, int]:
    """Which side of the layout each team is on: team (ally team) id -> index of the side.

    Teams are matched to sides by the distance from the mean of their start points to the
    middle of the side's spawn points, nearest pairs first, each side taken once. Which team
    gets which start box changes from game to game, so team ids say nothing.
    """
    middles = [_mean([(point.x, point.z) for point in side]) for side in layout.sides if side]
    pairs = sorted(
        (math.dist(_mean(points), middle), team, side)
        for team, points in starts.items()
        if points
        for side, middle in enumerate(middles)
    )
    sides: dict[int, int] = {}
    for _, team, side in pairs:
        if team not in sides and side not in sides.values():
            sides[team] = side
    return sides


def spot_radii(layout: Layout) -> dict[str, float]:
    """Per spawn point, half the distance to the nearest other spawn point of the layout."""
    points = [point for side in layout.sides for point in side]
    radii = {}
    for point in points:
        others = [
            math.dist((point.x, point.z), (other.x, other.z))
            for other in points
            if other.id != point.id
        ]
        radii[point.id] = min(others) / 2 if others else math.inf
    return radii


def replay_positions(
    replay: Replay, map_list: Mapping[str, MapMetadata] | None = None
) -> dict[int, Position]:
    """Position of every team (player or AI) of a parsed replay that has a start point.

    Empty when there are no recommended positions for the map and the game's number of
    teams and team size. Every other start gets the nearest spawn point of its team's side;
    `Position.on_spot` says whether it is close enough to be called a start there.
    """
    layout, _ = replay_layout(replay, map_list)
    if layout is None:
        return {}
    teams = replay.teams()
    starts: dict[int, list[Point]] = defaultdict(list)
    for team in teams.values():
        if team.start_pos is not None:
            starts[team.ally_team_id].append(team.start_pos)
    sides = team_sides(layout, starts)
    radii = spot_radii(layout)
    positions = {}
    for team in teams.values():
        side = sides.get(team.ally_team_id)
        if team.start_pos is None or side is None:
            continue
        positions[team.team_id] = position_of(layout, side, team.start_pos, radii)
    return positions


def position_of(
    layout: Layout, side: int, start: Point, radii: Mapping[str, float] | None = None
) -> Position:
    """The position of a start on one side of a layout: its nearest spawn point there.

    `radii` are the layout's `spot_radii`, computed when not given.
    """
    radii = spot_radii(layout) if radii is None else radii
    nearest = min(layout.sides[side], key=lambda point: math.dist(start, (point.x, point.z)))
    distance = math.dist(start, (nearest.x, nearest.z))
    return Position(
        spawn_point=nearest.id,
        role=nearest.role,
        side=side,
        index=layout.sides[side].index(nearest),
        distance=distance,
        on_spot=distance < radii[nearest.id],
    )


def _resolve_boxes(sets: Mapping[int, tuple[Box, ...]], team_count: int) -> tuple[Box, ...] | None:
    """The arrangement the game uses for a number of teams: exact, else larger, else smaller."""
    if team_count in sets:
        return sets[team_count]
    larger = [count for count in sets if count > team_count]
    smaller = [count for count in sets if count < team_count]
    if larger:
        return sets[min(larger)]
    return sets[max(smaller)] if smaller else None


def _rounded(rectangle: Sequence[float]) -> tuple[float, ...]:
    return tuple(round(value, 3) for value in rectangle)


def start_boxes(replay: Replay) -> list[tuple[float, ...]]:
    """(left, top, right, bottom) of the start box of every team with players, as fractions."""
    in_use = {team.ally_team_id for team in replay.teams().values()}
    return sorted(
        _rounded([box[side] for side in ("left", "top", "right", "bottom")])
        for ally_team in replay.doc.get("allyTeams") or []
        if ally_team.get("allyTeamId") in in_use and (box := ally_team.get("startBox"))
    )


def default_boxes(
    replay: Replay, map_list: Mapping[str, MapMetadata] | None = None
) -> tuple[bool | None, str | None]:
    """Whether the teams' start areas are the map's default, and the default's source.

    The default is the arrangement for the game's number of teams in the game's own
    ``mapmetadata_startboxes_set`` option or, without it, in the pinned map list. The areas
    are the default when no ``mapmetadata_startbox_override`` changes them and every team's
    start box in the replay is the bounding box of a default box.

    Against the pinned map list a difference proves nothing, because the list may have
    changed since the game: the answer is then None.
    """
    team_count, _ = game_shape(replay)
    options = _options(replay)
    source = FROM_GAME
    default = _resolve_boxes(
        parse_box_sets(decode_option(options.get("mapmetadata_startboxes_set"))), team_count
    )
    if default is None:
        metadata = _map_metadata(replay, map_list)
        source = FROM_MAP_LIST
        default = _resolve_boxes(metadata.start_boxes, team_count) if metadata else None
    actual = start_boxes(replay)
    if default is None or len(actual) < team_count:
        return None, None
    allowed = Counter(_rounded(bounding_box(box)) for box in default)
    same = not Counter(actual) - allowed
    override = parse_boxes(decode_option(options.get("mapmetadata_startbox_override")))
    if override is not None and len(override) >= team_count:
        same = same and Counter(override) == Counter(default)
    if not same and source == FROM_MAP_LIST:
        return None, source
    return same, source


def start_setup(replay: Replay, map_list: Mapping[str, MapMetadata] | None = None) -> StartSetup:
    """Where the game's positions come from, whether it showed them, and its start boxes.

    The game shows the recommended positions when its ``mapmetadata_startpos`` option holds
    a layout for its number of teams and team size. A player can still switch the display
    off in their own settings; a replay does not record that.
    """
    _, positions_source = replay_layout(replay, map_list)
    is_default, boxes_source = default_boxes(replay, map_list)
    return StartSetup(
        positions_source=positions_source,
        overlay=positions_source == FROM_GAME,
        default_boxes=is_default,
        boxes_source=boxes_source,
    )


def position_order(name: str) -> tuple[int, str]:
    """Sort key that puts P2 before P10."""
    digits = re.search(r"\d+", name)
    return (int(digits.group()) if digits else 0, name)


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({100 * part / whole:.1f}%)" if whole else "0 of 0"


def check(replays: Iterable[Replay], map_list: Mapping[str, MapMetadata] | None = None) -> str:
    """Per map: how the games were set up and how far starts are from the spawn points."""
    setups: dict[str, list[StartSetup]] = defaultdict(list)
    starts: dict[str, list[tuple[Position, StartSetup]]] = defaultdict(list)
    boxes: dict[str, Counter] = defaultdict(Counter)
    for replay in replays:
        map_name = replay.meta.get("map")
        setup = start_setup(replay, map_list)
        setups[map_name].append(setup)
        drawn = "; ".join(
            f"{left:g}-{right:g} x {top:g}-{bottom:g}"
            for left, top, right, bottom in start_boxes(replay)
        )
        boxes[map_name][(str(setup.default_boxes), str(setup.boxes_source), drawn)] += 1
        starts[map_name] += [(p, setup) for p in replay_positions(replay, map_list).values()]
    lines = []
    for map_name in sorted(setups):
        games = setups[map_name]
        lines += [f"## {map_name}", "", f"{len(games)} games"]
        for title, counts in (
            ("positions from", Counter(str(setup.positions_source) for setup in games)),
            ("positions shown in the game", Counter(setup.overlay for setup in games)),
            ("default start boxes", Counter(str(setup.default_boxes) for setup in games)),
            ("default boxes known from", Counter(str(setup.boxes_source) for setup in games)),
        ):
            listed = ", ".join(f"{value}: {n}" for value, n in sorted(counts.items(), key=str))
            lines.append(f"- {title}: {listed}")
        lines += ["", "| default boxes | compared with | start boxes (x, z ranges) | games |"]
        lines += ["| --- | --- | --- | --- |"]
        for (is_default, source, drawn), count in sorted(boxes[map_name].items()):
            lines.append(f"| {is_default} | {source} | {drawn} | {count} |")
        found = starts[map_name]
        if not found:
            lines += ["", "no recommended positions for these games", ""]
            continue
        lines += ["", f"starts on a spot: {_share(sum(p.on_spot for p, _ in found), len(found))}"]
        for title, test in (
            ("positions shown", lambda setup: setup.overlay),
            ("positions not shown", lambda setup: not setup.overlay),
            ("default boxes", lambda setup: setup.default_boxes is True),
            ("changed boxes", lambda setup: setup.default_boxes is False),
            ("boxes unknown", lambda setup: setup.default_boxes is None),
        ):
            group = [p for p, setup in found if test(setup)]
            if group:
                lines.append(f"- {title}: {_share(sum(p.on_spot for p in group), len(group))}")
        lines += ["", "| position | role | nearest starts | on the spot | median | 90% within |"]
        lines += ["| --- | --- | --- | --- | --- | --- |"]
        by_name: dict[str, list[Position]] = defaultdict(list)
        for position, _ in found:
            by_name[position.spawn_point].append(position)
        for name in sorted(by_name, key=position_order):
            group = by_name[name]
            distances = sorted(position.distance for position in group)
            on_spot = sum(position.on_spot for position in group)
            lines.append(
                f"| {name} | {group[0].role} | {len(group)} | {100 * on_spot / len(group):.1f}% "
                f"| {distances[len(distances) // 2]:.0f} "
                f"| {distances[int(0.9 * (len(distances) - 1))]:.0f} |"
            )
        lines.append("")
    return "\n".join(lines)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    tables.add_source_arguments(parser)
    parser.add_argument(
        "--map", action="append", help="map name; default: the maps of the training slice"
    )


def game_headers(source: tables.Source, maps: Iterable[str]) -> list[Replay]:
    """The games on `maps` without AIs, from the games and players tables, by replay name."""
    games = source.scan(tables.GAMES).filter(pl.col("map").is_in(list(maps))).collect()
    players = (
        source.scan(tables.PLAYERS).filter(pl.col("replay").is_in(games["replay"].implode()))
    ).collect()
    headers = tables.replay_headers(games, players)
    return [headers[name] for name in sorted(headers) if not headers[name].ais]


def run(args: argparse.Namespace) -> int:
    if not load_map_list():
        print("no map list: run `reason8 maps fetch` first", file=sys.stderr)
    source = tables.open_source(
        args.tables, since=args.since, until=args.until, tables=(tables.GAMES, tables.PLAYERS)
    )
    print(check(game_headers(source, args.map or DEFAULT_MAPS)))
    return 0
