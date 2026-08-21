"""Step 10 / P2b — C2: secondaries EVALUATE, and their outcomes reach the record.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2b_secondary_metric_transport.md`` §4.2, §4.3, §6 C2; operator rulings
Q-P2b-1 (`WHEREVER_PRIMARY_EVALUATES`) and Q-P2b-2 (the exception taxonomy).

The defects only this module catches
------------------------------------
1. **A secondary breaking an attempt.** The whole claim is that observational
   evidence costs the primary nothing. Asserted by running the IDENTICAL
   bounded pseudo iteration with and without secondaries bound and requiring
   every attempt-lifecycle surface to be byte-identical — status, record count,
   per-record status sequence, primary payloads, the LLM call sequence.
2. **A crash dressed as science.** `NotScoreableResult` reports a CONTRACT
   verdict. An implementation crash produced no verdict, so recording one would
   fabricate a measurement. The two must land in different carriers.
3. **A framework-integrity failure swallowed.** `ScopeViolationError` is raised
   INSIDE `evaluate_metric` (DataScope validation is step 1 of every call), so a
   secondary can raise it. "Observational" bounds ordinary outcomes; it must not
   turn a non-retryable run-termination into a dictionary entry.
4. **Evidence leaking to the planner.** A second, differently-directed number
   beside the one being optimised is exactly the vote secondaries must not get.
5. **Collapsed identities.** Two secondaries evaluated under one id would make
   the record's join meaningless.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.dataset_config import ScopeViolationError
from execute_tools.evaluation_metric import (
    MetricResult,
    NotScoreableError,
    NotScoreableResult,
    bind_run_secondary_metrics,
)
from nodes.ml_hyperparameter_tune_agent.execution import _evaluate_secondary_metrics
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
from workflows.task_composition import compose_run_task_bindings

DAVIS_MANIFEST = "tests/fixtures/step10_p1/davis/composition.yaml"


@pytest.fixture(scope="module")
def davis_secondaries():
    """The REAL declared DAVIS pair — psnr (higher) and mae (lower).

    Composed through the production edge rather than hand-built, so these
    fixtures cannot drift from what a DAVIS run would actually bind.
    """
    secondaries = compose_run_task_bindings(DAVIS_MANIFEST).secondary_metrics
    assert [(m.spec.id, m.spec.direction) for m in secondaries] == [
        ("psnr", "higher"),
        ("mae", "lower"),
    ]
    return secondaries


def _refusal(metric_id: str, direction: str) -> NotScoreableResult:
    return NotScoreableResult(
        metric_id=metric_id,
        direction=direction,
        verdict={
            "contract_id": "deliverable_presence",
            "failures": [{"requirement": "deliverable_exists", "detail": "absent"}],
        },
    )


# ---------------------------------------------------------------------------
# 1. The frozen exception taxonomy, at the boundary that owns it
# ---------------------------------------------------------------------------


class _ScriptedSandbox:
    """Minimal sandbox: one scripted outcome per metric id, calls recorded."""

    def __init__(self, outcomes: dict[str, object]):
        self.outcomes = outcomes
        self.seen: list[str] = []

    def evaluate_metric(self, metric, *, sample_set, anchor_map, s_max, denoised_filename_fn):
        self.seen.append(metric.spec.id)
        outcome = self.outcomes[metric.spec.id]
        if isinstance(outcome, Exception):
            raise outcome
        return MetricResult(
            metric_id=metric.spec.id,
            direction=metric.spec.direction,
            scalar=outcome,
            per_sample=None,
            references_used=(),
        )


def _evaluate(secondaries, outcomes):
    sandbox = _ScriptedSandbox(outcomes)
    return sandbox, _evaluate_secondary_metrics(
        sandbox,
        secondaries,
        sample_set={0: [0]},
        anchor_map={},
        s_max=1.0,
        denoised_filename_fn=lambda i: f"/tmp/{i}.h5",
    )


class TestTheFrozenExceptionTaxonomy:
    def test_each_secondary_is_evaluated_under_its_OWN_identity(self, davis_secondaries):
        sandbox, (results, refusals, errors) = _evaluate(
            davis_secondaries, {"psnr": 31.5, "mae": 0.017}
        )
        assert sandbox.seen == ["psnr", "mae"]
        assert [(r.metric_id, r.direction, r.scalar) for r in results] == [
            ("psnr", "higher", 31.5),
            ("mae", "lower", 0.017),
        ]
        assert (refusals, errors) == ([], {})

    def test_a_refusal_is_a_typed_scientific_outcome(self, davis_secondaries):
        _s, (results, refusals, errors) = _evaluate(
            davis_secondaries,
            {"psnr": 31.5, "mae": NotScoreableError(_refusal("mae", "lower"))},
        )
        assert [r.metric_id for r in results] == ["psnr"]
        assert [r.metric_id for r in refusals] == ["mae"]
        assert refusals[0].verdict.contract_id == "deliverable_presence"
        assert errors == {}

    def test_a_crash_is_diagnostic_provenance_and_NEVER_a_refusal(self, davis_secondaries):
        _s, (results, refusals, errors) = _evaluate(
            davis_secondaries, {"psnr": 31.5, "mae": ValueError("shape mismatch")}
        )
        assert [r.metric_id for r in results] == ["psnr"]
        assert refusals == [], (
            "a crash produced no contract verdict; recording one would fabricate "
            "a measurement nothing made"
        )
        assert errors == {"mae": "ValueError: shape mismatch"}

    def test_a_scope_violation_is_RE_RAISED_not_downgraded(self, davis_secondaries):
        """The bounded meaning of "observational" (Q-P2b-2), and the CATCH ORDER.

        DataScope validation runs inside EVERY `evaluate_metric` call, so a
        secondary can raise this. It must reach the outer handler that
        terminates the run, never a `secondary_metric_errors` entry — a
        framework-integrity failure is not an ordinary secondary outcome.

        This is also the ORDER test, and the assertion below is why it
        discriminates: `ScopeViolationError` IS a `ValueError`, so swapping the
        two `except` clauses would silently convert a non-retryable run
        termination into a harmless-looking dictionary entry. With the subclass
        relation asserted, "it was re-raised" can only be true if the narrow
        clause comes first.
        """
        assert issubclass(ScopeViolationError, ValueError), (
            "the catch-order claim below depends on this relation; if it ever "
            "stops holding, the ordering constraint must be re-derived"
        )
        sandbox = _ScriptedSandbox({"psnr": ScopeViolationError("file 7 outside scope")})
        with pytest.raises(ScopeViolationError, match="outside scope"):
            _evaluate_secondary_metrics(
                sandbox,
                davis_secondaries,
                sample_set={0: [0]},
                anchor_map={},
                s_max=1.0,
                denoised_filename_fn=lambda i: "",
            )

    def test_one_secondary_crashing_does_not_stop_the_others(self, davis_secondaries):
        sandbox, (results, _refusals, errors) = _evaluate(
            davis_secondaries, {"psnr": RuntimeError("boom"), "mae": 0.017}
        )
        assert sandbox.seen == ["psnr", "mae"]
        assert [r.metric_id for r in results] == ["mae"]
        assert set(errors) == {"psnr"}

    def test_no_declared_secondary_means_no_work_and_no_evidence(self):
        sandbox, (results, refusals, errors) = _evaluate((), {})
        assert (sandbox.seen, results, refusals, errors) == ([], [], [], {})

    def test_a_crash_is_reported_on_the_diagnostic_surface(self, davis_secondaries, capsys):
        _evaluate(davis_secondaries, {"psnr": 31.5, "mae": ValueError("boom")})
        printed = capsys.readouterr().out
        assert "mae" in printed and "crashed" in printed, (
            "a secondary crash must never be silent — it is an operator-facing "
            f"fact about the implementation: {printed!r}"
        )


# ---------------------------------------------------------------------------
# 2. The record and output carriers
# ---------------------------------------------------------------------------


class TestTheRecordCarriers:
    BASE: ClassVar[dict[str, Any]] = {
        "exp_id": "e",
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-21T00:00:00Z",
        "params": {},
        "denoising_score": -2.0,
        "health_gate_enabled": False,
    }

    def test_a_record_carrying_all_three_survives_a_json_round_trip(self):
        record = ExperimentRecord.model_validate(
            {
                **self.BASE,
                "secondary_metric_results": [
                    {"metric_id": "psnr", "direction": "higher", "scalar": 31.5}
                ],
                "secondary_metric_refusals": [_refusal("mae", "lower").model_dump()],
                "secondary_metric_errors": {"macro_f1": "ValueError: boom"},
            }
        )
        assert ExperimentRecord.model_validate(json.loads(record.model_dump_json())) == record

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (
                {
                    "secondary_metric_results": [
                        {"metric_id": "psnr", "direction": "higher", "scalar": 1.0}
                    ],
                    "secondary_metric_errors": {"psnr": "boom"},
                },
                "in both secondary_metric_results and secondary_metric_errors",
            ),
            (
                {
                    "secondary_metric_results": [
                        {"metric_id": "psnr", "direction": "higher", "scalar": 1.0},
                        {"metric_id": "psnr", "direction": "higher", "scalar": 2.0},
                    ]
                },
                "twice in secondary_metric_results",
            ),
            (
                {
                    "secondary_metric_results": [
                        {"metric_id": "psnr", "direction": "higher", "scalar": 1.0}
                    ],
                    "secondary_metric_refusals": [_refusal("psnr", "higher").model_dump()],
                },
                "in both secondary_metric_results and secondary_metric_refusals",
            ),
        ],
        ids=["result-and-error", "duplicate-result", "result-and-refusal"],
    )
    def test_one_id_has_exactly_one_outcome(self, payload, expected):
        with pytest.raises(ValueError, match=expected):
            ExperimentRecord.model_validate({**self.BASE, **payload})

    def test_a_legacy_record_validates_with_all_three_absent(self):
        record = ExperimentRecord.model_validate(self.BASE)
        assert (
            record.secondary_metric_results,
            record.secondary_metric_refusals,
            record.secondary_metric_errors,
        ) == ([], [], {})

    @pytest.mark.parametrize("stamp", [None, []], ids=["null", "empty-list"])
    def test_absent_null_and_empty_are_equivalent_on_the_output_stamp(self, stamp):
        """§4.7's frozen read contract. A consumer that treated `[]` as "declared
        nothing" and `null` as "legacy" would classify the same run two ways."""
        base = {
            "run_name": "r",
            "model_type": "wavenet",
            "file_index": 6,
            "status": "completed",
            "completed_rounds": 1,
            "total_attempts": 1,
            "started_at": "a",
            "finished_at": "b",
        }
        absent = HyperparamTuningOutput.model_validate(base)
        explicit = HyperparamTuningOutput.model_validate({**base, "secondary_metric_specs": stamp})
        assert not absent.secondary_metric_specs
        assert not explicit.secondary_metric_specs


