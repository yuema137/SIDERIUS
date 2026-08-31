"""
evaluate_time_skill/wrapper.py

Sum-time aggregator over the three execution phases. Estimates the
total wall-time a proposed experiment will take and checks it against
the per-mode time budget.

Call this BEFORE training to avoid burning the round on a config that
won't finish in time.

Aggregation (K.2.5):
  The three phases — training, inference, scoring — run *sequentially*
  (execute_training → execute_inference → execute_scoring). The total
  wall-time is the sum of each phase's seconds. This wrapper calls the
  three per-phase estimators and sums:

      training_skill/estimator.py:estimate_wall_time_seconds
      inference_skill/estimator.py:estimate_wall_time_seconds
      denoising_score_skill/estimator.py:estimate_wall_time_seconds

  Per-phase formulae live next to the code that actually executes each
  phase — see each estimator's docstring. This wrapper owns the
  warmup infrastructure (the real-dataset ms/step measurement that
  feeds the training + inference phases) and picks the sum.

Warmup -> per-phase ms/step derivation:
  * Training ms/step     = the measured warmup value (training estimator
                           applies k(gpu, model_type) + SAFETY_MULTIPLIER).
  * Inference ms/step    = measured training ms/step × 1/3 (no backward
                           pass). See inference_skill/estimator.py.
  * Scoring wall-time    = total_psd_segments × per_psd_segment_seconds /
                           num_workers, from core/server_configs/{hostname}.py.
  * Fallback: if warmup fails / no CUDA / no data_dir, each estimator
    falls back to its own static formula; static ms/step for training
    uses ``max(num_params × seg × bs × 3e-9, 2.0)``
    (breakdown.source == "static_uncalibrated"). Rev 4 contract: a
    static-backed estimate is stamped
    ``formal_execution_eligible: False`` — it is a preliminary risk
    screen, never the runtime prediction that admits a formal
    execution (enforcement wired in RT2/RT3).

Breakdown contract:
  The flat ``breakdown`` dict in the return preserves the pre-K.2.5
  keys that downstream callers depend on. In particular,
  ``nodes/ml_hyperparameter_tune_agent.py`` reads ``breakdown.source``
  and ``breakdown.gpu_name`` to decide when to trigger the Phase F
  per-GPU EMA update. The three-phase split is surfaced separately
  under ``phase_breakdown``.

See docs/resource_estimator_implement.md §10.5 / §10.14 Commit 6.
"""

from __future__ import annotations

import gc
import os
import statistics
import time
import traceback
from collections.abc import Sized
from typing import cast

from agent.skills.denoising_score_skill import estimator as _scoring_est
from agent.skills.inference_skill import estimator as _inference_est
from agent.skills.training_skill import estimator as _training_est
from execute_tools.dataset_config import (
    DatasetProfile,
    tidmad_topology,
)

# Phase 6.7 Fix 1 — fast-fail short-circuit for DOA models. If a single
# forward+backward+optimizer step at step 0 already takes ≥ this many ms,
# the model is hopelessly slow and we abort the warmup rather than burn
# the full warmup quota plus the configured safety margin on a config that the
# downstream time gate will reject anyway. The threshold is set high
# enough that a healthy first-step (cudnn autotune + cudaMalloc) on the
# largest seed model still completes well under it.
_WARMUP_FAST_FAIL_MS: float = 5000.0


# ── pure helpers (testable without torch) ────────────────────────────────────


def _suggest_lever(
    ms_per_step: float, seg_size: int, batch_size: int, psd_segment_length: int
) -> str:
    """Pick the dominant lever to recommend based on where time is going.

    Step 05b: ``psd_segment_length`` is supplied by the caller, which holds
    the run-bound profile. Reading it ambiently here meant the advice a run
    was given could name a decomposition length the run was not using.
    """
    if ms_per_step > 50.0:
        return (
            "Reduce model depth/width (num_blocks, hidden_channels, "
            "embedding_dim) — per-step cost is dominant."
        )
    if seg_size < 10_000 and batch_size == 1:
        return "Raise batch_size (amortises per-step cost without changing model capacity)."
    # Derived from the declared decomposition length, not hardcoded. Under
    # TIDMAD ``f"{10_000_000:,}"`` renders "10,000,000", so this advisory
    # string is byte-identical to the literal it replaces.
    return (
        f"Raise segmentation_size to the next valid divisor of {psd_segment_length:,} "
        "so fewer steps cover the same data."
    )


