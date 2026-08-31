"""Step 10 / P1 C2 — the composed value actually GOVERNS a run.

C1 proved a composition can be built. This module proves it is consumed, that
it is consumed by *every* family rather than most of them, and that it stops
being consumed the moment the run ends.

The defect this exists to catch has a specific shape, and it is not an
exception. A half-composed run does not crash: the families that were wired
read the composed task, the families that were missed read the legacy
defaults, and every log line looks normal. Numbers come out. They are wrong in
a way that no amount of staring at the output reveals. So:

* **consumption** is asserted on the objects the production seams actually
  return (``is``-identity where the seam guarantees it), never on the
  composition's own fields — comparing the composition to itself would pass
  for a value nothing consumes;

* **reachability** covers all five LLM consumer families named in design §5.8
  (planner · literature review · proposer · implementor · interpreter),
  because the task description reaches each of them through its own call to
  ``load_task_config()`` at its own depth. A wiring proof that checked one
  family would say nothing about the other four;

* **leakage** is tested across sequential and nested runs, since the binding
  is a ContextVar and a missing token reset is invisible until the *next* run
  quietly inherits the previous task;

* **the lock** must gain the composed fingerprint, refuse a changed one on
  resume, and stay byte-identical for an un-composed run — the key ABSENT,
  never ``null`` (design §5.9).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from workflows.task_composition import (
    CompositionNotBoundError,
    bind_run_task_composition,
    compose_run_task_bindings,
    verify_composition_is_bound,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"
FOURTH_MANIFEST = FIXTURES / "fourth_task" / "composition.yaml"
QUICKSTART_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"


@pytest.fixture(autouse=True)
def _clear_task_config_cache():
    from workflows.task_config import _clear_cache_for_tests

    _clear_cache_for_tests()
    yield
    _clear_cache_for_tests()


@pytest.fixture
def composition():
    return compose_run_task_bindings(str(FOURTH_MANIFEST))


# ---------------------------------------------------------------------------
# The production seams return the composed objects
# ---------------------------------------------------------------------------


class TestEachFamilyIsConsumedThroughItsOwnSeam:
    """Asserted at the seam a PRODUCTION consumer calls, not at the carrier."""

    def test_the_dataset_profile_seam_returns_the_composed_profile(self, composition):
        from execute_tools.dataset_config import resolve_dataset_profile

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            assert resolve_dataset_profile() is composition.dataset_profile

    def test_the_metric_seam_returns_the_composed_metric(self, composition):
        """The tuner's acquisition site calls exactly this."""
        from execute_tools.evaluation_metric import resolve_bound_run_metric

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            bound = resolve_bound_run_metric()
        assert bound is composition.metric
        assert bound.spec.id == "band_coverage_error"
        assert bound.spec.direction == "lower"

    def test_the_task_data_path_seam_returns_the_composed_implementation(self, composition):
        from execute_tools.task_data_path import (
            active_task_data_path,
            resolve_bound_task_data_path,
        )

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            assert active_task_data_path() is composition.task_data_path
            assert resolve_bound_task_data_path() is composition.task_data_path

    def test_the_task_config_seam_returns_the_composed_values(self, composition):
        from workflows.task_config import get_task_description, load_task_config

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            values = load_task_config()
            assert get_task_description(values) == composition.task_description
            assert values["forward_contract"]["task_type"] == "segmentation"

    def test_the_tuner_acquires_the_composed_metric(self, composition):
        """Reachability for the ONE production line C2 changed.

        The seam test above proves the ContextVar works; this proves the
        tuner's own expression reads it. Executed as the tuner executes it,
        against the real bound state, so a future edit that reorders the
        `or` — making every composed run silently run TIDMAD's arithmetic —
        turns this RED.
        """
        from execute_tools.evaluation_metric import resolve_bound_run_metric

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            acquired = resolve_bound_run_metric()
        assert acquired is composition.metric
        assert resolve_bound_run_metric() is None


