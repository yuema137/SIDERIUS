"""Deterministic cold-start interpretation, without provider construction."""

from agent.prompt_templates.formal_failure import render_formal_failure_feedback
from agent.schemas.health_feedback import merge_fingerprint_history
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput, MetricIdentity


def build_cold_start_interpretation(inp: InterpretationInput) -> InterpretationOutput:
    """Carry native cold-start facts; optional analysis remains owned by the node."""
    if not inp.cold_start:
        raise ValueError("build_cold_start_interpretation requires explicit cold_start=True")
    return InterpretationOutput(
        model_types=[],
        model_descriptions={},
        total_experiments=0,
        key_findings=(
            [render_formal_failure_feedback(inp.recent_formal_validity)]
            if inp.recent_formal_validity
            else ["Cold start: no prior experimental runs or score history exist yet."]
        ),
        bottlenecks=[],
        take_home_message=(
            "No valid incumbent exists. Failed Formal evidence is provided in key_findings; "
            "use it to avoid repeating unsupported configurations. Do not claim improvement "
            "over an invalid result."
            if inp.recent_formal_validity
            else "This is a cold start — there is no prior experimental evidence. "
            "Propose the first experiment from the task description, the "
            "available model/loss registries (as options, not results), "
            "advice, and resource constraints. Do not claim improvement "
            "over prior runs; none exist."
        ),
        runtime_vocab=inp.runtime_vocab,
        # Step 10 / P5+P6 C2, DD-2 — carry the confirmation map through,
        # exactly as the degraded branch below does. Without this the
        # cold-start branch omits the field, the schema default `{}`
        # wins, and the workflow's loop closure (which reads the output
        # unconditionally) would CLOBBER a restored non-empty mapping.
        # Whether that state is reachable depends on a distant workflow
        # condition; making the three branches symmetric makes the
        # closure safe by LOCAL construction instead. Digest bytes are
        # unchanged for every pre-P5 caller, whose input is always `{}`.
        vocab_link_confirmations=dict(inp.vocab_link_confirmations),
        cold_start=True,
        metric_identity=(
            MetricIdentity(metric_id=inp.metric_spec.id, direction=inp.metric_spec.direction)
            if inp.metric_spec is not None
            else None
        ),
        # V19 PR 3 — the deterministic merge runs on every path
        # (a cold start has no summaries, so this is retention
        # applied to the carried history — normally empty).
        collapse_fingerprint_history=merge_fingerprint_history(
            inp.collapse_fingerprint_history,
            {},
            inp.iteration,
            inp.health_feedback_retention_policy(),
        ),
    )
