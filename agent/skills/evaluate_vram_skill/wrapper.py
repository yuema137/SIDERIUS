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
import math
import signal
from contextlib import contextmanager
from typing import TYPE_CHECKING

import psutil
import torch
from pydantic import ValidationError

from agent.skills.evaluate_vram_skill import compute_intensity, killer_report
from agent.skills.evaluate_vram_skill.batch_resolver import (
    BatchSearchTimeout,
    resolve_inference_batch,
)
from agent.skills.evaluate_vram_skill.overhead import (
    cuda_context_bytes,
    cudnn_backward_workspace_bytes,
    training_overhead_bytes,
)
from agent.skills.evaluate_vram_skill.probe_budgets import (
    ProbeBudgets,
    ProbeTimeoutRecord,
    classify_host_memory_exception,
)
from agent.skills.evaluate_vram_skill.structural_probe import (
    ProbeResult,
    probe_activation_footprint,
)
from agent.skills.model_io_probe_skill import (
    build_model_input,
    declared_output_tensor,
    output_without_class_axis,
    realize_shape,
)
from agent.skills.training_skill.estimator import resolve_model_field
from core.hardware_context import HardwareContext, discover
from ml_models.loss_models_sandbox import get_criterion, get_target_torch_dtype
from ml_models.models_format_sandbox import (
    LossConfig,
    get_config_class,
    output_semantic_from_legacy,
)
from ml_models.models_sandbox import MODEL_REGISTRY

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.schemas.model_io_contract import ModelIOContract

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
#: Superseded by `_BUDGETS`. Retained only so external references keep
#: importing successfully; nothing in this module reads it any more.
_FORWARD_PASS_TIMEOUT_S: int = 60

#: Per-operation budgets. One number can no longer bound four different
#: operations — see probe_budgets for why that mattered.
_BUDGETS = ProbeBudgets()


class ForwardPassTimeoutError(Exception):
    """Raised when a probe's forward pass exceeds ``_FORWARD_PASS_TIMEOUT_S``."""


@contextmanager
def _forward_pass_timeout(seconds: float, label: str):
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
        # Deliberately makes NO claim about the candidate. The previous
        # text asserted the most common cause was a loop inside
        # `nn.Module.forward`, which sent agents chasing their own model
        # when the loop responsible was SIDERIUS's own batch search.
        raise ForwardPassTimeoutError(
            f"Bounded pre-flight step '{label}' exceeded its {seconds}s budget. "
            f"This is an INCONCLUSIVE inspection result: the measurement did "
            f"not complete, so it says nothing about whether this model fits "
            f"or how fast it is. It is not a reason to reduce model capacity "
            f"or batch size."
        )

    old_handler = signal.signal(signal.SIGALRM, _handler)
    # `signal.alarm` takes whole seconds; budgets are floats. Round UP so a
    # fractional budget is never silently truncated toward zero.
    signal.alarm(max(1, math.ceil(seconds)))
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


