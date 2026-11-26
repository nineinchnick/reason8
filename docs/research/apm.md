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
per process (`--jobs`, 4 by default; each holds one day of commands). On the
two weeks of the tables sample (2,830 replays) it takes 325 s with 3
processes, where reading the JSON documents took 383 s with 4, with the same
tables. The numbers below were measured from the JSON documents.

The limits recommended for the bot are in ADR 0008; this document holds the
measurements.

## Summary

- **Sample:** every parsed game of the slice: 42,930 games (all but three of
  them 8v8), 686,838 player-games, 18.1 million whole player-minutes.
- **Actions are counted as BAR counts them** (one per frame, and the 7-frame
  rule per unit), so a dragged line of buildings or a held right button is one
  action. `clicked` counts what the player clicked, `all` adds the commands
  sent by the player's widgets and is close to the APM BAR shows in game.
- **A typical player clicks 13 actions a minute** (median of all
  player-minutes; quartiles 7 and 22, p90 34, p99 62). With the widgets it is
  36 (quartiles 22 and 56, p90 80, p99 159).
- **Over the game,** clicking peaks between minutes 2 and 10 (median 17, p90
  40 to 42) and slows to 10 after minute 30, while widget commands keep
  growing with the army: `all` goes from 18 in the first two minutes to 39 at
  minutes 5 to 10, and stays there with a long tail late in the game (p99 257
  after minute 30).
- **Skill doubles the rate.** Median `clicked` per minute goes from 9 below
  skill 10 to 21 at 40 and up; `all` from 22 to 55. Averaged over a game,
  `clicked` is 11, 13, 16, 20 and 24 per minute in the five skill bands, and
  `all` 25, 31, 40, 48 and 56.
- **Short bursts hardly grow with skill.** The most `clicked` actions a player
  takes in any 10 seconds of a game has a median of 14 to 17 and a p90 of 22
  to 23 in every band; for `all` the median is 20 to 29 and the p90 35 to 50,
  and in any second a median of 6 to 7 and a p90 of 9 to 11. Better players
  are busier all the time, not much faster at the peak.
