# Isolated Python 3.12 scoring environment; does not change parser dependencies.
DDR_MD_DIR ?= $(abspath $(PROJ_DIR)/..)
SCORING_PYTHON ?= $(DDR_MD_DIR)/build/scoring-env/bin/python
SCORING_BUNDLE ?= $(DDR_MD_DIR)/build/scoring-v31

.PHONY: tiers tiers-check
# SONG is an exact song ID for the single-song/chart-fix workflow. Omit for all.
tiers:
	"$(SCORING_PYTHON)" "$(DDR_MD_DIR)/tool/scoring/cli.py" --input "$(BUILD_DIR)" --bundle "$(SCORING_BUNDLE)" --cache "$(BUILD_DIR)/scoring-cache" --report "$(BUILD_DIR)/scoring-coverage.json" $(if $(SONG),--song "$(SONG)",)

tiers-check:
	python3 "$(DDR_MD_DIR)/tool/scoring/validate_content.py" --songs "$(BUILD_DIR)/songs" --steps "$(BUILD_DIR)/steps"
