# 0019. First model: trees that decide each builder's next order, played live

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

The bot plays whole human openings chosen before the game and compiled into a
table ([ADR 0007](0007-ship-the-model-as-tables-in-a-barb-variant.md)). It
plays them from top to bottom whatever happens in the game.

What we measured and built since:

- The state of the game predicts the next order better than the order history
  alone. On held-out games of the 2,996 re-simulated ones, trees on the order
  history get the next order right 56.0% of the time, 60.5% when told which
  builder the order is for, and 63.8% with the inputs of this record
  ([`results.md`](../results.md), [`context.md`](../research/context.md)).
- Our build of BARb's library gives the scripts the live state and holds the
  bot to the action budget ([ADR 0008](0008-play-under-human-like-limits.md)),
  so a model can be consulted during the game.
- The commands say which units each order went to, and the re-simulated games
  say what those units are, so an order can be given to the builder that got
  it. The unit definitions have every builder's build power.
- The decision table holds build orders only, without the builder, and nothing
  about the enemy or what a player could see
  ([ADR 0018](0018-learn-from-orders-joined-with-the-state-before-them.md)).

Everything with build power takes the same kinds of orders, with differences a
model has to know: factories cannot move, reclaim or assist; construction
units build a few things; some other mobile units build specialised units and
structures; the commander has more build power and health; build towers can be
carried by air. Build power is a resource like metal and energy: what a team
can do with its income depends on it.

What others did with the same problems is in
[`builder-model-prior-work.md`](../research/builder-model-prior-work.md): no
source shows that setting a skill input changes how a model plays, a model fed
its own earlier answers can learn to repeat them, and the usual remedies for
drift need an expert to ask, which we do not have.

The skill we have is a rating of the account. Many things move it besides how
a person plays, it can be gamed, and an experienced player on a new account
starts low.

## Decision

The first learned model decides during the game what a builder does next. The
bot stays one player: like a person who notices an idle builder and gives it
an order, it consults one model, which sees the whole team's state, each time
a builder has nothing to do. The builder is what the decision is about, not
who makes it.

- **What it decides:** the next order of any unit with build power: the
  commander, factories, construction units, build towers and the others. The
  decision is made when a builder has nothing to do. The model is told what
  kind of builder the order is for.
- **Its answers:** a unit to build, or a job without a target: assist,
  reclaim, repair or resurrect.
- **Its inputs:** the order history, the map and start position, the game
  time, the team's economy, its own units finished and under construction, its
  build power (the idle builder's and the team's), and the skill of the
  player. In the game the skill is a number we choose. The allies and the wind
  are left out. The first version also has three inputs that mean something
  else for the bot than for a player: how many orders the player gave before,
  how many jobs of each kind, and the build power of the idle builders. A
  player's counts grow with every building of a drag and every reclaim of a
  feature their widget sends, while the bot gives one order per decision; and
  the builder an order is for is idle at every decision of the bot but at few
  of the players' orders. Leaving the three out costs 0.1 point of top-1 and
  0.006 nats on held-out games
  ([`context.md`](../research/context.md#inputs-the-game-cannot-give-exactly)),
  so the models trained on the rebuilt decision table leave them out. The
  first version keeps them, the library giving its best approximation of each,
  so that the bot can be wired with it before that training.
- **The model:** gradient-boosted trees, written to a data file that the
  library evaluates with its own code, without a runtime. The list of inputs
  and the form of the answer are kept independent of trees, so that a network
  can take their place.
- **Possible answers only:** the answers the idle builder can never carry out
  (a factory cannot reclaim, a builder builds only its own list) are removed
  and the rest rescaled to sum to one. What a team cannot afford stays: the
  game lets a player start anything. Models are scored on replays with the
  same mask, so that the model chosen there is the one that plays.
- **Choosing from the answer:** after the mask, the bot samples among the
  answers with a probability of at least 10%. When no answer reaches the
  threshold or the chosen one cannot be carried out, BARb decides. An order
  cannot be carried out when it cannot be given or its task ends within a
  second; that answer is then held back for that builder for 30 s of game
  time, so that the bot does not give the same order again while nothing
  changed. The model is consulted only for an idle builder.
- **Skill stays an input only if the bot plays better with it:** on held-out
  games the predictions must change between low and high skill and the fit per
  skill band must improve; a model that passes is then played with and without
  skill, and skill stays when the in-game measures
  ([ADR 0003](0003-define-success-as-in-game-measures.md)) are better with it.
  The replay test alone does not decide, because it passes only narrowly and
  the rating is a weak label. In the game skill is set high but inside the
  range seen in training, because trees answer the same for every value above
  it.
- **Where:** metal extractors go to the metal spots in the order players
  usually take them from that map and start position, of those near the bot's
  own start, else to the free spot BARb would take next; a builder ordered a
  structure of a type the team is building already helps build it instead (a
  factory anywhere, another structure near the builder); BARb places every
  other structure and picks the target of every job, the way its own tasks do
  for that job.
- **Until when:** first contact
  ([ADR 0012](0012-end-openings-at-first-contact.md)), then BARb plays on.

## Consequences

- The bot can leave what any human played. One unusual choice leads to a state
  no player was in, and the choices after it get worse. Sampling only among
  likely answers and falling back to BARb limit this; how far the bot's games
  drift from human ones has to be measured from its games: how often it falls
  back to BARb by game minute, how likely the model finds the bot's own
  choices compared with held-out human games, how far the bot's state is from
  human states at fixed minutes, and the classifier of
  [ADR 0003](0003-define-success-as-in-game-measures.md).
- In the game the order history is the model's own earlier answers that were
  carried out (their task lasted a second), with BARb's orders to the builders
  left to it, and a model can learn to repeat them: repeating the last order
  is right for 32% of steps. A model with a shorter history is played next to
  the full one to see whether it drifts less.
- The account's rating is a weak label of skill. A measure of how well someone
  played, taken from their actions in the game, would be a better input and a
  better way to choose training games; it has to be found.
- The decision table has to give every order its builder and its build power,
  hold the jobs next to the build orders, and carry the skill. It can only do
  that for re-simulated games, so the amount of training data is the number of
  games played again, and more have to be.
- The usual order of metal spots exists only for maps and positions with data.
  Elsewhere BARb places extractors too.
- The library needs an evaluator for trees and has to consult the model for
  every idle builder, and the action budget now covers all builders' orders.
- Where to build, and what to assist, reclaim or resurrect, are the next
  decisions to learn. They need the model to see the map around the builder.
  Reclaim and resurrection set new players apart from experienced ones, and
  some maps put their most valuable metal where teams fight for it, so the
  target matters more than for other jobs.
- Playing past first contact needs line of sight per ally team, which state
  format 7 records, re-simulated games that have it, and a finer notion of
  contact than one frame: a scout seeing or being seen, a raid on economy
  buildings, an allied raid that goes around the enemy's defences, a fight
  over a choke point. Until then the model does not direct contested reclaim.
- Revisit the model when a network clearly beats the trees on the decision
  table, and the hand-over when re-simulated games record visibility.
