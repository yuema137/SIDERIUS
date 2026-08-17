"""Step 07 PR 07b — C5: direction, metric identity and training dynamics, rendered.

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.7 (the declared byte deltas), §3.8 (diagnosis
rendering), §3.9 (the bridge contract), §6 rung **B-07b-2**, §8 rows 9/10/11.

This is the ONLY commit in 07b that changes what the LLM reads on purpose, so
the claims are about MEANING, not byte-stability:

1. **Direction comes from the declaration.** "maximize", "GOOD if HIGHER",
   "beats the best score" were TIDMAD's convention stated as the framework's.
   Under a lower-is-better metric they are not incomplete — they are backwards,
   and would have the reflector praise every regression.

2. **The metric has an identity.** The record field stays ``denoising_score``
   (D1 is not 07b's), but the prompt now also says what that field measures.

3. **Training dynamics are FACTS.** 07a deliberately derived no calibrated
   label, because the threshold for "overfitting" is not something the
   framework can know. The prompts previously supplied one anyway, as a
   hand-written rule. The renderers state the trajectory and let the LLM
   judge — and a vocabulary guard keeps it that way.

4. **Persistence is still not visibility.** The planner gets an owned summary;
   the raw ``training_history`` / ``training_diagnosis`` payloads stay out of
   the history JSON. The reflector gets the diagnosis ONLY — never the history
   — and ``actual_results`` / ``reflection_context`` keep their frozen 9 and 23.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.prompt_templates.tuner.rendering import (
    CALIBRATED_LABELS,
    render_metric_direction_words,
    render_metric_identity_line,
    render_planner_dynamics_block,
    render_reflector_dynamics_block,
    render_training_dynamics_line,
)
from agent.schemas.training_diagnosis import TrainingDiagnosis
from execute_tools.evaluation_metric import MetricSpec
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec
from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import (
    _HISTORY_3,
    _REFLECT_DIAGNOSIS,
    planner_fixture_kwargs,
    reflect_fixture_args,
    reflect_fixture_kwargs,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = REPO_ROOT / "examples"


def _pack_spec(pack: str, filename: str) -> MetricSpec:
    """A MetricSpec loaded from a persistent example pack's DECLARED metric.

    Not a fixture written for this test: these are the packs' own
    ``declared/metric_*.json`` files, so the rung consumes the same
    declaration a real Pets/DAVIS run would (PR0; §3.12).
    """
    raw = json.loads((EXAMPLES / pack / "declared" / filename).read_text(encoding="utf-8"))
    from execute_tools.evaluation_metric import PresenceScoreabilityContract

    return MetricSpec(
        id=raw["id"],
        direction=raw["direction"],
        aggregation=raw["aggregation"],
        transform=raw["transform"],
        transform_params=raw["transform_params"],
        references=tuple(raw["references"]),
        scoreability=PresenceScoreabilityContract(),
    )


def _pack_diagnosis(pack: str) -> TrainingDiagnosis:
    raw = json.loads(
        (EXAMPLES / pack / "expected" / "training_diagnosis_l1_fixture.json").read_text(
            encoding="utf-8"
        )
    )
    return TrainingDiagnosis.model_validate(raw["training_diagnosis"])


# ---------------------------------------------------------------------------
# 1. Direction words and metric identity
# ---------------------------------------------------------------------------


class TestDirectionAndIdentity:
    def test_the_words_invert_with_the_declaration(self):
        assert render_metric_direction_words(shipped_spec()) == {
            "verb": "maximize",
            "comparative": "higher",
            "antonym": "lower",
        }
        assert render_metric_direction_words(direction_only_spec()) == {
            "verb": "minimize",
            "comparative": "lower",
            "antonym": "higher",
        }

    def test_the_identity_line_names_the_metric_and_its_direction(self):
        assert render_metric_identity_line(shipped_spec()) == (
            "golden metric `tidmad_denoising_score` (higher is better)"
        )
        assert render_metric_identity_line(
            _pack_spec("oxford_iiit_pet", "metric_accuracy.json")
        ) == ("golden metric `accuracy` (higher is better)")
        assert render_metric_identity_line(
            _pack_spec("davis_future_prediction", "metric_mse.json")
        ) == ("golden metric `mse` (lower is better)")

    def test_an_unusual_id_renders_verbatim_inside_backticks(self):
        spec = shipped_spec().model_copy(update={"id": "psnr@4x_v2"})
        assert "`psnr@4x_v2`" in render_metric_identity_line(spec)


# ---------------------------------------------------------------------------
# 2. The training-dynamics line
# ---------------------------------------------------------------------------

_OK = _REFLECT_DIAGNOSIS


class TestTrainingDynamicsLine:
    def test_the_planner_line_carries_the_objective_family_label(self):
        assert render_training_dynamics_line(_OK, "focal").startswith("[focal] ")

    def test_the_reflector_line_omits_it(self):
        """Not an oversight (§3.8): the reflector's ``actual_results`` already
        carries this round's ``final_loss`` / ``loss_history`` under the run's
        own loss config, so transporting the objective family again would widen
        the frozen bridge surface to restate what is already there."""
        assert not render_training_dynamics_line(_OK, None).startswith("[")

    def test_an_absent_history_says_so_rather_than_rendering_nothing(self):
        """A legacy record with no history must not read as 'the training was
        unremarkable'."""
        absent = TrainingDiagnosis(state="absent", validation_state="absent")
        assert render_training_dynamics_line(absent) == "training dynamics: none recorded"
        assert render_training_dynamics_line(None) == "training dynamics: none recorded"

    def test_a_non_finite_history_says_so(self):
        invalid = TrainingDiagnosis(state="invalid", validation_state="absent")
        assert render_training_dynamics_line(invalid) == "training dynamics: invalid (non-finite)"

    def test_a_train_only_history_renders_without_inventing_validation(self):
        train_only = TrainingDiagnosis(
            state="ok",
            validation_state="absent",
            epochs_completed=3,
            train_first=2.9,
            train_last=2.1,
            train_trend="decreasing",
        )
        line = render_training_dynamics_line(train_only)
        assert "train 2.90->2.10 (decreasing, 3 ep)" in line
        assert "val not recorded" in line

    def test_an_incomparable_gap_says_WHY_it_is_absent(self):
        """``gap n/a`` alone would read as a missing measurement. It is not:
        the two curves were measured on different objectives, and 07a refused
        to subtract them."""
        incomparable = TrainingDiagnosis(
            state="ok",
            validation_state="present",
            comparability="not_established",
            train_first=2.9,
            train_last=2.1,
            train_trend="decreasing",
            validation_first=3.0,
            validation_last=2.6,
            validation_trend="decreasing",
        )
        assert "gap n/a (not comparable)" in render_training_dynamics_line(incomparable)

    def test_degradation_after_the_best_epoch_is_stated_as_a_number(self):
        drifted = _OK.model_copy(
            update={"best_validation_epoch": 3, "final_vs_best_validation_degradation": 0.07}
        )
        line = render_training_dynamics_line(drifted)
        assert "best ep 3" in line
        assert "+0.07 after best" in line

    @pytest.mark.parametrize("word", CALIBRATED_LABELS)
    def test_no_calibrated_label_is_ever_rendered(self, word):
        """MUTATION TARGET: a renderer that helpfully concludes "overfitting".

        07a produced facts precisely so the LLM judges with the run's context in
        hand. A renderer that pre-labels the curve silently picks a threshold
        nobody declared — and hides that it did.
        """
        drifted = _OK.model_copy(
            update={"best_validation_epoch": 0, "final_vs_best_validation_degradation": 5.0}
        )
        for diagnosis in (_OK, drifted):
            for kind in (None, "focal"):
                assert word not in render_training_dynamics_line(diagnosis, kind).lower()
        assert word not in render_reflector_dynamics_block(drifted).lower()


