"""
Tests for ml_models/loss_models_sandbox.py

Verifies that all loss functions compute correctly on synthetic tensors
and that get_criterion instantiates the right class for each loss_type.
"""

import math
import shutil
import sys
from pathlib import Path

import pytest
import torch
from pydantic import ValidationError

from ml_models.loss_models_sandbox import FocalLoss1D, FocalLoss1DCW, get_criterion
from ml_models.models_format_sandbox import ExperimentConfig, LossConfig

# ==========================================
# Shared fixtures
# ==========================================

BATCH = 2
NUM_CLASSES = 256
SEQ_LEN = 1000


@pytest.fixture
def classification_inputs():
    """Synthetic logits: [Batch, NumClasses, SeqLen]"""
    torch.manual_seed(0)
    return torch.randn(BATCH, NUM_CLASSES, SEQ_LEN)


@pytest.fixture
def classification_targets():
    """Synthetic discrete targets: [Batch, SeqLen], values in [0, 255]"""
    torch.manual_seed(0)
    return torch.randint(0, NUM_CLASSES, (BATCH, SEQ_LEN))


@pytest.fixture
def regression_inputs():
    """Synthetic regression output: [Batch, SeqLen]"""
    torch.manual_seed(0)
    return torch.randn(BATCH, SEQ_LEN)


@pytest.fixture
def regression_targets():
    """Synthetic regression targets: [Batch, SeqLen]"""
    torch.manual_seed(0)
    return torch.randn(BATCH, SEQ_LEN)


@pytest.fixture
def class_weights():
    """Synthetic per-class weights: [NumClasses]"""
    return torch.ones(NUM_CLASSES) / NUM_CLASSES


# ==========================================
# FocalLoss1D
# ==========================================


class TestFocalLoss1D:
    def test_output_is_scalar(self, classification_inputs, classification_targets):
        cfg = LossConfig(loss_type="focal")
        loss_fn = FocalLoss1D(cfg)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.shape == torch.Size([])

    def test_output_is_non_negative(self, classification_inputs, classification_targets):
        cfg = LossConfig(loss_type="focal")
        loss_fn = FocalLoss1D(cfg)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_perfect_prediction_lower_than_random(self, classification_targets):
        """Loss on near-perfect logits should be lower than on random logits."""
        cfg = LossConfig(loss_type="focal")
        loss_fn = FocalLoss1D(cfg)

        # Near-perfect: high logit on the correct class
        perfect_logits = torch.full((BATCH, NUM_CLASSES, SEQ_LEN), -10.0)
        for b in range(BATCH):
            for t in range(SEQ_LEN):
                perfect_logits[b, classification_targets[b, t], t] = 10.0

        random_logits = torch.randn(BATCH, NUM_CLASSES, SEQ_LEN)

        loss_perfect = loss_fn(perfect_logits, classification_targets).item()
        loss_random = loss_fn(random_logits, classification_targets).item()
        assert loss_perfect < loss_random

    def test_reduction_sum_larger_than_mean(self, classification_inputs, classification_targets):
        loss_mean = FocalLoss1D(LossConfig(loss_type="focal", reduction="mean"))
        loss_sum = FocalLoss1D(LossConfig(loss_type="focal", reduction="sum"))
        assert (
            loss_sum(classification_inputs, classification_targets).item()
            > loss_mean(classification_inputs, classification_targets).item()
        )


# ==========================================
# FocalLoss1DCW
# ==========================================


