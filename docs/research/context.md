# Context: what the game state adds to predicting the next order

Models of the opening are to decide from the game state as well as from the
orders before
([ADR 0005](../decisions/0005-learn-decisions-with-their-context.md)). Before
the whole slice is re-simulated, this document measures on a sample how much
each kind of state improves the prediction of the next order over the orders
alone. The first learned model is asked by every builder what it does next, a
unit to build or a job
([ADR 0019](../decisions/0019-first-model-trees-asked-by-every-builder.md)).
The table it is measured on is decided in
[ADR 0018](../decisions/0018-learn-from-orders-joined-with-the-state-before-them.md)
and described in [`context-dataset.md`](../reference/context-dataset.md).
Code: `reason8/context/`.

```sh
uv run reason8 context build                   # data/state -> data/datasets/context_v2/
uv run reason8 context check --games 20        # the join, below
uv run reason8 context measure                 # validation: compare
uv run reason8 context measure --split test    # the tables below
```

The first part is the builder model's table, `context_v2`: orders with their
builders, jobs next to build orders, build power and skill. The second part is
the first table, `context_v1`, with the build orders only; its numbers stay as
they were measured.

## Summary

The game state helps to predict a builder's next order, but only by a few
points; knowing which builder asks helps more. On the builder model's table
(2,996 re-simulated games, scored on the test split), trees given only the
order history predict the next answer right 56.0% of the time. Told what kind
of builder asks and what it did last, they reach 60.5%; adding the game time,
the team's economy, its own units, build power and skill (the inputs of ADR
0019\) gives 63.8%, another 3.3 points. Economy and own units add the most;
allies and wind add little. Skill passes ADR 0019's test, but only narrowly.
The commander gains the most from the state, factories the least. Two points
matter for play: the trees repeat their previous answer more often than
players do (36.5% of steps against 30.7%), and a history of one step instead
of three scores as well and repeats a little less. The mask of impossible
answers removes under 1% of the probability and changes no top answer.

The second part, on build orders only, was measured on the first 503 games and
is preliminary; for what the state adds, the first part's numbers replace it.
Its finding that trees on 411 games match the n-gram trained on the whole
dataset was not measured again.

Used in
[ADR 0019](../decisions/0019-first-model-trees-asked-by-every-builder.md): the
model's inputs, the mask, the test that keeps skill, and the shorter history
played next to the full one.

## The builder model's table (`context_v2`)

On the whole sample: 2,996 of its 3,000 games were re-simulated when the table
was built (2026-11-27), 2,411 of them in training, 299 in validation and 286
in test. The numbers are on the test split: 286 games, 129,525 scored steps.

### Findings

- **Almost every order has its builder.** 99.98% of the structure orders and
  99.5% of the factory orders of the openings reached a unit that can build
  what was ordered. On 20 games, the unit that started a structure was one of
  the order's builders for 98.7% of the commander's orders and 95.7% of the
  construction units', and every factory order's units came from its factory.
