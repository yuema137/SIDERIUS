"""Step 09a — C2: the run's MetricSpec leaves the tuner, once, intact.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.2, §4.3.

Before Step 09a the tuner resolved a ``MetricSpec`` at run scope and it went
NOWHERE: ``HyperparamTuningOutput`` carried scores, configs and records, but not
the identity or the DIRECTION they were scored under. The interpreter, one node
downstream, therefore had no choice but to assume "higher is better" — which is
silently wrong for any lower-is-better metric.

C2 transports that already-resolved value. What only these tests catch:

* the live tuner path actually WRITES ``bindings.run_metric.spec`` onto the
  output — a schema field nothing populates is dead weight;
* the persisted JSON re-validates to an EQUAL spec. This is not free: a
  ``MetricSpec`` cannot re-validate its own dump (the abstract
  ``scoreability`` field), so the round trip only works because the field
  routes mappings through the ONE sanctioned rebind;
* the DEGRADED output carries it too — the metric binding is a launch fact and
  does not stop existing because the tuner later failed;
* a genuinely pre-Step-09a artifact still validates, reading ``None``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from execute_tools.evaluation_metric import (
    MetricSpec,
    metric_spec_from_declaration,
)
from execute_tools.scoring_utils import coerce_nonfinite_to_none
from tests.helpers.metric_fixtures import accuracy_like_spec
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

_HERE = Path(__file__).parent
_PREFLIGHT_FIXTURE = _HERE / "fixtures" / "step00_preflight_results.json"
_REPLAY_WS = _HERE.parents[1] / "core" / "fixtures" / "step00_replay_workspace" / "iter_001"
FIXTURE_METRIC_ID = "fixture_accuracy"


@pytest.fixture(scope="module")
def pseudo_run(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("step09a_c2")
    try:
        output, bridge, sandbox, workspace = run_bounded_pseudo_iteration(
            tmp, mp, preflight_results=preflight
        )
    finally:
        mp.undo()
    return output, bridge, sandbox, workspace


class TestTheLivePathStampsTheRunSpec:
    def test_the_output_carries_the_runs_bound_spec(self, pseudo_run):
        output, _bridge, _sandbox, _ws = pseudo_run
        assert output.metric_spec is not None, (
            "finalize_run_output did not stamp the run's MetricSpec — the "
            "interpreter would have to re-derive a metric, which Step 09 forbids"
        )
        # Hardcoded expectation, not read back off the output.
        assert output.metric_spec.id == FIXTURE_METRIC_ID
        assert output.metric_spec.direction == "higher"
        assert output.metric_spec == accuracy_like_spec()

    def test_the_persisted_json_revalidates_to_an_equal_spec(self, pseudo_run):
        """The round trip the transport depends on, through the REAL writer's
        serialization path (``coerce_nonfinite_to_none`` -> ``json``)."""
        output, _bridge, _sandbox, _ws = pseudo_run
        on_disk = json.loads(json.dumps(coerce_nonfinite_to_none(output.model_dump())))
        reloaded = HyperparamTuningOutput.model_validate(on_disk)
        assert reloaded.metric_spec == output.metric_spec
        assert reloaded.metric_spec is not None
        assert reloaded.metric_spec.scoreability == output.metric_spec.scoreability, (
            "the executable scoreability contract did not survive the round trip"
        )

    def test_the_written_run_output_file_carries_it(self, pseudo_run):
        """Reachability through the FILE the workflow and resume actually read."""
        output, _bridge, _sandbox, workspace = pseudo_run
        path = Path(workspace) / f"run_output_{output.run_name}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["metric_spec"]["id"] == FIXTURE_METRIC_ID
        assert payload["metric_spec"]["direction"] == "higher"


class TestTheDegradedWriterKeepsTheLaunchFact:
    """The partial output is written when serialization fails — and it must
    still carry the run's metric binding.

    The rule is the one the ``healthgate_mode`` comment beside it already
    states: a LAUNCH fact does not stop existing because the tuner later
    failed. Gate 2 attempt 1 caught exactly this class of bug once already
    (a real run launched with ``--healthgate_mode blocking`` wrote
    ``healthgate_mode: null`` because it failed).

    Forced at ``coerce_nonfinite_to_none`` — the single call site, reached
    only on the healthy branch, immediately after validation. That makes the
    REAL ``finalize_run_output`` take its REAL except path rather than a
    simulated one.
    """

    def test_the_partial_output_carries_the_metric_spec(self, tmp_path_factory):
        import importlib

        from _pytest.monkeypatch import MonkeyPatch

        # The tuner package rebinds sys.modules to its MAIN module, so a
        # private submodule is reached by dotted path (the repo convention).
        _records = importlib.import_module("nodes.ml_hyperparameter_tune_agent.records")

        preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
        mp = MonkeyPatch()
        tmp = tmp_path_factory.mktemp("step09a_c2_degraded")

        def _boom(_payload):
            raise RuntimeError("forced serialization failure")

        try:
            mp.setattr(_records, "coerce_nonfinite_to_none", _boom)
            output, _bridge, _sandbox, workspace = run_bounded_pseudo_iteration(
                tmp, mp, preflight_results=preflight
            )
        finally:
            mp.undo()

        payload = json.loads(
            (Path(workspace) / f"run_output_{output.run_name}.json").read_text(encoding="utf-8")
        )
        assert "_partial_reason" in payload, (
            "the degraded writer did not run — this test proved nothing about it"
        )
        assert payload["metric_spec"]["id"] == FIXTURE_METRIC_ID
        assert payload["metric_spec"]["direction"] == "higher"
        # The re-validated in-memory output the caller receives carries it too.
        assert output.metric_spec == accuracy_like_spec()


class TestTheCarrierSurvivesItsOwnDump:
    """The finding that forced ``MetricSpecField`` to exist."""

    def test_a_bare_metric_spec_cannot_revalidate_its_own_dump(self):
        """Anti-vacuity for the field: if this ever STOPS raising, the
        BeforeValidator is no longer load-bearing and the extra machinery
        should be reconsidered rather than kept out of habit."""
        spec = accuracy_like_spec()
        with pytest.raises((TypeError, ValidationError)) as excinfo:
            MetricSpec.model_validate(spec.model_dump())
        if isinstance(excinfo.value, ValidationError):
            assert "extra_forbidden" in str(excinfo.value) or "Extra inputs" in str(excinfo.value)

    def test_the_field_accepts_an_instance_a_mapping_and_rejects_garbage(self):
        spec = accuracy_like_spec()

        from_instance = HyperparamTuningOutput.model_validate(
            _minimal_output_dict() | {"metric_spec": spec}
        )
        assert from_instance.metric_spec == spec

        from_mapping = HyperparamTuningOutput.model_validate(
            _minimal_output_dict() | {"metric_spec": json.loads(json.dumps(spec.model_dump()))}
        )
        assert from_mapping.metric_spec == spec

        assert (
            HyperparamTuningOutput.model_validate(
                _minimal_output_dict() | {"metric_spec": None}
            ).metric_spec
            is None
        )

        with pytest.raises(ValidationError):
            HyperparamTuningOutput.model_validate(
                _minimal_output_dict() | {"metric_spec": "not_a_metric_declaration"}
            )

    def test_the_field_uses_the_one_sanctioned_rebind(self):
        """The mapping path must be EXACTLY ``metric_spec_from_declaration`` —
        the equality below is what makes 'no second construction path' checkable
        rather than merely asserted in a comment."""
        spec = accuracy_like_spec()
        declared = json.loads(json.dumps(spec.model_dump()))
        assert metric_spec_from_declaration(declared) == spec
        assert HyperparamTuningOutput.model_validate(
            _minimal_output_dict() | {"metric_spec": declared}
        ).metric_spec == metric_spec_from_declaration(declared)


class TestTheCompatibilityBoundary:
    def test_a_pre_step09a_artifact_validates_and_reads_none(self):
        """A REAL committed artifact from before the field existed.

        It must still load — the schema addition is additive. What it must NOT
        do is acquire a spec from somewhere: ``None`` here is what makes the
        interpreter's refusal reachable instead of a silent default.
        """
        run_output = json.loads(
            (
                _REPLAY_WS / "iteration_001" / "pe_wavenet_delta" / "run_output_iter_001.json"
            ).read_text()
        )
        out = HyperparamTuningOutput.model_validate(run_output)
        assert out.metric_spec is None


def _minimal_output_dict() -> dict:
    """The smallest valid ``HyperparamTuningOutput`` payload."""
    return {
        "run_name": "step09a_c2",
        "model_type": "wavenet",
        "file_index": 6,
        "status": "completed",
        "completed_rounds": 0,
        "total_attempts": 0,
        "started_at": "2026-08-19T00:00:00Z",
        "finished_at": "2026-08-19T01:00:00Z",
    }


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
