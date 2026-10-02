# execute_tools/health_checks/_task_health_config.py
"""The task-owned Health configuration document (Step 08b, C1).

**What a task owns.** Until 08b, `configs/health_checks.yaml` carried
TIDMAD's roster, thresholds, peek set and science prose alongside the
framework's operational policy, so adding a task meant editing framework
source. This module is the document a TASK writes instead: its gate roster,
its thresholds, its dispositions, its peek files, its numerical value scale,
its plugin refs and its science prose. The framework file keeps policy only.

**Phase A only — authoring validation.** Design
``docs/design/generic_framework_upgrade/step_08_health_check_task_profile/
pr_08b_extension_architecture.md`` §3.1 freezes the contract this module
exists to honour::

    PHASE A — AUTHORING / SCHEMA VALIDATION        (no plugins loaded)
        field shape · non-empty ids · plugin-ref syntax
        duplicate roster entries · valid disposition names
        contradictory facts · unknown schema fields
        ACCEPTS any syntactically valid check/provider/capability id
        NEVER interprets an opaque capability value

               ↓  load declared plugins  ↓

    PHASE B — BINDING RESOLUTION                   (plugins loaded)
        resolve check ids · resolve provider ids
        validate capability exposure · validate family references
        UNRESOLVED  →  deterministic fail-closed startup error

A schema may not require an externally supplied identifier to EXIST, because
it necessarily does not exist until its plugin loads. So a roster naming an
unregistered check parses here and fails in Phase B (C3) — and the two
outcomes must stay different, because a configuration error is never
downgraded to a Health verdict (§3.2).

**Single-source ownership, made structural** (§3.7). A task selects a
:class:`HealthDisposition` KEY; it cannot state ``gate_role``, ``on_pass``,
``on_fail``, ``short_circuit``, severity or cadence at all. There is
therefore no second copy of an *operational* field to contradict the
framework's, and no precedence rule to get wrong — the failure mode is
structurally impossible rather than resolved.

**``aggregation`` is the one declarable exception** (F-SCAND-2). It was
excluded alongside the operational fields, but not for their reason:
nothing derives it from the disposition. It says how a gate combines
per-file evidence into one verdict — the strictness of a *measurement*,
which is task science, and which the shipped TIDMAD roster's own prose
argues about at length. Framework ownership had a concrete cost, recorded
on the row: one value governed every blocking gate of every task, so
``amplitude_collapse_blocking`` could not be made strict without making all
three strict. A task may now declare it per roster entry; see
:data:`TASK_DECLARABLE_POLICY_KEYS` for the precedence, which is stated
once and is not a guess. Declaring nothing is unchanged in every byte.

This document is task-owned TRUTH, so it has exactly one consumption path:
the binding/composition seam. C1 landed it inert with a guard asserting
nothing imported it; C2 wired it and the guard was INVERTED rather than
deleted (the 08a precedent) into an allowlist of seam modules. A check, a
runner or a script reading it directly would be a second reader deciding for
itself what a roster or a threshold means.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from execute_tools.health_checks._multi_file_peek import VALID_AGGREGATION_MODES
from execute_tools.health_checks.schemas import TaskHealthFacts


def validate_aggregation_config(value: dict[str, Any]) -> dict[str, Any]:
    """Validate an explicitly supplied aggregation without changing the mapping.

    Shared by task parameters and framework policy defaults. Presence matters:
    a missing key leaves default resolution to its owner; an explicit null is
    invalid. The executable aggregation vocabulary remains the sole authority.
    """
    if "aggregation" not in value:
        return value
    declared = value["aggregation"]
    if declared is None:
        raise ValueError(
            "aggregation is declared with no value. In YAML, a bare "
            "'aggregation:' parses to None. Give it a mode from "
            f"{sorted(VALID_AGGREGATION_MODES)}, or omit the key to leave "
            "default resolution to the containing configuration."
        )
    if not isinstance(declared, str) or declared not in VALID_AGGREGATION_MODES:
        raise ValueError(
            f"aggregation {declared!r} is not a rule this runtime implements; "
            f"valid modes: {sorted(VALID_AGGREGATION_MODES)}."
        )
    return value


class HealthDisposition(StrEnum):
    """What a roster entry's gate MEANS scientifically.

    The task's ONE policy-facing choice, and deliberately the ONLY one. The
    framework derives every operational consequence — ``gate_role``,
    ``on_pass``, ``on_fail``, ``short_circuit``, severity and cadence — from
    this key at composition (C4), so the task never states them and cannot
    disagree with them.

    Framework-owned vocabulary, exactly like
    :data:`~execute_tools.health_checks.schemas.FACT_AXES`: a new TASK picks
    an existing disposition and needs no new one. Growth is a framework
    decision requiring a task that forces it, never a per-task edit — which
    is what keeps this from becoming the closed task-semantic enum the
    roadmap's external-extensibility invariant forbids.

    The two members are not a guess: read verbatim at master ``a226495b``,
    both shipped configs have exactly TWO policy shapes and nothing else —
    every blocking gate is ``(blocking, every, short_circuit=true, continue,
    invalidate_round)`` and every recording gate is ``(observational, every,
    false, continue, continue)``.
    """

    BLOCKING = "blocking"
    """Decides whether the round's record is a valid candidate."""

    RECORDING = "recording"
    """Measures and records only; never invalidates anything."""


