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
from enum import StrEnum

from core.layout import checkout_path

_ML_MODELS_DIR = os.path.dirname(os.path.abspath(__file__))
# LEGACY CHECKOUT plugin-descriptions dir (arXiv P1: read-only compatibility
# — promotion writes descriptions under the resolved generated-library
# models dir now; this location keeps resolving pre-migration copies).
_PLUGIN_DESCRIPTIONS_DIR = checkout_path("agent_generated", "models")


class DescriptionSourcePolicy(StrEnum):
    """Which description roots a caller is authorized to consult."""

    LEGACY = "legacy"
    COMPOSED = "composed"


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


def _declared_pack_candidates(model_type: str) -> list[str]:
    """Description paths under the run's DECLARED model-plugin roots.

    Lane E / F11. Every other candidate root is inside the checkout or the
    generated library, so a task package living outside the tree had nowhere
    to put a ``description.md`` — it could only supply one by writing into
    the framework's own directories, which is precisely what the package
    contract exists to prevent. The effect was silent: the tuner's read is
    non-fatal, so an out-of-tree task simply got a thinner planner prompt
    forever.

    No new declaration surface is introduced. The manifest's
    ``model_plugins:`` section ALREADY declares where a pack's models live;
    this reads those same roots through the same ``active_*`` accessor the
    transport uses, and applies the layout every other candidate uses
    (``{root}/{model_type}/description.md``).

    Empty for an un-composed run, so legacy resolution is byte-unchanged.
    """
    from ml_models.plugin_binding import active_run_model_plugin_roots

    return [
        os.path.join(root, model_type, "description.md") for root in active_run_model_plugin_roots()
    ]


def get_model_description(
    model_type: str,
    *,
    baseline_isolation: bool = False,
    source_policy: DescriptionSourcePolicy = DescriptionSourcePolicy.LEGACY,
) -> str | None:
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
      5. {declared model-plugin root}/{model_type}/description.md (Lane E /
         F11 — the roots the manifest's ``model_plugins:`` section declares,
         so an OUT-OF-TREE pack can ship a description beside its plugin
         instead of writing into the framework tree. Empty, hence invisible,
         for an un-composed run.)

    Searched LAST, deliberately: a pack description must not shadow a
    workspace registration for the same model type, because the workspace
    copy is what the run actually staged and promoted.

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
    from core.generated_library import generated_library_is_workspace_bound, generated_models_dir

    try:
        source_policy = DescriptionSourcePolicy(source_policy)
    except ValueError as exc:
        raise ValueError(f"Unknown description source policy: {source_policy!r}") from exc

    composed = source_policy is DescriptionSourcePolicy.COMPOSED
    # A composed run is an explicit authority boundary.  The old flag remains
    # supported for standalone baseline-isolation witnesses, but never opts a
    # composed caller back into packaged prose.
    refuse_bundled = baseline_isolation or composed

    bundled = os.path.join(_ML_MODELS_DIR, model_type, "description.md")
    legacy_candidates = (
        []
        if generated_library_is_workspace_bound() or _PLUGIN_DESCRIPTIONS_DIR is None
        else [os.path.join(_PLUGIN_DESCRIPTIONS_DIR, model_type, "description.md")]
    )
    candidates = [
        *([] if refuse_bundled else [bundled]),
        os.path.join(generated_models_dir(), model_type, "description.md"),
        *legacy_candidates,
        *_chain_workspace_candidates(model_type),
        *_declared_pack_candidates(model_type),
    ]

    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()

    if composed:
        return None

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
