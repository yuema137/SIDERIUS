"""Real cold children verify captured pins before selected source executes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.generated_library import bind_generated_library_to_workspace
from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    acquire_module,
    bind_code_package,
    bootstrap_code_package,
    capture_package,
    root_code_scope,
)
from core.local_code.transport import DIGEST_ENV, MANIFEST_ENV
from core.subprocess_env import subprocess_env


def captured_fixture(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir()
    marker = tmp_path / "executed"
    (code / "_helper.py").write_text(
        "from pydantic import BaseModel\nfrom torch.nn import Module\n"
        "class Config(BaseModel): pass\nclass Model(Module): pass\n"
        "def calculate(value): return value + 7\n"
    )
    (code / "model.py").write_text(
        "from ._helper import Config, Model\n"
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "PLUGIN_MODEL_TYPE = 'local_transport_model'\nPLUGIN_CONFIG_CLASS = Config\n"
        "PLUGIN_MODEL_CLASS = Model\nPLUGIN_OUTPUT_TYPE = 'regressor'\n"
    )
    (code / "loss.py").write_text(
        "from ._helper import Config, Model\nPLUGIN_LOSS_TYPE = 'local_transport_loss'\n"
        "PLUGIN_LOSS_CONFIG_CLASS = Config\nPLUGIN_LOSS_CLASS = Model\n"
        "PLUGIN_LOSS_TARGET_DTYPE = 'float'\nPLUGIN_LOSS_REDUCTION = 'mean'\n"
    )
    captured = capture_package(
        CodePackageDeclaration(root="code", files=("model.py", "loss.py", "_helper.py")), tmp_path
    )
    return captured, marker


def bind_workspace(tmp_path: Path, monkeypatch):
    env: dict[str, str] = {}
    bind_generated_library_to_workspace(str(tmp_path / "workspace"), environ=env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "helper-edit",
        "helper-missing",
        "manifest-edit",
        "half",
        "empty-scan",
        "missing-declaration",
    ],
)
def test_cold_model_bootstrap_checks_all_members_before_execution(tmp_path, monkeypatch, case):
    """Restoring broad bootstrap catch or spawn-time recapture executes the marker."""
    captured, marker = captured_fixture(tmp_path)
    bind_workspace(tmp_path, monkeypatch)
    with bind_code_package(captured):
        env = subprocess_env(plugin_dir=str(captured.root), loss_dir=str(captured.root))
        original = Path(env[MANIFEST_ENV]).read_bytes()
        if case in {"helper-edit", "empty-scan"}:
            (captured.root / "_helper.py").write_text(
                "raise AssertionError('tampered helper executed')\n"
            )
        if case == "helper-missing":
            (captured.root / "_helper.py").unlink()
        # Calling production env construction AFTER mutation must not re-pin.
        assert subprocess_env()[MANIFEST_ENV] == env[MANIFEST_ENV]
        assert Path(env[MANIFEST_ENV]).read_bytes() == original
    if case == "manifest-edit":
        Path(env[MANIFEST_ENV]).write_bytes(b"{}")
    if case == "half":
        env.pop(DIGEST_ENV)
    if case == "empty-scan":
        env["SIDERIUS_PLUGIN_DIRS"] = str(tmp_path / "missing-model-dir")
    env["CUDA_VISIBLE_DEVICES"] = ""
    code = """
import sys
from core.local_code import LocalCodeError, composition_package
try:
    if sys.argv[1] == 'missing-declaration':
        with composition_package(None, sys.argv[2]): pass
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.loss_plugin_loader import load_loss_plugin
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    loss = load_loss_plugin('local_transport_loss')
    assert loss['loss_class'] is MODEL_REGISTRY['local_transport_model']
    assert loss['config_class'] is PLUGIN_CONFIG_REGISTRY['local_transport_model']
    from core.subprocess_env import subprocess_env
    import os
    assert subprocess_env()['SIDERIUS_TASK_CODE_SHA256'] == os.environ['SIDERIUS_TASK_CODE_SHA256']
except LocalCodeError as exc:
    print('REFUSED:' + str(exc))
    sys.exit(23)
print('PINNED')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, case, str(captured.root)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == (0 if case == "success" else 23), result.stdout + result.stderr
    assert marker.exists() is (case == "success")
    assert ("PINNED" if case == "success" else "REFUSED:") in result.stdout


def test_explicit_absence_masks_stale_halves_and_transport_needs_workspace(tmp_path, monkeypatch):
    captured, _ = captured_fixture(tmp_path)
    monkeypatch.setenv(MANIFEST_ENV, "/missing/stale.json")
    monkeypatch.delenv(DIGEST_ENV, raising=False)
    with root_code_scope():
        assert MANIFEST_ENV not in subprocess_env()
        assert DIGEST_ENV not in subprocess_env()
        assert os.environ[MANIFEST_ENV] == "/missing/stale.json"
        with bind_code_package(captured):
            monkeypatch.delenv("SIDERIUS_CHAIN_WORKSPACE", raising=False)
            with pytest.raises(LocalCodeError, match="explicit bound workspace"):
                subprocess_env()
    assert not (tmp_path / "workspace").exists()


def test_spawn_pool_initializer_installs_names_before_unpickling(tmp_path, monkeypatch):
    """A captured helper callable needs the same finder in a genuinely spawned worker."""
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    captured, marker = captured_fixture(tmp_path)
    bind_workspace(tmp_path, monkeypatch)
    with bind_code_package(captured), acquire_module(captured.root / "_helper.py") as helper:
        env = subprocess_env()
        with ProcessPoolExecutor(
            max_workers=1,
            mp_context=get_context("spawn"),
            initializer=bootstrap_code_package,
            initargs=(env[MANIFEST_ENV], env[DIGEST_ENV]),
        ) as pool:
            assert pool.submit(helper.calculate, 5).result(timeout=60) == 12
    assert not marker.exists(), "initializer must install names, not execute unrelated entries"
