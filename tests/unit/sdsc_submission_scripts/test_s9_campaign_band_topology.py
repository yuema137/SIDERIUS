"""S9 (arXiv launch topology) — band campaign launcher, preflight arithmetic,
arm symmetry.

Author ruling 2026-08-25: four co-resident band chains per H100 card
(bands 0-3 / 4-9 / 10-14 / 15-19), per-chain VRAM ~18 GiB, watchdog math
scaled by a PROBE-MEASURED co-residency factor, campaign workspaces on
persistent volume. Each test below names the defect ONLY it catches.

* ``TestBandMapping`` — the band -> (--data_scope, --health_gate_files)
  map and the derived workspace/run_name identity. The map lives ONLY in
  ``launch_prior_baseline_experiment.sh``; a wrong or partial pair (say
  ``4,5,6,7,8`` for band 4-9) violates the DS8 pairing rule invisibly to
  every python test and costs a refused (or worse, mis-scoped) launch on
  the H100 box. Plant-proven: dropping one index from one band's health
  list turns exactly that band's case RED (see the S9 return packet).
* ``TestBandRefusals`` — band-decided flags refused as passthrough; the
  workspace-root existence/writability refusals; the band/workspace
  mutual exclusions. A silent passthrough of ``--data_scope`` would let
  _chain_common's later-wins parsing desynchronize the executed scope
  from the band identity baked into run_name and the lock.
* ``TestCoresidencyFactorGate`` — campaign (--band) + --h100 refuses an
  EMPTY ``H100_CORESIDENCY_FACTOR`` by name (and a stale environment
  value cannot satisfy the check). Without this gate a fleet launches
  under one-chain watchdog math and the RT4 watchdog kills healthy 4-way
  rounds — the exact failure class the probe exists to price.
* ``TestFixedCandidateMode`` — ``--fixed-candidate`` forwards the plan
  as an ABSOLUTE ``--validation_fixed_candidate_plan`` (run_chain cd's
  before exec, so a relative path would dangle), pins
  ``--num_iterations 1`` unless the caller passed it (the chain default
  of 2 would silently retrain every champion twice), refuses a missing
  plan file, and refuses the raw flag (one spelling per mode).
* ``TestPreflightArithmetic`` — the pure admission/host-RAM functions
  sourced from ``campaign_preflight.sh``. An arithmetic slip (headroom
  dropped from the comparison) would green-light a posture that OOMs the
  80 GB card at launch; only these table tests compute the inequality
  independently of the script's own caller.
* ``TestArmSymmetryChecker`` — the #255 launch-blocking gate can
  actually turn RED: a planted ``--formal_portion`` asymmetry (the
  #255-named lock-invisible knob) is caught and named; identically
  resolved arms (mis-wired, not symmetric) are caught; a symmetric pair
  passes. An allowlist typo that admitted a population knob would make
  preflight R7 permanently green while still LOOKING like a guard — only
  this test exercises the red path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_SDSC = _REPO / "sdsc_submission_scripts"
_LAUNCHER = _SDSC / "launch_prior_baseline_experiment.sh"
_PREFLIGHT = _SDSC / "campaign_preflight.sh"
_SYMMETRY = _SDSC / "campaign_arm_symmetry.py"

#: The frozen campaign band map (author ruling 2026-08-25). Hardcoded here
#: ON PURPOSE — asserting values read back from the launcher would compare
#: the map to itself and pass for any map.
EXPECTED_BAND_MAP = {
    "0-3": "0,1,2,3",
    "4-9": "4,5,6,7,8,9",
    "10-14": "10,11,12,13,14",
    "15-19": "15,16,17,18,19",
}


def _fixture_tree(tmp_path: Path, posture_text: str | None = None) -> Path:
    """Launcher copy + argv-echoing fake run_chain.sh (+ optional posture)."""
    tree = tmp_path / "sdsc"
    tree.mkdir()
    shutil.copy2(_LAUNCHER, tree / _LAUNCHER.name)
    fake_chain = tree / "run_chain.sh"
    fake_chain.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
    fake_chain.chmod(0o755)
    if posture_text is not None:
        (tree / "h100_posture.env").write_text(posture_text)
    return tree


def _launch(tree: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(tree / _LAUNCHER.name), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


class TestBandMapping:
    @pytest.mark.parametrize("band", sorted(EXPECTED_BAND_MAP))
    def test_band_maps_to_the_exact_ds8_pair(self, tmp_path, band):
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(
            tree, "--arm", "without-prior-art", "--band", band, "--workspace-root", str(root)
        )
        assert r.returncode == 0, r.stderr
        argv = r.stdout.splitlines()
        i = argv.index("--data_scope")
        assert argv[i + 1] == band
        j = argv.index("--health_gate_files")
        assert argv[j + 1] == EXPECTED_BAND_MAP[band]

    def test_dry_run_prints_the_pythonpath_pin(self, tmp_path):
        """P0 launch blocker (supervisor 2026-08-25, E1 trap): the launcher
        must export PYTHONPATH=<its own tree> so spawned children resolve
        THIS tree, not the venv's editable-install target (the main
        checkout — which can sit on an unrelated branch missing #299's
        divergence repair). The dry-run prints the pin so R7 symmetry sees
        it and an operator reads it. Defect only this catches: the export
        silently dropped — children then import another checkout's code
        while every git-SHA check stays green. Fails by: pin line absent
        or pointing outside the launcher's own tree."""
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(tree, "--arm", "with-prior-art", "--band", "0-3", "--workspace-root", str(root))
        assert r.returncode == 0, r.stderr
        pin_lines = [ln for ln in (r.stdout + r.stderr).splitlines() if "pythonpath_pin=" in ln]
        assert pin_lines, "dry-run must print the pythonpath_pin line"
        pinned = pin_lines[0].split("pythonpath_pin=", 1)[1].strip()
        # PROJECT_DIR = the script dir's PARENT (in production the repo root,
        # since the launcher lives in sdsc_submission_scripts/); the fixture
        # tree mirrors that geometry, so the pin is tmp_path itself.
        assert pinned == str(tree.parent), (pinned, str(tree.parent))

    def test_band_mode_pins_the_regressor_constraint(self, tmp_path):
        """arXiv #259 (fleet ruling): campaign-band mode MUST pass
        `--allowed_output_types regressor` — identically derived for every
        band and arm, so the #255 symmetry condition holds by construction.
        Defect only this catches: the pin silently dropped from BAND_ARGS —
        the proposer then unconstrains and a classifier proposal can train
        into the regression campaign. Fails by: token pair absent."""
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(tree, "--arm", "with-prior-art", "--band", "0-3", "--workspace-root", str(root))
        assert r.returncode == 0, r.stderr
        argv = r.stdout.splitlines()
        i = argv.index("--allowed_output_types")
        assert argv[i + 1] == "regressor"

    def test_band_enters_workspace_and_run_name(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(
            tree, "--arm", "with-prior-art", "--band", "10-14", "--workspace-root", str(root)
        )
        assert r.returncode == 0, r.stderr
        argv = r.stdout.splitlines()
        ws = argv[argv.index("--workspace") + 1]
        rn = argv[argv.index("--run_name") + 1]
        assert ws == str(root / "with-prior-art_band10-14")
        assert rn == "with-prior-art_band10-14"

    def test_an_unknown_band_is_refused(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(tree, "--arm", "with-prior-art", "--band", "2-7", "--workspace-root", str(root))
        assert r.returncode == 1
        assert "unknown --band" in r.stderr


class TestBandRefusals:
    @pytest.mark.parametrize("flag", ["--data_scope", "--health_gate_files"])
    def test_band_decided_flags_are_refused_as_passthrough(self, tmp_path, flag):
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--band",
            "0-3",
            "--workspace-root",
            str(root),
            flag,
            "0-3",
        )
        assert r.returncode == 1
        assert "decided by --band" in r.stderr

    def test_a_missing_workspace_root_is_refused_by_name(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--band",
            "0-3",
            "--workspace-root",
            str(tmp_path / "absent"),
        )
        assert r.returncode == 1
        assert "does not exist" in r.stderr
        assert "persistent" in r.stderr.lower()

    def test_an_unwritable_workspace_root_is_refused(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "ro_root"
        root.mkdir()
        root.chmod(0o555)
        try:
            r = _launch(
                tree, "--arm", "with-prior-art", "--band", "0-3", "--workspace-root", str(root)
            )
            assert r.returncode == 1
            assert "not writable" in r.stderr
        finally:
            root.chmod(0o755)

    def test_band_without_root_and_root_without_band_are_refused(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(tree, "--arm", "with-prior-art", "--band", "0-3")
        assert r.returncode == 1
        assert "--workspace-root" in r.stderr
        r = _launch(tree, "--arm", "with-prior-art", "--workspace-root", str(root))
        assert r.returncode == 1
        assert "campaign-band mode only" in r.stderr

    def test_workspace_and_band_are_mutually_exclusive(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--band",
            "0-3",
            "--workspace-root",
            str(root),
            "--workspace",
            str(root / "w"),
        )
        assert r.returncode == 1
        assert "mutually exclusive" in r.stderr


class TestCoresidencyFactorGate:
    _NO_FACTOR = "H100_POSTURE_VERSION=77\nH100_CHAIN_ARGS=(--max_rounds 5)\n"
    _WITH_FACTOR = (
        "H100_POSTURE_VERSION=77\nH100_CORESIDENCY_FACTOR=3.2\nH100_CHAIN_ARGS=(--max_rounds 5)\n"
    )

    def test_empty_factor_refuses_campaign_h100_naming_the_probe(self, tmp_path):
        tree = _fixture_tree(tmp_path, posture_text=self._NO_FACTOR)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--band",
            "0-3",
            "--workspace-root",
            str(root),
            "--h100",
        )
        assert r.returncode == 1
        assert "H100_CORESIDENCY_FACTOR" in r.stderr
        assert "gpu_c_coresidency_probe.sh" in r.stderr

    def test_a_stale_environment_factor_cannot_satisfy_the_gate(self, tmp_path):
        import os

        tree = _fixture_tree(tmp_path, posture_text=self._NO_FACTOR)
        root = tmp_path / "root"
        root.mkdir()
        env = dict(os.environ, H100_CORESIDENCY_FACTOR="9.9")
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--band",
            "0-3",
            "--workspace-root",
            str(root),
            "--h100",
            env=env,
        )
        assert r.returncode == 1
        assert "H100_CORESIDENCY_FACTOR" in r.stderr

    def test_a_filled_factor_proceeds_and_is_logged(self, tmp_path):
        tree = _fixture_tree(tmp_path, posture_text=self._WITH_FACTOR)
        root = tmp_path / "root"
        root.mkdir()
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--band",
            "0-3",
            "--workspace-root",
            str(root),
            "--h100",
        )
        assert r.returncode == 0, r.stderr
        assert "coresidency_factor=3.2" in r.stdout
        assert "--max_rounds" in r.stdout.splitlines()

    def test_non_band_h100_does_not_require_the_factor(self, tmp_path):
        tree = _fixture_tree(tmp_path, posture_text=self._NO_FACTOR)
        r = _launch(tree, "--arm", "with-prior-art", "--workspace", str(tmp_path / "w"))
        assert r.returncode == 0, r.stderr


