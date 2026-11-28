"""Scores of how well a player played the opening, from what they did in the game.

Usage::

    uv run reason8 analysis play-quality           # data/state -> <data dir>/play-quality/
    uv run reason8 analysis play-quality --report  # the tables of docs/research/play-quality.md

The skill we have for a player is the rating of their account. This pass computes, per
player and game, candidate scores taken from the re-simulated game instead
(``data/state``, `reason8.headless.tables`), over the opening window (the first
`WINDOW_MINUTES` of game time), and the report measures how each relates to the rating, how
well it repeats for the same player, how much the map and start position move it, and
whether it tells the winning team apart.

The scores (one row per replay and team; in BAR each player is a team):

``metal_income_<m>``, ``energy_income_<m>``
    Mean income over the `INCOME_SECONDS` before minute ``m`` (`MINUTES`).
``metal_spent``
    Metal spent (the sum of ``metal_expense`` over every second) in the window.
``metal_float``
    Share of the seconds from `SETTLE_SECONDS` to the end of the window with the metal store
    at least `FULL` full: income the player did not spend (BAR passes it to allies with
    room, or loses it when every ally is full too).
``metal_overflow``
    Metal that came in while the store was full and was not spent, as a share of the
    metal income over the same seconds.
``metal_stall``, ``energy_stall``
    Share of the seconds with the store at most `EMPTY` full: spending held back by income.
``spend_ratio``
    Metal spent over metal income, from `SETTLE_SECONDS` to the end of the window.
``first_factory``
    Seconds to the first factory finished (null: none in the state, which ends at 10 min).
``mex_<n>``
    Seconds to the ``n``-th metal extractor finished (`MEX_COUNTS`; null: fewer).
``mexes_at_5``
    Metal extractors finished by 5:00.
``idle_power``
    Share of the build power of the team's finished builders that was idle, over the
    window, weighted by time: an idle line of the state export starts idleness, the next
    order to the unit that gives it something to do ends it
    (`reason8.context.builders.idle_build_power`).
``idle_power_mobile``
    The same without factories: commander, construction units, towers and the rest.
``reclaim_orders``
    Reclaim and resurrect commands the player gave in the window, clicked or sent by a
    widget: what they were told to do, not what they got (the state of format 5 does not
    record reclaim).

The output, in ``<data dir>/play-quality/``: ``scores.parquet``, one row per player-game
with the scores, the player's rating, uncertainty, position, faction and result, and the
actions per minute of the window (`opening_apm`); ``later.parquet``, the player's rating
after this game and at the end of the match dump (`later_ratings`). Both hold player data
and stay in the data directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import polars as pl

from reason8.context import builders
from reason8.context.table import game_states, state_dir, state_stem, unit_changes
from reason8.headless import tables as state_tables
from reason8.markdown import table
from reason8.paths import data_dir
from reason8.replays import tables as replay_tables
from reason8.replays.replay import GAME_SPEED

WINDOW_MINUTES = 8
MINUTES = (3, 5, 8)
INCOME_SECONDS = 30
#: The first seconds are left out of floating and spending: the game starts with the store full.
SETTLE_SECONDS = 60
FULL = 0.95
EMPTY = 0.01
MEX_COUNTS = (3, 6)
GAMES_PER_CHUNK = 100
FACTORY = builders.FACTORY

SCORES = (
    *(f"metal_income_{minute}" for minute in MINUTES),
    *(f"energy_income_{minute}" for minute in MINUTES),
    "metal_spent",
    "metal_float",
    "metal_overflow",
    "metal_stall",
    "energy_stall",
    "spend_ratio",
    "first_factory",
    *(f"mex_{count}" for count in MEX_COUNTS),
    "mexes_at_5",
    "idle_power",
    "idle_power_mobile",
    "reclaim_orders",
)
#: Scores where less is better; the report flips their sign so that more is better for all.
LOWER_IS_BETTER = frozenset(
    {
        "metal_float",
        "metal_overflow",
        "metal_stall",
        "energy_stall",
        "first_factory",
        *(f"mex_{count}" for count in MEX_COUNTS),
        "idle_power",
        "idle_power_mobile",
    }
)


def is_extractor(unit_def: pl.Expr) -> pl.Expr:
    """Metal extractors of every faction and tech level (``armmex``, ``cormoho``, ``legmext15``,
    ``armamex``...)."""
    return unit_def.str.contains(r"^(arm|cor|leg)(a?mex|moho|mext)")


# --- the scores of some games


def resource_scores(resources: pl.DataFrame, window_minutes: int = WINDOW_MINUTES) -> pl.DataFrame:
    """Income, spending, floating and stalling per replay and team, from the ``resources``
    table (a row per team and second)."""
    end = window_minutes * 60 * GAME_SPEED
    settle = SETTLE_SECONDS * GAME_SPEED
    rows = (
        resources.lazy()
        .with_columns(pl.col("replay").cast(pl.String))
        .filter(pl.col("frame") <= end)
    )
    income = [
        rows.filter(
            pl.col("frame") > (minute * 60 - INCOME_SECONDS) * GAME_SPEED,
            pl.col("frame") <= minute * 60 * GAME_SPEED,
        )
        .group_by("replay", "team")
        .agg(
            pl.col("metal_income").mean().alias(f"metal_income_{minute}"),
            pl.col("energy_income").mean().alias(f"energy_income_{minute}"),
        )
        for minute in MINUTES
        if minute <= window_minutes
    ]
    full = pl.col("metal") >= FULL * pl.col("metal_storage")
    settled = rows.filter(pl.col("frame") > settle).with_columns(
        (pl.col("metal_income") - pl.col("metal_expense")).clip(0).alias("_left")
    )
    flows = settled.group_by("replay", "team").agg(
        full.mean().alias("metal_float"),
        (pl.col("_left").filter(full).sum() / pl.col("metal_income").sum()).alias("metal_overflow"),
        (pl.col("metal") <= EMPTY * pl.col("metal_storage")).mean().alias("metal_stall"),
        (pl.col("energy") <= EMPTY * pl.col("energy_storage")).mean().alias("energy_stall"),
        (pl.col("metal_expense").sum() / pl.col("metal_income").sum()).alias("spend_ratio"),
    )
    spent = rows.group_by("replay", "team").agg(pl.col("metal_expense").sum().alias("metal_spent"))
    joined = flows.join(spent, on=["replay", "team"], how="full", coalesce=True)
    for part in income:
        joined = joined.join(part, on=["replay", "team"], how="full", coalesce=True)
    return joined.with_columns(pl.col("team").cast(pl.Int32)).collect()


def milestone_scores(
    events: pl.DataFrame, types: pl.DataFrame, games: pl.DataFrame
) -> pl.DataFrame:
    """Seconds to the first factory and to the n-th metal extractor finished, and the
    extractors finished by 5:00, per replay and team (only teams with such a unit)."""
    finished = (
        events.lazy()
        .with_columns(pl.col("replay").cast(pl.String), pl.col("unit_def").cast(pl.String))
        .filter(pl.col("kind").cast(pl.String) == "finished")
        .select("replay", pl.col("team").cast(pl.Int32), "frame", "unit_def")
    )
    factories = (
        types.lazy()
        .filter(pl.col("builder_kind") == FACTORY)
        .select("game", pl.col("unit_def"), pl.lit(True).alias("_factory"))
    )
    first_factory = (
        finished.join(games.lazy().select("replay", "game"), on="replay")
        .join(factories, on=["game", "unit_def"])
        .group_by("replay", "team")
        .agg((pl.col("frame").min() / GAME_SPEED).alias("first_factory"))
    )
    extractors = (
        finished.filter(is_extractor(pl.col("unit_def")))
        .sort("frame")
        .group_by("replay", "team")
        .agg(
            *(
                (pl.col("frame").get(count - 1, null_on_oob=True) / GAME_SPEED).alias(
                    f"mex_{count}"
                )
                for count in MEX_COUNTS
            ),
            (pl.col("frame") <= 5 * 60 * GAME_SPEED).sum().cast(pl.Int32).alias("mexes_at_5"),
        )
    )
    return first_factory.join(
        extractors, on=["replay", "team"], how="full", coalesce=True
    ).collect()


def time_weighted_share(
    steps: pl.DataFrame, part: Sequence[str], whole: Sequence[str], end: int
) -> pl.DataFrame:
    """Per replay and team, the time integral from frame 0 to `end` of the sum of the `part`
    columns of `steps` over that of the `whole` columns. `steps` is a step function: a row
    per frame with a change, the values holding until the next row."""
    return (
        steps.lazy()
        .filter(pl.col("frame") < end)
        .sort("replay", "team", "frame")
        .with_columns(
            (pl.col("frame").shift(-1).over("replay", "team").fill_null(end) - pl.col("frame"))
            .clip(0)
            .alias("_frames")
        )
        .group_by("replay", "team")
        .agg(
            (pl.sum_horizontal(part) * pl.col("_frames")).sum().alias("_part"),
            (pl.sum_horizontal(whole) * pl.col("_frames")).sum().alias("_whole"),
        )
        .select(
            "replay",
            pl.col("team").cast(pl.Int32),
            (pl.col("_part") / pl.col("_whole")).alias("share"),
        )
        .collect()
    )


def idle_scores(
    commands: pl.DataFrame,
    events: pl.DataFrame,
    types: pl.DataFrame,
    games: pl.DataFrame,
    window_minutes: int = WINDOW_MINUTES,
) -> pl.DataFrame:
    """Share of the team's finished build power that was idle in the window, all builders
    (``idle_power``) and all but factories (``idle_power_mobile``)."""
    end = window_minutes * 60 * GAME_SPEED
    events = events.with_columns(pl.col("replay").cast(pl.String))
    lives = builders.unit_lives(events).collect()
    changes = unit_changes(events).collect()
    power = builders.team_build_power(changes, types, games)
    transitions = builders.transitions_of(
        commands, events, builders.builder_unit_ids(lives, types, games)
    )
    idle = builders.idle_build_power(transitions, lives, types, games)
    every = builders.power_columns("team_build_power")
    every_idle = builders.power_columns("idle_build_power")
    mobile = [column for column in every if not column.endswith(f"_{FACTORY}")]
    mobile_idle = [column for column in every_idle if not column.endswith(f"_{FACTORY}")]
    # both step functions on the same frames, so that a ratio of integrals is well defined
    both = power.join(idle, on=["replay", "team", "frame"], how="full", coalesce=True).sort(
        "replay", "team", "frame"
    )
    both = both.with_columns(
        pl.col([*every, *every_idle]).forward_fill().over("replay", "team").fill_null(0)
    )
    total = time_weighted_share(both, every_idle, every, end).rename({"share": "idle_power"})
    total_mobile = time_weighted_share(both, mobile_idle, mobile, end).rename(
        {"share": "idle_power_mobile"}
    )
    return total.join(total_mobile, on=["replay", "team"], how="full", coalesce=True)


def order_scores(commands: pl.DataFrame, window_minutes: int = WINDOW_MINUTES) -> pl.DataFrame:
    """Reclaim and resurrect commands per replay and team in the window."""
    end = window_minutes * 60 * GAME_SPEED
    return (
        commands.lazy()
        .filter(
            pl.col("command").is_in(["RECLAIM", "RESURRECT"]),
            pl.col("frame").is_not_null(),
            pl.col("frame") <= end,
        )
        .group_by("replay", pl.col("team").cast(pl.Int32))
        .agg(pl.len().cast(pl.Int32).alias("reclaim_orders"))
        .collect()
    )


def chunk_scores(
    names: Sequence[str],
    games: pl.DataFrame,
    states: Path,
    source: replay_tables.Source,
    types: pl.DataFrame,
) -> pl.DataFrame:
    """Every score of the teams of the games `names` (one row per replay and team)."""
    stems = [state_stem(states, name) for name in names]
    end = WINDOW_MINUTES * 60 * GAME_SPEED
    resources = (
        state_tables.scan_files(
            [state_tables.table_path(stem, "resources") for stem in stems], "resources"
        )
        .filter(pl.col("frame") <= end)
        .collect()
    )
    events = (
        state_tables.scan_files(
            [state_tables.table_path(stem, "events") for stem in stems], "events"
        )
        .with_columns(pl.col("replay").cast(pl.String))
        .collect()
    )
    chunk_games = games.filter(pl.col("replay").is_in(names))
    commands = builders.command_units(
        source.scan(replay_tables.COMMANDS, names)
        .filter(pl.col("frame").is_null() | (pl.col("frame") <= end))
        .select(builders.COMMAND_COLUMNS),
        source.scan(replay_tables.SELECTIONS, names).filter(
            pl.col("frame").is_null() | (pl.col("frame") <= end)
        ),
    ).collect()
    scores = resource_scores(resources)
    for part in (
        milestone_scores(events, types, chunk_games),
        idle_scores(commands, events, types, chunk_games),
        order_scores(commands),
    ):
        scores = scores.join(part, on=["replay", "team"], how="left")
    return scores.with_columns(pl.col("reclaim_orders").fill_null(0)).select(
        "replay", "team", *SCORES
    )


def opening_apm(minutes_path: Path, replays: Sequence[str]) -> pl.DataFrame:
    """Actions per minute over the whole minutes of the window, per replay and player id:
    ``apm_clicked`` (the player's own commands) and ``apm_all`` (with their widgets'), as
    `reason8.analysis.apm` counts them."""
    return (
        pl.scan_parquet(minutes_path)
        .filter(pl.col("replay").is_in(list(replays)), pl.col("minute") < WINDOW_MINUTES)
        .group_by("replay", pl.col("player_id").cast(pl.Int16))
        .agg(
            (pl.col("clicked").cast(pl.Float64).sum() / pl.len()).alias("apm_clicked"),
            (pl.col("all").cast(pl.Float64).sum() / pl.len()).alias("apm_all"),
        )
        .collect()
    )


def build(
    out_dir: Path,
    *,
    states: Path,
    openings_dir: Path,
    types_path: Path,
    tables: Path | None = None,
    apm_minutes: Path | None = None,
    log=lambda message: print(message, file=sys.stderr),
) -> Path:
    """Compute the scores of every re-simulated game of the opening dataset; write
    ``scores.parquet`` (one row per player-game, with the player's rating, position and
    result) to `out_dir`. With `apm_minutes` (the ``minutes.parquet`` of
    `reason8.analysis.apm`), also the actions per minute of the window (`opening_apm`)."""
    openings_games = pl.read_parquet(
        openings_dir / "games.parquet", columns=["match_id", "replay_file_name", "map", "status"]
    ).with_columns(pl.col("replay_file_name").str.replace(r"\.sdfz$", "").alias("replay"))
    found = game_states(states, openings_games["replay"].to_list())
    games = (
        openings_games.join(found.select("replay", "game", "last_frame"), on="replay")
        .filter(pl.col("last_frame") >= WINDOW_MINUTES * 60 * GAME_SPEED)
        .sort("replay")
    )
    source = replay_tables.open_source(
        tables,
        replays=games["replay"].to_list(),
        tables=(replay_tables.COMMANDS, replay_tables.SELECTIONS, replay_tables.PLAYERS),
        log=log,
    )
    games = games.filter(pl.col("replay").is_in(sorted(source.stored)))
    types = pl.read_parquet(types_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts_dir = out_dir / "parts"
    parts_dir.mkdir(exist_ok=True)
    names = games["replay"].to_list()
    parts = []
    for start in range(0, len(names), GAMES_PER_CHUNK):
        part = parts_dir / f"part-{start // GAMES_PER_CHUNK:04d}.parquet"
        parts.append(part)
        if not part.is_file():
            chunk_scores(
                names[start : start + GAMES_PER_CHUNK], games, states, source, types
            ).write_parquet(part)
        log(f"{min(start + GAMES_PER_CHUNK, len(names))} of {len(names)} games scored")
    players = (
        source.scan(replay_tables.PLAYERS, names)
        .filter(pl.col("role") == "player")
        .select("replay", pl.col("team_id").cast(pl.Int32).alias("team"), "user_id", "player_id")
        .unique(["replay", "team"], keep="first")
        .collect()
    )
    openings = pl.read_parquet(
        openings_dir / "openings.parquet",
        columns=[
            "match_id",
            "player_slot",
            "ally_team",
            "faction",
            "position",
            "role",
            "won",
            "skill",
            "skill_uncertainty",
            "status",
            "split",
        ],
    ).rename({"status": "opening_status"})
    scores = (
        pl.scan_parquet(parts)
        .collect()
        .join(games.select("replay", "match_id", "map", "game"), on="replay")
        .join(players, on=["replay", "team"], how="left")
        .join(
            openings,
            left_on=["match_id", "team"],
            right_on=["match_id", "player_slot"],
            how="inner",
        )
    )
    if apm_minutes is not None and apm_minutes.is_file():
        scores = scores.join(
            opening_apm(apm_minutes, names), on=["replay", "player_id"], how="left"
        )
    path = out_dir / "scores.parquet"
    scores.drop("player_id").write_parquet(path)
    return path


# --- measuring the scores

GROUP = ("map", "position")
BOOTSTRAP = 200
SEED = 0
#: The scores averaged into ``composite``: aspects of the opening that repeat for a player
#: and are nearly independent of each other (docs/research/play-quality.md).
COMPOSITE = ("metal_spent", "mex_3", "first_factory", "idle_power", "reclaim_orders")


def oriented(scores: pl.DataFrame, names: Sequence[str] = SCORES) -> pl.DataFrame:
    """`scores` with every score turned so that more is better (`LOWER_IS_BETTER` negated)."""
    return scores.with_columns(
        (-pl.col(name) if name in LOWER_IS_BETTER else pl.col(name)).alias(name) for name in names
    )


def normalised(
    scores: pl.DataFrame, names: Sequence[str], by: Sequence[str] = GROUP
) -> pl.DataFrame:
    """Each of `names` as its percentile rank among the player-games of the same `by` (map and
    start position), centred on 0 (-0.5 to 0.5); null stays null."""
    return scores.with_columns(
        ((pl.col(name).rank("average").over(by) - 0.5) / pl.col(name).count().over(by) - 0.5).alias(
            name
        )
        for name in names
    )


def with_composite(scores: pl.DataFrame, names: Sequence[str] = COMPOSITE) -> pl.DataFrame:
    """Add ``composite``: the mean of the normalised `names`, normalised again."""
    mean = pl.mean_horizontal(names).alias("composite")
    return normalised(scores.with_columns(mean), ["composite"])


def rank_correlation(x: np.ndarray, y: np.ndarray) -> float:
    from scipy.stats import spearmanr

    keep = ~(np.isnan(x) | np.isnan(y))
    if keep.sum() < 3:
        return float("nan")
    return float(spearmanr(x[keep], y[keep]).statistic)


def cluster_bootstrap(
    clusters: np.ndarray, statistic, resamples: int = BOOTSTRAP, seed: int = SEED
) -> tuple[float, float, float]:
    """`statistic(rows, labels)` on all rows, and the 2.5th and 97.5th percentiles of it
    over `resamples` resamples of the clusters (games or players) with replacement.
    `labels` numbers the clusters of `rows`: a cluster drawn twice is two clusters."""
    rng = np.random.default_rng(seed)
    unique, inverse = np.unique(clusters, return_inverse=True)
    members = np.argsort(inverse, kind="stable")
    starts = np.searchsorted(inverse[members], np.arange(len(unique) + 1))
    point = statistic(np.arange(len(clusters)), inverse)
    values = []
    for _ in range(resamples):
        chosen = rng.integers(0, len(unique), len(unique))
        parts = [members[starts[c] : starts[c + 1]] for c in chosen]
        rows = np.concatenate(parts)
        labels = np.repeat(np.arange(len(parts)), [len(part) for part in parts])
        values.append(statistic(rows, labels))
    low, high = np.nanpercentile(values, [2.5, 97.5])
    return point, float(low), float(high)


def between_share(values: np.ndarray, groups: np.ndarray) -> float:
    """Share of the variance of `values` between the means of `groups` (eta squared)."""
    keep = ~np.isnan(values)
    values, groups = values[keep], groups[keep]
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    means = np.bincount(inverse, values) / counts
    total = ((values - values.mean()) ** 2).sum()
    return float(((means[inverse] - values.mean()) ** 2).sum() / total) if total else float("nan")


def intraclass(values: np.ndarray, players: np.ndarray) -> float:
    """ICC(1) of `values` grouped by `players`: the share of the variance between players,
    from a one-way random-effects analysis of variance (unequal group sizes), over the
    players with at least two values."""
    keep = ~np.isnan(values)
    values, players = values[keep], players[keep]
    _, inverse, counts = np.unique(players, return_inverse=True, return_counts=True)
    repeated = counts[inverse] >= 2
    values, inverse = values[repeated], inverse[repeated]
    _, inverse, counts = np.unique(inverse, return_inverse=True, return_counts=True)
    groups, total = len(counts), len(values)
    if groups < 2:
        return float("nan")
    means = np.bincount(inverse, values) / counts
    grand = values.mean()
    between = (counts * (means - grand) ** 2).sum() / (groups - 1)
    within = ((values - means[inverse]) ** 2).sum() / (total - groups)
    size = (total - (counts**2).sum() / total) / (groups - 1)
    return float((between - within) / (between + (size - 1) * within))


def residual(values: np.ndarray, skill: np.ndarray) -> np.ndarray:
    """`values` less their least-squares line on `skill` (null stays null)."""
    keep = ~(np.isnan(values) | np.isnan(skill))
    slope, intercept = np.polyfit(skill[keep], values[keep], 1)
    return values - (slope * skill + intercept)


def team_differences(scores: pl.DataFrame, names: Sequence[str]) -> pl.DataFrame:
    """Per game, the mean of each of `names` on the lower-numbered ally team less that on
    the other, and whether the lower-numbered team won (``won``)."""
    teams = scores.group_by("match_id", "ally_team").agg(
        *(pl.col(name).mean() for name in names), pl.col("won").first()
    )
    first = teams.sort("ally_team").group_by("match_id", maintain_order=True).first()
    second = teams.sort("ally_team").group_by("match_id", maintain_order=True).last()
    joined = first.join(second, on="match_id", suffix="_other").filter(
        pl.col("ally_team") != pl.col("ally_team_other")
    )
    return joined.select(
        "match_id", *((pl.col(name) - pl.col(f"{name}_other")).alias(name) for name in names), "won"
    ).drop_nulls("won")


def auc(score: np.ndarray, won: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score

    keep = ~np.isnan(score)
    if len(np.unique(won[keep])) < 2:
        return float("nan")
    return float(roc_auc_score(won[keep], score[keep]))


def cross_validated_auc(features: np.ndarray, won: np.ndarray, folds: int = 5) -> float:
    """AUC of a logistic regression on `features`, each game predicted by a model fitted on
    the other folds (null features as 0: no difference)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict

    features = np.nan_to_num(features)
    predicted = cross_val_predict(
        LogisticRegression(), features, won, cv=folds, method="predict_proba"
    )[:, 1]
    return auc(predicted, won)


