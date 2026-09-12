"""
core/resume.py — Plugin + source-path restoration for chain-mode runs.

Per-iteration Python processes inherit nothing from prior iters' interpreters
— a fresh ``python run_one_iteration.py --start_iteration N`` starts with
``MODEL_REGISTRY`` at the built-in set. This module restores the "soul" of
every prior iter (1..N-1) into the current process before ``run_workflow``
runs.

The same code path serves both:
  * normal sequential chain (iter N+1 launched after iter N completes), and
  * SIGKILL-then-restart resume (iter K relaunched after a crash).

There is no "resume" branch in the Python — the contract is just
"current_iter > 1 means there are prior iters on disk to absorb".

See ``docs/phase68_orchestrator_memory_and_resume.md`` §3.3 for the design.
"""

from __future__ import annotations

import json
import math
import os
import re
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent.schemas.health_feedback import CollapseFingerprintHistoryEntry, TrialValidityFeedback
from agent.schemas.hyperparam_tuning import (
    GateExhaustionInfo,
    HyperparamTuningOutput,
    PhysicalRejection,
)
from agent.schemas.interpretation import (
    PREDICTION_SEMANTICS_SIGNSAFE_V2,
    PredictionMemory,
)
from agent.schemas.proposal import VocabEntry
from core.committed_digests import (
    DigestRead,
    digest_unusable_message,
    interpretation_digest_path,
    read_committed_digests,
)
from core.iteration_manifest import (
    MANIFEST_BASENAME,
    RUN_OUTPUT_DIGEST_KEY,
    ManifestVerdict,
    verify_iteration_manifest,
)
from core.run_invariants import (
    RunInvariants,
    load_run_invariants,
    validate_run_invariants,
    validate_stamped_invariants,
)
from core.sandbox_executor import get_plugin_dir
from core.scientific_authority import resolve_record_authority
from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.evaluation_metric import (
    StampedMetricSpec,
    metric_identity_from_record,
    metric_identity_unavailable_notice,
    reconcile_metric_identity,
)
from execute_tools.health_checks.candidate_eligibility import (
    CandidateHealthValidity,
    classify_under_pinned_policy,
    resolve_scientific_gate_ids,
)
from execute_tools.health_checks.config import (
    EFFECTIVE_CONFIG_BASENAME,
    read_effective_config_body_sha,
)
from execute_tools.metric_order import MetricOrder

# Step 12 / PR-12a C6 (09.5 Q2 = B) — the PUBLIC registration authority.
# `core` used to import a PRIVATE symbol from `workflows`, which is the wrong
# direction across the layering AND forced two cycle workarounds in
# `model_exploration` (a TYPE_CHECKING-only `RestoredState` and a
# function-local `union_key_findings`). The private duplicate is retired; both
# workarounds are gone.
from ml_models.plugin_loader import register_model_in_memory

# ---------------------------------------------------------------------------
# Cross-iter negative-feedback retention caps (V8 hardening §1).
# Keep the K most-recent entries across ALL prior committed iters; older ones
# are evicted. K=10 is the operator-approved balance between prompt bloat
# (each rendered rejection ≈150 chars, so K=10 → ~1.5 KB worst-case) and
# coverage (a 30-iter chain typically has ≤2 distinct architectural classes
# rejected, so 10 is generous). See docs/V8_Gap_Report.md Domain 1.
# ---------------------------------------------------------------------------
_MAX_ACCUMULATED_REJECTIONS = 10
_MAX_ACCUMULATED_GATE_EXHAUSTIONS = 10


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ResumeError(RuntimeError):
    """Raised when the workspace state is incompatible with resuming.

    Distinct from generic ``RuntimeError`` so the chain runner can surface a
    targeted operator-facing message ("iter 003 manifest is missing — was
    the chain interrupted between iter 002 commit and iter 003 launch?")
    rather than a stack trace.
    """


class ReplayIntegrityError(ResumeError):
    """A committed artifact changed after its manifest hashes were recorded.

    V19 PR 1 §3.6 (docs/design/v19_priorities/pr1_chain_incumbents.md):
    a ``run_output_sha256`` mismatch means chain history is no longer
    trustworthy — excluding-and-continuing could still alter the chain
    incumbent and therefore future decisions, so the chain STOPS before
    the next iteration launches. S2 / U5 (#257, #258) widened the
    predicate to the manifest's own ``manifest_sha256`` self-digest: an
    edited manifest field, a removed ``run_output_sha256`` on a completed
    iteration, or a rewritten artifact+hash pair with a stale self-digest
    all stop the chain the same way (``core.iteration_manifest``). A
    pre-S2 manifest carrying neither digest stays admitted and visibly
    unverified. Recovery is an explicit operator action: restore the
    original artifact, or replace the iteration through
    ``run_one_iteration.py --replace_iteration_manifest --replacement_reason``
    (which sets the old manifest aside and records its digests), then
    relaunch. Not bypassed by ``enable_chain_incumbent_formal_gates`` —
    integrity verification always runs.
    """


@dataclass
class RestoredState:
    """Result of :func:`restore_prior_state` — everything the chain runner
    needs to forward to ``run_workflow``.

    Attributes:
        resolved_source_paths: ordered list of source-data JSON paths to
            feed into ``run_workflow(source_paths=...)``. Layout:
            ``seed_paths`` first (in caller order), then prior iters'
            ``run_output`` JSON paths in ascending iter order. Mirrors what
            an in-process run would have accumulated naturally.
        restored_plugins: ``model_type`` strings whose plugin classes were
            re-registered into the four registry surfaces (see
            :func:`ml_models.plugin_loader.register_model_in_memory`).
            Plugin files that were missing on disk are *not* in this list
            (a warning is emitted but the restore continues — the JSON
            record is kept in ``resolved_source_paths`` because
            ``memory_history`` reconstruction doesn't need the class).
        committed_iters: 1-based iter indices successfully restored.
            Equivalent to ``range(1, current_iter)`` for a clean chain.
        runtime_vocab: latest committed iter's
            ``InterpretationOutput.runtime_vocab``, loaded from
            ``iter_NNN/iteration_NNN/interpretation_iter_NNN.json``. Empty
            list when ``current_iter == 1`` or no committed iter has a
            parseable interpretation digest. ``seen_in_runs`` is preserved
            verbatim — the next iter's ``build_runtime_vocab`` appends the
            current run's ID via the ``proposed_candidates`` channel only.
            See ``docs/Consistent_growing_vocab_list.md``.
        accumulated_key_findings: chronological union (dedup by string,
            first-occurrence wins) of every committed iter's
            ``InterpretationOutput.key_findings``. Forwarded to the next
            proposer as a single ``ExpertContextItem`` so the LLM sees the
            full chain history, not just iter N-1's take-homes.
        vocab_link_confirmations: latest committed iter's
            ``InterpretationOutput.vocab_link_confirmations`` — the map
            ``{"feature:capability": [confirming run_name, ...]}`` the
            interpreter accumulates and counts against ``min_runs`` before
            promoting a pair into ``VocabEntry.related_to``. Latest-wins
            whole-dict, because the producer already returns the FULL
            cumulative map every call; unioning here would be a second
            accumulation authority. ``{}`` when ``current_iter == 1`` or no
            committed digest carries the key (pre-activation digests). A
            present-but-malformed value raises — see
            :func:`project_vocab_link_confirmations`.
        accumulated_physical_rejections: VRAM-gate rejections collected
            from every committed iter's ``HyperparamTuningOutput.physical_rejections``,
            in chronological order, capped to the last
            ``_MAX_ACCUMULATED_REJECTIONS`` entries (most-recent wins on
            overflow). Forwarded to the next workflow's ``previous_failures``
            seed so the proposer sees full-chain VRAM lessons, not just
            iter N-1's. See docs/V8_Gap_Report.md Domain 1.
        accumulated_gate_exhaustions: gate-abort summaries collected from
            every committed iter's ``HyperparamTuningOutput.gate_exhaustion``
            (only when non-None), in chronological order, capped to the
            last ``_MAX_ACCUMULATED_GATE_EXHAUSTIONS`` entries. Forwarded
            to the next workflow's ``recent_tune_outputs`` deque so the
            proposer's ``[RECENT GATE EXHAUSTIONS]`` block reflects the
            chain history. See docs/V8_Gap_Report.md Domain 1.
        previous_proposal_data: latest committed iter's proposal JSON
            (raw dict, not validated) — the file produced by the
            proposal node at
            ``iter_NNN/iteration_NNN/attempt_MMM_<model>/proposal_iter_NNN.json``.
            Forwarded to the next iter's ``run_workflow`` as
            ``restored_previous_proposal``, replacing the unconditional
            ``None`` initialisation that today erases ``proposed_vocab_candidates``
            at every chain-subprocess boundary. Latest-wins semantics
            (one iter's snapshot, not a merged history) — the asymmetry
            with ``runtime_vocab`` is correct because the interp digest
            already carries cumulative ``seen_in_runs``; the proposal
            channel only contributes the iter-N delta. None when
            ``current_iter == 1`` or no committed iter has a parseable
            proposal JSON. See ``docs/Consistent_growing_vocab_list.md``
            §10 for the bridge design and the three downstream consumers
            this unblocks.
        model_knowledge_cache: latest committed iter's
            ``InterpretationOutput.model_knowledge_cache`` — the per-model
            Phase-1 summarisation cache (``Dict[model_type, cache_entry]``).
            Forwarded to the next iter's ``run_workflow`` as
            ``restored_model_knowledge_cache`` so that
            ``workflows/model_exploration.py:830``'s unconditional
            ``model_knowledge_cache: dict = {}`` becomes a chain-aware
            ``dict(restored_model_knowledge_cache)`` re-init. Without this,
            every chain subprocess starts with an empty cache, the
            interp agent's cache-hit branch never fires, and every
            ``model_type`` triggers a fresh ``interpretation.per_model``
            LLM call regardless of how stable its evidence is. Latest-wins
            semantics (mirrors ``runtime_vocab`` and ``previous_proposal_data``)
            because each digest already carries the rolling ``_cap_knowledge_cache``
            window — concatenating across iters would leak evicted entries
            back in. Empty dict when ``current_iter == 1`` or no committed
            iter has a parseable interpretation digest. See Commit 6.1.a
            in ``docs/audit_and_optimize_token_usage_and_growth.md``
            (Rev 8.3 changelog) for the audit that found the persistence /
            restoration asymmetry.
    """

    resolved_source_paths: list[str] = field(default_factory=list)
    restored_plugins: list[str] = field(default_factory=list)
    committed_iters: list[int] = field(default_factory=list)
    runtime_vocab: list[VocabEntry] = field(default_factory=list)
    accumulated_key_findings: list[str] = field(default_factory=list)
    accumulated_physical_rejections: list[PhysicalRejection] = field(default_factory=list)
    accumulated_gate_exhaustions: list[GateExhaustionInfo] = field(default_factory=list)
    accumulated_negative_feedback: list[
        tuple[GateExhaustionInfo | None, TrialValidityFeedback | None]
    ] = field(default_factory=list)
    previous_proposal_data: dict | None = None
    model_knowledge_cache: dict[str, dict] = field(default_factory=dict)
    collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] = field(
        default_factory=dict
    )

    #: Step 09a C5 — the interpreter's prediction state (four digest fields in
    #: one typed carrier). Exactly ONE new restored field, by the ruling's
    #: scope: no other restored value, no restore-precedence change, and no
    #: second store — the digest remains the canonical record.
    prediction_memory: PredictionMemory = field(default_factory=PredictionMemory)

    #: Step 10 / P5+P6 C1 — the vocab-link confirmation map, restored so the
    #: producer's ``min_runs`` promotion counter survives the subprocess
    #: boundary. Latest-wins whole-dict (the producer already accumulates);
    #: ``{}`` for a fresh chain or a pre-activation digest set.
    vocab_link_confirmations: dict[str, list[str]] = field(default_factory=dict)

    # --- V19 PR 1 chain incumbents (design doc §3.3) -----------------------
    # ``chain_best_valid_formal_*`` is the DECISION-STATE incumbent: the best
    # commit-time-HealthGate-valid FORMAL score across committed iterations,
    # with full provenance ({iter_idx, round_index, round_provenance,
    # exp_id, model_type, score, resolved_data_scope, health_config_sha256,
    # validity_basis, artifact_verified}). Consumed ONLY by the formal
    # delta gates (behind ``enable_chain_incumbent_formal_gates``) and
    # provenance stamps — never serialized as any iteration's own best_*.
    # ``chain_best_trial_*`` is READ-ONLY bookkeeping context; its
    # provenance additionally carries the mandatory sampling fields
    # (eval_strategy, eval_portion, train_portion). ``None`` = no eligible
    # incumbent (fresh chain, or nothing commit-time valid).
    chain_best_valid_formal_score: float | None = None
    chain_best_valid_formal_provenance: dict[str, Any] | None = None
    chain_best_trial_score: float | None = None
    chain_best_trial_provenance: dict[str, Any] | None = None


