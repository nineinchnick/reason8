"""Minimal raw reader for the command packets of a `.sdfz` demo.

sdfz-demo-parser (v5.15.1) drops the numeric command id from its JSON output
whenever it has no name for it, which is the case for every BAR custom command
(factory quota toggle, area mex, set target, ...). It also reads the shared
command id of `AICOMMANDS` packets as *unsigned*, so BUILD orders sent by
widgets come out unnamed. This module walks the demo stream itself and returns
the raw ids, so `reason8.parse` can put them back. Everything else still comes
from sdfz-demo-parser.

Demo layout: https://github.com/beyond-all-reason/RecoilEngine/blob/master/rts/System/LoadSave/demofile.h
"""

from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"spring demofile\0"

PACKET_COMMAND = 11
PACKET_AICOMMAND = 14
PACKET_AICOMMANDS = 15
COMMAND_PACKETS = {PACKET_COMMAND, PACKET_AICOMMAND, PACKET_AICOMMANDS}


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
        raise ValueError("not a spring demo file")
    header_size, script_size, stream_size = (
        struct.unpack_from("<i", data, 20)[0],
        *struct.unpack_from("<ii", data, 16 + 4 + 4 + 256 + 16 + 8),
    )
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