class TestFocalLoss1DNumericParity:
    """The frozen loss's missing numeric oracle.

    CLAUDE.md asserts `loss_models_sandbox.py:135-168` is line-for-line
    identical to TIDMAD's `network.py:FocalLoss1D`, and records that
    `alpha` was once wrong -- 0.25 where the paper uses 0.5 -- on wavenet.
    Nothing asserted the arithmetic. `TestFocalLoss1D` above checks only
    properties that hold for almost any loss: a scalar shape (guaranteed by
    `reduction="mean"`), non-negativity (mathematically guaranteed), and two
    coarse orderings. Set `alpha = 0.25` today and all four stay green.

    Line 161 masks the sum to the target class, so for target class c:

        loss = mean over (batch, length) of
                   -alpha * (1 - p_c) ** gamma * log(p_c)

    Every expectation below is HAND-COMPUTED from that closed form and
    hardcoded. Nothing is read back from the implementation, and no fixture
    is involved -- two classes, one sample, one timestep.
    """

    @staticmethod
    def _loss(alpha: float, gamma: float, logits: tuple[float, float], target: int) -> float:
        cfg = LossConfig(loss_type="focal", alpha=alpha, gamma=gamma, reduction="mean")
        x = torch.tensor([[[logits[0]], [logits[1]]]], dtype=torch.float32)  # [1, 2, 1]
        t = torch.tensor([[target]], dtype=torch.long)  # [1, 1]
        return float(FocalLoss1D(cfg)(x, t))

    def test_the_paper_alpha_and_gamma_give_the_hand_computed_value(self):
        """alpha=0.5, gamma=2, p=0.5  ->  -0.5 * 0.25 * ln(0.5)."""
        assert self._loss(0.5, 2.0, (0.0, 0.0), 0) == pytest.approx(0.0866433978, rel=1e-6)

    def test_both_alpha_DEFAULTS_give_the_paper_value(self):
        """The drift that actually happened was a DEFAULT, not an argument.

        Every other case here passes `alpha` explicitly and therefore cannot
        see a default change — verified by mutation: flipping
        `loss_models_sandbox.py:143` from 0.5 to 0.25 left the four legacy
        property tests AND every explicit-alpha case below green.

        There are TWO defaults on this path and they are easy to confuse:
        `LossConfig.alpha` is declared `default=0.5`
        (`models_format_sandbox.py:640`), which is what an unset config
        actually gets; the class-level `else 0.5`
        (`loss_models_sandbox.py:143`) is reached only when alpha is
        explicitly `None`. A config that omits alpha never touches the
        second one, so both are pinned here.
        """
        x = torch.tensor([[[0.0], [0.0]]], dtype=torch.float32)
        t = torch.tensor([[0]], dtype=torch.long)

        schema_default = LossConfig(loss_type="focal", gamma=2.0, reduction="mean")
        assert schema_default.alpha == 0.5, "the schema default moved off the paper value"
        assert float(FocalLoss1D(schema_default)(x, t)) == pytest.approx(0.0866433978, rel=1e-6)

        explicit_none = LossConfig(loss_type="focal", alpha=None, gamma=2.0, reduction="mean")
        assert float(FocalLoss1D(explicit_none)(x, t)) == pytest.approx(0.0866433978, rel=1e-6)

    def test_the_historical_alpha_drift_is_visible_here(self):
        """The 0.5 -> 0.25 regression, as an exact factor of two. This is the
        case the four property tests above cannot see."""
        paper = self._loss(0.5, 2.0, (0.0, 0.0), 0)
        drifted = self._loss(0.25, 2.0, (0.0, 0.0), 0)
        assert drifted == pytest.approx(0.0433216989, rel=1e-6)
        assert drifted == pytest.approx(paper / 2.0, rel=1e-6)

    def test_gamma_zero_collapses_to_weighted_cross_entropy(self):
        """gamma=0 removes the focal term: -0.5 * ln(0.5). Pins the exponent
        -- the alpha rows alone cannot distinguish gamma=2 from gamma=1."""
        assert self._loss(0.5, 0.0, (0.0, 0.0), 0) == pytest.approx(0.3465735912, rel=1e-6)

    def test_an_asymmetric_logit_pins_the_softmax_and_the_target_mask(self):
        """logits (ln 3, 0) -> p_0 = 0.75, so -0.5 * 0.0625 * ln(0.75).
        A uniform-logit case cannot tell the target class from the other one;
        this one can."""
        assert self._loss(0.5, 2.0, (math.log(3.0), 0.0), 0) == pytest.approx(
            0.0089900587, rel=1e-6
        )


class TestFocalLoss1DCW:
    def test_output_is_scalar(self, classification_inputs, classification_targets, class_weights):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.shape == torch.Size([])

    def test_output_is_non_negative(
        self, classification_inputs, classification_targets, class_weights
    ):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_none_class_weights_falls_back_gracefully(
        self, classification_inputs, classification_targets
    ):
        cfg = LossConfig(loss_type="focal_cw")
        loss_fn = FocalLoss1DCW(cfg, class_weights=None)
        loss = loss_fn(classification_inputs, classification_targets)
        assert loss.shape == torch.Size([])


# ==========================================
# get_criterion factory
# ==========================================


