"""
Releases: the only way content reaches players.

Draft → Checks → Staging → Signed off → Live → Confirmed. A release is a
commit on the content repo's staging branch carrying release.json; staging
CI publishes it to the staging host for testing; signing off records the
tested manifest id and fast-forwards master to it, and production CI refuses
to publish anything else (see publish-content.yml in ddr-md). Nothing here is
stored locally: the record and its history are the content repo's git.
"""

import hashlib
import json
import shutil
import threading
from pathlib import Path

from . import diff, jobs, paths, util

DIRS = list(paths.KINDS)
KINDS = ("add", "fix", "remove", "engine", "site", "rollback")
_lock = threading.Lock()


def _git(*args, check=True):
    return util.git(paths.CONTENT, *args, check=check)


def content_hash(tree: str = "HEAD") -> str:
    """Hash of the published directories' git trees. Matches check_release.py in ddr-md."""
    text = "".join(f"{d} {_git('rev-parse', f'{tree}:{d}')}\n" for d in DIRS)
    return hashlib.sha256(text.encode()).hexdigest()


def record(ref: str) -> dict | None:
    out = _git("show", f"{ref}:release.json", check=False)
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def _sync():
    """Fetch, and refuse to touch a checkout that has work of its own in it."""
    if not (paths.CONTENT / ".git").exists():
        raise util.Refused(f"No content checkout at {paths.CONTENT}")
    _git("fetch", "--quiet", "origin")
    if _git("status", "--porcelain"):
        raise util.Refused("The content checkout has uncommitted changes. Release from a clean checkout.")
    master = _git("rev-parse", "origin/master")
    if _git("rev-parse", "--verify", "--quiet", "master", check=False) not in ("", master) and \
            _git("rev-list", "origin/master..master", check=False):
        raise util.Refused("Local master has commits that aren't on origin. Content only ships through a release.")
    return master


def _app_master() -> str:
    return util.run(["gh", "api", f"repos/{paths.APP_REPO}/commits/master", "--jq", ".sha"])


def _prep_commit() -> str:
    head = util.git(paths.PREP, "rev-parse", "HEAD")
    if not util.git(paths.PREP, "branch", "-r", "--contains", head, check=False):
        raise util.Refused("Prep has commits that aren't pushed. Push prep first, so the release can name what built it.")
    return head


def in_progress() -> bool:
    return bool(_git("rev-list", "origin/master..origin/staging", check=False)) or \
        bool(_git("rev-list", "origin/staging..staging", check=False))


def _start_branch(replace: bool):
    master = _sync()
    if in_progress() and not replace:
        raise util.Refused("A release is already in progress. Promote or discard it first.")
    _git("switch", "--quiet", "-C", "staging", master)


def _abort():
    """Undo a half-made draft: the checkout was clean before it started."""
    _git("reset", "--hard", "--quiet", check=False)
    _git("clean", "-fdq", "--", *DIRS, check=False)
    _git("switch", "--quiet", "-C", "staging", "origin/staging", check=False)


def _write_record(rec: dict):
    (paths.CONTENT / "release.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")


def _finish_draft(rec: dict, changes: list[diff.SongChange]):
    _git("add", "-A", *DIRS)
    tree = _git("write-tree")
    rec["content_hash"] = content_hash(tree)
    _write_record(rec)
    _git("add", "release.json")
    _git("commit", "--quiet", "-m", f"content: {rec['title']}", "-m", rec.get("notes") or "")
    (paths.LOG / "drafts").mkdir(parents=True, exist_ok=True)
    sha = _git("rev-parse", "HEAD")
    (paths.LOG / "drafts" / f"{sha}.json").write_text(json.dumps([c.as_dict() for c in changes], ensure_ascii=False))
    util.log("release.draft", commit=sha, title=rec["title"], kind=rec["kind"], songs=rec["songs"])
    return {"commit": sha, "record": rec, "changes": [c.as_dict() for c in changes]}


def _base_record(kind, title, notes, app_commit=None):
    if kind not in KINDS:
        raise util.Refused(f"Kind must be one of {', '.join(KINDS)}")
    if not title.strip():
        raise util.Refused("Give the release a title")
    live = util.fetch_json(f"{paths.LIVE_URL}/latest.json") or {}
    return {"schema": 1, "title": title.strip(), "kind": kind, "notes": notes.strip(),
            "songs": {"added": [], "changed": [], "removed": []}, "removes": [],
            "app_commit": app_commit or _app_master(), "prep_commit": _prep_commit(),
            "content_hash": None, "expected_id": None, "previous_id": live.get("id"),
            "tested": None, "created_at": util.now()}


