"""Copy the data directory to and from the private S3 bucket.

Usage::

    export REASON8_S3_URI=s3://<bucket>            # or pass --s3-uri
    uv run reason8 sync push                       # every area to the bucket
    uv run reason8 sync pull replays tables        # some areas from the bucket
    uv run reason8 sync pull replays --since 2026-11-01 --until 2026-11-08 --dry-run
    uv run reason8 sync pull replays --match '*Rosetta*'

The bucket is the shared copy and the local data directory a working copy (ADR 0016), with the
same relative paths on both sides. Each area is a directory of the data directory with the same
name in the bucket:

``replays``
    raw ``.sdfz`` replays in daily partitions (``date=YYYY-MM-DD/``), and ``manifest.parquet``;
``tables``
    the Parquet tables of the parsed replays (``reason8 parse``) in daily partitions, and
    ``_index.jsonl``;
``matches``
    the cached match dumps (``.parquet``) and other downloaded ``.json``.

A file is copied when the other side doesn't have it or has it with a different size; nothing is
ever deleted on either side. Other files in these directories (``.part`` downloads, leftovers of
earlier formats, files in the wrong partition) are not copied, and data files outside the date
partitions (the earlier, flat layout) stop the sync until they have been
moved. The bookkeeping files (``manifest.parquet``, ``_index.jsonl``) are merged instead of
copied, so rows written on different machines all survive: manifest rows by match, the later
``updated_at`` winning; index entries by replay file, the copied side winning. ``--match``
(file names) and ``--since``/``--until`` (partitions; ``--until`` is exclusive) copy only some
data files and leave the bookkeeping files alone; areas without partitions have no files in a
date range. ``push`` writes only to the bucket and ``pull`` only to the data directory.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from reason8.data import download, storage
from reason8.data.storage import Bucket
from reason8.paths import LayoutError, data_dir, partition, partition_in_range
from reason8.replays import parse, tables

PUSH = "push"
PULL = "pull"
DEFAULT_JOBS = 8
LOCAL_SIDE = "data directory"
BUCKET_SIDE = "bucket"


@dataclass(frozen=True)
class Area:
    #: Shell patterns of the data files to copy.
    patterns: tuple[str, ...]
    #: Bookkeeping files and how to merge them: ``merge(destination, source)`` returns the
    #: merged contents, or ``None`` when the destination already holds everything.
    merged_files: dict[str, Callable[[bytes, bytes], bytes | None]] = field(default_factory=dict)
    #: Whether the data files are kept in date partitions (`reason8.paths`) or at the top.
    partitioned: bool = False


AREAS = {
    download.REPLAYS_DIRECTORY: Area(
        ("*.sdfz",), {download.MANIFEST_NAME: download.merge_manifests}, partitioned=True
    ),
    tables.AREA: Area(
        ("*" + tables.SUFFIX,), {tables.INDEX_NAME: parse.merge_indexes}, partitioned=True
    ),
    "matches": Area(("*.parquet", "*.json")),
}


@dataclass
class SyncSummary:
    files: int = 0
    already_there: int = 0
    copied: int = 0
    bytes: int = 0
    merged: list[str] = field(default_factory=list)


def is_data_name(name: str, area: Area) -> bool:
    """Whether a file name is one of the area's data files (wherever it lies)."""
    return (
        name not in area.merged_files
        and safe_file_name(name)
        and any(fnmatch.fnmatchcase(name, pattern) for pattern in area.patterns)
    )


def is_data_file(
    relative_path: str,
    area: Area,
    match: str | None = None,
    since: date | None = None,
    until: date | None = None,
) -> bool:
    """Whether a path relative to the area is a data file in its place, and selected.

    In a partitioned area a data file lies in the partition of its name, and ``since`` and
    ``until`` select partitions; elsewhere it lies at the top and no date range selects it.
    """
    path = PurePosixPath(relative_path)
    name, parent = path.name, str(path.parent)
    if area.partitioned:
        in_place = parent == partition(name) and partition_in_range(parent, since, until)
    else:
        in_place = parent == "." and since is None and until is None
    return (
        in_place
        and is_data_name(name, area)
        and (match is None or fnmatch.fnmatchcase(name, match))
    )


def safe_file_name(name: str) -> bool:
    return bool(name) and Path(name).name == name and not name.startswith(".")


def local_files(directory: Path) -> dict[str, int]:
    """Sizes of the files under ``directory`` at any depth, by path relative to it."""
    if not directory.is_dir():
        return {}
    return {
        path.relative_to(directory).as_posix(): path.stat().st_size
        for path in directory.rglob("*")
        if path.is_file()
    }


def check_layout(area_name: str, area: Area, sizes: dict[str, int], side: str) -> None:
    """Raise `LayoutError` when a partitioned area has data files outside its partitions."""
    if not area.partitioned:
        return
    flat = [path for path in sizes if "/" not in path and is_data_name(path, area)]
    if flat:
        raise LayoutError(
            f"{len(flat)} {area_name} files in the {side} are not in date partitions; move "
            "them into their partitions"
        )


