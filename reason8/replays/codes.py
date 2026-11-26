"""The numbers of a replay's packets as names: commands, their options and other actions.

`command_record` turns one command, as the replay holds it, into the record of the parsed
document (see docs/reference/replay-format.md).
"""

from __future__ import annotations

import math
from typing import Any

# BAR custom commands (Beyond-All-Reason modules/customcommands.lua, Nov 2026).
# The engine's own commands are named by the parser.
BAR_CUSTOM_COMMANDS = {
    13921: "FACTORY_GUARD",
    13922: "AREA_GUARD",
    13923: "STOP_PRODUCTION",
    18200: "BLUEPRINT_PLACE",
    18201: "BLUEPRINT_CREATE",
    23000: "QUOTA_BUILD_TOGGLE",
    30100: "AREA_MEX",
    30101: "SELL_UNIT",
    30102: "SHARE_UNIT",
    31200: "CARRIER_SPAWN_ONOFF",
    31210: "MORPH",
    31300: "USER_FIRESTATE",
    32102: "MANUAL_LAUNCH",
    34569: "LAND_AT",
    34571: "PRIORITY",
    34922: "UNIT_SET_TARGET_NO_GROUND",
    34923: "UNIT_SET_TARGET",
    34924: "UNIT_CANCEL_TARGET",
    34925: "UNIT_SET_TARGET_RECTANGLE",
    37382: "WANT_CLOAK",
    37383: "HOUND_WEAPON_TOGGLE",
    37384: "SMART_TOGGLE",
    39812: "RAW_MOVE",
    39954: "AREA_ATTACK_GROUND",
}

# Engine command ids (rts/Sim/Units/CommandAI/Command.h), for nested INSERT commands.
ENGINE_COMMANDS = {
    0: "STOP",
    1: "INSERT",
    2: "REMOVE",
    5: "WAIT",
    6: "TIMEWAIT",
    7: "DEATHWAIT",
    8: "SQUADWAIT",
    9: "GATHERWAIT",
    10: "MOVE",
    15: "PATROL",
    16: "FIGHT",
    20: "ATTACK",
    21: "AREA_ATTACK",
    25: "GUARD",
    35: "GROUPSELECT",
    36: "GROUPADD",
    37: "GROUPCLEAR",
    40: "REPAIR",
    45: "FIRE_STATE",
    50: "MOVE_STATE",
    55: "SETBASE",
    60: "INTERNAL",
    65: "SELFD",
    75: "LOAD_UNITS",
    76: "LOAD_ONTO",
    80: "UNLOAD_UNITS",
    81: "UNLOAD_UNIT",
    85: "ONOFF",
    90: "RECLAIM",
    95: "CLOAK",
    100: "STOCKPILE",
    105: "MANUALFIRE",
    110: "RESTORE",
    115: "REPEAT",
    120: "TRAJECTORY",
    125: "RESURRECT",
    130: "CAPTURE",
    135: "AUTOREPAIRLEVEL",
    145: "IDLEMODE",
    150: "FAILED",
}

# Command option bits (rts/Sim/Units/CommandAI/Command.h).
OPTION_BITS = [
    (4, "meta"),
    (8, "internal"),
    (16, "right"),
    (32, "shift"),
    (64, "ctrl"),
    (128, "alt"),
]

MAPDRAW_ACTIONS = {0: "point", 1: "erase", 2: "line"}
TEAM_ACTIONS = {
    1: "giveaway",
    2: "resign",
    3: "join_team",
    4: "team_died",
    5: "ai_created",
    6: "ai_destroyed",
}
LUAUI_AI_ID = 255  # AICOMMAND(S) with this aiId come from a player's LuaUI widget, not a bot


def command_name(cmd_id: int) -> str:
    if cmd_id < 0:
        return "BUILD"
    return ENGINE_COMMANDS.get(cmd_id) or BAR_CUSTOM_COMMANDS.get(cmd_id) or f"CMD_{cmd_id}"


def option_names(bits: int) -> list[str]:
    return [name for bit, name in OPTION_BITS if bits & bit]


def round_number(value: Any) -> Any:
    """Round floats for compactness; command params are float32 anyway."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if value.is_integer():
            return int(value)
        return round(value, 2)
    return value


def round_numbers(values: Any) -> list[Any]:
    return [round_number(value) for value in values]


def command_record(
    command_id: int, options: int, params: list[float], unitdefs: list[str]
) -> dict[str, Any]:
    record: dict[str, Any] = {"cmd": command_name(command_id), "cmd_id": command_id}
    if command_id < 0:
        unitdef_index = -command_id
        record["unit"] = unitdefs[unitdef_index] if unitdef_index < len(unitdefs) else None
    option_labels = option_names(options)
    if option_labels:
        record["opts"] = option_labels
    if command_id == 1 and len(params) >= 3:  # INSERT: [queuePos, cmdId, options, *params]
        record["pos"] = round_number(params[0])
        record["inner"] = command_record(int(params[1]), int(params[2]), params[3:], unitdefs)
    else:
        record["params"] = round_numbers(params)
    return record
