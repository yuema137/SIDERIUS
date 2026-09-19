"""Formal-only failure must cross process restart without promoting a candidate."""

import json
from unittest.mock import MagicMock

import pytest

from agent.schemas.interpretation import InterpretationInput
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
    local_full_context as propose_input,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.resume import ResumeError, restore_prior_state
from nodes.ml_hyperparameter_tune_agent.feedback import _build_formal_validity_feedback
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import _build_reasoning_prompt
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.unit.agent.tune_ml_hyperparam_agent.test_trial_validity_feedback import (
    BLOCKING_IDS,
    _trial,
)
from tests.unit.sdsc_submission_scripts.test_run_one_iteration import _StubResult
from workflows.run_one_iteration import write_manifest


def _feedback(*, passed=False, explicit_role=True):
    record = _trial(
        "formal-candidate",
        status="failed_mode_collapse",
        passed=passed,
        metrics={"dominant_fraction": 0.99},
    )
    if explicit_role:
        record["is_trial"] = False
    else:
        record.pop("is_trial", None)
    if passed:
        record["status"] = "success"
    return _build_formal_validity_feedback(
        [record],
        model_type="synthetic_model",
        healthgate_mode="blocking",
        required_gate_ids=frozenset(BLOCKING_IDS),
    )


@pytest.mark.parametrize("explicit_role", [False, True], ids=["stored-omission", "explicit-false"])
def test_failed_formal_manifest_to_next_interpreter_and_proposer(tmp_path, explicit_role):
    """Fails on the observed no_records loss, cold-start lie or missing prompt edge."""
    # 2026-09-19 diagnostic E: the production writer omits is_trial for Formal.
    # Testing only already-normalized output records hid the lost feedback.
    feedback = _feedback(explicit_role=explicit_role)
    assert feedback is not None
    assert feedback.invalid_count == 1 and feedback.execution_failure_count == 0
    output = _StubResult("synthetic_model", score=None, all_records=[])
    output.formal_validity_feedback = feedback
    write_manifest(str(tmp_path / "iter_001"), "iter_001", [output])
    restored = restore_prior_state(str(tmp_path), 2, [])
    assert restored.resolved_source_paths == []
    assert restored.restored_plugins == []
    assert restored.committed_iters == []
    assert restored.chain_best_valid_formal_score is None
    assert restored.accumulated_formal_feedback == [feedback]
    storage = StorageConfig(local=LocalStorageConfig(workspace=str(tmp_path), run_name="iter_002"))
    bridge = MagicMock()
    interpretation = ResultInterpretationAgent(bridge_factory=lambda **kwargs: bridge).run(
        InterpretationInput(
            cold_start=True,
            storage=storage,
            recent_formal_validity=restored.accumulated_formal_feedback,
        )
    )
    bridge.generate.assert_not_called()
    assert "no prior experimental evidence" not in interpretation.take_home_message
    assert "dominant_fraction" in " ".join(interpretation.key_findings)
    proposal = propose_input(
        interpretation, storage=storage, recent_formal_validity=restored.accumulated_formal_feedback
    )
    prompt = _build_reasoning_prompt(proposal)
    assert "RECENT FORMAL VALIDITY" in prompt
    assert "formal-candidate" in prompt and "0.99" in prompt
    assert proposal.recent_trial_validity == []


def test_valid_formal_does_not_emit_failure_feedback():
    """Prevents treating a scientific success as failure evidence."""
    assert _feedback(passed=True) is None


def test_malformed_formal_feedback_is_refused_on_restore(tmp_path):
    """Untrusted manifest feedback must not bypass the typed process boundary."""
    directory = tmp_path / "iter_001"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "status": "no_records",
                "iteration_dir": str(directory),
                "output_path": None,
                "negative_feedback": {"formal_validity_feedback": {"model_type": "forged"}},
            }
        )
    )
    with pytest.raises(ResumeError, match="invalid Formal feedback"):
        restore_prior_state(str(tmp_path), 2, [])


@pytest.mark.usefixtures("synthetic_dataset_profile")
def test_formal_failure_reaches_pipeline_proposing_call(tmp_path):
    """The pipeline and legacy proposer must both consume the same failed evidence."""
    from tests.unit.agent.ml_model_proposal_agent.test_pipeline_runner import (
        TestPipelineRunner as PipelineHarness,
    )

    harness = PipelineHarness()
    agent, bridge = harness._make_agent_with_mock()
    inp = harness._make_pipeline_input(tmp_path)
    feedback = _feedback()
    assert feedback is not None
    inp.recent_formal_validity = [feedback]
    agent.run(inp)
    last_call = bridge.generate.call_args_list[-1]
    text = " ".join(str(item) for item in last_call.args) + str(last_call.kwargs)
    assert "RECENT FORMAL VALIDITY" in text
    assert "formal-candidate" in text and "dominant_fraction" in text


def test_analysis_brief_receives_failed_formal_facts_in_cold_start(tmp_path):
    """DA question generation must not erase failed evidence when no incumbent exists."""
    from tests.unit.agent.result_interpretation_agent.test_analysis_brief_generation import (
        _BriefBridge,
        _cold_input,
    )

    feedback = _feedback()
    assert feedback is not None
    inp = _cold_input(tmp_path, requested=True).model_copy(
        update={"recent_formal_validity": [feedback]}
    )
    bridge = _BriefBridge(
        {"questions": [{"question": "What authorized input scales were observed?", "priority": 1}]}
    )
    ResultInterpretationAgent(bridge_factory=lambda **kwargs: bridge).run(inp)
    evidence = json.loads(bridge.calls[0][2])["interpretation_evidence"]
    assert evidence["failed_formal_attempts"][0]["invalid_count"] == 1
    assert "No prior experimental evidence exists" not in evidence["statement"]
