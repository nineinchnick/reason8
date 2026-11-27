# Results: predicting the next build

The numbers later models are compared against. Every model predicts the unit
of the next step of an opening (a drag of buildings or a quick run of clicks
on one unit is one step), from the steps before it and what is known before
the game: the player's faction, the map and the start position. An opening
ends at the player's first contact with the enemy
([ADR 0012](decisions/0012-end-openings-at-first-contact.md)). The protocol is
[ADR 0013](decisions/0013-evaluate-on-held-out-games.md), the data
[`openings-dataset.md`](reference/openings-dataset.md). Code:
`reason8/models/`.

```sh
uv run reason8 baseline                 # validation: compare and choose
uv run reason8 baseline --split test    # the tables below
```

## The models

uniform
: Every unit equally likely. Its top-1 is 0%, because the true unit ties with
  all others and ties count against the model.

unit frequency, unit frequency per faction
: The most ordered units, overall or of the player's faction, whatever came
  before.

repeat the previous step
: The unit of the previous step, with the share of steps that repeat the one
  before them in training; the rest by the faction's frequencies.

bigram, trigram, 4-gram, faction
: The next unit after the previous one, two or three steps of the same
  faction. The start of the opening counts as a step, so the first steps are
  predicted from what players of the faction do first.

trigram, faction and map; and role; and position
: The faction trigram, told the map, the map and the role of the start
  position, or the map and the position itself: each history length is tried
  with that condition first and then without it.

4-gram, faction, map and position
: The same with three previous steps.

The n-grams interpolate from the most specific context down to plain unit
frequencies and then to the uniform distribution, with Witten-Bell weights: a
context is trusted as much as it has seen different next units. Each model is
counted on every step of the training openings and scored on the first 30
steps of each held-out opening.

## Data

The dataset `openings_v2` as built on 2026-11-24 from the 42,904 parsed
replays of the slice ([`openings-dataset.md`](reference/openings-dataset.md)):
33,657 training games, 4,168 validation games and 4,270 test games, with
openings that end at first contact. The models were compared on validation and
the tables below are on test.

## Validation

| model                              | top-1             | top-3             | log-loss            |
| ---------------------------------- | ----------------- | ----------------- | ------------------- |
| uniform                            | 0.0% (0.0–0.0)    | 0.0% (0.0–0.0)    | 6.219 (6.219–6.219) |
| unit frequency                     | 10.8% (10.7–11.0) | 30.9% (30.7–31.1) | 3.839 (3.829–3.848) |
| unit frequency per faction         | 19.8% (19.6–19.9) | 43.0% (42.8–43.1) | 3.118 (3.112–3.125) |
| repeat the previous step           | 32.1% (32.0–32.2) | 51.9% (51.8–52.1) | 2.871 (2.864–2.877) |
| bigram, faction                    | 39.5% (39.4–39.6) | 65.6% (65.4–65.7) | 2.125 (2.120–2.130) |
| trigram, faction                   | 43.2% (43.1–43.3) | 70.3% (70.2–70.4) | 1.953 (1.948–1.957) |
| 4-gram, faction                    | 45.3% (45.2–45.4) | 72.3% (72.2–72.4) | 1.876 (1.872–1.881) |
| trigram, faction and map           | 44.6% (44.5–44.7) | 71.3% (71.2–71.4) | 1.905 (1.900–1.909) |
| trigram, faction, map and role     | 45.5% (45.4–45.6) | 72.8% (72.7–72.9) | 1.812 (1.808–1.817) |
| trigram, faction, map and position | 46.1% (46.0–46.3) | 73.5% (73.4–73.6) | 1.793 (1.789–1.798) |
| 4-gram, faction, map and position  | 48.0% (47.9–48.1) | 74.8% (74.7–74.9) | 1.781 (1.776–1.786) |

The lowest log-loss is `4-gram, faction, map and position` (1.781), which is
the model the detailed tables are about and the one that is saved.

## Test

