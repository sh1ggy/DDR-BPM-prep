"""Small shared helpers: commands, git, HTTP and the activity log."""

import datetime
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import paths


class Refused(Exception):
    """An action the console won't take, with the reason shown to the user."""


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd: list[str], cwd: Path | None = None, input: str | None = None, check=True) -> str:
    p = subprocess.run(cmd, cwd=cwd, input=input, capture_output=True, text=True)
    if check and p.returncode:
        raise Refused(f"{' '.join(cmd[:3])} failed: {(p.stderr or p.stdout).strip()[-400:]}")
    return p.stdout.strip()


def git(repo: Path, *args: str, check=True) -> str:
    return run(["git", "-C", str(repo), *args], check=check)


def fetch_json(url: str, timeout=15):
    """The JSON at url, or None on a 404. Cloudflare turns away Python's default agent."""
    req = urllib.request.Request(url, headers={"User-Agent": "ddr-md-release-console"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def log(action: str, **detail) -> None:
    paths.LOG.mkdir(parents=True, exist_ok=True)
    with open(paths.LOG / "activity.jsonl", "a") as f:
        f.write(json.dumps({"at": now(), "action": action, **detail}, ensure_ascii=False) + "\n")


def activity(limit=50) -> list[dict]:
    f = paths.LOG / "activity.jsonl"
    if not f.exists():
        return []
    lines = f.read_text().splitlines()[-limit:]
    return [json.loads(l) for l in reversed(lines)]
