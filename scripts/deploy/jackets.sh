#!/bin/bash
# Stage each parsed song's jacket as build/jackets/<name>.png (full
# resolution) and build/jackets-160/<name>.png (160x160), the two the content
# repo publishes. Existing ones are kept unless FORCE is set.
SEED_DIR=${SEED_DIR:-./data}
BUILD_DIR=${BUILD_DIR:-./build}

normalize_name() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+//g'
}

jackets_full_dir=$BUILD_DIR/jackets
jackets_160_dir=$BUILD_DIR/jackets-160
mkdir -p $jackets_full_dir
mkdir -p $jackets_160_dir

OIFS="$IFS"
IFS=$'\n'

# Build a normalized index of source jacket paths once to support fuzzy lookup
# (e.g. punctuation/symbol variants).
jacket_index=$(mktemp)
while IFS= read -r p; do
    b=$(basename "$p" "-jacket.png")
    n=$(normalize_name "$b")
    echo "$n|$p" >> "$jacket_index"
done < <(find "$SEED_DIR" -type f -name "*-jacket.png")

while IFS= read -r name; do
    [[ -f "$jackets_full_dir/$name.png" && -f "$jackets_160_dir/$name.png" && -z $FORCE ]] && continue

    search_name=$(echo $name | sed -e 's:\[:\\[:g' -e 's:]:\\]:g') # escape square brackets
    png=$(find $SEED_DIR -type f -name "$search_name-jacket.png")

    if [[ -z $png ]]; then
        norm=$(normalize_name "$name")
        matches=$(grep -E "^${norm}\|" "$jacket_index" | cut -d'|' -f2-)
        if [[ -n $matches ]]; then
            # Keep deterministic behaviour if multiple matches are present.
            png=$(echo "$matches" | sort | head -n 1)
            if [[ $(echo "$matches" | wc -l) -gt 1 ]]; then
                printf "Multiple normalized jacket matches for %s; selected:\n\t%s\n" "$name" "$png"
            fi
        fi
    fi

    [[ -z $png ]] && echo "$name jacket not found (exact or normalized)" && exit 1
    [[ $(echo "$png" | wc -l) -gt 1 ]] && printf "Multiple found for %s:\n\t%s\n" "$name" "$png" && exit 1

    echo Copying full-res jacket for $name from $png
    cp "$png" "$jackets_full_dir/$name.png"

    echo Downsizing jacket for $name from $png
    convert "$png" -resize 160x160 -quality 100 "$jackets_160_dir/$name.png"
done < <(ls "$BUILD_DIR/songs" | sed 's/\.json$//')

rm -f "$jacket_index"
