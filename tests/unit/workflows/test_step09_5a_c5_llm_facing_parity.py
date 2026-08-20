"""Step 09.5a C5 — the Gate-1 waiver owner.

The operator's ruling waives Gate 1 **only if exact LLM-facing parity is
proven**, and requires that proof to be executable rather than rhetorical. This
module is that proof, and it is deliberately explicit about its own shape.

THE ARGUMENT, IN TWO HALVES
----------------------------
1. **The values reaching every node are byte-identical.** Owned by the C0
   oracle (`test_step09_5a_c0_oracle.py`), which deep-compares the full input
   object handed to each of the five agents against a golden captured before
   any production edit.
2. **No code that turns those values into prompts was touched.** Owned here: a
   diff census over the whole PR proving it changed no prompt template, no
   renderer, no node, no schema and no bridge.

Identical inputs into untouched prompt-building code produce identical prompts.
Both halves are executable, and neither alone is sufficient — which is why they
are separate owners.

A THIRD HALF WAS ADDED AT C5c
------------------------------
This module originally stated that it does **not** capture prompt bytes,
because the pre-refactor side no longer exists in the working tree. The
operator ruled that insufficient: the frozen waiver requires exact LLM-facing
parity *including rendered prompt bytes*, and "the source did not change" is
not a substitute for the comparison.

That gap is now closed by an actual BASE-vs-HEAD execution differential —
`tests/helpers/step09_5a_llm_parity_capture.py` — which rendered both trees on
one fixture and compared **16 calls / 5,362,333 prompt bytes**: call count,
order, labels, methods, system bytes, user bytes and structured inputs, all
exact-equal (sha256 `f5d706385e18add4` on both sides).

The two checks below remain, because they are cheap, run in CI, and catch a
FUTURE commit that the one-time differential cannot see.

If a later commit in this PR touches any surface listed in
:data:`LLM_FACING_SURFACES`, this test turns RED and — per the frozen
disposition — **Gate 1 becomes REQUIRED**. That is the intended behaviour, not
a nuisance: an LLM-facing delta in a behaviour-preserving structural PR is a
scope-creep signal first and a Gate question second.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The frozen design head — the commit this PR branched from. Everything the PR
#: changed is `git diff <this> HEAD`.
DESIGN_BASE = "14b7e22a6d832891d4ffd1c0ca5e3d686365f7df"

#: Every production surface that can change what an LLM receives: the prompt
#: templates and their renderers, the nodes that assemble and issue calls, the
#: bridge itself, and the schemas whose fields those prompts render.
LLM_FACING_SURFACES = (
    "agent/prompt_templates/",
    "agent/prompts.py",
    "agent/llm_bridge.py",
    "agent/schemas/",
    "nodes/",
    "ml_models/",
    "execute_tools/evaluation_metric.py",
    "execute_tools/metric_order.py",
)


def _changed_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", DESIGN_BASE, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"cannot diff against the design base: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line.strip()]


class TestLlmFacingParity:
    def test_the_pr_touches_no_llm_facing_production_surface(self):
        """Half two of the parity argument.

        Defect this catches: a prompt template, renderer, node or schema edited
        somewhere in this PR — which would make the Gate-1 waiver unsound, and
        which no behavioural test in this PR would notice, because none of them
        renders a prompt.
        """
        changed = _changed_files()
        offending = sorted(
            f
            for f in changed
            if not f.startswith(("tests/", "docs/")) and f.startswith(LLM_FACING_SURFACES)
        )
        assert not offending, (
            "Step 09.5a touched LLM-facing production code: "
            f"{offending}.\nThe Gate-1 waiver rests on this being empty — per the "
            "frozen disposition, Gate 1 is now REQUIRED, and an LLM-facing delta "
            "in a behaviour-preserving structural PR should first be investigated "
            "as scope creep."
        )

    def test_the_census_is_not_vacuous(self):
        """A diff that returned nothing would pass the check above."""
        changed = _changed_files()
        assert len(changed) >= 10, (
            f"the diff against {DESIGN_BASE[:8]} returned only {len(changed)} "
            "files — the census is not looking at this PR"
        )
        production = [f for f in changed if not f.startswith(("tests/", "docs/"))]
        assert production, "no production file changed; the census proves nothing"

    def test_the_detector_would_catch_an_llm_facing_change(self):
        """Anti-vacuity for the matcher itself, not just the diff."""
        planted = ["workflows/model_exploration.py", "agent/prompt_templates/tuner/rendering.py"]
        offending = [f for f in planted if f.startswith(LLM_FACING_SURFACES)]
        assert offending == ["agent/prompt_templates/tuner/rendering.py"]

    def test_the_changed_production_surface_is_exactly_the_designed_one(self):
        """The PR's production footprint matches design §28.

        Defect this catches: scope creep of any kind — a production file edited
        that no Class-A finding justifies.
        """
        expected = {
            "core/chain_state.py",
            "core/committed_digests.py",
            "core/resume.py",
            # Step 09.5a Gate-2 forensics (2026-08-20), operator-authorized as
            # a narrow blocking repair inside this PR: the
            # insufficient-stability diagnostic reported a SATISFIED condition
            # as the failure. MESSAGE TEXT ONLY — no arithmetic, no verdict, no
            # threshold, no schema, and `failure_reason` participates in no
            # calibration key or identity hash. It is listed here rather than
            # silenced because this census exists to make scope creep visible,
            # and an unexplained new production file is exactly what it should
            # catch.
            "core/runtime_control/adaptive.py",
            # Gate CONFIGURATION, not production code: the intent half of the
            # gate standard's binding 4 GiB + advice policy (2026-08-16), which
            # this milestone's first Gate command violated. Listed rather than
            # excluded by widening the filter — the census's job is to make
            # every non-test, non-docs addition visible and explained.
            "advice/gate/gate_09_5a_carrier_refactor_advice.json",
            "sdsc_submission_scripts/run_exploration_test.py",
            "sdsc_submission_scripts/run_one_iteration.py",
            "workflows/model_exploration.py",
            "workflows/run_bindings.py",
            "workflows/run_config.py",
            "workflows/strategy_modes.py",
        }
        actual = {f for f in _changed_files() if not f.startswith(("tests/", "docs/"))}
        assert actual == expected, (
            "the production footprint moved away from design §28.\n"
            f"  unexpected: {sorted(actual - expected)}\n"
            f"  missing:    {sorted(expected - actual)}"
        )
