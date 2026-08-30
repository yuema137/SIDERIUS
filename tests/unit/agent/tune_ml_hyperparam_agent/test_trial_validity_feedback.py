"""An iteration with no valid trial tells the next planner WHY.

V20 PR D, checkpoint D-C6.

Without this, an all-invalid iteration reaches the next proposer looking
exactly like an iteration that merely scored badly — the planner cannot
tell "the model collapsed and every gate rejected it" from "nothing ran"
from "it ran fine but scored low", and those call for different proposals.

**The distinctions are the point.** The report keeps apart:

- trial EXECUTION failure — the evidence is *absent*;
- trial HealthGate INVALIDITY — the evidence is *negative*;
- validity UNKNOWN — the gates could not judge it at all;
- formal skipped because no valid winner existed;
- formal skipped on the ordinary budget (a different carrier entirely).

Collapsing them into "trial failed" is the failure mode being prevented.

**Task-generic.** The report transports gate names, reasons and metrics
exactly as the gate system recorded them and states no remedy. What a
mode fraction implies for a particular task is the planner's judgement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent.schemas.health_feedback import TrialValidityFeedback
from execute_tools.health_checks.schemas import CandidateHealthValidity
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _build_trial_validity_feedback,
)
from tests.helpers.tuner_source import tuner_node_source

BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)


def _trial(exp_id, *, status="success", passed=None, metrics=None, gates=True):
    """A trial record. ``passed=None`` with ``gates=False`` omits verdicts,
    which is how validity becomes UNKNOWN rather than a pass."""
    record = {
        "exp_id": exp_id,
        "status": status,
        "is_trial": True,
        "denoising_score": 1.0,
        "memory": {"time_mode": "trial"},
    }
    if gates:
        record["health_gate_results"] = [
            {
                "gate_name": gate,
                "execution_status": "passed",
                "check_passed": passed,
                "would_invalidate_under_production_policy": passed is False,
                "failure_reason": None if passed else "mode_collapse",
                "key_metrics": metrics or {},
            }
            for gate in BLOCKING_IDS
        ]
    else:
        record["health_gate_results"] = []
    return record


def _build(records, *, skipped=False, mode="blocking"):
    return _build_trial_validity_feedback(
        records, formal_skipped_for_no_valid_winner=skipped, healthgate_mode=mode
    )


class TestWhenItFires:
    def test_all_trials_gate_invalid(self):
        result = _build([_trial("t1", passed=False), _trial("t2", passed=False)])
        assert result is not None
        assert result.trial_records_considered == 2
        assert result.invalid_count == 2

    def test_a_valid_trial_suppresses_it_entirely(self):
        """MUTATION TARGET: reporting on healthy runs.

        A run with a winner must leave the field None, so the downstream
        proposer prompt is byte-identical to before this checkpoint.
        """
        assert _build([_trial("bad", passed=False), _trial("good", passed=True)]) is None

    def test_no_trial_stage_at_all_is_a_different_fact(self):
        """An iteration that ran no trials is not an iteration whose trials
        all failed. Reporting the former would be a fabricated claim."""
        assert _build([]) is None
        assert _build([{"exp_id": "f", "status": "success", "is_trial": False}]) is None

    def test_run_scoped_gate_ids_are_used_without_default_resolution(self, monkeypatch):
        """A composed task must not reload the process-default Health config.

        This fails on the real DAVIS incident path if the feedback producer
        omits the already-resolved run-scoped gate set.
        """
        from execute_tools.health_checks import candidate_eligibility

        monkeypatch.setattr(
            candidate_eligibility,
            "required_blocking_gate_ids",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("default reloaded")),
        )
        record = {
            "exp_id": "custom-task-collapse",
            "status": "failed_mode_collapse",
            "is_trial": True,
            "health_gate_enabled": True,
            "health_gate_results": [
                {
                    "gate_name": "custom_task_gate",
                    "execution_status": "passed",
                    "check_passed": False,
                    "would_invalidate_under_production_policy": True,
                    "failure_reason": "collapsed",
                    "key_metrics": {},
                }
            ],
        }
        result = _build_trial_validity_feedback(
            [record],
            formal_skipped_for_no_valid_winner=True,
            healthgate_mode="blocking",
            required_gate_ids=frozenset({"custom_task_gate"}),
        )
        assert result.invalid_count == 1


class TestTheDistinctionsSurvive:
    def test_execution_failure_is_not_gate_invalidity(self):
        """THE CORE REQUIREMENT. A crash means the evidence is ABSENT; a
        gate failure means it is NEGATIVE. A planner told only 'trial
        failed' would fix the wrong thing."""
        result = _build(
            [_trial("crashed", status="error_training"), _trial("collapsed", passed=False)]
        )
        assert result.execution_failure_count == 1
        assert result.invalid_count == 1
        statuses = {o.exp_id: o.status for o in result.outcomes}
        assert statuses == {"crashed": "error_training", "collapsed": "success"}

    def test_durable_collapse_status_remains_gate_invalidity(self):
        """The persisted collapse status means execution reached HealthGate.

        This fails if status is classified before the run-scoped Health
        verdict, which would tell the next proposer that training crashed.
        """
        collapsed = _trial("collapsed", status="failed_mode_collapse", passed=False)
        result = _build([collapsed])
        assert result.invalid_count == 1
        assert result.execution_failure_count == 0

    def test_validity_unknown_is_not_invalidity(self):
        """Gates that could not judge are not gates that rejected."""
        result = _build([_trial("ungated", gates=False)])
        assert result.unknown_validity_count == 1
        assert result.invalid_count == 0
        assert result.outcomes[0].health_validity is CandidateHealthValidity.UNKNOWN

    def test_absent_evidence_is_named_rather_than_left_silent(self):
        """A partial gate set reads exactly like a pass unless said aloud."""
        result = _build([_trial("ungated", gates=False)])
        assert any("no gate results persisted" in e for e in result.evidence_absent)

    def test_a_no_winner_skip_is_distinguishable_from_a_budget_skip(self):
        """MUTATION TARGET: inferring the skip reason from the absence of a
        formal record — which cannot tell the two apart."""
        assert _build([_trial("t", passed=False)], skipped=True).formal_skipped_for_no_valid_winner
        assert not _build(
            [_trial("t", passed=False)], skipped=False
        ).formal_skipped_for_no_valid_winner


