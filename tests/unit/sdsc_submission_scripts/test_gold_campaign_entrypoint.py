"""F-LAUNCH-1 — the canonical Gold campaign entrypoint (contract PR #329).

Each test names the defect ONLY it can catch:

* ``TestSourceSafety`` — the five campaign scripts parse (``bash -n``) and
  the three executables use the standard source-safe entry guard, so
  sourcing one for its functions can never launch a campaign (the
  2026-07-31 gate-runner incident class).
* ``TestFrozenThirteenWitness`` — the effective-resolution witness: the
  dry-run's fully-resolved per-band run_chain argv carries ALL THIRTEEN
  frozen values TYPED (decisions D-BUD-2/6/7/8, D-BUD-11/13, P6-A, P6-B;
  the D-BUD-6 row split ``max_epochs=1`` into ``trial_max_epochs=2`` /
  ``formal_max_epochs=1`` when the per-mode transport landed, 2026-08-26).
  The expected pairs are HARDCODED here — asserting values read back from
  the lib would compare the table to itself and pass for any table. This
  is the defect class F-LAUNCH-1 closes: a chain default silently standing
  in for a frozen campaign value (e.g. skip_formal_min_delta -1.0 vs the
  frozen -2.0) is invisible to every other check because the launch still
  exits 0.
* ``TestFrozenTableMutation`` — the mutation witness: dropping one row
  from a COPY of the frozen table makes the dry-run FAIL NAMING that key.
  Without it, the witness above could go green while the builder silently
  stopped consulting the table (printing from one copy, emitting from
  another).
* ``TestFrozenLlmRouting`` — F-LLM-WIRE-1 (release blocker): the campaign
  path BINDS ``--llm_config llm_configs/openai_tiered_pro.json`` (D-LLM-1)
  on every stage-1 band AND every stage-2 unit, the runner's REAL parser +
  ``WorkflowLLMConfig`` resolve the pinned snapshot model, an unavailable
  frozen config REFUSES by name, a passed-through override is refused, and
  the non-campaign chain default still legitimately omits the flag. The
  defect class: ``--llm_config`` is optional at every hop, so omitting it
  ran the entire official campaign on the deprecated all-Gemini default
  while still exiting 0 — the pin was real and nothing consumed it.
* ``TestOnlySelection`` — ``--only`` SELECTS correctly AND returns 0.
  ``gold_select_bands`` fell off the end of its emission loop, so it
  returned the status of ``[ "$name" = "$band" ] && printf`` on the LAST
  band: every selection not containing ``15-19`` printed the right bands
  and then refused the launch with NO message on any stream. No existing
  test passed ``--only``, which is why it survived.
* ``TestRetention`` — R-RETENTION-1 (release blocker): (a) the campaign
  argv carries the retention token and NO ``--cleanup_denoised``; (b) a
  passthrough ``--cleanup_denoised`` is refused BY NAME; (c) the
  exploratory chain default still emits the flag (the retention fix must
  not break non-campaign disk hygiene); (d) sdsc mode refuses a retention
  request instead of letting submit_one_iteration.slurm silently
  re-inject the cleanup flag one layer down.
* ``TestBoundaryRefusals`` — arm vocabulary (X9 labels refused,
  R-ARM-STAMP-1), the treatment boundary (goldpod requires the advice
  file, blindpod refuses one), and frozen-flag passthrough refusal.
* ``TestGpuMap`` — the frozen single-resident band->GPU map
  (0-3->0, 4-9->1, 10-14->2, 15-19->3). A transposed map trains two bands
  on one card and leaves one H100 idle, visibly only at launch.
* ``TestStage2DryRun`` — 16 units, wave = design across the four GPUs,
  the fixed-candidate seam on every unit argv, ``--num_iterations 1``
  (the D-ARCH-2 retrain pin, NOT the stage-1 horizon), and COMPLETE.json
  idempotent skip.
* ``TestBandStateHelper`` / ``TestStage2Finalize`` — the persisted-state
  helper against synthetic workspaces: the contract section-1 winner rule
  (trial exclusion by KEY ABSENCE, eligibility through
  ``is_valid_candidate``, direction from the stamped spec — a
  lower-is-better spec flips the winner, so no assumed direction can
  survive), the fail-closed missing-spec refusal, the FCNet+2 stop
  tri-state, horizon exhaustion, and the atomic COMPLETE.json contract
  (marker only when the TARGET band's deliverable set fully resolves —
  Q-S3-2 ruling A band scoping, counts HARDCODED 4/6/5/5; written last).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
ENTRYPOINT = SDSC / "run_gold_campaign.sh"
STAGE1 = SDSC / "stage1_search.sh"
STAGE1_BAND = SDSC / "stage1_run_band.sh"
STAGE2 = SDSC / "stage2_strict_retrain.sh"
LIB = SDSC / "_gold_campaign_lib.sh"
CHAIN_COMMON = SDSC / "_chain_common.sh"
RUN_CHAIN = SDSC / "run_chain.sh"
STATE_HELPER = SDSC / "gold_campaign_state.py"

#: The canonical thirteen (decisions D-BUD-2 / D-BUD-6 / D-BUD-7 / D-BUD-8 /
#: D-BUD-11/13 / P6-A / P6-B), HARDCODED on purpose — see module docstring.
#: D-BUD-6 is the PAIR ``trial_max_epochs=2 / formal_max_epochs=1`` (the
#: frozen trial/formal split; the retired mode-agnostic ``--max_epochs 1``
#: stand-in is now a RESERVED passthrough, not an emitted value).
CANONICAL_THIRTEEN = {
    "--num_iterations": "20",
    "--trial_portion": "0.1",
    "--train_portion": "0.1",
    "--eval_portion": "0.01",
    "--formal_portion": "1.0",
    "--formal_train_portion": "0.1",
    "--formal_eval_portion": "0.1",
    "--trial_max_epochs": "2",
    "--formal_max_epochs": "1",
    "--trial_time_budget_minutes": "30",
    "--formal_time_budget_minutes": "120",
    "--skip_formal_min_delta": "-2.0",
    "--bypass_formal_time_budget_min_delta": "0.5",
}

#: The campaign's frozen LLM routing authority (D-LLM-1). HARDCODED here for
#: the same reason the thirteen are: reading the path back out of the lib
#: would compare the declaration to itself.
FROZEN_LLM_CONFIG_RELPATH = "llm_configs/openai_tiered_pro.json"
FROZEN_LLM_CONFIG = REPO_ROOT / FROZEN_LLM_CONFIG_RELPATH

#: The snapshot model D-LLM-1 pins every campaign LLM role to, and the
#: deprecated default that silently stands in when --llm_config is omitted.
PINNED_MODEL_ID = "gpt-5.5-2026-04-23"
UNPINNED_DEFAULT_MODEL_ID = "gemini-3.1-pro-preview"


def _install_frozen_llm_config(project_dir: Path) -> Path:
    """Give a synthetic script tree the frozen routing config it now needs.

    A tmp tree holding only the campaign scripts is no longer a faithful
    checkout: the boundary binds ``--llm_config`` from
    ``GOLD_PROJECT_DIR/llm_configs/`` and refuses when it is absent.
    """
    dest = project_dir / FROZEN_LLM_CONFIG_RELPATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FROZEN_LLM_CONFIG, dest)
    return dest


#: (``--only`` selection, expected canonical-order bands). HARDCODED:
#: reading the expectation back out of GOLD_BANDS would compare the lib to
#: itself. `15-19` appears as the control that ALWAYS passed; the
#: last-band-excluding rows are the ones that were red.
ONLY_SELECTIONS = [
    ("0-3", ["0-3"]),
    ("4-9", ["4-9"]),
    ("10-14", ["10-14"]),
    ("15-19", ["15-19"]),
    ("0-3,4-9", ["0-3", "4-9"]),
    ("10-14,0-3", ["0-3", "10-14"]),  # canonical order, not input order
    ("4-9,15-19", ["4-9", "15-19"]),
    ("0-3,4-9,10-14", ["0-3", "4-9", "10-14"]),
    ("0-3,4-9,10-14,15-19", ["0-3", "4-9", "10-14", "15-19"]),
    (" 0-3 , 10-14 ", ["0-3", "10-14"]),  # whitespace tolerated
]

EXPECTED_GPU_MAP = {"0-3": "0", "4-9": "1", "10-14": "2", "15-19": "3"}
EXPECTED_BAND_FILES = {
    "0-3": "0,1,2,3",
    "4-9": "4,5,6,7,8,9",
    "10-14": "10,11,12,13,14",
    "15-19": "15,16,17,18,19",
}


def _bash(*argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.pop("CUDA_VISIBLE_DEVICES", None)
    if env:
        merged.update({k: str(v) for k, v in env.items()})
    return subprocess.run(
        ["bash", *argv],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=merged,
        timeout=180,
    )


@pytest.fixture
def campaign_root(tmp_path: Path) -> dict:
    root = tmp_path / "ws"
    root.mkdir()
    advice = tmp_path / "advice.json"
    advice.write_text('{"propose": "placeholder"}\n')
    return {"root": root, "advice": advice}


def _stage1_dry(campaign_root: dict, *extra: str) -> subprocess.CompletedProcess:
    return _bash(
        str(ENTRYPOINT),
        "--workspace_root",
        str(campaign_root["root"]),
        "--stage",
        "1",
        "--gold_advice_file",
        str(campaign_root["advice"]),
        "--dry-run",
        *extra,
    )


def _band_argvs(stdout: str) -> dict[str, list[str]]:
    """Parse the dry-run's ``band <B> run_chain argv:`` blocks."""
    argvs: dict[str, list[str]] = {}
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if "run_chain argv:" in line and "[gold-band]" in line:
            # "[gold-band] band 0-3 run_chain argv:" — split on the spaced
            # word, because "gold-band" itself contains "band".
            band = line.split(" band ")[1].split(" run_chain")[0].strip()
            argvs[band] = shlex.split(lines[i + 1])
    return argvs


