#!/bin/bash
# Download every pack listed in packs.txt (categoryid<TAB>version).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PACKS_FILE=${1:-$SCRIPT_DIR/packs.txt}

status=0
while IFS=$'\t' read -r id ver
do
	case $id in ''|\#*) continue;; esac
	bash "$SCRIPT_DIR/zenius_pack.sh" "$id" "$ver" || status=1
done < "$PACKS_FILE"
exit $status