Trained on 33657 games (536288 openings), scored on the test split: 4270
games, 68067 openings, the first 30 steps of each. Intervals are 95%, from
resampling games.

### All models

| model                              | top-1             | top-3             | log-loss            |
| ---------------------------------- | ----------------- | ----------------- | ------------------- |
| uniform                            | 0.0% (0.0–0.0)    | 0.0% (0.0–0.0)    | 6.219 (6.219–6.219) |
| unit frequency                     | 10.7% (10.6–10.9) | 30.9% (30.8–31.1) | 3.835 (3.824–3.844) |
| unit frequency per faction         | 19.8% (19.7–19.9) | 43.0% (42.8–43.2) | 3.113 (3.107–3.119) |
| repeat the previous step           | 32.3% (32.1–32.4) | 52.0% (51.9–52.2) | 2.864 (2.857–2.870) |
| bigram, faction                    | 39.6% (39.5–39.7) | 65.6% (65.5–65.8) | 2.122 (2.117–2.126) |
| trigram, faction                   | 43.3% (43.2–43.4) | 70.4% (70.3–70.5) | 1.947 (1.942–1.952) |
| 4-gram, faction                    | 45.4% (45.3–45.5) | 72.4% (72.3–72.6) | 1.870 (1.865–1.875) |
| trigram, faction and map           | 44.7% (44.6–44.8) | 71.4% (71.3–71.5) | 1.898 (1.893–1.902) |
| trigram, faction, map and role     | 45.7% (45.6–45.8) | 72.9% (72.8–73.0) | 1.806 (1.802–1.811) |
| trigram, faction, map and position | 46.3% (46.2–46.4) | 73.5% (73.5–73.6) | 1.788 (1.784–1.792) |
| 4-gram, faction, map and position  | 48.1% (48.0–48.2) | 74.9% (74.8–75.0) | 1.773 (1.768–1.778) |

1795375 steps scored per model. Chosen on validation log-loss:
`4-gram, faction, map and position`.

`trigram, faction` on raw orders (no orders merged), for comparison with the
measurements in docs/research/game-versions.md and docs/research/maps/: 60.4%
(60.3–60.5), 81.4% (81.4–81.5), 1.458 (1.455–1.462) over 1983212 orders.

The tables below are for `4-gram, faction, map and position`. The last column
is its top-1 minus that of `trigram, faction` on the same steps, in points,
with a paired interval.

### By step of the opening

| step  | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference     |
| ----- | ----- | ------ | ----------------- | ----------------- | ------------------- | ---------------------- |
| 1     | 4270  | 68067  | 96.7% (96.5–96.8) | 99.5% (99.4–99.5) | 0.152 (0.146–0.159) | +5.7 (+5.6 to +5.9)    |
| 2–5   | 4270  | 272218 | 49.8% (49.6–50.1) | 83.6% (83.4–83.7) | 1.421 (1.415–1.427) | +15.2 (+14.9 to +15.4) |
| 6–10  | 4270  | 339365 | 43.9% (43.7–44.1) | 74.5% (74.3–74.7) | 1.784 (1.777–1.790) | +4.3 (+4.2 to +4.5)    |
| 11–20 | 4270  | 636684 | 45.0% (44.9–45.2) | 71.9% (71.8–72.1) | 1.914 (1.907–1.922) | +2.7 (+2.6 to +2.8)    |
| 21–30 | 4270  | 479041 | 47.4% (47.2–47.6) | 70.9% (70.7–71.0) | 2.008 (1.999–2.017) | +2.0 (+1.9 to +2.1)    |

### By map

| map                      | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------------------------ | ----- | ------ | ----------------- | ----------------- | ------------------- | ------------------- |
| All That Glitters v2.2.3 | 1961  | 873804 | 49.3% (49.2–49.5) | 76.3% (76.1–76.4) | 1.699 (1.694–1.705) | +4.7 (+4.6 to +4.8) |
| Rosetta 1.4.4            | 128   | 50284  | 47.8% (47.3–48.3) | 76.4% (75.9–76.8) | 1.760 (1.734–1.789) | +9.0 (+8.5 to +9.4) |
| Supreme Isthmus v2.1     | 2181  | 871287 | 46.9% (46.8–47.1) | 73.5% (73.4–73.7) | 1.847 (1.840–1.854) | +4.8 (+4.7 to +4.9) |