class TestTheFactsAreTransportedUnchanged:
    def test_failed_gate_names_and_reasons_come_from_the_gate_system(self):
        result = _build([_trial("t", passed=False)])
        outcome = result.outcomes[0]
        assert outcome.failed_gate_names == sorted(BLOCKING_IDS)
        assert outcome.failure_reasons == ["mode_collapse"]

    def test_measured_metrics_are_passed_through_namespaced(self):
        result = _build([_trial("t", passed=False, metrics={"mode_fraction": 0.994})])
        assert result.outcomes[0].key_metrics["output_diversity_blocking.mode_fraction"] == 0.994

    def test_nothing_task_specific_is_synthesised(self):
        """MUTATION TARGET: baking task remediation advice into the
        workflow layer. The report may carry only what the gates emitted."""
        import inspect

        from nodes.ml_hyperparameter_tune_agent import _build_trial_validity_feedback as fn

        src = inspect.getsource(fn)
        for forbidden in ("wavenet", "punet", "tidmad", "TIDMAD", "5.576", "try ", "consider "):
            assert forbidden not in src, f"task-specific content leaked: {forbidden!r}"

    def test_it_is_json_safe_for_the_artifact(self):
        import json

        result = _build([_trial("t", passed=False, metrics={"mode_fraction": 0.994})])
        restored = json.loads(json.dumps(result.model_dump(), allow_nan=False))
        assert restored["invalid_count"] == 1


class TestProducerToConsumerReachability:
    """A field written to an artifact but never consumed is not complete."""

    def test_the_tuner_output_declares_the_carrier(self):
        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

        assert "trial_validity_feedback" in HyperparamTuningOutput.model_fields

    def test_the_proposal_input_declares_the_window(self):
        from agent.schemas.proposal import ProposalInput

        assert "recent_trial_validity" in ProposalInput.model_fields

    def test_the_protocol_collects_it_from_tuner_outputs(self):
        """MUTATION TARGET: producing the report but never forwarding it."""
        import inspect

        from agent.schemas.protocols import ml_result_interp_to_ml_model_propose as proto

        src = inspect.getsource(proto)
        assert "trial_validity_feedback" in src
        assert '"recent_trial_validity"' in src

    def test_the_tuner_sets_the_skip_reason_at_the_skip_gate(self):
        """The flag must be set where the decision is MADE, not inferred
        later from a missing formal record."""
        import inspect

        from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent as _Agent

        # The decision is still made in run(); the flag now reaches the output
        # through RunExitSnapshot rather than a direct keyword, because output
        # construction moved into records.finalize_run_output (07b, C7d). Both
        # hops are pinned, so deleting either still fails here.
        src = inspect.getsource(_Agent.run)
        assert "_skipped_formal_for_no_valid_winner = True" in src
        assert "skipped_formal_for_no_valid_winner=_skipped_formal_for_no_valid_winner" in src
        assert re.search(
            r"formal_skipped_for_no_valid_winner=\s*"
            r"(exit_snapshot\.)?_?skipped_formal_for_no_valid_winner",
            tuner_node_source(),
        ), "the skip reason no longer reaches the run output"

    def test_the_block_reaches_the_real_proposing_prompt_template(self):
        """The last hop: the rendered block must have a placeholder in the
        template the planner actually receives."""
        from pathlib import Path

        template = (
            Path(__file__).resolve().parents[4]
            / "agent"
            / "prompt_templates"
            / "proposal"
            / "proposing_stage.md"
        ).read_text(encoding="utf-8")
        assert "{recent_trial_validity_block}" in template

    def test_the_prompt_variable_is_populated_from_the_input(self):
        import inspect
        import sys

        from nodes.ml_model_proposal_agent import _format_recent_trial_validity_block as fn

        src = inspect.getsource(sys.modules[fn.__module__])
        assert '"recent_trial_validity_block": _format_recent_trial_validity_block(' in src
        assert "inp.recent_trial_validity" in src


