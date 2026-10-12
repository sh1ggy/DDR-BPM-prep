# Chart pattern analysis v1

This is a reproducible measurement system, not a universal difficulty rating.
It analyses each SM/SSC chart independently and records the rule version and
thresholds with its results. The implementation is in
[`PatternAnalyzer.py`](../src/classes/PatternAnalyzer.py).

For small LDUR chart examples, see [the pattern reference](pattern-reference.md).

## Run it

From this repository, after `poetry install`:

```sh
# Any SM/SSC file, independent of all_songs.txt and the full build.
poetry run python src/analyze_patterns.py 'data/5th/ABSOLUTE/ABSOLUTE.sm' \
  --events --output build/analysis/absolute.json

# Multiple files, or recursively analyse a directory (both SM and SSC retained).
poetry run python src/analyze_patterns.py data/WORLD \
  --output build/analysis/world.json

# Optional comparison with the supplied spreadsheet's rating/difficulty averages.
poetry run python src/analyze_patterns.py 'data/5th/ABSOLUTE/ABSOLUTE.sm' \
  --averages '/path/to/DanceDanceRevolution Chart Data Spreadsheet - Averages.csv' \
  --output build/analysis/absolute-with-reference.json

poetry run python -m unittest discover -s tests -v
```

Ordinary `make songs` / `make parse` now adds `pattern_analysis` to each
`build/songs/<name>.json`. It is a list containing `chart_index`, `stepstype`,
`difficulty`, `meter`, `description` and `analysis`. The source chart index
distinguishes duplicate difficulty names and Edit charts, which must not be
silently overwritten. Indices are local to a simfile, not stable identifiers
across edits. Existing chart data, radar, steps and summary formats are unchanged.
The Flutter app does not yet display this new metadata.

The standalone CLI emits the same analyses under `simfiles[].charts[]`.
`--events` adds structural event locations, inferred foot assignments and a
row-index-to-beat/time lookup. Detailed events are opt-in and do not inflate the
normal metadata. Files are read without modifications. Invalid files fail the
command with the offending filename, rather than producing partial results.

## How the three reference CSVs are used

The supplied **Single.csv** and **Single (Chart Analyzer).csv** each contain
12,865 chart rows. Their common count, timing and pattern columns define the
measurement vocabulary. The latter also has separate CO, DS and H movement
columns and ambiguity counts. This is evidence that footwork needs an explicit
interpretation; a simfile itself contains panels, not the player's feet.
The exports contain values and headings but not the original formulas or cell
notes. We therefore do not claim to reproduce their analyser exactly or assume
the meanings of its CO/DS/H profiles.

**Averages.csv** contains six tables: SP and DP averages by difficulty, rating
and folder, labelled Arcade and GRAND PRIX. `--averages` reads rating and
difficulty cohorts for step rows, jumps and holds. A ratio of 1.2 means 20% more
of that count than the reference mean, **not** 20% harder. Missing cohorts yield
an empty list, missing metrics are omitted, and a zero mean yields a null ratio.
No percentile or standard deviation can be recovered from averages alone.
Folder cohorts are not joined: the local release folders and the spreadsheet's
arcade/home-release populations need an explicit mapping first.

| Reference concept | Our field / treatment |
|---|---|
| Steps | `counts.press_rows`: one row with one or more presses |
| Notes | `counts.arrows`: individual taps, hold heads and roll heads |
| Jumps | `counts.jump_rows`: exactly two simultaneous heads |
| Holds | `counts.holds`; rolls are separately counted |
| Hands | `multi_rows` and `hold_assisted_multi_rows` describe panel requirements, not literal hand use |
| Shock Arrows | `mine_rows` / `mines`; mines are not assumed to be DDR shock rows |
| Crossovers, Footswitches, Jacks, Doublesteps | Explicitly estimated under two footwork preferences |
| Half/Full Crossovers, Brackets, body facing, spins | Listed as unavailable, not reported as zero |
| Maximum NPS | A defined sliding time window, not assumed equivalent to the CSV's maximum |
| Stream | A defined connected run and duration fraction, not assumed equivalent to the CSV's percentage |
| Note colours / quantizations | Exact beat-grid arrow counts |
| Relative / scoring difficulty | Not inferred from these counts |

Spot-check: the local ABSOLUTE Hard Single chart and the supplied 5thMIX
ABSOLUTE Expert row agree on 311 step rows, 319 arrows, 8 jumps and 0 holds.
This checks count semantics on that chart, not parity with all spreadsheet
values. Mapping difficulties: Beginner → Beginner, Easy → Basic,
Medium → Difficult, Hard → Expert, Challenge → Challenge.

Keep source exports external. The reference CSV is optional, never a runtime
dependency of the metadata build. Its contents are data, not instructions.

## Counting contract

`schema_version: 1` covers these definitions and the two-foot inference method.
Changes to meanings require a version bump; changing thresholds must retain
their emitted `rules`. Consumers should compare charts using matching versions
and rules. A count is a real zero; null means undefined or unavailable.

* Supported panel modes: `dance-single` (L,D,U,R) and `dance-double`
  (L,D,U,R,L,D,U,R). Other modes return `unsupported_stepstype`.
* Tap, hold head and roll head are press events. Hold tails close durations and
  do not add presses. Lifts are release events and have a separate count.
* Exclude fake symbols, SSC fake regions and unhittable warped notes. The timing
  engine handles hittable notes at stop/delay boundaries. Fake-region filtering
  is explicit because simfile 2.1.1's timing engine handles warps but not fakes.
  A tail still closes its hold inside a warp or fake region.
