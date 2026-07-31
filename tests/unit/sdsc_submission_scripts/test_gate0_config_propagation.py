"""Gate 0 frozen configuration — shell→CLI value resolution + CLI→workflow
binding (V19 launch-critical propagation audit, layer 1-2 of the chain

    gate_chain_args → parse_chain_args → build_app_args → argparse
    → normalize_args → run_workflow(call site)

Layer 3 (run_workflow → tuner input, value level) lives in
tests/integration/workflows/test_launch_config_propagation_pseudo.py.

These tests execute the REAL shell functions on the REAL frozen Gate
command (single source of truth: v19_gate0_pair_runner.sh
``gate_chain_args``) and parse the result with the REAL
run_one_iteration parser + normalize_args — no re-typed expectations of
intermediate layers, only the frozen operator values at the resolved
end. No LLM, no training, no GPU.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_gate0_pair_runner.sh"
CHAIN_LIB = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"
RUN_ONE_ITERATION = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "run_one_iteration_for_gate0_propagation", RUN_ONE_ITERATION
)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)


def _bridged_args(flavor: str):
    """Real shell bridge: frozen Gate command → parse_chain_args →
    build_app_args → argparse → normalize_args."""
    script = f"""
V19_GATE0_NO_MAIN=1 source '{RUNNER}'
mapfile -t GA < <(gate_chain_args {flavor})
source '{CHAIN_LIB}'
parse_chain_args "${{GA[@]}}"
build_app_args 1
for a in "${{APP_ARGS[@]}}"; do echo "$a"; done
"""
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert r.returncode == 0, r.stderr
    app_args = r.stdout.splitlines()
    assert len(app_args) > 40, f"implausibly short APP_ARGS: {app_args}"
    args = roi.build_parser().parse_args(app_args)
    return roi.normalize_args(args)


@pytest.fixture(scope="module")
def arch_args():
    return _bridged_args("arch")


@pytest.fixture(scope="module")
def loss_args():
    return _bridged_args("loss")


class TestResolvedGateValues:
    """The frozen operator values, asserted on the RESOLVED namespace."""

    def test_identity_per_flavor(self, arch_args, loss_args):
        assert arch_args.run_name == "v19_gate_arch_15_19"
        assert loss_args.run_name == "v19_gate_loss_15_19"
        assert arch_args.workspace.endswith("/v19_gate_arch_15_19")
        assert loss_args.workspace.endswith("/v19_gate_loss_15_19")
        assert arch_args.workspace != loss_args.workspace
        assert arch_args.start_iteration == 1

    def test_execution_controls(self, arch_args, loss_args):
        for a in (arch_args, loss_args):
            assert a.max_rounds == 2
            assert a.max_epochs == 1
            assert a.max_proposal_attempts == 3
            assert a.force_formal_round is True  # default ON — Gate requires it
            assert not getattr(a, "seed_paths", None)  # cold start

    def test_portions(self, arch_args, loss_args):
        for a in (arch_args, loss_args):
            assert a.trial_portion == 0.02
            assert a.train_portion == 1.0
            assert a.eval_portion == 0.01
            assert a.formal_portion == 0.02
            assert a.formal_train_portion == 1.0
            assert a.formal_eval_portion == 0.01

    def test_budgets(self, arch_args, loss_args):
        for a in (arch_args, loss_args):
            assert a.trial_time_budget_minutes == 5
            assert a.formal_time_budget_minutes == 30
            assert a.trial_vram_budget_gb == 12
            assert a.formal_vram_budget_gb == 12

    def test_runtime_control(self, arch_args, loss_args):
        for a in (arch_args, loss_args):
            assert a.runtime_watchdog is True
            assert a.runtime_safety_factor == 1.5
            assert a.runtime_trial_safety_factor == 3.0
            assert a.runtime_formal_safety_factor == 2.25
            assert a.runtime_watchdog_safety_factor == 3.5
            assert a.runtime_watchdog_floor_seconds == 120

    def test_scope_and_ordering(self, arch_args, loss_args):
        """normalize_args resolves scope/order into TYPED values (DataScope,
        int lists) — assert the typed resolution, and that the explicit
        order survives as the exact permutation (the DataScope.from_cli
        sorted-permutation hazard never touches file_order_override)."""
        for a in (arch_args, loss_args):
            assert a.data_scope.file_indices == [15, 16, 17, 18, 19]
            assert a.health_gate_files == [15, 16, 17, 18, 19]
            assert a.health_gate_enabled is True
            assert a.order_strategy_override == "sequential"
            assert a.file_order_override == [15, 16, 17, 18, 19]

    def test_incumbent_and_feedback(self, arch_args, loss_args):
        for a in (arch_args, loss_args):
            assert a.enable_chain_incumbent_formal_gates is True
            assert a.skip_formal_min_delta == 0.0
            assert a.bypass_formal_time_budget_min_delta == 0.5
            assert a.enable_structured_health_feedback is True
            assert a.health_feedback_history_window_iterations == 3
            assert a.health_feedback_history_max_entries_per_model == 8

    def test_strategies_and_configs(self, arch_args, loss_args):
        for a in (arch_args, loss_args):
            assert a.formal_strategy == "snapshot"
            assert a.formal_round_strategy == "inherit_best_trial"
            assert a.exploration_mode == "explore"
            assert a.ml_lit_review_enabled is True
            assert a.llm_config == "llm_configs/openai_tiered_v1.json"
            assert a.health_checks_config == ("configs/health_checks_baseline_observe_mode.yaml")

    def test_advice_resolves_per_flavor(self, arch_args, loss_args):
        """--advice is loaded by normalize_args into human_advice_* — the
        value-level proof that each chain gets ITS advice content."""
        assert arch_args.advice == "advice/workflow/v19_gate0_arch.json"
        assert loss_args.advice == "advice/workflow/v19_gate0_loss.json"
        assert arch_args.human_advice_propose
        assert loss_args.human_advice_propose
        assert arch_args.human_advice_propose != loss_args.human_advice_propose
        assert "ARCHITECTURE change" in arch_args.human_advice_propose
        assert "LOSS modification" in loss_args.human_advice_propose
        # neither Gate advice asks to match/beat the baseline
        for a in (arch_args, loss_args):
            joined = " ".join(
                filter(
                    None,
                    (
                        a.human_advice_mindset,
                        a.human_advice_propose,
                        a.human_advice_tune,
                    ),
                )
            )
            assert "beat FCNet" not in joined
            assert "match FCNet" not in joined


# kwarg → expected source expression at the run_workflow call site.
EXPECTED_BINDINGS = {
    "trial_portion": "args.trial_portion",
    "train_portion": "args.train_portion",
    "eval_portion": "args.eval_portion",
    "formal_portion": "args.formal_portion",
    "formal_train_portion": "args.formal_train_portion",
    "formal_eval_portion": "args.formal_eval_portion",
    "trial_time_budget_minutes": "args.trial_time_budget_minutes",
    "formal_time_budget_minutes": "args.formal_time_budget_minutes",
    "trial_vram_budget_gb": "args.trial_vram_budget_gb",
    "formal_vram_budget_gb": "args.formal_vram_budget_gb",
    "runtime_watchdog_enabled": "args.runtime_watchdog",
    "runtime_safety_factor": "args.runtime_safety_factor",
    "runtime_trial_safety_factor": "args.runtime_trial_safety_factor",
    "runtime_formal_safety_factor": "args.runtime_formal_safety_factor",
    "runtime_watchdog_safety_factor": "args.runtime_watchdog_safety_factor",
    "runtime_watchdog_floor_seconds": "args.runtime_watchdog_floor_seconds",
    "data_scope": "args.data_scope",
    "health_gate_files": "args.health_gate_files",
    "health_gate_enabled": "args.health_gate_enabled",
    "order_strategy_override": "args.order_strategy_override",
    "file_order_override": "args.file_order_override",
    "enable_chain_incumbent_formal_gates": "args.enable_chain_incumbent_formal_gates",
    "skip_formal_min_delta": "args.skip_formal_min_delta",
    "bypass_formal_time_budget_min_delta": "args.bypass_formal_time_budget_min_delta",
    "enable_structured_health_feedback": "args.enable_structured_health_feedback",
    "health_feedback_history_window_iterations": ("args.health_feedback_history_window_iterations"),
    "health_feedback_history_max_entries_per_model": (
        "args.health_feedback_history_max_entries_per_model"
    ),
    "max_rounds": "args.max_rounds",
    "max_epochs": "args.max_epochs",
    "max_proposal_attempts": "args.max_proposal_attempts",
    "force_formal_round": "args.force_formal_round",
    "exploration_mode": "args.exploration_mode",
    "human_advice_propose": "args.human_advice_propose",
    "human_advice_tune": "args.human_advice_tune",
    "human_advice_mindset": "args.human_advice_mindset",
}


class TestCliToWorkflowBinding:
    """The run_workflow call site binds each launch-critical kwarg to the
    resolved ``args.<name>`` (or a documented transform) — no layer
    substitutes a constant or a different attribute."""

    def test_call_site_bindings(self):
        tree = ast.parse(RUN_ONE_ITERATION.read_text())
        bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "run_workflow"
            ):
                for kw in node.keywords:
                    if kw.arg is not None:
                        bindings[kw.arg] = ast.unparse(kw.value)
        assert bindings, "run_workflow call site not found"
        for kwarg, expected in EXPECTED_BINDINGS.items():
            assert kwarg in bindings, f"call site no longer passes {kwarg}"
            assert bindings[kwarg] == expected, (
                f"{kwarg} bound to {bindings[kwarg]!r}, expected {expected!r}"
            )
