# Pattern reference

Read each chart **bottom to top**, as notes approach the receptors. Columns stay
aligned in **L D U R** order. `x` is a tap, `.` is empty, and two `x` on one
line form a jump. Every example uses half-beat spacing at 120 BPM and the
[default analysis rules](pattern-analysis.md).

These are the seven patterns the prep engine detects directly from chart rows.
Counts below are **occurrences**, not steps; patterns can overlap.

### Repeated panel — 1

The same panel appears in two connected rows.

```text
beat  L D U R
0.5   x . . .
0.0   x . . .
```

### Jack run — 1

At least three connected single taps on one panel. The whole run counts once.

```text
beat  L D U R
1.0   x . . .
0.5   x . . .
0.0   x . . .
```

### Trill — 1

Four or more evenly spaced single taps alternating between two panels.

```text
beat  L D U R
1.5   . . . x
1.0   x . . .
0.5   . . . x
0.0   x . . .
```

### Staircase — 2

Any three consecutive single taps moving one **column index** at a time.
`L-D-U-R` has two overlapping three-row windows. This is a grid definition;
column order is not physical foot travel distance.

```text
beat  L D U R
1.5   . . . x
1.0   . . x .
0.5   . x . .
0.0   x . . .
```

### Candle candidate — 1

`D-U-D` or `U-D-U` on one pad. The chart supplies the geometry, but does not
specify which foot plays each row.

```text
beat  L D U R
1.0   . x . .
0.5   . . x .
0.0   . x . .
```

### Jumpstream — 1

At least four connected rows alternating between one and two presses.

```text
beat  L D U R
1.5   x . . x
1.0   . . x .
0.5   . x x .
0.0   x . . .
```

### Stream — 1

At least eight connected press rows with each gap at most half a beat. Jumps
and hold heads may appear in the run.

```text
beat  L D U R
3.5   . . . x
3.0   . x . .
2.5   . . x .
2.0   x . . .
1.5   . . . x
1.0   . . x .
0.5   . x . .
0.0   x . . .
```

The footwork fields—crossover, footswitch, sideswitch, jack and doublestep—come
from the engine's **inferred feet**, not the arrow symbols alone. The two
profiles can assign the same chart differently. Use `--events` in
[`analyze_patterns.py`](../src/analyze_patterns.py) to inspect the exact beat,
time and chosen foot for any chart. [The counting contract](pattern-analysis.md)
defines the gap limits, stop handling, footwork rules and unavailable techniques.
