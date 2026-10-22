"""Standalone physical mains must reject unsafe identity before loading task inputs."""

from argparse import Namespace
from unittest.mock import Mock

import pytest

from execute_tools import inference_single, train_engine_sandbox


@pytest.mark.parametrize(
    "module,parser_factory",
    [(inference_single, "get_parser"), (train_engine_sandbox, "build_training_parser")],
)
@pytest.mark.parametrize("run_name", ["../escape", "/absolute", r"C:\escape", "bad\nname"])
def test_main_refuses_name_before_contract_loading(module, parser_factory, run_name, monkeypatch):
    """Bypassing the guard reaches the contract-loading tripwire, never a runtime job."""
    args = Namespace(
        run_name=run_name, dataset_profile_json="dataset.json", model_io_json="io.json"
    )
    parser = Mock()
    parser.parse_args.return_value = args
    monkeypatch.setattr(module, parser_factory, lambda: parser)
    first_effect = Mock(side_effect=AssertionError("task loading reached"))
    monkeypatch.setattr(module, "load_dataset_profile", first_effect)
    monkeypatch.setattr(module, "load_model_io_contract", first_effect)
    with pytest.raises(ValueError, match=r"run_name.*filesystem component"):
        module.main()
    first_effect.assert_not_called()
