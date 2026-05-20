from typing import Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# ==========================================
# 1. Base Model Configuration
# ==========================================


class BaseConfig(BaseModel):
    """General config"""

    segmentation_size: int = Field(default=40000, ge=1000, description="Input time series length")
    batch_size: int = Field(default=1, ge=1)


# ==========================================
# 2. PUNet Configuration (Convolutional)
# ==========================================
class PUNetConfig(BaseConfig):
    model_type: Literal["punet"] = "punet"
    multi: int = Field(default=40, ge=8, le=128, description="Base channel multiplier")
    depth: int = Field(default=4, ge=1, le=5, description="Number of downsampling steps")
    bilinear: bool = Field(
        default=True, description="Whether to use bilinear upsampling or conv transpose"
    )
    pe_factor: float = Field(default=1.0, ge=0.0, le=10.0, description="Positional encoding weight")
    kernel_size: int = Field(default=9, ge=3, le=15, description="Convolutional kernel size")
    embedding_dim: int = Field(
        default=32, ge=8, le=256, description="Latent space dimension for ADC values"
    )

    @field_validator("kernel_size")
    @classmethod
    def kernel_must_be_odd(cls, v: int) -> int:
        """Ensures symmetric padding is possible."""
        if v % 2 == 0:
            raise ValueError("kernel_size must be odd for symmetric padding")
        return v

    @model_validator(mode="after")
    def check_dimension_reduction(self) -> "PUNetConfig":
        """
        Physical/Architecture Constraint:
        Ensures segmentation_size is large enough to sustain the chosen depth.
        With a stride of 4, the size reduces by 4^depth.
        """
        reduction_factor = 4**self.depth
        if self.segmentation_size < reduction_factor:
            raise ValueError(
                f"segmentation_size ({self.segmentation_size}) is too small for "
                f"depth ({self.depth}). Minimum required: {reduction_factor}"
            )

        # Optional: Check if size is a multiple of the reduction factor for clean division
        if self.segmentation_size % reduction_factor != 0:
            # We don't necessarily raise an error because F.pad handles it,
            # but it's good practice to log or warn.
            pass

        return self


# ==========================================
# 3. AE Configuration (Fully Connected)
# ==========================================
class AEConfig(BaseConfig):
    """
    Configuration for Fully Connected AutoEncoder.
    Designed for global feature compression and noise filtering.
    """

    model_type: Literal["fcnet"] = "fcnet"
    # Agent can modify the depth and width by changing this list
    latent_dims: list[int] = Field(
        default=[4000, 400, 40],
        min_length=1,
        max_length=6,
        description="List of hidden layer dimensions for the encoder",
    )
    dropout: float = Field(default=0.0, ge=0.0, le=0.5)

    @field_validator("latent_dims")
    @classmethod
    def check_dimensions(cls, v: list[int]) -> list[int]:
        if any(d <= 0 for d in v):
            raise ValueError("All hidden dimensions must be positive integers.")
        return v


# ==========================================
# 4. Transformer Configuration
# ==========================================
class TransformerConfig(BaseConfig):
    model_type: Literal["transformer"] = "transformer"
    # Note: Baseline used 20000 to avoid OOM
    segmentation_size: int = Field(default=20000, ge=1000, le=40000)
    embedding_dim: int = Field(default=32, ge=8, le=256)
    nhead: int = Field(default=4, ge=1, le=16)
    num_layers: int = Field(default=2, ge=1, le=10)
    dim_feedforward: int = Field(default=128, ge=64, le=1024)
    dropout: float = Field(default=0.1, ge=0.0, le=0.5)
    pe_factor: float = Field(default=1.0, ge=0.0, le=10.0)

    @model_validator(mode="after")
    def check_memory_risk(self) -> "TransformerConfig":
        if self.segmentation_size > 25000:
            # We could raise a warning here if we had a logger,
            # for now, we just keep it as a known risk.
            pass
        return self

    @field_validator("nhead")
    @classmethod
    def check_nhead_divisibility(cls, v: int, info) -> int:
        embedding_dim = info.data.get("embedding_dim")
        if embedding_dim and embedding_dim % v != 0:
            raise ValueError(f"embedding_dim {embedding_dim} must be divisible by nhead {v}")
        return v


