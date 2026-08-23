"""Step 07 PR 07b — C4: task content rendered from its authority, byte-exact.

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.6 (the per-block table), §3.9 (the bridge surface),
§3.10 (OD-1), §6 rung **B-07b-3**, §8 rows 7/12/13.

Four claims, four failure classes:

1. **Byte equality under TIDMAD.** Each rendered token equals the literal it
   replaced, to the byte. The PB-1/PB-2 goldens are the primary proof — they
   must PASS UNCHANGED, with nothing regenerated in this commit — and the
   per-token tests below say *which* token broke when they do not.

2. **The template no longer carries the literal.** Byte equality alone would
   also be satisfied by leaving the literal in place and never calling the
   renderer. Scoped absence pins on ``PLANNER_PROMPT`` / ``REFLECTOR_PROMPT``
   (Step-01 §13.4: scoped to the constants, never a whole-prompt absence
   claim) are what make the render load-bearing.

3. **A contrast task renders differently** (rung B-07b-3) — a different
   dataset topology, a different Model-I/O contract and an effective health
   config with different check names produce different tokens from the same
   code, and the check whose name is absent takes its advice sentence with it.

4. **OD-1 is closed.** The condensed history branch is byte-stable across
   processes. Proved in a SUBPROCESS with a different ``PYTHONHASHSEED``,
   because the defect was invisible to any in-process assertion: within one
   interpreter the frozenset's iteration order is stable, so a same-process
   comparison passes while the bytes still differ between runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.prompt_templates.tuner.rendering import (
    EFFICIENCY_BAND_FRACTION,
    EFFICIENCY_BAND_PCT,
    TunerTaskRender,
    build_tuner_task_render,
    render_builtin_model_roster,
    render_focal_defaults,
    render_full_scope_segments,
    render_gate_name_tokens,
    render_output_contract_shape,
)
from agent.prompts import PLANNER_PROMPT, REFLECTOR_PROMPT, _truncate_memory_history
from tests.helpers.golden import assert_golden
from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import (
    BoundaryRecorderBridge,
    planner_fixture_kwargs,
    tidmad_task_render,
)

GOLDENS = Path(__file__).parent / "goldens"
REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# 1. Byte equality — the literal each token replaced
# ---------------------------------------------------------------------------

# Hardcoded, never re-derived from the renderer: comparing a renderer to itself
# passes for any implementation (CLAUDE.md). These ARE the bytes the shipped
# templates carried before C4, read out of the pre-C4 goldens.
PRE_C4_LITERALS = {
    "builtin_model_roster": "punet | fcnet | transformer | wavenet | rnn | gated_fno",
    "full_scope_segments": 4000,
    "output_contract_shape": "[B, 256, T]",
    "focal_alpha_default": "0.5",
    "focal_gamma_default": "2.0",
    "efficiency_band_pct": "5",
}


class TestTidmadTokensAreByteIdentical:
    @pytest.mark.parametrize("token", sorted(PRE_C4_LITERALS))
    def test_each_token_equals_the_literal_it_replaced(self, token):
        rendered = getattr(tidmad_task_render(), token)
        assert rendered == PRE_C4_LITERALS[token]

    def test_the_effective_config_declares_the_two_advised_checks(self):
        """The collapse advice names ``output_diversity`` and
        ``amplitude_collapse``; under the shipped config both exist, so both
        sentences render and PB-1 is unchanged."""
        render = tidmad_task_render()
        assert render.has_check("output_diversity")
        assert render.has_check("amplitude_collapse")

    def test_the_efficiency_constant_is_the_policys_own(self):
        """One symbol, two consumers. If the band and the prompt drifted apart
        the agent would optimise against a rule the tuner does not apply."""
        assert EFFICIENCY_BAND_PCT == f"{EFFICIENCY_BAND_FRACTION * 100:g}" == "5"


# ---------------------------------------------------------------------------
# 2. The template no longer carries the rendered literals (scoped absence)
# ---------------------------------------------------------------------------


class TestTemplatesCarryNoRenderedLiteral:
    @pytest.mark.parametrize(
        "literal",
        [
            "punet | fcnet | transformer | wavenet | rnn | gated_fno",
            "4000",
            "alpha=0.5",
            "gamma=2.0",
            "`output_diversity`",
            "`amplitude_collapse`",
        ],
    )
    def test_planner_template_is_free_of_the_literal(self, literal):
        """MUTATION TARGET: reinstating a literal beside its token.

        The prompt would still render correctly under TIDMAD and every golden
        would stay green, while the value silently stopped coming from the
        authority.
        """
        assert literal not in PLANNER_PROMPT

    def test_the_planner_template_still_carries_the_KEPT_literals(self):
        """The other half of the pin, and the reason it is scoped.

        Facts no landed authority owns stay literal ON PURPOSE (§3.6): the
        per-model roster descriptions, the CH1/CH2 log-space prose, the
        "200 segments" illustration, the regressor/hybrid shapes, the built-in
        loss list. Asserting them absent would be asserting a claim 07b never
        made — and would push a future author toward inventing a task-config
        field to satisfy the test.

        UPGRADED by Step 12 / PR-12a C7: these facts are still literal and
        still un-owned by any task authority — but four of them now live in
        the RENDER authority as the legacy substitution for a composition-gated
        token, rather than inline in the template. The property this test
        cares about is what an UN-COMPOSED run renders, which has not moved,
        so it asks the legacy-rendered template instead of the raw constant.
        Asserting them absent would still be asserting a claim nobody made.
        """
        from tests.helpers.step12_pr12a_prompt_capture import legacy_rendered_template

        rendered = legacy_rendered_template("planner")
        for kept in (
            "**PositionalUNet (punet)**",
            "200 segments",
            "`smooth_l1`",
            "raw_baseline",
        ):
            assert kept in rendered

    def test_the_reflector_template_renders_the_band_and_keeps_its_anchor(self):
        """The reflector's bridge surface stays the frozen additive one, so it
        gets no ``task_render``. The efficiency band still renders — it is a
        framework constant needing no transport — but the profile-derived
        ``200 vs 4000`` anchor stays literal, recorded as a gap rather than
        smuggled through a new kwarg (§3.9)."""
        assert "{EFFICIENCY_BAND_PCT}" in REFLECTOR_PROMPT
        assert "within 5% of the best score" not in REFLECTOR_PROMPT
        assert "200 vs 4000" in REFLECTOR_PROMPT


# ---------------------------------------------------------------------------
# 3. Rung B-07b-3 — a contrast task renders different task content
# ---------------------------------------------------------------------------


class _Dataset:
    def __init__(self, num_files, segments_per_file):
        self.num_files = num_files
        self.segments_per_file = segments_per_file


class _Check:
    def __init__(self, name):
        self.name = name


class _Gate:
    def __init__(self, checks):
        self.checks = [_Check(c) for c in checks]


class _HealthConfig:
    def __init__(self, checks):
        self.health_gates = [_Gate(checks)]


def contrast_task_render() -> TunerTaskRender:
    """A task that shares NO rendered fact with TIDMAD.

    3 files x 50 segments (the Step-02 contrast topology), a two-model
    registry, a contract with a different output shape, and a health config
    whose checks are renamed — so every assertion below fails if a token is
    still coming from a TIDMAD literal rather than from the run's authority.
    """

    class _Dim:
        def __init__(self, token):
            self.token = token

        def render(self):
            return self.token

    class _Axis:
        def __init__(self, token):
            self.dimension = _Dim(token)

    class _Output:
        axes = (_Axis("B"), _Axis("T"))

        def render_shape(self):
            return "[" + ", ".join(a.dimension.render() for a in self.axes) + "]"

    class _Contract:
        output = _Output()

    return build_tuner_task_render(
        dataset=_Dataset(num_files=3, segments_per_file=50),
        model_io_contract=_Contract(),
        health_config=_HealthConfig(["frame_drift", "spatial_collapse"]),
        efficiency_band_fraction=EFFICIENCY_BAND_FRACTION,
        registry={"punet": object(), "fcnet": object()},
    )


class TestContrastTaskRendersDifferently:
    def test_every_profile_derived_token_differs(self):
        contrast = contrast_task_render()
        assert contrast.full_scope_segments == 150  # 3 x 50, not TIDMAD's 4000
        assert contrast.output_contract_shape == "[B, T]"
        assert contrast.builtin_model_roster == "punet | fcnet"
        assert contrast.gate_check_names == ("frame_drift", "spatial_collapse")

    def test_the_planner_prompt_carries_the_contrast_facts_not_tidmads(self):
        bridge = BoundaryRecorderBridge()
        bridge.plan(**{**planner_fixture_kwargs(), "task_render": contrast_task_render()})
        _method, _label, system, user = bridge.captures[0]

        assert "trains on 150 segments" in system
        assert "trains on 4000 segments" not in system
        assert "punet | fcnet | transformer" not in user

    def test_advice_about_a_check_the_run_does_not_run_is_omitted(self):
        """A run whose effective config has no ``output_diversity`` check would
        otherwise be told to read a ``failure_reason`` it can never receive."""
        bridge = BoundaryRecorderBridge()
        bridge.plan(**{**planner_fixture_kwargs(), "task_render": contrast_task_render()})
        _method, _label, system, _user = bridge.captures[0]

        assert "output_diversity" not in system
        assert "amplitude_collapse" not in system
        # ...and the surrounding collapse-recovery advice, which is NOT
        # check-specific, survives.
        assert "switch immediately to focal loss" in system

    def test_a_run_without_a_model_io_contract_omits_the_shape(self):
        """No contract, no shape token — never a guessed one. The shape tells
        the planner which loss families are legal, so guessing would make every
        plan it produces invalid."""
        assert render_output_contract_shape(None) is None
        render = build_tuner_task_render(
            dataset=_Dataset(4, 10),
            model_io_contract=None,
            health_config=_HealthConfig([]),
            efficiency_band_fraction=EFFICIENCY_BAND_FRACTION,
        )
        bridge = BoundaryRecorderBridge()
        bridge.plan(**{**planner_fixture_kwargs(force_model="punet"), "task_render": render})
        _method, _label, _system, user = bridge.captures[0]
        assert "**CLASSIFIER**. " in user
        assert "output [B, 256, T]" not in user


# ---------------------------------------------------------------------------
# 4. Fail-closed — no silent TIDMAD fallback in the bridge
# ---------------------------------------------------------------------------


def test_plan_without_a_task_render_fails_closed():
    """MUTATION TARGET: a ``task_render or <shipped default>`` fallback.

    Such a bridge would render TIDMAD's roster, TIDMAD's 4000 and TIDMAD's
    ``[B, 256, T]`` for a task that declared none of them, and every test above
    would still pass because the shipped path supplies a real object.
    """
    bridge = BoundaryRecorderBridge()
    kwargs = {k: v for k, v in planner_fixture_kwargs().items() if k != "task_render"}
    with pytest.raises(ValueError, match="task_render"):
        bridge.plan(**kwargs)
    assert bridge.captures == [], "the refusal must precede any render"


# ---------------------------------------------------------------------------
# 5. OD-1 — the condensed branch is byte-stable across processes
# ---------------------------------------------------------------------------

_HISTORY_4 = [
    {
        "exp_id": f"punet_step07b_od1_{i:03d}",
        "status": "success",
        "model_type": "punet",
        "denoising_score": -3.0 + 0.1 * i,
        "is_trial": i < 3,
        "failure_reason": None,
        "params": {
            "model_config": {"hidden_dim": 32 * i, "depth": 2},
            "train_config": {"lr": 0.0005, "batch_size": 8, "epochs": 1},
            "loss_config": {"loss_type": "focal"},
        },
        "memory": {
            "hypothesis": f"Round {i} hypothesis.",
            "conclusion": f"Round {i} conclusion.",
            "round_index": i,
            "memory_update": f"Round {i} memory update.",
        },
    }
    for i in range(1, 5)
]

_RENDER_SNIPPET = """
import json, sys
sys.path.insert(0, sys.argv[1])
from agent.prompts import _truncate_memory_history
history = json.loads(sys.argv[2])
print(json.dumps(_truncate_memory_history(history), indent=2))
"""


def _render_in_subprocess(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    result = subprocess.run(
        [sys.executable, "-c", _RENDER_SNIPPET, str(REPO_ROOT), json.dumps(_HISTORY_4)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        check=True,
    )
    return result.stdout


class TestOD1CondensedBranchIsStable:
    def test_the_four_record_history_actually_enters_the_condensed_branch(self):
        """Precondition. With <= 3 records the verbatim path returns the
        records unchanged and the whole rung would prove nothing — which is
        precisely why the pre-07b PB-1 fixture never caught this."""
        condensed = _truncate_memory_history(_HISTORY_4)
        assert len(condensed) == 4
        assert "params" not in condensed[0], "the oldest record must be condensed"
        assert "params" in condensed[-1], "the window's records stay verbatim"

    def test_the_render_is_byte_identical_across_hash_seeds(self):
        """MUTATION TARGET: iterating the frozenset again.

        Before 07b this produced a different key order per process — five
        distinct orders across five seeds — so the planner's prompt bytes for
        any history longer than the verbatim window were not reproducible. An
        in-process comparison cannot see it: within one interpreter the order
        is stable.
        """
        renders = {_render_in_subprocess(seed) for seed in ("0", "1", "12345")}
        assert len(renders) == 1, "condensed key order still varies across processes"

    def test_the_condensed_entry_uses_the_records_own_key_order(self):
        """Not a sorted order — the record's own. The verbatim window already
        serialises records in insertion order, so imposing an alphabetical one
        here would serialise the SAME record two different ways depending on
        whether it had fallen out of the window."""
        condensed = _truncate_memory_history(_HISTORY_4)[0]
        assert list(condensed) == [
            "exp_id",
            "status",
            "model_type",
            "denoising_score",
            "is_trial",
            "failure_reason",
            "memory",
        ]
        assert list(condensed["memory"]) == ["hypothesis", "conclusion", "round_index"]

    def test_the_four_record_planner_prompt_matches_its_golden(self):
        bridge = BoundaryRecorderBridge()
        bridge.plan(**{**planner_fixture_kwargs(), "memory_history": _HISTORY_4})
        _method, _label, _system, user = bridge.captures[0]
        assert_golden(
            user,
            GOLDENS / "pb1_planner_history4_user.txt",
            surface="PB-1 planner user prompt (4-record condensed branch)",
        )


# ---------------------------------------------------------------------------
# 6. The renderers read the authority, not a copy of it
# ---------------------------------------------------------------------------


def test_renderers_read_their_declared_authority():
    """Reachability for each renderer: a renderer that returned a constant
    would satisfy every byte-equality test above under TIDMAD."""
    assert render_full_scope_segments(_Dataset(7, 11)) == 77
    assert render_builtin_model_roster({"wavenet": object(), "punet": object()}) == (
        "wavenet | punet"
    )
    assert render_gate_name_tokens(_HealthConfig(["a", "b"])) == {"a": "a", "b": "b"}


def test_the_focal_defaults_follow_LossConfig_when_it_changes(monkeypatch):
    """MUTATION TARGET: ``return ("0.5", "2.0")``.

    A hardcoded pair is indistinguishable from a correct render while
    ``LossConfig``'s defaults happen to be 0.5 and 2.0 — and a mutation sweep
    proved exactly that: replacing the field lookup with those literals
    survived every other test in this module. Comparing the renderer against
    ``LossConfig.model_fields[...].default`` did not help either: that is the
    same value from the same place, so it agrees with the literal too.

    The only assertion that separates them PERTURBS the authority. If the
    shipped focal defaults are ever retuned, the collapse-recovery advice
    ("reset to focal loss (alpha=…, gamma=…)") must move with them, or the
    prompt will tell the planner to reset to a configuration a reset does not
    produce.
    """
    from ml_models.models_format_sandbox import LossConfig

    monkeypatch.setattr(LossConfig.model_fields["alpha"], "default", 0.25)
    monkeypatch.setattr(LossConfig.model_fields["gamma"], "default", 3.5)
    assert render_focal_defaults() == ("0.25", "3.5")
