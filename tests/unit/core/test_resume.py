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
    restore_prior_state,
    _iter_run_name,
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
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

    test_keys = (
        "resume_test_arch_a", "resume_test_arch_b", "resume_test_arch_c",
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

    def test_current_iter_1_does_not_require_existing_workspace(self, tmp_path, isolated_registries):
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
            "resume_test_arch_a", "resume_test_arch_b",
        ]

    def test_registry_actually_populated(self, workspace, isolated_registries):
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.plugin_loader import (
            PLUGIN_OUTPUT_TYPE_REGISTRY, get_output_type,
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
        with pytest.raises(ResumeError, match="manifest.json is malformed"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_status_failed_raises(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path, 1, "resume_test_arch_a",
            manifest_status="failed",
        )
        with pytest.raises(ResumeError, match="status='failed'"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_status_partial_raises(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path, 1, "resume_test_arch_a",
            manifest_status="partial",
        )
        with pytest.raises(ResumeError, match="status='partial'"):
            restore_prior_state(str(tmp_path), 2, [])

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
        run_output = tmp_path / "iter_001" / "iteration_001" / "resume_test_arch_a" / "run_output_iter_001.json"
        run_output.unlink()
        with pytest.raises(ResumeError, match="output_path .* does not exist"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_malformed_run_output_json_raises(self, tmp_path, isolated_registries):
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        run_output = tmp_path / "iter_001" / "iteration_001" / "resume_test_arch_a" / "run_output_iter_001.json"
        run_output.write_text("{this is not json")
        with pytest.raises(ResumeError, match="run_output failed validation"):
            restore_prior_state(str(tmp_path), 2, [])

    def test_run_output_validation_error_raises(self, tmp_path, isolated_registries):
        """A JSON object that's structurally valid but missing required
        fields → Pydantic ValidationError → ResumeError."""
        _materialise_iter(tmp_path, 1, "resume_test_arch_a")
        run_output = tmp_path / "iter_001" / "iteration_001" / "resume_test_arch_a" / "run_output_iter_001.json"
        run_output.write_text(json.dumps({"run_name": "iter_001"}))  # missing model_type, status, ...
        with pytest.raises(ResumeError, match="run_output failed validation"):
            restore_prior_state(str(tmp_path), 2, [])


# ===========================================================================
# Plugin-file edge cases
# ===========================================================================

class TestPluginFileEdgeCases:

    def test_missing_plugin_file_warns_and_continues(self, tmp_path, isolated_registries):
        _materialise_iter(
            tmp_path, 1, "resume_test_arch_a",
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
            tmp_path, 1, "resume_test_arch_a",
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
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.plugin_loader import (
            PLUGIN_OUTPUT_TYPE_REGISTRY, get_output_type,
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
