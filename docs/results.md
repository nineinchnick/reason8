# Results: predicting the next build

The numbers later models are compared against. Every model predicts the unit
of the next step of an opening, the orders of one drag merged into one step,
from the steps before it and what is known before the game: the player's
faction, the map and the start position. An opening ends at the player's first
contact with the enemy
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
| unit frequency                     | 9.7% (9.6–9.8)    | 27.1% (26.9–27.2) | 3.936 (3.927–3.945) |
| unit frequency per faction         | 17.4% (17.3–17.5) | 38.4% (38.2–38.6) | 3.205 (3.199–3.211) |
| repeat the previous step           | 40.3% (40.2–40.5) | 57.9% (57.7–58.0) | 2.651 (2.644–2.657) |
| bigram, faction                    | 44.1% (43.9–44.2) | 69.9% (69.8–70.0) | 1.987 (1.983–1.992) |
| trigram, faction                   | 46.7% (46.6–46.8) | 73.8% (73.7–73.9) | 1.835 (1.831–1.840) |
| 4-gram, faction                    | 48.6% (48.5–48.7) | 75.6% (75.5–75.7) | 1.765 (1.760–1.769) |
| trigram, faction and map           | 47.9% (47.8–48.0) | 74.7% (74.6–74.8) | 1.791 (1.786–1.796) |
| trigram, faction, map and role     | 48.7% (48.6–48.8) | 76.2% (76.1–76.3) | 1.706 (1.702–1.711) |
| trigram, faction, map and position | 49.2% (49.1–49.3) | 76.7% (76.6–76.8) | 1.688 (1.684–1.692) |
| 4-gram, faction, map and position  | 51.1% (51.0–51.2) | 78.0% (77.9–78.1) | 1.668 (1.663–1.673) |

The lowest log-loss is `4-gram, faction, map and position` (1.668), which is
the model the detailed tables are about and the one that is saved.

## Test

Trained on 33657 games (536288 openings), scored on the test split: 4270
games, 68067 openings, the first 30 steps of each. Intervals are 95%, from
resampling games.

### All models

| model                              | top-1             | top-3             | log-loss            |
| ---------------------------------- | ----------------- | ----------------- | ------------------- |
| uniform                            | 0.0% (0.0–0.0)    | 0.0% (0.0–0.0)    | 6.219 (6.219–6.219) |
| unit frequency                     | 9.6% (9.5–9.7)    | 27.1% (27.0–27.3) | 3.933 (3.923–3.942) |
| unit frequency per faction         | 17.5% (17.4–17.6) | 38.4% (38.3–38.6) | 3.200 (3.194–3.206) |
| repeat the previous step           | 40.5% (40.3–40.6) | 57.9% (57.8–58.0) | 2.644 (2.638–2.650) |
| bigram, faction                    | 44.2% (44.0–44.3) | 70.0% (69.9–70.1) | 1.985 (1.980–1.989) |
| trigram, faction                   | 46.8% (46.7–46.9) | 73.9% (73.8–74.0) | 1.831 (1.826–1.835) |
| 4-gram, faction                    | 48.7% (48.6–48.8) | 75.7% (75.6–75.8) | 1.759 (1.755–1.763) |
| trigram, faction and map           | 48.0% (47.9–48.1) | 74.8% (74.7–74.9) | 1.785 (1.780–1.790) |
| trigram, faction, map and role     | 48.8% (48.7–48.9) | 76.3% (76.2–76.4) | 1.701 (1.697–1.705) |
| trigram, faction, map and position | 49.3% (49.2–49.4) | 76.8% (76.7–76.9) | 1.683 (1.679–1.687) |
| 4-gram, faction, map and position  | 51.2% (51.1–51.3) | 78.1% (78.0–78.2) | 1.661 (1.657–1.666) |

1886617 steps scored per model. Chosen on validation log-loss:
`4-gram, faction, map and position`.

`trigram, faction` on raw orders (drags not merged), for comparison with the
measurements in docs/research/game-versions.md and docs/research/maps/: 60.4%
(60.3–60.5), 81.4% (81.4–81.5), 1.458 (1.455–1.462) over 1983212 orders.

The tables below are for `4-gram, faction, map and position`. The last column
is its top-1 minus that of `trigram, faction` on the same steps, in points,
with a paired interval.

### By step of the opening

