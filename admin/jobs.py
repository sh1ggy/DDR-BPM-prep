"""
Long-running work (parse, scrape, builds), one at a time. Every job writes
log/admin/jobs/<id>.log and a <id>.json record, and lands in the activity
log, so anything that ran is visible afterwards.
"""

import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import paths, util

JOBS = paths.LOG / "jobs"
_lock = threading.Lock()
_current: dict | None = None
_proc: subprocess.Popen | None = None


def _make(*targets, **env):
    return {"cmd": ["make", *targets], "cwd": paths.PREP, "env": env}


def _py(script, *args):
    return {"cmd": ["poetry", "run", "python", f"src/{script}", *args], "cwd": paths.PREP, "env": {}}


def _ddr(script, *args, **env):
    return {"cmd": ["bash", f"scripts/{script}", *args], "cwd": paths.DDR_MD, "env": env}


# name -> (label, step builder taking the job's params). Each step is a
# command; a job stops at the first that fails.
CATALOG = {
    "prepare": ("Prepare everything", lambda p: [_make("prepare")]),
    "parse": ("Parse simfiles", lambda p: [_make("parse")]),
    "simfile_sync": ("Merge simfile sync", lambda p: [_py("sync_songs.py", *p.get("songs", []))]),
    "simfile_sync_full": ("Simfile sync, extracting audio (hours on a fresh cache)", lambda p: [_make("sync")]),
    "arcade_sync": ("Arcade sync", lambda p: [_py("arcade_sync.py", *p.get("songs", []))]),
    "arcade_sync_force": ("Arcade sync, recomputing the cache", lambda p: [_make("arcade_sync-force")]),
    "arcade_timesigs": ("Time signatures", lambda p: [_py("arcade_timesigs.py", *p.get("songs", []))]),
    "tiers": ("Scoring tiers", lambda p: [_make("tiers", **({"SONG": p["song"]} if p.get("song") else {})),
                                          _make("tiers-check")]),
    "jackets": ("Stage jackets", lambda p: [_make("jackets-force" if p.get("force") else "jackets")]),
    "song": ("Rebuild one song's data", lambda p: [
        _py("sync_songs.py", p["song"]), _py("arcade_sync.py", p["song"]),
        _py("arcade_timesigs.py", p["song"]),
        _make("tiers", SONG=p["song"]), _make("tiers-check"), _make("jackets")]),
    "scrape_packs": ("Scrape packs from Zenius", lambda p: [_make("full_scrape")]),
    "scrape_song": ("Scrape one song from Zenius", lambda p: [
        {"cmd": ["bash", "scripts/scrape/zenius_song.sh", str(p["simfile_id"]), p["version"]],
         "cwd": paths.PREP, "env": {"SEED_DIR": "./data"}}]),
    "konami_fetch": ("Refresh the Konami song list (signed in)", lambda p: [_make("konami_music")]),
    "konami_relink": ("Relink Konami IDs from saved pages", lambda p: [_py("konami_music.py", "-l")]),
    "noteskin": ("Extract noteskin to assets", lambda p: [
        _make("noteskin"),
        {"cmd": ["rsync", "-a", "--delete", "build/noteskin/", str(paths.DDR_MD / "assets/noteskin/")],
         "cwd": paths.PREP, "env": {}}]),
    "scoring_restore": ("Restore the scoring bundle", lambda p: [
        {"cmd": ["bash", "-c", "mkdir -p build && gh release download scoring-v31 --repo "
                 f"{paths.CONTENT_REPO} --pattern 'scoring-v31-macos.*' --dir build --clobber && "
                 "(cd build && shasum -a 256 -c scoring-v31-macos.sha256) && "
                 "tar -xzf build/scoring-v31-macos.tar.gz -C build"], "cwd": paths.DDR_MD, "env": {}}]),
    "fetch_content": ("Put the live content in the app's assets", lambda p: [_ddr("fetch_content.sh")]),
    "store_build": ("Store build", lambda p: [_ddr("build_store.sh", p["target"])]),
    "lite_build": ("Lite build", lambda p: [_ddr("build_lite.sh", *p.get("args", []))]),
}


def fingerprint() -> str:
    """What a prepare reads: prep's code and seed files, the scraped song folders, the arcade data and ddr-md's scoring tool."""
    h = hashlib.sha256()
    h.update(util.git(paths.PREP, "rev-parse", "HEAD").encode())
    h.update(util.git(paths.PREP, "diff", "HEAD", "--", "src", "scripts", "data", "Makefile", "Makefiles").encode())
    for d in sorted(paths.DATA.glob("*/*")):
        if d.is_dir():
            h.update(f"{d.relative_to(paths.DATA)}:{d.stat().st_mtime_ns}".encode())
    h.update(util.git(paths.DDR_MD, "log", "-1", "--format=%H", "--", "tool/scoring").encode())
    return h.hexdigest()[:16]


def prepared() -> dict | None:
    f = paths.LOG / "prepared.json"
    return json.loads(f.read_text()) if f.exists() else None


def current() -> dict | None:
    return _current


def history(limit=20) -> list[dict]:
    if not JOBS.exists():
        return []
    recs = sorted(JOBS.glob("*.json"), reverse=True)[:limit]
    return [json.loads(r.read_text()) for r in recs]


def log_text(job_id: str, start=0) -> str:
    f = JOBS / f"{job_id}.log"
    if not f.exists() or "/" in job_id:
        return ""
    with open(f, "rb") as fh:
        fh.seek(start)
        return fh.read().decode(errors="replace")


def start(name: str, params: dict | None = None, wait=False, echo=False) -> dict:
    """Run a catalog job. Refuses while another job runs."""
    global _current
    if name not in CATALOG:
        raise util.Refused(f"No job called {name}")
    if not _lock.acquire(blocking=False):
        raise util.Refused(f"{_current['label']} is still running")
    params = params or {}
    label, build = CATALOG[name]
    try:
        steps = build(params)
    except KeyError as e:
        _lock.release()
        raise util.Refused(f"{label} needs {e.args[0]}")
    JOBS.mkdir(parents=True, exist_ok=True)
    job_id = time.strftime("%Y%m%d-%H%M%S") + f"-{name}"
    job = _current = {"id": job_id, "name": name, "label": label, "params": params,
                      "started": util.now(), "status": "running"}
    util.log("job.start", job=job_id, label=label, params=params)
    t = threading.Thread(target=_run, args=(steps, echo), daemon=True)
    t.start()
    if wait:
        t.join()
    return job


def stop() -> None:
    if _proc and _proc.poll() is None:
        _proc.terminate()


def _run(steps, echo):
    global _current, _proc
    job = _current
    fp = fingerprint() if job["name"] == "prepare" else None
    code = 0
    with open(JOBS / f"{job['id']}.log", "w") as out:
        for step in steps:
            out.write(f"$ {' '.join(step['cmd'])}\n")
            out.flush()
            _proc = subprocess.Popen(step["cmd"], cwd=step["cwd"], env={**os.environ, **step["env"]},
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in _proc.stdout:
                out.write(line)
                out.flush()
                if echo:
                    print(line, end="")
            code = _proc.wait()
            if code:
                break
    job.update(ended=util.now(), exit=code, status="done" if code == 0 else "failed")
    (JOBS / f"{job['id']}.json").write_text(json.dumps(job, indent=1))
    if job["name"] == "prepare" and code == 0:
        (paths.LOG / "prepared.json").write_text(json.dumps({"at": job["ended"], "fingerprint": fp}))
    util.log("job.end", job=job["id"], status=job["status"], exit=code)
    _current = None
    _proc = None
    _lock.release()
