# Scoring how well a player played

The skill we have for a player is the rating of their account (OpenSkill). It
chooses the training games
([ADR 0014](../decisions/0014-first-training-slice.md)) and is an input of the
first model
([ADR 0019](../decisions/0019-first-model-decides-each-builders-next-order.md)),
but many things move it besides how a person plays, it can be gamed, and an
experienced player on a new account starts low. This document looks for a
score of how well someone played a game, computed from what they did in it:
first what others use, then candidates measured on our re-simulated games.
Code: `reason8/analysis/play_quality.py`.

```sh
uv run reason8 analysis play-quality             # data/state -> data/play-quality/
uv run reason8 analysis play-quality --report    # the tables below
```

## Summary

**In short: this is mostly a negative result.** No score of the first 8
minutes can stand in for the rating, and none is a usable label of how well
someone played one game. The numbers below are low, and they are meant to be
read as low: a correlation of 0.3 with the rating means a score shares about a
tenth of its variance with it, and a repeat of 0.3 means that two thirds of
what one game shows is not the player. What can be used from it:

- **Keep the rating** for choosing training games and as the model's input.
  Nothing measured here does that job better.
- **Compare economy only within a map and start position.** The position sets
  a third to three quarters of an economic score, so the in-game measures of
  the bot
  ([ADR 0003](../decisions/0003-define-success-as-in-game-measures.md)) have
  to be compared with players at the same position, as percentiles.
- **Treat new accounts with care.** Their rating has not settled and on
  average they play below it; the composite, averaged over a player's games,
  is the one place a score adds to the rating.
- **The promising score is a different kind:** how likely the builder model
  finds a player's orders, as accuracy is to chess. It needs the model first.

The findings in detail:

- **Elsewhere, scores of play predict the rating; they do not replace it.**
  StarCraft's spending quotient, APM and action latency, Age of Empires' idle
  town centre time and, with caveats, Lichess's accuracy relate to the rating,
  and are used to predict it. The one source that tests a score against what a
  rating is for, TrueSkill 2, finds that a player's kill rate in *earlier*
  games predicts winning beyond the rating, and adds it to the rating rather
  than replacing it. BAR rates by results only and says why: in-game scores
  are not direct indicators of skill and would change what players aim for.
- **Measured:** 19 candidate scores of the first 8 minutes, from the state of
  2,995 re-simulated games of the slice (47,920 player-games, 8,934 players,
  5,633 of them in two games or more), and APM for comparison.
- **The start position sets most of an economic score.** It explains 29% to
  78% of the variance of income, metal spent and the extractor counts, and
  normalising per map and position (percentile among the same position) is
  needed: it raises the correlation of the extractor times with the rating
  from 0.10 to 0.18 and of floating from 0.01 to 0.09. The faction adds under
  1.2%. Team size cannot be measured: every game is 8v8.
- **Each economic score on its own says little about the player.** After
  normalising, the scores correlate with the rating at 0.02 to 0.29 (metal
  spent 0.29, extractors by 5:00 0.23, metal income 0.18 to 0.19). They repeat
  for the same player with an intraclass correlation of 0.06 to 0.30, best for
  the time to the third extractor (0.30), the time to the first factory and
  idle build power (0.28), and reclaim orders (0.28); APM repeats at 0.51 and
  correlates with the rating at 0.41, more than any economic score.
- **A composite of five nearly independent scores** (metal spent, time to the
  third extractor, time to the first factory, idle build power, reclaim
  orders) correlates with the rating at 0.32 (0.31 to 0.32) and repeats at
  0.32 (0.31 to 0.34) per game; averaged over 10 games of a player that would
  be a reliability of about 0.82.
- **Within a game, economy says who is winning, not who played well.** Team
  income at 8:00 picks the winner with an AUC of 0.73, at 3:00 with 0.55, but
  a player's scores from their *other* games give at most 0.54 (0.52 to 0.56):
  the 8-minute economy is mostly the state of the game (most players have met
  the enemy by then), and the same player's play elsewhere predicts the result
  only slightly. The rating at the game predicts it at 0.49, because the lobby
  balances teams by rating.