class TestFixedCandidateMode:
    def test_plan_is_forwarded_absolute_with_one_iteration_pinned(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        plan = tmp_path / "champ_plan.json"
        plan.write_text('{"model_name": "champ"}\n')
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--workspace",
            str(tmp_path / "w"),
            "--fixed-candidate",
            str(plan),
        )
        assert r.returncode == 0, r.stderr
        argv = r.stdout.splitlines()
        i = argv.index("--validation_fixed_candidate_plan")
        assert argv[i + 1] == str(plan.resolve()), "plan path must be forwarded ABSOLUTE"
        j = argv.index("--num_iterations")
        assert argv[j + 1] == "1", "a finalization retrain is one iteration by default"

    def test_an_explicit_num_iterations_wins(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        plan = tmp_path / "champ_plan.json"
        plan.write_text("{}\n")
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--workspace",
            str(tmp_path / "w"),
            "--fixed-candidate",
            str(plan),
            "--num_iterations",
            "3",
        )
        assert r.returncode == 0, r.stderr
        argv = r.stdout.splitlines()
        assert argv.count("--num_iterations") == 1
        assert argv[argv.index("--num_iterations") + 1] == "3"

    def test_a_missing_plan_file_is_refused(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--workspace",
            str(tmp_path / "w"),
            "--fixed-candidate",
            str(tmp_path / "absent.json"),
        )
        assert r.returncode == 1
        assert "plan file not found" in r.stderr

    def test_the_raw_chain_flag_is_refused(self, tmp_path):
        tree = _fixture_tree(tmp_path)
        r = _launch(
            tree,
            "--arm",
            "with-prior-art",
            "--workspace",
            str(tmp_path / "w"),
            "--validation_fixed_candidate_plan",
            "p.json",
        )
        assert r.returncode == 1
        assert "decided by --fixed-candidate" in r.stderr


