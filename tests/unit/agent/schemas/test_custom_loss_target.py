"""Fractional targets must survive assembly, admission, registration and native routing."""

import pytest
import torch

from agent.schemas.custom_loss_contract import (
    ExplicitPairApplicability,
    build_custom_loss_contract_snapshot,
)
from agent.schemas.custom_loss_target import resolve_custom_loss_target
from agent.schemas.custom_loss_validation import validate_custom_loss_plugin
from agent.schemas.model_io_contract import Dimension, ModelIOContract, TensorAxis, TensorContract
from core.local_code import CodePackageDeclaration, bind_code_package, capture_package
from core.training_seeds import SeedContext, TrainingSeedPlan
from ml_models import loss_models_sandbox as losses
from ml_models import loss_plugin_loader as loader
from ml_models.models_format_sandbox import DtypeAdmissibility, LossConfig
from nodes.ml_model_implementor.ml_model_implementor import _assemble_loss_plugin


def tensor(*shape, dtype="float32"):
    return TensorContract(
        axes=tuple(
            TensorAxis(
                dimension=Dimension(fixed=x) if isinstance(x, int) else Dimension(symbolic=x)
            )
            for x in shape
        ),
        dtype=DtypeAdmissibility(admissible=(dtype,)),
    )


def contract(shape, dtype="float32"):
    target = tensor(*shape, dtype=dtype)
    prediction = tensor(*shape)
    applicability = ExplicitPairApplicability(prediction=prediction, target=target)
    snapshot = build_custom_loss_contract_snapshot(prediction, target, applicability)
    return ModelIOContract(input=prediction, output=prediction), target, applicability, snapshot


def source(snapshot, name="fractional_mse"):
    return _assemble_loss_plugin(
        name,
        "MSE oracle",
        {
            "forward_body": "return ((inputs - targets) ** 2).mean()",
            "target_dtype": "long",  # Untrusted generated metadata cannot override the task.
        },
        snapshot,
    )


@pytest.fixture(autouse=True)
def isolated_registries(monkeypatch):
    for owner, names in (
        (losses, ("LOSS_REGISTRY", "LOSS_CONFIG_REGISTRY", "LOSS_CONTRACT_REGISTRY")),
        (loader, ("LOSS_TARGET_DTYPE_REGISTRY", "LOSS_REDUCTION_REGISTRY")),
    ):
        for name in names:
            monkeypatch.setattr(owner, name, {})


@pytest.mark.parametrize("shape", [(3, 2), (3, 1, 4, 5)])
def test_fractional_objective_and_gradient_survive_real_plugin_route(tmp_path, shape):
    _, _, _, snapshot = contract(("B", *shape[1:]))
    path = tmp_path / "loss.py"
    path.write_text(source(snapshot))
    assert losses.register_loss_in_memory(str(path))
    config = LossConfig(loss_type="custom", loss_name="fractional_mse")
    criterion = losses.get_criterion(config)
    prediction = torch.full(shape, 0.5, requires_grad=True)
    original = torch.full(shape, 0.25)
    prepared = original.to(losses.get_target_torch_dtype(config))
    assert prepared.dtype == torch.float32
    assert torch.equal(prepared, original)
    value = criterion(prediction, prepared)
    assert value.item() == pytest.approx(0.0625)
    value.backward()
    torch.testing.assert_close(prediction.grad, torch.full(shape, 0.5 / prediction.numel()))


