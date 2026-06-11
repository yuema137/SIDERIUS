"""Package re-export — preserves ``from nodes.ml_model_proposal_agent import X``
AND ``import nodes.ml_model_proposal_agent as alias`` import paths after the
Step 1 directory restructure. The actual node implementation lives in
``ml_model_proposal_agent.py`` alongside this file.

This package uses a ``sys.modules`` rebind (see bottom of file) so that
``nodes.ml_model_proposal_agent`` and
``nodes.ml_model_proposal_agent.ml_model_proposal_agent`` resolve to the SAME
module object. This restores the pre-restructure single-namespace semantics:
``unittest.mock.patch("nodes.ml_model_proposal_agent.X")`` intercepts the same
``X`` the agent code looks up internally, exactly as before the move.

The explicit re-export list below is informational — it documents the public
surface for readers. The rebind makes every name on the inner module reachable
via the package path automatically.
"""

from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _MAX_PREFLIGHT_ATTEMPTS,
    _MAX_PROPOSING_RETRIES,
    _PROPOSER_INPUT_KEYS,
    PROPOSAL_COMMIT_PROMPT,
    PROPOSAL_REASONING_PROMPT,
    LLMBridge,
    MLModelProposalAgent,
    _audit_proposer_components,
    _build_preflight_rejection_block,
    _build_reasoning_prompt,
    _check_citation_discipline,
    _format_recent_gate_exhaustions_block,
    _render_hardware_context_block,
    _render_stage_user_prompt,
    _truncate_description,
)

__all__ = [
    "PROPOSAL_COMMIT_PROMPT",
    "PROPOSAL_REASONING_PROMPT",
    "_MAX_PREFLIGHT_ATTEMPTS",
    "_MAX_PROPOSING_RETRIES",
    "_PROPOSER_INPUT_KEYS",
    "LLMBridge",
    "MLModelProposalAgent",
    "_audit_proposer_components",
    "_build_preflight_rejection_block",
    "_build_reasoning_prompt",
    "_check_citation_discipline",
    "_format_recent_gate_exhaustions_block",
    "_render_hardware_context_block",
    "_render_stage_user_prompt",
    "_truncate_description",
]

# --- sys.modules rebind ------------------------------------------------------
# Make `nodes.ml_model_proposal_agent` (this package) and
# `nodes.ml_model_proposal_agent.ml_model_proposal_agent` (the inner module)
# resolve to the SAME module object. After this line, attribute lookups on the
# package path are forwarded to the inner module — making
# `unittest.mock.patch` work correctly regardless of which path the test uses.
import sys

from nodes.ml_model_proposal_agent import ml_model_proposal_agent as _impl

sys.modules[__name__] = _impl
