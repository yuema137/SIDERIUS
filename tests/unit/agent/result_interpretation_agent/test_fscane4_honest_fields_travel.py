"""F-SCANE-4 — the honest per-model fields travel; the mixed ones no longer travel alone.

Historical regression boundary retained after campaign evidence moved to external ownership.

    finding: ModelRunSummary.best_valid_formal_score ... - the only per-model
    headline that is BOTH HealthGate-valid AND formal - has no production
    consumer past construction. ModelRunSummary.formal_file_vector, documented
    "Definitive per-file performance", has none at all - while the MIXED
    best_file_vector IS consumed ...

    shape: This is the F-SCANB-3 pattern one layer up: the honest field
    exists, is persisted, and decides nothing, while the mixed field is the
    one rendered.

The defect only this file catches
---------------------------------
Every per-model headline the interpreter's LLM used to see is mixed on one
axis or the other — ``Raw best score`` and ``Best valid score`` may come from
a TRIAL round, ``Formal round score`` may come from a health-INVALID record.
``best_valid_formal_score`` is the only one that is both, and it reached
nothing past ``evidence.py``'s constructor. ``formal_file_vector``, declared
"Definitive per-file performance", reached nothing at all.

Two consumers, two mutations:

* the per-model prompt states the valid-formal headline, and NAMES its absence
  (delete the block in ``rendering.py`` -> ``TestTheValidFormalHeadlineIsRendered``
  red);
* the per-model prompt renders the definitive per-sample vector where no
  enriched formal table exists — the composed-run case, in which the enriched
  table is deliberately omitted (F-12e-UX-7) and the definitive evidence
  therefore reached nothing at all (delete the ``elif`` ->
  ``TestTheDefinitiveVectorIsRendered`` red);

Every summary here is built by the PRODUCER
(``tuning_output_to_model_run_summary``) from real ``ExperimentRecord``s, so
the fields under test are the ones production computes, not values this file
chose.

**Deliberately NOT changed here**, and recorded so a later reader does not
mistake either omission for an oversight.

* ``prediction._PER_SAMPLE_KEY`` still resolves per-sample prediction forms
  from the MIXED best score table. Repointing it at the formal evidence
  would change which value the prediction pool is scored against — a
  scientific change needing a new ``prediction_evaluation_semantics`` id
  and an operator decision, not a reporting fix.
* the ``_stats`` knowledge cache still carries only the mixed pair, so a
  model that goes QUIET keeps ``formal_score`` and loses
  ``best_valid_formal_score``. Writing the honest pair into ``_stats``
  today would create a second field that is persisted and read by nothing
  — the exact defect this row records. Closing it properly means carrying
  a per-model valid-formal aggregate through ``precompute_evidence`` into
  the CROSS-MODEL synthesis block, beside ``per_model_formal``.
"""

from __future__ import annotations

from agent.prompt_templates.interpretation.rendering import _build_per_model_prompt
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import accuracy_like_spec

ORDER = MetricOrder(accuracy_like_spec())
REQUIRED_GATES = frozenset({"synthetic_stability_blocking"})

#: The exact sentence the renderer emits when no HealthGate-valid formal
#: result exists. Hardcoded, not read back from the renderer.
NO_VALID_FORMAL_LINE = (
    "Best valid formal    : NONE — this model produced no "
    "HealthGate-valid formal result; every score above is from a "
    "trial round, a health-invalid record, or both."
)


def _record(
    exp_id: str,
    score: float | None,
    *,
    model_type: str = "punet",
    is_trial: bool = False,
    health_gate_enabled: bool = False,
    file_vector: list[float] | None = None,
) -> dict:
    payload: dict = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": "2026-08-27T00:00:00Z",
        "params": {},
        "denoising_score": score,
        "is_trial": is_trial,
        # `False` is the classifier's explicit waiver: a run with gates
        # disabled has VALID successful records. Left at `True` with no gate
        # results the record classifies UNKNOWN, which is NOT valid — the
        # "formal but its health could not be established" case below.
        "health_gate_enabled": health_gate_enabled,
    }
    if file_vector is not None:
        payload["file_vector"] = file_vector
    return payload


