"""Package re-export — preserves ``from nodes.ml_model_implementor import X``
AND ``import nodes.ml_model_implementor as alias`` import paths after the
Step 1 directory restructure. The actual node implementation lives in
``ml_model_implementor.py`` alongside this file.

This package uses a ``sys.modules`` rebind (see bottom of file) so that
``nodes.ml_model_implementor`` and
``nodes.ml_model_implementor.ml_model_implementor`` resolve to the SAME module
object. This restores the pre-restructure single-namespace semantics:
``unittest.mock.patch("nodes.ml_model_implementor.X")`` intercepts the same
``X`` the agent code looks up internally, exactly as before the move.

The explicit re-export list below is informational — it documents the public
surface for readers. The rebind makes every name on the inner module reachable
via the package path automatically.
"""

from nodes.ml_model_implementor.ml_model_implementor import (
    MLModelImplementor,
    _assemble_plugin,
    _build_reasoning_prompt,
    _check_baseline_schema_compatibility,
    _check_config_field_consistency,
    _class_name,
    _smoke_test_plugin,
)

__all__ = [
    "MLModelImplementor",
    "_assemble_plugin",
    "_build_reasoning_prompt",
    "_check_baseline_schema_compatibility",
    "_check_config_field_consistency",
    "_class_name",
    "_smoke_test_plugin",
]

# --- sys.modules rebind ------------------------------------------------------
# Make `nodes.ml_model_implementor` (this package) and
# `nodes.ml_model_implementor.ml_model_implementor` (the inner module) resolve
# to the SAME module object. After this line, attribute lookups on the package
# path are forwarded to the inner module — making `unittest.mock.patch` work
# correctly regardless of which path the test uses.
import sys  # noqa: E402

from nodes.ml_model_implementor import ml_model_implementor as _impl  # noqa: E402

sys.modules[__name__] = _impl
