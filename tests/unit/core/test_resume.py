"""
Unit tests for ``core/resume.py`` — Phase 6.8 Task 2 Commit 7.

Covers ``restore_prior_state`` against a synthetic chain workspace built
under ``tmp_path``. The fixture mirrors the real layout written by
``sdsc_submission_scripts/run_one_iteration.py``:

    {workspace}/
      iter_001/
        manifest.json
        iteration_001/
          {model}/
            run_output_iter_001.json
      iter_002/
        ...
      plugins/
        iter_001/{model}.py
        iter_002/{model}.py

The tests exercise:
  * happy path (clean 3-iter workspace),
  * current_iter == 1 (no-op, seeds verbatim),
  * missing manifest, missing run_output, missing plugin file,
  * malformed JSON, status != "completed", validation failures,
  * strict ascending order, seed-paths prepended verbatim, registry
    side effects.

A high-fidelity "pseudo-integration" test at the bottom builds a 2-iter
workspace using *real* plugin .py files (whose ``PLUGIN_CONFIG_CLASS`` /
``PLUGIN_MODEL_CLASS`` actually load) and verifies the four registry
surfaces are populated end-to-end. This stands in for the full pseudo-
integration test scheduled for Commit 12 (which exercises the entire
``run_workflow`` → manifest → restore loop).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap

import pytest

from core.resume import (
    RestoredState,
    ResumeError,
    _iter_run_name,
    restore_prior_state,
)
from core.sandbox_executor import get_plugin_dir

# ---------------------------------------------------------------------------
# Plugin source — kept in sync with the contract in ml_models/plugin_loader.py
# ---------------------------------------------------------------------------


def _plugin_src(model_type: str) -> str:
    return textwrap.dedent(f'''\
        import torch
        import torch.nn as nn
        from pydantic import BaseModel, Field

        PLUGIN_MODEL_TYPE = "{model_type}"

        class TestPluginConfig(BaseModel):
            model_type: str = "{model_type}"
            segmentation_size: int = Field(default=1000, ge=100)
            batch_size: int = 1

        class TestPluginModel(nn.Module):
            def __init__(self, config):
                super().__init__()
                self.proj = nn.Linear(config.segmentation_size, config.segmentation_size)
            def forward(self, x):
                out = self.proj(x.float())
                return out.unsqueeze(1).expand(-1, 256, -1)

        PLUGIN_CONFIG_CLASS = TestPluginConfig
        PLUGIN_MODEL_CLASS  = TestPluginModel
    ''')


# Minimum-required fields for HyperparamTuningOutput — others have defaults.
def _run_output_dict(run_name: str, model_type: str, score: float) -> dict:
    return {
        "run_name": run_name,
        "model_type": model_type,
        "file_index": 6,
        "status": "completed",
        "completed_rounds": 3,
        "total_attempts": 5,
        "best_exp_id": "exp_001",
        "best_denoising_score": score,
        "started_at": "2026-04-27T10:00:00",
        "finished_at": "2026-04-27T11:00:00",
    }


# ---------------------------------------------------------------------------
# Workspace builder
# ---------------------------------------------------------------------------


def _materialise_iter(
    workspace,
    iter_idx: int,
    model_type: str,
    score: float = 0.5,
    *,
    write_plugin: bool = True,
    plugin_body: str | None = None,
    run_output_overrides: dict | None = None,
    manifest_status: str = "completed",
):
    """Write one iter's manifest + run_output + plugin file under workspace.

    Returns the manifest dict written. ``plugin_body`` lets tests inject a
    deliberately broken plugin to exercise the validation-failure path.
    """
    run_name = _iter_run_name(iter_idx)
    iter_dir = workspace / run_name
    model_dir = iter_dir / "iteration_001" / model_type
    model_dir.mkdir(parents=True)

    output_path = model_dir / f"run_output_{run_name}.json"
    payload = _run_output_dict(run_name, model_type, score)
    if run_output_overrides:
        payload.update(run_output_overrides)
    output_path.write_text(json.dumps(payload, indent=2))

    manifest = {
        "status": manifest_status,
        "iteration_dir": str(iter_dir),
        "output_path": str(output_path),
        "model_name": model_type,
        "best_score": score,
        "completed_rounds": 3,
    }
    (iter_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if write_plugin:
        plugin_dir = workspace / "plugins" / run_name
        plugin_dir.mkdir(parents=True, exist_ok=True)
        body = plugin_body if plugin_body is not None else _plugin_src(model_type)
        (plugin_dir / f"{model_type}.py").write_text(body)

    return manifest


# ---------------------------------------------------------------------------
# Registry-snapshot fixture — prevent test pollution
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_registries():
    """Snapshot every registry surface + clear test model_types after the
    test. Keeps cross-test bleed from masking real bugs."""
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

    test_keys = (
        "resume_test_arch_a",
        "resume_test_arch_b",
        "resume_test_arch_c",
        "resume_test_arch_d",
    )
    yield
    for k in test_keys:
        MODEL_REGISTRY.pop(k, None)
        PLUGIN_CONFIG_REGISTRY.pop(k, None)
        PLUGIN_OUTPUT_TYPE_REGISTRY.pop(k, None)
        sys.modules.pop(f"siderius_plugin_{k}", None)
    bare = sys.modules.get("models_format_sandbox")
    pkg = sys.modules.get("ml_models.models_format_sandbox")
    if bare is not None and pkg is not None and bare is not pkg:
        for k in test_keys:
            bare.PLUGIN_CONFIG_REGISTRY.pop(k, None)


# ===========================================================================
# Trivial paths
# ===========================================================================


class TestTrivialPaths:
    def test_current_iter_1_returns_seeds_verbatim(self, tmp_path, isolated_registries):
        seeds = ["/seed/punet.json", "/seed/wavenet.json"]
        state = restore_prior_state(str(tmp_path), 1, seeds)
        assert isinstance(state, RestoredState)
        assert state.resolved_source_paths == seeds
        assert state.restored_plugins == []
        assert state.committed_iters == []

    def test_current_iter_1_does_not_require_existing_workspace(
        self, tmp_path, isolated_registries
    ):
        """An iter-1 launch may target a workspace that doesn't exist yet."""
        ws = tmp_path / "nonexistent_yet"
        state = restore_prior_state(str(ws), 1, [])
        assert state.resolved_source_paths == []

    def test_current_iter_below_one_raises(self, tmp_path, isolated_registries):
        with pytest.raises(ResumeError, match="current_iter must be >= 1"):
            restore_prior_state(str(tmp_path), 0, [])

    def test_workspace_does_not_exist_raises_for_iter_above_1(self, tmp_path, isolated_registries):
        ws = tmp_path / "missing"
        with pytest.raises(ResumeError, match="workspace does not exist"):
            restore_prior_state(str(ws), 2, [])


# ===========================================================================
# Clean 3-iter chain — happy path
# ===========================================================================


