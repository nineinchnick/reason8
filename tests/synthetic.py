"""Made-up map metadata and replays for tests: none of it describes a real map."""

from __future__ import annotations

import copy

from reason8.map_metadata import encode_option
from reason8.replay import Replay

MAP = "Test Valley 1.0"  # 10,000 x 10,000 map units, teams in opposite corners

#: Two recommended positions per side for 2v2, and a 1v1 layout with one each.
START_POSITIONS = {
    "positions": {
        "P1": {"x": 3000, "y": 7000},
        "P2": {"x": 1000, "y": 9000},
        "P3": {"x": 7000, "y": 3000},
        "P4": {"x": 9000, "y": 1000},
    },
    "team": [
        {
            "teamCount": 2,
            "playersPerTeam": 2,
            "sides": [
                {
                    "starts": [
                        {"spawnPoint": "P1", "role": "front"},
                        {"spawnPoint": "P2", "role": "air"},
                    ]
                },
                {
                    "starts": [
                        {"spawnPoint": "P3", "role": "front"},
                        {"spawnPoint": "P4", "role": "air"},
                    ]
                },
            ],
        },
        {
            "teamCount": 2,
            "playersPerTeam": 1,
            "sides": [
                {"starts": [{"spawnPoint": "P1", "role": "front"}]},
                {"starts": [{"spawnPoint": "P3", "role": "front"}]},
            ],
        },
    ],
}

#: Default start boxes for two teams: the bottom-left and the top-right quarter.
BOX_SETS = {
    "2": {
        "maxPlayersPerStartbox": 2,
        "startboxes": [
            {"poly": [{"x": 0, "y": 100}, {"x": 100, "y": 200}]},
            {"poly": [{"x": 100, "y": 0}, {"x": 200, "y": 100}]},
        ],
    }
}

#: The same data as an entry of a map list file.
MAP_LIST_YAML = f"""
madeUpId:
  springName: {MAP}
  startPosActive: true
  startPos:
    positions:
      P1: {{x: 3000, y: 7000}}
      P2: {{x: 1000, y: 9000}}
      P3: {{x: 7000, y: 3000}}
      P4: {{x: 9000, y: 1000}}
    team:
      - teamCount: 2
        playersPerTeam: 2
        sides:
          - starts:
              - {{role: front, spawnPoint: P1}}
              - {{role: air, spawnPoint: P2}}
          - starts:
              - {{role: front, spawnPoint: P3}}
              - {{role: air, spawnPoint: P4}}
  startboxesSet:
    anotherMadeUpId:
      maxPlayersPerStartbox: 2
      startboxes:
        - poly: [{{x: 0, y: 100}}, {{x: 100, y: 200}}]
        - poly: [{{x: 100, y: 0}}, {{x: 200, y: 100}}]
noStartData:
  springName: Empty Plains 2.0
"""


# --- replays, for the tests of positions

#: The default start boxes as a replay records them.
BOTTOM_LEFT = {"left": 0, "top": 0.5, "right": 0.5, "bottom": 1}
TOP_RIGHT = {"left": 0.5, "top": 0, "right": 1, "bottom": 0.5}


def replay(
    sides: dict[int, list[tuple[float, float]]],
    *,
    map_name: str = MAP,
    options: dict[str, str] | None = None,
    boxes: dict[int, dict[str, float]] | None = None,
) -> Replay:
    """A parsed replay with only what positions need: `sides` is ally team -> start points."""
    players = []
    for ally_team_id, starts in sides.items():
        for x, z in starts:
            team_id = len(players)
            players.append(
                {
                    "playerId": team_id,
                    "teamId": team_id,
                    "allyTeamId": ally_team_id,
                    "startPos": {"x": x, "y": 0.0, "z": z},
                }
            )
    ally_teams = [
        {
            "allyTeamId": ally_team_id,
            "startBox": box,
            "playerCount": len(sides.get(ally_team_id, [])),
        }
        for ally_team_id, box in (boxes or {}).items()
    ]
    return Replay(
        {
            "meta": {"map": map_name},
            "allyTeams": ally_teams,
            "players": players,
            "ais": [],
            "modoptions": options or {},
            "events": [],
        }
    )


def start_options(positions=START_POSITIONS, box_sets=BOX_SETS, override=None) -> dict[str, str]:
    """Lobby options as the lobby sends them; pass None to leave one out."""
    options = {}
    if positions is not None:
        options["mapmetadata_startpos"] = encode_option(positions)
    if box_sets is not None:
        options["mapmetadata_startboxes_set"] = encode_option(box_sets)
    if override is not None:
        options["mapmetadata_startbox_override"] = encode_option(override)
    return options


def with_own_starts_recommended(document: dict) -> dict:
    """A copy of a parsed replay whose recommended positions are made up from its own starts.

    Every player's start becomes a spawn point of their side with the role front, so the
    copy does not depend on what the real game's lobby sent.
    """
    document = copy.deepcopy(document)
    sides: dict[int, list[dict]] = {}
    for player in document["players"]:
        sides.setdefault(player["allyTeamId"], []).append(player)
    points = {}
    starts = []
    for players in sides.values():
        side = []
        for player in players:
            name = f"P{len(points) + 1}"
            start = player["startPos"]
            points[name] = {"x": start["x"], "y": start["z"]}
            side.append({"spawnPoint": name, "role": "front"})
        starts.append({"starts": side})
    team_size = max(len(players) for players in sides.values())
    layout = {"teamCount": len(sides), "playersPerTeam": team_size, "sides": starts}
    document["modoptions"] = {
        **document.get("modoptions", {}),
        "mapmetadata_startpos": encode_option({"positions": points, "team": [layout]}),
    }
    return document
