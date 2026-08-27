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

import hashlib
import json
import os
import pathlib
import sys
import textwrap
import warnings
from unittest.mock import patch

import pytest

from sdsc_submission_scripts import run_one_iteration as runner
from tests.helpers.launcher_bindings import effective_workflow_kwargs

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

    @pytest.mark.parametrize("flag", ["--trial_max_epochs", "--formal_max_epochs"])
    @pytest.mark.parametrize("bad", ["0", "-1"])
    def test_per_mode_epoch_cap_zero_or_negative_is_rejected(self, capsys, flag, bad):
        """D-BUD-6 witness (d): a nonsensical per-mode ceiling refuses at
        PARSE time, before any launch work — same ``_positive_int`` contract
        as --max_epochs. A silently-accepted 0 would disable training for
        one round role while the launch exits 0."""
        with pytest.raises(SystemExit):
            runner.build_parser().parse_args(
                self._minimal_argv("--start_iteration", "1", flag, bad)
            )
        err = capsys.readouterr().err
        assert ">= 1" in err or "positive integer" in err

    def test_per_mode_epoch_caps_parse_and_default(self):
        """D-BUD-6 witness (c), app-argparse layer: the campaign pair lands
        as trial=2 / formal=1 on the Namespace, and the flags OMITTED land
        as None (the mode-agnostic --max_epochs then governs both roles —
        the legacy posture)."""
        args = runner.build_parser().parse_args(
            self._minimal_argv(
                "--start_iteration",
                "1",
                "--trial_max_epochs",
                "2",
                "--formal_max_epochs",
                "1",
            )
        )
        assert args.trial_max_epochs == 2
        assert args.formal_max_epochs == 1
        bare = runner.build_parser().parse_args(self._minimal_argv("--start_iteration", "1"))
        assert bare.trial_max_epochs is None
        assert bare.formal_max_epochs is None
        assert bare.max_epochs == 1

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


