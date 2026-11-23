# 0002. License the project GPL-2.0-or-later

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

Reason8 builds on Beyond All Reason: its AI is a variant of BARb, whose
scripts come from the game, and it reads BAR's data. Beyond All Reason's code
is GPL-2.0-or-later. BAR's map metadata (spawn points, their roles and the
default start areas, in `beyond-all-reason/maps-metadata`) is Apache-2.0,
which is compatible with GPL version 3 but not with GPL version 2 only.

## Decision

License Reason8 under the GNU General Public License, version 2 or later
(`GPL-2.0-or-later`), the same as BAR's code.

## Consequences

- Code copied from BAR stays compatible.
- Apache-2.0 sources such as BAR's map metadata can be used, under the terms
  of GPL version 3 where needed.
- The licence text in `LICENSE` is GPL version 2; the "or any later version"
  option is stated in `pyproject.toml` and the README.
