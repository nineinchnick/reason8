"""Write the start script of a team game between AIs on a map's recommended start positions.

Usage::

    uv run reason8 bot game --map "Supreme Isthmus v2.1" \\
        --game "Beyond All Reason test-32018-ad135b9" --seed 1 --minutes 6 \\
        --out data/runs/team-game/script.txt
    uv run reason8 headless run --data-dir data/bar --run-dir data/runs/team-game \\
        --engine-dir data/bar/engine-variants/reason8 --timeout 900 \\
        data/runs/team-game/script.txt

The openings are per start position, so the AI has to be tried where humans start: in a
game of two teams of `players` (8 by default) on the positions the map list recommends for
that shape (``reason8 maps fetch``). Team ``i`` of the first ally team starts on that side's
``i``-th position, and so on. The first ally team is played by one AI and the second by
another (`--ai` and `--opponent`), each on its own side. The engine places every commander
on its team's start point (``StartPosType=3``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from reason8.game.maps import Layout, load_map_list

FRAMES_PER_MINUTE = 30 * 60
SIDES = ("Armada", "Cortex", "Legion")


def ai_fields(short_name: str) -> str:
    """What identifies an AI in the start script; BARb also needs its version."""
    return f"ShortName={short_name};" + (" Version=stable;" if short_name == "BARb" else "")


def team_game_script(
    *,
    map_name: str,
    game: str,
    layout: Layout,
    ais: tuple[str, str],
    sides: tuple[str, str],
    seed: int,
    frames: int,
) -> str:
    """The start script: one AI team per recommended position, a spectating host."""
    teams, ai_sections = [], []
    team_id = 0
    for ally_team, spawn_points in enumerate(layout.sides):
        for spawn_point in spawn_points:
            teams.append(
                f"\t[TEAM{team_id}] {{ Side={sides[ally_team]}; Handicap=0; "
                f"AllyTeam={ally_team}; TeamLeader=0; StartPosX={round(spawn_point.x)}; "
                f"StartPosZ={round(spawn_point.z)}; }}"
            )
            ai_sections.append(
                f"\t[AI{team_id}] {{ Host=0; IsFromDemo=0; Name={ais[ally_team]}{team_id}; "
                f"{ai_fields(ais[ally_team])} Team={team_id}; }}"
            )
            team_id += 1
    ally_teams = [f"\t[ALLYTEAM{index}] {{ NumAllies=0; }}" for index in range(len(layout.sides))]
    return "\n".join(
        [
            "[GAME]",
            "{",
            f"\tMapName={map_name};",
            f"\tGameType={game};",
            "\tGameStartDelay=0;",
            "\tStartPosType=3;",
            "\tRecordDemo=1;",
            "\tMyPlayerName=Reason8Runner;",
            "\tIsHost=1;",
            f"\tFixedRNGSeed={seed};",
            "\tNumPlayers=1;",
            "\tNumUsers=1;",
            "\tHostIP=127.0.0.1;",
            "\tHostPort=0;",
            "\t[MODOPTIONS]",
            "\t{",
            "\t\tdeathmode=neverend;",
            f"\t\tdebugcommands={frames}:quitforce;",
            "\t}",
            *ally_teams,
            *teams,
            *ai_sections,
            "\t[PLAYER0] { IsFromDemo=0; Name=Reason8Runner; Team=0; Spectator=1; Rank=0; }",
            "}",
            "",
        ]
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--map", required=True, help="map name, as in the map list")
    parser.add_argument("--game", required=True, help="installed game version, by name")
    parser.add_argument("--players", type=int, default=8, help="players per team")
    parser.add_argument("--ai", default="Reason8", help="the first ally team's AI")
    parser.add_argument("--opponent", default="BARb", help="the second ally team's AI")
    parser.add_argument("--sides", nargs=2, choices=SIDES, default=("Armada", "Cortex"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--minutes", type=float, default=6, help="game time before the end")
    parser.add_argument("--out", type=Path, required=True, help="where to write the script")


def run(args: argparse.Namespace) -> int:
    metadata = load_map_list().get(args.map)
    if metadata is None or metadata.start_positions is None:
        raise SystemExit(f"no recommended positions for {args.map!r} (reason8 maps fetch)")
    layout = metadata.start_positions.layout_for(2, args.players)
    if layout is None:
        raise SystemExit(f"{args.map!r} has no positions for two teams of {args.players}")
    script = team_game_script(
        map_name=args.map,
        game=args.game,
        layout=layout,
        ais=(args.ai, args.opponent),
        sides=tuple(args.sides),
        seed=args.seed,
        frames=round(args.minutes * FRAMES_PER_MINUTE),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(script, encoding="utf-8")
    print(f"{2 * args.players} AI teams on {args.map} -> {args.out}")
    return 0
