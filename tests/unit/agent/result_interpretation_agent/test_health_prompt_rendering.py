"""Flag ON ⇒ the interpreter prompts carry exact structured gate evidence.

CB3-c suite (``pr3_healthgate_feedback.md`` §3.6, §7.1): block content
exactness, trajectory gate labels, legacy/disabled renderings, the
no-empty-header rule, and no cross-model contamination.
"""

from agent.schemas.interpretation import InterpretationInput
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from nodes.result_interpretation_agent.result_interpretation_agent import (
    HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS,
    _build_per_model_prompt,
    _build_per_model_system_prompt,
)
from tests.unit.agent.result_interpretation_agent.test_round_health_summary import (
    _gate_result,
    _output,
    _record,
)

SIG = "output_diversity_blocking:n_unique_int8_values=1"


def _collapse_output(model_type="wavenet"):
    return _output(
        _record(
            f"{model_type}_iter_001_001",
            model_type=model_type,
            status="failed_mode_collapse",
            denoising_score=None,
            gate_action="invalidate_round",
            failure_reason="[output_diversity_blocking] unique=1",
            health_gate_results=[_gate_result()],
        ),
        _record(f"{model_type}_iter_001_002", model_type=model_type, denoising_score=1.25),
    )


def _render(summary, *, on=True):
    return _build_per_model_prompt(summary, "A test architecture.", structured_health_feedback=on)


class TestTrajectoryLabels:
    def test_invalidated_round_labeled_with_action_and_signature(self):
        summary = tuning_output_to_model_run_summary(_collapse_output())
        prompt = _render(summary)
        assert f"Round 1: score=invalidated [GATE invalidate_round — {SIG}] —" in prompt
        # The healthy round keeps its plain form.
        assert "Round 2: score=1.2500 —" in prompt

    def test_flag_off_keeps_bare_skipped(self):
        summary = tuning_output_to_model_run_summary(_collapse_output())
        prompt = _render(summary, on=False)
        assert "score=skipped" in prompt
        assert "GATE" not in prompt
        assert "HealthGate summary" not in prompt

    def test_round_fields_only_uses_verbatim_failure_reason(self):
        """Mid-vintage record: no per-gate results → the verbatim round
        failure_reason is the label; nothing invented."""
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    "r1",
                    status="failed_mode_collapse",
                    denoising_score=None,
                    gate_action="invalidate_round",
                    failure_reason="[output_diversity_blocking] unique=1",
                )
            )
        )
        prompt = _render(summary)
        assert (
            "Round 1: score=invalidated "
            "[GATE invalidate_round — [output_diversity_blocking] unique=1]"
        ) in prompt


class TestHealthGateSummarySection:
    def test_counts_and_fingerprints_exact(self):
        summary = tuning_output_to_model_run_summary(_collapse_output())
        prompt = _render(summary)
        assert "### HealthGate summary" in prompt
        assert "Round validity: 0 valid, 1 invalid, 1 unknown (of 2)" in prompt
        assert f"- {SIG}  (x1, round 1)" in prompt

    def test_repeated_fingerprint_aggregates_rounds(self):
        summary = tuning_output_to_model_run_summary(
            _output(
                *[
                    _record(
                        f"r{i}",
                        status="failed_mode_collapse",
                        denoising_score=None,
                        gate_action="invalidate_round",
                        failure_reason="x",
                        health_gate_results=[_gate_result()],
                    )
                    for i in (1, 2)
                ]
            )
        )
        prompt = _render(summary)
        assert f"- {SIG}  (x2, rounds 1, 2)" in prompt

    def test_legacy_run_renders_no_empty_header(self):
        """All-legacy rounds with nothing informative: no HealthGate
        section at all (design: no empty headers)."""
        summary = tuning_output_to_model_run_summary(_output(_record("r1")))
        prompt = _render(summary)
        assert "### HealthGate summary" not in prompt

    def test_gates_disabled_counts_render_without_fingerprints(self):
        summary = tuning_output_to_model_run_summary(
            _output(_record("r1", health_gate_enabled=False))
        )
        prompt = _render(summary)
        assert "Round validity: 1 valid, 0 invalid, 0 unknown (of 1)" in prompt
        assert "Distinct collapse fingerprints" not in prompt

    def test_no_cross_model_contamination(self):
        """Two models rendered separately: model A's prompt never contains
        model B's evidence."""
        wavenet = tuning_output_to_model_run_summary(_collapse_output("wavenet"))
        punet_gate = _gate_result(
            name="amplitude_collapse_blocking",
            metric="dominant_mode_fraction",
            unit="fraction",
            worst=0.97,
        )
        punet = tuning_output_to_model_run_summary(
            _output(
                _record(
                    "punet_iter_001_001",
                    model_type="punet",
                    status="failed_mode_collapse",
                    denoising_score=None,
                    gate_action="invalidate_round",
                    failure_reason="y",
                    health_gate_results=[punet_gate],
                )
            )
        )
        wavenet_prompt = _render(wavenet)
        punet_prompt = _render(punet)
        assert SIG in wavenet_prompt and SIG not in punet_prompt
        assert "amplitude_collapse_blocking" in punet_prompt
        assert "amplitude_collapse_blocking" not in wavenet_prompt


class TestSystemPromptInstructions:
    def test_flag_on_appends_block(self):
        inp = InterpretationInput(
            model_types=["wavenet"],
            task_description="Denoise.",
            enable_structured_health_feedback=True,
        )
        rendered = _build_per_model_system_prompt(inp)
        assert rendered.endswith(HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS)
        assert "Preserve every collapse fingerprint VERBATIM" in rendered

    def test_flag_off_no_block(self):
        inp = InterpretationInput(model_types=["wavenet"], task_description="Denoise.")
        assert "HealthGate evidence" not in _build_per_model_system_prompt(inp)
