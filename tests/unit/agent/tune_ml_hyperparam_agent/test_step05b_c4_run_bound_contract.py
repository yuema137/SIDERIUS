"""Step 05b C4 — ONE run-bound Model-I/O declaration, explicitly transported.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
C4, §20 (configuration-architecture preservation), ledger §18.3 D-05b-1.

C4 makes the live resource gate the third production consumer of the probe
authority. The value it consumes must be the declaration **this run trains
against** — not a declaration a resource consumer resolved for itself, which
would agree by coincidence until the day it did not.

Source ruled out the design's first-choice transport. Production launches the
tuner node as a SUBPROCESS (``scripts/run_comparison.py``) and builds its
``HyperparamTuningInput`` from argv alone, leaving ``task_description`` at its
``""`` default — so no parent process holds a resolved contract that reaches
the tuner, and an optional schema field would be ``None`` on the production
chain. What the tuner process DOES already have is the exact expression that
feeds every training and inference child. C4 extracts that expression into one
acquisition point and threads its value.

The failure classes guarded here:

1. **two acquisition points.** If the pre-flight and the training child
   computed the contract independently, "they agree" would be a property of
   the filesystem, not of the code.
2. **a task with no declaration breaks.** The legacy prose-only form is a
   supported task shape; it must yield ``None`` and today's behaviour.
3. **the configuration architecture widens.** No new persisted field, no new
   required CLI argument, no migration for an existing config.

The tuner-to-pre-flight hop is proven by EXECUTION at Checkpoint C, through
the real production control flow. It is deliberately not claimed here.
"""

from __future__ import annotations

import json

import yaml

from agent.schemas.model_io_contract import ModelIOContract
from tests.helpers.step04a_fixtures import tidmad_model_io
from workflows.task_config import _clear_cache_for_tests, run_bound_model_io_contract

SHIPPED_CONFIG = "configs/task_config.yaml"


def _task_config_without_model_io(tmp_path):
    """The legacy prose-only form: a real task shape, not a broken config."""
    raw = yaml.safe_load(open(SHIPPED_CONFIG, encoding="utf-8"))
    fc = raw["forward_contract"]
    fc.pop("model_io", None)
    fc.pop("preset", None)
    fc.update(
        {
            "input_shape": "[B, T] int64",
            "output_shape": "[B, 256, T] float32",
            "num_classes": 256,
        }
    )
    path = tmp_path / "legacy_task_config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return str(path)


class TestOneAcquisitionPoint:
    def test_the_training_child_receives_exactly_the_bound_contract(self, tmp_path, monkeypatch):
        """THE structural claim behind C4's transport choice.

        The sandbox executor materializes the contract to ``--model_io_json``
        for every training and inference child. If it computed its own, the
        pre-flight could price a candidate against one declaration while the
        run trained against another and nothing would notice. Moving the
        SINGLE acquisition point must move what the child is handed.
        """
        from core.sandbox_executor import TidmadSandbox

        contrast = tidmad_model_io(num_classes=16)
        monkeypatch.setattr("workflows.task_config.run_bound_model_io_contract", lambda: contrast)

        sandbox = TidmadSandbox.__new__(TidmadSandbox)
        sandbox.dirs = {"configs": str(tmp_path)}
        written = sandbox._write_model_io_config("s05b_c4")

        assert written is not None
        loaded = ModelIOContract(**json.loads(open(written, encoding="utf-8").read()))
        assert loaded == contrast, (
            "the training child is handed a contract the run did not bind — "
            "the pre-flight and the run it prices could then disagree"
        )

    def test_the_bound_contract_is_the_shipped_declaration(self):
        """Under TIDMAD the bound value IS the task's declaration, so C2's
        equivalence proof (shipped contract reproduces the legacy tensor)
        applies to what production actually passes."""
        _clear_cache_for_tests()
        contract = run_bound_model_io_contract()
        assert contract is not None
        assert contract.output.render_shape() == "[B, 256, T]"
        assert contract.class_cardinality == 256


class TestALegacyTaskYieldsNone:
    def test_a_prose_only_task_config_binds_no_contract(self, tmp_path):
        """Regime A is a supported task shape. ``None`` reaches the resource
        path and selects the legacy no-contract branch — it is not an error,
        and it must not become one."""
        _clear_cache_for_tests()
        try:
            assert run_bound_model_io_contract(_task_config_without_model_io(tmp_path)) is None
        finally:
            _clear_cache_for_tests()


class TestTheConfigurationArchitectureIsUnchanged:
    def test_no_new_persisted_or_user_authored_field(self):
        """§20: ambient -> injected does NOT mean copying an authority into
        persisted configuration. The contract travels as a runtime value, so
        none of the four config schemas may have grown a copy of it."""
        from agent.schemas.hyperparam_tuning import HyperparamTuningInput, TrialConfig
        from ml_models.models_format_sandbox import LossConfig

        for schema in (HyperparamTuningInput, TrialConfig, LossConfig):
            offenders = [f for f in schema.model_fields if "model_io" in f]
            assert not offenders, (
                f"{schema.__name__} carries a persisted Model-I/O copy {offenders}; "
                "the contract is transport, not configuration (§20)"
            )

    def test_the_tuner_cli_gained_no_argument(self):
        """A new required CLI argument is a MATERIAL STOP, and an optional one
        would still be a user-facing configuration surface for a value the run
        already owns."""
        import inspect
        from importlib import import_module

        tuner = import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
        assert "model_io" not in inspect.getsource(tuner.main)
