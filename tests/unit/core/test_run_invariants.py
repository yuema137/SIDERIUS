"""
DS6 — core/run_invariants.py: generic immutable run-level invariant lock.

Covers the doc's DS6 lock tests: atomic create with first-writer-wins,
loser-validates, equality over canonical fields only (timestamps excluded),
and the violation matrix — scope change / HealthGate enable flip /
policy-sha drift each fail naming the drifted field.
See docs/design/enable_partial_file_list.md (Commit DS6).
"""

from __future__ import annotations

import json
import os

import pytest

from core.run_invariants import (
    RUN_INVARIANTS_BASENAME,
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
    ensure_run_invariants,
    load_run_invariants,
    validate_run_invariants,
    validate_stamped_invariants,
    write_run_invariants,
)

FULL = RunInvariants(
    resolved_data_scope=list(range(20)),
    health_gate_enabled=True,
    health_config_sha256="a" * 64,
)
PARTIAL = RunInvariants(
    resolved_data_scope=[4, 5, 6, 7, 8, 9],
    health_gate_enabled=True,
    health_config_sha256="b" * 64,
)
DISABLED = RunInvariants(
    resolved_data_scope=[4, 5, 6, 7, 8, 9],
    health_gate_enabled=False,
    health_config_sha256=None,
)


class TestWriteAndLoad:
    def test_round_trip(self, tmp_path):
        path = write_run_invariants(str(tmp_path), PARTIAL)
        assert os.path.basename(path) == RUN_INVARIANTS_BASENAME
        loaded = load_run_invariants(str(tmp_path))
        assert loaded is not None
        assert loaded.canonical() == PARTIAL.canonical()

    def test_created_at_stamped_but_not_canonical(self, tmp_path):
        write_run_invariants(str(tmp_path), PARTIAL)
        loaded = load_run_invariants(str(tmp_path))
        assert loaded.created_at is not None
        assert "created_at" not in loaded.canonical()

    def test_load_absent_returns_none(self, tmp_path):
        assert load_run_invariants(str(tmp_path)) is None

    def test_no_stray_temp_files(self, tmp_path):
        write_run_invariants(str(tmp_path), PARTIAL)
        assert os.listdir(str(tmp_path)) == [RUN_INVARIANTS_BASENAME]

    def test_corrupted_lock_is_violation_not_legacy(self, tmp_path):
        (tmp_path / RUN_INVARIANTS_BASENAME).write_text("{not json")
        with pytest.raises(RunInvariantsViolation, match="corrupted"):
            load_run_invariants(str(tmp_path))

    def test_second_write_raises_file_exists(self, tmp_path):
        write_run_invariants(str(tmp_path), PARTIAL)
        with pytest.raises(FileExistsError):
            write_run_invariants(str(tmp_path), PARTIAL)


class TestEnsureFirstWriterWins:
    def test_create_then_validate(self, tmp_path):
        assert ensure_run_invariants(str(tmp_path), PARTIAL) == "created"
        # Simulated losing writer: same configuration arrives second.
        assert ensure_run_invariants(str(tmp_path), PARTIAL) == "validated"

    def test_losing_writer_with_drift_fails(self, tmp_path):
        ensure_run_invariants(str(tmp_path), PARTIAL)
        with pytest.raises(RunInvariantsViolation):
            ensure_run_invariants(str(tmp_path), FULL)

    def test_equality_ignores_created_at(self, tmp_path):
        ensure_run_invariants(str(tmp_path), PARTIAL)
        # Same canonical fields, explicit different timestamp → still valid.
        relabeled = PARTIAL.model_copy(update={"created_at": "1970-01-01T00:00:00+00:00"})
        assert ensure_run_invariants(str(tmp_path), relabeled) == "validated"


