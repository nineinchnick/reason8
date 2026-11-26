"""Can a classifier tell the bot's openings from human openings at the same positions?

Usage::

    uv run reason8 eval openings data/eval/reason8-spots                   # what was built
    uv run reason8 eval openings data/eval/reason8-spots --compare orders  # what was ordered

ADR 0003's first measure: the openings the Reason8 bot plays are human-like when a
classifier trained on them and on human openings of the same start positions cannot tell
them apart on games it has not seen. An opening is what gets built, in order, until first
contact: the units each team finished, from the state files of the games, with first contact
measured the same way for both (`reason8.openings.contact`, ADR 0012) and at most the
8-minute opening window. The bot's builds come from the games of `reason8 eval games`, the
human ones from the re-simulated games of the dataset's test split (`reason8 headless
batch`, ADR 0010) on the same map, at the positions and with the factions the bot played,
started on their spot. Commanders, which every team starts with, are left out.

``--compare orders`` compares what was ordered instead, a stricter test that also tells
how orders are given, and needs no re-simulated human games:

Bot openings
    The build orders of every team of the evaluated AI in the games of `reason8 eval
    games`, read from each game's replay, up to that team's first contact (or the 8-minute
    opening window), as the dataset cuts human openings (ADR 0012).

Human openings
    The openings of the dataset's test split (``openings_v2``) on the same map, at the
    positions and with the factions the bot played, started on their spot.

Both are reduced to the same thing: the sequence of unit names ordered, with a run of the
same unit counted once. A human drags a line of buildings in one order and an AI orders
them one at a time, so without that the classifier would only learn how the orders were
given. The features are the counts of single units and of pairs of consecutive units in
the first `STEPS` of the sequence, and the position; the classifier is a logistic
regression.

The score is the share of held-out openings classified right (balanced: as many human as
bot openings per position), with folds that keep the openings of one game together, and a
95% interval from resampling the held-out games. Chance is 50%: the bot passes when the
interval covers it.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence, Set
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

from reason8.evaluation.games import RESULT_NAME, STATE_NAME, TEAMS_NAME
from reason8.game.positions import position_order
from reason8.game.unitdefs import game_unit_defs
from reason8.headless.state import read_records
from reason8.markdown import table
from reason8.openings.contact import first_contact, is_commander, read_fights
from reason8.openings.dataset import INCLUDED
from reason8.openings.extract import OPENING_SECONDS
from reason8.paths import data_dir
from reason8.replays.parse import default_parser, parse_replay
from reason8.replays.replay import Replay

STEPS = 20
ORDERS = "orders"
BUILDS = "builds"
SEPARATE = "separate"
VIEWS = (ORDERS, SEPARATE)
FOLDS = 5
ROUNDS = 2000


def collapse(units: Sequence[str]) -> list[str]:
    """The units in order, a run of the same unit counted once."""
    collapsed: list[str] = []
    for unit in units:
        if not collapsed or collapsed[-1] != unit:
            collapsed.append(unit)
    return collapsed


def sequence_features(units: Sequence[str], prefix: str) -> Counter:
    """Counts of units and of pairs of consecutive units in the first `STEPS` of a sequence,
    a run of the same unit counted once."""
    steps = collapse(units)[:STEPS]
    counted = Counter(f"{prefix}u:{unit}" for unit in steps)
    counted.update(
        f"{prefix}b:{first}>{second}" for first, second in zip(steps, steps[1:], strict=False)
    )
    return counted


def features(
    units: Sequence[str], position: str, static: Set[str] | None = None, view: str = ORDERS
) -> dict[str, float]:
    """The features of one opening, by `view`:

    ``orders``
        all units in the order they were ordered;
    ``separate``
        the structures in their order and the factory units in theirs, so how structure
        and unit orders interleave (a matter of timing: the AI queues one unit at a time)
        does not count. `static` names the structures.
    """
    if view == SEPARATE:
        static = static or set()
        counted = sequence_features([unit for unit in units if unit in static], "s")
        counted.update(sequence_features([unit for unit in units if unit not in static], "f"))
    else:
        counted = sequence_features(units, "")
    return {**dict(counted), f"p:{position}": 1.0}


def bot_openings(games_dir: Path, parser: Path) -> pl.DataFrame:
    """One row per team of the evaluated AI: game, position, faction and units ordered up to
    its first contact or the opening window."""
    teams = pl.read_parquet(games_dir / TEAMS_NAME)
    evaluated = (pl.col("game") == "a") == (pl.col("ally_team") == 0)
    ours = teams.filter(evaluated)
    rows = []
    for result_path in sorted(games_dir.glob(f"*/{RESULT_NAME}")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok"):
            continue
        replays = sorted((result_path.parent / "run" / "demos").glob("*.sdfz"))
        if not replays:
            continue
        document, _ = parse_replay(parser, replays[0])
        replay = Replay(document)
        seed, game = result["seed"], result["game"][-1]
        for team in ours.filter(pl.col("seed") == seed, pl.col("game") == game).iter_rows(
            named=True
        ):
            contact = team["contact_frame"]
            end = min(contact, OPENING_SECONDS * 30) if contact else OPENING_SECONDS * 30
            units = [
                order.unit
                for order in replay.build_orders(team=team["team"], until_frame=end)
                if order.unit and (order.count or 1) > 0
            ]
            rows.append(
                {
                    "group": f"bot-{seed}-{game}",
                    "source": "bot",
                    "position": team["position"],
                    "faction": team["faction"],
                    "units": units,
                }
            )
    return pl.DataFrame(rows)


def human_openings(dataset: Path, map_name: str, wanted: pl.DataFrame) -> pl.DataFrame:
    """The test split's openings on the map, at the positions and with the factions of
    `wanted` (columns position, faction), started on their spot."""
    games = pl.read_parquet(dataset / "games.parquet", columns=["match_id", "map"])
    openings = (
        pl.read_parquet(dataset / "openings.parquet")
        .filter(pl.col("status") == INCLUDED, pl.col("split") == "test", pl.col("on_spot"))
        .join(games.filter(pl.col("map") == map_name), on="match_id")
        .join(wanted.unique(), on=("position", "faction"))
        .select("match_id", "player_slot", "position", "faction")
    )
    rows = (
        pl.scan_parquet(dataset / "test.parquet")
        .select("match_id", "player_slot", "seq_idx", "unit")
        .filter(pl.col("seq_idx").is_not_null())
        .join(openings.lazy(), on=("match_id", "player_slot"))
        .sort("match_id", "player_slot", "seq_idx")
        .group_by("match_id", "player_slot", maintain_order=True)
        .agg(pl.col("position", "faction").first(), pl.col("unit").alias("units"))
        .collect()
    )
    return rows.select(
        pl.format("human-{}", pl.col("match_id")).alias("group"),
        pl.lit("human").alias("source"),
        "position",
        "faction",
        "units",
    )


def balanced(bot: pl.DataFrame, human: pl.DataFrame, seed: int = 0) -> pl.DataFrame:
    """As many bot as human openings at each position: the larger side is drawn at random
    down to the size of the smaller."""
    parts = []
    for (position,), group in bot.group_by("position", maintain_order=True):
        pool = human.filter(pl.col("position") == position)
        size = min(group.height, pool.height)
        if size:
            parts += [group.sample(size, seed=seed), pool.sample(size, seed=seed)]
    return pl.concat(parts) if parts else bot.clear()


def built_units(
    state_path: Path, window_frames: int = OPENING_SECONDS * 30
) -> dict[int, list[str]]:
    """Per team of a state file, the units it finished, in order, until its first contact
    (measured in the same file) or the opening window; commanders left out."""
    contact = first_contact(read_fights(state_path))
    names: dict[str, str] = {}
    built: dict[int, list[str]] = {}
    for record in read_records(state_path):
        if record["t"] == "header":
            names = record["unitdefs"]
        elif record["t"] == "finished":
            team = record["team"]
            frame = record["f"]
            end = contact.get(team)
            end = min(end, window_frames) if end is not None else window_frames
            unit = names.get(str(record["d"]))
            if frame <= end and unit and not is_commander(unit):
                built.setdefault(team, []).append(unit)
    return built


def bot_builds(games_dir: Path) -> pl.DataFrame:
    """One row per team of the evaluated AI with the units it built (`built_units`)."""
    teams = pl.read_parquet(games_dir / TEAMS_NAME)
    evaluated = (pl.col("game") == "a") == (pl.col("ally_team") == 0)
    ours = teams.filter(evaluated)
    rows = []
    for result_path in sorted(games_dir.glob(f"*/{RESULT_NAME}")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        state = result_path.parent / STATE_NAME
        if not result.get("ok") or not state.is_file():
            continue
        built = built_units(state)
        seed, game = result["seed"], result["game"][-1]
        for team in ours.filter(pl.col("seed") == seed, pl.col("game") == game).iter_rows(
            named=True
        ):
            rows.append(
                {
                    "group": f"bot-{seed}-{game}",
                    "source": "bot",
                    "position": team["position"],
                    "faction": team["faction"],
                    "units": built.get(team["team"], []),
                }
            )
    return pl.DataFrame(rows)


def human_builds(
    state_dir: Path, dataset: Path, map_name: str, wanted: pl.DataFrame
) -> pl.DataFrame:
    """One row per human player of the re-simulated test-split games on the map, at the
    positions and with the factions of `wanted`, started on their spot, with the units they
    built (`built_units`)."""
    games = pl.read_parquet(dataset / "games.parquet").filter(
        pl.col("split") == "test", pl.col("map") == map_name, pl.col("status") == INCLUDED
    )
    by_name = {
        name.removesuffix(".sdfz"): match_id
        for name, match_id in games.select("replay_file_name", "match_id").iter_rows()
    }
    players = (
        pl.read_parquet(dataset / "openings.parquet")
        .filter(pl.col("status") == INCLUDED, pl.col("on_spot"))
        .join(wanted.unique(), on=("position", "faction"))
        .select("match_id", "player_slot", "position", "faction")
    )
    rows = []
    for state_path in sorted(state_dir.glob("date=*/*.jsonl.gz")):
        match_id = by_name.get(state_path.name.removesuffix(".jsonl.gz"))
        if match_id is None:
            continue
        built = built_units(state_path)
        for player in players.filter(pl.col("match_id") == match_id).iter_rows(named=True):
            rows.append(
                {
                    "group": f"human-{match_id}",
                    "source": "human",
                    "position": player["position"],
                    "faction": player["faction"],
                    "units": built.get(player["player_slot"], []),
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "group": pl.String,
            "source": pl.String,
            "position": pl.String,
            "faction": pl.String,
            "units": pl.List(pl.String),
        },
    )


def classify(
    openings: pl.DataFrame, static: Set[str] | None = None, view: str = ORDERS, seed: int = 0
) -> pl.DataFrame:
    """Each opening with the held-out prediction of a classifier trained on the other
    folds: ``bot_probability`` and ``correct``."""
    vectorizer = DictVectorizer()
    matrix = vectorizer.fit_transform(
        [
            features(units, position, static, view)
            for units, position in openings.select("units", "position").iter_rows()
        ]
    )
    labels = (openings["source"] == "bot").to_numpy().astype(int)
    groups = openings["group"].to_numpy()
    probability = np.zeros(len(labels))
    for train, test in GroupKFold(n_splits=FOLDS).split(matrix, labels, groups):
        model = LogisticRegression(max_iter=2000, random_state=seed)
        model.fit(matrix[train], labels[train])
        probability[test] = model.predict_proba(matrix[test])[:, 1]
    return openings.with_columns(
        bot_probability=pl.Series(probability),
        correct=pl.Series((probability >= 0.5).astype(int) == labels),
    )


def accuracy_interval(
    classified: pl.DataFrame, rounds: int = ROUNDS, seed: int = 0
) -> tuple[float, float, float]:
    """Share classified right, and a 95% interval from resampling the held-out games."""
    per_group = classified.group_by("group").agg(
        pl.col("correct").sum().alias("right"), pl.len().alias("all")
    )
    right = per_group["right"].to_numpy()
    total = per_group["all"].to_numpy()
    generator = np.random.default_rng(seed)
    picks = generator.integers(0, len(right), size=(rounds, len(right)))
    shares = right[picks].sum(axis=1) / total[picks].sum(axis=1)
    low, high = np.quantile(shares, [0.025, 0.975])
    return float(right.sum() / total.sum()), float(low), float(high)


def distinct_openings(sequences: Sequence[Sequence[str]], steps: int = 10) -> int:
    """How many different openings there are among `sequences`, by their first steps."""
    return len({tuple(collapse(units)[:steps]) for units in sequences})


def report(by_view: dict[str, pl.DataFrame]) -> str:
    classified = by_view[ORDERS]
    share, low, high = accuracy_interval(classified)
    bot = classified.filter(pl.col("source") == "bot")
    lines = [
        f"{bot.height} bot openings from {bot['group'].n_unique()} games, "
        f"{classified.height - bot.height} human openings; first {STEPS} steps, runs "
        f"collapsed; {FOLDS} folds by game.",
        "",
        f"Classified right: {100 * share:.1f}% ({100 * low:.1f}%–{100 * high:.1f}%); "
        "chance is 50%.",
        *(
            f"With structures and factory units as separate sequences ({view}): "
            + "{:.1f}% ({:.1f}%–{:.1f}%).".format(
                *(100 * value for value in accuracy_interval(other))
            )
            for view, other in by_view.items()
            if view != ORDERS
        ),
        "",
        "Distinct bot openings per position (first 10 steps): "
        + ", ".join(
            f"{position} {distinct_openings(group['units'].to_list())}"
            for (position,), group in sorted(
                bot.group_by("position"), key=lambda item: position_order(item[0][0])
            )
        ),
        "",
    ]
    rows = []
    for (position, faction), group in sorted(
        classified.group_by("position", "faction"), key=lambda item: position_order(item[0][0])
    ):
        share, low, high = accuracy_interval(group)
        rows.append(
            [
                faction,
                position,
                str(group.height),
                f"{100 * share:.1f}% ({100 * low:.1f}%–{100 * high:.1f}%)",
            ]
        )
    lines += table(["faction", "position", "openings", "classified right"], rows)
    return "\n".join(lines)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("games", type=Path, help="folder of `reason8 eval games`")
    parser.add_argument("--map", default="Supreme Isthmus v2.1")
    parser.add_argument("--dataset", type=Path, help="default: openings_v2")
    parser.add_argument("--parser", type=Path, help="sdfz-demo-parser binary")
    parser.add_argument(
        "--compare",
        choices=(BUILDS, ORDERS),
        default=BUILDS,
        help="what was built (ADR 0003) or what was ordered",
    )
    parser.add_argument("--state-dir", type=Path, help="re-simulated games: <data dir>/state")
    parser.add_argument("--data-dir", default="data/bar", help="content dir with the game")
    parser.add_argument(
        "--game",
        default="Beyond All Reason test-32018-ad135b9",
        help="the game version whose unit files tell structures from units",
    )


def run(args: argparse.Namespace) -> int:
    dataset = args.dataset or data_dir() / "datasets" / "openings_v2"
    if args.compare == BUILDS:
        bot = bot_builds(args.games)
        state_dir = args.state_dir or data_dir() / "state"
        human = human_builds(state_dir, dataset, args.map, bot.select("position", "faction"))
    else:
        bot = bot_openings(args.games, args.parser or default_parser())
        human = human_openings(dataset, args.map, bot.select("position", "faction"))
    openings = balanced(bot, human)
    if openings.is_empty():
        raise SystemExit("no human openings at the bot's positions (re-simulate test games)")
    print(f"Compared: what was {'built' if args.compare == BUILDS else 'ordered'}.")
    unit_defs = game_unit_defs(Path(args.data_dir).resolve(), args.game)
    static = {name for name, unit in unit_defs.items() if unit.is_static}
    print(report({view: classify(openings, static, view) for view in VIEWS}))
    return 0
