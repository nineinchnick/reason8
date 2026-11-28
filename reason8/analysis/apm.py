"""Measure how many actions per minute people take, over the game and by skill.

Usage::

    uv run reason8 analysis apm             # tables of the parsed replays -> <data dir>/apm/
    uv run reason8 analysis apm --since 2026-11-01 --until 2026-11-08 --out data/apm-week
    uv run reason8 analysis apm --report    # the tables of docs/research/apm.md

Only the command packets of the parsed replays are used, no re-simulation. They are read
from the commands, selections and events tables (`reason8.replays.tables`), a day per
process, and put back in stream order (`event_stream`). An action is
counted the way BAR's own APM gadget (``luarules/gadgets/game_apm_broadcast.lua``) counts it,
from the commands a player's units receive:

- at most one action per player per game frame, so dragging a line of buildings, which
  sends many orders in one frame, is one action;
- a command counts only if at least one of its units got no command from that player in
  the 7 frames before, and every command marks its units for the next 7 frames. Holding the
  right mouse button repeats a move order every few frames; this makes it one action.

A ``COMMAND`` packet goes to the player's current selection (the last ``select`` event), an
``AICOMMAND``/``AICOMMANDS`` packet to the units it lists. Four counts are kept per player:

``clicked``
    ``COMMAND`` packets: what the player clicked or typed.
``widget``
    ``AICOMMAND``/``AICOMMANDS`` packets sent by the player's LuaUI widgets (``ai`` 255).
    Some follow a click (a formation move is sent this way), others run on their own
    (queue clean-up, priorities, idle modes).
``all``
    Both together: what BAR shows in game as a player's APM.
``clicked_raw``
    ``COMMAND`` packets, one per frame, without the 7-frame rule: closest to counting clicks.

A player is counted from the start of the game until the game ends, they resign, their team
dies or they leave for good. Only whole minutes in that span are kept.

The output, in ``<data dir>/apm/``:

``games.parquet``
    One row per parsed replay, with why a game was left out (``status``).
``players.parquet``
    One row per player of every game used: skill, minutes played, actions of each kind and
    the most actions in any 1, 5, 10 and 60 seconds.
``minutes.parquet``
    One row per player and whole minute: actions of each kind, and the most ``clicked`` and
    ``all`` actions in any 1 and 10 seconds that start in that minute.
"""

from __future__ import annotations

import argparse
import math
import sys
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from reason8 import markdown
from reason8.paths import data_dir
from reason8.replays import tables
from reason8.replays.replay import GAME_SPEED, Replay, parse_skill

#: BAR's APM gadget ignores a unit's commands for this many frames after its last one.
SPAM_FRAMES = 7
#: The ``ai`` number of AICOMMAND packets sent by a human player's widgets.
WIDGET_AI = 255
FRAMES_PER_MINUTE = 60 * GAME_SPEED

KINDS = ("clicked", "widget", "all", "clicked_raw")
#: Burst windows, in seconds, measured over each player's whole game.
BURST_SECONDS = (1, 5, 10, 60)
#: Burst windows, in seconds, measured within each minute.
MINUTE_BURST_SECONDS = (1, 10)
MINUTE_BURST_KINDS = ("clicked", "all")

INCLUDED = "included"
WITH_BOTS = "bots in the game"
NOT_FINISHED = "no game over"
TOO_SHORT = "shorter than a minute"

#: Game phases of the report, in minutes: (name, first minute, end minute).
PHASES = (
    ("0-2 min", 0, 2),
    ("2-5 min", 2, 5),
    ("5-10 min", 5, 10),
    ("10-15 min", 10, 15),
    ("15-20 min", 15, 20),
    ("20-30 min", 20, 30),
    ("30+ min", 30, 10**6),
)
#: Skill bands of the report (OpenSkill mu as BAR shows it): (name, low, high).
SKILL_BANDS = (
    ("below 10", -math.inf, 10),
    ("10-20", 10, 20),
    ("20-30", 20, 30),
    ("30-40", 30, 40),
    ("40 and up", 40, math.inf),
)
QUANTILES = (0.25, 0.5, 0.75, 0.9, 0.99)


