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

import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.prompt_rendering import PromptRenderingProfile, bind_prompt_profile
from agent.prompt_templates.attempt_history import RepairExhaustedError, earlier_attempts_block
from nodes.ml_model_proposal_agent.stage_validation import earlier_response_errors
from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tuning_output,
    _make_validator_output,
)
from workflows.model_exploration import _proposal_attempt_failure, run_workflow
from workflows.proposal_failure_feedback import (
    exhausted_validation_feedback,
    implementation_error_feedback,
    next_attempt_validation_feedback,
    repair_exhausted_entry,
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
        assert str(
            RepairExhaustedError(
                "Code generation",
                "m",
                "E",
                [],
                source_heading="The assembled plugin source",
                source="S",
            )
        ) == (
            "Code generation failed after 1 attempts for 'm': E\n\nThe assembled plugin source:\nS"
        )

    pinned = _profile(tmp_path, {"proposal.failure_attempt_history": lambda **_: ""})
    with bind_prompt_profile(pinned):
        assert exhausted_validation_feedback([(1, "V1"), (2, "V2")]) == "V2"
        assert implementation_error_feedback("Node error: X", [(1, "V1")]) == "Node error: X"
        # #1553 retry requests restore their pre-#1553 text as well.
        assert next_attempt_validation_feedback([(1, "V1"), (2, "V2")]) == "V2"
        assert earlier_response_errors([(1, "E1")], "E2") == ""
        assert str(
            RepairExhaustedError(
                "Loss generation",
                "l",
                "E3",
                [(1, "E1"), (2, "E2")],
                source_heading="The assembled loss source",
                source="S",
            )
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
            RepairExhaustedError(
                "Code generation",
                "candidate",
                "IMPL-ERR",
                [],
                source_heading="The assembled plugin source",
                source="PLUGIN-SOURCE",
            ),
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
        "Node error: ValueError: Code generation failed after 1 attempts for 'candidate': "
        f"IMPL-ERR\n\n{_HEADING}\n  Implementation attempt 1: V3",
    ]


def test_next_attempt_feedback_keeps_every_earlier_rejection():
    """#1553: fails if the next implementation attempt sees only the latest
    rejection; the first retry keeps its pre-#1553 text."""
    assert next_attempt_validation_feedback([]) is None
    assert next_attempt_validation_feedback([(1, "V1")]) == "V1"
    assert next_attempt_validation_feedback([(1, "V1"), (2, "V2")]) == (
        f"V2\n\n{_HEADING}\n  Implementation attempt 1: V1"
    )


def test_run_workflow_gives_each_implementation_attempt_all_earlier_rejections(tmp_path):
    """Reachability: within one proposal, implementation attempt 3 must receive
    both earlier rejections. Fails if ``run_workflow`` passes only the latest."""
    workspace = str(tmp_path / "ws")
    os.makedirs(workspace)
    composition = compose_run_task_bindings(str(QUICKSTART))
    rejections = [
        _make_validator_output(passed=False).model_copy(update={"error_message": text})
        for text in ("V1", "V2")
    ]
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
        implementor.return_value.run.return_value = _make_implementor_output(model_type="candidate")
        validator.return_value.run.side_effect = [*rejections, _make_validator_output(passed=True)]
        tuner.return_value.run.return_value = _make_tuning_output(
            model_type="candidate", fingerprint=composition.semantic_fingerprint
        ).model_copy(update={"metric_spec": composition.metric.spec})
        run_workflow(
            launch=WorkflowLaunchConfig(
                source_paths=[],
                max_iterations=1,
                start_iteration=1,
                max_proposal_attempts=1,
                max_impl_attempts=3,
                data_dir=workspace,
            ),
            workspace=workspace,
            run_name="rejection_history",
            llm_config=_llm_config_pseudo(),
            task_composition=composition,
        )
        inputs = [call.args[0] for call in implementor.return_value.run.call_args_list]

    assert [item.previous_validation_failure for item in inputs] == [
        None,
        "V1",
        f"V2\n\n{_HEADING}\n  Implementation attempt 1: V1",
    ]


# ---------------------------------------------------------------------------
# #1554 — the proposer entry carries the cause, not the assembled source
# ---------------------------------------------------------------------------

_SOURCE = "\n".join(f"source line {n}" for n in range(1, 41))


def _exhausted(final_error, history=(), source=_SOURCE):
    return RepairExhaustedError(
        "Code generation",
        "m",
        final_error,
        list(history),
        source_heading="The assembled plugin source",
        source=source,
    )


def test_exhausted_repair_entry_drops_the_source_and_keeps_the_cause():
    """#1554: fails if the entry still embeds the assembled source, or loses
    the headline, the earlier-attempt block or the ``Node error: ValueError:``
    label; ``str()`` must keep the full text for logs."""
    exc = _exhausted("E2 shape mismatch", [(1, "E1 name 'x' is not defined")])
    entry = _proposal_attempt_failure(exc)
    assert entry == (
        "Node error: ValueError: Code generation failed after 2 attempts for 'm': "
        "E2 shape mismatch\n\nEarlier attempt errors (oldest first):\n"
        "  Attempt 1: E1 name 'x' is not defined"
    )
    assert "source line" not in entry and "The assembled plugin source" not in entry
    assert str(exc).endswith(f"The assembled plugin source:\n{_SOURCE}")
    # Any other node exception keeps the generic label and its own text.
    assert _proposal_attempt_failure(ValueError("boom")) == "Node error: ValueError: boom"


def test_entry_quotes_only_the_source_lines_the_final_error_names():
    """Location and key lines survive, bounded: at most three SyntaxError
    locations, each with one line of context and cut to 160 characters;
    out-of-range or repeated locations add nothing. Fails if the excerpt grows
    with the source, ignores the error's own location, quotes a line for a
    "line N" that is not a location in this source, or counts lines
    differently from Python."""
    long_line = "x" * 300
    source = "\n".join([*(f"l{n}" for n in range(1, 10)), long_line, "l11", "l12"])
    error = (
        "invalid syntax (<unknown>, line 10); also (<unknown>, line 2), (<unknown>, line 2), "
        "(plugin_1.py, line 5), (<unknown>, line 7) and (<unknown>, line 99)"
    )
    entry = repair_exhausted_entry(_exhausted(error, source=source))
    excerpt = entry.split("\n\n", 1)[1]
    assert excerpt.splitlines() == [
        "Source lines named by the final error:",
        "     9 | l9",
        f"  > 10 | {'x' * 160}",
        "    11 | l11",
        "     1 | l1",
        "  >  2 | l2",
        "     3 | l3",
        "     4 | l4",
        "  >  5 | l5",
        "     6 | l6",
    ]
    # No SyntaxError location: a JSON decode position or a bare "line N" is not
    # a line of the plugin, so nothing is quoted.
    for unrelated in ("no location here", "Expecting value: line 1 column 1 (char 0)"):
        assert repair_exhausted_entry(_exhausted(unrelated)).endswith(unrelated)
    # Adjacent locations share context lines; each line is printed once.
    adjacent = repair_exhausted_entry(
        _exhausted("bad (<unknown>, line 2) and (<unknown>, line 3)", source=source)
    )
    assert adjacent.split("\n\n", 1)[1].splitlines()[1:] == [
        "     1 | l1",
        "  >  2 | l2",
        "  >  3 | l3",
        "     4 | l4",
    ]
    # Python counts lines at \r\n, \r and \n only; a form feed inside line 2
    # must not shift the real SyntaxError's line 3 (str.splitlines would).
    feed_source = "a = 1\nb = '\x0c'\nc = (\nd = 2\n"
    with pytest.raises(SyntaxError) as raised:
        ast.parse(feed_source)
    feed = repair_exhausted_entry(_exhausted(str(raised.value), source=feed_source))
    assert feed.split("\n\n", 1)[1].split("\n")[1:] == [
        "    2 | b = '\x0c'",
        "  > 3 | c = (",
        "    4 | d = 2",
    ]


def test_profile_restores_the_pre_1554_entry_bytes(tmp_path):
    """The siderius-exp pin: a profile whose ``proposal.failure_cause``
    renderer appends the source heading and source reproduces the old entry,
    ``Node error: ValueError: <full exception text>``, byte for byte."""
    pinned = _profile(
        tmp_path,
        {
            "proposal.failure_cause": lambda cause, final_error, source_heading, source: (
                f"{cause}\n\n{source_heading}:\n{source}"
            ),
            "proposal.failure_attempt_history": lambda **_: "",
        },
    )
    with bind_prompt_profile(pinned):
        exc = _exhausted("E2 at line 3", [(1, "E1")])
        assert repair_exhausted_entry(exc) == f"Node error: ValueError: {exc}"


def test_repair_exhausted_error_survives_pickling():
    """A raise inside a process pool is pickled; the custom signature would
    otherwise fail to rebuild the exception and hide the real failure."""
    import pickle

    exc = _exhausted("E at line 1", [(1, "E0")])
    copy = pickle.loads(pickle.dumps(exc))
    assert (str(copy), copy.cause, copy.source) == (str(exc), exc.cause, exc.source)
