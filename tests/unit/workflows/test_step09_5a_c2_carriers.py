"""Step 09.5a C2 — the carrier contracts and the ownership guard.

Three carriers, three membership rules, and one structural boundary between the
immutable ones and the mutable one.

Defect only this file catches: **mutable cross-iteration state living in a
carrier that claims to be immutable** (or transit configuration). Nothing
behavioural would notice — the value would still arrive at the same place — but
the ownership boundary this whole milestone exists to establish would be gone,
and Step 10's new carried state would land on the wrong side of it.

The guard is deliberately DERIVED from ``ChainState``'s own fields rather than
hand-listed, so it cannot go stale when that carrier grows. A hand-maintained
deny list fails exactly on the field nobody remembered to add.
"""

from __future__ import annotations

import dataclasses
from collections import deque

import pytest

from core.chain_state import ChainState, chain_state_field_names
from workflows.run_bindings import WorkflowRunBindings, run_bindings_field_names
from workflows.run_config import WorkflowLaunchConfig, launch_config_field_names


class TestTheOwnershipBoundary:
    def test_no_field_name_is_shared_between_immutable_and_mutable_carriers(self):
        mutable = chain_state_field_names()
        assert not (mutable & run_bindings_field_names())
        assert not (mutable & launch_config_field_names())

    def test_bindings_reject_a_planted_chain_state_field(self):
        """Anti-vacuity. A guard that never fires is decoration.

        Planting a real ``ChainState`` field name on a bindings-shaped class
        must raise — this is the failure mode the guard exists for.
        """
        victim = next(iter(chain_state_field_names()))
        offending = dataclasses.make_dataclass(
            "PlantedBindings",
            [
                (f.name, f.type, dataclasses.field(default=None))
                for f in dataclasses.fields(WorkflowRunBindings)
            ]
            + [(victim, object, dataclasses.field(default=None))],
            bases=(),
            frozen=True,
            namespace={"__post_init__": WorkflowRunBindings.__post_init__},
        )
        with pytest.raises(TypeError, match="must not carry mutable chain state"):
            offending()

    def test_launch_config_rejects_a_planted_chain_state_field(self):
        """Amendment B's half of the same boundary."""
        victim = next(iter(chain_state_field_names()))
        offending = dataclasses.make_dataclass(
            "PlantedLaunchConfig",
            [(victim, object, dataclasses.field(default=None))],
            frozen=True,
            namespace={"__post_init__": WorkflowLaunchConfig.__post_init__},
        )
        with pytest.raises(TypeError, match="must not carry cross-iteration state"):
            offending()

    def test_the_guard_reads_the_live_chain_state_not_a_copy(self):
        """If ChainState grows a field, the forbidden set grows with it."""
        assert chain_state_field_names() == {f.name for f in dataclasses.fields(ChainState)}
        assert len(chain_state_field_names()) >= 11


class TestImmutability:
    def test_bindings_are_frozen(self):
        b = WorkflowRunBindings(workspace="/w", run_name="r", run_dir="/w/r")
        with pytest.raises(dataclasses.FrozenInstanceError):
            b.workspace = "/other"

    def test_launch_config_is_frozen(self):
        c = WorkflowLaunchConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.max_rounds = 99

    def test_chain_state_is_deliberately_mutable(self):
        """Mutation across iterations is the point; freezing it would force a
        rebuild per update and hide who owns the change."""
        s = ChainState.cold_start()
        s.best_score_overall = 1.0
        assert s.best_score_overall == 1.0


