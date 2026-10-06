"""
FU-10 — plan_overrides fail-fast hardening.

The operator override lock is a contract:
  * unknown keys fail at SCHEMA validation (input construction — the
    earliest practical point), with keys normalized to alias form so the
    tuner's by_alias merge replaces fields instead of adding stray keys;
  * the merged effective plan is revalidated every round, and an invalid
    result raises PlanOverridesError that terminates the run — it is never
    recorded as a retryable attempt failure, and the run never continues
    on the unclamped LLM plan.
See docs/design/enable_partial_file_list.md (Follow-up tracker, FU-10).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    PlanOverridesError,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.experiment_plans import make_scope_plan
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    _mock_run_skill,
    _synth_reference,
)


def _input(
    tmp_path, *, max_rounds: int = 1, is_trial: bool = True, **kwargs
) -> HyperparamTuningInput:
    return HyperparamTuningInput(
        planner_strategy="native-timing-v1",
        model_type="punet",
        file_index=6,
        max_rounds=max_rounds,
        is_trial=is_trial,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="fu10_test"),
        ),
        progress_bar=False,
        **kwargs,
    )


class TestSchemaKeyValidation:
    def test_unknown_key_fails_at_construction(self, tmp_path):
        with pytest.raises(ValidationError, match="unknown ExperimentPlan field"):
            _input(tmp_path, plan_overrides={"not_a_plan_field": 1})

    def test_valid_python_names_pass(self, tmp_path):
        # force_formal_round=False: the documented escape — with the helper's
        # max_rounds=1 default the F14 satisfiability validator would
        # (correctly) refuse trial-scoped overrides that could never apply.
        inp = _input(
            tmp_path,
            plan_overrides={"trial_portion": 0.05, "is_trial": True},
            force_formal_round=False,
        )
        assert inp.plan_overrides == {"trial_portion": 0.05, "is_trial": True}

    def test_alias_normalization_both_directions(self, tmp_path):
        # Python name normalizes to the alias the by_alias dump emits...
        inp = _input(tmp_path, plan_overrides={"model_cfg": {"depth": 2}})
        assert inp.plan_overrides == {"model_config": {"depth": 2}}
        # ...and the alias itself is accepted verbatim.
        inp = _input(tmp_path, plan_overrides={"model_config": {"depth": 2}})
        assert inp.plan_overrides == {"model_config": {"depth": 2}}

    def test_name_plus_alias_collision_rejected(self, tmp_path):
        with pytest.raises(ValidationError, match="twice"):
            _input(
                tmp_path,
                plan_overrides={"model_cfg": {"depth": 2}, "model_config": {"depth": 3}},
            )

    def test_empty_overrides_unchanged(self, tmp_path):
        assert _input(tmp_path).plan_overrides == {}


class TestMergeFailFast:
    """An invalid effective plan terminates the run — never a silent
    fallback, never a retryable attempt failure."""

    def _run_agent(self, tmp_path, plan_overrides):
        with (
            patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
            patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
            patch(
                "nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill
            ),
            patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
            patch(
                "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
                return_value=_synth_reference(),
            ),
            patch("os.path.exists", return_value=True),
            tempfile.TemporaryDirectory() as configs_dir,
        ):
            mock_brain = MockBridge.return_value
            mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
            mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

            mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

            saved_records: list[dict] = []
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
            mock_sandbox.save_record.side_effect = saved_records.append
            mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
            stub_scoring(mock_sandbox, [1.0] * 20, 1.5)

            agent = HyperparamTuningAgent()
            # force_formal_round=False so the F14 satisfiability validator
            # admits the trial-scoped override — this class tests the
            # MERGE-time failure, which requires the override to be
            # applicable in the first place.
            inp = _input(tmp_path, plan_overrides=plan_overrides, force_formal_round=False)
            with pytest.raises(PlanOverridesError, match="never silently released"):
                agent.run(inp)
            return mock_brain, saved_records

    def test_invalid_value_terminates_without_retry(self, tmp_path):
        # trial_portion=5.0 fails ExperimentPlan validation after the merge.
        mock_brain, saved_records = self._run_agent(tmp_path, {"trial_portion": 5.0})
        # Exactly ONE plan call: the error propagated instead of burning
        # the attempt-retry budget on a deterministic config error.
        assert mock_brain.plan.call_count == 1
        # And it was never recorded as a retryable attempt failure.
        assert not any(r.get("record_type") == "attempt_failure" for r in saved_records)


class TestF14TrialScopedOverrideSatisfiability:
    """Lane F / F14 (fresh-user witness, 2026-08-26): ``--trial_portion 1.0``
    printed "Plan overrides applied" and trained on 6 of 64 rows. Mechanism:
    the last-round force (``force_formal_round`` default True) flips the
    only round of a ``max_rounds=1`` run to FORMAL, and formal workload
    comes from ``formal_portion`` (default 0.1) — the override applied to
    zero rounds, silently. These tests pin the refusal, the escape hatches,
    and the disclosure; each names the defect only it catches."""

    def test_zero_trial_round_combination_refuses_at_construction(self, tmp_path):
        """The defect only this catches: the F14 witness configuration
        constructing successfully again — an override that can never apply,
        acknowledged by a print that says it did. Fails by: the input
        validating."""
        with pytest.raises(ValidationError, match="zero rounds"):
            _input(tmp_path, plan_overrides={"is_trial": True, "trial_portion": 1.0})

    def test_multi_round_run_accepts_the_same_overrides(self, tmp_path):
        """The defect only this catches: the refusal over-firing on the
        LEGITIMATE production shape (trial rounds exist; only the last is
        formal-forced) — which would break every real chain launch. Fails
        by: construction refusing at max_rounds=3."""
        inp = _input(
            tmp_path, max_rounds=3, plan_overrides={"is_trial": True, "trial_portion": 1.0}
        )
        assert inp.plan_overrides["trial_portion"] == 1.0

    def test_chain_shaped_single_round_run_is_immune_the_q4_shape(self, tmp_path):
        """The Q4-immunity pin (supervisor ruling, 2026-08-26) — the defect
        only this catches: the qualification lane's minimum-lifecycle shape
        (the CHAIN path: ``is_trial`` as the INPUT FIELD, ``plan_overrides``
        EMPTY, ``max_rounds=1``, ``force_formal_round`` at its default True)
        being refused. Today that immunity is an emergent property of two
        same-named ``--is_trial`` flags on two surfaces agreeing by accident
        of history — the chain launcher (BooleanOptionalAction default True,
        which NEVER auto-bundles overrides) vs the tuner node CLI
        (store_true default False, which bundles ONLY when explicitly
        typed). Someone "harmonising" the two definitions later must trip
        THIS test instead of finding out on the qualification pod. Fails
        by: construction refusing."""
        # The shape lives in the CALL (explicit kwargs, NO plan_overrides
        # passed, force_formal_round left at its schema default True); the
        # load-bearing check is the EXPLICIT no-raise below — reading the
        # four values back from the constructed input would compare the
        # schema to itself (review NOTE-d / CLAUDE.md).
        try:
            _input(tmp_path, max_rounds=1, is_trial=True)
        except ValidationError as exc:
            pytest.fail(f"the Q4 chain shape must CONSTRUCT, got a refusal: {exc}")

    def test_no_force_formal_escape_is_honored(self, tmp_path):
        """The defect only this catches: the refusal ignoring the schema's
        own documented escape (``force_formal_round=False`` exists precisely
        so the final round honors the planner's mode). Fails by: refusing
        despite the escape."""
        inp = _input(
            tmp_path,
            force_formal_round=False,
            plan_overrides={"is_trial": True, "trial_portion": 1.0},
        )
        assert inp.plan_overrides["is_trial"] is True


class TestF14ModeBoundaryPropagation:
    """The invariant, per leg: a requested value reaches execution EXACTLY
    (trial), is transformed by a DOCUMENTED resolver (formal — now
    disclosed per round), or is EXPLICITLY REFUSED (the class above)."""

    @staticmethod
    def _plan(**kw):
        return make_scope_plan(**kw)

    @staticmethod
    def _agent_input(tmp_path, **kw):
        return _input(tmp_path, force_formal_round=False, **kw)

    def test_trial_mode_receives_the_override_exactly(self, tmp_path):
        """The exact-arrival leg — the defect only this catches: a resolver
        between the overridden plan and the trial TrialConfig mutating the
        operator's 1.0 (any clamp, default, or substitution). Fails by:
        cfg["trial_portion"] != 1.0."""
        from nodes.ml_hyperparameter_tune_agent.policy import (
            _apply_plan_overrides,
            _resolve_sample_set_cfg,
        )

        agent_input = self._agent_input(tmp_path)
        plan = _apply_plan_overrides(
            self._plan(trial_portion=0.1), {"is_trial": True, "trial_portion": 1.0}
        )
        assert plan.trial_portion == 1.0, "override must land on the plan (precondition)"
        cfg = _resolve_sample_set_cfg("trial", agent_input, plan)
        assert cfg["trial_portion"] == 1.0

    def test_formal_mode_sources_formal_portion_not_the_override(self, tmp_path):
        """THE F14 mechanism, pinned as designed-and-documented — the defect
        only this catches: someone "fixing" F14 by making the operator's
        trial override leak into FORMAL workload, silently breaking the
        cross-architecture comparability contract in the other direction.
        The witness's 6-of-64 rows = THIS line sourcing formal_portion=0.1.
        Fails by: the override (1.0) winning in formal mode."""
        from nodes.ml_hyperparameter_tune_agent.policy import (
            _apply_plan_overrides,
            _resolve_sample_set_cfg,
        )

        agent_input = self._agent_input(tmp_path)
        assert agent_input.formal_portion == 0.1, "the witness's default (precondition)"
        plan = _apply_plan_overrides(
            self._plan(trial_portion=0.1), {"is_trial": True, "trial_portion": 1.0}
        )
        cfg = _resolve_sample_set_cfg("formal", agent_input, plan)
        assert cfg["trial_portion"] == 0.1
        assert cfg["trial_portion"] == agent_input.formal_portion

    def test_formal_round_disclosure_names_the_discarded_keys(self, tmp_path, capsys):
        """The documented-resolver leg — the defect only this catches: the
        disclosure going silent again (the exact silence that let the F14
        witness mis-attribute the value), or firing on rounds where the
        override DOES govern. Fails by: no line on formal, or a line on
        trial / override-less inputs."""
        from nodes.ml_hyperparameter_tune_agent.policy import (
            _disclose_inapplicable_trial_overrides,
        )

        with_overrides = self._agent_input(
            tmp_path, plan_overrides={"is_trial": True, "trial_portion": 1.0}
        )
        line = _disclose_inapplicable_trial_overrides("formal", with_overrides)
        assert line is not None
        assert "'is_trial'" in line and "'trial_portion'" in line
        assert "formal_portion=0.1" in line
        assert line in capsys.readouterr().out

        assert _disclose_inapplicable_trial_overrides("trial", with_overrides) is None
        without = self._agent_input(tmp_path)
        assert _disclose_inapplicable_trial_overrides("formal", without) is None


class TestF14ReviewBlockers:
    """The independent review's B1/C3/C4, each pinned so it cannot regress."""

    def test_single_file_mode_is_not_refused_and_applies_the_override(self, tmp_path):
        """Reviewer B1 — the defect only this catches: the refusal firing on
        a configuration where the override DEMONSTRABLY applies. With
        is_trial=False the round resolves to SINGLE_FILE mode, whose branch
        READS plan.trial_portion / plan.train_portion — so
        is_trial=False + max_rounds=1 + a trial_portion override must
        CONSTRUCT, and the resolved cfg must carry the overridden value.
        Fails by: construction refusing (the B1 over-fire), or the value
        not arriving."""
        from nodes.ml_hyperparameter_tune_agent.policy import (
            _apply_plan_overrides,
            _resolve_sample_set_cfg,
        )

        inp = _input(tmp_path, is_trial=False, plan_overrides={"trial_portion": 0.5})
        plan = _apply_plan_overrides(make_scope_plan(trial_portion=0.1), inp.plan_overrides)
        cfg = _resolve_sample_set_cfg("single_file", inp, plan)
        assert cfg["trial_portion"] == 0.5, "single_file must read the OVERRIDDEN value"

    def test_the_guarded_set_covers_the_resolvers_formal_replacement(self, tmp_path):
        """Reviewer C4, as a CONCEPT test — the defect only this catches:
        the resolver's formal branch replacing a plan field that the
        guarded set does not contain (F14 one key over: train_portion was
        exactly that). Asserts every key the formal branch REPLACES is in
        TRIAL_SCOPED_OVERRIDE_KEYS, so adding a sixth replaced field
        without widening the authority turns this RED. Fails by: a
        replaced key outside the set."""
        from agent.schemas.hyperparam_tuning import TRIAL_SCOPED_OVERRIDE_KEYS
        from nodes.ml_hyperparameter_tune_agent.policy import _resolve_sample_set_cfg

        inp = _input(tmp_path, max_rounds=3)
        cfg = _resolve_sample_set_cfg("formal", inp, make_scope_plan())
        # SRI-3 (review NOTE-a): the subset relation is VACUOUSLY true on an
        # empty cfg — assert the population, or "no violations" and
        # "nothing to look at" are indistinguishable.
        assert len(cfg) == 5
        assert set(cfg.keys()) <= TRIAL_SCOPED_OVERRIDE_KEYS
        # The authority itself, hardcoded (never read back from the resolver):
        assert TRIAL_SCOPED_OVERRIDE_KEYS == {
            "is_trial",
            "trial_strategy",
            "trial_portion",
            "train_portion",
            "eval_strategy",
            "eval_portion",
        }

    def test_train_portion_override_refuses_in_the_zero_trial_round_shape(self, tmp_path):
        """Reviewer C4's concrete instance — the defect only this catches:
        `--plan_overrides '{"train_portion": 1.0}'` surviving the
        zero-trial-round refusal (it used to: the old 3-key set was the
        CLI bundle, not the resolver's discard set). Fails by: the input
        constructing."""
        with pytest.raises(ValidationError, match="zero rounds"):
            _input(tmp_path, plan_overrides={"train_portion": 1.0})

    def test_the_disclosure_is_reachable_from_prepare_attempt(self):
        """Reviewer C3 (CLAUDE.md reachability) — the defect only this
        catches: the ONE production call at planning.py's mode boundary
        being deleted while every behavior test calls the helper DIRECTLY
        (the reviewer proved 1474 tests stay green across exactly that
        deletion). Mirrors the F5 half's wiring census, AST-based. Fails
        by: no Call to _disclose_inapplicable_trial_overrides inside
        prepare_attempt."""
        import ast

        src = (
            Path(__file__).resolve().parents[4]
            / "src/nodes"
            / "ml_hyperparameter_tune_agent"
            / "planning.py"
        ).read_text()
        calls: list[int] = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == "prepare_attempt":
                calls.extend(
                    sub.lineno
                    for sub in ast.walk(node)
                    if isinstance(sub, ast.Call)
                    and getattr(sub.func, "id", "") == "_disclose_inapplicable_trial_overrides"
                )
        assert calls, (
            "the disclosure helper is DEFINED but no longer CALLED from "
            "prepare_attempt — the DOCUMENTED leg of F14 is severed in production"
        )

    def test_single_file_round_disclosure_names_the_forced_keys_only(self, tmp_path):
        """Review NOTE-b — the defect only this catches: the B1 fix exempted
        is_trial=False from the refusal (correctly), which is exactly the
        condition reaching SINGLE_FILE mode — where trial_strategy /
        eval_strategy are forced to 'snapshot' and eval_portion to 1.0. If
        the disclosure stays formal-only, three keys are silently discarded
        there: F14's own class, in the PR that closes F14. Fails by: no
        line for single_file, the forced keys unnamed, or the APPLYING keys
        (trial_portion/train_portion) wrongly named as discarded."""
        from nodes.ml_hyperparameter_tune_agent.policy import (
            _disclose_inapplicable_trial_overrides,
        )

        inp = _input(
            tmp_path,
            is_trial=False,
            plan_overrides={
                "trial_strategy": "anchors",
                "eval_portion": 0.2,
                "trial_portion": 0.5,
            },
        )
        line = _disclose_inapplicable_trial_overrides("single_file", inp)
        assert line is not None
        assert "'trial_strategy'" in line and "'eval_portion'" in line
        assert "'trial_portion'" not in line, "trial_portion APPLIES in single_file"
        assert "SINGLE_FILE" in line


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