#: An existing directory for the wiring harness's dataset preflight. The
#: repository root always exists and is never read as data by these tests —
#: `run_workflow` is mocked out, so nothing opens a file under it.
_WIRING_DATA_DIR = pathlib.Path(__file__).resolve().parents[3]


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
    # V20 PR D (D-C1b): the formal-launch policy declarations, synthesised
    # for the same reason as --run_name below — the production chain shell
    # always supplies them, and these tests target the runner's argparse +
    # wiring layer, not the launch-policy refusal. The refusal itself is
    # tested directly in test_formal_launch_policy.py, which builds its
    # argv explicitly and does NOT go through this helper.
    if "--healthgate_mode" not in argv:
        argv = [*argv, "--healthgate_mode", "blocking"]
    if "--result_authority" not in argv:
        argv = [*argv, "--result_authority", "scientific"]
    if "--run_name" not in argv:
        iter_n = 1
        for flag in ("--start_iteration", "--iteration"):
            if flag in argv:
                iter_n = int(argv[argv.index(flag) + 1])
                break
        argv = ["--run_name", f"iter_{iter_n:03d}", *argv]
    # Dataset-directory preflight: `main()` now resolves and VALIDATES the
    # physical data directory before any expensive work, so a wiring test
    # must name one that exists. Synthesised here for the same reason as the
    # declarations above — these tests target the argparse + wiring layer,
    # not the dataset preflight, and CI has no dataset. The preflight's own
    # behaviour (resolution, precedence, refusal) is tested directly in
    # test_gate_data_dir_resolution.py, which does NOT use this helper.
    if "--data_dir" not in argv:
        argv = [*argv, "--data_dir", str(_WIRING_DATA_DIR)]
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
        kwargs = effective_workflow_kwargs(mock_wf.call_args)
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
                        # D-C1b: this test drives the OBSERVE-ONLY config, so
                        # it must declare the matching posture. The helper's
                        # default `blocking` would be refused as a
                        # declaration/config mismatch — which is the check
                        # doing its job, not a test defect.
                        "--healthgate_mode",
                        "observe_only",
                        "--result_authority",
                        "diagnostic",
                    ]
                )

        assert code == 0
        assert effective_workflow_kwargs(mock_wf.call_args)["health_checks_config"] == health_path

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
        kwargs = effective_workflow_kwargs(mock_wf.call_args)
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
        kwargs = effective_workflow_kwargs(mock_wf.call_args)
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
        kwargs = effective_workflow_kwargs(mock_wf.call_args)
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

    @pytest.mark.parametrize(
        "kwargs,results",
        [
            ({}, []),
            ({}, [_StubResult("c8_test_arch_a", score=None)]),
            ({}, [_StubResult("c8_test_arch_a", score=0.71)]),
            ({"crashed": True}, [_StubResult("c8_test_arch_a", score=0.71)]),
        ],
        ids=["no_records", "none_score", "completed", "crashed"],
    )
    def test_manifest_records_the_preflight_execution_mode(self, tmp_path, kwargs, results):
        """V20 PR A §11 — pre-flight provenance, on every branch.

        Stamped for the same reason as ``health_feedback_policy``: a
        crashed iteration is exactly when an auditor needs to know how
        the pre-flight ran, so the field must not be confined to the
        happy path.
        """
        manifest = runner.write_manifest(str(tmp_path), "iter_001", results, **kwargs)
        assert manifest["preflight_execution_mode"] == "isolated_subprocess"

    def test_preflight_mode_is_imported_from_the_adapter_not_a_literal(self, tmp_path):
        """The manifest must not be able to claim a mechanism the build
        does not ship. Tying the value to the module that *is* the
        isolated path means the two cannot drift apart independently."""
        from agent.skills.evaluate_vram_skill import preflight_adapter

        manifest = runner.write_manifest(
            str(tmp_path), "iter_001", [_StubResult("c8_test_arch_a", score=0.71)]
        )
        assert manifest["preflight_execution_mode"] is preflight_adapter.PREFLIGHT_EXECUTION_MODE

    def test_preflight_mode_survives_the_json_round_trip(self, tmp_path):
        """The manifest is a handoff file, so the field has to be on disk,
        not merely in the returned dict."""
        runner.write_manifest(
            str(tmp_path), "iter_001", [_StubResult("c8_test_arch_a", score=0.71)]
        )
        on_disk = json.loads((tmp_path / "manifest.json").read_text())
        assert on_disk["preflight_execution_mode"] == "isolated_subprocess"

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
        kwargs = effective_workflow_kwargs(mock_wf.call_args)
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
        return code, effective_workflow_kwargs(mock_wf.call_args)

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
    never reaches the workflow — refused at launch since S2 / U5 (#258),
    or crashing on the immutability guard when the rerun is explicit."""

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
        kwargs = effective_workflow_kwargs(mock_wf.call_args)
        assert kwargs["data_scope"] == DataScope(file_indices=[4, 5, 6, 7, 8, 9])
        assert kwargs["health_gate_enabled"] is True
        assert kwargs["health_gate_files"] == [4, 7, 9]
        # Invariants were materialized into the chain root pre-restore.
        assert os.path.isfile(os.path.join(str(tmp_path), "health_checks_effective.yaml"))

    def test_a_second_launch_into_a_committed_iteration_is_refused_before_workflow(self, tmp_path):
        """S2 / U5 (#258). Before write-once this test asserted that the
        conflicting rerun wrote a ``failed`` manifest — i.e. that it
        OVERWROTE the committed iteration's handoff. That is the hazard
        #258 forbids. The committed manifest must survive byte-for-byte and
        the rerun is refused at launch, before the invariants guard, the
        restore or the workflow can run.

        Re-scoped by the #258 refinement (operator ruling): this refusal is
        a property of the COMPLETED manifest specifically — matrix row A in
        ``TestAutoResumeRecovery`` proves ``--auto_resume`` does not lift
        it, while a ``failed``/``no_records`` slot IS the auto-resume
        recovery case (rows D/E)."""
        code, _ = self._main(tmp_path, "--data_scope", "4-9", "--health_gate_files", "4,7,9")
        assert code == 0
        manifest_path = tmp_path / "iter_001" / "manifest.json"
        first = manifest_path.read_bytes()
        assert json.loads(first)["status"] == "completed"

        code2, mock_wf2 = self._main(tmp_path, "--data_scope", "4-9", "--health_gate_files", "5,8")
        assert code2 == 2
        mock_wf2.assert_not_called()
        assert manifest_path.read_bytes() == first

    def test_an_explicit_replacement_still_crashes_on_the_conflicting_config(self, tmp_path):
        """The original property, kept: with the replacement requested, the
        materialized-config immutability guard fires inside
        compute_expected_invariants before restore/run_workflow. The crashed
        manifest now carries the replacement provenance, and the committed
        one is set aside rather than destroyed."""
        code, _ = self._main(tmp_path, "--data_scope", "4-9", "--health_gate_files", "4,7,9")
        assert code == 0
        first = (tmp_path / "iter_001" / "manifest.json").read_bytes()

        code2, mock_wf2 = self._main(
            tmp_path,
            "--data_scope",
            "4-9",
            "--health_gate_files",
            "5,8",
            "--replace_iteration_manifest",
            "--replacement_reason",
            "conflicting rerun (test)",
        )
        assert code2 == 1
        mock_wf2.assert_not_called()
        manifest = json.loads((tmp_path / "iter_001" / "manifest.json").read_text())
        assert manifest["status"] == "failed"
        prov = manifest["manifest_replacement"]
        assert prov["replacement_reason"] == "conflicting rerun (test)"
        assert prov["previous_manifest_status"] == "completed"
        assert prov["previous_manifest_sha256"] == hashlib.sha256(first).hexdigest()
        assert (tmp_path / "iter_001" / prov["previous_manifest_path"]).read_bytes() == first

    def test_the_replacement_flag_without_a_reason_is_refused_at_launch(self, tmp_path):
        code, mock_wf = self._main(tmp_path, "--replace_iteration_manifest")
        assert code == 2
        mock_wf.assert_not_called()
        assert not (tmp_path / "iter_001" / "manifest.json").exists()


class TestAutoResumeRecovery:
    """#258 refinement (operator ruling, 2026-08-24): ``--auto_resume`` is
    recovery intent for a FAILED / NO_RECORDS same-iteration manifest ONLY,
    routed through the EXISTING explicit replacement path with provenance.
    A completed manifest stays immutable; without the flag, nothing changed.
    Matrix rows A-E; row F is unit-level in ``test_manifest_write_once.py``.
    """

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

    def _seed(self, tmp_path, *, crashed):
        """A terminal failed (crashed=True) or no_records manifest at iter_001."""
        iter_dir = tmp_path / "iter_001"
        iter_dir.mkdir()
        runner.write_manifest(str(iter_dir), "iter_001", results=[], crashed=crashed)
        return (iter_dir / "manifest.json").read_bytes()

    @staticmethod
    def _replaced_files(tmp_path):
        return [n for n in os.listdir(tmp_path / "iter_001") if n.startswith("manifest.replaced.")]

    def test_matrix_a_completed_plus_auto_resume_is_still_refused(self, tmp_path):
        """Row A. PLANT TARGET: a naive rule that auto-replaces ANY existing
        manifest turns this RED — the completed handoff would be set aside
        and the iteration rerun."""
        code, _ = self._main(tmp_path)
        assert code == 0
        manifest_path = tmp_path / "iter_001" / "manifest.json"
        first = manifest_path.read_bytes()
        assert json.loads(first)["status"] == "completed"

        code2, wf2 = self._main(tmp_path, "--auto_resume")
        assert code2 == 2
        wf2.assert_not_called()
        assert manifest_path.read_bytes() == first
        assert self._replaced_files(tmp_path) == []

    def test_matrix_b_failed_without_recovery_intent_is_refused(self, tmp_path):
        """Row B: write-once holds — a failed slot still needs EXPLICIT
        intent (the flag, or the operator's replacement op)."""
        first = self._seed(tmp_path, crashed=True)
        code, wf = self._main(tmp_path)
        assert code == 2
        wf.assert_not_called()
        assert (tmp_path / "iter_001" / "manifest.json").read_bytes() == first

    def test_matrix_c_no_records_without_recovery_intent_is_refused(self, tmp_path):
        first = self._seed(tmp_path, crashed=False)
        code, wf = self._main(tmp_path)
        assert code == 2
        wf.assert_not_called()
        assert (tmp_path / "iter_001" / "manifest.json").read_bytes() == first

    def test_matrix_d_failed_plus_auto_resume_replaces_with_provenance(self, tmp_path):
        """Row D — the bounded flow: auto-resume + terminal 'failed' → the
        EXISTING replacement path. The evidence establishes a prior manifest
        existed, its prior terminal state, WHY this write happened (the
        recognizable reason), and which bytes were replaced — a failed
        manifest carries no artifact hash, but its history is not erasable."""
        first = self._seed(tmp_path, crashed=True)
        code, _ = self._main(tmp_path, "--auto_resume")
        assert code == 0
        manifest = json.loads((tmp_path / "iter_001" / "manifest.json").read_text())
        assert manifest["status"] == "completed"
        prov = manifest["manifest_replacement"]
        assert prov["replacement_reason"].startswith("auto_resume recovery")
        assert "'failed'" in prov["replacement_reason"]
        assert prov["previous_manifest_status"] == "failed"
        assert prov["previous_manifest_sha256"] == hashlib.sha256(first).hexdigest()
        assert prov["previous_run_output_sha256"] is None
        set_aside = tmp_path / "iter_001" / prov["previous_manifest_path"]
        assert set_aside.read_bytes() == first

    def test_matrix_e_no_records_plus_auto_resume_replaces_with_provenance(self, tmp_path):
        first = self._seed(tmp_path, crashed=False)
        code, _ = self._main(tmp_path, "--auto_resume")
        assert code == 0
        manifest = json.loads((tmp_path / "iter_001" / "manifest.json").read_text())
        prov = manifest["manifest_replacement"]
        assert prov["previous_manifest_status"] == "no_records"
        assert prov["previous_manifest_sha256"] == hashlib.sha256(first).hexdigest()
        assert prov["replacement_reason"].startswith("auto_resume recovery")
        assert "'no_records'" in prov["replacement_reason"]
        assert (tmp_path / "iter_001" / prov["previous_manifest_path"]).read_bytes() == first

    def test_an_unclassifiable_manifest_fails_closed_under_auto_resume(self, tmp_path):
        """Load-bearing beyond the matrix: a slot the launcher cannot
        classify as failed/no_records is NOT authorized — malformed history
        is never erased on a guess."""
        iter_dir = tmp_path / "iter_001"
        iter_dir.mkdir()
        (iter_dir / "manifest.json").write_bytes(b"{not json")
        code, wf = self._main(tmp_path, "--auto_resume")
        assert code == 2
        wf.assert_not_called()
        assert (iter_dir / "manifest.json").read_bytes() == b"{not json"

    def test_the_explicit_operator_reason_outranks_the_auto_reason(self, tmp_path):
        """The destructive replacement stays the separate operator-visible
        operation: given both, the provenance carries the operator's words,
        never the auto template."""
        self._seed(tmp_path, crashed=True)
        code, _ = self._main(
            tmp_path,
            "--auto_resume",
            "--replace_iteration_manifest",
            "--replacement_reason",
            "operator-directed rerun",
        )
        assert code == 0
        prov = json.loads((tmp_path / "iter_001" / "manifest.json").read_text())[
            "manifest_replacement"
        ]
        assert prov["replacement_reason"] == "operator-directed rerun"


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
        kwargs = effective_workflow_kwargs(mock_wf.call_args)
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
from execute_tools.evaluation_metric import TIDMAD_METRIC_ID  # noqa: E402
from tests.helpers.metric_fixtures import shipped_spec  # noqa: E402


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
        # Step 10 P2a C2 — a scored record carries the identity it was scored
        # under, and the chain fold reads it to decide which way is better.
        "metric_result": {
            "metric_id": TIDMAD_METRIC_ID,
            "direction": "higher",
            "scalar": score,
        },
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
        # Step 10 P2a C2: the chain incumbent fold builds its MetricOrder from
        # the run's stamped MetricSpec (Step 09a). An output without one is a
        # NAMED refusal rather than a re-derivation, so these attribution
        # tests stamp what a real post-09a output carries.
        metric_spec=shipped_spec(),
        # V20 PR D (D-C4): the chain incumbent now additionally requires
        # scientific authority. These tests are about incumbent
        # ATTRIBUTION in the manifest — which iteration a carried-over
        # score came from — so they declare the production posture the
        # chain shell supplies and keep testing attribution. An output
        # with no declaration is `unreconstructable_legacy` and yields no
        # incumbent at all; that case is covered in
        # tests/unit/core/test_resume_incumbent.py.
        healthgate_mode="blocking",
        result_authority="scientific",
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


class TestFormalLaunchPolicyIsEnforcedAtTheChainBoundary:
    """D-C1b reachability: the refusal must be on the REAL launch path.

    These build argv explicitly and do NOT go through `_run_main`, which
    synthesises the declarations the production shell supplies. A test that
    used the helper could not observe an omission.
    """

    def _main(self, argv):
        """Invoke the real `main()` and return its exit code."""
        import sys as _sys

        from sdsc_submission_scripts import run_one_iteration as runner

        argv = ["run_one_iteration.py", *argv]
        old = _sys.argv
        _sys.argv = argv
        try:
            runner.main()
            return 0
        except SystemExit as exc:
            return exc.code
        finally:
            _sys.argv = old

    def test_omitting_the_declarations_refuses_before_any_work(self, capsys, tmp_path):
        """THE REACHABILITY PROOF. Exit 2 with the refusal on stderr, and
        no iteration directory created — the refusal precedes even the
        failure-brake preflight, which is the first thing that touches
        disk."""
        ws = str(tmp_path / "ws")
        code = self._main(["--workspace", ws, "--run_name", "iter_001", "--start_iteration", "1"])

        assert code == 2
        assert "FORMAL LAUNCH REFUSED" in capsys.readouterr().err
        assert not os.path.exists(ws), "the refusal created a workspace"

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
    @pytest.mark.parametrize(
        "flag", ["--skip_formal_min_delta", "--bypass_formal_time_budget_min_delta"]
    )
    def test_a_non_finite_delta_refuses_before_any_work(self, capsys, tmp_path, flag, value):
        """FU-D-8 reachability, on the REAL launch path.

        `argparse(type=float)` happily parses 'nan'/'inf', so this reaches
        the validator exactly as an operator's CLI would. Without the
        refusal the run would proceed with both gates silently disabled
        while the artifact recorded an enforced launch.

        Same assertion as the declaration proof above: exit 2, refusal on
        stderr, and NO workspace on disk — so it precedes the failure-brake
        preflight, the LLM, model construction and the GPU.
        """
        ws = str(tmp_path / "ws")
        code = self._main(
            [
                "--workspace",
                ws,
                "--run_name",
                "iter_001",
                "--start_iteration",
                "1",
                "--healthgate_mode",
                "blocking",
                "--result_authority",
                "scientific",
                "--enable_chain_incumbent_formal_gates",
                # `=` form deliberately: argparse reads a bare `-inf` as a
                # flag because of the leading dash and errors out before
                # the validator. That path fails closed, so it is safe —
                # but it is not the path under test here.
                f"{flag}={value}",
            ]
        )

        assert code == 2
        err = capsys.readouterr().err
        assert "FORMAL LAUNCH REFUSED" in err
        assert "not finite" in err
        assert not os.path.exists(ws), "the refusal created a workspace"

    def test_the_contradiction_refuses_on_the_real_path(self, capsys, tmp_path):
        code = self._main(
            [
                "--workspace",
                str(tmp_path / "ws"),
                "--run_name",
                "iter_001",
                "--start_iteration",
                "1",
                "--healthgate_mode",
                "observe_only",
                "--result_authority",
                "scientific",
            ]
        )

        assert code == 2
        assert "contradiction" in capsys.readouterr().err

    def test_the_chain_shell_declares_blocking_scientific(self):
        """The launcher must actually supply what the boundary requires —
        otherwise this checkpoint would refuse every production launch.

        MUTATION TARGET: dropping either line from the argv assembly.
        """
        common = (
            pathlib.Path(__file__).resolve().parents[3]
            / "sdsc_submission_scripts"
            / "_chain_common.sh"
        ).read_text(encoding="utf-8")
        assert "HEALTHGATE_MODE=blocking" in common
        assert "RESULT_AUTHORITY=scientific" in common
        assert '--healthgate_mode "$HEALTHGATE_MODE"' in common
        assert '--result_authority "$RESULT_AUTHORITY"' in common