def _summary(*records: dict, model_type: str = "punet"):
    """Build the summary the way PRODUCTION builds it."""
    output = HyperparamTuningOutput.model_validate(
        {
            "run_name": "fscane4",
            "model_type": model_type,
            "file_index": 6,
            "status": "completed",
            "completed_rounds": len(records),
            "total_attempts": len(records),
            "started_at": "2026-08-27T00:00:00Z",
            "finished_at": "2026-08-27T01:00:00Z",
            "best_denoising_score": max(
                (r["denoising_score"] for r in records if r["denoising_score"] is not None),
                default=None,
            ),
            "all_records": [ExperimentRecord.model_validate(r) for r in records],
        }
    )
    return tuning_output_to_model_run_summary(
        output,
        order=ORDER,
        required_gate_ids=REQUIRED_GATES,
    )


def _prompt(summary) -> str:
    return _build_per_model_prompt(summary, description="d", order=ORDER)


class TestTheValidFormalHeadlineIsRendered:
    def test_a_valid_formal_result_is_stated_as_its_own_headline(self):
        summary = _summary(
            _record("t1", 5.0, is_trial=True),
            _record("f1", 2.0),
        )
        # Non-vacuity: the producer really distinguishes the two, and the
        # mixed headline really is the misleading one here.
        assert summary.best_denoising_score == 5.0
        assert summary.best_valid_formal_score == 2.0

        block = _prompt(summary)
        assert "Best valid formal    : 2.0" in block
        assert "Raw best score       : 5.0" in block

    def test_the_absence_is_NAMED_when_no_formal_round_ran(self):
        summary = _summary(_record("t1", 5.0, is_trial=True))
        assert summary.formal_score is None
        assert summary.best_valid_formal_score is None

        assert NO_VALID_FORMAL_LINE in _prompt(summary)

    def test_a_formal_result_whose_health_is_not_established_still_names_the_absence(self):
        """The sharpest case, and the one an omission would hide.

        This model HAS a formal round — ``Formal round score`` renders a
        number — but its HealthGate validity could not be established, so it
        is not a valid formal result. Omitting the line would leave that
        number standing as the model's authoritative headline."""
        summary = _summary(
            _record("t1", 5.0, is_trial=True),
            _record("f1", 2.0, health_gate_enabled=True),
        )
        assert summary.formal_score == 2.0
        assert summary.best_valid_formal_score is None

        block = _prompt(summary)
        assert "Formal round score   : 2.0" in block
        assert NO_VALID_FORMAL_LINE in block

    def test_a_valid_formal_run_does_not_render_the_absence_line(self):
        """The complement, so the assertions above cannot pass on a renderer
        that emits the NONE sentence unconditionally."""
        summary = _summary(_record("f1", 2.0))
        assert "NONE — this model produced no" not in _prompt(summary)


class TestTheDefinitiveVectorIsRendered:
    def test_the_formal_vector_renders_where_no_enriched_table_exists(self):
        """A COMPOSED run omits the enriched score table by design
        (F-12e-UX-7), so the "definitive per-file performance" the summary
        carries used to reach nothing at all."""
        summary = _summary(
            _record("t1", 5.0, is_trial=True, file_vector=[9.0, 9.0]),
            _record("f1", 2.0, file_vector=[1.5, 2.5]),
        )
        # Non-vacuity: the enriched view really is absent and the raw
        # definitive vector really is present.
        assert summary.formal_score_table is None
        assert summary.formal_file_vector == [1.5, 2.5]

        block = _prompt(summary)
        assert "### Per-sample performance (formal round — definitive, no enriched table)" in block
        assert "[1.5, 2.5]" in block

    def test_no_formal_vector_renders_no_section(self):
        summary = _summary(_record("t1", 5.0, is_trial=True, file_vector=[9.0, 9.0]))
        assert summary.formal_file_vector is None
        assert "definitive, no enriched table" not in _prompt(summary)

    def test_the_mixed_best_vector_is_never_promoted_into_the_definitive_section(self):
        """The section names the FORMAL evidence. Rendering the mixed
        `best_file_vector` under a "definitive" header would restate the
        defect with a better label."""
        summary = _summary(
            _record("t1", 5.0, is_trial=True, file_vector=[9.0, 9.0]),
            _record("f1", 2.0, file_vector=[1.5, 2.5]),
        )
        block = _prompt(summary)
        header = "### Per-sample performance (formal round — definitive, no enriched table)"
        assert header in block, "the definitive section is absent, so this check is vacuous"
        definitive = block.split(header, 1)[1].split("###", 1)[0]
        assert "[1.5, 2.5]" in definitive
        assert "[9.0, 9.0]" not in definitive
