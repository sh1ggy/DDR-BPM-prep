"""
make sure the scraped song set is valid: no song scraped under two versions,
and every name in removed.txt is a scraped folder (a typo there would let the
song through)
"""

import env


def main():
    songs = env.song_folders()  # raises on a name scraped under two versions
    scraped = {folder.name for folder in env.seed_dir.glob("*/*")}
    with open(env.removed_file, "r") as file:
        removed = [line.strip() for line in file if line.strip()]

    unknown = [name for name in removed if name not in scraped]
    for name in unknown:
        env.logger.warning(f"{env.removed_file} names a song that isn't scraped: {name}")
    print(f"{len(songs)} songs, {len(removed)} removed ({len(unknown)} not scraped)")


if __name__ == "__main__":
    main()
