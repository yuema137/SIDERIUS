"""
F-SCANH-1 — the task-config run-invariants lock pin (wave2 repair R1).

``configs/task_config.yaml`` feeds TASK_DESCRIPTION / FORWARD_CONTRACT into
every prompt surface via ``workflows.task_config.load_task_config``, yet it
was the ONE tracked config the run-invariants lock did not pin
(``health_config_sha256`` and ``lit_review_config_sha256`` are pinned).
``workflows/model_exploration.py::_snapshot_task_config`` is
first-writer-wins, so an operator edit at iteration 2+ reached the LLM but
neither the snapshot nor any refusal. The fix: the sha256 of the raw file
bytes joins the lock as a COMPARED canonical field
(``RunInvariants.task_config_sha256``), computed by
``workflows.task_config.task_config_file_sha256`` inside
``build_run_invariants`` for un-composed runs only.

Every test here builds the lock through the PRODUCTION entry points
(``build_run_invariants`` -> ``ensure_run_invariants`` /
``write_run_invariants``) — never by hand-writing lock JSON — so a defect in
the production wiring (the builder not calling the helper, the writer
dropping the key, the validator not comparing it) cannot hide behind a
test-built artifact.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from core.run_invariants import (
    RUN_INVARIANTS_BASENAME,
    RunInvariantsViolation,
    build_run_invariants,
    ensure_run_invariants,
    write_run_invariants,
)

#: Known task-config bytes — realistic YAML (the sha helper hashes bytes and
#: never parses, but the fixture mirrors the real file's shape).
TASK_CONFIG_BODY = (
    b"task_description: |\n"
    b"  full-spectrum 1-D time-series denoising of SQUID dark-matter\n"
    b"  detector data: map a noisy [B, T] integer signal to a clean\n"
    b"  [B, 256, T] reconstruction.\n"
    b"forward_contract:\n"
    b"  input_shape: '[B, T] int64'\n"
    b"  output_shape: '[B, 256, T] float32'\n"
)

#: A second, different config — the mid-workspace operator edit.
EDITED_BODY = TASK_CONFIG_BODY + b"  task_note: retuned mid-workspace\n"


def _write_task_config(tmp_path, body: bytes) -> None:
    """Place ``configs/task_config.yaml`` with KNOWN bytes under the tmp cwd."""
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "task_config.yaml").write_bytes(body)


def _build(workspace):
    """The production build, health disabled (the lock-pin surface under
    test is orthogonal to the HealthGate machinery — same convention as
    ``test_run_invariants.py``'s DISABLED fixtures)."""
    invariants, _ = build_run_invariants(
        resolved_data_scope=[4, 5, 6],
        health_gate_enabled=False,
        health_gate_files=None,
        health_checks_config=None,
        workspace=str(workspace),
    )
    return invariants


class TestScanH1TaskConfigLockPin:
    def test_lock_carries_the_pin(self, tmp_path, monkeypatch):
        """F-SCANH-1 (a): the serialized lock pins the task-config file sha.

        Defect only this catches: an operator edit to
        ``configs/task_config.yaml`` mid-workspace changes what the LLM
        reads with no lock refusal — because the lock never recorded the
        file's identity in the first place. The sha is recomputed
        INDEPENDENTLY here from the exact bytes the test wrote, never read
        back from the model under test.

        Fails when: ``build_run_invariants`` stops calling
        ``task_config_file_sha256`` (the key is absent or ``None``), the
        helper hashes something other than the raw file bytes, or
        ``write_run_invariants`` drops the populated key.
        """
        monkeypatch.chdir(tmp_path)
        _write_task_config(tmp_path, TASK_CONFIG_BODY)
        workspace = tmp_path / "ws"

        invariants = _build(workspace)
        assert ensure_run_invariants(str(workspace), invariants) == "created"

        raw = json.loads((workspace / RUN_INVARIANTS_BASENAME).read_text())
        assert raw["task_config_sha256"] == hashlib.sha256(TASK_CONFIG_BODY).hexdigest()

    def test_same_bytes_resume_validates(self, tmp_path, monkeypatch):
        """F-SCANH-1 (b): an unchanged task config resumes cleanly.

        Defect only this catches: the pin refusing what it must admit — a
        nondeterministic digest (ordering, mtime or path leaking into the
        hash) would make every legitimate same-bytes resume fail, which is
        how an over-eager pin gets reverted and the workspace loses the
        protection entirely.

        Fails when: a second production build over identical file bytes
        produces a different ``task_config_sha256``, so
        ``ensure_run_invariants`` raises instead of returning "validated".
        """
        monkeypatch.chdir(tmp_path)
        _write_task_config(tmp_path, TASK_CONFIG_BODY)
        workspace = tmp_path / "ws"

        assert ensure_run_invariants(str(workspace), _build(workspace)) == "created"
        # A fresh build — the resume recomputes from the file, never reuses.
        assert ensure_run_invariants(str(workspace), _build(workspace)) == "validated"

    def test_edited_file_resume_refuses_naming_the_field(self, tmp_path, monkeypatch):
        """F-SCANH-1 (c): the mid-workspace operator edit is REFUSED.

        THE defect this repair exists for: editing
        ``configs/task_config.yaml`` between iterations changes what the
        LLM reads while ``_snapshot_task_config`` (first-writer-wins) keeps
        the stale snapshot — pre-fix, nothing refused the resume. Also the
        no-caching witness: a cached digest in the helper would return the
        first sha here and validate the edited file.

        Fails when: the rebuilt invariants carry the OLD sha (caching), the
        field leaves ``_CANONICAL`` (comparison skipped), or the refusal
        stops naming ``task_config_sha256``.
        """
        monkeypatch.chdir(tmp_path)
        _write_task_config(tmp_path, TASK_CONFIG_BODY)
        workspace = tmp_path / "ws"
        assert ensure_run_invariants(str(workspace), _build(workspace)) == "created"

        _write_task_config(tmp_path, EDITED_BODY)
        with pytest.raises(RunInvariantsViolation, match="task_config_sha256"):
            ensure_run_invariants(str(workspace), _build(workspace))

    def test_composed_run_pins_none_and_never_reads_the_file(self, tmp_path, monkeypatch):
        """F-SCANH-1 (d): a composed run's lock is untouched by the pin.

        Defect only this catches: the builder hashing the cwd task-config
        file for a COMPOSED run — whose task config arrives via
        ``bind_task_config`` and whose identity is owned by
        ``task_composition_fingerprint``. Pinning an unread file would (1)
        crash composed runs launched where no ``configs/task_config.yaml``
        exists, and (2) change composed lock bytes, breaking the
        omitted-when-``None`` byte-identity rule.

        Fails when: the composed build raises ``FileNotFoundError`` (it
        read the file — no config exists in this cwd BY CONSTRUCTION), the
        model carries a non-``None`` pin, or the serialized lock gains the
        key.
        """
        monkeypatch.chdir(tmp_path)  # deliberately NO configs/ dir here
        workspace = tmp_path / "ws"

        invariants, _ = build_run_invariants(
            resolved_data_scope=[4, 5, 6],
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(workspace),
            task_composition_fingerprint="f" * 64,
        )
        assert invariants.task_config_sha256 is None
        assert ensure_run_invariants(str(workspace), invariants) == "created"

        raw = json.loads((workspace / RUN_INVARIANTS_BASENAME).read_text())
        assert "task_config_sha256" not in raw

    def test_legacy_workspace_meets_pinning_build_and_fails_closed(self, tmp_path, monkeypatch):
        """F-SCANH-1 (e): a pre-pin lock refuses a pinning resume.

        Defect only this catches: a compatibility bypass — treating a lock
        with no ``task_config_sha256`` as matching ANY task config, which
        would exempt exactly the workspaces the defect lives in (every
        pre-fix workspace). The 12a composition-fingerprint precedent:
        refusal is intended, no bypass. The legacy artifact is a
        directly-constructed legacy-shaped ``RunInvariants`` (it IS the
        legacy artifact) written through the production writer; it differs
        from the pinning build ONLY in the pin, so the refusal is
        attributable to this field alone.

        Fails when: the canonical comparison starts special-casing a
        ``None`` locked pin as compatible, or the refusal stops naming
        ``task_config_sha256``.
        """
        monkeypatch.chdir(tmp_path)
        _write_task_config(tmp_path, TASK_CONFIG_BODY)
        workspace = tmp_path / "ws"

        pinning = _build(workspace)
        assert pinning.task_config_sha256 is not None
        legacy = pinning.model_copy(update={"task_config_sha256": None})
        write_run_invariants(str(workspace), legacy)
        # Fixture sanity: the artifact on disk IS legacy-shaped (no key).
        raw = json.loads((workspace / RUN_INVARIANTS_BASENAME).read_text())
        assert "task_config_sha256" not in raw

        with pytest.raises(RunInvariantsViolation, match="task_config_sha256"):
            ensure_run_invariants(str(workspace), pinning)
