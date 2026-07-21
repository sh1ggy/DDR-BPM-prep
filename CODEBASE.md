# DDR-BPM-prep — Codebase Guide

This document explains what this project is, what every part of it does, and how the
pieces fit together. It is written for a human reading the code for the first time.

---

## 1. What this project is

**DDR-BPM-prep is a data pipeline.** It takes *simfiles* (the community file format that
describes Dance Dance Revolution songs and their step charts) from the fan site
[Zenius-I-Vanisher](https://zenius-i-vanisher.com), and turns them into clean,
compact JSON data plus jacket artwork (full-res and 160x160). The results are published as a GitHub
release, where they are consumed by a companion app (the `DDR-BPM-assets` git
submodule points at that downstream repo).

The point of all this: a DDR player wants to know a song's **BPM behaviour** — its
dominant tempo, its min/max range, where it speeds up, slows down, or stops — so they
can pick the right speed-modifier in game. Raw simfiles contain this information, but
buried in a noisy format. This pipeline extracts and summarises it.

The pipeline has **four stages**, each with its own Makefile and scripts:

```
 1. SCRAPE                 2. PARSE                    3. SYNC                     4. DEPLOY
 ─────────                 ────────                    ───────                     ─────────
 Download .zip song packs  Read every simfile,         Extract audio from the      Stage jacket art (full + 160),
 from Zenius-I-Vanisher    extract BPM/stops/levels,   zips, fingerprint it        zip everything, push a
 and unzip into ./data/    write JSON into ./build/    against chart timing,       GitHub release
 (shell scripts)           (Python)                    attach "sync" to song JSON  (shell + ImageMagick + gh)
                                                       (shell + Python)
```

---

## 2. Repository layout

```
DDR-BPM-prep/
├── Makefile                 # Entry point; wires the three stage-specific makefiles together
├── Makefiles/
│   ├── scraper.mk           # Stage 1 targets: full_scrape, scrape_packs, scrape_songs, unzip, dedupe
│   ├── parser.mk            # Stage 2 targets: parse, songs, courses, check_songs, fix, load, write
│   ├── sync.mk              # Stage 3 targets: sync, sync-force, arcade_sync, arcade_sync-force, unzip_audio, clobber_sync, clobber_arcade_sync
│   └── deploy.mk            # Stage 4 targets: predeploy, predeploy-force
├── scripts/
│   ├── scrape/              # Stage 1 shell scripts (download/unzip/dedupe)
│   ├── parse/               # fix.sh — one-off surgical fixes to broken simfiles
│   └── deploy/              # predeploy.sh (build artefacts), release.sh (GitHub release)
├── src/                     # Stage 2+3 Python code (the heart of the project)
│   ├── env.py               # Paths, directories, logging setup — imported by everything
│   ├── utils.py             # JSON I/O, song lookup, Japanese/English title sorting
│   ├── build_tools.py       # Writers: per-song JSON, summary JSON, grouped indexes
│   ├── parse_simfiles.py    # MAIN SCRIPT: songs → JSON
│   ├── parse_courses.py     # SECOND SCRIPT: course lists → JSON
│   ├── check_songs.py       # Sanity checker run before parsing
│   ├── sync_songs.py        # Stage 3 driver: audio sync analysis → "sync" in song JSON
│   ├── arcade_sync.py       # Stage 3 driver: arcade data analysis → "arcade_sync" in song JSON
│   └── classes/
│       ├── SimfileRes.py    # Locates a song's files on disk (.sm/.ssc, jacket, banner)
│       ├── SimfileParser.py # Extracts & cleans BPM/stop/level data from one simfile
│       ├── SyncAnalyzer.py  # Audio-vs-timing sync fingerprint (vendored from nine-or-null, MIT)
│       ├── ArcadeSyncAnalyzer.py # Same fingerprint, but for arcade .ssq charts + .xwb audio
│       └── BPMRange.py      # Small BPM-range helper (speed-mod tables) — mostly legacy
├── data/                    # "Seed" directory: downloaded packs + hand-maintained lists
│   ├── <VERSION>.zip        # One zip per DDR arcade release (WORLD, A3, A20 PLUS, … 1st)
│   ├── <VERSION>/<SONG>/    # Unzipped song folders (simfile + artwork + audio)
│   ├── arcade/              # Paste an arcade data dump here for `make arcade_sync` (git-ignored)
│   ├── all_songs.txt        # ★ Master list of every song currently in the game (~1,264)
│   ├── removed.txt          # Songs that used to exist but were removed from the arcade
│   ├── title_map.csv        # Title spelling overrides used only for sorting (e.g. "IX" → "9")
│   ├── dansp_courses.txt    # Dan course definitions, single-play
│   ├── dandp_courses.txt    # Dan course definitions, double-play
│   ├── ddr_courses.txt      # Official DDR in-game courses
│   └── life4_courses.txt    # LIFE4 (community ranking) courses
├── build/                   # All generated output (git-ignored)
│   ├── songs/               # One JSON file per song (full chart detail incl. sync)
│   ├── steps/               # One note-stream JSON per song (per-difficulty notes for the chart renderer / dancing bot; large, shipped & loaded separately)
│   ├── sync/                # Cached sync-analysis results (expensive; spared by clobber)
│   ├── arcade_sync/         # Cached arcade sync results, keyed by arcade basename (e.g. tlov.json)
│   ├── summaries/           # summary.json + grouped indexes (by name/version/level)
│   ├── courses/             # dan_sp.json, dan_dp.json, ddr.json, life4.json
│   ├── jackets/             # full-resolution jacket art (predeploy output)
│   ├── jackets-160/         # 160×160 downscaled jacket art (predeploy output)
│   └── *.zip                # songs.zip, jackets.zip, jackets-full.zip — release artefacts
├── log/                     # log.txt (main log), removed.txt (removal suspects)
├── pyproject.toml           # Poetry project; Python ^3.11
└── DDR-BPM-assets           # Git submodule: the downstream repo that consumes releases
```

### Quick glossary (DDR / simfile terms used throughout)

| Term | Meaning |
|---|---|
| **Simfile** (`.sm` / `.ssc`) | Text file describing a song: title, BPM changes, stops, and step charts. `.ssc` is the newer format and can define BPMs *per chart* instead of per song. |
| **Chart** | One playable difficulty of a song (e.g. "Expert Single"). |
| **SP / DP** | Single Play (one 4-panel pad) / Double Play (two pads, 8 panels). |
| **Difficulties** | Beginner, Basic/Easy, Difficult/Medium, Expert/Hard, Challenge — abbreviated in this codebase as `b, B, D, E, C`. |
| **Level / meter** | The 1–19 numeric difficulty rating of a chart. |
| **BPM range** | e.g. `74~148~296`: minimum ~ dominant ~ maximum tempo of a song. |
| **Stop** | A moment where the arrows freeze mid-song for a fixed time. |
| **Jacket / banner** | Album-art-style square image / wide banner image for a song. |
| **Dan courses (段位認定)** | Ranked 4-song gauntlets, 1st Dan through Kaiden. |
| **LIFE4** | A community-run DDR ranking system with its own course requirements. |
| **Version** | The arcade release a song debuted in (1st, 2nd, … MAX, EXTREME, SuperNOVA, X, A, A20, A3, WORLD). Doubles as the folder name in `data/`. |

---

## 3. The Makefile: how you drive everything

[Makefile](Makefile) sets four exported variables that all scripts and Python read
(`PROJ_DIR`, `SRC_DIR`, `SEED_DIR=./data`, `BUILD_DIR=./build`), then includes the
three stage makefiles. Key targets:

| Target | Stage | What it does |
|---|---|---|
| `make full_scrape` | Scrape | Download all packs → unzip → download stray songs → delete duplicates |
| `make parse` | Parse | Sanity-check the song list, then generate all song + course JSON |
| `make load` | Parse | Load the generated JSON into an interactive Python REPL for inspection |
| `make write` | Parse | Re-generate the summary files from already-built song JSON |
| `make unzip_audio` | Sync | Extract song audio (`*.ogg` etc.) from the pack zips into `data/` |
| `make sync` | Sync | `unzip_audio`, then fingerprint audio vs. chart timing and merge `sync` into song JSON (`sync-force` recomputes cached results) |
| `make arcade_sync` | Sync | Fingerprint arcade `.ssq` timing vs. `.xwb` audio from a dump in `data/arcade/` and merge `arcade_sync` into song JSON (no-op without the dump; `arcade_sync-force` recomputes) |
| `make predeploy` | Deploy | Stage full-res + 160 jackets, zip artefacts (`FORCE=Y` via `predeploy-force` to redo images) |
| `make release` | Deploy | Push `build/*.zip` + song lists as the GitHub release tagged `Latest` |
| `make main` | All | `clobber` → `parse` → `arcade_sync` → `predeploy` (the everything-after-scraping shortcut; simfile `sync` is opt-in, run it explicitly if wanted) |
| `make clean` / `make clobber` | — | Delete logs / also delete inner zips and built JSON (the `build/sync/` cache is spared; use `make clobber_sync`) |

---

## 4. Stage 1 — Scraping (`Makefiles/scraper.mk` + `scripts/scrape/`)

Everything here is plain bash + `curl` + `unzip`.

- **[zenius_pack.sh](scripts/scrape/zenius_pack.sh)** — downloads one whole "pack"
  (all simfiles for one arcade version) from Zenius-I-Vanisher. It takes the site's
  numeric `categoryid` and a version name, scrapes the category page's HTML for the
  actual zip link, and saves it as `data/<VERSION>.zip`. Uses `curl -z` so an
  existing zip is only re-downloaded if the server has a newer one.
  `scraper.mk` hard-codes the list of 20 pack IDs, from WORLD (1709) down to 1st (37).

- **[unzip_pack.sh](scripts/scrape/unzip_pack.sh)** — unzips every `data/*.zip` into a
  folder of the same name, extracting **only** `*.sm`, `*.ssc`, and `*.png` (charts and
  artwork; audio and videos are skipped). Result: `data/<VERSION>/<SONG>/<files>`.

- **[zenius_song.sh](scripts/scrape/zenius_song.sh)** — same idea but for a single
  song that isn't included in any pack (the site's `simfileid`). The two known cases
  (PARANOiA KCET ~clean mix~, LOVE THIS FEELIN') are listed in the `scrape_songs`
  target.

- **[dedupe_song.sh](scripts/scrape/dedupe_song.sh)** — simply `rm -rf`s
  `data/<version>/<song>`. Used by the `dedupe` target to delete songs that appear in
  two packs (e.g. DYNAMITE RAVE exists in both the 3rd-mix pack and a later pack;
  only one copy may remain, because the parser treats duplicates as suspicious).

After this stage, `data/` holds one folder per arcade version, each containing one
folder per song.

---

## 5. Stage 2 — Parsing (the Python in `src/`)

This is where the real work happens. Run order under `make parse`:
**fix → check_songs → parse_simfiles → parse_courses**.

### 5.0 Pre-step: [fix.sh](scripts/parse/fix.sh)

Three hand-written patches for known-broken simfiles, applied with `sed` before any
parsing:

1. **deltaMAX** — rewrites the `#BPMS` line entirely. The song ramps 100→573 BPM in
   ~490 tiny increments; the shipped file's data confuses the parser, so a corrected
   sequence is substituted (and `SimfileParser.cleanBPM` also special-cases this song
   to skip smoothing).
2. **Koi hadou…** — removes a stray `;new;` token that breaks the simfile library.
3. **take me higher** — the A20 PLUS version shares its name with an older song, so
   the folder and files are renamed to `take me higher A20P` to keep names unique.

### 5.1 Shared plumbing

- **[env.py](src/env.py)** — the single source of truth for paths. Reads `SEED_DIR`
  and `BUILD_DIR` from the environment (the Makefile sets them), creates all
  `build/` subdirectories on import, defines the paths of every seed data file, and
  configures the logger that writes to `log/log.txt`. Every other module starts with
  `import env`.

- **[utils.py](src/utils.py)** — small toolbox:
  - `readJson` / `writeJson` — trivial JSON I/O.
  - `locSong(summary, title)` — find a song by (sub)string match on a key; used both
    by course parsing and interactively in the REPL.
  - `sortSongsByTitle(songs)` — the most intricate utility: partitions all songs into
    the in-game alphabet **あかさたなはまやらわ A–Z 0–9**. Japanese titles are
    transliterated to hiragana (`unihandecode` + `romkan`) and sorted with a proper
    Japanese collator (`PyICU`); English titles are sorted A–Z/0–9. `title_map.csv`
    overrides titles that should sort as something else (e.g. Roman numeral "IX"
    sorts as "9"). This produces the `songs_name.json` index.

### 5.2 Pre-flight check: [check_songs.py](src/check_songs.py)

Validates that `data/all_songs.txt` (the hand-maintained master song list) and the
scraped folders agree, before wasting time parsing:

- Every listed song must exist as a folder **with exact case-sensitive spelling**
  (`_checkFiles`; a case-insensitive match is reported as "found in …" to help fix it).
- No song may appear twice in the list (`_checkDupesInList`).
- No song may be in *both* `all_songs.txt` and `removed.txt`, and any folder on disk
  that is in **neither** list is logged to `log/removed.txt` as a "suspected removed
  song" (`_checkRemoved`) — the usual sign that Konami removed songs from the arcade
  since the last run. Errors abort the pipeline.

### 5.3 Main event: [parse_simfiles.py](src/parse_simfiles.py)

The orchestrator. For every title in `all_songs.txt`:

1. **`loadSongs`** — locate the song's folder under `data/*/<title>` (erroring if
   missing, warning if duplicated) and wrap it in a `SimfileRes` to discover whether
   it uses `.sm` or `.ssc`. Records `{name, version, ssc}`.
