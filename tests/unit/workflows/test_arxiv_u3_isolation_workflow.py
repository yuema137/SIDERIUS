"""arXiv U3 (#260) — baseline isolation through the workflow.

What only these tests catch:

* the refusal authority's semantics — a built-in candidate (named directly
  or as a reuse target) is refused fail-closed and NAMED under isolation,
  and untouched otherwise;
* REACHABILITY — the production ``run_workflow`` path actually calls the
  authority BEFORE the implementor: a mocked proposer returning
  ``wavenet`` under isolation never reaches the implementor. The attempt
  loop's EXISTING generic handler converts the raise into NAMED retry
  feedback (``previous_failures``) and, after exhausting
  ``max_proposal_attempts``, the iteration ends with no candidate — fail
  closed, and the LLM is told exactly why. A helper nobody calls passes
  every unit test; only this fails when the call site is dropped;
* the flag reaches every consumer: the interpreter, proposer and tuner
  inputs carry ``baseline_isolation=True`` and the workspace lock pins it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.run_invariants import RUN_INVARIANTS_BASENAME
from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tuning_output,
    _make_validator_output,
)
from workflows.model_exploration import (
    BaselineIsolationViolation,
    refuse_builtin_proposal_under_isolation,
    run_workflow,
)
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"


class TestRefusalAuthority:
    def test_a_builtin_candidate_is_refused_and_named(self):
        with pytest.raises(BaselineIsolationViolation) as exc:
            refuse_builtin_proposal_under_isolation(
                _make_proposal_output(model_name="wavenet"), baseline_isolation=True
            )
        msg = str(exc.value)
        assert "wavenet" in msg and "baseline_isolation" in msg

    def test_a_builtin_reuse_target_is_refused_too(self):
        proposal = _make_proposal_output(model_name="fresh_tcn")
        proposal.baseline_config["model_config"]["model_name"] = "punet"
        with pytest.raises(BaselineIsolationViolation, match="punet"):
            refuse_builtin_proposal_under_isolation(proposal, baseline_isolation=True)

    def test_a_plugin_candidate_passes(self):
        refuse_builtin_proposal_under_isolation(
            _make_proposal_output(model_name="fresh_tcn"), baseline_isolation=True
        )

    def test_without_isolation_a_builtin_candidate_is_untouched(self):
        refuse_builtin_proposal_under_isolation(
            _make_proposal_output(model_name="punet"), baseline_isolation=False
        )


def _run(workspace: str, *, isolation: bool, proposal_name: str, out: dict | None = None):
    """Drive run_workflow with mocked agents; fill ``out`` (also returned)
    with the captured node inputs and call counts EVEN when the workflow
    raises, so a refusal can be shown to have preceded the implementor."""
    captured: dict = out if out is not None else {}
    composition = compose_run_task_bindings(str(QUICKSTART))

    with (
        bind_run_task_composition(composition, physical_data_root=workspace),
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockPropose.return_value.run.return_value = _make_proposal_output(model_name=proposal_name)
        MockImpl.return_value.run.return_value = _make_implementor_output(model_type=proposal_name)
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.return_value = _make_tuning_output(
            model_type=proposal_name, fingerprint=composition.semantic_fingerprint
        ).model_copy(update={"metric_spec": composition.metric.spec})
        try:
            run_workflow(
                launch=WorkflowLaunchConfig(
                    source_paths=[],
                    max_iterations=1,
                    start_iteration=1,
                    baseline_isolation=isolation,
                    data_dir=workspace,
                ),
                workspace=workspace,
                run_name="u3_iso",
                llm_config=_llm_config_pseudo(),
                task_composition=composition,
            )
        finally:
            captured["implementor_runs"] = MockImpl.return_value.run.call_count
            captured["propose_runs"] = MockPropose.return_value.run.call_count
            captured["propose_inputs"] = [
                c.args[0] for c in MockPropose.return_value.run.call_args_list
            ]
            captured["propose_input"] = (
                MockPropose.return_value.run.call_args.args[0]
                if MockPropose.return_value.run.call_args
                else None
            )
            captured["interp_input"] = (
                MockInterp.return_value.run.call_args.args[0]
                if MockInterp.return_value.run.call_args
                else None
            )
            captured["tune_input"] = (
                MockTune.return_value.run.call_args.args[0]
                if MockTune.return_value.run.call_args
                else None
            )
    return captured


class TestWorkflowReachabilityAndThreading:
    def test_a_builtin_proposal_under_isolation_never_reaches_the_implementor(self, tmp_path):
        """The refusal fires inside the attempt loop, whose existing generic
        handler feeds the NAMED violation back to the next proposal attempt;
        after exhaustion the iteration ends candidate-less. Fail-closed: the
        implementor count is the load-bearing zero."""
        ws = str(tmp_path / "iso")
        os.makedirs(ws)
        out: dict = {}
        _run(ws, isolation=True, proposal_name="wavenet", out=out)
        assert out["implementor_runs"] == 0, (
            "the refusal must precede the implementor — a baseline was implemented"
        )
        assert out["propose_runs"] == 3, "every offending proposal must be refused, then retried"
        failures = out["propose_inputs"][-1].previous_failures
        assert any("BaselineIsolationViolation" in f and "wavenet" in f for f in failures), failures

    def test_the_flag_reaches_every_consumer_and_the_lock(self, tmp_path):
        ws = str(tmp_path / "iso3")
        os.makedirs(ws)
        captured = _run(ws, isolation=True, proposal_name="fresh_tcn")
        assert captured["interp_input"].baseline_isolation is True
        assert captured["propose_input"].baseline_isolation is True
        assert captured["tune_input"].baseline_isolation is True
        lock = json.loads((tmp_path / "iso3" / RUN_INVARIANTS_BASENAME).read_text())
        assert lock["baseline_isolation"] is True

    def test_without_isolation_nothing_changes_and_the_lock_omits_the_key(self, tmp_path):
        ws = str(tmp_path / "plain")
        os.makedirs(ws)
        captured = _run(ws, isolation=False, proposal_name="fresh_tcn")
        assert captured["interp_input"].baseline_isolation is False
        assert captured["propose_input"].baseline_isolation is False
        assert captured["tune_input"].baseline_isolation is False
        lock = json.loads((tmp_path / "plain" / RUN_INVARIANTS_BASENAME).read_text())
        assert "baseline_isolation" not in lock
