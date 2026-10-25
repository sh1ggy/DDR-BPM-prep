full_scrape: scrape_packs unzip scrape_songs dedupe

# Pack categoryids (one per DDR version) live in scripts/scrape/packs.txt.
# Already-downloaded packs are skipped via the manifest in data/downloaded.txt.
scrape_packs:
	bash $(PROJ_DIR)/scripts/scrape/scrape_packs.sh

# Some songs aren't located in the above packs.
# They are listed in scripts/scrape/songs.txt and downloaded into one of the folders.
scrape_songs:
	bash $(PROJ_DIR)/scripts/scrape/scrape_songs.sh

# Some songs are duplicates.
# Deprecated song-titles are listed in scripts/scrape/deprecated.txt and deleted.
dedupe:
	bash $(PROJ_DIR)/scripts/scrape/dedupe_songs.sh

unzip:
	bash $(PROJ_DIR)/scripts/scrape/unzip_pack.sh

# Rebuild data/konami.tsv (Konami song ID -> prep song) from the e-amusement pages; run after parse.
# Needs the session cookie in the Keychain; see src/konami_music.py.
konami_music:
	poetry run python $(SRC_DIR)/konami_music.py
