# 0005. Learn decisions with their context

- **Status:** Accepted
- **Date:** 2026-11-26

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
  the correct command ids. `reason8 parse` turns each replay into one compact
  document in memory and keeps it only as rows of Parquet tables.
- **The tables are the one copy of the parsed replays.** They hold one row per
  command, per selection, per lifecycle event (start, game over, resign, team
  died, player left, pause, quit), per chat message, map drawing,
  start-position pick and resource share, per player, AI or spectator, per
  sample of the end-of-game statistics and per game, and so everything the
  document holds but the names of players and spectators. User ids stay, for
  the join with the match dumps, and so does the chat text. A field of the
  document without a column is an error, not a field dropped: the replay fails
  to parse until the tables have a column for it. A command keeps its frame,
  player, team, `via`, the units it is addressed to, its name and id, its
  options as a bitmask, its unit, its parameters (x, z and facing in their own
  columns for structures) and what an INSERT wraps, so that the build orders
  and the action counts come out exactly as from the document. Rows are in
  stream order, so a scan of the opening stops reading a game early.
- **Every pass over the parsed replays reads the tables, and only them**: the
  position check, first contact, the opening dataset and the measurements of
  actions per minute, reactions to idle units, the opening meta and the
  balance patches. Only `reason8 parse` writes them.
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
- A pass reads only the columns it needs. Decoding a whole parsed document
  took about a third of a second however little of it a pass needed (a
  document is about 17 MB of JSON, more than half of it MOVE commands); the
  build orders of the first 8 minutes of every game come out of the tables in
  seconds instead
  ([`replay-format.md`](../reference/replay-format.md#tables)): on two weeks
  of the slice the opening dataset takes 14 s in one process instead of 288 s
  with four, with the same rows.
- **A field the parser output has and the document does not keep, or one the
  parser does not emit yet, needs every replay parsed again**: 88.5 hours of
  compute for the 42,931 replays of the slice, measured from the parse index,
  and the replays themselves must be kept. This is accepted for one copy of
  about 64 GB instead of two (65 GB of JSON next to 50 GB of tables that held
  less). A new layout of the tables alone does not need the replays:
  `reason8.replays.tables.replay_documents` gives the documents back from the
  rows.
- The tables keep user ids and chat text, so they must not be published.
- The dataset gains placement (position relative to the start, metal spots,
  vents and other buildings), unit properties and per-snapshot state.
- The in-game side has to pass positions to BARb, which today chooses where to
  build itself
  ([ADR 0007](0007-ship-the-model-as-tables-in-a-barb-variant.md)).
- The order-only models stay as baselines to beat.
- Batching orders by dragging, which players use to save actions, is learned
  later, with the action budget of
  [ADR 0008](0008-play-under-human-like-limits.md).
