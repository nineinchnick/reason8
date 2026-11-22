# Architecture decision records

Decisions that shape further development, one file each, numbered in the order
they were made. Each record says what was decided, why, and what follows from
it; the measurements and research behind it stay in the other docs and are
linked from the record.

To add one, copy [`template.md`](template.md) to `NNNN-short-title.md` with
the next number and add it to the list below with its status. Don't rewrite an
accepted record: when a decision changes, write a new record and mark the old
one "Superseded by NNNN".

- [0001. Record architecture decisions](0001-record-architecture-decisions.md):
  Accepted
- [0002. Recover game state by re-running replays headlessly](0002-recover-game-state-by-re-running-replays.md):
  Accepted
- [0003. Learn from human replays by imitation](0003-learn-from-human-replays-by-imitation.md):
  Accepted
- [0004. Build on BARb and replace its decisions layer by layer](0004-build-on-barb-and-replace-its-decisions-layer-by-layer.md):
  Accepted
- [0005. Start with team-game openings per start position](0005-start-with-team-game-openings.md):
  Accepted
- [0006. First training slice](0006-first-training-slice.md): Accepted
- [0007. Read build orders from replay commands](0007-read-build-orders-from-replay-commands.md):
  Accepted
- [0008. Copy no code from Apex](0008-copy-no-code-from-apex.md): Accepted
- [0009. Play under human-like limits](0009-play-under-human-like-limits.md):
  Accepted
- [0010. Run locally first, move bulk jobs to the cloud](0010-run-locally-first.md):
  Accepted
- [0011. Ship the model as generated tables in a BARb variant](0011-ship-the-model-as-tables-in-a-barb-variant.md):
  Accepted
- [0012. Keep the time window across balance patches](0012-keep-the-time-window-across-balance-patches.md):
  Accepted
- [0013. Download replays in a fixed random order, maps taking turns](0013-download-replays-in-a-fixed-random-order-per-map.md):
  Accepted
- [0014. Keep the data in a private S3 bucket](0014-keep-the-data-in-a-private-s3-bucket.md):
  Accepted
- [0016. License the project GPL-2.0-or-later](0016-license-the-project-gpl-2-0-or-later.md):
  Accepted
