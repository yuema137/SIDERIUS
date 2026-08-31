# execute_tools/health_checks/_plugin_binding.py
"""Run-scoped loading of a task's external Health plugins (Step 08b, C2).

**The one missing seam.** The model surface
(``ml_models/plugin_loader.py``) and the loss surface
(``ml_models/loss_plugin_loader.py``) already loads external Python from
config-named locations, register it into a generic registry, and fail closed
when a declared name does not resolve. Health had no such instance: the ONLY
thing that populated its registry was ``__init__._bootstrap_registry``, a
central import list — so registering a check meant editing SIDERIUS. This
module closes that gap and is deliberately a thin instance of the existing
idiom rather than a second plugin system (parent §6a.3).

**What is the same as the model/loss loaders**::

    importlib.util.spec_from_file_location(<stable name>, path)
    sys.modules[name] = module      # registered BEFORE exec, so the plugin
    spec.loader.exec_module(module) # can see its own __name__, and rolled
                                    # back on failure so a fixed plugin can
                                    # be retried in the same process
    sorted(os.listdir(dir)), skipping non-".py" and "_"-prefixed members

**What is deliberately different, and why**:

* **Config, not environment, is the semantic authority** (Q-08b-1). The
  model/loss loaders resolve directories from ``SIDERIUS_PLUGIN_DIRS`` /
  ``SIDERIUS_LOSS_DIRS``; a task's Health plugins are named by its own
  Health config. No Health env var exists, and none is needed: those two
  variables are *subprocess transport*, and Health checks run only in the
  run process — no sandbox subprocess imports this package (verified at the
  implementation head). Inventing one would create exactly the ambient
  parallel override Q-08b-1 forbids.
* **Registration is by CALL, not by module attribute.** Model and loss
  plugins declare ``PLUGIN_*`` attributes that their loader reads; a Health
  plugin instead calls the SAME PUBLIC ``register()`` the built-ins use
  (parent §6a.3), and this module learns what it produced by diffing the
  registry across the import. That means there is no new plugin-attribute
  vocabulary for an external author to get wrong, and no second registration
  path to keep in step with the first.
* **An explicitly named FILE that fails to load is FATAL** (§3.2, operator
  amendment). The existing idiom is fail-open per scanned file, which is
  right for a *scan*: an unrelated member of a directory is not something
  the task asked for. An explicitly named file is. **Scan tolerance is not
  declared-binding tolerance** — and either way, a check or provider the
  config REQUIRES that does not resolve after loading fails closed in
  Phase B (C3), not here.

**Run scope is enforced, not assumed** (§3.5). In production one process
hosts at most one run, but that is an emergent property of how entry points
happen to be written, not a guarantee — and tests run many things in one
process. So the resolved plugin set is recorded in a process-level ledger:
an identical re-load is idempotent, and a DIFFERENT set in the same process
fails closed naming both. This module owns that enforcement for 08b; Step
10/12's composition root may subsume the mechanism, provided the semantic
requirement survives — one run must never silently inherit another run's
plugin set.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import posixpath
import re
import sys
import warnings
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from execute_tools.health_checks._task_health_config import TaskHealthConfig
from execute_tools.health_checks._view_provider import HealthView, HealthViewMaterializationError
from execute_tools.health_checks.registry import (  # the plugin calls register() itself
    _PROVIDER_REGISTRY,
    _REGISTRY,
    all_registered_view_providers,
    get_view_provider,
)
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    HealthCheckContext,
    TaskHealthFacts,
)

_MODULE_NAME_PREFIX = "siderius_health_plugin_"
"""Prefix for per-plugin ``sys.modules`` names.

