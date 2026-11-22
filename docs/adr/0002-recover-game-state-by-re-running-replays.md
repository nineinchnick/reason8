# 0002. Recover game state by re-running replays headlessly

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

Replays record player commands, not the game state. From milestone 2 the model
needs to know what the game looked like (units, positions, resources) at each
moment. The only source of that is the engine itself: play the replay again
and write the state down while it runs.

[`state-extraction.md`](../state-extraction.md) measured this on engine
2026.09.03 and on older engines:

- The re-run is exact: no desyncs, the recorded winner and length, and
  byte-identical output across runs.
- It needs the exact engine and game version of each replay. A wrong engine
  refuses to load; a wrong game version loads and silently desyncs.
- Cost: a 1v1 replay takes about 40 s of one core, an 8v8 replay 7 to 11
  minutes; 5–6 GB of RAM per engine, so RAM limits how many run at once.

## Decision

Use game state from milestone 2 on, recovered by re-running each replay in
`spring-headless` with a spectator widget that writes snapshots and events
(`tools/headless/`).

- **1v1:** re-run whole games.
- **8v8 (team openings):** stop at minute 10 unless whole games are needed;
  run bulk whole-game jobs on a cloud cluster.

Every run fetches the engine, game version and map named in the replay's
header, uses one engine per replay with one worker thread, its own write dir
and a free port, and is rejected on any desync warning, non-zero exit code or
timeout.

## Consequences

- We have to keep several engines and many game versions on disk (about 0.4 GB
  for the top three engines of the first slice, a few GB of game versions).
- Throughput is bounded by RAM, not cores; a bulk runner and a cloud cost
  estimate are still needed.
- The state is the spectator's full view. Line of sight per player must be
  recorded before the state is used for training.
- Revisit if a replay stops re-simulating exactly, or if per-replay cost makes
  whole 8v8 games too expensive even in the cloud.
