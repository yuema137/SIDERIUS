"""F-SCANG-3 — the RSS refusal contract, extended to its three env siblings.

``SIDERIUS_SUBPROCESS_RSS_GB`` refuses a malformed value loudly
(``MalformedCeilingOverride``, Step 11 C3 / R-11-5). Its three sibling
overrides used to swallow the same class of typo in silence:

* ``SIDERIUS_GPU_VRAM_QUOTA_MIB``   -> quota silently "undeclared"
* ``SIDERIUS_PAIR_VRAM_CEILING_GIB`` -> arm silently capped at the
  28-GiB 5090 default — the named incident shape: no log line, no lock
  entry, no preflight row
* ``SIDERIUS_GPU_VRAM_QUOTA_GB``    -> probe attribution silently at the
  device-fraction bound

This family is the ONLY guard for that defect: Pydantic never sees these
values (they are read straight from ``os.environ`` inside plain
functions), pyright cannot know ``"7O2"`` is a typo, and no Gate compares
a resolved ceiling against the operator's intent. Every expected number
below is HARDCODED — asserting a value read back from the thing under
test would compare the function to itself.

Deliberate divergence from the RSS variable, preserved on purpose: an
EMPTY string still behaves as unset in all three siblings (the
shell-wrapper pass-through pattern ``VAR="${VAR:-}"``), where the RSS
variable refuses "". The repaired class is silently-consumed TYPOS, and
"" is not a typo'd number.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from core.execution_calibration import MalformedCeilingOverride
from core.runtime_control.pair_admission import (
    HOST_VRAM_QUOTA_MIB_ENV,
    PAIR_CEILING_GIB_ENV,
    host_quota_gib,
    pair_ceiling_gib,
)
from core.runtime_control.probe_subprocess import (
    VRAM_QUOTA_ENV,
    vram_attribution_threshold_gb,
)

#: 32.0 is a power of two, so 0.90 * 32.0 == 28.8 EXACTLY (scaling a
#: double by 2**5 shifts the exponent without rounding). The probe
#: expectations below rely on that to stay exact-equality assertions.
_PROBE_DEVICE_GB = 32.0
_PROBE_FRACTION_BOUND = 28.8

#: (env var, resolver with everything else unset, expected unset result).
#: One row per sibling so every parametrized case names its variable.
SIBLINGS: list[tuple[str, Callable[[], float | None], float | None]] = [
    (HOST_VRAM_QUOTA_MIB_ENV, host_quota_gib, None),
    (PAIR_CEILING_GIB_ENV, lambda: pair_ceiling_gib(measured_capacity_gib=96), 96),
    (
        VRAM_QUOTA_ENV,
        lambda: vram_attribution_threshold_gb(_PROBE_DEVICE_GB),
        _PROBE_FRACTION_BOUND,
    ),
]

_SIBLING_IDS = ["host_quota_mib", "pair_ceiling_gib", "probe_vram_quota_gb"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test states its own deployment; none inherits the shell's."""
    monkeypatch.delenv(HOST_VRAM_QUOTA_MIB_ENV, raising=False)
    monkeypatch.delenv(PAIR_CEILING_GIB_ENV, raising=False)
    monkeypatch.delenv(VRAM_QUOTA_ENV, raising=False)


class TestMalformedValuesRefuse:
    """A set-but-unusable override is a refusal, never a silent default."""

    @pytest.mark.parametrize(("env_var", "resolve", "_unset"), SIBLINGS, ids=_SIBLING_IDS)
    @pytest.mark.parametrize("bad", ["4O", "28..0", "abc"])
    def test_a_typo_raises_and_names_the_variable(self, monkeypatch, env_var, resolve, _unset, bad):
        """F-SCANG-3. Only-catchable defect: a typo'd override silently
        consumed as a DIFFERENT number — for the pair ceiling, an arm
        capped at the 28-GiB 5090 default with no log/lock/preflight row.
        Fails when broken: remove the refusal and nothing raises, so
        ``pytest.raises`` fails on the silent fallback value."""
        monkeypatch.setenv(env_var, bad)
        with pytest.raises(MalformedCeilingOverride) as exc:
            resolve()
        assert env_var in str(exc.value)
        assert repr(bad) in str(exc.value)

    @pytest.mark.parametrize(("env_var", "resolve", "_unset"), SIBLINGS, ids=_SIBLING_IDS)
    @pytest.mark.parametrize("bad", ["0", "-5"])
    def test_zero_and_negative_raise_with_no_0_disables_semantics(
        self, monkeypatch, env_var, resolve, _unset, bad
    ):
        """F-SCANG-3. Only-catchable defect: ``0`` copied over from the
        RSS variable's disable idiom (or a negative value) silently
        resolving to a default the operator never chose — these three
        variables have NO 0-disables semantics, unlike
        ``SIDERIUS_SUBPROCESS_RSS_GB``. Fails when broken: the refusal
        removed -> the resolver returns the unset default and
        ``pytest.raises`` fails."""
        monkeypatch.setenv(env_var, bad)
        with pytest.raises(MalformedCeilingOverride) as exc:
            resolve()
        assert env_var in str(exc.value)
        assert "0-disables" in str(exc.value)

    def test_pair_ceiling_refuses_transitively_on_a_malformed_quota(self, monkeypatch):
        """F-SCANG-3. Only-catchable defect: ``pair_ceiling_gib`` growing
        a try/except around its ``host_quota_gib()`` call, which would
        turn the quota refusal back into a silent "undeclared" one hop
        up. Fails when broken: the wrap added -> nothing raises ->
        ``pytest.raises`` fails on 28.0."""
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "3O000")
        with pytest.raises(MalformedCeilingOverride) as exc:
            pair_ceiling_gib()
        assert HOST_VRAM_QUOTA_MIB_ENV in str(exc.value)


