"""Flag-OFF prompts preserve reviewed golden bytes outside declared changes.

The captures originated before the PR3 Health renderer (f3a0b8c). With
structured Health feedback disabled, Health-only additions remain absent.
The synthetic fixture supplies an explicit metric and gate roster.

2026-09-19: persisted role labels and aggregate-overlap guidance are intentional
additions, independent of the Health flag. The exact golden edits preserve
all other bytes. Fixture records are Formal (is_trial=False), including the
legacy Health record; legacy Health provenance does not mean missing role data.
"""

from pathlib import Path

from agent.prompt_templates.interpretation.rendering import (
    _build_per_model_prompt,
)
from execute_tools.metric_order import MetricOrder
from tests.helpers.metric_fixtures import accuracy_like_spec
from tests.unit.agent.result_interpretation_agent.test_round_health_summary import (
    _gate_result,
    _output,
    _record,
    tuning_output_to_model_run_summary,
)

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The synthetic metric is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(accuracy_like_spec())

GOLDENS = Path(__file__).parent / "goldens"


def _summary_collapse():
    """Original record shape, with explicit synthetic Health evidence."""
    return tuning_output_to_model_run_summary(
        _output(
            _record(
                "m_iter_001_001",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="[synthetic_stability_blocking] dispersion=1",
                health_gate_results=[_gate_result()],
                trial_portion=0.05,
                model_params=120000,
            ),
            _record(
                "m_iter_001_002",
                denoising_score=1.25,
                trial_portion=0.05,
                model_params=120000,
                health_gate_results=[],
            ),
        ),
        order=_STEP09A_ORDER,
    )


def _summary_legacy():
    return tuning_output_to_model_run_summary(
        _output(_record("m_iter_001_001", denoising_score=0.7)), order=_STEP09A_ORDER
    )


def test_per_model_prompt_parity_with_health_data_present():
    """The strong form of the claim: health evidence EXISTS on the summary
    (fingerprint, gate outcomes) and the flag-OFF prompt still matches the
    pre-PR3 golden byte for byte."""
    summary = _summary_collapse()
    assert summary.round_health[0].fingerprint is not None  # data is there
    rendered = _build_per_model_prompt(
        summary,
        "A test architecture.",
        expert_advice_str="Focus on stability.",
        human_advice=None,
    )
    assert rendered == (GOLDENS / "per_model_prompt_collapse.txt").read_text()


def test_per_model_prompt_parity_legacy_summary():
    rendered = _build_per_model_prompt(
        _summary_legacy(),
        "A test architecture.",
        expert_advice_str="",
        human_advice="Try smaller lr.",
    )
    assert rendered == (GOLDENS / "per_model_prompt_legacy.txt").read_text()
