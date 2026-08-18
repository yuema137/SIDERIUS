"""B-C3a — typed attribution, and the evidence it refuses to act without.

The V19 failure this exists to prevent: a CUDA OOM raised while a
neighbouring chain held the card was read as a statement about the
candidate, and the agent was told to shrink a model that was the right
size. So the bar for blaming a candidate is a completed counterfactual,
and everything short of it is `unknown`.

Every gate test asserts the *reason*, not only the outcome. `unknown` is
the module's fallback, so a test that checks the outcome alone passes
whenever anything at all goes wrong — including a bug unrelated to the
condition under test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.runtime_control.failure_attribution import (
    AttributionResult,
    attribute_gpu_failure,
    attribute_process_termination,
    extract_attempted_allocation_mib,
    looks_like_cuda_oom,
    may_recommend_resource_reduction,
)
from core.runtime_control.gpu_accounting import (
    DeviceBaselineSnapshot,
    DeviceIdentity,
    GpuAccountingSnapshot,
)
from core.runtime_control.gpu_observer import GpuEvidenceBundle, GpuObservationPolicy

SOURCE = Path(__file__).resolve().parents[3] / "core" / "runtime_control" / "failure_attribution.py"
DEV = DeviceIdentity(uuid="GPU-aaaa-0000", physical_index=0)
OTHER_DEV = DeviceIdentity(uuid="GPU-bbbb-1111", physical_index=1)
OOM = "CUDA out of memory. Tried to allocate 11.31 GiB (GPU 0; 31.75 GiB total capacity)"


def _snap(total=32000, used=30000, other=0, own=1000, unattr=0, dev=DEV, ok=True):
    if not ok:
        return GpuAccountingSnapshot(device=dev, telemetry_available=False)
    return GpuAccountingSnapshot(
        device=dev,
        telemetry_available=True,
        device_total_mib=total,
        device_used_mib=used,
        own_tree_mib=own,
        other_mib=other,
        other_process_count=1 if other else 0,
        per_pid_total_mib=own + other,
        unattributed_mib=unattr,
        accounting_skew_mib=unattr,
    )


def _baseline(dev=DEV, ok=True):
    if not ok:
        return DeviceBaselineSnapshot(device=dev, telemetry_available=False, sampled_at=1.0)
    return DeviceBaselineSnapshot(
        device=dev,
        telemetry_available=True,
        sampled_at=1.0,
        device_total_mib=32000,
        device_used_mib=0,
        device_free_mib=32000,
        processes=(),
        process_count=0,
    )


def _bundle(**over):
    base = dict(
        device=DEV,
        sampling_policy=GpuObservationPolicy(),
        baseline_before_spawn=_baseline(),
        observed_peak=_snap(),
        last_while_alive=_snap(),
        valid_sample_count=10,
        child_runtime_ms=10_000.0,
        last_valid_offset_ms=9_900.0,
    )
    base.update(over)
    return GpuEvidenceBundle(**base)


def _interval_bundle():
    """total=32000, used=30000, other=9000, unattributed=3000.

    current_free                     =  2000
    free_without_known_other         = 11000
    free_without_all_possible_other  = 14000
    """
    return _bundle(last_while_alive=_snap(total=32_000, used=30_000, other=9_000, unattr=3_000))


def _gpu(bundle, attempted, text=OOM):
    return attribute_gpu_failure(
        bundle=bundle, attempted_allocation_mib=attempted, failure_text=text
    )


class TestAllocationExtraction:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Tried to allocate 11.31 GiB", 11.31 * 1024),
            ("Tried to allocate 118.00 MiB", 118.0),
            ("Tried to allocate 314 MiB", 314.0),
            ("tried to allocate 512 KiB", 0.5),
        ],
    )
    def test_real_message_forms_parse(self, text, expected):
        assert extract_attempted_allocation_mib(text) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "text",
        [
            None,
            "",
            "CUDA out of memory.",
            "the job finished normally",
            "Tried to allocate 1,024 MiB",
            "Tried to allocate 8589934592 bytes",
        ],
    )
    def test_absent_or_unsupported_size_is_none_not_zero(self, text):
        """An unparsed size must never become 0, which would fit anywhere."""
        assert extract_attempted_allocation_mib(text) is None

    def test_the_decision_function_does_no_parsing(self):
        """The framework-specific parse must not reach the decision logic.

        Asserted structurally rather than by searching for one literal:
        an inlined `re.compile` under a different string would defeat a
        single-literal check.
        """
        tree = ast.parse(SOURCE.read_text())
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "attribute_gpu_failure"
        )
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "re" not in names
        assert "_TRIED_TO_ALLOCATE" not in names
        assert "_UNIT_TO_MIB" not in names

    def test_the_pattern_is_referenced_only_by_the_adapter(self):
        tree = ast.parse(SOURCE.read_text())
        users = {
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(isinstance(n, ast.Name) and n.id == "_TRIED_TO_ALLOCATE" for n in ast.walk(fn))
        }
        assert users == {"extract_attempted_allocation_mib"}


class TestCudaOomDetection:
    @pytest.mark.parametrize(
        "text",
        [
            OOM,
            "torch.OutOfMemoryError: CUDA out of memory.",
            "CUDA error: out of memory",
        ],
    )
    def test_device_oom_is_recognised(self, text):
        assert looks_like_cuda_oom(text) is True

    @pytest.mark.parametrize(
        "text",
        [None, "", "MemoryError", "Killed", "process exited with code 1"],
    )
    def test_host_and_bare_failures_are_not_device_oom(self, text):
        assert looks_like_cuda_oom(text) is False


class TestBundleNormalization:
    def test_a_serialized_bundle_is_revalidated_not_read_by_attribute(self):
        """`coverage_is_thin` is a property and is absent from model_dump.

        Reading it off the dumped dict with a fail-closed default would
        refuse every record-shaped bundle and look like healthy caution.
        Re-validation recomputes it, so a dumped bundle decides exactly
        as the live one does.
        """
        live = _bundle(last_while_alive=_snap(other=9000))
        dumped = live.model_dump(mode="json")
        assert "coverage_is_thin" not in dumped

        assert _gpu(dumped, 5000).attribution == "gpu_contention"
        assert _gpu(live, 5000).attribution == "gpu_contention"

    def test_a_thin_serialized_bundle_is_still_refused(self):
        """Re-validation must not launder a thin bundle into a verdict."""
        dumped = _bundle(valid_sample_count=1).model_dump(mode="json")
        r = _gpu(dumped, 20_000)
        assert r.attribution == "unknown"
        assert "thin" in r.reason

    def test_a_foreign_object_is_refused_by_type(self):
        r = _gpu(object(), 20_000)
        assert r.attribution == "unknown"
        assert "not GpuEvidenceBundle" in r.reason

    def test_a_malformed_mapping_is_refused_not_coerced(self):
        r = _gpu({"valid_sample_count": -5}, 20_000)
        assert r.attribution == "unknown"
        assert "did not validate" in r.reason


class TestEvidenceQualityGate:
    def test_thin_coverage_is_unknown(self):
        r = _gpu(_bundle(valid_sample_count=1), 20_000)
        assert r.attribution == "unknown"
        assert "thin" in r.reason

    def test_an_observer_that_raised_cannot_convict(self):
        r = _gpu(_bundle(observer_error="RuntimeError: boom"), 20_000)
        assert r.attribution == "unknown"
        assert "observer itself failed" in r.reason

    def test_an_observer_that_would_not_stop_cannot_convict(self):
        r = _gpu(_bundle(observer_join_timed_out=True), 20_000)
        assert r.attribution == "unknown"
        assert "join timeout" in r.reason

    def test_missing_baseline_is_unknown(self):
        r = _gpu(_bundle(baseline_before_spawn=None), 20_000)
        assert r.attribution == "unknown"
        assert "baseline" in r.reason

    def test_missing_observed_peak_is_unknown(self):
        r = _gpu(_bundle(observed_peak=None), 20_000)
        assert r.attribution == "unknown"
        # coverage_is_thin is defined to include a missing peak, so the
        # thin-coverage gate legitimately fires first.
        assert "thin" in r.reason

    def test_missing_last_while_alive_is_unknown(self):
        r = _gpu(_bundle(last_while_alive=None), 20_000)
        assert r.attribution == "unknown"
        assert "while the child was alive" in r.reason

    @pytest.mark.parametrize(
        "slot,label",
        [
            ("baseline_before_spawn", "baseline"),
            ("observed_peak", "peak"),
            ("last_while_alive", "last"),
        ],
    )
    def test_unavailable_telemetry_on_any_snapshot_is_unknown(self, slot, label):
        broken = _baseline(ok=False) if slot == "baseline_before_spawn" else _snap(ok=False)
        r = _gpu(_bundle(**{slot: broken}), 20_000)
        assert r.attribution == "unknown"
        assert f"telemetry was unavailable for the {label}" in r.reason

    def test_uuid_disagreement_between_snapshots_is_unknown(self):
        r = _gpu(_bundle(observed_peak=_snap(dev=OTHER_DEV)), 20_000)
        assert r.attribution == "unknown"
        assert "different devices" in r.reason

    def test_a_bundle_naming_a_device_its_snapshots_do_not_is_unknown(self):
        """The bundle's own device is part of the consistency check.

        Without it a bundle can declare one card while every sample
        describes another, and the verdict would be about the wrong GPU.
        """
        r = _gpu(_bundle(device=OTHER_DEV), 20_000)
        assert r.attribution == "unknown"
        assert "different devices" in r.reason

    def test_a_missing_policy_is_unknown_not_a_default_bound(self):
        """No recorded policy means freshness is unestablished.

        Falling back to a constant here would silently widen the bound
        on exactly the runs whose telemetry was already degraded.
        """
        r = _gpu(_bundle(sampling_policy=None), 20_000)
        assert r.attribution == "unknown"
        assert "no observation policy was recorded" in r.reason

    @pytest.mark.parametrize(
        "runtime,offset",
        [(None, 9_900.0), (10_000.0, None), (None, None)],
    )
    def test_unrecorded_timing_is_unknown_not_a_skipped_check(self, runtime, offset):
        """The observer leaves child_runtime_ms None when stop() never ran.

        That happens precisely when the phase died abnormally, so a
        skipped freshness check here would convict on the stalest
        bundles the system can produce.
        """
        r = _gpu(_bundle(child_runtime_ms=runtime, last_valid_offset_ms=offset), 20_000)
        assert r.attribution == "unknown"
        assert "freshness cannot be established" in r.reason

    def test_a_stale_last_sample_is_unknown(self):
        r = _gpu(_bundle(child_runtime_ms=60_000.0, last_valid_offset_ms=1_000.0), 20_000)
        assert r.attribution == "unknown"
        assert "freshness bound" in r.reason

    @pytest.mark.parametrize(
        "steady_ms,staleness_ms,stale",
        [(1000, 2_999.0, False), (1000, 3_001.0, True), (200, 599.0, False), (200, 601.0, True)],
    )
    def test_the_freshness_bound_is_three_steady_intervals(self, steady_ms, staleness_ms, stale):
        """Pins the derived bound itself, not merely that one exists.

        A silent fallback to a fixed millisecond constant would leave a
        single large-gap test passing while the bound changed.
        """
        r = _gpu(
            _bundle(
                sampling_policy=GpuObservationPolicy(steady_interval_ms=steady_ms),
                child_runtime_ms=100_000.0,
                last_valid_offset_ms=100_000.0 - staleness_ms,
            ),
            20_000,
        )
        assert (r.attribution == "unknown" and "freshness bound" in r.reason) is stale

    def test_no_bundle_at_all_is_unknown(self):
        r = _gpu(None, 20_000)
        assert r.attribution == "unknown"
        assert "no GPU evidence bundle" in r.reason

    def test_a_non_cuda_failure_is_unknown_even_with_perfect_coverage(self):
        r = _gpu(_bundle(), 20_000, text="MemoryError")
        assert r.attribution == "unknown"
        assert "credible CUDA" in r.reason

    def test_impossible_telemetry_is_unknown_not_negative_free_memory(self):
        """used > total yields negative free memory and would convict.

        A driver transient must not be able to manufacture the one
        verdict that carries authority.
        """
        r = _gpu(_bundle(last_while_alive=_snap(total=32_000, used=33_000)), 100)
        assert r.attribution == "unknown"
        assert "cannot" in r.reason
        assert r.evidence["device_used_mib"] == 33_000
        assert r.evidence["device_total_mib"] == 32_000

    def test_a_refusal_still_records_how_degraded_the_telemetry_was(self):
        r = _gpu(_bundle(valid_sample_count=1, failed_sample_count=7), 20_000)
        assert r.evidence["valid_sample_count"] == 1
        assert r.evidence["failed_sample_count"] == 7
        assert r.evidence["coverage_is_thin"] is True


class TestCounterfactualIntervals:
    """The four intervals, on the fixture built by `_interval_bundle`."""

    def test_a_missing_allocation_size_is_unknown(self):
        r = _gpu(_interval_bundle(), None)
        assert r.attribution == "unknown"
        assert "attempted allocation size" in r.reason

    def test_an_allocation_that_should_have_fitted_is_unknown(self):
        r = _gpu(_interval_bundle(), 1_000)
        assert r.attribution == "unknown"
        assert "should have fitted" in r.reason

    def test_fits_without_the_known_other_occupancy_is_contention(self):
        r = _gpu(_interval_bundle(), 5_000)
        assert r.attribution == "gpu_contention"
        assert r.evidence["free_without_known_other_mib"] == 11_000

    def test_the_unattributed_band_is_unknown_not_candidate_blame(self):
        """The verdict here depends on who owns the unattributed memory.

        12000 MiB does not fit in the 11000 attributable to others, but
        would fit in 14000 if the 3000 the driver could not attribute
        belonged to somebody else. Charging it to the candidate is the
        V19 mistake in a subtler form.
        """
        r = _gpu(_interval_bundle(), 12_000)
        assert r.attribution == "unknown"
        assert r.may_recommend_resource_reduction is False
        assert "could not attribute" in r.reason
        assert r.evidence["free_without_all_possible_other_mib"] == 14_000

    def test_does_not_fit_even_under_the_most_favourable_reading_is_candidate(self):
        r = _gpu(_interval_bundle(), 20_000)
        assert r.attribution == "candidate_gpu_capacity"
        assert r.may_recommend_resource_reduction is True
        assert r.evidence["free_without_all_possible_other_mib"] == 14_000

    def test_the_boundaries_are_inclusive_upward(self):
        """Exactly at a bound belongs to the more conservative side."""
        assert _gpu(_interval_bundle(), 2_000).attribution == "unknown"
        assert _gpu(_interval_bundle(), 11_000).attribution == "gpu_contention"
        assert _gpu(_interval_bundle(), 14_000).attribution == "unknown"
        assert _gpu(_interval_bundle(), 14_001).attribution == "candidate_gpu_capacity"

    def test_an_absent_unattributed_figure_cannot_convict(self):
        """Without it the candidate-favourable bound is unmeasurable."""
        snap = GpuAccountingSnapshot(
            device=DEV,
            telemetry_available=True,
            device_total_mib=32_000,
            device_used_mib=30_000,
            own_tree_mib=1_000,
            other_mib=9_000,
        )
        r = _gpu(_bundle(last_while_alive=snap), 20_000)
        assert r.attribution == "unknown"
        assert "unattributed" in r.reason

    def test_contention_does_not_need_the_unattributed_figure(self):
        """Fitting below the known bound implies fitting below the wider one."""
        snap = GpuAccountingSnapshot(
            device=DEV,
            telemetry_available=True,
            device_total_mib=32_000,
            device_used_mib=30_000,
            own_tree_mib=1_000,
            other_mib=9_000,
        )
        assert _gpu(_bundle(last_while_alive=snap), 5_000).attribution == "gpu_contention"

    def test_every_figure_is_preserved_with_its_value(self):
        r = _gpu(_interval_bundle(), 20_000)
        assert r.evidence["attempted_allocation_mib"] == 20_000
        assert r.evidence["device_total_mib"] == 32_000
        assert r.evidence["device_used_mib"] == 30_000
        assert r.evidence["other_mib"] == 9_000
        assert r.evidence["unattributed_mib"] == 3_000
        assert r.evidence["accounting_skew_mib"] == 3_000
        assert r.evidence["current_free_mib"] == 2_000
        assert r.evidence["free_without_known_other_mib"] == 11_000
        assert r.evidence["free_without_all_possible_other_mib"] == 14_000
        assert r.evidence["device_uuid"] == DEV.uuid
        assert r.evidence["freshness_bound_ms"] == 3_000

    def test_the_reason_states_the_arithmetic_it_used(self):
        r = _gpu(_interval_bundle(), 5_000)
        assert "5000 MiB" in r.reason
        assert "2000 MiB" in r.reason
        assert "11000 MiB" in r.reason


class TestV19ReconstructedFixture:
    """The V19 regression, reconstructed — not replayed.

    The historical records preserved free-memory context but never an
    attempted-allocation size, and no captured CUDA OOM stderr exists in
    this repository. The attempted figures below are therefore an
    explicit fixture assumption. These tests prove the frozen rule
    produces the right verdict on complete evidence; they do not prove
    the parser has been validated against real production stderr.
    """

    def test_the_contention_case_does_not_blame_the_candidate(self):
        # 125.94 MiB free of 31.34 GiB, a peer holding the card.
        snap = _snap(total=32_607, used=32_481, other=9_222, own=23_259)
        r = _gpu(_bundle(observed_peak=snap, last_while_alive=snap), 2_000)
        assert r.attribution == "gpu_contention"
        assert r.may_recommend_resource_reduction is False

    def test_the_genuine_case_does_blame_the_candidate(self):
        # 9.20 GiB free, nothing else on the card. Wired through the
        # adapter so an adapter/decision unit mismatch cannot hide.
        snap = _snap(total=32_607, used=23_187, other=0, own=23_187)
        attempted = extract_attempted_allocation_mib(OOM)
        assert attempted == pytest.approx(11.31 * 1024)
        r = _gpu(_bundle(observed_peak=snap, last_while_alive=snap), attempted)
        assert r.attribution == "candidate_gpu_capacity"
        assert r.may_recommend_resource_reduction is True

    def test_free_memory_alone_does_not_decide_it(self):
        """The same free figure, a small allocation: no verdict.

        "9.20 GiB free" is not by itself evidence about the candidate.
        """
        snap = _snap(total=32_607, used=23_187, other=0, own=23_187)
        r = _gpu(_bundle(observed_peak=snap, last_while_alive=snap), 100)
        assert r.attribution == "unknown"


class TestTerminationAttribution:
    def test_a_bare_signal_never_blames_the_candidate(self):
        r = attribute_process_termination(returncode=-9)
        assert r.attribution == "unknown"
        assert "indistinguishable by return code" in r.reason

    def test_corroborated_host_pressure(self):
        r = attribute_process_termination(returncode=-9, host_memory_evidence=True)
        assert r.attribution == "host_memory_pressure"

    def test_corroborated_external_termination(self):
        r = attribute_process_termination(returncode=-15, external_signal_evidence=True)
        assert r.attribution == "external_termination"

    def test_contradictory_evidence_is_unknown(self):
        r = attribute_process_termination(
            returncode=-9, host_memory_evidence=True, external_signal_evidence=True
        )
        assert r.attribution == "unknown"
        assert "explained two ways" in r.reason

    @pytest.mark.parametrize("returncode", [None, 0, 1, -9, -15, -6])
    def test_the_return_code_is_not_a_discriminator(self, returncode):
        """Corroboration decides; the signal only travels as evidence.

        Every other test here passes a signal that happens to agree with
        its verdict, so a future `if returncode == -9` branch would break
        none of them. This one would.
        """
        assert (
            attribute_process_termination(
                returncode=returncode, host_memory_evidence=True
            ).attribution
            == "host_memory_pressure"
        )
        assert (
            attribute_process_termination(
                returncode=returncode, external_signal_evidence=True
            ).attribution
            == "external_termination"
        )
        assert attribute_process_termination(returncode=returncode).attribution == "unknown"

    def test_the_return_code_is_still_recorded(self):
        assert attribute_process_termination(returncode=-9).evidence["returncode"] == -9


class TestAuthorityMapping:
    @pytest.mark.parametrize(
        "attribution,expected",
        [
            ("candidate_gpu_capacity", True),
            ("gpu_contention", False),
            ("host_memory_pressure", False),
            ("external_termination", False),
            ("unknown", False),
        ],
    )
    def test_exhaustive_authority_table(self, attribution, expected):
        assert may_recommend_resource_reduction(attribution) is expected
        r = AttributionResult(
            attribution=attribution,
            may_recommend_resource_reduction=expected,
            reason="fixture",
        )
        assert r.may_recommend_resource_reduction is expected

    @pytest.mark.parametrize(
        "attribution",
        ["gpu_contention", "host_memory_pressure", "external_termination", "unknown"],
    )
    def test_authority_cannot_be_forged(self, attribution):
        with pytest.raises(ValidationError):
            AttributionResult(
                attribution=attribution,
                may_recommend_resource_reduction=True,
                reason="fixture",
            )

    def test_the_capacity_outcome_cannot_disclaim_its_authority(self):
        with pytest.raises(ValidationError):
            AttributionResult(
                attribution="candidate_gpu_capacity",
                may_recommend_resource_reduction=False,
                reason="fixture",
            )

    def test_an_unrecognised_string_is_denied_authority(self):
        assert may_recommend_resource_reduction("candidate") is False


class TestGenericity:
    FORBIDDEN = ("tidmad", "denois", "segmentation_size", "batch_size", "model size")

    def test_no_task_vocabulary_anywhere_including_prose(self):
        """Identifiers, strings, docstrings and comments all count.

        An earlier version excluded docstrings, which made the guard
        blind to exactly the place task vocabulary tends to survive.
        """
        text = SOURCE.read_text().lower()
        assert [term for term in self.FORBIDDEN if term in text] == []

    def test_no_task_vocabulary_in_any_identifier_position(self):
        tree = ast.parse(SOURCE.read_text())
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.alias):
                names.add(node.asname or node.name)
            elif isinstance(node, ast.FunctionDef | ast.ClassDef):
                names.add(node.name)
        lowered = {n.lower() for n in names}
        assert [t for t in self.FORBIDDEN if any(t in n for n in lowered)] == []

    def test_it_imports_no_task_module(self):
        tree = ast.parse(SOURCE.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = ("nodes", "agent", "ml_models", "execute_tools", "dashboard", "scripts")
        assert [m for m in imported if m.split(".")[0] in forbidden] == []

    def test_every_numeric_constant_is_accounted_for(self):
        """An allowlist, because a denylist cannot see a new constant.

        The previous form listed seven forbidden floats that could never
        have appeared and was blind to integers — so it could not have
        seen a `* 2` safety factor or an `other_mib > 12000` ceiling. Any
        new number must be justified here or the guard fails.
        """
        allowed_ints = {1, 2, 3, 1024}
        allowed_floats = {1.0, 1024.0}
        tree = ast.parse(SOURCE.read_text())
        unexpected = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
                continue
            if isinstance(node.value, int) and node.value not in allowed_ints:
                unexpected.append(node.value)
            elif isinstance(node.value, float) and node.value not in allowed_floats:
                unexpected.append(node.value)
        assert unexpected == []