Distinct from ``siderius_plugin_`` (models) and the loss loader's prefix so a
model, a loss and a health plugin sharing a filename stem cannot collide. The
full name is derived from the plugin's LOGICAL ref rather than its bare stem,
so two directories each containing ``checks.py`` stay separate."""


class HealthPluginError(RuntimeError):
    """A declared Health plugin could not be loaded. Fails the run closed.

    Deliberately an exception rather than a skipped plugin: the task named
    this code, and a run that silently continued without it would evaluate a
    DIFFERENT set of gates than the one its config describes — which is the
    synthesized-evidence failure the parent §6a.5 forbids, arriving as a
    quietly healthier-looking run rather than as an error.
    """


class HealthPluginRunScopeError(HealthPluginError):
    """A second, DIFFERENT plugin set was loaded in one process.

    Registration is process-global, so allowing this would let a later run
    evaluate checks registered by an earlier one — invisible in every record,
    because the check names would resolve perfectly.
    """


class ResolvedHealthPlugin(BaseModel):
    """One plugin file that was actually resolved, with its content digest.

    The identity is CANONICAL, not host-specific (§3.6): two scientifically
    identical task packages checked out at different absolute paths must
    produce the same semantic identity, or every relocation would fail a
    resume for no scientific reason. ``absolute_path`` is therefore
    diagnostics only and is excluded from :meth:`canonical_identity`, which
    is what C4 folds into the hashed effective-config body.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    configured_ref: str = Field(
        description="The ref as authored, path-normalized. Never host-anchored.",
    )
    member: str = Field(
        default="",
        description=(
            "Relative member path within a configured DIRECTORY; empty string "
            "for a file ref. Deterministically ordered by the scan."
        ),
    )
    content_sha256: str = Field(
        description=(
            "Digest of the bytes actually loaded. This is what makes an "
            "edited plugin change the pinned run identity (§3.6) rather than "
            "silently altering behaviour under an unchanged config."
        ),
    )
    absolute_path: str = Field(
        description=(
            "Where it was found on THIS host. Diagnostics only — deliberately "
            "not part of canonical_identity()."
        ),
    )

    def canonical_identity(self) -> dict[str, str]:
        """The host-independent identity C4 hashes into the run's pin."""
        return {
            "configured_ref": self.configured_ref,
            "member": self.member,
            "content_sha256": self.content_sha256,
        }


class _RunScope(BaseModel):
    """What this process has loaded, and what it produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plugins: tuple[ResolvedHealthPlugin, ...]
    registered_checks: tuple[str, ...]
    registered_view_providers: tuple[str, ...] = ()


_RUN_SCOPE: _RunScope | None = None


class _BoundView(BaseModel):
    """A capability key resolved to the provider that will materialize it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str
    config: dict[str, Any] = Field(default_factory=dict)


_TASK_FACTS: TaskHealthFacts | None = None
"""The bound task's declared health facts for this run, when one is bound.

``None`` means no task binding was resolved and the regime-A derivation
applies — the pre-08b behaviour. Part of the same run-scoped lifecycle as
``_RUN_SCOPE`` and cleared with it."""


_VIEW_BINDINGS: dict[str, _BoundView] = {}
"""Capability key → the bound provider that serves it, for THIS run.

Empty for every pre-08b run and for TIDMAD, which binds no provider — which
is exactly why the built-in checks keep their unchanged call path. Part of
the same run-scoped lifecycle as ``_RUN_SCOPE`` and cleared with it."""


def _digest(path: str) -> str:
    return hashlib.sha256(_read_bytes(path)).hexdigest()


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _normalized_ref(ref: str) -> str:
    """Collapse an authored ref to one logical spelling.

    ``./plugins/health.py`` and ``plugins/health.py`` name the same file and
    must therefore pin the same identity; leaving both spellings alive would
    make a purely cosmetic config edit invalidate a workspace.
    """
    return posixpath.normpath(ref)


