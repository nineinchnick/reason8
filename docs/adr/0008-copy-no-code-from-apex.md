# 0008. Copy no code from Apex

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

Apex (`apexearth/bar-ai`) is the closest related project and has useful
tooling, including headless replay extraction. Its repository has no licence
file: the Lua gadgets and widgets declare GPL v2 or later, `cpp/` derives from
GPL-2.0 CircuitAI, and the Python tools declare nothing
([`related-work.md`](../related-work.md)).

## Decision

Read Apex for ideas and measurements, but copy no code from it. Write our own
replay widget and tools.

## Consequences

- Our code stays clearly under Reason8's GPL-2.0 licence.
- Some work is duplicated, such as the state-export widget.
- Revisit if Apex adds a licence that covers the whole repository.
