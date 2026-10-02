# execute_tools/health_checks/_composition.py
"""Framework policy + task-owned config → the ONE pinned effective artifact.

**What composition is for.** The framework owns operational policy — what a
gate DOES. The task owns its science — which gates exist, what they measure,
where the boundaries are, and why. Until 08b both lived in
`configs/health_checks.yaml`, so a second task could not exist without
editing framework source. This module is where the two halves meet, and it
meets them in exactly one place so there is never a second answer.

**One definition per field** (§3.7). The task selects a
:class:`~execute_tools.health_checks._task_health_config.HealthDisposition`
KEY; the framework derives every operational consequence from it::

    blocking   -> gate_role=blocking,      after_round=every,
                  short_circuit=true,      on_pass=continue,
                  on_fail=invalidate_round, aggregation=all_pass

    recording  -> gate_role=observational, after_round=every,
                  short_circuit=false,     on_pass=continue,
                  on_fail=continue

A task cannot state any of the OPERATIONAL fields, so the conflicting-copies
failure mode is structurally impossible rather than resolved by a precedence
rule. The two shapes are not an invention: read verbatim at master
``a226495b``, the six shipped gates have exactly these two policy shapes and
nothing else. (One VALUE inside the blocking shape has since moved by
operator decision: the C2 flip, 2026-08-26, set ``aggregation`` from
``any_pass`` to ``all_pass``; the field set is unchanged.)

``aggregation`` is the single exception, and it is an exception to the
OWNERSHIP, not to the rule against unresolved precedence (F-SCAND-2). It is
not derived from the disposition — it is how a gate turns per-file evidence
into one verdict, which is the strictness of the measurement and therefore
task science. The framework value above is its DEFAULT: a roster entry that
declares ``aggregation`` keeps its own, an entry that stays silent gets this
one, and that sentence is the complete precedence rule. See
``TASK_DECLARABLE_POLICY_KEYS``.

**Three binding states, never two** (§3.10). "The caller did not mention a
task binding" and "the caller states there is no task binding" are different
claims and must not collapse — because collapsing them means a task that
deliberately declares no health silently inherits another task's family,
which is the synthesized-evidence failure the parent §6a.5 forbids::

    A. LEGACY OMITTED   the pre-08b compatibility path. Byte-identical
                        output. NOT the extension mechanism.
    B. EXPLICIT NONE    a NAMED absence, recorded in the pinned artifact.
                        Never falls back to another task's family.
    C. EXPLICIT BINDING load, resolve and compose the named task config.

The three are distinguished by a typed sentinel and the parameter's default
state — never by a task name, which appears nowhere in this module.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.layout import checkout_root
from execute_tools.health_checks._plugin_binding import ResolvedHealthPlugin
from execute_tools.health_checks._policy_resources import read_default_policy
from execute_tools.health_checks._task_health_config import (
    TASK_DECLARABLE_POLICY_KEYS,
    HealthRosterEntry,
    TaskHealthConfig,
    validate_aggregation_config,
)
from execute_tools.health_checks.schemas import GateAction


class HealthBindingState(StrEnum):
    """The two non-path binding states (§3.10 A and B).

    State C is expressed by passing a path instead of one of these, so the
    three states are one typed union rather than two booleans whose
    combinations include impossible ones.
    """

    LEGACY_OMITTED = "legacy_omitted"
    """The caller said nothing about a task Health binding.

    The DEFAULT, and deliberately so: every pre-08b call site keeps working
    unchanged and produces a byte-identical artifact. C5 redirects this state
    to TIDMAD's task-owned config, once that config exists — which is why C4
    and C5 are separate commits rather than one."""

    EXPLICIT_NONE = "explicit_none"
    """The caller states this task has no Health binding.

    A legal, NAMED absence — recorded in the pinned artifact so a reader can
    tell "no gates were configured" from "gates were configured and passed".
    It must never be satisfied by falling back to another task's family."""