| step  | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference     |
| ----- | ----- | ------ | ----------------- | ----------------- | ------------------- | ---------------------- |
| 1     | 4270  | 68067  | 96.7% (96.5–96.8) | 99.5% (99.4–99.5) | 0.152 (0.146–0.159) | +5.7 (+5.6 to +5.9)    |
| 2–5   | 4270  | 272222 | 50.2% (50.0–50.4) | 83.9% (83.8–84.1) | 1.411 (1.405–1.416) | +14.7 (+14.4 to +15.0) |
| 6–10  | 4270  | 339808 | 47.5% (47.4–47.7) | 78.9% (78.7–79.1) | 1.642 (1.636–1.649) | +4.1 (+3.9 to +4.2)    |
| 11–20 | 4270  | 658094 | 49.0% (48.9–49.2) | 76.4% (76.3–76.5) | 1.760 (1.753–1.767) | +2.3 (+2.2 to +2.4)    |
| 21–30 | 4270  | 548426 | 51.0% (50.8–51.2) | 74.2% (74.1–74.4) | 1.867 (1.858–1.875) | +1.9 (+1.8 to +1.9)    |

### By map

| map                      | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------------------------ | ----- | ------ | ----------------- | ----------------- | ------------------- | ------------------- |
| All That Glitters v2.2.3 | 1961  | 904063 | 52.5% (52.4–52.6) | 79.5% (79.4–79.6) | 1.591 (1.586–1.597) | +4.1 (+4.0 to +4.2) |
| Rosetta 1.4.4            | 128   | 53308  | 52.5% (52.0–53.0) | 80.1% (79.7–80.6) | 1.626 (1.600–1.652) | +7.8 (+7.4 to +8.2) |
| Supreme Isthmus v2.1     | 2181  | 929246 | 49.9% (49.8–50.0) | 76.7% (76.6–76.8) | 1.732 (1.726–1.738) | +4.5 (+4.4 to +4.6) |

### By faction

| faction | games | steps   | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------- | ----- | ------- | ----------------- | ----------------- | ------------------- | ------------------- |
| Armada  | 4270  | 1009699 | 51.5% (51.4–51.6) | 78.9% (78.8–79.0) | 1.630 (1.624–1.635) | +4.6 (+4.5 to +4.7) |
| Cortex  | 4270  | 832009  | 51.0% (50.8–51.1) | 77.4% (77.3–77.6) | 1.682 (1.675–1.689) | +4.3 (+4.2 to +4.4) |
| Legion  | 435   | 44909   | 48.8% (48.2–49.6) | 74.1% (73.4–74.7) | 1.997 (1.957–2.042) | +1.9 (+1.5 to +2.3) |

### By era

| era                                 | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ----------------------------------- | ----- | ------ | ----------------- | ----------------- | ------------------- | ------------------- |
| Air constructors and mobile jammers | 1306  | 579220 | 51.4% (51.2–51.5) | 78.4% (78.2–78.6) | 1.648 (1.641–1.656) | +4.5 (+4.4 to +4.7) |
| August balance patch                | 568   | 253649 | 51.6% (51.3–51.9) | 78.5% (78.3–78.8) | 1.643 (1.629–1.656) | +4.6 (+4.4 to +4.8) |
| July balance patch                  | 771   | 340121 | 51.3% (51.0–51.5) | 78.2% (78.0–78.5) | 1.657 (1.647–1.667) | +4.6 (+4.4 to +4.7) |
| May balance patch                   | 1426  | 626628 | 51.0% (50.8–51.2) | 77.7% (77.6–77.9) | 1.679 (1.671–1.689) | +4.2 (+4.0 to +4.3) |
| Season 3                            | 199   | 86999  | 50.7% (50.3–51.2) | 77.6% (77.1–78.0) | 1.693 (1.671–1.715) | +4.1 (+3.7 to +4.4) |

### By map and position

