"""Step 12 / PR-12e — the semantic report projection.

Design: ``pr_12e_out_of_tree_graduation.md`` §V.4 (the two frozen semantic
rules), §V.5, §V.6 (real artifacts; class A vs class B), §V.12, §V.13c.

Fixture provenance — REAL production artifacts, per §V.6
---------------------------------------------------------
``step12_pr12e_fixtures/chain_workspace/`` is a verbatim copy of three
iterations of the **Step-10 P5+P6 Gate-2 terminal run**
(``step10_p56_gate2_final_20260821_135242``) plus its run-invariants lock.
Nothing in it was authored for a test.

``real_health_gate_results.json`` is the six ``PersistedHealthGateResult``
objects from the ``step09_5a_gate2_inconclusive`` collapse record — the one
that drove ``invalidate_round``. ``real_pets_metric_declarations.json`` is
the PR-12d Pets run's ``metric_spec`` and ``secondary_metric_specs``: the
only non-TIDMAD metric declaration and the only ``lower``-is-better
declaration (``log_loss``) present in any artifact on this machine.

**Two gaps no real artifact on disk can fill, stated rather than papered
over.** A census over every ``run_output_*.json`` and a byte scan of 16,019
JSON files found (1) NO artifact anywhere with a populated
``secondary_metric_results``/``refusals``/``errors`` — consistent with
Q-09-7 = B, which landed the transport but no evaluator — and (2) no
artifact with ``metric_spec`` AND a ``success`` record AND populated
``health_gate_results`` in one file. Those two cases are therefore
constructed **through the production Pydantic schemas** from real declared
values, so they cannot drift from the schema; that is a test input, not a
fabricated example curve, and §V.6's prohibition is on the latter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.evaluation_metric import (
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    metric_spec_from_declaration,
)
from execute_tools.health_checks.schemas import PersistedHealthGateResult
from execute_tools.run_report import (
    CLASS_B_GAPS,
    RUN_OUTPUT_GLOB,
    RunReportError,
    build_report,
    build_trajectory,
    load_run_output,
    project_run,
)

FIXTURES = Path(__file__).parent / "step12_pr12e_fixtures"
CHAIN_WORKSPACE = FIXTURES / "chain_workspace"


@pytest.fixture
def report():
    return build_report(workspace=CHAIN_WORKSPACE)


def _pets_declarations() -> dict:
    return json.loads((FIXTURES / "real_pets_metric_declarations.json").read_text())


def _real_gates() -> list[PersistedHealthGateResult]:
    payload = json.loads((FIXTURES / "real_health_gate_results.json").read_text())
    return [PersistedHealthGateResult.model_validate(g) for g in payload]


def _flip_direction(doc: dict, direction: str, metric_id: str) -> dict:
    """The SAME real artifact, re-declared with the opposite direction.

    Only the declaration moves. Every score stays byte-identical, which is
    what makes the resulting assertions a direction test rather than a data
    test: if the projection ignored ``direction``, both regimes would produce
    the same best-so-far.
    """
    doc = json.loads(json.dumps(doc))
    doc["metric_spec"]["direction"] = direction
    doc["metric_spec"]["id"] = metric_id
    for record in doc["all_records"]:
        if record.get("metric_result"):
            record["metric_result"]["direction"] = direction
            record["metric_result"]["metric_id"] = metric_id
    return doc


class TestDirectionIsAskedNeverAssumed:
    """§V.4 rule 2 — the rule that inverts a whole campaign when it breaks."""

    def test_the_best_so_far_fold_inverts_with_the_declared_direction(self, tmp_path):
        """MUTATION TARGET: replace ``order.is_better`` with ``>`` in ``_fold_best_so_far``.

        The three real iterations scored -1.229119, -2.314129, -2.030708 in
        that order. Under ``higher`` the campaign's best is the FIRST; under
        ``lower`` it is the SECOND, and the third is not a new best under
        either. The expectations are hardcoded — reading the fold's own answer
        back would pass for any implementation.

        This is the defect F-12e-UX-3 describes on the dashboard's side: a
        `Math.max`-shaped fold marks the WORST attempts as new bests and
        reports the wrong winner, silently and confidently.
        """
        docs = [json.loads(p.read_text()) for p in sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))]

        def trajectory_for(direction: str, metric_id: str):
            paths = []
            for index, doc in enumerate(docs):
                path = tmp_path / f"{direction}_run_output_{index}.json"
                path.write_text(json.dumps(_flip_direction(doc, direction, metric_id)))
                paths.append(path)
            return build_report(run_outputs=paths).trajectory

        higher = trajectory_for("higher", "demo_metric")
        lower = trajectory_for("lower", "demo_metric")

        assert [p.score for p in higher.points] == [p.score for p in lower.points], (
            "the two regimes must differ only in the DECLARATION; identical "
            "scores are what makes this a direction test"
        )
        assert [round(p.score, 6) for p in higher.points] == [-1.229119, -2.314129, -2.030708]
        assert [round(p.best_so_far, 6) for p in higher.points] == [
            -1.229119,
            -1.229119,
            -1.229119,
        ]
        assert [p.is_new_best for p in higher.points] == [True, False, False]
        assert [round(p.best_so_far, 6) for p in lower.points] == [
            -1.229119,
            -2.314129,
            -2.314129,
        ]
        assert [p.is_new_best for p in lower.points] == [True, True, False]

    def test_the_direction_words_come_from_the_order_authority(self, report):
        """MUTATION TARGET: spell "higher"/"lower" from ``direction ==`` in ``metric_view``.

        The words must be the ones ``MetricOrder.direction_words`` produces.
        A renderer that computed them itself would be a SECOND interpreter of
        ``direction`` — the pattern Step 07b removed from twenty-one tuner
        sites and Step 06's C5 guard fails on.
        """
        metric = report.runs[0].metric
        assert metric is not None
        assert (metric.verb, metric.comparative, metric.antonym) == ("maximize", "higher", "lower")
        assert metric.label == "tidmad_denoising_score (higher is better)"

    def test_a_lower_metric_gets_minimize_wording(self, tmp_path):
        """The wording must invert too, or a chart title contradicts its curve."""
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        path = tmp_path / "run_output_low.json"
        path.write_text(json.dumps(_flip_direction(json.loads(source.read_text()), "lower", "mse")))
        metric = build_report(run_outputs=[path]).runs[0].metric
        assert metric is not None
        assert (metric.verb, metric.comparative) == ("minimize", "lower")
        assert metric.label == "mse (lower is better)"

    def test_each_secondary_keeps_its_own_direction(self):
        """MUTATION TARGET: build ``SecondaryView.metric`` from the run's spec.

        Uses the REAL Pets declarations: `macro_f1` is `higher`, `log_loss` is
        `lower`, and the run's PRIMARY (`accuracy`) is `higher`. A secondary
        that inherited the primary's direction would label `log_loss`
        backwards — the exact case Step 10 P2b named with DAVIS's
        `higher` psnr beside a `lower` mse primary.
        """
        declarations = _pets_declarations()
        specs = [metric_spec_from_declaration(s) for s in declarations["secondary_metric_specs"]]
        record = _record(
            "e1",
            status="success",
            score=0.5,
            secondary_results=[
                MetricResult(metric_id="macro_f1", direction="higher", scalar=0.4),
                MetricResult(metric_id="log_loss", direction="lower", scalar=2.3),
            ],
        )
        output = _output(
            [record],
            spec=metric_spec_from_declaration(declarations["metric_spec"]),
            secondaries=specs,
        )
        views = project_run(output, source_path="x").attempts[0].secondaries
        assert [(v.metric.metric_id, v.metric.comparative) for v in views] == [
            ("macro_f1", "higher"),
            ("log_loss", "lower"),
        ]
        assert [v.status for v in views] == ["scored", "scored"]
        assert [v.scalar for v in views] == [0.4, 2.3]


class TestItDeclinesByNameRatherThanGuessing:
    """§V.14h — delegate to the authority, or decline by name."""

    def test_a_corpus_mixing_two_metrics_draws_no_trajectory(self, tmp_path):
        """MUTATION TARGET: pick the first identity instead of reconciling.

        Silently ranking a mixed corpus under whichever direction came first
        is the failure the reconciliation authority exists to prevent, and it
        produces a plausible-looking chart that is simply wrong.
        """
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        doc = json.loads(source.read_text())
        a = tmp_path / "run_output_a.json"
        b = tmp_path / "run_output_b.json"
        a.write_text(json.dumps(doc))
        b.write_text(json.dumps(_flip_direction(doc, "lower", "other_metric")))
        report = build_report(run_outputs=[a, b])
        assert report.trajectory.metric is None
        assert report.trajectory.points == []
        assert report.trajectory.refusal is not None
        assert "other_metric" in report.trajectory.refusal
        assert any("trajectory" in gap for gap in report.gaps), (
            "a refusal must reach the report's gaps, or the chart is simply "
            "absent with no stated reason"
        )

    def test_a_legacy_run_with_no_identity_is_not_ranked(self, tmp_path):
        """MUTATION TARGET: default to ``higher`` when no spec is present.

        A pre-Step-06 artifact declares no metric anywhere. Step 09a made this
        FAIL CLOSED for the interpreter; the report must refuse too rather
        than assume the TIDMAD convention.
        """
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        doc = json.loads(source.read_text())
        doc["metric_spec"] = None
        for record in doc["all_records"]:
            record["metric_result"] = None
        path = tmp_path / "run_output_legacy.json"
        path.write_text(json.dumps(doc))
        run = build_report(run_outputs=[path]).runs[0]
        assert run.metric is None
        assert run.metric_source == "unavailable"
        assert run.ranking_refusal is not None
        assert all(a.best_so_far is None for a in run.attempts), (
            "no attempt may carry a best-so-far when no direction is declared"
        )
        assert all(not a.is_new_best for a in run.attempts)
        assert [a.score for a in run.attempts] != [None], (
            "the values must remain fully readable — excluded from RANKING is "
            "not excluded from the report"
        )

    def test_a_record_with_no_identity_is_excluded_individually(self):
        """MUTATION TARGET: hand identity-less records to ``reconcile_metric_identity``.

        ``partition_by_metric_identity``'s rule: one identity-less record does
        not poison the compatible records beside it. It is excluded from the
        FOLD; its neighbours keep ranking.

        **This test caught a real defect in the projection.** The first
        implementation passed every record — ``None`` entries included —
        straight into reconciliation, which REFUSES a source set where some
        entries declare an identity and others do not. That rule is right for
        a uniformly-stamped interpretation output and wrong for a record
        corpus, and it made the most ordinary real shape unrankable:
        reproduced on ``step09_5a_gate2_TERMINAL_PASS_20260820`` iter_002 —
        15 records, 14 ``error_training`` that never reached scoring, 1
        ``success`` carrying the identity — where the whole run resolved to
        "metric direction unavailable" and lost its ranking, its best-so-far
        and its direction label. The three-run fixture could not reveal it,
        because every record in it is scored.
        """
        spec = metric_spec_from_declaration(_pets_declarations()["metric_spec"])
        records = [
            _record("a", status="success", score=0.10),
            _record("b", status="success", score=0.90, identity=False),
            _record("c", status="success", score=0.50),
        ]
        run = project_run(_output(records, spec=spec), source_path="x")
        assert [a.rankable for a in run.attempts] == [True, False, True]
        # 0.90 is the largest value present and must NOT become the best,
        # because the record carrying it declares no identity.
        assert [a.best_so_far for a in run.attempts] == [0.10, None, 0.50]
        assert [a.is_new_best for a in run.attempts] == [True, False, True]

    def test_the_run_spec_is_reconciled_against_the_records(self):
        """MUTATION TARGET: trust ``metric_spec`` without checking the records.

        A corrupt artifact whose declared spec disagrees with what its records
        were actually scored under must REFUSE, not rank the records under the
        declaration they were not evaluated with.
        """
        spec = metric_spec_from_declaration(_pets_declarations()["metric_spec"])
        record = _record("a", status="success", score=0.5, metric_id="something_else")
        run = project_run(_output([record], spec=spec), source_path="x")
        assert run.metric is None
        assert run.ranking_refusal is not None


class TestTheObjectiveIsNotCalledLoss:
    """§V.4 rule 1 — the typed identity, carried, never renamed."""

    def test_the_objective_kind_is_projected_verbatim(self, report):
        """MUTATION TARGET: hardcode "loss" as the objective label.

        The real fixture's objective is ``ce``. Training MAE/L1 and a terminal
        MSE/PSNR/MAE stay semantically distinct even where the mathematics
        overlaps, which is why the framework types this at all.
        """
        objective = report.runs[0].attempts[0].objective
        assert objective is not None
        assert objective.objective_kind == "ce"
        assert objective.objective_reduction == "mean"

    def test_r2_and_r3_comparability_is_carried_with_its_reason(self):
        """MUTATION TARGET: drop ``comparability`` from the projection.

        Drawing the train and validation curves on one axis without this stamp
        implies a comparison the framework explicitly refused to certify. The
        reason travels with it, because "not comparable" without "why" sends
        the reader looking for a bug that is a declared property.
        """
        record = _record(
            "a",
            status="success",
            score=0.5,
            history={
                "objective_kind": "custom",
                "objective_config_fingerprint": "f" * 64,
                "objective_reduction": "sum",
                "comparability": "not_established",
                "comparability_reason": "custom_objective_undeclared",
                "epochs_planned": 3,
                "epochs_completed": 2,
                "train_objective": [1.0, 0.8],
            },
        )
        objective = (
            project_run(_output([record], spec=_spec()), source_path="x").attempts[0].objective
        )
        assert objective is not None
        assert objective.comparability == "not_established"
        assert objective.comparability_reason == "custom_objective_undeclared"
        assert objective.truncated is True
        assert objective.validation_objective is None

    def test_a_diverged_epoch_survives_as_a_GAP_not_a_shortened_curve(self):
        """F-12e-G2 one layer up: the projection must PRESERVE a None epoch.

        `coerce_nonfinite_to_none` writes JSON null for a NaN/inf epoch at the
        storage boundary, and `TrainingHistory` declares `list[float | None]`
        to match (#299). The projection mirrors that shape instead of
        narrowing it.

        Defect this catches, and how it fails: someone "fixes" a type
        complaint with a filtering comprehension
        (``[v for v in series if v is not None]``) or a ``cast``. The
        comprehension SHORTENS the series, so a run that diverged at epoch 3
        of 5 renders as a healthy 4-point curve — the statistic-silently-wrong
        mode #299 was landed to eliminate, reintroduced in the presentation
        layer. Then the length assertion fails and the position assertion
        fails. A ``cast`` leaves a runtime None inside a series the type
        claims is numeric; the element assertion below still pins the value.

        Positions are load-bearing: `epochs_completed == len(train_objective)`
        is the invariant the schema itself enforces, so the report must not be
        the one place it stops holding. matplotlib renders the None as a gap,
        which is the honest picture of a diverged epoch.
        """
        record = _record(
            "diverged",
            status="success",
            score=0.5,
            history={
                "objective_kind": "ce",
                "objective_config_fingerprint": "d" * 64,
                "objective_reduction": "mean",
                "comparability": "established",
                "epochs_planned": 5,
                "epochs_completed": 5,
                "train_objective": [1.0, 0.8, None, 0.5, 0.4],
                # The four validation fields are a schema-enforced group — they
                # travel together or not at all — so R3 needs its companions.
                "validation_objective": [1.1, 0.9, None, 0.6, 0.5],
                "validation_samples": 8,
                "validation_requested_samples": 8,
                "validation_seconds": [0.1, 0.1, 0.1, 0.1, 0.1],
            },
        )
        objective = (
            project_run(_output([record], spec=_spec()), source_path="x").attempts[0].objective
        )
        assert objective is not None
        # Length preserved -- a comprehension would give 4.
        assert len(objective.train_objective) == 5
        assert len(objective.validation_objective or []) == 5
        # The gap is at the epoch that diverged, not squeezed out of the series.
        assert objective.train_objective[2] is None
        assert (objective.validation_objective or [])[2] is None
        # The surviving epochs keep their values and their positions.
        assert objective.train_objective[3] == 0.5
        # The schema's own invariant still holds through the projection.
        assert objective.epochs_completed == len(objective.train_objective)

    def test_the_diagnosis_line_comes_from_the_07b_authority(self, report):
        """MUTATION TARGET: re-phrase the training-dynamics line locally.

        The authority owns the DEGENERATE renderings — "none recorded",
        "invalid (non-finite)", "gap n/a (not comparable)". A local rephrasing
        would omit them, and a silent omission reads as "training was
        unremarkable".
        """
        diagnosis = report.runs[0].attempts[0].diagnosis
        assert diagnosis is not None
        assert diagnosis.summary_line.startswith("[ce] train ")
        assert "gap " in diagnosis.summary_line


class TestTheClassASurfaceIsActuallyProjected:
    """Every §V.12a row reaches the projection, from a real artifact."""

    def test_the_real_chain_projects_three_runs_with_full_provenance(self, report):
        assert [r.run_name for r in report.runs] == ["iter_001", "iter_002", "iter_003"]
        assert [r.model_type for r in report.runs] == [
            "compact_residual_dilated_cnn_v5",
            "compact_residual_dilated_cnn_v6",
            "compact_residual_dilated_cnn_v7",
        ]
        for run in report.runs:
            assert run.provenance.resolved_data_scope == [4, 5, 6, 7, 8, 9]
            assert run.status == "completed"
        assert report.lock is not None
        assert report.lock.resolved_data_scope == [4, 5, 6, 7, 8, 9]
        assert (
            report.lock.task_composition_fingerprint
            == "d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a"
        )

    def test_runs_are_ordered_by_their_persisted_timestamps(self, tmp_path):
        """MUTATION TARGET: sort by path instead of ``started_at``.

        §V.12b: a typed chain-iteration index is NOT persisted, and a
        directory name is a path fact, not a semantic one. Sorting by path
        happens to agree here, so the paths are deliberately named to
        DISAGREE with chronology — otherwise this test could not tell the two
        rules apart.
        """
        sources = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))
        reversed_names = ["run_output_zzz.json", "run_output_mmm.json", "run_output_aaa.json"]
        paths = []
        for source, name in zip(sources, reversed_names, strict=True):
            path = tmp_path / name
            path.write_text(source.read_text())
            paths.append(path)
        report = build_report(run_outputs=paths)
        assert [r.run_name for r in report.runs] == ["iter_001", "iter_002", "iter_003"]
        assert [Path(r.source_path).name for r in report.runs] == reversed_names

    def test_health_gate_outcomes_carry_verdicts_and_the_computed_label(self):
        """MUTATION TARGET: rebuild ``display_label`` from the gate id.

        ``display_label`` is a ``@computed_field`` whose rule is "never from
        the id" — a gate whose configured action cannot invalidate anything is
        observational however its id is spelled. A view that re-derived it
        would show a legacy gate as "enforcing" exactly where the authority
        refuses to. Uses the six REAL gates from the collapse record.
        """
        gates = _real_gates()
        record = _record("a", status="failed_mode_collapse", score=-0.46, gates=gates)
        views = project_run(_output([record], spec=_spec()), source_path="x").attempts[0]
        assert len(views.health_gates) == 6
        by_name = {g.gate_name: g for g in views.health_gates}
        blocking = by_name["output_diversity_blocking"]
        assert blocking.display_label == "output_diversity_blocking (enforcing)"
        assert blocking.execution_status == "failed"
        assert blocking.check_passed is False
        assert blocking.resolved_action == "invalidate_round"
        assert blocking.check_verdicts == {"output_diversity": "failed"}
        assert by_name["pearson_dispersion_recording"].display_label.endswith("(observational)")

    def test_failure_attribution_and_the_thirteen_statuses_survive(self):
        """MUTATION TARGET: collapse statuses into success/failure.

        The framework's statuses are not interchangeable —
        ``skipped_resource_admission`` says nothing about the candidate,
        ``failed_mode_collapse`` says everything — and the dashboard's charts
        filter every non-success away entirely (§V.12a). The report keeps the
        status verbatim; ``outcome`` is a rendering grouping BESIDE it, never
        instead of it.
        """
        records = [
            _record("a", status="success", score=0.5),
            _record(
                "b",
                status="error_training",
                attribution={"attribution": "unknown", "reason": "a signal alone..."},
            ),
            _record("c", status="skipped_resource_admission"),
            _record("d", status="failed_mode_collapse", score=-999.0),
            _record("e", status="error_scoring", refusal=True),
        ]
        run = project_run(_output(records, spec=_spec()), source_path="x")
        assert run.status_counts == {
            "success": 1,
            "error_training": 1,
            "skipped_resource_admission": 1,
            "failed_mode_collapse": 1,
            "error_scoring": 1,
        }
        assert [a.outcome for a in run.attempts] == [
            "scored",
            "failed",
            "skipped",
            "failed",
            "refused",
        ]
        assert run.attempts[1].failure_attribution == {
            "attribution": "unknown",
            "reason": "a signal alone...",
        }
        assert run.attempts[4].refusal_contract_id == "deliverable_presence"

    def test_a_collapse_penalty_never_becomes_the_best(self):
        """MUTATION TARGET: fold every finite score, whatever the status.

        On a ``failed_mode_collapse`` record ``denoising_score`` is the gate
        policy's PENALTY by design. Under a MINIMISED metric that penalty is
        the best number in the run, so a fold that admitted it would hand the
        campaign's finest result to its worst failure — precisely what
        ``MetricOrder.penalty_convention_applies`` exists to name.
        """
        spec = metric_spec_from_declaration(
            {**_pets_declarations()["metric_spec"], "id": "loss_like", "direction": "lower"}
        )
        records = [
            _record(
                "a", status="success", score=2.0, metric_id="loss_like", metric_direction="lower"
            ),
            _record(
                "b",
                status="failed_mode_collapse",
                score=-999.0,
                metric_id="loss_like",
                metric_direction="lower",
            ),
            _record(
                "c", status="success", score=1.5, metric_id="loss_like", metric_direction="lower"
            ),
        ]
        run = project_run(_output(records, spec=spec), source_path="x")
        assert [a.best_so_far for a in run.attempts] == [2.0, None, 1.5]
        assert run.attempts[1].score == -999.0, (
            "the penalty stays fully visible in the report; it is excluded "
            "from the FOLD, not hidden"
        )

    def test_the_tuner_headline_is_surfaced_and_not_recomputed(self, report):
        """MUTATION TARGET: recompute ``best_valid_*`` from the records.

        HealthGate validity is the authority's question. The tuner already
        committed its answers; a report that re-derived them would be a second
        answer to a settled question. Hardcoded from the real artifact.
        """
        headline = report.runs[0].headline
        assert headline.best_exp_id == "compact_residual_dilated_cnn_v5_iter_001_001"
        assert round(headline.best_score, 6) == -1.229119
        assert round(headline.best_valid_score, 6) == -1.229119
        assert round(headline.best_valid_formal_score, 6) == -1.229119


class TestClassBIsRefusedAndRecorded:
    """§V.6/§V.12b — a gap is recorded, never closed by a new field."""

    def test_the_projection_adds_no_persisted_field(self):
        """MUTATION TARGET: add a field to ``ExperimentRecord`` for a plot.

        The whole addition is a projection. If a class-B semantic ever gets
        persisted to make a chart nicer, it will show up here as a new record
        or output field, and this test is the tripwire.
        """
        assert "iteration_index" not in ExperimentRecord.model_fields
        assert "per_step_loss" not in ExperimentRecord.model_fields
        assert "train_seconds_per_epoch" not in ExperimentRecord.model_fields
        assert "model_plugin_sha256" not in ExperimentRecord.model_fields
        assert "report" not in HyperparamTuningOutput.model_fields

    def test_every_report_states_the_gaps_it_did_without(self, report):
        """A silence about a missing view must be a stated decision."""
        assert len(CLASS_B_GAPS) == 7
        for gap in CLASS_B_GAPS:
            assert gap in report.gaps
        joined = " ".join(report.gaps)
        for topic in ("per-step", "per-sample", "GPU", "digest", "chain-iteration"):
            assert topic in joined


class TestNamedFailuresRatherThanASilentEmptyReport:
    """A report that renders nothing must say why."""

    def test_an_empty_workspace_raises_a_named_error(self, tmp_path):
        with pytest.raises(RunReportError) as excinfo:
            build_report(workspace=tmp_path)
        assert excinfo.value.name == "no_run_output_found"
        assert "summary_*.json" in str(excinfo.value), (
            "the message must name the file it deliberately does NOT read, or "
            "an operator with a summary_*.json will think the tool is broken"
        )

    def test_a_missing_workspace_is_distinguished_from_an_empty_one(self, tmp_path):
        with pytest.raises(RunReportError) as excinfo:
            build_report(workspace=tmp_path / "nope")
        assert excinfo.value.name == "workspace_not_a_directory"

    def test_a_corpus_of_only_corrupt_artifacts_raises_and_names_them(self, tmp_path):
        (tmp_path / "run_output_bad.json").write_text('{"not": "an output"}')
        with pytest.raises(RunReportError) as excinfo:
            build_report(workspace=tmp_path)
        assert excinfo.value.name == "no_run_output_consumable"
        assert "run_output_bad.json" in str(excinfo.value)

    def test_one_corrupt_artifact_does_not_lose_the_readable_ones(self, tmp_path):
        """MUTATION TARGET: abort the whole report on the first bad file.

        A mid-crash iteration leaves an unparseable artifact beside good ones.
        Losing the whole report to it is the difference between a tool an
        operator reaches for after a failure and one they cannot use precisely
        then.
        """
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        (tmp_path / "run_output_good.json").write_text(source.read_text())
        (tmp_path / "run_output_broken.json").write_text("{oh no")
        report = build_report(workspace=tmp_path)
        assert len(report.runs) == 1
        assert len(report.unreadable) == 1
        assert "run_output_broken.json" in report.unreadable[0]
        assert "run_output_malformed_json" in report.unreadable[0]

    def test_discovery_finds_both_on_disk_layouts(self, tmp_path):
        """MUTATION TARGET: hardcode ``iter_*/iteration_*/{model}/`` nesting.

        Two layouts exist — the chain one and the legacy in-process one — and
        a third nesting is exactly how a report goes silently empty. The walk
        is recursive on purpose.
        """
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0].read_text()
        flat = tmp_path / "run_output_flat.json"
        flat.write_text(source)
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "run_output_deep.json").write_text(source)
        assert len(build_report(workspace=tmp_path).runs) == 2


class TestItReadsTheNormalizedArtifact:
    """§V.13c — settled by source, and worth a guard."""

    def test_the_glob_targets_run_output_not_summary(self, tmp_path):
        """MUTATION TARGET: point the projection at ``summary_*.json``.

        ``summary_*.json`` is a RAW record log whose declared keys are ABSENT
        rather than null, and it carries no ``metric_spec`` — so reading it
        would throw away the direction §V.4 rule 2 depends on. It sits in the
        SAME directory as the artifact this reads, so the mistake is one glob
        away.
        """
        assert RUN_OUTPUT_GLOB == "run_output_*.json"
        (tmp_path / "summary_x.json").write_text("[]")
        with pytest.raises(RunReportError) as excinfo:
            build_report(workspace=tmp_path)
        assert excinfo.value.name == "no_run_output_found"

    def test_the_artifact_is_revalidated_against_the_schema_that_wrote_it(self):
        source = sorted(CHAIN_WORKSPACE.rglob(RUN_OUTPUT_GLOB))[0]
        output = load_run_output(source)
        assert isinstance(output, HyperparamTuningOutput)
        assert output.metric_spec is not None
        assert output.metric_spec.id == "tidmad_denoising_score"


class TestNoTaskDispatch:
    """§V.4 — the framework must never contain ``if task == tidmad``.

    ONE census over BOTH halves of this addition — the projection and the
    renderer. Split per directory it could be true of each file and false of
    the pair, and the rule is about the addition as a whole.
    """

    #: Task identity may appear in PROSE — the docstrings deliberately cite
    #: TIDMAD, Pets and DAVIS as worked examples, and deleting that would make
    #: the modules harder to read for no safety gain. It may not appear in
    #: CODE: not as an identifier, not as an attribute, and not as a string
    #: LITERAL, because ``metric_id == "tidmad_denoising_score"`` is dispatch
    #: written as a string and a census blind to it would be green for the
    #: wrong reason.
    TASK_TOKENS = ("tidmad", "pets", "davis", "oxford")

    def _offenders(self, path: Path) -> list[str]:
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                text = node.value.lower()
            elif isinstance(node, ast.Name):
                text = node.id.lower()
            elif isinstance(node, ast.Attribute):
                text = node.attr.lower()
            elif isinstance(node, ast.keyword) and node.arg:
                text = node.arg.lower()
            else:
                continue
            if any(token in text for token in self.TASK_TOKENS):
                found.append(f"{path.name}:{getattr(node, 'lineno', '?')}: {text[:80]}")
        return found

    def test_no_task_identity_reaches_the_code_of_either_half(self):
        """MUTATION TARGET: add ``if metric.metric_id == "tidmad_...":`` anywhere.

        Covers the projection AND the renderer, including a task name written
        as a string literal rather than an identifier.
        """
        import execute_tools.run_report as module

        repo_root = Path(module.__file__).resolve().parents[1]
        paths = [Path(module.__file__), *sorted((repo_root / "tools/run_report").rglob("*.py"))]
        assert len(paths) >= 5, f"the census walked only {len(paths)} files"
        offenders = [row for path in paths for row in self._offenders(path)]
        assert offenders == [], f"task identity reached executable code: {offenders}"

    def test_the_census_would_catch_a_planted_dispatch(self, tmp_path):
        """MUTATION TARGET: weaken the census to identifiers only.

        Anti-vacuity. Three plants — an identifier, a string literal
        comparison and a keyword argument — because a census that only sees
        one of them is green for a reason narrower than the claim it makes.
        """
        planted = tmp_path / "planted.py"
        planted.write_text(
            '"""A docstring naming TIDMAD and DAVIS is fine."""\n'
            "def f(spec):\n"
            '    if spec.id == "tidmad_denoising_score":\n'
            "        return 1\n"
            "    tidmad_special = 2\n"
            "    return g(davis_mode=tidmad_special)\n"
        )
        offenders = self._offenders(planted)
        assert len(offenders) >= 3, f"the census saw only {offenders}"
        assert not any("docstring" in o for o in offenders), (
            "prose must stay allowed; the docstring names two tasks"
        )

    def test_the_projection_treats_a_non_tidmad_run_identically(self):
        """The real Pets declarations must project with no special-casing."""
        declarations = _pets_declarations()
        spec = metric_spec_from_declaration(declarations["metric_spec"])
        run = project_run(
            _output([_record("a", status="success", score=0.027, metric_id="accuracy")], spec=spec),
            source_path="x",
        )
        assert run.metric is not None
        assert run.metric.metric_id == "accuracy"
        assert run.attempts[0].best_so_far == 0.027


class TestTrajectoryIsTheSharedConsumerModel:
    """§V.5 — one projection, two presentation consumers."""

    def test_the_trajectory_spans_runs_because_a_chain_spans_files(self, report):
        """MUTATION TARGET: build the trajectory per run.

        Each chain iteration is a separate ``run_output`` file, and the
        question an operator asks — "is this campaign improving?" — spans
        them. A per-run curve would show three single points.
        """
        assert len(report.trajectory.points) == 3
        assert [p.run_name for p in report.trajectory.points] == [
            "iter_001",
            "iter_002",
            "iter_003",
        ]

    def test_an_empty_corpus_trajectory_declines_rather_than_returning_empty(self):
        trajectory = build_trajectory([])
        assert trajectory.metric is None
        assert trajectory.refusal is not None
        assert trajectory.points == []


# ---------------------------------------------------------------------------
# Builders — every object goes through the PRODUCTION schema, so a fixture
# cannot drift from the contract it is standing in for.
# ---------------------------------------------------------------------------


def _spec() -> MetricSpec:
    """A REAL declared spec, rebound through the ONE sanctioned entry point.

    ``MetricSpec.model_validate(spec.model_dump())`` does NOT round-trip:
    ``scoreability`` is an abstract ``SerializeAsAny`` field, so a dump emits
    the SUBCLASS's fields and the base rejects them as ``extra_forbidden``.
    ``metric_spec_from_declaration`` is the rebind every persisting schema
    uses (through ``MetricSpecField``), so a test reaching for
    ``model_validate`` would be constructing something production never can.
    """
    return metric_spec_from_declaration(_pets_declarations()["metric_spec"])


def _record(
    exp_id: str,
    *,
    status: str,
    score: float | None = None,
    identity: bool = True,
    metric_id: str = "accuracy",
    metric_direction: str = "higher",
    history: dict | None = None,
    gates: list[PersistedHealthGateResult] | None = None,
    secondary_results: list[MetricResult] | None = None,
    attribution: dict | None = None,
    refusal: bool = False,
) -> ExperimentRecord:
    payload: dict = {
        "exp_id": exp_id,
        "status": status,
        "model_type": "m",
        "timestamp": "2026-08-24 00:00:00",
        "params": {},
        "denoising_score": score,
        "health_gate_results": [g.model_dump() for g in (gates or [])],
        "secondary_metric_results": [s.model_dump() for s in (secondary_results or [])],
    }
    if identity and score is not None and not refusal:
        payload["metric_result"] = MetricResult(
            metric_id=metric_id, direction=metric_direction, scalar=score
        ).model_dump()
    if refusal:
        payload["metric_refusal"] = NotScoreableResult(
            metric_id=metric_id,
            direction=metric_direction,
            verdict={
                "contract_id": "deliverable_presence",
                "failures": [{"requirement": "deliverable", "detail": "missing"}],
            },
        ).model_dump()
    if history is not None:
        payload["training_history"] = history
    if attribution is not None:
        payload["failure_attribution"] = attribution
    return ExperimentRecord.model_validate(payload)


def _output(
    records: list[ExperimentRecord],
    *,
    spec: MetricSpec | None,
    secondaries: list[MetricSpec] | None = None,
) -> HyperparamTuningOutput:
    return HyperparamTuningOutput.model_validate(
        {
            "run_name": "r",
            "model_type": "m",
            "file_index": 6,
            "status": "completed",
            "completed_rounds": 1,
            "total_attempts": len(records),
            "started_at": "2026-08-24 00:00:00",
            "finished_at": "2026-08-24 01:00:00",
            "all_records": [r.model_dump() for r in records],
            "metric_spec": None if spec is None else spec.model_dump(),
            "secondary_metric_specs": (
                None if secondaries is None else [s.model_dump() for s in secondaries]
            ),
        }
    )
