"""
The console's actions from a terminal: `poetry run python -m admin <command>`.
Same code as the page, so scripts and agents follow the same path.
"""

import argparse
import json
import sys

from . import diff, jobs, paths, release, seeds, status, util


def out(x):
    print(json.dumps(x, indent=1, ensure_ascii=False, default=str))


def main(argv=None):
    p = argparse.ArgumentParser(prog="admin", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="Run the console page (make admin)")
    s.add_argument("--port", type=int, default=8767)
    sub.add_parser("status", help="Live, staging, the release in progress and readiness")
    sub.add_parser("inbox", help="Songs waiting for something")
    d = sub.add_parser("diff", help="What the build would change, in chart terms")
    d.add_argument("songs", nargs="*")
    j = sub.add_parser("job", help=f"Run a job and wait: {', '.join(jobs.CATALOG)}")
    j.add_argument("name")
    j.add_argument("params", nargs="*", help="key=value")
    dr = sub.add_parser("draft", help="Draft a release from built songs")
    dr.add_argument("songs", nargs="*")
    dr.add_argument("--remove", action="append", default=[])
    dr.add_argument("--title", required=True)
    dr.add_argument("--notes", default="")
    dr.add_argument("--kind", default="add", choices=["add", "fix", "remove"])
    pin = sub.add_parser("pin", help="Draft an engine or site release")
    pin.add_argument("kind", choices=["engine", "site"])
    pin.add_argument("--title", required=True)
    pin.add_argument("--app-commit")
    sub.add_parser("checks", help="Check the draft")
    sub.add_parser("stage", help="Publish the checked draft to staging")
    so = sub.add_parser("signoff", help="Sign off the staged release and make it live")
    so.add_argument("note")
    sub.add_parser("discard", help="Drop the release in progress")
    rb = sub.add_parser("rollback", help="Draft a rollback to an earlier release")
    rb.add_argument("commit")
    sub.add_parser("history", help="Releases, newest first")
    seed = sub.add_parser("seed-add", help="Add a line to a seed file and commit")
    seed.add_argument("name", choices=list(paths.SEEDS))
    seed.add_argument("line")
    seed.add_argument("--why", required=True)
    a = p.parse_args(argv)

    try:
        if a.cmd == "serve":
            from . import web
            web.serve(a.port)
        elif a.cmd == "status":
            s = release.state()
            out({**{k: s[k] for k in ("live_id", "staging_id", "confirmed", "unreleased_commit", "stage", "draft_commit")},
                 "draft": (s["draft"] or {}).get("title"), "readiness": status.readiness()})
        elif a.cmd == "inbox":
            ib = status.inbox()
            out({**ib, "no_simfile": [r["title"] for r in ib["no_simfile"]]})
        elif a.cmd == "diff":
            out([c.as_dict() for c in diff.compare(paths.CONTENT, paths.BUILD, only=set(a.songs) or None)])
        elif a.cmd == "job":
            params = dict(x.split("=", 1) for x in a.params)
            r = jobs.start(a.name, params, wait=True, echo=True)
            print(f"\n{r['label']}: {r['status']}")
            return 0 if r["status"] == "done" else 1
        elif a.cmd == "draft":
            out(release.draft(a.songs, a.remove, a.title, a.notes, a.kind))
        elif a.cmd == "pin":
            out(release.draft_pin(a.kind, a.title, app_commit=a.app_commit))
        elif a.cmd == "checks":
            r = release.checks()
            out(r)
            return 0 if r["ok"] else 1
        elif a.cmd == "stage":
            out(release.stage())
        elif a.cmd == "signoff":
            out(release.sign_off(a.note))
        elif a.cmd == "discard":
            out(release.discard())
        elif a.cmd == "rollback":
            out(release.rollback(a.commit))
        elif a.cmd == "history":
            out([{k: r.get(k) for k in ("date", "title", "kind", "expected_id", "commit", "tested")} for r in release.history()])
        elif a.cmd == "seed-add":
            out(seeds.add_line(a.name, a.line, a.why))
    except util.Refused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
