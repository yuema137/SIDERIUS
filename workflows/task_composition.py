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
from contextvars import ContextVar
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any, cast

import yaml

from agent.schemas.hyperparam_tuning import TaskCompositionRef

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
        "secondary_metrics",
        "task_health",
        "interpretation_blocks",
        "proposal_blocks",
        "implementor_blocks",
        "task_config",
        "deliverable",
        "model_plugins",
        "loss_plugins",
        "objective",
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
"""``secondary_metrics`` is deliberately NOT here (Step 10 / P2b §4.1).

Health is required-as-a-STATEMENT because saying nothing about it resolves
TIDMAD's family. Secondaries have no such default: the absence of the section
means the run has none, which is a first-class state (TIDMAD's own), and
requiring every manifest to write ``secondary_metrics: []`` would be ceremony
that buys no safety."""


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
    deliverable_naming: Any = None
    """The run's DECLARED deliverable naming, or ``None`` for the shipped one.

    Step 11 C6. A RESOLVED ``DeliverableNaming`` — the Deliverable Contract's
    own validated type — carried so the spawn and cleanup consumers can read
    it. The composition does not become a second naming authority (R-11-3):
    it holds what that contract produced and nothing else.

    ``None`` is the un-declared state and resolves the shipped TIDMAD naming
    byte-identically, so a manifest with no ``deliverable:`` section composes
    exactly as it did before C6.
    """

    proposal_blocks: Any = None
    """The run's DECLARED proposer guidance, or ``None``.

    Step 12 / PR-12a C7 (D-12a-6). A ``ProposalTaskBlocks``, resolved by the
    SAME optional-section shape ``interpretation_blocks`` uses. ``None`` is
    the un-declared state and renders ZERO added bytes, so a manifest with no
    ``proposal_blocks:`` section composes exactly as it did before C7. Typed
    ``Any`` for the same reason the deliverable naming is: this carrier holds
    what another module's contract produced and never becomes a second
    authority for it.
    """

    implementor_blocks: Any = None
    """The run's DECLARED implementor science, or ``None``.

    Step 12 / PR-12a C7-4, the operator-ratified contract correction. An
    ``ImplementorTaskBlocks``, resolved by the SAME optional-section shape its
    two siblings use. ``None`` is the un-declared state and renders NOTHING —
    a composed task that declares none gets no implementor science rather
    than TIDMAD's.
    """

    model_plugins: Any = None
    loss_plugins: Any = None
    objective: Any = None
    """The run's AUTHORITATIVE objective as a validated ``LossConfig``, or ``None``.

    Step 12 / PR-12d, F-12d-31. Present only when the manifest declares an
    ``objective:`` section. ``None`` means the task states no authoritative
    objective and the planner's choice stands, which is every run that
    exists today.
    """

    """The run's DECLARED model plugins, resolved and pinned, or ``None``.

    Step 12 / PR-12d, seam P. A ``RunModelPluginBinding`` — the plugin
    authority's own validated type — carried so the composition edge can bind
    it for the run and the invariants lock can record which implementations
    executed. This carrier does not become a second plugin authority: it holds
    what ``ml_models.plugin_binding`` produced and nothing else, the same rule
    ``deliverable_naming`` follows (R-11-3).

    ``None`` is the un-declared state, binds nothing, and leaves plugin
    resolution byte-identical to its pre-seam-P behaviour. Typed ``Any`` for
    the same reason the naming is: importing the concrete type here would pull
    ``ml_models`` into every importer of this module.
    """

    secondary_metrics: tuple[EvaluationMetric, ...] = ()
    """The run's DECLARED observational secondary metrics, in manifest order.

    Step 10 / P2b. Each is an ordinary :class:`EvaluationMetric` resolved by
    the SAME :func:`_compose_metric` authority the primary uses, carrying its
    OWN direction — DAVIS declares ``psnr`` (higher) beside a ``mse`` primary
    that is lower-is-better, and neither inherits from the other.

    Defaulted to ``()`` so a manifest that declares none composes exactly as
    it did before P2b, and so this carrier's existing nine fields keep their
    positions. Secondaries are OBSERVATIONAL: nothing in this tuple may ever
    become an operand of an ordering expression.
    """

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
        # Step 12 / PR-12bc C1 — F-12bc-2. The `sys.modules` rollback below was
        # only half the story: a plugin that REGISTERED a data path and then
        # raised left the registry dirty, so its id was permanently taken by an
        # implementation whose module never finished running. The health loader
        # already rolls back its own registries (`_plugin_binding.py:338-341`);
        # this is the same idiom, one family over, and it is what the retirement
        # path added by the overlay makes possible.
        from execute_tools.task_registration_scope import registration_rollback

        with registration_rollback():
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


def _refuse_unknown_section_keys(
    section: dict[str, Any], allowed: frozenset[str], where: str
) -> None:
    """Refuse a key a section does not define. Fails closed, by name.

    Step 12 / PR-12d, seam A. The top-level unknown-key refusal at
    ``_read_manifest`` never looked INSIDE a section, so a misspelled sibling
    — ``configs:`` for ``config:`` — was silently dropped and the family
    resolved as though nothing had been declared. That is the same
    silent-default failure the top-level check exists to prevent, one level
    down.
    """
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise TaskCompositionError(
            f"section {where!r} declares unknown key(s) {unknown}; known keys "
            f"are {sorted(allowed)}. An unknown key inside a section is "
            f"refused rather than ignored: a misspelled key would otherwise "
            f"be silently dropped and the family would resolve as though "
            f"nothing had been declared."
        )


