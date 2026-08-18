"""
Tests for nodes/ml_code_validator_agent.py

Tests cover:
  _check_plugin
    - Valid plugin file returns (True, None)
    - Import error returns (False, message containing "Import error")
    - Missing attribute returns (False, message naming the attribute)

  _run_tests
    - subprocess returncode 0 → (True, output)
    - subprocess returncode 1 → (False, output)
    - stdout and stderr are concatenated into test_output

  _check_description
    - Existing file with >50 chars returns (True, None)
    - Missing file returns (False, error message)
    - File with ≤50 chars returns (False, error message)

  _check_config_fields
    - All int/float/bool values returns (True, None)
    - List value returns (False, message naming the field)
    - Dict value returns (False, message naming the field)
    - Mixed (some scalar, some not) returns (False, message)

  _check_instantiation_and_gradient
    - Valid plugin returns (True, True, None)
    - Import error returns (False, False, error_msg)
    - Forward shape mismatch returns (False, False, error_msg)
    - Backward failure returns (True, False, error_msg)

  MLCodeValidatorAgent.run
    - All checks pass → passed=True, error_message=None
    - Plugin check fails → passed=False, plugin_registered=False
    - Tests fail → passed=False, tests_passed=False
    - Description invalid → passed=False, description_valid=False
    - Config fields invalid → passed=False, config_fields_valid=False
    - Multiple failures → all booleans correct, error_message combines messages
    - Output file written to {workspace}/validation_{run_name}.json
    - Output file content matches ValidatorOutput
    - instantiation_passed, gradient_check_passed, llm_review_passed in output

  TestLLMReview
    - LLM bridge is called with correct prompts
    - LLMCodeReview is parsed from bridge output
    - Failed test_output is included in the review prompt
    - Passing test_output is NOT included in the review prompt
    - Instantiation error is included in the review prompt
"""

import json
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

#: The provider/model pair every agent-run case in this module uses.
_AGENT_KWARGS = {"provider": "gemini", "model_id": "gemini-3.1-flash-lite-preview"}

