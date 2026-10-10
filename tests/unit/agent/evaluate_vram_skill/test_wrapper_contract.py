"""Return-contract tests for ``agent/skills/evaluate_vram_skill/wrapper.py``.

Phase 6.6 §3.7 and #615. The wrapper composes structural probes, overhead,
batch decisions and compute intensity. These tests pin:

- exact top-level keys of the return dict — downstream consumers in
  ``ml_hyperparameter_tune_agent`` read by name;
- new keys present: ``inference_batch`` (int), ``memory_killer`` (dict | None);
- removed key absent: ``inference_batch_uncalibrated``;
- Phase K keys preserved verbatim: ``status``, ``feasible``, ``verdict``,
  ``suggestion``, ``num_params``, ``dominant_phase``, ``phase_breakdown``,
  ``estimated_gb``, ``limit_gb``, ``vram_budget_gb``;
- ``hardware_context=None`` kwarg falls back to ``discover()`` (kept
  green until A.11 wires the tuner pass-through);
- CPU-only short-circuit honoured;
- over-budget paths retain actual decision bytes and caps separately from
  the legacy diagnostic proxies, without re-probing or inventing layer attribution;
- schema-violation path (``pydantic.ValidationError`` from plugin config)
  preserved from Phase D.4.

All tests are hermetic — no real model instantiation, no real probe run,
no CUDA, no filesystem. Primitives are patched at the wrapper module
level because that is the import surface the wrapper uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from unittest.mock import patch

import pytest
import torch
from pydantic import BaseModel, ValidationError

from agent.schemas.preflight import StaticPreflightEvidence
from agent.skills.evaluate_vram_skill import native_estimation, wrapper
from agent.skills.evaluate_vram_skill.batch_resolver import BatchSearchRefused
from agent.skills.evaluate_vram_skill.evidence import (
    phase_decision,
)
from agent.skills.evaluate_vram_skill.structural_probe import (
    AutogradTapeReport,
    ForwardLayerReport,
    LayerReport,
    ProbeResult,
)
from core.hardware_context import HardwareContext
from tests.helpers.step04a_fixtures import regressor_model_io

# ── Hardware fixtures ───────────────────────────────────────────────────────


def _gpu_ctx(total_gb: float = 32.0) -> HardwareContext:
    """Build a GPU HardwareContext by hand — no torch.cuda probe."""
    return HardwareContext(
        device_name="MockGPU 9000",
        total_memory_bytes=int(total_gb * 1024**3),
        compute_capability=(9, 0),
        multiprocessor_count=128,
        cuda_runtime_version="12.1",
        torch_version="2.0.0",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime.now(UTC),
    )


def _cpu_ctx() -> HardwareContext:
    return HardwareContext(
        device_name="cpu",
        total_memory_bytes=0,
        compute_capability=(0, 0),
        multiprocessor_count=0,
        cuda_runtime_version=None,
        torch_version="2.0.0",
        hostname="test-host",
        device_available=False,
        discovered_at=datetime.now(UTC),
    )


# ── Probe-result fixtures ───────────────────────────────────────────────────


def _leaf(var_name: str, cls: str, out_bytes: int) -> LayerReport:
    return LayerReport(
        depth=1,
        var_name=var_name,
        class_name=cls,
        input_shape=[],
        output_shape=[1, 1],
        num_params=0,
        param_bytes=0,
        output_bytes=out_bytes,
        is_leaf=True,
    )


def _probe(
    *,
    layers: list[LayerReport] | None = None,
    saved_bytes: int = 0,
    input_bytes: int = 0,
    output_bytes: int = 0,
    total_param_bytes: int = 0,
    mode: str = "training",
) -> ProbeResult:
    layers = layers if layers is not None else [_leaf("x", "Y", 1_000_000)]
    sum_out = sum(layer.output_bytes for layer in layers if layer.is_leaf)
    max_out = max((layer.output_bytes for layer in layers if layer.is_leaf), default=0)
    return ProbeResult(
        mode=mode,
        model_forward=ForwardLayerReport(
            module_name="Fake",
            layers=layers,
            total_param_bytes=total_param_bytes,
            forward_output_bytes_sum=sum_out,
            forward_output_bytes_max=max_out,
        ),
        loss_forward=None,
        autograd_tape=AutogradTapeReport(
            unique_storage_count=1,
            total_saved_bytes=saved_bytes,
        )
        if mode == "training"
        else None,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
    )


# ── Common patch bundle ─────────────────────────────────────────────────────


class _Patches:
    """Context-manager bundle for the wrapper's five external collaborators,
    pre-wired with neutral (fit-in-budget) return values. Individual tests
    override attributes after ``__enter__`` to steer into failure paths."""

    def __init__(self):
        self.model_mock = torch.nn.Module()
        self.model_mock.register_parameter("weight", torch.nn.Parameter(torch.zeros(25)))
        self.loss_mock = torch.nn.Identity()
        self.training_probe = _probe(
            mode="training",
            saved_bytes=10,
            input_bytes=5,
            output_bytes=5,
            total_param_bytes=100,
        )
        self.inference_probe = _probe(
            mode="inference",
            input_bytes=5,
            output_bytes=5,
            total_param_bytes=100,
        )
        self.resolved_batch = 4

    def __enter__(self):
        self._stack = [
            patch.object(wrapper, "_build_model", return_value=self.model_mock),
            patch.object(wrapper, "get_criterion", return_value=self.loss_mock),
            patch.object(
                wrapper,
                "probe_activation_footprint",
                side_effect=self._probe_side_effect,
            ),
            patch.object(
                wrapper,
                "resolve_inference_decision",
                side_effect=self._resolve_side_effect,
            ),
            patch.object(native_estimation, "training_overhead_bytes", return_value=20),
            patch.object(native_estimation, "cuda_context_bytes", return_value=30),
            patch.object(native_estimation, "cudnn_backward_workspace_bytes", return_value=40),
            patch.object(wrapper.compute_intensity, "passes", return_value=True),
        ]
        self._mocks = [p.start() for p in self._stack]
        self.build_model = self._mocks[0]
        self.get_criterion = self._mocks[1]
        self.probe = self._mocks[2]
        self.resolve = self._mocks[3]
        self.training_over = self._mocks[4]
        self.ctx_over = self._mocks[5]
        self.cudnn_over = self._mocks[6]
        self.intensity_passes = self._mocks[7]
        return self

    def __exit__(self, *exc):
        for p in self._stack:
            p.stop()

    def _probe_side_effect(self, *, model, loss_module, input_sample, target_sample, mode):
        return self.training_probe if mode == "training" else self.inference_probe

    def _resolve_side_effect(self, model, *, segmentation_size, cap_bytes, **kwargs):
        return phase_decision(
            phase="inference",
            batch_size=self.resolved_batch,
            cap_bytes=cap_bytes,
            estimate_bytes=1_000_130,
            segmentation_size=segmentation_size,
        )


# ── Common kwargs ───────────────────────────────────────────────────────────


def _run_kwargs(**overrides):
    base = dict(
        model_type="fcnet",
        model_config={"segmentation_size": 40_000},
        train_config={"batch_size": 1, "optimizer": "adam"},
        loss_config={"loss_type": "ce"},
    )
    base.update(overrides)
    return base


# ── 1. Return-dict shape (feasible path) ────────────────────────────────────

_REQUIRED_KEYS = frozenset(
    {
        # Phase K preserved:
        "status",
        "feasible",
        "verdict",
        "suggestion",
        "num_params",
        "dominant_phase",
        "phase_breakdown",
        "estimated_gb",
        "limit_gb",
        "vram_budget_gb",
        # Phase 6.6 new:
        "inference_batch",
        "memory_killer",
        "static_preflight_evidence",
    }
)


# Eight cases used to run this exact call -- `_Patches()` plus
# `run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())`,
# `_gpu_ctx` defaulting to the same 32.0 GB -- and read one key each. They are
# grouped below by CONTRACT rather than by field: what the dict contains, and
# what the values mean. Every equivalence class the eight covered is kept.


def test_feasible_path_returns_the_declared_shape():
    """What the dict CONTAINS on the success path."""
    with _Patches():
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())

    assert _REQUIRED_KEYS.issubset(out.keys()), f"Missing keys: {_REQUIRED_KEYS - set(out.keys())}"
    # Phase K's `inference_batch_uncalibrated` is obsolete under the
    # probe-driven resolver; its reappearance would mean a merge leak.
    assert "inference_batch_uncalibrated" not in out
    assert out["status"] == "success"


def test_task_owned_probe_pair_reaches_the_training_loss_without_zero_substitution():
    """Regression: semantic targets must survive the resource boundary.

    Replacing either tensor with ``_build_probe_tensors`` recreates the
    all-zero target that custom masked losses correctly refuse.
    """
    task_input = torch.tensor([[[1.0, 7.0]]])
    task_target = torch.tensor([[[1.0, 1.0, 0.0]]])
    with (
        _Patches() as patches,
        patch.object(
            wrapper,
            "_build_probe_tensors",
            side_effect=AssertionError("task-owned samples were discarded"),
        ),
    ):
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(),
            probe_input_sample=task_input,
            probe_target_sample=task_target,
            **_run_kwargs(),
        )

    training_call = patches.probe.call_args_list[0]
    assert torch.equal(training_call.kwargs["input_sample"], task_input.to(torch.int32))
    assert torch.equal(training_call.kwargs["target_sample"], task_target.to(torch.long))
    assert out["status"] == "success"
    assert out["feasible"] is True
    # The killer slot is populated only when the wrapper REFUSED the config.
    assert out["memory_killer"] is None
    # `scoring` is a passthrough slot left for Phase 6.7, so this is `>=`.
    assert set(out["phase_breakdown"].keys()) >= {"training", "inference"}


def test_composed_probe_converts_storage_dtype_for_training_and_inference():
    """A task-owned int16 sample must reach every model forward as int64."""
    task_input = torch.zeros((1, 128), dtype=torch.int16)
    task_target = torch.zeros((1, 128), dtype=torch.float32)
    with _Patches() as patches:
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(),
            probe_input_sample=task_input,
            probe_target_sample=task_target,
            model_io_contract=regressor_model_io(),
            **_run_kwargs(
                model_type="strict_int64_plugin",
                model_config={"segmentation_size": 128},
                loss_config={"loss_type": "smooth_l1"},
            ),
        )

    assert out["status"] == "success"
    assert task_input.dtype == torch.int16
    assert patches.probe.call_args_list[0].kwargs["input_sample"].dtype == torch.int64
    assert patches.resolve.call_args.kwargs["supplied_probe"].dtype == torch.int64
    assert patches.probe.call_args_list[1].kwargs["input_sample"].dtype == torch.int64


def test_fixed_task_probe_does_not_acquire_an_invented_temporal_dimension(monkeypatch):
    """Absent geometry skips only the temporal heuristic, not measurement.

    A regression to the historical 40,000 fallback makes either the resolver
    assertion or the forbidden intensity call fail while the same task-owned
    tensors still traverse both structural probe phases.
    """
    from pydantic import BaseModel

    import ml_models.models_format_sandbox as model_formats

    class FixedProbeConfig(BaseModel):
        hidden_dim: int = 4

    monkeypatch.setattr(model_formats, "get_config_class", lambda _model_type: FixedProbeConfig)
    task_input = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
    task_target = torch.tensor([1])
    with _Patches() as patches:
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(),
            probe_input_sample=task_input,
            probe_target_sample=task_target,
            **_run_kwargs(model_type="fixed_probe_model", model_config={}),
        )

    assert patches.probe.call_count == 2
    assert patches.resolve.call_args.kwargs["segmentation_size"] is None
    assert torch.equal(patches.resolve.call_args.kwargs["supplied_probe"], task_input)
    patches.intensity_passes.assert_not_called()
    assert out["status"] == "success"
    assert out["feasible"] is True


def test_absent_dimension_without_task_probe_refuses_before_hardware(monkeypatch):
    """A legacy tensor cannot be constructed by quietly restoring 40,000."""
    from agent.skills.training_skill.estimator import SegmentationDimensionUnavailableError

    monkeypatch.setattr(
        wrapper,
        "discover",
        lambda: pytest.fail("hardware discovery ran before dimension refusal"),
    )
    with pytest.raises(SegmentationDimensionUnavailableError, match="no task-owned probe"):
        wrapper.run_skill(
            sandbox=None,
            **_run_kwargs(model_type="undeclared_fixed_model", model_config={}),
        )


def test_feasible_path_reports_the_measured_values():
    """What the values MEAN. Separated from the shape contract because a
    wrapper that returned the right keys filled with constants would satisfy
    the test above."""
    with _Patches() as p:
        p.resolved_batch = 16
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())

    # Forwarded from the resolver, not hardcoded: `_Patches` was told 16.
    assert out["inference_batch"] == 16
    assert isinstance(out["inference_batch"], int)
    # GB units, and the cap is the physical ceiling: 32 GB x 0.80 = 25.6 GB.
    assert isinstance(out["estimated_gb"], float)
    assert isinstance(out["limit_gb"], float)
    assert out["limit_gb"] == pytest.approx(25.6, abs=0.01)
    # The agent-facing verdict names the cap it was measured against.
    assert "25.6 GB" in out["verdict"] or "25.60 GB" in out["verdict"]
    assert "Dominant phase" in out["verdict"]


# ── 2. hardware_context=None fallback ───────────────────────────────────────


def test_none_hardware_context_falls_back_to_discover():
    """Until A.11 wires the tuner pass-through, ``hardware_context=None``
    must fall back to ``core.hardware_context.discover()`` — the same
    primitive ``get_or_create`` uses. Keeps intermediate-stage tests green."""
    with _Patches(), patch.object(wrapper, "discover", return_value=_gpu_ctx()) as mock_discover:
        wrapper.run_skill(sandbox=None, hardware_context=None, **_run_kwargs())
    mock_discover.assert_called_once()


def test_explicit_hardware_context_skips_discover():
    """When the caller supplies a context, the wrapper must NOT probe."""
    with _Patches(), patch.object(wrapper, "discover") as mock_discover:
        wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    mock_discover.assert_not_called()


# ── 3. CPU-only short-circuit ───────────────────────────────────────────────


def test_cpu_only_host_short_circuits_with_success():
    """CPU-only hosts have ``device_available=False``. The wrapper must not
    attempt VRAM accounting — return ``feasible=True`` with a ``CPU mode``
    verdict so the tuner can still run on laptops / CI."""
    with _Patches() as p:
        out = wrapper.run_skill(sandbox=None, hardware_context=_cpu_ctx(), **_run_kwargs())
        # The training-phase probe must NOT have been called on CPU-only:
        p.probe.assert_not_called()
    assert out["status"] == "success"
    assert out["feasible"] is True
    assert "CPU mode" in out["verdict"]
    assert out["memory_killer"] is None
    assert out["inference_batch"] == 1


# ── 4. Training-VRAM over-budget ────────────────────────────────────────────


def test_training_vram_over_budget_produces_vram_killer():
    """When training estimate exceeds the cap but intensity passes,
    ``memory_killer.binding_cap
    == 'vram'``, ``feasible=False``, ``status='success'`` (transport status
    is success — the verdict is infeasible; ``schema_violation`` is reserved
    for real ValidationErrors so the tuner's Phase-D.4 branch never swallows
    over-budget verdicts)."""
    with _Patches() as p:
        # Huge autograd tape → training peak blows the cap regardless of
        # the 32 GB context.
        p.training_probe = _probe(
            mode="training",
            layers=[_leaf("big_layer", "Conv1d", 9_000_000_000)],
            saved_bytes=50 * 1024**3,
            input_bytes=10,
            output_bytes=10,
            total_param_bytes=100,
        )
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(32.0), **_run_kwargs())
    assert out["feasible"] is False
    assert out["status"] == "success"
    assert out["memory_killer"] is not None
    assert isinstance(out["memory_killer"], dict)
    assert out["memory_killer"]["binding_cap"] == "vram"
    assert "dominant_layer" not in out["memory_killer"]
    evidence = StaticPreflightEvidence.model_validate(out["static_preflight_evidence"])
    assert evidence.refused_phase.phase == "training"


# ── 5. Training-intensity over-budget ──────────────────────────────────────


@pytest.mark.usefixtures("historical_workload_rule")
def test_training_intensity_over_budget_produces_intensity_killer():
    """When the VRAM estimate fits but B*T > 800k, retain the intensity dimensions."""
    with _Patches() as p:
        p.intensity_passes.return_value = False
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(),
            **_run_kwargs(
                model_config={"segmentation_size": 40_000},
                train_config={"batch_size": 25, "optimizer": "adam"},
            ),
        )
    assert out["feasible"] is False
    assert out["memory_killer"]["binding_cap"] == "compute_intensity"
    assert out["memory_killer"]["batch_size"] == 25
    assert out["memory_killer"]["segmentation_size"] == 40_000


# ── 6. Combined training failure (both caps bind) ──────────────────────────


@pytest.mark.usefixtures("historical_workload_rule")
def test_both_training_caps_binding_produces_combined_killer():
    with _Patches() as p:
        p.intensity_passes.return_value = False
        p.training_probe = _probe(
            mode="training",
            layers=[_leaf("huge", "Any", 9_000_000_000)],
            saved_bytes=50 * 1024**3,
            total_param_bytes=100,
        )
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(),
            **_run_kwargs(train_config={"batch_size": 25, "optimizer": "adam"}),
        )
    assert out["feasible"] is False
    assert out["memory_killer"]["binding_cap"] == "vram+compute_intensity"
    assert "dominant_layer" not in out["memory_killer"]
    assert out["memory_killer"]["batch_size"] == 25


# ── 7. Inference-resolver failure ──────────────────────────────────────────


def test_inference_resolver_vram_failure_produces_vram_killer():
    """The actual custom batch decision survives; no B=1 diagnostic re-probe."""
    with _Patches() as p:
        decision = phase_decision(
            phase="inference",
            batch_size=3,
            cap_bytes=5 * 1024**3,
            estimate_bytes=9 * 1024**3,
            segmentation_size=40_000,
        )
        p.resolve.side_effect = BatchSearchRefused(decision, 40_000)
        out = wrapper.run_skill(
            sandbox=None, hardware_context=_gpu_ctx(), vram_budget_gb=5.0, **_run_kwargs()
        )
        assert p.probe.call_count == 1
        assert p.build_model.call_count == 2
    assert out["feasible"] is False
    assert out["inference_batch"] is None
    assert out["memory_killer"]["binding_cap"] == "vram"
    assert "dominant_layer" not in out["memory_killer"]
    assert out["estimated_gb"] == 9.0
    assert out["dominant_phase"] == "inference"
    assert "B=3" in out["verdict"]
    assert "9,663,676,416 bytes" in out["verdict"]
    assert out["static_preflight_evidence"]["phases"][1] == decision.model_dump(mode="json")


@pytest.mark.usefixtures("historical_workload_rule")
def test_inference_resolver_intensity_failure_produces_intensity_killer():
    """When the resolver fails on intensity at B=1, the wrapper must NOT
    re-probe (pure ``segmentation_size`` problem, no layer attribution)."""
    with _Patches() as p:
        p.resolve.side_effect = BatchSearchRefused(
            phase_decision(
                phase="inference",
                batch_size=1,
                cap_bytes=int(25.6 * 1024**3),
                estimate_bytes=None,
                segmentation_size=900_000,
            ),
            900_000,
        )
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(),
            **_run_kwargs(model_config={"segmentation_size": 900_000}),
        )
    assert out["feasible"] is False
    assert out["memory_killer"]["binding_cap"] == "compute_intensity"
    assert out["memory_killer"]["segmentation_size"] == 900_000
    assert out["estimated_gb"] is None


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (ValueError("unsupported input geometry"), "error"),
        (MemoryError("host allocator refused"), "host_memory"),
        (RuntimeError("CUDA out of memory"), "cuda_oom"),
    ],
)
def test_inference_failures_keep_their_domain_without_diagnostic_reprobe(failure, status):
    """#615: unrelated errors and allocator refusals cannot become static VRAM claims."""
    with _Patches() as patches:
        patches.resolve.side_effect = failure
        out = wrapper.run_skill(None, hardware_context=_gpu_ctx(), **_run_kwargs())
        assert patches.probe.call_count == 1
        assert patches.build_model.call_count == 2
    assert out["status"] == status
    assert "memory_killer" not in out
    assert "static_preflight_evidence" not in out


