# 0019. End openings at first contact

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

[ADR 0017](0017-define-openings-by-time-and-split-games-by-match-id.md) made
an opening every build order of a player's first 8 minutes. An opening can
only be told apart from the rest of the game until the player meets the enemy.
After that, orders answer raids, losses and what teammates ask for. None of
those causes is in the replay's commands, so a model that sees only commands
has to treat the answers as noise.

A replay does not say when a player meets the enemy: it records commands, not
the world ([ADR 0002](0002-recover-game-state-by-re-running-replays.md)). We
played the first 12 minutes of 72 slice games again headlessly and wrote down
every first hit between two enemy units
([`first-contact.md`](../first-contact.md)):

- A player's units other than scouts are first hit by an enemy unit after a
  median of 4:08 on All That Glitters, 3:20 on Rosetta and 4:40 on Supreme
  Isthmus. 33%, 44% and 31% of the build orders of the first 8 minutes are
  given after that.
- It depends on where the player starts. Front positions are hit after 2 to
  4.5 minutes, air and sea positions after 4 to 5; most tech positions are not
  hit within 8 minutes. Within a front position the middle half of the players
  is 1 to 1.5 minutes apart.
- A side as a whole is in contact after about 2 minutes: somebody's raider has
  been shot at.
- The other ways of saying "contact" that we measured (any hit given or taken,
  scouts included, the first unit lost, 500 damage taken) move the median by
  about a minute in either direction. Leaving out commanders shooting at each
  other changes nothing.
- Re-simulating 12 minutes of an 8v8 game takes about 2.5 minutes of one core
  and 5 GB of RAM. The whole slice would take about two weeks on the machine
  we have, so for now most games have no measured contact.

The options were: keep the 8 minutes; a shorter time for every player; the
side's first contact for all its players; or each player's own first contact,
measured where the game was re-simulated and estimated from the map and the
start position where it was not.

## Decision

An **opening** is the build orders a player gives up to their **first
contact** with the enemy, and at most those of the first 8 minutes, which stay
as the opening window of ADR 0017.

**First contact** is the first frame in which a unit of the player, other than
a scout, is damaged by a unit of an enemy player
(`reason8.contact.first_contact()`). Scouts are the units built to look
(`reason8.contact.SCOUTS`).

Where an opening ends, in this order (`reason8.contact.opening_cutoff()`):

1. **Measured:** the game was re-simulated, and the opening ends at the
   player's own first contact.
2. **By position:** otherwise it ends at the median first contact measured for
   the map and the start position, the two mirrored positions of a map taken
   together. These cutoffs are a table in the code
   (`POSITION_CUTOFF_SECONDS`), written from the measurements.
3. **Window:** on a map without measurements it ends with the opening window.

The dataset built this way is `openings_v2`. Every opening and every row
carries the frame its opening ends at and which of the three it came from
(`cutoff_frame`, `cutoff_source`); the manifest carries the window, the
definition of contact, the cutoff table and the number of re-simulated games.
The window and the cutoff are parameters of the builder, and `--cutoff window`
builds the openings of ADR 0017 again.

The evaluation of
[ADR 0018](0018-evaluate-next-build-models-on-held-out-games.md) is unchanged:
the first 30 steps of every held-out opening. An opening that ends before its
30th step is scored whole.

## Consequences

- The dataset keeps 66% of the build orders of the 8-minute window. An opening
  has a median of 33 to 39 steps, depending on the map, instead of 48 to 63,
  and 68% of the openings reach the 30 scored steps instead of 96%, so the
  later steps are scored mostly on back positions.
- The orders left are the ones a commands-only model can be expected to
  predict. The chosen baseline of [`results.md`](../results.md) gets 49.5% of
  the next steps right on them, against 48.5% on the 8-minute openings of the
  same games; most of the difference is in what is scored, a little in what it
  is trained on.
- A cutoff by position is an estimate. Measured against the players' own
  contacts, 8 to 11% of the orders it keeps were given after contact and 8 to
  16% of the orders given before contact are dropped. Every re-simulated game
  replaces the estimate with a measurement, and the table is rewritten from
  `python -m reason8.contact --report` as the sample grows.
- Contact is damage. A player who has only seen the enemy, or who was asked
  for help by a teammate under attack, counts as not yet in contact; what a
  player could see is not recorded yet.
- The in-game side has the same boundary: the opening it plays should end at
  the position's cutoff or when its own units are first hit, whichever comes
  first, and hand over to BARb's reactive logic
  ([`in-game.md`](../in-game.md)).
- The measurements of the opening meta and of balance patches
  ([`maps/`](../maps/README.md), [`game-versions.md`](../game-versions.md))
  were made on the 8-minute window and are not redone here.
- Revisit when the whole slice is re-simulated (then every opening is cut at
  its own contact and the table is only needed in the game), when the state
  export records what each player could see, or when a model is given the
  state and can learn the answers too.
