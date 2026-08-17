"""Phase 6.7 Commit 4 — tuner-side silent-train-crash routing.

Pins the contract that connects the producer-side sentinel (Commit 3,
``execute_tools.train_engine_sandbox._save_with_sentinel``) and the
orchestrator's error-categorization logic in
``nodes.ml_hyperparameter_tune_agent.run`` (the inference-error branch
around lines 1387-1446).

Concretely: when the inference subprocess fails because the trainer
crashed silently after ``torch.save`` returned (kernel OOM-kill,
post-save segfault, GPU watchdog), the inference subprocess raises
``RuntimeError("error_training: missing _OK_<exp_id> sentinel ...")``
inside ``inference_single._assert_training_sentinel``. That error is
captured by ``execute_inference``, formatted by
``_format_subprocess_error``, and surfaced as
``inf_status = {"status": "error", "message": "...error_training:..."}``.

The tuner's branch must detect the ``error_training:`` substring and
re-route the saved record's status from ``error_inference`` (the
default for an inference-skill error) to ``error_training``. Without
this re-route, a silent training crash would be misclassified as an
inference failure and the planner would be told to "fix inference"
when the real bug is in training.

Three branches are pinned:

1. **Re-routing path**: inference returns an error with the
   ``error_training:`` prefix → saved record's status is
   ``error_training`` (not ``error_inference``).
2. **Negative case**: inference returns a plain error without the
   prefix → status stays ``error_inference``.
3. **CUDA-OOM disambiguation**: inference returns CUDA OOM (no
   ``error_training:`` prefix) → status is ``error_inference_oom``,
   not ``error_training`` — the prefix check must be specific.

The harness mirrors ``test_physical_rejection_capture.py``: patch
``LLMBridge``, ``TidmadSandbox``, ``_run_skill``, ``load_reference_scores``,
and ``get_or_create`` so the run is hermetic (no GPU, no API, no HDF5).
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timezone
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.hardware_context import HardwareContext
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.scoring_reference import ReferenceScores


def _stub_hardware_context() -> HardwareContext:
    return HardwareContext(
        device_name="stub-cuda-device",
        total_memory_bytes=32 * 1024**3,
        compute_capability=(9, 0),
        multiprocessor_count=128,
        cuda_runtime_version="12.4",
        torch_version="2.5.1",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime(2026, 4, 26, tzinfo=UTC),
    )


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
# Canned skill payloads
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
FAKE_TRAIN_OK = {
    "status": "success",
    "results": {"final_loss": 0.5, "model_params": 100000},
}


# Realistic silent-crash inference error: the inference subprocess's
# preflight raises ``error_training: missing _OK_<exp_id>`` and
# ``_format_subprocess_error`` wraps it into the message field. The
# ``error_training:`` substring is what the tuner pattern-matches.
SILENT_CRASH_INFERENCE_ERROR = {
    "status": "error",
    "message": (
        "Inference failed with exit code 1\n"
        "--- stderr ---\n"
        "Traceback (most recent call last):\n"
        '  File "execute_tools/inference_single.py", line 47, in main\n'
        "    _assert_training_sentinel(model_path, exp_id)\n"
        "RuntimeError: error_training: missing _OK_exp_silent_001 sentinel "
        "next to model checkpoint — trainer crashed silently after save.\n"
    ),
}

# Plain inference failure — no error_training: prefix anywhere.
PLAIN_INFERENCE_ERROR = {
    "status": "error",
    "message": (
        "Inference failed with exit code 1\n"
        "--- stderr ---\n"
        "Traceback (most recent call last):\n"
        '  File "execute_tools/inference_single.py", line 132, in run\n'
        "    out = model(x)\n"
        "RuntimeError: shape mismatch in conv layer\n"
    ),
}

# CUDA OOM during inference — must route to ``error_inference_oom``,
# NOT ``error_training``. The prefix check must not over-match.
CUDA_OOM_INFERENCE_ERROR = {
    "status": "error",
    "message": (
        "Inference failed with exit code 1\n"
        "--- stderr ---\n"
        "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 314 MiB.\n"
    ),
}


# ---------------------------------------------------------------------------
# Agent wiring
# ---------------------------------------------------------------------------


def _make_input(tmp_path) -> HyperparamTuningInput:
    """1 round, 1 attempt, 1 fail-budget — the moment our single
    inference-side failure lands a record, the outer loop aborts."""
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=1,
        attempts_per_round=1,
        attempts_per_formal_round=1,
        max_fail_rounds=1,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(tmp_path),
                run_name="silent_crash_test",
            ),
        ),
        progress_bar=False,
    )


def _make_scripted_skill(inference_response: dict):
    """Skill router: VRAM OK → training OK → inference returns the
    caller-supplied response. The time-check gate is skipped because
    the input leaves both budget kwargs at their defaults (None)."""

    def side_effect(skill_folder, sandbox, **params):
        if skill_folder == "check_config_format_skill":
            return FAKE_CONFIG_MANUAL
        if skill_folder == "evaluate_vram_skill":
            return FAKE_VRAM_OK
        if skill_folder == "training_skill":
            return FAKE_TRAIN_OK
        if skill_folder == "inference_skill":
            return inference_response
        # The scoring skill should never run — inference fails first.
        return {"status": "error", "message": f"unexpected skill {skill_folder}"}

    return side_effect


@pytest.fixture
def agent_with_inference_error():
    """Yields a factory that wires the harness around a scripted
    inference response, returning ``(agent, saved_records, cleanup)``."""

    def make(inference_response: dict):
        side_effect = _make_scripted_skill(inference_response)
        cms = (
            patch("nodes.ml_hyperparameter_tune_agent.LLMBridge"),
            patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox"),
            patch(
                "nodes.ml_hyperparameter_tune_agent.runtime._run_skill",
                side_effect=side_effect,
            ),
            patch(
                "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
                return_value=_synth_reference_stub(),
            ),
            patch(
                "nodes.ml_hyperparameter_tune_agent.get_or_create",
                return_value=_stub_hardware_context(),
            ),
            tempfile.TemporaryDirectory(),
        )
        bridge_cm, sandbox_cm, skill_cm, ref_cm, hw_cm, configs_cm = cms
        MockBridge = bridge_cm.__enter__()
        MockSandbox = sandbox_cm.__enter__()
        skill_cm.__enter__()
        ref_cm.__enter__()
        hw_cm.__enter__()
        configs_dir = configs_cm.__enter__()

        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN
        mock_brain.reflect.return_value = FAKE_REFLECT

        saved: list[dict] = []
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

        return HyperparamTuningAgent(), saved, cleanup

    yield make


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSilentCrashReroute:
    """The headline contract: an inference-side error carrying the
    ``error_training:`` substring must surface as ``status=error_training``
    in the saved record. This is the integration point that turns the
    Commit 3 sentinel into actionable feedback for the planner."""

    def test_inference_error_with_training_prefix_routes_to_error_training(
        self,
        agent_with_inference_error,
        tmp_path,
    ):
        agent, saved, cleanup = agent_with_inference_error(
            SILENT_CRASH_INFERENCE_ERROR,
        )
        try:
            agent.run(_make_input(tmp_path))
        finally:
            cleanup()

        # Find the inference-failure record. Other records (rejection,
        # time-skip) won't appear in this scripted path, but we filter
        # by the status family to be robust against future preflight
        # additions that emit their own records.
        error_records = [r for r in saved if r.get("status", "").startswith("error_")]
        assert len(error_records) == 1, (
            f"expected exactly one error record; saved statuses: {[r.get('status') for r in saved]}"
        )

        rec = error_records[0]
        assert rec["status"] == "error_training", (
            f"silent train crash routed as {rec['status']!r}; "
            f"the ``error_training:`` prefix was not detected. "
            f"This means the planner would see an inference failure when "
            f"the real cause is a post-save training crash."
        )

    def test_silent_crash_record_carries_actionable_memory(
        self,
        agent_with_inference_error,
        tmp_path,
    ):
        """The record's ``memory.discovery`` and ``memory.memory_update``
        must point the planner at the trainer, not at inference. This
        is the second half of the routing contract — a correct status
        with the wrong memory text would still mislead the LLM."""
        agent, saved, cleanup = agent_with_inference_error(
            SILENT_CRASH_INFERENCE_ERROR,
        )
        try:
            agent.run(_make_input(tmp_path))
        finally:
            cleanup()

        rec = next(r for r in saved if r["status"] == "error_training")
        mem = rec["memory"]
        # The conclusion explicitly says "silently" — that's the keyword
        # that distinguishes this record from a normal training-side
        # crash and tells the planner the .pth was nominally produced.
        assert "silently" in mem["conclusion"].lower(), (
            f"expected 'silently' in conclusion; got: {mem['conclusion']!r}"
        )
        # The memory_update should not tell the planner to "fix inference".
        assert "fix the inference" not in mem["memory_update"].lower()


class TestNonSilentCrashStaysAsInference:
    """Negative-control: a plain inference crash without the prefix
    must continue to route as ``error_inference``. The substring check
    must not over-trigger on every inference error."""

    def test_plain_inference_error_routes_to_error_inference(
        self,
        agent_with_inference_error,
        tmp_path,
    ):
        agent, saved, cleanup = agent_with_inference_error(
            PLAIN_INFERENCE_ERROR,
        )
        try:
            agent.run(_make_input(tmp_path))
        finally:
            cleanup()

        error_records = [r for r in saved if r.get("status", "").startswith("error_")]
        assert len(error_records) == 1
        assert error_records[0]["status"] == "error_inference"

    def test_cuda_oom_routes_to_error_inference_oom_not_training(
        self,
        agent_with_inference_error,
        tmp_path,
    ):
        """A CUDA OOM during inference must route to
        ``error_inference_oom``, NOT ``error_training``. This pins
        that the prefix check is specific enough to leave the existing
        OOM disambiguation intact."""
        agent, saved, cleanup = agent_with_inference_error(
            CUDA_OOM_INFERENCE_ERROR,
        )
        try:
            agent.run(_make_input(tmp_path))
        finally:
            cleanup()

        error_records = [r for r in saved if r.get("status", "").startswith("error_")]
        assert len(error_records) == 1
        rec = error_records[0]
        assert rec["status"] == "error_inference_oom", (
            f"CUDA OOM mis-routed as {rec['status']!r}; the prefix check is over-matching."
        )