def _pf_call(fn_and_args: str) -> subprocess.CompletedProcess:
    script = f'source "{_PREFLIGHT}"\n{fn_and_args}\n'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


class TestPreflightArithmetic:
    @pytest.mark.parametrize(
        "chains,per_chain,total,headroom,fits",
        [
            (4, 18, 80, 6, True),  # the shipped v2 posture: 72+6 <= 80
            (4, 20, 80, 6, False),  # 80+6 > 80 — over-budget per-chain value
            (4, 18, 80, 9, False),  # 72+9 > 80 — headroom must be IN the inequality
            (2, 18, 80, 6, True),  # partial fleet fits trivially
            (4, 18, 72, 0, True),  # exact fit with zero headroom demanded
        ],
    )
    def test_admission_arithmetic_table(self, chains, per_chain, total, headroom, fits):
        r = _pf_call(f"preflight_admission_arithmetic {chains} {per_chain} {total} {headroom}")
        assert (r.returncode == 0) is fits, r.stdout + r.stderr
        assert f"sum={chains * per_chain}" in r.stdout

    @pytest.mark.parametrize(
        "avail,expected,headroom,ok",
        [
            (63, 47, 16, True),  # exactly the requirement
            (62, 47, 16, False),  # one GiB short of expected+headroom
            (200, 47, 16, True),
        ],
    )
    def test_host_ram_table(self, avail, expected, headroom, ok):
        r = _pf_call(f"preflight_host_ram_check {avail} {expected} {headroom}")
        assert (r.returncode == 0) is ok, r.stdout + r.stderr
        assert f"required={expected + headroom}" in r.stdout

    def test_sourcing_the_preflight_runs_nothing(self):
        r = _pf_call("echo SOURCED_OK")
        assert r.returncode == 0
        assert "SOURCED_OK" in r.stdout
        assert "[preflight]" not in r.stdout, "sourcing must not execute pf_main"