def actual_inference_refusal(monkeypatch):
    """Run the real resolver and wrapper with bounded synthetic probe observations."""
    from functools import partial

    from agent.skills.evaluate_vram_skill import batch_resolver

    observed = []
    inference_probe = _probe(
        mode="inference",
        layers=[_leaf(str(index), "Linear", 512 * 1024**2) for index in range(16)],
        total_param_bytes=1024,
    )

    def probe(**kwargs):
        observed.append(kwargs["input_sample"].shape[0])
        return inference_probe

    monkeypatch.setattr(batch_resolver, "probe_activation_footprint", probe)
    with _Patches() as patches:
        patches.resolve.side_effect = partial(
            batch_resolver.resolve_inference_decision, candidate_batches=(7, 3)
        )
        out = wrapper.run_skill(
            None, hardware_context=_gpu_ctx(), vram_budget_gb=5.0, **_run_kwargs()
        )
        assert patches.probe.call_count == 1
    assert observed == [7, 3]
    return out


def test_actual_inference_decision_reaches_wrapper_without_max_proxy_or_reprobe(monkeypatch):
    """#615: the real resolver's large sum must survive a much smaller max diagnostic."""
    out = actual_inference_refusal(monkeypatch)
    assert out["feasible"] is False
    assert out["dominant_phase"] == "inference"
    assert out["estimated_gb"] == 8.0
    assert (
        out["static_preflight_evidence"]["phases"][1]["vram_estimate_bytes"]
        == 8 * 1024**3 + 100 + 30
    )
    assert "8,589,934,722 bytes" in out["verdict"]
    assert "5,368,709,120 bytes" in out["verdict"]


