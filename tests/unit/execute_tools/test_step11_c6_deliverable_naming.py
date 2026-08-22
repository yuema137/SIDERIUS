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

    def test_tidmads_manifest_declares_no_naming(self):
        """Un-declared is a first-class state, not an omission to be filled."""
        assert compose_deliverable_naming_from_manifest(str(TIDMAD_MANIFEST)) is None
        assert compose_run_task_bindings(str(TIDMAD_MANIFEST)).deliverable_naming is None

    def test_an_undeclared_composition_leaves_the_shipped_naming_in_force(self):
        from workflows.task_composition import bind_run_task_composition

        composition = compose_run_task_bindings(str(TIDMAD_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            assert active_deliverable_naming() is None
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
            assert naming.name(model_type="m", run_name="r", exp_id="e", file_index=7) == (
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

    def test_the_watchdog_cleanup_site_is_unchanged(self):
        """Acceptance criterion: the cleanup consumers change no call site.

        Both read a HELD naming; C6 changed only where that value is
        CONSTRUCTED.
        """
        src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        assert "self.deliverable_naming.attempt_glob(" in src
        tuner = (REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/execution.py").read_text(
            encoding="utf-8"
        )
        assert "run_deliverable_spec.naming.experiment_glob(exp_id=exp_id)" in tuner

    def test_the_naming_type_is_constructed_only_where_it_may_be(self):
        """Census: exactly one naming authority.

        ``DeliverableNaming(...)`` may be constructed inside its own module —
        the type and the shipped default — and in the ONE declaration
        composer. Anywhere else is a second authority quietly deciding what
        a run's files are called.

        The permission is derived from the ENCLOSING FUNCTION, not from a
        list of file names: a by-name exemption is the shape this PR keeps
        removing, and it would let a future construction in the same file
        pass unnoticed.
        """
        allowed_function = "_compose_deliverable_naming"
        offenders: list[str] = []
        for root in ("core", "execute_tools", "agent", "nodes", "workflows", "dashboard"):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                if path.name == "deliverable_spec.py":
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for fn in ast.walk(tree):
                    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    for node in ast.walk(fn):
                        if (
                            isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                            and node.func.id == "DeliverableNaming"
                            and fn.name != allowed_function
                        ):
                            offenders.append(
                                f"{path.relative_to(REPO_ROOT)}:{node.lineno} in {fn.name}"
                            )
        assert offenders == [], (
            f"a second naming authority was constructed outside the contract "
            f"and outside {allowed_function}: {offenders}"
        )

    def test_that_census_is_not_vacuous(self):
        """It must actually SEE the one permitted construction, or it would
        be green on a repository that had none and be proving nothing.
        """
        src = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        assert "return DeliverableNaming(**section)" in src

    def test_default_deliverable_naming_delegates_rather_than_duplicating(self):
        """The shipped-default helper and the resolver must not drift."""
        assert default_deliverable_naming() == resolve_deliverable_naming()
        with bind_deliverable_naming(CONTRAST):
            assert default_deliverable_naming() == CONTRAST
