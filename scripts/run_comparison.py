#!/usr/bin/env python3
"""
run_comparison.py — Compare baseline vs agent-assisted exploration for a given TIDMAD model.

Phases:
  1. Baseline: Train/infer/score using exact legacy configs from the TIDMAD paper.
               Computed ONCE per model and reused across all run_names — auto-skipped
               if already present.
  2. Seed:     Pre-populate the agent's summary.json with the baseline result so the
               agent knows what benchmark it must beat from round 1.
  3. Agent:    Launch nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py for --max_rounds exploration rounds, locked to
               the same model type but free to vary config, loss, and train hparams.

Output structure:
  /home/klz/Data/SIDEREIS_DATA/
  └── {model}/
      ├── baseline/          ← shared baseline workspace (computed once)
      └── {run_name}/
          └── agent/         ← isolated agent workspace per run_name

Usage:
  python scripts/run_comparison.py --model punet
  python scripts/run_comparison.py --model punet --run_name v2 --max_rounds 50
  python scripts/run_comparison.py --model rnn --provider openai --model_id gpt-4o
"""

import argparse
import glob
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import UTC
from typing import cast

from core.campaign_artifacts import (
    decide_phase1_reuse,
    sha256_file,
    validate_phase1_baseline,
    write_campaign_manifest,
)
from core.run_invariants import (
    build_run_invariants,
    ensure_run_invariants,
    load_run_invariants,
    validate_run_invariants,
    validate_stamped_invariants,
)
from core.sandbox_executor import LocalRecorder, TidmadSandbox, sandbox_records_dir
from execute_tools.build_anchor_map import load_anchor_map
from execute_tools.data_paths import (
    SIDERIUS_DATA_DIR,
    TIDMAD_DATA_DIR,
    DatasetDirectoryUnavailable,
    resolve_dataset_dir,
)
from execute_tools.dataset_config import NUM_FILES, TIDMAD, DataScope, resolve_dataset_profile
from execute_tools.deliverable_spec import default_deliverable_naming
from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.evaluation import evaluate_and_persist_health_gates
from execute_tools.health_checks.schemas import GateAction, HealthCheckContext
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_utils import score_vector

SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DATA_DIR = SIDERIUS_DATA_DIR
DATA_DIR = TIDMAD_DATA_DIR
LEGACY_CONFIGS_PATH = os.path.join(SIDERIUS_ROOT, "ml_models", "legacy_baseline_configs.json")
HEALTH_CHECKS_PATH = os.path.join(SIDERIUS_ROOT, "configs", "health_checks.yaml")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_diagnostic_metadata(
    model_type, run_name, run_dir, baseline_workspace, baseline_record, baseline_retrained
):
    """Write the reproducibility snapshot for a diagnostic pre-v17 run."""
    import torch

    anchor_path = os.path.join(DATA_DIR, "segment_anchors.json")
    anchor_data = load_anchor_map(anchor_path)
    dataset_files = sorted(
        glob.glob(os.path.join(DATA_DIR, "abra_training_????.h5"))
        + glob.glob(os.path.join(DATA_DIR, "abra_validation_????.h5"))
    )
    try:
        driver = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version,name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        driver = None
    payload = {
        "run_name": run_name,
        "run_class": "diagnostic_pre_v17",
        "objective": "current_siderius_workflow_diagnostics",
        "paper_reproduction": False,
        "model": model_type,
        "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=SIDERIUS_ROOT, text=True
        ).strip(),
        "exact_command": [sys.executable, *sys.argv],
        "siderius_training_configuration": baseline_record.get("params", {}),
        "scorer": {
            "implementation": "execute_tools/scoring_utils.py::score_vector",
            "threshold_policy": "noise <= 1e-10 -> invalid; no epsilon and no denominator floor",
        },
        "anchor_map": {
            "path": anchor_path,
            "sha256": _sha256(anchor_path),
            "s_max": anchor_data["s_max"],
        },
        "healthgate": {"path": HEALTH_CHECKS_PATH, "sha256": _sha256(HEALTH_CHECKS_PATH)},
        "dataset_inventory": [
            {"path": p, "size_bytes": os.path.getsize(p), "mtime_ns": os.stat(p).st_mtime_ns}
            for p in dataset_files
        ],
        "runtime": {
            "python": sys.version,
            "pytorch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "driver_query": driver,
        },
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "finished_at": None,
        "output_path": os.path.abspath(run_dir),
        "baseline_source": "new_diagnostic_artifact"
        if baseline_retrained
        else "reused_existing_artifact",
        "baseline_checkpoint_path": baseline_record.get("checkpoint_path"),
        "baseline_workspace": os.path.abspath(baseline_workspace),
        "baseline_retrained": baseline_retrained,
        "inference_reused": False,
        "rescored_with_current_scorer": True,
        "healthgate_rerun": True,
    }
    path = os.path.join(run_dir, "run_metadata.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def _agent_env() -> dict:
    """
    Build a subprocess environment with all SIDERIUS paths on PYTHONPATH
    so that flat imports in nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py, train_engine_sandbox.py, etc. resolve.
    """
    extra = [
        SIDERIUS_ROOT,
        os.path.join(SIDERIUS_ROOT, "ml_models"),
        os.path.join(SIDERIUS_ROOT, "execute_tools"),
    ]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(extra + ([existing] if existing else []))
    return env


# ==========================================
# Phase 1: Baseline
# ==========================================


def run_baseline(
    model_type: str, baseline_workspace: str, progress_bar: bool = False, file_index: int = 6
) -> dict:
    """
    Runs the full pipeline (train -> inference -> score) with the exact legacy config
    from the TIDMAD paper. Returns the final record dict.
    """
    with open(LEGACY_CONFIGS_PATH) as f:
        legacy = json.load(f)

    if model_type not in legacy:
        raise ValueError(
            f"No legacy config found for model '{model_type}' in {LEGACY_CONFIGS_PATH}"
        )

    cfg = legacy[model_type]
    m_cfg = cfg["model_cfg"]
    t_cfg = cfg["train_cfg"]
    l_cfg = cfg["loss_cfg"]

    run_name = f"baseline_{model_type}"
    exp_id = f"baseline_{model_type}_{int(time.time())}"

    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=run_name,
        workspace=baseline_workspace,
        progress_bar=progress_bar,
        file_index=file_index,
    )

    print(f"\n{'=' * 60}")
    print(f"  PHASE 1 — BASELINE: {model_type.upper()}")
    print(f"{'=' * 60}")
    print(f"  model_cfg  : {m_cfg}")
    print(f"  train_cfg  : {t_cfg}")
    print(f"  loss_cfg   : {l_cfg}")
    print()

    # --- Train ---
    t0 = time.time()
    train_result = sandbox.execute_training(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        t_cfg=t_cfg,
        l_cfg=l_cfg,
    )
    train_time = round(time.time() - t0, 1)
    if train_result["status"] != "success":
        raise RuntimeError(f"Baseline training failed:\n{train_result.get('message')}")

    # --- Inference ---
    t0 = time.time()
    inf_result = sandbox.execute_inference(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        l_cfg=l_cfg,
    )
    inference_time = round(time.time() - t0, 1)
    if inf_result["status"] != "success":
        raise RuntimeError(f"Baseline inference failed:\n{inf_result.get('message')}")

    # --- Score ---
    t0 = time.time()
    score_result = sandbox.execute_scoring(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        t_cfg=t_cfg,
        l_cfg=l_cfg,
    )
    scoring_time = round(time.time() - t0, 1)
    if score_result["status"] != "success":
        raise RuntimeError(f"Baseline scoring failed:\n{score_result.get('message')}")

    # Extract results from each stage. Cast required because the executor's
    # untyped return dict mixes str (status/message) and dict (results), so
    # pyright cannot narrow the value at the `results` key. Runtime safety is
    # guaranteed by the `status != "success"` gates above.
    train_res = cast(dict, train_result.get("results", {}))
    score_res = cast(dict, score_result.get("results", {}))

    record = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": file_index,
        "params": {
            "exp_id": exp_id,
            "run_name": run_name,
            "model_type": model_type,
            "model_config": m_cfg,
            "train_config": t_cfg,
            "loss_config": l_cfg,
        },
        "final_loss": train_res.get("final_loss"),
        "loss_history": train_res.get("loss_history"),
        "model_params": train_res.get("model_params"),
        "denoising_score": score_res.get("denoising_score"),
        "timing": {
            "train_time_s": train_time,
            "inference_time_s": inference_time,
            "scoring_time_s": scoring_time,
        },
        "memory": {
            "expert_advice_followed": "Legacy TIDMAD paper baseline — no agent involvement.",
            "hypothesis": "Original hardcoded baseline configuration from the TIDMAD paper.",
            "conclusion": (
                f"Baseline {model_type.upper()} achieved "
                f"denoising_score={score_res.get('denoising_score', 'N/A')}."
            ),
            "discovery": (
                "This is the paper's reference result. All subsequent agent experiments "
                "should aim to surpass this benchmark."
            ),
            "memory_update": (
                f"Baseline {model_type.upper()} performance established. "
                f"Score: {score_res.get('denoising_score', 'N/A')}. "
                "Use this as the minimum target for improvement."
            ),
        },
    }

    sandbox.save_record(record)
    print(f"\n  Baseline complete. Denoising score: {score_res.get('denoising_score', 'N/A')}")
    return record


