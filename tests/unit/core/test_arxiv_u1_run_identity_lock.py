"""arXiv U1 (#253 / #254) — run identity in the workspace lock.

The lock gained three CANONICAL fields: the workflow topology
(``lit_review_enabled`` + ``lit_review_config_sha256``) and the opaque
``experiment_arm`` label. Everything here is what Pydantic, pyright and the
existing lock tests cannot see:

* ``TestTopologyAndArmAreCanonical`` — the EXISTING comparison refuses a
  resume across any of the three. Fails when a field is dropped from
  ``_CANONICAL`` (the partition guard would still be green if it were moved
  to ``_PROVENANCE`` deliberately — that move is exactly the defect this
  pins) or when the violation stops naming the field.
* ``TestLegacyLockBytes`` — the three keys are OMITTED at their defaults.
  Fails when any of them is serialized as ``null``/``false`` (every legacy
  lock's bytes would change) or when a pre-U1 lock text stops parsing into
  the unlabelled, lit-review-OFF state.
* ``TestRefusedShapes`` — cross-field rules the schema cannot express as
  types: an empty arm label, and a topology flag that disagrees with the
  config pin.
* ``TestIngressThreeCases`` — the R-11-9 three-case rule applied to the arm
  at the record-ingress validator. Fails when a labelled run silently reads
  an unstamped record (case 3 collapsing into case 1).
"""

from __future__ import annotations

import json

import pytest

