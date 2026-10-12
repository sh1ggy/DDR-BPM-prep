"""
Arcade time-signature stage (`make arcade_timesigs`, run after `make parse`).

Fan simfiles almost never carry time signatures (.sm can't store them), so
every song parses as 4/4 from beat 0. The cabinet charts do: a list of
(beat, beats per bar) entries over a quarter note. Only the guideline uses it
(measure lines every bar, beat lines stepped from each entry), but on ~60
songs that moves the measure lines, and on a dozen it shifts the beat lines
off the notes' beats too.

Reads each matched song's .ssq from the arcade dump in data/arcade/ (same
discovery and title matching as arcade_sync.py) and merges a top-level
"time_signatures" list into its song JSON, only when it isn't plain 4/4 from
beat 0:

    "time_signatures": [{"beat": 0.0, "beats": 4}, {"beat": 208.0, "beats": 1}, ...]

Beats are the chart's own (cabinet and simfile beat 0 coincide). An entry
governs until the next one; the first also governs any beats before it. Cheap
(no audio), so it isn't cached. Pass song names to restrict the run; without
data/arcade/ contents the stage is a no-op.
"""

import env
import utils
from arcade_sync import findRip, findSsq, loadArcadeIndex, matchBasename

import struct
import sys

# .ssq chunk stream: u32 length (incl. header), u16 type, u16 param, u32 count.
# Type 2 holds chart events: i32 position[count] (1024 per beat) then
# u16 event[count]; low byte 1 is a time signature with beats per bar in the
# high byte.
EVENTS_CHUNK = 2
TIME_SIGNATURE = 1
TICKS_PER_BEAT = 1024


def readTimeSignatures(ssq_path) -> list[dict]:
    data = ssq_path.read_bytes()
    pos = 0
    while pos + 12 <= len(data):
        (length,) = struct.unpack_from("<I", data, pos)
        if length == 0:
            break
        ctype, _param, count = struct.unpack_from("<HHI", data, pos + 4)
        if ctype == EVENTS_CHUNK:
            positions = struct.unpack_from(f"<{count}i", data, pos + 12)
            events = struct.unpack_from(f"<{count}H", data, pos + 12 + 4 * count)
            return [
                {"beat": p / TICKS_PER_BEAT, "beats": e >> 8}
                for p, e in zip(positions, events)
                if e & 0xFF == TIME_SIGNATURE
            ]
        pos += length
    return []


def main():
    rip = findRip()
    if rip is None:
        print(f"No arcade data found under {env.arcade_dir}; skipping arcade time signatures")
        return
    musicdb_path, ssq_dir, _xwb_dir = rip
    exact, normalized = loadArcadeIndex(musicdb_path)

    song_paths = sorted(env.build_songs_dir.glob("*.json"))
    only = set(sys.argv[1:])
    if only:
        song_paths = [p for p in song_paths if p.stem in only]

    merged = []
    for song_path in song_paths:
        song = utils.readJson(str(song_path))
        basename = matchBasename(song, exact, normalized)
        ssq_path = findSsq(basename, ssq_dir) if basename else None
        sigs = readTimeSignatures(ssq_path) if ssq_path else []
        plain = sigs == [] or sigs == [{"beat": 0.0, "beats": 4}]
        if plain:
            if song.pop("time_signatures", None) is not None:
                utils.writeJson(song, str(song_path))
            continue
        song["time_signatures"] = sigs
        utils.writeJson(song, str(song_path))
        merged.append(song_path.stem)

    print(f"Time signatures merged for {len(merged)}/{len(song_paths)} songs (the rest are 4/4 or unmatched)")
    env.logger.info(f"arcade time signatures: {merged}")


if __name__ == "__main__":
    main()
