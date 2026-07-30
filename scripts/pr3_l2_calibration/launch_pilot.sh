#!/usr/bin/env bash
# P3-L2p calibration launch wrapper (R-4 fix, PR 3 audit §13.3).
#
# Guarantees the Python runner's exit status is the wrapper's exit status:
# the rev-2/rev-3 pilots were launched with an ad-hoc `... ; echo` chain
# whose trailing echo turned every failure into observed exit 0. Here the
# runner is the ONLY status source — tee runs in a pipeline and we return
# PIPESTATUS[0] explicitly, so trailing logging can never mask a failure.
#
# Usage:
#   scripts/pr3_l2_calibration/launch_pilot.sh <log-file> \
#       --run_id <id> --max_calls N --dollar_cap D --max_terminal_failures K
#
# Exit codes mirror runner.EXIT_CODES:
#   0 completed | 3 protocol_stop | 4 budget_stop | 1 technical_failure |
#   130 external_interruption
#
# PILOT_PYTHON may override the interpreter (tests use this); the default
# is the repo venv resolved relative to this script — never the caller's
# cwd or a hardcoded absolute path (portability rule).
set -uo pipefail

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <log-file> [runner args...]" >&2
    exit 2
fi

LOG_FILE="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_BIN="${PILOT_PYTHON:-${REPO_ROOT}/.venv/bin/python}"

cd "${REPO_ROOT}"
"${PYTHON_BIN}" -m scripts.pr3_l2_calibration.runner "$@" 2>&1 | tee -a "${LOG_FILE}"
exit "${PIPESTATUS[0]}"
