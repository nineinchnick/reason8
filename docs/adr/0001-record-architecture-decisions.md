# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

The project produces a lot of research and measurement docs. Decisions that
drive further development end up inside them, often near the end, and are hard
to find later.

## Decision

Record each decision that shapes further development as a short architecture
decision record in `docs/adr/`, using [`template.md`](template.md). The
supporting research stays in its own doc and is linked from the record.

## Consequences

- Decisions can be found in one place, with their reasons.
- Research docs report findings and point to the ADR instead of restating the
  decision.
- Changing a decision means writing a new record that supersedes the old one,
  so the history stays visible.