# ---------------------------------------------------------------------------
# 3. The production lifecycle, through the real tuner
# ---------------------------------------------------------------------------


class _SecondaryScriptedSandbox(RecordingSandbox):
    """`RecordingSandbox` plus a scripted outcome per SECONDARY metric id.

    The primary keeps the shared helper's canned FIFO untouched, so the
    with/without comparison below differs in exactly one thing: whether
    secondaries were bound.
    """

    secondary_outcomes: ClassVar[dict[str, Any]] = {}
    secondary_calls: ClassVar[list[tuple[str, str]]] = []

    def evaluate_metric(self, metric, sample_set, anchor_map, s_max, denoised_filename_fn, **kw):
        if metric.spec.id in self.secondary_outcomes:
            self.secondary_calls.append((metric.spec.id, metric.spec.direction))
            outcome = self.secondary_outcomes[metric.spec.id]
            if isinstance(outcome, Exception):
                raise outcome
            return MetricResult(
                metric_id=metric.spec.id,
                direction=metric.spec.direction,
                scalar=outcome,
                per_sample=None,
                references_used=(),
            )
        return super().evaluate_metric(
            metric, sample_set, anchor_map, s_max, denoised_filename_fn, **kw
        )


def _run(tmp_path, monkeypatch, secondaries, outcomes):
    """One bounded pseudo iteration, optionally with secondaries bound."""
    import json as _json
    from pathlib import Path

    from tests.helpers import recording_sandbox as _rs

    preflight = _json.loads(
        (Path(__file__).parent / "fixtures" / "step00_preflight_results.json").read_text(
            encoding="utf-8"
        )
    )["results"]

    _SecondaryScriptedSandbox.secondary_outcomes = dict(outcomes)
    _SecondaryScriptedSandbox.secondary_calls = []
    # Patched on the SOURCE module: the helper imports the name inside its
    # function body, so this is the binding it actually resolves.
    monkeypatch.setattr(_rs, "RecordingSandbox", _SecondaryScriptedSandbox)
    with bind_run_secondary_metrics(secondaries):
        output, bridge, sandbox, _workspace = run_bounded_pseudo_iteration(
            tmp_path, monkeypatch, preflight_results=preflight
        )
    return output, bridge, sandbox, list(_SecondaryScriptedSandbox.secondary_calls)


