"""Unit tests for agent/skills/evaluate_vram_skill/batch_resolver.py.

Phase 6.6 §3.5. We mock ``probe_activation_footprint`` so the resolver's
logic is tested independently of torch or torchinfo. The probe's real
behaviour is covered by tests/unit/agent/evaluate_vram_skill/test_structural_probe.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch
import torch.nn as nn

from agent.skills.evaluate_vram_skill import batch_resolver, estimation_inputs
from agent.skills.evaluate_vram_skill.batch_resolver import (
    _DEFAULT_CANDIDATE_BATCHES,
    BatchSearchRefused,
    resolve_inference_batch,
    resolve_inference_decision,
)
from agent.skills.evaluate_vram_skill.overhead import cuda_context_bytes
from agent.skills.evaluate_vram_skill.structural_probe import (
    ForwardLayerReport,
    ProbeResult,
)
from core.preflight_observations import RegisteredStateInventory

# ── Fakes ───────────────────────────────────────────────────────────────────


class _NoOp(nn.Module):
    """Stand-in for a real model. The resolver never calls .forward when
    ``probe_activation_footprint`` is monkeypatched, so this is just a
    valid ``nn.Module`` placeholder for the type hint."""


def _make_probe_result(params_bytes: int, activation_bytes: int) -> ProbeResult:
    """Build a minimal ProbeResult that satisfies the fields the resolver
    reads (`model_forward.total_param_bytes`, `.forward_output_bytes_sum`).
    Every other field is filled with a plausible zero."""
    return ProbeResult(
        mode="inference",
        model_forward=ForwardLayerReport(
            module_name="Fake",
            layers=[],
            total_param_bytes=params_bytes,
            forward_output_bytes_sum=activation_bytes,
            forward_output_bytes_max=activation_bytes,
        ),
        loss_forward=None,
        autograd_tape=None,
        input_bytes=0,
        output_bytes=0,
    )


def _install_probe(monkeypatch, curve):
    """Install a fake ``probe_activation_footprint`` that returns
    ``_make_probe_result(*curve(B))`` for whatever batch size was probed.

    ``curve`` is ``B -> (params_bytes, activation_bytes)``. This lets each
    test specify an explicit bytes-vs-B relationship and verify the resolver
    picks the right batch.
    """

    def fake_probe(*, model, loss_module, input_sample, target_sample, mode, device="cpu"):
        B = input_sample.shape[0]
        params_bytes, activation_bytes = curve(B)
        model.projected_parameter_bytes = params_bytes
        return _make_probe_result(params_bytes, activation_bytes)

    monkeypatch.setattr(batch_resolver, "probe_activation_footprint", fake_probe)
    monkeypatch.setattr(
        estimation_inputs,
        "inventory_registered_state",
        lambda model: RegisteredStateInventory(
            status="available",
            parameter_bytes=model.projected_parameter_bytes,
            trainable_parameter_bytes=model.projected_parameter_bytes,
            buffer_bytes=0,
            parameter_count=1,
            buffer_count=0,
        ),
    )


# ── Happy path: VRAM-only acceptance at various batches ─────────────────────


def test_picks_largest_batch_when_all_fit(monkeypatch):
    """Params + activation both tiny; intensity well under cap at T=1000.
    Every candidate clears both caps → resolver returns the largest (64)."""
    _install_probe(monkeypatch, lambda B: (1_000_000, B * 1_000_000))
    cap = 10 * 1024**3  # 10 GB — plenty

    assert resolve_inference_batch(_NoOp(), segmentation_size=1000, cap_bytes=cap) == 64


def test_missing_segmentation_uses_supplied_probe_without_intensity(monkeypatch):
    """A fixed task probe is measured; absent temporal geometry is not priced."""
    _install_probe(monkeypatch, lambda B: (1_000_000, B * 1_000_000))
    probe = torch.zeros((1, 4), dtype=torch.float32)
    assert (
        resolve_inference_batch(
            _NoOp(), segmentation_size=None, supplied_probe=probe, cap_bytes=10 * 1024**3
        )
        == 64
    )


def test_missing_segmentation_without_probe_refuses_by_name():
    with pytest.raises(ValueError, match="segmentation dimension unavailable"):
        resolve_inference_batch(_NoOp(), segmentation_size=None, cap_bytes=10 * 1024**3)


def test_picks_largest_batch_that_fits_vram(monkeypatch):
    """Activation scales at 100 MB × B. Cap is 1 GB + overhead + params.
    Only B ≤ 8 fits → resolver returns 8, skipping 64/32/16."""
    params = 50 * 1024**2  # 50 MB
    per_B = 100 * 1024**2  # 100 MB per batch-sample
    _install_probe(monkeypatch, lambda B: (params, B * per_B))
    # Budget: exactly enough for B=8 (50 + 800 MB activations + 185 MB context ≈ 1035 MB)
    cap = params + 8 * per_B + cuda_context_bytes()

    got = resolve_inference_batch(_NoOp(), segmentation_size=1000, cap_bytes=cap)
    assert got == 8


def test_picks_batch_equal_to_cap_boundary(monkeypatch):
    """`peak <= cap` (not `<`): a batch whose peak exactly matches the cap
    must be accepted. Pin this so a future tightening to `<` trips a test."""
    params = 10 * 1024**2
    per_B = 20 * 1024**2
    _install_probe(monkeypatch, lambda B: (params, B * per_B))
    # At B=4: peak = 10 + 80 + 185 MB
    cap = params + 4 * per_B + cuda_context_bytes()

    got = resolve_inference_batch(_NoOp(), segmentation_size=1000, cap_bytes=cap)
    assert got == 4


# ── Candidate-list overrides ───────────────────────────────────────────────


def test_respects_custom_candidate_order(monkeypatch):
    """A caller-supplied candidate list must be honoured descending."""
    _install_probe(monkeypatch, lambda B: (0, 0))
    cap = 10 * 1024**3

    got = resolve_inference_batch(
        _NoOp(),
        segmentation_size=1000,
        cap_bytes=cap,
        candidate_batches=[128, 96, 48],
    )
    assert got == 128


def test_task_semantic_ceiling_limits_the_resource_feasible_batch(monkeypatch):
    """A memory-feasible batch must not exceed the task's collation ceiling."""
    _install_probe(monkeypatch, lambda B: (0, 0))

    got = resolve_inference_batch(
        _NoOp(),
        segmentation_size=1000,
        cap_bytes=10 * 1024**3,
        max_batch_size=1,
    )

    assert got == 1


