# Automation widgets in replays

Some BAR widgets give orders for the player: build queues, copied constructor
queues, factory queue tricks. Their orders are recorded in the replay as if
the player gave them, so imitation would learn the widget along with the
human. This document says where a replay tells which widgets a player had,
what the slice holds, and how much of the opening dataset comes from players
with widgets that automate build orders. The decision that follows is
[ADR 0017](../decisions/0017-keep-openings-with-automation-widgets-flagged.md).
Code: `reason8/replays/widgets.py` (`reason8 widgets`) and the widget columns
of `reason8/openings/dataset.py`.

Replays of the slice as downloaded on 2026-11-24, `openings_v2` as built on
the same day.

## Where the list comes from

Since 2025-11-13 BAR ships an "Analytics - Widgets" widget
(`luaui/Widgets/ana_report_widgets.lua`, on top of the "Analytics API" widget
`api_analytics.lua`). About one second into the game (frame 30 and later) it
sends a LuaUI message, `NETMSG_LUAMSG` (packet 50, script 2000),
`complex-match-event:<base64 JSON>`, with `eventtype` `widgets_report`:

```json
{
  "eventtype": "widgets_report",
  "username": "...",
  "frame": 31,
  "widgetCount": 2,
  "truncated": false,
  "widgets": [
    {
      "name": "BuildWatch",
      "author": "...",
      "hash": "6w4OQSGYZi1Q6YNVzjDWUg==",
      "state": 1,
      "desc": "Displays organized icons for all units under construction, ..."
    }
  ]
}
```

What it holds and what it doesn't:

- Only **user widgets**: files in the player's own `LuaUI/Widgets` folder. The
  widgets that ship with the game (pregame queue, area mex, factory quota,
  build splitting in the grid menu, ...) are left out, so the report can't
  tell whether a player used those.
- Since 2025-11-14 a player without user widgets sends no report. A missing
  report means "no user widgets", or that the player turned the analytics
  widget off; the replay can't tell which.
- `state` is 1 for a widget that is enabled and running, 0 for a disabled one,
  and -1 for one that is enabled but not running. At most 50 widgets are
  listed (`truncated`); `desc` is cut at 100 characters; `hash` is the MD5 of
  the widget file.
- Spectators send reports too. A player can send more than one (1,079 players
  of the slice did, the later ones up to the end of the game); Gex keeps a
  widget as enabled if any report has it enabled, and so do we.
- The message carries the player's name. We drop it.

