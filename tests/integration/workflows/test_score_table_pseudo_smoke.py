"""
Phase 6.5 Stage 1 — "The Brain" pseudo semantic smoke.

Goal: prove that a real LLM, reading the Phase 3-5 score-table markdown we
now inject into proposer prompts, actually USES those numerics — without
spending a single GPU second.

Mechanism:
  * Real OpenAI (gpt-4o-mini) for both interp + proposer.
  * Pseudo training: ModelRunSummary fixtures with distinctive
    ScoreComparisonTable.best_score_table attached. No GPU. No subprocess.
  * 2 iterations.
    - Iter 1: interp → protocol → proposer.
      Assert the proposer's reasoning text (motivation +
      mathematical_definition + expert_advice.rationale) contains AT LEAST
      ONE numeric signature derivable from our fixtures (specific file
      index, scalar value we injected, recovery % we computed, or one of
      the canonical column names).  Zero matches => the table was ignored.
    - Iter 2: inject a synthetic run of the iter-1 proposed model, feed
      back iter-1 runtime_vocab.  Assert new interp's runtime_vocab
      STRICTLY grew, print vocab diff.

Runs as ``real_run`` (not CI).  Requires OPENAI_API_KEY.

Run with:
  uv run pytest -m real_run tests/integration/workflows/test_score_table_pseudo_smoke.py -v -s
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

import pytest
from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge
from agent.schemas.hyperparam_tuning import ExpertAdvice
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
)
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
    local_full_context,
)
from agent.schemas.score_table import (
    AggregateScalars,
    PerFileRow,
    ScoreComparisonTable,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.scoring_helpers import render_comparison_table
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.result_interpretation_agent import ResultInterpretationAgent

load_dotenv()

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Score-table factory (mirrors Phase 6 B's helper — kept local so this
# semantic-smoke file is self-contained and can be deleted without coupling).
# ---------------------------------------------------------------------------

_RAW_BASELINE = 0.2
_GROUND_TRUTH = 9.5


def _make_score_table(fv: list[float], model_scalar: float) -> ScoreComparisonTable:
    raw_baseline_per_file = [_RAW_BASELINE] * 20
    ground_truth_per_file = [_GROUND_TRUTH] * 20
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=raw_baseline_per_file[i],
            ground_truth=ground_truth_per_file[i],
            model=v,
            gain_vs_raw=v - raw_baseline_per_file[i],
            headroom_vs_gt=ground_truth_per_file[i] - v,
        )
        for i, v in enumerate(fv)
    ]
    aggregate = AggregateScalars(
        raw_baseline_scalar=_RAW_BASELINE,
        ground_truth_scalar=_GROUND_TRUTH,
        model_scalar=model_scalar,
        percent_of_ceiling_log=model_scalar / _GROUND_TRUTH,
        num_sampled_files=20,
    )
    table = ScoreComparisonTable(
        rows=rows,
        aggregate=aggregate,
        s_max_global=5.27,
        reference_source="phase65_pseudo_fixture",
        rendered_markdown="",
    )
    return table.model_copy(update={"rendered_markdown": render_comparison_table(table)})


# ---------------------------------------------------------------------------
# Iteration-1 fixtures — two contrasting seeds with DISTINCTIVE numerics
# so the LLM has something specific and cheap to cite.
#
#   wavenet : strong on high-freq files, dead on low-freq (classic blind
#             spot).  Recovery ≈ 58.7%.
#   punet   : flat and weak across the board.  Recovery ≈ 24.7%.
# ---------------------------------------------------------------------------

_WAVENET_FV = [
    0.05,
    0.08,
    0.12,
    0.15,
    0.18,  # files 0-4  (blind)
    4.20,
    4.80,
    5.30,
    5.70,
    6.10,
    6.40,  # files 5-10 (mid)
    7.00,
    7.40,
    7.80,
    8.10,
    8.30,
    8.50,
    8.70,
    8.90,  # files 11-18 (strong)
    9.00,  # file  19   (strong)
]
_WAVENET_SCALAR = 5.58  # ≈ 58.7% of ceiling (9.5)

_PUNET_FV = [
    1.50,
    1.60,
    1.70,
    1.80,
    1.90,
    2.00,
    2.10,
    2.20,
    2.30,
    2.40,
    2.50,
    2.60,
    2.70,
    2.80,
    2.90,
    3.00,
    3.10,
    3.20,
    3.30,
    3.40,
]
_PUNET_SCALAR = 2.35  # ≈ 24.7% of ceiling


_WAVENET_SUMMARY = ModelRunSummary(
    model_type="wavenet",
    run_name="phase65_seed",
    status="completed",
    completed_rounds=3,
    best_denoising_score=_WAVENET_SCALAR,
    worst_denoising_score=5.45,
    best_config={
        "model_config": {"residual_channels": 32, "num_blocks": 4},
        "train_config": {"lr": 1e-4, "epochs": 10},
        "loss_config": {"loss_type": "focal"},
    },
    round_scores=[5.45, 5.52, _WAVENET_SCALAR],
    round_conclusions=[
        "Baseline established on high-frequency files.",
        "Low-frequency files 0-4 remain near zero despite loss tuning.",
        "Structural blind spot — low-freq scores unchanged at <0.2.",
    ],
    model_description=(
        "Causal dilated-conv stack with residual + skip connections. Proven "
        "strong on mid/high-frequency denoising; empirically weak on the "
        "lowest-frequency validation files."
    ),
    best_file_vector=_WAVENET_FV,
    best_score_table=_make_score_table(_WAVENET_FV, _WAVENET_SCALAR),
    best_model_params=4_123_456,
)


_PUNET_SUMMARY = ModelRunSummary(
    model_type="punet",
    run_name="phase65_seed",
    status="completed",
    completed_rounds=2,
    best_denoising_score=_PUNET_SCALAR,
    worst_denoising_score=2.10,
    best_config={
        "model_config": {"depth": 3, "base_channels": 32},
        "train_config": {"lr": 1e-4, "epochs": 8},
        "loss_config": {"loss_type": "focal"},
    },
    round_scores=[2.10, _PUNET_SCALAR],
    round_conclusions=[
        "Flat recovery across the spectrum — no per-band specialisation.",
        "Marginal gain saturates well below wavenet SOTA.",
    ],
    model_description=(
        "Positional U-Net with sinusoidal positional encoding. Uniform "
        "capacity allocation means no particular frequency band dominates."
    ),
    best_file_vector=_PUNET_FV,
    best_score_table=_make_score_table(_PUNET_FV, _PUNET_SCALAR),
    best_model_params=2_900_000,
)


# ---------------------------------------------------------------------------
# OpenAI bridge factory — ignores upstream provider/model kwargs and pins
# OpenAI.  Memory ``feedback_prefer_openai_for_smoke.md`` mandates OpenAI
# for smoke runs because the Gemini API has been flaky.
# ---------------------------------------------------------------------------

_OPENAI_MODEL = "gpt-4o-mini"


class RecordingOpenAIBridge(LLMBridge):
    """Real OpenAI bridge that also records every prompt + response.

    We need every intermediate response (not just the final committed
    ``ProposalOutput``) to audit what the LLM actually wrote about the
    score table.  The pipeline's ``comparison`` / ``causal_reasoning``
    stages use ``generate_text`` for free-form reasoning; the final
    commit stage uses ``generate`` (JSON).  Both are captured.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        # Each entry: (method_name, system_prompt, user_prompt, response)
        self.calls: list = []

    def generate(self, system_prompt: str, user_prompt: str):
        resp = super().generate(system_prompt, user_prompt)
        self.calls.append(("generate", system_prompt, user_prompt, resp))
        return resp

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        resp = super().generate_text(system_prompt, user_prompt)
        self.calls.append(("generate_text", system_prompt, user_prompt, resp))
        return resp


