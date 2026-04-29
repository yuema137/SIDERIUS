# ml_models/model_descriptions.py
"""
Loader for per-model description.md files.

Each built-in model has a description.md in ml_models/{model_type}/description.md.
Agent-generated plugins get their description.md mirrored into the chain
workspace by ``workflows.model_exploration._register_plugin`` at the path
``{workspace}/plugins/iter_NNN/{model_type}/description.md``. The chain
entry script (``sdsc_submission_scripts/run_one_iteration.py`` or
``run_exploration_adaptive.py``) sets ``SIDERIUS_CHAIN_WORKSPACE`` to that
workspace root, and this loader picks up the plugin descriptions from the
chain tree on later iterations.

Descriptions are written in markdown with math and are injected into LLM prompts
by the interpretation and proposal agents.
"""

import os
import re

_ML_MODELS_DIR = os.path.dirname(os.path.abspath(__file__))
_SIDERIUS_ROOT = os.path.dirname(_ML_MODELS_DIR)
_PLUGIN_DESCRIPTIONS_DIR = os.path.join(_SIDERIUS_ROOT, "agent_generated", "models")

_ITER_DIR_RE = re.compile(r"^iter_\d{3}$")


def _chain_workspace_candidates(model_type: str) -> list[str]:
    """Return chain-workspace plugin description.md paths, newest iter first.

    Reads the ``SIDERIUS_CHAIN_WORKSPACE`` env var set by the chain entry
    script. Walks ``{workspace}/plugins/iter_NNN/{model_type}/description.md``
    and returns matches sorted by iter index, highest first — so a model
    re-registered in a later iter wins over an earlier one. Empty when the
    env var is unset, the dir is missing, or no iter has registered this
    model type.
    """
    workspace = os.environ.get("SIDERIUS_CHAIN_WORKSPACE")
    if not workspace:
        return []
    plugins_root = os.path.join(workspace, "plugins")
    if not os.path.isdir(plugins_root):
        return []
    iter_dirs = sorted(
        (n for n in os.listdir(plugins_root) if _ITER_DIR_RE.match(n)),
        reverse=True,
    )
    return [
        os.path.join(plugins_root, name, model_type, "description.md")
        for name in iter_dirs
    ]


def get_model_description(model_type: str) -> str:
    """
    Load and return the description.md for the given model_type.

    Searches in priority order:
      1. ml_models/{model_type}/description.md  (built-in models)
      2. agent_generated/models/{model_type}/description.md  (legacy plugin global)
      3. ${SIDERIUS_CHAIN_WORKSPACE}/plugins/iter_NNN/{model_type}/description.md
         (chain workspace plugin tree, newest iter first)

    Raises:
        FileNotFoundError: if no description.md is found for the model_type.
    """
    candidates = [
        os.path.join(_ML_MODELS_DIR, model_type, "description.md"),
        os.path.join(_PLUGIN_DESCRIPTIONS_DIR, model_type, "description.md"),
        *_chain_workspace_candidates(model_type),
    ]

    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

    raise FileNotFoundError(
        f"No description.md found for model_type '{model_type}'.\n"
        f"Searched:\n" + "\n".join(f"  {p}" for p in candidates) + "\n"
        f"Each model must have a description.md in its folder."
    )
