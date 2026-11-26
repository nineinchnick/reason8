"""Made-up map metadata and replays for tests: none of it describes a real map."""

from __future__ import annotations

import copy
import json
from compression import zstd
from pathlib import Path

from reason8.game.maps import encode_option
from reason8.replays import tables
from reason8.replays.parse import output_path
from reason8.replays.replay import FORMAT, Replay

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


# --- replays, for the tests of the commands tables


def _command(frame, player, team, command, *, via="COMMAND", units=None, **fields):
    event = {"frame": frame, "type": "cmd", "player": player, "via": via, "team": team}
    if via != "COMMAND":
        event["ai"] = fields.pop("ai", 255)
    if units is not None:
        event["units"] = list(units)
    return event | {"cmd": command} | fields


def command_replay(*, started: bool = True) -> Replay:
    """A parsed replay with every kind of build order and the events around them.

    Options are listed in the order the parser writes them (`reason8.replays.codes.OPTION_BITS`).

    Two players share team 0, a bot plays team 1. ``started=False`` gives a game that never
    started: every frame is None.
    """

    def frame(value):
        return value if started else None

    def build(unit, cmd_id, params, opts=()):
        record = {"cmd": "BUILD", "cmd_id": cmd_id, "unit": unit, "params": params}
        return record | ({"opts": list(opts)} if opts else {})

    events = [
        {"frame": frame(-300), "type": "select", "player": 0, "units": [100]},
        {"frame": frame(-200), "type": "team", "player": 0, "action": "join_team", "param": 0},
        {"frame": frame(-100), "type": "chat", "player": 0, "to": 252, "message": "hello"},
        {"frame": frame(0), "type": "start"},
        # pregame queue: widget orders for the commander, shift-appended
        _command(
            frame(5),
            0,
            0,
            "BUILD",
            via="AICOMMAND",
            units=[100],
            cmd_id=-3,
            unit="armmex",
            opts=["shift"],
            params=[5200.12, 38.1, 6704.5, 1],
        ),
        _command(frame(5), 0, 0, "BUILD", **build("armwin", -4, [5300, 40, 6800, 3], ["shift"])),
        # a structure without facing, and one with a NaN coordinate
        _command(frame(40), 1, 0, "BUILD", **build("armsolar", -5, [100.25, 0, 200.75])),
        _command(frame(41), 1, 0, "BUILD", **build("armsolar", -5, [None, 0, 1, 2])),
        # factory orders: every combination of shift, ctrl and right
        *(
            _command(frame(60 + index), 0, 0, "BUILD", **build("armpw", -6, [], opts))
            for index, opts in enumerate(
                [
                    (),
                    ("shift",),
                    ("ctrl",),
                    ("shift", "ctrl"),
                    ("right",),
                    ("right", "shift"),
                    ("right", "ctrl", "alt"),
                    ("meta", "internal"),
                ]
            )
        ),
        {"frame": frame(70), "type": "select", "player": 1, "units": [200, 201]},
        _command(frame(70), 1, 0, "MOVE", cmd_id=10, params=[1000, 50, 2000]),
        # BAR's factory quota widget, and INSERTs of other commands
        _command(
            frame(80),
            0,
            0,
            "INSERT",
            via="AICOMMANDS",
            units=[300],
            cmd_id=1,
            opts=["ctrl", "alt"],
            pos=0,
            inner=build("armpw", -6, [], ["internal", "alt"]),
        ),
        _command(
            frame(81),
            0,
            0,
            "INSERT",
            cmd_id=1,
            opts=["alt"],
            pos=2,
            inner=build("armmex", -3, [10, 0, 20, 0], ["shift"]),
        ),
        _command(
            frame(82),
            0,
            0,
            "INSERT",
            cmd_id=1,
            pos=123456,
            inner={"cmd": "MOVE", "cmd_id": 10, "params": [1, 2, 3]},
        ),
        _command(
            frame(83),
            0,
            0,
            "INSERT",
            cmd_id=1,
            pos=0,
            inner={
                "cmd": "INSERT",
                "cmd_id": 1,
                "pos": 1,
                "inner": build("armpw", -6, [], ["ctrl"]),
            },
        ),
        _command(frame(84), 0, 0, "INSERT", cmd_id=1, params=[0, 1]),  # too short to resolve
        _command(frame(90), 0, None, "BUILD", **build("armpw", -6, [])),  # no team
        _command(frame(91), 0, 0, "BUILD", **build(None, -999, [])),  # not in the unit list
        # the bot's orders, pairwise to two builders
        *(
            _command(
                frame(100),
                2,
                1,
                "BUILD",
                via="AICOMMANDS",
                ai=0,
                units=[builder],
                **build("cormex", -7, [7000, 0, 3000 + builder, 1]),
            )
            for builder in (400, 401)
        ),
        {"frame": frame(150), "type": "pause", "player": 0, "paused": True},
        {"frame": frame(160), "type": "pause", "player": 0, "paused": False},
        _command(frame(300), 0, 0, "BUILD", **build("armlab", -8, [500, 0, 600, 2])),
        {"frame": frame(400), "type": "team", "player": 1, "action": "resign", "param": 0},
        {"frame": frame(410), "type": "playerleft", "player": 1, "reason": 1},
        {"frame": frame(500), "type": "team", "player": 2, "action": "team_died", "param": 1},
        {"frame": frame(600), "type": "gameover", "player": 0, "winners": [0]},
        {"frame": frame(601), "type": "quit"},
    ]
    players = [
        {
            "playerId": player_id,
            "teamId": 0,
            "allyTeamId": 0,
            "name": f"Player{player_id + 1}",
            "userId": 1000 + player_id,
            "faction": "Armada",
            "rank": 3,
            "skill": "[25.5]",
            "skillUncertainty": 3.25,
            "startPos": {"x": 1000.5 + player_id, "y": 10.0, "z": 9000.25},
        }
        for player_id in (0, 1)
    ]
    ais = [
        {
            "aiId": 0,
            "teamId": 1,
            "allyTeamId": 1,
            "name": "BARb(1)",
            "shortName": "BARb",
            "version": "stable",
            "faction": "Cortex",
            "startPos": {"x": 9000.0, "y": 0.0, "z": 1000.0},
        }
    ]
    return Replay(
        {
            "format": "reason8.replay/1",
            "source": {"file": "2026-11-01_00-00-00-000_Test Valley 1.0_2026.09.03.sdfz"},
            "meta": {
                "map": MAP,
                "game": "Beyond All Reason test-32018-ad135b9",
                "engine": "2026.09.03",
                "serverMatchId": "123",
                "winningAllyTeamIds": [0],
                "startFrame": 0 if started else None,
                "endFrame": frame(600),
            },
            "allyTeams": [{"allyTeamId": 0, "startBox": BOTTOM_LEFT, "playerCount": 2}],
            "players": players,
            "ais": ais,
            "spectators": [{"playerId": 3, "name": "Spectator1", "userId": 2000}],
            "modoptions": {"map_waterlevel": "0", "mapmetadata_startpos": ""},
            "mapoptions": {},
            "restrictions": {},
            "unitdefs": ["", "armcom", "corcom", "armmex", "armwin", "armsolar", "armpw"],
            "events": events,
        }
    )


# --- parsed replays and their tables on disk


def write_parsed(directory: Path, name: str, replay: Replay | dict) -> Path:
    """Write a replay as `reason8 parse` does, into the date partition of its name."""
    document = replay.doc if isinstance(replay, Replay) else replay
    path = output_path(directory, Path(f"{name}.sdfz"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zstd.compress(json.dumps({"format": FORMAT, **document}).encode()))
    return path


def write_tables(parsed: Path) -> Path:
    """The tables of every parsed replay, as `reason8 tables` writes them next to `parsed`."""
    out = parsed.parent / tables.AREA
    tables.update(tables.parsed_days(parsed), out, jobs=0, log=lambda message: None)
    return out
