"""``RunTaskComposition`` — the ONE run-scoped task-composition authority.

Step 10 / P1 (design
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/pr_10_p1_run_scoped_task_composition.md``).

THE PROBLEM THIS OWNS
---------------------
Before P1, a run discovered what task it was running by *not deciding*: five
independent implicit defaults, one per semantic family, each quietly resolving
TIDMAD — a registry compatibility id, an ``or`` fallback, an omitted keyword,
an unconditional derivation and a default-path constant. Nothing bound them,
so nothing could bind them to anything else, and the two contrast tasks
executed through hand-written Gate scripts instead of the loop.

This module is the one place a run's task semantics are RESOLVED, and its
only semantic owner is exactly that: **run-scoped task composition**.

WHAT IT IS NOT
--------------
* not a ``WorkflowContext`` and not a bag of launch/transit values — every
  field is one existing subsystem's own already-validated type;
* not a service locator — nothing here has mutable state or a lifecycle this
  module drives;
* not ``ChainState`` — the ownership guard refuses any field name the mutable
  cross-iteration carrier declares;
* not a task registry and not a ``TASKS = {...}`` table — there is no mapping
  from task identity to behaviour anywhere in this file. A composition names
  FILES and SYMBOLS; the framework never learns what "tidmad" or "pets"
  means;
* not a second copy of any family's semantics — the profile loader, the
  metric spec authority, the Health binding states, the interpretation-blocks
  loader and the forward-contract validator are all CALLED, never
  reimplemented.

FAIL-CLOSED, ALWAYS
-------------------
An explicitly composed run never falls back to TIDMAD. A missing manifest, an
unknown key, a misspelled ref, a plugin that raises, a declaration whose
metric id disagrees with its implementation — each raises
:class:`TaskCompositionError` naming what was found and what was expected. The
legacy defaults remain reachable only by *not composing at all*, which is the
bounded compatibility path Step 12 removes.

TWO IDENTITIES, DELIBERATELY SEPARATE
-------------------------------------
``semantic_fingerprint`` is what a composed run pins into
``run_invariants_lock.json``: a digest over resolved semantic VALUES,
declaration CONTENTS and plugin CONTENT digests. It excludes every
machine-local absolute path, so the same task package checked out somewhere
else is the same scientific run. ``provenance`` carries those paths for
diagnostics and is never hashed into the lock. Conflating them would make a
relocation look like a semantic change and fail a resume for no scientific
reason (design §5.9, Q-P1-2).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import posixpath
import re
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any, cast

import yaml

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.schemas.interpretation import InterpretationTaskBlocks
    from agent.schemas.task_config import ForwardContract
    from execute_tools.dataset_config import DatasetProfile
    from execute_tools.evaluation_metric import EvaluationMetric
    from execute_tools.health_checks._composition import TaskHealthBinding
    from execute_tools.task_data_path import TaskDataPath

_MODULE_NAME_PREFIX = "siderius_task_composition_plugin_"
"""Prefix for per-plugin ``sys.modules`` names.

