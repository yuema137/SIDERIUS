"""FU-B-16: no launch argument may disappear between layers.

`submit_one_iteration.slurm` used to parse ~14 application flags into
shell variables, rebuild the command line from them, and end its case
block with `*) shift ;;`. Everything it did not name -- 35 flags,
including `--data_scope`, every runtime-control flag and both VRAM
budgets -- was silently discarded. A run configured on the command line
therefore executed with *different settings* on SDSC than on lilab, and
nothing in the log said so.

The ownership rule these tests enforce:

    owned by this layer  -> consume
    owned downstream     -> forward unchanged
    unknown at Python    -> rejected, loudly

A shell wrapper must not need to know the application CLI. It owns
scheduler concerns; `run_one_iteration.py` is the single authoritative
validator.

Every test drives the **real** parse and default-fill blocks sliced out
of the shipped script, so a regression in the script fails here rather
than on a cluster.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
SLURM = SDSC / "submit_one_iteration.slurm"
CHAIN_COMMON = SDSC / "_chain_common.sh"
RUNNER = SDSC / "run_one_iteration.py"

#: Required by the wrapper's own validation; supplied so a test exercises
#: the token under study rather than tripping over an unrelated check.
BASE = ["--workspace", "/tmp/ws", "--iteration", "3", "--source_paths", "/tmp/seed.json"]


def _slice(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def forward(argv: list[str]) -> list[str]:
    """Run the wrapper's real argument handling and return final argv.

    Slices the shipped parse loop and default-fill block rather than
    restating them, so this cannot drift from the script it validates.
    """
    src = SLURM.read_text()
    parse = _slice(src, "# --- Argument parsing ---", 'if [ -z "$WORKSPACE" ]')
    build = _slice(src, "# --- Fill in defaults", "# --- Execute the runner ---")
    script = (
        "set -u\n"
        'WORKSPACE=""\nITERATION=""\nSOURCE_PATHS=()\n'
        "MAX_ROUNDS=20\nMAX_PROPOSAL_ATTEMPTS=3\nLLM_MODEL=default-model\n"
        "TRIAL_PORTION=0.1\nTRAIN_PORTION=0.1\nEVAL_PORTION=0.1\n"
        + parse
        + build
        + '\necho "__WORKSPACE__=${WORKSPACE}"\n'
        + 'printf "%s\\n" "${RUNNER_ARGS[@]}"\n'
    )
    out = subprocess.run(
        ["bash", "-c", script, "bash", *argv],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    return [ln for ln in lines if not ln.startswith("__WORKSPACE__=")]


def peeked_workspace(argv: list[str]) -> str:
    """What the wrapper recorded for its banner/manifest check."""
    src = SLURM.read_text()
    parse = _slice(src, "# --- Argument parsing ---", 'if [ -z "$WORKSPACE" ]')
    script = (
        'set -u\nWORKSPACE=""\nITERATION=""\nSOURCE_PATHS=()\n' + parse + '\necho "$WORKSPACE"\n'
    )
    out = subprocess.run(
        ["bash", "-c", script, "bash", *argv],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def runner_options() -> set[str]:
    spec = importlib.util.spec_from_file_location("_roi_fwd", RUNNER)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:  # pragma: no cover
        pass
    return {s for a in module.build_parser()._actions for s in a.option_strings}


def chain_forwarded_flags() -> set[str]:
    """Flags `build_app_args` puts on the wire."""
    import re

    src = CHAIN_COMMON.read_text()
    blocks = re.findall(r"APP_ARGS\+=\(([^)]*)\)", src)
    return {m for b in blocks for m in re.findall(r"--[a-z_0-9-]+", b)}


class TestNothingIsDroppedSilently:
    def test_the_silent_drop_branch_is_gone(self):
        src = SLURM.read_text()
        assert "# ignore unknown flags" not in src
        assert "dropping unrecognised flag" not in src, "warn-and-drop is still a drop"

    def test_every_chain_forwarded_flag_survives(self):
        """The census, enforced. Each flag `build_app_args` can emit must
        come out the other side of the wrapper."""
        missing = []
        for flag in sorted(chain_forwarded_flags()):
            out = forward([*BASE, flag, "X"])
            if flag not in out:
                missing.append(flag)
        assert missing == [], f"dropped by the SDSC wrapper: {missing}"

    def test_the_previously_dropped_flags_now_arrive(self):
        """Spot-check the ones the old parser named nowhere."""
        for flag, value in [
            ("--data_scope", "4-9"),
            ("--runtime_watchdog_floor_seconds", "30"),
            ("--trial_vram_budget_gb", "12.0"),
            ("--max_steps_per_attempt", "1000"),
            ("--gpu_pair_ceiling_gib", "6.0"),
        ]:
            out = forward([*BASE, flag, value])
            assert flag in out
            assert out[out.index(flag) + 1] == value

    def test_an_unknown_flag_is_forwarded_not_swallowed(self):
        """It must reach the typed parser, which is what rejects it. The
        wrapper deciding would mean two validators."""
        out = forward([*BASE, "--totally_unknown_flag", "x"])
        assert "--totally_unknown_flag" in out
        assert "x" in out


class TestExactArgvPreservation:
    def test_a_flag_with_a_value(self):
        out = forward([*BASE, "--llm_model", "gpt-5.5"])
        assert out[out.index("--llm_model") + 1] == "gpt-5.5"

    def test_a_boolean_flag_gains_no_value(self):
        out = forward([*BASE, "--debug_dump_prompts"])
        i = out.index("--debug_dump_prompts")
        assert i == len(out) - 1 or out[i + 1].startswith("--")

    def test_equals_form_survives_intact(self):
        out = forward([*BASE, "--data_scope=4-9"])
        assert "--data_scope=4-9" in out

    def test_a_negative_number_is_not_read_as_a_flag(self):
        out = forward([*BASE, "--degenerate_penalty_score", "-5"])
        assert out[out.index("--degenerate_penalty_score") + 1] == "-5"

    def test_a_path_with_spaces_stays_one_token(self):
        out = forward([*BASE, "--data_dir", "/a b/c d"])
        assert "/a b/c d" in out

    def test_a_quoted_value_stays_one_token(self):
        out = forward([*BASE, "--advice", "try a wider net, then stop"])
        assert "try a wider net, then stop" in out

    def test_a_repeated_flag_is_not_collapsed(self):
        out = forward([*BASE, "--seed_paths", "a.json", "--seed_paths", "b.json"])
        assert out.count("--seed_paths") == 2

    def test_token_order_is_preserved(self):
        out = forward([*BASE, "--max_epochs", "1", "--train_portion", "0.5"])
        assert out.index("--max_epochs") < out.index("--train_portion")

    def test_the_double_dash_separator_forwards_verbatim(self):
        out = forward([*BASE, "--", "--anything", "--goes=here"])
        assert "--anything" in out
        assert "--goes=here" in out
        assert "--" not in out

    def test_after_the_separator_even_an_owned_flag_is_not_interpreted(self):
        """The one thing only `--` provides. Without it, these tokens
        would still be forwarded by the catch-all, so a test using an
        unowned flag cannot tell the separator is working at all."""
        argv = [*BASE, "--", "--workspace", "/should/not/be/peeked"]
        assert peeked_workspace(argv) == "/tmp/ws"
        out = forward(argv)
        assert out.count("--workspace") == 2
        assert "/should/not/be/peeked" in out


class TestPeekedArgumentsAreStillForwarded:
    """`--workspace`, `--iteration` and `--source_paths` are needed by
    the wrapper's banner and manifest check. Recording a value must not
    consume the token — that is the same defect in miniature."""

    def test_workspace_is_forwarded(self):
        assert "--workspace" in forward(BASE)

    def test_iteration_is_forwarded(self):
        out = forward(BASE)
        assert "--iteration" in out
        assert out[out.index("--iteration") + 1] == "3"

    def test_source_paths_are_all_forwarded(self):
        out = forward(
            ["--workspace", "/tmp/ws", "--iteration", "1", "--source_paths", "a.json", "b.json"]
        )
        assert "--source_paths" in out
        assert "a.json" in out and "b.json" in out


class TestDefaultsOnlyFillGaps:
    def test_a_default_is_supplied_when_absent(self):
        assert "--max_rounds" in forward(BASE)

    def test_a_caller_value_is_not_duplicated_or_overridden(self):
        out = forward([*BASE, "--max_rounds", "7"])
        assert out.count("--max_rounds") == 1
        assert out[out.index("--max_rounds") + 1] == "7"

    def test_trial_is_defaulted_in_when_unspecified(self):
        assert "--is_trial" in forward(BASE)

    def test_an_explicit_formal_request_is_not_overridden(self):
        """`--no-is_trial` must survive, or making the flag able to
        express false would have bought nothing on SDSC."""
        out = forward([*BASE, "--no-is_trial"])
        assert "--no-is_trial" in out
        assert "--is_trial" not in out

    def test_equals_form_also_suppresses_the_default(self):
        out = forward([*BASE, "--max_rounds=9"])
        assert "--max_rounds=9" in out
        assert out.count("--max_rounds") == 0


class TestPythonIsTheSingleValidator:
    def test_the_runner_parser_is_strict(self):
        """`parse_known_args` would put the silent drop back one layer
        further down."""
        src = RUNNER.read_text()
        assert "parse_known_args" not in src
        assert "parse_args()" in src

    def test_an_unknown_flag_fails_the_runner_loudly(self):
        out = subprocess.run(
            [
                str(REPO_ROOT / ".venv" / "bin" / "python"),
                str(RUNNER),
                "--workspace",
                "/tmp/ws",
                "--run_name",
                "r",
                "--totally_unknown_flag",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=REPO_ROOT,
        )
        assert out.returncode != 0
        assert "totally_unknown_flag" in (out.stderr + out.stdout)

    def test_every_flag_the_chain_forwards_is_known_to_python(self):
        """Parity: lossless forwarding is only safe if the far end
        recognises what arrives."""
        unknown = sorted(chain_forwarded_flags() - runner_options())
        assert unknown == [], f"forwarded but unknown to run_one_iteration: {unknown}"


class TestLilabSdscParity:
    @pytest.mark.parametrize(
        "flag,value",
        [
            ("--data_scope", "4-9"),
            ("--gpu_pair_ceiling_gib", "6.0"),
            ("--gpu_admission_measurement_source", "registry://none"),
            ("--max_steps_per_attempt", "1000"),
        ],
    )
    def test_an_application_setting_resolves_identically_on_both_paths(self, flag, value):
        """lilab runs `run_one_iteration.py` directly, SDSC goes through
        the wrapper. For an application-owned setting the two must reach
        the same parsed value."""
        parser_opts = runner_options()
        assert flag in parser_opts

        spec = importlib.util.spec_from_file_location("_roi_par", RUNNER)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit:  # pragma: no cover
            pass
        required = ["--workspace", "/tmp/ws", "--run_name", "r"]
        dest = flag.lstrip("-")

        lilab = module.build_parser().parse_args([*required, flag, value])
        sdsc_argv = forward([*BASE, flag, value])
        assert flag in sdsc_argv
        assert sdsc_argv[sdsc_argv.index(flag) + 1] == value
        sdsc = module.build_parser().parse_args([*required, flag, value])
        assert getattr(lilab, dest) == getattr(sdsc, dest)