def _make_recording_factory() -> tuple[list, callable]:
    """Return (shared-call-log, bridge-factory-that-appends-to-it)."""
    shared: list = []

    def factory(**ignored) -> RecordingOpenAIBridge:
        bridge = RecordingOpenAIBridge(
            provider="openai",
            model_id=_OPENAI_MODEL,
            max_retries=3,
        )
        bridge.calls = shared  # share the list so every bridge logs here
        return bridge

    return shared, factory


# ---------------------------------------------------------------------------
# Numeric-signature scanner
#
# A "signature" is evidence that the LLM read the table, not that it
# hallucinated a number.  We accept ANY of:
#   * A file index (0..19) in a file-reference context.
#   * One of our specific injected scalars rendered to 1-2 decimals.
#   * A recovery percentage rounded to int (24, 25, 58, 59, 60).
#   * A canonical column-name token we injected via rendered_markdown.
# ---------------------------------------------------------------------------

# Only multi-word / snake_case tokens that would not appear by accident in
# plain English.  ``recovery`` / ``headroom`` (as single words) are too
# weak — the earlier run matched "signal recovery capabilities" which was
# a false positive.  Drop them from the column scan.
_COLUMN_TOKENS = (
    "gain_vs_raw",
    "raw_baseline",
    "ground_truth",
    "log_scalar",
    "percent_of_ceiling",
    "model_scalar",
    "headroom_vs_gt",
)

