"""
DataScope boundary invariant at the sandbox (DS3).

No SampleSet outside the resolved scope may reach file I/O:
  * execute_training / execute_inference — reject BEFORE subprocess launch,
    returning each method's established structured error dict with
    error_type="scope_violation" (non-retryable; see design doc DS5).
  * score_vector — raises ValueError (ScopeViolationError subclass),
    consistent with its existing exception contract.

The invariant is uniform (rejection before any file I/O); only the outward
error shape follows each method's contract. See
docs/design/enable_partial_file_list.md (Commit DS3).

Uses unittest.mock to intercept subprocess.run — no GPU, no real data.
"""

import os
from unittest.mock import patch

import pytest

from core.sandbox_executor import StubSandbox, TidmadSandbox
from execute_tools.dataset_config import DataScope, ScopeViolationError
from execute_tools.scoring_utils import validate_sample_set

# Minimal valid configs that pass Pydantic validation (mirrors
# tests/unit/core/test_sandbox_executor.py).
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
EXP_ID = "scope_exp_001"
RUN_NAME = "scope_run"

SCOPE_4_9 = DataScope(file_indices=[4, 5, 6, 7, 8, 9])
IN_SCOPE_SS = {4: [0, 1], 7: [5]}
OUT_OF_SCOPE_SS = {2: [0, 1], 7: [5]}


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), data_scope=SCOPE_4_9)


@pytest.fixture
def stub(tmp_path):
    return StubSandbox(run_name=RUN_NAME, workspace=str(tmp_path), data_scope=SCOPE_4_9)


def _assert_scope_error_dict(result):
    assert result["status"] == "error"
    assert result["error_type"] == "scope_violation"
    assert result["message"].startswith("error_scope_violation:")
    assert "outside the DataScope" in result["message"]


# ---------------------------------------------------------------------------
# validate_sample_set — scope parameter
# ---------------------------------------------------------------------------


class TestValidateSampleSetScope:
    def test_scope_none_keeps_legacy_behavior(self):
        assert validate_sample_set({2: [0, 1]}) == {2: [0, 1]}

    def test_legacy_string_keys_still_coerced(self):
        assert validate_sample_set({"4": [0]}, scope=SCOPE_4_9) == {4: [0]}

    def test_in_scope_passes(self):
        assert validate_sample_set(IN_SCOPE_SS, scope=SCOPE_4_9) == IN_SCOPE_SS

    def test_out_of_scope_raises_scope_violation(self):
        with pytest.raises(ScopeViolationError, match="file_index 2 is outside the DataScope"):
            validate_sample_set(OUT_OF_SCOPE_SS, scope=SCOPE_4_9)

    def test_scope_violation_is_a_value_error(self):
        with pytest.raises(ValueError):
            validate_sample_set(OUT_OF_SCOPE_SS, scope=SCOPE_4_9)

    def test_out_of_range_without_scope_stays_plain_value_error(self):
        with pytest.raises(ValueError, match="out of range") as exc_info:
            validate_sample_set({25: [0]})
        assert not isinstance(exc_info.value, ScopeViolationError)


# ---------------------------------------------------------------------------
# TidmadSandbox — rejection before any file I/O
# ---------------------------------------------------------------------------


class TestProductionSandboxScope:
    @patch("core.sandbox_executor.subprocess.run")
    def test_training_out_of_scope_error_dict_no_subprocess(self, mock_run, sandbox):
        result = sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=OUT_OF_SCOPE_SS,
        )
        _assert_scope_error_dict(result)
        mock_run.assert_not_called()

    @patch("core.sandbox_executor.subprocess.run")
    def test_inference_out_of_scope_error_dict_no_subprocess(self, mock_run, sandbox):
        result = sandbox.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            sample_set=OUT_OF_SCOPE_SS,
        )
        _assert_scope_error_dict(result)
        # Inference error dict carries the method's timing keys.
        assert result["per_file_timings_ms"] == []
        assert result["process_startup_ms"] is None
        mock_run.assert_not_called()

    def test_score_vector_out_of_scope_raises(self, sandbox):
        with pytest.raises(ScopeViolationError, match="outside the DataScope"):
            sandbox.score_vector(
                OUT_OF_SCOPE_SS, anchor_map={}, s_max=1.0, denoised_filename_fn=lambda i: f"{i}.h5"
            )

    @patch("core.sandbox_executor.subprocess.run")
    def test_training_in_scope_passes_validation(self, mock_run, sandbox):
        """In-scope SampleSet proceeds to the subprocess (mocked success +
        sentinel, mirroring test_sandbox_executor's success pattern)."""

        def _side_effect(*args, **kwargs):
            os.makedirs(sandbox.dirs["models"], exist_ok=True)
            with open(os.path.join(sandbox.dirs["models"], f"_OK_{EXP_ID}"), "wb"):
                pass
            mock = type("R", (), {})()
            mock.returncode, mock.stdout, mock.stderr = 0, "done\n", ""
            return mock

        mock_run.side_effect = _side_effect
        result = sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=IN_SCOPE_SS,
        )
        assert result["status"] == "success"
        mock_run.assert_called_once()

    def test_default_scope_preserves_behavior(self, tmp_path):
        """No data_scope → complete dataset; formerly-valid sets still pass."""
        sb = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path))
        assert sb.data_scope == DataScope.default()
        assert validate_sample_set({2: [0]}, scope=sb.data_scope) == {2: [0]}


# ---------------------------------------------------------------------------
# StubSandbox — parity (pseudo mode must exercise the invariant)
# ---------------------------------------------------------------------------


class TestStubSandboxScope:
    def test_training_out_of_scope_error_dict(self, stub):
        result = stub.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=OUT_OF_SCOPE_SS,
        )
        _assert_scope_error_dict(result)

    def test_inference_out_of_scope_error_dict(self, stub):
        result = stub.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            sample_set=OUT_OF_SCOPE_SS,
        )
        _assert_scope_error_dict(result)
        assert result["per_file_timings_ms"] == []

    def test_score_vector_out_of_scope_raises(self, stub):
        with pytest.raises(ScopeViolationError):
            stub.score_vector(
                OUT_OF_SCOPE_SS, anchor_map={}, s_max=1.0, denoised_filename_fn=lambda i: f"{i}.h5"
            )

    def test_in_scope_synthesis_still_works(self, stub):
        train = stub.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=IN_SCOPE_SS,
        )
        assert train["status"] == "success"
        infer = stub.execute_inference(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG, sample_set=IN_SCOPE_SS
        )
        assert infer["status"] == "success"
        _vec, scalar = stub.score_vector(
            IN_SCOPE_SS, anchor_map={}, s_max=1.0, denoised_filename_fn=lambda i: f"{i}.h5"
        )
        assert isinstance(scalar, float)