def _aggregate_warmup_timings(
    all_step_times_ms: list[float],
    n_warmup_batches: int,
    fast_fail_threshold_ms: float = _WARMUP_FAST_FAIL_MS,
) -> tuple[float | None, dict]:
    """Reduce raw per-step warmup timings into a single ms/step estimate.

    Two branches, in priority order:

      * **fast_fail** — step 0 already took ``≥ fast_fail_threshold_ms``.
        The model is DOA: a healthy first step (even with cudnn autotune
        + cudaMalloc on a large seed model) finishes well under the
        threshold, so anything above it is a clear signal the time gate
        will reject this config. Return that step's elapsed ms with
        ``aggregator='fast_fail'`` so the caller can short-circuit on a
        worst-case-conservative number.

      * **median** — discard the first ``n_warmup_batches`` steps
        (one-off cudnn autotune, cudaMalloc, lazy CUDA-graph capture) and
        return ``statistics.median`` of the remaining timed steps. Median
        is robust to a single rogue slow step (e.g. a kernel re-tune
        triggered by an unusual input shape).

    Returns ``(measured_ms_or_None, breakdown_dict)`` where the breakdown
    surfaces ``n_warmup_batches`` (the configured warmup count),
    ``n_timed_batches`` (actual steady-state samples used for the
    aggregate; 0 in the fast-fail branch), ``timings_ms`` (raw all-step
    list, copy), and ``aggregator`` ('median' / 'fast_fail' / None).
    """
    breakdown: dict = {
        "n_warmup_batches": n_warmup_batches,
        "n_timed_batches": 0,
        "timings_ms": list(all_step_times_ms),
        "aggregator": None,
    }

    if not all_step_times_ms:
        return None, breakdown

    # Fast-fail beats the median branch: a DOA step 0 means we never
    # collected meaningful steady-state samples, and we want the caller
    # to see a high ms/step number that will trip the time gate rather
    # than a tiny median over a near-empty post-warmup list.
    if all_step_times_ms[0] >= fast_fail_threshold_ms:
        breakdown["aggregator"] = "fast_fail"
        return all_step_times_ms[0], breakdown

    timed = all_step_times_ms[n_warmup_batches:]
    if not timed:
        # Loop terminated early (StopIteration before any timed step).
        # No aggregator runs — caller falls back to the static formula.
        return None, breakdown

    breakdown["n_timed_batches"] = len(timed)
    breakdown["aggregator"] = "median"
    return statistics.median(timed), breakdown


def _aggregate_inference_file_timings(
    per_file_timings_ms: list,
    warmup_fraction: float = 0.20,
) -> tuple[float | None, dict]:
    """Reduce raw per-file trial-mode inference timings into a single
    per-PSD-segment ms estimate, robust to warmup leak.

    Mirrors ``_aggregate_warmup_timings`` in spirit: discard a leading
    fraction of files (CUDA context init, cold-disk h5py read, lazy CUDA
    graph capture all leak into the first 1-2 files even though they're
    one-shot costs) and take the median of the remainder normalised per
    PSD segment.

    Per-PSD-segment normalisation matters because trial files are sampled
    sparsely — file 0 might carry 3 PSD segments, file 1 might carry 8 —
    and the raw elapsed_ms scales with the segment count. Normalising by
    ``n_psd_segs`` produces a unit cost the formal round can multiply
    back up by its own segment count.

    Args:
        per_file_timings_ms: List of dicts emitted by the trial-mode
            subprocess sidecar. Each dict carries
            ``{"file_index", "n_psd_segs", "elapsed_ms"}``. Defensive
            ``.get()`` is used on consumption so legacy or partial
            sidecars don't crash the aggregator.
        warmup_fraction: Fraction of leading files to discard as warmup.
            Applied as ``round(n_files × warmup_fraction)``, clamped to
            ``[1, n_files − 1]``. Default 0.20 means 1 file warmup at
            n=5, 2 at n=10, 4 at n=20.

    Returns:
        ``(per_psd_seg_ms_or_None, breakdown_dict)``. The breakdown
        mirrors ``_aggregate_warmup_timings``'s shape so downstream
        record-writing is symmetric.

    Returns ``None`` (with the aggregator key still ``None``) when:
      * fewer than 2 files exist (no signal to discard warmup from);
      * the post-warmup slice is empty;
      * every post-warmup per-PSD-seg cost is ≤ 0 (degenerate sidecar).

    The ``None`` return routes the caller to the legacy ``× 2.7``
    fallback in Commit D — preserving back-compat for tiny trials and
    OOM-killed subprocesses where no measurement was captured.
    """
    n_files = len(per_file_timings_ms)
    breakdown: dict = {
        "aggregator": None,
        "n_warmup_files": 0,
        "n_timed_files": 0,
        "warmup_fraction": warmup_fraction,
        "timings_ms": list(per_file_timings_ms),
    }
    if n_files < 2:
        return None, breakdown

    n_warmup = min(max(1, round(n_files * warmup_fraction)), n_files - 1)
    timed = per_file_timings_ms[n_warmup:]
    if not timed:
        return None, breakdown

    per_psd_seg_ms = [
        float(t.get("elapsed_ms", 0.0)) / max(int(t.get("n_psd_segs", 1)), 1) for t in timed
    ]
    if not per_psd_seg_ms or all(v <= 0 for v in per_psd_seg_ms):
        return None, breakdown

    breakdown["aggregator"] = "median"
    breakdown["n_warmup_files"] = n_warmup
    breakdown["n_timed_files"] = len(timed)
    return statistics.median(per_psd_seg_ms), breakdown


# ── torch-dependent helpers (warmup infrastructure) ──────────────────────────


def _detect_gpu_name() -> str | None:
    """Return the active CUDA device name, or None on CPU-only / import-fail
    hosts. Stable across SDSC node reassignment because it queries the GPU,
    not the hostname (§2.6.4)."""
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    try:
        return torch.cuda.get_device_name(0)
    except Exception:
        return None


