"""B-C4a0 — the extracted tuner control boundary.

`run()` is 2,300+ lines and sits on pyright's strict complexity ceiling:
past it the checker abandons the whole function, so every annotation
inside the tuner's main method goes unverified. B-C4 adds a refusal path
to exactly that method. This extracts the surfaces admission needs so it
has somewhere to live other than another `if`.

The tests here are about the *boundary*, not the arithmetic: that the
helpers are pure, that production actually reaches them, that they did
not take ownership of anything `run()` still has to release, and that
they remain substitutable by `unittest.mock.patch`.
"""

from __future__ import annotations

import ast
import gc
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from execute_tools.health_checks.schemas import GateAction
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    INFRASTRUCTURE_FAILURE_STATUS,
    RESOURCE_ADMISSION_REASONS,
    RESOURCE_ADMISSION_STATUS,
    RoundDecision,
    _build_execution_failure_record,
    _build_resource_admission_record,
    _build_skip_record,
    _decide_round_outcome,
    _emit_record,
)
from tests.helpers.tuner_source import tuner_node_source

#: The per-round transients `run()` releases at the end of every round.
#:
#: Step 07 PR 07b, C7d changed WHICH names carry the round's large objects,
#: not the property being defended. `file_vector` and `final_scalar` are now
#: locals of the execution phase and are freed when it returns, so `run()` has
#: nothing to delete; the objects the round still holds arrive on the two
#: carriers, which is why those are released in their place.
CLEANUP_OWNED_NAMES = (
    "train_results",
    "score_results",
    "score_table",
    "reflect_results",
    "memory_history",
    "prepared",
    "executed",
)

#: Released by returning rather than by `del` — see above. Pinned so the
#: transition is a stated fact: if either of these is ever re-bound in `run()`
#: it needs a `del` again, and this test says so.
PHASE_LOCAL_RELEASED_NAMES = ("file_vector", "final_scalar")

#: The large objects no extracted helper may take ownership of. Unchanged by
#: the decomposition — the risk is a helper capturing one, and that risk does
#: not care which frame currently binds it.
LEAK_FORBIDDEN_NAMES = (
    "train_results",
    "score_results",
    "score_table",
    "file_vector",
    "final_scalar",
    "reflect_results",
    "memory_history",
)

IDENTITY = dict(
    exp_id="e1",
    model_type="wavenet",
    file_index=0,
    record_params={"batch_size": 4},
    expert_advice_str="none",
    hypothesis="fixture",
    round_index=2,
    attempt_in_round=1,
)


def _tree() -> ast.Module:
    # The node, not one of its files: C7 split the tuner into a main module
    # plus node-local submodules, and every function below is still the
    # node's. Scanning one file would silently stop finding them.
    return ast.parse(tuner_node_source())


def _fn(name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(_tree()) if isinstance(n, ast.FunctionDef) and n.name == name)


# ---------------------------------------------------------------------
# C1 — cleanup ownership stays in run()
# ---------------------------------------------------------------------


class TestCleanupOwnership:
    """`run()` releases seven large transients per round under
    `suppress(NameError)`. If an extraction moves one into a helper's
    frame, the `del` becomes a silent no-op — the exception is
    swallowed — and the object stays alive. That is visible as RSS
    growth across rounds and invisible to every behavioural test, which
    is exactly why it needs its own guard."""

    def test_run_still_binds_and_releases_all_seven(self):
        run = _fn("run")
        deleted = {
            t.id
            for node in ast.walk(run)
            if isinstance(node, ast.Delete)
            for t in node.targets
            if isinstance(t, ast.Name)
        }
        missing = [n for n in CLEANUP_OWNED_NAMES if n not in deleted]
        assert missing == [], f"no longer released by run(): {missing}"

    def test_phase_local_transients_are_not_rebound_in_run(self):
        """The other half of the C7d change, stated as a check.

        `file_vector` / `final_scalar` are freed when the execution phase
        returns. If a future edit binds either back into `run()`'s frame, it
        lives until the next round and no `del` covers it — so that must fail
        here rather than show up as RSS growth.
        """
        run = _fn("run")
        bound = {
            t.id
            for node in ast.walk(run)
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
            for t in ast.walk(node)
            if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)
        }
        rebound = [n for n in PHASE_LOCAL_RELEASED_NAMES if n in bound]
        assert rebound == [], (
            f"run() re-bound phase-local transients without releasing them: {rebound}"
        )

    def test_the_release_still_runs_a_collection(self):
        run = _fn("run")
        assert any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "collect"
            for n in ast.walk(run)
        )

    @pytest.mark.parametrize(
        "helper",
        [
            "_build_execution_failure_record",
            "_build_skip_record",
            "_build_resource_admission_record",
            "_emit_record",
            "_decide_round_outcome",
            "_vram_skip_memory_extra",
            "_time_skip_memory_extra",
        ],
    )
    def test_no_extracted_helper_names_a_cleanup_owned_object(self, helper):
        """Not merely "does not return one" — does not mention one.

        A helper that never names them cannot capture them in a closure,
        stash them on a default argument, or return them inside a new
        container.
        """
        fn = _fn(helper)
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        names |= {a.arg for a in ast.walk(fn) if isinstance(a, ast.arg)}
        leaked = [n for n in LEAK_FORBIDDEN_NAMES if n in names]
        assert leaked == [], f"{helper} took ownership of {leaked}"

    def test_a_built_record_retains_nothing_after_the_caller_drops_it(self):
        """The builders copy scalars; they must not pin their inputs."""
        import weakref

        class _Params(dict):
            pass

        params = _Params({"batch_size": 4})
        ref = weakref.ref(params)
        identity = {**IDENTITY, "record_params": params}
        record = _build_skip_record(
            status="skipped_oom_risk",
            conclusion="c",
            discovery="d",
            memory_update="m",
            **identity,
        )
        # The record legitimately references params (it is persisted).
        assert record["params"] is params
        del record, params, identity
        gc.collect()
        assert ref() is None, "a builder kept the params alive after the record was dropped"