def _pairs(argv: list[str]) -> dict[str, str]:
    out = {}
    for i, tok in enumerate(argv):
        if tok.startswith("--") and i + 1 < len(argv):
            out.setdefault(tok, argv[i + 1])
    return out


class TestSourceSafety:
    def test_all_campaign_scripts_parse(self):
        for script in (ENTRYPOINT, STAGE1, STAGE1_BAND, STAGE2, LIB):
            proc = _bash("-n", str(script))
            assert proc.returncode == 0, f"bash -n failed for {script.name}: {proc.stderr}"

    @pytest.mark.parametrize("script", [ENTRYPOINT, STAGE1, STAGE1_BAND, STAGE2])
    def test_entry_guard_is_the_standard_form(self, script):
        source = script.read_text()
        assert '[[ "${BASH_SOURCE[0]}" == "$0" ]]' in source

    def test_sourcing_runs_nothing_and_writes_nothing(self, tmp_path):
        root = tmp_path / "never_created"
        for script in (ENTRYPOINT, STAGE1, STAGE1_BAND, STAGE2):
            proc = _bash("-c", f"source '{script}'; echo SOURCED_OK")
            assert "SOURCED_OK" in proc.stdout, f"{script.name}: {proc.stderr}"
        assert not root.exists()

    def test_lib_refuses_direct_execution(self):
        proc = _bash(str(LIB))
        assert proc.returncode != 0
        assert "source it" in proc.stderr