def leave_one_out_means(scores: pl.DataFrame, names: Sequence[str]) -> pl.DataFrame:
    """Each of `names` replaced by the mean of the same player's other games (null for a
    player with no other game with a value)."""

    def other_games(name: str) -> pl.Expr:
        count = pl.col(name).count().over("user_id") - pl.col(name).is_not_null().cast(pl.Int64)
        total = pl.col(name).sum().over("user_id") - pl.col(name).fill_null(0)
        return pl.when(count > 0).then(total / count).alias(name)

    return scores.with_columns(other_games(name) for name in names)


def measure(scores: pl.DataFrame, names: Sequence[str]) -> list[dict]:
    """For each of `names`, how it relates to the rating, the start position, the player and
    the result (see `report` for the columns)."""
    # the rating as it is, apart from the scores: the rating itself can be one of `names`
    raw = oriented(scores.with_columns(pl.col("skill").alias("_rating")), names)
    norm = normalised(raw, names)
    games = norm["match_id"].to_numpy()
    players = norm["user_id"].to_numpy()
    skill = norm["_rating"].to_numpy().astype(float)
    groups = (norm["map"] + "|" + norm["position"]).to_numpy()
    with_faction = (norm["map"] + "|" + norm["position"] + "|" + norm["faction"]).to_numpy()
    differences = team_differences(norm, [*names, "_rating"])
    won = differences["won"].to_numpy().astype(int)
    differences_games = differences["match_id"].to_numpy()
    skill_difference = differences["_rating"].to_numpy().astype(float)
    elsewhere = team_differences(leave_one_out_means(norm, names), names)
    won_elsewhere = elsewhere["won"].to_numpy().astype(int)
    elsewhere_games = elsewhere["match_id"].to_numpy()
    rows = []
    for name in names:
        values = norm[name].to_numpy().astype(float)
        raw_values = raw[name].rank("average").to_numpy().astype(float)
        difference = differences[name].to_numpy().astype(float)
        other = elsewhere[name].to_numpy().astype(float)
        both = np.column_stack([skill_difference, difference])
        rows.append(
            {
                "score": name,
                "coverage": float(np.mean(~np.isnan(values))),
                "rating_raw": rank_correlation(raw_values, skill),
                "rating": cluster_bootstrap(
                    games,
                    lambda rows, _, values=values: rank_correlation(values[rows], skill[rows]),
                ),
                "position_share": between_share(raw_values, groups),
                "faction_share": between_share(raw_values, with_faction)
                - between_share(raw_values, groups),
                "repeat_raw": intraclass(raw_values, players),
                "repeat": cluster_bootstrap(
                    players,
                    lambda rows, labels, values=values: intraclass(values[rows], labels),
                    resamples=100,
                ),
                "repeat_beyond_rating": intraclass(residual(values, skill), players),
                "win": cluster_bootstrap(
                    differences_games,
                    lambda rows, _, difference=difference: auc(difference[rows], won[rows]),
                ),
                "win_elsewhere": cluster_bootstrap(
                    elsewhere_games,
                    lambda rows, _, other=other: auc(other[rows], won_elsewhere[rows]),
                ),
                "win_with_rating": cross_validated_auc(both, won),
            }
        )
    return rows