def _resolve(config: TaskHealthConfig, config_dir: str) -> tuple[ResolvedHealthPlugin, ...]:
    """Resolve and digest every declared plugin WITHOUT importing anything.

    Separated from import on purpose: the run-scope ledger has to compare the
    incoming set against the recorded one BEFORE any module executes, or a
    second run's code would already have registered itself by the time the
    conflict was detected.
    """
    resolved: list[ResolvedHealthPlugin] = []
    for ref in config.plugins:
        logical = _normalized_ref(ref.ref)
        target = os.path.normpath(os.path.join(config_dir, ref.ref))

        if ref.kind == "file":
            if not os.path.isfile(target):
                raise HealthPluginError(
                    f"Health plugin file {logical!r} declared by the task health "
                    f"config does not exist at {target!r}. An explicitly named "
                    f"plugin file is not a scan candidate — the task asked for "
                    f"this file, so skipping it would run a different set of "
                    f"gates than the config describes."
                )
            try:
                digest = _digest(target)
            except OSError as exc:
                raise HealthPluginError(
                    f"Health plugin file {logical!r} at {target!r} is unreadable: {exc}"
                ) from exc
            resolved.append(
                ResolvedHealthPlugin(
                    configured_ref=logical, content_sha256=digest, absolute_path=target
                )
            )
            continue

        if not os.path.isdir(target):
            raise HealthPluginError(
                f"Health plugin directory {logical!r} declared by the task "
                f"health config does not exist at {target!r}. Per-MEMBER "
                f"tolerance covers unrelated files inside a directory; the "
                f"directory itself is something the task explicitly named."
            )
        for name in sorted(os.listdir(target)):
            if not name.endswith(".py") or name.startswith("_"):
                continue
            member_path = os.path.join(target, name)
            if not os.path.isfile(member_path):
                continue
            try:
                digest = _digest(member_path)
            except OSError as exc:
                # Scan tolerance: an unreadable member of a directory is not
                # something the task asked for by name. Any binding that then
                # fails to resolve still fails closed in Phase B.
                warnings.warn(
                    f"[HealthPluginLoader] skipping unreadable member "
                    f"{name!r} of {logical!r}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            resolved.append(
                ResolvedHealthPlugin(
                    configured_ref=logical,
                    member=name,
                    content_sha256=digest,
                    absolute_path=member_path,
                )
            )
    return tuple(resolved)


def _module_name(plugin: ResolvedHealthPlugin) -> str:
    """A stable, unique ``sys.modules`` name derived from the LOGICAL ref.

    Derived from the ref rather than the content digest so that editing a
    plugin does not orphan its previous module entry, and rather than the
    bare filename stem so two directories each holding ``checks.py`` do not
    overwrite one another.
    """
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", f"{plugin.configured_ref}/{plugin.member}").strip("_")
    return _MODULE_NAME_PREFIX + slug


