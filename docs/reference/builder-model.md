# The builder model's file

The first learned model decides, during the game, the next order of every idle
unit with build power: a unit to build or a job
([ADR 0019](../decisions/0019-first-model-decides-each-builders-next-order.md)).
It is gradient-boosted trees trained on the decision table `context_v2`
([`context-dataset.md`](context-dataset.md)) and written to a plain JSON file
that the game library evaluates with its own code, without XGBoost. This
document is the contract between the two: what the file holds, how a decision
is evaluated, and what the library has to compute for every input. Code:
`reason8/models/builder.py` (training, export, scoring) and
`reason8/models/trees.py` (the reference evaluator).

```sh
uv run reason8 model train                  # -> data/models/builder_v1.json, builder_v1_no_skill.json
uv run reason8 model score data/models/builder_v1.json data/models/builder_v1_no_skill.json --split test
uv run reason8 model vectors                # -> tests/models/builder_vectors.json
uv run reason8 model vectors --model data/models/builder_v1.json
```

## Training

`reason8 model train` trains two models with the same settings, one with the
player's skill as an input (`builder_v1`) and one without
(`builder_v1_no_skill`); the in-game measures choose between them (ADR 0019).
For each it writes:

`<name>.json`
: The model file below.

`<name>.xgb.ubj`
: XGBoost's own model, to check the file against; the game never reads it.

The settings are a `Config` (`--config` takes one as JSON; `--max-depth`,
`--max-rounds`, `--min-class-steps` and `--drop` change one setting), written
into the file with the seed, the rounds kept and the table's manifest. The
defaults are the model measured in [`context.md`](../research/context.md):

- **Rows:** the order view of the table's steps: one row per step, the builder
  of most build power standing for the builders the order went to (the builder
  view has one row per builder). Trained on the training split and stopped on
  the validation split.
- **Inputs:** the order history of one step, the builder, the game time, the
  team's economy, its own units, build power, and skill (below). Not the pace
  of the orders and not whether the builder was idle: they describe the
  player's timing, not the game.
- **Answers:** one class per answer seen at least 20 times in training; the
  rarer answers share one class.
