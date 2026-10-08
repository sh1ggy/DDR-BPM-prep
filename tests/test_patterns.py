"""Name: Pattern analysis tests
Parent: metadata pipeline
Description: Hand-counted charts and format/timing regressions for analysis v1.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import simfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from classes.PatternAnalyzer import PatternRules, analyze_chart, analyze_simfile
from classes.PatternReference import read_averages, compare_averages


def sm(notes, mode="dance-single", timing=""):
    return simfile.loads(f"#TITLE:Test;\n#BPMS:0=120;\n#OFFSET:0;\n{timing}\n"
                         f"#NOTES:{mode}:test:Hard:10:0,0,0,0,0:\n{notes};")


def ssc(notes, timing="", chart_timing="", extra=""):
    return simfile.loads(f"#VERSION:0.83;\n#TITLE:Test;\n#BPMS:0=120;\n#OFFSET:0;\n{timing}\n"
                         f"#NOTEDATA:;\n#STEPSTYPE:dance-single;\n#DIFFICULTY:Hard;\n"
                         f"#METER:10;\n{chart_timing}\n#NOTES:\n{notes};\n{extra}")


def sequence(columns, spacing=0.5):
    per_measure = round(4 / spacing)
    rows = ["".join("1" if c == column else "0" for c in range(4)) for column in columns]
    rows.extend(["0000"] * ((-len(rows)) % per_measure))
    return ",\n".join("\n".join(rows[i:i+per_measure]) for i in range(0, len(rows), per_measure))


def result(sim, **kwargs):
    return analyze_chart(sim, sim.charts[0], **kwargs)


class PatternTests(unittest.TestCase):
    def test_counts_and_sustain_tail(self):
        data = result(sm("1000\n1100\n1110\n2000,\n0100\n3000\n000M\n000L"))
        self.assertEqual(data["counts"]["press_rows"], 5)
        self.assertEqual(data["counts"]["arrows"], 8)
        self.assertEqual(data["counts"]["jump_rows"], 1)
        self.assertEqual(data["counts"]["multi_rows"], 1)
        self.assertEqual(data["counts"]["holds"], 1)
        self.assertEqual(data["counts"]["mines"], 1)
        self.assertEqual(data["counts"]["lifts"], 1)
        self.assertEqual(data["timing"]["end_second"], 2.5)
        self.assertEqual(data["timing"]["total_hold_seconds"], 1)
        self.assertEqual(sum(data["quantization_arrows"].values()), 8)

    def test_maximal_runs_and_overlap(self):
        data = result(sm(sequence([0, 3] * 5)), include_events=True)
        self.assertEqual(data["patterns"]["trill"]["count"], 1)
        self.assertEqual(data["patterns"]["stream"]["count"], 1)
        self.assertEqual(data["events"][0]["start_beat"], 0)
        self.assertEqual(data["stream_fraction"], 1)
        jack = result(sm(sequence([0] * 5)))
        self.assertEqual(jack["patterns"]["jack_run"]["count"], 1)
        self.assertEqual(jack["patterns"]["repeated_panel"]["count"], 4)

    def test_staircase_and_candle(self):
        data = result(sm(sequence([0, 1, 2, 3, 1, 2, 1])))
        self.assertEqual(data["patterns"]["staircase"]["count"], 2)
        self.assertEqual(data["patterns"]["candle"]["count"], 1)

    def test_jumpstream(self):
        data = result(sm("1000\n0110\n0001\n1100\n0000\n0000\n0000\n0000"))
        self.assertEqual(data["patterns"]["jumpstream"]["count"], 1)

    def test_gap_and_stop_split_runs(self):
        data = result(sm(sequence([0] * 8), timing="#STOPS:1.5=2;"))
        self.assertEqual(data["patterns"]["jack_run"]["count"], 2)
        self.assertEqual(data["patterns"]["stream"]["count"], 0)
        self.assertEqual(data["timing"]["interval_seconds"]["max"], 2.25)

    def test_window_is_half_open_and_arrow_weighted(self):
        data = result(sm("1100\n0010\n0001\n1000"))
        self.assertEqual(data["density"]["peak_press_rows_per_second"], 2)
        self.assertEqual(data["density"]["peak_arrows_per_second"], 3)
        self.assertEqual(data["density"]["fastest_burst_seconds"]["3"], 1)
        self.assertIsNone(data["density"]["fastest_burst_seconds"]["7"])

    def test_split_timing_and_equivalent_formats(self):
        notes = sequence([0, 1, 2, 3] * 2)
        base = result(sm(notes))
        self.assertEqual(base, result(ssc(notes)))
        faster = result(ssc(notes, chart_timing="#BPMS:0=240;\n#OFFSET:2;"))
        self.assertEqual(faster["timing"]["start_second"], -2)
        self.assertEqual(faster["timing"]["duration_seconds"], base["timing"]["duration_seconds"] / 2)
        self.assertEqual(faster["counts"], base["counts"])

    def test_fake_warp_and_lift_semantics(self):
        data = result(ssc(sequence([0] * 8), timing="#WARPS:1=1;\n#FAKES:2=1;"))
        self.assertEqual(data["counts"]["arrows"], 4)
        self.assertEqual(data["excluded"]["fake_or_warped_notes"], 4)
        data = result(ssc("F000\n0L00\n00M0\n0001"))
        self.assertEqual(data["counts"]["arrows"], 1)
        self.assertEqual(data["counts"]["lifts"], 1)

    def test_chart_fake_regions_override_song(self):
        data = result(ssc(sequence([0] * 8), timing="#FAKES:0=4;",
                          chart_timing="#BPMS:0=120;\n#FAKES:0=1;"))
        self.assertEqual(data["counts"]["arrows"], 6)

    def test_warped_tail_closes_hold(self):
        data = result(ssc("2000\n0000\n3000\n0001", timing="#WARPS:1=2;"))
        self.assertEqual(data["counts"]["holds"], 1)
        self.assertFalse(data["warnings"])

    def test_fake_hold_is_not_a_broken_real_hold(self):
        data = result(ssc("2000\n0000\n3000\n0001", timing="#FAKES:0=1;"))
        self.assertEqual(data["counts"]["holds"], 0)
        self.assertFalse(data["warnings"])

    def test_bpm_change_and_delay(self):
        data = result(ssc("1000\n0100\n0010\n0001",
                          chart_timing="#BPMS:0=120,2=240;#DELAYS:1=1;"), include_events=True)
        self.assertEqual([r["second"] for r in data["row_locations"]], [0, 1.5, 2, 2.25])

    def test_triplet_quantization(self):
        rows = ["1000"] * 12
        data = result(sm("\n".join(rows)))
        self.assertEqual(data["quantization_arrows"]["4"], 4)
        self.assertEqual(data["quantization_arrows"]["12"], 8)

    def test_reference_cohorts_and_zero_mean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "averages.csv"
            path.write_text(",Single Play by Rating Averages (Arcade and GRAND PRIX)\n"
                            "Rating,AVERAGE of Steps,AVERAGE of Jumps,AVERAGE of Holds\n"
                            "10,2,0,\n\n"
                            ",Double Play by Rating Averages (Arcade and GRAND PRIX)\n"
                            "Rating,AVERAGE of Steps,AVERAGE of Jumps,AVERAGE of Holds\n"
                            "10,8,1,1\n")
            tables = read_averages(path)
            chart = analyze_simfile(sm(sequence([0, 1, 2, 3])))[0]
            comparison = compare_averages(chart, tables)
            self.assertEqual(len(comparison), 1)
            self.assertEqual(comparison[0]["metrics"]["press_rows"]["ratio_to_mean"], 2)
            self.assertIsNone(comparison[0]["metrics"]["jump_rows"]["ratio_to_mean"])
            self.assertNotIn("holds", comparison[0]["metrics"])
            chart["meter"] = "99"
            self.assertEqual(compare_averages(chart, tables), [])

    def test_hold_lock_and_release(self):
        data = result(sm("2000\n0100\n0010\n3001"), include_events=True)
        for profile in data["footwork"].values():
            assignments = profile["assignments"]
            self.assertEqual(profile["analysed_press_rows"], 4)
            held_foot = assignments[0]["feet"][0]
            self.assertNotEqual(assignments[1]["feet"][0], held_foot)
            self.assertNotEqual(assignments[2]["feet"][0], held_foot)
            self.assertIn("doublesteps", assignments[2]["patterns"])

    def test_profile_sensitivity(self):
        data = result(sm(sequence([0, 1, 3, 2, 0, 1, 3, 2])))
        alternate = data["footwork"]["prefer_alternation"]["counts"]
        uncrossed = data["footwork"]["prefer_uncrossed"]["counts"]
        self.assertGreater(alternate["crossed_rows"], uncrossed["crossed_rows"])
        self.assertLess(alternate["doublesteps"], uncrossed["doublesteps"])

    def test_feet_coverage_and_unavailable(self):
        data = result(sm("1110\n2000\n0110\n3001"))
        for profile in data["footwork"].values():
            self.assertEqual(profile["analysed_press_rows"] + profile["excluded_press_rows"], 4)
            self.assertIn("brackets", profile["unavailable"])
        dp = result(sm("10000000\n01000000\n00100000\n00010000", mode="dance-double"))
        self.assertEqual(dp["counts"]["arrows"], 4)
        self.assertEqual(dp["footwork"]["status"], "unsupported_double_footwork")
        self.assertEqual(len(dp["lane_arrows"]), 8)

    def test_empty_single_and_broken_hold(self):
        empty = result(sm("0000\n0000\n0000\n0000"))
        self.assertEqual(empty["counts"]["arrows"], 0)
        self.assertIsNone(empty["density"]["arrows_per_second"])
        self.assertIsNone(empty["timing"]["start_second"])
        data = result(sm("2000\n0000\n0000\n0000"))
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIsNone(data["density"]["arrows_per_second"])
        json.dumps(data, allow_nan=False)

    def test_duplicate_difficulties_keep_chart_identity(self):
        extra = "#NOTEDATA:;#STEPSTYPE:dance-single;#DIFFICULTY:Hard;#METER:12;#NOTES:1000;"
        charts = analyze_simfile(ssc(sequence([0, 1]), extra=extra))
        self.assertEqual([c["chart_index"] for c in charts], [0, 1])
        self.assertEqual([c["analysis"]["counts"]["arrows"] for c in charts], [2, 1])

    def test_rules_validation(self):
        for kwargs in ({"max_gap_seconds": 0}, {"max_gap_beats": float("nan")},
                       {"stream_min_rows": 1}, {"density_window_seconds": -1}):
            with self.assertRaises(ValueError):
                PatternRules(**kwargs)

    def test_cli_keeps_inputs_and_emits_json(self):
        script = Path(__file__).resolve().parents[1] / "src" / "analyze_patterns.py"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "chart.sm"
            original = str(sm(sequence([0, 1, 2, 3])))
            source.write_text(original)
            run = subprocess.run([sys.executable, str(script), str(source), "--events"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            parsed = json.loads(run.stdout)
            self.assertEqual(len(parsed["simfiles"][0]["charts"]), 1)
            self.assertEqual(source.read_text(), original)


if __name__ == "__main__":
    unittest.main()
