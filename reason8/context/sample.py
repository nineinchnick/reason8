"""Draw the context sample: the games the decision table is built from.

Usage::

    uv run reason8 context sample                       # -> <data dir>/logs/context-sample.parquet
    uv run reason8 context sample --seed 7 --out data/logs/other-sample.parquet
    uv run reason8 context sample --count "Rosetta 1.4.4=600" --exclude-state data/state

Re-simulating a game costs minutes of an engine (docs/research/state-extraction.md), so the
decision table (`reason8 context build`) is built from a sample of the games of the opening
dataset, not from all of them, and `reason8 headless batch` re-simulates the sample's games.
The rule:

1. the games of the opening dataset (``openings_v2``) whose status is ``ok``;
2. without the games that already have a state file in an ``--exclude-state`` directory, if
   any is given;
3. sorted by match id, so the draw does not depend on the order of the dataset's file;
4. per map, ``--count`` games drawn without replacement with ``--seed`` (by default 1,350
   Supreme Isthmus, 1,350 All That Glitters and 300 Rosetta, `COUNTS`);
5. all of them shuffled with the same seed, so the first games of the sample, which a batch
   plays first, are a sample too.

The games keep the split the dataset gave them. The existing sample was drawn with this rule,
the default counts and seed 48, with ``--exclude-state data/state`` as it was then, when it
held the state of earlier batches. Excluding is off by default.

The output, ``--out`` (default ``<data dir>/logs/context-sample.parquet``):

``context-sample.parquet``
    One row per game: ``match_id``, ``replay_file_name``, ``map`` and ``split``, in the
    order of step 5.
``context-sample.json``
    How it was drawn: the rule, the seed, the counts, the source dataset and the SHA-256 of
    its manifest, the directories excluded and the match ids they excluded, and the counts
    per map and split. With the same dataset and the same excluded games, the same rule and
    seed draw the same sample.

An existing sample is not overwritten without ``--force``: a batch may be playing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from reason8.headless.state import STATE_SUFFIX
from reason8.openings import dataset as openings
from reason8.paths import data_dir, find_files

FORMAT = "reason8.context-sample/1"
#: Games per map: the three maps of the training slice, Rosetta fewer because it has fewer.
COUNTS = {"Supreme Isthmus v2.1": 1350, "All That Glitters v2.2.3": 1350, "Rosetta 1.4.4": 300}
SEED = 48
COLUMNS = ("match_id", "replay_file_name", "map", "split")
RULE = (
    "the ok games of the source dataset, without those with a state file in exclude_state, "
    "sorted by match_id; per map, counts[map] games drawn with seed; then all of them "
    "shuffled with seed"
)


def sample_file() -> Path:
    return data_dir() / "logs" / "context-sample.parquet"


def description_path(sample_path: Path) -> Path:
    """The file that says how a sample was drawn: its name with ``.json``."""
    return sample_path.with_suffix(".json")


def replay_stem(column: str = "replay_file_name") -> pl.Expr:
    return pl.col(column).str.replace(r"\.sdfz$", "")


def state_stems(directories: Iterable[Path]) -> set[str]:
    """The replay names (without ``.sdfz``) that have a state file in any of the directories."""
    return {
        path.name.removesuffix(STATE_SUFFIX)
        for directory in directories
        for path in find_files(directory, "*" + STATE_SUFFIX)
    }


def draw(
    games: pl.DataFrame,
    counts: Mapping[str, int] = COUNTS,
    seed: int = SEED,
    excluded: Collection[str] = (),
) -> pl.DataFrame:
    """The sample of `games` (the opening dataset's ``games.parquet``) by the rule above.

    `excluded` holds replay names without ``.sdfz``.
    """
    pool = (
        games.filter(pl.col("status") == "ok")
        .filter(~replay_stem().is_in(list(excluded)))
        .sort("match_id")
    )
    parts = []
    for map_name, count in counts.items():
        of_map = pool.filter(pl.col("map") == map_name)
        if of_map.height < count:
            raise ValueError(f"{map_name}: {count} games asked for, {of_map.height} to draw from")
        parts.append(of_map.sample(n=count, seed=seed, shuffle=True))
    return pl.concat(parts).sample(fraction=1.0, seed=seed, shuffle=True).select(COLUMNS)


def describe(
    sample: pl.DataFrame,
    *,
    counts: Mapping[str, int],
    seed: int,
    source: Path,
    exclude_state: Iterable[Path],
    excluded_match_ids: Iterable[str],
) -> dict[str, Any]:
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    by_map_and_split = sample.group_by("map", "split").len().sort("map", "split")
    return {
        "format": FORMAT,
        "drawn_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": openings._code_version(),
        "rule": RULE,
        "seed": seed,
        "counts": dict(counts),
        "source": {
            "dataset": str(source),
            "name": manifest.get("name"),
            "built_at": manifest.get("built_at"),
            "manifest_sha256": (
                hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                if manifest_path.exists()
                else None
            ),
        },
        "exclude_state": [str(directory) for directory in exclude_state],
        "excluded_match_ids": sorted(excluded_match_ids),
        "games": sample.height,
        "games_by_map_and_split": [
            {"map": row["map"], "split": row["split"], "games": row["len"]}
            for row in by_map_and_split.iter_rows(named=True)
        ],
    }


def parse_count(text: str) -> tuple[str, int]:
    map_name, separator, count = text.rpartition("=")
    if not separator or not map_name or not count.isdigit():
        raise argparse.ArgumentTypeError(f"expected MAP=N, got {text!r}")
    return map_name, int(count)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source", type=Path, default=openings.dataset_dir(), help="the opening dataset"
    )
    parser.add_argument(
        "--count",
        type=parse_count,
        action="append",
        metavar="MAP=N",
        help="games of a map (repeat for each map; default: "
        + ", ".join(f"{name}={count}" for name, count in COUNTS.items())
        + ")",
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--exclude-state",
        type=Path,
        action="append",
        default=[],
        metavar="DIR",
        help="leave out games with a state file here (repeatable)",
    )
    parser.add_argument("--out", type=Path, default=sample_file())
    parser.add_argument("--force", action="store_true", help="overwrite an existing sample")


def run(args: argparse.Namespace) -> int:
    description_file = description_path(args.out)
    if not args.force and (args.out.exists() or description_file.exists()):
        print(f"{args.out} exists; --force overwrites it", file=sys.stderr)
        return 1
    counts = dict(args.count) if args.count else COUNTS
    games = pl.read_parquet(args.source / "games.parquet")
    excluded = state_stems(args.exclude_state)
    sample = draw(games, counts, args.seed, excluded)
    excluded_match_ids = (
        games.filter(pl.col("status") == "ok")
        .filter(replay_stem().is_in(list(excluded)))["match_id"]
        .to_list()
    )
    description = describe(
        sample,
        counts=counts,
        seed=args.seed,
        source=args.source,
        exclude_state=args.exclude_state,
        excluded_match_ids=excluded_match_ids,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sample.write_parquet(args.out)
    description_file.write_text(json.dumps(description, indent=2) + "\n")
    print(
        json.dumps(
            {
                "sample": str(args.out),
                "games": sample.height,
                "excluded": len(excluded_match_ids),
                "games_by_map_and_split": description["games_by_map_and_split"],
            },
            indent=2,
        )
    )
    return 0
