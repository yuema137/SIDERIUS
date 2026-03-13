# ml_models/model_descriptions.py
"""
Loader for per-model description.md files.

Each built-in model has a description.md in ml_models/{model_type}/description.md.
Agent-generated plugins should place their description.md in agent_generated/models/{model_type}/description.md.

Descriptions are written in markdown with math and are injected into LLM prompts
by the interpretation and proposal agents.
"""

import os

_ML_MODELS_DIR = os.path.dirname(os.path.abspath(__file__))
_SIDERIUS_ROOT = os.path.dirname(_ML_MODELS_DIR)
_PLUGIN_DESCRIPTIONS_DIR = os.path.join(_SIDERIUS_ROOT, "agent_generated", "models")


def get_model_description(model_type: str) -> str:
    """
    Load and return the description.md for the given model_type.

    Searches:
      1. ml_models/{model_type}/description.md  (built-in models)
      2. agent_generated/models/{model_type}/description.md  (plugin models)

    Raises:
        FileNotFoundError: if no description.md is found for the model_type.
    """
    candidates = [
        os.path.join(_ML_MODELS_DIR, model_type, "description.md"),
        os.path.join(_PLUGIN_DESCRIPTIONS_DIR, model_type, "description.md"),
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
