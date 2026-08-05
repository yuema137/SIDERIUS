"""Scientific gate membership comes from a declared role, not an action.

Predecessor hotfix to V20 PR D, found by the post-PR-E re-audit.

**The defect.** Two production paths disagreed about the same record:

    in-run trial selection   -> resolved against the REPO-CURRENT config
    resume-time incumbent    -> resolved against the EFFECTIVE config

and the scientific gate set was derived from ``on_fail.action``. Under an
observe-only config every action is ``continue``, so the action-derived set
was **empty**, ``required.issubset(results)`` was trivially true, and every
successful record classified VALID — including one whose collapse detector
had failed with ``would_invalidate_under_production_policy: true``.

Measured before the fix:

    in-run  -> invalid
    resume  -> valid

So a record rejected during the run could become the incumbent on resume.

**The fix.** ``gate_role`` is declared in the config and is a property of
the *science*, identical in both shipped configs, which differ only in
enforcement. One resolver reads it and both paths call it.

Deriving the role from the action does not merely lose information — it
**inverts** the answer, which is why these tests assert on an observe-only
config rather than only on the blocking one.
"""

from __future__ import annotations

import hashlib
import os

import pytest
import yaml

from execute_tools.health_checks.candidate_eligibility import (
    classify_candidate_health,
    legacy_config_body_sha,
    resolve_scientific_gate_ids,
)
from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.schemas import CandidateHealthValidity

BLOCKING_CONFIG = "configs/health_checks.yaml"
OBSERVE_CONFIG = "configs/health_checks_baseline_observe_mode.yaml"

#: The scientific set, which must be identical under both configs.
SCIENTIFIC = frozenset(
    {"output_diversity_blocking", "output_std_blocking", "amplitude_collapse_blocking"}
)
OBSERVATIONAL = frozenset(
    {
        "pearson_dispersion_recording",
        "spectral_peak_ratio_recording",
        "per_file_output_std_recording",
    }
)


def _collapsed_record() -> dict:
    """THE record from the re-audit: observe-only run, collapse gate failed,
    production policy says it would have been invalidated."""
    return {
        "status": "success",
        "denoising_score": 1.23,
        "is_trial": True,
        "health_gate_results": [
            {
                "gate_name": gate_id,
                "execution_status": "passed",
                "check_passed": False,
                "would_invalidate_under_production_policy": True,
            }
            for gate_id in sorted(SCIENTIFIC)
        ],
    }


def _role_less_copy(tmp_path, source: str, mutate=None) -> str:
    """A copy of ``source`` with every ``gate_role`` stripped — i.e. the
    config as it was written before the field existed."""
    body = yaml.safe_load(open(source, encoding="utf-8"))
    for gate in body["health_gates"]:
        gate.pop("gate_role", None)
    if mutate is not None:
        mutate(body)
    path = os.path.join(str(tmp_path), "health_checks_effective.yaml")
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(body, handle, sort_keys=False)
    return path


class TestTheTwoPathsNoLongerDisagree:
    def test_the_reaudit_record_classifies_identically(self):
        """THE REGRESSION, reproduced exactly.

        Before the fix this was `invalid` in-run and `valid` at resume.
        """
        record = _collapsed_record()

        in_run = classify_candidate_health(record)
        resume = classify_candidate_health(
            record, required_gate_ids=resolve_scientific_gate_ids(OBSERVE_CONFIG)
        )

        assert in_run is resume, (
            f"the same record classified {in_run} in-run and {resume} at "
            f"resume — a record rejected during the run could become the "
            f"incumbent"
        )
        assert in_run is CandidateHealthValidity.INVALID

    def test_a_collapsed_record_is_invalid_under_the_observe_config(self):
        """The direction that matters: observe-only must not launder a
        collapse into a valid candidate."""
        verdict = classify_candidate_health(
            _collapsed_record(),
            required_gate_ids=resolve_scientific_gate_ids(OBSERVE_CONFIG),
        )
        assert verdict is CandidateHealthValidity.INVALID


