"""
Arcade sync-bias stage (`make arcade_sync`, run after `make parse`).

Unlike the simfile sync stage (sync_songs.py), which measures how well the
*fan-made* simfile is synced, this stage fingerprints the game's own assets —
.ssq chart timing against .xwb audio from an arcade data dump — so the result
is the sync a player actually feels on the cabinet.

Prerequisite: paste the game data into data/arcade/ (any layout containing
gamedata/musicdb.xml, mdb_apx/ssq/ and sound/win/dance/; dropping the whole
`data` folder of the dump in there works). Songs are matched to build/songs/
by title via musicdb.xml. The result is merged into each song's JSON as a
top-level "arcade_sync" block (arcade timing is never per-chart).

Analysis is cached in build/arcade_sync/<basename>.json like the simfile
stage; set FORCE=Y to recompute. Pass song names as arguments to restrict
the run. Without data/arcade/ contents the stage is a no-op.
"""

import env
import utils
from classes.ArcadeSyncAnalyzer import ArcadeSyncAnalyzer

import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path


def findRip():
    # os.walk instead of rglob so a symlinked dump also works
    matches = [
        Path(parent) / "musicdb.xml"
        for parent, _dirs, files in os.walk(env.arcade_dir, followlinks=True)
        if Path(parent).name == "gamedata" and "musicdb.xml" in files
    ]
    if not matches:
        return None
    if len(matches) > 1:
        env.logger.error(f"multiple musicdb.xml under {env.arcade_dir}: {matches}")
        raise RuntimeError
    root = matches[0].parent.parent
    ssq_dir = root / "mdb_apx" / "ssq"
    xwb_dir = root / "sound" / "win" / "dance"
    for folder in (ssq_dir, xwb_dir):
        if not folder.is_dir():
            env.logger.error(f"arcade data incomplete: missing {folder}")
            raise RuntimeError
    return matches[0], ssq_dir, xwb_dir


def normTitle(title: str) -> str:
    decomposed = unicodedata.normalize("NFKD", title)
    return re.sub(r"[^a-z0-9]", "", decomposed.lower())


def loadArcadeIndex(musicdb_path) -> tuple[dict, dict]:
    # title -> basename, exact and normalized (normalized collisions such as
    # "TRUE♥LOVE" vs a hypothetical "TRUE LOVE" resolve via the exact map).
    # title_yomi also feeds the normalized map: for decorated titles it holds
    # the plain reading (e.g. "CANDY♡" has yomi "candyheart").
    exact = {}
    normalized = {}
    for music in ET.parse(musicdb_path).iter("music"):
        title = music.findtext("title")
        basename = music.findtext("basename")
        if not title or not basename:
            continue
        exact[title] = basename
        for key in {normTitle(title), normTitle(music.findtext("title_yomi") or "")}:
            if key:  # fully-Japanese text normalizes to "" — never index that
                normalized.setdefault(key, []).append(basename)
    return exact, {k: v[0] for k, v in normalized.items() if len(set(v)) == 1}


def matchBasename(song: dict, exact: dict, normalized: dict) -> str | None:
    for title in (song.get("title"), song.get("titletranslit")):
        if title and title in exact:
            return exact[title]
    for title in (song.get("title"), song.get("titletranslit"), song.get("name")):
        key = normTitle(title) if title else ""
        if key and key in normalized:
            return normalized[key]
    return None


def findSsq(basename: str, ssq_dir):
    # Usually <basename>.ssq holds the whole song's timing. A few titles only
    # ship per-chart files instead (e.g. ACE FOR ACES: acef1.ssq..acef5.ssq /
    # acef_1.ssq..); tempo is song-wide regardless of difficulty, so the
    # lowest-numbered chart's timing is as good as any other's.
    plain = ssq_dir / (basename + ".ssq")
    if plain.exists():
        return plain
    variants = sorted(ssq_dir.glob(f"{basename}[0-9].ssq")) + sorted(ssq_dir.glob(f"{basename}_[0-9].ssq"))
    return variants[0] if variants else None


def analyzeSong(basename: str, ssq_dir, xwb_dir, force: bool) -> dict | None:
    cache_path = env.build_arcade_sync_dir / (basename + ".json")
    if cache_path.exists() and not force:
        return utils.readJson(str(cache_path))

    ssq_path = findSsq(basename, ssq_dir)
    xwb_path = xwb_dir / (basename + ".xwb")
    if ssq_path is None:
        env.logger.warning(f"{basename}: no arcade file {basename}.ssq (or numbered variant)")
        return None
    if not xwb_path.exists():
        env.logger.warning(f"{basename}: no arcade file {xwb_path.name}")
        return None
    try:
        sync = ArcadeSyncAnalyzer(ssq_path, xwb_path).sync_data
    except Exception as e:
        env.logger.error(f"Arcade sync analysis failed for {basename}: {e}")
        return None
    utils.writeJson(sync, str(cache_path))
    return sync


def main():
    rip = findRip()
    if rip is None:
        print(f"No arcade data found under {env.arcade_dir}; skipping arcade sync")
        return
    musicdb_path, ssq_dir, xwb_dir = rip
    exact, normalized = loadArcadeIndex(musicdb_path)

    song_paths = sorted(env.build_songs_dir.glob("*.json"))
    only = set(sys.argv[1:])
    if only:
        song_paths = [p for p in song_paths if p.stem in only]
    force = bool(os.getenv("FORCE"))

    unmatched = []
    failed = []
    merged = 0
    for i, song_path in enumerate(song_paths):
        song = utils.readJson(str(song_path))
        basename = matchBasename(song, exact, normalized)
        if basename is None:
            env.logger.warning(f"{song_path.stem}: no arcade song matches title")
            unmatched.append(song_path.stem)
            continue

        cached = (env.build_arcade_sync_dir / (basename + ".json")).exists() and not force
        if not cached:
            print(f"[{i + 1}/{len(song_paths)}] Analyzing arcade sync for {song_path.stem} ({basename})", flush=True)
        sync = analyzeSong(basename, ssq_dir, xwb_dir, force)
        if sync is None:
            failed.append(song_path.stem)
            continue
        song["arcade_sync"] = sync
        utils.writeJson(song, str(song_path))
        merged += 1

    print(f"Arcade sync merged for {merged}/{len(song_paths)} songs")
    if unmatched:
        print(f"No arcade match ({len(unmatched)}): see log/log.txt")
    if failed:
        print(f"Failed ({len(failed)}): see log/log.txt")
        for name in failed:
            print(f"\t{name}")


if __name__ == "__main__":
    main()
