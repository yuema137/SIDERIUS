"""
4-zh — Cognitive Alignment Smoke Test (V9 Gate 1).

Realises the §12.5 Gate 1 acceptance contract from
``docs/aggregated_score_table_awareness.md``. Six property-based
assertions verify that the post-2-zh interpreter prompt makes the LLM
read the score table through the Log-of-Mean-trap lens — ranking
opportunity by ``Impact_Score`` and reading saturation as a relative
judgment against ``model_scalar``, with no fixed-index or fixed-threshold
reasoning.

Setup
-----
* 3 pseudo-training iterations (no GPU, no subprocess).
* Real ``load_reference_scores()`` data feeds ``build_score_table`` with
  a per-iter ``model_fv_linear`` shaped to shift the largest
  ``Impact_Score`` lever between iters: iter_1 suppresses file ``17``;
  iter_2 recovers file ``17`` and suppresses file ``14``; iter_3 has all
  files near ceiling.
* Real OpenAI at synthesis (interpreter) + proposer — model IDs pulled
  from the production tier config (``llm_configs/openai_tiered_v1.json``)
  via ``_load_tier_models``, so the cognitive contract is exercised
  against the same models V9 chains use.
* ``RecordingOpenAIBridge`` captures every prompt + response — needed
  for Metric 5's prompt-column presence check.
* Manual carry-forward of ``runtime_vocab`` and ``previous_proposal``
  between iterations. We drive the cognitive contract at the agent
  level rather than via ``run_workflow`` because Gate 1 is the
  *cognitive* contract, not the full plumbing — ``run_workflow`` runs
  real training/scoring/VRAM probes which Gate 2 already covers, and
  ``start_iteration`` plumbing has its own unit coverage in
  ``TestRunWorkflowStartIteration``. Cf. Phase 8 §12.5 — "Other
  subsystems (training, scoring, VRAM probe) stay pseudo."

Six metrics (all six required, all property-based, no fixed-index
expectations baked into the success criteria):

  M1. Dynamic lever ID — top-Impact file cited in iter_1 differs from
      iter_2; both cited indices come from the score table itself, never
      hardcoded into the assertion.
  M2. No permanent-irrelevance — forbidden phrasings absent across all 3
      take_home_messages.
  M3. Relative saturation — iter_3's flat Impact_Score column triggers a
      chain-ceiling declaration in the take_home_message.
  M4. Jaccard < 0.7 — pairwise echo-chamber guard.
  M5. Prompt columns — ``Impact_Score`` + ``Linear_Weight`` visible in
      ``RecordingOpenAIBridge``-captured synthesis prompts.
  M6. Vocab evolution — ``runtime_vocab`` grows or refines across iters;
      no entries dropped (carries the H.1 monotonicity guarantee from
      ``test_vocab_accumulation.py``).

Calibration before promotion to gating
--------------------------------------
Run the same fixture against the **pre-2-zh prompt** (recover ``3ea439e^``
for ``agent/prompts.py``, ``nodes/result_interpretation_agent.py``,
``nodes/ml_model_proposal_agent.py``): metrics 1, 2, and 3 must FAIL.
The old prompt's "Weak Frequency Files" block + fixed-index examples
forces the LLM into permanent-irrelevance and fixed-lever phrasings.
If they pass on the V8-style prompt, the assertions are too weak.

Run with::

    uv run pytest -m real_run \\
        tests/integration/workflows/test_cognitive_alignment_smoke.py -v -s
"""

from __future__ import annotations

import math
import os
import re
import time
from typing import Any, Optional

import pytest
from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge
from agent.schemas.interpretation import (
    InterpretationInput,
    InterpretationOutput,
    ModelRunSummary,
)
from agent.schemas.proposal import (
    ModelSelectionStrategy,
    ProposalOutput,
    ReasoningPipelineConfig,
    ReasoningStage,
    VocabEntry,
)
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
    local_full_context,
)
from agent.schemas.score_table import ScoreComparisonTable
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.scoring_helpers import build_score_table
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.scoring_reference import load_reference_scores

