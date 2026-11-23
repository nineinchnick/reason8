"""Move data files from the earlier flat layout into the date partitions.

Usage::

    uv run reason8 storage migrate-layout local                 # list what would move
    uv run reason8 storage migrate-layout local --apply         # move it
    uv run reason8 storage migrate-layout s3                    # list what would be copied
    uv run reason8 storage migrate-layout s3 --apply            # copy it and verify the copies
    uv run reason8 storage migrate-layout s3 --apply --delete-old   # ... then delete the old keys

Replays, parsed replays and state files used to lie directly in their directory
(``replays/<name>.sdfz``); they are now kept in daily partitions (``replays/date=YYYY-MM-DD/
<name>.sdfz``, see `reason8.paths`). This command moves what is still at the top of the
``replays``, ``parsed`` and ``state`` directories (or of the areas named) into the partitions.
Without ``--apply`` it changes nothing and only says what it would do. Running it again does
nothing more, so an interrupted run can be repeated.

``local``
    renames the files of the data directory (``REASON8_DATA_DIR``) into their partitions. A
    file whose partition already holds an identical copy is removed; one whose partition holds
    a different file is left where it is and reported.
``s3``
    copies each flat key of the bucket (``--s3-uri`` or ``REASON8_S3_URI``) to its partitioned
    key inside S3, without downloading it, lists the bucket again and checks that every copy
    has the size of its original. The flat keys are deleted only with ``--delete-old``, and
    only those whose copy was verified. A key whose partitioned key already holds an object of
    another size is left alone and reported.

Bookkeeping files (``manifest.parquet``, ``_index.jsonl``) stay where they are. Stop the
commands that write into the data directory or the bucket (``download``, ``parse``, ``sync``,
``headless batch``) while this runs. The exit code is 1 when anything was left behind.
"""

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from reason8.data import download, storage
from reason8.data.storage import Bucket
from reason8.headless.state import STATE_SUFFIX
from reason8.paths import data_dir, partitioned_name, partitioned_path, unpartitioned_files
from reason8.replays.parse import PARSED_SUFFIX

LOCAL = "local"
BUCKET = "s3"
DEFAULT_JOBS = 16
#: How many files a dry run names before it only counts them.
EXAMPLES = 5

#: The partitioned directories and the pattern of their data files.
PARTITIONED_AREAS = {
    download.REPLAYS_DIRECTORY: "*.sdfz",
    "parsed": "*" + PARSED_SUFFIX,
    "state": "*" + STATE_SUFFIX,
}


@dataclass
class MigrationSummary:
    #: Data files found outside the partitions.
    flat: int = 0
    #: Files moved (local) or copied (S3) into their partition, or that would be.
    moved: int = 0
    bytes: int = 0
    #: Files whose partition already held a copy of the same content (local) or size (S3).
    already_there: int = 0
    #: Flat files removed because their partition holds a copy, or that would be.
    deleted: int = 0
    #: Flat files left behind: a different file in the partition, or a copy that failed.
    left: list[str] = field(default_factory=list)


def migrate_local(
    directory: Path, pattern: str, *, apply: bool = False, log: Callable[[str], None] = print
) -> MigrationSummary:
    """Move the data files at the top of ``directory`` into its date partitions."""
    summary = MigrationSummary()
    for path in unpartitioned_files(directory, pattern) if directory.is_dir() else ():
        summary.flat += 1
        target = partitioned_path(directory, path.name)
        if target.exists():
            if filecmp.cmp(path, target, shallow=False):
                summary.already_there += 1
                summary.deleted += 1
                if apply:
                    path.unlink()
            else:
                summary.left.append(path.name)
                log(f"left {path}: {target} holds a different file")
            continue
        summary.moved += 1
        summary.bytes += path.stat().st_size
        if apply:
            target.parent.mkdir(exist_ok=True)
            path.rename(target)
        elif summary.moved <= EXAMPLES:
            log(f"would move {path} -> {target}")
    return summary