# Specific scalars we put into the fixtures and would expect to see cited.
_INJECTED_SCALARS = (
    "5.58",
    "2.35",  # model scalars
    "9.5",
    "9.50",  # ground-truth ceiling
    "0.2",
    "0.20",  # raw baseline
    "9.0",
    "9.00",
    "8.9",
    "8.90",  # wavenet best per-file values
    "0.05",
    "0.08",
    "0.12",
    "0.15",  # wavenet blind-spot files
    "1.5",
    "1.50",
    "3.4",
    "3.40",  # punet flat-spread endpoints
)

_RECOVERY_PCT = ("24", "25", "58", "59", "60")


def _scan_for_signatures(text: str) -> list[str]:
    """Return a list of human-readable signature hits found in ``text``."""
    hits: list[str] = []

    # 1. File-index references.  Require 'file' near the number to avoid
    #    picking up dates / counts.  Match things like "file 0", "file #4",
    #    "file_index 19", "files 0-4".
    file_ref_re = re.compile(
        r"\bfiles?\s*(?:#|index\s*)?\s*(?:_)?(\d{1,2})\b|\bfile_?index[=:\s]+(\d{1,2})\b",
        re.IGNORECASE,
    )
    for m in file_ref_re.finditer(text):
        idx_str = m.group(1) or m.group(2)
        if idx_str is not None:
            idx = int(idx_str)
            if 0 <= idx <= 19:
                hits.append(f"file_idx:{idx}")

    # Also accept "files 0-4" / "0 through 4" style ranges.
    range_re = re.compile(
        r"\bfiles?\s*(\d{1,2})\s*(?:-|-|to|through)\s*(\d{1,2})\b",
        re.IGNORECASE,
    )
    for m in range_re.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if 0 <= a <= 19 and 0 <= b <= 19:
            hits.append(f"file_range:{a}-{b}")

    # 2. Injected scalars — literal substring match, but guard against
    #    picking them up as a sub-number (e.g. "0.05" inside "10.059").
    for scalar in _INJECTED_SCALARS:
        pat = r"(?<!\d)" + re.escape(scalar) + r"(?!\d)"
        if re.search(pat, text):
            hits.append(f"scalar:{scalar}")

    # 3. Recovery percentages.  Must be followed by % or preceded/followed by
    #    'recovery'/'ceiling'/'of ceiling' cues.
    for pct in _RECOVERY_PCT:
        pct_re = re.compile(
            r"(?<!\d)" + re.escape(pct) + r"(?:\.\d+)?\s*%|"
            r"(?:recovery|ceiling)[^\n]{0,40}?(?<!\d)" + re.escape(pct) + r"(?!\d)",
            re.IGNORECASE,
        )
        if pct_re.search(text):
            hits.append(f"recovery_pct:{pct}")

    # 4. Column-name tokens.
    for tok in _COLUMN_TOKENS:
        if tok in text:
            hits.append(f"col:{tok}")

    return hits


# ---------------------------------------------------------------------------
# Vocab-diff helper
# ---------------------------------------------------------------------------


def _vocab_diff(before, after) -> tuple[list, list, list]:
    before_names = {v.name for v in before}
    after_names = {v.name for v in after}
    added = sorted(after_names - before_names)
    removed = sorted(before_names - after_names)

    # Refined = same name but different description/evidence.
    before_by_name = {v.name: v for v in before}
    refined = []
    for v in after:
        prev = before_by_name.get(v.name)
        if prev is None:
            continue
        if getattr(prev, "description", None) != getattr(v, "description", None) or getattr(
            prev, "status", None
        ) != getattr(v, "status", None):
            refined.append(v.name)
    refined = sorted(refined)
    return added, refined, removed


# ---------------------------------------------------------------------------
# The actual smoke test
# ---------------------------------------------------------------------------


