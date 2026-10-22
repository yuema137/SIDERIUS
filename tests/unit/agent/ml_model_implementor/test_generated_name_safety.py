"""#778: archival payloads remain readable, live names refuse before paid/effectful work."""

from unittest.mock import MagicMock

import pytest

from agent.schemas.custom_loss_validation import validate_custom_loss_plugin_or_raise_setup
from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import CustomLossSpec
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_model_implementor.ml_model_implementor import (
    _check_baseline_schema_compatibility,
    _smoke_test_plugin,
)


def request(tmp_path, **updates):
    fields = dict(
        model_name="safe_model",
        model_description="Synthetic model",
        mathematical_definition="y=x",
        baseline_config={"model_config": {"width": 4}, "loss_config": {"loss_type": "ce"}},
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        loss_dir=str(tmp_path / "losses"),
    )
    fields.update(updates)
    return ImplementorInput(**fields)


def loss_spec(name):
    return CustomLossSpec(
        loss_name=name,
        description="Synthetic loss",
        mathematical_definition="mean(abs(y-x))",
        config_fields={},
    )


@pytest.mark.parametrize("kind", ["model", "custom_loss", "reuse_model", "reuse_loss"])
def test_archival_decode_then_live_refusal_before_any_llm_or_loss_generation(tmp_path, kind):
    inp = request(tmp_path)
    if kind == "model":
        inp.model_name = "../escape"
    elif kind == "custom_loss":
        inp.custom_loss_spec = loss_spec("../escape")
    elif kind == "reuse_model":
        inp.baseline_config["model_config"]["model_name"] = "../escape"
        inp.custom_loss_spec = loss_spec("safe_loss")
    else:
        inp.baseline_config["loss_config"] = {"loss_type": "custom", "loss_name": "../escape"}
    restored = ImplementorInput.model_validate_json(inp.model_dump_json())
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge = MagicMock()
    agent._generate_loss = MagicMock()
    with pytest.raises(ValueError, match="filesystem component"):
        agent.run(restored)
    agent._generate_loss.assert_not_called()
    assert agent.bridge.mock_calls == []
    assert list(tmp_path.iterdir()) == []


def test_unused_legacy_loss_name_does_not_restrict_live_eligibility(tmp_path):
    inp = request(tmp_path)
    inp.baseline_config["loss_config"]["loss_name"] = "../unused"
    inp.validate_for_implementation()
    inp.custom_loss_spec = loss_spec("Safe-Loss.v2")
    inp.baseline_config["loss_config"] = {"loss_type": "custom", "loss_name": "../overridden"}
    inp.validate_for_implementation()


def test_direct_loss_generation_refuses_before_provider_or_inventory(tmp_path):
    inp = request(tmp_path, custom_loss_spec=loss_spec("../escape"))
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge = MagicMock()
    agent._registry = MagicMock()
    with pytest.raises(ValueError, match=r"custom_loss_spec\.loss_name"):
        agent._generate_loss(inp)
    assert agent.bridge.mock_calls == agent._registry.mock_calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("probe", ["smoke", "baseline", "loss"])
def test_direct_probe_refuses_before_temp_creation_or_pair_provider(monkeypatch, probe):
    # Removing a probe guard invokes this tripwire, even with otherwise benign source.
    import tempfile

    def forbidden(*args, **kwargs):
        pytest.fail("unsafe name reached probe effects")

    monkeypatch.setattr(tempfile, "mkdtemp", forbidden)
    if probe == "smoke":
        error = _smoke_test_plugin("# benign source", "../escape")
    elif probe == "baseline":
        error = _check_baseline_schema_compatibility(
            "# benign source", "../escape", {"model_config": {"width": 4}}
        )
    else:
        error = validate_custom_loss_plugin_or_raise_setup(
            "# benign source", "../escape", pair_provider=forbidden
        )
    assert error is not None and "filesystem component" in error
