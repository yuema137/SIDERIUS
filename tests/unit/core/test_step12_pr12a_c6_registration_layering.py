"""Step 12 / PR-12a — C6: ONE public plugin-registration authority.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C6 (D-12a-8), parent §8 / 09.5 Q2 = B.

`workflows.model_exploration._add_plugin_to_registries` was a private DUPLICATE
of `ml_models.plugin_loader.register_model_in_memory`: same `_load_plugin`,
same three registries, same `model_type | None` return. Its only behavioural
difference was the ABSENCE of the re-registration warning — strictly less
visible, which is why the public one is the survivor.

Two consequences, and the second is the reason this was a Step-12 item at all:

    layering   `core.resume` imported a PRIVATE symbol from `workflows`,
               which is the wrong direction across the layer boundary
    cycles     that import made `workflows -> core.resume` a cycle, so
               `model_exploration` carried TWO workarounds to break it: a
               TYPE_CHECKING-only `RestoredState` with a quoted annotation,
               and a function-local `union_key_findings` import buried inside
               `run_workflow`

Both workarounds are gone, and the census below is what stops either from
being reintroduced by a future convenience import.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE = REPO_ROOT / "src/core"
MODEL_EXPLORATION = REPO_ROOT / "src/workflows" / "model_exploration.py"


def _import_sources(path: Path) -> list[str]:
    """Every module a file imports FROM, at any nesting depth."""
    return [
        node.module
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module
    ]


def _private_workflows_imports(path: Path) -> list[str]:
    """Underscore-prefixed names imported from `workflows` by `path`."""
    return [
        f"{node.module}.{alias.name}"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
        if node.module.startswith("workflows") and alias.name.startswith("_")
    ]


class TestCoreDoesNotReachIntoAWorkflowsPRIVATE:
    """09.5 Q2 = B, as an executable rule rather than a note.

    **The rule is about PRIVATE symbols, and deliberately not about the layer
    edge as a whole.** `core.sandbox_executor` imports
    `workflows.task_composition.active_task_manifest_path` and
    `workflows.task_config.run_bound_model_io_contract` — PUBLIC run-scoped
    accessors, function-local, added by Step 11 so the spawn surface can ask
    what the run is bound to. That is a deliberate design edge, not this
    commit's to relitigate, and a census that banned it would be asserting a
    rule the repository does not hold. Recorded in the PR-12a ledger rather
    than exempted by name.

    What is genuinely a defect is `core` reaching for a workflows PRIVATE:
    it inverts the layering AND it is what made `workflows -> core.resume` a
    cycle, forcing two workarounds inside `model_exploration`.
    """

    @pytest.mark.parametrize(
        "module", sorted(p.name for p in CORE.glob("*.py") if p.name != "__init__.py")
    )
    def test_no_core_module_imports_a_private_workflows_symbol(self, module):
        offenders = _private_workflows_imports(CORE / module)
        assert offenders == [], (
            f"core/{module} imports {offenders} — a PRIVATE symbol from the "
            f"layer above. That is what forced the import cycle C6 dissolved."
        )

    def test_the_census_can_see_a_planted_violation(self, tmp_path):
        """Anti-vacuity: the scanner must actually detect the shape it bans,
        not merely find nothing because it looks in the wrong place."""
        planted = tmp_path / "planted.py"
        planted.write_text(
            "from workflows.model_exploration import _add_plugin_to_registries\n", encoding="utf-8"
        )
        assert _private_workflows_imports(planted) == [
            "workflows.model_exploration._add_plugin_to_registries"
        ]

    def test_the_public_edge_is_recorded_not_banned(self):
        """Pins the observation the rule above deliberately allows, so a
        future reader sees it was measured rather than missed.

        Deduped: the property is WHICH modules `core` reaches across the
        layer edge, not how many function-local import statements name them.
        D2 added a second read from `workflows.task_config` (the run's
        declared output geometry, for `_validate_configs`) in its own method
        beside the existing one in `_write_model_io_config`; that is the same
        recorded edge, not a new one. A genuinely new module still reds here.
        """
        public = [
            module
            for module in _import_sources(CORE / "sandbox_executor.py")
            if module.startswith("workflows")
        ]
        assert sorted(set(public)) == ["workflows.task_composition", "workflows.task_config"]
        assert _private_workflows_imports(CORE / "sandbox_executor.py") == []

    def test_resume_uses_the_public_registration_authority(self):
        source = (CORE / "resume.py").read_text(encoding="utf-8")
        assert "from ml_models.plugin_loader import register_model_in_memory" in source
        assert "_add_plugin_to_registries" not in source


class TestThePrivateDuplicateIsGone:
    def test_it_no_longer_exists_anywhere_in_production(self):
        offenders = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in REPO_ROOT.rglob("*.py")
            if path.is_file()
            and not any(
                part in {".venv", "__pycache__", "tests", "agent_generated", "legacy_repo"}
                for part in path.parts
            )
            and "def _add_plugin_to_registries" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_the_workflow_caller_uses_the_public_authority(self):
        source = MODEL_EXPLORATION.read_text(encoding="utf-8")
        assert "registered = register_model_in_memory(primary_plugin)" in source


class TestTheCycleWorkaroundsAreDissolved:
    """The layering fix is only real if the things the cycle FORCED are gone.

    Asserted on the AST, because a stale comment claiming the cycle exists
    would read as justification for reintroducing either workaround.
    """

    def test_restored_state_is_an_ordinary_top_level_import(self):
        tree = ast.parse(MODEL_EXPLORATION.read_text(encoding="utf-8"))
        top_level = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "RestoredState" in top_level
        assert "union_key_findings" in top_level

        type_checking_blocks = [
            node
            for node in tree.body
            if isinstance(node, ast.If)
            and "TYPE_CHECKING" in ast.dump(node.test)
            and "RestoredState" in ast.dump(node)
        ]
        assert type_checking_blocks == []

    def test_no_function_local_import_of_the_resume_symbols_remains(self):
        """The workaround that mattered most: `union_key_findings` was
        imported INSIDE `run_workflow`, which hid a cross-layer dependency in
        the middle of an already-large function."""
        tree = ast.parse(MODEL_EXPLORATION.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.ImportFrom)
                    and sub.module == "core.resume"
                    and sub is not node
                ):
                    offenders.append(f"{node.name}: from {sub.module} import ...")
        assert offenders == []

    def test_the_annotation_is_no_longer_quoted(self):
        tree = ast.parse(MODEL_EXPLORATION.read_text(encoding="utf-8"))
        run_workflow = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run_workflow"
        )
        restored = next(
            arg
            for arg in run_workflow.args.args + run_workflow.args.kwonlyargs
            if arg.arg == "restored_state"
        )
        assert restored.annotation is not None
        assert not isinstance(restored.annotation, ast.Constant), (
            "the annotation is still a string — it was quoted only because of "
            "the cycle C6 dissolved"
        )


class TestResumeKeepsWarnAndContinue:
    """C6's §6 edge case, stated as behaviour rather than as an intention.

    `restore_prior_state` must WARN and CONTINUE on a plugin that fails to
    load — the consolidation must not convert it to a raise, or one corrupt
    prior-iteration plugin would take down a resume that can still produce
    memory_history.
    """

    def test_the_failure_branch_still_warns_rather_than_raising(self):
        source = (CORE / "resume.py").read_text(encoding="utf-8")
        marker = "registered = register_model_in_memory(plugin_file)"
        assert marker in source
        after = source[source.index(marker) : source.index(marker) + 900]
        assert "if registered is None:" in after
        assert "warnings.warn(" in after
        assert "raise" not in after.split("warnings.warn(")[0]

    def test_the_public_authority_returns_None_rather_than_raising(self, tmp_path):
        """The behavioural half: warn-and-continue is only preserved if the
        new callee still SIGNALS failure the same way the private one did."""
        from ml_models.plugin_loader import register_model_in_memory

        broken = tmp_path / "broken_plugin.py"
        broken.write_text("# missing every required attribute\n", encoding="utf-8")
        assert register_model_in_memory(str(broken)) is None