- **New accounts play worse than their rating, not better.** Accounts with
  rating uncertainty of 6 or more (1,512 player-games) have a median rating of
  23.2 but a median composite at the 19th percentile; the rating starts at 25
  for everyone. For them the composite predicts where the rating goes over
  their next games (rank correlation 0.20 (0.11 to 0.27) with the change,
  after regression to the mean); for established accounts only at 0.05 (0.02
  to 0.08). This is where a score adds most to the rating.
- **Usable:** the composite, or its parts, normalised per map and position,
  averaged over several games of a player, next to the rating. **Not usable:**
  floating, overflow and stalling of metal and energy (they barely repeat or
  relate to the rating), the spend ratio, and any score taken past first
  contact as a per-game label (it measures the fight). Reclaim and
  resurrection, which set experienced players apart (ADR 0019), are only
  orders here: the state of format 5 does not record what was reclaimed.

## 1. Prior work

### StarCraft II

Spending quotient (SQ)
: A score of economic management from two numbers on the end-of-game screen,
  the resource collection rate *i* and the average unspent resources *u*: SQ =
  35 (0.00137 *i* − ln *u*) + 240. It was fitted on 2,084 ladder games of 2011
  from the observation that unspent resources grow about exponentially with
  income in every league. The Liquipedia page lists its limits: not meaningful
  in short games (its author advises against it below an income of 600 a
  minute), it differs by race (Protoss banks resources before each warp-in
  cycle), and it punishes players who bank on purpose at maximum supply
  ([Liquipedia](https://liquipedia.net/starcraft2/Spending_quotient), read in
  full; the Team Liquid thread it comes from was not read).

APM
: Liquipedia calls APM as a measure of skill "generally incorrect", because
  spamming inflates it: better players have higher APM because they know what
  needs doing, not the other way round
  ([Liquipedia](https://liquipedia.net/starcraft2/APM), read in full).

League prediction from replays
: Thompson et al. (2013) took telemetry of 3,360 players in seven leagues and
  classified neighbouring leagues with conditional inference forests. The
  importance of the variables changes with skill: *action latency* (the time
  from looking at a new part of the map to the first action there) is the
  strongest predictor in most classifiers, APM beats it only between Diamond
  and professional players, and worker production (a marker of economy)
  matters in the low leagues and not between Diamond and professionals, which
  the authors read as worker production becoming automatic. A classifier of
  the extremes only (Bronze against professionals) would have overrated hotkey
  use ([PLOS ONE](https://pmc.ncbi.nlm.nih.gov/articles/PMC3776738/), read in
  full apart from the methods' details). Chen, Aitchison and Sweetser add SQ
  to such features and predict the exact league 61.7% of the time (within one
  league 94.5%), against 47.3% before; APM is by far the most important
  feature, SQ second
  ([ANU preprint](https://openresearch-repository.anu.edu.au/bitstream/1885/213262/1/SC2_League_Prediction.pdf),
  read in full). Avontuur, Spronck and van Zaanen (AIIDE 2013) report that the
  league can be predicted after about 2.5 minutes of play from 1,297 replays
  (seen only in a search listing of the
  [abstract](https://ojs.aaai.org/index.php/AIIDE/article/view/12682); the
  site refused automated access).

AlphaStar
: Uses the rating, not a score of play: the 2019 agent's data is filtered to
  MMR above 3,500 and fine-tuned on won games above 6,200, and AlphaStar
  Unplugged takes the MMR as an input and sets it high at play time; the same
  paper found the agent ignored conditioning on the game's result
  ([`builder-model-prior-work.md`](builder-model-prior-work.md#2-skill-as-an-input),
  where these were read).

What these share: the label is still the rating (the league); the scores are
features that predict it. None of them checks whether a score measures the
player better than the league does.

### Age of Empires II and Supreme Commander (FAF)

- **Age of Empires II:** the community grades economy by idle time. AoE2
  Insights sells per-game analysis built on "six numbers coaches actually
  grade": town centre idle time until Feudal and until Castle Age, idle
  villagers, banked resources, villager work efficiency and time housed (the
  equivalent of a supply block), each benchmarked against similarly rated
  players and costed in villagers not trained
  ([product page](https://www.aoe2insights.com/premium/), read in full; how
  the numbers are computed is not given). A forum request asks for idle time
  in the game's own end statistics, which do not have it
  ([forum](https://forums.ageofempires.com/t/suggestion-improve-end-game-statistics/110846),
  search listing only). No study of these against rating or winning was found.
- **FAF:** rates with TrueSkill from results only; its wiki explains the
  rating, and the community statistics come from the database's per-game
  rating fields
  ([wiki](https://wiki.faforever.com/en/Infrastructure/Rating-System), search
  listing only). No per-game measure of play was found.

### Beyond All Reason

- **Why BAR rates by results only:** BAR's guide to OpenSkill answers "why
  can't we rate based on in-game scores?": APM, metal produced and damage
  dealt correlate with good players but none of them is a direct indicator of
  skill, they cannot represent communication or leadership, they can mislead
  (little damage to a very important place; much metal produced but wasted),
  and rating by them would shift motivations ("farm damage instead of trying
  to win"). The same guide says new players start at skill 25 with uncertainty
  8.33, that the lobby balances by mu − sigma, and that a new player "might be
  brand new to RTS gaming ... or they could be an experienced player from a
  similar game"
  ([guide](https://www.beyondallreason.info/guide/rating-and-lobby-balance),
  read in full).
- **End-of-game awards** (`luarules/gadgets/game_awards.lua`, read in full at
  the commit of 2026-09-01): the game names the top three teams by the cost of
  enemy armed units killed, of enemy economy buildings killed, by economy
  produced (energy plus 60 × metal, reclaim and excess included), by damage
  received, and an *efficiency* award: the team's share of all kills less its
  share of all economy produced, times the number of teams, given only when
  enough was killed. They are whole-game totals and reward a role as much as
  play.
- **End-of-game statistics:** the replay keeps the engine's team statistics
  (metal and energy used, produced, excess, damage, units), one sample at the
  end ([`replay-format.md`](../reference/replay-format.md)). The in-game APM
  counter is described in [`apm.md`](apm.md).

### Chess, and rating systems that use statistics

Accuracy against an engine
: Lichess turns the engine's evaluation into a win chance, Win% = 50 + 50 (2 /
  (1 + exp(−0.00368208 × centipawns)) − 1), scores a move by how much it
  lowers the mover's win chance, Accuracy% = 103.1668 exp(−0.04354 ×
  (Win%before − Win%after)) − 3.1669, and averages a game with a
  volatility-weighted and a harmonic mean. Its own page says the correlation
  with rating "is not straightforward": stronger players make more complicated
  positions, so both sides err more, and weaker players resign later, so long
  lost endgames raise accuracy; an opponent's early blunder makes high
  accuracy easy ([Lichess](https://lichess.org/page/accuracy), read in full).

Intrinsic ratings
: Regan and Haworth (2011) fit a model of a fallible player with two
  parameters, sensitivity and consistency, to how often players of a given Elo
  choose each engine-ranked move and how much they lose, and map the
  parameters back to Elo: a rating from move quality alone, free of "luck when
  opponents blunder" and of drift in the player pool
  ([paper](https://cse.buffalo.edu/faculty/regan/papers/pdf/ReHa11c.pdf),
  abstract, background and method read).

TrueSkill 2
: Microsoft's rating for Halo 5 adds a player's kills and deaths, quitting,
  squad and experience to win/loss, and predicts the winner of 68% of test
  matches against 52% for TrueSkill. Its test of kills is the one we copy: a
  player's kill rate in the *previous* match predicts winning the next one
  beyond the rating (win rates 43% to 59% across kill-rate bins where
  TrueSkill expected 48% to 50%); the current match's kills are left out
  because they come with winning it. Among its design rules: "the more control
  that a player has over a quantity, the less useful it is for skill rating",
  because a rated quantity becomes a target
  ([MSR-TR-2018-8](https://www.microsoft.com/en-us/research/wp-content/uploads/2018/03/trueskill2.pdf),
  read in full).

PlayeRank (football)
: Rates a player's match from a vector of event counts, weighted by how they
  relate to the team's result, per role, and checks the ranking against
  professional scouts ([arXiv:1802.04987](https://arxiv.org/abs/1802.04987),
  abstract only).

### What transfers

- An RTS has no engine to measure a move against, so the chess method does not
  carry over directly; the nearest thing we have is the model of
  [ADR 0019](../decisions/0019-first-model-decides-each-builders-next-order.md),
  which could score how likely each of a player's orders is (our reading).
- What the RTS sources measure is economy management (SQ, idle town centre,
  worker production) and attention (APM, action latency). Both are features
  that predict the league; neither has been shown to measure a player better
  than the league.
- TrueSkill 2's test separates a score of the player from a score of how the
  game went: a score from *other* games of the same player has to predict this
  game's result. Lichess's caveats say the same about chess: an opponent's
  blunder raises one's accuracy.
- BAR's own reason for rating by results only is incentives. A score used only
  to choose training data and as a model input, not shown to players, does not
  change what players aim for.

## 2. Measurements on our data

### Sample

The 2,995 games of `data/state` that the opening dataset has and whose replay
tables are parsed: the context sample of the decision table
([`context-dataset.md`](../reference/context-dataset.md)), 1,346 Supreme
Isthmus, 1,350 All That Glitters and 299 Rosetta games, re-simulated for their
first 10 minutes in state format 5 (resources every second, unit events, idle
lines; no features, reclaim or builders' work). Every game is ranked 8v8 with
a lobby above its map's median rating (ADR 0014). The players come from the
opening dataset (`openings_v2`): position, faction, rating and uncertainty
before the game, and the result. The account is the replay's user id.

### The scores

All are taken over the opening window, the first 8 minutes of game time, the
same for every player, not up to each player's first contact: a player who
meets the enemy later would be measured later
([`evaluation.md`](../reference/evaluation.md)). Median first contact is 3:20
to 4:40 on these maps, and 76% to 90% of players have it within 8 minutes
([`first-contact.md`](first-contact.md)), so the scores at 3:00 are mostly
before it and those at 8:00 mostly after.

`metal_income_3`, `_5`, `_8`, `energy_income_3`, `_5`, `_8`
: Mean income over the 30 seconds before 3:00, 5:00 and 8:00.

`metal_spent`
: Metal spent in the 8 minutes (the sum of the expense of every second): the
  value of what the player built and helped build.

`metal_float`, `metal_overflow`
: Share of the seconds from 1:00 with the metal store at least 95% full, and
  the metal that came in while it was full and was not spent, as a share of
  income. BAR passes a full store's income to allies with room, so this is
  income the player did not use, not always income the team lost.

`metal_stall`, `energy_stall`
: Share of the seconds from 1:00 with the store at most 1% full.

`spend_ratio`
: Metal spent over metal income from 1:00.

`first_factory`, `mex_3`, `mex_6`, `mexes_at_5`
: Seconds to the first factory finished and to the third and sixth metal
  extractor finished, and the extractors finished by 5:00. `mex_6` is missing
  for the 8% of players with fewer than six in 10 minutes.

`idle_power`, `idle_power_mobile`
: The share of the build power of the player's finished builders that stood
  idle, weighted by time: an idle line of the state starts it, the next order
  to the unit that gives it work ends it (the same rule as the decision
  table's `idle_build_power`). `_mobile` leaves out factories.

`reclaim_orders`
: Reclaim and resurrect commands the player gave, clicked or by a widget.

`apm_clicked`, `apm_all`
: For comparison: the player's own actions per minute in the window, and with
  their widgets', as [`apm.md`](apm.md) counts them.

`composite`
: The mean of the normalised `metal_spent`, `mex_3`, `first_factory`,
  `idle_power` and `reclaim_orders`, normalised again. They were chosen for
  repeating for the player and correlating little with each other (rank
  correlations −0.03 to 0.29 between them). Defaults chosen here without
  tuning: the five scores with equal weight.

Every score is turned so that more is better (the times, idleness, floating
and stalling are negated), and **normalised** as its percentile among the
player-games of the same map and start position (48 positions, 294 to 1,380
player-games each).

### Method

Rating
: Spearman correlation with the rating (mu) before the game, of the raw score
  and of the normalised one; 95% intervals by resampling games (200 times).

Position share
: The share of the variance of the raw score (ranked) between the means of the
  map and position, and what the faction adds to it.

Same player
: The intraclass correlation (ICC(1), one-way random effects) of the
  normalised score over the accounts with two games or more: the share of its
  variance between players. 1 means a player always gets the same score, 0
  that the score says nothing about the player. Intervals by resampling
  players (100 times). "Beyond the rating" is the same for the score less its
  linear fit on the rating. The rating's own ICC is high by construction: it
  changes slowly from game to game.

Winner
: Per game, the mean normalised score of one team less that of the other, and
  the AUC with which it tells the winning team (0.5: no better than a coin).
  "This game" uses the game's own scores; "other games" replaces each player's
  score by the mean of their other games in the sample, which TrueSkill 2's
  test does with the previous match: a score that measures the player has to
  predict results it did not see. For the rating, the "other games" figure is
  not a fair comparison: the ratings of later games already hold this game's
  result.

Later rating
: For player-games with at least 20 ranked Large Team games after them in the
  match dump: the rank correlation of the normalised score with the change of
  the player's rating from just after this game to their last game in the
  dump, less what the rating predicts of that change (regression to the mean).

### The rating and the start position

| score               | rating, raw |     rating, normalised | position share |
| ------------------- | ----------: | ---------------------: | -------------: |
| `metal_income_3`    |        0.30 |    0.18 (0.17 to 0.19) |           0.36 |
| `metal_income_5`    |        0.27 |    0.18 (0.17 to 0.19) |           0.36 |
| `metal_income_8`    |        0.29 |    0.19 (0.18 to 0.20) |           0.29 |
| `energy_income_3`   |        0.18 |    0.14 (0.13 to 0.15) |           0.30 |
| `energy_income_5`   |        0.10 |    0.06 (0.05 to 0.07) |           0.33 |
| `energy_income_8`   |        0.08 |    0.06 (0.05 to 0.07) |           0.23 |
| `metal_spent`       |        0.37 |    0.29 (0.28 to 0.30) |           0.54 |
| `metal_float`       |        0.01 |    0.09 (0.08 to 0.10) |           0.08 |
| `metal_overflow`    |        0.01 |    0.09 (0.09 to 0.10) |           0.07 |
| `metal_stall`       |        0.08 |    0.05 (0.04 to 0.06) |           0.06 |
| `energy_stall`      |        0.00 |    0.02 (0.01 to 0.03) |           0.10 |
| `spend_ratio`       |       -0.15 | -0.11 (-0.12 to -0.11) |           0.26 |
| `first_factory`     |        0.09 |    0.07 (0.06 to 0.08) |           0.55 |
| `mex_3`             |        0.10 |    0.18 (0.17 to 0.18) |           0.55 |
| `mex_6`             |        0.15 |    0.22 (0.22 to 0.23) |           0.61 |
| `mexes_at_5`        |        0.19 |    0.23 (0.22 to 0.24) |           0.78 |
| `idle_power`        |        0.06 |    0.11 (0.10 to 0.12) |           0.13 |
| `idle_power_mobile` |        0.06 |    0.10 (0.09 to 0.11) |           0.11 |
| `reclaim_orders`    |        0.20 |    0.17 (0.16 to 0.18) |           0.42 |
| `apm_clicked`       |        0.43 |    0.41 (0.40 to 0.42) |           0.34 |
| `apm_all`           |        0.48 |    0.49 (0.49 to 0.50) |           0.46 |
| `skill`             |        1.00 |    0.89 (0.89 to 0.90) |           0.17 |
| `composite`         |        0.32 |    0.32 (0.31 to 0.32) |           0.00 |

Normalising matters most where the position decides how much there is to take:
the extractors (55% to 78% of the variance between positions) and the metal
spent (54%). Their correlation with the rating rises after normalising,
because strong players and weak ones are spread over positions that differ
more than they do. The incomes at fixed minutes fall instead (0.30 to 0.18 at
3:00): part of what they had with the rating was which position strong players
take. The rating itself differs between positions (17% of its variance).
Floating and stalling hardly relate to the rating either way.

### The same player

| score               |                 ICC | ICC beyond the rating |
| ------------------- | ------------------: | --------------------: |
| `metal_income_3`    | 0.17 (0.16 to 0.18) |                  0.14 |
| `metal_income_5`    | 0.10 (0.10 to 0.11) |                  0.08 |
| `metal_income_8`    | 0.11 (0.10 to 0.11) |                  0.08 |
| `energy_income_3`   | 0.14 (0.13 to 0.15) |                  0.12 |
| `energy_income_5`   | 0.13 (0.12 to 0.13) |                  0.12 |
| `energy_income_8`   | 0.12 (0.11 to 0.13) |                  0.12 |
| `metal_spent`       | 0.22 (0.20 to 0.23) |                  0.16 |
| `metal_float`       | 0.07 (0.06 to 0.08) |                  0.07 |
| `metal_overflow`    | 0.06 (0.05 to 0.07) |                  0.06 |
| `metal_stall`       | 0.18 (0.17 to 0.19) |                  0.18 |
| `energy_stall`      | 0.09 (0.08 to 0.10) |                  0.09 |
| `spend_ratio`       | 0.11 (0.10 to 0.12) |                  0.10 |
| `first_factory`     | 0.28 (0.27 to 0.30) |                  0.28 |
| `mex_3`             | 0.30 (0.28 to 0.32) |                  0.28 |
| `mex_6`             | 0.21 (0.20 to 0.22) |                  0.17 |
| `mexes_at_5`        | 0.16 (0.15 to 0.17) |                  0.12 |
| `idle_power`        | 0.28 (0.27 to 0.29) |                  0.27 |
| `idle_power_mobile` | 0.26 (0.25 to 0.27) |                  0.26 |
| `reclaim_orders`    | 0.28 (0.26 to 0.29) |                  0.26 |
| `apm_clicked`       | 0.51 (0.49 to 0.52) |                  0.42 |
| `apm_all`           | 0.55 (0.53 to 0.57) |                  0.43 |
| `skill`             | 0.82 (0.81 to 0.83) |                  0.54 |
| `composite`         | 0.32 (0.31 to 0.34) |                  0.26 |

A single game is a noisy measurement of the player for every score. The better
ones repeat at 0.28 to 0.30, close to what they keep after the rating is taken
out (0.26 to 0.28): what repeats is mostly not the rating. With an ICC of r
per game, the mean of k games has a reliability of k r / (1 + (k − 1) r)
(Spearman–Brown): for the composite's 0.32, 0.70 at 5 games and 0.82 at 10.
Income at 5:00 and 8:00 repeats less than at 3:00, because the fight comes
into it.

### The winner

| score               |      AUC, this game |    AUC, other games |
| ------------------- | ------------------: | ------------------: |
| `metal_income_3`    | 0.55 (0.53 to 0.57) | 0.53 (0.51 to 0.55) |
| `metal_income_5`    | 0.63 (0.62 to 0.65) | 0.53 (0.51 to 0.55) |
| `metal_income_8`    | 0.73 (0.71 to 0.75) | 0.52 (0.49 to 0.54) |
| `energy_income_3`   | 0.58 (0.56 to 0.60) | 0.52 (0.50 to 0.54) |
| `energy_income_5`   | 0.57 (0.55 to 0.58) | 0.51 (0.49 to 0.53) |
| `energy_income_8`   | 0.65 (0.63 to 0.67) | 0.50 (0.48 to 0.51) |
| `metal_spent`       | 0.72 (0.71 to 0.74) | 0.52 (0.50 to 0.53) |
| `metal_float`       | 0.51 (0.49 to 0.53) | 0.49 (0.47 to 0.51) |
| `metal_overflow`    | 0.51 (0.48 to 0.53) | 0.49 (0.47 to 0.51) |
| `metal_stall`       | 0.52 (0.50 to 0.55) | 0.52 (0.50 to 0.54) |
| `energy_stall`      | 0.52 (0.50 to 0.54) | 0.51 (0.49 to 0.52) |
| `spend_ratio`       | 0.43 (0.41 to 0.45) | 0.48 (0.46 to 0.49) |
| `first_factory`     | 0.53 (0.51 to 0.55) | 0.51 (0.49 to 0.54) |
| `mex_3`             | 0.54 (0.52 to 0.55) | 0.51 (0.49 to 0.53) |
| `mex_6`             | 0.54 (0.53 to 0.56) | 0.53 (0.51 to 0.55) |
| `mexes_at_5`        | 0.58 (0.56 to 0.60) | 0.54 (0.52 to 0.56) |
| `idle_power`        | 0.53 (0.51 to 0.55) | 0.52 (0.50 to 0.54) |
| `idle_power_mobile` | 0.54 (0.52 to 0.56) | 0.52 (0.50 to 0.54) |
| `reclaim_orders`    | 0.54 (0.52 to 0.56) | 0.51 (0.49 to 0.53) |
| `apm_clicked`       | 0.52 (0.49 to 0.54) | 0.53 (0.50 to 0.55) |
| `apm_all`           | 0.56 (0.54 to 0.58) | 0.53 (0.51 to 0.55) |
| `skill`             | 0.49 (0.48 to 0.51) | 0.58 (0.56 to 0.60) |
| `composite`         | 0.65 (0.63 to 0.67) | 0.53 (0.51 to 0.55) |

Economy late in the window tells the winner (0.73 at 8:00) because it is the
game's state: the team that wins the first fights keeps more extractors. At
3:00, before most contact, income tells it at 0.55. From the other games the
best scores reach 0.53 to 0.54, with intervals that just clear 0.5; the
composite 0.53 (0.51 to 0.55). The rating at the game tells it at 0.49 (0.48
to 0.51): the lobby balances teams by rating (by mu − sigma,
[guide](https://www.beyondallreason.info/guide/rating-and-lobby-balance)), so
the difference between teams is small and what is left of it is noise. A
logistic regression on the rating and a score together (cross-validated)
changes the score's AUC by at most 0.01 (the spend ratio's is turned the other
way round), so the rating adds nothing to it.

### Between the scores

After normalising, most candidates are nearly independent of each other (rank
correlations within ±0.2). The exceptions are what one would expect: floating
and overflow (0.97), the two idle shares (0.88), metal spent with income at
8:00 (0.58) and with income at 5:00 (0.47), the sixth extractor with income at
3:00 (0.47) and with extractors by 5:00 (0.48). The time to the third
extractor, the first factory, idle build power and reclaim orders correlate
with each other at 0.06 or less, and with APM at 0.15 or less: they measure
different things, each of them a little.

### New accounts

| uncertainty | player-games | players | median rating | composite, median percentile | composite and rating |
| ----------- | -----------: | ------: | ------------: | ---------------------------: | -------------------: |
| below 4     |       42,371 |   6,095 |          28.8 |                           53 |                 0.28 |
| 4 to 6      |        4,037 |   2,837 |          19.3 |                           30 |                 0.25 |
| 6 and up    |        1,512 |   1,328 |          23.2 |                           19 |                 0.09 |

The issue asks for new accounts that play like veterans. In this sample the
new accounts play worse than their rating says: at the 19th percentile with a
median rating of 23.2, against the 53rd at 28.8 for established ones. Their
composite hardly follows their rating (0.09), so for them the two disagree
most, and the composite is the better guess of the two:

| accounts             | score            | player-games | players | correlation with the later change |
| -------------------- | ---------------- | -----------: | ------: | --------------------------------: |
| all accounts         | `composite`      |       41,325 |   6,723 |               0.05 (0.02 to 0.08) |
| all accounts         | `mex_3`          |       41,325 |   6,723 |               0.06 (0.04 to 0.08) |
| uncertainty 6 and up | `composite`      |          755 |     637 |               0.20 (0.11 to 0.27) |
| uncertainty 6 and up | `metal_spent`    |          755 |     637 |               0.17 (0.09 to 0.25) |
| uncertainty 6 and up | `mex_3`          |          755 |     637 |               0.14 (0.08 to 0.21) |
| uncertainty 6 and up | `reclaim_orders` |          755 |     637 |               0.13 (0.06 to 0.20) |
| uncertainty 6 and up | `first_factory`  |          755 |     637 |              0.07 (−0.00 to 0.14) |
| uncertainty 6 and up | `idle_power`     |          755 |     637 |              0.05 (−0.02 to 0.11) |

A new account's opening predicts where its rating goes over the following
games; an established account's barely does, since its rating has already
absorbed what the score says. Experienced players on new accounts are surely
among the new accounts, but with this sample they cannot be told from the
rest: the slice keeps lobbies above the median, so few new accounts are in it
at all.

## What the evidence supports

- A score from the opening can be computed for every re-simulated game, and it
  measures something of the player: the composite repeats at 0.32 per game,
  beyond the rating at 0.26, and correlates with the rating at 0.32. It does
  not measure the player as well as the rating: APM, which nobody counts as
  skill, relates to the rating more (0.41) and repeats more (0.51).
- As a label of *one game* the scores are weak: one game is mostly noise about
  the player, and past first contact the economy measures the fight. As a
  measure of a *player*, averaged over their games, the composite is reliable
  (about 0.8 at 10 games) and complements the rating, most of all for new
  accounts, where the rating has not settled.
- Nothing here shows that a score picks better training games than the rating,
  or that a model uses it better as an input; that needs the model.

What adopting a score would take:

- **Re-simulated games for every game it scores**, since every candidate needs
  the state; ADR 0019 already needs them for the decision table.
- **Normalising per map and position** from enough games of each, and a rule
  for positions with few (the 48 here have 294 or more).
- **The reclaim and resurrection that experienced players are known for:**
  state format 6 or later records what each team reclaimed, which games of
  format 5 cannot give (`state-extraction.md`). The scores here should be
  measured again on those games, with reclaimed metal in place of reclaim
  orders.
- **A test with the model**, as ADR 0019 asks of the rating: train on the
  slice chosen or weighted by the per-player composite and by the rating, and
  with the composite and the rating as inputs, and compare on held-out games
  and then in the game.
- **A score of the orders themselves**, as accuracy is to chess: once the
  model predicts every builder's next order, how likely it finds a player's
  orders compared with those of strong players is a score that needs no
  hand-chosen measure. Lichess's caveats would apply: the position, not only
  the player, sets how hard the right move is.

## Sources not read in full

- *Abstract or listing only:* Avontuur, Spronck and van Zaanen (AIIDE 2013,
  the site refused automated access), PlayeRank
  ([arXiv:1802.04987](https://arxiv.org/abs/1802.04987)), the FAF wiki's
  rating page (the page needs a browser; seen through a search listing), the
  Age of Empires forum request.
- *Partly read:* Thompson et al. (methods' details skipped), Regan and Haworth
  (abstract, background and method).
- *Not read:* the Team Liquid thread that introduced the spending quotient,
  the AlphaStar papers beyond what
  [`builder-model-prior-work.md`](builder-model-prior-work.md) records,
  supply-block measures (Liquipedia has no page that could be read), and
  community measures for FAF and BAR beyond the game's own awards and
  statistics; none were found.
