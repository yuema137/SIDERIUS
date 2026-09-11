"""V21 PR B3 Stage C — the operator-visible half of S3.

> After admission, realized threshold exceedance is recorded and surfaced
> as an operator-visible condition, but exceedance alone does not
> automatically terminate the phase, invalidate the scientific result, or
> alter the score.

Stage B armed the admission half. This is the other half, and its defining
property is what it must NOT do. Stage A rejected `RuntimeEstimate.warnings`
as the carrier — it is a pre-admission object — and chose
``final_record["memory"]``, where the other resource facts already live.

Design doc: ``docs/design/v21_priorities/pr_b_resource_budget_semantics.md``
§0.7 (Stage A) and Commit B3 Stage C.
"""

from __future__ import annotations

from core.runtime_control.realized_memory import (
    ThresholdExceedanceNotice,
    realized_vs_admitted,
    render_exceedance_notice,
    threshold_exceedance_notices,
)

_GB = 1024


class TestTheOperatorNotice:
    """S3's second half: recorded, surfaced, and inert."""

    @staticmethod
    def _row(realized_gb, threshold_gb=12.0, estimated_gb=8.0, completeness="complete"):
        return realized_vs_admitted(
            "training",
            resource_check={
                "estimated_gb": estimated_gb,
                "limit_gb": threshold_gb,
                "vram_budget_gb": threshold_gb,
            },
            runtime_verification={
                "components": {
                    "training": {
                        "realized_memory": {
                            "reserved_peak_mib": int(realized_gb * _GB),
                            "measurement_completeness": completeness,
                            "owning_process_pid": 4242,
                        }
                    }
                }
            },
        )

    def test_an_exceedance_produces_a_notice(self):
        rows = {"training": self._row(20.0)}
        notices = threshold_exceedance_notices(rows, model_identity="m", exp_id="e1")
        assert len(notices) == 1
        n = notices[0]
        assert n.realized_peak_mib == 20 * _GB
        assert n.effective_threshold_mib == 12 * _GB
        assert n.realized_minus_threshold_mib == 8 * _GB
        assert n.realized_minus_estimated_mib == 12 * _GB
        assert n.owning_process_pid == 4242

    def test_a_phase_within_the_threshold_is_silent(self):
        assert threshold_exceedance_notices({"training": self._row(8.0)}) == []

    def test_an_UNMEASURED_phase_is_silent_rather_than_reassuring(self):
        """`realized_above_threshold` is None, and `None is not True`.

        The failure this guards is subtle: a truthiness check would treat
        unknown as "not exceeded" and produce silence that reads as
        compliance. Silence here means *no claim*, and the row still
        records `unavailable` for anyone who looks.
        """
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            runtime_verification={},
        )
        assert row is not None and row.realized_above_threshold is None
        assert threshold_exceedance_notices({"training": row}) == []

    def test_the_notice_states_that_nothing_was_done(self):
        """S3 forbids automatic action; the artifact says so on its face."""
        n = threshold_exceedance_notices({"training": self._row(20.0)})[0]
        assert n.action_taken == "none_recorded_only"
        rendered = render_exceedance_notice(n)
        assert "ACTION" in rendered
        assert "not terminated" in rendered
        assert "score is unchanged" in rendered

    def test_a_lower_bound_is_presented_as_a_lower_bound(self):
        n = threshold_exceedance_notices({"training": self._row(20.0, completeness="lower_bound")})[
            0
        ]
        rendered = render_exceedance_notice(n)
        assert "LOWER BOUND" in rendered
        assert "at least" in rendered

    def test_the_training_HWM_limitation_is_stated_not_hidden(self):
        """The known limitation from B0.E must reach the operator.

        `reset_process_peak()` is deliberately uncalled, so a training
        figure includes setup and warm-up. Presenting it as a precise
        training-only peak would overstate the measurement.
        """
        n = threshold_exceedance_notices({"training": self._row(20.0)})[0]
        assert "UPPER BOUND on the training-only peak" in render_exceedance_notice(n)

    def test_attribution_is_stated_in_the_operator_text(self):
        rendered = render_exceedance_notice(
            threshold_exceedance_notices({"training": self._row(20.0)})[0]
        )
        assert "peer usage is never counted here" in rendered

    def test_the_notice_carries_no_policy_verdict_field(self):
        """Same guard B2 has, applied to the presentation layer.

        S3 chose the semantics, but the artifact still must not read as an
        automatic sanction — `action_taken` is a constant stating that
        nothing happened, not a decision.
        """
        forbidden = ("breach", "violation", "over_budget", "penalty", "reject", "kill", "abort")
        offenders = [
            f
            for f in ThresholdExceedanceNotice.model_fields
            for bad in forbidden
            if bad in f.lower()
        ]
        assert offenders == []

    def test_it_is_not_called_escalation(self):
        """The word already means TERM->KILL and escalate-to-verification.

        A third meaning would make all three ambiguous at exactly the
        moment an operator is reading urgently.
        """
        import core.runtime_control.realized_memory as rm

        assert "escalation" not in rm.__name__
        assert not any("escalat" in name.lower() for name in dir(rm))


class TestTheNoticeChangesNothing:
    """§8 — producing the surface must not alter any decision."""

    def test_no_decision_module_reads_the_notice(self):
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[3]
        for rel in (
            "src/core/runtime_control/decision_policy.py",
            "src/core/runtime_control/gpu_requirement.py",
            "src/core/runtime_control/total_assembly.py",
            "src/core/runtime_control/probe_lifecycle.py",
            "src/agent/skills/evaluate_vram_skill/wrapper.py",
        ):
            text = (repo / rel).read_text(encoding="utf-8")
            assert "threshold_exceedance_notice" not in text, (
                f"{rel} reads the operator notice — S3 requires it be observation only"
            )

    def test_the_tuner_builds_it_after_the_record_and_prints_it(self, capsys):
        """Reachability plus inertness, on the production boundary."""
        import nodes.ml_hyperparameter_tune_agent as tuner

        record: dict = {"model_type": "punet", "exp_id": "e42"}
        tuner._attach_realized_memory(
            record,
            {"estimated_gb": 8.0, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            {
                "components": {
                    "training": {
                        "realized_memory": {
                            "reserved_peak_mib": 20 * _GB,
                            "measurement_completeness": "complete",
                            "owning_process_pid": 7,
                        }
                    }
                }
            },
        )
        assert record["memory"]["threshold_exceedance_notices"][0]["phase"] == "training"
        assert record["memory"]["realized_vs_admitted"]["training"]["realized_above_threshold"]
        out = capsys.readouterr().out
        assert "[RESOURCE]" in out
        assert "punet" in out and "e42" in out

    def test_a_compliant_run_emits_no_notice_and_no_noise(self, capsys):
        import nodes.ml_hyperparameter_tune_agent as tuner

        record: dict = {"model_type": "punet", "exp_id": "e43"}
        tuner._attach_realized_memory(
            record,
            {"estimated_gb": 8.0, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            {
                "components": {
                    "training": {
                        "realized_memory": {
                            "reserved_peak_mib": 4 * _GB,
                            "measurement_completeness": "complete",
                        }
                    }
                }
            },
        )
        assert "threshold_exceedance_notices" not in record["memory"]
        assert "[RESOURCE]" not in capsys.readouterr().out