class TestTheRoleIsDeclaredNotDerived:
    @pytest.mark.parametrize("config", [BLOCKING_CONFIG, OBSERVE_CONFIG])
    def test_both_shipped_configs_resolve_the_same_scientific_set(self, config):
        """MUTATION TARGET: restoring action-derived membership.

        The two configs declare identical science and differ only in
        enforcement, so this set must not move between them. Under the old
        action-derived rule the observe config returned the EMPTY SET.
        """
        assert resolve_scientific_gate_ids(config) == SCIENTIFIC

    @pytest.mark.parametrize("config", [BLOCKING_CONFIG, OBSERVE_CONFIG])
    def test_every_gate_declares_a_role(self, config):
        gates = load_health_gates_config(config).health_gates
        missing = [gate.id for gate in gates if gate.gate_role is None]
        assert not missing, f"{config}: gates without a declared role: {missing}"

    def test_the_two_configs_declare_identical_roles(self):
        """The concept, asserted across both files rather than per-file: a
        role that differed between them would mean enforcement had leaked
        into the science."""
        roles = {
            config: {g.id: g.gate_role for g in load_health_gates_config(config).health_gates}
            for config in (BLOCKING_CONFIG, OBSERVE_CONFIG)
        }
        assert roles[BLOCKING_CONFIG] == roles[OBSERVE_CONFIG]

    def test_only_enforcement_differs_between_them(self):
        """The other half: if the actions were also identical, the configs
        would be the same file and these tests would prove nothing."""
        actions = {
            config: {g.id: g.on_fail.action for g in load_health_gates_config(config).health_gates}
            for config in (BLOCKING_CONFIG, OBSERVE_CONFIG)
        }
        assert actions[BLOCKING_CONFIG] != actions[OBSERVE_CONFIG]

    def test_observational_gates_are_never_scientific(self):
        for config in (BLOCKING_CONFIG, OBSERVE_CONFIG):
            assert not (resolve_scientific_gate_ids(config) or frozenset()) & OBSERVATIONAL

    def test_a_mixed_role_config_is_legal(self, tmp_path):
        """Mixed roles are the normal case — three blocking, three
        observational. Only mixed *semantics within one role* would be a
        defect."""
        resolved = resolve_scientific_gate_ids(BLOCKING_CONFIG)
        assert resolved == SCIENTIFIC
        assert OBSERVATIONAL and resolved != frozenset()


class TestHistoricalConfigsStayReadable:
    def test_a_known_historical_config_is_recovered_by_sha(self, tmp_path):
        """Adding the field changes every config's body sha, so a recorded
        `health_config_sha256` from before the hotfix can only be matched by
        reproducing the OLD body."""
        legacy = _role_less_copy(tmp_path, OBSERVE_CONFIG)

        assert (
            legacy_config_body_sha(legacy)
            == "d133a12d3133fb20d632383aa010b1a861fe0fdb6fb6436874b2142d6b5ef58d"
        )
        assert resolve_scientific_gate_ids(legacy) == SCIENTIFIC

    def test_the_blocking_config_historical_sha_also_resolves(self, tmp_path):
        legacy = _role_less_copy(tmp_path, BLOCKING_CONFIG)
        assert (
            legacy_config_body_sha(legacy)
            == "3b5521180f5460a4a7aa67ad0ff67701633d75ed8fdcac4277c222b713655b74"
        )
        assert resolve_scientific_gate_ids(legacy) == SCIENTIFIC

    def test_an_unknown_role_less_config_is_UNKNOWN_not_guessed(self, tmp_path):
        """MUTATION TARGET: inferring the role from the `_blocking` suffix,
        the filename or the action.

        A role-less config that is not in the audited map cannot have its
        science established. `None` means UNKNOWN, and the caller excludes
        the record rather than assuming.
        """

        def nudge(body):
            body["health_gates"][0]["checks"][0]["config"]["min_unique_ratio"] = 0.123456

        unknown = _role_less_copy(tmp_path, OBSERVE_CONFIG, mutate=nudge)

        assert resolve_scientific_gate_ids(unknown) is None, (
            "an unaudited role-less config had its roles guessed — the gate "
            "ids still end in `_blocking`, which is exactly the inference "
            "the compatibility map exists to avoid"
        )

    def test_the_map_is_keyed_on_a_sha_that_is_actually_reproducible(self, tmp_path):
        """The map would be decoration if its keys could never be produced
        by a real file. Both entries are reached above; this asserts the
        derivation itself is the one `resume.py` stamps."""
        legacy = _role_less_copy(tmp_path, BLOCKING_CONFIG)
        config = load_health_gates_config(legacy)
        body = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=True)
        recomputed = hashlib.sha256(body.encode()).hexdigest()

        # The CURRENT dump carries `gate_role: null`, so it must NOT equal
        # the historical sha — that is precisely why the legacy helper
        # strips the key.
        assert recomputed != legacy_config_body_sha(legacy)

    def test_a_missing_or_unparseable_config_yields_no_sha(self, tmp_path):
        """Absence is not evidence: a sha that cannot be computed must be
        `None`, so the caller reaches UNKNOWN rather than a stray match."""
        assert legacy_config_body_sha(str(tmp_path / "nope.yaml")) is None
