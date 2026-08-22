"""Step 10 / P5+P6 — C6: three-task ORCHESTRATION closure through ``run_workflow``.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §10.3, §13 C6.

Three materially different tasks traverse the ONE generic path, with only the
COMPOSITION differing:

    TIDMAD   1-D denoising      negative-valued `higher` primary, no secondaries
    Pets     37-way RGB class.  `accuracy` higher + exactly `macro_f1` observational
    DAVIS    spatiotemporal     `mse` LOWER + `psnr` higher / `mae` lower

**FROZEN HONESTY RULE (§10.3), which this module obeys and states in every
claim it makes:**

> C6 MUST NOT label its Pets/DAVIS pseudo sandbox inputs as task-correct
> training scope. It proves ORCHESTRATION semantics only.

Real task-correct contrast TRAINING is **CAP-SCOPE** — a declared missing
capability (task-owned scope construction), NOT something these drives
demonstrate and NOT something Step 10 delivers. Nothing here is evidence of
contrast-track L4. The retained Pets/DAVIS runners keep the real-execution
evidence (§10.4).

What the drives DO own: the loop initializes and traverses under each task's
own declared direction, secondaries, Health family and typed proposer
boundary, with the carried lifecycle live — through ``run_workflow`` itself,
never a per-task hand-written driver and never the bounded-iteration helper.
That is what makes "same framework path" a fact rather than a fixture
arrangement.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.candidate_eligibility import resolve_run_scientific_gate_ids
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tune_output,
    _make_validator_output,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

#: The three tracks' DECLARED semantics, hand-written from their manifests —
#: never read back from the code under test.
DECLARED = {
    "tidmad": {"primary": ("tidmad_denoising_score", "higher"), "secondaries": []},
    "pets": {"primary": ("accuracy", "higher"), "secondaries": [("macro_f1", "higher")]},
    "davis": {
        "primary": ("mse", "lower"),
        "secondaries": [("psnr", "higher"), ("mae", "lower")],
    },
}

TASKS = ["tidmad", "pets", "davis"]


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """One process binds ONE Health plugin set — the C6 driver crosses three.

    This is a binding constraint the C0 baselines discovered, not an
    incidental fixture: without the reset, the parametrized driver would pass
    only for whichever task happened to run first.
    """
    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _composition(task: str):
    return compose_run_task_bindings(str(FIXTURES / task / "composition.yaml"))


def _write_seed(tmp_path: Path, composition, score: float) -> None:
    """A seed tuning output stamped with THIS composition's metric.

    Composition-consistent by construction. A TIDMAD-stamped seed under an
    ``accuracy`` composition is correctly refused by P2a's reconciliation —
    that refusal is the system working, and feeding it here would test the
    refusal rather than the orchestration.

    Step 11 C8 adds a second axis of that same consistency: the seed now
    also carries this composition's ``task_composition_fingerprint``,
    because R-11-9 refuses an UNSTAMPED output under a composed run. The
    docstring above already stated the principle; C8 only widened what
    "consistent" covers.
    """
    agent_dir = tmp_path / "data" / "punet" / "v1" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    output = HyperparamTuningOutput(
        run_name="v1",
        model_type="punet",
        file_index=0,
        status="completed",
        # Step 11 C8 / R-11-9 — see the docstring.
        task_composition_fingerprint=composition.semantic_fingerprint,
        completed_rounds=1,
        total_attempts=1,
        best_exp_id="punet_v1_001",
        best_denoising_score=score,
        best_formal_denoising_score=score,
        best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        all_records=[
            {
                "exp_id": "punet_v1_001",
                "status": "success",
                "model_type": "punet",
                "timestamp": "2026-01-01 00:00:00",
                "file_index": 0,
                "params": {"model_config": {}, "train_config": {}, "loss_config": {}},
                "results": {"denoising_score": score},
                "denoising_score": score,
            }
        ],
        started_at="2026-01-01 00:00:00",
        finished_at="2026-01-01 01:00:00",
        metric_spec=composition.metric.spec,
    )
    (agent_dir / "run_output_v1_agent.json").write_text(output.model_dump_json(indent=2))


def drive(task: str, tmp_path: Path, *, iterations: int = 1) -> dict:
    """**THE ONE DRIVER.** Parametrized by manifest; no per-task branch.

    Every task enters through ``compose_run_task_bindings`` ->
    ``bind_run_task_composition`` -> ``run_workflow``. There is deliberately
    no ``if task == ...`` anywhere below: if a task needed special handling
    here, "same framework path" would be false.
    """
    composition = _composition(task)
    score = 0.5 if DECLARED[task]["primary"][1] == "lower" else 1.5
    _write_seed(tmp_path, composition, score)

    observed: dict = {"interp_in": [], "propose_in": [], "tune_in": []}

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        call = {"n": 0}

        def _interp(inp):
            call["n"] += 1
            n = call["n"]
            observed["interp_in"].append(inp)
            out = _make_interpretation_output()
            out.key_findings = [f"{task} finding {n}"]
            out.vocab_link_confirmations = {
                f"{task}_feature:{task}_capability": [f"run_{i}" for i in range(1, n + 1)]
            }
            return out

        def _propose(inp):
            observed["propose_in"].append(inp)
            return _make_proposal_output(f"{task}_cand_{len(observed['propose_in'])}")

        def _tune(inp):
            observed["tune_in"].append(inp)
            out = _make_tune_output(model_type=inp.model_type, score=score)
            out.metric_spec = composition.metric.spec
            return out

        MockInterp.return_value.run.side_effect = _interp
        MockPropose.return_value.run.side_effect = _propose
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = _tune

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            results = run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=iterations,
                ),
                workspace=str(tmp_path / "ws"),
                run_name=f"c6_{task}",
                task_composition=composition,
            )

    observed["results"] = results
    observed["composition"] = composition
    observed["workspace"] = tmp_path / "ws"
    return observed


# ---------------------------------------------------------------------------
# The matrix: every task, ONE path
# ---------------------------------------------------------------------------


class TestAllThreeTasksTraverseTheOneGenericPath:
    @pytest.mark.parametrize("task", TASKS)
    def test_the_loop_initializes_and_traverses_every_node(self, task, tmp_path):
        """interpret -> propose -> implement -> validate -> plan, per task."""
        seen = drive(task, tmp_path)
        assert len(seen["results"]) == 1
        assert len(seen["interp_in"]) == 1
        assert len(seen["propose_in"]) == 1
        assert len(seen["tune_in"]) == 1

    @pytest.mark.parametrize("task", TASKS)
    def test_the_run_is_ordered_by_the_tasks_OWN_declared_direction(self, task, tmp_path):
        """The interpreter receives the composition's spec, not an assumed one.

        DAVIS is the discriminating case: a `lower` primary reaching the
        interpreter unchanged is what proves nothing in the generic path
        assumes higher-is-better.
        """
        seen = drive(task, tmp_path)
        metric_id, direction = DECLARED[task]["primary"]
        spec = seen["interp_in"][0].metric_spec
        assert spec is not None
        assert (spec.id, spec.direction) == (metric_id, direction)

    @pytest.mark.parametrize("task", TASKS)
    def test_the_declared_secondaries_are_exactly_the_tasks_own(self, task, tmp_path):
        """Observational secondaries, per P2b — declared, never inferred.

        TIDMAD declares NONE, which is a semantic emptiness rather than an
        omission: zero rows, zero bytes.
        """
        seen = drive(task, tmp_path)
        bound = [(m.spec.id, m.spec.direction) for m in seen["composition"].secondary_metrics]
        assert bound == DECLARED[task]["secondaries"]

    @pytest.mark.parametrize("task", TASKS)
    def test_the_run_binds_the_tasks_OWN_health_family_state_c(self, task, tmp_path):
        """State C — an explicit declaration, never `LEGACY_OMITTED`, and never
        another task's family (W6)."""
        composition = _composition(task)
        binding = composition.task_health_binding
        assert isinstance(binding, str) and binding.endswith(".yaml")
        assert Path(binding).is_file()
        resolved = resolve_run_scientific_gate_ids(binding)
        assert resolved, f"{task} declares no blocking gates"

        # Comparing against TIDMAD's family means binding a SECOND one, which
        # is a new run as far as the process-global scope is concerned.
        _plugin_binding.reset_run_scope()
        tidmad = resolve_run_scientific_gate_ids(_composition("tidmad").task_health_binding)
        if task == "tidmad":
            assert resolved == tidmad
        else:
            assert not (resolved & tidmad), (
                f"{task} shares a blocking gate with TIDMAD's legacy family"
            )

    @pytest.mark.parametrize("task", TASKS)
    def test_the_composed_run_is_pinned_in_the_workspace_lock(self, task, tmp_path):
        """Anti-vacuity for the whole matrix: prove the run really COMPOSED.

        The run-invariants lock records the composition fingerprint, so a drive
        that silently fell back to un-composed behaviour is visible here.
        """
        seen = drive(task, tmp_path)
        lock = json.loads((seen["workspace"] / "run_invariants_lock.json").read_text())
        assert lock.get("task_composition_fingerprint") == seen["composition"].semantic_fingerprint

    # NOTE — C-P56-1 (no implicit legacy TIDMAD reference science in a composed
    # run) is deliberately NOT owned here. This module's driver MOCKS
    # `HyperparamTuningAgent`, so `load_reference_scores()` never executes and
    # the W4 guard cannot be observed through this loop at all. A test here
    # could only re-assert the guard's precondition directly, which is exactly
    # what `test_step10_p56_c5_wiring_closures.py::
    # test_2_3_4_the_guard_keys_on_composition_presence_for_every_task` already
    # does for these same three tasks — and it additionally pins the legacy
    # `is None` half, which a composed-only assertion cannot.
    #
    # An earlier revision of this file carried such a test whose docstring
    # claimed it observed the guard "through the loop rather than at the
    # guard". It did not: it never called `drive()`. Removed rather than
    # reworded, because the claim is unimplementable in this harness.