### By faction

| faction | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------- | ----- | ------ | ----------------- | ----------------- | ------------------- | ------------------- |
| Armada  | 4270  | 965788 | 48.7% (48.6–48.8) | 75.9% (75.8–76.0) | 1.732 (1.727–1.738) | +5.0 (+4.9 to +5.1) |
| Cortex  | 4270  | 787362 | 47.6% (47.4–47.8) | 74.0% (73.9–74.2) | 1.803 (1.796–1.810) | +4.8 (+4.7 to +5.0) |
| Legion  | 435   | 42225  | 44.7% (44.1–45.4) | 70.2% (69.6–70.9) | 2.143 (2.103–2.186) | +2.4 (+2.0 to +2.9) |

### By era

| era                                 | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ----------------------------------- | ----- | ------ | ----------------- | ----------------- | ------------------- | ------------------- |
| Air constructors and mobile jammers | 1306  | 552290 | 48.4% (48.2–48.6) | 75.3% (75.1–75.5) | 1.756 (1.748–1.764) | +5.0 (+4.8 to +5.1) |
| August balance patch                | 568   | 242023 | 48.5% (48.3–48.8) | 75.3% (75.0–75.6) | 1.754 (1.740–1.768) | +5.0 (+4.8 to +5.2) |
| July balance patch                  | 771   | 323496 | 48.2% (47.9–48.4) | 75.0% (74.8–75.3) | 1.767 (1.756–1.778) | +5.0 (+4.9 to +5.2) |
| May balance patch                   | 1426  | 595126 | 47.7% (47.5–47.9) | 74.5% (74.3–74.6) | 1.794 (1.785–1.804) | +4.6 (+4.5 to +4.8) |
| Season 3                            | 199   | 82440  | 47.4% (46.9–47.9) | 74.2% (73.7–74.7) | 1.813 (1.789–1.836) | +4.4 (+4.0 to +4.7) |

### By map and position

#### All That Glitters v2.2.3

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 1957     | 52684 | 44.8% (44.2–45.3) | 72.5% (72.1–72.9) | 1.883 (1.864–1.901) | +4.0 (+3.6 to +4.4) |
| P2       | 1944     | 51280 | 43.8% (43.3–44.3) | 70.4% (69.9–71.0) | 1.957 (1.933–1.980) | +4.6 (+4.2 to +5.0) |
| P3       | 1944     | 58062 | 47.9% (47.4–48.4) | 77.5% (77.0–77.9) | 1.679 (1.661–1.699) | +3.8 (+3.4 to +4.1) |
| P4       | 1929     | 54649 | 46.9% (46.4–47.5) | 74.7% (74.3–75.2) | 1.793 (1.771–1.814) | +4.4 (+4.0 to +4.8) |
| P5       | 1976     | 50535 | 46.8% (46.3–47.3) | 74.4% (73.9–74.9) | 1.784 (1.764–1.806) | +4.7 (+4.3 to +5.1) |
| P6       | 1961     | 56621 | 53.9% (53.3–54.4) | 79.2% (78.8–79.6) | 1.539 (1.521–1.557) | +5.0 (+4.6 to +5.3) |
| P7       | 1994     | 58013 | 54.2% (53.7–54.7) | 80.2% (79.9–80.6) | 1.515 (1.498–1.532) | +5.9 (+5.5 to +6.3) |
| P8       | 1967     | 55576 | 54.0% (53.5–54.5) | 79.5% (79.1–79.9) | 1.523 (1.506–1.541) | +5.5 (+5.1 to +5.9) |
| P9       | 1936     | 51920 | 44.1% (43.6–44.6) | 72.2% (71.7–72.7) | 1.912 (1.892–1.931) | +3.7 (+3.3 to +4.0) |
| P10      | 1958     | 51452 | 44.7% (44.2–45.2) | 70.5% (70.0–71.0) | 1.946 (1.922–1.967) | +4.6 (+4.2 to +5.0) |
| P11      | 1942     | 57959 | 48.9% (48.4–49.3) | 78.2% (77.8–78.6) | 1.650 (1.633–1.668) | +3.9 (+3.6 to +4.2) |
| P12      | 1930     | 54546 | 46.8% (46.2–47.3) | 74.5% (74.1–75.1) | 1.786 (1.765–1.805) | +4.1 (+3.7 to +4.5) |
| P13      | 1980     | 50533 | 47.3% (46.8–47.8) | 74.6% (74.1–75.0) | 1.771 (1.750–1.789) | +5.1 (+4.6 to +5.5) |
| P14      | 1998     | 57509 | 53.7% (53.1–54.1) | 79.2% (78.7–79.6) | 1.549 (1.531–1.569) | +4.5 (+4.1 to +4.8) |
| P15      | 1976     | 57739 | 54.7% (54.2–55.2) | 80.5% (80.1–81.0) | 1.495 (1.478–1.512) | +5.6 (+5.2 to +6.0) |
| P16      | 1943     | 54726 | 54.6% (54.0–55.1) | 79.6% (79.2–80.0) | 1.513 (1.495–1.533) | +6.0 (+5.5 to +6.4) |

