"""Deployment seam contracts; not evidence of an installed private service."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from execute_tools.observables import (
    DeclaredDynamicObservable,
    DynamicObservable,
    ObservableError,
    RunObservables,
    RunObservationSession,
)
from execute_tools.scope_artifact import validation_rows_argv
from execute_tools.task_data_path import bind_task_data_path
from execute_tools.validation_execution import (
    ValidationDeployment,
    ValidationExecutionResult,
    bind_validation_deployment,
    bind_validation_executor,
    bound_validation_rows,
    child_validation_executor_binding,
    execute_validation_epoch,
    validation_executor_argv,
)
from ml_models.models_format_sandbox import LossConfig
from tests.helpers import validation_execution_client


class PrivateObservable(DynamicObservable):
    def reset(self):
        raise AssertionError("private reset executed in research")

    def update(self, output, target):
        raise AssertionError("private update executed in research")

    def value(self):
        raise AssertionError("private value executed in research")


def observation():
    return RunObservationSession(
        RunObservables(dynamic=(DeclaredDynamicObservable("error", PrivateObservable()),))
    )


def test_external_observables_validate_before_history_or_latch_changes():
    session = observation()
    session.accept_external_epoch({"error": 2.0}, ())
    for values, failed in (
        ({}, ()),
        ({"other": 1.0}, ()),
        ({"error": float("nan")}, ()),
        ({"error": 1.0}, ("error",)),
        ({}, ("error", "error")),
    ):
        with pytest.raises(ObservableError):
            session.accept_external_epoch(values, failed)
        assert session.dynamic_series() == {"error": [2.0]}
    session.accept_external_epoch({}, ("error",))
    with pytest.raises(ObservableError):
        session.accept_external_epoch({"error": 3.0}, ())
    session.accept_external_epoch({}, ("error",))
    assert session.dynamic_series() == {"error": [2.0]}


def test_parent_row_declaration_avoids_private_dataset_and_unwinds():
    scope = object()
    seen = []

    def forbidden(*args):
        raise AssertionError("parent materialized private validation data")

    def declared(actual):
        seen.append(actual)
        return 7

    executor = SimpleNamespace(declared_rows=declared)
    with (
        bind_task_data_path(SimpleNamespace(validation_dataset=forbidden)),
        bind_validation_executor(executor),
    ):
        assert validation_rows_argv(
            SimpleNamespace(training=object(), evaluation=scope),
            data_dir="unused",
            regime_a_eval_declared=False,
        ) == ["--validation_requested_rows", "7"]
        with (
            pytest.raises(RuntimeError),
            bind_validation_executor(
                SimpleNamespace(declared_rows=lambda _: (_ for _ in ()).throw(RuntimeError()))
            ),
        ):
            bound_validation_rows(scope)
        assert bound_validation_rows(scope) == 7
    assert seen == [scope, scope]
    assert bound_validation_rows(scope) is None


@pytest.mark.parametrize("rows", [True, 0, -1, 2.5, "3"])
def test_bad_row_declarations_refuse(rows):
    with bind_validation_executor(SimpleNamespace(declared_rows=lambda _: rows)):
        with pytest.raises(ValueError, match="positive integer"):
            bound_validation_rows(object())


def test_explicit_binding_reaches_fresh_child_and_nested_local_binding_refuses():
    declaration = ValidationDeployment(
        factory=f"{validation_execution_client.__name__}:create", settings={"rows": 19}
    )
    with bind_validation_deployment(declaration):
        declaration.settings["rows"] = 99
        assert bound_validation_rows(object()) == 19
        argv = validation_executor_argv()
        assert argv[0] == "--validation_executor_json"
        with bind_validation_executor(SimpleNamespace()):
            with pytest.raises(ValueError, match="no subprocess"):
                validation_executor_argv()
        assert validation_executor_argv() == argv
        with pytest.raises(ValueError, match="omitted"), child_validation_executor_binding(None):
            pass
    assert validation_executor_argv() == []
    child = subprocess.run(
        [sys.executable, "-B", "-m", validation_execution_client.__name__, argv[1]],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "19"


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"factory":"os:system","settings":{},"unexpected":true}',
        '{"factory":"missing_client_module:create","settings":{}}',
        '{"factory":"tests.helpers.validation_execution_client:create","settings":{"rows":0}}',
    ],
)
def test_invalid_child_binding_never_becomes_unbound(payload):
    with (
        pytest.raises((ValueError, ModuleNotFoundError)),
        child_validation_executor_binding(payload),
    ):
        raise AssertionError("broken supplied binding accepted")
    assert validation_executor_argv() == []


@pytest.mark.parametrize("failure", ["exception", "raw_dict", "wrong_rows", "success"])
def test_bound_dispatch_keeps_callbacks_and_never_falls_back(failure):
    session = observation()
    events = []
    verifier = object()

    def local(**kwargs):
        raise AssertionError("bound execution fell back to local data")

    def remote(request, callbacks):
        assert request.expected_rows == 7
        assert callbacks.verifier is verifier
        callbacks.check_allocation()
        callbacks.on_verified()
        events.append("result")
        if failure == "exception":
            raise RuntimeError("executor failed")
        if failure == "raw_dict":
            return {"r3": 1.25, "rows": 7}
        return ValidationExecutionResult(
            r3=1.25,
            rows=6 if failure == "wrong_rows" else 7,
            observables={"error": 2.0},
        )

    kwargs = dict(
        model=torch.nn.Identity(),
        criterion=torch.nn.SmoothL1Loss(),
        model_cfg=SimpleNamespace(model_type="synthetic"),
        model_io=None,
        loss_cfg=LossConfig(loss_type="smooth_l1"),
        task_eval_scope=object(),
        device=torch.device("cpu"),
        batch_size=2,
        observables=session,
        verifier=verifier,
        on_verified=lambda: events.append("verified"),
        check_allocation=lambda: events.append("allocation"),
    )
    with bind_validation_executor(SimpleNamespace(observe=remote)):
        if failure == "success":
            value, rows, seconds = execute_validation_epoch(local, expected_rows=7, **kwargs)
            assert (value, rows) == (1.25, 7)
            assert seconds >= 0
            assert session.dynamic_series() == {"error": [2.0]}
        else:
            with pytest.raises((RuntimeError, TypeError, ValueError)):
                execute_validation_epoch(local, expected_rows=7, **kwargs)
            assert session.dynamic_series() == {}
    assert events == ["allocation", "verified", "result"]
