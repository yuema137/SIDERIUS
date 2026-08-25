"""Step 09a — C2: ONE run MetricSpec, reconciled, and fail-closed without it.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §3.2, §4.3; parent §4a; operator
rulings Q-09a-4, Q-09a-6, Q-09a-7.

The defect these tests own
--------------------------
"Higher is better" was an ASSUMPTION baked into every interpreter comparison.
Under a lower-is-better metric — DAVIS's ``mse`` is one, and it already exists
as a declared pack metric — that assumption does not error, it silently
inverts: the worst model is reported as the best, and every downstream
proposal is built on it. A wrong answer that looks right is the failure mode,
so the contract REFUSES instead of defaulting.

Four refusals, each with its own named owner (Q-09a-4):

* a score-bearing input with NO run spec;
* a summary whose evidence-borne ``metric_id`` disagrees with the run spec;
* a summary whose evidence-borne ``direction`` disagrees with the run spec;
* a set of tuning outputs that does not agree on one spec (including the
  mixed present/absent case — the legacy boundary of Q-09a-6).

Plus the structural claim the whole step rests on: Step 09 adds ZERO
production metric-derivation sites (Q-09a-7).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.interpretation import (
    InterpretationInput,
    MetricIdentity,
    ModelRunSummary,
)
from execute_tools.evaluation_metric import TIDMAD_METRIC_ID
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import (
    InterpretationContractError,
    reconcile_metric_spec,
    tuning_output_to_model_run_summary,
)
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder
#: as a REQUIRED keyword. TIDMAD is `higher`, so expectations are unchanged.
_STEP09A_ORDER = MetricOrder(shipped_spec())

REPO_ROOT = Path(__file__).resolve().parents[4]

_ordering = importlib.import_module("nodes.result_interpretation_agent.ordering")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _summary(model_type: str = "wavenet", **overrides) -> ModelRunSummary:
    base = {
        "model_type": model_type,
        "run_name": "c2",
        "status": "completed",
        "completed_rounds": 2,
        "best_denoising_score": -2.0,
        "worst_denoising_score": -3.0,
        "round_scores": [-3.0, -2.0],
        "round_conclusions": ["a", "b"],
    }
    return ModelRunSummary(**{**base, **overrides})


def _scoreless_summary(model_type: str = "wavenet") -> ModelRunSummary:
    return ModelRunSummary(
        model_type=model_type,
        run_name="c2",
        status="error",
        completed_rounds=0,
        round_scores=[],
        round_conclusions=[],
    )


def _storage(tmp_path) -> dict:
    return {"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "c2"}}


def _record(exp_id: str, score: float, metric_id: str | None, direction: str = "higher"):
    payload = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-19T00:00:00Z",
        "params": {},
        "denoising_score": score,
        "health_gate_enabled": False,
    }
    if metric_id is not None:
        payload["metric_result"] = {
            "metric_id": metric_id,
            "direction": direction,
            "scalar": score,
            "per_sample": None,
        }
    return ExperimentRecord.model_validate(payload)


def _output(*records, run_name="c2_run", model_type="wavenet", metric_spec=...):
    payload = {
        "run_name": run_name,
        "model_type": model_type,
        "file_index": 6,
        "status": "completed",
        "completed_rounds": len(records),
        "total_attempts": len(records),
        "started_at": "2026-08-19T00:00:00Z",
        "finished_at": "2026-08-19T01:00:00Z",
        "all_records": list(records),
    }
    if metric_spec is not ...:
        payload["metric_spec"] = metric_spec
    return HyperparamTuningOutput.model_validate(payload)


# ---------------------------------------------------------------------------
# 1. Fail closed: score-bearing input without the run spec
# ---------------------------------------------------------------------------


class TestAScoreBearingInputRequiresTheRunSpec:
    def test_a_summary_score_without_a_spec_is_refused_and_names_the_witness(self, tmp_path):
        with pytest.raises(ValidationError) as excinfo:
            InterpretationInput(summaries=[_summary()], storage=_storage(tmp_path))
        message = str(excinfo.value)
        assert "metric_spec is required" in message
        assert "'wavenet'" in message and "best_denoising_score" in message, (
            "the refusal must name WHICH evidence made the spec mandatory, or an "
            "operator cannot act on it"
        )
        assert "re-produce the output under Step 09a" in message

    def test_a_cached_stats_score_without_a_spec_is_refused(self, tmp_path):
        """The cache is ordering evidence too — ``_cap_knowledge_cache`` and the
        pre-computation both rank on it, so a spec-less cache is the same defect
        with a different carrier."""
        with pytest.raises(ValidationError) as excinfo:
            InterpretationInput(
                model_knowledge_cache={"punet": {"_stats": {"best_denoising_score": -2.9}}},
                storage=_storage(tmp_path),
            )
        message = str(excinfo.value)
        assert "cache entry 'punet'" in message and "best_denoising_score" in message

    @pytest.mark.parametrize(
        "field, value",
        [
            ("best_valid_denoising_score", -2.1),
            ("worst_denoising_score", -3.3),
            ("formal_score", -2.2),
            ("best_valid_formal_score", -2.2),
        ],
    )
    def test_every_score_field_counts_as_ordering_evidence(self, tmp_path, field, value):
        """One field per parametrisation: a witness scan that missed any of them
        would let that shape through with no direction."""
        summary = _scoreless_summary()
        setattr(summary, field, value)
        with pytest.raises(ValidationError, match="metric_spec is required"):
            InterpretationInput(summaries=[summary], storage=_storage(tmp_path))

    def test_a_round_score_alone_counts_as_ordering_evidence(self, tmp_path):
        summary = _scoreless_summary()
        summary.round_scores = [None, -2.4]
        with pytest.raises(ValidationError) as excinfo:
            InterpretationInput(summaries=[summary], storage=_storage(tmp_path))
        assert "round_scores" in str(excinfo.value)


class TestTheNamedAbsenceStaysLegal:
    """Cold start and genuinely scoreless inputs need no ordering (parent §4a).

    This is the boundary that must NOT widen: it is what keeps a real chain's
    first iteration working, and nothing more.
    """

    def test_a_cold_start_is_accepted_without_a_spec(self, tmp_path):
        inp = InterpretationInput(cold_start=True, storage=_storage(tmp_path))
        assert inp.metric_spec is None
        assert _ordering.bind_run_order(inp) is None

    def test_a_scoreless_summary_is_accepted_without_a_spec(self, tmp_path):
        inp = InterpretationInput(summaries=[_scoreless_summary()], storage=_storage(tmp_path))
        assert inp.metric_spec is None
        assert _ordering.bind_run_order(inp) is None

    def test_a_bound_spec_produces_the_run_order(self, tmp_path):
        inp = InterpretationInput(
            summaries=[_summary()], metric_spec=shipped_spec(), storage=_storage(tmp_path)
        )
        order = _ordering.bind_run_order(inp)
        assert order is not None
        assert order.direction == "higher"

        lower = InterpretationInput(
            summaries=[_summary()], metric_spec=direction_only_spec(), storage=_storage(tmp_path)
        )
        lower_order = _ordering.bind_run_order(lower)
        assert lower_order is not None
        assert lower_order.direction == "lower"


# ---------------------------------------------------------------------------
# 2. Fail closed: the record's identity must agree with the run spec
# ---------------------------------------------------------------------------


class TestRecordIdentityMustAgreeWithTheRunSpec:
    def test_agreement_is_accepted(self, tmp_path):
        summary = _summary(
            metric_identity=MetricIdentity(metric_id=TIDMAD_METRIC_ID, direction="higher")
        )
        inp = InterpretationInput(
            summaries=[summary], metric_spec=shipped_spec(), storage=_storage(tmp_path)
        )
        assert inp.metric_spec is not None

    def test_an_id_mismatch_is_refused_and_names_both_sides(self, tmp_path):
        summary = _summary(
            metric_identity=MetricIdentity(metric_id="some_other_metric", direction="higher")
        )
        with pytest.raises(ValidationError) as excinfo:
            InterpretationInput(
                summaries=[summary], metric_spec=shipped_spec(), storage=_storage(tmp_path)
            )
        message = str(excinfo.value)
        assert "metric identity mismatch" in message
        assert "some_other_metric" in message and TIDMAD_METRIC_ID in message

    def test_a_direction_mismatch_is_refused_and_names_both_sides(self, tmp_path):
        """The dangerous one: same metric id, opposite direction. Nothing about
        the VALUES would look wrong — only the ranking would invert."""
        summary = _summary(
            metric_identity=MetricIdentity(metric_id=TIDMAD_METRIC_ID, direction="lower")
        )
        with pytest.raises(ValidationError) as excinfo:
            InterpretationInput(
                summaries=[summary], metric_spec=shipped_spec(), storage=_storage(tmp_path)
            )
        message = str(excinfo.value)
        assert "metric direction mismatch" in message
        assert "'lower'" in message and "'higher'" in message

    def test_a_summary_without_an_identity_is_not_second_guessed(self, tmp_path):
        """Pre-Step-06 evidence carries no identity. Absence is absence — the
        run spec still orders, and nothing is invented for the summary."""
        inp = InterpretationInput(
            summaries=[_summary()], metric_spec=shipped_spec(), storage=_storage(tmp_path)
        )
        assert inp.summaries[0].metric_identity is None


# ---------------------------------------------------------------------------
# 3. The builder projects the evidence-borne identity
# ---------------------------------------------------------------------------


class TestTheBuilderProjectsRecordIdentity:
    def test_identity_is_projected_from_the_records(self):
        summary = tuning_output_to_model_run_summary(
            _output(
                _record("r1", -2.6, TIDMAD_METRIC_ID),
                _record("r2", -2.0, TIDMAD_METRIC_ID),
            ),
            order=_STEP09A_ORDER,
        )
        assert summary.metric_identity == MetricIdentity(
            metric_id=TIDMAD_METRIC_ID, direction="higher"
        )

    def test_no_metric_result_yields_a_named_absence(self):
        summary = tuning_output_to_model_run_summary(
            _output(_record("r1", -2.6, None)), order=_STEP09A_ORDER
        )
        assert summary.metric_identity is None

    def test_records_disagreeing_about_their_metric_fail_closed_at_the_builder(self):
        """A corrupt output refuses HERE — before any consumer reads a number
        off a summary that would silently describe two metrics."""
        with pytest.raises(InterpretationContractError) as excinfo:
            tuning_output_to_model_run_summary(
                _output(
                    _record("r1", -2.6, TIDMAD_METRIC_ID),
                    _record("r2", -2.0, TIDMAD_METRIC_ID, direction="lower"),
                ),
                order=_STEP09A_ORDER,
            )
        assert "disagree about the metric" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Reconciliation across the outputs feeding ONE interpretation
# ---------------------------------------------------------------------------


class TestReconciliation:
    def test_equal_specs_across_three_outputs_reconcile_to_that_value(self):
        outputs = [
            _output(run_name=f"r{i}", model_type=f"m{i}", metric_spec=shipped_spec())
            for i in range(3)
        ]
        assert reconcile_metric_spec(outputs) == shipped_spec()

    def test_all_absent_reconciles_to_a_named_absence(self):
        outputs = [_output(run_name=f"r{i}", model_type=f"m{i}") for i in range(2)]
        assert reconcile_metric_spec(outputs) is None

    def test_an_empty_set_reconciles_to_none(self):
        assert reconcile_metric_spec([]) is None

    def test_one_absent_among_present_is_refused_and_names_the_offender(self):
        """The Q-09a-6 legacy boundary: a chain resumed ACROSS the 09a boundary
        mixes stamped and unstamped outputs, and that must stop rather than
        quietly interpret half the evidence."""
        outputs = [
            _output(run_name="stamped", model_type="a", metric_spec=shipped_spec()),
            _output(run_name="legacy", model_type="b"),
        ]
        with pytest.raises(InterpretationContractError) as excinfo:
            reconcile_metric_spec(outputs)
        message = str(excinfo.value)
        assert "'legacy'" in message and "'b'" in message
        assert "No replacement spec is derived" in message

    def test_two_specs_with_the_SAME_id_but_opposite_direction_are_refused(self):
        """The case an id-only comparison would wave through.

        Same metric id, opposite direction, is the most dangerous disagreement
        there is: nothing about the identity looks wrong, and the ranking
        inverts. Reconciliation therefore compares the WHOLE spec, not its id.
        """
        flipped = shipped_spec().model_copy(update={"direction": "lower"})
        outputs = [
            _output(run_name="as_higher", model_type="a", metric_spec=shipped_spec()),
            _output(run_name="as_lower", model_type="b", metric_spec=flipped),
        ]
        with pytest.raises(InterpretationContractError) as excinfo:
            reconcile_metric_spec(outputs)
        message = str(excinfo.value)
        assert "'as_higher'" in message and "'as_lower'" in message
        assert "'higher'" in message and "'lower'" in message

    def test_two_unequal_specs_are_refused_and_name_both(self):
        outputs = [
            _output(run_name="higher_run", model_type="a", metric_spec=shipped_spec()),
            _output(run_name="lower_run", model_type="b", metric_spec=direction_only_spec()),
        ]
        with pytest.raises(InterpretationContractError) as excinfo:
            reconcile_metric_spec(outputs)
        message = str(excinfo.value)
        assert "'higher_run'" in message and "'lower_run'" in message
        assert "'higher'" in message and "'lower'" in message


# ---------------------------------------------------------------------------
# 5. Reachability + the structural claim
# ---------------------------------------------------------------------------


class TestTheWorkflowSuppliesTheReconciledSpec:
    def test_the_protocol_maps_the_field(self, tmp_path):
        """The schema is the completeness contract: a protocol that dropped the
        field would leave the interpreter spec-less on this edge."""
        from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import local_all_records

        out = _output(_record("r1", -2.0, TIDMAD_METRIC_ID), metric_spec=shipped_spec())
        built = local_all_records(out, storage=_storage(tmp_path))
        assert built.metric_spec == shipped_spec()

    def test_the_cli_refuses_a_legacy_output_with_the_named_error(self, tmp_path, monkeypatch):
        """The ad-hoc entry point must fail with a NAMED contract refusal, not a
        traceback from somewhere inside ordering.

        Which owner fires is itself a design fact (child §3.3): the CLI builds a
        summary BEFORE any ``InterpretationInput`` exists, and the builder ranks
        records, so the BUILDER's own fail-closed clause is reached first. The
        input validator is the second line of defence, for hand-built summaries.
        """
        import json as _json
        import sys

        from nodes.result_interpretation_agent import main

        legacy = _output(_record("r1", -2.0, None), run_name="legacy")
        (tmp_path / "run_output_legacy.json").write_text(
            _json.dumps(_json.loads(legacy.model_dump_json())), encoding="utf-8"
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "result_interpretation_agent",
                "--workspace",
                str(tmp_path),
                "--run_name",
                "legacy",
                "--model_type",
                "wavenet",
            ],
        )
        with pytest.raises(InterpretationContractError) as excinfo:
            main()
        message = str(excinfo.value)
        assert "requires the run's MetricOrder" in message
        assert "'legacy'" in message, "the refusal must name the offending run"
        assert "never assumed" in message


class TestStep09AddsNoProductionMetricDerivationSite:
    """Q-09a-7, made executable.

    The whole architecture rests on there being ONE derivation. A second one
    would not fail any test on its own — it would agree with the first, until
    the day a task binds a different metric and the two silently diverge. So
    the SET of call sites is pinned, and a new one is a hard failure.
    """

    PRODUCTION_DIRS = ("nodes", "agent", "core", "execute_tools", "workflows", "dashboard")
    DERIVERS: ClassVar[set[str]] = {"derive_tidmad_metric", "derive_tidmad_metric_spec"}
    #: Step 12 / PR-12d seam B REMOVED one — the tuner. It used to spell the
    #: rule inline as ``resolve_bound_run_metric() or derive_tidmad_metric(...)``
    #: and now calls ``evaluation_metric.resolve_run_metric``, which owns the
    #: whole rule including the order. That is this census's goal arriving,
    #: not a violation of it: the claim is "ZERO ADDED derivation sites", and
    #: a site leaving makes the ONE derivation more true, not less.
    EXPECTED: ClassVar[set[str]] = {
        "execute_tools/denoising_score_single.py",
        "core/sandbox_executor.py",
        "execute_tools/evaluation_metric.py",
    }

    def _callers(self, roots) -> set[str]:
        found: set[str] = set()
        for root in roots:
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        fn = node.func
                        name = (
                            fn.id
                            if isinstance(fn, ast.Name)
                            else fn.attr
                            if isinstance(fn, ast.Attribute)
                            else None
                        )
                        if name in self.DERIVERS:
                            found.add(path.relative_to(REPO_ROOT).as_posix())
        return found

    def test_the_production_derivation_call_sites_are_exactly_the_expected_set(self):
        assert self._callers(self.PRODUCTION_DIRS) == self.EXPECTED, (
            "the set of production modules deriving the TIDMAD metric changed. "
            "Step 09 transports the tuner's already-resolved spec and adds ZERO "
            "derivation sites (child design §4.3 acceptance, Q-09a-7)."
        )

    def test_the_census_is_not_vacuous(self):
        """If the AST walk found nothing, the assertion above would be trivially
        satisfiable by deleting the whole feature."""
        assert len(self._callers(self.PRODUCTION_DIRS)) == 3

    def test_the_calibration_fixture_is_the_one_stamping_module_and_is_unreachable_from_production(
        self,
    ):
        """The PR3 calibration fixture DOES construct a spec (it simulates a
        tuner-output writer, Q-09a-7). That is legitimate only while production
        cannot reach it."""
        stamping = self._callers(("scripts",))
        assert stamping == {"scripts/pr3_l2_calibration/fixtures.py"}, (
            f"unexpected spec-constructing script modules: {stamping}"
        )

        importers: dict[str, list[str]] = {}
        for root in self.PRODUCTION_DIRS:
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                hits = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        hits += [a.name for a in node.names if "pr3_l2_calibration" in a.name]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        if "pr3_l2_calibration" in node.module:
                            hits.append(node.module)
                if hits:
                    importers[path.relative_to(REPO_ROOT).as_posix()] = hits
        assert importers == {}, (
            "production code imported the calibration fixture package; its spec "
            f"stamp would then be a production derivation authority: {importers}"
        )