# ---------------------------------------------------------------------------
# DAVIS — the lower-is-better falsifier, with carried state live
# ---------------------------------------------------------------------------


class TestDavisIsTheDirectionFalsifier:
    """§10.3's discriminating track: a `lower` primary end-to-end across
    iterations, with both carried values live."""

    def test_two_iterations_carry_state_under_a_lower_primary(self, tmp_path):
        seen = drive("davis", tmp_path, iterations=2)

        assert len(seen["interp_in"]) == 2
        # The lifecycle is live: iteration 2 received iteration 1's mapping.
        assert seen["interp_in"][0].vocab_link_confirmations == {}
        assert seen["interp_in"][1].vocab_link_confirmations == {
            "davis_feature:davis_capability": ["run_1"]
        }
        # ...and iteration 2's proposer saw iteration 1's finding.
        findings = [i.content for i in seen["propose_in"][1].expert_context if i.kind == "findings"]
        assert findings and "davis finding 1" in findings[0]

    def test_the_direction_stayed_lower_across_both_iterations(self, tmp_path):
        seen = drive("davis", tmp_path, iterations=2)
        for inp in seen["interp_in"]:
            assert inp.metric_spec.direction == "lower"

    def test_the_carried_values_contain_nothing_direction_shaped(self, tmp_path):
        """Structural, not incidental: the carriers hold run-name lists and
        synthesized strings. No score, no direction, nothing orderable — which
        is WHY the lifecycle cannot inherit a higher-is-better assumption."""
        seen = drive("davis", tmp_path, iterations=2)
        mapping = seen["interp_in"][1].vocab_link_confirmations
        for key, runs in mapping.items():
            assert isinstance(key, str)
            assert all(isinstance(r, str) for r in runs)
        for item in seen["propose_in"][1].expert_context:
            assert isinstance(item.content, str)

    def test_the_direction_TRACKS_the_declaration_rather_than_being_constant(self, tmp_path):
        """ANTI-VACUITY, as a differential.

        `test_the_direction_stayed_lower_across_both_iterations` would also
        pass if `run_workflow` hardcoded ``"lower"``, or if the DAVIS manifest
        were the only one ever exercised. So drive TWO tasks whose manifests
        declare OPPOSITE directions and apply the SAME expression to both: a
        drive that ignores the declaration and returns a constant cannot
        satisfy both halves, whichever constant it picks.

        (The previous revision of this test asserted ``direction == "lower"``
        and then required ``assert direction == "higher"`` to raise. Given the
        line above it, that second block is a theorem of ``str.__eq__`` — it
        tests CPython's ``assert`` statement, not the composition, and no
        mutation of production code could turn it red.)
        """
        observed = {}
        for task in ("tidmad", "davis"):
            # One process binds ONE Health plugin set, so crossing tasks inside
            # a single test needs the same reset the module fixture performs
            # between tests. Discovered by this test failing with
            # HealthPluginRunScopeError — the run-scope guard working.
            _plugin_binding.reset_run_scope()
            observed[task] = drive(task, tmp_path / task)["interp_in"][0].metric_spec.direction

        assert observed == {"tidmad": "higher", "davis": "lower"}
        # ...and those are exactly what the two manifests declare, so the
        # workflow is reading the declaration, not a default.
        assert observed["tidmad"] == DECLARED["tidmad"]["primary"][1]
        assert observed["davis"] == DECLARED["davis"]["primary"][1]
        assert observed["tidmad"] != observed["davis"]


