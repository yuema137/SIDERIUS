"""A.1.6 — Tuner wiring of ``core.hardware_context.get_or_create``.

Phase 6.6 §3.9. The tuner must produce the per-run hardware manifest at
``{workspace}/{run_name}_hardware.json`` on the first invocation of
``run()`` and must NOT rewrite it on a subsequent invocation over the
same workspace. The manifest's ``discovered_at`` field is treated as
immutable for the life of a workspace; subprocess children and the VRAM
wrapper will later (A.8 / A.11) load the same file instead of re-probing,
so the whole run must agree on one snapshot.

Tests exercise the full ``agent.run()`` path with LLM, sandbox, skill,
and reference-score calls mocked — only ``get_or_create`` is real.
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.hardware_context import HardwareContext, load_manifest
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.scoring_reference import ReferenceScores

# ── Canned responses (mirror test_tuning_agent.py so this file stays
#    hermetic — no import coupling across test modules) ─────────────────────

_FAKE_PLAN = {
    "model_type": "punet",
    "hypothesis": "stub",
    "reasoning": "stub",
    "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
    "train_config": {"epochs": 5, "lr": 1e-4},
    "loss_config": {"loss_type": "focal", "gamma": 2.0},
}

_FAKE_REFLECT = {
    "conclusion": "ok",
    "key_factor": "depth",
    "discovery": "gamma=2",
    "memory_update": "try depth 5",
}

_FAKE_SKILL_RESULTS = {
    "check_config_format_skill": {
        "status": "success",
        "data": {"punet": {"fields": ["depth", "segmentation_size"]}},
    },
    "evaluate_vram_skill": {
        "status": "success",
        "feasible": True,
        "estimated_gb": 2.5,
        "limit_gb": 6.0,
        "vram_budget_gb": 8.0,
        "verdict": "FITS",
        "suggestion": "",
    },
    "training_skill": {
        "status": "success",
        "results": {"final_loss": 0.5, "model_params": 100000},
    },
    "inference_skill": {"status": "success", "results": {}},
    "denoising_score_skill": {
        "status": "success",
        "results": {"denoising_score": 1.75},
    },
}


def _synth_reference() -> ReferenceScores:
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


def _mock_run_skill(skill_folder, sandbox, **params):
    return _FAKE_SKILL_RESULTS.get(skill_folder, {"status": "error", "message": "unknown skill"})


def _make_input(tmp_path) -> HyperparamTuningInput:
    return HyperparamTuningInput(
        planner_strategy="native-timing-v1",
        model_type="punet",
        file_index=6,
        max_rounds=1,
        attempts_per_round=3,
        attempts_per_formal_round=3,
        max_fail_rounds=1,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test_run"),
        ),
        progress_bar=False,
    )


# ── Fixture ────────────────────────────────────────────────────────────────


@pytest.fixture
def agent_run(tmp_path):
    """Run the agent once under mocks; yield (tmp_path, agent, agent_input)
    with mocks still live so tests can invoke ``agent.run()`` a second time."""
    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill),
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = _FAKE_PLAN
        mock_brain.reflect.return_value = _FAKE_REFLECT

        saved_records: list = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
        mock_sandbox.dirs = {"configs": configs_dir}

        agent = HyperparamTuningAgent()
        agent_input = _make_input(tmp_path)
        agent.run(agent_input)

        yield tmp_path, agent, agent_input


# ── Tests ─────────────────────────────────────────────────────────────────


def test_manifest_written_on_run(agent_run):
    """After the first run(), the manifest file must exist at
    ``{workspace}/{run_name}_hardware.json``. This is the A.1.6 completeness
    evidence — subprocess children depend on the file being there."""
    tmp_path, _, _ = agent_run
    manifest_path = tmp_path / "test_run_hardware.json"
    assert manifest_path.exists(), (
        f"Expected tuner to write hardware manifest at {manifest_path} "
        f"but the file does not exist after run()."
    )


def test_manifest_round_trips_to_schema(agent_run):
    """The file on disk must deserialise cleanly through ``load_manifest``
    into a ``HardwareContext``. Guards against a drift between the writer
    (get_or_create → write_manifest) and the reader (the sandbox child
    will call ``load_manifest`` in A.11)."""
    tmp_path, _, _ = agent_run
    ctx = load_manifest(tmp_path / "test_run_hardware.json")
    assert isinstance(ctx, HardwareContext)
    # usable_cap_bytes is a derived property, not a stored field — its
    # correctness after the round-trip proves the full schema loaded,
    # not just an ad-hoc dict of fields.
    assert ctx.usable_cap_bytes == int(0.80 * ctx.total_memory_bytes)


def test_second_run_does_not_rewrite_manifest(agent_run):
    """§3.9 treats ``discovered_at`` as immutable for the run. On a second
    ``run()`` over the same workspace, ``get_or_create`` must return the
    stored manifest (device + hostname match the live discover()) and
    skip ``write_manifest`` entirely — mtime is the cheapest proxy for
    'no write happened'."""
    tmp_path, agent, agent_input = agent_run
    manifest_path = tmp_path / "test_run_hardware.json"
    first_mtime = manifest_path.stat().st_mtime_ns

    # Second run on the same workspace. The fixture's patch context is still
    # active (we yielded from inside the ``with``), so LLM/sandbox/skills
    # stay mocked.
    agent.run(agent_input)

    second_mtime = manifest_path.stat().st_mtime_ns
    assert second_mtime == first_mtime, (
        f"Manifest was rewritten on second run "
        f"(mtime {first_mtime} → {second_mtime}). "
        f"get_or_create should return the stored manifest when device + "
        f"hostname match, preserving discovered_at."
    )


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