class TestCleanThreeIterChain:
    @pytest.fixture
    def workspace(self, tmp_path):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        _materialise_iter(tmp_path, 2, "resume_test_arch_b", 0.78)
        _materialise_iter(tmp_path, 3, "resume_test_arch_c", 0.82)
        return tmp_path

    def test_restores_all_prior_iters(self, workspace, isolated_registries):
        seeds = ["/seed/punet.json"]
        state = restore_prior_state(str(workspace), 4, seeds)
        assert state.committed_iters == [1, 2, 3]

    def test_resolved_paths_are_seeds_then_chronological(self, workspace, isolated_registries):
        seeds = ["/seed/punet.json", "/seed/wavenet.json"]
        state = restore_prior_state(str(workspace), 4, seeds)
        # Seeds first (in order), then iter outputs in ascending order.
        assert state.resolved_source_paths[:2] == seeds
        assert "iter_001" in state.resolved_source_paths[2]
        assert "iter_002" in state.resolved_source_paths[3]
        assert "iter_003" in state.resolved_source_paths[4]

    def test_restored_plugins_in_chronological_order(self, workspace, isolated_registries):
        state = restore_prior_state(str(workspace), 4, [])
        assert state.restored_plugins == [
            "resume_test_arch_a",
            "resume_test_arch_b",
            "resume_test_arch_c",
        ]

    def test_partial_restore_when_current_iter_in_middle(self, workspace, isolated_registries):
        """current_iter=3 should restore only iters 1 and 2."""
        state = restore_prior_state(str(workspace), 3, [])
        assert state.committed_iters == [1, 2]
        assert state.restored_plugins == [
            "resume_test_arch_a",
            "resume_test_arch_b",
        ]

    def test_registry_actually_populated(self, workspace, isolated_registries):
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.plugin_loader import (
            PLUGIN_OUTPUT_TYPE_REGISTRY,
            get_output_type,
        )

        restore_prior_state(str(workspace), 4, [])

        for mt in ("resume_test_arch_a", "resume_test_arch_b", "resume_test_arch_c"):
            assert mt in MODEL_REGISTRY, f"{mt} missing from MODEL_REGISTRY"
            assert mt in PLUGIN_CONFIG_REGISTRY, f"{mt} missing from PLUGIN_CONFIG_REGISTRY"
            # Default classifier output_type per the synthetic plugin.
            assert get_output_type(mt) == "classifier"

    def test_seeds_empty_list_works(self, workspace, isolated_registries):
        state = restore_prior_state(str(workspace), 4, [])
        # No seeds → resolved == prior outputs only.
        assert len(state.resolved_source_paths) == 3


# ===========================================================================
# Hostile-state branches
# ===========================================================================


class TestMissingManifest:
    def test_missing_manifest_raises(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        # Iter 2's dir exists but no manifest.json.
        (tmp_path / "iter_002" / "iteration_001").mkdir(parents=True)
        with pytest.raises(ResumeError, match=r"iter 002: manifest\.json not found"):
            restore_prior_state(str(tmp_path), 3, [])

    def test_iter_dir_entirely_missing_raises(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        # Iter 2 doesn't exist at all.
        with pytest.raises(ResumeError, match=r"iter 002: manifest"):
            restore_prior_state(str(tmp_path), 3, [])


class TestCorruptManifest:
    def test_malformed_manifest_json_raises(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        manifest_path = tmp_path / "iter_001" / "manifest.json"
        manifest_path.write_text("{not valid json")
        with pytest.raises(ResumeError, match=r"manifest.json is malformed"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_status_failed_raises(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            manifest_status="failed",
        )
        with pytest.raises(ResumeError, match="status='failed'"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_status_partial_raises(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            manifest_status="partial",
        )
        with pytest.raises(ResumeError, match="status='partial'"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_status_no_records_skips_cleanly(self, tmp_path, isolated_registries):
        """A no-records iter (gate-exhaustion or all-rounds-failed without
        crash) must be skipped silently — no plugin restored, output_path
        not appended, no error. This is the chain-fragility fix that lets
        a single dead-end iter not take out the rest of the chain."""
        # Materialise iter_001 with manifest.status="no_records" and no
        # run_output / no plugin file (matches what write_manifest emits
        # for empty results).
        run_name = _iter_run_name(1)
        iter_dir = tmp_path / run_name
        iter_dir.mkdir()
        (iter_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "no_records",
                    "iteration_dir": str(iter_dir),
                    "output_path": None,
                    "model_name": None,
                    "best_score": None,
                }
            )
        )

        # iter_002 also no-records — verify multiple consecutive skips.
        run_name_2 = _iter_run_name(2)
        iter_dir_2 = tmp_path / run_name_2
        iter_dir_2.mkdir()
        (iter_dir_2 / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "no_records",
                    "iteration_dir": str(iter_dir_2),
                    "output_path": None,
                    "model_name": None,
                    "best_score": None,
                }
            )
        )

        seeds = ["/seed/punet.json", "/seed/wavenet.json"]
        state = restore_prior_state(str(tmp_path), 3, seeds)

        # No plugin restored, no iter committed, only seeds in resolved paths.
        assert state.committed_iters == []
        assert state.restored_plugins == []
        assert state.resolved_source_paths == seeds

    def test_status_no_records_interleaved_with_completed(
        self,
        tmp_path,
        isolated_registries,
    ):
        """no_records iter sandwiched between two completed iters: the
        completed iters are absorbed normally, the middle iter is skipped."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        # iter_002 is no_records.
        run_name_2 = _iter_run_name(2)
        iter_dir_2 = tmp_path / run_name_2
        iter_dir_2.mkdir()
        (iter_dir_2 / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "no_records",
                    "iteration_dir": str(iter_dir_2),
                    "output_path": None,
                    "model_name": None,
                    "best_score": None,
                }
            )
        )
        _materialise_iter(tmp_path, 3, "resume_test_arch_c", 0.82)

        state = restore_prior_state(str(tmp_path), 4, ["/seed/punet.json"])

        # iters 1 and 3 committed, iter 2 skipped.
        assert state.committed_iters == [1, 3]
        assert state.restored_plugins == ["resume_test_arch_a", "resume_test_arch_c"]
        # Resolved paths: seed, iter_001 output, iter_003 output (no iter_002).
        assert len(state.resolved_source_paths) == 3
        assert state.resolved_source_paths[0] == "/seed/punet.json"
        assert "iter_001" in state.resolved_source_paths[1]
        assert "iter_003" in state.resolved_source_paths[2]

    def test_manifest_without_output_path_raises(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        manifest_path = tmp_path / "iter_001" / "manifest.json"
        m = json.loads(manifest_path.read_text())
        m.pop("output_path")
        manifest_path.write_text(json.dumps(m))
        with pytest.raises(ResumeError, match="no output_path"):
            restore_prior_state(str(tmp_path), 2, [])


class TestCorruptRunOutput:
    def test_run_output_file_missing_raises(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        # Delete the run_output file but leave the manifest pointing at it.
        run_output = (
            tmp_path
            / "iter_001"
            / "iteration_001"
            / "resume_test_arch_a"
            / "run_output_iter_001.json"
        )
        run_output.unlink()
        with pytest.raises(ResumeError, match=r"output_path .* does not exist"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_malformed_run_output_json_raises(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        run_output = (
            tmp_path
            / "iter_001"
            / "iteration_001"
            / "resume_test_arch_a"
            / "run_output_iter_001.json"
        )
        run_output.write_text("{this is not json")
        with pytest.raises(ResumeError, match="run_output failed validation"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_run_output_validation_error_raises(self, tmp_path, isolated_registries):
        """A JSON object that's structurally valid but missing required
        fields → Pydantic ValidationError → ResumeError."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        run_output = (
            tmp_path
            / "iter_001"
            / "iteration_001"
            / "resume_test_arch_a"
            / "run_output_iter_001.json"
        )
        run_output.write_text(
            json.dumps({"run_name": "iter_001"})
        )  # missing model_type, status, ...
        with pytest.raises(ResumeError, match="run_output failed validation"):
            restore_prior_state(str(tmp_path), 2, [])


# ===========================================================================
# Plugin-file edge cases
# ===========================================================================


class TestPluginFileEdgeCases:
    def test_missing_plugin_file_warns_and_continues(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            write_plugin=False,
        )
        with pytest.warns(UserWarning, match="plugin file not found"):
            state = restore_prior_state(str(tmp_path), 2, [])
        # Source path is still kept — JSON record is the contract.
        assert len(state.resolved_source_paths) == 1
        assert state.committed_iters == [1]
        # But the model_type is NOT in restored_plugins.
        assert state.restored_plugins == []

    def test_invalid_plugin_file_warns_and_continues(self, tmp_path, isolated_registries):
        """A .py file is on disk but missing PLUGIN_MODEL_TYPE etc — _load_plugin
        returns None. Resume should warn loudly and continue, not raise."""
        broken_body = "# I am not a valid plugin\nx = 1\n"
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            plugin_body=broken_body,
        )
        with pytest.warns(UserWarning, match="failed _load_plugin validation"):
            state = restore_prior_state(str(tmp_path), 2, [])
        assert state.committed_iters == [1]
        assert state.restored_plugins == []

    def test_some_plugins_present_some_missing_partial_restore(self, tmp_path, isolated_registries):
        """Iter 1 plugin missing, iter 2 plugin present → both committed_iters,
        only iter 2's model_type in restored_plugins."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", write_plugin=False)
        _materialise_iter(tmp_path, 2, "resume_test_arch_b")
        with pytest.warns(UserWarning):
            state = restore_prior_state(str(tmp_path), 3, [])
        assert state.committed_iters == [1, 2]
        assert state.restored_plugins == ["resume_test_arch_b"]
        assert len(state.resolved_source_paths) == 2


# ===========================================================================
# Pseudo-integration — high-fidelity 2-iter chain
# ===========================================================================
#
# This stands in for the full pseudo-integration test scheduled for Commit 12.
# It builds a 2-iter chain workspace using *real* plugin files that load
# successfully, then verifies that restore_prior_state populates all four
# registry surfaces end-to-end, in the exact order a real chain would.
# ===========================================================================


class TestPseudoIntegrationTwoIterChain:
    def test_two_iter_pseudo_run_repopulates_model_registry(self, tmp_path, isolated_registries):
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.plugin_loader import (
            PLUGIN_OUTPUT_TYPE_REGISTRY,
            get_output_type,
        )

        # Materialise a clean 2-iter chain with two distinct plugins. Mirrors
        # what `python run_one_iteration.py --iteration 1` then `... --iteration 2`
        # would have written to disk (without actually running run_workflow).
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", score=0.71)
        _materialise_iter(tmp_path, 2, "resume_test_arch_b", score=0.84)

        # Sanity check: nothing is registered yet.
        assert "resume_test_arch_a" not in MODEL_REGISTRY
        assert "resume_test_arch_b" not in MODEL_REGISTRY

        # Now simulate iter 3's process startup: a fresh interpreter would
        # call restore_prior_state(workspace, 3, seeds) before run_workflow.
        seeds = []
        state = restore_prior_state(str(tmp_path), 3, seeds)

        # All four registry surfaces should be populated for both prior iters.
        for mt in ("resume_test_arch_a", "resume_test_arch_b"):
            assert mt in MODEL_REGISTRY, (
                f"{mt} missing from MODEL_REGISTRY — chain runner would fail "
                f"with 'Unknown model_type' at any cross-iter dispatch"
            )
            assert mt in PLUGIN_CONFIG_REGISTRY
            assert mt in PLUGIN_OUTPUT_TYPE_REGISTRY
            assert get_output_type(mt) == "classifier"

        # Bare-name mirror — only meaningful when the bare/packaged identities
        # are distinct objects (the subprocess training path's import shape).
        bare = sys.modules.get("models_format_sandbox")
        pkg = sys.modules.get("ml_models.models_format_sandbox")
        if bare is not None and pkg is not None and bare is not pkg:
            for mt in ("resume_test_arch_a", "resume_test_arch_b"):
                assert mt in bare.PLUGIN_CONFIG_REGISTRY, (
                    f"bare-name mirror missing {mt} — subprocess training path "
                    f"would fail to find the config class"
                )

        # Source paths in chronological order.
        assert state.committed_iters == [1, 2]
        assert state.restored_plugins == ["resume_test_arch_a", "resume_test_arch_b"]
        assert len(state.resolved_source_paths) == 2
        assert "iter_001" in state.resolved_source_paths[0]
        assert "iter_002" in state.resolved_source_paths[1]

    def test_plugin_dir_layout_uses_get_plugin_dir_helper(self, tmp_path, isolated_registries):
        """Pin the layout contract — restore must read from the same path the
        sandbox executor and _register_plugin write to."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")

        expected = get_plugin_dir(str(tmp_path), "iter_001")
        plugin_file = os.path.join(expected, "resume_test_arch_a.py")
        assert os.path.isfile(plugin_file), (
            f"materialiser wrote the plugin somewhere other than "
            f"get_plugin_dir({tmp_path!r}, 'iter_001'); the test fixture is "
            f"out of sync with the production layout helper"
        )

        state = restore_prior_state(str(tmp_path), 2, [])
        assert state.restored_plugins == ["resume_test_arch_a"]