def migrate_bucket(
    bucket: Bucket,
    area_name: str,
    pattern: str,
    *,
    apply: bool = False,
    delete_old: bool = False,
    jobs: int = DEFAULT_JOBS,
    log: Callable[[str], None] = print,
) -> MigrationSummary:
    """Copy the flat keys of an area to their partitioned keys, verify, and maybe delete them."""
    summary = MigrationSummary()
    sizes = bucket.list_files(area_name)
    flat = sorted(
        name
        for name in sizes
        if "/" not in name and not name.startswith(".") and fnmatch.fnmatchcase(name, pattern)
    )
    summary.flat = len(flat)
    to_copy = []
    for name in flat:
        target_size = sizes.get(partitioned_name(name))
        if target_size is None:
            to_copy.append(name)
        elif target_size == sizes[name]:
            summary.already_there += 1
        else:
            summary.left.append(name)
            log(f"left {area_name}/{name}: {partitioned_name(name)} has another size")
    summary.moved = len(to_copy)
    summary.bytes = sum(sizes[name] for name in to_copy)
    left = set(summary.left)

    if not apply:
        for name in to_copy[:EXAMPLES]:
            log(f"would copy {area_name}/{name} -> {area_name}/{partitioned_name(name)}")
        if delete_old:
            summary.deleted = summary.flat - len(left)
        return summary

    def copy(name: str) -> None:
        bucket.copy(f"{area_name}/{name}", f"{area_name}/{partitioned_name(name)}")

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for count, _ in enumerate(pool.map(copy, to_copy), start=1):
            if count % 1000 == 0:
                log(f"{area_name}: {count} of {len(to_copy)} copied")

    copied_sizes = bucket.list_files(area_name)
    verified = []
    for name in flat:
        if name in left:
            continue
        if copied_sizes.get(partitioned_name(name)) == sizes[name]:
            verified.append(name)
        else:
            summary.left.append(name)
            log(f"left {area_name}/{name}: its copy is missing or has another size")
    if delete_old and verified:
        bucket.delete([f"{area_name}/{name}" for name in verified])
        summary.deleted = len(verified)
    return summary


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "where",
        choices=(LOCAL, BUCKET),
        help="local: the data directory; s3: the bucket",
    )
    parser.add_argument(
        "areas",
        nargs="*",
        metavar="AREA",
        help=f"{', '.join(PARTITIONED_AREAS)} (default: all of them)",
    )
    storage.add_uri_argument(parser)
    parser.add_argument(
        "--apply", action="store_true", help="make the changes (default: only list them)"
    )
    parser.add_argument(
        "--delete-old",
        action="store_true",
        help="s3: delete the flat keys whose partitioned copies were verified",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=f"parallel copies in S3 (default {DEFAULT_JOBS})",
    )


def run(args: argparse.Namespace) -> int:
    def log(line: str) -> None:
        print(line, file=sys.stderr)

    unknown_areas = [area_name for area_name in args.areas if area_name not in PARTITIONED_AREAS]
    if unknown_areas:
        log(f"unknown areas {unknown_areas}; choose from {list(PARTITIONED_AREAS)}")
        return 2
    if args.delete_old and args.where != BUCKET:
        log("--delete-old is for s3; locally files are moved, not copied")
        return 2
    bucket = None
    if args.where == BUCKET:
        bucket = storage.configured_bucket(args.s3_uri)
        if bucket is None:
            log(f"no S3 location: pass --s3-uri or set {storage.S3_URI_VARIABLE}")
            return 2
        log(f"{'migrating' if args.apply else 'dry run of'} s3://{bucket.name}/{bucket.prefix}")
    else:
        log(f"{'migrating' if args.apply else 'dry run of'} {data_dir()}")

    complete = True
    for area_name in args.areas or PARTITIONED_AREAS:
        pattern = PARTITIONED_AREAS[area_name]
        if bucket is None:
            summary = migrate_local(data_dir() / area_name, pattern, apply=args.apply, log=log)
            moved, deleted = ("moved", "deleted") if args.apply else ("to move", "to delete")
        else:
            summary = migrate_bucket(
                bucket,
                area_name,
                pattern,
                apply=args.apply,
                delete_old=args.delete_old,
                jobs=args.jobs,
                log=log,
            )
            moved, deleted = ("copied", "deleted") if args.apply else ("to copy", "to delete")
        log(
            f"{area_name}: {summary.flat} outside the partitions: {summary.moved} {moved} "
            f"({summary.bytes / 1e6:.1f} MB), {summary.already_there} already there, "
            f"{summary.deleted} {deleted}, {len(summary.left)} left"
        )
        complete = complete and not summary.left
    return 0 if complete else 1