class TestTheRenderedBlock:
    @staticmethod
    def _render(entries):
        from nodes.ml_model_proposal_agent import _format_recent_trial_validity_block

        return _format_recent_trial_validity_block(entries)

    def test_an_empty_window_collapses_to_nothing(self):
        """Backward compatibility: a healthy chain's prompt is unchanged."""
        assert self._render([]) == ""

    def test_it_states_the_counts_and_keeps_them_separate(self):
        entry = _build(
            [
                _trial("crashed", status="error_training"),
                _trial("collapsed", passed=False, metrics={"mode_fraction": 0.994}),
                _trial("ungated", gates=False),
            ],
            skipped=True,
        )
        text = self._render([entry])

        assert "1 gate-invalid" in text
        assert "1 validity-unknown" in text
        assert "1 execution failure" in text
        assert "SKIPPED because no valid trial winner existed" in text
        assert "not because of the time budget" in text
        assert "output_diversity_blocking" in text
        assert "mode_fraction=0.994" in text
        assert "EVIDENCE ABSENT" in text

    def test_it_prescribes_no_remedy(self):
        """The workflow transports facts; the planner decides what to do.
        Task-specific advice here would also be wrong for the next task."""
        entry = _build([_trial("t", passed=False)], skipped=True)
        text = self._render([entry]).lower()
        for verb in ("you should", "recommend", "increase the", "reduce the", "instead use"):
            assert verb not in text

    @pytest.mark.parametrize("count", [1, 2, 3])
    def test_multiple_iterations_are_tagged_oldest_first(self, count):
        entries = [_build([_trial(f"t{i}", passed=False)]) for i in range(count)]
        text = self._render(entries)
        assert f"{count} iteration(s)" in text
        assert "iter N-1" in text  # the most recent is always N-1


def test_the_carrier_is_not_gate_exhaustion(self=None):
    """MUTATION TARGET: merging this into `GateExhaustionInfo`.

    Its triggers require budget-gated records (`skipped_oom_risk` /
    `skipped_time_risk`); an all-invalid iteration has records that ran
    and SUCCEEDED, so neither fires. Proven by execution rather than
    asserted, because the whole design decision rests on it.
    """
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _build_gate_exhaustion,
    )

    records = [_trial("t1", passed=False), _trial("t2", passed=False)]
    assert (
        _build_gate_exhaustion(
            records=records,
            active_mode="trial",
            vram_budget_gb=10.0,
            time_budget_minutes=10.0,
            consecutive_fail_rounds_at_exit=0,
            max_fail_rounds=3,
            completed_rounds=2,
        )
        is None
    ), "gate_exhaustion fired for an all-invalid iteration — the carriers have merged"
    assert isinstance(_build(records), TrialValidityFeedback)


class TestBothPromptPathsCarryTheBlock:
    """REGRESSION, found by Gate 1 rather than by any unit test.

    The first wiring reached only the PIPELINE template. The real proposer
    call took the LEGACY branch, so the block never reached the model —
    Gate 1 passed on its other properties while the headline one was
    silently unproven.

    This is the mirror image of the P3-V1 defect already recorded in the
    proposal agent, where a legacy-only splice never reached pipeline mode.
    Both directions have now occurred, so both paths are asserted here:
    whichever branch a run takes, the evidence must travel.
    """

    @staticmethod
    def _input(with_feedback: bool):
        from agent.schemas.proposal import ProposalInput
        from agent.schemas.proposer_evidence import build_proposer_evidence

        entry = _build([_trial("t", passed=False)], skipped=True)
        dump = {"model_types": ["a"], "best_denoising_score": 1.0}
        return ProposalInput(
            interpretation_evidence=build_proposer_evidence(dump),
            recent_trial_validity=[entry] if with_feedback else [],
        )

    def test_the_legacy_reasoning_prompt_carries_it(self):
        from nodes.ml_model_proposal_agent import _build_reasoning_prompt

        assert "RECENT TRIAL VALIDITY" in _build_reasoning_prompt(self._input(True))

    def test_the_legacy_prompt_is_unchanged_on_a_healthy_run(self):
        from nodes.ml_model_proposal_agent import _build_reasoning_prompt

        assert "RECENT TRIAL VALIDITY" not in _build_reasoning_prompt(self._input(False))

    def test_the_pipeline_template_still_has_its_placeholder(self):
        from pathlib import Path

        template = (
            Path(__file__).resolve().parents[4]
            / "agent"
            / "prompt_templates"
            / "proposal"
            / "proposing_stage.md"
        ).read_text(encoding="utf-8")
        assert "{recent_trial_validity_block}" in template

    def test_both_splice_sites_exist_in_the_agent(self):
        """MUTATION TARGET: wiring one path and forgetting the other."""
        import inspect
        import sys

        from nodes.ml_model_proposal_agent import _format_recent_trial_validity_block as fn

        src = inspect.getsource(sys.modules[fn.__module__])
        assert src.count("_format_recent_trial_validity_block(") >= 3, (
            "expected the formatter at the legacy splice, the pipeline "
            "variable and the token accounting"
        )


