# SIDERIUS contributor gate (issue #292) — see CONTRIBUTING.md.
#
# `make check` runs, locally, the same checks CI's quality job runs on every
# push and pull request (.github/workflows/ci.yml), minus the two
# environment-dependent pieces:
#
#   * dependency installation — CI runs `uv sync --group dev --frozen` as its
#     own step; that command is the one supported environment path. Run it
#     once yourself before the first `make check` (see CONTRIBUTING.md).
#   * pyright, when the host toolchain cannot execute it (the PyPI `pyright`
#     wraps the Node.js implementation) — the stage is then skipped with a
#     clearly labelled line, and CI remains the owner of the type check.
#
# No GPU, no dataset, no API key is required: the unit tier mocks every heavy
# subsystem by design. Recipes invoke tools through `uv run --no-sync`, so the
# gate never installs, upgrades or re-locks anything — a stale environment
# fails visibly instead of being silently "fixed".
#
# Drift guard: tests/unit/tools/test_contributor_gate_makefile.py goes RED
# when these recipes stop matching the command strings in
# .github/workflows/ci.yml. Change CI and this file together.

UV_RUN := uv run --no-sync

.PHONY: check lint format-check typecheck test

check: lint format-check typecheck test
	@echo "make check: all stages done (any SKIP line above names what CI still owns)."

lint:
	$(UV_RUN) ruff check .

format-check:
	$(UV_RUN) ruff format --check .

# CI runs `uv run pyright` unconditionally. Locally the probe below fails fast
# on a host whose Node.js cannot run pyright's bundled JS (e.g. Node 10), and
# the stage is skipped honestly rather than half-run.
typecheck:
	@if $(UV_RUN) pyright --version >/dev/null 2>&1; then \
		$(UV_RUN) pyright; \
	else \
		echo "SKIP typecheck: this host's toolchain cannot run pyright (it needs a modern Node.js runtime); CI owns this check — the 'uv run pyright' step in .github/workflows/ci.yml."; \
	fi

test:
	$(UV_RUN) pytest tests/unit/ -m "not real_run" -q