#### Rosetta 1.4.4

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference     |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ---------------------- |
| P1       | 131      | 3121  | 45.6% (43.5–47.6) | 75.7% (73.7–77.5) | 1.797 (1.715–1.882) | +6.0 (+4.4 to +7.5)    |
| P2       | 122      | 3647  | 46.8% (44.8–48.8) | 75.0% (72.6–77.2) | 1.945 (1.730–2.269) | +9.2 (+7.6 to +10.7)   |
| P3       | 125      | 3197  | 50.1% (47.8–52.3) | 78.5% (76.4–80.6) | 1.633 (1.557–1.708) | +8.4 (+6.7 to +10.2)   |
| P4       | 106      | 2118  | 45.8% (43.4–48.2) | 73.0% (70.8–75.2) | 1.864 (1.771–1.957) | +9.7 (+7.8 to +11.5)   |
| P5       | 118      | 2647  | 44.7% (42.4–47.0) | 68.6% (66.6–70.7) | 2.141 (2.037–2.252) | +9.2 (+7.5 to +10.9)   |
| P6       | 126      | 3244  | 46.0% (44.1–47.8) | 77.3% (75.6–79.0) | 1.706 (1.639–1.774) | +7.4 (+5.7 to +8.9)    |
| P7       | 119      | 3568  | 48.2% (46.4–50.1) | 79.0% (77.1–80.7) | 1.660 (1.590–1.736) | +10.5 (+9.4 to +11.7)  |
| P8       | 126      | 3542  | 50.0% (48.2–51.8) | 80.0% (78.2–81.6) | 1.595 (1.531–1.665) | +7.8 (+6.4 to +9.1)    |
| P9       | 128      | 2934  | 46.9% (44.9–49.0) | 73.4% (71.3–75.5) | 1.804 (1.725–1.895) | +8.8 (+7.0 to +10.6)   |
| P10      | 116      | 3480  | 48.6% (47.0–50.5) | 77.4% (75.7–79.0) | 1.706 (1.632–1.781) | +11.8 (+10.4 to +13.2) |
| P11      | 129      | 3248  | 48.3% (46.4–50.3) | 77.3% (75.7–79.0) | 1.709 (1.639–1.777) | +7.5 (+6.0 to +9.0)    |
| P12      | 107      | 2239  | 46.4% (43.8–49.0) | 73.2% (71.1–75.4) | 1.828 (1.738–1.915) | +8.5 (+6.6 to +10.7)   |
| P13      | 122      | 2908  | 44.3% (42.6–46.2) | 68.3% (66.5–70.2) | 2.167 (2.069–2.265) | +8.3 (+6.6 to +9.9)    |
| P14      | 125      | 3321  | 49.7% (48.1–51.4) | 78.7% (77.2–80.1) | 1.648 (1.587–1.709) | +10.4 (+9.1 to +11.7)  |
| P15      | 120      | 3591  | 49.3% (47.6–51.1) | 80.6% (78.6–82.5) | 1.586 (1.510–1.662) | +10.2 (+8.9 to +11.5)  |
| P16      | 124      | 3479  | 51.1% (49.3–53.0) | 80.2% (78.6–81.9) | 1.590 (1.525–1.659) | +9.6 (+8.2 to +11.0)   |

