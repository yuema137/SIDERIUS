"""Step 08b C6 / D18 — a scalar-only metric reaches Health as a statement.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08b_extension_architecture.md`` §2.6,
§4.6, and frozen invariant 16.

Defect classes owned here:

* **"This question does not arise for this task" recorded as health.** Step
  06 already states scalar-only-ness at the producer (``per_sample is
  None``); the tuner's bridge collapsed it into ``list(... or [])``, so a
  scalar-only task presented per-file checks with ``[]`` — which reads as
  "no files" and PASSES. The whole point of Step 08 is that inapplicability
  and health are different answers.
* **Absence inferred as a statement.** A context that says nothing has not
  said "this task is scalar-only". Three values exist rather than a boolean
  precisely so the undeclared case stays undeclared.
* **Health reading the golden metric scalar.** Invariant 16 permits Health
  to consume capability METADATA only. A check that read the score would be
  grading the result it is supposed to be independent of.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from execute_tools.health_checks import registry, runner
from execute_tools.health_checks.config import (
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
)
from execute_tools.health_checks.schemas import (
    CONTEXT_INPUT_PREDICATES,
    CheckInputDeclaration,
    CheckVerdict,
    GateAction,
    HealthCheckContext,
    HealthCheckResult,
    PerSampleEvidence,
    TaskHealthFacts,
    applicability,
)

PER_SAMPLE_DECLARATION = CheckInputDeclaration(
    consumes_view="step08.per_sample_consumer",
    required_context_inputs=("per_sample_evidence",),
)


def _ctx(**overrides) -> HealthCheckContext:
    base: dict[str, Any] = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


class TestTheStatementIsTypedNotInferred:
    """A typed value, because an empty list cannot carry a claim."""

    def test_an_empty_file_vector_and_a_scalar_only_metric_are_different_states(self):
        """THE D18 defect, stated as an assertion.

        Both produce ``file_vector == []``. If that list were the only
        signal, these two situations would be indistinguishable — and one of
        them is "there is nothing to look at this round" while the other is
        "there is no such thing as a per-file view of this task".
        """
        empty_but_capable = _ctx(file_vector=[], per_sample_evidence=PerSampleEvidence.AVAILABLE)
        scalar_only = _ctx(file_vector=[], per_sample_evidence=PerSampleEvidence.SCALAR_ONLY)

        assert empty_but_capable.file_vector == scalar_only.file_vector == []
        assert empty_but_capable.per_sample_evidence is not scalar_only.per_sample_evidence

    def test_the_default_is_undeclared_not_scalar_only(self):
        """Absence is not a statement, and must never be inferred as one.

        A pre-scoring gate and a pre-D18 context both say nothing. Reading
        that as "this task is scalar-only" would invent a declaration.
        """
        assert _ctx().per_sample_evidence is PerSampleEvidence.UNDECLARED

    def test_evidence_present_but_empty_is_still_AVAILABLE(self):
        """The producer's statement is about capability, not about content.

        ``per_sample == []`` means the metric produces per-sample evidence
        and produced none; whether there is anything to read is
        ``file_vector``'s question, deliberately kept separate.
        """
        assert CONTEXT_INPUT_PREDICATES["per_sample_evidence"](
            _ctx(per_sample_evidence=PerSampleEvidence.AVAILABLE, file_vector=[])
        )


class TestTheProducerStatementSurvivesTheBridge:
    """The mapping, and proof the production path actually uses it."""

    @pytest.mark.parametrize(
        ("per_sample", "expected"),
        [
            (None, PerSampleEvidence.SCALAR_ONLY),
            ([], PerSampleEvidence.AVAILABLE),
            ([1.0, 2.0], PerSampleEvidence.AVAILABLE),
            ([1.0, None], PerSampleEvidence.AVAILABLE),
        ],
    )
    def test_the_mapping_reads_step_06s_existing_statement(self, per_sample, expected):
        """``None`` vs a list is Step 06's contract; no second flag invented."""
        assert PerSampleEvidence.for_per_sample(per_sample) is expected

    def test_the_tidmad_shaped_result_is_AVAILABLE(self):
        """Negative control: the task whose behaviour must not move.

        TIDMAD's metric returns a per-file vector, so it lands on the branch
        that changes nothing — which is why the 27-case verdict manifest and
        the six gates are untouched by D18.
        """
        assert PerSampleEvidence.for_per_sample([0.5] * 20) is PerSampleEvidence.AVAILABLE

    def test_the_tuner_bridge_carries_the_statement_into_the_context(self):
        """REACHABILITY: the production path must not bypass the boundary.

        Without this, every test above could pass while the tuner still
        collapsed the statement into an empty list — the exact defect D18
        exists to remove, and one no behavioural test would see, because a
        hollow pass looks like health.

        Read as TEXT, deliberately: ``execution`` is a PRIVATE module of the
        tuner node, and 08a's public-boundary rule forbids importing one from
        outside the node. Reading the file asserts the same fact without
        breaching the boundary the rule protects.
        """
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[4]
        source = (
            repo_root / "src/nodes" / "ml_hyperparameter_tune_agent" / "execution.py"
        ).read_text()

        assert "PerSampleEvidence.for_per_sample(per_sample)" in source, (
            "the tuner bridge no longer derives the per-sample statement"
        )
        assert "per_sample_evidence=per_sample_evidence" in source, (
            "the derived statement is no longer passed into HealthCheckContext"
        )
        assert "list(metric_result.per_sample or [])" not in source, (
            "the collapsing expression D18 removed has been reintroduced"
        )


