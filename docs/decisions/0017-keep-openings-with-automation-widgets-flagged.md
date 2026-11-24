# 0017. Keep openings with automation widgets and flag them

- **Status:** Proposed
- **Date:** 2026-11-24

## Context

Some BAR widgets give orders for the player, and the replay records those
orders like the player's own. If many openings came from widgets that decide
what to build, imitation would learn the widget instead of the human
([ADR 0004](0004-learn-from-human-replays-by-imitation.md)). The options were
to drop those openings, keep them with a flag, or keep them as they are.

What we measured on the slice
([`automation-widgets.md`](../research/automation-widgets.md)):

- Since November 2025 every replay lists each player's *user* widgets (those
  installed by the player, not the ones shipped with the game), with whether
  they were enabled. Players without user widgets send no list. 91% of the
  games of the dataset have at least one list, and 20% of the openings come
  from players who sent one.
- 7,906 of 670,814 openings (1.2%) come from players with a user widget that
  gives build orders on its own. 88% of those are one widget that copies a
  constructor's queue to the constructors guarding it: it repeats the player's
  own orders. Widgets that decide what to build are under 0.1% of the
  openings.
- A quarter of every opening's orders are sent by widgets anyway, mostly BAR's
  built-in ones (the pregame queue, area mex). The replay tells them apart
  from clicks (`via`), but not from user widgets. Players with automation
  widgets send 1 to 4 points more of their orders through widgets than other
  players with user widgets.
- 86% of the games disallow user widgets that give orders, but some of those
  widgets still show the same effect in such games. The lobby option is not a
  reliable filter.

## Decision

Keep the openings of players with automation widgets in the dataset, and flag
them. `openings.parquet` records each player's enabled user widgets
(`widgets`), those that automate build orders (`automation_widgets`, from the
list in `reason8.replays.widgets.AUTOMATION_WIDGETS`) and whether the player
sent a widget list at all (`widgets_reported`); `games.parquet` records
whether the lobby let user widgets give orders (`unit_control_widgets`).

The first models train on every opening. The flag is for evaluation: report
accuracy on the flagged openings next to the rest, and train once without them
to see whether it matters.

## Consequences

- No opening is lost, and the dataset keeps the same games as before.
- Building the dataset needs `reason8 widgets` to have read the replays first;
  without it the widget columns are empty.
- The flag is a lower bound: it misses players who turned off BAR's analytics
  widget and widgets we don't know by name. The list of automation widgets is
  kept by hand.
- Built-in widgets stay unflagged: they are part of how every player plays,
  and `via` and `quota` already mark their orders.
- Revisit when the evaluation shows a model doing worse on, or because of, the
  flagged openings; when the share of flagged openings grows to several
  percent; or when a widget that decides openings by itself spreads.