def run_baseline_trial(
    model_type: str,
    baseline_workspace: str,
    progress_bar: bool = False,
    max_epochs: int = 1,
    health_checks_config: str | None = None,
    campaign_run_name: str | None = None,
    existing_record: dict | None = None,
    data_scope: DataScope | None = None,
    health_gate_enabled: bool = True,
    health_config_sha256: str | None = None,
) -> dict:
    """
    Runs baseline with the TIDMAD paper config using the trial pipeline:
    - Training: all 20 files, train_portion=0.1 (subsampled per epoch),
      streamed via run_experiment_streaming
    - Inference: all 20 files, all segments
    - Scoring: anchor-normalized score_vector (parallel)

    No LLM call — config is hardcoded from legacy_baseline_configs.json.
    Produces scores on the same anchor-normalized scale as agent trial/formal runs.
    """
    with open(LEGACY_CONFIGS_PATH) as f:
        legacy = json.load(f)

    if model_type not in legacy:
        raise ValueError(
            f"No legacy config found for model '{model_type}' in {LEGACY_CONFIGS_PATH}"
        )

    cfg = legacy[model_type]
    m_cfg = cfg["model_cfg"]
    t_cfg = cfg["train_cfg"]
    l_cfg = cfg["loss_cfg"]

    run_name = (
        str((existing_record.get("params") or {}).get("run_name"))
        if existing_record
        else f"baseline_{model_type}"
    )
    exp_id = (
        str(existing_record["exp_id"])
        if existing_record
        else f"baseline_{model_type}_{int(time.time())}"
    )

    # Override epochs to 1 per paper authors (direct communication).
    t_cfg = dict(t_cfg)
    t_cfg["epochs"] = max_epochs

    # DS6d — scoped baselines: sample sets are built within the scope and the
    # sandbox boundary enforces it before any file I/O.
    scope = data_scope if data_scope is not None else DataScope.default()
    resolved_scope = scope.resolve(NUM_FILES)

    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=run_name,
        workspace=baseline_workspace,
        progress_bar=progress_bar,
        file_index=6,  # unused in trial mode but required by TidmadSandbox
        data_scope=scope,
    )

    print(f"\n{'=' * 60}")
    print(f"  PHASE 1 — BASELINE (trial pipeline): {model_type.upper()}")
    print(f"{'=' * 60}")
    print(f"  model_cfg   : {m_cfg}")
    print(f"  train_cfg   : {t_cfg}")
    print(f"  loss_cfg    : {l_cfg}")
    print(f"  train scope : files {resolved_scope}, portion=1.0, train_portion=0.1/epoch")
    print(f"  eval scope  : files {resolved_scope}, all segments")
    print()

    # Build SampleSets — full coverage of the scope, deterministic seed
    train_sample_set = build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=1.0,
        seed=0,
        scope=scope,
    )
    eval_sample_set = build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=1.0,
        seed=0,
        scope=scope,
    )

    # --- Train (streaming, all 20 files, 10% subsample/epoch) ---
    if existing_record is None:
        t0 = time.time()
        train_result = sandbox.execute_training(
            exp_id=exp_id,
            run_name=run_name,
            model_type=model_type,
            m_cfg=m_cfg,
            t_cfg=t_cfg,
            l_cfg=l_cfg,
            sample_set=train_sample_set,
            train_portion=0.1,
            train_base_seed=42,
        )
        train_time = round(time.time() - t0, 1)
        if train_result["status"] != "success":
            raise RuntimeError(f"Baseline training failed:\n{train_result.get('message')}")
    else:
        train_time = float((existing_record.get("timing") or {}).get("train_time_s") or 0.0)
        train_result = {
            "status": "success",
            "results": {
                "final_loss": existing_record.get("final_loss"),
                "loss_history": existing_record.get("loss_history"),
                "model_params": existing_record.get("model_params"),
            },
        }
        print("  [resume] Reusing validated Phase 1 checkpoint; regenerating inference/scoring.")

    # --- Inference (all 20 files, all segments) ---
    t0 = time.time()
    inf_result = sandbox.execute_inference(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        l_cfg=l_cfg,
        sample_set=eval_sample_set,
    )
    inference_time = round(time.time() - t0, 1)
    if inf_result["status"] != "success":
        raise RuntimeError(f"Baseline inference failed:\n{inf_result.get('message')}")

    # --- Score (anchor-normalized, parallel) ---
    t0 = time.time()
    anchor_map_path = os.path.join(DATA_DIR, "segment_anchors.json")
    anchor_data = load_anchor_map(anchor_map_path)

    def _denoised_fn(fi):
        return default_deliverable_naming().name(
            model_type=model_type, run_name=run_name, exp_id=exp_id, input_identity=fi
        )

    file_vector, final_scalar = score_vector(
        data_dir=baseline_workspace,
        sample_set=eval_sample_set,
        anchor_map=anchor_data["anchors"],
        s_max=anchor_data["s_max"],
        denoised_filename_fn=_denoised_fn,
        raw_data_dir=DATA_DIR,
    )
    scoring_time = round(time.time() - t0, 1)
    checkpoint_path = os.path.join(sandbox.dirs["models"], f"model_{model_type}_{exp_id}_agent.pth")
    health_context = HealthCheckContext(
        model_name=model_type,
        run_name=run_name,
        round_index=1,
        denoised_filename_fn=lambda fi: os.path.join(baseline_workspace, _denoised_fn(fi)),
        target_path_fn=lambda fi: os.path.join(DATA_DIR, f"abra_validation_{fi:04d}.h5"),
        checkpoint_path=checkpoint_path,
        file_vector=file_vector,
        denoising_score=final_scalar,
    )
    if health_gate_enabled:
        gate_results, persisted_gate_results, gate_action = evaluate_and_persist_health_gates(
            health_context,
            config_path=health_checks_config,
            production_config_path=HEALTH_CHECKS_PATH,
        )
    else:
        # DS6d — disabled mode mirrors the tuner: no evaluation, no
        # persistence; the record self-describes via health_gate_enabled.
        gate_results, persisted_gate_results, gate_action = [], [], GateAction.CONTINUE
    failed_gates = [result for result in gate_results if not result.passed]
    failure_reason = (
        " | ".join(f"[{result.gate_id}] {result.failure_reason}" for result in failed_gates) or None
    )

    # Extract training results. See run_baseline_single for the cast rationale.
    train_res = cast(dict, train_result.get("results", {}))

    record = {
        "exp_id": exp_id,
        "status": (
            "failed_mode_collapse"
            if any(item.would_invalidate_under_production_policy for item in persisted_gate_results)
            else "success"
        ),
        "campaign_run_name": campaign_run_name,
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": 6,
        "params": {
            "exp_id": exp_id,
            "run_name": run_name,
            "model_type": model_type,
            "model_config": m_cfg,
            "train_config": t_cfg,
            "loss_config": l_cfg,
        },
        "final_loss": train_res.get("final_loss"),
        "loss_history": train_res.get("loss_history"),
        "model_params": train_res.get("model_params"),
        "denoising_score": final_scalar,
        "file_vector": file_vector,
        "invalid_score_reason": (
            "score is missing or non-finite under the frozen scorer policy"
            if final_scalar is None or not math.isfinite(final_scalar)
            else None
        ),
        "file_vector_absence_reason": None
        if file_vector is not None
        else "scorer returned no vector",
        "failure_reason": failure_reason,
        "gate_action": gate_action.value,
        "health_gate_results": [item.model_dump(mode="json") for item in persisted_gate_results],
        "checkpoint_path": checkpoint_path,
        "checkpoint_sha256": sha256_file(checkpoint_path),
        # DS6d — invariant stamps (scalar comparability boundary).
        "resolved_data_scope": resolved_scope,
        "health_gate_enabled": health_gate_enabled,
        "health_config_sha256": health_config_sha256,
        "training_files": sorted(glob.glob(os.path.join(DATA_DIR, "abra_training_????.h5"))),
        "training_sample_set": train_sample_set,
        "evaluation_sample_set": eval_sample_set,
        "train_base_seed": 42,
        "is_trial": False,
        "trial_strategy": "snapshot",
        "trial_portion": 1.0,
        "train_portion": 0.1,
        "training_psd_segments": sum(len(v) for v in train_sample_set.values()),
        "eval_psd_segments": sum(len(v) for v in eval_sample_set.values()),
        "timing": {
            "train_time_s": train_time,
            "inference_time_s": inference_time,
            "scoring_time_s": scoring_time,
        },
        "memory": {
            "expert_advice_followed": "Legacy TIDMAD paper baseline — no agent involvement.",
            "hypothesis": "Original paper configuration with anchor-normalized scoring.",
            "conclusion": (
                f"Baseline {model_type.upper()} achieved "
                f"denoising_score={final_scalar:.4f} (anchor-normalized)."
            ),
            "discovery": (
                "This is the paper's reference result scored with anchor normalization. "
                "All subsequent agent experiments use the same scoring scale."
            ),
            "memory_update": (
                f"Baseline {model_type.upper()} performance established. "
                f"Anchor-normalized score: {final_scalar:.4f}. "
                "Use this as the minimum target for improvement."
            ),
        },
    }

    sandbox.save_record(record)
    print(f"\n  Baseline complete. Anchor-normalized score: {final_scalar:.4f}")
    print(f"  Timing: train={train_time}s, infer={inference_time}s, score={scoring_time}s")
    return record