class TestADeclaringCheckBecomesInapplicable:
    """The consequence: ``inapplicable``, with the axis named — never a pass."""

    @pytest.mark.parametrize(
        "state",
        [PerSampleEvidence.SCALAR_ONLY, PerSampleEvidence.UNDECLARED],
    )
    def test_a_check_requiring_per_sample_evidence_does_not_apply(self, state):
        verdict = applicability(
            PER_SAMPLE_DECLARATION, TaskHealthFacts(), _ctx(per_sample_evidence=state)
        )

        assert verdict.applicable is False
        assert verdict.axis == "per_sample_evidence"

    def test_the_same_check_applies_when_evidence_is_available(self):
        """The positive half. Without it, a bug making everything
        inapplicable would look like success."""
        verdict = applicability(
            PER_SAMPLE_DECLARATION,
            TaskHealthFacts(),
            _ctx(per_sample_evidence=PerSampleEvidence.AVAILABLE),
        )

        assert verdict.applicable is True

    def test_the_gate_records_INAPPLICABLE_rather_than_a_pass(self, monkeypatch, clean_registry):
        """End to end through the real runner: the verdict, not just the axis.

        ``passed=True`` on an inapplicable result is 08a's deliberate
        routing, so asserting on ``passed`` alone would not distinguish this
        from health. The VERDICT is what carries the meaning, and what
        eligibility and the persisted record read.
        """

        class _PerSampleCheck:
            name: ClassVar[str] = "step08_per_sample_consumer"
            declaration: ClassVar[CheckInputDeclaration] = PER_SAMPLE_DECLARATION

            def __init__(self):
                self.calls = 0

            def run(self, ctx, config=None):
                self.calls += 1
                return HealthCheckResult(check_name=self.name, passed=True, reason="ran")

        check = _PerSampleCheck()
        registry.register(check)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda: HealthChecksConfig(
                health_gates=[
                    GateConfig(
                        id="g",
                        after_round="every",
                        checks=[CheckRef(name=check.name)],
                        on_pass=ActionConfig(action=GateAction.CONTINUE),
                        on_fail=ActionConfig(action=GateAction.INVALIDATE_ROUND),
                    )
                ]
            ),
        )
        monkeypatch.setattr(runner, "_resolve_task_facts", TaskHealthFacts)

        result = runner.evaluate_gate("g", _ctx(per_sample_evidence=PerSampleEvidence.SCALAR_ONLY))

        assert result.check_results[0].verdict is CheckVerdict.INAPPLICABLE
        assert result.check_results[0].metrics["inapplicable_axis"] == "per_sample_evidence"
        # It was never invoked, so it opened nothing (08a's guarantee).
        assert check.calls == 0


class TestTheShippedChecksAreUnaffected:
    """TIDMAD's negative control, and invariant 16's census."""

    def test_no_shipped_check_declares_per_sample_evidence(self):
        """They read FILES, not per-sample evidence.

        Declaring an input a check never consumes would make it report itself
        inapplicable for a property it does not use — the mirror of the
        `value_scale_unit` biconditional. The consuming checks arrive with
        08c's standard capabilities.
        """
        for name in registry.all_registered():
            declaration = getattr(registry.get(name), "declaration", None)
            if declaration is None:
                continue
            assert "per_sample_evidence" not in declaration.required_context_inputs, name

    def test_no_check_reads_the_golden_metric_scalar(self):
        """Invariant 16: Health consumes CAPABILITY metadata, never the score.

        A check that read ``denoising_score`` would be grading the very
        result it exists to be independent of — health evidence derived from
        the number under judgement.
        """
        import inspect

        for name in registry.all_registered():
            source = inspect.getsource(type(registry.get(name)))
            assert "denoising_score" not in source, name
            assert "ctx.file_vector" not in source, name

    def test_the_context_vocabulary_grew_by_exactly_one_entry(self):
        """Pins the CONCEPT: these are logical inputs a round PRODUCED.

        Growth is a framework decision requiring a task that forces it. A new
        TASK must need no new entry here — that is what keeps this from
        becoming a per-task registry.
        """
        assert set(CONTEXT_INPUT_PREDICATES) == {
            "denoised_source",
            "target_source",
            "file_vector",
            "denoising_score",
            "per_sample_evidence",
        }
