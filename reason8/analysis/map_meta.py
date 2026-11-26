"""Measure the opening meta of each start position: how alike are the openings played there?

Usage::

    uv run reason8 analysis map-meta                        # the tables of docs/research/maps/
    uv run reason8 analysis map-meta --map "Rosetta 1.4.4"  # one map

Replays come from ``<data dir>/parsed/``. A game counts when it is on a map of the
training slice, it is an 8v8 of human players and the lobby left the map's water level
alone. Positions are the recommended start positions of BAR's map metadata
(`reason8.game.positions`); fetch the pinned map list once with
``reason8 maps fetch``.

Three questions per map:

- **How consistent is each position?** Top openings and their share, entropy, and the chance
  that two players of a position ordered the same thing.
- **Can the position be recognised from the builds?** A naive Bayes classifier over the
  kinds of unit ordered in the first minutes, tested on games it has not seen.
- **Can an opening that does not fit its position be told?** The same classifier's
  probability for the position the player actually took.

Players of one game react to each other, so games, not players, are held out.
"""

from __future__ import annotations

import argparse
import math
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from reason8 import markdown
from reason8.analysis.opening_shift import (
    NextUnitModel,
    by_match,
    feature_distance,
    shuffled,
)
from reason8.data.matches import DEFAULT_MAPS
from reason8.game.maps import MapMetadata
from reason8.game.positions import StartSetup, position_order, replay_positions, start_setup
from reason8.models.evaluate import SCORED_STEPS
from reason8.models.ngram import OpeningSteps
from reason8.openings.extract import (
    FACTIONS,
    Opening,
    first_factory,
    opening_shape,
    openings,
    unit_role,
)
from reason8.paths import data_dir
from reason8.replays.replay import GAME_SPEED, iter_replays

TEAM_SIZE = 8
FIRST_ORDERS = 6  # "the first N builds" of the consistency tables
SKILLED = (
    30.0  # OpenSkill mu; about the top quarter of Large Team players (docs/reference/dataset.md)
)
FOLDS = 10  # held-out tests split the games into this many parts
RECOGNITION_MINUTES = (1, 2, 4, 8)
OFF_META_PROBABILITY = 0.05  # an opening is flagged when its own position gets less than this
MINIMUM_OPENINGS = 20  # smaller groups are left out of the tables
SIDE_SHUFFLES = 1000  # shuffles of teams between the sides, for the noise floor


@dataclass
class Sample:
    """The openings of the sampled games per map, with what the measurements need besides.

    `setups` is each game's start setup by match. `places` says, for every opening on a
    position, which side of the layout it is on and where in that side's list:
    (match, team) -> (side, index).
    """

    openings: dict[str, list[Opening]] = field(default_factory=lambda: defaultdict(list))
    setups: dict[str, StartSetup] = field(default_factory=dict)
    places: dict[tuple[str, int], tuple[int, int]] = field(default_factory=dict)


def load_sample(
    parsed_dir: Path,
    maps: Iterable[str] | None = None,
    map_list: Mapping[str, MapMetadata] | None = None,
) -> Sample:
    """Openings of the 8v8 games between humans on the slice maps (or on `maps`).

    Games with a changed water level (the ``map_waterlevel`` lobby option) are left out:
    they are played on different terrain.
    """
    wanted = set(maps) if maps is not None else set(DEFAULT_MAPS)
    sample = Sample()
    for replay in iter_replays(parsed_dir):
        map_name = replay.meta.get("map")
        if map_name not in wanted or replay.ais:
            continue
        if (replay.doc.get("modoptions") or {}).get("map_waterlevel", "0") != "0":
            continue
        found = openings(replay, map_list=map_list)
        sides = Counter(opening.side for opening in found)
        if sorted(sides.values()) == [TEAM_SIZE, TEAM_SIZE]:
            sample.openings[map_name] += found
            sample.setups[found[0].match] = start_setup(replay, map_list)
            for team, position in replay_positions(replay, map_list).items():
                if position.on_spot:
                    sample.places[(found[0].match, team)] = (position.side, position.index)
    return sample


def roles(opening: Opening, length: int | None = None) -> tuple[str, ...]:
    """The opening's orders without faction prefixes, so that factions can be compared."""
    return tuple(unit_role(unit) for unit in opening.units[:length])


def entropy(counts: Counter) -> float:
    """Shannon entropy of the shares, in bits. On small samples it reads too low."""
    total = sum(counts.values())
    if not total:
        return 0.0
    return abs(-sum(n / total * math.log2(n / total) for n in counts.values() if n))


