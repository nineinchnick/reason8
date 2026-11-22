"""Public BAR match dumps and the selection of training matches.

The dumps are published by https://github.com/beyond-all-reason/data-processing and rebuilt
twice a week. They are cached under ``<data dir>/matches/`` and downloaded only once.

The data directory defaults to ``data/`` at the repository root and can be overridden with the
``REASON8_DATA_DIR`` environment variable (useful in git worktrees that share one cache).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import polars as pl

DUMPS_URL = "https://data-marts.beyondallreason.dev/"
DUMPS = ("matches", "match_players", "players", "player_skill_snapshot")
REPLAY_URL = "https://storage.uk.cloud.ovh.net/v1/AUTH_10286efc0d334efd917d476d7183232e/BAR/demos/"

#: Default maps of the first slice: the three most played Large Team (8v8) maps.
DEFAULT_MAPS = ("Supreme Isthmus v2.1", "All That Glitters v2.2.3", "Rosetta 1.4.4")


def data_dir() -> Path:
    """Root of the local, git-ignored data cache."""
    env = os.environ.get("REASON8_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "data"


def matches_dir() -> Path:
    """Directory holding the cached Parquet dumps."""
    return data_dir() / "matches"


def download_dumps(
    names: Sequence[str] = DUMPS, dest: Path | None = None, force: bool = False
) -> dict[str, Path]:
    """Download the public Parquet dumps (once) and return their local paths."""
    dest = dest or matches_dir()
    dest.mkdir(parents=True, exist_ok=True)
    paths = {}
    with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as client:
        for name in names:
            path = dest / f"{name}.parquet"
            if force or not path.exists():
                tmp = path.with_suffix(".parquet.part")
                with client.stream("GET", f"{DUMPS_URL}{name}.parquet") as r:
                    r.raise_for_status()
                    with tmp.open("wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                tmp.rename(path)
            paths[name] = path
    return paths


def scan_dump(name: str, dest: Path | None = None) -> pl.LazyFrame:
    """Lazily scan one cached dump, e.g. ``scan_dump("matches")``."""
    return pl.scan_parquet((dest or matches_dir()) / f"{name}.parquet")


def replay_url(replay_file_name: str) -> str:
    """Public download URL of a replay (``.sdfz``) file."""
    return REPLAY_URL + quote(replay_file_name)


def lobby_stats(match_players: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Per-match aggregates of ``match_players``.

    Columns: ``match_id``, ``n_players``, ``n_teams``, ``max_team_size``, ``avg_skill``
    (mean of ``old_skill``, i.e. OpenSkill mu before the match), ``min_skill``,
    ``min_left_after`` (seconds; earliest time any player left).
    """
    mp = match_players.lazy()
    team_sizes = mp.group_by("match_id", "team_id").agg(pl.len().alias("team_size"))
    return (
        mp.group_by("match_id")
        .agg(
            pl.len().alias("n_players"),
            pl.col("team_id").n_unique().alias("n_teams"),
            pl.col("old_skill").mean().alias("avg_skill"),
            pl.col("old_skill").min().alias("min_skill"),
            pl.col("left_after").min().alias("min_left_after"),
            pl.col("left_after").null_count().alias("n_left_after_null"),
        )
        .join(
            team_sizes.group_by("match_id").agg(pl.col("team_size").max().alias("max_team_size")),
            on="match_id",
        )
    )