def _count_params(model_type: str, model_config: dict, loss_type: str) -> int:
    """Instantiate the model on CPU and return exact parameter count.

    Kept in a function so tests can monkeypatch it without importing torch.
    """
    from ml_models.models_format_sandbox import get_config_class
    from ml_models.models_sandbox import MODEL_REGISTRY

    config_cls = get_config_class(model_type)
    if config_cls is None:
        raise ValueError(
            f"_count_params: unknown model_type={model_type!r} — "
            f"get_config_class returned None (no plugin or built-in config registered)."
        )
    config_obj = config_cls(**model_config)
    if model_type == "fcnet":
        model = MODEL_REGISTRY[model_type](config_obj, loss_type=loss_type)
    else:
        model = MODEL_REGISTRY[model_type](config_obj)
    return sum(p.numel() for p in model.parameters())


def _measure_ms_per_step(
    model_type: str,
    model_config: dict,
    train_config: dict,
    loss_config: dict,
    data_dir: str,
    sample_set: dict,
    profile: DatasetProfile,
    task_scope: object | None = None,
    n_warmup_batches: int = 3,
    n_timed_batches: int = 7,
) -> tuple[float | None, dict]:
    """Measure real ms/step by running a micro training pass on 1+ real PSDs.

    Mirrors the training code path in ``execute_tools.train_engine_sandbox`` so
    the measurement captures GPU compute, disk/HDF5 load, DataLoader overhead,
    and the actual model+loss+optimizer combination in one shot.

    Phase 6.7 Fix 1 — Steady-state warmup. Defaults moved from 1+2 to 3+7
    so the first cudnn-autotune step (and any kernel selection rebound on
    steps 1-2) is excluded from the aggregate, and the steady-state
    estimate has 7 samples to median over instead of 2 to mean over.
    Step 0 also gates a fast-fail short-circuit (``_WARMUP_FAST_FAIL_MS``)
    so a hopelessly slow first step aborts the warmup immediately rather
    than burning the full quota on a config the time gate will reject.

    Returns ``(measured_ms_or_None, warmup_breakdown)``:

      * ``measured_ms`` is ``None`` on any setup failure (missing CUDA,
        missing data_dir, build/instantiation error, dataset too small) —
        caller falls back to the static formula.
      * ``warmup_breakdown`` is always a dict; surfaces ``aggregator``
        ('median' / 'fast_fail' / None), ``n_warmup_batches``,
        ``n_timed_batches`` (actual count after fast-fail / truncation),
        and the raw ``timings_ms`` list. Empty-ish on early returns so
        the caller can merge it unconditionally.
    """
    empty_breakdown: dict = {
        "n_warmup_batches": n_warmup_batches,
        "n_timed_batches": 0,
        "timings_ms": [],
        "aggregator": None,
    }

    if not data_dir or not os.path.isdir(data_dir):
        print("    [warmup skipped] no data_dir; falling back to static formula.")
        return None, empty_breakdown

    try:
        import torch
    except ImportError:
        return None, empty_breakdown
    if not torch.cuda.is_available():
        print("    [warmup skipped] CUDA not available; falling back to static formula.")
        return None, empty_breakdown

    try:
        from torch.utils.data import DataLoader

        # D14-1 C5: the warmup probe reaches the epoch dataset through the
        # resolved TaskDataPath like every other production consumer — under
        # a non-TIDMAD run binding the implementation refuses the TIDMAD
        # scope loudly instead of silently timing TIDMAD data.
        from execute_tools.task_data_path import (
            EpochSamplingParams,
            resolve_bound_task_data_path,
        )
        from ml_models.loss_models_sandbox import (
            get_criterion,
        )
        from ml_models.loss_models_sandbox import (
            get_target_torch_dtype as _get_target_torch_dtype,
        )
        from ml_models.models_format_sandbox import (
            LossConfig,
            TrainConfig,
            get_config_class,
        )
        from ml_models.models_sandbox import MODEL_REGISTRY

        batch_size = int(train_config.get("batch_size", 1))
        loss_type = _training_est.resolve_loss_type(loss_config)

        required_segs = (n_warmup_batches + n_timed_batches) * batch_size
        if task_scope is None:
            print(
                "    [warmup skipped] no task-owned training scope was supplied; "
                "the framework does not construct a scientific task scope."
            )
            return None, empty_breakdown
        # The attempt already owns a task-built scope. The existing max_samples
        # carrier bounds materialization without inspecting or rewriting the
        # task's opaque scope.
        measurement_scope = task_scope

        dataset = resolve_bound_task_data_path().training_dataset(
            measurement_scope,
            EpochSamplingParams(
                data_dir=data_dir,
                epoch_seed=0,
                train_portion=1.0,
                max_samples=required_segs,
            ),
        )
        dataset_size = len(cast("Sized", dataset))
        if dataset_size < required_segs:
            print(
                f"    [warmup skipped] mini dataset too small "
                f"({dataset_size} < {required_segs} required); falling back."
            )
            return None, empty_breakdown
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, drop_last=True)

        device = torch.device("cuda")

        config_cls = get_config_class(model_type)
        if config_cls is None:
            print(
                f"    [warmup skipped] unknown model_type={model_type!r}; "
                f"falling back to static formula."
            )
            return None, empty_breakdown
        model_cfg_obj = config_cls(**model_config)
        if model_type == "fcnet":
            model = MODEL_REGISTRY[model_type](model_cfg_obj, loss_type=loss_type).to(device)
        else:
            model = MODEL_REGISTRY[model_type](model_cfg_obj).to(device)

        train_cfg_obj = TrainConfig(**train_config)
        loss_cfg_obj = LossConfig(**loss_config)
        criterion = get_criterion(loss_cfg_obj, class_weights=None)

        if train_cfg_obj.optimizer_type == "adamw":
            optimizer = torch.optim.AdamW(
                model.parameters(),
                lr=train_cfg_obj.lr,
                weight_decay=train_cfg_obj.weight_decay,
            )
        elif train_cfg_obj.optimizer_type == "adam":
            optimizer = torch.optim.Adam(model.parameters(), lr=train_cfg_obj.lr)
        else:
            optimizer = torch.optim.SGD(model.parameters(), lr=train_cfg_obj.lr)

        model.train()
        all_step_times_ms: list[float] = []
        it = iter(loader)
        for step in range(n_warmup_batches + n_timed_batches):
            try:
                x, y = next(it)
            except StopIteration:
                break
            x = x.to(device)
            y = y.to(device)
            x = x.float() if model_type == "fcnet" else x.int()
            # I13 — single source of truth for target dtype routing.
            # ``get_target_torch_dtype`` reads built-in routing for
            # ce/focal/focal_cw/smooth_l1 and the plugin's declared
            # ``PLUGIN_LOSS_TARGET_DTYPE`` for loss_type="custom"
            # (defaulting to torch.long for pre-I13 plugins).
            y = y.to(dtype=_get_target_torch_dtype(loss_cfg_obj))

            torch.cuda.synchronize()
            t0 = time.perf_counter()
            optimizer.zero_grad()
            out = model(x)
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            torch.cuda.synchronize()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            all_step_times_ms.append(elapsed_ms)

            # Phase 6.7 Fix 1 fast-fail: a single forward+backward+optimizer
            # ≥ _WARMUP_FAST_FAIL_MS at step 0 means the model is DOA. Don't
            # burn the rest of the warmup quota on a config the time gate
            # will reject anyway. The aggregator returns this same elapsed
            # ms tagged ``aggregator='fast_fail'`` so the caller short-
            # circuits on a worst-case-conservative number.
            if step == 0 and elapsed_ms >= _WARMUP_FAST_FAIL_MS:
                print(
                    f"    [warmup fast-fail] step 0 took {elapsed_ms:.0f} ms "
                    f"(≥ {_WARMUP_FAST_FAIL_MS:.0f} ms threshold). "
                    f"Aborting warmup — DOA model."
                )
                break

        del model, optimizer, criterion, dataset, loader
        torch.cuda.empty_cache()
        gc.collect()

        return _aggregate_warmup_timings(all_step_times_ms, n_warmup_batches)

    except Exception as exc:  # pragma: no cover — defensive
        print(f"    [warmup failed] {exc}\n{traceback.format_exc(limit=3)}")
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass
        return None, empty_breakdown


