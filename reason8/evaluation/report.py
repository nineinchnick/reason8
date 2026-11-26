"""Compare the evaluated AI with its opponent, team by team, from `reason8 eval games`.

Usage::

    uv run reason8 eval report data/eval/reason8-vs-barb                    # at 4:00
    uv run reason8 eval report data/eval/reason8-vs-barb --at-seconds 300   # at 5:00
    uv run reason8 eval report data/eval/barb-vs-barb    # the A/A test

In the two games of a seed each AI plays every position once with the same faction
(`reason8.evaluation.games`), so every position, faction and seed gives a pair: the
evaluated AI's team and the opponent's team on the same spot. The evaluated AI is told
apart by its ally team, not by its name, so the A/A test (stock BARb on both sides) pairs
the same way.

For each measure the report gives the evaluated AI's total over the pairs as a share of the
opponent's (100% is equal), with a 95% interval from resampling seeds: the 16 pairs of a
seed share two games and are not independent. ADR 0003 asks for economy at 4:00 at least
BARb's: the interval of the share should not lie below 100%. Every team is measured at the
same game time from the state files the games keep; the economy at each team's own first
contact follows, for information.

The A/A test sets how many seeds that takes. From the spread of the per-seed shares,
``seeds for 10%`` is the number of seeds at which a true 10% difference would be found
95% of the time with 80% power (a two-sided normal approximation).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import polars as pl

from reason8.evaluation.games import TEAMS_NAME, measure_again
from reason8.game.positions import position_order
from reason8.game.unitdefs import game_unit_defs
from reason8.markdown import table

MEASURES = ("metal_income", "energy_income", "built_metal", "built_energy", "units")
AT_SECONDS = 240  # ADR 0003: the economy at 4:00
ROUNDS = 2000
PAIR_KEY = ("seed", "faction", "position")


def pairs(teams: pl.DataFrame) -> pl.DataFrame:
    """One row per seed, faction and position: the evaluated AI's measures and the
    opponent's (suffix ``_opponent``). The evaluated AI is the first ally team in game ``a``
    and the second in game ``b``."""
    evaluated = (pl.col("game") == "a") == (pl.col("ally_team") == 0)
    columns = [*PAIR_KEY, "contact_frame", *MEASURES]
    ours = teams.filter(evaluated).select(*columns, "ai")
    theirs = teams.filter(~evaluated).select(*columns, pl.col("ai").alias("opponent"))
    return ours.join(theirs, on=PAIR_KEY, suffix="_opponent")


def share_interval(
    paired: pl.DataFrame, measure: str, rounds: int = ROUNDS, seed: int = 0
) -> tuple[float, float, float]:
    """The evaluated total as a share of the opponent's, and a 95% interval from
    resampling seeds."""
    per_seed = paired.group_by("seed").agg(
        pl.col(measure).sum().alias("ours"), pl.col(f"{measure}_opponent").sum().alias("theirs")
    )
    ours = per_seed["ours"].to_numpy()
    theirs = per_seed["theirs"].to_numpy()
    share = ours.sum() / theirs.sum() if theirs.sum() else math.nan
    generator = np.random.default_rng(seed)
    picks = generator.integers(0, len(ours), size=(rounds, len(ours)))
    shares = ours[picks].sum(axis=1) / np.maximum(theirs[picks].sum(axis=1), 1e-9)
    low, high = np.quantile(shares, [0.025, 0.975])
    return float(share), float(low), float(high)


def seeds_for(paired: pl.DataFrame, measure: str, effect: float = 0.10) -> int | None:
    """Seeds needed to find a true `effect` (relative) difference, from the spread of the
    per-seed log share."""
    per_seed = paired.group_by("seed").agg(
        pl.col(measure).sum().alias("ours"), pl.col(f"{measure}_opponent").sum().alias("theirs")
    )
    per_seed = per_seed.filter(pl.col("ours") > 0, pl.col("theirs") > 0)
    if per_seed.height < 3:
        return None
    log_share = np.log(per_seed["ours"].to_numpy() / per_seed["theirs"].to_numpy())
    spread = float(np.std(log_share, ddof=1))
    return math.ceil(((1.96 + 0.84) * spread / math.log(1 + effect)) ** 2)


def _percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def report(teams: pl.DataFrame, when: str = "at first contact") -> str:
    paired = pairs(teams)
    if paired.is_empty():
        return "No pairs: play both games of a seed first."
    ai = paired["ai"][0]
    opponent = paired["opponent"][0]
    seeds = paired["seed"].n_unique()
    lines = [
        f"{ai} (evaluated) against {opponent}: {seeds} seeds, {paired.height} pairs of teams "
        "on the same position with the same faction.",
        "",
        f"## Economy {when}",
        "",
    ]
    rows = []
    for measure in MEASURES:
        share, low, high = share_interval(paired, measure)
        needed = seeds_for(paired, measure)
        rows.append(
            [
                measure,
                f"{paired[measure].mean():.1f}",
                f"{paired[f'{measure}_opponent'].mean():.1f}",
                f"{_percent(share)} ({_percent(low)}–{_percent(high)})",
                str(needed) if needed is not None else "",
            ]
        )
    lines += table(["measure", ai, opponent, f"{ai} / {opponent}", "seeds for 10%"], rows)
    contact = paired.select(
        pl.col("contact_frame").is_not_null().mean().alias("ours"),
        pl.col("contact_frame_opponent").is_not_null().mean().alias("theirs"),
        (pl.col("contact_frame").median() / 30).alias("ours_seconds"),
        (pl.col("contact_frame_opponent").median() / 30).alias("theirs_seconds"),
    ).row(0, named=True)
    lines += [
        "",
        f"Contact before the end of the game: {_percent(contact['ours'])} of {ai}'s teams, "
        f"{_percent(contact['theirs'])} of {opponent}'s; median contact at "
        f"{contact['ours_seconds'] or 0:.0f} s and {contact['theirs_seconds'] or 0:.0f} s.",
        "",
        "## By position (built metal)",
        "",
    ]
    rows = []
    for (faction, position), group in sorted(
        paired.group_by("faction", "position"),
        key=lambda item: (item[0][0], position_order(item[0][1])),
    ):
        if group["seed"].n_unique() < 2:
            continue
        share, low, high = share_interval(group, "built_metal")
        rows.append(
            [
                faction,
                position,
                str(group.height),
                f"{group['built_metal'].mean():.0f}",
                f"{group['built_metal_opponent'].mean():.0f}",
                f"{_percent(share)} ({_percent(low)}–{_percent(high)})",
            ]
        )
    lines += table(["faction", "position", "pairs", ai, opponent, f"{ai} / {opponent}"], rows)
    return "\n".join(lines)


def contact_lines(teams: pl.DataFrame) -> list[str]:
    """The economy table at each team's own first contact."""
    paired = pairs(teams)
    if paired.is_empty():
        return []
    ai, opponent = paired["ai"][0], paired["opponent"][0]
    rows = []
    for measure in MEASURES:
        share, low, high = share_interval(paired, measure)
        rows.append([measure, f"{_percent(share)} ({_percent(low)}–{_percent(high)})"])
    return [
        "## For information: at each team's first contact",
        "",
        *table(["measure", f"{ai} / {opponent}"], rows),
    ]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("games", type=Path, help="folder of `reason8 eval games`")
    parser.add_argument(
        "--at-seconds",
        type=int,
        default=AT_SECONDS,
        help=f"game time every team is measured at (default {AT_SECONDS}, ADR 0003)",
    )
    parser.add_argument("--data-dir", default="data/bar", help="content dir with the game")
    parser.add_argument(
        "--game",
        default="Beyond All Reason test-32018-ad135b9",
        help="the game version the games were played with (for unit costs)",
    )


def run(args: argparse.Namespace) -> int:
    unit_defs = game_unit_defs(Path(args.data_dir).resolve(), args.game)
    teams = measure_again(args.games, unit_defs, args.at_seconds * 30)
    minutes, seconds = divmod(args.at_seconds, 60)
    lines = [report(teams, when=f"at {minutes}:{seconds:02d}"), ""]
    lines += contact_lines(pl.read_parquet(args.games / TEAMS_NAME))
    print("\n".join(lines))
    return 0