# ---------------------------------------------------------------------------
# Structural: one path, protocol-only proposer input, no task dispatch
# ---------------------------------------------------------------------------


class TestTheDriverItselfIsGeneric:
    def test_the_driver_contains_no_per_task_branch(self):
        """If a task needed special handling in the driver, "same framework
        path" would be false. Asserted over the AST of ``drive`` itself."""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "drive")
        rendered = ast.dump(fn)
        for task in TASKS:
            assert f"Constant(value='{task}')" not in rendered, (
                f"the driver mentions {task!r} — it must be parametrized by manifest only"
            )

    def test_every_task_enters_through_run_workflow_itself(self):
        """Not the bounded-iteration helper, not a hand-written runner.

        Checked over the AST of ``drive``: a substring search would match this
        module's own prose about what it does NOT use.
        """
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "drive")
        called = {
            node.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "run_workflow" in called
        assert "run_bounded_pseudo_iteration" not in called

    @pytest.mark.parametrize("task", TASKS)
    def test_proposer_input_is_built_by_the_protocol_not_by_hand(self, task, tmp_path):
        """The P3 typed boundary, forced by driving the real loop.

        ``ProposalInput.interpretation`` was REMOVED by P3; the typed evidence
        is the only carrier. A drive that hand-built proposer input would not
        exercise it.
        """
        seen = drive(task, tmp_path)
        proposal_input = seen["propose_in"][0]
        assert proposal_input.interpretation_evidence is not None
        assert not hasattr(proposal_input, "interpretation")

    @pytest.mark.parametrize("task", TASKS)
    def test_raw_secondary_values_never_reach_the_proposer(self, task, tmp_path):
        """Q-P3-3 held across all three tasks, including the two that actually
        declare secondaries."""
        seen = drive(task, tmp_path)
        evidence = seen["propose_in"][0].interpretation_evidence
        assert not hasattr(evidence, "secondary_metric_results")
        for metric_id, _direction in DECLARED[task]["secondaries"]:
            assert metric_id not in str(evidence.model_dump())


#: Task-identity tokens a generic-core `if` must never test against. Includes
#: BOTH the pack directory names and the short names, because a dispatch can
#: be written either way — the short forms were previously covered only by a
#: separate substring scan in the C2 module, which could not see
#: ``if task_id == "tidmad"`` in any file but one.
TASK_IDENTITY_TOKENS = (
    "oxford_iiit_pet",
    "davis_future_prediction",
    "tidmad",
    "pets",
    "davis",
)


def _task_identity_branches(source: str) -> list[str]:
    """THE detector. Returns the rendered test of every `if` that compares
    against a task-identity token.

    Module-level so the census below and its anti-vacuity plant call the SAME
    function. An earlier revision inlined this logic into both, which meant the
    plant proved only that a COPY of the detector bites — the real census could
    have been broken or mis-scoped and the plant would still have passed.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.If):
            continue
        rendered = ast.dump(node.test)
        if any(f"'{token}'" in rendered for token in TASK_IDENTITY_TOKENS):
            found.append(rendered)
    return found


def test_the_generic_path_gained_no_task_identity_dispatch():
    """The standing census, over the files THIS commit touched."""
    touched = [
        REPO_ROOT / "workflows" / "model_exploration.py",
        REPO_ROOT / "core" / "chain_state.py",
        REPO_ROOT / "core" / "resume.py",
        REPO_ROOT / "execute_tools" / "health_checks" / "candidate_eligibility.py",
    ]
    for path in touched:
        offenders = _task_identity_branches(path.read_text(encoding="utf-8"))
        assert offenders == [], f"{path.name} branches on a task identity: {offenders}"


def test_the_task_identity_census_would_CATCH_a_planted_offender():
    """ANTI-VACUITY for the census above (§17 R9).

    A census that asserts an absence passes just as well when its detector is
    broken or its scope misses the file. Planting the offending shape into a
    parsed COPY must be detected — nothing is written to disk.
    """
    planted = (
        "def run_workflow(task_id):\n"
        "    if task_id == 'oxford_iiit_pet':\n"
        "        return 'special-cased'\n"
        "    return 'generic'\n"
    )
    assert len(_task_identity_branches(planted)) == 1, (
        "the census detector failed to see a planted task branch"
    )
    # ...and the SHORT form too, which is how a dispatch is most naturally
    # written and which the census must therefore also catch.
    short = "def f(t):\n    if t == 'tidmad':\n        return 1\n    return 2\n"
    assert len(_task_identity_branches(short)) == 1
    # A branch that mentions no task identity is not flagged, so the detector
    # is discriminating rather than merely eager.
    assert _task_identity_branches("def f(x):\n    if x == 'anything':\n        return 1\n") == []
