"""Name: PatternReference
Parent: pattern analysis
Description: Optional count comparisons against the supplied Averages CSV layout.
"""

import csv
from math import isfinite


DIFFICULTIES = {"beginner": "Beginner", "easy": "Basic", "medium": "Difficult",
                "hard": "Expert", "challenge": "Challenge"}
METRICS = {"press_rows": "AVERAGE of Steps", "jump_rows": "AVERAGE of Jumps",
           "holds": "AVERAGE of Holds"}


def read_averages(path):
    """Treat headings as data, never execute cell contents or follow links."""
    tables = {}
    mode = group = header = None
    with open(path, encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source):
            heading = " ".join(row)
            if "Play by" in heading and "Averages" in heading:
                mode = "sp" if "Single Play" in heading else "dp" if "Double Play" in heading else None
                group = "rating" if "by Rating" in heading else "difficulty" if "by Difficulty" in heading else None
                header = None
            elif row and row[0] in ("Rating", "Difficulty") and mode and group:
                header = row
            elif header and row and row[0].strip():
                cells = dict(zip(header, row))
                values = {}
                for metric, name in METRICS.items():
                    try:
                        value = float(cells.get(name, ""))
                    except ValueError:
                        continue
                    if isfinite(value) and value >= 0:
                        values[metric] = value
                if values:
                    key = (mode, group, row[0])
                    if key in tables:
                        raise ValueError(f"Duplicate averages cohort: {key}")
                    tables[key] = values
    if not tables:
        raise ValueError("No SP/DP rating or difficulty average tables found")
    return tables


def compare_averages(chart_result, tables):
    mode = {"dance-single": "sp", "dance-double": "dp"}.get(chart_result["stepstype"])
    analysis = chart_result["analysis"]
    if analysis["status"] != "ok":
        return []
    cohorts = (("rating", str(chart_result["meter"])),
               ("difficulty", DIFFICULTIES.get((chart_result["difficulty"] or "").lower())))
    comparisons = []
    for group, name in cohorts:
        baseline = tables.get((mode, group, name))
        if baseline is None:
            continue
        comparisons.append({"mode": mode, "group": group, "cohort": name,
                            "metrics": {metric: {"chart": analysis["counts"][metric],
                                                 "reference_mean": average,
                                                 "ratio_to_mean": round(analysis["counts"][metric] / average, 6) if average else None}
                                        for metric, average in baseline.items()}})
    return comparisons