def test_success_retains_legacy_diagnostics_and_separate_admission_evidence():
    """#615: adding exact decision evidence must not rewrite successful prompt inputs."""
    with _Patches() as patches:
        patches.inference_probe = _probe(
            mode="inference",
            layers=[_leaf("a", "Linear", 1_000_000)] * 4,
            input_bytes=10,
            output_bytes=5,
            total_param_bytes=100,
        )
        out = wrapper.run_skill(None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert out["feasible"] is True
    assert out["phase_breakdown"]["inference"]["total_bytes"] == 1_000_140
    assert out["estimated_gb"] == round(1_000_140 / 1024**3, 3)
    assert out["static_preflight_evidence"]["phases"][1]["vram_estimate_bytes"] == 1_000_130


# ── 8. Schema violation preserved from Phase D.4 ───────────────────────────


def test_pydantic_validation_error_maps_to_schema_violation_response():
    """A ``pydantic.ValidationError`` during model or loss instantiation
    must return the canonical ``schema_violation`` dict — not crash, not
    fall into the ``memory_killer`` path. The Proposer's memory uses the
    ``violations`` field to avoid repeating the same config."""

    # Build a real ValidationError by validating a schema with a bad value.
    class _Demo(BaseModel):
        n: int

    try:
        _Demo(n="not_an_int")
    except ValidationError as ve:
        real_ve = ve

    with _Patches() as p:
        p.build_model.side_effect = real_ve
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())

    assert out["status"] == "schema_violation"
    assert "violations" in out
    assert "offending_config" in out
    assert "verdict" in out
    assert "suggestion" in out