# ==========================================
# 5. WaveNet Configuration
# ==========================================
class WaveNetConfig(BaseConfig):
    model_type: Literal["wavenet"] = "wavenet"
    input_channels: int = Field(default=16, ge=4, le=64, description="Embedding output dimension")
    residual_channels: int = Field(
        default=32, ge=8, le=128, description="Channel width through residual blocks"
    )
    gate_channels: int = Field(
        default=64, ge=8, le=256, description="Channels for gated activation (must be even)"
    )
    skip_channels: int = Field(default=32, ge=8, le=128, description="Skip connection channels")
    kernel_size: int = Field(default=12, ge=2, le=32, description="Causal convolution kernel size")
    num_blocks: int = Field(
        default=10, ge=1, le=20, description="Number of WaveNet residual blocks"
    )

    @field_validator("gate_channels")
    @classmethod
    def gate_channels_must_be_even(cls, v: int) -> int:
        if v % 2 != 0:
            raise ValueError("gate_channels must be even (split in half for gated activation)")
        return v


# ==========================================
# 6. RNNSeq2Seq Configuration
# ==========================================
class RNNSeq2SeqConfig(BaseConfig):
    model_type: Literal["rnn"] = "rnn"
    embedding_dim: int = Field(
        default=128, ge=8, le=512, description="Embedding dimension for ADC tokens"
    )
    hidden_dim: int = Field(default=256, ge=8, le=1024, description="LSTM hidden state size")
    num_layers: int = Field(
        default=2, ge=1, le=6, description="Number of LSTM layers in encoder and decoder"
    )
    dropout: float = Field(
        default=0.1,
        ge=0.0,
        le=0.5,
        description="Dropout applied between LSTM layers (ignored if num_layers=1)",
    )


# ==========================================
# 7. GatedFNO Configuration
# ==========================================


def _build_gate_grid(step: float) -> list[float]:
    """
    Return the allowed static_v values for a given step size.

    The grid is {0.0, step, 2*step, ..., 1.0}. The largest legal step is 1.0
    (collapses to binary {0.0, 1.0}); smallest practical step is bounded only
    by floating-point precision. Step must divide 1.0 evenly.
    """
    if not (0.0 < step <= 1.0):
        raise ValueError(f"gate_step must be in (0, 1], got {step}")
    n = round(1.0 / step)
    if abs(n * step - 1.0) > 1e-9:
        raise ValueError(f"gate_step {step} must divide 1.0 evenly (got n*step = {n * step})")
    return [round(i * step, 10) for i in range(n + 1)]