FRAMEWORK_OWNED_PARAMETER_KEYS: frozenset[str] = frozenset(
    {
        "gate_role",
        "on_pass",
        "on_fail",
        "short_circuit",
        "severity",
        "after_round",
        "peek_file_indices",
    }
)
"""Keys a task may never write into a roster entry's ``parameters``.

The first six are framework operational policy derived from the disposition
(§3.7). They are the operator's lever, not the task's: the shipped
``health_checks_baseline_observe_mode.yaml`` exists precisely to change
``on_fail`` for every gate at once, and a task able to state it would make
observe mode unenforceable. ``peek_file_indices`` is excluded for a
different reason: the task DOES own its peek set, but it owns it ONCE, as
:attr:`TaskHealthConfig.health_peek_files`, opted into per entry — a literal
list restated inside three entries would be three copies of one fact.

Rejecting these at authoring time is what makes §3.7's "exactly one
definition of each field" executable rather than aspirational.

``aggregation`` used to sit in this set and no longer does; see
:data:`TASK_DECLARABLE_POLICY_KEYS`. The two sets must stay disjoint — a key
in both would be refused here and honoured at composition — which
``test_no_key_is_both_refused_and_declarable`` enforces."""


TASK_DECLARABLE_POLICY_KEYS: frozenset[str] = frozenset({"aggregation"})
"""Check-config policy keys a task MAY declare, overriding the framework's.

Everything else the framework injects per disposition is unconditional. For
a key in this set the framework's value is a **default**: it is applied to
every roster entry that stays silent, and an entry that declares the key
keeps its own. That is the whole precedence rule, it lives here, and it is
the only one — the failure mode §3.7 forbids is two authorities with no
stated winner, not two authorities at all.

Why ``aggregation`` qualifies and the other seven do not: it is not derived
from the disposition and it is not an operator lever over what a failure
DOES. It decides how per-file evidence becomes one verdict, which is the
strictness of the measurement itself — task science, and the thing TIDMAD's
own roster prose has been arguing about since M9. F-SCAND-2 records the cost
of getting this wrong: one framework value governed every blocking gate of
every task, so a task could not tighten one gate without tightening all of
them.

Growing this set is a framework decision requiring a task that forces it,
exactly like growing :class:`HealthDisposition` — it is not a general
escape hatch from framework policy."""


def _require_identifier(value: str, field: str) -> str:
    """Reject an id that is empty or whitespace-only.

    An id is a join key — a gate id reaches the persisted
    ``health_gate_results``, a check id and a provider id are looked up in
    Phase B. A blank one produces a lookup that fails much later with a
    message about the wrong thing.
    """
    if not value.strip():
        raise ValueError(f"{field} must be a non-empty identifier; got {value!r}.")
    return value


