"""Step 11 C6 — deliverable naming flows FROM the Deliverable Contract.

Before C6 the naming half of every `DeliverableSpec` was
``DeliverableNaming()`` with all defaults, at every construction site. A
composed contrast task had no way to say what its deliverables are called,
so its cleanup globs matched filenames it had never written — and
``experiment_glob`` is what ``--cleanup_denoised`` deletes with.

**R-11-3 is the shape of the fix.** The Deliverable Contract stays the sole
naming OWNER: a manifest supplies a DECLARATION, and
:class:`DeliverableNaming` — with its own fail-closed validators — turns it
into a rule. Not one of those rules is restated in the composition layer,
and the composition does not become a second naming authority.

The transport reuses C5's manifest binding rather than adding a second one,
and resolution happens at the two places a naming is CONSTRUCTED — the
sandbox and ``derive_tidmad_deliverable_spec`` — so both cleanup consumers
pick up a composed template with **no change at their call sites**.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from execute_tools.deliverable_spec import (
    DeliverableNaming,
    active_deliverable_naming,
    bind_deliverable_naming,
    default_deliverable_naming,
    derive_tidmad_deliverable_spec,
    resolve_deliverable_naming,
)
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.task_composition import (
    TaskCompositionError,
    compose_deliverable_naming_from_manifest,
    compose_run_task_bindings,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TIDMAD_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml"

CONTRAST = DeliverableNaming(prefix="pets_pred", extension=".npz", index_width=3)


# ----------------------------------------------------------------------
# TIDMAD parity — the workhorse assertion
# ----------------------------------------------------------------------


class TestTidmadNamingIsByteIdentical:
    def test_the_shipped_globs_are_unchanged(self):
        naming = resolve_deliverable_naming()
        assert naming.prefix == "abra_validation_denoised"
        assert (
            naming.attempt_glob(model_type="fcnet", run_name="r", exp_id="e")
            == "abra_validation_denoised_fcnet_r_e_*.h5"
        )
        assert naming.experiment_glob(exp_id="e") == "abra_validation_denoised_*_e_*.h5"

    def test_tidmads_manifest_declares_its_naming_byte_identically(self):
        """Declared delta (arXiv #268, 2026-08-26): the anchor manifest now
        DECLARES the previously-implicit shipped values — omission stopped
        being a legal shape for a not-own-naming composed task (discussion
        (13)'s repaired defect). The VALUES are pinned byte-identical to the
        old shipped template, so nothing about TIDMAD's naming moved; only
        the declaration requirement did."""
        declared = compose_deliverable_naming_from_manifest(str(TIDMAD_MANIFEST))
        assert declared is not None
        assert (declared.prefix, declared.extension, declared.index_width) == (
            "abra_validation_denoised",
            ".h5",
            4,
        )
        assert compose_run_task_bindings(str(TIDMAD_MANIFEST)).deliverable_naming == declared

    def test_the_declared_composition_binds_the_same_shipped_values(self):
        """Declared delta (arXiv #268): the bound naming is now the DECLARED
        one — byte-identical to the template the old omission path resolved,
        proven by comparing against a directly-constructed default."""
        from execute_tools.deliverable_spec import DeliverableNaming
        from workflows.task_composition import bind_run_task_composition

        composition = compose_run_task_bindings(str(TIDMAD_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            assert active_deliverable_naming() == DeliverableNaming()
            assert resolve_deliverable_naming().prefix == "abra_validation_denoised"


# ----------------------------------------------------------------------
# A composed task's declaration
# ----------------------------------------------------------------------


def _manifest_with_naming(tmp_path: pathlib.Path, declaration) -> pathlib.Path:
    """A COMPLETE manifest carrying ``declaration`` as its `deliverable:`.

    Deliberately not a fragment: `_read_manifest` refuses a manifest missing
    a required section, so a fragment would make every negative case below
    pass for the wrong reason — proving the required-section check fires
    rather than the naming validator.
    """
    return write_complete_manifest(tmp_path, deliverable=declaration)


class TestADeclaredNamingIsHonoured:
    def test_the_binding_changes_every_derived_name(self):
        with bind_deliverable_naming(CONTRAST):
            naming = resolve_deliverable_naming()
            assert naming.attempt_glob(model_type="m", run_name="r", exp_id="e") == (
                "pets_pred_m_r_e_*.npz"
            )
            assert naming.name(model_type="m", run_name="r", exp_id="e", input_identity=7) == (
                "pets_pred_m_r_e_007.npz"
            )

    def test_the_derived_spec_follows_the_binding(self):
        """`derive_tidmad_deliverable_spec` is the shared derivation both
        sides call; if it did not follow, the child and parent would disagree.
        """
        from execute_tools.dataset_config import resolve_dataset_profile

        profile = resolve_dataset_profile()
        with bind_deliverable_naming(CONTRAST):
            assert derive_tidmad_deliverable_spec(profile).naming.prefix == "pets_pred"
        assert derive_tidmad_deliverable_spec(profile).naming.prefix == ("abra_validation_denoised")

    def test_a_manifest_declaration_composes(self, tmp_path):
        m = _manifest_with_naming(
            tmp_path, {"prefix": "pets_pred", "extension": ".npz", "index_width": 3}
        )
        naming = compose_deliverable_naming_from_manifest(str(m))
        assert naming is not None
        assert (naming.prefix, naming.extension, naming.index_width) == ("pets_pred", ".npz", 3)

    def test_a_COMPOSED_run_binds_its_declared_naming_end_to_end(self, tmp_path):
        """The hop from `RunTaskComposition` to the active binding.

        Added because a mutation SURVIVED without it: disabling the
        `bind_deliverable_naming` call inside `bind_run_task_composition`
        left every other test green, since the only composition under test
        was TIDMAD's — which declares no naming, so the branch was never
        taken. A declared-naming composition is the only fixture that can
        exercise it.
        """
        from workflows.task_composition import bind_run_task_composition

        manifest = write_complete_manifest(
            tmp_path, deliverable={"prefix": "pets_pred", "extension": ".npz", "index_width": 3}
        )
        composition = compose_run_task_bindings(str(manifest))
        assert composition.deliverable_naming is not None

        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            assert active_deliverable_naming() == composition.deliverable_naming
            assert (
                resolve_deliverable_naming().attempt_glob(model_type="m", run_name="r", exp_id="e")
                == "pets_pred_m_r_e_*.npz"
            )
        assert active_deliverable_naming() is None

    def test_a_declared_naming_changes_the_composition_fingerprint(self, tmp_path):
        """Naming is SEMANTIC: it decides deliverable file identity, so two
        runs that name their outputs differently are not the same run.
        """
        undeclared = compose_run_task_bindings(str(write_complete_manifest(tmp_path / "a")))
        (tmp_path / "b").mkdir(parents=True, exist_ok=True)
        declared = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path / "b", deliverable={"prefix": "pets_pred"}))
        )
        assert undeclared.semantic_fingerprint != declared.semantic_fingerprint

    def test_the_binding_resets(self):
        with bind_deliverable_naming(CONTRAST):
            pass
        assert active_deliverable_naming() is None

    def test_the_binding_resets_on_an_exception(self):
        with pytest.raises(RuntimeError), bind_deliverable_naming(CONTRAST):
            raise RuntimeError("boom")
        assert active_deliverable_naming() is None


# ----------------------------------------------------------------------
# Fail-safe — the Deliverable Contract owns every rule
# ----------------------------------------------------------------------


class TestAMalformedDeclarationRefuses:
    """C6 §6: an empty or malformed template must refuse, never produce a
    glob matching everything. Every rule below is the CONTRACT's, not a
    restatement — that is what R-11-3 requires.
    """

    @pytest.mark.parametrize(
        "declaration",
        [
            {"prefix": ""},  # empty stem -> a glob matching everything
            {"prefix": "  padded"},  # surrounding whitespace
            {"prefix": "has*star"},  # glob metacharacter in the stem
            {"extension": "noleadingdot"},
            {"extension": "."},
            {"index_width": 0},
            {"unknown_key": 1},  # extra="forbid" on the contract type
        ],
    )
    def test_it_refuses(self, tmp_path, declaration):
        with pytest.raises(TaskCompositionError):
            compose_deliverable_naming_from_manifest(
                str(_manifest_with_naming(tmp_path, declaration))
            )

    def test_a_non_mapping_section_refuses(self, tmp_path):
        with pytest.raises(TaskCompositionError):
            compose_deliverable_naming_from_manifest(
                str(_manifest_with_naming(tmp_path, "not-a-mapping"))
            )

    def test_the_refusal_comes_from_the_contract_not_a_copy(self):
        """The composition layer must not restate a single naming rule."""
        src = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_compose_deliverable_naming"
        )
        body = ast.dump(fn)
        for restatement in ("startswith", "glob metacharacter", "index_width", "'*'"):
            assert restatement not in body, (
                f"the composition layer restates a naming rule ({restatement!r}); "
                "DeliverableNaming is the sole owner (R-11-3)"
            )


# ----------------------------------------------------------------------
# Consumers pick it up with no call-site change
# ----------------------------------------------------------------------


class TestBothCleanupConsumersFollow:
    def test_the_sandbox_picks_up_a_bound_naming(self, tmp_path):
        from core.sandbox_executor import TidmadSandbox

        with bind_deliverable_naming(CONTRAST):
            sb = TidmadSandbox(run_name="r", workspace=str(tmp_path / "ws"))
            assert sb.deliverable_naming.prefix == "pets_pred"

    def test_both_cleanup_consumers_read_a_HELD_naming(self):
        """Acceptance criterion: the cleanup consumers read a HELD naming.

        C6's claim is that both globs come from a value the run already
        holds, rather than from a template re-derived at the call site.

        **Step 12 / PR-12d (F-12d-5) moved WHICH held value the tuner reads,
        and the claim is unchanged.** It used to reach through
        ``run_deliverable_spec.naming``; D2 made that spec ``| None`` for a
        task declaring no TIDMAD storage geometry, so this site — inside a
        ``finally:``, behind the standard launch command's
        ``--cleanup_denoised`` — would have raised ``AttributeError`` and
        masked any in-flight exception. It now reads
        ``RunBindings.run_deliverable_naming``, which is ALWAYS present.

        Asserted STRUCTURALLY rather than as a source string: the previous
        form pinned an expression, so a behaviour-preserving move to a
        better-typed authority turned it RED with nothing wrong. What matters
        is that each consumer calls its glob on a value it was HANDED, never
        on a freshly constructed template.
        """
        import ast as _ast

        src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        assert "self.deliverable_naming.attempt_glob(" in src, "the sandbox holds its naming"

        tuner_path = REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/execution.py"
        calls = [
            node
            for node in _ast.walk(_ast.parse(tuner_path.read_text(encoding="utf-8")))
            if isinstance(node, _ast.Call)
            and isinstance(node.func, _ast.Attribute)
            and node.func.attr == "experiment_glob"
        ]
        assert len(calls) == 1, "exactly one experiment-scoped cleanup site"
        receiver = _ast.unparse(calls[0].func.value)
        assert receiver == "run_deliverable_naming", (
            f"the cleanup glob must come from the run's MANDATORY naming authority; "
            f"got {receiver!r}"
        )
        assert [kw.arg for kw in calls[0].keywords] == ["exp_id"]

    def test_the_cleanup_naming_survives_a_task_with_no_tidmad_geometry(self):
        """F-12d-5's regression, at the value that broke.

        ``derive_run_deliverable_spec`` answers ``None`` for a Q-12-4-honest
        profile. The naming authority must NOT, or the cleanup path raises
        inside ``finally``.
        """
        from execute_tools.dataset_config import DatasetProfile
        from execute_tools.deliverable_spec import (
            derive_run_deliverable_spec,
            resolve_deliverable_naming,
        )

        contrast = DatasetProfile(
            partition_count=3,
            topology={"kind": "contrast_shaped"},
            anchor_selection_files=[0],
            health_peek_files=[0],
        )
        assert derive_run_deliverable_spec(contrast) is None
        naming = resolve_deliverable_naming()
        assert naming is not None
        assert naming.experiment_glob(exp_id="e1")

    def test_only_the_sanctioned_owners_decide_a_deliverable_file_name(self):
        """Census: exactly one naming authority — the CONCEPT, not one type.

        Step 12 / PR-12d D-FINAL rewrote this. It used to detect ``ast.Call``
        on the NAME ``DeliverableNaming`` and walk only ``FunctionDef``
        bodies, so its docstring claimed "exactly one naming authority" while
        what it enforced was "one construction of one type". Two consequences,
        both real rather than hypothetical:

        * the two production naming authorities inside its OWN swept
          directories — ``pets_data_path.deliverable_name`` and
          ``davis_data_path.deliverable_name`` — were invisible, because a
          task names its artifacts with an f-string, not by constructing the
          framework's indexed template;
        * a MODULE-LEVEL construction was invisible too, since only function
          bodies were walked.

        The invariant is *who may decide what a run's files are called*, and
        deciding takes two shapes. Both are now swept, over the whole module:

        1. constructing ``DeliverableNaming(...)`` — the framework's indexed
           template — allowed only in its own module and in the ONE
           declaration composer;
        2. composing a deliverable FILE NAME directly — allowed only in a
           task-owned ``*_data_path.py``, which is exactly where a task is
           entitled to name its own artifacts, and in the contract module.

        Permissions are derived from the enclosing function and from
        task-ownership, never from a list of exempted file names — a by-name
        exemption is the shape that cost F-12bc-9 a whole census once.
        """
        allowed_function = "_compose_deliverable_naming"
        markers = ("predictions_", "denoised_")
        extensions = (".h5", ".csv", ".npz", ".hdf5")
        offenders: list[str] = []

        for root in ("core", "execute_tools", "agent", "nodes", "workflows", "dashboard"):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                rel = path.relative_to(REPO_ROOT)
                if path.name == "deliverable_spec.py":
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))

                enclosing: dict[int, str] = {}
                for fn in ast.walk(tree):
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for d in ast.walk(fn):
                            enclosing.setdefault(id(d), fn.name)

                for node in ast.walk(tree):
                    # (1) the framework's indexed template
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "DeliverableNaming"
                        and enclosing.get(id(node)) != allowed_function
                    ):
                        where = enclosing.get(id(node), "<module level>")
                        offenders.append(f"{rel}:{node.lineno} constructs the template in {where}")

                    # (2) a deliverable file name composed directly
                    if path.name.endswith("_data_path.py"):
                        continue  # a task may name its OWN artifacts
                    if isinstance(node, (ast.JoinedStr, ast.Constant)):
                        text = ast.unparse(node) if isinstance(node, ast.JoinedStr) else node.value
                        if not isinstance(text, str):
                            continue
                        # A file NAME, not prose about one. Docstrings and error
                        # messages mention `denoised_...h5` constantly, and the
                        # first draft of this detector reported three of them as
                        # naming authorities — a census whose first run is all
                        # false positives teaches nobody to trust its next one.
                        if " " in text or "\n" in text:
                            continue
                        if any(m in text for m in markers) and any(e in text for e in extensions):
                            offenders.append(
                                f"{rel}:{node.lineno} composes a deliverable file name: {text[:60]!r}"
                            )

        assert offenders == [], (
            f"a second naming authority decided what a run's files are called, "
            f"outside the contract module, outside {allowed_function}, and "
            f"outside a task's own data path: {offenders}"
        )

    def test_that_census_is_not_vacuous(self):
        """It must actually SEE both permitted shapes, or it would be green on
        a repository that had neither and be proving nothing.

        Both are asserted because they are what the D-FINAL rewrite added: a
        census that saw only the first was green for years while the second
        went unswept.
        """
        composer = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        assert "return DeliverableNaming(**section)" in composer

        for pack in ("pets_data_path.py", "davis_data_path.py"):
            src = (REPO_ROOT / "execute_tools" / pack).read_text(encoding="utf-8")
            assert "def deliverable_name(" in src, (
                f"{pack} no longer owns a naming rule — the census's second "
                f"detector now sweeps for something that does not exist"
            )

    def test_default_deliverable_naming_delegates_rather_than_duplicating(self):
        """The shipped-default helper and the resolver must not drift."""
        assert default_deliverable_naming() == resolve_deliverable_naming()
        with bind_deliverable_naming(CONTRAST):
            assert default_deliverable_naming() == CONTRAST