NegativeFeedback = tuple[GateExhaustionInfo | None, TrialValidityFeedback | None]


def _append_negative_feedback(
    state: RestoredState,
    gate_exhaustion: GateExhaustionInfo | None,
    trial_feedback: TrialValidityFeedback | None,
) -> None:
    """Append one bounded negative-evidence pair when either fact exists."""
    if gate_exhaustion is not None or trial_feedback is not None:
        state.accumulated_negative_feedback.append((gate_exhaustion, trial_feedback))


def _restore_no_records_feedback(
    raw_feedback: object,
    *,
    iter_idx: int,
    state: RestoredState,
) -> None:
    """Validate and restore the bounded evidence from a no-records iteration."""
    if not isinstance(raw_feedback, dict):
        raise ResumeError(f"iter {iter_idx:03d}: no_records negative_feedback must be an object")
    unknown = sorted(set(raw_feedback) - {"gate_exhaustion", "trial_validity_feedback"})
    if unknown:
        raise ResumeError(
            f"iter {iter_idx:03d}: no_records negative_feedback has unknown field(s): {unknown}"
        )
    try:
        gate_exhaustion = (
            GateExhaustionInfo.model_validate(raw_feedback["gate_exhaustion"])
            if raw_feedback.get("gate_exhaustion") is not None
            else None
        )
        trial_feedback = (
            TrialValidityFeedback.model_validate(raw_feedback["trial_validity_feedback"])
            if raw_feedback.get("trial_validity_feedback") is not None
            else None
        )
    except Exception as exc:
        raise ResumeError(
            f"iter {iter_idx:03d}: no_records negative_feedback failed validation: {exc}"
        ) from exc
    if gate_exhaustion is not None:
        state.accumulated_gate_exhaustions.append(gate_exhaustion)
    _append_negative_feedback(state, gate_exhaustion, trial_feedback)


def _trim_negative_feedback(state: RestoredState) -> None:
    """Apply the same bounded history window used for gate exhaustion."""
    state.accumulated_negative_feedback = state.accumulated_negative_feedback[
        -_MAX_ACCUMULATED_GATE_EXHAUSTIONS:
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_run_name(iter_idx: int) -> str:
    """Chain-mode ``run_name`` convention.

    Mirrors ``src/workflows/run_one_iteration.py`` line 271
    (``run_name = f"iter_{args.iteration:03d}"``). Centralising the format
    string here means resume cannot drift from the writer.
    """
    return f"iter_{iter_idx:03d}"


def _read_manifest(workspace: str, iter_idx: int) -> dict:
    """Load + minimally validate ``iter_NNN/manifest.json``.

    Returns the manifest dict for either a completed iter or a clean
    no-records iter. Callers must inspect ``manifest["status"]`` and
    branch accordingly (``"completed"`` → consume; ``"no_records"`` →
    skip with no plugin restore).

    Raises :class:`ResumeError` for missing file, malformed JSON,
    ``status == "failed"`` (true crash → halt), unknown status, or
    ``status == "completed"`` with a missing ``output_path``.
    """
    manifest_path = os.path.join(workspace, _iter_run_name(iter_idx), "manifest.json")
    if not os.path.isfile(manifest_path):
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest.json not found at "
            f"{manifest_path}. The chain was interrupted before this iter "
            f"committed; rerun this iter from scratch (or pass "
            f"--start_iteration {iter_idx} to skip the missing prior)."
        )
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest.json is malformed at {manifest_path}: {e}"
        ) from e

    status = manifest.get("status")
    if status == "no_records":
        # Clean no-records exit (gate exhaustion or all-rounds-failed).
        # Caller skips this iter — no output_path, no plugin to restore.
        return manifest
    if status != "completed":
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest status={status!r}, expected "
            f"'completed' or 'no_records'. Refusing to chain off a "
            f"failed/unknown iter."
        )
    output_path = manifest.get("output_path")
    if not output_path:
        raise ResumeError(f"iter {iter_idx:03d}: manifest has no output_path: {manifest_path}")
    return manifest


