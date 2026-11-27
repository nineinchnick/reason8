"""The action budget of ADR 0008, and how a run kept to it.

The bot's actions are counted the way a player's are (`reason8.analysis.apm.ActionCounter`):
at most one a frame, and a command counts only if one of its units got no command in the 7
frames before. A skill band allows at most so many actions in any 1, 10 and 60 seconds (fewer
in the first two minutes) and in any 5 minutes (the game average). `ai/native/Budget.h` keeps
the same table for the 30-40 band, the one the bot plays.

`windows_kept` checks a list of action frames against a band; `governor_log` reads what the
command governor of our BARb library logged in a game (``Reason8 governor: team N: ...``).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

FRAMES_PER_SECOND = 30
FRAMES_PER_MINUTE = 60 * FRAMES_PER_SECOND
FIRST_MINUTES_FRAMES = 2 * FRAMES_PER_MINUTE
#: The band the bot plays (ADR 0008).
DEFAULT_BAND = "30-40"


@dataclass(frozen=True)
class Window:
    name: str
    frames: int
    cap: int
    until_frame: int | None = None  # the window applies while it ends before this frame


def band_windows(
    any_second: int, any_10_seconds: int, any_minute: int, first_minutes: int, average: int
) -> tuple[Window, ...]:
    return (
        Window("1 s", FRAMES_PER_SECOND, any_second),
        Window("10 s", 10 * FRAMES_PER_SECOND, any_10_seconds),
        Window("60 s, first 2 min", FRAMES_PER_MINUTE, first_minutes, FIRST_MINUTES_FRAMES),
        Window("60 s", FRAMES_PER_MINUTE, any_minute),
        Window("5 min", 5 * FRAMES_PER_MINUTE, 5 * average),
    )


#: ADR 0008's table: any 1 s, any 10 s, any 60 s, any 60 s in the first 2 minutes, and the
#: game average per minute, kept over any 5 minutes.
BANDS = {
    "below 10": band_windows(9, 35, 50, 25, 25),
    "10-20": band_windows(10, 40, 65, 30, 30),
    "20-30": band_windows(11, 50, 80, 35, 40),
    "30-40": band_windows(11, 50, 90, 40, 50),
    "40 and up": band_windows(11, 50, 100, 50, 55),
}


def most_in_window(frames: Sequence[int], window: Window) -> tuple[int, int | None]:
    """(most actions in any window of its length, the frame that window ends at).

    `frames` are sorted. A window ending at frame f holds the actions in (f - length, f];
    one with `until_frame` counts only windows ending before it.
    """
    most, at = 0, None
    for index, frame in enumerate(frames):
        if window.until_frame is not None and frame >= window.until_frame:
            break
        count = index + 1 - bisect_right(frames, frame - window.frames)
        if count > most:
            most, at = count, frame
    return most, at


def windows_kept(frames: Iterable[int], band: str = DEFAULT_BAND) -> dict:
    """For each window of the band: its cap, the most actions in it, and whether it held."""
    ordered = sorted(frames)
    result = {}
    for window in BANDS[band]:
        most, at = most_in_window(ordered, window)
        result[window.name] = {"cap": window.cap, "most": most, "at_frame": at}
    result["ok"] = all(row["most"] <= row["cap"] for row in result.values())
    return result


TALLY_FIELDS = (
    "seen",
    "sent at once",
    "sent later",
    "deferred",
    "collapsed",
    "dropped",
    "failed",
    "actions",
    "worst delay",
    "held",
)
GOVERNOR_LINE = re.compile(r"Reason8 governor: team (\d+): (.*)")
LIBRARY_LINE = re.compile(r"Reason8 library: team (\d+): (.*)")
MINUTE = re.compile(r"minute (\d+)( \(part\))?: (.*)")
MINUTE_FRAMES = re.compile(r"minute (\d+)(?: \(part\))? action frames:(.*)")
TOTAL = re.compile(r"total to frame (-?\d+): (.*)")
MODE = re.compile(r"mode (\w+), band (\S+)")
BUILT_FOR = re.compile(r"built for engine (\S+), running in engine (\S*)")


def parse_tally(text: str) -> dict[str, int]:
    """``seen 89, sent at once 49, ..., worst delay 58 frames, held 0`` as a dict."""
    tally = {}
    for part in text.split(", "):
        match = re.fullmatch(r"([a-z ]+?) (-?\d+)(?: frames)?", part)
        if match and match.group(1) in TALLY_FIELDS:
            tally[match.group(1).replace(" ", "_")] = int(match.group(2))
    return tally


def new_team() -> dict:
    return {
        "mode": None,
        "band": None,
        "engine_built_for": None,
        "engine_running": None,
        "minutes": [],
        "action_frames": [],
        "total": None,
        "total_frame": None,
    }


def read_line(teams: dict[int, dict], message: str) -> None:
    """Add one log message of the governor or the library (after the AI's prefix)."""
    if match := LIBRARY_LINE.search(message):
        team = teams.setdefault(int(match.group(1)), new_team())
        if built := BUILT_FOR.search(match.group(2)):
            team["engine_built_for"], team["engine_running"] = built.group(1), built.group(2)
        return
    match = GOVERNOR_LINE.search(message)
    if not match:
        return
    team = teams.setdefault(int(match.group(1)), new_team())
    text = match.group(2)
    if mode := MODE.fullmatch(text):
        team["mode"], team["band"] = mode.group(1), mode.group(2)
    elif frames := MINUTE_FRAMES.fullmatch(text):
        team["action_frames"] += [int(frame) for frame in frames.group(2).split()]
    elif minute := MINUTE.fullmatch(text):
        team["minutes"].append({"minute": int(minute.group(1)), **parse_tally(minute.group(3))})
    elif total := TOTAL.fullmatch(text):
        team["total_frame"] = int(total.group(1))
        team["total"] = parse_tally(total.group(2))


def check_team(team: dict) -> dict:
    """Whether one team's governor kept the budget and lost nothing, from its log lines.

    Every command the AI gave is sent (at once or later), replaced by a newer order to the
    same unit while held (``collapsed``), dropped, or still held when the game ended; only a
    dropped command is lost. The actions it logged are checked against the band's windows
    here, independently of the governor's own count.
    """
    result: dict = {
        "mode": team["mode"],
        "engine_built_for": team["engine_built_for"],
        "engine_running": team["engine_running"],
    }
    problems = []
    built_for, running = team["engine_built_for"], team["engine_running"]
    if built_for is not None and not (running or "").startswith(built_for):
        problems.append(f"library built for engine {built_for}, running in {running}")
    total = team["total"]
    if team["mode"] in (None, "off") or total is None:
        if team["mode"] is None:
            problems.append("no governor lines")
        elif team["mode"] != "off" and total is None:
            problems.append("no total line: the AI did not end cleanly")
        result.update({"problems": problems, "ok": not problems})
        return result
    result["total"] = total
    sums = {
        name: sum(minute.get(name, 0) for minute in team["minutes"])
        for name in ("seen", "sent_at_once", "sent_later", "collapsed", "dropped", "actions")
    }
    accounted = (
        total["sent_at_once"] + total["sent_later"] + total["collapsed"] + total["dropped"]
    ) + total["held"]
    if accounted != total["seen"]:
        problems.append(f"{total['seen']} commands seen, {accounted} accounted for")
    if any(sums[name] != total[name] for name in sums):
        problems.append(f"the minutes add up to {sums}, not to the total")
    if total["dropped"]:
        problems.append(f"{total['dropped']} commands dropped")
    if len(team["action_frames"]) != total["actions"]:
        problems.append(
            f"{len(team['action_frames'])} action frames logged for {total['actions']} actions"
        )
    if team["mode"] == "defer":
        kept = windows_kept(team["action_frames"], team["band"] or DEFAULT_BAND)
        result["windows"] = kept
        if not kept["ok"]:
            problems.append("over the budget")
    result.update({"problems": problems, "ok": not problems})
    return result


def governor_log(messages: Iterable[str]) -> dict[int, dict]:
    """Per team, the governor's log and its check, from the AI's log messages."""
    teams: dict[int, dict] = {}
    for message in messages:
        read_line(teams, message)
    return {team: check_team(lines) for team, lines in sorted(teams.items())}
