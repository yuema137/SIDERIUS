"""Step 09a — C6: diagnosis, secondaries and failure counts reach the summary.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.5, §4.7; parent §4, §4b, §5;
operator ruling Q-09-7 = B.

The gap this closes
-------------------
``tuning_output_to_model_run_summary`` read NONE of ``metric_result``,
``metric_refusal``, ``training_history`` or ``training_diagnosis``. The
interpreter could therefore see that a score existed but nothing about how the
training that produced it behaved, could not NAME a not-scoreable round as a
failure, and had no way to report what went wrong across a model's records.
Step 07a computes the diagnosis and Step 06 computes the identity and the
refusal; both stopped at the tuner's records.

What C6 deliberately did NOT do — and what Step 10 / P2b then did
-----------------------------------------------------------------
Q-09-7 = B: the interpreter-side CONTRACT for secondary metrics was Step 09's,
while the upstream half — tuner-side evaluation, `ExperimentRecord`
persistence, workflow transport — was Step 10's. C6 therefore left
``secondary_metrics`` EMPTY rather than inventing values or reading undeclared
record keys.

**Step 10 / P2b landed that upstream half**, so the guards below were INVERTED
rather than deleted: the reserved schema names must now exist (exactly those),
the evaluator and the binder must exist in exactly one owner each, and the
projection is empty precisely when the output carries no DECLARED secondary
set. Each inversion is the same claim seen from the other side — the same
defect falsifies both readings. The positive projection matrix lives in
``test_step10_p2b_c3_secondary_projection.py``.

The other standing rule: secondaries are OBSERVATIONAL. They must be unable
to reach any ordering decision, which is asserted structurally (no reference
inside an order-consuming function) and behaviourally (mutating every
secondary value changes no ordering output).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.interpretation import (
    RecordFailureCounts,
    SecondaryMetricEvidence,
)
from agent.schemas.training_diagnosis import TrainingDiagnosis
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import accuracy_like_spec, shipped_spec

REPO_ROOT = Path(__file__).resolve().parents[4]
ORDER = MetricOrder(shipped_spec())


def _diagnosis(state: str = "absent", validation: str = "absent") -> TrainingDiagnosis:
    """A diagnosis these fixtures can attach to a record WITHOUT a history.

    `ExperimentRecord` enforces `state != "absent" => training_history is not
    None` (`hyperparam_tuning.py:759-763`), so a fixture asserting the
    PROJECTION does not get to invent an `ok` diagnosis on a record with no
    training results. That coupling is asserted directly in
    `test_a_non_absent_diagnosis_requires_its_history`; every projection case
    below therefore uses states the record contract actually admits.
    """
    return TrainingDiagnosis(state=state, validation_state=validation)


def _record(exp_id: str, **overrides) -> ExperimentRecord:
    base = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-19T00:00:00Z",
        "params": {},
        "denoising_score": -2.0,
        "health_gate_enabled": False,
    }
    return ExperimentRecord.model_validate({**base, **overrides})


def _output(*records) -> HyperparamTuningOutput:
    return HyperparamTuningOutput.model_validate(
        {
            "run_name": "c6",
            "model_type": "wavenet",
            "file_index": 6,
            "status": "completed",
            "completed_rounds": len(records),
            "total_attempts": len(records),
            "started_at": "2026-08-19T00:00:00Z",
            "finished_at": "2026-08-19T01:00:00Z",
            "all_records": list(records),
        }
    )


# ---------------------------------------------------------------------------
# 1. The 07a diagnosis reaches the summary, per ROLE
# ---------------------------------------------------------------------------


class TestTheDiagnosisProjection:
    def test_the_best_and_formal_roles_carry_their_OWN_diagnoses(self):
        """One per role, not one per model.

        A best trial round and the formal round are different experiments and
        may have behaved differently — a single field would have to pick one
        and silently mislabel the other.
        """
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    "trial",
                    denoising_score=-1.5,
                    is_trial=True,
                    training_diagnosis=_diagnosis("absent", "absent"),
                ),
                _record(
                    "formal",
                    denoising_score=-2.5,
                    is_trial=False,
                    training_diagnosis=None,
                ),
            ),
            order=ORDER,
        )
        # best = the highest score = the TRIAL round under `higher`; the
        # formal round carries none. A single per-model field would have to
        # report one of these for both.
        assert summary.best_training_diagnosis is not None
        assert summary.best_training_diagnosis.state == "absent"
        assert summary.formal_training_diagnosis is None

    def test_it_is_carried_verbatim_not_re_derived(self):
        """The interpreter must not become a SECOND diagnosis authority
        (parent §7): 07a derives it once at the tuner boundary."""
        diagnosis = _diagnosis("absent", "absent")
        summary = tuning_output_to_model_run_summary(
            _output(_record("r", is_trial=False, training_diagnosis=diagnosis)), order=ORDER
        )
        assert summary.best_training_diagnosis == diagnosis
        assert summary.formal_training_diagnosis == diagnosis

    def test_a_non_absent_diagnosis_requires_its_history(self):
        """The record contract C6 relies on, asserted rather than assumed.

        It is what makes "the diagnosis is carried verbatim" safe: a record
        cannot claim a diagnosed state without the history that produced it.
        """
        with pytest.raises(ValidationError, match="requires a training_history"):
            _record(
                "r", training_diagnosis=TrainingDiagnosis(state="ok", validation_state="present")
            )

    def test_absence_is_absence(self):
        """A record predating 07a carries none; nothing is invented for it."""
        summary = tuning_output_to_model_run_summary(_output(_record("r")), order=ORDER)
        assert summary.best_training_diagnosis is None
        assert summary.formal_training_diagnosis is None


# ---------------------------------------------------------------------------
# 2. Failure counts, from EXISTING authorities only
# ---------------------------------------------------------------------------


class TestTheFailureCounts:
    def test_a_mixed_record_set_is_counted_by_hand(self):
        summary = tuning_output_to_model_run_summary(
            _output(
                _record("diagnosed", training_diagnosis=_diagnosis("absent", "absent")),
                _record("no_diag", denoising_score=-2.2),
                _record(
                    "collapse",
                    status="failed_mode_collapse",
                    denoising_score=-9.0,
                    gate_action="invalidate_round",
                    failure_reason="collapsed",
                    training_diagnosis=_diagnosis("absent", "absent"),
                ),
                _record("skipped", status="skipped_oom_risk", denoising_score=None),
            ),
            order=ORDER,
        )
        counts = summary.failure_counts
        assert counts is not None
        assert counts.records_total == 4
        assert counts.status_counts == {
            "success": 2,
            "failed_mode_collapse": 1,
            "skipped_oom_risk": 1,
        }
        assert counts.diagnosis_state_counts == {"absent": 2, "diagnosis_missing": 2}
        assert counts.validation_state_counts == {"absent": 2}
        assert counts.gate_action_counts == {"none": 3, "invalidate_round": 1}

    def test_a_missing_diagnosis_is_counted_separately_from_an_absent_one(self):
        """ "no diagnosis object" and "the diagnosis says the history was
        absent" are different facts about different records. Folding them
        together would report training that never ran as training that ran
        without validation."""
        summary = tuning_output_to_model_run_summary(
            _output(
                _record("none"),
                _record(
                    "has_absent_diagnosis",
                    denoising_score=-2.1,
                    training_diagnosis=_diagnosis("absent", "absent"),
                ),
            ),
            order=ORDER,
        )
        assert summary.failure_counts is not None
        assert summary.failure_counts.diagnosis_state_counts == {
            "diagnosis_missing": 1,
            "absent": 1,
        }

    def test_a_metric_refusal_is_counted_with_its_OPAQUE_contract_id(self):
        refusal = {
            "metric_id": "tidmad_denoising_score",
            "direction": "higher",
            "verdict": {
                "contract_id": "tidmad_h5_presence",
                "failures": [{"requirement": "required_attrs", "detail": "missing"}],
            },
        }
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    "refused",
                    status="error_scoring",
                    failure_type="not_scoreable",
                    denoising_score=None,
                    metric_refusal=refusal,
                )
            ),
            order=ORDER,
        )
        counts = summary.failure_counts
        assert counts is not None
        assert counts.metric_refusal_count == 1
        assert counts.refusal_contract_ids == {"tidmad_h5_presence": 1}

    def test_an_unknown_future_status_needs_no_source_change(self):
        """The point of open dicts over a closed enum: a fourth task's novel
        pathology is expressed at ITS owning layer and the interpreter renders
        it without growing a vocabulary."""
        counts = RecordFailureCounts(status_counts={"some_status_invented_later": 3})
        assert counts.status_counts["some_status_invented_later"] == 3

    def test_the_counts_reach_BOTH_digest_paths(self, tmp_path):
        from unittest.mock import patch

        from agent.schemas.interpretation import InterpretationInput
        from nodes.result_interpretation_agent import ResultInterpretationAgent

        summary = tuning_output_to_model_run_summary(
            _output(_record("r", training_diagnosis=_diagnosis())), order=ORDER
        )
        summary.model_description = "d"
        inp = InterpretationInput(
            summaries=[summary],
            metric_spec=shipped_spec(),
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r"}},
        )

        with patch("nodes.result_interpretation_agent.LLMBridge") as bridge:
            bridge.return_value.generate.side_effect = RuntimeError("forced LLM failure")
            agent = ResultInterpretationAgent(provider="openai", model_id="x")
            agent.bridge = bridge.return_value
            degraded = agent.run(inp)

        assert degraded.is_degraded is True
        assert "wavenet" in degraded.per_model_failure_counts, (
            "the DEGRADED digest lost the failure counts — an interpreter LLM "
            "failure must not erase deterministic evidence (the §3.10 rule)"
        )


# ---------------------------------------------------------------------------
# 3. Secondary metrics — the contract, and its production emptiness
# ---------------------------------------------------------------------------


class TestSecondaryMetricEvidence:
    def test_the_three_states_are_distinguishable(self):
        spec = accuracy_like_spec("fixture_macro_f1")
        scored = SecondaryMetricEvidence(
            spec=spec,
            result={"metric_id": spec.id, "direction": "higher", "scalar": 0.81},
        )
        refused = SecondaryMetricEvidence(
            spec=spec,
            refusal={
                "metric_id": spec.id,
                "direction": "higher",
                "verdict": {
                    "contract_id": "presence",
                    "failures": [{"requirement": "x", "detail": "y"}],
                },
            },
        )
        unavailable = SecondaryMetricEvidence(spec=spec)
        assert (scored.status, refused.status, unavailable.status) == (
            "scored",
            "refused",
            "unavailable",
        )

    def test_a_result_and_a_refusal_together_are_rejected(self):
        spec = accuracy_like_spec("fixture_macro_f1")
        with pytest.raises(ValidationError, match="both a result and a refusal"):
            SecondaryMetricEvidence(
                spec=spec,
                result={"metric_id": spec.id, "direction": "higher", "scalar": 0.81},
                refusal={
                    "metric_id": spec.id,
                    "direction": "higher",
                    "verdict": {
                        "contract_id": "p",
                        "failures": [{"requirement": "x", "detail": "y"}],
                    },
                },
            )

    def test_each_secondary_keeps_its_OWN_direction(self):
        """DAVIS declares psnr (higher) beside mse (lower). A secondary that
        inherited the primary's direction would be rendered backwards."""
        lower = SecondaryMetricEvidence(
            spec=shipped_spec().model_copy(update={"direction": "lower"})
        )
        assert lower.spec.direction == "lower"

    @pytest.mark.parametrize(
        "record_kwargs",
        [
            {},
            {
                "metric_result": {
                    "metric_id": "tidmad_denoising_score",
                    "direction": "higher",
                    "scalar": -2.0,
                }
            },
        ],
        ids=["bare-record", "fully-scored-record"],
    )
    def test_an_output_with_no_DECLARED_set_projects_nothing(self, record_kwargs):
        """Q-09-7 = B's claim, REWRITTEN for the world where Step 10 landed.

        Until P2b this said "the builder always leaves it empty, because no
        record carrier exists". The carrier exists now, so that sentence would
        assert the opposite of the shipped contract. What survives — and what
        was the real content all along — is that evidence appears ONLY under a
        DECLARED set: an output carrying no `secondary_metric_specs` stamp
        projects nothing, no matter what its records hold. That covers both a
        legacy output and a run of a task with no secondaries, and it is what
        keeps TIDMAD's rendered bytes at zero.

        The FULLY-SCORED case is the one that matters and was missing at
        first: mutation C6-3 fabricated a secondary only for records carrying
        a `metric_result`, and the original bare-record fixture never reached
        that branch. The claim has to be made on the record shape production
        actually produces.

        The positive half — that a STAMPED output projects scored / refused /
        unavailable correctly — is owned by
        `test_step10_p2b_c3_secondary_projection.py`.
        """
        summary = tuning_output_to_model_run_summary(
            _output(_record("r", **record_kwargs)), order=ORDER
        )
        assert _output(_record("r")).secondary_metric_specs is None
        assert summary.secondary_metrics == []

    def test_the_builder_does_not_read_undeclared_record_keys(self):
        """MUTATION TARGET: reading a key no schema has defined.

        `ExperimentRecord` ignores extra keys, so a builder that speculatively
        read one would appear to work on a hand-made fixture and silently do
        nothing in production — a hidden contract.

        Step 10 / P2b KEPT this mutation and moved its payload. The original
        fabricated `secondary_metric_results`, which P2b C2 turned into a real
        declared carrier the projection is now SUPPOSED to read; continuing to
        use it would assert the opposite of the shipped contract. The claim
        being pinned is unchanged — evidence reaches the summary through a
        DECLARED carrier or not at all — so the payload moves to a key that
        remains undeclared and always will.
        """
        undeclared = "tertiary_metric_results"
        assert undeclared not in ExperimentRecord.model_fields, (
            f"{undeclared!r} became a real field; pick another undeclared key "
            "rather than weakening this mutation"
        )
        record = _record("r")
        object.__setattr__(
            record,
            "__dict__",
            {**record.__dict__, undeclared: [{"metric_id": "sneaky"}]},
        )
        summary = tuning_output_to_model_run_summary(_output(record), order=ORDER)
        assert summary.secondary_metrics == [], (
            "the builder read a record key no schema declares; evidence reaches "
            "the summary through a declared carrier or not at all"
        )