class TestGetCriterion:
    def test_focal_returns_focal_loss(self):
        cfg = LossConfig(loss_type="focal")
        criterion = get_criterion(cfg)
        assert isinstance(criterion, FocalLoss1D)

    def test_focal_cw_returns_focal_cw_loss(self, class_weights):
        cfg = LossConfig(loss_type="focal_cw")
        criterion = get_criterion(cfg, class_weights)
        assert isinstance(criterion, FocalLoss1DCW)

    def test_ce_returns_cross_entropy(self):
        cfg = LossConfig(loss_type="ce")
        criterion = get_criterion(cfg)
        assert isinstance(criterion, torch.nn.CrossEntropyLoss)

    def test_smooth_l1_returns_smooth_l1_loss(self):
        cfg = LossConfig(loss_type="smooth_l1")
        criterion = get_criterion(cfg)
        assert isinstance(criterion, torch.nn.SmoothL1Loss)

    def test_unknown_loss_type_raises(self):
        cfg = LossConfig(loss_type="focal")
        cfg.loss_type = "unknown"  # bypass Pydantic to simulate bad state
        with pytest.raises(ValueError, match="Unknown loss_type"):
            get_criterion(cfg)

    def test_ce_computes_on_synthetic_data(self, classification_inputs, classification_targets):
        cfg = LossConfig(loss_type="ce")
        criterion = get_criterion(cfg)
        loss = criterion(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_smooth_l1_computes_on_synthetic_data(self, regression_inputs, regression_targets):
        cfg = LossConfig(loss_type="smooth_l1")
        criterion = get_criterion(cfg)
        loss = criterion(regression_inputs, regression_targets)
        assert loss.item() >= 0.0


# ==========================================
# L2 — LossConfig.loss_type="custom" + loss_name + get_criterion routing
# ==========================================
#
# Verifies the custom-loss routing path added by L2. See
# ``docs/design/enable_loss_inventory.md`` § Commit L2.

# Stub template lives in agent_generated/_stub_loss_template.py (committed in L1a).
# Tests copy it (without the leading ``_``) into a tmp loss dir and point
# SIDERIUS_LOSS_DIRS at that dir.
_STUB_TEMPLATE = Path(__file__).resolve().parents[3] / "agent_generated" / "_stub_loss_template.py"


@pytest.fixture
def loss_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a fresh tmp loss directory containing the stub plugin (loadable
    as ``stub_ce``) and point ``SIDERIUS_LOSS_DIRS`` at it.

    Also clears any pre-existing ``siderius_loss_plugin_*`` entries from
    ``sys.modules`` so a previous test run's stub doesn't shadow this one.
    """
    d = tmp_path / "losses"
    d.mkdir()
    shutil.copy2(_STUB_TEMPLATE, d / "stub_ce.py")
    monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(d))
    for k in list(sys.modules):
        if k.startswith("siderius_loss_plugin_"):
            sys.modules.pop(k, None)
    return d


# ---------------------------------------------------------------------------
# Schema: loss_type="custom" requires loss_name; non-custom forbids it
# ---------------------------------------------------------------------------


class TestLossConfigCustomValidation:
    def test_custom_without_loss_name_raises(self):
        with pytest.raises(ValidationError, match="loss_name is required"):
            LossConfig(loss_type="custom")

    def test_custom_with_explicit_none_loss_name_raises(self):
        with pytest.raises(ValidationError, match="loss_name is required"):
            LossConfig(loss_type="custom", loss_name=None)

    def test_custom_with_empty_loss_name_raises(self):
        with pytest.raises(ValidationError, match="loss_name is required"):
            LossConfig(loss_type="custom", loss_name="")

    def test_custom_with_loss_name_succeeds(self):
        cfg = LossConfig(loss_type="custom", loss_name="snr_weighted_mse")
        assert cfg.loss_type == "custom"
        assert cfg.loss_name == "snr_weighted_mse"

    @pytest.mark.parametrize("lt", ["focal", "focal_cw", "ce", "smooth_l1"])
    def test_non_custom_with_loss_name_raises(self, lt: str):
        with pytest.raises(ValidationError, match="loss_name must be None"):
            LossConfig(loss_type=lt, loss_name="something")  # type: ignore[arg-type]

    @pytest.mark.parametrize("lt", ["focal", "focal_cw", "ce", "smooth_l1"])
    def test_non_custom_without_loss_name_succeeds(self, lt: str):
        cfg = LossConfig(loss_type=lt)  # type: ignore[arg-type]
        assert cfg.loss_name is None


# ---------------------------------------------------------------------------
# Schema: enforce_parameter_consistency nullifies alpha/gamma/beta for custom
# ---------------------------------------------------------------------------


class TestEnforceParameterConsistencyCustom:
    def test_custom_nullifies_alpha_gamma_beta(self):
        cfg = LossConfig(
            loss_type="custom",
            loss_name="snr_weighted_mse",
            alpha=0.7,
            gamma=3.0,
            beta=2.0,
        )
        # The router-vs-plugin two-config design means LossConfig's
        # alpha/gamma/beta are dead weight for custom; the validator
        # nullifies them so the agent can't accidentally pass them through.
        assert cfg.alpha is None
        assert cfg.gamma is None
        assert cfg.beta is None


# ---------------------------------------------------------------------------
# Schema: custom loss defers compatibility to the plugin
# ---------------------------------------------------------------------------
#
# V21 PR A retargeted this class. It previously called
# ``LossConfig.check_compatibility``, which had zero production callers and
# was deleted. The BEHAVIOUR it described is real and still owned by the
# single live authority, ``ExperimentConfig.validate_architecture_loss_match``
# — so the test now exercises that instead. A test that only proved a dead
# method did not raise was guarding nothing.


class TestCustomLossDefersToPlugin:
    # Scope note (V21 PR A): the original test also parametrized
    # ``any_plugin_model``. That case cannot be expressed through
    # ``ExperimentConfig`` — ``network_config`` is a discriminated union over
    # the six built-in config classes, so an unregistered name fails union
    # validation before any compatibility rule runs.
    #
    # This is not a gap in the test. Agent-generated plugin models never reach
    # ``ExperimentConfig`` at all: ``SandboxExecutor._validate_configs``
    # (``core/sandbox_executor.py:1093-1101``) takes a separate branch for
    # ``model_type in PLUGIN_CONFIG_REGISTRY`` and validates only the plugin's
    # own config class plus ``TrainConfig``/``LossConfig``. The built-in
    # models below are therefore the complete set for which this authority
    # actually runs.
    @pytest.mark.parametrize("model_type", ["punet", "fcnet", "wavenet"])
    def test_custom_is_compatible_with_any_builtin_model(self, model_type: str):
        """``loss_type='custom'`` must be accepted for every built-in model —
        the plugin's own forward pass raises at training time if the shape
        contract is violated.

        Asserted through the production authority: if a future edit made the
        live gate reject ``custom``, this fails.
        """
        ExperimentConfig(
            exp_id="custom-compat",
            run_name="custom-compat",
            model_type=model_type,
            network_config={"model_type": model_type},
            train_config={"lr": 5e-4, "epochs": 1, "batch_size": 2},
            loss_config={"loss_type": "custom", "loss_name": "anything"},
        )


# ---------------------------------------------------------------------------
# get_criterion routing for loss_type="custom"
# ---------------------------------------------------------------------------


class TestGetCriterionCustom:
    def test_custom_loads_plugin(self, loss_dir: Path):
        """Happy path: with a valid plugin in SIDERIUS_LOSS_DIRS, get_criterion
        returns an instance of the plugin's PLUGIN_LOSS_CLASS."""
        cfg = LossConfig(loss_type="custom", loss_name="stub_ce")
        criterion = get_criterion(cfg)
        # The stub_ce plugin's PLUGIN_LOSS_CLASS is named StubCE.
        assert criterion.__class__.__name__ == "StubCE"

    def test_custom_plugin_forward_pass_runs(
        self, loss_dir: Path, classification_inputs, classification_targets
    ):
        """Sanity check: the loaded plugin actually runs its forward pass
        on classifier-shaped tensors and returns a scalar with grad. We
        explicitly enable ``requires_grad`` on the inputs to mimic the real
        training path (model outputs always have grad)."""
        cfg = LossConfig(loss_type="custom", loss_name="stub_ce")
        criterion = get_criterion(cfg)
        inputs = classification_inputs.detach().clone().requires_grad_(True)
        loss = criterion(inputs, classification_targets)
        assert loss.dim() == 0  # scalar
        assert loss.requires_grad
        assert loss.item() >= 0.0

    def test_missing_plugin_raises_value_error(self, loss_dir: Path):
        """When the loss_name doesn't match any plugin in LOSS_REGISTRY OR
        SIDERIUS_LOSS_DIRS, get_criterion raises ValueError with the
        documented remediation text. L6c — message references both surfaces."""
        cfg = LossConfig(loss_type="custom", loss_name="nonexistent_loss")
        with pytest.raises(
            ValueError,
            match=r"not found in LOSS_REGISTRY or agent_generated/losses/",
        ):
            get_criterion(cfg)

    def test_missing_plugin_error_mentions_implementor_and_env_var(self, loss_dir: Path):
        """Verify both remediation paths are in the error message — operator
        running into this manually needs to know about both implementor
        generation AND SIDERIUS_LOSS_DIRS configuration."""
        cfg = LossConfig(loss_type="custom", loss_name="nonexistent_loss")
        try:
            get_criterion(cfg)
        except ValueError as e:
            msg = str(e)
            assert "Run the implementor first" in msg
            assert "SIDERIUS_LOSS_DIRS" in msg
        else:
            pytest.fail("Expected ValueError")


# ---------------------------------------------------------------------------
# Regression guard: the 4 built-in loss types still work after the
# custom-branch addition at the top of the if/elif chain.
# ---------------------------------------------------------------------------


class TestBuiltinsStillWorkAfterCustomBranch:
    @pytest.mark.parametrize("lt", ["focal", "focal_cw", "ce"])
    def test_classifier_branches_still_route_correctly(
        self, lt: str, classification_inputs, classification_targets
    ):
        cfg = LossConfig(loss_type=lt)  # type: ignore[arg-type]
        criterion = get_criterion(cfg)
        loss = criterion(classification_inputs, classification_targets)
        assert loss.item() >= 0.0

    def test_smooth_l1_branch_still_routes_correctly(self, regression_inputs, regression_targets):
        cfg = LossConfig(loss_type="smooth_l1")
        criterion = get_criterion(cfg)
        loss = criterion(regression_inputs, regression_targets)
        assert loss.item() >= 0.0


# ---------------------------------------------------------------------------
# L6c — In-memory LOSS_REGISTRY + filesystem fallback + preload
# ---------------------------------------------------------------------------
#
# These tests verify the two-tier lookup added in L6c:
#   1. LOSS_REGISTRY (populated by workflow._register_plugin + preload_global_losses)
#   2. Filesystem fallback via _resolve_loss_dirs union mode
# plus register_loss_in_memory, preload_global_losses, and the idempotency
# warning when re-registering a different class under the same loss_type.


_L6C_PLUGIN_SRC_FOR_FOO = """
import torch
import torch.nn as nn
from pydantic import BaseModel


class _FooLossConfig(BaseModel):
    pass


class _FooLoss(nn.Module):
    def __init__(self, config: _FooLossConfig) -> None:
        super().__init__()
        self.config = config

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        return inputs.mean()


PLUGIN_LOSS_TYPE = "foo_loss_l6c"
PLUGIN_LOSS_CONFIG_CLASS = _FooLossConfig
PLUGIN_LOSS_CLASS = _FooLoss
"""

_L6C_PLUGIN_SRC_FOR_BAR = (
    _L6C_PLUGIN_SRC_FOR_FOO.replace("foo_loss_l6c", "bar_loss_l6c")
    .replace("_FooLoss", "_BarLoss")
    .replace("_FooLossConfig", "_BarLossConfig")
)


@pytest.fixture(autouse=True)
def _l6c_clear_loss_registry():
    """Autouse fixture (L6c) — clear LOSS_REGISTRY between tests so module-
    level state doesn't pollute downstream tests. Restores any pre-existing
    entries on teardown for safety, though in practice the registry should
    be empty at unit-test boot.

    I13 — also clears LOSS_TARGET_DTYPE_REGISTRY so dtype-routing tests
    don't leak custom-loss declarations between tests.
    """
    from agent_generated._loss_loader import LOSS_TARGET_DTYPE_REGISTRY
    from ml_models.loss_models_sandbox import LOSS_CONFIG_REGISTRY, LOSS_REGISTRY

    saved_loss = dict(LOSS_REGISTRY)
    saved_cfg = dict(LOSS_CONFIG_REGISTRY)
    saved_dtype = dict(LOSS_TARGET_DTYPE_REGISTRY)
    LOSS_REGISTRY.clear()
    LOSS_CONFIG_REGISTRY.clear()
    LOSS_TARGET_DTYPE_REGISTRY.clear()
    yield
    LOSS_REGISTRY.clear()
    LOSS_CONFIG_REGISTRY.clear()
    LOSS_TARGET_DTYPE_REGISTRY.clear()
    LOSS_REGISTRY.update(saved_loss)
    LOSS_CONFIG_REGISTRY.update(saved_cfg)
    LOSS_TARGET_DTYPE_REGISTRY.update(saved_dtype)


class TestL6cResolveLossDirsUnion:
    def test_union_mode_with_env_var(self, tmp_path, monkeypatch):
        """With SIDERIUS_LOSS_DIRS set, _resolve_loss_dirs returns env-var
        dirs FIRST followed by the global LOSSES_DIR as a union."""
        from agent_generated._loss_loader import LOSSES_DIR, _resolve_loss_dirs

        ws_dir = tmp_path / "ws_losses"
        ws_dir.mkdir()
        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(ws_dir))
        result = _resolve_loss_dirs()
        assert result == [str(ws_dir), LOSSES_DIR]

    def test_no_env_returns_only_global(self, monkeypatch):
        """With SIDERIUS_LOSS_DIRS unset, _resolve_loss_dirs returns just
        [LOSSES_DIR] — unchanged pre-L6c behavior for that branch."""
        from agent_generated._loss_loader import LOSSES_DIR, _resolve_loss_dirs

        monkeypatch.delenv("SIDERIUS_LOSS_DIRS", raising=False)
        result = _resolve_loss_dirs()
        assert result == [LOSSES_DIR]


