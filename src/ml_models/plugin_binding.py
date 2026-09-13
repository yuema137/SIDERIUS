# ml_models/plugin_binding.py
"""The run-scoped MODEL-PLUGIN authority (Step 12 / PR-12d, seam P).

**The gap this closes.** ``ml_models/plugin_loader.py`` already knows how to
load a model plugin from a directory; what nothing owned was *which
directories THIS RUN declares*. The answer was an ambient environment
variable, ``SIDERIUS_PLUGIN_DIRS``, that:

* **no operator or launcher surface ever set** — only the two in-process D14
  Gate harnesses did, and ``--seed_plugin_path`` exists solely on the tuner
  node's own CLI, so a composed chain had no route at all to supply a task's
  model plugin;
* was **REPLACED, not inherited, at every child spawn** — ``subprocess_env``
  assigned it while joining ``PYTHONPATH`` two lines above; and
* carried **no content identity**, so nothing could prove which
  implementation actually executed.

**What changes, and what deliberately does not.** The semantic authority
becomes a run-scoped typed binding resolved at the composition edge from the
task's own declaration. ``SIDERIUS_PLUGIN_DIRS`` survives as the **transport
encoding** — the mechanism children already read — but it stops being where
the answer lives.

This module is a thin instance of two idioms the repository already has,
never a second plugin system:

* **the run-scoped bind/active pair** (``bind_run_metric``,
  ``bind_task_data_path``, ``bind_dataset_profile``): a token-reset
  ``ContextVar``, so nested and sequential runs in one process never observe
  each other's declared set;
* **the resolved-plugin identity record** (08b's ``ResolvedHealthPlugin``,
  12bc's ``ResolvedPluginRef``): ``configured_ref`` normalized, a
  ``content_sha256`` over the bytes actually loaded, and an
  ``absolute_path`` that is diagnostics only and never part of
  :meth:`ResolvedModelPlugin.canonical_identity`. **Model plugins must not
  acquire a second, divergent identity mechanism** (§D.P), so the shape is
  the same one and the composition folds it into the SAME plugin set the
  semantic fingerprint already hashes.

**Fail-closed, by name.** A composed run declares the model types it
REQUIRES. A required type that the declared root does not produce is a named
refusal — never a silent resolution of some other implementation of that name
from ``AGENT_GENERATED_DIR``. That silent case is ``C-P56-1`` one family
over: the run would train, score and rank a model nobody declared.

**Legacy is untouched.** A run that binds nothing resolves plugins exactly as
it did before: ``SIDERIUS_PLUGIN_DIRS`` when set, otherwise
``AGENT_GENERATED_DIR``. There is no task name anywhere in this module and no
central plugin catalog: discrimination is by BINDING PRESENCE, and the
declaration belongs to the task.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict, Field

from core.local_code import (
    MemberIdentity,
    scan_candidate_allowed,
    selected_identity,
    selected_member,
)


class ModelPluginResolutionError(RuntimeError):
    """A composed run's declared model plugins could not be resolved.

    Deliberately one error type for every fail-closed branch, matching
    ``TaskCompositionError``'s reasoning: the operator question is always
    "what did the run ask for, and what was actually there", and the message
    answers it. It is a ``RuntimeError`` rather than a ``ValueError`` so a
    caller that catches broken *data* does not accidentally swallow a broken
    *declaration*.
    """


class ResolvedModelPlugin(BaseModel):
    """One model plugin a run's declaration actually loaded, with its identity.

    Mirrors 08b's ``ResolvedHealthPlugin`` and 12bc's ``ResolvedPluginRef``
    field for field, for the same reasons — this is the third instance of one
    idiom, not a third identity mechanism.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    local_code: MemberIdentity | None = None

    configured_ref: str = Field(
        description="The declared root as authored, path-normalized. Never host-anchored.",
    )
    member: str = Field(
        description="The plugin file's name within the configured root. Deterministically ordered.",
    )
    model_type: str = Field(
        description=(
            "The ``PLUGIN_MODEL_TYPE`` this file declared. Part of the identity "
            "because it is the name production resolves the implementation BY."
        ),
    )
    content_sha256: str = Field(
        description=(
            "Digest of the bytes actually loaded. This is what makes an edited "
            "plugin change the run's composition fingerprint rather than "
            "silently altering behaviour under an unchanged declaration."
        ),
    )
    absolute_path: str = Field(
        description=(
            "Where it was found on THIS host. Diagnostics only — deliberately "
            "not part of canonical_identity()."
        ),
    )

    def canonical_identity(self) -> dict[str, object]:
        """The host-independent identity the composition fingerprint hashes."""
        identity: dict[str, object] = {
            "configured_ref": self.configured_ref,
            "member": self.member,
            "model_type": self.model_type,
            "content_sha256": self.content_sha256,
        }
        if self.local_code is not None:
            identity["local_code"] = self.local_code.model_dump(mode="json")
        return identity


