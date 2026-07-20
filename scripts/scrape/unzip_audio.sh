#!/bin/bash
# Extract song audio from the scraped zips (skipped by unzip_pack.sh) so the
# sync-bias stage can fingerprint it. Exit 11 = a zip with no audio entries.
SEED_DIR=${SEED_DIR:-./data}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

for f in $SEED_DIR/*.zip; do
    unzip -uo "$f" "*.ogg" "*.oga" "*.mp3" "*.wav" -d "$(echo $f | sed -e 's/\.zip//')" || [[ $? -eq 1 || $? -eq 9 || $? -eq 11 ]];
done

# Standalone song zips (scrape_songs) live inside the version folders.
for f in $SEED_DIR/*/*.zip; do
    unzip -uo "$f" "*.ogg" "*.oga" "*.mp3" "*.wav" -d "$(dirname "$f")" || [[ $? -eq 1 || $? -eq 9 || $? -eq 11 ]];
done

# Extraction resurrects deduped song folders as audio-only shells that would
# shadow the real folder during parsing; delete them again.
bash "$SCRIPT_DIR/dedupe_songs.sh"

# fix.sh renames this folder during parse; re-home its audio after extraction.
if [[ -d "$SEED_DIR/A20 PLUS/take me higher A20P" \
   && -f "$SEED_DIR/A20 PLUS/take me higher/take me higher.ogg" \
   && ! -f "$SEED_DIR/A20 PLUS/take me higher/take me higher.sm" ]]; then
    mv -v "$SEED_DIR/A20 PLUS/take me higher/take me higher.ogg" "$SEED_DIR/A20 PLUS/take me higher A20P/take me higher A20P.ogg"
    rm -rf "$SEED_DIR/A20 PLUS/take me higher"
fi