# ── public entry point ───────────────────────────────────────────────────────


def _store_reuse_decision(
    *,
    store_root: str,
    model_type: str,
    train_config: dict,
    sample_set: dict,
    train_portion: float,
    seg_size: int,
    batch_size: int,
    num_params: int,
    gpu_name: str | None,
    profile: DatasetProfile,
):
    """§3 store-reuse decision for a trial round (RT3). Best-effort:
    any store/lookup problem degrades to warm-up-required — the policy
    can only ever SKIP work, never fabricate an estimate.

    Returns ``(decision | None, lookup_status | None, key | None)``.
    """
    from agent.skills.evaluate_time_skill.trigger_policy import decide_nonformal_estimation

    try:
        import torch

        from core.runtime_control.observation_store import ObservationStore, calibration_key
        from execute_tools.workload_resolvers import resolve_training_workload

        key = calibration_key(
            "training",
            gpu_name=gpu_name,
            torch_version=torch.__version__,
            precision="float32",  # the production trainer's default dtype
            optimizer_type=str(train_config.get("optimizer_type", "adamw")),
            model_family=model_type,
            param_count=num_params,
            seg_size=seg_size,
            batch_size=batch_size,
        )
        lookup = ObservationStore(store_root).lookup_prior(
            key,
            "training",
            current_gpu_name=gpu_name,
            current_torch_version=torch.__version__,
        )
        prior_ms = lookup.prior_unit_ms if lookup.status == "valid" else None
        n_steps = resolve_training_workload(
            sample_set,
            seg_size=seg_size,
            profile=profile,
            batch_size=batch_size,
            train_portion=train_portion,
            # V21 PR B1 — TrainConfig declares 10; the literal 1 made the
            # store-reuse step count 10x optimistic (design doc §0.6.4).
            epochs=_training_est.resolve_train_field(train_config, "epochs", safety_margin=1),
        ).unit_count
        decision = decide_nonformal_estimation(
            is_trial_round=True,
            n_steps=n_steps,
            batch_size=batch_size,
            seg_size=seg_size,
            store_prior_unit_ms=prior_ms,
            static_ms_per_step=_training_est._static_ms_per_step(num_params, seg_size, batch_size),
        )
        return decision, lookup.status, key
    except Exception as exc:
        print(f"    [TimeEval] store-reuse check failed (non-fatal, warming up): {exc}")
        return None, None, None