# --- synthetic dry-run captures for the symmetry checker --------------------

_ARM_POLICY = {
    "with-prior-art": {
        "experiment_arm": "with-prior-art",
        "lit_review_enabled": True,
        "lit_review_config_path": "/repo/configs/lit_review_config.yaml",
        "lit_review_config_sha256": "ab" * 32,
        "baseline_isolation": False,
    },
    "without-prior-art": {
        "experiment_arm": "without-prior-art",
        "lit_review_enabled": False,
        "lit_review_config_path": "/repo/configs/lit_review_config.yaml",
        "lit_review_config_sha256": None,
        "baseline_isolation": True,
    },
}


def _capture(arm: str, root: str = "/persist/camp", band: str = "0-3", **argv_overrides) -> str:
    cfg = {
        "workspace": f"{root}/{arm}_band{band}",
        "run_name": f"{arm}_band{band}",
        "start_iteration": 1,
        "task_composition": None,
        "advice_file": None,
        "healthgate_mode": "blocking",
        "result_authority": "scientific",
        **_ARM_POLICY[arm],
    }
    argv = {
        "--workspace": f"{root}/{arm}_band{band}",
        "--run_name": f"{arm}_band{band}",
        "--data_scope": band,
        "--health_gate_files": "0\\,1\\,2\\,3",
        "--formal_portion": "0.1",
        "--formal_train_portion": "1.0",
        "--formal_eval_portion": "1.0",
        "--healthgate_mode": "blocking",
        "--result_authority": "scientific",
    }
    argv.update(argv_overrides)
    arm_tokens = (
        "--ml_lit_review_enabled --experiment_arm with-prior-art"
        if arm == "with-prior-art"
        else "--no-ml_lit_review_enabled --experiment_arm without-prior-art --baseline_isolation"
    )
    flat = " ".join(f"{k} {v}" for k, v in argv.items() if v is not None)
    return (
        "[prior-baseline] resolved launch configuration:\n"
        + json.dumps(cfg, indent=2, sort_keys=True)
        + "\n  [DRY-RUN] would exec from /repo:\n"
        + "    /venv/bin/python /repo/sdsc_submission_scripts/run_one_iteration.py "
        + f"{flat} {arm_tokens} --cleanup_denoised \n"
    )