class TestL6cRegisterLossInMemory:
    def test_register_populates_registry(self, tmp_path):
        """register_loss_in_memory loads a real plugin .py and inserts the
        loss_class + config_class into LOSS_REGISTRY / LOSS_CONFIG_REGISTRY."""
        from ml_models.loss_models_sandbox import (
            LOSS_CONFIG_REGISTRY,
            LOSS_REGISTRY,
            register_loss_in_memory,
        )

        plugin_path = tmp_path / "foo_loss_l6c.py"
        plugin_path.write_text(_L6C_PLUGIN_SRC_FOR_FOO)
        loss_type = register_loss_in_memory(str(plugin_path))
        assert loss_type == "foo_loss_l6c"
        assert "foo_loss_l6c" in LOSS_REGISTRY
        assert "foo_loss_l6c" in LOSS_CONFIG_REGISTRY

    def test_register_unloadable_returns_none(self, tmp_path):
        """A .py with missing PLUGIN_* attributes is rejected by the loader
        and register_loss_in_memory returns None without raising."""
        from ml_models.loss_models_sandbox import LOSS_REGISTRY, register_loss_in_memory

        plugin_path = tmp_path / "broken.py"
        plugin_path.write_text("# no PLUGIN_LOSS_TYPE here\n")
        result = register_loss_in_memory(str(plugin_path))
        assert result is None
        assert "broken" not in LOSS_REGISTRY

    def test_idempotency_warning_on_class_mismatch(self, tmp_path, capsys):
        """Re-registering the same loss_type with a different class
        identity (different __qualname__) emits a warning to stdout."""
        from ml_models.loss_models_sandbox import register_loss_in_memory

        # First registration
        plugin_a = tmp_path / "first.py"
        plugin_a.write_text(_L6C_PLUGIN_SRC_FOR_FOO)
        register_loss_in_memory(str(plugin_a))
        capsys.readouterr()  # drain

        # Second registration with same loss_type but a different file path
        # (different module → different class identity). Build a variant by
        # renaming the class inside the source.
        plugin_b = tmp_path / "second.py"
        plugin_b.write_text(_L6C_PLUGIN_SRC_FOR_FOO.replace("_FooLoss", "_FooLossV2"))
        register_loss_in_memory(str(plugin_b))
        captured = capsys.readouterr()
        assert "re-registering" in captured.out.lower()
        assert "foo_loss_l6c" in captured.out


