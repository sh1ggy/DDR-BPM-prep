"""
Extract chart-preview noteskin sprites from a DDR World arcade dump.

Reads the game's own arrow textures (`data/arc/2d/2d_arrow0N.arc`) out of the
dump under `data/arcade/` (the same place `arcade_sync` looks), decompresses and
decodes them, cuts the atlas into the few frames the app renderer needs, and
writes PNGs into `build/noteskin/`.

Atlas layout (verified against DDR World `2d_arrow00`): each sheet is 768x192,
a grid of 96x96 cells. All sheets share one green palette (DDR colours arrows by
direction in-game, not by note quantisation), and cell (0,0) is a colourless
GREY arrow — ideal to tint per-quantisation in the app. So one sheet is enough:

    (col 0, row 0) -> grey note base   -> note.png    (tinted in app)
    (col 4, row 0) -> hold body tile   -> hold_body.png
    (col 0, row 1) -> hold tail cap    -> hold_tail.png

The arrow points LEFT; the app rotates it per lane, matching the game/StepMania.

These are copyrighted Konami assets: they are written to build/ (git-ignored)
and must be copied into the app's git-ignored assets/noteskin/ by hand. Nothing
is committed. Without a dump this script is a polite no-op.
"""

import os
from pathlib import Path

import env
from classes.ArcExtractor import read_arc, dds_to_rgba, write_png, crop

CELL = 96
SHEET_W = 768


def findArrowArc() -> Path | None:
    """Locate 2d_arrow00.arc anywhere under the arcade dump (symlink-safe)."""
    for parent, _dirs, files in os.walk(env.arcade_dir, followlinks=True):
        if "2d_arrow00.arc" in files and Path(parent).name == "2d":
            return Path(parent) / "2d_arrow00.arc"
    return None


def findShockArc() -> Path | None:
    """Locate the shock-arrow IFS `.arc` (its lightning texture) in the dump."""
    for parent, _dirs, files in os.walk(env.arcade_dir, followlinks=True):
        for f in files:
            if f.startswith("dance_shock_arrow") and f.endswith(".arc"):
                return Path(parent) / f
    return None


def extractShock(out_dir: Path) -> None:
    """Dump the game's own shock-arrow lightning texture, if the dump has it.

    Best-effort: the app renders a vector lightning shock, so this is optional
    reference art. The largest `dash_thunder` frame is the clean full-row bolt.
    """
    from classes.ArcExtractor import read_arc, read_ifs_textures

    arc = findShockArc()
    if arc is None:
        return
    try:
        _name, payload = read_arc(arc)
        biggest = None
        for name, w, h, rgba in read_ifs_textures(payload):
            if biggest is None or w * h > biggest[1] * biggest[2]:
                biggest = (name, w, h, rgba)
        if biggest is not None:
            _n, w, h, rgba = biggest
            write_png(w, h, rgba, out_dir / "shock_lightning.png")
            env.logger.info(f"noteskin: wrote shock_lightning.png ({w}x{h})")
    except Exception as e:  # noqa: BLE001 - reference art, never fatal
        env.logger.warning(f"noteskin: shock extraction failed: {e}")


def main() -> None:
    if not env.arcade_dir.exists():
        print(f"No arcade dir at {env.arcade_dir}; skipping noteskin extraction")
        return

    arc = findArrowArc()
    if arc is None:
        print(f"No 2d_arrow00.arc under {env.arcade_dir}; skipping noteskin extraction")
        return

    name, payload = read_arc(arc)
    env.logger.info(f"noteskin: read {arc} ({name})")
    width, height, rgba = dds_to_rgba(payload)
    if (width, height) != (SHEET_W, 192):
        env.logger.warning(
            f"noteskin: unexpected atlas size {width}x{height}; frame cuts may be off"
        )

    out_dir = env.build_dir / "noteskin"
    out_dir.mkdir(exist_ok=True)

    # The app tints the grey note (cell 0,0) for taps AND freeze heads, tiles
    # the green body (cell 4,0) for the sustain, and can optionally use the
    # atlas freeze cap at (0,1) for an exact tail-end marker.
    frames = {
        "note.png": (0 * CELL, 0 * CELL),  # grey base, tinted in app
        "hold_body.png": (4 * CELL, 0 * CELL),  # tiled freeze body
        "hold_tail.png": (0 * CELL, 1 * CELL),  # atlas freeze tail/end cap
    }
    for fname, (sx, sy) in frames.items():
        cell = crop(rgba, width, sx, sy, CELL, CELL)
        write_png(CELL, CELL, cell, out_dir / fname)
        env.logger.info(f"noteskin: wrote {fname}")

    extractShock(out_dir)

    print(f"Noteskin sprites written to {out_dir}")
    print("Copy them into the app's assets/noteskin/ (git-ignored) to enable the")
    print("sprite noteskin; the app falls back to the vector skin without them.")


if __name__ == "__main__":
    main()
