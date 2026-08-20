"""Flag OFF ⇒ interpreter prompts byte-identical to the pre-PR3 goldens.

The §3.1 parity claim (``pr3_healthgate_feedback.md``): with
``enable_structured_health_feedback`` OFF, agent-facing prompts remain
byte-identical to the pre-PR3 condition — even when ``round_health``
data is present on the summary. The goldens under ``goldens/`` were
captured from the PRE-rendering-change code at commit ``f3a0b8c``
(clean tree), so equality here is against true pre-change output, not a
re-derivation.

Parity is proven by exact string equality, not by absence of diffs in
the renderer (design §11-CB3 acceptance criteria).
"""

from pathlib import Path

from agent.prompt_templates.interpretation.rendering import (
    _build_per_model_prompt,
    _build_per_model_system_prompt,
)
from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.schemas.interpretation import InterpretationInput
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import shipped_spec
from tests.unit.agent.result_interpretation_agent.test_round_health_summary import (
    _gate_result,
    _output,
    _record,
)

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())

GOLDENS = Path(__file__).parent / "goldens"


def _summary_collapse():
    """Same fixture the golden-capture script used — collapse-heavy run
    WITH round_health populated."""
    return tuning_output_to_model_run_summary(
        _output(
            _record(
                "m_iter_001_001",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="[output_diversity_blocking] unique=1",
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


def test_per_model_system_prompt_parity():
    """Step 09b C2 SUPERSEDES the pre-PR3 provenance for THIS golden only:
    the system prompt's science moved into TIDMAD's task blocks, so
    ``per_model_system_prompt.txt`` now pins the CURRENT assembled bytes
    (framework template + TIDMAD blocks; regenerated at C2 with the delta
    declared in the 09b design §22.2). The USER-prompt parity tests above
    keep their original pre-PR3 capture claim untouched."""
    inp = InterpretationInput(
        model_types=["wavenet"],
        task_description="Denoise SQUID data.",
        task_blocks=load_interpretation_task_blocks(),
    )
    rendered = _build_per_model_system_prompt(inp)
    assert rendered == (GOLDENS / "per_model_system_prompt.txt").read_text()