Distinct from the model (``siderius_plugin_``), loss and Health
(``siderius_health_plugin_``) prefixes, so a task package whose files share a
filename stem with one of those cannot collide with it."""

#: The manifest's complete top-level key set. Unknown keys are refused rather
#: than ignored: a misspelled section is the failure mode a composition exists
#: to prevent, and silently dropping it would resolve the family from its
#: legacy default — the silent-TIDMAD outcome in a new disguise.
_MANIFEST_KEYS = frozenset(
    {
        "task_data_path",
        "dataset_profile",
        "metric",
        "task_health",
        "interpretation_blocks",
        "task_config",
    }
)

#: Sections a manifest must state. Health is REQUIRED-as-a-statement rather
#: than required-as-a-path: a task with no Health family says ``none``, which
#: is 08b's ``EXPLICIT_NONE`` — a named absence. What a composition can never
#: express is ``LEGACY_OMITTED``, because "I said nothing" is precisely the
#: state that resolves TIDMAD's config (design §4).
_REQUIRED_KEYS = frozenset(
    {"task_data_path", "dataset_profile", "metric", "task_health", "task_config"}
)


class TaskCompositionError(ValueError):
    """A run composition could not be resolved. The run does not start.

    Deliberately one error type for every fail-closed branch: the operator
    question is always the same ("what did the composition ask for, and what
    was actually there"), and the message answers it. Subclassing per branch
    would invite ``except`` clauses that treat one class of broken
    composition as recoverable.
    """


@dataclass(frozen=True, slots=True)
class ResolvedPluginRef:
    """One plugin file the composition loaded, with its CONTENT identity.

    Mirrors 08b's ``ResolvedHealthPlugin`` deliberately (same idiom, same
    reasons): ``configured_ref`` is the authored spelling normalized to one
    logical form, ``content_sha256`` is what makes an edited plugin change
    the run identity, and ``absolute_path`` is where it happened to live on
    THIS host — diagnostics only, and never part of
    :meth:`canonical_identity`.
    """

    configured_ref: str
    symbol: str
    content_sha256: str
    absolute_path: str

    def canonical_identity(self) -> dict[str, str]:
        """The host-independent identity the semantic fingerprint hashes."""
        return {
            "configured_ref": self.configured_ref,
            "symbol": self.symbol,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class CompositionProvenance:
    """Where this composition came from, on this host. DIAGNOSTIC ONLY.

    Never hashed into :attr:`RunTaskComposition.semantic_fingerprint`: it is
    full of absolute paths, and a task package that moved directories is the
    same science (design §5.9).
    """

    manifest_path: str
    source_paths: dict[str, str] = field(default_factory=dict)
    plugins: tuple[ResolvedPluginRef, ...] = ()


@dataclass(frozen=True, slots=True)
class RunTaskComposition:
    """The typed, immutable set of task authorities ONE run is bound to.

    Every field is an existing subsystem's own type, already validated by
    that subsystem's own authority. This carrier composes them; it owns none
    of their semantics.

    ``task_data_path`` holds the **RESOLVED implementation object**, not an
    id (design §5.2a). The implementation's own declared
    ``task_data_path_id`` is read FROM it for subprocess transport,
    provenance and the fingerprint — so there is exactly one semantic
    resolution, at the composition edge, and no downstream id→implementation
    lookup anywhere in the parent process.
    """

    task_data_path: TaskDataPath
    dataset_profile: DatasetProfile
    metric: EvaluationMetric
    task_health_binding: TaskHealthBinding
    interpretation_blocks: InterpretationTaskBlocks | None
    task_description: str
    forward_contract: ForwardContract
    semantic_fingerprint: str
    provenance: CompositionProvenance

    def __post_init__(self) -> None:
        """Refuse mutable cross-iteration state, by DERIVED name set.

        The same guard ``WorkflowRunBindings`` carries, for the same reason
        and with the same derivation: a hand-maintained deny list goes stale
        the first time ``ChainState`` grows, and the field it fails to name
        is exactly the one that would leak.
        """
        from core.chain_state import chain_state_field_names

        offending = sorted(chain_state_field_names() & {f.name for f in dataclass_fields(self)})
        if offending:
            raise TypeError(
                f"RunTaskComposition must not carry mutable chain state: {offending}. "
                "A composition holds task authorities settled once at the "
                "composition edge; values that evolve as iterations complete "
                "belong to ChainState."
            )

    @property
    def task_data_path_id(self) -> str:
        """The resolved implementation's OWN declared id.

        Transport and provenance identity — never a lookup key the parent
        turns back into an implementation.
        """
        return self.task_data_path.task_data_path_id

    def task_config_values(self) -> dict[str, Any]:
        """The composed values in the shape ``load_task_config`` returns.

        Derived from the two frozen fields rather than stored, so the mapping
        handed to consumers cannot drift from the validated values this
        composition resolved.

        Extra top-level keys that ``load_task_config`` would pass through
        verbatim are deliberately NOT carried: the two keys below are the
        ones the loader validates and the only ones any consumer reads
        (measured across production at the P1 implementation head). Carrying
        an unvalidated grab-bag would make the composition a config bag,
        which §4 rejects.
        """
        return {
            "task_description": self.task_description,
            "forward_contract": self.forward_contract.model_dump(mode="json"),
        }


def composition_field_names() -> frozenset[str]:
    """The carrier's field names — used by the structural censuses."""
    return frozenset(f.name for f in dataclass_fields(RunTaskComposition))


# ---------------------------------------------------------------------------
# Manifest reading — every branch fails closed
# ---------------------------------------------------------------------------