TaskHealthBinding = HealthBindingState | str
"""Either a binding state, or a path to a task health config (state C)."""


SIDERIUS_ROOT = checkout_root()
"""This checkout's repository root, derived from this file's own location.

**F-7.** The two shipped-config defaults below and in ``config.py`` were
RELATIVE paths, so they resolved against the caller's working directory. The
stage scripts never ``cd``, so a campaign launched from anywhere but the repo
root raised ``FileNotFoundError: 'configs/task_health/tidmad.yaml'`` and
refused every band scan and every Stage-2 finalize. CLAUDE.md's portability
rule names exactly this: path resolution derives from the file's own location
or a supplied root, never from the caller's cwd.

**Correction (release remediation N-1).** The sentence that stood here — "Every
sibling authority in the repository already anchors this way; these two were
the stragglers" — was FALSE when it was written, and it was false about the
three constants whose own comments name THIS one as the idiom they copy:
``LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG``,
``LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG`` and
``LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG`` all stayed cwd-relative, and the
un-composed branch of ``workflows/model_exploration.py`` calls their
fail-closed loaders zero-arg — so the identical launch geometry killed the
proposer, the implementor and the interpreter. They are anchored now
(``agent/prompt_templates/_task_blocks_loader.SIDERIUS_ROOT``), and the
property is stated executably in
``tests/unit/guardrails/test_cwd_independent_shipped_defaults.py``, which
DISCOVERS the constants instead of listing them: a prose claim about "every
sibling" is precisely the kind that stops being true with nobody noticing."""


class DispositionPolicy(BaseModel):
    """What the FRAMEWORK does for one disposition. Operator policy surface.

    Every field here is one a task may not state (§3.7), which is what makes
    the ownership split structural rather than conventional.

    Values live in the packaged default or an explicitly selected policy
    YAML, not a second Python table. The optional observe-only policy differs
    from the default only in blocking ``on_fail``. The gate roster remains
    task-owned; selecting a different consequence policy never selects a task.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_role: Literal["blocking", "observational"]
    after_round: int | Literal["every"] | list[int] = "every"
    short_circuit: bool
    on_pass: GateAction
    on_fail: GateAction
    check_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-check policy keys the framework injects into every gate of "
            "this disposition. ``aggregation`` lives here: every shipped "
            "blocking gate carries ``all_pass`` (the C2 flip, "
            "operator-frozen 2026-08-26; ``any_pass`` before) while no "
            "recording gate carries it. Since F-SCAND-2 the value is a "
            "DEFAULT for that one key — a roster entry declaring "
            "``aggregation`` keeps its own, and every entry that stays "
            "silent still gets this. Every other key here is unconditional."
        ),
    )

    @field_validator("check_config")
    @classmethod
    def _declared_aggregation_is_an_implemented_mode(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Refuse invalid defaults before composition can turn them into Health errors."""
        return validate_aggregation_config(value)


class _DefaultPolicyDocument(BaseModel):
    """The required packaged default, not the permissive external root schema."""

    health_policy: dict[str, DispositionPolicy] = Field(min_length=1)


def default_disposition_policy() -> dict[str, DispositionPolicy]:
    """Lazily validate the single default authority when it is needed.

    No module-import I/O or mutable shared table: complete explicit policies
    remain independent of the packaged default, including a damaged install.
    """
    return _DefaultPolicyDocument.model_validate(read_default_policy()).health_policy


class HealthCompositionError(RuntimeError):
    """Framework policy and task config cannot be composed coherently."""


VALUE_SCALE_PARAMETER: str = "value_scale_units_per_sample"
"""Check-config key carrying the task's numerical value scale.

The FACTOR the arithmetic needs, delivered as a parameter beside the
thresholds. Before 08b each of four check modules held its own
``_MV_PER_LSB = 40.0 / 128.0`` literal that nothing declared — so the axis
could not be required without flipping TIDMAD's std checks to inapplicable,
which is why 08a had to leave it absent."""

