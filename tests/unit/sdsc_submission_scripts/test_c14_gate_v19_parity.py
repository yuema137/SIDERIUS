"""C14 — the Gate must be formal V19, only smaller.

HISTORICAL SNAPSHOT (operator ruling Q6(b), 2026-08-17). Both surfaces this
file compares — `v19_gate0_pair_runner.sh` and `v19_queue_runner.sh` — are
**retained legacy operator surfaces, not the current canonical launcher**.
Today's campaign surface is `launch_v20_campaign.sh`, driven by
`v20_queue_runner.py:37`; `sdsc_submission_scripts/README.md:77` still calls
the V19 runner "current production surface" only because it was last written
2026-08-04, two days before the V20 launcher was added. Today's Gate entry
point is `run_chain.sh` directly (`docs/gates/gate_testing_standard.md:176-194`),
not the pair runner.

So this file pins a frozen historical pair. It is kept for reversibility and
forensic compatibility, and its `openai_tiered_v1.json` reference is a
statement about what V19 emitted — NOT a claim about current Gate policy, which
`test_gate_standard_contract.py:244` owns and which requires
`openai_tiered_pro.json` (operator decision 2026-08-13). Do not read a current
policy out of this file.

Its per-flag value pins were removed in the pruning PR: all 32 were re-asserted
by `test_v19_gate0_pair_runner.py::test_frozen_values_exact`, which checks the
same `gate_chain_args` output for BOTH flavors and additionally asserts the
switch set exactly. What survives here is what only a cross-surface comparison
can establish.

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

This comparison found one divergence on 2026-07-31 — the Gate carried
`--{trial,formal}_vram_budget_gb 24` against formal V19's 16, because
`docs/gates/gate_testing_standard.md` specifies 24/24 generously so a
VRAM gate never eats a Gate attempt. Both sources were authoritative, so
it was recorded rather than resolved unilaterally. The operator resolved
it on 2026-07-31: this final V19-aligned Gate uses the formal V19 values
(16/16), and the generic Gate-standard values do not apply to it. There
is now NO permitted divergence outside the frozen Gate-scoped set.
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
        assert not divergences, (
            "the Gate would not exercise the formal V19 path; these settings "
            f"differ outside the frozen Gate-scoped set: {divergences}"
        )


class TestGateScopedValues:
    """The bounded Gate settings, exactly as the operator specified."""

    def test_the_scope_and_health_gate_files_are_paired(self):
        """DS8 partial-scope rule: monitored files must lie in the scope."""
        args = _gate_args()
        low, high = (int(x) for x in args["--data_scope"].split("-"))
        monitored = [int(x) for x in args["--health_gate_files"].split(",")]
        assert all(low <= f <= high for f in monitored)

    @pytest.mark.parametrize("flavor", ["arch", "loss"])
    def test_each_flavor_uses_its_own_lightweight_advice(self, flavor):
        args = _gate_args(flavor)
        assert args["--advice"] == f"advice/workflow/v19_gate0_{flavor}.json"
        assert (REPO_ROOT / args["--advice"]).is_file()


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