# ---------------------------------------------------------------------------
# Step 08a C3 — the LLM-facing rendering is byte-stable
# ---------------------------------------------------------------------------


def _step08a_gate(
    name,
    *,
    execution_status="passed",
    check_passed=True,
    would_invalidate=False,
    reason=None,
):
    return {
        "gate_name": name,
        "execution_status": execution_status,
        "check_passed": check_passed,
        "would_invalidate_under_production_policy": would_invalidate,
        "resolved_action": "continue",
        "failure_reason": reason,
        "key_metrics": {"unique_int8": 1} if reason else {},
    }


_STEP08A_REQUIRED = [
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
]

_STEP08A_RECORD_SETS = {
    "all_invalid": [
        {
            "exp_id": "e1",
            "is_trial": True,
            "status": "success",
            "denoising_score": 3.0,
            "health_gate_results": [
                _step08a_gate(
                    _STEP08A_REQUIRED[0],
                    check_passed=False,
                    execution_status="failed",
                    reason="collapsed",
                ),
                _step08a_gate(_STEP08A_REQUIRED[1]),
                _step08a_gate(_STEP08A_REQUIRED[2]),
            ],
        }
    ],
    "not_run_gate": [
        {
            "exp_id": "e2",
            "is_trial": True,
            "status": "success",
            "denoising_score": 3.0,
            "health_gate_results": [
                _step08a_gate(_STEP08A_REQUIRED[0]),
                _step08a_gate(_STEP08A_REQUIRED[1]),
                _step08a_gate(_STEP08A_REQUIRED[2], execution_status="not_run"),
            ],
        }
    ],
    "no_gates": [
        {
            "exp_id": "e3",
            "is_trial": True,
            "status": "success",
            "denoising_score": 3.0,
            "health_gate_results": [],
        }
    ],
    "execution_failure": [
        {
            "exp_id": "e4",
            "is_trial": True,
            "status": "error_training",
            "health_gate_results": [],
        }
    ],
}


def test_trial_validity_feedback_is_byte_identical_to_pre_step08a():
    """Step 08a changes nothing the planner can see.

    The golden was CAPTURED from a worktree at ``a37fd15d`` — the commit
    before any 08a code existed — so it is not this implementation's own
    output played back. The records are pre-08a shaped (no
    ``check_verdicts``), which is the case that must not move: 08a alters
    eligibility only for gates that carry the new typed evidence.

    If this fails, an LLM-facing surface changed and Gate 1 must be
    re-dispositioned with the operator before the PR proceeds (frozen 08a
    design §7; parent §10).
    """
    golden_path = (
        Path(__file__).resolve().parent / "goldens" / "step08a_trial_validity_feedback_pre08a.json"
    )
    golden = json.loads(golden_path.read_text())

    rendered = {}
    for name, records in _STEP08A_RECORD_SETS.items():
        for skipped in (False, True):
            block = _build_trial_validity_feedback(
                records,
                formal_skipped_for_no_valid_winner=skipped,
                healthgate_mode="enforce",
            )
            rendered[f"{name}__skipped_{skipped}"] = (
                None if block is None else block.model_dump(mode="json")
            )

    assert rendered == golden


def test_the_feedback_golden_actually_exercises_the_rendering():
    """Guards the guard: an all-``None`` golden would compare nothing."""
    golden_path = (
        Path(__file__).resolve().parent / "goldens" / "step08a_trial_validity_feedback_pre08a.json"
    )
    golden = json.loads(golden_path.read_text())
    populated = [key for key, value in golden.items() if value]
    assert populated, golden
    assert any(value.get("evidence_absent") for value in golden.values() if value)
    assert any(value.get("outcomes") for value in golden.values() if value)
