"""Measure how many commands and distinct orders one action holds, for players and the bot.

Usage::

    uv run reason8 analysis orders --every 16 --out data/orders     # players, every 16th day
    uv run reason8 analysis orders --out data/orders \\
        --bot lobby=data/runs/lobby-2026-11-27 --bot headless=data/eval/end-opening/after
    uv run reason8 analysis orders --out data/orders --report      # docs/research tables

ADR 0008 counts the commands of one frame as at most one action
(`reason8.analysis.apm.ActionCounter`). This pass looks inside the frames: for every frame
in which a player (or a bot's team) gave commands, how many commands there are, how many
units they go to, and how many *distinct orders* they hold. An order is the command with
its unit to build, parameters, options and, for an INSERT, its position and options; which
units get it is left out, so one click to 20 selected units is one order, while a dragged
line of 10 buildings is 10. A *kind* of order leaves out the parameters as well: the line
of 10 buildings of one type is one kind, and so is a formation move that gives every unit
its own spot.

A player's commands come in three sources, as in `reason8.analysis.apm`: ``clicked``
(``COMMAND`` packets, to the current selection), ``widget`` (``AICOMMAND``/``AICOMMANDS``
with ``ai`` 255) and, for a bot, ``bot`` (the AI's own ``AICOMMAND`` packets). Every frame
is marked with whether it is an action when all of the commander's commands are counted
(``action``, the count of ADR 0008 and BAR's own APM) and when only the clicked ones are
(``clicked_action``).

An *action span* is a counted action with everything that follows it until the next one:
the commands of later frames that the 7-frame rule lets through without counting. It is
what one counted action pays for.

The output, in ``--out``:

``frames/<day>.parquet``
    One row per player and frame with commands, from the parsed replays of a day.
``spans/<day>.parquet``
    One row per player and action span.
``bot_frames.parquet``, ``bot_spans.parquet``
    The same for the bot's teams in the replays given with ``--bot``, with the label.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from reason8 import markdown
from reason8.analysis.apm import (
    FRAMES_PER_MINUTE,
    PHASES,
    SKILL_BANDS,
    WIDGET_AI,
    ActionCounter,
    game_exclusion,
    phase,
    skill_band,
)
from reason8.paths import data_dir
from reason8.replays import tables
from reason8.replays.replay import Replay, parse_skill

CLICKED = "clicked"
WIDGET = "widget"
BOT = "bot"

#: Why a frame holds more than one distinct order (see `category`).
ONE_ORDER = "one order"
LINE = "line of one building"
TARGETS = "one kind, several targets"
BUILDINGS = "several buildings"
DIFFERENT = "different kinds"
CATEGORIES = (ONE_ORDER, LINE, TARGETS, BUILDINGS, DIFFERENT)

#: Bins of distinct orders per action in the report: (name, lowest, highest).
ORDER_BINS = (
    ("1", 1, 1),
    ("2", 2, 2),
    ("3-5", 3, 5),
    ("6-10", 6, 10),
    ("11-20", 11, 20),
    ("more", 21, 10**9),
)
BOOTSTRAP_ROUNDS = 1000
#: Replays whose commands are read at once: a day's commands at once take over 10 GB.
REPLAYS_PER_READ = 20


def order_columns() -> list[pl.Expr]:
    """``order`` and ``kind`` hashes and ``structure`` of the rows of a commands table."""
    kind = pl.struct(
        pl.col("command_id"), pl.col("unit"), pl.col("options"), pl.col("inserted")
    ).hash(seed=0)
    order = pl.struct(
        pl.col("command_id"),
        pl.col("unit"),
        pl.col("options"),
        pl.col("inserted"),
        pl.col("params"),
        pl.col("insert_options"),
        pl.col("insert_position"),
    ).hash(seed=0)
    return [
        order.alias("order"),
        kind.alias("kind"),
        pl.col("x").is_not_null().alias("structure"),
    ]


@dataclass(frozen=True)
class Command:
    """One command, as the counting reads it."""

    frame: int
    source: str
    units: Sequence[int]
    order: int
    kind: int
    structure: bool
    command: str


def category(orders: int, kinds: int, structures: int, commands: int) -> str:
    """Why a frame holds the orders it does.

    ``one order`` (to one unit or a selection); ``line of one building`` (several spots of
    one kind of building, a dragged line); ``one kind, several targets`` (the same command
    to several spots or units, as a formation move or a spread of targets); ``several
    buildings`` (structures of different kinds, as a blueprint); ``different kinds`` (any
    other mix).
    """
    if orders <= 1:
        return ONE_ORDER
    all_structures = structures == commands
    if kinds == 1:
        return LINE if all_structures else TARGETS
    return BUILDINGS if all_structures else DIFFERENT


@dataclass
class _Frame:
    frame: int
    commands: int = 0
    unit_orders: int = 0
    clicked_unit_orders: int = 0
    clicked: int = 0
    widget: int = 0
    bot: int = 0
    structures: int = 0
    action: bool = False
    clicked_action: bool = False
    orders: set[int] = field(default_factory=set)
    kinds: set[int] = field(default_factory=set)
    clicked_orders: set[int] = field(default_factory=set)
    clicked_kinds: set[int] = field(default_factory=set)
    names: set[str] = field(default_factory=set)


@dataclass
class _Span:
    frame: int
    frames: int = 0
    commands: int = 0
    unit_orders: int = 0
    orders: set[int] = field(default_factory=set)
    kinds: set[int] = field(default_factory=set)
    last_frame: int = 0


def _sources(frame: _Frame) -> str:
    present = [name for name in (CLICKED, WIDGET, BOT) if getattr(frame, name)]
    return present[0] if len(present) == 1 else "both"


class OrderCounter:
    """The frames and action spans of one commander's commands, in stream order."""

    def __init__(self) -> None:
        self.all = ActionCounter()
        self.clicked = ActionCounter()
        self.frames: list[dict[str, Any]] = []
        self.spans: list[dict[str, Any]] = []
        self._frame: _Frame | None = None
        self._span: _Span | None = None

    def add(self, command: Command) -> None:
        if self._frame is not None and self._frame.frame != command.frame:
            self._close_frame()
        if self._frame is None:
            self._frame = _Frame(command.frame)
        frame = self._frame
        if self.all.command(command.frame, command.units):
            frame.action = True
        if command.source == CLICKED and self.clicked.command(command.frame, command.units):
            frame.clicked_action = True
        frame.commands += 1
        frame.unit_orders += len(command.units)
        setattr(frame, command.source, getattr(frame, command.source) + 1)
        frame.structures += command.structure
        frame.orders.add(command.order)
        frame.kinds.add(command.kind)
        frame.names.add(command.command)
        if command.source == CLICKED:
            frame.clicked_unit_orders += len(command.units)
            frame.clicked_orders.add(command.order)
            frame.clicked_kinds.add(command.kind)

    def finish(self) -> OrderCounter:
        if self._frame is not None:
            self._close_frame()
        if self._span is not None:
            self._close_span()
        return self

    def _close_frame(self) -> None:
        frame = self._frame
        assert frame is not None
        self._frame = None
        kinds = len(frame.kinds)
        self.frames.append(
            {
                "frame": frame.frame,
                "action": frame.action,
                "clicked_action": frame.clicked_action,
                "commands": frame.commands,
                "unit_orders": frame.unit_orders,
                "clicked_unit_orders": frame.clicked_unit_orders,
                "clicked": frame.clicked,
                "widget": frame.widget,
                "bot": frame.bot,
                "orders": len(frame.orders),
                "kinds": kinds,
                "clicked_orders": len(frame.clicked_orders),
                "clicked_kinds": len(frame.clicked_kinds),
                "sources": _sources(frame),
                "category": category(len(frame.orders), kinds, frame.structures, frame.commands),
                "names": " ".join(sorted(frame.names)) if len(frame.orders) > 1 else None,
            }
        )
        if frame.action:
            if self._span is not None:
                self._close_span()
            self._span = _Span(frame.frame)
        span = self._span
        if span is None:  # commands before the first action pay for none
            return
        span.frames += 1
        span.commands += frame.commands
        span.unit_orders += frame.unit_orders
        span.orders |= frame.orders
        span.kinds |= frame.kinds
        span.last_frame = frame.frame

    def _close_span(self) -> None:
        span = self._span
        assert span is not None
        self._span = None
        self.spans.append(
            {
                "frame": span.frame,
                "frames": span.frames,
                "length": span.last_frame - span.frame + 1,
                "commands": span.commands,
                "unit_orders": span.unit_orders,
                "orders": len(span.orders),
                "kinds": len(span.kinds),
            }
        )