#: Transit fields declared on ``WorkflowLaunchConfig`` AFTER the Step 09.5a
#: refactor, with the default each was declared with. The pre-refactor golden
#: is HISTORY (the 72 values ``run_workflow`` carried at the C2 head) and is
#: never edited; a later addition is instead declared here, by hand, so the
#: two census tests below keep catching an undeclared field or a drifted
#: default while the historical record stays what it was.
#:
#: * ``experiment_arm`` — arXiv U1 (#254): the OPAQUE experiment-arm label,
#:   pure transit (the workflow locks it and forwards it; never interprets
#:   it, ruling R2). Default ``None`` = the unlabelled legacy run.
#: * ``baseline_isolation`` — arXiv U3 (#260): the WITHOUT arm's explicit
#:   behaviour flag (ruling R6), locked and forwarded to the interpreter,
#:   proposer and tuner inputs. Default ``False`` = no isolation.
#: * ``allowed_output_types`` — arXiv #259 (fleet ruling 2026-08-25): the
#:   run's declared output-type constraint, pure transit (forwarded post-hoc
#:   into ``ProposalInput``; the proposer's SCHEMA GATE enforces it — this
#:   layer never interprets it). Default ``None`` = unconstrained legacy.
#: Pre-refactor fields whose DECLARED DEFAULT deliberately changed after the
#: golden was recorded — the parallel slot to the additions dict (the golden
#: is history and is never edited). Each entry names its authority.
#:
#: * Lane F2 (campaign-portion authority, 2026-08-26): the three trial-side
#:   portions became TRI-STATE — a TYPED value is EXPERIMENT_FIXED (merged
#:   into the plan_overrides lock), ``None`` is AGENT_CONTROLLED. The old
#:   concrete 0.1 defaults were dead transit (no tuner consumer) that made
#:   "typed" indistinguishable from "defaulted", which is how the frozen
#:   campaign portions failed to reach execution.
#: * Repository separation (2026-08-31): literature-review science is owned by
#:   the caller. ``None`` keeps review disabled unless an enabled run supplies
#:   an explicit task-owned config; the framework ships no scientific default.
POST_REFACTOR_DEFAULT_CHANGES: dict[str, object] = {
    "trial_portion": None,
    "train_portion": None,
    "eval_portion": None,
    "lit_review_config_path": None,
}

#: * ``bypass_formal_time_budget_minutes`` — Lane F3 / F-BYPASS-WD-1: the
#:   elevated bypass ceiling, pure transit to the tuner input via the
#:   validator→tuner protocol. Default ``None`` = a qualified bypass grants
#:   NO extension (load-bearing safety semantics).
POST_REFACTOR_TRANSIT_ADDITIONS: dict[str, object] = {
    "training_validation_portion": None,
    # Operator-approved cooperative training, opt-in only (2026-09-18).
    "training_budget_reserve_fraction": None,
    "bypass_formal_time_budget_minutes": None,
    "experiment_arm": None,
    "baseline_isolation": False,
    "allowed_output_types": None,
    # D-BUD-6 (2026-08-26) — per-mode epoch ceilings; None = the
    # mode-agnostic max_epochs governs that role (legacy behavior).
    "trial_max_epochs": None,
    "formal_max_epochs": None,
    # Gold campaign (advice-invariant) — the advice artifact the launch
    # OBSERVED, as pure transit to `_workflow_lock_identity`. `None` is the
    # no-advice launch, which is what keeps the workspace lock byte-identical
    # for every run that declares no advice.
    "advice_path": None,
    "advice_sha256": None,
    # Generic VRAM-preflight watchdogs (2026-09-01). Pure transit from the
    # workflow to the isolated worker; defaults preserve the pre-feature
    # production adapter's 180 s per-forward and 900 s worker deadlines.
    "vram_probe_step_timeout_seconds": 180.0,
    "vram_preflight_total_timeout_seconds": 900.0,
    "vram_preflight_host_memory_limit_gb": None,
    # Unified workflow parameter rules (2026-09-01). The validated rules are
    # transit-only here; the planner owns their semantics and run identity.
    "workflow_parameter_rules": None,
    # One admission authority per candidate role. These fields are pure
    # workflow-to-tuner transport; the runtime policy owns enforcement.
    "trial_time_admission_source": "measured",
    "formal_time_admission_source": "measured",
    # PR #520 — caller-owned Formal training scope choice is transit to the
    # tuner; "operator" preserves the existing Formal training defaults.
    "formal_training_scope_source": "operator",
    # Caller-configurable measurement window; None retains runtime defaults.
    "runtime_verification_max_wall_seconds": None,
    # Data Analysis workflow integration (2026-09-15). Advice is transit-only
    # caller input and does not imply that the optional topology is enabled.
    "human_advice_analysis": None,
    # One optional inline source directive. Its exact content is pinned by
    # _workflow_lock_identity; None/auto do not perturb the legacy lock.
    "analysis_source_prompt": None,
    # Explicit workflow treatment; None preserves composition behavior.
    "data_analysis_enabled": None,
    # Per-sample output lifetime is caller transit, not a second DA switch.
    "retain_model_outputs": False,
    # Raw training checkpoint lifetime is independent of certified models.
    "retain_training_checkpoints": False,
    # PR-C — workflow-owned ordering of two independent evidence capabilities.
    "scientific_evidence_order": "analysis_then_literature",
}