def later_ratings(
    matches_dir: Path, scores: pl.DataFrame, game_type: str = "Large Team"
) -> pl.DataFrame:
    """Per player-game of `scores` (``match_id``, ``user_id``): the player's rating right
    after this game (``rating_after``), after their last ranked `game_type` game in the match
    dump (``rating_later``), and how many such games they played after this one
    (``games_later``)."""
    matches = pl.scan_parquet(matches_dir / "matches.parquet").filter(
        pl.col("game_type") == game_type, pl.col("is_ranked")
    )
    users = scores.select("user_id").unique()
    history = (
        pl.scan_parquet(matches_dir / "match_players.parquet")
        .join(users.lazy(), on="user_id", how="semi")
        .join(matches.select("match_id", "start_time"), on="match_id")
        .select("user_id", "match_id", "start_time", "new_skill")
        .collect()
        .sort("user_id", "start_time")
    )
    last = history.group_by("user_id").agg(pl.col("new_skill").last().alias("rating_later"))
    played = scores.select("match_id", "user_id").join(
        history.select(
            "user_id", "match_id", "start_time", pl.col("new_skill").alias("rating_after")
        ),
        on=["match_id", "user_id"],
        how="left",
    )
    after = (
        played.join(history.select("user_id", pl.col("start_time").alias("_later")), on="user_id")
        .filter(pl.col("_later") > pl.col("start_time"))
        .group_by("match_id", "user_id")
        .agg(pl.len().cast(pl.Int32).alias("games_later"))
    )
    return (
        played.select("match_id", "user_id", "rating_after")
        .join(last, on="user_id", how="left")
        .join(after, on=["match_id", "user_id"], how="left")
        .with_columns(pl.col("games_later").fill_null(0))
    )


