# 0010. Run locally first, move bulk jobs to the cloud

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

Training and headless simulation can run on a single workstation, but bulk
jobs (re-running thousands of replays, large evaluation runs) can outgrow it.
A headless engine needs 5–6 GB of RAM, so RAM rather than cores limits how
many run at once ([`state-extraction.md`](../state-extraction.md)).

## Decision

Run everything locally first. Move bulk jobs to a cloud cluster of
containerised headless engines only when local machines aren't enough, based
on measured cost.

## Consequences

- The headless tools must run unattended, in parallel, in their own write
  directories, so they can later be containerised.
- We need cost measurements per 1,000 replays and per evaluation run before
  moving anything to the cloud.