#### Supreme Isthmus v2.1

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 2138     | 58967 | 46.7% (46.2–47.2) | 70.7% (70.2–71.1) | 1.950 (1.927–1.972) | +4.4 (+4.0 to +4.7) |
| P2       | 2171     | 64653 | 53.6% (53.2–54.1) | 80.8% (80.4–81.1) | 1.496 (1.479–1.515) | +4.3 (+4.1 to +4.6) |
| P3       | 2163     | 54667 | 43.6% (43.1–44.0) | 69.3% (68.9–69.8) | 1.926 (1.906–1.944) | +3.3 (+3.0 to +3.6) |
| P4       | 2179     | 55220 | 46.8% (46.3–47.4) | 72.2% (71.6–72.7) | 2.028 (1.999–2.057) | +6.1 (+5.8 to +6.4) |
| P5       | 2212     | 41897 | 44.7% (44.1–45.3) | 76.2% (75.6–76.7) | 1.695 (1.675–1.715) | +9.3 (+8.7 to +9.9) |
| P6       | 2214     | 39631 | 45.0% (44.4–45.6) | 75.6% (75.0–76.1) | 1.696 (1.676–1.714) | +5.7 (+5.2 to +6.3) |
| P7       | 2162     | 64072 | 47.9% (47.5–48.4) | 74.1% (73.7–74.5) | 1.843 (1.822–1.864) | +4.3 (+4.1 to +4.6) |
| P8       | 2157     | 56800 | 44.7% (44.2–45.2) | 69.8% (69.4–70.3) | 2.091 (2.065–2.118) | +2.4 (+2.1 to +2.8) |
| P9       | 2135     | 59498 | 47.0% (46.6–47.5) | 71.2% (70.8–71.7) | 1.938 (1.915–1.961) | +4.6 (+4.2 to +4.9) |
| P10      | 2192     | 65349 | 53.4% (53.0–53.9) | 80.8% (80.5–81.2) | 1.497 (1.481–1.514) | +4.1 (+3.8 to +4.3) |
| P11      | 2175     | 54658 | 43.1% (42.6–43.6) | 68.9% (68.4–69.3) | 1.949 (1.931–1.970) | +3.0 (+2.7 to +3.3) |
| P12      | 2157     | 53824 | 46.7% (46.2–47.3) | 72.0% (71.5–72.6) | 2.052 (2.019–2.082) | +5.9 (+5.6 to +6.2) |
| P13      | 2219     | 41657 | 44.6% (44.0–45.3) | 75.9% (75.4–76.5) | 1.701 (1.680–1.722) | +9.1 (+8.5 to +9.7) |
| P14      | 2187     | 39019 | 45.1% (44.4–45.6) | 75.0% (74.5–75.5) | 1.704 (1.683–1.724) | +6.3 (+5.8 to +7.0) |
| P15      | 2158     | 63893 | 48.0% (47.4–48.5) | 74.1% (73.7–74.6) | 1.842 (1.818–1.868) | +4.3 (+4.0 to +4.5) |
| P16      | 2169     | 57482 | 45.1% (44.6–45.6) | 69.8% (69.3–70.2) | 2.094 (2.071–2.120) | +2.4 (+2.1 to +2.7) |

