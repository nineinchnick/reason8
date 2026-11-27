"""Tests for the action budget of ADR 0008 and the governor's log."""

import re

import pytest

from reason8.bot import budget
from reason8.paths import REPO_ROOT


def test_bands_are_adr_0008s_table():
    adr = (REPO_ROOT / "docs" / "decisions" / "0008-play-under-human-like-limits.md").read_text(
        encoding="utf-8"
    )
    for band, windows in budget.BANDS.items():
        row = re.search(rf"^\| {re.escape(band)} +\|(.*)\|$", adr, re.M)
        assert row, band
        second, ten, minute, first, average = (int(cell) for cell in row.group(1).split("|"))
        caps = {window.name: window.cap for window in windows}
        assert caps == {
            "1 s": second,
            "10 s": ten,
            "60 s, first 2 min": first,
            "60 s": minute,
            "5 min": 5 * average,
        }


def test_c_plus_plus_budget_is_the_default_band():
    header = (REPO_ROOT / "ai" / "native" / "Budget.h").read_text(encoding="utf-8")
    body = header.split("Band30To40()")[1].split("};")[0]
    windows = [
        (int(seconds) * {"FRAMES_PER_SECOND": 30, "FRAMES_PER_MINUTE": 1800}[unit], int(cap))
        for seconds, unit, cap in re.findall(r"\{(\d+) \* (\w+), (\d+),", body)
    ]
    windows += [(1800, int(cap)) for cap in re.findall(r"\{FRAMES_PER_MINUTE, (\d+),", body)]
    expected = {(window.frames, window.cap) for window in budget.BANDS[budget.DEFAULT_BAND]}
    assert set(windows) == expected


def test_most_in_window():
    window = budget.Window("1 s", 30, 2)
    assert budget.most_in_window([0, 10, 30, 45, 60], window) == (2, 10)
    assert budget.most_in_window([], window) == (0, None)
    # a window ending at frame f holds (f - 30, f]: frames 0 and 30 are never together
    assert budget.most_in_window([0, 30, 60], window) == (1, 0)


def test_window_of_the_first_minutes_ends():
    window = budget.Window("60 s, first 2 min", 1800, 1, 3600)
    assert budget.most_in_window([3500, 3599], window)[0] == 2
    assert budget.most_in_window([3500, 3600], window)[0] == 1


def test_windows_kept():
    kept = budget.windows_kept(range(0, 9000, 60))  # 30 a minute
    assert kept["ok"] and kept["5 min"]["most"] == 150
    kept = budget.windows_kept(range(0, 9000, 30))  # one a second: 60 a minute
    assert not kept["ok"]
    assert kept["60 s, first 2 min"]["most"] == 60 and kept["60 s"]["most"] == 60
    assert kept["5 min"]["most"] == 300


def test_parse_tally():
    text = (
        "seen 89, sent at once 49, sent later 35, deferred 40, collapsed 5, dropped 0, "
        "failed 0, actions 31, worst delay 58 frames, held 0"
    )
    assert budget.parse_tally(text) == {
        "seen": 89,
        "sent_at_once": 49,
        "sent_later": 35,
        "deferred": 40,
        "collapsed": 5,
        "dropped": 0,
        "failed": 0,
        "actions": 31,
        "worst_delay": 58,
        "held": 0,
    }


def tally(seen, at_once, later, collapsed, dropped, actions, held, failed=0) -> str:
    return (
        f"seen {seen}, sent at once {at_once}, sent later {later}, deferred {later + held}, "
        f"collapsed {collapsed}, dropped {dropped}, failed {failed}, actions {actions}, "
        f"worst delay 40 frames, held {held}"
    )


def log(minute_1: str, frames_1: str, minute_2: str, frames_2: str, total: str) -> list[str]:
    """Governor lines of team 3 for a game of a bit over a minute."""
    prefix = "Reason8 governor: team 3: "
    return [
        "Reason8 library: team 3: built for engine 2026.09.03, running in engine 2026.09.03",
        prefix + "mode defer, band 30-40",
        prefix + "minute 1: " + minute_1,
        prefix + "minute 1 action frames: " + frames_1,
        prefix + "minute 2 (part): " + minute_2,
        prefix + "minute 2 (part) action frames: " + frames_2,
        prefix + "total to frame 1900: " + total,
        prefix + "commands by topic: 42=12, not governed 0",
    ]


def test_governor_log_of_a_good_game():
    lines = log(
        tally(10, 4, 4, 2, 0, 3, 0),
        "10 100 1000",
        tally(3, 1, 1, 0, 0, 1, 1),
        "1850",
        tally(13, 5, 5, 2, 0, 4, 1),
    )
    checked = budget.governor_log(lines)[3]
    assert checked["ok"], checked["problems"]
    assert checked["mode"] == "defer" and checked["engine_running"] == "2026.09.03"
    assert checked["total"]["held"] == 1
    assert checked["windows"]["5 min"]["most"] == 4


@pytest.mark.parametrize(
    ("total", "frames_2", "problem"),
    [
        (tally(13, 5, 5, 2, 1, 4, 0), "1850", "dropped"),  # one dropped
        (tally(14, 5, 5, 2, 0, 4, 1), "1850", "accounted for"),  # one missing
        (tally(13, 5, 5, 2, 0, 5, 1), "1850", "add up"),  # minutes and total differ
        (tally(13, 5, 5, 2, 0, 4, 1), "1850 1851", "action frames"),
    ],
)
def test_governor_log_problems(total, frames_2, problem):
    lines = log(
        tally(10, 4, 4, 2, 0, 3, 0),
        "10 100 1000",
        tally(3, 1, 1, 0, 0, 1, 1),
        frames_2,
        total,
    )
    checked = budget.governor_log(lines)[3]
    assert not checked["ok"]
    assert any(problem in text for text in checked["problems"]), checked["problems"]


def test_governor_log_over_budget():
    frames = " ".join(str(frame) for frame in range(0, 1800, 30))  # 60 in the first minute
    lines = log(
        tally(60, 60, 0, 0, 0, 60, 0),
        frames,
        tally(0, 0, 0, 0, 0, 0, 0),
        "",
        tally(60, 60, 0, 0, 0, 60, 0),
    )
    checked = budget.governor_log(lines)[3]
    assert "over the budget" in checked["problems"]
    assert checked["windows"]["60 s, first 2 min"]["most"] == 60


def test_governor_log_engine_mismatch():
    lines = [
        "Reason8 library: team 0: built for engine 2026.09.03, running in engine 2026.07.04",
        "Reason8 governor: team 0: mode off, band 30-40",
    ]
    checked = budget.governor_log(lines)[0]
    assert not checked["ok"]
    assert checked["problems"] == ["library built for engine 2026.09.03, running in 2026.07.04"]


def test_governor_log_without_an_end():
    lines = ["Reason8 governor: team 0: mode defer, band 30-40"]
    assert "no total line" in budget.governor_log(lines)[0]["problems"][0]
