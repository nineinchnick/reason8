# 0001. Record decisions as ADRs

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

The project produces a lot of research and measurement docs. Decisions that
drive further development end up inside them, often near the end, and are hard
to find later. A reader, human or agent, needs to know what holds today
without reading how it came about.

## Decision

Record each decision that shapes further development as a short architecture
decision record (ADR) in `docs/decisions/`, using
[`template.md`](template.md). The supporting research stays in its own doc and
is linked from the record.

Each record states the decision as it stands now. When a decision changes, its
record is rewritten to say what holds, and the commit that changes it says
what changed and why; git keeps the earlier versions. There are no superseded
records. Records are numbered from the most fundamental decision to the most
specific; a new record takes the next free number.

## Consequences

- Decisions can be found in one place, with their reasons, and every record
  can be read on its own without following a chain of replacements.
- Research docs report findings and point to the record instead of restating
  the decision.
- The history of a decision is in git, not in the docs: `git log` on a record
  shows how it changed.