class TestPlannerDynamicsBlock:
    def test_one_line_per_record_including_those_without_a_diagnosis(self):
        """The block's shape must not depend on how many rounds happened to
        record a history, or its absence would itself carry meaning."""
        block = render_planner_dynamics_block(_HISTORY_3)
        assert block.startswith("### Training dynamics (last 3 experiments)")
        assert len(block.splitlines()) == 4
        assert block.count("none recorded") == 2
        assert "[focal] train 0.02->0.01" in block

    def test_an_empty_history_renders_nothing_at_all(self):
        assert render_planner_dynamics_block([]) == ""


# ---------------------------------------------------------------------------
# 3. The bridge contract — fail closed, and the declared additive surface
# ---------------------------------------------------------------------------


class TestBridgeFailsClosed:
    def test_plan_without_a_metric_spec_refuses(self):
        """MUTATION TARGET: defaulting to "maximize".

        A default is not a smaller version of the truth here — it inverts the
        goal for a minimised metric, and every TIDMAD test would still pass.
        """
        kwargs = {k: v for k, v in planner_fixture_kwargs().items() if k != "metric_spec"}
        bridge = BoundaryRecorderBridge()
        with pytest.raises(ValueError, match="metric_spec"):
            bridge.plan(**kwargs)
        assert bridge.captures == []

    def test_reflect_without_a_metric_spec_refuses(self):
        bridge = BoundaryRecorderBridge()
        kwargs = {k: v for k, v in reflect_fixture_kwargs().items() if k != "metric_spec"}
        with pytest.raises(ValueError, match="metric_spec"):
            bridge.reflect(*reflect_fixture_args(), **kwargs)
        assert bridge.captures == []


