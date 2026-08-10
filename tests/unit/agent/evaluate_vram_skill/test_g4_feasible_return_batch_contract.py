"""V21 PR G G4 — the agent-path fallback is unreachable by CONTRACT.

`core/sandbox_executor.py::execute_inference` still carries the
`inference_batch_for` fallback for `inference_batch is None` — kept
INTENTIONALLY for no-hint callers (`run_comparison.py` baselines,
legacy validation scripts). On the agent path it must be unreachable:
every route by which an agent attempt reaches `execute_inference`
passes through a feasible (or CPU-mode) `evaluate_vram_skill` return
whose `inference_batch` the tuner captures into `active_params`
(:4696) — the value that then feeds the time-gate forecast (G2), the
measurement identity (G3) and runtime inference alike.

This module pins that contract by EXECUTING the two return families
audited in PR G §0.R.6 as capable of reaching agent inference
(`status == "success"` and `feasible is True`) and asserting each
return carries `inference_batch: int >= 1`:

  * the CPU-only short-circuit (`device_available=False`, wrapper :571)
    — hint present by construction (`inference_batch: 1`);
  * the feasible probe path (wrapper :701) — the probe-derived batch.

Every other return family (`schema_violation`, infeasible
`feasible=False`, `timeout`, `cuda_oom`/`host_memory`, `inconclusive`,
`error`) never reaches inference (skip-record + continue, retry, or
raise — §0.R.6), so the contract quantifies over exactly the
success+feasible shapes. A future feasible return path that omits the
batch fails these tests before it can silently re-activate the
executor fallback on the agent path. This is what formally replaces
the never-completed A.9 "remove the fallback" migration (Q-G-4).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent.skills.evaluate_vram_skill import wrapper as vram_wrapper
from core.hardware_context import HardwareContext


class FakeSandbox:
    """run_skill ignores the sandbox argument."""


def _ctx(**overrides) -> HardwareContext:
    defaults: dict = dict(
        device_name="G4-TEST-DEVICE",
        total_memory_bytes=32 * 1024**3,
        compute_capability=(12, 0),
        multiprocessor_count=170,
        cuda_runtime_version="12.8",
        torch_version="2.10.0+cu128",
        hostname="g4-test-host",
        device_available=True,
        discovered_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    defaults.update(overrides)
    return HardwareContext(**defaults)


def _base_kwargs(**overrides) -> dict:
    kw = {
        "model_type": "rnn",
        "model_config": {"segmentation_size": 1000},
        "train_config": {"batch_size": 1, "epochs": 1},
        "loss_config": {"loss_type": "ce"},
    }
    kw.update(overrides)
    return kw


def _assert_carries_the_batch(result: dict) -> None:
    """The G4 contract for one agent-inference-capable return."""
    assert result["status"] == "success"
    assert result["feasible"] is True
    batch = result["inference_batch"]
    assert isinstance(batch, int) and not isinstance(batch, bool), batch
    assert batch >= 1, batch


class TestFeasibleReturnsCarryTheBatch:
    def test_cpu_mode_return_carries_batch_1(self):
        """Wrapper :571 — the CPU short-circuit is agent-inference-capable
        and must state its batch (1) rather than leave the executor to
        fall back."""
        result = vram_wrapper.run_skill(
            FakeSandbox(),
            **_base_kwargs(hardware_context=_ctx(device_available=False)),
        )
        _assert_carries_the_batch(result)
        assert result["inference_batch"] == 1

    def test_feasible_probe_return_carries_the_probed_batch(self):
        """Wrapper :701 — the feasible probe path. A tiny rnn at seg 1000
        under a 32 GiB cap probes feasible on CPU in seconds; the probed
        batch must be a positive int (whatever the resolver picked)."""
        result = vram_wrapper.run_skill(
            FakeSandbox(),
            **_base_kwargs(hardware_context=_ctx(device_available=True)),
        )
        _assert_carries_the_batch(result)
