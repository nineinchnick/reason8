"""Openings: what each player ordered at the start of a game.

The one definition of an opening that the measurements (`reason8.opening_shift`,
`reason8.map_meta`) and the training dataset share. An opening is the build orders a
player gave in the first `OPENING_SECONDS` of the game: orders, not finished units (see
docs/replay-format.md).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from reason8.map_metadata import MapMetadata
from reason8.positions import replay_positions
from reason8.replay import GAME_SPEED, BuildOrder, Replay

OPENING_SECONDS = 8 * 60
FACTION_PREFIXES = ("arm", "cor", "leg")
# First-tier factories by the part of the unit name after the faction prefix.
FACTORY_NAMES = {
    "lab": "bot lab",
    "vp": "vehicle plant",
    "ap": "aircraft plant",
    "sy": "shipyard",
    "hp": "hovercraft platform",
    "fhp": "hovercraft platform",
    "amsub": "amphibious complex",
    "plat": "seaplane platform",
}


@dataclass(frozen=True)
class Opening:
    """What one player ordered at the start of one game."""

    match: str
    team: int
    side: int  # ally team
    faction: str | None
    start: tuple[float, float] | None
    units: tuple[str, ...]
    position: str | None = None  # recommended start position taken (reason8.positions)
    role: str | None = None  # that position's role in the map metadata
    skill: float | None = None  # OpenSkill mu before the game
    frames: tuple[int, ...] = ()  # game frame of each order in `units`

    def until(self, seconds: float) -> Opening:
        """The same opening cut off after `seconds` of game time."""
        kept = sum(frame <= seconds * GAME_SPEED for frame in self.frames)
        return replace(self, units=self.units[:kept], frames=self.frames[:kept])


def opening_orders(replay: Replay, seconds: int = OPENING_SECONDS) -> dict[int, list[BuildOrder]]:
    """Every build order of the first `seconds` of the game per team, in stream order.

    Orders without a team or without a unit name are left out. Orders that take units out
    of a factory queue (negative `count`) are kept; `openings()` leaves them out.
    """
    by_team: dict[int, list[BuildOrder]] = defaultdict(list)
    for order in replay.build_orders(until_frame=seconds * GAME_SPEED):
        if order.team is not None and order.unit:
            by_team[order.team].append(order)
    return by_team


def openings(
    replay: Replay,
    seconds: int = OPENING_SECONDS,
    map_list: Mapping[str, MapMetadata] | None = None,
) -> list[Opening]:
    """The units each human player ordered in the first `seconds` of the game, in order.

    These are orders, not finished units (see docs/replay-format.md). Orders that take units
    out of a factory queue are left out. `position` is the recommended start position the
    player started on; it is None for a start that is on none of them and for games
    without recommended positions.
    """
    added = {
        team: [order for order in orders if order.count > 0]
        for team, orders in opening_orders(replay, seconds).items()
    }
    match = str(replay.meta.get("serverMatchId") or replay.meta.get("gameId"))
    positions = {
        team: position
        for team, position in replay_positions(replay, map_list).items()
        if position.on_spot
    }
    skills = {player["teamId"]: replay_skill(player.get("skill")) for player in replay.players}
    return [
        Opening(
            match=match,
            team=team.team_id,
            side=team.ally_team_id,
            faction=team.faction,
            start=team.start_pos,
            units=tuple(order.unit for order in added.get(team.team_id, [])),
            position=(positions[team.team_id].spawn_point if team.team_id in positions else None),
            role=positions[team.team_id].role if team.team_id in positions else None,
            skill=skills.get(team.team_id),
            frames=tuple(order.frame for order in added.get(team.team_id, [])),
        )
        for team in replay.teams().values()
        if not team.is_ai
    ]


def replay_skill(text: str | None) -> float | None:
    """OpenSkill mu from the replay's skill string, e.g. ``"[20.5]"`` or ``"~(12.3)"``."""
    found = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(found.group()) if found else None


def unit_role(unit: str) -> str:
    """Unit name without its faction prefix: ``armlab`` and ``corlab`` are both ``lab``."""
    return unit[3:] if unit.startswith(FACTION_PREFIXES) else unit


def first_factory(units: Iterable[str]) -> str:
    """Kind of the first factory ordered, e.g. ``"bot lab"``, or ``"none"``."""
    for unit in units:
        kind = FACTORY_NAMES.get(unit_role(unit))
        if kind:
            return kind
    return "none"


def opening_shape(units: Sequence[str], length: int = 4) -> tuple[str, ...]:
    """The first `length` distinct steps: roles in order, repeats of the same unit merged.

    ``armmex armmex armwin armwin armwin armlab armck`` becomes ``("mex", "win", "lab", "ck")``.
    """
    shape: list[str] = []
    for unit in units:
        role = unit_role(unit)
        if not shape or shape[-1] != role:
            shape.append(role)
            if len(shape) == length:
                break
    return tuple(shape)