2. **`addChartData`** — run `SimfileParser` on the simfile and merge its output into
   the song dict: title info, song length, per-difficulty levels, and per-chart
   BPM/stop data.
3. **Write output** — `build_tools.writeSongsToDist` writes one
   `build/songs/<name>.json` per song, and `writeSummaryToDist` writes the summary
   and index files (see §5.6).

Command-line flags (used by the make targets):
`-l` load previously built JSON instead of parsing; `-w` (with `-l`) rewrite the
summaries; `-n` parse but write nothing; `-i` drop into a `ptpython` REPL with
`songs` in scope — this is what `make load` gives you.

### 5.4 The extractor: [classes/SimfileParser.py](src/classes/SimfileParser.py)

One instance per simfile, built on the [`simfile`](https://pypi.org/project/simfile/)
library and its `TimingData`/`TimingEngine` (which convert beat positions into
wall-clock seconds). Produces four things:

- **`song_data`** — title, transliterated title, song length in seconds (computed by
  counting measures in the first chart and asking the timing engine for the time at
  the final beat), and a `per_chart` flag (true for `.ssc` files where each chart can
  carry its own BPM/stop data).
- **`levels_data`** — `{sp: {...}, dp: {...}}` mapping difficulty name → 1–19 level,
  split by `dance-single` vs `dance-double`.
- **`notecounts_data`** — same `{sp: {...}, dp: {...}}` shape mapping difficulty name →
  step count (a jump counts as one step, matching the in-game combo counter). Written
  to each song JSON as the `notecounts` attribute.
- **`chart_data`** — a list of BPM/stop descriptions. For ordinary songs all charts
  share timing, so only one entry exists; for `per_chart` songs, one entry per
  distinct difficulty (asserted to appear in Beginner→Challenge order, `"BEMHC"`).
- **`steps_data`** — the per-difficulty note stream, keyed `{sp: {<difficulty>:
  {notes: [...]}}, dp: {...}}`. Unlike `chart_data`, notes differ for every
  difficulty, so this walks *every* chart. Each note is compact
  `{"b": beat, "s": second, "c": col, "t": type}` (type `0`=tap `1`=hold `2`=roll
  `3`=mine); holds/rolls also carry `"e"`/`"es"` (tail beat + second). Written to
  its **own** `build/steps/<name>.json` by `build_tools.writeStepsToDist` — never
  folded into the per-song JSON or the merged songlist, because the app loads it
  lazily only when a chart view is opened. Feeds the app's scrolling chart
  renderer (and, later, a parity-solved dancing bot — the `feet` field is added
  downstream). Built from the `simfile` library's `time_notes`, which already
  yields wall-clock seconds; hold heads are paired with their tails per column.

The interesting logic is the cleanup, governed by the tunable constants at the top of
the file:

- **`cleanBPM`** — real simfiles are full of *false BPM bumps*: sub-2-second blips
  where the BPM wiggles by ≤3 (often sync artefacts, not gameplay). These get merged
  into their neighbour, and consecutive equal-BPM sections are coalesced. Changes of
  ≤10 BPM are logged as suspicious but kept. (deltaMAX is exempted — its whole
  gimmick is continuous BPM change.)
- **`dominantBPM`** — the BPM the player will spend most time at: total duration is
  summed per BPM value, and the longest wins, with a bias toward a *faster* BPM if it
  also plays for a substantial time (>30 s) or if no BPM is clearly dominant (<13 s).
  Players set speed mods against the dominant/fastest sustained tempo, hence the bias.
- **`parseBpm`** — assembles `bpm_range` as `"min~dominant~max"` (or a single number
  for constant-BPM songs), ignoring very short (<4.5 s) extremes when a clear
  dominant BPM exists, but also reporting the instantaneous `true_min`/`true_max`.
- **`processStop`** — converts each stop from seconds into **beats**, which is how
  players think of them ("a 2-beat stop"). Since a stop sits between two possible
  BPMs (before/after), it computes the beat value at both and picks whichever lands
  "nicely" on a multiple of ¼ or ⅓ beat (within 0.05); if neither is nice, both
  candidates are emitted.

### 5.5 File discovery: [classes/SimfileRes.py](src/classes/SimfileRes.py)

A tiny helper representing a song folder's resources. Given `data/<ver>/<song>/`, it
finds the simfile (prefers `<song>.sm`, falls back to `<song>.ssc`), the jacket
(`<song>-jacket.png`) and the banner (`<song>.png`), logging anything missing. Its
main output consumed downstream is the `ssc` boolean.

([classes/BPMRange.py](src/classes/BPMRange.py) is a leftover helper that models a
BPM range and can print speed-mod multiplication tables (0.25×–8×). Nothing imports
it currently; the equivalent logic lives in `SimfileParser`/`build_tools`.)

### 5.6 Output writers: [build_tools.py](src/build_tools.py)

- **`writeSongsToDist`** — one detailed JSON per song into `build/songs/`.
- **`summariseSong`** — boils a song down to what a list view needs:
  name, title, version, levels (with difficulty names abbreviated to
  `b/B/D/E/C`), and a song-level `bpm_range` `[min, dominant, max]` aggregated
  across charts (mode of the per-chart dominants; collapses to `[bpm]` when constant).
- **`writeSummaryToDist`** — writes to `build/summaries/`:
  - `summary.json` — every song's summary, sorted in in-game title order;
  - `songs_name.json` — songs grouped by あ–わ / A–Z / 0–9 heading (via
    `utils.sortSongsByTitle`);
  - `songs_version.json` — grouped by the 20 arcade versions;
  - `songs_level_sp.json` / `songs_level_dp.json` — grouped by level 1–19 (a song
    appears under every level it has a chart for).

  Everything is stored as arrays of `{category, songs}` rather than dicts, because
  JSON object order isn't guaranteed and the consumer needs a stable display order.

### 5.7 Courses: [parse_courses.py](src/parse_courses.py)

Parses the four hand-maintained course files in `data/`. Each file is plain text:
courses separated by blank lines, one song per line. Three formats exist:

- **Dan courses** (`dansp_courses.txt`, `dandp_courses.txt`) — four lines of
  `<difficulty letter> <song name>`. Course names aren't in the file; the script
  attaches the fixed ladder "1st Dan (初段) … Kaiden (皆伝)" by position.
- **DDR courses** (`ddr_courses.txt`) — first line is the course name, then bare song
  names (playable at any difficulty).
- **LIFE4 courses** (`life4_courses.txt`) — course name, then a numeric level, then
  `<difficulty> <song>` lines.

`fillCourseInfo` then enriches every course entry by looking the song up in the
freshly built `summary.json` (so **`parse_simfiles.py` must run first**), copying in
its display title, relevant SP/DP level(s), and BPM range. Output:
`build/courses/{dan_sp,dan_dp,ddr,life4}.json`.

---

## 6. Stage 3 — Sync analysis (`Makefiles/sync.mk` + `src/sync_songs.py`)

Measures how the song's audio lines up with the simfile's beat grid and attaches
the result to the per-song JSON, so the app can graph "song sync". Runs after
`make parse` (it merges into `build/songs/*.json`). This simfile flavour is
**opt-in** and not part of `make main`: it measures the fan pack's own sync,
which is not the app's use case (cabinet feel — see "Arcade sync" below, which
*is* in `make main`). It is kept working for when it's needed.

