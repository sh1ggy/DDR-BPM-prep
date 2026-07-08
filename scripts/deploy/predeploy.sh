#!/bin/bash
SEED_DIR=${SEED_DIR:-./data}
BUILD_DIR=${BUILD_DIR:-./build}

# Downsize images
jackets_dir=$BUILD_DIR/jackets-160
mkdir -p $jackets_dir

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
    [[ -f "$jackets_dir/$name.png" && -z $FORCE ]] && continue

    search_name=$(echo $name | sed -e 's:\[:\\[:g' -e 's:]:\\]:g') # escape square brackets
    png=$(find $SEED_DIR -type f -name "$search_name-jacket.png")
    [[ -z $png ]] && echo "$name jacket not found" && exit 1
    [[ $(echo "$png" | wc -l) -gt 1 ]] && printf "Multiple found for %s:\n\t%s\n" "$name" "$png" && exit 1

    # Images
    echo Downsizing $name from $png
    convert "$png" -resize 160x160 -quality 100 "$jackets_dir/$name.png"
done < $SEED_DIR/all_songs.txt


# Zip
7z a -tzip $BUILD_DIR/songs.zip -w $BUILD_DIR/songs/.
7z a -tzip $BUILD_DIR/jackets.zip -w $jackets_dir/.
7z a -tzip $BUILD_DIR/simfiles.zip -w $simfiles_dir/.

# other files
cp $SEED_DIR/all_songs.txt $SEED_DIR/removed.txt $BUILD_DIR/