def draft(songs: list[str], removes: list[str], title: str, notes="", kind="add", replace=False) -> dict:
    """Stage build/ files for songs, delete removes, record it. Local only until stage()."""
    with _lock:
        if jobs.current():
            raise util.Refused("A job is changing the build. Wait for it to finish.")
        if not songs and not removes:
            raise util.Refused("Pick at least one song to add, change or remove")
        missing = [f"{n}: {k}" for n in songs for k, p in diff.files(paths.BUILD, n).items() if not p.exists()]
        if missing:
            raise util.Refused(f"Missing from the build: {', '.join(missing[:5])}")
        rec = _base_record(kind, title, notes)
        _start_branch(replace)
        try:
            return _draft_files(rec, songs, removes)
        except Exception:
            _abort()
            raise


def _draft_files(rec, songs, removes):
    changes = [diff.song_change(n, paths.CONTENT, paths.BUILD) for n in songs]
    for n in songs:
        for k, src in diff.files(paths.BUILD, n).items():
            shutil.copy2(src, diff.files(paths.CONTENT, n)[k])
    for n in removes:
        if not (paths.CONTENT / "songs" / f"{n}.json").exists():
            raise util.Refused(f"{n} isn't live")
        changes.append(diff.song_change(n, paths.CONTENT, Path("/nonexistent")))
        for p in diff.files(paths.CONTENT, n).values():
            p.unlink(missing_ok=True)
    for c in changes:
        key = {"new": "added", "changed": "changed", "removed": "removed"}.get(c.status)
        if key:
            rec["songs"][key].append(c.name)
    rec["removes"] = list(removes)
    if not any(rec["songs"].values()):
        raise util.Refused("Those songs are already live exactly as built")
    return _finish_draft(rec, changes)


def draft_pin(kind: str, title: str, notes="", app_commit: str | None = None, replace=False) -> dict:
    """A release with no song files changed: new generators (engine) or the privacy page and app links (site)."""
    with _lock:
        if kind not in ("engine", "site"):
            raise util.Refused("Only engine and site releases leave the songs alone")
        rec = _base_record(kind, title, notes, app_commit)
        _start_branch(replace)
        return _finish_draft(rec, [])


def rollback(to: str, title: str = "", notes="") -> dict:
    """A new release whose content and generators are those of an earlier one."""
    with _lock:
        _sync()
        old = record(to)
        if not old:
            raise util.Refused("Only releases made by the console can be rolled back to")
        _start_branch(replace=False)
        try:
            return _rollback_files(to, old, title, notes)
        except Exception:
            _abort()
            raise


def _rollback_files(to, old, title, notes):
    before = diff.names(paths.CONTENT)
    _git("rm", "-r", "--quiet", *DIRS)
    _git("checkout", to, "--", *DIRS)
    gone = sorted(before - diff.names(paths.CONTENT))
    rec = {**_base_record("rollback", title or f"Roll back to {old['title']}", notes, old["app_commit"]),
           "removes": gone, "expected_id": old.get("expected_id")}
    rec["songs"]["removed"] = gone
    return _finish_draft(rec, [diff.SongChange(n, "removed") for n in gone])


