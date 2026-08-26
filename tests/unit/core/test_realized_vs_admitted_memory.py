"""V21 PR B2 — realized memory is measured, recorded, and decides nothing.

Three properties, each failing for a different reason:

1. **The facts are semantics-neutral.** Q-B-1 is unfrozen until B0, so the
   stored row must be readable as S1 (forecast error), S2 (cap violation)
   or S3 (recorded breach) without the schema having picked one. A stored
   ``budget_breach`` would already have chosen.
2. **Missing evidence stays missing.** An unavailable peak must never
   become "within threshold" — inferring compliance from silence is how a
   silent regression comes to look exactly like a healthy run.
3. **Nothing decides on it.** If any admission path started reading the
   observation, B2 would have become B3 without the operator's decision.

Design doc: ``docs/design/v21_priorities/pr_b_resource_budget_semantics.md``
§0.7 and Commit B2.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from core.runtime_control.realized_memory import (
    RealizedVsAdmittedMemory,
    realized_vs_admitted,
)
from core.runtime_control.records import PhaseComponentRecord, RealizedPhaseMemory
from tests.helpers.tuner_source import tuner_node_source

_GB = 1024


def _rv(phase="training", **realized):
    return {"components": {phase: {"realized_memory": realized}}} if realized else {}


def _admitted(estimated_gb=8.0, limit_gb=12.0, budget_gb=12.0):
    return {"estimated_gb": estimated_gb, "limit_gb": limit_gb, "vram_budget_gb": budget_gb}


class TestTheTwoDeltasStaySeparate:
    """``realized - estimated`` and ``realized - threshold`` answer different
    questions and must not be collapsed.

    Forecast error says "the prediction was wrong". Headroom consumed says
    "the budget was tight". They diverge exactly when the physical cap
    rather than the operator budget was binding, which is the distinction
    B0 needs in order to choose between S1 and S2 at all.
    """

    def test_both_deltas_are_recorded_and_differ(self):
        row = realized_vs_admitted(
            "training",
            resource_check=_admitted(estimated_gb=8.0, limit_gb=12.0),
            runtime_verification=_rv(
                reserved_peak_mib=20 * _GB,
                allocator_peak_mib=18 * _GB,
                measurement_completeness="complete",
                owning_process_pid=4242,
            ),
        )
        assert row is not None
        assert row.realized_minus_estimated_mib == (20 - 8) * _GB  # forecast error
        assert row.realized_minus_threshold_mib == (20 - 12) * _GB  # headroom consumed
        assert row.realized_minus_estimated_mib != row.realized_minus_threshold_mib

    def test_a_delta_is_none_when_its_operand_is_unknown(self):
        """A delta against a missing operand would be a fabricated number
        wearing the same field name as a measured one."""
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": None, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            runtime_verification=_rv(
                reserved_peak_mib=20 * _GB, measurement_completeness="complete"
            ),
        )
        assert row is not None
        assert row.realized_minus_estimated_mib is None
        assert row.realized_minus_threshold_mib == (20 - 12) * _GB


class TestMissingEvidenceStaysMissing:
    def test_an_unavailable_peak_is_unknown_not_within_threshold(self):
        row = realized_vs_admitted("training", resource_check=_admitted(), runtime_verification={})
        assert row is not None
        assert row.realized_peak_mib is None
        assert row.realized_above_threshold is None, (
            "None means unknown. False would assert compliance from an absence "
            "of data, which is the exact failure mode B2 exists to prevent."
        )
        assert row.measurement_completeness == "unavailable"

    def test_the_schema_refuses_to_claim_compliance_without_a_measurement(self):
        """Structural, not merely conventional: the model rejects the pair."""
        with pytest.raises(ValidationError):
            RealizedVsAdmittedMemory(
                phase="training",
                effective_admission_threshold_mib=12 * _GB,
                realized_peak_mib=None,
                realized_above_threshold=False,
            )

    def test_a_completeness_claim_must_be_backed_by_a_number(self):
        with pytest.raises(ValidationError):
            RealizedPhaseMemory(measurement_completeness="complete")
        with pytest.raises(ValidationError):
            RealizedPhaseMemory(measurement_completeness="unavailable", allocator_peak_mib=100)

    def test_a_lower_bound_is_preserved_as_a_lower_bound(self):
        """A process that died mid-phase has a floor, not a peak.

        Rounding that up into a precise realized peak would manufacture
        evidence about a run that never finished.
        """
        row = realized_vs_admitted(
            "training",
            resource_check=_admitted(),
            runtime_verification=_rv(
                allocator_peak_mib=19 * _GB, measurement_completeness="lower_bound"
            ),
        )
        assert row is not None
        assert row.measurement_completeness == "lower_bound"
        assert row.realized_peak_source == "allocator"

    def test_no_budget_configured_is_not_an_error(self):
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 20.0, "vram_budget_gb": None},
            runtime_verification=_rv(
                reserved_peak_mib=9 * _GB, measurement_completeness="complete"
            ),
        )
        assert row is not None
        assert row.operator_budget_mib is None
        assert row.realized_above_threshold is False  # measured, and genuinely below

    def test_nothing_at_all_returns_none(self):
        assert (
            realized_vs_admitted("training", resource_check=None, runtime_verification=None) is None
        )


class TestBindingConstraint:
    """Which cap set the threshold — the fact the deltas cannot express."""

    def test_the_operator_budget_binds_when_it_is_lower(self):
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 12.0, "vram_budget_gb": 12.0},
            runtime_verification=_rv(
                reserved_peak_mib=9 * _GB, measurement_completeness="complete"
            ),
            physical_cap_gb=25.0,
        )
        assert row is not None and row.binding_constraint == "operator_budget"

    def test_the_physical_cap_binds_when_the_budget_exceeds_it(self):
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 25.0, "vram_budget_gb": 40.0},
            runtime_verification=_rv(
                reserved_peak_mib=9 * _GB, measurement_completeness="complete"
            ),
            physical_cap_gb=25.0,
        )
        assert row is not None and row.binding_constraint == "physical_cap"

    def test_no_budget_means_the_physical_cap_binds(self):
        row = realized_vs_admitted(
            "training",
            resource_check={"estimated_gb": 8.0, "limit_gb": 25.0, "vram_budget_gb": None},
            runtime_verification=_rv(
                reserved_peak_mib=9 * _GB, measurement_completeness="complete"
            ),
            physical_cap_gb=25.0,
        )
        assert row is not None and row.binding_constraint == "physical_cap"


class TestAttribution:
    """A peer's usage is never this candidate's.

    The mechanism is structural rather than a filter: the counters are
    read with ``torch.cuda.max_memory_allocated`` **inside the phase's own
    subprocess**, and those are per-process, so another process on the
    same card cannot inflate them. The PID is recorded to make that
    checkable after the fact.
    """

    def test_the_owning_pid_travels_with_the_measurement(self):
        row = realized_vs_admitted(
            "training",
            resource_check=_admitted(),
            runtime_verification=_rv(
                reserved_peak_mib=9 * _GB,
                measurement_completeness="complete",
                owning_process_pid=31337,
            ),
        )
        assert row is not None and row.owning_process_pid == 31337

    def test_the_session_stamps_its_own_pid(self, tmp_path):
        """Reachability for attribution: the recorder cannot be handed
        someone else's PID, because it never accepts one."""
        import inspect
        import os

        from core.runtime_control.session import RuntimeVerificationSession

        assert (
            "pid"
            not in inspect.signature(RuntimeVerificationSession.record_phase_peak_memory).parameters
        )

        session = RuntimeVerificationSession(str(tmp_path / "rv.json"), attempt_id="b2")
        session.record_phase_peak_memory(
            "training",
            allocator_peak_mib=100,
            reserved_peak_mib=200,
            completeness="complete",
        )
        rec = session.observation.components["training"].realized_memory
        assert rec is not None and rec.owning_process_pid == os.getpid()


