#!/bin/bash
# ---------------------------------------------------------------------------
# DEPRECATED: thin wrapper around run_chain.sh --mode sdsc
# ---------------------------------------------------------------------------
# Phase 6.8 Commit 13 consolidated lilab + SDSC chain orchestration into
# run_chain.sh. This stub remains so existing runbooks / muscle memory keep
# working; removal is tracked under Commit 15.
#
# Migrate to:   bash sdsc_submission_scripts/run_chain.sh --mode sdsc ...
#
# All flags pass through unchanged.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "WARNING: run_iteration_chain.sh is deprecated; use 'run_chain.sh --mode sdsc' instead." >&2
exec bash "${SCRIPT_DIR}/run_chain.sh" --mode sdsc "$@"
