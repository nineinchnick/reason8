# 0008. Play under human-like limits

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

An AI can win by seeing everything or acting faster than any person, which
makes it neither a fair opponent nor a good teammate. AlphaStar is the main
lesson here. Imitation of humans also only makes sense if the bot acts on the
same information people have.

People also spend their actions carefully. One drag of the mouse places a
whole line of buildings, and about half of the build orders in a replay repeat
the order before them in the same frame
([`openings-dataset.md`](../reference/openings-dataset.md)).

How fast people act is measured on every game of the slice in
[`apm.md`](../research/apm.md), counting actions the way BAR's own APM gadget
does: at most one per frame, and a command counts only if one of its units got
no command in the 7 frames before. Measured there:

- A player-minute has a median of 13 clicked actions (p90 34) and of 36 when
  the commands of the player's widgets are added (p90 80); the second figure
  is close to the APM BAR shows in game.
- Skill doubles the rate: averaged over a game, the median player clicks 11
  actions a minute below skill 10 and 24 at 40 and up (25 and 56 with
  widgets).
- Short bursts barely depend on skill: the most clicked actions in any 10
  seconds of a game has a p90 of 22 to 23 in every band, and of 35 to 50 with
  widgets; in any second, a p90 of 9 to 11 with widgets.
- The first two minutes are the quietest: a p90 of 26 to 48 actions a minute
  with widgets, depending on skill.

## Decision

The bot plays under the same limits as people: only what it can see, human
command rates (including bursts), reaction time and limited attention. It
should win by decisions, not by speed or extra information. This holds for
every milestone, including any later reinforcement learning.

The command rate is an action budget, counted the way a player spends it and
the way BAR counts it: at most one action per frame, and a command counts only
if at least one of its units got no command from the bot in the 7 frames
before. Batching orders, such as dragging a line of buildings or queueing with
shift, is one action, and the bot learns to batch where players do. Every
command the bot sends counts, so the comparable human figure is the one with
widget commands (`all` in [`apm.md`](../research/apm.md)), and BAR's in-game
APM is a check on it.

The bot plays at a chosen skill band, and its actions must stay within every
window of that band's row at all times:

| skill band | any 1 s | any 10 s | any 60 s | any 60 s, first 2 min | game average |
| ---------- | ------: | -------: | -------: | --------------------: | -----------: |
| below 10   |       9 |       35 |       50 |                    25 |           25 |
| 10-20      |      10 |       40 |       65 |                    30 |           30 |
| 20-30      |      11 |       50 |       80 |                    35 |           40 |
| 30-40      |      11 |       50 |       90 |                    40 |           50 |
| 40 and up  |      11 |       50 |      100 |                    50 |           55 |

These limits are our recommendation, rounded from the measurements: the 1 s
and 10 s caps are the p90 of the most actions a player takes in that window of
a game; the 60 s caps are the p90 of actions per minute over the whole game
and over its first two minutes; the game average is the median of a player's
average over the game, kept over any 5 minutes as a running budget. A bot that
keeps to them acts like a busy player of its band, not like its fastest
moment.

## Consequences

- Game state used for training has to be what the player could see, not the
  spectator's full view (line of sight per ally team).
- The in-game side needs explicit limits on command rate and reaction time:
  the windows above, enforced on every command the bot sends.
- Evaluation must check that the bot stays within these limits, counting its
  commands in its replays the same way (`reason8.analysis.apm.ActionCounter`;
  the `analysis apm` command itself leaves out games with bots).
- Models predict a step (one drag or click), and how many orders a step holds
  is learned separately, as part of the action budget.
- BARb already sends commands that a person would leave to widgets (formation
  moves, queue clean-up). They count against the budget, as widget commands
  count in the measured figure.
- Revisit the numbers if the counting changes (BAR's gadget or the parser), if
  a check against BAR's own in-game APM shows `all` to be off, or if the bot
  turns out unable to play at all within its band's budget.