def select_matches(
    matches: pl.LazyFrame | pl.DataFrame,
    match_players: pl.LazyFrame | pl.DataFrame,
    *,
    maps: Sequence[str] | None = DEFAULT_MAPS,
    game_type: str | None = "Large Team",
    ranked: bool | None = True,
    team_size: int | None = 8,
    since: datetime | None = None,
    until: datetime | None = None,
    window: timedelta | None = timedelta(days=182),
    min_avg_skill: float | str | None = "median",
    early_leave_s: int | None = 600,
    min_duration_s: int | None = 600,
    require_replay: bool = True,
) -> pl.DataFrame:
    """Select the matches to learn from and return their ids and replay file names.

    Defaults give the first training slice: ranked 8v8 games on the three most
    played maps (Supreme Isthmus v2.1, All That Glitters v2.2.3, Rosetta 1.4.4) from the last ~6
    months, lobby average skill at or above that map's median, nobody leaving in
    the first 10 minutes, and a replay file available.

    Args:
        matches: the ``matches`` dump (or a subset of it).
        match_players: the ``match_players`` dump (or a subset of it).
        maps: exact map names to keep (map versions differ in layout); ``None`` keeps all.
        game_type: ``matches.game_type`` to keep (``"Large Team"`` is 6v6..8v8); ``None`` keeps all.
        ranked: keep only ranked (``True``) / unranked (``False``) games; ``None`` keeps both.
        team_size: require exactly two full teams of this size (8 -> 8v8, 16 players);
            ``None`` disables the check.
        since: earliest ``start_time`` (inclusive). Defaults to ``until - window``.
        until: latest ``start_time`` (exclusive). Defaults to just after the newest match in
            ``matches``, so the default window moves with the dump. Pass explicit ``since`` and
            ``until`` to make a selection reproducible across dump rebuilds.
        window: length of the time window used when ``since`` is not given.
        min_avg_skill: minimum lobby average ``old_skill`` (OpenSkill mu before the match).
            ``"median"`` uses, per map, the median lobby average of the games passing all other
            filters (skill levels differ between maps);
            a float is used as is; ``None`` disables the filter.
        early_leave_s: drop games in which any player left before this many seconds (players
            leaving during the opening); ``None`` disables the filter.
        min_duration_s: drop games shorter than this (aborted / instantly decided games).
        require_replay: keep only games with a ``replay_file_name``.

    Returns:
        One row per match, sorted by ``start_time``: ``match_id``, ``replay_id``,
        ``replay_file_name``, ``map``, ``start_time``, ``game_duration``, ``engine``,
        ``game_version``, ``n_players``, ``avg_skill``.
    """
    m = matches.lazy()
    if until is None:
        newest = m.select(pl.col("start_time").max()).collect().item()
        until = newest + timedelta(microseconds=1) if newest is not None else datetime.max
    if since is None and window is not None:
        since = until - window

    filters = [pl.col("start_time") < until]
    if since is not None:
        filters.append(pl.col("start_time") >= since)
    if maps is not None:
        filters.append(pl.col("map").is_in(list(maps)))
    if game_type is not None:
        filters.append(pl.col("game_type") == game_type)
    if ranked is not None:
        filters.append(pl.col("is_ranked") == ranked)
    if min_duration_s is not None:
        filters.append(pl.col("game_duration") >= min_duration_s)
    if require_replay:
        filters.append(pl.col("replay_file_name").is_not_null())
    m = m.filter(*filters)

    stats = lobby_stats(match_players.lazy().join(m.select("match_id"), on="match_id"))
    df = m.join(stats, on="match_id")
    if team_size is not None:
        df = df.filter(
            pl.col("n_teams") == 2,
            pl.col("max_team_size") == team_size,
            pl.col("n_players") == 2 * team_size,
        )
    if early_leave_s is not None:
        df = df.filter(pl.col("n_left_after_null") == 0, pl.col("min_left_after") >= early_leave_s)

    df = df.collect()
    if min_avg_skill == "median":
        df = df.filter(pl.col("avg_skill") >= pl.col("avg_skill").median().over("map"))
    elif isinstance(min_avg_skill, str):
        raise ValueError(f"min_avg_skill must be a number, 'median' or None, not {min_avg_skill!r}")
    elif min_avg_skill is not None:
        df = df.filter(pl.col("avg_skill") >= min_avg_skill)

    return df.select(
        "match_id",
        "replay_id",
        "replay_file_name",
        "map",
        "start_time",
        "game_duration",
        "engine",
        "game_version",
        "n_players",
        "avg_skill",
    ).sort("start_time", "match_id")