class TestViolationMatrix:
    def test_model_output_retention_flip_is_canonical(self, tmp_path):
        write_run_invariants(str(tmp_path), PARTIAL)
        retained = PARTIAL.model_copy(update={"retain_model_outputs": True})
        with pytest.raises(RunInvariantsViolation, match="retain_model_outputs"):
            validate_run_invariants(str(tmp_path), retained)

    def test_validate_without_lock_raises(self, tmp_path):
        with pytest.raises(RunInvariantsViolation, match=r"no .*lock"):
            validate_run_invariants(str(tmp_path), PARTIAL)

    def test_scope_change_names_field(self, tmp_path):
        write_run_invariants(str(tmp_path), PARTIAL)
        changed = PARTIAL.model_copy(update={"resolved_data_scope": [5, 6, 7, 8, 9]})
        with pytest.raises(RunInvariantsViolation, match="resolved_data_scope"):
            validate_run_invariants(str(tmp_path), changed)

    def test_enabled_flip_names_field(self, tmp_path):
        write_run_invariants(str(tmp_path), PARTIAL)
        with pytest.raises(RunInvariantsViolation, match="health_gate_enabled"):
            validate_run_invariants(str(tmp_path), DISABLED)

    def test_policy_sha_drift_names_field(self, tmp_path):
        write_run_invariants(str(tmp_path), PARTIAL)
        drifted = PARTIAL.model_copy(update={"health_config_sha256": "c" * 64})
        with pytest.raises(RunInvariantsViolation, match="health_config_sha256"):
            validate_run_invariants(str(tmp_path), drifted)
        # The un-drifted fields are NOT reported.
        with pytest.raises(RunInvariantsViolation) as excinfo:
            validate_run_invariants(str(tmp_path), drifted)
        assert "resolved_data_scope" not in str(excinfo.value)

    def test_lock_file_is_plain_json(self, tmp_path):
        """The lock must stay hand-inspectable: flat JSON with the canonical
        fields + created_at. The ordering-override pair joined the canonical
        set in V19 PR 2 (defaults None = no override); the
        structured-health-feedback policy triple joined in V19 PR 3
        (defaults OFF / 3 / 8 = pre-feature state)."""
        write_run_invariants(str(tmp_path), DISABLED)
        raw = json.loads((tmp_path / RUN_INVARIANTS_BASENAME).read_text())
        assert raw["resolved_data_scope"] == [4, 5, 6, 7, 8, 9]
        assert raw["health_gate_enabled"] is False
        assert raw["health_config_sha256"] is None
        assert raw["ordering_override_strategy"] is None
        assert raw["ordering_override_file_order"] is None
        assert raw["structured_health_feedback_enabled"] is False
        assert raw["health_feedback_history_window_iterations"] == 3
        assert raw["health_feedback_history_max_entries_per_model"] == 8
        assert set(raw) == {
            "resolved_data_scope",
            "health_gate_enabled",
            "health_config_sha256",
            "ordering_override_strategy",
            "ordering_override_file_order",
            "structured_health_feedback_enabled",
            "health_feedback_history_window_iterations",
            "health_feedback_history_max_entries_per_model",
            # C9d — the runtime subsystem's behavioral identities.
            "runtime_estimator_identity",
            "runtime_policy_identity",
            "created_at",
        }


FULL_SCOPE = list(range(20))
SYNTHETIC_COMPOSITION_FINGERPRINT = "synthetic-composition"


class TestBuildRunInvariants:
    """DS6b — the ONE shared invariant-computation path (materialize+hash
    first, then construct)."""

    def test_enabled_full_scope_materializes_and_hashes(self, tmp_path):
        inv, path = build_run_invariants(
            resolved_data_scope=FULL_SCOPE,
            health_gate_enabled=True,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path),
            task_composition_fingerprint=SYNTHETIC_COMPOSITION_FINGERPRINT,
        )
        assert path is not None and os.path.isfile(path)
        assert inv.health_config_sha256 is not None
        assert inv.resolved_data_scope == FULL_SCOPE
        assert inv.health_gate_enabled is True

    def test_disabled_has_no_config_and_null_sha(self, tmp_path):
        inv, path = build_run_invariants(
            resolved_data_scope=[4, 5, 6],
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path),
            task_composition_fingerprint=SYNTHETIC_COMPOSITION_FINGERPRINT,
        )
        assert path is None
        assert inv.health_config_sha256 is None
        assert not os.path.exists(tmp_path / "health_checks_effective.yaml")

    def test_partial_scope_with_in_scope_files(self, tmp_path):
        inv, path = build_run_invariants(
            resolved_data_scope=[4, 5, 6, 7, 8, 9],
            health_gate_enabled=True,
            health_gate_files=[4, 7, 9],
            health_checks_config=None,
            workspace=str(tmp_path),
            task_composition_fingerprint=SYNTHETIC_COMPOSITION_FINGERPRINT,
        )
        assert path is not None
        assert inv.health_config_sha256 is not None

    def test_deterministic_sha_across_workspaces(self, tmp_path):
        """Workflow (chain root) and tuner (its own dir) must pin the SAME
        sha from the same canonical inputs — invariant 2 of DS6b."""
        inv_a, _ = build_run_invariants(
            resolved_data_scope=FULL_SCOPE,
            health_gate_enabled=True,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path / "chain_root"),
            task_composition_fingerprint=SYNTHETIC_COMPOSITION_FINGERPRINT,
        )
        inv_b, _ = build_run_invariants(
            resolved_data_scope=FULL_SCOPE,
            health_gate_enabled=True,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path / "iter_001_tuner"),
            task_composition_fingerprint=SYNTHETIC_COMPOSITION_FINGERPRINT,
        )
        assert inv_a.canonical() == inv_b.canonical()


