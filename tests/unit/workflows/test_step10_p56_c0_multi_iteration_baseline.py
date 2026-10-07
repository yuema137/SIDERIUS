"""Step 10 / P5+P6 — C0: the multi-iteration before-picture, through ``run_workflow``.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §13 C0, §2.1, §2.2, §5 (DD-1).

Two defects, both invisible to every single-iteration test, both recorded here
against the REAL loop (five agent classes stubbed at the workflow's import site
— no LLM, no sandbox, no subprocess):

**A. Findings amnesia (§2.2).** ``accumulated_key_findings`` is a bare local
(``model_exploration.py:1942``) seeded once from ``RestoredState`` and **never
updated in the loop**. So in an in-process multi-iteration run, iteration 3's
proposer sees exactly what iteration 1's saw. With nothing restored that is
*nothing at all* — the ``ExpertContextItem(kind="findings")`` block never
renders, however many findings the preceding iterations produced. C3 ends this.

**B. The severed confirmations carry (§2.1).** The production
``InterpretationInput(...)`` does not pass ``vocab_link_confirmations``, so
every iteration's interpreter receives the schema default ``{}`` no matter what
the previous iteration's digest wrote. One iteration can therefore append at
most one ``run_name``, and ``VocabEntry.related_to`` promotion — which needs
``min_runs=3`` DISTINCT runs — is **unreachable in production**. C2 ends this.

Both tests assert the DEFECT. **C2/C3 flip them**; they are not to be "fixed"
here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

# The established object factories (§2.3's harness — reused, not re-invented).
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tune_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

ITERATIONS = 3
REPO_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"

#: One distinct finding per iteration, so "did iteration N's finding survive to
#: iteration N+1's proposer?" is answerable by string identity.
FINDINGS = {
    1: ["iter1: dilated stacks widen the receptive field"],
    2: ["iter2: gated activations sharpen transients"],
    3: ["iter3: depthwise separable convolutions cut parameters"],
}

#: What an iteration's interpreter WOULD return if the carry existed — a
#: cumulative mapping growing by one run per iteration, exactly the producer's
#: real trajectory (pinned independently in the C0 producer golden).
CONFIRMATIONS = {
    1: {"dilated_stack:long_range_context": ["model_a"]},
    2: {"dilated_stack:long_range_context": ["model_a", "model_b"]},
    3: {"dilated_stack:long_range_context": ["model_a", "model_b", "model_c"]},
}


@pytest.fixture
def loop_env(tmp_path):
    """``run_workflow`` with all five agent classes stubbed, driven for
    ``ITERATIONS`` iterations.

    Each iteration MUST propose a unique model name: the workflow tracks
    ``state.all_model_types`` and mirrors plugin files per model name, so a
    repeated name collides. This is the established multi-iteration idiom.
    """
    composition = compose_run_task_bindings(str(QUICKSTART))
    _write_tuning_output(
        tmp_path,
        "punet",
        fingerprint=composition.semantic_fingerprint,
        metric_spec=composition.metric.spec,
    )
    workspace = str(tmp_path / "workflow_output")

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        interp_call = {"n": 0}

        def _interp(_inp):
            """Iteration N returns iteration N's findings and the cumulative
            confirmations mapping it would have accumulated."""
            interp_call["n"] += 1
            n = interp_call["n"]
            out = _make_interpretation_output()
            out.key_findings = list(FINDINGS.get(n, []))
            out.vocab_link_confirmations = dict(CONFIRMATIONS.get(n, {}))
            return out

        names = iter(["model_a", "model_b", "model_c"])
        MockInterp.return_value.run.side_effect = _interp
        MockPropose.return_value.run.side_effect = lambda inp: _make_proposal_output(next(names))
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type,
            score=1.6,
            fingerprint=composition.semantic_fingerprint,
            metric_spec=composition.metric.spec,
        )

        with bind_run_task_composition(composition, physical_data_root=str(tmp_path / "data")):
            run_workflow(
                llm_config=WorkflowLLMConfig(
                    tune=TunerLLMConfig(planner_strategy="native-timing-v1")
                ),
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=ITERATIONS,
                ),
                workspace=workspace,
                run_name="p56_c0",
                task_composition=composition,
            )
        yield {
            "interp_inputs": [c[0][0] for c in MockInterp.return_value.run.call_args_list],
            "propose_inputs": [c[0][0] for c in MockPropose.return_value.run.call_args_list],
        }


def _findings_items(proposal_input):
    return [item for item in proposal_input.expert_context if item.kind == "findings"]


# ---------------------------------------------------------------------------
# A. Findings amnesia
# ---------------------------------------------------------------------------


class TestFindingsNeverAccumulateInProcess:
    """**FLIPPED BY C3** — the §5 DD-1 delta, now delivered.

    Each docstring records the C0 expectation it replaced. Deeper accumulation
    semantics (the union rule, degraded/cold-start/quiet iterations, rendered
    bytes) are owned by ``test_step10_p56_c3_findings_accumulation.py``; what
    this class keeps is the end-to-end before/after through the real loop.
    """

    def test_the_loop_really_ran_three_iterations(self, loop_env):
        """Anti-vacuity, unchanged: the assertions below are meaningless if the
        loop did not actually produce findings to carry."""
        assert len(loop_env["interp_inputs"]) == ITERATIONS
        assert len(loop_env["propose_inputs"]) == ITERATIONS

    def test_the_findings_block_appears_once_the_history_is_non_empty(self, loop_env):
        """WAS: no iteration ever received a findings block, because the bare
        local was seeded once (here from nothing, so ``None``) and never
        updated in the loop.

        Iteration 1 still renders none — there is genuinely no PRIOR history
        yet, which is the existing empty-list guard, not amnesia. Iterations 2
        and 3 now render one.
        """
        rendered_counts = [len(_findings_items(p)) for p in loop_env["propose_inputs"]]
        assert rendered_counts == [0, 1, 1]

    def test_iteration_three_now_sees_iterations_one_and_two(self, loop_env):
        """WAS: nothing the first two iterations learned reached the third
        proposal. That was the science the defect damaged; this is it repaired.
        """
        rendered = "\n".join(item.content for item in loop_env["propose_inputs"][2].expert_context)
        assert FINDINGS[1][0] in rendered
        assert FINDINGS[2][0] in rendered
        # ...and NOT its own iteration's finding: the block is prior history.
        assert FINDINGS[3][0] not in rendered


# ---------------------------------------------------------------------------
# B. The severed confirmations carry
# ---------------------------------------------------------------------------


class TestConfirmationsNeverReachTheNextIteration:
    """**FLIPPED BY C2** — §2.1's measured consequence, now repaired.

    Each test's docstring records the C0 expectation it replaced. Kept rather
    than deleted: an inverted assertion is what proves the link was built.

    Promotion REACHABILITY itself is owned by
    ``test_step10_p56_c2_confirmations_reachability.py`` (S5's frozen primary
    evidence owner, with the four severing mutations). What this class owns is
    narrower and still distinct: that the TRANSPORT carries whatever the
    interpreter produced, verbatim, through the real loop.
    """

    def test_each_iteration_receives_what_its_predecessor_produced(self, loop_env):
        """WAS: ``received == [{}, {}, {}]`` — the workflow never passed the
        field, so the interpreter always got the schema default."""
        received = [inp.vocab_link_confirmations for inp in loop_env["interp_inputs"]]
        assert received == [
            {},  # iteration 1 of a fresh run: nothing restored, first-class
            CONFIRMATIONS[1],
            CONFIRMATIONS[2],
        ]

    def test_the_carry_is_verbatim_not_re_merged(self, loop_env):
        """WAS: an anti-vacuity check that the producer really produced a
        mapping which then went nowhere.

        Now it pins the rule that replaced the defect: LATEST-WINS. Iteration 3
        receives iteration 2's mapping EXACTLY — not a union of iterations 1
        and 2, which is what a workflow-side re-merge (a second accumulation
        authority) would have produced.
        """
        assert loop_env["interp_inputs"][2].vocab_link_confirmations == CONFIRMATIONS[2]
        assert CONFIRMATIONS[2] == {"dilated_stack:long_range_context": ["model_a", "model_b"]}

    def test_the_threshold_is_now_reachable(self, loop_env):
        """WAS: ``longest < 3`` for every iteration — ``min_runs=3`` distinct
        runs could never accumulate, so ``VocabEntry.related_to`` promotion did
        not happen in production at all.

        The counter now grows across iterations. (That the PRODUCER then
        promotes at exactly three is the reachability module's claim, not
        this one's.)
        """
        longest_per_iteration = [
            max((len(v) for v in inp.vocab_link_confirmations.values()), default=0)
            for inp in loop_env["interp_inputs"]
        ]
        assert longest_per_iteration == [0, 1, 2]
