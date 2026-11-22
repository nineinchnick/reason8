"""Measure how much openings differ between groups of games, e.g. across balance patches.

Usage::

    uv run python -m reason8.opening_shift            # the tables of docs/game-versions.md
    uv run python -m reason8.opening_shift --list     # replay files of the sample, per group

Replays come from ``<data dir>/parsed/``; only games that pass the training-slice filters of
`reason8.match_dumps.select_matches()` are used.

Every comparison is reported next to its noise floor: the same statistic after shuffling the
group labels of whole matches. Two samples from one distribution are never at distance zero,
so a distance means something only when it stands clear of the shuffled ones.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reason8.game_versions import BALANCE_OPTIONS, balance_options, build_number
from reason8.openings import Opening, first_factory, opening_shape, openings
from reason8.parse import output_path
from reason8.positions import position_order
from reason8.replay import load_replay

# Steps per opening used for next-unit accuracy. A few players send hundreds of orders in
# the first minutes (one drag queues dozens of wind turbines) and would otherwise decide
# the result.
SCORED_ORDERS = 30


def total_variation(first: Counter, second: Counter) -> float:
    """Total variation distance between two samples: 0 same shares, 1 nothing in common."""
    first_total, second_total = sum(first.values()), sum(second.values())
    if not first_total or not second_total:
        return math.nan
    keys = first.keys() | second.keys()
    return 0.5 * sum(abs(first[key] / first_total - second[key] / second_total) for key in keys)


def feature_distance(
    first: Sequence[Opening], second: Sequence[Opening], feature: Callable[[Opening], Hashable]
) -> float:
    return total_variation(Counter(map(feature, first)), Counter(map(feature, second)))


class NextUnitModel:
    """Most frequent next unit after the previous two orders of the same faction.

    Backs off to the previous order alone, then to the faction's most ordered unit. The
    start of the game counts as an order, so the first orders are predicted from what
    players of that faction order first. This is the frequency baseline an opening model has
    to beat.
    """

    START = "<start>"

    def __init__(self, context: int = 2) -> None:
        self.context = context
        self.counts: dict[tuple[str | None, ...], Counter] = defaultdict(Counter)

    def _keys(self, opening: Opening, index: int) -> list[tuple[str | None, ...]]:
        """Contexts of the order at `index`, longest first."""
        before = (self.START,) * self.context + opening.units[:index]
        return [
            (opening.faction, *before[len(before) - length :])
            for length in range(self.context, -1, -1)
        ]

    def fit(self, training: Iterable[Opening]) -> NextUnitModel:
        for opening in training:
            for index, unit in enumerate(opening.units[:SCORED_ORDERS]):
                for key in self._keys(opening, index):
                    self.counts[key][unit] += 1
        return self

    def predict(self, opening: Opening, index: int) -> str | None:
        for key in self._keys(opening, index):
            seen = self.counts.get(key)
            if seen:
                return seen.most_common(1)[0][0]
        return None

    def score(self, test: Iterable[Opening]) -> tuple[int, int]:
        """(correct, total) next-unit predictions over the scored steps of every opening."""
        correct = total = 0
        for opening in test:
            for index, unit in enumerate(opening.units[:SCORED_ORDERS]):
                total += 1
                correct += self.predict(opening, index) == unit
        return correct, total


def by_match(group: Iterable[Opening]) -> dict[str, list[Opening]]:
    matches: dict[str, list[Opening]] = defaultdict(list)
    for opening in group:
        matches[opening.match].append(opening)
    return matches


def transfer_scores(
    training: Sequence[Opening], test: Sequence[Opening]
) -> dict[str, tuple[int, int]]:
    """Per test match, (correct, total) of the frequency model fitted on `training`."""
    model = NextUnitModel().fit(training)
    return {match: model.score(members) for match, members in by_match(test).items()}


def held_out_scores(
    group: Sequence[Opening],
    training_matches: int | None = None,
    extra: Sequence[Opening] = (),
    seed: int = 0,
) -> dict[str, tuple[int, int]]:
    """Per match, (correct, total) of the frequency model fitted on the group's other matches.

    `training_matches` caps how many other matches are used, to compare like with like
    against a model fitted on a smaller group. `extra` openings (from other groups) are
    added to the training data of every match.
    """
    matches = by_match(group)
    scores = {}
    for match, members in matches.items():
        others = sorted(name for name in matches if name != match)
        if training_matches is not None and training_matches < len(others):
            others = random.Random(f"{seed}/{match}").sample(others, training_matches)
        model = NextUnitModel().fit([*(o for name in others for o in matches[name]), *extra])
        scores[match] = model.score(members)
    return scores


def accuracy(scores: Mapping[str, tuple[int, int]]) -> float:
    total = sum(total for _, total in scores.values())
    return sum(correct for correct, _ in scores.values()) / total if total else math.nan


def accuracy_difference_interval(
    first: Mapping[str, tuple[int, int]],
    second: Mapping[str, tuple[int, int]],
    rounds: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """95% bootstrap interval of accuracy(first) - accuracy(second) over the same matches."""
    matches = sorted(first)
    generator = random.Random(seed)
    differences = []
    for _ in range(rounds):
        drawn = generator.choices(matches, k=len(matches))
        differences.append(
            accuracy({i: first[m] for i, m in enumerate(drawn)})
            - accuracy({i: second[m] for i, m in enumerate(drawn)})
        )
    differences.sort()
    return differences[int(0.025 * rounds)], differences[int(0.975 * rounds) - 1]


def shuffled(
    first: Sequence[Opening],
    second: Sequence[Opening],
    statistic: Callable[[Sequence[Opening], Sequence[Opening]], float],
    rounds: int = 1000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Noise floor of a two-group statistic: reshuffle whole matches between the groups.

    Players of one match share a game version and react to each other, so matches, not
    players, are exchanged. Returns the mean and 95th percentile of the shuffled statistic
    and the share of shuffles at or above the observed one (a one-sided p-value).
    """
    observed = statistic(first, second)
    first_matches = list(by_match(first).values())
    pool = first_matches + list(by_match(second).values())
    generator = random.Random(seed)
    values = []
    for _ in range(rounds):
        generator.shuffle(pool)
        values.append(
            statistic(
                [o for match in pool[: len(first_matches)] for o in match],
                [o for match in pool[len(first_matches) :] for o in match],
            )
        )
    values.sort()
    at_or_above = sum(value >= observed for value in values)
    return (
        sum(values) / rounds,
        values[min(rounds - 1, int(0.95 * rounds))],
        (at_or_above + 1) / (rounds + 1),
    )


