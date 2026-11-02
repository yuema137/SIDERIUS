"""Paper-shaped fixed-workflow argv survives ``run_chain.sh`` end to end.

Defect (v1.1.0 freeze, 2026-11-02): siderius-exp's fixed paper workflows
(LIGO, Project 8 dual representation, TESS, TIDMAD main) render
``--no-disclose_execution_constraints``,
``--runtime_verification_pathological_min_unit_ms 0`` and (TIDMAD main)
``--is_trial`` into a ``run_chain.sh`` launch. ``run_one_iteration.py``
accepts all three, but the chain parser rejected them with ``Unknown arg``
before any iteration started.

The fixtures below mirror the flag shapes of those workflows (values from
siderius-exp e174ed786 ``experiments/*/main_fixed_workflow*/workflow.json``
plus the information-treatment and launcher-owned arguments). They are
generic launcher inputs; no task semantics are read here.

The check is semantic, not textual: the child argv printed by ``--dry-run``
is parsed by the runner's own ``build_parser`` and, for every runner flag the
chain received, the parsed destination must equal what the runner would have
parsed from that flag directly. A flag the chain accepts but drops, or
forwards with the wrong polarity, fails here.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

from workflows.standard_cli import build_parser

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_CHAIN = REPO_ROOT / "scripts" / "launch" / "run_chain.sh"
RUNNER_NAME = "run_one_iteration.py"

_TREATMENT = (
    "--experiment_arm",
    "fixture-no-prior",
    "--no-data_analysis_enabled",
    "--ml_lit_review_enabled",
)
_SHARED = (
    "--no-runtime_watchdog",
    "--max_rounds",
    "2",
    "--plan_overrides",
    '{"is_trial": true}',
    "--max_epochs",
    "100",
    "--trial_max_epochs",
    "100",
    "--formal_max_epochs",
    "100",
    "--formal_eval_portion",
    "1.0",
    "--training_validation_portion",
    "0.1",
    "--training_budget_reserve_fraction",
    "0.2",
    "--no-disclose_execution_constraints",
    "--gpu_admission_enforcement",
    "observe_only",
    "--runtime_verification_pathological_min_unit_ms",
    "0",
    "--run_seed",
    "20260922",
    "--workflow_parameter_rules",
    '{"rules":{"train_config.lr_schedule":{"exact":null}}}',
)
PAPER_POSTURES = {
    "ligo_agent_scope": (
        "--trial_time_budget_minutes",
        "10",
        "--formal_time_budget_minutes",
        "30",
        "--trial_vram_budget_gb",
        "16",
        "--formal_vram_budget_gb",
        "16",
        "--formal_training_scope_source",
        "agent",
    ),
    "project8_dual_operator_scope": (
        "--trial_time_budget_minutes",
        "30",
        "--formal_time_budget_minutes",
        "120",
        "--trial_vram_budget_gb",
        "40",
        "--formal_vram_budget_gb",
        "40",
        "--formal_training_scope_source",
        "operator",
        "--formal_portion",
        "1.0",
        "--formal_train_portion",
        "1.0",
    ),
    "tidmad_main_explicit_is_trial": (
        "--trial_time_budget_minutes",
        "30",
        "--formal_time_budget_minutes",
        "120",
        "--trial_vram_budget_gb",
        "40",
        "--formal_vram_budget_gb",
        "40",
        "--formal_training_scope_source",
        "operator",
        "--formal_portion",
        "0.1",
        "--formal_train_portion",
        "1.0",
        "--is_trial",
    ),
}


def _runner_flags(argv: list[str]) -> list[str]:
    """Runner-recognised flags (with their values) from a chain argv."""
    actions = {s: a for a in build_parser()._actions for s in a.option_strings}
    kept: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        action = actions.get(token)
        width = 0 if action is None or action.nargs == 0 else 1
        if action is not None:
            kept.extend(argv[index : index + 1 + width])
        index += 1 + width
    return kept


def _child_argv(stdout: str) -> list[str]:
    marker = "[DRY-RUN] would exec from"
    assert stdout.count(marker) == 1, stdout
    command = shlex.split(stdout.split(marker, 1)[1].splitlines()[1])
    runner = next(i for i, token in enumerate(command) if token.endswith(RUNNER_NAME))
    return command[runner + 1 :]


@pytest.mark.parametrize("posture", sorted(PAPER_POSTURES))
def test_paper_workflow_flags_reach_the_iteration_with_their_meaning(
    tmp_path: Path, posture: str
) -> None:
    workspace = tmp_path / "workspace"
    chain_argv = [
        "--mode",
        "lilab",
        "--workspace",
        str(workspace),
        "--data_dir",
        str(tmp_path),
        "--run_name",
        "paper-shape",
        "--result_authority",
        "scientific",
        "--ml_lit_review_config",
        str(tmp_path / "literature_review.yaml"),
        *_TREATMENT,
        "--task_composition",
        str(REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"),
        "--num_iterations",
        "1",
        *_SHARED,
        *PAPER_POSTURES[posture],
        "--dry-run",
    ]
    proc = subprocess.run(
        ["bash", str(RUN_CHAIN), *chain_argv],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert not workspace.exists()

    parser = build_parser()
    child = parser.parse_args(_child_argv(proc.stdout))
    requested = _runner_flags(chain_argv)
    direct = parser.parse_args(requested)
    actions = {s: a for a in parser._actions for s in a.option_strings}
    received = [t for t in requested if t in actions]
    assert {
        "--no-disclose_execution_constraints",
        "--runtime_verification_pathological_min_unit_ms",
    } <= set(received)
    for flag in received:
        dest = actions[flag].dest
        assert getattr(child, dest) == getattr(direct, dest), (
            f"{flag}: chain delivered {getattr(child, dest)!r}, "
            f"runner expects {getattr(direct, dest)!r}"
        )
