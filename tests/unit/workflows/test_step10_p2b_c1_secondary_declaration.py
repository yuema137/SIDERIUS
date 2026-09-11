"""Step 10 / P2b — C1: a task DECLARES its secondaries and a run BINDS them.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2b_secondary_metric_transport.md`` §4.1, §6 C1.

The defects only this module catches
------------------------------------
Scientific secondary-metric roster, direction, order and provenance parity now
belongs to the external consumer witness in
``siderius-exp/tests/test_secondary_metric_parity.py``. This infrastructure
module retains only generic composition behavior:

1. **Fingerprint churn breaking existing composed resumes.** The secondary
   payload key is additive WHEN NON-EMPTY. A key that were always present would
   move the fingerprint of every composed run that exists today. Pinned against
   a sha captured BEFORE the production change, not recomputed on both sides of
   one run.
2. **Re-implemented fail-closed branches.** ``_compose_secondary_metrics`` must
   CALL ``_compose_metric`` rather than copy it; a copy would drift. Proven by
   driving an inherited branch (a missing ``implementation``) through a
   secondary entry and requiring the inherited message.
3. **The two rules a single metric cannot violate**: an id declared twice, and
   an id that is already the primary's.
4. **A binding that does not unwind.** A ContextVar left set would leak one
   run's declared family into the next run in the same process.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from execute_tools.evaluation_metric import (
    bind_run_secondary_metrics,
    resolve_bound_run_secondary_metrics,
)
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from workflows.task_composition import (
    CompositionNotBoundError,
    TaskCompositionError,
    bind_run_task_composition,
    compose_run_task_bindings,
    verify_composition_is_bound,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

#: Semantic fingerprints CAPTURED AT `3dc298f1` — the P2b freeze commit, before
#: any production line of this milestone existed. They are frozen evidence, not
#: a value this module recomputes: a test that hashed the same manifest twice
#: in one run would pass for any implementation of the additive rule.
#:
#: If one of these goes red, first establish WHICH input moved. A change to
#: `configs/task_config.yaml`, a shipped declaration or a task-health config
#: legitimately changes a fingerprint and the literal is then updated with the
#: reason recorded. A change caused by P2b's own machinery on a manifest that
#: declares NO secondary is a defect in the additive rule.
PRE_P2B_FINGERPRINTS = {
    "fourth_task": "cef7656eb958202ed10a806c45de1a8dfa06b2a063b95488f0fcd9aa0d973507",
}


def _manifest(task: str) -> str:
    return str(FIXTURES / task / "composition.yaml")


def _compose(task: str):
    return compose_run_task_bindings(_manifest(task))


def _copy_pack(tmp_path: Path) -> Path:
    """Create a writable synthetic task package under ``tmp_path``."""
    task = "fourth_task"
    destination = tmp_path / task
    shutil.copytree(FIXTURES / task, destination)
    manifest = destination / "composition.yaml"
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))

    def _absolutize(section: dict) -> None:
        for key in ("declaration", "config"):
            value = section.get(key)
            if isinstance(value, str) and value.startswith(".."):
                section[key] = str((FIXTURES / task / value).resolve())
        implementation = section.get("implementation")
        if isinstance(implementation, dict):
            ref = implementation.get("file")
            if isinstance(ref, str) and ref.startswith(".."):
                implementation["file"] = str((FIXTURES / task / ref).resolve())

    for key, value in raw.items():
        if isinstance(value, dict):
            _absolutize(value)
        elif key == "secondary_metrics" and isinstance(value, list):
            for entry in value:
                _absolutize(entry)
    manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return manifest


def _secondary_manifest(tmp_path: Path, *, count: int = 2) -> Path:
    """Copy the synthetic pack and declare one or two observational metrics."""
    manifest = _copy_pack(tmp_path)
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    declarations = (
        ("metric_band_bias.json", "BandBiasMetric"),
        ("metric_band_spread.json", "BandSpreadMetric"),
    )
    raw["secondary_metrics"] = [
        {
            "declaration": f"declared/{declaration}",
            "implementation": {
                "file": "plugins/secondary_metrics.py",
                "symbol": symbol,
            },
        }
        for declaration, symbol in declarations[:count]
    ]
    manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# 1. The constraints — every one fails the COMPOSITION, so the run never starts
# ---------------------------------------------------------------------------


class TestTheFailClosedBranches:
    def _mutate(self, tmp_path: Path, mutate, *, with_secondaries: bool = True) -> str:
        manifest = _secondary_manifest(tmp_path) if with_secondaries else _copy_pack(tmp_path)
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        mutate(raw)
        manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
        return str(manifest)

    def test_a_duplicate_secondary_id_is_refused_by_id(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"].append(raw["secondary_metrics"][0])

        with pytest.raises(TaskCompositionError, match="'band_bias'"):
            compose_run_task_bindings(self._mutate(tmp_path, mutate))

    def test_a_secondary_that_is_the_primary_is_refused_by_id(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"].append(
                {
                    "declaration": raw["metric"]["declaration"],
                    "implementation": raw["metric"]["implementation"],
                }
            )

        with pytest.raises(TaskCompositionError, match="PRIMARY"):
            compose_run_task_bindings(self._mutate(tmp_path, mutate))

    def test_a_mapping_where_a_list_belongs_names_the_shape(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"] = {"band_bias": {}}

        with pytest.raises(TaskCompositionError, match="must be a LIST"):
            compose_run_task_bindings(self._mutate(tmp_path, mutate))

    def test_a_non_mapping_entry_is_refused(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"] = ["metric_band_bias.json"]

        with pytest.raises(TaskCompositionError, match=r"secondary_metrics\[0\] must be a mapping"):
            compose_run_task_bindings(self._mutate(tmp_path, mutate))

    def test_an_inherited_branch_fires_with_the_SECONDARY_s_role_named(self, tmp_path):
        """Proof of REUSE, not reimplementation.

        A missing `implementation` is one of `_compose_metric`'s own five
        fail-closed branches. It must fire for a secondary entry — and the
        message must name `secondary_metrics[1]`, not `metric`, or an operator
        reading the refusal would be sent to the wrong section. A copied
        implementation would either miss the branch or keep the primary's
        hardcoded role.
        """

        def mutate(raw):
            del raw["secondary_metrics"][1]["implementation"]

        with pytest.raises(
            TaskCompositionError,
            match=r"secondary_metrics\[1\] requires an 'implementation' mapping",
        ):
            compose_run_task_bindings(self._mutate(tmp_path, mutate))

    def test_an_unimportable_secondary_implementation_fails_the_run_closed(self, tmp_path):
        def mutate(raw):
            # REPLACE the implementation, never add a key to it. Since D4c the
            # Synthetic secondaries bind by `file:`, so setting `module` alongside
            # it would trip the exactly-ONE-of check first and this test would
            # pass on the wrong refusal.
            raw["secondary_metrics"][0]["implementation"] = {
                "module": "no.such.module",
                "symbol": "Whatever",
            }

        with pytest.raises(TaskCompositionError, match="could not be imported"):
            compose_run_task_bindings(self._mutate(tmp_path, mutate))

    def test_the_primary_s_own_messages_are_unchanged(self, tmp_path):
        """The `where` parameter defaults to "metric", so adding it moved no
        primary byte."""

        def mutate(raw):
            del raw["metric"]["implementation"]

        with pytest.raises(
            TaskCompositionError, match=r"^metric requires an 'implementation' mapping"
        ):
            compose_run_task_bindings(self._mutate(tmp_path, mutate, with_secondaries=False))

    def test_an_unknown_manifest_key_is_still_refused(self, tmp_path):
        def mutate(raw):
            raw["secondary_metric"] = []  # a plausible misspelling

        with pytest.raises(TaskCompositionError, match="unknown key"):
            compose_run_task_bindings(self._mutate(tmp_path, mutate, with_secondaries=False))


# ---------------------------------------------------------------------------
# 2. The fingerprint — additive WHEN NON-EMPTY (delta D3)
# ---------------------------------------------------------------------------


class TestTheFingerprintRule:
    @pytest.mark.parametrize("task", ["fourth_task"])
    def test_a_zero_secondary_manifest_hashes_to_its_PRE_P2B_value(self, task):
        """The whole point of the additive-when-non-empty rule.

        Compared against a literal captured at the freeze commit, so this
        cannot pass by hashing the same thing twice.
        """
        assert _compose(task).semantic_fingerprint == PRE_P2B_FINGERPRINTS[task], (
            f"the {task} composition declares no secondary, yet its semantic "
            "fingerprint moved. Every existing composed run of this task now "
            "fails its resume for a reason with no scientific content."
        )

    def test_declaring_a_secondary_DOES_change_the_fingerprint(self, tmp_path):
        declared = compose_run_task_bindings(str(_secondary_manifest(tmp_path, count=1)))
        assert declared.semantic_fingerprint != PRE_P2B_FINGERPRINTS["fourth_task"]

    def test_an_explicitly_empty_list_equals_the_section_being_absent(self, tmp_path):
        manifest = _copy_pack(tmp_path)
        without = compose_run_task_bindings(str(manifest))
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        raw["secondary_metrics"] = []
        manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
        with_empty = compose_run_task_bindings(str(manifest))
        assert with_empty.secondary_metrics == () == without.secondary_metrics
        assert with_empty.semantic_fingerprint == without.semantic_fingerprint

    def test_reordering_two_secondaries_changes_the_fingerprint(self, tmp_path):
        """Manifest order is SEMANTIC — it is the declared set the output
        stamps — so a reordered manifest is a different declaration."""
        manifest = _secondary_manifest(tmp_path)
        first = compose_run_task_bindings(str(manifest))
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        raw["secondary_metrics"].reverse()
        manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
        second = compose_run_task_bindings(str(manifest))
        assert first.semantic_fingerprint != second.semantic_fingerprint
        assert [m.spec.id for m in second.secondary_metrics] == ["band_spread", "band_bias"]

    def test_the_same_declared_family_at_two_paths_yields_ONE_fingerprint(self, tmp_path):
        """Q-P1-2 held: a relocated task package is the same science."""
        a = compose_run_task_bindings(str(_secondary_manifest(tmp_path / "a")))
        b = compose_run_task_bindings(str(_secondary_manifest(tmp_path / "b")))
        assert a.semantic_fingerprint == b.semantic_fingerprint


# ---------------------------------------------------------------------------
# 3. Binding — run-scoped, and it unwinds
# ---------------------------------------------------------------------------


class TestTheRunScopedBinding:
    def test_unbound_resolves_to_the_empty_tuple(self):
        assert resolve_bound_run_secondary_metrics() == ()

    def test_the_composition_binding_activates_the_declared_family(self, tmp_path):
        composition = compose_run_task_bindings(str(_secondary_manifest(tmp_path)))
        assert resolve_bound_run_secondary_metrics() == ()
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            bound = resolve_bound_run_secondary_metrics()
            assert [m.spec.id for m in bound] == ["band_bias", "band_spread"]
            assert bound == composition.secondary_metrics
        assert resolve_bound_run_secondary_metrics() == ()

    def test_a_zero_secondary_composition_binds_the_empty_tuple(self, tmp_path):
        with bind_run_task_composition(
            compose_run_task_bindings(str(_copy_pack(tmp_path))),
            physical_data_root=COMPOSED_TEST_DATA_ROOT,
        ):
            assert resolve_bound_run_secondary_metrics() == ()

    def test_a_none_composition_is_refused(self):
        from workflows.task_composition import TaskCompositionError

        with pytest.raises(TaskCompositionError, match="task composition is required"):
            with bind_run_task_composition(None):
                pass

    def test_nested_runs_do_not_leak_into_each_other(self, tmp_path):
        outer = compose_run_task_bindings(str(_secondary_manifest(tmp_path / "outer")))
        inner = compose_run_task_bindings(str(_secondary_manifest(tmp_path / "inner", count=1)))
        with bind_run_task_composition(outer, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            with bind_run_task_composition(inner, physical_data_root=COMPOSED_TEST_DATA_ROOT):
                assert [m.spec.id for m in resolve_bound_run_secondary_metrics()] == ["band_bias"]
            assert [m.spec.id for m in resolve_bound_run_secondary_metrics()] == [
                "band_bias",
                "band_spread",
            ]
        assert resolve_bound_run_secondary_metrics() == ()

    def test_the_binding_unwinds_on_an_exception(self, tmp_path):
        composition = compose_run_task_bindings(str(_secondary_manifest(tmp_path)))
        with (
            pytest.raises(RuntimeError, match="forced"),
            bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT),
        ):
            raise RuntimeError("forced")
        assert resolve_bound_run_secondary_metrics() == ()

    def test_verify_refuses_a_composition_whose_secondaries_are_not_active(self, tmp_path):
        """A half-composed run that stamped a declared family it never
        evaluated would project the WHOLE family as a named absence — silent,
        and indistinguishable from a task that declared nothing."""
        composition = compose_run_task_bindings(str(_secondary_manifest(tmp_path)))
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            verify_composition_is_bound(composition)  # the healthy case
            with bind_run_secondary_metrics(()):
                with pytest.raises(CompositionNotBoundError, match="secondary_metrics"):
                    verify_composition_is_bound(composition)


# ---------------------------------------------------------------------------
# 4. Ownership — one binder, in one module (the C1 half of the Q097 inversion)
# ---------------------------------------------------------------------------


class TestTheBinderHasExactlyOneOwner:
    """Step 09a's `test_no_production_module_evaluates_a_secondary_metric`
    asserted this shape did not exist anywhere. P2b C1 INVERTS the binder
    half: it must now exist, in its named owner, and nowhere else."""

    OWNER = "src/execute_tools/evaluation_metric.py"

    def test_the_binder_pair_lives_only_in_evaluation_metric(self):
        import re

        offenders: dict[str, list[str]] = {}
        for root in ("src/nodes", "src/agent", "src/core", "src/execute_tools", "src/workflows"):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                hits = re.findall(
                    r"^def ((?:bind|resolve)\w*secondary\w*)\(",
                    path.read_text(encoding="utf-8"),
                    re.M,
                )
                if hits:
                    offenders[path.relative_to(REPO_ROOT).as_posix()] = sorted(hits)
        assert offenders == {
            self.OWNER: ["bind_run_secondary_metrics", "resolve_bound_run_secondary_metrics"]
        }, (
            "the run-scoped secondary binding must have exactly one owner — a "
            f"second binder is a second way for a declared family to exist: {offenders}"
        )