class ActionCounter:
    """Counts the actions of one player the way BAR's APM gadget does."""

    def __init__(self, spam_frames: int = SPAM_FRAMES) -> None:
        self.spam_frames = spam_frames
        self.ignored_until: dict[int, int] = {}
        self.last_frame: int | None = None
        self.frames: list[int] = []

    def command(self, frame: int, units: Iterable[int]) -> bool:
        """Record a command to `units` at `frame`; True when it counts as an action."""
        counted = False
        for unit in units:
            if not counted and self.last_frame != frame:
                until = self.ignored_until.get(unit)
                counted = until is None or until <= frame
            self.ignored_until[unit] = frame + self.spam_frames
        if counted:
            self.frames.append(frame)
            self.last_frame = frame
        return counted


class FrameCounter:
    """Counts frames with at least one command: no 7-frame rule."""

    def __init__(self) -> None:
        self.frames: list[int] = []

    def command(self, frame: int, units: Iterable[int] = ()) -> bool:
        if self.frames and self.frames[-1] == frame:
            return False
        self.frames.append(frame)
        return True


#: The fields of an event that the counting reads, in the order of `event_rows`.
EVENT_FIELDS = ("type", "frame", "player", "via", "ai", "units", "action", "param", "kind")
EventRow = tuple[Any, ...]


def order_kind(event: Mapping[str, Any]) -> str | None:
    """The kind of order of a command event: its command, unit to build and options, and
    for an INSERT the inserted command's and the INSERT's own options; not its parameters
    or units. A dragged line of one building is one kind, a move and a shift-queued move
    are two. The same as `order_kind_column` of the command's row in the tables."""
    if event.get("type") != "cmd":
        return None
    command = event
    insert_options = None
    if event.get("cmd") == "INSERT" and "inner" in event:
        command = event["inner"]
        insert_options = tables.option_bits(event.get("opts"))
    return _kind_key(
        command.get("cmd_id"),
        command.get("unit"),
        tables.option_bits(command.get("opts")),
        insert_options,
    )


def _kind_key(command_id: Any, unit: Any, options: Any, insert_options: Any) -> str:
    parts = (command_id, unit, options, insert_options)
    return ":".join("" if part is None else str(part) for part in parts)


def order_kind_column() -> pl.Expr:
    """`order_kind` of the rows of the commands table, as a ``kind`` column."""
    parts = [
        pl.col(name).cast(pl.String).fill_null("")
        for name in ("command_id", "unit", "options", "insert_options")
    ]
    return pl.concat_str(parts, separator=":").alias("kind")


def event_rows(events: Iterable[Mapping[str, Any]]) -> list[EventRow]:
    """The events of a parsed document as tuples of `EVENT_FIELDS`. An event that already
    has a ``kind`` (one rebuilt from `event_stream`) keeps it."""
    return [
        (
            *(event.get(name) for name in EVENT_FIELDS[:-1]),
            event["kind"] if "kind" in event else order_kind(event),
        )
        for event in events
    ]


def end_frames(replay: Replay, events: Sequence[EventRow] | None = None) -> dict[int, int]:
    """Player id -> the frame their game ended: game over, resign, team died or left for good.

    `events` are the replay's events as `event_rows` gives them (by default from its
    document), or as `day_apm` reads them from the tables.
    """
    game_end = replay.end_frame or 0
    team_of = {player["playerId"]: player["teamId"] for player in replay.players}
    ends = dict.fromkeys(team_of, game_end)
    left: dict[int, int] = {}
    last_command: dict[int, int] = {}
    team_died: dict[int, int] = {}
    if events is None:
        events = event_rows(replay.events)
    for kind, frame, player, _, _, _, action, param, _ in events:
        if frame is None or frame < 0:
            continue
        if kind == "cmd" and player is not None:
            last_command[player] = frame
        elif kind == "team":
            if action == "resign" and player in ends:
                ends[player] = min(ends[player], frame)
            elif action == "team_died" and param is not None:
                team_died.setdefault(int(param), frame)
        elif kind == "playerleft" and player in ends:
            left[player] = frame
    for player, team in team_of.items():
        if team in team_died:
            ends[player] = min(ends[player], team_died[team])
        if player in left and last_command.get(player, -1) <= left[player]:
            ends[player] = min(ends[player], left[player])
    return ends


