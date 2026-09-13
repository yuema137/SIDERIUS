# ml_models/plugin_loader.py
"""
Plugin loader for agent-generated models.

Scans the resolved plugin directories (run-scoped binding / env dirs /
the generated-library models dir with the legacy checkout
``agent_generated/models`` as read-only fallback — see
``_resolve_plugin_dirs``) for *.py files and extends MODEL_REGISTRY,
PLUGIN_CONFIG_REGISTRY, and PLUGIN_OUTPUT_TYPE_REGISTRY with any valid
plugins found.

Plugin interface — each plugin file must define:
    PLUGIN_MODEL_TYPE  : str   — unique model key (e.g. "attn_fcnet")
    PLUGIN_CONFIG_CLASS: type  — Pydantic BaseModel subclass
    PLUGIN_MODEL_CLASS : type  — nn.Module subclass
                                  forward contract: [B, T] int → [B, 256, T] float
    PLUGIN_OUTPUT_TYPE : str   — "classifier" or "regressor" (optional, defaults to "classifier")
"""

import importlib.util
import os
import sys
from types import ModuleType
from typing import get_args

from agent.schemas.output_types import OutputTypeName
from core.layout import checkout_path

# LEGACY CHECKOUT model-plugin directory: the repository's
# ``agent_generated/models``. arXiv P1: this is a READ-ONLY compatibility
# fallback — promotions write to the resolved generated-library root
# (``core.generated_library.generated_models_dir()``), and this dir is
# scanned AFTER it so a pre-migration checkout keeps resolving what it
# already promoted while never being written to again.
AGENT_GENERATED_DIR = checkout_path("agent_generated", "models")

# Env var name used to opt into run-scoped plugin directories. When set to a
# non-empty ``os.pathsep``-separated list of directory paths, plugin loading
# scans *only* those directories and ignores ``AGENT_GENERATED_DIR``. When
# unset or empty, the loader falls back to scanning ``AGENT_GENERATED_DIR``
# (legacy global-dir mode) — this is the back-compat default.
# See docs/run_scoped_plugins.md.
_PLUGIN_DIRS_ENV_VAR = "SIDERIUS_PLUGIN_DIRS"

# Prefix for per-plugin module names registered in ``sys.modules`` after load.
# The full name is ``_MODULE_NAME_PREFIX + <filename stem>`` so each plugin gets
# a unique, stable identity. Stability is required for ``inspect.getsource`` /
# ``inspect.getmodule`` to resolve the source file — without registration, any
# class loaded from a plugin appears as a built-in (Python's inspect machinery
# walks ``sys.modules[cls.__module__]`` to find ``__file__``). The tuner's
# Phase D.1 planner-prompt excerpt (``format_plugin_source_excerpt_block``)
# depends on that resolution.
_MODULE_NAME_PREFIX = "siderius_plugin_"

# Populated at load time by extend_registries().
# Maps plugin model_type → "classifier" or "regressor".
PLUGIN_OUTPUT_TYPE_REGISTRY: dict[str, str] = {}


# --- Output-contract vocabulary: ONE authority, two derived sets -------------
# Step 12 / PR-12a C4, closing issue #234.
#
# The two sets are genuinely different, which is why one constant could not
# serve both and why a 3-vs-2 disagreement between the loader and the validator
# survived for so long: a plugin legal at LOAD time was refused at VALIDATION
# time, and an unrecognised value was silently rewritten to "classifier".

#: What a PLUGIN may declare. Evidence-derived, not asserted: across the 109
#: generated plugins on record the distribution is 106 ``classifier`` +
#: 3 ``regressor`` and **zero** ``hybrid``; the implementor template emits one
#: of the two; and the validator has independently enforced exactly this pair
#: (``_LEGAL_OUTPUT_TYPES``) since V21 PR A. ``hybrid`` reaches the registry
#: through the builtin table, never through a plugin file.
#: Derive from the lightweight schema owner shared with proposal/config/CLI.
PLUGIN_LEGAL_OUTPUT_TYPES: tuple[str, ...] = get_args(OutputTypeName)

#: Every output contract the framework can INTERPRET, including the legacy
#: builtin adapter value. ``"hybrid"`` is not a tensor semantic — it means "the
#: shape is classifier-shaped but every loss is legal" and is carried by
#: BUILT-IN models only (``BUILTIN_OUTPUT_TYPES``: ``fcnet``). It stays in the
#: vocabulary because real consumers branch on it — ``inference_single``
#: routes regression on ``output_type == "hybrid" and target_dtype ==
#: torch.float32`` — so deleting it would change execution, not just wording.
OUTPUT_TYPE_VOCABULARY: tuple[str, ...] = (*PLUGIN_LEGAL_OUTPUT_TYPES, "hybrid")