#### All That Glitters v2.2.3

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 1957     | 55470 | 50.4% (49.8–50.9) | 76.6% (76.2–77.0) | 1.727 (1.708–1.746) | +3.2 (+2.8 to +3.5) |
| P2       | 1944     | 54242 | 48.3% (47.7–48.8) | 74.1% (73.6–74.6) | 1.821 (1.798–1.843) | +4.5 (+4.2 to +4.9) |
| P3       | 1944     | 58165 | 49.4% (48.9–49.9) | 79.1% (78.7–79.5) | 1.617 (1.600–1.635) | +3.6 (+3.2 to +3.9) |
| P4       | 1929     | 56296 | 52.1% (51.5–52.6) | 78.8% (78.4–79.3) | 1.638 (1.617–1.658) | +3.7 (+3.3 to +4.0) |
| P5       | 1976     | 54312 | 51.5% (51.0–52.0) | 78.4% (78.0–78.9) | 1.637 (1.617–1.657) | +4.3 (+4.0 to +4.7) |
| P6       | 1961     | 57652 | 55.4% (54.9–55.9) | 82.1% (81.6–82.4) | 1.464 (1.448–1.480) | +4.2 (+3.8 to +4.5) |
| P7       | 1994     | 59001 | 55.7% (55.2–56.2) | 83.2% (82.9–83.6) | 1.430 (1.415–1.446) | +5.2 (+4.8 to +5.5) |
| P8       | 1967     | 57336 | 55.3% (54.8–55.8) | 82.3% (82.0–82.7) | 1.448 (1.432–1.465) | +4.5 (+4.1 to +4.9) |
| P9       | 1936     | 54757 | 50.1% (49.5–50.7) | 76.5% (76.0–76.9) | 1.742 (1.722–1.762) | +2.9 (+2.6 to +3.2) |
| P10      | 1958     | 54282 | 49.1% (48.6–49.7) | 74.1% (73.6–74.6) | 1.814 (1.791–1.835) | +4.8 (+4.4 to +5.2) |
| P11      | 1942     | 58143 | 50.7% (50.2–51.1) | 79.9% (79.5–80.4) | 1.586 (1.569–1.604) | +3.7 (+3.4 to +4.0) |
| P12      | 1930     | 56319 | 52.2% (51.6–52.7) | 78.7% (78.2–79.1) | 1.632 (1.612–1.652) | +3.3 (+3.0 to +3.7) |
| P13      | 1980     | 54324 | 51.8% (51.3–52.4) | 78.8% (78.4–79.3) | 1.629 (1.610–1.647) | +4.4 (+4.0 to +4.8) |
| P14      | 1998     | 58624 | 55.4% (54.8–55.9) | 81.9% (81.5–82.3) | 1.471 (1.454–1.491) | +4.0 (+3.6 to +4.3) |
| P15      | 1976     | 58532 | 55.9% (55.4–56.4) | 83.5% (83.1–83.9) | 1.416 (1.400–1.433) | +4.6 (+4.3 to +4.9) |
| P16      | 1943     | 56608 | 56.0% (55.5–56.5) | 82.7% (82.3–83.0) | 1.434 (1.417–1.453) | +5.2 (+4.8 to +5.6) |

#### Rosetta 1.4.4

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference   |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | -------------------- |
| P1       | 131      | 3481  | 51.9% (50.0–53.9) | 80.1% (78.3–82.0) | 1.633 (1.549–1.718) | +6.6 (+5.2 to +8.0)  |
| P2       | 122      | 3651  | 52.6% (50.3–54.8) | 78.9% (76.5–81.0) | 1.773 (1.555–2.081) | +7.6 (+6.4 to +8.9)  |
| P3       | 125      | 3439  | 55.2% (52.9–57.4) | 81.9% (80.1–83.8) | 1.499 (1.425–1.575) | +7.6 (+6.0 to +9.2)  |
| P4       | 106      | 2388  | 50.0% (47.8–52.3) | 76.9% (74.8–79.1) | 1.772 (1.681–1.864) | +8.8 (+7.2 to +10.5) |
| P5       | 118      | 2914  | 48.2% (45.9–50.5) | 72.3% (70.4–74.3) | 1.999 (1.892–2.108) | +7.4 (+5.9 to +8.9)  |
| P6       | 126      | 3527  | 52.2% (50.3–54.2) | 81.8% (80.2–83.5) | 1.555 (1.484–1.622) | +7.5 (+6.0 to +8.9)  |
| P7       | 119      | 3569  | 51.5% (49.8–53.3) | 81.6% (79.8–83.4) | 1.551 (1.480–1.620) | +8.2 (+7.2 to +9.2)  |
| P8       | 126      | 3664  | 55.1% (53.3–57.1) | 83.9% (82.2–85.4) | 1.465 (1.392–1.537) | +7.2 (+5.9 to +8.4)  |
| P9       | 128      | 3273  | 51.1% (49.3–53.1) | 78.5% (76.8–80.2) | 1.678 (1.603–1.760) | +7.1 (+5.3 to +8.9)  |
| P10      | 116      | 3480  | 52.6% (51.1–54.2) | 80.6% (78.9–82.2) | 1.576 (1.507–1.643) | +8.6 (+7.2 to +10.0) |
| P11      | 129      | 3554  | 52.6% (50.4–54.7) | 81.8% (80.3–83.4) | 1.576 (1.501–1.653) | +8.0 (+6.4 to +9.7)  |
| P12      | 107      | 2479  | 48.6% (46.3–50.8) | 77.2% (75.3–79.0) | 1.741 (1.658–1.827) | +8.1 (+6.4 to +9.8)  |
| P13      | 122      | 3152  | 49.2% (47.3–51.4) | 72.4% (70.7–74.3) | 2.008 (1.909–2.106) | +7.7 (+6.1 to +9.4)  |
| P14      | 125      | 3538  | 54.6% (52.9–56.4) | 83.0% (81.6–84.4) | 1.500 (1.444–1.558) | +9.2 (+8.0 to +10.4) |
| P15      | 120      | 3598  | 54.7% (53.1–56.5) | 84.0% (82.4–85.7) | 1.440 (1.370–1.510) | +7.9 (+6.8 to +9.0)  |
| P16      | 124      | 3601  | 56.7% (54.6–58.7) | 82.8% (81.2–84.4) | 1.439 (1.371–1.514) | +8.4 (+7.1 to +9.5)  |