def _gate_decision(
    *,
    result_shape: dict,
    effective_budget_minutes: float,
    runtime_phase: str,
    probe_record_available: bool = False,
) -> dict:
    """Ask the shared runtime policy whether this projection may gate the
    round (C8c).

    Returns a plain dict so the skill's result stays JSON-serialisable for
    the record. The estimate is built by the canonical adapter, so its
    provenance — and therefore its authority — is derived from the
    measurement path the estimate actually came from, never asserted here.
    """
    from core.runtime_control.decision_policy import RuntimeBudget, RuntimeMode
    from core.runtime_control.estimate_types import from_time_eval_result
    from core.runtime_control.estimator import shared_runtime_components

    # C8g: the process-wide policy, not a per-call construction — the
    # proposer, this gate, and any future consumer must demonstrably
    # decide with the SAME policy identity.
    policy = shared_runtime_components()[1]
    try:
        estimate = from_time_eval_result(result_shape)
    except ValueError as exc:
        # An evidence source this subsystem cannot interpret is an
        # EVIDENCE-CHANNEL failure, not a verdict on the candidate
        # (operator decision, C8 §2). It must never be silently converted
        # into "infeasible" — the caller turns ABORT into an error.
        return {
            "kind": "ABORT",
            "reasons": [f"uninterpretable runtime evidence: {exc}"],
            "evidence_provenance": "unknown",
            "evidence_rank": -1,
            "policy_identity": policy.identity,
        }
    phase = runtime_phase if runtime_phase in ("proposal", "trial", "formal") else "trial"
    decision = policy.decide(
        estimate,
        RuntimeBudget(time_seconds=max(effective_budget_minutes, 1e-9) * 60.0),
        RuntimeMode(phase=phase, candidate_stage="post_implementation"),  # type: ignore[arg-type]
        # No bounded live probe feeds this pre-flight today (the tuner's
        # authoritative formal measurement is the in-subprocess
        # verification, RT2). Declaring the absence honestly is what makes
        # a formal prior-tier projection return REQUEST_PROBE instead of
        # quietly pricing the round from a prior.
        evidence_channel="ok" if probe_record_available else "probe_absent",
    )
    return {
        "kind": decision.kind,
        "reasons": list(decision.reasons),
        "evidence_provenance": decision.evidence_provenance,
        "evidence_rank": decision.evidence_rank,
        "policy_identity": policy.identity,
    }