#: The scores the report adds for comparison: the actions per minute of the window
#: (`opening_apm`) and the rating itself.
REFERENCES = ("apm_clicked", "apm_all", "skill")
#: Games the player has to play after a game for their later rating to count.
LATER_GAMES = 20
#: Uncertainty from which an account counts as new (it starts at 8.33).
NEW_ACCOUNT = 6.0


def later_rows(scores: pl.DataFrame, names: Sequence[str]) -> list[dict]:
    """For each of `names` (normalised), its rank correlation with how the player's rating
    moved after this game, from the rating it gave (``rating_after``, so that this game's
    own result is left out) to the end of the dump (``rating_later``), less what that rating
    predicts of the move (regression to the mean); player-games with at least
    `LATER_GAMES` games after them, all accounts and new ones."""
    kept = scores.filter(pl.col("games_later") >= LATER_GAMES)
    rows = []
    for label, part in (
        ("all accounts", kept),
        (
            f"uncertainty {NEW_ACCOUNT:g} and up",
            kept.filter(pl.col("skill_uncertainty") >= NEW_ACCOUNT),
        ),
    ):
        after = part["rating_after"].to_numpy().astype(float)
        moved = residual(part["rating_later"].to_numpy().astype(float) - after, after)
        players = part["user_id"].to_numpy()
        for name in names:
            values = part[name].to_numpy().astype(float)
            rows.append(
                {
                    "accounts": label,
                    "score": name,
                    "player_games": part.height,
                    "players": part["user_id"].n_unique(),
                    "later": cluster_bootstrap(
                        players,
                        lambda rows, _, values=values, moved=moved: rank_correlation(
                            values[rows], moved[rows]
                        ),
                    ),
                }
            )
    return rows


