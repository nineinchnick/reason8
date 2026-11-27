# Holding commands under the action budget

The bot has to stay within a strong player's action budget
([ADR 0008](../decisions/0008-play-under-human-like-limits.md)), and BARb's
library sends far more: 400 to 3,000 commands a minute
([`in-game.md`](../reference/in-game.md#command-rate)). A first governor in
our build of the library dropped the commands over the budget, 45% of them,
with BARb believing they were given
([`in-game.md`](../reference/in-game.md#a-command-governor)). This document
measures the governor that holds them instead and sends them later, and the
live state the same library gives the scripts. How it works is in
[`in-game.md`](../reference/in-game.md#our-barb-library); code: `ai/native`,
`reason8/bot/budget.py`, `reason8/bot/live_state.py`.

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
In a game played in real time the delay should be a frame or two; that is not
measured.

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

## Not measured

- A game played in real time, where the replay should record the bot's
  commands within a frame or two of when they were sent.
- Whether BARb's own timeouts on tasks (a builder whose order is held for two
  seconds) change what it does later; the economy measures of
  [`evaluation.md`](../reference/evaluation.md#our-barb-library) cover the
  effect as a whole.