# ===========================================================================
# Cross-iter knowledge persistence (load_latest_knowledge)
# See docs/Consistent_growing_vocab_list.md.
# ===========================================================================

from core.committed_digests import read_committed_digests
from core.resume import _interpretation_path, project_knowledge


# Step 09.5a C1 — the four carried-state loaders became PURE projections over
# one shared committed-digest read (core/committed_digests.py). These shims keep
# every assertion below unchanged while exercising the real production
# composition: one read, then the projection under test.
def load_latest_knowledge(workspace, current_iter, committed_iters):
    return project_knowledge(read_committed_digests(workspace, current_iter, committed_iters))


def _write_interp_digest(
    workspace,
    iter_idx: int,
    *,
    runtime_vocab: list | None = None,
    key_findings: list[str] | None = None,
    raw_text: str | None = None,
):
    """Write a synthetic ``interpretation_iter_NNN.json`` under the chain layout.

    ``raw_text`` lets a test inject malformed JSON deliberately; otherwise the
    given vocab + findings are serialised. Only the fields the loader reads are
    required — the rest of ``InterpretationOutput`` is irrelevant here.
    """
    path = workspace / _interpretation_path("", iter_idx).lstrip(os.sep)
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw_text is not None:
        path.write_text(raw_text)
        return path
    payload = {
        "runtime_vocab": runtime_vocab or [],
        "key_findings": key_findings or [],
    }
    path.write_text(json.dumps(payload))
    return path


def _vocab_entry(
    name: str,
    *,
    kind: str = "feature",
    tier: str = "candidate",
    seen_in_runs: list[str] | None = None,
) -> dict:
    """Minimum-required dict that validates as VocabEntry."""
    return {
        "name": name,
        "kind": kind,
        "description": f"test entry {name}",
        "tier": tier,
        "seen_in_runs": list(seen_in_runs or []),
    }


