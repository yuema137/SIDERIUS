# core/run_invariants.py
"""Immutable run-level invariants — workspace lock creation and validation.

A *run invariant* is a configuration value that defines the identity of every
record produced in a workspace and therefore must never change across
executions against that workspace (chain iterations, ``--resume``, standalone
tuner runs). Changing one mid-workspace would make already-persisted records
incomparable with future ones — e.g. a DataScope change alters the scalar
population, and a HealthGate policy change retroactively relabels candidate
validity (see docs/design/enable_partial_file_list.md, *Policy lock*).

The invariants are pinned by ``{workspace}/run_invariants_lock.json``:

- The first execution to initialize a workspace atomically creates the lock
  (first writer wins; a concurrent losing writer falls through to
  read-and-validate).
- Every later execution validates its own resolved configuration against the
  lock and fails fast on mismatch, naming exactly which field drifted.
- Equality is defined ONLY over the canonical invariant fields; provenance
  metadata (``created_at``) never participates.

The current canonical set is ``resolved_data_scope`` +
``health_gate_enabled`` + ``health_config_sha256`` plus every later
canonical field declared on ``RunInvariants._CANONICAL`` (ordering
override, health-feedback policy, runtime identities, task composition,
arXiv U1's workflow topology ``lit_review_enabled`` /
``lit_review_config_sha256`` and the opaque ``experiment_arm`` label, and
the Gold campaign's observed ``advice_sha256`` treatment identity). The
mechanism is deliberately generic: future run-defining settings (dataset
version, execution policy, ...) join by adding a field to ``RunInvariants``
— the file format and validation logic need no redesign.

v1 policy: no escape hatch — a deliberate invariant change means a new
workspace (FU-6 tracks an explicit migration path if a need appears).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from core.execution_calibration import calibration_provenance
from core.generated_library import generated_library_provenance

RUN_INVARIANTS_BASENAME = "run_invariants_lock.json"


class RunInvariantsViolation(ValueError):
    """A run's configuration contradicts the workspace's invariant lock."""


class RunInvariants(BaseModel):
    """The canonical immutable configuration of one workspace.

    Attributes:
        resolved_data_scope: Sorted resolved file indices this workspace's
            runs may access (full scope is stored explicitly, e.g.
            ``[0..19]`` — never ``None``, so records are unambiguous).
        health_gate_enabled: Whether the HealthGate subsystem is active.
        health_config_sha256: sha256 of the canonical materialized effective
            HealthGate config; ``None`` when gates are disabled (a disabled
            run has no effective config file, so the flag itself is part of
            the locked identity).
        ordering_override_strategy: The operator's data-ordering override for
            this chain, or ``None`` when no override is in force. This locks
            the chain's ordering CONTROL POLICY, not its outcome — see below.
        ordering_override_file_order: The operator-forced file visitation
            order, or ``None``.
        structured_health_feedback_enabled: Whether the structured
            HealthGate feedback PROMPT rendering is enabled (V19 PR 3,
            ``docs/design/v19_priorities/pr3_healthgate_feedback.md``
            §3.9). Locked because it changes the agents' decision context
            — the chain's behavioral policy — even though it changes no
            data or scoring.
        health_feedback_history_window_iterations: Fingerprint-history
            retention window (total iterations retained, including the
            current one). Locked with the flag: retention affects agent
            context.
        health_feedback_history_max_entries_per_model: Deterministic trim
            bound on retained history entries per model. Locked with the
            flag.
        lit_review_enabled: Whether the ``ml_literature_review`` node is
            part of this run's WORKFLOW TOPOLOGY (arXiv U1, #253). ``False``
            means the node is never constructed and the proposer receives
            the four-channel zero — not a "root-paper variant" (ruling R1).
            Locked because two runs differing in topology are incomparable.
            OMITTED from the serialized lock when ``False`` so a legacy lock
            stays byte-identical and parses to ``False``.
        lit_review_config_sha256: sha256 of the resolved lit-review YAML
            bytes when the node is enabled; ``None`` when disabled (the
            config is not read, so there is nothing to pin). Omitted from
            the serialized lock when ``None``.
        experiment_arm: OPAQUE canonical provenance label naming the
            experiment arm this workspace belongs to (arXiv U1, #254;
            ruling R2). Compared, never interpreted: no behaviour may key on
            its value — any behaviour an arm needs is driven by its own
            explicit, recorded flag. ``None`` is "unlabelled" (every legacy
            run); an EMPTY string is refused, so absence is never spelled as
            an empty-string default. Omitted from the lock when ``None``.
        advice_sha256: OBSERVED sha256 of the exact advice-artifact bytes
            this run consumed, or ``None`` when it consumed none. CANONICAL:
            the advice artifact IS the Gold campaign's independent variable,
            so two workspaces that read different advice are not comparable
            and a resume across them must refuse. Never an echo of a
            declared value — see ``advice_path``.
        advice_path: Resolved ABSOLUTE path the advice bytes were read from,
            or ``None``. RECORDED, never compared: path proves authority and
            reachability, the observed digest proves treatment identity.
        created_at: ISO-8601 creation timestamp. Provenance only — never
            part of equality.

    PR 3 resume matrix (the generic ``_CANONICAL`` comparison enforces it;
    defaults below make a pre-PR3 lock file validate into the pre-feature
    state):

        same flag + same policy values        → accepted
        changed flag, same workspace          → RunInvariantsViolation
        changed window or entry limit         → RunInvariantsViolation
        legacy workspace (no PR3 keys)        → resolves OFF / 3 / 8; accepted
        enabling ON on a legacy/OFF workspace → rejected (canonical
                                                 mismatch); use a NEW
                                                 workspace

    Why the ordering OVERRIDE is locked but the RESOLVED ordering is not:
    an override is a chain-level control decision, and silently changing it
    mid-chain would invalidate the comparison the chain exists to make. The
    resolved value, by contrast, may legitimately differ from round to round
    when no override is active and the agent is exploring — locking it would
    forbid the intended behavior. Each round's resolved ordering is recorded
    on its own ``ExperimentRecord`` instead
    (docs/design/v19_priorities/pr2_data_ordering.md §3.8).
    """

    model_config = ConfigDict(frozen=True)

    resolved_data_scope: list[int]
    health_gate_enabled: bool
    health_config_sha256: str | None
    # Default None so a pre-PR2 lock file — which has no ordering keys at
    # all — validates cleanly into the no-override state instead of tripping
    # the corruption guard in load_run_invariants().
    ordering_override_strategy: str | None = None
    ordering_override_file_order: list[int] | None = None
    # V19 PR 3 — defaults chosen so a pre-PR3 lock file validates into the
    # pre-feature state (OFF / 3 / 8), same mechanism as the ordering keys.
    structured_health_feedback_enabled: bool = False
    health_feedback_history_window_iterations: int = 3
    health_feedback_history_max_entries_per_model: int = 8
    # C9d — the runtime decision subsystem's behavioral identities. Unlike
    # every field above, these have NO pre-feature state to default into:
    # a lock without them was written before runtime authority was
    # unified, so the workspace's history was produced under different
    # decision rules. `None` therefore means "legacy", and legacy is
    # REJECTED at validation (see _reject_legacy_runtime_lock) rather
    # than silently accepted. The default exists only so an old lock file
    # can be PARSED well enough to produce that explicit error.
    runtime_estimator_identity: str | None = None
    runtime_policy_identity: str | None = None
    # Step 10 / P1 — the COMPOSED run's canonical semantic task-composition
    # fingerprint, or None for an un-composed (legacy) run. `None` is not a
    # compatible default here: it means "this workspace was not composed",
    # and a composed run meeting an un-composed lock is a genuine mismatch
    # that the canonical comparison below must refuse. The key is OMITTED
    # from the serialized lock when None (see `write_run_invariants`), so a
    # legacy lock file stays byte-identical to its pre-P1 form.
    task_composition_fingerprint: str | None = None
    # F-SCANH-1 — sha256 of the raw bytes of the task-config FILE an
    # UN-COMPOSED run reads (``configs/task_config.yaml``, the source of the
    # prompt surfaces' TASK_DESCRIPTION / FORWARD_CONTRACT). It was the ONE
    # tracked config the lock did not pin: `_snapshot_task_config` is
    # first-writer-wins, so an iteration-2+ edit reached the LLM with no
    # snapshot and no refusal. `None` means either (a) a COMPOSED run — the
    # file is unread, the task identity is owned by
    # `task_composition_fingerprint`, and pinning an unread config is
    # exactly what the lit-review sha validator refuses — or (b) a legacy
    # lock, where the default exists only to PARSE; a legacy lock meeting a
    # pinning build REFUSES via the ordinary canonical comparison (the 12a
    # composition-fingerprint precedent: intended, no compatibility bypass).
    # The key is OMITTED from the serialized lock when None (see
    # `write_run_invariants`), so composed and legacy locks stay
    # byte-identical.
    task_config_sha256: str | None = None
    # arXiv U1 (#253 / #254) — the run's WORKFLOW TOPOLOGY and its
    # EXPERIMENT ARM. All three are CANONICAL: two workspaces that differ
    # in whether the literature-review node ran, in WHICH lit-review config
    # it ran under, or in the arm they belong to are not comparable, and the
    # EXISTING lock comparison is what refuses the resume (no new
    # machinery). Defaults are the legacy state, so a pre-U1 lock file
    # parses into exactly the run it described; the keys are OMITTED from
    # the serialized lock at their defaults (see `write_run_invariants`),
    # so that legacy lock's bytes are unchanged too.
    #
    # `experiment_arm` is OPAQUE (ruling R2): the framework compares it and
    # stamps it; nothing reads its VALUE to decide anything.
    lit_review_enabled: bool = False
    lit_review_config_sha256: str | None = None
    experiment_arm: str | None = None
    # arXiv U3 (#259 / #260) — BASELINE ISOLATION: the explicit, recorded
    # flag that drives the WITHOUT arm's behaviour (ruling R2: never the arm
    # label). Under it the bundled built-in model descriptions, the
    # baseline-naming prompt literals and built-in proposals are excluded.
    # Canonical: an isolated and a non-isolated run saw different prompt
    # surfaces and are not comparable. Omitted from the lock at `False`.
    baseline_isolation: bool = False
    # Gold campaign (advice-invariant) — the run's ADVICE TREATMENT identity:
    # the OBSERVED sha256 of the exact advice-artifact bytes this run
    # consumed, and the resolved absolute path they were read from.
    #
    # The split between the two is the operator's formulation: PATH PROVES
    # AUTHORITY AND REACHABILITY; OBSERVED DIGEST PROVES TREATMENT IDENTITY.
    # So `advice_sha256` is CANONICAL and `advice_path` is `_PROVENANCE`.
    # Filesystem location is execution-HOST layout, not scientific semantics
    # — the same advice bytes staged at two absolute paths are one treatment,
    # which is the Q-P1-2 exclusion rule `model_plugin_identities` states
    # above and the `generated_library` root states below. No frozen decision
    # in this repository makes a file's location part of a run's semantics.
    #
    # WHY PLAIN `_CANONICAL` MEMBERSHIP *IS* THE CONDITIONAL COMPARISON, and
    # why no second comparison surface was built for it. The required
    # outcomes are:
    #
    #     stored absent + current absent -> COMPATIBLE (legacy regime)
    #     stored A      + current A      -> COMPATIBLE
    #     stored A      + current B      -> REFUSE
    #     stored A      + current absent -> REFUSE
    #     stored absent + current A      -> REFUSE
    #
    # `validate_run_invariants` compares `locked != expected` field by field
    # over `_CANONICAL`. A legacy lock carries no advice key and parses to
    # `None`; a run that consumed no advice resolves `None`. Those five rows
    # are therefore exactly `!=` over `str | None` — the conditional
    # behaviour is a PROPERTY of an optional canonical field, not machinery
    # that has to be written.
    #
    # The contrast with `task_config_sha256` above is the whole reason this
    # addition does not invalidate the repository's existing workspaces:
    # that field is pinned UNCONDITIONALLY by every un-composed run, so a
    # legacy lock's `None` met a real digest and refused (intended, and
    # separately accepted). Advice is OPTIONAL, so the overwhelming case is
    # `None` vs `None` and every no-advice workspace stays resumable. Only a
    # workspace that is resumed WITH advice is refused — and that is the row
    # the operator singled out: it is the case that would otherwise let an
    # advice-bound campaign quietly inherit a workspace whose treatment
    # nobody can reconstruct.
    #
    # A dedicated conditional-comparison mechanism would express the same
    # five rows with more machinery AND would move the semantics back inside
    # a validator — precisely what declaring the `_CANONICAL` / `_PROVENANCE`
    # partition (R-11-6) exists to prevent.
    #
    # Both keys are OMITTED from the serialized lock at `None`, so every lock
    # written by a run that consumed no advice — legacy or current — stays
    # byte-identical.
    advice_sha256: str | None = None
    advice_path: str | None = None
    # F-SCANF-1 (D-FAIL-7 known_gap G4) — the FRACTION of the eval scope a
    # FORMAL round scores over. It was recorded as per-file-best provenance
    # (`execute_tools/per_file_best.py`, "from run_config; null for legacy")
    # and existed as a CLI argument, but was not a declared invariant at all
    # — neither `_CANONICAL` nor `_PROVENANCE` — so two iterations whose
    # formal evaluation covered different fractions of the data folded into
    # one incumbent with no refusal. Recorded was not enforced, and D-FAIL-7
    # lists "train / eval portions" among the values a resume must verify.
    #
    # CANONICAL: aggregate scalars are only comparable within one evaluation
    # scope, exactly as `resolved_data_scope` above is only comparable within
    # one file subset.
    #
    # WHY THE DEFAULT IS 1.0 AND NOT `None`. The five rows this produces:
    #
    #     stored absent + current 1.0  -> COMPATIBLE (legacy regime)
    #     stored absent + current 0.1  -> REFUSE
    #     stored 0.1    + current 0.1  -> COMPATIBLE
    #     stored 0.1    + current 1.0  -> REFUSE
    #     stored 0.1    + current 0.5  -> REFUSE
    #
    # Every entry point resolves a real float (the CLI default is 1.0), so an
    # OPTIONAL `str | None`-shaped declaration in the `advice_sha256` mould
    # would put a real value opposite every legacy lock's `None` and refuse
    # EVERY pre-existing workspace's resume. Defaulting to the framework's own
    # 1.0 instead confines the refusal to workspaces whose current run declares
    # a NON-DEFAULT portion — precisely the ones whose comparability the lock
    # cannot otherwise establish. The residual, accepted deliberately: a legacy
    # lock cannot distinguish "ran at 1.0" from "predates the field", so a
    # legacy workspace resumed at 1.0 is admitted. Making that distinguishable
    # needs a conditional-comparison surface, which the `advice_sha256` block
    # above forbids by name (R-11-6).
    #
    # Omitted from the serialized lock at 1.0 (see `write_run_invariants`), so
    # every legacy and every full-eval lock file stays byte-identical.
    formal_eval_portion: float = 1.0
    # Workflow-owned parameter rules change the effective plan and therefore
    # the scientific treatment. Store their canonical validated JSON shape;
    # None is the unconstrained legacy state.
    workflow_parameter_rules: dict[str, Any] | None = None
    # Wall-time admission authority changes which evidence may refuse an
    # attempt. ``None`` denotes a legacy lock so a pre-feature workspace
    # cannot silently resume under the new measured-by-default behavior.
    trial_time_admission_source: Literal["forecast", "measured"] | None = None
    formal_time_admission_source: Literal["forecast", "measured"] | None = None
    created_at: str | None = None
    # Step 11 C3 (R-11-6) — the per-role subprocess memory ceilings this
    # run executed under, plus their provenance. RECORDED, never compared.
    #
    # Ceilings are execution-HOST calibration, not task semantics: the same
    # scientific run resumed on a differently-calibrated host must remain
    # legal, unlike a composition, metric or dataset-semantics change. That
    # is why this field is declared in `_PROVENANCE` below rather than
    # merely left out of `_CANONICAL` — "absent from the canonical tuple"
    # is a validator remembering not to compare something, and the operator
    # constraint on R-11-6 is that the two concepts be distinguishable in
    # the REPRESENTATION.
    #
    # Omitted from the serialized lock when None, like the composition
    # fingerprint, so a pre-C3 lock file stays byte-identical.
    execution_calibration: dict[str, Any] | None = None
    # Step 12 / PR-12d, seam P — WHICH model-plugin implementations this run
    # actually loaded, as host-independent content identities. RECORDED,
    # never compared.
    #
    # Not canonical, and deliberately so: what makes an edited pack plugin a
    # different scientific run is already the composition fingerprint, which
    # hashes these same content digests and IS compared. Comparing them here
    # too would be a second opinion on one fact — and would refuse a resume
    # on a host where the pack simply lives at a different path, which is not
    # a semantic difference (the Q-P1-2 exclusion rule).
    #
    # What it buys is the thing nothing else offered: production-visible
    # evidence of the implementation that executed, so a Gate can answer
    # "was that really the pack's reference model" from a persisted artifact
    # rather than from a transient log line.
    #
    # Omitted from the serialized lock when None, like the two fields above,
    # so every pre-seam-P lock file stays byte-identical.
    model_plugin_identities: list[dict[str, str]] | None = None
    # arXiv P1 — WHERE this run's generated-capability library resolved
    # ({"root": ..., "source": "env"|"default"},
    # ``core.generated_library.generated_library_provenance``). RECORDED,
    # never compared: the library root is execution-HOST layout, not task
    # semantics — the same scientific run resumed on a host whose library
    # lives elsewhere must remain legal (promoted capabilities stay
    # discoverable through the read-priority chain), exactly the
    # ``execution_calibration`` precedent (R-11-6). What it buys: persisted
    # evidence of which library this workspace's Branch-B reuse, promotions
    # and capability index drew from, so "why did my resumed run stop
    # seeing loss X" is answerable from the lock rather than from a
    # transient log line.
    #
    # Omitted from the serialized lock when None, like the fields above,
    # so every pre-P1 lock file stays byte-identical.
    generated_library: dict[str, Any] | None = None

    # Fields participating in lock equality.
    _CANONICAL: ClassVar[tuple[str, ...]] = (
        "resolved_data_scope",
        "health_gate_enabled",
        "health_config_sha256",
        "ordering_override_strategy",
        "ordering_override_file_order",
        "structured_health_feedback_enabled",
        "health_feedback_history_window_iterations",
        "health_feedback_history_max_entries_per_model",
        "runtime_estimator_identity",
        "runtime_policy_identity",
        "task_composition_fingerprint",
        # F-SCANH-1 — the un-composed task-config pin is COMPARED (supervisor
        # ruling; never `_PROVENANCE`): an operator edit to
        # configs/task_config.yaml mid-workspace changes what the LLM reads
        # and must refuse the resume.
        "task_config_sha256",
        # arXiv U1 — topology + arm are compared, never interpreted.
        "lit_review_enabled",
        "lit_review_config_sha256",
        "experiment_arm",
        # arXiv U3 — the isolation flag is a prompt-surface identity.
        "baseline_isolation",
        # Gold campaign — the OBSERVED advice-artifact digest. The treatment
        # itself, not the arm LABEL that describes it: `experiment_arm` two
        # lines up is opaque provenance about which arm a workspace claims to
        # belong to, and before this field nothing pinned what that arm
        # actually received. Optional, so `None` vs `None` keeps every
        # no-advice workspace resumable (see the field's declaration).
        "advice_sha256",
        # F-SCANF-1 — the formal round's evaluation FRACTION. Aggregate
        # scalars are only comparable within one evaluation scope; this is
        # `resolved_data_scope`'s sibling one axis over (see the field's
        # declaration for the five-row table and the legacy-lock consequence).
        "formal_eval_portion",
        "workflow_parameter_rules",
        "trial_time_admission_source",
        "formal_time_admission_source",
    )

    #: Fields RECORDED for audit and never compared (Step 11 C3, R-11-6).
    #:
    #: The counterpart of ``_CANONICAL``, declared so the distinction is a
    #: property of the model rather than of whichever validator happens to
    #: read it. Together the two tuples must PARTITION every declared
    #: field: a new field is either a semantic invariant or execution
    #: provenance, and it cannot be neither. ``__init_subclass__``-free —
    #: the partition is asserted by a guard test, because enforcing it at
    #: import time would turn a naming slip into a repo-wide import error.
    _PROVENANCE: ClassVar[tuple[str, ...]] = (
        "created_at",
        "execution_calibration",
        "model_plugin_identities",
        "generated_library",
        # Gold campaign — WHERE the advice bytes were read from. Recorded so
        # a refusal naming two digests can be traced back to an artifact,
        # and never compared: staging the same advice at a different
        # absolute path is not a different treatment (the Q-P1-2 rule).
        "advice_path",
    )

    #: C9d fields that a legacy lock cannot supply. Their absence is a
    #: refusal, never a compatible default.
    _RUNTIME_IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = (
        "runtime_estimator_identity",
        "runtime_policy_identity",
    )

    @field_validator("experiment_arm")
    @classmethod
    def _refuse_empty_arm_label(cls, value: str | None) -> str | None:
        """An arm label is present or absent — never an empty string.

        ``None`` is the one spelling of "unlabelled" (every legacy run
        carries it); accepting ``""`` would create a second, silent
        spelling that a stamp comparison could confuse with a real label.
        The value is otherwise opaque and is never normalized (R2).
        """
        if value is not None and not value.strip():
            raise ValueError(
                "experiment_arm must be a non-empty label or None (absent); an "
                "empty string is refused so absence is never spelled as an "
                "empty-string default."
            )
        return value

    @field_validator("advice_sha256")
    @classmethod
    def _advice_digest_is_a_bare_sha256(cls, value: str | None) -> str | None:
        """The digest is 64 lowercase hex characters, or absent.

        The defect this names: ``sha256sum FILE`` prints ``<hex>  <path>``,
        and the campaign launcher strips the path with ``awk '{print $1}'``.
        Drop the ``awk`` and the "identity" becomes a host-dependent string
        that still compares equal to itself — a pin that looks authoritative
        and silently encodes the machine's directory layout into the run's
        scientific identity.
        """
        if value is None:
            return value
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(
                f"advice_sha256 must be 64 lowercase hex characters (a bare "
                f"sha256 digest) or None; got {value!r}. `sha256sum` output "
                f"includes the FILE NAME — hash the bytes, or strip it."
            )
        return value

    @field_validator("advice_path")
    @classmethod
    def _advice_path_is_absolute(cls, value: str | None) -> str | None:
        """A recorded advice path is absolute, or absent — never relative.

        The consuming subprocess does not share the operator's working
        directory (``run_chain.sh`` cd's to the project dir before exec), so
        a relative path recorded in the lock names a different file for
        whoever reads it back than for the run that wrote it. The
        ``RequiredProfileBinding.artifact_path`` precedent, for the same
        reason.
        """
        if value is None:
            return value
        if not value.strip():
            raise ValueError(
                "advice_path must be a non-empty absolute path or None "
                "(absent); an empty string is refused so absence is never "
                "spelled as an empty-string default."
            )
        if not os.path.isabs(value):
            raise ValueError(
                f"advice_path {value!r} is relative. The recorded path must be "
                f"absolute: the run that wrote this lock and whoever reads it "
                f"back do not share a working directory, so a relative path "
                f"would name two different files."
            )
        return value

    @model_validator(mode="after")
    def _advice_path_and_digest_travel_together(self) -> RunInvariants:
        """The advice pin is the PAIR, or it is absent.

        A path with no digest is the dangerous half: the COMPARED field is
        then ``None``, so the lock admits ANY advice on resume while looking
        pinned — the same fail-open ``_lit_review_sha_matches_topology``
        refuses one field over. A digest with no path is unattributable: a
        refusal shows the operator two hex strings and no artifact to go
        and compare. Both are refused at construction, before any lock is
        written.
        """
        if self.advice_path is not None and self.advice_sha256 is None:
            raise ValueError(
                "advice_path is set but advice_sha256 is None: a lock recording "
                "WHERE the advice came from without WHAT it contained pins "
                "nothing — the compared field is None, so the workspace would "
                "admit any advice on resume while appearing bound."
            )
        if self.advice_sha256 is not None and self.advice_path is None:
            raise ValueError(
                "advice_sha256 is set but advice_path is None: a digest with no "
                "artifact is unattributable — a resume refusal would name two "
                "hex strings and no file to compare."
            )
        return self

    @model_validator(mode="after")
    def _lit_review_sha_matches_topology(self) -> RunInvariants:
        """The config pin and the topology flag must agree.

        Enabled without a sha means a caller passed the flag and forgot the
        pin (the lock would then accept ANY lit-review config on resume);
        a sha without the flag pins a config the run never reads. Both are
        refused at construction, before any lock is written.
        """
        if self.lit_review_enabled and self.lit_review_config_sha256 is None:
            raise ValueError(
                "lit_review_enabled=True requires lit_review_config_sha256 (the "
                "sha256 of the resolved lit-review YAML this run reads); a lock "
                "without the pin would admit any config on resume."
            )
        if not self.lit_review_enabled and self.lit_review_config_sha256 is not None:
            raise ValueError(
                "lit_review_config_sha256 is set but lit_review_enabled=False: a "
                "disabled lit-review reads no config, so there is nothing to pin."
            )
        return self

    def canonical(self) -> dict:
        """The equality-defining subset of the invariants."""
        return {name: getattr(self, name) for name in self._CANONICAL}

    def provenance(self) -> dict:
        """The RECORDED-only subset: audit evidence, never compared."""
        return {name: getattr(self, name) for name in self._PROVENANCE}


def _lock_path(workspace: str) -> str:
    return os.path.join(workspace, RUN_INVARIANTS_BASENAME)


def load_run_invariants(workspace: str) -> RunInvariants | None:
    """Read the workspace's invariant lock; ``None`` when no lock exists.

    A missing lock means the workspace predates this mechanism (or is being
    initialized right now) — callers decide whether to create it via
    ``ensure_run_invariants``.

    Raises:
        RunInvariantsViolation: the lock file exists but is unreadable or
            structurally invalid (corruption is a violation, not a legacy
            state — silently regenerating it could relabel history).
    """
    try:
        with open(_lock_path(workspace)) as f:
            raw = f.read()
    except FileNotFoundError:
        return None
    try:
        return RunInvariants.model_validate(json.loads(raw))
    except Exception as exc:
        raise RunInvariantsViolation(
            f"{RUN_INVARIANTS_BASENAME} in workspace {workspace!r} is corrupted "
            f"or has an unrecognized shape ({exc}). Refusing to guess the "
            f"workspace's invariants — restore the file or use a new workspace."
        ) from exc


def write_run_invariants(workspace: str, invariants: RunInvariants) -> str:
    """Atomically create the invariant lock. First writer wins.

    The content is written to a same-directory temp file and published with
    ``os.link`` — atomic on POSIX and, unlike ``os.rename``, it FAILS when
    the lock already exists instead of overwriting it, which is what gives
    the first writer its win. A losing concurrent writer receives
    ``FileExistsError`` and should fall through to validation
    (``ensure_run_invariants`` does exactly that).

    Returns:
        The lock file path.

    Raises:
        FileExistsError: the lock already exists (caller must validate
            against it instead).
    """
    os.makedirs(workspace, exist_ok=True)
    stamped = (
        invariants
        if invariants.created_at is not None
        else invariants.model_copy(update={"created_at": datetime.now(UTC).isoformat()})
    )
    path = _lock_path(workspace)
    payload = stamped.model_dump()
    # Step 10 / P1 §5.9: an UN-COMPOSED run's lock must be byte-identical to
    # its pre-P1 form, so the composition key is ABSENT rather than `null`.
    # Serializing it as null would change every legacy lock's bytes for a
    # feature those runs do not use — and "absent" is also the honest
    # encoding: the workspace predates composition rather than having been
    # composed with nothing. Pydantic's default makes it parse back to None.
    if payload.get("task_composition_fingerprint") is None:
        payload.pop("task_composition_fingerprint", None)
    # F-SCANH-1 — same rule for the task-config pin: a COMPOSED run reads no
    # task-config file (its identity is the composition fingerprint above)
    # and a legacy lock predates the pin, so the key is ABSENT rather than
    # `null` and both lock forms keep their prior bytes.
    if payload.get("task_config_sha256") is None:
        payload.pop("task_config_sha256", None)
    # arXiv U1 — same rule for the topology + arm keys: an unlabelled,
    # lit-review-OFF run (every run that predates them) writes none of the
    # three, so its lock is byte-identical to its pre-U1 form and parses
    # back to the defaults. `lit_review_enabled` is omitted at `False`, the
    # two optional strings at `None`.
    if payload.get("lit_review_enabled") is False:
        payload.pop("lit_review_enabled", None)
    if payload.get("lit_review_config_sha256") is None:
        payload.pop("lit_review_config_sha256", None)
    if payload.get("experiment_arm") is None:
        payload.pop("experiment_arm", None)
    # arXiv U3 — same rule for the isolation flag: omitted at `False`.
    if payload.get("baseline_isolation") is False:
        payload.pop("baseline_isolation", None)
    # Step 11 C3 — same rule, same reason: a lock written before execution
    # calibration was recorded stays byte-identical rather than gaining a
    # `null` for a concept it predates.
    if payload.get("execution_calibration") is None:
        payload.pop("execution_calibration", None)
    # Step 12 / PR-12d, seam P — third instance of the same rule: a run that
    # declared no model plugins writes no key, so every legacy lock is
    # byte-identical rather than gaining a `null` for a concept it predates.
    if payload.get("model_plugin_identities") is None:
        payload.pop("model_plugin_identities", None)
    # arXiv P1 — same rule for the generated-library provenance: a lock
    # written before the library migration stays byte-identical rather than
    # gaining a `null` for a concept it predates.
    if payload.get("generated_library") is None:
        payload.pop("generated_library", None)
    # Gold campaign — same rule for the advice pin, and here it is doing more
    # than cosmetics: the omission is what makes "this run consumed no
    # advice" and "this lock predates the advice pin" the SAME stored value,
    # which is what lets the ordinary canonical comparison produce the
    # required legacy-compatible row without a second comparison surface.
    if payload.get("advice_sha256") is None:
        payload.pop("advice_sha256", None)
    if payload.get("advice_path") is None:
        payload.pop("advice_path", None)
    # F-SCANF-1 — same rule for the formal eval fraction, and here too the
    # omission is load-bearing rather than cosmetic: it makes "this run scored
    # the whole eval scope" and "this lock predates the pin" the SAME stored
    # value, which is what confines the new refusal to workspaces that declare
    # a NON-DEFAULT portion (the field's declaration states the five rows and
    # the residual this accepts).
    if payload.get("formal_eval_portion") == 1.0:
        payload.pop("formal_eval_portion", None)
    if payload.get("workflow_parameter_rules") is None:
        payload.pop("workflow_parameter_rules", None)
    if payload.get("trial_time_admission_source") is None:
        payload.pop("trial_time_admission_source", None)
    if payload.get("formal_time_admission_source") is None:
        payload.pop("formal_time_admission_source", None)
    fd, tmp_path = tempfile.mkstemp(dir=workspace, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.link(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
    return path


def _reject_legacy_runtime_lock(
    workspace: str, locked: RunInvariants, expected: RunInvariants
) -> None:
    """C9d: refuse to resume a workspace locked before runtime authority
    was unified.

    Pydantic defaults let an old lock file PARSE — that is all they are
    for. They must never be read as "compatible": a workspace whose lock
    predates these fields produced its history under different decision
    rules (a static formula could gate rounds, priors could arm the
    watchdog), so continuing it under the current rules would mix two
    incompatible regimes in one trajectory.

    Raised before any LLM call or training, and only when THIS run has the
    identities (a legacy-vs-legacy comparison stays legal so old tooling
    can still read old workspaces).
    """
    missing = [
        name
        for name in RunInvariants._RUNTIME_IDENTITY_FIELDS
        if getattr(locked, name) is None and getattr(expected, name) is not None
    ]
    if not missing:
        return
    raise RunInvariantsViolation(
        f"workspace {workspace!r} was created before the runtime-control "
        f"invariants existed and cannot be resumed by this build.\n"
        + "\n".join(f"  - {name}: absent from the lock" for name in missing)
        + "\n  This run would decide runtime authority under rules the "
        "workspace's existing iterations never ran under (unified "
        "estimator/policy, measured-evidence-only blocking, "
        "REQUEST_PROBE resolution). Defaults are used to PARSE the old "
        "lock, never to declare it compatible.\n"
        "  Start a FRESH workspace; the old one remains readable and is "
        "not modified."
    )


def validate_run_invariants(workspace: str, expected: RunInvariants) -> None:
    """Compare ``expected`` against the workspace lock; raise on any drift.

    Equality covers only the canonical fields. Every drifted field is named
    with its locked and attempted values so the operator sees exactly what
    changed (scope change, HealthGate enable flip, and policy-content drift
    each produce their own line).

    Raises:
        RunInvariantsViolation: no lock exists (callers wanting
            create-or-validate semantics use ``ensure_run_invariants``), or
            one or more canonical fields differ.
    """
    locked = load_run_invariants(workspace)
    if locked is None:
        raise RunInvariantsViolation(
            f"workspace {workspace!r} has no {RUN_INVARIANTS_BASENAME} to "
            f"validate against. Initialize it via ensure_run_invariants()."
        )
    _reject_legacy_runtime_lock(workspace, locked, expected)
    drifted = [
        name
        for name in RunInvariants._CANONICAL
        if getattr(locked, name) != getattr(expected, name)
    ]
    if drifted:
        detail = "\n".join(
            f"  - {name}: locked={getattr(locked, name)!r} vs this run={getattr(expected, name)!r}"
            for name in drifted
        )
        raise RunInvariantsViolation(
            f"run-invariants lock violation in workspace {workspace!r} — this "
            f"run's configuration contradicts the workspace's immutable "
            f"invariants:\n{detail}\n"
            f"  Run invariants are immutable per workspace; use a new "
            f"workspace to change them."
        )


def ensure_run_invariants(workspace: str, expected: RunInvariants) -> str:
    """Create the lock if absent, else validate against it.

    The single entry point for workspace startup (workflow pre-flight,
    standalone tuner, resume): exactly one caller wins the creation race and
    every other execution — concurrent or later — is validated.

    Returns:
        ``"created"`` when this call created the lock, ``"validated"`` when
        an existing lock matched.

    Raises:
        RunInvariantsViolation: an existing lock contradicts ``expected``.
    """
    try:
        write_run_invariants(workspace, expected)
        return "created"
    except FileExistsError:
        validate_run_invariants(workspace, expected)
        return "validated"


class LockLaunchIdentity(BaseModel):
    """The launch-identity values a run's entry point resolves, as ONE carrier.

    The Gold campaign's advice pin rides here too, for the reason the
    carrier exists: it is resolved once at the launch boundary and has
    exactly one destination, the lock. ``advice_sha256`` is CANONICAL and so
    must be threaded explicitly by every caller that participates — a
    compared value must never arrive ambiently — and ``advice_path`` travels
    with it because it has no ambient authority to be read from.

    Four CANONICAL lock fields travel together from every entry point —
    workflow topology (``lit_review_enabled`` + its config sha), the opaque
    ``experiment_arm`` label (ruling R2: compared, never read for behaviour)
    and the WITHOUT arm's explicit ``baseline_isolation`` flag. Threading
    them as four scalars grew :func:`build_run_invariants` past the frozen
    12a parameter budget (13 → 17 vs +1 allowed), and the budget is right:
    values with one origin and one destination are a carrier, not four
    parameters. Defaults are the legacy/unlabelled state, so a caller that
    omits the carrier gets a byte-identical pre-U1 lock.
    """

    model_config = ConfigDict(frozen=True)

    lit_review_enabled: bool = False
    lit_review_config_sha256: str | None = None
    experiment_arm: str | None = None
    baseline_isolation: bool = False
    #: The OBSERVED advice-artifact digest and the path it was read from.
    #: Defaults are the no-advice state, so a caller that omits them gets a
    #: byte-identical lock.
    advice_sha256: str | None = None
    advice_path: str | None = None
    #: F-SCANF-1 — the FORMAL round's evaluation fraction. It rides the
    #: carrier for the reason the carrier exists: one origin (the launch
    #: argument), one destination (the lock). CANONICAL, so every entry point
    #: that participates threads it explicitly — a compared value must never
    #: arrive ambiently. The default is the framework's own full-eval value,
    #: so a caller that omits it gets a byte-identical lock.
    formal_eval_portion: float = 1.0
    workflow_parameter_rules: dict[str, Any] | None = None
    trial_time_admission_source: Literal["forecast", "measured"] | None = None
    formal_time_admission_source: Literal["forecast", "measured"] | None = None


#: The unlabelled default — module-level so call sites can splat a shared
#: legacy value without constructing per call.
UNLABELLED_LAUNCH_IDENTITY = LockLaunchIdentity()


@dataclass(frozen=True, slots=True)
class RunHealthMaterialization:
    """Inputs needed only while materializing the run's Health config."""

    task_health_binding: Any = None
    dataset_partition_count: int | None = None


def build_run_invariants(
    resolved_data_scope: list[int],
    health_gate_enabled: bool,
    health_gate_files: list[int] | None,
    health_checks_config: str | None,
    workspace: str,
    ordering_override_strategy: str | None = None,
    ordering_override_file_order: list[int] | None = None,
    structured_health_feedback_enabled: bool = False,
    health_feedback_history_window_iterations: int = 3,
    health_feedback_history_max_entries_per_model: int = 8,
    include_runtime_identities: bool = True,
    health_materialization: RunHealthMaterialization | None = None,
    task_composition_fingerprint: str | None = None,
    launch_identity: LockLaunchIdentity | None = None,
) -> tuple[RunInvariants, str | None]:
    """Compute a run's invariants — the ONE shared path for every entry point.

    Materializes and hashes the effective HealthGate config FIRST (when
    gates are enabled), then constructs ``RunInvariants`` from the result,
    so the sha in the lock always describes the exact config the run will
    read. Workflow startup and the standalone tuner both call this — never
    duplicate the normalization/hashing logic at a call site.

    F-SCANH-1: an UN-COMPOSED run (``task_composition_fingerprint is
    None``) also pins the task-config FILE its prompt surfaces read —
    ``workflows.task_config.task_config_file_sha256()``, the loader's own
    resolution — so an operator edit mid-workspace refuses the resume. A
    composed run pins ``None``: its task config is bound, not read from
    this file, and its identity is the fingerprint.

    Args:
        resolved_data_scope: Already-resolved sorted file indices (the
            caller runs its scope validation — e.g.
            ``validate_runtime_config`` — before this).
        health_gate_enabled: The run's HealthGate switch.
        health_gate_files: Run-level shared monitored-file list
            (``None`` = YAML defaults; only legal with a full scope).
        health_checks_config: Operator-supplied HealthGate YAML path, or
            ``None`` for the shipped default.
        workspace: Directory receiving ``health_checks_effective.yaml``.
        health_materialization: Task binding and already-resolved partition
            count needed to compose and validate the effective Health config.
        ordering_override_strategy: The run's data-ordering override, or
            ``None`` for no override. Defaults keep every pre-PR2 call site
            producing an unchanged, no-override lock.
        ordering_override_file_order: The operator-forced file order, or
            ``None``.
        structured_health_feedback_enabled: V19 PR 3 structured-feedback
            prompt flag (chain behavioral policy — locked). Defaults keep
            every pre-PR3 call site producing an unchanged OFF lock.
        health_feedback_history_window_iterations: PR 3 retention window
            (locked policy).
        health_feedback_history_max_entries_per_model: PR 3 retention trim
            bound (locked policy).
        lit_review_enabled: arXiv U1 — whether the literature-review node
            is part of this run's topology (locked). Defaults keep every
            pre-U1 call site producing an unchanged lock.
        lit_review_config_sha256: sha256 of the resolved lit-review YAML
            when enabled; ``None`` when disabled. Threaded EXPLICITLY by
            every caller (never read ambiently) because it is compared.
        experiment_arm: The opaque arm label, or ``None`` (unlabelled).
            Compared, never interpreted.
        baseline_isolation: arXiv U3 — whether the run excludes the bundled
            baselines from its prompt surface (locked; defaults off).

    Returns:
        ``(invariants, effective_config_path)`` — the path is ``None`` when
        gates are disabled (no effective config exists for disabled runs).
    """
    # Imported here, not at module top: keeps this generic module importable
    # without the health-check package for consumers that only need the
    # lock primitives (and avoids widening core→execute_tools coupling to
    # every importer of the lock).
    _launch_identity = (
        launch_identity if launch_identity is not None else UNLABELLED_LAUNCH_IDENTITY
    )
    from execute_tools.health_checks.config import materialize_effective_config

    if health_gate_enabled:
        # Step 10 / P1: the composed task Health binding is PASSED THROUGH to
        # 08b's existing keyword. Omitting it (the un-composed default) is
        # what resolves `LEGACY_OMITTED`, so a legacy run materializes the
        # byte-identical effective config it always did — the call shape is
        # the branch, and there is no task name on either side of it.
        health_inputs = health_materialization or RunHealthMaterialization()
        health_kwargs = (
            {}
            if health_inputs.task_health_binding is None
            else {"task_health_binding": health_inputs.task_health_binding}
        )
        effective_path, sha = materialize_effective_config(
            health_checks_config,
            health_gate_files,
            workspace,
            resolved_scope=resolved_data_scope,
            dataset_partition_count=health_inputs.dataset_partition_count,
            **health_kwargs,
        )
    else:
        effective_path, sha = None, None
    # F-SCANH-1 — pin the task-config FILE an un-composed run reads. The
    # deferred function-scope import matches the module's convention above
    # (the lock primitives stay importable without the workflows package).
    # A composed run reads no file — its identity is the fingerprint — so
    # it pins None and its lock bytes are unchanged.
    if task_composition_fingerprint is None:
        from workflows.task_config import task_config_file_sha256

        task_config_sha: str | None = task_config_file_sha256()
    else:
        task_config_sha = None
    return (
        RunInvariants(
            resolved_data_scope=list(resolved_data_scope),
            health_gate_enabled=health_gate_enabled,
            health_config_sha256=sha,
            ordering_override_strategy=ordering_override_strategy,
            ordering_override_file_order=(
                list(ordering_override_file_order)
                if ordering_override_file_order is not None
                else None
            ),
            structured_health_feedback_enabled=structured_health_feedback_enabled,
            health_feedback_history_window_iterations=(health_feedback_history_window_iterations),
            health_feedback_history_max_entries_per_model=(
                health_feedback_history_max_entries_per_model
            ),
            # C9d: stamped HERE so every entry point (workflow, chain
            # runner, standalone tuner) locks the same identities — the
            # builder is the one shared path by contract.
            task_composition_fingerprint=task_composition_fingerprint,
            # F-SCANH-1 — computed above from the mode, never a parameter:
            # the builder is the one shared path, so every un-composed
            # entry point pins the same file the same way.
            task_config_sha256=task_config_sha,
            # arXiv U1 — CANONICAL, so threaded explicitly by every caller
            # (a compared value must never arrive ambiently). The default is
            # the generic unlabelled, literature-review-disabled posture.
            lit_review_enabled=_launch_identity.lit_review_enabled,
            lit_review_config_sha256=_launch_identity.lit_review_config_sha256,
            experiment_arm=_launch_identity.experiment_arm,
            baseline_isolation=_launch_identity.baseline_isolation,
            # Advice identity is CANONICAL, so it is threaded explicitly like
            # the fields above. The value handed in here is the OBSERVED digest of the
            # bytes the run read; this builder never re-derives it, because a
            # digest recomputed here would describe whatever is on disk NOW
            # rather than what the run consumed (F-12bc-7's lesson: a pin
            # that follows the edit it exists to catch is not a pin).
            advice_sha256=_launch_identity.advice_sha256,
            advice_path=_launch_identity.advice_path,
            # F-SCANF-1 — CANONICAL, threaded explicitly like the six above.
            formal_eval_portion=_launch_identity.formal_eval_portion,
            workflow_parameter_rules=_launch_identity.workflow_parameter_rules,
            trial_time_admission_source=_launch_identity.trial_time_admission_source,
            formal_time_admission_source=_launch_identity.formal_time_admission_source,
            # Step 11 C3 (R-11-6) — stamped at the SAME shared builder, for
            # the same reason C9d is: every entry point then records the
            # ceilings its children actually ran under. Provenance, never
            # compared.
            execution_calibration=calibration_provenance(),
            # Step 12 / PR-12d, seam P — the same shape and the same
            # justification as the line above: a PROVENANCE field is read
            # from the run-scoped authority AT the shared builder, not
            # threaded through five call sites, because "what was active
            # when this lock was written" is exactly the question it
            # answers. The CANONICAL composition fingerprint is threaded
            # explicitly two lines up precisely because it is compared, and
            # a compared value must never arrive ambiently.
            model_plugin_identities=_model_plugin_identities(),
            # arXiv P1 — same shape and same justification again: a
            # PROVENANCE field read ambiently AT the shared builder, because
            # "which generated-capability library was active when this lock
            # was written" is exactly the question it answers. Recorded,
            # never compared.
            generated_library=generated_library_provenance(),
            **_runtime_identity_fields(include_runtime_identities),
        ),
        effective_path,
    )


def _model_plugin_identities() -> list[dict[str, str]] | None:
    """The run's declared model-plugin identities, or ``None`` when unbound.

    ``None`` — not ``[]`` — is what an un-composed run, and a composed run
    that declares no model plugins, produce: the key is then OMITTED from the
    serialized lock, so every pre-seam-P lock file stays byte-identical. An
    empty list would be a different, and wrong, statement: "this run declared
    plugins and there were none of them".
    """
    from ml_models.plugin_binding import active_run_model_plugins

    binding = active_run_model_plugins()
    return None if binding is None else binding.canonical_identities()


def _runtime_identity_fields(include: bool) -> dict[str, str | None]:
    """The runtime subsystem's behavioral identities for the lock.

    ``include=False`` is for tooling that must build a LEGACY-shaped
    invariant set (e.g. reading an old workspace); production callers
    always stamp them.
    """
    if not include:
        return {}
    from core.runtime_control.estimator import shared_runtime_components

    estimator, policy = shared_runtime_components()
    return {
        "runtime_estimator_identity": estimator.identity,
        "runtime_policy_identity": policy.identity,
    }


def validate_stamped_invariants(
    stamped: dict,
    expected: RunInvariants,
    *,
    full_scope: list[int],
    source: str,
) -> None:
    """Check one persisted record/output's invariant stamps against a run.

    Legacy-aware ingress validation for restored history and seed evidence:

    - ``resolved_data_scope`` missing → the record predates DataScope and
      was necessarily produced under the FULL scope (compared against
      ``full_scope``).
    - ``health_gate_enabled`` missing → the record predates the disabled
      mode and was produced with gates active — compatible ONLY with an
      enabled run.
    - ``health_config_sha256`` missing → predates the policy lock; the sha
      comparison is skipped (scope + enabled remain enforced).

    **Step 11 C8 / R-11-9 — the composition fingerprint, three cases.**
    ``_CANONICAL`` has included ``task_composition_fingerprint`` since
    Step 10, so the workspace LOCK refuses a cross-composition resume — but
    this INGRESS validator never looked at it, so a record produced under a
    different composition could be restored into a run that would then
    compare it as though it were its own (**F-11-6**). The asymmetry is
    closed under a rule that distinguishes the modes rather than picking one
    default::

        legacy / un-composed run + unstamped record   -> READABLE
        composed run + record carrying a fingerprint  -> must MATCH
        composed run + UNSTAMPED legacy record        -> REFUSE

    The third case is the one that needs stating. A record written before
    composition existed cannot be certified as belonging to this
    composition: "unstamped" says *nothing was recorded*, not *nothing was
    composed*. Treating absence as agreement is exactly how a
    cross-composition record would slip in, so this follows
    ``_reject_legacy_runtime_lock``'s precedent of refusing rather than
    defaulting. An UN-composed run is untouched by all of it, which is what
    keeps every pre-Step-10 workspace readable.

    **arXiv U1 (#254) — the experiment arm, the same three cases.** Keyed on
    whether THIS RUN is labelled, never on the label's value (R2)::

        unlabelled run + unstamped record     -> READABLE
        labelled run + record carrying an arm -> must MATCH
        labelled run + UNSTAMPED record       -> REFUSE (names the field)

    Raises:
        RunInvariantsViolation: any present-or-assumed stamp contradicts
            ``expected``; the message names ``source`` and the field.
    """
    problems: list[str] = []

    record_scope = stamped.get("resolved_data_scope")
    effective_scope = full_scope if record_scope is None else sorted(record_scope)
    if effective_scope != list(expected.resolved_data_scope):
        origin = "unstamped (legacy = full scope)" if record_scope is None else "stamped"
        problems.append(
            f"resolved_data_scope: record is {origin} {effective_scope} vs "
            f"this run's {list(expected.resolved_data_scope)}"
        )

    record_enabled = stamped.get("health_gate_enabled")
    effective_enabled = True if record_enabled is None else record_enabled
    if effective_enabled != expected.health_gate_enabled:
        origin = "unstamped (legacy = gates active)" if record_enabled is None else "stamped"
        problems.append(
            f"health_gate_enabled: record is {origin} {effective_enabled} vs "
            f"this run's {expected.health_gate_enabled}"
        )

    record_sha = stamped.get("health_config_sha256")
    if record_sha is not None and record_sha != expected.health_config_sha256:
        problems.append(
            f"health_config_sha256: record pinned {record_sha[:12]}… vs "
            f"this run's {(expected.health_config_sha256 or 'None')[:12]}…"
        )

    # Step 11 C8 / R-11-9 — the composition fingerprint. Keyed on whether
    # THIS RUN is composed, never on a task name.
    if expected.task_composition_fingerprint is not None:
        record_fingerprint = stamped.get("task_composition_fingerprint")
        if record_fingerprint is None:
            problems.append(
                "task_composition_fingerprint: this run is COMPOSED "
                f"({expected.task_composition_fingerprint[:12]}…) but the record "
                "carries no fingerprint. A record written before composition "
                "existed cannot be certified as belonging to this composition — "
                "unstamped means nothing was recorded, not that nothing was "
                "composed."
            )
        elif record_fingerprint != expected.task_composition_fingerprint:
            problems.append(
                f"task_composition_fingerprint: record pinned "
                f"{str(record_fingerprint)[:12]}… vs this run's "
                f"{expected.task_composition_fingerprint[:12]}…"
            )

    # arXiv U1 (#254) — the experiment arm. Keyed on whether THIS RUN is
    # labelled; the label itself is opaque and only ever compared (R2).
    if expected.experiment_arm is not None:
        record_arm = stamped.get("experiment_arm")
        if record_arm is None:
            problems.append(
                f"experiment_arm: this run is LABELLED ({expected.experiment_arm!r}) "
                "but the record carries no arm label. An unstamped record cannot "
                "be certified as belonging to this arm — unstamped means nothing "
                "was recorded, not that the record belongs to the same arm."
            )
        elif record_arm != expected.experiment_arm:
            problems.append(
                f"experiment_arm: record is labelled {record_arm!r} vs this run's "
                f"{expected.experiment_arm!r}"
            )

    if problems:
        detail = "\n".join(f"  - {p}" for p in problems)
        raise RunInvariantsViolation(
            f"ingress evidence from {source} is incompatible with this run's "
            f"invariants:\n{detail}\n"
            f"  Records are only comparable within one invariant set — start "
            f"a new workspace, or seed with matching-scope evidence."
        )