from core.run_invariants import (
    RUN_INVARIANTS_BASENAME,
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
    load_run_invariants,
    validate_stamped_invariants,
    write_run_invariants,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
FULL = list(range(20))


def _inv(**overrides) -> RunInvariants:
    base = dict(resolved_data_scope=FULL, health_gate_enabled=False, health_config_sha256=None)
    base.update(overrides)
    return RunInvariants(**base)


# The serialized key set of a lock built with every default, BEFORE U1 (the
# eleven keys `write_run_invariants` emitted for this shape at c991d6f6).
# Hardcoded on purpose: reading it back from the writer would pass for any
# key set.
PRE_U1_DEFAULT_LOCK_KEYS = {
    "resolved_data_scope",
    "health_gate_enabled",
    "health_config_sha256",
    "ordering_override_strategy",
    "ordering_override_file_order",
    "structured_health_feedback_enabled",
    "health_feedback_history_window_iterations",
    "health_feedback_history_max_entries_per_model",
    "runtime_estimator_identity",
    "runtime_policy_identity",
    "created_at",
}


class TestTopologyAndArmAreCanonical:
    def test_the_three_fields_are_compared_never_merely_recorded(self):
        for name in (
            "lit_review_enabled",
            "lit_review_config_sha256",
            "experiment_arm",
            "baseline_isolation",
        ):
            assert name in RunInvariants._CANONICAL, name
            assert name not in RunInvariants._PROVENANCE, name

    @pytest.mark.parametrize(
        "field, first, second",
        [
            (
                "lit_review_enabled",
                dict(lit_review_enabled=True, lit_review_config_sha256=SHA_A),
                dict(),
            ),
            (
                "lit_review_config_sha256",
                dict(lit_review_enabled=True, lit_review_config_sha256=SHA_A),
                dict(lit_review_enabled=True, lit_review_config_sha256=SHA_B),
            ),
            (
                "experiment_arm",
                dict(experiment_arm="with-prior-art"),
                dict(experiment_arm="without-prior-art"),
            ),
            # arXiv U3 — an isolated and a non-isolated run saw different
            # prompt surfaces; toggling the flag on one workspace is refused.
            ("baseline_isolation", dict(baseline_isolation=True), dict()),
        ],
    )
    def test_toggling_refuses_the_resume_naming_the_field(self, tmp_path, field, first, second):
        assert ensure_run_invariants(str(tmp_path), _inv(**first)) == "created"
        with pytest.raises(RunInvariantsViolation) as exc:
            ensure_run_invariants(str(tmp_path), _inv(**second))
        assert field in str(exc.value)

    def test_same_identity_resumes(self, tmp_path):
        labelled = _inv(
            experiment_arm="with-prior-art",
            lit_review_enabled=True,
            lit_review_config_sha256=SHA_A,
        )
        assert ensure_run_invariants(str(tmp_path), labelled) == "created"
        assert ensure_run_invariants(str(tmp_path), labelled) == "validated"

    def test_unlabelling_a_labelled_workspace_is_refused(self, tmp_path):
        ensure_run_invariants(str(tmp_path), _inv(experiment_arm="with-prior-art"))
        with pytest.raises(RunInvariantsViolation) as exc:
            ensure_run_invariants(str(tmp_path), _inv())
        msg = str(exc.value)
        assert "experiment_arm" in msg
        assert "locked='with-prior-art'" in msg and "this run=None" in msg

    def test_labelling_a_legacy_workspace_is_refused(self, tmp_path):
        """A pre-U1 lock parses to the unlabelled state; a labelled run
        meeting it is a canonical mismatch, never a silent upgrade."""
        legacy = {
            "resolved_data_scope": FULL,
            "health_gate_enabled": False,
            "health_config_sha256": None,
        }
        (tmp_path / RUN_INVARIANTS_BASENAME).write_text(json.dumps(legacy))
        with pytest.raises(RunInvariantsViolation, match="experiment_arm"):
            ensure_run_invariants(str(tmp_path), _inv(experiment_arm="with-prior-art"))


class TestLegacyLockBytes:
    def test_defaults_write_none_of_the_three_keys(self, tmp_path):
        write_run_invariants(str(tmp_path), _inv(created_at="2026-08-24T00:00:00+00:00"))
        payload = json.loads((tmp_path / RUN_INVARIANTS_BASENAME).read_text())
        assert set(payload) == PRE_U1_DEFAULT_LOCK_KEYS

    def test_legacy_lock_text_parses_to_the_unlabelled_state_and_validates(self, tmp_path):
        legacy = {
            "resolved_data_scope": FULL,
            "health_gate_enabled": False,
            "health_config_sha256": None,
            "created_at": "2026-07-01T00:00:00+00:00",
        }
        (tmp_path / RUN_INVARIANTS_BASENAME).write_text(json.dumps(legacy))
        loaded = load_run_invariants(str(tmp_path))
        assert loaded is not None
        assert loaded.lit_review_enabled is False
        assert loaded.lit_review_config_sha256 is None
        assert loaded.experiment_arm is None
        assert ensure_run_invariants(str(tmp_path), _inv()) == "validated"

    def test_a_labelled_lit_review_on_lock_round_trips_with_the_keys_present(self, tmp_path):
        labelled = _inv(
            experiment_arm="with-prior-art",
            lit_review_enabled=True,
            lit_review_config_sha256=SHA_A,
        )
        write_run_invariants(str(tmp_path), labelled)
        payload = json.loads((tmp_path / RUN_INVARIANTS_BASENAME).read_text())
        assert payload["experiment_arm"] == "with-prior-art"
        assert payload["lit_review_enabled"] is True
        assert payload["lit_review_config_sha256"] == SHA_A
        loaded = load_run_invariants(str(tmp_path))
        assert loaded is not None
        assert loaded.canonical() == labelled.canonical()

    def test_a_labelled_lit_review_off_lock_writes_only_the_arm(self, tmp_path):
        """The WITHOUT arm: the label is present, the OFF topology is the
        omitted default — one rule for the lock and the manifest."""
        write_run_invariants(str(tmp_path), _inv(experiment_arm="without-prior-art"))
        payload = json.loads((tmp_path / RUN_INVARIANTS_BASENAME).read_text())
        assert payload["experiment_arm"] == "without-prior-art"
        assert "lit_review_enabled" not in payload
        assert "lit_review_config_sha256" not in payload
        assert "baseline_isolation" not in payload

    def test_an_isolated_lock_writes_the_flag_positively(self, tmp_path):
        write_run_invariants(str(tmp_path), _inv(baseline_isolation=True))
        payload = json.loads((tmp_path / RUN_INVARIANTS_BASENAME).read_text())
        assert payload["baseline_isolation"] is True


class TestRefusedShapes:
    @pytest.mark.parametrize("bad", ["", "   "])
    def test_an_empty_arm_label_is_refused(self, bad):
        with pytest.raises(ValueError, match="experiment_arm"):
            _inv(experiment_arm=bad)

    def test_enabled_without_a_config_pin_is_refused(self):
        with pytest.raises(ValueError, match="lit_review_config_sha256"):
            _inv(lit_review_enabled=True)

    def test_a_config_pin_without_the_topology_flag_is_refused(self):
        with pytest.raises(ValueError, match="lit_review_enabled=False"):
            _inv(lit_review_config_sha256=SHA_A)


class TestIngressThreeCases:
    def _check(self, stamped: dict, expected: RunInvariants) -> None:
        # The fixture runs gates OFF; an UNSTAMPED gate flag reads as "gates
        # active" (DS6b), so the record states its own posture explicitly.
        validate_stamped_invariants(
            {"health_gate_enabled": False, **stamped}, expected, full_scope=FULL, source="seed x"
        )

    def test_unlabelled_run_reads_an_unstamped_record(self):
        self._check({}, _inv())

    def test_unlabelled_run_reads_a_labelled_record(self):
        """Mirrors R-11-9: the rule is keyed on THIS run being labelled, so an
        unlabelled (legacy) run is untouched by the arm entirely."""
        self._check({"experiment_arm": "with-prior-art"}, _inv())

    def test_labelled_run_reads_a_matching_record(self):
        self._check({"experiment_arm": "with-prior-art"}, _inv(experiment_arm="with-prior-art"))

    def test_labelled_run_refuses_a_record_from_another_arm(self):
        with pytest.raises(RunInvariantsViolation) as exc:
            self._check(
                {"experiment_arm": "without-prior-art"}, _inv(experiment_arm="with-prior-art")
            )
        msg = str(exc.value)
        assert "experiment_arm" in msg
        assert "'without-prior-art'" in msg and "'with-prior-art'" in msg

    def test_labelled_run_refuses_an_unstamped_record(self):
        """Case 3 — absence is not agreement."""
        with pytest.raises(RunInvariantsViolation) as exc:
            self._check({}, _inv(experiment_arm="with-prior-art"))
        msg = str(exc.value)
        assert "experiment_arm" in msg and "LABELLED" in msg
