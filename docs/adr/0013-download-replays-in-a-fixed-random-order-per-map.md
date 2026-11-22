# 0013. Download replays in a fixed random order, maps taking turns

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

The first slice ([ADR 0006](0006-first-training-slice.md)) holds about 43k
games, but replays come from BAR's community-funded object storage, and bulk
downloads need the BAR infrastructure developers' agreement first. Until then
we download small samples, and the first one has to tell us what parsing costs
and where it fails across the slice.

The order matters because any run downloads a prefix of it:

- **Newest first** gives the current meta, but the newest 100 games all run on
  engine 2026.09.03 and a handful of game versions
  ([`dataset.md`](../dataset.md)), so they say nothing about older replays.
- **Evenly spaced in time** covers every engine, but a different `--limit`
  picks a different set, so growing the sample wastes earlier downloads.
- **Random** covers engines and versions in proportion to the slice, is a fair
  sample for statistics such as opening frequencies, and a larger sample can
  extend a smaller one.

Rosetta has 1.1k games against about 20k on each of the other two maps, so a
purely random sample would hold almost no Rosetta games.

## Decision

`reason8 download` walks the slice in a fixed pseudo-random order within each
map (SHA-256 of `"<seed>:<match_id>"`, seed 0), and the maps take turns, so
every prefix has about the same number of games per map. `--limit N` means "N
replays of this order on disk": files already there count, and replays that
are gone (404) are skipped and replaced by the next ones. `--order newest`
remains for when only the current game version matters.

The first sample is the first 100 of this order over the window 2026-05-23 ..
2026-11-22 (`--since 2026-05-23 --until 2026-11-22`).

## Consequences

- Samples are reproducible from the window and seed, and every larger sample
  contains the smaller ones; a newer dump only inserts its new games.
- Per map, a sample is uniform; across maps, Rosetta is over-represented
  compared to the slice. Statistics over the whole slice must weight by map.
- The engine and game version mix follows the slice, so older engines show up
  in the parser's failure counts.
- Revisit when training needs a different mix, e.g. only recent game versions
  under the version policy.