VALUE_SCALE_UNIT_PARAMETER: str = "value_scale_unit"
"""Check-config key carrying the unit the factor converts INTO.

Travels with the factor, never separately: a number without its unit is how
a millivolt threshold silently becomes a volt threshold."""

SYMBOL_CARDINALITY_PARAMETER: str = "symbol_cardinality"
"""Check-config key carrying the task's declared symbol-alphabet size.

An injected scientific FACT (Step 08c §3.3), with exactly one authority:
``TaskHealthFacts.symbol_cardinality``. It is NOT a threshold — it never
appears in ``threshold_parameter_names`` (the 08a ``peek_samples``
lesson) — and it is never independently authored in gate parameters."""


INJECTABLE_AXIS_PARAMETERS: dict[str, tuple[str, ...]] = {
    "value_scale_unit": (VALUE_SCALE_PARAMETER, VALUE_SCALE_UNIT_PARAMETER),
    "symbol_cardinality": (SYMBOL_CARDINALITY_PARAMETER,),
}
"""The FROZEN table of injectable fact axes (Step 08c §3.3).

Injection is declaration-driven AND table-bounded: a check receives an
axis's parameters iff its declaration requires that axis AND the axis has
an entry here. An axis without a frozen injection rule injects nothing —
"every FACT_AXES value becomes a check parameter" is census-refused.
Growing this table is a framework decision requiring a task that forces
it, exactly like growing ``FACT_AXES`` itself."""


INJECTED_PARAMETER_KEYS: frozenset[str] = frozenset(
    key for keys in INJECTABLE_AXIS_PARAMETERS.values() for key in keys
)
"""Every check-config key composition may inject.

A task roster may not hand-author ANY of these (§3.3): composition refuses
the collision deterministically rather than silently overwriting in either
direction. Derived from the frozen table so the two can never disagree."""


