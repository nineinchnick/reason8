"""Copy the data directory to and from the private S3 bucket.

Usage::

    export REASON8_S3_URI=s3://<bucket>            # or pass --s3-uri
    uv run reason8 sync push                       # every area to the bucket
    uv run reason8 sync pull replays parsed        # some areas from the bucket
    uv run reason8 sync pull replays --match '2026-11-*' --dry-run

The bucket is the shared copy and the local data directory a working copy (ADR 0016). Each
area is a directory of the data directory with the same name in the bucket:

``replays``
    raw ``.sdfz`` replays and ``manifest.parquet``;
``parsed``
    parsed ``.json.zst`` replays and ``_index.jsonl``;
``matches``
    the cached match dumps (``.parquet``) and other downloaded ``.json``.

A file is copied when the other side doesn't have it or has it with a different size; nothing is
ever deleted on either side. Other files in these directories (``.part`` downloads, leftovers of
earlier formats) are not copied. The bookkeeping files (``manifest.parquet``, ``_index.jsonl``)
are merged instead of copied, so rows written on different machines all survive: manifest rows
by match, the later ``updated_at`` winning; index entries by replay file, the copied side
winning. ``--match`` copies only some data files and leaves the bookkeeping files alone.
``push`` writes only to the bucket and ``pull`` only to the data directory.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from reason8.data import download, storage
from reason8.data.storage import Bucket
from reason8.paths import data_dir
from reason8.replays import parse

PUSH = "push"
PULL = "pull"
DEFAULT_JOBS = 8


@dataclass(frozen=True)
class Area:
    #: Shell patterns of the data files to copy.
    patterns: tuple[str, ...]
    #: Bookkeeping files and how to merge them: ``merge(destination, source)`` returns the
    #: merged contents, or ``None`` when the destination already holds everything.
    merged_files: dict[str, Callable[[bytes, bytes], bytes | None]] = field(default_factory=dict)


AREAS = {
    download.REPLAYS_DIRECTORY: Area(
        ("*.sdfz",), {download.MANIFEST_NAME: download.merge_manifests}
    ),
    "parsed": Area(("*" + parse.PARSED_SUFFIX,), {parse.INDEX_NAME: parse.merge_indexes}),
    "matches": Area(("*.parquet", "*.json")),
}


@dataclass
class SyncSummary:
    files: int = 0
    already_there: int = 0
    copied: int = 0
    bytes: int = 0
    merged: list[str] = field(default_factory=list)


def is_data_file(name: str, area: Area, match: str | None) -> bool:
    return (
        name not in area.merged_files
        and safe_file_name(name)
        and any(fnmatch.fnmatchcase(name, pattern) for pattern in area.patterns)
        and (match is None or fnmatch.fnmatchcase(name, match))
    )


def safe_file_name(name: str) -> bool:
    return bool(name) and Path(name).name == name and not name.startswith(".")


def sync_area(
    bucket: Bucket,
    area_name: str,
    direction: str,
    *,
    data_directory: Path | None = None,
    match: str | None = None,
    jobs: int = DEFAULT_JOBS,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> SyncSummary:
    """Copy one area between the data directory and the bucket in ``direction``."""
    if direction not in (PUSH, PULL):
        raise ValueError(f"direction must be {PUSH!r} or {PULL!r}, not {direction!r}")
    area = AREAS[area_name]
    local_directory = (data_directory or data_dir()) / area_name
    local_sizes = {
        path.name: path.stat().st_size
        for path in (local_directory.iterdir() if local_directory.is_dir() else ())
        if path.is_file()
    }
    bucket_sizes = bucket.list_directory(area_name)
    source_sizes, destination_sizes = (
        (local_sizes, bucket_sizes) if direction == PUSH else (bucket_sizes, local_sizes)
    )
    names = sorted(name for name in source_sizes if is_data_file(name, area, match))
    to_copy = [name for name in names if destination_sizes.get(name) != source_sizes[name]]
    summary = SyncSummary(
        files=len(names),
        already_there=len(names) - len(to_copy),
        copied=len(to_copy),
        bytes=sum(source_sizes[name] for name in to_copy),
    )

    def copy(name: str) -> None:
        relative_path = f"{area_name}/{name}"
        if direction == PUSH:
            bucket.upload(local_directory / name, relative_path)
        elif not bucket.download(relative_path, local_directory / name):
            raise FileNotFoundError(f"s3://{bucket.name}/{bucket.key(relative_path)}")
        log(f"{direction} {relative_path} ({source_sizes[name] / 1e6:.2f} MB)")

    if dry_run:
        for name in to_copy:
            log(f"would {direction} {area_name}/{name} ({source_sizes[name] / 1e6:.2f} MB)")
    else:
        if direction == PULL and to_copy:
            local_directory.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            for _ in pool.map(copy, to_copy):
                pass

    for name, merge in area.merged_files.items() if match is None else ():
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