def _validate_run_output(
    output_path: str,
    iter_idx: int,
) -> HyperparamTuningOutput:
    """Validate the run_output JSON against ``HyperparamTuningOutput``.

    Same predicate as ``scripts/launch/inspect_run_state.py:91-104`` so the
    inspector and the resume helper agree on what "committed" means.
    """
    if not os.path.isfile(output_path):
        raise ResumeError(
            f"iter {iter_idx:03d}: manifest points at output_path "
            f"{output_path} but the file does not exist."
        )
    try:
        with open(output_path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise ResumeError(f"iter {iter_idx:03d}: cannot read run_output {output_path}: {e}") from e
    try:
        return HyperparamTuningOutput.model_validate_json(text)
    except Exception as e:  # pydantic ValidationError or json parse
        raise ResumeError(
            f"iter {iter_idx:03d}: run_output failed validation at {output_path}: {e}"
        ) from e


# ---------------------------------------------------------------------------
# V19 PR 1 — chain-incumbent reconstruction (design doc §3.3/§3.6).
# Commit-time validity ONLY: the repo-current configs/health/health_checks.yaml is
# NEVER consulted for decision state. Candidates whose commit-time validity
# cannot be established are UNKNOWN and excluded.
# ---------------------------------------------------------------------------


def _verify_manifest_or_stop(
    manifest: dict,
    *,
    iter_idx: int,
    manifest_path: str,
    output_path: str | None,
) -> ManifestVerdict:
    """Raise :class:`ReplayIntegrityError` unless the manifest is trustworthy.

    S2 / U5: the predicate lives in ``core.iteration_manifest`` so resume,
    the per-file best table and the inspector cannot disagree about what
    "committed" means; this wrapper only supplies resume's prefix and its
    recovery advice.
    """
    verdict = verify_iteration_manifest(
        manifest, iter_idx=iter_idx, manifest_path=manifest_path, output_path=output_path
    )
    if verdict.problem is not None:
        raise ReplayIntegrityError(
            f"[resume] REPLAY-INTEGRITY: {verdict.problem}. A committed artifact no "
            f"longer matches its manifest hashes — chain history is not trustworthy. "
            f"Restore the original artifact, or replace the iteration explicitly "
            f"(run_one_iteration.py --replace_iteration_manifest --replacement_reason "
            f"'<why>'), then relaunch."
        )
    return verdict


def _scores_agree(a: float, b: float) -> bool:
    """Operator-fixed tolerance (design §3.3): |a-b| <= 1e-9 * max(1, |a|)."""
    return abs(a - b) <= 1e-9 * max(1.0, abs(a))


def _record_dict(record: Any) -> dict[str, Any]:
    """Normalize an ExperimentRecord model (or dict) to a plain dict."""
    if isinstance(record, dict):
        return record
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    return {}


def _round_provenance(record: dict[str, Any]) -> tuple[int | None, str]:
    """Round identity from the PERSISTED ``logical_round`` only.

    Design §3.3 (rev 3): position in ``all_records`` is NOT a round index
    and is never presented as one — the field is conditionally written, so
    no positional invariant exists. Missing/null → ``(None,
    "legacy_unknown")``, an explicit gap rather than a fabricated value.
    """
    lr = record.get("logical_round")
    if isinstance(lr, int) and not isinstance(lr, bool):
        return lr, "persisted"
    return None, "legacy_unknown"


def _effective_config_body_sha(path: str) -> str | None:
    """Canonical body sha of a materialized effective config.

    **Delegates rather than mirrors** (Step 08b C4). This used to re-derive
    the sha by loading the file into ``HealthChecksConfig`` and re-dumping
    it, which silently dropped any key the model does not declare — and 08b's
    ``resolved_plugins`` / ``task_health_binding`` are exactly such keys, so
    the mirror would have reported a mismatch that was not there. One
    implementation cannot drift from itself.

    ``None`` when the file is missing or unparseable, unchanged.
    """
    return read_effective_config_body_sha(path)


def _commit_time_gate_ids(
    parsed: HyperparamTuningOutput,
    output_path: str,
    workspace: str,
) -> frozenset[str] | None:
    """Blocking-gate ids under the iteration's COMMIT-TIME effective policy.

    Locates the materialized ``health_checks_effective.yaml`` (tuner
    workspace beside the run_output, falling back to the chain root) and
    accepts it only when its canonical body sha equals the iteration's
    stamped ``health_config_sha256``. Returns ``None`` when commit-time
    gate-set completeness cannot be established (missing stamp, missing
    artifact, or sha mismatch) — callers must treat affected candidates
    as UNKNOWN. The repo-current shipped config is deliberately never
    used here (design §3.3).
    """
    stamped = getattr(parsed, "health_config_sha256", None)
    if not stamped:
        return None
    candidates = (
        os.path.join(os.path.dirname(output_path), EFFECTIVE_CONFIG_BASENAME),
        os.path.join(workspace, EFFECTIVE_CONFIG_BASENAME),
    )
    for path in candidates:
        if os.path.isfile(path) and _effective_config_body_sha(path) == stamped:
            # `resolve_scientific_gate_ids`, not `required_blocking_gate_ids`:
            # the shared resolver reads the DECLARED `gate_role` and can
            # return None for a role-less config whose sha is not in the
            # audited compatibility map. The deprecated shim collapses that
            # None to an empty set, which reads as "no gate is required" —
            # i.e. everything valid — and is how a record rejected in-run
            # could become the incumbent on resume.
            return resolve_scientific_gate_ids(path)
    return None


def _classify_commit_time(
    record: dict[str, Any],
    gate_ids: frozenset[str] | None,
) -> CandidateHealthValidity:
    """Commit-time validity of one record from PERSISTED verdicts only.

    The record-level ``health_gate_enabled=False`` waiver (DS5 stamp)
    applies without needing the policy artifact; otherwise gate-set
    completeness is judged against the commit-time ``gate_ids`` — and an
    unresolvable policy (``gate_ids is None``) yields UNKNOWN, never a
    fallback to repo-current policy.

    That rule now has ONE home,
    :func:`~execute_tools.health_checks.candidate_eligibility.classify_under_pinned_policy`,
    because the Stage-3 and gold-campaign readers need exactly it (F-4) and a
    second copy is how two readers of the same records start disagreeing.
    What stays HERE is the resume-specific half above it:
    :func:`_commit_time_gate_ids` resolves the artifact the ITERATION'S OWN
    stamped sha verifies, which is a stronger question than "the workspace's
    pinned config" and is not shared.
    """
    return classify_under_pinned_policy(record, gate_ids)


def _pick_best(records: list[dict[str, Any]], *, order: MetricOrder) -> dict[str, Any] | None:
    """Within-iteration selection: BEST score; tie → lexicographic smallest
    ``exp_id`` (design §3.3 tie rules; cross-iteration earliest-wins is
    enforced by the strictly-better update in the caller's walk).

    Step 10 P2a C2: "best" is the metric's own direction, asked of
    ``MetricOrder`` — under a minimised metric this selects the MINIMUM. The
    ``order`` is keyword-only and has NO default: a caller that has not
    reconciled an identity must not be able to reach a ranking by omission.

    The ``exp_id`` tie-break is DIRECTION-INDEPENDENT and is untouched.
    """
    best: dict[str, Any] | None = None
    for rec in records:
        if best is None:
            best = rec
            continue
        score, best_score = rec["denoising_score"], best["denoising_score"]
        if order.is_better(score, best_score) or (
            score == best_score and str(rec.get("exp_id")) < str(best.get("exp_id"))
        ):
            best = rec
    return best


def _chain_fold_order(parsed: HyperparamTuningOutput) -> MetricOrder | None:
    """The order the CHAIN-level incumbent fold ranks one iteration's candidate by.

    Step 10 P2a C2, deviation D-P2a-1. The chain fold compares an iteration's
    winning candidate against the incumbent carried across iterations, so its
    identity source is that iteration's own stamped ``MetricSpec``. ``None``
    when the output carries none — a named refusal, never a re-derivation
    (parent §8), which leaves the chain incumbent untouched for that iteration
    rather than advancing it on an assumed direction.
    """
    run_spec = getattr(parsed, "metric_spec", None)
    if run_spec is None:
        print(
            metric_identity_unavailable_notice(
                "the chain incumbent fold",
                detail=f"{parsed.run_name!r} carries no stamped MetricSpec",
            )
        )
        return None
    return MetricOrder(run_spec)


def _rankable_pool(
    records: list[dict[str, Any]],
    parsed: HyperparamTuningOutput,
    *,
    context: str,
) -> tuple[list[dict[str, Any]], MetricOrder | None]:
    """Split a candidate pool into what may be RANKED, and the order to rank by.

    Design §4.2/§4.2a, applied PER RECORD:

    * a record carrying no metric identity is excluded INDIVIDUALLY — one
      legacy row never poisons an otherwise compatible corpus (case B);
    * the remaining identities are reconciled against the output's own
      ``metric_spec`` stamp through the SHARED authority; conflicting KNOWN
      identities fail closed (case D);
    * no rankable record, or no spec to order by, yields ``None`` — the caller
      restores no incumbent and says so (case C).

    The order comes from the output's stamped ``MetricSpec``, never from a
    spec re-derived out of a record's identity: parent §8 requires a named
    refusal rather than a re-derivation, and a record only ever declared
    ``(id, direction)``.

    Raises:
        MetricIdentityConflictError: conflicting known identities within the
            pool, or against the output's stamp.
    """
    identities = [(rec, metric_identity_from_record(rec)) for rec in records]
    rankable = [rec for rec, identity in identities if identity is not None]
    excluded = [rec for rec, identity in identities if identity is None]

    if excluded:
        print(
            metric_identity_unavailable_notice(
                f"{len(excluded)} of {len(records)} {context} candidate records",
                detail="excluded individually; the remaining records still compete",
            )
        )
    if not rankable:
        return [], None

    run_spec = getattr(parsed, "metric_spec", None)
    # Raises on a conflict — among the records themselves, or against the
    # output's stamp. Never silently prefers one identity.
    reconcile_metric_identity(
        [
            StampedMetricSpec(label=f"record {rec.get('exp_id')!r}", spec=identity)
            for rec, identity in identities
            if identity is not None
        ],
        bound=run_spec,
        bound_label=f"the run's stamped MetricSpec ({parsed.run_name!r})",
    )
    if run_spec is None:
        # The records agree on an identity, but nothing carries the declaration
        # the order must be built from. A named refusal, NOT a re-derivation.
        print(
            metric_identity_unavailable_notice(
                f"the {context} incumbent",
                detail=f"{parsed.run_name!r} carries no stamped MetricSpec",
            )
        )
        return [], None
    return rankable, MetricOrder(run_spec)


def _summary_mismatch(iter_idx: int, field_name: str, detail: str) -> None:
    print(
        f"[resume] SUMMARY-MISMATCH: iter {iter_idx:03d} {field_name}: {detail} "
        f"— candidate classified UNKNOWN and excluded from decision state."
    )


# ---------------------------------------------------------------------------
# Public boundary — V19 PR 1 shared helper for other in-repo callers that
# need the SAME commit-time validity classification as the incumbent
# reconstruction, without duplicating logic or importing private names
# (design doc §3.7.3, rev 3.1 — the smallest boundary P1-C5 needs).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommitTimeClassification:
    """Commit-time classification of one ``ExperimentRecord`` for public use.

    ``validity_basis`` mirrors the ``gate_summary`` schema in the P1-C5
    per-file best table (design doc §3.7 A2):

      * ``committed_fields`` — record matched the parsed output's
        summary fields under the P1-C2 six-check contract (formal path
        only; caller decides when to route here);
      * ``persisted_verdicts`` — re-derived from the record's per-gate
        results against the iteration's commit-time policy;
      * ``waiver`` — the DS5 ``health_gate_enabled=False`` stamp (record
        waived from gate requirement at commit time);
      * ``unknown`` — commit-time validity could not be established (no
        stamp, missing effective-policy artifact, sha mismatch, or
        required verdicts absent).

    ``round_index`` / ``round_provenance`` follow §3.3: never fabricated
    from list position — persisted ``logical_round`` or explicit
    ``legacy_unknown``.
    """

    validity: CandidateHealthValidity
    validity_basis: str
    round_index: int | None
    round_provenance: str


def classify_committed_record(
    record: Any,
    parsed_output: HyperparamTuningOutput,
    output_path: str,
    workspace: str,
) -> CommitTimeClassification:
    """Return commit-time validity + round provenance for one record.

    Uses ONLY commit-time evidence: the iteration's persisted per-record
    gate verdicts interpreted against the workspace's materialized
    effective HealthGate policy (accepted only when its canonical body
    sha equals the iteration's stamped ``health_config_sha256``). The
    repo-current shipped ``configs/health/health_checks.yaml`` is NEVER
    consulted — the same rule that makes incumbent reconstruction
    stable across repo-policy edits (design doc §3.3).

    Args:
        record: an ``ExperimentRecord`` model or a plain dict as
            serialized in ``run_output_*.json`` ``all_records``.
        parsed_output: the validated ``HyperparamTuningOutput`` the
            record was pulled from (needed for ``health_config_sha256``
            when resolving commit-time gate ids).
        output_path: absolute path of that ``run_output_*.json`` (used
            for the effective-config lookup fallback: file's directory
            first, then the workspace root).
        workspace: chain workspace root.

    Returns:
        :class:`CommitTimeClassification`. The caller decides how to use
        it — this function performs no artifact-hash verification or
        summary/source cross-checks (those live in resume's incumbent
        walker for incumbent-specific reasons).
    """
    rec = _record_dict(record)
    gate_ids = _commit_time_gate_ids(parsed_output, output_path, workspace)
    validity = _classify_commit_time(rec, gate_ids)

    if rec.get("health_gate_enabled") is False:
        validity_basis = "waiver"
    elif gate_ids is None:
        validity_basis = "unknown"
    else:
        validity_basis = "persisted_verdicts"

    round_index, round_provenance = _round_provenance(rec)
    return CommitTimeClassification(
        validity=validity,
        validity_basis=validity_basis,
        round_index=round_index,
        round_provenance=round_provenance,
    )


def _formal_candidate_from_committed_fields(
    parsed: HyperparamTuningOutput,
    manifest: dict,
    iter_idx: int,
) -> dict[str, Any] | None:
    """§3.3 step 1: committed ``best_valid_formal_*`` fast path, with
    mandatory summary-vs-source-record validation (rev 3). Any check
    failure → ``None`` (UNKNOWN, excluded) with a visible warning."""
    score = parsed.best_valid_formal_denoising_score
    if score is None:
        return None  # not this path — caller falls to verdict re-derivation
    exp_id = parsed.best_valid_formal_exp_id
    if not exp_id:
        _summary_mismatch(
            iter_idx, "best_valid_formal_exp_id", "null exp_id beside a non-null score"
        )
        return None
    source = next(
        (r for r in (_record_dict(rec) for rec in parsed.all_records) if r.get("exp_id") == exp_id),
        None,
    )
    if source is None:
        _summary_mismatch(
            iter_idx, "best_valid_formal_exp_id", f"exp_id {exp_id!r} absent from all_records"
        )
        return None
    if source.get("is_trial"):
        _summary_mismatch(
            iter_idx, "best_valid_formal_exp_id", f"source record {exp_id!r} is a TRIAL"
        )
        return None
    rec_score = source.get("denoising_score")
    if (
        not isinstance(rec_score, int | float)
        or isinstance(rec_score, bool)
        or not math.isfinite(rec_score)
    ):
        _summary_mismatch(
            iter_idx,
            "best_valid_formal_denoising_score",
            f"source record {exp_id!r} has no finite score",
        )
        return None
    if not _scores_agree(float(score), float(rec_score)):
        _summary_mismatch(
            iter_idx,
            "best_valid_formal_denoising_score",
            f"summary {score!r} vs record {rec_score!r} beyond tolerance",
        )
        return None
    manifest_score = manifest.get("best_valid_formal_score")
    if manifest_score is not None and not _scores_agree(float(score), float(manifest_score)):
        _summary_mismatch(
            iter_idx,
            "best_valid_formal_score",
            f"output {score!r} vs manifest {manifest_score!r} conflict",
        )
        return None
    for stamp in ("resolved_data_scope", "health_config_sha256"):
        m_val, o_val = manifest.get(stamp), getattr(parsed, stamp, None)
        if m_val is not None and o_val is not None and m_val != o_val:
            _summary_mismatch(iter_idx, stamp, f"manifest {m_val!r} vs output {o_val!r} conflict")
            return None
    round_index, round_prov = _round_provenance(source)
    return {
        "record": source,
        "score": float(score),
        "round_index": round_index,
        "round_provenance": round_prov,
        "validity_basis": "committed_fields",
    }


def _candidates_from_persisted_verdicts(
    parsed: HyperparamTuningOutput,
    gate_ids: frozenset[str] | None,
    *,
    want_trial: bool,
) -> dict[str, Any] | None:
    """§3.3 step 2: re-derive from persisted per-record gate verdicts."""
    pool: list[dict[str, Any]] = []
    for rec in parsed.all_records:
        r = _record_dict(rec)
        if bool(r.get("is_trial")) is not want_trial:
            continue
        if _classify_commit_time(r, gate_ids) is not CandidateHealthValidity.VALID:
            continue
        pool.append(r)
    # Step 10 P2a C2 — reconcile identity BEFORE ordering. Validity filtering
    # above is unchanged and still runs first; this only decides which of the
    # already-valid candidates carry enough identity to be ranked at all.
    rankable, order = _rankable_pool(pool, parsed, context="trial" if want_trial else "formal")
    if order is None:
        return None
    best = _pick_best(rankable, order=order)
    if best is None:
        return None
    round_index, round_prov = _round_provenance(best)
    return {
        "record": best,
        "score": float(best["denoising_score"]),
        "round_index": round_index,
        "round_provenance": round_prov,
        "validity_basis": "persisted_verdicts",
    }


def _formal_candidate_is_authoritative(
    candidate: dict[str, Any],
    parsed: HyperparamTuningOutput,
    gate_ids: frozenset[str] | None,
    iter_idx: int,
) -> bool:
    """V20 PR D (D-C4): may this formal candidate become the incumbent?

    The authority question is answered by consuming the typed verdict
    D-C2a/D-C2b already produce — never re-derived here from gate ids,
    configured actions, an ``_blocking`` suffix, the score, the trial
    evidence, or whether the round bypassed its time budget. A second
    authority implementation is exactly the divergence the predecessor
    hotfix (``af5339ce``) existed to remove.

    Fail-closed. The persisted verdict is a plain dict that any later
    writer could edit, so :func:`resolve_record_authority` re-derives the
    conclusions from the record's own facts and refuses anything that
    disagrees with itself. Excluded candidates are announced with a
    structured reason rather than dropped silently — an operator watching
    an incumbent stop advancing needs to know which record was refused and
    why.

    Args:
        candidate: the formal candidate dict (carries ``record``).
        parsed: the iteration's validated output — supplies the
            output-level declaration used to reconstruct a legacy record.
        gate_ids: commit-time blocking gate ids for this iteration.
        iter_idx: for the log line.

    Returns:
        ``True`` only for an authoritative record.
    """
    record = candidate["record"]
    resolution = resolve_record_authority(
        record,
        declared_healthgate_mode=getattr(parsed, "healthgate_mode", None),
        declared_result_authority=getattr(parsed, "result_authority", None),
        commit_time_validity=_classify_commit_time(record, gate_ids).value,
    )
    if resolution.authoritative:
        candidate["authority_basis"] = resolution.basis
        return True
    print(
        f"[resume] iter {iter_idx:03d}: formal candidate "
        f"{record.get('exp_id')!r} (score {candidate['score']!r}) is NOT "
        f"scientifically authoritative — reason={resolution.exclusion_reason}, "
        f"basis={resolution.basis}. The record is kept; it cannot become the "
        f"chain incumbent (V20 PR D §16.D)."
    )
    return False


def _build_provenance(
    candidate: dict[str, Any],
    parsed: HyperparamTuningOutput,
    iter_idx: int,
    artifact_verified: bool,
    *,
    trial: bool,
) -> dict[str, Any] | None:
    """Assemble the provenance dict (design §3.3 schema). For trial
    candidates the sampling fields are MANDATORY — a valid trial record
    lacking them is uninterpretable and excluded (with a warning)."""
    record = candidate["record"]
    prov: dict[str, Any] = {
        "iter_idx": iter_idx,
        "round_index": candidate["round_index"],
        "round_provenance": candidate["round_provenance"],
        "exp_id": record.get("exp_id"),
        "model_type": record.get("model_type") or parsed.model_type,
        "score": candidate["score"],
        "resolved_data_scope": getattr(parsed, "resolved_data_scope", None),
        "health_config_sha256": getattr(parsed, "health_config_sha256", None),
        "validity_basis": candidate["validity_basis"],
        "artifact_verified": artifact_verified,
    }
    if not trial:
        # V20 PR D (D-C4): HOW authority was established for the record
        # that became the incumbent. Set by the admission predicate, which
        # runs before this, so a present incumbent always carries it —
        # `validity_basis` says the gates passed, this says the result was
        # allowed to inform science, and they are different questions.
        prov["authority_basis"] = candidate.get("authority_basis")
    if trial:
        eval_strategy = record.get("eval_strategy")
        eval_portion = record.get("eval_portion")
        if eval_strategy is None or eval_portion is None:
            print(
                f"[resume] iter {iter_idx:03d}: trial candidate "
                f"{record.get('exp_id')!r} lacks sampling provenance "
                f"(eval_strategy={eval_strategy!r}, eval_portion={eval_portion!r}) "
                f"— excluded from the trial incumbent (design §3.3)."
            )
            return None
        prov.update(
            {
                "eval_strategy": eval_strategy,
                "eval_portion": eval_portion,
                "train_portion": record.get("train_portion"),
            }
        )
    return prov


# ---------------------------------------------------------------------------
# Knowledge carry-over (cross-iter vocab + findings persistence)
# ---------------------------------------------------------------------------


def _interpretation_path(workspace: str, iter_idx: int) -> str:
    """Path convention for the chain-mode interpretation digest.

    Step 09.5a C1: the convention itself now lives with the committed-digest
    authority, so the reader and any caller resolving a digest path cannot
    disagree. This name is kept because it is the established one and several
    tests import it.
    """
    return interpretation_digest_path(workspace, iter_idx)


def union_key_findings(existing: list[str], incoming: Iterable[object] | None) -> list[str]:
    """THE union rule for accumulated key findings — ONE authority.

    Non-empty ``str`` only, dedup by exact string, FIRST occurrence wins,
    order preserved. Mutates and returns ``existing``.

    Both consumers call this rather than re-implementing it: the digest
    projection (`project_knowledge`, which unions across restored digests)
    and `run_workflow`'s loop closure (which unions the current iteration's
    findings into the carried history). That is what makes an uninterrupted
    in-process trajectory and a per-iteration chain restore produce EQUAL
    state BY CONSTRUCTION rather than by two implementations that happen to
    agree today — if this rule ever normalises (strip, casefold), both paths
    move together. An earlier revision had two bodies whose comment claimed
    the rule was "applied, not re-implemented"; it was re-implemented, and
    only the C4 equality test stood between that and a silently divergent
    chain history.

    First-wins also makes the union IDEMPOTENT, which is what lets a resume
    re-union the same digests without duplicating.
    """
    seen = set(existing)
    for finding in incoming or []:
        if isinstance(finding, str) and finding and finding not in seen:
            existing.append(finding)
            seen.add(finding)
    return existing


def project_knowledge(
    reads: Sequence[DigestRead],
) -> tuple[list[VocabEntry], list[str]]:
    """Project knowledge carry-over from already-read committed digests.

    Step 09.5a C1: this was ``load_latest_knowledge``, which did its own I/O.
    It is now a PURE projection over :func:`core.committed_digests.read_committed_digests`
    output — one of four, each keeping its own merge rule and failure policy.

    Args:
        reads: every committed digest of this restoration pass, ascending, each
            already classified ok / missing / unreadable. An empty sequence
            (nothing committed, or ``current_iter <= 1``) yields ``([], [])``.

    Returns:
        ``(runtime_vocab, accumulated_key_findings)``:
          * ``runtime_vocab`` — the LATEST parseable digest's ``runtime_vocab``.
            Per-entry validation failure drops that entry with a warning; the
            rest of the digest survives.
          * ``accumulated_key_findings`` — chronological union across every
            parseable digest, dedup by string, first-occurrence wins.

    Soft-fail policy: a missing or malformed digest warns and is skipped, and
    the warning names THIS carry-over so an operator can tell which value was
    affected — unchanged from before the consolidation.
    """
    runtime_vocab: list[VocabEntry] = []
    findings: list[str] = []

    for read in reads:
        if not read.ok:
            warnings.warn(
                digest_unusable_message(read, "knowledge"),
                UserWarning,
                stacklevel=2,
            )
            continue
        data = read.payload or {}

        union_key_findings(findings, data.get("key_findings"))

        # Latest parseable digest wins for runtime_vocab. Validate each entry
        # individually to drop malformed records without losing the rest.
        raw_vocab = data.get("runtime_vocab") or []
        validated: list[VocabEntry] = []
        for entry in raw_vocab:
            try:
                validated.append(VocabEntry.model_validate(entry))
            except Exception as e:
                warnings.warn(
                    f"[resume] iter {read.iter_idx:03d}: dropped malformed "
                    f"runtime_vocab entry {entry!r}: {e}",
                    UserWarning,
                    stacklevel=2,
                )
        if validated:
            runtime_vocab = validated  # overwrite: only LAST iter's wins

    return runtime_vocab, findings


def project_fingerprint_history(
    reads: Sequence[DigestRead],
) -> dict[str, list[CollapseFingerprintHistoryEntry]]:
    """Project the latest TYPED fingerprint history from committed digests.

    V19 PR 3 (pr3_healthgate_feedback.md §3.8/§11-CB5). Latest-wins, matching
    :func:`project_knowledge_cache`: each digest's
    ``collapse_fingerprint_history`` is already the merged, retention-trimmed
    history AFTER that iteration, so concatenating across iters would
    double-merge and resurrect expired buckets.

    Step 09.5a C1: formerly ``load_latest_fingerprint_history``; the I/O moved
    to the shared committed-digest authority, the semantics did not.

    A malformed entry RAISES rather than being dropped — deterministic gate
    evidence must not disappear silently. That is this projection's own policy
    and deliberately differs from :func:`project_knowledge`.
    """
    history: dict[str, list[CollapseFingerprintHistoryEntry]] = {}

    for read in reads:
        if not read.ok:
            warnings.warn(
                digest_unusable_message(read, "fingerprint-history"),
                UserWarning,
                stacklevel=2,
            )
            continue
        data = read.payload or {}

        raw = data.get("collapse_fingerprint_history") or {}
        if not raw:
            continue
        typed: dict[str, list[CollapseFingerprintHistoryEntry]] = {}
        for model_type, entries in raw.items():
            validated = []
            for entry in entries:
                try:
                    validated.append(CollapseFingerprintHistoryEntry.model_validate(entry))
                except Exception as e:
                    raise ValueError(
                        f"[resume] iter {read.iter_idx:03d}: corrupted "
                        f"collapse_fingerprint_history entry for model "
                        f"{model_type!r} in {read.path}: {e}. Refusing to drop "
                        f"deterministic gate evidence silently — fix or "
                        f"remove the digest."
                    ) from e
            typed[model_type] = validated
        history = typed  # overwrite: only the LATEST iter's wins

    return history


def project_prediction_memory(reads: Sequence[DigestRead]) -> PredictionMemory:
    """Project the latest interpreter prediction state from committed digests.

    Step 09a C5 (operator ruling Q-09a-1 = A, NARROW), Step 09.5a C1 (the I/O
    moved to the shared authority). A sibling of
    :func:`project_fingerprint_history` in every respect that matters:
    latest-wins, digest-only, one direction.

    A corrupted record RAISES: an accuracy statistic assembled from half a pool
    is worse than none. This projection's own policy.
    """
    memory = PredictionMemory()

    for read in reads:
        if not read.ok:
            warnings.warn(
                digest_unusable_message(read, "prediction-memory"),
                UserWarning,
                stacklevel=2,
            )
            continue
        data = read.payload or {}

        fields = {
            "prediction_outcomes_history": data.get("prediction_outcomes_history") or {},
            "prediction_outcomes_by_semantics": (
                data.get("prediction_outcomes_by_semantics") or {}
            ),
            "cumulative_information_gain": data.get("cumulative_information_gain") or 0.0,
            "cumulative_information_gain_by_semantics": (
                data.get("cumulative_information_gain_by_semantics") or {}
            ),
        }
        if not any(fields.values()):
            continue
        try:
            memory = PredictionMemory.model_validate(fields)  # overwrite: LATEST wins
        except Exception as e:
            raise ValueError(
                f"[resume] iter {read.iter_idx:03d}: corrupted prediction memory in "
                f"{read.path}: {e}. Refusing to restore a partial prediction record — "
                f"an accuracy statistic assembled from half a pool is worse than "
                f"none. Fix or remove the digest."
            ) from e

    return memory


def project_vocab_link_confirmations(
    reads: Sequence[DigestRead],
) -> dict[str, list[str]]:
    """Project the latest committed iter's vocab-link confirmation map.

    Step 10 / P5+P6 C1. The fifth projection, and a sibling of
    :func:`project_prediction_memory` in the two ways that matter: latest-wins,
    and a corrupted record RAISES.

    **Latest-wins on the WHOLE dict**, and the reason is a property of the
    producer, not a preference. ``update_vocab_link_confirmations``
    (``nodes/interpretation_helpers.py:587``) deep-copies the incoming mapping
    and returns the FULL cumulative map every call, so each normal digest
    already carries the complete history. A union across digests would be a
    SECOND accumulation authority: it would resurrect pairs a later iteration
    legitimately dropped, and it would let the workflow disagree with the
    producer about the promotion count. The producer owns the count; this
    projection only transports it.

    Consequences that follow, each deliberate:

    * a digest MISSING the key is SKIPPED, not treated as a reset: the latest
      digest that CARRIES the key wins, and when no digest carries it the
      result is ``{}``. Pre-activation digests predate this lifecycle, so an
      absent key is a compatible default, never fabricated history — and
      never a silent erasure of a mapping a newer key-less digest happens to
      sit in front of. (Unreachable once the producer is active, since it
      then always emits the key; stated because the code says it.)
    * an EMPTY mapping in the latest digest OVERWRITES an earlier non-empty
      one — ``{}`` is a legitimate cleared state, distinct from an absent key;
    * run lists pass through UNVALIDATED for duplicates. The producer is the
      only authority on the promotion count, so de-duplicating here could
      silently change WHEN a vocabulary relationship graduates.

    A present-but-malformed value RAISES (design §8.2, operator-approved):
    this is PROMOTION state, and silently keeping an older partial mapping can
    change when a scientific relationship graduates — the same argument
    :func:`project_prediction_memory` makes one level down ("an accuracy
    statistic assembled from half a pool is worse than none").

    Args:
        reads: every committed digest of this restoration pass, ascending, each
            already classified ok / missing / unreadable.

    Returns:
        ``{"feature:capability": [run_name, ...]}`` — the latest parseable
        digest's mapping, or ``{}`` when nothing committed carries one.

    Raises:
        ValueError: a digest carries the key with a value that is not a
            ``dict[str, list[str]]``.
    """
    confirmations: dict[str, list[str]] = {}

    for read in reads:
        if not read.ok:
            warnings.warn(
                digest_unusable_message(read, "vocab-link-confirmations"),
                UserWarning,
                stacklevel=2,
            )
            continue
        data = read.payload or {}

        if "vocab_link_confirmations" not in data:
            # Pre-activation digest: compatible default, no warning noise.
            continue
        raw = data["vocab_link_confirmations"]

        def _refuse(detail: str, *, _read: DigestRead = read) -> ValueError:
            return ValueError(
                f"[resume] iter {_read.iter_idx:03d}: corrupted "
                f"vocab_link_confirmations in {_read.path}: {detail}. Refusing "
                f"to restore a partial confirmation map — this is promotion "
                f"state, and silently keeping an older mapping can change WHEN "
                f"a vocabulary relationship graduates. Fix or remove the digest."
            )

        if not isinstance(raw, dict):
            raise _refuse(f"expected a mapping, got {type(raw).__name__}")
        validated: dict[str, list[str]] = {}
        for key, run_names in raw.items():
            if not isinstance(key, str):
                raise _refuse(f"non-string key {key!r}")
            if not isinstance(run_names, list):
                raise _refuse(f"key {key!r} maps to {type(run_names).__name__}, expected a list")
            for run_name in run_names:
                if not isinstance(run_name, str):
                    raise _refuse(f"key {key!r} contains non-string run name {run_name!r}")
            # Pass the list through as-is: no dedup, no reordering.
            validated[key] = list(run_names)
        confirmations = validated  # overwrite: only the LATEST iter's wins

    return confirmations


def project_knowledge_cache(reads: Sequence[DigestRead]) -> dict[str, dict]:
    """Project the latest committed iter's ``model_knowledge_cache``.

    Commit 6.1.a — cross-subprocess restoration of the per-model Phase 1 cache,
    so the interpreter's cache-hit branch is reachable in chain mode. Step 09.5a
    C1 moved the I/O to the shared committed-digest authority.

    Latest-wins. This projection has NO validator: an absent or non-dict value
    leaves the running cache untouched, while an *empty dict* on disk is a valid
    latest snapshot and overwrites — that is how an operator's eviction is
    honoured. Deliberately weaker than the two projections that raise.
    """
    cache: dict[str, dict] = {}

    for read in reads:
        if not read.ok:
            warnings.warn(
                digest_unusable_message(read, "knowledge-cache"),
                UserWarning,
                stacklevel=2,
            )
            continue
        data = read.payload or {}

        raw_cache = data.get("model_knowledge_cache")
        # `None` / missing key (legacy digest) -> leave the running `cache`
        # untouched and continue. An *empty dict* on disk is still a valid
        # latest snapshot — overwrite to reflect the operator's eviction.
        if isinstance(raw_cache, dict):
            cache = dict(raw_cache)  # latest-wins; defensive copy

    return cache


# ---------------------------------------------------------------------------
# Proposal carry-over (G1 bridge — proposed_vocab_candidates persistence).
# See docs/Consistent_growing_vocab_list.md §10.
# ---------------------------------------------------------------------------


def _proposal_path(workspace: str, iter_idx: int) -> str | None:
    """Resolve the proposal JSON path for a committed iter.

    Layout written by the proposal node + sandbox executor::

        {workspace}/iter_NNN/iteration_NNN/attempt_MMM_<model_name>/
                                                  proposal_iter_NNN.json

    Both NNN segments carry the same chain-wide iter index (see
    :func:`_interpretation_path` for the post-cc198ad rationale). The
    implementor produces one final attempt dir per iter under happy
    path; under validation retries, multiple ``attempt_MMM_*`` dirs may
    exist with monotonically increasing ``MMM`` prefix. The highest-MMM
    attempt is the one whose proposal was accepted, so it wins.

    Returns:
        Absolute path to the chosen proposal JSON, or ``None`` if no
        ``attempt_MMM_*`` directory exists (no_records iter).
    """
    import glob as _glob

    run_name = _iter_run_name(iter_idx)
    iteration_dir = os.path.join(
        workspace,
        run_name,
        f"iteration_{iter_idx:03d}",
    )
    if not os.path.isdir(iteration_dir):
        return None

    # Match attempt_MMM_<anything>/ directories. Sort by basename so
    # the lexicographic order on the zero-padded MMM prefix gives
    # numeric ordering (attempt_001 < attempt_002 < ... < attempt_999).
    candidates = sorted(
        _glob.glob(os.path.join(iteration_dir, "attempt_*_*")),
    )
    candidates = [c for c in candidates if os.path.isdir(c)]
    if not candidates:
        return None

    chosen = candidates[-1]  # highest MMM prefix wins
    proposal_file = os.path.join(chosen, f"proposal_{run_name}.json")
    if not os.path.isfile(proposal_file):
        return None
    return proposal_file


def load_latest_proposal(
    workspace: str,
    committed_iters: Sequence[int],
) -> dict | None:
    """Walk ``committed_iters`` in reverse; return the first parseable
    proposal dict.

    Latest-wins, mirrors :func:`load_latest_knowledge`'s ``runtime_vocab``
    semantics: the proposal channel forwards exactly one iter's snapshot
    (the most-recent one whose JSON parses), not a merged history. The
    downstream consumer (``workflows.model_exploration.run_workflow``)
    seeds ``previous_proposal_data`` with this dict in place of an
    unconditional ``None``.

    Args:
        workspace: chain workspace root (absolute path preferred).
        committed_iters: ascending list of iter indices already known
            to be committed (i.e. their manifests parsed cleanly via
            ``_read_manifest``). Empty → returns ``None``.

    Returns:
        The latest committed iter's ``proposal_iter_NNN.json`` contents
        as a raw dict, or ``None`` if no committed iter has a parseable
        proposal. The dict is **not** validated against any Pydantic
        schema here — the workflow does that on consumption.

    Soft-fail policy: a missing proposal file or a malformed JSON emits
    a ``UserWarning`` and is skipped; the loader falls back to the
    next-older iter and continues. This mirrors how
    :func:`load_latest_knowledge` tolerates a missing interpretation
    digest — proposal carry-over is best-effort, not a hard
    prerequisite. A no-records iter (no ``attempt_MMM_*`` subdir)
    returns silently with no warning since there is genuinely nothing
    to load.
    """
    if not committed_iters:
        return None

    for iter_idx in reversed(committed_iters):
        path = _proposal_path(workspace, iter_idx)
        if path is None:
            # No proposal file produced this iter (no_records or
            # implementor failure path). Silently fall back.
            continue
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            warnings.warn(
                f"[resume] iter {iter_idx:03d}: cannot read proposal "
                f"JSON {path}: {e}. Falling back to the next-older "
                f"committed iter for proposal carry-over.",
                UserWarning,
                stacklevel=2,
            )
            continue
        # Loader contract: latest parseable wins. Return immediately —
        # do NOT keep walking older iters.
        return data

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def restore_prior_state(
    workspace: str,
    current_iter: int,
    seed_paths: Sequence[str],
    expected_invariants: RunInvariants | None = None,
    dataset_partition_count: int | None = None,
) -> RestoredState:
    """Restore every prior iter's plugin classes and assemble the
    source-paths list for ``run_workflow``.

    Args:
        workspace: chain workspace root containing ``iter_NNN/`` and
            ``plugins/iter_NNN/`` subdirs. Same value as the ``--workspace``
        flag on ``src/workflows/run_one_iteration.py`` and
        ``scripts/launch/run_chain.sh``.
        current_iter: 1-based index of the iter this process is about to
            run. Iters ``[1, current_iter-1]`` are restored.
            ``current_iter == 1`` is a no-op that returns ``seed_paths``
            verbatim (no prior iters to absorb).
        seed_paths: caller's seed source paths (e.g. baseline punet/wavenet
            run_output JSONs). Prepended to the resolved list in original
            order. May be empty if the caller has no seeds.
        expected_invariants: this run's computed ``RunInvariants`` (DS6b).
            When provided, an existing workspace lock is validated up front,
            and every prior iter's parsed run_output has its invariant
            stamps checked BEFORE that iter's plugin is registered — a
            mismatch fails fast with zero registry mutation. ``None`` skips
            both checks (legacy callers; the chain runner threads this once
            its DataScope CLI lands — DS6c). Seed-path contents are NOT
            parsed here and are validated by ``run_workflow``'s pre-flight
            instead.
        dataset_partition_count: Number of partitions declared by the run's
            resolved dataset profile. The chain runner supplies this value
            explicitly because resume occurs before task-composition
            activation. ``None`` preserves the legacy bound-profile lookup.

    Returns:
        :class:`RestoredState` with ``resolved_source_paths``,
        ``restored_plugins``, and ``committed_iters`` populated.

    Raises:
        ResumeError: workspace state cannot be safely chained off — missing
            workspace dir, missing manifest, malformed JSON, unsupported
            status, invalid no-records feedback, missing run_output file, or
            run_output validation failure. The shell driver should surface
            this error and refuse to launch.

    Side effects:
        Calls :func:`register_model_in_memory` for each prior iter, which
        mutates the global ``MODEL_REGISTRY``, ``PLUGIN_CONFIG_REGISTRY``,
        and ``PLUGIN_OUTPUT_TYPE_REGISTRY``. Idempotent if the same plugin
        is already registered (overwrites with the same class).

    Warnings:
        Emits a ``UserWarning`` when a plugin file is missing on disk or
        fails ``_load_plugin`` validation. The JSON record is kept in
        ``resolved_source_paths`` either way because ``memory_history``
        reconstruction only reads the JSON; only training would need the
        class, and the chain never re-trains prior iters.
    """
    if current_iter < 1:
        raise ResumeError(f"current_iter must be >= 1, got {current_iter}")

    state = RestoredState(
        resolved_source_paths=list(seed_paths),
        restored_plugins=[],
        committed_iters=[],
    )

    if current_iter == 1:
        # No prior iters to absorb — seeds verbatim. This is the iter-1
        # path (clean chain start). Returning early keeps the workspace
        # check below from rejecting a not-yet-created chain dir.
        return state

    abs_workspace = os.path.abspath(workspace)
    if not os.path.isdir(abs_workspace):
        raise ResumeError(f"workspace does not exist: {abs_workspace}")

    # DS6b — fail on a contradicting workspace lock before touching any
    # prior iter (no plugin registration, no state accumulation). Lock
    # CREATION is not this function's job (run_workflow's pre-flight
    # creates it after all ingress evidence is validated).
    if expected_invariants is not None and load_run_invariants(abs_workspace) is not None:
        validate_run_invariants(abs_workspace, expected_invariants)

    # Strict ascending order — prior iters must be processed chronologically
    # so the source_paths list mirrors what an in-process run would build,
    # and so any plugin shadow-warnings happen in the same order.
    for iter_idx in range(1, current_iter):
        manifest = _read_manifest(abs_workspace, iter_idx)
        manifest_path = os.path.join(abs_workspace, _iter_run_name(iter_idx), MANIFEST_BASENAME)
        if manifest.get("status") == "no_records":
            # S2 / U5 — a no_records manifest names no artifact, but its
            # own self-digest is still verified: a hashed artifact that
            # changed after publication stops the chain whatever it says.
            _verify_manifest_or_stop(
                manifest, iter_idx=iter_idx, manifest_path=manifest_path, output_path=None
            )
            # Issue #396 — no scientific incumbent does not mean no
            # scientific evidence.  New manifests may carry the same bounded,
            # already-validated negative summaries produced by the tuner.
            # Validate them again at this process boundary before transport;
            # never parse a run output, restore a plugin, append a source path,
            # or mark the iteration committed on this branch.
            raw_feedback = manifest.get("negative_feedback")
            if raw_feedback is not None:
                _restore_no_records_feedback(raw_feedback, iter_idx=iter_idx, state=state)
            # Iter ran cleanly but produced no usable model (gate exhaustion
            # or all-rounds-failed). Skip output absorption + plugin
            # restoration entirely. Not appended to committed_iters because
            # there is no scientific result to commit. Negative feedback, when
            # present, was restored above through its dedicated typed channel.
            print(
                f"[resume] iter {iter_idx:03d}: no_records — skipping "
                f"output absorption, no plugin to restore"
                + ("; restored negative feedback" if raw_feedback is not None else "")
            )
            continue
        output_path = manifest["output_path"]

        # V19 PR 1 §3.6 — replay integrity BEFORE trusting the artifact's
        # content. A recorded hash that no longer matches the bytes on disk
        # STOPS the chain (fail closed); a legacy manifest without any hash
        # is admitted but visibly unverified. S2 / U5 widened the predicate
        # (manifest self-digest; hash removal is a tamper) and moved it to
        # the ONE authority every verifier shares:
        # `core.iteration_manifest.verify_iteration_manifest`.
        if manifest.get(RUN_OUTPUT_DIGEST_KEY) and not os.path.isfile(output_path):
            raise ResumeError(
                f"iter {iter_idx:03d}: manifest points at output_path "
                f"{output_path} but the file does not exist."
            )
        verdict = _verify_manifest_or_stop(
            manifest, iter_idx=iter_idx, manifest_path=manifest_path, output_path=output_path
        )
        artifact_verified = verdict.artifact_verified

        parsed = _validate_run_output(output_path, iter_idx)

        # DS6b — invariant-stamp check BEFORE this iter's plugin is
        # registered, so a scope/policy mismatch mutates nothing.
        if expected_invariants is not None:
            validate_stamped_invariants(
                {
                    "resolved_data_scope": getattr(parsed, "resolved_data_scope", None),
                    "health_gate_enabled": getattr(parsed, "health_gate_enabled", None),
                    "health_config_sha256": getattr(parsed, "health_config_sha256", None),
                    # Step 11 C8 / R-11-9.
                    "task_composition_fingerprint": getattr(
                        parsed, "task_composition_fingerprint", None
                    ),
                    # arXiv U1 (#254) — the arm label travels to the SAME
                    # three-case ingress rule. Without this key here a
                    # labelled chain refused its own iteration-1 output at
                    # restore time (found by the two-iteration pseudo chain,
                    # the F-11-C10-a class: a stamp the writer emits but the
                    # reader never forwards).
                    "experiment_arm": getattr(parsed, "experiment_arm", None),
                },
                expected_invariants,
                # Step 11 C8 (F-11-5) — the run's OWN profile, not TIDMAD's.
                # This was the only task token in a 1,772-line file, while
                # the sibling call site (`model_exploration.py:1857`) had
                # already been composition-aware for a milestone: a composed
                # resume compared its records against TIDMAD's file count.
                # The chain supplies the already-resolved partition count.
                # Older programmatic callers may instead activate an
                # explicit profile binding before invoking resume.
                full_scope=list(
                    range(
                        dataset_partition_count
                        if dataset_partition_count is not None
                        else resolve_dataset_profile().partition_count
                    )
                ),
                source=f"restored iter {iter_idx:03d} run_output {output_path}",
            )

        run_name = _iter_run_name(iter_idx)
        plugin_dir = get_plugin_dir(abs_workspace, run_name)
        plugin_file = os.path.join(plugin_dir, f"{parsed.model_type}.py")

        if os.path.isfile(plugin_file):
            registered = register_model_in_memory(plugin_file)
            if registered is None:
                # The .py is on disk but failed _load_plugin validation —
                # broken plugin contract (missing PLUGIN_MODEL_TYPE etc).
                # Higher tier of corruption than a missing file: warn and
                # continue, so the run can still produce memory_history but
                # the operator is alerted.
                warnings.warn(
                    f"[resume] iter {iter_idx:03d}: plugin file at "
                    f"{plugin_file} failed _load_plugin validation. "
                    f"Continuing with JSON-only history; model class is "
                    f"unavailable for any retraining.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                state.restored_plugins.append(registered)
                print(
                    f"[resume] iter {iter_idx:03d}: restored plugin "
                    f"'{registered}' from {plugin_file}"
                )
        else:
            warnings.warn(
                f"[resume] iter {iter_idx:03d}: plugin file not found at "
                f"{plugin_file}. JSON record is kept (memory_history is "
                f"still reconstructible); model class is unavailable for "
                f"any retraining.",
                UserWarning,
                stacklevel=2,
            )

        state.resolved_source_paths.append(output_path)
        state.committed_iters.append(iter_idx)

        # V8 Domain 1 — accumulate negative feedback as we walk prior iters.
        # The same parsed HyperparamTuningOutput already validated above
        # carries every signal we need; no second disk pass required. The
        # caps below enforce K=10 most-recent retention per channel.
        # See docs/V8_Gap_Report.md Domain 1.
        if parsed.physical_rejections:
            state.accumulated_physical_rejections.extend(parsed.physical_rejections)
        if parsed.gate_exhaustion is not None:
            state.accumulated_gate_exhaustions.append(parsed.gate_exhaustion)
        _append_negative_feedback(state, parsed.gate_exhaustion, parsed.trial_validity_feedback)

        # V19 PR 1 §3.3 — chain-incumbent fold, commit-time validity only.
        # FORMAL: committed-fields fast path (with summary-vs-source
        # validation); a legacy output (field absent) re-derives from
        # persisted verdicts under the iteration's commit-time policy.
        # TRIAL: always re-derived from persisted verdicts (committed
        # trial-best fields only exist from P1-C4 onward).
        # Cross-iteration tie rule: strictly-greater replaces, so the
        # ascending walk makes earliest-iteration-wins automatic.
        gate_ids = _commit_time_gate_ids(parsed, output_path, abs_workspace)
        formal_cand = _formal_candidate_from_committed_fields(parsed, manifest, iter_idx)
        if formal_cand is None and parsed.best_valid_formal_denoising_score is None:
            formal_cand = _candidates_from_persisted_verdicts(parsed, gate_ids, want_trial=False)
        # V20 PR D (D-C4) — scientific authority is an ADDITIONAL conjunct
        # on top of commit-time validity, never a replacement for it. A
        # record that is commit-time valid but non-authoritative (declared
        # diagnostic, observe-only, validity unknown, unreconstructable
        # legacy, or a verdict that disagrees with its own facts) stays
        # fully persisted and readable — it simply never becomes the
        # comparison basis for a later gate.
        if formal_cand is not None and not _formal_candidate_is_authoritative(
            formal_cand, parsed, gate_ids, iter_idx
        ):
            formal_cand = None
        # Step 10 P2a C2, deviation D-P2a-1 — the CHAIN-level fold. Found by
        # the C0 scanner, absent from the frozen §2.1 table, and audited to be
        # the same golden values as `_pick_best` one level below (this
        # candidate's "score" is `best_valid_formal_denoising_score`, or a
        # record's own `denoising_score`). It ranks across ITERATIONS, so its
        # order is reconciled per iteration from that iteration's output stamp.
        _chain_order = _chain_fold_order(parsed)

        if (
            formal_cand is not None
            and _chain_order is not None
            and (
                state.chain_best_valid_formal_score is None
                or _chain_order.is_better(formal_cand["score"], state.chain_best_valid_formal_score)
            )
        ):
            prov = _build_provenance(formal_cand, parsed, iter_idx, artifact_verified, trial=False)
            if prov is not None:
                state.chain_best_valid_formal_score = formal_cand["score"]
                state.chain_best_valid_formal_provenance = prov

        trial_cand = _candidates_from_persisted_verdicts(parsed, gate_ids, want_trial=True)
        if (
            trial_cand is not None
            and _chain_order is not None
            and (
                state.chain_best_trial_score is None
                or _chain_order.is_better(trial_cand["score"], state.chain_best_trial_score)
            )
        ):
            prov = _build_provenance(trial_cand, parsed, iter_idx, artifact_verified, trial=True)
            if prov is not None:
                state.chain_best_trial_score = trial_cand["score"]
                state.chain_best_trial_provenance = prov

    # Apply K-most-recent caps. We collect chronologically and trim from the
    # head so the *latest* signals win — older rejections become stale once
    # the architecture/budget combo evolves past them.
    if len(state.accumulated_physical_rejections) > _MAX_ACCUMULATED_REJECTIONS:
        state.accumulated_physical_rejections = state.accumulated_physical_rejections[
            -_MAX_ACCUMULATED_REJECTIONS:
        ]
    if len(state.accumulated_gate_exhaustions) > _MAX_ACCUMULATED_GATE_EXHAUSTIONS:
        state.accumulated_gate_exhaustions = state.accumulated_gate_exhaustions[
            -_MAX_ACCUMULATED_GATE_EXHAUSTIONS:
        ]
    _trim_negative_feedback(state)

    # Cross-iter knowledge carry-over. Without this, every chain iter's
    # interp node sees only the static seed (empirically: 5 iters × 21
    # entries on the V7 explore workspace before this patch landed). See
    # docs/Consistent_growing_vocab_list.md §1.2 for the bug evidence.
    # Step 09.5a C1 — ONE open + ONE json.load per committed digest for this
    # whole restoration pass. Before, four loaders each re-read every digest
    # (4N reads for N committed iters) and each re-implemented the same
    # missing/corrupt policy. The four projections below still differ in
    # validator, merge rule and failure policy — that is real semantics, and it
    # is preserved; only the I/O was duplicated.
    digest_reads = read_committed_digests(abs_workspace, current_iter, state.committed_iters)

    state.runtime_vocab, state.accumulated_key_findings = project_knowledge(digest_reads)
    if state.runtime_vocab or state.accumulated_key_findings:
        print(
            f"[resume] knowledge carry-over: "
            f"{len(state.runtime_vocab)} vocab entries, "
            f"{len(state.accumulated_key_findings)} accumulated key findings"
        )

    # Commit 6.1.a — Knowledge Restoration. Pull the latest committed iter's
    # model_knowledge_cache so the next subprocess's interp agent sees a
    # populated cache and the Stability Filter (Commit 6.1) can skip the
    # per_model LLM call for stable architectures. Without this, the
    # cache-hit branch at nodes/result_interpretation_agent.py:687-693 is
    # unreachable in chain mode. See Rev 8.3 changelog.
    state.model_knowledge_cache = project_knowledge_cache(digest_reads)
    # V19 PR 3 — typed fingerprint-history carry-over (digest-only, one
    # direction: digest -> typed restore -> workflow input -> interpreter
    # merge -> next digest). Never rebuilt from proposer output or prompts.
    state.collapse_fingerprint_history = project_fingerprint_history(digest_reads)
    # Step 09a C5 — the interpreter's prediction memory rides the SAME
    # canonical path, one line below the fingerprint history it mirrors.
    state.prediction_memory = project_prediction_memory(digest_reads)
    # Step 10 / P5+P6 C1 — the vocab-link confirmation map rides it too. Same
    # digest reads, same latest-wins shape, same fail-closed policy; the only
    # reader of this digest key outside the interpreter.
    state.vocab_link_confirmations = project_vocab_link_confirmations(digest_reads)
    _v2_pool = state.prediction_memory.prediction_outcomes_by_semantics.get(
        PREDICTION_SEMANTICS_SIGNSAFE_V2, {}
    )
    if sum(state.prediction_memory.prediction_outcomes_history.values()) or sum(_v2_pool.values()):
        print(
            f"[resume] prediction-memory carry-over: "
            f"legacy pool n={sum(state.prediction_memory.prediction_outcomes_history.values())}, "
            f"v2 pool n={sum(_v2_pool.values())}"
        )
    if state.collapse_fingerprint_history:
        n_entries = sum(len(v) for v in state.collapse_fingerprint_history.values())
        print(
            f"[resume] fingerprint-history carry-over: {n_entries} "
            f"entr{'y' if n_entries == 1 else 'ies'} across "
            f"{len(state.collapse_fingerprint_history)} model(s)"
        )
    if state.model_knowledge_cache:
        n = len(state.model_knowledge_cache)
        print(
            f"[resume] knowledge-cache carry-over: "
            f"{n} cached model {'summary' if n == 1 else 'summaries'} restored"
        )

    # G1 bridge — proposal carry-over restores `proposed_vocab_candidates`
    # across the chain-subprocess boundary. Without this, the workflow's
    # init at workflows/model_exploration.py:784 unconditionally resets
    # the candidate channel to None at every iter, so a candidate proposed
    # in iter N never accumulates `seen_in_runs` evidence at iter N+1.
    # See docs/Consistent_growing_vocab_list.md §10.
    state.previous_proposal_data = load_latest_proposal(
        abs_workspace,
        state.committed_iters,
    )
    if state.previous_proposal_data is not None:
        n_candidates = len(state.previous_proposal_data.get("proposed_vocab_candidates") or [])
        print(
            f"[resume] proposal carry-over: latest proposal restored "
            f"({n_candidates} proposed_vocab_candidates)"
        )
    if (
        state.accumulated_physical_rejections
        or state.accumulated_gate_exhaustions
        or state.accumulated_negative_feedback
    ):
        print(
            f"[resume] negative-feedback carry-over: "
            f"{len(state.accumulated_physical_rejections)} physical rejection(s), "
            f"{len(state.accumulated_gate_exhaustions)} gate-exhaustion summar"
            f"{'y' if len(state.accumulated_gate_exhaustions) == 1 else 'ies'}, "
            f"{sum(item[1] is not None for item in state.accumulated_negative_feedback)} "
            f"trial-validity summary(ies)"
        )

    # V19 PR 1 — incumbent carry-over audit lines (design §3.3).
    if state.chain_best_valid_formal_provenance is not None:
        p = state.chain_best_valid_formal_provenance
        print(
            f"[resume] incumbent carry-over: score={p['score']:.4f} "
            f"iter={p['iter_idx']:03d} "
            f"round={p['round_index'] if p['round_index'] is not None else 'none'} "
            f"exp_id={p['exp_id']} basis={p['validity_basis']} "
            f"verified={str(p['artifact_verified']).lower()}"
        )
    else:
        print("[resume] incumbent carry-over: none")
    if state.chain_best_trial_provenance is not None:
        p = state.chain_best_trial_provenance
        print(
            f"[resume] trial-incumbent carry-over: score={p['score']:.4f} "
            f"iter={p['iter_idx']:03d} "
            f"round={p['round_index'] if p['round_index'] is not None else 'none'} "
            f"exp_id={p['exp_id']} basis={p['validity_basis']} "
            f"verified={str(p['artifact_verified']).lower()}"
        )
    else:
        print("[resume] trial-incumbent carry-over: none")

    return state


# ---------------------------------------------------------------------------
# Workspace layout guard (Phase 6.8 §3.9)
# ---------------------------------------------------------------------------


def validate_workspace_layout(workspace: str) -> None:
    """Detect legacy workspace layout and refuse to start.

    The chain layout uses ``{workspace}/iter_NNN/``. The legacy in-process
    layout uses ``{workspace}/{run_name}/iteration_NNN/``. If a workspace
    has legacy artifacts, writing chain artifacts alongside them would
    silently produce an incoherent workspace.

    Raises:
        ResumeError: when legacy layout patterns are detected.
    """
    import glob as _glob

    if not os.path.isdir(workspace):
        return  # nothing to guard

    # Pattern 1: {workspace}/{non-iter}/iteration_001/  (legacy run_name subtree).
    # Chain layout also has iteration_001/ but under iter_NNN/ — exclude those.
    matches = _glob.glob(os.path.join(workspace, "*", "iteration_001", ""))
    legacy_matches = [
        m
        for m in matches
        if not re.match(r"iter_\d{3}$", os.path.basename(os.path.dirname(os.path.dirname(m))))
    ]
    if legacy_matches:
        _raise_legacy(workspace, legacy_matches[0])

    # Pattern 2: workflow_*.json (workflow summary from in-process runner)
    matches = _glob.glob(os.path.join(workspace, "workflow_*.json"))
    if matches:
        _raise_legacy(workspace, matches[0])

    # Pattern 3: memory_trace.jsonl exists AND no iter_001/ (ambiguous legacy)
    trace = os.path.join(workspace, "memory_trace.jsonl")
    if os.path.exists(trace) and not os.path.isdir(os.path.join(workspace, "iter_001")):
        _raise_legacy(workspace, trace)


def _raise_legacy(workspace: str, matched: str) -> None:
    raise ResumeError(
        f"Legacy workspace layout detected at {workspace}.\n"
        f"  Found: {matched}\n\n"
        f"This workspace was created by the in-process runner (v5/v6 era).\n"
        f"The chain runner uses a different layout ({{workspace}}/iter_NNN/).\n\n"
        f"To proceed:\n"
        f"  (a) Use a new --workspace path for the chain run.\n"
        f"  (b) To resume from legacy results, use the migration tool:\n"
        f"      python scripts/migrate_workspace.py --from {workspace} --to <new>\n"
        f"      (migration tool planned — not yet implemented)"
    )