#### Supreme Isthmus v2.1

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 2138     | 61144 | 48.9% (48.5–49.4) | 74.2% (73.8–74.6) | 1.826 (1.803–1.846) | +3.8 (+3.4 to +4.1) |
| P2       | 2171     | 64829 | 52.6% (52.2–53.1) | 81.9% (81.5–82.3) | 1.471 (1.453–1.488) | +5.9 (+5.5 to +6.2) |
| P3       | 2163     | 58633 | 47.7% (47.3–48.2) | 72.6% (72.2–73.1) | 1.811 (1.791–1.830) | +3.3 (+3.0 to +3.6) |
| P4       | 2179     | 58054 | 50.8% (50.2–51.3) | 75.1% (74.6–75.6) | 1.908 (1.881–1.937) | +5.4 (+5.1 to +5.6) |
| P5       | 2212     | 49727 | 50.2% (49.6–50.8) | 80.1% (79.6–80.6) | 1.562 (1.545–1.581) | +5.6 (+5.2 to +6.1) |
| P6       | 2214     | 48129 | 51.6% (51.1–52.2) | 80.2% (79.7–80.6) | 1.545 (1.528–1.563) | +3.4 (+3.0 to +3.8) |
| P7       | 2162     | 64519 | 48.8% (48.3–49.2) | 77.1% (76.8–77.5) | 1.726 (1.707–1.746) | +6.0 (+5.7 to +6.4) |
| P8       | 2157     | 59712 | 48.2% (47.8–48.7) | 72.8% (72.4–73.3) | 1.966 (1.940–1.991) | +2.2 (+1.9 to +2.5) |
| P9       | 2135     | 61341 | 49.1% (48.6–49.5) | 74.5% (74.1–74.9) | 1.820 (1.799–1.842) | +3.8 (+3.4 to +4.1) |
| P10      | 2192     | 65493 | 52.4% (52.0–52.8) | 81.8% (81.5–82.2) | 1.474 (1.458–1.490) | +5.6 (+5.3 to +6.0) |
| P11      | 2175     | 58913 | 47.8% (47.3–48.3) | 72.9% (72.5–73.3) | 1.811 (1.794–1.831) | +3.1 (+2.8 to +3.3) |
| P12      | 2157     | 56842 | 50.7% (50.1–51.2) | 75.1% (74.6–75.6) | 1.925 (1.895–1.954) | +5.2 (+4.9 to +5.5) |
| P13      | 2219     | 49764 | 50.6% (50.1–51.2) | 80.3% (79.8–80.8) | 1.557 (1.539–1.574) | +6.0 (+5.5 to +6.5) |
| P14      | 2187     | 47629 | 52.1% (51.6–52.7) | 79.9% (79.4–80.3) | 1.550 (1.530–1.571) | +4.1 (+3.7 to +4.6) |
| P15      | 2158     | 64289 | 48.6% (48.2–49.1) | 77.1% (76.6–77.5) | 1.733 (1.711–1.756) | +5.8 (+5.5 to +6.2) |
| P16      | 2169     | 60228 | 48.8% (48.3–49.3) | 72.9% (72.5–73.4) | 1.955 (1.932–1.980) | +2.2 (+1.9 to +2.5) |