class GatedFNOConfig(BaseConfig):
    """
    Configuration for Gated Fourier Neural Operator.
    Enables frequency-domain denoising with manual signal protection.
    """

    model_type: Literal["gated_fno"] = "gated_fno"
    width: int = Field(default=64, ge=16, le=256, description="Latent channel width")
    num_layers: int = Field(default=2, ge=1, le=5, description="Number of FNO blocks")
    num_gates: int = Field(default=128, ge=8, le=4096, description="Granularity of the gate vector")
    gate_mapping: Literal["linear", "log"] = Field(
        default="log",
        description="How gate indices map to frequency bins. "
        "'log': denser at low frequencies (matches physics — signals are log-spaced). "
        "'linear': uniform spacing across the spectrum.",
    )
    # --- Discrete grid for static_v values (per-instance hyperparameter) ---
    gate_step: float = Field(
        default=0.1,
        gt=0.0,
        le=1.0,
        description=(
            "Step size for the discrete grid of allowed static_v values. "
            "Allowed grid is {0.0, gate_step, 2*gate_step, ..., 1.0}. "
            "Examples: 0.1 -> {0.0, 0.1, ..., 1.0} (11 levels, default), "
            "0.2 -> {0.0, 0.2, 0.4, 0.6, 0.8, 1.0} (6 levels), "
            "0.5 -> {0.0, 0.5, 1.0} (3 levels), "
            "1.0 -> {0.0, 1.0} (binary on/off). "
            "Must divide 1.0 evenly. Smaller step = finer granularity but a "
            "larger search space; binary (1.0) loses smoothness."
        ),
    )
    # --- Agent-tunable gate vector ---
    static_v: list[float] | None = Field(
        default=None,
        description=(
            "Static gate vector. Length must match num_gates. Each entry must "
            "lie on the discrete grid defined by gate_step "
            "(i.e. {0.0, gate_step, 2*gate_step, ..., 1.0}). "
            "These are continuous attenuation factors (0.0 = fully blocked, "
            "1.0 = fully passed) — NOT a binary mask unless gate_step=1.0. "
            "You should explore intermediate values to produce smooth gating "
            "curves: linear ramps, soft low-pass, soft band-pass, graded "
            "attenuation. Examples (with gate_step=0.1): a smooth low-pass "
            "[1.0, 1.0, 0.9, 0.7, 0.4, 0.1, 0.0, ...] or a band-pass "
            "[0.0, 0.2, 0.6, 1.0, 1.0, 0.6, 0.2, 0.0, ...]."
        ),
    )

    @field_validator("gate_step")
    @classmethod
    def validate_gate_step(cls, v: float) -> float:
        # Run _build_gate_grid for its side-effect (range + divisibility check).
        _build_gate_grid(v)
        return v

    @field_validator("static_v")
    @classmethod
    def validate_static_v(cls, v: list[float] | None, info) -> list[float] | None:
        if v is None:
            return v
        num_gates = info.data.get("num_gates")
        if num_gates is not None and len(v) != num_gates:
            raise ValueError(f"static_v length ({len(v)}) must match num_gates ({num_gates})")
        # Resolve grid from this instance's gate_step. Falls back to the field
        # default if gate_step failed earlier validation (then info.data omits it).
        gate_step = info.data.get("gate_step", 0.1)
        try:
            grid = _build_gate_grid(gate_step)
        except ValueError:
            # gate_step itself was invalid; that error will surface separately.
            return v
        tol = 1e-6
        snapped: list[float] = []
        bad: list[tuple] = []
        for i, x in enumerate(v):
            if not isinstance(x, (int, float)):
                bad.append((i, x))
                continue
            if not (-tol <= x <= 1.0 + tol):
                bad.append((i, x))
                continue
            n = round(x / gate_step)
            s = round(n * gate_step, 10)
            if abs(s - x) > tol:
                bad.append((i, x))
                continue
            snapped.append(s)
        if bad:
            preview = bad[:5]
            more = "..." if len(bad) > 5 else ""
            raise ValueError(
                f"static_v entries must lie on the discrete grid {grid} "
                f"(gate_step={gate_step}). Invalid entries (index, value): "
                f"{preview}{more}"
            )
        return snapped


# Update ModelConfigUnion
ModelConfigUnion = Union[
    PUNetConfig, AEConfig, TransformerConfig, WaveNetConfig, RNNSeq2SeqConfig, GatedFNOConfig
]

# Update get_config_class mapping
# "gated_fno": GatedFNOConfig

# ==========================================
# Global Model Registry
# ==========================================

# Union type for the Agent to choose from
ModelConfigUnion = Union[
    PUNetConfig, AEConfig, TransformerConfig, WaveNetConfig, RNNSeq2SeqConfig, GatedFNOConfig
]


def get_config_class(model_type: str) -> type[BaseConfig] | None:
    """Helper for the Orchestrator to map strings to Pydantic classes."""
    mapping = {
        "punet": PUNetConfig,
        "fcnet": AEConfig,
        "transformer": TransformerConfig,
        "wavenet": WaveNetConfig,
        "rnn": RNNSeq2SeqConfig,
        "gated_fno": GatedFNOConfig,
    }
    return mapping.get(model_type) or PLUGIN_CONFIG_REGISTRY.get(model_type)


# Plugin config registry — populated at runtime by ml_models/plugin_loader.py.
# Agents must not modify this dict directly; use extend_registries() instead.
PLUGIN_CONFIG_REGISTRY: dict = {}

# ==========================================
# Loss Configs
# ==========================================


