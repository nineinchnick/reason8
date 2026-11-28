# How long players take to answer an idle unit

A factory that finishes its queue, or a builder that finishes its last task,
goes idle. BAR's interface lists idle factories and builders, and players use
the list to give them new orders. How long that takes is how long the bot
waits before giving an idle unit orders
([ADR 0008](../decisions/0008-play-under-human-like-limits.md)): attention,
not reflexes, sets the pace of a real player. Code:
`reason8/analysis/reactions.py`.

## Summary

Players are slow to answer an idle unit, whatever their skill: attention, not
speed, sets the pace. Counting their own clicks, they give an idle builder new
orders after a median of 6 s and an idle factory after 13 s, with a long tail
(p90 33 s and 43 s), and often not within a minute at all: 19% of idle
builders and 37% of idle factories get no order in that time. They answer
fastest in the first 3 minutes. From the lowest skill band to the highest, the
factory median falls only from 13.7 s to 11.0 s. Widgets answer at once; their
orders are automation, not attention, and are left out. Measured on one map,
in the first 10 minutes of 300 games.

Used in [ADR 0008](../decisions/0008-play-under-human-like-limits.md): the bot
waits a delay drawn from these, by kind of unit, game phase and skill band
([below](#what-the-bot-does-with-it)).

## Method

Games
: 300 games of the dataset's test split on Supreme Isthmus v2.1, drawn at
  random, re-simulated for their first 10 minutes with the state export
  (`reason8 headless batch`), which writes an `idle` line when a factory or
  builder runs out of orders. All 300 played back without a desync.

Reaction
: The first command the unit's player gives that unit at or after the idle
  frame, within 60 s, from the replay's commands: a `COMMAND` packet goes to
  the player's current selection, an `AICOMMAND` packet from the player's
  widgets to the units it lists, as in [`apm.md`](apm.md). `clicked` counts
  the player's own commands, `any` adds the widgets'.

Kinds
: `factory`; `builder` for a mobile builder, commanders included; `turret` for
  a construction turret, a static builder that assists what is near it.

Skill
: The player's OpenSkill mu as the replay records it, in the bands of
  [`apm.md`](apm.md).

```sh
uv run reason8 headless batch --data-dir data/bar --out-dir data/state \
    --jobs 7 --max-frame 18000 --list <replays>
uv run reason8 analysis reactions            # -> data/reactions/idle.parquet
uv run reason8 analysis reactions --report   # the tables below
```

## Results

300 games, 167979 idle events of human players' factories and builders;
answered: an order within 60 s.

### Clicked orders

#### Factory, by skill

| skill band | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| below 10   | 378    | 71%      | 6.6     | 13.7    | 29.3    | 46.3    |
| 10-20      | 3253   | 67%      | 6.5     | 13.8    | 26.1    | 43.0    |
| 20-30      | 4556   | 63%      | 6.0     | 13.6    | 27.4    | 42.8    |
| 30-40      | 2286   | 60%      | 5.2     | 12.4    | 25.4    | 42.0    |
| 40 and up  | 704    | 55%      | 4.8     | 11.0    | 24.7    | 39.3    |
| all        | 11177  | 63%      | 6.0     | 13.4    | 26.5    | 42.6    |

#### Factory, by phase

| phase      | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| 0:00-3:00  | 2489   | 59%      | 3.9     | 8.8     | 17.7    | 33.5    |
| 3:00-6:00  | 4101   | 59%      | 6.6     | 15.2    | 30.4    | 45.8    |
| 6:00-10:00 | 4587   | 69%      | 7.0     | 14.5    | 26.9    | 42.8    |
| all        | 11177  | 63%      | 6.0     | 13.4    | 26.5    | 42.6    |

#### Builder, by skill

| skill band | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| below 10   | 3798   | 84%      | 2.2     | 7.6     | 19.6    | 35.1    |
| 10-20      | 31003  | 82%      | 1.8     | 6.2     | 16.5    | 32.4    |
| 20-30      | 45099  | 80%      | 1.8     | 6.1     | 17.1    | 33.5    |
| 30-40      | 24892  | 80%      | 1.7     | 5.8     | 16.3    | 33.2    |
| 40 and up  | 13121  | 83%      | 1.6     | 5.6     | 14.6    | 30.1    |
| all        | 117913 | 81%      | 1.8     | 6.0     | 16.6    | 32.9    |

#### Builder, by phase

| phase      | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| 0:00-3:00  | 12809  | 92%      | 0.9     | 3.0     | 9.5     | 23.3    |
| 3:00-6:00  | 42211  | 86%      | 1.6     | 5.2     | 14.3    | 29.0    |
| 6:00-10:00 | 62893  | 75%      | 2.4     | 7.9     | 20.3    | 37.0    |
| all        | 117913 | 81%      | 1.8     | 6.0     | 16.6    | 32.9    |

#### Turret, by skill

| skill band | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| below 10   | 712    | 16%      | 1.8     | 13.5    | 37.1    | 49.8    |
| 10-20      | 7918   | 26%      | 1.6     | 11.1    | 31.5    | 47.7    |
| 20-30      | 16948  | 28%      | 2.2     | 12.7    | 32.0    | 47.1    |
| 30-40      | 9409   | 31%      | 2.8     | 13.8    | 32.5    | 48.8    |
| 40 and up  | 3902   | 35%      | 4.5     | 16.0    | 36.2    | 49.4    |
| all        | 38889  | 29%      | 2.4     | 13.1    | 32.5    | 48.1    |

#### Turret, by phase

| phase      | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| 0:00-3:00  | 353    | 36%      | 3.4     | 13.1    | 30.2    | 47.1    |
| 3:00-6:00  | 11736  | 33%      | 2.9     | 12.7    | 32.5    | 48.7    |
| 6:00-10:00 | 26800  | 27%      | 2.1     | 13.3    | 32.7    | 47.9    |
| all        | 38889  | 29%      | 2.4     | 13.1    | 32.5    | 48.1    |

### Any order, widgets included

#### Factory, by skill

| skill band | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| below 10   | 378    | 74%      | 6.3     | 13.1    | 28.1    | 45.2    |
| 10-20      | 3253   | 73%      | 5.0     | 12.2    | 24.1    | 41.0    |
| 20-30      | 4556   | 68%      | 5.1     | 12.5    | 25.9    | 40.7    |
| 30-40      | 2286   | 67%      | 4.4     | 11.1    | 23.3    | 40.0    |
| 40 and up  | 704    | 64%      | 2.0     | 8.0     | 19.7    | 37.7    |
| all        | 11177  | 69%      | 4.7     | 11.9    | 24.6    | 40.5    |

#### Factory, by phase

| phase      | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| 0:00-3:00  | 2489   | 62%      | 3.5     | 7.6     | 16.6    | 31.6    |
| 3:00-6:00  | 4101   | 64%      | 5.5     | 14.0    | 29.5    | 45.2    |
| 6:00-10:00 | 4587   | 78%      | 5.2     | 12.5    | 24.7    | 39.6    |
| all        | 11177  | 69%      | 4.7     | 11.9    | 24.6    | 40.5    |

#### Builder, by skill

| skill band | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| below 10   | 3798   | 94%      | 0.0     | 0.2     | 2.0     | 13.7    |
| 10-20      | 31003  | 93%      | 0.0     | 0.3     | 2.4     | 12.5    |
| 20-30      | 45099  | 92%      | 0.0     | 0.3     | 3.1     | 13.3    |
| 30-40      | 24892  | 92%      | 0.0     | 0.5     | 3.5     | 14.7    |
| 40 and up  | 13121  | 93%      | 0.0     | 0.4     | 2.5     | 10.3    |
| all        | 117913 | 93%      | 0.0     | 0.3     | 2.9     | 12.9    |

#### Builder, by phase

| phase      | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| 0:00-3:00  | 12809  | 98%      | 0.0     | 0.1     | 1.6     | 7.3     |
| 3:00-6:00  | 42211  | 94%      | 0.0     | 0.4     | 2.7     | 11.3    |
| 6:00-10:00 | 62893  | 90%      | 0.0     | 0.4     | 3.5     | 15.8    |
| all        | 117913 | 93%      | 0.0     | 0.3     | 2.9     | 12.9    |

#### Turret, by skill

| skill band | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| below 10   | 712    | 100%     | 0.2     | 0.2     | 0.3     | 0.4     |
| 10-20      | 7918   | 100%     | 0.2     | 0.2     | 0.3     | 0.4     |
| 20-30      | 16948  | 100%     | 0.2     | 0.2     | 0.3     | 0.4     |
| 30-40      | 9409   | 100%     | 0.2     | 0.2     | 0.3     | 0.3     |
| 40 and up  | 3902   | 100%     | 0.2     | 0.2     | 0.3     | 0.3     |
| all        | 38889  | 100%     | 0.2     | 0.2     | 0.3     | 0.4     |

#### Turret, by phase

| phase      | events | answered | p25 (s) | p50 (s) | p75 (s) | p90 (s) |
| ---------- | ------ | -------- | ------- | ------- | ------- | ------- |
| 0:00-3:00  | 353    | 100%     | 0.2     | 0.2     | 0.3     | 0.3     |
| 3:00-6:00  | 11736  | 100%     | 0.2     | 0.2     | 0.3     | 0.4     |
| 6:00-10:00 | 26800  | 100%     | 0.2     | 0.2     | 0.3     | 0.4     |
| all        | 38889  | 100%     | 0.2     | 0.2     | 0.3     | 0.4     |

## Findings

- **Players answer an idle builder in about 6 s and an idle factory in about
  13 s,** counting their own clicks: medians of 6.0 s and 13.4 s, with a long
  tail (p90 33 s and 43 s).
- **A third of the time they do not answer within a minute.** 81% of idle
  builders get a clicked order within 60 s, 63% of idle factories, and 29% of
  idle turrets, which mostly keep assisting on their own.
- **The opening is the busiest time.** In the first 3 minutes the median is
  3.0 s for a builder and 8.8 s for a factory; from 6 to 10 minutes, 7.9 s and
  14.5 s, as there is more to look at.
- **Skill changes little.** From the lowest band to the highest, the factory
  median falls from 13.7 s to 11.0 s and the builder median hardly moves.
  Attention, not speed, limits everyone.
- **Widgets answer at once.** With the widgets' commands included, 94% of idle
  builders get an order within 60 s, at a median of 0.3 s: BAR's
  idle-constructor helpers and similar widgets. That is automation, not the
  player's attention.

## What the bot does with it

Decided in [ADR 0008](../decisions/0008-play-under-human-like-limits.md): the
bot waits the clicked delays of its band (30-40) and of the game phase, by
kind of unit. It does not copy the share of idle units players leave without
an order for a minute: drawn blindly, that left a bot's first factory idle for
182 of its first 223 seconds in a lobby game, with its commander assisting it.

## Limits

- One map, the first 10 minutes, 300 games.
- A command to an idle unit is taken as the reaction to its going idle; a
  player who planned the order before the unit went idle reacts "fast" here.
- A unit that is selected with others and ordered as part of a group counts as
  answered by that order.
