"""Game versions, balance patches and the version policy.

Evidence in docs/game-versions.md, decision in ADR 0012 (docs/adr/).

A game version looks like ``Beyond All Reason test-32018-ad135b9``. Games are released from
the `stable` branch of Beyond-All-Reason: the number is the commit count of that branch at
the release, so it only grows, and the hash is the release commit. We call the number the
*build* and order versions by it.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

VERSION_PATTERN = re.compile(r"^Beyond All Reason test-(\d+)-([0-9a-f]{7,40})$")


def build_number(game_version: str | None) -> int | None:
    """Build of a released game version, e.g. 32018 for ``Beyond All Reason test-32018-ad135b9``.

    ``None`` for anything else: a missing version or a pull-request build
    (``Beyond All Reason pr-9493-...``), which is not a release and has no place in the order.
    """
    match = VERSION_PATTERN.match(game_version or "")
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class BalancePatch:
    """A balance change to the base game, for all factions.

    `changes_openings` marks patches that touch the cost, build time or build power of what
    players order in the first minutes: first-tier economy, factories, constructors,
    construction turrets and the main first-tier combat units. It is a reading of the patch
    notes, not a measurement.
    """

    first_build: int
    released: date
    name: str
    pull_request: int  # in beyond-all-reason/Beyond-All-Reason
    changes_openings: bool
    summary: str


# Balance patches since mid-2025, oldest first. `first_build` is the first release whose
# history contains the patch's merge commit. Add new patches at the end (see the retraining
# routine in docs/game-versions.md).
BALANCE_PATCHES = (
    BalancePatch(
        28407,
        date(2025, 7, 24),
        "July 2025 balance patch",
        5543,
        True,
        "T1 factories cheaper with more build power, commander makes more energy",
    ),
    BalancePatch(
        28548, date(2025, 8, 30), "August 2025 balance patch", 5736, False, "aircraft, T2 units"
    ),
    BalancePatch(
        29241,
        date(2026, 1, 8),
        "Season 3",
        6583,
        True,
        "T1 aircraft plants and hovercraft platforms cheaper, construction turrets dearer, "
        "T2 factories cheaper with twice the build power, smaller and cheaper fusions",
    ),
    BalancePatch(
        29251, date(2026, 1, 10), "Shield rework", 6625, False, "shields block projectiles"
    ),
    BalancePatch(
        29466,
        date(2026, 2, 16),
        "February balance patch",
        6801,
        False,
        "radars, mines, T2 units, idle auto-heal",
    ),
    BalancePatch(
        30051,
        date(2026, 5, 4),
        "Brake rate and sight distance",
        7542,
        False,
        "minimum brake rate and sight distance for vehicles and bots",
    ),
    BalancePatch(
        30236,
        date(2026, 5, 29),
        "May balance patch",
        7620,
        True,
        "T1 bot constructors tougher, T1 tanks and Rover take longer to build",
    ),
    BalancePatch(30299, date(2026, 6, 5), "Commando patch", 7853, False, "Commando"),
    BalancePatch(
        30755,
        date(2026, 7, 23),
        "July balance patch",
        8333,
        True,
        "T1 tanks and Rover take longer to build, Grunt dearer, anti-air turrets stronger",
    ),
    BalancePatch(
        30874,
        date(2026, 8, 5),
        "Naval anti-air",
        8621,
        False,
        "floating anti-air turrets match the land ones",
    ),
    BalancePatch(
        31075,
        date(2026, 8, 25),
        "August balance patch",
        8726,
        True,
        "T1 air constructors 35% cheaper, faster to build and slower; Legion's T1.5 metal "
        "extractor removed",
    ),
    BalancePatch(
        31357,
        date(2026, 9, 19),
        "Air constructors and mobile jammers",
        9218,
        True,
        "T1 air constructors lose 10 build power",
    ),
    BalancePatch(
        31479,
        date(2026, 10, 1),
        "Vertical missile launchers",
        9415,
        False,
        "missile flight paths, damage and costs of missile units",
    ),
    BalancePatch(
        31720,
        date(2026, 10, 23),
        "Turrets, anti-air and missile flight",
        9752,
        False,
        "light laser turrets aim earlier, anti-air retargets, mobile missile flight reverted",
    ),
    BalancePatch(
        31891,
        date(2026, 11, 8),
        "Navy standardisation",
        10016,
        False,
        "naval mines, radars and nuclear submarines match the land ones",
    ),
)


def opening_era(build: int) -> BalancePatch | None:
    """The last patch that changed openings at or before `build`; ``None`` before the table."""
    era = None
    for patch in BALANCE_PATCHES:
        if patch.changes_openings and patch.first_build <= build:
            era = patch
    return era


def opening_patches_between(first_build: int, last_build: int) -> list[BalancePatch]:
    """Patches that changed openings after `first_build`, up to and including `last_build`."""
    return [
        patch
        for patch in BALANCE_PATCHES
        if patch.changes_openings and first_build < patch.first_build <= last_build
    ]


# Lobby options that change unit stats or the units available, so two games of one build
# can differ in balance. Ranked lobbies do switch some of them on (docs/game-versions.md).
BALANCE_OPTIONS = (
    "naval_balance_tweaks",
    "community_balance_patch",
    "proposed_unit_reworks",
    "experimentallegionfaction",
    "legionsimplifiedmexes",
    "shieldsrework",
    "lategame_rebalance",
    "air_rework",
    "emprework",
    "junorework",
    "techsplit",
    "techsplit_balance",
    "experimentalextraunits",
    "releasecandidates",
    "scavunitsforplayers",
    "evocom",
    "experimentalshields",
)
_OPTION_OFF = {"", "0", "disabled", "unchanged"}
_TWEAK_PREFIXES = ("tweakdefs", "tweakunits")


def balance_options(modoptions: Mapping[str, str]) -> dict[str, str]:
    """The balance-changing lobby options that are switched on, with their values.

    Covers the named `BALANCE_OPTIONS`, custom unit tweaks (``tweakdefs*``, ``tweakunits*``)
    and stat multipliers (``multiplier_*`` other than 1). An empty result is a standard game.
    """
    switched_on = {}
    for name, value in modoptions.items():
        value = str(value)
        if name in BALANCE_OPTIONS or name.startswith(_TWEAK_PREFIXES):
            if value not in _OPTION_OFF:
                switched_on[name] = value
        elif name.startswith("multiplier_") and value not in ("1", "1.0", ""):
            switched_on[name] = value
    return dict(sorted(switched_on.items()))


# Unit names that changed: old name -> current name. None found in the builds 29036..32018
# (docs/game-versions.md); the table is here so a rename becomes a one-line change.
UNIT_RENAMES: dict[str, str] = {}


def current_unit_name(unit: str) -> str:
    """The name a unit has today (follows chains of renames)."""
    seen = set()
    while unit in UNIT_RENAMES and unit not in seen:
        seen.add(unit)
        unit = UNIT_RENAMES[unit]
    return unit


def playable_units(units: Iterable[str], unit_definitions: Iterable[str]) -> tuple[str, ...] | None:
    """An opening in today's unit names, or ``None`` if it uses a unit that no longer exists.

    `unit_definitions` are the unit names of the game version the model will play, from a
    game with the same factions enabled (a parsed replay's ``unitdefs``). An opening built
    around a removed unit cannot be played as it was, so the whole opening is dropped rather
    than cut short.
    """
    known = set(unit_definitions)
    renamed = tuple(current_unit_name(unit) for unit in units)
    return renamed if all(unit in known for unit in renamed) else None


def unit_name_changes(
    old_definitions: Iterable[str], new_definitions: Iterable[str]
) -> tuple[list[str], list[str]]:
    """(added, removed) unit names between two versions, after applying `UNIT_RENAMES`.

    Compare games with the same factions enabled: a game with Legion has a few hundred more
    unit definitions than one without.
    """
    old = {current_unit_name(name) for name in old_definitions if name}
    new = {name for name in new_definitions if name}
    return sorted(new - old), sorted(old - new)


# The commander of each faction, by the faction's unit name prefix.
FACTION_COMMANDERS = {"arm": "armcom", "cor": "corcom", "leg": "legcom"}


def loaded_factions(unit_definitions: Iterable[str]) -> set[str]:
    """Unit name prefixes of the factions a game has loaded: those whose commander it has.

    The prefixes of the names alone do not say it: a game without Legion still defines a
    few Legion helper units (``legnanotcbase``, ``leghaap``, ...).
    """
    known = set(unit_definitions)
    return {prefix for prefix, commander in FACTION_COMMANDERS.items() if commander in known}


# About 30 days of releases (builds grow by about 8.6 a day): the retraining interval.
STALE_BUILDS = 260
# The span we measured openings over (12 months); nothing is known beyond it.
MEASURED_BUILDS = 3000


@dataclass(frozen=True)
class TrainedOn:
    """The game versions a model was trained on, stored with the model."""

    first_build: int
    last_build: int
    units: frozenset[str]  # every unit name the model can output

    @classmethod
    def from_training_data(cls, game_versions: Iterable[str], units: Iterable[str]) -> TrainedOn:
        builds = [build for build in map(build_number, game_versions) if build is not None]
        if not builds:
            raise ValueError("no released game version in the training data")
        return cls(min(builds), max(builds), frozenset(units))

    def to_json(self) -> dict[str, object]:
        return {
            "first_build": self.first_build,
            "last_build": self.last_build,
            "units": sorted(self.units),
        }

    @classmethod
    def from_json(cls, document: Mapping[str, object]) -> TrainedOn:
        return cls(
            int(document["first_build"]), int(document["last_build"]), frozenset(document["units"])
        )


@dataclass(frozen=True)
class Compatibility:
    level: str  # "ok", "warn" or "refuse"
    reasons: tuple[str, ...]


class IncompatibleGameVersion(RuntimeError):
    """The model must not be used with this game version."""


def check_game_version(
    trained: TrainedOn, game_version: str | None, unit_definitions: Iterable[str] | None = None
) -> Compatibility:
    """How far the running game is from the versions a model was trained on.

    Refuse when the model can order a unit the game no longer has (among the factions the
    game has loaded), or when the game is further from the training data than the span we
    measured. Warn when a patch that changes openings came out after the training data,
    when the training data is older than the retraining interval, when the game is older
    than the training data, or when the version is not a release.
    """
    warnings_found: list[str] = []
    refusals: list[str] = []
    if unit_definitions is not None:
        known = {name for name in unit_definitions if name}
        loaded = loaded_factions(known)
        missing = sorted(
            unit
            for unit in map(current_unit_name, trained.units)
            if unit not in known and (unit[:3] in loaded or unit[:3] not in FACTION_COMMANDERS)
        )
        if missing:
            refusals.append(f"units the model can order are not in this game: {', '.join(missing)}")

    build = build_number(game_version)
    if build is None:
        warnings_found.append(f"not a released game version: {game_version!r}")
    elif build < trained.first_build:
        gap = trained.first_build - build
        target = refusals if gap > MEASURED_BUILDS else warnings_found
        target.append(f"game build {build} is {gap} builds older than the training data")
    elif build > trained.last_build:
        gap = build - trained.last_build
        if gap > MEASURED_BUILDS:
            refusals.append(
                f"game build {build} is {gap} builds newer than the training data, "
                f"beyond the {MEASURED_BUILDS} builds openings were measured over"
            )
        patches = opening_patches_between(trained.last_build, build)
        if patches:
            names = ", ".join(f"{patch.name} ({patch.first_build})" for patch in patches)
            warnings_found.append(f"patches that change openings since training: {names}")
        elif gap > STALE_BUILDS:
            warnings_found.append(
                f"game build {build} is {gap} builds newer than the training data; retrain"
            )
    if refusals:
        return Compatibility("refuse", tuple(refusals + warnings_found))
    if warnings_found:
        return Compatibility("warn", tuple(warnings_found))
    return Compatibility("ok", ())


def ensure_compatible(
    trained: TrainedOn, game_version: str | None, unit_definitions: Iterable[str] | None = None
) -> Compatibility:
    """`check_game_version`, raising on "refuse" and emitting a warning on "warn"."""
    result = check_game_version(trained, game_version, unit_definitions)
    if result.level == "refuse":
        raise IncompatibleGameVersion("; ".join(result.reasons))
    if result.level == "warn":
        warnings.warn("; ".join(result.reasons), stacklevel=2)
    return result