def account_rows(scores: pl.DataFrame, name: str = "composite") -> list[list]:
    """By the rating's uncertainty: player-games, players, median rating, median of the
    normalised `name` as a percentile, and its rank correlation with the rating."""
    bands = [
        ("below 4", None, 4.0),
        ("4 to 6", 4.0, NEW_ACCOUNT),
        (f"{NEW_ACCOUNT:g} and up", NEW_ACCOUNT, None),
    ]
    rows = []
    for label, low, high in bands:
        part = scores.filter(
            (pl.col("skill_uncertainty") >= low) if low is not None else pl.lit(True),
            (pl.col("skill_uncertainty") < high) if high is not None else pl.lit(True),
        )
        values = part[name].to_numpy().astype(float)
        rating = part["_rating"].to_numpy().astype(float)
        rows.append(
            [
                label,
                part.height,
                part["user_id"].n_unique(),
                f"{part['_rating'].median():.1f}",
                f"{50 + 100 * part[name].median():.0f}",
                f"{rank_correlation(values, rating):.2f}",
            ]
        )
    return rows


def _interval(values: tuple[float, float, float], digits: int = 2) -> str:
    point, low, high = values
    return f"{point:.{digits}f} ({low:.{digits}f} to {high:.{digits}f})"


def report(scores: pl.DataFrame, later: pl.DataFrame | None = None) -> str:
    """The tables of ``docs/research/play-quality.md``."""
    names = [*SCORES, *(name for name in REFERENCES if name in scores.columns)]
    prepared = normalised(
        oriented(scores.with_columns(pl.col("skill").alias("_rating")), SCORES), SCORES
    )
    prepared = with_composite(prepared)
    measured = measure(scores, names) + measure(prepared.drop("_rating"), ["composite"])
    lines = [
        f"{scores['match_id'].n_unique()} games, {scores.height} player-games, "
        f"{scores['user_id'].n_unique()} players "
        f"({scores.group_by('user_id').len().filter(pl.col('len') >= 2).height} with two "
        "games or more).",
        "",
        "### The rating and the start position",
        "",
    ]
    lines += table(
        [
            "score",
            "coverage",
            "rating, raw",
            "rating, normalised (95% CI)",
            "position share",
            "faction share",
        ],
        [
            [
                row["score"],
                f"{row['coverage']:.0%}",
                f"{row['rating_raw']:.2f}",
                _interval(row["rating"]),
                f"{row['position_share']:.2f}",
                f"{row['faction_share']:.3f}",
            ]
            for row in measured
        ],
    )
    lines += ["", "### The same player", ""]
    lines += table(
        ["score", "ICC, raw", "ICC, normalised (95% CI)", "ICC beyond the rating"],
        [
            [
                row["score"],
                f"{row['repeat_raw']:.2f}",
                _interval(row["repeat"]),
                f"{row['repeat_beyond_rating']:.2f}",
            ]
            for row in measured
        ],
    )
    lines += ["", "### The winner", ""]
    lines += table(
        ["score", "AUC, this game (95% CI)", "AUC, other games", "AUC with the rating (CV)"],
        [
            [
                row["score"],
                _interval(row["win"]),
                _interval(row["win_elsewhere"]),
                f"{row['win_with_rating']:.3f}",
            ]
            for row in measured
        ],
    )
    correlated = [name for name in (*SCORES, "apm_clicked") if name in prepared.columns]
    if "apm_clicked" in correlated:
        prepared = normalised(oriented(prepared, ["apm_clicked"]), ["apm_clicked"])
    lines += ["", "### Between the scores (normalised, rank correlation)", ""]
    lines += table(
        ["", *correlated],
        [
            [a, *(f"{prepared.select(pl.corr(a, b)).item():.2f}" for b in correlated)]
            for a in correlated
        ],
    )
    lines += ["", "### New accounts", ""]
    lines += table(
        [
            "uncertainty",
            "player-games",
            "players",
            "median rating",
            "composite, median percentile",
            "composite and rating",
        ],
        account_rows(prepared),
    )
    if later is not None:
        joined = prepared.join(later, on=["match_id", "user_id"], how="left")
        lines += ["", "### Where the rating went afterwards", ""]
        lines += table(
            ["accounts", "score", "player-games", "players", "rank correlation (95% CI)"],
            [
                [
                    row["accounts"],
                    row["score"],
                    row["player_games"],
                    row["players"],
                    _interval(row["later"]),
                ]
                for row in later_rows(joined, ["composite", *COMPOSITE])
            ],
        )
    return "\n".join(lines) + "\n"


