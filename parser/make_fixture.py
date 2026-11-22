"""Make the small, anonymised test fixture from one parsed replay.

    uv run python parser/make_fixture.py data/parsed/<replay>.json.gz tests/fixtures/replay.json

Keeps everything about the game except identities, and only a slice of events:
- for a few teams, the build-related commands of the first minutes (plus their
  selections), which is what the opening dataset uses;
- the first example of every (packet, command) kind, so every shape is covered;
- every factory-quota order, and samples of chat/mapdraw/share/team events.
Player names become Player1.., spectators Spectator1..; user ids, the game id,
match id, start time and the file name are replaced; chat text and map labels
are replaced with placeholders.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reason8.replay import load_replay

BUILD_RELATED = {"BUILD", "INSERT", "REMOVE", "STOP", "WAIT", "REPEAT"}
FACTORY_SETTINGS = {"REPEAT", "QUOTA_BUILD_TOGGLE", "FACTORY_GUARD", "STOP_PRODUCTION"}
SAMPLE_TYPES = {"chat": 4, "mapdraw": 4, "share": 3, "setshare": 2, "aishare": 2, "pause": 2}


def anonymise(document: dict) -> None:
    names: dict[int, str] = {}
    players = sorted(document["players"], key=lambda player: player["playerId"])
    for number, player in enumerate(players, 1):
        names[player["playerId"]] = f"Player{number}"
    spectators = sorted(document["spectators"], key=lambda spectator: spectator["playerId"])
    for number, spectator in enumerate(spectators, 1):
        names[spectator["playerId"]] = f"Spectator{number}"
    for person in document["players"] + document["spectators"]:
        person["name"] = names[person["playerId"]]
        person.pop("userId", None)
    document["meta"].update(
        gameId="0" * 32, serverMatchId=None, startTime="2026-01-01T00:00:00.000Z"
    )
    document["source"]["file"] = "fixture.sdfz"
    chat_count = label_count = 0
    for event in document["events"]:
        if event["type"] == "chat":
            chat_count += 1
            event["message"] = f"chat message {chat_count}"
        elif event["type"] == "mapdraw" and "label" in event:
            label_count += 1
            event["label"] = f"label {label_count}" if event["label"] else ""
    statistics = document.get("statistics") or {}
    for player_stats in statistics.get("playerStats", []):  # input-device stats aren't needed
        for key in ("mousePixels", "mouseClicks", "keyPresses"):
            player_stats.pop(key, None)


def select_events(document: dict, team_count: int, until_frame: int) -> list[dict]:
    # Pick teams from both sides (round robin over ally teams) so winners and
    # losers are both represented.
    teams_by_ally: dict[int, list[int]] = {}
    for player in sorted(document["players"], key=lambda player: player["teamId"]):
        teams_by_ally.setdefault(player["allyTeamId"], []).append(player["teamId"])
    chosen: list[int] = []
    while len(chosen) < team_count and any(teams_by_ally.values()):
        for ally_team in sorted(teams_by_ally):
            if teams_by_ally[ally_team] and len(chosen) < team_count:
                chosen.append(teams_by_ally[ally_team].pop(0))
    chosen_players = {
        player["playerId"] for player in document["players"] if player["teamId"] in chosen
    }

    keep: list[dict] = []
    seen_kinds: set[tuple] = set()
    samples: dict[str, int] = {}
    last_startpos: dict[int, dict] = {}
    for event in document["events"]:
        event_type = event["type"]
        frame = event["frame"] if event["frame"] is not None else 0
        take = False
        if event_type == "cmd":
            inner_command = (event.get("inner") or {}).get("cmd")
            kind = (event["via"], event["cmd"], inner_command)
            inner_options = (event.get("inner") or {}).get("opts") or []
            if kind not in seen_kinds:
                seen_kinds.add(kind)
                take = True
            elif (
                event.get("team") in chosen
                and frame <= until_frame
                and event["cmd"] in BUILD_RELATED
            ):
                take = True
            elif event["cmd"] in FACTORY_SETTINGS and event.get("team") in chosen:
                take = True
            elif event["cmd"] == "INSERT" and "internal" in inner_options:
                take = True  # factory-quota order
        elif event_type == "select":
            take = event["player"] in chosen_players and frame <= until_frame
        elif event_type in SAMPLE_TYPES:
            samples[event_type] = samples.get(event_type, 0) + 1
            take = samples[event_type] <= SAMPLE_TYPES[event_type]
        elif event_type == "gameover":
            take = not any(kept["type"] == "gameover" for kept in keep)
        elif event_type == "startpos":
            last_startpos[event["team"]] = event  # pregame drags send many; keep the final one
        else:  # start, team, playerleft, quit
            take = True
        if take:
            keep.append(event)
    return sorted(keep + list(last_startpos.values()), key=lambda event: event["frame"] or 0)


def dump(document: dict, path: Path) -> None:
    """JSON with one event per line: small, but still diffable."""
    events = document.pop("events")
    header_json = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    event_lines = ",\n".join(
        json.dumps(event, separators=(",", ":"), ensure_ascii=False) for event in events
    )
    path.write_text(header_json[:-1] + ',\n"events":[\n' + event_lines + "\n]}\n", encoding="utf-8")


def main() -> None:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("source", type=Path)
    argument_parser.add_argument("dest", type=Path)
    argument_parser.add_argument("--teams", type=int, default=2)
    argument_parser.add_argument("--minutes", type=float, default=3)
    args = argument_parser.parse_args()

    document = load_replay(args.source).doc
    document["events"] = select_events(document, args.teams, int(args.minutes * 60 * 30))
    anonymise(document)
    document["source"]["trimmed"] = (
        f"fixture: {args.teams} teams, build-related commands of the first {args.minutes:g} "
        "minutes, one example per command kind, samples of other events"
    )
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    event_count = len(document["events"])
    dump(document, args.dest)
    print(f"{args.dest}: {args.dest.stat().st_size / 1024:.1f} KiB, {event_count} events")


if __name__ == "__main__":
    main()
