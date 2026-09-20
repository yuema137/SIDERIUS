"""Step-00 REC-1 / REC-2 / REC-3 / REC-4 — record & artifact baselines.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.3 / §22.1 (OD-2 outcome A) / §15.1 (roadmap steps 03/05/08/09/10/12).

REC-2's fixture path is the OD-2-approved one: a bounded pseudo tuner
iteration (``tests/helpers/step00_pseudo_iteration``) drives the REAL
production record assembly — every record funnels through the
``_emit_record`` seam (stamp → ``ExperimentRecord.model_validate`` →
``sandbox.save_record``); ``RecordingSandbox`` persists the validated
record verbatim (no ``_pseudo_origin``) and the pseudo score fixture
carries a length-20 vector. No test-side record normalization or
re-assembly.

The projection compares every field whose VALUE drives a production
decision; volatile-by-value fields (timestamps, exp_id values, measured
timings/memory, LLM free text, gpu_evidence) are reduced to
PRESENCE-ONLY markers — their keys stay pinned, only the measured/minted
value is free (design §13.3, review F4's honest exclusion claim).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import (
    ExperimentRecord,
    HyperparamTuningOutput,
    TrialConfig,
)
from agent.schemas.interpretation import InterpretationOutput
from tests.helpers.golden import assert_json_golden
from tests.helpers.step00_pseudo_iteration import (
    PLUGIN_MODEL_TYPE,
    run_bounded_pseudo_iteration,
)

# PR #548 declares one additive output field: formal_validity_feedback before
# trial_validity_feedback. Its independent ordered golden is updated surgically;
# no recorded scientific values or other schema fields were re-captured.
GOLDENS = Path(__file__).parent / "goldens"

_PRESENT = "<present>"

# ---------------------------------------------------------------------------
# REC-1 — ordered full field lists (Type 3). Hardcoded expectations,
# captured at clean tree; NEVER read back from the schema under test.
#
# Declared delta, `R-OBS-1` (2026-08-27): 63 -> 64. `static_observations`
# was inserted after `training_diagnosis`, the position `model_fields`
# reports for it. Measured before the list was touched: EXACTLY ONE ADDED
# NAME, zero moved, zero removed — and the same one key, `{}`, in each of
# the two REC-2 projection goldens, inserted surgically rather than
# re-captured. The record WRITER emits no key at all for a run that
# declares no static observable, so a non-declaring run's persisted record
# file is byte-identical; what these baselines see is the SCHEMA default
# materializing through `model_dump()`.
# NOTE: the duplicate `file_vector` declaration (design §13.8) is
# byte-identical and keeps first-declaration position — this list cannot
# detect it; the known-defect register is the guard.
# ---------------------------------------------------------------------------

EXPERIMENT_RECORD_FIELDS = [
    "record_type",
    "exp_id",
    "status",
    "model_type",
    "candidate_id",
    "timestamp",
    "file_index",
    "params",
    "logical_round",
    "attempt_index",
    "failure_stage",
    "failure_type",
    "proposed_config",
    "gpu_evidence",
    "failure_attribution",
    "traceback_summary",
    "counts_toward_completed_rounds",
    "counts_toward_attempt_budget",
    "final_loss",
    "loss_history",
    "model_params",
    # Step 07a C3 — ADDITIVE (design pr_07a §3.8 / ledger §14.3): the trainer's
    # observation payload + its diagnosis, persisted, hidden from both LLM-facing
    # renders. 56 → 58; positioned beside the legacy training keys, every other
    # position unchanged.
    "training_history",
    "training_diagnosis",
    # Data Analysis Gate 5 — additive, omitted from legacy serialization when
    # absent. A successful producer may bind one immutable trained-model
    # artifact; legacy records never guess reconstruction identity from paths.
    "trained_model_artifact_ref",
    "static_observations",
    "denoising_score",
    "file_vector",
    "score_table",
    "failure_reason",
    "gate_action",
    "health_gate_results",
    "scientific_authority",
    "training_psd_segments",
    "eval_psd_segments",
    "timing",
    # PR #560: retain the two existing execution receipt families through the
    # typed record boundary. Both remain omitted when absent; other fields
    # and legacy persisted values are unchanged.
    "training_budget",
    "runtime_verification",
    "memory",
    "is_trial",
    "trial_strategy",
    "trial_portion",
    "eval_strategy",
    "eval_portion",
    "train_portion",
    "target_files",
    "validation_workload_ceiling",
    # Step 11 C8 — ADDITIVE (design step_11 §7 C8 / R-11-9): the COMPOSED
    # run's task-composition fingerprint, stamped at the single
    # validate-and-persist seam so a later resume can certify the records it
    # restores. 61 -> 62; positioned with the other run-invariant stamps it
    # is validated beside, every earlier position unchanged. Defaults None,
    # so every record of an UN-composed run carries what these baselines
    # already pin.
    "task_composition_fingerprint",
    # arXiv U1 (#254) — ADDITIVE: the OPAQUE experiment-arm label, stamped at
    # the same validate-and-persist seam as the fingerprint above but ONLY
    # when the run is labelled, so the on-disk summary entries of an
    # unlabelled run (REC-3, pinned below) carry no key. 62 -> 63; positioned
    # beside the other run-invariant stamp it is validated with, every
    # earlier position unchanged. Defaults None, so every record of an
    # unlabelled run still projects to what REC-2 pins (with one added
    # `experiment_arm: null` — the same declared-delta shape as C8's).
    "experiment_arm",
    "resolved_data_scope",
    "health_gate_enabled",
    "planned_trial_strategy",
    "planned_eval_strategy",
    "strategy_normalization_reason",
    "proposed_order_strategy",
    "proposed_file_order",
    "ordering_proposal_rejected",
    "ordering_proposal_rejection_reason",
    "override_order_strategy",
    "override_file_order",
    "resolved_order_strategy",
    "resolved_file_order",
    "ordering_resolution_source",
    # Step 06 C4 — ADDITIVE (design step_06 §19 C4 / ledger §20.6): the metric
    # interface's record-facing payload. 54 → 56; every earlier position unchanged.
    "metric_result",
    "metric_refusal",
    # Step 10 / P2b C2 — ADDITIVE (design pr_10_p2b §4.3 / ledger §15.6): the
    # DECLARED observational secondaries' three outcomes — value, scientific
    # refusal, and crash provenance. 58 -> 61; positioned beside the primary
    # pair they mirror, every earlier position unchanged. All three default
    # EMPTY, so every record of a run that declares no secondary carries the
    # same values these baselines pin.
    "secondary_metric_results",
    "secondary_metric_refusals",
    "secondary_metric_errors",
]


def project_record(rec: dict) -> dict:
    """Load-bearing projection of a serialized ``ExperimentRecord``.

    Values kept: everything a production consumer decides on (status,
    scores, vector, score_table, params configs, trial/eval stamps,
    DataScope stamps, ordering provenance, gate fields). Values reduced
    to presence markers: minted/measured/free-text (their KEYS remain —
    a rename/drop still fails here and in REC-1).
    """
    p = dict(rec)
    for key in ("timestamp", "exp_id"):
        p[key] = _PRESENT if p.get(key) else p.get(key)
    if p.get("timing") is not None:
        p["timing"] = {k: (_PRESENT if v is not None else None) for k, v in p["timing"].items()}
    if p.get("memory") is not None:
        p["memory"] = {k: (_PRESENT if v is not None else None) for k, v in p["memory"].items()}
    if p.get("params") is not None:
        params = dict(p["params"])
        for key in ("run_name", "exp_id"):
            if key in params:
                params[key] = _PRESENT
        p["params"] = params
    if p.get("gpu_evidence") is not None:
        p["gpu_evidence"] = _PRESENT
    if p.get("traceback_summary") is not None:
        p["traceback_summary"] = _PRESENT
    return p


_PREFLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "step00_preflight_results.json"


@pytest.fixture(scope="module")
def pseudo_run(tmp_path_factory):
    """One bounded pseudo iteration shared by every test in this module.

    module-scoped monkeypatching is done manually because the built-in
    ``monkeypatch`` fixture is function-scoped. The pre-flight boundary is
    stubbed with the committed production-captured fixture (the tuner
    package's sanctioned unit-tier pattern — its autouse guard forbids the
    real isolated worker here).
    """
    from _pytest.monkeypatch import MonkeyPatch

    preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("step00_rec")
    try:
        output, bridge, sandbox, workspace = run_bounded_pseudo_iteration(
            tmp, mp, preflight_results=preflight
        )
    finally:
        mp.undo()
    return output, bridge, sandbox, workspace


class TestREC1FieldLists:
    def test_experiment_record_ordered_fields(self):
        assert list(ExperimentRecord.model_fields) == EXPERIMENT_RECORD_FIELDS

    def test_output_and_interpretation_field_counts_and_heads(self):
        """REC-3 schema part: HyperparamTuningOutput and
        InterpretationOutput ordered field lists, pinned as committed
        JSON expectations (46 and 35+ fields — too long for inline
        literals; the JSON golden IS the hardcoded expectation)."""
        assert_json_golden(
            {
                "hyperparam_tuning_output": list(HyperparamTuningOutput.model_fields),
                "interpretation_output": list(InterpretationOutput.model_fields),
                "trial_config": list(TrialConfig.model_fields),
            },
            GOLDENS / "rec3_schema_field_lists.json",
            surface="REC-3 artifact schema ordered field lists",
        )


class TestREC2CanonicalRecordProjection:
    def test_formal_success_record_projection(self, pseudo_run):
        output, _bridge, _sandbox, _ws = pseudo_run
        formal = [r for r in output.all_records if r.status == "success" and not r.is_trial]
        assert len(formal) == 1
        projected = project_record(formal[0].model_dump(mode="json"))
        assert_json_golden(
            projected,
            GOLDENS / "rec2_formal_success_projection.json",
            surface="REC-2 canonical formal-success record projection",
        )

    def test_oom_skip_record_projection(self, pseudo_run):
        """The skip taxonomy is load-bearing for resume/interpretation;
        pin the OOM-skip record's projection too."""
        output, _bridge, _sandbox, _ws = pseudo_run
        skips = [r for r in output.all_records if r.status == "skipped_oom_risk"]
        assert len(skips) == 1
        projected = project_record(skips[0].model_dump(mode="json"))
        assert_json_golden(
            projected,
            GOLDENS / "rec2_oom_skip_projection.json",
            surface="REC-2 OOM-skip record projection",
        )

    def test_projection_negative_control_volatile_fields_free(self, pseudo_run):
        """§19.2: a record differing ONLY in volatile values projects
        identically — the exclusion list excludes exactly what it claims."""
        output, _bridge, _sandbox, _ws = pseudo_run
        rec = output.all_records[-1].model_dump(mode="json")
        mutated = json.loads(json.dumps(rec))
        mutated["timestamp"] = "1999-01-01 00:00:00"
        mutated["exp_id"] = "other_model_other_run_999"
        if mutated.get("timing"):
            mutated["timing"] = {
                k: (v + 1.0 if isinstance(v, (int, float)) else v)
                for k, v in mutated["timing"].items()
            }
        assert project_record(mutated) == project_record(rec)