# ==========================================
# Phase 2: Seed agent memory
# ==========================================


def seed_agent_memory(baseline_record: dict, agent_workspace: str, agent_run_name: str):
    """
    Writes the baseline record into the agent's memory so that on round 1 the
    agent immediately sees the benchmark it must beat.

    S2 / U5: routed through the SAME ``LocalRecorder`` the tuner opens on
    this workspace (``TidmadSandbox(workspace=agent_workspace,
    run_name=agent_run_name)`` builds the identical paths), so the baseline
    enters the canonical ``records/<run>/records.jsonl`` and the
    ``summary_<run>.json`` view is its projection. Writing the summary
    directly — as this function used to — put a record in the view that
    was in no history: the tuner's first save would have rebuilt the view
    from the log and the baseline would have vanished.

    Ordering preserved: in every production launch the agent workspace is
    fresh when seeded (``run_dir`` must be empty, ``--resume``, or
    ``--override_old_run``), so the baseline is the FIRST canonical record
    and therefore index 0 of the view — exactly where the old
    ``existing.insert(0, ...)`` put it. Re-seeding an already-seeded
    workspace is a no-op, as before. The one path that differs is a
    ``--resume`` of a workspace that already holds agent rounds under a
    DIFFERENT baseline id: the baseline is then appended (recorded in
    history order) rather than inserted at index 0. No reader depends on
    the index — the dashboard filters baseline records by ``exp_id``, and
    the tuner's resume counters key on the run-name prefix.
    """
    workspace = os.path.abspath(agent_workspace)
    os.makedirs(workspace, exist_ok=True)
    summary_path = os.path.join(workspace, f"summary_{agent_run_name}.json")
    recorder = LocalRecorder(sandbox_records_dir(workspace), summary_path, agent_run_name)

    already_seeded = any(
        r.get("exp_id") == baseline_record.get("exp_id") for r in recorder.get_summary()
    )
    if not already_seeded:
        recorder.save_record(baseline_record)
        print(f"\n  Agent memory seeded with baseline record → {summary_path}")
    else:
        print("\n  Agent memory already contains baseline record — skipping seed.")


# ==========================================
# Phase 3: Agent exploration
# ==========================================


PARTIAL_CAMPAIGN_EXIT_CODE = 2


def _read_tuner_completion(output_path: str, *, requested_rounds: int) -> tuple[bool, str]:
    """Return whether the persisted tuner result completed the request."""
    try:
        with open(output_path, encoding="utf-8") as f:
            result = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"tuner result unavailable or unreadable: {exc}"

    status = result.get("status")
    completed = result.get("completed_rounds")
    reason = result.get("termination_reason") or "unspecified"
    if status == "completed" and completed == requested_rounds:
        return True, f"{completed}/{requested_rounds} rounds completed"
    return (
        False,
        f"status={status}, {completed}/{requested_rounds} rounds completed, "
        f"termination_reason={reason}",
    )


