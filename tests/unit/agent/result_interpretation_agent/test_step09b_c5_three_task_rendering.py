"""Step 09b C5 — three-task rendering contrast + the roadmap 11-A/11-B rungs.

Owners here (design §11.5 / §8):

* the §8 table as assertions, driven through the REAL builders over three
  materially different declarations — TIDMAD (higher, negative-valued,
  per-sample evidence, task blocks SUPPLIED), Pets (accuracy higher,
  scalar-only, one scored secondary, NO blocks) and DAVIS (**mse LOWER**,
  scalar-only, one scored + one NAMED-ABSENT secondary, NO blocks);
* the leak direction that matters: with no task blocks, NO TIDMAD science
  reaches a Pets/DAVIS prompt — no Impact_Score, no Log-of-Mean, no
  per-file instruction, no PSD volume line;
* the roadmap's one-axis rungs (`siderius_generic_framework_upgrade.md`
  :1233-1235): **11-A** varies metric identity ONLY (the rendered delta must
  be the identity/direction lines and nothing else); **11-B** varies table
  INDEXING only (the delta must be the table's own bytes).

Pets/DAVIS inputs are the 09a C7 pack `expected/` L1 fixtures — contract
evidence, NOT a claim that either task runs a production workflow. Every
expectation here is a hand-owned literal.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from agent.prompt_templates.interpretation.rendering import (
    _build_per_model_prompt,
    _build_per_model_system_prompt,
)
from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import (
    InterpretationInput,
    MetricIdentity,
    SecondaryMetricEvidence,
)
from agent.schemas.score_table import AggregateScalars, PerFileRow, ScoreComparisonTable
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import shipped_spec

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKS = {
    "pets": REPO_ROOT / "examples/oxford_iiit_pet/expected/interpretation_evidence_l1_fixture.json",
    "davis": REPO_ROOT
    / "examples/davis_future_prediction/expected/interpretation_evidence_l1_fixture.json",
}

#: TIDMAD science tokens that must NEVER reach a task that supplies no blocks.
TIDMAD_SCIENCE = ("Impact_Score", "Linear_Weight", "Log-of-Mean", "PSD segments")


def _pack(name: str) -> dict:
    return json.loads(PACKS[name].read_text(encoding="utf-8"))


def _pack_summary(name: str):
    data = _pack(name)
    output = HyperparamTuningOutput.model_validate(data["tuning_output"])
    order = MetricOrder(output.metric_spec)
    summary = tuning_output_to_model_run_summary(output, order=order)
    secondaries = [SecondaryMetricEvidence.model_validate(s) for s in data["secondary_metrics"]]
    return summary.model_copy(update={"secondary_metrics": secondaries}), output


# ---------------------------------------------------------------------------
# §8 three-task contrast
# ---------------------------------------------------------------------------


class TestThreeTaskContrast:
    def test_tidmad_renders_higher_with_task_science_supplied(self):
        system = _build_per_model_system_prompt(
            InterpretationInput(
                model_types=["wavenet"],
                task_description="Denoise SQUID data.",
                task_blocks=load_interpretation_task_blocks(),
            )
        )
        for token in TIDMAD_SCIENCE:
            assert token in system, f"{token} must reach TIDMAD's prompt through its blocks"
        user = _build_per_model_prompt(_tidmad_summary(), "desc", structured_health_feedback=False)
        assert "golden metric `tidmad_denoising_score` (higher is better)" in user
        assert "### Per-file performance (best experiment)" in user, "per-sample evidence renders"

    @pytest.mark.parametrize(
        "task,metric_id,direction",
        [("pets", "accuracy", "higher"), ("davis", "mse", "lower")],
    )
    def test_scalar_only_tasks_render_their_own_direction(self, task, metric_id, direction):
        summary, _ = _pack_summary(task)
        user = _build_per_model_prompt(summary, "desc")
        assert f"golden metric `{metric_id}` ({direction} is better)" in user

    @pytest.mark.parametrize("task", ["pets", "davis"])
    def test_a_task_without_blocks_receives_no_tidmad_science(self, task):
        """The leak direction that matters: framework prompt + no blocks."""
        system = _build_per_model_system_prompt(
            InterpretationInput(model_types=["m"], task_description="A different task.")
        )
        summary, _ = _pack_summary(task)
        user = _build_per_model_prompt(summary, "desc")
        for token in (*TIDMAD_SCIENCE, "### Task evidence guidance"):
            assert token not in system, f"{token} leaked into a block-less system prompt"
            assert token not in user, f"{token} leaked into a {task} user prompt"

    @pytest.mark.parametrize("task", ["pets", "davis"])
    def test_scalar_only_tasks_render_no_per_sample_section(self, task):
        summary, _ = _pack_summary(task)
        user = _build_per_model_prompt(summary, "desc")
        assert "### Per-file performance" not in user
        assert "file_index" not in user

    def test_pets_renders_its_one_scored_secondary(self):
        summary, _ = _pack_summary("pets")
        user = _build_per_model_prompt(summary, "desc")
        assert "### Secondary metrics (observational — never used for ranking)" in user
        assert "  `macro_f1` (higher is better): " in user

    def test_davis_renders_a_scored_and_a_named_absent_secondary(self):
        """The load-bearing row: `psnr` HIGHER beside a LOWER primary, and
        `mae` declared-but-unavailable — a named absence, never a number."""
        summary, _ = _pack_summary("davis")
        user = _build_per_model_prompt(summary, "desc")
        assert "  `psnr` (higher is better): " in user
        assert "  `mae` (lower is better): declared, not evaluated this run" in user

    def test_davis_best_is_the_smallest_score_and_the_prompt_says_so(self):
        """Anti-vacuity for the whole DAVIS row: a direction-blind builder
        would put the LARGEST mse on the 'Raw best score' line."""
        summary, output = _pack_summary("davis")
        scores = [r.denoising_score for r in output.all_records if r.denoising_score is not None]
        assert summary.best_denoising_score == min(scores), "best under `lower` is the smallest"
        assert summary.best_denoising_score != max(scores), "…and not the largest"
        user = _build_per_model_prompt(summary, "desc")
        assert f"Raw best score       : {summary.best_denoising_score}" in user

    @pytest.mark.parametrize("task", ["pets", "davis"])
    def test_the_fixture_is_labelled_l1_and_names_step_10(self, task):
        """Maturity honesty, re-asserted at the rendering rung."""
        note = _pack(task)["_fixture"]
        assert note["label"] == "l1_fixture"
        assert "NOT a real tuning output" in note["note"]
        assert "Step 10" in note["note"]


# ---------------------------------------------------------------------------
# Roadmap rungs 11-A / 11-B (one axis each)
# ---------------------------------------------------------------------------


def _tidmad_summary(*, table: ScoreComparisonTable | None = None, identity=None):
    """A TIDMAD-shaped summary; the rungs vary ONE field of it at a time."""
    from agent.schemas.interpretation import ModelRunSummary

    return ModelRunSummary(
        model_type="wavenet",
        run_name="r1",
        status="completed",
        completed_rounds=2,
        best_denoising_score=-2.33,
        best_valid_denoising_score=-2.33,
        worst_denoising_score=-2.91,
        round_scores=[-2.91, -2.33],
        round_conclusions=["a", "b"],
        metric_identity=identity
        or MetricIdentity(metric_id="tidmad_denoising_score", direction="higher"),
        best_score_table=table if table is not None else _table(per_sample=False),
    )


#: One row per validation file — the carrier's own topology rule. The rung
#: varies how those rows are LABELLED (file- vs sample-indexed), not how many
#: there are, which is exactly the one axis 11-B is allowed to move.
_N_ROWS = 20


def _table(*, per_sample: bool) -> ScoreComparisonTable:
    """The SAME carrier, indexed per-FILE or per-SAMPLE (rung 11-B's axis)."""
    label = "sample" if per_sample else "file"
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=0.1,
            ground_truth=100.0,
            model=1.0 + i,
            gain_vs_raw=0.9 + i,
            headroom_vs_gt=99.0 - i,
        )
        for i in range(_N_ROWS)
    ]
    return ScoreComparisonTable(
        rows=rows,
        aggregate=AggregateScalars(
            raw_baseline_scalar=0.1,
            ground_truth_scalar=100.0,
            model_scalar=2.0,
            percent_of_ceiling_log=0.2,
            num_sampled_files=_N_ROWS,
        ),
        s_max_global=1.0,
        reference_source="rung_fixture",
        rendered_markdown="\n".join(
            [f"| {label} | model |", *(f"| {label} {i} | {1.0 + i} |" for i in range(_N_ROWS))]
        ),
    )


