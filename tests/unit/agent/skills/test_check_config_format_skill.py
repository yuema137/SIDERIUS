"""Regressions for the public configuration-format skill boundary."""

from agent.skills.check_config_format_skill import wrapper
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.tuner_prompt_fixtures import planner_kwargs


def test_wrapper_preserves_public_envelope_and_schema_keys() -> None:
    result = wrapper.run_skill(object())

    assert set(result) == {"status", "message", "data"}
    assert result["status"] == "success"
    assert set(result["data"]) == {"schemas", "quick_notes"}
    assert set(result["data"]["schemas"]) == {
        "PUNetConfig",
        "AEConfig",
        "TransformerConfig",
        "LossConfig",
        "TrainConfig",
    }


def test_quick_notes_defer_semantics_to_resolved_authorities() -> None:
    notes = wrapper.run_skill(None)["data"]["quick_notes"]

    assert "schemas define configuration format" in notes
    assert "resolved task contracts" in notes
    assert "execution validators" in notes
    assert "model/loss compatibility" in notes
    assert "output shape" in notes
    assert "class cardinality" in notes
    assert "segmentation legality" in notes
    assert "resource limits" in notes

    stale_claims = ("smooth_l1", "FCNet", "PUNet", "Transformer", "256", "20,000", "128")
    assert not any(claim in notes for claim in stale_claims)


def test_non_256_task_reaches_planner_without_fixed_class_claim() -> None:
    """A foreign class count must not be contradicted at the real prompt seam."""
    bridge = BoundaryRecorderBridge()
    kwargs = planner_kwargs()
    kwargs["task_description"] = "A synthetic 37-class supervised task."
    kwargs["config_manual"] = wrapper.run_skill(None)["data"]

    bridge.plan(**kwargs)

    assert len(bridge.captures) == 1
    _, label, system_prompt, user_prompt = bridge.captures[0]
    assert label == "tuner.planner"
    assert "37-class supervised task" in system_prompt
    assert "resolved task contracts" in user_prompt
    assert "256 classes" not in user_prompt