def _lifecycle(output, bridge):
    """Every attempt-lifecycle surface, in one comparable structure.

    Deliberately EXCLUDES the three new record keys and the output stamp —
    those are the declared delta. Everything else must be identical.
    """
    return {
        "status": output.status,
        "termination_reason": output.termination_reason,
        "completed_rounds": output.completed_rounds,
        "total_attempts": output.total_attempts,
        "record_statuses": [r.status for r in output.all_records],
        "record_scores": [r.denoising_score for r in output.all_records],
        "primary_payloads": [
            r.metric_result.model_dump() if r.metric_result else None for r in output.all_records
        ],
        "best_denoising_score": output.best_denoising_score,
        "llm_call_labels": [c[0] for c in bridge.calls],
    }


class TestTheProductionLifecycle:
    def test_the_declared_family_is_evaluated_and_lands_on_every_scored_record(
        self, tmp_path, monkeypatch, davis_secondaries
    ):
        output, _bridge, _sandbox, calls = _run(
            tmp_path, monkeypatch, davis_secondaries, {"psnr": 31.5, "mae": 0.017}
        )
        scored = [r for r in output.all_records if r.metric_result is not None]
        assert scored, "the fixture must produce at least one primary-scored record"

        # The STATE SEQUENCE, not "the field is populated": which ids landed in
        # which carrier, on which records, in which order.
        assert [
            [(s.metric_id, s.direction, s.scalar) for s in r.secondary_metric_results]
            for r in scored
        ] == [[("psnr", "higher", 31.5), ("mae", "lower", 0.017)] for _ in scored]
        assert all(r.secondary_metric_refusals == [] for r in scored)
        assert all(r.secondary_metric_errors == {} for r in scored)
        # Q-P2b-1: evaluated wherever the primary evaluates — once per scored
        # record, for BOTH trial and formal rounds, with no round-type branch.
        assert calls == [("psnr", "higher"), ("mae", "lower")] * len(scored)
        assert {r.is_trial for r in scored} == {True, False}, (
            "the fixture must exercise both a trial and a formal scored round, "
            "or Q-P2b-1's 'no round-type branch' claim is untested"
        )

    def test_the_output_stamps_the_DECLARED_set_in_order(
        self, tmp_path, monkeypatch, davis_secondaries
    ):
        output, *_ = _run(tmp_path, monkeypatch, davis_secondaries, {"psnr": 31.5, "mae": 0.017})
        assert output.secondary_metric_specs is not None
        assert [(s.id, s.direction) for s in output.secondary_metric_specs] == [
            ("psnr", "higher"),
            ("mae", "lower"),
        ]

    def test_a_mixed_outcome_run_records_each_id_in_its_own_carrier(
        self, tmp_path, monkeypatch, davis_secondaries
    ):
        output, *_ = _run(
            tmp_path,
            monkeypatch,
            davis_secondaries,
            {"psnr": NotScoreableError(_refusal("psnr", "higher")), "mae": ValueError("boom")},
        )
        scored = [r for r in output.all_records if r.metric_result is not None]
        assert scored
        for record in scored:
            assert record.secondary_metric_results == []
            assert [r.metric_id for r in record.secondary_metric_refusals] == ["psnr"]
            assert record.secondary_metric_errors == {"mae": "ValueError: boom"}
            # Both ids stay DECLARED on the stamp, so the interpreter can still
            # name them — a refused or crashed secondary is not an undeclared one.
        assert [s.id for s in output.secondary_metric_specs] == ["psnr", "mae"]

    def test_the_attempt_lifecycle_is_byte_identical_with_and_without_secondaries(
        self, tmp_path, monkeypatch, davis_secondaries
    ):
        """The claim that makes "observational" safe, measured on the outcome
        rather than on prints. A refusal AND a crash are in play, so this also
        covers the paths most likely to disturb an attempt."""
        with monkeypatch.context() as m:
            without, bridge_a, _s, calls = _run(tmp_path / "a", m, (), {})
        assert calls == []
        with monkeypatch.context() as m:
            with_secondaries, bridge_b, _s, _c = _run(
                tmp_path / "b",
                m,
                davis_secondaries,
                {"psnr": 31.5, "mae": ValueError("boom")},
            )
        assert _lifecycle(with_secondaries, bridge_b) == _lifecycle(without, bridge_a)

    def test_a_zero_secondary_run_writes_no_secondary_record_keys(self, tmp_path, monkeypatch):
        """§4.7's record half: the builder controls the record dict key-by-key,
        so a run that declared nothing produces the pre-P2b record verbatim."""
        _output, _bridge, sandbox, _calls = _run(tmp_path, monkeypatch, (), {})
        assert sandbox.saved_records
        offenders = [
            (r.get("exp_id"), k)
            for r in sandbox.saved_records
            for k in r
            if k.startswith("secondary_")
        ]
        assert offenders == [], offenders