def _diff_lines(a: str, b: str) -> list[str]:
    return [
        line
        for line in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


class TestRung11AMetricIdentityOnly:
    """Vary metric identity ONLY; the table stays per-file (roadmap :1233)."""

    def test_the_rendered_delta_is_exactly_the_identity_line(self):
        base = _build_per_model_prompt(_tidmad_summary(), "desc")
        stubbed = _build_per_model_prompt(
            _tidmad_summary(identity=MetricIdentity(metric_id="stub_error", direction="lower")),
            "desc",
        )
        delta = _diff_lines(base, stubbed)
        assert delta == [
            "-Metric               : golden metric `tidmad_denoising_score` (higher is better)",
            "+Metric               : golden metric `stub_error` (lower is better)",
        ], delta


class TestRung11BTableIndexingOnly:
    """Vary table indexing ONLY; the metric stays TIDMAD's (roadmap :1234)."""

    def test_the_rendered_delta_is_exactly_the_table_bytes(self):
        per_file = _build_per_model_prompt(_tidmad_summary(), "desc")
        per_sample = _build_per_model_prompt(_tidmad_summary(table=_table(per_sample=True)), "desc")
        delta = _diff_lines(per_file, per_sample)
        assert delta, "anti-vacuity: the table must actually differ"
        for line in delta:
            assert "file" in line or "sample" in line, f"non-table byte moved: {line!r}"
        assert not any("golden metric" in line for line in delta)

    def test_the_framework_injects_no_per_file_assumption_around_the_carrier(self):
        """The table is rendered from its own `rendered_markdown`; the
        framework adds no per-file instruction around a per-sample carrier."""
        rendered = _build_per_model_prompt(_tidmad_summary(table=_table(per_sample=True)), "desc")
        section = rendered.split("### Per-file performance (best experiment)")[1]
        assert "| sample |" in section
        for token in TIDMAD_SCIENCE:
            assert token not in section