def test_empty_candidate_list_raises(monkeypatch):
    _install_probe(monkeypatch, lambda B: (0, 0))
    with pytest.raises(ValueError, match="candidate_batches must be non-empty"):
        resolve_inference_batch(
            _NoOp(),
            segmentation_size=1000,
            cap_bytes=10 * 1024**3,
            candidate_batches=[],
        )


# ── Compute-intensity cap: rejects even when VRAM fits ─────────────────────


@pytest.mark.usefixtures("historical_workload_rule")
def test_skips_candidate_that_fits_vram_but_fails_intensity(monkeypatch):
    """At T=40000: B=64 → 2,560,000 fails; B=32 → 1,280,000 fails;
    B=16 → 640,000 passes (< 800_000). Activations are nil, so every
    candidate clears VRAM easily. Resolver must still skip 64/32 and land
    on 16 because intensity dominates."""
    _install_probe(monkeypatch, lambda B: (0, 0))
    cap = 10 * 1024**3

    got = resolve_inference_batch(_NoOp(), segmentation_size=40_000, cap_bytes=cap)
    assert got == 16


@pytest.mark.usefixtures("historical_workload_rule")
def test_intensity_cap_at_exact_boundary_accepts(monkeypatch):
    """`compute_intensity.passes` uses `<=`. At B=20, T=40000 → 800_000 ==
    cap → must be accepted. At B=32, product = 1,280,000 → rejected.
    With a hand-built candidate list [32, 20, 10], resolver picks 20."""
    _install_probe(monkeypatch, lambda B: (0, 0))
    cap = 10 * 1024**3

    got = resolve_inference_batch(
        _NoOp(),
        segmentation_size=40_000,
        cap_bytes=cap,
        candidate_batches=[32, 20, 10],
    )
    assert got == 20


# ── Failure modes: diagnostic names the binding cap ────────────────────────


def _binding_label(msg: str) -> str:
    """Extract just the `Binding cap(s): <label>` substring. The full error
    message also includes hint text that mentions both 'vram' and
    'compute_intensity' unconditionally — so a naive 'in msg' check of
    those words would always pass. The label is the only authoritative
    field the resolver reports."""
    after = msg.split("Binding cap(s):", 1)[1]
    return after.split(".", 1)[0].strip()


