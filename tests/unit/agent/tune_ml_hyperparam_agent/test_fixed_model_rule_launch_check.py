"""Issue #1047: a fixed model refuses a model_config lock it would drop, once, at launch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]

# Default ``extra="ignore"``: without the check, ``segmentaton_size`` is dropped.
PLUGIN = """
import torch
from pydantic import BaseModel
PLUGIN_MODEL_TYPE = "fixed_rule_probe"
PLUGIN_OUTPUT_TYPE = "classifier"
class Config(BaseModel):
    model_type: str = "fixed_rule_probe"
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
import json
workspace, checkout, rules = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
bind_generated_library_to_workspace(str(workspace))
from workflows.task_composition import compose_run_task_bindings, bind_run_task_composition, build_task_composition_ref
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.parameter_rules import ParameterRuleError
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import HyperparamTuningAgent
class ReachedBridge(Exception):
    pass
def bridge(**kwargs):
    raise ReachedBridge
composition = compose_run_task_bindings(str(checkout / "configs/task_composition/quickstart.yaml"))
with bind_run_task_composition(composition, physical_data_root=str(workspace / "data")):
    request = HyperparamTuningInput(
        run_seed=20261028,
        planner_strategy="native-timing-v1",
        model_type="fixed_rule_probe", file_index=2, seed_plugin_path=str(workspace / "seed.py"),
        storage={"backend": "local", "local": {"workspace": str(workspace / "records"), "run_name": "probe"}},
        data_dir=str(workspace / "data"), health_gate_enabled=False,
        task_composition_ref=build_task_composition_ref(composition),
        workflow_parameter_rules=rules,
        max_rounds=1, attempts_per_round=1,
    )
    node = HyperparamTuningAgent(bridge_factory=bridge, sandbox_factory=lambda **kwargs: SimpleNamespace(plugin_dir=str(workspace / "plugins")))
    try:
        node.run(request)
    except ReachedBridge:
        print("OUTCOME reached-bridge")
    except ParameterRuleError as exc:
        print("OUTCOME refused", exc)
"""


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (
            {"model_config.segmentaton_size": {"exact": 4}},
            "OUTCOME refused unsupported model_config parameter path",
        ),
        # Can never pass for the forced model: refused once, not per attempt.
        (
            {"model_config.model_type": {"allowed": ["wavenet"]}},
            "OUTCOME refused workflow parameter rule for 'model_config.model_type'",
        ),
        ({"model_config.segmentation_size": {"exact": 4}}, "OUTCOME reached-bridge"),
    ],
    ids=["typo-target", "model-type-allowed-list", "valid-lock"],
)
def test_fixed_model_refuses_impossible_model_rule_before_any_attempt(
    tmp_path: Path, rules: dict, expected: str
) -> None:
    """Without the launch check, each attempt spends an LLM call before refusing the rule."""
    (tmp_path / "data").mkdir()
    (tmp_path / "plugins").mkdir()
    (tmp_path / "seed.py").write_text(textwrap.dedent(PLUGIN))
    script = tmp_path / "worker.py"
    script.write_text(textwrap.dedent(WORKER))
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1")
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path), str(ROOT), json.dumps(rules)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout, result.stdout[-2000:] + result.stderr[-2000:]