# ---------------------------------------------------------------------------
# 4. Boundary — owned summary in, raw payload out
# ---------------------------------------------------------------------------


def _render_planner(**overrides) -> tuple[str, str]:
    bridge = BoundaryRecorderBridge()
    bridge.plan(**{**planner_fixture_kwargs(), **overrides})
    _method, _label, system, user = bridge.captures[0]
    return system, user


def _render_reflector(**overrides) -> tuple[str, str]:
    bridge = BoundaryRecorderBridge()
    bridge.reflect(*reflect_fixture_args(), **{**reflect_fixture_kwargs(), **overrides})
    _method, _label, system, user = bridge.captures[0]
    return system, user


class TestBoundary:
    def test_the_planner_sees_the_summary_and_not_the_raw_payload(self):
        _system, user = _render_planner()
        assert "### Training dynamics (last 3 experiments)" in user
        assert "[focal] train 0.02->0.01" in user
        for raw in ("training_history", "training_diagnosis", "metric_result", "metric_refusal"):
            assert raw not in user
        # ...and values that exist ONLY inside those payloads.
        assert "objective_config_fingerprint" not in user
        assert "flat_rel_tol" not in user

    def test_the_reflector_sees_the_diagnosis_and_never_the_history(self):
        _system, user = _render_reflector()
        assert "### TRAINING DYNAMICS (this experiment)" in user
        assert "train 0.02->0.01" in user
        for raw in ("training_history", "training_diagnosis", "objective_kind"):
            assert raw not in user

    def test_a_record_with_no_diagnosis_still_renders_the_block(self):
        plain = [{k: v for k, v in r.items() if k != "training_diagnosis"} for r in _HISTORY_3]
        _system, user = _render_planner(memory_history=plain)
        assert "### Training dynamics (last 3 experiments)" in user
        assert user.count("none recorded") == 3


# ---------------------------------------------------------------------------
# 5. Rung B-07b-2 — the rendering axis across three declarations
# ---------------------------------------------------------------------------

_LOWER = direction_only_spec()
_PETS = None  # bound below
_DAVIS = None


