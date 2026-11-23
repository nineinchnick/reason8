"""Read replays parsed by `reason8 parse` (see docs/reference/replay-format.md)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from compression import zstd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reason8.replays.sdfz import GAME_SPEED as GAME_SPEED

FORMAT = "reason8.replay/1"

# Factory order multipliers (Recoil CFactoryCAI): shift x5, ctrl x20, both x100.
SHIFT_MULTIPLIER = 5
CTRL_MULTIPLIER = 20


@dataclass(frozen=True)
class Team:
    team_id: int
    ally_team_id: int
    faction: str | None
    is_ai: bool
    player_ids: tuple[int, ...]
    start_pos: tuple[float, float] | None  # (x, z)


@dataclass(frozen=True)
class BuildOrder:
    """One BUILD command as the player gave it. An order, not a finished unit."""

    frame: int
    team: int | None
    player: int
    unit: str | None
    kind: str  # "structure" (placed on the map) or "factory" (unit production)
    via: str  # COMMAND, AICOMMAND or AICOMMANDS
    builders: tuple[int, ...] | None  # unit ids; None means the player's current selection
    x: float | None = None
    z: float | None = None
    facing: int | None = None
    count: int = 1  # factory: units added (negative: removed from the queue)
    queued: bool = False  # shift: appended; a structure order without it replaces the queue
    inserted: bool = False  # came from an INSERT command (placed inside the queue)
    quota: bool = False  # inserted by BAR's factory-quota widget, not clicked by the player
    opts: tuple[str, ...] = ()


@dataclass
class Replay:
    doc: dict[str, Any] = field(repr=False)

    @property
    def meta(self) -> dict[str, Any]:
        return self.doc["meta"]

    @property
    def players(self) -> list[dict[str, Any]]:
        return self.doc["players"]

    @property
    def ais(self) -> list[dict[str, Any]]:
        return self.doc["ais"]

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.doc["events"]

    @property
    def statistics(self) -> dict[str, Any]:
        return self.doc.get("statistics") or {}

    @property
    def winning_ally_teams(self) -> list[int]:
        return self.meta.get("winningAllyTeamIds") or []

    @property
    def end_frame(self) -> int | None:
        return self.meta.get("endFrame")

    def teams(self) -> dict[int, Team]:
        teams: dict[int, Team] = {}
        for player in self.players:
            team_id = player["teamId"]
            previous = teams.get(team_id)
            start_pos = player.get("startPos")
            teams[team_id] = Team(
                team_id=team_id,
                ally_team_id=player["allyTeamId"],
                faction=player.get("faction"),
                is_ai=False,
                player_ids=(previous.player_ids if previous else ()) + (player["playerId"],),
                start_pos=(start_pos["x"], start_pos["z"]) if start_pos else None,
            )
        for ai in self.ais:
            start_pos = ai.get("startPos")
            teams[ai["teamId"]] = Team(
                team_id=ai["teamId"],
                ally_team_id=ai["allyTeamId"],
                faction=ai.get("faction"),
                is_ai=True,
                player_ids=(),
                start_pos=(start_pos["x"], start_pos["z"]) if start_pos else None,
            )
        return dict(sorted(teams.items()))

    def team_stats(self) -> dict[int, list[dict[str, Any]]]:
        """End-of-game `teamStats` per team id (keys are strings in the JSON)."""
        return {
            int(team_id): stats
            for team_id, stats in (self.statistics.get("teamStats") or {}).items()
        }

    def events_of(self, *types: str) -> Iterator[dict[str, Any]]:
        wanted = set(types)
        return (event for event in self.events if event["type"] in wanted)

    def commands(self, *names: str) -> Iterator[dict[str, Any]]:
        """Command events, optionally only those with the given command names."""
        wanted = set(names)
        for event in self.events:
            if event["type"] == "cmd" and (not wanted or event["cmd"] in wanted):
                yield event

    def build_orders(
        self, team: int | None = None, until_frame: int | None = None
    ) -> list[BuildOrder]:
        """BUILD commands in stream order, including ones nested in INSERT.

        Each element is what the player *ordered*. Orders can be dequeued (factory
        right-click, negative `count`), replaced (a structure order without shift),
        removed (`REMOVE`/`STOP` commands) or never started; see docs/reference/replay-format.md.
        """
        orders: list[BuildOrder] = []
        for event in self.commands("BUILD", "INSERT"):
            if (
                until_frame is not None
                and event["frame"] is not None
                and event["frame"] > until_frame
            ):
                break
            if team is not None and event.get("team") != team:
                continue
            if event["cmd"] == "INSERT":
                inner = event.get("inner") or {}
                if inner.get("cmd") != "BUILD":
                    continue
                order = _build_order(event, inner, inserted=True)
            else:
                order = _build_order(event, event, inserted=False)
            orders.append(order)
        return orders


def _build_order(event: dict[str, Any], command: dict[str, Any], *, inserted: bool) -> BuildOrder:
    params = command.get("params") or []
    options = tuple(command.get("opts") or ())
    outer_options = tuple(event.get("opts") or ())
    structure = len(params) >= 3
    count = 1
    if not structure:
        if "shift" in options:
            count *= SHIFT_MULTIPLIER
        if "ctrl" in options:
            count *= CTRL_MULTIPLIER
        if "right" in options:
            count = -count
    units = event.get("units")
    return BuildOrder(
        frame=event["frame"],
        team=event.get("team"),
        player=event["player"],
        unit=command.get("unit"),
        kind="structure" if structure else "factory",
        via=event["via"],
        builders=tuple(units) if units is not None else None,
        x=params[0] if structure else None,
        z=params[2] if structure else None,
        facing=int(params[3]) if structure and len(params) > 3 else None,
        count=count,
        queued="shift" in options,
        inserted=inserted,
        # BAR's factory-quota widget sends INSERT{alt,ctrl} of BUILD{alt,internal}.
        quota=inserted and "internal" in options and "ctrl" in outer_options,
        opts=options,
    )


def load_replay(path: str | Path) -> Replay:
    path = Path(path)
    if path.suffix == ".zst":
        document = json.loads(zstd.decompress(path.read_bytes()))
    else:
        document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != FORMAT:
        raise ValueError(f"{path}: unsupported format {document.get('format')!r}")
    return Replay(document)


def iter_replays(directory: str | Path) -> Iterator[Replay]:
    """All parsed replays in a directory (as written by `reason8 parse`)."""
    for path in sorted(Path(directory).glob("*.json.zst")):
        yield load_replay(path)