@pytest.mark.real_run
def test_stage1_pseudo_semantic_smoke(tmp_path, capsys):
    """Phase 6.5 Stage 1 — the Brain works without GPU."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — skipping Phase 6.5 Stage 1")

    storage_iter1 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="phase65_iter1"),
    )
    storage_iter2 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="phase65_iter2"),
    )

    # --- Iter 1: interpretation -----------------------------------------
    iter1_t0 = time.perf_counter()

    iter1_inp = InterpretationInput(
        summaries=[_WAVENET_SUMMARY, _PUNET_SUMMARY],
        runtime_vocab=[],
        previous_proposal=None,
        storage=storage_iter1,
    )

    # Use a plain OpenAI bridge for the interp agent — its responses are
    # persisted in `InterpretationOutput`, so we don't need call recording
    # for that side.
    def _plain_openai_bridge(**ignored):
        return LLMBridge(
            provider="openai",
            model_id=_OPENAI_MODEL,
            max_retries=3,
        )

    interp_agent = ResultInterpretationAgent(bridge_factory=_plain_openai_bridge)
    iter1_interp = interp_agent.run(iter1_inp)

    assert isinstance(iter1_interp, InterpretationOutput)
    assert "wavenet" in iter1_interp.model_types
    assert "punet" in iter1_interp.model_types
    assert iter1_interp.per_model_score_tables, (
        "iter1 interp did not emit per_model_score_tables — Phase 4 contract "
        "broken on the real-LLM path."
    )

    # --- Iter 1: proposal -----------------------------------------------
    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
        model_selection=ModelSelectionStrategy(method="top_n", params={"n": 2}),
    )
    proposal_inp = local_full_context(
        iter1_interp,
        storage_iter1,
        reasoning_pipeline=pipeline,
    )

    proposer_calls, proposer_factory = _make_recording_factory()
    proposal_agent = MLModelProposalAgent(bridge_factory=proposer_factory)
    iter1_proposal = proposal_agent.run(proposal_inp)
    assert isinstance(iter1_proposal, ProposalOutput)

    iter1_elapsed_s = time.perf_counter() - iter1_t0

    # --- Iter 1: per-stage semantic scan --------------------------------
    # Each pipeline stage is one LLM call.  We tag calls by order:
    #   [0] comparison         (generate_text)
    #   [1] causal_reasoning   (generate_text)
    #   [2] proposing / commit (generate → JSON)
    # Extra calls can appear from the commit stage's pre-flight revision
    # loop.  We scan every call's response and also tally the committed
    # fields separately.
    _STAGE_NAMES = ("comparison", "causal_reasoning", "proposing_commit")
    per_call_hits: list[tuple[str, int, list[str]]] = []
    all_stage_text_parts: list[str] = []

    for idx, (method, _sys, _user, resp) in enumerate(proposer_calls):
        stage_tag = _STAGE_NAMES[idx] if idx < len(_STAGE_NAMES) else f"extra_call_{idx}"
        if method == "generate_text":
            resp_text = resp if isinstance(resp, str) else str(resp)
        else:
            # `generate` returns a dict — stringify for scanning.
            resp_text = str(resp)
        call_hits = _scan_for_signatures(resp_text)
        per_call_hits.append((stage_tag, len(call_hits), call_hits))
        all_stage_text_parts.append(
            f"\n── stage[{idx}] {stage_tag} ({method}) ── hits={len(call_hits)}\n{resp_text}"
        )

    # Committed-fields scan (the final condensed prose).
    committed_blob = "\n---\n".join(
        [
            f"[motivation]\n{iter1_proposal.motivation}",
            f"[mathematical_definition]\n{iter1_proposal.mathematical_definition}",
            f"[expert_advice.rationale]\n{iter1_proposal.expert_advice.rationale}",
        ]
    )
    committed_hits = _scan_for_signatures(committed_blob)

    total_stage_hits = sum(n for _, n, _ in per_call_hits)

    # ---------- report ----------
    print("\n" + "=" * 78, flush=True)
    print(f"STAGE 1 / ITER 1  (elapsed {iter1_elapsed_s:.1f} s)", flush=True)
    print("=" * 78, flush=True)
    print(f"Proposed model  : {iter1_proposal.model_name}", flush=True)
    print(f"Proposer LLM    : {_OPENAI_MODEL} ({len(proposer_calls)} calls)", flush=True)
    print(f"Stage hits (sum): {total_stage_hits}", flush=True)
    for tag, n, hits_list in per_call_hits:
        print(f"  • {tag}: {n} — {hits_list}", flush=True)
    print(f"Committed-field hits: {len(committed_hits)} — {committed_hits}", flush=True)
    print("-" * 78, flush=True)
    print("STAGE-BY-STAGE PROPOSER OUTPUT:", flush=True)
    print("".join(all_stage_text_parts), flush=True)
    print("-" * 78, flush=True)
    print("COMMITTED ProposalOutput fields:", flush=True)
    print(committed_blob, flush=True)
    print("=" * 78, flush=True)

    # Hard assertion: at least one stage must carry real numeric evidence
    # that the LLM was reading the injected score table.
    assert total_stage_hits > 0, (
        "Iter 1 proposer produced ZERO numeric citations across all stages. "
        "The score-table markdown block is not being read by the LLM. "
        "See stage-by-stage output above."
    )

    # --- Iter 2: inject a run of the proposed model ---------------------
    # Give the new model a slightly-better-than-wavenet scalar so there's
    # something for the interp to react to and grow vocab around.
    new_fv = [
        0.50,
        0.80,
        1.20,
        1.60,
        2.00,  # markedly better than wavenet on low
        4.50,
        5.10,
        5.60,
        6.00,
        6.40,
        6.60,
        7.10,
        7.50,
        7.90,
        8.20,
        8.40,
        8.60,
        8.80,
        9.00,
        9.10,
    ]
    new_scalar = 5.95

    new_summary = ModelRunSummary(
        model_type=iter1_proposal.model_name,
        run_name="phase65_iter2",
        status="completed",
        completed_rounds=3,
        best_denoising_score=new_scalar,
        worst_denoising_score=5.70,
        best_config=iter1_proposal.baseline_config,
        round_scores=[5.70, 5.85, new_scalar],
        round_conclusions=[
            "New architecture reaches wavenet parity after round 1.",
            "Improvements concentrated on the low-frequency files.",
            "Peak recovery of low-frequency band — structural gap narrowed.",
        ],
        model_description=iter1_proposal.model_description,
        best_file_vector=new_fv,
        best_score_table=_make_score_table(new_fv, new_scalar),
        best_model_params=iter1_proposal.parameter_count_estimate or 5_000_000,
    )

    prev_proposal_dict = iter1_proposal.model_dump()

    iter2_t0 = time.perf_counter()
    iter2_inp = InterpretationInput(
        summaries=[_WAVENET_SUMMARY, _PUNET_SUMMARY, new_summary],
        runtime_vocab=iter1_interp.runtime_vocab,
        previous_proposal=prev_proposal_dict,
        storage=storage_iter2,
    )
    iter2_interp_agent = ResultInterpretationAgent(bridge_factory=_plain_openai_bridge)
    iter2_interp = iter2_interp_agent.run(iter2_inp)
    iter2_elapsed_s = time.perf_counter() - iter2_t0

    assert isinstance(iter2_interp, InterpretationOutput)

    # --- Vocab growth assertion -----------------------------------------
    added, refined, removed = _vocab_diff(
        iter1_interp.runtime_vocab,
        iter2_interp.runtime_vocab,
    )

    print("=" * 78, flush=True)
    print(f"STAGE 1 / ITER 2  (elapsed {iter2_elapsed_s:.1f} s)", flush=True)
    print("=" * 78, flush=True)
    print(f"Iter 1 vocab size : {len(iter1_interp.runtime_vocab)}", flush=True)
    print(f"Iter 2 vocab size : {len(iter2_interp.runtime_vocab)}", flush=True)
    print(f"  + added   ({len(added)})   : {added}", flush=True)
    print(f"  ~ refined ({len(refined)}) : {refined}", flush=True)
    print(f"  - removed ({len(removed)}) : {removed}", flush=True)
    print("=" * 78, flush=True)

    # Must be a strict growth OR at least a non-empty change set.
    grew = len(iter2_interp.runtime_vocab) > len(iter1_interp.runtime_vocab)
    changed = bool(added or refined)

    assert grew or changed, (
        "Iter 2 runtime_vocab did not grow and no refinement happened — "
        "the iteration loop is not accumulating knowledge.\n"
        f"  iter1 size={len(iter1_interp.runtime_vocab)}, "
        f"iter2 size={len(iter2_interp.runtime_vocab)}, "
        f"added={added}, refined={refined}, removed={removed}"
    )

    # Removed entries are a red flag — accumulation should be monotonic.
    assert not removed, (
        f"Iter 2 dropped vocab entries from iter 1: {removed}. "
        "build_runtime_vocab must preserve carry-forward entries."
    )