def count_commands(
    rows: Iterable[tuple[Any, ...]],
) -> dict[Any, OrderCounter]:
    """Commander -> its frames and spans, from rows in stream order.

    A row is ``(commander, type, frame, via, ai, units, order, kind, structure, command)``,
    ``type`` being ``cmd`` or ``select``. A ``COMMAND`` goes to the commander's last
    selection; a command to no unit is left out, as it does nothing.
    """
    counters: dict[Any, OrderCounter] = {}
    selections: dict[Any, Sequence[int]] = {}
    for commander, kind_of_row, frame, via, ai, units, order, kind, structure, name in rows:
        if kind_of_row == "select":
            selections[commander] = units or ()
            continue
        if frame is None or frame < 0:
            continue
        if via == "COMMAND":
            source, units = CLICKED, selections.get(commander, ())
        elif ai == WIDGET_AI:
            source = WIDGET
        else:
            source = BOT
        units = units or ()
        if not units:
            continue
        counter = counters.get(commander)
        if counter is None:
            counter = counters[commander] = OrderCounter()
        counter.add(Command(frame, source, units, order, kind, bool(structure), name or ""))
    return {commander: counter.finish() for commander, counter in counters.items()}


STREAM_FIELDS = (
    "type",
    "frame",
    "via",
    "ai",
    "units",
    "order",
    "kind",
    "structure",
    "command",
)