# ---------------------------------------------------------------------
# C4 — helpers stay substitutable by mock.patch
# ---------------------------------------------------------------------


class TestPatchSubstitutability:
    """Ten test files drive `run()` across ~94 invocations, all relying
    on `unittest.mock.patch` intercepting module-global names. A helper
    that captures one into a local, a closure or a default argument
    keeps working — and silently stops being the thing under test."""

    PATCHABLE = ("_run_skill", "TidmadSandbox", "run_production_preflight", "LLMBridge")

    def test_no_helper_captures_a_patchable_name_as_a_default_argument(self):
        offenders = []
        for fn in ast.walk(_tree()):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for default in [*fn.args.defaults, *fn.args.kw_defaults]:
                if isinstance(default, ast.Name) and default.id in self.PATCHABLE:
                    offenders.append((fn.name, default.id))
        assert offenders == []

    def test_no_module_level_alias_of_a_patchable_name(self):
        """`_rs = _run_skill` at module scope would freeze the binding."""
        offenders = []
        for node in _tree().body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
                if node.value.id in self.PATCHABLE:
                    offenders.append(node.value.id)
        assert offenders == []

    def test_the_patchable_names_are_resolved_by_bare_global_reference(self):
        """Reverse proof for the guard above: the production call sites
        must be `_run_skill(...)`, not `something._run_skill(...)` or a
        captured local — otherwise patching the module attribute stops
        intercepting."""
        calls = [
            n
            for n in ast.walk(_tree())
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_run_skill"
        ]
        assert len(calls) >= 1


# ---------------------------------------------------------------------
# E1 — one execution-failure builder for both phases
# ---------------------------------------------------------------------


