"""Step 12 / PR-12d — D4c: DAVIS's exact MAE / L1 objective, end to end.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §M `D4c`, ruling **A3**.

§22.9a freezes DAVIS's training objective as exact mean absolute error. Five
things stood between that declaration and a run that actually optimises it —
the four blockers A3 names plus **F-12d-2**, which the pre-implementation
audit found. Each is asserted here as a property, not as a checklist item:

1. **no MAE plugin existed** → the pack ships one;
2. **no pack-declared loss channel** → `loss_plugins:` composes into a
   run-scoped binding;
3. **the closed comparability whitelist** → a plugin may DECLARE its
   normalization, and an undeclared one is still refused;
4. **loss-dir discovery never saw a pack** → the binding is UNIONED into the
   child transport, so a spawn cannot destroy it;
5. **F-12d-2** — a declared `float` target dtype was silently ignored on the
   Tier-2 filesystem path the training child actually uses, so exact MAE would
   have computed against `int64`-truncated targets.

What A3 forbids is asserted too, because closing a gap by widening a frozen
constraint would satisfy every item above and still be wrong.
"""

from __future__ import annotations

import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PACK_PLUGINS = REPO_ROOT / "examples" / "davis_future_prediction" / "plugins"
OBJECTIVE = PACK_PLUGINS / "davis_exact_l1_loss.py"


# ======================================================================
# FALSIFIER 2 — what A3 forbids
# ======================================================================


class TestFalsifier2TheForbiddenRoutes:
    """*"assert `smooth_l1(beta=0.1)` is not accepted as DAVIS's frozen R1."*"""

    def test_the_loss_type_literal_is_still_CLOSED_with_no_l1_member(self):
        """Growing it is the central task catalog this whole step avoids."""
        from ml_models.models_format_sandbox import LossConfig

        allowed = LossConfig.model_fields["loss_type"].annotation
        assert set(getattr(allowed, "__args__", ())) == {
            "focal",
            "focal_cw",
            "ce",
            "smooth_l1",
            "custom",
        }

    def test_smooth_l1_still_cannot_degenerate_to_exact_l1(self):
        """`beta` is bounded `ge=0.1`, so the L1 limit stays unreachable."""
        import pydantic

        from ml_models.models_format_sandbox import LossConfig

        with pytest.raises(pydantic.ValidationError):
            LossConfig(loss_type="smooth_l1", beta=0.0)

    def test_smooth_l1_at_its_minimum_beta_is_NUMERICALLY_a_different_objective(self):
        """The compromise the runner used to make, measured.

        `smooth_l1(0.1)` was chosen because 0.1 is the schema's minimum — the
        most L1-like admissible setting — and it is still quadratic below beta,
        which is where a future-frame model spends its time near convergence.
        Errors 0, 0.05, 1.0: exact L1 = 0.35, smooth = 0.3208…, an ~8% gap the
        report would have labelled MAE.
        """
        import torch

        predicted = torch.tensor([[0.0, 0.05, 1.0]])
        target = torch.tensor([[0.0, 0.0, 0.0]])
        exact = torch.nn.L1Loss(reduction="mean")(predicted, target).item()
        smooth = torch.nn.SmoothL1Loss(beta=0.1)(predicted, target).item()
        assert exact == pytest.approx(0.35, abs=1e-6)
        assert smooth == pytest.approx(0.3208333, abs=1e-6)
        assert exact != pytest.approx(smooth, abs=1e-4)

    def test_the_davis_runner_declares_the_exact_objective(self):
        source = (REPO_ROOT / "scripts" / "run_davis_gate2.py").read_text(encoding="utf-8")
        assert 'LossConfig(loss_type="smooth_l1", beta=0.1)' not in source
        assert 'LossConfig(loss_type="custom", loss_name="davis_exact_l1")' in source


# ======================================================================
# The objective itself
# ======================================================================