def checks() -> dict:
    """Checks on the drafted commit that don't need the generators. CI runs the rest on staging."""
    sha = _git("rev-parse", "staging")
    rec = record("staging") or {}
    problems, warnings = [], []
    if rec.get("content_hash") != content_hash("staging"):
        problems.append("release.json doesn't describe these files")
    live = set(n[:-5] for n in _git("ls-tree", "--name-only", "origin/master:songs").splitlines())
    now = set(n[:-5] for n in _git("ls-tree", "--name-only", "staging:songs").splitlines())
    gone = sorted(live - now - set(rec.get("removes") or []))
    if gone:
        problems.append(f"Songs would disappear without being named as removed: {gone[:5]}")
    for d in DIRS[1:]:
        have = set(Path(n).stem for n in _git("ls-tree", "--name-only", f"staging:{d}").splitlines())
        if now - have:
            problems.append(f"{len(now - have)} songs have no {d}, e.g. {sorted(now - have)[:3]}")
    _git("switch", "--quiet", "staging")
    v = util.run(["python3", str(paths.DDR_MD / "tool/scoring/validate_content.py"),
                  "--songs", str(paths.CONTENT / "songs"), "--steps", str(paths.CONTENT / "steps")], check=False)
    try:
        problems += json.loads(v)["problems"]
    except (json.JSONDecodeError, KeyError):
        problems.append(f"Scoring validation didn't run: {v[-300:]}")
    shared = paths.DDR_MD / "tool/content/check_release.py"
    if shared.exists():
        out = util.run(["python3", str(shared), "--content", str(paths.CONTENT), "--ref", "staging",
                        "--live", paths.LIVE_URL, "--local"], check=False)
        try:
            r = json.loads(out)
            problems += r.get("problems", [])
            warnings += r.get("warnings", [])
        except json.JSONDecodeError:
            problems.append(f"check_release.py: {out[-300:]}")
    drafted = paths.LOG / "drafts" / f"{sha}.json"
    if drafted.exists():
        for c in json.loads(drafted.read_text()):
            warnings += [f"{c['name']}: {w}" for w in c["warnings"]]
    result = {"commit": sha, "at": util.now(), "problems": problems, "warnings": warnings, "ok": not problems}
    (paths.LOG / "checks").mkdir(parents=True, exist_ok=True)
    (paths.LOG / "checks" / f"{sha}.json").write_text(json.dumps(result, ensure_ascii=False))
    util.log("release.checks", commit=sha, ok=result["ok"], problems=len(problems))
    return result


def last_checks(sha: str) -> dict | None:
    f = paths.LOG / "checks" / f"{sha}.json"
    return json.loads(f.read_text()) if f.exists() else None


def _pr_body(sha: str) -> str:
    rec = record(sha) or {}
    drafted = paths.LOG / "drafts" / f"{sha}.json"
    lines = [rec.get("notes") or "", "", f"Kind: {rec.get('kind')} · generators "
             f"`{(rec.get('app_commit') or '')[:7]}` · prep `{(rec.get('prep_commit') or '')[:7]}`", ""]
    for c in json.loads(drafted.read_text()) if drafted.exists() else []:
        lines.append(f"- **{c['name']}** ({c['status']}): {'; '.join(c['changes'])}")
        lines += [f"  - ⚠ {w}" for w in c["warnings"]]
    lines += ["", "Made by the release console. Sign off there (or on the phone page); "
              "don't merge this PR by hand: master only takes a signed-off release."]
    return "\n".join(lines)


def stage() -> dict:
    """Push the checked draft to staging and open its PR. Staging CI publishes it for testing."""
    with _lock:
        _git("fetch", "--quiet", "origin")
        sha = _git("rev-parse", "staging")
        c = last_checks(sha)
        if not c or not c["ok"]:
            raise util.Refused("Run the checks on this draft first, and fix what they find")
        _git("push", "--quiet", f"--force-with-lease=staging:{_git('rev-parse', 'origin/staging')}",
             "origin", "staging")
        rec = record(sha)
        title = rec["title"]
        prs = util.run(["gh", "pr", "list", "-R", paths.CONTENT_REPO, "--head", "staging",
                        "--base", "master", "--json", "number", "--jq", ".[].number"])
        body = _pr_body(sha)
        if prs:
            util.run(["gh", "pr", "edit", prs.split()[0], "-R", paths.CONTENT_REPO, "--title", title, "--body", body])
        else:
            util.run(["gh", "pr", "create", "-R", paths.CONTENT_REPO, "--head", "staging", "--base", "master",
                      "--title", title, "--body", body])
        util.log("release.stage", commit=sha, title=title)
        return {"commit": sha}


def ci_run(branch: str, sha: str) -> dict | None:
    out = util.run(["gh", "run", "list", "-R", paths.CONTENT_REPO, "--branch", branch, "--commit", sha,
                    "-L", "1", "--json", "databaseId,status,conclusion,url,event"], check=False)
    runs = json.loads(out or "[]")
    return runs[0] if runs else None


