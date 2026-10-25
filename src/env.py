from pathlib import Path
from os import getenv
import logging


build_dir = Path(getenv("BUILD_DIR") or "./build")
build_courses_dir = build_dir / "courses"
build_jackets_dir = build_dir / "jackets"
build_simfiles_dir = build_dir / "simfiles"
build_songs_dir = build_dir / "songs"
build_steps_dir = build_dir / "steps"
build_summaries_dir = build_dir / "summaries"
build_sync_dir = build_dir / "sync"
build_arcade_sync_dir = build_dir / "arcade_sync"
for folder in [
    build_dir,
    build_courses_dir,
    build_jackets_dir,
    build_songs_dir,
    build_steps_dir,
    build_simfiles_dir,
    build_summaries_dir,
    build_sync_dir,
    build_arcade_sync_dir,
]:
    if not folder.exists():
        folder.mkdir()

seed_dir = Path(getenv("SEED_DIR") or "./data")
arcade_dir = seed_dir / "arcade"
removed_file = str(seed_dir / "removed.txt")
title_map_file = str(seed_dir / "title_map.csv")
konami_file = str(seed_dir / "konami.tsv")
dansp_courses_file = str(seed_dir / "dansp_courses.txt")
dandp_courses_file = str(seed_dir / "dandp_courses.txt")
ddr_courses_file = str(seed_dir / "ddr_courses.txt")
life4_courses_file = str(seed_dir / "life4_courses.txt")


def song_folders() -> list[Path]:
    """
    Every scraped song: each <version>/<song> folder holding a simfile, minus
    the names in removed.txt. A name scraped under two versions is an error.
    """
    with open(removed_file, "r") as file:
        removed = {line.strip() for line in file if line.strip()}
    folders: dict[str, Path] = {}
    for folder in sorted(seed_dir.glob("*/*")):
        if folder.name in removed or not (
            any(folder.glob("*.sm")) or any(folder.glob("*.ssc"))
        ):
            continue
        if folder.name in folders:
            raise RuntimeError(f"{folder.name} in both {folders[folder.name]} and {folder}")
        folders[folder.name] = folder
    return [folders[name] for name in sorted(folders)]


log_folder = Path("./log")


def logfile(fname: str = "log.txt") -> str:
    return str(log_folder / fname)


logging.basicConfig(
    filename=logfile(),
    filemode="w",
    format="[%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