# ── 9. vram_budget_gb soft cap is honoured ─────────────────────────────────


def test_vram_budget_gb_further_restricts_cap():
    """``vram_budget_gb`` is an operator-set soft cap. The effective cap
    must be ``min(ctx.usable_cap_bytes, budget)``."""
    with _Patches():
        # Training peak = 70 bytes with a neutral probe → fits a 32 GB GPU
        # easily. Clamp the budget to 1 byte so the wrapper must refuse.
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(32.0),
            vram_budget_gb=1e-12,  # near-zero byte cap
            **_run_kwargs(),
        )
    # Budget clamps below training peak → VRAM refusal:
    assert out["feasible"] is False
    assert out["memory_killer"]["binding_cap"] == "vram"


def test_vram_budget_gb_cannot_exceed_physical_cap():
    """Veto direction: ``hardware_context.usable_cap_bytes`` (the
    ``0.80 × total_memory_bytes`` physical ceiling) is **absolute**. An
    operator-set ``vram_budget_gb`` that is *larger* than the physical
    ceiling MUST be ignored by ``min()`` — the effective cap stays at
    the physical limit, never the budget.

    Scenario per directive: 32 GB device → physical cap 25.6 GB. Operator
    requests 30 GB (> 25.6 GB). ``limit_gb`` must be 25.6, not 30.0.
    The returned ``vram_budget_gb`` still echoes the operator's request
    so the record-keeping layer knows what was asked for — but the cap
    used for the feasibility check is the physical one.

    Pairs with ``test_vram_budget_gb_further_restricts_cap`` (restriction
    direction): together they pin both halves of the ``min(physical, budget)``
    contract — restriction when budget < physical, veto when budget > physical.
    """
    with _Patches():
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(32.0),
            vram_budget_gb=30.0,  # exceeds physical 25.6 GB
            **_run_kwargs(),
        )
    # 32.0 × 0.80 = 25.6. The physical cap MUST win.
    assert out["limit_gb"] == pytest.approx(25.6, abs=0.01)
    # Operator's request is preserved in the record but did NOT become the cap.
    assert out["vram_budget_gb"] == 30.0
    # Neutral probe fits well inside 25.6 GB, so the config is feasible.
    assert out["feasible"] is True