[Gex](https://github.com/Varunda/gex) reads the same message
(`BarDemofileParser.cs`, the `complex-match-event:` branch) into its
`BarMatchPlayerWidget` and `BarWidgetEntry` tables.

Our parser doesn't keep it: `reason8 parse` drops all Lua messages
([`replay-format.md`](../reference/replay-format.md#document)), so the parsed
replays don't hold the list. `reason8 widgets` reads it straight from the
`.sdfz` demo stream (`reason8.replays.sdfz.iter_packets()`), maps each player
to their team through the start script, and writes
`data/widgets/replays.parquet` and `data/widgets/reports.parquet`. That avoids
parsing the slice again; reading all 42,935 replays takes about 15 minutes
with 24 processes.

### Lobby options that restrict user widgets

Since 2026-01-11 a lobby can set `allowunitcontrolwidgets` to 0: user widgets
that are marked as giving orders are not loaded, and `Spring.GiveOrder*`
raises an error in every other user widget
([`doc/RestrictedUserWidgets.md`](https://github.com/beyond-all-reason/Beyond-All-Reason/blob/master/doc/RestrictedUserWidgets.md)).
`allowuserwidgets` 0 loads no user widgets, and an anonymous team-colour mode
turns them off too.

## The slice

The 42,095 games of `openings_v2` (status `ok`), 670,814 openings.

- Every replay could be read; **38,360 games (91.1%) have at least one player
  report**, 135,336 reports of players in all. Per game: median 3 reports of
  16 players (10th percentile 1, 90th 6).

- Reports per game grow steadily over the slice, with no step at any build:

  | month   | games | with a report | reports per game | unit control off |
  | ------- | ----- | ------------- | ---------------- | ---------------- |
  | 2026-05 | 2549  | 1940          | 1.57             | 2100             |
  | 2026-06 | 7612  | 5986          | 1.64             | 6482             |
  | 2026-07 | 7681  | 6490          | 2.13             | 6618             |
  | 2026-08 | 7393  | 7204          | 3.67             | 6430             |
  | 2026-09 | 6452  | 6394          | 4.28             | 5668             |
  | 2026-10 | 6338  | 6290          | 4.47             | 5328             |
  | 2026-11 | 4070  | 4056          | 4.77             | 3660             |

  So the share of players without a report shrinks over time. It is likely
  more players installing user widgets, but the data can't rule out a change
  in how many players had the analytics widget on.

- Lobby options: **36,286 games (86.2%) had `allowunitcontrolwidgets` 0**,
  5,809 allowed unit control widgets, 7 ran an anonymous colour mode (user
  widgets off). `allowuserwidgets` was 1 in every game.

- 1,605 distinct widget names (3,203 distinct files by hash). 6 reports were
  truncated.

Openings (players of the games used, status `ok`):

| openings                                      | count   | share |
| --------------------------------------------- | ------- | ----- |
| all                                           | 670,814 | 100%  |
| player sent a widget report                   | 133,493 | 19.9% |
| at least one user widget enabled              | 109,262 | 16.3% |
| an enabled widget that automates build orders | 7,906   | 1.18% |
| the same, in a game that allowed unit control | 1,098   | 0.16% |

### The most common user widgets

Reports with the widget enabled (`state` 1), all reports of players:

| widget                                  | enabled | what it does                       |
| --------------------------------------- | ------- | ---------------------------------- |
| Ping Wheel                              | 21475   | pings                              |
| Energy Conversion Meter                 | 19604   | display                            |
| BuildWatch                              | 18895   | display                            |
| Juno Shot Ranges                        | 18509   | display                            |
| Factory Queue                           | 18417   | shows and reorders a factory queue |
| Build Placement Cost                    | 17469   | display                            |
| Extended ETA Info                       | 15693   | display                            |
| Metal Tracker                           | 13539   | display                            |
| Lazy Reclaimers                         | 13387   | stops reclaim when storage is full |
| Top Bar Extra                           | 10922   | display                            |
| Build Snap (all buildings)              | 9250    | snaps placement to a grid          |
| Constructors copy queue of Constructors | 7022    | copies orders between constructors |
| Constructors GTFO                       | 6936    | moves new constructors off the lab |
| Battle Resource Tracker                 | 5305    | display                            |
| Tweakdefs Bridge                        | 5091    | display                            |
| Factory Quota With Meta                 | 4679    | sets quotas with space and click   |
| Subgroup Cycle                          | 4402    | selection                          |
| Minimap Extra - Idle Indicators         | 3922    | display                            |
| D-Gun Energy Meter                      | 3808    | display                            |
| Cheerleaders                            | 3590    | cosmetic                           |

Most user widgets show things. Of those that give orders, most act on a click
of the player (reordering a queue, snapping a placement, a blueprint) or
manage units outside openings (reclaim, repair, nano turrets, retreat).

### Widgets that automate build orders

`AUTOMATION_WIDGETS` in `reason8/replays/widgets.py`: user widgets that give
build orders the player didn't click one by one. They were picked from the
names and descriptions of every widget enabled in at least 5 reports, by
searching for build orders, queues, macro and automation. Openings with each
enabled, and whether the game allowed unit control widgets:

| widget                                  | openings | unit control on | unit control off |
| --------------------------------------- | -------- | --------------- | ---------------- |
| Constructors copy queue of Constructors | 6951     | 971             | 5980             |
| Build Orders                            | 324      | 43              | 281              |
| Factory Always-Alt Queue                | 226      | 44              | 182              |
| Build Split                             | 209      | 14              | 195              |
| OP Macro                                | 141      | 20              | 121              |
| 📋 Copy Queue v2                        | 85       | 15              | 70               |
| Economy Assist V2 (Rebuild)             | 65       | 11              | 54               |
| Build Split - alternative               | 32       | 7               | 25               |
| Macro Copilot (Safe)                    | 17       | 1               | 16               |
| Build Order Practice Bot                | 7        | 0               | 7                |
| BAR Front Macro                         | 6        | 0               | 6                |
| Apex Copilot                            | 1        | 0               | 1                |

What they do, from their descriptions:

Build Orders, OP Macro, Economy Assist V2, Macro Copilot, Build Order Practice Bot, BAR Front Macro, Apex Copilot, EcoPilot Adaptive
: Take over constructors (and nano turrets) and build an economy or a stored
  build order. These are the ones that decide *what* to build.

Constructors copy queue of Constructors, Copy Queue v2
: A constructor told to guard another copies its build orders instead, so the
  same structures appear again as orders of the second constructor. The player
  still decided what to build. 88% of the flagged openings have this one.

Build Split, Build Split - alternative
: Spread a build order over the selected constructors.

Factory Always-Alt Queue
: Queues chosen units (constructors) at the front of the factory queue.

Left out on purpose: widgets that expand one click into several orders the way
built-in features do (area mex variants, blueprints, Clone Builder, Area
Rebuild), widgets that only touch factory quotas (the quota builds already
come from BAR's own quota widget and are flagged by `quota`), and those that
repair, reclaim, resurrect, assist or move units.

## How `via` relates

Every order a widget gives, built in or user, arrives as `AICOMMAND` or
`AICOMMANDS` with `ai` 255
([`replay-format.md`](../reference/replay-format.md#commands)). `via`
therefore can't tell a user widget from a built-in one. Share of opening
orders that a widget sent (`via` not `COMMAND`), from all build-order rows of
`openings_v2`:

| unit control | report | automation | openings | widget orders | after the pregame queue | of factory orders |
| ------------ | ------ | ---------- | -------- | ------------- | ----------------------- | ----------------- |
| off          | no     | no         | 462268   | 26.3%         | 18.3%                   | 6.9%              |
| off          | yes    | no         | 109299   | 31.6%         | 23.8%                   | 11.5%             |
| off          | yes    | yes        | 6808     | 35.7%         | 28.2%                   | 10.6%             |
| on           | no     | no         | 75025    | 25.6%         | 17.6%                   | 6.9%              |
| on           | yes    | no         | 16286    | 31.8%         | 24.0%                   | 11.9%             |
| on           | yes    | yes        | 1098     | 33.2%         | 25.3%                   | 15.8%             |

"After the pregame queue" counts orders after frame 30, when the pregame queue
has been sent.

- **A quarter of every opening's orders come from widgets anyway**, mostly
  BAR's own: the pregame queue, area mex, grid-menu splitting. Players with no
  user widgets are no exception.
- Players with user widgets send 5 to 6 points more of their orders through
  widgets, automation or not. Players with automation widgets send another 1
  to 4 points more. The difference is small next to what built-in widgets
  send.
- Per widget, with unit control on (openings in brackets): Copy Queue v2 (15)
  49% of orders after the pregame from widgets, OP Macro (20) 36% and 56% of
  its factory orders, Factory Always-Alt Queue (44) 31% and 43% of factory
  orders, copy queue (971) 26%, Build Orders (43) 17%.
- **The lobby option doesn't clearly stop them.** With unit control off,
  Factory Always-Alt Queue falls to the level of players without it (7% of
  factory orders), as expected. OP Macro (121 openings) keeps the same 56% of
  factory orders and copy queue 29% of orders after the pregame, so either
  these widgets still give orders, or their users simply lean on built-in
  widgets more. The samples are small.

## What this means for the dataset

- The flagged openings are 1.2% of the dataset, and those from widgets that
  decide what to build (Build Orders, OP Macro and the other macro widgets)
  are about 0.08%. Dropping them would not change any measured share.
- The flag is a lower bound: players without a report may have had the
  analytics widget off, and the widgets were picked by name, so a renamed copy
  of one would be missed.
- A model can't learn "the widget" from `via` alone: built-in widgets already
  send a quarter of the orders of everyone.
- The copy-queue widgets don't change what is built, but they make the same
  structure appear in the orders of two constructors. Collapsing repeated
  placements at the same spot would remove that, and it would also help with
  built-in guard and split behaviour.

`openings.parquet` gets `widgets_reported`, `widgets` and
`automation_widgets`, and `games.parquet` `unit_control_widgets`
([`openings-dataset.md`](../reference/openings-dataset.md)).
