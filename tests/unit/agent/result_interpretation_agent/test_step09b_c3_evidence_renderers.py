"""Step 09b C3 — explicit evidence renderers, one authority per family.

Owners here (design §11.3 / §6):

* each renderer's OWN contract — identity words per direction, both
  diagnosis roles with their degenerate forms, the three secondary states
  (scored / refused / NAMED-ABSENT), failure counts from existing
  authorities with zero-omission and open future keys;
* the builders' presence gating — a summary carrying none of the new
  evidence renders NONE of the new headers (legacy-summary safety);
* the "one authority" structural claim — the builders contain no inline
  formatting of these families;
* secondaries are INERT: flipping every secondary value changes no ordering
  output (the 09a behavioural claim, re-proven over the rendering surface).

Expectations are hand-owned literals; nothing is read back from the
function under test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agent.prompt_templates.interpretation import rendering
from agent.prompt_templates.interpretation.rendering import (
    _build_per_model_prompt,
    _build_synthesis_prompt,
    render_failure_counts,
    render_interpretation_diagnosis_lines,
    render_metric_identity,
    render_secondary_metrics,
)
from agent.schemas.interpretation import (
    MetricIdentity,
    ModelRunSummary,
    RecordFailureCounts,
    SecondaryMetricEvidence,
)
from agent.schemas.training_diagnosis import TrainingDiagnosis
from execute_tools.evaluation_metric import (
    MetricResult,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from tests.helpers.metric_fixtures import accuracy_like_spec, error_like_spec

REPO_ROOT = Path(__file__).resolve().parents[4]


def _summary(**overrides) -> ModelRunSummary:
    base = {
        "model_type": "m",
        "run_name": "r",
        "status": "completed",
        "completed_rounds": 1,
        "best_denoising_score": 1.0,
        "worst_denoising_score": 0.5,
    }
    return ModelRunSummary(**{**base, **overrides})


# ---------------------------------------------------------------------------
# Metric identity
# ---------------------------------------------------------------------------


class TestMetricIdentityRenderer:
    def test_higher_direction_words(self):
        line = render_metric_identity(MetricIdentity(metric_id="accuracy", direction="higher"))
        assert line == "golden metric `accuracy` (higher is better)"

    def test_lower_direction_words(self):
        """DAVIS's regime: the SAME renderer must say lower."""
        line = render_metric_identity(MetricIdentity(metric_id="mse", direction="lower"))
        assert line == "golden metric `mse` (lower is better)"

    def test_absent_identity_renders_nothing(self):
        assert render_metric_identity(None) is None

    def test_the_id_is_carried_verbatim_never_parsed(self):
        weird = "Some.Task/metric-v2 (raw)"
        line = render_metric_identity(MetricIdentity(metric_id=weird, direction="lower"))
        assert f"`{weird}`" in line


# ---------------------------------------------------------------------------
# Training diagnosis
# ---------------------------------------------------------------------------


def _diagnosis(**overrides) -> TrainingDiagnosis:
    base = {
        "state": "ok",
        "validation_state": "absent",
        "train_first": 2.9,
        "train_last": 2.35,
        "train_trend": "decreasing",
        "epochs_completed": 5,
    }
    return TrainingDiagnosis(**{**base, **overrides})


class TestDiagnosisRenderer:
    def test_both_roles_render_separately(self):
        lines = render_interpretation_diagnosis_lines(_diagnosis(), _diagnosis(train_last=2.10))
        assert len(lines) == 2
        assert lines[0].startswith("  best: ")
        assert lines[1].startswith("  formal: ")
        assert "2.35" in lines[0] and "2.10" in lines[1], "roles must not be conflated"

    def test_absent_role_contributes_no_line(self):
        assert len(render_interpretation_diagnosis_lines(_diagnosis(), None)) == 1
        assert render_interpretation_diagnosis_lines(None, None) == []

    def test_degenerate_states_render_explicitly_not_silently(self):
        absent = render_interpretation_diagnosis_lines(_diagnosis(state="absent"), None)
        invalid = render_interpretation_diagnosis_lines(
            _diagnosis(state="invalid", train_first=None, train_last=None, train_trend=None), None
        )
        assert absent == ["  best: training dynamics: none recorded"]
        assert invalid == ["  best: training dynamics: invalid (non-finite)"]

    def test_the_line_grammar_is_the_07b_authority(self):
        """Not a re-implementation: the same function the tuner renders with."""
        from agent.prompt_templates.tuner.rendering import render_training_dynamics_line

        d = _diagnosis()
        assert render_interpretation_diagnosis_lines(d, None) == [
            f"  best: {render_training_dynamics_line(d, None)}"
        ]


