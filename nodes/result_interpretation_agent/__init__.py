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
    LLMBridge,
    PER_MODEL_SYSTEM_PROMPT,
    ResultInterpretationAgent,
    SYNTHESIS_SYSTEM_PROMPT,
    _append_evolution_log,
    _build_per_model_prompt,
    _build_synthesis_prompt,
    _compute_evolution_stats,
    _resolve_evolution_log_root,
    tuning_output_to_model_run_summary,
)

__all__ = [
    "LLMBridge",
    "PER_MODEL_SYSTEM_PROMPT",
    "ResultInterpretationAgent",
    "SYNTHESIS_SYSTEM_PROMPT",
    "_append_evolution_log",
    "_build_per_model_prompt",
    "_build_synthesis_prompt",
    "_compute_evolution_stats",
    "_resolve_evolution_log_root",
    "tuning_output_to_model_run_summary",
]

# --- sys.modules rebind ------------------------------------------------------
# Make `nodes.result_interpretation_agent` (this package) and
# `nodes.result_interpretation_agent.result_interpretation_agent` (the inner
# module) resolve to the SAME module object. After this line, attribute lookups
# on the package path are forwarded to the inner module — making
# `unittest.mock.patch` work correctly regardless of which path the test uses.
import sys  # noqa: E402

from nodes.result_interpretation_agent import result_interpretation_agent as _impl  # noqa: E402

sys.modules[__name__] = _impl
