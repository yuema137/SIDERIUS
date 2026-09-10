"""The tuner really resolves a capability, and an unavailable one says why.

V20 PR C1 / C-C3b.

C-C3a built the boundary; this proves the production path uses it. Without
that, the boundary is a component built, tested and never called -- the
shape of #156, #157, #159 and the A5 field-drop, three of which were found
during this very PR's audit.

The concrete risk being guarded: `_resolve_time_check_probe_request` used to
call `probe_runner_availability()` with no argument, which reached for
`TIDMAD_DATA_DIR` itself and returned a bare False on any other task. If the
tuner ever reverts to the no-argument form, generic runtime-control answers
"no capability was resolved by the caller" and the measured-evidence path
goes off again -- silently, unless something asserts otherwise.

Verified during C-C3b that the existing suite did NOT catch that: reverting
the call site to `probe_runner_availability()` left all 23 launch-guard
tests green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nodes.ml_hyperparameter_tune_agent as tuner
from core.runtime_control.measurement_capability import (
    ResolvedMeasurementCapability,
    resolve_measurement_capability,
)
from core.runtime_control.probe_wiring import probe_runner_availability
from tests.helpers.tuner_source import tuner_node_source


def _resolver_call() -> ast.Call:
    """The `probe_runner_availability(...)` call inside the tuner."""
    tree = ast.parse(tuner_node_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "probe_runner_availability":
                return node
    raise AssertionError("the tuner no longer calls probe_runner_availability at all")


class TestTheTunerResolvesACapability:
    def test_the_call_site_passes_one(self):
        """The reachability assertion. Reverting the tuner to the
        no-argument form -- which is what silently disabled the measured
        path on non-TIDMAD tasks -- fails here."""
        call = _resolver_call()
        assert call.args or call.keywords, (
            "the tuner calls probe_runner_availability() with no capability; "
            "generic runtime-control then reports that none was resolved and "
            "the measured-evidence path switches itself off"
        )

    def test_it_consumes_the_caller_resolved_capability(self):
        """Generic tuning must not pick the dataset or task identity."""
        source = tuner_node_source()
        assert "measurement_capability" in source
        assert "resolve_tidmad_measurement_capability" not in source

    def test_the_resolved_root_is_the_one_the_probe_will_use(self):
        """`data_dir` is already a parameter of the enclosing function, so
        the capability describes the dataset the probe actually runs on --
        not a second, independently resolved path that could disagree."""
        call = _resolver_call()
        # The capability handed over must be the local resolved from data_dir,
        # not a fresh no-argument resolution.
        assert any(isinstance(a, ast.Name) and a.id == "capability" for a in call.args)


class TestAnUnavailableCapabilityExplainsItself:
    def test_generic_code_refuses_rather_than_choosing_a_dataset(self):
        available, detail = probe_runner_availability(None)
        assert available is False
        assert "no measurement capability was resolved" in detail

    def test_a_missing_dataset_root_reports_a_reason(self, tmp_path):
        cap = resolve_measurement_capability(
            task_identity="fixture_task",
            dataset_adapter="fixture_adapter",
            data_shape_class="fixture_shape",
            dataset_root=str(tmp_path / "absent"),
        )
        assert cap.probe_available is False
        assert cap.unavailability_reason
        available, detail = probe_runner_availability(cap)
        assert available is False
        assert cap.unavailability_reason in detail

    def test_the_task_identity_survives_an_unavailable_verdict(self, tmp_path):
        """ "We cannot measure tidmad_denoise" beats "we cannot measure": the
        record of WHY the path was off has to name what was being measured.
        """
        cap = resolve_measurement_capability(
            task_identity="fixture_task",
            dataset_adapter="fixture_adapter",
            data_shape_class="fixture_shape",
            dataset_root=str(tmp_path / "absent"),
        )
        assert cap.task_identity == "fixture_task"
        assert cap.data_shape_class

    def test_the_tuner_records_the_reason_not_a_bare_false(self):
        """The unavailable branch stamps the task and the reason into the
        breakdown. A bare `probe_resolution="unavailable"` is what let the
        V19 posture persist without anyone noticing which task was silently
        unmeasurable."""
        source = tuner_node_source()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert 'breakdown["probe_capability_reason"]' in code
        assert 'breakdown["probe_capability_task"]' in code


class TestTheBoundaryStaysGeneric:
    def test_probe_wiring_no_longer_imports_the_task_dataset(self):
        """AST, not text: `probe_wiring`'s docstring names `TIDMAD_DATA_DIR`
        while explaining what it stopped doing, and commentary about a
        symbol is not a use of it."""
        import core.runtime_control.probe_wiring as mod

        tree = ast.parse(Path(mod.__file__).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)

        offenders = sorted(n for n in imported if "data_paths" in n or "dataset_config" in n)
        assert offenders == [], f"generic probe wiring imports task-owned modules: {offenders}"

    def test_the_capability_type_is_what_crosses_the_boundary(self):
        cap = resolve_measurement_capability(
            task_identity="fixture_task",
            dataset_adapter="fixture_adapter",
            data_shape_class="fixture_shape",
            dataset_root=None,
        )
        assert isinstance(cap, ResolvedMeasurementCapability)


class TestTheWorkflowIsSuppliedACapability:
    """The OTHER call site, missed when C-C3b fixed the tuner's.

    `workflows/model_exploration.py` called `run_launch_self_test(...)`
    without `capability`. It defaults to `None`, generic runtime-control
    reports "no measurement capability was resolved by the caller", and a
    real launch (`require_probe_runner=True`) raises `LaunchGuardFailure`
    before any LLM call.

    Measured, not theorised: a bounded real chain aborted with exactly that
    message while `resolve_tidmad_measurement_capability()` reported the
    dataset available. The class above proved the TUNER resolves one;
    nothing asserted the same of the workflow — the gap this module's own
    docstring warns about.

    **The shape matters as much as the fix.** Generic orchestration must
    not name a task's resolver, so the capability is resolved by the
    task-aware launcher and THREADED IN, exactly as
    `measurement_capability.py` specifies: "Callers that know the task
    supply those."
    """

    @staticmethod
    def _launch_self_test_call() -> ast.Call:
        import workflows.model_exploration as workflow

        tree = ast.parse(Path(workflow.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name == "run_launch_self_test":
                    return node
        raise AssertionError("the workflow no longer calls run_launch_self_test at all")

    def test_the_workflow_passes_a_capability(self):
        """MUTATION TARGET: dropping the argument again."""
        call = self._launch_self_test_call()
        assert "capability" in {kw.arg for kw in call.keywords}, (
            "the workflow calls run_launch_self_test() without a capability; "
            "a real launch will abort with LaunchGuardFailure even when the "
            "measurement capability is available"
        )

    def test_the_workflow_accepts_one_rather_than_resolving_it(self):
        """GENERICITY. The workflow takes a typed capability as a parameter;
        it must not reach for a task's dataset itself."""
        import inspect

        import workflows.model_exploration as workflow

        assert "measurement_capability" in inspect.signature(workflow.run_workflow).parameters

    def test_no_task_resolver_is_named_in_generic_orchestration(self):
        """MUTATION TARGET: importing the TIDMAD resolver into the workflow.

        That is the defect `measurement_capability.py` exists to end — a
        task assumption inside generic infrastructure, which fails the next
        task silently rather than loudly.
        """
        import workflows.model_exploration as workflow

        source = Path(workflow.__file__).read_text()
        for forbidden in ("resolve_tidmad", "TIDMAD_DATA_DIR", "tidmad_denoise"):
            assert forbidden not in source, (
                f"generic workflow orchestration names {forbidden!r}; the "
                f"capability must be threaded in by a caller that knows the task"
            )

    def test_the_task_aware_launcher_supplies_it(self):
        """The other half: someone must actually pass one, or the parameter
        is a boundary nobody uses.

        **F-MEASCAP-1 — UPGRADED.** This used to assert the exact substring
        ``measurement_capability=resolve_tidmad_measurement_capability()``,
        which was the DEFECT: an unconditional TIDMAD resolver, twenty-one
        lines from ``task_composition=run_composition`` in the same call. A
        source-text assertion cannot tell "someone supplies a capability" from
        "someone supplies the WRONG capability", so this one held the hardwired
        answer in place and would have gone red on the fix.

        The intent survives; the mechanism does not. What is asserted here is
        now only the structural half — the boundary has a supplier, and the
        composed half exists. The VALUE is proven behaviourally, at the real
        boundary and in both regimes, by
        ``tests/unit/sdsc_submission_scripts/test_fmeascap1_measurement_capability_composition.py``,
        whose composed witnesses are mutation-proven against exactly the line
        this assertion used to pin.
        """
        launcher = (
            Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "run_one_iteration.py"
        ).read_text()
        assert "measurement_capability=measurement_capability," in launcher, (
            "the launcher no longer threads a capability into run_workflow"
        )
        assert "resolve_composed_measurement_capability(" in launcher, (
            "the launcher resolves no composed capability; a composed run would "
            "fall back to another task's measurement identity (F-MEASCAP-1)"
        )

    def test_fail_closed_is_preserved_when_none_is_supplied(self):
        """Threading it in must not become a way to skip the check."""
        available, detail = probe_runner_availability(None)
        assert available is False
        assert "no measurement capability was resolved" in detail

    def test_supplying_a_capability_changes_the_REASON_not_just_the_answer(self):
        """The property that actually failed, stated PORTABLY.

        The first version asserted `available is True`, which needs CUDA
        and a dataset — it passed on the GPU box and failed CI, where
        neither exists. That is the machine-dependent-assertion defect the
        repository's portability rule names, and a green local run was no
        evidence of it.

        The real property is environment-INDEPENDENT and is the whole
        point of the fix: once a capability is supplied, the guard reports
        the TASK's own reason. It can still refuse — on a CPU runner it
        says "no CUDA device is visible" — but it must never again say
        "no measurement capability was resolved by the caller", which is
        the failure that aborted a real launch while the dataset was in
        fact available.
        """
        capability = resolve_measurement_capability(
            task_identity="fixture_task",
            dataset_adapter="fixture_adapter",
            data_shape_class="fixture_shape",
            dataset_root=None,
        )
        available, detail = probe_runner_availability(capability)

        assert "no measurement capability was resolved" not in detail, (
            "supplying a capability did not reach the guard"
        )
        assert capability.task_identity in detail or detail == capability.detail, (
            f"the guard did not report the task's own reason: {detail!r}"
        )
        # Availability itself is a property of the MACHINE, not of the fix.
        assert isinstance(available, bool)