class RunModelPluginBinding(BaseModel):
    """What ONE run declared about its model plugins, resolved.

    ``roots`` is what crosses the process boundary; ``plugins`` is what
    actually loaded and is the provenance surface. Both are needed: the roots
    alone cannot say which implementation ran, and the identities alone
    cannot make it reachable in a child.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    roots: tuple[str, ...] = Field(
        description=(
            "Absolute directories this run declares, in declaration order. "
            "These are UNIONED into every child's transport, never assigned "
            "over what the child already had."
        ),
    )
    required_model_types: tuple[str, ...] = Field(
        description=(
            "The model types the run REQUIRES its own roots to produce. An "
            "unmet requirement is a named refusal at composition, so nothing "
            "downstream can resolve a same-named implementation from "
            "somewhere the run never declared."
        ),
    )
    plugins: tuple[ResolvedModelPlugin, ...] = Field(
        description="Every plugin the declared roots produced, in scan order.",
    )

    def canonical_identities(self) -> list[dict[str, object]]:
        """Provenance, ordered deterministically for persistence."""
        return [
            plugin.canonical_identity()
            for plugin in sorted(
                self.plugins, key=lambda plugin: (plugin.configured_ref, plugin.member)
            )
        ]


_ACTIVE_RUN_MODEL_PLUGINS: ContextVar[RunModelPluginBinding | None] = ContextVar(
    "siderius_active_run_model_plugins", default=None
)


@contextmanager
def bind_run_model_plugins(
    binding: RunModelPluginBinding | None,
) -> Iterator[RunModelPluginBinding | None]:
    """Activate a run's declared model plugins for the enclosing scope.

    ``None`` is a no-op that yields ``None``: an un-composed run, or a
    composed one that declares no model plugins, enters no context and
    behaves exactly as it did before seam P.
    """
    if binding is None:
        yield None
        return
    token = _ACTIVE_RUN_MODEL_PLUGINS.set(binding)
    try:
        yield binding
    finally:
        _ACTIVE_RUN_MODEL_PLUGINS.reset(token)


def active_run_model_plugins() -> RunModelPluginBinding | None:
    """The run's declared binding, or ``None``.

    **The ``active_*`` half of the Step-11 split**: it has NO legacy
    fallback, so the transport asks this one. A helper that quietly answered
    "the legacy directory" here would put ``AGENT_GENERATED_DIR`` into every
    un-composed child's argv-equivalent environment and change legacy
    behaviour — the exact defect R-11-13 recorded one subsystem over.
    """
    return _ACTIVE_RUN_MODEL_PLUGINS.get()


def active_run_model_plugin_roots() -> tuple[str, ...]:
    """The declared roots, or ``()`` when nothing is bound."""
    binding = active_run_model_plugins()
    return () if binding is None else binding.roots


_ACTIVE_RUN_LOSS_PLUGIN_ROOTS: ContextVar[tuple[str, ...]] = ContextVar(
    "siderius_active_run_loss_plugin_roots", default=()
)


@contextmanager
def bind_run_loss_plugin_roots(roots: tuple[str, ...] | None) -> Iterator[tuple[str, ...]]:
    """Activate a run's declared LOSS-plugin directories for the enclosing scope.

    Step 12 / PR-12d D4c, closing the *"no pack-declared loss channel"* and
    *"loss-dir discovery never sees a pack"* blockers named in A3.

    **Deliberately separate from the model-plugin binding**, and the reason is
    recorded at `core/subprocess_env.py:40-42`: the two environment variables
    were split because sharing one would mask globally-registered losses
    whenever only a model directory was set. A pack keeps its losses in the
    same *directory* as its models, but the framework must keep the two
    *channels* distinct or it silently un-registers the promoted-loss library.

    ``None`` or empty is a no-op yielding ``()`` — an un-composed run, or a
    composed one declaring no loss plugins, behaves exactly as before.
    """
    if not roots:
        yield ()
        return
    token = _ACTIVE_RUN_LOSS_PLUGIN_ROOTS.set(tuple(roots))
    try:
        yield tuple(roots)
    finally:
        _ACTIVE_RUN_LOSS_PLUGIN_ROOTS.reset(token)


def active_run_loss_plugin_roots() -> tuple[str, ...]:
    """The declared loss roots, or ``()``.

    The ``active_*`` half of the Step-11 split: NO legacy fallback, so the
    transport asks this one and an un-composed child's environment is
    unchanged.
    """
    return _ACTIVE_RUN_LOSS_PLUGIN_ROOTS.get()


def union_plugin_roots(*groups: object) -> tuple[str, ...]:
    """Merge root groups into one order-stable, de-duplicated set.

    The ONE place root-set merging is expressed, so the transport, the
    loader and the tests cannot drift into three slightly different unions.
    First occurrence wins the position; blank entries are dropped, which
    matches how shells compose path-like variables (``":a::b:"`` → ``a, b``).
    """
    merged: list[str] = []
    for group in groups:
        if group is None:
            continue
        items: tuple[str, ...]
        if isinstance(group, str):
            items = tuple(part for part in group.split(os.pathsep))
        else:
            items = tuple(str(part) for part in group)  # type: ignore[arg-type]
        for item in items:
            candidate = item.strip()
            if candidate and candidate not in merged:
                merged.append(candidate)
    return tuple(merged)


def _digest(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def resolve_declared_model_plugins(
    *,
    configured_ref: str,
    root: str,
    required_model_types: tuple[str, ...],
) -> RunModelPluginBinding:
    """Load a declared plugin root and pin what it produced. FAILS CLOSED.

    Scanning tolerance follows the established idiom exactly: a directory is
    a SCAN, so an unrelated or broken member is skipped rather than fatal
    (``extend_registries``' behaviour, and 08b's explicit rule that "scan
    tolerance is not declared-binding tolerance"). What makes that safe here
    is ``required_model_types``: if the broken member was the one the run
    needs, the requirement check below names it.

    Args:
        configured_ref: the root as authored, for host-independent identity.
        root: the absolute directory to scan.
        required_model_types: the types this root MUST produce.

    Returns:
        The resolved :class:`RunModelPluginBinding`.

    Raises:
        ModelPluginResolutionError: the root is not a directory, a required
            type is not produced by it, or a required type is produced more
            than once within it.
    """
    from ml_models.plugin_loader import register_model_in_memory

    if not os.path.isdir(root):
        raise ModelPluginResolutionError(
            f"declared model-plugin root {configured_ref!r} does not exist at "
            f"{root!r}. A composed run never falls back to the legacy global "
            f"plugin directory: doing so would run some other implementation "
            f"of the same name than the one this run declared."
        )

    resolved: list[ResolvedModelPlugin] = []
    produced_by: dict[str, list[str]] = {}
    for member in sorted(os.listdir(root)):
        if not member.endswith(".py") or member.startswith("_"):
            continue
        path = os.path.join(root, member)
        if not scan_candidate_allowed(path):
            continue
        captured = selected_member(path)
        digest = captured.pin.content_sha256 if captured is not None else _digest(path)
        model_type = register_model_in_memory(path)
        if model_type is None:
            # The loader already printed the named reason. A scanned member
            # that does not load is not something the run asked for; a
            # REQUIRED one that failed is caught by the check below.
            continue
        resolved.append(
            ResolvedModelPlugin(
                configured_ref=configured_ref,
                member=member,
                model_type=model_type,
                content_sha256=digest,
                absolute_path=path,
                local_code=selected_identity(path),
            )
        )
        produced_by.setdefault(model_type, []).append(member)

    produced = {plugin.model_type for plugin in resolved}
    missing = [name for name in required_model_types if name not in produced]
    if missing:
        raise ModelPluginResolutionError(
            f"declared model-plugin root {configured_ref!r} (at {root!r}) does "
            f"not produce required model type(s) {sorted(missing)}. It "
            f"produced {sorted(produced)}. The run REFUSES rather than "
            f"resolving a same-named implementation from anywhere it did not "
            f"declare — a silent fallback there would train, score and rank a "
            f"model nobody declared."
        )
    duplicated = {name: members for name, members in produced_by.items() if len(members) > 1}
    if duplicated:
        raise ModelPluginResolutionError(
            f"declared model-plugin root {configured_ref!r} produces the same "
            f"model type from more than one file: {duplicated}. Which "
            f"implementation ran would depend on scan order, so the "
            f"declaration is refused instead."
        )
    return RunModelPluginBinding(
        roots=(os.path.abspath(root),),
        required_model_types=required_model_types,
        plugins=tuple(resolved),
    )


def normalized_ref(ref: str) -> str:
    """Collapse an authored ref to one logical spelling.

    ``./plugins`` and ``plugins`` name the same directory and must pin the
    same identity, or a cosmetic declaration edit would invalidate a
    workspace. Same rule, same reason, as ``task_composition._normalized_ref``.
    """
    return posixpath.normpath(ref)