class TestValidateStampedInvariants:
    """DS6b — legacy-aware ingress validation of persisted stamps."""

    EXPECTED_FULL = RunInvariants(
        resolved_data_scope=FULL_SCOPE,
        health_gate_enabled=True,
        health_config_sha256="e" * 64,
    )
    EXPECTED_PARTIAL = RunInvariants(
        resolved_data_scope=[4, 5, 6, 7, 8, 9],
        health_gate_enabled=True,
        health_config_sha256="e" * 64,
    )

    def test_fully_stamped_match_passes(self):
        validate_stamped_invariants(
            {
                "resolved_data_scope": FULL_SCOPE,
                "health_gate_enabled": True,
                "health_config_sha256": "e" * 64,
            },
            self.EXPECTED_FULL,
            full_scope=FULL_SCOPE,
            source="record x",
        )

    def test_legacy_unstamped_vs_full_run_passes(self):
        validate_stamped_invariants(
            {}, self.EXPECTED_FULL, full_scope=FULL_SCOPE, source="legacy record"
        )

    def test_legacy_unstamped_vs_partial_run_fails(self):
        with pytest.raises(RunInvariantsViolation, match="legacy = full scope"):
            validate_stamped_invariants(
                {}, self.EXPECTED_PARTIAL, full_scope=FULL_SCOPE, source="legacy record"
            )

    def test_stamped_scope_mismatch_fails(self):
        with pytest.raises(RunInvariantsViolation, match="resolved_data_scope"):
            validate_stamped_invariants(
                {"resolved_data_scope": [1, 2, 3]},
                self.EXPECTED_FULL,
                full_scope=FULL_SCOPE,
                source="record x",
            )

    def test_enabled_flip_fails(self):
        expected_disabled = RunInvariants(
            resolved_data_scope=FULL_SCOPE,
            health_gate_enabled=False,
            health_config_sha256=None,
        )
        with pytest.raises(RunInvariantsViolation, match="health_gate_enabled"):
            validate_stamped_invariants(
                {"resolved_data_scope": FULL_SCOPE, "health_gate_enabled": True},
                expected_disabled,
                full_scope=FULL_SCOPE,
                source="record x",
            )

    def test_legacy_missing_enabled_incompatible_with_disabled_run(self):
        expected_disabled = RunInvariants(
            resolved_data_scope=FULL_SCOPE,
            health_gate_enabled=False,
            health_config_sha256=None,
        )
        with pytest.raises(RunInvariantsViolation, match="legacy = gates active"):
            validate_stamped_invariants(
                {"resolved_data_scope": FULL_SCOPE},
                expected_disabled,
                full_scope=FULL_SCOPE,
                source="record x",
            )

    def test_sha_drift_fails_and_missing_sha_skipped(self):
        with pytest.raises(RunInvariantsViolation, match="health_config_sha256"):
            validate_stamped_invariants(
                {
                    "resolved_data_scope": FULL_SCOPE,
                    "health_gate_enabled": True,
                    "health_config_sha256": "f" * 64,
                },
                self.EXPECTED_FULL,
                full_scope=FULL_SCOPE,
                source="record x",
            )
        # Missing sha (pre-policy-lock record) → skipped, no error.
        validate_stamped_invariants(
            {"resolved_data_scope": FULL_SCOPE, "health_gate_enabled": True},
            self.EXPECTED_FULL,
            full_scope=FULL_SCOPE,
            source="record x",
        )


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