class TestREC3ArtifactShapes:
    def test_summary_file_shape_and_entry_key_lists(self, pseudo_run):
        """Previous assumption: on-disk summary entries carry the full
        54-key validated shape.
        Audit evidence (first run of this test): ``save_record``
        json-dumps the RAW construction-site dict — entry keys are the
        producing site's insertion-order subset, NOT the model dump.
        Corrected understanding: the summary artifact's contract is
        'validatable record dicts', with per-status key lists owned by
        the construction sites.
        Implementation consequence: pin (a) every entry validates via
        ``ExperimentRecord.model_validate`` (the production parse
        contract) and (b) the exact per-entry key lists as a golden.
        Validation consequence: a construction-site key add/drop/reorder
        or a validation-breaking change fails here."""
        _output, _bridge, _sandbox, ws = pseudo_run
        summary = json.loads((Path(ws) / "summary_step00_pseudo.json").read_text(encoding="utf-8"))
        assert isinstance(summary, list) and len(summary) == 3
        for entry in summary:
            ExperimentRecord.model_validate(entry)
        assert_json_golden(
            [{"status": e.get("status"), "keys": list(e.keys())} for e in summary],
            GOLDENS / "rec3_summary_entry_key_lists.json",
            surface="REC-3 summary-artifact per-entry key lists",
        )

    def test_manifest_key_sets_all_three_branches(self, pseudo_run, tmp_path):
        """REC-3: manifest.json key sets per status branch, produced by
        the REAL ``write_manifest`` (the resume contract's producer)."""
        from workflows.run_one_iteration import write_manifest

        output, _bridge, _sandbox, _ws = pseudo_run
        branches = {}
        for name, kwargs in (
            ("completed", {"results": [output]}),
            ("no_records", {"results": []}),
            ("failed", {"results": [], "crashed": True}),
        ):
            iter_dir = tmp_path / name
            iter_dir.mkdir()
            manifest = write_manifest(str(iter_dir), "step00_pseudo", **kwargs)
            branches[name] = {
                "status": manifest["status"],
                "keys": sorted(manifest.keys()),
            }
        assert branches["completed"]["status"] == "completed"
        assert branches["no_records"]["status"] == "no_records"
        assert branches["failed"]["status"] == "failed"
        assert_json_golden(
            branches,
            GOLDENS / "rec3_manifest_key_sets.json",
            surface="REC-3 manifest key sets (3 status branches)",
        )


