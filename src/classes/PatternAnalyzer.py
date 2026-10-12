"""Name: PatternAnalyzer
Parent: metadata pipeline
Description: Versioned, timing-aware chart counts and explicit footwork estimates.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction
from itertools import groupby, permutations
from math import isclose
from statistics import mean, median, pstdev

from simfile.notes import NoteData, NoteType
from simfile.timing import TimingData, BeatValues, timing_source
from simfile.timing.engine import TimingEngine


@dataclass(frozen=True)
class PatternRules:
    # Rhythm thresholds are beats; the additional seconds limit breaks at stops.
    max_gap_beats: float = 1.0
    max_gap_seconds: float = 1.0
    stream_gap_beats: float = 0.5
    stream_min_rows: int = 8
    density_window_seconds: float = 1.0

    def __post_init__(self):
        from math import isfinite

        for value in (self.max_gap_beats, self.max_gap_seconds,
                      self.stream_gap_beats, self.density_window_seconds):
            if not isfinite(value) or value <= 0:
                raise ValueError("Pattern timing thresholds must be finite and positive")
        if self.stream_min_rows < 2 or not isinstance(self.stream_min_rows, int):
            raise ValueError("stream_min_rows must be an integer >= 2")


PRESS_TYPES = {NoteType.TAP, NoteType.HOLD_HEAD, NoteType.ROLL_HEAD}
QUANTIZATIONS = (4, 8, 12, 16, 20, 24, 32, 48, 64, 96, 192)
PATTERNS = ("repeated_panel", "jack_run", "trill", "staircase", "candle",
            "jumpstream", "stream")
FOOT_PATTERNS = ("crossed_rows", "crossover_entries", "footswitches",
                 "up_footswitches", "down_footswitches", "sideswitches",
                 "jacks", "doublesteps")


def _rounded(value):
    return round(float(value), 6)


def _stats(values):
    if not values:
        return dict.fromkeys(("min", "max", "mean", "median", "stddev"))
    return {"min": _rounded(min(values)), "max": _rounded(max(values)),
            "mean": _rounded(mean(values)), "median": _rounded(median(values)),
            "stddev": _rounded(pstdev(values))}


def _normalize(sim, chart):
    """Use exact beats for grouping, unrounded seconds for density and rhythm."""
    timing = TimingData(sim, chart)
    engine = TimingEngine(timing)
    fakes = BeatValues.from_str(timing_source(sim, chart).get("FAKES"))
    fake_regions = [(v.beat, v.beat + Fraction(v.value)) for v in fakes]
    rows, holds, warnings = [], {}, []
    excluded_holds = set()
    excluded = Counter()
    for beat, notes in groupby(NoteData(chart), key=lambda n: n.beat):
        second = float(engine.time_at(beat))
        # A tail still closes a real hold when it lies inside a fake/warp region.
        notes = list(notes)
        for note in notes:
            if note.note_type == NoteType.TAIL:
                if note.column in excluded_holds:
                    excluded_holds.remove(note.column)
                    continue
                head = holds.pop(note.column, None)
                if head is None:
                    warnings.append(f"Orphan hold tail at beat {beat}, column {note.column}")
                else:
                    head["end_beat"], head["end_second"] = beat, second
        row = {"beat": beat, "second": second, "presses": [], "mines": [],
               "lifts": [], "active_holds": set(holds)}
        hittable = engine.hittable(beat) and not any(a <= beat < b for a, b in fake_regions)
        for note in notes:
            kind, col = note.note_type, note.column
            if kind == NoteType.TAIL:
                continue
            if not hittable or kind == NoteType.FAKE:
                excluded["fake_or_warped_notes"] += 1
                if kind in (NoteType.HOLD_HEAD, NoteType.ROLL_HEAD):
                    excluded_holds.add(col)
                continue
            if kind in PRESS_TYPES:
                head = {"column": col, "type": kind, "beat": beat, "second": second}
                row["presses"].append(head)
                if kind in (NoteType.HOLD_HEAD, NoteType.ROLL_HEAD):
                    if col in holds:
                        warnings.append(f"Overlapping hold heads at beat {beat}, column {col}")
                    holds[col] = head
            elif kind == NoteType.MINE:
                row["mines"].append(col)
            elif kind == NoteType.LIFT:
                row["lifts"].append(col)
            else:
                excluded["unsupported_notes"] += 1
        if row["presses"] or row["mines"] or row["lifts"]:
            rows.append(row)
    for col, head in holds.items():
        warnings.append(f"Unterminated hold at beat {head['beat']}, column {col}")
    return rows, dict(excluded), warnings


def _linked(a, b, rules, beat_limit=None):
    gap = float(b["beat"] - a["beat"])
    seconds = b["second"] - a["second"]
    return (0 < gap <= (beat_limit or rules.max_gap_beats) + 1e-9
            and 0 < seconds <= rules.max_gap_seconds + 1e-9)


def _event(name, rows):
    return {"pattern": name, "start_beat": _rounded(rows[0]["beat"]),
            "end_beat": _rounded(rows[-1]["beat"]),
            "start_second": _rounded(rows[0]["second"]),
            "end_second": _rounded(rows[-1]["second"]), "rows": len(rows)}


def _structural(rows, rules):
    events = []
    # Maximal runs, independently per pattern. Different families may overlap.
    def runs(name, eligible, links, minimum):
        run = []
        for row in rows:
            if not eligible(row):
                if len(run) >= minimum:
                    events.append(_event(name, run))
                run = []
            elif run and not links(run, row):
                if len(run) >= minimum:
                    events.append(_event(name, run))
                run = [row]
            else:
                run.append(row)
        if len(run) >= minimum:
            events.append(_event(name, run))

    def single(row):
        return (len(row["presses"]) == 1 and not row["active_holds"]
                and not row["mines"] and not row["lifts"]
                and row["presses"][0]["type"] == NoteType.TAP)

    def col(row):
        return row["presses"][0]["column"]

    def even(run, row):
        return len(run) < 2 or isclose(float(row["beat"] - run[-1]["beat"]),
                                      float(run[-1]["beat"] - run[-2]["beat"]),
                                      abs_tol=1e-8)

    runs("jack_run", single,
         lambda run, r: _linked(run[-1], r, rules) and col(run[-1]) == col(r), 3)
    # Sliding four-row windows merged into maximal ABAB runs (even rhythm).
    trill = []
    for row in rows:
        if not single(row) or (trill and not _linked(trill[-1], row, rules)):
            if len(trill) >= 4:
                events.append(_event("trill", trill))
            trill = [row] if single(row) else []
            continue
        if trill and (col(trill[-1]) == col(row) or not even(trill, row)
                      or (len(trill) >= 2 and col(trill[-2]) != col(row))):
            if len(trill) >= 4:
                events.append(_event("trill", trill))
            trill = [trill[-1]] if col(trill[-1]) != col(row) else []
        trill.append(row)
    if len(trill) >= 4:
        events.append(_event("trill", trill))

    for a, b in zip(rows, rows[1:]):
        if _linked(a, b, rules):
            shared = {p["column"] for p in a["presses"]} & {p["column"] for p in b["presses"]}
            for column in sorted(shared):
                events.append(dict(_event("repeated_panel", [a, b]), column=column))

    for a, b, c in zip(rows, rows[1:], rows[2:]):
        if not all(single(r) for r in (a, b, c)) or not (
                _linked(a, b, rules) and _linked(b, c, rules)):
            continue
        cols = [col(r) for r in (a, b, c)]
        # A candle is a geometric candidate, not a claim about the player's feet.
        if cols[0] == cols[2] and cols[0] // 4 == cols[1] // 4 and {
                cols[0] % 4, cols[1] % 4} == {1, 2}:
            events.append(_event("candle", [a, b, c]))
        # Staircase means column-order staircase, not the player's travel path.
        if cols[1] - cols[0] == cols[2] - cols[1] and abs(cols[1] - cols[0]) == 1:
            events.append(_event("staircase", [a, b, c]))

    runs("stream", lambda r: bool(r["presses"]) and not r["mines"] and not r["lifts"],
         lambda run, r: _linked(run[-1], r, rules, rules.stream_gap_beats), rules.stream_min_rows)
    runs("jumpstream", lambda r: 1 <= len(r["presses"]) <= 2 and not r["mines"] and not r["lifts"],
         lambda run, r: _linked(run[-1], r, rules, rules.stream_gap_beats)
         and len(run[-1]["presses"]) != len(r["presses"]), 4)
    return sorted(events, key=lambda e: (e["start_beat"], e["pattern"], e.get("column", -1)))


def _crossed(left, right):
    # Side-panel crossover, or reversed horizontal ordering of known feet.
    x = {-1: 0, 0: -1, 1: 0, 2: 0, 3: 1}
    return left == 3 or right == 0 or (left >= 0 and right >= 0 and x[left] > x[right])


def _footwork(rows, rules, profile):
    """Two-foot dynamic program; unsupported rows split the path explicitly.

    A foot can occupy one panel. Holds lock it until the tail. Moving the other
    foot onto its panel lifts the old foot (unknown resting position = -1).
    Costs encode preferences, not biomechanical truth or calibrated difficulty.
    """
    cross_cost, double_cost = (1, 6) if profile == "prefer_alternation" else (6, 2)
    paths, chosen, skipped = {}, [], []

    def flush():
        if paths:
            node = min(paths.values(), key=lambda n: n[0])
            segment = []
            while node[1] is not None:
                segment.append(node[2])
                node = node[1]
            chosen.extend(reversed(segment))

    previous = None
    for index, row in enumerate(rows):
        cols = tuple(p["column"] for p in row["presses"])
        locked = row["active_holds"]
        if previous is not None and not locked and not _linked(previous, row, rules):
            flush()
            paths = {}
        if (not cols or len(set(cols) | locked) > 2 or row["mines"] or row["lifts"]):
            flush()
            paths = {}
            skipped.append(index)
            previous = row
            continue
        if not paths:
            # Cannot infer a held foot after a skipped row without its history.
            if locked:
                skipped.append(index)
                previous = row
                continue
            paths = {(-1, -1, -1): (0, None, None)}
        next_paths = {}
        for (left, right, last), node in paths.items():
            old = (left, right)
            for feet in permutations((0, 1), len(cols)):
                new = list(old)
                for column, foot in zip(cols, feet):
                    new[foot] = column
                if any(old[f] in locked and new[f] != old[f] for f in (0, 1)):
                    continue
                if new[0] == new[1]:
                    idle = 1 - feet[0]
                    if len(cols) == 2 or old[idle] in locked:
                        continue
                    new[idle] = -1
                tags = []
                cost = node[0] + cross_cost * _crossed(*new)
                if _crossed(*new):
                    tags.append("crossed_rows")
                    if not _crossed(*old):
                        tags.append("crossover_entries")
                if len(cols) == 1 and last >= 0:
                    foot, column = feet[0], cols[0]
                    if foot == last:
                        if old[foot] == column:
                            tags.append("jacks")
                        else:
                            tags.append("doublesteps")
                            cost += double_cost
                    elif old[last] == column:
                        tags.append("footswitches")
                        tags.append({0: "sideswitches", 1: "down_footswitches",
                                     2: "up_footswitches", 3: "sideswitches"}[column])
                        cost += 4
                # Small deterministic travel preference resolves otherwise equal costs.
                cost += sum(0.1 for c, f in zip(cols, feet) if old[f] >= 0 and old[f] != c)
                key = (*new, feet[0] if len(cols) == 1 else -1)
                record = {"row_index": index, "feet": list(feet), "columns": list(cols),
                          "patterns": tags}
                if key not in next_paths or cost < next_paths[key][0]:
                    next_paths[key] = (cost, node, record)
        if not next_paths:
            flush()
            skipped.append(index)
        paths = next_paths
        previous = row
    flush()
    counts = Counter(tag for r in chosen for tag in r["patterns"])
    return {"status": "estimated", "profile": profile, "method": "two_foot_dp_v1",
            "counts": {name: counts[name] for name in FOOT_PATTERNS},
            "analysed_press_rows": len(chosen),
            "excluded_press_rows": sum(bool(rows[i]["presses"]) for i in skipped),
            "assignments": chosen,
            "unavailable": ["half_crossovers", "full_crossovers", "brackets", "body_facing", "spins"]}


def analyze_chart(sim, chart, rules=None, include_events=False):
    """Analyze one chart without merging equal difficulties or touching inputs."""
    rules = rules or PatternRules()
    if chart.stepstype not in ("dance-single", "dance-double"):
        return {"schema_version": 1, "status": "unsupported_stepstype", "stepstype": chart.stepstype}
    rows, excluded, warnings = _normalize(sim, chart)
    width = 4 if chart.stepstype == "dance-single" else 8
    if any(p["column"] >= width for r in rows for p in r["presses"]):
        raise ValueError(f"Invalid column for {chart.stepstype}")
    presses = [r for r in rows if r["presses"]]
    heads = [p for r in presses for p in r["presses"]]
    sustains = [p for p in heads if p["type"] in (NoteType.HOLD_HEAD, NoteType.ROLL_HEAD)]
    durations = [p["end_second"] - p["second"] for p in sustains if "end_second" in p]
    start = presses[0]["second"] if presses else None
    end = max([r["second"] for r in presses] + [p["end_second"] for p in sustains if "end_second" in p], default=None)
    duration = end - start if start is not None else 0
    if duration < 0 or any(b["second"] < a["second"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Nonmonotonic chart timing cannot be analysed")
    counts = {"press_rows": len(presses), "arrows": len(heads),
              "single_rows": sum(len(r["presses"]) == 1 for r in presses),
              "jump_rows": sum(len(r["presses"]) == 2 for r in presses),
              "multi_rows": sum(len(r["presses"]) >= 3 for r in presses),
              "holds": sum(p["type"] == NoteType.HOLD_HEAD for p in heads),
              "rolls": sum(p["type"] == NoteType.ROLL_HEAD for p in heads),
              "mines": sum(len(r["mines"]) for r in rows),
              "mine_rows": sum(bool(r["mines"]) for r in rows),
              "lifts": sum(len(r["lifts"]) for r in rows),
              "hold_assisted_multi_rows": sum(len(r["active_holds"] | {p["column"] for p in r["presses"]}) >= 3 for r in presses)}
    quantization = Counter()
    for row in presses:
        beat = Fraction(row["beat"])
        quant = next((str(q) for q in QUANTIZATIONS if (beat * q / 4).denominator == 1), "other")
        quantization[quant] += len(row["presses"])
    times = [r["second"] for r in presses]
    intervals = [b - a for a, b in zip(times, times[1:])]
    peak_rows = peak_arrows = right = arrow_sum = 0
    for left, row in enumerate(presses):
        while right < len(presses) and presses[right]["second"] - row["second"] < rules.density_window_seconds:
            arrow_sum += len(presses[right]["presses"])
            right += 1
        peak_rows, peak_arrows = max(peak_rows, right - left), max(peak_arrows, arrow_sum)
        arrow_sum -= len(row["presses"])
    events = _structural(rows, rules)
    pattern_counts = Counter(e["pattern"] for e in events)
    stream_seconds = sum(e["end_second"] - e["start_second"] for e in events if e["pattern"] == "stream")
    result = {"schema_version": 1, "status": "ok", "rules": asdict(rules),
              "counts": counts, "excluded": excluded, "warnings": warnings,
              "timing": {"start_second": _rounded(start) if start is not None else None,
                         "end_second": _rounded(end) if end is not None else None,
                         "duration_seconds": _rounded(duration),
                         "interval_seconds": _stats(intervals),
                         "hold_seconds": _stats(durations),
                         "total_hold_seconds": _rounded(sum(durations))},
              "density": {"press_rows_per_second": _rounded(len(presses) / duration) if duration > 0 else None,
                          "arrows_per_second": _rounded(len(heads) / duration) if duration > 0 else None,
                          "peak_press_rows_per_second": _rounded(peak_rows / rules.density_window_seconds),
                          "peak_arrows_per_second": _rounded(peak_arrows / rules.density_window_seconds),
                          "fastest_burst_seconds": {str(n): _rounded(min(times[i+n-1] - times[i] for i in range(len(times)-n+1)))
                                                    if len(times) >= n else None for n in (2, 3, 5, 7, 15)}},
              "lane_arrows": [sum(p["column"] == c for p in heads) for c in range(width)],
              "quantization_arrows": {str(q): quantization[str(q)] for q in (*QUANTIZATIONS, "other")},
              "patterns": {name: {"count": pattern_counts[name],
                                  "per_100_press_rows": _rounded(100 * pattern_counts[name] / len(presses)) if presses else None}
                           for name in PATTERNS},
              "stream_seconds": _rounded(stream_seconds),
              "stream_fraction": _rounded(stream_seconds / duration) if duration > 0 else None}
    if width == 4:
        result["footwork"] = {profile: _footwork(rows, rules, profile)
                              for profile in ("prefer_alternation", "prefer_uncrossed")}
        if not include_events:
            for value in result["footwork"].values():
                del value["assignments"]
    else:
        result["footwork"] = {"status": "unsupported_double_footwork"}
    if include_events:
        result["events"] = events
        result["row_locations"] = [{"beat": _rounded(r["beat"]), "second": _rounded(r["second"])} for r in rows]
    return result


def analyze_simfile(sim, rules=None, include_events=False):
    """Chart indices retain edit charts and duplicate difficulty names."""
    return [{"chart_index": index, "stepstype": chart.stepstype,
             "difficulty": chart.difficulty, "meter": chart.meter,
             "description": chart.description,
             "analysis": analyze_chart(sim, chart, rules, include_events)}
            for index, chart in enumerate(sim.charts)]