def player_actions(
    replay: Replay, events: Sequence[EventRow] | None = None
) -> dict[int, dict[str, list[int]]]:
    """Player id -> kind -> the frames of that player's actions (see the module docs).

    `events` as for `end_frames`.
    """
    counters = {
        player["playerId"]: {
            "clicked": ActionCounter(),
            "widget": ActionCounter(),
            "all": ActionCounter(),
            "clicked_raw": FrameCounter(),
        }
        for player in replay.players
    }
    selections: dict[int, Sequence[int]] = {}
    if events is None:
        events = event_rows(replay.events)
    for kind, frame, player, via, ai, event_units, _, _, _ in events:
        if player not in counters:
            continue
        if kind == "select":  # pregame selections count too
            selections[player] = event_units or ()
            continue
        if kind != "cmd" or frame is None or frame < 0:
            continue
        counter = counters[player]
        if via == "COMMAND":
            units = selections.get(player, ())
            counter["clicked"].command(frame, units)
            if units:
                counter["clicked_raw"].command(frame)
        elif ai == WIDGET_AI:
            units = event_units or ()
            counter["widget"].command(frame, units)
        else:
            continue
        counter["all"].command(frame, units)
    return {
        player: {kind: counter.frames for kind, counter in kinds.items()}
        for player, kinds in counters.items()
    }


def most_in_window(frames: Sequence[int], window: int, start: int = 0, end: int | None = None):
    """The most of the sorted `frames` in any `window` frames that start in [start, end)."""
    best = 0
    first = bisect_left(frames, start)
    last = len(frames) if end is None else bisect_left(frames, end)
    upper = first
    for index in range(first, last):
        upper = max(upper, index)
        while upper < len(frames) and frames[upper] < frames[index] + window:
            upper += 1
        best = max(best, upper - index)
    return best


def per_minute(frames: Sequence[int], minutes: int) -> list[int]:
    """Actions in each of the first `minutes` whole minutes."""
    counts = [0] * minutes
    for frame in frames:
        minute = frame // FRAMES_PER_MINUTE
        if minute < minutes:
            counts[minute] += 1
    return counts


@dataclass
class GameApm:
    """What one replay gives: the game, its players and their minutes."""

    game: dict[str, Any]
    players: list[dict[str, Any]] = field(default_factory=list)
    minutes: dict[str, list[Any]] = field(default_factory=lambda: {})


def game_exclusion(replay: Replay) -> str | None:
    if replay.ais:
        return WITH_BOTS
    if replay.end_frame is None:
        return NOT_FINISHED
    if replay.end_frame < FRAMES_PER_MINUTE:
        return TOO_SHORT
    return None