def _stream(commands: pl.LazyFrame, selections: pl.LazyFrame, commander: str) -> pl.LazyFrame:
    command_rows = commands.select(
        "replay",
        "seq",
        pl.col(commander).alias("commander"),
        pl.lit("cmd").alias("type"),
        "frame",
        pl.col("via").cast(pl.String),
        "ai",
        "units",
        *order_columns(),
        "command",
    )
    selection_rows = selections.select(
        "replay",
        "seq",
        pl.col("player").alias("commander"),
        pl.lit("select").alias("type"),
        "frame",
        "units",
    )
    return pl.concat([command_rows, selection_rows], how="diagonal_relaxed").sort(
        "replay", "seq", maintain_order=True
    )


def _rows(stream: pl.DataFrame) -> Iterator[tuple[str, Iterator[tuple[Any, ...]]]]:
    for (name,), rows in stream.group_by("replay", maintain_order=True):
        columns = [rows[column].to_list() for column in ("commander", *STREAM_FIELDS)]
        yield str(name), zip(*columns, strict=True)


FRAME_SCHEMA = {
    "frame": pl.Int32,
    "action": pl.Boolean,
    "clicked_action": pl.Boolean,
    "commands": pl.Int32,
    "unit_orders": pl.Int32,
    "clicked_unit_orders": pl.Int32,
    "clicked": pl.Int32,
    "widget": pl.Int32,
    "bot": pl.Int32,
    "orders": pl.Int32,
    "kinds": pl.Int32,
    "clicked_orders": pl.Int32,
    "clicked_kinds": pl.Int32,
    "sources": pl.String,
    "category": pl.String,
    "names": pl.String,
}
SPAN_SCHEMA = {
    "frame": pl.Int32,
    "frames": pl.Int32,
    "length": pl.Int32,
    "commands": pl.Int32,
    "unit_orders": pl.Int32,
    "orders": pl.Int32,
    "kinds": pl.Int32,
}


def _frames_of(
    counters: Mapping[Any, OrderCounter], keys: Mapping[str, Any], commander: str
) -> tuple[list[pl.DataFrame], list[pl.DataFrame]]:
    frames, spans = [], []
    for who, counter in sorted(counters.items()):
        extra = [pl.lit(value).alias(name) for name, value in keys.items()]
        extra.append(pl.lit(who, dtype=pl.Int32).alias(commander))
        frames.append(pl.DataFrame(counter.frames, schema=FRAME_SCHEMA).with_columns(extra))
        spans.append(pl.DataFrame(counter.spans, schema=SPAN_SCHEMA).with_columns(extra))
    return frames, spans


