"""Run a start script or play back a replay in spring-headless, and measure it.

    uv run reason8 headless run --data-dir data/bar SCRIPT.txt
    uv run reason8 headless run --data-dir data/bar --snapshots REPLAY.sdfz

Each run gets its own write dir (--run-dir, default: a new folder under
<data-dir>/../runs), so runs can go in parallel and never touch the shared
content in --data-dir (engine/, pool/, packages/, maps/), which the engine
reads through SPRING_DATADIR.

For a replay the engine is picked from the replay's header
(<data-dir>/engine/recoil_<version>) and our widget is installed: it sets the
speed, stops the run at game over or at the replay's last frame, and with
--snapshots writes the game state. For a start script, --speed is written
into the script as the MinSpeed/MaxSpeed mod options.

Prints one JSON object: frames simulated, wall time, speed, peak memory, CPU
time and desync warnings. A replay that desyncs was not re-simulated
correctly (wrong engine or game version), so the exit code is then non-zero.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from reason8.replays import sdfz

STATE_WIDGET = Path(__file__).resolve().parent / "widgets" / "reason8_state_export.lua"
STATE_FILE = Path("LuaUI") / "Config" / "reason8_state.jsonl"

# The few settings a headless run needs. Everything else stays at the default.
BASE_SETTINGS = {
    # BAR resolves rapid tags (byar:test) through these hosts
    "RapidTagResolutionOrder": "repos-cdn.beyondallreason.dev;repos.beyondallreason.dev",
    "LogFlushLevel": 0,
    # BAR stops user widgets that use "too much" memory; ours is the only one
    "UserWidgetMemoryLimits": 0,
}


def find_engine(data_dir: Path, version: str | None) -> Path:
    engines = data_dir / "engine"
    if version:
        tag = version.split()[0]
        for name in (f"recoil_{tag}", tag):
            if (engines / name / "spring-headless").is_file():
                return engines / name
        raise SystemExit(
            f"engine {tag} is not installed under {engines} (see `reason8 headless setup`)"
        )
    found = sorted(executable.parent for executable in engines.glob("*/spring-headless"))
    if not found:
        raise SystemExit(f"no engine under {engines} (see `reason8 headless setup`)")
    return found[-1]


def with_speed(script: str, speed: float) -> str:
    """Add MinSpeed/MaxSpeed to the [MODOPTIONS] section of a start script."""
    options = f"MinSpeed={speed:g};\n\t\tMaxSpeed={speed:g};"
    match = re.search(r"\[modoptions\]\s*\{", script, re.I)
    if match:
        return script[: match.end()] + "\n\t\t" + options + script[match.end() :]
    match = re.search(r"\[game\]\s*\{", script, re.I)
    if not match:
        raise SystemExit("start script has no [GAME] section")
    block = f"\n\t[MODOPTIONS]\n\t{{\n\t\t{options}\n\t}}"
    return script[: match.end()] + block + script[match.end() :]


def log_errors(infolog: Path, limit: int = 5) -> list[str]:
    """Lines that explain a failed run (version mismatch, missing content, desync)."""
    if not infolog.is_file():
        return []
    needles = ("Error", "error:", "corrupt", "not found", "Fatal", "terminate")
    noise = ("is deprecated", "missing model", "LoadSoundFile", "texture atlas")
    hits = []
    for line in infolog.read_text(encoding="utf-8", errors="replace").splitlines():
        if any(needle in line for needle in needles) and not any(word in line for word in noise):
            # desync messages name the players: keep the frame and checksums only
            line = re.sub(r"Sync error for .* in frame", "Sync error for <players> in frame", line)
            line = re.sub(r"from demo player (\d+) \(.*?\) does", r"from demo player \1 does", line)
            hits.append(line.strip()[:300])
    return hits[:limit]


DESYNC_PATTERN = re.compile(
    r"\[DESYNC WARNING\].*for frame-number (\d+)|Sync error for .* in frame (\d+)"
)


def desyncs(infolog: Path) -> tuple[int, int | None]:
    """(number of desync messages, first desynced frame).

    While a replay plays, the engine compares its own state checksum with the
    ones the original players sent (every 60 frames) and logs each mismatch.
    None at all means the re-simulation matched the original game.
    """
    if not infolog.is_file():
        return 0, None
    frames = []
    with infolog.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            match = DESYNC_PATTERN.search(line)
            if match:
                frames.append(int(match.group(1) or match.group(2)))
    return len(frames), (min(frames) if frames else None)


def play(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data_dir).resolve()
    target = Path(args.target).resolve()
    is_replay = target.suffix.lower() in (".sdfz", ".sdf")

    header = sdfz.read_header(target) if is_replay else None
    engine_dir = Path(args.engine_dir).resolve() if args.engine_dir else None
    if engine_dir is None:
        engine_dir = find_engine(data_dir, header.engine_version if header else None)

    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        runs = data_dir.parent / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=runs))

    settings = dict(BASE_SETTINGS)
    widgets = [Path(widget).resolve() for widget in args.widget]
    if is_replay:
        # the replay's own script decides the mod options, so the widget sets the speed
        widgets.append(STATE_WIDGET)
        settings["Reason8SnapshotFrames"] = int(args.snapshot_seconds * 30) if args.snapshots else 0
        settings["Reason8Events"] = 1 if args.snapshots else 0
        settings["Reason8Speed"] = int(args.speed)
        max_frame = args.max_frame
        if not max_frame and header.frames:
            max_frame = header.frames + 30
        settings["Reason8MaxFrame"] = int(max_frame or 0)
        # a replay is served on UDP port 8452 by default, so a second playback on the
        # same machine dies with "bind: Address already in use"; 0 = any free port
        settings["HostPortDefault"] = 0
        launch = target
    else:
        script = target.read_text(encoding="utf-8")
        for item in args.var:
            name, _, value = item.partition("=")
            script = script.replace("$" + name, value)
        if args.speed:
            script = with_speed(script, args.speed)
        launch = run_dir / "script.txt"
        launch.write_text(script, encoding="utf-8")
        if args.snapshots:
            # the host spectates; the widget records the game as it is played, and the
            # script's own mod options end it and set its speed
            widgets.append(STATE_WIDGET)
            settings["Reason8SnapshotFrames"] = int(args.snapshot_seconds * 30)
            settings["Reason8Events"] = 1
    if args.threads:
        settings["WorkerThreadCount"] = args.threads
    for item in args.set:
        key, _, value = item.partition("=")
        settings[key] = value

    if widgets:
        widget_dir = run_dir / "LuaUI" / "Widgets"
        widget_dir.mkdir(parents=True, exist_ok=True)
        for widget in widgets:
            shutil.copy2(widget, widget_dir / widget.name)
        config = run_dir / "LuaUI" / "Config" / "BYAR.lua"
        if not config.exists():
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(widget_config(widgets), encoding="utf-8")
    (run_dir / "springsettings.cfg").write_text(
        "".join(f"{key} = {value}\n" for key, value in settings.items()), encoding="utf-8"
    )
    # the archive scan of a big pool takes seconds; reuse the shared cache when there is one
    cache = data_dir / "cache"
    if cache.is_dir() and not (run_dir / "cache").exists():
        shutil.copytree(cache, run_dir / "cache")

    command = [
        str(engine_dir / "spring-headless"),
        "--isolation",
        "--write-dir",
        str(run_dir),
        str(launch),
    ]
    environment = {**os.environ, "SPRING_DATADIR": str(data_dir)}
    start_time = time.monotonic()
    timed_out = False
    with (run_dir / "stdout.txt").open("w") as stdout_file:
        process = subprocess.Popen(
            command,
            cwd=run_dir,
            stdout=stdout_file,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
        peak_threads = 0
        deadline = start_time + args.timeout
        while True:
            try:
                # wait4 gives the child's own CPU time and peak memory
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            except ChildProcessError:
                pid, status, usage = process.pid, 0, None
            if pid:
                break
            try:
                process_status = Path(f"/proc/{process.pid}/status").read_text()
                match = re.search(r"^Threads:\s+(\d+)", process_status, re.M)
                peak_threads = max(peak_threads, int(match.group(1)) if match else 0)
            except OSError:
                pass
            if time.monotonic() > deadline:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                deadline = float("inf")
            time.sleep(0.5)
    wall_seconds = time.monotonic() - start_time
    process.returncode = os.waitstatus_to_exitcode(status)

    infolog = run_dir / "infolog.txt"
    load_seconds, sim_seconds, frames = sim_window(infolog)
    frames = max(frames, 0)
    sim_seconds = max(sim_seconds, 1e-9)
    cpu_seconds = (usage.ru_utime + usage.ru_stime) if usage else 0.0
    desync_count, first_desync = desyncs(infolog)
    result = {
        "target": target.name,
        "kind": "replay" if is_replay else "script",
        "engine": engine_dir.name,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "frames": frames,
        "game_minutes": round(frames / 1800, 2),
        "wall_seconds": round(wall_seconds, 1),
        "load_seconds": round(load_seconds, 1),
        "sim_seconds": round(sim_seconds, 1),
        # game minutes per wall minute: simulation only, and including load + shutdown
        "speed_x": round(frames / 30 / sim_seconds, 1),
        "speed_x_with_load": round(frames / 30 / wall_seconds, 1),
        "cpu_seconds": round(cpu_seconds, 1),
        "cores_used": round(cpu_seconds / wall_seconds, 2),
        "peak_rss_mb": round(usage.ru_maxrss / 1024) if usage else None,
        "peak_threads": peak_threads,
        "desyncs": desync_count,
        "first_desync_frame": first_desync,
        "run_dir": str(run_dir),
    }
    if header:
        result["replay_frames"] = header.frames
        result["replay_engine"] = header.engine_version
        result["replay_game"] = header.game
        result["replay_map"] = header.map
    state = run_dir / STATE_FILE
    if state.is_file():
        result["state_file"] = str(state)
        result["state_bytes"] = state.stat().st_size
    if process.returncode != 0 or frames <= 0:
        result["errors"] = log_errors(infolog) or log_errors(run_dir / "stdout.txt")
    if args.out and state.is_file():
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(state, out_path)
        result["state_file"] = str(out_path.resolve())
    if not args.keep and not args.run_dir:
        shutil.rmtree(run_dir, ignore_errors=True)
        result["run_dir"] = None
    return result


def widget_config(widgets: list[Path]) -> str:
    """BAR's widget handler config (LuaUI/Config/BYAR.lua) with our widgets switched on.

    Game versions before late 2026 do not enable a new user widget by itself,
    even with `enabled = true` in its GetInfo(): it needs an entry in the order list.
    """
    names = []
    for widget in widgets:
        match = re.search(r'\bname\s*=\s*"([^"]+)"', widget.read_text(encoding="utf-8"))
        if match:
            names.append(match.group(1))
    order = "".join(f'\t\t["{name}"] = {i + 1},\n' for i, name in enumerate(names))
    return (
        f"return {{\n\tallowUserWidgets = true,\n\tdata = {{}},\n\torder = {{\n{order}\t}},\n}}\n"
    )


def sim_window(infolog: Path) -> tuple[float, float, int]:
    """(load seconds, simulation seconds, last frame) from the engine log's timestamps.

    Loading ends at the last line logged before frame 1; the simulation ends at
    the first line logged at the last frame (shutdown is not counted).
    """
    pattern = re.compile(r"^\[t=(\d+):(\d+):(\d+\.\d+)\]\[f=(-?\d+)\]")
    load_end = 0.0
    last_frame, last_frame_time = -1, 0.0
    if not infolog.is_file():
        return 0.0, 0.0, -1
    with infolog.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            match = pattern.match(line)
            if not match:
                continue
            seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
            frame = int(match.group(4))
            if frame <= 0 and last_frame <= 0:
                load_end = seconds
            if frame > last_frame:
                last_frame, last_frame_time = frame, seconds
    return load_end, max(last_frame_time - load_end, 0.0), last_frame


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", help="a start script (.txt) or a replay (.sdfz)")
    parser.add_argument(
        "--data-dir", required=True, help="content dir: engine/ pool/ packages/ maps/"
    )
    parser.add_argument(
        "--engine-dir", help="engine folder (default: from the replay, or the newest)"
    )
    parser.add_argument(
        "--run-dir", help="write dir for this run (default: a new temp folder, removed)"
    )
    parser.add_argument("--keep", action="store_true", help="keep the temp run dir (logs, demo)")
    parser.add_argument("--speed", type=float, default=100, help="game speed to ask for (0: leave)")
    parser.add_argument(
        "--threads", type=int, default=0, help="WorkerThreadCount (0: engine default)"
    )
    parser.add_argument(
        "--timeout", type=float, default=3600, help="kill the engine after this many s"
    )
    parser.add_argument(
        "--widget", action="append", default=[], help="extra widget file to install"
    )
    parser.add_argument(
        "--set", action="append", default=[], metavar="KEY=VALUE", help="engine setting"
    )
    parser.add_argument(
        "--var", action="append", default=[], metavar="NAME=VALUE", help="script: $NAME"
    )
    parser.add_argument("--snapshots", action="store_true", help="write state snapshots")
    parser.add_argument(
        "--snapshot-seconds", type=float, default=5, help="game seconds per snapshot"
    )
    parser.add_argument("--max-frame", type=int, default=0, help="replay: stop at this frame")
    parser.add_argument("--out", help="copy the state file here")


def run(args: argparse.Namespace) -> int:
    result = play(args)
    print(json.dumps(result, indent=1))
    ok = result["exit_code"] == 0 and not result["timed_out"] and not result["desyncs"]
    return 0 if ok else 1
