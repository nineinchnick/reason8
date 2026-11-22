# 0012. Keep the time window across balance patches

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

BAR ships a new game version about every day and a balance patch every few
weeks: 13 in the last 12 months, 5 of which touch what players order in the
first minutes ([`game-versions.md`](../game-versions.md)). Openings learned
from old versions could be wrong today. The options were a hard cutoff at the
last patch, the version as a model input, or weighting recent games more.

What we measured on 94 Supreme Isthmus games (1,504 openings) from before
Season 3 to now:

- No shift in first factory, opening shape or first orders stands clear of
  sampling noise, over 12 months and four opening-changing patches. The start
  spot moves the first factory several times more than any patch.
- A frequency model trained on 12-month-old games predicts today's orders 0.3
  points worse than one trained on as many current games (interval −0.9 to
  +0.4); adding the older games to the current ones gains 0.9 points.
- A cutoff at the last opening-changing patch keeps 30% of the Isthmus slice
  and 23% of Rosetta's 1,138 games.
- No unit was renamed in 12 months; one unit used in openings was removed.
  Build command ids change between versions; names don't.
- Two games of one version can differ in balance: 67 of the 94 ranked games
  had a balance-changing lobby option on.

The sample is small. It would miss a shift of a few points in shares or of
under a point in accuracy.

## Decision

Train across balance patches. The dataset keeps the whole time window of the
slice ([ADR 0006](0006-first-training-slice.md)): no cutoff at a patch, no
recency weights and no version input for the first models.

Record what would be needed to change that, per game: the game version, its
build number, the opening era (the first build of the last patch that changes
openings, from `BALANCE_PATCHES`) and the balance-changing lobby options that
are on. Report model accuracy per opening era.

Supporting rules:

- Versions are ordered and cut by build number, never by date. Games whose
  version is not a release are left out.
- Games with custom unit tweaks or stat multipliers are left out. Other
  balance options are kept and recorded.
- A unit is identified by its name. The vocabulary is the unit names of the
  newest build in the dataset; renamed units are mapped (`UNIT_RENAMES`); an
  opening that orders a unit that no longer exists is dropped whole.
- Retrain monthly on the moved window. After a patch that changes openings,
  measure the current model on games after the patch; cut the training data at
  the patch (`select_matches(min_build=...)`) only if accuracy there is 2
  points or more lower than before it.
- A model is saved with the builds and unit names it was trained on
  (`TrainedOn`). Loading it warns when the game is a month or an
  opening-changing patch ahead of the training data, and refuses when the
  model can order a unit the game doesn't have or the game is more than 12
  months of builds away.

## Consequences

- The slice keeps all of its games, and Rosetta stays trainable.
- The dataset builder has to read lobby options from the replays (the match
  dumps don't have them) and add the version columns.
- `BALANCE_PATCHES` is kept by hand: someone adds each patch and judges
  whether it changes openings.
- Because the era is a column, a cutoff, weights or a version input can be
  tried later without rebuilding the dataset.
- Legion's own patches are not tracked; with 45 Legion openings we know
  nothing about them.
- Revisit when the measurement repeated on the full dataset shows older eras
  costing more than a point or two; when a real model turns out more sensitive
  to old games than the frequency baseline; or when a patch renames or removes
  units that are common in openings.