class LossConfig(BaseModel):
    """
    Configuration for the Denoising Scoring Functions (Loss).
    Strictly validates parameters based on the chosen loss_type.
    """

    loss_type: Literal["focal", "focal_cw", "ce", "smooth_l1"] = "focal"

    # Parameters for Focal / Focal_CW
    alpha: float | None = Field(default=0.5, ge=0.0, le=1.0)
    gamma: float | None = Field(default=2.0, ge=0.0, le=5.0)

    # Parameter for SmoothL1
    beta: float | None = Field(default=1.0, ge=0.1, le=10.0)

    reduction: Literal["mean", "sum"] = "mean"
    use_class_weights: bool = Field(default=False)

    def check_compatibility(self, model_type: str):
        """Called by Executor to prevent illegal combinations."""
        if self.loss_type == "smooth_l1" and model_type != "fcnet":
            raise ValueError(
                f"Incompatible Pair: 'smooth_l1' is for waveform regression (AE/fcnet). "
                f"Model '{model_type}' is a classifier and requires 'ce' or 'focal' ."
            )

    @model_validator(mode="after")
    def enforce_parameter_consistency(self) -> "LossConfig":
        """
        Ensures that only relevant parameters are active for the selected loss_type.
        This prevents the Agent from 'hallucinating' cross-parameter optimizations.
        """
        if self.loss_type in ["focal", "focal_cw"]:
            # SmoothL1 parameter is irrelevant here
            self.beta = None

        elif self.loss_type == "smooth_l1":
            # Focal parameters are irrelevant here
            self.alpha = None
            self.gamma = None
            # Regression usually doesn't use class weights in the same way
            self.use_class_weights = False

        elif self.loss_type == "ce":
            # CrossEntropy is the baseline, no special hyperparams needed
            self.alpha = None
            self.gamma = None
            self.beta = None

        return self


# ==========================================
# Training Config
# ==========================================


class TrainConfig(BaseModel):
    """
    Configuration for the training execution.
    Agent can optimize learning rate, optimizer type, and epochs.
    """

    lr: float = Field(default=1e-4, ge=1e-6, le=1e-1)
    epochs: int = Field(default=10, ge=1, le=100)
    # --- Add batch ---
    batch_size: int = Field(default=1, ge=1, le=1024, description="Batch size for training")
    # ----------------------------
    optimizer_type: Literal["adam", "adamw", "sgd"] = "adamw"
    weight_decay: float = Field(default=1e-5, ge=0, le=1e-1)
    device: str = "cuda"  # or "cpu"


# ==========================================
# Integrated Config
# ==========================================
class ExperimentConfig(BaseModel):
    """
    Top-level validation class that captures the entire experiment intent.
    This is where cross-config compatibility is enforced.
    """

    exp_id: str
    run_name: str
    model_type: str  # Accepts built-in and agent-generated plugin model types
    network_config: ModelConfigUnion  # This uses the Union defined earlier
    train_config: TrainConfig
    loss_config: LossConfig

    @model_validator(mode="after")
    def validate_architecture_loss_match(self) -> "ExperimentConfig":
        """
        Enforce the physical constraint: loss type must match model output type.

        - Classifiers ([B, 256, T] output) use ce, focal, focal_cw.
        - Regressors ([B, T] output) use smooth_l1.

        Output type is looked up from BUILTIN_OUTPUT_TYPES (built-in models)
        or PLUGIN_OUTPUT_TYPE_REGISTRY (agent-generated plugins). Unknown models
        default to 'classifier'.
        """
        from ml_models.plugin_loader import get_output_type

        output_type = get_output_type(self.model_type)
        l_type = self.loss_config.loss_type

        # "hybrid" models (e.g. fcnet) accept any loss type
        if output_type == "hybrid":
            return self

        if l_type == "smooth_l1" and output_type == "classifier":
            raise ValueError(
                f"Incompatible: '{self.model_type}' is a classifier (output [B, 256, T]) "
                f"— use 'ce' or 'focal', not 'smooth_l1'."
            )

        if l_type in ["ce", "focal", "focal_cw"] and output_type == "regressor":
            raise ValueError(
                f"Incompatible: '{self.model_type}' is a regressor (output [B, T]) "
                f"— use 'smooth_l1', not '{l_type}'."
            )

        return self
