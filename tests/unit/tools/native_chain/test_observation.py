"""One-byte snapshot verification, bounded evidence and legacy inspector parity."""

import hashlib
import json
from pathlib import Path

import pytest

from core.iteration_manifest import manifest_self_digest, verify_iteration_manifest
from tests.unit.scripts.test_inspect_run_state import _write_clean_chain_iter
from tools.native_chain.inspection import inspect_chain_iteration
from tools.native_chain.observation import ObservationBounds, observe_native_chain


def bounds(**changes):
    return ObservationBounds(
        final_iteration=2,
        input_max_bytes=16777216,
        max_observation_bytes=changes.get("max_observation_bytes", 1048576),
    )


def stamp(path):
    manifest = json.loads(path.read_text())
    if manifest["status"] == "completed":
        manifest["run_output_sha256"] = hashlib.sha256(
            Path(manifest["output_path"]).read_bytes()
        ).hexdigest()
    manifest["manifest_sha256"] = manifest_self_digest(manifest)
    path.write_text(json.dumps(manifest))
    return manifest


@pytest.mark.parametrize("mode", ["valid", "empty", "missing_hash", "mismatch", "legacy"])
def test_supplied_bytes_verifier_parity_without_reopen(tmp_path, mode):
    """Supplied bytes must preserve verdicts including empty bytes and missing-hash tamper."""
    output = tmp_path / "output"
    data = b"" if mode == "empty" else b"snapshot"
    output.write_bytes(data)
    manifest = {"status": "completed", "run_output_sha256": hashlib.sha256(data).hexdigest()}
    if mode == "mismatch":
        manifest["run_output_sha256"] = "0" * 64
    if mode in {"legacy", "missing_hash"}:
        manifest.pop("run_output_sha256")
    if mode != "legacy":
        manifest["manifest_sha256"] = manifest_self_digest(manifest)
    kwargs = dict(iter_idx=1, manifest_path="manifest", output_path=str(output))
    old = verify_iteration_manifest(manifest, **kwargs)
    output.unlink()
    assert verify_iteration_manifest(manifest, **kwargs, output_bytes=data) == old
    if mode == "legacy":
        assert not old.manifest_verified and not old.artifact_verified and old.problem is None
    elif mode in {"missing_hash", "mismatch"}:
        assert old.problem is not None
    else:
        assert old.manifest_verified and old.artifact_verified


def test_mixed_native_status_and_legacy_unverified_remain_distinct(tmp_path):
    first = _write_clean_chain_iter(tmp_path, 1)
    second = tmp_path / "iter_002"
    second.mkdir()
    (second / "manifest.json").write_text(json.dumps({"status": "no_records"}))
    stamp(second / "manifest.json")
    legacy = observe_native_chain(tmp_path, "native", bounds())
    assert legacy.checkpoints[0].integrity == "unverified"
    stamp(first / "manifest.json")
    observed = observe_native_chain(tmp_path, "native", bounds())
    assert [r.native_status for r in observed.checkpoints] == ["completed", "no_records"]
    assert all(r.manifest_verified for r in observed.checkpoints)
    assert observed.checkpoints[0].artifact_verified
    assert not observed.checkpoints[1].artifact_verified
    assert inspect_chain_iteration(second).status == "PARTIAL"
    manifest = json.loads((first / "manifest.json").read_text())
    Path(manifest["output_path"]).write_text("changed")
    assert observe_native_chain(tmp_path, "native", bounds()).checkpoints[0].integrity == "invalid"


def test_bounded_reader_refuses_symlink_escape_and_directory_flood(tmp_path):
    first = _write_clean_chain_iter(tmp_path, 1)
    manifest = stamp(first / "manifest.json")
    output = Path(manifest["output_path"])
    saved = output.read_bytes()
    output.unlink()
    target = tmp_path / "outside"
    target.write_bytes(saved)
    output.symlink_to(target)
    assert observe_native_chain(tmp_path, "native", bounds()).checkpoints[0].integrity == "invalid"
    assert (
        observe_native_chain(tmp_path, "native", bounds(max_observation_bytes=10)).availability
        == "limit_exceeded"
    )
    for i in range(20):
        (tmp_path / f"foreign{i}").touch()
    result = observe_native_chain(tmp_path, "native", bounds())
    assert result.availability == "limit_exceeded" and not result.checkpoints