def _contract_target_shape(
    model_io_contract: ModelIOContract | None,
    declared_output_type: str | None,
    *,
    batch_size: int,
    seg_size: int,
) -> tuple[int, ...] | None:
    """The probe target's shape as the DECLARED Model-I/O contract states it.

    Step 05b. ``None`` means *"this call has no contract-derived shape"* and
    the caller keeps its legacy construction; it never means *"the contract
    failed"*, which raises.

    The authority split is Step 04a's, inherited unchanged (Step-05b §0.5):

    ```text
    candidate declaration  (get_output_type)  -> selects the output FORM
    ModelIOContract                           -> supplies the FACTS inside it
    model_io_probe_skill                      -> realizes the concrete tensor
    ```

    so this function resolves no shape of its own and carries no second
    form table. It asks the EXISTING projection
    (``output_semantic_from_legacy``) whether the declared word denotes a
    tensor semantic at all, and delegates everything else.

    **Why ``hybrid`` keeps its legacy target, and why that is not a
    fallback.** ``hybrid`` is a legacy builtin adapter value, not a tensor
    semantic — Step-03 §8c states that outright and forbids inventing one
    for it. Source agrees: ``fcnet`` returns ``[B, T]`` under ``smooth_l1``
    and ``[B, C, T]`` otherwise (``models_sandbox.py:362-365``), so its
    emitted shape is chosen by the LOSS, a fact no Model-I/O contract owns.
    There is therefore nothing for the contract to supply, and the shipped
    target is preserved exactly rather than guessed at.

    Args:
        model_io_contract: the run's normalized declaration, or ``None`` for
            the legacy no-contract path.
        declared_output_type: what ``get_output_type`` answered for this
            candidate, or ``None`` when no ``model_type`` was supplied.
        batch_size: the candidate's real batch size — a capacity probe
            measures the tensor that will actually run.
        seg_size: the candidate's real segmentation size.

    Returns:
        The realized shape, or ``None`` when no contract-derived shape
        applies (no contract supplied, or a declaration carrying no
        canonical tensor semantic).

    Raises:
        ValueError: a contract was supplied with no candidate declaration to
            select a form from.
        ProbeConstructionError: the declared form needs a contract fact the
            contract does not carry, or the realization is not
            representable. Propagated rather than swallowed — it is already
            this module's ``ValueError`` idiom, and falling back to the
            literal would report a capacity number for a different tensor.
    """
    if model_io_contract is None:
        return None
    if declared_output_type is None:
        raise ValueError(
            "Cannot build a probe target: a Model-I/O contract was supplied "
            "but no model_type, so there is no candidate declaration to select "
            "an output form from. The declaration selects the form and the "
            "contract supplies the facts inside it; one without the other is "
            "not a probe specification."
        )
    if output_semantic_from_legacy(declared_output_type) is None:
        # `hybrid`, or a value the shipped projection does not recognise:
        # no canonical tensor semantic, so no contract-owned fact to derive.
        return None
    return realize_shape(
        declared_output_tensor(model_io_contract, declared_output_type),
        batch=batch_size,
        symbolic=seg_size,
    )


def _probe_input_tensor(
    batch_size: int,
    seg_size: int,
    model_io_contract: ModelIOContract | None,
) -> torch.Tensor:
    """The probe's INPUT tensor — F-12d-24.

    Contract-shaped and contract-dtyped, at the candidate's REAL batch size
    and segmentation length, when a Model-I/O declaration is bound
    (``model_io_probe_skill.build_model_input`` — the same Step-04 recipe
    authority ``realize_shape``'s own docstring already promised this caller
    "supplies the candidate's real batch size" / "real segmentation size",
    a promise this module never kept until now). Otherwise the exact
    ``[B, T]`` int64 tensor every call built before Step 05b — legacy,
    byte-identical, untouched.
    """
    if model_io_contract is not None:
        return build_model_input(model_io_contract, batch=batch_size, symbolic=seg_size)
    return torch.zeros((batch_size, seg_size), dtype=torch.long)


def _class_index_target_tensor(
    batch_size: int,
    seg_size: int,
    model_io_contract: ModelIOContract | None,
) -> torch.Tensor:
    """The classification loss's class-INDEX target — F-12d-24.

    One integer per remaining (non-class) position of the contract's output
    — ``model_io_probe_skill.output_without_class_axis`` — at the
    candidate's real batch/segmentation size, when a Model-I/O declaration
    is bound. This is why TIDMAD's own shape is unchanged: its output
    carries both a class axis (256, dropped) and a temporal axis (T, kept),
    so the realized shape is exactly the legacy ``[B, T]`` below. Otherwise
    that exact ``[B, T]`` long tensor every classifier-loss call built
    before Step 05b — legacy, byte-identical, untouched.
    """
    if model_io_contract is not None:
        shape = realize_shape(
            output_without_class_axis(model_io_contract), batch=batch_size, symbolic=seg_size
        )
        return torch.zeros(shape, dtype=torch.long)
    return torch.zeros((batch_size, seg_size), dtype=torch.long)


