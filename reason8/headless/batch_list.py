"""Write the replay list of a batch from a sample, in parts for several machines.

Usage::

    uv run reason8 headless list --out data/workers/context.txt
    uv run reason8 headless list --out data/workers/context.txt --parts 3
    uv run reason8 headless list --out data/workers/context.txt --weights 6,4,3
    uv run reason8 headless batch --data-dir data/bar --out-dir data/state \\
        --jobs 6 --max-frame 18000 --list data/workers/context.1.txt

The games are those of a sample (``--sample``, by default the context sample of
`reason8 context sample`), in its order, without the games that already have a state file in
``--state-dir``, the folder the batch writes to. A game's replay is looked for in its date
partition of ``--replays``; a game whose replay is not there is left out and counted.

With ``--parts N`` the list is cut into N parts of consecutive games, ``<out stem>.1<suffix>``
to ``<out stem>.N<suffix>``; ``--weights 6,4,3`` cuts it in proportion to how many games each
machine plays in the same time. A batch decides which games to skip only when it starts, so
the parts do not overlap: each game is in exactly one, and no two machines play it.

Every file starts with ``#`` lines, which the batch skips: the sample it came from with the
SHA-256 of the file and the seed it was drawn with, the state folder, the part and the time.
Prints one JSON object with the counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from reason8.context.sample import description_path, sample_file
from reason8.headless.state import state_path
from reason8.paths import data_dir, partitioned_path


def replays_to_play(
    sample: pl.DataFrame, replays: Path, states: Path
) -> tuple[list[Path], dict[str, int]]:
    """The replay paths of the sample's games, in its order, without those that have a state
    file in `states`, and the counts of games left out."""
    paths = []
    counts = {"games": sample.height, "with_state": 0, "missing_replay": 0}
    for name in sample["replay_file_name"]:
        path = partitioned_path(replays, name)
        if state_path(states, path).exists():
            counts["with_state"] += 1
        elif not path.is_file():
            counts["missing_replay"] += 1
        else:
            paths.append(path)
    return paths, counts


def split(items: Sequence[Any], weights: Sequence[float]) -> list[list[Any]]:
    """`items` cut into consecutive parts with sizes in proportion to `weights`.

    Every item is in exactly one part; the sizes are rounded by the largest remainder.
    """
    if not weights or any(weight <= 0 for weight in weights):
        raise ValueError(f"weights must be positive, got {list(weights)}")
    total = sum(weights)
    exact = [len(items) * weight / total for weight in weights]
    sizes = [int(size) for size in exact]
    by_remainder = sorted(
        range(len(weights)), key=lambda index: exact[index] - sizes[index], reverse=True
    )
    for index in by_remainder[: len(items) - sum(sizes)]:
        sizes[index] += 1
    parts = []
    start = 0
    for size in sizes:
        parts.append(list(items[start : start + size]))
        start += size
    return parts


def part_path(out: Path, part: int, parts: int) -> Path:
    return out if parts == 1 else out.with_name(f"{out.stem}.{part}{out.suffix}")


def header(sample: Path, states: Path, part: int, parts: int, games: int) -> list[str]:
    description_file = description_path(sample)
    seed = None
    if description_file.exists():
        seed = json.loads(description_file.read_text()).get("seed")
    digest = hashlib.sha256(sample.read_bytes()).hexdigest()
    drawn = f"seed {seed}" if seed is not None else "how it was drawn is not recorded"
    return [
        f"# replays of the sample {sample} (sha256 {digest}, {drawn})",
        f"# without the games that have a state file in {states}",
        f"# part {part} of {parts}: {games} games; written "
        + datetime.now(UTC).isoformat(timespec="seconds"),
    ]


def parse_weights(text: str) -> list[float]:
    try:
        weights = [float(weight) for weight in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected numbers like 6,4,3, got {text!r}") from None
    if any(weight <= 0 for weight in weights):
        raise argparse.ArgumentTypeError(f"weights must be positive, got {text!r}")
    return weights


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sample", type=Path, default=sample_file(), help="the games")
    parser.add_argument(
        "--replays",
        type=Path,
        default=None,
        help="the replays, in date partitions (default: <data dir>/replays)",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="the batch's --out-dir: games with a state file there are left out "
        "(default: <data dir>/state)",
    )
    parser.add_argument("--out", type=Path, required=True, help="the list to write")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--parts", type=int, default=1, help="equal parts, one per machine")
    group.add_argument(
        "--weights", type=parse_weights, help="parts in these proportions, e.g. 6,4,3"
    )


def run(args: argparse.Namespace) -> int:
    replays = args.replays or data_dir() / "replays"
    states = args.state_dir or data_dir() / "state"
    if args.parts < 1:
        raise SystemExit("--parts must be at least 1")
    weights = args.weights or [1.0] * args.parts
    paths, counts = replays_to_play(pl.read_parquet(args.sample), replays, states)
    parts = split(paths, weights)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for index, part in enumerate(parts, start=1):
        target = part_path(args.out, index, len(parts))
        lines = header(args.sample, states, index, len(parts), len(part))
        target.write_text("\n".join([*lines, *(str(path) for path in part)]) + "\n")
        written.append({"file": str(target), "games": len(part)})
    print(json.dumps({**counts, "to_play": len(paths), "parts": written}, indent=2))
    return 0
