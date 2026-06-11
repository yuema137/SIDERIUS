"""Package re-export — preserves ``from nodes.ml_code_validator_agent import X``
AND ``import nodes.ml_code_validator_agent as alias`` import paths after the
Step 1 directory restructure. The actual node implementation lives in
``ml_code_validator_agent.py`` alongside this file.

This package uses a ``sys.modules`` rebind (see bottom of file) so that
``nodes.ml_code_validator_agent`` and
``nodes.ml_code_validator_agent.ml_code_validator_agent`` resolve to the SAME
module object. This restores the pre-restructure single-namespace semantics:
``unittest.mock.patch("nodes.ml_code_validator_agent.X")`` intercepts the same
``X`` the agent code looks up internally, exactly as before the move.

The explicit re-export list below is informational — it documents the public
surface for readers. The rebind makes every name on the inner module reachable
via the package path automatically.
"""

from nodes.ml_code_validator_agent.ml_code_validator_agent import (
    LLMBridge,
    MLCodeValidatorAgent,
    _build_review_prompt,
    _check_config_fields,
    _check_description,
    _check_inherited_components,
    _check_instantiation_and_gradient,
    _check_plugin,
    _run_tests,
    subprocess,
)

__all__ = [
    "LLMBridge",
    "MLCodeValidatorAgent",
    "_build_review_prompt",
    "_check_config_fields",
    "_check_description",
    "_check_inherited_components",
    "_check_instantiation_and_gradient",
    "_check_plugin",
    "_run_tests",
    "subprocess",
]

# --- sys.modules rebind ------------------------------------------------------
# Make `nodes.ml_code_validator_agent` (this package) and
# `nodes.ml_code_validator_agent.ml_code_validator_agent` (the inner module)
# resolve to the SAME module object. After this line, attribute lookups on the
# package path are forwarded to the inner module — making
# `unittest.mock.patch` work correctly regardless of which path the test uses.
import sys

from nodes.ml_code_validator_agent import ml_code_validator_agent as _impl

sys.modules[__name__] = _impl
