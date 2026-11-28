# Holding commands under the action budget

The bot has to stay within a strong player's action budget
([ADR 0008](../decisions/0008-play-under-human-like-limits.md)), and BARb's
library sends far more: 400 to 3,000 commands a minute
([`in-game.md`](../reference/in-game.md#command-rate)). A first governor in
our build of the library dropped the commands over the budget, 45% of them,
with BARb believing they were given
([`in-game.md`](../reference/in-game.md#a-command-governor)). This document
measures the governor that holds them instead and sends them later, and the
live state the same library gives the scripts, and what one action holds. How
it works is in [`in-game.md`](../reference/in-game.md#our-barb-library); code:
`ai/native`, `reason8/bot/budget.py`, `reason8/bot/live_state.py`,
`reason8/analysis/orders.py`.

## Summary

The governor keeps the bot within its action budget and loses no command, but
counting the commands of a frame as one action let one action hold far more
than a player's: in games played in real time a counted action of the bot held
4.8 kinds of order and 9.9 different orders on average, where 99.4% of a
player's clicked actions give one kind of order (89.6% with their widgets). So
ADR 0008 now counts each kind of order in a frame as one action, and the
governor counts that way. In a first game under that rule the budget still
holds and nothing is lost, but the bot's commands wait longer: 82% of them are
held (three quarters before), up to 11.5 s (2 s before), and a third are
replaced by a newer order while they wait. What that costs in play is not yet
measured.

What to use from here: the governor's log as the measure of the budget (a
headless replay records the bot's commands late and overcounts its actions,
now by 12 to 25%), the evidence that one action is one kind of order
([What one action holds](#what-one-action-holds)), and the holding numbers of
[Under the count by kind of order](#under-the-count-by-kind-of-order) as the
baseline for the paired games that measure the effect on play.

## Method

Library
: CircuitAI at the engine's BARb commit with `ai/native`, built by
  `reason8 bot build` for engine `recoil_2026.09.03`. Game
  `Beyond All Reason test-32018-ad135b9`, Supreme Isthmus v2.1.

Budget
: The 30-40 band of ADR 0008: at most 11 actions in any second, 50 in any 10
  s, 40 in any minute of the first two and 90 in any later minute, and 250 in
  any 5 minutes.

What is counted
: The governor logs, per team and minute, the commands the AI gave (`seen`),
  sent at once, held and sent later, replaced while held by a newer order to
  the same unit (`collapsed`), dropped, and refused by the engine after being
  held (`failed`), the worst delay, and the frame of each action it sent.
  `reason8 bot check` reads the log, checks that every command is accounted
  for, and counts the logged actions in every window of the budget again. It
  also counts each team's commands in the replay as actions, the way a
  player's are (`reason8.analysis.apm.ActionCounter`).

## Holding without pacing

The first version sent a held command as soon as one more action fitted every
window. `test_budget.cpp` feeds it a command to one of 40 units every other
frame for 10 minutes, about 900 a minute.

| version | actions | most held | longest wait | dropped |
| ------- | ------: | --------: | -----------: | ------: |
| greedy  |     500 |     1,024 |         68 s |   1,170 |
| paced   |     431 |        29 |        1.9 s |       0 |

Of 9,000 commands in each run.

- **Greedy spending stalls.** It took a window's whole cap in a few seconds
  (11 a second until the minute's 40 were gone, about 20 s into each of the
  first two minutes) and then had to wait out the rest of the window; once the
  5-minute budget was spent it waited over a minute at a time, the queue
  filled and the oldest commands were dropped.
- **Pacing fixes it.** Each window also has a bucket of a quarter of its cap
  that refills at the rate that spends the rest evenly over the window, and an
  action needs a token from every bucket. Under the same load the governor
  then acts every second or two, holds at most 29 commands and none for more
  than 2 s. It takes fewer actions (43 a minute against the 50 the 5-minute
  window allows on average) and is never stopped by a full window.

## One game

Reason8 (Armada) on our library against stock BARb, 5 game minutes, seed 1,
one AI a side (`ai_vs_ai.txt`). `reason8 bot check` passed for the governor
and the opening was played in order (20 steps, 12 done in 5 minutes).

| minute | seen | sent at once | sent later | collapsed | actions | worst delay |
| -----: | ---: | -----------: | ---------: | --------: | ------: | ----------: |
|      1 |   89 |           49 |         35 |         5 |      31 |       1.9 s |
|      2 |   98 |           22 |         58 |        18 |      29 |       2.0 s |
|      3 |  160 |          103 |         51 |         2 |      88 |       0.8 s |
|      4 |  189 |           28 |        139 |        22 |      48 |       1.4 s |
|      5 |  341 |           39 |        250 |        50 |      38 |       1.6 s |

- **Nothing was lost.** Of 877 commands, 774 were sent (533 of them after
  being held), 97 were replaced by a newer order to the same unit while held
  and 6 were still held when the game ended. None was dropped; 10 held
  commands were refused by the engine because their unit was gone.
- **Every window held.** At most 6 actions in a second, 25 in 10 s, 37 in a
  minute of the first two, 89 in a later minute, 234 in the 5 minutes.
- **Holding is short.** The longest wait was 59 frames (2 s).

## In team games

Twenty 8v8 games of
[`evaluation.md`](../reference/evaluation.md#our-barb-library): 10 seeds, each
played twice with the sides swapped, eight Reason8 teams on our library
against eight on the engine's library (`Reason8Stock`, the same scripts and
openings), 8.5 game minutes, with the current openings. Every team-game below
is one team of one game, 160 per AI.

Commands and actions per team-game, counted in the replays the same way for
both:

| per team-game, median (most) | engine's library |      ours |
| ---------------------------- | ---------------: | --------: |
| commands a minute            |        168 (711) | 157 (456) |
| actions a minute             |         94 (269) |   36 (46) |
| most actions in 1 s          |          11 (21) |    6 (10) |
| most actions in 10 s         |         60 (133) |   24 (34) |
| most in 60 s, first 2 min    |         19 (151) |   20 (41) |
| most in any later 60 s       |        243 (689) |   87 (95) |
| most in 5 min                |      708 (1,977) | 249 (264) |

Within every window of the budget: 29 of 160 team-games on the engine's
library, 81 of 160 on ours (see
[The replay as a check](#the-replay-as-a-check)).

The governor's own log, summed over the 160 team-games of our library:

| commands                               |   count |
| -------------------------------------- | ------: |
| given by the AI (`seen`)               | 248,827 |
| sent at once                           |  65,528 |
| held, then sent                        | 162,583 |
| replaced while held (`collapsed`)      |  19,866 |
| dropped                                |       0 |
| still held at the end                  |     850 |
| refused by the engine after being held |     925 |

- **The budget holds and nothing is lost.** `reason8 bot check` passed the
  governor of all 160 team-games: every command accounted for, none dropped,
  every window kept. The most actions in any window were 10 in a second, 33 in
  10 s, 39 in a minute of the first two, 89 in a later minute and 249 in 5
  minutes, against caps of 11, 50, 40, 90 and 250.
- **Holding is short.** The longest wait in a team-game was 47 frames at the
  median and 59 (2 s) at most.
- **The commands are about as many; the actions are a third.** BARb gives
  about as many commands as before: the governor replaces 8% of them while
  held, and sends most of the rest in batches, a frame at a time, which by the
  counting rule of ADR 0008 is one action. Three quarters of the commands were
  held at least a frame.
- **The engine's library is far over the budget.** Without the governor a
  Reason8 team took 94 actions a minute at the median, up to 689 in a minute
  and 1,977 in 5 minutes.
- **It costs nothing measurable in play.** At 4:00 the teams on our library
  had built 99.0% (97.4%–100.5%) of the metal value of those on the engine's,
  and their openings were in order a little less often (108 against 124 of
  160).

## The replay as a check

Counted from the replay, our library's teams kept every window in 81 of 160
team-games; the worst had 95 actions in a minute (cap 90) and 264 in 5 minutes
(cap 250). The governor's log for the same teams has at most 89 and 249.

The difference is in the replay's frames. A headless game runs several times
faster than real time, and the replay records an AI's commands when the server
handles them: 12 to 30 frames after the governor sent them, and unevenly.
Commands the governor sent in one frame, one action, land in different frames
of the replay and count as two; a command just outside a unit's 7 frames moves
inside or out. In the first game, the replay had 332, 319 and 85 actions for
three teams whose governors sent 330, 315 and 83.

So `reason8 bot check` judges the budget by the governor's log, which records
the frame each command left the AI, and reports the replay's count next to it.
In the two games played in real time the replay records the commands of an
action in the frame the governor sent them (one game) or 4 to 5 frames later
(the other), and the counts agree within 1.2%
([What one action holds](#how-it-is-counted)).

## The live state

The opening script logged the live state 5,308 times in the 20 games, at every
commander step and every 30 s. Each line is compared with the state export of
the same game (the host's widget, `Spring.GetWind` and
`Spring.GetTeamResources`), the last resource line within a second before it.
Medians over the teams of the per-team median difference:

| value          | median difference | most (a team's median) |
| -------------- | ----------------: | ---------------------: |
| wind           |             0.019 |                  0.102 |
| metal stored   |               2.1 |                    7.5 |
| metal storage  |                 0 |                      0 |
| metal income   |             0.002 |                  0.013 |
| metal expense  |             0.018 |                  0.036 |
| energy stored  |               6.9 |                     35 |
| energy storage |                 0 |                    0.5 |
| energy income  |              0.15 |                   0.36 |
| energy expense |              0.15 |                   0.35 |

- **The values are the game's.** The differences are what changes in the up to
  29 frames between the export's line and the script's, and the export's
  rounding (wind to 0.01, energy to whole numbers): stored energy moves by
  tens a second, the wind by a little every frame.
- **The units standing** matched the last snapshot exactly in 3,315 of the
  5,308 lines (62%); the snapshot is written every 5 s, and a unit finished
  since it is the usual difference.

## What one action holds

ADR 0008 counts the commands of one frame as at most one action, which fits a
player: one click on 20 selected units is 20 commands in one frame. The
governor uses the same rule: when one action fits the budget it sends every
command it holds in that frame, to any number of units, with any mix of
orders. This section measures what one counted action holds for players and
for the bot. Code: `reason8/analysis/orders.py`.

```sh
uv run reason8 analysis orders --every 16 --jobs 1 --out data/orders
uv run reason8 analysis orders --out data/orders \
    --bot lobby=data/runs/lobby-2026-11-27 --bot lobby=data/runs/lobby-2026-11-28 \
    --bot headless=data/eval/end-opening/after
uv run reason8 analysis orders --out data/orders --report
```

### How it is counted

Order
: A command with its unit to build, parameters and options (and, for an
  INSERT, its position and options), without the units it goes to. One click
  to a selection is one order; a dragged line of ten buildings is ten; a
  formation move, which gives each unit its own spot, is one order per unit.

Kind
: An order without its parameters: the command, unit to build and options. A
  line of one building is one kind, and so is a formation move; a `MOVE` and a
  shift-queued `MOVE` are two, as they are two clicks.

Action
: A frame that counts as an action under the rule ADR 0008 had then, one
  action a frame (`reason8.analysis.apm.ActionCounter` without kinds),
  counting either only the player's clicked commands (`COMMAND` packets, to
  the current selection) or all of their commands, widgets' included (`all` in
  [`apm.md`](apm.md), the figure the budget is drawn from). Every number below
  is per action and counts the commands of the action's frame, clicked ones
  only or all.

Action span
: An action and the commands of the frames after it until the next action:
  what the 7-frame rule lets through for free. It adds little on either side
  (below), so the tables use the action's frame.

Players
: Every 16th day of the tables (13 days from 2025-12-10 to 2026-11-17), the
  games without bots: 2,879 games, 46,060 player-games, 20.9 million clicked
  actions and 54.3 million actions with widgets. Intervals are 95% bootstrap
  intervals over games.

Bot
: The governed Reason8 teams of two lobby games played in real time on Supreme
  Isthmus (a 3v3 with five Reason8 teams, 24.7 minutes, and a game with three
  Reason8 teams and four of stock BARb, which has no governor), 8 team-games
  in all, and the 20 headless 8v8 games of the comparison with `BARbLimited`
  with the opening's new ends
  ([`evaluation.md`](../reference/evaluation.md#our-barb-library)), 8.5
  minutes, 160 team-games of each AI. The bot's commands come from the
  replays, and its intervals are bootstrap intervals over team-games.

The governor's log records the frames of its actions, not the commands of
each, so the bot's actions are counted in the replay. In the lobby games that
is exact: in the second game every action of the replay is at a frame the
governor logged (3,825 replay actions for 3,822 logged), and in the first 95%
are 4 or 5 frames after one (3,894 for 3,847). In the headless games the
replay scatters the commands of one action over up to 30 frames
([The replay as a check](#the-replay-as-a-check)), which splits a flush into
several smaller ones: their numbers are a lower bound. The governor's own
totals give commands per action without frames: 5.1 in the headless games
(pooled; team-games 1.6 to 13.0), 20.4 in the lobby games (3.1 to 42.6).

### Players

| per counted action               |          n |         commands |      unit orders |  distinct orders | more than one order | more than one kind | p90 | p99 |
| -------------------------------- | ---------: | ---------------: | ---------------: | ---------------: | ------------------: | -----------------: | --: | --: |
| clicked commands                 | 20,899,661 | 1.51 (1.50–1.52) | 6.16 (6.04–6.27) | 1.50 (1.49–1.51) |      4.8% (4.7–4.9) |     0.6% (0.6–0.6) |   1 |  14 |
| all commands                     | 54,301,788 | 5.32 (5.23–5.41) | 7.09 (6.98–7.21) | 4.65 (4.59–4.72) |   40.2% (40.0–40.5) |  10.4% (10.2–10.5) |  10 |  50 |
| all commands, with the free ones | 54,301,788 | 6.37 (6.27–6.49) | 9.59 (9.45–9.73) | 5.51 (5.44–5.58) |   48.9% (48.7–49.0) |  13.1% (12.9–13.2) |  12 |  60 |

Unit orders are commands times the units each goes to. p90 and p99 are of
distinct orders.

Distinct orders per action:

| per counted action | 1     | 2    | 3-5   | 6-10 | 11-20 | more |
| ------------------ | ----- | ---- | ----- | ---- | ----- | ---- |
| clicked commands   | 95.2% | 1.2% | 1.3%  | 1.0% | 0.7%  | 0.6% |
| all commands       | 59.8% | 9.6% | 13.1% | 7.9% | 5.9%  | 3.6% |

Distinct kinds per action:

| per counted action | mean | one kind | at most 2 | at most 3 | p99 | p99.9 |
| ------------------ | ---: | -------: | --------: | --------: | --: | ----: |
| clicked commands   | 1.01 |    99.4% |    99.95% |    99.97% |   1 |     2 |
| all commands       | 1.18 |    89.6% |     95.9% |     96.7% |   4 |     5 |

- **A click is one kind of order.** 95.2% of clicked actions hold one order
  and 99.4% one kind. Those with more orders are dragged lines of one building
  (1.5% of actions, 13 buildings on average); clicked actions with more than
  one kind are 0.6%, and with more than two 0.03%.
- **Widgets add orders, not kinds.** With widget commands 40% of actions hold
  more than one order, but most of those are one kind sent to several spots:
  28% of all actions, 11.6 orders on average, nearly all from widgets alone
  (`MOVE` 64%, `FIGHT` 21%, `REMOVE` 13% of them). These are formation moves
  and area commands that follow a drag of the player, and queue clean-up.
- **Several kinds come from widget housekeeping.** The 10% of actions with
  more than one kind are 9.1% widgets alone, 0.8% a click with widget
  commands, and 0.2% clicks. The most common are the orders a widget gives a
  unit its factory just finished (`FIGHT MOVE_STATE PRIORITY REPAIR`, 29% of
  them; BAR's own APM gadget leaves out the first command of a finished unit,
  which our count can't), build priorities and queue clean-up
  (`PRIORITY REMOVE`, 29%), and `MOVE REPAIR` (5%).
- **Skill and phase change little.** Clicked actions hold 1.34 (40 and up) to
  1.56 (20-30) orders, and more than one kind in 0.3% to 1.0% of actions in
  every band. With widgets, orders per action grow with skill (3.2 below 10,
  5.0 to 5.1 from 30 up) and over the game (2.2 in the first two minutes, 3.6
  at 5 to 10, 6.9 after 30), and so does the share with more than one kind
  (7.6% in the first two minutes, 4.3% to 4.9% from 2 to 10, 18.7% after 30)
  as armies grow and widgets manage more units.
- **Automation widgets don't change it.** Actions of the players with a widget
  that automates build orders enabled
  ([`automation-widgets.md`](automation-widgets.md)): 4.5 (4.1–4.9) orders,
  more than one kind in 9.4% (8.6–10.3), against 4.7 and 10.4% for the rest.

### The bot

| per counted action             |      n |           commands |   distinct orders | more than one order | more than one kind | p90 | p99 | most |
| ------------------------------ | -----: | -----------------: | ----------------: | ------------------: | -----------------: | --: | --: | ---: |
| Reason8, lobby                 |  7,719 | 18.39 (9.59–26.33) | 9.94 (5.91–13.36) |   85.3% (74.4–91.8) |  84.7% (73.7–91.2) |  22 |  39 |   77 |
| Reason8, headless, lower bound | 45,098 |   4.76 (4.37–5.12) |  3.77 (3.51–4.01) |   64.9% (62.6–67.1) |  63.9% (61.6–66.1) |   9 |  18 |   34 |
| BARbLimited, headless, l. b.   | 52,137 |   4.55 (4.32–4.77) |  3.51 (3.36–3.68) |   66.5% (64.9–68.1) |  65.2% (63.6–66.8) |   8 |  15 |   30 |
| stock BARb, lobby, no governor | 38,345 |   1.94 (1.64–2.30) |  1.69 (1.53–1.88) |   45.5% (37.2–53.9) |  44.8% (36.5–53.1) |   3 |   6 |   29 |

Each of the bot's commands goes to one unit, so its commands are its unit
orders.

| per counted action, kinds      | mean | one kind | at most 2 | at most 3 | p99 |
| ------------------------------ | ---: | -------: | --------: | --------: | --: |
| Reason8, lobby                 | 4.81 |    15.3% |     30.7% |     41.3% |  13 |
| Reason8, headless, lower bound | 2.86 |    36.1% |     57.0% |     72.9% |  10 |
| stock BARb, lobby, no governor | 1.58 |    55.2% |     89.9% |     97.5% |   4 |

Reason8 in the lobby games, by phase:

| phase     | actions | commands | distinct orders | more than one kind | p90 orders |
| --------- | ------: | -------: | --------------: | -----------------: | ---------: |
| 0-2 min   |     322 |      2.5 |             2.4 |              59.6% |          4 |
| 2-5 min   |     849 |      4.8 |             3.8 |              74.2% |          8 |
| 5-10 min  |   1,190 |     10.8 |             6.5 |              81.3% |         16 |
| 10-15 min |   1,395 |     13.5 |             8.3 |              80.8% |         18 |
| 15-20 min |   1,605 |     18.1 |            10.0 |              84.8% |         21 |
| 20-30 min |   1,847 |     31.8 |            15.4 |              94.7% |         31 |
| 30+ min   |     511 |     34.5 |            17.4 |              99.6% |         29 |

Per team-game of Reason8 in the lobby games, the mean distinct orders per
action is 2.1 to 18.4 (2.1, 2.5, 6.3, 6.6 and 8.7 in the first game; 10.8,
13.4 and 18.4 in the second, which was busier: 21 to 39 commands per action).

- **An action of the bot is many different orders.** In real time, 85% of
  Reason8's actions hold more than one kind of order, against 0.6% of a
  player's clicks and 10% of a player's actions with widgets; it averages 4.8
  kinds and 9.9 distinct orders an action, and 13 kinds at p99, where a
  player's p99 is 1 (clicked) or 4 (with widgets).
- **It grows with the game.** In the first two minutes an action holds 2.4
  orders, about a player's with widgets (2.2), but 60% of them mix kinds
  (players: 7.6%); from 5 to 10 minutes 6.5 orders, and 15 to 17 after 20
  minutes, when nearly every action mixes kinds.
- **The mixes are many units' business at once.** Kinds mix because the
  governor sends what it held for different units together: paths (a `MOVE`
  and shift-queued `MOVE`s: 98% of the mixed actions whose only command is
  `MOVE`, in the second lobby game), a new unit's settings
  (`FIRE_STATE MOVE_STATE REPAIR`, `AUTOREPAIRLEVEL ONOFF`), queue edits
  (`REMOVE`) and attack orders (`ATTACK FIGHT MOVE`), in any combination: the
  most common set is 12.5% of the mixed actions and the tenth 1.1%.
- **The headless games show the same at the opening's scale.** Even split by
  the replay's frames, an action holds 3.8 orders, fewer than a player's with
  widgets (4.7), but 2.9 kinds against 1.2, and 64% of the actions mix kinds
  against 10%. `BARbLimited` on the same library is the same (3.5 orders, 65%
  mixed).
- **Without the governor BARb's frames are small.** Stock BARb in the lobby
  game gives 1.7 orders a frame: it spreads its commands over many frames
  (6,300 to 12,800 actions a team-game). The governor's flushes, not BARb, put
  many orders in one action.
- **Free commands add little.** The span of an action, with the commands the
  7-frame rule lets through after it, holds 10.5 orders instead of 9.9 for
  Reason8 and 5.5 instead of 4.7 for players.

### What it says about the counting rule

- **A flush of different orders in one frame is not something players do.** A
  player's action is one kind of order: 99.4% of clicked actions, and 89.6%
  with widgets, whose extra kinds are housekeeping of units the player did not
  click (new units' settings, priorities, queue clean-up). Even with widgets,
  more than three kinds in one action are rare (3.3%) and the p99.9 is 5. The
  bot's actions hold a median of four kinds or more and up to 18: one counted
  action of the bot is what several actions of a player would be.
- **Distinct orders alone are the wrong bound.** One kind can hold many orders
  in a human action: a dragged line (13 buildings on average, p99 of clicked
  actions 14) and formation moves (11.6 orders); ADR 0008 counts these as one
  action, and they are what players do.
- **A human-like bound is one kind per action,** with any number of targets:
  clicked actions hold more in 0.6%, actions with widgets in 10.4%, nearly all
  of it widgets' housekeeping. Counted that way, a player's actions would rise
  by 1% (clicked) and 18% (with widgets), while the bot's would rise by about
  4.8 times in real time.

## Under the count by kind of order

ADR 0008 now counts each kind of order in a frame as an action, and leaves out
the commands a unit gets in the frame it is finished, as BAR's gadget does;
the bands were rounded again from players' actions counted the same way
([`apm.md`](apm.md#the-count-by-kind-of-order)), the 30-40 band's to 14
actions in any second, 60 in any 10 s, 40 in any minute of the first two, 90
in any later minute and 250 in any 5 minutes. The governor counts this way:
when one action fits, it sends the held commands of that kind, and every other
kind waits for an action of its own.

One game, to see that it works: 8v8 on Supreme Isthmus, seed 1, 10 game
minutes, headless at 5.3 times real time, eight Reason8 teams (with the model
deciding idle builders' next orders, ADR 0019: 319 decisions logged) against
eight `BARbLimited`, both on this library.

| per team-game, median (range)  | Reason8            | `BARbLimited`      |
| ------------------------------ | ------------------ | ------------------ |
| actions a minute               | 39.5 (26.2–41.8)   | 40.7 (37.8–41.9)   |
| commands sent per action       | 3.4                | 3.8                |
| commands held at least a frame | 82% (34–88%)       | 85% (75–90%)       |
| replaced while held            | 33%                | 36%                |
| longest wait                   | 212 frames (7.1 s) | 265 frames (8.8 s) |

- **The budget holds and nothing is lost.** `reason8 bot check` passed the
  governor of all 16 teams: every command accounted for, none dropped, every
  window kept. The most actions in any window were 9 in a second, 34 in a
  minute of the first two, 89 in a later minute and 249 in 5 minutes, against
  caps of 14, 40, 90 and 250. The orders that follow the model's decisions go
  through the governor like the rest: the model gives BARb a task, and BARb
  gives the unit commands through the governed callback.
- **The bot waits longer.** In the 8v8 games under the old count three
  quarters of the commands were held, 8% were replaced while held and none
  waited over 59 frames (2 s). Now 82% are held, a third are replaced by a
  newer order to the same unit before they go, and the longest wait is 7 s at
  the median and 11.5 s at most. From minute 6 on, Reason8's teams act about
  37 times a minute, the pace the 5-minute budget allows, while BARb gives
  each of them hundreds of commands a minute (team 1: 290 to 800).
- **The replay overcounts more.** Counted from the replay, Reason8's teams
  took 12 to 25% more actions than their governors logged (team 1: 469 against
  418), and the replay goes over the 5-minute cap for seven of them. Most of
  the difference is the settings BARb gives a new unit (`AUTOREPAIRLEVEL`,
  `ONOFF`): the governor leaves them out in the frame the unit is finished,
  while the headless replay records them frames after the unit's first
  command, which is all the replay can take for the frame it was finished.

## Not measured

- What holding longer under the count by kind of order costs in play: that
  needs paired games, Reason8 under the new count against the same AI under
  the old one.
- Whether BARb's own timeouts on tasks (a builder whose order is held for two
  seconds) change what it does later; the economy measures of
  [`evaluation.md`](../reference/evaluation.md#our-barb-library) cover the
  effect as a whole.