@pytest.mark.parametrize("captured", [False, True])
@pytest.mark.parametrize("declaration", ["missing", "long", "invalid", "malformed"])
def test_contradictory_or_missing_metadata_refused_by_loader_and_probe(
    tmp_path, captured, declaration
):
    model_io, target, applicability, snapshot = contract(("B", 2))
    code = source(snapshot)
    if declaration == "missing":
        code = code.replace('PLUGIN_LOSS_TARGET_DTYPE = "float"', "")
    elif declaration == "malformed":
        code = code.replace("PLUGIN_CAPABILITY_CONTRACT = ", "PLUGIN_CAPABILITY_CONTRACT = None # ")
    else:
        code = code.replace(
            'PLUGIN_LOSS_TARGET_DTYPE = "float"', f'PLUGIN_LOSS_TARGET_DTYPE = "{declaration}"'
        )
    path = tmp_path / "loss.py"
    path.write_text(code)
    package = capture_package(CodePackageDeclaration(root=".", files=("loss.py",)), tmp_path)
    from contextlib import nullcontext

    with bind_code_package(package) if captured else nullcontext():
        with pytest.raises(ValueError):
            loader.load_loss_plugin_from_path(str(path))
        error = validate_custom_loss_plugin(
            code,
            "fractional_mse",
            model_io,
            target,
            applicability,
            pair_provider=lambda: (torch.full((3, 2), 0.5), torch.full((3, 2), 0.25)),
            plugin_path=str(path) if captured else None,
        )
        assert error is not None


@pytest.mark.parametrize("broken_syntax", [False, True])
def test_mixed_library_skips_unrelated_invalid_contract(tmp_path, monkeypatch, broken_syntax):
    _, _, _, snapshot = contract(("B", 2))
    (tmp_path / "a_bad.py").write_text(
        source(snapshot, "other").replace(
            'PLUGIN_LOSS_TARGET_DTYPE = "float"', 'PLUGIN_LOSS_TARGET_DTYPE = "long"'
        )
    )
    if broken_syntax:
        (tmp_path / "a_bad.py").write_text("def malformed(:\n")
    (tmp_path / "z_good.py").write_text(source(snapshot))
    monkeypatch.setattr(loader, "_resolve_loss_dirs", lambda: [str(tmp_path)])
    assert (
        losses.get_target_torch_dtype(LossConfig(loss_type="custom", loss_name="fractional_mse"))
        == torch.float32
    )
    if broken_syntax:
        assert loader.load_loss_plugin("other") is None
    else:
        with pytest.raises(ValueError):
            loader.load_loss_plugin("other")


def test_unsupported_canonical_target_is_not_silently_narrowed():
    _, _, _, snapshot = contract(("B", 2), "float64")
    with pytest.raises(ValueError, match="canonical dtype"):
        resolve_custom_loss_target(snapshot)


