"""Pre-flight VRAM gate — Phase 6.6 §3.7.

Replaces the Phase K "empirical polling" wrapper with a deterministic
forecast built from five primitives that all landed earlier in the
phase:

  * ``structural_probe.probe_activation_footprint``  (§3.2, A.2)
  * ``overhead`` {``training_overhead_bytes``, ``cuda_context_bytes``,
     ``cudnn_backward_workspace_bytes``}                (§3.3, A.3)
  * ``batch_resolver.resolve_inference_batch``       (§3.5, A.4)
  * ``compute_intensity.passes``                     (§3.10, A.4.5)
  * ``killer_report.{render_vram,render_intensity,render_combined}``
                                                      (§3.6, A.5)

The wrapper is the single consumer that glues them together. Training
and inference run in isolated subprocesses (``core.sandbox_executor``),
so the binding cap is the single phase with the larger peak, not their
sum — the wrapper probes both, composes each peak from the probe's
primitives plus overhead, and takes ``max()`` (§3.8).

Return contract (§3.7)
----------------------
Preserved (same semantics as Phase K):
    status, feasible, verdict, suggestion, num_params,
    dominant_phase, phase_breakdown,
    estimated_gb, limit_gb, vram_budget_gb

New:
    inference_batch  — int chosen by ``resolve_inference_batch``
    memory_killer    — dict (flattened ``killer_report.MemoryKillerDetails``)
                       on an infeasible verdict, ``None`` otherwise.

Removed:
    inference_batch_uncalibrated — obsolete now every batch is probed.
    torch.cuda.mem_get_info      — the cap is ``ctx.usable_cap_bytes``.
    4 GB minimum-free floor      — obsolete under the capacity-based cap.
    Contention log               — belongs to scheduling, not forecasting.
"""

from __future__ import annotations

import gc
import inspect
import signal
from contextlib import contextmanager

import psutil
import torch
from pydantic import ValidationError

from agent.skills.evaluate_vram_skill import compute_intensity, killer_report
from agent.skills.evaluate_vram_skill.batch_resolver import resolve_inference_batch
from agent.skills.evaluate_vram_skill.overhead import (
    cuda_context_bytes,
    cudnn_backward_workspace_bytes,
    training_overhead_bytes,
)
from agent.skills.evaluate_vram_skill.structural_probe import (
    ProbeResult,
    probe_activation_footprint,
)
from core.hardware_context import HardwareContext, discover
from ml_models.loss_models_sandbox import get_criterion, get_target_torch_dtype
from ml_models.models_format_sandbox import LossConfig, get_config_class
from ml_models.models_sandbox import MODEL_REGISTRY

# ── Constants ────────────────────────────────────────────────────────────────

_GB: int = 1024**3
# Training defaults mirror the project-wide pipeline: Adam-family. Proposer
# configs that use a different optimizer populate ``train_config.optimizer``
# explicitly; ``overhead.training_overhead_bytes`` hard-errors on anything
# it does not recognise, so there is no silent fallback downstream.
_DEFAULT_OPTIMIZER: str = "adam"
# I14 — target dtype routing now reads from each loss plugin's
# ``PLUGIN_LOSS_TARGET_DTYPE`` declaration via ``get_target_torch_dtype``
# rather than a hardcoded float-target loss list. The probe's
# training-mode forward runs ``loss_module(logits, target)``, so target
# shape (and dtype) has to match what the loss's forward expects or the
# probe crashes. Long-dtype losses get ``[B, T]`` class-index targets;
# float-dtype losses get ``[B, 256, T]`` broadcast-shaped targets matching
# the model's logits. See ``docs/design/enable_loss_inventory.md`` § I14.

# Hard ceiling on a single forward-pass probe call. A Python time-loop
# inside `forward()` at long T will burn host RAM linearly under autograd;
# at T=200,000 the V11 kill mode reached 28 GB anon-rss before the kernel
# OOM-killed the process. SIGALRM trips long before that point.
_FORWARD_PASS_TIMEOUT_S: int = 60


class ForwardPassTimeoutError(Exception):
    """Raised when a probe's forward pass exceeds ``_FORWARD_PASS_TIMEOUT_S``."""


