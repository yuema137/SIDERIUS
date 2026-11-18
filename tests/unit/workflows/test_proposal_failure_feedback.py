"""Proposer feedback keeps every earlier attempt's cause (#1538, user report #1530).

What only these tests catch:

* the shared earlier-attempt block stays bounded by distinct causes (a long
  history of one repeated error is one line, never N copies) and keeps the
  chronological order of first occurrence;
* the native loop's per-proposal entry carries every validation rejection,
  including those recorded before an implementor exception ended the
  proposal; the production ``run_workflow`` path reaches the helpers;
* an experiment profile bound to ``proposal.failure_attempt_history`` that
  returns ``""`` reproduces the pre-#1538 strings byte for byte (the
  siderius-exp pin), and a single-attempt failure never enters the boundary.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from agent.prompt_rendering import PromptRenderingProfile, bind_prompt_profile
from agent.prompt_templates.attempt_history import earlier_attempts_block
from nodes.ml_model_implementor.ml_model_implementor import _repair_exhausted_message
from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tuning_output,
    _make_validator_output,
)
from workflows.model_exploration import run_workflow
from workflows.proposal_failure_feedback import (
    exhausted_validation_feedback,
    implementation_error_feedback,
)
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"
_HEADING = "Earlier implementation attempts for this proposal failed validation (oldest first):"


def _profile(tmp_path, renderers):
    source = tmp_path / "provider.txt"
    source.write_text("fixed paper-style provider")
    return PromptRenderingProfile("paper-style", "1", renderers, frozenset(), {"source": source})


def test_repeated_causes_collapse_in_first_occurrence_order():
    """Fails if a long history repeats one error per attempt (unbounded growth
    for a large retry budget) or if the order stops being chronological."""
    block = earlier_attempts_block(
        [(1, "A"), (2, "B"), (3, "A"), (4, "C")], "C", heading="H:", unit="Attempt"
    )
    assert block == (
        "H:\n  Attempts 1, 3: A\n  Attempt 2: B\n  Attempt 4: same error as the final attempt"
    )


def test_exhausted_proposal_entry_keeps_every_rejection():
    """Fails if exhaustion reports only the last validator rejection (#1538)."""
    entry = exhausted_validation_feedback([(1, "V1"), (2, "V2"), (3, "V3")])
    assert entry == (
        f"V3\n\n{_HEADING}\n  Implementation attempt 1: V1\n  Implementation attempt 2: V2"
    )
    assert exhausted_validation_feedback([(1, "only")]) == "only"
    assert exhausted_validation_feedback([]) == "Unknown error"


def test_exception_entry_keeps_rejections_recorded_before_it():
    """Fails if an implementor exception hides the earlier validator rejection."""
    entry = implementation_error_feedback("Node error: ValueError: boom", [(1, "V1")])
    assert entry == f"Node error: ValueError: boom\n\n{_HEADING}\n  Implementation attempt 1: V1"
    assert implementation_error_feedback("Node error: X", []) == "Node error: X"


def test_profile_returning_empty_restores_pre_1538_bytes(tmp_path):
    """The siderius-exp pin: with the boundary rendering ``""``, every failure
    string equals its pre-#1538 form. An undeclared profile is never asked for
    a single-attempt failure. Fails if a caller adds separators around an empty
    block or enters the boundary without an earlier attempt."""
    with bind_prompt_profile(_profile(tmp_path, {})):
        assert exhausted_validation_feedback([(1, "V1")]) == "V1"
        assert _repair_exhausted_message(
            "Code generation",
            "m",
            "E",
            [],
            source_heading="The assembled plugin source",
            source="S",
        ) == (
            "Code generation failed after 1 attempts for 'm': E\n\nThe assembled plugin source:\nS"
        )

    pinned = _profile(tmp_path, {"proposal.failure_attempt_history": lambda **_: ""})
    with bind_prompt_profile(pinned):
        assert exhausted_validation_feedback([(1, "V1"), (2, "V2")]) == "V2"
        assert implementation_error_feedback("Node error: X", [(1, "V1")]) == "Node error: X"
        assert _repair_exhausted_message(
            "Loss generation",
            "l",
            "E3",
            [(1, "E1"), (2, "E2")],
            source_heading="The assembled loss source",
            source="S",
        ) == (
            "Loss generation failed after 3 attempts for 'l': E3\n\nThe assembled loss source:\nS"
        )


def test_run_workflow_feeds_every_rejection_to_the_next_proposal(tmp_path):
    """Reachability through the production loop: proposal 1 exhausts two
    rejected implementations, proposal 2 is rejected once and then its
    implementor raises, proposal 3 passes. Fails if ``run_workflow`` drops the
    earlier rejections from either kind of ``previous_failures`` entry."""
    workspace = str(tmp_path / "ws")
    os.makedirs(workspace)
    composition = compose_run_task_bindings(str(QUICKSTART))
    rejections = [
        _make_validator_output(passed=False).model_copy(update={"error_message": text})
        for text in ("V1", "V2", "V3")
    ]
    output = _make_implementor_output(model_type="candidate")
    with (
        bind_run_task_composition(composition, physical_data_root=workspace),
        patch("workflows.model_exploration.ResultInterpretationAgent") as interp,
        patch("workflows.model_exploration.MLModelProposalAgent") as proposer,
        patch("workflows.model_exploration.MLModelImplementor") as implementor,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as validator,
        patch("workflows.model_exploration.HyperparamTuningAgent") as tuner,
    ):
        interp.return_value.run.return_value = _make_interpretation_output()
        proposer.return_value.run.return_value = _make_proposal_output(model_name="candidate")
        implementor.return_value.run.side_effect = [
            output,
            output,
            output,
            ValueError("IMPL-ERR"),
            output,
        ]
        validator.return_value.run.side_effect = [*rejections, _make_validator_output(passed=True)]
        tuner.return_value.run.return_value = _make_tuning_output(
            model_type="candidate", fingerprint=composition.semantic_fingerprint
        ).model_copy(update={"metric_spec": composition.metric.spec})
        run_workflow(
            launch=WorkflowLaunchConfig(
                source_paths=[],
                max_iterations=1,
                start_iteration=1,
                max_proposal_attempts=3,
                max_impl_attempts=2,
                data_dir=workspace,
            ),
            workspace=workspace,
            run_name="failure_feedback",
            llm_config=_llm_config_pseudo(),
            task_composition=composition,
        )
        calls = proposer.return_value.run.call_args_list

    assert len(calls) == 3
    assert calls[2].args[0].previous_failures == [
        f"V2\n\n{_HEADING}\n  Implementation attempt 1: V1",
        f"Node error: ValueError: IMPL-ERR\n\n{_HEADING}\n  Implementation attempt 1: V3",
    ]
