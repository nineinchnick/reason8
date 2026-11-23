# 0016. Download in a fixed order, keep the data in a private S3 bucket, run locally first

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

The first slice ([ADR 0014](0014-first-training-slice.md)) holds about 43k
games. Their replays come from BAR's community-funded object storage, which
should be asked for each file once, and bulk downloads need the BAR
infrastructure developers' agreement first
([`dataset.md`](../reference/dataset.md)). Replays older than a year may
expire there, so a replay we lose may be gone for good.

The order of the downloads matters because any run downloads a prefix of it:

- **Newest first** gives the current meta, but the newest 100 games all run on
  engine 2026.09.03 and a handful of game versions, so they say nothing about
  older replays.
- **Evenly spaced in time** covers every engine, but a different `--limit`
  picks a different set, so growing the sample wastes earlier downloads.
- **Random** covers engines and versions in proportion to the slice, is a fair
  sample for statistics such as opening frequencies, and a larger sample can
  extend a smaller one. Rosetta has 1.1k games against about 20k on each of
  the other two maps, so a purely random sample would hold almost no Rosetta
  games.

Everything we work on lives in the git-ignored data directory: raw replays,
parsed replays, the match dumps, re-simulated state, datasets and models.
Parsing the whole slice takes about 19 hours with 8 jobs
([`replay-format.md`](../reference/replay-format.md)), and re-simulating it
much longer
([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)). Work runs
in several git worktrees and will run on more machines, each needing the same
data without downloading it from BAR again. The whole slice is about 175 GB of
replays and 70 GB of parsed replays. Replays contain player names, which are
personal data: raw replays must never be published.

A headless engine needs 5 to 6 GB of RAM, so RAM rather than cores limits how
many run at once ([`state-extraction.md`](../research/state-extraction.md)).
Training and simulation fit a single workstation for now; bulk jobs
(re-running thousands of replays, large evaluation runs) may outgrow it.

## Decision

**Download order.** `reason8 download` walks the slice in a fixed
pseudo-random order within each map (SHA-256 of `"<seed>:<match_id>"`, seed
0), and the maps take turns, so every prefix has about the same number of
games per map. `--limit N` means "N replays of this order on disk": files
already there count, and replays that are gone (404) are skipped and replaced
by the next ones. `--order newest` remains for when only the current game
version matters. The window is pinned to 2026-05-23 .. 2026-11-22
(`--since 2026-05-23 --until 2026-11-22`).

**Storage.** Keep the data in a private S3 bucket (eu-central-1, all public
access blocked, encrypted at rest, no versioning) that mirrors the data
directory: `replays/`, `parsed/`, `matches/`, later `state/`. The bucket is
the shared cache; a local data directory is a working copy that can be rebuilt
from it.

- `reason8 sync push|pull` copies files that are missing or differ in size,
  merges the bookkeeping files (`manifest.parquet`, `_index.jsonl`), and never
  deletes anything on either side.
- `reason8 download` looks for a missing replay in the bucket before asking
  BAR's servers, uploads what it gets from BAR, and records in the manifest
  where each replay came from. Requests to BAR keep their limits: one
  connection, about one request a second, and a stop on 429 or 503.
- S3 is opt-in (`REASON8_S3_URI` or `--s3-uri`), so a fresh clone works
  without AWS.
- Nothing in the bucket is public, and nothing derived from it is published
  without anonymising it first.

**Compute.** Run everything locally first. Move bulk jobs to a cloud cluster
of containerised headless engines only when local machines aren't enough,
based on measured cost.

## Consequences

- Samples are reproducible from the window and seed, and every larger sample
  contains the smaller ones; a newer dump only inserts its new games.
- Per map, a sample is uniform; across maps, Rosetta is over-represented
  compared to the slice. Statistics over the whole slice must weight by map.
- The engine and game version mix follows the slice, so older engines show up
  in the parser's failure counts.
- Each replay is asked from BAR's servers once for all machines, and expired
  replays we already have stay available.
- Storing the slice costs about $6 a month (245 GB of S3 Standard at $0.0245
  per GB-month) plus about $0.50 once for the uploads. Pulling it all to a
  machine outside AWS costs about $0.09 per GB above the free 100 GB a month;
  jobs running in eu-central-1 read it for free.
- Without versioning, an overwrite or a delete can't be undone: `sync` never
  deletes and overwrites a file only when its size differs, and only the
  maintainer manages the bucket itself.
- Contributors need AWS credentials from the maintainer to use the bucket;
  without them, everything still works from BAR's servers.
- The headless tools run unattended, in parallel, in their own write
  directories, so they can be containerised later. Cost per 1,000 replays and
  per evaluation run is measured before anything moves to the cloud.
- Revisit when training needs a different mix (e.g. only recent game
  versions), when storage costs grow past the slice, when contributors without
  AWS access need the data, or when a published, anonymised dataset is needed.