from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import LLMCodeReview, ValidatorInput, ValidatorOutput
from nodes.ml_code_validator_agent import (
    MLCodeValidatorAgent,
    _build_review_prompt,
    _check_config_fields,
    _check_description,
    _check_instantiation_and_gradient,
    _check_plugin,
    _run_tests,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PLUGIN_SRC = textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "test_model"

    class TestModelConfig(BaseModel):
        depth: int = Field(default=2, ge=1)

    class TestModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.emb = nn.Embedding(256, 32)
            self.proj = nn.Conv1d(32, 256, kernel_size=1)

        def forward(self, x):
            out = self.emb(x).permute(0, 2, 1)  # [B, 32, T]
            return self.proj(out)  # [B, 256, T]

    PLUGIN_CONFIG_CLASS = TestModelConfig
    PLUGIN_MODEL_CLASS  = TestModel
""")

VALID_DESCRIPTION = "A test model that does signal denoising using a simple embedding layer.\n" * 2

VALID_CONFIG_FIELDS = {"depth": 2, "channels": 64, "use_bias": True, "lr": 1e-3}

FAKE_LLM_REVIEW = {
    "spec_alignment": True,
    "trainability_concerns": [],
    "implementation_issues": [],
    "passed": True,
    "notes": "Implementation matches specification. Gradients flow correctly.",
}


def make_storage(tmp_path: Path, run_name: str = "r1") -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name=run_name),
    )


def make_input(tmp_path: Path, run_name: str = "r1", **overrides) -> ValidatorInput:
    """Build a ValidatorInput where all files exist and are valid by default."""
    plugin_path = tmp_path / "test_model.py"
    plugin_path.write_text(VALID_PLUGIN_SRC)

    test_path = tmp_path / "test_test_model.py"
    test_path.write_text("def test_dummy(): assert True\n")

    desc_path = tmp_path / "description.md"
    desc_path.write_text(VALID_DESCRIPTION)

    defaults = dict(
        model_type="test_model",
        model_file_path=str(plugin_path),
        test_file_path=str(test_path),
        description_file_path=str(desc_path),
        config_fields=VALID_CONFIG_FIELDS,
        model_description="A test model for signal denoising using embedding and projection.",
        mathematical_definition="Embedding(256,32) -> Conv1d(32,256) -> [B,256,T]",
        llm_provider="gemini",
        llm_model_id="gemini-3.1-flash-lite-preview",
        storage=make_storage(tmp_path, run_name),
    )
    defaults.update(overrides)
    return ValidatorInput(**defaults)


# ---------------------------------------------------------------------------
# _check_plugin
# ---------------------------------------------------------------------------


class TestCheckPlugin:
    def test_valid_plugin_returns_true(self, tmp_path):
        path = tmp_path / "plugin.py"
        path.write_text(VALID_PLUGIN_SRC)
        ok, err = _check_plugin(str(path))
        assert ok is True
        assert err is None

    def test_import_error_returns_false_with_message(self, tmp_path):
        path = tmp_path / "bad_plugin.py"
        path.write_text("import nonexistent_module_xyz\n")
        ok, err = _check_plugin(str(path))
        assert ok is False
        assert "Import error" in err

    def test_missing_model_type_returns_false(self, tmp_path):
        src = VALID_PLUGIN_SRC.replace("PLUGIN_MODEL_TYPE", "PLUGIN_MODEL_TYPE_GONE")
        path = tmp_path / "no_type.py"
        path.write_text(src)
        ok, err = _check_plugin(str(path))
        assert ok is False
        assert "PLUGIN_MODEL_TYPE" in err

    def test_missing_config_class_returns_false(self, tmp_path):
        src = VALID_PLUGIN_SRC.replace("PLUGIN_CONFIG_CLASS", "PLUGIN_CONFIG_CLASS_GONE")
        path = tmp_path / "no_config.py"
        path.write_text(src)
        ok, err = _check_plugin(str(path))
        assert ok is False
        assert "PLUGIN_CONFIG_CLASS" in err

    def test_missing_model_class_returns_false(self, tmp_path):
        src = VALID_PLUGIN_SRC.replace("PLUGIN_MODEL_CLASS", "PLUGIN_MODEL_CLASS_GONE")
        path = tmp_path / "no_model.py"
        path.write_text(src)
        ok, err = _check_plugin(str(path))
        assert ok is False
        assert "PLUGIN_MODEL_CLASS" in err

    def test_syntax_error_returns_false(self, tmp_path):
        path = tmp_path / "syntax_error.py"
        path.write_text("def broken(:\n    pass\n")
        ok, err = _check_plugin(str(path))
        assert ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# _run_tests
# ---------------------------------------------------------------------------


class TestRunTests:
    @staticmethod
    def _touch_test_file(tmp_path):
        """Materialize a real file so the empty-path guard doesn't
        short-circuit — these tests exercise the pytest-subprocess path."""
        p = tmp_path / "test_dummy.py"
        p.write_text("def test_dummy(): assert True\n")
        return str(p)

    def test_passing_tests_return_true(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3 passed in 0.5s"
        mock_result.stderr = ""
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            ok, _output = _run_tests(self._touch_test_file(tmp_path))
        assert ok is True

    def test_failing_tests_return_false(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED test_forward - AssertionError"
        mock_result.stderr = ""
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            ok, _output = _run_tests(self._touch_test_file(tmp_path))
        assert ok is False

    def test_stdout_and_stderr_concatenated(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "stdout content"
        mock_result.stderr = "stderr content"
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            _ok, output = _run_tests(self._touch_test_file(tmp_path))
        assert "stdout content" in output
        assert "stderr content" in output

    def test_output_returned_on_pass(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3 passed"
        mock_result.stderr = ""
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            _ok, output = _run_tests(self._touch_test_file(tmp_path))
        assert "3 passed" in output

    def test_output_returned_on_fail(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED"
        mock_result.stderr = "error detail"
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            _ok, output = _run_tests(self._touch_test_file(tmp_path))
        assert "FAILED" in output

    # --- Branch B empty/nonexistent-path guard (v16 fix) ---

    def test_run_tests_skips_when_empty_path(self):
        """Empty ``test_file_path`` is the Branch B model reuse sentinel
        emitted by the implementor's short-circuit. Pytest must NOT be
        invoked — an empty positional arg triggers full-project discovery
        (the v16 loss-chain false-negative bug)."""
        with patch("nodes.ml_code_validator_agent.subprocess.run") as mocked:
            ok, output = _run_tests("")
        assert ok is True
        assert "Skipped" in output
        assert "Branch B model reuse" in output
        mocked.assert_not_called()

    def test_run_tests_skips_when_path_not_a_file(self):
        """Nonexistent path also skips — same guard, defensive against a
        stale/cleaned path (v16 iter_015 pytest-tmp-dir race)."""
        with patch("nodes.ml_code_validator_agent.subprocess.run") as mocked:
            ok, output = _run_tests("/nonexistent/path/that/does/not/exist.py")
        assert ok is True
        assert "Skipped" in output
        mocked.assert_not_called()


# ---------------------------------------------------------------------------
# _check_description
# ---------------------------------------------------------------------------


class TestCheckDescription:
    def test_valid_description_returns_true(self, tmp_path):
        path = tmp_path / "description.md"
        path.write_text(VALID_DESCRIPTION)
        ok, err = _check_description(str(path))
        assert ok is True
        assert err is None

    def test_missing_file_returns_false(self, tmp_path):
        ok, err = _check_description(str(tmp_path / "nonexistent.md"))
        assert ok is False
        assert "not found" in err

    def test_too_short_content_returns_false(self, tmp_path):
        path = tmp_path / "description.md"
        path.write_text("short")
        ok, err = _check_description(str(path))
        assert ok is False
        assert "too short" in err

    def test_exactly_50_chars_returns_false(self, tmp_path):
        path = tmp_path / "description.md"
        path.write_text("x" * 50)
        ok, _err = _check_description(str(path))
        assert ok is False

    def test_51_chars_returns_true(self, tmp_path):
        path = tmp_path / "description.md"
        path.write_text("x" * 51)
        ok, _err = _check_description(str(path))
        assert ok is True

    def test_empty_file_returns_false(self, tmp_path):
        path = tmp_path / "description.md"
        path.write_text("")
        ok, _err = _check_description(str(path))
        assert ok is False


# ---------------------------------------------------------------------------
# _check_config_fields
# ---------------------------------------------------------------------------


class TestCheckConfigFields:
    def test_all_int_returns_true(self):
        ok, err = _check_config_fields({"depth": 2, "channels": 64})
        assert ok is True
        assert err is None

    def test_all_float_returns_true(self):
        ok, _err = _check_config_fields({"lr": 1e-3, "dropout": 0.1})
        assert ok is True

    def test_bool_returns_true(self):
        ok, _err = _check_config_fields({"use_bias": True, "depth": 3})
        assert ok is True

    def test_mixed_scalar_returns_true(self):
        ok, _err = _check_config_fields(VALID_CONFIG_FIELDS)
        assert ok is True

    def test_list_value_returns_false(self):
        ok, err = _check_config_fields({"kernel_sizes": [3, 5, 7]})
        assert ok is False
        assert "kernel_sizes" in err

    def test_dict_value_returns_false(self):
        ok, err = _check_config_fields({"nested": {"a": 1}})
        assert ok is False
        assert "nested" in err

    def test_none_value_returns_false(self):
        ok, err = _check_config_fields({"optional_field": None})
        assert ok is False
        assert "optional_field" in err

    def test_mixed_returns_false_names_all_bad_fields(self):
        ok, err = _check_config_fields({"depth": 2, "bad_list": [1, 2], "bad_dict": {}})
        assert ok is False
        assert "bad_list" in err
        assert "bad_dict" in err

    def test_empty_dict_returns_true(self):
        ok, _err = _check_config_fields({})
        assert ok is True


# ---------------------------------------------------------------------------
# _check_instantiation_and_gradient
# ---------------------------------------------------------------------------


class TestCheckInstantiationAndGradient:
    def test_valid_plugin_returns_true_true_none(self, tmp_path):
        path = tmp_path / "valid_plugin.py"
        path.write_text(VALID_PLUGIN_SRC)
        inst_ok, grad_ok, _otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert inst_ok is True
        assert grad_ok is True
        assert err is None

    def test_import_error_returns_false_false_message(self, tmp_path):
        path = tmp_path / "bad_import.py"
        path.write_text("import nonexistent_module_xyz_abc\n")
        inst_ok, grad_ok, _otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert inst_ok is False
        assert grad_ok is False
        assert err is not None

    def test_forward_shape_mismatch_returns_false_false_message(self, tmp_path):
        # Plugin that produces wrong shape
        wrong_shape_src = textwrap.dedent("""\
            import torch
            import torch.nn as nn
            from pydantic import BaseModel, Field

            PLUGIN_MODEL_TYPE = "wrong_shape_model"

            class WrongShapeConfig(BaseModel):
                depth: int = Field(default=2)

            class WrongShapeModel(nn.Module):
                def __init__(self, config):
                    super().__init__()
                    self.emb = nn.Embedding(256, 32)

                def forward(self, x):
                    return self.emb(x)  # [B, T, 32] — wrong shape

            PLUGIN_CONFIG_CLASS = WrongShapeConfig
            PLUGIN_MODEL_CLASS = WrongShapeModel
        """)
        path = tmp_path / "wrong_shape.py"
        path.write_text(wrong_shape_src)
        inst_ok, grad_ok, _otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert inst_ok is False
        assert grad_ok is False
        assert err is not None
        assert "shape" in err.lower() or "does not match" in err.lower()

    def test_backward_failure_returns_true_false_message(self, tmp_path):
        # Plugin where forward produces non-differentiable output (detached)
        no_grad_src = textwrap.dedent("""\
            import torch
            import torch.nn as nn
            from pydantic import BaseModel, Field

            PLUGIN_MODEL_TYPE = "no_grad_model"

            class NoGradConfig(BaseModel):
                depth: int = Field(default=2)

            class NoGradModel(nn.Module):
                def __init__(self, config):
                    super().__init__()
                    self.emb = nn.Embedding(256, 32)
                    self.proj = nn.Conv1d(32, 256, kernel_size=1)

                def forward(self, x):
                    out = self.emb(x).permute(0, 2, 1)
                    out = self.proj(out)
                    # Detach breaks gradient flow
                    return out.detach().requires_grad_(False)

            PLUGIN_CONFIG_CLASS = NoGradConfig
            PLUGIN_MODEL_CLASS = NoGradModel
        """)
        path = tmp_path / "no_grad.py"
        path.write_text(no_grad_src)
        inst_ok, grad_ok, _otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        # instantiation and forward pass succeed (correct shape)
        assert inst_ok is True
        # gradient check fails because output is detached
        assert grad_ok is False
        assert err is not None


# ---------------------------------------------------------------------------
# Declared output contract (V21 PR A2)
# ---------------------------------------------------------------------------
#
# MUTATION TARGET: the expected forward shape must be DERIVED from the
# plugin's declared PLUGIN_OUTPUT_TYPE, not hardcoded to the classifier
# contract. Before PR A2 the probe required (1, 256, 64) unconditionally and
# only then read the declaration, so:
#
#   * a regressor emitting [B, T] was rejected before its declaration was
#     read  -> ``test_declared_regressor_with_2d_output_passes`` FAILS on the
#     pre-PR-A2 code with
#     "Forward output shape (1, 64) does not match expected (1, 256, 64)";
#   * BOTH arms of the old declared-vs-actual check were unreachable — a
#     shape equal to (1, 256, 64) is 3-dim by construction, so the
#     classifier arm could never fire either.
#
# Reverting the derivation turns the regressor test red. That is the
# acceptance signal for the whole of PR A.


def _regressor_plugin_src(declared: str = '"regressor"') -> str:
    """A plugin whose forward returns [B, T] — the regression contract."""
    return textwrap.dedent(f"""\
        import torch
        import torch.nn as nn
        from pydantic import BaseModel, Field

        PLUGIN_MODEL_TYPE = "regressor_model"
        PLUGIN_OUTPUT_TYPE = {declared}

        class RegressorConfig(BaseModel):
            depth: int = Field(default=2, ge=1)

        class RegressorModel(nn.Module):
            def __init__(self, config):
                super().__init__()
                self.emb = nn.Embedding(256, 32)
                self.proj = nn.Conv1d(32, 1, kernel_size=1)

            def forward(self, x):
                out = self.emb(x).permute(0, 2, 1)   # [B, 32, T]
                return self.proj(out).squeeze(1)      # [B, T]

        PLUGIN_CONFIG_CLASS = RegressorConfig
        PLUGIN_MODEL_CLASS = RegressorModel
    """)


class TestDeclaredOutputContract:
    def test_declared_regressor_with_2d_output_passes(self, tmp_path):
        """THE acceptance signal for PR A: a plugin declaring ``regressor``
        and emitting [B, T] validates. This test fails on pre-PR-A2 code."""
        path = tmp_path / "regressor_plugin.py"
        path.write_text(_regressor_plugin_src())
        inst_ok, grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert (inst_ok, grad_ok, otype_ok, err) == (True, True, True, None)

    def test_declared_classifier_with_3d_output_passes(self, tmp_path):
        """Parity: the classifier contract is unaffected by PR A2."""
        path = tmp_path / "classifier_plugin.py"
        path.write_text(
            VALID_PLUGIN_SRC.replace(
                'PLUGIN_MODEL_TYPE = "test_model"',
                'PLUGIN_MODEL_TYPE = "test_model"\nPLUGIN_OUTPUT_TYPE = "classifier"',
            )
        )
        inst_ok, grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert (inst_ok, grad_ok, otype_ok, err) == (True, True, True, None)

    def test_missing_declaration_is_read_as_classifier(self, tmp_path):
        """Legacy-read compatibility: plugins predating the declaration keep
        validating. A NEW plugin must declare explicitly — that is enforced on
        the producer side, not here."""
        path = tmp_path / "legacy_plugin.py"
        path.write_text(VALID_PLUGIN_SRC)  # no PLUGIN_OUTPUT_TYPE at all
        inst_ok, grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert (inst_ok, grad_ok, otype_ok, err) == (True, True, True, None)

    def test_declared_regressor_but_3d_output_is_refused(self, tmp_path):
        """Declaration and reality must agree — the dangerous case: metadata
        says regressor, the model still emits the classifier shape."""
        src = VALID_PLUGIN_SRC.replace(
            'PLUGIN_MODEL_TYPE = "test_model"',
            'PLUGIN_MODEL_TYPE = "test_model"\nPLUGIN_OUTPUT_TYPE = "regressor"',
        )
        path = tmp_path / "lying_regressor.py"
        path.write_text(src)
        inst_ok, _grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert inst_ok is False
        assert otype_ok is False
        assert err is not None
        # names the actual shape and the shape its own declaration requires
        assert "(1, 256, 64)" in err and "(1, 64)" in err

    def test_declared_classifier_but_2d_output_is_refused(self, tmp_path):
        """The mirror case."""
        path = tmp_path / "lying_classifier.py"
        path.write_text(_regressor_plugin_src(declared='"classifier"'))
        inst_ok, _grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert inst_ok is False
        assert otype_ok is False
        assert err is not None
        assert "(1, 64)" in err and "(1, 256, 64)" in err

    def test_unknown_declaration_fails_closed(self, tmp_path):
        """An unrecognised contract must NOT be coerced to classifier — that
        is how a metadata defect becomes wrong scientific semantics."""
        path = tmp_path / "nonsense_contract.py"
        path.write_text(_regressor_plugin_src(declared='"nonsense"'))
        inst_ok, grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert (inst_ok, grad_ok, otype_ok) == (False, False, False)
        assert err is not None
        assert "nonsense" in err
        assert "classifier" in err and "regressor" in err

    def test_non_tensor_output_is_refused(self, tmp_path):
        """A model returning a non-tensor must fail with a typed message
        rather than raising out of the validator."""
        src = textwrap.dedent("""\
            import torch.nn as nn
            from pydantic import BaseModel

            PLUGIN_MODEL_TYPE = "tuple_model"

            class TupleConfig(BaseModel):
                pass

            class TupleModel(nn.Module):
                def __init__(self, config):
                    super().__init__()
                    self.lin = nn.Linear(4, 4)

                def forward(self, x):
                    return ("not", "a", "tensor")

            PLUGIN_CONFIG_CLASS = TupleConfig
            PLUGIN_MODEL_CLASS = TupleModel
        """)
        path = tmp_path / "tuple_out.py"
        path.write_text(src)
        inst_ok, grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
            str(path)
        )
        assert (inst_ok, grad_ok, otype_ok) == (False, False, False)
        assert err is not None
        assert "tuple" in err.lower()


# ---------------------------------------------------------------------------
# Fixtures for full run tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_bridge():
    """Mock LLMBridge.generate to return a passing review."""
    with patch("nodes.ml_code_validator_agent.LLMBridge") as MockBridge:
        instance = MockBridge.return_value
        instance.generate.return_value = FAKE_LLM_REVIEW
        yield MockBridge


@pytest.fixture
def passing_subprocess():
    """Patch subprocess.run to simulate all pytest tests passing."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "1 passed in 0.1s"
    mock_result.stderr = ""
    with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
        yield


@pytest.fixture
def passing_mocks(mock_llm_bridge, passing_subprocess):
    """Combined fixture: mocked LLM + mocked subprocess."""
    yield


# ---------------------------------------------------------------------------
# MLCodeValidatorAgent.run — integration of all checks
# ---------------------------------------------------------------------------


class TestMLCodeValidatorAgentRun:
    def test_a_fully_passing_validation_produces_the_complete_output(self, tmp_path, passing_mocks):
        """One property, one agent run.

        Was four functions -- `..._returns_passed_true`,
        `..._individual_booleans`, `..._error_message_is_none`,
        `..._model_type_set` -- each executing the IDENTICAL
        `agent.run(make_input(tmp_path))` under the same fixture and reading a
        different attribute off the same output. That is one semantic claim
        ("a fully-passing validation reports every check passed, names the
        model, and carries no error") paid for with four full agent runs.

        Grouped rather than merged: each assertion below keeps its own message,
        so a failure still says which half of the contract broke.
        """
        agent = MLCodeValidatorAgent(**_AGENT_KWARGS)
        out = agent.run(make_input(tmp_path))

        assert out.passed is True, "the overall verdict"
        assert out.error_message is None, "a passing run must carry no error"
        assert out.model_type == "test_model", "the model under validation is named"

        per_check = {
            "plugin_registered": out.plugin_registered,
            "tests_passed": out.tests_passed,
            "description_valid": out.description_valid,
            "config_fields_valid": out.config_fields_valid,
            "instantiation_passed": out.instantiation_passed,
            "gradient_check_passed": out.gradient_check_passed,
            "llm_review_passed": out.llm_review_passed,
        }
        failed = sorted(name for name, ok in per_check.items() if ok is not True)
        assert not failed, f"individual checks not reported as passed: {failed}"

    def test_plugin_failure_sets_passed_false(self, tmp_path, passing_subprocess, mock_llm_bridge):
        bad_plugin = tmp_path / "bad.py"
        bad_plugin.write_text("import broken_import_xyz\n")
        inp = make_input(tmp_path, model_file_path=str(bad_plugin))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            inp
        )
        assert out.passed is False
        assert out.plugin_registered is False

    def test_plugin_failure_error_message_present(
        self, tmp_path, passing_subprocess, mock_llm_bridge
    ):
        bad_plugin = tmp_path / "bad.py"
        bad_plugin.write_text("import broken_import_xyz\n")
        inp = make_input(tmp_path, model_file_path=str(bad_plugin))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            inp
        )
        assert out.error_message is not None

    def test_test_failure_sets_passed_false(self, tmp_path, mock_llm_bridge):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED test_forward - AssertionError"
        mock_result.stderr = ""
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            out = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            ).run(make_input(tmp_path))
        assert out.passed is False
        assert out.tests_passed is False

    def test_test_failure_test_output_captured(self, tmp_path, mock_llm_bridge):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED test_forward"
        mock_result.stderr = ""
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            out = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            ).run(make_input(tmp_path))
        assert out.test_output is not None
        assert "FAILED" in out.test_output

    def test_description_failure_sets_passed_false(self, tmp_path, passing_mocks):
        subdir = tmp_path / "short_desc"
        subdir.mkdir()
        desc_path = subdir / "description.md"
        desc_path.write_text("too short")
        inp = make_input(tmp_path, description_file_path=str(desc_path))
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            inp
        )
        assert out.passed is False
        assert out.description_valid is False

    def test_config_fields_failure_sets_passed_false(self, tmp_path, passing_mocks):
        inp = make_input(tmp_path, config_fields={"depth": 2, "bad": [1, 2, 3]})
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            inp
        )
        assert out.passed is False
        assert out.config_fields_valid is False

    def test_multiple_failures_all_booleans_correct(self, tmp_path, mock_llm_bridge):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "1 failed"
        mock_result.stderr = ""
        bad_plugin = tmp_path / "bad.py"
        bad_plugin.write_text("import broken_xyz\n")
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            inp = make_input(
                tmp_path,
                model_file_path=str(bad_plugin),
                config_fields={"bad": [1, 2]},
            )
            out = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            ).run(inp)
        assert out.passed is False
        assert out.plugin_registered is False
        assert out.tests_passed is False
        assert out.config_fields_valid is False

    def test_test_output_included_on_pass(self, tmp_path, passing_mocks):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            make_input(tmp_path)
        )
        assert out.test_output is not None
        assert "passed" in out.test_output

    def test_llm_review_fields_in_output(self, tmp_path, passing_mocks):
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            make_input(tmp_path)
        )
        assert out.llm_review_spec_alignment is True
        assert out.llm_review_trainability_concerns == []
        assert out.llm_review_implementation_issues == []
        assert out.llm_review_notes is not None


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------