def run_agent(
    model_type: str,
    agent_workspace: str,
    agent_run_name: str,
    provider: str,
    model_id: str,
    max_rounds: int,
    progress_bar: bool = False,
    file_index: int = 6,
    is_trial: bool = False,
    human_advice: str | None = None,
    cleanup_denoised: bool = False,
    reflect_provider: str | None = None,
    reflect_model_id: str | None = None,
    formal_strategy: str = "snapshot",
    formal_portion: float = 0.1,
    formal_train_portion: float = 1.0,
    # V19 PR 2 — agent-phase ordering override (baseline phase excluded).
    order_strategy_override: str | None = None,
    file_order_override: str | None = None,
    max_epochs: int | None = None,
    # D-BUD-6 — per-mode epoch ceilings (trial/formal split). None = the
    # mode-agnostic max_epochs governs that role (legacy behavior).
    trial_max_epochs: int | None = None,
    formal_max_epochs: int | None = None,
    trial_time_budget_minutes: float | None = None,
    formal_time_budget_minutes: float | None = None,
    health_checks_config: str | None = None,
    resume: bool = False,
    data_scope_spec: str | None = None,
    health_gate_enabled: bool = True,
    health_gate_files_spec: str | None = None,
    # Runtime-control operator surface (RT6, runtime design §4/§5). None →
    # tuner CLI defaults (§5 provisional operational values) apply.
    max_steps_per_attempt: int | None = None,
    min_formal_batch_size: int | None = None,
    allow_extreme_steps: bool = False,
    runtime_watchdog: bool = False,
    runtime_safety_factor: float | None = None,
    runtime_trial_safety_factor: float | None = None,
    runtime_formal_safety_factor: float | None = None,
    runtime_watchdog_floor_seconds: float | None = None,
    enable_chain_incumbent_formal_gates: bool = False,
    data_dir: str | None = None,
):
    """
    Launches nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py as a subprocess, locked to
    model_type, for max_rounds rounds.

    ``data_dir`` is the run's ALREADY-RESOLVED physical dataset root (C12-P).
    It is forwarded to the tuner verbatim; this function does not resolve it,
    because the resolution must happen once at the launch boundary before any
    expensive work — see ``main()``. ``None`` reproduces the pre-C12-P argv
    exactly, which is what every caller that has not been migrated still gets.

    DS6d: ``data_scope_spec`` / ``health_gate_files_spec`` are the operator's
    raw CLI spec strings, forwarded verbatim to the tuner's own
    ``--data_scope`` / ``--health_gate_files`` flags (the tuner parses and
    validates them itself — one parser, no drift).

    The tuner makes two distinct LLM calls per round (planner + reflector).
    By default both use the same provider+model. Pass `reflect_provider`
    and/or `reflect_model_id` to route the reflector to a different
    provider+model than the planner.
    """
    expert_advice = (
        "You should actively try different model configs, loss types and train configs, "
        "while not exceeding the limit of GPU memory. "
        "The baseline result is already in your memory — "
        "your goal is to find configurations that outperform it."
        "CRITICAL: We are using an RTX 5090 (32GB VRAM), the single model should not use more than 10GB VRAM, but you should try to verify batch size and segmentation to make the best usage of the 10GB limit"
    )

    cmd = [
        sys.executable,
        os.path.join(
            SIDERIUS_ROOT,
            "nodes",
            "ml_hyperparameter_tune_agent",
            "ml_hyperparameter_tune_agent.py",
        ),
        "--provider",
        provider,
        "--model_id",
        model_id,
        "--force_model",
        model_type,
        "--max_rounds",
        str(max_rounds),
        "--run_name",
        agent_run_name,
        "--workspace",
        agent_workspace,
        "--expert_advice",
        expert_advice,
    ]
    # C12-P: the physical dataset root, resolved ONCE at the launch boundary.
    #
    # Its absence is what blocked PR-12d's TIDMAD attempts 5 and 6. This
    # launcher never forwarded the value, so `agent_input.data_dir` reached the
    # tuner as None and TWO runtime-control consumers refused, fail-closed but
    # only after a real LLM had already produced a candidate:
    #   armed time budget    -> probe_production.py       "no dataset directory
    #                                                      was supplied"
    #   unarmed time budget  -> gpu_measurement_worker_main.py
    #                                                     "dataset directory
    #                                                      unavailable ...: None"
    # `sdsc_submission_scripts/run_one_iteration.py` already resolved and
    # forwarded it; this is the SAME authority applied at the second launch
    # boundary, never a second convention and never a default path.
    if data_dir:
        cmd.extend(["--data_dir", data_dir])
    if reflect_provider:
        cmd.extend(["--reflect_provider", reflect_provider])
    if reflect_model_id:
        cmd.extend(["--reflect_model_id", reflect_model_id])
    if is_trial:
        cmd.append("--is_trial")
    else:
        cmd.extend(["--file_index", str(file_index)])
    if human_advice:
        cmd.extend(["--human_advice", human_advice])
    if progress_bar:
        cmd.append("--progress_bar")
    if cleanup_denoised:
        cmd.append("--cleanup_denoised")
    # Phase M — formal-mode training levers (eval side locked in tuner)
    cmd.extend(["--formal_strategy", formal_strategy])
    cmd.extend(["--formal_portion", str(formal_portion)])
    cmd.extend(["--formal_train_portion", str(formal_train_portion)])
    # V19 PR 2 — forwarded only when set, so an unset override reproduces
    # the pre-V19 tuner argv exactly.
    if order_strategy_override is not None:
        cmd.extend(["--order_strategy_override", order_strategy_override])
    if file_order_override is not None:
        cmd.extend(["--file_order_override", file_order_override])
    # Epoch cap + wall-time budgets (forwarded when set; None → tuner defaults).
    if max_epochs is not None:
        cmd.extend(["--max_epochs", str(max_epochs)])
    # D-BUD-6 — per-mode epoch ceilings, forwarded only when set so an
    # unset pair reproduces the legacy tuner argv exactly.
    if trial_max_epochs is not None:
        cmd.extend(["--trial_max_epochs", str(trial_max_epochs)])
    if formal_max_epochs is not None:
        cmd.extend(["--formal_max_epochs", str(formal_max_epochs)])
    if trial_time_budget_minutes is not None:
        cmd.extend(["--trial_time_budget_minutes", str(trial_time_budget_minutes)])
    if formal_time_budget_minutes is not None:
        cmd.extend(["--formal_time_budget_minutes", str(formal_time_budget_minutes)])
    if health_checks_config:
        cmd.extend(["--health_checks_config", health_checks_config])
    # DS6d — DataScope + HealthGate subsystem forwarding.
    if data_scope_spec:
        cmd.extend(["--data_scope", data_scope_spec])
    if not health_gate_enabled:
        cmd.append("--no-health_gate_enabled")
    if health_gate_files_spec:
        cmd.extend(["--health_gate_files", health_gate_files_spec])
    # RT6 runtime-control surface: numeric flags forwarded only when the
    # operator set them (tuner CLI carries the §5 operational defaults);
    # booleans forwarded when set.
    if max_steps_per_attempt is not None:
        cmd.extend(["--max_steps_per_attempt", str(max_steps_per_attempt)])
    if min_formal_batch_size is not None:
        cmd.extend(["--min_formal_batch_size", str(min_formal_batch_size)])
    if allow_extreme_steps:
        cmd.append("--allow_extreme_steps")
    if runtime_watchdog:
        cmd.append("--runtime_watchdog")
    if runtime_safety_factor is not None:
        cmd.extend(["--runtime_safety_factor", str(runtime_safety_factor)])
    if runtime_trial_safety_factor is not None:
        cmd.extend(["--runtime_trial_safety_factor", str(runtime_trial_safety_factor)])
    if runtime_formal_safety_factor is not None:
        cmd.extend(["--runtime_formal_safety_factor", str(runtime_formal_safety_factor)])
    if runtime_watchdog_floor_seconds is not None:
        cmd.extend(["--runtime_watchdog_floor_seconds", str(runtime_watchdog_floor_seconds)])
    if enable_chain_incumbent_formal_gates:
        cmd.append("--enable_chain_incumbent_formal_gates")
    if resume:
        cmd.append("--resume")

    print(f"\n{'=' * 60}")
    print(f"  PHASE 3 — AGENT EXPLORATION: {model_type.upper()}")
    print(f"  Rounds:    {max_rounds}")
    print(f"  Workspace: {agent_workspace}")
    print(f"  Planner:   {provider} / {model_id}")
    if reflect_provider or reflect_model_id:
        eff_reflect_provider = reflect_provider or provider
        eff_reflect_model_id = reflect_model_id or model_id
        print(f"  Reflector: {eff_reflect_provider} / {eff_reflect_model_id}")
    else:
        print("  Reflector: (same as planner)")
    print(f"{'=' * 60}\n")

    child = subprocess.run(cmd, cwd=SIDERIUS_ROOT, env=_agent_env(), check=False)
    output_path = os.path.join(agent_workspace, f"run_output_{agent_run_name}.json")
    completed, detail = _read_tuner_completion(output_path, requested_rounds=max_rounds)
    if not completed:
        print(f"Comparison run ended partial: {detail}")
        raise SystemExit(PARTIAL_CAMPAIGN_EXIT_CODE)
    if child.returncode != 0:
        raise subprocess.CalledProcessError(child.returncode, cmd)
    print("Comparison run completed successfully.")


# ==========================================
# Entry point
# ==========================================


