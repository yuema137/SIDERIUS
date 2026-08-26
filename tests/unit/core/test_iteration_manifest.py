"""S2 / U5 (#258) — the iteration manifest authority (``core/iteration_manifest.py``).

Self-digest, write-once publish, the explicit replacement operation, and
the verification predicate shared by resume / per_file_best / the inspector.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from pydantic import ValidationError

from core.iteration_manifest import (
    MANIFEST_DIGEST_KEY,
    MANIFEST_REPLACEMENT_KEY,
    REPLACED_MANIFEST_PREFIX,
    RUN_OUTPUT_DIGEST_KEY,
    ManifestAlreadyPublishedError,
    ManifestReplacementError,
    ManifestReplacementRequest,
    classify_manifest_slot,
    manifest_self_digest,
    publish_iteration_manifest,
    verify_iteration_manifest,
)


def _completed_manifest(iter_dir: str, output_path: str) -> dict:
    return {
        "status": "completed",
        "iteration_dir": iter_dir,
        "output_path": output_path,
        "model_name": "punet",
        "best_score": 1.25,
        RUN_OUTPUT_DIGEST_KEY: hashlib.sha256(open(output_path, "rb").read()).hexdigest(),
    }


def _publish_completed(tmp_path, artifact: bytes = b'{"run": 1}') -> tuple[str, str, dict]:
    iter_dir = str(tmp_path / "iter_001")
    os.makedirs(iter_dir)
    output_path = os.path.join(iter_dir, "run_output_iter_001.json")
    with open(output_path, "wb") as f:
        f.write(artifact)
    manifest = _completed_manifest(iter_dir, output_path)
    publish_iteration_manifest(iter_dir, manifest)
    return iter_dir, output_path, manifest


def _reload(iter_dir: str) -> dict:
    with open(os.path.join(iter_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _rewrite(iter_dir: str, manifest: dict) -> None:
    """A hand edit — bypasses the producer on purpose."""
    with open(os.path.join(iter_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _verify(iter_dir: str, output_path: str | None):
    manifest = _reload(iter_dir)
    return verify_iteration_manifest(
        manifest,
        iter_idx=1,
        manifest_path=os.path.join(iter_dir, "manifest.json"),
        output_path=output_path,
    )


class TestPublish:
    def test_the_digest_covers_every_other_field_and_survives_the_round_trip(self, tmp_path):
        """DEFECT: a digest computed over the on-disk formatting, or one
        that includes itself, cannot be recomputed from the reloaded dict.
        Fails if the reloaded manifest does not verify."""
        iter_dir, output_path, published = _publish_completed(tmp_path)
        reloaded = _reload(iter_dir)
        assert reloaded[MANIFEST_DIGEST_KEY] == published[MANIFEST_DIGEST_KEY]
        assert manifest_self_digest(reloaded) == reloaded[MANIFEST_DIGEST_KEY]
        verdict = _verify(iter_dir, output_path)
        assert verdict.problem is None
        assert verdict.manifest_verified and verdict.artifact_verified

    def test_the_digest_is_independent_of_key_order(self):
        """DEFECT: an insertion-order-sensitive canonical form would make
        the SAME content verify or fail depending on which producer wrote
        it (S1 adds keys to the dict). Fails if the two digests differ."""
        a = {"status": "no_records", "iteration_dir": "x", "best_score": None}
        b = {"best_score": None, "iteration_dir": "x", "status": "no_records"}
        assert manifest_self_digest(a) == manifest_self_digest(b)

    def test_a_caller_supplied_digest_is_never_trusted(self, tmp_path):
        iter_dir = str(tmp_path / "iter_001")
        os.makedirs(iter_dir)
        manifest = {"status": "no_records", MANIFEST_DIGEST_KEY: "f" * 64}
        publish_iteration_manifest(iter_dir, manifest)
        assert _reload(iter_dir)[MANIFEST_DIGEST_KEY] != "f" * 64
        assert _verify(iter_dir, None).problem is None

    def test_a_second_publish_is_refused_by_name_and_leaves_the_first_intact(self, tmp_path):
        """#258 WRITE-ONCE. Fails if the second manifest lands, or if the
        refusal is a generic ``FileExistsError`` a caller could mistake for
        a temp-file collision."""
        iter_dir, _output_path, _ = _publish_completed(tmp_path)
        first = open(os.path.join(iter_dir, "manifest.json"), "rb").read()
        with pytest.raises(ManifestAlreadyPublishedError, match="write-once"):
            publish_iteration_manifest(iter_dir, {"status": "failed"})
        assert open(os.path.join(iter_dir, "manifest.json"), "rb").read() == first
        assert sorted(os.listdir(iter_dir)) == ["manifest.json", "run_output_iter_001.json"]


class TestReplacement:
    def test_replacement_sets_the_previous_manifest_aside_and_records_its_digests(self, tmp_path):
        """#258: the explicit operation keeps the previous manifest on
        disk, records ``replaced_at`` / ``replacement_reason`` /
        ``previous_manifest_sha256`` / ``previous_run_output_sha256``, and
        computes ``run_output_sha256`` for the NEW artifact rather than
        copying the old one. Fails on any of those."""
        iter_dir, output_path, first_manifest = _publish_completed(tmp_path, b'{"run": 1}')
        first_bytes = open(os.path.join(iter_dir, "manifest.json"), "rb").read()
        with open(output_path, "wb") as f:
            f.write(b'{"run": 2}')
        second = _completed_manifest(iter_dir, output_path)
        publish_iteration_manifest(
            iter_dir, second, replacement=ManifestReplacementRequest(reason="GPU fault rerun")
        )

        reloaded = _reload(iter_dir)
        prov = reloaded[MANIFEST_REPLACEMENT_KEY]
        assert prov["replacement_reason"] == "GPU fault rerun"
        assert prov["replaced_at"]
        assert prov["previous_manifest_sha256"] == hashlib.sha256(first_bytes).hexdigest()
        assert prov["previous_run_output_sha256"] == first_manifest[RUN_OUTPUT_DIGEST_KEY]
        assert prov["previous_manifest_status"] == "completed"
        set_aside = os.path.join(iter_dir, prov["previous_manifest_path"])
        assert prov["previous_manifest_path"].startswith(REPLACED_MANIFEST_PREFIX)
        assert open(set_aside, "rb").read() == first_bytes
        # Fresh hash for the NEW artifact — never regenerated silently, never copied.
        assert reloaded[RUN_OUTPUT_DIGEST_KEY] == hashlib.sha256(b'{"run": 2}').hexdigest()
        assert reloaded[RUN_OUTPUT_DIGEST_KEY] != first_manifest[RUN_OUTPUT_DIGEST_KEY]
        assert _verify(iter_dir, output_path).problem is None

    def test_an_empty_reason_is_refused(self):
        """The provenance must carry an explanation; whitespace is not one."""
        with pytest.raises(ValidationError):
            ManifestReplacementRequest(reason="   ")

    def test_the_launch_gate_classifies_both_refusals_by_name(self, tmp_path):
        """Fails if a launch into a committed iteration proceeds, or if a
        replacement with nothing to replace is accepted."""
        iter_dir = str(tmp_path / "iter_001")
        os.makedirs(iter_dir)
        with pytest.raises(ManifestReplacementError, match="nothing to replace"):
            classify_manifest_slot(iter_dir, ManifestReplacementRequest(reason="x"))
        classify_manifest_slot(iter_dir, None)  # a fresh slot is fine
        publish_iteration_manifest(iter_dir, {"status": "failed"})
        with pytest.raises(ManifestAlreadyPublishedError, match="--replace_iteration_manifest"):
            classify_manifest_slot(iter_dir, None)
        classify_manifest_slot(iter_dir, ManifestReplacementRequest(reason="rerun"))


class TestTamperMatrix:
    """Every row is RED; the message names the iteration and the offending path."""

    def test_a_manifest_field_edit_is_detected(self, tmp_path):
        """Undetected before S2: the artifact hash stayed consistent."""
        iter_dir, output_path, _ = _publish_completed(tmp_path)
        edited = _reload(iter_dir)
        edited["best_score"] = 99.0
        _rewrite(iter_dir, edited)
        verdict = _verify(iter_dir, output_path)
        assert verdict.problem is not None
        assert "manifest changed after publication" in verdict.problem
        assert os.path.join(iter_dir, "manifest.json") in verdict.problem

    def test_naive_hash_removal_is_detected_by_the_self_digest(self, tmp_path):
        iter_dir, output_path, _ = _publish_completed(tmp_path)
        edited = _reload(iter_dir)
        del edited[RUN_OUTPUT_DIGEST_KEY]
        _rewrite(iter_dir, edited)
        assert "manifest changed after publication" in (
            _verify(iter_dir, output_path).problem or ""
        )

    def test_hash_removal_with_a_recomputed_self_digest_is_a_tamper_not_legacy(self, tmp_path):
        """Undetected before S2: a hash-less manifest read as pre-V19 legacy
        and was admitted. Fails if this manifest is admitted as legacy."""
        iter_dir, output_path, _ = _publish_completed(tmp_path)
        edited = _reload(iter_dir)
        del edited[RUN_OUTPUT_DIGEST_KEY]
        edited.pop(MANIFEST_DIGEST_KEY)
        edited[MANIFEST_DIGEST_KEY] = manifest_self_digest(edited)
        _rewrite(iter_dir, edited)
        verdict = _verify(iter_dir, output_path)
        assert verdict.problem is not None
        assert RUN_OUTPUT_DIGEST_KEY in verdict.problem
        assert "not a legacy manifest" in verdict.problem

    def test_an_artifact_byte_change_is_still_detected(self, tmp_path):
        """RED today — kept. Fails if the artifact check was lost in the move."""
        iter_dir, output_path, published = _publish_completed(tmp_path)
        with open(output_path, "ab") as f:
            f.write(b"\n")
        verdict = _verify(iter_dir, output_path)
        assert verdict.problem is not None
        assert "committed artifact changed" in verdict.problem
        assert output_path in verdict.problem
        assert published[RUN_OUTPUT_DIGEST_KEY][:16] in verdict.problem

    def test_a_consistent_pair_rewrite_without_the_replacement_op_is_detected(self, tmp_path):
        """Undetected before S2: artifact + ``run_output_sha256`` rewritten
        together looked like a legitimate commit. The self-digest they did
        not recompute is what catches it."""
        iter_dir, output_path, _ = _publish_completed(tmp_path)
        with open(output_path, "wb") as f:
            f.write(b'{"run": "forged"}')
        edited = _reload(iter_dir)
        edited[RUN_OUTPUT_DIGEST_KEY] = hashlib.sha256(b'{"run": "forged"}').hexdigest()
        _rewrite(iter_dir, edited)
        verdict = _verify(iter_dir, output_path)
        assert verdict.problem is not None
        assert "manifest changed after publication" in verdict.problem

    def test_a_no_records_manifest_field_edit_is_detected(self, tmp_path):
        """The self-digest is verified even where no artifact exists."""
        iter_dir = str(tmp_path / "iter_001")
        os.makedirs(iter_dir)
        publish_iteration_manifest(iter_dir, {"status": "no_records", "best_score": None})
        edited = _reload(iter_dir)
        edited["best_score"] = 3.0
        _rewrite(iter_dir, edited)
        assert "manifest changed after publication" in (_verify(iter_dir, None).problem or "")


class TestLegacyStaysVisiblyUnverified:
    def test_a_pre_s2_manifest_with_only_the_artifact_hash_verifies_the_artifact(self, tmp_path):
        """Frozen contract: pre-S2 manifests keep working, artifact-verified
        but manifest-unverified. Fails if S2 refuses them."""
        iter_dir = str(tmp_path / "iter_001")
        os.makedirs(iter_dir)
        output_path = os.path.join(iter_dir, "run_output_iter_001.json")
        with open(output_path, "wb") as f:
            f.write(b"{}")
        _rewrite(iter_dir, _completed_manifest(iter_dir, output_path))
        verdict = _verify(iter_dir, output_path)
        assert verdict.problem is None
        assert verdict.artifact_verified is True
        assert verdict.manifest_verified is False

    def test_a_manifest_with_neither_digest_is_admitted_visibly_unverified(self, tmp_path):
        """Frozen contract (the pre-V19 shape): removal of BOTH digests is
        indistinguishable from legacy and is deliberately NOT a problem.
        Pinned so a future tightening is a decision, not a drift."""
        iter_dir = str(tmp_path / "iter_001")
        os.makedirs(iter_dir)
        output_path = os.path.join(iter_dir, "run_output_iter_001.json")
        with open(output_path, "wb") as f:
            f.write(b"{}")
        _rewrite(iter_dir, {"status": "completed", "output_path": output_path})
        verdict = _verify(iter_dir, output_path)
        assert verdict.problem is None
        assert verdict.artifact_verified is False
        assert verdict.manifest_verified is False