class ValueScale(BaseModel):
    """The task's numerical value scale — unit and factor, owned TOGETHER.

    ``value_scale_unit`` is an applicability FACT, but the arithmetic needs
    the NUMBER: TIDMAD's dispersion checks multiply raw samples by
    ``40.0 / 128.0`` to reach millivolts. At master ``a226495b`` that literal
    is duplicated in FOUR check modules (``output_std``,
    ``per_file_output_std``, ``pearson_dispersion``, ``spectral_peak_ratio``)
    and declared by nothing, which is why 08a had to leave the axis absent —
    requiring it would have flipped TIDMAD's std checks to ``inapplicable``.

    The two halves are one field pair here, not two declarations, because
    08a proved that separating a scale declaration from its consumers breaks
    parity in between (§3.9). C5 migrates them atomically.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit: str = Field(
        description=(
            "Physical unit a scaled sample carries, e.g. 'mV'. The SINGLE "
            "source of the task's ``value_scale_unit`` health fact — see "
            "``TaskHealthConfig.resolved_facts``."
        ),
    )
    units_per_sample: float = Field(
        gt=0.0,
        description=(
            "Multiply one raw stored sample by this to obtain a value in "
            "``unit``. TIDMAD: 40.0 / 128.0 = 0.3125 mV per int8 step. "
            "Rejected at zero or below: a non-positive scale collapses every "
            "dispersion measurement to zero or inverts its sign."
        ),
    )

    @field_validator("unit")
    @classmethod
    def _unit_is_named(cls, value: str) -> str:
        return _require_identifier(value, "unit")


class HealthPluginRef(BaseModel):
    """One external Python file or directory this task's health config names.

    ``kind`` is DECLARED rather than probed, and that is load-bearing: §3.2
    gives a missing explicitly-named FILE and an unloadable MEMBER of a
    configured DIRECTORY deliberately different outcomes (fail closed vs. a
    tolerated per-member warning). A ref that does not exist cannot be
    classified by looking at the filesystem, so the document says which it
    is and the loader (C2) never has to guess.

    Refs are RELATIVE to the task config's own directory. An absolute ref
    would make the pinned plugin identity host-specific, which C4's
    path-independence criterion forbids: two scientifically identical task
    packages checked out at different absolute paths must produce the SAME
    semantic identity (§3.6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["file", "directory"] = Field(
        description=(
            "'file' — an explicitly named module whose failure to load is "
            "fatal at startup. 'directory' — a scanned member set that keeps "
            "the existing loader idiom's per-member tolerance. Either way an "
            "unresolved DECLARED binding still fails closed in Phase B."
        ),
    )
    ref: str = Field(
        description=(
            "Path relative to the directory holding this task health config. "
            "Normalized and digested into the pinned run identity (§3.6)."
        ),
    )

    @field_validator("ref")
    @classmethod
    def _ref_is_relative_and_well_formed(cls, value: str) -> str:
        """Reject refs that are empty, host-anchored, or unrepresentable.

        Absolute paths and ``~`` expansion are rejected for the same reason:
        both resolve against THIS host, so the same task package would pin a
        different plugin identity on a different machine and every resume
        would fail closed for no scientific reason.
        """
        _require_identifier(value, "plugin ref")
        if os.path.isabs(value) or value.startswith("/"):
            raise ValueError(
                f"plugin ref {value!r} is absolute. Refs are relative to the "
                f"task health config's directory so the same task package "
                f"pins one identity regardless of where it is checked out."
            )
        if value.startswith("~"):
            raise ValueError(
                f"plugin ref {value!r} starts with '~'. Home expansion is "
                f"host-specific; use a path relative to the task health "
                f"config's directory."
            )
        if "\x00" in value or "\n" in value:
            raise ValueError(f"plugin ref {value!r} contains a NUL or newline.")
        return value


class HealthProviderBinding(BaseModel):
    """One view provider this task binds, plus its provider-owned config.

    ``provider_id`` is accepted as any non-empty string: the provider is
    registered by a plugin that has not loaded yet, so requiring it to exist
    HERE would make the document unparseable before the code it names is
    read. Phase B resolves it (§3.1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str = Field(
        description=(
            "Stable identity a loaded plugin registers under. Opaque at "
            "Phase A — never interpreted, never matched against a closed list."
        ),
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Provider-owned configuration, passed through untouched. The "
            "framework never inspects it — a provider's parameters are its "
            "own business, exactly as a check's thresholds are the task's."
        ),
    )

    @field_validator("provider_id")
    @classmethod
    def _provider_id_is_named(cls, value: str) -> str:
        return _require_identifier(value, "provider_id")


class HealthRosterEntry(BaseModel):
    """One gate the task declares: which check, under which disposition.

    The gate id lives here because it is a persisted join key into
    ``health_gate_results`` — TIDMAD's six ids must survive the migration
    byte-identical, which is only possible if the task states them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str = Field(
        description=("Stable gate identity, persisted and joined on. Unique within the roster."),
    )
    check: str = Field(
        description=(
            "Registered check name. Accepted as any non-empty string at "
            "Phase A — an externally supplied check does not exist until its "
            "plugin loads, and Phase B is where a name that never appears "
            "fails closed."
        ),
    )
    disposition: HealthDisposition = Field(
        description="The task's scientific choice; the framework derives the policy.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Task-owned check configuration — thresholds (08a's "
            "``threshold_parameter_names``) and task parameters the check "
            "reads, such as ``peek_samples``. Framework-policy keys are "
            "rejected: see FRAMEWORK_OWNED_PARAMETER_KEYS. The single "
            "declarable policy key is ``aggregation`` "
            "(TASK_DECLARABLE_POLICY_KEYS); declaring it overrides the "
            "framework default for THIS gate only."
        ),
    )
    uses_health_peek_files: bool = Field(
        default=False,
        description=(
            "When True, composition supplies this entry with the task's "
            "declared ``health_peek_files``. Default False is not an "
            "oversight and not a smaller default — it preserves today's "
            "behaviour exactly: only the three blocking gates carry a peek "
            "set, and injecting one into the recording gates would move them "
            "from every file onto a three-file triplet, which is a policy "
            "change rather than an ownership change."
        ),
    )
    reason: str = Field(
        default="",
        description=(
            "Why this gate exists, in the task's own scientific terms — "
            "empirical margins, band exemplars, the investigation that set a "
            "threshold. Task science, so it travels with the task."
        ),
    )

    @field_validator("gate_id", "check")
    @classmethod
    def _ids_are_named(cls, value: str) -> str:
        return _require_identifier(value, "roster entry id")

    @field_validator("parameters")
    @classmethod
    def _parameters_carry_no_framework_policy(cls, value: dict[str, Any]) -> dict[str, Any]:
        """A task may not state what the framework derives from its disposition.

        Caught at authoring time rather than silently dropped at composition:
        an author who writes ``on_fail: continue`` expecting it to take
        effect has misunderstood the ownership split, and a config that
        accepts the key while ignoring it teaches exactly that
        misunderstanding.
        """
        offenders = sorted(set(value) & FRAMEWORK_OWNED_PARAMETER_KEYS)
        if offenders:
            raise ValueError(
                f"parameters {offenders} are framework policy, not task "
                f"parameters. A task selects a disposition and the framework "
                f"derives gate role, actions, short-circuit, severity and "
                f"cadence from it. Declare the peek set once as "
                f"health_peek_files and opt in with "
                f"uses_health_peek_files=true. The one declarable policy key "
                f"is 'aggregation'."
            )
        return value

    @field_validator("parameters")
    @classmethod
    def _declared_aggregation_is_an_implemented_mode(cls, value: dict[str, Any]) -> dict[str, Any]:
        """A declared ``aggregation`` must name a rule the runtime implements.

        Phase A owns closed framework vocabularies — this is the same check
        as "valid disposition names", applied to the one policy key a task
        may now write. Without it a typo (``all_passs``) would parse, compose
        into the pinned artifact, and only surface at gate-evaluation time as
        a check ERROR: a configuration mistake wearing a Health verdict's
        clothes, which §3.2 forbids.

        Deliberately NOT a ``Literal`` on a typed field: ``parameters`` is an
        open task-owned mapping and must stay one, so the vocabulary is
        enforced on the value rather than on the field.

        **Keyed on PRESENCE, because the composer is** (release remediation
        N-5). This validator used to read ``value.get("aggregation")`` and
        early-return on ``None``, while ``_composition.compose_gate`` decides
        which framework defaults to withhold from
        ``TASK_DECLARABLE_POLICY_KEYS & entry.parameters.keys()`` — presence.
        YAML ``aggregation:`` with no value parses to ``None``, so a blank
        declaration was PRESENT to the composer (framework default
        suppressed) and ABSENT to the validator (accepted in silence). The
        three consuming checks read ``cfg.get("aggregation", DEFAULT)``, and a
        present ``None`` defeats a fallback, so it composed cleanly into
        ``health_checks_effective.yaml``, was sha-pinned into the run
        invariants, and first surfaced as ``unknown aggregation mode None`` —
        a ``CheckVerdict.ERROR`` on a BLOCKING gate, i.e. ``invalidate_round``
        every round. Precisely what this validator's docstring says it exists
        to prevent.

        The validator moved rather than the composer, because "declared
        nothing" and "declared blank" are different operator intents and only
        one of them is an error: value-keying the composer would have made a
        blank declaration silently inherit the framework default, teaching
        that a half-written line is a working line.
        """
        return validate_aggregation_config(value)


