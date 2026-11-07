jackets:
	bash $(PROJ_DIR)/scripts/deploy/jackets.sh

jackets-force: export FORCE=Y
jackets-force: jackets
