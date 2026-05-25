"""Unit tests for agent/skills/evaluate_vram_skill/killer_report.py.

Phase 6.6 §3.6 + §3.10.2. Pure Pydantic + probe-consumption logic — no
torch forward, no CUDA, no filesystem. All probes are hand-built
``ProbeResult`` instances so we can pin the layer-attribution outcome per
test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.skills.evaluate_vram_skill import killer_report
from agent.skills.evaluate_vram_skill.compute_intensity import _MAX_BATCH_TIMESTEPS
from agent.skills.evaluate_vram_skill.killer_report import (
    KillerReport,
    MemoryKillerDetails,
    PerLayerEntry,
    render_combined_report,
    render_intensity_report,
    render_vram_report,
)
from agent.skills.evaluate_vram_skill.structural_probe import (
    ForwardLayerReport,
    LayerReport,
    ProbeResult,
)

# ── Fixtures: minimal ProbeResult builders ─────────────────────────────────


def _leaf(
    var_name: str,
    class_name: str,
    output_bytes: int,
    output_shape: list[int] | None = None,
) -> LayerReport:
    """Build a single leaf LayerReport. Every field that the killer report
    reads is populated; the rest are plausible zeros."""
    return LayerReport(
        depth=1,
        var_name=var_name,
        class_name=class_name,
        input_shape=[],
        output_shape=output_shape or [1, 1],
        num_params=0,
        param_bytes=0,
        output_bytes=output_bytes,
        is_leaf=True,
    )


def _non_leaf(var_name: str, class_name: str, output_bytes: int) -> LayerReport:
    """A container layer — must be filtered out of per_layer + dominant
    selection since it double-counts its own leaves' bytes."""
    return LayerReport(
        depth=0,
        var_name=var_name,
        class_name=class_name,
        input_shape=[],
        output_shape=[1],
        num_params=0,
        param_bytes=0,
        output_bytes=output_bytes,
        is_leaf=False,
    )


def _probe(layers: list[LayerReport]) -> ProbeResult:
    total_params = sum(layer.param_bytes for layer in layers if layer.is_leaf)
    sum_out = sum(layer.output_bytes for layer in layers if layer.is_leaf)
    max_out = max((layer.output_bytes for layer in layers if layer.is_leaf), default=0)
    return ProbeResult(
        mode="inference",
        model_forward=ForwardLayerReport(
            module_name="Fake",
            layers=layers,
            total_param_bytes=total_params,
            forward_output_bytes_sum=sum_out,
            forward_output_bytes_max=max_out,
        ),
        loss_forward=None,
        autograd_tape=None,
        input_bytes=0,
        output_bytes=0,
    )


# ── VRAM renderer — layer-level attribution (§3.6) ─────────────────────────


def test_vram_report_identifies_dominant_leaf():
    """The leaf with the largest output_bytes wins. Name, class, and
    absolute bytes must all propagate verbatim into memory_killer."""
    layers = [
        _leaf("head", "Linear", 1_000_000_000),
        _leaf("block3_big", "MyBigOp", 8_000_000_000),  # ← dominant
        _leaf("tail", "Linear", 500_000_000),
    ]
    probe = _probe(layers)
    peak = 10_000_000_000
    cap = 5 * 1024**3
    total = 10 * 1024**3

    report = render_vram_report(probe, peak, cap, total)
    d = report.memory_killer

    assert d.binding_cap == "vram"
    assert d.dominant_layer == "block3_big"
    assert d.dominant_layer_class == "MyBigOp"
    assert d.dominant_layer_bytes == 8_000_000_000
    assert d.dominant_fraction == pytest.approx(0.8, abs=1e-9)


def test_vram_report_suggestion_names_dominant_layer_by_user_name():
    """The suggestion must name the *user-given* layer name (var_name),
    not the class. A user looking at their own code can only grep by
    var_name — naming the class would be useless guidance."""
    layers = [_leaf("my_attn_block", "InternalClassName", 9_000_000_000)]
    report = render_vram_report(_probe(layers), 10_000_000_000, 5 * 1024**3, 10 * 1024**3)
    assert "my_attn_block" in report.suggestion
    # The class name MUST NOT be surfaced into the suggestion itself:
    assert "InternalClassName" not in report.suggestion


def test_vram_report_suggestion_has_no_architecture_family_terms():
    """Principle 2 (§3.6 line 337): wording is deliberately generic — never
    mentions 'attention' or 'transformer' even when the layer in question
    is attention. Names a dimension to reduce, not an architecture class."""
    layers = [_leaf("block3_attn", "MultiheadAttention", 9_000_000_000)]
    report = render_vram_report(_probe(layers), 10_000_000_000, 5 * 1024**3, 10 * 1024**3)
    sugg = report.suggestion.lower()
    for banned in [
        "multiheadattention",
        "self-attention",
        "transformer",
        "wavenet",
        "punet",
        "fcnet",
        "rnn",
        "unet",
        "lstm",
    ]:
        assert banned not in sugg, f"architecture term {banned!r} leaked into VRAM suggestion"


