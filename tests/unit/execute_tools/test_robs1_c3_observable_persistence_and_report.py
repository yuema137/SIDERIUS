"""`R-OBS-1` C3 — persistence into the record, and a consumer that reads it.

Levels 4 and 5 of the row's five-level required contract:

  level 4  persistence — it survives into the record
  level 5  downstream / report exposure — a consumer actually reads it

Families, each naming the defect only it catches:

  (a) a record carrying observations round-trips through `ExperimentRecord`
      and the run-report projection reads BOTH families;
  (b) the HTML renderer emits them, so a consumer exists at the surface a
      human sees, and emits NOTHING when a run declared none;
  (c) the persisted record of a NON-declaring run has no observable key at
      all — byte identity, not merely semantic emptiness;
  (d) the LLM-facing planner surface is unchanged: `static_observations` is
      hidden exactly as `training_history` and the secondaries are.

The level-3 producer evidence — that a REAL training run populates these —
lives in `test_robs1_c2_observable_producer.py`, which drives the trainer.
This file starts from a record, which is the right altitude for levels 4 and
5 and the wrong one for level 3.
"""

from __future__ import annotations

import json

import pytest

from agent.prompts import _PLANNER_HIDDEN_RECORD_KEYS, _planner_visible
from agent.schemas.hyperparam_tuning import ExperimentRecord
from execute_tools.run_report import AttemptView, ObjectiveHistory, project_attempt
from execute_tools.training_history import TrainingHistory, interpret_training_results
from tools.run_report.html import _observable_table


def _history(**overrides) -> dict:
    payload = {
        "objective_kind": "focal",
        "objective_config_fingerprint": "a" * 64,
        "objective_reduction": "mean",
        "comparability": "established",
        "epochs_planned": 3,
        "epochs_completed": 3,
        "train_objective": [3.0, 2.0, 1.0],
    }
    payload.update(overrides)
    return payload


