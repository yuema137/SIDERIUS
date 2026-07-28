"""
Unit tests for ``sdsc_submission_scripts/run_one_iteration.py`` —
Phase 6.8 Task 2 Commit 8.

Covers two layers:

  * **CLI surface (TestArgparseSurface)** — the new ``--start_iteration``
    flag, the deprecated ``--iteration`` alias, the mutex between them,
    and the ``< 1`` guard. ``argparse``-level concerns only; no workflow
    invocation.

  * **Wiring around restore_prior_state (TestRestoreWiring)** — exercises
    ``main()`` with ``run_workflow`` mocked so we can assert the resolved
    ``source_paths`` list reaching the workflow is exactly the one
    ``restore_prior_state`` returns. Uses the same on-disk fixture pattern
    as ``tests/unit/core/test_resume.py`` (manifest + run_output JSON +
    plugin .py file under ``{workspace}/iter_NNN/`` + ``{workspace}/plugins/iter_NNN/``).

The "manual delete iter_001 plugin" and "manual override --start_iteration 3"
tests called out in design doc §3.5 Commit 8 live in the wiring layer.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import warnings
from unittest.mock import patch

import pytest

from sdsc_submission_scripts import run_one_iteration as runner

# ---------------------------------------------------------------------------
# Shared fixtures
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


def _materialise_iter(workspace, iter_idx, model_type, *, write_plugin=True):
    run_name = f"iter_{iter_idx:03d}"
    iter_dir = workspace / run_name
    model_dir = iter_dir / "iteration_001" / model_type
    model_dir.mkdir(parents=True)

    output_path = model_dir / f"run_output_{run_name}.json"
    output_path.write_text(
        json.dumps(
            {
                "run_name": run_name,
                "model_type": model_type,
                "file_index": 6,
                "status": "completed",
                "completed_rounds": 3,
                "total_attempts": 5,
                "best_exp_id": "exp_001",
                "best_denoising_score": 0.5 + 0.05 * iter_idx,
                "started_at": "2026-04-27T10:00:00",
                "finished_at": "2026-04-27T11:00:00",
            }
        )
    )

    (iter_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "iteration_dir": str(iter_dir),
                "output_path": str(output_path),
                "model_name": model_type,
                "best_score": 0.5 + 0.05 * iter_idx,
                "completed_rounds": 3,
            }
        )
    )

    if write_plugin:
        plugin_dir = workspace / "plugins" / run_name
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / f"{model_type}.py").write_text(_plugin_src(model_type))

    return str(output_path)


@pytest.fixture
def isolated_registries():
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

    test_keys = (
        "c8_test_arch_a",
        "c8_test_arch_b",
        "c8_test_arch_c",
        "c8_test_arch_d",
        "c8_test_arch_e",
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
# CLI surface
# ===========================================================================


class TestArgparseSurface:
    """The flag-renaming UX. Argparse-level concerns only — no workflow."""

    def _minimal_argv(self, *extra):
        return [
            "--workspace",
            "/tmp/ws",
            "--run_name",
            "iter_001",
            "--seed_paths",
            "/tmp/seed.json",
            *extra,
        ]

    def test_start_iteration_canonical_path(self):
        args = runner.build_parser().parse_args(self._minimal_argv("--start_iteration", "3"))
        normalized = runner.normalize_args(args)
        assert normalized.start_iteration == 3
        # Legacy attr removed after normalisation.
        assert not hasattr(normalized, "iteration_legacy")

    def test_legacy_iteration_alias_works_with_deprecation_warning(self):
        args = runner.build_parser().parse_args(self._minimal_argv("--iteration", "2"))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            normalized = runner.normalize_args(args)
        assert normalized.start_iteration == 2
        depr = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(depr) == 1
        assert "use --start_iteration" in str(depr[0].message)

    def test_both_flags_supplied_is_an_error(self, capsys):
        args = runner.build_parser().parse_args(
            self._minimal_argv("--start_iteration", "3", "--iteration", "2")
        )
        with pytest.raises(SystemExit):
            runner.normalize_args(args)
        err = capsys.readouterr().err
        assert "mutually exclusive" in err

    def test_neither_flag_supplied_is_an_error(self, capsys):
        args = runner.build_parser().parse_args(self._minimal_argv())
        with pytest.raises(SystemExit):
            runner.normalize_args(args)
        err = capsys.readouterr().err
        assert "one of --start_iteration / --iteration is required" in err

    def test_start_iteration_below_one_is_an_error(self, capsys):
        args = runner.build_parser().parse_args(self._minimal_argv("--start_iteration", "0"))
        with pytest.raises(SystemExit):
            runner.normalize_args(args)
        err = capsys.readouterr().err
        assert ">= 1" in err

    def test_workspace_is_required(self, capsys):
        with pytest.raises(SystemExit):
            runner.build_parser().parse_args(
                ["--start_iteration", "1", "--seed_paths", "/tmp/seed.json"]
            )
        # argparse writes its own message to stderr.

    def test_omitting_seed_paths_is_a_cold_start(self):
        """Omitting BOTH --seed_paths and --source_paths is a valid cold start
        (empty seed list), not an error — seedless chain support. A bare
        --seed_paths with no values remains an argparse error (nargs='+'),
        covered by the cold-start CLI tests."""
        args = runner.build_parser().parse_args(
            ["--workspace", "/tmp/ws", "--run_name", "iter_001", "--start_iteration", "1"]
        )
        normalized = runner.normalize_args(args)
        assert normalized.seed_paths == []

    def test_legacy_source_paths_alias_works_with_deprecation_warning(self):
        """--source_paths still resolves to args.seed_paths and emits one DeprecationWarning."""
        args = runner.build_parser().parse_args(
            [
                "--workspace",
                "/tmp/ws",
                "--run_name",
                "iter_001",
                "--start_iteration",
                "1",
                "--source_paths",
                "/tmp/seed.json",
            ]
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            normalized = runner.normalize_args(args)
        assert normalized.seed_paths == ["/tmp/seed.json"]
        assert not hasattr(normalized, "source_paths_legacy")
        depr = [
            w
            for w in caught
            if issubclass(w.category, DeprecationWarning)
            and "--source_paths is deprecated" in str(w.message)
        ]
        assert len(depr) == 1

    def test_seed_paths_and_source_paths_both_supplied_is_an_error(self, capsys):
        args = runner.build_parser().parse_args(
            [
                "--workspace",
                "/tmp/ws",
                "--run_name",
                "iter_001",
                "--start_iteration",
                "1",
                "--seed_paths",
                "/tmp/a.json",
                "--source_paths",
                "/tmp/b.json",
            ]
        )
        with pytest.raises(SystemExit):
            runner.normalize_args(args)
        err = capsys.readouterr().err
        assert "mutually exclusive" in err

    def test_max_epochs_zero_is_rejected(self, capsys):
        """--max_epochs must be >= 1 (Phase 6.8 Commit 11 ruling)."""
        with pytest.raises(SystemExit):
            runner.build_parser().parse_args(
                self._minimal_argv("--start_iteration", "1", "--max_epochs", "0")
            )
        err = capsys.readouterr().err
        assert ">= 1" in err or "positive integer" in err

    def test_max_epochs_negative_is_rejected(self, capsys):
        with pytest.raises(SystemExit):
            runner.build_parser().parse_args(
                self._minimal_argv("--start_iteration", "1", "--max_epochs", "-1")
            )

    def test_plan_overrides_json_string_becomes_dict(self):
        args = runner.build_parser().parse_args(
            self._minimal_argv(
                "--start_iteration",
                "1",
                "--plan_overrides",
                '{"trial_portion": 0.2}',
            )
        )
        normalized = runner.normalize_args(args)
        assert normalized.plan_overrides == {"trial_portion": 0.2}

    def test_plan_overrides_default_none(self):
        args = runner.build_parser().parse_args(self._minimal_argv("--start_iteration", "1"))
        normalized = runner.normalize_args(args)
        assert normalized.plan_overrides is None

    def test_human_advice_file_is_loaded(self, tmp_path):
        advice_file = tmp_path / "advice.json"
        advice_file.write_text(
            json.dumps(
                {
                    "interpret": "interp text",
                    "propose": "propose text",
                }
            )
        )
        args = runner.build_parser().parse_args(
            self._minimal_argv(
                "--start_iteration",
                "1",
                "--human_advice_file",
                str(advice_file),
            )
        )
        normalized = runner.normalize_args(args)
        assert normalized.human_advice_interpret == "interp text"
        assert normalized.human_advice_propose == "propose text"

    def test_human_advice_cli_overrides_file(self, tmp_path):
        advice_file = tmp_path / "advice.json"
        advice_file.write_text(json.dumps({"propose": "from file"}))
        args = runner.build_parser().parse_args(
            self._minimal_argv(
                "--start_iteration",
                "1",
                "--human_advice_file",
                str(advice_file),
                "--human_advice_propose",
                "from CLI",
            )
        )
        normalized = runner.normalize_args(args)
        assert normalized.human_advice_propose == "from CLI"


# ===========================================================================
# Wiring layer — main() with run_workflow mocked
# ===========================================================================


class _StubResult:
    """Minimal HyperparamTuningOutput-shaped object for write_manifest."""

    def __init__(
        self,
        model_type,
        score=0.7,
        health_checks_config=None,
        formal_reference_score=None,
        resolved_skip_formal_threshold=None,
        resolved_bypass_formal_threshold=None,
    ):
        self.model_type = model_type
        self.best_denoising_score = score
        self.completed_rounds = 3
        self.health_checks_config = health_checks_config
        self.formal_reference_score = formal_reference_score
        self.resolved_skip_formal_threshold = resolved_skip_formal_threshold
        self.resolved_bypass_formal_threshold = resolved_bypass_formal_threshold


def _run_main(argv):
    """Invoke runner.main() under SystemExit catch + return the captured args.

    Injects ``--run_name iter_NNN`` (matching ``--start_iteration N`` /
    ``--iteration N``) when the caller didn't supply one. The chain
    runner now requires ``--run_name``; the production chain shell
    always supplies it. These unit tests target the runner's argparse
    + wiring layer in isolation, so we synthesise the same shell-side
    convention here rather than baking ``--run_name`` into every
    hand-crafted argv list.
    """
    if "--run_name" not in argv:
        iter_n = 1
        for flag in ("--start_iteration", "--iteration"):
            if flag in argv:
                iter_n = int(argv[argv.index(flag) + 1])
                break
        argv = ["--run_name", f"iter_{iter_n:03d}", *argv]
    with patch.object(sys, "argv", ["run_one_iteration.py", *argv]):
        try:
            runner.main()
        except SystemExit as e:
            return e.code
    return 0


class TestRestoreWiring:
    """End-to-end wiring of the runner with run_workflow mocked.

    The chain workspace is materialised by the same helpers used for
    test_resume.py so the test fixtures exercise the production layout
    contract (``{workspace}/iter_NNN/`` + ``{workspace}/plugins/iter_NNN/``).
    """

    def test_start_iteration_1_passes_seeds_through_unchanged(
        self,
        tmp_path,
        isolated_registries,
    ):
        seed_file = tmp_path / "seed.json"
        seed_file.write_text(
            json.dumps(
                {
                    "run_name": "seed",
                    "model_type": "punet",
                    "file_index": 6,
                    "status": "completed",
                    "completed_rounds": 1,
                    "total_attempts": 1,
                    "started_at": "x",
                    "finished_at": "y",
                }
            )
        )

        with patch.object(runner, "run_workflow") as mock_wf:
            mock_wf.return_value = [_StubResult("c8_test_arch_a")]
            with patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_a",
                    "best_score": 0.7,
                    "output_path": "x",
                },
            ):
                code = _run_main(
                    [
                        "--workspace",
                        str(tmp_path),
                        "--start_iteration",
                        "1",
                        "--seed_paths",
                        str(seed_file),
                    ]
                )
        assert code == 0
        # The workflow received the seed list verbatim — no extra prior iters.
        kwargs = mock_wf.call_args.kwargs
        assert kwargs["source_paths"] == [str(seed_file)]
        assert kwargs["run_name"] == "iter_001"

    def test_health_checks_config_reaches_workflow(
        self,
        tmp_path,
        isolated_registries,
    ):
        seed_file = tmp_path / "seed.json"
        seed_file.write_text(
            json.dumps(
                {
                    "run_name": "seed",
                    "model_type": "punet",
                    "file_index": 6,
                    "status": "completed",
                    "completed_rounds": 1,
                    "total_attempts": 1,
                    "started_at": "x",
                    "finished_at": "y",
                }
            )
        )
        health_path = "configs/health_checks_baseline_observe_mode.yaml"

        with patch.object(runner, "run_workflow") as mock_wf:
            mock_wf.return_value = [_StubResult("c8_test_arch_a")]
            with patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_a",
                    "best_score": 0.7,
                    "output_path": "x",
                },
            ):
                code = _run_main(
                    [
                        "--workspace",
                        str(tmp_path),
                        "--start_iteration",
                        "1",
                        "--seed_paths",
                        str(seed_file),
                        "--health_checks_config",
                        health_path,
                    ]
                )

        assert code == 0
        assert mock_wf.call_args.kwargs["health_checks_config"] == health_path

    def test_start_iteration_2_restores_iter_1_plugin_and_prepends_path(
        self,
        tmp_path,
        isolated_registries,
    ):
        from ml_models.models_sandbox import MODEL_REGISTRY

        # Iter 1 is committed on disk.
        iter1_output = _materialise_iter(tmp_path, 1, "c8_test_arch_a")

        seed_file = tmp_path / "seed.json"
        seed_file.write_text(
            json.dumps(
                {
                    "run_name": "seed",
                    "model_type": "punet",
                    "file_index": 6,
                    "status": "completed",
                    "completed_rounds": 1,
                    "total_attempts": 1,
                    "started_at": "x",
                    "finished_at": "y",
                }
            )
        )

        # Sanity: registry doesn't contain the prior plugin yet (this process
        # is simulating a fresh interpreter for iter 2).
        assert "c8_test_arch_a" not in MODEL_REGISTRY

        with (
            patch.object(runner, "run_workflow") as mock_wf,
            patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_b",
                    "best_score": 0.8,
                    "output_path": "x",
                },
            ),
        ):
            mock_wf.return_value = [_StubResult("c8_test_arch_b")]
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "2",
                    "--seed_paths",
                    str(seed_file),
                ]
            )

        assert code == 0
        # restore_prior_state should have re-registered the iter-1 plugin.
        assert "c8_test_arch_a" in MODEL_REGISTRY
        # source_paths the workflow saw = [seed, iter_001 output] in order.
        kwargs = mock_wf.call_args.kwargs
        assert kwargs["source_paths"] == [str(seed_file), iter1_output]
        assert kwargs["run_name"] == "iter_002"

    def test_chain_banner_printed_when_priors_restored(
        self,
        tmp_path,
        isolated_registries,
        capsys,
    ):
        _materialise_iter(tmp_path, 1, "c8_test_arch_a")
        seed = tmp_path / "seed.json"
        seed.write_text("{}")  # content irrelevant — resolve_source_paths
        # only treats @manifest: prefixes specially.

        with (
            patch.object(runner, "run_workflow", return_value=[_StubResult("c8_test_arch_b")]),
            patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_b",
                    "best_score": 0.8,
                    "output_path": "x",
                },
            ),
        ):
            _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "2",
                    "--seed_paths",
                    str(seed),
                ]
            )

        out = capsys.readouterr().out
        assert "[CHAIN] Restored 1 prior plugin(s) from iters [1]" in out
        assert "c8_test_arch_a" in out  # plugin name appears in the listing

    def test_chain_banner_omitted_for_iter_1(
        self,
        tmp_path,
        isolated_registries,
        capsys,
    ):
        seed = tmp_path / "seed.json"
        seed.write_text("{}")

        with (
            patch.object(runner, "run_workflow", return_value=[_StubResult("c8_test_arch_a")]),
            patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_a",
                    "best_score": 0.7,
                    "output_path": "x",
                },
            ),
        ):
            _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "1",
                    "--seed_paths",
                    str(seed),
                ]
            )

        out = capsys.readouterr().out
        assert "[CHAIN] Restored" not in out

    def test_missing_iter_1_plugin_warns_but_iteration_runs(
        self,
        tmp_path,
        isolated_registries,
    ):
        """§3.5 Commit 8 spec: 2-iter chain on synthetic data; manually delete
        iter_001 plugin file; rerun iter_002; warning is emitted but the iter
        still runs. memory_history is built from the JSON record."""
        iter1_output = _materialise_iter(tmp_path, 1, "c8_test_arch_a", write_plugin=False)

        seed = tmp_path / "seed.json"
        seed.write_text("{}")

        with (
            patch.object(runner, "run_workflow") as mock_wf,
            patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_b",
                    "best_score": 0.8,
                    "output_path": "x",
                },
            ),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            mock_wf.return_value = [_StubResult("c8_test_arch_b")]
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "2",
                    "--seed_paths",
                    str(seed),
                ]
            )

        assert code == 0
        # Workflow still ran with the prior iter's run_output in source_paths.
        kwargs = mock_wf.call_args.kwargs
        assert iter1_output in kwargs["source_paths"]
        # Warning was emitted somewhere in the call chain.
        plugin_warnings = [w for w in caught if "plugin file not found" in str(w.message)]
        assert len(plugin_warnings) >= 1

    def test_manual_override_start_iteration_3_with_iters_1_and_2_on_disk(
        self,
        tmp_path,
        isolated_registries,
    ):
        """§3.5 Commit 8 spec: ``--start_iteration 3`` against a workspace
        with iters 1+2 already committed; verify it skips auto-detect and
        runs iter 3 directly with both prior plugins restored."""
        from ml_models.models_sandbox import MODEL_REGISTRY

        iter1 = _materialise_iter(tmp_path, 1, "c8_test_arch_a")
        iter2 = _materialise_iter(tmp_path, 2, "c8_test_arch_b")

        seed = tmp_path / "seed.json"
        seed.write_text("{}")

        with (
            patch.object(runner, "run_workflow") as mock_wf,
            patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_c",
                    "best_score": 0.85,
                    "output_path": "x",
                },
            ),
        ):
            mock_wf.return_value = [_StubResult("c8_test_arch_c")]
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "3",
                    "--seed_paths",
                    str(seed),
                ]
            )

        assert code == 0
        # Both prior plugins re-registered.
        assert "c8_test_arch_a" in MODEL_REGISTRY
        assert "c8_test_arch_b" in MODEL_REGISTRY
        # source_paths in chronological order.
        kwargs = mock_wf.call_args.kwargs
        assert kwargs["source_paths"] == [str(seed), iter1, iter2]
        # Iter dir name reflects the start_iteration (no auto-detection
        # silently shifted us elsewhere).
        assert kwargs["run_name"] == "iter_003"

    def test_corrupt_prior_iter_aborts_with_clear_error(
        self,
        tmp_path,
        isolated_registries,
        capsys,
    ):
        _materialise_iter(tmp_path, 1, "c8_test_arch_a")
        # Corrupt iter 1's manifest after the fact.
        (tmp_path / "iter_001" / "manifest.json").write_text("{not json")

        seed = tmp_path / "seed.json"
        seed.write_text("{}")

        with patch.object(runner, "run_workflow") as mock_wf:
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "2",
                    "--seed_paths",
                    str(seed),
                ]
            )

        assert code == 1, "runner should exit non-zero on corrupt prior"
        # run_workflow must not have been invoked.
        mock_wf.assert_not_called()
        out = capsys.readouterr().out
        assert "FAIL: restore_prior_state refused" in out

    def test_legacy_iteration_alias_still_drives_restore(
        self,
        tmp_path,
        isolated_registries,
    ):
        """Operators on the old chain shell can still pass --iteration; the
        restore path is reached through the deprecation alias."""
        from ml_models.models_sandbox import MODEL_REGISTRY

        _materialise_iter(tmp_path, 1, "c8_test_arch_a")

        seed = tmp_path / "seed.json"
        seed.write_text("{}")

        with (
            patch.object(runner, "run_workflow") as mock_wf,
            patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_b",
                    "best_score": 0.8,
                    "output_path": "x",
                },
            ),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            mock_wf.return_value = [_StubResult("c8_test_arch_b")]
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--iteration",
                    "2",  # deprecated alias
                    "--seed_paths",
                    str(seed),
                ]
            )

        assert code == 0
        assert "c8_test_arch_a" in MODEL_REGISTRY
        # DeprecationWarning was emitted.
        depr = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(depr) >= 1


# ===========================================================================
# no_records contract — chain-fragility fix
# ===========================================================================


class TestNoRecordsExit:
    """A clean no-records iter (gate exhaustion or all-rounds-failed without
    a Python crash) must exit 0 with manifest.status='no_records', so the
    next iter can run and the LLM can adapt to the skip.

    True crashes (workflow exception, seed-resolution error, restore_prior_state
    error) must keep exit 1 with manifest.status='failed' so the chain halts.
    """

    def _seed_file(self, tmp_path):
        seed = tmp_path / "seed.json"
        seed.write_text(
            json.dumps(
                {
                    "run_name": "seed",
                    "model_type": "punet",
                    "file_index": 6,
                    "status": "completed",
                    "completed_rounds": 1,
                    "total_attempts": 1,
                    "started_at": "x",
                    "finished_at": "y",
                }
            )
        )
        return seed

    def test_write_manifest_empty_results_emits_no_records(self, tmp_path):
        manifest = runner.write_manifest(str(tmp_path), "iter_001", results=[])
        assert manifest["status"] == "no_records"
        assert manifest["output_path"] is None
        assert manifest["best_score"] is None

    def test_write_manifest_results_with_none_score_emits_no_records(self, tmp_path):
        # Workflow returned a result object but every round failed → score is None.
        results = [_StubResult("c8_test_arch_a", score=None)]
        manifest = runner.write_manifest(str(tmp_path), "iter_001", results)
        assert manifest["status"] == "no_records"
        assert manifest["output_path"] is None
        assert manifest["best_score"] is None

    def test_write_manifest_completed_path_unchanged(self, tmp_path):
        results = [_StubResult("c8_test_arch_a", score=0.71)]
        manifest = runner.write_manifest(str(tmp_path), "iter_001", results)
        assert manifest["status"] == "completed"
        assert manifest["best_score"] == 0.71

    def test_write_manifest_records_consumed_health_checks_config(self, tmp_path):
        path = "configs/health_checks_baseline_observe_mode.yaml"
        results = [
            _StubResult(
                "c8_test_arch_a",
                score=0.71,
                health_checks_config=path,
            )
        ]
        manifest = runner.write_manifest(str(tmp_path), "iter_001", results)
        assert manifest["health_checks_config"] == path

    def test_write_manifest_mirrors_resolved_formal_thresholds(self, tmp_path):
        results = [
            _StubResult(
                "c8_test_arch_a",
                score=0.71,
                formal_reference_score=6.0,
                resolved_skip_formal_threshold=6.2,
                resolved_bypass_formal_threshold=6.7,
            )
        ]
        manifest = runner.write_manifest(str(tmp_path), "iter_001", results)
        assert manifest["formal_reference_score"] == 6.0
        assert manifest["resolved_skip_formal_threshold"] == 6.2
        assert manifest["resolved_bypass_formal_threshold"] == 6.7

    def test_write_manifest_crashed_forces_failed_regardless_of_results(self, tmp_path):
        # Crash path: even if results is non-empty, crashed=True forces failed.
        results = [_StubResult("c8_test_arch_a", score=0.71)]
        manifest = runner.write_manifest(
            str(tmp_path),
            "iter_001",
            results,
            crashed=True,
        )
        assert manifest["status"] == "failed"
        assert manifest["output_path"] is None
        assert manifest["best_score"] is None

    def test_main_empty_results_exits_zero_and_writes_no_records(
        self,
        tmp_path,
        isolated_registries,
        capsys,
    ):
        seed = self._seed_file(tmp_path)
        with patch.object(runner, "run_workflow", return_value=[]):
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "1",
                    "--seed_paths",
                    str(seed),
                ]
            )

        assert code == 0, "no_records exit must be 0 so set -e doesn't halt the chain"
        # Manifest on disk shows no_records.
        manifest_path = tmp_path / "iter_001" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["status"] == "no_records"
        assert manifest["output_path"] is None
        # Operator-facing CHAIN message printed.
        out = capsys.readouterr().out
        assert "[CHAIN] No models passed gates" in out

    def test_main_workflow_exception_still_exits_one(
        self,
        tmp_path,
        isolated_registries,
        capsys,
    ):
        seed = self._seed_file(tmp_path)
        with patch.object(
            runner,
            "run_workflow",
            side_effect=RuntimeError("simulated workflow crash"),
        ):
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "1",
                    "--seed_paths",
                    str(seed),
                ]
            )

        assert code == 1, "true crashes must still halt the chain"
        # Manifest on disk shows failed.
        manifest_path = tmp_path / "iter_001" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["status"] == "failed"

    def test_chain_continues_past_no_records_iter(
        self,
        tmp_path,
        isolated_registries,
    ):
        """End-to-end wiring: an iter_001 with status='no_records' on disk
        must let restore_prior_state in iter_002 skip cleanly and reach
        run_workflow (no ResumeError raised)."""
        # Materialise iter_001 as no_records (no run_output, no plugin file).
        iter1_dir = tmp_path / "iter_001"
        iter1_dir.mkdir()
        (iter1_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "status": "no_records",
                    "iteration_dir": str(iter1_dir),
                    "output_path": None,
                    "model_name": None,
                    "best_score": None,
                }
            )
        )

        seed = self._seed_file(tmp_path)
        with patch.object(runner, "run_workflow") as mock_wf:
            mock_wf.return_value = [_StubResult("c8_test_arch_b", score=0.78)]
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "2",
                    "--seed_paths",
                    str(seed),
                ]
            )

        assert code == 0
        # run_workflow was actually invoked — restore did not raise on no_records.
        mock_wf.assert_called_once()
        kwargs = mock_wf.call_args.kwargs
        # source_paths = seeds only (no iter_001 output to absorb).
        assert kwargs["source_paths"] == [str(seed)]
        assert kwargs["run_name"] == "iter_002"


# ===========================================================================
# Pseudo-mode factory wiring — Stage 3 / Commit 4.5
# ===========================================================================


class TestPseudoModeFactoryWiring:
    """``--is_pseudo_llm`` / ``--is_pseudo_training`` select the correct
    factory class and forward it to ``run_workflow`` via the
    ``bridge_factory`` / ``sandbox_factory`` kwargs (landed in C1).

    The four tests cover the four reachable combinations
    (real/stub × real/stub) so any future refactor that drops a flag
    or mis-routes a factory fails here, not in production. The
    ``--is_pseudo_llm`` + ``--is_pseudo_training`` combination
    additionally asserts the loud ``[PSEUDO-MODE ACTIVE]`` stderr
    banner so a $0-cost smoke run cannot be mistaken for a real chain.
    """

    def _seed(self, tmp_path):
        seed = tmp_path / "seed.json"
        seed.write_text(
            json.dumps(
                {
                    "run_name": "seed",
                    "model_type": "punet",
                    "file_index": 6,
                    "status": "completed",
                    "completed_rounds": 1,
                    "total_attempts": 1,
                    "started_at": "x",
                    "finished_at": "y",
                }
            )
        )
        return seed

    def _invoke(self, tmp_path, *extra_flags):
        seed = self._seed(tmp_path)
        with (
            patch.object(runner, "run_workflow") as mock_wf,
            patch.object(
                runner,
                "write_manifest",
                return_value={
                    "status": "completed",
                    "model_name": "c8_test_arch_a",
                    "best_score": 0.7,
                    "output_path": "x",
                },
            ),
        ):
            mock_wf.return_value = [_StubResult("c8_test_arch_a")]
            code = _run_main(
                [
                    "--workspace",
                    str(tmp_path),
                    "--start_iteration",
                    "1",
                    "--seed_paths",
                    str(seed),
                    *extra_flags,
                ]
            )
        return code, mock_wf.call_args.kwargs

    def test_default_args_pass_no_factories(self, tmp_path, isolated_registries):
        code, kwargs = self._invoke(tmp_path)
        assert code == 0
        assert kwargs["bridge_factory"] is None
        assert kwargs["sandbox_factory"] is None

    def test_is_pseudo_llm_swaps_bridge_only(self, tmp_path, isolated_registries):
        from agent.llm_bridge import StubLLMBridge

        code, kwargs = self._invoke(tmp_path, "--is_pseudo_llm")
        assert code == 0
        assert kwargs["bridge_factory"] is StubLLMBridge
        assert kwargs["sandbox_factory"] is None

    def test_is_pseudo_training_swaps_sandbox_only(self, tmp_path, isolated_registries):
        from core.sandbox_executor import StubSandbox

        code, kwargs = self._invoke(tmp_path, "--is_pseudo_training")
        assert code == 0
        assert kwargs["bridge_factory"] is None
        assert kwargs["sandbox_factory"] is StubSandbox

    def test_both_flags_swap_both_factories_and_warn_on_stderr(
        self,
        tmp_path,
        isolated_registries,
        capsys,
    ):
        from agent.llm_bridge import StubLLMBridge
        from core.sandbox_executor import StubSandbox

        code, kwargs = self._invoke(
            tmp_path,
            "--is_pseudo_llm",
            "--is_pseudo_training",
        )
        assert code == 0
        assert kwargs["bridge_factory"] is StubLLMBridge
        assert kwargs["sandbox_factory"] is StubSandbox
        err = capsys.readouterr().err
        assert "[PSEUDO-MODE ACTIVE]" in err
        assert "LLM + training" in err


class TestLitReviewCLI:
    """Commit 6 sub-step 6f (commit 596b206, 2026-06-12) — the two
    ``--ml_lit_review_*`` CLI flags.

    Design Decision 1 (2026-06-11): the ``--ml_*`` prefix is enforced —
    argparse REJECTS the pre-rename name ``--lit_review_enabled``.

    Design Decision 2 (2026-06-11): ``--ml_lit_review_config`` lets
    operators point at a non-default YAML without editing the default
    file."""

    def _argv(self, *extra):
        return [
            "--workspace",
            "/tmp/ws",
            "--run_name",
            "iter_001",
            "--seed_paths",
            "/tmp/seed.json",
            "--start_iteration",
            "1",
            *extra,
        ]

    def test_ml_lit_review_enabled_yields_true(self):
        args = runner.build_parser().parse_args(self._argv("--ml_lit_review_enabled"))
        assert args.ml_lit_review_enabled is True

    def test_no_ml_lit_review_enabled_yields_false(self):
        args = runner.build_parser().parse_args(self._argv("--no-ml_lit_review_enabled"))
        assert args.ml_lit_review_enabled is False

    def test_neither_flag_yields_none_sentinel(self):
        """BooleanOptionalAction signals 'fall through to YAML' with None
        when neither --ml_lit_review_enabled nor --no-ml_lit_review_enabled
        is passed. main() handles None by peeking at the YAML's `enabled`
        key (see 6f resolution logic)."""
        args = runner.build_parser().parse_args(self._argv())
        assert args.ml_lit_review_enabled is None

    def test_pre_rename_name_rejected_with_systemexit(self):
        """The pre-rename name --lit_review_enabled (without the ml_ prefix)
        is REJECTED by argparse — confirms Design Decision 1's naming
        convention is enforced, not just documented."""
        with pytest.raises(SystemExit):
            runner.build_parser().parse_args(self._argv("--lit_review_enabled"))

    def test_ml_lit_review_config_passthrough(self):
        """A custom --ml_lit_review_config path threads through verbatim
        to args.ml_lit_review_config (Design Decision 2)."""
        args = runner.build_parser().parse_args(
            self._argv("--ml_lit_review_config", "/path/to/other.yaml")
        )
        assert args.ml_lit_review_config == "/path/to/other.yaml"

    def test_ml_lit_review_config_default(self):
        """Default --ml_lit_review_config value is the canonical
        configs/lit_review_config.yaml path."""
        args = runner.build_parser().parse_args(self._argv())
        assert args.ml_lit_review_config == "configs/lit_review_config.yaml"


# ===========================================================================
# DS6c — DataScope + HealthGate chain CLI
# ===========================================================================

from core.run_invariants import RunInvariants  # noqa: E402
from execute_tools.dataset_config import DataScope  # noqa: E402

_BASE = ["--workspace", "WS", "--start_iteration", "1", "--run_name", "iter_001"]


def _normalized(*extra):
    return runner.normalize_args(runner.build_parser().parse_args([*_BASE, *extra]))


class TestDataScopeCLI:
    def test_defaults(self):
        args = _normalized()
        assert args.data_scope is None
        assert args.health_gate_enabled is True
        assert args.health_gate_files is None

    def test_range_and_list_forms_canonicalize_identically(self):
        a = _normalized("--data_scope", "4-9")
        b = _normalized("--data_scope", "4,5,6,7,8,9")
        assert a.data_scope == b.data_scope == DataScope(file_indices=[4, 5, 6, 7, 8, 9])

    def test_mixed_form_and_files_parse(self):
        args = _normalized(
            "--data_scope", "0-3,7", "--health_gate_files", "1,3", "--no-health_gate_enabled"
        )
        assert args.data_scope.file_indices == [0, 1, 2, 3, 7]
        assert args.health_gate_files == [1, 3]
        assert args.health_gate_enabled is False

    def test_malformed_scope_is_a_parser_error(self, capsys):
        with pytest.raises(SystemExit) as e:
            _normalized("--data_scope", "4-x")
        assert e.value.code == 2
        assert "malformed" in capsys.readouterr().err


class TestComputeExpectedInvariants:
    def test_default_full_scope_materializes(self, tmp_path):
        args = _normalized()
        args.workspace = str(tmp_path)
        inv = runner.compute_expected_invariants(args)
        assert isinstance(inv, RunInvariants)
        assert inv.resolved_data_scope == list(range(20))
        assert inv.health_gate_enabled is True
        assert inv.health_config_sha256 is not None
        assert os.path.isfile(os.path.join(str(tmp_path), "health_checks_effective.yaml"))

    def test_disabled_gates_null_sha_no_file(self, tmp_path):
        args = _normalized("--no-health_gate_enabled", "--data_scope", "4-9")
        args.workspace = str(tmp_path)
        inv = runner.compute_expected_invariants(args)
        assert inv.resolved_data_scope == [4, 5, 6, 7, 8, 9]
        assert inv.health_config_sha256 is None
        assert not os.path.exists(os.path.join(str(tmp_path), "health_checks_effective.yaml"))

    def test_partial_scope_without_files_fails(self, tmp_path):
        args = _normalized("--data_scope", "4-9")
        args.workspace = str(tmp_path)
        with pytest.raises(ValueError):
            runner.compute_expected_invariants(args)


class TestDataScopeChainWiring:
    """DS6c wiring through main(): invariants computed before restore, the
    three params reach run_workflow, and a conflicting second invocation
    fails at startup with a crashed manifest."""

    def _main(self, tmp_path, *extra):
        argv = [
            "--workspace",
            str(tmp_path),
            "--start_iteration",
            "1",
            "--run_name",
            "iter_001",
            *extra,
        ]
        with patch.object(runner, "run_workflow") as mock_wf:
            mock_wf.return_value = [_StubResult("c8_test_arch_a")]
            code = _run_main(argv)
        return code, mock_wf

    def test_scope_and_gates_reach_workflow(self, tmp_path):
        code, mock_wf = self._main(tmp_path, "--data_scope", "4-9", "--health_gate_files", "4,7,9")
        assert code == 0
        kwargs = mock_wf.call_args.kwargs
        assert kwargs["data_scope"] == DataScope(file_indices=[4, 5, 6, 7, 8, 9])
        assert kwargs["health_gate_enabled"] is True
        assert kwargs["health_gate_files"] == [4, 7, 9]
        # Invariants were materialized into the chain root pre-restore.
        assert os.path.isfile(os.path.join(str(tmp_path), "health_checks_effective.yaml"))

    def test_conflicting_second_invocation_crashes_before_workflow(self, tmp_path):
        code, _ = self._main(tmp_path, "--data_scope", "4-9", "--health_gate_files", "4,7,9")
        assert code == 0
        # Same workspace, different monitored files → the materialized-config
        # immutability guard fires inside compute_expected_invariants, before
        # restore/run_workflow; the runner writes a crashed manifest.
        code2, mock_wf2 = self._main(tmp_path, "--data_scope", "4-9", "--health_gate_files", "5,8")
        assert code2 == 1
        mock_wf2.assert_not_called()
        manifest = json.loads((tmp_path / "iter_001" / "manifest.json").read_text())
        assert manifest["status"] == "failed"


class TestManifestInvariantStamps:
    def test_completed_manifest_carries_stamps(self, tmp_path):
        stub = _StubResult("c8_test_arch_a")
        stub.resolved_data_scope = [4, 5, 6, 7, 8, 9]
        stub.health_gate_enabled = True
        stub.health_config_sha256 = "e" * 64
        iter_dir = tmp_path / "iter_001"
        iter_dir.mkdir()
        manifest = runner.write_manifest(str(iter_dir), "iter_001", results=[stub])
        assert manifest["resolved_data_scope"] == [4, 5, 6, 7, 8, 9]
        assert manifest["health_gate_enabled"] is True
        assert manifest["health_config_sha256"] == "e" * 64


class TestDeprecatedStrategyFlags:
    """DS7 — --trial_strategy / --target_files are accepted no-ops: warn
    when non-default, never reach run_workflow."""

    def test_non_default_values_warn(self):
        with pytest.warns(DeprecationWarning, match="deprecated and IGNORED"):
            _normalized("--trial_strategy", "anchors")
        with pytest.warns(DeprecationWarning, match="deprecated and IGNORED"):
            _normalized("--target_files", "3", "7")

    def test_defaults_do_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            _normalized()

    def test_deprecated_values_never_reach_run_workflow(self, tmp_path):
        argv = [
            "--workspace",
            str(tmp_path),
            "--start_iteration",
            "1",
            "--run_name",
            "iter_001",
            "--trial_strategy",
            "anchors",
        ]
        with patch.object(runner, "run_workflow") as mock_wf:
            mock_wf.return_value = [_StubResult("c8_test_arch_a")]
            with pytest.warns(DeprecationWarning):
                code = _run_main(argv)
        assert code == 0
        kwargs = mock_wf.call_args.kwargs
        assert "trial_strategy" not in kwargs
        assert "target_files" not in kwargs
        assert "eval_strategy" not in kwargs


# ---------------------------------------------------------------------------
# V19 PR 1 (P1-C3) — manifest incumbent stamps, artifact hash, and the
# operator-specified three-iteration separation test (design doc §3.1
# Invariant II + §3.4 equivalence, on-disk half).
# ---------------------------------------------------------------------------

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput  # noqa: E402
from core.resume import restore_prior_state  # noqa: E402


def _p1_record(exp_id: str, score: float | None) -> dict:
    """Minimal schema-valid formal ExperimentRecord with the DS5 waiver
    stamp (health_gate_enabled=False → commit-time VALID)."""
    return {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-07-27 00:00:00",
        "params": {},
        "denoising_score": score,
        "health_gate_results": [],
        "health_gate_enabled": False,
    }


def _p1_tune_output(
    run_name: str,
    *,
    valid_formal: float | None,
    exp_id: str | None,
    records: list[dict],
) -> HyperparamTuningOutput:
    return HyperparamTuningOutput(
        run_name=run_name,
        model_type="punet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        best_denoising_score=(records[0]["denoising_score"] if records else None),
        all_records=records,
        best_valid_formal_denoising_score=valid_formal,
        best_valid_formal_exp_id=exp_id,
        started_at="2026-07-27 00:00:00",
        finished_at="2026-07-27 00:00:01",
    )


def _p1_write_iter_output(workspace: str, iter_idx: int, output: HyperparamTuningOutput) -> str:
    run_name = f"iter_{iter_idx:03d}"
    model_dir = os.path.join(workspace, run_name, "iteration_001", "punet")
    os.makedirs(model_dir, exist_ok=True)
    path = os.path.join(model_dir, f"run_output_{run_name}.json")
    with open(path, "w") as f:
        f.write(output.model_dump_json())
    return path


class TestChainIncumbentManifest:
    def test_three_iteration_separation_and_attribution(self, tmp_path):
        """iter 1 commits a valid formal; iter 2 has NO valid formal of its
        own but consumes iter 1's score as its chain reference; iter 2's
        local best stays None while the chain stamps carry the incumbent;
        iter 3's reconstruction still attributes the source to iter 1."""
        ws = str(tmp_path)

        # --- iter 1: valid formal 1.2 ---
        out1 = _p1_tune_output(
            "iter_001",
            valid_formal=1.2,
            exp_id="f1",
            records=[_p1_record("f1", 1.2)],
        )
        _p1_write_iter_output(ws, 1, out1)
        m1 = runner.write_manifest(os.path.join(ws, "iter_001"), "iter_001", [out1])
        assert m1["best_valid_formal_score"] == 1.2
        assert "run_output_sha256" in m1  # §3.6 immutable artifact identity

        # --- iter 2 startup: reconstruction (the chained-equivalence half:
        # the on-disk walk yields exactly iter 1's committed valid formal,
        # matching the in-process rule tested in test_model_exploration) ---
        state2 = restore_prior_state(ws, 2, seed_paths=[])
        assert state2.chain_best_valid_formal_score == 1.2
        assert state2.chain_best_valid_formal_provenance["iter_idx"] == 1
        assert state2.chain_best_valid_formal_provenance["artifact_verified"] is True

        # --- iter 2: NO valid formal of its own; consumed iter 1's ref
        # (flag-ON scenario) ---
        out2 = _p1_tune_output(
            "iter_002",
            valid_formal=None,
            exp_id=None,
            records=[_p1_record("f2", 0.3)],
        )
        _p1_write_iter_output(ws, 2, out2)
        m2 = runner.write_manifest(
            os.path.join(ws, "iter_002"),
            "iter_002",
            [out2],
            chain_incumbent_used=state2.chain_best_valid_formal_score,
            chain_incumbent_source=state2.chain_best_valid_formal_provenance,
        )
        # Invariant II: iteration-local best stays None…
        assert m2["best_valid_formal_score"] is None
        # …while the chain stamps live under their OWN keys.
        assert m2["chain_incumbent_used"] == 1.2
        assert m2["chain_incumbent_source"]["iter_idx"] == 1

        # --- iter 3: attribution still names iter 1, not iter 2 ---
        state3 = restore_prior_state(ws, 3, seed_paths=[])
        assert state3.chain_best_valid_formal_score == 1.2
        assert state3.chain_best_valid_formal_provenance["iter_idx"] == 1

    def test_flag_off_stamps_source_but_not_used(self, tmp_path):
        """Rollback semantics: reconstruction provenance is stamped even
        when consumption is OFF; ``chain_incumbent_used`` is null."""
        ws = str(tmp_path)
        out1 = _p1_tune_output(
            "iter_001", valid_formal=1.2, exp_id="f1", records=[_p1_record("f1", 1.2)]
        )
        _p1_write_iter_output(ws, 1, out1)
        runner.write_manifest(os.path.join(ws, "iter_001"), "iter_001", [out1])
        state = restore_prior_state(ws, 2, seed_paths=[])

        out2 = _p1_tune_output(
            "iter_002", valid_formal=None, exp_id=None, records=[_p1_record("f2", 0.3)]
        )
        _p1_write_iter_output(ws, 2, out2)
        m2 = runner.write_manifest(
            os.path.join(ws, "iter_002"),
            "iter_002",
            [out2],
            chain_incumbent_used=None,  # flag OFF: gates consumed nothing
            chain_incumbent_source=state.chain_best_valid_formal_provenance,
        )
        assert m2["chain_incumbent_used"] is None
        assert m2["chain_incumbent_source"]["iter_idx"] == 1

    def test_manifest_mirrors_best_valid_trial_score(self, tmp_path):
        """V19 PR 1 (P1-C4): the read-only trial-best bookkeeping mirrors
        into the manifest; absent on the output → null in the manifest."""
        ws = str(tmp_path)
        out1 = _p1_tune_output(
            "iter_001", valid_formal=1.2, exp_id="f1", records=[_p1_record("f1", 1.2)]
        )
        out1.best_valid_trial_denoising_score = 0.5
        out1.best_valid_trial_exp_id = "t1"
        _p1_write_iter_output(ws, 1, out1)
        m1 = runner.write_manifest(os.path.join(ws, "iter_001"), "iter_001", [out1])
        assert m1["best_valid_trial_score"] == 0.5

        out2 = _p1_tune_output(
            "iter_002", valid_formal=None, exp_id=None, records=[_p1_record("f2", 0.3)]
        )
        _p1_write_iter_output(ws, 2, out2)
        m2 = runner.write_manifest(os.path.join(ws, "iter_002"), "iter_002", [out2])
        assert m2["best_valid_trial_score"] is None