def _refuse_unrunnable_loss_geometry(
    model_type: str,
    loss_type: str,
    model_io_contract: ModelIOContract | None,
) -> None:
    """Ask the shared geometry authority before probing — **D2**.

    This module is the first place a real run instantiates the candidate's
    loss and CALLS it, so it is the first place an unrunnable geometry can
    fail. Before this, a task declaring ``[B, C]`` logits paired with
    ``focal`` died in ``probe_activation_footprint`` on the loss's own
    ``permute`` and surfaced as an opaque ``"VRAMEval runtime error"``; the
    refusal waiting in ``SandboxExecutor._validate_configs`` was never
    reached.

    It asks the GEOMETRY question only. Deciding SEMANTIC legality here would
    move where a classifier/``smooth_l1`` mismatch is reported — that pairing
    probes fine today (``_build_probe_tensors`` shapes the target from the
    declared output contract) and is refused, with its own advice, at config
    validation. The pre-flight is not the config-validation authority; it
    only has to not blow up on what it is about to execute.

    ``model_io_contract is None`` — the legacy prose-only task — declares no
    geometry, so nothing is refused and behaviour is exactly pre-D2.

    Raises:
        ValueError: the loss cannot run at the run's declared geometry.
    """
    from ml_models.models_format_sandbox import validate_loss_output_geometry

    validate_loss_output_geometry(
        loss_type,
        model_type=model_type,
        output_has_temporal_axis=(
            None if model_io_contract is None else model_io_contract.output_has_temporal_axis
        ),
    )


