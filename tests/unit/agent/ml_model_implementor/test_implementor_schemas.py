"""
Workspace binding behavior in agent/schemas/implementor.py.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.implementor import (
    ImplementorInput,
)


class TestImplementorInput:
    def test_custom_plugin_and_test_dirs(self):
        inp = ImplementorInput(
            model_name="attn_unet",
            model_description="x",
            mathematical_definition="x",
            baseline_config={},
            plugin_dir="/custom/models",
            test_dir="/custom/tests",
        )
        assert inp.plugin_dir == "/custom/models"
        assert inp.test_dir == "/custom/tests"

    def test_default_generated_dirs_follow_local_workspace(self):
        inp = ImplementorInput(
            model_name="x",
            model_description="x",
            mathematical_definition="x",
            baseline_config={},
            storage={"backend": "local", "local": {"workspace": "/runs", "run_name": "r1"}},
        )
        assert inp.storage.local.workspace == "/runs"
        assert inp.plugin_dir == "/runs/generated/r1/models"
        assert inp.test_dir == "/runs/generated/r1/tests"
        assert inp.loss_dir == "/runs/generated/r1/losses"

    def test_default_generated_dirs_do_not_cross_workspaces(self, tmp_path):
        def make_input(workspace):
            return ImplementorInput(
                model_name="x",
                model_description="x",
                mathematical_definition="x",
                baseline_config={},
                storage={
                    "backend": "local",
                    "local": {"workspace": str(workspace), "run_name": "same_run"},
                },
            )

        left = make_input(tmp_path / "left")
        right = make_input(tmp_path / "right")

        assert left.plugin_dir != right.plugin_dir
        assert left.plugin_dir.startswith(str(tmp_path / "left"))
        assert right.plugin_dir.startswith(str(tmp_path / "right"))

    def test_non_local_storage_requires_explicit_generated_dirs(self):
        with pytest.raises(ValidationError, match="must be explicit"):
            ImplementorInput(
                model_name="x",
                model_description="x",
                mathematical_definition="x",
                baseline_config={},
                storage={
                    "backend": "postgres",
                    "postgres": {
                        "connection_string": "postgresql://example.invalid/db",
                    },
                },
            )
