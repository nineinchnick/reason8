# Context: what the game state adds to predicting the next build

Models of the opening are to decide from the game state as well as from the
orders before
([ADR 0005](../decisions/0005-learn-decisions-with-their-context.md)). Before
the whole slice is re-simulated, this document measures on a sample how much
each kind of state improves the prediction of the next build over the orders
alone. The table it is measured on is decided in
[ADR 0018](../decisions/0018-learn-from-orders-joined-with-the-state-before-them.md)
and described in [`context-dataset.md`](../reference/context-dataset.md).
Code: `reason8/context/`.

```sh
uv run reason8 context build                   # data/state -> data/datasets/context_v1/
uv run reason8 context check --games 20        # the join, below
uv run reason8 context measure                 # validation: compare
uv run reason8 context measure --split test    # the tables below
```

**The numbers below are preliminary**: 503 of the 3,000 games of the sample
were re-simulated when they were measured (2026-11-27), 411 of them in
training, 47 in validation and 45 in test. The test split is small and its
intervals are wide; the same commands give the numbers on the whole sample
once the batch is done.

## Summary

- **The join is exact.** On 20 games (28,895 rows) every row has the resources
  line of the second before its order with the same values, and the same units
  for the team and its allies as `standing_units()`. 99.4% of the structure
  orders that start one of the scored steps are built on their spot within the
  simulated 10 minutes, a median of 23 s later.
- **The state adds a little, clearly.** Gradient-boosted trees given the
  team's economy, its own units, its allies and the game time predict the next
  step right 51.4% of the time on test, against 48.1% with the order history
  alone: +3.2 points (2.6 to 3.8), and 0.135 nats less log-loss (0.123 to
  0.148). The economy and the team's own units carry most of it, +2.3 and +3.0
  points, and they overlap. The allies and the game time add about a point
  each, and wind nothing.
- **More on Supreme Isthmus**: +3.9 points there, +2.8 on All That Glitters,
  +2.8 on Rosetta (6 test games).
- **Trees on 411 games match the n-gram on 33,657.** With the order history
  alone the trees reach 48.1% top-1 and 1.698 nats; the saved 4-gram, trained
  on 80 times as many games, 48.3% and 1.759. The same 4-gram trained on the
  411 games gets 44.1% and 2.187: the n-gram needs the data, the trees use it
  better.
- **The time since the previous order is not context.** On its own it adds 5.1
  points, but it says how the order being predicted was clicked, not what the
  game looked like; it is kept out of the model with all context (below).

## The sample

3,000 games of the slice, drawn with a fixed seed from the `ok` games of
`openings_v2`: 1,350 Supreme Isthmus, 1,350 All That Glitters and 300 Rosetta,
in the dataset's train, validation and test splits
(`data/logs/context-sample.parquet`). Each is re-simulated for its first 10
minutes (`reason8 headless batch --max-frame 18000`, 8 engines at once, about
150 games an hour on one machine), with resources every second (state format
5). The decision table takes the rows of `openings_v2` of every game whose
state is there, so it grows as the batch goes on, and the split of a game
never changes.

## The join

Every row of the table gets the state the game wrote at the end of the frame
before the order: the last resources line (at most a second old) and the units
standing after that frame's events, of the player's team and, summed, of its
allies. `reason8 context check` compares each row of some games with the state
tables directly.

On 20 games of the table, 28,895 rows (`reason8 context check --games 20`):

| check                                                        | rows that differ |
| ------------------------------------------------------------ | ---------------- |
| the resources line is the one of the second before the order | 0                |
| its resources and wind equal the table's                     | 0                |
| the team's units by type equal `standing_units()`            | 0                |
| the allies' units by type equal `standing_units()`           | 0                |

In 2,113 rows the team has a unit of a type outside the table's 79 types and
the commander, counted as `other`. The tests (`tests/context/`) check the same
on made-up games, unit given to an ally and unit ids used again included.

What players ordered shows up afterwards:

