"""Step 10 / P2b — C4: secondary evidence across the whole lifecycle.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2b_secondary_metric_transport.md`` §5, §6 C4.

The defect only this module catches
-----------------------------------
Every earlier commit proved ONE hop with the others stubbed. A transport can
have every hop individually correct and still lose evidence at a join — a
stamp written from one authority and read against another, a declared id that
survives composition but not persistence, a task whose zero-secondary path is
only ever exercised by a fixture that never declared anything.

So each synthetic declaration below is driven through the REAL chain, once, with nothing
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

The three declaration shapes are non-equivalent:

``absent``
    declares NOTHING. The absence path is first-class: no binding, no record
    keys, no stamp, no `_stats` key, ZERO rendered bytes.
``single``
    exactly one lower-is-better secondary.
``opposing``
    the discriminating case: one higher-is-better and one lower-is-better
    secondary, exercised across scored, refused, and unavailable states.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

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
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
from workflows.task_composition import (
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"
SECONDARY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"
PREFLIGHT = (
    REPO_ROOT
    / "tests"
    / "unit"
    / "agent"
    / "tune_ml_hyperparam_agent"
    / "fixtures"
    / "step00_preflight_results.json"
)

SECONDARY_REFS = {
    "band_bias": {
        "declaration": str(SECONDARY_FIXTURE / "declared" / "metric_band_bias.json"),
        "implementation": {
            "file": str(SECONDARY_FIXTURE / "plugins" / "secondary_metrics.py"),
            "symbol": "BandBiasMetric",
        },
    },
    "band_spread": {
        "declaration": str(SECONDARY_FIXTURE / "declared" / "metric_band_spread.json"),
        "implementation": {
            "file": str(SECONDARY_FIXTURE / "plugins" / "secondary_metrics.py"),
            "symbol": "BandSpreadMetric",
        },
    },
}


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

    def execute_scoring(self, exp_id: str, run_name: str, model_type: str, **kwargs):
        """Return a composed-child result without consuming a legacy FIFO."""
        self.calls.append(("execute_scoring", exp_id, model_type))
        secondary_results = []
        secondary_refusals = []
        secondary_errors = {}
        for metric_id, outcome in self.outcomes.items():
            direction = "higher" if metric_id == "band_spread" else "lower"
            if isinstance(outcome, NotScoreableError):
                secondary_refusals.append(outcome.result.model_dump(mode="json"))
            elif isinstance(outcome, Exception):
                secondary_errors[metric_id] = f"{type(outcome).__name__}: {outcome}"
            else:
                secondary_results.append(
                    MetricResult(
                        metric_id=metric_id,
                        direction=direction,
                        scalar=outcome,
                        per_sample=None,
                        references_used=(),
                    ).model_dump(mode="json")
                )
        return {
            "status": "success",
            "message": "Synthetic composed scoring completed.",
            "results": {
                "denoising_score": 0.65,
                "file_vector": [],
                "metric_result": MetricResult(
                    metric_id="quickstart_accuracy",
                    direction="higher",
                    scalar=0.65,
                    per_sample=None,
                    references_used=(),
                ).model_dump(mode="json"),
                "secondary_metric_results": secondary_results,
                "secondary_metric_refusals": secondary_refusals,
                "secondary_metric_errors": secondary_errors,
            },
        }

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


def _manifest_with_secondaries(tmp_path: Path, metric_ids: tuple[str, ...]) -> Path:
    package_root = tmp_path / "relocated_quickstart"
    manifest_dir = package_root / "configs" / "task_composition"
    manifest_dir.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "examples" / "quickstart", package_root / "examples" / "quickstart")
    manifest = yaml.safe_load(QUICKSTART.read_text(encoding="utf-8"))
    manifest["secondary_metrics"] = [SECONDARY_REFS[metric_id] for metric_id in metric_ids]
    path = manifest_dir / "composition.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


def _drive(
    metric_ids: tuple[str, ...], outcomes: dict[str, Any], tmp_path, monkeypatch
) -> dict[str, Any]:
    """Drive one synthetic declaration through the complete join."""
    from tests.helpers import recording_sandbox as _rs

    composition = compose_run_task_bindings(str(_manifest_with_secondaries(tmp_path, metric_ids)))
    composed = [(m.spec.id, m.spec.direction) for m in composition.secondary_metrics]

    # The C1 link, re-asserted here rather than assumed: the run-scoped binding
    # activates exactly what composition resolved.
    with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
        bound = [(m.spec.id, m.spec.direction) for m in resolve_bound_run_secondary_metrics()]
        _LifecycleSandbox.outcomes = dict(outcomes)
        monkeypatch.setattr(_rs, "RecordingSandbox", _LifecycleSandbox)
        preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))["results"]
        with bind_run_secondary_metrics(composition.secondary_metrics):
            output, _bridge, sandbox, _ws = run_bounded_pseudo_iteration(
                tmp_path,
                monkeypatch,
                preflight_results=preflight,
                input_overrides={"task_composition_ref": build_task_composition_ref(composition)},
            )

    scored = [r for r in output.all_records if r.metric_result is not None]
    assert scored, "the fixture must reach primary scoring, or nothing downstream is exercised"
    summary = tuning_output_to_model_run_summary(output, order=MetricOrder(composition.metric.spec))

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


class TestSecondaryLifecycleShapes:
    def test_absence_costs_zero_bytes(self, tmp_path, monkeypatch):
        state = _drive((), {}, tmp_path, monkeypatch)
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

    def test_single_secondary_survives_end_to_end(self, tmp_path, monkeypatch):
        state = _drive(("band_bias",), {"band_bias": 0.19}, tmp_path, monkeypatch)
        assert state["composed"] == [("band_bias", "lower")]
        assert state["bound"] == [("band_bias", "lower")]
        assert state["record_results"] == [
            [("band_bias", "lower", 0.19)] for _ in state["record_results"]
        ]
        assert state["record_keys_written"] == ["secondary_metric_results"]
        assert state["stamp"] == [("band_bias", "lower")]
        assert state["projected"] == [("band_bias", "lower", "scored")]
        assert len(state["rendered"]) == 1 and "band_bias" in state["rendered"][0]

    def test_opposing_directions_survive_end_to_end(self, tmp_path, monkeypatch):
        state = _drive(
            ("band_spread", "band_bias"),
            {"band_spread": 0.72, "band_bias": 0.08},
            tmp_path,
            monkeypatch,
        )
        assert state["composed"] == [("band_spread", "higher"), ("band_bias", "lower")]
        assert state["bound"] == state["composed"]
        assert state["record_results"] == [
            [("band_spread", "higher", 0.72), ("band_bias", "lower", 0.08)]
            for _ in state["record_results"]
        ]
        assert state["stamp"] == [("band_spread", "higher"), ("band_bias", "lower")]
        assert state["projected"] == [
            ("band_spread", "higher", "scored"),
            ("band_bias", "lower", "scored"),
        ]
        spread_line, bias_line = state["rendered"]
        assert "higher" in spread_line and "lower" not in spread_line, spread_line
        assert "lower" in bias_line and "higher" not in bias_line, bias_line

    def test_refused_and_unavailable_survive_one_run(self, tmp_path, monkeypatch):
        """One metric refuses and one crashes. The refusal is a scientific state; the
        crash is diagnostic provenance that projects as a NAMED absence — and
        both stay on the stamp, so neither silently disappears."""
        state = _drive(
            ("band_spread", "band_bias"),
            {
                "band_spread": NotScoreableError(_refusal("band_spread", "higher")),
                "band_bias": ValueError("boom"),
            },
            tmp_path,
            monkeypatch,
        )
        assert state["record_results"] == [[] for _ in state["record_results"]]
        assert state["record_refusals"] == [["band_spread"] for _ in state["record_refusals"]]
        assert state["record_errors"] == [
            {"band_bias": "ValueError: boom"} for _ in state["record_errors"]
        ]
        assert sorted(state["record_keys_written"]) == [
            "secondary_metric_errors",
            "secondary_metric_refusals",
        ]
        assert state["stamp"] == [("band_spread", "higher"), ("band_bias", "lower")]
        assert state["projected"] == [
            ("band_spread", "higher", "refused"),
            ("band_bias", "lower", "unavailable"),
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
