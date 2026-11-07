"""Name: Release console tests
Parent: admin (release console)
Description: A release end to end against throwaway git repos: draft, checks,
staging, sign-off, history, then a rollback that removes the added song.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin import diff, paths, release, util  # noqa: E402


def sh(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def song(root: Path, name: str, level: int):
    for d in ("songs", "steps", "jackets", "jackets-160"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "songs" / f"{name}.json").write_text(json.dumps(
        {"name": name, "title": name, "version": "WORLD", "konami_id": "k" + name, "arcade_sync": {},
         "sp": {"hard": level}, "charts": [{"bpm_range": "150"}]}))
    (root / "steps" / f"{name}.json").write_text(json.dumps({"name": name, "charts": {"sp": {"hard": {"notes": [level]}}}}))
    (root / "jackets" / f"{name}.png").write_bytes(name.encode())
    (root / "jackets-160" / f"{name}.png").write_bytes(name.encode())


class ReleaseFlow(unittest.TestCase):
    def test_release_and_rollback(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            sh(t, "git", "init", "-q", "--bare", "-b", "master", "remote.git")
            sh(t, "git", "clone", "-q", "remote.git", "content")
            content, build = t / "content", t / "build"
            song(content, "A", 10)
            (content / "release.json").write_text("{}")
            sh(content, "git", "add", "-A")
            sh(content, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
            sh(content, "git", "push", "-q", "origin", "master", "master:staging")
            song(build, "A", 11)
            song(build, "B", 12)

            ids = iter(["id-1", "id-1", "id-2", "id-2"])
            live = {"id": "id-0"}

            def fetch(url, timeout=15):
                return {"id": next(ids)} if "staging" in url else live

            real_run = util.run
            with mock.patch.multiple(paths, CONTENT=content, BUILD=build, LOG=t / "log"), \
                    mock.patch.object(util, "fetch_json", fetch), \
                    mock.patch.object(release, "_app_master", lambda: "a" * 40), \
                    mock.patch.object(release, "_prep_commit", lambda: "p" * 40), \
                    mock.patch.object(release, "ci_run", lambda b, s: {"status": "completed", "conclusion": "success", "url": ""}), \
                    mock.patch.object(util, "run", lambda cmd, **k: "" if cmd[0] == "gh" else real_run(cmd, **k)), \
                    mock.patch.dict("os.environ", {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
                d = release.draft(["A", "B"], [], "B and an A fix")
                self.assertEqual(d["record"]["songs"], {"added": ["B"], "changed": ["A"], "removed": []})
                self.assertIn("SP hard level 10 → 11", d["changes"][0]["changes"])
                with self.assertRaises(util.Refused):
                    release.stage()  # not checked yet
                self.assertTrue(release.checks()["ok"], release.last_checks(d["commit"]))
                release.stage()
                release.sign_off("played it")
                first = release.history()[0]
                self.assertEqual((first["expected_id"], first["tested"]["note"]), ("id-1", "played it"))
                self.assertEqual(release.content_hash("origin/master"), first["content_hash"])

                live = {"id": "id-1"}
                song(build, "A", 12)
                release.draft(["A"], [], "Another A fix", kind="fix")
                release.checks()
                release.stage()
                release.sign_off("played it again")

                rb = release.rollback(first["commit"])
                self.assertEqual(rb["record"]["expected_id"], "id-1")
                self.assertEqual(rb["record"]["removes"], [])
                self.assertTrue(release.checks()["ok"])
                release.promote_rollback("roll back")
                self.assertEqual(release.content_hash("origin/master"), first["content_hash"])
                self.assertEqual(json.loads((content / "songs" / "A.json").read_text())["sp"]["hard"], 11)
                self.assertEqual([c.name for c in diff.compare(content, build)], ["A"])


if __name__ == "__main__":
    unittest.main()
