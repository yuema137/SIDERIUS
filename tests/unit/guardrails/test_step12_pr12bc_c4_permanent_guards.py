"""Step 12 / PR-12bc — C4: Phase C's guarantees as permanent guards.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §K, §M / C4; ledger §Q.C4.

Three jobs, none of which any single checkpoint's module could do:

* the **R-11-10 sweep** — every guard Phase B or C inverted is now either a
  permanent owner of the corrected property or deleted, and never both;
* **cwd independence** — the child resolution path must not care where the
  parent left the working directory;
* the **§J** structural comparison across both phases.

**F-12bc-6, found here.** C0's flip-detector for C3
(`test_no_child_composes_a_data_path_from_a_manifest_today`) searched each
child for the string `_compose_task_data_path` — the PRIVATE composer. C3
reached composition through the public sibling `resolve_child_task_data_path`,
so the detector stayed GREEN through the very landing it was written to
announce, message and all ("C3 has landed; retire this guard"). A flip
detector that names an implementation detail rather than a PROPERTY detects
one implementation, and a green result from it means nothing. Corrected below
by asserting the property — *can a child resolve an id it never imported?* —
which no choice of symbol can dodge.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TEST_ROOT = REPO_ROOT / "tests"

CHILDREN = (
    "execute_tools/train_engine_sandbox.py",
    "execute_tools/inference_single.py",
    "execute_tools/denoising_score_single.py",
)


def _test_function_names() -> dict[str, list[str]]:
    """Every test function in the suite, by name → the files defining it."""
    out: dict[str, list[str]] = {}
    for path in TEST_ROOT.rglob("test_*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                out.setdefault(node.name, []).append(str(path.relative_to(REPO_ROOT)))
    return out


# ======================================================================
# The R-11-10 sweep
# ======================================================================

#: Every guard Phase B or C inverted, and the module that owns the corrected
#: property now. R-11-10: *a flipped guard becomes the permanent owner or is
#: deleted — never both.*
RETIRED_INVERTED_GUARDS: dict[str, str] = {
    # B6 — the pairing gap
    "test_main_passes_no_scope_parameter_today": (
        "tests/unit/core/test_step12_pr12bc_b6_scope_transport.py"
    ),
    "test_the_training_child_has_no_scope_argv_today": (
        "tests/unit/core/test_step12_pr12bc_b6_scope_transport.py"
    ),
    # B7 — the four scope-adjacent satellites
    "test_it_accepts_a_sample_set_illegal_under_a_smaller_profile": (
        "tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py"
    ),
    "test_the_signature_has_no_profile_parameter": (
        "tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py"
    ),
    "test_the_inline_tidmad_filename_literal_is_still_there": (
        "tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py"
    ),
    "test_the_peek_root_defaults_to_the_import_time_constant": (
        "tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py"
    ),
    "test_the_unconditional_anchor_demand_is_still_present": (
        "tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py"
    ),
    "test_the_measurement_path_still_constructs_a_tidmad_scope": (
        "tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py"
    ),
    # C3 — the manifest reaches every child
    "test_the_emitter_is_used_once_and_only_by_scoring": (
        "tests/unit/execute_tools/test_step12_pr12bc_c3_child_loading.py"
    ),
    "test_training_and_inference_do_not_get_it": (
        "tests/unit/execute_tools/test_step12_pr12bc_c3_child_loading.py"
    ),
    # C3 — F-12bc-6: the flip detector that never fired
    "test_no_child_composes_a_data_path_from_a_manifest_today": (
        "tests/unit/execute_tools/test_step12_pr12bc_c3_child_loading.py"
    ),
}

#: The properties those guards were pointing at, and their single owner now.
CORRECTED_PROPERTY_OWNERS: dict[str, str] = {
    "test_same_id_DIFFERENT_content_is_refused_naming_both": (
        "tests/unit/workflows/test_step12_pr12e_negative_controls.py"
    ),
}


class TestR1110Sweep:
    @pytest.mark.parametrize("name", sorted(RETIRED_INVERTED_GUARDS))
    def test_no_retired_inverted_guard_survives(self, name):
        """A retired guard that comes back is a duplicate that will one day
        disagree with its own replacement — and the inverted half is the one
        that passes for the wrong reason, because it asserts the defect.
        """
        defined_in = _test_function_names().get(name, [])
        assert not defined_in, (
            f"{name!r} was retired under R-11-10 but is defined again in "
            f"{defined_in}. Its corrected property is owned by "
            f"{RETIRED_INVERTED_GUARDS[name]}"
        )

    @pytest.mark.parametrize("name", sorted(CORRECTED_PROPERTY_OWNERS))
    def test_every_corrected_property_has_exactly_one_owner(self, name):
        """The other half of R-11-10, and the half a deletion sweep can
        silently break: retiring the inverted guard is only safe because the
        positive contract exists somewhere.
        """
        defined_in = _test_function_names().get(name, [])
        assert defined_in == [CORRECTED_PROPERTY_OWNERS[name]], (
            f"{name!r} is defined in {defined_in}, expected exactly "
            f"[{CORRECTED_PROPERTY_OWNERS[name]!r}]"
        )


# ======================================================================
# F-12bc-6 — the property, stated so no symbol choice can dodge it
# ======================================================================


class TestAChildCanResolveWhatItNeverImported:
    """The corrected form of C0's broken flip detector.

    Stated as behaviour, in a REAL fresh interpreter. A source-text guard
    asserts what one implementation happens to look like; this asserts what
    the system does, and there is no way to satisfy it without the capability
    actually being present.
    """

    def test_a_fresh_interpreter_resolves_an_out_of_tree_id(self, tmp_path):
        fixture = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"
        script = textwrap.dedent(
            f"""
            import shutil, sys
            sys.path.insert(0, {str(REPO_ROOT)!r})
            root = {str(tmp_path / "ft")!r}
            shutil.copytree({str(fixture)!r}, root)

            from execute_tools.task_data_path import registered_task_data_path_ids
            from workflows.task_composition import resolve_child_task_data_path

            assert "spectro_segmentation_v0" not in registered_task_data_path_ids()
            impl = resolve_child_task_data_path(
                "spectro_segmentation_v0",
                manifest_path=root + "/composition.yaml",
            )
            print("RESOLVED", impl.task_data_path_id)
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=180,
        )
        assert proc.returncode == 0, proc.stderr[-3000:]
        assert "RESOLVED spectro_segmentation_v0" in proc.stdout

    def test_the_children_reach_composition_through_the_PUBLIC_authority(self):
        """Why F-12bc-6 happened, pinned so the next detector is written
        against the right thing: no child names the private composer, and a
        detector that watches for it will never fire.
        """
        for child in CHILDREN:
            src = (REPO_ROOT / child).read_text(encoding="utf-8")
            code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
            assert "_compose_task_data_path" not in code
            assert "resolve_child_task_data_path" in code