#: Read for a plugin that predates the declaration (V21 PR A). Kept — and
#: deliberately NOT folded into the refusal below — because the validator's
#: matching ``_DEFAULT_OUTPUT_TYPE`` is a legacy-read path with its own
#: reachability test guarding it against silent removal. Refusing omission here
#: while the validator still accepts it would recreate the loader/validator
#: divergence this commit exists to remove. Issue #234 is about a declaration
#: that is PRESENT and unrecognised; that is what fails closed.
_LEGACY_OMITTED_OUTPUT_TYPE = "classifier"


class _InvalidPackageModel(ValueError):
    """Unwind new modules when the family's ordinary metadata check rejects."""


def _load_captured_plugin(path: str) -> dict | None:
    """Validate a selected package model, rolling back rejected acquisitions."""
    from core.local_code import LocalCodeError, acquire_module

    try:
        with acquire_module(path) as captured:
            assert captured is not None
            attributes = _plugin_attributes(captured, path)
            if attributes is None:
                raise _InvalidPackageModel
            return attributes
    except LocalCodeError:
        raise
    except _InvalidPackageModel:
        return None
    except Exception as exc:
        from core.local_code.failure import raise_if_code_package_failure

        raise_if_code_package_failure(exc)
        print(f"[PluginLoader] Failed to load {path}: {exc}")
        return None


def _load_plugin(path: str) -> dict | None:
    """Load a single plugin file. Returns attribute dict or None if invalid.

    Legacy modules retain their filename-derived ``sys.modules`` name for
    downstream source inspection; declared members use their captured package.
    """
    from core.local_code import selected_member

    if selected_member(path) is not None:
        # Invalid selected metadata is an ordinary refusal, never legacy fallback.
        return _load_captured_plugin(path)
    module_name = _MODULE_NAME_PREFIX + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        print(f"[PluginLoader] Could not resolve module spec for {path}")
        return None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so the plugin can reference its own module name
    # (via ``__name__``) without surprising downstream inspect calls.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # Roll back the sys.modules entry on load failure so a broken plugin
        # can be fixed and retried in the same process.
        sys.modules.pop(module_name, None)
        from core.local_code.failure import raise_if_code_package_failure

        raise_if_code_package_failure(e)
        print(f"[PluginLoader] Failed to load {path}: {e}")
        return None

    return _plugin_attributes(module, path)


def _plugin_attributes(module: ModuleType, path: str) -> dict | None:
    """The existing model metadata contract, independent of source acquisition."""
    for attr in ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS"):
        if not hasattr(module, attr):
            print(f"[PluginLoader] Skipping {os.path.basename(path)}: missing '{attr}'")
            return None

    # PLUGIN_OUTPUT_TYPE is optional — an OMITTED declaration reads the legacy
    # default (see `_LEGACY_OMITTED_OUTPUT_TYPE`). A declaration that is
    # PRESENT but not plugin-legal REFUSES the plugin.
    #
    # Issue #234, closed here. This used to print a warning and rewrite the
    # value to "classifier": an external package whose model emits, say,
    # segmentation masks would then have trained, been scored and been ranked
    # as a 256-class classifier, with nothing downstream able to tell. A
    # metadata defect became wrong science. The refusal uses this module's
    # established malformed-plugin convention — a named printed reason and a
    # `None` return — so every existing caller already handles it.
    output_type = getattr(module, "PLUGIN_OUTPUT_TYPE", _LEGACY_OMITTED_OUTPUT_TYPE)
    if output_type not in PLUGIN_LEGAL_OUTPUT_TYPES:
        print(
            f"[PluginLoader] Skipping {os.path.basename(path)}: "
            f"PLUGIN_OUTPUT_TYPE={output_type!r} is not a legal plugin output "
            f"contract (expected one of: {', '.join(PLUGIN_LEGAL_OUTPUT_TYPES)}). "
            f"It is NOT coerced to a default — an unrecognised output contract "
            f"is a defect, not a preference."
        )
        return None

    return {
        "model_type": module.PLUGIN_MODEL_TYPE,
        "config_class": module.PLUGIN_CONFIG_CLASS,
        "model_class": module.PLUGIN_MODEL_CLASS,
        "output_type": output_type,
    }