def test_raises_vram_binding_when_smallest_batch_blows_cap(monkeypatch):
    """Params alone exceed cap — no batch fits. B=1 passes intensity
    trivially (1 × 40000 = 40k << 800k), so the binding cap is VRAM only."""
    _install_probe(monkeypatch, lambda B: (100 * 1024**3, 0))  # 100 GB of params
    cap = 25 * 1024**3  # 25 GB

    with pytest.raises(ValueError) as exc_info:
        resolve_inference_batch(_NoOp(), segmentation_size=40_000, cap_bytes=cap)

    label = _binding_label(str(exc_info.value))
    assert label == "vram", f"Expected VRAM-only binding, got {label!r}"


@pytest.mark.usefixtures("historical_workload_rule")
def test_raises_intensity_binding_when_only_intensity_fails(monkeypatch):
    """Activations are nil; cap is huge → VRAM is never binding. But every
    candidate has B × T > 800_000, so intensity refuses all. B=1 is the
    last tried: 1 × 1_000_000 = 1,000,000 > 800_000."""
    _install_probe(monkeypatch, lambda B: (0, 0))
    cap = 100 * 1024**3

    with pytest.raises(ValueError) as exc_info:
        resolve_inference_batch(_NoOp(), segmentation_size=1_000_000, cap_bytes=cap)

    label = _binding_label(str(exc_info.value))
    assert label == "compute_intensity", f"Expected intensity-only binding, got {label!r}"


@pytest.mark.usefixtures("historical_workload_rule")
def test_intensity_only_refusal_does_not_invent_unmeasured_vram_verdict(monkeypatch):
    """All batches are ineligible; do not run or claim a memory measurement."""

    def forbidden_probe(batch):
        pytest.fail("an intensity-ineligible batch must never be probed")

    _install_probe(monkeypatch, forbidden_probe)
    cap = 1 * 1024**3

    with pytest.raises(ValueError) as exc_info:
        resolve_inference_batch(_NoOp(), segmentation_size=800_000 + 1, cap_bytes=cap)

    label = _binding_label(str(exc_info.value))
    assert label == "compute_intensity", f"Only intensity was measured, got {label!r}"


def test_error_message_surfaces_cap_and_peak_numbers(monkeypatch):
    """The Memory Killer report needs the raw numbers to render a useful
    suggestion — not just the binding label."""
    _install_probe(monkeypatch, lambda B: (5 * 1024**3, 0))
    cap = 1 * 1024**3

    with pytest.raises(ValueError) as exc_info:
        resolve_inference_batch(_NoOp(), segmentation_size=1000, cap_bytes=cap)

    msg = str(exc_info.value)
    assert "predicted_peak=" in msg
    assert "cap_bytes=" in msg
    assert "compute_intensity_passes=" in msg


@pytest.mark.usefixtures("historical_workload_rule")
def test_error_message_names_segmentation_size(monkeypatch):
    """The Proposer must see T so it knows which lever to pull."""
    _install_probe(monkeypatch, lambda B: (100 * 1024**3, 0))
    with pytest.raises(ValueError, match="segmentation_size=12345"):
        resolve_inference_batch(_NoOp(), segmentation_size=12_345, cap_bytes=1 * 1024**3)


# ── Descending-search verification ────────────────────────────────────────


def test_visits_batches_in_descending_order_and_stops_early(monkeypatch):
    """Resolver must try B=64 first, then 32, then 16 — and stop as soon as
    one clears. Activations engineered so B=16 is the first to fit."""
    calls: list[int] = []

    def fake_probe(*, model, loss_module, input_sample, target_sample, mode, device="cpu"):
        B = input_sample.shape[0]
        calls.append(B)
        # Peak = B * 1 GB + 185 MB context
        return _make_probe_result(0, B * 1024**3)

    monkeypatch.setattr(batch_resolver, "probe_activation_footprint", fake_probe)

    cap = 16 * 1024**3 + cuda_context_bytes()  # fits exactly at B=16
    got = resolve_inference_batch(_NoOp(), segmentation_size=1000, cap_bytes=cap)

    assert got == 16
    assert calls == [64, 32, 16], f"Expected descending probe order, got {calls}"


def test_exhausts_all_candidates_before_raising(monkeypatch):
    """When no candidate fits, every one of them must be probed. (Equivalent
    to: the resolver does not short-circuit on a partial failure.)"""
    calls: list[int] = []

    def fake_probe(*, model, loss_module, input_sample, target_sample, mode, device="cpu"):
        calls.append(input_sample.shape[0])
        return _make_probe_result(0, 1000 * 1024**3)  # 1000 GB of activations

    monkeypatch.setattr(batch_resolver, "probe_activation_footprint", fake_probe)

    with pytest.raises(ValueError):
        resolve_inference_batch(_NoOp(), segmentation_size=1000, cap_bytes=1 * 1024**3)

    assert calls == list(_DEFAULT_CANDIDATE_BATCHES)