class TestFilePersistence:
    def test_the_artifact_is_written_and_carries_every_check(self, tmp_path, passing_mocks):
        """One property, one agent run.

        Was four functions each re-running the agent to read a different key
        out of the same JSON file: that it exists, that it parses, that it
        holds the check fields, and that `model_type` is right. One write, one
        read, all four claims.
        """
        agent = MLCodeValidatorAgent(**_AGENT_KWARGS)
        agent.run(make_input(tmp_path, run_name="myrun"))

        path = tmp_path / "validation_myrun.json"
        assert path.exists(), "no validation artifact was written"
        data = json.loads(path.read_text())

        required = [
            "passed",
            "model_type",
            "plugin_registered",
            "tests_passed",
            "description_valid",
            "config_fields_valid",
            "instantiation_passed",
            "gradient_check_passed",
            "llm_review_passed",
        ]
        missing = [f for f in required if f not in data]
        assert not missing, f"the artifact omits check fields: {missing}"
        assert data["model_type"] == "test_model"

    def test_workspace_created_if_missing(self, tmp_path, passing_mocks):
        nested = tmp_path / "deep" / "workspace"
        inp = make_input(tmp_path)
        inp = inp.model_copy(update={"storage": make_storage(nested, "r1")})
        MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(inp)
        assert (nested / "validation_r1.json").exists()


