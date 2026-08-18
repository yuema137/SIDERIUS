"""Host-aware aggregate VRAM admission (operator decision 2026-07-31).

The failure this prevents is measured, not hypothetical: during C12 a
probe holding 31,266 MiB tripped this host's 30,000 MiB per-user quota
and a root watchdog SIGTERM'd it. The first component to notice was the
watchdog, and what it produced was a kill.

Unit handling gets the most attention here because it is where this
would silently go wrong: the watchdog and nvidia-smi say "MB" and mean
MiB, torch reports bytes, operators think in GiB. A factor-of-1000 slip
would make the guard read as passing while the host disagrees.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.runtime_control.pair_admission import (
    BYTES_PER_GIB,
    BYTES_PER_MIB,
    DEFAULT_PAIR_CEILING_GIB,
    HOST_VRAM_QUOTA_MIB_ENV,
    MIB_PER_GIB,
    PAIR_CEILING_GIB_ENV,
    PairAdmissionDecision,
    PairMember,
    bytes_from_gib,
    evaluate_configured_caps,
    evaluate_pair_admission,
    gib_from_bytes,
    gib_from_mib,
    host_quota_gib,
    mib_from_gib,
    pair_ceiling_gib,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test states its own deployment; none inherits the shell's."""
    monkeypatch.delenv(HOST_VRAM_QUOTA_MIB_ENV, raising=False)
    monkeypatch.delenv(PAIR_CEILING_GIB_ENV, raising=False)


def _member(name: str, gb: float) -> PairMember:
    return PairMember(run_name=name, predicted_peak_vram_gb=gb, provenance="test")


class TestUnitConversion:
    """1024-based, exact, and never inferred."""

    def test_the_constants_are_binary(self):
        assert BYTES_PER_MIB == 1_048_576
        assert BYTES_PER_GIB == 1_073_741_824
        assert MIB_PER_GIB == 1024

    def test_the_host_quota_is_not_30_gib(self):
        """The watchdog says '30000MB'. That is 29.2969 GiB, and treating
        it as 30 would hand back 0.7 GiB of headroom that does not exist."""
        assert gib_from_mib(30_000) == pytest.approx(29.296875)
        assert gib_from_mib(30_000) < 30.0

    def test_mib_and_gib_round_trip(self):
        for gib in (1.0, 16.0, 28.0, 31.34):
            assert gib_from_mib(mib_from_gib(gib)) == pytest.approx(gib)

    def test_bytes_and_gib_round_trip(self):
        for gib in (0.5, 18.115402698516846, 31.27):
            assert gib_from_bytes(bytes_from_gib(gib)) == pytest.approx(gib)

    def test_a_measured_torch_peak_converts_exactly(self):
        """transformer@5M's recorded peak, in the units torch reports."""
        assert gib_from_bytes(19_451_181_465) == pytest.approx(18.115, abs=1e-3)

    def test_the_c12_incident_numbers_reproduce(self):
        """31,266 MiB held against a 30,000 MiB quota — over by 1,266 MiB."""
        held, quota = gib_from_mib(31_266), gib_from_mib(30_000)
        assert held > quota
        assert mib_from_gib(held - quota) == pytest.approx(1266.0)


class TestCeilingResolution:
    def test_the_default_is_the_operator_value(self):
        assert DEFAULT_PAIR_CEILING_GIB == 28.0
        assert pair_ceiling_gib() == 28.0

    def test_an_undeclared_quota_is_unknown_not_unlimited(self):
        assert host_quota_gib() is None
        assert pair_ceiling_gib() == DEFAULT_PAIR_CEILING_GIB  # not raised

    def test_a_declared_quota_is_read_in_mib(self, monkeypatch):
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "30000")
        assert host_quota_gib() == pytest.approx(29.296875)

    def test_a_tighter_quota_wins_over_the_operator_ceiling(self, monkeypatch):
        """A ceiling above the enforced limit is no ceiling at all."""
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "20480")  # 20 GiB
        assert pair_ceiling_gib() == pytest.approx(20.0)

    def test_a_looser_quota_does_not_relax_the_operator_ceiling(self, monkeypatch):
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "81920")  # 80 GiB
        assert pair_ceiling_gib() == DEFAULT_PAIR_CEILING_GIB

    def test_the_ceiling_is_configurable(self, monkeypatch):
        monkeypatch.setenv(PAIR_CEILING_GIB_ENV, "24")
        assert pair_ceiling_gib() == 24.0

    @pytest.mark.parametrize("bad", ["", "not-a-number", "0", "-5"])
    def test_a_malformed_setting_falls_back_rather_than_crashing(self, monkeypatch, bad):
        monkeypatch.setenv(PAIR_CEILING_GIB_ENV, bad)
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, bad)
        assert pair_ceiling_gib() == DEFAULT_PAIR_CEILING_GIB
        assert host_quota_gib() is None


