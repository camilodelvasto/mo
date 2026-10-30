# moui (018-workspace) — dev tasks.
#
# Two editable installs off this same repo (so your CODE is always live in both):
#   • pipx `mo`  — the global command for RUNNING the tool   (~/.local/bin/mo)
#   • .venv      — for RUNNING THE TESTS (pytest lives in the dev extra)
#
# Code edits need no reinstall (editable). Only DEPENDENCY changes drift the envs.
# After editing pyproject.toml, run `make sync` to resync both from it.

VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: help sync venv test

help:                ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  make %-8s %s\n", $$1, $$2}'

sync: venv           ## resync BOTH installs from pyproject.toml (run after changing deps)
	pipx install --force --editable .
	$(PY) -m pip install -e ".[dev]"
	@echo "✓ synced. Run the tool with:  mo corpus catalogue <corpus-path>"

venv:                ## create the test virtualenv if it does not exist
	@test -d $(VENV) || python3.12 -m venv $(VENV)

test: venv           ## run the test suite (corpus tests: make test ARGS="-k corpus")
	$(PY) -m pytest $(ARGS)
