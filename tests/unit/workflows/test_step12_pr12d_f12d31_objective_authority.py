"""A task-declared objective is authoritative, generic, and identity-bearing.

The scientific incident that motivated this contract is owned by
``siderius-exp``. This module protects only framework behavior through the two
framework-owned example packs and temporary objective plugins.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import os
import pathlib
import shutil
import subprocess
import sys
import textwrap
from typing import ClassVar

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs/task_composition/quickstart.yaml"
MASKED_REGRESSION = REPO_ROOT / "configs/task_composition/synthetic_masked_regression.yaml"
MASKED_OBJECTIVE = REPO_ROOT / "examples/synthetic_masked_regression/plugins/masked_mse_loss.py"
MASKED_LOSS_NAME = "synthetic_masked_mse"


def _compose(manifest: pathlib.Path):
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(str(manifest))


class TestDeclaredObjectiveIsAuthoritative:
    def test_plugin_objective_selects_the_implementation_declared_name(self):
        objective = _compose(MASKED_REGRESSION).objective
        assert objective is not None
        assert objective.loss_type == "custom"
        assert objective.loss_name == MASKED_LOSS_NAME

    def test_the_manifest_does_not_restate_the_plugin_name(self):
        text = MASKED_REGRESSION.read_text(encoding="utf-8")
        objective_block = text.split("objective:", 1)[1]
        assert "masked_mse_loss.py" in objective_block
        assert "PLUGIN_LOSS_TYPE" in objective_block
        assert "loss_name" not in objective_block

    def test_the_tuner_input_projection_carries_the_objective(self):
        from workflows.task_composition import build_task_composition_ref

        ref = build_task_composition_ref(_compose(MASKED_REGRESSION))
        assert ref is not None and ref.objective is not None
        assert ref.objective.loss_name == MASKED_LOSS_NAME

    def test_an_agent_selected_loss_is_replaced_by_the_declaration(self):
        from workflows.task_composition import build_task_composition_ref

        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")

        class _Plan:
            loss_cfg: ClassVar[dict] = {"loss_type": "smooth_l1", "beta": 1.0}

        plan = planning._apply_declared_objective(
            _Plan(), build_task_composition_ref(_compose(MASKED_REGRESSION))
        )
        assert plan.loss_cfg["loss_type"] == "custom"
        assert plan.loss_cfg["loss_name"] == MASKED_LOSS_NAME

    def test_objective_application_follows_the_mode_override_chain(self):
        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")
        source = inspect.getsource(planning.prepare_attempt)
        assert source.find("_apply_mode_override_chain(") < source.find(
            "_apply_declared_objective("
        )


class TestObjectiveSemanticIdentity:
    def test_plugin_content_moves_its_identity(self, tmp_path):
        from workflows.task_composition import _compose_objective

        copy = tmp_path / "objective.py"
        shutil.copy2(MASKED_OBJECTIVE, copy)
        section = {
            "objective": {"implementation": {"file": str(copy), "symbol": "PLUGIN_LOSS_TYPE"}}
        }
        before_config, before_ref = _compose_objective(section, str(tmp_path))
        copy.write_text(
            copy.read_text(encoding="utf-8") + "\n# semantic fixture edit\n",
            encoding="utf-8",
        )
        after_config, after_ref = _compose_objective(section, str(tmp_path))

        assert before_config == after_config
        assert before_ref is not None and after_ref is not None
        assert before_ref.content_sha256 != after_ref.content_sha256

    def test_byte_identical_relocation_preserves_content_identity(self, tmp_path):
        from workflows.task_composition import _compose_objective

        first = tmp_path / "first" / "objective.py"
        second = tmp_path / "second" / "objective.py"
        first.parent.mkdir()
        second.parent.mkdir()
        shutil.copy2(MASKED_OBJECTIVE, first)
        shutil.copy2(MASKED_OBJECTIVE, second)

        def identity(path: pathlib.Path) -> str:
            _, ref = _compose_objective(
                {
                    "objective": {
                        "implementation": {
                            "file": str(path),
                            "symbol": "PLUGIN_LOSS_TYPE",
                        }
                    }
                },
                str(path.parent),
            )
            assert ref is not None
            return ref.content_sha256

        assert identity(first) == identity(second)

    def test_executed_file_and_declared_identity_are_the_same_bytes(self):
        from workflows.task_composition import _compose_objective

        _, ref = _compose_objective(
            {
                "objective": {
                    "implementation": {
                        "file": str(MASKED_OBJECTIVE),
                        "symbol": "PLUGIN_LOSS_TYPE",
                    }
                }
            },
            str(REPO_ROOT),
        )
        assert ref is not None
        assert ref.content_sha256 == hashlib.sha256(MASKED_OBJECTIVE.read_bytes()).hexdigest()


class TestFrameworkProvidedObjectiveDeclaration:
    def test_builtin_config_resolves_to_the_existing_loss_contract(self):
        from workflows.task_composition import _compose_objective

        objective, plugin = _compose_objective(
            {"objective": {"config": {"loss_type": "ce", "reduction": "sum"}}},
            str(REPO_ROOT),
        )
        assert plugin is None
        assert objective.loss_type == "ce"
        assert objective.reduction == "sum"

    @pytest.mark.parametrize(
        ("section", "message"),
        [
            ({"config": {"loss_type": "ce"}, "implementation": {}}, "exactly one"),
            ({"config": {"loss_type": "custom", "loss_name": "x"}}, "cannot select"),
            ({"config": {"loss_type": "ce", "typo": 1}}, "unknown LossConfig keys"),
            ({"config": {"loss_type": "ce"}, "typo": {}}, "unknown key"),
        ],
    )
    def test_ambiguous_custom_or_misspelled_config_refuses(self, section, message):
        from workflows.task_composition import TaskCompositionError, _compose_objective

        with pytest.raises(TaskCompositionError, match=message):
            _compose_objective({"objective": section}, str(REPO_ROOT))

    def test_quickstart_demonstrates_the_builtin_objective_seam(self):
        objective = _compose(QUICKSTART).objective
        assert objective is not None
        assert objective.loss_type == "ce"
        assert objective.reduction == "mean"

    def test_builtin_objective_parameters_join_composition_identity(self, tmp_path):
        original = QUICKSTART.read_text(encoding="utf-8")
        variant = tmp_path / "quickstart_sum.yaml"
        variant.write_text(
            original.replace("../../examples/", f"{REPO_ROOT}/examples/").replace(
                "reduction: mean", "reduction: sum"
            ),
            encoding="utf-8",
        )
        child = (
            "from workflows.task_composition import compose_run_task_bindings as compose; "
            "import sys; print(compose(sys.argv[1]).semantic_fingerprint)"
        )

        def fingerprint(manifest: pathlib.Path) -> str:
            completed = subprocess.run(
                [sys.executable, "-c", child, str(manifest)],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            return completed.stdout.splitlines()[-1]

        assert fingerprint(variant) != fingerprint(QUICKSTART)


class TestGenericBoundaries:
    def test_absent_declaration_leaves_the_agent_choice_untouched(self):
        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")

        class _Plan:
            loss_cfg: ClassVar[dict] = {"loss_type": "focal", "alpha": 0.5}

        original = dict(_Plan.loss_cfg)
        assert planning._apply_declared_objective(_Plan(), None).loss_cfg == original
        assert (
            planning._apply_declared_objective(
                _Plan(), type("R", (), {"objective": None})()
            ).loss_cfg
            == original
        )

    def test_no_task_name_dispatch_exists_in_generic_authorities(self):
        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")
        from workflows import task_composition

        for function in (planning._apply_declared_objective, task_composition._compose_objective):
            tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
            executable_names = {
                node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)
            } | {node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            assert not {"task_id", "task_name", "package_name"} & executable_names
            assert not any(isinstance(node, ast.Match) for node in ast.walk(tree))

    def test_pre_contract_behavior_fails_the_authority_assertion(self):
        class _Plan:
            loss_cfg: ClassVar[dict] = {"loss_type": "smooth_l1", "beta": 1.0}

        stale = _Plan()
        with pytest.raises(AssertionError):
            assert stale.loss_cfg["loss_type"] == "custom"

    def test_same_name_shadow_is_refused_and_absence_is_allowed(self, tmp_path):
        from workflows.task_composition import TaskCompositionError, _compose_objective

        section = {
            "objective": {
                "implementation": {
                    "file": str(MASKED_OBJECTIVE),
                    "symbol": "PLUGIN_LOSS_TYPE",
                }
            }
        }
        clean_config, clean_ref = _compose_objective(section, str(REPO_ROOT))
        assert clean_config.loss_name == MASKED_LOSS_NAME and clean_ref is not None

        shadow = tmp_path / "shadow"
        shadow.mkdir()
        (shadow / "impostor.py").write_text(
            f"PLUGIN_LOSS_TYPE = {MASKED_LOSS_NAME!r}\n", encoding="utf-8"
        )
        previous = os.environ.get("SIDERIUS_LOSS_DIRS")
        os.environ["SIDERIUS_LOSS_DIRS"] = str(shadow)
        try:
            with pytest.raises(TaskCompositionError, match="same name"):
                _compose_objective(section, str(REPO_ROOT))
        finally:
            if previous is None:
                os.environ.pop("SIDERIUS_LOSS_DIRS", None)
            else:
                os.environ["SIDERIUS_LOSS_DIRS"] = previous


def test_fresh_process_composes_the_framework_objective_pack():
    code = (
        "from workflows.task_composition import compose_run_task_bindings as compose; "
        "import sys; print(compose(sys.argv[1]).objective.loss_name)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(MASKED_REGRESSION)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert completed.stdout.splitlines()[-1] == MASKED_LOSS_NAME