## Until first contact, against the first 8 minutes

The same replays built both ways (`--cutoff window` builds the 8-minute
openings), the same games in every split, `4-gram, faction, map and position`,
which validation chooses in both, on test:

| trained on          | scored on           | openings | steps   | top-1             | top-3             | log-loss            |
| ------------------- | ------------------- | -------- | ------- | ----------------- | ----------------- | ------------------- |
| the first 8 minutes | the first 8 minutes | 67902    | 2000040 | 46.4% (46.3–46.5) | 72.6% (72.5–72.7) | 1.866 (1.861–1.872) |
| the first 8 minutes | until first contact | 68067    | 1795375 | 48.0% (47.9–48.1) | 74.7% (74.6–74.8) | 1.768 (1.764–1.773) |
| until first contact | until first contact | 68067    | 1795375 | 48.1% (48.0–48.2) | 74.9% (74.8–75.0) | 1.773 (1.768–1.778) |

The middle row is `reason8 baseline --split test --train-dataset` with the
8-minute build. On validation the first and the last row are 46.3%, 72.4% and
1.875 against 48.0%, 74.8% and 1.781.

## With the game state (preliminary)

Preliminary, on the 503 games of the context sample re-simulated by 2026-11-27
(411 train, 47 validation, 45 test): the decision table
([`context-dataset.md`](reference/context-dataset.md)) joins the same rows
with the state just before each order, and gradient-boosted trees are scored
with the protocol above on its 45 test games, 18,943 steps. Method, the other
groups and the breakdowns: [`context.md`](research/context.md).

```sh
uv run reason8 context build
uv run reason8 context measure --split test
```

| model                                    | trained on           | top-1             | top-3             | log-loss            |
| ---------------------------------------- | -------------------- | ----------------- | ----------------- | ------------------- |
| 4-gram, faction, map and position        | 411 table games      | 44.1% (43.2–45.0) | 69.9% (69.0–70.9) | 2.187 (2.121–2.254) |
| 4-gram, faction, map and position, saved | 33,657 dataset games | 48.3% (47.3–49.3) | 75.0% (74.0–76.0) | 1.759 (1.715–1.802) |
| trees: order history                     | 411 table games      | 48.1% (47.2–49.1) | 75.6% (74.7–76.5) | 1.698 (1.654–1.748) |
| trees: order history and the state       | 411 table games      | 51.4% (50.3–52.4) | 79.4% (78.3–80.3) | 1.563 (1.514–1.615) |

The state (game time, the team's economy and units, the allies' economy and
units) adds 3.2 points of top-1 (2.6 to 3.8, paired) and 0.135 nats over the
same trees with the order history alone; the economy and the team's own units
carry most of it, the wind nothing.

## Findings

- **Counting sets a high bar.** The chosen n-gram predicts the next step right
  48.1% of the time and has it among its three guesses 74.9% of the time, on
  test. Repeating the previous step already gives 32.3% top-1: openings are
  runs of extractors and energy. Unit frequencies alone reach 19.8%.
- **Merging quick runs of clicks lowers the scores of the history models.** A
  run of clicks on one unit within 0.2 s used to be several steps, the later
  ones nearly free to predict. Merged into one step, as drags are
  ([ADR 0013](decisions/0013-evaluate-on-held-out-games.md)), they take 13% of
  the steps away, and the models that predict repeats lose the most: the
  repeat baseline 8 points of top-1, the n-grams 3 to 5.
- **More games help the longer history most.** With 8 times the training games
  of the first sample, the 4-gram with the map and position gained 0.4 points
  of top-1 and 0.09 nats on test, and its log-loss became the best of all
  models: on the sample its probabilities were too sure on the little data per
  context, and validation chose a trigram. The other models moved by less than
  a point either way, on test games that are not the same. (Measured before
  quick runs of clicks were merged.)
