# Where players really start

A player's position
([ADR 0011](../decisions/0011-take-positions-from-the-map-metadata.md)) is
taken from the start point a replay records. That point is not always where
the player's commander started. This document measures how often, why, and
what it does to the openings; the decision is in the ADR.

Data: the opening dataset `openings_v2` (670,814 openings of 42,095 games on
the three maps of the first training slice, built on 2026-11-24) and the 2,996
of its games that were re-simulated by 2026-11-28
([ADR 0010](../decisions/0010-re-simulate-replays-headlessly-for-game-state.md)),
47,617 players. The game's rules are those of `game_initial_spawn.lua` and
`game_draft_spawn_order.lua` in BAR's `luarules/gadgets/` (read in game
version test-32096).

## How a start is chosen

Before the game, each player clicks a start point. Every click is sent to all
players as a start position message (`STARTPOS`), and the replay keeps them
all: the start picks table of the parsed replays
([`replay-format.md`](../reference/replay-format.md#tables)). The start point
in the replay's header is the player's last pick: so it is for every one of
the 47,617 players.

The game does not take every pick. BAR's spawn gadget answers each one
(`AllowStartPosition`) and refuses it:

- once the player has locked their place: BAR's ready button sends the
  LuaRules message `locking_in_place`, and `unlocking_in_place` undoes it;
- when it is within 350 map units of another team's accepted start
  (`tooCloseToSpawn`);
- outside the player's start box, or where the commander cannot stand;
- in a draft lobby (`draft_mode`), when it is not the player's turn.

A refused pick stays in the replay, and the commander starts at the player's
last accepted pick.

## How often

In the re-simulated games the state records where each commander was created
at frame 0. Against the start in the replay's header:

| map                      | players | commander elsewhere | other position |
| ------------------------ | ------- | ------------------- | -------------- |
| All That Glitters v2.2.3 | 21,561  | 5.2%                | 1.9%           |
| Supreme Isthmus v2.1     | 21,498  | 5.1%                | 1.9%           |
| Rosetta 1.4.4            | 4,558   | 4.6%                | 1.8%           |

*Commander elsewhere*: created more than 50 units from the recorded start.
*Other position*: the spawn point nearest to the commander, on the player's
side, is not the recorded position.

Replaying the refusals on the picks alone, without the LuaRules messages,
finds the real start of 9% of the moved commanders: the 350-unit rule explains
few of them. With the lock messages from the raw replays, on 60 sampled games,
it finds 80% of them (78 of 98), and gets 22 of 851 others wrong; the rest
need the draft turns.

## What it does to the openings

The first buildings of an opening are placed near the commander. Measured by
the distance from the start to the nearest of the opening's first three
structures:

| from                    | players | further than 700, by map |
| ----------------------- | ------- | ------------------------ |
| the replay's start      | 47,617  | 2.4% to 2.6%             |
| where the commander was | 47,617  | 0.1% to 0.4%             |

Of the openings built more than 700 units from the recorded start, 73% are
those of players whose commander started at another position.

Over the whole dataset, by 100 units of that distance from the recorded start:

| from (units) | openings |
| ------------ | -------- |
| 0            | 100,026  |
| 100          | 538,243  |
| 200          | 9,127    |
| 300          | 3,182    |
| 400          | 1,784    |
| 500          | 1,355    |
| 600          | 1,096    |
| 700          | 924      |
| 800          | 851      |
| 900          | 779      |
| 1,000        | 823      |
| 1,100        | 803      |
| 1,200        | 799      |
| 1,300        | 650      |
| 1,400        | 589      |

95% of openings are within 200 units. The count falls steeply to about 1,000
per 100 units at 600, and from 700 on stays about flat: buildings at some
other place, not a start position's spread. Beyond 700 are 15,971 openings:
2.1% on All That Glitters, 2.6% on Supreme Isthmus and 2.9% on Rosetta.

The nearest of three, not the median, is the measure because at two positions
of Rosetta (P4 and P12) players build their first extractor at the start and
the next ones about 1,300 units away: the median of the first three places is
beyond 700 for 62% of their openings, the nearest for 6 to 8%.

Starts that are not on the spot of their position (`on_spot`, 1.5 to 2.4% of
openings) mostly build near their own start; they are not the cause.

## In the bot's openings

`ai/Reason8/openings.json` before this was measured held 480 openings. 24 had
the median of their first three places more than 700 units from the position's
start:

- 12 genuine: the Rosetta P4 and P12 openings above;
- 2 at the limit: their player built just about 700 units from the start, or
  started 470 units off the spot;
- 10 built at another position: their player's commander did not start at the
  recorded start, or the player started off the spot.

One of them (All That Glitters, P2, Armada) was played in a lobby game: the
bot walked about 1,200 units to an ally's metal spots, its extractor steps
failed, and its opening ended at first contact without a factory.
