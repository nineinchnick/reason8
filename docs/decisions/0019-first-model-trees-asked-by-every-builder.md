# 0019. First model: trees that every builder asks, played live

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

The bot plays whole human openings chosen before the game and compiled into a
table ([ADR 0007](0007-ship-the-model-as-tables-in-a-barb-variant.md)). It
plays them from top to bottom whatever happens in the game.

What we measured and built since:

- The state of the game predicts the next order better than the order history
  alone: the team's economy, its own units and the game time add one to three
  points of top-1 each over trees on the history, and trees trained on a few
  hundred games match the n-gram trained on the whole dataset
  ([`context.md`](../research/context.md), preliminary).
- Our build of BARb's library gives the scripts the live state and holds the
  bot to the action budget ([ADR 0008](0008-play-under-human-like-limits.md)),
  so a model can be asked during the game.
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

The first learned model is asked during the game what a builder does next.

- **What it decides:** the next order of any unit with build power: the
  commander, factories, construction units, build towers and the others. A
  builder asks when it has nothing to do. The model is told what kind of
  builder asks.
- **Its answers:** a unit to build, or a job without a target: assist,
  reclaim, repair or resurrect.
- **Its inputs:** the order history, the map and start position, the game
  time, the team's economy, its own units finished and under construction, its
  build power (the asking builder's and the team's), and the skill of the
  player. In the game the skill is a number we choose. The allies and the wind
  are left out.
- **The model:** gradient-boosted trees, written to a data file that the
  library evaluates with its own code, without a runtime. The list of inputs
  and the form of the answer are kept independent of trees, so that a network
  can take their place.
- **Possible answers only:** the answers the asking builder can never give (a
  factory cannot reclaim, a builder builds only its own list) are removed and
  the rest rescaled to sum to one. What a team cannot afford stays: the game
  lets a player start anything. Models are scored on replays with the same
  mask, so that the model chosen there is the one that plays.
- **Choosing from the answer:** after the mask, the bot samples among the
  answers with a probability of at least 10%. When no answer reaches the
  threshold or the chosen one cannot be carried out, BARb decides.
- **Skill stays an input only if the model uses it:** on held-out games the
  predictions must change between low and high skill and the fit per skill
  band must improve. In the game it is set high but inside the range seen in
  training, because trees answer the same for every value above it.
- **Where:** metal extractors go to the metal spots in the order players
  usually take them from that map and start position; BARb places every other
  structure and picks the target of every job.
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
- In the game the order history is the model's own earlier answers, and a
  model can learn to repeat them: repeating the last order is right for 32% of
  steps. A model with a shorter history is played next to the full one to see
  whether it drifts less.
- The account's rating is a weak label of skill. A measure of how well someone
  played, taken from their actions in the game, would be a better input and a
  better way to choose training games; it has to be found.
- The decision table has to give every order its builder and its build power,
  hold the jobs next to the build orders, and carry the skill. It can only do
  that for re-simulated games, so the amount of training data is the number of
  games played again, and more have to be.
- The usual order of metal spots exists only for maps and positions with data.
  Elsewhere BARb places extractors too.
- The library needs an evaluator for trees and a way for every builder to ask,
  and the action budget now covers all builders' orders.
- Where to build, and what to assist, reclaim or resurrect, are the next
  decisions to learn. They need the model to see the map around the builder.
  Reclaim and resurrection set new players apart from experienced ones, and
  some maps put their most valuable metal where teams fight for it, so the
  target matters more than for other jobs.
- Playing past first contact needs line of sight per ally team in the state
  export, and a finer notion of contact than one frame: a scout seeing or
  being seen, a raid on economy buildings, an allied raid that goes around the
  enemy's defences, a fight over a choke point. Until then the model does not
  direct contested reclaim.
- Revisit the model when a network clearly beats the trees on the decision
  table, and the hand-over when the state export records visibility.
