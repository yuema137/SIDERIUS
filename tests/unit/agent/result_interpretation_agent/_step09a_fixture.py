"""The FIXED interpretation input behind the Step-09a differential oracle.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §4.1 (C1a).

Why this module exists
----------------------
Step 09a extracts, then re-owns, the interpreter's deterministic evidence /
ordering / prediction logic. "Behaviour-preserving" is only a claim unless
there is a MEASURED baseline, so C1a pins one FIXED input's full deterministic
digest and its exact LLM-call sequence from the UNMODIFIED tree, before any
production line moves. Every later commit's parity claim is a DECLARED diff
against that baseline (parent §16: differential ownership, never "same full
digest").

What the fixture deliberately exercises
---------------------------------------
Three model types, so every branch 09a will touch is on the path:

``wavenet``
    A new tuning output (built through the REAL
    ``tuning_output_to_model_run_summary``) PLUS a modern ``CacheEntry``-shaped
    cache entry. Active + new rounds ⇒ a fresh ``interpretation.per_model``
    call followed by the LLM-powered consolidator (two
    ``cache_consolidator.list_merge`` calls). Carries the run's only
    authoritative formal record, a score table, a file vector, a gated
    collapse round and a skipped round.
``bidirectional_gated_tcn``
    A new tuning output with NO cache entry ⇒ cache-miss build, and it is the
    previous proposal's model, so it drives prediction evaluation and
    discovery generation. Its formal record carries NO scientific authority,
    so the aggregation scope has both an included and an excluded member.
``punet``
    Cache-only, legacy-flat shape, outside the active set ⇒ the Stability
    Filter skip path (``emit_marker``), the cache ``_stats`` reconstruction
    loop, the cached score-table re-validation and ``compress_model_summary``.

Determinism
-----------
Nothing in the digest may vary between runs:

* model descriptions never reach disk — the two new summaries carry an inline
  ``model_description`` (assigned exactly as production does at
  ``workflows/model_exploration.py:2720``) and the cached model carries one in
  its ``_stats``;
* candidate health is decided by the DS5 ``health_gate_enabled=False`` waiver
  rather than by the ambient HealthGate roster, so record validity does not
  depend on ``configs/health_checks.yaml``;
* no vocabulary entry reaches the promotion threshold, so the dedup call site
  never fires and the call sequence has a fixed length;
* the ONLY non-deterministic string anywhere on the path is the tmp workspace,
  which is interpolated VERBATIM into the synthesis prompt's compressed-model
  hint (``result_interpretation_agent.py:641-651``). It is normalised at the
  RECORDER (:class:`RecordingStubBridge`), never in production.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.schemas.cache_entry import CacheEntry, ConsolidatedFinding, ConsolidatedNarrative
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.proposal import VocabEntry
from agent.schemas.score_table import AggregateScalars, PerFileRow, ScoreComparisonTable
from core.scientific_authority import ScientificAuthority
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import (
    reconcile_metric_spec,
    tuning_output_to_model_run_summary,
)
from tests.helpers.metric_fixtures import shipped_spec

# The iteration this fixture represents. Fixed: it is stamped into the
# consolidator's evidence_iters and the archive directory name.
ITERATION = 3

WAVENET = "wavenet"
BGT = "bidirectional_gated_tcn"
PUNET = "punet"

# The workspace placeholder the recorder substitutes before hashing.
WORKSPACE_TOKEN = "<STEP09A_WORKSPACE>"


# ---------------------------------------------------------------------------
# Canned LLM responses (one per call label)
# ---------------------------------------------------------------------------

PER_MODEL_RESPONSE: dict[str, Any] = {
    "key_findings": [
        "focal gamma=2 beats ce by ~0.05 at equal depth",
        "depth beyond 3 yields diminishing returns",
    ],
    "bottlenecks": [
        "capacity ceiling at depth=3 — the score plateaus",
    ],
    "best_config_analysis": "Depth 4 with focal loss gamma=2 was the best configuration.",
    "score_trend": "Scores improved early, then plateaued after depth=3.",
}

SYNTHESIS_RESPONSE: dict[str, Any] = {
    "key_findings": [
        "wavenet leads the iteration on the formal round",
        "the gated TCN trails but is the freshest architecture",
    ],
    "bottlenecks": [
        "every architecture plateaus at a similar training budget",
    ],
    "take_home_message": "The current family has saturated; change the receptive-field mechanism.",
}

LIST_MERGE_RESPONSE: dict[str, Any] = {
    "survivors": [
        {"statement": "consolidated observation", "evidence_iters": [2], "strength": "moderate"},
    ],
    "archived": [],
}


def canned_response(system_prompt: str) -> dict[str, Any]:
    """Route a canned response by system prompt, like the production dispatch.

    Mirrors the routing every existing interpreter unit test uses
    (``test_dispatcher_wiring.py:76-82``) so the fixture does not invent a
    second convention.
    """
    if "ONE model architecture" in system_prompt:
        return PER_MODEL_RESPONSE
    if "semantic merge engine" in system_prompt:
        return LIST_MERGE_RESPONSE
    return SYNTHESIS_RESPONSE


class RecordingStubBridge:
    """A stub ``LLMBridge`` that records the boundary and answers canned JSON.

    Records, per ``generate`` call, the label and the sha256 of the system and
    user prompts. A hash rather than the text keeps the golden small while
    still failing on ANY render change — which is exactly the property C1b's
    "same LLMBridge kwargs for a fixed input" claim needs.

    ``workspace`` is replaced by :data:`WORKSPACE_TOKEN` before hashing: the
    tmp path is the one genuinely run-varying string on the path, and
    normalising it at the fixture is the design's prescribed remedy (§4.1
    "Failure and edge cases") — production is never touched.
    """

    def __init__(self, workspace: str) -> None:
        self._workspace = workspace
        self.calls: list[dict[str, str]] = []
        self.markers: list[dict[str, Any]] = []

    def _digest(self, text: str) -> str:
        normalised = text.replace(self._workspace, WORKSPACE_TOKEN)
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        label: str = "unlabeled",
        components: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "label": label,
                "system_sha256": self._digest(system_prompt),
                "user_sha256": self._digest(user_prompt),
            }
        )
        return canned_response(system_prompt)

    def emit_marker(self, *, label: str, extra: dict[str, Any] | None = None) -> None:
        self.markers.append({"label": label, "extra": dict(extra or {})})


# ---------------------------------------------------------------------------
# Record / output builders
# ---------------------------------------------------------------------------


def _score_table(file_scores: list[float | None]) -> ScoreComparisonTable:
    """A table with one row per declared file, from a per-file model column."""
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=0.1,
            ground_truth=100.0,
            model=v,
            gain_vs_raw=(v - 0.1) if v is not None else None,
            headroom_vs_gt=(100.0 - v) if v is not None else None,
        )
        for i, v in enumerate(file_scores)
    ]
    present = [v for v in file_scores if v is not None]
    model_scalar = (sum(present) / len(present)) if present else 0.0
    return ScoreComparisonTable(
        rows=rows,
        aggregate=AggregateScalars(
            raw_baseline_scalar=0.1,
            ground_truth_scalar=100.0,
            model_scalar=model_scalar,
            percent_of_ceiling_log=model_scalar / 100.0,
            num_sampled_files=len(present) or 1,
        ),
        s_max_global=1.0,
        reference_source="step09a_fixture",
        rendered_markdown="| file | raw | gt | model |\n(step09a fixture table)",
    )


def _num_declared_files() -> int:
    from execute_tools.dataset_config import resolve_dataset_profile

    return resolve_dataset_profile().dataset.num_files


def _file_vector(base: float) -> list[float | None]:
    """A deterministic per-file vector of the declared length."""
    n = _num_declared_files()
    return [round(base + 0.01 * i, 4) for i in range(n)]


def _gate_result() -> dict[str, Any]:
    """One persisted gate result in the real V17 shape.

    Same shape as ``test_round_health_summary.py:22-40`` — the fixture reuses
    the vintage the P3-CA audit found on disk rather than inventing one.
    """
    return {
        "gate_name": "output_diversity_blocking",
        "execution_status": "failed",
        "check_passed": False,
        "would_invalidate_under_production_policy": True,
        "resolved_action": "invalidate_round",
        "failure_reason": "output_diversity_blocking: n_unique_int8_values=1.0",
        "threshold": {
            "metric": "n_unique_int8_values",
            "operator": ">",
            "value": 25,
            "unit": "count",
        },
        "aggregation": {},
        "metrics": {"aggregate_statistics": {"minimum": 1.0, "maximum": 1.0, "mean": 1.0}},
        "gate_runtime_seconds": 0.4,
    }


def _authoritative_verdict() -> dict[str, Any]:
    """The verdict the tuner stamps on an authoritative formal record.

    Built through ``ScientificAuthority.from_context`` — the same constructor
    the tuner uses — so ``resolve_record_authority`` re-derives it and admits
    the record instead of excluding it as ``unreconstructable_legacy``.
    """
    return ScientificAuthority.from_context(
        healthgate_mode="blocking",
        declared_result_authority="scientific",
        formal_validity="valid",
    ).model_dump(mode="json")


def _memory(conclusion: str) -> dict[str, Any]:
    return {
        "expert_advice_followed": "yes",
        "hypothesis": "A wider receptive field improves the low-frequency files.",
        "conclusion": conclusion,
    }


def _record(exp_id: str, model_type: str, **overrides: Any) -> ExperimentRecord:
    """A dict-validated record — ``model_fields_set`` mirrors authored keys.

    Dict validation (not kwargs) is deliberate: both production paths write
    records this way, and ``classify_round_provenance`` reads field PRESENCE.
    """
    base: dict[str, Any] = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": "2026-08-19T00:00:00Z",
        "params": {"model_config": {"depth": 4}, "train_config": {"lr": 0.0005}},
        # DS5 waiver: candidate validity is decided by this stamp rather than
        # by the ambient blocking-gate roster, so the fixture's VALID/INVALID
        # split cannot drift with configs/health_checks.yaml.
        "health_gate_enabled": False,
    }
    return ExperimentRecord.model_validate({**base, **overrides})


def _wavenet_output() -> HyperparamTuningOutput:
    """Four rounds: two trials (one collapsed under a gate), a formal, a skip."""
    formal_vector = _file_vector(-2.10)
    formal_table = _score_table([float(v) if v is not None else None for v in formal_vector])
    records = [
        _record(
            "wavenet_r1",
            WAVENET,
            denoising_score=-2.60,
            is_trial=True,
            model_params=1_200_000,
            trial_portion=0.1,
            training_psd_segments=4096,
            eval_psd_segments=512,
            timing={"train_time_s": 420.0, "inference_time_s": 80.0, "scoring_time_s": 12.0},
            memory=_memory("Baseline trial: focal gamma=2 at depth 3."),
            metric_result={
                "metric_id": "tidmad_denoising_score",
                "direction": "higher",
                "scalar": -2.60,
                "per_sample": None,
                "references_used": ["raw_baseline", "ground_truth"],
            },
        ),
        _record(
            "wavenet_r2",
            WAVENET,
            status="failed_mode_collapse",
            denoising_score=-3.10,
            is_trial=True,
            gate_action="invalidate_round",
            failure_reason="[output_diversity_blocking] n_unique_int8_values=1.0",
            health_gate_results=[_gate_result()],
            memory=_memory("Collapsed: the decoder emitted a constant."),
        ),
        _record(
            "wavenet_r3",
            WAVENET,
            denoising_score=-2.00,
            is_trial=False,
            model_params=1_450_000,
            trial_portion=1.0,
            training_psd_segments=40960,
            eval_psd_segments=5120,
            file_vector=formal_vector,
            score_table=formal_table.model_dump(),
            scientific_authority=_authoritative_verdict(),
            timing={"train_time_s": 900.0, "inference_time_s": 210.0, "scoring_time_s": 30.0},
            memory=_memory("Formal round: depth 4 held the gain at full scope."),
            metric_result={
                "metric_id": "tidmad_denoising_score",
                "direction": "higher",
                "scalar": -2.00,
                "per_sample": formal_vector,
                "references_used": ["raw_baseline", "ground_truth"],
            },
        ),
        _record(
            "wavenet_r4",
            WAVENET,
            status="skipped_oom_risk",
            denoising_score=None,
            is_trial=False,
            failure_reason="Projected activation memory exceeded the device budget.",
        ),
    ]
    return HyperparamTuningOutput(
        run_name="step09a_wavenet",
        model_type=WAVENET,
        file_index=6,
        status="completed",
        completed_rounds=4,
        total_attempts=4,
        started_at="2026-08-19T00:00:00Z",
        finished_at="2026-08-19T02:00:00Z",
        best_denoising_score=-2.00,
        best_config={
            "model_config": {"depth": 4},
            "train_config": {"lr": 0.0005},
            "loss_config": {"loss_type": "focal", "gamma": 2.0},
        },
        best_score_table=formal_table,
        all_records=records,
        # Step 09a C2 — the tuner stamps its already-resolved spec on every
        # output (`finalize_run_output`); the fixture reproduces that, so the
        # interpreter receives a transported value rather than deriving one.
        metric_spec=shipped_spec(),
    )


def _bgt_output() -> HyperparamTuningOutput:
    """Three successful rounds; the formal one carries NO authority verdict."""
    formal_vector = _file_vector(-2.53)
    formal_table = _score_table([float(v) if v is not None else None for v in formal_vector])
    records = [
        _record(
            "bgt_r1",
            BGT,
            denoising_score=-2.90,
            is_trial=True,
            model_params=830_000,
            trial_portion=0.1,
            memory=_memory("First gated-TCN trial."),
            metric_result={
                "metric_id": "tidmad_denoising_score",
                "direction": "higher",
                "scalar": -2.90,
                "per_sample": None,
                "references_used": ["raw_baseline", "ground_truth"],
            },
        ),
        _record(
            "bgt_r2",
            BGT,
            denoising_score=-2.55,
            is_trial=True,
            model_params=910_000,
            trial_portion=0.1,
            memory=_memory("Widening the gate improved the mid-band files."),
        ),
        _record(
            "bgt_r3",
            BGT,
            denoising_score=-2.43,
            is_trial=False,
            model_params=980_000,
            trial_portion=1.0,
            training_psd_segments=38000,
            eval_psd_segments=4800,
            file_vector=formal_vector,
            score_table=formal_table.model_dump(),
            # Deliberately no scientific_authority: this model is the EXCLUDED
            # half of the aggregation scope.
            timing={"train_time_s": 1200.0, "inference_time_s": 700.0, "scoring_time_s": 40.0},
            memory=_memory("Formal round: the gain held but the cost is high."),
            metric_result={
                "metric_id": "tidmad_denoising_score",
                "direction": "higher",
                "scalar": -2.43,
                "per_sample": formal_vector,
                "references_used": ["raw_baseline", "ground_truth"],
            },
        ),
    ]
    return HyperparamTuningOutput(
        run_name="step09a_bgt",
        model_type=BGT,
        file_index=6,
        status="completed",
        completed_rounds=3,
        total_attempts=3,
        started_at="2026-08-19T02:00:00Z",
        finished_at="2026-08-19T03:30:00Z",
        best_denoising_score=-2.43,
        best_config={
            "model_config": {"gate_width": 5},
            "train_config": {"lr": 0.0005},
            "loss_config": {"loss_type": "focal", "gamma": 2.0},
        },
        best_score_table=formal_table,
        all_records=records,
        # Step 09a C2 — the tuner stamps its already-resolved spec on every
        # output (`finalize_run_output`); the fixture reproduces that, so the
        # interpreter receives a transported value rather than deriving one.
        metric_spec=shipped_spec(),
    )


def build_tuning_outputs() -> list[HyperparamTuningOutput]:
    """The two tuning outputs this fixture interprets, in workflow order."""
    return [_wavenet_output(), _bgt_output()]


def build_summaries() -> list[ModelRunSummary]:
    """Summaries through the REAL builder, then the production description hop.

    ``tuning_output_to_model_run_summary`` never sets ``model_description``;
    the workflow assigns it afterwards from the proposal
    (``workflows/model_exploration.py:2720``). The fixture does the same, which
    is what keeps ``get_model_description`` — a filesystem read — off the path.
    """
    descriptions = {
        WAVENET: "wavenet: dilated causal convolution stack (step09a fixture).",
        BGT: "bidirectional_gated_tcn: gated temporal conv, both directions (step09a fixture).",
    }
    # Step 09a C3 — the builder RANKS records, so it takes the run's order as a
    # required keyword. TIDMAD is `higher`, so every selection is unchanged.
    order = MetricOrder(shipped_spec())
    summaries = [tuning_output_to_model_run_summary(o, order=order) for o in build_tuning_outputs()]
    for summary in summaries:
        summary.model_description = descriptions[summary.model_type]
    return summaries


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _wavenet_cache_entry() -> dict[str, Any]:
    """Modern ``CacheEntry``-shaped entry, stored the way ``run()`` stores it.

    ``run()`` persists a consolidated entry with its ``stats`` field renamed to
    the legacy ``_stats`` key (``result_interpretation_agent.py:1259``), so the
    fixture reproduces that exact on-disk shape — which is also what makes the
    modern branch of the consolidator's prior-entry validation the one taken.
    """
    entry = CacheEntry(
        model_type=WAVENET,
        key_findings=[
            ConsolidatedFinding(
                statement="focal gamma=2 outperforms ce at equal depth",
                evidence_iters=[1, 2],
                strength="strong",
            ),
            ConsolidatedFinding(
                statement="depth 4 is the current capacity sweet spot",
                evidence_iters=[2],
                strength="moderate",
            ),
        ],
        bottlenecks=[
            ConsolidatedFinding(
                statement="low-frequency files dominate the residual error",
                evidence_iters=[2],
                strength="moderate",
            ),
        ],
        best_config_analysis=ConsolidatedNarrative(latest="Depth 4 / focal gamma=2 (iter 2)."),
        score_trend=ConsolidatedNarrative(latest="Improving, decelerating."),
        stats={
            "best_denoising_score": -2.20,
            "best_valid_denoising_score": -2.20,
            "best_raw_health_validity": "valid",
            "worst_denoising_score": -3.05,
            "best_file_vector": None,
            "best_score_table": None,
            "best_model_params": 1_180_000,
            "completed_rounds": 3,
            "best_config": {"model_config": {"depth": 4}, "train_config": {"lr": 0.0005}},
            "best_valid_config": {"model_config": {"depth": 4}, "train_config": {"lr": 0.0005}},
            "formal_score": -2.20,
            "model_description": "wavenet: dilated causal convolution stack (step09a fixture).",
            "round_health_counts": {"valid": 3, "invalid": 0, "unknown": 0},
            "collapse_fingerprints": [],
        },
    )
    dumped = entry.model_dump()
    dumped["_stats"] = dumped.pop("stats")
    return dumped


def _punet_cache_entry() -> dict[str, Any]:
    """Legacy flat-dict entry — the pre-6.3 shape, still resumable.

    Cache-only and outside the active set, so it exercises the ``_stats``
    reconstruction loop, the cached score-table re-validation, the Stability
    Filter skip marker and ``compress_model_summary``.
    """
    cached_vector = _file_vector(-2.95)
    return {
        "key_findings": [
            "punet saturates well before the wavenet family",
            "shallow encoders lose the high-frequency band",
        ],
        "bottlenecks": ["encoder depth is the binding constraint"],
        "best_config_analysis": "Best at depth 3; deeper variants diverged.",
        "score_trend": "Flat after iteration 1.",
        "_stats": {
            "best_denoising_score": -2.90,
            "best_valid_denoising_score": -2.90,
            "best_raw_health_validity": "valid",
            "worst_denoising_score": -3.40,
            "best_file_vector": cached_vector,
            "best_score_table": _score_table(
                [float(v) if v is not None else None for v in cached_vector]
            ).model_dump(),
            "best_model_params": 640_000,
            "completed_rounds": 2,
            "best_config": {"model_config": {"depth": 3}, "train_config": {"lr": 0.0005}},
            "formal_score": -2.90,
            "model_description": "punet: U-net style encoder/decoder (step09a fixture).",
        },
    }


def build_cache() -> dict[str, Any]:
    return {WAVENET: _wavenet_cache_entry(), PUNET: _punet_cache_entry()}


# ---------------------------------------------------------------------------
# Carried memory + the previous proposal
# ---------------------------------------------------------------------------


def build_runtime_vocab() -> list[VocabEntry]:
    """Two canonicals and one single-run candidate — all below promotion.

    ``promote_candidates`` promotes at ``min_runs=2`` (its default, and what
    ``run()`` uses), so every candidate here stays at one run and the dedup
    call site never fires. That keeps the recorded call sequence a fixed
    length, which is the property the LLM-call golden pins.
    """
    return [
        VocabEntry(
            name="dilated_causal_conv",
            kind="feature",
            description="Causal convolution with exponentially growing dilation.",
            tier="canonical",
            related_to=["receptive_field"],
            seen_in_runs=["wavenet"],
        ),
        VocabEntry(
            name="receptive_field",
            kind="capability",
            description="How far back in time one output sample can see.",
            tier="canonical",
            seen_in_runs=["wavenet"],
        ),
        VocabEntry(
            name="bidirectional_gating",
            kind="feature",
            description="Gated fusion of forward and backward context.",
            tier="candidate",
            proposed_by_run=BGT,
            seen_in_runs=[BGT],
        ),
    ]


def build_previous_proposal() -> dict[str, Any]:
    """The proposal whose prediction this iteration evaluates.

    Chosen so v1 and v2 prediction semantics AGREE on this fixture: the
    prediction is computable and CONFIRMED (actual -2.43 beats the -2.55 SOTA
    at proposal time), and the discovery-band comparison lands outside the
    relative band under BOTH the current sign-degenerate rule and the sign-safe
    replacement (the strictest SOTA is wavenet's -2.00, and 0.43 exceeds
    0.05 * 2.00 either way). C4's declared delta is therefore the version
    PARTITION alone, not a changed outcome.
    """
    return {
        "model_name": BGT,
        "falsifiable_prediction": {
            "metric": "denoising_score",
            "current_value": -2.55,
            "predicted_value": -2.40,
        },
        "inherited_components": [
            {"component": "dilated_causal_conv", "source_run": "wavenet"},
        ],
        "proposed_vocab_links": [
            {"feature": "bidirectional_gating", "capability": "receptive_field"},
        ],
        "proposed_vocab_candidates": [
            {
                "name": "gated_residual_fusion",
                "kind": "feature",
                "description": "Residual path fused through a learned gate.",
            }
        ],
    }


def build_input(workspace: str) -> InterpretationInput:
    """The one FIXED input the oracle pins.

    ``active_model_top_k=1`` with ``active_model_last_n=2`` makes the active
    set exactly ``{wavenet, bidirectional_gated_tcn}``: wavenet is the
    highest-scoring cached model, both new summaries arrive via Last-N, and
    punet is left out — which is what puts the skip / compression path on the
    recorded sequence.
    """
    return InterpretationInput(
        summaries=build_summaries(),
        model_knowledge_cache=build_cache(),
        # Reconciled from the outputs exactly as the workflow does — the fixed
        # input is score-bearing, so the contract REQUIRES it (Step 09a C2).
        metric_spec=reconcile_metric_spec(build_tuning_outputs()),
        task_description="Denoise SQUID magnetometer time series.",
        # Step 09b C2 — production-faithful: the workflow supplies the task
        # blocks through the ONE bounded Regime-A adapter, so the oracle's
        # fixed input does too (declared oracle delta: the system-prompt
        # digests moved when the science changed owner).
        task_blocks=load_interpretation_task_blocks(),
        runtime_vocab=build_runtime_vocab(),
        previous_proposal=build_previous_proposal(),
        cumulative_information_gain=0.3,
        prediction_outcomes_history={"confirmed": 1, "partial": 0, "refuted": 1},
        vocab_link_confirmations={"bidirectional_gating:receptive_field": ["seed_run"]},
        enable_structured_health_feedback=False,
        iteration=ITERATION,
        active_model_top_k=1,
        active_model_last_n=2,
        active_model_score_delta=0.05,
        storage={
            "backend": "local",
            "local": {"workspace": workspace, "run_name": "step09a"},
        },
    )
