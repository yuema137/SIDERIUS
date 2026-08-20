"""Package re-export — preserves ``from nodes.result_interpretation_agent import X``
AND ``import nodes.result_interpretation_agent as alias`` import paths after the
Step 1 directory restructure. The actual node implementation lives in
``result_interpretation_agent.py`` alongside this file.

This package uses a ``sys.modules`` rebind (see bottom of file) so that
``nodes.result_interpretation_agent`` and
``nodes.result_interpretation_agent.result_interpretation_agent`` resolve to the
SAME module object. This restores the pre-restructure single-namespace semantics:
``unittest.mock.patch("nodes.result_interpretation_agent.X")`` intercepts the
same ``X`` the agent code looks up internally, exactly as before the move.

The explicit re-export list below is informational — it documents the public
surface for readers. The rebind makes every name on the inner module reachable
via the package path automatically.
"""

from nodes.result_interpretation_agent.result_interpretation_agent import (
    InterpretationContractError,
    LLMBridge,
    ResultInterpretationAgent,
    _append_evolution_log,
    _compute_evolution_stats,
    _resolve_evolution_log_root,
    reconcile_metric_spec,
    tuning_output_to_model_run_summary,
)

__all__ = [
    # Step 09a C2 — PUBLIC: the protocol, the workflow and the calibration
    # scripts import these from the package. The sys.modules rebind below makes
    # them reachable at runtime either way, but a type checker reads THIS list,
    # so omitting them is an unknown-import-symbol error at every caller.
    #
    # Step 09b C1 — the prompt constants/builders left this package: the
    # interpreter's prompt surface lives in
    # agent/prompt_templates/interpretation/rendering.py, and their only
    # importers were tests (moved to the owning module). This list shrank;
    # it must never re-grow a prompt symbol.
    "InterpretationContractError",
    "LLMBridge",
    "ResultInterpretationAgent",
    "_append_evolution_log",
    "_compute_evolution_stats",
    "_resolve_evolution_log_root",
    "reconcile_metric_spec",
    "tuning_output_to_model_run_summary",
]

# --- sys.modules rebind ------------------------------------------------------
# Make `nodes.result_interpretation_agent` (this package) and
# `nodes.result_interpretation_agent.result_interpretation_agent` (the inner
# module) resolve to the SAME module object. After this line, attribute lookups
# on the package path are forwarded to the inner module — making
# `unittest.mock.patch` work correctly regardless of which path the test uses.
import sys

from nodes.result_interpretation_agent import result_interpretation_agent as _impl

sys.modules[__name__] = _impl
