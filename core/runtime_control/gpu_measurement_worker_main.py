"""The isolated process that measures one candidate on one phase.

V20 PR C2 / C2-2. Run as::

    python -m core.runtime_control.gpu_measurement_worker_main <spec.json>

in its own process group, launched by the parent (C2-3). Everything
expensive happens here and nowhere else -- model construction, the real
data batch, the real optimizer, the real forward/backward/step -- so the
parent stays small enough to survive whatever this process does. Nothing
large crosses back: only a bounded `WorkerMeasurementReport`.

WHAT THIS PROCESS IS FOR. `sandbox_executor.py:489` reads the requirement
PR B admits on, and nothing populates it, so formal admission reports
`policy_unavailable` forever. The audit established that neither existing
probe can fill it: PR A's isolated worker never calls `backward()`
(`structural_probe.py:177`, and `:201` raises if it does), and
`probe_production.py` is in-process and resets the CUDA peak once in
`_setup()`, so its number is a running maximum over setup + training +
inference. Option (a) -- a new worker with both properties -- was approved
on 2026-08-03.

THREE THINGS IT REFUSES TO DO.

1. **No CPU fallback.** A CUDA request on a host without CUDA returns
   `DEVICE_UNAVAILABLE`. A CPU number carrying a GPU requirement's
   provenance is the failure this whole PR exists to prevent, and it would
   under-state by the entire device footprint.
2. **No synthetic data.** The batch is real, resolved from the dataset root
   the caller supplied (F-1a). A missing dataset is a reported failure.
3. **No LLM.** This process makes no model calls of any kind. It is on the
   critical path of every formal launch, and a network call there would put
   an external service between a candidate and its GPU.

WHAT IT MEASURES, AND WHAT IT KNOWINGLY DOES NOT. It measures the phase's
allocator peaks per phase, and marks the wall-clock window the parent
samples the driver over. It does NOT reproduce a `DataLoader` pipeline, a
full epoch, or two concurrent chains -- every one of those axes can only
push a real phase HIGHER than this measurement, which is why the coverage
and completeness the parent records travel with the number.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from core.runtime_control.gpu_measurement_identity import build_realized_identity
from core.runtime_control.gpu_measurement_phases import (
    CandidateComponents,
    PhaseJournal,
    run_measured_phases,
)
from core.runtime_control.gpu_measurement_spec import (
    GpuMeasurementSpec,
    WorkerMeasurementReport,
    WorkerStatus,
)
from core.runtime_control.gpu_milestone_trace import tracer_from_environment


class DeviceResolution:
    """What device this process is actually on, and whether it is the one
    that was asked for."""

    __slots__ = ("detail", "device_name", "observed_uuid", "status")

    def __init__(
        self,
        status: WorkerStatus | None,
        *,
        observed_uuid: str | None = None,
        device_name: str | None = None,
        detail: str = "",
    ) -> None:
        #: `None` means "usable"; anything else is the terminal status.
        #
        # Annotated explicitly: pyright WIDENS literal types when it infers
        # an attribute's declared type from an assignment, so `self.status`
        # would be inferred `str | None` even though the parameter is
        # `WorkerStatus | None` -- and every caller passing it on to
        # `WorkerMeasurementReport(status=...)` is then rejected under
        # strict. Type-only: the value assigned is unchanged.
        self.status: WorkerStatus | None = status
        self.observed_uuid = observed_uuid
        self.device_name = device_name
        self.detail = detail


def _normalize_uuid(raw: object) -> str:
    """The driver's `GPU-<uuid>` form, from whatever torch returns.

    `torch.cuda.get_device_properties(i).uuid` is a `uuid.UUID`, whose
    string form has no `GPU-` prefix; `nvidia-smi` and `DeviceIdentity`
    both use the prefixed form. Normalizing in one place keeps a UUID
    comparison from failing on punctuation and being read as a
    wrong-device refusal.
    """
    text = str(raw).strip()
    return text if text.upper().startswith("GPU-") else f"GPU-{text}"


def resolve_device(spec: GpuMeasurementSpec) -> DeviceResolution:
    """Confirm the process is on the device the request names.

    Fails closed in both directions: an unreadable UUID is a mismatch, not
    an assumed match. Answering about the wrong GPU is worse than not
    answering -- `gpu_accounting` refuses a substituted device for the same
    reason.
    """
    if not spec.device.startswith("cuda"):
        # Only tests ask for a non-CUDA device. It is allowed to RUN, and
        # it can never become authoritative: `observed_device_uuid` stays
        # None and the authority contract's UUID match cannot succeed.
        return DeviceResolution(None, detail=f"non-CUDA device {spec.device!r}")

    try:
        import torch
    except ImportError as exc:
        return DeviceResolution("DEVICE_UNAVAILABLE", detail=f"torch is not importable: {exc}")

    if not torch.cuda.is_available():
        return DeviceResolution(
            "DEVICE_UNAVAILABLE",
            detail=(
                f"{spec.device!r} was requested and CUDA is not available; "
                "this measurement does not fall back to the CPU"
            ),
        )

    index = 0
    if ":" in spec.device:
        try:
            index = int(spec.device.split(":", 1)[1])
        except ValueError:
            return DeviceResolution(
                "DEVICE_UNAVAILABLE", detail=f"unparsable device string {spec.device!r}"
            )

    try:
        props = torch.cuda.get_device_properties(index)
    except Exception as exc:
        return DeviceResolution(
            "DEVICE_UNAVAILABLE", detail=f"device {index} is not addressable: {exc!r}"
        )

    raw_uuid = getattr(props, "uuid", None)
    if raw_uuid is None:
        return DeviceResolution(
            "DEVICE_MISMATCH",
            device_name=getattr(props, "name", None),
            detail=(
                "the driver exposed no UUID for this device, so it cannot be "
                "confirmed as the one requested; an unverifiable device is "
                "refused rather than assumed"
            ),
        )

    observed = _normalize_uuid(raw_uuid)
    name = getattr(props, "name", None)
    if observed != spec.request.device_uuid:
        return DeviceResolution(
            "DEVICE_MISMATCH",
            observed_uuid=observed,
            device_name=name,
            detail=(f"measured on {observed} but the request names {spec.request.device_uuid}"),
        )
    return DeviceResolution(None, observed_uuid=observed, device_name=name)


#: The MEASUREMENT site's input-dtype preference (Step 07 / PR 07c, Q-07c-8).
#:
#: Declared once, here, rather than inlined at the call: it is this site's
#: historical dtype and the reason 07c's batches are byte-identical. It is
#: deliberately NOT the phase-correct inference dtype — the measurement worker
#: runs an inference phase at the production inference batch, so a phase-aware
#: preference is arguably more faithful, but adopting it would CHANGE what is
#: measured, and 07c's whole claim is that it does not. Recorded as separate
#: debt.
_MEASUREMENT_DTYPE_PREFERENCE = "int32"


def build_production_components(spec: GpuMeasurementSpec, trace: Any = None):
    """A builder that constructs exactly what the phase will really run.

    Returns a zero-argument callable so construction happens INSIDE the
    setup window, where it is measured.

    Every choice below mirrors `execute_tools/train_engine_sandbox.py`
    rather than approximating it:

    * the model comes from the LIVE `MODEL_REGISTRY` -- the validator has
      just registered the candidate, and the LLM's parameter estimate is
      never used (F-1b);
    * the model is constructed through `construct_registered_model`, so a
      class whose head shape depends on `loss_type` receives it — decided by
      introspecting the constructor, never by matching a model name
      (07c C3 / Q-07c-3);
    * the optimizer comes from `build_training_optimizer`, the trainer's
      own switch, because Adam-family moments are a first-order term in
      the memory being measured;
    * the input dtype comes from `resolve_input_dtype` — the model's own
      declaration where it has one, else the task's Model-I/O contract, else
      this site's historical preference — and the target dtype from
      `get_target_torch_dtype`, both the trainer's single sources of truth;
    * input and target are DISTINCT tensors, because the trainer holds two.

    `class_weights=None` matches the streaming trainer
    (`run_experiment_streaming`), which is the production path; the weight
    vector is 256 elements and cannot move a GB-scale measurement either
    way.
    """

    def _build() -> CandidateComponents:
        from core.runtime_control.gpu_measurement_data import load_bounded_probe_batch
        from execute_tools.model_input_dtype import resolve_input_dtype
        from execute_tools.train_engine_sandbox import build_training_optimizer
        from ml_models.loss_models_sandbox import get_criterion, get_target_torch_dtype
        from ml_models.models_format_sandbox import (
            LossConfig,
            TrainConfig,
            get_config_class,
        )
        from ml_models.models_sandbox import MODEL_REGISTRY, construct_registered_model

        model_type = spec.request.model_type
        if model_type not in MODEL_REGISTRY:
            raise RuntimeError(
                f"model_type {model_type!r} is not in the live MODEL_REGISTRY — "
                "the measurement must run AFTER validation/registration"
            )
        config_cls = get_config_class(model_type)
        if config_cls is None:
            raise RuntimeError(f"no config class registered for {model_type!r}")

        model_cfg = config_cls(**spec.model_config_payload)
        train_cfg = TrainConfig(**spec.train_config)
        loss_cfg = LossConfig(**spec.loss_config)

        # Construction and transfer split into two statements so a
        # milestone can sit between them (V20 PR C2, validation only), and
        # split the SAME way `inference_single.py` is, so the two traces
        # bracket the same operation. `nn.Module.to()` moves parameters in
        # place and returns `self`: the chained and split forms perform an
        # identical sequence on an identical object.
        #
        # 07c C3 / Q-07c-3: whether the constructor takes `loss_type` is read
        # from its SIGNATURE by the shared owner beside the registry. The name
        # branch this replaces was wrong for any generated plugin whose head
        # shape depends on the loss — it would silently build the wrong model
        # and measure it.
        model = construct_registered_model(model_type, model_cfg, loss_type=loss_cfg.loss_type)
        if trace is not None:
            trace.record(
                "after_model_construction",
                model=model,
                detail="constructed on host from the live MODEL_REGISTRY; no checkpoint",
            )
        model = model.to(spec.device)
        if trace is not None:
            trace.record("after_model_to_device", synchronize=True, model=model)

        if not spec.data_dir or not os.path.isdir(spec.data_dir):
            raise RuntimeError(
                f"dataset directory unavailable for the measurement: "
                f"{spec.data_dir!r} (no silent synthetic fallback — F-1a)"
            )
        # C12-P / B11. Paired with `build_planned_identity`, whose docstring
        # states the invariant explicitly: "the defaults for `seg_size` and
        # `batch_size` are the same ones the measurement worker will apply, so
        # the two sides cannot disagree because one of them filled a blank
        # differently." Both sides now fill the blank through the SAME
        # authority, so the invariant holds for a model whose declared default
        # is not 40 000 as well.
        from agent.skills.training_skill.estimator import resolve_model_field

        seg = resolve_model_field(
            model_type, spec.model_config_payload, "segmentation_size", safety_margin=40_000
        )
        # TWO batches, deliberately distinct.
        #
        # `batch_size` is the TRAINING batch. It is the identity field C1's
        # hash uses, so it must keep meaning the same thing in every phase;
        # overloading it with the inference batch made every inference
        # measurement mismatch its own request.
        #
        # `input_batch` is what the measured tensor is actually built at:
        # the training batch for a training phase, the production inference
        # batch for an inference phase. Using the training batch there is
        # the attempt-6 under-read -- 1050 MiB reported for a phase that
        # really held 3642 MiB.
        batch_size = int(spec.train_config.get("batch_size", 1))
        input_batch = (
            int(spec.inference_batch_size)
            if spec.phase == "inference" and spec.inference_batch_size
            else batch_size
        )
        # D-C2-12. BOUNDED read. The predecessor materialized the whole
        # 2,010,000,000-sample channel before `max_segments` applied, and
        # Gate 2 Lite-A c1 was killed at 24.10 GiB host RSS before the model
        # was even built -- to produce a batch occupying 0.31 MiB on the GPU.
        # The tensor is byte-identical (pinned against the pre-refactor golden
        # in `test_gpu_measurement_data.py`); only the host-side path differs,
        # and the host path is not the GPU requirement. There is no fallback:
        # bounded access failing is an infrastructure condition.
        #
        # 07c C2: the batch's data facts -- input channel, value encoding,
        # training filename family -- come from the profile the PARENT
        # transported. This process is clean, so an ambient resolution here
        # would always answer TIDMAD regardless of the bound task.
        bounded = load_bounded_probe_batch(
            data_dir=spec.data_dir,
            batch_size=input_batch,
            segment_length=seg,
            profile=spec.dataset_profile,
        )
        batch = bounded.tensor.to(spec.device)

        # 07c C3 / Q-07c-8. The dtype authority, not a model name. The site
        # preference stays `int32` -- the MEASUREMENT site's historical dtype,
        # which reproduces today's tensor exactly for every builtin in both
        # phases, with and without a transported contract. Adopting the
        # phase-correct inference dtype is recorded as separate debt: it would
        # change what is measured, and this PR's whole claim is that it does
        # not.
        model_input = batch.to(
            resolve_input_dtype(
                model_type, spec.model_io_contract, site_preference=_MEASUREMENT_DTYPE_PREFERENCE
            )
        )
        if trace is not None:
            # The same point `inference_single.py` records: the input is on
            # the device in the dtype the model will be handed. What the
            # probe allocates AFTER this — `loss_target`, the optimizer —
            # has no formal-inference counterpart, so it deliberately falls
            # on the far side of this milestone where the comparison can
            # see it rather than inside it.
            trace.record(
                "after_input_to_device",
                batch_index=0,
                synchronize=True,
                model=model,
                model_input=model_input,
            )
        target_dtype = get_target_torch_dtype(loss_cfg)
        loss_target = batch.to(dtype=target_dtype)
        if loss_target is batch:
            # `.to()` on a matching dtype returns the SAME object, which
            # would leave one fewer tensor resident than the trainer holds.
            loss_target = batch.clone()

        optimizer = build_training_optimizer(model, train_cfg)
        loss_fn = get_criterion(loss_cfg, class_weights=None)

        total = int(sum(p.numel() for p in model.parameters()))
        trainable = int(sum(p.numel() for p in model.parameters() if p.requires_grad))
        # D-C2-7. THE authoritative measurement identity, and the only
        # place it can exist: `precision` and the parameter counts come
        # from the instantiated module, which the parent is forbidden to
        # build. The hash is C1's canonical one, called not restated.
        realized = build_realized_identity(
            model_type=model_type,
            optimizer_type=str(getattr(train_cfg, "optimizer_type", "adamw")),
            seg_size=seg,
            # The batch actually used, whichever phase this is.
            batch_size=batch_size,
            precision=str(next(model.parameters()).dtype).replace("torch.", ""),
            parameter_count=total,
            trainable_parameter_count=trainable,
            inference_batch_size=spec.inference_batch_size,
        )
        return CandidateComponents(
            model=model,
            model_input=model_input,
            loss_target=loss_target,
            optimizer=optimizer,
            loss_fn=loss_fn,
            parameter_count=total,
            trainable_parameter_count=trainable,
            realized_identity=realized,
            bounded_read=bounded.evidence,
        )

    return _build


def validate_candidate_configs(spec: GpuMeasurementSpec) -> str | None:
    """Reject an unusable configuration BEFORE the setup window opens.

    Two reasons it happens here rather than inside the builder. A schema
    rejection is a fact about the configuration, not a measurement, and it
    must not be reported as a failed measurement of the candidate. And
    validation costs nothing, so leaving it inside the timed window would
    add construction noise to every setup figure.

    Returns the rejection message, or `None` when the configuration is
    usable.
    """
    try:
        from ml_models.models_format_sandbox import (
            LossConfig,
            TrainConfig,
            get_config_class,
        )

        # ``get_config_class`` reads ``PLUGIN_CONFIG_REGISTRY``, which is
        # populated as an IMPORT SIDE EFFECT of ``models_sandbox``
        # (models_sandbox.py:750-753 calls ``extend_registries``). Importing
        # only ``models_format_sandbox`` leaves it empty, so every
        # agent-generated model resolved to ``None`` here and was reported as
        # CONFIG_REJECTED — while ``build_production_components`` (which does
        # import ``models_sandbox``) resolved the same model fine. That
        # asymmetry cost V20 attempt 3 all 15 formal promotions. The import
        # must stay; ``MODEL_REGISTRY`` is read below so it cannot be
        # dropped as unused.
        from ml_models.models_sandbox import MODEL_REGISTRY

        config_cls = get_config_class(spec.request.model_type)
        if config_cls is None:
            return (
                f"no config class registered for {spec.request.model_type!r} "
                f"({len(MODEL_REGISTRY)} model(s) in the live registry)"
            )
        config_cls(**spec.model_config_payload)
        TrainConfig(**spec.train_config)
        LossConfig(**spec.loss_config)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _marker_waiter(path: str | None, budget_seconds: float):
    """Block until the parent touches `path`, or give up loudly.

    Used for the sampler-ready handshake. The parent touches it only after
    a REAL driver sample succeeds, so this is evidence rather than a
    promise: without it a fast phase can open, run and close before the
    first poll, which is what Gate 2 Lite-A c7 did.

    Returns `None` when no path was supplied, so the handshake is opt-in by
    configuration rather than silently skipped.
    """
    if not path:
        return None
    marker = Path(path)

    def _wait() -> bool:
        deadline = time.monotonic() + budget_seconds
        while time.monotonic() < deadline:
            if marker.exists():
                return True
            time.sleep(0.01)
        # Timing out is reported on the phase, not raised: the phase can
        # still run, and the parent's own coverage decides whether what it
        # saw is admissible.
        return False

    return _wait


def _marker_probe(path: str | None):
    """Non-blocking check for the parent's phase-completion signal.

    The parent touches this once it has COUNTED enough valid in-phase
    samples. That is the only place the count is known, which is why the
    stop condition lives there and not in a repetition limit here.
    """
    if not path:
        return None
    marker = Path(path)
    return marker.exists


def _write_report(path: str, report: WorkerMeasurementReport) -> None:
    """Atomic and bounded: a partially written report must never be read
    as a complete one."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    tmp.replace(target)