class TestLaunchConfigIsTransitOnly:
    def test_it_carries_no_capability_reference(self):
        """Amendment B: capabilities live on the bindings carrier."""
        names = launch_config_field_names()
        assert "bridge_factory" not in names
        assert "sandbox_factory" not in names
        assert "measurement_capability" not in names

    def test_require_probe_runner_is_launch_config_not_a_capability(self):
        """Amendment A's reclassification, pinned.

        It is a plain bool read once. Putting it with the capability references
        would have been the "it shortens the signature" reasoning the amendment
        forbids.
        """
        assert "require_probe_runner" in launch_config_field_names()
        assert "require_probe_runner" not in run_bindings_field_names()

    def test_every_default_matches_the_pre_refactor_signature(self):
        """Amendment B: the carrier RESTATES no default.

        Defect this catches: a field's default silently drifting from the one
        ``run_workflow`` carried before C3 — which would change behaviour for
        every caller that omits it, invisibly, because both sides would look
        self-consistent.

        The comparison is against a golden recorded from the PRE-C3 signature
        (``git show`` of the C2 head), not against the live signature: after
        C3 the live signature no longer carries these 72 defaults, so it can no
        longer be the reference. Reading the old values from history is what
        keeps this test meaningful instead of tautological.
        """
        import ast
        import json
        from pathlib import Path

        golden = json.loads(
            (
                Path(__file__).parent / "goldens" / "step09_5a_pre_refactor_launch_defaults.json"
            ).read_text()
        )
        assert len(golden) == 72, "the pre-refactor default record is incomplete"

        mismatched = []
        for f in dataclasses.fields(WorkflowLaunchConfig):
            declared = (
                f.default_factory() if f.default_factory is not dataclasses.MISSING else f.default
            )
            if f.name in POST_REFACTOR_TRANSIT_ADDITIONS:
                # Declared AFTER the refactor: the golden cannot know it, so
                # its default is pinned here, by hand, at its declaration.
                expected = POST_REFACTOR_TRANSIT_ADDITIONS[f.name]
            elif f.name in POST_REFACTOR_DEFAULT_CHANGES:
                # Default DELIBERATELY changed after the golden (declared
                # above with its authority) — pinned by hand, so an
                # UNdeclared change still fails against the golden.
                expected = POST_REFACTOR_DEFAULT_CHANGES[f.name]
            elif f.name in golden:
                expected = ast.literal_eval(golden[f.name])
            else:
                mismatched.append(f"{f.name}: absent from the pre-refactor record")
                continue
            if declared != expected:
                mismatched.append(f"{f.name}: carrier {declared!r} != pre-refactor {expected!r}")
        assert not mismatched, mismatched

    def test_the_carrier_covers_the_whole_pre_refactor_transit_surface(self):
        """Every value that used to be a transit parameter still has a home —
        and nothing joins the carrier without being declared in
        ``POST_REFACTOR_TRANSIT_ADDITIONS`` with its pinned default."""
        import json
        from pathlib import Path

        golden = json.loads(
            (
                Path(__file__).parent / "goldens" / "step09_5a_pre_refactor_launch_defaults.json"
            ).read_text()
        )
        assert set(golden) | set(POST_REFACTOR_TRANSIT_ADDITIONS) == launch_config_field_names()
        assert not set(golden) & set(POST_REFACTOR_TRANSIT_ADDITIONS), (
            "a pre-refactor field cannot also be declared as a later addition"
        )