def _resolve_plugin_dirs() -> list[str]:
    """Return the ordered list of directories to scan for plugins.

    Priority:
      1. the RUN-SCOPED binding's declared roots (Step 12 / PR-12d, seam P),
         when a composed run declared model plugins. These come FIRST because
         they are the most run-specific statement of what should execute.
      2. ``SIDERIUS_PLUGIN_DIRS`` env var — ``os.pathsep``-separated list of
         directory paths. Per-run mode: scans exactly those directories,
         does NOT fall back to the global library.
      3. ``[generated_models_dir(), AGENT_GENERATED_DIR]`` — global-library
         mode when neither of the above is present (arXiv P1): the resolved
         generated-library models dir first, then the LEGACY CHECKOUT
         ``agent_generated/models`` as a read-only compatibility fallback so
         pre-migration promotions keep loading. A ``model_type`` loadable
         from BOTH locations refuses via :func:`_refuse_ambiguous_origins`
         — that state is never produced by promotion (same-name promotion
         is an idempotent skip across both locations), only by hand-copying,
         and silently picking one copy is the seam-P failure mode.

    Branch (2) is unchanged. A process with no run-scoped binding and no
    env var — the parent workflow process — now scans the two library
    locations instead of the checkout one; the binding rule is unchanged:
    a runtime default may extend the declared set and may never overwrite
    or drop it.

    Whitespace-only or empty entries in the env var are filtered out so
    that ``SIDERIUS_PLUGIN_DIRS=":dir_a::dir_b:"`` still resolves to
    ``["dir_a", "dir_b"]`` — this matches how shells commonly compose
    path-like variables. The merge is delegated to
    ``plugin_binding.union_plugin_roots``, the ONE place root-set merging is
    expressed, so the loader and the transport cannot drift apart.
    """
    from core.generated_library import generated_library_is_workspace_bound, generated_models_dir
    from ml_models.plugin_binding import active_run_model_plugin_roots, union_plugin_roots

    declared = active_run_model_plugin_roots()
    env = os.environ.get(_PLUGIN_DIRS_ENV_VAR, "").strip()
    if declared:
        return list(union_plugin_roots(declared, env))
    if env:
        return [p for p in env.split(os.pathsep) if p.strip()]
    if generated_library_is_workspace_bound() or AGENT_GENERATED_DIR is None:
        return [generated_models_dir()]
    return [generated_models_dir(), AGENT_GENERATED_DIR]


def _refuse_ambiguous_origins(origins: dict[str, list[str]], scanned: list[str]) -> None:
    """Refuse a ``model_type`` produced by more than one scanned DIRECTORY.

    Step 12 / PR-12d, seam P. ``extend_registries`` resolves collisions by
    scan order — the later directory wins — which was safe for as long as
    exactly one directory was ever scanned. That was structurally true before
    seam P: ``_resolve_plugin_dirs`` returned *either* the env list (one
    entry, the sandbox's own plugin dir) *or* ``[AGENT_GENERATED_DIR]``.

    Unioning declared roots into the set makes the collision reachable, and
    silent shadowing there is the failure this PR exists to prevent: a run
    that declared a pack's reference model would train, score and rank a
    same-named implementation from a directory it never declared, with
    nothing anywhere saying so.

    **Within one directory nothing changed** — the pre-seam-P
    warn-and-overwrite behaviour for two files in the same dir is untouched.
    Un-bound, un-env'd processes scan the two GLOBAL library locations since
    arXiv P1 (resolved library + legacy checkout), so a ``model_type``
    hand-copied into both now refuses here too — deliberately: promotion
    never creates that state (same-name promotion is an idempotent skip
    across both locations), and silently resolving it by scan order is the
    exact failure this function exists to prevent.
    """
    if len(scanned) < 2:
        return
    ambiguous = {
        model_type: sorted(set(dirs)) for model_type, dirs in origins.items() if len(set(dirs)) > 1
    }
    if not ambiguous:
        return
    from ml_models.plugin_binding import ModelPluginResolutionError

    raise ModelPluginResolutionError(
        f"model type(s) {sorted(ambiguous)} are produced by more than one "
        f"scanned plugin directory: {ambiguous}. Which implementation would "
        f"execute depends on scan order, so the scan REFUSES instead of "
        f"letting the last one win. Scanned, in order: {scanned}."
    )