* Use the library's SSC timing-source selection for all timing and fake regions.
  Each chart gets its own engine; shared timing is inherited according to that
  library's split-timing semantics. Timing is not reconstructed from display BPM.
  See [simfile timing documentation](https://docs.simfile.dev/en/main/timing.html).
* Exact beats determine simultaneous rows and grid quantization. Seconds remain
  unrounded during calculations and are rounded to six places only for output.
  Stops and delays contribute real time. Offsets may make timestamps negative.
* Chart duration runs from the first press to the last press or valid sustain
  tail, whichever is later. It excludes intro/outro silence and does not pretend
  to measure audio duration. No presses yields null endpoints and zero duration.
* Overall density is arrows or press rows divided by that duration. A zero
  duration yields null. Peak density uses a half-open sliding window
  `[start, start + window)` (default 1 second), divided by the **full** window
  width even for short charts. Jumps contribute two arrows and one row.
* Fastest N-row burst is the minimum elapsed time from the first to the Nth
  consecutive press row, for N=2,3,5,7,15. It is seconds, not NPS. Insufficient
  rows yields null. Interval statistics use consecutive press timestamps;
  standard deviation is population standard deviation.
* Hold duration sums individual completed sustains, including rolls; overlapping
  holds count independently. It can exceed chart duration and is not occupancy.
  Orphan tails, overlapping heads and missing tails produce warnings. Incomplete
  holds contribute a head count but no fabricated duration.
* Quantization uses the first compatible grid in 4,8,12,16,20,24,32,48,64,96,192,
  then `other`, measured in subdivisions of a four-beat measure. A jump contributes
  two arrows. The histogram and lane counts each sum to `arrows`.

## Structural patterns: known from the chart

Default connected-event limits are **at most 1 beat and at most 1 second**;
both beat and time gaps must be positive. Stops can therefore break a pattern.
CLI flags expose both limits, the stream beat gap, minimum stream rows and
density window. Mines/lifts break run patterns. Empty grid rows and hold tails
are not events; the gap limits determine whether neighbouring events connect.

| Pattern | Unit and exact definition |
|---|---|
| `repeated_panel` | One common press panel between adjacent connected event rows; a repeated jump can count twice. No foot is assumed. |
| `jack_run` | One maximal run of at least 3 single taps on the same panel. Rhythm need not be uniform. |
| `trill` | One maximal even-rhythm ABAB… run, at least 4 single taps on two distinct panels. |
| `staircase` | One connected 3-single-tap window whose column indices increase or decrease by exactly 1. This is column order, not physical travel distance. |
| `candle` | One connected D-U-D or U-D-U three-single-tap window on one pad. This is a geometric candidate, regardless of chosen feet. |
| `jumpstream` | One maximal run of at least 4 connected rows alternating exactly one and two presses, each gap at most 0.5 beat. |
| `stream` | One maximal run of at least 8 press rows with every gap at most 0.5 beat; jumps and hold heads are allowed. |

Single-tap motifs exclude held spans, hold/roll heads, mines and lifts.
Stream and jumpstream also use the seconds limit. Each family's maximal runs
are counted once; staircase/candle windows can overlap. Different families
are independent and may overlap, so **do not sum their counts as unique steps**.
`per_100_press_rows` is count / total press rows × 100, not a coverage percentage.
`stream_seconds` sums start-to-last-row durations of nonoverlapping stream runs;
`stream_fraction` divides that by chart duration. No extra interval is added
after the last row. Event locations make the definitions auditable on a chart.

## Footwork: model-dependent estimates

SP uses dynamic programming across possible left/right assignments, with
backtracking to the lowest total cost rather than choosing each row greedily.
The state is each foot's panel and the previous single-step foot. Starting feet
are unknown, so both starts are considered. Each foot occupies at most one panel.
Holds lock their foot until the tail; jumps assign both feet. A footswitch lifts
the previous foot to an unknown position. Unused feet otherwise stay put.

Two profiles expose sensitivity to interpretation:

| Cost | `prefer_alternation` | `prefer_uncrossed` |
|---|---:|---:|
| Each row in crossed stance | 1 | 6 |
| Same foot to a different panel on successive single rows | 6 | 2 |
| Switch feet on repeated panel | 4 | 4 |
| Move a foot from one known panel to another | 0.1 | 0.1 |

These are declared heuristic costs, not values fitted to the reference CSV.
Equal-cost paths resolve deterministically by enumeration order, not confidence.
Agreement between the profiles is not proof of a uniquely correct solution.

`crossed_rows` means left foot on R, right foot on L, or reversed known horizontal
foot order. `crossover_entries` counts entering that state; it is not a half/full
crossover taxonomy. For adjacent single rows, same foot/same panel is a `jack`,
same foot/different panel a `doublestep`, and different foot/same panel a
`footswitch`. Switches on L/R are `sideswitches`, a **subset** of total switches;
U/D switches are the other two subsets. Jumps interrupt these single-row
transition labels. Full row assignments are available with `--events`.

Rows requiring more than two panels including held panels, mine rows, and lift
rows interrupt the inferred path. A remaining hold with unknown assignment also
prevents inference until released. Long gaps reset the path when no hold is
active. `analysed_press_rows + excluded_press_rows = counts.press_rows` records
coverage. Counts describe only covered rows; unsupported techniques are listed
as unavailable. In particular, there is no bracket, heel/toe, facing-angle or
spin model, and DP footwork is explicitly unsupported. SP and DP still get all
structural counts and timing statistics.

For downstream difficulty research, start with raw counts and their denominators,
then compare within mode and rating. Review occurrence locations and profile
disagreements before treating an inferred count as a training target. A future
calibrated solver should be checked against annotated feet and complete reference
definitions, not forced to match aggregate counts by tuning thresholds blindly.