def sync_area(
    bucket: Bucket,
    area_name: str,
    direction: str,
    *,
    data_directory: Path | None = None,
    match: str | None = None,
    since: date | None = None,
    until: date | None = None,
    jobs: int = DEFAULT_JOBS,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> SyncSummary:
    """Copy one area between the data directory and the bucket in ``direction``.

    Raises `LayoutError` when either side still has data files outside the date partitions.
    """
    if direction not in (PUSH, PULL):
        raise ValueError(f"direction must be {PUSH!r} or {PULL!r}, not {direction!r}")
    area = AREAS[area_name]
    local_directory = (data_directory or data_dir()) / area_name
    local_sizes = local_files(local_directory)
    bucket_sizes = bucket.list_files(area_name)
    check_layout(area_name, area, local_sizes, LOCAL_SIDE)
    check_layout(area_name, area, bucket_sizes, BUCKET_SIDE)
    source_sizes, destination_sizes = (
        (local_sizes, bucket_sizes) if direction == PUSH else (bucket_sizes, local_sizes)
    )
    paths = sorted(path for path in source_sizes if is_data_file(path, area, match, since, until))
    to_copy = [path for path in paths if destination_sizes.get(path) != source_sizes[path]]
    summary = SyncSummary(
        files=len(paths),
        already_there=len(paths) - len(to_copy),
        copied=len(to_copy),
        bytes=sum(source_sizes[path] for path in to_copy),
    )

    def copy(path: str) -> None:
        relative_path = f"{area_name}/{path}"
        if direction == PUSH:
            bucket.upload(local_directory / path, relative_path)
        else:
            (local_directory / path).parent.mkdir(parents=True, exist_ok=True)
            if not bucket.download(relative_path, local_directory / path):
                raise FileNotFoundError(f"s3://{bucket.name}/{bucket.key(relative_path)}")
        log(f"{direction} {relative_path} ({source_sizes[path] / 1e6:.2f} MB)")

    if dry_run:
        for path in to_copy:
            log(f"would {direction} {area_name}/{path} ({source_sizes[path] / 1e6:.2f} MB)")
    else:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            for _ in pool.map(copy, to_copy):
                pass

    selected = match is not None or since is not None or until is not None
    for name, merge in area.merged_files.items() if not selected else ():
        if merge_file(bucket, area_name, name, merge, direction, local_directory, dry_run):
            summary.merged.append(name)
            log(f"{'would merge' if dry_run else 'merged'} {area_name}/{name} ({direction})")
    return summary


def merge_file(
    bucket: Bucket,
    area_name: str,
    name: str,
    merge: Callable[[bytes, bytes], bytes | None],
    direction: str,
    local_directory: Path,
    dry_run: bool,
) -> bool:
    """Merge one bookkeeping file into the destination; ``True`` if the destination changed."""
    local_path = local_directory / name
    local_contents = local_path.read_bytes() if local_path.is_file() else None
    bucket_contents = bucket.read(f"{area_name}/{name}")
    source, destination = (
        (local_contents, bucket_contents)
        if direction == PUSH
        else (bucket_contents, local_contents)
    )
    if source is None:
        return False
    merged = source if destination is None else merge(destination, source)
    if merged is None:
        return False
    if dry_run:
        return True
    if direction == PUSH:
        bucket.write(f"{area_name}/{name}", merged)
    else:
        local_directory.mkdir(parents=True, exist_ok=True)
        temporary_path = local_path.with_name(local_path.name + ".tmp")
        temporary_path.write_bytes(merged)
        temporary_path.replace(local_path)
    return True


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "direction",
        choices=(PUSH, PULL),
        help="push: data directory to bucket; pull: bucket to data directory",
    )
    parser.add_argument(
        "areas", nargs="*", metavar="AREA", help=f"{', '.join(AREAS)} (default: all of them)"
    )
    storage.add_uri_argument(parser)
    parser.add_argument(
        "--match", metavar="PATTERN", help="copy only the data files whose names match PATTERN"
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="copy only the date partitions from this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        help="copy only the date partitions before this date (YYYY-MM-DD, exclusive)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=DEFAULT_JOBS,
        help=f"parallel transfers (default {DEFAULT_JOBS})",
    )
    parser.add_argument("--dry-run", action="store_true", help="list what would be copied")


def run(args: argparse.Namespace) -> int:
    unknown_areas = [area_name for area_name in args.areas if area_name not in AREAS]
    if unknown_areas:
        print(f"unknown areas {unknown_areas}; choose from {list(AREAS)}", file=sys.stderr)
        return 2
    bucket = storage.configured_bucket(args.s3_uri)
    if bucket is None:
        print(
            f"no S3 location: pass --s3-uri or set {storage.S3_URI_VARIABLE}",
            file=sys.stderr,
        )
        return 2
    print(
        f"{args.direction}: {data_dir()} and s3://{bucket.name}/{bucket.prefix}",
        file=sys.stderr,
    )
    for area_name in args.areas or AREAS:
        summary = sync_area(
            bucket,
            area_name,
            args.direction,
            match=args.match,
            since=args.since,
            until=args.until,
            jobs=args.jobs,
            dry_run=args.dry_run,
            log=lambda line: print(line, file=sys.stderr),
        )
        merged = f"; merged {', '.join(summary.merged)}" if summary.merged else ""
        print(
            f"{area_name}: {summary.files} files, {summary.already_there} already there, "
            f"{summary.copied} {'to copy' if args.dry_run else 'copied'} "
            f"({summary.bytes / 1e6:.1f} MB){merged}",
            file=sys.stderr,
        )
    return 0
