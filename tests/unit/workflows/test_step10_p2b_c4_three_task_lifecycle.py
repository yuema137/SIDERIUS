"""Step 10 / P2b — C4: the whole lifecycle, on all three tasks.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2b_secondary_metric_transport.md`` §5, §6 C4.

The defect only this module catches
-----------------------------------
Every earlier commit proved ONE hop with the others stubbed. A transport can
have every hop individually correct and still lose evidence at a join — a
stamp written from one authority and read against another, a declared id that
survives composition but not persistence, a task whose zero-secondary path is
only ever exercised by a fixture that never declared anything.

So each task below is driven through the REAL chain, once, with nothing
hand-assembled in between:

```text
compose the task's own manifest
  -> bind for the run
  -> the real tuner (pseudo mode) evaluates and records
  -> the real output stamp
  -> the real interpreter projection
  -> the real 09b renderer
```

and the assertion is the STATE SEQUENCE the whole chain produced, not a
spot-check at the end.

The three tasks are chosen to be non-equivalent, per §5:

``tidmad``
    declares NOTHING. The absence path is first-class: no binding, no record
    keys, no stamp, no `_stats` key, ZERO rendered bytes.
``pets``
    exactly one secondary (`macro_f1`, higher). `log_loss` stays D16-owned and
    must not appear.
``davis``
    the discriminating case: `psnr` (higher) and `mae` (lower) beside a `mse`
    primary that is lower-is-better, exercised across scored, refused and
    unavailable in one run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from agent.prompt_templates.interpretation.rendering import render_secondary_metrics
from execute_tools.evaluation_metric import (
    MetricResult,
    NotScoreableError,
    NotScoreableResult,
    bind_run_secondary_metrics,
    resolve_bound_run_secondary_metrics,
)
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import shipped_spec
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "step10_p1"
PREFLIGHT = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "unit"
    / "agent"
    / "tune_ml_hyperparam_agent"
    / "fixtures"
    / "step00_preflight_results.json"
)
ORDER = MetricOrder(shipped_spec())


def _refusal(metric_id: str, direction: str) -> NotScoreableResult:
    return NotScoreableResult(
        metric_id=metric_id,
        direction=direction,
        verdict={
            "contract_id": "deliverable_presence",
            "failures": [{"requirement": "deliverable_exists", "detail": "absent"}],
        },
    )


class _LifecycleSandbox(RecordingSandbox):
    """One scripted outcome per SECONDARY id; the primary keeps its canned FIFO."""

    outcomes: ClassVar[dict[str, Any]] = {}

    def evaluate_metric(self, metric, sample_set, anchor_map, s_max, denoised_filename_fn, **kw):
        if metric.spec.id in self.outcomes:
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
        return super().evaluate_metric(
            metric, sample_set, anchor_map, s_max, denoised_filename_fn, **kw
        )


def _drive(task: str, outcomes: dict[str, Any], tmp_path, monkeypatch) -> dict[str, Any]:
    """The whole chain for ONE task; returns its observed state sequence."""
    from tests.helpers import recording_sandbox as _rs

    composition = compose_run_task_bindings(str(FIXTURES / task / "composition.yaml"))
    composed = [(m.spec.id, m.spec.direction) for m in composition.secondary_metrics]

    # The C1 link, re-asserted here rather than assumed: the run-scoped binding
    # activates exactly what composition resolved.
    with bind_run_task_composition(composition):
        bound = [(m.spec.id, m.spec.direction) for m in resolve_bound_run_secondary_metrics()]

    _LifecycleSandbox.outcomes = dict(outcomes)
    monkeypatch.setattr(_rs, "RecordingSandbox", _LifecycleSandbox)
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))["results"]
    with bind_run_secondary_metrics(composition.secondary_metrics):
        output, _bridge, sandbox, _ws = run_bounded_pseudo_iteration(
            tmp_path, monkeypatch, preflight_results=preflight
        )

    scored = [r for r in output.all_records if r.metric_result is not None]
    assert scored, "the fixture must reach primary scoring, or nothing downstream is exercised"
    summary = tuning_output_to_model_run_summary(output, order=ORDER)

    return {
        "composed": composed,
        "bound": bound,
        "record_results": [
            [(s.metric_id, s.direction, s.scalar) for s in r.secondary_metric_results]
            for r in scored
        ],
        "record_refusals": [[s.metric_id for s in r.secondary_metric_refusals] for r in scored],
        "record_errors": [dict(r.secondary_metric_errors) for r in scored],
        "record_keys_written": sorted(
            {k for r in sandbox.saved_records for k in r if k.startswith("secondary_")}
        ),
        "stamp": (
            [(s.id, s.direction) for s in output.secondary_metric_specs]
            if output.secondary_metric_specs
            else None
        ),
        "projected": [(e.spec.id, e.spec.direction, e.status) for e in summary.secondary_metrics],
        "rendered": render_secondary_metrics(summary.secondary_metrics),
    }


class TestTheThreeTaskLifecycle:
    def test_tidmad_declares_nothing_and_the_absence_costs_ZERO_bytes(self, tmp_path, monkeypatch):
        state = _drive("tidmad", {}, tmp_path, monkeypatch)
        assert state["composed"] == []
        assert state["bound"] == []
        assert all(entry == [] for entry in state["record_results"])
        assert all(entry == [] for entry in state["record_refusals"])
        assert all(entry == {} for entry in state["record_errors"])
        assert state["record_keys_written"] == [], (
            "a task that declared no secondary must write no secondary record "
            "key at all — its records stay byte-identical to their pre-P2b form"
        )
        assert state["stamp"] is None
        assert state["projected"] == []
        assert state["rendered"] == [], (
            "no declared secondary must render no line — not an empty section, "
            "which would still cost prompt bytes"
        )

    def test_pets_carries_exactly_macro_f1_end_to_end(self, tmp_path, monkeypatch):
        state = _drive("pets", {"macro_f1": 0.81}, tmp_path, monkeypatch)
        assert state["composed"] == [("macro_f1", "higher")]
        assert state["bound"] == [("macro_f1", "higher")]
        assert state["record_results"] == [
            [("macro_f1", "higher", 0.81)] for _ in state["record_results"]
        ]
        assert state["record_keys_written"] == ["secondary_metric_results"]
        assert state["stamp"] == [("macro_f1", "higher")]
        assert state["projected"] == [("macro_f1", "higher", "scored")]
        assert len(state["rendered"]) == 1 and "macro_f1" in state["rendered"][0]
        assert "log_loss" not in json.dumps(state), (
            "log_loss stays D16 / Step-06-owned (Q-10-4 = A) and must not be "
            "activated by P2b anywhere in the lifecycle"
        )

    def test_davis_carries_two_OPPOSING_directions_beside_a_lower_primary(
        self, tmp_path, monkeypatch
    ):
        """The discriminating case. `psnr` is higher-is-better, `mae` is lower,
        and the primary is lower — so nothing here can be produced by
        inheriting a single direction from anywhere."""
        state = _drive("davis", {"psnr": 31.5, "mae": 0.017}, tmp_path, monkeypatch)
        assert state["composed"] == [("psnr", "higher"), ("mae", "lower")]
        assert state["bound"] == state["composed"]
        assert state["record_results"] == [
            [("psnr", "higher", 31.5), ("mae", "lower", 0.017)] for _ in state["record_results"]
        ]
        assert state["stamp"] == [("psnr", "higher"), ("mae", "lower")]
        assert state["projected"] == [
            ("psnr", "higher", "scored"),
            ("mae", "lower", "scored"),
        ]
        psnr_line, mae_line = state["rendered"]
        assert "higher" in psnr_line and "lower" not in psnr_line, psnr_line
        assert "lower" in mae_line and "higher" not in mae_line, mae_line

    def test_davis_exercises_refused_and_unavailable_in_ONE_run(self, tmp_path, monkeypatch):
        """`psnr` refuses, `mae` crashes. The refusal is a scientific state; the
        crash is diagnostic provenance that projects as a NAMED absence — and
        both stay on the stamp, so neither silently disappears."""
        state = _drive(
            "davis",
            {"psnr": NotScoreableError(_refusal("psnr", "higher")), "mae": ValueError("boom")},
            tmp_path,
            monkeypatch,
        )
        assert state["record_results"] == [[] for _ in state["record_results"]]
        assert state["record_refusals"] == [["psnr"] for _ in state["record_refusals"]]
        assert state["record_errors"] == [
            {"mae": "ValueError: boom"} for _ in state["record_errors"]
        ]
        assert sorted(state["record_keys_written"]) == [
            "secondary_metric_errors",
            "secondary_metric_refusals",
        ]
        assert state["stamp"] == [("psnr", "higher"), ("mae", "lower")]
        assert state["projected"] == [
            ("psnr", "higher", "refused"),
            ("mae", "lower", "unavailable"),
        ]
        refused_line, absent_line = state["rendered"]
        assert "deliverable_presence" in refused_line
        assert "boom" not in absent_line, (
            "a crash diagnostic is operator-facing provenance and must not "
            "reach an LLM-facing render"
        )


class TestTheObservationalInvariantAtTheFinalHead:
    """§4.6 re-proved over the FINISHED surface, plus its anti-vacuity plant."""

    def test_no_ordering_expression_takes_a_secondary_operand(self):
        from tests.unit.agent.result_interpretation_agent.test_step09a_c6_evidence_projection import (
            TestSecondariesCannotReachOrdering as Census,
        )

        repo_root = Path(__file__).resolve().parents[3]
        offenders = {
            rel: hits
            for rel in Census.SCANNED_FILES
            if (
                hits := Census._secondaries_in_ordering_expressions(
                    (repo_root / rel).read_text(encoding="utf-8")
                )
            )
        }
        assert offenders == {}, offenders

    @pytest.mark.parametrize(
        "rel",
        [
            "workflows/task_composition.py",
            "execute_tools/evaluation_metric.py",
            "nodes/ml_hyperparameter_tune_agent/execution.py",
            "nodes/result_interpretation_agent/evidence.py",
            "nodes/result_interpretation_agent/result_interpretation_agent.py",
        ],
        ids=["composition", "binding", "evaluation", "projection", "carry"],
    )
    def test_a_planted_offender_is_caught_in_each_file_P2b_ACTUALLY_changed(self, rel):
        """The C4 anti-vacuity half, aimed at the files this PR really touched
        rather than at the whole declared scope. A census green because it read
        a file P2b never modified would prove nothing about P2b."""
        from tests.unit.agent.result_interpretation_agent.test_step09a_c6_evidence_projection import (
            TestSecondariesCannotReachOrdering as Census,
        )

        repo_root = Path(__file__).resolve().parents[3]
        source = (repo_root / rel).read_text(encoding="utf-8")
        planted = (
            "\n\ndef _p2b_c4_probe(a, b, models, order):\n"
            "    if a.secondary_metric_results[0].scalar > b.secondary_metric_results[0].scalar:\n"
            "        return order.best(models, key=lambda m: m.secondary_metric_results[0].scalar)\n"
            "    return sorted(models, key=lambda m: m.secondary_metric_results[0].scalar)\n"
        )
        assert Census._secondaries_in_ordering_expressions(source + planted), rel
        assert Census._secondaries_in_ordering_expressions(source) == [], (
            f"{rel} already contains a secondary ordering operand"
        )
