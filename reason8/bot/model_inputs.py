"""The builder model's inputs as the library computed them in a game, checked against the
state export of the same game.

With the learned model (``reason8/builder_model.json`` in the AI folder) our library logs
the inputs of every fourth decision of a team, from the first (``LogInputs`` in
``ai/native/NextOrder.cpp``): every name, every number but zero, ``?`` for a missing one::

    Reason8 next order: team 2: frame 913: armck 1234 construction: inputs faction=Armada;
    map=Supreme Isthmus v2.1; position=P3; role=front; step_idx=7; ...

`compare` computes the same inputs again from what `reason8 bot check` has besides the log,
as the decision table defines them (``docs/reference/builder-model.md``, "The inputs"), and
counts where the two differ:

- the economy: the last resource line of the state export before the decision's frame
  (the table's ``state_frame``), as the export wrote it;
- the team's units, finished and under construction, by type: the export's ``created``,
  ``finished``, ``given`` and ``destroyed`` lines before that frame;
- the build power of the team's finished builders by kind, and of the idle ones: the
  build power and kind of each builder type from the model file's ``builders``, and a
  builder idle from its export ``idle`` line until the bot's next order to it in the log;
- the builder: its kind, whether it moves and its build power from ``builders``, its
  type from its name;
- the order history: the bot's orders in the log (the model's that were given, and
  BARb's), counted and cut into steps as the table does;
- the start: the faction of the team's commander, the replay's map, and the start
  position nearest to the commander's start in the map list's layout for two teams of
  eight, with its role;
- the time: the frame over 30.

Skill is chosen, not computed, and is only reported. Both rows are encoded as the trees
read them (`reason8.models.trees.Feature.encode`) and compared too.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from reason8.models.trees import CATEGORICAL, TreeFile

INPUTS_LINE = re.compile(r"frame (\d+): (\w+) (\d+) (\w+): inputs (.*)")
DECIDED = re.compile(r"frame (\d+): (\w+) (\d+) \w+: model chose (\S+) ")
BARB_ORDERED = re.compile(r"frame (\d+): (\w+) (\d+) \w+: BARb ordered (\S+)$")
NOT_GIVEN = re.compile(r"frame (\d+): (\w+) (\d+) \w+: cannot carry out (\S+): (.*); left to BARb")
MISSING = "?"
START = "<start>"
OTHER = "other"
STEP_FRAMES = 6
JOBS = ("assist", "reclaim", "repair", "resurrect")
KINDS = ("commander", "factory", "construction", "tower", "other")
ECONOMY = (
    "metal",
    "metal_storage",
    "metal_income",
    "metal_expense",
    "energy",
    "energy_storage",
    "energy_income",
    "energy_expense",
)
FACTIONS = {"arm": "Armada", "cor": "Cortex", "leg": "Legion"}
#: The usual metal spots, and with them the bot's start positions, come from games of two
#: teams of this many players (`reason8.bot.build.TEAM_SIZE`).
TEAM_SIZE = 8
#: Numbers closer than this are the same (the log writes 9 significant digits).
TOLERANCE = 1e-4


def unit_type(unit: str) -> str:
    return unit[3:] if unit[:3] in FACTIONS else unit


def parse_inputs(text: str) -> dict[str, Any]:
    """The ``name=value; ...`` part of an inputs line: numbers as floats, names as text,
    None for a missing input."""
    inputs: dict[str, Any] = {}
    for part in text.split("; "):
        name, _, value = part.partition("=")
        if value == MISSING:
            inputs[name] = None
            continue
        try:
            inputs[name] = float(value)
        except ValueError:
            inputs[name] = value
    return inputs


class History:
    """The bot's orders so far, as the library counts them (``OrderHistory`` in
    ``ai/native/ModelInputs.h``), computed again from the log."""

    def __init__(self) -> None:
        self.orders = 0
        self.steps = 0
        self.last: tuple[str, int] | None = None
        self.previous_step = START
        self.by_answer: Counter[str] = Counter()
        self.builder_previous: dict[int, str] = {}

    def record(self, unit_id: int, answer: str, frame: int) -> None:
        if not (self.last and self.last[0] == answer and frame - self.last[1] <= STEP_FRAMES):
            self.steps += 1
            self.previous_step = answer
        self.last = (answer, frame)
        self.orders += 1
        self.by_answer[answer] += 1
        self.builder_previous[unit_id] = answer

    def inputs(self, unit_id: int, types: Sequence[str]) -> dict[str, Any]:
        ordered: Counter[str] = Counter()
        for answer, count in self.by_answer.items():
            if answer in JOBS:
                ordered[answer] += count
            else:
                kind = unit_type(answer)
                ordered[kind if kind in types else OTHER] += count
        return {
            "step_idx": float(self.steps),
            "decision_index": float(self.orders),
            "previous_1": self.previous_step,
            "builder_previous": self.builder_previous.get(unit_id, START),
            **{f"ordered_{name}": float(ordered[name]) for name in (*types, *JOBS)},
        }


LINE_FRAME = re.compile(r"frame (\d+): ")


def logged_decisions(lines: Iterable[str]) -> list[dict]:
    """The logged inputs of one team's decisions (the ``Reason8 next order: team N:`` part
    removed), each with the history the bot's orders before it give."""
    history = History()
    snapshot: tuple[int, History] | None = None
    decisions = []
    for line, order in _with_orders(lines):
        if order is not None:
            history.record(*order)
        if logged := INPUTS_LINE.match(line):
            unit_id = int(logged.group(3))
            decisions.append(
                {
                    "frame": int(logged.group(1)),
                    "unit": logged.group(2),
                    "unit_id": unit_id,
                    "kind": logged.group(4),
                    "logged": parse_inputs(logged.group(5)),
                    "history": snapshot[1] if snapshot and snapshot[0] == unit_id else None,
                }
            )
        elif DECIDED.match(line) or _left_to_barb(line):
            snapshot = (int(line.split()[3].rstrip(":")), _copy(history))
    return decisions