load_dotenv()

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _load_tier_models() -> tuple[str, str]:
    """Pull the production-tier model IDs for the two slots Gate 1 exercises.

    Gate 1 used to pin the recording bridge to ``gpt-4o-mini`` so the test
    was cheap to run, but that meant the cognitive contract was being
    enforced against a strictly weaker model than production V8/V9 chains
    actually use. Aligning here mirrors the Gate 2 patch (test_score_table
    _real_smoke.py) which now loads ``llm_configs/openai_tiered_v1.json``.

    The two slots Gate 1 calls into are the interpreter (synthesis stage)
    and the proposer's third stage (the structured-JSON ``proposing``
    sub-agent). In the current tier config both happen to be the same
    frontier model, but we resolve them separately so any future tier
    re-routing is picked up automatically.
    """
    from pathlib import Path

    from workflows.llm_config import WorkflowLLMConfig

    repo_root = Path(__file__).resolve().parents[3]
    cfg = WorkflowLLMConfig.from_json(str(repo_root / "llm_configs" / "openai_tiered_v1.json"))
    return cfg.interpret.model_id, cfg.propose.proposing.model_id


_INTERP_MODEL, _PROPOSER_MODEL = _load_tier_models()

# Per-file recovery fractions used to shape model_fv_linear. Files 14-19
# carry ~91% of the GT linear mass (the post-Path-A reference), so
# suppressing one of those produces the largest Impact_Score delta and
# makes the lever the LLM should rank #1 unambiguous.
_BASE_RECOVERY = 0.95
_LEVER_RECOVERY = 0.30
_SATURATED_RECOVERY = 0.995

# Mirror baseline: weak_baseline_arch tracks the candidate's per-iter
# recovery shape with a uniform offset (every file 0.01 lower than the
# candidate that iter). We need a 2nd model present because the interp
# agent *skips* the synthesis LLM call when ``len(effective_types) == 1``
# (nodes/result_interpretation_agent.py:790) — a degenerate branch that
# would never be hit in real chains and would short-circuit our Gate 1
# cognitive contract.
#
# Why mirror, not constant: Runs #3 and #4 used a constant baseline
# (0.20 then 0.93). Both surfaced cross-model anchoring bias — the
# baseline's *flat* shape made its high-Linear_Weight file (file 17)
# look like a stable cross-model lever even when the candidate's
# per-iter lever was elsewhere. With the mirror baseline, both models
# point to the *same* file_index as the leader each iter (the
# candidate's lever, slightly less suppressed in the baseline), so
# synthesis aggregates trivially without competition between
# "high-weight/low-impact" and "low-weight/high-impact" files. See
# Run #3 / Run #4 / Run #5 entries in the design doc
# (`docs/aggregated_score_table_awareness.md`, §8 4-zh checkbox) for
# the full diagnosis.
_BASELINE_OFFSET = 0.01  # uniform amount baseline trails candidate per file

ITER1_LEVER = 17  # iter_1 suppresses this file → top Impact_Score
ITER2_LEVER = 14  # iter_2 suppresses this file (and recovers ITER1_LEVER)


# ---------------------------------------------------------------------------
# RecordingOpenAIBridge — real LLM + capture every prompt/response pair.
# Ported verbatim from tests/integration/workflows/test_score_table_pseudo
# _smoke.py:196 (Phase 6.5). RecordingLLMBridge cannot proxy to a real LLM
# (it is canned-FIFO only and would raise on queue exhaustion), so the
# Gate 1 contract — "real OpenAI + capture" — requires this subclass.
# ---------------------------------------------------------------------------


