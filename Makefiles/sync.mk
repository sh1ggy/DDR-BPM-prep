# Audio is packaged in the scraped zips but not extracted by `unzip`;
# this stage pulls it out on its own.
unzip_audio:
	bash $(PROJ_DIR)/scripts/scrape/unzip_audio.sh

# Fingerprint each song's audio against its chart timing and attach the
# result ("sync") to build/songs/*.json. Needs `make parse` output.
# Raw analysis is cached in build/sync/ (survives clobber); the first full
# run takes a couple of hours, reruns only merge.
sync: unzip_audio
	poetry run python $(SRC_DIR)/sync_songs.py

# Recompute sync analysis even for songs already cached in build/sync/
sync-force: export FORCE=Y
sync-force: sync

# Fingerprint arcade .ssq timing against .xwb audio and attach "arcade_sync"
# to build/songs/*.json — the sync a player feels on the cabinet, vs. the
# fan simfile's own sync above. Needs an arcade data dump pasted into
# data/arcade/ (no-op without it); cached in build/arcade_sync/.
arcade_sync:
	poetry run python $(SRC_DIR)/arcade_sync.py

arcade_sync-force: export FORCE=Y
arcade_sync-force: arcade_sync

clobber_sync:
	rm -fv build/sync/*.json || [ $$? -eq 1 ]

clobber_arcade_sync:
	rm -fv build/arcade_sync/*.json || [ $$? -eq 1 ]
