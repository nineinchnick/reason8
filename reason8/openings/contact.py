"""First contact: when a player's units are first hit by the enemy's.

Usage::

    uv run reason8 contact             # state files -> first_contact.parquet
    uv run reason8 contact --report    # the tables of docs/research/first-contact.md

An opening can only be told apart from the rest of the game until the player meets the
enemy: after that orders answer raids and losses, which the replay's commands do not show.
A replay does not say when that is, so a sample of replays is played again headlessly
(``reason8 headless batch``, ADR 0010) with the state export widget, which writes every
first hit between two units of opposite sides. This module reads those state files, finds
each player's first contact, and gives the dataset builder the frame at which an opening
ends: the measured one for a game that was re-simulated, and otherwise the usual one of
its map and start position (`POSITION_CUTOFF_SECONDS`). The decision is ADR 0012; the
measurements are in docs/research/first-contact.md.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from reason8 import markdown
from reason8.game.maps import MapMetadata, load_map_list
from reason8.game.positions import position_order, replay_positions
from reason8.headless.state import STATE_SUFFIX, read_records
from reason8.openings.extract import OPENING_SECONDS, opening_orders
from reason8.paths import data_dir
from reason8.replays.parse import output_path
from reason8.replays.replay import GAME_SPEED, Replay, load_replay

COMMANDER_PREFIXES = ("armcom", "corcom", "legcom")


#: Attacker sources in a state file's "end" line that name the real attacker.
EXACT_ATTACKERS = ("last_attacker", "attacker")


@dataclass(frozen=True)
class Hit:
    """The first time a unit was damaged by a unit of an enemy player."""

    frame: int
    team: int  # the player whose unit was damaged
    unit: str | None
    by_team: int
    by_unit: str | None
    damage: float


@dataclass(frozen=True)
class Loss:
    """A unit destroyed by an enemy player."""

    frame: int
    team: int
    unit: str | None
    by_team: int


@dataclass
class Fights:
    """What a state file says about the fighting in one game."""

    game_version: str | None = None
    map: str | None = None
    last_frame: int = 0
    complete: bool = False  # the file ends with its "end" line
    # how the widget knew who did the damage: "last_attacker" (asked from the
    # engine), or in older files "attacker" (read through BAR's widget handler) or
    # "nearest" (guessed: the nearest enemy unit); "none" when there was no damage
    attackers: str | None = None
    ally_teams: dict[int, int] = field(default_factory=dict)  # player -> side, without Gaia
    hits: list[Hit] = field(default_factory=list)
    losses: list[Loss] = field(default_factory=list)
    # (frame, damaged player, attacking player, damage) summed per second
    damage: list[tuple[int, int, int, float]] = field(default_factory=list)


def read_fights(path: str | Path) -> Fights:
    """The hits, losses and damage between the two sides in a state file."""
    fights = Fights()
    names: dict[str, str] = {}
    for record in read_records(path):
        kind = record["t"]
        if kind == "header":
            if record.get("v", 1) < 2:
                raise ValueError(f"{path}: written before the widget recorded damage")
            fights.game_version = record.get("game")
            fights.map = record.get("map")
            names = record["unitdefs"]
            fights.ally_teams = {
                team["team"]: team["ally"] for team in record["teams"] if not team.get("gaia")
            }
        elif kind == "hit":
            fights.hits.append(
                Hit(
                    record["f"],
                    record["team"],
                    names.get(str(record["d"])),
                    record["by_team"],
                    names.get(str(record["by_d"])),
                    record["damage"],
                )
            )
        elif kind == "destroyed":
            sides = fights.ally_teams
            by_team = record.get("by_team", -1)
            if by_team in sides and record["team"] in sides:
                if sides[by_team] != sides[record["team"]]:
                    fights.losses.append(
                        Loss(record["f"], record["team"], names.get(str(record["d"])), by_team)
                    )
        elif kind == "damage":
            fights.damage.append((record["f"], record["team"], record["by_team"], record["damage"]))
        elif kind == "end":
            fights.last_frame = record["f"]
            fights.attackers = record.get("attackers")
            fights.complete = True
    return fights


# --- when a player first meets the enemy

#: Units built to look, not to fight. Losing one is not something its owner answers with
#: their build orders.
SCOUTS = frozenset(
    {"armflea", "armfav", "armpeep", "corfav", "corfink", "legscout", "legfig", "legnavyscout"}
)
DAMAGE_THRESHOLD = 500  # for the "damage" measure: about the health of two light bots

#: The ways of saying when a player first met the enemy that docs/research/first-contact.md
#: compares. `CONTACT` is the one the dataset uses.
MEASURES = {
    "any_hit": "a unit of the player is hit by an enemy unit, or hits one",
    "hit_with_scouts": "a unit of the player is hit by an enemy unit",
    "hit": "a unit of the player other than a scout is hit by an enemy unit",
    "hit_without_duels": "the same, not counting a commander hit by a commander",
    "loss": "a unit of the player other than a scout is destroyed by an enemy unit",
    "damage": f"enemy units have done {DAMAGE_THRESHOLD} damage to the player's units",
}
CONTACT = "hit"


def is_commander(unit: str | None) -> bool:
    return bool(unit) and unit.startswith(COMMANDER_PREFIXES)


def contact_measures(fights: Fights) -> dict[int, dict[str, int | None]]:
    """Per player, the frame of first contact by each of `MEASURES` (None: not by the end)."""
    found: dict[int, dict[str, int | None]] = {
        team: dict.fromkeys(MEASURES) for team in fights.ally_teams
    }

    def note(team: int, measure: str, frame: int) -> None:
        if team in found and found[team][measure] is None:
            found[team][measure] = frame

    for hit in fights.hits:
        note(hit.team, "any_hit", hit.frame)
        note(hit.by_team, "any_hit", hit.frame)
        note(hit.team, "hit_with_scouts", hit.frame)
        if hit.unit not in SCOUTS:
            note(hit.team, "hit", hit.frame)
            if not (is_commander(hit.unit) and is_commander(hit.by_unit)):
                note(hit.team, "hit_without_duels", hit.frame)
    for loss in fights.losses:
        if loss.unit not in SCOUTS:
            note(loss.team, "loss", loss.frame)
    taken = dict.fromkeys(fights.ally_teams, 0.0)
    for frame, team, _, damage in fights.damage:
        if team in taken:
            taken[team] += damage
            if taken[team] >= DAMAGE_THRESHOLD:
                note(team, "damage", frame)
    return found


def first_contact(fights: Fights) -> dict[int, int | None]:
    """Per player, the frame of their first contact with the enemy (`CONTACT`)."""
    return {team: frames[CONTACT] for team, frames in contact_measures(fights).items()}


# --- the measured games

TABLE_NAME = "first_contact.parquet"
TABLE_SCHEMA = {
    "replay": pl.String,  # the replay's file name without its ending
    "map": pl.String,
    "game_version": pl.String,
    "attackers": pl.String,
    "last_frame": pl.Int32,  # the game was played up to here
    "team": pl.Int32,
    "ally_team": pl.Int32,
    "position": pl.String,
    "role": pl.String,
    "position_index": pl.Int32,
    **{measure: pl.Int32 for measure in MEASURES},
    "order_frames": pl.List(pl.Int32),  # the player's build orders of the opening window
}


def contact_dir() -> Path:
    return data_dir() / "contact"


def replay_name(path: str | Path, suffix: str = STATE_SUFFIX) -> str:
    """The name that a replay, its parsed file and its state file share."""
    return Path(path).name.removesuffix(suffix)


def measure_game(
    fights: Fights, replay: Replay, name: str, map_list: Mapping[str, MapMetadata] | None = None
) -> list[dict[str, Any]]:
    """One row per player of a re-simulated game: who, where, and their first contact."""
    positions = replay_positions(replay, map_list)
    orders = opening_orders(replay)
    rows = []
    for team, measures in sorted(contact_measures(fights).items()):
        position = positions.get(team)
        rows.append(
            {
                "replay": name,
                "map": replay.meta.get("map"),
                "game_version": replay.meta.get("game"),
                "attackers": fights.attackers,
                "last_frame": fights.last_frame,
                "team": team,
                "ally_team": fights.ally_teams[team],
                "position": position.spawn_point if position else None,
                "role": position.role if position else None,
                "position_index": position.index if position else None,
                **measures,
                "order_frames": [order.frame for order in orders.get(team, [])],
            }
        )
    return rows


def measure(
    state_dir: Path, parsed_dir: Path, map_list: Mapping[str, MapMetadata] | None = None
) -> pl.DataFrame:
    """The first contact of every player of every complete state file in `state_dir`."""
    map_list = load_map_list() if map_list is None else map_list
    rows: list[dict[str, Any]] = []
    for path in sorted(state_dir.glob("*" + STATE_SUFFIX)):
        name = replay_name(path)
        parsed = output_path(parsed_dir, Path(name + ".sdfz"))
        fights = read_fights(path)
        if not fights.complete or not parsed.exists():
            print(f"skipped {path.name}: cut off, or its replay is not parsed", file=sys.stderr)
            continue
        rows += measure_game(fights, load_replay(parsed), name, map_list)
    return pl.from_dicts(rows, schema=TABLE_SCHEMA)


def load_measured(path: Path) -> dict[str, dict[int, int | None]]:
    """Replay name -> player -> frame of first contact (None: none while it was played)."""
    measured: dict[str, dict[int, int | None]] = {}
    if not path.exists():
        return measured
    for name, team, frame in pl.read_parquet(path).select("replay", "team", CONTACT).iter_rows():
        measured.setdefault(name, {})[team] = frame
    return measured


# --- where an opening ends

MEASURED = "measured"  # the game was re-simulated: the player's own first contact
BY_POSITION = "position"  # the usual first contact of the map and start position
WINDOW = "window"  # no contact known: the whole opening window

#: The share of a position's players who have met the enemy by the position's cutoff.
CUTOFF_QUANTILE = 0.5

#: When an opening ends in a game that was not re-simulated, in seconds, per map and start
#: position: the `CUTOFF_QUANTILE` of the measured first contacts, capped at the window
#: (docs/research/first-contact.md; printed by `reason8 contact --report`).
POSITION_CUTOFF_SECONDS: dict[str, dict[str, int]] = {
    "All That Glitters v2.2.3": {
        "P1": 250,
        "P9": 250,
        "P2": 300,
        "P10": 300,
        "P3": 480,
        "P11": 480,
        "P4": 275,
        "P12": 275,
        "P5": 195,
        "P13": 195,
        "P6": 225,
        "P14": 225,
        "P7": 230,
        "P15": 230,
        "P8": 205,
        "P16": 205,
    },
    "Rosetta 1.4.4": {
        "P1": 175,
        "P9": 175,
        "P2": 385,
        "P10": 385,
        "P3": 175,
        "P11": 175,
        "P4": 165,
        "P12": 165,
        "P5": 230,
        "P13": 230,
        "P6": 170,
        "P14": 170,
        "P7": 395,
        "P15": 395,
        "P8": 180,
        "P16": 180,
    },
    "Supreme Isthmus v2.1": {
        "P1": 240,
        "P9": 240,
        "P2": 480,
        "P10": 480,
        "P3": 295,
        "P11": 295,
        "P4": 440,
        "P12": 440,
        "P5": 125,
        "P13": 125,
        "P6": 125,
        "P14": 125,
        "P7": 480,
        "P15": 480,
        "P8": 265,
        "P16": 265,
    },
}


def opening_cutoff(
    map_name: str | None,
    position: str | None,
    window_frames: int,
    measured: Mapping[int, int | None] | None = None,
    team: int | None = None,
    position_cutoffs: Mapping[str, Mapping[str, int]] | None = None,
) -> tuple[int, str]:
    """The last frame of a player's opening and where it comes from.

    `measured` is the first contacts of the game's players when the game was
    re-simulated. Nothing ends later than the window.
    """
    if measured is not None and team in measured:
        contact_frame = measured[team]
        return (
            window_frames if contact_frame is None else min(contact_frame, window_frames)
        ), MEASURED
    cutoffs = POSITION_CUTOFF_SECONDS if position_cutoffs is None else position_cutoffs
    seconds = cutoffs.get(map_name or "", {}).get(position or "")
    if seconds is None:
        return window_frames, WINDOW
    return min(seconds * GAME_SPEED, window_frames), BY_POSITION


def quantile_frame(frames: Iterable[int | None], share: float) -> float:
    """The frame by which `share` of the players had contact; inf when fewer ever had."""
    ordered = sorted(math.inf if frame is None else frame for frame in frames)
    if not ordered:
        return math.inf
    return ordered[min(len(ordered) - 1, math.floor(share * len(ordered)))]


def position_cutoffs(
    table: pl.DataFrame,
    quantile: float = CUTOFF_QUANTILE,
    window_seconds: int = OPENING_SECONDS,
    step_seconds: int = 5,
) -> dict[str, dict[str, int]]:
    """Per map and position, the second at which openings end, from the measured games.

    The two sides of a map mirror each other, so a position shares its cutoff with the
    position at the same place in the other side's list. Rounded down to `step_seconds`.
    """
    cutoffs: dict[str, dict[str, int]] = {}
    known = table.filter(pl.col("position").is_not_null())
    for (map_name, _), group in sorted(known.group_by("map", "position_index"), key=str):
        seconds = quantile_frame(group[CONTACT].to_list(), quantile) / GAME_SPEED
        seconds = min(seconds, window_seconds)
        rounded = int(seconds // step_seconds) * step_seconds
        for position in sorted(set(group["position"].to_list()), key=position_order):
            cutoffs.setdefault(map_name, {})[position] = rounded
    return cutoffs


# --- the tables of docs/research/first-contact.md


def _clock(frame: float) -> str:
    if math.isinf(frame):
        return "none"
    seconds = int(frame // GAME_SPEED)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _share(part: float, whole: float) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def _spread(frames: Sequence[int | None], window_frames: int) -> list[str]:
    """Lower quartile, median, upper quartile, and the share with contact in the window."""
    in_window = sum(frame is not None and frame <= window_frames for frame in frames)
    return [
        *(_clock(quantile_frame(frames, share)) for share in (0.25, 0.5, 0.75)),
        _share(in_window, len(frames)),
    ]


def _orders_after(group: pl.DataFrame, measure: str) -> str:
    """The share of the window's build orders given after the player's contact."""
    after = total = 0
    for contact_frame, frames in group.select(measure, "order_frames").iter_rows():
        total += len(frames)
        if contact_frame is not None:
            after += sum(frame > contact_frame for frame in frames)
    return _share(after, total)


def cutoff_effect(
    table: pl.DataFrame, cutoffs: Mapping[str, Mapping[str, int]], window_frames: int
) -> tuple[int, int, int, int, int]:
    """What cutting every opening of `table` at its position's cutoff keeps and loses.

    Returns the build orders (in the window, given before the player's own contact, kept,
    kept although given after that contact, dropped although given before it).
    """
    in_window = before = kept = kept_after = dropped_before = 0
    for row in table.iter_rows(named=True):
        cutoff, _ = opening_cutoff(
            row["map"], row["position"], window_frames, position_cutoffs=cutoffs
        )
        contact_frame = math.inf if row[CONTACT] is None else row[CONTACT]
        for frame in row["order_frames"]:
            in_window += 1
            before += frame <= contact_frame
            kept += frame <= cutoff
            kept_after += contact_frame < frame <= cutoff
            dropped_before += cutoff < frame <= contact_frame
    return in_window, before, kept, kept_after, dropped_before


def report(table: pl.DataFrame, window_seconds: int = OPENING_SECONDS) -> str:
    """The tables of docs/research/first-contact.md, from the measured games."""
    window_frames = window_seconds * GAME_SPEED
    maps = sorted(table["map"].unique().to_list())
    games = table.unique("replay")
    lines = ["## The sample", ""]
    lines += markdown.table(
        ["map", "games", "players", "attacker known", "attacker guessed"],
        [
            [
                map_name,
                games.filter(pl.col("map") == map_name).height,
                table.filter(pl.col("map") == map_name).height,
                games.filter(
                    pl.col("map") == map_name, pl.col("attackers").is_in(EXACT_ATTACKERS)
                ).height,
                games.filter(pl.col("map") == map_name, pl.col("attackers") == "nearest").height,
            ]
            for map_name in maps
        ],
    )
    played = sorted(games["last_frame"].to_list())
    lines += [
        "",
        f"Played for {_clock(played[0])} to {_clock(played[-1])} of game time "
        f"(median {_clock(played[len(played) // 2])}).",
    ]

    lines += ["", "## The definitions compared", ""]
    header = ["players", "lower quartile", "median", "upper quartile"]
    header += [f"contact in {window_seconds // 60} min", "orders after contact"]
    for map_name in maps:
        group = table.filter(pl.col("map") == map_name)
        lines += [f"### {map_name}", ""]
        lines += markdown.table(
            ["first contact", *header],
            [
                [f"`{measure}`", group.height, *_spread(group[measure].to_list(), window_frames)]
                + [_orders_after(group, measure)]
                for measure in MEASURES
            ],
        )
        lines += [""]

    lines += ["## Sides", ""]
    sides = table.group_by("replay", "map", "ally_team").agg(pl.col(CONTACT).min())
    lines += markdown.table(
        ["map", "sides", "lower quartile", "median", "upper quartile"],
        [
            [
                map_name,
                sides.filter(pl.col("map") == map_name).height,
                *_spread(sides.filter(pl.col("map") == map_name)[CONTACT].to_list(), window_frames)[
                    :3
                ],
            ]
            for map_name in maps
        ],
    )

    cutoffs = position_cutoffs(table, window_seconds=window_seconds)
    lines += ["", "## Per map and position", ""]
    for map_name in maps:
        lines += [f"### {map_name}", ""]
        rows = []
        on_map = table.filter(pl.col("map") == map_name, pl.col("position").is_not_null())
        for (_,), group in sorted(on_map.group_by("position_index")):
            positions = sorted(set(group["position"].to_list()), key=position_order)
            roles = Counter(group["role"].to_list()).most_common(1)[0][0]
            rows.append(
                [", ".join(positions), roles or "-", group.height]
                + _spread(group[CONTACT].to_list(), window_frames)
                + [_orders_after(group, CONTACT)]
                + [_clock(cutoffs[map_name][positions[0]] * GAME_SPEED)]
            )
        lines += markdown.table(["positions", "role", *header, "cutoff"], rows)
        lines += [""]

    lines += ["## What a cutoff per position keeps", ""]
    rows = []
    for quantile in (0.25, 0.5, 0.75):
        candidate = position_cutoffs(table, quantile, window_seconds)
        for map_name in maps:
            in_window, before, kept, kept_after, dropped_before = cutoff_effect(
                table.filter(pl.col("map") == map_name), candidate, window_frames
            )
            rows.append(
                [
                    f"{quantile:.2f}",
                    map_name,
                    _share(kept, in_window),
                    _share(kept_after, kept),
                    _share(before, in_window),
                    _share(dropped_before, before),
                ]
            )
    lines += markdown.table(
        ["quantile", "map", "orders kept", "of them after contact"]
        + ["orders before contact", "of them dropped"],
        rows,
    )

    lines += ["", "## The cutoffs", "", "```python", "POSITION_CUTOFF_SECONDS = {"]
    for map_name, by_position in cutoffs.items():
        lines += [f'    "{map_name}": {{']
        lines += [
            "        " + ", ".join(f'"{position}": {seconds}' for position, seconds in chunk) + ","
            for chunk in _chunks(list(by_position.items()), 6)
        ]
        lines += ["    },"]
    lines += ["}", "```"]
    return "\n".join(lines)


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", type=Path, default=data_dir() / "state")
    parser.add_argument("--parsed", type=Path, default=data_dir() / "parsed")
    parser.add_argument("--out", type=Path, default=contact_dir() / TABLE_NAME)
    parser.add_argument(
        "--report", action="store_true", help="print the tables of an existing first contact file"
    )


def run(args: argparse.Namespace) -> int:
    if args.report:
        print(report(pl.read_parquet(args.out)))
        return 0
    table = measure(args.state, args.parsed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.write_parquet(args.out)
    print(f"{table['replay'].n_unique()} games, {table.height} players -> {args.out}")
    return 0
