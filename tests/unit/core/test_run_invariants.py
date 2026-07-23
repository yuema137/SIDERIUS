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
    ensure_run_invariants,
    load_run_invariants,
    validate_run_invariants,
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
        """The lock must stay hand-inspectable: flat JSON with the three
        canonical fields + created_at."""
        write_run_invariants(str(tmp_path), DISABLED)
        raw = json.loads((tmp_path / RUN_INVARIANTS_BASENAME).read_text())
        assert raw["resolved_data_scope"] == [4, 5, 6, 7, 8, 9]
        assert raw["health_gate_enabled"] is False
        assert raw["health_config_sha256"] is None
        assert set(raw) == {
            "resolved_data_scope",
            "health_gate_enabled",
            "health_config_sha256",
            "created_at",
        }