## Until first contact, against the first 8 minutes

The same replays built both ways (`--cutoff window` builds the 8-minute
openings), the same games in every split, `4-gram, faction, map and position`,
which validation chooses in both, on test:

| trained on          | scored on           | openings | steps   | top-1             | top-3             | log-loss            |
| ------------------- | ------------------- | -------- | ------- | ----------------- | ----------------- | ------------------- |
| the first 8 minutes | the first 8 minutes | 67902    | 2016384 | 50.2% (50.1–50.3) | 76.7% (76.5–76.8) | 1.722 (1.717–1.727) |
| the first 8 minutes | until first contact | 68067    | 1886617 | 51.1% (51.0–51.2) | 77.9% (77.8–78.0) | 1.662 (1.657–1.666) |
| until first contact | until first contact | 68067    | 1886617 | 51.2% (51.1–51.3) | 78.1% (78.0–78.2) | 1.661 (1.657–1.666) |

The middle row is `reason8 baseline --split test --train-dataset` with the
8-minute build. On validation the first and the last row are 50.1%, 76.5% and
1.730 against 51.1%, 78.0% and 1.668.

## Findings

- **Counting sets a high bar.** The chosen n-gram predicts the next step right
  51.2% of the time and has it among its three guesses 78.1% of the time, on
  test. Repeating the previous step already gives 40.5% top-1: openings are
  runs of extractors and energy. Unit frequencies alone reach 17.5%.
- **More games help the longer history most.** With 8 times the training games
  of the first sample, the 4-gram with the map and position gains 0.4 points
  of top-1 and 0.09 nats on test, and its log-loss is now the best of all
  models: on the sample its probabilities were too sure on the little data per
  context, and validation chose a trigram. The other models move by less than
  a point either way, on test games that are not the same.
- **Steps before first contact are easier to predict, a little.** Scored on
  the openings that end at first contact, the model trained on 8-minute
  openings gets 51.1% of the steps right instead of 50.2%, and 1.662 instead
  of 1.722 nats: the steps left out were predicted worse than the rest.
  Trained on the cut openings instead, it gains nothing more (0.1 points and
  0.001 nats) with two thirds of the training orders. The change shows at
  steps 21 to 30, which only openings with a late contact reach: 51.0% top-1
  and 74.2% top-3 there, against 48.9% and 71.5% in the 8-minute openings.
- **Fewer steps are scored.** 1,886,617 instead of 2,016,384: an opening that
  ends before its 30th step is scored whole, and 69% of the openings reach 30
  steps, against 95% of the 8-minute ones.
- **Short histories carry most of it.** Going from one previous step to two
  gains 2.6 points of top-1, from two to three 1.9. With the map and position,
  the third step gains another 1.9 points.
- **The map and the position help.** Telling the trigram the map and the role
  gains 2.0 points of top-1 and 0.13 nats of log-loss over the faction
  trigram; the exact position instead of the role adds 0.5 points and 0.02
  nats. The chosen model gains 4.5 points over the faction trigram on Supreme
  Isthmus and 7.8 on Rosetta, and up to 9.2 at a single position (Rosetta
  `P14`). It gains least at the Isthmus shipyard positions (`P8`, `P16`, 2.2
  points), whose openings vary the most.
- **The gain is at the start.** The chosen model gains 14.7 points at steps 2
  to 5, where the first factory and the first energy are chosen, and about 2
  points after step 10. The first step is right 97% of the time, 5.7 points
  more than without the position.
- **No era stands out.** Top-1 is 50.7 to 51.6% in every opening era, as ADR
  0015 expected.
- **Raw orders flatter.** On raw orders, where a drag counts each building,
  the faction trigram scores 60.4% top-1, the number the earlier measurements
  in [`maps/`](research/maps/README.md) report. On steps it scores 46.8%.
- **Against StarCraft.** Justesen and Risi (2017) report a top-1 error of
  54.6% and a top-3 error of 22.9% predicting the next build in StarCraft from
  replays. Here the errors are 48.8% and 21.9%: a little better, on a
  different game and a simpler model.

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
