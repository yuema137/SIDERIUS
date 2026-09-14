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

from core.capability_registry import CapabilityMetadata
from core.run_invariants import RUN_INVARIANTS_BASENAME
from core.runtime_control.construction_memory import CandidateAdmissionError
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
    def test_construction_refusal_retries_before_candidate_state_is_committed(self, tmp_path):
        """Regression for the rc.3 TIDMAD failure.

        This fails if admission moves after any candidate registry, staging,
        or promotion effect, or if its typed refusal no longer reaches the
        next proposer's ``previous_failures``.
        """
        workspace = str(tmp_path / "construction-admission")
        os.makedirs(workspace)
        composition = compose_run_task_bindings(str(QUICKSTART))
        refusal = CandidateAdmissionError(
            "0.75 GiB unexplained constructor memory",
            model_name="candidate",
        )

        with (
            bind_run_task_composition(composition, physical_data_root=workspace),
            patch("workflows.model_exploration.ResultInterpretationAgent") as interp,
            patch("workflows.model_exploration.MLModelProposalAgent") as proposer,
            patch("workflows.model_exploration.MLModelImplementor") as implementor,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as validator,
            patch("workflows.model_exploration.HyperparamTuningAgent") as tuner,
            patch(
                "workflows.model_exploration._admit_generated_model_construction",
                side_effect=[refusal, None],
            ) as admit,
            patch("workflows.model_exploration._register_plugin") as stage,
            patch("workflows.model_exploration._promote_model_to_global") as promote_model,
            patch("workflows.model_exploration._promote_loss_to_global") as promote_loss,
            patch("core.capability_registry.CapabilityRegistry.register") as register_capability,
            patch("workflows.model_exploration.register_model_in_memory") as register_memory,
        ):
            interp.return_value.run.return_value = _make_interpretation_output()
            proposer.return_value.run.return_value = _make_proposal_output(model_name="candidate")
            metadata = CapabilityMetadata(
                name="candidate",
                capability_type="model",
                file_path=str(tmp_path / "candidate.py"),
                created_at="2026-09-14T00:00:00+00:00",
                source_iteration="iter_001",
                description="Construction-admission regression candidate.",
                mathematical_definition="y = f(x)",
            )
            loss_metadata = CapabilityMetadata(
                name="candidate_loss",
                capability_type="loss",
                file_path=str(tmp_path / "candidate_loss.py"),
                created_at="2026-09-14T00:00:00+00:00",
                source_iteration="iter_001",
                description="Attempt-local generated loss.",
                mathematical_definition="L = |y - y_hat|",
            )
            implementor.return_value.run.return_value = _make_implementor_output(
                model_type="candidate"
            ).model_copy(
                update={
                    "capability_metadata": metadata,
                    "loss_capability_metadata": loss_metadata,
                }
            )
            validator.return_value.run.return_value = _make_validator_output(passed=True)
            tuner.return_value.run.return_value = _make_tuning_output(
                model_type="candidate",
                fingerprint=composition.semantic_fingerprint,
            ).model_copy(update={"metric_spec": composition.metric.spec})

            run_workflow(
                launch=WorkflowLaunchConfig(
                    source_paths=[],
                    max_iterations=1,
                    start_iteration=1,
                    max_proposal_attempts=2,
                    data_dir=workspace,
                ),
                workspace=workspace,
                run_name="construction_admission",
                llm_config=_llm_config_pseudo(),
                task_composition=composition,
            )

        assert admit.call_count == 2
        assert proposer.return_value.run.call_count == 2
        failures = proposer.return_value.run.call_args_list[1].args[0].previous_failures
        assert any("CandidateAdmissionError" in item and "0.75 GiB" in item for item in failures)
        assert stage.call_count == 1
        assert promote_model.call_count == 1
        assert promote_loss.call_count == 2  # early commit plus idempotent end-of-round safety net
        assert [call.args[0].capability_type for call in register_capability.call_args_list] == [
            "loss",
            "model",
        ]
        assert register_memory.call_count == 1

    def test_exhausted_construction_refusals_never_tune_a_stale_valid_candidate(self, tmp_path):
        """A passed validator result is not sufficient after admission refuses.

        This fails if the attempt loop reuses the previous ``validation``
        object and tunes a candidate that never passed construction admission.
        """
        workspace = str(tmp_path / "construction-exhausted")
        os.makedirs(workspace)
        composition = compose_run_task_bindings(str(QUICKSTART))
        refusal = CandidateAdmissionError("unexplained memory", model_name="candidate")

        with (
            bind_run_task_composition(composition, physical_data_root=workspace),
            patch("workflows.model_exploration.ResultInterpretationAgent") as interp,
            patch("workflows.model_exploration.MLModelProposalAgent") as proposer,
            patch("workflows.model_exploration.MLModelImplementor") as implementor,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as validator,
            patch("workflows.model_exploration.HyperparamTuningAgent") as tuner,
            patch(
                "workflows.model_exploration._admit_generated_model_construction",
                side_effect=refusal,
            ),
            patch("workflows.model_exploration._register_plugin") as stage,
        ):
            interp.return_value.run.return_value = _make_interpretation_output()
            proposer.return_value.run.return_value = _make_proposal_output(model_name="candidate")
            implementor.return_value.run.return_value = _make_implementor_output(
                model_type="candidate"
            )
            validator.return_value.run.return_value = _make_validator_output(passed=True)

            run_workflow(
                launch=WorkflowLaunchConfig(
                    source_paths=[],
                    max_iterations=1,
                    start_iteration=1,
                    max_proposal_attempts=2,
                    data_dir=workspace,
                ),
                workspace=workspace,
                run_name="construction_exhausted",
                llm_config=_llm_config_pseudo(),
                task_composition=composition,
            )

        assert proposer.return_value.run.call_count == 2
        stage.assert_not_called()
        tuner.return_value.run.assert_not_called()

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
