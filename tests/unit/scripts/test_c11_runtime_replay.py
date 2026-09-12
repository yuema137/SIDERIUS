"""C11 — replay tools and legacy migration.

Everything runs against a SYNTHETIC snapshot built in tmp_path: these
tests must not depend on a developer machine holding the real forensic
evidence, and they must never write near it.

The property under test is mostly negative: a replay report must be
structurally incapable of claiming runtime truth it does not have.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tools.runtime_replay.executable_replay import (
    eligible_candidates,
    plan_executable_replay,
    run_executable_replay,
)
from tools.runtime_replay.legacy_migration import (
    discover_legacy_tables,
    legacy_entries_as_priors,
    migrate_legacy_table,
)
from tools.runtime_replay.metadata_replay import (
    SnapshotNotFound,
    run_metadata_replay,
    verify_snapshot_integrity,
)
from tools.runtime_replay.schemas import (
    MeasuredRuntime,
    ReplayCandidate,
    ReplayReport,
)


def _snapshot(tmp_path, *, with_manifest=True, proposals=None, rejections=None):
    """A miniature forensic snapshot with the real directory shape."""
    root = tmp_path / "forensics" / "wave1"
    workspace = root / "arch" / "workspace" / "iter_001" / "iteration_001" / "attempt_001"
    workspace.mkdir(parents=True)
    for index, payload in enumerate(
        proposals
        if proposals is not None
        else [
            {
                "model_name": "registered_survivor",
                "parameter_count_estimate": 312_000,
                "preflight_estimated_minutes": 29.16,
                "preflight_factor": 1.458,
            }
        ]
    ):
        (workspace / f"proposal_iter_{index + 1:03d}.json").write_text(json.dumps(payload))
    log = root / "arch" / "chain.log"
    lines = [
        "   Stage 'proposing': calling LLM (pre-flight 1/3, structural 1/3)...",
    ]
    for factor in rejections if rejections is not None else [84.64, 8.12]:
        lines.append(f"   Pre-flight rejected (factor={factor}x); requesting revision 2/3.")
    log.write_text("\n".join(lines))
    if with_manifest:
        shared = root / "shared"
        shared.mkdir(parents=True, exist_ok=True)
        import hashlib

        entries = []
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries.append(f"{digest}  {path}")
        (shared / "SHA256SUMS").write_text("\n".join(entries) + "\n")
    return root


class TestSchemaEnforcedLabels:
    def test_metadata_mode_cannot_carry_a_measurement(self):
        candidate = ReplayCandidate(
            model_name="m",
            stage="surviving_proposal",
            source="s",
            implementation_available=True,
            measured=MeasuredRuntime(train_ms_per_step=10.0),
        )
        with pytest.raises(ValidationError, match="METADATA replay cannot carry"):
            ReplayReport(mode="metadata", snapshot_root="/x", candidates=(candidate,))
        # the same candidate is fine in executable mode
        ReplayReport(mode="executable", snapshot_root="/x", candidates=(candidate,))

    def test_a_candidate_without_an_implementation_cannot_be_measured(self):
        with pytest.raises(ValidationError, match="no loadable implementation"):
            ReplayCandidate(
                model_name="ghost",
                stage="surviving_proposal",
                source="s",
                implementation_available=False,
                measured=MeasuredRuntime(train_ms_per_step=10.0),
            )

    def test_a_rejected_draft_can_never_carry_runtime(self):
        """The drafts the static formula killed were never implemented, so
        no tooling may attach a runtime number to them."""
        with pytest.raises(ValidationError, match="rejected before implementation"):
            ReplayCandidate(
                model_name=None,
                stage="rejected_draft",
                source="chain.log",
                implementation_available=True,  # even if this were somehow true
                measured=MeasuredRuntime(train_ms_per_step=10.0),
            )

    def test_static_numbers_are_labeled_as_estimates(self):
        candidate = ReplayCandidate(
            model_name="m", stage="surviving_proposal", source="s", static_factor=84.64
        )
        assert candidate.static_label == "static_estimate"
        assert candidate.runtime_truth_known is False


class TestMetadataReplay:
    def test_it_reads_surviving_proposals_and_rejected_drafts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ml_models.models_sandbox.MODEL_REGISTRY", {"registered_survivor": object()}
        )
        report = run_metadata_replay(_snapshot(tmp_path))
        assert report.mode == "metadata"
        survivors = [c for c in report.candidates if c.stage == "surviving_proposal"]
        drafts = [c for c in report.candidates if c.stage == "rejected_draft"]
        assert len(survivors) == 1 and len(drafts) == 2
        assert survivors[0].parameter_count_estimate == 312_000
        assert survivors[0].implementation_available is True
        assert sorted(d.static_factor for d in drafts) == [8.12, 84.64]

    def test_rejected_drafts_carry_no_reconstructed_numbers(self, tmp_path):
        """Only the factor survives in the log. Inventing a parameter count
        would manufacture the evidence the replay exists to look for."""
        report = run_metadata_replay(_snapshot(tmp_path))
        for draft in (c for c in report.candidates if c.stage == "rejected_draft"):
            assert draft.parameter_count_estimate is None
            assert draft.static_estimated_minutes is None
            assert draft.model_name is None
            assert draft.implementation_available is False
            assert "never implemented" in draft.implementation_detail

    def test_an_unregistered_model_is_marked_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ml_models.models_sandbox.MODEL_REGISTRY", {})
        report = run_metadata_replay(_snapshot(tmp_path))
        survivor = next(c for c in report.candidates if c.stage == "surviving_proposal")
        assert survivor.implementation_available is False
        assert "not present" in survivor.implementation_detail

    def test_it_never_claims_ground_truth(self, tmp_path):
        report = run_metadata_replay(_snapshot(tmp_path))
        assert all(c.measured is None for c in report.candidates)
        text = report.render()
        assert "neither that the original verdict was right nor that it was wrong" in text

    def test_a_missing_snapshot_is_a_clear_path_error(self, tmp_path):
        with pytest.raises(SnapshotNotFound, match="read-only evidence"):
            run_metadata_replay(tmp_path / "does_not_exist")

    def test_replay_is_deterministic(self, tmp_path):
        first = run_metadata_replay(_snapshot(tmp_path))
        second = run_metadata_replay(first.snapshot_root)
        assert first.model_dump() == second.model_dump()

    def test_it_does_not_modify_the_snapshot(self, tmp_path):
        import hashlib

        root = _snapshot(tmp_path)
        before = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }
        run_metadata_replay(root)
        after = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }
        assert before == after


class TestSnapshotIntegrity:
    def test_verified(self, tmp_path):
        status, detail = verify_snapshot_integrity(_snapshot(tmp_path))
        assert status == "verified"
        assert "hash-match" in detail

    def test_tampering_is_detected(self, tmp_path):
        root = _snapshot(tmp_path)
        (root / "arch" / "chain.log").write_text("tampered")
        status, _ = verify_snapshot_integrity(root)
        assert status == "mismatch"

    def test_absent_manifest_is_unverified_not_verified(self, tmp_path):
        status, detail = verify_snapshot_integrity(_snapshot(tmp_path, with_manifest=False))
        assert status == "unverified"
        assert "no SHA256SUMS" in detail


class TestExecutableReplay:
    def _report(self, tmp_path, monkeypatch, registered=True):
        monkeypatch.setattr(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            {"registered_survivor": object()} if registered else {},
        )
        return run_metadata_replay(_snapshot(tmp_path))

    def test_only_implemented_survivors_are_eligible(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, monkeypatch)
        eligible = eligible_candidates(report)
        assert [c.model_name for c in eligible] == ["registered_survivor"]

    def test_nothing_is_eligible_without_an_implementation(self, tmp_path, monkeypatch):
        assert eligible_candidates(self._report(tmp_path, monkeypatch, registered=False)) == ()

    def test_the_plan_names_what_is_skipped_and_why(self, tmp_path, monkeypatch):
        plan = plan_executable_replay(self._report(tmp_path, monkeypatch))
        assert plan["probes"] == 1
        assert plan["gpu_required"] is True
        reasons = [s["reason"] for s in plan["skipped"]]
        assert len(plan["skipped"]) == 2
        assert all("never implemented" in r for r in reasons)

    def test_measuring_promotes_the_report_to_executable_mode(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, monkeypatch)
        measured = run_executable_replay(
            report,
            probe=lambda c: MeasuredRuntime(
                train_ms_per_step=17.6, realized_parameter_count=45_408
            ),
        )
        assert measured.mode == "executable"
        survivor = next(c for c in measured.candidates if c.stage == "surviving_proposal")
        assert survivor.measured is not None
        assert survivor.measured.label == "empirical_measurement"
        assert survivor.measured.realized_parameter_count == 45_408

    def test_unmeasurable_candidates_are_carried_through_not_dropped(self, tmp_path, monkeypatch):
        """Dropping them would make the report read as though every
        candidate had been validated."""
        report = self._report(tmp_path, monkeypatch)
        measured = run_executable_replay(report, probe=lambda c: MeasuredRuntime())
        assert len(measured.candidates) == len(report.candidates)
        drafts = [c for c in measured.candidates if c.stage == "rejected_draft"]
        assert len(drafts) == 2
        assert all(d.measured is None for d in drafts)
        assert len(measured.metadata_only) == 2

    def test_the_report_states_the_limits_of_what_it_measured(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, monkeypatch)
        measured = run_executable_replay(report, probe=lambda c: MeasuredRuntime())
        assert any("never implemented" in note for note in measured.notes)


class TestLegacyMigration:
    def _table(self, tmp_path):
        path = tmp_path / "time_calibration_nvidia_geforce_rtx_5090.json"
        path.write_text(
            json.dumps(
                {
                    "history": [
                        {"actual_ms_per_step": 20.0, "actual_minutes": 12.5},
                        {"actual_ms_per_step": 21.0, "actual_minutes": 13.0},
                    ]
                }
            )
        )
        return path

    def test_migration_registers_by_hash_and_imports_nothing(self, tmp_path):
        from core.runtime_control.calibration_registry import CalibrationRegistry

        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        summary = migrate_legacy_table(self._table(tmp_path), registry=registry)
        assert summary["entry_count"] == 2
        assert summary["imported_as_observations"] == 0
        assert summary["provenance_of_entries"] == "legacy_calibration_prior"
        assert summary["registered"] is True
        assert summary["source_unmodified"] is True
        manifest = registry.load_manifest()
        assert len(manifest.legacy_sources) == 1
        assert manifest.legacy_sources[0].file_sha256 == summary["file_sha256"]
        # the crucial part: no observation was fabricated from the legacy rows
        assert manifest.observation_ids == []

    def test_dry_run_writes_nothing(self, tmp_path):
        from core.runtime_control.calibration_registry import CalibrationRegistry

        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        summary = migrate_legacy_table(self._table(tmp_path), registry=registry, dry_run=True)
        assert summary["registered"] is False
        assert registry.load_manifest().legacy_sources == []

    def test_legacy_entries_are_tier_one_priors(self, tmp_path):
        priors = legacy_entries_as_priors(self._table(tmp_path))
        assert len(priors) == 2
        for prior in priors:
            assert prior["provenance"] == "legacy_calibration_prior"
            assert prior["blocking_eligible"] is False

    def test_discovery_is_scoped_and_safe_when_absent(self, tmp_path):
        assert discover_legacy_tables(tmp_path / "nowhere") == []
        self._table(tmp_path)
        assert [p.name for p in discover_legacy_tables(tmp_path)] == [
            "time_calibration_nvidia_geforce_rtx_5090.json"
        ]


class TestCliSurface:
    def test_the_three_subcommands_exist(self):
        from tools.runtime_replay.__main__ import build_parser

        parser = build_parser()
        for argv in (
            ["metadata", "--snapshot", "/x"],
            ["executable", "--snapshot", "/x"],
            ["legacy", "--dry-run"],
        ):
            assert parser.parse_args(argv)

    def test_executable_defaults_to_planning_not_running(self):
        from tools.runtime_replay.__main__ import build_parser

        args = build_parser().parse_args(["executable", "--snapshot", "/x"])
        assert args.run is False