class TestL6cLoadCustomLossUsesInMemoryFirst:
    def test_in_memory_hit_skips_filesystem(self):
        """When LOSS_REGISTRY contains the name, _load_custom_loss uses it
        and never touches the filesystem."""
        import torch
        import torch.nn as nn
        from pydantic import BaseModel

        from ml_models.loss_models_sandbox import (
            LOSS_CONFIG_REGISTRY,
            LOSS_REGISTRY,
            _load_custom_loss,
        )

        class _StubCfg(BaseModel):
            pass

        class _StubLoss(nn.Module):
            def __init__(self, cfg):
                super().__init__()
                self.cfg = cfg

            def forward(self, inputs, targets):
                return inputs.mean()

        LOSS_REGISTRY["stub_l6c"] = _StubLoss
        LOSS_CONFIG_REGISTRY["stub_l6c"] = _StubCfg
        loss = _load_custom_loss("stub_l6c")
        assert isinstance(loss, _StubLoss)
        # Forward smoke test
        inputs = torch.randn(2, 256, 4, requires_grad=True)
        targets = torch.zeros(2, 4, dtype=torch.long)
        result = loss(inputs, targets)
        assert result.dim() == 0

    def test_filesystem_fallback_when_not_in_registry(self, tmp_path, monkeypatch):
        """When LOSS_REGISTRY is empty, _load_custom_loss falls back to
        the filesystem scan via _resolve_loss_dirs union mode."""
        from ml_models.loss_models_sandbox import _load_custom_loss

        plugin_path = tmp_path / "bar_loss_l6c.py"
        plugin_path.write_text(_L6C_PLUGIN_SRC_FOR_BAR)
        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(tmp_path))
        loss = _load_custom_loss("bar_loss_l6c")
        assert loss is not None
        assert hasattr(loss, "forward")

    def test_missing_error_lists_registry_contents(self):
        """The post-L6c ValueError message lists currently-registered
        names so operators can spot typos at a glance."""
        from ml_models.loss_models_sandbox import LOSS_REGISTRY, _load_custom_loss

        # Inject one known name so the error message has something to show
        LOSS_REGISTRY["known_loss"] = object  # type: ignore[assignment]
        with pytest.raises(ValueError) as exc:
            _load_custom_loss("typo_loss")
        msg = str(exc.value)
        assert "typo_loss" in msg
        assert "known_loss" in msg
        assert "LOSS_REGISTRY" in msg