# --- the command line


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", type=Path, help="default: <data dir>/state")
    parser.add_argument(
        "--tables", type=Path, help="the replay tables (default: <data dir>/tables)"
    )
    parser.add_argument(
        "--openings",
        type=Path,
        help="the opening dataset (default: <data dir>/datasets/openings_v2)",
    )
    parser.add_argument(
        "--builder-types",
        type=Path,
        help="the builder types of every game version, as the decision table keeps them "
        "(default: <data dir>/datasets/context_v2/builder_types.parquet)",
    )
    parser.add_argument(
        "--apm", type=Path, help="actions per minute (default: <data dir>/apm/minutes.parquet)"
    )
    parser.add_argument("--matches", type=Path, help="the match dump (default: <data dir>/matches)")
    parser.add_argument("--out", type=Path, help="default: <data dir>/play-quality")
    parser.add_argument("--report", action="store_true", help="print the tables of a run")


def run(args: argparse.Namespace) -> int:
    out_dir = args.out or data_dir() / "play-quality"
    if args.report:
        later_path = out_dir / "later.parquet"
        print(
            report(
                pl.read_parquet(out_dir / "scores.parquet"),
                pl.read_parquet(later_path) if later_path.is_file() else None,
            )
        )
        return 0
    path = build(
        out_dir,
        states=args.state_dir or state_dir(),
        openings_dir=args.openings or data_dir() / "datasets" / "openings_v2",
        types_path=args.builder_types
        or data_dir() / "datasets" / "context_v2" / "builder_types.parquet",
        tables=args.tables,
        apm_minutes=args.apm or data_dir() / "apm" / "minutes.parquet",
    )
    scores = pl.read_parquet(path)
    later_ratings(args.matches or data_dir() / "matches", scores).write_parquet(
        out_dir / "later.parquet"
    )
    print(json.dumps({"scores": str(path), "rows": scores.height}))
    return 0