# ---------------------------------------------------------------------------
# 4. Secondaries are observational — structurally and behaviourally
# ---------------------------------------------------------------------------


class TestSecondariesCannotReachOrdering:
    """The observational invariant, over EVERY surface that handles secondaries.

    Step 10 / P2b C0 extends the scanned set. Until P2b, secondaries existed
    only on the interpreter side, so scanning the interpreter was the whole
    surface. P2b gives them a production lifecycle — declared at composition,
    bound for the run, evaluated at the tuner's scoring point, carried on the
    record and the output — and every one of those files is a place where a
    "helpful" ordering line could give a secondary a vote.

    An invariant whose scope is extended AFTER the code exists cannot prove the
    extension found anything, which is why the extension lands in C0, green at
    base, with `test_the_scope_extension_is_live` planting an offender in a
    NEWLY-scanned file and requiring it to be caught.
    """

    #: The Step-09a surface: where secondary EVIDENCE is projected and ranked.
    INTERPRETER_FILES: ClassVar[list[str]] = [
        "nodes/result_interpretation_agent/result_interpretation_agent.py",
        "nodes/result_interpretation_agent/evidence.py",
        "nodes/result_interpretation_agent/ordering.py",
        "nodes/result_interpretation_agent/prediction.py",
        "nodes/interpretation_helpers.py",
    ]

    #: The Step-10 / P2b production surface: declaration, binding, evaluation
    #: and transport. Named from the child design's measured touch set (§2.7);
    #: files P2b ends up not modifying stay listed deliberately — the claim is
    #: about the whole lifecycle, not about one diff.
    PRODUCTION_FILES: ClassVar[list[str]] = [
        "workflows/task_composition.py",
        "execute_tools/evaluation_metric.py",
        "nodes/ml_hyperparameter_tune_agent/execution.py",
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
        "nodes/ml_hyperparameter_tune_agent/contracts.py",
        "nodes/ml_hyperparameter_tune_agent/records.py",
        "nodes/ml_hyperparameter_tune_agent/policy.py",
        "agent/schemas/hyperparam_tuning.py",
        "agent/schemas/interpretation.py",
        "agent/prompt_templates/interpretation/rendering.py",
    ]

    SCANNED_FILES: ClassVar[list[str]] = INTERPRETER_FILES + PRODUCTION_FILES

    @staticmethod
    def _secondaries_in_ordering_expressions(source: str) -> list[str]:
        """Any ordering EXPRESSION whose operands mention a secondary metric.

        The first cut of this census asked "does a function that reads `order`
        also mention secondaries?" — too coarse. The summary builder and
        `run()` legitimately do both: they RANK primary scores and they
        PROJECT secondary evidence, in the same scope. Flagging that would
        have forced the projection into a contrived second function to satisfy
        a test, which is the tail wagging the dog.

        The rule as actually claimed is narrower and checkable: a secondary
        metric may not appear as an operand of an ORDER comparison, as an
        argument to a `MetricOrder` method, or as a sort key.

        "ORDER comparison" — `<`, `<=`, `>`, `>=` — is a Step 10 / P2b C1
        refinement (IR-P2b-3), made against evidence rather than to make a
        test green. Until P2b, no production line touched a secondary at all,
        so flagging EVERY comparison cost nothing. P2b gives secondaries a
        production lifecycle, and the first thing it produced was
        `resolve_bound_run_secondary_metrics() != composition.secondary_metrics`
        in `verify_composition_is_bound` — a binding-integrity check written in
        the same `!=` idiom the line directly below it uses for `task_config`.
        That is not an ordering decision, and rewriting it into a helper purely
        to dodge an AST rule is the tail wagging the dog this docstring already
        warns about.

        Equality and membership are not thereby unguarded. A ranking has to
        produce an ORDER somewhere — an order comparison, an extremum call, a
        sort key or a `MetricOrder` method — and all four remain flagged; an
        `==` tie-break that changed a ranking would still have to pass through
        one of them, and `test_flipping_every_secondary_value_changes_no_
        ordering_output` is the behavioural backstop for whatever the AST
        cannot see.
        """
        _ORDER_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
        offenders: list[str] = []
        tree = ast.parse(source)
        for node in ast.walk(tree):
            expression = None
            if isinstance(node, ast.Compare):
                if any(isinstance(op, _ORDER_OPS) for op in node.ops):
                    expression = node
            elif isinstance(node, ast.Call):
                fn = node.func
                is_order_call = isinstance(fn, ast.Attribute) and re.search(
                    r"(?<![\w_])(order|run_order)$", ast.unparse(fn.value)
                )
                is_extremum = (isinstance(fn, ast.Name) and fn.id in {"max", "min", "sorted"}) or (
                    isinstance(fn, ast.Attribute) and fn.attr == "sort"
                )
                if is_order_call or is_extremum:
                    expression = node
            if expression is None:
                continue
            text = ast.unparse(expression)
            if "secondary_metric" in text:
                offenders.append(f"{expression.lineno}: {text[:120]}")
        return offenders

    def test_no_ordering_expression_mentions_a_secondary_metric(self):
        offenders: dict[str, list[str]] = {}
        for rel in self.SCANNED_FILES:
            path = REPO_ROOT / rel
            assert path.is_file(), (
                f"the invariant names {rel!r}, which does not exist. A scanned "
                "file that silently disappears turns this census into a test "
                "that passes because it looked at nothing."
            )
            hits = self._secondaries_in_ordering_expressions(path.read_text(encoding="utf-8"))
            if hits:
                offenders[rel] = hits
        assert offenders == {}, (
            "a secondary metric is an operand of an ordering expression — "
            "secondaries are OBSERVATIONAL and must never affect a ranking: "
            f"{offenders}"
        )

    def test_the_scope_extension_is_live(self):
        """The P2b scope extension, proven rather than declared.

        `test_a_planted_offender_is_caught` proves the DETECTOR works on a
        string. This proves the detector is actually pointed at the Step-10
        production files: it reads each newly-scanned file from disk, appends
        an offending expression, and requires a hit. A scope list that named a
        file the census never opened would pass the former and fail this.
        """
        plants = {
            "order-method": (
                "\n\ndef _p2b_scope_probe(models, order):\n"
                "    return order.best(models, key=lambda m: m.secondary_metric_results[0].scalar)\n"
            ),
            # The narrowed Compare branch (IR-P2b-3), proven live on disk too.
            "order-comparison": (
                "\n\ndef _p2b_scope_probe(a, b):\n"
                "    return a.secondary_metric_results[0].scalar > b.secondary_metric_results[0].scalar\n"
            ),
        }
        for rel in self.PRODUCTION_FILES:
            source = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for shape, planted in plants.items():
                assert self._secondaries_in_ordering_expressions(source + planted), (
                    f"{rel} is listed as scanned, but a planted {shape} over a "
                    "secondary metric is not detected in it"
                )

    @pytest.mark.parametrize(
        "planted",
        [
            "def f(models, order):\n    return order.best(models, key=lambda m: m.secondary_metrics[0].result.scalar)\n",
            "def f(a, b):\n    return a.secondary_metrics[0].result.scalar > b.secondary_metrics[0].result.scalar\n",
            "def f(a, b):\n    return a.secondary_metrics[0].result.scalar < b.secondary_metrics[0].result.scalar\n",
            "def f(a, b):\n    return a.secondary_metrics[0].result.scalar >= b.secondary_metrics[0].result.scalar\n",
            "def f(a, b):\n    return a.secondary_metrics[0].result.scalar <= b.secondary_metrics[0].result.scalar\n",
            "def f(models):\n    models.sort(key=lambda m: m.secondary_metrics[0].result.scalar)\n",
            "def f(models):\n    return max(models, key=lambda m: m.secondary_metric_results[0].scalar)\n",
            "def f(models):\n    return sorted(models, key=lambda m: m.secondary_metric_results[0].scalar)\n",
        ],
        ids=["order-method", "gt", "lt", "ge", "le", "sort-key", "max", "sorted"],
    )
    def test_a_planted_offender_is_caught(self, planted):
        assert self._secondaries_in_ordering_expressions(planted) != []

    def test_a_binding_integrity_check_is_deliberately_not_an_offender(self):
        """IR-P2b-3, pinned so the narrowing is a decision and not a drift.

        This is the exact shape P2b's `verify_composition_is_bound` uses, and
        the exact shape the pre-P2b `task_config` check beside it already used.
        Equality against a bound family decides SAMENESS, never an order.
        """
        legitimate = (
            "def verify(composition):\n"
            "    if resolve_bound_run_secondary_metrics() != composition.secondary_metrics:\n"
            "        unbound.append('secondary_metrics')\n"
        )
        assert self._secondaries_in_ordering_expressions(legitimate) == []

    def test_the_projection_itself_is_not_flagged(self):
        """Anti-over-reach: assigning secondaries in a scope that also ranks is
        exactly what the builder does, and it is legitimate."""
        legitimate = (
            "def build(records, order):\n"
            "    best = order.best(records, key=lambda r: r.score)\n"
            "    return {'best': best, 'secondary_metrics': []}\n"
        )
        assert self._secondaries_in_ordering_expressions(legitimate) == []

    def test_flipping_every_secondary_value_changes_no_ordering_output(self):
        """The behavioural half. The structural census can only see the code
        that exists; this asserts the OUTPUT is invariant."""
        import importlib

        _ordering = importlib.import_module("nodes.result_interpretation_agent.ordering")
        spec = accuracy_like_spec("fixture_macro_f1")

        def _summary_with(scalar: float):
            summary = tuning_output_to_model_run_summary(
                _output(_record("a", denoising_score=-2.0), _record("b", denoising_score=-2.6)),
                order=ORDER,
            )
            return summary.model_copy(
                update={
                    "secondary_metrics": [
                        SecondaryMetricEvidence(
                            spec=spec,
                            result={"metric_id": spec.id, "direction": "higher", "scalar": scalar},
                        )
                    ]
                }
            )

        low = _ordering.precompute_evidence([_summary_with(0.01)], {}, ["wavenet"], order=ORDER)
        high = _ordering.precompute_evidence([_summary_with(0.99)], {}, ["wavenet"], order=ORDER)
        assert low.overall_best_score == high.overall_best_score
        assert low.per_model_best == high.per_model_best
        assert low.per_model_worst == high.per_model_worst


