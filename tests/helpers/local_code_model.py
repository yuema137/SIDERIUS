"""One tiny helper-defined model for declared-source consumer tests."""

from __future__ import annotations

from pathlib import Path

from core.local_code import CodePackageDeclaration, bind_code_package, capture_package
from ml_models.plugin_binding import resolve_declared_model_plugins

MODEL_TYPE = "resume_test_arch_a"


def make_package(root: Path):
    root.mkdir(parents=True)
    (root / "_helper.py").write_text(
        "import torch\nfrom torch import nn\nfrom pydantic import BaseModel\n"
        "class TestPluginConfig(BaseModel):\n"
        f" model_type: str = {MODEL_TYPE!r}\n segmentation_size: int = 64\n"
        "class TestPluginModel(nn.Module):\n"
        " def __init__(self, config):\n"
        "  super().__init__()\n  self.weight = nn.Parameter(torch.ones(1))\n"
        " def forward(self, x): return x.float() * self.weight\n"
    )
    (root / "model.py").write_text(
        "from ._helper import TestPluginConfig, TestPluginModel\n"
        f"PLUGIN_MODEL_TYPE = {MODEL_TYPE!r}\nPLUGIN_OUTPUT_TYPE = 'regressor'\n"
        "PLUGIN_CONFIG_CLASS = TestPluginConfig\nPLUGIN_MODEL_CLASS = TestPluginModel\n"
    )
    package = capture_package(
        CodePackageDeclaration(root=".", files=("model.py", "_helper.py")), root
    )
    with bind_code_package(package):
        binding = resolve_declared_model_plugins(
            configured_ref=".", root=str(root), required_model_types=(MODEL_TYPE,)
        )
    return package, binding
