# Prior work for the builder model

The first learned model is gradient-boosted trees that every unit with build
power asks, during the game, what to do next
([ADR 0019](../decisions/0019-first-model-decides-each-builders-next-order.md)).
This document collects what prior work says about five questions that decision
raises, and what Reason8 should do about each:

1. [Drift](#1-drift): the bot picks every step live, so one unusual choice
   leads to states no human was in.
2. [Skill as an input](#2-skill-as-an-input): the model is told the player's
   skill, and in the game the skill is a number we choose.
3. [Action masking](#3-action-masking): one model answers every kind of
   builder, so impossible answers have to be excluded.
4. [What the model sees of the map](#4-what-the-model-sees-of-the-map): the
   next decisions to learn are where to build and which target to reclaim,
   resurrect, repair or assist.
5. [How hand-written AIs choose builder jobs and targets](#5-how-hand-written-ais-choose-builder-jobs-and-targets):
   what BARb does for the model until those are learned, and a source of
   features.

Apex, the BARb fork that learns from AI games, is covered in
[`related-work.md`](related-work.md) and not repeated here; BARb's design is
in [`barb.md`](barb.md).

**How it was read.** Every claim below links the source it comes from. Papers
were read in full text unless marked *abstract only* or *introduction only*.
Source code was read at the commits linked. Where this document reasons beyond
what a source says, it says so ("our reading", "not verified"). All figures
are the sources' own.

## Summary

- **Drift:** the remedies that fix drift properly (DAgger, DART) need an
  expert to label the bot's own states, and we have none. What needs neither
  an expert nor many simulated games: sharpening the sampling (our 10%
  threshold, AlphaStar Unplugged's temperature 0.8), not letting the model
  lean on its own previous answers (the copycat problem), and conditioning on
  a plan taken from human games, as AlphaStar does with its build-order
  statistic. **Cheapest first step:** measure drift from the bot's own games
  with numbers we already have the tools for, and train a variant with a
  shorter order history to see whether it drifts less.
- **Skill:** AlphaStar Unplugged passes MMR as an input and sets it to the
  highest value in play, but reports no test of what changing it does; the
  same paper found that conditioning on the game's result was ignored. Maia-2
  shows that skill concatenated to the other inputs works less well than a
  dedicated mechanism. Nothing found tests skill as a tree feature. **Check
  that the trees use it** before relying on it: predictions at low and high
  skill should differ, and per skill band the model should fit that band
  better.
- **Masking:** RL agents in microRTS mask invalid actions in training and in
  play, and lose much of their strength without it. AlphaStar's open-source
  supervised agent masks unit selections and targets, but not the action type.
  In imitation every label is a valid action, so for trees the correct and
  simple way is **one model, mask and renormalise at inference, and score
  log-loss after the same mask**. Mask only what is impossible (build lists,
  jobs the builder type cannot do), not what is unaffordable.
- **The map:** AlphaStar and microRTS agents output a target as a pointer into
  a list of units or as a cell of a grid, both from large networks. The small
  version that works with trees is **ranking candidates**: list the wrecks (or
  build spots) near a builder, describe each by value, distance and what is
  around it, and train a classifier or ranker to pick the one the player
  chose.
- **Hand-written AIs:** those that choose a reclaim target (BARb, M28AI,
  RNGAI) choose it mainly by distance, with a value threshold and a check for
  danger; M28AI and RNGAI also count the builders already sent to an area.
  BARb picks the nearest reachable, safe feature worth at least 1 metal, near
  the builder or, when a builder is idle, anywhere on the map. Those inputs
  (value, distance, threat, builders already there) are the first features for
  the learned target model.

## 1. Drift

### What the sources did

**The problem.** Ross, Gordon and Bagnell show that a policy trained on the
expert's states, with error ε per step, can make up to T²ε mistakes over T
steps, because once it errs it is in states the expert never showed
([DAgger, arXiv:1011.0686](https://arxiv.org/abs/1011.0686)). Laskey et al.
call this the robot "drifting away from the supervisor's demonstrations"
([DART, arXiv:1703.09327](https://arxiv.org/abs/1703.09327)).

**Remedies that need an expert.**

DAgger
: The learner plays, the expert labels the states the learner visits, and the
  learner is trained again on everything collected
  ([arXiv:1011.0686](https://arxiv.org/abs/1011.0686)).

DART
: Noise is injected into the expert's actions while it demonstrates, so the
  data shows how to recover from small errors; the noise is tuned to the
  learner's error. On grasping in clutter it improved on behaviour cloning by
  62% on average ([arXiv:1703.09327](https://arxiv.org/abs/1703.09327)).

Causal confusion
: De Haan et al. find that a cloned policy can rely on a correlate of the
  expert's action instead of its cause, and fix it with targeted
  interventions, "either environment interaction or expert queries"
  ([arXiv:1905.11979](https://arxiv.org/abs/1905.11979), introduction only).

**Remedies that need a simulator but no expert.**

GAIL
: Learns a policy by playing in the environment against a discriminator that
  tells its behaviour from the expert's
  ([arXiv:1606.03476](https://arxiv.org/abs/1606.03476), abstract only). How
  many environment steps it needs was not checked here.

Spencer et al.
: Argue that the gap between held-out error and play "when conditioning
  policies on previous actions" is covariate shift, and that it can be
  mitigated "by taking advantage of a simulator but without any further
  querying of expert demonstration"; they also find naive behaviour cloning
  does well on the usual benchmarks
  ([arXiv:2102.02872](https://arxiv.org/abs/2102.02872), abstract only; the
  method was not read).

**Remedies that need neither.**

Conditioning on a plan (AlphaStar)
: From each replay AlphaStar extracts a statistic z: the first 20 buildings
  and units built, and which units, buildings, effects and upgrades were
  present during the game. The policy is conditioned on z in supervised
  learning (z set to zero 10% of the time) and in RL, where pseudo-rewards
  reward following a z sampled from human data
  ([Vinyals et al. 2019](https://www.nature.com/articles/s41586-019-1724-z),
  read in the
  [preprint](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)).
  TStarBot-X does the same and plays with either a zero z or one sampled from
  174 human replays ([arXiv:2011.13729](https://arxiv.org/abs/2011.13729)).

Sharper sampling
: AlphaStar Unplugged samples with a temperature at play time; 0.8 instead of
  1 raised the behaviour-cloning agent's win rate against the very_hard bot
  from 84% to 88% ([arXiv:2308.03526](https://arxiv.org/abs/2308.03526), Table
  4).

Less memory
: In the same paper a behaviour-cloning agent without memory beat one with an
  LSTM, 84% against 70% against very_hard, although its loss was higher
  ([arXiv:2308.03526](https://arxiv.org/abs/2308.03526), Table 3). Wen et al.
  name the "copycat" problem: policies given past observations can do worse
  than ones given one frame, because the past reveals the previous action and
  the policy learns to repeat it
  ([arXiv:2010.14876](https://arxiv.org/abs/2010.14876), introduction only).

Fine-tuning on better data
: Training on all games above MMR 3500 and fine-tuning on winning games above
  6200 gave 89% against very_hard, against 84% without fine-tuning and 65% for
  training on games above 6000 only
  ([arXiv:2308.03526](https://arxiv.org/abs/2308.03526), Table 2).

Rules on critical states
: TStarBot-X adds a loss that pulls the policy towards a hand-written expert
  on a small set of states "considered to be critical by human experts", in
  its RL stage ([arXiv:2011.13729](https://arxiv.org/abs/2011.13729)). No
  source found mixes a scripted fallback into an imitation policy at play
  time, as ADR 0019 does with BARb.

**The league.** AlphaStar's league and its later RL stages improve on
imitation by playing; they need the simulator at a scale far beyond ours
(TStarBot-X's imitation alone ran on 144 GPUs,
[arXiv:2011.13729](https://arxiv.org/abs/2011.13729)), and are not a remedy
for drift that Reason8 can use now.

**How drift was measured.** The StarCraft papers measure win rate against a
fixed bot and Elo among agents
([arXiv:2308.03526](https://arxiv.org/abs/2308.03526)); that measures
strength, not drift. Pearce and Zhu, cloning human Counter-Strike play,
compare where on the map the agent spends its time with where humans and the
built-in bot do, on a 60×60 grid, by earth mover's distance
([arXiv:2104.04258](https://arxiv.org/abs/2104.04258)). That is a drift
measure: the distribution of states the agent visits against the humans'.

### What transfers

- We have no expert to query: the humans of the replays cannot label the bot's
  states, and BARb is not the behaviour we imitate. DAgger, DART and the
  interventions of de Haan et al. do not apply.
- We have a simulator, but slow: about 5 game minutes per wall minute per
  engine. GAIL-style training needs the policy to play many games while it
  learns; with trees that cannot be updated by gradient, and with our
  throughput, it is not a first step (our reading).
- The remedies that need neither transfer directly:
  - ADR 0019 already samples only among answers of at least 10%, which, like a
    temperature below 1, cuts the unlikely tail where drift starts.
  - The order history is the copycat risk: the model's inputs include the
    units of the three previous steps and the counts ordered so far, and in
    the game those are the model's own earlier answers. The repeat baseline
    alone scores 32% top-1
    ([ADR 0013](../decisions/0013-evaluate-on-held-out-games.md)), so the
    trees can lean on it. Held-out accuracy does not show this; play does.
  - A plan in the style of z fits our data: from each training game, take a
    few facts about the player's opening (the first factory, the number of
    extractors by 3:00, whether they built a second factory), give them to the
    model as inputs, and in the game sample them from the human openings of
    that map and position. This is our proposal, not tested anywhere for
    trees. It needs care in evaluation: the plan is taken from the future of
    the same game, so a model given the true plan scores better on held-out
    games than it will play; it has to be scored with sampled plans as well.
- ADR 0003's classifier, which tells the bot's openings from human ones, is
  already a drift measure of the kind Pearce and Zhu use.

### Recommendation

1. **Measure first**, from the games the bot plays anyway
   ([ADR 0003](../decisions/0003-define-success-as-in-game-measures.md)):
   - the share of asks where no answer reaches 10% and BARb decides, by game
     minute: it rises as the bot drifts;
   - the log-likelihood, under the model, of the states-and-choices of the
     bot's games against that of held-out human games (the average probability
     the model gave to what was chosen, by minute);
   - the distance between the bot's state at fixed minutes (economy, units by
     type) and the human states of the same map and position, as Pearce and
     Zhu do for map positions;
   - the classifier of ADR 0003.
2. **Then try the cheapest change:** a model with a shorter history (the
   previous step only, or counts only) next to the one with three steps, both
   played. If the shorter one drifts less in the game while scoring slightly
   worse on replays, prefer it.
3. **Then a plan input**, sampled from human openings of the map and position,
   if drift remains.

## 2. Skill as an input

### What the sources did

AlphaStar Unplugged
: Passes the MMR of the player who made the trajectory as an input during
  training; "during inference, we can control the quality of the game played
  by the agent by changing the MMR input. In practice, we set the MMR to the
  highest value". No experiment in the paper varies it at play time. The same
  paper conditioned behaviour cloning on the game's result and "did not notice
  any difference, in fact the agent seemed to ignore the return conditioning"
  ([arXiv:2308.03526](https://arxiv.org/abs/2308.03526)).

AlphaStar (2019)
: Filters the data to MMR above 3500 (the top 22%) and fine-tunes on winning
  games above 6200
  ([preprint](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)).
  Whether the 2019 agent also takes MMR as an input was not verified: the
  paper does not say, and the supplementary pseudocode was not read.

Maia and Maia-2 (chess)
: Maia was nine separate models, one per rating band. Maia-2 is one model with
  skill as an input through a dedicated "skill-aware attention"; in its
  ablation, concatenating the skill encodings to the other inputs instead
  lowered accuracy from 52.74% to 51.75%
  ([arXiv:2409.20553](https://arxiv.org/abs/2409.20553), Table 3). Maia-2 also
  measures coherence: whether the probability of the right move rises steadily
  with skill. The original Maia models did so for 1% of positions, Maia-2 for
  27%.

Lux AI 2021
: A public imitation solution gave the model the identity of the agent to
  imitate as an input, so one model learned many agents; its author names it
  when asked for the most important trick, and it improved local validation
  ([ironbar/luxai](https://github.com/ironbar/luxai/blob/main/reports/05_Solution_Summary.md)).

### What transfers

- Nothing found tests skill as an input to boosted trees or on small data. The
  failure the sources show, the model ignoring the input (Unplugged's result
  conditioning), is likely with trees too: a tree uses skill only where
  splitting on it lowers the loss more than other features, and skill says
  less about the next build than the economy does (our reading).
- Two properties of trees matter when we set skill in the game (our reading):
  beyond the highest skill seen in training, the prediction stays as at that
  skill, so a value above the data gives nothing more; and the data is already
  filtered to lobbies above each map's median skill
  ([`dataset.md`](../reference/dataset.md)), so the range is narrow.
- Unplugged's filtering result points the other way from a hard filter:
  training only on the best games lost more from the smaller data than it
  gained (65% against 84%), and training on all with fine-tuning on the best
  won (89%).

### Recommendation

- Before relying on the skill input, **check it on the validation split**: the
  predictions for the same rows with skill set to the 10th and the 90th
  percentile should differ (average total variation distance between the two
  answers), the trees should split on it (feature gain), and log-loss by skill
  band should be better than that of the same model without skill. If skill
  barely changes the answers, either drop it or train per skill band, as Maia
  did.
- In the game, set skill to a high value **inside** the training range, not
  above it.
- Consider widening the skill filter once skill is an input, since the model
  can then tell the bands apart; Unplugged's numbers favour more data plus
  conditioning over fewer, better games. This touches ADR 0004 ("the data is
  filtered by skill") and the slice's filter.

## 3. Action masking

### What the sources did

Huang and Ontañón (microRTS)
: Masking invalid actions in policy-gradient training is justified in theory
  and matters more as the space of invalid actions grows. Agents trained with
  masking and played without it ("masking removed") still behaved "to some
  extent" but got worse as maps grew, mostly by choosing invalid units; an
  invalid-action penalty instead of a mask did not scale
  ([arXiv:2006.14171](https://arxiv.org/abs/2006.14171)).

Gym-µRTS
: Gives the agent a full mask over the unit to act, the action type and every
  parameter. A mask on the action type only had little effect; the full mask
  "considerably improves performance"
  ([arXiv:2105.13807](https://arxiv.org/abs/2105.13807)).

RAISocketAI (microRTS competition winner)
: Sets the logits of actions that are illegal "or would accomplish nothing" to
  a very large negative number, which zeroes their probabilities and
  gradients; it added walls and units' destinations to the mask. The authors
  cite Gym-µRTS's ablation, in which an agent won 82% with masking and 0%
  without ([arXiv:2402.08112](https://arxiv.org/abs/2402.08112)).

AlphaStar Unplugged, open-source code
: The pointer over which units act is masked to selectable units and the
  target unit to targetable ones; the action-type logits are not masked ("so
  the mask only contains ones"); the loss assumes masked logits are −∞ and
  sets the loss to zero where the human's action is masked, "the data is not
  consistent"
  ([`heads.py`, `supervised.py` at 700b1e7](https://github.com/google-deepmind/alphastar/tree/700b1e74364ed5dfc66f6cd2574c5ffac2fa474e/alphastar)).

TStarBot-X
: Gives the agent "masks encoding the game logic (e.g., after choosing a
  Zergling, 'Build' abilities are not available)"
  ([arXiv:2011.13729](https://arxiv.org/abs/2011.13729)).

Lux AI 2021
: The imitation solution trained its outputs with masked losses: the "act or
  not" output only where a unit could act, the action output only where it did
  ([ironbar/luxai](https://github.com/ironbar/luxai/blob/main/reports/05_Solution_Summary.md)).
  Whether it also masked at play time was not checked.

### What transfers

The evidence is for RL, where an unmasked agent wastes exploration on actions
that do nothing. In imitation the case differs (our reading):

- Every label in the replays is something the player's builder could do, so
  the model never learns to choose an impossible answer; it only spreads a
  little probability onto answers that never occur for that builder type.
  Masking at play time and renormalising removes that leak exactly; it is not
  the "masking removed" failure of Huang and Ontañón, which is training with a
  mask and playing without.
- What goes wrong when masking is applied only at play time is the
  bookkeeping: the probabilities the bot samples from are not the ones scored
  on replays, so a model chosen by log-loss
  ([ADR 0013](../decisions/0013-evaluate-on-held-out-games.md)) is not quite
  the model played, and the 10% threshold applies to different numbers. Both
  are fixed by applying the same mask when scoring.
- One model or one per builder type: XGBoost's multi-class objective builds
  one tree per class in each round (checked: 3 rounds on 5 classes give 15
  trees), so a model per builder type with only its own answers is smaller and
  faster to train, but each sees less data and the types cannot share what
  they have in common (the economy, the time). A custom objective that
  computes the softmax over the valid answers only, as AlphaStar's loss does
  with logits, is possible but not needed while the leak is small.
- What to mask: answers the builder can never give (outside its build list;
  for factories, the jobs they cannot do) are certain. Unaffordable answers
  are not impossible in BAR: anything can be started and is built as resources
  come in, and players do queue more than they can pay for, so the model's
  economy inputs should handle them, not a mask (our reading of the game).
  Unit limits and a job with no target in reach (nothing to reclaim or repair)
  are impossible at that moment and can be masked, since BARb would fail at
  them anyway.

### Recommendation

- **One model; at inference, zero the answers the asking builder cannot give
  and renormalise; then apply the 10% threshold.** Score validation and test
  log-loss with the same mask, and report how much probability the mask
  removes on average: if it is large for some builder type, train that type
  its own model.
- Mask impossibility (build list, builder kind, unit limits, no target), not
  cost.
- [ADR 0019](../decisions/0019-first-model-decides-each-builders-next-order.md)
  records the rule.

## 4. What the model sees of the map

### What the sources did

AlphaStar and Unplugged
: Three input modalities: a list of up to 512 units with 43 features each,
  eight 128×128 feature planes (height, visibility, ownership, pathable,
  buildable, …) and a vector of scalars (resources, supply, unit counts, game
  time, upgrades). The action is sampled argument by argument: action type,
  delay, queued and repeat from the vector, the acting units and the target
  unit by pointer networks over the unit list, and the target location from
  upsampled feature planes
  ([arXiv:2308.03526](https://arxiv.org/abs/2308.03526), section 4.2 and
  appendix A.1).

Gym-µRTS and RAISocketAI
: The map is a grid of feature planes; GridNet outputs an action for every
  cell at once, masked to the cells with own units, and a target is a
  direction or a relative position from the unit
  ([arXiv:2105.13807](https://arxiv.org/abs/2105.13807),
  [arXiv:2402.08112](https://arxiv.org/abs/2402.08112)). RAISocketAI's
  networks are convolutional and had to be shrunk for large maps to stay under
  100 ms.

Lux AI 2021
: A conditioned U-Net over 32×32 map features, with global features as the
  condition; per cell, whether the unit there acts and which of 10 actions
  ([ironbar/luxai](https://github.com/ironbar/luxai/blob/main/reports/05_Solution_Summary.md)).

Hand-written AIs
: All of them describe reclaim by aggregating it over a grid or zones (M28AI's
  reclaim segments per land zone, RNGAI's reclaim grid) and then choose among
  nearby candidates (section 5).

### What transfers

- Pointer networks and per-cell outputs need a network; trees cannot output a
  position or an index into a list of varying length.
- A pointer network scores every candidate and takes the best; trees can do
  the same if each candidate is a row (our proposal): for a builder about to
  reclaim, every wreck or reclaim cell within some radius is a row with its
  metal and energy, its distance or travel time from the builder, its distance
  from the base and from the front, the builders already on it, and later what
  the player could see of the enemy near it; the label is whether the player
  chose it. A binary classifier or XGBoost's ranking objectives fit this, and
  BARb can take the best-scored candidate as the target of its task. Placement
  works the same way, with candidate spots instead of wrecks.
- Players often reclaim an area with one order rather than one wreck. The
  candidates are then cells of a grid, as M28AI and RNGAI use, rather than
  single features.
- The state export does not record wrecks or other features yet
  ([`state-extraction.md`](state-extraction.md#not-recorded-yet)); the target
  model needs them first.

### Recommendation

For the next model (where to reclaim, resurrect, build), **rank candidates
with trees**: one row per candidate around the asking builder, local features
per candidate, the player's choice as the label. Keep the global inputs of the
first model on every row. Leave grids and pointer networks for when a network
replaces the trees.

## 5. How hand-written AIs choose builder jobs and targets

### BARb (CircuitAI)

Read at
[`f4a6ca3`](https://github.com/rlcevg/CircuitAI/tree/f4a6ca3ae096631894e194cfa9b4e8e53f4fb78c),
the commit the pinned engine tag uses (`ai/native/build.sh`). Zero-K's AI is
built from the same codebase; its branch was not read separately.

Choosing a job (`CBuilderManager::MakeBuilderTask`)
: An idle builder first assists a factory if the factory asks for help, the
  builder is within 600 of it and there are resources for about 8 seconds of
  the faster build (`CEconomyManager::CheckMobileAssistRequired`). Otherwise
  it takes the task of the pool with the lowest travel cost × 1/(priority+1)²,
  skipping tasks it cannot do, cannot reach, or that are threatened beyond the
  builder's own power where enemy influence outweighs ours, and, while the
  economy stalls, tasks that are not urgent. A far task to finish or repair a
  unit is taken only if the health still missing is worth the travel time.

Reclaim and resurrect targets (`CEconomyManager::UpdateReclaimTasks`)
: Created in two places: when the economy looks for metal tasks and finds no
  extractor to build, among the features within 20 to 60 seconds of the
  builder's travel; and when an idle builder finds nothing else to do, among
  all features on the map. Either way only while metal storage is not full and
  fewer reclaim tasks exist than half the builders, and it takes the
  **nearest** feature that is reachable and safe and holds at least 1 metal;
  resurrectors take the nearest resurrectable one. While reclaiming, the task
  re-targets to the nearest such feature within 500, and reclaims enemy units
  that are not armed (`CBReclaimTask::Reevaluate`).

Repair
: A repair task is queued when a building is damaged (high priority) or a
  builder is started (normal). Unfinished buildings left alone are repaired if
  the rest fits in a time budget set by income and build power, and reclaimed
  otherwise.

Assist when idle (`CBuilderManager::CreateBuilderTask`)
: With nothing else to do: energy, reclaim, a "big gun" if income allows, then
  guard the closest factory (or army leader), then the commander, then patrol.

### FAF: M28AI and RNGAI

M28AI
: Read at
  [`59217e9`](https://github.com/maudlin27/M28AI/blob/59217e902015d5fd86e2dee1711b9c73a2a50f83/lua/AI/M28Engineer.lua).
  Per land or water zone, a long ordered list of conditions assigns an amount
  of build power to each action
  (`HaveActionToAssign(action, tech level, build power wanted)`); the priority
  counter is raised 247 times in the file. For reclaim
  (`GetEngineerToReclaimNearbyArea`) the map is cut into reclaim segments; a
  builder takes the segment with the lowest modified distance, where the
  distance grows with the builders already assigned to a segment of a zone
  whose reclaim is less than 200 mass per builder. Segments with "significant"
  reclaim (a threshold of 10 in the code) are preferred: their distance is
  halved when the zone has a little of it, and when it has 500 mass or more
  only such segments are considered. In the segment it takes the nearest wreck
  above a minimum value that no other builder is reclaiming, unless it is
  worth more than 150.

RNGAI
: Read at
  [`309636e`](https://github.com/relent0r/RNGAI/tree/309636e30f3af1ca83352ae2f6e4f0538b08a51b/lua/AI).
  Jobs come from builders with priorities and conditions, FAF's builder
  framework. The reclaim job's priority is computed from the reclaim grid: 900
  when more than 500 mass lies within a radius of the base and builders are
  wanted, 700 above 250, otherwise 0; the job also needs a rising energy trend
  and storage below a set ratio (`ReclaimMassInRadiusPriority` and the
  builder's conditions in `RNGAIEngineerBuilders.lua`). The first reclaim at
  the start takes the most valuable wreck, later ones the nearest; general
  reclaim considers wrecks of at least 5 mass in a box around the builder, and
  paths that cross too much threat are refused
  (`platoon-engineer-reclaim.lua`).

M27AI was not read.

### BAR's STAI

STAI was removed from BAR on 2026-06-19
([`3ad8f3f`](https://github.com/beyond-all-reason/Beyond-All-Reason/commit/3ad8f3fb592f8ebacf892926b3f4d83b41bd6023));
read at its parent
[`2ac74f8`](https://github.com/beyond-all-reason/Beyond-All-Reason/tree/2ac74f81d27cb07342d1906c940fd3f3c75595ea/luarules/gadgets/ai/STAI).
Reclaimers give one area-reclaim order of radius 10,000 around themselves and
leave the choice to the engine (`reclaimbst.lua`). Assisting units guard a
builder of the right role, up to a cap per builder (`engineerbst.lua`).
"Cleaners" reclaim their own obsolete buildings within 390 when metal storage
is below half and the team has more than two fusion reactors
(`cleanerbst.lua`).

### What transfers

- The AIs that choose a reclaim target do so mainly by **distance**, filtered
  by a **minimum value**, **reachability** and **danger**, and two of them
  (M28AI, RNGAI) by how many builders are **already there**. None models where
  the fight will be, which is what ADR 0019 says matters on maps like Supreme
  Isthmus.
- BARb reclaims late: only when no other task fits. A model that answers
  "reclaim" often will hand BARb a job it handles with its simplest rule, the
  nearest wreck anywhere on the map; the bot may send builders far.
- The features of section 4 follow from this list: value, distance, danger,
  builders already assigned, and the team's metal storage.

### Recommendation

Until the target model exists, watch how far BARb sends builders on reclaim
jobs the model asked for (distance travelled, time spent, builders lost), and
if it is far, restrict the job to wrecks within a radius around the builder,
as BARb already does in its other call (`isNear`). Use value, distance, threat
and builders already assigned as the first candidate features.

## What the records took from this

[ADR 0019](../decisions/0019-first-model-decides-each-builders-next-order.md)
states the mask, the check that keeps skill as an input, the measures of drift
and the test with a shorter order history. This doc keeps the evidence for
them.

Still proposals:

- **The slice's skill filter:** consider training on a wider skill range and
  conditioning on skill, as AlphaStar Unplugged's results favour.
- **A new record when the target model is decided:** targets and placements as
  candidates ranked by trees.

## Sources not read in full

- *Abstract only:* GAIL
  ([arXiv:1606.03476](https://arxiv.org/abs/1606.03476)), Spencer et al.
  ([arXiv:2102.02872](https://arxiv.org/abs/2102.02872)).
- *Introduction only:* de Haan et al.
  ([arXiv:1905.11979](https://arxiv.org/abs/1905.11979)), Wen et al.
  ([arXiv:2010.14876](https://arxiv.org/abs/2010.14876)).
- *Not read:* AlphaStar's supplementary pseudocode (so whether the 2019 agent
  took MMR as an input is not verified), M27AI, Zero-K's CircuitAI branch,
  DI-star, the Lux AI Season 2 and 3 winners and the Kaggle discussion
  threads.
