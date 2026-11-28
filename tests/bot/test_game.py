"""Tests for `reason8 bot game` (no engine needed)."""

import pytest

from reason8.bot.game import ai_options, parse_options, team_game_script, team_positions
from reason8.game.maps import Layout, SpawnPoint

LAYOUT = Layout(
    2,
    2,
    (
        (SpawnPoint("P1", 100, 200, "front"), SpawnPoint("P2", 300, 400, "air")),
        (SpawnPoint("P3", 900, 800, "front"), SpawnPoint("P4", 700, 600, "air")),
    ),
)


def test_team_positions():
    assert team_positions(LAYOUT) == [(0, "P1"), (0, "P2"), (1, "P3"), (1, "P4")]


def test_team_game_script():
    script = team_game_script(
        map_name="Some Map",
        game="Some Game test-1",
        layout=LAYOUT,
        ais=("Reason8", "BARb"),
        sides=("Armada", "Cortex"),
        seed=7,
        frames=900,
    )
    assert "StartPosType=3;" in script and "FixedRNGSeed=7;" in script
    assert "[TEAM3] { Side=Cortex; Handicap=0; AllyTeam=1; TeamLeader=0; StartPosX=700;" in script
    # players are named by AI and position, and BARb gets its version
    assert "Name=Reason8-P2; ShortName=Reason8; Team=1;" in script
    assert "Name=BARb-P4; ShortName=BARb; Version=stable; Team=3;" in script
    assert "debugcommands=900:quitforce;" in script


def test_team_game_script_with_ai_options():
    script = team_game_script(
        map_name="Some Map",
        game="Some Game test-1",
        layout=LAYOUT,
        ais=("Reason8", "BARb"),
        sides=("Armada", "Cortex"),
        seed=7,
        frames=900,
        options={"builder_orders": "model"},
    )
    # the first ally team's AI only
    assert "ShortName=Reason8; Team=1; [OPTIONS] { builder_orders=model; } }" in script
    assert "Version=stable; Team=3; }" in script


def test_ai_options_are_checked():
    with pytest.raises(SystemExit, match="bad AI option"):
        ai_options({"builder_orders": "model; cheating=1"})
    with pytest.raises(SystemExit, match="KEY=VALUE"):
        parse_options(["builder_orders"])
    assert parse_options(["a=b", "c=d=e"]) == {"a": "b", "c": "d=e"}