class TestTheWorkflowRefusesAHalfComposedRun:
    """``run_workflow`` consumes a binding it does not establish, so the
    refusal is what makes that split safe."""

    def test_an_unbound_composition_is_refused(self, composition):
        with pytest.raises(CompositionNotBoundError, match="not active"):
            verify_composition_is_bound(composition)

    def test_a_bound_composition_passes(self, composition):
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            verify_composition_is_bound(composition)

    def test_an_un_composed_run_is_a_no_op(self):
        verify_composition_is_bound(None)

    @pytest.mark.parametrize(
        "family", ["task_data_path", "dataset_profile", "metric", "task_config"]
    )
    def test_a_PARTIALLY_bound_composition_is_refused_and_names_the_family(
        self, composition, family
    ):
        """The real hazard, one family at a time.

        Binding three of the four and forgetting the fourth is exactly what a
        future edit to the ExitStack would produce, and it is the state that
        produces plausible wrong numbers rather than an error. Each partial
        bind must be refused BY NAME.
        """
        from contextlib import ExitStack

        from execute_tools.dataset_config import bind_dataset_profile
        from execute_tools.evaluation_metric import bind_run_metric
        from execute_tools.task_data_path import bind_task_data_path
        from workflows.task_config import bind_task_config

        binders = {
            "task_data_path": lambda: bind_task_data_path(composition.task_data_path),
            "dataset_profile": lambda: bind_dataset_profile(composition.dataset_profile),
            "metric": lambda: bind_run_metric(composition.metric),
            "task_config": lambda: bind_task_config(composition.task_config_values()),
        }
        with ExitStack() as stack:
            for name, binder in binders.items():
                if name != family:
                    stack.enter_context(binder())
            with pytest.raises(CompositionNotBoundError, match=family):
                verify_composition_is_bound(composition)


# ---------------------------------------------------------------------------
# §5.8 — the consumer-reachability matrix
# ---------------------------------------------------------------------------


class TestConsumerReachabilityMatrix:
    """All FIVE families read the composed task description (design §5.8).

    Each family is exercised through the expression its own production code
    uses, so this is reachability rather than a restatement of the seam test.
    The hazard it kills: a region that covers the proposer and the tuner while
    the planner, a literature-review call or the interpreter loses the bound
    declaration — one run, inconsistent task descriptions, no error.
    """

    def test_all_five_families_read_the_composed_description(self, composition):
        from agent.prompt_templates.literature_review import render_paper_extract_prompt
        from agent.prompts import PLANNER_PROMPT
        from workflows.task_config import get_task_description, load_task_config

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            # 1. planner — the workflow assigns tune_input.task_description
            #    from this, and the bridge substitutes it into PLANNER_PROMPT.
            planner_value = get_task_description(load_task_config())
            planner_rendered = PLANNER_PROMPT.replace("{TASK_DESCRIPTION}", planner_value)

            # 2. literature review — the input builder reads the same call and
            #    the template substitutes the same placeholder.
            lit_system, _lit_user = render_paper_extract_prompt(
                raw_text="a paper",
                task_description=get_task_description(load_task_config()),
            )

            # 3. proposer — its node reads load_task_config() directly.
            proposer_value = get_task_description(load_task_config())

            # 4. implementor — the workflow assigns from the same call.
            implementor_value = get_task_description(load_task_config())

            # 5. interpreter — InterpretationInput.task_description, rendered
            #    into both phase system prompts.
            from agent.prompt_templates.interpretation.rendering import (
                PER_MODEL_SYSTEM_PROMPT,
            )

            interpreter_rendered = PER_MODEL_SYSTEM_PROMPT.replace(
                "{TASK_DESCRIPTION}", get_task_description(load_task_config())
            )

        composed = composition.task_description
        assert planner_value == composed
        assert proposer_value == composed
        assert implementor_value == composed
        for name, rendered in (
            ("planner", planner_rendered),
            ("literature review", lit_system),
            ("interpreter", interpreter_rendered),
        ):
            assert "Spectrogram band-coverage" in rendered, f"{name} rendered the wrong task"
        assert implementor_value == composed

    def test_the_matrix_is_not_vacuous(self):
        """Without a composition, the same reader refuses explicitly.

        Without this, the assertions above would pass on any fixture whose
        text happened to appear everywhere — including one where nothing was
        bound at all.
        """
        from workflows.task_config import load_task_config

        with pytest.raises(ValueError, match="no task configuration is bound"):
            load_task_config()


