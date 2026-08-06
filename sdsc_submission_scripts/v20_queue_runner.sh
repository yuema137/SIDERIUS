#!/bin/bash
# ---------------------------------------------------------------------------
# V20 QUEUE RUNNER — shim
# ---------------------------------------------------------------------------
# The queue POLICY lives in core/campaign/slot_scheduler.py, where it is
# unit-tested deterministically (no clock, no subprocess, no GPU), and the
# process management lives in v20_queue_runner.py.
#
# This file exists only so operator muscle memory from
# `v19_queue_runner.sh` still lands somewhere correct. It holds no
# scheduling logic of its own — a second implementation of "what launches
# next" is exactly how a band barrier gets reintroduced by accident.
#
#   bash sdsc_submission_scripts/v20_queue_runner.sh --plan
#   bash sdsc_submission_scripts/v20_queue_runner.sh --dry-run
#   bash sdsc_submission_scripts/v20_queue_runner.sh --execute
# ---------------------------------------------------------------------------
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
    PY="${PROJECT_DIR}/.venv/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
    PY="${VIRTUAL_ENV}/bin/python"
else
    echo "ERROR: no project virtualenv found; SIDERIUS requires .venv/bin/python" >&2
    exit 1
fi

exec "$PY" "${SCRIPT_DIR}/v20_queue_runner.py" "$@"