def run_skill(sandbox, **kwargs) -> dict:
    """Estimate wall-time (training + inference + scoring) for the proposed
    config and gate against the time budget.

    Required kwargs: model_type, model_config, train_config, loss_config,
                     sample_set, time_budget_minutes, dataset_profile
                     (Step 05b — the RUN-BOUND Dataset Profile; every
                     decomposition-derived term below is resolved from it,
                     and this skill never resolves one of its own, because a
                     time gate that re-read an ambient topology could price a
                     run against a dataset it is not using).
    Optional kwargs: train_portion (default 1.0), data_dir (enables warmup),
                     inference_batch (V21 PR G — explicit batch to price
                     the inference forecast at, overriding the registry
                     default; None → pre-G1 behaviour, byte-identical. Must
                     be a positive int; an invalid value surfaces via the
                     structured ``status: "error"`` return, never a silent
                     clamp. LIVE on the agent path: the tuner's
                     _run_time_preflight splats **active_params, whose
                     ``inference_batch`` is the current attempt's probed
                     batch, set at tuner :4696 before the gate fires —
                     so the forecast prices at the batch inference will
                     actually run).

    Returns a dict with keys: status, feasible, verdict, suggestion,
    estimated_minutes, limit_minutes, breakdown, dominant_phase,
    phase_breakdown.
    """
    model_type = kwargs.get("model_type")
    # Required kwarg per docstring contract; downstream helpers (_count_params,
    # _measure_ms_per_step, _training_est.estimate_wall_time_seconds, …) all
    # require a concrete ``str``. Fail explicitly here instead of letting the
    # first internal call crash on a None argument.
    if not isinstance(model_type, str) or not model_type:
        raise ValueError(
            f"evaluate_time_skill.run_skill: 'model_type' kwarg is required "
            f"and must be a non-empty str (got {model_type!r})."
        )
    model_config = kwargs.get("model_config", {})
    train_config = kwargs.get("train_config", {})
    loss_config = kwargs.get("loss_config", {})
    sample_set = kwargs.get("sample_set", {})
    # eval_sample_set drives inference + scoring projections. Falls back to
    # sample_set for back-compat with callers that haven't been updated to
    # pass both. The bug this guards against: in formal mode train data is
    # ~10% (formal_portion=0.1) but eval data defaults to 100%
    # (formal_eval_portion=1.0 — Phase M § 12.2 production default; now
    # operator-configurable per Phase R §13), so using sample_set for
    # inf/score under-projects by ~10×.
    eval_sample_set = kwargs.get("eval_sample_set", sample_set)
    train_portion = float(kwargs.get("train_portion", 1.0))
    budget_min = float(kwargs.get("time_budget_minutes", 0.0))
    data_dir = kwargs.get("data_dir")
    # Step 05b — the run's ONE topology, received rather than resolved. A
    # missing profile is a wiring defect, not a case to default through:
    # every step count, output-byte term and advisory string below depends
    # on it, so a silent ambient substitution would price the whole gate
    # against a dataset the run never declared.
    profile = kwargs.get("dataset_profile")
    if not isinstance(profile, DatasetProfile):
        raise ValueError(
            "evaluate_time_skill.run_skill: 'dataset_profile' kwarg is required "
            f"and must be a DatasetProfile (got {type(profile).__name__}). The "
            "caller binds the run's topology; this skill does not resolve one."
        )

    # V21 PR B1. These were resolved against literals contradicting the
    # declarations the run itself uses, and `seg_size` in particular is not
    # only printed: it is a component of the observation-store calibration
    # key (`_store_reuse_decision`). A run whose model really runs at 40000
    # was reading and writing a bucket labelled 1000, mixing incomparable
    # measurements. See the PR B design doc §0.6.5b.
    seg_size = _training_est.resolve_model_field(
        model_type, model_config, "segmentation_size", safety_margin=1000
    )
    batch_size = int(train_config.get("batch_size", 1))
    epochs = _training_est.resolve_train_field(train_config, "epochs", safety_margin=1)
    loss_type = _training_est.resolve_loss_type(loss_config)

    print(
        f"\n>>> [Skill: TimeEval] Checking wall-time for {str(model_type).upper()} "
        f"(bs={batch_size}, seg={seg_size}, epochs={epochs}, budget={budget_min:.0f} min)..."
    )

    try:
        num_params = _count_params(model_type, model_config, loss_type)
        gpu_name = _detect_gpu_name()

        # RT3 (§3 table): NON-formal rounds may reuse a stored unit time
        # instead of warming up — only on a valid exact-key store hit
        # within the §3 bounds. Formal rounds never take this path (the
        # tuner only passes allow_store_reuse for trial rounds; their
        # authority is the in-subprocess verification, §2.1/§3).
        store_decision = None
        store_lookup_status = None
        store_key = None
        if kwargs.get("allow_store_reuse") and kwargs.get("observation_store_root"):
            store_decision, store_lookup_status, store_key = _store_reuse_decision(
                store_root=str(kwargs["observation_store_root"]),
                model_type=model_type,
                train_config=train_config,
                sample_set=sample_set,
                train_portion=train_portion,
                seg_size=seg_size,
                batch_size=batch_size,
                num_params=num_params,
                gpu_name=gpu_name,
                profile=profile,
            )

        # Real-dataset warmup — only with CUDA + data_dir, and only when
        # the §3 policy did not authorize store reuse. Feeds the
        # training estimator directly and the inference estimator after
        # scaling by _INFERENCE_VS_TRAINING_RATIO. Phase 6.7 Fix 1: the
        # warmup also returns a structured breakdown so the audit log
        # shows whether the estimate came from a steady-state median or
        # from the step-0 fast-fail short-circuit.
        measured: float | None = None
        warmup_breakdown: dict = {
            "n_warmup_batches": 0,
            "n_timed_batches": 0,
            "timings_ms": [],
            "aggregator": None,
        }
        store_reused = store_decision is not None and store_decision.action == "reuse_store"
        if store_reused:
            assert store_decision is not None
            measured = store_decision.store_unit_ms
            print(
                f"    [TimeEval] §3 store reuse: {measured:.2f} ms/step from the "
                f"observation store (key hit, warm-up skipped)."
            )
        elif data_dir:
            task_scopes = kwargs.get("task_scopes")
            measured, warmup_breakdown = _measure_ms_per_step(
                model_type=model_type,
                model_config=model_config,
                train_config=train_config,
                loss_config=loss_config,
                data_dir=data_dir,
                sample_set=sample_set,
                profile=profile,
                task_scope=getattr(task_scopes, "training", None),
            )

        training = _training_est.estimate_wall_time_seconds(
            model_type,
            model_config,
            train_config,
            sample_set,
            train_portion=train_portion,
            ms_per_step=measured,
            gpu_name=gpu_name,
            num_params=num_params,
            loss_type=loss_type,
            dataset_profile=profile,
        )
        if store_reused:
            # RT3 provenance correction: the estimator stamps a passed
            # ms_per_step as the warm-up source; a store-reused value is
            # a HISTORICAL prior — never formal-eligible (§3 non-formal
            # table; formal admission is the in-subprocess verification).
            training["breakdown"]["ms_source"] = "store"
            training["breakdown"]["formal_execution_eligible"] = False

        # refine_inference_time_estimator.md Commit D — three-branch
        # inference-ms derivation, in priority order:
        #   1. ``trial_inference_warmup``: the tuner passed a measured
        #      per-PSD-segment cost via ``inference_per_psd_seg_ms_hint``
        #      (Commit C aggregator output, captured during the trial
        #      round and now consumed by the formal round). This is the
        #      most accurate path — convert per-PSD-seg cost back to
        #      per-step cost by inverting the estimator's
        #      ``total_steps = ceil(n_psd × ml_per_psd / inf_batch)``
        #      identity. See the design doc §3.5 correction note for
        #      the derivation.
        #   2. ``training_warmup_x2.7_fallback``: the legacy path —
        #      training warmup measured ms/step, scale by the
        #      hand-calibrated ``_INFERENCE_VS_TRAINING_RATIO`` constant.
        #      Used when no trial measurement is available (first iter,
        #      OOM-killed trial, CPU-only host).
        #   3. ``static_formula``: nothing measured. The inference
        #      estimator's internal static fallback fires because
        #      ``inference_ms_per_step`` is None. Source tag is set
        #      explicitly here so audit logs distinguish "we passed
        #      None" from a measured path.
        inference_per_psd_seg_ms_hint = kwargs.get("inference_per_psd_seg_ms_hint")
        # V21 PR G G1 — both forecast sides must price the same batch: this
        # hint scaling AND the estimator call below receive the SAME explicit
        # value (0.R.3), so a caller-supplied probe batch can never apply to
        # one side only. None → registry default, exactly pre-G1.
        explicit_inference_batch = kwargs.get("inference_batch")
        inf_batch = _inference_est.resolve_forecast_batch(explicit_inference_batch, model_type)
        _psd_len = tidmad_topology(profile).dataset.psd_segment_length
        ml_per_psd = max(_psd_len // max(seg_size, 1), 1)
        if inference_per_psd_seg_ms_hint is not None and inference_per_psd_seg_ms_hint > 0:
            inference_ms = float(inference_per_psd_seg_ms_hint) * inf_batch / ml_per_psd
            inference_ms_source = "trial_inference_warmup"
        elif measured is not None and measured > 0:
            inference_ms = measured * _inference_est._INFERENCE_VS_TRAINING_RATIO
            inference_ms_source = "training_warmup_x2.7_fallback"
        else:
            inference_ms = None
            inference_ms_source = "static_formula"

        inference = _inference_est.estimate_wall_time_seconds(
            model_type,
            model_config,
            eval_sample_set,
            inference_ms_per_step=inference_ms,
            num_params=num_params,
            inference_batch=explicit_inference_batch,
            dataset_profile=profile,
        )

        scoring = _scoring_est.estimate_wall_time_seconds(eval_sample_set)

    except Exception as e:
        msg = f"TimeEval error: {e}\n{traceback.format_exc()}"
        print(f"!!! [TimeEval] {msg}")
        return {"status": "error", "message": msg}

    phases = [training, inference, scoring]
    total_sec = sum(p["seconds"] for p in phases)
    total_min = total_sec / 60.0
    phase_breakdown = {p["phase"]: p for p in phases}
    dominant = max(phases, key=lambda p: p["seconds"])["phase"]

    # K.2.5-8: surface the inference estimator's soft-fallback flag.
    # Mirror of the warning emitted by evaluate_vram_skill — same flag,
    # same model_type, same architecture-uncalibrated caveat. Both gates
    # call the same inference estimator, so the flag is identical; we
    # warn once per gate so audit logs from either side are
    # self-contained. See docs/resource_estimator_implement.md §10.14
    # K.2.5-8.
    inference_batch_uncalibrated = bool(inference["breakdown"].get("inference_batch_uncalibrated"))
    if inference_batch_uncalibrated:
        # V21 PR G: the batch shown is whatever the forecast actually
        # priced — the probe-derived hint on the agent path, the silent
        # table fallback (25) only on no-hint paths. The flag itself keeps
        # its registration meaning either way.
        _batch_provenance = (
            "probe-derived hint" if explicit_inference_batch is not None else "runtime fallback"
        )
        print(
            f"!!! [evaluate_time_skill] model_type {model_type!r} has no "
            f"registered inference batch in core/inference_defaults.py — "
            f"pricing at the {_batch_provenance} "
            f"({inference['breakdown']['inference_batch']}). "
            f"Architecture-level ms/step is UNCALIBRATED for this "
            f"novel architecture. Treat verdict as best-effort."
        )

    # refine_inference_time_estimator.md Commit D / Step 6.5 — measurement-
    # aware feasibility check. When the inference path was the measured
    # ``trial_inference_warmup`` branch, the estimate is precise to ±10%
    # in practice (median over n≥4 post-warmup files), so a config that
    # lands at e.g. 102% of budget is throwing away signal if we reject it
    # on the strict ``<=``. Soften by 10%. The fallback paths
    # (``training_warmup_x2.7_fallback``, ``static_formula``) keep the
    # strict check because their uncertainty bands are much wider — a 10%
    # slack would let configs that genuinely overrun budget by 30% slip
    # through.
    SLACK_FRACTION_WHEN_MEASURED = 0.10
    if inference_ms_source == "trial_inference_warmup":
        effective_budget_min = budget_min * (1.0 + SLACK_FRACTION_WHEN_MEASURED)
        slack_applied = True
    else:
        effective_budget_min = budget_min
        slack_applied = False

    # Flat breakdown: preserves the pre-K.2.5 contract so
    # nodes/ml_hyperparameter_tune_agent.py can still read `source` +
    # `gpu_name` to trigger the Phase F EMA update. Phase 6.7 Fix 1
    # appends ``warmup_aggregator`` + the per-step timing detail so the
    # audit log distinguishes a steady-state median from a step-0
    # fast-fail event without losing the legacy keys. Commit D appends
    # ``inference_ms_source`` + slack-rule fields so the tuner can record
    # which branch produced the inference-ms estimate and whether the
    # 10% slack softened the verdict.
    tbd = training["breakdown"]
    breakdown = {
        "total_train_steps": tbd["total_train_steps"],
        "ms_per_step_warmup": tbd["ms_per_step"],
        # `k_correction` is gone (operator decision 2026-08-03): the legacy
        # per-GPU historical scaling no longer reaches the production time
        # verdict, and this breakdown no longer carries a slot for it.
        "safety_multiplier": tbd["safety_multiplier"],
        "train_minutes": round(training["seconds"] / 60.0, 2),
        "num_params": num_params,
        "source": tbd["ms_source"],
        # Rev 4: fail-closed — a breakdown that doesn't declare eligibility
        # (legacy shape, stubbed estimator) is NOT formal-eligible.
        "formal_execution_eligible": tbd.get("formal_execution_eligible", False),
        "gpu_name": tbd["gpu_name"],
        "warmup_aggregator": warmup_breakdown.get("aggregator"),
        "warmup_n_warmup_batches": warmup_breakdown.get("n_warmup_batches", 0),
        "warmup_n_timed_batches": warmup_breakdown.get("n_timed_batches", 0),
        "warmup_timings_ms": warmup_breakdown.get("timings_ms", []),
        "inference_ms_source": inference_ms_source,
        "slack_applied": slack_applied,
        "effective_budget_minutes": round(effective_budget_min, 2),
        # RT3 planner-visible provenance: how the §3 non-formal policy
        # resolved (absent keys when the policy was never consulted).
        "store_reuse": store_reused,
        "store_lookup_status": store_lookup_status,
        "store_key": store_key,
        "store_policy_reasons": (
            list(store_decision.reasons) if store_decision is not None else None
        ),
    }

    # C8c — the gate verdict comes from the SHARED decision policy, not from
    # a private comparison in this skill. The arithmetic is unchanged: the
    # effective budget (including the measured-inference slack) is what the
    # policy is asked about, so a MEASURED estimate over budget still
    # REJECTs exactly as before. What changes is that a static or
    # historical-prior estimate can no longer reject a round on its own —
    # the authority rule the V19 wave-1 incident violated (§7.4 matrix
    # rows static_prior/historical_prior_only = cannot_block).
    runtime_decision = _gate_decision(
        result_shape={
            "status": "success",
            "estimated_minutes": round(total_min, 2),
            "breakdown": breakdown,
            "phase_breakdown": phase_breakdown,
            "inference_batch_uncalibrated": inference_batch_uncalibrated,
        },
        effective_budget_minutes=effective_budget_min,
        runtime_phase=str(kwargs.get("runtime_phase", "trial")),
        probe_record_available=bool(kwargs.get("probe_record_available", False)),
    )
    if runtime_decision["kind"] == "ABORT":
        # Execution-system failure — surfaced as an ERROR result, which the
        # tuner raises on. Never presented as a candidate-level verdict.
        return {
            "status": "error",
            "message": (
                "TimeEval evidence-channel failure (ABORT): "
                + "; ".join(runtime_decision["reasons"])
            ),
        }
    feasible = runtime_decision["kind"] != "REJECT"
    breakdown["runtime_decision"] = runtime_decision["kind"]
    breakdown["runtime_decision_reasons"] = runtime_decision["reasons"]
    breakdown["runtime_decision_provenance"] = runtime_decision["evidence_provenance"]
    breakdown["runtime_policy_identity"] = runtime_decision["policy_identity"]

    # The projection exceeding the budget is an OBSERVATION; whether it may
    # gate the round is the POLICY's call. Keeping them separate means an
    # advisory-only (static / historical) overshoot still tells the
    # operator what it saw and which lever to pull — it just cannot stop
    # the round. Conflating them would have silently deleted the warning
    # along with the authority.
    over_budget = total_min > effective_budget_min
    breakdown["over_effective_budget"] = over_budget
    slack_note = (
        f" (within +{int(SLACK_FRACTION_WHEN_MEASURED * 100)}% slack on measured inference)"
        if slack_applied and not over_budget and total_min > budget_min
        else ""
    )
    authority_note = (
        ""
        if not over_budget or not feasible
        else (
            f" [{runtime_decision['kind']}: not blocking — "
            f"{runtime_decision['evidence_provenance']} evidence cannot gate "
            f"this round]"
        )
    )
    verdict = (
        f"{'✅ FITS' if not over_budget else '❌ OVER BUDGET'} — "
        f"Est {total_min:.1f} min vs budget {budget_min:.1f} min "
        f"(train {training['seconds']:.1f}s + inf {inference['seconds']:.1f}s "
        f"+ score {scoring['seconds']:.1f}s). Dominant phase: {dominant}."
        f"{slack_note}{authority_note}"
    )
    suggestion = (
        ""
        if not over_budget
        else _suggest_lever(
            tbd["ms_per_step"],
            seg_size,
            batch_size,
            tidmad_topology(profile).dataset.psd_segment_length,
        )
    )

    print(f"    Parameters   : {num_params:,}")
    print(f"    Train steps  : {tbd['total_train_steps']:,}")
    print(f"    ms/step      : {tbd['ms_per_step']:.2f}  ({tbd['ms_source']})")
    print(
        f"    Phase sec    : train={training['seconds']:.1f} "
        f"inf={inference['seconds']:.1f} score={scoring['seconds']:.1f}"
    )
    print(f"    Est minutes  : {total_min:.1f} / budget {budget_min:.1f}  (dominant: {dominant})")
    print(
        f"    Feasible     : {'YES' if feasible else 'NO'}  "
        f"(policy {runtime_decision['kind']}, evidence "
        f"{runtime_decision['evidence_provenance']})"
    )
    if suggestion:
        print(f"    Suggestion   : {suggestion}")

    return {
        "status": "success",
        "feasible": feasible,
        "verdict": verdict,
        "suggestion": suggestion,
        "estimated_minutes": round(total_min, 2),
        "limit_minutes": budget_min,
        "breakdown": breakdown,
        "dominant_phase": dominant,
        "phase_breakdown": phase_breakdown,
        "inference_batch_uncalibrated": inference_batch_uncalibrated,
    }
