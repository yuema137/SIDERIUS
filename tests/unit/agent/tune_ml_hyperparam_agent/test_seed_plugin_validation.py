"""
Schema-level tests for ``HyperparamTuningInput.seed_plugin_path`` validation.

Phase 3 of docs/run_scoped_plugins.md introduces an optional plugin path that
the tuner copies into the per-run plugin directory at run start. The schema
validates (a) the file exists, (b) it declares a top-level
``PLUGIN_MODEL_TYPE = "..."`` string, and (c) that value equals ``model_type``.

Validation is AST-based (``ast.parse`` + walk) rather than import-based so
that a malformed or hostile seed plugin cannot execute code at validation
time and cannot pollute ``sys.modules`` before the tuner has even started.
Each test writes a small fixture into ``tmp_path`` and feeds its path through
``HyperparamTuningInput.model_validate``.
"""
import sys
import textwrap
import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningInput


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_input_dict():
    """Valid input skeleton. Tests override ``model_type`` / add
    ``seed_plugin_path`` as needed."""
    return {
        "model_type":    "attn_fcnet",
        "file_index":    6,
        "max_rounds":    3,
        "expert_advice": "",
        "llm_provider":  "gemini",
        "llm_model_id":  "gemini-3.1-flash-lite-preview",
        "storage": {
            "backend": "local",
            "local": {"workspace": "./workspace", "run_name": "v1"},
        },
        "progress_bar":  False,
    }


def _write_plugin(tmp_path, filename: str, body: str) -> str:
    """Write ``body`` to ``tmp_path / filename`` and return the path."""
    path = tmp_path / filename
    path.write_text(textwrap.dedent(body))
    return str(path)


_VALID_PLUGIN_BODY = '''
    """Minimal valid plugin fixture."""
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "attn_fcnet"

    class PLUGIN_CONFIG_CLASS(BaseModel):
        segmentation_size: int = 10000

    class PLUGIN_MODEL_CLASS:  # stand-in for nn.Module
        pass
'''


# ---------------------------------------------------------------------------
# TestSeedPluginPathValidator
# ---------------------------------------------------------------------------

class TestSeedPluginPathValidator:

    def test_none_is_ok(self, base_input_dict):
        """Default (unset) seed_plugin_path must validate — this is the
        built-in-seed path used by every pre-Phase-3 caller."""
        agent_input = HyperparamTuningInput.model_validate(base_input_dict)
        assert agent_input.seed_plugin_path is None

    def test_valid_plugin_passes(self, tmp_path, base_input_dict):
        path = _write_plugin(tmp_path, "attn_fcnet_plugin.py", _VALID_PLUGIN_BODY)
        base_input_dict["seed_plugin_path"] = path
        agent_input = HyperparamTuningInput.model_validate(base_input_dict)
        assert agent_input.seed_plugin_path == path

    def test_missing_file_raises(self, tmp_path, base_input_dict):
        base_input_dict["seed_plugin_path"] = str(tmp_path / "does_not_exist.py")
        with pytest.raises(ValidationError, match="does not exist"):
            HyperparamTuningInput.model_validate(base_input_dict)

    def test_directory_path_raises(self, tmp_path, base_input_dict):
        # A directory is not a file — must be rejected.
        base_input_dict["seed_plugin_path"] = str(tmp_path)
        with pytest.raises(ValidationError, match="does not exist or is not a file"):
            HyperparamTuningInput.model_validate(base_input_dict)

    def test_model_type_mismatch_raises(self, tmp_path, base_input_dict):
        """Plugin's PLUGIN_MODEL_TYPE must equal the tuner's model_type;
        otherwise the training subprocess would register the seed under the
        wrong key."""
        path = _write_plugin(
            tmp_path,
            "seed.py",
            '''
                PLUGIN_MODEL_TYPE = "some_other_type"
                class PLUGIN_CONFIG_CLASS: ...
                class PLUGIN_MODEL_CLASS: ...
            ''',
        )
        base_input_dict["seed_plugin_path"] = path
        # model_type stays "attn_fcnet"; plugin declares "some_other_type"
        with pytest.raises(ValidationError, match="PLUGIN_MODEL_TYPE"):
            HyperparamTuningInput.model_validate(base_input_dict)

    def test_missing_plugin_model_type_raises(self, tmp_path, base_input_dict):
        """File without a top-level PLUGIN_MODEL_TYPE string is rejected."""
        path = _write_plugin(
            tmp_path,
            "bad_seed.py",
            '''
                # Intentionally no PLUGIN_MODEL_TYPE here.
                class PLUGIN_CONFIG_CLASS: ...
                class PLUGIN_MODEL_CLASS: ...
            ''',
        )
        base_input_dict["seed_plugin_path"] = path
        with pytest.raises(ValidationError, match="does not declare a top-level"):
            HyperparamTuningInput.model_validate(base_input_dict)

    def test_plugin_model_type_non_string_raises(self, tmp_path, base_input_dict):
        """PLUGIN_MODEL_TYPE must be a string constant — not an int, list, etc."""
        path = _write_plugin(
            tmp_path,
            "non_string.py",
            '''
                PLUGIN_MODEL_TYPE = 42
                class PLUGIN_CONFIG_CLASS: ...
                class PLUGIN_MODEL_CLASS: ...
            ''',
        )
        base_input_dict["seed_plugin_path"] = path
        with pytest.raises(ValidationError, match="does not declare a top-level"):
            HyperparamTuningInput.model_validate(base_input_dict)

    def test_syntax_error_raises(self, tmp_path, base_input_dict):
        path = _write_plugin(
            tmp_path,
            "broken.py",
            '''
                PLUGIN_MODEL_TYPE = "attn_fcnet"
                def oops(
            ''',
        )
        base_input_dict["seed_plugin_path"] = path
        with pytest.raises(ValidationError, match="not valid Python"):
            HyperparamTuningInput.model_validate(base_input_dict)

    def test_validator_does_not_import_the_plugin(
        self, tmp_path, base_input_dict
    ):
        """Regression guard: validation must be AST-only. Importing the seed
        would execute its top-level code and register it in ``sys.modules``
        before the tuner has even constructed its sandbox — which is exactly
        the kind of side effect the run-scoped design is trying to prevent."""
        path = _write_plugin(
            tmp_path, "isolated_plugin.py", _VALID_PLUGIN_BODY
        )
        base_input_dict["seed_plugin_path"] = path

        # Scrub any lingering entries from previous runs so the assertion is
        # meaningful.
        stem = "isolated_plugin"
        for key in list(sys.modules):
            if key.endswith(stem):
                sys.modules.pop(key, None)

        HyperparamTuningInput.model_validate(base_input_dict)

        for key in sys.modules:
            assert not key.endswith(stem), (
                f"Validator imported the seed plugin as {key!r} — it must "
                f"stay AST-only."
            )
