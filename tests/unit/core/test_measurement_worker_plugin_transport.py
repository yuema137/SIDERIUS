"""A generated plugin must reach the isolated measurement worker.

V20 launch attempt 2 (aborted 2026-08-07) died here. The training and
inference subprocesses were spawned with an env carrying
`SIDERIUS_PLUGIN_DIRS`; the pre-phase GPU measurement worker was spawned
with no `env=` at all and inherited the parent's, which does not contain
that variable — it is built per-sandbox for the sandbox's own children.

The worker therefore started with a clean registry and returned:

    status : CONFIG_REJECTED
    detail : no config class registered for '<generated model>'

The pre-phase gate correctly fail-closed on that, so every
agent-generated candidate passed its trial rounds and then died at the
formal promotion boundary — 15 attempts on one chain.

**These tests must cross a real process boundary.** The defect is
invisible in-process: the parent's registry already holds the plugin, so
calling the worker's functions directly passes while the campaign still
dies. Each test below spawns an actual subprocess and asserts on what
THAT process could resolve.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

PLUGIN_SRC = textwrap.dedent(
    '''
    """A minimal stand-in for an agent-generated model plugin."""
    import torch
    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "transport_probe_model"

    class TransportProbeConfig(BaseModel):
        model_type: str = "transport_probe_model"
        segmentation_size: int = 64
        num_classes: int = 256

    class TransportProbeModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.emb = nn.Embedding(256, 8)
            self.head = nn.Conv1d(8, 256, 1)
        def forward(self, x):
            return self.head(self.emb(x).transpose(1, 2))

    PLUGIN_CONFIG_CLASS = TransportProbeConfig
    PLUGIN_MODEL_CLASS = TransportProbeModel
    '''
)


@pytest.fixture
def plugin_dir(tmp_path) -> Path:
    d = tmp_path / "plugins"
    d.mkdir()
    (d / "transport_probe_model.py").write_text(PLUGIN_SRC)
    return d


def _resolve_in_subprocess(env: dict[str, str]) -> dict:
    """Ask a CLEAN python process whether it can resolve the plugin.

    Deliberately `sys.executable -c` rather than an in-process call: the
    whole defect is that a fresh interpreter sees a different registry
    from its parent.
    """
    code = textwrap.dedent(
        """
        import json, sys
        out = {"loaded": False, "config": False, "error": None}
        try:
            # models_sandbox extends the registries from the resolved plugin
            # dirs at import time -- the same path every SIDERIUS subprocess
            # takes. Nothing here is test-only.
            from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
            from ml_models.models_sandbox import MODEL_REGISTRY
            out["loaded"] = "transport_probe_model" in MODEL_REGISTRY
            out["config"] = "transport_probe_model" in PLUGIN_CONFIG_REGISTRY
            out["registry_size"] = len(MODEL_REGISTRY)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(out))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if not line:
        pytest.skip(f"probe subprocess produced no verdict: {proc.stdout}\n{proc.stderr}")
    return json.loads(line[-1])


class TestTheTransportIsWhatMakesItWork:
    def test_a_clean_subprocess_resolves_the_plugin_when_the_env_is_transported(self, plugin_dir):
        from core.subprocess_env import subprocess_env

        got = _resolve_in_subprocess(subprocess_env(plugin_dir=str(plugin_dir)))
        assert got.get("error") is None, got["error"]
        assert got["loaded"] is True, (
            "a clean subprocess given SIDERIUS_PLUGIN_DIRS must resolve the "
            "generated plugin — this is the hop the measurement worker lacked"
        )
        assert got["config"] is True, (
            "the CONFIG class must resolve too: 'no config class registered' "
            "is the exact detail V20 attempt 2 died on"
        )

    def test_the_same_subprocess_FAILS_without_the_transport(self, plugin_dir):
        # The mutation, made permanent: this is precisely how the worker was
        # spawned in V20 attempt 2 (no env=, so the parent's environment,
        # which carries no SIDERIUS_PLUGIN_DIRS).
        env = os.environ.copy()
        env.pop("SIDERIUS_PLUGIN_DIRS", None)
        env["PYTHONPATH"] = str(REPO_ROOT)
        got = _resolve_in_subprocess(env)
        assert got.get("loaded") is not True, (
            "without the transported plugin dir the clean subprocess must NOT "
            "resolve the generated plugin; if it does, this test is no longer "
            "proving the seam"
        )

    def test_the_parent_registry_does_not_leak_across_the_boundary(self, plugin_dir):
        # Register in THIS process, then ask a clean one. If the child sees
        # it, the test harness is not crossing the seam and every assertion
        # above is vacuous.
        from ml_models.plugin_loader import register_model_in_memory

        try:
            registered = register_model_in_memory(str(plugin_dir / "transport_probe_model.py"))
        except Exception as exc:  # pragma: no cover - loader shape guard
            pytest.skip(f"could not pre-register in-process: {exc}")
        assert registered == "transport_probe_model", "precondition: parent must hold it"
        env = os.environ.copy()
        env.pop("SIDERIUS_PLUGIN_DIRS", None)
        env["PYTHONPATH"] = str(REPO_ROOT)
        got = _resolve_in_subprocess(env)
        assert got.get("loaded") is not True, (
            "the parent's MODEL_REGISTRY must not be visible to a clean "
            "subprocess — if it were, the in-process tests would have caught "
            "the V20 attempt-2 defect, and they did not"
        )


class TestTheSpawnerActuallyPassesIt:
    def test_the_measurement_runner_spawns_with_the_transported_env(self):
        # Reachability, asserted against the production call site: the
        # runner must pass env=subprocess_env(...) built from the spec's
        # plugin_dir. Parsed as source, because spawning a real measurement
        # worker needs CUDA and a dataset.
        src = (REPO_ROOT / "core" / "runtime_control" / "gpu_measurement_runner.py").read_text()
        assert "env=subprocess_env(" in src, (
            "the measurement worker must be spawned with the transported "
            "environment; without env= it inherits a parent that has no "
            "SIDERIUS_PLUGIN_DIRS"
        )
        assert "spec.plugin_dir" in src and "spec.loss_dir" in src

    def test_the_spec_carries_the_plugin_context(self):
        from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec

        fields = GpuMeasurementSpec.model_fields
        assert "plugin_dir" in fields and "loss_dir" in fields
        assert fields["plugin_dir"].default is None, "must stay optional for built-ins"

    def test_env_construction_has_exactly_one_home(self):
        # Two copies of "which variables a SIDERIUS subprocess needs" is how
        # the worker came to be missing one.
        exec_src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text()
        assert "from core.subprocess_env import subprocess_env" in exec_src
        assert exec_src.count('env["SIDERIUS_PLUGIN_DIRS"]') == 0, (
            "sandbox_executor must delegate to core.subprocess_env, not build "
            "the environment itself"
        )
