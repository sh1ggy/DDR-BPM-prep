#!/bin/bash
# Delete every deprecated song copy listed in deprecated.txt (song-title<TAB>version).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
DEPRECATED_FILE=${1:-$SCRIPT_DIR/deprecated.txt}

while IFS=$'\t' read -r title ver
do
	case $title in ''|\#*) continue;; esac
	bash "$SCRIPT_DIR/dedupe_song.sh" "$title" "$ver"
done < "$DEPRECATED_FILE"
