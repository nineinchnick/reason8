# 0005. Learn decisions with their context

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

A replay records the commands players gave, not the game they were playing
([`replay-format.md`](../reference/replay-format.md)). Every build order is a
command, so what players ordered, where and when can be read straight from the
replay. BAR's own `sdfz-demo-parser` turns replays into JSON with build
commands resolved to unit names, but it drops the ids of BAR's custom commands
and misreads the command id of batched widget orders, losing about 7% of the
build orders of an 8v8 game.

Players don't decide from their previous orders alone:

- They set up their build queue from the resources they have, and those change
  during a game. Wind strength is random within each map's range, so whether
  wind generators are worth building differs from game to game.
- Where a building goes matters as much as what it is. Expensive or rare
  buildings get protection; cheap ones such as solar collectors are
  expendable; buildings that explode when destroyed are kept apart from each
  other and from the rest of the base.
- After first contact, orders react to raids and losses that the commands
  don't show ([ADR 0012](0012-end-openings-at-first-contact.md)).
- A command is an intention: orders are cancelled, replaced or never finished,
  so "ordered" and "built" differ.

Most of that context is available:

- Every build order in a replay carries its position and facing.
- The map archive and BAR's map metadata give metal spots, geothermal vents,
  terrain, and the wind and tidal ranges.
- The game's unit definitions give cost, build time, energy output and
  explosion damage and radius.
- Re-simulating a replay
  ([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)) gives
  the actual wind, each team's income, expense and storage, what was finished,
  lost or destroyed, and who was hit by whom, over time.

## Decision

Models predict the player's next decision, meaning what to build, where, and
when, given that context: map and position, unit properties, wind, current
resources and the buildings already standing.

- **Orders come from the replay's commands.** Replays are parsed with the
  pinned standalone `sdfz-demo-parser`, and the command packets are read again
  from the replay file by our own reader (`reason8.replays.sdfz`) to recover
  the correct command ids. Each replay is stored as one compact,
  zstd-compressed JSON document (`reason8 parse`).
- **State comes from re-simulating the replay.** Training data joins the
  orders with the re-simulated state, at least for the part of the game being
  learned.
- **Measure before scaling.** Re-simulate a sample of a few thousand games
  locally first, and measure how much each kind of context improves prediction
  over the order-only baselines ([`results.md`](../results.md)) before
  re-simulating the whole slice.

## Consequences

- Parsing is fast (about 1.6 s of wall time per replay with 8 jobs) and needs
  no engine, so every downloaded replay is parsed; re-simulation is the
  expensive step, about 65 s of one core and 5 to 6 GB of RAM per replay for
  the first 10 minutes.
- Our command reader must agree with the parser packet by packet; a mismatch
  is an error, not a guess.
- The parsed files keep player names and ids for joining with match data, so
  they must not be published.
- The dataset gains placement (position relative to the start, metal spots,
  vents and other buildings), unit properties and per-snapshot state.
- The in-game side has to pass positions to BARb, which today chooses where to
  build itself
  ([ADR 0007](0007-ship-the-model-as-tables-in-a-barb-variant.md)).
- The order-only models stay as baselines to beat.
- Batching orders by dragging, which players use to save actions, is learned
  later, with the action budget of
  [ADR 0008](0008-play-under-human-like-limits.md).