class TestLoadLatestKnowledge:
    """Read-only loader behaviour — no plugin / manifest involvement."""

    def test_iter1_returns_empty(self, tmp_path):
        """current_iter == 1 short-circuits; no disk read attempted."""
        vocab, findings = load_latest_knowledge(str(tmp_path), 1, [])
        assert vocab == []
        assert findings == []

    def test_picks_latest_runtime_vocab(self, tmp_path):
        """Latest committed iter wins on runtime_vocab (not concatenation)."""
        _write_interp_digest(
            tmp_path,
            1,
            runtime_vocab=[_vocab_entry("feat_iter1")],
            key_findings=["finding_iter1"],
        )
        _write_interp_digest(
            tmp_path,
            2,
            runtime_vocab=[_vocab_entry("feat_iter2_a"), _vocab_entry("feat_iter2_b")],
            key_findings=["finding_iter2"],
        )
        vocab, _findings = load_latest_knowledge(str(tmp_path), 3, [1, 2])
        names = sorted(v.name for v in vocab)
        assert names == ["feat_iter2_a", "feat_iter2_b"]

    def test_accumulates_findings_chronologically(self, tmp_path):
        """Union across iters; first-occurrence wins on dedup."""
        _write_interp_digest(
            tmp_path,
            1,
            runtime_vocab=[_vocab_entry("v")],
            key_findings=["A", "B"],
        )
        _write_interp_digest(
            tmp_path,
            2,
            runtime_vocab=[_vocab_entry("v")],
            key_findings=["B", "C"],
        )
        _vocab, findings = load_latest_knowledge(str(tmp_path), 3, [1, 2])
        assert findings == ["A", "B", "C"]

    def test_skips_missing_digest_with_warning(self, tmp_path):
        """Iter committed but interp digest missing → warn + continue."""
        _write_interp_digest(
            tmp_path,
            1,
            runtime_vocab=[_vocab_entry("feat_iter1")],
            key_findings=["finding_iter1"],
        )
        # iter_002 has no digest written.
        with pytest.warns(UserWarning, match="iter 002.*digest not found"):
            vocab, findings = load_latest_knowledge(str(tmp_path), 3, [1, 2])
        # iter_001's vocab still survives.
        assert [v.name for v in vocab] == ["feat_iter1"]
        assert findings == ["finding_iter1"]

    def test_skips_malformed_json_with_warning(self, tmp_path):
        """Malformed digest → warn + continue with the rest."""
        _write_interp_digest(
            tmp_path,
            1,
            runtime_vocab=[_vocab_entry("feat_iter1")],
            key_findings=["finding_iter1"],
        )
        _write_interp_digest(tmp_path, 2, raw_text="{not valid json")
        with pytest.warns(UserWarning, match="iter 002.*cannot read"):
            vocab, findings = load_latest_knowledge(str(tmp_path), 3, [1, 2])
        assert [v.name for v in vocab] == ["feat_iter1"]
        assert findings == ["finding_iter1"]

    def test_drops_malformed_vocab_entries_with_warning(self, tmp_path):
        """Per-entry validation failure → drop that entry, keep the rest."""
        _write_interp_digest(
            tmp_path,
            1,
            runtime_vocab=[
                _vocab_entry("good_a"),
                {"name": "bad_entry"},  # missing required fields → ValidationError
                _vocab_entry("good_b"),
            ],
            key_findings=["finding_iter1"],
        )
        with pytest.warns(UserWarning, match="dropped malformed runtime_vocab entry"):
            vocab, findings = load_latest_knowledge(str(tmp_path), 2, [1])
        names = sorted(v.name for v in vocab)
        assert names == ["good_a", "good_b"]
        assert findings == ["finding_iter1"]

    def test_seen_in_runs_preserved_verbatim(self, tmp_path):
        """Loader must not mutate seen_in_runs — preservation is contract.

        See docs/Consistent_growing_vocab_list.md §2.1: build_runtime_vocab
        is the only place seen_in_runs grows, via the proposed_candidates
        channel inside the next iter's interp call.
        """
        _write_interp_digest(
            tmp_path,
            1,
            runtime_vocab=[
                _vocab_entry(
                    "carry_me",
                    seen_in_runs=["iter_001"],
                )
            ],
            key_findings=[],
        )
        vocab, _findings = load_latest_knowledge(str(tmp_path), 2, [1])
        assert len(vocab) == 1
        assert vocab[0].seen_in_runs == ["iter_001"]


class TestRestorePriorStateKnowledgeCarryOver:
    """Full-stack: restore_prior_state populates the new RestoredState fields."""

    def test_iter1_leaves_new_fields_empty(self, tmp_path, isolated_registries):
        state = restore_prior_state(str(tmp_path), 1, [])
        assert state.runtime_vocab == []
        assert state.accumulated_key_findings == []
        # V8 Domain 1 — negative-feedback fields also empty at iter 1
        assert state.accumulated_physical_rejections == []
        assert state.accumulated_gate_exhaustions == []

    def test_populates_new_fields_from_prior_iters(self, tmp_path, isolated_registries):
        """Mock 2-iter workspace: manifests + run_outputs + interp digests.

        After restore, RestoredState.runtime_vocab should reflect iter_002's
        digest and accumulated_key_findings should be the chronological
        union of both iters' findings.
        """
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        _materialise_iter(tmp_path, 2, "resume_test_arch_b", 0.78)
        _write_interp_digest(
            tmp_path,
            1,
            runtime_vocab=[_vocab_entry("feat_iter1", seen_in_runs=["iter_001"])],
            key_findings=["lesson_iter1"],
        )
        _write_interp_digest(
            tmp_path,
            2,
            runtime_vocab=[
                _vocab_entry("feat_iter1", seen_in_runs=["iter_001", "iter_002"]),
                _vocab_entry("feat_iter2", seen_in_runs=["iter_002"]),
            ],
            key_findings=["lesson_iter2"],
        )
        state = restore_prior_state(str(tmp_path), 3, [])
        assert state.committed_iters == [1, 2]
        names = sorted(v.name for v in state.runtime_vocab)
        assert names == ["feat_iter1", "feat_iter2"]
        # iter_002's seen_in_runs (the latest) wins as a whole.
        feat_iter1 = next(v for v in state.runtime_vocab if v.name == "feat_iter1")
        assert feat_iter1.seen_in_runs == ["iter_001", "iter_002"]
        assert state.accumulated_key_findings == ["lesson_iter1", "lesson_iter2"]


# ===========================================================================
# Cross-iter knowledge-cache persistence (Commit 6.1.a — Rev 8.3)
# See docs/audit_and_optimize_token_usage_and_growth.md Rev 8.3 changelog.
# ===========================================================================

from core.resume import project_knowledge_cache


# Step 09.5a C1 — the four carried-state loaders became PURE projections over
# one shared committed-digest read (core/committed_digests.py). These shims keep
# every assertion below unchanged while exercising the real production
# composition: one read, then the projection under test.
def load_latest_knowledge_cache(workspace, current_iter, committed_iters):
    return project_knowledge_cache(read_committed_digests(workspace, current_iter, committed_iters))


def _write_interp_digest_with_cache(
    workspace,
    iter_idx: int,
    *,
    model_knowledge_cache: dict | None = None,
    runtime_vocab: list | None = None,
    key_findings: list[str] | None = None,
):
    """Like _write_interp_digest but adds the model_knowledge_cache field.

    Older digests (written before Commit 6.1.a) lack the key entirely; this
    helper supports both regimes — pass ``model_knowledge_cache=None`` to
    omit the field, or a dict to include it.
    """
    path = workspace / _interpretation_path("", iter_idx).lstrip(os.sep)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "runtime_vocab": runtime_vocab or [],
        "key_findings": key_findings or [],
    }
    if model_knowledge_cache is not None:
        payload["model_knowledge_cache"] = model_knowledge_cache
    path.write_text(json.dumps(payload))
    return path


