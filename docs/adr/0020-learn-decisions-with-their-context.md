# 0020. Learn decisions with their context, not build orders alone

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

The first models predict the next unit a player orders from the previous
orders, the faction, the map and the position (ADR 0018). Players don't decide
that way:

- They set up their build queue from the resources they have, and those change
  during a game. Wind strength is random within each map's range, so whether
  wind generators are worth building differs from game to game.
- Where a building goes matters as much as what it is. Expensive or rare
  buildings get protection; cheap ones such as solar collectors are
  expendable; buildings that explode when destroyed are kept apart from each
  other and from the rest of the base.
- After first contact, orders react to raids and losses that the commands
  don't show.

Most of that context is available:

- Every build order in a replay carries its position and facing.
- The map archive and BAR's map metadata give metal spots, geothermal vents,
  terrain, and the wind and tidal ranges.
- The game's unit definitions give cost, build time, energy output and
  explosion damage and radius.
- Re-simulating a replay (ADR 0002) gives the actual wind, each team's income,
  expense and storage, and what was finished, lost or destroyed, over time.

## Decision

Models predict the player's next decision, meaning what to build, where, and
when, given that context: map and position, unit properties, wind, current
resources and the buildings already standing. Training data therefore joins
the replay's orders with re-simulated state, at least for the part of the game
being learned.

Re-simulate a sample of a few thousand games locally first, and measure how
much each kind of context improves prediction over the order-only baselines
before re-simulating the whole slice.

Batching orders by dragging, which players use to save actions, is a later
goal that belongs with the action budget of ADR 0009, not with what is learned
first.

## Consequences

- Re-simulation is needed for openings as well, not only from milestone 2:
  about 65 s of one core and 5 to 6 GB of RAM per replay for the first 10
  minutes.
- The dataset gains placement (position relative to the start, metal spots,
  vents and other buildings), unit properties and per-snapshot state.
- The in-game side has to pass positions to BARb, which today chooses where to
  build itself (ADR 0011).
- The order-only models stay as baselines to beat.
- This supersedes the "build orders from commands alone" scope of ADR 0005 and
  ADR 0007 for training; reading orders from commands stays the way orders are
  extracted.