# ---------------------------------------------------------------------------
# Secondary metrics
# ---------------------------------------------------------------------------


def _scored(spec, value: float) -> SecondaryMetricEvidence:
    return SecondaryMetricEvidence(
        spec=spec,
        result=MetricResult(metric_id=spec.id, direction=spec.direction, scalar=value),
    )


class TestSecondaryRenderer:
    def test_scored_secondary_states_its_own_direction(self):
        lines = render_secondary_metrics([_scored(accuracy_like_spec("macro_f1"), 0.42)])
        assert lines == ["  `macro_f1` (higher is better): 0.42"]

    def test_a_lower_is_better_secondary_says_lower(self):
        lines = render_secondary_metrics([_scored(error_like_spec("mae"), 0.017)])
        assert lines == ["  `mae` (lower is better): 0.017"]

    def test_an_unavailable_secondary_is_a_named_absence_never_a_number(self):
        lines = render_secondary_metrics([SecondaryMetricEvidence(spec=error_like_spec("mae"))])
        assert lines == ["  `mae` (lower is better): declared, not evaluated this run"]
        assert not re.search(r"\d", lines[0].split("):")[1])

    def test_a_refused_secondary_carries_its_contract_id_verbatim(self):
        spec = accuracy_like_spec("psnr_like")
        refusal = NotScoreableResult(
            metric_id=spec.id,
            direction=spec.direction,
            verdict=ScoreabilityVerdict(
                contract_id="presence_v1",
                failures=(
                    ScoreabilityFailure(
                        requirement="deliverable_present", detail="missing channel"
                    ),
                ),
            ),
        )
        lines = render_secondary_metrics([SecondaryMetricEvidence(spec=spec, refusal=refusal)])
        assert lines == ["  `psnr_like` (higher is better): not scoreable (presence_v1)"]

    def test_declaration_order_is_preserved(self):
        lines = render_secondary_metrics(
            [_scored(accuracy_like_spec("a"), 1.0), _scored(error_like_spec("b"), 2.0)]
        )
        assert [line.split("`")[1] for line in lines] == ["a", "b"]

    def test_no_secondaries_render_nothing(self):
        assert render_secondary_metrics([]) == []


# ---------------------------------------------------------------------------
# Failure counts
# ---------------------------------------------------------------------------


class TestFailureCountsRenderer:
    def test_hand_computed_mixed_record_set(self):
        counts = RecordFailureCounts(
            records_total=5,
            status_counts={"success": 3, "failed_oom": 1, "skipped_oom_risk": 1, "never": 0},
            diagnosis_state_counts={"ok": 2, "invalid": 1, "diagnosis_missing": 2},
            validation_state_counts={"present": 2, "absent": 3},
            metric_refusal_count=1,
            refusal_contract_ids={"presence_v1": 1},
            gate_action_counts={"none": 4, "invalidate_round": 1},
            health_provenance_counts={"gated": 5},
        )
        assert render_failure_counts(counts) == [
            "  records: 5",
            "  status: failed_oom=1, skipped_oom_risk=1, success=3",
            "  training diagnosis: diagnosis_missing=2, invalid=1, ok=2",
            "  validation: absent=3, present=2",
            "  gate actions: invalidate_round=1, none=4",
            "  health provenance: gated=5",
            "  metric refusals: 1 (presence_v1=1)",
        ]

    def test_zero_counts_are_omitted_not_printed(self):
        rendered = render_failure_counts(
            RecordFailureCounts(records_total=1, status_counts={"success": 1, "failed_oom": 0})
        )
        assert rendered == ["  records: 1", "  status: success=1"]
        assert "failed_oom" not in "".join(rendered)

    def test_absent_counts_render_nothing_never_zero_failures(self):
        assert render_failure_counts(None) == []

    def test_an_unknown_future_status_renders_verbatim(self):
        """Open dicts: a new authority value needs no source growth here."""
        rendered = render_failure_counts(
            RecordFailureCounts(records_total=1, status_counts={"some_future_status": 1})
        )
        assert "  status: some_future_status=1" in rendered


# ---------------------------------------------------------------------------
# Builder integration — presence gating
# ---------------------------------------------------------------------------