class TestValidValuesAreConsumed:
    """Declared-but-unconsumed is the refusal's mirror defect: a guard
    that rejects typos but then ignores the valid value would be worse
    than the original bug. TWO different valid values must produce TWO
    different resolved outputs, asserted against hardcoded numbers."""

    def test_two_pair_ceilings_resolve_to_two_ceilings(self, monkeypatch):
        """F-SCANG-3. Fails when broken: consumption dropped (e.g. the
        refusal added but ``ceiling = configured`` lost) -> both setenvs
        resolve to 28.0 and the exact assertions fail."""
        monkeypatch.setenv(PAIR_CEILING_GIB_ENV, "20")
        assert pair_ceiling_gib() == 20.0
        monkeypatch.setenv(PAIR_CEILING_GIB_ENV, "21")
        assert pair_ceiling_gib() == 21.0
        # Above the operator default too: consumed, not min'd with 28.
        monkeypatch.setenv(PAIR_CEILING_GIB_ENV, "72")
        assert pair_ceiling_gib() == 72.0

    def test_two_quotas_convert_mib_to_gib_and_tighten_the_ceiling(self, monkeypatch):
        """F-SCANG-3. Fails when broken: the 1024-based conversion or the
        quota-tightens-ceiling rule dropped -> 10.0/20.0 (and the
        tightened pair ceiling) no longer come out exactly."""
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "10240")
        assert host_quota_gib() == 10.0
        # With no pair override, the declared quota tightens the
        # operator default (28.0 -> 10.0).
        assert pair_ceiling_gib() == 10.0
        monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "20480")
        assert host_quota_gib() == 20.0
        assert pair_ceiling_gib() == 20.0

    def test_two_probe_quotas_resolve_to_two_thresholds(self, monkeypatch):
        """F-SCANG-3. Fails when broken: consumption dropped -> both
        setenvs resolve to the 28.8 fraction bound and the exact
        assertions fail."""
        monkeypatch.setenv(VRAM_QUOTA_ENV, "20")
        assert vram_attribution_threshold_gb(_PROBE_DEVICE_GB) == 20.0
        monkeypatch.setenv(VRAM_QUOTA_ENV, "25")
        assert vram_attribution_threshold_gb(_PROBE_DEVICE_GB) == 25.0
        # A quota looser than the device fraction does not loosen it.
        monkeypatch.setenv(VRAM_QUOTA_ENV, "30")
        assert vram_attribution_threshold_gb(_PROBE_DEVICE_GB) == _PROBE_FRACTION_BOUND


class TestUnsetAndEmptyStayDefault:
    @pytest.mark.parametrize(("env_var", "resolve", "unset_expected"), SIBLINGS, ids=_SIBLING_IDS)
    def test_unset_resolves_the_default(self, env_var, resolve, unset_expected):
        """F-SCANG-3. Fails when broken: the refusal over-reaching into
        the unset path (raising with no variable set) crashes here, and
        a changed default fails the exact comparison."""
        if unset_expected is None:
            assert resolve() is None
        else:
            assert resolve() == unset_expected

    @pytest.mark.parametrize(("env_var", "resolve", "unset_expected"), SIBLINGS, ids=_SIBLING_IDS)
    def test_empty_string_behaves_as_unset(self, monkeypatch, env_var, resolve, unset_expected):
        """F-SCANG-3, the named deliberate DIVERGENCE from the RSS
        variable (which refuses ""): an empty value is the shell-wrapper
        pass-through pattern ``VAR="${VAR:-}"``, not a typo'd number, so
        it stays unset-equivalent. Fails when broken: someone "completes"
        the RSS mirror by refusing "" -> the raise fails the exact
        comparison; or "" starts being consumed as 0 -> likewise."""
        monkeypatch.setenv(env_var, "")
        if unset_expected is None:
            assert resolve() is None
        else:
            assert resolve() == unset_expected
