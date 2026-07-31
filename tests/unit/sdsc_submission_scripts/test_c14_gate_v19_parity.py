"""C14 — the Gate must be formal V19, only smaller.

C14 is the last Gate before the V19 restart, so its value depends
entirely on it exercising the SAME production path. The operator froze
exactly which settings may differ (scale and budgets); everything else —
LLM config, runtime estimator and policy, admission and watchdog
factors, HealthGate config, incumbent coupling, structured feedback,
ordering, formal strategy — must be byte-identical to the formal V19
launch surface.

This test compares the two launch surfaces directly, so drift in either
script fails here rather than being discovered in a Gate that quietly
validated something other than V19.

Found by this comparison on 2026-07-31: the Gate carries
`--{trial,formal}_vram_budget_gb 24` against formal V19's 16. That is
NOT drift — `docs/gates/gate_testing_standard.md` deliberately specifies
"24 / 24 (GENEROUS — never let the VRAM gate eat a Gate attempt)". The
C14 message and the Gate standard are both authoritative and disagree
here, so the divergence is recorded as PENDING an operator decision
rather than silently resolved either way. The test pins it as the ONLY
known divergence: a second one, or this one changing without a decision,
fails.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_gate0_pair_runner.sh"
V19_RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"

#: The ONLY settings the operator froze as Gate-scoped: bounded scale,
#: budgets, identity and the lightweight advice. Anything else differing
#: means the Gate is not exercising the formal path.
GATE_SCOPED_FLAGS = frozenset(
    {
        "--workspace",
        "--run_name",
        "--advice",
        "--num_iterations",
        "--max_rounds",
        "--max_proposal_attempts",
        "--data_scope",
        "--health_gate_files",
        "--file_order_override",
        "--trial_portion",
        "--train_portion",
        "--eval_portion",
        "--formal_portion",
        "--formal_train_portion",
        "--formal_eval_portion",
        "--trial_time_budget_minutes",
        "--formal_time_budget_minutes",
    }
)


#: Divergences that exist because two authoritative sources disagree.
#: Recorded, not resolved — see the module docstring.
PENDING_OPERATOR_DECISION = {
    "--trial_vram_budget_gb": ("24", "16"),  # (gate standard, formal V19)
    "--formal_vram_budget_gb": ("24", "16"),
}


def _gate_args(flavor: str = "arch") -> dict[str, str]:
    result = subprocess.run(
        ["bash", "-c", f"V19_GATE0_NO_MAIN=1 source '{GATE_RUNNER}'; gate_chain_args {flavor}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    args, i = {}, 0
    while i < len(lines):
        if lines[i].startswith("--"):
            if i + 1 < len(lines) and not lines[i + 1].startswith("--"):
                args[lines[i]] = lines[i + 1]
                i += 2
            else:
                args[lines[i]] = "(flag)"
                i += 1
        else:
            i += 1
    return args


def _v19_args() -> dict[str, str]:
    """The formal V19 chain argv, read from the heredoc in the runner."""
    source = V19_RUNNER.read_text()
    start = source.index("bash sdsc_submission_scripts/run_chain.sh")
    block = source[start : source.index("status=\\$?", start)]
    args = {}
    for flag, value in re.findall(r"(--[a-z_0-9]+)(?:[ \t]+((?:'[^']*')|(?:[^\s\\]+)))?", block):
        args[flag] = (value or "(flag)").strip("'")
    return args


class TestGateMatchesFormalV19:
    def test_nothing_outside_the_frozen_set_differs(self):
        gate, v19 = _gate_args(), _v19_args()
        divergences = {
            flag: (gate.get(flag, "ABSENT"), v19.get(flag, "ABSENT"))
            for flag in set(gate) | set(v19)
            if flag not in GATE_SCOPED_FLAGS and gate.get(flag) != v19.get(flag)
        }
        assert divergences == PENDING_OPERATOR_DECISION, (
            "the Gate would not exercise the formal V19 path; settings differ "
            "outside the frozen Gate-scoped set beyond the one known, recorded "
            f"conflict: {divergences}"
        )

    def test_the_known_conflict_is_still_exactly_what_was_recorded(self):
        """The VRAM-budget conflict must not be resolved by a silent edit
        to either script — only by an operator decision that updates this
        test alongside it."""
        gate, v19 = _gate_args(), _v19_args()
        for flag, (gate_value, v19_value) in PENDING_OPERATOR_DECISION.items():
            assert gate[flag] == gate_value, f"{flag} changed on the Gate side"
            assert v19[flag] == v19_value, f"{flag} changed on the formal V19 side"

    @pytest.mark.parametrize(
        "flag,value",
        [
            # admission and watchdog — the whole point of the Gate
            ("--runtime_watchdog", "(flag)"),
            ("--runtime_safety_factor", "1.5"),
            ("--runtime_trial_safety_factor", "3.0"),
            ("--runtime_formal_safety_factor", "2.0"),
            ("--runtime_watchdog_safety_factor", "3.5"),
            ("--runtime_watchdog_floor_seconds", "120"),
            # production LLM + HealthGate + coupling + ordering
            ("--llm_config", "llm_configs/openai_tiered_v1.json"),
            ("--health_checks_config", "configs/health_checks_baseline_observe_mode.yaml"),
            ("--enable_chain_incumbent_formal_gates", "(flag)"),
            ("--enable_structured_health_feedback", "(flag)"),
            ("--order_strategy_override", "sequential"),
            ("--formal_strategy", "snapshot"),
            ("--formal_round_strategy", "inherit_best_trial"),
            ("--exploration_mode", "explore"),
            ("--ml_lit_review_enabled", "(flag)"),
            ("--max_epochs", "1"),
        ],
    )
    def test_the_production_settings_are_pinned(self, flag, value):
        assert _gate_args().get(flag) == value


class TestGateScopedValues:
    """The bounded Gate settings, exactly as the operator specified."""

    @pytest.mark.parametrize(
        "flag,value",
        [
            ("--num_iterations", "2"),
            ("--max_rounds", "2"),
            ("--max_proposal_attempts", "3"),
            ("--data_scope", "15-19"),
            ("--health_gate_files", "15,16,17,18,19"),
            ("--file_order_override", "15,16,17,18,19"),
            ("--trial_portion", "0.02"),
            ("--train_portion", "1.0"),
            ("--eval_portion", "0.01"),
            ("--formal_portion", "0.02"),
            ("--formal_train_portion", "1.0"),
            ("--formal_eval_portion", "0.01"),
            ("--trial_time_budget_minutes", "5"),
            ("--formal_time_budget_minutes", "30"),
        ],
    )
    def test_the_bounded_settings(self, flag, value):
        assert _gate_args().get(flag) == value

    def test_the_scope_and_health_gate_files_are_paired(self):
        """DS8 partial-scope rule: monitored files must lie in the scope."""
        args = _gate_args()
        low, high = (int(x) for x in args["--data_scope"].split("-"))
        monitored = [int(x) for x in args["--health_gate_files"].split(",")]
        assert all(low <= f <= high for f in monitored)

    def test_the_gate_is_cold_start(self):
        """Operator rule 2026-07-27: every real-training gate run is
        cold-start. `--seed_paths` must be absent, not empty."""
        assert "--seed_paths" not in _gate_args()

    @pytest.mark.parametrize("flavor", ["arch", "loss"])
    def test_each_flavor_uses_its_own_lightweight_advice(self, flavor):
        args = _gate_args(flavor)
        assert args["--advice"] == f"advice/workflow/v19_gate0_{flavor}.json"
        assert (REPO_ROOT / args["--advice"]).is_file()

    def test_the_two_chains_differ_only_in_identity_and_advice(self):
        arch, loss = _gate_args("arch"), _gate_args("loss")
        differing = {k for k in set(arch) | set(loss) if arch.get(k) != loss.get(k)}
        assert differing == {"--workspace", "--run_name", "--advice"}


class TestLightweightAdviceIntegrity:
    @pytest.mark.parametrize("flavor", ["arch", "loss"])
    def test_the_advice_is_valid_and_role_scoped(self, flavor):
        import json

        payload = json.loads(
            (REPO_ROOT / "advice" / "workflow" / f"v19_gate0_{flavor}.json").read_text()
        )
        assert set(payload) == {"mindset", "propose", "implement", "tune", "validate"}
        assert all(isinstance(v, list) and v for v in payload.values())
        # each file must speak about its OWN role, so the two cannot be swapped
        other = "loss" if flavor == "arch" else "arch"
        head = " ".join(payload["mindset"] + payload["propose"]).lower()
        assert flavor in head
        assert f"{other} chain" not in head
