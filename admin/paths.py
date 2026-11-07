"""Where everything lives. DDR_MD_DIR and CONTENT_DIR override the defaults."""

import os
from pathlib import Path

PREP = Path(__file__).resolve().parent.parent
DDR_MD = Path(os.getenv("DDR_MD_DIR") or PREP.parent).resolve()
CONTENT = Path(os.getenv("CONTENT_DIR") or Path.home() / "repos" / "ddr-md-content")
BUILD = PREP / "build"
DATA = PREP / "data"
LOG = PREP / "log" / "admin"

CONTENT_REPO = "sh1ggy/ddr-md-content"
APP_REPO = "sh1ggy/ddr-md"
LIVE_URL = "https://ddr-md-content.pages.dev"
STAGING_URL = "https://staging.ddr-md-content.pages.dev"

# The four things a song publishes, as directory -> extension. Everything
# else the app downloads is derived from these by CI.
KINDS = {"songs": ".json", "steps": ".json", "jackets": ".png", "jackets-160": ".png"}

# Seed files edited through the console: name -> path under PREP.
SEEDS = {
    "removed": "data/removed.txt",
    "title_map": "data/title_map.csv",
    "packs": "scripts/scrape/packs.txt",
    "songs": "scripts/scrape/songs.txt",
    "deprecated": "scripts/scrape/deprecated.txt",
    "chart_patches": "scripts/parse/fix.sh",
    "courses_dan_sp": "data/dansp_courses.txt",
    "courses_dan_dp": "data/dandp_courses.txt",
    "courses_ddr": "data/ddr_courses.txt",
    "courses_life4": "data/life4_courses.txt",
}
