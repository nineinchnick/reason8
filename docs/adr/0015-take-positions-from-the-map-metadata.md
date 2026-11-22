# 0015. Take positions from BAR's map metadata

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

The first milestone learns openings per start position
([ADR 0005](0005-start-with-team-game-openings.md)), so "position" needs one
definition that the dataset, the measurements and later the bot all share.

BAR already defines start positions. Its
[maps-metadata](https://github.com/beyond-all-reason/maps-metadata) repository
(`map_list.yaml`) holds, per map:

- recommended start positions (spawn points `P1`, `P2`, …), each with a role
  (front, tech, air, sea, or two of them), for one or more layouts: a number
  of teams and a team size;
- whether the game shows them by default;
- the default start boxes per number of teams.

The lobby sends this to every game as lobby options (`mapmetadata_startpos`,
`mapmetadata_startboxes_set`, `mapmetadata_startbox_override`), and the game
draws the recommended positions before the start. A replay therefore records
what its own game used. Lobbies can change the boxes and leave the positions
out.

What we measured on 315 games of the three slice maps
([`docs/maps/`](../maps/README.md)):

- Players start on the recommended positions: 97.1 to 98.6% of starts are
  nearer to one than half the way to the next. The median distance is 12 to
  184 map units at 45 of the 48 positions; the exceptions are the two pond
  positions of Supreme Isthmus (777 and 802: players start at the water, not
  on the point) and one air position of All That Glitters (358).
- 310 of the 315 games showed the positions. All 167 games on All That
  Glitters and Rosetta used the default boxes. On Supreme Isthmus 65 did, 1
  did not, and 82 cannot be compared, because they predate the lobby option
  and the map's default boxes changed in November 2026.
- The two sides of a map list the same roles in the same order, and open alike
  at the same place of the list: the distance between the sides in first
  factory per place is 0.04 to 0.06, the same as after shuffling teams between
  the sides (p 0.35 to 0.60).
- An earlier version of this work found the positions by clustering the start
  points of replays. It arrived at the same eight places per side.

The options were the raw start coordinates, positions clustered from replays
and kept as a table in the code, or the map metadata; and, with the metadata,
one position per spawn point or one per pair of mirrored spawn points.

## Decision

A player's position is the nearest recommended start position of their team's
side (`reason8.positions.replay_positions()`):

- The recommended positions come from the game's own `mapmetadata_startpos`
  option, and from the pinned map list when the game has none.
- The layout is the one for the game's number of teams and its largest team,
  matched exactly, as the game matches it. No layout, no positions.
- A team's side is decided for the whole team, from the mean of its start
  points. Which team gets which box changes from game to game.
- A position is its spawn point, and carries BAR's role: `P2`, tech. Every
  spawn point is a position of its own: an 8v8 map has sixteen, and `P10` is
  not `P2`, although the list gives it the same role in the same place on the
  other side.
- Every start gets its nearest spawn point and the distance to it. It is "on
  the spot" when it is nearer than half the way to the next spawn point.

Each game also records how it started (`start_setup()`): whether it showed the
recommended positions, and whether the team areas are the map's default boxes
for that number of teams (yes, no, or cannot tell).

The map list is fetched at a pinned commit into the data directory
(`reason8.map_metadata`) and read from there, which keeps it current and every
run reproducible. Tests use made-up metadata. Community names for positions
(pond, geo, …) are labels in the documents, not keys.

## Consequences

- Any map with recommended positions has positions without a replay being
  looked at: 66 of the 228 maps in the pinned list. The other maps have none.
- The dataset can carry, per player, the position, the spawn point, the role,
  the distance and whether the start is on the spot, and per game the two
  setup flags, and filter on any of them.
- A position says where a player started, not what they played. A player who
  starts next to an empty air spot may still play air; the recognition test in
  [`docs/maps/`](../maps/README.md) measures how often builds and position
  disagree.
- With sixteen positions a position has about half the openings it would have
  if mirrored spawn points were merged: 73 to 151 in our sample instead of 151
  to 298. Since the two sides open alike, a model can still share what it
  learns between them through the role and the spawn point's place in its
  side's list, which the position keeps (`Position.index`).
- Spawn point names mean nothing across maps; roles are the same words on
  every map. A model that should carry over to an unseen map has to use the
  role and the terrain.
- The pin has to be moved on purpose, and a game older than a change in the
  list is compared with data it did not use. That is why default boxes can
  come out as "cannot tell". Storing the list's history, or the defaults that
  later replays record, would settle those.
- Using the data needs one download (`python -m reason8.map_metadata`).
  Without it, only games that carry their own positions get any.
- Revisit if BAR stops sending the options or changes their format.