class TestBindingsMembership:
    def test_the_capability_references_are_exactly_the_three_audited_ones(self):
        """Amendment A: admitted individually, not as a group."""
        names = run_bindings_field_names()
        for capability in ("bridge_factory", "sandbox_factory", "measurement_capability"):
            assert capability in names

    def test_bindings_hold_the_locked_invariants(self):
        names = run_bindings_field_names()
        for locked in (
            "resolved_data_scope",
            "health_gate_enabled",
            "health_gate_files",
            "health_checks_config",
            "order_strategy_override",
            "file_order_override",
            "enable_structured_health_feedback",
            "run_invariants",
        ):
            assert locked in names, locked


class TestChainStateConstruction:
    def test_cold_start_is_the_only_default_authority(self):
        s = ChainState.cold_start()
        assert s.iteration_results == []
        assert s.best_score_overall is None
        assert s.chain_formal_incumbent_reference is None
        assert s.model_knowledge_cache == {}
        assert s.recent_tune_outputs.maxlen == 3

    def test_cold_start_seeds_the_vocabulary(self):
        s = ChainState.cold_start(vocab_seed=["a", "b"])
        assert s.current_runtime_vocab == ["a", "b"]

    def test_restored_vocabulary_beats_the_static_seed(self):
        """Without this priority every chain iteration resets to the seed —
        the empirical bug at docs/Consistent_growing_vocab_list.md §1.2."""
        s = ChainState.from_restored(vocab_seed=["seed"], restored_runtime_vocab=["restored"])
        assert s.current_runtime_vocab == ["restored"]

    def test_an_empty_restored_vocabulary_falls_back_to_the_seed(self):
        s = ChainState.from_restored(vocab_seed=["seed"], restored_runtime_vocab=[])
        assert s.current_runtime_vocab == ["seed"]

    def test_the_knowledge_cache_is_copied_not_aliased(self):
        """The workflow mutates this dict in place at iteration end."""
        caller = {"m": {"_stats": {}}}
        s = ChainState.from_restored(restored_model_knowledge_cache=caller)
        s.model_knowledge_cache["other"] = {}
        assert "other" not in caller

    def test_the_two_incumbent_like_fields_stay_separate(self):
        """They look alike and mean different things: best_score_overall is
        THIS execution's raw formal tracker and is never restored;
        chain_formal_incumbent_reference is the restored decision state."""
        s = ChainState.from_restored(restored_chain_incumbent_score=2.5)
        assert s.chain_formal_incumbent_reference == 2.5
        assert s.best_score_overall is None

    def test_record_tune_output_advances_both_collections(self):
        s = ChainState.cold_start()
        for i in range(5):
            s.record_tune_output(i)
        assert s.iteration_results == [0, 1, 2, 3, 4]
        assert list(s.recent_tune_outputs) == [2, 3, 4], "bounded window keeps the last three"

    def test_a_prepopulated_recent_window_keeps_its_bound(self):
        s = ChainState.from_restored(recent_tune_outputs=deque([1, 2], maxlen=3))
        s.record_tune_output(3)
        s.record_tune_output(4)
        assert list(s.recent_tune_outputs) == [2, 3, 4]