def _cache_entry(score: float, n_rounds: int = 5) -> dict:
    """Minimal shape for a model_knowledge_cache value — only fields a
    consumer might check are populated."""
    return {
        "key_findings": [f"summary at score {score}"],
        "best_config_analysis": "no notable issues",
        "_stats": {
            "best_denoising_score": score,
            "n_rounds_completed": n_rounds,
        },
    }


class TestLoadLatestKnowledgeCache:
    """Direct loader tests — parallel to TestLoadLatestKnowledge."""

    def test_iter1_returns_empty_dict(self, tmp_path):
        """current_iter <= 1 short-circuits; no disk read attempted."""
        cache = load_latest_knowledge_cache(str(tmp_path), 1, [])
        assert cache == {}

    def test_empty_committed_iters_returns_empty(self, tmp_path):
        cache = load_latest_knowledge_cache(str(tmp_path), 5, [])
        assert cache == {}

    def test_picks_latest_cache(self, tmp_path):
        """3-iter chain: iter_003's cache wins (latest-wins, NOT union)."""
        _write_interp_digest_with_cache(
            tmp_path,
            1,
            model_knowledge_cache={"a": _cache_entry(0.5)},
        )
        _write_interp_digest_with_cache(
            tmp_path,
            2,
            model_knowledge_cache={"b": _cache_entry(0.6)},
        )
        _write_interp_digest_with_cache(
            tmp_path,
            3,
            model_knowledge_cache={"c": _cache_entry(0.7)},
        )
        cache = load_latest_knowledge_cache(str(tmp_path), 4, [1, 2, 3])
        assert sorted(cache.keys()) == ["c"]
        # No leakage from older iters (proves latest-wins, not union).
        assert "a" not in cache and "b" not in cache

    def test_legacy_digest_without_cache_key_skipped(self, tmp_path):
        """Pre-Commit-6.1.a digests have no model_knowledge_cache key — the
        loader must leave the running cache untouched and continue."""
        _write_interp_digest_with_cache(
            tmp_path,
            1,
            model_knowledge_cache={"early": _cache_entry(0.5)},
        )
        # iter_002 digest exists but lacks the cache key (legacy shape).
        _write_interp_digest_with_cache(
            tmp_path,
            2,
            model_knowledge_cache=None,
        )
        cache = load_latest_knowledge_cache(str(tmp_path), 3, [1, 2])
        # iter_001's cache must survive — iter_002's missing key is treated
        # as "no update", not "explicit empty".
        assert sorted(cache.keys()) == ["early"]

    def test_explicit_empty_overwrites(self, tmp_path):
        """An on-disk empty dict IS a valid latest snapshot (operator may have
        evicted everything via _cap_knowledge_cache). Distinguished from a
        missing key per the loader docstring."""
        _write_interp_digest_with_cache(
            tmp_path,
            1,
            model_knowledge_cache={"early": _cache_entry(0.5)},
        )
        _write_interp_digest_with_cache(
            tmp_path,
            2,
            model_knowledge_cache={},
        )
        cache = load_latest_knowledge_cache(str(tmp_path), 3, [1, 2])
        assert cache == {}

    def test_skips_missing_digest_with_warning(self, tmp_path):
        """Iter committed but interp digest missing → warn + continue."""
        _write_interp_digest_with_cache(
            tmp_path,
            1,
            model_knowledge_cache={"a": _cache_entry(0.5)},
        )
        # iter_002 has no digest written.
        with pytest.warns(UserWarning, match="iter 002.*digest not found"):
            cache = load_latest_knowledge_cache(str(tmp_path), 3, [1, 2])
        # iter_001's cache still survives.
        assert sorted(cache.keys()) == ["a"]

    def test_skips_malformed_json_with_warning(self, tmp_path):
        """Malformed digest → warn + continue with the rest."""
        _write_interp_digest_with_cache(
            tmp_path,
            1,
            model_knowledge_cache={"a": _cache_entry(0.5)},
        )
        # Write a corrupt iter_002 digest manually.
        bad_path = tmp_path / _interpretation_path("", 2).lstrip(os.sep)
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("{not valid json")
        with pytest.warns(UserWarning, match="iter 002.*cannot read"):
            cache = load_latest_knowledge_cache(str(tmp_path), 3, [1, 2])
        assert sorted(cache.keys()) == ["a"]

    def test_returns_defensive_copy(self, tmp_path):
        """Mutating the returned dict must not alter on-disk state if
        re-read. Defends against caller-side mutation leaking back."""
        _write_interp_digest_with_cache(
            tmp_path,
            1,
            model_knowledge_cache={"a": _cache_entry(0.5)},
        )
        cache_a = load_latest_knowledge_cache(str(tmp_path), 2, [1])
        cache_a["mutated"] = {"sentinel": True}
        cache_b = load_latest_knowledge_cache(str(tmp_path), 2, [1])
        assert "mutated" not in cache_b


class TestRestorePriorStateKnowledgeCacheCarryOver:
    """Full-stack: restore_prior_state populates RestoredState.model_knowledge_cache."""

    def test_iter1_leaves_cache_empty(self, tmp_path, isolated_registries):
        state = restore_prior_state(str(tmp_path), 1, [])
        assert state.model_knowledge_cache == {}

    def test_populates_cache_from_latest_iter(self, tmp_path, isolated_registries):
        """2-iter chain: state.model_knowledge_cache reflects iter_002's
        cache verbatim — the field a fresh chain subprocess reads to seed
        its in-iter cache before the per_model loop runs."""
        _materialise_iter(tmp_path, 1, "resume_cache_arch_a", 0.71)
        _materialise_iter(tmp_path, 2, "resume_cache_arch_b", 0.78)
        _write_interp_digest_with_cache(
            tmp_path,
            1,
            model_knowledge_cache={"resume_cache_arch_a": _cache_entry(0.71)},
        )
        _write_interp_digest_with_cache(
            tmp_path,
            2,
            model_knowledge_cache={
                "resume_cache_arch_a": _cache_entry(0.71),
                "resume_cache_arch_b": _cache_entry(0.78),
            },
        )
        state = restore_prior_state(str(tmp_path), 3, [])
        assert state.committed_iters == [1, 2]
        assert sorted(state.model_knowledge_cache.keys()) == [
            "resume_cache_arch_a",
            "resume_cache_arch_b",
        ]
        # iter_002's entry for arch_b is the latest; spot-check round-trip.
        assert (
            state.model_knowledge_cache["resume_cache_arch_b"]["_stats"]["best_denoising_score"]
            == 0.78
        )


# ===========================================================================
# Cross-iter negative-feedback persistence (V8 Domain 1)
# See docs/V8_Gap_Report.md.
# ===========================================================================

from core.resume import (
    _MAX_ACCUMULATED_GATE_EXHAUSTIONS,
    _MAX_ACCUMULATED_REJECTIONS,
)


def _physical_rejection(
    model_type: str, *, estimated_gb: float = 14.0, budget_gb: float = 12.0
) -> dict:
    """Minimum-required dict that validates as PhysicalRejection."""
    return {
        "attempt_config": {"model_type": model_type, "batch_size": 4},
        "binding_cap": "vram",
        "dominant_layer": f"{model_type}.layer_0",
        "dominant_layer_gb": 6.0,
        "dominant_fraction": 0.5,
        "budget_gb": budget_gb,
        "estimated_gb": estimated_gb,
        "suggestion": f"reduce batch_size below 2 for {model_type}",
    }


def _gate_exhaustion(
    active_mode: str = "trial",
    *,
    total_attempts: int = 3,
    summary: str = "all attempts gate-rejected",
) -> dict:
    """Minimum-required dict that validates as GateExhaustionInfo."""
    return {
        "total_attempts": total_attempts,
        "vram_gated_attempts": total_attempts,
        "time_gated_attempts": 0,
        "other_failure_attempts": 0,
        "active_mode": active_mode,
        "summary_message": summary,
    }


