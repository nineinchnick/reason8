"""Read a Recoil replay (`.sdfz`) directly: its header and its command packets.

The header says which engine, game version and map a replay needs, without running the
engine (``reason8 header REPLAY`` prints it). Player names are in the embedded start script
and are deliberately not printed.

sdfz-demo-parser (v5.15.1) drops the numeric command id from its JSON output whenever it has
no name for it, which is the case for every BAR custom command (factory quota toggle, area
mex, set target, ...). It also reads the shared command id of `AICOMMANDS` packets as
*unsigned*, so BUILD orders sent by widgets come out unnamed. `read_command_packets()` walks
the demo stream itself and returns the raw ids, so `reason8.replays.parse` can put them back.
Everything else still comes from sdfz-demo-parser.

Layout (rts/System/LoadSave/demofile.h in the engine): a gzip stream holding a packed
little-endian DemoFileHeader, then the start script, then the command stream.
https://github.com/beyond-all-reason/RecoilEngine/blob/master/rts/System/LoadSave/demofile.h
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

MAGIC = b"spring demofile\0"
# magic, version, headerSize, versionString, gameID, unixTime, then 12 ints
HEADER = struct.Struct("<16sii256s16sQ12i")
GAME_SPEED = 30  # simulation frames per game second

PACKET_COMMAND = 11
PACKET_AICOMMAND = 14
PACKET_AICOMMANDS = 15
COMMAND_PACKETS = {PACKET_COMMAND, PACKET_AICOMMAND, PACKET_AICOMMANDS}


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


@dataclass(frozen=True)
class RawCommand:
    cmd_id: int
    options: int
    params: tuple[float, ...]


@dataclass(frozen=True)
class RawCommandPacket:
    packet_id: int
    commands: tuple[RawCommand, ...]


def _demo_stream(data: bytes) -> memoryview:
    if not data.startswith(MAGIC):
        raise DemoError("not a Recoil demo file (bad magic)")
    fields = HEADER.unpack_from(data)
    header_size, script_size, stream_size = fields[2], fields[6], fields[7]
    start = header_size + script_size
    return memoryview(data)[start : start + stream_size]


def _read_floats(buffer: memoryview, offset: int, count: int) -> tuple[float, ...]:
    return struct.unpack_from(f"<{count}f", buffer, offset)


def _parse_command_packet(packet: memoryview) -> RawCommandPacket:
    packet_id = packet[0]
    if packet_id == PACKET_COMMAND:
        # id u8, size u16, player u8, cmd i32, timeout i32, options u8, nparams u32, floats
        command_id, _timeout, options, param_count = struct.unpack_from("<iiBI", packet, 4)
        commands = (RawCommand(command_id, options, _read_floats(packet, 17, param_count)),)
    elif packet_id == PACKET_AICOMMAND:
        # id u8, size u16, player u8, ai u8, team u8, unit i16, cmd i32, timeout i32,
        # options u8, nparams u32, floats
        command_id, _timeout, options, param_count = struct.unpack_from("<iiBI", packet, 8)
        commands = (RawCommand(command_id, options, _read_floats(packet, 21, param_count)),)
    elif packet_id == PACKET_AICOMMANDS:
        # id u8, size u16, player u8, ai u8, pairwise u8, refCmdId i32, refOpts u8,
        # refSize u16, unitCount u16, unitIds u16*n, cmdCount u16, then per command:
        # [id i32 if refCmdId == 0] [opts u8 if refOpts == 0xFF] [size u16 if 0xFFFF] floats
        shared_command_id, shared_options, shared_param_count, unit_count = struct.unpack_from(
            "<iBHH", packet, 6
        )
        offset = 15 + 2 * unit_count
        (command_count,) = struct.unpack_from("<H", packet, offset)
        offset += 2
        command_list = []
        for _ in range(command_count):
            command_id = shared_command_id
            if shared_command_id == 0:
                (command_id,) = struct.unpack_from("<i", packet, offset)
                offset += 4
            options = shared_options
            if shared_options == 0xFF:
                options = packet[offset]
                offset += 1
            param_count = shared_param_count
            if shared_param_count == 0xFFFF:
                (param_count,) = struct.unpack_from("<H", packet, offset)
                offset += 2
            command_list.append(
                RawCommand(command_id, options, _read_floats(packet, offset, param_count))
            )
            offset += 4 * param_count
        commands = tuple(command_list)
    else:
        raise ValueError(f"not a command packet: {packet_id}")
    return RawCommandPacket(packet_id, commands)


def read_command_packets(data: bytes) -> list[RawCommandPacket]:
    """Return every COMMAND/AICOMMAND/AICOMMANDS packet of an uncompressed demo, in order."""
    stream = _demo_stream(data)
    packets: list[RawCommandPacket] = []
    offset = 0
    end = len(stream)
    while offset + 8 <= end:
        (length,) = struct.unpack_from("<I", stream, offset + 4)
        packet = stream[offset + 8 : offset + 8 + length]
        offset += 8 + length
        if length and packet[0] in COMMAND_PACKETS:
            packets.append(_parse_command_packet(packet))
    return packets


def read_command_packets_file(path: str | Path) -> list[RawCommandPacket]:
    with gzip.open(path, "rb") as file:
        return read_command_packets(file.read())


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("replay", type=Path, help="a replay file (.sdfz)")


def run(args: argparse.Namespace) -> int:
    info = asdict(read_header(args.replay))
    del info["script"]  # holds player names
    print(json.dumps(info, indent=1))
    return 0