# ── 10. Killer renderers receive the cap = ctx.usable_cap_bytes ────────────


# `test_feasible_verdict_mentions_cap_and_dominant_phase` and
# `test_estimated_gb_and_limit_gb_are_floats_in_gb_units` lived here. Both ran
# `_gpu_ctx(32.0)`, which is `_gpu_ctx()`'s default, so they repeated the
# feasible-path call a seventh and eighth time. Their assertions moved into
# `test_feasible_path_reports_the_measured_values` above, beside the other
# value assertions on the same call.
#
# `test_vram_budget_gb_cannot_exceed_physical_cap` above stays separate: it
# passes `vram_budget_gb=30.0` and is about the VETO direction of `min()`,
# not about what a plain feasible run returns.


@pytest.mark.parametrize("historical", [False, True])
def test_large_task_shape_uses_one_selected_rule_in_both_phases(monkeypatch, historical):
    """#689: actual wrapper and batch resolver agree; only expensive probes are fake."""
    from dataclasses import replace
    from functools import partial

    from agent.skills.evaluate_vram_skill import batch_resolver, compute_intensity
    from core.preflight_estimation import (
        BatchSegmentationLimit,
        bind_preflight_estimator,
        resolve_preflight_estimator,
    )

    profile = replace(
        resolve_preflight_estimator(),
        workload_rule=BatchSegmentationLimit(limit=800_000) if historical else None,
    )
    real_passes = compute_intensity.passes
    with bind_preflight_estimator(profile), _Patches() as patches:
        patches.intensity_passes.side_effect = real_passes
        patches.resolve.side_effect = partial(
            batch_resolver.resolve_inference_decision, candidate_batches=(1,)
        )
        monkeypatch.setattr(
            batch_resolver, "probe_activation_footprint", patches._probe_side_effect
        )
        out = wrapper.run_skill(
            None,
            hardware_context=_gpu_ctx(),
            probe_input_sample=torch.zeros(1, 4),
            probe_target_sample=torch.zeros(1, 4, dtype=torch.long),
            max_inference_batch_size=1,
            **_run_kwargs(model_config={"segmentation_size": 5_469_229}),
        )
    assert out["status"] == "success"
    assert out["feasible"] is (not historical)
    evidence = StaticPreflightEvidence.model_validate(out["static_preflight_evidence"])
    assert evidence.binding_caps == (("compute_intensity",) if historical else ())
    for phase in evidence.phases:
        assert phase.batch_size == 1
        assert phase.intensity_product == (5_469_229 if historical else None)
        assert phase.intensity_limit == (800_000 if historical else None)
    if historical:
        assert evidence.phases[1].vram_estimate_bytes is None
    else:
        assert all(phase.vram_estimate_bytes is not None for phase in evidence.phases)