def test_vram_report_suggestion_names_a_specific_dimension_to_reduce():
    """§3.6 demands an actionable lever. The suggestion must tell the
    Proposer what to shrink — channel dim, segmentation_size, or a
    complexity-replacement option."""
    layers = [_leaf("x", "Y", 9_000_000_000)]
    report = render_vram_report(_probe(layers), 10_000_000_000, 5 * 1024**3, 10 * 1024**3)
    sugg = report.suggestion.lower()
    assert "segmentation_size" in sugg
    assert "channel" in sugg
    assert "reduce" in sugg or "shrink" in sugg


def test_vram_verdict_format_includes_labels_and_byte_figures():
    """Verdict must distinguish VRAM mode (§3.10.2), quote the peak and the
    cap in GB, and quote the cap-as-percentage-of-total anchor."""
    layers = [_leaf("x", "Y", 1_000_000_000)]
    probe = _probe(layers)
    peak = 50 * 1024**3
    cap = 25 * 1024**3
    total = 32 * 1024**3

    report = render_vram_report(probe, peak, cap, total)

    assert "OVER-BUDGET (VRAM)" in report.verdict
    assert "50.0 GB" in report.verdict  # peak
    assert "25.0 GB" in report.verdict  # cap
    assert "32.0 GB" in report.verdict  # total
    assert "78% of" in report.verdict  # 25/32 = 78% rounded


def test_vram_per_layer_only_contains_leaves():
    """Non-leaf containers must be filtered — otherwise the Proposer sees
    double-counted bytes (container + children)."""
    layers = [
        _non_leaf("stage1", "Sequential", 5_000_000_000),
        _leaf("stage1.conv", "Conv1d", 2_500_000_000),
        _leaf("stage1.bn", "BatchNorm", 2_500_000_000),
    ]
    report = render_vram_report(_probe(layers), 5_000_000_000, 1 * 1024**3, 10 * 1024**3)
    names = [p.name for p in report.memory_killer.per_layer]
    assert names == ["stage1.conv", "stage1.bn"]
    assert report.memory_killer.dominant_layer in {"stage1.conv", "stage1.bn"}


def test_vram_dominant_fraction_is_rounded_to_four_decimals():
    layers = [_leaf("a", "A", 333_333_333)]
    probe = _probe(layers)
    peak = 1_000_000_000
    report = render_vram_report(probe, peak, 1 * 1024**3, 10 * 1024**3)
    # 333.../1_000_... = 0.3333... → 0.3333
    assert report.memory_killer.dominant_fraction == 0.3333


def test_vram_report_handles_empty_layers_gracefully():
    """Edge case: wrapper nn.Module with no submodules. Suggestion falls
    back to whole-model phrasing; no crash."""
    report = render_vram_report(_probe([]), 50 * 1024**3, 25 * 1024**3, 32 * 1024**3)
    assert report.memory_killer.binding_cap == "vram"
    assert report.memory_killer.dominant_layer is None
    assert report.memory_killer.per_layer == []
    assert (
        "whole model" in report.suggestion.lower() or "total parameter" in report.suggestion.lower()
    )


# ── Intensity renderer — config-level attribution (§3.10.2) ────────────────


def test_intensity_report_populates_config_fields_only():
    """The VRAM-attribution half must stay empty: intensity is a config
    problem, not an architecture problem."""
    report = render_intensity_report(batch_size=25, segmentation_size=40_000)
    d = report.memory_killer

    assert d.binding_cap == "compute_intensity"
    assert d.batch_size == 25
    assert d.segmentation_size == 40_000
    assert d.intensity_product == 1_000_000
    assert d.intensity_cap == _MAX_BATCH_TIMESTEPS

    # VRAM half untouched:
    assert d.dominant_layer is None
    assert d.dominant_layer_class is None
    assert d.dominant_layer_bytes is None
    assert d.dominant_fraction is None
    assert d.per_layer == []


def test_intensity_verdict_uses_distinct_label():
    """§3.10.2 requires the verdict to distinguish the two failure modes."""
    report = render_intensity_report(25, 40_000)
    assert "OVER-BUDGET (Compute-intensity)" in report.verdict
    # The VRAM label must NOT appear — they are disjoint modes:
    assert "OVER-BUDGET (VRAM)" not in report.verdict


def test_intensity_suggestion_names_config_levers_only():
    """§3.10.2: the suggestion string names `batch_size` / `segmentation_size`,
    never a layer — because intensity is a config-shape problem."""
    report = render_intensity_report(25, 40_000)
    sugg = report.suggestion.lower()
    assert "batch_size" in sugg
    assert "segmentation_size" in sugg
    assert "layer" not in sugg


def test_intensity_suggestion_has_no_architecture_family_terms():
    report = render_intensity_report(25, 40_000)
    sugg = report.suggestion.lower()
    for banned in [
        "wavenet",
        "punet",
        "fcnet",
        "transformer",
        "rnn",
        "attention",
        "conv",
        "unet",
        "lstm",
    ]:
        assert banned not in sugg, f"architecture term {banned!r} leaked into intensity suggestion"


