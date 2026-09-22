"""
execute_tools/workload_resolvers.py

Exact per-phase workload resolution for the TIDMAD production engines
(RT2-A).

Design: docs/design/runtime_estimation_and_watchdog.md §1.2. Every
resolver mirrors its production implementation EXACTLY — no formula may
diverge from production execution semantics — and returns a generic
`ResolvedPhaseWorkload` consumed by the runtime-control framework
(`core/runtime_control`). Porting SIDERIUS to a new task means writing
new resolvers here, not changing the framework.

Authorities mirrored:
- **Training** — `tidmad_data_path.TIDMADEpochDataset.__init__`
  (owner since D14-1; the engine re-exports the class and reaches it
  through the run-bound `TaskDataPath`)
  (per-file ``max(1, round(portion × len(scope_segments)))`` subsample)
  + the configured DataLoader tail policy (floor per epoch by default,
  ceiling when ``drop_last=False``). This is the RT1 resolver, colocated with the
  engine; `agent/skills/training_skill/estimator._total_train_steps`
  delegates here.
- **Inference** — `inference_single.py` sample_set (trial) mode: per
  sorted file, ``n_psd × (PSD_SEGMENT_LENGTH // seg_size)`` ML segments
  processed in ``range(0, dim1, batch_size)`` batches (ceil), plus one
  output HDF5 write of two int8 channels per file.
- **Scoring** — `scoring_utils.score_vector`: unit = PSD segment,
  parallel over ``num_workers`` (per-host throughput lives in
  `core/server_configs`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from core.runtime_control.phases import RuntimePhase
from core.runtime_control.workload import ResolvedPhaseWorkload
from execute_tools.dataset_config import (
    DatasetProfile,
    tidmad_topology,
)
from execute_tools.training_batches import optimizer_steps_for_rows

SampleSet = Mapping[str, Sequence[int]] | Mapping[int, Sequence[int]]


def _validate_seg(seg_size: int, profile: DatasetProfile) -> int:
    """ML segments per PSD segment under the RUN-BOUND decomposition geometry.

    Step 05b: ``profile`` is required. It used to default to an ambient
    resolution, which meant a run bound to one topology could be PRICED
    against whatever singleton happened to be resolved — the Step-02b defect
    shape, on the workload side. The caller states which dataset it means.
    """
    if seg_size <= 0:
        raise ValueError(f"seg_size must be positive; got {seg_size!r}.")
    return tidmad_topology(profile).dataset.psd_segment_length // seg_size


def resolve_training_workload(
    sample_set: SampleSet,
    *,
    seg_size: int,
    profile: DatasetProfile,
    batch_size: int,
    train_portion: float | None,
    epochs: int,
    max_samples: int | None = None,
    drop_last: bool = True,
) -> ResolvedPhaseWorkload:
    """Optimizer-step workload, mirroring the trainer exactly (RT1).

    Per file: ``n_keep = max(1, round(train_portion × len(scope_segments)))``
    when ``train_portion`` < 1.0 (else all) — the ``max(1, ·)`` floor
    means many-small-file scopes train far more than the naive global
    product. Per epoch: ``(n_psd_kept × ml_per_psd) // batch_size``
    (default ``drop_last=True`` floor; false uses ceiling). ``n_keep`` is deterministic, so every
    epoch has the same step count.

    ``max_samples`` mirrors ``TIDMADEpochDataset``'s validation-posture
    ceiling: the epoch is cut to that many ML segments. It is what lets a
    Gate compute the EXACT executed step count before launching anything,
    which is the difference between sizing a run and killing one.
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive; got {batch_size!r}.")
    if epochs < 0:
        raise ValueError(f"epochs must be non-negative; got {epochs!r}.")
    ml_per_psd = _validate_seg(seg_size, profile)

    n_psd_kept = 0
    per_file_kept: dict[str, int] = {}
    for file_key, scope_segments in sample_set.items():
        if train_portion is not None and train_portion < 1.0:
            n_keep = max(1, round(train_portion * len(scope_segments)))
        else:
            n_keep = len(scope_segments)
        per_file_kept[str(file_key)] = n_keep
        n_psd_kept += n_keep

    samples_per_epoch = n_psd_kept * ml_per_psd
    if max_samples is not None:
        samples_per_epoch = min(samples_per_epoch, max_samples)
    steps_per_epoch = optimizer_steps_for_rows(samples_per_epoch, batch_size, drop_last=drop_last)
    total_steps = steps_per_epoch * epochs

    return ResolvedPhaseWorkload(
        phase="training",
        unit="optimizer_step",
        unit_count=total_steps,
        detail={
            "n_files": len(per_file_kept),
            "per_file_psd_kept": per_file_kept,
            "n_psd_kept": n_psd_kept,
            "ml_segments_per_psd": ml_per_psd,
            "samples_per_epoch": samples_per_epoch,
            "steps_per_epoch": steps_per_epoch,
            "epochs": epochs,
            "seg_size": seg_size,
            "batch_size": batch_size,
            "train_portion": train_portion,
            "max_samples": max_samples,
        },
    )


