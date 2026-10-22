"""Live sandbox names refuse before filesystem, validation, or pseudo-state effects."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from core import sandbox_executor as executor


@pytest.mark.parametrize("sandbox_type", [executor.TidmadSandbox, executor.StubSandbox])
@pytest.mark.parametrize("run_name", ["../escape", "/absolute", r"C:\escape", "bad\nname"])
def test_constructor_refuses_before_task_or_storage_resolution(
    sandbox_type, run_name, tmp_path, monkeypatch
):
    """Removing the constructor guard reaches task resolution or creates directories."""
    resolution = Mock(side_effect=AssertionError("task resolution reached"))
    directories = Mock(side_effect=AssertionError("directory creation reached"))
    monkeypatch.setattr(executor, "indexed_cleanup_naming", resolution)
    monkeypatch.setattr(executor, "_ensure_dir", directories)
    with pytest.raises(ValueError, match=r"run_name.*filesystem component"):
        sandbox_type(run_name=run_name, workspace=str(tmp_path / "workspace"))
    resolution.assert_not_called()
    directories.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.usefixtures("synthetic_dataset_profile", "synthetic_physical_data_root")
@pytest.mark.parametrize("sandbox_type", [executor.TidmadSandbox, executor.StubSandbox])
@pytest.mark.parametrize("method", ["execute_training", "execute_inference", "execute_scoring"])
@pytest.mark.parametrize("run_name", ["../escape", "/absolute", r"C:\escape", "bad\nname"])
def test_method_name_is_checked_independently_before_effects(
    sandbox_type, method, run_name, tmp_path, monkeypatch
):
    """A safe constructor must not authorize a different unsafe execution identity."""
    sandbox = sandbox_type(run_name="safe_run", workspace=str(tmp_path / "workspace"))
    # A real existing records parent exposes the scoring traversal mkdir defect.
    records = Path(sandbox.dirs["records"])
    assert records.is_dir()
    before = set(tmp_path.rglob("*"))
    first_effect = Mock(side_effect=AssertionError("validation or child launch reached"))
    monkeypatch.setattr(sandbox, "_validate_configs", first_effect)
    monkeypatch.setattr(sandbox, "_validate_model_and_loss", first_effect)
    monkeypatch.setattr(executor, "validate_sample_set", first_effect)
    monkeypatch.setattr(executor, "run_phase_subprocess", first_effect)
    monkeypatch.setattr(sandbox, "_write_dataset_profile_config", first_effect)
    state = None
    if isinstance(sandbox, executor.StubSandbox):
        state = (sandbox._rng.getstate(), deepcopy(sandbox._train_results_cache))
    kwargs = dict(exp_id="attempt", run_name=run_name, model_type="model", m_cfg={}, l_cfg={})
    if method != "execute_inference":
        kwargs["t_cfg"] = {}
    with pytest.raises(ValueError, match=r"run_name.*filesystem component"):
        getattr(sandbox, method)(**kwargs)
    first_effect.assert_not_called()
    assert set(tmp_path.rglob("*")) == before
    assert not (records.parent / "escape").exists()
    if isinstance(sandbox, executor.StubSandbox):
        assert (sandbox._rng.getstate(), sandbox._train_results_cache) == state
