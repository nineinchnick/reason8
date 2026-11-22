# 0014. Keep the data in a private S3 bucket

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

Everything we work on lives in the git-ignored data directory: raw replays,
parsed replays, the match dumps and, later, recovered game state. Until now
there was one copy of it, on one workstation.

- Raw replays come from BAR's community-funded object storage, which should be
  asked for each file once ([`dataset.md`](../dataset.md)). Replays older than
  a year may also expire there, so a replay we lose may be gone for good.
- Parsing costs about 1.6 s of wall time per replay with 8 jobs, about 19 h
  for the whole slice ([`replay-format.md`](../replay-format.md)).
- Work already runs in several git worktrees and will run on more machines,
  and bulk jobs may move to the cloud ([ADR 0010](0010-run-locally-first.md)).
  Each needs the same data without downloading it from BAR again.
- Replays contain player names, which are personal data. Raw replays must
  never be published; only anonymised derived data may be, after asking BAR's
  maintainers.

The whole slice is about 175 GB of replays and 54 GB of parsed replays.

## Decision

Keep the data in a private S3 bucket (eu-central-1, all public access blocked,
encrypted at rest, no versioning) that mirrors the data directory: `replays/`,
`parsed/`, later `matches/` and `state/`. The bucket is the shared cache; a
local data directory is a working copy that can be rebuilt from it.

- `reason8 sync push|pull` copies files that are missing or differ in size,
  merges the bookkeeping files (`manifest.parquet`, `_index.jsonl`), and never
  deletes anything on either side.
- `reason8 download` looks for a missing replay in the bucket before asking
  BAR's servers, uploads what it gets from BAR, and records in the manifest
  where each replay came from. Requests to BAR keep their limits.
- S3 is opt-in (`REASON8_S3_URI` or `--s3-uri`), so a fresh clone works
  without AWS.
- Nothing in the bucket is public, and nothing derived from it is published
  without anonymising it first.

## Consequences

- Each replay is asked from BAR's servers once for all machines, and expired
  replays we already have stay available.
- The full slice costs about $6 a month to store (229 GB of S3 Standard at
  $0.0245 per GB-month) plus about $0.50 once for the uploads. Pulling it all
  to a machine outside AWS costs about $0.09 per GB above the free 100 GB a
  month; jobs running in eu-central-1 read it for free.
- Without versioning, an overwrite or a delete can't be undone: `sync` never
  deletes and overwrites a file only when its size differs, and only the
  maintainer manages the bucket itself.
- Contributors need AWS credentials from the maintainer to use it; without
  them, everything still works from BAR's servers.
- Revisit if storage costs grow past the slice, if contributors without AWS
  access need the data, or when a published, anonymised dataset is needed.
