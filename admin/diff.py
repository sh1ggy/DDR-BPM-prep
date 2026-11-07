"""
What a set of song files changes for players, in chart terms: new and removed
songs, levels, note counts, BPM, charts, jackets, and data a song gained or
lost (arcade sync, scoring tiers, Konami ID...).

Both sides are directories laid out like the content repo (songs/, steps/,
jackets/, jackets-160/): prep's build/ and the content checkout both are.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

# Optional data a song carries. Losing one is a regression the release view
# shows as a warning: a parse rewrites song JSON without them.
OPTIONAL = ("konami_id", "sync", "arcade_sync", "time_signatures", "scoring_tiers")
# Fields compared one by one below; everything else is compared as a whole.
SHOWN = {"title", "artist", "version", "sp", "dp", "notecounts", "charts", "song_length", *OPTIONAL}
# Prep leaves these in song JSON; the songlist drops them and the app never reads them.
IGNORED = {"pattern_analysis"}


@dataclass
class SongChange:
    name: str
    status: str  # new | changed | removed | same
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self):
        return self.__dict__


def files(root: Path, name: str) -> dict[str, Path]:
    return {k: root / k / f"{name}{ext}" for k, ext in paths.KINDS.items()}


def names(root: Path) -> set[str]:
    return {p.stem for p in (root / "songs").glob("*.json")}


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def _levels(old: dict, new: dict, out: list[str]):
    for mode in ("sp", "dp"):
        a, b = old.get(mode) or {}, new.get(mode) or {}
        for d in [*a, *(k for k in b if k not in a)]:
            if a.get(d) != b.get(d):
                out.append(f"{mode.upper()} {d} level {a.get(d, 'none')} → {b.get(d, 'none')}")
        na, nb = (old.get("notecounts") or {}).get(mode) or {}, (new.get("notecounts") or {}).get(mode) or {}
        for d in [*na, *(k for k in nb if k not in na)]:
            if na.get(d) != nb.get(d):
                out.append(f"{mode.upper()} {d} notes {na.get(d, 'none')} → {nb.get(d, 'none')}")


def _bpm(song: dict):
    return [c.get("bpm_range") for c in song.get("charts") or []]


def _charts_core(song: dict):
    """Chart timing without the optional blocks, so lost sync shows as lost sync."""
    return [{k: v for k, v in c.items() if k not in OPTIONAL} for c in song.get("charts") or []]


def _steps_changes(old: dict, new: dict, out: list[str]):
    a, b = (old or {}).get("charts") or {}, (new or {}).get("charts") or {}
    for mode in ("sp", "dp"):
        ca, cb = a.get(mode) or {}, b.get(mode) or {}
        for d in [*ca, *(k for k in cb if k not in ca)]:
            if ca.get(d) != cb.get(d):
                out.append(f"{mode.upper()} {d} chart notes changed")


def song_change(name: str, old_root: Path, new_root: Path) -> SongChange:
    fo, fn = files(old_root, name), files(new_root, name)
    old, new = _json(fo["songs"]), _json(fn["songs"])
    if new is None:
        return SongChange(name, "removed", ["Removed from the app"],
                          ["Players' scores, notes and footing edits on it are orphaned"])
    c = SongChange(name, "new" if old is None else "same")
    old = old or {}
    for k in ("steps", "jackets", "jackets-160"):
        if not fn[k].exists():
            c.warnings.append(f"No {k} file")
    if old:
        for k in ("title", "artist", "version"):
            if old.get(k) != new.get(k):
                c.changes.append(f"{k.capitalize()} {old.get(k)!r} → {new.get(k)!r}")
        _levels(old, new, c.changes)
        if _bpm(old) != _bpm(new):
            c.changes.append(f"BPM {' / '.join(map(str, _bpm(old)))} → {' / '.join(map(str, _bpm(new)))}")
        elif _charts_core(old) != _charts_core(new):
            c.changes.append("BPM changes or stops moved")
        if old.get("song_length") != new.get("song_length"):
            c.changes.append(f"Length {old.get('song_length')}s → {new.get('song_length')}s")
        _steps_changes(_json(fo["steps"]), _json(fn["steps"]), c.changes)
        for k in ("jackets", "jackets-160"):
            if _sha(fo[k]) != _sha(fn[k]) and fn[k].exists():
                c.changes.append("Jacket changed" if k == "jackets" else "Thumbnail changed")
        for k in OPTIONAL:
            if (k in old) != (k in new):
                (c.warnings if k in old else c.changes).append(
                    f"{'Loses' if k in old else 'Gains'} {k.replace('_', ' ')}")
            elif k in old and old[k] != new[k] and k != "konami_id":
                c.changes.append(f"{k.replace('_', ' ').capitalize()} recalculated")
        if old.get("konami_id") and new.get("konami_id") and old["konami_id"] != new["konami_id"]:
            c.warnings.append("Konami ID changed: synced scores move to another song")
        other = sorted(k for k in (old.keys() | new.keys()) - SHOWN - IGNORED if old.get(k) != new.get(k))
        if other:
            c.changes.append(f"Also changed: {', '.join(other)}")
        if c.changes or c.warnings:
            c.status = "changed"
    else:
        c.changes.append(f"New song · {new.get('version')} · {_count(new)} charts")
        for k in ("konami_id", "arcade_sync"):
            if k not in new:
                c.warnings.append(f"No {k.replace('_', ' ')}")
    if new.get("name") != name:
        c.warnings.append(f"Song JSON names itself {new.get('name')!r}")
    return c


def _count(song: dict) -> int:
    return sum(1 for m in ("sp", "dp") for v in (song.get(m) or {}).values() if v)


def compare(old_root: Path, new_root: Path, only: set[str] | None = None) -> list[SongChange]:
    """Every song that differs between the two roots (or the ones in only)."""
    candidates = only if only is not None else names(old_root) | names(new_root)
    out = []
    for name in sorted(candidates):
        c = song_change(name, old_root, new_root)
        if c.status != "same":
            out.append(c)
    return out


def summary(changes: list[SongChange]) -> str:
    n = {s: sum(1 for c in changes if c.status == s) for s in ("new", "changed", "removed")}
    parts = [f"{v} {k}" for k, v in n.items() if v]
    return ", ".join(parts) or "No song changes"