def game_apm(replay: Replay, replay_name: str, events: Sequence[EventRow] | None = None) -> GameApm:
    """The actions of every player of one replay, per minute and over the game.

    `events` as for `end_frames`.
    """
    team_sizes: dict[int, int] = {}
    for player in replay.players:
        team_sizes[player["allyTeamId"]] = team_sizes.get(player["allyTeamId"], 0) + 1
    game = {
        "replay": replay_name,
        "match_id": replay.meta.get("serverMatchId"),
        "map": replay.meta.get("map"),
        "game_version": replay.meta.get("game"),
        "players": len(replay.players),
        "team_size": max(team_sizes.values(), default=0),
        "ally_teams": len(team_sizes),
        "end_frame": replay.end_frame,
        "status": game_exclusion(replay) or INCLUDED,
    }
    result = GameApm(game)
    if game["status"] != INCLUDED:
        return result
    if events is None:
        events = event_rows(replay.events)
    actions = player_actions(replay, events)
    ends = end_frames(replay, events)
    winners = set(replay.winning_ally_teams)
    minute_columns: dict[str, list[Any]] = {
        name: []
        for name in (
            "replay",
            "player_id",
            "skill",
            "minute",
            *KINDS,
            *(
                f"{kind}_max_{seconds}s"
                for kind in MINUTE_BURST_KINDS
                for seconds in MINUTE_BURST_SECONDS
            ),
        )
    }
    for player in replay.players:
        player_id = player["playerId"]
        skill = parse_skill(player.get("skill"))
        end = ends[player_id]
        minutes = end // FRAMES_PER_MINUTE
        frames = {kind: [f for f in actions[player_id][kind] if f < end] for kind in KINDS}
        row = {
            "replay": replay_name,
            "player_id": player_id,
            "skill": skill,
            "skill_uncertainty": parse_skill(player.get("skillUncertainty")),
            "team_size": game["team_size"],
            "won": player["allyTeamId"] in winners,
            "end_frame": end,
            "minutes": minutes,
        }
        for kind in KINDS:
            row[kind] = len(frames[kind])
            for seconds in BURST_SECONDS:
                row[f"{kind}_max_{seconds}s"] = most_in_window(frames[kind], seconds * GAME_SPEED)
        result.players.append(row)
        counts = {kind: per_minute(frames[kind], minutes) for kind in KINDS}
        for minute in range(minutes):
            minute_columns["replay"].append(replay_name)
            minute_columns["player_id"].append(player_id)
            minute_columns["skill"].append(skill)
            minute_columns["minute"].append(minute)
            for kind in KINDS:
                minute_columns[kind].append(counts[kind][minute])
            start = minute * FRAMES_PER_MINUTE
            for kind in MINUTE_BURST_KINDS:
                for seconds in MINUTE_BURST_SECONDS:
                    minute_columns[f"{kind}_max_{seconds}s"].append(
                        most_in_window(
                            frames[kind], seconds * GAME_SPEED, start, start + FRAMES_PER_MINUTE
                        )
                    )
    result.minutes = minute_columns
    return result


def event_stream(source: tables.Source, replays: Iterable[str]) -> pl.LazyFrame:
    """The commands, selections and events of `replays`, in stream order, from the tables.

    One row per event with the fields that `player_actions` and `end_frames` read: ``type``,
    ``frame``, ``player``, ``via``, ``ai``, ``units``, ``action``, ``param`` and ``kind``
    (`order_kind`).
    """
    replays = list(replays)
    commands = source.scan(tables.COMMANDS, replays).select(
        "replay",
        "seq",
        pl.lit("cmd").alias("type"),
        "frame",
        "player",
        pl.col("via").cast(pl.String),
        "ai",
        "units",
        order_kind_column(),
    )
    selections = source.scan(tables.SELECTIONS, replays).select(
        "replay", "seq", pl.lit("select").alias("type"), "frame", "player", "units"
    )
    events = source.scan(tables.EVENTS, replays).select(
        "replay", "seq", pl.col("type").cast(pl.String), "frame", "player", "action", "param"
    )
    return (
        pl.concat([commands, selections, events], how="diagonal_relaxed")
        .sort("replay", "seq", maintain_order=True)
        .drop("seq")
    )


#: Replays whose events are read at once: a busy day's events at once take over 10 GB.
REPLAYS_PER_READ = 20


def day_apm(source: tables.Source, chunk: int = REPLAYS_PER_READ) -> dict[str, GameApm]:
    """Replay -> its actions, for the replays of a source (one day), read `chunk` replays
    at a time to keep memory low."""
    headers = tables.replay_headers(
        source.scan(tables.GAMES).collect(), source.scan(tables.PLAYERS).collect()
    )
    results = {
        name: game_apm(header, name)
        for name, header in headers.items()
        if game_exclusion(header) is not None
    }
    included = sorted(set(headers) - set(results))
    for start in range(0, len(included), chunk):
        stream = event_stream(source, included[start : start + chunk]).collect()
        for (name,), rows in stream.group_by("replay", maintain_order=True):
            events = list(zip(*(rows[field].to_list() for field in EVENT_FIELDS), strict=True))
            results[name] = game_apm(headers[name], name, events)
        del stream
    for name in included:
        if name not in results:  # no events at all
            results[name] = game_apm(headers[name], name, [])
    return results