class TestFrozenThirteenWitness:
    def test_every_band_argv_carries_all_thirteen_typed(self, campaign_root):
        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _band_argvs(proc.stdout)
        assert sorted(argvs) == sorted(EXPECTED_GPU_MAP), proc.stdout
        for band, argv in argvs.items():
            pairs = _pairs(argv)
            for flag, value in CANONICAL_THIRTEEN.items():
                assert pairs.get(flag) == value, (
                    f"band {band}: frozen value {flag} {value} missing or wrong "
                    f"(got {pairs.get(flag)!r})"
                )
            # D-BUD-6: the pair REPLACES the retired mode-agnostic
            # stand-in — a re-emitted --max_epochs would be a third epoch
            # authority on the child argv.
            assert "--max_epochs" not in argv, band

    def test_band_identity_pair_and_arm_tokens(self, campaign_root):
        proc = _stage1_dry(campaign_root)
        argvs = _band_argvs(proc.stdout)
        for band, argv in argvs.items():
            pairs = _pairs(argv)
            assert pairs["--data_scope"] == band
            assert pairs["--health_gate_files"] == EXPECTED_BAND_FILES[band]
            assert pairs["--experiment_arm"] == "goldpod"
            assert pairs["--workspace"].endswith(f"goldpod_band{band}")
            assert pairs["--run_name"] == f"goldpod_band{band}"
            # Q-LIT-1 OFF as a NAMED absence: the explicit negative token,
            # asserted at TOKEN level (substring checks would be fooled by
            # the negative form containing the positive spelling).
            assert "--no-ml_lit_review_enabled" in argv
            assert "--ml_lit_review_enabled" not in argv
            # The treatment boundary: the advice artifact, absolute.
            assert pairs["--advice"] == str(campaign_root["advice"])

    def test_bypass_ceiling_emission_mirrors_both_probe_conditions(self, campaign_root):
        """The parallel-lane interface: emitting the flag before the WHOLE
        transport accepts it would refuse every campaign launch with
        'Unknown arg' one hop down. This mirror computes the lib probe's
        TWO conditions (chain parser AND runner argparse) and asserts the
        dry-run matches: both hold -> the typed 200 is on every band argv;
        either missing -> the token is absent. When #334 lands the runner
        half, the assertion flips by itself."""
        chain_parses = "--bypass_formal_time_budget_minutes)" in CHAIN_COMMON.read_text()
        runner_accepts = (
            '"--bypass_formal_time_budget_minutes"' in (SDSC / "run_one_iteration.py").read_text()
        )
        proc = _stage1_dry(campaign_root)
        argvs = _band_argvs(proc.stdout)
        for band, argv in argvs.items():
            if chain_parses and runner_accepts:
                assert _pairs(argv).get("--bypass_formal_time_budget_minutes") == "200", band
            else:
                assert "--bypass_formal_time_budget_minutes" not in argv, band

    def test_chain_side_probe_condition_holds_at_this_head(self):
        """The ownership-gap witness (F2 finding): the chain-side parse +
        emission for the bypass ceiling once ended up owned by NOBODY —
        each lane believed the other owned the hop — and without these
        lines the entrypoint's probe would self-disable FOREVER, running
        every campaign bypass-less with only a stderr NOTE and exit 0 (the
        silent-fallback class). RED again if the parse arm is descoped.

        Asserted BEHAVIORALLY through the production builder, not just
        bytes: typed -> the pair reaches the child argv; empty -> omitted
        (the tri-state, matching run_one_iteration's None default)."""
        assert "--bypass_formal_time_budget_minutes)" in CHAIN_COMMON.read_text(), (
            "the chain-side parse arm for --bypass_formal_time_budget_minutes is gone "
            "(folded from 378a68db); the entrypoint probe would silently self-disable"
        )
        typed = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t "
            "--bypass_formal_time_budget_minutes 200; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert typed.returncode == 0, typed.stderr
        tokens = typed.stdout.splitlines()
        assert "--bypass_formal_time_budget_minutes" in tokens
        assert tokens[tokens.index("--bypass_formal_time_budget_minutes") + 1] == "200"
        untyped = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert untyped.returncode == 0, untyped.stderr
        assert "--bypass_formal_time_budget_minutes" not in untyped.stdout.splitlines()

    def test_dry_run_emits_bypass_when_both_probe_conditions_hold(self, tmp_path, campaign_root):
        """The integration shape ahead of #334: a fixture tree pairs the
        REAL updated _chain_common.sh with a fake run_one_iteration.py
        carrying the argparse spelling, so BOTH probe conditions hold —
        the dry-run argv must then carry the typed 200. Fails if the probe
        greps drift from the folded lines' spelling (the self-disable
        hazard the ownership gap created)."""
        tree = tmp_path / "both_conditions"
        tree.mkdir()
        shutil.copy2(STAGE1_BAND, tree / STAGE1_BAND.name)
        shutil.copy2(LIB, tree / LIB.name)
        shutil.copy2(CHAIN_COMMON, tree / CHAIN_COMMON.name)
        # The runner half as #334 will spell it (argparse string, quoted).
        (tree / "run_one_iteration.py").write_text(
            '# fixture\nPARSER_FLAGS = ["--bypass_formal_time_budget_minutes"]\n'
        )
        # The fixture tree must be a faithful checkout for every binding the
        # boundary makes, not only the one under test: the lib resolves
        # GOLD_PROJECT_DIR to tree.parent and REFUSES when the frozen LLM
        # routing config is missing (F-LLM-WIRE-1). Supplying the real file
        # keeps this test measuring the BYPASS probe.
        _install_frozen_llm_config(tmp_path)
        proc = _bash(
            str(tree / STAGE1_BAND.name),
            "--band",
            "0-3",
            "--workspace_root",
            str(campaign_root["root"]),
            "--gold_advice_file",
            str(campaign_root["advice"]),
            "--dry-run",
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _band_argvs(proc.stdout)
        assert _pairs(argvs["0-3"]).get("--bypass_formal_time_budget_minutes") == "200"


class TestFrozenTableMutation:
    def test_dropping_a_row_fails_naming_the_key(self, tmp_path, campaign_root):
        """Copy the band script + lib, delete ONE frozen row, and the
        dry-run must fail NAMING that key — proving builder and printer
        both consult the ONE table."""
        tree = tmp_path / "mutated"
        tree.mkdir()
        shutil.copy2(STAGE1_BAND, tree / STAGE1_BAND.name)
        lib_text = LIB.read_text()
        mutated = lib_text.replace('    "trial_time_budget_minutes=30"\n', "")
        assert mutated != lib_text, "mutation did not apply — row spelling changed?"
        (tree / LIB.name).write_text(mutated)
        proc = _bash(
            str(tree / STAGE1_BAND.name),
            "--band",
            "0-3",
            "--workspace_root",
            str(campaign_root["root"]),
            "--gold_advice_file",
            str(campaign_root["advice"]),
            "--dry-run",
        )
        assert proc.returncode != 0
        assert "trial_time_budget_minutes" in proc.stderr
        assert "FROZEN TABLE MISSING VALUE" in proc.stderr

    def test_lib_table_matches_the_canonical_thirteen_exactly(self):
        """A silently EDITED value (30 -> 20) keeps the dry-run green, so
        the table itself is pinned against the hardcoded canon."""
        proc = _bash(
            "-c",
            f"source '{LIB}'; printf '%s\\n' \"${{GOLD_FROZEN_ROWS[@]}}\"",
        )
        assert proc.returncode == 0, proc.stderr
        rows = {line.split("=")[0]: line.split("=", 1)[1] for line in proc.stdout.split()}
        expected = {k.lstrip("-"): v for k, v in CANONICAL_THIRTEEN.items()}
        assert rows == expected


class TestFrozenLlmRouting:
    """F-LLM-WIRE-1 — the campaign path BINDS the frozen LLM routing config.

    The defect this closes is the declared-but-unconsumed class, and its
    whole danger is that the failure mode is SILENT: `--llm_config` is
    optional at every hop (`_chain_common.sh` LLM_CONFIG="" forwards
    nothing; `run_one_iteration.py` falls back to
    `WorkflowLLMConfig.uniform("gemini", --llm_model)`), so a campaign
    launched without it runs every LLM role on the deprecated
    all-Gemini default, exits 0, and produces records that look normal.
    The pin was real and the config was correct — nothing on the campaign
    path consumed it.
    """

    def test_every_stage1_band_argv_binds_the_frozen_config(self, campaign_root):
        """Witness (a), stage 1: the EFFECTIVE per-band argv the launcher
        would exec carries --llm_config at the frozen ABSOLUTE path.

        Absolute because run_chain.sh cd's to the project dir before exec
        (lilab mode), so a relative path would dangle — the same rule the
        advice artifact follows. Asserted against the resolved argv, never
        a grep of the script: a script may mention a flag it never emits."""
        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _band_argvs(proc.stdout)
        assert sorted(argvs) == sorted(EXPECTED_GPU_MAP), proc.stdout
        for band, argv in argvs.items():
            assert _pairs(argv).get("--llm_config") == str(FROZEN_LLM_CONFIG), (
                f"band {band} would launch WITHOUT the frozen routing config — every "
                f"LLM role silently resolves to {UNPINNED_DEFAULT_MODEL_ID}"
            )

    def test_every_stage2_unit_argv_binds_the_frozen_config(self, campaign_root, tmp_path):
        """Witness (a), stage 2: all sixteen strict-retrain units too.

        Stage 2 is a SEPARATE argv builder from stage 1. A stage that
        silently runs on a different model than the bands it is retraining
        designs from is the same defect one layer down, and it would be
        invisible: Stage-3 pools the winners without ever seeing which
        model proposed them."""
        registry = tmp_path / "designs"
        registry.mkdir()
        for design in ("wavenetA", "punetB", "rnnC", "fnoD"):
            (registry / f"{design}.json").write_text("{}\n")
        proc = _bash(
            str(ENTRYPOINT),
            "--workspace_root",
            str(campaign_root["root"]),
            "--stage",
            "2",
            "--design_registry",
            str(registry),
            "--gold_advice_file",
            str(campaign_root["advice"]),
            "--dry-run",
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        lines = proc.stdout.splitlines()
        units = {}
        for i, line in enumerate(lines):
            if "run_chain argv:" in line and "[gold-stage2]" in line:
                unit = line.split("unit")[1].split("gpu")[0].strip()
                units[unit] = shlex.split(lines[i + 1])
        assert len(units) == 16, sorted(units)
        for unit, argv in units.items():
            assert _pairs(argv).get("--llm_config") == str(FROZEN_LLM_CONFIG), unit

    def test_runner_resolves_the_pinned_model_not_the_gemini_default(self, campaign_root):
        """Witness (b): drive the REAL transport, end to end.

        The launcher's own emitted argv is walked through the production
        hops — `_chain_common.sh` parse + `build_app_args`, then
        `run_one_iteration.py`'s REAL argparse, then the SAME
        `WorkflowLLMConfig.from_json` branch the runner takes at
        `args.llm_config` — and every campaign-active role must land on the
        pinned snapshot. Asserting on strings would prove only that a path
        was copied around; this proves a model was actually selected.

        The negative half is what makes it a witness rather than a
        tautology: the identical parser with the flag ABSENT resolves every
        one of those roles to the deprecated default, which is exactly what
        the campaign was doing."""
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argv = _band_argvs(proc.stdout)["0-3"]
        # argv = ["CUDA_VISIBLE_DEVICES=0", "bash", "<run_chain.sh>", ...]
        chain_args = argv[3:]
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args {' '.join(shlex.quote(a) for a in chain_args)}; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert built.returncode == 0, built.stderr
        app_args = [tok for tok in built.stdout.splitlines() if tok]

        spec = importlib.util.spec_from_file_location(
            "roi_for_llm_wire_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        from workflows.llm_config import WorkflowLLMConfig

        ns = roi.build_parser().parse_args(app_args)
        assert ns.llm_config == str(FROZEN_LLM_CONFIG)

        # The production branch (run_one_iteration.py: `if args.llm_config`).
        pinned = WorkflowLLMConfig.from_json(ns.llm_config)
        # lit_review is deliberately excluded: Q-LIT-1 is OFF in both arms,
        # and the shipped config routes it elsewhere on purpose.
        campaign_roles = ("interpret", "propose", "implement", "validate", "tune")
        for role in campaign_roles:
            resolved = pinned.get(role)
            model_ids = {v for k, v in resolved.items() if k.endswith("model_id")}
            assert model_ids == {PINNED_MODEL_ID}, (role, resolved)

        # The negative half — the same parser, the flag omitted.
        bare = roi.build_parser().parse_args(["--workspace", "/tmp/x", "--run_name", "t"])
        assert bare.llm_config is None
        unpinned = WorkflowLLMConfig.uniform("gemini", bare.llm_model)
        for role in campaign_roles:
            resolved = unpinned.get(role)
            model_ids = {v for k, v in resolved.items() if k.endswith("model_id")}
            assert model_ids == {UNPINNED_DEFAULT_MODEL_ID}, (role, resolved)

    def test_unavailable_frozen_config_refuses_naming_the_flag(self, campaign_root, tmp_path):
        """Witness (c), the ANTI-SILENCE witness: a campaign launch that
        cannot resolve the frozen routing config REFUSES, loudly, naming
        `--llm_config`.

        This is the test that would have caught the original defect, and it
        is the one the fix exists for. Omission was survivable precisely
        because it looked like success; a launch that cannot bind the pin
        must not be allowed to proceed on a plausible-looking default.

        The tree holds ONLY the campaign scripts, so GOLD_PROJECT_DIR
        resolves to a directory with no llm_configs/ — the same fixture
        shape the frozen-table mutation witness uses."""
        tree = tmp_path / "no_llm_configs"
        tree.mkdir()
        shutil.copy2(STAGE1_BAND, tree / STAGE1_BAND.name)
        shutil.copy2(LIB, tree / LIB.name)
        assert not (tmp_path / "llm_configs").exists()
        proc = _bash(
            str(tree / STAGE1_BAND.name),
            "--band",
            "0-3",
            "--workspace_root",
            str(campaign_root["root"]),
            "--gold_advice_file",
            str(campaign_root["advice"]),
            "--dry-run",
        )
        assert proc.returncode != 0, proc.stdout
        assert "--llm_config" in proc.stderr
        assert "F-LLM-WIRE-1" in proc.stderr
        # The refusal must state the consequence, not merely the absence:
        # "file missing" reads as cosmetic, "runs on the wrong model" does not.
        assert UNPINNED_DEFAULT_MODEL_ID in proc.stderr
        # And it must refuse BEFORE emitting an argv anyone could copy.
        assert "run_chain argv" not in proc.stdout

    def test_passthrough_llm_config_refused_by_name(self, campaign_root):
        """An operator-supplied --llm_config would land AFTER the frozen
        tokens, and `_chain_common.sh`'s parse loop is last-wins — so it
        would silently override the pin. Same defect, one layer down."""
        proc = _stage1_dry(campaign_root, "--llm_config", "/tmp/somewhere_else.json")
        assert proc.returncode != 0
        assert "--llm_config" in proc.stderr

    def test_exploratory_chain_launch_still_omits_llm_config(self):
        """Witness (d), the differential: LLM_CONFIG="" stays legal OFF the
        campaign path.

        The general chain default must not be dragged into the campaign's
        refusal — exploratory and non-campaign runs legitimately launch
        without a routing config, and forwarding an empty value would put a
        bare `--llm_config` on the child argv and crash argparse."""
        proc = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert proc.returncode == 0, proc.stderr
        assert "--llm_config" not in proc.stdout.splitlines()

    def test_frozen_relpath_is_the_declared_authority(self):
        """A silently REPOINTED authority (a different file, or a typo that
        happens to exist) keeps every argv witness above green, so the
        declared path itself is pinned against the hardcoded canon — and
        the file it names must actually pin the campaign's model."""
        proc = _bash("-c", f"source '{LIB}'; printf '%s' \"$GOLD_LLM_CONFIG_RELPATH\"")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == FROZEN_LLM_CONFIG_RELPATH
        assert FROZEN_LLM_CONFIG.is_file(), FROZEN_LLM_CONFIG
        assert PINNED_MODEL_ID in FROZEN_LLM_CONFIG.read_text()


class TestOnlySelection:
    """``--only`` band selection SELECTS correctly AND succeeds.

    No existing test passed ``--only`` at all, which is exactly why this
    survived: ``gold_select_bands`` fell off the end of its emission loop,
    so the function returned the status of
    ``[ "$name" = "$band" ] && printf`` on the LAST band in ``GOLD_BANDS``.
    Any selection not containing ``15-19`` therefore printed the right
    bands and returned 1, and the caller's
    ``SELECTED="$(gold_select_bands "$ONLY")" || return 1`` turned that
    into a launch refusal with **no message on any stream**.

    The operational shape is a recovery path: a four-band campaign loses
    one band, the operator relaunches just that band with ``--only 0-3``,
    and gets an unexplained exit 1 with nothing to read.

    Both halves are asserted together on purpose — the selection was
    always correct, so a test that only checked the printed bands would
    have passed throughout.
    """

    @pytest.mark.parametrize("selection,expected", ONLY_SELECTIONS)
    def test_selection_succeeds_and_is_canonically_ordered(self, selection, expected):
        proc = _bash("-c", f"source '{LIB}'; gold_select_bands '{selection}'")
        assert proc.returncode == 0, (
            f"--only '{selection}' refused with rc={proc.returncode} and "
            f"stderr={proc.stderr!r} — a silent launch refusal"
        )
        assert proc.stdout.split() == expected

    def test_empty_selection_is_all_bands(self):
        proc = _bash("-c", f"source '{LIB}'; gold_select_bands ''")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split() == ["0-3", "4-9", "10-14", "15-19"]

    @pytest.mark.parametrize(
        "bad,reason",
        [
            ("0-3,0-3", "duplicate"),
            ("nope", "unknown"),
            ("0-3,nope", "unknown"),
            (",", "selected nothing"),
        ],
    )
    def test_invalid_selection_still_refuses_by_name(self, bad, reason):
        """The success fix must not turn a genuine refusal into a pass:
        every refusal path keeps its explicit `return 1` and its message."""
        proc = _bash("-c", f"source '{LIB}'; gold_select_bands '{bad}'")
        assert proc.returncode != 0, proc.stdout
        assert reason in proc.stderr

    def test_launcher_only_flag_reaches_a_band_dry_run(self, campaign_root):
        """End of the hop, through the real entrypoint: `--only 0-3` must
        walk the band and print its resolved argv. This is the surface the
        operator actually touches, and it exited 1 with an empty log."""
        proc = _stage1_dry(campaign_root, "--only", "0-3")
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _band_argvs(proc.stdout)
        assert sorted(argvs) == ["0-3"], proc.stdout
        # And the band it selected still carries the frozen routing config.
        assert _pairs(argvs["0-3"]).get("--llm_config") == str(FROZEN_LLM_CONFIG)


class TestRetention:
    def test_campaign_argv_retains_deliverables(self, campaign_root):
        """Witness (a): the retention token is typed and the cleanup token
        is ABSENT on every band argv."""
        proc = _stage1_dry(campaign_root)
        for band, argv in _band_argvs(proc.stdout).items():
            assert "--no-cleanup_denoised" in argv, band
            assert "--cleanup_denoised" not in argv, band

    def test_cleanup_passthrough_refused_by_name(self, campaign_root):
        """Witness (b)."""
        proc = _stage1_dry(campaign_root, "--cleanup_denoised")
        assert proc.returncode != 0
        assert "--cleanup_denoised" in proc.stderr
        assert "R-RETENTION-1" in proc.stderr

    def test_exploratory_chain_default_still_cleans_up(self):
        """Witness (c): sourcing _chain_common and building default args
        must still emit the flag — the campaign fix must not break
        non-campaign disk hygiene."""
        proc = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert proc.returncode == 0, proc.stderr
        assert "--cleanup_denoised" in proc.stdout.splitlines()

    def test_chain_retention_token_suppresses_cleanup(self):
        """The typed named absence flows through the chain builder: with
        --no-cleanup_denoised the child argv carries NEITHER token."""
        proc = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            "parse_chain_args --workspace /tmp/x --run_name t --no-cleanup_denoised; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert proc.returncode == 0, proc.stderr
        tokens = proc.stdout.splitlines()
        assert "--cleanup_denoised" not in tokens
        assert "--no-cleanup_denoised" not in tokens  # chain-level flag, not a child flag

    def test_sdsc_mode_refuses_retention(self, tmp_path):
        """submit_one_iteration.slurm force-injects --cleanup_denoised into
        jobs that omit it, so honoring retention in sdsc mode is
        impossible — the combination must refuse, not lie.

        Launch-inertness by FIXTURE CONSTRUCTION (the no-test-executes-a-
        launcher rule's concern): the copy runs in a tmp tree holding ONLY
        run_chain.sh + _chain_common.sh. The expected path exits at the
        retention refusal before any interpreter resolution; and were that
        refusal regressed away, the tree has no _import_resolution_probe.py,
        so the source-authority guard aborts before anything can submit —
        with a different stderr, which this assertion then catches."""
        tree = tmp_path / "chain"
        tree.mkdir()
        shutil.copy2(RUN_CHAIN, tree / RUN_CHAIN.name)
        shutil.copy2(CHAIN_COMMON, tree / CHAIN_COMMON.name)
        proc = _bash(
            str(tree / RUN_CHAIN.name),
            "--mode",
            "sdsc",
            "--workspace",
            str(tmp_path / "w"),
            "--run_name",
            "t",
            "--no-cleanup_denoised",
        )
        assert proc.returncode != 0
        assert "cannot be honored in --mode sdsc" in proc.stderr


class TestBoundaryRefusals:
    @pytest.mark.parametrize("label", ["with-prior-art", "without-prior-art"])
    def test_x9_arm_labels_refused_by_name(self, campaign_root, label):
        proc = _stage1_dry(campaign_root, "--arm", label)
        assert proc.returncode != 0
        assert "R-ARM-STAMP-1" in proc.stderr

    def test_goldpod_requires_the_advice_file(self, campaign_root):
        proc = _bash(
            str(ENTRYPOINT),
            "--workspace_root",
            str(campaign_root["root"]),
            "--stage",
            "1",
            "--dry-run",
        )
        assert proc.returncode != 0
        assert "--gold_advice_file" in proc.stderr

    def test_blindpod_refuses_an_advice_file(self, campaign_root):
        proc = _stage1_dry(campaign_root, "--arm", "blindpod")
        assert proc.returncode != 0
        assert "WITHOUT_ADVICE" in proc.stderr

    def test_frozen_flag_passthrough_refused(self, campaign_root):
        proc = _stage1_dry(campaign_root, "--trial_portion", "0.5")
        assert proc.returncode != 0
        assert "--trial_portion" in proc.stderr


class TestGpuMap:
    def test_band_to_gpu_assignment_is_the_frozen_map(self, campaign_root):
        proc = _stage1_dry(campaign_root)
        argvs = _band_argvs(proc.stdout)
        for band, argv in argvs.items():
            assert argv[0] == f"CUDA_VISIBLE_DEVICES={EXPECTED_GPU_MAP[band]}", band

    def test_band_map_matches_the_x9_authority_table(self):
        """The X9 band launcher's case table stays the historical
        authority; a silent divergence between the two maps would score a
        band against the wrong monitored files."""
        x9 = (SDSC / "launch_prior_baseline_experiment.sh").read_text()
        for band, files in EXPECTED_BAND_FILES.items():
            assert f'BAND_HEALTH_FILES="{files}"' in x9, band


class TestStage2DryRun:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> Path:
        reg = tmp_path / "designs"
        reg.mkdir()
        for design in ("wavenetA", "punetB", "rnnC", "fnoD"):
            (reg / f"{design}.json").write_text("{}\n")
        return reg

    def _dry(self, campaign_root, registry, *extra):
        return _bash(
            str(ENTRYPOINT),
            "--workspace_root",
            str(campaign_root["root"]),
            "--stage",
            "2",
            "--design_registry",
            str(registry),
            "--gold_advice_file",
            str(campaign_root["advice"]),
            "--dry-run",
            *extra,
        )

    def test_sixteen_units_with_fixed_candidate_and_retrain_pin(self, campaign_root, registry):
        proc = self._dry(campaign_root, registry)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        lines = proc.stdout.splitlines()
        unit_argvs = {}
        for i, line in enumerate(lines):
            if "run_chain argv:" in line and "[gold-stage2]" in line:
                unit = line.split("unit")[1].split("gpu")[0].strip()
                unit_argvs[unit] = shlex.split(lines[i + 1])
        assert len(unit_argvs) == 16
        for unit, argv in unit_argvs.items():
            design, band = unit.rsplit("_", 1)
            pairs = _pairs(argv)
            assert pairs["--validation_fixed_candidate_plan"].endswith(f"{design}.json"), unit
            # The D-ARCH-2 pin: a retrain is ONE iteration; the stage-1
            # horizon (20) must NOT leak into stage-2 argv.
            assert pairs["--num_iterations"] == "1", unit
            assert pairs["--data_scope"] == band, unit
            assert "--no-cleanup_denoised" in argv, unit
            for flag in (
                "--formal_portion",
                "--formal_train_portion",
                "--formal_eval_portion",
                # D-BUD-6: a stage-2 unit runs the SAME round machinery
                # (Stage-1 rules apply inside the unit workspace), so it
                # carries the same per-role pair; the FORMAL retrain round
                # that COMPLETE.json scores and Stage-3 pools trains under
                # formal_max_epochs=1 — identical to the retired
                # mode-agnostic --max_epochs 1.
                "--trial_max_epochs",
                "--formal_max_epochs",
            ):
                assert pairs[flag] == CANONICAL_THIRTEEN[flag], (unit, flag)
            assert "--max_epochs" not in argv, unit

    def test_completed_unit_is_skipped(self, campaign_root, registry):
        unit = campaign_root["root"] / "stage2" / "punetB_4-9"
        unit.mkdir(parents=True)
        (unit / "COMPLETE.json").write_text("{}\n")
        proc = self._dry(campaign_root, registry)
        assert proc.returncode == 0
        assert "unit punetB_4-9: SKIP (COMPLETE.json exists)" in proc.stdout

    def test_registry_must_hold_exactly_four_designs(self, campaign_root, tmp_path):
        reg = tmp_path / "three"
        reg.mkdir()
        for design in ("a", "b", "c"):
            (reg / f"{design}.json").write_text("{}\n")
        proc = self._dry(campaign_root, reg)
        assert proc.returncode != 0
        assert "exactly FOUR" in proc.stderr


# ---------------------------------------------------------------------------
# F-PROFILE-WIRE-1 — the required runtime-profile declaration on the Gold path.
#
# The value is OPERATOR-SUPPLIED rather than frozen in the lib, because the
# measured H100 overlay is post-tag qualification data: its sha256 cannot
# exist in tagged code, and filling a frozen constant on the pod at M4 would
# be a tagged-code change — the outcome the operator ruled must FAIL M4
# rather than be papered over. The campaign therefore freezes the MECHANISM
# and its OBSERVABILITY; qualification supplies the VALUE.
#
# So the witnesses here are the two the design owes: the launcher ACCEPTS and
# FORWARDS a supplied declaration (to both stages, from the one shared
# builder), and its ABSENCE is explicit rather than silent.
# ---------------------------------------------------------------------------

#: A syntactically valid declaration. HARDCODED — nothing in the lib declares
#: a profile key, so there is no source to read it back from, and at M4 the
#: real values come from the qualification run's provenance.
#: An ABSOLUTE artifact path. HARDCODED and deliberately not a real file:
#: the launcher must TRANSPORT the declaration, and certification (which
#: does need the bytes) belongs to the resolver's own tests.
DECLARED_PROFILE_PATH = "/persistent/qualification/runtime_profiles_h100.json"
DECLARED_PROFILE_KEY = "nvidia_h100_80gb_hbm3/single"
DECLARED_PROFILE_SHA = "c" * 64


def _stage2_unit_argvs(stdout: str) -> dict[str, list[str]]:
    """Parse the stage-2 dry-run's ``unit <U> gpu=<G> run_chain argv:`` blocks."""
    argvs: dict[str, list[str]] = {}
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if "run_chain argv:" in line and "[gold-stage2]" in line:
            unit = line.split("unit")[1].split("gpu")[0].strip()
            argvs[unit] = shlex.split(lines[i + 1])
    return argvs


class TestRequiredRuntimeProfileDeclaration:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> Path:
        reg = tmp_path / "designs"
        reg.mkdir()
        for design in ("wavenetA", "punetB", "rnnC", "fnoD"):
            (reg / f"{design}.json").write_text("{}\n")
        return reg

    def _stage2_dry(self, campaign_root, registry, *extra):
        return _bash(
            str(ENTRYPOINT),
            "--workspace_root",
            str(campaign_root["root"]),
            "--stage",
            "2",
            "--design_registry",
            str(registry),
            "--gold_advice_file",
            str(campaign_root["advice"]),
            "--dry-run",
            *extra,
        )

    def test_a_supplied_declaration_reaches_every_stage1_band_argv(self, campaign_root):
        """(d) The defect only this catches: the entrypoint accepting the
        declaration and then not forwarding it — the M4 operator would supply
        the binding, see it echoed by the launcher, and still get bands whose
        chain argv carries nothing. Fails by: any band's argv missing either
        token, or the four bands disagreeing."""
        proc = _stage1_dry(
            campaign_root,
            "--gold_required_runtime_profile_path",
            DECLARED_PROFILE_PATH,
            "--gold_required_runtime_profile",
            DECLARED_PROFILE_KEY,
            "--gold_required_runtime_profile_sha256",
            DECLARED_PROFILE_SHA,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _band_argvs(proc.stdout)
        assert len(argvs) == 4, argvs.keys()
        for band, argv in argvs.items():
            pairs = _pairs(argv)
            assert pairs["--required_runtime_profile_path"] == DECLARED_PROFILE_PATH, band
            assert pairs["--required_runtime_profile"] == DECLARED_PROFILE_KEY, band
            assert pairs["--required_runtime_profile_sha256"] == DECLARED_PROFILE_SHA, band
            # R-RETENTION-1 is unchanged: --no-cleanup_denoised still
            # terminates the FROZEN block, so the new tokens were inserted
            # before it rather than displacing it. (Retention itself is
            # owned by TestRetention; this only pins that we did not move
            # it — the band/arm args legitimately follow the frozen block.)
            assert "--no-cleanup_denoised" in argv, band
            assert argv.index("--no-cleanup_denoised") > argv.index(
                "--required_runtime_profile_sha256"
            ), band

    def test_a_supplied_declaration_reaches_every_stage2_unit_argv(self, campaign_root, registry):
        """(d) The defect only this catches: the declaration reaching stage 1
        but not stage 2 — the two stages build argv in separate scripts, so
        one binder feeding both is an assumption, not a guarantee. A stage-2
        unit certifying a different profile than the band it retrains would
        silently break the retrain's comparability. Fails by: any of the 16
        units missing the tokens."""
        proc = self._stage2_dry(
            campaign_root,
            registry,
            "--gold_required_runtime_profile_path",
            DECLARED_PROFILE_PATH,
            "--gold_required_runtime_profile",
            DECLARED_PROFILE_KEY,
            "--gold_required_runtime_profile_sha256",
            DECLARED_PROFILE_SHA,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _stage2_unit_argvs(proc.stdout)
        assert len(argvs) == 16, argvs.keys()
        for unit, argv in argvs.items():
            pairs = _pairs(argv)
            assert pairs["--required_runtime_profile_path"] == DECLARED_PROFILE_PATH, unit
            assert pairs["--required_runtime_profile"] == DECLARED_PROFILE_KEY, unit
            assert pairs["--required_runtime_profile_sha256"] == DECLARED_PROFILE_SHA, unit

    def test_b_absence_is_printed_explicitly_and_emits_no_token(self, campaign_root):
        """(d) The defect only this catches: an undeclared campaign being
        SILENT about it. Two distinct properties, and both matter.

        Byte-identity: a pre-M4 launch must emit no new token, or every
        existing campaign's child argv changes.

        Explicitness: the dry-run must still SAY that no profile is pinned.
        An absent line is indistinguishable from a feature that is not
        wired — which is precisely how F-PROFILE-WIRE-1 survived. Fails by:
        a token appearing, or the '(none' row disappearing."""
        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        for argv in _band_argvs(proc.stdout).values():
            assert "--required_runtime_profile_path" not in argv
            assert "--required_runtime_profile" not in argv
            assert "--required_runtime_profile_sha256" not in argv
        assert "supplied required_runtime_profile=(none" in proc.stdout, (
            "an undeclared binding must be stated, not omitted"
        )

    def test_b_a_declared_campaign_says_so_in_the_dry_run_row(self, campaign_root):
        """(d) The defect only this catches: the launcher forwarding a
        declaration it never displays, so an M4 operator cannot confirm from
        the dry run WHICH overlay the campaign will require. Fails by: the
        key or digest missing from the printed row."""
        proc = _stage1_dry(
            campaign_root,
            "--gold_required_runtime_profile_path",
            DECLARED_PROFILE_PATH,
            "--gold_required_runtime_profile",
            DECLARED_PROFILE_KEY,
            "--gold_required_runtime_profile_sha256",
            DECLARED_PROFILE_SHA,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        row = [
            line
            for line in proc.stdout.splitlines()
            if "supplied required_runtime_profile=" in line
        ]
        assert row, proc.stdout
        assert DECLARED_PROFILE_KEY in row[0]
        assert DECLARED_PROFILE_SHA in row[0]
        assert DECLARED_PROFILE_PATH in row[0]

    @pytest.mark.parametrize(
        ("extra", "expected"),
        [
            # A PARTIAL declaration is NO declaration: the chain would fall
            # back to the legacy ladder while the operator believed a pin was
            # in force. Refused at the boundary, before any band is forked.
            ((("--gold_required_runtime_profile", DECLARED_PROFILE_KEY),), "INCOMPLETE"),
            (
                (("--gold_required_runtime_profile_sha256", DECLARED_PROFILE_SHA),),
                "INCOMPLETE",
            ),
            (
                (("--gold_required_runtime_profile_path", DECLARED_PROFILE_PATH),),
                "INCOMPLETE",
            ),
            # (key, sha256) with NO path — the shape that shipped before the
            # artifact path was required, and the one an operator following
            # stale notes would most plausibly type. It must now refuse.
            (
                (
                    ("--gold_required_runtime_profile", DECLARED_PROFILE_KEY),
                    ("--gold_required_runtime_profile_sha256", DECLARED_PROFILE_SHA),
                ),
                "INCOMPLETE",
            ),
            # Shape errors caught here rather than in 4 forked children.
            (
                (
                    ("--gold_required_runtime_profile_path", DECLARED_PROFILE_PATH),
                    ("--gold_required_runtime_profile", "h100"),
                    ("--gold_required_runtime_profile_sha256", DECLARED_PROFILE_SHA),
                ),
                "is not '<gpu_slug>/<regime>'",
            ),
            (
                (
                    ("--gold_required_runtime_profile_path", DECLARED_PROFILE_PATH),
                    ("--gold_required_runtime_profile", DECLARED_PROFILE_KEY),
                    ("--gold_required_runtime_profile_sha256", "deadbeef"),
                ),
                "is not 64 lowercase",
            ),
            # A RELATIVE artifact path would resolve against the child's cwd
            # (run_chain cd's before exec), naming a different file than the
            # one qualified.
            (
                (
                    ("--gold_required_runtime_profile_path", "qual/profiles.json"),
                    ("--gold_required_runtime_profile", DECLARED_PROFILE_KEY),
                    ("--gold_required_runtime_profile_sha256", DECLARED_PROFILE_SHA),
                ),
                "is not ABSOLUTE",
            ),
        ],
    )
    def test_c_malformed_or_half_declarations_refuse_before_launching(
        self, campaign_root, extra, expected
    ):
        """(d) The defect only this catches: a typo'd declaration being
        discovered by the CHILD. The stage scripts fork one background chain
        per band, so a digest typo found downstream has already launched the
        fleet. Fails by: a non-zero-free run, or a refusal that does not say
        which half is wrong."""
        flat = [tok for pair in extra for tok in pair]
        proc = _stage1_dry(campaign_root, *flat)
        assert proc.returncode != 0, proc.stdout
        assert expected in proc.stderr, proc.stderr

    def test_d_the_chain_level_spelling_is_a_reserved_passthrough(self, campaign_root):
        """(d) The defect only this catches: an operator passing the CHAIN
        spelling through. Passthrough tokens are appended AFTER the frozen
        args and the chain parser is last-wins, so it would rebind the
        requirement to something the dry-run row and the launch manifest do
        not name — a pinned profile the manifest misreports is worse than no
        pin. Fails by: the token being accepted."""
        for flag in (
            "--required_runtime_profile",
            "--required_runtime_profile_sha256",
            "--required_runtime_profile_path",
        ):
            proc = _stage1_dry(campaign_root, flag, "whatever")
            assert proc.returncode != 0, flag
            assert flag in proc.stderr, flag
            assert "GOLD_RESERVED_PASSTHROUGH" in proc.stderr, flag


# ---------------------------------------------------------------------------
# State-helper fixtures (synthetic band workspaces)
# ---------------------------------------------------------------------------


def _metric_spec_dump(direction: str = "higher") -> dict:
    sys.path.insert(0, str(REPO_ROOT))
    from execute_tools.dataset_config import TIDMAD_PROFILE
    from execute_tools.evaluation_metric import derive_tidmad_metric_spec

    dump = derive_tidmad_metric_spec(TIDMAD_PROFILE).model_dump(mode="json")
    dump["direction"] = direction
    return dump


def _record(
    exp_id: str,
    score: float | None,
    *,
    trial: bool = False,
    valid: bool = True,
    status: str = "success",
) -> dict:
    rec = {
        "exp_id": exp_id,
        "status": status,
        "model_type": "wavenet",
        "params": {},
        "timestamp": "2026-08-26 00:00:30",
        "denoising_score": score,
        # health_gate_enabled=False takes the DS5 designed waiver path in
        # is_valid_candidate (VALID); True with no gate results resolves
        # UNKNOWN (excluded). Both route through the ONE authority.
        "health_gate_enabled": not valid,
    }
    if trial:
        rec["is_trial"] = True
    return rec


def _write_iter(
    workspace: Path,
    idx: int,
    records: list[dict],
    *,
    run_name: str = "goldpod_band0-3",
    spec: dict | None | str = "default",
    manifest_status: str = "completed",
) -> None:
    it = workspace / f"iter_{idx:03d}"
    sub = it / "iteration_001" / "wavenet"
    sub.mkdir(parents=True)
    out_path = sub / f"run_output_{run_name}.json"
    out = {
        "run_name": run_name,
        "model_type": "wavenet",
        "file_index": 0,
        "status": "completed",
        "completed_rounds": 1,
        "total_attempts": len(records),
        "best_exp_id": records[0]["exp_id"] if records else "none",
        "best_denoising_score": 0.0,
        "started_at": "2026-08-26 00:00:00",
        "finished_at": "2026-08-26 00:01:00",
        "all_records": records,
    }
    if spec == "default":
        out["metric_spec"] = _metric_spec_dump()
    elif spec is not None:
        out["metric_spec"] = spec
    out_path.write_text(json.dumps(out))
    manifest = {
        "status": manifest_status,
        "iteration_dir": str(it),
        "output_path": str(out_path),
        "model_name": "wavenet",
    }
    (it / "manifest.json").write_text(json.dumps(manifest))


def _helper(*argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, str(STATE_HELPER), *argv],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=300,
    )


def _band_state(
    workspace: Path, out: Path, *extra: str, horizon: int = 20
) -> tuple[int, dict, str]:
    proc = _helper(
        "band-state",
        "--workspace",
        str(workspace),
        "--horizon",
        str(horizon),
        "--band",
        "0-3",
        "--out",
        str(out),
        *extra,
    )
    data = json.loads(out.read_text()) if proc.returncode == 0 else {}
    return proc.returncode, data, proc.stderr


class TestBandStateHelper:
    def test_winner_rule_excludes_trials_and_invalid_records(self, tmp_path):
        """Contract section 1: a BETTER-scoring trial (is_trial key present)
        and a BETTER-scoring gate-ineligible record must both lose to the
        best HealthGate-valid FORMAL success record."""
        ws = tmp_path / "band"
        ws.mkdir()
        (ws / "run_invariants_lock.json").write_text(json.dumps({"experiment_arm": "goldpod"}))
        _write_iter(
            ws,
            1,
            [
                _record("w_formal_low", -4.0),
                _record("w_trial_best", 5.0, trial=True),
                _record("w_invalid_best", 9.9, valid=False),
                _record("w_failed", 11.0, status="error_training"),
            ],
        )
        _write_iter(ws, 2, [_record("w_formal_best", -1.2)])
        rc, data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 0, err
        assert data["incumbent"]["exp_id"] == "w_formal_best"
        assert data["incumbent"]["denoising_score"] == -1.2
        assert data["incumbent"]["experiment_arm"] == "goldpod"
        assert data["incumbent"]["iteration"] == 2
        assert data["next_iter"] == 3
        assert data["committed_count"] == 2
        assert data["terminal"] is False

    def test_direction_comes_from_the_stamped_spec(self, tmp_path):
        """A lower-is-better spec flips the winner — the scanner asks
        MetricOrder, never assumes higher-is-better (contract section 1)."""
        ws = tmp_path / "band"
        ws.mkdir()
        spec = _metric_spec_dump(direction="lower")
        _write_iter(ws, 1, [_record("w_high", 5.0), _record("w_low", 2.0)], spec=spec)
        rc, data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 0, err
        assert data["incumbent"]["exp_id"] == "w_low"
        assert data["incumbent"]["metric_direction"] == "lower"

    def test_missing_metric_spec_refuses_fail_closed(self, tmp_path):
        """A formal success record whose output stamps NO metric_spec is a
        NAMED refusal (Step-09a rule) — never an assumed direction."""
        ws = tmp_path / "band"
        ws.mkdir()
        _write_iter(ws, 1, [_record("w_1", 1.0)], spec=None)
        rc, _data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 2
        assert "metric_spec" in err

    def test_stop_rule_tristate(self, tmp_path):
        """No reference -> not evaluable (A2-FCNET interim, full horizon);
        reference met -> satisfied + terminal; reference not met -> keeps
        running. The +2.0 margin is applied toward BETTER."""
        ws = tmp_path / "band"
        ws.mkdir()
        _write_iter(ws, 1, [_record("w_1", -1.2)])
        out = tmp_path / "state.json"

        rc, data, err = _band_state(ws, out)
        assert rc == 0, err
        assert data["stop_rule_evaluable"] is False
        assert data["terminal"] is False

        met = tmp_path / "ref_met.json"
        met.write_text(json.dumps({"per_band": {"0-3": -3.5}}))  # target -1.5; -1.2 clears
        rc, data, err = _band_state(ws, out, "--fcnet-reference-json", str(met))
        assert rc == 0, err
        assert data["stop_rule_satisfied"] is True
        assert data["terminal"] is True
        assert data["terminal_reason"] == "stop_rule_satisfied"
        assert data["terminal_ok"] is True

        unmet = tmp_path / "ref_unmet.json"
        unmet.write_text(json.dumps({"per_band": {"0-3": -2.9}}))  # target -0.9; -1.2 short
        rc, data, err = _band_state(ws, out, "--fcnet-reference-json", str(unmet))
        assert rc == 0, err
        assert data["stop_rule_evaluable"] is True
        assert data["stop_rule_satisfied"] is False
        assert data["terminal"] is False

    def test_horizon_exhaustion(self, tmp_path):
        ws = tmp_path / "band"
        ws.mkdir()
        _write_iter(ws, 1, [_record("w_1", -1.0)])
        _write_iter(ws, 2, [_record("w_2", -0.5)])
        rc, data, err = _band_state(ws, tmp_path / "state.json", horizon=2)
        assert rc == 0, err
        assert data["terminal"] is True
        assert data["terminal_reason"] == "horizon_exhausted"
        assert data["terminal_ok"] is True

    def test_failed_first_iter_needs_force_fresh(self, tmp_path):
        """The NAMED stale-fresh corner: iter_001 exists non-completed with
        nothing committed — the loop must know to pass --force_fresh (and
        ONLY then)."""
        ws = tmp_path / "band"
        ws.mkdir()
        _write_iter(ws, 1, [], manifest_status="failed")
        rc, data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 0, err
        assert data["next_iter"] == 1
        assert data["needs_force_fresh"] is True

        fresh = tmp_path / "never_launched"
        rc, data, err = _band_state(fresh, tmp_path / "state2.json")
        assert rc == 0, err
        assert data["needs_force_fresh"] is False


class TestStage2Finalize:
    def _build_unit(self, tmp_path: Path, *, band: str, indices: tuple[int, ...]) -> Path:
        """A synthetic unit holding deliverables for exactly ``indices`` —
        the band-scoped chain's shape is the band's own indices ONLY
        (DataScope retention under --data_scope leaves nothing else)."""
        unit = tmp_path / "stage2" / f"wavenetA_{band}"
        ws = unit / "workspace"
        ws.mkdir(parents=True)
        run_name = f"goldpod_stage2_wavenetA_{band}"
        _write_iter(ws, 1, [_record("w_unit_1", -2.5)], run_name=run_name)
        sys.path.insert(0, str(REPO_ROOT))
        from execute_tools.deliverable_spec import default_deliverable_naming

        naming = default_deliverable_naming()
        data_dir = ws / "iter_001" / "iteration_001" / "wavenet" / "data"
        data_dir.mkdir()
        for idx in indices:
            name = naming.name(
                model_type="wavenet",
                run_name=run_name,
                exp_id="w_unit_1",
                input_identity=idx,
            )
            (data_dir / name).write_bytes(b"h5-bytes")
        return unit

    def _names_for(self, band: str, indices: tuple[int, ...]) -> set[str]:
        sys.path.insert(0, str(REPO_ROOT))
        from execute_tools.deliverable_spec import default_deliverable_naming

        naming = default_deliverable_naming()
        return {
            naming.name(
                model_type="wavenet",
                run_name=f"goldpod_stage2_wavenetA_{band}",
                exp_id="w_unit_1",
                input_identity=idx,
            )
            for idx in indices
        }

    # Q-S3-2 ruling A: the band's file set and count are HARDCODED here —
    # 4/6/5/5, never 20, and never read back from the code under test.
    @pytest.mark.parametrize(
        ("band", "band_indices", "count"),
        [
            ("0-3", (0, 1, 2, 3), 4),
            ("4-9", (4, 5, 6, 7, 8, 9), 6),
            ("10-14", (10, 11, 12, 13, 14), 5),
            ("15-19", (15, 16, 17, 18, 19), 5),
        ],
    )
    def test_finalize_copies_exactly_the_band_set(self, tmp_path, band, band_indices, count):
        """A band-complete unit (its band's files ONLY — the shape a
        --data_scope run leaves behind) finalizes with the band-derived
        count. The retired range(20) loop REFUSED these same units on the
        first out-of-band index, so a green here is the Q-S3-2 closure:
        band-scoped launch + band-scoped finalize compose."""
        unit = self._build_unit(tmp_path, band=band, indices=band_indices)
        proc = _helper(
            "stage2-finalize",
            "--unit-dir",
            str(unit),
            "--design",
            "wavenetA",
            "--target-band",
            band,
        )
        assert proc.returncode == 0, proc.stderr
        marker = json.loads((unit / "COMPLETE.json").read_text())
        assert marker["design"] == "wavenetA"
        assert marker["target_band"] == band
        assert marker["exp_id"] == "w_unit_1"
        assert marker["model_type"] == "wavenet"
        assert marker["denoising_score"] == -2.5
        assert marker["healthgate_valid"] is True
        assert marker["deliverable_count"] == count
        copied = {p.name for p in (unit / "deliverables").iterdir()}
        assert copied == self._names_for(band, band_indices)

    def test_out_of_band_files_present_are_never_copied(self, tmp_path):
        """A legacy workspace holding ALL 20 files must still yield a
        BAND-pure deliverables/ dir (out-of-band indices never consulted,
        never copied — otherwise strict_best's whole-dir pooling would
        refuse duplicate indices across a design's four band dirs)."""
        unit = self._build_unit(tmp_path, band="4-9", indices=tuple(range(20)))
        proc = _helper(
            "stage2-finalize",
            "--unit-dir",
            str(unit),
            "--design",
            "wavenetA",
            "--target-band",
            "4-9",
        )
        assert proc.returncode == 0, proc.stderr
        marker = json.loads((unit / "COMPLETE.json").read_text())
        assert marker["deliverable_count"] == 6
        copied = {p.name for p in (unit / "deliverables").iterdir()}
        assert copied == self._names_for("4-9", (4, 5, 6, 7, 8, 9))

    def test_missing_band_file_refuses_and_writes_no_marker(self, tmp_path):
        """The atomic contract: absence of COMPLETE.json == unit not done.
        5/6 band files leave NO marker; the refusal names the missing BAND
        index (7) and the retention rule. Before the Q-S3-2 fix this exact
        refusal was MASKED by an out-of-band 'file 0' refusal (range(20)
        consulted 0 first), so the file-0 absence assertion is the unmask
        witness — out-of-band indices are never consulted, never named."""
        unit = self._build_unit(tmp_path, band="4-9", indices=(4, 5, 6, 8, 9))
        proc = _helper(
            "stage2-finalize",
            "--unit-dir",
            str(unit),
            "--design",
            "wavenetA",
            "--target-band",
            "4-9",
        )
        assert proc.returncode == 2
        assert not (unit / "COMPLETE.json").exists()
        assert "band 4-9 file 7" in proc.stderr
        assert "R-RETENTION-1" in proc.stderr
        assert "file 0" not in proc.stderr

    def test_malformed_target_band_refuses_named(self, tmp_path):
        """--target-band is a PARSED authority input now (DataScope.from_cli
        — the same parse the unit chain applied to its --data_scope), not a
        recorded label: garbage refuses NAMED with no marker, even over a
        unit that would otherwise finalize."""
        unit = self._build_unit(tmp_path, band="4-9", indices=(4, 5, 6, 7, 8, 9))
        proc = _helper(
            "stage2-finalize",
            "--unit-dir",
            str(unit),
            "--design",
            "wavenetA",
            "--target-band",
            "banana",
        )
        assert proc.returncode == 2
        assert not (unit / "COMPLETE.json").exists()
        assert "banana" in proc.stderr
