"""Files of an installed game version, read from its rapid package.

`reason8 headless setup` installs game versions with pr-downloader as rapid packages:
``rapid/<repo>/<tag>/versions.gz`` names each version's package, ``packages/<hash>.sdp``
lists its files, and ``pool/`` holds their content.
"""

from __future__ import annotations

import gzip
from pathlib import Path


def find_game_package(data_dir: Path, game: str) -> Path:
    """The rapid package (.sdp) of an installed game version, looked up by its name."""
    for versions in sorted(data_dir.glob("rapid/*/*/versions.gz")):
        with gzip.open(versions, "rt", encoding="utf-8") as file:
            for line in file:
                # tag, package hash, dependencies, name
                fields = line.rstrip("\n").split(",", 3)
                if len(fields) == 4 and fields[3] == game:
                    package = data_dir / "packages" / f"{fields[1]}.sdp"
                    if package.is_file():
                        return package
    raise SystemExit(
        f"game {game!r} is not installed under {data_dir} (see `reason8 headless setup`)"
    )


def read_package(data_dir: Path, package: Path, prefix: str) -> dict[str, bytes]:
    """Files of a rapid package under `prefix` (compared in lower case), keyed by the rest
    of their path.

    A package is a gzipped list of entries: name length (1 byte), name, MD5 (16),
    CRC32 (4), size (4). The content is in pool/<first two hex digits>/<the rest>.gz.
    """
    index = gzip.decompress(package.read_bytes())
    files: dict[str, bytes] = {}
    offset = 0
    while offset < len(index):
        name_length = index[offset]
        name = index[offset + 1 : offset + 1 + name_length].decode("utf-8")
        digest = index[offset + 1 + name_length : offset + 17 + name_length].hex()
        offset += 1 + name_length + 16 + 4 + 4
        if name.lower().startswith(prefix):
            pooled = data_dir / "pool" / digest[:2] / f"{digest[2:]}.gz"
            files[name[len(prefix) :]] = gzip.decompress(pooled.read_bytes())
    return files