GAME_SCHEMA = {
    "replay": pl.String,
    "match_id": pl.String,
    "map": pl.String,
    "game_version": pl.String,
    "players": pl.Int32,
    "team_size": pl.Int32,
    "ally_teams": pl.Int32,
    "end_frame": pl.Int32,
    "status": pl.String,
    "error": pl.String,
}
PLAYER_SCHEMA = {
    "replay": pl.String,
    "player_id": pl.Int32,
    "skill": pl.Float32,
    "skill_uncertainty": pl.Float32,
    "team_size": pl.Int32,
    "won": pl.Boolean,
    "end_frame": pl.Int32,
    "minutes": pl.Int32,
    **{kind: pl.Int32 for kind in KINDS},
    **{f"{kind}_max_{seconds}s": pl.Int32 for kind in KINDS for seconds in BURST_SECONDS},
}
MINUTE_SCHEMA = {
    "replay": pl.String,
    "player_id": pl.Int16,
    "skill": pl.Float32,
    "minute": pl.Int16,
    **{kind: pl.Int16 for kind in KINDS},
    **{
        f"{kind}_max_{seconds}s": pl.Int16
        for kind in MINUTE_BURST_KINDS
        for seconds in MINUTE_BURST_SECONDS
    },
}


def measure(
    out_dir: Path,
    *,
    tables_dir: Path | None = None,
    jobs: int = 1,
    since: date | None = None,
    until: date | None = None,
) -> dict[str, int]:
    """Count the actions in every parsed replay and write the three tables to `out_dir`.

    The replays are read from the tables in `tables_dir` (by default those of the data
    directory, `reason8.replays.tables.open_source`), a day per process.
    """
    source = tables.open_source(tables_dir, since=since, until=until)
    days = source.by_day()
    game_parts: list[pl.DataFrame] = []
    player_parts: list[pl.DataFrame] = []
    minute_parts: list[pl.DataFrame] = []
    replays = 0
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        for count, found in enumerate(pool.map(day_apm, days), start=1):
            # a day's rows become frames at once: kept as dicts, the slice's do not fit
            game_part, player_part, minute_part = _day_frames(found)
            game_parts.append(game_part)
            player_parts.append(player_part)
            minute_parts.append(minute_part)
            replays += len(found)
            print(f"{count} of {len(days)} days, {replays} replays read", file=sys.stderr)
    games = _concat(game_parts, GAME_SCHEMA)
    players = _concat(player_parts, PLAYER_SCHEMA)
    out_dir.mkdir(parents=True, exist_ok=True)
    games.write_parquet(out_dir / "games.parquet")
    players.write_parquet(out_dir / "players.parquet")
    _concat(minute_parts, MINUTE_SCHEMA).write_parquet(out_dir / "minutes.parquet")
    included = games.filter(pl.col("status") == INCLUDED).height
    return {"replays": games.height, "games": included, "players": players.height}


def _day_frames(found: Mapping[str, GameApm]) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """The games, players and minutes of one day's replays, in replay order (a day's
    replays come after the days before it in name order too)."""
    games, players, minutes = [], [], []
    for name in sorted(found):
        result = found[name]
        games.append(result.game)
        players += result.players
        if result.minutes:
            minutes.append(pl.DataFrame(result.minutes, schema=MINUTE_SCHEMA))
    return (
        pl.DataFrame(games, schema=GAME_SCHEMA),
        pl.DataFrame(players, schema=PLAYER_SCHEMA),
        _concat(minutes, MINUTE_SCHEMA),
    )


def _concat(parts: Sequence[pl.DataFrame], schema: Mapping[str, Any]) -> pl.DataFrame:
    return pl.concat(parts) if parts else pl.DataFrame(schema=schema)


