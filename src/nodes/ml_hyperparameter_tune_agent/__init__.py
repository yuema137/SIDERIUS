"""Package re-export — preserves ``from nodes.ml_hyperparameter_tune_agent import X``
AND ``import nodes.ml_hyperparameter_tune_agent as alias`` import paths after the
Step 1 directory restructure. The actual node implementation lives in
``ml_hyperparameter_tune_agent.py`` alongside this file.

This package uses a ``sys.modules`` rebind (see bottom of file) so that
``nodes.ml_hyperparameter_tune_agent`` and
``nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent`` resolve to the
SAME module object. This restores the pre-restructure single-namespace semantics:
``unittest.mock.patch("nodes.ml_hyperparameter_tune_agent.X")`` intercepts the
same ``X`` the agent code looks up internally, exactly as before the move.

The explicit re-export list below is informational — it documents the public
surface for readers. The rebind makes every name on the inner module reachable
via the package path automatically.
"""

from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _FORMAL_STRATEGY_REGISTRY,
    HyperparamTuningAgent,
    LLMBridge,
    TidmadSandbox,
    _apply_degeneracy_reaction,
    _apply_mode_override_chain,
    _best_trial_winner,
    _build_gate_exhaustion,
    _collect_disallowed_patterns,
    _compute_termination_state,
    _copy_seed_plugin,
    _gate_results_to_score_meta,
    _latest_trial_inference_marginal,
    _merge_score_validity_failure,
    _render_gate_exhaustion_summary,
    _resolve_sample_set_cfg,
    _run_skill,
    _serialize_expert_advice,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
    _strategy_full_clone,
    _strategy_hybrid_params,
    _strategy_independent,
    build_sample_set,
    build_score_table,
    load_anchor_map,
    main,
)

__all__ = [
    "_FORMAL_STRATEGY_REGISTRY",
    "HyperparamTuningAgent",
    "LLMBridge",
    "TidmadSandbox",
    "_apply_degeneracy_reaction",
    "_apply_mode_override_chain",
    "_best_trial_winner",
    "_build_gate_exhaustion",
    "_collect_disallowed_patterns",
    "_compute_termination_state",
    "_copy_seed_plugin",
    "_gate_results_to_score_meta",
    "_latest_trial_inference_marginal",
    "_merge_score_validity_failure",
    "_render_gate_exhaustion_summary",
    "_resolve_sample_set_cfg",
    "_run_skill",
    "_serialize_expert_advice",
    "_should_bypass_formal_time_budget",
    "_should_skip_formal",
    "_strategy_full_clone",
    "_strategy_hybrid_params",
    "_strategy_independent",
    "build_sample_set",
    "build_score_table",
    "load_anchor_map",
    "main",
]

# --- sys.modules rebind ------------------------------------------------------
# Make `nodes.ml_hyperparameter_tune_agent` (this package) and
# `nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent` (the inner
# module) resolve to the SAME module object. After this line, attribute lookups
# on the package path are forwarded to the inner module — making
# `unittest.mock.patch` work correctly regardless of which path the test uses.
import sys

from nodes.ml_hyperparameter_tune_agent import ml_hyperparameter_tune_agent as _impl

sys.modules[__name__] = _impl