- **[unzip_audio.sh](scripts/scrape/unzip_audio.sh)** (`make unzip_audio`) — the
  pack zips ship each song's audio, but the regular `unzip` target deliberately
  skips it. This script extracts `*.ogg` / `*.oga` / `*.mp3` / `*.wav` into the
  same `data/<VERSION>/<SONG>/` folders. `make sync` depends on it.

- **[classes/SyncAnalyzer.py](src/classes/SyncAnalyzer.py)** — the algorithm,
  vendored from Telperion's [+9ms or Null?](https://github.com/telperion/nine-or-null)
  (MIT), minus its GUI/plots/offset-rewriting. One instance per simfile: loads
  the audio once (`pydub` → ffmpeg), then for each beat of the chart timing cuts
  a ±50 ms spectrogram window, flattens it, and stacks the rows into a "beat
  digest". A rising-edge convolution over the digest yields a response curve
  whose peak is the **sync bias**: how many ms the audio attack sits from the
  charted beat (positive = audio later than the chart, i.e. the chart feels
  early). A **confidence** metric (0–1) penalizes rivaling response far from the
  peak. For `per_chart` songs it mirrors `SimfileParser.parseCharts` (one result
  per unique difficulty, BEMHC order), reusing the analysis when charts share
  identical timing.

