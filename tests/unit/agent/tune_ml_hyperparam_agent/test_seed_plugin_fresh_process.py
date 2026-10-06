"""Standalone seed handoff must work without a validator's process registry."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]

PLUGIN = """
import builtins
builtins._seed_probe_imports = getattr(builtins, "_seed_probe_imports", 0) + 1
import torch
from pydantic import BaseModel
PLUGIN_MODEL_TYPE = "isolated_seed_probe"
PLUGIN_OUTPUT_TYPE = "classifier"
class Config(BaseModel):
    model_type: str = "isolated_seed_probe"
    segmentation_size: int = 4
class Model(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.layer = torch.nn.Linear(4, 2)
    def forward(self, x):
        return self.layer(x)
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Model
"""

WORKER = """
import sys
from pathlib import Path
from types import SimpleNamespace
from core.generated_library import bind_generated_library_to_workspace
workspace, checkout, expected = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
preloaded = sys.argv[4] == "preloaded"
bind_generated_library_to_workspace(str(workspace))
from workflows.task_composition import compose_run_task_bindings, bind_run_task_composition, build_task_composition_ref
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from ml_models.plugin_loader import get_output_type, UnknownOutputContractError
from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
from ml_models.models_sandbox import MODEL_REGISTRY
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import HyperparamTuningAgent
name = "isolated_seed_probe"
assert name not in MODEL_REGISTRY
try:
    get_output_type(name)
except UnknownOutputContractError:
    pass
else:
    raise AssertionError("fresh-process witness already had a model contract")
if preloaded:
    from ml_models.plugin_loader import register_model_in_memory
    assert register_model_in_memory(str(workspace / "seed.py")) == name
    original_model = MODEL_REGISTRY[name]
    original_config = PLUGIN_CONFIG_REGISTRY[name]
class ReachedBridge(Exception):
    pass
calls = []
def bridge(**kwargs):
    import builtins
    calls.append(True)
    assert builtins._seed_probe_imports == 1, "workflow seed imported a second time"
    if preloaded:
        assert MODEL_REGISTRY[name] is original_model
        assert PLUGIN_CONFIG_REGISTRY[name] is original_config
    assert get_output_type(name) == "classifier"
    config = PLUGIN_CONFIG_REGISTRY[name]()
    import torch
    assert tuple(MODEL_REGISTRY[name](config)(torch.ones(3, 4)).shape) == (3, 2)
    raise ReachedBridge
composition = compose_run_task_bindings(str(checkout / "configs/task_composition/quickstart.yaml"))
with bind_run_task_composition(composition, physical_data_root=str(workspace / "data")):
    request = HyperparamTuningInput(
        planner_strategy="native-timing-v1",
        model_type=name, file_index=2, seed_plugin_path=str(workspace / "seed.py"),
        storage={"backend": "local", "local": {"workspace": str(workspace / "records"), "run_name": "probe"}},
        data_dir=str(workspace / "data"), health_gate_enabled=False,
        task_composition_ref=build_task_composition_ref(composition),
        max_rounds=1, attempts_per_round=1,
    )
    node = HyperparamTuningAgent(bridge_factory=bridge, sandbox_factory=lambda **kwargs: SimpleNamespace(plugin_dir=str(workspace / "plugins")))
    try:
        node.run(request)
    except ReachedBridge:
        assert expected == "success"
        assert calls == [True]
    except ValueError as exc:
        assert expected == "failure" and "Seed model registration failed" in str(exc), str(exc)
        assert calls == []
        assert name not in MODEL_REGISTRY
    else:
        raise AssertionError("expected pre-planning observation")
assert (workspace / "plugins/seed.py").read_bytes() == (workspace / "seed.py").read_bytes()
print("FRESH_SEED_HANDOFF_PASS")
"""


@pytest.mark.parametrize(
    "broken_import,preloaded",
    [(False, False), (True, False), (False, True)],
    ids=["registered-before-plan", "import-failure-refuses", "workflow-registration-preserved"],
)
def test_native_run_registers_staged_seed_before_planning(tmp_path, broken_import, preloaded):
    """Real run() reaches the bridge with a usable contract, or refuses first."""
    (tmp_path / "data").mkdir()
    (tmp_path / "plugins").mkdir()
    source = textwrap.dedent(PLUGIN)
    if broken_import:
        source += '\nraise RuntimeError("synthetic plugin import failure")\n'
    (tmp_path / "seed.py").write_text(source)
    script = tmp_path / "worker.py"
    script.write_text(textwrap.dedent(WORKER))
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_path),
            str(ROOT),
            "failure" if broken_import else "success",
            "preloaded" if preloaded else "fresh",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FRESH_SEED_HANDOFF_PASS" in result.stdout
