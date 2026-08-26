"""S2 / U5 (#258) — the launcher's write-once manifest publish and the explicit
replacement operation, at the ``write_manifest`` / ``prepare_iteration_dir``
boundary. The ``main()``-driven launch refusals live beside the other
``main()`` wiring tests in ``test_run_one_iteration.py``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from core.iteration_manifest import (
    MANIFEST_REPLACEMENT_KEY,
    ManifestAlreadyPublishedError,
    ManifestReplacementError,
    ManifestReplacementRequest,
    verify_iteration_manifest,
)
from sdsc_submission_scripts import run_one_iteration as runner

LAUNCHER = Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "run_one_iteration.py"


class _Result:
    """The minimum ``write_manifest`` reads off a tuner output."""

    def __init__(self, model_type: str = "punet", score: float = 0.7) -> None:
        self.model_type = model_type
        self.best_denoising_score = score
        self.completed_rounds = 1


def _write_artifact(iter_dir: str, run_name: str, payload: bytes) -> str:
    model_dir = os.path.join(iter_dir, "iteration_001", "punet")
    os.makedirs(model_dir, exist_ok=True)
    path = os.path.join(model_dir, f"run_output_{run_name}.json")
    with open(path, "wb") as f:
        f.write(payload)
    return path


class TestWriteOnce:
    def test_a_second_write_for_the_same_iteration_is_refused_by_name(self, tmp_path):
        """Before S2 ``write_manifest`` opened ``manifest.json`` with ``"w"``:
        a rerun silently replaced the committed handoff and regenerated its
        hash. Fails if the second call succeeds or the first bytes change."""
        iter_dir = str(tmp_path)
        runner.write_manifest(iter_dir, "iter_001", results=[])
        first = (tmp_path / "manifest.json").read_bytes()
        with pytest.raises(ManifestAlreadyPublishedError, match="write-once"):
            runner.write_manifest(iter_dir, "iter_001", results=[], crashed=True)
        assert (tmp_path / "manifest.json").read_bytes() == first

    def test_the_published_manifest_carries_a_verifying_self_digest(self, tmp_path):
        manifest = runner.write_manifest(str(tmp_path), "iter_001", results=[])
        on_disk = json.loads((tmp_path / "manifest.json").read_text())
        assert on_disk["manifest_sha256"] == manifest["manifest_sha256"]
        verdict = verify_iteration_manifest(
            on_disk, iter_idx=1, manifest_path=str(tmp_path / "manifest.json"), output_path=None
        )
        assert verdict.problem is None and verdict.manifest_verified


class TestReplacement:
    def test_replacement_hashes_the_new_artifact_and_records_the_previous_digests(self, tmp_path):
        """#258: the rerun's ``run_output_sha256`` is computed for the NEW
        artifact — never copied, never regenerated silently — and the
        previous manifest survives on disk with its digests recorded."""
        iter_dir = str(tmp_path)
        output_path = _write_artifact(iter_dir, "iter_001", b'{"first": true}')
        first = runner.write_manifest(iter_dir, "iter_001", [_Result()])
        first_bytes = (tmp_path / "manifest.json").read_bytes()
        assert first["run_output_sha256"] == hashlib.sha256(b'{"first": true}').hexdigest()

        with open(output_path, "wb") as f:
            f.write(b'{"second": true}')
        second = runner.write_manifest(
            iter_dir,
            "iter_001",
            [_Result()],
            replacement=ManifestReplacementRequest(reason="rerun after a host fault"),
        )
        assert second["run_output_sha256"] == hashlib.sha256(b'{"second": true}').hexdigest()
        prov = second[MANIFEST_REPLACEMENT_KEY]
        assert prov["replacement_reason"] == "rerun after a host fault"
        assert prov["previous_run_output_sha256"] == first["run_output_sha256"]
        assert prov["previous_manifest_sha256"] == hashlib.sha256(first_bytes).hexdigest()
        assert (tmp_path / prov["previous_manifest_path"]).read_bytes() == first_bytes
        on_disk = json.loads((tmp_path / "manifest.json").read_text())
        assert on_disk == second
        assert (
            verify_iteration_manifest(
                on_disk,
                iter_idx=1,
                manifest_path=str(tmp_path / "manifest.json"),
                output_path=output_path,
            ).problem
            is None
        )


class TestPrepareIterationDir:
    def test_fresh_slot_then_refusal_then_explicit_replacement(self, tmp_path):
        """The launch gate: fails if a committed iteration can be relaunched
        without the flag, or if the flag is accepted without a reason."""
        plan = runner.prepare_iteration_dir(
            str(tmp_path), 3, replace_iteration_manifest=False, replacement_reason=None
        )
        assert plan.run_name == "iter_003"
        assert plan.iter_dir == os.path.join(str(tmp_path), "iter_003")
        assert os.path.isdir(plan.iter_dir)
        assert plan.manifest_replacement is None

        runner.write_manifest(plan.iter_dir, "iter_003", results=[], crashed=True)
        with pytest.raises(ManifestAlreadyPublishedError, match="--replace_iteration_manifest"):
            runner.prepare_iteration_dir(
                str(tmp_path), 3, replace_iteration_manifest=False, replacement_reason=None
            )
        with pytest.raises(ManifestReplacementError, match="--replacement_reason"):
            runner.prepare_iteration_dir(
                str(tmp_path), 3, replace_iteration_manifest=True, replacement_reason=" "
            )
        with pytest.raises(ManifestReplacementError, match="without --replace_iteration_manifest"):
            runner.prepare_iteration_dir(
                str(tmp_path), 3, replace_iteration_manifest=False, replacement_reason="why"
            )
        plan2 = runner.prepare_iteration_dir(
            str(tmp_path), 3, replace_iteration_manifest=True, replacement_reason="operator rerun"
        )
        assert plan2.manifest_replacement is not None
        assert plan2.manifest_replacement.reason == "operator rerun"

    def test_replacement_with_nothing_to_replace_is_refused(self, tmp_path):
        with pytest.raises(ManifestReplacementError, match="nothing to replace"):
            runner.prepare_iteration_dir(
                str(tmp_path), 1, replace_iteration_manifest=True, replacement_reason="x"
            )

    def test_matrix_f_auto_resume_never_replaces_a_valid_manifest(self, tmp_path):
        """#258 refinement, row F (+ PLANT TARGET): a completed,
        integrity-bearing manifest is immutable to auto-resume — the naive
        auto-replace-anything rule turns this RED. No set-aside file may
        appear and the bytes must be untouched."""
        iter_dir = os.path.join(str(tmp_path), "iter_001")
        os.makedirs(iter_dir)
        _write_artifact(iter_dir, "iter_001", b'{"ok": true}')
        runner.write_manifest(iter_dir, "iter_001", [_Result()])
        first = open(os.path.join(iter_dir, "manifest.json"), "rb").read()
        with pytest.raises(ManifestAlreadyPublishedError):
            runner.prepare_iteration_dir(
                str(tmp_path),
                1,
                replace_iteration_manifest=False,
                replacement_reason=None,
                auto_resume_recovery=True,
            )
        assert open(os.path.join(iter_dir, "manifest.json"), "rb").read() == first
        assert not [n for n in os.listdir(iter_dir) if n.startswith("manifest.replaced.")]

    def test_auto_resume_classifies_only_the_two_terminal_states(self, tmp_path):
        """#258 refinement: failed/no_records → a recognizable replacement
        request built by the LAUNCHER'S classification; a fresh slot → no
        replacement. The publish layer never inspects a status."""
        failed_dir = os.path.join(str(tmp_path), "iter_002")
        os.makedirs(failed_dir)
        runner.write_manifest(failed_dir, "iter_002", results=[], crashed=True)
        plan = runner.prepare_iteration_dir(
            str(tmp_path),
            2,
            replace_iteration_manifest=False,
            replacement_reason=None,
            auto_resume_recovery=True,
        )
        assert plan.manifest_replacement is not None
        assert plan.manifest_replacement.reason.startswith("auto_resume recovery")
        assert "'failed'" in plan.manifest_replacement.reason

        nr_dir = os.path.join(str(tmp_path), "iter_003")
        os.makedirs(nr_dir)
        runner.write_manifest(nr_dir, "iter_003", results=[])
        plan3 = runner.prepare_iteration_dir(
            str(tmp_path),
            3,
            replace_iteration_manifest=False,
            replacement_reason=None,
            auto_resume_recovery=True,
        )
        assert plan3.manifest_replacement is not None
        assert "'no_records'" in plan3.manifest_replacement.reason

        plan4 = runner.prepare_iteration_dir(
            str(tmp_path),
            4,
            replace_iteration_manifest=False,
            replacement_reason=None,
            auto_resume_recovery=True,
        )
        assert plan4.manifest_replacement is None


class TestLauncherReachability:
    def test_every_manifest_write_in_the_launcher_passes_the_replacement(self):
        """MUTATION TARGET: one crash-path call site dropping ``replacement=``.
        That branch would then hit the write-once refusal at publish time —
        loud, but AFTER the work — instead of honouring the operator's
        request. Checked per AST call node, never by substring."""
        tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
        calls, missing = 0, []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "write_manifest":
                continue
            calls += 1
            if "replacement" not in {kw.arg for kw in node.keywords}:
                missing.append(node.lineno)
        assert calls >= 7, f"expected every manifest branch; found {calls}"
        assert missing == [], f"write_manifest called without replacement= at lines {missing}"

    def test_the_launcher_never_writes_a_manifest_around_the_authority(self):
        """MUTATION TARGET: restoring ``json.dump(manifest, f, indent=2)``.
        Code lines only — the explanation above quotes the old call."""
        code = [
            ln
            for ln in LAUNCHER.read_text(encoding="utf-8").splitlines()
            if not ln.strip().startswith("#")
        ]
        joined = "\n".join(code)
        assert "json.dump(manifest" not in joined
        assert 'open(manifest_path, "w")' not in joined
        assert "publish_iteration_manifest(iter_dir, manifest, replacement=replacement)" in joined