class TestBuilderPresenceGating:
    def test_a_bare_summary_renders_none_of_the_new_headers(self):
        prompt = _build_per_model_prompt(_summary(), "desc")
        for header in (
            "Metric               :",
            "### Training dynamics",
            "### Secondary metrics",
            "### Record outcomes",
        ):
            assert header not in prompt

    def test_a_fully_evidenced_summary_renders_all_sections_in_order(self):
        prompt = _build_per_model_prompt(
            _summary(
                metric_identity=MetricIdentity(metric_id="mse", direction="lower"),
                best_training_diagnosis=_diagnosis(),
                secondary_metrics=[_scored(accuracy_like_spec("psnr"), 31.4)],
                failure_counts=RecordFailureCounts(records_total=2, status_counts={"success": 2}),
            ),
            "desc",
        )
        positions = [
            prompt.index("golden metric `mse` (lower is better)"),
            prompt.index("### Training dynamics"),
            prompt.index("### Secondary metrics"),
            prompt.index("### Record outcomes"),
            prompt.index("### Architecture Description"),
        ]
        assert positions == sorted(positions), "sections must render at their frozen positions"

    def test_the_synthesis_prompt_states_the_run_metric_when_bound(self):
        rendered = _build_synthesis_prompt(
            per_model_summaries={"m": {"key_findings": [], "bottlenecks": []}},
            per_model_best={"m": 0.1},
            per_model_worst={"m": 0.2},
            overall_best_score=0.1,
            overall_worst_score=0.2,
            overall_best_config=None,
            metric_identity=MetricIdentity(metric_id="mse", direction="lower"),
        )
        assert "Metric: golden metric `mse` (lower is better)" in rendered

    def test_the_synthesis_prompt_omits_the_line_without_a_bound_identity(self):
        rendered = _build_synthesis_prompt(
            per_model_summaries={"m": {"key_findings": [], "bottlenecks": []}},
            per_model_best={"m": 0.1},
            per_model_worst={"m": 0.2},
            overall_best_score=0.1,
            overall_worst_score=0.2,
            overall_best_config=None,
        )
        assert "Metric:" not in rendered


# ---------------------------------------------------------------------------
# Structural: one authority per family; secondaries inert
# ---------------------------------------------------------------------------


class TestOneAuthorityPerFamily:
    RENDERERS = (
        "render_metric_identity",
        "render_interpretation_diagnosis_lines",
        "render_secondary_metrics",
        "render_failure_counts",
    )

    def test_each_family_has_exactly_one_definition(self):
        source = (REPO_ROOT / "src/agent/prompt_templates/interpretation/rendering.py").read_text()
        tree = ast.parse(source)
        defined = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name in self.RENDERERS
        ]
        assert sorted(defined) == sorted(self.RENDERERS)

    def test_the_builders_do_not_inline_the_family_formatting(self):
        """The builders CALL the renderers; they must not re-format inline."""
        source = (REPO_ROOT / "src/agent/prompt_templates/interpretation/rendering.py").read_text()
        tree = ast.parse(source)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef) or fn.name not in (
                "_build_per_model_prompt",
                "_build_synthesis_prompt",
            ):
                continue
            body = ast.unparse(fn)
            for token in ("is better)", "not evaluated this run", "training dynamics:"):
                assert token not in body, f"{fn.name} inlines family formatting: {token!r}"


class TestSecondariesAreInert:
    def test_flipping_every_secondary_value_changes_only_its_own_lines(self):
        def build(value: float) -> str:
            return _build_per_model_prompt(
                _summary(
                    metric_identity=MetricIdentity(metric_id="acc", direction="higher"),
                    secondary_metrics=[_scored(accuracy_like_spec("macro_f1"), value)],
                ),
                "desc",
            )

        a, b = build(0.10), build(0.99)

        def strip(text: str) -> list[str]:
            return [ln for ln in text.splitlines() if "macro_f1" not in ln]

        assert strip(a) == strip(b), "a secondary value moved something other than its own line"
        assert a != b, "anti-vacuity: the secondary value must render somewhere"


@pytest.mark.parametrize(
    "direction,expected", [("higher", "higher is better"), ("lower", "lower is better")]
)
def test_direction_words_come_from_the_order_authority(direction, expected):
    """No literal 'higher'/'lower' decision is made in this module."""
    line = render_metric_identity(MetricIdentity(metric_id="m", direction=direction))
    assert expected in line
    source = (REPO_ROOT / "src/agent/prompt_templates/interpretation/rendering.py").read_text()
    tree = ast.parse(source)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "render_metric_identity"
    )
    # Executable body only — the docstring legitimately EXPLAINS the rule it
    # is enforcing (the same docstring exclusion the C2 censuses use).
    executable = [
        stmt
        for stmt in fn.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    body = "\n".join(ast.unparse(stmt) for stmt in executable)
    assert "render_metric_direction_words" in body
    assert '"higher"' not in body and "'higher'" not in body
