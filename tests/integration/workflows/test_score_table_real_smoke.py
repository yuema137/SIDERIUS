"""
Phase 6.5 Stage 2 — real-training semantic smoke for aggregated score-table
awareness (docs/aggregated_score_table_awareness.md §Phase 6.5).

Stage 1 (test_score_table_pseudo_smoke.py) verified the *brain* — that the
LLM proposer actually cites the attached ScoreComparisonTable numerics when
asked. This test verifies the *body* — that under realistic resource use
(real training, real eval, real GPU), the score-table-carrying workflow
does not exceed the tight single-node budgets we have for lilab.

Exercises two chained iterations of the real run_workflow:
  iter_001: seeds = punet + wavenet small_sample_trial_v0
  iter_002: seeds + iter_001 output

Under:
  - OpenAI routing (per memory feedback_prefer_openai_for_smoke.md):
      tuner planner    = gpt-5-mini  (reasoning-heavy)
      all others       = gpt-4o-mini (cheap + stable)
  - Trial  time budget = 60 s
  - Formal time budget = 1200 s (20 min)
  - max_rounds=2 per iter (one trial + one forced formal)

Instrumentation:
  - torch.cuda.reset_peak_memory_stats() at iter entry
  - torch.cuda.max_memory_allocated() at iter exit → peak VRAM
  - Per-phase wall clock from ExperimentRecord.timing (train/infer/score)
  - Split trial vs formal via ExperimentRecord.is_trial

Gate assertions (per user directive):
  * peak_vram > 32 GB             → FAIL  (OOM)
  * peak_vram > 22 GB             → WARN  ("High Pressure")
  * formal total (from timing)>1200s → FAIL  (launch gate too tight)
  * iter_001 best_score_table empty  → FAIL  (data integrity)

Run with:
  .venv/bin/python -m pytest -m real_run \\
      tests/integration/workflows/test_score_table_real_smoke.py -v -s

DO NOT run in CI — needs real GPU and real OpenAI keys.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

try:
    from execute_tools.data_paths import SIDERIUS_DATA_DIR, TIDMAD_DATA_DIR
except (FileNotFoundError, ImportError):
    TIDMAD_DATA_DIR = "/home/klz/Data/TIDMAD/"
    SIDERIUS_DATA_DIR = "/home/klz/Data/SIDEREIS_DATA/"

SOURCE_RUN_NAME = "small_sample_trial_v0"
SOURCE_MODELS = ["punet", "wavenet"]
ANCHOR_MAP_PATH = os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json")


# ---------------------------------------------------------------------------
# Gate thresholds (user directive)
# ---------------------------------------------------------------------------

VRAM_WARN_GB = 22.0  # >22 GB → "High Pressure"
VRAM_FAIL_GB = 32.0  # >32 GB → OOM
FORMAL_TIME_FAIL_S = 1200.0  # 20 min

TRIAL_BUDGET_MIN = 15.0  # 900 s — see Phase Q in docs/resource_estimator_implement.md.
# At trial_portion=0.02 + seg=1250 the PSD micro-segment
# expansion (PSD_SEGMENT_LENGTH//seg = 8000) yields
# ~32k steps/epoch, so the floor is ~7 min for any
# architecture. 1 min was unachievable; 15 min lets
# plausible drafts pass while still gating obvious bloat.
FORMAL_BUDGET_MIN = 20.0  # 1200 s


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------


def _skip_if_no_key():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


def _skip_if_no_data():
    if not os.path.isdir(TIDMAD_DATA_DIR):
        pytest.skip(f"TIDMAD data not found at {TIDMAD_DATA_DIR}")
    if not os.path.isdir(SIDERIUS_DATA_DIR):
        pytest.skip(f"SIDERIUS data not found at {SIDERIUS_DATA_DIR}")


def _skip_if_no_anchor_map():
    if not os.path.exists(ANCHOR_MAP_PATH):
        pytest.skip(f"segment_anchors.json not found at {ANCHOR_MAP_PATH}")


def _skip_if_no_tuning_outputs():
    for model in SOURCE_MODELS:
        path = os.path.join(
            SIDERIUS_DATA_DIR,
            model,
            SOURCE_RUN_NAME,
            "agent",
            f"run_output_{SOURCE_RUN_NAME}_agent.json",
        )
        if not os.path.exists(path):
            pytest.skip(f"Tuning output not found: {path}")


def _skip_if_no_cuda():
    import torch

    if not torch.cuda.is_available():
        pytest.skip("CUDA GPU not available")


# ---------------------------------------------------------------------------
# Report dataclass + helpers
# ---------------------------------------------------------------------------


@dataclass
class IterReport:
    iter_num: int
    model_type: str
    wallclock_s: float
    peak_vram_gb: float
    trial_train_s: float
    trial_infer_s: float
    trial_score_s: float
    formal_train_s: float
    formal_infer_s: float
    formal_score_s: float
    best_score: float | None
    best_table_ok: bool
    statuses: list[str]  # collected fail/warn flags

    @property
    def trial_total_s(self) -> float:
        return self.trial_train_s + self.trial_infer_s + self.trial_score_s

    @property
    def formal_total_s(self) -> float:
        return self.formal_train_s + self.formal_infer_s + self.formal_score_s

    @property
    def status(self) -> str:
        if not self.statuses:
            return "OK"
        return " | ".join(self.statuses)


def _extract_timings(tune_output) -> dict:
    """Sum per-phase wall times across trial/formal records."""
    t = {
        "trial_train": 0.0,
        "trial_infer": 0.0,
        "trial_score": 0.0,
        "formal_train": 0.0,
        "formal_infer": 0.0,
        "formal_score": 0.0,
    }
    for rec in tune_output.all_records:
        if rec.timing is None:
            continue
        prefix = "trial" if rec.is_trial else "formal"
        t[f"{prefix}_train"] += rec.timing.train_time_s or 0.0
        t[f"{prefix}_infer"] += rec.timing.inference_time_s or 0.0
        t[f"{prefix}_score"] += rec.timing.scoring_time_s or 0.0
    return t


def _best_table_non_empty(tune_output) -> bool:
    """True iff best_score_table is present with non-empty rendered_markdown."""
    tbl = getattr(tune_output, "best_score_table", None)
    if tbl is None:
        return False
    md = getattr(tbl, "rendered_markdown", None) or ""
    return len(md.strip()) > 0


def _apply_gates(report: IterReport) -> None:
    """Populate report.statuses in place based on the four user-directed gates."""
    if report.peak_vram_gb > VRAM_FAIL_GB:
        report.statuses.append(f"FAIL: OOM ({report.peak_vram_gb:.1f} GB > {VRAM_FAIL_GB})")
    elif report.peak_vram_gb > VRAM_WARN_GB:
        report.statuses.append(f"WARN: High Pressure ({report.peak_vram_gb:.1f} GB)")
    if report.formal_total_s > FORMAL_TIME_FAIL_S:
        report.statuses.append(
            f"FAIL: formal timeout ({report.formal_total_s:.1f}s > {FORMAL_TIME_FAIL_S:.0f}s)"
        )
    if not report.best_table_ok:
        report.statuses.append("FAIL: best_score_table empty")


def _print_report_table(reports: list[IterReport]) -> None:
    """Print the user's requested table:
    Iter # | Trial Time | Formal Time | Peak VRAM | Status
    """
    print()
    print("=" * 92)
    print("PHASE 6.5 STAGE 2 — REAL-TRAINING SMOKE REPORT")
    print("=" * 92)
    header = f"{'Iter':>4} | {'Trial Time':>12} | {'Formal Time':>12} | {'Peak VRAM':>10} | Status"
    print(header)
    print("-" * len(header))
    for r in reports:
        print(
            f"{r.iter_num:>4} | "
            f"{r.trial_total_s:>10.1f}s | "
            f"{r.formal_total_s:>10.1f}s | "
            f"{r.peak_vram_gb:>7.2f} GB | "
            f"{r.status}"
        )
    print("-" * len(header))
    # Extra breakdown (debug): show the train/infer/score split per iter
    print()
    print("Per-phase breakdown (seconds):")
    sub_hdr = (
        f"{'Iter':>4} | {'Model':>14} | "
        f"{'T-train':>8} {'T-infer':>8} {'T-score':>8} | "
        f"{'F-train':>8} {'F-infer':>8} {'F-score':>8} | "
        f"{'Wall':>8} | {'BestScore':>10}"
    )
    print(sub_hdr)
    print("-" * len(sub_hdr))
    for r in reports:
        bs = "n/a" if r.best_score is None else f"{r.best_score:.4f}"
        print(
            f"{r.iter_num:>4} | {r.model_type[:14]:>14} | "
            f"{r.trial_train_s:>8.1f} {r.trial_infer_s:>8.1f} {r.trial_score_s:>8.1f} | "
            f"{r.formal_train_s:>8.1f} {r.formal_infer_s:>8.1f} {r.formal_score_s:>8.1f} | "
            f"{r.wallclock_s:>8.1f} | {bs:>10}"
        )
    print("=" * 92)
    print()


def _build_llm_config():
    """
    Load the production tiered LLM config — the same JSON used by the
    V8/V9 chain runs (``llm_configs/openai_tiered_v1.json``).

    Earlier versions of this test pinned everything except the tuner
    planner to ``gpt-4o-mini``. Gate 2 run-3 showed that mini-class
    models cannot reliably do shape arithmetic for dilated/causal
    convolutions: the implementor failed 9/9 attempts in iter 1, all
    on off-by-(k-1) padding/trim mistakes. Production runs use the
    tiered config, which routes the reasoning-heavy slots (interpret,
    propose.reasoning, propose.proposing, implement, tune.planner) to
    a frontier model and keeps cheaper models only for templated
    extraction (validate, propose.comparison, tune.reflector). Testing
    with a strictly weaker model than production was producing
    failures that could never reproduce in real chains.
    """
    from pathlib import Path

    from workflows.llm_config import WorkflowLLMConfig

    repo_root = Path(__file__).resolve().parents[3]
    cfg_path = repo_root / "llm_configs" / "openai_tiered_v1.json"
    return WorkflowLLMConfig.from_json(str(cfg_path))


def _load_shared_advice() -> dict:
    """Reuse the tiny-model advice from the chained-iterations test."""
    advice_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "sdsc_submission_scripts",
        "human_advice_chain_test.json",
    )
    with open(advice_path, encoding="utf-8") as f:
        d = json.load(f)
    return {
        k: (d.get(k, "") or "") for k in ("interpret", "propose", "implement", "validate", "tune")
    }


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


class TestScoreTableRealSmoke:
    def setup_method(self):
        _skip_if_no_key()
        _skip_if_no_data()
        _skip_if_no_anchor_map()
        _skip_if_no_cuda()
        _skip_if_no_tuning_outputs()

    def test_two_iterations_under_budget(self, tmp_path):
        """2 chained iterations; gates on VRAM, formal time, and score-table integrity."""
        import torch

        from workflows.model_exploration import run_workflow

        workspace = str(tmp_path / "stage2_smoke")
        os.makedirs(workspace, exist_ok=True)

        llm_config = _build_llm_config()
        advice = _load_shared_advice()

        seed_paths = [
            os.path.join(
                SIDERIUS_DATA_DIR,
                model,
                SOURCE_RUN_NAME,
                "agent",
                f"run_output_{SOURCE_RUN_NAME}_agent.json",
            )
            for model in SOURCE_MODELS
        ]

        print(f"\n{'=' * 72}")
        print("  PHASE 6.5 STAGE 2 — REAL-TRAINING SMOKE")
        print(f"  Workspace: {workspace}")
        print("  LLM: OpenAI tiered (llm_configs/openai_tiered_v1.json — production config)")
        print(
            f"  Trial budget: {TRIAL_BUDGET_MIN * 60:.0f}s | "
            f"Formal budget: {FORMAL_BUDGET_MIN * 60:.0f}s"
        )
        print(f"  VRAM warn>{VRAM_WARN_GB}GB, fail>{VRAM_FAIL_GB}GB")
        print(f"{'=' * 72}\n")

        reports: list[IterReport] = []
        registered_models: list[str] = []

        try:
            # ================================================================
            # ITERATION 1
            # ================================================================
            print(f"\n{'#' * 72}")
            print(f"# ITERATION 1 — seeds only ({len(seed_paths)} files)")
            print(f"{'#' * 72}\n")

            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            t0 = time.perf_counter()

            results_1 = run_workflow(
                source_paths=seed_paths,
                workspace=workspace,
                run_name="stage2_iter_001",
                llm_config=llm_config,
                max_iterations=1,
                max_rounds=2,  # 1 trial + 1 forced formal
                max_proposal_attempts=3,
                is_trial=True,
                trial_strategy="snapshot",
                trial_portion=0.02,
                train_portion=1.0,
                eval_strategy="snapshot",
                eval_portion=0.02,
                cleanup_denoised=True,
                max_epochs=1,
                trial_time_budget_minutes=TRIAL_BUDGET_MIN,
                formal_time_budget_minutes=FORMAL_BUDGET_MIN,
                trial_vram_budget_gb=2.0,
                formal_vram_budget_gb=2.0,
                # Phase R (§13) — formal eval scope tightened for the smoke
                # test so the forced formal round fits inside FORMAL_BUDGET_MIN.
                # Production runs keep the 1.0 default; lowering this here
                # reflects a scope decision, not a calibration fix. The V9
                # audit (§13) showed the inference estimator under-projects
                # by ~8x on 5090 hardware, so silencing the formula by
                # touching its constants would defeat the gate. Matching
                # the trial eval_portion=0.02 keeps cross-architecture
                # comparability at smoke-test scope.
                formal_eval_portion=0.05,
                **{f"human_advice_{k}": v for k, v in advice.items()},
            )

            wall1 = time.perf_counter() - t0
            peak1_gb = torch.cuda.max_memory_allocated() / (1024**3)

            assert len(results_1) == 1, (
                f"Iteration 1 must produce exactly one tuning output "
                f"(got {len(results_1)}). Check the validation logs."
            )
            tune1 = results_1[0]
            iter1_model = tune1.model_type
            registered_models.append(iter1_model)

            t1 = _extract_timings(tune1)
            report1 = IterReport(
                iter_num=1,
                model_type=iter1_model,
                wallclock_s=wall1,
                peak_vram_gb=peak1_gb,
                trial_train_s=t1["trial_train"],
                trial_infer_s=t1["trial_infer"],
                trial_score_s=t1["trial_score"],
                formal_train_s=t1["formal_train"],
                formal_infer_s=t1["formal_infer"],
                formal_score_s=t1["formal_score"],
                best_score=tune1.best_denoising_score,
                best_table_ok=_best_table_non_empty(tune1),
                statuses=[],
            )
            _apply_gates(report1)
            reports.append(report1)

            iter1_output_path = os.path.join(
                workspace,
                "stage2_iter_001",
                "iteration_001",
                iter1_model,
                "run_output_stage2_iter_001.json",
            )
            assert os.path.exists(iter1_output_path), (
                f"Iteration 1 output not found at expected path: {iter1_output_path}"
            )

            print(
                f"\n[ITER 1 DONE] model={iter1_model} "
                f"wall={wall1:.1f}s peak_vram={peak1_gb:.2f}GB "
                f"best_score={tune1.best_denoising_score} "
                f"best_table_ok={report1.best_table_ok}"
            )

            # ================================================================
            # ITERATION 2
            # ================================================================
            iter2_sources = [*seed_paths, iter1_output_path]
            print(f"\n{'#' * 72}")
            print(f"# ITERATION 2 — seeds + iter_001 ({len(iter2_sources)} files)")
            print(f"{'#' * 72}\n")

            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            t0 = time.perf_counter()

            results_2 = run_workflow(
                source_paths=iter2_sources,
                workspace=workspace,
                run_name="stage2_iter_002",
                llm_config=llm_config,
                max_iterations=1,
                max_rounds=2,
                max_proposal_attempts=3,
                is_trial=True,
                trial_strategy="snapshot",
                trial_portion=0.02,
                train_portion=1.0,
                eval_strategy="snapshot",
                eval_portion=0.02,
                cleanup_denoised=True,
                max_epochs=1,
                trial_time_budget_minutes=TRIAL_BUDGET_MIN,
                formal_time_budget_minutes=FORMAL_BUDGET_MIN,
                trial_vram_budget_gb=2.0,
                formal_vram_budget_gb=2.0,
                # Phase R (§13) — formal eval scope tightened for the smoke
                # test so the forced formal round fits inside FORMAL_BUDGET_MIN.
                # Production runs keep the 1.0 default; lowering this here
                # reflects a scope decision, not a calibration fix. The V9
                # audit (§13) showed the inference estimator under-projects
                # by ~8x on 5090 hardware, so silencing the formula by
                # touching its constants would defeat the gate. Matching
                # the trial eval_portion=0.02 keeps cross-architecture
                # comparability at smoke-test scope.
                formal_eval_portion=0.05,
                **{f"human_advice_{k}": v for k, v in advice.items()},
            )

            wall2 = time.perf_counter() - t0
            peak2_gb = torch.cuda.max_memory_allocated() / (1024**3)

            assert len(results_2) == 1, (
                f"Iteration 2 must produce exactly one tuning output (got {len(results_2)})."
            )
            tune2 = results_2[0]
            iter2_model = tune2.model_type
            registered_models.append(iter2_model)

            t2 = _extract_timings(tune2)
            report2 = IterReport(
                iter_num=2,
                model_type=iter2_model,
                wallclock_s=wall2,
                peak_vram_gb=peak2_gb,
                trial_train_s=t2["trial_train"],
                trial_infer_s=t2["trial_infer"],
                trial_score_s=t2["trial_score"],
                formal_train_s=t2["formal_train"],
                formal_infer_s=t2["formal_infer"],
                formal_score_s=t2["formal_score"],
                best_score=tune2.best_denoising_score,
                best_table_ok=_best_table_non_empty(tune2),
                statuses=[],
            )
            _apply_gates(report2)
            reports.append(report2)

            print(
                f"\n[ITER 2 DONE] model={iter2_model} "
                f"wall={wall2:.1f}s peak_vram={peak2_gb:.2f}GB "
                f"best_score={tune2.best_denoising_score} "
                f"best_table_ok={report2.best_table_ok}"
            )

            # ================================================================
            # FINAL REPORT + HARD GATE ASSERTIONS
            # ================================================================
            _print_report_table(reports)

            # Hard gate: data integrity after Round 1 (user directive)
            assert report1.best_table_ok, (
                "DATA INTEGRITY FAIL: iteration 1's best_score_table is empty — "
                "the score-table contract broke during a real training run. "
                "Check ml_hyperparameter_tune_agent.py / scoring pipeline."
            )

            # Hard gate: no iteration busts the formal-time budget (user directive)
            for r in reports:
                assert r.formal_total_s <= FORMAL_TIME_FAIL_S, (
                    f"FORMAL TIMEOUT FAIL: iter {r.iter_num} formal phase "
                    f"took {r.formal_total_s:.1f}s > {FORMAL_TIME_FAIL_S:.0f}s budget — "
                    f"the launch gate is too tight for this hardware."
                )

            # Hard gate: no iteration OOMs (>32 GB — impossible on 32GB cards but
            # kept as a spec-faithful guard)
            for r in reports:
                assert r.peak_vram_gb <= VRAM_FAIL_GB, (
                    f"OOM FAIL: iter {r.iter_num} peak VRAM {r.peak_vram_gb:.2f} GB "
                    f"> {VRAM_FAIL_GB} GB."
                )

            # Surface warnings but do not fail the test on "High Pressure"
            high_pressure = [r for r in reports if any("WARN" in s for s in r.statuses)]
            if high_pressure:
                print(
                    "\n[WARNING] High VRAM pressure detected on "
                    + ", ".join(
                        f"iter {r.iter_num} ({r.peak_vram_gb:.2f} GB)" for r in high_pressure
                    )
                    + ". Headroom is thin on 24 GB cards — consider tightening budgets."
                )

            print("\n[PHASE 6.5 STAGE 2 PASSED] — score-table body holds under real training.\n")

        finally:
            # Clean up registered plugins (copied into repo-level agent_generated/models/
            # by legacy paths; new workflow uses run-scoped, but defensively clean both)
            for model_name in registered_models:
                plugin_file = os.path.join("agent_generated", "models", f"{model_name}.py")
                plugin_desc_dir = os.path.join("agent_generated", "models", model_name)
                if os.path.exists(plugin_file):
                    try:
                        os.remove(plugin_file)
                        print(f"  [CLEANUP] removed {plugin_file}")
                    except OSError:
                        pass
                if os.path.isdir(plugin_desc_dir):
                    try:
                        shutil.rmtree(plugin_desc_dir)
                        print(f"  [CLEANUP] removed {plugin_desc_dir}/")
                    except OSError:
                        pass