class TestExecutionFailureRecord:
    @pytest.mark.parametrize(
        "phase,expected",
        [("training", "error_training"), ("inference", "error_inference")],
    )
    def test_plain_failure_status(self, phase, expected):
        rec = _build_execution_failure_record({"message": "boom"}, phase=phase, **IDENTITY)
        assert rec["status"] == expected

    @pytest.mark.parametrize(
        "phase,expected",
        [("training", "error_training_oom"), ("inference", "error_inference_oom")],
    )
    def test_oom_failure_status(self, phase, expected):
        rec = _build_execution_failure_record(
            {"message": "CUDA out of memory"}, phase=phase, **IDENTITY
        )
        assert rec["status"] == expected

    def test_the_silent_train_crash_reroute_is_inference_only(self):
        """A training failure carrying the marker must NOT be re-routed;
        the marker exists because the *inference* subprocess is where a
        silent training crash surfaces."""
        inf = _build_execution_failure_record(
            {"message": "error_training: no sentinel"}, phase="inference", **IDENTITY
        )
        assert inf["status"] == "error_training"
        assert "silently" in inf["memory"]["conclusion"]

        train = _build_execution_failure_record(
            {"message": "error_training: no sentinel"}, phase="training", **IDENTITY
        )
        assert train["status"] == "error_training"
        assert "silently" not in train["memory"]["conclusion"]

    def test_the_message_is_truncated_to_the_last_500_characters(self):
        rec = _build_execution_failure_record(
            {"message": "x" * 900 + "TAIL"}, phase="training", **IDENTITY
        )
        assert "TAIL" in rec["memory"]["conclusion"]
        assert len(rec["memory"]["conclusion"]) < 600

    def test_position_is_stamped(self):
        rec = _build_execution_failure_record({"message": "e"}, phase="training", **IDENTITY)
        assert rec["memory"]["round_index"] == 2
        assert rec["memory"]["attempt_in_round"] == 1

    def test_it_is_pure(self):
        """No validation, no persistence — those belong to _emit_record."""
        fn = _fn("_build_execution_failure_record")
        calls = {
            n.func.attr
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "save_record" not in calls
        assert "model_validate" not in calls


# ---------------------------------------------------------------------
# E2 / C3 — skip records, and the admission surface
# ---------------------------------------------------------------------


class TestSkipRecords:
    def test_memory_extra_lands_before_the_position_stamps(self):
        """Key order matches what each site produced inline."""
        rec = _build_skip_record(
            status="skipped_oom_risk",
            conclusion="c",
            discovery="d",
            memory_update="m",
            memory_extra={"vram_budget_gb": 12.0},
            **IDENTITY,
        )
        keys = list(rec["memory"])
        assert keys.index("vram_budget_gb") < keys.index("round_index")

    def test_no_extra_is_the_same_shape_minus_the_extras(self):
        rec = _build_skip_record(
            status="skipped_time_risk",
            conclusion="c",
            discovery="d",
            memory_update="m",
            **IDENTITY,
        )
        assert list(rec["memory"]) == [
            "expert_advice_followed",
            "hypothesis",
            "conclusion",
            "discovery",
            "memory_update",
            "round_index",
            "attempt_in_round",
        ]


class TestResourceAdmissionSurface:
    """C3 — admission gets its own status.

    `skipped_time_risk` already carries three distinct meanings and
    feeds five time-factor consumers; a fourth producer would pollute
    statistics that mean something else.
    """

    def test_the_status_is_its_own(self):
        assert RESOURCE_ADMISSION_STATUS == "skipped_resource_admission"
        assert RESOURCE_ADMISSION_STATUS != "skipped_time_risk"

    @pytest.mark.parametrize("reason", RESOURCE_ADMISSION_REASONS)
    def test_each_frozen_reason_builds(self, reason):
        rec = _build_resource_admission_record(
            resource_type="gpu_memory", reason_code=reason, detail="d", **IDENTITY
        )
        # V20 attempt 2: only a genuine headroom verdict may claim a
        # resource refusal. A measurement/policy failure is infrastructure,
        # and filing it as a resource decision is what made 15 records read
        # as "the GPU was full" while it sat at 1.6 of 32.6 GiB.
        expected = (
            RESOURCE_ADMISSION_STATUS
            if reason == "insufficient_headroom"
            else INFRASTRUCTURE_FAILURE_STATUS
        )
        assert rec["status"] == expected
        assert rec["memory"]["reason_code"] == reason
        assert rec["memory"]["resource_type"] == "gpu_memory"

    def test_an_unknown_reason_is_rejected_rather_than_recorded(self):
        with pytest.raises(ValueError, match="unknown admission reason_code"):
            _build_resource_admission_record(
                resource_type="gpu_memory", reason_code="made_up", detail="d", **IDENTITY
            )

    def test_it_carries_no_authority_to_shrink_the_candidate(self):
        rec = _build_resource_admission_record(
            resource_type="gpu_memory",
            reason_code="insufficient_headroom",
            detail="d",
            **IDENTITY,
        )
        memory = rec["memory"]
        assert "Do NOT reduce model" in memory["memory_update"]
        assert "not evidence that the model was too large" in memory["discovery"]

    def test_the_builder_is_reached_only_from_the_approved_path(self):
        """Replaces B-C4a0's "no emitter yet" guard, which fired as
        designed when B-C4c added the caller.

        The surviving invariant is that its wording, its reason vocabulary
        and its budget accounting cannot drift into a second copy -- so
        every caller must go through THIS builder rather than assembling
        an equivalent.

        V20 PR C2 / C2-8 added the pre-phase measurement handler as a
        second approved caller. It uses the builder unchanged, which is
        the builder doing its job; what would break the invariant is a
        hand-rolled record, and that still fails here.
        """
        callers = {
            fn.name
            for fn in ast.walk(_tree())
            if isinstance(fn, ast.FunctionDef)
            and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_build_resource_admission_record"
                for n in ast.walk(fn)
            )
        }
        assert callers == {"_handle_admission_refusal", "_handle_prephase_gpu_measurement"}

    def test_both_phases_consume_the_refusal(self):
        phases = sorted(
            kw.value.value
            for node in ast.walk(_tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_handle_admission_refusal"
            for kw in node.keywords
            if kw.arg == "phase" and isinstance(kw.value, ast.Constant)
        )
        assert phases == ["inference", "training"]

    def test_nobody_hand_assembles_an_equivalent_record(self):
        """The status string must appear only in the frozen constant and
        the one guard that reads it — never in a literal dict somewhere
        building the same record by hand."""
        holders = set()
        for fn in ast.walk(_tree()):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value == "skipped_resource_admission"
                ):
                    holders.add(fn.name)
        assert holders == set(), (
            f"{sorted(holders)} name the status literally; it belongs to "
            "RESOURCE_ADMISSION_STATUS so there is one spelling"
        )


