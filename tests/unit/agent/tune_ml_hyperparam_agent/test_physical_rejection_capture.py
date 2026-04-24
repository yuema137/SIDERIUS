"""Unit tests for the tuner-side ``PhysicalRejection`` capture
(WS-B §5.1 test 2 — Hop 2 of the 5-hop wire).

Stubs ``_run_skill("evaluate_vram_skill", …)`` to return ``feasible=False``
with a known ``memory_killer`` payload, drives one or more tuner rounds,
then asserts ``HyperparamTuningOutput.physical_rejections`` carries the
expected entries.

The harness mirrors ``test_per_round_attempt_budget.py`` — patch ``LLMBridge``,
``TidmadSandbox``, ``_run_skill``, and ``load_reference_scores`` so the
run is hermetic (no GPU, no API, no HDF5).

See docs/phase66_ws_b_proposer_hardening.md §5.1 item 2 / §3.2.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    PhysicalRejection,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from core.hardware_context import HardwareContext
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.scoring_reference import ReferenceScores


def _stub_hardware_context() -> HardwareContext:
    """Plain stub so the tuner's ``get_or_create`` patch does not have
    to probe real ``torch.cuda`` or write a manifest to disk. Each test
    uses a fresh ``tmp_path`` so sharing a stub across tests is safe."""
    return HardwareContext(
        device_name="stub-cuda-device",
        total_memory_bytes=32 * 1024 ** 3,
        compute_capability=(9, 0),
        multiprocessor_count=128,
        cuda_runtime_version="12.4",
        torch_version="2.5.1",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Reference-score stub — lets the tuner's pre-loop load call succeed without
# any on-disk JSONs.
# ---------------------------------------------------------------------------

def _synth_reference_stub() -> ReferenceScores:
    return ReferenceScores(
        raw_per_file_log=[-2.7] * 20,
        gt_per_file_log=[7.0] * 20,
        raw_per_file_linear_sum=[2.0] * 20,
        raw_per_file_n_segments=[200] * 20,
        gt_per_file_linear_sum=[2000.0] * 20,
        gt_per_file_n_segments=[200] * 20,
        raw_scalar_full=-2.7,
        gt_scalar_full=7.0,
        s_max=295_715_680.14,
    )


# ---------------------------------------------------------------------------
# Canned LLM + skill payloads
# ---------------------------------------------------------------------------

FAKE_PLAN = {
    "model_type": "punet",
    "hypothesis": "h",
    "reasoning": "r",
    "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
    "train_config": {"epochs": 5, "lr": 1e-4},
    "loss_config": {"loss_type": "ce"},
}

FAKE_REFLECT = {
    "conclusion": "c",
    "key_factor": "k",
    "discovery": "d",
    "memory_update": "m",
}

FAKE_CONFIG_MANUAL = {
    "status": "success",
    "data": {"punet": {"fields": ["depth", "segmentation_size"]}},
}

FAKE_VRAM_OK = {
    "status": "success",
    "feasible": True,
    "estimated_gb": 2.5,
    "limit_gb": 6.0,
    "vram_budget_gb": 8.0,
    "verdict": "FITS",
    "suggestion": "",
}


def _make_oom_payload(
    *,
    dominant_layer: str = "encoder.block3.conv",
    dominant_layer_bytes: int = 5 * 1024 ** 3,     # 5.0 GB
    dominant_fraction: float = 0.42,
    binding_cap: str = "vram",
    estimated_gb: float = 12.0,
    limit_gb: float = 8.0,
    suggestion: str = "Reduce batch_size.",
    include_memory_killer: bool = True,
) -> dict:
    """Build one ``feasible=False`` resource_check payload.

    The ``memory_killer`` sub-dict is what the capture logic reads for
    ``binding_cap`` / ``dominant_layer`` / ``dominant_layer_bytes`` /
    ``dominant_fraction``. ``include_memory_killer=False`` exercises the
    "no killer sub-dict" degenerate path (the capture should still emit
    a rejection with defaulted fields, not crash).
    """
    payload = {
        "status": "success",
        "feasible": False,
        "estimated_gb": estimated_gb,
        "limit_gb": limit_gb,
        "verdict": f"Estimated {estimated_gb} GB exceeds {limit_gb} GB limit.",
        "suggestion": suggestion,
    }
    if include_memory_killer:
        payload["memory_killer"] = {
            "binding_cap":          binding_cap,
            "dominant_layer":       dominant_layer,
            "dominant_layer_bytes": dominant_layer_bytes,
            "dominant_fraction":    dominant_fraction,
        }
    return payload


FAKE_TRAIN = {
    "status": "success",
    "results": {"final_loss": 0.5, "model_params": 100000},
}
FAKE_INFER = {"status": "success", "results": {}}
FAKE_SCORE = {"status": "success", "results": {"denoising_score": 1.75}}


# ---------------------------------------------------------------------------
# Agent wiring
# ---------------------------------------------------------------------------

def _make_input(
    tmp_path,
    *,
    max_rounds: int = 1,
    attempts_per_round: int = 1,
    attempts_per_formal_round: int = 1,
    max_fail_rounds: int = 1,
) -> HyperparamTuningInput:
    """Build a tuner input for a rejection-capture scenario.

    ``max_fail_rounds`` defaults to 1 so that the outer loop aborts the
    instant the first failed round lands. This is important for the
    OOM-only tests: if the outer loop kept running after the single
    rejection, the scripted ``_run_skill`` would raise ``IndexError`` on
    the next call, which the tuner's generic ``except Exception`` block
    catches with a 5s ``time.sleep`` cool-down — multiplying a 0.1-second
    test into a 45-second one. Each test that expects N rejections sets
    ``max_fail_rounds=N`` explicitly.
    """
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        attempts_per_round=attempts_per_round,
        attempts_per_formal_round=attempts_per_formal_round,
        max_fail_rounds=max_fail_rounds,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="rej_cap_test"),
        ),
        progress_bar=False,
    )


def _make_scripted_skill(vram_verdicts: list[dict]):
    counter = {"i": 0}

    def side_effect(skill_folder, sandbox, **params):
        if skill_folder == "check_config_format_skill":
            return FAKE_CONFIG_MANUAL
        if skill_folder == "evaluate_vram_skill":
            i = counter["i"]
            counter["i"] = i + 1
            if i >= len(vram_verdicts):
                raise IndexError(
                    f"vram_verdicts exhausted at attempt {i + 1}; "
                    f"schedule length={len(vram_verdicts)}"
                )
            return vram_verdicts[i]
        if skill_folder == "training_skill":
            return FAKE_TRAIN
        if skill_folder == "inference_skill":
            return FAKE_INFER
        if skill_folder == "denoising_score_skill":
            return FAKE_SCORE
        return {"status": "error", "message": f"unknown skill {skill_folder}"}

    return side_effect, counter


@pytest.fixture
def agent_with_scripted_skill():
    def make(vram_verdicts):
        side_effect, counter = _make_scripted_skill(vram_verdicts)
        cm = (
            patch("nodes.ml_hyperparameter_tune_agent.LLMBridge"),
            patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox"),
            patch("nodes.ml_hyperparameter_tune_agent._run_skill",
                  side_effect=side_effect),
            patch("nodes.ml_hyperparameter_tune_agent.load_reference_scores",
                  return_value=_synth_reference_stub()),
            # Skip the real CUDA probe + manifest I/O — it takes ~30s
            # per call and is irrelevant to the capture contract we pin
            # here. See test_hardware_context_init.py for the A.1.6
            # wiring test that does exercise the real path.
            patch("nodes.ml_hyperparameter_tune_agent.get_or_create",
                  return_value=_stub_hardware_context()),
            tempfile.TemporaryDirectory(),
        )
        return cm, counter

    yield make


def _setup(make_factory, vram_verdicts):
    (bridge_cm, sandbox_cm, skill_cm, ref_cm, hw_cm, configs_cm), counter = (
        make_factory(vram_verdicts)
    )
    MockBridge = bridge_cm.__enter__()
    MockSandbox = sandbox_cm.__enter__()
    skill_cm.__enter__()
    ref_cm.__enter__()
    hw_cm.__enter__()
    configs_dir = configs_cm.__enter__()

    mock_brain = MockBridge.return_value
    mock_brain.plan.return_value = FAKE_PLAN
    mock_brain.reflect.return_value = FAKE_REFLECT

    saved = []
    mock_sandbox = MockSandbox.return_value
    mock_sandbox.get_summary.side_effect = lambda: list(saved)
    mock_sandbox.save_record.side_effect = lambda r: saved.append(r)
    mock_sandbox.dirs = {"configs": configs_dir}

    def cleanup():
        configs_cm.__exit__(None, None, None)
        hw_cm.__exit__(None, None, None)
        ref_cm.__exit__(None, None, None)
        skill_cm.__exit__(None, None, None)
        sandbox_cm.__exit__(None, None, None)
        bridge_cm.__exit__(None, None, None)

    return HyperparamTuningAgent(), saved, counter, cleanup


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSingleRejectionCapture:
    """Single VRAM-infeasible attempt → exactly one PhysicalRejection with
    the contract-specified fields (dominant_layer, binding_cap, suggestion)
    populated from the memory_killer payload."""

    def test_one_rejection_with_expected_killer_fields(
        self, agent_with_scripted_skill, tmp_path,
    ):
        oom = _make_oom_payload(
            dominant_layer="encoder.attention.block7.mha",
            dominant_layer_bytes=int(13.4 * 1024 ** 3),
            dominant_fraction=0.46,
            binding_cap="vram",
            estimated_gb=29.1,
            limit_gb=20.0,
            suggestion="Attention head stack is infeasible; drop hidden_dim.",
        )
        # 1 trial round, 1 attempt — the single attempt is a rejection.
        # Output will be status="partial" (no successful round) but we only
        # care about the rejection buffer being populated.
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [oom])
        try:
            output = agent.run(_make_input(tmp_path, max_rounds=1))
        finally:
            cleanup()

        assert len(output.physical_rejections) == 1, (
            f"expected 1 rejection, got {len(output.physical_rejections)}. "
            f"Saved records: {[r.get('status') for r in saved]}"
        )
        rej = output.physical_rejections[0]
        assert isinstance(rej, PhysicalRejection)
        assert rej.dominant_layer == "encoder.attention.block7.mha"
        assert rej.binding_cap == "vram"
        assert rej.suggestion == "Attention head stack is infeasible; drop hidden_dim."
        assert rej.budget_gb == 20.0
        assert rej.estimated_gb == 29.1
        assert rej.dominant_fraction == 0.46
        # bytes → GB conversion (rounded to 4 decimal places in the capture)
        assert abs(rej.dominant_layer_gb - 13.4) < 1e-3

    def test_attempt_config_carries_model_type(
        self, agent_with_scripted_skill, tmp_path,
    ):
        """The attempt_config snapshot must at minimum carry the model_type
        — the orchestrator groups rejections by model_type for worst-offender
        aggregation."""
        oom = _make_oom_payload()
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [oom])
        try:
            output = agent.run(_make_input(tmp_path, max_rounds=1))
        finally:
            cleanup()

        assert len(output.physical_rejections) == 1
        rej = output.physical_rejections[0]
        assert rej.attempt_config.get("model_type") == "punet"


class TestMultipleRejectionCapture:
    """Three OOM attempts in a row → three PhysicalRejections, in
    encounter order, each with its own dominant_layer / suggestion."""

    def test_three_rejections_preserved_in_order(
        self, agent_with_scripted_skill, tmp_path,
    ):
        verdicts = [
            _make_oom_payload(dominant_layer="layer_A", suggestion="s_A"),
            _make_oom_payload(dominant_layer="layer_B", suggestion="s_B"),
            _make_oom_payload(dominant_layer="layer_C", suggestion="s_C"),
        ]
        # 3 rounds * 1 attempt each; each round's single attempt is
        # rejected. ``max_fail_rounds=3`` ensures the loop aborts right
        # after the third fail rather than spinning on exhausted-schedule
        # IndexErrors (which the tuner's generic except swallows with a
        # 5s sleep).
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, verdicts)
        try:
            output = agent.run(_make_input(
                tmp_path,
                max_rounds=3,
                attempts_per_round=1,
                attempts_per_formal_round=1,
                max_fail_rounds=3,
            ))
        finally:
            cleanup()

        assert len(output.physical_rejections) == 3
        assert [r.dominant_layer for r in output.physical_rejections] == [
            "layer_A", "layer_B", "layer_C",
        ]
        assert [r.suggestion for r in output.physical_rejections] == [
            "s_A", "s_B", "s_C",
        ]


class TestDegenerateKillerPayload:
    """When ``memory_killer`` is absent, the capture must still emit a
    well-formed rejection using the documented defaults (empty string for
    dominant_layer, 0.0 for the two numeric fields, ``"vram"`` for
    binding_cap). This mirrors the compute_intensity path that produces
    no single blame-bearing layer — the renderer suppresses the Dominant-
    layer line, but the rejection itself must still exist so the
    aggregator sees it."""

    def test_missing_memory_killer_defaults_applied(
        self, agent_with_scripted_skill, tmp_path,
    ):
        oom = _make_oom_payload(include_memory_killer=False)
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [oom])
        try:
            output = agent.run(_make_input(tmp_path, max_rounds=1))
        finally:
            cleanup()

        assert len(output.physical_rejections) == 1
        rej = output.physical_rejections[0]
        assert rej.dominant_layer == ""
        assert rej.dominant_layer_gb == 0.0
        assert rej.dominant_fraction == 0.0
        assert rej.binding_cap == "vram"
        # The overshoot numerics still come from the outer payload.
        assert rej.estimated_gb == 12.0
        assert rej.budget_gb == 8.0


class TestNoRejectionWhenFeasible:
    """All-OK runs must emit zero rejections — the buffer is initialized
    empty at loop start and flushed verbatim into
    ``HyperparamTuningOutput.physical_rejections`` at ``run()`` exit."""

    def test_feasible_run_yields_empty_rejection_buffer(
        self, agent_with_scripted_skill, tmp_path,
    ):
        # 2 rounds, both feasible → no rejections.
        verdicts = [FAKE_VRAM_OK, FAKE_VRAM_OK]
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, verdicts)
        try:
            output = agent.run(_make_input(
                tmp_path,
                max_rounds=2,
                attempts_per_round=1,
                attempts_per_formal_round=1,
            ))
        finally:
            cleanup()

        assert output.physical_rejections == []


class TestBytesToGbConversion:
    """dominant_layer_gb is rendered as GB from the byte count in
    ``memory_killer.dominant_layer_bytes`` (rounded to 4 decimals). A
    future refactor that forgets the /1024**3 would produce absurd
    numbers — pin it here."""

    def test_one_gb_exact(self, agent_with_scripted_skill, tmp_path):
        oom = _make_oom_payload(dominant_layer_bytes=1 * 1024 ** 3)
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [oom])
        try:
            output = agent.run(_make_input(tmp_path, max_rounds=1))
        finally:
            cleanup()
        assert output.physical_rejections[0].dominant_layer_gb == 1.0

    def test_non_round_bytes_rounded_to_four_decimals(
        self, agent_with_scripted_skill, tmp_path,
    ):
        # 2_500_000_000 bytes ≈ 2.3283 GB
        oom = _make_oom_payload(dominant_layer_bytes=2_500_000_000)
        agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [oom])
        try:
            output = agent.run(_make_input(tmp_path, max_rounds=1))
        finally:
            cleanup()
        gb = output.physical_rejections[0].dominant_layer_gb
        assert abs(gb - 2.3283) < 1e-4