# ── Combined renderer — both caps binding ──────────────────────────────────


def test_combined_report_populates_both_halves():
    """Rare but real: training config with huge params AND huge B×T.
    Both sets of fields must land in the same ``memory_killer`` dict."""
    layers = [_leaf("huge_op", "Any", 9_000_000_000)]
    probe = _probe(layers)
    report = render_combined_report(
        probe=probe,
        predicted_peak_bytes=10_000_000_000,
        cap_bytes=5 * 1024**3,
        total_memory_bytes=32 * 1024**3,
        batch_size=25,
        segmentation_size=40_000,
    )
    d = report.memory_killer

    assert d.binding_cap == "vram+compute_intensity"
    # VRAM half:
    assert d.dominant_layer == "huge_op"
    assert d.dominant_layer_bytes == 9_000_000_000
    assert len(d.per_layer) == 1
    # Intensity half:
    assert d.batch_size == 25
    assert d.segmentation_size == 40_000
    assert d.intensity_product == 1_000_000
    assert d.intensity_cap == _MAX_BATCH_TIMESTEPS


def test_combined_verdict_names_both_modes():
    layers = [_leaf("x", "Y", 1_000_000)]
    report = render_combined_report(
        _probe(layers),
        10 * 1024**3,
        5 * 1024**3,
        32 * 1024**3,
        batch_size=25,
        segmentation_size=40_000,
    )
    assert "VRAM" in report.verdict
    assert "Compute-intensity" in report.verdict


def test_combined_suggestion_concatenates_both_halves():
    """The Proposer must see both fixes — addressing only one will not clear
    the gate on the next attempt."""
    layers = [_leaf("my_layer", "Any", 9_000_000_000)]
    report = render_combined_report(
        _probe(layers),
        10_000_000_000,
        5 * 1024**3,
        32 * 1024**3,
        batch_size=25,
        segmentation_size=40_000,
    )
    sugg = report.suggestion
    # VRAM half — named layer + dimensional lever:
    assert "my_layer" in sugg
    assert "segmentation_size" in sugg
    # Intensity half — the explicit product and cap:
    assert "1,000,000" in sugg or "1000000" in sugg
    assert "800,000" in sugg or "800000" in sugg


# ── Schema contracts ───────────────────────────────────────────────────────


def test_memory_killer_details_is_frozen():
    d = MemoryKillerDetails(binding_cap="vram")
    with pytest.raises(ValidationError):  # frozen-model attr write
        d.binding_cap = "compute_intensity"


def test_killer_report_is_frozen():
    r = KillerReport(
        verdict="x",
        memory_killer=MemoryKillerDetails(binding_cap="vram"),
        suggestion="y",
    )
    with pytest.raises(ValidationError):  # frozen-model attr write
        r.verdict = "z"


def test_killer_report_model_dump_matches_wrapper_flatten_contract():
    """§3.7 says the wrapper flattens this into its own return dict. Pin the
    exact top-level keys so a schema rename here cannot silently break the
    wrapper contract."""
    layers = [_leaf("layer", "Any", 1_000_000)]
    report = render_vram_report(_probe(layers), 10_000_000_000, 5 * 1024**3, 32 * 1024**3)
    dumped = report.model_dump()
    assert set(dumped.keys()) == {"status", "verdict", "memory_killer", "suggestion"}
    assert dumped["status"] == "schema_violation"
    # memory_killer is a dict (§3.7 declares it dict | null):
    assert isinstance(dumped["memory_killer"], dict)
    assert set(dumped["memory_killer"].keys()) >= {
        "binding_cap",
        "dominant_layer",
        "dominant_layer_class",
        "dominant_layer_bytes",
        "dominant_fraction",
        "per_layer",
        "batch_size",
        "segmentation_size",
        "intensity_product",
        "intensity_cap",
    }


def test_per_layer_entry_field_names_are_the_contract():
    """Regression: the Proposer's prompt template will read these keys by
    name. Changing one is a breaking change that must be coordinated with
    the prompt template."""
    e = PerLayerEntry(name="l", class_name="c", output_shape=[1, 2], bytes=3)
    assert set(e.model_dump().keys()) == {"name", "class_name", "output_shape", "bytes"}


# ── Principle 2 module-source spot-check ──────────────────────────────────


def test_module_source_has_no_architecture_literals():
    """The full guardrail test (A.12) covers the whole tree; this one
    documents the invariant inline on killer_report.py so a future edit
    that sneaks in a model-family branch fails close to the edit."""
    source = Path(killer_report.__file__).read_text().lower()
    for banned in ["wavenet", "punet", "fcnet", "transformer", "rnn"]:
        assert f'"{banned}"' not in source, f"architecture literal {banned!r} found"
        assert f"'{banned}'" not in source, f"architecture literal {banned!r} found"
