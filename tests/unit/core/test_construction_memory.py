import sys
from pathlib import Path
from typing import ClassVar

import pytest
import torch

from core.runtime_control.construction_memory import (
    CONSTRUCTION_REMAINDER_LIMIT_BYTES,
    CandidateAdmissionError,
    ConstructionMemory,
    admit_construction,
    measure_construction,
)


class Config:
    model_fields: ClassVar[dict] = {}


def test_unexplained_remainder_limit_remains_half_a_gibibyte():
    """The guard changed ownership, not its approved unexplained ceiling."""
    assert CONSTRUCTION_REMAINDER_LIMIT_BYTES == 512 * 1024**2


def _write_plugin(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}.py"
    path.write_text(
        "import torch\n"
        "from pydantic import BaseModel\n"
        f"PLUGIN_MODEL_TYPE = {name!r}\n"
        "class Config(BaseModel): pass\n"
        "class Model(torch.nn.Module):\n"
        "    def __init__(self, config): super().__init__()\n"
        "PLUGIN_CONFIG_CLASS = Config\n"
        "PLUGIN_MODEL_CLASS = Model\n"
    )
    return path


def test_registered_storage_is_counted_once_and_plain_tensor_is_remainder():
    class Model(torch.nn.Module):
        def __init__(self, _config):
            super().__init__()
            shared = torch.zeros(8)
            self.weight = torch.nn.Parameter(shared)
            self.register_buffer("alias", shared)
            self.hidden = torch.zeros(4)

    result = measure_construction(
        Model, Config, model_name="accounting", rss_reader=iter([0, 100]).__next__
    )
    assert result.parameter_bytes == 32
    assert result.buffer_bytes == 0
    assert result.unexplained_bytes == 68


def test_offset_view_and_registered_buffer_are_accounted_without_double_counting():
    """Backing storage, not tensor view address, owns the memory charge."""

    class Model(torch.nn.Module):
        def __init__(self, _config):
            super().__init__()
            shared = torch.zeros(8)
            self.weight = torch.nn.Parameter(shared)
            self.offset_view = torch.nn.Parameter(shared[2:])
            self.register_buffer("independent", torch.zeros(4))

    result = measure_construction(
        Model, Config, model_name="views", rss_reader=iter([0, 100]).__next__
    )
    assert result.parameter_bytes == 32
    assert result.buffer_bytes == 16
    assert result.unexplained_bytes == 52


def test_constructor_failure_is_typed_admission_refusal():
    class Broken(torch.nn.Module):
        def __init__(self, _config):
            super().__init__()
            raise RuntimeError("boom")

    with pytest.raises(CandidateAdmissionError, match="construction failed"):
        admit_construction(model_class=Broken, config_class=Config, model_name="broken")


def test_code_package_integrity_failure_is_not_downgraded_to_candidate_refusal():
    """Task-code integrity is fatal and must bypass proposal recovery."""
    from core.local_code import LocalCodeError

    class Broken(torch.nn.Module):
        def __init__(self, _config):
            super().__init__()
            raise LocalCodeError("tampered package")

    with pytest.raises(LocalCodeError, match="tampered package"):
        admit_construction(model_class=Broken, config_class=Config, model_name="broken")


def test_representative_length_and_loss_type_reach_constructor():
    """Preserve the old 2026-06-24 guard's production construction shape."""
    received: list[tuple[int, str]] = []

    class SegConfig:
        model_fields: ClassVar[dict] = {"segmentation_size": object()}

        def __init__(self, segmentation_size: int = 7):
            self.segmentation_size = segmentation_size

    class Model(torch.nn.Module):
        def __init__(self, config, loss_type: str = "ce"):
            super().__init__()
            received.append((config.segmentation_size, loss_type))

    measure_construction(
        Model,
        SegConfig,
        model_name="representative",
        representative_T=16000,
        rss_reader=iter([0, 0]).__next__,
    )
    assert received == [(16000, "focal")]


def test_rejected_representative_length_falls_back_to_config_default():
    """An incompatible probe length still performs a real construction."""
    received: list[int] = []

    class CappedConfig:
        model_fields: ClassVar[dict] = {"segmentation_size": object()}

        def __init__(self, segmentation_size: int = 500):
            if segmentation_size > 1000:
                raise ValueError("too large")
            self.segmentation_size = segmentation_size

    class Model(torch.nn.Module):
        def __init__(self, config):
            super().__init__()
            received.append(config.segmentation_size)

    measure_construction(
        Model,
        CappedConfig,
        model_name="fallback",
        representative_T=16000,
        rss_reader=iter([0, 0]).__next__,
    )
    assert received == [500]


def test_large_legitimate_parameters_are_not_rejected(monkeypatch):
    monkeypatch.setattr(
        "core.runtime_control.construction_memory.measure_construction",
        lambda *_args, **_kwargs: ConstructionMemory(700 * 1024**2, 650 * 1024**2, 0, 50 * 1024**2),
    )
    result = admit_construction(model_class=object, config_class=Config, model_name="large")
    assert result.parameter_bytes == 650 * 1024**2


def test_large_unexplained_remainder_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "core.runtime_control.construction_memory.measure_construction",
        lambda *_args, **_kwargs: ConstructionMemory(700 * 1024**2, 1, 0, 600 * 1024**2),
    )
    with pytest.raises(CandidateAdmissionError, match="unexplained remainder") as exc_info:
        admit_construction(model_class=object, config_class=Config, model_name="large")
    assert exc_info.value.model_name == "large"
    assert exc_info.value.measurement is not None


def test_inspection_restores_existing_module_entry(tmp_path):
    from ml_models.plugin_loader import _MODULE_NAME_PREFIX, inspect_model_plugin

    plugin_path = _write_plugin(tmp_path, "existing")
    module_name = _MODULE_NAME_PREFIX + "existing"
    sentinel = object()
    sys.modules[module_name] = sentinel  # type: ignore[assignment]
    try:
        with inspect_model_plugin(str(plugin_path)) as plugin:
            assert plugin is not None
            assert sys.modules[module_name] is not sentinel
        assert sys.modules[module_name] is sentinel
    finally:
        del sys.modules[module_name]


def test_inspection_removes_a_new_temporary_module(tmp_path):
    """A refused inspection cannot leave a candidate import in the process."""
    from ml_models.plugin_loader import _MODULE_NAME_PREFIX, inspect_model_plugin

    plugin_path = _write_plugin(tmp_path, "temporary")
    module_name = _MODULE_NAME_PREFIX + "temporary"
    assert module_name not in sys.modules
    with inspect_model_plugin(str(plugin_path)) as plugin:
        assert plugin is not None
        assert module_name in sys.modules
    assert module_name not in sys.modules