def resolve_task_scope_training_workload(
    training_scope: object,
    *,
    data_dir: str,
    batch_size: int,
    train_portion: float | None,
    epochs: int,
    max_samples: int | None = None,
    drop_last: bool = True,
) -> ResolvedPhaseWorkload:
    """:func:`resolve_training_workload`'s TASK-NEUTRAL sibling (C12-P / B7).

    The legacy resolver above prices a TIDMAD ``SampleSet``: it needs a PSD
    segment length, a segments-per-file decomposition and a ``seg_size`` to
    divide by. A composed task that declares no physical partition geometry
    has none of those, so it has no legacy sample set at all — and every
    operator bound expressed in optimizer steps was therefore inert for it.

    **The cardinality comes from the frozen four-method contract, not from a
    new one.** ``TaskDataPath.training_dataset`` is the training sibling of
    the ``validation_dataset`` leg already in production at
    ``scope_artifact.validation_rows_argv``, and ``len()`` on the torch
    ``Dataset`` the ``DataLoader`` already requires to be ``Sized`` is the
    same instrument that leg uses. Nothing is added to ``TaskDataPath`` and
    nothing is added to the optional ``TaskScopeCapability`` sibling: the
    implementation that BUILT the scope is the one asked how big it is.

    **The arithmetic mirrors the resolver above**, one term at a time::

        legacy   samples_per_epoch = n_psd_kept × ml_per_psd
        generic  samples_per_epoch = len(training_dataset(scope, params))

        both     steps_per_epoch   = floor or ceil(samples_per_epoch / batch_size)
        both     total_steps       = steps_per_epoch × epochs

    ``train_portion`` and ``max_samples`` are NOT applied here. They travel
    on :class:`EpochSamplingParams` into the implementation's own
    materialization, exactly as they do for the epoch the trainer will build,
    so the count is the executed one rather than a framework re-derivation of
    it. Re-applying them here would price the subsample twice.

    **What this costs** — the same trade ``validation_rows_argv`` documents:
    the parent materializes the dataset object, so an implementation whose
    construction touches its rows pays that I/O here. That is the price of
    asking the other side of the boundary instead of guessing.

    Args:
        training_scope: the task's OPAQUE training scope for this attempt.
        data_dir: the run's resolved physical data root.
        batch_size: the loader's batch size.
        drop_last: floor if true (default), otherwise count the partial batch.
        train_portion: per-epoch subsample fraction, or ``None``.
        epochs: the epoch count the attempt will run.
        max_samples: the validation-envelope row ceiling, or ``None``.

    Returns:
        The optimizer-step workload, in the same shape and unit as
        :func:`resolve_training_workload`.

    Raises:
        ValueError: ``batch_size``/``epochs`` are out of range, or no task
            data path is bound — a scope built by an implementation cannot be
            measured without that implementation.
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive; got {batch_size!r}.")
    if epochs < 0:
        raise ValueError(f"epochs must be non-negative; got {epochs!r}.")

    from execute_tools.task_data_path import (
        EpochSamplingParams,
        active_task_data_path,
    )

    # `active_task_data_path`, never `resolve_bound_task_data_path`: the
    # legacy fallback would hand back the TIDMAD compatibility implementation
    # and price a contrast task's scope against TIDMAD's data path. The
    # caller establishes PRESENCE (it holds the acquired scope); this asks
    # only for the implementation that presence implies.
    bound = active_task_data_path()
    if bound is None:
        raise ValueError(
            "a task-owned training scope was supplied but no task data path is "
            "bound, so its row count cannot be declared by the implementation "
            "that built it."
        )
    dataset = bound.training_dataset(
        training_scope,
        EpochSamplingParams(
            data_dir=data_dir,
            train_portion=train_portion,
            max_samples=max_samples,
        ),
    )
    samples_per_epoch = len(dataset)  # type: ignore[arg-type]
    steps_per_epoch = optimizer_steps_for_rows(samples_per_epoch, batch_size, drop_last=drop_last)
    total_steps = steps_per_epoch * epochs

    return ResolvedPhaseWorkload(
        phase="training",
        unit="optimizer_step",
        unit_count=total_steps,
        detail={
            "source": "task_training_dataset",
            "samples_per_epoch": samples_per_epoch,
            "steps_per_epoch": steps_per_epoch,
            "epochs": epochs,
            "batch_size": batch_size,
            "train_portion": train_portion,
            "max_samples": max_samples,
        },
    )


def resolve_inference_workload(
    sample_set: SampleSet,
    *,
    seg_size: int,
    inference_batch_size: int,
    profile: DatasetProfile,
) -> ResolvedPhaseWorkload:
    """Inference-batch workload, mirroring `inference_single.py`
    sample_set mode exactly.

    Per sorted file: ``dim1 = n_psd × (PSD_SEGMENT_LENGTH // seg_size)``
    ML segments, processed in ``range(0, dim1, batch_size)`` →
    ``ceil(dim1 / batch_size)`` batches; then one output HDF5 write of
    two int8 channels (denoised + injected), each
    ``n_psd × PSD_SEGMENT_LENGTH`` bytes. The output-write cost is
    tracked via ``detail["output_bytes"]`` so RT2-D can price it
    separately from compute (§2.6).
    """
    if inference_batch_size <= 0:
        raise ValueError(f"inference_batch_size must be positive; got {inference_batch_size!r}.")
    ml_per_psd = _validate_seg(seg_size, profile)

    per_file_batches: dict[str, int] = {}
    per_file_ml_segments: dict[str, int] = {}
    total_psd = 0
    total_ml = 0
    total_batches = 0
    for file_key, psd_segment_indices in sample_set.items():
        n_psd = len(psd_segment_indices)
        dim1 = n_psd * ml_per_psd
        batches = (dim1 + inference_batch_size - 1) // inference_batch_size
        per_file_ml_segments[str(file_key)] = dim1
        per_file_batches[str(file_key)] = batches
        total_psd += n_psd
        total_ml += dim1
        total_batches += batches

    output_bytes = (
        total_psd * tidmad_topology(profile).dataset.psd_segment_length * 2
    )  # denoised + injected

    return ResolvedPhaseWorkload(
        phase="inference",
        unit="inference_batch",
        unit_count=total_batches,
        detail={
            "n_files": len(per_file_batches),
            "per_file_ml_segments": per_file_ml_segments,
            "per_file_batches": per_file_batches,
            "n_psd": total_psd,
            "ml_segments_per_psd": ml_per_psd,
            "total_ml_segments": total_ml,
            "output_bytes": output_bytes,
            "output_files": len(per_file_batches),
            "seg_size": seg_size,
            "inference_batch_size": inference_batch_size,
        },
    )


def resolve_scoring_workload(
    sample_set: SampleSet,
    *,
    num_workers: int,
) -> ResolvedPhaseWorkload:
    """PSD-segment workload, mirroring `scoring_utils.score_vector`.

    Unit = PSD segment; scoring parallelizes over ``num_workers``
    in-process workers (`score_vector(..., num_workers=)`), so the
    effective serial unit count for time prediction is
    ``total_psd_segments / max(num_workers, 1)`` — recorded in detail,
    while ``unit_count`` stays the raw production unit count.
    """
    if num_workers < 0:
        raise ValueError(f"num_workers must be non-negative; got {num_workers!r}.")
    per_file_psd = {str(k): len(v) for k, v in sample_set.items()}
    total_psd = sum(per_file_psd.values())
    workers = max(num_workers, 1)

    return ResolvedPhaseWorkload(
        phase="scoring",
        unit="psd_segment",
        unit_count=total_psd,
        detail={
            "n_files": len(per_file_psd),
            "per_file_psd_segments": per_file_psd,
            "num_workers": workers,
            "effective_serial_units": total_psd / workers,
        },
    )


def resolve_formal_workloads(
    train_sample_set: SampleSet,
    eval_sample_set: SampleSet,
    *,
    seg_size: int,
    profile: DatasetProfile,
    batch_size: int,
    train_portion: float | None,
    epochs: int,
    inference_batch_size: int,
    scoring_num_workers: int,
    drop_last: bool = True,
) -> dict[RuntimePhase, ResolvedPhaseWorkload]:
    """Resolve the compute-phase workloads of one formal attempt.

    Training runs on ``train_sample_set``; inference and scoring run on
    ``eval_sample_set`` (the tuner's evaluation scope). Setup and
    orchestration have no unit-count resolvers — they are measured
    (§2.2) or bounded (§2.7) rather than unit-priced.
    """
    return {
        "training": resolve_training_workload(
            train_sample_set,
            seg_size=seg_size,
            profile=profile,
            batch_size=batch_size,
            train_portion=train_portion,
            epochs=epochs,
            drop_last=drop_last,
        ),
        "inference": resolve_inference_workload(
            eval_sample_set,
            seg_size=seg_size,
            inference_batch_size=inference_batch_size,
            profile=profile,
        ),
        "scoring": resolve_scoring_workload(
            eval_sample_set,
            num_workers=scoring_num_workers,
        ),
    }


def scoring_prediction_from_server_config(
    workload: ResolvedPhaseWorkload,
    *,
    per_psd_segment_seconds: float,
    hostname: str,
    num_workers: int,
):
    """Historically-calibrated scoring prediction (§2.7, RT2-E).

    The per-host ``ServerConfig.per_psd_segment_seconds`` (measured
    single-process sequential scoring throughput) is the §2.7
    "historically_calibrated" evidence class. Individually never
    formal-eligible; admissible into a formal total only through the
    contribution-based share rule (operator decision 2026-07-23).

    The parallel model assumes linear speedup across ``num_workers`` —
    recorded explicitly in the evidence so the assumption is auditable
    (§2.9: aggregation logic explicit and testable).

    Raises:
        ValueError: non-positive throughput or workers.
    """
    from core.runtime_control.total_assembly import evidence_backed_prediction

    if per_psd_segment_seconds <= 0:
        raise ValueError(
            f"per_psd_segment_seconds must be positive; got {per_psd_segment_seconds!r}."
        )
    if num_workers <= 0:
        raise ValueError(f"num_workers must be positive; got {num_workers!r}.")
    predicted = workload.unit_count * per_psd_segment_seconds / num_workers
    return evidence_backed_prediction(
        predicted_seconds=predicted,
        source="historical_observation_prior",
        confidence="medium",
        unit_count=workload.unit_count,
        evidence={
            "classification": "historically_calibrated",
            "per_psd_segment_seconds": per_psd_segment_seconds,
            "hostname": hostname,
            "num_workers": num_workers,
            "parallel_model": "linear_speedup_assumed",
        },
    )