- **An order is almost always one builder's.** 98.8% of the scored steps went
  to one builder. Scored once per step (the player's decision) or once per
  builder (the bot's asks), the models score within 0.1 point of each other.
- **Jobs are a fifth of the steps.** 21% of the scored steps are jobs: assist
  12%, reclaim 9%, repair and resurrect a few thousand steps. A third of all
  scored steps come from widgets, almost all of the construction turrets'
  among them.
- **The builder is the biggest input.** Told what kind of builder asks, its
  type and the answer it got before, the trees predict 4.5 points of top-1
  better than with the order history alone (56.0% to 60.5%), 13.7 points for
  construction units. With the inputs of ADR 0019 (time, economy, own units,
  build power, skill) they reach 63.8%, another +3.3 points (3.1 to 3.5) and
  0.092 nats; economy and own units add the most, +1.9 each, build power and
  time +0.9 each.
- **Build or job is right 92% of the time**, against 79% for always guessing a
  build. Factories, turrets and resurrection bots have only one kind of
  answer; for the commander it is 88%, for construction units 87% (86% for
  always a build).
- **Skill changes the answers and the fit, a little.** Set to the 10th and the
  90th percentile, the predictions for the same rows differ by a total
  variation of 0.096. Against the same model without skill the fit improves by
  0.009 and 0.013 nats in the lowest and highest skill bands and not in the
  middle one; top-1 by +0.3 points in the highest band only. ADR 0019's test
  is met, narrowly.
- **The mask removes little.** The answers a builder cannot give hold 0.06% to
  0.6% of the probability, and no true answer of the test steps is one its
  builder cannot give by the unit files. Masked and unmasked top-1 are the
  same; log-loss improves by up to 0.006 nats.
- **The trees repeat more than players.** Their most likely answer repeats the
  previous step's 36.5% of the time, against 30.7% for the players. A history
  of one step instead of three is as good (-0.2 points, -0.4 to +0.0; 0.002
  nats better) and repeats a little less (35.9%).

### Builders

A clicked command goes to the player's selection, the last `select` event of
the player before it in the replay's stream; a widget's command lists its
units, as `reason8.analysis.apm` and `reason8.analysis.reactions` resolve
them. The re-simulated game is the replay played again, so its unit ids are
the replay's, and its unit events say what each id was in the order's frame.
The unit files of the game version say what each type builds and which jobs it
can do. An order's builders are the units it went to that were the player's,
alive, and can carry it out.

On the 2,996 games (8.2 million orders and 8.9 million rows):

| orders    | count     | with a builder | to several builders | to a selection with army units |
| --------- | --------- | -------------- | ------------------- | ------------------------------ |
| structure | 3,517,752 | 99.98%         | 12.2%               | 0.02%                          |
| factory   | 753,645   | 99.49%         | 0.01%               | 0.53%                          |
| job       | 3,946,472 | 100%           | 1.3%                | 0.01%                          |

Most orders to several builders are later parts of long queues given to a
group of construction units; within the scored steps, 1.2% went to more than
one builder. The build orders without a builder (4,692) went mostly to units
whose unit file, as written, does not list the unit: the game changes some
build lists when it loads the files (`alldefs_post`), which the unit files do
not show. 14,648 jobs reached no builder: they went to army units only and are
not in the table.

Builders by kind, among the scored steps:

| kind         | steps   | jobs | sent by a widget |
| ------------ | ------- | ---- | ---------------- |
| commander    | 619,518 | 21%  | 39%              |
| factory      | 350,762 | 0%   | 10%              |
| construction | 253,993 | 13%  | 47%              |
| other        | 99,265  | 100% | 23%              |
| tower        | 22,292  | 100% | 95%              |
| none         | 2,065   | 0%   | 15%              |

"Other" builders are resurrection bots; "tower" are construction turrets.

### Jobs

The commands that give a builder a job and what the table makes of them:

| job       | command                    | orders    | steps   | scored steps |
| --------- | -------------------------- | --------- | ------- | ------------ |
| assist    | `GUARD`, `REPAIR` building | 466,815   | 369,027 | 162,523      |
| reclaim   | `RECLAIM`                  | 3,458,760 | 253,031 | 117,827      |
| repair    | `REPAIR` finished, area    | 17,631    | 15,587  | 3,448        |
| resurrect | `RESURRECT`                | 3,266     | 3,033   | 520          |

- `REPAIR` of a unit still being built is helping to build it, so it is
  assist, as `GUARD` of a builder is; 7,673 of the clicked `REPAIR` orders are
  of finished units or areas and stay repair.
- Area versions (reclaim, repair and resurrect of an area, 169,000 orders) are
  the same jobs as their single-target versions: the model answers the job,
  and BARb picks the target.
- Widgets turn one reclaim of an area into one `RECLAIM` per feature, all in
  one frame: 3.2 million of the reclaim orders. The rule that forms steps
  makes such a burst one step; 53,000 steps of widgets' reclaims remain.
- An order to a selection of builders and army units goes to the builders
  only; that is 0.01% to 0.5% of the orders.
- Moves, fights, patrols, attacks and the like are not answers of the model
  and are not rows. They count for whether a builder is busy.

### The join

`reason8 context check --games 20` (27,774 rows of build orders): the
resources and units of every row equal the state tables, as for the first
table.

Whether the unit that built what was ordered is one of the order's builders:

| order     | builder      | orders | built for it | by one of its builders | the same, one builder |
| --------- | ------------ | ------ | ------------ | ---------------------- | --------------------- |
| factory   | factory      | 4,576  | 99.4%        | 100%                   | 100%                  |
| structure | commander    | 8,269  | 77.8%        | 98.7%                  | 98.7%                 |
| structure | construction | 14,464 | 53.9%        | 95.7%                  | 95.5%                 |

A structure counts as built for an order when the team created a unit of its
type within 16 map units of its spot after it, and the unit that started it is
in its `created` line. As in the first table, many orders are never built in
the 10 minutes: later parts of long queues, and orders replaced later. Which
unit started the 4% to 5% that another unit built was not looked into.

### How it is measured

The protocol of the first table (below), with the answer in place of the unit:
the steps of each player are formed from all their decisions, build orders and
jobs, and the first 30 steps of each opening are scored. Two views of a step:

ask
: one row per builder that got the step's order: what the bot does, where each
  builder asks.

order
: one row per step, the builder with the most build power standing for it: the
  player's decision.

The trees are trained on the ask view of the training games, stopped on that
of the validation games, and scored with the mask of ADR 0019: the answers the
asking builder can never give (not in its build list, a job it cannot do) are
removed and the rest rescaled. Their history is that of the first table, with
jobs among the previous answers and counted like units. The reference for the
context groups is the history with the **builder** group: its kind, type,
whether it moves and the answer it got before, which the bot knows when a
builder asks.

The trees' settings are those of the first table but one: a leaf needs a
weight of at least 50 rows instead of 5. With 5, on the 1.9 million training
rows of this table, the boosting diverged from the second round (the training
loss rose) through leaves of a few rows on splits of the categorical history
columns; on 500,000 rows it did not.

### Results

| model                                | top-1             | top-3             | log-loss            | top-1 vs reference  | log-loss vs reference     |
| ------------------------------------ | ----------------- | ----------------- | ------------------- | ------------------- | ------------------------- |
| history                              | 56.0% (55.6–56.4) | 85.5% (85.2–85.9) | 1.260 (1.247–1.272) | -4.5 (-4.7 to -4.3) | +0.129 (+0.125 to +0.133) |
| history + builder (reference)        | 60.5% (60.1–60.9) | 88.2% (87.9–88.5) | 1.131 (1.118–1.145) |                     |                           |
| + time                               | 61.4% (61.0–61.8) | 88.6% (88.4–89.0) | 1.107 (1.094–1.120) | +0.9 (+0.8 to +1.0) | -0.025 (-0.026 to -0.023) |
| + economy                            | 62.4% (61.9–62.8) | 89.2% (88.9–89.5) | 1.080 (1.067–1.094) | +1.9 (+1.7 to +2.1) | -0.052 (-0.054 to -0.049) |
| + own units                          | 62.4% (62.0–62.8) | 89.1% (88.8–89.4) | 1.081 (1.068–1.095) | +1.9 (+1.7 to +2.1) | -0.050 (-0.052 to -0.048) |
| + build power                        | 61.4% (60.9–61.8) | 88.6% (88.3–88.9) | 1.107 (1.093–1.120) | +0.9 (+0.7 to +1.0) | -0.025 (-0.026 to -0.023) |
| + skill                              | 60.9% (60.4–61.3) | 88.4% (88.1–88.7) | 1.122 (1.109–1.136) | +0.4 (+0.2 to +0.5) | -0.009 (-0.011 to -0.008) |
| + allies                             | 61.2% (60.7–61.6) | 88.7% (88.4–89.0) | 1.109 (1.097–1.122) | +0.7 (+0.5 to +0.8) | -0.022 (-0.024 to -0.020) |
| + wind                               | 60.8% (60.4–61.2) | 88.4% (88.1–88.7) | 1.123 (1.110–1.136) | +0.3 (+0.1 to +0.4) | -0.009 (-0.010 to -0.007) |
| + pace (not context)                 | 62.9% (62.4–63.3) | 89.1% (88.8–89.4) | 1.051 (1.039–1.064) | +2.4 (+2.2 to +2.5) | -0.080 (-0.083 to -0.078) |
| ADR 0019 inputs                      | 63.8% (63.3–64.2) | 89.9% (89.6–90.1) | 1.039 (1.026–1.053) | +3.3 (+3.1 to +3.5) | -0.092 (-0.095 to -0.089) |
| ADR 0019 inputs without skill        | 63.6% (63.2–64.1) | 89.7% (89.4–90.0) | 1.047 (1.034–1.061) | +3.1 (+3.0 to +3.3) | -0.085 (-0.087 to -0.082) |
| ADR 0019 inputs, one step of history | 63.6% (63.1–64.0) | 89.9% (89.6–90.2) | 1.036 (1.024–1.051) | +3.1 (+2.8 to +3.3) | -0.095 (-0.099 to -0.091) |

The ADR 0019 inputs are the history, the builder, time, economy, own units,
build power and skill. The pace of the orders still adds the most of any
single group, as in the first table, and stays out of the models.

#### By kind of builder

Top-1 of the reference, and what each group adds to it (points, paired
intervals), per kind of the asking builder:

| model                                | commander (59,186)  | factory (34,075)    | construction (26,656)  | tower (2,123)       | other (9,154)       |
| ------------------------------------ | ------------------- | ------------------- | ---------------------- | ------------------- | ------------------- |
| history                              | -3.5 (-3.8 to -3.1) | -0.2 (-0.5 to +0.2) | -13.7 (-14.4 to -13.0) | -4.7 (-5.9 to -3.4) | -0.1 (-0.2 to +0.0) |
| history + builder (reference)        | 60.2% (59.7–60.7)   | 50.8% (50.2–51.5)   | 57.6% (56.6–58.5)      | 96.5% (95.6–97.4)   | 99.2% (98.9–99.4)   |
| + time                               | +1.4 (+1.2 to +1.6) | +0.4 (+0.0 to +0.7) | +0.8 (+0.5 to +1.1)    | +0.1 (-0.1 to +0.5) | -0.0 (-0.1 to +0.0) |
| + economy                            | +3.3 (+3.0 to +3.6) | +0.5 (+0.2 to +0.9) | +1.1 (+0.7 to +1.4)    | +0.3 (-0.1 to +0.8) | +0.0 (-0.1 to +0.1) |
| + own units                          | +2.9 (+2.6 to +3.2) | +0.4 (+0.1 to +0.8) | +2.3 (+2.0 to +2.7)    | +0.7 (+0.0 to +1.3) | -0.0 (-0.1 to +0.0) |
| + build power                        | +1.3 (+1.1 to +1.5) | +0.5 (+0.2 to +0.8) | +0.9 (+0.6 to +1.2)    | +0.2 (-0.3 to +0.9) | +0.0 (-0.0 to +0.1) |
| + skill                              | +0.3 (+0.1 to +0.5) | +0.7 (+0.4 to +1.1) | +0.2 (-0.1 to +0.4)    | +0.0 (-0.2 to +0.4) | -0.0 (-0.1 to +0.0) |
| + allies                             | +1.1 (+0.9 to +1.4) | +0.2 (-0.1 to +0.6) | +0.4 (+0.1 to +0.8)    | +0.0 (-0.1 to +0.2) | +0.0 (-0.1 to +0.1) |
| + wind                               | +0.5 (+0.3 to +0.7) | +0.1 (-0.2 to +0.4) | +0.1 (-0.2 to +0.4)    | +0.0 (-0.1 to +0.2) | -0.0 (-0.1 to -0.0) |
| + pace (not context)                 | +2.9 (+2.6 to +3.2) | +2.2 (+1.8 to +2.5) | +2.4 (+2.0 to +2.8)    | +0.1 (-0.1 to +0.4) | -0.0 (-0.1 to +0.0) |
| ADR 0019 inputs                      | +5.5 (+5.1 to +5.8) | +1.0 (+0.6 to +1.4) | +2.5 (+2.1 to +2.9)    | +1.2 (+0.5 to +2.0) | -0.0 (-0.2 to +0.1) |
| ADR 0019 inputs, one step of history | +5.5 (+5.1 to +5.9) | +0.3 (-0.2 to +0.8) | +2.5 (+2.1 to +2.9)    | +1.2 (+0.6 to +1.9) | +0.0 (-0.1 to +0.1) |

- **The commander gains the most from the state**: +5.5 points with the ADR
  0019 inputs, the economy and own units most.
- **Factories gain the least**, a point at most from any group of state. What
  a factory builds next follows its own previous unit (the builder's previous
  answer) and the history; 51% top-1 is the lowest of the kinds. Skill helps
  factories most of all kinds (+0.7 points).
- **Construction units need the builder most**: without it they are predicted
  14 points worse, because the player's last steps are often another
  builder's.
- Turrets and resurrection bots are near 100%: their answers are almost all
  assist or reclaim, much of it sent by widgets.

#### Build or job

Whether the answer is a job, taking the masked probability of the four jobs
together, a job at one half or more:

| model                  | commander | construction | all   | log-loss |
| ---------------------- | --------- | ------------ | ----- | -------- |
| share of jobs          | 20.8%     | 14.3%        | 20.9% |          |
| always the more common | 79.2%     | 85.7%        | 79.1% |          |
| history                | 83.0%     | 76.3%        | 87.5% | 0.259    |
| history + builder      | 84.0%     | 86.1%        | 90.0% | 0.215    |
| ADR 0019 inputs        | 88.3%     | 86.7%        | 92.0% | 0.181    |

Factories never get a job; turrets and resurrection bots get nothing else, so
both are right by construction. For construction units, the trees hardly beat
always answering a build: when a construction unit is sent to assist or
reclaim is what the inputs do not show (where the reclaimable metal is, what
is being built nearby).

#### The mask

For the ADR 0019 inputs, per kind of builder:

| kind         | rows   | probability removed, mean | p90   | true answers removed | log-loss masked vs unmasked |
| ------------ | ------ | ------------------------- | ----- | -------------------- | --------------------------- |
| commander    | 59,186 | 0.22%                     | 0.38% | 0                    | -0.002 (-0.002 to -0.002)   |
| factory      | 34,075 | 0.32%                     | 0.23% | 0                    | -0.005 (-0.007 to -0.003)   |
| construction | 26,656 | 0.57%                     | 0.76% | 0                    | -0.006 (-0.007 to -0.006)   |
| tower        | 2,123  | 0.12%                     | 0.28% | 0                    | -0.001 (-0.002 to -0.001)   |
| other        | 9,154  | 0.06%                     | 0.11% | 0                    | -0.001 (-0.001 to -0.001)   |

The trees already know the builder's kind and type, so they rarely put weight
on answers it cannot give; the mask changes no top-1 answer here. On the 60
games of a first trial, with fewer training games, it removed 1% to 9%. It
stays cheap insurance, and it is what the bot plays with.

#### The two views

| model                              | scored on | top-1             | top-3             | log-loss            |
| ---------------------------------- | --------- | ----------------- | ----------------- | ------------------- |
| ADR 0019 inputs, trained on asks   | asks      | 63.8% (63.3–64.2) | 89.9% (89.6–90.1) | 1.039 (1.026–1.053) |
| ADR 0019 inputs, trained on asks   | orders    | 63.8% (63.4–64.2) | 90.0% (89.7–90.2) | 1.036 (1.023–1.049) |
| ADR 0019 inputs, trained on orders | asks      | 64.0% (63.5–64.4) | 89.8% (89.6–90.1) | 1.036 (1.023–1.050) |
| ADR 0019 inputs, trained on orders | orders    | 64.0% (63.6–64.5) | 89.9% (89.7–90.2) | 1.032 (1.019–1.046) |

1.2% of the scored steps went to more than one builder, so the two views
differ by 1.4% of their rows and the scores by less than their intervals.
Trained on the order view, the trees are 0.2 points better on both views, at
the edge of the intervals.

#### Skill

ADR 0019 keeps skill as an input only if the predictions change between low
and high skill and the fit per skill band improves. With skill set to the 10th
and the 90th percentile of the training rows (18.0 and 44.1) for every test
row, the masked predictions differ by a total variation of 0.096 on average
(median 0.075, 90th percentile 0.212), and the most likely answer is the same
in 88.0% of the rows; the trees predict 20.2% jobs at low skill and 22.0% at
high skill. Against the same model without skill, by skill band of the test
rows:

| skill band   | games | rows   | top-1 with skill  | top-1 vs without skill | log-loss vs without skill |
| ------------ | ----- | ------ | ----------------- | ---------------------- | ------------------------- |
| 3.0 to 24.0  | 256   | 43,773 | 60.5% (59.8–61.2) | +0.0 (-0.2 to +0.3)    | -0.009 (-0.012 to -0.007) |
| 24.0 to 32.5 | 282   | 43,780 | 64.7% (64.0–65.4) | -0.0 (-0.2 to +0.2)    | -0.001 (-0.003 to +0.001) |
| 32.5 to 83.5 | 253   | 43,817 | 66.1% (65.5–66.8) | +0.3 (+0.1 to +0.6)    | -0.013 (-0.016 to -0.011) |

Both conditions hold, narrowly: the predictions move, and the fit improves in
the lowest and the highest band by about 0.01 nats, not in the middle one.
Skill has 0.5% of the trees' gain. On the first 800 games (633 in training)
the fit improved in no band, so the gain shows only with the larger data.

#### Repeating the previous answer

In the game the order history is the model's own earlier answers
([`builder-model-prior-work.md`](builder-model-prior-work.md)). How often an
answer is the previous step's answer, and the previous answer of the asking
builder:

|                                      | same as the previous step | same as the builder's previous | top-1             |
| ------------------------------------ | ------------------------- | ------------------------------ | ----------------- |
| the players                          | 30.7%                     | 32.7%                          |                   |
| ADR 0019 inputs, top answer          | 36.5%                     | 39.1%                          | 63.8% (63.3–64.2) |
| ADR 0019 inputs, one step of history | 35.9%                     | 38.4%                          | 63.6% (63.1–64.0) |

The trees' most likely answer repeats a fifth more often than players do. The
bot samples among likely answers rather than taking the top one, which brings
the rate closer to the players'; whether its games drift is measured from its
games (ADR 0019). A history of one step loses nothing measurable on replays
(-0.2 points, -0.4 to +0.0; 0.002 nats better) and repeats slightly less, so
it is the safer of the two to play.

#### What the trees use

The builder group has 51% of the gain of the model with the ADR 0019 inputs:
the builder's previous answer 28% and its type 19%. The history has 37% (the
previous step 12%), build power 5.0% (the builder's own 3.1%), economy 3.0%,
own units 2.3%, time 0.9% and skill 0.5%.

Clicked orders are harder than widgets' (57.0% top-1 against 77.6%); asks of
builders that were idle, the situation in which the bot asks, are predicted
about as well as all (62.7%).

### Cost

The build of the 2,996 games took 7 minutes. The measurement fits 15 tree
models on the GPU (`xgboost`, an RTX 4090), 8 to 21 minutes each with 24
threads for the data, 3 hours for one split and at most 33 GB of memory. On
800 games it fitted in 10 GB.

### What the state export lacks

Built from format 5 state tables, the table cannot honestly have:

Whether a builder is busy, and with what
: Format 5 writes a line when a builder runs out of orders, nothing when it
  starts working. Idle is inferred from that line and the commands it got
  after; a new builder counts as busy until its first idle line. 19% of the
  rows have no idle state for their builder, and 7% were idle when they got
  their order. Format 6 samples what every builder (not factories) works on
  every 5 frames; `builder_idle` and the idle build power would come from it
  directly, and so would the build power actually spent.

What a job is done to
: The table knows whether a `REPAIR` target was still being built and whether
  a `RECLAIM` points at a feature, but not how much metal and energy the map
  has to reclaim, or where. Format 6 records every reclaimable feature with
  its metal and energy and what each team took from it: an input for when to
  reclaim, which the trees cannot predict well for construction units now, and
  for the reclaim and resurrection targets ADR 0019 leaves to later.

What the game made of the unit files
: Build lists, build power and job flags come from the unit files as written.
  The game changes some when it loads them, so 0.1% of the build orders lose
  their builder and the mask could in principle remove a true answer (none on
  test). Format 7 of the state export writes them as the game loaded them, in
  the `game` table's `unit_defs` (build power, build options and job flags);
  the games of this sample are of formats 5 and 6
  ([`state-extraction.md`](state-extraction.md)).

Queues
: A builder's and a factory's queue are not exported. The table sees the
  orders given, not what is still to do, so it cannot tell a builder with a
  long queue from one about to go idle. Exporting every queue when it changes
  would add a third to the state tables
  ([`state-extraction.md`](state-extraction.md)).

## The first table: build orders only (`context_v1`)

**The numbers below are preliminary**: 503 of the 3,000 games of the sample
were re-simulated when they were measured (2026-11-27), 411 of them in
training, 47 in validation and 45 in test. The test split is small and its
intervals are wide; the same commands give the numbers on the whole sample
once the batch is done.

### Findings

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

### The sample

3,000 games of the slice, drawn with a fixed seed from the `ok` games of
`openings_v2`: 1,350 Supreme Isthmus, 1,350 All That Glitters and 300 Rosetta,
in the dataset's train, validation and test splits
(`data/logs/context-sample.parquet`). Each is re-simulated for its first 10
minutes (`reason8 headless batch --max-frame 18000`, 8 engines at once, about
150 games an hour on one machine), with resources every second (state format
5). The decision table takes the rows of `openings_v2` of every game whose
state is there, so it grows as the batch goes on, and the split of a game
never changes.

### The join

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

### How it is measured

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

#### The pace of the orders is not context

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

### Results

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

#### By map

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

#### What the trees use

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

#### Reading it

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

### What it means for the first model

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

### Reproducing

`context_v1` was built by the code of its manifest's commit; the code of today
builds `context_v2` instead, and still checks and measures the first table:

```sh
uv run reason8 context check --table data/datasets/context_v1 --games 20
uv run reason8 context measure --table data/datasets/context_v1 --split test
```

The build read every game whose state was there and took about 30 s for 500
games. The measurement fits eight tree models on all the steps of the training
games: on 503 games, 411 of them in training (230,000 steps), it took 55
minutes on the CPU with 6 threads and at most 5.1 GB of memory per split.
