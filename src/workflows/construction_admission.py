"""Shared generated-model construction admission before native staging."""

import os

from agent.schemas.implementor import ImplementorOutput
from core.runtime_control.construction_memory import CandidateAdmissionError


def admit_generated_model_construction(impl_output: ImplementorOutput, model_name: str) -> None:
    """Inspect and admit a generated model before staging or registration."""
    if not os.path.isfile(impl_output.model_file_path):
        # Test/pseudo implementations may intentionally provide no source;
        # staging has the established no-op contract for that case.
        return
    from core.runtime_control.construction_memory import admit_construction
    from ml_models.plugin_loader import inspect_model_plugin

    with inspect_model_plugin(impl_output.model_file_path) as plugin:
        if plugin is None:
            raise CandidateAdmissionError(
                f"Candidate {model_name!r} plugin metadata could not be loaded; "
                "repair the generated plugin and propose again.",
                model_name=model_name,
            )
        admit_construction(
            model_class=plugin["model_class"],
            config_class=plugin["config_class"],
            model_name=model_name,
        )
