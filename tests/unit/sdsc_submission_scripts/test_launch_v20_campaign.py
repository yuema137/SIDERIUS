"""The V20 production launcher must actually emit the frozen posture.

Audit findings M1/M2/M4 were all the same shape: a posture that existed
only in an operator's command line, so dropping a flag was invisible.
Moving it into `launch_v20_campaign.sh` only helps if something fails
when a line is deleted from that script — which is what these tests are.

They drive the REAL launcher with `--dry-run` and read the argv it would
hand `run_one_iteration.py`. A static grep of the script would pass on a
flag that `_chain_common.sh` silently declines to forward; only the
resolved argv proves delivery.

Portability: the repository root is derived from this file's location, so
the tests read the checkout they are executed in.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "sdsc_submission_scripts" / "launch_v20_campaign.sh"


def _argv_contains(argv: str, expected: str) -> bool:
    """Exact-token containment, never substring.

    `"--runtime_watchdog" in argv` is True when only
    `--runtime_watchdog_safety_factor` is present — so deleting the bare
    watchdog flag passed the first version of this test. Tokenising is
    what makes the mutation proof meaningful.
    """
    tokens = argv.split()
    wanted = expected.split()
    return any(tokens[i : i + len(wanted)] == wanted for i in range(len(tokens)))


def _dry_run_raw(workspace, run_name, band, chain_type, iterations="1"):
    return subprocess.run(
        [
            "bash",
            str(LAUNCHER),
            "--workspace",
            str(workspace),
            "--run_name",
            run_name,
            "--num_iterations",
            iterations,
            "--data_scope",
            band,
            "--chain_type",
            chain_type,
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _dry_run(workspace, run_name: str, band: str, chain_type: str):
    """Drive the real launcher for one banded job."""
    return subprocess.run(
        [
            "bash",
            str(LAUNCHER),
            "--workspace",
            str(workspace),
            "--run_name",
            run_name,
            "--num_iterations",
            "1",
            "--data_scope",
            band,
            "--chain_type",
            chain_type,
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def runner_argv(tmp_path_factory) -> str:
    """The argv the launcher would hand the runner, as one string."""
    workspace = tmp_path_factory.mktemp("v20_launcher") / "ws"
    proc = _dry_run(workspace, "posture_probe", "15-19", "loss")
    assert proc.returncode == 0, f"launcher dry-run failed:\n{proc.stdout}\n{proc.stderr}"
    marker = "run_one_iteration.py"
    lines = [line for line in proc.stdout.splitlines() if marker in line]
    assert lines, f"no runner invocation in dry-run output:\n{proc.stdout}"
    assert not workspace.exists(), "a dry run must not create the workspace"
    # The dry run renders the command with printf %q, which escapes commas
    # and the like. shlex un-quotes it back to the argv the runner would
    # really receive — asserting against the rendering instead would test
    # the printer, not the launcher.
    return " ".join(shlex.split(lines[-1]))


class TestTheFrozenPostureIsDelivered:
    """Mandate Part II §10, flag by flag, as the runner would see it."""

    @pytest.mark.parametrize(
        "expected",
        [
            # §10.1 LLM — the M4 defect was falling through to Gemini
            "--llm_config llm_configs/openai_tiered_pro.json",
            # operator ruling: best ability + advice + sequenced files
            "--exploration_mode explore",
            "--human_advice_file advice/workflow/v20_loss_explorer.json",
            "--order_strategy_override sequential",
            "--ml_lit_review_enabled",
            "--enable_structured_health_feedback",
            # §10.2 scientific policy
            "--healthgate_mode blocking",
            "--result_authority scientific",
            "--enable_chain_incumbent_formal_gates",
            "--skip_formal_min_delta -1.0",
            "--bypass_formal_time_budget_min_delta 0.5",
            # §10.3 runtime safety — the whole of M1
            "--trial_time_budget_minutes 20",
            "--formal_time_budget_minutes 120",
            "--runtime_watchdog",
            "--runtime_safety_factor 1.5",
            "--runtime_trial_safety_factor 3.0",
            "--runtime_formal_safety_factor 2.25",
            "--runtime_watchdog_safety_factor 3.5",
            "--runtime_watchdog_floor_seconds 120",
            "--trial_vram_budget_gb 12",
            "--formal_vram_budget_gb 12",
            # §10.4 workload
            "--max_rounds 3",
            "--max_epochs 1",
            "--trial_portion 0.1",
            "--train_portion 0.1",
            "--eval_portion 0.1",
            "--formal_portion 0.1",
            "--formal_train_portion 1.0",
            "--formal_eval_portion 1.0",
            "--formal_round_strategy full_clone",
            # M5 production admission posture
            "--gpu_admission_enforcement enforce_resource_limits",
        ],
    )
    def test_flag_reaches_the_runner(self, runner_argv, expected):
        assert _argv_contains(runner_argv, expected), (
            f"{expected!r} is missing from the runner argv — the frozen V20 "
            f"posture is not being delivered"
        )


class TestTheBandIsProductionConfiguration:
    """`--data_scope` selecting the authoritative band is SCIENCE, not leakage.

    An earlier reading listed `--data_scope` as a validation-only posture
    and froze V20 as a single full-scope campaign. That was wrong: V20 is
    banded, and the scope IS the experiment's definition. What must stay
    absent is a VALIDATION-specific scope override, which this launcher
    still cannot emit.
    """

    def test_the_job_carries_its_own_band(self, runner_argv):
        assert _argv_contains(runner_argv, "--data_scope 15-19")

    def test_healthgate_watches_exactly_the_band_it_trains_on(self, runner_argv):
        # A gate monitoring files the chain never trains on is judging a
        # different experiment.
        assert _argv_contains(runner_argv, "--health_gate_files 15,16,17,18,19")

    def test_no_file_order_override_so_the_band_is_visited_ascending(self, runner_argv):
        # With `sequential` and no override, the chain visits the resolved
        # scope in ascending order — that IS the band's sequence. An
        # override here would silently reorder the science.
        assert not _argv_contains(runner_argv, "--file_order_override")


class TestNoValidationPostureCanLeak:
    """§10.5. These must be unreachable, not merely unset."""

    @pytest.mark.parametrize(
        "forbidden",
        [
            "--is_pseudo_llm",
            "--is_pseudo_training",
            "--validation_fixed_candidate_plan",
            "--validation_max_portion",
            "--debug_dump_prompts",
        ],
    )
    def test_absent_from_the_runner_argv(self, runner_argv, forbidden):
        assert not _argv_contains(runner_argv, forbidden)

    @pytest.mark.parametrize(
        "forbidden",
        [
            "--is_pseudo_llm",
            "--is_pseudo_training",
            "--validation_fixed_candidate_plan",
            "--validation_max_portion",
        ],
    )
    def test_the_launcher_cannot_even_emit_it(self, forbidden):
        # Unset-by-default is one edit away from set. Absent-from-the-CODE
        # is the property that survives a careless change.
        #
        # Comments are stripped first: the script explains in prose which
        # flags it deliberately cannot emit, and a naive substring scan
        # matches that prose and "passes" for the wrong reason. (It did,
        # on the first version of this test.)
        code = "\n".join(
            line for line in LAUNCHER.read_text().splitlines() if not line.lstrip().startswith("#")
        )
        assert forbidden not in code


class TestTheOperatorSurface:
    def test_a_non_positive_iteration_count_is_refused(self, tmp_path):
        proc = _dry_run_raw(tmp_path / "ws", "bad", "15-19", "loss", iterations="0")
        assert proc.returncode != 0
        assert "positive integer" in proc.stderr

    def test_a_missing_band_is_refused(self, tmp_path):
        # A banded job with no scope would silently run the FULL dataset —
        # a different experiment wearing this job's run name.
        proc = subprocess.run(
            [
                "bash",
                str(LAUNCHER),
                "--workspace",
                str(tmp_path / "ws"),
                "--run_name",
                "nobands",
                "--num_iterations",
                "1",
                "--chain_type",
                "loss",
                "--dry-run",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode != 0
        assert "--data_scope" in proc.stderr

    def test_an_unknown_band_is_refused(self, tmp_path):
        proc = _dry_run_raw(tmp_path / "ws", "badband", "7-9", "loss")
        assert proc.returncode != 0
        assert "unknown band" in proc.stderr

    def test_an_unknown_chain_type_is_refused(self, tmp_path):
        # "arc" is the operator shorthand; the real flavour is "arch", and
        # accepting the typo would silently pick the wrong explorer advice.
        proc = _dry_run_raw(tmp_path / "ws", "badtype", "15-19", "arc")
        assert proc.returncode != 0
        assert "--chain_type" in proc.stderr

    def test_an_unknown_flag_is_refused(self, tmp_path):
        proc = subprocess.run(
            [
                "bash",
                str(LAUNCHER),
                "--workspace",
                str(tmp_path / "ws"),
                "--run_name",
                "bad",
                "--num_iterations",
                "1",
                "--data_scope",
                "15-19",
                "--chain_type",
                "loss",
                "--is_pseudo_training",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode != 0
        assert "Unknown arg" in proc.stderr

    def test_the_logfile_is_derived_from_the_workspace(self, runner_argv):
        # M2: monitoring documentation pointed at a file nothing created.
        # The launcher's own banner must name the file it will write.
        assert re.search(r"--workspace \S+", runner_argv)


class TestTheFrozenInputsExist:
    def test_the_production_llm_config_is_present(self):
        assert (REPO_ROOT / "llm_configs" / "openai_tiered_pro.json").is_file()

    def test_the_v20_advice_file_is_present(self):
        assert (REPO_ROOT / "advice" / "workflow" / "v20_arch_explorer.json").is_file()

    def test_the_advice_does_not_claim_healthgate_is_observe_only(self):
        # It was derived from the V18r explorer, whose HealthGate
        # statements are false under a blocking campaign. Telling the
        # proposer that collapse has no consequence is worse than no advice.
        text = (REPO_ROOT / "advice" / "workflow" / "v20_arch_explorer.json").read_text()
        assert "observe-only in V18r" not in text
        assert "HealthGate is BLOCKING in V20" in text


BAND_FILES = {
    "15-19": "15,16,17,18,19",
    "10-14": "10,11,12,13,14",
    "4-9": "4,5,6,7,8,9",
    "0-3": "0,1,2,3",
}


@pytest.fixture(scope="module")
def eight_job_argv(tmp_path_factory):
    """The resolved runner argv for each of the eight V20 chains."""
    from core.campaign.slot_scheduler import v20_campaign_jobs

    root = tmp_path_factory.mktemp("v20_matrix")
    out = {}
    for job in v20_campaign_jobs():
        proc = _dry_run(root / job.run_name, job.run_name, job.band, job.chain_type)
        assert proc.returncode == 0, f"{job.run_name}: {proc.stderr}"
        line = [ln for ln in proc.stdout.splitlines() if "run_one_iteration.py" in ln][-1]
        out[job.run_name] = " ".join(shlex.split(line))
    return out


class TestTheEightJobsAreEachCorrectlyScoped:
    """Per-job inputs differ; scientific policy does not."""

    def test_all_eight_resolve(self, eight_job_argv):
        assert len(eight_job_argv) == 8

    @pytest.mark.parametrize(
        ("run_name", "band", "chain_type"),
        [
            ("v20_loss_15_19", "15-19", "loss"),
            ("v20_arch_15_19", "15-19", "arch"),
            ("v20_loss_10_14", "10-14", "loss"),
            ("v20_arch_10_14", "10-14", "arch"),
            ("v20_loss_04_09", "4-9", "loss"),
            ("v20_arch_04_09", "4-9", "arch"),
            ("v20_loss_00_03", "0-3", "loss"),
            ("v20_arch_00_03", "0-3", "arch"),
        ],
    )
    def test_band_gate_files_and_advice_all_agree(self, eight_job_argv, run_name, band, chain_type):
        argv = eight_job_argv[run_name]
        # scope, HealthGate scope and run identity must describe ONE experiment
        assert _argv_contains(argv, f"--data_scope {band}")
        assert _argv_contains(argv, f"--health_gate_files {BAND_FILES[band]}")
        assert _argv_contains(argv, f"--run_name {run_name}")
        assert _argv_contains(
            argv, f"--human_advice_file advice/workflow/v20_{chain_type}_explorer.json"
        )

    def test_no_job_carries_another_bands_scope(self, eight_job_argv):
        # The mutation that matters: 10-14 loss accidentally receiving the
        # 15-19 scope would run a different experiment under this name.
        for run_name, argv in eight_job_argv.items():
            tag = run_name.rsplit("_", 2)[-2] + "_" + run_name.rsplit("_", 1)[-1]
            expected = {"15_19": "15-19", "10_14": "10-14", "04_09": "4-9", "00_03": "0-3"}[tag]
            for band in BAND_FILES:
                present = _argv_contains(argv, f"--data_scope {band}")
                assert present == (band == expected), f"{run_name} scope {band}"

    def test_loss_and_arch_never_swap_advice(self, eight_job_argv):
        for run_name, argv in eight_job_argv.items():
            wrong = "arch" if "_loss_" in run_name else "loss"
            assert not _argv_contains(
                argv, f"--human_advice_file advice/workflow/v20_{wrong}_explorer.json"
            )

    def test_every_job_carries_the_identical_scientific_policy(self, eight_job_argv):
        # Policy has one home. If a job could differ here, the campaign's
        # posture would depend on which chain you inspected.
        frozen = [
            "--llm_config llm_configs/openai_tiered_pro.json",
            "--healthgate_mode blocking",
            "--result_authority scientific",
            "--enable_chain_incumbent_formal_gates",
            "--skip_formal_min_delta -1.0",
            "--bypass_formal_time_budget_min_delta 0.5",
            "--order_strategy_override sequential",
            "--gpu_admission_enforcement enforce_resource_limits",
            "--runtime_watchdog",
            "--trial_time_budget_minutes 20",
            "--formal_time_budget_minutes 120",
            "--trial_vram_budget_gb 12",
            "--formal_vram_budget_gb 12",
            "--max_epochs 1",
        ]
        for run_name, argv in eight_job_argv.items():
            for flag in frozen:
                assert _argv_contains(argv, flag), f"{run_name} missing {flag}"

    def test_no_job_can_carry_a_pseudo_or_validation_posture(self, eight_job_argv):
        for run_name, argv in eight_job_argv.items():
            for forbidden in (
                "--is_pseudo_llm",
                "--is_pseudo_training",
                "--validation_fixed_candidate_plan",
                "--validation_max_portion",
            ):
                assert not _argv_contains(argv, forbidden), f"{run_name} {forbidden}"