- **Steps before first contact are easier to predict.** Scored on the openings
  that end at first contact, the model trained on 8-minute openings gets 48.0%
  of the steps right instead of 46.4%, and 1.768 instead of 1.866 nats: the
  steps left out were predicted worse than the rest. Trained on the cut
  openings instead, it gains 0.1 points of top-1 and loses 0.005 nats, with
  two thirds of the training orders: no better. The change shows at steps 21
  to 30, which only openings with a late contact reach: 47.4% top-1 and 70.9%
  top-3 there, against 43.6% and 66.4% in the 8-minute openings.
- **Fewer steps are scored.** 1,795,375 instead of 2,000,040: an opening that
  ends before its 30th step is scored whole, and 56% of the openings reach 30
  steps, against 90% of the 8-minute ones.
- **Short histories carry most of it.** Going from one previous step to two
  gains 3.7 points of top-1, from two to three 2.1. With the map and position,
  the third step gains another 1.8 points.
- **The map and the position help.** Telling the trigram the map and the role
  gains 2.4 points of top-1 and 0.14 nats of log-loss over the faction
  trigram; the exact position instead of the role adds 0.6 points and 0.02
  nats. The chosen model gains 4.8 points over the faction trigram on Supreme
  Isthmus and 9.0 on Rosetta, and up to 11.8 at a single position (Rosetta
  `P10`). It gains least at the Isthmus shipyard positions (`P8`, `P16`, 2.4
  points), whose openings vary the most.
- **The gain is at the start.** The chosen model gains 15.2 points at steps 2
  to 5, where the first factory and the first energy are chosen, and 2 to 3
  points after step 10. The first step is right 97% of the time, 5.7 points
  more than without the position.
- **No era stands out.** Top-1 is 47.4 to 48.5% in every opening era, as ADR
  0015 expected.
- **Raw orders flatter.** On raw orders, where a drag counts each building and
  a run of clicks each click, the faction trigram scores 60.4% top-1, the
  number the earlier measurements in [`maps/`](research/maps/README.md)
  report. On steps it scores 43.3%.
- **Against StarCraft.** Justesen and Risi (2017) report a top-1 error of
  54.6% and a top-3 error of 22.9% predicting the next build in StarCraft from
  replays. Here the errors are 51.9% and 25.1%: about the same, on a different
  game and a simpler model.

## The saved model

`reason8 baseline` saves the n-gram with the lowest validation log-loss to
`data/models/ngram_v2.json`: its levels, vocabulary and counts, what it was
trained on (`TrainedOn`: the first and last build and every unit it can order)
and the dataset's manifest. `load_model()` reads it back and `check_model()`
runs `check_game_version()`
([ADR 0015](decisions/0015-train-across-balance-patches.md)): it warns when
the game is a month or an opening-changing patch ahead of the training data
and refuses when the model can order a unit the game does not have.

## Using it in the game

`reason8 bot export` turns the saved model into the in-game AI's openings,
`ai/Reason8/openings.json` ([`in-game.md`](reference/in-game.md)): one per
map, start position and faction (Armada and Cortex), 96 in all.

Which opening
: Taking the most likely next step again and again does not give an opening:
  after a few wind generators another one is always the most likely step, so
  the decoded opening never ends. Instead the export scores up to 2,000 human
  openings of each map, position and faction from the training split by how
  likely the model finds their first 15 steps, and the AI plays the most
  likely one: the model's most typical opening of the position. It is a real
  opening, so it ends at its player's first contact, and its drags and factory
  queues have real lengths.

Which position
: Each opening carries the median start point of its position. The AI plays
  the opening of its side and map whose start point is nearest to its
  commander.

Drags
: A step of five extractors is five structures for the commander, a factory
  order with shift five units.

Builders
: The commander builds the structures, at most 30, its first factory among
  them: a human shares a long opening with the first constructors, and the
  AI's constructors are BARb's. The first factory makes the opening's units;
  units of a second factory or of another kind are dropped.

Task types
: Each structure gets its BARb task type from the game's unit files
  (`reason8.game.unitdefs`); structures no script task builds, such as walls,
  are dropped.