def skill_band(column: str = "skill") -> pl.Expr:
    expression = pl.lit(None, dtype=pl.String)
    for name, low, high in reversed(SKILL_BANDS):
        expression = (
            pl.when((pl.col(column) >= low) & (pl.col(column) < high))
            .then(pl.lit(name))
            .otherwise(expression)
        )
    return expression.alias("skill_band")


def phase(column: str = "minute") -> pl.Expr:
    expression = pl.lit(None, dtype=pl.String)
    for name, first, end in reversed(PHASES):
        expression = (
            pl.when((pl.col(column) >= first) & (pl.col(column) < end))
            .then(pl.lit(name))
            .otherwise(expression)
        )
    return expression.alias("phase")


def _quantile_columns(column: str, quantiles: Sequence[float] = QUANTILES) -> list[pl.Expr]:
    return [
        pl.col(column).quantile(share, interpolation="nearest").alias(f"p{round(100 * share)}")
        for share in quantiles
    ]


def quantile_rows(
    frame: pl.DataFrame,
    group: str,
    column: str,
    order: Sequence[str],
    quantiles: Sequence[float] = QUANTILES,
    scale: float = 1.0,
) -> list[list[str]]:
    """One row per group (in `order`): count, mean and quantiles of `column` times `scale`."""
    found = {
        row[group]: row
        for row in frame.group_by(group)
        .agg(
            pl.len().alias("count"),
            pl.col(column).mean().alias("mean"),
            *_quantile_columns(column, quantiles),
        )
        .iter_rows(named=True)
    }
    rows = []
    for name in order:
        row = found.get(name)
        if row is None:
            continue
        rows.append(
            [name, f"{row['count']:,}", _number(row["mean"] * scale)]
            + [_number(row[f"p{round(100 * share)}"] * scale) for share in quantiles]
        )
    return rows


def _number(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.0f}" if abs(value) >= 10 else f"{value:.1f}"


def _quantile_header(first: str, quantiles: Sequence[float] = QUANTILES) -> list[str]:
    return [first, "n", "mean", *(_quantile_name(share) for share in quantiles)]


def _quantile_name(share: float) -> str:
    return {0.25: "p25", 0.5: "median", 0.75: "p75"}.get(share, f"p{round(100 * share)}")


def _with_all(frame: pl.DataFrame, group: str, label: str = "all") -> pl.DataFrame:
    return pl.concat([frame, frame.with_columns(pl.lit(label).alias(group))])


