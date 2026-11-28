# Actions per minute of human players

The bot plays under human-like limits
([ADR 0008](../decisions/0008-play-under-human-like-limits.md)), and the
command rate is one of them. This document measures how many actions people
take per minute in the games of the slice, how that changes over a game and
with skill, and how fast they act in bursts. Code: `reason8/analysis/apm.py`.

```sh
uv run reason8 analysis apm             # data/tables -> data/apm/
uv run reason8 analysis apm --report    # every table this is drawn from
```

The pass reads the commands, selections and events tables of the parsed
replays ([`replay-format.md`](../reference/replay-format.md#tables)), a day
per process (`--jobs`, 4 by default), 20 replays at a time. On the two weeks
of the tables sample (2,830 replays) it took 325 s with 3 processes, where
reading the JSON documents took 383 s with 4. The numbers below were measured
from the tables of the whole slice, counting each kind of order in a frame
([below](#what-counts-as-an-action)): about 3.5 hours with 3 processes on a
machine that was also playing games, within 8 GB.

The limits recommended for the bot are in ADR 0008; this document holds the
measurements.

## Summary

People act at a slow, steady rate: a typical player takes 13 actions a minute
that they clicked themselves, and 35 once the commands their widgets send are
added. Better players are busier, not faster at the peak: skill doubles the
rate per minute (averaged over a game, 11 to 24 clicked actions a minute from
the lowest band to the highest, 24 to 56 with widgets), while the most clicked
actions in any 10 seconds has a p90 of 23 to 24 in every band. Clicking peaks
between minutes 2 and 10 and slows late in the game; widget commands keep
growing with the army.

An action is one kind of order in a frame, so a dragged line of buildings, a
formation move or a held right button is one action, while a move and a
shift-queued move are two. Counting every click instead doubles the p90 (68 a
minute instead of 35). Counting each kind of order rather than each frame, as
BAR's own counter does, changes the rates per minute by a few percent and
raises the short bursts: the p90 of the most actions with widgets in any
second goes from 11 to 13, in any 10 seconds from 47 to 56
([The count by kind of order](#the-count-by-kind-of-order)). The counts are
not yet checked against BAR's own in-game number.

Used in [ADR 0008](../decisions/0008-play-under-human-like-limits.md): the
bot's action budget per skill band is rounded from these measurements.

## What counts as an action

A replay holds the command packets of every player, so actions can be counted
without playing the game again. Counting packets is not enough, for two
reasons seen in the replays:

- **One gesture sends many packets in one frame.** Dragging a line of
  buildings sends one `COMMAND` per building, all in the same frame.
- **Holding the right mouse button repeats the order.** While the button is
  held, a new `MOVE` goes to the same selection every 4 frames (7.5 a second),
  for as long as the player holds it.

BAR has its own APM counter, the `APM Broadcast` gadget
(`luarules/gadgets/game_apm_broadcast.lua`), whose number players see in game.
It runs in `AllowCommand`, so it sees every command a unit gets, from clicks
and widgets alike, and it counts:

- at most one action per team per game frame;
- a command only if at least one of its units got no command in the 7 frames
  before; every command marks its units for the next 7 frames ("don't count
  severe command spam");
- not commands to drones or to units still being built, nor the commands a
  unit gets in the frame it is finished (`UnitFinished`, so the settings a
  widget gives a new unit at once).

We count per player as ADR 0008 says: a `COMMAND` packet goes to the player's
current selection (the last `select` event, pregame ones included), an
`AICOMMAND`/`AICOMMANDS` packet to the units it lists, and

- one action for each kind of order in a frame: the command, the unit it
  builds and its options, whatever its parameters and units. The gadget counts
  at most one a frame; one frame of a player rarely holds more than one kind
  (0.6% of clicked actions), and one frame of the bot's command governor often
  did ([`command-governor.md`](command-governor.md#what-one-action-holds));
- a command only if at least one of its units got no command in the 7 frames
  before its frame, as the gadget;
- not the commands a widget gives a unit in the frame of the unit's first
  command. The gadget leaves out the commands a unit gets in the frame it is
  finished (`UnitFinished`), the settings widgets give a new unit; the replay
  doesn't say when a unit was finished, and the frame of its first command
  stands in for it. A click is always counted. Drones are not left out.

With these rules a dragged line of buildings is one action, and so are a
formation move and a held right button (each repeat comes within 7 frames of
the one before), which is what ADR 0008 asks for: an action is a step, however
many orders of one kind it holds.

Gex (`Varunda/gex`), which shows APM per player on its match pages, takes it
from the same gadget: its game-event widget copies the gadget's counting and
writes the running count every few seconds, and the page shows the rate over
the last four samples. Gex also has a calculator from replay commands alone
(`ApmCalculatorUtil`, 15-second periods, one action per frame, the 7-frame
rule per unit, skipping commands with the `internal` option). Its comment says
it is not used because "the values calculated were just too high to be
reasonable". It doesn't tell clicks from widget commands, and without the
selection a `COMMAND` packet has no units, so the 7-frame rule can't apply to
clicks: by our numbers below, widget commands and click spam each come close
to doubling the count.

Four counts are kept for every player:

`clicked`
: `COMMAND` packets: what the player clicked or typed. This is the main
  measure.

`widget`
: `AICOMMAND`/`AICOMMANDS` packets with `ai` 255, sent by the player's LuaUI
  widgets. Some follow a click (BAR's formation moves are sent this way, one
  `MOVE` per unit), others run on their own (queue clean-up with `REMOVE`,
  build priorities, idle modes, factory guard).

`all`
: Both, counted together: what the bot's budget is drawn from. BAR's in-game
  APM counts at most one action a frame and has to be a little lower.

`clicked_raw`
: `COMMAND` packets, at most one per frame, without the 7-frame rule: closest
  to counting clicks and key presses.

A player is counted from the start of the game until the game ends, they
resign, their team dies, or they leave and send no more commands. Only whole
minutes in that span are kept, so a player who resigns at 12:40 has 12
minutes. The replays' own per-player counters (`statistics.playerStats`:
`numCommands`, `mouseClicks`, `keyPresses`) can't be used: the values the
parser gives are garbage (large negative numbers), so the field seems to be
read with the wrong layout.

## Sample

`reason8 analysis apm` reads every parsed replay in the tables: the 42,931
parsed games of the slice (the window of
[`dataset.md`](../reference/dataset.md)). One game has bots and is left out;
42,927 of the rest are 8v8 and three are 1v1. Skill is the player's OpenSkill
value from the replay (the lobby's, before the game), in five bands:

| skill band | player-games | player-minutes |
| ---------- | -----------: | -------------: |
| below 10   |       26,605 |        737,847 |
| 10-20      |      208,527 |      5,774,758 |
| 20-30      |      260,771 |      7,041,510 |
| 30-40      |      133,429 |      3,276,692 |
| 40 and up  |       57,503 |      1,294,808 |

A player-game lasts 24 minutes at the median (44 at p90). The tables give
quantiles of one value per player-minute, or per player-game where they say
so; with this many values, sampling noise is below the rounding.

## Over the game

Actions in each whole minute, by the phase of the game the minute is in.

`clicked`:

| phase     |      n | mean | p25 | median | p75 | p90 | p99 |
| --------- | -----: | ---: | --: | -----: | --: | --: | --: |
| 0-2 min   | 1.37 M |   11 |   3 |      8 |  15 |  23 |  44 |
| 2-5 min   | 2.06 M |   20 |  10 |     17 |  27 |  40 |  68 |
| 5-10 min  | 3.41 M |   21 |  10 |     18 |  29 |  42 |  71 |
| 10-15 min | 3.09 M |   19 |   9 |     15 |  25 |  37 |  65 |
| 15-20 min | 2.52 M |   16 |   7 |     13 |  22 |  33 |  60 |
| 20-30 min | 3.25 M |   15 |   6 |     12 |  19 |  30 |  57 |
| 30+ min   | 2.42 M |   12 |   5 |     10 |  16 |  25 |  51 |
| all       | 18.1 M |   17 |   7 |     13 |  23 |  35 |  63 |

`all`:

| phase     |      n | mean | p25 | median | p75 | p90 | p99 |
| --------- | -----: | ---: | --: | -----: | --: | --: | --: |
| 0-2 min   | 1.37 M |   19 |  10 |     16 |  25 |  35 |  61 |
| 2-5 min   | 2.06 M |   35 |  21 |     30 |  45 |  63 | 101 |
| 5-10 min  | 3.41 M |   43 |  25 |     39 |  57 |  76 | 116 |
| 10-15 min | 3.09 M |   43 |  25 |     39 |  57 |  76 | 120 |
| 15-20 min | 2.52 M |   45 |  23 |     39 |  59 |  83 | 147 |
| 20-30 min | 3.25 M |   46 |  21 |     37 |  60 |  91 | 180 |
| 30+ min   | 2.42 M |   52 |  18 |     35 |  66 | 114 | 259 |
| all       | 18.1 M |   42 |  21 |     35 |  55 |  80 | 163 |

`widget` on its own has a median of 18 (p90 61, p99 149), growing from 7 in
the first two minutes to 21 after minute 30 (p99 247). `clicked_raw` has a
median of 17 (p90 68, p99 152), and its p90 is twice that of `clicked` from
minute 2 to minute 15 (75 to 88 against 37 to 42): that is where holding the
right button and click spam are.

The first minute holds the pregame queue, which the widget sends in frames 5
to 13 (up to 9 actions). In minute 0 the median is 5 `clicked`, 6 `widget` and
11 `all` actions. 10.5% of the minutes in the first two minutes have no
`clicked` action, 0.6 to 1.9% of those from minute 2 to 20, 3.0% from 20 to 30
and 5.6% after that (players away from the keyboard, or waiting).

## By skill

Actions per minute, every minute of the game:

| skill band | clicked p25 | median | p75 | p90 | p99 | all p25 | median | p75 | p90 | p99 |
| ---------- | ----------: | -----: | --: | --: | --: | ------: | -----: | --: | --: | --: |
| below 10   |           5 |      9 |  15 |  25 |  54 |      13 |     21 |  33 |  50 | 103 |
| 10-20      |           6 |     11 |  18 |  29 |  57 |      16 |     27 |  42 |  63 | 132 |
| 20-30      |           8 |     13 |  22 |  33 |  62 |      22 |     36 |  56 |  81 | 169 |
| 30-40      |          10 |     18 |  28 |  40 |  68 |      29 |     46 |  66 |  91 | 187 |
| 40 and up  |          13 |     22 |  33 |  46 |  70 |      36 |     55 |  76 |  99 | 199 |
| all        |           7 |     13 |  23 |  35 |  63 |      21 |     35 |  55 |  80 | 163 |

Average actions per minute over a player's game, one value per player-game:

| skill band | clicked p25 | median | p75 | p90 | p99 | all p25 | median | p75 | p90 | p99 |
| ---------- | ----------: | -----: | --: | --: | --: | ------: | -----: | --: | --: | --: |
| below 10   |         7.8 |     11 |  15 |  20 |  33 |      18 |     24 |  31 |  38 |  57 |
| 10-20      |         9.5 |     13 |  18 |  23 |  36 |      23 |     30 |  39 |  48 |  72 |
| 20-30      |          12 |     16 |  21 |  27 |  40 |      31 |     40 |  50 |  62 |  89 |
| 30-40      |          15 |     20 |  26 |  32 |  46 |      39 |     48 |  59 |  71 | 106 |
| 40 and up  |          19 |     24 |  30 |  36 |  48 |      46 |     56 |  67 |  79 | 116 |
| all        |          12 |     16 |  22 |  29 |  42 |      29 |     39 |  51 |  64 |  93 |

### By skill and phase

Median `clicked` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |       6 |      11 |       11 |        10 |         9 |         8 |       7 |
| 10-20      |       7 |      13 |       14 |        12 |        11 |        10 |       8 |
| 20-30      |       8 |      16 |       17 |        15 |        13 |        12 |      10 |
| 30-40      |      10 |      22 |       23 |        20 |        17 |        15 |      13 |
| 40 and up  |      13 |      28 |       27 |        23 |        20 |        18 |      15 |

p90 of `clicked` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |      17 |      28 |       31 |        27 |        24 |        22 |      19 |
| 10-20      |      19 |      32 |       36 |        31 |        28 |        25 |      22 |
| 20-30      |      22 |      37 |       41 |        36 |        32 |        29 |      26 |
| 30-40      |      27 |      46 |       48 |        42 |        37 |        35 |      30 |
| 40 and up  |      32 |      55 |       51 |        45 |        41 |        39 |      34 |

Median `all` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |      13 |      21 |       24 |        23 |        22 |        21 |      18 |
| 10-20      |      15 |      24 |       30 |        30 |        29 |        28 |      25 |
| 20-30      |      16 |      30 |       39 |        41 |        40 |        39 |      39 |
| 30-40      |      19 |      39 |       50 |        50 |        50 |        49 |      51 |
| 40 and up  |      23 |      49 |       60 |        58 |        60 |        59 |      60 |

p90 of `all` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |      25 |      41 |       51 |        49 |        52 |        56 |      62 |
| 10-20      |      29 |      48 |       61 |        60 |        65 |        72 |      86 |
| 20-30      |      34 |      59 |       73 |        76 |        84 |        94 |     123 |
| 30-40      |      40 |      72 |       85 |        86 |        96 |       105 |     146 |
| 40 and up  |      46 |      86 |       94 |        94 |       106 |       116 |     162 |

Better players click more in every phase, most of all from minute 2 to 10,
when they place buildings and send out the first units. The gap in `all`
widens late in the game, as bigger armies get more formation moves and widget
housekeeping.

## Bursts

The most actions a player takes in any window of 1, 10 and 60 seconds of their
game, one value per player-game. Median:

| skill band | clicked 1 s | 10 s | 60 s | all 1 s | 10 s | 60 s | clicked_raw 1 s | 10 s |
| ---------- | ----------: | ---: | ---: | ------: | ---: | ---: | --------------: | ---: |
| below 10   |           4 |   14 |   35 |       7 |   22 |   68 |               7 |   28 |
| 10-20      |           4 |   15 |   40 |       8 |   25 |   82 |               7 |   33 |
| 20-30      |           4 |   16 |   46 |       9 |   30 |  100 |               8 |   38 |
| 30-40      |           4 |   16 |   52 |       9 |   30 |  106 |               9 |   42 |
| 40 and up  |           4 |   17 |   59 |       9 |   31 |  113 |              10 |   44 |
| all        |           4 |   16 |   46 |       8 |   28 |   96 |               8 |   38 |

p90:

| skill band | clicked 1 s | 10 s | 60 s | all 1 s | 10 s | 60 s | clicked_raw 1 s | 10 s |
| ---------- | ----------: | ---: | ---: | ------: | ---: | ---: | --------------: | ---: |
| below 10   |           5 |   23 |   67 |      11 |   38 |  127 |              11 |   52 |
| 10-20      |           5 |   24 |   71 |      12 |   49 |  160 |              12 |   55 |
| 20-30      |           5 |   23 |   74 |      13 |   59 |  200 |              14 |   59 |
| 30-40      |           5 |   23 |   78 |      14 |   59 |  201 |              14 |   61 |
| 40 and up  |           5 |   23 |   81 |      14 |   60 |  205 |              15 |   62 |
| all        |           5 |   23 |   75 |      13 |   56 |  186 |              14 |   59 |

p99:

| skill band | clicked 1 s | 10 s | 60 s | all 1 s | 10 s | 60 s | clicked_raw 1 s | 10 s |
| ---------- | ----------: | ---: | ---: | ------: | ---: | ---: | --------------: | ---: |
| below 10   |           7 |   32 |  109 |      15 |   65 |  224 |              25 |   86 |
| 10-20      |           9 |   32 |  111 |      17 |   82 |  296 |              24 |   81 |
| 20-30      |          10 |   31 |  110 |      19 |  101 |  378 |              24 |   85 |
| 30-40      |          12 |   31 |  112 |      20 |  110 |  421 |              23 |   82 |
| 40 and up  |          12 |   29 |  104 |      21 |  122 |  463 |              25 |   84 |
| all        |          10 |   31 |  110 |      19 |   99 |  371 |              24 |   83 |

The 1-second `clicked` figure is set mostly by the counting rule, not by the
player: commands to the same units count once every 7 frames, so one selection
gets at most 5 actions a second unless a frame holds several kinds of order.
6.6% of the player-games go above 5 (the highest is 39), against 0.2% when
each frame counted once. Over 10 seconds every band peaks at 14 to 17 actions
(p90 23 to 24), and the best players are no faster at the peak; what skill
changes is how often players are near it. The 60-second window does grow with
skill, as the per-minute rates do.

Within one minute the bursts are smaller. The most `clicked` actions in any 10
seconds that start in a minute has a median of 6 (p90 14, p99 22), and of
`all` 13 (p90 27, p99 55); `all` in any second of a minute has a median of 4
and a p99 of 13.

## The count by kind of order

Until 2026-11-28 this document counted at most one action a frame, as BAR's
gadget does, and every command to a unit as the gadget would but for the frame
a unit is finished. ADR 0008 now counts each kind of order in a frame and
leaves out a new unit's first commands
([What counts as an action](#what-counts-as-an-action)). The same games,
counted both ways:

| per player-minute or player-game, all bands |   each frame |    each kind |
| ------------------------------------------- | -----------: | -----------: |
| `clicked` a minute, median (p90)            |      13 (34) |      13 (35) |
| `widget` a minute, median (p90)             |      19 (62) |      18 (61) |
| `all` a minute, median (p90, p99)           | 36 (80, 159) | 35 (80, 163) |
| `all` a minute in the first 2 min, median   |           18 |           16 |
| `all` a minute after 30 min, median         |           40 |           35 |
| `all` averaged over a game, median          |           39 |           39 |
| most `all` in any 1 s, p90                  |           11 |           13 |
| most `all` in any 10 s, p90                 |           47 |           56 |
| most `all` in any 60 s, p90                 |          168 |          186 |
| player-games with over 5 `clicked` in 1 s   |         0.2% |         6.6% |

- **Rates a minute hardly move.** The two changes pull against each other:
  frames with several kinds of order add actions, and the commands widgets
  give new units take them away. The second wins where many units are finished
  at once, in the first two minutes and late in the game; the medians of the
  game average are the same in every band but the two lowest, which lose one
  (25 to 24, 31 to 30).
- **Short bursts grow.** A burst is where several kinds land in one frame: a
  click with the widget's follow-up, or widget housekeeping of many units at
  once. The p90 of the most actions in any second goes from 9, 10, 11, 11 and
  11 in the five bands to 11, 12, 13, 14 and 14, in any 10 seconds from 35,
  42, 50, 49 and 48 to 38, 49, 59, 59 and 60.

ADR 0008's bands are rounded from these figures. With the count by kind their
1-second and 10-second caps rise (the 30-40 band's from 11 and 50 to 14 and
60), the 40-and-up band's cap on a minute of the first two falls from 50 to 45
(its p90 from 48 to 46), and the other caps stay within rounding.

## What is left open

- **Widget commands are not split** into those that follow a click (formation
  moves, area commands) and those widgets send on their own. Both are in
  `all`, as in BAR's own counter, so `all` overstates what the player decided
  and `clicked` understates it.
- **When a unit is finished is guessed** from its first command. A unit that
  gets no command when it is finished, and a unit id used again after its unit
  died, are counted as BAR's gadget would not.
- **Selections are not counted.** A `select` event is a click too (StarCraft's
  APM counts it), but the bot gives orders without selecting.
- **The skill is the lobby's value before the game**, the same for every
  minute of it.
- **Not checked against BAR's own number.** The replays don't keep the APM the
  gadget broadcasts. Playing a few replays headlessly with a widget that logs
  it would show how close `all` comes.
