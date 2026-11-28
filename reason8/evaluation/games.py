"""Play evaluation games headlessly, many at a time, and measure each team's economy.

Usage::

    # Reason8 against stock BARb, 30 seeds, each played twice with the AIs swapped
    uv run reason8 eval games --data-dir data/bar --game "Beyond All Reason test-32018-ad135b9" \\
        --engine-dir data/bar/engine-variants/reason8 --seeds 30 --jobs 6 \\
        --out data/eval/reason8-vs-barb
    # the A/A test: stock BARb against itself, the same way
    uv run reason8 eval games ... --ai BARb --out data/eval/barb-vs-barb

ADR 0003 judges the bot in the game: its economy at first contact must be at least that of
stock BARb at the same position. A game is two teams of 8 AIs on the map's recommended
positions (`reason8.bot.game`). Every seed is played twice: in game ``a`` the evaluated AI
(`--ai`) is the first ally team, with the first side (Armada), and the opponent
(`--opponent`) the second; in game ``b`` they swap. So at every position and with every
faction each AI plays once per seed, and the two games of a seed compare the AIs on the same
spot with the same faction. BARb seeds its own random numbers from the clock, so the two
games are not otherwise the same; the A/A test measures how much that alone moves the
numbers.

The host spectates with the state export widget (`reason8 headless run --snapshots`): a
snapshot of every team's resources and units every 5 game seconds, and every hit between
the sides. Each team's opening ends at its first contact (`reason8.openings.contact`,
ADR 0012), or with the 8-minute opening window when it has none. At the last snapshot
before that, the team's measures are:

``metal_income``, ``energy_income``
    per second, as the engine reports them;
``built_metal``, ``built_energy``
    the metal and energy cost of the team's finished units (the value of what it has built);
``units``
    how many finished units it has.

One row per team goes to ``<out>/teams.parquet`` (`reason8 eval report` compares them). A
game whose ``result.json`` exists is not played again, so an interrupted run can be repeated.
Each game's folder keeps its start script, engine log, replay and state file, and the
state's Parquet tables (`reason8.headless.tables`).
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from reason8.bot.game import (
    FRAMES_PER_MINUTE,
    parse_options,
    team_game_layout,
    team_game_script,
    team_positions,
)
from reason8.game.unitdefs import UnitDef, game_unit_defs
from reason8.headless import run as headless_run
from reason8.headless import tables
from reason8.headless.state import read_records
from reason8.openings.contact import first_contact, read_fights
from reason8.openings.extract import OPENING_SECONDS

GAMES = ("a", "b")
STATE_NAME = "state.jsonl.gz"
RESULT_NAME = "result.json"
TEAMS_NAME = "teams.parquet"
WINDOW_FRAMES = OPENING_SECONDS * 30
TEAM_SCHEMA = {
    "seed": pl.Int32,
    "game": pl.String,
    "team": pl.Int32,
    "ally_team": pl.Int32,
    "ai": pl.String,
    "faction": pl.String,
    "position": pl.String,
    "contact_frame": pl.Int32,  # empty: no contact in the game
    "measured_frame": pl.Int32,  # the snapshot the measures come from
    "metal_income": pl.Float64,
    "energy_income": pl.Float64,
    "built_metal": pl.Float64,
    "built_energy": pl.Float64,
    "units": pl.Int32,
}


@dataclass(frozen=True)
class GameSpec:
    seed: int
    game: str  # "a" or "b"
    ais: tuple[str, str]  # by ally team
    sides: tuple[str, str]

    @property
    def name(self) -> str:
        return f"{self.seed:03d}-{self.game}"


def game_specs(
    seeds: Sequence[int], ai: str, opponent: str, sides: tuple[str, str]
) -> list[GameSpec]:
    """Two games per seed, the AIs swapped between the ally teams."""
    return [
        GameSpec(seed, game, (ai, opponent) if game == "a" else (opponent, ai), sides)
        for seed in seeds
        for game in GAMES
    ]


def team_measures(
    state_path: Path,
    unit_defs: Mapping[str, UnitDef],
    window_frames: int = WINDOW_FRAMES,
    at_frame: int | None = None,
) -> dict[int, dict]:
    """Per team: its first contact and its economy at the last snapshot before its opening
    ends (first contact, or the opening window), or before `at_frame` for every team."""
    contact = first_contact(read_fights(state_path))
    names: dict[str, str] = {}
    snapshots: list[dict] = []
    for record in read_records(state_path, snapshots=True):
        if record["t"] == "header":
            names = record["unitdefs"]
        elif record["t"] == "s":
            snapshots.append(record)
    measures = {}
    for team, contact_frame in contact.items():
        if at_frame is not None:
            end = at_frame
        elif contact_frame is not None:
            end = min(contact_frame, window_frames)
        else:
            end = window_frames
        before = [snapshot for snapshot in snapshots if snapshot["f"] <= end]
        if not before:
            continue
        snapshot = before[-1]
        resources = next((row for row in snapshot["teams"] if row[0] == team), None)
        if resources is None:
            continue
        built_metal = built_energy = 0.0
        units = 0
        for _, unit_def_id, unit_team, _, _, _, build_percent in snapshot["units"]:
            if unit_team != team or build_percent < 100:
                continue
            unit = unit_defs.get(names.get(str(unit_def_id), ""))
            units += 1
            if unit is not None:
                built_metal += unit.number("metalcost")
                built_energy += unit.number("energycost")
        measures[team] = {
            "contact_frame": contact_frame,
            "measured_frame": snapshot["f"],
            "metal_income": float(resources[3]),
            "energy_income": float(resources[7]),
            "built_metal": built_metal,
            "built_energy": built_energy,
            "units": units,
        }
    return measures


def play_game(
    spec: GameSpec,
    *,
    out_dir: Path,
    map_name: str,
    game: str,
    data_dir: Path,
    engine_dir: Path | None,
    minutes: float,
    timeout: float,
    unit_defs: Mapping[str, UnitDef],
    options: Mapping[str, str] | None = None,
) -> dict:
    """Play one game (unless it was played) and measure its teams. `options` are AI options
    of the evaluated AI, whichever ally team it plays in this game."""
    game_dir = out_dir / spec.name
    result_path = game_dir / RESULT_NAME
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    if game_dir.exists():
        shutil.rmtree(game_dir)
    game_dir.mkdir(parents=True)
    layout = team_game_layout(map_name)
    script = game_dir / "script.txt"
    script.write_text(
        team_game_script(
            map_name=map_name,
            game=game,
            layout=layout,
            ais=spec.ais,
            sides=spec.sides,
            seed=spec.seed,
            frames=round(minutes * FRAMES_PER_MINUTE),
            options=options,
            options_ally_team=0 if spec.game == GAMES[0] else 1,
        ),
        encoding="utf-8",
    )
    state = game_dir / "state.jsonl"
    run_args = argparse.Namespace(
        data_dir=str(data_dir),
        engine_dir=str(engine_dir) if engine_dir else None,
        run_dir=str(game_dir / "run"),
        keep=True,
        speed=100,
        threads=1,
        timeout=timeout,
        widget=[],
        set=[],
        var=[],
        snapshots=True,
        snapshot_seconds=5,
        max_frame=0,
        out=str(state),
        target=str(script),
    )
    played = headless_run.play(run_args)
    result: dict = {"game": spec.name, "seed": spec.seed, "ais": list(spec.ais), "run": played}
    if state.is_file():
        with state.open("rb") as source, gzip.open(game_dir / STATE_NAME, "wb") as target:
            shutil.copyfileobj(source, target)
        state.unlink()
        tables.convert(game_dir / STATE_NAME)
        measures = team_measures(game_dir / STATE_NAME, unit_defs)
        teams = []
        for team, (ally_team, position) in enumerate(team_positions(layout)):
            if team in measures:
                teams.append(
                    {
                        "seed": spec.seed,
                        "game": spec.game,
                        "team": team,
                        "ally_team": ally_team,
                        "ai": spec.ais[ally_team],
                        "faction": spec.sides[ally_team],
                        "position": position,
                        **measures[team],
                    }
                )
        result["teams"] = teams
    shutil.rmtree(game_dir / "run" / "cache", ignore_errors=True)
    ok = played["exit_code"] == 0 and not played["timed_out"] and not played["desyncs"]
    result["ok"] = ok and bool(result.get("teams"))
    result_path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def measure_again(out_dir: Path, unit_defs: Mapping[str, UnitDef], at_frame: int) -> pl.DataFrame:
    """The team rows of every game played into `out_dir`, measured again from the kept state
    files at the same frame for every team."""
    rows = []
    for result_path in sorted(out_dir.glob(f"*/{RESULT_NAME}")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok"):
            continue
        measures = team_measures(result_path.parent / STATE_NAME, unit_defs, at_frame=at_frame)
        for team in result["teams"]:
            if team["team"] in measures:
                rows.append({**team, **measures[team["team"]]})
    return pl.DataFrame(rows, schema=TEAM_SCHEMA)


def collect(out_dir: Path) -> pl.DataFrame:
    """The team rows of every game played into `out_dir`."""
    rows = []
    for result_path in sorted(out_dir.glob(f"*/{RESULT_NAME}")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("ok"):
            rows += result["teams"]
    return pl.DataFrame(rows, schema=TEAM_SCHEMA)


def parse_seeds(text: str) -> list[int]:
    """``30`` (seeds 1 to 30), ``5-12`` or ``1,4,9``."""
    if "," in text:
        return [int(part) for part in text.split(",")]
    if "-" in text:
        first, last = text.split("-")
        return list(range(int(first), int(last) + 1))
    return list(range(1, int(text) + 1))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", required=True, help="content dir (reason8 headless setup)")
    parser.add_argument("--game", required=True, help="installed game version, by name")
    parser.add_argument("--engine-dir", help="engine with the AIs installed (reason8 bot build)")
    parser.add_argument("--map", default="Supreme Isthmus v2.1")
    parser.add_argument("--ai", default="Reason8", help="the AI evaluated")
    parser.add_argument("--opponent", default="BARb", help="the AI it is compared with")
    parser.add_argument("--sides", nargs=2, default=("Armada", "Cortex"))
    parser.add_argument("--seeds", default="30", help="30 (1 to 30), 5-12 or 1,4,9")
    parser.add_argument("--minutes", type=float, default=8.5, help="game time of each game")
    parser.add_argument("--jobs", type=int, default=6, help="games at a time (about 6 GB each)")
    parser.add_argument("--timeout", type=float, default=1800, help="seconds per game")
    parser.add_argument(
        "--ai-option",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="an option of the evaluated AI, e.g. reaction_delays=off (repeatable)",
    )
    parser.add_argument("--out", type=Path, required=True, help="folder of the games")


def run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    engine_dir = Path(args.engine_dir).resolve() if args.engine_dir else None
    unit_defs = game_unit_defs(data_dir, args.game)
    specs = game_specs(parse_seeds(args.seeds), args.ai, args.opponent, tuple(args.sides))
    args.out.mkdir(parents=True, exist_ok=True)
    options = parse_options(args.ai_option)

    def one(spec: GameSpec) -> dict:
        result = play_game(
            spec,
            out_dir=args.out,
            map_name=args.map,
            game=args.game,
            data_dir=data_dir,
            engine_dir=engine_dir,
            minutes=args.minutes,
            timeout=args.timeout,
            unit_defs=unit_defs,
            options=options,
        )
        run_facts = result["run"]
        print(
            f"{spec.name} {'ok' if result['ok'] else 'FAILED'}: "
            f"{run_facts.get('wall_seconds')} s, {run_facts.get('peak_rss_mb')} MB",
            flush=True,
        )
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(one, specs))
    teams = collect(args.out)
    teams.write_parquet(args.out / TEAMS_NAME)
    failed = [result["game"] for result in results if not result["ok"]]
    print(f"{len(results) - len(failed)} of {len(results)} games ok; {teams.height} team rows")
    if failed:
        print("failed: " + " ".join(failed))
    return 1 if failed else 0