# ---------------------------------------------------------------------
# E5 / C2 — typed decisions
# ---------------------------------------------------------------------

# ``TestAttemptDecision`` lived here. Step 07 PR 07b DELETED it together with
# the ``AttemptTransition`` / ``AttemptDecision`` types it exercised (§3.5,
# operator decision Q-07b-1): the types had zero production consumers, and
# wiring them would have required resetting the round-scoped
# ``resolved_action`` per attempt — a change to round outcomes that 07b is not
# permitted to make. Testing a type nothing calls proved nothing about the
# tuner; the hazard those tests described is now recorded as a known defect
# beside the ``resolved_action`` declaration in ``run()``, with a proposed fix
# and an owner. ``TestRoundOutcome`` below is untouched: ``RoundDecision`` and
# ``_decide_round_outcome`` ARE wired.


def _round_inputs(**over):
    base = dict(
        scope_violation_reason=None,
        evidence_channel_failure=None,
        resolved_action=GateAction.CONTINUE,
        is_formal_round=False,
    )
    base.update(over)
    return base


class TestRoundOutcome:
    def test_the_default_is_to_continue(self):
        assert _decide_round_outcome(**_round_inputs()) is RoundDecision.CONTINUE

    @pytest.mark.parametrize("field", ["scope_violation_reason", "evidence_channel_failure"])
    def test_a_non_retryable_condition_breaks_the_iteration(self, field):
        assert (
            _decide_round_outcome(**_round_inputs(**{field: "boom"}))
            is RoundDecision.BREAK_ITERATION
        )

    def test_skip_iter_breaks_the_iteration(self):
        assert (
            _decide_round_outcome(**_round_inputs(resolved_action=GateAction.SKIP_ITER))
            is RoundDecision.BREAK_ITERATION
        )

    def test_skip_to_formal_only_outside_the_formal_round(self):
        assert (
            _decide_round_outcome(**_round_inputs(resolved_action=GateAction.SKIP_TO_FORMAL))
            is RoundDecision.SKIP_TO_FORMAL
        )
        assert (
            _decide_round_outcome(
                **_round_inputs(resolved_action=GateAction.SKIP_TO_FORMAL, is_formal_round=True)
            )
            is RoundDecision.CONTINUE
        )

    def test_a_non_retryable_condition_outranks_a_gate_action(self):
        """Order is load-bearing: a scope violation is deterministic on
        retry, so it must not be overtaken by SKIP_TO_FORMAL."""
        assert (
            _decide_round_outcome(
                **_round_inputs(
                    scope_violation_reason="scope", resolved_action=GateAction.SKIP_TO_FORMAL
                )
            )
            is RoundDecision.BREAK_ITERATION
        )

    def test_it_decides_without_acting(self):
        fn = _fn("_decide_round_outcome")
        calls = {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "print" not in calls


class TestEmitRecordSeam:
    def test_it_validates_before_saving(self):
        saved = []

        class _Sandbox:
            def save_record(self, record):
                saved.append(record)

        rec = _build_skip_record(
            status="skipped_oom_risk",
            conclusion="c",
            discovery="d",
            memory_update="m",
            **IDENTITY,
        )
        _emit_record(_Sandbox(), rec)
        assert saved == [rec]

    def test_an_invalid_record_never_reaches_the_sandbox(self):
        saved = []

        class _Sandbox:
            def save_record(self, record):
                saved.append(record)

        with pytest.raises(ValidationError):
            _emit_record(_Sandbox(), {"exp_id": "e", "status": "not_a_status"})
        assert saved == []

    def test_stamping_is_opt_in(self):
        """`status=None` stamps nothing — what every non-executor path
        does today."""

        class _Sandbox:
            def save_record(self, record):
                pass

        rec = _build_skip_record(
            status="skipped_oom_risk",
            conclusion="c",
            discovery="d",
            memory_update="m",
            **IDENTITY,
        )
        _emit_record(_Sandbox(), rec)
        assert "gpu_evidence" not in rec
        assert "failure_attribution" not in rec
