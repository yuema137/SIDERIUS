"""D14-1 C5 — the no-dual-path AST census and the task-identity guardrail.

Child §5 C5: after the relocation (C2b-C4) there is ONE way to reach TIDMAD's
executable data path — through the registry-resolved ``TaskDataPath``. The
compat re-export is import-compat only, so this census counts *constructions
and codec CALLS*, never imports (child §8). Counts are pinned EXACTLY: a new
direct construction or codec call anywhere in production — including a second
one inside a sanctioned file — is a dual path and fails here.

The task-identity guardrail (parent §3.1 capability-key row: "the framework
never inspects the id's spelling") extends the token discipline to the
data-path surface for the D14 task family (``tidmad|pet|davis``): no
production comparison against those literals on the surface files. The
surface list GROWS at D14-2/3 when the pets/davis packs land.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Production roots the construction/codec census walks (tests excluded by
#: construction — the census is about PRODUCTION dual paths).
_PRODUCTION_ROOTS = (
    "execute_tools",
    "core",
    "nodes",
    "agent",
    "workflows",
    "ml_models",
    "scripts",
    "dashboard",
    "tools",
    "sdsc_submission_scripts",
)

#: file (repo-relative) -> exact allowed number of CALLS.
_ALLOWED_DATASET_CONSTRUCTIONS = {
    "execute_tools/tidmad_data_path.py": 2,  # training_dataset + validation_dataset
}
_ALLOWED_CREATE_ABRA_CALLS = {
    "execute_tools/tidmad_data_path.py": 1,  # write_deliverable delegation
    # The fix-mode (baseline) single-file writer: baseline deliverables carry
    # no run/exp identity, which the seam request requires (C4 ledger).
    "execute_tools/inference_single.py": 1,
}

#: The data-path surface for the task-identity token guardrail.
#: GROWS with each task pack (D14-2 added the Pets implementation).
_DATA_PATH_SURFACE = (
    "execute_tools/task_data_path.py",
    "execute_tools/tidmad_data_path.py",
    "execute_tools/pets_data_path.py",
    "execute_tools/davis_data_path.py",
    "execute_tools/train_engine_sandbox.py",
    "execute_tools/inference_single.py",
    "execute_tools/denoising_score_single.py",
    # Step 11 C9 (F-11-8) — the SPAWN PARENT. It was absent while every one
    # of its children was listed, so the module that decides what the
    # children read was the one place this guardrail could not see. Bringing
    # it in is the point of the finding, not a formality: it carries
    # `TidmadSandbox`, `_tidmad_data_dir` and a `"tidmad_db"` literal, none
    # of which the census had ever examined.
    "core/sandbox_executor.py",
)

_TASK_NAME_TOKENS = {"tidmad", "pet", "pets", "davis"}


def _production_files() -> list[Path]:
    files: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        base = _REPO_ROOT / root
        if base.exists():
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _count_calls(tree: ast.AST, name: str) -> int:
    return sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.Call) and _call_name(node) == name
    )


class TestNoDualPath:
    def test_tidmad_epoch_dataset_constructed_only_inside_the_owner(self):
        violations: list[str] = []
        for path in _production_files():
            rel = path.relative_to(_REPO_ROOT).as_posix()
            count = _count_calls(ast.parse(path.read_text(encoding="utf-8")), "TIDMADEpochDataset")
            allowed = _ALLOWED_DATASET_CONSTRUCTIONS.get(rel, 0)
            if count != allowed:
                violations.append(f"{rel}: {count} construction(s), {allowed} allowed")
        assert not violations, (
            "TIDMADEpochDataset must be constructed ONLY by the TIDMAD "
            f"TaskDataPath implementation (dual-path census): {violations}"
        )

    def test_create_abra_file_called_only_at_sanctioned_sites(self):
        violations: list[str] = []
        for path in _production_files():
            rel = path.relative_to(_REPO_ROOT).as_posix()
            count = _count_calls(ast.parse(path.read_text(encoding="utf-8")), "create_abra_file")
            allowed = _ALLOWED_CREATE_ABRA_CALLS.get(rel, 0)
            if count != allowed:
                violations.append(f"{rel}: {count} call(s), {allowed} allowed")
        assert not violations, (
            "create_abra_file (the deliverable byte codec) may be CALLED only "
            f"at the sanctioned sites (dual-path census): {violations}"
        )

    def test_the_production_path_goes_through_the_resolved_binding(self):
        """Delete-the-hop detector (static half; the synthetic e2e is the
        dynamic half): each relocated caller must reach the data path through
        resolution, and the seam methods must actually be invoked."""
        engine = ast.parse(
            (_REPO_ROOT / "execute_tools/train_engine_sandbox.py").read_text(encoding="utf-8")
        )
        assert _count_calls(engine, "resolve_bound_task_data_path") >= 1, (
            "the engine no longer resolves the run-bound TaskDataPath — the "
            "registry hop was deleted"
        )
        assert _count_calls(engine, "training_dataset") >= 1
        assert _count_calls(engine, "validation_dataset") >= 1

        inference = ast.parse(
            (_REPO_ROOT / "execute_tools/inference_single.py").read_text(encoding="utf-8")
        )
        assert (
            _count_calls(inference, "resolve_child_task_data_path")
            + _count_calls(inference, "bootstrap_legacy_tidmad_data_path")
            >= 1
        )
        assert _count_calls(inference, "write_deliverable") >= 1

        scoring = ast.parse(
            (_REPO_ROOT / "execute_tools/denoising_score_single.py").read_text(encoding="utf-8")
        )
        assert _count_calls(scoring, "read_evaluation_payload") >= 1

    def test_the_transport_flag_is_never_an_operator_flag(self):
        """Child §4.1 (correction 1, FROZEN): ``--task_data_path_id`` is
        emitted by the parent process FROM the resolved run binding only —
        one configuration authority. No launcher shell may know it, accept
        it, or forward it, so an operator can never supply a binding that
        bypasses resolution."""
        offenders: list[str] = []
        for root in ("sdsc_submission_scripts", "scripts"):
            base = _REPO_ROOT / root
            if not base.exists():
                continue
            for sh in base.rglob("*.sh"):
                if "task_data_path_id" in sh.read_text(encoding="utf-8"):
                    offenders.append(sh.relative_to(_REPO_ROOT).as_posix())
        assert not offenders, f"launcher surfaces must not carry the transport flag: {offenders}"


class TestTaskIdentityGuardrail:
    def test_no_task_name_literal_comparison_on_the_data_path_surface(self):
        """The framework resolves ids by LOOKUP; nothing on the surface may
        branch on the spelling of a task name (``tidmad|pet|davis``). The
        declared ``TIDMAD_COMPATIBILITY_ID`` constant is a declaration, not a
        comparison, and does not match here."""
        violations: list[str] = []
        for rel in _DATA_PATH_SURFACE:
            tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                comparands: list[ast.expr] = []
                if isinstance(node, ast.Compare):
                    comparands = [node.left, *node.comparators]
                elif isinstance(node, ast.MatchValue):
                    comparands = [node.value]
                for expr in comparands:
                    if (
                        isinstance(expr, ast.Constant)
                        and isinstance(expr.value, str)
                        and expr.value.lower() in _TASK_NAME_TOKENS
                    ):
                        violations.append(f"{rel}:{node.lineno}: compares against {expr.value!r}")
        assert not violations, (
            f"task-name spelling must never be branched on (parent §3.1): {violations}"
        )

    def test_task_implementation_imports_on_the_surface_are_the_declared_set(self):
        """A task identity can enter a generic module as an IMPORT, and the
        comparison census above cannot see one.

        `ast.Compare`/`ast.MatchValue` walking is blind to `ast.Import`, so
        the three subprocess entrypoints could name every built-in task
        implementation and still pass the test above — while every file
        involved is listed in `_DATA_PATH_SURFACE`, which makes a reader
        believe the area is covered. That is the F-P2b-4 shape: a census
        green for the wrong reason.

        Import-time real-task bootstrap is forbidden. The remaining TIDMAD
        imports are explicit legacy codec/dataset dependencies and the one
        bounded compatibility adapter; Pets and DAVIS reach children only
        through transported manifests. The exact residue is pinned so adding
        a task import or removing the final legacy dependency is deliberate.
        """
        expected = {
            "execute_tools/train_engine_sandbox.py",
            "execute_tools/inference_single.py",
            "execute_tools/task_data_path.py",
        }
        found: dict[str, set[str]] = {}
        for rel in _DATA_PATH_SURFACE:
            tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
            names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(a.name for a in node.names if a.name.endswith("_data_path"))
                elif isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                    "_data_path"
                ):
                    names.add(node.module or "")
            # The seam module itself is not a task implementation.
            names = {n for n in names if not n.endswith("execute_tools.task_data_path")}
            if names:
                found[rel] = names

        assert set(found) == expected, (
            "task-implementation imports appeared on a data-path surface that "
            f"has no bootstrap role, or a bootstrap disappeared: {sorted(found)}"
        )
        for rel, names in found.items():
            assert names == {"execute_tools.tidmad_data_path"}, (
                f"{rel} imports an unexpected real task: {sorted(names)}"
            )
