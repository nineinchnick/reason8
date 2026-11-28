# 0020. Re-simulate replays in bulk on spot instances fed by a queue

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

Re-simulating replays for their game state
([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)) is the
slowest step of building the training data. The local machines take about 13
hours for 3,000 games, and each new state format means playing the games
again. A headless engine needs about 6 GB of RAM and 1.5 cores
([`state-extraction.md`](../research/state-extraction.md)), so a machine with
32 GB plays about five games at once. A game needs nothing but its replay, the
engine, game version and map named in the replay's header, and a place for its
results, so games can be played anywhere, in any order.

[ADR 0016](0016-download-and-store-the-data.md) keeps the data in a private S3
bucket that mirrors the data directory. Replays hold player names, which are
personal data and must stay in that bucket. The jobs are batches that run for
hours and then nothing for days: nothing should keep running, or costing,
between them.

A trial of 60 games on one spot instance (an m7i.2xlarge: 8 threads on 4
cores, 32 GiB), all played without a failure:

| what                                        | measured                  |
| ------------------------------------------- | ------------------------- |
| spot price                                  | about $0.21 per hour      |
| a game of 20 minutes, five at once          | 347 s (median)            |
| games per instance and hour                 | 52 running, 37 with start |
| cost per game                               | $0.004 to $0.0055         |
| instance ready after launch                 | about a minute            |
| first game done, content from BAR's servers | after 20 minutes          |
| peak memory per engine                      | 6.2 GB                    |
| electricity per game on the local machines  | $0.0004 to $0.0008        |

The local electricity is an estimate from assumed power draw.

## Decision

Run bulk re-simulation on EC2 spot instances in the bucket's region, set up
from one CloudFormation template that `reason8 cloud up` deploys:

- **Work sharing by an SQS queue.** One message is one game: the replay's path
  in the bucket and the batch's settings. A worker on each instance takes a
  game per free engine and deletes its message only after the results are in
  the bucket. While a game runs, a heartbeat keeps its message hidden. A
  reclaimed spot instance needs no handling: its messages show up again for
  another worker. A game that fails three times goes to a dead-letter queue,
  with a failure record in the bucket.
- **Data in S3.** Replays are read from the bucket's `replays/` area and the
  results written to a state area of the bucket (`state/`, or `state-<name>`
  for a batch in another state format) with the layout of a local batch, so
  `reason8 sync pull` brings them home. The data never leaves the private
  bucket and the region, where reading it is free.
- **Setup by cloud-init, not an image.** The instance's user data installs
  git, 7z and uv, clones the repository at a pinned commit (one that origin
  has), runs `uv sync` and starts the worker as a systemd service. Engines,
  game versions and maps are fetched per replay as locally.
- **CloudFormation, not Terraform or Ansible.** Everything is one stack that
  is created and deleted with one command, with no state file or tool to
  install besides boto3, which the project already uses.
- **Cost guards.** Spot instances only, in a group capped at `--max-instances`
  (10 by default) that starts empty. `reason8 cloud run` raises its capacity
  no higher than the cap, the account's spot quota and the games can keep
  busy. A worker terminates its own instance through the group when the queue
  has been empty for a few minutes, and so does an instance whose setup or
  worker fails, so the group drains to 0 by itself. No inbound traffic, no SSH
  key; Session Manager for debugging.

## Consequences

- A batch of 3,000 games takes about four and a half hours on ten instances
  instead of 13 hours on the local machines, for about $10 instead of $1 to $2
  in electricity, by the estimates above; a trial batch replaces them with
  measured numbers (`reason8 cloud status` reports the instance hours and a
  rough cost).
- Between batches nothing runs and nothing costs but the queues, which are
  free when empty; the stack can also be deleted
  (`reason8 cloud down --delete`).
- Every instance downloads the engines, game versions and maps of its games
  from GitHub and BAR's CDN, as a local machine does once. A batch of many
  game versions spends minutes per instance on that; if it becomes a large
  share, a content cache in the bucket is the next step, not an image, which
  would go stale with every engine and game version.
- A game is played again when its instance is reclaimed, when its message is
  queued twice, or when the upload of its last table fails after the results
  were written. The results are the same, so this costs time, not correctness.
  A game reclaimed three times lands in the dead-letter queue like a failed
  one.
- The workers run the commit the stack names: code changes need a pushed
  commit and `reason8 cloud up` before the next batch.
- The workers' role can only read replays, write the state areas, failure
  records and logs, use the queue and terminate instances of its group.
- Revisit when a trial shows a different cost per game, when the quota or spot
  capacity of the region limits batches, or when another job (training,
  evaluation games) needs the cloud too.