# ── Default candidate space regression ─────────────────────────────────────


def test_default_candidate_batches_matches_spec():
    """§3.5 specifies the default search space explicitly. Changing it is a
    design decision — this test guards the spec from a casual edit."""
    assert _DEFAULT_CANDIDATE_BATCHES == (64, 32, 16, 8, 4, 2, 1)


# ── Principle 2 module-source spot-check ──────────────────────────────────


@pytest.mark.usefixtures("historical_workload_rule")
def test_known_ineligible_batches_never_execute_a_probe(monkeypatch):
    """2026-09-19: CPU probes at 64/32 consumed 668s before eligible batch16."""
    measured = []

    def curve(batch):
        measured.append(batch)
        assert batch <= 16, "known intensity refusal must precede expensive forward"
        return 0, 0

    _install_probe(monkeypatch, curve)
    assert resolve_inference_batch(_NoOp(), segmentation_size=40000, cap_bytes=10 * 1024**3) == 16
    assert measured == [16]


def test_typed_refusal_keeps_last_custom_batch_and_original_estimate(monkeypatch):
    """#615: diagnosis must retain the rejecting sum, not re-probe B=1 with max."""
    _install_probe(monkeypatch, lambda batch: (1024, batch * 10_000))
    with pytest.raises(BatchSearchRefused) as exc:
        resolve_inference_decision(
            _NoOp(), segmentation_size=10, cap_bytes=1, candidate_batches=(7, 3)
        )
    assert isinstance(exc.value, ValueError)
    decision = exc.value.decision
    assert decision.batch_size == 3
    assert decision.vram_estimate_bytes == 1024 + 30_000 + cuda_context_bytes()
    assert decision.binding_caps == ("vram",)
    assert decision.estimator == "inference_registered_state_v1"


@pytest.mark.usefixtures("historical_workload_rule")
def test_prefilter_refusal_keeps_actual_custom_batch_without_vram_observation(monkeypatch):
    """#615: intensity prefilter must not invent a B=1 probe or zero-byte peak."""
    monkeypatch.setattr(
        batch_resolver,
        "probe_activation_footprint",
        lambda **kwargs: pytest.fail("ineligible candidates were probed"),
    )
    with pytest.raises(BatchSearchRefused) as exc:
        resolve_inference_decision(
            _NoOp(), segmentation_size=400_000, cap_bytes=1, candidate_batches=(7, 3)
        )
    assert exc.value.decision.batch_size == 3
    assert exc.value.decision.intensity_product == 1_200_000
    assert exc.value.decision.vram_estimate_bytes is None
    assert exc.value.decision.binding_caps == ("compute_intensity",)


@pytest.mark.parametrize(
    "failure", [MemoryError("host allocation failed"), RuntimeError("CUDA out of memory")]
)
def test_exhausted_allocation_failures_keep_original_domain(monkeypatch, failure):
    """#615: an unobserved final candidate cannot become a structural VRAM refusal."""
    visited = []

    def fail(**kwargs):
        visited.append(kwargs["input_sample"].shape[0])
        raise failure

    monkeypatch.setattr(batch_resolver, "probe_activation_footprint", fail)
    with pytest.raises(type(failure)) as exc:
        resolve_inference_decision(
            _NoOp(), segmentation_size=10, cap_bytes=1, candidate_batches=(7, 3)
        )
    assert exc.value is failure
    assert visited == [7, 3]


def test_typed_success_keeps_no_temporal_dimension_and_boundary_selection(monkeypatch):
    """The evidence API must retain integer-API choice and absent intensity geometry."""
    _install_probe(monkeypatch, lambda batch: (1024, batch * 100))
    decision = resolve_inference_decision(
        _NoOp(),
        segmentation_size=None,
        cap_bytes=1024 + 300 + cuda_context_bytes(),
        candidate_batches=(7, 3),
        supplied_probe=torch.zeros(1, 4),
    )
    assert decision.batch_size == 3
    assert decision.vram_estimate_bytes == decision.vram_cap_bytes
    assert decision.intensity_product is None
    assert decision.binding_caps == ()
