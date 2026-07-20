"""
Sync-bias analysis stage (`make sync`, run after `make parse`).

For every song in all_songs.txt, fingerprint the audio against the chart
timing (see classes/SyncAnalyzer.py) and attach the result to the song's
build/songs/<name>.json under "sync" (per_chart songs: one block per
charts[] entry instead).

Analysis is expensive (a few seconds per song), so raw results are cached
in build/sync/<name>.json and reused on later runs; the merge into
build/songs/ always happens, so re-running after `make parse` is cheap.
Set FORCE=Y to recompute. Pass song names as arguments to restrict the run.
"""

import env
import utils
from parse_simfiles import loadSongs
from classes.SyncAnalyzer import SyncAnalyzer

import os
import sys


def analyzeSong(song: dict, force: bool) -> dict | None:
    cache_path = env.build_sync_dir / (song["name"] + ".json")
    if cache_path.exists() and not force:
        return utils.readJson(str(cache_path))

    simfile_path = (
        env.seed_dir
        / song["version"]
        / song["name"]
        / (song["name"] + (".ssc" if song["ssc"] else ".sm"))
    )
    try:
        sync = SyncAnalyzer(simfile_path).sync_data
    except Exception as e:
        env.logger.error(f"Sync analysis failed for {song['name']}: {e}")
        return None
    utils.writeJson(sync, str(cache_path))
    return sync


def mergeSong(name: str, sync: dict) -> None:
    song_path = env.build_songs_dir / (name + ".json")
    if not song_path.exists():
        env.logger.warning(f"{name}: no song json to merge sync into (run `make parse` first)")
        return

    data = utils.readJson(str(song_path))
    chart_syncs = sync.get("charts")
    if data.get("per_chart") and chart_syncs:
        if len(chart_syncs) != len(data["charts"]):
            env.logger.error(
                f"{name}: {len(chart_syncs)} sync entries vs {len(data['charts'])} charts; not merging"
            )
            return
        for chart, chart_sync in zip(data["charts"], chart_syncs):
            chart["sync"] = chart_sync
    else:
        data["sync"] = sync.get("song") or (chart_syncs or [None])[0]
    utils.writeJson(data, str(song_path))


def main():
    songs = []
    loadSongs(songs)

    only = set(sys.argv[1:])
    if only:
        songs = [song for song in songs if song["name"] in only]
    force = bool(os.getenv("FORCE"))

    failed = []
    for i, song in enumerate(songs):
        cached = (env.build_sync_dir / (song["name"] + ".json")).exists() and not force
        if not cached:
            print(f"[{i + 1}/{len(songs)}] Analyzing sync for {song['name']}", flush=True)
        sync = analyzeSong(song, force)
        if sync is None:
            failed.append(song["name"])
            continue
        mergeSong(song["name"], sync)

    print(f"Sync merged for {len(songs) - len(failed)}/{len(songs)} songs")
    if failed:
        print(f"Failed ({len(failed)}): see log/log.txt")
        for name in failed:
            print(f"\t{name}")


if __name__ == "__main__":
    main()