def _import_and_register(plugin: ResolvedHealthPlugin) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Execute one plugin file and report what it registered.

    Returns:
        ``(check_names, provider_ids)`` contributed by this module.

    The plugin registers through the public :func:`register`; what it
    produced is learned by DIFFING the registry across the import, so there
    is no second registration contract to keep in step with the first.

    Raises:
        HealthPluginError: the module could not be imported, or its
            registrations collided with an existing name. A collision is
            fatal rather than a warning because the alternative is a run
            where a check name silently means something other than what the
            registry says it means.
    """
    module_name = _module_name(plugin)
    spec = importlib.util.spec_from_file_location(module_name, plugin.absolute_path)
    if spec is None or spec.loader is None:
        raise HealthPluginError(
            f"Cannot resolve a module spec for Health plugin "
            f"{plugin.configured_ref!r} at {plugin.absolute_path!r}."
        )
    module = importlib.util.module_from_spec(spec)
    before = set(_REGISTRY)
    before_providers = set(_PROVIDER_REGISTRY)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        # Roll back partial registrations. A module that registered check A
        # and then raised must contribute NOTHING, or A would sit in the
        # registry able to satisfy a binding while the plugin that defines
        # its behaviour never finished executing.
        for name in set(_REGISTRY) - before:
            del _REGISTRY[name]
        for provider_id in set(_PROVIDER_REGISTRY) - before_providers:
            del _PROVIDER_REGISTRY[provider_id]
        raise HealthPluginError(
            f"Health plugin {plugin.configured_ref!r}"
            f"{'/' + plugin.member if plugin.member else ''} at "
            f"{plugin.absolute_path!r} raised while importing: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return (
        tuple(sorted(set(_REGISTRY) - before)),
        tuple(sorted(set(_PROVIDER_REGISTRY) - before_providers)),
    )


def load_task_health_plugins(
    config: TaskHealthConfig,
    config_dir: str,
) -> tuple[ResolvedHealthPlugin, ...]:
    """Load the task's declared Health plugins, once per run.

    Refs are resolved relative to ``config_dir`` — the directory holding the
    task health config — which is what lets a task package be relocated
    without changing its pinned identity.

    Args:
        config: the task's parsed Health config (Phase A already passed).
        config_dir: directory the config was read from; refs resolve against it.

    Returns:
        The resolved plugin set, in declaration order (directory members in
        deterministic sorted order). C4 folds their
        :meth:`ResolvedHealthPlugin.canonical_identity` into the pinned
        effective-config body.

    Raises:
        HealthPluginError: an explicitly named file is missing, unreadable or
            raises at import; a declared directory does not exist; a
            registration collides.
        HealthPluginRunScopeError: a DIFFERENT plugin set was already loaded
            in this process.
    """
    global _RUN_SCOPE
    resolved = _resolve(config, config_dir)

    if _RUN_SCOPE is not None:
        recorded = tuple(p.canonical_identity() for p in _RUN_SCOPE.plugins)
        incoming = tuple(p.canonical_identity() for p in resolved)
        if recorded == incoming:
            # Idempotent: re-entrant startup and resume reload the same set.
            # Compared on CANONICAL identity, so the same package resolved
            # from a different absolute path is correctly the same set.
            return _RUN_SCOPE.plugins
        raise HealthPluginRunScopeError(
            f"A different Health plugin set was already loaded in this process. "
            f"Health check registration is process-global, so continuing would "
            f"let this run evaluate checks registered by the previous one.\n"
            f"  already loaded: {[dict(i) for i in recorded]}\n"
            f"  now requested:  {[dict(i) for i in incoming]}"
        )

    registered: list[str] = []
    registered_providers: list[str] = []
    for plugin in resolved:
        try:
            checks, providers = _import_and_register(plugin)
            registered.extend(checks)
            registered_providers.extend(providers)
        except HealthPluginError:
            if plugin.member:
                # Scan tolerance, per §3.2: an unrelated member of a
                # configured DIRECTORY is not something the task named.
                warnings.warn(
                    f"[HealthPluginLoader] member {plugin.member!r} of "
                    f"{plugin.configured_ref!r} failed to load; any binding "
                    f"that needed it will fail closed at resolution.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            raise

    _RUN_SCOPE = _RunScope(
        plugins=resolved,
        registered_checks=tuple(registered),
        registered_view_providers=tuple(registered_providers),
    )
    return resolved


def loaded_plugin_set() -> tuple[ResolvedHealthPlugin, ...]:
    """The plugin set this process loaded; empty when none was loaded."""
    return () if _RUN_SCOPE is None else _RUN_SCOPE.plugins


def externally_registered_checks() -> tuple[str, ...]:
    """Check names contributed by external plugins in this process."""
    return () if _RUN_SCOPE is None else _RUN_SCOPE.registered_checks


def externally_registered_view_providers() -> tuple[str, ...]:
    """Provider ids contributed by external plugins in this process."""
    return () if _RUN_SCOPE is None else _RUN_SCOPE.registered_view_providers


# ---------------------------------------------------------------------------
# Phase B — binding resolution (Step 08b C3)
#
# Phase A accepted any syntactically valid id, because the plugin that
# registers it had not loaded. Now it has, so every DECLARED binding must
# resolve or the run fails closed.
#
# The distinction this section exists to protect: an unresolved binding is a
# CONFIGURATION ERROR, never CheckVerdict.INAPPLICABLE. Inapplicability means
# "this validly-bound question does not arise for this task"; a typo'd check
# id means "this run is not the run you configured". Collapsing them would
# turn every misconfiguration into a quietly healthier-looking result.
# ---------------------------------------------------------------------------


class HealthBindingError(RuntimeError):
    """A declared binding did not resolve after plugins loaded.

    Fails the run closed at startup, before any round. Never a Health verdict.
    """


def resolve_task_health_bindings(config: TaskHealthConfig) -> dict[str, _BoundView]:
    """Resolve every binding the task declared. Fail closed on any that does not.

    Order is deliberate — check ids, then provider ids, then capability
    exposure — so the error names the most specific thing that is wrong
    rather than a downstream symptom of it.

    Args:
        config: the task's Health config, already through Phase A. Its
            plugins must already be loaded (:func:`load_task_health_plugins`).

    Returns:
        Capability key → the bound provider serving it. Also recorded at run
        scope so the runner can materialize views without re-resolving.

    Raises:
        HealthBindingError: a roster check is not registered; a declared
            provider is not registered; two bound providers advertise one
            capability; or a check that REQUIRES a view has no provider for it.
    """
    for entry in config.roster:
        if entry.check not in _REGISTRY:
            raise HealthBindingError(
                f"Roster entry {entry.gate_id!r} names check {entry.check!r}, "
                f"which is not registered after loading the task's plugins. "
                f"Registered: {sorted(_REGISTRY)}. This is a configuration "
                f"error, not an inapplicable check — the run would silently "
                f"evaluate a different gate set."
            )

    bindings: dict[str, _BoundView] = {}
    for binding in config.providers:
        try:
            provider = get_view_provider(binding.provider_id)
        except KeyError as exc:
            raise HealthBindingError(
                f"Task health config binds view provider "
                f"{binding.provider_id!r}, which is not registered after "
                f"loading the task's plugins. Registered: "
                f"{all_registered_view_providers()}."
            ) from exc
        for capability in sorted(provider.capabilities):
            if capability in bindings:
                raise HealthBindingError(
                    f"Capability {capability!r} is advertised by two bound "
                    f"providers ({bindings[capability].provider_id!r} and "
                    f"{binding.provider_id!r}). Resolution must be "
                    f"deterministic, so this is refused rather than decided "
                    f"by binding order."
                )
            bindings[capability] = _BoundView(
                provider_id=binding.provider_id, config=binding.config
            )

    for entry in config.roster:
        declaration = getattr(_REGISTRY[entry.check], "declaration", None)
        if not isinstance(declaration, CheckInputDeclaration):
            continue
        if declaration.requires_view and declaration.consumes_view not in bindings:
            raise HealthBindingError(
                f"Check {entry.check!r} (gate {entry.gate_id!r}) requires view "
                f"capability {declaration.consumes_view!r}, which no bound "
                f"provider advertises. Bound capabilities: {sorted(bindings)}. "
                f"A check that cannot be given its inputs is a binding error, "
                f"never an inapplicable check."
            )

    global _TASK_FACTS
    _VIEW_BINDINGS.clear()
    _VIEW_BINDINGS.update(bindings)
    # The bound task's facts REPLACE the regime-A derivation for this run —
    # the call-site redirect the Step-08 parent's finding 6 names. It is a
    # call-site change, not a contract change: ``applicability`` still
    # receives one ``TaskHealthFacts``, derived or declared.
    _TASK_FACTS = config.resolved_facts()
    return dict(bindings)


def bound_task_facts() -> TaskHealthFacts | None:
    """The bound task's declared facts, or None when no task binding resolved."""
    return _TASK_FACTS