def sign_off(note: str) -> dict:
    """Record the test and the tested id, then fast-forward master to it."""
    with _lock:
        if len(note.strip()) < 3:
            raise util.Refused("Say how you tested it")
        _git("fetch", "--quiet", "origin")
        sha = _git("rev-parse", "origin/staging")
        if not _git("rev-list", "origin/master..origin/staging"):
            raise util.Refused("Nothing on staging to sign off")
        rec = record(sha)
        if rec.get("kind") != "rollback" or not rec.get("expected_id"):
            run = ci_run("staging", sha)
            if not run or run["conclusion"] != "success":
                raise util.Refused("Staging CI hasn't published this release yet")
            rec["expected_id"] = (util.fetch_json(f"{paths.STAGING_URL}/latest.json") or {}).get("id")
        rec["tested"] = {"at": util.now(), "note": note.strip()}
        _git("switch", "--quiet", "-C", "staging", sha)
        _write_record(rec)
        _git("commit", "--quiet", "-am", f"release: signed off, {rec['title']}")
        _git("push", "--quiet", "origin", "staging")
        _git("push", "--quiet", "origin", "staging:master")
        _git("switch", "--quiet", "-C", "master", "origin/master")
        util.log("release.promote", commit=_git("rev-parse", "HEAD"), title=rec["title"],
                 expected_id=rec["expected_id"], note=rec["tested"]["note"])
        return {"commit": _git("rev-parse", "HEAD"), "expected_id": rec["expected_id"]}


def promote_rollback(confirm: str) -> dict:
    """A rollback to a release that was live goes straight to master: its id is already known."""
    with _lock:
        rec = record("staging") or {}
        if rec.get("kind") != "rollback" or not rec.get("expected_id"):
            raise util.Refused("Only a drafted rollback can skip staging")
        if confirm != "roll back":
            raise util.Refused('Type "roll back" to confirm')
        c = last_checks(_git("rev-parse", "staging"))
        if not c or not c["ok"]:
            raise util.Refused("Run the checks on the rollback first")
    stage()
    return sign_off("Rollback to a release that was live, not retested")


def discard() -> dict:
    with _lock:
        _git("fetch", "--quiet", "origin")
        _git("switch", "--quiet", "-C", "staging", "origin/master")
        _git("push", "--quiet", "--force-with-lease", "origin", "staging")
        _git("switch", "--quiet", "-C", "master", "origin/master")
        util.log("release.discard")
        return {"ok": True}


def history(limit=30) -> list[dict]:
    out = _git("log", "origin/master", f"-{limit}", "--format=%H %cs", "--", "release.json", check=False)
    items = []
    for line in out.splitlines():
        sha, date = line.split()
        rec = record(sha)
        if rec and rec.get("tested"):
            items.append({"commit": sha, "date": date, **rec})
    return items


def state() -> dict:
    """Where the current release is, for the home page and the release page."""
    _git("fetch", "--quiet", "origin", check=False)
    live_id = (util.fetch_json(f"{paths.LIVE_URL}/latest.json") or {}).get("id")
    staging_id = (util.fetch_json(f"{paths.STAGING_URL}/latest.json") or {}).get("id")
    master = _git("rev-parse", "origin/master")
    live_rec = record(master)
    unreleased = None
    if live_rec is None or live_rec.get("content_hash") != content_hash(master):
        unreleased = master
    local = _git("rev-parse", "staging", check=False)
    remote = _git("rev-parse", "origin/staging")
    stage_name, draft_sha = None, None
    if local and _git("rev-list", "origin/master..staging", check=False) and local != remote:
        stage_name, draft_sha = "checks" if not (last_checks(local) or {}).get("ok") else "ready to stage", local
    elif _git("rev-list", "origin/master..origin/staging", check=False):
        draft_sha = remote
        run = ci_run("staging", remote)
        stage_name = "staging" if not run or run["status"] != "completed" else \
            ("sign off" if run["conclusion"] == "success" else "staging failed")
    confirmed = bool(live_rec and live_rec.get("expected_id") == live_id)
    return {"live_id": live_id, "staging_id": staging_id, "master": master, "live_record": live_rec,
            "confirmed": confirmed, "unreleased_commit": unreleased, "stage": stage_name,
            "draft_commit": draft_sha, "draft": record(draft_sha) if draft_sha else None,
            "checks": last_checks(draft_sha) if draft_sha else None,
            "changes": json.loads((paths.LOG / "drafts" / f"{draft_sha}.json").read_text())
            if draft_sha and (paths.LOG / "drafts" / f"{draft_sha}.json").exists() else [],
            "staging_run": ci_run("staging", remote) if draft_sha == remote else None,
            "master_run": ci_run("master", master)}
