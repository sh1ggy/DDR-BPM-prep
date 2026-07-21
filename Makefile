SHELL := /bin/zsh

export PROJ_DIR=$(CURDIR)
export SRC_DIR=$(CURDIR)/src
export SEED_DIR=$(CURDIR)/data
export BUILD_DIR=$(PROJ_DIR)/build
include Makefiles/scraper.mk
include Makefiles/parser.mk
include Makefiles/sync.mk
include Makefiles/deploy.mk

# Run after scraping (parse, attach arcade sync & prepare full-res + 160 jackets).
# Simfile sync (`make sync`) is kept available but deliberately not part of
# main: the app's use case is cabinet feel, which only arcade_sync provides.
main: clobber parse arcade_sync predeploy

release:
	bash $(PROJ_DIR)/scripts/deploy/release.sh
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
