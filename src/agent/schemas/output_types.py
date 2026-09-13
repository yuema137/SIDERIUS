"""Output names shared by schemas, launch configuration and model plugins.

Keep this module independent of node schemas and model registries: the plugin
loader imports it before those heavier consumers initialize.
"""

from typing import Literal

# Builtin-only ``hybrid`` is an execution adapter, not a declarable output type.
OutputTypeName = Literal["classifier", "regressor"]