def _build_probe_tensors(
    batch_size: int,
    seg_size: int,
    loss_type: str,
    loss_name: str | None = None,
    model_type: str | None = None,
    model_io_contract: ModelIOContract | None = None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Zero-valued ``(input, target)`` pair matching the SIDERIUS forward
    contract. Both tensors live on CPU; the probe will ``.to(device)`` them
    if the caller asks for CUDA (we don't, here).

    Two INDEPENDENT questions decide the target, and conflating them was a
    real defect (V21 PR A, found by Gate 2R on real hardware):

    * **dtype** comes from the loss — ``PLUGIN_LOSS_TARGET_DTYPE`` via
      ``get_target_torch_dtype`` (I14).
    * **shape** comes from the model's declared OUTPUT CONTRACT, because the
      target has to be comparable with what the model actually emits.

    Previously the shape was derived from the dtype: any float target was
    built as ``[B, 256, T]``. That is right for ``fcnet`` (``hybrid``), which
    emits ``[B, 256, T]`` and broadcasts a float target against its logits —
    and wrong for a ``regressor``, which emits ``[B, T]``. A generated
    regressor + ``smooth_l1`` therefore died in the VRAM pre-flight with
    ``size of tensor a (4) must match tensor b (256) at dimension 1``, before
    any capacity question was reached.

        classifier -> [B, T]        (class indices, long)
        regressor  -> [B, T]        (continuous target, float)
        hybrid      -> [B, 256, T]  (float broadcast against logits)

    ``model_type=None`` keeps the historical dtype-derived shape so callers
    that predate the contract are unaffected.

    **Step 05b — ``model_io_contract``.** When the run binds a normalized
    Model-I/O declaration, the float target's shape is REALIZED from it
    through the one Step-04a authority, at this candidate's real
    ``batch_size`` and ``seg_size``, instead of from the ``[B, 256, T]``
    literal below. Two things are deliberately unchanged:

    * **dtype** still comes from the loss. The contract supplies shape only;
      moving dtype ownership would create a second dtype mapping beside
      ``get_target_torch_dtype``.
    * **the class-index branch**. A long target is class indices, ``[B, T]``,
      carrying no contract-owned extent — so it returns before any contract
      is consulted, exactly as it does today.

    ``model_io_contract=None`` is the legacy no-contract path and builds
    byte-identical tensors to every call before Step 05b.
    """
    inp = _probe_input_tensor(batch_size, seg_size, model_io_contract)
    # Dict-unpack to mirror the existing ``LossConfig(**loss_cfg)`` pattern
    # at the run_skill site (line ~469); avoids a Literal-narrowing pyright
    # error when ``loss_type`` arrives as a plain ``str``.
    target_dtype = get_target_torch_dtype(
        LossConfig(**{"loss_type": loss_type, "loss_name": loss_name})
    )
    if target_dtype == torch.long:
        return inp, _class_index_target_tensor(batch_size, seg_size, model_io_contract)

    # Float target: the shape follows the declared output contract.
    output_type = None
    if model_type is not None:
        from ml_models.plugin_loader import (
            UnknownOutputContractError,
            get_output_type,
        )

        try:
            output_type = get_output_type(model_type)
        except UnknownOutputContractError as e:
            # V21 PR C1 — typed MEASUREMENT refusal, in this module's idiom
            # (`ValueError`, as at :160 and :250).
            #
            # Falling through with `output_type = None` would be the worst
            # possible handling here: the else-branch below builds a
            # [B, 256, T] target, so an unregistered regressor would be
            # probed against the classifier shape and the VRAM forecast
            # would silently describe a different model. A3c fixed exactly
            # this class of shape error during PR A.
            raise ValueError(f"Cannot build a probe target: {e!s}") from e

    # Step 05b — the declared Model-I/O contract, when the run binds one.
    # A failure here PROPAGATES: a silently-wrong probe reports a capacity
    # number for a different model, which is the defect this seam exists to
    # remove, not one it may reintroduce.
    contract_shape = _contract_target_shape(
        model_io_contract, output_type, batch_size=batch_size, seg_size=seg_size
    )
    if contract_shape is not None:
        return inp, torch.zeros(contract_shape, dtype=target_dtype)

    if output_type == "regressor":
        tgt = torch.zeros((batch_size, seg_size), dtype=target_dtype)
    else:
        # The "hybrid" contract, plus the legacy model_type=None path.
        # Note this is a branch on the DECLARED CONTRACT, never on a model
        # name — the name only ever reaches get_output_type as a registry key.
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
    model_io_contract: ModelIOContract | None = None,
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
        input_sample=_probe_input_tensor(1, seg_size, model_io_contract),
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
    model_io_contract: ModelIOContract | None = None,
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
            model_io_contract=model_io_contract,
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
        model_io_contract — the RUN-BOUND normalized Model-I/O declaration
                           (Step 05b). Supplied explicitly by the caller;
                           this skill never resolves one of its own, because
                           a resource consumer that re-reads an ambient task
                           configuration can silently price a run against a
                           declaration the run is not using. ``None`` is the
                           legacy no-contract path and is byte-identical to
                           every call before Step 05b.
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
    model_io_contract: ModelIOContract | None = kwargs.get("model_io_contract")

    loss_type = loss_cfg.get("loss_type", "ce")
    # I14 — loss_name plumbs through to _build_probe_tensors so the helper
    # can route custom-loss target dtype via PLUGIN_LOSS_TARGET_DTYPE.
    loss_name = loss_cfg.get("loss_name")
    batch_size = int(train_cfg.get("batch_size", 1))
    # C12-P / B2 — price the candidate from the DECLARATION, not a literal.
    #
    # This read was `model_cfg.get("segmentation_size", 40000)`: a raw dict
    # lookup with TIDMAD's scale as the fallback, while `_build_model` above
    # constructs the very same candidate through its config CLASS, whose pack
    # defaults are 144 (Pets) and 128 (DAVIS). The two halves of one function
    # therefore disagreed, silently, and `seg_size` is the SOLE operand of the
    # compute-intensity gate below — so any planned `batch_size >= 21` refused
    # a foreign candidate and advised the LLM to "reduce segmentation_size", a
    # knob both contrast packs declare as inert engine residue.
    #
    # `resolve_model_field` is the existing single authority (supplied value >
    # config-class default > safety margin) and four sibling estimators already
    # use it; this was the last holdout. The margin keeps the previous last
    # resort, so behaviour is unchanged whenever the key is present — which is
    # every production plan measured across 1,844 persisted planner configs.
    seg_size = resolve_model_field(model_type, model_cfg, "segmentation_size", safety_margin=40000)
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
        #
        # D2 — the geometry authority's second consumer, and the one a real
        # run reaches FIRST: admission runs before `execute_training`, and
        # the probe below calls `loss_module(logits, target)`. Same shared
        # function the config-validation branches call, so no verdict can
        # differ between them; re-inlining the rule here is the defect V21
        # PR A1 deleted.
        _refuse_unrunnable_loss_geometry(model_type, loss_type, model_io_contract)
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
        x_train, y_train = _build_probe_tensors(
            batch_size,
            seg_size,
            loss_type,
            loss_name,
            model_type=model_type,
            model_io_contract=model_io_contract,
        )
        with _forward_pass_timeout(_BUDGETS.single_probe_seconds, "training_probe"):
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
            # No enclosing alarm here: `resolve_inference_batch` now times
            # each candidate AND the whole search separately, so wrapping it
            # in one more budget would recreate the very conflation this
            # replaced.
            inference_batch = resolve_inference_batch(
                model_for_resolve,
                segmentation_size=seg_size,
                cap_bytes=cap_bytes,
                budgets=_BUDGETS,
                model_identity=model_type,
                model_io_contract=model_io_contract,
            )
            del model_for_resolve
            gc.collect()

            model_for_bd = _build_model(model_type, model_cfg, loss_type)
            with _forward_pass_timeout(_BUDGETS.single_probe_seconds, "inference_probe"):
                inference_probe = probe_activation_footprint(
                    model=model_for_bd,
                    loss_module=None,
                    input_sample=_probe_input_tensor(inference_batch, seg_size, model_io_contract),
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
            model_io_contract=model_io_contract,
        )
        print(f"    Verdict    : {report.verdict}")
        print("    Feasible   : NO")

        return {
            # Transport status is "success": the skill executed fine and the
            # VERDICT is infeasible (feasible=False). The tuner's branch
            # order (error → schema_violation → not-feasible) relies on this
            # so over-budget verdicts reach the skipped_oom_risk path with
            # PhysicalRejection capture — "schema_violation" is reserved for
            # real ValidationErrors (_schema_violation_response above).
            "status": "success",
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

    except BatchSearchTimeout as e:
        # A bounded search step ran out of time. The candidate measured
        # nothing, so this must not reach the tuner as a capacity verdict.
        # `timeout` rather than `inconclusive`: a deadline ACTUALLY
        # elapsed here, and the caller must be able to tell that from an
        # inspection that simply failed. Conflating the two produced a
        # 65.6 s "timeout" against a 600 s deadline on 2026-07-31.
        print(f"!!! [VRAMEval] TIMEOUT: {e.record.agent_facing_summary()}")
        return {
            "status": "timeout",
            "message": e.record.agent_facing_summary(),
            "timeout_record": e.record.model_dump(mode="json"),
        }
    except ForwardPassTimeoutError as e:
        record = ProbeTimeoutRecord(
            operation="model_inspection",
            budget_seconds=_BUDGETS.single_probe_seconds,
            elapsed_seconds=_BUDGETS.single_probe_seconds,
            model_identity=model_type,
            disposition="inconclusive",
        )
        print(f"!!! [VRAMEval] TIMEOUT: {e}")
        return {
            "status": "timeout",
            "message": str(e),
            "timeout_record": record.model_dump(mode="json"),
        }
    except RuntimeError as e:
        # An allocation failure is a CANDIDATE-level fact and must be
        # reported as one. On 2026-07-31 a baseline-scale candidate's
        # torchinfo trace failed because the allocator refused it, and
        # this handler filed it as "inconclusive" — which downstream
        # became a TIMEOUT, after 3.771 s against a 600 s deadline.
        memory_kind = classify_host_memory_exception(e)
        if memory_kind is not None:
            print(f"!!! [VRAMEval] {memory_kind.upper()} ALLOCATION FAILURE: {str(e)[:160]}")
            return {
                "status": "cuda_oom" if memory_kind == "cuda" else "host_memory",
                "message": str(e)[:600],
            }
        # `torchinfo` tracing failure that is NOT an allocation problem. It
        # is a DIAGNOSTIC convenience, not a capacity oracle: the
        # authoritative parameter count already comes from the
        # instantiated model, and real memory comes from the bounded CUDA
        # probe. A tracing failure leaves the question open rather than
        # answering it against the candidate.
        if "torchinfo" not in str(e):
            raise
        record = ProbeTimeoutRecord(
            operation="model_inspection",
            budget_seconds=_BUDGETS.single_inspection_seconds,
            elapsed_seconds=0.0,
            model_identity=model_type,
            phase="torchinfo_trace",
            disposition="inconclusive",
        )
        # NO deadline elapsed here — tracing simply failed. Reported as
        # inconclusive, never as a timeout.
        print(f"!!! [VRAMEval] INCONCLUSIVE (torchinfo trace failed): {str(e)[:160]}")
        return {
            "status": "inconclusive",
            "message": (
                "VRAM pre-flight did not complete: structural tracing (torchinfo) "
                "failed. This is an INCONCLUSIVE inspection result, not a "
                "measurement of this model, and not a reason to reduce model "
                "capacity or batch size."
            ),
            "timeout_record": record.model_dump(mode="json"),
        }
    except Exception as e:
        import traceback

        msg = f"VRAMEval runtime error: {e}\n{traceback.format_exc()}"
        print(f"!!! [VRAMEval] {msg}")
        return {"status": "error", "message": msg}