class TestPairDecision:
    def test_a_pair_that_fits_is_feasible(self):
        decision = evaluate_pair_admission([_member("arch", 10.0), _member("loss", 12.0)])
        assert decision.feasible is True
        assert decision.aggregate_gib == 22.0
        assert decision.headroom_gib == pytest.approx(6.0)

    def test_a_pair_that_does_not_fit_is_refused_before_launch(self):
        decision = evaluate_pair_admission([_member("arch", 16.0), _member("loss", 16.0)])
        assert decision.feasible is False
        assert decision.aggregate_gib == 32.0
        assert decision.headroom_gib == pytest.approx(-4.0)
        assert any("INFEASIBLE under the host quota" in r for r in decision.reasons)
        assert any("watchdog" in r for r in decision.reasons)

    def test_exactly_at_the_ceiling_is_allowed(self):
        decision = evaluate_pair_admission([_member("a", 14.0), _member("b", 14.0)])
        assert decision.feasible is True
        assert decision.headroom_gib == 0.0

    def test_one_gib_over_is_not(self):
        decision = evaluate_pair_admission([_member("a", 14.0), _member("b", 15.0)])
        assert decision.feasible is False

    def test_every_member_is_reported_with_its_provenance(self):
        decision = evaluate_pair_admission(
            [
                PairMember(run_name="arch", predicted_peak_vram_gb=3.4, provenance="probe"),
                PairMember(run_name="loss", predicted_peak_vram_gb=10.3, provenance="registry"),
            ]
        )
        joined = "\n".join(decision.reasons)
        assert "arch: 3.40 GiB (probe)" in joined
        assert "loss: 10.30 GiB (registry)" in joined

    def test_a_declared_quota_is_reported(self, monkeypatch):
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "30000")
        decision = evaluate_pair_admission([_member("a", 4.0)])
        assert decision.host_quota_gib == pytest.approx(29.296875)
        assert any("30000 MiB" in r for r in decision.reasons)

    def test_an_undeclared_quota_says_so_explicitly(self):
        decision = evaluate_pair_admission([_member("a", 4.0)])
        assert decision.host_quota_gib is None
        assert any("not the same as unlimited" in r for r in decision.reasons)

    def test_more_than_two_members_are_supported(self):
        decision = evaluate_pair_admission([_member(f"c{i}", 10.0) for i in range(3)])
        assert decision.aggregate_gib == 30.0
        assert decision.feasible is False

    def test_an_empty_set_is_an_error_not_a_pass(self):
        with pytest.raises(ValueError, match="at least one member"):
            evaluate_pair_admission([])


class TestDecisionIntegrity:
    """The record cannot claim something its own numbers contradict."""

    def test_headroom_must_follow_from_the_inputs(self):
        with pytest.raises(ValidationError):
            PairAdmissionDecision(
                feasible=True, aggregate_gib=10.0, ceiling_gib=28.0, headroom_gib=99.0
            )

    def test_feasible_must_follow_from_the_comparison(self):
        with pytest.raises(ValidationError):
            PairAdmissionDecision(
                feasible=True, aggregate_gib=40.0, ceiling_gib=28.0, headroom_gib=-12.0
            )


class TestConfiguredCaps:
    """The pre-launch question: can this CONFIGURATION exceed the ceiling?"""

    def test_the_configured_v19_and_c14_pair_fits(self):
        """12 GiB per chain (operator 2026-07-31): 24 GiB together, below
        both the 28 GiB ceiling and this host's 29.30 GiB quota, so a
        pair at cap cannot trip the host watchdog."""
        decision = evaluate_configured_caps(
            {"v19_gate_arch_15_19": 12.0, "v19_gate_loss_15_19": 12.0}
        )
        assert decision.feasible is True
        assert decision.aggregate_gib == 24.0
        assert decision.headroom_gib == pytest.approx(4.0)

    def test_the_superseded_16_plus_16_would_not_have_fit(self):
        """Why the cap moved: the earlier posture could reach 32 GiB."""
        decision = evaluate_configured_caps({"arch": 16.0, "loss": 16.0})
        assert decision.feasible is False
        assert decision.aggregate_gib == 32.0

    def test_fourteen_each_is_the_largest_symmetric_pair_that_fits(self):
        assert evaluate_configured_caps({"a": 14.0, "b": 14.0}).feasible is True
        assert evaluate_configured_caps({"a": 14.5, "b": 14.5}).feasible is False

    def test_a_cap_is_labelled_as_a_cap_not_a_measurement(self):
        decision = evaluate_configured_caps({"a": 8.0})
        assert "not a measurement" in decision.members[0].provenance

    def test_members_are_ordered_deterministically(self):
        first = evaluate_configured_caps({"z": 1.0, "a": 2.0})
        second = evaluate_configured_caps({"a": 2.0, "z": 1.0})
        assert [m.run_name for m in first.members] == ["a", "z"]
        assert first.model_dump() == second.model_dump()