# The sample of docs/game-versions.md: (name, first build, last build), cut at the balance
# patches that change what an opening costs.
GROUPS = (
    ("before Season 3", 29034, 29240),
    ("May patch", 30236, 30754),
    ("July patch", 30755, 31074),
    ("since August patch", 31075, 10**9),
)
NEWEST_GROUP = GROUPS[-1][0]
LATE_BUILD = 31720  # splits the newest group in two for a comparison without a patch between
SAMPLE_MAP = "Supreme Isthmus v2.1"
SAMPLE_SKILL = 22.1  # the slice's median lobby skill on that map (docs/dataset.md)
SAMPLE_SINCE, SAMPLE_UNTIL = datetime(2025, 11, 22), datetime(2026, 11, 22)
MINIMUM_GAMES = 10  # groups smaller than this are shown but not tested


@dataclass(frozen=True)
class SampleMatch:
    build: int
    options: dict[str, str]  # balance-changing lobby options that are switched on


def group_of(build: int) -> str | None:
    return next((name for name, low, high in GROUPS if low <= build <= high), None)


def sample_matches() -> dict[str, int]:
    """Replay file name -> build of the slice-quality Supreme Isthmus games of 12 months."""
    from reason8 import match_dumps

    chosen = match_dumps.select_matches(
        match_dumps.scan_dump("matches"),
        match_dumps.scan_dump("match_players"),
        maps=[SAMPLE_MAP],
        since=SAMPLE_SINCE,
        until=SAMPLE_UNTIL,
        min_avg_skill=SAMPLE_SKILL,
    )
    builds = {}
    for row in chosen.select("replay_file_name", "game_version").iter_rows(named=True):
        build = build_number(row["game_version"])
        if build is not None:
            builds[row["replay_file_name"]] = build
    return builds


def load_sample(parsed_dir: Path) -> tuple[list[Opening], dict[str, SampleMatch]]:
    """Openings (with start spots) and match details of the parsed sample replays."""
    loaded: list[Opening] = []
    matches: dict[str, SampleMatch] = {}
    for file_name, build in sorted(sample_matches().items()):
        path = output_path(parsed_dir, Path(file_name))
        if not path.exists() or group_of(build) is None:
            continue
        replay = load_replay(path)
        match_openings = openings(replay)
        if not match_openings:
            continue
        loaded += match_openings
        matches[match_openings[0].match] = SampleMatch(
            build, balance_options(replay.doc.get("modoptions") or {})
        )
    return loaded, matches