class TaskHealthConfig(BaseModel):
    """A task's complete Health declaration.

    Every field is optional, because a task legitimately declaring health
    while declaring no gates is a legal absence rather than an error — and
    "this task states no roster" must stay distinguishable from "this task
    was never asked", which is what §3.10's three binding states preserve.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: TaskHealthFacts = Field(
        default_factory=TaskHealthFacts,
        description=(
            "What this task declares about the data its checks inspect — "
            "08a's vocabulary, reused rather than restated, so a check's "
            "``required_facts`` compares against exactly one kind of thing."
        ),
    )
    value_scale: ValueScale | None = Field(
        default=None,
        description=(
            "The task's numerical value scale, when it has one. None means "
            "the task declares no physical scale, and checks that require "
            "the axis are inapplicable — which is a statement, not a gap."
        ),
    )
    health_peek_files: tuple[int, ...] = Field(
        default=(),
        description=(
            "File indices this task's opted-in gates watch, declared ONCE. "
            "Replaces the ``task_health_peek`` sentinel, whose only job was "
            "to inject the same set from the dataset profile into a "
            "framework-owned check config."
        ),
    )
    plugins: tuple[HealthPluginRef, ...] = Field(
        default=(),
        description="External Python files/directories that register this task's providers and checks.",
    )
    providers: tuple[HealthProviderBinding, ...] = Field(
        default=(),
        description="View providers this task binds, resolved in Phase B.",
    )
    roster: tuple[HealthRosterEntry, ...] = Field(
        default=(),
        description="The gates this task declares, in order.",
    )

    @field_validator("health_peek_files")
    @classmethod
    def _peek_files_are_distinct_and_real(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        """Reject negatives and duplicates; keep the authored order.

        Order is preserved rather than sorted because this is the authored
        document — normalization belongs to composition, where it is one
        deterministic step instead of a property spread across every reader.
        """
        negative = sorted({i for i in value if i < 0})
        if negative:
            raise ValueError(f"health_peek_files contains negative indices {negative}.")
        dupes = sorted({i for i in value if value.count(i) > 1})
        if dupes:
            raise ValueError(
                f"health_peek_files contains duplicate indices {dupes}. A file "
                f"peeked twice is peeked once; the repeat is an authoring slip."
            )
        return value

    @model_validator(mode="after")
    def _phase_a_coherence(self) -> TaskHealthConfig:
        """Reject documents that contradict themselves.

        These are the contradictions §3.1 assigns to Phase A. None of them
        needs a plugin to be loaded, and each one would otherwise surface far
        from its cause — as a silently inapplicable check, a duplicate
        persisted gate id, or a peek opt-in resolving to nothing.
        """
        if self.facts.value_scale_unit is not None:
            raise ValueError(
                f"facts.value_scale_unit={self.facts.value_scale_unit!r} is declared "
                f"in two places. The unit and its numerical factor are one fact — "
                f"declare value_scale.unit and let resolved_facts() supply the axis, "
                f"so the number and the unit can never drift apart."
            )

        for label, ids in (
            ("gate ids", [e.gate_id for e in self.roster]),
            ("provider ids", [p.provider_id for p in self.providers]),
            ("plugin refs", [p.ref for p in self.plugins]),
        ):
            seen: set[str] = set()
            dupes: list[str] = []
            for item in ids:
                if item in seen and item not in dupes:
                    dupes.append(item)
                seen.add(item)
            if dupes:
                raise ValueError(
                    f"duplicate {label} in the task health config: {dupes!r}. "
                    f"Each must be unique — a duplicate makes the later entry "
                    f"either unreachable or ambiguous."
                )

        if not self.health_peek_files:
            opted_in = [e.gate_id for e in self.roster if e.uses_health_peek_files]
            if opted_in:
                raise ValueError(
                    f"roster entries {opted_in!r} set uses_health_peek_files=true "
                    f"but the config declares no health_peek_files. The opt-in "
                    f"would resolve to an empty set, silently returning those "
                    f"gates to whatever default file source their check happens "
                    f"to have."
                )
        return self

    def resolved_facts(self) -> TaskHealthFacts:
        """The task's health facts, with ``value_scale_unit`` filled from the scale.

        The unit reaches 08a's applicability engine from the SAME declaration
        that carries the number the checks multiply by, so the axis a check
        requires and the arithmetic it performs cannot describe different
        units. That is the whole reason ``facts.value_scale_unit`` is
        rejected as an independent input above.
        """
        if self.value_scale is None:
            return self.facts
        # Reconstructed rather than ``model_copy(update=…)`` so the result is
        # re-validated: a copy would skip TaskHealthFacts' own coherence rules
        # and hand the applicability engine an object it never approved.
        return TaskHealthFacts(
            **{**self.facts.model_dump(), "value_scale_unit": self.value_scale.unit}
        )
