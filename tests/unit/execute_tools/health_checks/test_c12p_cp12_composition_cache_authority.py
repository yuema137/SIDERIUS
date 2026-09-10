"""CP12 cache isolation after retirement of implicit scientific defaults.

The old witness installed LEGACY_DEFAULT_TASK_HEALTH_CONFIG and expected the
default loader to bind it. That path is retired, not restored by this test.
Tasks bind explicitly; the generic default has no roster. The surviving
invariants are cache HIT under unchanged binding, MISS after state changes,
and explicit task/guard behaviour independent of default-cache warmth.
Each scenario runs in a fresh interpreter from this exact checkout.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]

_PROBE = r"""
import json, sys
from pathlib import Path
from types import SimpleNamespace
import execute_tools.health_checks.config as cfg
from execute_tools.health_checks import _plugin_binding as binding
from execute_tools.health_checks.candidate_eligibility import resolve_run_scientific_gate_ids
assert Path(cfg.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
scenario, primary, alternate = sys.argv[2:]
out = {}
try:
    if scenario == "cache_identity":
        cfg.load_composed_health_config(None, primary)
        first = cfg.load_health_gates_config()
        out["same_binding_hit"] = cfg.load_health_gates_config() is first
        binding.reset_run_scope()
        second = cfg.load_health_gates_config()
        out["reset_misses"] = second is not first
        out["default_stays_rosterless"] = not second.health_gates
        out["default_does_not_rebind_task"] = binding.bound_task_facts() is None
        cfg.load_composed_health_config(None, alternate)
        third = cfg.load_health_gates_config()
        out["new_family_misses"] = third is not second
        out["new_family_hit"] = cfg.load_health_gates_config() is third
    elif scenario in ("tuner_cold", "tuner_warm"):
        if scenario == "tuner_warm":
            cfg.load_health_gates_config()
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _resolve_run_gate_ids, _resolve_run_health_config,
        )
        inp = SimpleNamespace(health_checks_config=None,
            task_composition_ref=SimpleNamespace(task_health_binding=primary))
        out["gate_ids"] = [gate.id for gate in _resolve_run_health_config(inp).health_gates]
        out["scientific_ids"] = sorted(_resolve_run_gate_ids(inp))
    elif scenario in ("guard_same", "guard_other", "guard_other_warm"):
        if scenario == "guard_other_warm":
            cfg.load_health_gates_config()
        resolve_run_scientific_gate_ids(primary)
        out["gate_ids"] = sorted(resolve_run_scientific_gate_ids(
            primary if scenario == "guard_same" else alternate))
    else:
        raise ValueError("unknown probe scenario")
    out["outcome"] = "ok"
except Exception as exc:
    out["outcome"] = "raised"
    out["exc_type"] = type(exc).__name__
    out["exc"] = str(exc)
facts = binding.bound_task_facts()
out["encoding_family"] = facts.encoding_family if facts else None
print("CP12_JSON " + json.dumps(out))
"""


@pytest.fixture(scope="module")
def health_configs(tmp_path_factory):
    root = tmp_path_factory.mktemp("explicit_health_families")
    paths = []
    for family in ("primary", "alternate"):
        plugin = root / f"{family}.py"
        plugin.write_text(
            "from execute_tools.health_checks import register\n"
            "from execute_tools.health_checks.schemas import HealthCheckResult\n"
            "class Check:\n"
            f"    name = 'synthetic_{family}'\n"
            "    def run(self, ctx, config=None):\n"
            "        return HealthCheckResult(check_name=self.name, passed=True)\n"
            "register(Check())\n",
            encoding="utf-8",
        )
        path = root / f"{family}.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "facts": {"encoding_family": f"synthetic_{family}"},
                    "plugins": [{"kind": "file", "ref": plugin.name}],
                    "roster": [
                        {
                            "gate_id": f"{family}_blocking",
                            "check": f"synthetic_{family}",
                            "disposition": "blocking",
                            "reason": "Synthetic cache witness.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _run(scenario, configs):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO_ROOT), scenario, *map(str, configs)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    lines = [
        line.removeprefix("CP12_JSON ")
        for line in result.stdout.splitlines()
        if line.startswith("CP12_JSON ")
    ]
    assert len(lines) == 1, (result.stdout, result.stderr)
    return json.loads(lines[0])


def test_cache_hits_and_misses_follow_explicit_binding_identity(health_configs):
    obs = _run("cache_identity", health_configs)
    assert obs == {
        "same_binding_hit": True,
        "reset_misses": True,
        "new_family_misses": True,
        "new_family_hit": True,
        "default_stays_rosterless": True,
        "default_does_not_rebind_task": True,
        "outcome": "ok",
        "encoding_family": "synthetic_alternate",
    }


def test_tuner_first_resolution_uses_its_task_even_with_warm_default_cache(health_configs):
    cold = _run("tuner_cold", health_configs)
    warm = _run("tuner_warm", health_configs)
    assert (
        cold
        == warm
        == {
            "gate_ids": ["primary_blocking"],
            "scientific_ids": ["primary_blocking"],
            "encoding_family": "synthetic_primary",
            "outcome": "ok",
        }
    )


def test_explicit_family_guard_is_discriminative_with_cold_and_warm_cache(health_configs):
    same = _run("guard_same", health_configs)
    assert same == {
        "gate_ids": ["primary_blocking"],
        "outcome": "ok",
        "encoding_family": "synthetic_primary",
    }
    for scenario in ("guard_other", "guard_other_warm"):
        other = _run(scenario, health_configs)
        assert other["outcome"] == "raised", other
        assert other["exc_type"] == "HealthPluginRunScopeError", other


def test_memo_key_observes_all_run_scoped_binding_globals():
    def function(relative, name):
        tree = ast.parse((REPO_ROOT / relative).read_text())
        return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)

    reset = function("execute_tools/health_checks/_plugin_binding.py", "reset_run_scope")
    key = function("execute_tools/health_checks/config.py", "_resolved_binding_identity")
    cleared = {
        name
        for node in ast.walk(reset)
        if isinstance(node, ast.Global)
        for name in node.names
        if name.startswith("_")
    }
    cleared.update(
        node.value.id
        for node in ast.walk(reset)
        if isinstance(node, ast.Attribute)
        and node.attr == "clear"
        and isinstance(node.value, ast.Name)
        and node.value.id.startswith("_")
    )
    observed = {
        node.attr
        for node in ast.walk(key)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "_plugin_binding"
        and node.attr.startswith("_")
    }
    assert cleared == {"_RUN_SCOPE", "_TASK_FACTS", "_VIEW_BINDINGS"}
    assert observed == cleared