# ---------------------------------------------------------------------------
# 4. The evidence stays out of the LLM's hands
# ---------------------------------------------------------------------------


class TestTheHiddenPayloadBoundary:
    RECORD: ClassVar[dict[str, Any]] = {
        "exp_id": "e1",
        "status": "success",
        "denoising_score": -2.0,
        "metric_result": {"metric_id": "m", "direction": "higher", "scalar": -2.0},
        "secondary_metric_results": [{"metric_id": "psnr", "direction": "higher", "scalar": 31.5}],
        "secondary_metric_refusals": [],
        "secondary_metric_errors": {"mae": "ValueError: boom"},
    }

    def test_the_planner_prompt_carries_none_of_the_three_keys(self):
        """Asserted on the SERIALIZED prompt text, not on the mechanism's
        docstring: the hidden-key set is an enumerated frozenset, so a new
        record key is visible by default until someone adds it."""
        from agent.prompts import get_planner_user_prompt

        prompt = get_planner_user_prompt(
            memory_history=[dict(self.RECORD)],
            expert_advice="None",
            current_round=2,
            max_rounds=2,
        )
        for key in (
            "secondary_metric_results",
            "secondary_metric_refusals",
            "secondary_metric_errors",
        ):
            assert key not in prompt, f"the planner prompt renders {key}"
        assert "psnr" not in prompt and "31.5" not in prompt
        assert "boom" not in prompt
        # ...while the planner still sees the record it is supposed to reason
        # about, so this is an exclusion test and not an empty-prompt test.
        assert "e1" in prompt

    def test_the_reflector_sees_only_the_scoring_results_dict(self):
        """The reflector's payload is `{**train_results, **score_results}`, and
        secondaries never enter `score_res["results"]` — so this surface is safe
        BY CONSTRUCTION rather than by a filter. Pinned, because a future commit
        adding them to that dict would be silent."""
        import inspect
        from importlib import import_module

        # `import_module`, not `from ... import`: the package rebinds
        # `sys.modules[__name__]` to the main module, so the attribute form
        # resolves one level too deep (the note at `execution.py`'s own
        # `_records` import).
        execution = import_module("nodes.ml_hyperparameter_tune_agent.execution")

        source = inspect.getsource(execution.run_inference_scoring_health)
        results_block = source[source.index("score_res = {") :]
        results_block = results_block[: results_block.index("            }")]
        assert "secondary" not in results_block, (
            "a secondary reached `score_res['results']`, which is json-dumped "
            "verbatim into the reflector prompt"
        )