def _left_to_barb(line: str) -> bool:
    return line.startswith("frame ") and any(
        f": {outcome}" in line for outcome in ("below threshold", "nothing possible", "no answers")
    )


def _with_orders(lines: Iterable[str]) -> Iterator[tuple[str, tuple[int, str, int] | None]]:
    """Each line with the order of the bot that the library records just before it, as
    (unit, answer, frame), or None. BARb's orders are recorded at once; the model's at the
    next decision, BARb order or frame, unless the script reports it could not be carried
    out before then (``CommitPending`` and ``Failed`` in ``ai/native/NextOrder.cpp``)."""
    pending: tuple[int, str, int] | None = None
    for line in lines:
        order = None
        frame = LINE_FRAME.match(line)
        later = frame is not None and pending is not None and int(frame.group(1)) > pending[2]
        if pending is not None and (later or DECIDED.match(line) or BARB_ORDERED.match(line)):
            order, pending = pending, None
        if decided := DECIDED.match(line):
            pending = (int(decided.group(3)), decided.group(4), int(decided.group(1)))
        elif ordered := BARB_ORDERED.match(line):
            if order is not None:
                yield line, order  # the model's pending order first
                order = None
            yield line, (int(ordered.group(3)), ordered.group(4), int(ordered.group(1)))
            continue
        elif (failed := NOT_GIVEN.match(line)) and pending and pending[0] == int(failed.group(3)):
            pending = None
        yield line, order
    if pending is not None:
        yield "", pending  # given at the end of the log


def _copy(history: History) -> History:
    copy = History()
    copy.orders, copy.steps, copy.last = history.orders, history.steps, history.last
    copy.previous_step = history.previous_step
    copy.by_answer = Counter(history.by_answer)
    copy.builder_previous = dict(history.builder_previous)
    return copy


