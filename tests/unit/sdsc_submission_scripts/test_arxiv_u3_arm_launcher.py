"""arXiv U3 (#259 / #260) — the two-arm launcher and its operator surface.

What only these tests catch:

* ``TestArmDryRun`` — the launcher expresses each arm EXPLICITLY on the
  child argv (positive OR negative lit-review token; the arm label; the
  isolation flag only in the WITHOUT arm), wraps ``run_chain.sh`` /
  ``run_one_iteration.py`` (never the tuner node CLI, whose omitted
  ``--is_trial`` silently falls into legacy single-file mode — F-12d-26),
  ships no V20 advice file, prints the resolved configuration as JSON, and
  leaves an absent workspace absent.
* ``TestLauncherRefusals`` — every arm-decided or experiment-breaking flag
  is refused loudly rather than silently absorbed.
* ``TestH100Posture`` — the S3 contract: ``--h100`` sources
  ``h100_posture.env`` and splats ``H100_CHAIN_ARGS`` AFTER the launcher's
  own args; a missing file or a file without the array refuses by name.
  Exercised against a FIXTURE env file (S3's real file lives on its own
  branch and is absent here by design).
* ``TestChainCommonForwarding`` — the three-state lit-review forwarding:
  unset forwards NOTHING (legacy argv byte-identical), explicit negative
  forwards ``--no-ml_lit_review_enabled`` (the OFF arm recorded
  positively), positive forwards the positive token, a task-owned config path
  is transported unchanged; and
  ``--baseline_isolation`` forwards only when requested.
* ``TestPrintResolvedLaunchConfig`` — the print mode emits ONE JSON object,
  exits 0, and creates NOTHING (no workspace dir); an unresolvable
  identity exits 1 naming the config.
* ``TestManifestAndInvariants`` — ``baseline_isolation`` reaches the lock
  via ``compute_expected_invariants`` and the manifest under the omission
  rule.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_SDSC = _REPO / "sdsc_submission_scripts"
_LAUNCHER = _SDSC / "launch_prior_baseline_experiment.sh"
_ROI = _SDSC / "run_one_iteration.py"
_CHAIN_COMMON = _SDSC / "_chain_common.sh"

_spec = importlib.util.spec_from_file_location("run_one_iteration_for_u3_test", _ROI)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)


def _env() -> dict:
    env = dict(os.environ)
    env["SIDERIUS_PYTHON"] = sys.executable
    env["VIRTUAL_ENV"] = str(Path(sys.executable).parents[1])
    # THIS checkout must win over the shared venv's editable install (which
    # points at whatever clone it was installed from) — the portability rule:
    # a test must never validate another clone's code.
    env["PYTHONPATH"] = str(_REPO)
    return env


def _extract_json(stdout: str) -> dict:
    """The resolved-config JSON object, robust to import-time noise.

    ``json.dump(indent=2)`` starts the object on its own ``{`` line;
    plugin-loader chatter precedes it and run_chain's dry-run output
    follows it, so parse from the first lone ``{`` line after the banner.
    """
    marker = stdout.find("resolved launch configuration:")
    start = marker if marker >= 0 else 0
    idx = stdout.find("\n{", start)
    idx = idx + 1 if idx >= 0 else stdout.index("{", start)
    obj, _ = json.JSONDecoder().raw_decode(stdout[idx:])
    return obj


class TestArmDryRun:
    def _dry_run(self, tmp_path, arm: str) -> tuple[str, Path]:
        ws = tmp_path / "ws_absent"
        r = subprocess.run(
            [
                "bash",
                str(_LAUNCHER),
                "--arm",
                arm,
                "--workspace",
                str(ws),
                "--run_name",
                "armtest",
                "--mode",
                "lilab",
                "--dry-run",
                "--num_iterations",
                "1",
                "--max_rounds",
                "1",
                "--healthgate_mode",
                "blocking",
                "--result_authority",
                "scientific",
            ],
            capture_output=True,
            text=True,
            env=_env(),
            timeout=300,
        )
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        return r.stdout, ws

    def test_the_with_arm_argv_and_resolved_config(self, tmp_path):
        out, ws = self._dry_run(tmp_path, "with-prior-art")
        assert "run_one_iteration.py" in out
        assert "ml_hyperparameter_tune_agent" not in out
        assert "advice/workflow/v20_" not in out
        assert "--experiment_arm with-prior-art" in out
        assert "--no-ml_lit_review_enabled" not in out
        assert "--ml_lit_review_enabled" in out
        assert "--baseline_isolation" not in out
        resolved = _extract_json(out)
        assert resolved["experiment_arm"] == "with-prior-art"
        assert resolved["lit_review_enabled"] is True
        assert resolved["baseline_isolation"] is False
        assert resolved["advice_file"] is None
        assert not ws.exists(), "a dry-run must leave an absent workspace absent"

    def test_the_without_arm_argv_and_resolved_config(self, tmp_path):
        out, ws = self._dry_run(tmp_path, "without-prior-art")
        assert "run_one_iteration.py" in out
        assert "--experiment_arm without-prior-art" in out
        assert "--no-ml_lit_review_enabled" in out
        assert "--baseline_isolation" in out
        assert "advice/workflow/v20_" not in out
        resolved = _extract_json(out)
        assert resolved["experiment_arm"] == "without-prior-art"
        assert resolved["lit_review_enabled"] is False
        assert resolved["lit_review_config_sha256"] is None
        assert resolved["baseline_isolation"] is True
        assert not ws.exists()


class TestLauncherRefusals:
    @pytest.mark.parametrize(
        "extra, needle",
        [
            (["--advice", "x.json"], "advice"),
            (["--human_advice_file", "x.json"], "advice"),
            (["--experiment_arm", "x"], "decided by --arm"),
            (["--baseline_isolation"], "decided by --arm"),
            (["--ml_lit_review_enabled"], "decided by --arm"),
            (["--no-ml_lit_review_enabled"], "decided by --arm"),
            (["--seed_paths", "a.json"], "cold-start"),
        ],
    )
    def test_forbidden_passthrough_is_refused(self, tmp_path, extra, needle):
        r = subprocess.run(
            [
                "bash",
                str(_LAUNCHER),
                "--arm",
                "with-prior-art",
                "--workspace",
                str(tmp_path / "w"),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 1
        assert needle in r.stderr

    def test_an_unknown_arm_is_refused(self, tmp_path):
        r = subprocess.run(
            ["bash", str(_LAUNCHER), "--arm", "bogus", "--workspace", str(tmp_path / "w")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 1
        assert "unknown --arm" in r.stderr

    def test_a_missing_workspace_flag_is_refused(self):
        r = subprocess.run(
            ["bash", str(_LAUNCHER), "--arm", "with-prior-art"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 1
        assert "--workspace" in r.stderr


class TestH100Posture:
    """S3's contract, exercised against a FIXTURE tree: launcher copy + fake
    run_chain.sh; the posture file present or absent per test."""

    def _fixture_tree(self, tmp_path) -> Path:
        tree = tmp_path / "sdsc"
        tree.mkdir()
        shutil.copy2(_LAUNCHER, tree / _LAUNCHER.name)
        fake_chain = tree / "run_chain.sh"
        fake_chain.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
        fake_chain.chmod(0o755)
        return tree

    def test_h100_without_the_posture_file_refuses_by_name(self, tmp_path):
        tree = self._fixture_tree(tmp_path)
        r = subprocess.run(
            [
                "bash",
                str(tree / _LAUNCHER.name),
                "--arm",
                "without-prior-art",
                "--workspace",
                str(tmp_path / "w"),
                "--h100",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 1
        assert "h100_posture.env" in r.stderr

    def test_h100_chain_args_are_splatted_after_the_arm_args(self, tmp_path):
        tree = self._fixture_tree(tmp_path)
        (tree / "h100_posture.env").write_text(
            "H100_POSTURE_VERSION=fixture\n"
            "export SIDERIUS_TEST_POSTURE=1\n"
            "H100_CHAIN_ARGS=(--max_rounds 7 --trial_time_budget_minutes 20)\n"
        )
        r = subprocess.run(
            [
                "bash",
                str(tree / _LAUNCHER.name),
                "--arm",
                "without-prior-art",
                "--workspace",
                str(tmp_path / "w"),
                "--h100",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 0, r.stderr
        lines = r.stdout.splitlines()
        assert "--baseline_isolation" in lines
        assert "--max_rounds" in lines
        assert lines.index("--baseline_isolation") < lines.index("--max_rounds"), (
            "H100_CHAIN_ARGS must be splatted AFTER the launcher's own args"
        )

    def test_h100_posture_without_the_array_is_refused(self, tmp_path):
        tree = self._fixture_tree(tmp_path)
        (tree / "h100_posture.env").write_text("export SIDERIUS_TEST_POSTURE=1\n")
        r = subprocess.run(
            [
                "bash",
                str(tree / _LAUNCHER.name),
                "--arm",
                "without-prior-art",
                "--workspace",
                str(tmp_path / "w"),
                "--h100",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode == 1
        assert "H100_CHAIN_ARGS" in r.stderr


def _app_args(chain_args: str) -> list[str]:
    script = f"""
    set +e
    source "{_CHAIN_COMMON}"
    parse_chain_args --workspace /tmp/ws --run_name cs {chain_args}
    SEED_PATHS=()
    build_app_args 1
    printf '%s\\n' "${{APP_ARGS[@]}}"
    """
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


class TestChainCommonForwarding:
    def test_unset_lit_review_forwards_nothing(self):
        lines = _app_args("")
        assert "--ml_lit_review_enabled" not in lines
        assert "--no-ml_lit_review_enabled" not in lines
        assert "--baseline_isolation" not in lines

    def test_explicit_negative_is_forwarded(self):
        assert "--no-ml_lit_review_enabled" in _app_args("--no-ml_lit_review_enabled")

    def test_positive_is_forwarded(self):
        lines = _app_args("--ml_lit_review_enabled")
        assert "--ml_lit_review_enabled" in lines
        assert "--no-ml_lit_review_enabled" not in lines

    def test_task_owned_lit_review_config_is_forwarded_verbatim(self):
        lines = _app_args("--ml_lit_review_config /task/config/lit-review.yaml")
        flag_index = lines.index("--ml_lit_review_config")
        assert lines[flag_index + 1] == "/task/config/lit-review.yaml"

    def test_baseline_isolation_is_forwarded_when_requested(self):
        assert "--baseline_isolation" in _app_args("--baseline_isolation")


class TestPrintResolvedLaunchConfig:
    def _print(self, tmp_path, extra=()):
        ws = tmp_path / "ws_never_created"
        r = subprocess.run(
            [
                sys.executable,
                str(_ROI),
                "--workspace",
                str(ws),
                "--run_name",
                "r",
                "--start_iteration",
                "1",
                "--healthgate_mode",
                "blocking",
                "--result_authority",
                "scientific",
                "--print_resolved_launch_config",
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=240,
            cwd=str(_REPO),
            env=_env(),
        )
        return r, ws

    def test_prints_one_json_object_and_touches_nothing(self, tmp_path):
        r, ws = self._print(
            tmp_path, ["--experiment_arm", "without-prior-art", "--baseline_isolation"]
        )
        assert r.returncode == 0, r.stderr
        resolved = _extract_json(r.stdout)
        assert resolved["experiment_arm"] == "without-prior-art"
        assert resolved["baseline_isolation"] is True
        assert resolved["lit_review_enabled"] is False
        assert resolved["healthgate_mode"] == "blocking"
        assert resolved["task_composition"] is None
        assert not ws.exists(), "the print mode must create nothing"

    def test_an_unresolvable_identity_exits_one_naming_the_config(self, tmp_path):
        missing = tmp_path / "absent.yaml"
        r, ws = self._print(
            tmp_path, ["--ml_lit_review_enabled", "--ml_lit_review_config", str(missing)]
        )
        assert r.returncode == 1
        assert str(missing) in r.stderr
        assert not ws.exists()


def _identity(**overrides):
    base = dict(
        experiment_arm=None,
        lit_review_enabled=False,
        lit_review_config_path="configs/lit_review_config.yaml",
        lit_review_config_sha256=None,
        baseline_isolation=False,
    )
    base.update(overrides)
    return roi.LaunchIdentity(**base)


class TestManifestAndInvariants:
    def test_the_isolation_stamp_obeys_the_omission_rule(self, tmp_path):
        on = tmp_path / "on"
        on.mkdir()
        manifest = roi.write_manifest(
            str(on), "iter_001", results=[], launch_identity=_identity(baseline_isolation=True)
        )
        assert manifest["baseline_isolation"] is True
        off = tmp_path / "off"
        off.mkdir()
        manifest = roi.write_manifest(str(off), "iter_001", results=[], launch_identity=_identity())
        assert "baseline_isolation" not in manifest

    def test_compute_expected_invariants_locks_the_flag(self, tmp_path):
        args = roi.build_parser().parse_args(
            [
                "--workspace",
                str(tmp_path),
                "--start_iteration",
                "1",
                "--run_name",
                "t",
                "--baseline_isolation",
            ]
        )
        args.health_gate_enabled = False
        args.health_gate_files = None
        invariants = roi.compute_expected_invariants(args)
        assert invariants.baseline_isolation is True
