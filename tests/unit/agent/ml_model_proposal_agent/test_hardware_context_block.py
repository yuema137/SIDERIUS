"""Unit tests for ``_render_hardware_context_block`` (WS-B §5.1 test 3).

Covers the three regimes of the [HARDWARE CONTEXT] prompt block renderer
plus the None / CPU-only fallback path. The renderer mirrors
``wrapper.py``'s [Hardware] log classifier; these tests pin the regime
selection logic so a future refactor cannot silently drift the prompt
signalling.

See docs/phase66_ws_b_proposer_hardening.md §3.1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest

from core.hardware_context import HardwareContext
from nodes.ml_model_proposal_agent import _render_hardware_context_block


def _make_ctx(
    total_memory_bytes: int = 32 * 1024**3,
    device_available: bool = True,
    device_name: str = "stub-cuda-device",
    hostname: str = "test-host",
) -> HardwareContext:
    return HardwareContext(
        device_name=device_name,
        total_memory_bytes=total_memory_bytes,
        compute_capability=(9, 0),
        multiprocessor_count=128,
        cuda_runtime_version="12.4",
        torch_version="2.5.1",
        hostname=hostname,
        device_available=device_available,
        discovered_at=datetime(2026, 4, 23, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Regime selection
# ---------------------------------------------------------------------------


class TestBudgetRegime:
    """Operator budget is below the 80% physical floor -> BUDGET regime.

    32 GB * 0.80 = 25.6 GB usable cap. A 20 GB budget is below the cap,
    so the operator's budget is the binding ceiling.
    """

    def test_selects_budget_regime_when_budget_below_usable_cap(self):
        ctx = _make_ctx()
        block = _render_hardware_context_block(ctx, vram_budget_gb=20.0)
        assert "Regime:            BUDGET" in block
        assert "operator's budget is the binding ceiling" in block

    def test_budget_regime_reports_operator_budget_as_effective_cap(self):
        ctx = _make_ctx()
        block = _render_hardware_context_block(ctx, vram_budget_gb=20.0)
        assert "Operator budget:   20.00 GB" in block
        assert "Effective cap:     20.00 GB" in block

    def test_budget_regime_still_shows_physical_facts(self):
        ctx = _make_ctx()
        block = _render_hardware_context_block(ctx, vram_budget_gb=20.0)
        assert "Total VRAM:        32.00 GB" in block
        assert "Usable cap (80%):  25.60 GB" in block
        assert "Device:            stub-cuda-device" in block
        assert "Host:              test-host" in block

    def test_budget_equal_to_usable_cap_still_budget_regime(self):
        """Boundary: budget == usable_cap takes the <= branch -> BUDGET.

        Pass ctx.usable_cap_gb verbatim — the runtime value is
        int(0.80 * total_memory_bytes) / 1024**3 and differs from the
        literal 25.6 by a float epsilon, which would otherwise flip the
        comparison to PHYSICAL VETO.
        """
        ctx = _make_ctx()
        block = _render_hardware_context_block(ctx, vram_budget_gb=ctx.usable_cap_gb)
        assert "Regime:            BUDGET" in block
        assert "PHYSICAL VETO" not in block


class TestPhysicalRegime:
    """No operator budget set -> PHYSICAL regime (cap = usable_cap_gb)."""

    def test_selects_physical_regime_when_budget_is_none(self):
        ctx = _make_ctx()
        block = _render_hardware_context_block(ctx, vram_budget_gb=None)
        assert "Regime:            PHYSICAL" in block
        assert "no operator budget set" in block

    def test_physical_regime_cap_reported_in_regime_line(self):
        ctx = _make_ctx()
        block = _render_hardware_context_block(ctx, vram_budget_gb=None)
        # Regime line embeds effective cap = usable_cap = 25.60 GB
        assert "cap = 25.60 GB" in block

    def test_physical_regime_suppresses_operator_budget_lines(self):
        """When no budget is set, the Operator/Effective lines are omitted
        (the PHYSICAL cap is already reported in the Regime line)."""
        ctx = _make_ctx()
        block = _render_hardware_context_block(ctx, vram_budget_gb=None)
        assert "Operator budget" not in block
        assert "Effective cap" not in block


class TestPhysicalVetoRegime:
    """Operator budget > 80% physical safety floor -> PHYSICAL VETO.

    Smaller GPU: 8 GB total -> 6.4 GB usable cap. A 20 GB budget is
    above the cap, so the physical cap wins and the operator's ceiling
    is ignored.
    """

    def test_selects_physical_veto_when_budget_exceeds_usable_cap(self):
        ctx = _make_ctx(total_memory_bytes=8 * 1024**3)
        block = _render_hardware_context_block(ctx, vram_budget_gb=20.0)
        assert "Regime:            PHYSICAL VETO" in block
        assert "operator budget exceeds the 80%" in block
        assert "physical cap wins" in block

    def test_physical_veto_effective_cap_is_usable_cap_not_budget(self):
        ctx = _make_ctx(total_memory_bytes=8 * 1024**3)
        block = _render_hardware_context_block(ctx, vram_budget_gb=20.0)
        # usable_cap = 0.80 * 8 = 6.40 GB -> effective_cap shows this, not 20.
        assert "Effective cap:     6.40 GB" in block
        assert "Operator budget:   20.00 GB" in block  # still surfaced


# ---------------------------------------------------------------------------
# None / CPU-only fallback
# ---------------------------------------------------------------------------


class TestNoneFallback:
    """ctx=None or device_available=False -> empty string (no block injected)."""

    def test_none_ctx_returns_empty_string(self):
        assert _render_hardware_context_block(None, vram_budget_gb=20.0) == ""

    def test_none_ctx_and_none_budget_returns_empty_string(self):
        assert _render_hardware_context_block(None, vram_budget_gb=None) == ""

    def test_device_unavailable_returns_empty_string(self):
        """CPU-only hosts (discover() stub with device_available=False)
        must produce no block even when a budget was explicitly set."""
        ctx = _make_ctx(
            total_memory_bytes=0,
            device_available=False,
            device_name="cpu",
        )
        assert _render_hardware_context_block(ctx, vram_budget_gb=20.0) == ""

    def test_device_unavailable_returns_empty_string_when_budget_none(self):
        ctx = _make_ctx(
            total_memory_bytes=0,
            device_available=False,
            device_name="cpu",
        )
        assert _render_hardware_context_block(ctx, vram_budget_gb=None) == ""


# ---------------------------------------------------------------------------
# Trailing instruction text (present in all three regimes)
# ---------------------------------------------------------------------------


class TestInstructionText:
    """The renderer appends one instruction paragraph telling the Proposer
    to size the baseline under the effective cap — this must travel with
    every rendered block, regardless of regime."""

    @pytest.mark.parametrize(
        "budget_gb, total_bytes",
        [
            (20.0, 32 * 1024**3),  # BUDGET
            (None, 32 * 1024**3),  # PHYSICAL
            (20.0, 8 * 1024**3),  # PHYSICAL VETO
        ],
    )
    def test_instruction_text_appended_in_every_regime(self, budget_gb, total_bytes):
        ctx = _make_ctx(total_memory_bytes=total_bytes)
        block = _render_hardware_context_block(ctx, vram_budget_gb=budget_gb)
        assert "must fit within the **effective cap**" in block
        assert "VRAM engine will reject" in block