class TestRestorePriorStateNegativeFeedbackCarryOver:
    """V8 Domain 1: restore_prior_state populates the two negative-feedback
    fields on RestoredState by walking each prior iter's parsed
    HyperparamTuningOutput. Caps applied at K=10 most-recent."""

    def test_iter1_leaves_negative_feedback_empty(self, tmp_path, isolated_registries):
        state = restore_prior_state(str(tmp_path), 1, [])
        assert state.accumulated_physical_rejections == []
        assert state.accumulated_gate_exhaustions == []

    def test_collects_rejections_chronologically(self, tmp_path, isolated_registries):
        """3-iter chain, each with one rejection → all three collected in order."""
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            run_output_overrides={
                "physical_rejections": [_physical_rejection("arch_a", estimated_gb=15.0)],
            },
        )
        _materialise_iter(
            tmp_path,
            2,
            "resume_test_arch_b",
            run_output_overrides={
                "physical_rejections": [_physical_rejection("arch_b", estimated_gb=18.0)],
            },
        )
        _materialise_iter(
            tmp_path,
            3,
            "resume_test_arch_c",
            run_output_overrides={
                "physical_rejections": [_physical_rejection("arch_c", estimated_gb=20.0)],
            },
        )
        state = restore_prior_state(str(tmp_path), 4, [])
        assert len(state.accumulated_physical_rejections) == 3
        # Order: iter_001 → iter_002 → iter_003
        order = [r.attempt_config["model_type"] for r in state.accumulated_physical_rejections]
        assert order == ["arch_a", "arch_b", "arch_c"]

    def test_collects_gate_exhaustions_chronologically(self, tmp_path, isolated_registries):
        """3-iter chain with gate_exhaustion → all three collected in order."""
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            run_output_overrides={"gate_exhaustion": _gate_exhaustion(summary="iter1")},
        )
        _materialise_iter(
            tmp_path,
            2,
            "resume_test_arch_b",
            run_output_overrides={"gate_exhaustion": _gate_exhaustion(summary="iter2")},
        )
        _materialise_iter(
            tmp_path,
            3,
            "resume_test_arch_c",
            run_output_overrides={"gate_exhaustion": _gate_exhaustion(summary="iter3")},
        )
        state = restore_prior_state(str(tmp_path), 4, [])
        msgs = [g.summary_message for g in state.accumulated_gate_exhaustions]
        assert msgs == ["iter1", "iter2", "iter3"]

    def test_collects_trial_validity_for_next_chain_process(self, tmp_path, isolated_registries):
        """A Health-invalid iteration must reach the next process's proposer.

        This fails on the production one-iteration-per-process path if resume
        restores resource exhaustion but drops scientific invalidity.
        """
        feedback = {
            "trial_records_considered": 1,
            "invalid_count": 1,
            "unknown_validity_count": 0,
            "execution_failure_count": 0,
            "formal_skipped_for_no_valid_winner": True,
            "healthgate_mode": "blocking",
        }
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_collapsed",
            run_output_overrides={"trial_validity_feedback": feedback},
        )
        state = restore_prior_state(str(tmp_path), 2, [])
        assert len(state.accumulated_negative_feedback) == 1
        gate, restored = state.accumulated_negative_feedback[0]
        assert gate is None
        assert restored is not None
        assert restored.invalid_count == 1
        assert restored.execution_failure_count == 0

    def test_no_records_restores_feedback_without_restoring_candidate(
        self, tmp_path, isolated_registries
    ):
        """Regression for #396: negative evidence crosses a no-records
        boundary, while the invalid model, score, and source artifact do not.

        This test fails if resume returns early before validating the manifest
        feedback, or if the repair accidentally promotes the invalid
        iteration into ordinary committed history.
        """
        run_name = _iter_run_name(1)
        iter_dir = tmp_path / run_name
        iter_dir.mkdir()
        feedback = {
            "trial_records_considered": 1,
            "invalid_count": 1,
            "unknown_validity_count": 0,
            "execution_failure_count": 0,
            "formal_skipped_for_no_valid_winner": False,
            "healthgate_mode": "blocking",
        }
        (iter_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "no_records",
                    "iteration_dir": str(iter_dir),
                    "output_path": None,
                    "model_name": "resume_test_collapsed",
                    "best_score": None,
                    "negative_feedback": {
                        "gate_exhaustion": _gate_exhaustion(summary="iteration 1"),
                        "trial_validity_feedback": feedback,
                    },
                }
            )
        )

        state = restore_prior_state(str(tmp_path), 2, ["/seed/reference.json"])

        assert state.committed_iters == []
        assert state.restored_plugins == []
        assert state.resolved_source_paths == ["/seed/reference.json"]
        assert [item.summary_message for item in state.accumulated_gate_exhaustions] == [
            "iteration 1"
        ]
        assert len(state.accumulated_negative_feedback) == 1
        gate, restored = state.accumulated_negative_feedback[0]
        assert gate is not None
        assert restored is not None
        assert restored.invalid_count == 1

    def test_rejections_capped_at_K10_most_recent_wins(self, tmp_path, isolated_registries):
        """Build a 3-iter chain that produces 12 rejections total. After cap,
        only the 10 most-recent should remain (oldest 2 evicted)."""
        # iter_001: 4 rejections, iter_002: 4 rejections, iter_003: 4 rejections
        for iter_idx, model in [(1, "arch_a"), (2, "arch_b"), (3, "arch_c")]:
            _materialise_iter(
                tmp_path,
                iter_idx,
                f"resume_test_arch_{chr(96 + iter_idx)}",
                run_output_overrides={
                    "physical_rejections": [
                        _physical_rejection(model, estimated_gb=10.0 + i) for i in range(4)
                    ],
                },
            )
        state = restore_prior_state(str(tmp_path), 4, [])
        assert len(state.accumulated_physical_rejections) == _MAX_ACCUMULATED_REJECTIONS
        # First 2 (oldest) should have been evicted; last 10 retained.
        # iter_001 contributed 4, iter_002 contributed 4, iter_003 contributed 4.
        # Evicting oldest 2 means iter_001's first 2 are dropped, the rest kept.
        # So accumulator starts with iter_001[2], iter_001[3], iter_002[*], iter_003[*].
        first = state.accumulated_physical_rejections[0]
        assert first.attempt_config["model_type"] == "arch_a"
        last = state.accumulated_physical_rejections[-1]
        assert last.attempt_config["model_type"] == "arch_c"

    def test_gate_exhaustions_capped_at_K10(self, tmp_path, isolated_registries):
        """Build a 12-iter chain (one gate_exhaustion each). After cap, only
        the 10 most-recent retained."""
        for iter_idx in range(1, 13):
            _materialise_iter(
                tmp_path,
                iter_idx,
                f"resume_test_arch_{iter_idx:02d}",
                run_output_overrides={
                    "gate_exhaustion": _gate_exhaustion(summary=f"iter{iter_idx:02d}"),
                },
            )
        state = restore_prior_state(str(tmp_path), 13, [])
        assert len(state.accumulated_gate_exhaustions) == _MAX_ACCUMULATED_GATE_EXHAUSTIONS
        # iter_01 and iter_02 evicted; iter_03..iter_12 retained.
        msgs = [g.summary_message for g in state.accumulated_gate_exhaustions]
        assert msgs[0] == "iter03"
        assert msgs[-1] == "iter12"

    def test_iter_with_no_rejections_contributes_nothing(self, tmp_path, isolated_registries):
        """Iters with empty/missing physical_rejections must not break collection."""
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            run_output_overrides={
                "physical_rejections": [_physical_rejection("arch_a")],
            },
        )
        # iter_002: no overrides → defaults to empty physical_rejections list.
        _materialise_iter(tmp_path, 2, "resume_test_arch_b")
        _materialise_iter(
            tmp_path,
            3,
            "resume_test_arch_c",
            run_output_overrides={
                "physical_rejections": [_physical_rejection("arch_c")],
            },
        )
        state = restore_prior_state(str(tmp_path), 4, [])
        # Only iter_001 and iter_003 contribute.
        assert len(state.accumulated_physical_rejections) == 2
        order = [r.attempt_config["model_type"] for r in state.accumulated_physical_rejections]
        assert order == ["arch_a", "arch_c"]

    def test_iter_with_none_gate_exhaustion_skipped(self, tmp_path, isolated_registries):
        """Iters with gate_exhaustion=None (the default) must be skipped silently."""
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            run_output_overrides={"gate_exhaustion": _gate_exhaustion(summary="iter1")},
        )
        # iter_002: no override → default gate_exhaustion=None.
        _materialise_iter(tmp_path, 2, "resume_test_arch_b")
        _materialise_iter(
            tmp_path,
            3,
            "resume_test_arch_c",
            run_output_overrides={"gate_exhaustion": _gate_exhaustion(summary="iter3")},
        )
        state = restore_prior_state(str(tmp_path), 4, [])
        msgs = [g.summary_message for g in state.accumulated_gate_exhaustions]
        assert msgs == ["iter1", "iter3"]

    def test_no_records_iter_does_not_break_accumulation(self, tmp_path, isolated_registries):
        """A no_records iter (gate-exhaustion that produced no run_output) is
        skipped without affecting the rejection accumulator."""
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            run_output_overrides={
                "physical_rejections": [_physical_rejection("arch_a")],
            },
        )
        # iter_002: no_records (workspace + manifest only, no run_output).
        run_name_2 = _iter_run_name(2)
        iter_dir_2 = tmp_path / run_name_2
        iter_dir_2.mkdir()
        (iter_dir_2 / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "no_records",
                    "iteration_dir": str(iter_dir_2),
                    "output_path": None,
                    "model_name": None,
                    "best_score": None,
                }
            )
        )
        _materialise_iter(
            tmp_path,
            3,
            "resume_test_arch_c",
            run_output_overrides={
                "physical_rejections": [_physical_rejection("arch_c")],
            },
        )
        state = restore_prior_state(str(tmp_path), 4, [])
        # iter_002 contributes nothing; iter_001 and iter_003 do.
        assert len(state.accumulated_physical_rejections) == 2
        assert state.committed_iters == [1, 3]


