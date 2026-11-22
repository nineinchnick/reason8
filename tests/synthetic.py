"""Made-up map metadata and replays for tests: none of it describes a real map."""

from __future__ import annotations

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
