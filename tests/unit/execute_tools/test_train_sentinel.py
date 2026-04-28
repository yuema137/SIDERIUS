"""
Phase 6.7 Commit 3 regression-guard for the producer-side training sentinel.

Targets ``execute_tools.train_engine_sandbox._save_with_sentinel``, which
implements Fix 3's atomic ``torch.save`` + ``_OK_<exp_id>`` write. The
sentinel is the contract Commit 4's orchestrator depends on to distinguish
silent training crashes from genuine inference-side failures, so the
**atomicity** property — sentinel exists if and only if torch.save
returned successfully — is what these tests pin.

Three branches:

1. **Happy path**: ``torch.save`` succeeds → sentinel is written, named
   ``_OK_<exp_id>``, sibling of ``save_path``, zero bytes.
2. **Save fails**: ``torch.save`` raises → control flow never reaches
   the sentinel write, so no orphan ``_OK_*`` is left behind. (The
   exception is allowed to propagate; that is the desired behaviour.)
3. **Filename convention**: sentinel name is ``_OK_<exp_id>``, lives
   beside the .pth in ``cached_models/`` — must match what
   ``execute_tools.inference_single._assert_training_sentinel`` checks
   for and what Commit 4 will check for in the orchestrator.
"""
from __future__ import annotations

import os

import pytest

from execute_tools.train_engine_sandbox import _save_with_sentinel


class TestSaveWithSentinelAtomicity:

    def test_sentinel_written_on_successful_save(self, tmp_path, monkeypatch):
        # Stub torch.save to a plain file write so we don't depend on a
        # real state_dict — we're testing the helper's control flow, not
        # torch's serialiser. The sentinel must exist after the call.
        save_path = str(tmp_path / "model.pth")

        def fake_save(state_dict, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 16)

        import execute_tools.train_engine_sandbox as tes
        monkeypatch.setattr(tes.torch, "save", fake_save)

        _save_with_sentinel({"w": "stub"}, save_path, "exp_001")

        assert os.path.exists(save_path)
        sentinel = tmp_path / "_OK_exp_001"
        assert sentinel.exists()
        assert sentinel.stat().st_size == 0  # zero-byte sentinel

    def test_sentinel_not_written_when_save_raises(self, tmp_path, monkeypatch):
        # The atomic guarantee: torch.save raising must propagate AND
        # leave no orphan sentinel behind. A leftover _OK_ would defeat
        # Commit 4's whole point — the orchestrator would route a
        # silent training crash as a successful train.
        save_path = str(tmp_path / "model.pth")

        def fake_save(state_dict, path):
            raise RuntimeError("simulated CUDA OOM during save")

        import execute_tools.train_engine_sandbox as tes
        monkeypatch.setattr(tes.torch, "save", fake_save)

        with pytest.raises(RuntimeError, match="simulated CUDA OOM"):
            _save_with_sentinel({"w": "stub"}, save_path, "exp_002")

        sentinel = tmp_path / "_OK_exp_002"
        assert not sentinel.exists(), (
            f"Sentinel {sentinel} was written even though torch.save "
            f"raised — atomicity guarantee broken."
        )

    def test_sentinel_path_is_sibling_of_save_path(self, tmp_path, monkeypatch):
        # The consumer side (inference_single._assert_training_sentinel)
        # builds its expected sentinel path as
        # os.path.join(os.path.dirname(model_path), f"_OK_{exp_id}").
        # The producer must mirror that exactly — any drift makes the
        # sentinel invisible to the preflight.
        cached_dir = tmp_path / "cached_models"
        cached_dir.mkdir()
        save_path = str(cached_dir / "model_punet_exp_xyz_agent.pth")

        def fake_save(state_dict, path):
            with open(path, "wb") as f:
                f.write(b"\x00")

        import execute_tools.train_engine_sandbox as tes
        monkeypatch.setattr(tes.torch, "save", fake_save)

        _save_with_sentinel({"w": "stub"}, save_path, "exp_xyz")

        # Sentinel lives in cached_models/, NOT in tmp_path/ root.
        assert (cached_dir / "_OK_exp_xyz").exists()
        assert not (tmp_path / "_OK_exp_xyz").exists()

    def test_sentinel_name_uses_exact_exp_id(self, tmp_path, monkeypatch):
        # Pin the naming convention literally — no slugging, no
        # truncation, no hashing. Whatever exp_id the trainer received
        # is what the sentinel filename embeds.
        save_path = str(tmp_path / "model.pth")

        def fake_save(state_dict, path):
            with open(path, "wb") as f:
                f.write(b"\x00")

        import execute_tools.train_engine_sandbox as tes
        monkeypatch.setattr(tes.torch, "save", fake_save)

        weird_exp_id = "round_03_explore_punet_v2"
        _save_with_sentinel({"w": "stub"}, save_path, weird_exp_id)
        assert (tmp_path / f"_OK_{weird_exp_id}").exists()