def main():
    parser = argparse.ArgumentParser(
        description="SIDERIUS: Compare baseline vs agent-assisted exploration for a TIDMAD model."
    )
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Model architecture to explore (any model in MODEL_REGISTRY or legacy_baseline_configs).",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="gemini",
        choices=["gemini", "openai"],
        help="LLM provider for the planner sub-call (default: gemini). "
        "Also the default for the reflector when --reflect_provider is unset.",
    )
    parser.add_argument(
        "--model_id",
        type=str,
        default="gemini-3.1-flash-lite-preview",
        help="Model ID for the planner sub-call (default: gemini-3.1-flash-lite-preview). "
        "Also the default for the reflector when --reflect_model_id is unset.",
    )
    parser.add_argument(
        "--reflect_provider",
        type=str,
        default=None,
        choices=["gemini", "openai"],
        help="Optional separate provider for the reflector sub-call. "
        "When unset, the reflector uses --provider. Set to a different "
        "vendor (e.g. 'openai') to route the reflector to an entirely "
        "different provider.",
    )
    parser.add_argument(
        "--reflect_model_id",
        type=str,
        default=None,
        help="Optional separate model for the reflector sub-call. "
        "When unset for the gemini provider, defaults to 'gemini-2.5-flash' "
        "(unlimited daily quota, GA model, well-suited for the templated "
        "reflection step). When unset for non-gemini providers, falls "
        "back to --model_id (legacy behavior).",
    )
    parser.add_argument(
        "--max_rounds",
        type=int,
        default=50,
        help="Number of agent exploration rounds (default: 50).",
    )
    parser.add_argument(
        "--progress_bar",
        action="store_true",
        help="Stream live tqdm progress bars from training/inference/scoring subprocesses.",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="v1",
        help=(
            "Name for this comparison run (default: v1). "
            "Use different names (e.g. 'test', 'v1', 'v2') to keep runs isolated. "
            "Agent results go to {ROOT_DATA_DIR}/{model}/{run_name}/agent/. "
            "Baseline is shared at {ROOT_DATA_DIR}/{model}/baseline/."
        ),
    )
    parser.add_argument(
        "--override_old_run",
        action="store_true",
        help=(
            "Delete any existing data for --run_name and start fresh. "
            "Without this flag the script will error if the run_name already exists."
        ),
    )
    parser.add_argument(
        "--file_index",
        type=int,
        default=6,
        help="Validation/training file index (default: 6). Ignored when --is_trial.",
    )
    parser.add_argument(
        "--is_trial",
        action="store_true",
        help="Enable trial-explore mode with multi-file sparse sampling.",
    )
    parser.add_argument(
        "--human_advice",
        type=str,
        default=None,
        help="Human guidance for the agent (free-form string, single value).",
    )
    parser.add_argument(
        "--human_advice_file",
        type=str,
        default=None,
        help=(
            "Path to a per-agent human advice JSON file. The file must contain a "
            "single key matching the agent receiving the advice — for the tuner, "
            'use {"tune": "..."}. Strict subset of the aggregated advice file '
            "format used at workflow/chain levels (which has all 5 agent keys). "
            "If both --human_advice and --human_advice_file are given, the file "
            "takes precedence."
        ),
    )
    parser.add_argument(
        "--cleanup_denoised",
        action="store_true",
        help="Delete denoised HDF5 files after scoring each round to save disk space.",
    )
    parser.add_argument(
        "--health_checks_config",
        type=str,
        default=None,
        help="Optional HealthGate YAML override; omitted preserves the default.",
    )
    # --- physical dataset root (C12-P) ---
    parser.add_argument(
        "--data_dir",
        type=str,
        default=None,
        help=(
            "Physical dataset root for this run. Optional: when omitted the "
            "machine-local tidmad_data_config.yaml supplies it, which is the "
            "precedence execute_tools.data_paths.resolve_dataset_dir already "
            "declares. Resolved and validated at launch and forwarded to the "
            "tuner; an unresolvable root refuses the launch rather than "
            "failing later inside runtime-control."
        ),
    )
    # --- DataScope + HealthGate subsystem (DS6d) ---
    parser.add_argument(
        "--data_scope",
        type=str,
        default=None,
        help=(
            "Restrict the campaign (baseline + agent) to a file subset: "
            "'4-9', '4,5,6,7,8,9', or mixed '0-3,7'. Omitted = complete "
            "dataset. Pinned per workspace by the run-invariants lock. "
            "See docs/design/enable_partial_file_list.md."
        ),
    )
    parser.add_argument(
        "--health_gate_enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "HealthGate subsystem switch for baseline gate evaluation and "
            "the agent phase (default: enabled)."
        ),
    )
    parser.add_argument(
        "--health_gate_files",
        type=str,
        default=None,
        help=(
            "Run-level shared monitored-file list for ALL HealthGate checks "
            "(same spec format as --data_scope). Omitted + full scope = YAML "
            "defaults; omitted + partial scope = startup error."
        ),
    )
    parser.add_argument(
        "--baseline_workspace",
        type=str,
        default=None,
        help="Optional isolated Phase 1 workspace; omitted preserves current defaults.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Validate and reuse same-campaign Phase 1 and completed rounds.",
    )
    # --- Formal-mode training levers (Phase M, docs §12) ---
    # Forwarded to the agent subprocess. Formal eval strategy is locked to
    # ``snapshot``; the portion defaults to 1.0 (production full-clone,
    # §12.2) and can be opted down via the agent CLI's
    # ``--formal_eval_portion`` (Phase R, §13) — not surfaced here because
    # this script is a baseline benchmark runner, not a chain entry point.
    parser.add_argument(
        "--formal_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="Training-side strategy on formal rounds (default snapshot).",
    )
    parser.add_argument(
        "--formal_portion",
        type=float,
        default=0.1,
        help="Fraction of segments per file for formal training scope (default 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion",
        type=float,
        default=1.0,
        help="Per-epoch iteration fraction for formal training (default 1.0).",
    )
    # V19 PR 2 — data-ordering OVERRIDE, forwarded to the agent phase only.
    # The BASELINE phase is deliberately excluded: it is the frozen
    # comparison anchor, so its training must stay on the pre-V19 global
    # shuffle regardless of what the agent phase is asked to do.
    parser.add_argument(
        "--order_strategy_override",
        type=str,
        default=None,
        choices=["shuffle", "sequential"],
        help="V19 PR 2: force the training sample visitation order for every "
        "agent-phase round, overriding any agent proposal. Unset (default) = "
        "the agent decides, falling back to 'shuffle'. Does NOT affect the "
        "baseline phase.",
    )
    parser.add_argument(
        "--file_order_override",
        type=str,
        default=None,
        help="V19 PR 2: comma-separated file visitation ORDER for "
        "--order_strategy_override sequential, e.g. '4,6,5,9,7,8'. Order is "
        "preserved as written; must be a full permutation of the resolved "
        "DataScope. Omit for ascending file index.",
    )
    parser.add_argument(
        "--max_epochs",
        type=int,
        default=None,
        help=(
            "Optional epoch cap for Phase 2/3 planner rounds. When omitted, "
            "the planner may choose epochs within the TrainConfig bounds. "
            "Phase 1 baseline remains fixed at 1 epoch per paper authors "
            "(direct communication). Per-mode overrides: --trial_max_epochs "
            "/ --formal_max_epochs take precedence for their round role "
            "(D-BUD-6)."
        ),
    )
    parser.add_argument(
        "--trial_max_epochs",
        type=int,
        default=None,
        help=(
            "TRIAL-role epoch ceiling for the tuner rounds (campaign "
            "decision D-BUD-6). Precedence for a trial round: this value -> "
            "--max_epochs -> no clamp; formal rounds never read it. Must be "
            ">= 1 (the tuner input schema refuses zero/negative loudly). "
            "The Phase 1 baseline is unaffected."
        ),
    )
    parser.add_argument(
        "--formal_max_epochs",
        type=int,
        default=None,
        help=(
            "FORMAL-role epoch ceiling for the tuner rounds (campaign "
            "decision D-BUD-6). Precedence for a formal round: this value -> "
            "--max_epochs -> no clamp; trial rounds never read it. Must be "
            ">= 1 (the tuner input schema refuses zero/negative loudly). "
            "The Phase 1 baseline is unaffected."
        ),
    )
    parser.add_argument(
        "--trial_time_budget_minutes",
        type=float,
        default=None,
        help=(
            "Forwarded to the tuner subprocess as --trial_time_budget_minutes "
            "when set. Wall-time cap per trial round. Default None = tuner "
            "default (no cap)."
        ),
    )
    parser.add_argument(
        "--formal_time_budget_minutes",
        type=float,
        default=None,
        help=(
            "Forwarded to the tuner subprocess as --formal_time_budget_minutes "
            "when set. Wall-time cap for the formal round. Default None = tuner "
            "default (no cap)."
        ),
    )
    # --- Runtime-control operator surface (RT6, runtime design §4/§5) ---
    parser.add_argument(
        "--max_steps_per_attempt",
        type=int,
        default=None,
        help="Forwarded to the tuner when set. §5 step guardrail; 0 disables. "
        "Default None = tuner default (150000, provisional §5 value).",
    )
    parser.add_argument(
        "--min_formal_batch_size",
        type=int,
        default=None,
        help="Forwarded to the tuner when set. §5 formal batch floor; 0 "
        "disables. Default None = tuner default (4, provisional §5 value).",
    )
    parser.add_argument(
        "--allow_extreme_steps",
        action="store_true",
        help="Forwarded to the tuner: §5 operator override bypassing both "
        "step/batch guardrails (recorded in provenance).",
    )
    parser.add_argument(
        "--runtime_watchdog",
        action="store_true",
        help="Forwarded to the tuner: enable the §4 runtime watchdog "
        "(process-group deadline kill on training/inference).",
    )
    parser.add_argument(
        "--runtime_safety_factor",
        type=float,
        default=None,
        help="Forwarded to the tuner when set. §2.10 safety multiplier; "
        "V18 production posture 1.5. Default None = tuner default (1.0).",
    )
    parser.add_argument(
        "--runtime_trial_safety_factor",
        type=float,
        default=None,
        help="Forwarded when set: phase-specific TRIAL factor (wins over "
        "--runtime_safety_factor for trials). V18 posture 2.0.",
    )
    parser.add_argument(
        "--runtime_formal_safety_factor",
        type=float,
        default=None,
        help="Forwarded when set: phase-specific FORMAL factor (wins over "
        "--runtime_safety_factor for formals).",
    )
    parser.add_argument(
        "--runtime_watchdog_floor_seconds",
        type=float,
        default=None,
        help="Forwarded to the tuner when set. §4 watchdog floor; V18 "
        "production posture 120. Default None = tuner default (60).",
    )
    parser.add_argument(
        "--enable_chain_incumbent_formal_gates",
        action="store_true",
        help="V19 PR 1: forwarded to the tuner — let the formal delta "
        "gates consume the chain-incumbent reference. Default OFF "
        "(consumption-only switch; rollback = omit).",
    )
    args = parser.parse_args()

    # DS6d — parse DataScope specs ('4-9' / '4,5,6,7,8,9' / mixed canonicalize
    # to one sorted deduplicated list).
    try:
        data_scope = DataScope.from_cli(args.data_scope) if args.data_scope else DataScope.default()
        health_gate_files = (
            DataScope.from_cli(args.health_gate_files).file_indices
            if args.health_gate_files
            else None
        )
    except ValueError as e:
        raise SystemExit(f"[ERROR] {e}") from e
    resolved_data_scope = data_scope.resolve(NUM_FILES)

    # DS6d — v17_pregate override pin: that campaign's policy file is the
    # contract; run-level HealthGate overrides are not allowed for it.
    if args.run_name == "v17_pregate_baseline" and (
        args.health_gate_files is not None or not args.health_gate_enabled
    ):
        raise SystemExit(
            "[ERROR] v17_pregate_baseline pins its HealthGate policy file: "
            "--health_gate_files / --no-health_gate_enabled are not allowed "
            "for this campaign."
        )

    # C12-P — resolve the physical dataset root ONCE, at the launch boundary,
    # through the same authority and precedence (explicit override >
    # machine-local config) that `sdsc_submission_scripts/run_one_iteration.py`
    # already applies. It FAILS CLOSED: an unresolvable root refuses here,
    # before any expensive work, rather than after a real LLM has generated and
    # registered a candidate — the cost PR-04a paid once and PR-12d's TIDMAD
    # attempts 5/6 paid again.
    #
    # ORDERED AFTER the pure-CLI validation above, deliberately. Those guards
    # decide whether the operator's FLAGS are well formed, which is knowable
    # with no machine configuration at all; this one asks whether the
    # ENVIRONMENT can supply a dataset. Resolving first made a malformed
    # `--data_scope` report a missing data directory instead, and made the
    # startup guards untestable anywhere without a per-machine config —
    # environment coupling in exactly the place the portability rule forbids it.
    #
    # No default, no synthetic directory, no task-name dispatch: the value
    # comes from the operator's override or the gitignored per-machine config,
    # and from nowhere else.
    try:
        resolved_data_dir = resolve_dataset_dir(args.data_dir, purpose="this comparison run")
    except DatasetDirectoryUnavailable as e:
        raise SystemExit(f"[ERROR] {e}") from e

    if args.health_checks_config:
        args.health_checks_config = os.path.abspath(args.health_checks_config)
        loaded_gate_config = load_health_gates_config(args.health_checks_config)
        if args.run_name == "v17_pregate_baseline":
            policy_errors = []
            for gate in loaded_gate_config.health_gates:
                if gate.after_round != "every":
                    policy_errors.append(f"{gate.id}: after_round must be 'every'")
                if (
                    gate.on_pass.action.value != "continue"
                    or gate.on_fail.action.value != "continue"
                ):
                    policy_errors.append(f"{gate.id}: pass/fail actions must both be continue")
            if policy_errors:
                raise SystemExit(
                    "[ERROR] v17_pregate_baseline requires observe-only every-round gates:\n- "
                    + "\n- ".join(policy_errors)
                )

    # --- Resolve reflect provider/model defaults ---
    # The reflector sub-call does templated extraction (not reasoning), so it
    # benefits from a faster/cheaper/higher-quota model than the planner. For
    # the gemini provider, default the reflector to gemini-2.5-flash (GA model,
    # unlimited daily quota, strong JSON-mode). For other providers, leave
    # unset = legacy behavior (reflector uses the planner's model).
    reflect_provider = args.reflect_provider
    reflect_model_id = args.reflect_model_id
    if reflect_model_id is None and reflect_provider is None and args.provider == "gemini":
        # Apply the gemini-specific default. Stays on the gemini provider.
        reflect_model_id = "gemini-2.5-flash"

    # --- Resolve human advice (file > CLI flag > None) ---
    human_advice: str = args.human_advice or ""
    if args.human_advice_file:
        if not os.path.exists(args.human_advice_file):
            raise SystemExit(f"\n[ERROR] --human_advice_file not found: {args.human_advice_file}")
        with open(args.human_advice_file, encoding="utf-8") as f:
            advice_blob = json.load(f)
        if not isinstance(advice_blob, dict) or "tune" not in advice_blob:
            raise SystemExit(
                f"\n[ERROR] Per-agent advice file for the tuner must contain a "
                f"'tune' key. Got keys: {list(advice_blob.keys()) if isinstance(advice_blob, dict) else type(advice_blob).__name__}"
            )
        human_advice = advice_blob["tune"] or ""
        print(f"  Loaded human advice from: {args.human_advice_file}")

    model_type = args.model
    model_root = os.path.join(ROOT_DATA_DIR, model_type)
    run_dir = os.path.join(model_root, args.run_name)
    # Trial and single-file baselines are on different scoring scales — keep separate
    baseline_subdir = (
        f"{args.run_name}_baseline_trial"
        if args.is_trial and args.run_name == "diagnostic_baseline_pre_v17"
        else ("baseline_trial" if args.is_trial else "baseline")
    )
    baseline_workspace = os.path.abspath(
        args.baseline_workspace or os.path.join(model_root, baseline_subdir)
    )
    agent_workspace = os.path.join(run_dir, "agent")
    agent_run_name = f"{args.run_name}_agent"

    # --- Guard: prevent accidental overwrite of existing run ---
    if os.path.exists(run_dir) and os.listdir(run_dir) and not args.resume:
        if not args.override_old_run:
            raise SystemExit(
                f"\n[ERROR] Run '{args.run_name}' already exists at:\n"
                f"  {run_dir}\n\n"
                f"Options:\n"
                f"  1. Use a different run name:\n"
                f"       --run_name <new_name>\n\n"
                f"  2. Manually delete the existing run and restart:\n"
                f"       rm -rf {run_dir}\n\n"
                f"  3. Let the script delete it automatically:\n"
                f"       --override_old_run"
            )
        else:
            import shutil

            shutil.rmtree(run_dir)
            print(f"  [override] Deleted existing run at: {run_dir}")

    os.makedirs(baseline_workspace, exist_ok=True)
    os.makedirs(agent_workspace, exist_ok=True)

    # --- DS6d — campaign invariants (materialize + hash BEFORE any phase) ---
    # The v17 pin above ran against the SOURCE config; from here on the
    # materialized effective config is the single path both baseline gate
    # evaluation and the agent subprocess read. Existing baseline history is
    # stamp-validated before a lock-less workspace is locked (never silently).
    run_invariants, _effective_health_config = build_run_invariants(
        resolved_data_scope=resolved_data_scope,
        health_gate_enabled=args.health_gate_enabled,
        health_gate_files=health_gate_files,
        health_checks_config=args.health_checks_config,
        workspace=baseline_workspace,
    )
    if _effective_health_config is not None:
        args.health_checks_config = _effective_health_config
    if load_run_invariants(baseline_workspace) is not None:
        validate_run_invariants(baseline_workspace, run_invariants)
    else:
        for _summary_path in glob.glob(os.path.join(baseline_workspace, "summary_*.json")):
            try:
                with open(_summary_path, encoding="utf-8") as _f:
                    _history = json.load(_f)
            except (OSError, json.JSONDecodeError):
                continue
            for _rec in _history:
                if _rec.get("status") in {"success", "failed_mode_collapse"}:
                    validate_stamped_invariants(
                        _rec,
                        run_invariants,
                        full_scope=list(range(TIDMAD.num_files)),
                        source=f"baseline summary record {_rec.get('exp_id')} ({_summary_path})",
                    )
    ensure_run_invariants(baseline_workspace, run_invariants)

    print(f"\n{'#' * 60}")
    print(f"  SIDERIUS Comparison Run — {model_type.upper()}")
    print(f"  Baseline  : {baseline_workspace}")
    print(f"  Agent     : {agent_workspace}")
    print(f"  Rounds    : {args.max_rounds}")
    print(f"{'#' * 60}")

    # --- Phase 1: Baseline (computed once, reused across all run_names) ---
    matches = glob.glob(os.path.join(baseline_workspace, "summary_*.json"))
    baseline_done = False
    baseline_needs_inference = False
    if matches and args.resume:
        try:
            with open(matches[0]) as f:
                history = json.load(f)
            if history:
                candidate = history[0]
                with open(LEGACY_CONFIGS_PATH, encoding="utf-8") as handle:
                    expected_source = json.load(handle)[model_type]
                expected_params = {
                    "model_config": expected_source["model_cfg"],
                    "train_config": {
                        **expected_source["train_cfg"],
                        "epochs": args.max_epochs if args.max_epochs is not None else 1,
                    },
                    "loss_config": expected_source["loss_cfg"],
                }
                exp_id = candidate.get("exp_id", "")
                baseline_run_name = (candidate.get("params") or {}).get(
                    "run_name", f"baseline_{model_type}"
                )
                expected_outputs = [
                    os.path.join(
                        baseline_workspace,
                        default_deliverable_naming().name(
                            model_type=model_type,
                            run_name=baseline_run_name,
                            exp_id=exp_id,
                            input_identity=i,
                        ),
                    )
                    for i in resolved_data_scope
                ]
                gate_ids = [
                    gate.id
                    for gate in load_health_gates_config(args.health_checks_config).health_gates
                    if gate.matches_round(1)
                ]
                decision = decide_phase1_reuse(
                    candidate,
                    campaign_name=args.run_name,
                    model_type=model_type,
                    expected_params=expected_params,
                    expected_training_files=sorted(
                        glob.glob(os.path.join(DATA_DIR, "abra_training_????.h5"))
                    ),
                    configured_gate_ids=gate_ids,
                    expected_output_paths=expected_outputs,
                    # Step 10 / P1 (S7) — the campaign script supplies the two
                    # task-semantic values; generic campaign code no longer
                    # resolves a profile or imports a dataset singleton.
                    declared_health_peek=resolve_dataset_profile().health_peek_files,
                    full_scope_num_files=TIDMAD.num_files,
                    expected_resolved_data_scope=resolved_data_scope,
                )
                validation = decision.validation
                if decision.action != "train":
                    assert validation is not None
                    baseline_record = candidate
                    baseline_done = decision.action == "reuse"
                    baseline_needs_inference = decision.action == "regenerate_inference"
                    print(
                        f"\n  Validated same-campaign Phase 1: {candidate.get('exp_id')} "
                        f"(missing outputs={len(validation.missing_inference_outputs)})."
                    )
                else:
                    print("\n  Phase 1 reuse rejected:")
                    for error in validation.errors if validation else ["no campaign record"]:
                        print(f"    - {error}")
        except (OSError, json.JSONDecodeError):
            pass
    elif matches and not args.baseline_workspace:
        # Backward-compatible legacy behavior: shared baseline workspaces are
        # still reused by existence when the new campaign options are omitted.
        try:
            with open(matches[0], encoding="utf-8") as handle:
                history = json.load(handle)
            if history:
                baseline_record = history[0]
                baseline_done = True
                print(
                    f"\n  Baseline already computed: {baseline_record.get('exp_id')} "
                    f"(score={baseline_record.get('denoising_score', 'N/A')}) — skipping."
                )
        except (OSError, json.JSONDecodeError):
            pass

    baseline_retrained = not baseline_done and not baseline_needs_inference
    if baseline_needs_inference:
        baseline_record = run_baseline_trial(
            model_type,
            baseline_workspace,
            progress_bar=args.progress_bar,
            max_epochs=(args.max_epochs if args.max_epochs is not None else 1),
            health_checks_config=args.health_checks_config,
            campaign_run_name=args.run_name,
            existing_record=baseline_record,
            data_scope=data_scope,
            health_gate_enabled=args.health_gate_enabled,
            health_config_sha256=run_invariants.health_config_sha256,
        )
    elif not baseline_done:
        if args.is_trial:
            baseline_record = run_baseline_trial(
                model_type,
                baseline_workspace,
                progress_bar=args.progress_bar,
                max_epochs=(args.max_epochs if args.max_epochs is not None else 1),
                health_checks_config=args.health_checks_config,
                campaign_run_name=args.run_name,
                data_scope=data_scope,
                health_gate_enabled=args.health_gate_enabled,
                health_config_sha256=run_invariants.health_config_sha256,
            )
        else:
            baseline_record = run_baseline(
                model_type,
                baseline_workspace,
                progress_bar=args.progress_bar,
                file_index=args.file_index,
            )

    if args.baseline_workspace:
        with open(LEGACY_CONFIGS_PATH, encoding="utf-8") as handle:
            expected_source = json.load(handle)[model_type]
        expected_params = {
            "model_config": expected_source["model_cfg"],
            "train_config": {
                **expected_source["train_cfg"],
                "epochs": args.max_epochs if args.max_epochs is not None else 1,
            },
            "loss_config": expected_source["loss_cfg"],
        }
        baseline_exp_id = baseline_record["exp_id"]
        baseline_run_name = (baseline_record.get("params") or {}).get(
            "run_name", f"baseline_{model_type}"
        )
        expected_outputs = [
            os.path.join(
                baseline_workspace,
                default_deliverable_naming().name(
                    model_type=model_type,
                    run_name=baseline_run_name,
                    exp_id=baseline_exp_id,
                    input_identity=i,
                ),
            )
            for i in resolved_data_scope
        ]
        gate_ids = [
            gate.id
            for gate in load_health_gates_config(args.health_checks_config).health_gates
            if gate.matches_round(1)
        ]
        validation = validate_phase1_baseline(
            baseline_record,
            campaign_name=args.run_name,
            model_type=model_type,
            expected_params=expected_params,
            expected_training_files=sorted(
                glob.glob(os.path.join(DATA_DIR, "abra_training_????.h5"))
            ),
            configured_gate_ids=gate_ids,
            expected_output_paths=expected_outputs,
            # Step 10 / P1 (S7) — the campaign SCRIPT knows which task it is
            # running and supplies the two task-semantic values explicitly.
            # Generic campaign code no longer reaches for a profile or a
            # dataset singleton of its own; this is the same "callers that
            # know the task supply those" contract the launcher already
            # follows for the measurement capability.
            declared_health_peek=resolve_dataset_profile().health_peek_files,
            full_scope_num_files=TIDMAD.num_files,
        )
        if not validation.valid or validation.missing_inference_outputs:
            problems = [
                *validation.errors,
                f"missing inference outputs: {validation.missing_inference_outputs}",
            ]
            raise RuntimeError(
                "Phase 1 completeness validation failed:\n- " + "\n- ".join(problems)
            )
        manifest_path = os.path.join(run_dir, "campaign_manifest.json")
        write_campaign_manifest(
            manifest_path,
            {
                "campaign_run_name": args.run_name,
                "model_type": model_type,
                # DS6d — functional campaign identity: scope + policy join
                # campaign_run_name; reuse decisions verify them explicitly.
                "resolved_data_scope": resolved_data_scope,
                "health_gate_enabled": args.health_gate_enabled,
                "health_config_sha256": run_invariants.health_config_sha256,
                "baseline": {
                    "workspace": baseline_workspace,
                    "record": os.path.join(
                        baseline_workspace,
                        "records",
                        baseline_run_name,
                        f"{baseline_exp_id}.json",
                    ),
                    "summary": matches[0]
                    if matches
                    else os.path.join(baseline_workspace, f"summary_{baseline_run_name}.json"),
                    "checkpoint": baseline_record["checkpoint_path"],
                    "checkpoint_sha256": baseline_record["checkpoint_sha256"],
                    "denoised_outputs": expected_outputs,
                    "health_gate_results": "embedded:baseline_record.health_gate_results",
                },
                "agent_workspace": agent_workspace,
                "threshold_review": os.path.join(run_dir, "threshold_review.json"),
                "health_checks_config": os.path.abspath(args.health_checks_config)
                if args.health_checks_config
                else HEALTH_CHECKS_PATH,
            },
        )
        print(f"  Campaign artifact manifest written: {manifest_path}")

    if args.run_name == "diagnostic_baseline_pre_v17":
        path = _write_diagnostic_metadata(
            model_type,
            args.run_name,
            run_dir,
            baseline_workspace,
            baseline_record,
            baseline_retrained,
        )
        print(f"  Diagnostic run metadata written: {path}")

    # --- Phase 2: Seed agent memory ---
    # DS6d — ingress validation at seeding time: the baseline record must
    # carry this campaign's invariants before it enters the agent's memory
    # (the tuner re-validates at consumption; failing here is earlier).
    validate_stamped_invariants(
        baseline_record,
        run_invariants,
        full_scope=list(range(TIDMAD.num_files)),
        source=f"baseline record {baseline_record.get('exp_id')}",
    )
    seed_agent_memory(baseline_record, agent_workspace, agent_run_name)

    # --- Write tuner-level run metadata before launching the agent ---
    from datetime import datetime

    from agent.schemas.hyperparam_tuning import ExpertAdvice
    from agent.schemas.run_metadata import (
        PerAgentAdvice,
        TunerRunMetadata,
        capture_env_info,
        capture_git_info,
        write_metadata,
    )

    # Legacy free-form preamble used by run_agent() — captured here so the
    # metadata snapshot reflects exactly what the tuner will see in its prompt.
    legacy_expert_preamble = (
        "You should actively try different model configs, loss types and train configs, "
        "while not exceeding the limit of GPU memory. "
        "The baseline result is already in your memory — "
        "your goal is to find configurations that outperform it."
        "CRITICAL: We are using an RTX 5090 (32GB VRAM), the single model should not use more than 10GB VRAM, but you should try to verify batch size and segmentation to make the best usage of the 10GB limit"
    )

    tuner_meta = TunerRunMetadata(
        run_name=agent_run_name,
        workspace=os.path.abspath(agent_workspace),
        started_at=datetime.now(UTC).isoformat(),
        git=capture_git_info(repo_root=SIDERIUS_ROOT),
        env=capture_env_info(),
        argv=list(sys.argv),
        advice={
            "tune": PerAgentAdvice(
                human=human_advice,
                expert=ExpertAdvice(freeform_notes=legacy_expert_preamble),
            ),
        },
        human_advice_file=args.human_advice_file,
        model_type=model_type,
        llm_provider=args.provider,
        llm_model_id=args.model_id,
        reflect_provider=reflect_provider,
        reflect_model_id=reflect_model_id,
        max_rounds=args.max_rounds,
        file_index=None if args.is_trial else args.file_index,
        is_trial=args.is_trial,
        baseline_score=baseline_record.get("denoising_score"),
    )
    metadata_path = os.path.join(agent_workspace, "tuner_run_metadata.json")
    write_metadata(tuner_meta, metadata_path)
    print(f"  Tuner run metadata written: {metadata_path}")

    # --- Phase 3: Agent exploration ---
    run_agent(
        model_type=model_type,
        agent_workspace=agent_workspace,
        agent_run_name=agent_run_name,
        provider=args.provider,
        model_id=args.model_id,
        reflect_provider=reflect_provider,
        reflect_model_id=reflect_model_id,
        max_rounds=args.max_rounds,
        progress_bar=args.progress_bar,
        file_index=args.file_index,
        is_trial=args.is_trial,
        human_advice=human_advice or None,
        cleanup_denoised=args.cleanup_denoised,
        formal_strategy=args.formal_strategy,
        formal_portion=args.formal_portion,
        formal_train_portion=args.formal_train_portion,
        order_strategy_override=args.order_strategy_override,
        file_order_override=args.file_order_override,
        max_epochs=args.max_epochs,
        trial_max_epochs=args.trial_max_epochs,
        formal_max_epochs=args.formal_max_epochs,
        trial_time_budget_minutes=args.trial_time_budget_minutes,
        formal_time_budget_minutes=args.formal_time_budget_minutes,
        health_checks_config=args.health_checks_config,
        resume=args.resume,
        data_scope_spec=args.data_scope,
        health_gate_enabled=args.health_gate_enabled,
        health_gate_files_spec=args.health_gate_files,
        max_steps_per_attempt=args.max_steps_per_attempt,
        min_formal_batch_size=args.min_formal_batch_size,
        allow_extreme_steps=args.allow_extreme_steps,
        runtime_watchdog=args.runtime_watchdog,
        runtime_safety_factor=args.runtime_safety_factor,
        runtime_trial_safety_factor=args.runtime_trial_safety_factor,
        runtime_formal_safety_factor=args.runtime_formal_safety_factor,
        runtime_watchdog_floor_seconds=args.runtime_watchdog_floor_seconds,
        enable_chain_incumbent_formal_gates=args.enable_chain_incumbent_formal_gates,
        data_dir=resolved_data_dir,
    )

    print(f"\n{'#' * 60}")
    print(f"  Comparison run complete for {model_type.upper()}")
    print(f"  Baseline results : {baseline_workspace}")
    print(f"  Agent results    : {agent_workspace}")
    print(f"{'#' * 60}\n")


if __name__ == "__main__":
    main()
