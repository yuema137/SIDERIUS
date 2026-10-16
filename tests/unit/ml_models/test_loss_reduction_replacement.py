"""Successful loss replacement cannot inherit an older normalization claim."""

import sys

import pytest

from execute_tools.training_history import stamp_comparability
from ml_models import loss_models_sandbox as models
from ml_models import loss_plugin_loader as loader
from ml_models.models_format_sandbox import LossConfig

from .test_loss_contract_preimport import _plugin_source, _snapshot

NAME = "transport_loss"
REGISTRIES = (
    models.LOSS_REGISTRY,
    models.LOSS_CONFIG_REGISTRY,
    models.LOSS_CONTRACT_REGISTRY,
    loader.LOSS_TARGET_DTYPE_REGISTRY,
    loader.LOSS_REDUCTION_REGISTRY,
)


@pytest.fixture(autouse=True)
def restore_state():
    saved = [dict(registry) for registry in REGISTRIES]
    modules = {
        name: module
        for name, module in sys.modules.items()
        if name.startswith(loader._MODULE_NAME_PREFIX)
    }
    yield
    for registry, original in zip(REGISTRIES, saved, strict=True):
        registry.clear()
        registry.update(original)
    for name in list(sys.modules):
        if name.startswith(loader._MODULE_NAME_PREFIX):
            sys.modules.pop(name)
    sys.modules.update(modules)


def source(tmp_path, reduction):
    text = _plugin_source(_snapshot(2), tmp_path / "imported")
    if reduction != "omitted":
        text += f"\nPLUGIN_LOSS_REDUCTION = {reduction!r}\n"
    return text


def load(tmp_path, monkeypatch, route, stage, text):
    directory = tmp_path / stage
    directory.mkdir()
    path = directory / "replacement.py"
    path.write_text(text)
    if route == "memory":
        return models.register_loss_in_memory(str(path), _snapshot(2))
    monkeypatch.setattr(loader, "_resolve_loss_dirs", lambda: [str(directory)])
    return loader.load_loss_plugin(NAME, _snapshot(2))


@pytest.mark.parametrize("route", ["memory", "filesystem"])
@pytest.mark.parametrize(
    "before, after, expected",
    [
        ("mean", "omitted", None),
        ("mean", None, None),
        ("mean", "invalid", None),
        ("mean", "sum", "sum"),
        ("sum", "mean", "mean"),
        ("omitted", "mean", "mean"),
    ],
)
def test_successful_replacement_owns_its_reduction(
    tmp_path, monkeypatch, route, before, after, expected
):
    monkeypatch.setitem(loader.LOSS_REDUCTION_REGISTRY, "unrelated", "sum")
    assert load(tmp_path, monkeypatch, route, "before", source(tmp_path, before)) is not None
    assert load(tmp_path, monkeypatch, route, "after", source(tmp_path, after)) is not None
    assert loader.get_loss_declared_reduction(NAME) == expected
    if expected is None:
        assert NAME not in loader.LOSS_REDUCTION_REGISTRY
    state, reason = stamp_comparability(LossConfig(loss_type="custom", loss_name=NAME))
    assert state == ("established" if expected == "mean" else "not_established")
    assert (reason is None) == (expected == "mean")
    assert loader.LOSS_REDUCTION_REGISTRY["unrelated"] == "sum"


@pytest.mark.parametrize("route", ["memory", "filesystem"])
@pytest.mark.parametrize("failure", ["import", "dtype", "contract"])
def test_failed_replacement_preserves_selected_metadata(tmp_path, monkeypatch, route, failure):
    valid = source(tmp_path, "mean")
    assert load(tmp_path, monkeypatch, route, "before", valid) is not None
    previous = [dict(registry) for registry in REGISTRIES]
    invalid = source(tmp_path, "omitted")
    if failure == "import":
        invalid += '\nraise RuntimeError("broken import")\n'
        assert load(tmp_path, monkeypatch, route, "after", invalid) is None
    else:
        if failure == "dtype":
            invalid = invalid.replace(
                'PLUGIN_LOSS_TARGET_DTYPE = "float"', 'PLUGIN_LOSS_TARGET_DTYPE = "invalid"'
            )
        else:
            invalid = _plugin_source(_snapshot(3), tmp_path / "refused-import")
        with pytest.raises(ValueError):
            load(tmp_path, monkeypatch, route, "after", invalid)
    assert [dict(registry) for registry in REGISTRIES] == previous
    assert stamp_comparability(LossConfig(loss_type="custom", loss_name=NAME)) == (
        "established",
        None,
    )
    if failure == "contract":
        assert not (tmp_path / "refused-import").exists()