class TestL6cPreloadGlobalLosses:
    def test_preload_loads_all_plugins(self, tmp_path, monkeypatch):
        """preload_global_losses scans LOSSES_DIR (monkeypatched to a tmp
        dir for isolation) and registers every valid .py."""
        from agent_generated import _loss_loader
        from ml_models import loss_models_sandbox
        from ml_models.loss_models_sandbox import LOSS_REGISTRY, preload_global_losses

        # Redirect LOSSES_DIR to tmp_path for this test
        monkeypatch.setattr(_loss_loader, "LOSSES_DIR", str(tmp_path))
        # Also patch the lazy import used inside preload_global_losses
        monkeypatch.setattr(loss_models_sandbox, "__name__", loss_models_sandbox.__name__)

        # Write two valid plugins + one underscore-prefixed (skipped)
        (tmp_path / "foo_loss_l6c.py").write_text(_L6C_PLUGIN_SRC_FOR_FOO)
        (tmp_path / "bar_loss_l6c.py").write_text(_L6C_PLUGIN_SRC_FOR_BAR)
        (tmp_path / "_template_loss.py").write_text("# should be skipped\n")

        loaded = preload_global_losses()
        assert sorted(loaded) == ["bar_loss_l6c", "foo_loss_l6c"]
        assert "foo_loss_l6c" in LOSS_REGISTRY
        assert "bar_loss_l6c" in LOSS_REGISTRY

    def test_preload_returns_empty_when_dir_missing(self, tmp_path, monkeypatch):
        """preload_global_losses is safe when LOSSES_DIR doesn't exist —
        first-run / fresh-checkout case."""
        from agent_generated import _loss_loader
        from ml_models.loss_models_sandbox import preload_global_losses

        monkeypatch.setattr(_loss_loader, "LOSSES_DIR", str(tmp_path / "does_not_exist"))
        loaded = preload_global_losses()
        assert loaded == []


