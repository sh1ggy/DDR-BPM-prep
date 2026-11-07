SHELL := /bin/zsh

export PROJ_DIR=$(CURDIR)
export SRC_DIR=$(CURDIR)/src
export SEED_DIR=$(CURDIR)/data
export BUILD_DIR=$(PROJ_DIR)/build
include Makefiles/scraper.mk
include Makefiles/parser.mk
include Makefiles/sync.mk
include Makefiles/jackets.mk
include Makefiles/tiers.mk

# Everything after scraping, in the shape the content repo publishes: parse,
# then put back what the parse drops (simfile sync and arcade sync from their
# caches, time signatures, scoring tiers) and stage jackets. The release
# console runs this; on unchanged inputs it reproduces the live content.
prepare:
	$(MAKE) parse
	poetry run python $(SRC_DIR)/sync_songs.py
	$(MAKE) arcade_sync
	$(MAKE) arcade_timesigs
	$(MAKE) tiers
	$(MAKE) tiers-check
	$(MAKE) jackets

# prepare from scratch: also deletes the pack zips, which a scrape has to
# download again.
main:
	$(MAKE) clobber
	$(MAKE) prepare
################################################################################
# CLEAN
################################################################################
clean:
	rm -fv log/*.txt || [ $$? -eq 1 ]

# build/sync is deliberately spared: it caches hours of audio analysis and
# only depends on data/ (wipe it explicitly with `make clobber_sync`)
clobber: clean
	rm -fv data/**/*.zip || [ $$? -eq 1 ]
	rm -fv build/{courses,songs,steps,summaries}/*.json(N) || [ $$? -eq 1 ]

# The release console: the one way to prepare and release content.
admin:
	poetry run python -m admin serve