class TestNoPolicyTermInTheSchema:
    """Q-B-1 is unfrozen; the primitive fact must not presume its answer."""

    _FORBIDDEN = (
        "breach",
        "violation",
        "over_budget",
        "overbudget",
        "exceeded_budget",
        "illegal",
        "forbidden",
        "penalty",
        "reject",
    )

    @pytest.mark.parametrize("model", [RealizedVsAdmittedMemory, RealizedPhaseMemory])
    def test_no_field_name_encodes_a_verdict(self, model):
        offenders = [
            name for name in model.model_fields for bad in self._FORBIDDEN if bad in name.lower()
        ]
        assert offenders == [], (
            f"{model.__name__} has policy-flavoured field(s) {offenders}. B2 records "
            "measured facts; naming one after a verdict freezes Q-B-1 by accident. "
            "`realized_above_threshold` is a comparison and is the intended form."
        )

    def test_all_three_semantics_remain_expressible_from_one_row(self):
        """The row must support S1, S2 and S3 readings without change."""
        row = realized_vs_admitted(
            "training",
            resource_check=_admitted(estimated_gb=8.0, limit_gb=12.0),
            runtime_verification=_rv(
                reserved_peak_mib=20 * _GB, measurement_completeness="complete"
            ),
        )
        assert row is not None
        # S1 — forecast error
        assert row.realized_minus_estimated_mib == 12 * _GB
        # S2 — would the cap have been violated
        assert row.realized_above_threshold is True
        # S3 — magnitude of the exceedance, for escalation
        assert row.realized_minus_threshold_mib == 8 * _GB