class TestTC1bOnDiskTrialConfigArtifact:
    def test_tuner_written_trial_config_deep_equal(self, pseudo_run):
        """TC-1b (closure-audit F2): the REAL trial-decision resolution.
        The tuner composes and validates ``TrialConfig`` inline in
        ``run()`` and persists it per attempt
        (`ml_hyperparameter_tune_agent.py:4448-4452`) — this pins the
        ON-DISK artifacts the real resolution produced, closing the gap
        the schema-round-trip TC-1 tests could not (rewriting the inline
        composition now goes red here). Seeds are sha256-derived from
        `{run_name}_{total_attempts}` — deterministic for the fixture
        run, so pinned as values."""
        _output, _bridge, sandbox, _ws = pseudo_run
        configs_dir = Path(sandbox.dirs["configs"])
        artifacts = sorted(configs_dir.glob("trial_config_*.json"))
        assert artifacts, "the tuner must persist trial_config artifacts"
        assert_json_golden(
            [
                {"file": a.name, "config": json.loads(a.read_text(encoding="utf-8"))}
                for a in artifacts
            ],
            GOLDENS / "tc1b_on_disk_trial_configs.json",
            surface="TC-1b tuner-resolved on-disk TrialConfig artifacts",
        )


class TestREC4ExpIdFormat:
    def test_exp_id_format_and_ordering(self, pseudo_run):
        """REC-4 (Type 5): `{model}_{run}_{NNN}` with zero-padded,
        strictly increasing attempt counters. The `:03d` padding is
        SEMANTIC — `core/resume.py:438-441` breaks score ties
        lexicographically on exp_id (design §13, review F12).

        Scope (closure-audit F4): this pins the POST-PLAN composition
        site (tuner:4440) — the one every record in this fixture flows
        through. The pre-plan site (:4089) is only observable on a
        planning-stage failure record, which the bounded fixture does
        not produce; that variant is an explicit §15.2 deferral owned
        by step 05a.
        """
        output, _bridge, _sandbox, _ws = pseudo_run
        pattern = re.compile(rf"^{PLUGIN_MODEL_TYPE}_step00_pseudo_(\d{{3}})$")
        counters = []
        for rec in output.all_records:
            m = pattern.match(rec.exp_id)
            assert m, f"exp_id format drifted: {rec.exp_id!r}"
            counters.append(int(m.group(1)))
        assert counters == sorted(counters)
        assert len(set(counters)) == len(counters)


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
