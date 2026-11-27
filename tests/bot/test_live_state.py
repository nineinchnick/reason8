"""Tests for reading the live state the opening script logs and comparing it with the export."""

from reason8.bot import check, live_state
from tests.bot.test_check import write_log

LINE = (
    "state at frame 673: wind 13.2594, metal 533.997 of 1100 +2 -20.0029, "
    "energy 559.982 of 1100 +30 -38.0055, standing armcom 1, armlab 1"
)


def test_parse_line():
    parsed = live_state.parse_line(LINE)
    assert parsed == {
        "frame": 673,
        "wind": 13.2594,
        "metal": 533.997,
        "metal_storage": 1100.0,
        "metal_income": 2.0,
        "metal_expense": 20.0029,
        "energy": 559.982,
        "energy_storage": 1100.0,
        "energy_income": 30.0,
        "energy_expense": 38.0055,
        "standing": {"armcom": 1, "armlab": 1},
    }
    assert live_state.parse_line("step 1 armwin: task queued, frame 25") is None
    empty = LINE.replace("standing armcom 1, armlab 1", "standing ")
    assert live_state.parse_line(empty)["standing"] == {}


def records() -> list[dict]:
    return [
        {"t": "header", "unitdefs": {"1": "armcom", "2": "armlab", "3": "armwin"}},
        {"t": "s", "f": 600, "units": [[10, 1, 0, 0, 0, 100, 100], [11, 2, 0, 0, 0, 90, 100]]},
        {"t": "r", "f": 630, "wind": 13.0, "teams": [[0, 560, 1100, 2.0, 20.0, 570, 1100, 30, 38]]},
        {"t": "r", "f": 660, "wind": 13.2, "teams": [[0, 534, 1100, 2.0, 20.0, 560, 1100, 30, 38]]},
        {"t": "r", "f": 690, "wind": 14.0, "teams": [[0, 500, 1100, 2.0, 20.0, 540, 1100, 30, 38]]},
        # a unit of another team, and one still being built, do not stand
        {"t": "s", "f": 750, "units": [[10, 1, 0, 0, 0, 100, 100], [12, 3, 1, 0, 0, 100, 100]]},
    ]


def test_compare_with_the_last_resource_line_before():
    compared = live_state.compare([live_state.parse_line(LINE)], records(), team=0)
    assert compared["lines"] == 1 and compared["compared"] == 1
    differences = compared["median_difference"]
    assert abs(differences["wind"] - 0.0594) < 1e-3
    assert abs(differences["metal"] - 0.003) < 1e-3
    assert differences["energy_storage"] == 0.0
    assert compared["standing_compared"] == 1 and compared["standing_equal"] == 1


def test_compare_without_a_close_resource_line():
    late = live_state.parse_line(LINE.replace("frame 673", "frame 900"))
    compared = live_state.compare([late], records(), team=0)
    assert compared["compared"] == 0 and compared["median_difference"]["wind"] is None
    assert compared["standing_equal"] == 0  # at 750 only the commander stood


def test_infolog_keeps_state_lines_apart(tmp_path):
    log = write_log(
        tmp_path,
        [
            "Skirmish AI <Reason8-0.1>: Load script: /engine/Reason8/0.1/script/hard/main.as",
            "Skirmish AI <Reason8-0.1>: Reason8 opening: team 4: " + LINE,
            "Skirmish AI <Reason8-0.1>: Reason8 opening: team 4: step 1 armwin: task queued, "
            "frame 25",
        ],
    )
    result = check.check_infolog(log, "Reason8")
    assert result["opening_log_lines"] == 1
    assert result["live_state_by_team"][4][0]["frame"] == 673
    assert result["governor_by_team"] == {} and result["errors"] == []