def day_orders(
    source: tables.Source, chunk: int = REPLAYS_PER_READ
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The frames and spans of every player of the games of a source (one day), read
    `chunk` replays at a time to keep memory low."""
    headers = tables.replay_headers(
        source.scan(tables.GAMES).collect(), source.scan(tables.PLAYERS).collect()
    )
    included = sorted(name for name, header in headers.items() if game_exclusion(header) is None)
    frames: list[pl.DataFrame] = []
    spans: list[pl.DataFrame] = []
    for start in range(0, len(included), chunk):
        replays = included[start : start + chunk]
        commands = source.scan(tables.COMMANDS, replays).filter(
            pl.col("ai").is_null() | (pl.col("ai") == WIDGET_AI)
        )
        stream = _stream(commands, source.scan(tables.SELECTIONS, replays), "player").collect()
        for name, rows in _rows(stream):
            skills = {
                player["playerId"]: parse_skill(player.get("skill"))
                for player in headers[name].players
            }
            counters = {
                who: counter
                for who, counter in count_commands(rows).items()
                if who in skills  # players, not spectators
            }
            found_frames, found_spans = _frames_of(counters, {"replay": name}, "player")
            frames += [
                part.with_columns(pl.lit(skills[who], dtype=pl.Float64).alias("skill"))
                for who, part in zip(sorted(counters), found_frames, strict=True)
            ]
            spans += [
                part.with_columns(pl.lit(skills[who], dtype=pl.Float64).alias("skill"))
                for who, part in zip(sorted(counters), found_spans, strict=True)
            ]
        del stream
    return _concat(frames, FRAME_SCHEMA, "player"), _concat(spans, SPAN_SCHEMA, "player")


def _concat(parts: list[pl.DataFrame], schema: Mapping[str, Any], commander: str) -> pl.DataFrame:
    if not parts:
        return pl.DataFrame(
            schema={**schema, "replay": pl.String, "skill": pl.Float64, commander: pl.Int32}
        )
    return pl.concat(parts, how="vertical_relaxed")


def bot_orders(replay: Replay, name: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The frames and spans of every AI team of a replay (its own commands, not widgets')."""
    frames_of_tables = tables.replay_tables(replay, name)
    commands = (
        frames_of_tables[tables.COMMANDS]
        .lazy()
        .filter(pl.col("ai").is_not_null() & (pl.col("ai") != WIDGET_AI))
    )
    no_selections = frames_of_tables[tables.SELECTIONS].lazy().head(0)
    stream = _stream(commands, no_selections, "team").collect()
    ai_names = {ai["teamId"]: ai.get("shortName") for ai in replay.ais}
    frames: list[pl.DataFrame] = []
    spans: list[pl.DataFrame] = []
    for _, rows in _rows(stream):
        for team, counter in count_commands(rows).items():
            keys = {"replay": name, "ai_name": ai_names.get(team)}
            found_frames, found_spans = _frames_of({team: counter}, keys, "team")
            frames += found_frames
            spans += found_spans
    return (
        pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame(),
        pl.concat(spans, how="vertical_relaxed") if spans else pl.DataFrame(),
    )


def measure(
    out_dir: Path,
    *,
    tables_dir: Path | None = None,
    jobs: int = 1,
    since=None,
    until=None,
    every: int = 1,
) -> dict[str, int]:
    """Count the frames and spans of every player in the parsed replays of every
    `every`-th day, a day per process, into ``out_dir/frames`` and ``out_dir/spans``."""
    source = tables.open_source(
        tables_dir,
        since=since,
        until=until,
        tables=(tables.GAMES, tables.PLAYERS, tables.COMMANDS, tables.SELECTIONS),
    )
    days = source.by_day()[:: max(1, every)]
    for directory in ("frames", "spans"):
        (out_dir / directory).mkdir(parents=True, exist_ok=True)
    counts = {"days": 0, "frames": 0, "spans": 0}
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        for day, (frames, spans) in zip(days, pool.map(day_orders, days), strict=True):
            name = tables.partition(next(iter(day.stored))).removeprefix(tables.PARTITION_PREFIX)
            frames.write_parquet(out_dir / "frames" / f"{name}.parquet")
            spans.write_parquet(out_dir / "spans" / f"{name}.parquet")
            counts["days"] += 1
            counts["frames"] += frames.height
            counts["spans"] += spans.height
            print(f"{counts['days']} of {len(days)} days: {name}", file=sys.stderr)
    return counts


def measure_bots(
    out_dir: Path, replays: Iterable[tuple[str, Path]], parser: Path | None = None
) -> dict[str, int]:
    """Parse the bot replays (label, file) and write their frames and spans."""
    from reason8.replays.parse import default_parser, parse_replay

    parser = parser or default_parser()
    frames: list[pl.DataFrame] = []
    spans: list[pl.DataFrame] = []
    for label, path in replays:
        document, _ = parse_replay(parser, path)
        found_frames, found_spans = bot_orders(Replay(document), path.stem)
        frames.append(found_frames.with_columns(pl.lit(label).alias("label")))
        spans.append(found_spans.with_columns(pl.lit(label).alias("label")))
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = pl.concat(frames, how="vertical_relaxed")
    span = pl.concat(spans, how="vertical_relaxed")
    frame.write_parquet(out_dir / "bot_frames.parquet")
    span.write_parquet(out_dir / "bot_spans.parquet")
    return {"replays": len(frames), "frames": frame.height, "spans": span.height}


def bot_replays(arguments: Iterable[str]) -> list[tuple[str, Path]]:
    """``label=path`` -> (label, replay file); a directory stands for its ``.sdfz`` files."""
    found = []
    for argument in arguments:
        label, _, path = argument.partition("=")
        location = Path(path)
        files = sorted(location.rglob("*.sdfz")) if location.is_dir() else [location]
        found += [(label, file) for file in files]
    return found


# --- the report


def ratio_interval(
    games: Sequence[Any],
    numerator: Sequence[float],
    denominator: Sequence[float],
    rounds: int = BOOTSTRAP_ROUNDS,
    seed: int = 0,
) -> tuple[float, float, float]:
    """sum(numerator) / sum(denominator) and a 95% interval from resampling whole games."""
    _, game_of_row = np.unique(np.asarray(games), return_inverse=True)
    count = int(game_of_row.max()) + 1 if len(game_of_row) else 0
    if not count:
        return math.nan, math.nan, math.nan
    tops = np.bincount(game_of_row, weights=np.asarray(numerator, dtype=float), minlength=count)
    bottoms = np.bincount(
        game_of_row, weights=np.asarray(denominator, dtype=float), minlength=count
    )
    value = tops.sum() / bottoms.sum()
    generator = np.random.default_rng(seed)
    draws = generator.multinomial(count, np.full(count, 1 / count), size=rounds)
    values = (draws @ tops) / np.maximum(draws @ bottoms, 1e-12)
    low, high = np.quantile(values, [0.025, 0.975])
    return float(value), float(low), float(high)


def _per_game(per_game: pl.DataFrame, column: str, game: str) -> tuple[float, float, float]:
    return ratio_interval(
        per_game[game].to_list(),
        per_game[column].cast(pl.Float64).to_list(),
        per_game["n"].cast(pl.Float64).to_list(),
    )


def _percent(value: tuple[float, float, float]) -> str:
    middle, low, high = value
    return f"{100 * middle:.1f}% ({100 * low:.1f}–{100 * high:.1f})"


def _decimal(value: tuple[float, float, float]) -> str:
    middle, low, high = value
    return f"{middle:.2f} ({low:.2f}–{high:.2f})"


#: What each view of a frame counts: (which rows, orders, kinds, commands, unit orders).
FRAME_VIEWS = {
    "clicked": (
        pl.col("clicked_action"),
        "clicked_orders",
        "clicked_kinds",
        "clicked",
        "clicked_unit_orders",
    ),
    "action": (pl.col("action"), "orders", "kinds", "commands", "unit_orders"),
    "frame": (pl.lit(True), "orders", "kinds", "commands", "unit_orders"),
}
SPAN_VIEWS = {"span": (pl.lit(True), "orders", "kinds", "commands", "unit_orders")}


def histogram(
    rows: pl.LazyFrame, views: Mapping[str, tuple[pl.Expr, str, str, str, str]], keys: Sequence[str]
) -> pl.LazyFrame:
    """Rows counted by `keys`, view, distinct orders and whether they hold several kinds,
    with the sums of their commands and unit orders: everything the report's tables need,
    in a few rows per game."""
    parts = []
    for view, (condition, orders, kinds, commands, unit_orders) in views.items():
        parts.append(
            rows.filter(condition)
            .group_by(
                *keys,
                pl.col(orders).alias("orders"),
                (pl.col(kinds) > 1).alias("several_kinds"),
            )
            .agg(
                pl.len().cast(pl.Int64).alias("n"),
                pl.col(commands).cast(pl.Int64).sum().alias("commands"),
                pl.col(unit_orders).cast(pl.Int64).sum().alias("unit_orders"),
            )
            .with_columns(pl.lit(view).alias("view"))
        )
    return pl.concat(parts, how="vertical_relaxed")


def _quantile_of(counts: pl.DataFrame, share: float) -> str:
    ordered = counts.group_by("orders").agg(pl.col("n").sum()).sort("orders")
    cumulative = ordered["n"].cum_sum()
    index = int((cumulative >= share * cumulative[-1]).arg_max())
    return f"{ordered['orders'][index]:.0f}"


def summary_row(label: str, counts: pl.DataFrame, game: str = "replay") -> list[str]:
    """n, mean commands, unit orders and distinct orders per row (95% intervals from
    resampling games), the share with more than one order and more than one kind, and the
    p90, p99 and most orders; from rows of `histogram`."""
    if not counts.height:
        return [label, "0", *(["-"] * (len(SUMMARY_HEADER) - 2))]
    per_game = counts.group_by(game).agg(
        pl.col("n").sum(),
        pl.col("commands").sum(),
        pl.col("unit_orders").sum(),
        (pl.col("orders") * pl.col("n")).sum().alias("orders"),
        pl.col("n").filter(pl.col("orders") > 1).sum().alias("several"),
        pl.col("n").filter(pl.col("several_kinds")).sum().alias("several_kinds"),
    )
    return [
        label,
        f"{per_game['n'].sum():,}",
        _decimal(_per_game(per_game, "commands", game)),
        _decimal(_per_game(per_game, "unit_orders", game)),
        _decimal(_per_game(per_game, "orders", game)),
        _percent(_per_game(per_game, "several", game)),
        _percent(_per_game(per_game, "several_kinds", game)),
        _quantile_of(counts, 0.9),
        _quantile_of(counts, 0.99),
        f"{counts['orders'].max()}",
    ]


SUMMARY_HEADER = [
    "",
    "n",
    "commands",
    "unit orders",
    "orders",
    "more than one order",
    "more than one kind",
    "p90",
    "p99",
    "most",
]


def bin_row(label: str, counts: pl.DataFrame) -> list[str]:
    total = max(int(counts["n"].sum()), 1)
    cells = []
    for _, low, high in ORDER_BINS:
        count = counts.filter(pl.col("orders").is_between(low, high))["n"].sum()
        cells.append(f"{100 * count / total:.1f}%")
    return [label, *cells]


def _with_phase(rows: pl.LazyFrame) -> pl.LazyFrame:
    return rows.with_columns((pl.col("frame") // FRAMES_PER_MINUTE).alias("minute")).with_columns(
        phase()
    )


def _day_counts(
    frames_file: Path, spans_file: Path, automation: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict[str, int]]:
    """One day's histogram, why-table counts and command names, read lazily."""
    keys = ["replay", "skill_band", "phase", "automation"]
    frames = (
        _with_phase(pl.scan_parquet(frames_file))
        .with_columns(skill_band())
        .join(automation.lazy(), on=["replay", "player"], how="left")
        .with_columns(pl.col("automation").fill_null(False))
    )
    spans = (
        _with_phase(pl.scan_parquet(spans_file))
        .with_columns(skill_band())
        .with_columns(pl.lit(False).alias("automation"))
    )
    counts = pl.concat(
        [histogram(frames, FRAME_VIEWS, keys), histogram(spans, SPAN_VIEWS, keys)]
    ).collect(engine="streaming")
    actions = frames.filter(pl.col("action"), pl.col("orders") > 1)
    why = (
        actions.group_by("category", "sources")
        .agg(pl.len().alias("n"), pl.col("orders").sum())
        .collect(engine="streaming")
    )
    names = (
        actions.group_by("category", "names").agg(pl.len().alias("n")).collect(engine="streaming")
    )
    sample = (
        pl.scan_parquet(frames_file)
        .select(
            pl.col("replay").n_unique().alias("games"),
            pl.struct("replay", "player").n_unique().alias("player_games"),
        )
        .collect(engine="streaming")
        .row(0, named=True)
    )
    return counts, why, names, sample


def _why(why: pl.DataFrame, actions: int, sources: Sequence[str]) -> list[str]:
    total = max(actions, 1)
    rows = []
    for name in CATEGORIES[1:]:
        part = why.filter(pl.col("category") == name)
        count = int(part["n"].sum())
        cells = [
            f"{100 * part.filter(pl.col('sources') == source)['n'].sum() / total:.1f}%"
            for source in sources
        ]
        mean = part["orders"].sum() / count if count else 0
        rows.append([name, f"{100 * count / total:.1f}%", *cells, f"{mean:.1f}"])
    columns = [source if source == "both" else f"{source} only" for source in sources]
    return markdown.table(["why", "of actions", *columns, "orders"], rows)


def _names(names: pl.DataFrame, category_name: str, top: int = 10) -> list[str]:
    """The most common sets of commands of actions of a category, with their share."""
    part = names.filter(pl.col("category") == category_name)
    total = max(int(part["n"].sum()), 1)
    counted = part.group_by("names").agg(pl.col("n").sum()).sort("n", descending=True).head(top)
    return markdown.table(
        ["commands in the frame", "share"],
        [[f"`{found}`", f"{100 * count / total:.1f}%"] for found, count in counted.iter_rows()],
    )


def report(out_dir: Path, widgets_dir: Path | None = None) -> str:
    """The tables of docs/research/command-governor.md from the output of `measure()`.

    Each day's files are reduced to histograms on their own (`histogram`), so the report
    never holds more than a day's aggregates and the histograms."""
    automation = automation_players(widgets_dir or data_dir() / "widgets")
    has_automation = automation is not None
    if automation is None:
        automation = pl.DataFrame(
            schema={"replay": pl.String, "player": pl.Int32, "automation": pl.Boolean}
        )
    count_parts, why_parts, name_parts = [], [], []
    sample = {"games": 0, "player_games": 0}
    for frames_file in sorted((out_dir / "frames").glob("*.parquet")):
        found = _day_counts(frames_file, out_dir / "spans" / frames_file.name, automation)
        count_parts.append(found[0])
        why_parts.append(found[1])
        name_parts.append(found[2])
        for key in sample:
            sample[key] += found[3][key]
    counts = pl.concat(count_parts, how="vertical_relaxed")
    why = pl.concat(why_parts, how="vertical_relaxed")
    names = pl.concat(name_parts, how="vertical_relaxed")

    def view(name: str) -> pl.DataFrame:
        return counts.filter(pl.col("view") == name)

    clicks, actions, spans, frames = (view(name) for name in ("clicked", "action", "span", "frame"))
    lines = [
        "## Sample",
        "",
        f"{sample['games']:,} games, {sample['player_games']:,} player-games, "
        f"{frames['n'].sum():,} frames with commands, {actions['n'].sum():,} counted actions "
        f"(all commands), {clicks['n'].sum():,} counted clicked actions.",
        "",
        "## Per counted action, players",
        "",
    ]
    lines += markdown.table(
        SUMMARY_HEADER,
        [
            summary_row("clicked action, clicked orders", clicks),
            summary_row("action, every command of the frame", actions),
            summary_row("action span (every command)", spans),
            summary_row("every frame with commands", frames),
        ],
    )
    lines += ["", "## Distinct orders per action, players", ""]
    lines += markdown.table(
        ["", *(name for name, _, _ in ORDER_BINS)],
        [
            bin_row("clicked action", clicks),
            bin_row("action", actions),
            bin_row("action span", spans),
        ],
    )
    for title, part in (
        ("clicked actions, clicked orders", clicks),
        ("actions, every command", actions),
    ):
        lines += ["", f"## By skill band: {title}", ""]
        lines += markdown.table(
            SUMMARY_HEADER,
            [
                summary_row(band, part.filter(pl.col("skill_band") == band))
                for band, _, _ in SKILL_BANDS
            ],
        )
        lines += ["", f"## By game phase: {title}", ""]
        lines += markdown.table(
            SUMMARY_HEADER,
            [summary_row(name, part.filter(pl.col("phase") == name)) for name, _, _ in PHASES],
        )
    lines += ["", "## Why an action holds more than one order, players", ""]
    lines += _why(why, int(actions["n"].sum()), (CLICKED, WIDGET, "both"))
    for name in (TARGETS, DIFFERENT):
        lines += ["", f"## Most common commands of actions of {name}, players", ""]
        lines += _names(names, name)
    if has_automation:
        lines += ["", "## Players with an automation widget enabled", ""]
        lines += markdown.table(
            SUMMARY_HEADER,
            [
                summary_row(
                    "with" if flag else "without", actions.filter(pl.col("automation") == flag)
                )
                for flag in (True, False)
            ],
        )
    if (out_dir / "bot_frames.parquet").exists():
        lines += ["", *bot_report(out_dir)]
    return "\n".join(lines)


def bot_report(out_dir: Path) -> list[str]:
    team_game = pl.concat_str("replay", pl.col("team").cast(pl.String), separator="#")
    frames = _with_phase(pl.scan_parquet(out_dir / "bot_frames.parquet")).with_columns(
        team_game.alias("team_game")
    )
    spans = _with_phase(pl.scan_parquet(out_dir / "bot_spans.parquet")).with_columns(
        team_game.alias("team_game")
    )
    keys = ["label", "ai_name", "team_game", "phase"]
    views = {"action": FRAME_VIEWS["action"]}
    counts = pl.concat(
        [histogram(frames, views, keys), histogram(spans, SPAN_VIEWS, keys)]
    ).collect(engine="streaming")
    actions = frames.filter(pl.col("action")).collect(engine="streaming")
    groups = sorted(counts.select("label", "ai_name").unique().iter_rows(), key=lambda item: item)
    rows, bins = [], []
    for label, ai_name in groups:
        part = counts.filter(pl.col("label") == label, pl.col("ai_name") == ai_name)
        for view_name in ("action", "span"):
            chosen = part.filter(pl.col("view") == view_name)
            rows.append(summary_row(f"{label}, {ai_name}, {view_name}", chosen, "team_game"))
            bins.append(bin_row(f"{label}, {ai_name}, {view_name}", chosen))
    lines = ["## Per counted action, the bot", ""]
    lines += markdown.table(SUMMARY_HEADER, rows)
    lines += ["", "## Distinct orders per action, the bot", ""]
    lines += markdown.table(["", *(name for name, _, _ in ORDER_BINS)], bins)
    for label, ai_name in groups:
        part = actions.filter(pl.col("label") == label, pl.col("ai_name") == ai_name)
        several = part.filter(pl.col("orders") > 1)
        why = several.group_by("category", "sources").agg(
            pl.len().alias("n"), pl.col("orders").sum()
        )
        names = several.group_by("category", "names").agg(pl.len().alias("n"))
        title = f"the bot ({label}, {ai_name})"
        lines += ["", f"## Why an action holds more than one order, {title}", ""]
        lines += _why(why, part.height, (BOT,))
        lines += ["", f"## Most common commands of actions of {DIFFERENT}, {title}", ""]
        lines += _names(names, DIFFERENT)
        chosen = counts.filter(
            pl.col("label") == label, pl.col("ai_name") == ai_name, pl.col("view") == "action"
        )
        lines += ["", f"## By game phase, {title}", ""]
        lines += markdown.table(
            SUMMARY_HEADER,
            [
                summary_row(name, chosen.filter(pl.col("phase") == name), "team_game")
                for name, _, _ in PHASES
                if chosen.filter(pl.col("phase") == name).height
            ],
        )
    few = [
        (label, ai_name)
        for label, ai_name in groups
        if actions.filter(pl.col("label") == label, pl.col("ai_name") == ai_name)[
            "team_game"
        ].n_unique()
        <= 10
    ]
    per_team = (
        actions.filter(
            pl.struct("label", "ai_name").is_in([{"label": a, "ai_name": b} for a, b in few])
        )
        .group_by("label", "ai_name", "replay", "team")
        .agg(
            pl.len().alias("actions"),
            pl.col("commands").sum().alias("commands"),
            pl.col("commands").mean().alias("commands_per_action"),
            pl.col("orders").mean().alias("orders_per_action"),
            (pl.col("orders") > 1).mean().alias("several"),
            pl.col("orders").quantile(0.95, interpolation="nearest").alias("p95"),
        )
        .sort("label", "ai_name", "replay", "team")
    )
    lines += ["", "## Per team-game, the bot", ""]
    lines += markdown.table(
        ["run", "AI", "team", "actions", "commands", "per action", "orders", "several", "p95"],
        [
            [
                row["label"],
                row["ai_name"],
                str(row["team"]),
                f"{row['actions']:,}",
                f"{row['commands']:,}",
                f"{row['commands_per_action']:.1f}",
                f"{row['orders_per_action']:.1f}",
                f"{100 * row['several']:.0f}%",
                str(row["p95"]),
            ]
            for row in per_team.iter_rows(named=True)
        ],
    )
    return lines


def automation_players(widgets_dir: Path) -> pl.DataFrame | None:
    """Replay and player id of every player with an automation widget enabled
    (`reason8.replays.widgets.AUTOMATION_WIDGETS`), or None without the widget tables."""
    from reason8.replays.widgets import AUTOMATION_WIDGETS

    reports = widgets_dir / "reports.parquet"
    if not reports.exists():
        return None
    return (
        pl.scan_parquet(reports)
        .select("replay_file_name", "player_id", "widgets")
        .explode("widgets")
        .filter(
            (pl.col("widgets").struct.field("state") == 1)
            & pl.col("widgets").struct.field("name").is_in(sorted(AUTOMATION_WIDGETS))
        )
        .select(
            pl.col("replay_file_name").str.strip_suffix(".sdfz").alias("replay"),
            pl.col("player_id").cast(pl.Int32).alias("player"),
            pl.lit(True).alias("automation"),
        )
        .unique()
        .collect()
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    tables.add_source_arguments(parser)
    parser.add_argument("--out", type=Path, default=data_dir() / "orders")
    parser.add_argument("--jobs", type=int, default=2, help="days read in parallel (default: 2)")
    parser.add_argument("--every", type=int, default=1, help="read every N-th day (default: 1)")
    parser.add_argument(
        "--bot",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="bot replays (a file, or a directory of them) to measure instead of the tables",
    )
    parser.add_argument(
        "--report", action="store_true", help="print the tables from an earlier run"
    )


def run(args: argparse.Namespace) -> int:
    if args.report:
        print(report(args.out))
        return 0
    if args.bot:
        counts = measure_bots(args.out, bot_replays(args.bot))
        print(
            f"{counts['replays']} replays, {counts['frames']:,} frames, {counts['spans']:,} spans"
        )
        return 0
    counts = measure(
        args.out,
        tables_dir=args.tables,
        jobs=args.jobs,
        since=args.since,
        until=args.until,
        every=args.every,
    )
    print(f"{counts['days']} days, {counts['frames']:,} frames, {counts['spans']:,} spans")
    return 0