class GameState:
    """One team's state from the state export, read forward in frame order: the
    resources of the last line, the units by id and which of them are idle."""

    def __init__(self, records: Sequence[dict], team: int) -> None:
        self.records = [record for record in records if record.get("t") != "header"]
        header = next((record for record in records if record.get("t") == "header"), {})
        self.names: dict[str, str] = header.get("unitdefs", {})
        self.team = team
        self.position = 0
        self.resources: list | None = None
        self.units: dict[int, tuple[str, bool]] = {}  # id -> (name, finished)
        self.idle: set[int] = set()

    def advance(self, before_frame: int) -> None:
        """Apply every record of a frame before `before_frame`."""
        while self.position < len(self.records):
            record = self.records[self.position]
            if record.get("f", 0) >= before_frame:
                return
            self.position += 1
            self._apply(record)

    def _apply(self, record: dict) -> None:
        kind = record["t"]
        if kind == "r":
            row = next((row for row in record["teams"] if row[0] == self.team), None)
            if row is not None:
                self.resources = row
            return
        if kind not in ("created", "finished", "given", "destroyed", "idle"):
            return
        unit_id = record["u"]
        name = self.names.get(str(record.get("d")), str(record.get("d")))
        ours = record.get("team") == self.team
        if kind == "created" and ours:
            self.units[unit_id] = (name, False)
        elif kind == "finished" and unit_id in self.units:
            self.units[unit_id] = (self.units[unit_id][0], True)
        elif kind == "given":
            if ours:
                self.units[unit_id] = (name, True)
            else:
                self.units.pop(unit_id, None)
                self.idle.discard(unit_id)
        elif kind == "destroyed":
            self.units.pop(unit_id, None)
            self.idle.discard(unit_id)
        elif kind == "idle" and ours:
            self.idle.add(unit_id)


def expected_inputs(
    decision: dict,
    state: GameState,
    model: TreeFile,
    types: Sequence[str],
    start: Mapping[str, Any],
) -> dict[str, Any]:
    """The inputs of one logged decision as the decision table would have them."""
    frame = decision["frame"]
    state.advance(frame)  # the table's state frame is the frame before the order
    expected: dict[str, Any] = {**start, "time_s": frame / 30}
    if decision["history"] is not None:
        expected |= decision["history"].inputs(decision["unit_id"], types)
    builder = model.builders.get(decision["unit"])
    expected["builder_kind"] = decision["kind"] if builder is None else builder["kind"]
    expected["builder_role"] = unit_type(decision["unit"])
    if builder is not None:
        expected["builder_moves"] = float(builder["moves"])
        expected["builder_build_power"] = float(builder["build_power"])
    if state.resources is not None:
        expected |= {
            name: float(value) for name, value in zip(ECONOMY, state.resources[1:], strict=True)
        }
    done = Counter({name: 0 for name in types})
    building = Counter({name: 0 for name in types})
    team_power = dict.fromkeys(KINDS, 0.0)
    idle_power = dict.fromkeys(KINDS, 0.0)
    for unit_id, (name, finished) in state.units.items():
        kind = unit_type(name)
        kind = kind if kind in types else OTHER
        if not finished:
            building[kind] += 1
            continue
        done[kind] += 1
        entry = model.builders.get(name)
        if entry is not None and entry["build_power"] > 0:
            team_power[entry["kind"]] += entry["build_power"]
            if unit_id in state.idle:
                idle_power[entry["kind"]] += entry["build_power"]
    for name in types:
        expected[f"own_done_{name}"] = float(done[name])
        expected[f"own_building_{name}"] = float(building[name])
    expected["team_build_power"] = sum(team_power.values())
    expected["idle_build_power"] = sum(idle_power.values())
    for kind in KINDS:
        expected[f"team_build_power_{kind}"] = team_power[kind]
        expected[f"idle_build_power_{kind}"] = idle_power[kind]
    return expected


