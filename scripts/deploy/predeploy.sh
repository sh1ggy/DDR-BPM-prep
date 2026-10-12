#!/bin/bash
SEED_DIR=${SEED_DIR:-./data}
BUILD_DIR=${BUILD_DIR:-./build}

normalize_name() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+//g'
}

# Jacket outputs
jackets_full_dir=$BUILD_DIR/jackets
jackets_160_dir=$BUILD_DIR/jackets-160
mkdir -p $jackets_full_dir
mkdir -p $jackets_160_dir

# Copy audio previews
audio_dir=$BUILD_DIR/audio
mkdir -p $audio_dir

while IFS= read -r ogg; do
    name=$(basename "$ogg" .ogg)
    [[ -f "$audio_dir/$name-song.ogg" && -z $FORCE ]] && continue

    echo Copying audio for $name
    cp "$ogg" "$audio_dir/$name-song.ogg"
done < <(find $SEED_DIR -type f -name "*.ogg")

# Copy simfiles
simfiles_dir=$BUILD_DIR/simfiles
mkdir -p $simfiles_dir

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
    [[ ( -f "$simfiles_dir/$name.sm" || -f "$simfiles_dir/$name.ssc" ) && -z $FORCE ]] && continue

    search_name=$(echo $name | sed -e 's:\[:\\[:g' -e 's:]:\\]:g') # escape square brackets
    # prefer .sm over .ssc, same as SimfileRes.findSimfile
    sim=$(find $SEED_DIR -type f -name "$search_name.sm")
    [[ -z $sim ]] && sim=$(find $SEED_DIR -type f -name "$search_name.ssc")
    [[ -z $sim ]] && echo "$name simfile not found" && exit 1
    [[ $(echo "$sim" | wc -l) -gt 1 ]] && printf "Multiple found for %s:\n\t%s\n" "$name" "$sim" && exit 1

    echo Copying simfile for $name
    cp "$sim" "$simfiles_dir/"
done < $SEED_DIR/all_songs.txt

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

    # Full-resolution copy
    echo Copying full-res jacket for $name from $png
    cp "$png" "$jackets_full_dir/$name.png"

    # 160x160 downscaled copy
    echo Downsizing jacket for $name from $png
    convert "$png" -resize 160x160 -quality 100 "$jackets_160_dir/$name.png"
done < $SEED_DIR/all_songs.txt

rm -f "$jacket_index"


# Zip
7z a -tzip $BUILD_DIR/songs.zip -w $BUILD_DIR/songs/.
7z a -tzip $BUILD_DIR/steps.zip -w $BUILD_DIR/steps/.
7z a -tzip $BUILD_DIR/jackets.zip -w $jackets_160_dir/.
7z a -tzip $BUILD_DIR/jackets-full.zip -w $jackets_full_dir/.
7z a -tzip $BUILD_DIR/simfiles.zip -w $simfiles_dir/.

# other files
cp $SEED_DIR/all_songs.txt $SEED_DIR/removed.txt $BUILD_DIR/