# ---------------------------------------------------------------------------
# I13 — get_target_torch_dtype routing for built-ins + custom plugins
# ---------------------------------------------------------------------------
#
# Verifies the single source of truth for "what dtype must `targets` be cast
# to before passing into the criterion's forward()". See
# ``docs/design/enable_loss_inventory.md`` § I13.
#
# Built-in routing must match the historical pre-I13 hardcoded behavior
# (ce/focal/focal_cw → long, smooth_l1 → float32). Custom routing must
# consult LOSS_TARGET_DTYPE_REGISTRY (populated via register_loss_in_memory).


class TestI13GetTargetTorchDtype:
    def test_ce_routes_to_long(self):
        from ml_models.loss_models_sandbox import get_target_torch_dtype

        cfg = LossConfig(loss_type="ce")
        assert get_target_torch_dtype(cfg) == torch.long

    def test_focal_routes_to_long(self):
        from ml_models.loss_models_sandbox import get_target_torch_dtype

        cfg = LossConfig(loss_type="focal")
        assert get_target_torch_dtype(cfg) == torch.long

    def test_focal_cw_routes_to_long(self):
        from ml_models.loss_models_sandbox import get_target_torch_dtype

        cfg = LossConfig(loss_type="focal_cw")
        assert get_target_torch_dtype(cfg) == torch.long

    def test_smooth_l1_routes_to_float32(self):
        from ml_models.loss_models_sandbox import get_target_torch_dtype

        cfg = LossConfig(loss_type="smooth_l1")
        assert get_target_torch_dtype(cfg) == torch.float32

    def test_custom_with_registered_long_routes_to_long(self):
        """Custom loss declared as ``PLUGIN_LOSS_TARGET_DTYPE = "long"`` —
        registered via the LOSS_TARGET_DTYPE_REGISTRY — routes to torch.long."""
        from agent_generated._loss_loader import LOSS_TARGET_DTYPE_REGISTRY
        from ml_models.loss_models_sandbox import get_target_torch_dtype

        LOSS_TARGET_DTYPE_REGISTRY["__i13_custom_long__"] = "long"
        try:
            cfg = LossConfig(loss_type="custom", loss_name="__i13_custom_long__")
            assert get_target_torch_dtype(cfg) == torch.long
        finally:
            LOSS_TARGET_DTYPE_REGISTRY.pop("__i13_custom_long__", None)

    def test_custom_with_registered_float_routes_to_float32(self):
        """Custom loss declared as ``PLUGIN_LOSS_TARGET_DTYPE = "float"`` —
        e.g. a regressor-style loss — routes to torch.float32."""
        from agent_generated._loss_loader import LOSS_TARGET_DTYPE_REGISTRY
        from ml_models.loss_models_sandbox import get_target_torch_dtype

        LOSS_TARGET_DTYPE_REGISTRY["__i13_custom_float__"] = "float"
        try:
            cfg = LossConfig(loss_type="custom", loss_name="__i13_custom_float__")
            assert get_target_torch_dtype(cfg) == torch.float32
        finally:
            LOSS_TARGET_DTYPE_REGISTRY.pop("__i13_custom_float__", None)

    def test_custom_unregistered_defaults_to_long(self):
        """When ``loss_name`` is not in LOSS_TARGET_DTYPE_REGISTRY (e.g.
        in-process pre-flight before register_loss_in_memory has run),
        the helper falls back to torch.long — the classifier contract."""
        from ml_models.loss_models_sandbox import get_target_torch_dtype

        cfg = LossConfig(loss_type="custom", loss_name="__i13_never_registered__")
        assert get_target_torch_dtype(cfg) == torch.long