# ---------------------------------------------------------------------------
# TestLLMReview
# ---------------------------------------------------------------------------


class TestLLMReview:
    def test_llm_bridge_called_with_prompts(self, tmp_path, passing_subprocess):
        with patch("nodes.ml_code_validator_agent.LLMBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.generate.return_value = FAKE_LLM_REVIEW
            agent = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            )
            inp = make_input(tmp_path)
            agent.run(inp)
            instance.generate.assert_called_once()
            call_args = instance.generate.call_args
            system_prompt = call_args[0][0]
            user_prompt = call_args[0][1]
            assert "mathematical" in system_prompt.lower() or "spec" in system_prompt.lower()
            assert inp.model_description in user_prompt
            assert inp.mathematical_definition in user_prompt

    def test_llm_review_parsed_into_llm_code_review(self, tmp_path, passing_subprocess):
        with patch("nodes.ml_code_validator_agent.LLMBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.generate.return_value = FAKE_LLM_REVIEW
            agent = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            )
            out = agent.run(make_input(tmp_path))
            assert out.llm_review_passed is True
            assert out.llm_review_spec_alignment is True
            assert out.llm_review_trainability_concerns == []
            assert "matches specification" in out.llm_review_notes

    def test_llm_review_failure_sets_passed_false(self, tmp_path, passing_subprocess):
        failing_review = {
            "spec_alignment": False,
            "trainability_concerns": ["detached tensor in path"],
            "implementation_issues": ["missing residual connection"],
            "passed": False,
            "notes": "Implementation does not match the spec.",
        }
        with patch("nodes.ml_code_validator_agent.LLMBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.generate.return_value = failing_review
            agent = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            )
            out = agent.run(make_input(tmp_path))
            assert out.llm_review_passed is False
            assert out.passed is False
            assert out.error_message is not None

    def test_failed_test_output_included_in_review_prompt(self, tmp_path):
        """When pytest fails, test_output is passed to the LLM review prompt."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED test_forward - RuntimeError: size mismatch"
        mock_result.stderr = ""
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            with patch("nodes.ml_code_validator_agent.LLMBridge") as MockBridge:
                instance = MockBridge.return_value
                instance.generate.return_value = FAKE_LLM_REVIEW
                agent = MLCodeValidatorAgent(
                    provider="gemini", model_id="gemini-3.1-flash-lite-preview"
                )
                agent.run(make_input(tmp_path))
                user_prompt = instance.generate.call_args[0][1]
                assert "FAILED test_forward" in user_prompt
                assert "Pytest Output" in user_prompt

    def test_passed_test_output_not_in_review_prompt(self, tmp_path, passing_subprocess):
        """When pytest passes, test_output is NOT forwarded to the LLM review prompt."""
        with patch("nodes.ml_code_validator_agent.LLMBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.generate.return_value = FAKE_LLM_REVIEW
            agent = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            )
            agent.run(make_input(tmp_path))
            user_prompt = instance.generate.call_args[0][1]
            assert "Pytest Output" not in user_prompt

    def test_instantiation_error_included_in_review_prompt(self, tmp_path, passing_subprocess):
        """When instantiation fails, inst_err is passed to the LLM review prompt."""
        broken_shape_src = textwrap.dedent("""\
            import torch
            import torch.nn as nn
            from pydantic import BaseModel, Field

            PLUGIN_MODEL_TYPE = "broken_shape"

            class BrokenShapeConfig(BaseModel):
                depth: int = Field(default=2)

            class BrokenShapeModel(nn.Module):
                def __init__(self, config):
                    super().__init__()
                    self.proj = nn.Linear(64, 32)

                def forward(self, x):
                    return self.proj(x.float())  # wrong shape

            PLUGIN_CONFIG_CLASS = BrokenShapeConfig
            PLUGIN_MODEL_CLASS = BrokenShapeModel
        """)
        plugin_path = tmp_path / "broken_shape.py"
        plugin_path.write_text(broken_shape_src)
        with patch("nodes.ml_code_validator_agent.LLMBridge") as MockBridge:
            instance = MockBridge.return_value
            instance.generate.return_value = FAKE_LLM_REVIEW
            agent = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            )
            agent.run(make_input(tmp_path, model_file_path=str(plugin_path)))
            user_prompt = instance.generate.call_args[0][1]
            assert "Runtime Error" in user_prompt


# ---------------------------------------------------------------------------
# Expert advice prompt injection tests
# ---------------------------------------------------------------------------


class TestExpertAdviceInReviewPrompt:
    """Verify expert_advice flows into the LLM review prompt."""

    def _make_input(self):
        return ValidatorInput(
            model_type="test_model",
            model_file_path="/fake/model.py",
            test_file_path="/fake/test_model.py",
            description_file_path="/fake/description.md",
            config_fields={"channels": 64},
            model_description="A test model.",
            mathematical_definition="Linear → ReLU → Linear",
            storage={"backend": "local", "local": {"workspace": "/tmp/test", "run_name": "r1"}},
        )

    def test_includes_expert_advice_string(self):
        inp = self._make_input()
        inp.expert_advice = "Pay extra attention to gradient flow"
        prompt = _build_review_prompt(inp, plugin_src="class Model: pass")
        assert "Expert Guidance" in prompt
        assert "gradient flow" in prompt

    def test_excludes_expert_when_empty(self):
        inp = self._make_input()
        inp.expert_advice = ""
        prompt = _build_review_prompt(inp, plugin_src="class Model: pass")
        assert "Expert Guidance" not in prompt

    def test_includes_structured_expert_advice(self):
        from agent.schemas.hyperparam_tuning import ExpertAdvice

        inp = self._make_input()
        inp.expert_advice = ExpertAdvice(
            focus_areas=["residual connections"],
            constraints=["must pass within 2 attempts"],
            known_failures=["vanishing gradients"],
            suggested_directions=[],
            rationale="Previous implementation failed gradient check.",
        )
        prompt = _build_review_prompt(inp, plugin_src="class Model: pass")
        assert "Expert Guidance" in prompt
        assert "residual connections" in prompt
        assert "vanishing gradients" in prompt

    def test_expert_advice_before_human_advice(self):
        inp = self._make_input()
        inp.expert_advice = "Expert says check padding"
        inp.human_advice = "Human says check normalization"
        prompt = _build_review_prompt(inp, plugin_src="class Model: pass")
        expert_pos = prompt.index("Expert Guidance")
        human_pos = prompt.index("Human Guidance")
        assert expert_pos < human_pos


# ---------------------------------------------------------------------------
# Inheritance decoupling — inherit_ok does NOT gate `passed`
# ---------------------------------------------------------------------------


class TestInheritanceDecoupledFromPassed:
    """Inheritance check is informational — a regex miss must not block a
    trainable model. Deviations flow downstream via inheritance_deviation_notes
    and unverified_inherited_components instead of failing the node."""

    def test_inheritance_miss_still_passes_when_trainable(self, tmp_path, passing_mocks):
        """All trainability checks pass, one inherited component's regex misses → passed=True."""
        from agent.schemas.proposal import InheritedComponent

        # VALID_PLUGIN_SRC has no fft/rfft — claim spectral_conv so it fails to match.
        inp = make_input(
            tmp_path,
            inherited_components=[
                InheritedComponent(
                    component="spectral_conv",
                    source_type="experiment",
                    source_id="gated_fno",
                    contribution_evidence="Claimed but absent in source.",
                )
            ],
        )
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            inp
        )
        assert out.passed is True
        assert out.inheritance_check_passed is False
        assert out.inheritance_deviation_notes is not None
        assert "spectral_conv" in out.inheritance_deviation_notes
        assert out.unverified_inherited_components == ["spectral_conv"]

    def test_error_message_does_not_mention_inheritance_when_passed(self, tmp_path, passing_mocks):
        """When only inheritance fails, error_message must remain None."""
        from agent.schemas.proposal import InheritedComponent

        inp = make_input(
            tmp_path,
            inherited_components=[
                InheritedComponent(
                    component="spectral_conv",
                    source_type="experiment",
                    source_id="gated_fno",
                    contribution_evidence="Claimed but absent in source.",
                )
            ],
        )
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            inp
        )
        assert out.error_message is None

    def test_inheritance_pass_leaves_deviation_notes_none(self, tmp_path, passing_mocks):
        """When every claimed component matches, deviation_notes stays None and the
        structured list stays empty."""
        from agent.schemas.proposal import InheritedComponent

        # VALID_PLUGIN_SRC contains nn.Embedding — this claim will match.
        inp = make_input(
            tmp_path,
            inherited_components=[
                InheritedComponent(
                    component="embedding_layer",
                    source_type="experiment",
                    source_id="punet",
                    contribution_evidence="ADC encoding.",
                )
            ],
        )
        out = MLCodeValidatorAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview").run(
            inp
        )
        assert out.inheritance_check_passed is True
        assert out.inheritance_deviation_notes is None
        assert out.unverified_inherited_components == []

    def test_trainability_failure_still_fails_even_when_inheritance_ok(
        self, tmp_path, mock_llm_bridge
    ):
        """If pytest fails, the model must still fail overall — inheritance cannot
        rescue a non-trainable model."""
        from agent.schemas.proposal import InheritedComponent

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED test_forward"
        mock_result.stderr = ""
        with patch("nodes.ml_code_validator_agent.subprocess.run", return_value=mock_result):
            inp = make_input(
                tmp_path,
                inherited_components=[
                    InheritedComponent(
                        component="embedding_layer",
                        source_type="experiment",
                        source_id="punet",
                        contribution_evidence="ADC encoding.",
                    )
                ],
            )
            out = MLCodeValidatorAgent(
                provider="gemini", model_id="gemini-3.1-flash-lite-preview"
            ).run(inp)
        assert out.passed is False
        assert out.tests_passed is False
        # When the model fails for a trainability reason, inheritance deviation
        # notes are not emitted (the deviation only propagates for passing models).
        assert out.inheritance_deviation_notes is None
