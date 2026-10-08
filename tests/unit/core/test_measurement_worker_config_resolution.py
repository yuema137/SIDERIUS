"""The worker's OWN validation function must resolve a generated plugin.

V20 attempt 3 (aborted 2026-08-07). PR #184 fixed the *transport* — the
measurement worker is now spawned with `env=subprocess_env(...)` so
`SIDERIUS_PLUGIN_DIRS` reaches it. The campaign died anyway, because the
consumer never used it.

`build_production_components` imports `ml_models.models_sandbox`, whose
import populates `PLUGIN_CONFIG_REGISTRY` via `extend_registries`
(`models_sandbox.py:750-753`). `validate_candidate_configs` imported only
`models_format_sandbox`, so `get_config_class` read an EMPTY registry and
returned `None` for every agent-generated model:

    status : CONFIG_REJECTED
    detail : no config class registered for '<generated model>'

Two paths in one file, one import apart, disagreeing about whether a
model exists. Every candidate passed its trial rounds and died at the
formal promotion boundary; the attempt produced 0 formal records.

**Why the PR #184 tests did not catch it.** They asserted that a clean
subprocess could resolve the plugin — it could. They never called the
function the worker actually calls. `test_measurement_worker_plugin_transport`
proves the environment arrives; this module proves the worker *uses* it.
Both are required; neither implies the other.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

PLUGIN_SRC = textwrap.dedent(
    '''
    """Stand-in for an agent-generated model plugin."""
    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "config_probe_model"

    class ConfigProbeConfig(BaseModel):
        model_type: str = "config_probe_model"
        segmentation_size: int = 64
        num_classes: int = 256

    class ConfigProbeModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.emb = nn.Embedding(256, 8)
            self.head = nn.Conv1d(8, 256, 1)
        def forward(self, x):
            return self.head(self.emb(x).transpose(1, 2))

    PLUGIN_CONFIG_CLASS = ConfigProbeConfig
    PLUGIN_MODEL_CLASS = ConfigProbeModel
    '''
)


@pytest.fixture
def plugin_dir(tmp_path) -> Path:
    d = tmp_path / "plugins"
    d.mkdir()
    (d / "config_probe_model.py").write_text(PLUGIN_SRC)
    return d


def _validate_in_clean_subprocess(plugin_dir: Path) -> dict:
    """Call `validate_candidate_configs` in a FRESH interpreter.

    In-process this test is vacuous: pytest has already imported
    `models_sandbox` through some other module, so the registry is warm
    and the defect is invisible. Only a clean interpreter reproduces the
    worker's actual starting state.
    """
    code = textwrap.dedent(
        """
        import json
        from types import SimpleNamespace
        out = {"rejection": "UNSET", "error": None}
        try:
            # The REAL production function under test.
            from core.runtime_control.gpu_measurement_worker_main import (
                validate_candidate_configs,
            )
            # The optional contract is absent in this registry-only witness.
            # A stand-in keeps this test bound to registry resolution rather
            # than to unrelated GpuMeasurementSpec fields (result_path,
            # worker_memory_limit_bytes, device_uuid, ...) whose evolution
            # says nothing about the defect. If the function grows a new
            # field read, this fails loudly with AttributeError -- which is
            # the correct signal to revisit the stand-in.
            spec = SimpleNamespace(
                request=SimpleNamespace(model_type="config_probe_model"),
                model_config_payload={
                    "model_type": "config_probe_model", "segmentation_size": 64,
                },
                train_config={"lr": 5e-4, "epochs": 1, "batch_size": 2},
                loss_config={"loss_type": "ce"},
                model_io_contract=None,
            )
            out["rejection"] = validate_candidate_configs(spec)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        print("VERDICT " + json.dumps(out))
        """
    )
    from core.subprocess_env import subprocess_env

    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=subprocess_env(plugin_dir=str(plugin_dir)),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("VERDICT ")]
    if not lines:
        pytest.skip(f"probe produced no verdict:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(lines[-1][len("VERDICT ") :])


class TestTheWorkerResolvesWhatItWasGiven:
    def test_validation_accepts_a_generated_plugin_in_a_clean_process(self, plugin_dir):
        got = _validate_in_clean_subprocess(plugin_dir)
        assert got["error"] is None, got["error"]
        assert got["rejection"] is None, (
            "validate_candidate_configs rejected a plugin whose directory it "
            f"was given: {got['rejection']!r}. This is the V20 attempt-3 "
            "defect — the validation path did not import models_sandbox, so "
            "PLUGIN_CONFIG_REGISTRY was empty and every agent-generated "
            "candidate was reported CONFIG_REJECTED at formal promotion."
        )

    def test_the_rejection_message_reports_registry_size(self, plugin_dir):
        # The original message named only the model, so the record could not
        # distinguish "this model is genuinely unknown" from "the registry
        # was never populated". Three audits misread it as the former.
        got = _validate_in_clean_subprocess(plugin_dir.parent / "does_not_exist")
        assert got["error"] is None, got["error"]
        assert got["rejection"] is not None, "an unresolvable model must reject"
        assert "in the live registry" in got["rejection"], (
            "the rejection must state how many models the registry held, or "
            "an empty-registry failure is indistinguishable from an unknown "
            f"model: {got['rejection']!r}"
        )


class TestTheTwoPathsAgree:
    def test_both_import_sites_populate_the_registry(self):
        """Reachability guard: the two config-resolving paths must not drift.

        `build_production_components` and `validate_candidate_configs` both
        call `get_config_class`, which depends on the `models_sandbox`
        import side effect. If either drops that import, generated models
        become invisible to that path alone — exactly the asymmetry that
        cost attempt 3, and one that no in-process test can see.
        """
        import ast

        src = (
            REPO_ROOT / "src/core" / "runtime_control" / "gpu_measurement_worker_main.py"
        ).read_text()
        tree = ast.parse(src)

        targets = {"build_production_components", "validate_candidate_configs"}
        seen: dict[str, bool] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in targets:
                continue
            calls_resolver = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "get_config_class"
                for n in ast.walk(node)
            )
            if not calls_resolver:
                continue
            seen[node.name] = any(
                isinstance(n, ast.ImportFrom) and n.module == "ml_models.models_sandbox"
                for n in ast.walk(node)
            )

        assert seen, "neither worker path calls get_config_class — test is stale"
        missing = sorted(name for name, ok in seen.items() if not ok)
        assert not missing, (
            f"{missing} call get_config_class without importing "
            "ml_models.models_sandbox, so PLUGIN_CONFIG_REGISTRY stays empty "
            "and every agent-generated model resolves to None"
        )
