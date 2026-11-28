# 0016. Download in a fixed order, keep the data in a private S3 bucket by day, run locally first

- **Status:** Accepted
- **Date:** 2026-11-26

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
the tables of the parsed replays, the match dumps, re-simulated state,
datasets and models. Parsing the whole slice takes 88.5 hours of compute
([`replay-format.md`](../reference/replay-format.md)), and re-simulating it
much longer
([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)). Work runs
in several git worktrees and will run on more machines, each needing the same
data without downloading it from BAR again. The whole slice is about 175 GB of
replays in some 43k files and about 64 GB of tables, while much of the work
needs only some days of the window (a week to try something, the newest games
for the current meta). Replays contain player names, which are personal data:
raw replays must never be published.

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
directory: `replays/`, `tables/`, `matches/`, `state/` (and `state-<name>` for
the state of a batch in a format of its own). The bucket is the shared cache;
a local data directory is a working copy that can be rebuilt from it.

- Replays and state files are kept in daily partitions by the day the match
  started, Hive style: `replays/date=YYYY-MM-DD/<name>.sdfz`,
  `state/date=YYYY-MM-DD/<name>.jsonl.gz`. The day is the first ten characters
  of the replay's file name, which every derived file keeps; a name that
  doesn't start with a date goes to `date=unknown`.
- The parsed replays are the Parquet tables
  ([ADR 0005](0005-learn-decisions-with-their-context.md)) of the `tables`
  area, with the same partitions and **one file per table and day**:
  `tables/date=YYYY-MM-DD/YYYY-MM-DD.commands.parquet`, and likewise for the
  other tables ([`replay-format.md`](../reference/replay-format.md#tables)). A
  file per replay would make about 43k small files per table, each with its
  own footer and too few rows for its row groups and dictionaries to pay off;
  a scan would spend its time opening files. A day holds a few hundred
  replays, a few hundred MB, so it is still the unit that `sync`, `--since`
  and `--until` select. A day's files are rewritten whole when replays of that
  day are parsed: the rows of the other replays are copied from the old files,
  and each file is written under a temporary name and renamed into place, the
  `games` table last. That table records each replay and the size of its
  replay file, so a replay is done when its day lists it with that size, and a
  day that a run left halfway is done again. Every file holds the layout
  version of the tables; a day of another version is not read until its
  replays are parsed again.
- The bookkeeping files stay at the top of their directory:
  `replays/manifest.parquet` (every match of the slice and what became of its
  download) and `tables/_index.jsonl` (every replay parsed, with its status,
  the error of one that failed, its sizes and the time it took). The match
  dumps in `matches/` aren't partitioned. One function
  (`reason8.paths.partition()`) knows the layout; the data directory and the
  bucket use the same relative paths, so copying between them needs no
  mapping.
- Commands that read a directory find the files in every partition; `sync`,
  `parse` and the passes over the parsed replays take `--since` and `--until`
  to work on some days only. Data files outside the partitions stop the
  commands that write or copy them, until they are moved into their
  partitions.
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

**Compute.** Run everything locally first. Bulk re-simulation can run on spot
instances in the bucket's region
([ADR 0020](0020-re-simulate-in-bulk-on-spot-instances.md)).

## Consequences

- Samples are reproducible from the window and seed, and every larger sample
  contains the smaller ones; a newer dump only inserts its new games.
- Per map, a sample is uniform; across maps, Rosetta is over-represented
  compared to the slice. Statistics over the whole slice must weight by map.
- The engine and game version mix follows the slice, so older engines show up
  in the parser's failure counts.
- Each replay is asked from BAR's servers once for all machines, and expired
  replays we already have stay available.
- A day of the window is one directory, a few hundred files, so a machine can
  pull, parse or build from some days without listing or copying the rest, and
  tools that read Hive partitions (Polars, DuckDB, Spark) see the date as a
  column. A replay's path follows from its name alone.
- A day's tables are a handful of files that a scan opens at once, and a pass
  over the opening of every game reads only the first row groups of each
  replay. Adding a replay to a day rewrites that day's files, a few hundred
  MB, which takes seconds next to parsing the replays.
- Storing the slice costs about $6 a month (about 240 GB of S3 Standard at
  $0.0245 per GB-month: 175 GB of replays and about 64 GB of tables) plus
  about $0.50 once for the uploads. Pulling it all to a machine outside AWS
  costs about $0.09 per GB above the free 100 GB a month; jobs running in
  eu-central-1 read it for free.
- Without versioning, an overwrite or a delete can't be undone: `sync` never
  deletes and overwrites a file only when its size differs, and only the
  maintainer manages the bucket itself.
- Contributors need AWS credentials from the maintainer to use the bucket;
  without them, everything still works from BAR's servers.
- The headless tools run unattended, in parallel, in their own write
  directories, so the same code runs on a local machine and on a cloud
  instance. The cost per game is measured by a trial batch before batches move
  to the cloud for good.
- Revisit when training needs a different mix (e.g. only recent game
  versions), when storage costs grow past the slice, when contributors without
  AWS access need the data, or when a published, anonymised dataset is needed.