def _validated_task_config_mapping(
    section: dict[str, Any], manifest_dir: str, where: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The OPTIONAL ``config:`` mapping — shape only, never a field name.

    Step 12 / PR-12d, seam A. This is the whole task-agnosticism rule made
    executable: the composition authority checks that the declaration is a
    mapping with string keys, and then hands it to the implementation's own
    constructor. ``manifest_path`` and ``clips_path`` are strings the TASK's
    constructor understands; nothing here knows either name, and nothing here
    maps a task id to a set of arguments.

    **The ``{ref: …}`` envelope, and why it is necessary.** Every other ref in
    a manifest is resolved relative to the MANIFEST's directory, so a task
    package composes identically wherever it is checked out and whatever the
    cwd is. A ``config:`` value cannot get that for free: the framework must
    not decide which of a task's own keys hold paths, because that is exactly
    the task knowledge this seam exists to keep out. So the TASK declares it::

        config:
          manifest_path: {ref: ../../examples/<pack>/data/manifests/train.csv}
          batch_hint: 32

    A value that is a mapping with exactly the key ``ref`` is resolved through
    the SAME ``_resolve_path`` authority every other ref uses; everything else
    passes through verbatim. The framework still knows no field name — only a
    shape the task opted into.

    Returns ``(constructor_kwargs, declared_config)``. The second is the
    AUTHORED form, and it is what enters the semantic fingerprint: hashing the
    resolved absolute paths would make the same task package at two checkout
    locations two different runs, which is precisely the Q-P1-2 exclusion the
    fingerprint already applies to every other ref.
    """
    config = section.get("config")
    if config is None:
        return {}, {}
    if not isinstance(config, dict):
        raise TaskCompositionError(
            f"{where}.config must be a mapping of constructor arguments the "
            f"declared implementation understands; got {type(config).__name__}."
        )
    bad = sorted(str(key) for key in config if not isinstance(key, str) or not key.strip())
    if bad:
        raise TaskCompositionError(
            f"{where}.config keys must be non-empty strings; got {bad}. They "
            f"are passed to the implementation's constructor as keyword "
            f"arguments, so a non-identifier key could never be accepted."
        )

    kwargs: dict[str, Any] = {}
    for key, value in config.items():
        if not isinstance(value, dict) or "ref" not in value:
            kwargs[key] = value
            continue
        if set(value) != {"ref"}:
            raise TaskCompositionError(
                f"{where}.config[{key!r}] declares a 'ref' alongside "
                f"{sorted(set(value) - {'ref'})}. A ref envelope carries "
                f"exactly one key; a sibling next to it is a misspelling that "
                f"would otherwise be passed through as an opaque mapping."
            )
        ref = value["ref"]
        if not isinstance(ref, str) or not ref.strip():
            raise TaskCompositionError(
                f"{where}.config[{key!r}].ref must be a non-empty string path "
                f"relative to the manifest; got {ref!r}."
            )
        kwargs[key] = _resolve_path(ref, manifest_dir)
    return kwargs, dict(config)


def _construct_declared_implementation(factory: Any, config: dict[str, Any], where: str) -> Any:
    """Turn a resolved symbol plus its declared config into a live instance.

    Extracted rather than inlined (§E.2): construction is its own
    responsibility — it decides between an already-built instance and a
    class/factory, applies the task's own constructor arguments, and owns
    three named refusals. Folding it into :func:`_compose_task_data_path`
    would have pushed that function's branch count past the budget for a
    reason the decomposition rule already answers.

    Three fail-closed branches, each named:

    * ``config:`` declared against an already-CONSTRUCTED symbol —
      configuration happens at construction, and a composition never mutates
      an object it was handed;
    * a key the declared implementation does not accept — the keys are the
      implementation's OWN constructor arguments, and this authority never
      invents or renames one;
    * a constructor that raises for any other reason.
    """
    if _looks_like_instance(factory):
        if config:
            raise TaskCompositionError(
                f"{where}.config was declared, but {where}.symbol resolves to "
                f"an already-constructed instance rather than a class or "
                f"factory. Configuration happens AT construction — a "
                f"composition never mutates an object it was handed."
            )
        return factory
    if not callable(factory):
        return factory
    try:
        return factory(**config)
    except TypeError as exc:
        raise TaskCompositionError(
            f"{where}: the declared implementation does not accept the "
            f"declared config {sorted(config)}: {exc}. The config keys are "
            f"the implementation's OWN constructor arguments; the composition "
            f"authority never invents or renames them."
        ) from exc
    except Exception as exc:
        raise TaskCompositionError(
            f"{where}: the declared implementation raised while being "
            f"constructed with config {sorted(config)}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def _compose_task_data_path(
    section: dict[str, Any], manifest_dir: str
) -> tuple[TaskDataPath, ResolvedPluginRef | None, dict[str, Any]]:
    """Load the implementation, register it if new, and return the OBJECT.

    Registration is the existing public registry's own call, so a duplicate
    id is refused by the authority that owns ids rather than by a second
    opinion here.

    **"One id, one object" means one SEMANTIC IMPLEMENTATION IDENTITY, not
    one immortal Python instance** (Step 12 / PR-12d, ruling A1). Source
    already implied it: ``content_identity`` is class-and-source derived, so a
    bare and a CONFIGURED instance of the same class are identically
    identified, and a child process can never share the parent's object
    anyway. So the registered instance ANCHORS the identity — that is what
    keeps a transported id resolvable in every child — while a declaration
    carrying ``config:`` yields the run-specific configured instance, and the
    bare object is **never returned in its place**.

    Before this, ``factory()`` was called with no arguments and no ``config:``
    key existed, so ``PetsTaskDataPath`` and ``DavisTaskDataPath`` raised BY
    NAME at the first tuner attempt — instructing the operator to declare a
    section key the composition authority did not implement (F-12d-8).

    Returns ``(implementation, plugin_ref, config)``. The config travels out
    because it is SEMANTIC: changing ``manifest_path`` changes what the run
    trains on, so it must move the composition fingerprint.
    """
    from execute_tools.task_data_path import (
        TaskBindingContext,
        TaskDataPathRegistrationError,
        content_identity,
        register_task_data_path,
        registered_content_identity,
        registered_task_data_path_ids,
        resolve_task_data_path,
    )

    where = "task_data_path"
    _refuse_unknown_section_keys(
        section, frozenset({"file", "module", "symbol", "id", "config"}), where
    )
    config, declared_config = _validated_task_config_mapping(section, manifest_dir, where)
    factory, plugin_ref = _load_symbol(section, manifest_dir, where)

    resolved = _construct_declared_implementation(factory, config, where)

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
        # Step 12 / PR-12bc C1 — F-12-3. This used to return the registered
        # object on an ID match alone, while the composition went on to report
        # the NEWLY loaded plugin's content digest into the fingerprint. An
        # EDITED plugin therefore ran the OLD code under a FRESH identity, and
        # nothing anywhere said so.
        #
        # The registration performed above (or, for an already-present id,
        # skipped as idempotent) has already settled the two-phase rule: an
        # id whose content DIFFERS never reaches here, because
        # `register_task_data_path` refused it. So reaching this line means the
        # content matched, and returning the registered object is correct —
        # but the check is stated HERE too, because "the other function
        # already checked" is exactly the kind of reasoning that decays.
        registered_identity = registered_content_identity(declared)
        loaded_identity = content_identity(resolved)
        if (
            loaded_identity is not None
            and registered_identity is not None
            and loaded_identity != registered_identity
        ):
            raise TaskCompositionError(
                f"{where}: task_data_path {declared!r} is registered with "
                f"different content than the plugin just loaded.\n"
                f"  registered: {registered_identity}\n"
                f"  loaded:     {loaded_identity}\n"
                f"Returning the registered object would run the OLD code under "
                f"the NEW plugin's identity — the composition fingerprint would "
                f"name something that never executed."
            )
        if config:
            # Ruling A1. The registered instance ANCHORS the identity — the
            # check above just proved the content matches — but it was built
            # with nothing, and this declaration asked for configured
            # semantics. Returning the bare object here is exactly the defect:
            # every built-in registers at module import in all three children,
            # so the registered instance ALWAYS exists first, and a composed
            # Pets or DAVIS run would silently receive the one that cannot
            # build a scope.
            return cast("TaskDataPath", resolved), plugin_ref, declared_config
        return (
            resolve_task_data_path(TaskBindingContext(task_data_path_id=declared)),
            plugin_ref,
            declared_config,
        )

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
    return impl, plugin_ref, declared_config


def _looks_like_instance(candidate: Any) -> bool:
    """A resolved symbol may be a CLASS or an already-built instance.

    Classes are callable, so ``callable()`` alone cannot tell them apart from
    a factory; an instance that declares the protocol's id attribute on
    itself is taken as already built.
    """
    return not isinstance(candidate, type) and hasattr(candidate, "task_data_path_id")


def _compose_metric(
    section: dict[str, Any], manifest_dir: str, where: str = "metric"
) -> tuple[EvaluationMetric, dict[str, Any], ResolvedPluginRef | None]:
    """Declaration JSON → ``MetricSpec`` → the declared implementation.

    The spec comes from ``metric_spec_from_declaration`` — the ONE
    spec-from-declaration authority (Step 06) — so this module adds no second
    way for a metric identity to come into existence.

    ``where`` names the ROLE being composed in every fail-closed message.
    It defaults to ``"metric"``, so the primary's messages are byte-identical
    to their pre-P2b text; :func:`_compose_secondary_metrics` passes
    ``"secondary_metrics[i]"`` so an operator reading a refusal is told which
    declaration failed rather than being sent to the primary section. This
    parameter is the whole reason P2b needs no second copy of the five
    fail-closed branches below (Step 10 / P2b §3.1: reuse or STOP).
    """
    from execute_tools.evaluation_metric import EvaluationMetric, metric_spec_from_declaration

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
    # Step 12 / PR-12d D4c — F-12d-3. The check ABOVE compares the declaration
    # to itself (`EvaluationMetric.__init__` assigns `self.spec = spec`), so it
    # can only fire for an implementation that rewrites its own id. It is kept
    # — that case is real — but it never was the check this line needs.
    #
    # `IMPLEMENTS` is what the implementation asserts INDEPENDENTLY of the
    # declaration it was handed. When it makes a claim and the declared id is
    # not in it, the two parties disagree about what arithmetic will run, and
    # composition refuses. An implementation making no claim composes under any
    # id, so `MetricSpec.id` stays opaque (D16/C5) and every pre-D4c binding
    # remains valid.
    claimed = getattr(type(metric), "IMPLEMENTS", ())
    if claimed and spec.id not in claimed:
        raise TaskCompositionError(
            f"{where}: the declaration declares id {spec.id!r}, but "
            f"{type(metric).__name__} states it implements "
            f"{', '.join(repr(c) for c in claimed)}. Binding a metric id to an "
            "implementation that computes something else produces a terminal "
            "report labelled with one metric and populated by another — the "
            "declaration would name the science and the arithmetic would "
            "disagree with it, silently."
        )
    return metric, payload, plugin_ref


def _compose_secondary_metrics(
    raw: dict[str, Any], manifest_dir: str, primary_id: str
) -> tuple[tuple[EvaluationMetric, ...], list[dict[str, Any]], list[ResolvedPluginRef], list[str]]:
    """The OPTIONAL ``secondary_metrics`` list → resolved observational metrics.

    Step 10 / P2b §4.1. Every entry has the same ``{declaration,
    implementation}`` shape the ``metric`` section already uses and is
    resolved by :func:`_compose_metric` ITSELF, so all five of its
    fail-closed branches — unreadable or non-object declaration, invalid
    spec, missing implementation mapping, non-``EvaluationMetric``
    implementation, implementation that rewrites its own spec id — are
    INHERITED rather than re-implemented. The only rules that are new here
    are the two this list can violate and a single metric cannot: an id
    declared twice, and an id that is already the primary's.

    An absent section and an empty list are the same state: a task with no
    secondaries, composing byte-identically to its pre-P2b self.

    Returns ``(metrics, declarations, plugins, declaration_paths)`` in
    manifest order — manifest order is SEMANTIC (it is what the fingerprint
    and the output stamp preserve), so nothing here sorts.

    Raises:
        TaskCompositionError: the section is not a list, an entry is not a
            mapping, an entry fails any inherited branch, an id repeats, or
            an id collides with the primary's.
    """
    section = raw.get("secondary_metrics")
    if section is None:
        return (), [], [], []
    if not isinstance(section, list):
        raise TaskCompositionError(
            f"section 'secondary_metrics' must be a LIST of "
            f"{{declaration, implementation}} entries; got "
            f"{type(section).__name__}. Order is semantic, which a mapping "
            "cannot express."
        )

    metrics: list[EvaluationMetric] = []
    declarations: list[dict[str, Any]] = []
    plugins: list[ResolvedPluginRef] = []
    declaration_paths: list[str] = []
    seen: dict[str, int] = {}

    for index, entry in enumerate(section):
        where = f"secondary_metrics[{index}]"
        if not isinstance(entry, dict):
            raise TaskCompositionError(
                f"{where} must be a mapping declaring 'declaration' and "
                f"'implementation'; got {type(entry).__name__}."
            )
        metric, declaration, plugin_ref = _compose_metric(entry, manifest_dir, where)
        metric_id = metric.spec.id
        if metric_id == primary_id:
            raise TaskCompositionError(
                f"{where} declares metric id {metric_id!r}, which is already "
                "this run's PRIMARY metric. A metric is either the quantity "
                "the run is optimised against or an observational secondary "
                "beside it — never both, because the same id would then reach "
                "ordering through one role while claiming to be excluded from "
                "it through the other."
            )
        if metric_id in seen:
            raise TaskCompositionError(
                f"{where} declares metric id {metric_id!r}, already declared "
                f"by secondary_metrics[{seen[metric_id]}]. Secondary ids are "
                "the keys every downstream carrier joins on — the record's "
                "results/refusals/errors and the output's declared stamp — so "
                "a duplicate would make 'which one is this' unanswerable."
            )
        seen[metric_id] = index
        metrics.append(metric)
        declarations.append(declaration)
        if plugin_ref is not None:
            plugins.append(plugin_ref)
        declaration_paths.append(_resolve_path(_require(entry, "declaration", where), manifest_dir))

    return tuple(metrics), declarations, plugins, declaration_paths


def _compose_model_plugins(raw: dict[str, Any], manifest_dir: str):
    """The OPTIONAL ``model_plugins`` section → a run-scoped plugin binding.

    Step 12 / PR-12d, seam P. The task DECLARES where its own model plugins
    live and which model types that root must produce; the framework resolves
    them through the SAME public loader the legacy path uses and pins their
    content identities. There is no task name here and no catalog — the
    declaration belongs to the pack, exactly as ``task_health`` already does.

    Shape, deliberately the same optional-section idiom the three ``*_blocks``
    families use — a mapping, ``none: true`` for a NAMED absence, otherwise a
    ``dir`` ref plus a ``require`` list::

        model_plugins:
          dir: ../../examples/oxford_iiit_pet/plugins
          require: [pets_reference_cnn]

    An ABSENT section and ``none: true`` both yield ``None``, which binds
    nothing: a manifest that declares no model plugins composes exactly as it
    did before seam P, and its semantic fingerprint is byte-unchanged.

    Returns ``(binding_or_None, resolved_root_or_None)``.

    Raises:
        TaskCompositionError: the section is not a mapping, declares both
            ``none: true`` and a ``dir``, omits ``dir`` or ``require``,
            declares a malformed ``require`` list, or the resolver refuses.
    """
    from ml_models.plugin_binding import (
        ModelPluginResolutionError,
        normalized_ref,
        resolve_declared_model_plugins,
    )

    where = "model_plugins"
    section = raw.get(where)
    if section is None:
        return None, None
    if not isinstance(section, dict):
        raise TaskCompositionError(
            f"section {where!r} must be a mapping; got {type(section).__name__}."
        )
    if section.get("none") is True:
        if "dir" in section:
            raise TaskCompositionError(
                f"{where} declares both 'none: true' and a 'dir'. A task either "
                "ships model plugins or explicitly ships none."
            )
        return None, None

    dir_ref = _require(section, "dir", f"{where} (without 'none: true')")
    required = section.get("require")
    if not isinstance(required, list) or not required:
        raise TaskCompositionError(
            f"{where} requires a non-empty list 'require' naming the model "
            f"type(s) the declared root must produce; got {required!r}. "
            "Without it an unresolvable plugin would be indistinguishable "
            "from a root that simply had nothing in it."
        )
    if not all(isinstance(name, str) and name.strip() for name in required):
        raise TaskCompositionError(
            f"{where}.require must contain only non-empty strings; got {required!r}."
        )

    root = _resolve_path(dir_ref, manifest_dir)
    try:
        binding = resolve_declared_model_plugins(
            configured_ref=normalized_ref(dir_ref),
            root=root,
            required_model_types=tuple(str(name) for name in required),
        )
    except ModelPluginResolutionError as exc:
        raise TaskCompositionError(f"{where}: {exc}") from exc
    return binding, root


def _compose_loss_plugins(raw: dict[str, Any], manifest_dir: str):
    """The OPTIONAL ``loss_plugins`` section → the run's declared loss roots.

    Step 12 / PR-12d D4c, closing two of A3's four named blockers: there was
    no way for a pack to DECLARE where its objective lives, and loss-directory
    discovery therefore never saw a pack at all. DAVIS's exact-L1 objective
    could be written but not reached.

    **Why this is not folded into ``model_plugins``**, even though a pack keeps
    both in one directory: the two environment variables were split on purpose
    (`core/subprocess_env.py:40-42`) because sharing one masks the globally
    registered loss library whenever only a model directory is set. One
    directory, two channels.

    Shape mirrors ``model_plugins`` exactly, minus ``require``: a loss is
    resolved BY NAME at training time through ``LossConfig.loss_name``, so the
    "which types must this root produce" question has no analogue here — the
    run's own `loss_name` already names it, and an unresolvable one is already
    a named refusal in `_load_custom_loss`::

        loss_plugins:
          dir: ../../examples/davis_future_prediction/plugins

    An ABSENT section and ``none: true`` both yield ``()``, which binds
    nothing: legacy loss discovery is untouched and the semantic fingerprint
    is byte-unchanged.

    Returns ``(roots_tuple, resolved_root_or_None)``.
    """
    where = "loss_plugins"
    section = raw.get(where)
    if section is None:
        return (), None
    if not isinstance(section, dict):
        raise TaskCompositionError(
            f"section {where!r} must be a mapping; got {type(section).__name__}."
        )
    if section.get("none") is True:
        if "dir" in section:
            raise TaskCompositionError(
                f"{where} declares both 'none: true' and a 'dir'. A task either "
                "ships loss plugins or explicitly ships none."
            )
        return (), None

    dir_ref = _require(section, "dir", f"{where} (without 'none: true')")
    root = _resolve_path(dir_ref, manifest_dir)
    if not os.path.isdir(root):
        raise TaskCompositionError(
            f"{where}.dir names {dir_ref!r}, which does not resolve to a directory "
            f"at {root!r}. A declared objective root that does not exist would "
            "leave the run silently falling back to the global loss library."
        )
    return (root,), root


def _objective_name_declared_by(path: str) -> str | None:
    """The ``PLUGIN_LOSS_TYPE`` a loss file declares, by TEXT not import.

    Read rather than imported on purpose: this runs over every candidate in the
    run's loss search path, and importing arbitrary modules to answer "does
    this shadow my objective?" would execute third-party code as a side effect
    of a safety check.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return None
    match = re.search(r"^PLUGIN_LOSS_TYPE\s*[:=][^=]*?['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    return match.group(1) if match else None


def _refuse_ambiguous_objective(
    declared_name: str,
    resolved_ref: ResolvedPluginRef | None,
    manifest_dir: str,
    where: str,
) -> None:
    """One authoritative declaration must resolve to ONE implementation.

    Step 12 / PR-12d, F-12d-31 — the C12-I substitution finding. Runtime
    resolves a custom loss BY NAME over a UNION (``SIDERIUS_LOSS_DIRS`` ∪
    ``agent_generated/losses/``, plus an in-memory registry). So a second file
    anywhere in that search path declaring the same ``PLUGIN_LOSS_TYPE`` could
    be the one actually executed, while the fingerprint pinned the declared
    one — selection and identity silently describing different code.

    For an AUTHORITATIVELY DECLARED objective that must fail loudly. This does
    NOT touch legacy loss discovery: a run that declares no ``objective:`` is
    unaffected, name-based resolution is unchanged, and nothing here alters
    which directories are searched. It only refuses the ambiguity for the one
    objective a manifest claims authority over.

    ``resolved_ref is None`` is the ``module:`` form — an in-tree import whose
    identity the repository's own commit already pins, with no directory to be
    shadowed from.
    """
    if resolved_ref is None:
        return
    declared_path = os.path.realpath(resolved_ref.absolute_path)
    # PRODUCTION's own search path, not a reconstruction of it: asking a
    # different question than runtime asks is how a guard passes while the
    # thing it guards is broken.
    try:
        from agent_generated._loss_loader import _resolve_loss_dirs

        search_roots = list(_resolve_loss_dirs())
    except Exception:  # pragma: no cover - loader absent in a trimmed checkout
        search_roots = []
    search_roots.append(os.path.dirname(declared_path))

    shadows: list[str] = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            if not entry.endswith(".py"):
                continue
            candidate = os.path.realpath(os.path.join(root, entry))
            if candidate == declared_path or candidate in shadows:
                continue
            if _objective_name_declared_by(candidate) == declared_name:
                shadows.append(candidate)
    if shadows:
        raise TaskCompositionError(
            f"{where} declares the authoritative objective {declared_name!r}, but "
            f"{len(shadows)} OTHER implementation(s) in this run's loss search "
            f"path declare the same name: {shadows}. Runtime resolves a custom "
            f"loss by name, so which one trains would be decided by search "
            f"order while the run's identity pinned "
            f"{resolved_ref.configured_ref!r}. An authoritative objective "
            "resolves to exactly one implementation or the run refuses."
        )


def _compose_objective(raw: dict[str, Any], manifest_dir: str):
    """The OPTIONAL ``objective`` section → the run's AUTHORITATIVE loss.

    Step 12 / PR-12d, F-12d-31. ``loss_plugins:`` made a pack's objective
    REACHABLE; nothing made it SELECTED. A composed DAVIS run therefore trained
    with ``smooth_l1`` twice, because the planner is told ``smooth_l1`` is the
    only valid regressor loss and never learns the task ships its own. §I
    requires exact MAE/L1, so "the objective a task declares" has to be a
    typed authority, not a prompt suggestion an LLM may decline.

    **The name is NOT restated here.** The manifest points at the
    implementation and at the symbol that implementation uses to declare
    itself::

        objective:
          implementation:
            file: ../../examples/davis_future_prediction/plugins/davis_exact_l1_loss.py
            symbol: PLUGIN_LOSS_TYPE

    ``_load_symbol`` returns that symbol's VALUE — the loss name the plugin
    claims — so the implementation is the single source of its own identity
    and the manifest cannot disagree with it. Exactly the ``IMPLEMENTS``
    discipline F-12d-3 established for metrics, one family over.

    **No new selection vocabulary.** The result is an ordinary validated
    :class:`LossConfig` on the existing ``custom`` + ``loss_name`` route —
    ``loss_type`` keeps its five members, nothing is added to a central enum,
    and no task name appears anywhere.

    Absent section ⇒ ``(None, None)``: no override, no fingerprint key, legacy
    byte-unchanged.

    Returns ``(loss_config_or_None, resolved_ref_or_None)``.
    """
    where = "objective"
    section = raw.get(where)
    if section is None:
        return None, None
    if not isinstance(section, dict):
        raise TaskCompositionError(
            f"section {where!r} must be a mapping; got {type(section).__name__}."
        )
    if section.get("none") is True:
        if "implementation" in section:
            raise TaskCompositionError(
                f"{where} declares both 'none: true' and an 'implementation'. A task "
                "either declares an authoritative objective or explicitly declares none."
            )
        return None, None

    implementation = section.get("implementation")
    if not isinstance(implementation, dict):
        raise TaskCompositionError(
            f"{where} (without 'none: true') requires an 'implementation' mapping "
            f"naming the plugin file and the symbol it declares itself with; got "
            f"{implementation!r}."
        )
    declared_name, resolved_ref = _load_symbol(
        implementation, manifest_dir, f"{where}.implementation"
    )
    if not isinstance(declared_name, str) or not declared_name.strip():
        raise TaskCompositionError(
            f"{where}.implementation resolves a loss name that is not a non-empty "
            f"string: {declared_name!r}. The symbol named here must be the "
            "implementation's own declaration of the loss it provides (e.g. "
            "PLUGIN_LOSS_TYPE), so the plugin states its identity and the "
            "manifest merely points at it."
        )

    _refuse_ambiguous_objective(declared_name, resolved_ref, manifest_dir, where)

    from ml_models.models_format_sandbox import LossConfig

    try:
        loss_config = LossConfig(loss_type="custom", loss_name=declared_name)
    except Exception as exc:
        raise TaskCompositionError(
            f"{where}.implementation declares loss name {declared_name!r}, which does "
            f"not form a valid LossConfig: {type(exc).__name__}: {exc}"
        ) from exc
    return loss_config, resolved_ref


def build_task_composition_ref(task_composition: Any) -> TaskCompositionRef | None:
    """Project the run's composition into what the TUNER needs (D-12a-1).

    Step 12 / PR-12d D8a — relocated from ``workflows/model_exploration.py`` so the tuner's standalone CLI (`nodes/ml_hyperparameter_tune_agent/cli.py`) can call it without importing an ORCHESTRATOR module that itself imports the tuner node — the dependency direction CLAUDE.md's decomposition rule asks every module to respect. `model_exploration.py` re-imports it from here; nothing about the function's behaviour moved.

    One place builds it, from values the composition already resolved. The
    tuner then learns "this run is composed, and by what" from its INPUT
    instead of asking the ambient environment — the W4 reference-science guard
    used to call ``active_task_data_path()`` for that, and the per-model
    run-invariants lock had no composition values to record at all.

    Deliberately NOT a second authority: nothing is re-derived here, and the
    record/output composition-fingerprint stamps keep reading
    ``active_composition_fingerprint()`` (Step 11 F-11-C10-a, AST-pinned).

    Returns ``None`` for an un-composed run, which is what makes the whole
    mechanism invisible to regime A.
    """
    if task_composition is None:
        return None
    return TaskCompositionRef(
        semantic_fingerprint=task_composition.semantic_fingerprint,
        task_data_path_id=type(task_composition.task_data_path).task_data_path_id,
        task_health_binding=task_composition.task_health_binding,
        objective=getattr(task_composition, "objective", None),
    )


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


def _compose_implementor_blocks(raw: dict[str, Any], manifest_dir: str) -> tuple[Any, str | None]:
    """Optional by design: an absent declaration renders NOTHING (C7-4).

    Third instance of the same shape, deliberately identical to its two
    siblings — same `none: true` escape, same `config:` ref, same fail-closed
    propagation.
    """
    from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks

    section = raw.get("implementor_blocks")
    if section is None:
        return None, None
    if not isinstance(section, dict):
        raise TaskCompositionError(
            f"section 'implementor_blocks' must be a mapping; got {type(section).__name__}."
        )
    if section.get("none") is True:
        return None, None

    config_ref = _require(section, "config", "implementor_blocks (without 'none: true')")
    config_path = _resolve_path(config_ref, manifest_dir)
    try:
        blocks = load_implementor_task_blocks(config_path)
    except Exception as exc:
        raise TaskCompositionError(
            f"implementor_blocks declaration at {config_path!r} could not be loaded: {exc}"
        ) from exc
    return blocks, config_path


def _compose_proposal_blocks(raw: dict[str, Any], manifest_dir: str) -> tuple[Any, str | None]:
    """Optional by design: an absent declaration renders NOTHING (D-12a-6).

    Deliberately the same shape as :func:`_compose_interpretation_blocks` —
    same `none: true` escape, same `config:` ref, same fail-closed
    propagation. Two sibling families that behave differently would be two
    things to learn instead of one.
    """
    from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks

    section = raw.get("proposal_blocks")
    if section is None:
        return None, None
    if not isinstance(section, dict):
        raise TaskCompositionError(
            f"section 'proposal_blocks' must be a mapping; got {type(section).__name__}."
        )
    if section.get("none") is True:
        return None, None

    config_ref = _require(section, "config", "proposal_blocks (without 'none: true')")
    config_path = _resolve_path(config_ref, manifest_dir)
    try:
        blocks = load_proposal_task_blocks(config_path)
    except Exception as exc:
        raise TaskCompositionError(
            f"proposal_blocks declaration at {config_path!r} could not be loaded: {exc}"
        ) from exc
    return blocks, config_path


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
    secondary_metric_declarations: list[dict[str, Any]] | None = None,
    deliverable_naming_declaration: dict[str, Any] | None = None,
    proposal_blocks: Any = None,
    implementor_blocks: Any = None,
    task_data_path_config: dict[str, Any] | None = None,
    task_data_path_content_identity: str | None = None,
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
        "dataset_profile": dataset_profile.to_wire(),
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
    # Step 10 / P2b (delta D3) — ADDITIVE WHEN NON-EMPTY, never always-present.
    # An unconditional key would move the fingerprint of EVERY composed run
    # that exists today and fail their resumes for a reason with no scientific
    # content — precisely what Q-P1-2's exclusion rule exists to prevent, and
    # the same idiom as the run-invariants lock's "key ABSENT for legacy".
    # Manifest ORDER is preserved: the declared set is what the output stamps
    # and what the interpreter's absence rows are keyed on, so re-ordering two
    # secondaries is a different declaration, not the same one shuffled.
    if secondary_metric_declarations:
        payload["secondary_metric_declarations"] = secondary_metric_declarations
    # Step 11 C6 — a DECLARED naming is semantic: it decides deliverable file
    # identity, so two runs that name their outputs differently are not the
    # same run. Added only when declared, following the secondaries
    # precedent, so an un-declared manifest's fingerprint is unchanged.
    if deliverable_naming_declaration:
        payload["deliverable_naming"] = deliverable_naming_declaration
    # Step 12 / PR-12a C7 (D-12a-6) — declared proposer science is semantic:
    # it changes what the model is ASKED, so two runs whose proposer guidance
    # differs are not the same run. ADDITIVE WHEN DECLARED, on the same
    # precedent as the two above, so every existing composed manifest's
    # fingerprint is byte-unchanged and its resume still validates.
    if proposal_blocks is not None:
        payload["proposal_blocks"] = proposal_blocks.model_dump(mode="json")
    # Step 12 / PR-12a C7-4 — same rule, same reason: declared implementor
    # science changes what the model is asked, so it changes the run's
    # identity. ADDITIVE WHEN DECLARED, so undeclared fingerprints are
    # byte-unchanged.
    if implementor_blocks is not None:
        payload["implementor_blocks"] = implementor_blocks.model_dump(mode="json")
    # Step 12 / PR-12d, seam A (ruling A1) — the task-instance CONFIG is
    # semantic: `manifest_path` decides which images a Pets run trains on and
    # `clips_path` which clips DAVIS uses, so two runs configured differently
    # are not the same run. Without this, changing either would leave resume
    # identity unchanged — "a second hole, of the same family as the one being
    # closed". ADDITIVE WHEN NON-EMPTY, on the same precedent as the four
    # additions above, so every existing composed manifest's fingerprint is
    # byte-unchanged and its resume still validates.
    if task_data_path_config:
        payload["task_data_path_config"] = task_data_path_config
    # arXiv #255 — the registered implementation's SOURCE CONTENT is semantic:
    # changing Pets' CROP_SIZE changes every tensor the run sees, so two runs
    # whose implementation bytes differ are not the same run (the paper's
    # S13/S14 comparability discipline). The value is the identity CAPTURED at
    # registration (`registered_content_identity`), NEVER a fresh file read —
    # F-12bc-7: a spawn-time re-read follows the very edit it exists to catch.
    # Mechanically additive-when-present like the six keys above, but state
    # the consequence honestly: a composed run's implementation is ALWAYS
    # registered by resolution time, so every PRE-EXISTING composed
    # fingerprint MOVES under this key. That is the point — those
    # fingerprints did not pin the content, so their runs are not provably
    # comparable to post-#255 runs; the existing incomparable-resume
    # machinery refuses the cross (acceptance row 3), the same declared
    # consequence as PR-12a's `proposal_blocks:` precedent.
    if task_data_path_content_identity is not None:
        payload["task_data_path_content_identity"] = task_data_path_content_identity
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The composition edge
# ---------------------------------------------------------------------------


def _compose_deliverable_naming(raw: dict[str, Any], manifest_path: str):
    """The OPTIONAL ``deliverable:`` section → a ``DeliverableNaming``.

    Step 11 C6 / R-11-3. The Deliverable Contract stays the sole naming
    OWNER: this reads a declaration and hands it to
    :class:`~execute_tools.deliverable_spec.DeliverableNaming`, whose own
    fail-closed validators reject an empty prefix, a padded prefix, a glob
    metacharacter in the stem or an extension that is not a dotted suffix.
    Not one of those rules is restated here — a second naming authority is
    exactly what §9.2 forbids.

    Absent section ⇒ ``None`` ⇒ the shipped TIDMAD naming, byte-identical.
    """
    from execute_tools.deliverable_spec import DeliverableNaming

    section = raw.get("deliverable")
    if section is None:
        return None
    if not isinstance(section, dict):
        raise TaskCompositionError(
            f"section 'deliverable' in {manifest_path!r} must be a mapping; "
            f"got {type(section).__name__}."
        )
    try:
        return DeliverableNaming(**section)
    except Exception as exc:
        raise TaskCompositionError(
            f"the 'deliverable' declaration in {manifest_path!r} is not a "
            f"valid DeliverableNaming: {type(exc).__name__}: {exc}"
        ) from exc


def compose_deliverable_naming_from_manifest(manifest_path: str):
    """The run's DECLARED deliverable naming, or ``None``. Step 11 C6.

    The child-process counterpart of the naming half of
    :func:`compose_run_task_bindings`, and only that half — the sibling of
    :func:`compose_metric_from_manifest`, reading the same transported
    manifest. ``None`` means the task declared no ``deliverable:`` section
    and the shipped TIDMAD naming applies, byte-identically.
    """
    resolved_manifest = os.path.abspath(manifest_path)
    return _compose_deliverable_naming(_read_manifest(resolved_manifest), resolved_manifest)


def compose_metric_from_manifest(manifest_path: str) -> EvaluationMetric:
    """The run's PRIMARY metric, composed from its manifest. Step 11 C5.

    The child-process counterpart of the metric half of
    :func:`compose_run_task_bindings`, and deliberately **only** that half:
    a scoring subprocess must not re-resolve the profile, the Health family
    or the interpretation blocks, all of which either already cross by
    their own transport or have no consumer there.

    It is a thin public entry over :func:`_compose_metric` — the SAME
    declaration→spec→implementation authority the parent used — so Step 11
    transports the binding and derives nothing (**R-11-4**). Every
    fail-closed branch is that function's: an unreadable manifest, a
    missing section, an invalid ``MetricSpec``, an unloadable symbol or an
    implementation that is not an ``EvaluationMetric`` all raise
    :class:`TaskCompositionError`.

    Why the manifest PATH rather than a serialized metric: the composition
    retains the resolved metric INSTANCE, not the declaration it was built
    from, and an instance cannot cross a process boundary. Re-composing the
    section from the run's own manifest is the same pattern the scoring
    child already uses for its deliverable spec — reconstruct from what
    crosses, one derivation, the same value the parent holds — with the
    TIDMAD-shaped source replaced by the run's declared one.

    Raises:
        TaskCompositionError: the metric could not be composed. A composed
            run MUST NOT silently score with TIDMAD's metric; that is the
            C-P56-1 failure class one layer down.
    """
    resolved_manifest = os.path.abspath(manifest_path)
    raw = _read_manifest(resolved_manifest)
    metric, _declaration, _plugin = _compose_metric(
        _section(raw, "metric", resolved_manifest), os.path.dirname(resolved_manifest)
    )
    return metric


def compose_task_data_path_from_manifest(manifest_path: str) -> TaskDataPath:
    """The run's DECLARED task data path, composed from its manifest.

    Step 12 / PR-12bc C3. The sibling of :func:`compose_metric_from_manifest`,
    reading the same transported manifest through the same authority
    (:func:`_compose_task_data_path`) the parent used — so a child DERIVES
    nothing, exactly as R-11-4 requires. Composition registers the
    implementation as a side effect, which is what makes the id resolvable
    for the rest of the child's life.

    Raises:
        TaskCompositionError: the manifest is unreadable, declares no
            ``task_data_path`` section, or the section could not be composed.
    """
    resolved_manifest = os.path.abspath(manifest_path)
    raw = _read_manifest(resolved_manifest)
    impl, _plugin, _config = _compose_task_data_path(
        _section(raw, "task_data_path", resolved_manifest),
        os.path.dirname(resolved_manifest),
    )
    return impl


def resolve_child_task_data_path(
    task_data_path_id: str,
    *,
    identity: str | None = None,
    manifest_path: str | None = None,
) -> TaskDataPath:
    """Resolve a transported id in a child, composing it if it is not built in.

    Step 12 / PR-12bc C3 — §E.1's four-row table, and the reason an
    OUT-OF-TREE task can reach a training or inference subprocess at all.
    Before this, a child resolved the transported id through the registry
    alone, and the registry holds exactly what the child's bootstrap imported:
    the three built-ins. An externally declared implementation was therefore
    resolvable in the parent and unresolvable in every child it spawned::

        transported id -> registry lookup
                          |- HIT  -> verify identity == parent-pinned
                          |           match     -> use it
                          |           divergent -> REFUSE (C2)
                          |- MISS -> compose `task_data_path` from the
                          |           transported manifest via the SAME
                          |           authority, then verify as above
                          '- neither registered nor composable -> REFUSE,
                                      naming BOTH facts

    **A MISS is a membership question, never an exception to catch.** Row 2's
    identity refusal and row 4's resolution refusal are different failures,
    and treating the first as a miss would silently re-compose a task whose
    registration diverged — turning C2's refusal into a fallback, which is the
    C-P56-1 shape.

    Args:
        task_data_path_id: the id the parent transported.
        identity: the parent-pinned content identity, if the parent pinned
            one. ``None`` is an ABSENCE OF A CLAIM (a pre-C2 parent), not a
            passing check.
        manifest_path: the transported manifest, if the run is composed.
            ``None`` means an un-composed run, whose id must already be built
            in.

    Raises:
        TaskDataPathIdentityError: the implementation resolved here is not the
            one the parent pinned.
        TaskDataPathResolutionError: the id is neither registered nor
            composable. The message names both facts, because "unknown id" and
            "no manifest reached me" send an operator to different files.
        TaskCompositionError: a manifest was transported but could not be
            composed.
    """
    from execute_tools.task_data_path import (
        TaskDataPathResolutionError,
        registered_task_data_path_ids,
        resolve_transported_task_data_path,
        verify_transported_identity,
    )

    registered = registered_task_data_path_ids()
    if task_data_path_id in registered:
        # Rows 1 and 2 — the existing child-side authority, unchanged.
        return resolve_transported_task_data_path(task_data_path_id, identity)

    if manifest_path is None:
        raise TaskDataPathResolutionError(
            f"task data path {task_data_path_id!r} is not registered in this "
            f"child process, and no task manifest was transported to it.\n"
            f"  registered here: {sorted(registered)}\n"
            f"  manifest:        (none)\n"
            f"Both facts matter: an id the child cannot find AND no "
            f"declaration it could compose one from. A composed run emits "
            f"--task_manifest; an un-composed run's id must be a built-in."
        )

    # Rows 3 and 4 — compose from the run's own declaration. Registration is
    # the composer's side effect, so a later resolve in this process hits.
    composed = compose_task_data_path_from_manifest(manifest_path)
    declared = composed.task_data_path_id
    if declared != task_data_path_id:
        raise TaskDataPathResolutionError(
            f"task data path {task_data_path_id!r} is not registered in this "
            f"child process, and the transported manifest declares "
            f"{declared!r} instead.\n"
            f"  registered here: {sorted(registered)}\n"
            f"  manifest:        {manifest_path}\n"
            f"The parent and the child are reading different declarations — "
            f"composing this one would run a task the parent never bound."
        )
    return verify_transported_identity(composed, identity)


_ACTIVE_TASK_MANIFEST_PATH: ContextVar[str | None] = ContextVar(
    "siderius_active_task_manifest_path", default=None
)


@contextmanager
def bind_task_manifest_path(manifest_path: str) -> Iterator[str]:
    """Bind the composed run's manifest path for the run scope. Step 11 C5.

    Narrow on purpose. It would be easy to bind the whole composition and
    let any call site help itself, and that is precisely what this module's
    own rule forbids — a value that already has an explicit path must not
    gain a second, ambient way to arrive. What is bound here is ONE
    transportable string, for ONE consumer: the argv fragment that lets the
    scoring child compose the run's declared metric instead of TIDMAD's.
    """
    token = _ACTIVE_TASK_MANIFEST_PATH.set(os.path.abspath(manifest_path))
    try:
        yield _ACTIVE_TASK_MANIFEST_PATH.get() or manifest_path
    finally:
        _ACTIVE_TASK_MANIFEST_PATH.reset(token)


_ACTIVE_COMPOSITION_FINGERPRINT: ContextVar[str | None] = ContextVar(
    "siderius_active_composition_fingerprint", default=None
)


@contextmanager
def bind_composition_fingerprint(fingerprint: str) -> Iterator[str]:
    """Bind the composed run's semantic fingerprint for the run scope.

    Step 11 C8 / R-11-9. Narrow, like the manifest path beside it: ONE
    string, for ONE consumer — the single validate-and-persist seam that
    stamps every experiment record, so no record-construction site can
    forget it. That is the reason `candidate_id` is stamped there too.
    """
    token = _ACTIVE_COMPOSITION_FINGERPRINT.set(fingerprint)
    try:
        yield fingerprint
    finally:
        _ACTIVE_COMPOSITION_FINGERPRINT.reset(token)


def active_composition_fingerprint() -> str | None:
    """The bound fingerprint, or ``None`` for an un-composed run."""
    return _ACTIVE_COMPOSITION_FINGERPRINT.get()


def active_task_manifest_path() -> str | None:
    """The bound manifest path, or ``None`` — **no** legacy fallback.

    Same ``active_*`` contract as ``active_task_data_path`` and
    ``active_physical_data_root``: the transport must not emit a flag on
    the strength of a fallback, or every legacy child's argv changes.
    """
    return _ACTIVE_TASK_MANIFEST_PATH.get()


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

    impl, impl_plugin, task_data_path_config = _compose_task_data_path(
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

    # Step 10 / P2b — the OPTIONAL observational secondaries, resolved through
    # the same `_compose_metric` authority immediately beside the primary so
    # the collision check has the primary's id and nothing later can reorder
    # the two.
    (
        secondary_metrics,
        secondary_declarations,
        secondary_plugins,
        secondary_declaration_paths,
    ) = _compose_secondary_metrics(raw, manifest_dir, metric.spec.id)
    plugins.extend(secondary_plugins)
    for _index, _path in enumerate(secondary_declaration_paths):
        source_paths[f"secondary_metric_declaration[{_index}]"] = _path

    # Step 12 / PR-12d, seam P — the OPTIONAL model-plugin declaration. Its
    # resolved identities join the SAME `plugins` set the fingerprint already
    # hashes, so editing a pack plugin moves the run's identity and fails a
    # resume closed, and a manifest that declares none is byte-unchanged.
    model_plugin_binding, model_plugin_root = _compose_model_plugins(raw, manifest_dir)
    loss_plugin_roots, loss_plugin_root = _compose_loss_plugins(raw, manifest_dir)
    if model_plugin_binding is not None:
        source_paths["model_plugins"] = str(model_plugin_root)
        plugins.extend(
            ResolvedPluginRef(
                configured_ref=f"{plugin.configured_ref}/{plugin.member}",
                symbol=plugin.model_type,
                content_sha256=plugin.content_sha256,
                absolute_path=plugin.absolute_path,
            )
            for plugin in model_plugin_binding.plugins
        )
    # Step 12 / PR-12d D4c: the declared loss ROOT joins `source_paths`, so the
    # run's identity records where its objective came from. The individual loss
    # files are deliberately NOT hashed into `plugins` the way model plugins
    # are: a loss is resolved by NAME at training time from whatever the root
    # holds, so hashing every file in the directory would make the run identity
    # depend on losses it never loads.
    if loss_plugin_root is not None:
        source_paths["loss_plugins"] = str(loss_plugin_root)

    # Step 12 / PR-12d, F-12d-31 wire C — the AUTHORITATIVE objective's content
    # identity. Appended to the SAME `plugins` set the fingerprint already
    # hashes, exactly as seam P does for model plugins, so editing the declared
    # objective moves the run's identity and fails a resume closed. Declaring an
    # authoritative objective while leaving the selected behaviour outside
    # semantic identity would be an incomplete contract — which is why the
    # operator ruled the three wires land together.
    #
    # This is NOT the "hash every loss in the root" rule the comment above
    # rejects: exactly ONE file is hashed, the one the manifest explicitly
    # named, and only when a manifest names it. A task declaring no objective
    # adds no plugin entry and its fingerprint is byte-unchanged.
    composed_objective, objective_ref = _compose_objective(raw, manifest_dir)
    if objective_ref is not None:
        source_paths["objective"] = str(objective_ref.absolute_path)
        plugins.append(objective_ref)

    # Step 11 C6 — the OPTIONAL naming declaration, validated by the
    # Deliverable Contract's own type. Absent ⇒ the shipped TIDMAD naming.
    deliverable_naming = _compose_deliverable_naming(raw, resolved_manifest)

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
    # Step 12 / PR-12a C7 (D-12a-6) — same shape, same `source_paths` entry,
    # so the declaration participates in the semantic fingerprint exactly as
    # its sibling does: editing the prose moves the run's identity.
    proposal_blocks, proposal_path = _compose_proposal_blocks(raw, manifest_dir)
    if proposal_path is not None:
        source_paths["proposal_blocks"] = proposal_path
    implementor_blocks, implementor_path = _compose_implementor_blocks(raw, manifest_dir)
    if implementor_path is not None:
        source_paths["implementor_blocks"] = implementor_path

    task_config_section = _section(raw, "task_config", resolved_manifest)
    description, contract, _values = _compose_task_config(
        task_config_section, manifest_dir, profile
    )
    source_paths["task_config"] = _resolve_path(
        _require(task_config_section, "config", "task_config"), manifest_dir
    )

    from execute_tools.deliverable_spec import task_names_its_own_deliverables
    from execute_tools.task_data_path import registered_content_identity

    # arXiv #268 (the paper's discussion (13): "a fail-open default
    # inconsistent with the rest of the manifest's semantics; reported here
    # as a defect under repair" — this is the repair). A COMPOSED manifest
    # must either declare its indexed `deliverable:` naming or bind an
    # implementation that names its artifacts itself (module-level
    # `deliverable_name`, the F-A4-1 capability). Omission by a task with
    # NEITHER used to resolve the anchor task's shipped template silently —
    # the one manifest key whose omission took a default instead of refusing.
    # The legacy un-composed path is untouched (it is the anchor task's own
    # regime); every shipped composed manifest now satisfies one of the two
    # legal shapes.
    if deliverable_naming is None and not task_names_its_own_deliverables(impl):
        raise TaskCompositionError(
            f"manifest {resolved_manifest!r} declares no 'deliverable:' section and its "
            f"task_data_path {impl.task_data_path_id!r} does not name its own artifacts "
            "(no module-level deliverable_name). Omission used to resolve the anchor "
            "task's indexed template silently — a fail-open default the manifest's "
            "omission-vs-named-absence semantics forbid (arXiv #268). Declare "
            "'deliverable:' explicitly, or implement deliverable_name beside the "
            "task_data_path implementation."
        )

    # arXiv #255 — fail closed, never omit: by this line the implementation
    # has been RESOLVED, so its registration capture must exist. An absent
    # capture means the registration lifecycle broke; silently omitting the
    # content key would ship a fingerprint without the pin (the quiet
    # weakening the review criterion forbids), and recomputing from the file
    # here would be F-12bc-7 one layer up. Refuse and say why.
    impl_content_identity = registered_content_identity(impl.task_data_path_id)
    if impl_content_identity is None:
        raise TaskCompositionError(
            f"task_data_path {impl.task_data_path_id!r} resolved but has no "
            "registration-captured content identity; the fingerprint cannot "
            "pin the implementation's bytes. This is a registration-lifecycle "
            "defect, not a configuration error — refusing rather than "
            "composing an unpinned fingerprint (arXiv #255)."
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
        secondary_metric_declarations=secondary_declarations,
        deliverable_naming_declaration=(
            deliverable_naming.model_dump(mode="json") if deliverable_naming is not None else None
        ),
        proposal_blocks=proposal_blocks,
        implementor_blocks=implementor_blocks,
        task_data_path_config=task_data_path_config,
        task_data_path_content_identity=impl_content_identity,
    )

    return RunTaskComposition(
        task_data_path=impl,
        dataset_profile=profile,
        metric=metric,
        task_health_binding=task_health_binding,
        interpretation_blocks=interpretation_blocks,
        proposal_blocks=proposal_blocks,
        implementor_blocks=implementor_blocks,
        task_description=description,
        forward_contract=contract,
        semantic_fingerprint=fingerprint,
        provenance=CompositionProvenance(
            manifest_path=resolved_manifest,
            source_paths=source_paths,
            plugins=tuple(plugins),
        ),
        secondary_metrics=secondary_metrics,
        deliverable_naming=deliverable_naming,
        model_plugins=model_plugin_binding,
        loss_plugins=loss_plugin_roots or None,
        objective=composed_objective,
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


class CompositionDataRootMissing(RuntimeError):
    """A composed run did not declare where its data physically lives.

    Step 11 C4 / R-11-8. Before Step 11 every child fell back to the
    import-time ``TIDMAD_DATA_DIR``, so a composed run read TIDMAD's data
    no matter what it had declared and looked entirely normal doing it.
    After Step 11 that fallback is **legacy-only** and must never be
    consulted for a composed run — so a composition with no root is a
    refusal at the binding edge, before any LLM call or GPU minute.

    Removing the import-time fallback itself is deliberately NOT Step-11
    scope (R-11-8): CI resolves the root from the tracked template and
    creates no real config, so removing it would break collection
    repo-wide. Stopping the composed path from DEPENDING on it comes
    first; retiring it comes second.
    """


@contextmanager
def bind_run_task_composition(
    composition: RunTaskComposition | None,
    *,
    physical_data_root: str | None = None,
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

    from execute_tools.data_paths import bind_physical_data_root
    from execute_tools.dataset_config import bind_dataset_profile
    from execute_tools.evaluation_metric import bind_run_metric, bind_run_secondary_metrics
    from execute_tools.task_data_path import bind_task_data_path
    from workflows.task_config import bind_task_config

    if not physical_data_root:
        raise CompositionDataRootMissing(
            "a composed run must declare where its data physically lives. "
            "Supply --data_dir <path>. Without it every subprocess child "
            "falls back to the import-time TIDMAD_DATA_DIR, so the run reads "
            "TIDMAD's data whatever it composed — silently (Step 11 R-11-8)."
        )

    with ExitStack() as stack:
        # Step 11 C4 — FIRST on the stack, so it is bound before any other
        # authority and unwinds last. `bind_physical_data_root` validates
        # fail-closed through `resolve_dataset_dir`, the ONE such rule, so a
        # missing / placeholder / non-directory root refuses HERE rather
        # than in a child that has already been spawned.
        stack.enter_context(
            bind_physical_data_root(physical_data_root, purpose="this composed run")
        )
        # Step 11 C5 — the manifest path, so the scoring child can compose
        # the run's DECLARED metric instead of unconditionally deriving
        # TIDMAD's (R-11-4). One string, one consumer.
        stack.enter_context(bind_task_manifest_path(composition.provenance.manifest_path))
        # Step 11 C8 / R-11-9 — so every record this run persists carries the
        # identity the ingress validator checks.
        stack.enter_context(bind_composition_fingerprint(composition.semantic_fingerprint))
        # Step 11 C6 — bound only when the task DECLARED naming. An
        # un-declared composition binds nothing, so `resolve_deliverable_naming`
        # returns the shipped TIDMAD naming and every glob is byte-identical.
        if composition.deliverable_naming is not None:
            from execute_tools.deliverable_spec import bind_deliverable_naming

            stack.enter_context(bind_deliverable_naming(composition.deliverable_naming))
        # Step 12 / PR-12d, seam P — bound only when the task DECLARED model
        # plugins, so an un-declared composition binds nothing and every
        # child's plugin environment is byte-identical to its pre-seam-P
        # value. Placed before the data path because a task's own model
        # implementation must be reachable by the time anything asks the run
        # to build or execute against a scope.
        if composition.model_plugins is not None:
            from ml_models.plugin_binding import bind_run_model_plugins

            stack.enter_context(bind_run_model_plugins(composition.model_plugins))
        if composition.loss_plugins is not None:
            from ml_models.plugin_binding import bind_run_loss_plugin_roots

            stack.enter_context(bind_run_loss_plugin_roots(composition.loss_plugins))
        stack.enter_context(bind_task_data_path(composition.task_data_path))
        stack.enter_context(bind_dataset_profile(composition.dataset_profile))
        stack.enter_context(bind_run_metric(composition.metric))
        # Step 10 / P2b — the declared observational secondaries ride the SAME
        # stack as the primary, so they unwind together on every path
        # including an exception. A composed task with none binds `()`, which
        # is the same value an un-composed run resolves.
        stack.enter_context(bind_run_secondary_metrics(composition.secondary_metrics))
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

    from execute_tools.data_paths import active_physical_data_root
    from execute_tools.dataset_config import resolve_dataset_profile
    from execute_tools.evaluation_metric import (
        resolve_bound_run_metric,
        resolve_bound_run_secondary_metrics,
    )
    from execute_tools.task_data_path import active_task_data_path
    from workflows.task_config import resolve_bound_task_config

    unbound: list[str] = []
    if active_task_data_path() is not composition.task_data_path:
        unbound.append("task_data_path")
    # Step 11 C4 — the root is not ON the composition (a host path is
    # execution provenance, never fingerprint material — R-11-7), so what
    # is checked is that ONE is bound at all. Unbound means every child
    # would silently resolve TIDMAD's import-time constant.
    if active_physical_data_root() is None:
        unbound.append("physical_data_root")
    if resolve_dataset_profile() is not composition.dataset_profile:
        unbound.append("dataset_profile")
    if resolve_bound_run_metric() is not composition.metric:
        unbound.append("metric")
    # Step 10 / P2b — identity per entry, in order. A composed run whose
    # secondaries are NOT active would evaluate none of them and then stamp a
    # declared set the records cannot possibly satisfy, projecting the whole
    # declared family as a named absence: silent, and indistinguishable from a
    # task that genuinely declared nothing.
    if resolve_bound_run_secondary_metrics() != composition.secondary_metrics:
        unbound.append("secondary_metrics")
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