- **[sync_songs.py](src/sync_songs.py)** (`make sync`) — the driver. Iterates
  `all_songs.txt` (same `loadSongs` as the parser), analyzes each song, and
  merges a `sync` block into `build/songs/<name>.json` — top-level for shared
  timing, per `charts[]` entry for `per_chart` songs:

  ```json
  "sync": {
      "bias_ms": 1.3,          // peak of the response curve
      "confidence": 0.752,
      "curve_start_ms": -49,   // x of curve[0]; x_i = start + i * step
      "curve_step_ms": 1.0,
      "curve": [0, 3, "..."]   // response normalized to 0..100 ints
  }
  ```

  The curve is resampled onto a fixed 1 ms grid so consumers never see the
  audio sample rate; the app draws it as a line chart with a vertical marker at
  `bias_ms`. Analysis costs a few seconds per song (hours for the full
  catalogue), so raw results are cached in `build/sync/<name>.json`; re-runs
  only re-merge, which is why `make sync` is cheap to repeat after every
  `make parse`. `make clobber` spares the cache; `make clobber_sync` wipes it,
  `make sync-force` (or `FORCE=Y`) recomputes. Passing song names restricts the
  run: `poetry run python src/sync_songs.py "CHAOS"`. Songs whose audio is
  missing or ambiguous are logged and skipped (their JSON simply has no `sync`).