- **Trees:** XGBoost `multi:softprob`, depth 6, learning rate 0.15, 64 bins, a
  leaf weight of at least 50 rows, subsampling 0.8 of the rows and of the
  inputs per node, seed 0, 100 rounds (a smaller file than the 400 the
  measurement allows; see [size](#size)), stopped earlier only after 20 rounds
  without a better validation log-loss.

Before the file is kept, the probabilities it gives through the reference
evaluator are compared with XGBoost's on every held-out row of the test split;
a difference above 10⁻⁴ stops the training. The largest difference is recorded
in the file (`training.check`).

## The file

One JSON object, format `reason8.builder-trees/1`. A change that a reader of
this version cannot evaluate gets a new format name. Abridged:

```json
{
  "format": "reason8.builder-trees/1",
  "name": "builder_v1",
  "answers": ["assist", "armwin", "...", "reclaim", "<unknown>"],
  "features": [
    {
      "name": "faction",
      "group": "history",
      "type": "categorical",
      "categories": ["Armada", "Cortex", "Legion"]
    },
    {
      "name": "time_s",
      "group": "time",
      "type": "numeric"
    }
  ],
  "classes": [
    {
      "answers": [0],
      "weights": [1.0]
    },
    {
      "answers": [7, 12, 40],
      "weights": [0.5, 0.3, 0.2]
    }
  ],
  "base_score": [0.12, -0.4],
  "trees": [
    {
      "class": 0,
      "feature": [3, 0, -1, -1, -1],
      "threshold": [120.5, 0.0, 0.0, 0.0, 0.0],
      "left": [1, 3, 0, 0, 0],
      "right": [2, 4, 0, 0, 0],
      "default_left": [1, 0, 0, 0, 0],
      "value": [0.0, 0.0, -0.21, 0.45, -0.21],
      "categories": [[1, [0, 2]]]
    }
  ],
  "builders": {
    "armcom": {
      "kind": "commander",
      "moves": true,
      "build_power": 300.0,
      "answers": [0, 1, 2]
    }
  },
  "choice": {
    "threshold": 0.1,
    "unknown": "<unknown>"
  },
  "training": {
    "config": {},
    "seed": 0,
    "rounds": 100,
    "dataset": {},
    "check": {},
    "size": {}
  }
}
```

`answers`
: Every answer the model can give, by index: unit names of today's game (with
  the faction prefix) and the four jobs `assist`, `reclaim`, `repair`,
  `resurrect`. The last is `choice.unknown`, the share of answers never seen
  in training; it cannot be carried out.

`features`
: The inputs in the order the trees index them (`trees[].feature`), with the
  group they come from and their type. A `numeric` input is a 32-bit float; a
  `categorical` one is the index of its value in `categories`. Their meaning
  and where the library gets them: [the inputs](#the-inputs).

`classes`
: What each class of the trees stands for: the answers (indices into
  `answers`) and the share of the class's probability each gets. Most classes
  are one answer with weight 1; the last holds the rare answers and the
  unknown one, each weighted by its training count plus one.

`base_score`
: One number per class: where its margin starts.

`trees`
: The trees, each for one `class`, as parallel arrays over its nodes, node 0
  the root. A node with `feature` −1 is a leaf, with `value` its leaf value. A
  split node sends the row to `left` or `right`: a missing input goes left
  when `default_left` is 1; a categorical node (listed in `categories` as
  `[node, [codes]]`) sends the codes of its set right and every other code
  left; a numeric node sends a value below `threshold` left and the rest
  right. Thresholds and leaf values are 32-bit floats, written as the shortest
  decimal that reads back to the same float.

`builders`
: Per builder type (today's unit name): its kind, whether it moves, its build
  power and the answers it can give (indices into `answers`): its build list
  and the jobs it can do, from the unit files of the newest game version in
  the table (`training.mask_game_version`), as written.

`choice`
: The threshold of ADR 0019's choice and the name of the unknown answer.

`training`
: When, from which code and with which XGBoost the model was trained, its
  `config`, `seed`, the `rounds` kept, the training rows and games, the 10th,
  50th, 90th and 99th percentile of skill in training (`skill_quantiles`), the
  table's manifest (`dataset`), the check against XGBoost (`check`) and the
  size (`size`: bytes, trees, nodes, leaves, classes, answers, inputs).

## Deciding an order

`TreeFile.decide` in `reason8/models/trees.py` is the reference. Steps 1 to 4
are the model's part, what replaces the stand-in behind `AnswerModel` in
`ai/native/Model.h`; steps 5 and 6 are the bot's mask and choice, `Mask` and
`Choose` in `ai/native/Choice.h`, which the reference does the same way so
that the test vectors cover a whole decision.

1. **Encode** each input of `features`: a number as a 32-bit float, true and
   false as 1 and 0, a name as its index in `categories`. A name not in
   `categories` and an input the library does not have are missing (NaN).
2. **Margins:** each class starts at its `base_score`; walk each tree from
   node 0 to a leaf as above and add the leaf's value to the margin of the
   tree's class. Compare as 32-bit floats; the reference sums in 64 bits and
   XGBoost in 32, which differ by about 10⁻⁷ in the probabilities.
3. **Class probabilities:** the softmax of the margins.
4. **Answer probabilities:** each class's probability split over its answers
   by `classes`. `Predict` returns these, one `Answer` per entry of `answers`
   with its name.
5. **Mask:** remove the answers the builder the order is for cannot give and
   those of probability zero, rescale the rest to sum to one, most likely
   first. In the game the bot reads the unit definitions as the game loaded
   them (`CanGive` in `ai/native/NextOrder.cpp`); the unknown answer is no
   unit, so it is always removed. The reference takes the builder's answers
   from `builders`, the unit files the model was trained with.
6. **Choose:** the candidates are the possible answers of at least
   `choice.threshold`; with none, BARb decides. Otherwise a uniform number u
   in \[0, 1) times the candidates' total picks the first candidate, most
   likely first, at which their running sum exceeds it.

The scores of [`context.md`](../research/context.md#the-first-model) mask by
each game's own unit files and keep the unknown answer, so that an answer no
model has seen still has a probability.

### Test vectors

`tests/models/builder_vectors.json` holds a small model trained on synthetic
rows (`model`, a complete file of this format with categorical and numeric
inputs, missing values, a class shared by rare answers and two builder types
to mask) and 40 `decisions`, each with:

`inputs`
: By name; `builder_unit` names the builder's type. A value may be `null`, a
  name never seen, or exactly on a threshold.

`encoded`
: The row the trees read, `null` for missing.

`probabilities`
: What `Predict` returns: the probability of every entry of `answers`, in its
  order.

`can_give`
: The answers the builder can give, for the mask (`CanGive`).

`possible`
: The answers after the mask, most likely first, as `[answer, probability]`.

`uniform`, `answer`
: The number of the draw and the answer `Choose` draws with it (`null`: BARb
  decides). The draws are at least 10⁻⁴ from where the answer changes, so 32-
  and 64-bit sums draw the same.

The library must reproduce the numbers to within `tolerance`.
`reason8 model vectors` writes them again, the same every time; with `--model`
it writes 100 synthetic decisions of a trained model next to it, to test the
library against the file it plays. The tests check that the evaluator still
gives the committed vectors and that it matches XGBoost.

## In the bot

The bot decides the next order of an idle builder through `AnswerModel`
(`ai/native/Model.h`), whose stand-in (`StandIn.h`,
`ai/Reason8/stand_in.json`) answers from a fixed table per builder unit and
minute. The trees replace the stand-in: a model that loads this file once per
process, computes the inputs below for the `IdleBuilder` it is given (its
unit, kind, build power and the frame come with it; the rest it reads from the
engine), walks the trees and returns the probability of every answer. The mask
and the choice stay as they are. That model is the next step: its C++ side,
tested against the vectors above, and the build step that copies the file into
the AI folder in place of `stand_in.json`, which the option
`builder_orders = model` then plays. Until then the stand-in plays.

## Size

`builder_v1` is 73.5 MB of JSON (6.3 MB gzipped): 289 classes, 100 rounds,
28,900 trees and 489,020 nodes, of which 258,960 leaves; `builder_v1_no_skill`
is 73.3 MB with 484,522 nodes. A decision walks every tree once: about 55,000
split nodes (at most 60,400 on 20 synthetic decisions), a fraction of a
millisecond in C++. Held as arrays (a 16-bit input index, a 32-bit threshold
or leaf value, two 32-bit children and the missing side), the trees take about
7 MB per process.

Trained for the 400 rounds the measurement allows, without stopping by itself,
the model is 293 MB of JSON with 2.1 million nodes, too large to load in the
game. Cutting rounds costs the least accuracy for the size: the shipped 100
rounds cost 1.3 points of top-1 and 0.043 nats on validation against 400,
while fewer classes or shallower trees of the same size cost more
([`context.md`](../research/context.md#the-size-of-the-model)).

The file is plain JSON so that the library reads it with the JSON parser BARb
already has (jsoncpp, in BARb's `src/lib/json`). Parsed whole, a 73 MB file
takes far more memory than its arrays, so the library should read it once per
process, for all its AIs, and keep only the arrays. It is not committed: it is
built from data that stays private and it is larger than anything in the
repository. The plan is that `reason8 bot build` copies it from `data/models/`
into the AI folder in place of `stand_in.json`, in the next step.

## The inputs

What the library computes for every input when it decides the next order of an
idle builder, and from where. "The team" is the AI's own team, "the builder"
the builder the order is for. The table takes the state at the end of the
frame before the order; the library reads it when it decides, which is the
same moment for the bot.

Each entry gives what the input is in the table, how the library computes it,
and whether that is exactly what the model was trained on.

### The order history (one step)

`faction`
: *Table:* the player's faction: `Armada`, `Cortex` or `Legion`.
: *Library:* from the prefix of the team's commander's unit name at frame 0
  (`UnitDef_getName`).
: *Exact:* yes.

`map`
: *Table:* the map's name with its version, e.g. `Supreme Isthmus v2.1`.
: *Library:* `Map_getName` (as the opening script reads it). Any map not in
  `categories` is missing.
: *Exact:* yes.

`position`, `role`
: *Table:* the start position (the nearest spawn point of the map's metadata,
  `P1` …) and its role, from the opening dataset.
: *Library:* the position the opening script already finds from the
  commander's position at frame 0 and the map's positions in `openings.json`,
  and its role from the same metadata.
: *Exact:* yes for the maps and positions of the metadata; elsewhere missing.

`step_idx`
: *Table:* how many steps the player had made before this one: their build
  orders and jobs, a run of orders of one answer at most 6 frames apart being
  one step ([ADR 0013](../decisions/0013-evaluate-on-held-out-games.md)).
: *Library:* the number of the team's earlier decisions, every order the bot
  gives a builder (the model's and BARb's), by the same rule.
: *Exact:* the same rule, but on the bot's decisions, not a player's; see
  [below](#inputs-the-library-cannot-compute-exactly).

`decision_index`
: *Table:* how many orders the player had given before this one, build orders
  and jobs: each building of a drag and each reclaim of a feature a widget
  sends counts.
: *Library:* the number of the bot's earlier orders.
: *Exact:* **no**; see below.

`previous_1`
: *Table:* the answer of the player's previous step, `<start>` before the
  first.
: *Library:* the answer of the bot's previous decision; for an order of BARb,
  the unit it builds or the job it does.
: *Exact:* yes when BARb's orders are named as answers.

`ordered_<type>`, one per unit type of the table (`mex`, `win`, … `other`)
: *Table:* how many earlier orders of the player added units of that type (the
  unit name without the faction prefix; types not listed count as `other`); a
  drag counts each building, a factory order counts once.
: *Library:* the number of the bot's earlier build decisions per type.
: *Exact:* yes for the bot's own decisions.

`ordered_assist`, `ordered_reclaim`, `ordered_repair`, `ordered_resurrect`
: *Table:* how many earlier job orders of the player were of that job; a
  widget's reclaim of an area counts once per feature.
: *Library:* the number of the bot's earlier job decisions.
: *Exact:* **no** for reclaim; see below.

### The builder

`builder_kind`
: *Table:* `commander` (`customparams.iscommander`), `factory` (does not move,
  has a build list), `construction` (moves, has a build list), `tower` (does
  not move, no build list), `other` (moves, no build list).
: *Library:* from the builder's unit definition: `UnitDef_getCustomParams`,
  `UnitDef_getBuildOptions`, `UnitDef_getSpeed`; or the `kind` of its entry in
  `builders`.
: *Exact:* yes; the table reads the unit files as written, the library as the
  game loaded them, which differ for a few build lists.

`builder_role`
: *Table:* the builder's unit name without the faction prefix (`com`, `ck`,
  `lab`, …).
: *Library:* `UnitDef_getName` of the builder, prefix removed.
: *Exact:* yes.

`builder_moves`
: *Table:* whether the builder's type moves (speed above 0), 1 or 0.
: *Library:* `UnitDef_getSpeed` above 0, or `moves` in `builders`.
: *Exact:* yes.

`builder_previous`
: *Table:* the answer of the previous order that went to this builder,
  `<start>` for its first.
: *Library:* kept per unit: the model's last answer to it, or the unit or job
  of BARb's last order to it.
: *Exact:* yes when BARb's orders are named as answers.

### Time

`time_s`
: *Table:* the game time of the order in seconds.
: *Library:* the current frame divided by 30.
: *Exact:* yes.

### Economy

`metal`, `metal_storage`, `metal_income`, `metal_expense`, `energy`, `energy_storage`, `energy_income`, `energy_expense`
: *Table:* the team's stored resource, storage, income and expense, as
  `Spring.GetTeamResources` gives them, from the last line of the state
  export, written every 30 frames: stored and storage rounded to whole
  numbers, metal income and expense to one decimal, energy income and expense
  to whole numbers.
: *Library:* `Economy_getCurrent`, `Economy_getStorage`, `Economy_getIncome`,
  `Economy_getUsage` (the live state of our library reads the same), taken at
  the last frame that is a multiple of 30 and rounded the same way.
: *Exact:* yes, if the library keeps the values of the last whole second; read
  live they are up to a second newer than the table's.

### Own units

`own_done_<type>`, `own_building_<type>`
: *Table:* the team's units of each type (as `ordered_<type>`, with `com` for
  the commander), finished and under construction.
: *Library:* `getTeamUnits`, `Unit_getDef`, `UnitDef_getName` and
  `Unit_isBeingBuilt`, as the live state's `Reason8Standing` does, counting
  the units being built too.
: *Exact:* yes.

### Build power

`builder_build_power`
: *Table:* the builder's build power (`workertime`).
: *Library:* `UnitDef_getBuildSpeed`, or `build_power` in `builders`.
: *Exact:* yes.

`team_build_power`, `team_build_power_<kind>`
: *Table:* the build power of the team's finished builders, in all and by kind
  (as `builder_kind`).
: *Library:* the same sum over `getTeamUnits` without the units being built.
: *Exact:* yes.

`idle_build_power`, `idle_build_power_<kind>`
: *Table:* the same over the builders that were idle: that went idle (an
  `UnitIdle` line of the state export) and got no order since that gives them
  work. A builder that has not gone idle yet counts as busy, however new.
: *Library:* the same rule from the `UnitIdle` events the AI gets and the
  orders it gives.
: *Exact:* the rule can be followed, but the builder the order is for is idle
  at every decision of the bot and at few of the table's rows; see below.

### Skill

`skill`
: *Table:* the player's rating before the game.
: *Library:* a number the bot is given (ADR 0019: high, but inside the range
  of `training.skill_quantiles`). Absent from `builder_v1_no_skill`.
: *Exact:* not a measurement; chosen.

### Inputs the library cannot compute exactly

Three inputs mean something else for the bot than for a player, so the library
cannot give the value the model learned from:

- `decision_index` and the four `ordered_<job>` counts grow with every
  building of a drag and every reclaim of a feature that a player's widget
  sends; the bot gives one order per decision.
- `idle_build_power` and its kinds follow a rule the library can apply, but
  the builder the order is for is idle at every decision of the bot and at 7%
  of the table's rows.

Leaving all three out costs 0.1 point of top-1 (0.0 to 0.2) and 0.006 nats on
validation, each alone nothing measurable
([`context.md`](../research/context.md#inputs-the-game-cannot-give-exactly)).
They are inputs of this first version only: `builder_v1` and
`builder_v1_no_skill` have them, and the library gives its best approximation
of each as described above. The models trained on the rebuilt decision table
leave them out
([ADR 0019](../decisions/0019-first-model-decides-each-builders-next-order.md)).