def _read_manifest(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise TaskCompositionError(
            f"task composition manifest not found at {path!r}. A composition "
            "was explicitly requested, so this fails closed rather than "
            "resolving the legacy defaults — a silent fallback would run a "
            "different task than the one the operator named."
        )
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except OSError as exc:
        raise TaskCompositionError(
            f"task composition manifest at {path!r} is unreadable ({exc})."
        ) from exc
    except yaml.YAMLError as exc:
        raise TaskCompositionError(
            f"task composition manifest at {path!r} is not valid YAML ({exc})."
        ) from exc

    if not isinstance(raw, dict):
        raise TaskCompositionError(
            f"task composition manifest at {path!r} must be a YAML mapping; "
            f"got {type(raw).__name__}."
        )

    unknown = sorted(set(raw) - _MANIFEST_KEYS)
    if unknown:
        raise TaskCompositionError(
            f"task composition manifest at {path!r} declares unknown key(s) "
            f"{unknown}; known keys are {sorted(_MANIFEST_KEYS)}. An unknown "
            "key is refused rather than ignored: a misspelled section would "
            "otherwise leave its family resolving the legacy default."
        )
    missing = sorted(_REQUIRED_KEYS - set(raw))
    if missing:
        raise TaskCompositionError(
            f"task composition manifest at {path!r} is missing required "
            f"section(s) {missing}. Every semantic family must be stated — a "
            "family a composition does not mention is a family that would "
            "silently resolve the framework's legacy compatibility default, "
            "which belongs to a different task than the one being composed."
        )
    return raw


def _section(raw: dict[str, Any], key: str, manifest_path: str) -> dict[str, Any]:
    value = raw[key]
    if not isinstance(value, dict):
        raise TaskCompositionError(
            f"section {key!r} in {manifest_path!r} must be a mapping; got {type(value).__name__}."
        )
    return value


def _require(section: dict[str, Any], key: str, where: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TaskCompositionError(f"{where} requires a non-empty string {key!r}; got {value!r}.")
    return value


def _resolve_path(ref: str, manifest_dir: str) -> str:
    """Refs are relative to the MANIFEST's directory, never to the cwd.

    A task package must be movable and must compose identically regardless of
    where the process happens to be launched from.
    """
    return ref if os.path.isabs(ref) else os.path.normpath(os.path.join(manifest_dir, ref))


def _normalized_ref(ref: str) -> str:
    """Collapse an authored ref to one logical spelling.

    ``./plugins/x.py`` and ``plugins/x.py`` name the same file and must pin
    the same identity, or a cosmetic config edit would invalidate a
    workspace (08b §3.6, same reasoning).
    """
    return posixpath.normpath(ref)


def _digest_file(path: str, what: str) -> str:
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError as exc:
        raise TaskCompositionError(f"{what} at {path!r} is unreadable ({exc}).") from exc


def _read_json(path: str, what: str) -> Any:
    if not os.path.isfile(path):
        raise TaskCompositionError(f"{what} not found at {path!r}.")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise TaskCompositionError(f"{what} at {path!r} is unreadable ({exc}).") from exc
    except json.JSONDecodeError as exc:
        raise TaskCompositionError(f"{what} at {path!r} is not valid JSON ({exc}).") from exc


# ---------------------------------------------------------------------------
# Symbol resolution — a FILE ref or an importable MODULE ref, never a table
# ---------------------------------------------------------------------------


def _module_name(logical_ref: str, symbol: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", f"{logical_ref}/{symbol}").strip("_")
    return _MODULE_NAME_PREFIX + slug


def _load_symbol(
    section: dict[str, Any], manifest_dir: str, where: str
) -> tuple[Any, ResolvedPluginRef | None]:
    """Resolve ``{file, symbol}`` or ``{module, symbol}`` to a live object.

    Two forms, one mechanism, and no per-task knowledge in either:

    * ``file:`` — an OUT-OF-TREE plugin, executed by path exactly the way the
      model, loss and Health plugin loaders execute theirs. This is the form
      that makes a fourth task need zero framework edits, and it is the form
      whose CONTENT digest joins the semantic fingerprint.
    * ``module:`` — an importable dotted module, for implementations that
      already ship with the framework (the three built-in metrics, the
      shipped data-path implementations). A dotted name the manifest supplies
      is still the task naming its own binding; the framework holds no
      mapping from task identity to symbol.

    Returns ``(object, resolved_ref_or_None)``. The ref is ``None`` for the
    module form: an in-tree module has no content digest to pin that the
    repository's own commit does not already pin.
    """
    symbol = _require(section, "symbol", where)
    file_ref = section.get("file")
    module_ref = section.get("module")

    if (file_ref is None) == (module_ref is None):
        raise TaskCompositionError(
            f"{where} must declare exactly ONE of 'file' (an out-of-tree "
            f"plugin path) or 'module' (an importable dotted module); got "
            f"file={file_ref!r}, module={module_ref!r}."
        )

    if module_ref is not None:
        if not isinstance(module_ref, str) or not module_ref.strip():
            raise TaskCompositionError(
                f"{where} requires a non-empty string 'module'; got {module_ref!r}."
            )
        try:
            module = importlib.import_module(module_ref)
        except Exception as exc:
            raise TaskCompositionError(
                f"{where} names module {module_ref!r}, which could not be "
                f"imported: {type(exc).__name__}: {exc}"
            ) from exc
        return _getattr_or_fail(module, symbol, where, module_ref), None

    if not isinstance(file_ref, str) or not file_ref.strip():
        raise TaskCompositionError(f"{where} requires a non-empty string 'file'; got {file_ref!r}.")
    logical = _normalized_ref(file_ref)
    target = _resolve_path(file_ref, manifest_dir)
    if not os.path.isfile(target):
        raise TaskCompositionError(
            f"{where} names plugin file {logical!r}, which does not exist at "
            f"{target!r}. An explicitly named plugin file is not a scan "
            "candidate — the composition asked for this file."
        )
    digest = _digest_file(target, f"{where} plugin file {logical!r}")

    module_name = _module_name(logical, symbol)
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise TaskCompositionError(
            f"{where}: cannot resolve a module spec for plugin {logical!r} at {target!r}."
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        # Roll back so a corrected plugin can be retried in the same process
        # (the 08b idiom) — a half-executed module left in sys.modules would
        # satisfy the next import while never having finished running.
        sys.modules.pop(module_name, None)
        raise TaskCompositionError(
            f"{where}: plugin {logical!r} at {target!r} raised while "
            f"importing: {type(exc).__name__}: {exc}"
        ) from exc

    resolved = ResolvedPluginRef(
        configured_ref=logical,
        symbol=symbol,
        content_sha256=digest,
        absolute_path=target,
    )
    return _getattr_or_fail(module, symbol, where, logical), resolved


def _getattr_or_fail(module: Any, symbol: str, where: str, origin: str) -> Any:
    try:
        return getattr(module, symbol)
    except AttributeError as exc:
        available = sorted(n for n in vars(module) if not n.startswith("_"))
        raise TaskCompositionError(
            f"{where}: {origin!r} defines no symbol {symbol!r}. Available: {available}."
        ) from exc


# ---------------------------------------------------------------------------
# Per-family resolution
# ---------------------------------------------------------------------------


def _compose_task_data_path(
    section: dict[str, Any], manifest_dir: str
) -> tuple[TaskDataPath, ResolvedPluginRef | None]:
    """Load the implementation, register it if new, and return the OBJECT.

    Registration is the existing public registry's own call, so a duplicate
    id is refused by the authority that owns ids rather than by a second
    opinion here.

    Re-composing the same task twice in one process (tests, sequential runs)
    is idempotent, and it returns the **registered** instance rather than the
    freshly constructed one. That is not a detail: the child process resolves
    a transported id through the registry, so if the parent bound a second
    instance of the same class the two ends would hold different objects
    while every id-based check still passed. One id, one object.
    """
    from execute_tools.task_data_path import (
        TaskBindingContext,
        TaskDataPathRegistrationError,
        register_task_data_path,
        registered_task_data_path_ids,
        resolve_task_data_path,
    )

    where = "task_data_path"
    factory, plugin_ref = _load_symbol(section, manifest_dir, where)
    resolved: Any = (
        factory() if callable(factory) and not _looks_like_instance(factory) else factory
    )

    declared = getattr(resolved, "task_data_path_id", None)
    if not isinstance(declared, str) or not declared:
        raise TaskCompositionError(
            f"{where}: the resolved implementation declares no non-empty "
            f"string 'task_data_path_id'; got {declared!r}. The id is the "
            "implementation's own property — a composition never assigns it."
        )

    expected = section.get("id")
    if expected is not None and expected != declared:
        raise TaskCompositionError(
            f"{where}: the manifest expects id {expected!r} but the resolved "
            f"implementation declares {declared!r}. The implementation is the "
            "authority on its own id; the manifest's value is a cross-check, "
            "and a mismatch means the composition names something other than "
            "what it thinks it names."
        )

    if declared in registered_task_data_path_ids():
        return resolve_task_data_path(TaskBindingContext(task_data_path_id=declared)), plugin_ref

    # A plugin's symbol is `Any` by construction — it came from a file this
    # module executed. The narrowing is DISCHARGED on the very next line:
    # `register_task_data_path` validates all four protocol methods and
    # refuses a malformed implementation before any execution. Re-checking
    # the method list here would put a second copy of the protocol's own
    # definition in this module, which is exactly what §2.5 forbids.
    impl = cast("TaskDataPath", resolved)
    try:
        register_task_data_path(impl)
    except TaskDataPathRegistrationError as exc:
        raise TaskCompositionError(f"{where}: {exc}") from exc
    return impl, plugin_ref


def _looks_like_instance(candidate: Any) -> bool:
    """A resolved symbol may be a CLASS or an already-built instance.

    Classes are callable, so ``callable()`` alone cannot tell them apart from
    a factory; an instance that declares the protocol's id attribute on
    itself is taken as already built.
    """
    return not isinstance(candidate, type) and hasattr(candidate, "task_data_path_id")


def _compose_metric(
    section: dict[str, Any], manifest_dir: str
) -> tuple[EvaluationMetric, dict[str, Any], ResolvedPluginRef | None]:
    """Declaration JSON → ``MetricSpec`` → the declared implementation.

    The spec comes from ``metric_spec_from_declaration`` — the ONE
    spec-from-declaration authority (Step 06) — so this module adds no second
    way for a metric identity to come into existence.
    """
    from execute_tools.evaluation_metric import EvaluationMetric, metric_spec_from_declaration

    where = "metric"
    declaration_ref = _require(section, "declaration", where)
    declaration_path = _resolve_path(declaration_ref, manifest_dir)
    payload = _read_json(declaration_path, f"{where} declaration")
    if not isinstance(payload, dict):
        raise TaskCompositionError(
            f"{where} declaration at {declaration_path!r} must be a JSON "
            f"object; got {type(payload).__name__}."
        )
    try:
        spec = metric_spec_from_declaration(payload)
    except Exception as exc:
        raise TaskCompositionError(
            f"{where} declaration at {declaration_path!r} is not a valid "
            f"MetricSpec: {type(exc).__name__}: {exc}"
        ) from exc

    implementation = section.get("implementation")
    if not isinstance(implementation, dict):
        raise TaskCompositionError(
            f"{where} requires an 'implementation' mapping naming the "
            f"EvaluationMetric to instantiate; got {implementation!r}."
        )
    metric_cls, plugin_ref = _load_symbol(implementation, manifest_dir, f"{where}.implementation")
    try:
        metric = metric_cls(spec)
    except Exception as exc:
        raise TaskCompositionError(
            f"{where}.implementation could not be instantiated with the "
            f"declared spec: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(metric, EvaluationMetric):
        raise TaskCompositionError(
            f"{where}.implementation resolved to {type(metric).__name__}, "
            "which is not an EvaluationMetric. The metric handle is the ONE "
            "scoring contract (Step 06); a composition may choose which "
            "instance, never a different contract."
        )
    if metric.spec.id != spec.id:
        raise TaskCompositionError(
            f"{where}: the declaration declares id {spec.id!r} but the "
            f"instantiated metric reports {metric.spec.id!r}. An implementation "
            "that rewrites its own spec breaks the declaration's authority."
        )
    return metric, payload, plugin_ref


def _compose_task_health(section: dict[str, Any], manifest_dir: str) -> TaskHealthBinding:
    """08b's binding STATES, minus the one a composition may not express.

    ``LEGACY_OMITTED`` means "the caller said nothing", which is precisely
    the state that resolves TIDMAD's task health config. A composition that
    could express it would be able to compose a Pets run that silently used
    TIDMAD's roster and thresholds, so it is unreachable here by
    construction: a manifest states either a path or ``none``
    (``EXPLICIT_NONE``, a NAMED absence).
    """
    from execute_tools.health_checks._composition import HealthBindingState

    where = "task_health"
    if section.get("none") is True:
        if "config" in section:
            raise TaskCompositionError(
                f"{where} declares both 'none: true' and a 'config' path. A "
                "task either has a Health family or explicitly has none."
            )
        return HealthBindingState.EXPLICIT_NONE

    config_ref = _require(section, "config", f"{where} (without 'none: true')")
    config_path = _resolve_path(config_ref, manifest_dir)
    if not os.path.isfile(config_path):
        raise TaskCompositionError(
            f"{where} config not found at {config_path!r}. A composed run "
            "never falls back to another task's Health family — declare "
            "'none: true' if this task has none."
        )
    return config_path


def _compose_interpretation_blocks(
    raw: dict[str, Any], manifest_dir: str
) -> tuple[InterpretationTaskBlocks | None, str | None]:
    """Optional by design: an absent declaration renders NOTHING (09b).

    Unlike Health, the absence here needs no ceremony — 09b already made "no
    task blocks" a legal state that produces no header and no bytes. What is
    NOT legal is a declared path that does not load; the existing loader
    fails closed and this propagates it.
    """
    from agent.prompt_templates.interpretation.task_blocks import (
        load_interpretation_task_blocks,
    )

    section = raw.get("interpretation_blocks")
    if section is None:
        return None, None
    if not isinstance(section, dict):
        raise TaskCompositionError(
            f"section 'interpretation_blocks' must be a mapping; got {type(section).__name__}."
        )
    if section.get("none") is True:
        return None, None

    config_ref = _require(section, "config", "interpretation_blocks (without 'none: true')")
    config_path = _resolve_path(config_ref, manifest_dir)
    try:
        blocks = load_interpretation_task_blocks(config_path)
    except Exception as exc:
        raise TaskCompositionError(
            f"interpretation_blocks declaration at {config_path!r} could not "
            f"be loaded: {type(exc).__name__}: {exc}"
        ) from exc
    return blocks, config_path


def _compose_task_config(
    section: dict[str, Any], manifest_dir: str, profile: DatasetProfile
) -> tuple[str, ForwardContract, dict[str, Any]]:
    """The task's description + forward contract, through the EXISTING loader.

    ``load_task_config`` is called rather than reimplemented, so a composed
    task gets exactly the validation a legacy one gets — including the Step-03
    ``model_io`` resolution and its cross-check against the dataset's class
    count.

    That cross-check is why this runs under ``bind_dataset_profile``: the
    loader reads the AMBIENT profile for the cardinality comparison, and
    without the composed profile bound it would validate a composed task's
    contract against TIDMAD's topology — a wrong answer that looks like a
    passing check.
    """
    from agent.schemas.task_config import ForwardContract
    from execute_tools.dataset_config import bind_dataset_profile
    from workflows.task_config import get_task_description, load_task_config

    where = "task_config"
    config_ref = _require(section, "config", where)
    config_path = _resolve_path(config_ref, manifest_dir)
    if not os.path.isfile(config_path):
        raise TaskCompositionError(f"{where} not found at {config_path!r}.")
    try:
        with bind_dataset_profile(profile):
            values = load_task_config(config_path)
    except Exception as exc:
        raise TaskCompositionError(
            f"{where} at {config_path!r} could not be loaded: {type(exc).__name__}: {exc}"
        ) from exc

    description = get_task_description(values)
    if not description:
        raise TaskCompositionError(f"{where} at {config_path!r} carries an empty task_description.")
    contract = ForwardContract(**values["forward_contract"])
    return description, contract, values


# ---------------------------------------------------------------------------
# The semantic fingerprint (design §5.9)
# ---------------------------------------------------------------------------


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_semantic_fingerprint(
    *,
    task_data_path_id: str,
    dataset_profile: DatasetProfile,
    metric_declaration: dict[str, Any],
    task_health_binding: TaskHealthBinding,
    task_health_content: str | None,
    interpretation_blocks: InterpretationTaskBlocks | None,
    task_description: str,
    forward_contract: ForwardContract,
    plugins: tuple[ResolvedPluginRef, ...],
) -> str:
    """sha256 over the composition's SEMANTIC content, and nothing else.

    Included: resolved semantic values, declaration CONTENTS, plugin CONTENT
    digests, and stable binding identities the implementations declare about
    themselves.

    Excluded, deliberately: every machine-local absolute path, the workspace
    location, the manifest's own location and load order. Two checkouts of
    the same task package at different paths are the same scientific run, and
    a fingerprint that disagreed would fail their resumes for a reason that
    has nothing to do with the science (design §5.9, Q-P1-2).
    """
    from execute_tools.health_checks._composition import HealthBindingState

    binding_repr: str
    if isinstance(task_health_binding, HealthBindingState):
        binding_repr = str(task_health_binding.value)
    else:
        # A path is a LOCATION; its CONTENT is the semantics. Hash the content
        # and record only that the binding is of the "explicit config" kind.
        binding_repr = "explicit_config"

    payload = {
        "task_data_path_id": task_data_path_id,
        "dataset_profile": dataset_profile.model_dump(mode="json"),
        "metric_declaration": metric_declaration,
        "task_health_binding_kind": binding_repr,
        "task_health_content_sha256": task_health_content,
        "interpretation_blocks": (
            interpretation_blocks.model_dump(mode="json")
            if interpretation_blocks is not None
            else None
        ),
        "task_description": task_description,
        "forward_contract": forward_contract.model_dump(mode="json"),
        "plugins": sorted(
            (plugin.canonical_identity() for plugin in plugins),
            key=lambda identity: (identity["configured_ref"], identity["symbol"]),
        ),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The composition edge
# ---------------------------------------------------------------------------


def compose_run_task_bindings(manifest_path: str) -> RunTaskComposition:
    """Resolve a YAML composition manifest into the run's bound authorities.

    Called ONCE, at the launcher / composition edge, BEFORE ``run_workflow``
    — the same edge that already supplies the measurement capability. The
    workflow receives the resolved value and never a path, so it performs no
    YAML or plugin I/O and rediscovers nothing.

    Args:
        manifest_path: path to the composition manifest. Refs inside it are
            resolved relative to ITS directory, so a task package composes
            identically wherever it is checked out and whatever the cwd is.

    Returns:
        The frozen :class:`RunTaskComposition`.

    Raises:
        TaskCompositionError: any fail-closed branch — missing manifest,
            unknown or missing section, unresolvable ref, plugin import
            failure, id or contract mismatch, empty task description. No
            branch resolves TIDMAD.
    """
    resolved_manifest = os.path.abspath(manifest_path)
    manifest_dir = os.path.dirname(resolved_manifest)
    raw = _read_manifest(resolved_manifest)

    source_paths: dict[str, str] = {}
    plugins: list[ResolvedPluginRef] = []

    impl, impl_plugin = _compose_task_data_path(
        _section(raw, "task_data_path", resolved_manifest), manifest_dir
    )
    if impl_plugin is not None:
        plugins.append(impl_plugin)

    from execute_tools.dataset_config import load_dataset_profile

    profile_section = _section(raw, "dataset_profile", resolved_manifest)
    profile_ref = _require(profile_section, "config", "dataset_profile")
    profile_path = _resolve_path(profile_ref, manifest_dir)
    try:
        profile = load_dataset_profile(profile_path)
    except Exception as exc:
        raise TaskCompositionError(
            f"dataset_profile at {profile_path!r} could not be loaded: {type(exc).__name__}: {exc}"
        ) from exc
    source_paths["dataset_profile"] = profile_path

    metric_section = _section(raw, "metric", resolved_manifest)
    metric, metric_declaration, metric_plugin = _compose_metric(metric_section, manifest_dir)
    source_paths["metric_declaration"] = _resolve_path(
        _require(metric_section, "declaration", "metric"), manifest_dir
    )
    if metric_plugin is not None:
        plugins.append(metric_plugin)

    task_health_binding = _compose_task_health(
        _section(raw, "task_health", resolved_manifest), manifest_dir
    )
    task_health_content: str | None = None
    if isinstance(task_health_binding, str) and os.path.isfile(task_health_binding):
        task_health_content = _digest_file(task_health_binding, "task_health config")
        source_paths["task_health"] = task_health_binding

    interpretation_blocks, interpretation_path = _compose_interpretation_blocks(raw, manifest_dir)
    if interpretation_path is not None:
        source_paths["interpretation_blocks"] = interpretation_path

    task_config_section = _section(raw, "task_config", resolved_manifest)
    description, contract, _values = _compose_task_config(
        task_config_section, manifest_dir, profile
    )
    source_paths["task_config"] = _resolve_path(
        _require(task_config_section, "config", "task_config"), manifest_dir
    )

    fingerprint = compute_semantic_fingerprint(
        task_data_path_id=impl.task_data_path_id,
        dataset_profile=profile,
        metric_declaration=metric_declaration,
        task_health_binding=task_health_binding,
        task_health_content=task_health_content,
        interpretation_blocks=interpretation_blocks,
        task_description=description,
        forward_contract=contract,
        plugins=tuple(plugins),
    )

    return RunTaskComposition(
        task_data_path=impl,
        dataset_profile=profile,
        metric=metric,
        task_health_binding=task_health_binding,
        interpretation_blocks=interpretation_blocks,
        task_description=description,
        forward_contract=contract,
        semantic_fingerprint=fingerprint,
        provenance=CompositionProvenance(
            manifest_path=resolved_manifest,
            source_paths=source_paths,
            plugins=tuple(plugins),
        ),
    )


# ---------------------------------------------------------------------------
# Run-scoped activation (design §5.8)
# ---------------------------------------------------------------------------


class CompositionNotBoundError(RuntimeError):
    """A composed run reached the workflow without its authorities active.

    A wiring error rather than a configuration one, and fatal for the same
    reason every other fail-closed branch is: a run holding a composition
    whose bindings are NOT active would read the composed interpretation
    blocks and Health family while resolving the dataset profile, metric and
    task description from the legacy defaults — a half-composed run that
    looks completely normal in every log line.
    """


@contextmanager
def bind_run_task_composition(
    composition: RunTaskComposition | None,
) -> Iterator[RunTaskComposition | None]:
    """Activate every composed authority for the enclosing run scope.

    Entered at the composition EDGE — the launcher, or the module CLI — so
    the binding's lifetime is the lifetime of the run that owns the
    composition, and it covers the workflow's startup pre-flight as well as
    its iteration loop. That matters: the scope resolution and the Health
    materialisation both happen before iteration 1 and both read the run's
    profile.

    ``None`` is a no-op that yields ``None``: an un-composed run enters no
    context, sets no ContextVar and behaves exactly as it did before P1.

    Every binding is token-reset through :class:`~contextlib.ExitStack`, so
    all of them unwind in reverse order on the way out — including on an
    exception. Nested and sequential runs in one process therefore never
    observe each other's values (§5.8's leak invariant).

    Deliberately NOT bound here: the Health family and the interpretation
    blocks. Neither is ambient — the Health binding travels as an explicit
    parameter into ``build_run_invariants`` and the interpretation blocks as
    an explicit field on ``InterpretationInput``. Binding a ContextVar for a
    value that already has an explicit path would create a second way for it
    to arrive, which is the ambiguity this whole milestone removes.
    """
    if composition is None:
        yield None
        return

    from execute_tools.dataset_config import bind_dataset_profile
    from execute_tools.evaluation_metric import bind_run_metric
    from execute_tools.task_data_path import bind_task_data_path
    from workflows.task_config import bind_task_config

    with ExitStack() as stack:
        stack.enter_context(bind_task_data_path(composition.task_data_path))
        stack.enter_context(bind_dataset_profile(composition.dataset_profile))
        stack.enter_context(bind_run_metric(composition.metric))
        stack.enter_context(bind_task_config(composition.task_config_values()))
        yield composition


def verify_composition_is_bound(composition: RunTaskComposition | None) -> None:
    """Refuse a composed run whose authorities are not actually active.

    The workflow CONSUMES bindings it does not establish, so this is the
    check that makes that split safe: it converts a silent half-composed run
    — the most dangerous outcome in this milestone, because every value
    still resolves to *something* — into a loud refusal at startup, before
    any LLM call or training.

    An un-composed run (``None``) is a no-op.

    Raises:
        CompositionNotBoundError: a composition was supplied but one or more
            of its authorities is unbound or bound to a different value.
    """
    if composition is None:
        return

    from execute_tools.dataset_config import resolve_dataset_profile
    from execute_tools.evaluation_metric import resolve_bound_run_metric
    from execute_tools.task_data_path import active_task_data_path
    from workflows.task_config import resolve_bound_task_config

    unbound: list[str] = []
    if active_task_data_path() is not composition.task_data_path:
        unbound.append("task_data_path")
    if resolve_dataset_profile() is not composition.dataset_profile:
        unbound.append("dataset_profile")
    if resolve_bound_run_metric() is not composition.metric:
        unbound.append("metric")
    bound_config = resolve_bound_task_config()
    if bound_config is None or bound_config.get("task_description") != (
        composition.task_description
    ):
        unbound.append("task_config")

    if unbound:
        raise CompositionNotBoundError(
            f"a run was given a task composition whose authorities are not "
            f"active: {unbound}. Wrap the run in "
            "`bind_run_task_composition(composition)` at the composition "
            "edge — a half-composed run resolves the remaining families from "
            "the legacy defaults and looks entirely normal while doing it."
        )
