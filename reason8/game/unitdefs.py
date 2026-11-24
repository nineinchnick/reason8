"""What the game's unit files say about each unit: enough to tell BARb how to build it.

BAR defines every unit in a Lua file under ``units/`` of the game archive, as one table
literal: ``return { armsolar = { energystorage = 50, ..., customparams = {...} } }``. This
module reads those literals (a small parser for Lua table constructors, not a Lua
interpreter) and keeps, per unit, the fields that say what kind of structure it is and what
a factory can make.

BARb's scripts create a build task with one of a few task types (``Task::BuildType`` in
its ``task.as``); `build_task()` maps a structure to the one that builds it, the way
CircuitAI sorts unit definitions: extractors, factories, construction turrets, weapons,
converters, energy, storage, radar and sonar. Anything else (walls, mines, jammers) has no
task a script can create.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reason8.game.package import find_game_package, read_package

UNITS_PREFIX = "units/"


class LuaSyntaxError(ValueError):
    pass


_TOKEN = re.compile(
    r"""
    (?P<space>\s+|--\[(?P<level>=*)\[.*?\](?P=level)\]|--[^\n]*)
    | (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
    | (?P<number>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?))
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<symbol>[{}\[\]=,;])
    """,
    re.VERBOSE | re.DOTALL,
)


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise LuaSyntaxError(f"unexpected {text[position : position + 20]!r}")
        position = match.end()
        kind = match.lastgroup if match.lastgroup != "level" else "space"
        if kind != "space":
            tokens.append((kind, match.group(kind)))
    return tokens


def _unquote(literal: str) -> str:
    body = literal[1:-1]
    return re.sub(r"\\(.)", lambda escape: {"n": "\n", "t": "\t"}.get(escape[1], escape[1]), body)


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokens(text)
        self.position = 0

    def peek(self, offset: int = 0) -> tuple[str, str] | None:
        index = self.position + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def take(self, value: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (value is not None and token[1] != value):
            raise LuaSyntaxError(f"expected {value!r}, got {token!r}")
        self.position += 1
        return token

    def value(self) -> Any:
        kind, text = self.take()
        if kind == "string":
            return _unquote(text)
        if kind == "number":
            return int(text, 0) if re.fullmatch(r"-?(0[xX][0-9a-fA-F]+|\d+)", text) else float(text)
        if kind == "name" and text in ("true", "false", "nil"):
            return {"true": True, "false": False, "nil": None}[text]
        if text == "{":
            return self.table()
        raise LuaSyntaxError(f"not a literal: {text!r}")

    def table(self) -> dict | list:
        entries: dict[Any, Any] = {}
        next_index = 1
        while self.peek() is not None and self.peek()[1] != "}":
            token, after = self.peek(), self.peek(1)
            if token[1] == "[":
                self.take("[")
                key = self.value()
                self.take("]")
                self.take("=")
            elif token[0] == "name" and after is not None and after[1] == "=":
                key = self.take()[1]
                self.take("=")
            else:
                key = next_index
                next_index += 1
            entries[key] = self.value()
            if self.peek() is not None and self.peek()[1] in (",", ";"):
                self.take()
        self.take("}")
        keys = list(entries)
        if keys and all(isinstance(key, int) for key in keys):
            return [entries[key] for key in sorted(keys)]
        return entries


def parse_unit_file(text: str) -> dict[str, dict]:
    """The unit tables of one ``units/**/*.lua`` file, by unit name."""
    start = re.search(r"\breturn\s*\{", text)
    if start is None:
        raise LuaSyntaxError("no 'return {'")
    parser = _Parser(text[start.end() - 1 :])
    parser.take("{")
    units = parser.table()
    if not isinstance(units, dict):
        raise LuaSyntaxError("the file does not return a table of units")
    return {name.lower(): unit for name, unit in units.items() if isinstance(unit, dict)}


@dataclass(frozen=True)
class UnitDef:
    name: str
    fields: Mapping[str, Any] = field(repr=False)

    def number(self, key: str) -> float:
        value = self.fields.get(key)
        return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0

    @property
    def custom(self) -> Mapping[str, Any]:
        custom = self.fields.get("customparams")
        return custom if isinstance(custom, Mapping) else {}

    @property
    def is_static(self) -> bool:
        return self.number("speed") <= 0 and self.number("maxvelocity") <= 0

    @property
    def build_options(self) -> list[str]:
        options = self.fields.get("buildoptions")
        if isinstance(options, Mapping):
            options = list(options.values())
        return [option.lower() for option in options or [] if isinstance(option, str)]

    @property
    def has_weapons(self) -> bool:
        return bool(self.fields.get("weapons") or self.fields.get("weapondefs"))


def build_task(unit: UnitDef) -> str | None:
    """The BARb task type that builds this structure (a key of the bot build's
    ``TASK_TYPES``), or None for a mobile unit or a structure no script task can build."""
    if not unit.is_static:
        return None
    if unit.number("extractsmetal") > 0:
        return "mex"
    if unit.build_options:
        return "factory"
    if unit.number("workertime") > 0:
        return "nano"
    if unit.has_weapons:
        return "defence"
    if unit.custom.get("energyconv_capacity"):
        return "convert"
    produces_energy = (
        unit.number("energymake") > 0
        or unit.number("windgenerator") > 0
        or unit.number("tidalgenerator") > 0
        or unit.number("energyupkeep") < 0
        or unit.custom.get("solar")
    )
    if produces_energy:
        return "energy"
    if unit.number("metalstorage") >= 500 or unit.number("energystorage") >= 500:
        return "store"
    if unit.number("radardistance") > 0:
        return "radar"
    if unit.number("sonardistance") > 0:
        return "sonar"
    return None


def read_unit_defs(files: Mapping[str, bytes]) -> dict[str, UnitDef]:
    """Unit definitions out of the files of the game's ``units/`` folder. A file the parser
    cannot read is skipped: BAR's unit files are plain table literals, but a few build
    their table with code."""
    units: dict[str, UnitDef] = {}
    for path, content in sorted(files.items()):
        if not path.lower().endswith(".lua"):
            continue
        try:
            parsed = parse_unit_file(content.decode("utf-8", errors="replace"))
        except LuaSyntaxError:
            continue
        for name, fields in parsed.items():
            units[name] = UnitDef(name, fields)
    return units


def game_unit_defs(data_dir: Path, game: str) -> dict[str, UnitDef]:
    """The unit definitions of an installed game version."""
    package = find_game_package(data_dir, game)
    return read_unit_defs(read_package(data_dir, package, UNITS_PREFIX))
