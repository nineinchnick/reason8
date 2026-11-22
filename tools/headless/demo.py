#!/usr/bin/env python3
"""Read the header of a Recoil replay (.sdfz) without running the engine.

    python tools/headless/demo.py REPLAY.sdfz

Prints the engine version, game version, map and length as JSON: everything
needed to decide which engine, game and map a replay needs. Player names are
in the embedded start script and are deliberately not printed.

Layout (rts/System/LoadSave/demofile.h in the engine): a gzip stream holding
a packed little-endian DemoFileHeader, then the start script, then the
command stream.
"""

from __future__ import annotations

import gzip
import json
import re
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

MAGIC = b"spring demofile\0"
# magic, version, headerSize, versionString, gameID, unixTime, then 12 ints
HEADER = struct.Struct("<16sii256s16sQ12i")
GAME_SPEED = 30  # simulation frames per game second


class DemoError(ValueError):
    pass


@dataclass(frozen=True)
class DemoHeader:
    engine_version: str
    game_id: str
    unix_time: int
    game_seconds: int
    wallclock_seconds: int
    num_players: int
    num_teams: int
    game: str
    map: str
    script: str

    @property
    def frames(self) -> int:
        return self.game_seconds * GAME_SPEED

    @property
    def engine_tag(self) -> str:
        """The release tag of the engine: "2026.09.03 BAR" -> "2026.09.03"."""
        return self.engine_version.split()[0] if self.engine_version else ""


def script_value(script: str, key: str) -> str:
    """The first `key=value;` in a start script, case-insensitive."""
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.*?);", script, re.I | re.M)
    return match.group(1).strip() if match else ""


def parse_header(raw: bytes) -> DemoHeader:
    if len(raw) < HEADER.size:
        raise DemoError("too short to be a demo file")
    fields = HEADER.unpack_from(raw)
    magic, _version, header_size, version_string, game_id, unix_time = fields[:6]
    script_size, _stream_size, game_time, wallclock_time, num_players = fields[6:11]
    num_teams = fields[13]
    if magic != MAGIC:
        raise DemoError("not a Recoil demo file (bad magic)")
    script = raw[header_size : header_size + script_size].decode("utf-8", "replace")
    return DemoHeader(
        engine_version=version_string.split(b"\0", 1)[0].decode("ascii", "replace"),
        game_id=game_id.hex(),
        unix_time=unix_time,
        game_seconds=game_time,
        wallclock_seconds=wallclock_time,
        num_players=num_players,
        num_teams=num_teams,
        game=script_value(script, "gametype"),
        map=script_value(script, "mapname"),
        script=script,
    )


def read_header(path: str | Path, max_script: int = 4 << 20) -> DemoHeader:
    """Read only the start of the file: the header and the start script."""
    with gzip.open(path, "rb") as file:
        return parse_header(file.read(HEADER.size + max_script))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    info = asdict(read_header(argv[0]))
    del info["script"]  # holds player names
    print(json.dumps(info, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