class TestTheObjectiveIsExactL1:
    def _loss(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("_d4c_objective", OBJECTIVE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_it_computes_the_hand_calculated_mean_absolute_error(self):
        """Errors 0, 0.05, 1.0 -> mean(|e|) = 1.05/3 = 0.35."""
        import torch

        module = self._loss()
        criterion = module.PLUGIN_LOSS_CLASS(module.PLUGIN_LOSS_CONFIG_CLASS())
        value = criterion(torch.tensor([[0.0, 0.05, 1.0]]), torch.tensor([[0.0, 0.0, 0.0]]))
        assert value.item() == pytest.approx(0.35, abs=1e-6)

    def test_it_declares_float_targets_and_mean_reduction(self):
        module = self._loss()
        assert module.PLUGIN_LOSS_TYPE == "davis_exact_l1"
        assert module.PLUGIN_LOSS_TARGET_DTYPE == "float"
        assert module.PLUGIN_LOSS_REDUCTION == "mean"

    def test_its_config_admits_NO_hyperparameter(self):
        """A `beta` here would be the smooth-L1 shortcut through the back door."""
        import pydantic

        module = self._loss()
        with pytest.raises(pydantic.ValidationError):
            module.PLUGIN_LOSS_CONFIG_CLASS(beta=0.1)

    def test_a_shape_mismatch_is_LOUD_rather_than_broadcast(self):
        import torch

        module = self._loss()
        criterion = module.PLUGIN_LOSS_CLASS(module.PLUGIN_LOSS_CONFIG_CLASS())
        with pytest.raises(ValueError, match="matching shapes"):
            criterion(torch.zeros(1, 3), torch.zeros(1, 4))

    def test_the_file_carries_NO_leading_underscore(self):
        """Reachability, and it is not cosmetic.

        A loss is resolved BY NAME through a directory SCAN, and that scan
        skips `_`-prefixed members. An underscore here would have left the
        objective unreachable while every declaration still looked correct —
        which is exactly how it failed on first execution.
        """
        assert OBJECTIVE.exists()
        assert not OBJECTIVE.name.startswith("_")


# ======================================================================
# F-12d-2 — the declared target dtype survives the Tier-2 path
# ======================================================================


class TestDeclaredTargetDtypeIsHonoured:
    """The audit's reproduction, inverted into the property it demands.

    `LOSS_TARGET_DTYPE_REGISTRY` was populated ONLY by
    `register_loss_in_memory`, which the training subprocess never calls — it
    resolves a custom loss through the Tier-2 filesystem path. So
    `get_loss_target_dtype` fell through to its `"long"` default and DAVIS's
    float targets were cast to `int64`. Same class as issue #234: a metadata
    declaration silently ignored becomes wrong science.
    """

    def test_the_tier2_filesystem_path_records_the_declared_dtype(self, monkeypatch):
        import torch

        from agent_generated._loss_loader import LOSS_TARGET_DTYPE_REGISTRY
        from ml_models.loss_models_sandbox import _load_custom_loss, get_target_torch_dtype
        from ml_models.models_format_sandbox import LossConfig

        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(PACK_PLUGINS))
        monkeypatch.delitem(LOSS_TARGET_DTYPE_REGISTRY, "davis_exact_l1", raising=False)

        _load_custom_loss("davis_exact_l1")  # Tier 2 — the path the child uses
        assert LOSS_TARGET_DTYPE_REGISTRY["davis_exact_l1"] == "float"
        assert (
            get_target_torch_dtype(LossConfig(loss_type="custom", loss_name="davis_exact_l1"))
            is torch.float32
        )

    def test_a_plugin_declaring_nothing_still_defaults_to_long(self):
        """The pre-I13 forward contract is untouched."""
        from agent_generated._loss_loader import get_loss_target_dtype

        assert get_loss_target_dtype("a_loss_that_was_never_loaded") == "long"


# ======================================================================
# The pack-declared loss channel, and its transport
# ======================================================================


class TestTheLossChannelReachesTheChild:
    def test_a_declared_root_binds_and_reaches_the_transport(self):
        from core.subprocess_env import LOSS_DIRS_ENV_VAR, subprocess_env
        from ml_models.plugin_binding import bind_run_loss_plugin_roots

        assert LOSS_DIRS_ENV_VAR not in subprocess_env(), "legacy transport must be unchanged"
        with bind_run_loss_plugin_roots((str(PACK_PLUGINS),)):
            assert subprocess_env()[LOSS_DIRS_ENV_VAR] == str(PACK_PLUGINS)
        assert LOSS_DIRS_ENV_VAR not in subprocess_env(), "the binding must unwind"

    def test_a_child_spawn_cannot_DESTROY_the_declared_root(self):
        """UNION, not assign — the correction seam P made for model plugins.

        The one variable whose entire purpose is to say which objective runs
        must not be the one a child spawn overwrites.
        """
        from core.subprocess_env import LOSS_DIRS_ENV_VAR, subprocess_env
        from ml_models.plugin_binding import bind_run_loss_plugin_roots

        with bind_run_loss_plugin_roots((str(PACK_PLUGINS),)):
            merged = subprocess_env(loss_dir="/some/runtime/dir")[LOSS_DIRS_ENV_VAR]
        parts = merged.split(os.pathsep)
        assert "/some/runtime/dir" in parts
        assert str(PACK_PLUGINS) in parts

    def test_the_loss_channel_is_SEPARATE_from_the_model_channel(self):
        """One directory, two channels — and the split is load-bearing.

        `core/subprocess_env.py` records why: sharing one variable masks the
        globally registered loss library whenever only a model directory is
        set. A pack keeping both in one folder must not collapse them.
        """
        from core.subprocess_env import LOSS_DIRS_ENV_VAR, PLUGIN_DIRS_ENV_VAR, subprocess_env
        from ml_models.plugin_binding import bind_run_loss_plugin_roots

        assert LOSS_DIRS_ENV_VAR != PLUGIN_DIRS_ENV_VAR
        with bind_run_loss_plugin_roots((str(PACK_PLUGINS),)):
            env = subprocess_env()
        assert PLUGIN_DIRS_ENV_VAR not in env

    def test_an_undeclared_manifest_binds_nothing(self, tmp_path):
        from workflows.task_composition import _compose_loss_plugins

        assert _compose_loss_plugins({}, str(tmp_path)) == ((), None)
        assert _compose_loss_plugins({"loss_plugins": {"none": True}}, str(tmp_path)) == ((), None)

    def test_a_declared_root_that_does_not_exist_is_REFUSED(self, tmp_path):
        """Silence here would mean falling back to the global library.

        The run would train on whatever loss of that name happened to be
        promoted, rather than on the objective the pack declared.
        """
        from workflows.task_composition import TaskCompositionError, _compose_loss_plugins

        with pytest.raises(TaskCompositionError, match="does not resolve to a directory"):
            _compose_loss_plugins({"loss_plugins": {"dir": "no_such_dir"}}, str(tmp_path))

    def test_declaring_both_none_and_a_dir_is_REFUSED(self, tmp_path):
        from workflows.task_composition import TaskCompositionError, _compose_loss_plugins

        with pytest.raises(TaskCompositionError, match="either"):
            _compose_loss_plugins({"loss_plugins": {"none": True, "dir": "x"}}, str(tmp_path))


# ======================================================================
# Comparability — the repair, and the half that must not move
# ======================================================================


class TestComparabilityIsDeclarableNotAssumed:
    def test_a_plugin_declaring_mean_reduction_is_ESTABLISHED(self, monkeypatch):
        from agent_generated._loss_loader import LOSS_REDUCTION_REGISTRY
        from execute_tools.training_history import stamp_comparability
        from ml_models.loss_models_sandbox import _load_custom_loss
        from ml_models.models_format_sandbox import LossConfig

        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(PACK_PLUGINS))
        monkeypatch.delitem(LOSS_REDUCTION_REGISTRY, "davis_exact_l1", raising=False)
        _load_custom_loss("davis_exact_l1")

        assert stamp_comparability(LossConfig(loss_type="custom", loss_name="davis_exact_l1")) == (
            "established",
            None,
        )

    def test_a_plugin_declaring_NOTHING_is_unchanged(self):
        """The repair is a declaration channel, never a blanket relaxation."""
        from execute_tools.training_history import stamp_comparability
        from ml_models.models_format_sandbox import LossConfig

        assert stamp_comparability(
            LossConfig(loss_type="custom", loss_name="never_declared_anything")
        ) == ("not_established", "custom_objective_undeclared")

    def test_a_SUM_reduction_is_refused_for_a_custom_loss_too(self, monkeypatch):
        """Sum-reduced values scale with batch count, so epochs are not comparable.

        The built-in kinds are held to this rule; a declaring custom plugin
        must be held to the same one or the declaration would buy an exemption
        rather than an assurance.
        """
        from agent_generated._loss_loader import LOSS_REDUCTION_REGISTRY
        from execute_tools.training_history import (
            COMPARABILITY_REASON_SUM,
            stamp_comparability,
        )
        from ml_models.models_format_sandbox import LossConfig

        monkeypatch.setitem(LOSS_REDUCTION_REGISTRY, "a_sum_reduced_loss", "sum")
        assert stamp_comparability(
            LossConfig(loss_type="custom", loss_name="a_sum_reduced_loss")
        ) == ("not_established", COMPARABILITY_REASON_SUM)

    def test_an_invalid_declared_reduction_is_treated_as_UNDECLARED(self, tmp_path, monkeypatch):
        """A typo must not silently buy comparability."""
        plugin = tmp_path / "typo_reduction_loss.py"
        plugin.write_text(
            "import torch.nn as nn\n"
            "from pydantic import BaseModel\n"
            'PLUGIN_LOSS_TYPE = "typo_reduction"\n'
            'PLUGIN_LOSS_REDUCTION = "meen"\n'
            "class C(BaseModel):\n    pass\n"
            "class L(nn.Module):\n"
            "    def __init__(self, cfg):\n        super().__init__()\n"
            "    def forward(self, o, t):\n        return (o - t).abs().mean()\n"
            "PLUGIN_LOSS_CONFIG_CLASS = C\nPLUGIN_LOSS_CLASS = L\n",
            encoding="utf-8",
        )
        from agent_generated._loss_loader import LOSS_REDUCTION_REGISTRY, load_loss_plugin
        from execute_tools.training_history import stamp_comparability
        from ml_models.models_format_sandbox import LossConfig

        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(tmp_path))
        monkeypatch.delitem(LOSS_REDUCTION_REGISTRY, "typo_reduction", raising=False)
        assert load_loss_plugin("typo_reduction") is not None
        assert "typo_reduction" not in LOSS_REDUCTION_REGISTRY
        assert stamp_comparability(LossConfig(loss_type="custom", loss_name="typo_reduction")) == (
            "not_established",
            "custom_objective_undeclared",
        )
