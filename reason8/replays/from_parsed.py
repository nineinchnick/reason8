"""Convert the parsed JSON documents of earlier versions into the tables, once.

Usage::

    uv run reason8 tables --from-parsed data/parsed               # every day
    uv run reason8 tables --from-parsed data/parsed --since 2026-11-01 --jobs 4

Before the tables held everything, `reason8 parse` kept each replay as a zstd JSON document,
``parsed/date=YYYY-MM-DD/<name>.json.zst``, with its index in ``parsed/_index.jsonl``. This
command reads those documents and writes their rows into the tables
(`reason8.replays.tables`), without parsing the ``.sdfz`` files again, and merges the index
into ``tables/_index.jsonl`` (an entry already there wins). A replay that the tables of its
day already hold is skipped, so the command can be stopped and run again; ``--force``
converts every document again.

This is the only code that still reads the JSON documents. Once they are converted, delete
``parsed/`` (locally and in the bucket) and this module, with the ``tables`` command.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from reason8.paths import PARTITION_PREFIX, data_dir, partition_in_range, require_partitioned
from reason8.replays import parse, tables
from reason8.replays.replay import load_replay

PARSED_SUFFIX = ".json.zst"


def default_jobs() -> int:
    """A quarter of the CPU threads: each process holds one document, 0.3 to 2 GB."""
    return max(1, (os.cpu_count() or 1) // 4)


def replay_key(path: Path) -> str:
    return path.name.removesuffix(PARSED_SUFFIX)


def convert_into(path: Path, staging: Path) -> dict[str, Any]:
    """Stage the rows of one parsed document; return its entry, with the error if it fails."""
    entry: dict[str, Any] = {"file": path.name}
    try:
        name = replay_key(path)
        tables.stage(tables.replay_tables(load_replay(path), name), staging, name)
        entry["status"] = "ok"
    except Exception as error:  # one bad file must not stop the day; it is retried next time
        entry.update(status="error", error=f"{type(error).__name__}: {error}"[:500])
    return entry


def parsed_days(
    parsed_dir: Path, since: date | None = None, until: date | None = None
) -> list[Path]:
    """The partitions of the parsed area in the range, oldest first."""
    return sorted(
        path
        for path in parsed_dir.glob(PARTITION_PREFIX + "*")
        if path.is_dir() and partition_in_range(path.name, since, until)
    )


def plan_days(partitions: list[Path], out_dir: Path, force: bool = False) -> list[tables.DayPlan]:
    """The documents of each day that its tables lack (all of them with ``force``)."""
    plans = []
    for parsed_partition in partitions:
        day = parsed_partition.name.removeprefix(PARTITION_PREFIX)
        stored = tables.stored_replays(out_dir / parsed_partition.name, day) or {}
        paths = sorted(parsed_partition.glob("*" + PARSED_SUFFIX))
        tasks = [(path,) for path in paths if force or replay_key(path) not in stored]
        plans.append(tables.DayPlan(day, tasks, stored))
    return plans


def merge_index(parsed_dir: Path, out_dir: Path) -> int:
    """Add the entries of the parsed area's index to that of the tables; return how many."""
    old = parse.read_index(parsed_dir)
    current = parse.read_index(out_dir)
    added = len(set(old) - set(current))
    if added:
        out_dir.mkdir(parents=True, exist_ok=True)
        parse.write_index(out_dir, old | current)
    return added


def convert(
    parsed_dir: Path,
    out_dir: Path,
    *,
    since: date | None = None,
    until: date | None = None,
    jobs: int = 1,
    force: bool = False,
    log: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> list[tables.DayResult]:
    plans = plan_days(parsed_days(parsed_dir, since, until), out_dir, force)
    log(f"{len(plans)} days, {sum(len(plan.tasks) for plan in plans)} documents to convert")
    results = tables.update_days(plans, out_dir, convert_into, jobs=jobs, log=log)
    log(f"{merge_index(parsed_dir, out_dir)} entries of the index added")
    return results


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--from-parsed",
        type=Path,
        required=True,
        metavar="DIR",
        help="the parsed JSON documents of earlier versions (data/parsed)",
    )
    parser.add_argument("--out", type=Path, default=data_dir() / tables.AREA, help="the tables")
    parser.add_argument(
        "--jobs",
        type=int,
        default=default_jobs(),
        help="documents converted in parallel (default: a quarter of the CPU threads)",
    )
    parser.add_argument("--force", action="store_true", help="convert documents already done")
    parser.add_argument("--since", type=date.fromisoformat, help="first day (YYYY-MM-DD)")
    parser.add_argument("--until", type=date.fromisoformat, help="day after the last (YYYY-MM-DD)")


def run(args: argparse.Namespace) -> int:
    require_partitioned(args.from_parsed, "*" + PARSED_SUFFIX)
    results = convert(
        args.from_parsed,
        args.out,
        since=args.since,
        until=args.until,
        jobs=args.jobs,
        force=args.force,
    )
    print(tables.summarize(results), file=sys.stderr)
    return 0
