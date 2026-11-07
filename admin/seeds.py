"""
The hand-maintained inputs (removed songs, title map, scrape lists, course
lists, chart patches). Every save is checked, then committed to prep with a
message, so the reason for each edit stays in git.
"""

import subprocess

from . import paths, util


def _path(name):
    if name not in paths.SEEDS:
        raise util.Refused(f"No seed file called {name}")
    return paths.PREP / paths.SEEDS[name]


def read(name: str) -> str:
    p = _path(name)
    return p.read_text() if p.exists() else ""


def _problems(name: str, text: str) -> list[str]:
    lines = [l for l in text.splitlines() if l.strip()]
    if name == "removed":
        if lines != sorted(lines, key=lambda s: s.encode()):
            return ["Keep removed.txt in byte order (LC_ALL=C sort)"]
        if len(set(lines)) != len(lines):
            return ["A song is listed twice"]
        scraped = {p.name for p in paths.DATA.glob("*/*") if p.is_dir()}
        before = set(read(name).splitlines())
        typos = [l for l in lines if l not in scraped and l not in before]
        if typos:
            return [f"Not a scraped song folder (spelling must be exact): {typos[:5]}"]
    if name == "chart_patches":
        p = subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True)
        if p.returncode:
            return [f"Shell syntax: {p.stderr.strip()}"]
    if name == "title_map":
        bad = [l for l in lines if l.count(",") < 1]
        if bad:
            return [f"Each line is old,new: {bad[:3]}"]
    if name in ("songs", "packs"):
        bad = [l for l in lines if not l.startswith("#") and len(l.split("\t")) < 2]
        if bad:
            return [f"Tab-separated lines expected: {bad[:3]}"]
    return []


def preview(name: str, text: str) -> dict:
    return {"problems": _problems(name, text), "diff": _diff(name, text)}


def _diff(name, text):
    p = subprocess.run(["git", "diff", "--no-index", "--", str(_path(name)), "-"], input=text,
                       capture_output=True, text=True, cwd=paths.PREP)
    return p.stdout


def save(name: str, text: str, message: str) -> dict:
    if not message.strip():
        raise util.Refused("Say why, for the commit message")
    if not text.endswith("\n"):
        text += "\n"
    problems = _problems(name, text)
    if problems:
        raise util.Refused("; ".join(problems))
    p = _path(name)
    if p.exists() and p.read_text() == text:
        raise util.Refused("No change")
    p.write_text(text)
    rel = paths.SEEDS[name]
    util.git(paths.PREP, "add", "--", rel)
    util.git(paths.PREP, "commit", "--quiet", "-m", f"seeds: {message.strip()}", "--", rel)
    util.log("seed.save", seed=name, message=message.strip())
    return {"commit": util.git(paths.PREP, "rev-parse", "HEAD")}


def add_line(name: str, line: str, message: str) -> dict:
    lines = [l for l in read(name).splitlines() if l.strip()]
    if line in lines:
        raise util.Refused(f"Already in {name}")
    lines.append(line)
    if name == "removed":
        lines.sort(key=lambda s: s.encode())
    return save(name, "\n".join(lines) + "\n", message)


def push_prep() -> dict:
    branch = util.git(paths.PREP, "branch", "--show-current")
    util.git(paths.PREP, "push", "--quiet", "-u", "origin", branch)
    util.log("prep.push", branch=branch)
    return {"branch": branch}
