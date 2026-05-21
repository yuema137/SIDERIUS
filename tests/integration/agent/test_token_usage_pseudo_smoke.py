"""Gate T0 — pseudo-training cognitive plumbing harness.

The cheapest gate in the Phase 1.5 ladder (see ``docs/audit_and_optimize_
token_usage_and_growth.md`` §1.5.0). T0 catches label-coverage / 10-key
components-math / ``template_and_scaffolding`` accounting regressions on
the *real* OpenAI surface — without spinning up a GPU or paying for a full
workflow loop. If a commit breaks the bridge's audit invariants, T0 fails
in tens of seconds rather than 10 minutes into T1.

Setup
-----
- Real OpenAI ``gpt-4o-mini`` for both ResultInterpretationAgent and
  MLModelProposalAgent (memory ``feedback_prefer_openai_for_smoke``).
- Pseudo "training": synthetic ``ModelRunSummary`` fixtures with a
  hand-tuned ``ScoreComparisonTable`` attached. No GPU, no subprocess.
- 2 iterations driven directly through ``agent.run()`` — sufficient to
  exercise the bridge ``_iter_flush`` boundary and the cross-iter
  protocol hand-off.

Assertions (all four match §1.5.0 success metrics)
--------------------------------------------------
1. **Zero unlabeled** — every row in ``token_usage.jsonl`` has
   ``label != "unlabeled"`` (marker rows ``label == "_iter_flush"`` are
   the only sanctioned non-stage-call labels).
2. **10-key precision** — for every proposer row,
   ``len(components) == 10`` AND
   ``sum(components.values()) == chars.total`` exactly. This pins the
   Commit 4.2 invariant on a clean LLM surface.
3. **Catch-all non-negative** — ``components["template_and_scaffolding"]
   >= 0`` on every proposer row. The bridge's ``max(0, …)`` clamp must
   never fire; if it does, the audit hook is over-counting.
4. **prior_stage_outputs monotonic across iters** — within each iter the
   3 stages (comparison → causal_reasoning → proposing) produce
   monotonically non-decreasing ``prior_stage_outputs`` char counts, and
   the *same* monotonic shape holds in iter 2 — proving the in-iter
   chain works AND survives the iter boundary.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timezone
from pathlib import Path

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

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.real_run

_OPENAI_MODEL = "gpt-4o-mini"
_RAW_BASELINE = 0.2
_GROUND_TRUTH = 9.5


# ---------------------------------------------------------------------------
# Score-table factory — same shape as test_score_table_pseudo_smoke.py.
# ---------------------------------------------------------------------------


def _make_score_table(fv: list[float], model_scalar: float) -> ScoreComparisonTable:
    raw = [_RAW_BASELINE] * 20
    gt = [_GROUND_TRUTH] * 20
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=raw[i],
            ground_truth=gt[i],
            model=v,
            gain_vs_raw=v - raw[i],
            headroom_vs_gt=gt[i] - v,
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
        reference_source="t0_pseudo_fixture",
        rendered_markdown="",
    )
    return table.model_copy(update={"rendered_markdown": render_comparison_table(table)})


_WAVENET_FV = [
    0.05,
    0.08,
    0.12,
    0.15,
    0.18,
    4.20,
    4.80,
    5.30,
    5.70,
    6.10,
    6.40,
    7.00,
    7.40,
    7.80,
    8.10,
    8.30,
    8.50,
    8.70,
    8.90,
    9.00,
]
_WAVENET_SCALAR = 5.58

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
_PUNET_SCALAR = 2.35


_WAVENET_SUMMARY = ModelRunSummary(
    model_type="wavenet",
    run_name="t0_seed",
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
        "Causal dilated-conv stack with residual + skip connections. Strong "
        "on mid/high frequencies; weak on the lowest-frequency files."
    ),
    best_file_vector=_WAVENET_FV,
    best_score_table=_make_score_table(_WAVENET_FV, _WAVENET_SCALAR),
    best_model_params=4_123_456,
)


_PUNET_SUMMARY = ModelRunSummary(
    model_type="punet",
    run_name="t0_seed",
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
        "Flat recovery across the spectrum.",
        "Marginal gain saturates well below wavenet SOTA.",
    ],
    model_description=(
        "Positional U-Net with sinusoidal positional encoding. Uniform "
        "capacity allocation — no per-band specialisation."
    ),
    best_file_vector=_PUNET_FV,
    best_score_table=_make_score_table(_PUNET_FV, _PUNET_SCALAR),
    best_model_params=2_900_000,
)


# ---------------------------------------------------------------------------
# Recording bridge — accepts the full keyword surface the agents use.
# ---------------------------------------------------------------------------


class RecordingOpenAIBridge(LLMBridge):
    """Real-OpenAI bridge that also captures (method, label, response).

    The reference subclass in ``test_score_table_pseudo_smoke.py`` only takes
    positional ``(system_prompt, user_prompt)``. The proposer and interp
    agents now pass ``label=`` and ``components=`` as keyword-only — so we
    accept ``**kwargs`` and forward them transparently. Anything else goes
    through ``LLMBridge``'s real OpenAI client.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls: list = []

    def generate(self, system_prompt, user_prompt, **kwargs):
        resp = super().generate(system_prompt, user_prompt, **kwargs)
        self.calls.append(("generate", kwargs.get("label"), resp))
        return resp

    def generate_text(self, system_prompt, user_prompt, **kwargs):
        resp = super().generate_text(system_prompt, user_prompt, **kwargs)
        self.calls.append(("generate_text", kwargs.get("label"), resp))
        return resp


