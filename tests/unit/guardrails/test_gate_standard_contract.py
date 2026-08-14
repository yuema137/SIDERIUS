"""The Gate standard's canonical command must stay the bounded one.

`docs/gates/gate_testing_standard.md` is not commentary — an operator (or
an agent) copies the canonical Gate-2 command out of it and runs it. When
the document drifts from the bounded shape, nothing fails; the next Gate
simply costs an hour again, which is precisely how the pre-2026-08-13
shape survived.

So the properties that make a Gate 2 bounded, real and functional are
asserted against the document itself. Each test names one way the
document could quietly stop meaning what it says.

Scope note: these are contract tests over the canonical command's SHAPE.
Whether the bounds then hold at execution is proved separately, by
`tests/unit/execute_tools/test_validation_workload_envelope.py` (the
epoch is really smaller) and
`tests/unit/agent/tune_ml_hyperparam_agent/test_validation_posture_bounds.py`
(the envelope reaches the policy, and covers formal as well as trial).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sdsc_submission_scripts.run_one_iteration import build_parser

REPO_ROOT = Path(__file__).resolve().parents[3]
STANDARD = REPO_ROOT / "docs" / "gates" / "gate_testing_standard.md"

#: The canonical command is the FIRST ```bash block under the Gate 2
#: heading. Anchoring on the heading rather than on the first block in the
#: file keeps Gate 1's setup from being mistaken for it.
GATE2_HEADING = "### Gate 2 — Real LLM + real training (smoke test)"


@pytest.fixture(scope="module")
def standard_text() -> str:
    return STANDARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def gate2_section(standard_text: str) -> str:
    start = standard_text.index(GATE2_HEADING)
    rest = standard_text[start + len(GATE2_HEADING) :]
    end = rest.find("\n### ")
    return rest if end == -1 else rest[:end]


@pytest.fixture(scope="module")
def canonical_command(gate2_section: str) -> str:
    match = re.search(r"```bash\n(.*?)```", gate2_section, re.DOTALL)
    assert match, "the Gate 2 section has no canonical command block"
    return match.group(1)


def _flag_value(command: str, flag: str) -> str | None:
    """The value following ``flag``, or '' for a bare switch, or None."""
    match = re.search(rf"{re.escape(flag)}(?:\s+([^\s\\]+))?", command)
    if not match:
        return None
    return match.group(1) or ""


# ---------------------------------------------------------------------
# Temporal depth — the default is the SHALLOWEST that proves the path
# ---------------------------------------------------------------------


def test_the_canonical_gate_runs_one_iteration(canonical_command):
    """Case A. Two iterations doubled the Gate for no functional evidence.

    Fails when: the canonical command's depth creeps back up, which is
    what turned a smoke test into a ~30-60 minute campaign.
    """
    assert _flag_value(canonical_command, "--num_iterations") == "1"


def test_the_canonical_gate_runs_one_tuner_round(canonical_command):
    """Case B. A second round exercises tuner POLICY, not the PR.

    Fails when: the default depth grows again. Deeper depth is opt-in per
    failure class, which the document states separately.
    """
    assert _flag_value(canonical_command, "--max_rounds") == "1"


def test_deeper_depth_is_documented_as_failure_class_driven(gate2_section):
    """The escalation rule must survive, or 'default 1x1' reads as a cap.

    Fails when: the table saying which failure classes justify more
    rounds or iterations is dropped, leaving operators with either an
    under-powered Gate or no rule at all.
    """
    assert "Temporal depth is failure-class driven" in gate2_section
    assert "≥ 2 rounds" in gate2_section
    assert "≥ 2 iterations" in gate2_section


# ---------------------------------------------------------------------
# The envelope — and no force-trial
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag",
    ["--validation_max_train_samples", "--validation_max_portion", "--max_epochs"],
)
def test_the_canonical_gate_carries_the_workload_envelope(canonical_command, flag):
    """Case C/D/F. The three bounds that hold whatever the planner chose.

    The absolute sample ceiling is the one a portion cannot replace:
    samples per PSD segment are ``psd_segment_length // seg_size`` and
    seg_size is the planner's, so 1 % of the scope resolved to 12,500
    optimizer steps during Step 03.

    Fails when: any of them is dropped from the canonical command — at
    which point a planner-elected formal round can pull full scope.
    """
    assert _flag_value(canonical_command, flag) not in (None, "")


def test_the_canonical_gate_does_not_force_a_round_mode(canonical_command, gate2_section):
    """Case D, the design decision. The Gate bounds COST, not policy.

    A force-trial flag would have made the Gate cheap by overriding the
    tuner's scientific decision — the wrong authority, and unnecessary
    once formal is bounded too.

    Fails when: someone reintroduces mode forcing as an efficiency
    measure, which would also stop the Gate exercising whichever mode
    production would really pick.
    """
    assert "--validation_force_trial" not in canonical_command
    assert "force-trial" not in canonical_command
    assert "planner-controlled" in gate2_section or "planner plans normally" in gate2_section


def test_every_envelope_flag_in_the_canonical_command_actually_exists(canonical_command):
    """A documented flag that argparse rejects is a Gate that will not start.

    Fails when: the command is edited with a flag name the chain runner
    does not accept — the failure would otherwise surface only when an
    operator pastes it, after paying for the LLM calls.
    """
    known = {
        action_option
        for action in build_parser()._actions
        for action_option in action.option_strings
    }
    documented = set(re.findall(r"(--[a-z0-9_\-]+)", canonical_command))
    # run_chain.sh owns a few flags the per-iteration runner does not.
    shell_only = {"--mode", "--num_iterations", "--run_name", "--workspace", "--llm_config"}
    unknown = documented - known - shell_only
    assert not unknown, (
        f"canonical command uses flags run_one_iteration.py rejects: {sorted(unknown)}"
    )


# ---------------------------------------------------------------------
# Non-bounds must stay labelled as non-bounds
# ---------------------------------------------------------------------


def test_the_forecast_budget_is_not_presented_as_a_hard_limit(gate2_section):
    """The document previously called ``--trial_time_budget_minutes``
    mandatory 'without it training runs without a time ceiling'.

    That is false — it is admission logic over a forecast, and a round ran
    33m53s under a 5-minute budget. An operator who believes it is a
    ceiling stops looking for a real one.

    Fails when: the correction is lost and the Gate standard again
    promises a bound that does not exist.
    """
    assert "33m53s" in gate2_section
    assert "forecast" in gate2_section.lower()


def test_the_rejection_guard_is_not_the_sizing_mechanism(gate2_section):
    """``max_steps_per_attempt`` REJECTS; it does not bound.

    Set below the planner's normal solution it skipped every round —
    zero training, zero score, and a Gate that proved nothing while
    appearing configured.

    Fails when: the document stops warning about it and someone sizes the
    next Gate with it again.
    """
    assert "max_steps_per_attempt" in gate2_section
    assert "SKIPPED" in gate2_section


def test_the_wall_clock_ceiling_is_documented_as_an_emergency_fuse(gate2_section):
    """Case I. A deadline kill is not sizing — it spends the whole run
    and yields no evidence.

    Fails when: the fuse is re-described as the Gate's cost control,
    which would make 'bounded' mean 'killed after 15 minutes'.
    """
    assert "--validation_max_phase_seconds" in gate2_section
    assert "emergency fuse" in gate2_section.lower() or "fuse only" in gate2_section.lower()
    assert "never reaches it" in gate2_section or "almost never" in gate2_section


# ---------------------------------------------------------------------
# PASS semantics — functional, real, and not scientific
# ---------------------------------------------------------------------


def test_pass_requires_the_real_path_to_have_executed(gate2_section):
    """Case H. Gate 2's entire value is that the work was REAL.

    Fails when: the criteria stop naming real training, inference and
    scoring, at which point pseudo evidence could satisfy them and the
    Gate would differ from Gate 1 in cost only.
    """
    lowered = gate2_section.lower()
    assert "real training actually executed" in lowered
    assert "real inference actually executed" in lowered
    assert "real scoring actually executed" in lowered
    assert "finite" in lowered


def test_pass_does_not_require_scientific_model_quality(gate2_section):
    """Case L. A one-epoch, 1 %-scope, sample-capped model is a plumbing
    signal, not a scientific one.

    Requiring quality here would make a correctly-working framework fail
    its own Gate whenever the LLM invented a mediocre architecture — and
    that is a proposer outcome, not a defect in the PR under test.

    Fails when: an improvement or threshold requirement creeps back into
    the PASS list.
    """
    lowered = gate2_section.lower()
    assert "not** pass/fail criteria" in lowered or "not pass/fail criteria" in lowered
    assert "baseline" in lowered
    assert "convergence" in lowered


def test_every_real_llm_gate_uses_the_pro_config(standard_text):
    """Case K. Binding operator decision, 2026-08-13.

    A weak tier makes the Gate measure proposer/planner judgement instead
    of the PR: during Step 03 it invented a list-valued ``dilation_cycle``
    against a scalar-only contract and burned three codegen attempts.

    Fails when: a v1/minimal mandate is reintroduced anywhere in the
    standard, or the canonical commands stop naming the pro config.
    """
    assert standard_text.count("openai_tiered_pro.json") >= 3
    # Paragraph-scoped, not line-scoped: the standard is hard-wrapped
    # prose, so a mention and its "no longer sufficient" qualifier
    # routinely land on different lines.
    paragraphs = re.split(r"\n\s*\n", standard_text)
    for superseded in ("certify_minimal.json", "openai_tiered_v1.json"):
        for paragraph in paragraphs:
            if superseded in paragraph:
                assert re.search(
                    r"no longer|not sufficient|superseded|unusable|historical"
                    r"|was replaced|previous",
                    paragraph,
                    re.IGNORECASE,
                ), f"{superseded} appears without being marked superseded: {paragraph[:200]!r}"