class TestI13RegisterPopulatesDtypeRegistry:
    """register_loss_in_memory must populate BOTH LOSS_REGISTRY (the class)
    AND LOSS_TARGET_DTYPE_REGISTRY (the declared dtype). Without the latter,
    cross-process Branch B reuse can't route targets correctly."""

    def test_register_populates_dtype_registry_long(self, tmp_path):
        from agent_generated._loss_loader import LOSS_TARGET_DTYPE_REGISTRY
        from ml_models.loss_models_sandbox import register_loss_in_memory

        src = _L6C_PLUGIN_SRC_FOR_FOO + '\nPLUGIN_LOSS_TARGET_DTYPE = "long"\n'
        plugin_path = tmp_path / "foo_loss_l6c.py"
        plugin_path.write_text(src)
        loss_type = register_loss_in_memory(str(plugin_path))
        assert loss_type == "foo_loss_l6c"
        assert LOSS_TARGET_DTYPE_REGISTRY.get("foo_loss_l6c") == "long"

    def test_register_populates_dtype_registry_float(self, tmp_path):
        from agent_generated._loss_loader import LOSS_TARGET_DTYPE_REGISTRY
        from ml_models.loss_models_sandbox import register_loss_in_memory

        src = _L6C_PLUGIN_SRC_FOR_FOO + '\nPLUGIN_LOSS_TARGET_DTYPE = "float"\n'
        plugin_path = tmp_path / "foo_loss_l6c.py"
        plugin_path.write_text(src)
        register_loss_in_memory(str(plugin_path))
        assert LOSS_TARGET_DTYPE_REGISTRY.get("foo_loss_l6c") == "float"

    def test_register_missing_declaration_defaults_to_long(self, tmp_path):
        """A pre-I13 plugin (no PLUGIN_LOSS_TARGET_DTYPE) registers cleanly
        with the default 'long' — back-compat path."""
        from agent_generated._loss_loader import LOSS_TARGET_DTYPE_REGISTRY
        from ml_models.loss_models_sandbox import register_loss_in_memory

        plugin_path = tmp_path / "foo_loss_l6c.py"
        plugin_path.write_text(_L6C_PLUGIN_SRC_FOR_FOO)
        register_loss_in_memory(str(plugin_path))
        assert LOSS_TARGET_DTYPE_REGISTRY.get("foo_loss_l6c") == "long"