class TestB07b2RenderingAxis:
    """Scoped assertions (Step-01 §13.4): the rung asserts the DERIVED blocks,
    never whole-prompt absence.

    Deliberately NOT asserted: "classification phrasing" / "regression
    phrasing". ``MetricSpec`` owns no task type and no landed authority supplies
    that word to the tuner prompt, so claiming it would be asserting a fact the
    system does not have (§6, corrected at revision 2).
    """

    @pytest.mark.parametrize(
        ("spec_factory", "expected_verb", "expected_comparative"),
        [
            (shipped_spec, "maximize", "higher"),
            (direction_only_spec, "minimize", "lower"),
            (lambda: _pack_spec("oxford_iiit_pet", "metric_accuracy.json"), "maximize", "higher"),
            (lambda: _pack_spec("davis_future_prediction", "metric_mse.json"), "minimize", "lower"),
        ],
        ids=["tidmad", "lower", "pets_accuracy", "davis_mse"],
    )
    def test_the_planner_states_the_declared_direction(
        self, spec_factory, expected_verb, expected_comparative
    ):
        spec = spec_factory()
        system, _user = _render_planner(metric_spec=spec)
        assert f"Your goal is to {expected_verb} the `denoising_score` metric" in system
        assert f"(golden metric `{spec.id}` ({expected_comparative} is better))" in system
        assert f"Goal: {expected_verb} the score" in system
        assert f"does not\n  move toward {expected_comparative}" in system

    @pytest.mark.parametrize(
        ("spec_factory", "good", "bad"),
        [
            (shipped_spec, "HIGHER", "LOWER"),
            (direction_only_spec, "LOWER", "HIGHER"),
            (lambda: _pack_spec("davis_future_prediction", "metric_mse.json"), "LOWER", "HIGHER"),
        ],
        ids=["tidmad", "lower", "davis_mse"],
    )
    def test_the_reflector_judging_rule_follows_the_declaration(self, spec_factory, good, bad):
        """Under a minimised metric the shipped wording would have the reflector
        call every regression a good result."""
        system, _user = _render_reflector(metric_spec=spec_factory())
        assert f"A result is GOOD if its denoising_score is {good} than the best score" in system
        assert f"A result is BAD if it is {bad} than most previous scores" in system

    def test_under_a_lower_metric_the_derived_blocks_carry_no_higher_residue(self):
        """SCOPED: the derived blocks only. The prompt still contains the word
        "higher" elsewhere (e.g. "higher dropout"), and asserting whole-prompt
        absence is a test-design error this project has recorded before."""
        system, _user = _render_planner(metric_spec=_LOWER)
        goal_line = next(ln for ln in system.splitlines() if ln.startswith("Your goal is to"))
        assert "minimize" in goal_line and "lower is better" in goal_line
        assert "maximize" not in goal_line and "higher is better" not in goal_line

        reflector, _ru = _render_reflector(metric_spec=_LOWER)
        judging = [ln for ln in reflector.splitlines() if ln.startswith("- A result is")]
        assert any("GOOD" in ln and "LOWER" in ln for ln in judging)
        assert not any("GOOD" in ln and "HIGHER" in ln for ln in judging)

    @pytest.mark.parametrize(
        "pack", ["oxford_iiit_pet", "davis_future_prediction"], ids=["pets", "davis"]
    )
    def test_a_pack_fixture_diagnosis_renders_at_both_surfaces(self, pack):
        """L1 evidence: the packs' own 07a expected fixtures render through the
        production renderers. No real Pets/DAVIS execution — that is D14."""
        diagnosis = _pack_diagnosis(pack)
        planner_line = render_training_dynamics_line(diagnosis, "cross_entropy")
        reflector_block = render_reflector_dynamics_block(diagnosis)
        assert planner_line.startswith("[cross_entropy] train ")
        assert "val " in planner_line
        assert "### TRAINING DYNAMICS (this experiment)" in reflector_block
        for word in CALIBRATED_LABELS:
            assert word not in planner_line.lower()
            assert word not in reflector_block.lower()


# ---------------------------------------------------------------------------
# 6. The field name survives — D1 is not 07b's
# ---------------------------------------------------------------------------


def test_the_denoising_score_field_name_is_still_what_the_prompt_names():
    """Q-07b-3: the metric IDENTITY was ADDED beside the field noun, not
    substituted for it. The LLM reads `denoising_score` out of the history
    JSON, and renaming the field is D1's decision."""
    system, _user = _render_planner(metric_spec=direction_only_spec())
    assert "`denoising_score`" in system
