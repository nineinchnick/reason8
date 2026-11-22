# 0007. Read build orders from replay commands

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

Openings are build orders, and every build order a player gives is a command
in the replay. BAR's own `sdfz-demo-parser` turns replays into JSON, with
build commands resolved to unit names, but it drops the ids of BAR's custom
commands and misreads the command id of batched widget orders, losing about 7%
of build orders in an 8v8 game ([`replay-format.md`](../replay-format.md)).

## Decision

For openings, read build orders directly from the replay's commands, without
re-simulating the game. Parse with the pinned standalone `sdfz-demo-parser`,
re-read the command packets from the replay file ourselves to recover the
correct command ids, and store one compact gzipped JSON document per replay.

## Consequences

- Parsing is fast (about a second per replay) and needs no engine.
- A command is an intention: orders can be cancelled, replaced or never
  finished, so "ordered" and "built" differ. Knowing what was finished needs
  re-simulation (ADR 0002).
- Our command reader must agree with the parser packet by packet; a mismatch
  is an error, not a guess.
- The parsed files keep player names and ids for joining with match data, so
  they must not be published.
