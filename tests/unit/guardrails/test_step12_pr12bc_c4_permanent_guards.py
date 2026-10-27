"""Child task loading preserves process isolation, path resolution and registration ownership."""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


CHILDREN = (
    "src/execute_tools/train_engine_sandbox.py",
    "src/execute_tools/inference_single.py",
    "src/execute_tools/denoising_score_single.py",
)


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


class TestRegistrationOwnership:
    def test_the_composer_did_not_become_the_overlay(self):
        """§J's actual sentence: *"the overlay is its own module, not a growth
        of the composer."* Asserted as ownership, not as a line count — C0
        declared `COMPOSITION_LOC_AT_C0 = 1475` and never asserted it, and a
        raw LOC ceiling would have blocked C3's two child-facing entry points,
        which belong in the composer beside their Step-11 sibling.

        What must NOT be there is the registration overlay. It has its own
        module, and this is what says so.
        """
        src = (REPO_ROOT / "src/workflows" / "task_composition.py").read_text(encoding="utf-8")
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