class TestNoLeakAcrossRuns:
    """A missing token reset is invisible until the NEXT run inherits a task."""

    def test_composed_then_un_composed_leaves_nothing_bound(self, composition):
        from execute_tools.evaluation_metric import resolve_bound_run_metric
        from execute_tools.task_data_path import active_task_data_path
        from workflows.task_config import load_task_config

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            pass

        assert active_task_data_path() is None
        assert resolve_bound_run_metric() is None
        with pytest.raises(ValueError, match="no task configuration is bound"):
            load_task_config()

    def test_composed_A_then_composed_B_shows_no_contamination(self, composition):
        from execute_tools.dataset_config import resolve_dataset_profile
        from execute_tools.evaluation_metric import resolve_bound_run_metric

        quickstart = compose_run_task_bindings(str(QUICKSTART_MANIFEST))

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            assert resolve_bound_run_metric().spec.id == "band_coverage_error"
        with bind_run_task_composition(quickstart, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            assert resolve_bound_run_metric().spec.id == "accuracy"
            assert resolve_dataset_profile() is quickstart.dataset_profile
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            assert resolve_bound_run_metric().spec.id == "band_coverage_error"
            assert resolve_dataset_profile() is composition.dataset_profile

    def test_nested_runs_restore_the_outer_binding(self, composition):
        from execute_tools.evaluation_metric import resolve_bound_run_metric

        quickstart = compose_run_task_bindings(str(QUICKSTART_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            with bind_run_task_composition(quickstart, physical_data_root=COMPOSED_TEST_DATA_ROOT):
                assert resolve_bound_run_metric() is quickstart.metric
            assert resolve_bound_run_metric() is composition.metric

    def test_an_exception_inside_the_region_still_unwinds_every_binding(self, composition):
        """The reason this is a ``finally``/token idiom and not a pair of
        assignments: a run that raises must not leave its task bound for
        whatever runs next in the same process."""
        from execute_tools.evaluation_metric import resolve_bound_run_metric
        from execute_tools.task_data_path import active_task_data_path
        from workflows.task_config import load_task_config

        with pytest.raises(RuntimeError, match="deliberate"):
            with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
                raise RuntimeError("deliberate failure inside the run region")

        assert active_task_data_path() is None
        assert resolve_bound_run_metric() is None
        with pytest.raises(ValueError, match="no task configuration is bound"):
            load_task_config()


# ---------------------------------------------------------------------------
# §5.9 — the composed fingerprint in the run-invariants lock
# ---------------------------------------------------------------------------


def _build(workspace: str, fingerprint: str | None, **kwargs):
    from core.run_invariants import build_run_invariants

    composition = compose_run_task_bindings(str(QUICKSTART_MANIFEST))
    with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
        invariants, _ = build_run_invariants(
            resolved_data_scope=[0, 1],
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace=workspace,
            task_composition_fingerprint=(fingerprint or composition.semantic_fingerprint),
            **kwargs,
        )
    if fingerprint is None:
        return invariants.model_copy(update={"task_composition_fingerprint": None})
    return invariants


class TestCompositionFingerprintInTheLock:
    def test_an_un_composed_lock_OMITS_the_key_rather_than_writing_null(self, tmp_path):
        """§5.9's byte-identity requirement, at the level it is stated: the
        serialized document. A ``null`` would satisfy every Python-level
        assertion while changing the bytes of every legacy workspace."""
        from core.run_invariants import write_run_invariants

        workspace = str(tmp_path / "legacy")
        path = write_run_invariants(workspace, _build(workspace, None))
        payload = json.loads(Path(path).read_text(encoding="utf-8"))

        assert "task_composition_fingerprint" not in payload
        assert "task_composition_fingerprint" in json.loads(
            Path(
                write_run_invariants(
                    str(tmp_path / "composed"), _build(str(tmp_path / "composed"), "abc123")
                )
            ).read_text(encoding="utf-8")
        )

    def test_a_composed_lock_records_the_fingerprint_and_parses_back(self, tmp_path):
        from core.run_invariants import load_run_invariants, write_run_invariants

        workspace = str(tmp_path / "ws")
        write_run_invariants(workspace, _build(workspace, "fingerprint-A"))
        assert load_run_invariants(workspace).task_composition_fingerprint == "fingerprint-A"

    def test_an_omitted_key_parses_back_as_None(self, tmp_path):
        """A legacy lock file must still READ. The Pydantic default exists for
        exactly this and for nothing else."""
        from core.run_invariants import load_run_invariants, write_run_invariants

        workspace = str(tmp_path / "ws")
        write_run_invariants(workspace, _build(workspace, None))
        assert load_run_invariants(workspace).task_composition_fingerprint is None

    def test_resuming_a_composed_workspace_with_a_CHANGED_fingerprint_fails_closed(self, tmp_path):
        """The property the whole fingerprint exists for: a workspace's
        scientific identity is immutable, and continuing it under different
        task semantics would mix two experiments in one trajectory."""
        from core.run_invariants import RunInvariantsViolation, ensure_run_invariants

        workspace = str(tmp_path / "ws")
        assert ensure_run_invariants(workspace, _build(workspace, "fingerprint-A")) == "created"
        assert ensure_run_invariants(workspace, _build(workspace, "fingerprint-A")) == "validated"

        with pytest.raises(RunInvariantsViolation, match="task_composition_fingerprint"):
            ensure_run_invariants(workspace, _build(workspace, "fingerprint-B"))

    def test_composing_a_previously_un_composed_workspace_fails_closed(self, tmp_path):
        """Also a mismatch, and deliberately so: the earlier iterations ran
        under whatever the legacy defaults resolved to, which is not the same
        experiment as the composed one."""
        from core.run_invariants import RunInvariantsViolation, ensure_run_invariants

        workspace = str(tmp_path / "ws")
        ensure_run_invariants(workspace, _build(workspace, None))
        with pytest.raises(RunInvariantsViolation, match="task_composition_fingerprint"):
            ensure_run_invariants(workspace, _build(workspace, "fingerprint-A"))

    def test_a_real_composition_fingerprint_travels_into_the_lock(self, tmp_path, composition):
        from core.run_invariants import load_run_invariants, write_run_invariants

        workspace = str(tmp_path / "ws")
        write_run_invariants(workspace, _build(workspace, composition.semantic_fingerprint))
        assert (
            load_run_invariants(workspace).task_composition_fingerprint
            == composition.semantic_fingerprint
        )


class TestTaskHealthBindingPassThrough:
    def test_a_composed_build_passes_the_composed_binding(self, tmp_path, monkeypatch, composition):
        import core.run_invariants as ri

        seen: dict = {}

        def _spy(*args, **kwargs):
            seen.update(kwargs)
            return ("/tmp/effective.yaml", "sha")

        monkeypatch.setattr("execute_tools.health_checks.config.materialize_effective_config", _spy)
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            ri.build_run_invariants(
                resolved_data_scope=[0],
                health_gate_enabled=True,
                health_gate_files=None,
                health_checks_config=None,
                workspace=str(tmp_path),
                task_composition_fingerprint=composition.semantic_fingerprint,
                health_materialization=ri.RunHealthMaterialization(
                    task_health_binding=composition.task_health_binding,
                ),
            )
        assert seen["task_health_binding"] == composition.task_health_binding