- **Spam is much of the raw clicking.** Without the 7-frame rule the median
  player-minute has 17 clicks instead of 13, and the p90 68 instead of 34. At
  the peak a player clicks 8 times in a second (median of the game's maximum),
  24 at p99.

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
- not commands to drones or to units still being built, and not the first
  command of a unit just finished (its factory's rally orders).

We count the same way, per player: a `COMMAND` packet goes to the player's
current selection (the last `select` event, pregame ones included), an
`AICOMMAND`/`AICOMMANDS` packet to the units it lists. The last rule needs the
game state and is left out; it touches only commands sent in the frame a unit
is finished. With the rules above a dragged line of buildings is one action,
and so is a held right button (each repeat comes within 7 frames of the one
before), which is what ADR 0008 asks for: an action is a step, however many
orders it holds.

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
: Both, counted together: close to BAR's in-game APM.

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
| 2-5 min   | 2.06 M |   20 |  10 |     17 |  27 |  40 |  67 |
| 5-10 min  | 3.41 M |   21 |  10 |     17 |  29 |  42 |  70 |
| 10-15 min | 3.09 M |   18 |   9 |     15 |  25 |  37 |  64 |
| 15-20 min | 2.52 M |   16 |   7 |     13 |  22 |  33 |  59 |
| 20-30 min | 3.25 M |   15 |   6 |     12 |  19 |  30 |  56 |
| 30+ min   | 2.42 M |   12 |   5 |     10 |  16 |  25 |  51 |
| all       | 18.1 M |   17 |   7 |     13 |  22 |  34 |  62 |

`all`:

| phase     |      n | mean | p25 | median | p75 | p90 | p99 |
| --------- | -----: | ---: | --: | -----: | --: | --: | --: |
| 0-2 min   | 1.37 M |   20 |  11 |     18 |  26 |  36 |  63 |
| 2-5 min   | 2.06 M |   36 |  22 |     31 |  45 |  62 | 100 |
| 5-10 min  | 3.41 M |   43 |  26 |     39 |  57 |  75 | 114 |
| 10-15 min | 3.09 M |   44 |  26 |     40 |  57 |  76 | 117 |
| 15-20 min | 2.52 M |   45 |  25 |     40 |  59 |  82 | 138 |
| 20-30 min | 3.25 M |   46 |  23 |     38 |  61 |  89 | 164 |
| 30+ min   | 2.42 M |   56 |  21 |     40 |  74 | 122 | 257 |
| all       | 18.1 M |   43 |  22 |     36 |  56 |  80 | 159 |

`widget` on its own has a median of 19 (p90 62, p99 147), growing from 9 in
the first two minutes to 27 after minute 30 (p99 248). `clicked_raw` has a
median of 17 (p90 68, p99 152), and its p90 is twice that of `clicked` from
minute 2 to minute 15 (75 to 88 against 37 to 42): that is where holding the
right button and click spam are.

The first minute holds the pregame queue, which the widget sends in frames 5
to 13 (up to 9 actions). In minute 0 the median is 5 `clicked`, 8 `widget` and
13 `all` actions. 10.5% of the minutes in the first two minutes have no
`clicked` action, 0.6 to 1.9% of those from minute 2 to 20, 3.0% from 20 to 30
and 5.6% after that (players away from the keyboard, or waiting).

## By skill

Actions per minute, every minute of the game:

| skill band | clicked p25 | median | p75 | p90 | p99 | all p25 | median | p75 | p90 | p99 |
| ---------- | ----------: | -----: | --: | --: | --: | ------: | -----: | --: | --: | --: |
| below 10   |           5 |      9 |  15 |  25 |  54 |      14 |     22 |  34 |  51 | 101 |
| 10-20      |           6 |     11 |  18 |  28 |  57 |      18 |     28 |  43 |  64 | 131 |
| 20-30      |           8 |     13 |  22 |  33 |  61 |      24 |     38 |  57 |  82 | 166 |
| 30-40      |          10 |     18 |  28 |  40 |  67 |      31 |     47 |  67 |  91 | 181 |
| 40 and up  |          13 |     21 |  33 |  45 |  70 |      37 |     55 |  75 |  97 | 181 |
| all        |           7 |     13 |  22 |  34 |  62 |      22 |     36 |  56 |  80 | 159 |

Average actions per minute over a player's game, one value per player-game:

| skill band | clicked p25 | median | p75 | p90 | p99 | all p25 | median | p75 | p90 | p99 |
| ---------- | ----------: | -----: | --: | --: | --: | ------: | -----: | --: | --: | --: |
| below 10   |         7.8 |     11 |  15 |  20 |  33 |      19 |     25 |  31 |  39 |  59 |
| 10-20      |         9.4 |     13 |  17 |  23 |  36 |      24 |     31 |  39 |  49 |  75 |
| 20-30      |          12 |     16 |  21 |  27 |  40 |      32 |     40 |  51 |  62 |  94 |
| 30-40      |          15 |     20 |  26 |  32 |  46 |      39 |     48 |  59 |  71 | 106 |
| 40 and up  |          19 |     24 |  30 |  36 |  47 |      46 |     56 |  66 |  77 | 109 |
| all        |          11 |     16 |  22 |  28 |  42 |      30 |     39 |  51 |  64 |  95 |

### By skill and phase

Median `clicked` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |       6 |      11 |       11 |        10 |         9 |         8 |       7 |
| 10-20      |       7 |      13 |       14 |        12 |        11 |        10 |       8 |
| 20-30      |       8 |      16 |       17 |        15 |        13 |        12 |      10 |
| 30-40      |      10 |      22 |       23 |        19 |        17 |        15 |      13 |
| 40 and up  |      13 |      28 |       27 |        23 |        20 |        18 |      15 |

p90 of `clicked` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |      17 |      28 |       31 |        27 |        24 |        22 |      19 |
| 10-20      |      19 |      32 |       36 |        31 |        28 |        25 |      22 |
| 20-30      |      22 |      37 |       40 |        36 |        32 |        29 |      25 |
| 30-40      |      26 |      45 |       47 |        42 |        37 |        34 |      30 |
| 40 and up  |      31 |      54 |       50 |        45 |        40 |        38 |      34 |

Median `all` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |      14 |      21 |       25 |        23 |        23 |        22 |      20 |
| 10-20      |      16 |      25 |       31 |        30 |        30 |        29 |      29 |
| 20-30      |      18 |      31 |       39 |        41 |        41 |        41 |      46 |
| 30-40      |      20 |      39 |       50 |        50 |        51 |        51 |      57 |
| 40 and up  |      24 |      49 |       60 |        58 |        60 |        59 |      66 |

p90 of `all` per minute:

| skill band | 0-2 min | 2-5 min | 5-10 min | 10-15 min | 15-20 min | 20-30 min | 30+ min |
| ---------- | ------: | ------: | -------: | --------: | --------: | --------: | ------: |
| below 10   |      26 |      41 |       50 |        48 |        51 |        56 |      67 |
| 10-20      |      30 |      48 |       60 |        59 |        64 |        72 |      94 |
| 20-30      |      35 |      59 |       72 |        75 |        83 |        92 |     131 |
| 30-40      |      41 |      72 |       84 |        86 |        95 |       103 |     154 |
| 40 and up  |      48 |      85 |       93 |        92 |       102 |       112 |     166 |

Better players click more in every phase, most of all from minute 2 to 10,
when they place buildings and send out the first units. The gap in `all`
widens late in the game, as bigger armies get more formation moves and widget
housekeeping.

## Bursts

The most actions a player takes in any window of 1, 10 and 60 seconds of their
game, one value per player-game. Median:

| skill band | clicked 1 s | 10 s | 60 s | all 1 s | 10 s | 60 s | clicked_raw 1 s | 10 s |
| ---------- | ----------: | ---: | ---: | ------: | ---: | ---: | --------------: | ---: |
| below 10   |           4 |   14 |   35 |       6 |   20 |   65 |               7 |   28 |
| 10-20      |           4 |   15 |   40 |       7 |   24 |   79 |               7 |   33 |
| 20-30      |           4 |   15 |   45 |       7 |   28 |   96 |               8 |   38 |
| 30-40      |           4 |   16 |   52 |       7 |   28 |  103 |               9 |   42 |
| 40 and up  |           4 |   17 |   58 |       7 |   29 |  109 |              10 |   44 |
| all        |           4 |   15 |   46 |       7 |   26 |   92 |               8 |   38 |

p90:

| skill band | clicked 1 s | 10 s | 60 s | all 1 s | 10 s | 60 s | clicked_raw 1 s | 10 s |
| ---------- | ----------: | ---: | ---: | ------: | ---: | ---: | --------------: | ---: |
| below 10   |           5 |   23 |   67 |       9 |   35 |  118 |              11 |   52 |
| 10-20      |           5 |   23 |   71 |      10 |   42 |  146 |              12 |   55 |
| 20-30      |           5 |   23 |   74 |      11 |   50 |  178 |              14 |   59 |
| 30-40      |           5 |   23 |   77 |      11 |   49 |  179 |              14 |   61 |
| 40 and up  |           5 |   22 |   80 |      11 |   48 |  178 |              15 |   62 |
| all        |           5 |   23 |   75 |      11 |   47 |  168 |              14 |   59 |

p99:

| skill band | clicked 1 s | 10 s | 60 s | all 1 s | 10 s | 60 s | clicked_raw 1 s | 10 s |
| ---------- | ----------: | ---: | ---: | ------: | ---: | ---: | --------------: | ---: |
| below 10   |           5 |   32 |  109 |      13 |   56 |  202 |              25 |   86 |
| 10-20      |           5 |   32 |  111 |      14 |   69 |  265 |              24 |   81 |
| 20-30      |           5 |   31 |  109 |      15 |   79 |  330 |              24 |   85 |
| 30-40      |           5 |   31 |  112 |      15 |   81 |  355 |              23 |   82 |
| 40 and up  |           5 |   29 |  103 |      15 |   81 |  374 |              25 |   84 |
| all        |           5 |   31 |  110 |      14 |   77 |  321 |              24 |   83 |

The 1-second `clicked` figure is set by the counting rule, not by the player:
commands to the same units count once every 7 frames, so one selection gets at
most 5 actions a second. Only 0.2% of the player-games go above 5 (the highest
is 17). Over 10 seconds every band peaks at about 15 actions (p90 23), and the
best players are no faster at the peak; what skill changes is how often
players are near it. The 60-second window does grow with skill, as the
per-minute rates do.

Within one minute the bursts are smaller. The most `clicked` actions in any 10
seconds that start in a minute has a median of 6 (p90 14, p99 22), and of
`all` 13 (p90 25, p99 48); `all` in any second of a minute has a median of 4
and a p99 of 11.

## What is left open

- **Widget commands are not split** into those that follow a click (formation
  moves, area commands) and those widgets send on their own. Both are in
  `all`, as in BAR's own counter, so `all` overstates what the player decided
  and `clicked` understates it.
- **Selections are not counted.** A `select` event is a click too (StarCraft's
  APM counts it), but the bot gives orders without selecting.
- **The skill is the lobby's value before the game**, the same for every
  minute of it.
- **Not checked against BAR's own number.** The replays don't keep the APM the
  gadget broadcasts. Playing a few replays headlessly with a widget that logs
  it would show how close `all` comes.