def compose_gate(
    entry: HealthRosterEntry,
    health_peek_files: tuple[int, ...],
    policy_table: dict[str, DispositionPolicy] | None = None,
    injected_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One roster entry + framework policy → one gate, as a plain dict.

    A dict rather than a ``GateConfig`` because this is the SERIALIZED shape
    the pinned artifact carries; building the model here and dumping it again
    would create a second serialization to keep in step with the first.

    Args:
        entry: the task's roster entry.
        health_peek_files: the task's declared peek set, injected only into
            entries that opted in. An entry that did not opt in keeps its
            check's own default file source — injecting one everywhere would
            move the recording gates from every file onto a small triplet,
            which is a policy change rather than an ownership change.
        policy_table: the framework's disposition policy; the built-in
            default when the framework config declares none. Its
            ``check_config`` is unconditional except for the keys in
            ``TASK_DECLARABLE_POLICY_KEYS``, where it is the default the
            entry may override.
        injected_parameters: the declaration-driven fact parameters for this
            entry's check, per the frozen ``INJECTABLE_AXIS_PARAMETERS``
            table. See :func:`injected_parameters_for`.

    Raises:
        HealthCompositionError: the framework policy declares no entry for
            this disposition — refused rather than defaulted, because
            guessing what a gate DOES is the one thing composition must
            never do. Also raised when the entry hand-authors an INJECTED
            parameter key (§3.3): before this refusal existed, the update
            order below silently overwrote the authored value, and a silent
            winner in either direction is a hazard, not a resolution.
    """
    table = policy_table if policy_table is not None else default_disposition_policy()
    policy = table.get(entry.disposition.value)
    if policy is None:
        raise HealthCompositionError(
            f"Gate {entry.gate_id!r} declares disposition "
            f"{entry.disposition.value!r}, for which the framework config "
            f"declares no policy. Known dispositions: {sorted(table)}."
        )
    authored_injected = sorted(INJECTED_PARAMETER_KEYS & entry.parameters.keys())
    if authored_injected:
        raise HealthCompositionError(
            f"Gate {entry.gate_id!r} hand-authors injected parameter key(s) "
            f"{authored_injected} in its parameters. These keys are "
            f"composition-owned facts injected from the task's declarations "
            f"(value_scale, facts.symbol_cardinality); author the "
            f"declaration instead of the parameter."
        )
    check_config: dict[str, Any] = dict(entry.parameters)
    # Framework policy fills every key the entry did not declare. For the
    # keys in TASK_DECLARABLE_POLICY_KEYS an authored value WINS — that is
    # the whole precedence rule, and F-SCAND-2 is why it exists: while the
    # framework's value was unconditional, one number governed every
    # blocking gate of every task and no roster could tighten one gate
    # alone. Every other policy key stays unconditional, so the operator's
    # observe-mode lever over what a failure DOES is untouched. An entry
    # that declares nothing composes byte-identically to before.
    declared_policy = TASK_DECLARABLE_POLICY_KEYS & entry.parameters.keys()
    check_config.update(
        {key: value for key, value in policy.check_config.items() if key not in declared_policy}
    )
    if entry.uses_health_peek_files:
        check_config["peek_file_indices"] = list(health_peek_files)
    if injected_parameters:
        check_config.update(injected_parameters)
    return {
        "id": entry.gate_id,
        "gate_role": policy.gate_role,
        "after_round": policy.after_round,
        "short_circuit": policy.short_circuit,
        "checks": [{"name": entry.check, "config": check_config}],
        "on_pass": {"action": policy.on_pass.value},
        "on_fail": {"action": policy.on_fail.value},
        "reason": entry.reason,
    }


def value_scale_parameters_for(check_name: str, config: TaskHealthConfig) -> dict[str, Any]:
    """The scale parameters a check receives, or nothing.

    Injected only into checks whose DECLARATION requires the
    ``value_scale_unit`` axis — declaration-driven, never keyed on a check
    name or a task name. A check that does not declare the axis is not given
    a number it never asked for, and a check that DOES declare it cannot even
    reach ``run`` unless the task declared the unit, because 08a's
    applicability engine will already have ruled it inapplicable.

    Returns an empty dict when the task declares no scale, which is the same
    thing as the check being inapplicable — and is therefore never a silent
    fallback to some default number.
    """
    if config.value_scale is None:
        return {}
    if "value_scale_unit" not in _declared_axes(check_name):
        return {}
    return {
        VALUE_SCALE_PARAMETER: config.value_scale.units_per_sample,
        VALUE_SCALE_UNIT_PARAMETER: config.value_scale.unit,
    }


def _declared_axes(check_name: str) -> set[str]:
    """The fact axes the registered check's declaration requires."""
    from execute_tools.health_checks.registry import _REGISTRY

    skill = _REGISTRY.get(check_name)
    declaration = getattr(skill, "declaration", None)
    return {r.axis for r in getattr(declaration, "required_facts", ())}


def symbol_cardinality_parameters_for(check_name: str, config: TaskHealthConfig) -> dict[str, Any]:
    """The injected cardinality a check receives, or nothing (§3.3).

    Same declaration-driven shape as :func:`value_scale_parameters_for`:
    only a check requiring the ``symbol_cardinality`` axis receives the
    parameter, and only when the task declares one. A declaring check under
    a task with NO declared cardinality never reaches ``run`` anyway —
    applicability rules it inapplicable with the axis named — so the empty
    dict is never a silent fallback to some default alphabet.
    """
    if config.facts.symbol_cardinality is None:
        return {}
    if "symbol_cardinality" not in _declared_axes(check_name):
        return {}
    (parameter_key,) = INJECTABLE_AXIS_PARAMETERS["symbol_cardinality"]
    return {parameter_key: config.facts.symbol_cardinality}


def injected_parameters_for(check_name: str, config: TaskHealthConfig) -> dict[str, Any]:
    """Every parameter the frozen injectable-axes table grants this check.

    The union of the per-axis injectors, one per
    ``INJECTABLE_AXIS_PARAMETERS`` entry. An axis outside the table injects
    nothing, no matter what a declaration requires.
    """
    return {
        **value_scale_parameters_for(check_name, config),
        **symbol_cardinality_parameters_for(check_name, config),
    }


def compose_health_gates(
    config: TaskHealthConfig,
    policy_table: dict[str, DispositionPolicy] | None = None,
) -> list[dict[str, Any]]:
    """The task's roster, in declaration order, as composed gates.

    Order is PRESERVED rather than sorted: the sequence of gates is the
    sequence they fire in, which is a semantic property of the task's
    declaration and not a serialization detail. Determinism comes from the
    canonical key ordering applied when the body is dumped.
    """
    return [
        compose_gate(
            entry,
            config.health_peek_files,
            policy_table,
            injected_parameters_for(entry.check, config),
        )
        for entry in config.roster
    ]


def resolve_composed_gates(
    framework_gates: list[dict[str, Any]],
    task_config: TaskHealthConfig,
    policy_table: dict[str, DispositionPolicy] | None = None,
) -> list[dict[str, Any]]:
    """Which roster the run actually evaluates, for an explicit binding.

    Raises:
        HealthCompositionError: both the framework YAML and the task config
            declare a roster. Exactly ONE authority owns it — the framework
            file keeps policy only — so this is refused rather than merged or
            resolved by precedence. (Reachable only in the window between C4
            and C5, while the shipped YAML still carries TIDMAD's gates.)
    """
    task_gates = compose_health_gates(task_config, policy_table)
    if framework_gates and task_gates:
        raise HealthCompositionError(
            f"Both the framework config and the task health config declare a "
            f"roster ({len(framework_gates)} framework gate(s), "
            f"{len(task_gates)} task gate(s)). Exactly one authority owns the "
            f"roster: the framework file keeps policy only. Slim the framework "
            f"config, or remove the task roster."
        )
    return task_gates or framework_gates


def body_markers(
    binding: TaskHealthBinding,
    resolved_plugins: tuple[ResolvedHealthPlugin, ...],
) -> dict[str, Any]:
    """The non-gate keys the HASHED effective body carries, if any.

    **State A returns nothing at all**, so its body is the pre-08b document
    key for key. Any addition — even an empty list — would change the pinned
    sha of every existing workspace and force a needless re-materialization
    for runs whose Health behaviour did not change. The extra keys appear
    only when the run actually has something to say.

    The plugin set is folded in by CANONICAL identity — ``configured_ref`` +
    relative member + ``content_sha256``, never an absolute path — so two
    identical task packages checked out at different absolute paths pin ONE
    identity (§3.6), while edited plugin bytes correctly change it and a
    resume fails closed. Recording plugins only in the unhashed header would
    leave that last case silently accepted.
    """
    if binding is HealthBindingState.LEGACY_OMITTED:
        # C5: state A now composes from the legacy default task config, so
        # the pin records which path produced the roster. The sha therefore
        # MOVES at C5 — expected and authorised (Q-08b-2), with parity
        # measured on executed semantics rather than on bytes.
        markers: dict[str, Any] = {"task_health_binding": "legacy_default"}
        if resolved_plugins:
            markers["resolved_plugins"] = [p.canonical_identity() for p in resolved_plugins]
        return markers

    if binding is HealthBindingState.EXPLICIT_NONE:
        # A NAMED absence, in the HASHED body: "no task family was bound"
        # must be readable as a decision rather than inferred from an empty
        # gate list, which is also what a fully-passing run looks like.
        return {"task_health_binding": HealthBindingState.EXPLICIT_NONE.value}

    markers: dict[str, Any] = {"task_health_binding": "explicit"}
    if resolved_plugins:
        markers["resolved_plugins"] = [p.canonical_identity() for p in resolved_plugins]
    return markers