def test_classification_and_uncontracted_legacy_route_remain_integer(tmp_path):
    _, _, _, snapshot = contract(("B", 2), "int64")
    path = tmp_path / "loss.py"
    path.write_text(source(snapshot))
    assert loader.load_loss_plugin_from_path(str(path))["target_dtype"] == "long"
    path.write_text(source(None).replace('PLUGIN_LOSS_TARGET_DTYPE = "long"', ""))
    assert loader.load_loss_plugin_from_path(str(path))["target_dtype"] == "long"
    assert losses.get_target_torch_dtype(LossConfig(loss_type="smooth_l1")) == torch.float32


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.usefixtures("synthetic_task_config")
def test_native_loops_and_validation_preserve_fractional_batches(tmp_path, monkeypatch, streaming):
    from torch.utils.data import DataLoader, TensorDataset

    import execute_tools.train_engine_sandbox as engine
    from execute_tools.dataset_config import bind_dataset_profile
    from execute_tools.task_data_path import bind_task_data_path
    from ml_models.models_format_sandbox import TrainConfig
    from tests.helpers.synthetic_training_data_path import TwoFamilyDataPath
    from tests.helpers.two_family_profile import write_two_family_fixture
    from tests.unit.execute_tools.test_step07a_c1_validation_pass import _sandbox, _tiny_model_cfg

    fx = write_two_family_fixture(tmp_path)
    data_path = TwoFamilyDataPath(fx)
    dataset = TensorDataset(torch.full((3, fx.seg_size), 128), torch.full((3, fx.seg_size), 0.25))
    monkeypatch.setattr(data_path, "_dataset", lambda *args: dataset)
    prediction = tensor("B", 256, fx.seg_size)
    target = tensor("B", fx.seg_size)
    snapshot = build_custom_loss_contract_snapshot(
        prediction, target, ExplicitPairApplicability(prediction=prediction, target=target)
    )
    path = tmp_path / "observed.py"
    path.write_text(
        _assemble_loss_plugin(
            "observed",
            "Observed objective",
            {
                "forward_body": "assert targets.dtype == torch.float32\nassert torch.all(targets == 0.25)\nreturn ((inputs.mean(dim=1) - targets) ** 2).mean()",
            },
            snapshot,
        )
    )
    assert losses.register_loss_in_memory(str(path))
    cfg = TrainConfig(epochs=1, batch_size=2, device="cpu", drop_last=False)
    loss_cfg = LossConfig(loss_type="custom", loss_name="observed")
    batches = []
    loss_cls = losses.LOSS_REGISTRY["observed"]
    original = loss_cls.forward

    def observe(self, inputs, targets):
        batches.append(targets.detach().clone())
        return original(self, inputs, targets)

    monkeypatch.setattr(loss_cls, "forward", observe)
    with bind_dataset_profile(fx.profile), bind_task_data_path(data_path):
        if streaming:
            result = engine.run_experiment_streaming(
                _tiny_model_cfg(fx.seg_size),
                cfg,
                loss_cfg,
                sample_set=fx.full_sample_set(),
                data_dir=fx.data_dir,
                sandbox_dirs=_sandbox(tmp_path, "run"),
                exp_id="run",
                seed_plan=TrainingSeedPlan(SeedContext(run_seed=123)),
                profile=fx.profile,
                **data_path.scope_kwargs(fx.full_sample_set(), None),
            )
        else:
            result = engine.run_experiment(
                _tiny_model_cfg(fx.seg_size),
                cfg,
                loss_cfg,
                DataLoader(dataset, batch_size=2),
                _sandbox(tmp_path, "run"),
                "run",
            )
        assert result is not None
        assert [batch.shape[0] for batch in batches] == [2, 1]
        batches.clear()

        class Constant(torch.nn.Module):
            def forward(self, inputs):
                return torch.full((len(inputs), 256, fx.seg_size), 0.5)

        score, rows, _ = engine._validation_pass(
            model=Constant(),
            criterion=losses.get_criterion(loss_cfg),
            model_cfg=_tiny_model_cfg(fx.seg_size),
            loss_cfg=loss_cfg,
            model_io=None,
            device=torch.device("cpu"),
            data_path=data_path,
            task_eval_scope=None,
            data_dir=fx.data_dir,
            batch_size=2,
        )
        assert score == pytest.approx(0.0625)
        assert rows == 3
        assert [batch.shape[0] for batch in batches] == [2, 1]


def test_cached_registration_cannot_bypass_target_contract(tmp_path):
    _, _, _, snapshot = contract(("B", 2))
    path = tmp_path / "loss.py"
    path.write_text(source(snapshot))
    assert losses.register_loss_in_memory(str(path))
    loader.LOSS_TARGET_DTYPE_REGISTRY["fractional_mse"] = "long"
    config = LossConfig(loss_type="custom", loss_name="fractional_mse")
    with pytest.raises(ValueError, match="conflicts"):
        losses.get_criterion(config)
    with pytest.raises(ValueError, match="conflicts"):
        losses.get_target_torch_dtype(config)


def test_filesystem_dtype_cache_preserves_identity_without_reimport(tmp_path, monkeypatch):
    _, _, _, snapshot = contract(("B", 2))
    path = tmp_path / "loss.py"
    marker = tmp_path / "imports"
    code = source(snapshot) + f"\nwith open({str(marker)!r}, 'a') as f: f.write('x')\n"
    path.write_text(code)
    monkeypatch.setattr(loader, "_resolve_loss_dirs", lambda: [str(tmp_path)])
    config = LossConfig(loss_type="custom", loss_name="fractional_mse")
    losses.get_criterion(config, expected_contract_snapshot=snapshot)
    for _ in range(3):
        assert (
            losses.get_target_torch_dtype(config, expected_contract_snapshot=snapshot)
            == torch.float32
        )
    assert marker.read_text() == "x"
    _, _, _, different = contract(("B", 3))
    with pytest.raises(ValueError, match="does not match"):
        losses.get_target_torch_dtype(config, expected_contract_snapshot=different)
    assert marker.read_text() == "x"


