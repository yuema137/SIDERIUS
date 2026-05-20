"""Return-contract tests for ``agent/skills/evaluate_vram_skill/wrapper.py``.

Phase 6.6 §3.7. The wrapper is the single consumer of five primitives
(``structural_probe``, ``overhead``, ``batch_resolver``, ``compute_intensity``,
``killer_report``). These tests pin:

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
- over-budget paths (training-VRAM, training-intensity, inference-resolver)
  route to the correct ``killer_report`` renderer and flatten via
  ``model_dump`` into the ``memory_killer`` slot;
- schema-violation path (``pydantic.ValidationError`` from plugin config)
  preserved from Phase D.4.

All tests are hermetic — no real model instantiation, no real probe run,
no CUDA, no filesystem. Primitives are patched at the wrapper module
level because that is the import surface the wrapper uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from agent.skills.evaluate_vram_skill import wrapper
from agent.skills.evaluate_vram_skill.killer_report import (
    KillerReport,
    MemoryKillerDetails,
)
from agent.skills.evaluate_vram_skill.structural_probe import (
    AutogradTapeReport,
    ForwardLayerReport,
    LayerReport,
    ProbeResult,
)
from core.hardware_context import HardwareContext

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
    sum_out = sum(l.output_bytes for l in layers if l.is_leaf)
    max_out = max((l.output_bytes for l in layers if l.is_leaf), default=0)
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
        self.model_mock = MagicMock(name="model", parameters=lambda: iter([]))
        self.loss_mock = MagicMock(name="loss_module")
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
                "resolve_inference_batch",
                side_effect=self._resolve_side_effect,
            ),
            patch.object(wrapper, "training_overhead_bytes", return_value=20),
            patch.object(wrapper, "cuda_context_bytes", return_value=30),
            patch.object(wrapper, "cudnn_backward_workspace_bytes", return_value=40),
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
        return self.resolved_batch


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
    }
)


def test_return_dict_has_all_required_keys_on_feasible_path():
    """Every key in the contract must be present in the return dict."""
    with _Patches():
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert _REQUIRED_KEYS.issubset(out.keys()), f"Missing keys: {_REQUIRED_KEYS - set(out.keys())}"


def test_removed_inference_batch_uncalibrated_is_absent():
    """Phase K's ``inference_batch_uncalibrated`` is obsolete under the
    probe-driven resolver. Its presence would mean a merge leak."""
    with _Patches():
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert "inference_batch_uncalibrated" not in out


def test_inference_batch_is_populated_on_feasible_path():
    """``inference_batch`` must be the int the resolver chose."""
    with _Patches() as p:
        p.resolved_batch = 16
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert out["inference_batch"] == 16
    assert isinstance(out["inference_batch"], int)


def test_memory_killer_is_none_on_feasible_path():
    """On success the killer slot is ``None`` — it is only populated when
    the wrapper refused the config."""
    with _Patches():
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert out["feasible"] is True
    assert out["memory_killer"] is None


def test_feasible_status_is_success():
    with _Patches():
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert out["status"] == "success"


def test_phase_breakdown_has_training_and_inference():
    """The breakdown is keyed by phase name. Both probed phases must land
    in the map; ``scoring`` is a passthrough slot left for Phase 6.7."""
    with _Patches():
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert set(out["phase_breakdown"].keys()) >= {"training", "inference"}


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
    """When training peak exceeds the cap but intensity passes, the
    wrapper must route to ``render_vram_report``: ``memory_killer.binding_cap
    == 'vram'``, ``feasible=False``, ``status='schema_violation'``."""
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
    assert out["status"] == "schema_violation"
    assert out["memory_killer"] is not None
    assert isinstance(out["memory_killer"], dict)
    assert out["memory_killer"]["binding_cap"] == "vram"
    assert out["memory_killer"]["dominant_layer"] == "big_layer"


# ── 5. Training-intensity over-budget ──────────────────────────────────────


def test_training_intensity_over_budget_produces_intensity_killer():
    """When training VRAM fits but B*T > 800k, route to
    ``render_intensity_report`` — the fix is a config lever, not a layer."""
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
    assert out["memory_killer"]["dominant_layer"] == "huge"
    assert out["memory_killer"]["batch_size"] == 25


# ── 7. Inference-resolver failure ──────────────────────────────────────────


def test_inference_resolver_vram_failure_produces_vram_killer():
    """``resolve_inference_batch`` raises ``ValueError`` with a message
    that contains ``Binding cap(s): vram.`` when every candidate B blows
    the cap. The wrapper must parse the label, re-probe at B=1, and emit a
    VRAM killer report."""
    with _Patches() as p:
        p.resolve.side_effect = ValueError("No inference batch size fits. Binding cap(s): vram.")
        # Re-probe at B=1 returns an inference probe with a dominant layer:
        p.inference_probe = _probe(
            mode="inference",
            layers=[_leaf("dom_layer", "Any", 9_000_000_000)],
            input_bytes=10,
            output_bytes=10,
            total_param_bytes=100,
        )
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(), **_run_kwargs())
    assert out["feasible"] is False
    assert out["inference_batch"] is None
    assert out["memory_killer"]["binding_cap"] == "vram"
    assert out["memory_killer"]["dominant_layer"] == "dom_layer"


def test_inference_resolver_intensity_failure_produces_intensity_killer():
    """When the resolver fails on intensity at B=1, the wrapper must NOT
    re-probe (pure ``segmentation_size`` problem, no layer attribution)."""
    with _Patches() as p:
        p.resolve.side_effect = ValueError(
            "No inference batch size fits. Binding cap(s): compute_intensity."
        )
        out = wrapper.run_skill(
            sandbox=None,
            hardware_context=_gpu_ctx(),
            **_run_kwargs(model_config={"segmentation_size": 900_000}),
        )
    assert out["feasible"] is False
    assert out["memory_killer"]["binding_cap"] == "compute_intensity"
    assert out["memory_killer"]["segmentation_size"] == 900_000


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
    with _Patches() as p:
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


def test_feasible_verdict_mentions_cap_and_dominant_phase():
    with _Patches() as p:
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(32.0), **_run_kwargs())
    # 32 GB × 0.80 = 25.6 GB cap
    assert "25.6 GB" in out["verdict"] or "25.60 GB" in out["verdict"]
    assert "Dominant phase" in out["verdict"]


def test_estimated_gb_and_limit_gb_are_floats_in_gb_units():
    with _Patches():
        out = wrapper.run_skill(sandbox=None, hardware_context=_gpu_ctx(32.0), **_run_kwargs())
    assert isinstance(out["estimated_gb"], float)
    assert isinstance(out["limit_gb"], float)
    # 32 GB × 0.80 = 25.6 GB
    assert out["limit_gb"] == pytest.approx(25.6, abs=0.01)