def measure(spec: GpuMeasurementSpec, trace: Any = None) -> WorkerMeasurementReport:
    """Resolve the device, validate the configuration, run the phases.

    Returns a report for every path. It raises only for a programming
    error -- every outcome the O-7 boundary has a rule for is a value.

    `trace` is an optional `MilestoneTracer` (V20 PR C2, validation only).
    `None` in production; nothing here calls it when absent.
    """
    base: dict[str, Any] = {
        "label": spec.label,
        "request": spec.request,
        "device": spec.device,
        "worker_pid": os.getpid(),
        "request_id": spec.request.request_id,
    }

    resolution = resolve_device(spec)
    if resolution.status is not None:
        return WorkerMeasurementReport(
            **base,
            status=resolution.status,
            observed_device_uuid=resolution.observed_uuid,
            device_name=resolution.device_name,
            detail=resolution.detail,
        )

    # V20 PR C2, validation only. `resolve_device` is where this process
    # first imports torch AND where `get_device_properties` lazily creates
    # the CUDA context, so both milestones fall here. That the two land at
    # one point on this side and at different points on the formal side is
    # a real structural difference between the paths, recorded rather than
    # smoothed over: `cuda_initialized` on each record states which is true.
    if trace is not None:
        trace.record("after_imports")
        trace.record("after_cuda_init", detail=f"device={spec.device}")

    rejection = validate_candidate_configs(spec)
    if rejection is not None:
        return WorkerMeasurementReport(
            **base,
            status="CONFIG_REJECTED",
            observed_device_uuid=resolution.observed_uuid,
            device_name=resolution.device_name,
            detail=rejection[:400],
        )

    outcome = run_measured_phases(
        build_components=build_production_components(spec, trace),
        phase=spec.phase,
        device=spec.device,
        training_steps=spec.training_steps,
        inference_batches=spec.inference_batches,
        journal=PhaseJournal(spec.journal_path),
        soft_deadline_seconds=spec.soft_deadline_seconds,
        min_authoritative_samples=spec.min_authoritative_samples,
        max_phase_seconds=spec.max_phase_seconds,
        await_sampler_ready=_marker_waiter(
            spec.sampler_ready_path, spec.sampler_ready_timeout_seconds
        ),
        # Training polls (repeat until enough); inference BLOCKS (hold the
        # real state open until enough). A non-blocking probe here released
        # the hold instantly and only one sample landed.
        phase_observed_enough=(
            _marker_waiter(spec.phase_complete_path, spec.max_phase_seconds)
            if spec.phase == "inference"
            else _marker_probe(spec.phase_complete_path)
        ),
        trace=trace,
    )
    return WorkerMeasurementReport(
        **base,
        status=outcome.status,
        observed_device_uuid=resolution.observed_uuid,
        device_name=resolution.device_name,
        phases=outcome.phases,
        realism=outcome.realism,
        realized_identity=outcome.realized_identity,
        detail=outcome.detail,
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: gpu_measurement_worker_main <spec.json>", file=sys.stderr)
        return 2

    spec = GpuMeasurementSpec(**json.loads(Path(args[0]).read_text(encoding="utf-8")))
    print(
        f"[gpu-measure] {spec.label}: {spec.request.model_type} "
        f"phase={spec.phase} device={spec.device}",
        flush=True,
    )

    # V20 PR C2, validation only. `None` — and wholly inert — unless
    # SIDERIUS_C2_INFERENCE_MILESTONE_TRACE names a channel, which
    # production never does. Constructed after the spec is parsed because
    # the phase is part of every record; that read is a small JSON file and
    # touches no device, so `process_start` still precedes all GPU work.
    trace = tracer_from_environment(side="prephase_inference", phase=spec.phase)
    if trace is not None:
        trace.set_candidate(
            {
                "model_type": spec.request.model_type,
                "phase": spec.phase,
                "label": spec.label,
                "request_id": spec.request.request_id,
            },
            inference_batch_size=spec.inference_batch_size,
        )
        trace.record("process_start", detail="worker entry; torch not yet imported")

    try:
        report = measure(spec, trace)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        # The measurement system itself broke. That is not a property of
        # the candidate, and it must not be reported as one.
        report = WorkerMeasurementReport(
            label=spec.label,
            request=spec.request,
            device=spec.device,
            worker_pid=os.getpid(),
            status="WORKER_FAILURE",
            request_id=spec.request.request_id,
            detail=f"{type(exc).__name__}: {exc}"[:400],
        )
        _write_report(spec.result_path, report)
        return 1

    _write_report(spec.result_path, report)
    if trace is not None:
        trace.record("before_exit", synchronize=True, detail=f"status={report.status}")
    print(f"[gpu-measure] {spec.label}: {report.status}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