def bound_view_capabilities() -> tuple[str, ...]:
    """Capability keys a bound provider serves in this run. Empty when none."""
    return tuple(sorted(_VIEW_BINDINGS))


def materialize_view(
    declaration: CheckInputDeclaration,
    ctx: HealthCheckContext,
) -> HealthView | None:
    """Materialize a check's declared view, or None when no provider serves it.

    **Called by the runner ONLY after applicability returned applicable**
    (§3.3/§3.4). That ordering is the invariant: a provider must never have to
    open an artifact to decide whether a check applies, or 08a's whole pre-I/O
    applicability guarantee would be undone by the mechanism meant to extend it.

    Returns None — meaning "invoke the check the legacy way" — when no bound
    provider advertises the capability. That is the case for every pre-08b run
    and for TIDMAD, which binds no provider, so the seven built-ins keep their
    unchanged ``run(ctx, config)`` call path.

    Raises:
        HealthViewMaterializationError: the provider raised. The runner turns
            this into ``CheckVerdict.ERROR`` — the same verdict a raising
            check produces, because a check that could not be given its inputs
            and one that could not compute are the same thing to a gate.
    """
    bound = _VIEW_BINDINGS.get(declaration.consumes_view)
    if bound is None:
        return None
    provider = get_view_provider(bound.provider_id)
    try:
        return provider.materialize(declaration.consumes_view, ctx, bound.config or None)
    except Exception as exc:
        raise HealthViewMaterializationError(
            f"View provider {bound.provider_id!r} failed to materialize "
            f"advertised capability {declaration.consumes_view!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def reset_run_scope() -> None:
    """Forget this process's plugin set. Test-only — never call from production.

    Mirrors ``config.clear_health_gates_config_cache``. It deliberately does
    NOT unregister anything: registry restoration is the ``clean_registry``
    fixture's job, and having two mechanisms undo each other's work is how a
    test starts passing for the wrong reason.
    """
    global _RUN_SCOPE, _TASK_FACTS
    _RUN_SCOPE = None
    _TASK_FACTS = None
    _VIEW_BINDINGS.clear()
