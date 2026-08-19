"""P3-V1 closure audit tests — the four §7.1/§1.4 claims that had no
DIRECT assertion (pr3_healthgate_feedback.md §7.1; P3-V1 task §3.3).

Each test here closes a specific audit gap; none duplicates existing
coverage.
"""

import inspect
from pathlib import Path

from agent.schemas.health_feedback import (
    CollapseFingerprint,
    CollapseFingerprintHistoryEntry,
    FingerprintOccurrence,
    HealthFeedbackRetentionPolicy,
    merge_fingerprint_history,
)
from execute_tools.metric_order import MetricOrder
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _format_healthgate_evidence_block,
)
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import shipped_spec
from tests.helpers.tuner_source import tuner_node_source
from tests.unit.agent.result_interpretation_agent.test_round_health_summary import (
    _gate_result,
    _output,
    _record,
)

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())

REPO = Path(__file__).resolve().parents[4]
SIG = "output_diversity_blocking:n_unique_int8_values=1"


def _fp():
    return CollapseFingerprint(
        check_name="output_diversity_blocking",
        signature=SIG,
        metrics={"n_unique_int8_values": 1},
        human_readable="collapsed",
    )


def _entry(iteration, count=1):
    return CollapseFingerprintHistoryEntry(
        signature=SIG,
        check_name="output_diversity_blocking",
        metrics={"n_unique_int8_values": 1},
        human_readable="collapsed",
        occurrences=[FingerprintOccurrence(iteration=iteration, count=count)],
    )


class TestPolicyIsAlwaysAParameter:
    """§7.1: 'renderer consumes the RESOLVED policy (no module-level
    constant import)'. Structurally, renderers never need the policy —
    stored history is post-retention — so the enforceable form of the
    claim is: the MERGE (the only policy consumer) takes it as a
    REQUIRED parameter, and no renderer imports a retention constant."""

    def test_merge_policy_parameter_has_no_default(self):
        sig = inspect.signature(merge_fingerprint_history)
        assert sig.parameters["policy"].default is inspect.Parameter.empty

    def test_renderers_import_no_retention_constant(self):
        # Step 09a C1b: scan the whole node PACKAGE, not one file. The
        # interpreter's decomposition means a future retention constant could
        # be introduced in `evidence.py` / `ordering.py` / `prediction.py` and
        # the single-file scan would never see it — the guard would still be
        # green while the rule it protects was broken.
        renderers = [
            *sorted((REPO / "nodes/result_interpretation_agent").glob("*.py")),
            REPO / "nodes/ml_model_proposal_agent/ml_model_proposal_agent.py",
        ]
        assert len(renderers) >= 4, (
            "expected the interpreter package to contain its main module plus "
            f"the C1b private modules; found {[p.name for p in renderers]}"
        )
        for renderer in renderers:
            src = renderer.read_text()
            # A `... or True` assertion on the bare window name used to sit
            # here. It was neutered because the name may legitimately appear
            # in a comment, which left an assertion that could never fail --
            # a live false negative dressed as coverage. The two checks below
            # are the binding ones, and they were always the real content.
            assert "HealthFeedbackRetentionPolicy(" not in src, renderer
            assert "DEFAULT_HISTORY_WINDOW" not in src, renderer


class TestWindowedNotLifetimeEndToEnd:
    """§7.1: 'prompt-rendered counts equal the derived windowed values on
    a fixture whose lifetime totals differ'. Direct composition: a
    carried history whose LIFETIME total (4) differs from its windowed
    value (1) → merge → proposer block shows the windowed count only."""

    def test_out_of_window_bucket_never_reaches_the_prompt(self):
        prior = {
            "wavenet": [
                CollapseFingerprintHistoryEntry(
                    signature=SIG,
                    check_name="output_diversity_blocking",
                    metrics={"n_unique_int8_values": 1},
                    human_readable="collapsed",
                    occurrences=[
                        FingerprintOccurrence(iteration=1, count=3),  # expires
                        FingerprintOccurrence(iteration=5, count=1),  # retained
                    ],
                )
            ]
        }
        merged = merge_fingerprint_history(prior, {}, 5, HealthFeedbackRetentionPolicy())
        block = _format_healthgate_evidence_block(
            {
                "model_types": ["wavenet"],
                "collapse_fingerprint_history": {
                    m: [e.model_dump() for e in v] for m, v in merged.items()
                },
            }
        )
        assert f"- {SIG}: 1 occurrence(s) across iteration(s) 5" in block
        assert "4 occurrence" not in block  # the lifetime total never renders
        assert "iteration(s) 1" not in block


class TestIncidentalOrderInvariance:
    """Operator §1.4-C: reversing INCIDENTAL input order (model-dict
    insertion order) does not change results; only the approved
    chronological record order is meaningful."""

    def test_model_dict_insertion_order_is_irrelevant(self):
        policy = HealthFeedbackRetentionPolicy()
        prior_ab = {"a": [_entry(4)], "b": [_entry(5)]}
        prior_ba = {"b": [_entry(5)], "a": [_entry(4)]}
        current_ab = {"a": [(_fp(), "e1")], "b": [(_fp(), "e2")]}
        current_ba = {"b": [(_fp(), "e2")], "a": [(_fp(), "e1")]}
        assert merge_fingerprint_history(
            prior_ab, current_ab, 5, policy
        ) == merge_fingerprint_history(prior_ba, current_ba, 5, policy)


class TestTunerConsumptionSurface:
    """§7.1 'no production routing behavior changed': the tuner touches
    the flag EXACTLY at the lock call and the run_config stamp — no
    third reference means no behavioral consumption anywhere in its
    control flow."""

    def test_flag_referenced_exactly_twice_in_tuner(self):
        src = tuner_node_source()
        assert src.count("agent_input.enable_structured_health_feedback") == 2
        assert src.count("agent_input.health_feedback_history_window_iterations") == 2
        assert src.count("agent_input.health_feedback_history_max_entries_per_model") == 2


class TestBuilderAlignmentWithAttemptFailures:
    """§7.1 builder bullet, strengthened: alignment holds across a MIXED
    record stream (success / collapse / attempt-failure / skip) with
    round_ordering and round_health in lockstep."""

    def test_all_parallel_lists_aligned(self):
        summary = tuning_output_to_model_run_summary(
            _output(
                _record("r1", denoising_score=1.0),
                _record(
                    "r2",
                    status="failed_mode_collapse",
                    denoising_score=None,
                    gate_action="invalidate_round",
                    failure_reason="x",
                    health_gate_results=[_gate_result()],
                ),
                _record(
                    "r3",
                    record_type="attempt_failure",
                    status="error",
                    denoising_score=None,
                    counts_toward_completed_rounds=False,
                ),
                _record("r4", status="skipped_time_risk", denoising_score=None),
            ),
            order=_STEP09A_ORDER,
        )
        n = len(summary.round_scores)
        assert n == 4
        assert len(summary.round_health) == len(summary.round_ordering) == n
        assert [h.exp_id for h in summary.round_health] == ["r1", "r2", "r3", "r4"]
        assert [o.exp_id for o in summary.round_ordering] == ["r1", "r2", "r3", "r4"]