def test_integer_classification_keeps_cross_entropy_objective(tmp_path):
    prediction = tensor("B", 2)
    target = tensor("B", dtype="int64")
    snapshot = build_custom_loss_contract_snapshot(
        prediction, target, ExplicitPairApplicability(prediction=prediction, target=target)
    )
    path = tmp_path / "ce.py"
    path.write_text(
        _assemble_loss_plugin(
            "integer_ce",
            "CE oracle",
            {
                "forward_body": "return F.cross_entropy(inputs, targets)",
            },
            snapshot,
        )
    )
    assert losses.register_loss_in_memory(str(path))
    config = LossConfig(loss_type="custom", loss_name="integer_ce")
    logits = torch.zeros((2, 2), requires_grad=True)
    labels = torch.tensor([0, 1]).to(losses.get_target_torch_dtype(config))
    assert labels.dtype == torch.int64
    value = losses.get_criterion(config)(logits, labels)
    assert value.item() == pytest.approx(0.69314718056)
    value.backward()
    torch.testing.assert_close(logits.grad, torch.tensor([[-0.25, 0.25], [0.25, -0.25]]))


@pytest.mark.parametrize("entry", ["measurement", "streaming_standardization"])
@pytest.mark.usefixtures("synthetic_task_config")
def test_early_target_resolution_checks_active_identity_before_plugin_import(
    tmp_path, monkeypatch, entry
):
    from types import SimpleNamespace

    import execute_tools.train_engine_sandbox as engine
    from core.runtime_control.gpu_training_components import prepare_task_training_components
    from ml_models.models_format_sandbox import TrainConfig
    from tests.helpers.two_family_profile import write_two_family_fixture
    from tests.unit.execute_tools.test_step07a_c1_validation_pass import _sandbox, _tiny_model_cfg

    _, _, _, actual = contract(("B", 2))
    _, _, _, expected = contract(("B", 3))
    marker = tmp_path / "imported"
    path = tmp_path / "loss.py"
    path.write_text(source(actual) + f"\nopen({str(marker)!r}, 'w').close()\n")
    monkeypatch.setattr(loader, "_resolve_loss_dirs", lambda: [str(tmp_path)])
    config = LossConfig(loss_type="custom", loss_name="fractional_mse")
    with pytest.raises(ValueError, match="contract"):
        if entry == "measurement":
            spec = SimpleNamespace(
                task_probe_data=SimpleNamespace(sampling=SimpleNamespace(epoch_seed=1)),
                expected_custom_loss_snapshot=expected,
            )
            prepare_task_training_components(
                spec,
                model=torch.nn.Linear(2, 2),
                train_cfg=TrainConfig(device="cpu"),
                loss_cfg=config,
                input_dtype=torch.float32,
                deadline_at=None,
            )
        else:
            fx = write_two_family_fixture(tmp_path)
            monkeypatch.setattr(engine, "get_output_type", lambda _: "regressor")
            engine.run_experiment_streaming(
                _tiny_model_cfg(fx.seg_size),
                TrainConfig(epochs=1, device="cpu", target_standardization="training_pool_global"),
                config,
                sample_set=fx.full_sample_set(),
                data_dir=fx.data_dir,
                sandbox_dirs=_sandbox(tmp_path, "run"),
                exp_id="run",
                seed_plan=TrainingSeedPlan(SeedContext(run_seed=123)),
                profile=fx.profile,
                expected_custom_loss_snapshot=expected,
            )
    assert not marker.exists()