def _table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _share_table(groups: Mapping[str, Sequence[Opening]], feature, top: int = 6) -> list[str]:
    everything = Counter(feature(o) for group in groups.values() for o in group)
    rows = []
    for value, _ in everything.most_common(top):
        label = " ".join(value) if isinstance(value, tuple) else str(value)
        rows.append(
            [label]
            + [
                f"{100 * sum(feature(o) == value for o in group) / len(group):.0f}%"
                if group
                else "-"
                for group in groups.values()
            ]
        )
    return _table(["", *(f"{name} (n={len(group)})" for name, group in groups.items())], rows)


FEATURES: dict[str, Callable[[Opening], Hashable]] = {
    "first factory": lambda o: (o.faction, first_factory(o.units)),
    "first factory per start spot": lambda o: (o.position, o.faction, first_factory(o.units)),
    "opening shape": lambda o: (o.faction, opening_shape(o.units)),
    "first 6 orders": lambda o: o.units[:6],
}


def _distance_rows(
    label: str, first: Sequence[Opening], second: Sequence[Opening], rounds: int
) -> list[list[str]]:
    rows = []
    games = f"{len(by_match(first))} vs {len(by_match(second))}"
    for name, feature in FEATURES.items():

        def statistic(a, b, feature=feature):
            return feature_distance(a, b, feature)

        mean, high, p_value = shuffled(first, second, statistic, rounds)
        rows.append(
            [label, games, name, f"{statistic(first, second):.3f}", f"{mean:.3f}", f"{high:.3f}"]
            + [f"{p_value:.3f}"]
        )
    return rows


