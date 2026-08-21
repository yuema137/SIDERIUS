"""Step 10 / P2b — C1: a task DECLARES its secondaries and a run BINDS them.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2b_secondary_metric_transport.md`` §4.1, §6 C1.

The defects only this module catches
------------------------------------
1. **A secondary silently inheriting the primary's direction.** DAVIS declares
   ``psnr`` (higher) and ``mae`` (lower) beside a ``mse`` primary that is
   lower-is-better. Every other layer reads the direction off the carrier, so
   if composition resolved it wrongly, every downstream renderer would confidently
   report the wrong metric as improving. Asserted as hand-written literals.
2. **Fingerprint churn breaking existing composed resumes.** The secondary
   payload key is additive WHEN NON-EMPTY. A key that were always present would
   move the fingerprint of every composed run that exists today. Pinned against
   a sha captured BEFORE the production change, not recomputed on both sides of
   one run.
3. **Re-implemented fail-closed branches.** ``_compose_secondary_metrics`` must
   CALL ``_compose_metric`` rather than copy it; a copy would drift. Proven by
   driving an inherited branch (a missing ``implementation``) through a
   secondary entry and requiring the inherited message.
4. **The two rules a single metric cannot violate**: an id declared twice, and
   an id that is already the primary's.
5. **A binding that does not unwind.** A ContextVar left set would leak one
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
    "tidmad": "d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a",
    "fourth_task": "fe00fd076153c847da65c71c72df5520bec902d6d17b43b9c7b1bb80e2ab099a",
    "pets": "52a422b030bb896cc22862b687855101ed302f2e59792b523d353b7dc67d6086",
    "davis": "9980a7a955c689a8f94ab048eee9c4715ce9a25fdaac7bf3a510197cf2e0ac26",
}


def _manifest(task: str) -> str:
    return str(FIXTURES / task / "composition.yaml")


def _compose(task: str):
    return compose_run_task_bindings(_manifest(task))


def _copy_pack(task: str, tmp_path: Path) -> Path:
    """A writable copy of a fixture task, refs to `examples/` made absolute.

    The fixture manifests reach out of the tree with `../../../../`; copying
    only the task directory would break those refs, so they are rewritten to
    absolute paths — which the loader accepts (`_resolve_path`) and which the
    fingerprint deliberately does not see (Q-P1-2).
    """
    destination = tmp_path / task
    shutil.copytree(FIXTURES / task, destination)
    manifest = destination / "composition.yaml"
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))

    def _absolutize(section: dict) -> None:
        for key in ("declaration", "config"):
            value = section.get(key)
            if isinstance(value, str) and value.startswith(".."):
                section[key] = str((FIXTURES / task / value).resolve())

    for key, value in raw.items():
        if isinstance(value, dict):
            _absolutize(value)
        elif key == "secondary_metrics" and isinstance(value, list):
            for entry in value:
                _absolutize(entry)
    manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# 1. Declaration — what each task composes to
# ---------------------------------------------------------------------------


class TestTheDeclaredSet:
    def test_tidmad_declares_none_and_that_is_a_first_class_state(self):
        assert _compose("tidmad").secondary_metrics == ()

    def test_pets_declares_exactly_macro_f1(self):
        """`log_loss` stays D16 / Step-06-owned (Q-10-4 = A) and must NOT be
        activated by P2b — an extra entry here would silently widen the
        scientific claim of every Pets run."""
        secondaries = _compose("pets").secondary_metrics
        assert [(m.spec.id, m.spec.direction) for m in secondaries] == [("macro_f1", "higher")]

    def test_davis_carries_two_OPPOSING_directions_neither_of_them_the_primary_s(self):
        """The discriminating case, as literals.

        `psnr` is higher-is-better, `mae` is lower, and the primary `mse` is
        lower. A carrier that inherited the primary's direction would report
        psnr backwards; one that inherited a single per-run secondary direction
        would report mae backwards. Only per-entry resolution passes.
        """
        composition = _compose("davis")
        assert composition.metric.spec.direction == "lower"
        assert [(m.spec.id, m.spec.direction) for m in composition.secondary_metrics] == [
            ("psnr", "higher"),
            ("mae", "lower"),
        ]

    def test_manifest_order_is_preserved_not_sorted(self):
        """Order is semantic: it is what the output stamp and the interpreter's
        absence rows are keyed on. Sorted order would put `mae` first."""
        ids = [m.spec.id for m in _compose("davis").secondary_metrics]
        assert ids == ["psnr", "mae"] != sorted(ids)

    def test_every_declaration_path_reaches_provenance(self):
        paths = _compose("davis").provenance.source_paths
        declared = [v for k, v in paths.items() if k.startswith("secondary_metric_declaration")]
        assert len(declared) == 2
        assert all(Path(p).is_file() for p in declared)


# ---------------------------------------------------------------------------
# 2. The constraints — every one fails the COMPOSITION, so the run never starts
# ---------------------------------------------------------------------------


class TestTheFailClosedBranches:
    def _mutate(self, tmp_path: Path, task: str, mutate) -> str:
        manifest = _copy_pack(task, tmp_path)
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        mutate(raw)
        manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
        return str(manifest)

    def test_a_duplicate_secondary_id_is_refused_by_id(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"].append(raw["secondary_metrics"][0])

        with pytest.raises(TaskCompositionError, match="'psnr'"):
            compose_run_task_bindings(self._mutate(tmp_path, "davis", mutate))

    def test_a_secondary_that_is_the_primary_is_refused_by_id(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"].append(
                {
                    "declaration": raw["metric"]["declaration"],
                    "implementation": raw["metric"]["implementation"],
                }
            )

        with pytest.raises(TaskCompositionError, match="PRIMARY"):
            compose_run_task_bindings(self._mutate(tmp_path, "davis", mutate))

    def test_a_mapping_where_a_list_belongs_names_the_shape(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"] = {"psnr": {}}

        with pytest.raises(TaskCompositionError, match="must be a LIST"):
            compose_run_task_bindings(self._mutate(tmp_path, "davis", mutate))

    def test_a_non_mapping_entry_is_refused(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"] = ["metric_psnr.json"]

        with pytest.raises(TaskCompositionError, match=r"secondary_metrics\[0\] must be a mapping"):
            compose_run_task_bindings(self._mutate(tmp_path, "davis", mutate))

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
            compose_run_task_bindings(self._mutate(tmp_path, "davis", mutate))

    def test_an_unimportable_secondary_implementation_fails_the_run_closed(self, tmp_path):
        def mutate(raw):
            raw["secondary_metrics"][0]["implementation"]["module"] = "no.such.module"

        with pytest.raises(TaskCompositionError, match="could not be imported"):
            compose_run_task_bindings(self._mutate(tmp_path, "davis", mutate))

    def test_the_primary_s_own_messages_are_unchanged(self, tmp_path):
        """The `where` parameter defaults to "metric", so adding it moved no
        primary byte."""

        def mutate(raw):
            del raw["metric"]["implementation"]

        with pytest.raises(
            TaskCompositionError, match=r"^metric requires an 'implementation' mapping"
        ):
            compose_run_task_bindings(self._mutate(tmp_path, "tidmad", mutate))

    def test_an_unknown_manifest_key_is_still_refused(self, tmp_path):
        def mutate(raw):
            raw["secondary_metric"] = []  # a plausible misspelling

        with pytest.raises(TaskCompositionError, match="unknown key"):
            compose_run_task_bindings(self._mutate(tmp_path, "tidmad", mutate))


# ---------------------------------------------------------------------------
# 3. The fingerprint — additive WHEN NON-EMPTY (delta D3)
# ---------------------------------------------------------------------------


class TestTheFingerprintRule:
    @pytest.mark.parametrize("task", ["tidmad", "fourth_task"])
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

    @pytest.mark.parametrize("task", ["pets", "davis"])
    def test_declaring_a_secondary_DOES_change_the_fingerprint(self, task):
        assert _compose(task).semantic_fingerprint != PRE_P2B_FINGERPRINTS[task]

    def test_an_explicitly_empty_list_equals_the_section_being_absent(self, tmp_path):
        manifest = _copy_pack("tidmad", tmp_path)
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
        manifest = _copy_pack("davis", tmp_path)
        first = compose_run_task_bindings(str(manifest))
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        raw["secondary_metrics"].reverse()
        manifest.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
        second = compose_run_task_bindings(str(manifest))
        assert first.semantic_fingerprint != second.semantic_fingerprint
        assert [m.spec.id for m in second.secondary_metrics] == ["mae", "psnr"]

    def test_the_same_declared_family_at_two_paths_yields_ONE_fingerprint(self, tmp_path):
        """Q-P1-2 held: a relocated task package is the same science."""
        a = compose_run_task_bindings(str(_copy_pack("davis", tmp_path / "a")))
        b = compose_run_task_bindings(str(_copy_pack("davis", tmp_path / "b")))
        assert a.semantic_fingerprint == b.semantic_fingerprint


# ---------------------------------------------------------------------------
# 4. Binding — run-scoped, and it unwinds
# ---------------------------------------------------------------------------


class TestTheRunScopedBinding:
    def test_unbound_resolves_to_the_empty_tuple(self):
        assert resolve_bound_run_secondary_metrics() == ()

    def test_the_composition_binding_activates_the_declared_family(self):
        composition = _compose("davis")
        assert resolve_bound_run_secondary_metrics() == ()
        with bind_run_task_composition(composition):
            bound = resolve_bound_run_secondary_metrics()
            assert [m.spec.id for m in bound] == ["psnr", "mae"]
            assert bound == composition.secondary_metrics
        assert resolve_bound_run_secondary_metrics() == ()

    def test_a_zero_secondary_composition_binds_the_empty_tuple(self):
        with bind_run_task_composition(_compose("tidmad")):
            assert resolve_bound_run_secondary_metrics() == ()

    def test_a_None_composition_is_still_a_no_op(self):
        with bind_run_task_composition(None) as composition:
            assert composition is None
            assert resolve_bound_run_secondary_metrics() == ()

    def test_nested_runs_do_not_leak_into_each_other(self):
        outer, inner = _compose("davis"), _compose("pets")
        with bind_run_task_composition(outer):
            with bind_run_task_composition(inner):
                assert [m.spec.id for m in resolve_bound_run_secondary_metrics()] == ["macro_f1"]
            assert [m.spec.id for m in resolve_bound_run_secondary_metrics()] == ["psnr", "mae"]
        assert resolve_bound_run_secondary_metrics() == ()

    def test_the_binding_unwinds_on_an_exception(self):
        composition = _compose("davis")
        with pytest.raises(RuntimeError, match="forced"), bind_run_task_composition(composition):
            raise RuntimeError("forced")
        assert resolve_bound_run_secondary_metrics() == ()

    def test_verify_refuses_a_composition_whose_secondaries_are_not_active(self):
        """A half-composed run that stamped a declared family it never
        evaluated would project the WHOLE family as a named absence — silent,
        and indistinguishable from a task that declared nothing."""
        composition = _compose("davis")
        with bind_run_task_composition(composition):
            verify_composition_is_bound(composition)  # the healthy case
            with bind_run_secondary_metrics(()):
                with pytest.raises(CompositionNotBoundError, match="secondary_metrics"):
                    verify_composition_is_bound(composition)


# ---------------------------------------------------------------------------
# 5. Ownership — one binder, in one module (the C1 half of the Q097 inversion)
# ---------------------------------------------------------------------------


class TestTheBinderHasExactlyOneOwner:
    """Step 09a's `test_no_production_module_evaluates_a_secondary_metric`
    asserted this shape did not exist anywhere. P2b C1 INVERTS the binder
    half: it must now exist, in its named owner, and nowhere else."""

    OWNER = "execute_tools/evaluation_metric.py"

    def test_the_binder_pair_lives_only_in_evaluation_metric(self):
        import re

        offenders: dict[str, list[str]] = {}
        for root in ("nodes", "agent", "core", "execute_tools", "workflows"):
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