# ======================================================================
# cwd independence
# ======================================================================


class TestCwdIndependence:
    """A child's working directory is whatever the parent left it at. Every
    path the resolution route touches must be anchored to something else.
    """

    @pytest.mark.parametrize("where", ["repo_root", "tmp", "manifest_parent"])
    def test_resolution_succeeds_from_any_working_directory(self, where, tmp_path, monkeypatch):
        import shutil

        from execute_tools import task_data_path as tdp
        from workflows.task_composition import resolve_child_task_data_path

        monkeypatch.setattr(tdp, "_REGISTRY", {})
        monkeypatch.setattr(tdp, "_CONTENT", {})

        root = tmp_path / "ft"
        shutil.copytree(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task", root)
        manifest = root / "composition.yaml"

        monkeypatch.chdir(
            {
                "repo_root": REPO_ROOT,
                "tmp": tmp_path,
                "manifest_parent": root.parent,
            }[where]
        )
        impl = resolve_child_task_data_path("spectro_segmentation_v0", manifest_path=str(manifest))
        assert impl.task_data_path_id == "spectro_segmentation_v0"

    def test_a_RELATIVE_manifest_path_is_resolved_against_the_cwd_ONCE(self, tmp_path, monkeypatch):
        """The one thing that IS cwd-relative, stated rather than left
        ambiguous: the manifest PATH itself, as the caller supplied it. Every
        ref INSIDE the manifest anchors to the manifest's directory, so a
        relative manifest path does not make the plugin refs relative too.
        """
        import shutil

        from execute_tools import task_data_path as tdp
        from workflows.task_composition import resolve_child_task_data_path

        monkeypatch.setattr(tdp, "_REGISTRY", {})
        monkeypatch.setattr(tdp, "_CONTENT", {})

        root = tmp_path / "ft"
        shutil.copytree(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task", root)
        monkeypatch.chdir(tmp_path)
        impl = resolve_child_task_data_path(
            "spectro_segmentation_v0", manifest_path="ft/composition.yaml"
        )
        assert impl.task_data_path_id == "spectro_segmentation_v0"


# ======================================================================
# §J — the structural comparison across both phases
# ======================================================================


class TestStructuralBudgets:
    def test_no_baselined_phase_c_function_gained_a_branch_family(self):
        """The §J rule that matters, restated where both phases can be seen
        at once. The per-checkpoint modules assert their own baselines; this
        is the terminal statement.
        """
        from tests.unit.workflows.test_step12_pr12bc_c0_baselines import (
            MAX_BRANCH_GROWTH,
            PHASE_C_STRUCTURAL_BASELINE,
            phase_c_current_structure,
        )

        current = phase_c_current_structure()
        grew = {
            key: (current[key][1], base[1])
            for key, base in PHASE_C_STRUCTURAL_BASELINE.items()
            if current[key][1] - base[1] > MAX_BRANCH_GROWTH
        }
        assert not grew, f"branch families grew past budget: {grew}"

    def test_the_composer_did_not_become_the_overlay(self):
        """§J's actual sentence: *"the overlay is its own module, not a growth
        of the composer."* Asserted as ownership, not as a line count — C0
        declared `COMPOSITION_LOC_AT_C0 = 1475` and never asserted it, and a
        raw LOC ceiling would have blocked C3's two child-facing entry points,
        which belong in the composer beside their Step-11 sibling.

        What must NOT be there is the registration overlay. It has its own
        module, and this is what says so.
        """
        src = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        for owned_elsewhere in (
            "def run_registration_scope",
            "def retire_registrations",
            "_SCOPE_BASELINE",
        ):
            assert owned_elsewhere not in src, (
                f"{owned_elsewhere!r} moved into the composer — the overlay is "
                f"its own module (execute_tools/task_registration_scope.py)"
            )
        assert "from execute_tools.task_registration_scope import" in src, (
            "the composer no longer USES the overlay — F-12bc-2's rollback is "
            "reachable only from there"
        )
