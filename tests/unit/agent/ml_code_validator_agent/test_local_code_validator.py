"""Public validator consumers must execute and review one captured source view."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    bind_code_package,
    capture_package,
)
from nodes import ml_code_validator_agent as validator
from tests.helpers.local_code_model import MODEL_TYPE, make_package
from tests.unit.agent.ml_code_validator_agent.test_validator_agent import (
    FAKE_LLM_REVIEW,
    make_input,
)
from tests.unit.core.test_resume import isolated_registries

pytestmark = pytest.mark.usefixtures("isolated_registries")


@pytest.mark.parametrize("deleted", [False, True])
def test_actual_validator_executes_and_reviews_captured_entry_after_disk_changes(
    tmp_path, monkeypatch, deleted
):
    package, _ = make_package(tmp_path / "task")
    entry = package.root / "model.py"
    original = entry.read_text() + "# spectral_conv uses rfft\n"
    entry.write_text(original)
    package = capture_package(
        CodePackageDeclaration(root=".", files=("model.py", "_helper.py")), package.root
    )
    inp = make_input(
        tmp_path,
        model_type=MODEL_TYPE,
        model_file_path=str(entry),
        test_file_path="",
        inherited_components=[
            dict(
                component="spectral_conv",
                source_type="experiment",
                source_id="prior_model",
                contribution_evidence="Preserved entry claim",
            )
        ],
    )
    if deleted:
        entry.unlink()
    else:
        entry.write_text(
            "def forward(self, x):\n for t in range(x.shape[-1]):\n  x[t] = 0\n return x\n"
        )
    bridge = MagicMock()
    bridge.generate.return_value = FAKE_LLM_REVIEW
    agent = validator.MLCodeValidatorAgent(bridge_factory=lambda **kw: bridge)
    inherited_sources = []
    original_check = validator._check_inherited_components

    def check_inheritance(source, claims, vocab):
        inherited_sources.append(source)
        return original_check(source, claims, vocab)

    monkeypatch.setattr(validator, "_check_inherited_components", check_inheritance)
    with bind_code_package(package):
        assert validator._check_plugin(str(entry)) == (True, None)
        assert validator._check_instantiation_and_gradient(str(entry)) == (
            True,
            True,
            True,
            None,
            1,
            1,
        )
        result = agent.run(inp)
    assert result.passed
    assert result.forbidden_patterns_check_passed
    assert inherited_sources == [original]
    assert original in bridge.generate.call_args.args[1]
    bridge.generate.assert_called_once()


@pytest.mark.parametrize(
    "consumer", [validator._check_plugin, validator._check_instantiation_and_gradient]
)
def test_missing_package_metadata_rolls_back_helper_modules(tmp_path, consumer):
    marker = tmp_path / "helper-imported"
    (tmp_path / "_helper.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nVALUE = 1\n"
    )
    entry = tmp_path / "model.py"
    entry.write_text("from ._helper import VALUE\n")
    package = capture_package(
        CodePackageDeclaration(root=".", files=("model.py", "_helper.py")), tmp_path
    )
    before = set(sys.modules)
    with bind_code_package(package):
        result = consumer(str(entry))
    assert result[0] is False
    assert marker.exists()
    assert not [name for name in set(sys.modules) - before if name.startswith("_siderius_task_")]


@pytest.mark.parametrize("phase", ["construction", "forward", "backward"])
def test_validator_never_downgrades_late_package_refusal(tmp_path, phase):
    package, _ = make_package(tmp_path / "task")
    helper = package.root / "_helper.py"
    source = helper.read_text()
    if phase == "construction":
        source = source.replace(
            "  super().__init__()", "  from .undeclared import value\n  super().__init__()"
        )
    elif phase == "forward":
        source = source.replace(
            " def forward(self, x): return",
            " def forward(self, x):\n  from .undeclared import value\n  return",
        )
    else:
        source += "\ndef refuse(gradient):\n from .undeclared import value\n return gradient\n"
        source = source.replace(
            " def forward(self, x): return",
            " def forward(self, x):\n  self.weight.register_hook(refuse)\n  return",
        )
    helper.write_text(source)
    package = capture_package(
        CodePackageDeclaration(root=".", files=("model.py", "_helper.py")), package.root
    )
    with (
        bind_code_package(package),
        pytest.raises(LocalCodeError, match="undeclared relative import"),
    ):
        validator._check_instantiation_and_gradient(str(package.root / "model.py"))