| orders                                      | count  | built on the spot | median delay | p90 delay |
| ------------------------------------------- | ------ | ----------------- | ------------ | --------- |
| every structure order                       | 23,861 | 62.3%             | 59 s         | 283 s     |
| orders that start one of the first 30 steps | 5,321  | 99.4%             | 23 s         | 126 s     |

A structure order is matched with a unit of the same type that the player's
team started within 16 map units of the order's spot, after the order and
within the simulated 10 minutes. Most of the orders never built are the later
parts of long queues of wind turbines, which the 10 minutes do not reach, or
orders replaced later. From factories, players ordered 12,651 units of their
openings and their teams made 9,304 units of those types from the first such
order to minute 10 (74%): quota and repeat orders ask for more than gets
built.

## How it is measured

The protocol is [ADR 0013](../decisions/0013-evaluate-on-held-out-games.md) on
the table's rows: every model predicts the unit of the next step of an
opening, the first 30 steps of every opening of the held-out games are scored,
and the intervals are 95% from resampling whole games. Differences are paired:
the same games are drawn for both models.

The models:

n-grams on the table's games
: The faction trigram and the chosen baseline, the 4-gram with faction, map
  and position (`reason8.models.ngram`), trained on the openings of the
  table's training games only.

the saved n-gram
: The same 4-gram as saved by `reason8 baseline`
  (`data/models/ngram_v2.json`), trained on the whole training split of
  `openings_v2`: 33,657 games, which include the table's training games but
  none of its validation or test games. Against the n-gram trained on the
  table it shows what the smaller training set costs.

trees
: Gradient-boosted trees (XGBoost 3.4), one class per unit seen at least 20
  times in training and one class for the rest, its probability split between
  them by their training counts. Depth 6, learning rate 0.15, 64 bins, at most
  400 rounds, stopped when the validation log-loss has not improved for 20
  rounds.

The trees see the **order history** in every variant: faction, map, position,
its role, the step number, the number of orders so far, the units of the three
previous steps (as the 4-gram does), and how many units of each type the
player has ordered so far. Then each **context group** of the table is added
on its own, and all of them together:

time
: The game time of the order.

economy
: The team's metal and energy: stored, storage, income and expense.

wind
: The current wind, and the map's wind range.

own units
: The team's units of each of 79 types, the commander and the rest, finished
  and under construction.

allies
: The allies' economy and units, summed.

### The pace of the orders is not context

A first version had the time since the player's previous order in the time
group, and it raised top-1 by six points on its own, more than everything else
together. It does not come from the game:

- Orders of one frame are given at once, and an order that repeats the unit of
  the order before it at most 0.2 s (6 frames) later is part of its step
  ([ADR 0013](../decisions/0013-evaluate-on-held-out-games.md)). So a step
  that follows an order within that time is a different unit, and the time
  since the order before gives that away. The table takes the time since the
  player's last order in an earlier frame, which hides the orders of one
  frame, but not the quick clicks: 1.5% of the steps after the first follow
  the previous order by 1 to 6 frames, and 0.2% of them repeat the unit of the
  step before, against 34% of all steps.
- The time still describes the order being predicted. A step that follows the
  previous order by a quarter of a second to 3 seconds repeats the unit of the
  step before 50 to 57% of the time: a run of the same building with short
  pauses, placed one by one. After 10 seconds, 15% do.

Before quick runs of clicks were merged into one step, the pace added 7.7
points of top-1 on test, most of it from those runs: a step 0.05 to 0.2 s
after the one before repeated its unit 94% of the time. With them merged it
adds 5.1 points (4.4 to 5.7), 5.4 on validation: about two thirds of the
effect remains, from the two reasons above.

The table keeps that time (`since_previous_s`, the `pace` group) and the
measurement reports it, but the model with all context leaves it out: the bot
will not click like that, and a gain from it would not be a gain from the
state.

## Results

On the test split: 45 games, 716 openings, 18,943 steps. The trees are
compared with the trees on the order history alone, with paired intervals.

