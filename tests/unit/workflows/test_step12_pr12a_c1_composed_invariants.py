"""Step 12 / PR-12a — C1: projection-independent composed-invariant closure.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C1 (F-12-1 + D-12a-2's source half).

These are the PERMANENT owners of two properties whose C0 inverted guards this
commit retires (R-11-10: replace, never twin).

    F-12-1     a composed run's pre-flight resolves `resolved_data_scope`
               against ITS OWN declared topology, not TIDMAD's constant
    D-12a-2    the workflow hands the tuner the Health config the run
               ACTUALLY READS, so a composed run's per-model gates are the
               TASK's family and not TIDMAD's

Neither fix reads the typed composition projection — that lands in C2 with
every consumer at once, and the frozen ordering rule forbids an interim state
in which a commit reads an authority the next commit replaces.

WHAT C1 DELIBERATELY DOES NOT CLOSE
-----------------------------------
The per-model effective document's binding MARKERS. Handing over the
chain-level effective config fixes the ROSTER — measured below — but 08b
restamps `body_markers()` from the binding it was called with, and the tuner
still passes none, so its document says ``legacy_default`` while carrying the
task's gates. Body-sha equality with the chain is therefore **C2's**
acceptance, not C1's: it needs the ``task_health_binding`` kwarg, which comes
from the projection. Recorded rather than quietly redefined — see the design
ledger §8.2.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import pytest
import yaml

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from sdsc_submission_scripts.run_one_iteration import compute_expected_invariants
from workflows.task_composition import compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

#: The three composition fixtures and the topology each DECLARES. Hand-written
#: from the fixtures' own `dataset_profile.json`, never read back from the
#: object under test.
DECLARED_NUM_FILES = {"tidmad": 20, "pets": 4, "davis": 3}


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """Health registration is process-global; restore it around every drive."""
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


def _preflight_args(workspace: str) -> argparse.Namespace:
    """The argparse surface ``compute_expected_invariants`` actually reads."""
    return argparse.Namespace(
        data_scope=None,
        health_gate_enabled=False,
        health_gate_files=None,
        health_checks_config=None,
        workspace=workspace,
        order_strategy_override=None,
        file_order_override=None,
        enable_structured_health_feedback=False,
        health_feedback_history_window_iterations=3,
        health_feedback_history_max_entries_per_model=8,
    )


# ======================================================================
# F-12-1 — the composed pre-flight resolves the RUN's topology
# ======================================================================


class TestF121PreflightResolvesTheRunsTopology:
    """Replaces C0's inverted guard (a).

    HOW IT FAILS WHEN THE BEHAVIOUR BREAKS: re-inline the TIDMAD constant and
    every composed row below locks 20 files, so a 4-file task's workspace lock
    claims a topology it does not have — and iteration 2's pre-flight then
    disagrees with iteration 1's lock and the chain refuses itself.
    """

    @pytest.mark.parametrize("task", sorted(DECLARED_NUM_FILES))
    def test_the_lock_scope_is_the_tasks_own_topology(self, task, tmp_path):
        composition = compose_run_task_bindings(str(FIXTURES / task / "composition.yaml"))
        invariants = compute_expected_invariants(
            _preflight_args(str(tmp_path)), run_composition=composition
        )
        assert invariants.resolved_data_scope == list(range(DECLARED_NUM_FILES[task]))

    def test_two_composed_tasks_of_different_size_do_not_collapse(self, tmp_path):
        """Anti-vacuity. Parametrized rows can all pass while resolving one
        shared value if the expectation were read back from the object; these
        two must DIFFER, and they must differ by the declared amount."""
        (tmp_path / "p").mkdir()
        (tmp_path / "d").mkdir()
        pets = compute_expected_invariants(
            _preflight_args(str(tmp_path / "p")),
            run_composition=compose_run_task_bindings(str(FIXTURES / "pets" / "composition.yaml")),
        )
        davis = compute_expected_invariants(
            _preflight_args(str(tmp_path / "d")),
            run_composition=compose_run_task_bindings(str(FIXTURES / "davis" / "composition.yaml")),
        )
        assert pets.resolved_data_scope == [0, 1, 2, 3]
        assert davis.resolved_data_scope == [0, 1, 2]

    def test_an_un_composed_run_is_unchanged(self, tmp_path):
        """LEGACY PARITY. Un-composed, the resolver returns ``TIDMAD_PROFILE``
        and ``tidmad_topology(TIDMAD_PROFILE).dataset`` IS the singleton the constant named —
        the same object — so this value cannot have moved."""
        invariants = compute_expected_invariants(_preflight_args(str(tmp_path)))
        assert invariants.resolved_data_scope == list(range(20))

    def test_the_launcher_no_longer_imports_a_task_singleton(self):
        """Reachability + a head start on F-12-6: the fix removed the reason
        this launcher imported ``TIDMAD`` at all, so the import is gone rather
        than left dormant for the next reader to re-use."""
        source = (REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported |= {alias.name for alias in node.names}
        assert "TIDMAD" not in imported
        assert "TIDMAD_PROFILE" not in imported
        assert "resolve_dataset_profile" in imported


class TestW7ValueAgreement:
    """Extends the W7 agreement census (``test_step10_p56_c5_wiring_closures.py``
    ``TestW7PreflightAndWorkflowAgree``) from the KEYWORD SETS to the VALUE.

    W7 proved the two ``build_run_invariants`` call sites pass the same
    composition-derived keyword NAMES. F-12-1 lived in the blind spot that
    leaves: ``resolved_data_scope`` is passed by both sites, spelled
    identically, and computed from different topologies. A keyword-set census
    is structurally incapable of seeing that, which is why the value is
    censused here.
    """

    @pytest.mark.parametrize("task", ["pets", "davis"])
    def test_the_preflight_and_the_workflow_lock_the_same_scope(self, task, tmp_path):
        from tests.unit.workflows.test_step10_p56_c6_three_task_closure import drive

        seen = drive(task, tmp_path)
        lock = json.loads(
            (Path(seen["workspace"]) / "run_invariants_lock.json").read_text(encoding="utf-8")
        )

        preflight_dir = tmp_path / "preflight"
        preflight_dir.mkdir()
        preflight = compute_expected_invariants(
            _preflight_args(str(preflight_dir)), run_composition=seen["composition"]
        )

        assert preflight.resolved_data_scope == lock["resolved_data_scope"]
        assert preflight.resolved_data_scope == list(range(DECLARED_NUM_FILES[task]))


# ======================================================================
# D-12a-2 (source half) — the tuner is handed the config the run reads
# ======================================================================


class TestComposedHealthConfigHandoff:
    """Replaces C0's inverted guard (b-health)'s composed half.

    The defect this closes was not cosmetic: a composed Pets run with gates ON
    could not START. TIDMAD's roster peeks file indices ``[10, 17]``, outside
    Pets' 4-file scope, so ``validate_health_scope`` refused the run naming
    another task's gates (ledger F-12a-C0-1).
    """

    @staticmethod
    def _handed_config(task: str, tmp_path: Path) -> tuple[str, dict]:
        from tests.unit.workflows.test_step10_p56_c6_three_task_closure import drive

        seen = drive(task, tmp_path)
        handed = seen["tune_in"][0].health_checks_config
        assert handed, f"{task}: the workflow handed the tuner no Health config at all"
        return handed, yaml.safe_load(Path(handed).read_text(encoding="utf-8"))

    def test_the_tuner_is_handed_the_chain_effective_config(self, tmp_path):
        handed, document = self._handed_config("pets", tmp_path)
        assert Path(handed).name == "health_checks_effective.yaml"
        assert Path(handed).exists()
        assert document["task_health_binding"] == "explicit"

    def test_the_handed_roster_is_the_TASKS_family(self, tmp_path):
        """The decisive assertion. TIDMAD's gate ids must be absent and the
        task's own must be present — not merely 'some roster is present'."""
        _handed, document = self._handed_config("pets", tmp_path)
        gate_ids = {gate["id"] for gate in document["health_gates"]}
        assert gate_ids == {"pets_distinct_symbols_blocking", "pets_dominant_fraction_blocking"}
        assert not gate_ids & {
            "output_diversity_blocking",
            "output_std_blocking",
            "amplitude_collapse_blocking",
        }

    def test_re_materializing_the_handed_value_keeps_the_tasks_roster(self, tmp_path):
        """The tuner materializes AGAIN from whatever it is handed. That second
        pass must be a roster no-op — otherwise the hand-off buys nothing.

        It is deliberately NOT asserted to be a body-sha no-op: 08b restamps
        the binding markers and the tuner still passes no binding, so its
        document says ``legacy_default``. Closing that is C2's, with the
        projection. Asserting sha equality here would fail for a reason C1 is
        not allowed to fix, and asserting nothing would let the roster silently
        revert.
        """
        from execute_tools.health_checks.config import materialize_effective_config
        from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
        from workflows.task_composition import bind_run_task_composition

        handed, chain_document = self._handed_config("pets", tmp_path)
        model_workspace = tmp_path / "per_model"
        model_workspace.mkdir()

        # Bound, because that is how the tuner runs: `validate_health_scope`
        # asks `resolve_dataset_profile()` how many files a FULL scope has, so
        # an unbound call would judge Pets' complete [0,1,2,3] against
        # TIDMAD's 20 and call it partial.
        composition = compose_run_task_bindings(str(FIXTURES / "pets" / "composition.yaml"))
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            path, _sha = materialize_effective_config(
                handed, None, str(model_workspace), resolved_scope=[0, 1, 2, 3]
            )
        per_model = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        assert [g["id"] for g in per_model["health_gates"]] == [
            g["id"] for g in chain_document["health_gates"]
        ]
        assert per_model["task_health_binding"] == "legacy_default"  # C2 closes this

    def test_an_un_composed_run_is_handed_the_raw_operator_value(self, workflow_env):
        """LEGACY PARITY, and the reason the swap is keyed on composition
        PRESENCE rather than applied unconditionally: the tuner captures this
        value as ``health_checks_config_source`` BEFORE its own effective
        swap, and that is a PERSISTED output field and record key. Swapping it
        for a legacy run would move recorded provenance from ``None`` to a
        path — a legacy byte movement this PR does not license.
        """
        from workflows.model_exploration import run_workflow
        from workflows.run_config import WorkflowLaunchConfig

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
            ),
            workspace=workflow_env["workspace"],
            run_name="pr12a_c1_legacy",
        )
        tune_input = workflow_env["tune"].return_value.run.call_args[0][0]
        assert tune_input.health_checks_config is None

    @pytest.mark.parametrize(
        ("composed", "effective", "operator", "expected"),
        [
            (
                object(),
                "/ws/health_checks_effective.yaml",
                None,
                "/ws/health_checks_effective.yaml",
            ),
            (
                object(),
                "/ws/health_checks_effective.yaml",
                "/op.yaml",
                "/ws/health_checks_effective.yaml",
            ),
            (object(), None, "/op.yaml", "/op.yaml"),  # composed, gates OFF
            (None, "/ws/health_checks_effective.yaml", None, None),  # LEGACY, gates ON
            (None, "/ws/health_checks_effective.yaml", "/op.yaml", "/op.yaml"),
            (None, None, None, None),
        ],
    )
    def test_the_resolution_truth_table(self, composed, effective, operator, expected):
        """The extracted authority, exhaustively. The fourth row is the one
        that matters most: a LEGACY run with gates ON keeps ``None``, which is
        what stops a persisted provenance field from moving."""
        from workflows.model_exploration import resolve_tuner_health_config_source

        assert (
            resolve_tuner_health_config_source(
                task_composition=composed,
                effective_config_path=effective,
                operator_config=operator,
            )
            == expected
        )

    def test_the_decision_is_a_named_boundary_not_a_branch_in_the_orchestrator(self):
        """C-P56-1 plus the structural rule. The discriminator may never be a
        task-identity surrogate, and the orchestrator gains a CALL rather than
        another conditional — ``run_workflow`` is already 1,500+ lines and its
        §12.1 sibling-shape tripwire pins the branch count.
        """
        import inspect
        import textwrap

        from workflows import model_exploration
        from workflows.model_exploration import resolve_tuner_health_config_source

        # The EXECUTABLE body, with the docstring removed: the docstring
        # names TIDMAD to explain the defect, which is prose, not dispatch.
        function = next(
            node
            for node in ast.walk(
                ast.parse(textwrap.dedent(inspect.getsource(resolve_tuner_health_config_source)))
            )
            if isinstance(node, ast.FunctionDef)
        )
        statements = function.body[1:] if ast.get_docstring(function) else function.body
        executable = "\n".join(ast.unparse(node) for node in statements)
        assert "tidmad" not in executable.lower()
        assert "task_composition is None" in executable

        workflow = inspect.getsource(model_exploration.run_workflow)
        assert "health_checks_config=resolve_tuner_health_config_source(" in workflow


# ``workflow_env`` is the established un-composed ``run_workflow`` harness; it
# is imported rather than re-created so the legacy drive in this module is the
# SAME legacy drive the workflow suite already uses.
from tests.unit.workflows.test_model_exploration import workflow_env  # noqa: E402
