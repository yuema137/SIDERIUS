"""Mandatory offline effect boundary for the two composed tuner witnesses.

These supplied outcomes exercise orchestration, not resource measurement. The
real admission and probe-data projection still run; no worker or provider may.
"""

from __future__ import annotations

import importlib
import subprocess
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import pytest

from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeResult, PreflightOutcome
from agent.skills.evaluate_vram_skill.preflight_adapter import adapt_result
from core.hardware_context import HardwareContext, write_manifest
from execute_tools.task_data_path import TaskProbeDataSpec
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.recording_sandbox import RecordingSandbox


class ComposedTunerEffectEscape(BaseException):
    """Stop before effects, outside the tuner's generic Exception handlers.

    Same rationale as tests/unit/conftest.py's RealSubprocessEscape: a failed
    return envelope is too late and may silently become a retryable record.
    """


def _refuse_effect(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise ComposedTunerEffectEscape(
        "Composed tuner pseudo fixture reached a real provider, sandbox, or "
        "worker/process boundary. Fix the current leaf double before running."
    )


@dataclass
class ComposedTunerEffects:
    """Observed leaf inputs; callers may inspect the actual probe transport."""

    preflight_calls: list[dict[str, Any]] = field(default_factory=list)
    hardware_calls: list[tuple[Path, str]] = field(default_factory=list)


def _install_effect_backstop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse effect owners and ALL process spawns, including renamed workers."""
    # Keep Popen a class, as the unit guard does. A function replacement breaks
    # legitimate subclass/type consumers before it can guard the launch.
    original_popen = subprocess.Popen

    class RefusingPopen(original_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            _refuse_effect()

    monkeypatch.setattr(subprocess, "Popen", RefusingPopen)
    monkeypatch.setattr(subprocess, "run", _refuse_effect)
    # Patch the imported owner AND adapter binding: either route must stop
    # before the worker can write its spec or start a process.
    for module_name, attribute in (
        ("agent.skills.evaluate_vram_skill.isolated_probe", "run_isolated_preflight"),
        ("agent.skills.evaluate_vram_skill.preflight_adapter", "run_isolated_preflight"),
        ("core.runtime_control.gpu_measurement_runner", "run_prephase_measurement"),
        ("core.runtime_control.probe_subprocess", "spawn_worker"),
        ("core.hardware_context", "discover"),
    ):
        monkeypatch.setattr(importlib.import_module(module_name), attribute, _refuse_effect)

    from agent.llm_bridge import LLMBridge
    from core.sandbox_executor import TidmadSandbox

    monkeypatch.setattr(LLMBridge, "__init__", _refuse_effect)
    monkeypatch.setattr(TidmadSandbox, "__init__", _refuse_effect)


@contextmanager
def composed_tuner_effects(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sandbox: RecordingSandbox,
    bridge: RecordingLLMBridge,
    expected_attempts: int,
    hardware_context: HardwareContext | None = None,
    preflight_results: Sequence[tuple[PreflightOutcome, float]] | None = None,
) -> Iterator[ComposedTunerEffects]:
    """Install before composition/run; verify finite consumption on normal exit.

    The explicit CPU record is not a physical observation. Its absent GPU UUID
    leaves the REAL prephase applicability decision in force. The isolated
    preflight result is supplied at execution's actual call site because the
    real worker adapter requires a positive GPU hardware snapshot even on CPU.
    All patches are restored when this context exits, including on failure.
    """
    if type(sandbox) is not RecordingSandbox or type(bridge) is not RecordingLLMBridge:
        raise TypeError("Composed tuner witnesses require the recording sandbox and bridge")
    if expected_attempts < 1:
        raise ValueError("expected_attempts must describe a nonempty finite witness")
    result_specs = (
        [("COMPLETED_MEASUREMENT", 0.0) for _ in range(expected_attempts)]
        if preflight_results is None
        else preflight_results
    )
    if len(result_specs) != expected_attempts:
        raise ValueError("preflight_results must contain one result per expected attempt")

    effects = ComposedTunerEffects()
    hardware = hardware_context or HardwareContext(
        device_name="cpu",
        total_memory_bytes=0,
        compute_capability=(0, 0),
        multiprocessor_count=0,
        cuda_runtime_version=None,
        torch_version="fixture-not-discovered",
        hostname="composed-tuner-fixture",
        device_available=False,
        discovered_at=datetime(2000, 1, 1, tzinfo=UTC),
        cuda_visible_devices="",
        visible_device_count=0,
        devices=[],
        active_device_uuid=None,
        collection_errors=["test fixture: hardware discovery deliberately not executed"],
    )
    responses = deque(
        IsolatedProbeResult(
            label=f"supplied-fixture-{index}",
            outcome=outcome,
            detail="Supplied pseudo preflight outcome; no measurement executed",
            verdict="Supplied orchestration-only outcome",
            device="cuda" if hardware.device_available else "cpu",
            estimated_gb=estimated_gb,
            inference_batch=1,
        )
        for index, (outcome, estimated_gb) in enumerate(result_specs)
    )

    def supplied_hardware(workspace: Path, run_name: str) -> HardwareContext:
        if effects.hardware_calls:
            raise ComposedTunerEffectEscape("Unexpected repeated hardware acquisition")
        effects.hardware_calls.append((Path(workspace), run_name))
        write_manifest(hardware, Path(workspace) / f"{run_name}_hardware.json")
        return hardware

    def supplied_preflight(**kwargs: Any) -> dict[str, Any]:
        if not responses:
            raise ComposedTunerEffectEscape("Supplied preflight queue exhausted")
        if kwargs.get("hardware_context") is not hardware:
            raise ComposedTunerEffectEscape("Preflight bypassed the explicit CPU hardware record")
        if not isinstance(kwargs.get("task_probe_data"), TaskProbeDataSpec):
            raise ComposedTunerEffectEscape(
                "Composed preflight lost its real task probe projection"
            )
        effects.preflight_calls.append(dict(kwargs))
        payload = responses.popleft().model_dump()
        payload["limit_gb"] = kwargs.get("vram_budget_gb") or hardware.usable_cap_gb
        return adapt_result(payload)

    with monkeypatch.context() as scoped:
        _install_effect_backstop(scoped)
        tuner = importlib.import_module(
            "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
        )
        execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")
        scoped.setattr(tuner, "get_or_create", supplied_hardware)
        scoped.setattr(execution, "run_production_preflight", supplied_preflight)
        yield effects
        assert len(effects.hardware_calls) == 1, "Hardware double was bypassed"
        assert not responses, "Preflight double did not observe every expected attempt"