# ===========================================================================
# G1 bridge — proposal carry-over (load_latest_proposal)
# See docs/Consistent_growing_vocab_list.md §10 + §15.3 Commit 1.1.
# ===========================================================================

from core.resume import _proposal_path, load_latest_proposal


def _write_proposal(
    workspace,
    iter_idx: int,
    *,
    attempt: int = 1,
    model_name: str = "synthetic_model",
    payload: dict | None = None,
    raw_text: str | None = None,
):
    """Write a synthetic ``proposal_iter_NNN.json`` under the chain layout.

    Mirrors ``{workspace}/iter_NNN/iteration_NNN/attempt_MMM_<model>/
    proposal_iter_NNN.json`` — both NNN segments carry the same chain-wide
    iter index (post-cc198ad workflow loop). ``raw_text`` lets a test
    inject malformed JSON deliberately. ``payload`` defaults to a minimal
    dict carrying a ``proposed_vocab_candidates`` field so the loader's
    downstream consumer (the workflow) has something parseable to seed.
    """
    run_name = _iter_run_name(iter_idx)
    attempt_dir = (
        workspace / run_name / f"iteration_{iter_idx:03d}" / f"attempt_{attempt:03d}_{model_name}"
    )
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / f"proposal_{run_name}.json"
    if raw_text is not None:
        path.write_text(raw_text)
        return path
    body = (
        payload
        if payload is not None
        else {
            "proposed_model_type": model_name,
            "proposed_vocab_candidates": [
                {"name": f"cand_{run_name}", "kind": "feature"},
            ],
        }
    )
    path.write_text(json.dumps(body))
    return path


class TestLoadLatestProposal:
    """Read-only loader behaviour for the G1 bridge.

    Four contract cases per §10.4.1:
      1. No committed iters → returns None.
      2. Three committed iters with parseable proposals → latest wins.
      3. Latest iter has a malformed proposal → warn + fall back to next-older.
      4. An iter has both attempt_001_* and attempt_002_* dirs → highest MMM wins.
    """

    def test_load_latest_proposal_no_committed_iters_returns_none(self, tmp_path):
        assert load_latest_proposal(str(tmp_path), []) is None

    def test_load_latest_proposal_latest_committed_wins(self, tmp_path):
        """Three committed iters; loader returns iter_003's payload."""
        _write_proposal(tmp_path, 1, payload={"id": "iter1_proposal"})
        _write_proposal(tmp_path, 2, payload={"id": "iter2_proposal"})
        _write_proposal(tmp_path, 3, payload={"id": "iter3_proposal"})
        out = load_latest_proposal(str(tmp_path), [1, 2, 3])
        assert out == {"id": "iter3_proposal"}

    def test_load_latest_proposal_malformed_warns_and_skips(self, tmp_path):
        """Iter_002 malformed JSON → warn, fall back to iter_001."""
        _write_proposal(tmp_path, 1, payload={"id": "iter1_proposal"})
        _write_proposal(tmp_path, 2, raw_text="{not valid json")
        with pytest.warns(UserWarning, match=r"iter 002.*cannot read proposal"):
            out = load_latest_proposal(str(tmp_path), [1, 2])
        assert out == {"id": "iter1_proposal"}

    def test_load_latest_proposal_glob_walks_attempt_dirs(self, tmp_path):
        """Same iter has attempt_001 + attempt_002 → highest MMM wins."""
        # Older attempt with the rejected proposal:
        _write_proposal(
            tmp_path,
            3,
            attempt=1,
            model_name="rejected_arch",
            payload={"id": "iter3_attempt1_rejected"},
        )
        # Newer attempt that was accepted:
        _write_proposal(
            tmp_path,
            3,
            attempt=2,
            model_name="accepted_arch",
            payload={"id": "iter3_attempt2_accepted"},
        )
        out = load_latest_proposal(str(tmp_path), [3])
        assert out == {"id": "iter3_attempt2_accepted"}

    # ---- structural sanity for _proposal_path itself ----

    def test_proposal_path_returns_none_when_no_attempt_dir(self, tmp_path):
        """No ``attempt_MMM_*`` subdir → loader resolves to None silently."""
        # Iter dir exists but no attempt_* sub-dir under it.
        (tmp_path / "iter_001" / "iteration_001").mkdir(parents=True)
        assert _proposal_path(str(tmp_path), 1) is None

    def test_proposal_path_returns_none_when_iteration_dir_missing(self, tmp_path):
        """No iter_NNN/iteration_NNN/ at all → silent None (no_records iter)."""
        assert _proposal_path(str(tmp_path), 5) is None

    def test_proposal_path_uses_chain_wide_iter_dir_name_for_iter_above_1(
        self,
        tmp_path,
    ):
        """Regression for the cc198ad path drift.

        Post-cc198ad, ``workflows.model_exploration.run_workflow`` builds
        ``iter_dir = run_dir / f"iteration_{iteration:03d}"`` where
        ``iteration`` is the chain-wide loop variable. In chain mode that
        means iter 5 writes its attempt under
        ``iter_005/iteration_005/...``, NOT ``iter_005/iteration_001/...``.
        The earlier hardcoded ``iteration_001`` would silently miss every
        post-cc198ad chain iter > 1 — this test pins the dynamic name.
        """
        # Place a proposal under the post-cc198ad layout for iter 5.
        path = _write_proposal(
            tmp_path,
            5,
            payload={"id": "iter5_proposal_under_dynamic_dir"},
        )
        # Sanity: writer is honouring the dynamic layout.
        assert "iteration_005" in str(path), (
            f"_write_proposal still writing legacy layout: {path!r}"
        )
        # Loader must resolve the same dynamic path.
        resolved = _proposal_path(str(tmp_path), 5)
        assert resolved is not None
        assert "iter_005" in resolved and "iteration_005" in resolved, (
            f"_proposal_path resolved {resolved!r} — expected dynamic "
            f"iteration_005 segment, not the legacy iteration_001."
        )
        with open(resolved) as f:
            assert json.load(f) == {"id": "iter5_proposal_under_dynamic_dir"}

    def test_interpretation_path_uses_chain_wide_iter_dir_name_for_iter_above_1(
        self,
        tmp_path,
    ):
        """Regression for the cc198ad path drift on the knowledge channel.

        Same root cause as the proposal-path drift: ``_interpretation_path``
        previously hardcoded ``iteration_001`` and would silently miss
        every post-cc198ad chain iter > 1. This test pins the dynamic name
        for the digest reader.
        """
        from core.resume import _interpretation_path

        path = _interpretation_path(str(tmp_path), 7)
        assert "iter_007" in path and "iteration_007" in path, (
            f"_interpretation_path resolved {path!r} — expected dynamic "
            f"iteration_007 segment, not the legacy iteration_001."
        )


