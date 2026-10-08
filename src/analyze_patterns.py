"""Name: analyze_patterns
Parent: metadata pipeline
Description: Analyse SM/SSC charts independently of the song catalogue.
"""

import argparse
import json
from pathlib import Path

import simfile

from classes.PatternAnalyzer import PatternRules, analyze_simfile
from classes.PatternReference import read_averages, compare_averages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+", help="SM/SSC files or directories (recursive)")
    parser.add_argument("--output", type=Path, help="JSON output path; defaults to stdout")
    parser.add_argument("--events", action="store_true", help="Include pattern locations and inferred feet")
    parser.add_argument("--averages", type=Path, help="Optional reference Averages CSV for count ratios by rating/difficulty")
    parser.add_argument("--max-gap-beats", type=float, default=1.0)
    parser.add_argument("--max-gap-seconds", type=float, default=1.0)
    parser.add_argument("--stream-gap-beats", type=float, default=0.5)
    parser.add_argument("--stream-min-rows", type=int, default=8)
    parser.add_argument("--density-window-seconds", type=float, default=1.0)
    args = parser.parse_args()
    try:
        rules = PatternRules(args.max_gap_beats, args.max_gap_seconds,
                             args.stream_gap_beats, args.stream_min_rows,
                             args.density_window_seconds)
    except ValueError as error:
        parser.error(str(error))
    files = set()
    for path in args.paths:
        if not path.exists():
            parser.error(f"Path does not exist: {path}")
        candidates = path.rglob("*") if path.is_dir() else [path]
        files.update(p.resolve() for p in candidates if p.is_file() and p.suffix.lower() in (".sm", ".ssc"))
    if not files:
        parser.error("No SM/SSC files found")
    results = []
    try:
        averages = read_averages(args.averages) if args.averages else None
    except (OSError, ValueError) as error:
        parser.error(str(error))
    for path in sorted(files):
        try:
            sim = simfile.open(str(path))
            charts = analyze_simfile(sim, rules, args.events)
            if averages is not None:
                for chart in charts:
                    chart["reference_comparisons"] = compare_averages(chart, averages)
            results.append({"source": str(path), "title": sim.title, "charts": charts})
        except Exception as error:
            parser.exit(1, f"Failed to analyse {path}: {error}\n")
    report = {"schema_version": 1, "simfiles": results}
    if args.averages:
        report["reference_averages"] = str(args.averages.resolve())
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        if args.output.resolve() in files or (args.averages and args.output.resolve() == args.averages.resolve()):
            parser.error("Output must not overwrite an input file")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
