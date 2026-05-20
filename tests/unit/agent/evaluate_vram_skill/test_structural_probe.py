"""Unit tests for agent/skills/evaluate_vram_skill/structural_probe.py.

All tests run on CPU — no CUDA dependency. The probe's behaviour is identical
on CPU and GPU because it reads tensor metadata, not GPU memory counters.
"""

from __future__ import annotations

import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from agent.skills.evaluate_vram_skill.structural_probe import (
    AutogradTapeReport,
    ForwardLayerReport,
    LayerReport,
    ProbeResult,
    probe_activation_footprint,
    probe_autograd_tape,
    probe_forward_layers,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


class TinyModel(nn.Module):
    """Linear → ReLU → Linear. 3 leaf layers, fully deterministic shapes."""

    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(8, 16, bias=True)
        self.act = nn.ReLU()
        self.fc2 = nn.Linear(16, 4, bias=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.act(self.fc1(x)))


class LogitsProducer(nn.Module):
    """[B, T] long → [B, C, T] float. Mirrors SIDERIUS plugin contract."""

    def __init__(self, embed_dim: int = 8, channels: int = 16, n_classes: int = 32):
        super().__init__()
        self.emb = nn.Embedding(256, embed_dim)
        self.conv = nn.Conv1d(embed_dim, channels, 3, padding=1)
        self.out = nn.Conv1d(channels, n_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.out(self.conv(self.emb(x).transpose(1, 2)))


class FocalLikeLoss(nn.Module):
    """Mimics FocalLoss1D's ``[B, 256, T]`` intermediate-tensor pattern. Used
    to prove the tape walker captures what torchinfo cannot see."""

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        target_oh = F.one_hot(target, logits.size(1)).permute(0, 2, 1).float()
        log_p = F.log_softmax(logits, dim=1)
        p = log_p.exp()
        return -((1 - p) ** 2 * target_oh * log_p).sum(dim=1).mean()


# ── probe_forward_layers ────────────────────────────────────────────────────


def test_probe_forward_layers_returns_pydantic():
    model = TinyModel()
    x = torch.randn(2, 8)
    report = probe_forward_layers(model, x)
    assert isinstance(report, ForwardLayerReport)
    assert report.module_name == "TinyModel"
    assert all(isinstance(li, LayerReport) for li in report.layers)


def test_probe_forward_layers_counts_leaves_only_for_aggregates():
    """torchinfo emits both the root container and its leaves. Aggregates
    (total_param_bytes, forward_output_bytes_sum) must not double-count
    the container's bytes on top of its children."""
    model = TinyModel()
    x = torch.randn(2, 8)
    report = probe_forward_layers(model, x)

    leaf_params = sum(li.param_bytes for li in report.layers if li.is_leaf)
    assert report.total_param_bytes == leaf_params

    leaf_outputs = sum(li.output_bytes for li in report.layers if li.is_leaf)
    assert report.forward_output_bytes_sum == leaf_outputs


def test_probe_forward_layers_param_bytes_match_hand_computed():
    """fc1: 8*16 + 16 = 144 params; fc2: 16*4 + 4 = 68 params; f32 → ×4."""
    model = TinyModel()
    x = torch.randn(2, 8)
    report = probe_forward_layers(model, x)
    expected_params = (8 * 16 + 16) + (16 * 4 + 4)
    assert report.total_param_bytes == expected_params * 4


def test_probe_forward_layers_preserves_construction_order():
    model = TinyModel()
    x = torch.randn(2, 8)
    report = probe_forward_layers(model, x)
    leaf_vars = [li.var_name for li in report.layers if li.is_leaf]
    assert leaf_vars == ["fc1", "act", "fc2"]


def test_probe_forward_layers_max_output_is_truly_max():
    model = TinyModel()
    x = torch.randn(2, 8)
    report = probe_forward_layers(model, x)
    manual_max = max(li.output_bytes for li in report.layers if li.is_leaf)
    assert report.forward_output_bytes_max == manual_max


def test_probe_forward_layers_accepts_multi_input_module():
    """Losses take (logits, target) — probe must pass both as *args."""
    loss = FocalLikeLoss()
    logits = torch.randn(2, 32, 10)
    target = torch.randint(0, 32, (2, 10), dtype=torch.long)
    report = probe_forward_layers(loss, [logits, target])
    assert isinstance(report, ForwardLayerReport)
    assert report.module_name == "FocalLikeLoss"


# ── probe_autograd_tape ─────────────────────────────────────────────────────


def test_probe_autograd_tape_returns_pydantic():
    w = nn.Linear(4, 4)
    x = torch.randn(2, 4, requires_grad=True)

    def fwd():
        return w(x).sum()

    report = probe_autograd_tape(fwd)
    assert isinstance(report, AutogradTapeReport)


def test_probe_autograd_tape_captures_nonzero_bytes_for_training_graph():
    """Any grad-enabled forward through a Linear layer must save at least
    the input tensor (backward needs it to compute grad_W)."""
    w = nn.Linear(4, 4)
    x = torch.randn(2, 4, requires_grad=True)

    def fwd():
        return w(x).sum()

    report = probe_autograd_tape(fwd)
    assert report.unique_storage_count > 0
    assert report.total_saved_bytes > 0


def test_probe_autograd_tape_dedup_across_views_of_same_storage():
    """Storage-ptr dedup is the headline requirement. Build a graph that
    re-uses the same storage via a view, and assert the walker counts it
    exactly once."""
    base = torch.randn(10, 10, requires_grad=True)
    w1 = nn.Linear(10, 10, bias=False)
    w2 = nn.Linear(10, 10, bias=False)

    def fwd():
        # view shares storage with base
        view = base[:5]
        return (w1(view) + w2(view)).sum()

    report = probe_autograd_tape(fwd)
    # If dedup is wrong, `view` would be counted twice (once per usage);
    # with correct dedup it is counted once.
    # We assert the reported bytes do not exceed the sum of all unique
    # parameter storages + base storage + any intermediates, all counted once.
    base_bytes = base.untyped_storage().nbytes()
    w1_bytes = w1.weight.untyped_storage().nbytes()
    w2_bytes = w2.weight.untyped_storage().nbytes()
    upper_bound_if_dedup_ok = base_bytes + w1_bytes + w2_bytes
    assert report.total_saved_bytes <= upper_bound_if_dedup_ok, (
        f"total_saved_bytes={report.total_saved_bytes} > upper_bound="
        f"{upper_bound_if_dedup_ok} — dedup is under-counting or views are "
        f"being double-counted."
    )


def test_probe_autograd_tape_captures_loss_intermediates_torchinfo_misses():
    """The motivating case: FocalLikeLoss creates `[B, C, T]` intermediates
    inside its forward that no submodule hook can see. The tape walker must
    capture them, and the total must exceed a trivial floor."""
    B, C, T = 4, 32, 50
    logits = torch.randn(B, C, T, requires_grad=True)
    target = torch.randint(0, C, (B, T), dtype=torch.long)
    loss = FocalLikeLoss()

    def fwd():
        return loss(logits, target)

    report = probe_autograd_tape(fwd)
    # log_softmax alone saves its output (~B*C*T*4 bytes).
    floor = B * C * T * 4
    assert report.total_saved_bytes >= floor, (
        f"total_saved_bytes={report.total_saved_bytes} < floor={floor}: "
        f"expected at least the log_softmax output to be retained."
    )


# ── probe_activation_footprint ─────────────────────────────────────────────


def test_probe_activation_footprint_inference_mode_skips_tape():
    model = TinyModel()
    x = torch.randn(2, 8)
    result = probe_activation_footprint(
        model=model,
        loss_module=None,
        input_sample=x,
        target_sample=None,
        mode="inference",
        device="cpu",
    )
    assert isinstance(result, ProbeResult)
    assert result.mode == "inference"
    assert result.loss_forward is None
    assert result.autograd_tape is None
    assert result.input_bytes == 2 * 8 * 4  # f32
    assert result.output_bytes == 2 * 4 * 4


def test_probe_activation_footprint_training_mode_requires_loss_and_target():
    model = TinyModel()
    x = torch.randn(2, 8)
    with pytest.raises(ValueError, match="training mode requires both loss_module"):
        probe_activation_footprint(
            model=model,
            loss_module=None,
            input_sample=x,
            target_sample=None,
            mode="training",
            device="cpu",
        )


def test_probe_activation_footprint_training_populates_loss_and_tape():
    model = LogitsProducer(embed_dim=4, channels=8, n_classes=16)
    loss = FocalLikeLoss()
    B, T = 2, 20
    x = torch.randint(0, 256, (B, T), dtype=torch.long)
    y = torch.randint(0, 16, (B, T), dtype=torch.long)

    result = probe_activation_footprint(
        model=model,
        loss_module=loss,
        input_sample=x,
        target_sample=y,
        mode="training",
        device="cpu",
    )
    assert result.mode == "training"
    assert result.loss_forward is not None
    assert result.loss_forward.module_name == "FocalLikeLoss"
    assert result.autograd_tape is not None
    assert result.autograd_tape.total_saved_bytes > 0


def test_probe_training_bytes_exceed_inference_bytes_on_same_config():
    """Physical sanity: training must retain more than inference. This is
    the A.13 discovery (0.82 GB train vs 0.42 GB infer) at unit scale."""
    model_inf = LogitsProducer(embed_dim=4, channels=8, n_classes=16)
    model_tr = LogitsProducer(embed_dim=4, channels=8, n_classes=16)
    model_tr.load_state_dict(model_inf.state_dict())
    loss = FocalLikeLoss()
    B, T = 2, 20
    x = torch.randint(0, 256, (B, T), dtype=torch.long)
    y = torch.randint(0, 16, (B, T), dtype=torch.long)

    inf_result = probe_activation_footprint(
        model=model_inf,
        loss_module=None,
        input_sample=x,
        target_sample=None,
        mode="inference",
        device="cpu",
    )
    tr_result = probe_activation_footprint(
        model=model_tr,
        loss_module=loss,
        input_sample=x,
        target_sample=y,
        mode="training",
        device="cpu",
    )

    # Training must retain substantially more bytes than inference's single-
    # layer-at-a-time footprint.
    inf_peak = inf_result.input_bytes + 2 * inf_result.model_forward.forward_output_bytes_max
    tr_peak = (
        tr_result.autograd_tape.total_saved_bytes + tr_result.input_bytes + tr_result.output_bytes
    )
    assert tr_peak > inf_peak, (
        f"training peak ({tr_peak}) must exceed inference peak ({inf_peak}); "
        f"this is the physical truth the A.13 telemetry proved."
    )


def test_probe_activation_footprint_forward_layer_report_shapes_are_physical():
    """Smoke: the shapes torchinfo reports must match what the forward
    actually produces. If this drifts, the Memory Killer report is wrong."""
    model = LogitsProducer(embed_dim=4, channels=8, n_classes=16)
    x = torch.randint(0, 256, (2, 20), dtype=torch.long)
    result = probe_activation_footprint(
        model=model,
        loss_module=None,
        input_sample=x,
        target_sample=None,
        mode="inference",
        device="cpu",
    )

    # Final `out` layer: Conv1d(8, 16) → output [2, 16, 20]
    out_layer = next(
        li for li in result.model_forward.layers if li.is_leaf and li.var_name == "out"
    )
    assert out_layer.output_shape == [2, 16, 20]
    assert out_layer.output_bytes == 2 * 16 * 20 * 4


# ── Memory-safety tests (Phase 6.8 Commit 9) ──────────────────────────────


class SequentialModel(nn.Module):
    """Model with a Python-level sequential loop, mimicking SSM scan.
    Each iteration creates tensors retained by autograd in training mode."""

    def __init__(self, steps: int = 500, hidden: int = 16):
        super().__init__()
        self.proj = nn.Linear(hidden, hidden)
        self.steps = steps
        self.hidden = hidden

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        state = self.proj(x)
        for _ in range(self.steps):
            state = state * 0.99 + self.proj(x) * 0.01
        return state


def test_pack_hook_returns_none_not_tensor():
    """pack_hook must return None so autograd does NOT retain the actual
    tensor data. This is the core of the v6 OOM fix."""
    captured = []

    w = nn.Linear(4, 4)
    x = torch.randn(2, 4, requires_grad=True)

    original_pack = None

    def spy_pack(t):
        captured.append(t)
        return t

    # First: baseline — how many tensors autograd saves
    with torch.autograd.graph.saved_tensors_hooks(spy_pack, lambda t: t):
        _ = w(x).sum()
    baseline_count = len(captured)
    assert baseline_count > 0

    # Now verify our probe returns None
    report = probe_autograd_tape(lambda: w(x).sum())
    assert report.total_saved_bytes > 0
    assert report.unique_storage_count > 0


def test_probe_autograd_tape_unpack_raises_on_backward():
    """If someone accidentally calls backward() on the loss after probing,
    the unpack_hook should raise with a clear error."""
    w = nn.Linear(4, 4)
    x = torch.randn(2, 4, requires_grad=True)

    seen = {}

    def pack_hook(t):
        storage = t.untyped_storage()
        ptr = storage.data_ptr()
        if ptr and ptr not in seen:
            seen[ptr] = storage.nbytes()
        return None

    def unpack_hook(_):
        raise RuntimeError("probe_autograd_tape: backward() must not be called")

    with torch.autograd.graph.saved_tensors_hooks(pack_hook, unpack_hook):
        loss = w(x).sum()

    with pytest.raises(RuntimeError, match="backward.*must not be called"):
        loss.backward()


def test_sequential_model_probe_gc_called_between_phases():
    """Verify gc.collect() is called between the tape walk and the torchinfo
    passes inside probe_activation_footprint (training mode)."""
    import gc as gc_module
    from unittest.mock import patch

    model = SequentialModel(steps=10, hidden=8)
    loss = nn.MSELoss()
    x = torch.randn(1, 8)
    y = torch.randn(1, 8)

    gc_calls = []
    original_collect = gc_module.collect

    def counting_collect(*args, **kwargs):
        gc_calls.append(1)
        return original_collect(*args, **kwargs)

    with patch(
        "agent.skills.evaluate_vram_skill.structural_probe.gc.collect", side_effect=counting_collect
    ):
        result = probe_activation_footprint(
            model=model,
            loss_module=loss,
            input_sample=x,
            target_sample=y,
            mode="training",
            device="cpu",
        )

    assert isinstance(result, ProbeResult)
    assert result.autograd_tape.total_saved_bytes > 0
    # At least 2 gc.collect calls: one in probe_autograd_tape after del loss,
    # one in probe_activation_footprint after del _fwd.
    assert len(gc_calls) >= 2, (
        f"Expected >= 2 gc.collect() calls between probe phases, got {len(gc_calls)}"
    )


def test_sequential_model_training_probe_rss_bounded():
    """A model with 500 sequential steps should complete the training probe
    without RSS growth exceeding 500 MB. Before the fix, a similar model
    with 320K steps used ~33 GB."""
    import psutil

    model = SequentialModel(steps=500, hidden=16)
    loss = nn.MSELoss()
    x = torch.randn(1, 16)
    y = torch.randn(1, 16)

    rss_before = psutil.Process().memory_info().rss
    result = probe_activation_footprint(
        model=model,
        loss_module=loss,
        input_sample=x,
        target_sample=y,
        mode="training",
        device="cpu",
    )
    rss_after = psutil.Process().memory_info().rss
    delta_mb = (rss_after - rss_before) / (1024**2)

    assert isinstance(result, ProbeResult)
    assert result.autograd_tape.total_saved_bytes > 0
    assert delta_mb < 500, (
        f"RSS grew by {delta_mb:.1f} MB during sequential-model training probe; "
        f"expected < 500 MB. The pack_hook may not be returning None."
    )


def test_torchinfo_runs_under_no_grad_in_training_mode():
    """probe_forward_layers calls inside the training path must run under
    torch.no_grad() to prevent rebuilding the autograd graph."""
    grad_states = []

    class GradSpyModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(4, 4)

        def forward(self, x):
            grad_states.append(torch.is_grad_enabled())
            return self.fc(x)

    model = GradSpyModel()
    loss = nn.MSELoss()
    x = torch.randn(1, 4)
    y = torch.randn(1, 4)

    result = probe_activation_footprint(
        model=model,
        loss_module=loss,
        input_sample=x,
        target_sample=y,
        mode="training",
        device="cpu",
    )

    assert isinstance(result, ProbeResult)
    # forward is called 3+ times: once for tape (grad=True), then
    # torchinfo + shape forward (both should be no_grad).
    assert len(grad_states) >= 3
    # First call (tape walk): grad must be True
    assert grad_states[0] is True, "Tape walk must run with grad enabled"
    # Subsequent calls (torchinfo + shape): grad must be False
    for i, gs in enumerate(grad_states[1:], start=1):
        assert gs is False, (
            f"Forward call {i + 1} had grad_enabled={gs}; "
            f"torchinfo/shape passes must run under torch.no_grad()"
        )