class TestRestorePriorStateProposalCarryOver:
    """Full-stack: restore_prior_state populates the new field."""

    def test_iter1_leaves_proposal_field_none(self, tmp_path, isolated_registries):
        state = restore_prior_state(str(tmp_path), 1, [])
        assert state.previous_proposal_data is None

    def test_populates_previous_proposal_data_from_latest_iter(
        self,
        tmp_path,
        isolated_registries,
    ):
        """2-iter workspace with proposals at both iters; latest wins."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        _materialise_iter(tmp_path, 2, "resume_test_arch_b", 0.78)
        _write_proposal(
            tmp_path,
            1,
            model_name="resume_test_arch_a",
            payload={"proposed_model_type": "resume_test_arch_a", "id": "p1"},
        )
        _write_proposal(
            tmp_path,
            2,
            model_name="resume_test_arch_b",
            payload={"proposed_model_type": "resume_test_arch_b", "id": "p2"},
        )
        state = restore_prior_state(str(tmp_path), 3, [])
        assert state.previous_proposal_data is not None
        assert state.previous_proposal_data["id"] == "p2"

    def test_proposal_field_none_when_no_proposal_files_exist(
        self,
        tmp_path,
        isolated_registries,
    ):
        """Manifests + run_outputs present but no proposal JSON → None."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        state = restore_prior_state(str(tmp_path), 2, [])
        assert state.committed_iters == [1]
        assert state.previous_proposal_data is None


# ===========================================================================
# DS6b — run-invariants ingress validation
# ===========================================================================

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    write_run_invariants,
)

_FULL_SCOPE = list(range(20))
_INV_FULL = RunInvariants(
    resolved_data_scope=_FULL_SCOPE,
    health_gate_enabled=True,
    health_config_sha256="e" * 64,
)
_INV_PARTIAL = RunInvariants(
    resolved_data_scope=[4, 5, 6, 7, 8, 9],
    health_gate_enabled=True,
    health_config_sha256="e" * 64,
)


class TestRunInvariantsIngress:
    def test_explicit_partition_count_avoids_pre_binding_profile_lookup(
        self, tmp_path, isolated_registries, monkeypatch
    ):
        """Iteration 2 must restore an external task before activation.

        The chain already resolved the task profile.  Re-reading an ambient
        profile here fails for every external task because composition is not
        active until workflow execution.
        """
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)

        def _unexpected_profile_lookup():
            raise AssertionError("resume must use the caller-resolved partition count")

        monkeypatch.setattr("core.resume.resolve_dataset_profile", _unexpected_profile_lookup)
        state = restore_prior_state(
            str(tmp_path),
            2,
            [],
            expected_invariants=_INV_FULL,
            dataset_partition_count=20,
        )
        assert state.committed_iters == [1]

    def test_none_skips_all_checks(self, tmp_path, isolated_registries):
        """expected_invariants=None → pre-DS6b behavior, even with a
        contradicting lock present."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        write_run_invariants(str(tmp_path), _INV_PARTIAL)
        state = restore_prior_state(str(tmp_path), 2, [])
        assert state.committed_iters == [1]

    def test_legacy_unstamped_history_vs_full_run_passes(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        state = restore_prior_state(
            str(tmp_path),
            2,
            [],
            expected_invariants=_INV_FULL,
            dataset_partition_count=20,
        )
        assert state.committed_iters == [1]

    def test_legacy_unstamped_history_vs_partial_run_fails_unmutated(
        self, tmp_path, isolated_registries
    ):
        from ml_models.models_sandbox import MODEL_REGISTRY

        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        with pytest.raises(RunInvariantsViolation, match="resolved_data_scope"):
            restore_prior_state(
                str(tmp_path),
                2,
                [],
                expected_invariants=_INV_PARTIAL,
                dataset_partition_count=20,
            )
        # The mismatching iter's plugin was NOT registered (fails before
        # mutation — DS6b invariant 4).
        assert "resume_test_arch_a" not in MODEL_REGISTRY

    def test_stamped_matching_history_passes(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            0.71,
            run_output_overrides={
                "resolved_data_scope": [4, 5, 6, 7, 8, 9],
                "health_gate_enabled": True,
                "health_config_sha256": "e" * 64,
            },
        )
        state = restore_prior_state(
            str(tmp_path),
            2,
            [],
            expected_invariants=_INV_PARTIAL,
            dataset_partition_count=20,
        )
        assert state.committed_iters == [1]

    def test_stamped_sha_drift_fails(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path,
            1,
            "resume_test_arch_a",
            0.71,
            run_output_overrides={
                "resolved_data_scope": [4, 5, 6, 7, 8, 9],
                "health_gate_enabled": True,
                "health_config_sha256": "f" * 64,
            },
        )
        with pytest.raises(RunInvariantsViolation, match="health_config_sha256"):
            restore_prior_state(
                str(tmp_path),
                2,
                [],
                expected_invariants=_INV_PARTIAL,
                dataset_partition_count=20,
            )

    def test_contradicting_lock_fails_before_any_iter(self, tmp_path, isolated_registries):
        from ml_models.models_sandbox import MODEL_REGISTRY

        _materialise_iter(tmp_path, 1, "resume_test_arch_a", 0.71)
        write_run_invariants(str(tmp_path), _INV_PARTIAL)
        with pytest.raises(RunInvariantsViolation, match="lock violation"):
            restore_prior_state(str(tmp_path), 2, [], expected_invariants=_INV_FULL)
        assert "resume_test_arch_a" not in MODEL_REGISTRY
