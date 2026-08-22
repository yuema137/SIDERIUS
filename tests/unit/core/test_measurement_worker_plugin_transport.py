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

import ast
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


_PRODUCTION_ROOTS = ("core", "execute_tools", "agent", "nodes", "workflows", "dashboard")


def _production_popen_sites() -> list[tuple[str, int, set[str]]]:
    """Every ``subprocess.Popen(...)`` in production, with its kwarg names.

    Scope, stated so this census cannot pass for the wrong reason: it
    covers the **Popen** form only — the long-lived supervised worker
    child, which is exactly the failure class here. `subprocess.run` calls
    that launch `nvidia-smi`, `git` or `pytest` are a different shape
    (short-lived external tools that consume no SIDERIUS plugin context)
    and are deliberately outside it. The scope is defined by CALL FORM, not
    by a list of file names — a by-name exemption is the F-P2b-4 shape this
    census exists to replace.
    """
    sites: list[tuple[str, int, set[str]]] = []
    for root in _PRODUCTION_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - defensive
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Popen"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                ):
                    sites.append(
                        (
                            str(path.relative_to(REPO_ROOT)),
                            node.lineno,
                            {kw.arg for kw in node.keywords if kw.arg},
                        )
                    )
    return sites


class TestEveryProductionWorkerSpawnerTransportsTheEnvironment:
    """Step 11 C1 (F-11-2) — the CONTRACT, not one file by path.

    The guard this replaced asserted that the substring
    ``"env=subprocess_env("`` appeared in ONE named file. It was green
    while a second production spawner one directory along
    (`agent/skills/evaluate_vram_skill/isolated_probe.py`) had the very
    omission it was written to catch — the F-P2b-4 shape recorded in
    Step 10: a census green for the wrong reason.

    Derived, not enumerated: any NEW production `subprocess.Popen` is in
    scope the moment it is written.
    """

    def test_the_census_is_not_vacuous(self):
        sites = _production_popen_sites()
        assert len(sites) >= 5, f"the census found too few spawners to be meaningful: {sites}"

    def test_every_production_popen_passes_env(self):
        offenders = [(p, ln) for p, ln, kwargs in _production_popen_sites() if "env" not in kwargs]
        assert offenders == [], (
            "a production child spawned with no env= inherits a parent that "
            "carries no SIDERIUS_PLUGIN_DIRS and loses the PYTHONPATH "
            f"extension: {offenders}"
        )

    def test_the_isolated_preflight_transports_the_run_scoped_dirs(self):
        """Passing *an* env is not enough — it must be the RUN's env.

        Asserted behaviourally against the real spawn: `run_isolated_preflight`
        is driven with a stub `command` so no worker is needed, and the env
        the production code hands `Popen` is captured.
        """
        from agent.skills.evaluate_vram_skill import isolated_probe as mod

        captured: dict[str, str] = {}

        def _fake_popen(argv, **kwargs):
            captured.update(kwargs.get("env") or {})
            # The env is handed to Popen BEFORE anything else can happen, so
            # failing here captures exactly what production passes and
            # returns through the module's own typed
            # PROBE_INFRASTRUCTURE_FAILURE path — no worker, no poll loop.
            raise OSError("census stub")

        spec = mod.IsolatedProbeSpec(
            label="census",
            model_type="fcnet",
            result_path=str(Path(os.environ.get("PYTEST_TMPDIR", "/tmp")) / "census.json"),
            worker_memory_limit_bytes=1024**3,
            plugin_dir="/run/scoped/plugins",
            loss_dir="/run/scoped/losses",
        )
        real_popen = subprocess.Popen
        try:
            subprocess.Popen = _fake_popen  # type: ignore[assignment]
            result = mod.run_isolated_preflight(spec, deadline_seconds=0.1, command=["/bin/true"])
        finally:
            subprocess.Popen = real_popen  # type: ignore[assignment]

        assert result.outcome == "PROBE_INFRASTRUCTURE_FAILURE"
        assert captured.get("SIDERIUS_PLUGIN_DIRS") == "/run/scoped/plugins"
        assert captured.get("SIDERIUS_LOSS_DIRS") == "/run/scoped/losses"

    def test_the_production_entrypoint_cannot_omit_them(self):
        """`run_production_preflight` takes both as keyword-only arguments
        with NO default, so the defect cannot silently return through a
        caller that forgets. An explicit `None` is a statement.
        """
        import inspect

        from agent.skills.evaluate_vram_skill.preflight_adapter import run_production_preflight

        params = inspect.signature(run_production_preflight).parameters
        for name in ("plugin_dir", "loss_dir"):
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert params[name].default is inspect.Parameter.empty

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