| model                                     | trained on           | top-1             | top-3             | log-loss            | top-1 vs history    | log-loss vs history       |
| ----------------------------------------- | -------------------- | ----------------- | ----------------- | ------------------- | ------------------- | ------------------------- |
| n-gram: trigram, faction                  | 411 table games      | 42.8% (41.8–43.8) | 69.7% (68.4–70.8) | 2.036 (1.981–2.092) | -5.3 (-6.1 to -4.6) | +0.337 (+0.313 to +0.362) |
| n-gram: 4-gram, faction, map and position | 411 table games      | 44.1% (43.2–45.0) | 69.9% (69.0–70.9) | 2.187 (2.121–2.254) | -4.1 (-4.7 to -3.4) | +0.488 (+0.459 to +0.514) |
| the same 4-gram, saved                    | 33,657 dataset games | 48.3% (47.3–49.3) | 75.0% (74.0–76.0) | 1.759 (1.715–1.802) | +0.1 (-0.5 to +0.7) | +0.061 (+0.038 to +0.080) |
| trees: history                            | 411 table games      | 48.1% (47.2–49.1) | 75.6% (74.7–76.5) | 1.698 (1.654–1.748) |                     |                           |
| trees: history + time                     | 411 table games      | 49.5% (48.4–50.7) | 77.2% (76.1–78.2) | 1.638 (1.589–1.690) | +1.4 (+0.9 to +1.9) | -0.060 (-0.068 to -0.053) |
| trees: history + economy                  | 411 table games      | 50.4% (49.4–51.4) | 78.6% (77.4–79.7) | 1.593 (1.545–1.645) | +2.3 (+1.8 to +2.8) | -0.105 (-0.116 to -0.095) |
| trees: history + wind                     | 411 table games      | 48.4% (47.5–49.3) | 75.9% (74.8–77.0) | 1.692 (1.646–1.742) | +0.2 (-0.2 to +0.7) | -0.006 (-0.013 to +0.000) |
| trees: history + own units                | 411 table games      | 51.1% (50.2–52.0) | 78.7% (77.7–79.7) | 1.585 (1.538–1.638) | +3.0 (+2.4 to +3.6) | -0.113 (-0.125 to -0.102) |
| trees: history + allies                   | 411 table games      | 49.5% (48.5–50.5) | 77.0% (75.9–78.1) | 1.643 (1.594–1.696) | +1.3 (+0.8 to +1.9) | -0.055 (-0.064 to -0.047) |
| trees: history + all context              | 411 table games      | 51.4% (50.3–52.4) | 79.4% (78.3–80.3) | 1.563 (1.514–1.615) | +3.2 (+2.6 to +3.8) | -0.135 (-0.148 to -0.123) |
| trees: history + pace (not context)       | 411 table games      | 53.2% (52.2–54.2) | 79.6% (78.5–80.6) | 1.501 (1.450–1.555) | +5.1 (+4.4 to +5.7) | -0.198 (-0.209 to -0.187) |

On validation (47 games, 19,386 steps) the picture is the same: 48.6% top-1
and 1.685 nats with the history, 52.0% and 1.543 with all context (+3.4, 2.8
to 4.0); economy +2.8, own units +2.9, allies +0.8, time +1.3, wind -0.1, pace
+5.4; the saved 4-gram 48.5% and 1.756.

### By map

All context against the history alone, on test:

| map                      | games | steps | history top-1     | all context top-1 | top-1 vs history    | log-loss vs history       |
| ------------------------ | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------------- |
| All That Glitters v2.2.3 | 21    | 9,360 | 49.6% (48.6–50.5) | 52.3% (51.1–53.6) | +2.8 (+1.8 to +3.6) | -0.124 (-0.139 to -0.107) |
| Rosetta 1.4.4            | 6     | 2,423 | 48.7% (47.4–50.0) | 51.5% (49.6–53.5) | +2.8 (+1.4 to +4.0) | -0.114 (-0.124 to -0.104) |
| Supreme Isthmus v2.1     | 18    | 7,160 | 46.1% (44.3–47.8) | 50.0% (47.9–52.0) | +3.9 (+3.1 to +4.7) | -0.158 (-0.180 to -0.137) |

Each group on its own, top-1 against the history, on test:

| group     | All That Glitters   | Rosetta             | Supreme Isthmus     |
| --------- | ------------------- | ------------------- | ------------------- |
| time      | +1.8 (+1.1 to +2.5) | +0.0 (-0.7 to +0.9) | +1.2 (+0.2 to +2.1) |
| economy   | +2.0 (+1.4 to +2.7) | +1.7 (+0.2 to +3.1) | +2.8 (+2.0 to +3.6) |
| wind      | +0.5 (-0.2 to +1.3) | -0.7 (-1.4 to -0.0) | +0.2 (-0.6 to +1.0) |
| own units | +2.7 (+1.8 to +3.5) | +1.4 (+0.5 to +2.3) | +4.0 (+3.3 to +4.6) |
| allies    | +1.3 (+0.5 to +2.0) | +0.0 (-1.3 to +1.3) | +1.8 (+0.9 to +2.7) |

Rosetta has 6 test games: its intervals, from resampling those 6, are too
narrow to trust.

### What the trees use

The share of the total gain of the splits of the model with all context:

| group     | columns | share of gain |
| --------- | ------- | ------------- |
| history   | 90      | 81.3%         |
| time      | 1       | 1.4%          |
| economy   | 8       | 5.7%          |
| wind      | 3       | 0.7%          |
| own units | 162     | 5.4%          |
| allies    | 170     | 5.5%          |

The previous step alone has 43.3% of the gain, the two before it 12.3% and
7.5%, then faction, position and its role. The first state columns are the
game time (1.4%), the team's stored energy, metal expense and stored metal
(about 1% each). Which factories the player has ordered so far (`ordered_ap`,
`ordered_vp`, `ordered_alab`) are among the history columns used most.

### Reading it

- The state presumably helps where the history leaves the choice open, such as
  what to build when the energy runs short or the factory is up. That is a
  couple of points of the steps: most steps continue a run of the same
  building or follow the meta of the position, and the history has those.
- The economy and the units the team has say much the same: what a team has
  built is most of what its income is. Together they add about as much as
  either alone.
- Wind adds nothing measurable. A likely reason: a player's first steps
  already show whether they build wind turbines in this game, and the history
  carries that from there. Not checked here.
- The allies add about a point, the most on Supreme Isthmus.
- Context is measured with trees trained on 411 games. With more games the
  history-only trees get better too; whether the gap from the state grows or
  shrinks is what the whole sample will show.

## What it means for the first model

For the first learned model (the next step after the n-gram tables):

- **A tree model is worth it before any state.** On 411 games it predicts as
  well as the 4-gram does on all 33,657, with a better log-loss. Trained on
  the whole opening dataset, which needs no re-simulation, it is the first
  candidate.
- **Give it the team's economy and own units.** They are the state that helps,
  +2.3 and +3.0 points and overlapping (all context together +3.2), and both
  are close to what BARb's scripts already see: the team's resources and its
  unit counts
  ([ADR 0007](../decisions/0007-ship-the-model-as-tables-in-a-barb-variant.md)).
  Neither needs the current wind or the allies, which only our build of the
  library can read.
- **Leave the wind out**, and the allies until the bigger sample says they
  matter.
- These are development numbers
  ([ADR 0013](../decisions/0013-evaluate-on-held-out-games.md)). A model earns
  its place by the in-game measures
  ([ADR 0003](../decisions/0003-define-success-as-in-game-measures.md)), and a
  couple of points of next-step accuracy may not change which openings the bot
  plays.

## Reproducing

The batch writes its state next to the replays' date partitions in
`data/state/`; when it is done, or at any point before:

```sh
uv run reason8 context build
uv run reason8 context check --games 20
uv run reason8 context measure                 # validation
uv run reason8 context measure --split test --out data/context-check/test.md
```

The build reads every game whose state is there and takes about 30 s for 500
games. The measurement fits eight tree models on all the steps of the training
games, with 6 threads (`--threads`): on 503 games, 411 of them in training
(230,000 steps), it took 55 minutes and at most 5.1 GB of memory per split.
Both grow about linearly with the games: on the whole sample expect five to
six hours and 30 GB per split, or more threads once the machine is free.
