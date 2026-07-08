# Quickstart
## Install
Runs on Python 3.11.4 on MacOS M1.

### System dependencies
- python-tk
    ```shell
    brew install python-tk
    ```
- ICU
    - MacOS instructions
    ```shell
    # may need to install xcode to get clibs: `xcode-select --install`
    brew install pkg-config icu4c
    export PATH=/opt/homebrew/opt/icu4c/bin:$PATH
    export PATH=/opt/homebrew/opt/icu4c/sbin:$PATH
    export PKG_CONFIG_PATH=$PKG_CONFIG_PATH:/opt/homebrew/opt/icu4c/lib/pkgconfig
    ```
- ImageMagick (pre-deployment)
    ```shell
    # See https://imagemagick.org/script/download.php
    # may also need ghostscript: brew install ghostscript
    brew install imagemagick
    ```

### Python dependencies
```shell
poetry install
```

If parsing fails with `ModuleNotFoundError: No module named 'icu'`, install
PyICU into the active Poetry env:

```shell
# macOS (Homebrew ICU is required for building PyICU)
brew install pkg-config icu4c
export PATH=/opt/homebrew/opt/icu4c/bin:$PATH
export PATH=/opt/homebrew/opt/icu4c/sbin:$PATH
export PKG_CONFIG_PATH=$PKG_CONFIG_PATH:/opt/homebrew/opt/icu4c/lib/pkgconfig

# then install into Poetry env
poetry add pyicu
```

The parser now includes a fallback that keeps `make parse` working without
PyICU, but Japanese title collation quality is better with PyICU installed.

## Folder structure & Workflow
Rely on `Makefile` targets imported from `Makefiles/*.mk` for the 3 main steps of the workflow:

1. Scraper

    Scrape the DDR simfiles from ZiV and unpack them to the seed folder (`./data/`).
    Misc. fixes are applied to the simfiles at this stage to make it easier for later stages.

2. Parser

    This is the set of python scripts that does most of the heavy lifting.
    Simfiles are parsed and summarised into various formats for convenience.

3. Deploy

    This stage focuses on building the remaining artefacts and deploying them.
    At the moment, deployment just means pushing the build artefacts to GH, 
    though this may change in the future if it becomes sufficiently inconvenient.

## Run
### Scrape
```shell
make full_scrape
```
The scraper is driven by tab-separated config files in `scripts/scrape/`:
- `packs.txt` — categoryid per DDR version. Each pack's zip filename is resolved
  from the 302 `Location` header of
  `https://zenius-i-vanisher.com/v5.2/download.php?type=ddrpack&categoryid=<id>`
  and recorded in `data/downloaded.txt`; unchanged packs are skipped on re-runs.
- `songs.txt` — standalone simfileids not contained in any pack.
- `deprecated.txt` — deprecated/duplicate song-titles to delete after unpacking.

### Process and write data
```shell
make parse
```

Parser output includes a `radar` payload on each chart entry in the song JSON:

```json
{
    "charts": [
        {
            "dominant_bpm": 180,
            "bpm_range": "90~180~360",
            "bpms": [],
            "stops": [],
            "radar": {
                "stream": 61.234,
                "voltage": 47.889,
                "air": 22.101,
                "freeze": 31.004,
                "chaos": 55.762
            }
        }
    ]
}
```

`radar` values are generated during parse from the StepMania note/timing data
using formulas adapted from
https://github.com/sugoku/groove-radar-calculator (MIT).

### Load data to inspect
```shell
make load
```

### Build assets for deployment
This stages jacket assets in both full resolution and 160x160 variants.
```shell
make predeploy
```

`predeploy` resolves jacket images by exact `-jacket.png` name first, then
falls back to normalized matching (ignores punctuation/symbol differences) when
copying/downscaling. This helps keep output stable even when source jacket file
names differ slightly from song names.

Outputs:
- `build/jackets/` (full resolution, renamed to `<song>.png`)
- `build/jackets-160/` (downscaled 160x160)
- `build/jackets-full.zip` and `build/jackets.zip`

# Quality of Life
- Use `ipdb.set_trace()` for debugging.
- Use `ptpython` for a better REPL (see [official repo](https://github.com/prompt-toolkit/ptpython?tab=readme-ov-file#embedding-the-repl) on setting up a PYTHONSTARTUP).

# Improvements Ideas