class TestQ097StaysBinding:
    """Q-09-7 = B's upstream half — INVERTED by Step 10 / P2b, not deleted.

    Until P2b these asserted that the record schema, the tuning output and
    production evaluation carried NO secondary anything: Step 09a deliberately
    built the receiving side empty, and a field appearing early would have meant
    C6 had drifted into Step 10's territory. P2b C2 is that territory, so each
    guard now asserts the POSITIVE claim it was holding the place for: the
    reserved names exist, EXACTLY those names, in exactly one owner each.

    The inversion is what keeps the original claim testable. "No secondary
    field" and "exactly the three reserved secondary fields" are both falsified
    by the same defect — a fourth field, a differently-spelled field, or a
    speculative reader elsewhere in the tree.
    """

    def test_the_record_carries_EXACTLY_the_three_reserved_names(self):
        """The names come from `SecondaryMetricEvidence`'s own docstring, which
        reserved them verbatim in Step 09a. A fourth carrier here would be the
        fourth scientific state Q-P2b-2 explicitly forbids."""
        assert sorted(
            name for name in ExperimentRecord.model_fields if name.startswith("secondary_")
        ) == [
            "secondary_metric_errors",
            "secondary_metric_refusals",
            "secondary_metric_results",
        ]

    def test_the_tuning_output_carries_EXACTLY_the_declared_spec_stamp(self):
        assert [
            name for name in HyperparamTuningOutput.model_fields if name.startswith("secondary_")
        ] == ["secondary_metric_specs"]

    @staticmethod
    def _secondary_evaluators_in(source: str) -> list[str]:
        """Every `def` whose NAME says it evaluates/scores/loads a secondary.

        One predicate over the whole name, used by both the census and its
        probe — a probe that restated the rule would be testing a copy.
        `secondar` rather than `secondary` so a plural (`_score_secondaries`)
        cannot slip past, and no anchoring so a prefix cannot either (F-P2b-4).
        """
        return [
            name
            for name in re.findall(r"def (\w+)\(", source)
            if "secondar" in name.lower() and re.search(r"evaluat|scor|load", name, re.I)
        ]

    def test_the_secondary_evaluator_has_exactly_one_owner(self):
        """The C2 half of the inversion (C1 inverted the binder half into
        `tests/unit/workflows/test_step10_p2b_c1_secondary_declaration.py`).

        A SECOND evaluator would be a second place a secondary outcome could
        come into existence — and the whole frozen exception taxonomy lives
        inside this one function, so a second one would silently not have it.

        F-P2b-4: the Step-09a census used two anchored alternations, one of
        which required the name to BEGIN with `evaluat`/`load`. The real
        evaluator is `_evaluate_secondary_metrics`, and a single leading
        underscore made the guard blind to it — so the census would have
        reported "no production module evaluates a secondary metric" while one
        did. The predicate below is stated once, over the whole name, with no
        anchoring and no assumption about which half comes first.
        """
        offenders: dict[str, list[str]] = {}
        for root in ("nodes", "agent", "core", "execute_tools", "workflows"):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                hits = self._secondary_evaluators_in(path.read_text(encoding="utf-8"))
                if hits:
                    offenders[path.relative_to(REPO_ROOT).as_posix()] = sorted(hits)
        assert offenders == {
            "nodes/ml_hyperparameter_tune_agent/execution.py": ["_evaluate_secondary_metrics"]
        }, f"secondary-metric evaluation must have exactly one owner: {offenders}"

    @pytest.mark.parametrize(
        "planted",
        [
            "def _evaluate_secondary_metrics(x):\n    pass\n",
            "def evaluate_secondary(x):\n    pass\n",
            "def _secondary_metric_scoring(x):\n    pass\n",
            "def load_secondary_metrics(x):\n    pass\n",
            "def __score_secondaries(x):\n    pass\n",
        ],
        ids=["private-evaluator", "public-evaluator", "scorer", "loader", "plural-dunder"],
    )
    def test_the_evaluator_census_sees_through_a_name_prefix(self, planted, tmp_path):
        """F-P2b-4's anti-vacuity half.

        The defect the old regex had was invisible precisely because the census
        was green. Each shape below is a second evaluator a future commit could
        plausibly add; all five must be seen.
        """
        assert self._secondary_evaluators_in(planted), f"the census would not have seen {planted!r}"
