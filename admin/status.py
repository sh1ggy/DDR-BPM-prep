"""Readiness and the inbox: what's needed, what's waiting, what's off."""

import csv
import datetime
import getpass
import json
import subprocess
import tempfile
from pathlib import Path

from . import diff, jobs, paths, util


def _repo(path: Path) -> dict:
    if not (path / ".git").exists():
        return {"ok": False, "detail": "missing"}
    dirty = util.git(path, "status", "--porcelain", "--untracked-files=no", check=False)
    branch = util.git(path, "branch", "--show-current", check=False)
    head = util.git(path, "rev-parse", "HEAD", check=False)
    pushed = bool(util.git(path, "branch", "-r", "--contains", head, check=False))
    return {"ok": not dirty and pushed, "branch": branch, "dirty": bool(dirty), "pushed": pushed}


def readiness() -> list[dict]:
    """Each thing a prepare or release needs, as {name, ok, detail, fix}."""
    out = []
    arcade = paths.DATA / "arcade"
    out.append({"name": "Arcade data", "ok": arcade.exists() and any(arcade.iterdir()),
                "detail": "Found" if arcade.exists() else "Not in data/arcade: arcade sync and time signatures will be skipped"})
    bundle = paths.DDR_MD / "build/scoring-v31/manifest.json"
    out.append({"name": "Scoring bundle", "ok": bundle.exists(),
                "detail": "scoring-v31" if bundle.exists() else "Missing: scoring tiers can't run", "fix": "scoring_restore"})
    cookie = subprocess.run(["security", "find-generic-password", "-s", "eagate-session"],
                            capture_output=True).returncode == 0
    out.append({"name": "E-amusement cookie", "ok": cookie,
                "detail": "Stored in the Keychain" if cookie else "Not stored: the Konami song list can't refresh",
                "fix": "cookie"})
    p = jobs.prepared()
    fresh = bool(p and p.get("fingerprint") == jobs.fingerprint())
    out.append({"name": "Build", "ok": fresh,
                "detail": f"Prepared {p['at']}" + ("" if fresh else ", inputs changed since") if p else "Never prepared by the console",
                "fix": "prepare"})
    prep = _repo(paths.PREP)
    out.append({"name": "Prep repo", "ok": prep["ok"],
                "detail": f"{prep.get('branch')}" + (" · uncommitted changes" if prep.get("dirty") else "")
                + ("" if prep.get("pushed") else " · commits not pushed")})
    content = _repo(paths.CONTENT)
    out.append({"name": "Content checkout", "ok": content.get("ok") and not content.get("dirty"),
                "detail": "missing" if content.get("detail") == "missing" else
                f"{content.get('branch')}" + (" · uncommitted changes" if content.get("dirty") else "")})
    return out


def set_cookie(value: str) -> None:
    """Store the e-amusement session cookie. Goes to security(1) on stdin, never argv or a log."""
    value = value.strip()
    if not value:
        raise util.Refused("Paste the cookie value")
    quoted = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    util.run(["security", "-i"], input=f"add-generic-password -a {getpass.getuser()} -s eagate-session -U -w {quoted}\n")
    util.log("cookie.set")


def konami_rows() -> list[dict]:
    f = paths.DATA / "konami.tsv"
    if not f.exists():
        return []
    with open(f, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def set_konami_name(konami_id: str, name: str) -> None:
    """Link a Konami song to a prep song by hand (a rebuild keeps it)."""
    rows = konami_rows()
    if not any(r["konami_id"] == konami_id for r in rows):
        raise util.Refused("No such Konami ID")
    if name and not (paths.BUILD / "songs" / f"{name}.json").exists():
        raise util.Refused(f"No built song called {name}")
    for r in rows:
        if r["konami_id"] == konami_id:
            r["name"] = name
    with open(paths.DATA / "konami.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    util.log("konami.link", konami_id=konami_id, name=name)


def drift() -> dict | None:
    """The last nightly dry run's report, once CI makes one."""
    out = util.run(["gh", "run", "list", "-R", paths.CONTENT_REPO, "--event", "schedule", "-L", "1",
                    "--json", "databaseId,conclusion,createdAt,url"], check=False)
    runs = json.loads(out or "[]")
    if not runs:
        return None
    run = runs[0]
    with tempfile.TemporaryDirectory() as d:
        util.run(["gh", "run", "download", str(run["databaseId"]), "-R", paths.CONTENT_REPO, "-n", "drift", "-D", d],
                 check=False)
        reports = list(Path(d).glob("*.json"))
        report = json.loads(reports[0].read_text()) if reports else None
    return {**run, "report": report}


def inbox() -> dict:
    built, live = diff.names(paths.BUILD), diff.names(paths.CONTENT)
    rows = konami_rows()
    linked = {r["name"] for r in rows if r.get("name")}
    return {
        "no_simfile": [r for r in rows if not r.get("name")],
        "built_not_live": sorted(built - live),
        "changed": [c.as_dict() for c in diff.compare(paths.CONTENT, paths.BUILD, only=built & live)],
        "live_not_in_game": sorted(live - linked) if rows else [],
        "last_scrape": _mtime(paths.DATA / "downloaded.txt"),
    }


def _mtime(p: Path):
    return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d") if p.exists() else None
