PLUGIN_ID := latentoperator.audible
PLUGIN_DIR := $(HOME)/.config/omarchy/plugins/$(PLUGIN_ID)
REPO_DIR := $(CURDIR)

.PHONY: test lint check-symlinks dev-link dev-unlink

test:
	python -m pytest -q

lint: check-symlinks
	omarchy plugin validate .

check-symlinks:
	@if [ -n "$$(find . -type l -not -path './.git/*')" ]; then \
		echo "Symlinks found inside the repo (not allowed):"; \
		find . -type l -not -path './.git/*'; \
		exit 1; \
	fi
	@echo "No symlinks inside the repo."

dev-link:
	@mkdir -p "$(HOME)/.config/omarchy/plugins"
	@if [ -e "$(PLUGIN_DIR)" ] && [ ! -L "$(PLUGIN_DIR)" ]; then \
		echo "$(PLUGIN_DIR) exists and is not a symlink; remove it first (omarchy plugin remove $(PLUGIN_ID))"; \
		exit 1; \
	fi
	ln -sfn "$(REPO_DIR)" "$(PLUGIN_DIR)"
	@echo "Linked $(REPO_DIR) -> $(PLUGIN_DIR)"

dev-unlink:
	@if [ -e "$(PLUGIN_DIR)" ] && [ ! -L "$(PLUGIN_DIR)" ]; then \
		echo "$(PLUGIN_DIR) is not a symlink; refusing to remove it"; \
		exit 1; \
	fi
	rm -f "$(PLUGIN_DIR)"
	@echo "Removed $(PLUGIN_DIR)"