def _run_symmetry(tmp_path: Path, with_text: str, without_text: str) -> subprocess.CompletedProcess:
    w = tmp_path / "with.out"
    wo = tmp_path / "without.out"
    w.write_text(with_text)
    wo.write_text(without_text)
    return subprocess.run(
        [
            sys.executable,
            str(_SYMMETRY),
            "--with-output",
            str(w),
            "--without-output",
            str(wo),
            "--workspace-root",
            "/persist/camp",
            "--band",
            "0-3",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestArmSymmetryChecker:
    def test_a_symmetric_pair_passes(self, tmp_path):
        r = _run_symmetry(tmp_path, _capture("with-prior-art"), _capture("without-prior-art"))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "PASS" in r.stdout

    def test_a_population_knob_asymmetry_is_caught_and_named(self, tmp_path):
        r = _run_symmetry(
            tmp_path,
            _capture("with-prior-art", **{"--formal_portion": "0.3"}),
            _capture("without-prior-art"),
        )
        assert r.returncode == 1
        assert "--formal_portion" in r.stderr, "the #255-named knob must be named in the diff"

    def test_identically_wired_arms_are_mis_wired_not_symmetric(self, tmp_path):
        # Both captures claim the WITH policy: no declared asymmetry at all.
        r = _run_symmetry(tmp_path, _capture("with-prior-art"), _capture("with-prior-art"))
        assert r.returncode == 1
        assert "mis-wired" in r.stderr or "expected with=" in r.stderr

    def test_an_output_type_token_is_refused_on_either_argv(self, tmp_path):
        # No operator output-type knob exists on the un-composed path (S9
        # audit); an injected token on ONE arm must fail even though the
        # OTHER arm lacks it (asymmetric) — and naming the gap keeps a
        # future knob from silently entering one arm only.
        r = _run_symmetry(
            tmp_path,
            _capture("with-prior-art", **{"--proposal_output_type": "regressor"}),
            _capture("without-prior-art"),
        )
        assert r.returncode == 1
        assert "output" in r.stderr.lower()