class TestObservationOnly:
    def test_no_admission_or_refusal_path_reads_the_new_field(self):
        """B2 must not have become B3.

        Source-level because the property is an ABSENCE, which no
        execution can demonstrate. Scoped to the decision-bearing modules
        rather than the whole tree, so it states something specific: the
        admission machinery does not consult realized memory.

        ``session.py`` is deliberately NOT in this list — it is the
        *producer*, so the name must appear there. Its neighbouring test
        below covers the property that matters for it: the recorder
        derives nothing and no admission method branches on it.
        """
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[3]
        decision_sites = [
            repo / "core/runtime_control/decision_policy.py",
            repo / "core/runtime_control/gpu_requirement.py",
            repo / "core/runtime_control/total_assembly.py",
            repo / "agent/skills/evaluate_vram_skill/wrapper.py",
        ]
        checked = 0
        for path in decision_sites:
            if not path.exists():
                continue
            checked += 1
            assert "realized_memory" not in path.read_text(encoding="utf-8"), (
                f"{path.name} references realized_memory. B2 is observation only — "
                "a decision path reading it makes it B3, which needs the operator's "
                "frozen semantics first (Q-B-1)."
            )
        assert checked >= 3, "the decision-site list went stale; this test stopped checking"

    def test_the_admission_decision_does_not_consult_realized_memory(self):
        """The producer module's own guard.

        ``decide_admission`` and ``assess_total`` are the two methods that
        can refuse work. Neither may read the field the same class writes.
        """
        import inspect

        from core.runtime_control.session import RuntimeVerificationSession

        for method in ("decide_admission", "assess_total", "complete_setup"):
            src = inspect.getsource(getattr(RuntimeVerificationSession, method))
            assert "realized_memory" not in src, (
                f"RuntimeVerificationSession.{method} reads realized_memory — "
                "that turns an observation into an admission input."
            )

    def test_the_tuner_attaches_it_on_the_record_emission_path(self):
        """Reachability, not existence — PR A's and PR C's repeated lesson.

        A helper that works but is never called persists nothing. This
        drives the extracted boundary and then confirms the production
        emission path calls it, so removing either half fails.
        """
        import inspect

        import nodes.ml_hyperparameter_tune_agent as tuner

        # 1. the boundary does the work
        record: dict = {}
        tuner._attach_realized_memory(
            record,
            _admitted(),
            _rv(reserved_peak_mib=20 * _GB, measurement_completeness="complete"),
        )
        rows = record["memory"]["realized_vs_admitted"]
        assert rows["training"]["realized_peak_mib"] == 20 * _GB
        assert rows["training"]["realized_above_threshold"] is True

        # 2. production calls it, immediately before the record is emitted
        src = tuner_node_source()
        assert src.count("_attach_realized_memory(") >= 2, (
            "expected the definition plus at least one production call site; "
            "the observation is only worth anything if the emission path runs it"
        )
        # V21 PR E appended candidate_id= to the call; anchor on the stable
        # prefix so the guarded property (attach BEFORE emit) stays pinned
        # without re-encoding unrelated kwargs.
        # `_emit_record` is reached through its owning module since C7d, so the
        # call may be spelled `_records._emit_record(...)` and the formatter
        # wraps its arguments. The anchor is the emission of the final record —
        # neither the module path in front of it nor the line breaks inside it.
        # Both emission spellings (arXiv structural-budget closure): the
        # direct call, or the identity-threading helper the node's ONE
        # emission idiom now uses.
        emit_match = re.search(
            r"(?:_records\.)?_emit(?:_attempt)?_record\(\s*sandbox,\s*final_record", src
        )
        assert emit_match, "the final record is no longer emitted"
        emit_index = emit_match.start()
        preceding = src[max(0, emit_index - 400) : emit_index]
        assert "_attach_realized_memory(" in preceding, (
            "the attach call is not adjacent to the record emission — a future "
            "edit may have moved the emission past it, which would persist a "
            "record with no realized-memory row"
        )

    def test_both_phase_subprocesses_record_their_own_peak(self):
        """The producer end of the transport contract.

        Source-level, and honest about what that means: it proves the call
        EXISTS in each subprocess entry point, not that a real GPU run
        reaches it. The layer below — the sidecar round-trip test — proves
        the value survives once recorded, and the tuner test proves the
        parent consumes it. What no unit test can cover is a real CUDA
        read, which is why `read_process_peak_mib` returns None rather
        than raising when there is no device.

        Fails if: either phase stops recording, which would leave that
        phase permanently 'unavailable' while the other looked healthy —
        the asymmetry §0.7 warned against assuming away.
        """
        import inspect

        from execute_tools import inference_single, train_engine_sandbox

        for module, phase in (
            (train_engine_sandbox, "training"),
            (inference_single, "inference"),
        ):
            src = inspect.getsource(module)
            assert "record_phase_peak_memory(" in src, (
                f"{module.__name__} never records a realized peak; the {phase} "
                "phase would be permanently unmeasured"
            )
            assert f'"{phase}"' in src.split("record_phase_peak_memory(")[1][:80], (
                f"{module.__name__} records a peak against the wrong phase key"
            )
            assert "read_process_peak_mib" in src

    def test_an_absent_cuda_device_yields_unavailable_not_zero(self):
        """A failed read is missing evidence, not a measured 0 MiB.

        0 MiB is a much stronger claim than 'we could not look', and it
        would flow into the deltas as a real number.
        """
        from core.runtime_control.realized_memory import read_process_peak_mib

        allocator, reserved, device = read_process_peak_mib()
        if allocator is None:  # no CUDA here — the interesting case
            assert (allocator, reserved, device) == (None, None, None)
        else:  # CUDA present: values must be non-negative ints, not None
            assert allocator >= 0 and reserved is not None and reserved >= 0

    def test_a_failure_inside_the_boundary_cannot_break_the_attempt_loop(self):
        """Evidence collection must never take the run down with it."""
        import nodes.ml_hyperparameter_tune_agent as tuner

        record: dict = {}
        tuner._attach_realized_memory(record, {"estimated_gb": object()}, {"components": 7})
        assert "realized_vs_admitted" not in record.get("memory", {})

    def test_the_measurement_survives_the_sidecar_round_trip(self, tmp_path):
        """The transport hop, end to end and on disk.

        subprocess session -> atomic sidecar JSON -> parent read ->
        joined row. This is the hop that a schema test alone cannot cover,
        and the one the V20 post-mortems say to test: a field that exists
        on both ends but does not survive the middle.
        """
        import json

        from core.runtime_control.session import RuntimeVerificationSession

        sidecar = tmp_path / "rv.json"
        session = RuntimeVerificationSession(str(sidecar), attempt_id="b2_roundtrip")
        session.record_phase_peak_memory(
            "training",
            allocator_peak_mib=18 * _GB,
            reserved_peak_mib=20 * _GB,
            completeness="complete",
            device_index=0,
        )

        # Read the file, exactly as sandbox_executor does.
        on_disk = json.loads(sidecar.read_text(encoding="utf-8"))
        row = realized_vs_admitted(
            "training",
            resource_check=_admitted(estimated_gb=8.0, limit_gb=12.0),
            runtime_verification=on_disk,
        )
        assert row is not None
        assert row.realized_peak_mib == 20 * _GB
        assert row.realized_peak_source == "reserved"
        assert row.realized_minus_estimated_mib == 12 * _GB
        assert row.measurement_completeness == "complete"

    def test_the_phase_record_carries_it_without_deriving_anything(self):
        """``with_realized_memory`` mirrors ``with_actual`` but derives no
        error, because the memory forecast lives in the parent, not here."""
        rec = PhaseComponentRecord().with_realized_memory(
            RealizedPhaseMemory(allocator_peak_mib=10, measurement_completeness="complete")
        )
        assert rec.realized_memory is not None
        assert rec.prediction_error is None
        assert rec.actual_seconds is None
