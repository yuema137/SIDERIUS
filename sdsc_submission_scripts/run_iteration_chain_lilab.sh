#!/bin/bash
# ---------------------------------------------------------------------------
# DEPRECATED: thin wrapper around run_chain.sh --mode lilab
# ---------------------------------------------------------------------------
# Phase 6.8 Commit 13 consolidated lilab + SDSC chain orchestration into
# run_chain.sh. This stub remains so existing runbooks / muscle memory keep
# working; removal is tracked under Commit 15.
#
# Migrate to:   bash sdsc_submission_scripts/run_chain.sh --mode lilab ...
#
# All flags pass through unchanged.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "WARNING: run_iteration_chain_lilab.sh is deprecated; use 'run_chain.sh --mode lilab' instead." >&2
exec bash "${SCRIPT_DIR}/run_chain.sh" --mode lilab "$@"
