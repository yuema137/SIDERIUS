"""The generated-capability library root — the ONE resolved authority.

arXiv P1 (user-contract audit ``docs/audit/user_contract_audit.md`` §H,
ranked gap P1): a normal SIDERIUS run used to MUTATE the repository
checkout. Four artifact families were rooted at the checkout-level
``agent_generated/`` directory:

1. the capability index (``_capability_index.json``) written by the
   implementor / workflow and read by the proposer and tuner prompts;
2. the promote-to-global copies of generated model and loss plugins
   (``_promote_model_to_global`` / ``_promote_loss_to_global``);
3. the loss-union filesystem read (``SIDERIUS_LOSS_DIRS`` ∪ global losses);
4. the legacy read fallbacks (model descriptions, plugin-loader scan,
   proposer source excerpts).

Every later run on that checkout silently absorbed the accumulated state at
startup (``preload_global_models`` / ``preload_global_losses``), so two
collaborators sharing a checkout contaminated each other's runs and a
"fresh workspace" was not fresh.

Supported workflow and standalone-node entry points bind this library to
``{workspace}/generated_library`` before constructing any consumer. The
environment variable below is the subprocess transport for that binding.
Low-level callers that bypass those entry points retain the historical
two-layer resolution during migration::

    SIDERIUS_GENERATED_LIBRARY_DIR   (absolute path; ``~`` expanded)
        ->
    ~/.siderius/generated_library    (the ``~/.siderius`` durable-state
                                      precedent set by
                                      agent/skills/evaluate_time_skill/
                                      calibration.py)

An empty or whitespace-only override is treated as UNSET — the established
convention of this env-var family (``SIDERIUS_CALIBRATION_DIR``,
``SIDERIUS_LOSS_DIRS``, ``SIDERIUS_PLUGIN_DIRS`` all treat empty as
absent). A NON-empty relative path is REFUSED loudly: resolving it against
the current working directory would make the library location depend on
where the process was launched — and a run started inside the checkout
would silently recreate the exact checkout pollution this module exists to
remove.

Layout under the resolved root mirrors the legacy checkout layout so every
consumer keeps its shape::

    {root}/models/                  promoted model plugins (+ description
                                    subdirs: ``{model_type}/description.md``)
    {root}/losses/                  promoted loss plugins
    {root}/_capability_index.json   the capability index

**Legacy checkout artifacts stay READABLE only for unbound low-level
callers.** Each consumer keeps its
checkout-level location as a lower-priority read fallback (the constants
``ml_models.plugin_loader.AGENT_GENERATED_DIR``,
``ml_models.loss_plugin_loader.LOSSES_DIR``,
``core.capability_registry._LEGACY_CHECKOUT_INDEX_PATH``, …). A supported
workspace-bound execution excludes these fallbacks, so a fresh workspace
cannot absorb checkout history. No production path WRITES to the checkout
root — continued repository-root writes are deliberately not preserved for
compatibility.

Resolution happens at CALL time (no import-time cache), matching
``calibration_dir()`` — a test that sets the env var, and an operator who
exports it between runs, both see the updated value.

The resolved root is RECORDED as provenance, never compared:
``generated_library_provenance()`` feeds the run-invariants lock's
``generated_library`` field (``RunInvariants._PROVENANCE``) — same science,
different host layout, exactly the ``execution_calibration`` precedent.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The env override. Named once — every consumer resolves through this
#: module, never by reading the variable itself.
GENERATED_LIBRARY_ENV_VAR = "SIDERIUS_GENERATED_LIBRARY_DIR"

#: Workspace-relative directory used by workflow and standalone-node entry
#: points. The environment variable remains the subprocess transport, but the
#: configured workspace is the authority that chooses its value.
_WORKSPACE_LIBRARY_BASENAME = "generated_library"
_CHAIN_WORKSPACE_ENV_VAR = "SIDERIUS_CHAIN_WORKSPACE"

#: Default root, relative to the user's home: ``~/.siderius/generated_library``.
#: Nested under the same ``~/.siderius`` home the time-calibration store
#: already uses, so SIDERIUS's durable per-user state lives in one place.
_DEFAULT_ROOT_HOME_RELATIVE = os.path.join(".siderius", "generated_library")

#: Basename of the capability index inside the library root. Kept identical
#: to the legacy checkout basename so an operator inspecting either location
#: sees the same file name.
_CAPABILITY_INDEX_BASENAME = "_capability_index.json"


class MalformedGeneratedLibraryOverride(ValueError):
    """``SIDERIUS_GENERATED_LIBRARY_DIR`` was set to something unusable.

    A dedicated type (the ``MalformedCeilingOverride`` precedent): an
    operator who sets the variable to a relative path has stated an
    intention that would resolve DIFFERENTLY depending on the launch
    directory. Silently anchoring it to the cwd could re-point the library
    into the repository checkout — the exact pollution this module removes —
    so the resolution refuses instead.
    """


class GeneratedLibraryResolution(BaseModel):
    """Where the generated-capability library root resolved, and from what.

    Fields:
        root: Absolute path of the resolved library root. The directory is
            NOT created by resolution — writers ``os.makedirs`` on demand
            and readers skip a missing directory, exactly as the legacy
            checkout paths behaved.
        source: ``"env"`` when :data:`GENERATED_LIBRARY_ENV_VAR` supplied
            the root, ``"default"`` for ``~/.siderius/generated_library``.
    """

    model_config = ConfigDict(frozen=True)

    root: str = Field(min_length=1, description="Absolute library root path.")
    source: Literal["env", "default"] = Field(description="Which layer resolved the root.")


def resolve_generated_library(
    *, environ: Mapping[str, str] | None = None
) -> GeneratedLibraryResolution:
    """Resolve the generated-capability library root — two layers, no third.

    Args:
        environ: Environment mapping to read; defaults to ``os.environ``.
            ``Mapping`` rather than ``dict`` because ``os.environ`` is a
            ``Mapping`` (the ``resolve_role_ceiling_gb`` precedent). An
            explicit parameter so a caller can resolve against a
            transported environment rather than the ambient one.

    Returns:
        The resolved root with its provenance source.

    Raises:
        MalformedGeneratedLibraryOverride: the override is set to a
            non-empty RELATIVE path (after ``~`` expansion).
    """
    env = os.environ if environ is None else environ
    raw = (env.get(GENERATED_LIBRARY_ENV_VAR) or "").strip()
    if not raw:
        return GeneratedLibraryResolution(
            root=os.path.join(os.path.expanduser("~"), _DEFAULT_ROOT_HOME_RELATIVE),
            source="default",
        )
    expanded = os.path.expanduser(raw)
    if not os.path.isabs(expanded):
        raise MalformedGeneratedLibraryOverride(
            f"{GENERATED_LIBRARY_ENV_VAR}={raw!r} is a relative path. A relative "
            f"library root would resolve against the process working directory — "
            f"launched from the repository checkout it would write generated "
            f"artifacts back INTO the checkout, which is the pollution this "
            f'setting exists to prevent. Set an absolute path ("~" is expanded), '
            f"or unset the variable to use ~/.siderius/generated_library."
        )
    return GeneratedLibraryResolution(root=os.path.normpath(expanded), source="env")


def generated_library_root(*, environ: Mapping[str, str] | None = None) -> str:
    """The resolved library root path (see :func:`resolve_generated_library`)."""
    return resolve_generated_library(environ=environ).root


def bind_generated_library_to_workspace(
    workspace: str,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> str:
    """Bind generated-capability discovery and writes to ``workspace``.

    Full workflow entry points call this before constructing a registry or
    resolving run invariants. Descendant subprocesses inherit the existing
    environment transport, while the path itself is deterministically derived
    from the user-configured workspace.
    """
    env = os.environ if environ is None else environ
    root = os.path.abspath(os.path.join(workspace, _WORKSPACE_LIBRARY_BASENAME))
    env[GENERATED_LIBRARY_ENV_VAR] = root
    env[_CHAIN_WORKSPACE_ENV_VAR] = os.path.abspath(workspace)
    return root


def generated_library_is_workspace_bound(*, environ: Mapping[str, str] | None = None) -> bool:
    """Whether a workflow entry point bound discovery to its workspace."""
    env = os.environ if environ is None else environ
    workspace = (env.get(_CHAIN_WORKSPACE_ENV_VAR) or "").strip()
    root = (env.get(GENERATED_LIBRARY_ENV_VAR) or "").strip()
    if not workspace or not root:
        return False
    expected = os.path.abspath(os.path.join(workspace, _WORKSPACE_LIBRARY_BASENAME))
    return os.path.abspath(os.path.expanduser(root)) == expected


def generated_models_dir(*, environ: Mapping[str, str] | None = None) -> str:
    """``{root}/models`` — promoted model plugins and their description subdirs."""
    return os.path.join(generated_library_root(environ=environ), "models")


def generated_losses_dir(*, environ: Mapping[str, str] | None = None) -> str:
    """``{root}/losses`` — promoted loss plugins."""
    return os.path.join(generated_library_root(environ=environ), "losses")


def capability_index_path(*, environ: Mapping[str, str] | None = None) -> str:
    """``{root}/_capability_index.json`` — the capability index."""
    return os.path.join(generated_library_root(environ=environ), _CAPABILITY_INDEX_BASENAME)


def generated_library_provenance(*, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """What this run resolves the library to, for the run-invariants lock.

    **Recorded, never equality-enforced.** The library root is execution-HOST
    layout, not task semantics: the same scientific run resumed on a host
    whose library lives elsewhere must remain legal (promoted capabilities
    are still discoverable through the read-priority chain), unlike a
    composition, metric or dataset-semantics change. ``RunInvariants``
    therefore declares the ``generated_library`` field as PROVENANCE — the
    ``execution_calibration`` precedent, R-11-6's representation rule.

    The shape is deliberately flat and JSON-native so an auditor reading a
    lock file needs no code to interpret it.
    """
    resolution = resolve_generated_library(environ=environ)
    return {"root": resolution.root, "source": resolution.source}