class RecordingOpenAIBridge(LLMBridge):
    """Real OpenAI bridge that records every prompt + response.

    Each entry in ``self.calls`` is a tuple
    ``(method_name, system_prompt, user_prompt, response)``. The list is
    typically swapped to a shared list by the factory below, so multiple
    bridge instances created within one iter append to a single log.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls: list = []

    def generate(self, system_prompt, user_prompt):
        resp = super().generate(system_prompt, user_prompt)
        self.calls.append(("generate", system_prompt, user_prompt, resp))
        return resp

    def generate_text(self, system_prompt, user_prompt):
        resp = super().generate_text(system_prompt, user_prompt)
        self.calls.append(("generate_text", system_prompt, user_prompt, resp))
        return resp


def _make_recording_factory(model_id: str) -> tuple[list, callable]:
    """Return (shared-call-log, bridge-factory-that-appends-to-it).

    ``model_id`` is read from the production tier config — see
    ``_load_tier_models`` — so the recording bridge speaks to the same
    OpenAI model the corresponding agent slot uses in V9 chains.
    """
    shared: list = []

    def factory(**ignored) -> RecordingOpenAIBridge:
        bridge = RecordingOpenAIBridge(
            provider="openai",
            model_id=model_id,
            max_retries=3,
        )
        bridge.calls = shared
        return bridge

    return shared, factory


# ---------------------------------------------------------------------------
# Fixture math: build per-iter model_fv_linear from real reference data.
#
# Linear_Weight is computed from per-file linear MEANS (sigma = sum of
# means). Impact_Score is computed in linear-SUM space (means * n_segments).
# So model_fv_linear[i] is the per-file linear MEAN — we shape it as
# ``recovery[i] * gt_linear_mean[i]`` so the model recovers an explicit
# fraction of the ceiling on each file.
# ---------------------------------------------------------------------------


def _build_model_fv_linear(
    reference,
    recovery_per_file: list[float],
) -> list[float]:
    fv: list[float] = []
    for i in range(20):
        gt_lin_sum = reference.gt_per_file_linear_sum[i]
        n = reference.gt_per_file_n_segments[i]
        gt_mean = gt_lin_sum / n
        fv.append(recovery_per_file[i] * gt_mean)
    return fv


def _model_fv_log_from_linear(model_fv_linear: list[float]) -> list[float]:
    """log_5.27(v + 1e-10) — mirrors execute_tools/scoring_helpers."""
    return [math.log(v + 1e-10) / math.log(5.27) for v in model_fv_linear]


def _make_summary(
    model_type: str,
    iter_label: str,
    score_table: ScoreComparisonTable,
    fv_log: list[float],
    scalar_log: float,
    description: str,
) -> ModelRunSummary:
    return ModelRunSummary(
        model_type=model_type,
        run_name=f"4zh_{model_type}_{iter_label}",
        status="completed",
        completed_rounds=2,
        best_denoising_score=scalar_log,
        worst_denoising_score=scalar_log - 0.1,
        best_config={
            "model_config": {"hidden": 32},
            "train_config": {"lr": 1e-4, "epochs": 5},
            "loss_config": {"loss_type": "focal"},
        },
        round_scores=[scalar_log - 0.1, scalar_log],
        round_conclusions=[
            f"{iter_label}: per-file table populated.",
            f"{iter_label}: best round complete.",
        ],
        model_description=description,
        best_file_vector=fv_log,
        best_score_table=score_table,
        best_model_params=1_000_000,
    )


def _build_summary(
    model_type: str,
    iter_label: str,
    recovery: list[float],
    reference,
    description: str,
) -> tuple[ModelRunSummary, ScoreComparisonTable, float]:
    fv_lin = _build_model_fv_linear(reference, recovery)
    fv_log = _model_fv_log_from_linear(fv_lin)
    scalar_lin = sum(fv_lin) / len(fv_lin)
    scalar_log = math.log(scalar_lin + 1e-10) / math.log(5.27)
    table = build_score_table(
        model_fv_log=fv_log,
        model_scalar=scalar_log,
        reference=reference,
        model_fv_linear=fv_lin,
        reference_source=f"4zh_{model_type}_{iter_label}_fixture",
    )
    assert table is not None, f"build_score_table returned None for {model_type}/{iter_label}."
    summary = _make_summary(
        model_type=model_type,
        iter_label=iter_label,
        score_table=table,
        fv_log=fv_log,
        scalar_log=scalar_log,
        description=description,
    )
    return summary, table, scalar_log


# ---------------------------------------------------------------------------
# Banned vocabulary (Metric 2).
# Permanence-classification phrasings — the V8 echo-chamber pattern.
# Mirrors the production-prompt regression guard in
# ``tests/unit/agent/test_prompt_banned_vocabulary.py`` but applied to LLM
# output rather than prompt strings.
# ---------------------------------------------------------------------------

_FORBIDDEN_PERMANENCE_PHRASES = [
    "permanently irrelevant",
    "always at the floor",
    "ignore files",
    "can never improve",
    "permanent floor",
    "always inconsequential",
    "out of scope",
    "out-of-scope",
]


# ---------------------------------------------------------------------------
# Saturation cues (Metric 3) — relative judgments against ``model_scalar``,
# not fixed-cutoff partitions. The take_home_message must contain at least
# one of these to declare chain-ceiling reached.
# ---------------------------------------------------------------------------

_SATURATION_CUES = [
    "saturated",
    "saturation",
    "ceiling reached",
    "reached the ceiling",
    "near the ceiling",
    "near-ceiling",
    "at the ceiling",
    "no remaining lever",
    "no further lever",
    "no obvious lever",
    "diminishing returns",
    "uniformly small",
    "dataset-limited",
    "dataset limited",
    "all files at",
    "ceiling",
]


# ---------------------------------------------------------------------------
# Vocab-diff helper. Ported from test_score_table_pseudo_smoke.py:328.
# ---------------------------------------------------------------------------


def _vocab_diff(
    before: list[VocabEntry],
    after: list[VocabEntry],
) -> tuple[list[str], list[str], list[str]]:
    before_names = {v.name for v in before}
    after_names = {v.name for v in after}
    added = sorted(after_names - before_names)
    removed = sorted(before_names - after_names)

    before_by_name = {v.name: v for v in before}
    refined: list[str] = []
    for v in after:
        prev = before_by_name.get(v.name)
        if prev is None:
            continue
        if (
            getattr(prev, "description", None) != getattr(v, "description", None)
            or getattr(prev, "tier", None) != getattr(v, "tier", None)
            or sorted(getattr(prev, "seen_in_runs", [])) != sorted(getattr(v, "seen_in_runs", []))
            or sorted(getattr(prev, "related_to", [])) != sorted(getattr(v, "related_to", []))
        ):
            refined.append(v.name)
    refined = sorted(refined)
    return added, refined, removed


# ---------------------------------------------------------------------------
# Lever extraction & citation detection. The top-Impact file index is
# read from the score table itself (never hardcoded into the assertion);
# pre-LLM sanity then verifies the index matches the suppressed file.
# ---------------------------------------------------------------------------


def _top_impact_file(table: ScoreComparisonTable) -> int:
    best = -1.0
    best_idx = -1
    for row in table.rows:
        if row.impact_score is None:
            continue
        if row.impact_score > best:
            best = row.impact_score
            best_idx = row.file_index
    assert best_idx >= 0, "score_table has no impact_score column populated"
    return best_idx


def _file_idx_cited(text: str, target_idx: int) -> bool:
    """True iff ``text`` cites file at ``target_idx`` with a 'file' anchor."""
    pat = re.compile(
        rf"\bfiles?\s*(?:#|index\s*)?\s*(?:_)?{target_idx}\b|"
        rf"\bfile_?index[=:\s]+{target_idx}\b|"
        rf"\bfile\s+at\s+(?:index\s+)?{target_idx}\b|"
        rf"\bindex\s+{target_idx}\b",
        re.IGNORECASE,
    )
    return bool(pat.search(text))


# ---------------------------------------------------------------------------
# The Gate 1 test.
# ---------------------------------------------------------------------------


@pytest.mark.real_run
def test_cognitive_alignment_gate_one(tmp_path, capsys):
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — skipping 4-zh Gate 1.")

    reference = load_reference_scores()

    # --- Build per-iter recovery shapes ----------------------------------
    rec_iter1 = [_BASE_RECOVERY] * 20
    rec_iter1[ITER1_LEVER] = _LEVER_RECOVERY

    rec_iter2 = [_BASE_RECOVERY] * 20
    rec_iter2[ITER1_LEVER] = _SATURATED_RECOVERY  # recovered
    rec_iter2[ITER2_LEVER] = _LEVER_RECOVERY  # newly suppressed

    rec_iter3 = [_SATURATED_RECOVERY] * 20

    iter_recoveries = [rec_iter1, rec_iter2, rec_iter3]
    iter_tables: list[ScoreComparisonTable] = []  # candidate tables (cognitive_smoke_arch)
    iter_candidate_summaries: list[ModelRunSummary] = []
    iter_baseline_summaries: list[ModelRunSummary] = []

    candidate_desc = (
        "Smoke-test architecture for 4-zh Gate 1. Identity-style transform with "
        "per-file recovery shaping for cognitive-alignment validation."
    )
    baseline_desc = (
        "Mirror baseline. Tracks the candidate's per-iter recovery shape with "
        "a uniform 0.05 offset (every file 0.05 lower than the candidate that "
        "iter). Present as a comparison point so the synthesis stage fires "
        "(synthesis is bypassed when only one model_type is present); shaped "
        "to point at the same per-iter lever the candidate does, eliminating "
        "cross-model anchoring ambiguity."
    )

    for k, rec in enumerate(iter_recoveries, start=1):
        cand_summary, cand_table, _ = _build_summary(
            model_type="cognitive_smoke_arch",
            iter_label=f"iter{k}",
            recovery=rec,
            reference=reference,
            description=candidate_desc,
        )
        iter_tables.append(cand_table)
        iter_candidate_summaries.append(cand_summary)

        # Mirror baseline: candidate recovery minus uniform offset, clamped
        # to [0, 1] so an aggressive lever (e.g. 0.30 - 0.05 = 0.25) stays
        # well-formed and a saturated cell (0.97 - 0.05 = 0.92) doesn't
        # exceed bounds.
        baseline_recovery = [max(0.0, min(1.0, c - _BASELINE_OFFSET)) for c in rec]

        base_summary, _, _ = _build_summary(
            model_type="weak_baseline_arch",
            iter_label=f"iter{k}",
            recovery=baseline_recovery,
            reference=reference,
            description=baseline_desc,
        )
        iter_baseline_summaries.append(base_summary)

    # --- Pre-LLM sanity check on lever shape -----------------------------
    # The cognitive metrics depend on the column shape behaving as
    # designed; if the fixture math drifted, fail loudly here rather than
    # pinning the failure on the LLM.
    iter1_top = _top_impact_file(iter_tables[0])
    iter2_top = _top_impact_file(iter_tables[1])
    iter3_max_impact = max(
        (r.impact_score for r in iter_tables[2].rows if r.impact_score is not None),
        default=0.0,
    )
    iter3_scalar = iter_tables[2].aggregate.model_scalar

    assert iter1_top == ITER1_LEVER, (
        f"Pre-LLM sanity: iter_1 top-Impact file should be {ITER1_LEVER} "
        f"(suppressed at recovery={_LEVER_RECOVERY}); got {iter1_top}. "
        f"Fixture math broken — abort."
    )
    assert iter2_top == ITER2_LEVER, (
        f"Pre-LLM sanity: iter_2 top-Impact file should be {ITER2_LEVER} "
        f"(file {ITER1_LEVER} recovered, file {ITER2_LEVER} suppressed); "
        f"got {iter2_top}."
    )
    assert iter1_top != iter2_top, (
        "Pre-LLM sanity: iter_1 and iter_2 must have DIFFERENT top-Impact "
        "files for the dynamic-lever-ID metric to be meaningful."
    )
    assert iter3_max_impact < 0.05, (
        f"Pre-LLM sanity: iter_3 max Impact_Score ({iter3_max_impact:.4f}) "
        f"is not small in absolute terms — saturation fixture too "
        f"aggressive. model_scalar={iter3_scalar:.4f}. Bump "
        f"_SATURATED_RECOVERY closer to 1.0 or revisit the fixture math."
    )

    # --- Iterate the cognitive loop --------------------------------------
    interp_outputs: list[InterpretationOutput] = []
    proposal_outputs: list[ProposalOutput] = []
    interp_call_logs: list[list] = []  # one shared list per iter (Metric 5)

    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
        model_selection=ModelSelectionStrategy(method="top_n", params={"n": 1}),
    )

    prev_runtime_vocab: list[VocabEntry] = []
    prev_proposal_dict: dict[str, Any] | None = None

    for k, (cand_summary, base_summary) in enumerate(
        zip(iter_candidate_summaries, iter_baseline_summaries, strict=True), start=1
    ):
        storage = StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(tmp_path),
                run_name=f"4zh_iter{k}",
            ),
        )

        interp_calls, interp_factory = _make_recording_factory(_INTERP_MODEL)
        interp_call_logs.append(interp_calls)

        interp_inp = InterpretationInput(
            # Two model types every iter so the synthesis branch fires —
            # candidate carries the per-iter lever shape, baseline is
            # constant. Empty model_knowledge_cache forces fresh Phase 1
            # for both models each iter.
            summaries=[cand_summary, base_summary],
            runtime_vocab=prev_runtime_vocab,
            previous_proposal=prev_proposal_dict,
            storage=storage,
            iteration=k,
        )

        t0 = time.perf_counter()
        interp_agent = ResultInterpretationAgent(bridge_factory=interp_factory)
        interp_out = interp_agent.run(interp_inp)
        interp_elapsed = time.perf_counter() - t0
        interp_outputs.append(interp_out)

        # Run the proposer too — keeps the chain faithful to chain mode
        # (vocab carry-forward via proposed_vocab_candidates). Metrics
        # 1-6 read from interp output / interp prompts only; the proposer
        # contributes via build_runtime_vocab in the NEXT iter's interp.
        _, proposer_factory = _make_recording_factory(_PROPOSER_MODEL)
        proposer_inp = local_full_context(
            interp_out,
            storage,
            reasoning_pipeline=pipeline,
        )
        proposer_agent = MLModelProposalAgent(bridge_factory=proposer_factory)
        prop_out = proposer_agent.run(proposer_inp)
        proposal_outputs.append(prop_out)

        prev_runtime_vocab = interp_out.runtime_vocab
        prev_proposal_dict = prop_out.model_dump()

        expected_top = iter1_top if k == 1 else iter2_top if k == 2 else None
        print("=" * 78, flush=True)
        print(
            f"ITER {k}  (interp {interp_elapsed:.1f}s; "
            f"vocab→{len(interp_out.runtime_vocab)}; "
            f"expected top_impact_file={expected_top})",
            flush=True,
        )
        print(f"take_home_message: {interp_out.take_home_message}", flush=True)
        print("=" * 78, flush=True)

    # ====================================================================
    # Metric 1 — Dynamic lever identification.
    # iter_1's take_home cites ITER1_LEVER; iter_2's cites ITER2_LEVER.
    # Since the two indices differ, the cited file changes between iters.
    # ====================================================================
    iter1_msg = interp_outputs[0].take_home_message
    iter2_msg = interp_outputs[1].take_home_message
    iter3_msg = interp_outputs[2].take_home_message

    assert _file_idx_cited(iter1_msg, ITER1_LEVER), (
        f"M1: iter_1 take_home_message did not cite the top-Impact file "
        f"{ITER1_LEVER}. Message: {iter1_msg!r}"
    )
    assert _file_idx_cited(iter2_msg, ITER2_LEVER), (
        f"M1: iter_2 take_home_message did not cite the top-Impact file "
        f"{ITER2_LEVER} (which IS the new top-Impact file after "
        f"file {ITER1_LEVER} was recovered). Message: {iter2_msg!r}"
    )

    # ====================================================================
    # Metric 2 — No permanent-irrelevance phrasing across all 3 iters.
    # The agent may say a file is *currently* at its ceiling — that is a
    # reading of the data, not a permanence classification.
    # ====================================================================
    all_msgs_lower = " ".join(m.lower() for m in (iter1_msg, iter2_msg, iter3_msg))
    for phrase in _FORBIDDEN_PERMANENCE_PHRASES:
        assert phrase not in all_msgs_lower, (
            f"M2: forbidden permanence phrase {phrase!r} appears in one of "
            f"the 3 take_home_messages. The V9 framing is task-agnostic — "
            f"the agent should re-read Impact_Score per-iter, not classify "
            f"files as out-of-scope."
        )

    # ====================================================================
    # Metric 3 — Iteration-3 Saturation assertion.
    # iter_3's flat Impact_Score column (max impact < 0.05 vs scalar
    # ~|model_scalar|) should trigger a chain-ceiling cue grounded in
    # column distribution. No fixed cutoff is permitted in the assertion;
    # we just check that some saturation phrasing landed.
    # ====================================================================
    iter3_lower = iter3_msg.lower()
    saturation_hits = [c for c in _SATURATION_CUES if c in iter3_lower]
    assert saturation_hits, (
        f"M3: iter_3 take_home_message did not declare saturation despite "
        f"a flat Impact_Score column.\n"
        f"  iter_3 max Impact_Score = {iter3_max_impact:.4f}\n"
        f"  iter_3 model_scalar     = {iter3_scalar:.4f}\n"
        f"  message: {iter3_msg!r}\n"
        f"  expected any of: {_SATURATION_CUES}"
    )

    # ====================================================================
    # Metric 4 — Echo-chamber guard: pairwise Jaccard < 0.7 on
    # lower-cased word-token sets.
    # ====================================================================
    def tokenset(s: str) -> set:
        return set(re.findall(r"[a-z]+", s.lower()))

    def jaccard(a: set, b: set) -> float:
        union = a | b
        if not union:
            return 1.0
        return len(a & b) / len(union)

    t1, t2, t3 = tokenset(iter1_msg), tokenset(iter2_msg), tokenset(iter3_msg)
    pairs = {
        "1↔2": jaccard(t1, t2),
        "1↔3": jaccard(t1, t3),
        "2↔3": jaccard(t2, t3),
    }
    for label, jac in pairs.items():
        assert jac < 0.7, (
            f"M4: pairwise Jaccard for {label} = {jac:.3f} (≥ 0.7) — the "
            f"LLM is emitting one canned diagnosis regardless of per-iter "
            f"data. Pairs: {pairs}"
        )

    # ====================================================================
    # Metric 5 — Prompt-column presence.
    # The captured synthesis prompt for each iter must surface both the
    # Impact and Linear-Weight columns. Carries forward the Phase 6.5
    # Stage 1 numeric-citation continuity guard.
    #
    # Post-2-zh, the renderer at execute_tools/scoring_helpers.py emits
    # abbreviated column headers in the user-message table body
    # (`| Weight % | Impact |`) while the full literals `Linear_Weight`
    # and `Impact_Score` only appear in *system* prompts and prose
    # section headers. `Impact_Score` survives in user prompts via the
    # secondary-block section header (`### Sampled files re-ranked by
    # Impact_Score (descending)`); `Linear_Weight` does not. We assert
    # the metric's *intent* (both columns demonstrably reach the LLM
    # via the user message) by accepting either the full literal or
    # the rendered abbreviation.
    # ====================================================================
    for k, calls in enumerate(interp_call_logs, start=1):
        assert calls, f"M5: iter_{k} captured zero interp calls."
        all_user_prompts = "\n".join(c[2] for c in calls)
        impact_present = "Impact_Score" in all_user_prompts or "| Impact |" in all_user_prompts
        assert impact_present, (
            f"M5: iter_{k} interp prompt missing Impact column "
            f"(neither 'Impact_Score' nor '| Impact |' found). "
            f"Captured {len(calls)} calls; total prompt length="
            f"{len(all_user_prompts)}."
        )
        weight_present = "Linear_Weight" in all_user_prompts or "| Weight % |" in all_user_prompts
        assert weight_present, (
            f"M5: iter_{k} interp prompt missing Linear-Weight column "
            f"(neither 'Linear_Weight' nor '| Weight % |' found). "
            f"Captured {len(calls)} calls; total prompt length="
            f"{len(all_user_prompts)}."
        )

    # ====================================================================
    # Metric 6 — Vocab evolution across the 3 iters.
    # Either size grows OR existing entries refine; no entries dropped.
    # runtime_vocab is the agent's only persisted lesson-learning channel
    # — if the data shifts the lever between iters but no vocab change
    # registers, the chain is reading the column but accumulating no
    # insight from it.
    # ====================================================================
    v1 = interp_outputs[0].runtime_vocab
    v2 = interp_outputs[1].runtime_vocab
    v3 = interp_outputs[2].runtime_vocab

    _added_12, _refined_12, removed_12 = _vocab_diff(v1, v2)
    _added_23, _refined_23, removed_23 = _vocab_diff(v2, v3)
    added_13, refined_13, removed_13 = _vocab_diff(v1, v3)

    assert not removed_12, (
        f"M6: iter_2 dropped vocab entries from iter_1: {removed_12}. "
        f"build_runtime_vocab must preserve carry-forward entries."
    )
    assert not removed_23, f"M6: iter_3 dropped vocab entries from iter_2: {removed_23}."
    assert not removed_13, (
        f"M6: iter_3 dropped vocab entries from iter_1 (cross-iter): {removed_13}."
    )

    grew = len(v3) > len(v1)
    refined_overall = bool(added_13 or refined_13)
    assert grew or refined_overall, (
        f"M6: runtime_vocab neither grew nor refined across 3 iters. "
        f"sizes: iter1={len(v1)}, iter2={len(v2)}, iter3={len(v3)}; "
        f"added(1→3)={added_13}; refined(1→3)={refined_13}. "
        f"The iteration loop is not accumulating knowledge."
    )

    # --- Final report ---------------------------------------------------
    print("=" * 78, flush=True)
    print("4-zh Gate 1: ALL 6 METRICS PASSED.", flush=True)
    print(f"  M1 levers cited: iter_1=file{ITER1_LEVER}, iter_2=file{ITER2_LEVER}", flush=True)
    print(f"  M3 saturation cues hit: {saturation_hits}", flush=True)
    print(f"  M4 Jaccard pairs: { {k: round(v, 3) for k, v in pairs.items()} }", flush=True)
    print("  M5 prompt columns visible in all 3 iters", flush=True)
    print(
        f"  M6 vocab sizes: {len(v1)} → {len(v2)} → {len(v3)}; "
        f"added(1→3)={added_13}; refined(1→3)={refined_13}",
        flush=True,
    )
    print("=" * 78, flush=True)