def agreement(counts: Counter) -> float:
    """Chance that two different members of the sample have the same value.

    Unlike entropy this has no small-sample bias: it is the share of pairs that agree.
    """
    total = sum(counts.values())
    if total < 2:
        return math.nan
    return sum(n * (n - 1) for n in counts.values()) / (total * (total - 1))


FEATURES: dict[str, Callable[[Opening], Hashable]] = {
    "first factory": lambda opening: first_factory(opening.units),
    "opening shape": lambda opening: opening_shape(opening.units),
    f"first {FIRST_ORDERS} orders": lambda opening: roles(opening, FIRST_ORDERS),
}


def _label(value: Hashable) -> str:
    return (" ".join(value) if isinstance(value, tuple) else str(value)) or "(nothing)"


def _percent(share: float) -> str:
    return "-" if math.isnan(share) else f"{100 * share:.0f}%"


def _of(part: int, whole: int) -> str:
    return f"{part} of {whole} ({100 * part / max(1, whole):.1f}%)"


def consistency_tables(groups: Mapping[str, Sequence[Opening]], column: str) -> list[str]:
    """Two tables, one row per group: the first factory, then longer parts of the opening.

    Each feature gets the share of its most common value, its entropy and its agreement;
    the longer features also get the number of distinct values. Groups with fewer than
    `MINIMUM_OPENINGS` openings are left out.
    """
    factory_rows, order_rows = [], []
    for name, group in groups.items():
        if len(group) < MINIMUM_OPENINGS:
            continue
        cells: dict[str, list[str]] = {}
        for feature_name, feature in FEATURES.items():
            counts = Counter(feature(opening) for opening in group)
            value, top = counts.most_common(1)[0]
            cells[feature_name] = [
                _label(value),
                str(len(counts)),
                _percent(top / len(group)),
                f"{entropy(counts):.2f}",
                _percent(agreement(counts)),
            ]
        factory = cells["first factory"]
        factory_rows.append([name, str(len(group)), factory[0], *factory[2:]])
        order_rows.append([name, str(len(group))])
        for feature_name in list(FEATURES)[1:]:
            order_rows[-1] += cells[feature_name][1:]
    lines = markdown.table(
        [column, "openings", "first factory", "share", "entropy", "agree"], factory_rows
    )
    header = [column, "openings"]
    for feature_name in list(FEATURES)[1:]:
        header += [f"{feature_name}: distinct", "top share", "entropy", "agree"]
    return [*lines, "", *markdown.table(header, order_rows)]


def top_values(group: Sequence[Opening], feature: Callable[[Opening], Hashable], top: int = 3):
    """The most common values of a feature in a group, with shares, as text."""
    counts = Counter(feature(opening) for opening in group)
    return "; ".join(
        f"`{_label(value)}` {_percent(n / len(group))}" for value, n in counts.most_common(top)
    )