@contextmanager
def _forward_pass_timeout(seconds: int, label: str):
    """SIGALRM-based watchdog around a forward-pass probe call.

    On Linux, installs a SIGALRM handler that raises
    ``ForwardPassTimeoutError`` after ``seconds`` of wall time. On
    platforms without SIGALRM (e.g. Windows), the watchdog is a no-op —
    the production target is Linux, and CI mocks the probe.
    """
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise ForwardPassTimeoutError(
            f"Forward-pass probe '{label}' exceeded {seconds}s. "
            f"Most common cause: a Python `for`/`while` loop over the "
            f"time dimension inside `nn.Module.forward(...)`. Use "
            f"vectorized ops (FFT, linear attention, associative scans)."
        )

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


# ── Model / loss instantiation helpers ──────────────────────────────────────


def _build_model(model_type: str, model_cfg: dict, loss_type: str) -> torch.nn.Module:
    """CPU-instantiate a model by pushing ``model_cfg`` through the plugin's
    config class + registered model class.

    A ``pydantic.ValidationError`` from the config class indicates the
    proposer violated a schema bound or a ``@model_validator`` invariant.
    Callers catch it and emit the Phase D.4 ``schema_violation`` record.
    """
    config_cls = get_config_class(model_type)
    if config_cls is None:
        raise ValueError(
            f"_build_model: unknown model_type={model_type!r} — "
            f"get_config_class returned None (no plugin or built-in config registered)."
        )
    config_obj = config_cls(**model_cfg)
    model_cls = MODEL_REGISTRY[model_type]
    # Principle 2: no architecture-family branching. A registered model
    # class may optionally accept ``loss_type`` (used when the model's
    # head shape depends on the loss — e.g. AE + smooth_l1 regression).
    # Introspect the constructor signature to decide, so adding a new
    # plugin with the same requirement needs no wrapper edit.
    if "loss_type" in inspect.signature(model_cls.__init__).parameters:
        return model_cls(config_obj, loss_type=loss_type)
    return model_cls(config_obj)


