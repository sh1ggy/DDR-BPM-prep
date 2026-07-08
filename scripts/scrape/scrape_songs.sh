#!/bin/bash
# Download every standalone song listed in songs.txt (simfileid<TAB>version<TAB>title).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SONGS_FILE=${1:-$SCRIPT_DIR/songs.txt}

status=0
while IFS=$'\t' read -r id ver title
do
	case $id in ''|\#*) continue;; esac
	bash "$SCRIPT_DIR/zenius_song.sh" "$id" "$ver" || status=1
done < "$SONGS_FILE"
exit $status
