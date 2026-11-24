# Decisions

Decisions that shape further development, one file each, from the most
fundamental to the most specific
([ADR 0001](0001-record-decisions-as-adrs.md)). Each record says what is
decided, why, and what follows from it; the measurements and research behind
it stay in the other docs and are linked from the record.

Each record states the decision as it holds today. To change a decision,
rewrite its record and say in the commit what changed and why. To add one,
copy [`template.md`](template.md) to `NNNN-short-title.md` with the next free
number and add it to the list below, which is in the same order.

- [0001. Record decisions as ADRs](0001-record-decisions-as-adrs.md)
- [0002. License the project GPL-2.0-or-later](0002-license-the-project-gpl-2-0-or-later.md)
- [0003. Define success as in-game measures](0003-define-success-as-in-game-measures.md)
- [0004. Learn from human replays by imitation](0004-learn-from-human-replays-by-imitation.md)
- [0005. Learn decisions with their context](0005-learn-decisions-with-their-context.md)
- [0006. Build on BARb and replace its decisions layer by layer](0006-build-on-barb-and-replace-its-decisions-layer-by-layer.md)
- [0007. Ship the model as generated tables in a BARb variant](0007-ship-the-model-as-tables-in-a-barb-variant.md)
- [0008. Play under human-like limits](0008-play-under-human-like-limits.md)
- [0009. Start with team-game openings per start position](0009-start-with-team-game-openings.md)
- [0010. Re-simulate replays headlessly for game state](0010-re-simulate-replays-headlessly-for-game-state.md)
- [0011. Take positions from BAR's map metadata](0011-take-positions-from-the-map-metadata.md)
- [0012. End openings at first contact and split games by match id](0012-end-openings-at-first-contact.md)
- [0013. Evaluate on held-out games, one step per decision](0013-evaluate-on-held-out-games.md)
- [0014. First training slice](0014-first-training-slice.md)
- [0015. Train across balance patches](0015-train-across-balance-patches.md)
- [0016. Download in a fixed order, keep the data in a private S3 bucket by day, run locally first](0016-download-and-store-the-data.md)
- [0017. Keep openings with automation widgets and flag them](0017-keep-openings-with-automation-widgets-flagged.md)
