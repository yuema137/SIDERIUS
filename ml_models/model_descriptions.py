# ml_models/model_descriptions.py
"""
Loader for per-model description.md files.

Each built-in model has a description.md in ml_models/{model_type}/description.md.
Agent-generated plugins get their description.md mirrored into the chain
workspace by ``workflows.model_exploration._register_plugin`` at the path
``{workspace}/plugins/{run_name}/{model_type}/description.md``. The chain
entry script (``sdsc_submission_scripts/run_one_iteration.py``) and the
in-process workflow entry (``workflows.model_exploration.run_workflow``)
set ``SIDERIUS_CHAIN_WORKSPACE`` to that workspace root, and this loader
picks up the plugin descriptions from the chain tree on later iterations.

Descriptions are written in markdown with math and are injected into LLM prompts
by the interpretation and proposal agents.
"""

import os

_ML_MODELS_DIR = os.path.dirname(os.path.abspath(__file__))
_SIDERIUS_ROOT = os.path.dirname(_ML_MODELS_DIR)
# LEGACY CHECKOUT plugin-descriptions dir (arXiv P1: read-only compatibility
# — promotion writes descriptions under the resolved generated-library
# models dir now; this location keeps resolving pre-migration copies).
_PLUGIN_DESCRIPTIONS_DIR = os.path.join(_SIDERIUS_ROOT, "agent_generated", "models")


def _scan_bundled_model_types() -> frozenset[str]:
    """Every model type that ships a ``description.md`` under ``ml_models/``."""
    found: set[str] = set()
    for name in os.listdir(_ML_MODELS_DIR):
        if os.path.isfile(os.path.join(_ML_MODELS_DIR, name, "description.md")):
            found.add(name)
    return frozenset(found)


#: The BUNDLED built-in model types (arXiv U3, #260) — the ONE authority for
#: "is this a shipped baseline". Defined by the same fact the loader below
#: reads (a ``description.md`` shipped under ``ml_models/``), so the loader's
#: refusal and the proposal refusal cannot name different sets. Agent
#: plugins never live under ``ml_models/``, so this is stable at import.
BUNDLED_MODEL_TYPES: frozenset[str] = _scan_bundled_model_types()


def is_bundled_model_type(model_type: str) -> bool:
    """Whether ``model_type`` is one of the shipped built-in baselines."""
    return model_type in BUNDLED_MODEL_TYPES


def _chain_workspace_candidates(model_type: str) -> list[str]:
    """Return chain-workspace plugin description.md paths, newest run first.

    Reads the ``SIDERIUS_CHAIN_WORKSPACE`` env var set by the chain entry
    scripts (or by ``run_workflow`` for in-process / single-iteration
    callers). Walks ``{workspace}/plugins/*/{model_type}/description.md``
    and returns every match whose ``description.md`` exists, sorted by
    subdir name in descending order — so a model re-registered in a later
    run / iter wins over an earlier one. Subdir names follow whatever the
    caller's ``run_name`` is (e.g. ``iter_001`` for chain mode,
    ``stage2_iter_001`` for the score-table smoke test); we don't filter
    by shape so any registered plugin tree is discoverable. Empty when
    the env var is unset, the dir is missing, or no run has registered
    this model type.
    """
    workspace = os.environ.get("SIDERIUS_CHAIN_WORKSPACE")
    if not workspace:
        return []
    plugins_root = os.path.join(workspace, "plugins")
    if not os.path.isdir(plugins_root):
        return []
    matches: list[str] = []
    for name in sorted(os.listdir(plugins_root), reverse=True):
        candidate = os.path.join(plugins_root, name, model_type, "description.md")
        if os.path.isfile(candidate):
            matches.append(candidate)
    return matches


def get_model_description(model_type: str, *, baseline_isolation: bool = False) -> str:
    """
    Load and return the description.md for the given model_type.

    Searches in priority order:
      1. ml_models/{model_type}/description.md  (built-in models)
      2. {generated library}/models/{model_type}/description.md  (arXiv P1 —
         the resolved library promotion writes to)
      3. agent_generated/models/{model_type}/description.md  (legacy plugin
         global — pre-migration promotions, read-only compatibility)
      4. ${SIDERIUS_CHAIN_WORKSPACE}/plugins/*/{model_type}/description.md
         (chain workspace plugin tree, newest registration first; any
         subdir name is accepted — chain mode uses ``iter_NNN``,
         in-process workflows use whatever ``run_name`` the caller passed)

    ``baseline_isolation`` (arXiv U3, #260 / ruling R6): when True, candidate
    1 — the BUNDLED baseline description — is refused rather than searched,
    so no shipped baseline prose can reach an LLM-facing prompt or the
    interpreter's carried cache. Plugin and workspace descriptions resolve
    exactly as before, and the failure shape is unchanged: a model type with
    nothing left to resolve raises the same ``FileNotFoundError``, listing
    what was searched and naming the refused bundled path.

    Raises:
        FileNotFoundError: if no description.md is found for the model_type.
    """
    from core.generated_library import generated_models_dir

    bundled = os.path.join(_ML_MODELS_DIR, model_type, "description.md")
    candidates = [
        *([] if baseline_isolation else [bundled]),
        os.path.join(generated_models_dir(), model_type, "description.md"),
        os.path.join(_PLUGIN_DESCRIPTIONS_DIR, model_type, "description.md"),
        *_chain_workspace_candidates(model_type),
    ]

    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()

    refused = (
        f"Refused under baseline_isolation (not searched):\n  {bundled}\n"
        if baseline_isolation
        else ""
    )
    raise FileNotFoundError(
        f"No description.md found for model_type '{model_type}'.\n"
        f"Searched:\n" + "\n".join(f"  {p}" for p in candidates) + "\n" + refused + ""
        "Each model must have a description.md in its folder."
    )