def _record(**overrides) -> dict:
    payload = {
        "exp_id": "e1",
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-27 00:00:00",
        "params": {},
        "final_loss": 1.0,
        "loss_history": [3.0, 2.0, 1.0],
        "model_params": 10,
        "training_history": _history(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# (a) Level 4/5 — the record carries them and the projection reads them
# ---------------------------------------------------------------------------


class TestTheRecordCarriesBothFamilies:
    def test_both_families_survive_ExperimentRecord_validation(self):
        record = ExperimentRecord.model_validate(
            _record(
                training_history=_history(observations={"val_accuracy": [0.1, 0.4, 0.6]}),
                static_observations={"trainable_parameters": 1024.0},
            )
        )
        assert record.training_history is not None
        assert record.training_history.observations == {"val_accuracy": [0.1, 0.4, 0.6]}
        assert record.static_observations == {"trainable_parameters": 1024.0}

    def test_a_record_declaring_none_validates_to_the_empty_state(self):
        record = ExperimentRecord.model_validate(_record())
        assert record.training_history is not None
        assert record.training_history.observations == {}
        assert record.static_observations == {}

    def test_the_schema_still_REFUSES_a_misaligned_series(self):
        """The invariant that lets a consumer plot without re-deriving.

        `ObjectiveHistory` carries these on the same projection as R2/R3
        precisely because every series is guaranteed epoch-aligned. If the
        schema stopped enforcing it, that guarantee would silently become an
        assumption held by every downstream view.
        """
        with pytest.raises(ValueError, match="expected epochs_completed"):
            TrainingHistory.model_validate(_history(observations={"bad": [0.1, 0.2]}))

    def test_the_run_report_projection_reads_BOTH_families(self):
        """Level 5: a production consumer, not a test, reads the values."""
        record = ExperimentRecord.model_validate(
            _record(
                training_history=_history(observations={"val_accuracy": [0.1, 0.4, 0.6]}),
                static_observations={"trainable_parameters": 1024.0},
            )
        )
        view = project_attempt(record, position=0, run_metric=None, declared_secondaries=[])
        assert view.objective is not None
        assert view.objective.observations == {"val_accuracy": [0.1, 0.4, 0.6]}
        assert view.static_observations == {"trainable_parameters": 1024.0}

    def test_the_projection_reaches_report_json_verbatim(self):
        """`report.json` is the machine-readable half of the consumer.

        A view field that never serializes is not exposure — it is a value
        that reaches a Python object and stops there.
        """
        record = ExperimentRecord.model_validate(
            _record(
                training_history=_history(observations={"val_accuracy": [0.1, 0.4, 0.6]}),
                static_observations={"params": 8.0},
            )
        )
        view = project_attempt(record, position=0, run_metric=None, declared_secondaries=[])
        payload = json.loads(view.model_dump_json())
        assert payload["objective"]["observations"] == {"val_accuracy": [0.1, 0.4, 0.6]}
        assert payload["static_observations"] == {"params": 8.0}


# ---------------------------------------------------------------------------
# (b) The rendered surface a human reads
# ---------------------------------------------------------------------------


class TestTheRenderedSurface:
    def _view(self, **overrides) -> AttemptView:
        record = ExperimentRecord.model_validate(_record(**overrides))
        return project_attempt(record, position=0, run_metric=None, declared_secondaries=[])

    def test_the_html_names_each_observable_its_acquisition_and_a_value(self):
        html = _observable_table(
            self._view(
                training_history=_history(observations={"val_accuracy": [0.1, 0.4, 0.6]}),
                static_observations={"trainable_parameters": 1024.0},
            )
        )
        assert "val_accuracy" in html
        assert "trainable_parameters" in html
        assert "dynamic" in html
        assert "static" in html
        # The LATEST point of the series, not the first — a reader comparing
        # attempts wants where each one ended up.
        assert "0.6" in html
        assert "3 epoch(s)" in html

    def test_the_html_states_that_observables_are_NEVER_RANKED(self):
        """`D-BUD-16`'s prohibition, on the page that displays the values.

        A number rendered beside a score invites a reader — human or model —
        to trade the two off. The caption is the control that says not to.
        """
        html = _observable_table(
            self._view(training_history=_history(observations={"x": [1.0, 2.0, 3.0]}))
        )
        assert "never ranked" in html

    def test_a_run_declaring_none_renders_ZERO_BYTES(self):
        """The report of every existing run is unchanged, character for
        character, because this renderer contributes nothing at all."""
        assert _observable_table(self._view()) == ""

    def test_a_run_with_no_training_history_renders_zero_bytes(self):
        """A failure or skip record has no objective projection at all."""
        assert _observable_table(self._view(training_history=None)) == ""


class TestTheRendererIsREACHEDByTheRealReportPath:
    """Reachability: `_observable_table` is actually called by the page.

    Every assertion above calls the renderer directly. A renderer that is
    correct and never invoked leaves all of them green while no report ever
    shows an observable — which is the exact shape of a "level 5" that
    satisfies a grep and exposes nothing.
    """

    def _workspace_with_observations(self, tmp_path):
        """A REAL committed run output, with observations added to one record.

        The fixture corpus predates this family, so nothing in it declares an
        observable; injecting into a genuine record exercises the real
        `build_report` → `project_run` → `project_attempt` → `render_html`
        path rather than a hand-built `RunReport`.
        """
        from pathlib import Path

        from execute_tools.run_report import RUN_OUTPUT_GLOB

        workspace = Path(__file__).resolve().parent / "step12_pr12e_fixtures" / "chain_workspace"
        source = sorted(workspace.rglob(RUN_OUTPUT_GLOB))[0]
        doc = json.loads(source.read_text())
        patched = False
        for record in doc["all_records"]:
            history = record.get("training_history")
            if isinstance(history, dict) and history.get("train_objective"):
                history["observations"] = {
                    "robs1_probe_series": [0.5] * history["epochs_completed"]
                }
                record["static_observations"] = {"robs1_probe_scalar": 42.0}
                patched = True
                break
        assert patched, "the fixture corpus carries no record with a training history"
        path = tmp_path / "run_output_robs1.json"
        path.write_text(json.dumps(doc))
        return path

    def test_the_rendered_page_shows_both_families(self, tmp_path):
        from execute_tools.run_report import build_report
        from tools.run_report.figures import render_figures
        from tools.run_report.html import render_html

        report = build_report(run_outputs=[self._workspace_with_observations(tmp_path)])
        html = render_html(report, render_figures(report, tmp_path / "fig"))
        assert "robs1_probe_series" in html
        assert "robs1_probe_scalar" in html
        assert "42" in html

    def test_the_unpatched_fixture_corpus_renders_no_observable_bytes(self, tmp_path):
        """The same corpus, untouched: every existing report is unchanged."""
        from pathlib import Path

        from execute_tools.run_report import build_report
        from tools.run_report.figures import render_figures
        from tools.run_report.html import render_html

        workspace = Path(__file__).resolve().parent / "step12_pr12e_fixtures" / "chain_workspace"
        report = build_report(workspace=workspace)
        html = render_html(report, render_figures(report, tmp_path / "fig"))
        assert "Observables" not in html


# ---------------------------------------------------------------------------
# (c) Byte identity of the persisted record
# ---------------------------------------------------------------------------


class TestPersistedByteIdentity:
    def test_the_record_writer_omits_the_key_when_nothing_was_observed(self):
        """Conditional insertion, the `secondary_metric_results` precedent.

        A schema field with a default would materialize `"static_observations":
        {}` into every record of every run forever. The writer's `if` is what
        keeps a non-declaring run's persisted bytes identical to the ones it
        wrote before this family existed — so this asserts the SOURCE
        condition, not just the resulting dict.
        """
        import importlib
        import inspect

        # Full dotted path: the node package re-exports its main module under
        # the package name, so `from nodes.ml_... import records` resolves to
        # the wrong object.
        records = importlib.import_module("nodes.ml_hyperparameter_tune_agent.records")
        source = inspect.getsource(records)
        assert "if training_results.static_observations:\n" in source
        assert 'final_record["static_observations"]' in source
        # The precedent this copies, asserted alongside so the two cannot
        # drift apart silently: if the secondaries ever stop being written
        # conditionally, the rule this test enforces has changed and someone
        # should be told rather than left with one family following a
        # convention the other abandoned.
        assert "if secondary_metric_results:\n" in source

    def test_an_ObjectiveHistory_default_is_empty_not_None(self):
        """`{}` and absent are the same state; `None` would be a third one.

        A tri-state would force every consumer to distinguish "declared
        nothing" from "declared something that produced nothing", which is a
        difference this family deliberately does not make.
        """
        history = ObjectiveHistory.from_history(TrainingHistory.model_validate(_history()))
        assert history.observations == {}


class TestPresenceOfTheKeyIsUNOBSERVABLE:
    """Nothing downstream may branch on whether the key is in the JSON.

    The record writer omits `static_observations` for a run that declares no
    static observable, so records written before and after this feature differ
    by the key's PRESENCE. If any consumer distinguished the two, that
    difference would become a behavioural fork between old and new records —
    the defect only this family of tests can catch, because every other test
    here constructs one shape or the other and never compares them.

    The structural half is a census (no `"static_observations" in`, no
    `.get("static_observations")`, no `hasattr`) — but a census is only as
    good as its patterns. These assert the PROPERTY instead: the two JSON
    shapes must be indistinguishable after validation.
    """

    def test_absent_and_empty_validate_to_the_SAME_record(self):
        without = ExperimentRecord.model_validate(_record())
        with_empty = ExperimentRecord.model_validate(_record(static_observations={}))
        assert "static_observations" not in _record()
        assert without.static_observations == with_empty.static_observations == {}
        assert without.model_dump() == with_empty.model_dump()

    def test_absent_and_empty_project_to_the_SAME_view(self):
        def view(payload):
            record = ExperimentRecord.model_validate(payload)
            return project_attempt(
                record, position=0, run_metric=None, declared_secondaries=[]
            ).model_dump_json()

        assert view(_record()) == view(_record(static_observations={}))

    def test_absent_and_empty_render_the_SAME_bytes(self):
        def html(payload):
            record = ExperimentRecord.model_validate(payload)
            return _observable_table(
                project_attempt(record, position=0, run_metric=None, declared_secondaries=[])
            )

        assert html(_record()) == html(_record(static_observations={})) == ""

    def test_a_trainer_payload_without_the_key_interprets_like_one_with_an_empty_map(self):
        """The same property one layer up, at the trainer -> tuner boundary."""
        base = {
            "final_loss": 1.0,
            "loss_history": [3.0, 2.0, 1.0],
            "model_params": 10,
            "training_history": _history(),
        }
        absent = interpret_training_results(base, expected_validation=False)
        empty = interpret_training_results(
            {**base, "static_observations": {}}, expected_validation=False
        )
        assert absent.static_observations == empty.static_observations == {}
        assert absent.model_dump() == empty.model_dump()


# ---------------------------------------------------------------------------
# (d) The LLM surface is unchanged
# ---------------------------------------------------------------------------


class TestThePlannerCannotSeeObservables:
    def test_static_observations_is_in_the_planner_hidden_set(self):
        assert "static_observations" in _PLANNER_HIDDEN_RECORD_KEYS
        # Its dynamic sibling needs no entry of its own: it rides
        # `training_history`, which is already hidden.
        assert "training_history" in _PLANNER_HIDDEN_RECORD_KEYS

    def test_the_planner_projection_actually_drops_it(self):
        """Reachability: membership in a frozenset proves nothing on its own.

        A key can be listed in the hidden set and still reach the prompt if
        the projection that consumes the set is bypassed.
        """
        visible = _planner_visible(
            {
                "exp_id": "e1",
                "denoising_score": 1.0,
                "static_observations": {"params": 8.0},
                "training_history": {"objective_kind": "focal"},
            }
        )
        assert "static_observations" not in visible
        assert "training_history" not in visible
        assert visible["denoising_score"] == 1.0
