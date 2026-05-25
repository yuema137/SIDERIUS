"""Unit tests for the physical-rejection aggregation + render helpers
(WS-B §5.1 test 1).

Covers:

- ``_aggregate_worst_offender_rejections`` — groups rejections by
  ``attempt_config["model_type"]`` and picks the worst offender per
  group (ratio = estimated_gb / budget_gb, tie-breaker =
  dominant_fraction). Empty input is a no-op.

- ``_render_physical_rejection`` — renders one aggregated ``[PHYSICAL
  REJECTION]`` block. Suppresses the Dominant-layer line when
  ``dominant_layer=""`` (the compute-intensity path has no single
  blame-bearing layer).

See docs/phase66_ws_b_proposer_hardening.md §3.2 / §4.3.
"""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import PhysicalRejection
from workflows.model_exploration import (
    _aggregate_worst_offender_rejections,
    _render_physical_rejection,
)


def _mk(
    model_type: str,
    estimated_gb: float,
    budget_gb: float = 20.0,
    dominant_fraction: float = 0.30,
    dominant_layer: str = "encoder.block.conv",
    dominant_layer_gb: float = 6.0,
    binding_cap: str = "vram",
    suggestion: str = "reduce depth or batch_size.",
    batch_size: int = 16,
    depth: int = 7,
) -> PhysicalRejection:
    return PhysicalRejection(
        attempt_config={
            "model_type": model_type,
            "batch_size": batch_size,
            "segmentation_size": 16384,
            "depth": depth,
        },
        binding_cap=binding_cap,
        dominant_layer=dominant_layer,
        dominant_layer_gb=dominant_layer_gb,
        dominant_fraction=dominant_fraction,
        budget_gb=budget_gb,
        estimated_gb=estimated_gb,
        suggestion=suggestion,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregateWorstOffender:
    def test_empty_input_is_noop(self):
        assert _aggregate_worst_offender_rejections([]) == []

    def test_single_rejection_returns_one_group(self):
        r = _mk("deep_punet", estimated_gb=22.0)
        out = _aggregate_worst_offender_rejections([r])
        assert len(out) == 1
        worst, count = out[0]
        assert worst is r
        assert count == 1

    def test_picks_worst_by_ratio_within_group(self):
        """Two attempts for deep_punet; the higher estimated/budget ratio
        must win."""
        mild = _mk("deep_punet", estimated_gb=22.0)  # ratio 1.10
        worse = _mk("deep_punet", estimated_gb=29.0)  # ratio 1.45
        out = _aggregate_worst_offender_rejections([mild, worse])
        assert len(out) == 1
        worst, count = out[0]
        assert worst is worse, (
            "Aggregator must pick the higher ratio (29.0/20.0) as worst, "
            "not the milder (22.0/20.0) one."
        )
        assert count == 2

    def test_groups_by_model_type(self):
        """Two architectures, two groups — one worst per group."""
        a1 = _mk("deep_punet", estimated_gb=22.0)
        a2 = _mk("deep_punet", estimated_gb=29.0)
        b1 = _mk("wide_transformer", estimated_gb=24.0)
        out = _aggregate_worst_offender_rejections([a1, a2, b1])
        # Two groups
        assert len(out) == 2
        by_mt = {w.attempt_config["model_type"]: (w, c) for w, c in out}
        assert set(by_mt.keys()) == {"deep_punet", "wide_transformer"}
        # deep_punet group: worst is a2 (ratio 1.45 > 1.10), n=2
        assert by_mt["deep_punet"][0] is a2
        assert by_mt["deep_punet"][1] == 2
        # wide_transformer group: only b1, n=1
        assert by_mt["wide_transformer"][0] is b1
        assert by_mt["wide_transformer"][1] == 1

    def test_ties_broken_by_dominant_fraction(self):
        """Equal ratio -> tie-break by higher dominant_fraction."""
        a = _mk("deep_punet", estimated_gb=24.0, dominant_fraction=0.30)
        b = _mk("deep_punet", estimated_gb=24.0, dominant_fraction=0.50)
        out = _aggregate_worst_offender_rejections([a, b])
        assert len(out) == 1
        worst, _ = out[0]
        assert worst is b

    def test_zero_budget_treated_as_infinite_ratio(self):
        """budget_gb == 0 -> ratio = +inf (degenerate but must not crash
        or get dropped)."""
        degenerate = _mk("deep_punet", estimated_gb=5.0, budget_gb=0.0)
        sane = _mk("deep_punet", estimated_gb=29.0, budget_gb=20.0)
        out = _aggregate_worst_offender_rejections([sane, degenerate])
        assert len(out) == 1
        worst, count = out[0]
        assert worst is degenerate, (
            "budget_gb=0 must surface as +inf ratio and beat any finite one."
        )
        assert count == 2

    def test_missing_model_type_treated_as_unknown_group(self):
        """attempt_config without 'model_type' key groups under 'unknown'."""
        r = PhysicalRejection(
            attempt_config={"batch_size": 4},  # no model_type
            binding_cap="vram",
            dominant_layer="x",
            dominant_layer_gb=1.0,
            dominant_fraction=0.5,
            budget_gb=10.0,
            estimated_gb=12.0,
            suggestion="s",
        )
        out = _aggregate_worst_offender_rejections([r])
        assert len(out) == 1


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class TestRenderPhysicalRejection:
    def test_tag_and_model_type_in_header(self):
        r = _mk("deep_punet", estimated_gb=29.0)
        out = _render_physical_rejection(r, n_rejections=2)
        assert out.startswith("[PHYSICAL REJECTION] deep_punet:")

    def test_pluralization_with_multiple_rejections(self):
        r = _mk("deep_punet", estimated_gb=29.0)
        out = _render_physical_rejection(r, n_rejections=3)
        assert "rejected 3 attempts by the VRAM gate" in out

    def test_singular_phrasing_with_one_rejection(self):
        r = _mk("deep_punet", estimated_gb=29.0)
        out = _render_physical_rejection(r, n_rejections=1)
        assert "rejected 1 attempt by the VRAM gate" in out
        # Not "1 attempts"
        assert "1 attempts" not in out

    def test_reports_overshoot_and_budget(self):
        r = _mk("deep_punet", estimated_gb=29.1, budget_gb=20.0)
        out = _render_physical_rejection(r, n_rejections=1)
        assert "estimated 29.10 GB" in out
        assert "budget 20.00 GB" in out
        assert "binding cap: vram" in out

    def test_dominant_layer_line_present_when_named(self):
        r = _mk(
            "deep_punet",
            estimated_gb=29.1,
            dominant_layer="encoder.attention.block7.mha",
            dominant_layer_gb=13.4,
            dominant_fraction=0.46,
        )
        out = _render_physical_rejection(r, n_rejections=1)
        assert "Dominant layer: encoder.attention.block7.mha" in out
        assert "13.40 GB" in out
        assert "46% of peak" in out

    def test_dominant_layer_line_suppressed_when_empty(self):
        """compute_intensity path: dominant_layer='' means there is no
        single blame-bearing layer. The renderer must omit the Dominant
        layer: ... line entirely (not render '(0% of peak)')."""
        r = _mk(
            "wide_transformer",
            estimated_gb=18.3,
            binding_cap="compute_intensity",
            dominant_layer="",
            dominant_layer_gb=0.0,
            dominant_fraction=0.0,
            suggestion="Compute intensity exceeds device arithmetic budget.",
        )
        out = _render_physical_rejection(r, n_rejections=1)
        assert "Dominant layer" not in out, (
            f"Empty dominant_layer must suppress the line. Got:\n{out}"
        )
        assert "0% of peak" not in out
        # Other lines still rendered
        assert "[PHYSICAL REJECTION] wide_transformer" in out
        assert "binding cap: compute_intensity" in out

    def test_attempted_config_and_suggestion_rendered(self):
        r = _mk(
            "deep_punet",
            estimated_gb=29.1,
            batch_size=16,
            depth=7,
            suggestion="Drop hidden_dim to 512.",
        )
        out = _render_physical_rejection(r, n_rejections=1)
        assert "Attempted config:" in out
        assert "'model_type': 'deep_punet'" in out
        assert "'batch_size': 16" in out
        assert "Suggestion: Drop hidden_dim to 512." in out

    def test_empty_suggestion_is_suppressed(self):
        r = _mk("deep_punet", estimated_gb=29.1, suggestion="")
        out = _render_physical_rejection(r, n_rejections=1)
        assert "Suggestion:" not in out