def start_of(
    records: Sequence[dict],
    team: int,
    model: TreeFile,
    map_name: str | None,
    map_list: Mapping | None,
) -> dict[str, Any]:
    """Faction, map, position and role of a team as the table finds them: the faction of
    its commander, and the start position nearest to where the commander was created, in
    the map list's layout for two teams of `TEAM_SIZE`, with its role."""
    names = next((r for r in records if r.get("t") == "header"), {}).get("unitdefs", {})
    found: dict[str, Any] = {"map": map_name}
    start = None
    for record in records:
        if record.get("t") == "created" and record.get("team") == team:
            name = names.get(str(record.get("d")), "")
            if model.builders.get(name, {}).get("kind") == "commander":
                found["faction"] = FACTIONS.get(name[:3])
                start = (record["x"], record["z"])
                break
    metadata = (map_list or {}).get(map_name)
    layout = (
        metadata.start_positions.layout_for(2, TEAM_SIZE)
        if metadata is not None and metadata.start_positions is not None
        else None
    )
    if layout is not None and start is not None:
        point = min(
            (point for side in layout.sides for point in side),
            key=lambda point: (point.x - start[0]) ** 2 + (point.z - start[1]) ** 2,
        )
        found["position"], found["role"] = point.id, point.role
    return found


def same(logged: Any, expected: Any) -> bool:
    if isinstance(logged, float) and isinstance(expected, float):
        return math.isclose(logged, expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE)
    return logged == expected


def compare(
    lines: Sequence[str],
    records: Sequence[dict],
    team: int,
    model: TreeFile,
    *,
    map_name: str | None = None,
    map_list: Mapping | None = None,
) -> dict:
    """How one team's logged inputs differ from the inputs computed again (see the module).

    `lines` are the team's ``Reason8 next order`` messages without their ``team N:``
    prefix, in log order; `records` the state file's records (`read_records` with
    snapshots, for the resource lines); `map_name` the replay's map."""
    decisions = logged_decisions(lines)
    types = [
        feature.name.removeprefix("own_done_")
        for feature in model.features
        if feature.name.startswith("own_done_")
    ]
    state = GameState(records, team)
    team_start = start_of(records, team, model, map_name, map_list)
    # the bot's orders make its builders busy, as the library applies them
    busy = sorted(_orders(lines))
    differing: Counter[str] = Counter()
    largest: dict[str, float] = {}
    examples: dict[str, list] = {}
    rows_equal = 0
    compared = 0
    skill: set[float] = set()
    for decision in decisions:
        while busy and busy[0][0] < decision["frame"]:
            state.advance(busy[0][0] + 1)
            state.idle.discard(busy.pop(0)[1])
        expected = expected_inputs(decision, state, model, types, team_start)
        logged = decision["logged"]
        if isinstance(logged.get("skill"), float):
            skill.add(logged["skill"])
        compared += 1
        row_logged = model.encode(
            {name: logged.get(name, 0.0) for name in _names(model)} | _missing(logged)
        )
        row_expected = model.encode(
            {
                name: logged.get("skill") if name == "skill" else expected.get(name)
                for name in _names(model)
            }
        )
        equal = True
        for feature, left, right in zip(model.features, row_logged, row_expected, strict=True):
            if feature.name == "skill" or (math.isnan(left) and math.isnan(right)) or left == right:
                continue
            equal = False
            name = feature.name
            differing[name] += 1
            value = (
                logged.get(name, 0.0 if feature.type != CATEGORICAL else None),
                expected.get(name),
            )
            if feature.type != CATEGORICAL and None not in value:
                largest[name] = max(largest.get(name, 0.0), abs(value[0] - value[1]))
            examples.setdefault(name, [])
            if len(examples[name]) < 3:
                examples[name].append(
                    {"frame": decision["frame"], "logged": value[0], "expected": value[1]}
                )
        rows_equal += equal
    return {
        "decisions_logged": compared,
        "rows_equal": rows_equal,
        "inputs_differing": dict(differing.most_common()),
        "largest_difference": {name: round(value, 4) for name, value in sorted(largest.items())},
        "examples": examples,
        "skill": sorted(skill),
        "start": team_start,
    }


def _names(model: TreeFile) -> list[str]:
    return [feature.name for feature in model.features]


def _missing(logged: Mapping[str, Any]) -> dict[str, Any]:
    return {name: None for name, value in logged.items() if value is None}


def _orders(lines: Iterable[str]) -> list[tuple[int, int]]:
    """(frame, unit) of every order of the bot that the library records."""
    return [(order[2], order[0]) for _, order in _with_orders(lines) if order is not None]