def _build_probe_tensors(
    batch_size: int,
    seg_size: int,
    loss_type: str,
    loss_name: str | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Zero-valued ``(input, target)`` pair matching the SIDERIUS forward
    contract. Both tensors live on CPU; the probe will ``.to(device)`` them
    if the caller asks for CUDA (we don't, here).

    I14 — target dtype is read from the loss plugin's declared
    ``PLUGIN_LOSS_TARGET_DTYPE`` (via ``get_target_torch_dtype``), with the
    shape derived from the dtype: long-targets are class-index ``[B, T]``;
    float-targets broadcast against the model's ``[B, 256, T]`` logits.
    """
    inp = torch.zeros((batch_size, seg_size), dtype=torch.long)
    # Dict-unpack to mirror the existing ``LossConfig(**loss_cfg)`` pattern
    # at the run_skill site (line ~469); avoids a Literal-narrowing pyright
    # error when ``loss_type`` arrives as a plain ``str``.
    target_dtype = get_target_torch_dtype(
        LossConfig(**{"loss_type": loss_type, "loss_name": loss_name})
    )
    if target_dtype == torch.long:
        tgt = torch.zeros((batch_size, seg_size), dtype=torch.long)
    else:
        tgt = torch.zeros((batch_size, 256, seg_size), dtype=target_dtype)
    return inp, tgt


# ── Peak composition (§3.3) ──────────────────────────────────────────────────


def _compose_training_peak(probe: ProbeResult, optimizer: str) -> tuple[int, dict]:
    """``autograd_tape + input + output + params + training_overhead +
    cuda_context + cudnn_backward_workspace``.

    ``probe.autograd_tape`` is only populated when the probe ran in
    training-mode (backward-capable). Composing the training peak when
    it is ``None`` would silently drop the largest term — raise instead
    so the caller catches the contract violation explicitly.
    """
    if probe.autograd_tape is None:
        raise ValueError(
            "_compose_training_peak requires probe.autograd_tape to be populated "
            "(got None) — caller passed an inference-only probe."
        )
    params_bytes = probe.model_forward.total_param_bytes
    saved_bytes = probe.autograd_tape.total_saved_bytes
    overhead = training_overhead_bytes(params_bytes, optimizer)
    ctx = cuda_context_bytes()
    cudnn_bw = cudnn_backward_workspace_bytes()

    total = (
        saved_bytes
        + probe.input_bytes
        + probe.output_bytes
        + params_bytes
        + overhead
        + ctx
        + cudnn_bw
    )
    breakdown = {
        "autograd_tape_bytes": saved_bytes,
        "input_bytes": probe.input_bytes,
        "output_bytes": probe.output_bytes,
        "param_bytes": params_bytes,
        "training_overhead_bytes": overhead,
        "cuda_context_bytes": ctx,
        "cudnn_backward_bytes": cudnn_bw,
    }
    return total, breakdown


def _compose_inference_peak(probe: ProbeResult) -> tuple[int, dict]:
    """``input + max(output_bytes, forward_output_bytes_max) + params +
    cuda_context``. Uses ``max()`` on the two output-shape proxies
    because for sequential models the last layer's output equals the
    final ``output_bytes``; for branched models a mid-network layer may
    be larger. Neither is a sum — the allocator reuses transient
    buffers under ``no_grad``."""
    params_bytes = probe.model_forward.total_param_bytes
    peak_out = max(probe.output_bytes, probe.model_forward.forward_output_bytes_max)
    ctx = cuda_context_bytes()

    total = probe.input_bytes + peak_out + params_bytes + ctx
    breakdown = {
        "input_bytes": probe.input_bytes,
        "max_output_bytes": peak_out,
        "param_bytes": params_bytes,
        "cuda_context_bytes": ctx,
    }
    return total, breakdown


# ── Schema-violation helpers (preserved from Phase D.4) ─────────────────────


def _extract_schema_violations(exc: ValidationError) -> list[dict]:
    """Serialize every pydantic error into a per-field record the tuner's
    planner can read back via the saved ``skipped_schema_violation`` record."""
    out: list[dict] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "__root__"
        out.append(
            {
                "loc": loc,
                "type": err.get("type", "unknown"),
                "msg": err.get("msg", ""),
                "input": err.get("input"),
            }
        )
    return out


def _format_schema_violation_verdict(violations: list[dict]) -> str:
    if not violations:
        return "Schema rejected config (no details)."
    parts = [f"{v['loc']}={v.get('input')!r} ({v['type']})" for v in violations[:3]]
    extra = "" if len(violations) <= 3 else f" (+{len(violations) - 3} more)"
    return "Schema rejected config: " + "; ".join(parts) + extra


def _schema_violation_response(violations: list[dict], offending_cfg: dict) -> dict:
    verdict = _format_schema_violation_verdict(violations)
    print(f"    SCHEMA REJECT: {verdict}")
    return {
        "status": "schema_violation",
        "violations": violations,
        "offending_config": offending_cfg,
        "message": verdict,
        "verdict": verdict,
        "suggestion": (
            "Propose a config that satisfies the plugin's schema invariants. "
            "DO NOT repeat the same field/value combination."
        ),
    }


# ── Killer-report routing ───────────────────────────────────────────────────


def _parse_binding_label(exc_msg: str) -> str:
    """``resolve_inference_batch`` raises ``ValueError`` whose message contains
    ``Binding cap(s): <label>.``. Extract just the label (``vram``,
    ``compute_intensity``, or ``vram+compute_intensity``) so the wrapper can
    dispatch to the right killer-report renderer."""
    parts = exc_msg.split("Binding cap(s):", 1)
    if len(parts) < 2:
        return "vram"
    return parts[1].split(".", 1)[0].strip()


def _render_inference_killer(
    *,
    binding: str,
    model_type: str,
    model_cfg: dict,
    loss_type: str,
    seg_size: int,
    cap_bytes: int,
    total_memory_bytes: int,
) -> killer_report.KillerReport:
    """Build a killer report for the inference-resolver-failed case.

    The resolver exits with a ``ValueError`` after exhausting its candidate
    list; it does not hand back the probes it consumed along the way. For
    VRAM-binding failures we re-probe the model once at ``B=1`` so the
    per-layer attribution the Proposer reads is faithful to the failing
    mode (inference, not training)."""
    if binding == "compute_intensity":
        # Intensity failure at ``B=1`` means ``1 × T > 800_000`` — a pure
        # ``segmentation_size`` problem, no layer attribution required.
        return killer_report.render_intensity_report(
            batch_size=1,
            segmentation_size=seg_size,
        )

    model_tmp = _build_model(model_type, model_cfg, loss_type)
    inf_probe = probe_activation_footprint(
        model=model_tmp,
        loss_module=None,
        input_sample=torch.zeros((1, seg_size), dtype=torch.long),
        target_sample=None,
        mode="inference",
    )
    inf_peak, _ = _compose_inference_peak(inf_probe)
    if binding == "vram+compute_intensity":
        return killer_report.render_combined_report(
            probe=inf_probe,
            predicted_peak_bytes=inf_peak,
            cap_bytes=cap_bytes,
            total_memory_bytes=total_memory_bytes,
            batch_size=1,
            segmentation_size=seg_size,
        )
    return killer_report.render_vram_report(
        probe=inf_probe,
        predicted_peak_bytes=inf_peak,
        cap_bytes=cap_bytes,
        total_memory_bytes=total_memory_bytes,
    )


def _render_killer(
    *,
    training_probe: ProbeResult,
    training_peak: int,
    training_vram_ok: bool,
    training_intensity_ok: bool,
    inference_ok: bool,
    inference_err: str | None,
    model_type: str,
    model_cfg: dict,
    loss_type: str,
    batch_size: int,
    seg_size: int,
    cap_bytes: int,
    total_memory_bytes: int,
) -> killer_report.KillerReport:
    """Pick the right renderer based on which cap(s) bound the refusal.

    Training-phase failures take precedence over inference-phase ones
    because training is the more expensive phase to run (autograd tape
    dominates memory + wall time). The attribution for a training
    failure uses the training probe we already have in hand.
    """
    if not training_vram_ok and not training_intensity_ok:
        return killer_report.render_combined_report(
            probe=training_probe,
            predicted_peak_bytes=training_peak,
            cap_bytes=cap_bytes,
            total_memory_bytes=total_memory_bytes,
            batch_size=batch_size,
            segmentation_size=seg_size,
        )
    if not training_vram_ok:
        return killer_report.render_vram_report(
            probe=training_probe,
            predicted_peak_bytes=training_peak,
            cap_bytes=cap_bytes,
            total_memory_bytes=total_memory_bytes,
        )
    if not training_intensity_ok:
        return killer_report.render_intensity_report(batch_size, seg_size)
    if not inference_ok:
        return _render_inference_killer(
            binding=_parse_binding_label(inference_err or ""),
            model_type=model_type,
            model_cfg=model_cfg,
            loss_type=loss_type,
            seg_size=seg_size,
            cap_bytes=cap_bytes,
            total_memory_bytes=total_memory_bytes,
        )
    raise RuntimeError("_render_killer called with no binding failure")


# ── Main entry ──────────────────────────────────────────────────────────────


def run_skill(sandbox, **kwargs):
    """Run the VRAM gate against the proposer's config.

    Required kwargs:
        model_type, model_config, train_config, loss_config

    Optional kwargs:
        vram_budget_gb   — operator-set soft cap. When set, the effective
                           cap is ``min(ctx.usable_cap_bytes,
                           int(vram_budget_gb * GB))``.
        hardware_context — ``HardwareContext`` instance. When ``None`` (e.g.
                           during intermediate-stage tests before A.11 wires
                           the tuner), the wrapper falls back to
                           ``core.hardware_context.discover()`` — the same
                           function ``get_or_create`` uses, so the cap is
                           physically correct but the manifest on disk is
                           not consulted.
    """
    # Principle 2: no default architecture. If the caller failed to pass
    # ``model_type``, a ``KeyError`` is the right signal — silently
    # defaulting to a specific family would re-introduce exactly the
    # branching this phase is eliminating.
    model_type = kwargs["model_type"]
    model_cfg = kwargs.get("model_config", {})
    train_cfg = kwargs.get("train_config", {})
    loss_cfg = kwargs.get("loss_config", {})
    vram_budget_gb: float | None = kwargs.get("vram_budget_gb")
    hardware_context: HardwareContext | None = kwargs.get("hardware_context")

    loss_type = loss_cfg.get("loss_type", "ce")
    # I14 — loss_name plumbs through to _build_probe_tensors so the helper
    # can route custom-loss target dtype via PLUGIN_LOSS_TARGET_DTYPE.
    loss_name = loss_cfg.get("loss_name")
    batch_size = int(train_cfg.get("batch_size", 1))
    seg_size = int(model_cfg.get("segmentation_size", 40000))
    optimizer = str(train_cfg.get("optimizer") or _DEFAULT_OPTIMIZER).lower()

    print(
        f"\n>>> [Skill: VRAMEval] Pre-flight for {model_type.upper()} "
        f"(B={batch_size}, T={seg_size}, loss={loss_type})..."
    )

    try:
        # 1. Hardware context → cap ──────────────────────────────────────
        if hardware_context is None:
            hardware_context = discover()
        physical_cap_bytes = hardware_context.usable_cap_bytes
        cap_bytes = physical_cap_bytes
        if vram_budget_gb is not None:
            cap_bytes = min(cap_bytes, int(vram_budget_gb * _GB))
        total_memory_bytes = hardware_context.total_memory_bytes

        # Classify which of the three cap regimes is active so the log line
        # is self-explanatory (the operator should not have to compare
        # numbers to figure out which cap won).
        if vram_budget_gb is None:
            cap_note = f"PHYSICAL: 80% of {hardware_context.total_memory_gb:.1f} GB"
        elif int(vram_budget_gb * _GB) > physical_cap_bytes:
            cap_note = (
                f"PHYSICAL VETO: budget {vram_budget_gb:.2f} GB requested exceeds 80% ceiling"
            )
        else:
            cap_note = f"BUDGET: restricted by operator from {physical_cap_bytes / _GB:.2f} GB"

        print(
            f"    [Hardware] {hardware_context.device_name} "
            f"({hardware_context.total_memory_gb:.1f} GB total) "
            f"| cap={cap_bytes / _GB:.2f} GB ({cap_note})"
        )

        # 2. Instantiate model (schema validation happens here) ───────────
        try:
            model_for_train = _build_model(model_type, model_cfg, loss_type)
            loss_module = get_criterion(LossConfig(**loss_cfg))
        except ValidationError as ve:
            return _schema_violation_response(
                _extract_schema_violations(ve),
                model_cfg,
            )
        num_params = sum(p.numel() for p in model_for_train.parameters())
        print(f"    Parameters : {num_params:,}")

        # CPU-only host: probing is still possible but the cap is 0. Honour
        # the device_available flag and short-circuit with a no-constraint
        # verdict so the tuner can still run on laptops / in CI. Preserves
        # the Phase K "CPU mode" pathway.
        if not hardware_context.device_available:
            print("    [Hardware] CPU-only host — skipping VRAM gate.")
            return {
                "status": "success",
                "feasible": True,
                "verdict": (f"CPU mode ({hardware_context.device_name}) — no VRAM constraint."),
                "suggestion": "",
                "num_params": num_params,
                "dominant_phase": "inference",
                "phase_breakdown": {},
                "estimated_gb": 0.0,
                "limit_gb": 0.0,
                "vram_budget_gb": vram_budget_gb,
                "inference_batch": 1,
                "memory_killer": None,
            }

        # 3. Training-phase probe ─────────────────────────────────────────
        rss_before = psutil.Process().memory_info().rss
        x_train, y_train = _build_probe_tensors(batch_size, seg_size, loss_type, loss_name)
        with _forward_pass_timeout(_FORWARD_PASS_TIMEOUT_S, "training_probe"):
            training_probe = probe_activation_footprint(
                model=model_for_train,
                loss_module=loss_module,
                input_sample=x_train,
                target_sample=y_train,
                mode="training",
            )
        training_peak, training_breakdown = _compose_training_peak(
            training_probe,
            optimizer,
        )
        training_vram_ok = training_peak <= cap_bytes
        training_intensity_ok = compute_intensity.passes(batch_size, seg_size)

        # Free training-phase objects before building inference models.
        del model_for_train, loss_module, x_train, y_train
        gc.collect()

        rss_after = psutil.Process().memory_info().rss
        rss_delta_gb = (rss_after - rss_before) / _GB
        if rss_delta_gb > 8.0:
            print(
                f"    [PROBE_MEMORY_WARNING] {model_type}: training probe "
                f"RSS delta = {rss_delta_gb:.2f} GB "
                f"(before={rss_before / _GB:.2f}, after={rss_after / _GB:.2f})"
            )
        else:
            print(f"    [Probe RSS] delta={rss_delta_gb:.2f} GB")

        # 4. Inference-phase resolution + breakdown probe ────────────────
        #    ``resolve_inference_batch`` probes each candidate B internally
        #    and enforces both caps simultaneously. We pass a fresh model
        #    instance because the resolver moves tensors around; re-probe
        #    at the chosen B for the breakdown.
        inference_probe: ProbeResult | None = None
        inference_peak: int = 0
        inference_breakdown: dict = {}
        inference_batch: int | None = None
        inference_err: str | None = None
        try:
            model_for_resolve = _build_model(model_type, model_cfg, loss_type)
            with _forward_pass_timeout(_FORWARD_PASS_TIMEOUT_S, "resolve_inference_batch"):
                inference_batch = resolve_inference_batch(
                    model_for_resolve,
                    segmentation_size=seg_size,
                    cap_bytes=cap_bytes,
                )
            del model_for_resolve
            gc.collect()

            model_for_bd = _build_model(model_type, model_cfg, loss_type)
            with _forward_pass_timeout(_FORWARD_PASS_TIMEOUT_S, "inference_probe"):
                inference_probe = probe_activation_footprint(
                    model=model_for_bd,
                    loss_module=None,
                    input_sample=torch.zeros(
                        (inference_batch, seg_size),
                        dtype=torch.long,
                    ),
                    target_sample=None,
                    mode="inference",
                )
            del model_for_bd
            gc.collect()

            inference_peak, inference_breakdown = _compose_inference_peak(inference_probe)
            inference_breakdown["inference_batch"] = inference_batch
        except ValueError as e:
            inference_err = str(e)

        inference_ok = inference_batch is not None
        feasible = training_vram_ok and training_intensity_ok and inference_ok

        # 5. Phase breakdown + dominant phase ─────────────────────────────
        phase_breakdown: dict[str, dict] = {
            "training": {
                "phase": "training",
                "total_bytes": training_peak,
                "breakdown": training_breakdown,
            },
            "scoring": {"phase": "scoring", "total_bytes": 0, "breakdown": {}},
        }
        if inference_probe is not None:
            phase_breakdown["inference"] = {
                "phase": "inference",
                "total_bytes": inference_peak,
                "breakdown": inference_breakdown,
            }
        dominant_phase = max(phase_breakdown, key=lambda k: phase_breakdown[k]["total_bytes"])
        total_est = phase_breakdown[dominant_phase]["total_bytes"]

        # 6a. Feasible path ───────────────────────────────────────────────
        if feasible:
            verdict = (
                f"✅ FITS — estimated {total_est / _GB:.2f} GB "
                f"≤ cap {cap_bytes / _GB:.2f} GB "
                f"(usable {hardware_context.usable_cap_gb:.1f} GB of "
                f"{hardware_context.total_memory_gb:.1f} GB on "
                f"{hardware_context.device_name}). "
                f"Dominant phase: {dominant_phase}. Inference B: {inference_batch}."
            )
            print(f"    Estimated  : {total_est / _GB:.2f} GB / cap {cap_bytes / _GB:.2f} GB")
            print(f"    Inference B: {inference_batch}")
            print("    Feasible   : YES")
            return {
                "status": "success",
                "feasible": True,
                "verdict": verdict,
                "suggestion": "",
                "num_params": num_params,
                "dominant_phase": dominant_phase,
                "phase_breakdown": phase_breakdown,
                "estimated_gb": round(total_est / _GB, 3),
                "limit_gb": round(cap_bytes / _GB, 3),
                "vram_budget_gb": vram_budget_gb,
                "inference_batch": inference_batch,
                "memory_killer": None,
            }

        # 6b. Infeasible path: Memory Killer report ──────────────────────
        report = _render_killer(
            training_probe=training_probe,
            training_peak=training_peak,
            training_vram_ok=training_vram_ok,
            training_intensity_ok=training_intensity_ok,
            inference_ok=inference_ok,
            inference_err=inference_err,
            model_type=model_type,
            model_cfg=model_cfg,
            loss_type=loss_type,
            batch_size=batch_size,
            seg_size=seg_size,
            cap_bytes=cap_bytes,
            total_memory_bytes=total_memory_bytes,
        )
        print(f"    Verdict    : {report.verdict}")
        print("    Feasible   : NO")

        return {
            "status": report.status,  # "schema_violation"
            "feasible": False,
            "verdict": report.verdict,
            "suggestion": report.suggestion,
            "num_params": num_params,
            "dominant_phase": dominant_phase,
            "phase_breakdown": phase_breakdown,
            "estimated_gb": round(total_est / _GB, 3),
            "limit_gb": round(cap_bytes / _GB, 3),
            "vram_budget_gb": vram_budget_gb,
            "inference_batch": inference_batch,  # None on inference failure
            "memory_killer": report.memory_killer.model_dump(),
        }

    except Exception as e:
        import traceback

        msg = f"VRAMEval runtime error: {e}\n{traceback.format_exc()}"
        print(f"!!! [VRAMEval] {msg}")
        return {"status": "error", "message": msg}