def distinctive_orders(
    by_position: Mapping[str, Sequence[Opening]], top: int = 5, minimum_share: float = 0.3
) -> dict[str, list[tuple[str, float, float, float]]]:
    """Per position, the kinds of unit that set it apart from the other positions.

    A kind counts for a position when at least `minimum_share` of its players order it; the
    `top` kinds with the largest lead over the players of all other positions are returned
    as (kind, share here, share elsewhere, median seconds of the first such order).
    """
    first_orders: dict[str, list[dict[str, float]]] = {}
    for position, group in by_position.items():
        first_orders[position] = []
        for opening in group:
            first: dict[str, float] = {}
            for unit, frame in zip(opening.units, opening.frames, strict=True):
                first.setdefault(unit_role(unit), frame / GAME_SPEED)
            first_orders[position].append(first)
    found = {}
    for position, mine in first_orders.items():
        others = [
            first for other, group in first_orders.items() if other != position for first in group
        ]
        rows = []
        for kind in {kind for first in mine for kind in first}:
            times = sorted(first[kind] for first in mine if kind in first)
            here = len(times) / len(mine)
            elsewhere = sum(kind in first for first in others) / max(1, len(others))
            if here >= minimum_share:
                rows.append((kind, here, elsewhere, times[len(times) // 2]))
        rows.sort(key=lambda row: (row[2] - row[1], row[0]))
        found[position] = rows[:top]
    return found


class PositionNextUnitModel(NextUnitModel):
    """The frequency model, told the position: contexts with the position come first.

    With `group_of` (position -> group) it is told the group instead, e.g. the role, so
    that positions which play alike share their counts.
    """

    LEVELS = (
        (("position", "faction"), 2),
        (("position", "faction"), 1),
        *NextUnitModel.LEVELS,
    )

    def __init__(self, group_of: Mapping[str, str] | None = None) -> None:
        super().__init__()
        self.group_of = group_of

    def steps(self, opening: Opening) -> OpeningSteps:
        steps = super().steps(opening)
        if self.group_of is None or opening.position is None:
            return steps
        return replace(steps, position=self.group_of[opening.position])


def folds(matches: Iterable[str], count: int = FOLDS, seed: int = 0) -> list[set[str]]:
    """The matches split into `count` parts of equal size, in a fixed random order."""
    ordered = sorted(matches)
    random.Random(seed).shuffle(ordered)
    return [set(ordered[index::count]) for index in range(count)]


def next_unit_scores(
    group: Sequence[Opening], model: Callable[[], NextUnitModel]
) -> dict[str | None, tuple[int, int]]:
    """Held-out (correct, total) next-unit predictions per position."""
    scores: dict[str | None, list[int]] = defaultdict(lambda: [0, 0])
    for held_out in folds(by_match(group)):
        fitted = model().fit(o for o in group if o.match not in held_out)
        for opening in group:
            if opening.match in held_out:
                correct, total = fitted.score([opening])
                scores[opening.position][0] += correct
                scores[opening.position][1] += total
    return {position: (correct, total) for position, (correct, total) in scores.items()}


class PositionClassifier:
    """Naive Bayes: which position ordered these units?

    An opening is read as a set of words: each kind of unit ordered (the name without its
    faction prefix, once however often it was ordered) and the kind of the first factory.
    Counting every order instead makes the classifier far too sure of itself: one dragged
    line of wind turbines is forty words. Positions are equally likely beforehand, as they
    are in a game.
    """

    def __init__(self, smoothing: float = 0.5) -> None:
        self.smoothing = smoothing
        self.counts: dict[str, Counter] = defaultdict(Counter)
        self.vocabulary: set[str] = set()

    @staticmethod
    def words(opening: Opening) -> list[str]:
        return [*sorted(set(roles(opening))), "first factory: " + first_factory(opening.units)]

    def fit(self, training: Iterable[Opening]) -> PositionClassifier:
        for opening in training:
            if opening.position is not None:
                words = self.words(opening)
                self.counts[opening.position].update(words)
                self.vocabulary.update(words)
        return self

    def probabilities(self, opening: Opening) -> dict[str, float]:
        """Probability of each position given the opening's orders."""
        size = len(self.vocabulary) + 1  # one more for words never seen
        words = self.words(opening)
        scores = {}
        for position, counts in self.counts.items():
            total = sum(counts.values()) + self.smoothing * size
            scores[position] = sum(
                math.log((counts[word] + self.smoothing) / total) for word in words
            )
        highest = max(scores.values())
        weights = {position: math.exp(score - highest) for position, score in scores.items()}
        norm = sum(weights.values())
        return {position: weight / norm for position, weight in weights.items()}

    def predict(self, opening: Opening) -> str:
        found = self.probabilities(opening)
        return max(found, key=found.get)


def by_group(found: Mapping[str, float], group_of: Mapping[str, str]) -> dict[str, float]:
    """Position probabilities added up per group of positions, e.g. per role."""
    summed: dict[str, float] = defaultdict(float)
    for position, probability in found.items():
        summed[group_of[position]] += probability
    return dict(summed)


def held_out_probabilities(
    group: Sequence[Opening], seconds: float
) -> list[tuple[Opening, dict[str, float]]]:
    """Each placed opening with the classifier's probabilities, fitted without its game."""
    placed = [opening.until(seconds) for opening in group if opening.position is not None]
    results = []
    for held_out in folds(by_match(placed)):
        classifier = PositionClassifier().fit(o for o in placed if o.match not in held_out)
        results += [
            (opening, classifier.probabilities(opening))
            for opening in placed
            if opening.match in held_out
        ]
    return results


def planted(
    results: Sequence[tuple[Opening, dict[str, float]]],
    group_of: Mapping[str, str],
    seed: int = 0,
) -> list[tuple[Opening, dict[str, float], str]]:
    """Openings that are certainly not their position's: real builds, a teammate's position.

    Each opening is paired with the position of a random teammate from another group
    (`group_of`: position -> group; the identity plants any other position). Returns
    (opening, its probabilities, the claimed position); openings without such a teammate
    are left out.
    """
    teams: dict[tuple[str, int], set[str]] = defaultdict(set)
    for opening, _ in results:
        teams[(opening.match, opening.side)].add(opening.position)
    generator = random.Random(seed)
    swapped = []
    for opening, found in results:
        others = sorted(
            position
            for position in teams[(opening.match, opening.side)]
            if group_of[position] != group_of[opening.position]
        )
        if others:
            swapped.append((opening, found, generator.choice(others)))
    return swapped


def setup_lines(group: Sequence[Opening], setups: Mapping[str, StartSetup]) -> list[str]:
    """How the games were set up, and how many players start on a spot in each case."""
    games = by_match(group)
    rows = []
    for title, test in (
        ("recommended positions shown", lambda setup: setup.overlay),
        ("recommended positions not shown", lambda setup: not setup.overlay),
        ("default start boxes", lambda setup: setup.default_boxes is True),
        ("changed start boxes", lambda setup: setup.default_boxes is False),
        ("start boxes not comparable", lambda setup: setup.default_boxes is None),
    ):
        members = [o for match, found in games.items() if test(setups[match]) for o in found]
        on_spot = sum(o.position is not None for o in members)
        rows.append(
            [title, str(len(by_match(members))), str(len(members))]
            + [f"{100 * on_spot / len(members):.1f}%" if members else "-"]
        )
    return markdown.table(["games with", "games", "openings", "on a spot"], rows)


def sides_lines(
    group: Sequence[Opening],
    places: Mapping[tuple[str, int], tuple[int, int]],
    rounds: int = SIDE_SHUFFLES,
) -> list[str]:
    """Do the two sides of the layout open alike at the same place of their lists?

    The spawn points of the two sides are different positions, but the map list gives
    both sides the same roles in the same order. Each opening is given its place in the
    list instead of its position, and the first side is compared with the second: the
    total variation distance of a feature per place, next to the same distance after
    shuffling whole teams between the sides (teammates react to each other).
    """
    sides: tuple[list[Opening], list[Opening]] = ([], [])
    labels: dict[tuple[int, int], str] = {}
    for opening in group:
        place = places.get((opening.match, opening.team))
        if place is None or opening.position is None or place[0] > 1:
            continue
        side, index = place
        labels[place] = opening.position
        team = f"{opening.match}/{opening.side}"
        sides[side].append(replace(opening, match=team, position=str(index)))
    first, second = sides
    if not first or not second:
        return []
    rows = []
    for title, feature in (
        ("first factory per place", lambda o: (o.position, first_factory(o.units))),
        ("opening shape per place", lambda o: (o.position, opening_shape(o.units))),
        ("faction per place", lambda o: (o.position, o.faction)),
    ):

        def statistic(a, b, feature=feature):
            return feature_distance(a, b, feature)

        mean, high, p_value = shuffled(first, second, statistic, rounds)
        rows.append(
            [title, f"{statistic(first, second):.3f}", f"{mean:.3f}", f"{high:.3f}"]
            + [f"{p_value:.3f}"]
        )
    teams = f"{len(by_match(first))} teams against {len(by_match(second))}"
    lines = [f"First side against second side, {teams}:", ""]
    lines += markdown.table(["feature", "distance", "shuffled mean", "shuffled 95%", "p"], rows)
    rows = []
    for index in sorted({int(o.position) for o in first}):
        here = [[o for o in side if o.position == str(index)] for side in sides]
        if not all(here):
            continue
        top = Counter(first_factory(o.units) for side in here for o in side).most_common(1)
        cells = [
            f"{_percent(sum(first_factory(o.units) == top[0][0] for o in side) / len(side))}"
            f" of {len(side)}"
            for side in here
        ]
        rows.append([labels[(0, index)], labels[(1, index)], top[0][0], *cells])
    lines += ["", "Share of the most common first factory at the same place of the two lists:"]
    header = ["first side", "second side", "first factory", "first side", "second side"]
    return [*lines, "", *markdown.table(header, rows)]


def report(
    map_name: str,
    group: Sequence[Opening],
    setups: Mapping[str, StartSetup] | None = None,
    places: Mapping[tuple[str, int], tuple[int, int]] | None = None,
) -> str:
    # Tables show a position with its role: "P5 front".
    group = [
        replace(opening, position=f"{opening.position} {opening.role}")
        if opening.position is not None
        else opening
        for opening in group
    ]
    placed = [opening for opening in group if opening.position is not None]
    spot_roles = {opening.position: str(opening.role) for opening in placed}
    names = sorted(spot_roles, key=position_order)
    identity = {name: name for name in names}
    by_position = {name: [o for o in placed if o.position == name] for name in names}
    skilled = [o for o in placed if o.skill is not None and o.skill >= SKILLED]
    games = by_match(group)
    lines = [f"# {map_name}", "", "## Sample", ""]
    lines += [
        f"{len(games)} games, {len(group)} openings, {_of(len(placed), len(group))} on a spot, "
        f"{len(skilled)} of those by players with mu >= {SKILLED:g}.",
        "",
    ]
    teams: dict[tuple[str, int], list[str | None]] = defaultdict(list)
    for opening in group:
        teams[(opening.match, opening.side)].append(opening.position)
    complete = sum(len(set(spots) - {None}) == TEAM_SIZE for spots in teams.values())
    doubled = sum(
        max(Counter(spot for spot in spots if spot).values(), default=0) > 1
        for spots in teams.values()
    )
    lines += [
        f"{_of(complete, len(teams))} teams fill all {TEAM_SIZE} spots; "
        f"{doubled} teams have two players on one spot."
    ]
    if setups is not None:
        lines += ["", "## Start setup", "", *setup_lines(group, setups)]
    if places is not None:
        lines += ["", "## The two sides", "", *sides_lines(group, places)]

    for title, subset in (("all players", placed), (f"mu >= {SKILLED:g}", skilled)):
        lines += ["", f"## Consistency per position, {title}", ""]
        groups = {name: [o for o in subset if o.position == name] for name in names}
        lines += consistency_tables(groups, "position")
        for feature_name in ("opening shape", f"first {FIRST_ORDERS} orders"):
            lines += ["", f"Most common {feature_name}:", ""]
            for name, members in groups.items():
                if len(members) >= MINIMUM_OPENINGS:
                    lines.append(f"- {name}: " + top_values(members, FEATURES[feature_name]))

    lines += ["", "## Consistency per position and faction, all players", ""]
    groups = {
        f"{name}, {faction}": [o for o in by_position[name] if o.faction == faction]
        for name in names
        for faction in FACTIONS
    }
    lines += consistency_tables(groups, "position, faction")
    small = {label: len(members) for label, members in groups.items()}
    lines += [
        "",
        f"Left out (fewer than {MINIMUM_OPENINGS} openings): "
        + ", ".join(f"{label} {n}" for label, n in small.items() if n < MINIMUM_OPENINGS),
    ]

    lines += ["", "## What sets each position apart", ""]
    lines += [
        "Kinds of unit ordered in the first 8 minutes by a larger share of the position's "
        "players than of everyone else's: share here (share elsewhere), median time of the "
        "first such order.",
        "",
    ]
    for name, rows in distinctive_orders(by_position).items():
        listed = [
            f"`{kind}` {_percent(here)} ({_percent(elsewhere)}) at "
            f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
            for kind, here, elsewhere, seconds in rows
        ]
        lines.append(f"- {name}: " + "; ".join(listed))

    lines += ["", "## Factions per position", ""]
    rows = []
    for name in (*names, "all"):
        members = placed if name == "all" else by_position[name]
        counts = Counter(o.faction if o.faction in FACTIONS else "other" for o in members)
        rows.append(
            [name, str(len(members))]
            + [_percent(counts[faction] / len(members)) for faction in (*FACTIONS, "other")]
        )
    lines += markdown.table(["position", "openings", *FACTIONS, "other"], rows)

    lines += ["", "## First factory per position and faction", ""]
    kinds = [kind for kind, _ in Counter(first_factory(o.units) for o in placed).most_common()]
    rows = []
    for label, members in groups.items():
        if len(members) >= MINIMUM_OPENINGS:
            counts = Counter(first_factory(o.units) for o in members)
            rows.append(
                [label, str(len(members))]
                + [_percent(counts[kind] / len(members)) for kind in kinds]
            )
    lines += markdown.table(["position, faction", "openings", *kinds], rows)

    lines += ["", f"## Next-unit accuracy, first {SCORED_STEPS} orders, held-out games", ""]
    models = (
        next_unit_scores(placed, NextUnitModel),
        next_unit_scores(placed, lambda: PositionNextUnitModel(spot_roles)),
        next_unit_scores(placed, PositionNextUnitModel),
    )
    plain = models[0]
    rows = [
        [name, str(plain[name][1])]
        + [f"{scores[name][0] / scores[name][1]:.3f}" for scores in models]
        for name in names
    ]
    orders = sum(total for _, total in plain.values())
    rows.append(
        ["all", str(orders)]
        + [f"{sum(correct for correct, _ in scores.values()) / orders:.3f}" for scores in models]
    )
    lines += markdown.table(
        ["position", "orders", "faction only", "faction and role", "faction and position"], rows
    )

    lines += ["", "## Recognising the position from the orders", ""]
    rows = []
    results: list[tuple[Opening, dict[str, float]]] = []
    for minutes in RECOGNITION_MINUTES:
        results = held_out_probabilities(placed, 60 * minutes)
        right = sum(max(found, key=found.get) == o.position for o, found in results)
        role_right = 0
        for opening, found in results:
            per_role = by_group(found, spot_roles)
            role_right += max(per_role, key=per_role.get) == spot_roles[opening.position]
        kinds_ordered = sorted(len(set(o.units)) for o, _ in results)
        rows.append(
            [str(minutes), str(kinds_ordered[len(kinds_ordered) // 2])]
            + [f"{right / len(results):.3f}", f"{role_right / len(results):.3f}"]
        )
    lines += markdown.table(
        ["minutes", "kinds of unit (median)", "position right", "role right"], rows
    )
    role_counts = Counter(spot_roles[o.position] for o in placed)
    lines += [
        "",
        f"Guessing: {1 / len(names):.3f} for the position, "
        f"{max(role_counts.values()) / len(placed):.3f} for the role (always the commonest).",
    ]

    minutes = RECOGNITION_MINUTES[-1]  # `results` now holds the last, longest window
    lines += ["", f"### Per position after {minutes} minutes", ""]
    rows = []
    for name in names:
        mine = [(o, found) for o, found in results if o.position == name]
        guesses = Counter(max(found, key=found.get) for _, found in mine)
        listed = [f"{guess} {_percent(n / len(mine))}" for guess, n in guesses.most_common(3)]
        rows.append(
            [name, spot_roles[name], str(len(mine)), _percent(guesses[name] / len(mine))]
            + [", ".join(listed)]
        )
    lines += markdown.table(["position", "role", "openings", "recognised", "guessed as"], rows)

    lines += ["", f"## Openings that do not fit their position, after {minutes} minutes", ""]
    lines += [
        f"An opening is flagged when the classifier gives the player's own position (or "
        f"role: all positions with that role together) less than {OFF_META_PROBABILITY:g}.",
        "",
    ]
    rows = []
    for title, group_of in (("position", identity), ("role", spot_roles)):

        def flagged(found: Mapping[str, float], position: str, group_of=group_of) -> bool:
            return by_group(found, group_of)[group_of[position]] < OFF_META_PROBABILITY

        genuine = sum(flagged(found, o.position) for o, found in results)
        low = [(o, found) for o, found in results if o.skill is not None and o.skill < SKILLED]
        high = [(o, found) for o, found in results if o.skill is not None and o.skill >= SKILLED]
        swapped = planted(results, group_of)
        rows.append(
            [
                title,
                _of(genuine, len(results)),
                _of(sum(flagged(found, o.position) for o, found in low), len(low)),
                _of(sum(flagged(found, o.position) for o, found in high), len(high)),
                _of(sum(flagged(found, claimed) for _, found, claimed in swapped), len(swapped)),
            ]
        )
    lines += markdown.table(
        ["own", "flagged", f"mu < {SKILLED:g}", f"mu >= {SKILLED:g}", "planted, flagged"], rows
    )

    lines += ["", "Flagged by position:", ""]
    rows = []
    for name in names:
        mine = [(o, found) for o, found in results if o.position == name]
        mine_flagged = [o for o, found in mine if found[name] < OFF_META_PROBABILITY]
        usual = Counter(first_factory(o.units) for o, _ in mine).most_common(1)[0][0]
        other_factory = sum(first_factory(o.units) != usual for o in mine_flagged)
        rows.append(
            [name, str(len(mine)), str(len(mine_flagged))]
            + [_percent(len(mine_flagged) / len(mine)), str(other_factory)]
        )
    lines += markdown.table(
        ["position", "openings", "flagged", "share", "of those, another first factory"], rows
    )
    return "\n".join(lines)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--parsed", type=Path, default=data_dir() / "parsed")
    parser.add_argument("--map", action="append", help="map name; default: all")


def run(args: argparse.Namespace) -> int:
    sample = load_sample(args.parsed, args.map)
    for map_name, group in sample.openings.items():
        print(report(map_name, group, sample.setups, sample.places))
        print()
    return 0