def _make_recording_factory() -> tuple[list, callable]:
    shared: list = []

    def factory(**ignored) -> RecordingOpenAIBridge:
        bridge = RecordingOpenAIBridge(
            provider="openai",
            model_id=_OPENAI_MODEL,
            max_retries=3,
        )
        bridge.calls = shared
        return bridge

    return shared, factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bind(agent, *, workspace: Path, iter_idx: int, run_name: str, run_id: str) -> None:
    agent.bridge.set_run_context(
        workspace=workspace,
        iter=iter_idx,
        run_name=run_name,
        run_id=run_id,
    )


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@pytest.mark.real_run
def test_t0_cognitive_plumbing(tmp_path, capsys):
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — skipping Gate T0")

    run_name = "t0_pseudo_smoke"
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    run_id = f"{run_name}-{ts}-{os.getpid()}"

    storage_iter1 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name=f"{run_name}_iter1"),
    )
    storage_iter2 = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name=f"{run_name}_iter2"),
    )

    _interp_calls, interp_factory = _make_recording_factory()
    _propose_calls, propose_factory = _make_recording_factory()

    interp_agent = ResultInterpretationAgent(bridge_factory=interp_factory)
    propose_agent = MLModelProposalAgent(bridge_factory=propose_factory)

    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
        model_selection=ModelSelectionStrategy(method="top_n", params={"n": 2}),
    )

    # ===================================================================
    # Iter 1 — bind, interpret, propose
    # ===================================================================
    _bind(interp_agent, workspace=tmp_path, iter_idx=1, run_name=run_name, run_id=run_id)
    _bind(propose_agent, workspace=tmp_path, iter_idx=1, run_name=run_name, run_id=run_id)

    iter1_t0 = time.perf_counter()

    iter1_inp = InterpretationInput(
        summaries=[_WAVENET_SUMMARY, _PUNET_SUMMARY],
        runtime_vocab=[],
        previous_proposal=None,
        storage=storage_iter1,
    )
    iter1_interp = interp_agent.run(iter1_inp)
    assert isinstance(iter1_interp, InterpretationOutput)

    iter1_propose_inp = local_full_context(
        iter1_interp,
        storage_iter1,
        reasoning_pipeline=pipeline,
    )
    iter1_proposal = propose_agent.run(iter1_propose_inp)
    assert isinstance(iter1_proposal, ProposalOutput)

    iter1_elapsed = time.perf_counter() - iter1_t0

    # ===================================================================
    # Iter 2 — bind (triggers _iter_flush for iter 1), feed iter 1 forward
    # ===================================================================
    _bind(interp_agent, workspace=tmp_path, iter_idx=2, run_name=run_name, run_id=run_id)
    _bind(propose_agent, workspace=tmp_path, iter_idx=2, run_name=run_name, run_id=run_id)

    iter2_t0 = time.perf_counter()

    new_fv = [
        0.50,
        0.80,
        1.20,
        1.60,
        2.00,
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
        run_name="t0_iter2",
        status="completed",
        completed_rounds=2,
        best_denoising_score=new_scalar,
        worst_denoising_score=5.70,
        best_config=iter1_proposal.baseline_config,
        round_scores=[5.70, new_scalar],
        round_conclusions=[
            "Iter-2 round 1 — parity with wavenet.",
            "Iter-2 round 2 — low-freq band recovers.",
        ],
        model_description=iter1_proposal.model_description,
        best_file_vector=new_fv,
        best_score_table=_make_score_table(new_fv, new_scalar),
        best_model_params=iter1_proposal.parameter_count_estimate or 5_000_000,
    )

    iter2_inp = InterpretationInput(
        summaries=[new_summary],
        model_knowledge_cache=iter1_interp.model_knowledge_cache,
        runtime_vocab=iter1_interp.runtime_vocab,
        previous_proposal=iter1_proposal.model_dump(),
        storage=storage_iter2,
    )
    iter2_interp = interp_agent.run(iter2_inp)
    assert isinstance(iter2_interp, InterpretationOutput)

    iter2_propose_inp = local_full_context(
        iter2_interp,
        storage_iter2,
        reasoning_pipeline=pipeline,
    )
    iter2_proposal = propose_agent.run(iter2_propose_inp)
    assert isinstance(iter2_proposal, ProposalOutput)

    iter2_elapsed = time.perf_counter() - iter2_t0

    # ===================================================================
    # Read the audit log and assert
    # ===================================================================
    log_path = tmp_path / "token_usage.jsonl"
    assert log_path.exists(), f"token_usage.jsonl not produced at {log_path}"
    rows = _read_rows(log_path)

    # ---- Assertion 1: zero unlabeled ---------------------------------
    unlabeled = [r for r in rows if r.get("label") == "unlabeled"]
    assert not unlabeled, (
        f"Found {len(unlabeled)} unlabeled rows — every call site must pass "
        f"an explicit label. Sample row: {unlabeled[0] if unlabeled else None}"
    )

    # ---- Assertion 2 + 3: proposer row 10-key precision + clamp ------
    proposer_rows = [
        r for r in rows if isinstance(r.get("label"), str) and r["label"].startswith("proposer.")
    ]
    assert len(proposer_rows) >= 6, (
        f"Expected >= 6 proposer rows (3 stages × 2 iters), got "
        f"{len(proposer_rows)}. Labels: {[r['label'] for r in proposer_rows]}"
    )

    for r in proposer_rows:
        comps = r["components"]
        chars_total = r["chars"]["total"]
        delta = chars_total - sum(comps.values())
        assert len(comps) == 10, (
            f"Proposer row {r['label']!r} iter={r.get('iter')} has "
            f"{len(comps)} component keys (expected 10): {list(comps)}"
        )
        assert "template_and_scaffolding" in comps, (
            f"Proposer row {r['label']!r} iter={r.get('iter')} missing "
            f"the catch-all key 'template_and_scaffolding': {list(comps)}"
        )
        assert delta == 0, (
            f"C4.2 invariant violated on row {r['label']!r} iter="
            f"{r.get('iter')}: chars.total={chars_total} - "
            f"sum(components)={sum(comps.values())} = Δ{delta} "
            f"(expected 0)."
        )
        assert comps["template_and_scaffolding"] >= 0, (
            f"template_and_scaffolding negative on row {r['label']!r}: "
            f"{comps['template_and_scaffolding']} — the audit hook is "
            f"over-counting and the bridge had to clamp."
        )

    # ---- Assertion 4: prior_stage_outputs monotonic across iters -----
    # Order = JSONL append order = call-time order (rows are append-only).
    # Pipeline mode order: comparison → causal_reasoning → proposing.
    iter1_proposer = [r for r in proposer_rows if r.get("iter") == 1]
    iter2_proposer = [r for r in proposer_rows if r.get("iter") == 2]
    assert iter1_proposer and iter2_proposer, (
        f"Need proposer rows from both iters. Got iter1={len(iter1_proposer)} "
        f"iter2={len(iter2_proposer)}."
    )
    iter1_pso = [r["components"]["prior_stage_outputs"] for r in iter1_proposer]
    iter2_pso = [r["components"]["prior_stage_outputs"] for r in iter2_proposer]

    assert iter1_pso == sorted(iter1_pso), (
        f"iter1 prior_stage_outputs not monotonically non-decreasing across "
        f"stages: {iter1_pso}. The within-iter chain (comparison → "
        f"causal_reasoning → proposing) is not accumulating prior outputs."
    )
    assert iter2_pso == sorted(iter2_pso), (
        f"iter2 prior_stage_outputs not monotonically non-decreasing across "
        f"stages: {iter2_pso}. The chain hand-off survived the iter "
        f"boundary on iter 1 (asserted above) but breaks in iter 2 — "
        f"likely a bridge / accumulator state leak."
    )
    # Strict growth from stage 1 → last stage in each iter (later stages
    # see more accumulated context than the first stage).
    assert iter1_pso[-1] > iter1_pso[0], (
        f"iter1 prior_stage_outputs flat across stages: {iter1_pso}. "
        f"Stages are not feeding their outputs into the accumulator."
    )
    assert iter2_pso[-1] > iter2_pso[0], (
        f"iter2 prior_stage_outputs flat across stages: {iter2_pso}. "
        f"Stages are not feeding their outputs into the accumulator."
    )

    # ===================================================================
    # Report (visible with -s)
    # ===================================================================
    print("\n" + "=" * 78, flush=True)
    print("GATE T0 — COGNITIVE PLUMBING (REAL LLM + PSEUDO TRAINING)", flush=True)
    print("=" * 78, flush=True)
    print(f"Total rows         : {len(rows)}", flush=True)
    print(
        f"Proposer rows      : {len(proposer_rows)} "
        f"(iter1={len(iter1_proposer)}, iter2={len(iter2_proposer)})",
        flush=True,
    )
    print(
        f"_iter_flush rows   : {sum(1 for r in rows if r.get('label') == '_iter_flush')}",
        flush=True,
    )
    print(f"unlabeled rows     : {len(unlabeled)}  (must be 0)", flush=True)
    print(f"iter1 elapsed      : {iter1_elapsed:.1f} s", flush=True)
    print(f"iter2 elapsed      : {iter2_elapsed:.1f} s", flush=True)
    print(f"iter1 proposed     : {iter1_proposal.model_name}", flush=True)
    print(f"iter2 proposed     : {iter2_proposal.model_name}", flush=True)
    print(f"iter1 prior_stage_outputs progression: {iter1_pso}", flush=True)
    print(f"iter2 prior_stage_outputs progression: {iter2_pso}", flush=True)
    print("-" * 78, flush=True)
    print("Per-proposer-row Δ (chars.total - sum(components)):", flush=True)
    for r in proposer_rows:
        d = r["chars"]["total"] - sum(r["components"].values())
        ts_key = (r.get("iter"), r.get("label"))
        print(
            f"  iter={ts_key[0]} {ts_key[1]:<32} Δ={d:+d}  "
            f"chars.total={r['chars']['total']}  "
            f"tns={r['components']['template_and_scaffolding']}",
            flush=True,
        )
    print("=" * 78, flush=True)
