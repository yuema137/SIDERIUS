"""F-LAUNCH-1 — the canonical Gold campaign entrypoint (contract PR #329).

Each test names the defect ONLY it can catch:

* ``TestFrozenLlmRouting`` — F-LLM-WIRE-1 (release blocker): the historical
  Stage-2 path binds the frozen routing config, the runner's REAL parser +
  ``WorkflowLLMConfig`` resolve the pinned snapshot model, and the
  non-campaign chain default still legitimately omits the flag. The
  defect class: ``--llm_config`` is optional at every hop, so omitting it
  ran the entire official campaign on the deprecated all-Gemini default
  while still exiting 0 — the pin was real and nothing consumed it.
* ``TestGenericRetentionCompatibility`` — the exploratory chain default
  still cleans up, the typed retention token suppresses that cleanup, and
  SDSc mode refuses retention it cannot honor.
* ``TestX9BandFileParity`` — the historical X9 band launcher and Gold
  campaign still agree on the monitored-file membership of each band.
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
import re
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
LIB = SDSC / "_gold_campaign_lib.sh"
CHAIN_COMMON = SDSC / "_chain_common.sh"
RUN_CHAIN = SDSC / "run_chain.sh"
STATE_HELPER = SDSC / "gold_campaign_state.py"

#: The canonical nineteen (decisions D-BUD-2 / D-BUD-3 / D-BUD-4 / D-BUD-6 /
#: D-BUD-7 / D-BUD-8 / D-BUD-11/13 / P6-A / P6-B), HARDCODED on purpose — see
#: module docstring. D-BUD-6 is the PAIR ``trial_max_epochs / formal_max_epochs``
#: (the frozen trial/formal split, both 1 since the operator lowered the TRIAL
#: value 2 -> 1 on 2026-08-27 to make the in-search trial a fast viability
#: screen; the per-mode split mechanism is unchanged); the retired
#: mode-agnostic ``--max_epochs 1`` stand-in is now a RESERVED passthrough,
#: not an emitted value). The last six are F-LAUNCH-1 / adversarial F-2: they
#: rode ``_chain_common.sh`` defaults that AGREE with the frozen values, so
#: the gap was invisible to every check of effective values.
CANONICAL_NINETEEN = {
    "--num_iterations": "20",
    "--trial_portion": "0.1",
    "--train_portion": "0.1",
    "--eval_portion": "0.01",
    "--formal_portion": "1.0",
    "--formal_train_portion": "0.1",
    "--formal_eval_portion": "0.1",
    "--trial_max_epochs": "1",
    "--formal_max_epochs": "1",
    "--trial_time_budget_minutes": "30",
    "--formal_time_budget_minutes": "120",
    "--skip_formal_min_delta": "-2.0",
    "--bypass_formal_time_budget_min_delta": "0.5",
    # D-BUD-3 — the [trial, trial, formal] round structure.
    "--max_rounds": "3",
    # D-BUD-4 — the attempt budgets ("gold_blind: exactly the same values").
    "--attempts_per_round": "3",
    "--attempts_per_formal_round": "5",
    "--max_fail_rounds": "3",
    "--max_proposal_attempts": "3",
    "--max_impl_attempts": "3",
}

#: The six the F-LAUNCH-1 / F-2 commit added, named separately so a test can
#: assert THEM rather than the whole table. Hardcoded for the same reason.
BUDGETS_BOUND_BY_F_LAUNCH_1 = {
    "--max_rounds": "3",
    "--attempts_per_round": "3",
    "--attempts_per_formal_round": "5",
    "--max_fail_rounds": "3",
    "--max_proposal_attempts": "3",
    "--max_impl_attempts": "3",
}

#: The campaign's frozen LLM routing authority (D-LLM-1). HARDCODED here for
#: the same reason the nineteen are: reading the path back out of the lib
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


class TestBypassTransportCompatibility:
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


class TestGenericRetentionCompatibility:
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


class TestX9BandFileParity:
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
                assert pairs[flag] == CANONICAL_NINETEEN[flag], (unit, flag)
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


class TestHistoricalStage2RuntimeProfileDeclaration:
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


#: ARBITRARY TRANSPORT PROBES — NOT the campaign's ceiling, and deliberately
#: not near any value anybody has proposed for one. D-HW-6's ceiling is
#: HARDWARE_DERIVED / PENDING_H100_QUALIFICATION, so no number is bound
#: anywhere on the production path; these exist ONLY to be recognisable on
#: the far side of the transport. They DIFFER from each other on purpose:
#: identical probes could not tell a faithful two-value transport apart from
#: one that carries the trial value into both slots.
PROBE_TRIAL_VRAM = "7.5"
PROBE_FORMAL_VRAM = "9.25"


class TestHistoricalStage2AndGenericVramTransport:
    """Retained Stage-2 and generic transport evidence for D-HW-6.

    Stage-1 policy and concrete campaign values are owned externally. These
    tests preserve only the independent historical Stage-2 builder, the real
    chain-to-typed-config transport, and non-campaign empty-default behavior.

    UNITS ARE OUT OF SCOPE BY DESIGN. D-HW-6 records a live GB/GiB gap (the
    flags spell ``_gb``; ``evaluate_vram_skill/wrapper.py`` multiplies by
    ``_GB = 1024**3``). The seam carries the operator's value unchanged, so
    no test here may assert a converted or normalised number — that would
    silently settle a question the decision record leaves open.
    """

    @pytest.fixture
    def registry(self, tmp_path: Path) -> Path:
        reg = tmp_path / "designs"
        reg.mkdir()
        for design in ("wavenetA", "punetB", "rnnC", "fnoD"):
            (reg / f"{design}.json").write_text("{}\n")
        return reg

    def _supplied(self) -> list[str]:
        return [
            "--gold_trial_vram_budget_gb",
            PROBE_TRIAL_VRAM,
            "--gold_formal_vram_budget_gb",
            PROBE_FORMAL_VRAM,
        ]

    def test_a_supplied_ceiling_reaches_every_stage2_unit_argv(self, campaign_root, registry):
        """(d) The defect only this catches: the ceiling reaching stage 1 but
        not stage 2. The two stages build argv in SEPARATE scripts, so one
        binder feeding both is an assumption until witnessed. A stage-2
        retrain running uncapped while its stage-1 band ran capped would
        train the frozen designs under a different memory regime than the
        search that selected them. Fails by: any of the 16 units missing a
        token."""
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
            *self._supplied(),
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _stage2_unit_argvs(proc.stdout)
        assert len(argvs) == 16, argvs.keys()
        for unit, argv in argvs.items():
            pairs = _pairs(argv)
            assert pairs["--trial_vram_budget_gb"] == PROBE_TRIAL_VRAM, unit
            assert pairs["--formal_vram_budget_gb"] == PROBE_FORMAL_VRAM, unit

    def test_a_the_value_ARRIVES_at_the_consumer_through_the_real_transport(self, campaign_root):
        """(d) THE witness. The defect only this catches: a ceiling that is
        present in argv and consumed by nothing.

        Argv presence proves a string was assembled. It does NOT prove the
        value survives ``_chain_common.sh``'s parse (which forwards each
        budget only inside an ``if [ -n ... ]``), nor that the runner's
        argparse binds it, nor that it lands on the typed object the
        workflow actually reads. Each of those hops has an omission mode
        that still exits 0 — which is precisely how every defect in this
        release's family survived.

        So the launcher's OWN emitted argv is walked through the production
        hops: real ``parse_chain_args`` + ``build_app_args``, real
        ``run_one_iteration.py`` argparse, real ``WorkflowLaunchConfig``
        construction — the object ``model_exploration`` reads at the point
        it picks the active budget.

        Boundary stated honestly: this stops at ``WorkflowLaunchConfig``,
        the last hop the SEAM owns. Enforcement beyond it (the tuner's
        per-mode gate and ``evaluate_vram_skill``'s cap arithmetic) is
        landed behaviour with its own tests and needs a sandbox/GPU.

        The negative half is what makes it a witness and not a tautology:
        the identical parsers with the flags ABSENT must yield ``None`` —
        i.e. no operator ceiling — so a green assertion cannot be explained
        by a default that was going to be there anyway.

        Fails by: the value being dropped at any hop, or coerced to
        something other than what was supplied."""
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root, *self._supplied())
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
        assert "--trial_vram_budget_gb" in app_args, app_args
        assert "--formal_vram_budget_gb" in app_args, app_args

        spec = importlib.util.spec_from_file_location(
            "roi_for_vram_seam_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        from workflows.run_config import WorkflowLaunchConfig

        ns = roi.build_parser().parse_args(app_args)
        assert ns.trial_vram_budget_gb == float(PROBE_TRIAL_VRAM)
        assert ns.formal_vram_budget_gb == float(PROBE_FORMAL_VRAM)

        # The production construction site (run_one_iteration.py) — the
        # typed object model_exploration reads.
        launch = WorkflowLaunchConfig(
            trial_vram_budget_gb=ns.trial_vram_budget_gb,
            formal_vram_budget_gb=ns.formal_vram_budget_gb,
        )
        assert launch.trial_vram_budget_gb == float(PROBE_TRIAL_VRAM)
        assert launch.formal_vram_budget_gb == float(PROBE_FORMAL_VRAM)

        # The negative half — the same parsers, the flags omitted.
        bare = roi.build_parser().parse_args(["--workspace", "/tmp/x", "--run_name", "t"])
        assert bare.trial_vram_budget_gb is None
        assert bare.formal_vram_budget_gb is None
        assert WorkflowLaunchConfig().trial_vram_budget_gb is None
        assert WorkflowLaunchConfig().formal_vram_budget_gb is None

    def test_g_the_non_campaign_chain_path_is_behaviourally_unchanged(self, tmp_path):
        """(d) The defect only this catches: the seam leaking a ceiling into
        NON-Gold chains. The obvious way to 'wire VRAM up' would have been to
        give ``_chain_common.sh`` a default budget — which would silently cap
        every exploratory run, every X9 launcher and every smoke on the box,
        none of which asked for one.

        This drives the chain parser DIRECTLY with a non-campaign argv (no
        Gold script involved) and asserts the pre-existing 'empty == omit'
        contract still holds. Fails by: either token appearing in APP_ARGS
        for a chain that supplied no budget."""
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args --workspace {shlex.quote(str(tmp_path / 'w'))} "
            "--run_name t; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert built.returncode == 0, built.stderr
        app_args = [tok for tok in built.stdout.splitlines() if tok]
        assert "--trial_vram_budget_gb" not in app_args, app_args
        assert "--formal_vram_budget_gb" not in app_args, app_args


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

    def test_validity_is_judged_against_the_WORKSPACES_OWN_pinned_config(self, tmp_path):
        """F-4 — the band incumbent must be eligible under the RUN's roster.

        Eligibility used to be asked as ``is_valid_candidate(rec)``, whose
        zero-argument default resolves the REPO-CURRENT shipped config — a
        roster belonging to no particular run — and collapses UNKNOWN to the
        empty set on the way. So a record was judged against gates its own run
        never declared.

        The two records below make the two answers disagree, which is the only
        way to see the defect:

        * ``w_run_gate_failed`` (score 9.9) passes every REPO-CURRENT blocking
          gate and FAILS the run's own. Repo-current says VALID; the run's own
          roster says INVALID.
        * ``w_run_gate_passed`` (score 1.0) passes the run's own gate and
          carries none of the repo-current ones. Repo-current says UNKNOWN
          (excluded); the run's own roster says VALID.

        Fails as: the incumbent being ``w_run_gate_failed`` — the higher score,
        promoted on the strength of a roster it never ran. That incumbent is
        the FCNet+2 stop input and Stage-2's ``healthgate_valid``.
        """
        sys.path.insert(0, str(REPO_ROOT))
        from execute_tools.health_checks.candidate_eligibility import (
            pinned_workspace_gate_ids,
            required_blocking_gate_ids,
        )
        from tests.helpers.health_task_config import write_pinned_effective_config

        ws = tmp_path / "band"
        write_pinned_effective_config(ws, ["witness_run_declared_blocking"])
        run_declared = sorted(pinned_workspace_gate_ids(ws) or ())
        repo_current = sorted(required_blocking_gate_ids())

        # Vacuity guards: both rosters non-empty and DISJOINT, or a record
        # satisfying one would satisfy the other and this proves nothing.
        assert repo_current and run_declared
        assert not (set(repo_current) & set(run_declared))

        def _gate(name: str, passed: bool) -> dict:
            return {"gate_name": name, "execution_status": "passed", "check_passed": passed}

        _write_iter(
            ws,
            1,
            [
                {
                    "exp_id": "w_run_gate_failed",
                    "status": "success",
                    "model_type": "wavenet",
                    "params": {},
                    "timestamp": "2026-08-26 00:00:30",
                    "denoising_score": 9.9,
                    "health_gate_enabled": True,
                    "health_gate_results": [
                        *(_gate(g, True) for g in repo_current),
                        *(_gate(g, False) for g in run_declared),
                    ],
                },
                {
                    "exp_id": "w_run_gate_passed",
                    "status": "success",
                    "model_type": "wavenet",
                    "params": {},
                    "timestamp": "2026-08-26 00:00:30",
                    "denoising_score": 1.0,
                    "health_gate_enabled": True,
                    "health_gate_results": [_gate(g, True) for g in run_declared],
                },
            ],
        )

        rc, data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 0, err
        assert data["incumbent"]["exp_id"] == "w_run_gate_passed"
        assert data["incumbent"]["denoising_score"] == 1.0
        assert data["scan"]["formal_success"] == 2
        assert data["scan"]["healthgate_valid"] == 1


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


# ---------------------------------------------------------------------------
# #316 B2 — the PERSISTED formal-record shape
# ---------------------------------------------------------------------------


def _persisted_record(
    exp_id: str,
    score: float,
    *,
    trial: bool = False,
    valid: bool = True,
) -> dict:
    """A record in the shape production actually WRITES to disk.

    Built through the PRODUCTION schema path — ``ExperimentRecord``
    ``model_validate`` -> ``model_dump`` — which is exactly what
    ``records.py`` does (``:1041`` -> ``:1046`` -> ``:1052``
    ``publish_json_atomically``) because
    ``HyperparamTuningOutput.all_records`` is typed
    ``list[ExperimentRecord]`` and re-validates every dict.

    This is deliberately NOT ``_record()`` above. ``_record()`` hand-builds
    the dict and sets ``is_trial`` ONLY when ``trial=True``, i.e. it
    produces the one shape production NEVER persists — which is precisely
    why the absence-test defect (#316 B2) survived a test suite that
    appears to cover the winner rule. A hand-built dict cannot witness a
    materialized-default defect.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from agent.schemas.hyperparam_tuning import ExperimentRecord

    raw = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-26 00:00:30",
        "params": {},
        "denoising_score": score,
        # Same DS5 waiver routing as _record(): False takes the designed
        # waiver path in is_valid_candidate (VALID), True with no gate
        # results resolves UNKNOWN (excluded). One eligibility authority.
        "health_gate_enabled": not valid,
    }
    if trial:
        raw["is_trial"] = True
        raw["trial_portion"] = 0.1
    return ExperimentRecord.model_validate(raw).model_dump()


class TestPersistedFormalRecordShape:
    """#316 B2 — the Stage-1/Stage-2 reader must accept the record shape
    production PERSISTS, not the one the builder holds in memory.

    The frozen contract (``stage_artifact_contract.md`` section 1) is three
    cases, and the defect lived in the gap between two of them::

        is_trial is True    -> trial   (excluded)
        is_trial is False   -> FORMAL
        is_trial absent     -> FORMAL

    ``gold_campaign_state.py`` tested ``"is_trial" in rec``, which collapses
    the middle case into the first. Every real formal record carries the
    materialized default ``is_trial: False``, so the champion set was
    PERMANENTLY EMPTY. Nothing errored: Stage 1 exits 0 having burned its
    full 20-iteration horizon with a null winner, and Stage 2 refuses all
    16 units at ``stage2-finalize``.
    """

    def test_the_production_persisted_shape_carries_the_materialized_defaults(self):
        """The PREMISE, pinned with hardcoded expectations.

        If this ever stops holding, the three witnesses below stop being
        about production and become about a fixture. Asserting against
        ``model_fields[...].default`` would compare the schema to itself.
        """
        rec = _persisted_record("w_formal", -1.2)
        assert "is_trial" in rec, (
            "ExperimentRecord.model_dump() must MATERIALIZE is_trial onto every "
            "persisted formal record — that materialization is the whole defect."
        )
        assert rec["is_trial"] is False
        assert rec["trial_portion"] is None

    def test_case_is_trial_FALSE_is_formal_and_a_winner_emerges(self, tmp_path):
        """CASE 2 (the defect). A band whose ONLY records are
        production-persisted formal records must yield a NON-EMPTY
        champion. Under ``"is_trial" in rec`` this band's incumbent was
        null while the helper still exited 0."""
        ws = tmp_path / "band"
        ws.mkdir()
        (ws / "run_invariants_lock.json").write_text(json.dumps({"experiment_arm": "goldpod"}))
        _write_iter(ws, 1, [_persisted_record("w_formal_low", -4.0)])
        _write_iter(ws, 2, [_persisted_record("w_formal_best", -1.2)])
        rc, data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 0, err
        assert data["incumbent"] is not None, (
            "champion set EMPTY on a band of purely production-shaped formal "
            "records — this is #316 B2: Stage 1 burns its horizon silently."
        )
        assert data["incumbent"]["exp_id"] == "w_formal_best"
        assert data["incumbent"]["denoising_score"] == -1.2

    def test_case_is_trial_ABSENT_is_formal_and_a_winner_emerges(self, tmp_path):
        """CASE 3, witnessed SEPARATELY from case 2 because it is a
        different input and the old code got this one right by accident.

        A key-less record is the BUILDER's in-memory / legacy shape. The
        contract admits it as FORMAL, so the fix must not narrow the rule
        to "is_trial is False" while closing the middle case.
        """
        ws = tmp_path / "band"
        ws.mkdir()
        (ws / "run_invariants_lock.json").write_text(json.dumps({"experiment_arm": "goldpod"}))
        keyless = _persisted_record("w_keyless", -2.0)
        del keyless["is_trial"]
        del keyless["trial_portion"]
        _write_iter(ws, 1, [keyless])
        rc, data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 0, err
        assert data["incumbent"] is not None
        assert data["incumbent"]["exp_id"] == "w_keyless"

    def test_case_is_trial_TRUE_is_still_excluded(self, tmp_path):
        """CASE 1, the negative. Widening the predicate must NOT admit
        trials: a BETTER-scoring persisted TRIAL loses to a WORSE formal
        record. Without this, `return True` would pass both witnesses
        above."""
        ws = tmp_path / "band"
        ws.mkdir()
        (ws / "run_invariants_lock.json").write_text(json.dumps({"experiment_arm": "goldpod"}))
        _write_iter(
            ws,
            1,
            [
                _persisted_record("w_formal_only", -4.0),
                _persisted_record("w_trial_better", 9.9, trial=True),
            ],
        )
        rc, data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 0, err
        assert data["incumbent"]["exp_id"] == "w_formal_only"
        assert data["incumbent"]["denoising_score"] == -4.0

    @pytest.mark.parametrize(
        ("field", "value", "needle"),
        [
            ("is_trial", "yes", "non-bool role"),
            ("trial_portion", 0.1, "trial-only value"),
        ],
    )
    def test_anomalous_role_shapes_refuse_loudly(self, tmp_path, field, value, needle):
        """A shape production never writes is REFUSED by name, never
        silently classified — a silent choice here could silently move the
        winner."""
        ws = tmp_path / "band"
        ws.mkdir()
        (ws / "run_invariants_lock.json").write_text(json.dumps({"experiment_arm": "goldpod"}))
        bad = _persisted_record("w_bad", -1.0)
        bad[field] = value
        _write_iter(ws, 1, [bad])
        rc, _data, err = _band_state(ws, tmp_path / "state.json")
        assert rc == 2, f"expected a loud refusal, got rc={rc}"
        assert needle in err
        assert "w_bad" in err

    def test_all_sixteen_stage2_units_finalize_on_persisted_records(self, tmp_path):
        """The Stage-2 consequence, end to end.

        ``stage2_strict_retrain.sh:217`` gates the whole stage on
        ``done_count -eq 16``, counting COMPLETE.json markers. Under the
        absence test EVERY unit's finalize hit
        "no FORMAL success record with a usable score" (``:496``) -> rc 2
        (``:499``) -> no marker (``:199``) -> ``done_count`` stuck at 0.
        Sixteen units whose records are production-shaped must all
        finalize.
        """
        designs = ("wavenetA", "wavenetB", "punetA", "punetB")
        bands = {
            "0-3": (0, 1, 2, 3),
            "4-9": (4, 5, 6, 7, 8, 9),
            "10-14": (10, 11, 12, 13, 14),
            "15-19": (15, 16, 17, 18, 19),
        }
        sys.path.insert(0, str(REPO_ROOT))
        from execute_tools.deliverable_spec import default_deliverable_naming

        naming = default_deliverable_naming()
        stage2_root = tmp_path / "stage2"
        for design in designs:
            for band, indices in bands.items():
                unit = stage2_root / f"{design}_{band}"
                ws = unit / "workspace"
                ws.mkdir(parents=True)
                run_name = f"goldpod_stage2_{design}_{band}"
                _write_iter(ws, 1, [_persisted_record("w_unit_1", -2.5)], run_name=run_name)
                data_dir = ws / "iter_001" / "iteration_001" / "wavenet" / "data"
                data_dir.mkdir()
                for idx in indices:
                    (
                        data_dir
                        / naming.name(
                            model_type="wavenet",
                            run_name=run_name,
                            exp_id="w_unit_1",
                            input_identity=idx,
                        )
                    ).write_bytes(b"h5-bytes")
                proc = _helper(
                    "stage2-finalize",
                    "--unit-dir",
                    str(unit),
                    "--design",
                    design,
                    "--target-band",
                    band,
                )
                assert proc.returncode == 0, f"{design}_{band}: {proc.stderr}"

        done_count = len(list(stage2_root.glob("*/COMPLETE.json")))
        assert done_count == 16, (
            f"stage2_strict_retrain.sh:217 requires done_count -eq 16; got {done_count}"
        )


# ---------------------------------------------------------------------------
# #316 B1 / F-GATE-WIRE-1 — the incumbent-formal-gate switch
# ---------------------------------------------------------------------------

#: The frozen deltas, HARDCODED. Reading them back from the lib would compare
#: the table to itself and pass for any table (same rule as the nineteen).
FROZEN_SKIP_DELTA = -2.0
FROZEN_BYPASS_DELTA = 0.5
GATE_SWITCH = "--enable_chain_incumbent_formal_gates"


class TestIncumbentFormalGateSwitch:
    """#316 B1 — the Gold launcher declared two formal-gate deltas and never
    emitted the switch that makes them consumable.

    ``skip_formal_min_delta=-2.0`` and
    ``bypass_formal_time_budget_min_delta=0.5`` were transported and parsed
    all the way to the tuner, where
    ``ml_hyperparameter_tune_agent.py:1103-1107`` nulls the reference unless
    the switch is on. Both gates then resolve ``gates_disabled`` and go
    inert. Nothing fails; the campaign runs its whole horizon with a
    scientific policy that was declared, transported and never applied.

    The predecessor campaign emitted the switch on the line directly above
    the same two deltas (``launch_v20_campaign.sh:158-160``).
    """

    def test_the_switch_reaches_every_stage1_band_argv(self, campaign_root):
        """Textual half, stage 1: all four bands."""
        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _band_argvs(proc.stdout)
        assert set(argvs) == {"0-3", "4-9", "10-14", "15-19"}
        for band, argv in argvs.items():
            assert GATE_SWITCH in argv, f"band {band} argv has no {GATE_SWITCH}"
            pairs = _pairs(argv)
            assert float(pairs["--skip_formal_min_delta"]) == FROZEN_SKIP_DELTA
            assert float(pairs["--bypass_formal_time_budget_min_delta"]) == FROZEN_BYPASS_DELTA

    def test_the_switch_reaches_every_stage2_unit_argv(self, campaign_root, tmp_path):
        """Textual half, stage 2: a retrain unit must not run under
        different gate semantics than the band it retrains — which is why
        the emission lives in the ONE builder both stages consume."""
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
            "--gold_advice_file",
            str(campaign_root["advice"]),
            "--design_registry",
            str(registry),
            "--dry-run",
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout
        unit_argvs = _stage2_unit_argvs(proc.stdout)
        assert unit_argvs, "no stage-2 unit argv blocks in the dry run"
        for unit, argv in unit_argvs.items():
            assert GATE_SWITCH in argv, f"unit {unit} argv has no {GATE_SWITCH}"

    def test_the_real_transport_delivers_an_armed_switch_to_the_runner(self, campaign_root):
        """The launcher's OWN argv walked through the production hops —
        ``_chain_common.sh`` ``parse_chain_args`` + ``build_app_args``, then
        ``run_one_iteration.py``'s REAL argparse.

        ``_chain_common.sh:129`` defaults the switch OFF and ``:662`` forwards
        it only when it arrives, so this is where a dropped emission becomes
        an unarmed run."""
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        chain_args = _band_argvs(proc.stdout)["0-3"][3:]
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args {' '.join(shlex.quote(a) for a in chain_args)}; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        assert built.returncode == 0, built.stderr
        app_args = [tok for tok in built.stdout.splitlines() if tok]
        assert GATE_SWITCH in app_args, "the chain parse+forward dropped the switch"

        spec = importlib.util.spec_from_file_location(
            "roi_for_gate_wire_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        ns = roi.build_parser().parse_args(app_args)
        assert ns.enable_chain_incumbent_formal_gates is True
        assert ns.skip_formal_min_delta == FROZEN_SKIP_DELTA
        assert ns.bypass_formal_time_budget_min_delta == FROZEN_BYPASS_DELTA

        # The negative half: the identical parser with the switch absent is
        # what the campaign was actually running.
        bare = roi.build_parser().parse_args(["--workspace", "/tmp/x", "--run_name", "t"])
        assert bare.enable_chain_incumbent_formal_gates is False

    def test_the_gates_evaluate_live_with_the_switch_and_are_inert_without_it(self, campaign_root):
        """THE BEHAVIOURAL WITNESS. An argv assertion proves a token was
        copied; this proves a POLICY was applied.

        The real resolver is driven at the production call-site condition
        (``ml_hyperparameter_tune_agent.py:1103-1107``) for BOTH switch
        states, with the switch value taken from the REAL parsed args, and
        both real gate predicates are then evaluated against three winner
        scores chosen to straddle both thresholds.

        Note ``_should_bypass_formal_time_budget`` takes no ``gates_enabled``
        argument — it is inert only because the resolver handed it a ``None``
        threshold. That is why this is ONE fix and not two: the inertness
        originates at the reference-nulling call site, so restoring the
        switch re-arms both gates at once.
        """
        pytest.importorskip("pydantic")
        import importlib.util

        proc = _stage1_dry(campaign_root)
        chain_args = _band_argvs(proc.stdout)["0-3"][3:]
        built = _bash(
            "-c",
            f"source '{CHAIN_COMMON}'; "
            f"parse_chain_args {' '.join(shlex.quote(a) for a in chain_args)}; "
            'build_app_args 1; printf "%s\\n" "${APP_ARGS[@]}"',
        )
        app_args = [tok for tok in built.stdout.splitlines() if tok]
        spec = importlib.util.spec_from_file_location(
            "roi_for_gate_behaviour_test", SDSC / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)
        ns = roi.build_parser().parse_args(app_args)

        sys.path.insert(0, str(REPO_ROOT))
        from execute_tools.dataset_config import TIDMAD_PROFILE
        from execute_tools.evaluation_metric import derive_tidmad_metric_spec
        from execute_tools.metric_order import MetricOrder
        from nodes.ml_hyperparameter_tune_agent.policy import (
            _resolve_formal_comparison_thresholds,
            _should_bypass_formal_time_budget,
            _should_skip_formal,
        )

        order = MetricOrder(derive_tidmad_metric_spec(TIDMAD_PROFILE))
        assert order.direction == "higher", "fixture assumes the TIDMAD direction"
        incumbent = 5.0

        def resolve(switch: bool):
            # The production call-site expression, mirrored verbatim. The
            # source guard below fails if production stops doing this.
            consumed = incumbent if switch else None
            return _resolve_formal_comparison_thresholds(
                reference_score=consumed,
                gates_enabled=switch,
                skip_min_delta=ns.skip_formal_min_delta,
                bypass_min_delta=ns.bypass_formal_time_budget_min_delta,
                order=order,
            )

        # --- switch ON (what this fix delivers) --------------------------
        ref_on, skip_thr, bypass_thr, source_on = resolve(ns.enable_chain_incumbent_formal_gates)
        assert source_on == "restored_valid_formal_incumbent"
        assert ref_on == incumbent
        # Hardcoded, not recomputed from the deltas under test.
        assert skip_thr == 3.0, "5.0 loosened by -2.0"
        assert bypass_thr == 5.5, "5.0 tightened by +0.5"

        # Three winners straddling both thresholds — both gates DECIDE.
        def gates(score, thr_skip, thr_bypass):
            winner = {"denoising_score": score}
            return (
                _should_skip_formal(
                    winner,
                    threshold=thr_skip,
                    gates_enabled=ns.enable_chain_incumbent_formal_gates,
                    order=order,
                ),
                _should_bypass_formal_time_budget(winner, threshold=thr_bypass, order=order),
            )

        assert gates(2.0, skip_thr, bypass_thr) == (True, False), "SKIP must fire at 2.0"
        assert gates(4.0, skip_thr, bypass_thr) == (False, False), "neither at 4.0"
        assert gates(6.0, skip_thr, bypass_thr) == (False, True), "BYPASS must fire at 6.0"

        # --- switch OFF (the shipped state before this fix) --------------
        ref_off, skip_off, bypass_off, source_off = resolve(False)
        assert source_off == "gates_disabled"
        assert (ref_off, skip_off, bypass_off) == (None, None, None)
        for score in (2.0, 4.0, 6.0):
            winner = {"denoising_score": score}
            assert (
                _should_skip_formal(winner, threshold=skip_off, gates_enabled=False, order=order)
                is False
            )
            assert (
                _should_bypass_formal_time_budget(winner, threshold=bypass_off, order=order)
                is False
            ), "the bypass gate is inert ONLY via the None threshold"

    def test_the_production_call_site_still_nulls_the_reference_on_the_switch(self):
        """Reachability guard for the mirror above.

        The behavioural witness reproduces two lines of
        ``ml_hyperparameter_tune_agent.py``. If production stops nulling the
        reference on this switch, the mirror would keep testing a condition
        nothing evaluates — the exact "test captures what production
        recomputes" failure. This pins the call site instead.
        """
        src = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
        ).read_text()
        assert "_consumed_reference = (" in src
        assert "if agent_input.enable_chain_incumbent_formal_gates" in src
        assert "gates_enabled=agent_input.enable_chain_incumbent_formal_gates" in src

    def test_the_switch_is_a_reserved_passthrough(self, campaign_root):
        """Gate activation is a frozen campaign policy, typed once at this
        boundary — not something an invocation may re-decide."""
        proc = _stage1_dry(campaign_root, GATE_SWITCH)
        assert proc.returncode != 0
        assert GATE_SWITCH in proc.stderr


def _chain_flags(band_argv: list[str]) -> list[str]:
    """The run_chain.sh flags of a dry-run band line.

    The printed line is ``CUDA_VISIBLE_DEVICES=N bash .../run_chain.sh
    <flags...>``, so the prefix is dropped by locating the script token —
    the same shape ``campaign_arm_symmetry.extract_child_argv`` uses.
    """
    for i, token in enumerate(band_argv):
        if token.endswith("run_chain.sh"):
            return band_argv[i + 1 :]
    raise AssertionError(f"no run_chain.sh token in {band_argv[:4]}")


class TestAnAgreeingDefaultIsNotABinding:
    """F-LAUNCH-1 (seventh of the twelve) + adversarial F-2 — the six FROZEN
    ``EXPERIMENT_FIXED`` workflow budgets that rode ``_chain_common.sh``
    defaults.

    Why this class exists and why it is not just another row in
    ``CANONICAL_NINETEEN``: the chain defaults EQUAL the frozen values
    (``MAX_ROUNDS=3``, ``ATTEMPTS_PER_ROUND=3``, …), so the decision row's
    own recorded effective value reads ``3 — matches frozen`` and EVERY
    check of an effective value comes back correct. The gap was invisible
    to verification, which is exactly why F-LAUNCH-1 demanded TYPING rather
    than a value check. These tests therefore assert the SOURCE of the
    value, not the value.
    """

    def test_every_band_argv_types_all_six_budgets(self, campaign_root):
        """The typing itself. Fails by naming whichever budget went back to
        riding a default."""
        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        argvs = _band_argvs(proc.stdout)
        assert sorted(argvs) == sorted(EXPECTED_GPU_MAP), proc.stdout
        for band, argv in argvs.items():
            pairs = _pairs(argv)
            for flag, value in BUDGETS_BOUND_BY_F_LAUNCH_1.items():
                assert pairs.get(flag) == value, (
                    f"band {band}: {flag} is not typed at the campaign boundary "
                    f"(got {pairs.get(flag)!r}) — it rides a _chain_common.sh default"
                )

    def test_a_changed_chain_default_cannot_move_the_campaigns_values(
        self, tmp_path, campaign_root
    ):
        """THE defect, driven end to end through both production layers.

        Stage 1: the real entrypoint builds a band's run_chain argv.
        Stage 2: that argv is parsed by a COPY of ``_chain_common.sh`` whose
        defaults have been edited to 99 — someone changing a default in a
        file that knows nothing about this campaign.

        The resolved child argv must still carry the frozen values. Before
        the six rows were typed it carried 99, and nothing on any surface
        said so: ``gold_print_frozen_table`` prints only the table, and the
        launch manifest records only what the entrypoint bound.
        """
        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        flags = _chain_flags(_band_argvs(proc.stdout)["0-3"])

        mutated = tmp_path / "_chain_common.sh"
        text = CHAIN_COMMON.read_text()
        for default, replacement in (
            ("\nMAX_ROUNDS=3 ", "\nMAX_ROUNDS=99 "),
            ("\nATTEMPTS_PER_ROUND=3 ", "\nATTEMPTS_PER_ROUND=99 "),
            ("\nATTEMPTS_PER_FORMAL_ROUND=5 ", "\nATTEMPTS_PER_FORMAL_ROUND=99 "),
            ("\nMAX_FAIL_ROUNDS=3 ", "\nMAX_FAIL_ROUNDS=99 "),
            ("\nMAX_PROPOSAL_ATTEMPTS=3 ", "\nMAX_PROPOSAL_ATTEMPTS=99 "),
            ("\nMAX_IMPL_ATTEMPTS=3 ", "\nMAX_IMPL_ATTEMPTS=99 "),
        ):
            assert text.count(default) == 1, f"default spelling changed: {default!r}"
            text = text.replace(default, replacement)
        mutated.write_text(text)

        quoted = " ".join(shlex.quote(f) for f in flags)
        built = _bash(
            "-c",
            f"source '{mutated}'\nparse_chain_args {quoted}\n"
            'build_app_args 1\nprintf "%s\\n" "${APP_ARGS[@]}"\n',
        )
        assert built.returncode == 0, built.stderr
        child = _pairs(built.stdout.split("\n"))
        for flag, value in BUDGETS_BOUND_BY_F_LAUNCH_1.items():
            assert child.get(flag) == value, (
                f"{flag} resolved to {child.get(flag)!r} from the edited chain "
                "default — the campaign value is not bound, it merely agreed"
            )

    def test_the_same_probe_shows_99_when_the_rows_are_removed(self, tmp_path, campaign_root):
        """Discrimination for the test above: with the six rows dropped from
        a COPY of the table — the pre-fix state — the very same edited
        default DOES reach the child argv. Without this, a probe that
        silently stopped exercising the mutated default would still be
        green."""
        tree = tmp_path / "sdsc_submission_scripts"
        tree.mkdir()
        # A faithful synthetic checkout: the band script sources the lib,
        # the lib's capability probe greps _chain_common.sh and
        # run_one_iteration.py, and the boundary binds --llm_config from
        # GOLD_PROJECT_DIR. A tree missing any of them refuses the launch
        # for the wrong reason.
        for src in (STAGE1_BAND, CHAIN_COMMON, RUN_CHAIN, SDSC / "run_one_iteration.py"):
            shutil.copy2(src, tree / src.name)
        _install_frozen_llm_config(tmp_path)
        lib_text = LIB.read_text()
        for key, value in (
            ("max_rounds", "3"),
            ("attempts_per_round", "3"),
            ("attempts_per_formal_round", "5"),
            ("max_fail_rounds", "3"),
            ("max_proposal_attempts", "3"),
            ("max_impl_attempts", "3"),
        ):
            row = f'    "{key}={value}"\n'
            assert lib_text.count(row) == 1, row
            lib_text = lib_text.replace(row, "")
        # The builder loop must stop asking for them too, or the dry-run
        # fails NAMING the key instead of reproducing the pre-fix argv.
        loop = (
            "        max_rounds attempts_per_round attempts_per_formal_round \\\n"
            "        max_fail_rounds max_proposal_attempts max_impl_attempts; do"
        )
        assert lib_text.count(loop) == 1
        lib_text = lib_text.replace(loop, "        ; do")
        (tree / LIB.name).write_text(lib_text)

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
        flags = _chain_flags(_band_argvs(proc.stdout)["0-3"])
        assert "--max_rounds" not in flags, "the pre-fix table must type nothing here"

        mutated = tmp_path / "_chain_common_pre_fix.sh"
        text = CHAIN_COMMON.read_text().replace("\nMAX_ROUNDS=3 ", "\nMAX_ROUNDS=99 ")
        mutated.write_text(text)
        quoted = " ".join(shlex.quote(f) for f in flags)
        built = _bash(
            "-c",
            f"source '{mutated}'\nparse_chain_args {quoted}\n"
            'build_app_args 1\nprintf "%s\\n" "${APP_ARGS[@]}"\n',
        )
        assert built.returncode == 0, built.stderr
        assert _pairs(built.stdout.split("\n")).get("--max_rounds") == "99"

    @pytest.mark.parametrize("flag", sorted(BUDGETS_BOUND_BY_F_LAUNCH_1))
    def test_each_budget_is_refused_as_passthrough(self, flag):
        """Typing alone is not a binding either: parse_chain_args is
        last-wins and passthrough tokens are appended AFTER the frozen args,
        so an unreserved flag would override the value the frozen table just
        printed. Fails by name for whichever budget lost its reservation."""
        proc = _bash(
            "-c",
            f"source '{LIB}'; gold_refuse_reserved_passthrough {flag} && echo ALLOWED",
        )
        assert proc.returncode != 0, f"{flag} is accepted as passthrough"
        assert "ALLOWED" not in proc.stdout
        assert flag in proc.stderr

    def test_the_frozen_table_prints_all_six(self, campaign_root):
        """The operator-facing surface. A value bound but not printed is a
        launch decision nobody can read off the dry-run."""
        proc = _stage1_dry(campaign_root)
        assert proc.returncode == 0, proc.stderr
        for flag, value in BUDGETS_BOUND_BY_F_LAUNCH_1.items():
            assert f"frozen {flag.lstrip('-')}={value}" in proc.stdout, flag


PROBE_PROFILE_KEY = "nvidia_h100_80gb_hbm3/single"
PROBE_PROFILE_SHA = "b" * 64


def _stage1_direct(campaign_root: dict, *extra: str) -> subprocess.CompletedProcess:
    """``stage1_search.sh`` invoked DIRECTLY, bypassing the entrypoint.

    Every other dry-run helper in this module goes through
    ``run_gold_campaign.sh``. That is the whole reason N-7 survived: the
    entrypoint refuses a half declaration at :193/:196, so the existing
    half-supply family never reached the stage script's own fan-out.
    """
    return _bash(
        str(STAGE1),
        "--workspace_root",
        str(campaign_root["root"]),
        "--gold_advice_file",
        str(campaign_root["advice"]),
        "--only",
        "0-3",
        "--dry-run",
        *extra,
    )


class TestBothOrNeitherIsReachableOnTheDirectStagePath:
    """N-7 — the group refusals must hold where the fan-out happens.

    ``stage1_search.sh``'s header promises that a direct invocation cannot
    fork a value away from the entrypoint's. It could. The script keyed each
    both-or-neither group's forwarding on ONE member — the TRIAL variable for
    the VRAM pair, the profile KEY for the artifact/key/sha triple — and
    never called the lib builders that own the refusal. So a supply that left
    the keyed member empty forwarded nothing at all, and the band's
    ``gold_frozen_chain_args`` saw a group that was not half-supplied but
    ABSENT.

    Observed at the pre-fix head, ``stage1_search.sh --dry-run``:

        both                 -> rc=0, both chain tokens forwarded
        trial-only           -> rc=1 REFUSED
        formal-only          -> rc=0, chain tokens [], row reads
                                "vram_budget=(none - no operator ceiling)"
        full profile triple  -> rc=0, forwarded
        key-only             -> rc=1 REFUSED
        path-only, sha-only  -> rc=0, no token, row reads "(none)"

    The consequence is not a crash: a mistyped trial half gives four
    co-resident bands running formal rounds with NO VRAM cap, exit 0, no
    error — the exact exhaustion D-HW-6's both-or-neither rule exists to
    prevent. The profile half is the same shape with a worse story: the
    operator supplies an artifact and a certified digest, mistypes the key,
    and the campaign runs on the legacy measured>shipped>uncalibrated ladder
    believing a profile was pinned.

    These tests are NOT redundant with ``TestHistoricalStage2AndGenericVramTransport``'s
    half-supply family: that family calls ``_stage1_dry``, i.e. the
    ENTRYPOINT, where ``gold_vram_budget_args`` has already run. It asserts
    the refusal exists; this asserts it is reachable where the bands fork.
    """

    @pytest.mark.parametrize(
        ("extra", "expected"),
        [
            ((("--gold_trial_vram_budget_gb", PROBE_TRIAL_VRAM),), "INCOMPLETE VRAM"),
            ((("--gold_formal_vram_budget_gb", PROBE_FORMAL_VRAM),), "INCOMPLETE VRAM"),
            (
                (("--gold_required_runtime_profile_path", "/tmp/profile.json"),),
                "INCOMPLETE required runtime-profile",
            ),
            (
                (("--gold_required_runtime_profile", PROBE_PROFILE_KEY),),
                "INCOMPLETE required runtime-profile",
            ),
            (
                (("--gold_required_runtime_profile_sha256", PROBE_PROFILE_SHA),),
                "INCOMPLETE required runtime-profile",
            ),
        ],
    )
    def test_a_half_supply_refuses_before_any_band_forks(self, campaign_root, extra, expected):
        """Fails as: a ZERO exit from a half supply on the direct path.

        Parametrized over BOTH groups and over EVERY member of each, because
        the defect is per-member: the one member the forwarding keyed on did
        refuse, and it is the members that did not which produced a silent
        drop. A fix that repaired only the keyed member would still pass a
        single-case test.
        """
        proc = _stage1_direct(campaign_root, *[tok for pair in extra for tok in pair])

        assert proc.returncode != 0, (
            "a half declaration was ACCEPTED by the direct stage path:\n" + proc.stdout
        )
        assert expected in proc.stderr, proc.stderr
        assert "run_chain argv" not in proc.stdout, "a band was walked after a refused group"

    def test_a_complete_supply_still_reaches_every_band(self, campaign_root):
        """The other half — the refusal must not have become a blanket one.

        Fails as: a complete supply refused, or forwarded to the band without
        both members, which is the declared-but-unconsumed shape D-HW-6 and
        F-PROFILE-WIRE-1 were each written to close.
        """
        proc = _stage1_direct(
            campaign_root,
            "--gold_trial_vram_budget_gb",
            PROBE_TRIAL_VRAM,
            "--gold_formal_vram_budget_gb",
            PROBE_FORMAL_VRAM,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout

        argvs = _band_argvs(proc.stdout)
        assert argvs, proc.stdout
        for band, argv in argvs.items():
            pairs = _pairs(argv)
            assert pairs["--trial_vram_budget_gb"] == PROBE_TRIAL_VRAM, band
            assert pairs["--formal_vram_budget_gb"] == PROBE_FORMAL_VRAM, band

    def test_an_unsupplied_group_still_forwards_nothing(self, campaign_root):
        """ABSENT == UNSUPPLIED must stay byte-identical to the pre-seam argv.

        Fails as: the repair turning "no operator ceiling" into a refusal, or
        into an emitted token. Both D-HW-6 and F-PROFILE-WIRE-1 state
        explicitly that omission is NOT an error — the campaign has
        deliberately not frozen these values.
        """
        proc = _stage1_direct(campaign_root)
        assert proc.returncode == 0, proc.stderr + proc.stdout

        argvs = _band_argvs(proc.stdout)
        assert argvs, proc.stdout
        for band, argv in argvs.items():
            for flag in (
                "--trial_vram_budget_gb",
                "--formal_vram_budget_gb",
                "--required_runtime_profile",
                "--required_runtime_profile_path",
                "--required_runtime_profile_sha256",
            ):
                assert flag not in argv, (band, flag)
