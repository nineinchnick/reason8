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
  for the team and its allies as `standing_units()`. 99.5% of the structure
  orders that start one of the scored steps are built on their spot within the
  simulated 10 minutes, a median of 22 s later.
- **The state adds a little, clearly.** Gradient-boosted trees given the
  team's economy, its own units, its allies and the game time predict the next
  step right 54.0% of the time on test, against 51.3% with the order history
  alone: +2.7 points (2.2 to 3.3), and 0.124 nats less log-loss (0.113 to
  0.136). The economy and the team's own units carry most of it, about +2
  points each, and they overlap. The allies add about a point, game time 1.4,
  and wind nothing.
- **More on Supreme Isthmus**: +3.5 points there, +2.2 on All That Glitters,
  +2.6 on Rosetta (6 test games).
- **Trees on 411 games match the n-gram on 33,657.** With the order history
  alone the trees reach 51.3% top-1 and 1.589 nats; the saved 4-gram, trained
  on 80 times as many games, 51.0% and 1.649. The same 4-gram trained on the
  411 games gets 47.4% and 2.031: the n-gram needs the data, the trees use it
  better.
- **The time since the previous order is not context.** On its own it adds 7.7
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
| orders that start one of the first 30 steps | 4,863  | 99.5%             | 22 s         | 116 s     |

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
: Gradient-boosted trees (XGBoost 3.4, `xgboost-cpu`), one class per unit seen
  at least 20 times in training and one class for the rest, its probability
  split between them by their training counts. Depth 6, learning rate 0.15, 64
  bins, at most 400 rounds, stopped when the validation log-loss has not
  improved for 20 rounds.

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

- Orders of one frame are given at once. An order in the frame of the step
  before it starts a new step only when its unit differs from the order before
  (otherwise it is part of the drag), so "0 seconds since the previous order"
  says "a different unit". On 100 games, 8% of the steps after the first were
  in the frame of the order before, and none of them repeated the previous
  step's unit, against 43% of all steps.
- Taking the time since the last order of an earlier frame instead removes
  that, but the time still describes the order being predicted. A step that
  follows the one before by 0.05 to 0.2 seconds repeats its unit 94% of the
  time: one run of quick clicks of the same building, which the protocol
  counts as several steps. After 10 to 30 seconds, 17% do.

The table keeps that time (`since_previous_s`, the `pace` group) and the
measurement reports it, but the model with all context leaves it out: the bot
will not click like that, and a gain from it would not be a gain from the
state. Merging quick runs of the same unit into one step would change the
protocol of ADR 0013 and every baseline, and is not done here.

## Results

On the test split: 45 games, 716 openings, 19,933 steps. The trees are
compared with the trees on the order history alone, with paired intervals.

| model                                     | trained on           | top-1             | top-3             | log-loss            | top-1 vs history    | log-loss vs history       |
| ----------------------------------------- | -------------------- | ----------------- | ----------------- | ------------------- | ------------------- | ------------------------- |
| n-gram: trigram, faction                  | 411 table games      | 46.7% (45.6–47.7) | 73.5% (72.4–74.6) | 1.901 (1.851–1.957) | -4.6 (-5.2 to -4.0) | +0.311 (+0.290 to +0.333) |
| n-gram: 4-gram, faction, map and position | 411 table games      | 47.4% (46.6–48.3) | 74.1% (73.1–75.0) | 2.031 (1.970–2.095) | -3.9 (-4.4 to -3.3) | +0.441 (+0.415 to +0.468) |
| the same 4-gram, saved                    | 33,657 dataset games | 51.0% (50.0–52.0) | 78.2% (77.2–79.2) | 1.649 (1.608–1.692) | -0.3 (-0.8 to +0.3) | +0.059 (+0.038 to +0.076) |
| trees: history                            | 411 table games      | 51.3% (50.3–52.2) | 79.0% (77.9–80.1) | 1.589 (1.548–1.634) |                     |                           |
| trees: history + time                     | 411 table games      | 52.7% (51.7–53.6) | 80.6% (79.6–81.6) | 1.532 (1.488–1.578) | +1.4 (+1.0 to +1.9) | -0.058 (-0.065 to -0.051) |
| trees: history + economy                  | 411 table games      | 53.3% (52.2–54.5) | 81.5% (80.4–82.5) | 1.491 (1.445–1.541) | +2.1 (+1.4 to +2.7) | -0.099 (-0.111 to -0.086) |
| trees: history + wind                     | 411 table games      | 51.6% (50.7–52.6) | 79.1% (77.9–80.1) | 1.582 (1.539–1.627) | +0.4 (-0.1 to +0.7) | -0.008 (-0.014 to -0.003) |
| trees: history + own units                | 411 table games      | 53.6% (52.7–54.6) | 81.6% (80.6–82.6) | 1.478 (1.435–1.525) | +2.4 (+1.8 to +2.9) | -0.111 (-0.123 to -0.101) |
| trees: history + allies                   | 411 table games      | 52.2% (51.2–53.1) | 80.1% (79.1–81.2) | 1.542 (1.497–1.590) | +0.9 (+0.4 to +1.4) | -0.047 (-0.056 to -0.039) |
| trees: history + all context              | 411 table games      | 54.0% (52.9–55.1) | 82.4% (81.3–83.4) | 1.465 (1.422–1.514) | +2.7 (+2.2 to +3.3) | -0.124 (-0.136 to -0.113) |
| trees: history + pace (not context)       | 411 table games      | 59.0% (57.9–60.2) | 82.8% (81.8–83.8) | 1.310 (1.262–1.359) | +7.7 (+7.1 to +8.5) | -0.280 (-0.295 to -0.267) |

