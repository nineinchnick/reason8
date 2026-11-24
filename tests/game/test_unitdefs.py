"""Tests for reading the game's unit files (no game needed)."""

import pytest

from reason8.game.unitdefs import LuaSyntaxError, UnitDef, build_task, parse_unit_file

SOLAR = """
-- a comment
return {
	armsolar = {
		buildtime = 2600,
		energystorage = 50,
		energyupkeep = -20,
		objectname = "Units/ARMSOLAR.s3o",
		yardmap = "yyoyy yoooy",
		customparams = {
			solar = true,
			unitgroup = 'energy',
		},
		featuredefs = { dead = { metal = 75, }, },
	},
}
"""


def test_parse_unit_file():
    units = parse_unit_file(SOLAR)
    assert list(units) == ["armsolar"]
    solar = units["armsolar"]
    assert solar["energyupkeep"] == -20 and solar["objectname"] == "Units/ARMSOLAR.s3o"
    assert solar["customparams"] == {"solar": True, "unitgroup": "energy"}
    assert solar["featuredefs"]["dead"]["metal"] == 75


def test_parse_lists_and_explicit_keys():
    units = parse_unit_file(
        'return { armlab = { buildoptions = { [1] = "armck", [2] = "armpw" }, '
        "sizes = { 1.5, 2e3, 0x10 }, --[[ block\ncomment ]] canmove = true } }"
    )
    assert units["armlab"]["buildoptions"] == ["armck", "armpw"]
    assert units["armlab"]["sizes"] == [1.5, 2000.0, 16]


def test_parse_rejects_code():
    with pytest.raises(LuaSyntaxError):
        parse_unit_file("return { armx = { health = math.max(1, 2) } }")


def unit(**fields) -> UnitDef:
    return UnitDef("unit", fields)


@pytest.mark.parametrize(
    ("fields", "task"),
    [
        ({"extractsmetal": 0.001}, "mex"),
        ({"buildoptions": ["armck"], "canmove": True, "workertime": 150}, "factory"),
        ({"workertime": 200, "builddistance": 400}, "nano"),
        ({"weapons": [{"def": "laser"}]}, "defence"),
        ({"customparams": {"energyconv_capacity": 70}}, "convert"),
        ({"windgenerator": 25}, "energy"),
        ({"energyupkeep": -20, "energystorage": 50}, "energy"),
        ({"energystorage": 6000}, "store"),
        ({"radardistance": 2100}, "radar"),
        ({"sonardistance": 900}, "sonar"),
        ({"health": 3000}, None),  # a wall
        ({"speed": 50, "buildoptions": ["armsolar"]}, None),  # a constructor
    ],
)
def test_build_task(fields, task):
    assert build_task(unit(**fields)) == task