### Arcade sync (`make arcade_sync`)

The `sync` block above measures the *fan simfile's* sync — pack authors
re-sync songs for home play, so it says nothing about how a song feels on a
real cabinet. This second, optional sub-stage fingerprints the game's own
assets instead, producing the cabinet feel (validated against
[FinalOffset](https://finaloffset.telp.gg/) to within ~0.4 ms):

- **Input** — paste an arcade data dump into `data/arcade/` (git-ignored;
  a symlink works too). Any layout containing `gamedata/musicdb.xml`,
  `mdb_apx/ssq/` and `sound/win/dance/` is auto-discovered, so dropping the
  dump's whole `data` folder in there is enough. Without it the stage is a
  polite no-op, so `make main` works with or without the dump.

- **[classes/ArcadeSyncAnalyzer.py](src/classes/ArcadeSyncAnalyzer.py)** —
  shares the fingerprint core with `SyncAnalyzer` (both subclass its
  `Fingerprinter`: audio samples + an iterable of beat timestamps → sync
  block). Timing comes from the `.ssq` tempo chunk (measure-tick →
  timekeeper-tick breakpoints, linearly interpolated per beat); audio comes
  from the `.xwb` XACT wave bank — the longest entry (full song, not the
  song-wheel preview) is wrapped in an MS-ADPCM WAV header and piped through
  ffmpeg. No temp files, no resampling, so no constant shift sneaks in.

- **[arcade_sync.py](src/arcade_sync.py)** — the driver. Matches every
  `build/songs/*.json` to an arcade basename via `musicdb.xml` titles (exact
  title first, then a normalized fallback that ignores case/symbols when
  unambiguous), analyzes, and merges a top-level `arcade_sync` block with the
  same shape as `sync` (arcade timing is song-wide, never per-chart). Cached
  in `build/arcade_sync/<basename>.json`; same `FORCE=Y` / song-name-args /
  `clobber_arcade_sync` conventions as the simfile stage. Songs missing from
  the dump (removed licenses, old-version-only songs) are logged and simply
  keep only their simfile `sync`.

---

## 7. Stage 4 — Deploy (`Makefiles/deploy.mk` + `scripts/deploy/`)

- **[predeploy.sh](scripts/deploy/predeploy.sh)** — builds the release artefacts:
  1. For every song in `all_songs.txt`, find its `-jacket.png` in `data/`, copy it to
    `build/jackets/` (full resolution), and use ImageMagick `convert` to create a
    160×160 version in `build/jackets-160/` (skipping ones already done unless
    `FORCE=Y`, i.e. `make predeploy-force`). A missing or ambiguous jacket aborts
    the run.
  2. Zip `build/songs/` → `build/songs.zip`, `build/jackets-160/` → `build/jackets.zip`,
    and `build/jackets/` → `build/jackets-full.zip` (7z).
  3. Copy `all_songs.txt` and `removed.txt` into `build/` so they ship with the release.

- **[release.sh](scripts/deploy/release.sh)** (`make release`) — after an interactive
  y/n confirmation, deletes the existing GitHub release tagged `Latest` and creates a
  fresh one (via `gh`) containing `build/*.txt` and `build/*.zip`. The downstream
  app always fetches "Latest", so the tag is recycled rather than versioned.

---

## 8. The seed data files (hand-maintained inputs)

These files in `data/` are the human-curated half of the pipeline — the code trusts
them, and `check_songs.py` exists to keep them honest:

| File | Role |
|---|---|
| `all_songs.txt` | One song-folder name per line; the definitive "what's in the game right now" list (~1,264 songs). Parsing iterates over this, not over the folders, so a song only ships if it's listed here. Must end with a newline. |
| `removed.txt` | Songs deliberately absent from `all_songs.txt`. Suppresses "suspected removed" noise and ships with the release so the app can hide them. |
| `title_map.csv` | `old,new` sorting overrides (full-width text, Roman numerals, decorated titles → sortable spellings). Only affects `songs_name.json` ordering. |
| `*_courses.txt` | Course definitions described in §5.7. |

---

## 9. How a change typically flows (worked example)

Konami releases a new song, or removes some:

1. `make full_scrape` — refresh the packs from Zenius-I-Vanisher.
2. Edit `data/all_songs.txt` (add new songs) and `data/removed.txt` (move removed
   ones). `log/removed.txt` from the next step tells you what changed.
3. `make parse` — fix.sh patches known-bad files, `check_songs.py` validates your
   edits, then the song and course JSON are rebuilt into `build/`.
4. `make load` — optional: poke at the `songs` list in a REPL to spot-check a song
   (`locSong(summary, "paranoia")`).
5. `make sync` — extract audio for any new songs and merge sync-bias data back
   into the freshly parsed song JSON (cached songs are instant; only new songs
   get analyzed).
6. `make predeploy` — stage any new full-res/160 jackets, rebuild the zips.
7. `make release` — replace the `Latest` GitHub release; the DDR-BPM app picks it up.

---

## 10. Odds and ends

- **Logging** — everything logs to `log/log.txt` (fresh each run, INFO level);
  removal suspects go to `log/removed.txt`. When something fails, look there first —
  the code often raises a bare `RuntimeError` and expects the log to explain why.
- **Python setup** — Poetry-managed, Python ≥ 3.11. The heavyweight dependencies are
  `simfile` (parsing), `PyICU` (Japanese collation — needs the system ICU libraries,
  see the README's install notes), `unihandecode` + `romkan` (kanji → hiragana), and
  `ptpython`/`ipdb` for the interactive workflow.
- **`data/` is mostly git-ignored** — the zips and unzipped song folders are scraped
  artefacts; only the hand-maintained text files are tracked.
- **`DDR-BPM-assets` submodule** — declared in `.gitmodules`; the consumer repo for
  the released artefacts. It is not needed to run the pipeline itself.