On validation (47 games, 20,461 steps) the picture is the same: 52.1% top-1
and 1.574 nats with the history, 54.8% and 1.443 with all context (+2.8, 2.2
to 3.3); economy +2.0, own units +2.5, allies +0.9, time +1.2, wind +0.2; the
saved 4-gram 52.0% and 1.640.

### By map

All context against the history alone, on test:

| map                      | games | steps | history top-1     | all context top-1 | top-1 vs history    | log-loss vs history       |
| ------------------------ | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------------- |
| All That Glitters v2.2.3 | 21    | 9,722 | 52.6% (51.8–53.6) | 54.9% (53.6–56.4) | +2.2 (+1.5 to +3.0) | -0.121 (-0.136 to -0.102) |
| Rosetta 1.4.4            | 6     | 2,576 | 53.4% (50.9–56.5) | 56.0% (53.2–59.8) | +2.6 (+1.7 to +3.4) | -0.090 (-0.099 to -0.082) |
| Supreme Isthmus v2.1     | 18    | 7,635 | 48.8% (47.6–50.2) | 52.3% (50.6–54.0) | +3.5 (+2.6 to +4.3) | -0.140 (-0.157 to -0.122) |

Each group on its own, top-1 against the history, on test:

| group     | All That Glitters   | Rosetta             | Supreme Isthmus     |
| --------- | ------------------- | ------------------- | ------------------- |
| time      | +1.5 (+0.9 to +2.2) | -0.6 (-1.2 to +0.0) | +1.9 (+1.3 to +2.4) |
| economy   | +1.6 (+0.6 to +2.5) | +1.7 (+0.3 to +3.2) | +2.8 (+1.7 to +3.6) |
| wind      | +0.3 (-0.4 to +0.9) | -0.0 (-0.7 to +0.6) | +0.6 (-0.0 to +1.1) |
| own units | +1.7 (+1.0 to +2.4) | +1.5 (+1.3 to +1.7) | +3.5 (+2.8 to +4.2) |
| allies    | +0.6 (-0.1 to +1.4) | +0.2 (-0.8 to +0.8) | +1.5 (+0.7 to +2.2) |

Rosetta has 6 test games: its intervals, from resampling those 6, are too
narrow to trust.

### What the trees use

The share of the total gain of the splits of the model with all context:

| group     | columns | share of gain |
| --------- | ------- | ------------- |
| history   | 90      | 84.2%         |
| time      | 1       | 1.2%          |
| economy   | 8       | 4.8%          |
| wind      | 3       | 0.6%          |
| own units | 162     | 4.6%          |
| allies    | 170     | 4.6%          |

The previous step alone has 48.8% of the gain, the two before it 13.2% and
6.8%, then faction, position and its role. The first state columns are the
game time (1.2%), the team's metal expense, stored energy and stored metal
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
  about +2 points each and overlapping (all context together +2.7), and both
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
(250,000 steps), it took an hour and at most 5.6 GB of memory per split. Both
grow about linearly with the games: on the whole sample expect five to six
hours and 30 GB per split, or more threads once the machine is free.
