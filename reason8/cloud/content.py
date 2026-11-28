"""Keep the engines, game versions and maps of a data dir in the bucket for the cloud workers.

    uv run reason8 cloud content --data-dir data/bar

A new instance has none of what a headless run needs, and fetching it from BAR's servers took
the first games of a trial 20 minutes (`docs/reference/cloud.md`). This packs the parts of a
content dir that `reason8 headless setup` fills (engines, game versions, maps and its index)
into one archive in the bucket. A worker unpacks it before its first game and then fetches only
what the archive does not have, so the archive never has to be complete or current; run the
command again after new engines or game versions were fetched to add them.

The archive is not compressed: the game files and maps already are.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tarfile
import tempfile
from pathlib import Path

from reason8.cloud.messages import CLOUD_AREA
from reason8.data import storage
from reason8.data.storage import Bucket
from reason8.headless.setup import INDEX_NAME

logger = logging.getLogger(__name__)

CONTENT_PATH = f"{CLOUD_AREA}/content/bar.tar"
#: What `reason8 headless setup` writes into a content dir; nothing else is packed.
PARTS = ("engine", "maps", "packages", "pool", "rapid", INDEX_NAME)


def pack(data_dir: Path, archive: Path) -> list[str]:
    """Write the content parts of `data_dir` to `archive`; returns the parts it found."""
    packed = []
    with tarfile.open(archive, "w") as tar:
        for part in PARTS:
            if (data_dir / part).exists():
                tar.add(data_dir / part, arcname=part)
                packed.append(part)
    return packed


def push(bucket: Bucket, data_dir: Path) -> dict:
    with tempfile.TemporaryDirectory(dir=data_dir.parent) as scratch:
        archive = Path(scratch) / "bar.tar"
        packed = pack(data_dir, archive)
        if not packed:
            raise SystemExit(f"{data_dir} has no engines, games or maps (reason8 headless setup)")
        size = archive.stat().st_size
        bucket.upload(archive, CONTENT_PATH)
    return {"archive": CONTENT_PATH, "parts": packed, "bytes": size}


def restore(bucket: Bucket, data_dir: Path) -> bool:
    """Unpack the bucket's archive into `data_dir` when that has no content yet. Returns
    whether it did; without an archive the worker fetches everything itself."""
    if any((data_dir / part).exists() for part in PARTS):
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir.parent) as scratch:
        archive = Path(scratch) / "bar.tar"
        if not bucket.download(CONTENT_PATH, archive):
            return False
        with tarfile.open(archive) as tar:
            tar.extractall(data_dir, filter="data")
    return True


def add_arguments(parser: argparse.ArgumentParser) -> None:
    storage.add_uri_argument(parser)
    parser.add_argument("--data-dir", type=Path, required=True, help="content dir to pack")


def run(args: argparse.Namespace) -> int:
    bucket = storage.configured_bucket(args.s3_uri)
    if bucket is None:
        print(f"no S3 location: pass --s3-uri or set {storage.S3_URI_VARIABLE}", file=sys.stderr)
        return 2
    print(json.dumps(push(bucket, args.data_dir.resolve()), indent=2))
    return 0
