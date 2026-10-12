#!/bin/bash
# Download a DDR pack from ZiV by categoryid.
# The pack zip filename is unique per pack revision (e.g. pack_1509_3038f1.zip),
# so we resolve it from the 302 Location header and skip the download when the
# manifest already records it.
SEED_DIR=${SEED_DIR:-./data}
MANIFEST=$SEED_DIR/downloaded.txt
tab=$'\t'

if  [ $# -ne 2 ]
then
	echo "Input the pack id (contained in the URL as the categoryid, example : https://zenius-i-vanisher.com/v5.2/viewsimfilecategory.php?categoryid=34) and the version (folder name)";
    exit 1;
else
	id=$1;
	ver=$2;
fi

mkdir -p "$SEED_DIR"
touch "$MANIFEST"

uri="https://zenius-i-vanisher.com/v5.2/download.php?type=ddrpack&categoryid=$id"
redirect=$(curl -s -o /dev/null -w '%{redirect_url}' "$uri")
pack=$(basename "$redirect")

case $pack in
	pack_*.zip) ;;
	*)
		echo "$ver (categoryid=$id): expected a pack zip redirect, got '$redirect'" >&2
		exit 1;;
esac

entry="$ver$tab$pack"
if grep -qxF "$entry" "$MANIFEST" && [ -e "$SEED_DIR/$ver.zip" ]
then
	echo "$ver: $pack already downloaded, skipping"
	exit 0
fi

echo "$ver: downloading $pack"
curl -L "$redirect" -o "$SEED_DIR/$ver.zip" || exit 1

{ grep -vF "$ver$tab" "$MANIFEST" || [ $? -eq 1 ]; printf '%s\n' "$entry"; } > "$MANIFEST.tmp"
mv "$MANIFEST.tmp" "$MANIFEST"