def extend_registries(model_registry: dict, config_registry: dict) -> list:
    """
    Scan the resolved plugin directories (see ``_resolve_plugin_dirs``)
    and extend both registries in-place. Also populates
    ``PLUGIN_OUTPUT_TYPE_REGISTRY``.

    Returns the list of successfully loaded plugin ``model_type`` strings,
    in the order they were loaded across all scanned directories. When the
    same ``model_type`` appears twice within ONE directory, the later file's
    plugin overwrites the earlier one (matching the existing shadow-warning
    behavior); when it appears in more than one directory the scan REFUSES —
    see :func:`_refuse_ambiguous_origins`.
    """
    loaded = []
    from core.local_code import bootstrap_code_package, scan_candidate_allowed

    bootstrap_code_package()
    scanned = _resolve_plugin_dirs()
    origins: dict[str, list[str]] = {}
    for plugin_dir in scanned:
        if not os.path.isdir(plugin_dir):
            continue

        for fname in sorted(os.listdir(plugin_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue

            path = os.path.join(plugin_dir, fname)
            if not scan_candidate_allowed(path):
                continue
            plugin = _load_plugin(path)
            if plugin is None:
                continue

            model_type = plugin["model_type"]
            if model_type in model_registry:
                print(
                    f"[PluginLoader] Warning: plugin '{model_type}' shadows an existing registry entry."
                )

            origins.setdefault(model_type, []).append(plugin_dir)
            model_registry[model_type] = plugin["model_class"]
            config_registry[model_type] = plugin["config_class"]
            PLUGIN_OUTPUT_TYPE_REGISTRY[model_type] = plugin["output_type"]
            loaded.append(model_type)
            print(f"[PluginLoader] Loaded plugin: '{model_type}' from {fname}")

    _refuse_ambiguous_origins(origins, scanned)
    return loaded


class UnknownOutputContractError(LookupError):
    """A model's output contract is not established in either registry.

    V21 PR C1. This is deliberately an exception and not a return value.
    Reaching a site that *needs* a concrete output contract while the model
    is registered nowhere is a **registration / transport invariant
    failure**, not an expected workflow outcome — the model was supposed to
    be registered before anything asked for its contract.

    Before C1 this case silently returned ``"classifier"``. That converted
    an infrastructure failure into *wrong scientific semantics*: a
    regressor whose declaration was dropped anywhere upstream was trained,
    inferred and scored as a classifier, with nothing in the record to say
    so.

    Callers must translate this into their own layer's typed refusal — see
    the five production consumers listed in the PR C design document. It
    must never reach campaign level as a raw exception, and it must never
    be caught and converted back into a default contract.

    Attributes:
        model_type: the name whose contract could not be established.
    """

    def __init__(self, model_type: str) -> None:
        self.model_type = model_type
        super().__init__(
            f"Output contract not established for model_type {model_type!r}: "
            f"registered in neither BUILTIN_OUTPUT_TYPES nor "
            f"PLUGIN_OUTPUT_TYPE_REGISTRY. This means REGISTRATION FAILED "
            f"for this model — it does NOT mean the model is a classifier."
        )


def get_output_type(model_type: str) -> str:
    """
    Return the declared output contract for a model (built-in or plugin).

    Lookup order:
      1. BUILTIN_OUTPUT_TYPES (from models_sandbox.py)
      2. PLUGIN_OUTPUT_TYPE_REGISTRY (loaded at import time)

    Returns:
        ``"classifier"``, ``"regressor"`` or ``"hybrid"``.

    Raises:
        UnknownOutputContractError: the model is in neither registry.
            **Fails closed by design (V21 PR C1)** — there is no default.
    """
    # Lazy import to avoid circular dependency (models_sandbox imports plugin_loader)
    from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES

    if model_type in BUILTIN_OUTPUT_TYPES:
        return BUILTIN_OUTPUT_TYPES[model_type]
    if model_type in PLUGIN_OUTPUT_TYPE_REGISTRY:
        return PLUGIN_OUTPUT_TYPE_REGISTRY[model_type]
    raise UnknownOutputContractError(model_type)


# ---------------------------------------------------------------------------
# Per-file registration API (mirrors register_loss_in_memory)
# ---------------------------------------------------------------------------
#
# ``extend_registries`` above is the legacy startup-scan path — it walks
# every plugin directory and registers everything found at once. The per-
# file functions below mirror ``ml_models.loss_models_sandbox.register_loss_
# in_memory`` / ``preload_global_losses`` so the workflow can register a
# single freshly-generated model plugin without a full directory rescan,
# and so a Branch B reuse path can check membership against the same
# in-memory dicts the loss surface uses.


def register_model_in_memory(plugin_path: str) -> str | None:
    """Load a model plugin file and register its classes in the model
    registries.

    Mirrors ``ml_models.loss_models_sandbox.register_loss_in_memory`` for
    the model surface. Called by the workflow's ``_register_plugin`` after
    the model file has been mirrored into the workspace, AND by
    ``preload_global_models()`` at workflow startup.

    Updates three module-level dicts on success:
      * ``MODEL_REGISTRY``                 (model_type → model class)
      * ``PLUGIN_CONFIG_REGISTRY``         (model_type → config class)
      * ``PLUGIN_OUTPUT_TYPE_REGISTRY``    (model_type → "classifier"/...)

    Idempotency: re-registering the same ``model_type`` is allowed.
    When the new ``model_class`` differs in ``__qualname__`` from the
    already-registered one, a warning is printed (subtle bug signal — a
    plugin was reloaded with different code under the same name).

    Args:
        plugin_path: Absolute path to the model plugin ``.py`` file.

    Returns:
        The plugin's ``PLUGIN_MODEL_TYPE`` string on success, ``None`` on
        load failure (the loader logs the underlying error).
    """
    # Lazy import to avoid circular dependency with models_sandbox.
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    plugin = _load_plugin(plugin_path)
    if plugin is None:
        return None
    model_type = plugin["model_type"]
    new_cls = plugin["model_class"]
    from ml_models.plugin_binding import (
        active_run_model_plugins,
        declared_package_model,
        require_declared_model_source,
    )

    declared = declared_package_model(model_type, active_run_model_plugins())
    if declared is not None:
        require_declared_model_source(declared, plugin_path)
    existing_cls = MODEL_REGISTRY.get(model_type)
    if existing_cls is not None and getattr(existing_cls, "__qualname__", None) != getattr(
        new_cls, "__qualname__", None
    ):
        print(
            f"[ModelRegistry] Warning: re-registering model_type={model_type!r} "
            f"with a different class ({existing_cls.__qualname__} → "
            f"{new_cls.__qualname__}). Most-recent registration wins."
        )
    MODEL_REGISTRY[model_type] = new_cls
    PLUGIN_CONFIG_REGISTRY[model_type] = plugin["config_class"]
    PLUGIN_OUTPUT_TYPE_REGISTRY[model_type] = plugin["output_type"]
    return model_type


def preload_global_models() -> list[str]:
    """Load all promoted model plugins into the in-memory model registries.

    Mirrors ``ml_models.loss_models_sandbox.preload_global_losses`` for
    the model surface. Called at workflow startup so cross-process Branch B
    reuse (e.g. chain resume after restart, parallel chains hitting the
    same registry) finds previously-promoted models in-memory without
    needing ``SIDERIUS_PLUGIN_DIRS``. Idempotent — safe to call multiple
    times; ``register_model_in_memory`` handles re-registration.

    arXiv P1 — scans TWO locations, resolved library first:

      1. the resolved generated-library models dir
         (``core.generated_library.generated_models_dir()``), where every
         promotion writes now;
      2. the LEGACY CHECKOUT ``agent_generated/models``
         (``AGENT_GENERATED_DIR``) — read-only compatibility, so models
         promoted before the migration keep preloading.

    A legacy file whose BASENAME already appeared in the resolved library is
    skipped entirely — promotion names files ``{model_type}.py``, so a
    same-named pair is the same declared model and the resolved-library copy
    is authoritative. The shadow applies even when the resolved copy fails
    to load: falling back to the legacy bytes there would silently register
    a STALE implementation under the type name, when the honest outcome is
    a loud loader log line and an absent type.

    Files starting with ``_`` are skipped (template / dunder convention,
    matching the existing ``_load_plugin`` scan in ``extend_registries``).

    Returns:
        List of ``model_type`` strings successfully loaded. Empty list when
        neither directory exists or both are empty (first-run / fresh host).
    """
    from core.generated_library import generated_library_is_workspace_bound, generated_models_dir
    from core.local_code import bootstrap_code_package, scan_candidate_allowed

    bootstrap_code_package()
    loaded: list[str] = []
    seen_basenames: set[str] = set()
    model_dirs = [generated_models_dir()]
    if not generated_library_is_workspace_bound() and AGENT_GENERATED_DIR is not None:
        model_dirs.append(AGENT_GENERATED_DIR)
    for models_dir in model_dirs:
        if not os.path.isdir(models_dir):
            continue
        for fname in sorted(os.listdir(models_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            if fname in seen_basenames:
                continue  # resolved-library copy shadows the legacy one
            plugin_path = os.path.join(models_dir, fname)
            if not scan_candidate_allowed(plugin_path):
                continue
            seen_basenames.add(fname)
            model_type = register_model_in_memory(plugin_path)
            if model_type is not None:
                loaded.append(model_type)
    return loaded