def report(out_dir: Path) -> str:
    """The tables of docs/research/apm.md from the output of `measure()`."""
    games = pl.read_parquet(out_dir / "games.parquet")
    players = pl.read_parquet(out_dir / "players.parquet").with_columns(skill_band())
    minutes = pl.read_parquet(out_dir / "minutes.parquet").with_columns(skill_band(), phase())
    band_order = [name for name, _, _ in SKILL_BANDS] + ["all"]
    phase_order = [name for name, _, _ in PHASES] + ["all"]
    lines = ["## Sample", ""]
    lines += markdown.table(
        ["status", "games"],
        [
            [status, f"{count:,}"]
            for status, count in games.group_by("status")
            .len()
            .sort("len", descending=True)
            .iter_rows()
        ],
    )
    used = games.filter(pl.col("status") == INCLUDED)
    lines += ["", "Games used, by players per team:", ""]
    lines += markdown.table(
        ["players per team", "games"],
        [
            [str(size), f"{count:,}"]
            for size, count in used.group_by("team_size").len().sort("team_size").iter_rows()
        ],
    )
    known = players.filter(pl.col("skill").is_not_null())
    lines += [
        "",
        f"{players.height:,} player-games ({known.height:,} with a skill), "
        f"{minutes.height:,} player-minutes.",
        "",
        "Player-games by skill band:",
        "",
    ]
    lines += markdown.table(
        ["skill band", "player-games", "player-minutes"],
        [
            [
                name,
                f"{players.filter(pl.col('skill_band') == name).height:,}",
                f"{minutes.filter(pl.col('skill_band') == name).height:,}",
            ]
            for name, _, _ in SKILL_BANDS
        ],
    )

    minute_header = _quantile_header("phase")
    for kind in KINDS:
        lines += ["", f"## Actions per minute, `{kind}`, by game phase", ""]
        lines += markdown.table(
            minute_header, quantile_rows(_with_all(minutes, "phase"), "phase", kind, phase_order)
        )

    for kind in ("clicked", "all"):
        lines += ["", f"## Actions per minute, `{kind}`, by skill band (every minute)", ""]
        lines += markdown.table(
            _quantile_header("skill band"),
            quantile_rows(_with_all(minutes, "skill_band"), "skill_band", kind, band_order),
        )
        for share in (0.5, 0.9):
            lines += [
                "",
                f"## Actions per minute, `{kind}`, by skill band and phase: "
                + _quantile_name(share),
                "",
            ]
            found = {
                (row["skill_band"], row["phase"]): row["value"]
                for row in minutes.group_by("skill_band", "phase")
                .agg(pl.col(kind).quantile(share, interpolation="nearest").alias("value"))
                .iter_rows(named=True)
            }
            lines += markdown.table(
                ["skill band", *phase_order[:-1]],
                [
                    [band, *(_number(found.get((band, name))) for name in phase_order[:-1])]
                    for band, _, _ in SKILL_BANDS
                ],
            )

    played = players.filter(pl.col("minutes") > 0).with_columns(
        *(
            (pl.col(kind) * FRAMES_PER_MINUTE / pl.col("end_frame")).alias(f"{kind}_apm")
            for kind in KINDS
        )
    )
    for kind in ("clicked", "all"):
        lines += ["", f"## Average actions per minute over a game, `{kind}`, by skill band", ""]
        lines += markdown.table(
            _quantile_header("skill band"),
            quantile_rows(_with_all(played, "skill_band"), "skill_band", f"{kind}_apm", band_order),
        )

    for kind in ("clicked", "clicked_raw", "all"):
        for seconds in BURST_SECONDS:
            lines += [
                "",
                f"## Most `{kind}` actions in any {seconds} s of a game, by skill band",
                "",
            ]
            lines += markdown.table(
                _quantile_header("skill band"),
                quantile_rows(
                    _with_all(played, "skill_band"),
                    "skill_band",
                    f"{kind}_max_{seconds}s",
                    band_order,
                ),
            )

    for kind in MINUTE_BURST_KINDS:
        for seconds in MINUTE_BURST_SECONDS:
            lines += [
                "",
                f"## Most `{kind}` actions in any {seconds} s of a minute, by game phase",
                "",
            ]
            lines += markdown.table(
                minute_header,
                quantile_rows(
                    _with_all(minutes, "phase"), "phase", f"{kind}_max_{seconds}s", phase_order
                ),
            )

    lines += ["", "## Share of minutes without a `clicked` action, by phase", ""]
    idle = {
        row["phase"]: row["idle"]
        for row in _with_all(minutes, "phase")
        .group_by("phase")
        .agg((pl.col("clicked") == 0).mean().alias("idle"))
        .iter_rows(named=True)
    }
    lines += markdown.table(
        ["phase", "share"],
        [[name, f"{100 * idle[name]:.1f}%"] for name in phase_order if name in idle],
    )
    return "\n".join(lines)


def summary_lines(counts: Mapping[str, int]) -> str:
    return (
        f"{counts['replays']:,} replays read, {counts['games']:,} games used, "
        f"{counts['players']:,} player-games"
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    tables.add_source_arguments(parser)
    parser.add_argument("--out", type=Path, default=data_dir() / "apm")
    parser.add_argument("--jobs", type=int, default=4, help="days read in parallel (default: 4)")
    parser.add_argument(
        "--report", action="store_true", help="print the tables from an earlier run"
    )


def run(args: argparse.Namespace) -> int:
    if args.report:
        print(report(args.out))
        return 0
    counts = measure(
        args.out,
        tables_dir=args.tables,
        jobs=args.jobs,
        since=args.since,
        until=args.until,
    )
    print(summary_lines(counts))
    return 0