def report(all_openings: Sequence[Opening], matches: Mapping[str, SampleMatch], rounds: int) -> str:
    groups: dict[str, list[Opening]] = {name: [] for name, _, _ in GROUPS}
    for opening in all_openings:
        groups[group_of(matches[opening.match].build)].append(opening)
    newest = groups[NEWEST_GROUP]
    lines = ["## Sample", ""]
    lines += _table(
        ["group", "builds", "games", "openings"],
        [
            [name, f"{low}..{high if high < 10**9 else ''}", str(len(by_match(groups[name])))]
            + [str(len(groups[name]))]
            for name, low, high in GROUPS
        ],
    )
    placed = sum(o.position is not None for o in all_openings)
    lines += ["", f"start spot found for {placed} of {len(all_openings)} openings"]

    for faction in (None, "Armada", "Cortex"):
        subset = {
            name: [o for o in group if faction is None or o.faction == faction]
            for name, group in groups.items()
        }
        lines += ["", f"## First factory, {faction or 'all factions'}", ""]
        lines += _share_table(subset, lambda o: first_factory(o.units))
        lines += ["", f"## Opening shape (first 4 steps), {faction or 'all factions'}", ""]
        lines += _share_table(subset, lambda o: opening_shape(o.units))

    lines += ["", "## Most common first factory per start spot", ""]
    rows = []
    by_position: dict[str | None, list[Opening]] = defaultdict(list)
    for opening in all_openings:
        by_position[opening.position].append(opening)
    spots = sorted((name for name in by_position if name is not None), key=position_order)
    for position in spots:
        here = by_position[position]
        top = Counter(first_factory(o.units) for o in here).most_common(1)[0][0]
        cells = []
        for group in groups.values():
            members = [o for o in group if o.position == position]
            share = sum(first_factory(o.units) == top for o in members) / max(1, len(members))
            cells.append(f"{100 * share:.0f}% of {len(members)}")
        rows.append([position, top, *cells])
    lines += _table(["spot", "first factory", *groups], rows)
    spot_pairs = [
        feature_distance(by_position[first], by_position[second], lambda o: first_factory(o.units))
        for index, first in enumerate(spots)
        for second in spots[index + 1 :]
    ]
    if spot_pairs:
        spot_pairs.sort()
        lines += [
            "",
            "first-factory distance between two start spots (all groups pooled): "
            f"median {spot_pairs[len(spot_pairs) // 2]:.2f}, "
            f"range {spot_pairs[0]:.2f}..{spot_pairs[-1]:.2f}",
        ]

    lines += ["", "## Distance between groups (total variation) and its noise floor", ""]
    rows = []
    for name, group in groups.items():
        if name != NEWEST_GROUP and len(by_match(group)) >= MINIMUM_GAMES:
            rows += _distance_rows(f"{name} vs {NEWEST_GROUP}", group, newest, rounds)
    early = [o for o in newest if matches[o.match].build < LATE_BUILD]
    late = [o for o in newest if matches[o.match].build >= LATE_BUILD]
    label = f"{NEWEST_GROUP}: builds before vs from {LATE_BUILD}"
    rows += _distance_rows(label, early, late, rounds)
    header = ["comparison", "games", "feature", "distance", "shuffled mean", "shuffled p95", "p"]
    lines += _table(header, rows)

    lines += ["", "## Lobby options that change balance", ""]
    rows = []
    for option in BALANCE_OPTIONS:
        on = [o for o in all_openings if option in matches[o.match].options]
        off = [o for o in all_openings if option not in matches[o.match].options]
        if min(len(by_match(on)), len(by_match(off))) >= MINIMUM_GAMES:
            rows += _distance_rows(f"{option} on vs off", on, off, rounds)
        elif on:
            rows.append([f"{option} on vs off", f"{len(by_match(on))} vs {len(by_match(off))}"])
            rows[-1] += ["too few games", "", "", "", ""]
    lines += _table(header, rows)

    lines += ["", f"## Next-unit accuracy on '{NEWEST_GROUP}' (first {SCORED_ORDERS} orders)", ""]
    rows = []
    for name, group in groups.items():
        games = len(by_match(group))
        if name == NEWEST_GROUP or games < MINIMUM_GAMES:
            continue
        old = transfer_scores(group, newest)
        same = held_out_scores(newest, games)
        low, high = accuracy_difference_interval(old, same)
        rows.append(
            [name, str(games), f"{accuracy(old):.3f}", f"{accuracy(same):.3f}"]
            + [f"{accuracy(old) - accuracy(same):+.3f} ({low:+.3f}..{high:+.3f})"]
        )
    lines += _table(
        ["trained on", "games", "accuracy", "same number of newest games", "difference (95%)"],
        rows,
    )

    lines += ["", f"## Next-unit accuracy on '{NEWEST_GROUP}' with older games added", ""]
    alone = held_out_scores(newest)
    rows = [[f"{NEWEST_GROUP} only", str(len(by_match(newest)) - 1), f"{accuracy(alone):.3f}", ""]]
    older: list[Opening] = []
    for name in reversed([name for name in groups if name != NEWEST_GROUP]):
        older = older + groups[name]
        added = held_out_scores(newest, extra=older)
        low, high = accuracy_difference_interval(added, alone)
        games = len(by_match(newest)) - 1 + len(by_match(older))
        rows.append(
            [f"+ {name}", str(games), f"{accuracy(added):.3f}"]
            + [f"{accuracy(added) - accuracy(alone):+.3f} ({low:+.3f}..{high:+.3f})"]
        )
    lines += _table(["training data", "games", "accuracy", "difference (95%)"], rows)

    lines += ["", "## Next-unit accuracy by number of training games (all groups pooled)", ""]
    everything = by_match(all_openings)
    rows = []
    for games in (1, 2, 5, 10, 20, 40, 80, len(everything) - 1):
        if games < len(everything):
            scores = held_out_scores(all_openings, games)
            rows.append([str(games), str(games * 16), f"{accuracy(scores):.3f}"])
    lines += _table(["training games", "openings", "accuracy"], rows)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from reason8 import match_dumps

    argument_parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    argument_parser.add_argument("--parsed", type=Path, default=match_dumps.data_dir() / "parsed")
    argument_parser.add_argument("--rounds", type=int, default=1000, help="label shuffles")
    argument_parser.add_argument(
        "--list", action="store_true", help="print the parsed replays of the sample, per group"
    )
    args = argument_parser.parse_args(argv)
    if args.list:
        for file_name, build in sorted(sample_matches().items(), key=lambda item: item[1]):
            path = output_path(args.parsed, Path(file_name))
            if group_of(build) and path.exists():
                print(f"{group_of(build)}\t{build}\t{file_name}")
        return 0
    print(report(*load_sample(args.parsed), args.rounds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
