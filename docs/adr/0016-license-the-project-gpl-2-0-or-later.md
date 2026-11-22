# 0016. License the project GPL-2.0-or-later

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

Reason8 was set up as GPL-2.0-only. Beyond All Reason's code is
GPL-2.0-or-later, and BAR's map metadata (spawn points, their roles and the
default start areas, in `beyond-all-reason/maps-metadata`) is Apache-2.0.
Apache-2.0 is compatible with GPL version 3 but not with GPL version 2 only,
which put using that metadata in question.

## Decision

License Reason8 under the GNU General Public License, version 2 or later
(`GPL-2.0-or-later`), the same as BAR's code.

## Consequences

- Apache-2.0 sources such as BAR's map metadata can be used, under the terms
  of GPL version 3 where needed.
- Code copied from BAR stays compatible as before.
- The licence text in `LICENSE` is unchanged: GPL version 2 with the "or any
  later version" option, stated in `pyproject.toml` and the README.
