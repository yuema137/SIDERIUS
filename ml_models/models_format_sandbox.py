from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ==========================================
# 1. Base Model Configuration
# ==========================================


class BaseConfig(BaseModel):
    """General config — abstract base for every concrete model config.

    Every concrete subclass overrides ``model_type`` with a literal string
    (e.g. ``Literal["punet"] = "punet"``) that doubles as the discriminator
    for the ``MODEL_REGISTRY`` lookup. ``BaseConfig`` itself is not
    instantiated directly; the field is declared at the parent so static
    checkers can resolve ``cfg.model_type`` against an abstract
    ``BaseConfig`` reference without resorting to ``cast`` or ``getattr``.
    """

    model_type: str
    segmentation_size: int = Field(default=40000, ge=1000, description="Input time series length")
    batch_size: int = Field(default=1, ge=1)
    num_classes: int = Field(
        default=256,
        gt=0,
        description="Size of the output class alphabet, used to build "
        "embedding tables and output heads. **DERIVED, not authored** — Step "
        "03 injects it from the resolved Model-I/O contract, whose own class "
        "cardinality is cross-validated against the Dataset Profile's "
        "ValueEncoding.num_classes. The 256 default is the Regime-A "
        "compatibility value for a caller that predates the contract, in the "
        "same sense that an absent --dataset_profile_json resolves the "
        "shipped profile; a resolved path never reaches it. Setting it to "
        "contradict the contract fails closed rather than winning.",
    )


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
    def check_dimension_reduction(self) -> PUNetConfig:
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
    def check_memory_risk(self) -> TransformerConfig:
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


# ==========================================
# Global Model Registry
# ==========================================

# Union type for the Agent to choose from. The PEP 695 ``type`` keyword form
# is required so pyright accepts the symbol in type positions (e.g.
# ``network_config: ModelConfigUnion`` on ExperimentConfig); without it
# pyright treats the symbol as a runtime variable. Pydantic 2.12+ resolves
# the lazy alias correctly during model rebuild.
type ModelConfigUnion = (
    PUNetConfig | AEConfig | TransformerConfig | WaveNetConfig | RNNSeq2SeqConfig | GatedFNOConfig
)


def get_config_class(model_type: str) -> type[BaseConfig] | None:
    """Helper for the Orchestrator to map strings to Pydantic classes.

    Returns the built-in config class, else the plugin's, else ``None``.

    **V21 PR C2 — the plugin branch guarantees the registry is populated
    before reading it.** ``PLUGIN_CONFIG_REGISTRY`` is filled as an *import
    side effect* of ``ml_models.models_sandbox`` (its module tail calls
    ``extend_registries``). Importing *this* module does not trigger that,
    so before C2 any caller who had not separately imported
    ``models_sandbox`` read an **empty** registry and got ``None`` back for
    a plugin that was registered perfectly well on disk — silently, with no
    warning and no exception.

    That is the defect behind V20's ``CONFIG_REJECTED``. PR #185 fixed the
    *one* call site that had been caught (the measurement worker's
    ``validate_candidate_configs``) by adding an explicit ``models_sandbox``
    import there; the function itself was left vulnerable, so every other
    caller still depended on some unrelated module happening to import
    ``models_sandbox`` first. Measured at C2 time, a clean process
    importing only this module saw **0 of 82** plugins.

    The lazy import below is the same self-healing pattern
    ``plugin_loader.get_output_type`` already uses, and it must stay lazy:
    ``models_sandbox`` imports *this* module, so a module-level import here
    would be circular.
    """
    mapping = {
        "punet": PUNetConfig,
        "fcnet": AEConfig,
        "transformer": TransformerConfig,
        "wavenet": WaveNetConfig,
        "rnn": RNNSeq2SeqConfig,
        "gated_fno": GatedFNOConfig,
    }
    builtin = mapping.get(model_type)
    if builtin is not None:
        return builtin

    # Trigger the populating import. If ``models_sandbox`` is already in
    # sys.modules (including mid-import, when this is called from inside its
    # own import) this is a cheap no-op and behaviour is exactly as before.
    import ml_models.models_sandbox  # noqa: F401  (imported for side effect)

    return PLUGIN_CONFIG_REGISTRY.get(model_type)


# Plugin config registry — populated at runtime by ml_models/plugin_loader.py.
# Agents must not modify this dict directly; use extend_registries() instead.
PLUGIN_CONFIG_REGISTRY: dict = {}


# ==========================================
# Output-contract / loss compatibility — THE single authority
# ==========================================

#: Losses that consume per-timestep class logits, [B, C, T].
CLASSIFICATION_LOSSES: frozenset[str] = frozenset({"ce", "focal", "focal_cw"})

#: Losses that consume a continuous waveform, [B, T].
REGRESSION_LOSSES: frozenset[str] = frozenset({"smooth_l1"})


class DtypeAdmissibility(BaseModel):
    """Which concrete dtypes the model boundary will accept — **A-1**.

    This is the amendment's core correction (§4a.1). The contract owns an
    *admissibility requirement*, **not** a concrete cast, because baseline
    A6 proved there is no single shipped concrete dtype to own: the
    embedding-arm builtins are fed int32 in training and int64 in
    inference, and both are correct.

    ```text
    model-admissible  ∩  runtime-supported  ->  deterministic concrete dtype
                                            ->  empty = typed fail-closed
    ```

    **Extensible by construction.** ``admissible`` is an ordered tuple of
    normalized dtype names, not a closed enum, so representing a model
    that requires ``float16``, ``bfloat16``, ``float64``, ``bool`` or
    ``complex64`` needs no schema redesign. Execution support for those
    stays capability-gated: expressing a requirement is not a claim that
    the adaptation path can materialize it. Today only ``int32``,
    ``int64`` and ``float32`` are *validated* as executable (A6).

    **Order is meaning.** ``admissible[0]`` is the contract's CANONICAL
    representation: it is what renders into LLM-facing prose, and it is
    the deterministic tie-break when no execution site expresses a
    preference. A site's own preferred dtype still wins whenever it is
    admissible — that is what keeps TIDMAD's concrete matrix exact — but
    a site preference is compatibility behaviour, never model semantics
    (§4a.1), so it lives at the site and never in this model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    admissible: tuple[str, ...] = Field(
        min_length=1,
        description="Ordered normalized dtype names the model boundary "
        "accepts. admissible[0] is the canonical representation used for "
        "rendering and as the deterministic default.",
    )

    @model_validator(mode="after")
    def _no_duplicates(self) -> DtypeAdmissibility:
        """A repeated dtype makes 'the canonical one' ambiguous to a reader
        and hides an authoring mistake behind a set-like intersection."""
        if len(set(self.admissible)) != len(self.admissible):
            raise ValueError(f"duplicate dtype in admissible={self.admissible!r}")
        return self

    @property
    def canonical(self) -> str:
        """The representation shown to an LLM and used as the default."""
        return self.admissible[0]

    def admits(self, dtype_name: str) -> bool:
        return dtype_name in self.admissible


class OutputSemantic(StrEnum):
    """The canonical output semantic — Step 03 §8b.

    **The single authority answering "what output semantics does this model
    have".** Loss legality is a function of THIS, not of the legacy string
    ``"classifier"``; ``output_type`` becomes a derived projection.

    It lives here, beside the frozensets it keys, because §8a is explicit
    that Step 03 RE-KEYS the existing loss authority rather than creating a
    second one. It lives in ``ml_models`` rather than ``agent/schemas``
    because ``agent`` imports ``ml_models`` and not the reverse; putting it
    in the schema layer would invert the dependency.

    Two members, because the normalized output tensor supports exactly two
    distinctions today: an output carrying a class-alphabet axis, and one
    that does not (§4b). ``hybrid`` is deliberately absent — see
    :func:`output_semantic_from_legacy`.
    """

    CATEGORICAL = "categorical"
    CONTINUOUS = "continuous"


#: The §8b projection: canonical semantic -> the legacy ``output_type`` word.
#:
#: One-way by design. ``hybrid`` is never PRODUCED by the projection because
#: it is not a tensor semantic (§8c) — it is a legacy adapter value for
#: builtin ``fcnet``, which chooses its own forward shape from ``loss_type``
#: at construction time. Inventing tensor semantics for it is forbidden.
_LEGACY_OUTPUT_TYPE: dict[OutputSemantic, str] = {
    OutputSemantic.CATEGORICAL: "classifier",
    OutputSemantic.CONTINUOUS: "regressor",
}


def legacy_output_type_for(semantic: OutputSemantic) -> str:
    """Project the canonical semantic onto the legacy ``output_type`` word.

    The compatibility view of §8b — a derived projection, never a second
    authority. Nothing may write back through it.
    """
    return _LEGACY_OUTPUT_TYPE[semantic]


def output_semantic_from_legacy(output_type: str) -> OutputSemantic | None:
    """Adapt a legacy ``output_type`` string to the canonical semantic.

    Returns ``None`` for a value that carries **no** canonical output
    semantic. Two distinct cases share that answer, deliberately:

    * ``"hybrid"`` — a legacy builtin adapter value (§8c), not a tensor
      semantic. Its shipped behaviour is that every loss is legal, and that
      behaviour is preserved exactly.
    * any unrecognised string — the shipped rule matches neither guard
      branch and therefore raises nothing. That tolerance is **current
      behaviour, pinned by baseline A2**, not an endorsement: tightening it
      would change an accept/reject verdict, which §21 makes a STOP.

    Collapsing them here is what keeps the re-key verdict-preserving. If a
    future step wants to fail closed on an unrecognised value, that is a
    policy decision requiring an operator call, and A2's tolerance test is
    the tripwire that will demand it.
    """
    for semantic, legacy in _LEGACY_OUTPUT_TYPE.items():
        if output_type == legacy:
            return semantic
    return None


def validate_semantic_loss_compatibility(
    semantic: OutputSemantic | None,
    loss_type: str,
    *,
    model_type: str,
) -> None:
    """**THE** loss-availability rule, keyed on the canonical semantic (§8a).

    This is the re-keyed body of :func:`validate_output_loss_compatibility`;
    that function is now a thin legacy adapter over it. There is exactly one
    implementation of the rule, and both entry points reach it.

    ``semantic is None`` means "no canonical output semantic" — legacy
    ``hybrid`` or an unrecognised value — and every loss is permitted, which
    is precisely the shipped behaviour.

    Args:
        semantic: the canonical output semantic, or ``None``.
        loss_type: a ``LossConfig.loss_type`` value.
        model_type: used only to build a readable error message.

    Raises:
        ValueError: if the pair is incompatible.
    """
    if semantic is None:
        return

    if loss_type in REGRESSION_LOSSES and semantic is OutputSemantic.CATEGORICAL:
        raise ValueError(
            f"Incompatible: '{model_type}' is a classifier (output [B, 256, T]) "
            f"— use 'ce' or 'focal', not 'smooth_l1'."
        )

    if loss_type in CLASSIFICATION_LOSSES and semantic is OutputSemantic.CONTINUOUS:
        raise ValueError(
            f"Incompatible: '{model_type}' is a regressor (output [B, T]) "
            f"— use 'smooth_l1', not '{loss_type}'."
        )


def validate_output_loss_compatibility(
    output_type: str,
    loss_type: str,
    *,
    model_type: str,
) -> None:
    """Raise ``ValueError`` if an output contract and a loss are incompatible.

    **This function is THE production authority for model/loss compatibility.**
    Both production paths are its consumers and neither may re-implement the
    rule:

    ==========================  =========================================
    consumer                    path
    ==========================  =========================================
    ``ExperimentConfig``        built-in models
    ``SandboxExecutor.
    _validate_configs``         agent-generated plugin models
    ==========================  =========================================

    History (V21 PR A). Two defects motivated this shape:

    * ``LossConfig.check_compatibility`` was a SECOND, contradictory rule
      keyed on a model-name literal. It had no production callers and was
      deleted in A1.
    * The surviving rule lived inside ``ExperimentConfig``, which
      ``_validate_configs`` **bypasses for plugin models** — so the only kind
      of model the agent actually invents was governed by no rule at all. A
      registered plugin declaring ``classifier`` paired with ``smooth_l1``
      was accepted. A2b extracted this function and gave that branch a call
      site.

    The lesson generalises: a rule existing on one production branch is never
    evidence that it governs the other.

    ``hybrid`` (e.g. ``fcnet``) accepts any loss. Loss types in neither set —
    notably ``custom`` — are deliberately permitted for every contract: the
    plugin's own forward pass raises at training time if its shape contract is
    violated, which ``LossConfig`` cannot know in advance.

    Args:
        output_type: ``"classifier"``, ``"regressor"`` or ``"hybrid"``.
        loss_type: a ``LossConfig.loss_type`` value.
        model_type: used only to build a readable error message.

    Raises:
        ValueError: if the pair is incompatible.
    """
    # Step 03 §8a — RE-KEYED, not re-declared. The rule itself now lives in
    # `validate_semantic_loss_compatibility`, keyed on the canonical output
    # semantic; this entry point projects the legacy string onto that
    # semantic and delegates. There is one implementation, so the two entry
    # points cannot drift. Every verdict is unchanged — baseline A2 pins all
    # 15 cells, and a changed cell is a §21 STOP.
    validate_semantic_loss_compatibility(
        output_semantic_from_legacy(output_type),
        loss_type,
        model_type=model_type,
    )


# ==========================================
# Loss Configs
# ==========================================


class LossConfig(BaseModel):
    """
    Configuration for the Denoising Scoring Functions (Loss).
    Strictly validates parameters based on the chosen loss_type.

    The four built-in ``loss_type`` values (``focal``, ``focal_cw``, ``ce``,
    ``smooth_l1``) use the ``alpha`` / ``gamma`` / ``beta`` fields below.
    The ``custom`` value (L2 — see ``docs/design/enable_loss_inventory.md``)
    routes to a plugin loss in ``agent_generated/losses/``; the plugin's own
    ``PLUGIN_LOSS_CONFIG_CLASS`` carries any plugin-specific hyperparameters.
    LossConfig is purely the *router* in custom mode — ``alpha`` / ``gamma``
    / ``beta`` are nullified by ``enforce_parameter_consistency`` so the
    agent can't accidentally pass them through.
    """

    loss_type: Literal["focal", "focal_cw", "ce", "smooth_l1", "custom"] = "focal"

    # Parameters for Focal / Focal_CW
    alpha: float | None = Field(default=0.5, ge=0.0, le=1.0)
    gamma: float | None = Field(default=2.0, ge=0.0, le=5.0)

    # Parameter for SmoothL1
    beta: float | None = Field(default=1.0, ge=0.1, le=10.0)

    reduction: Literal["mean", "sum"] = "mean"
    use_class_weights: bool = Field(default=False)

    # Custom-loss routing (L2). Required when ``loss_type="custom"``;
    # forbidden otherwise.
    loss_name: str | None = Field(
        default=None,
        description=(
            "PLUGIN_LOSS_TYPE key of the agent-generated loss to use. "
            "Required when loss_type='custom'. The loss plugin must exist "
            "in agent_generated/losses/ (or in a SIDERIUS_LOSS_DIRS-resolved "
            "per-run directory) before training begins."
        ),
    )

    # NOTE (V21 PR A, 2026-08-07): ``check_compatibility`` was deleted here.
    # It was a name-literal gate (``model_type != "fcnet"``) with ZERO
    # production callers — only its own definition and one unit test — whose
    # docstring falsely claimed the Executor called it, and whose rule
    # CONTRADICTED the live authority: it rejected ``regressor + smooth_l1``,
    # which ``ExperimentConfig.validate_architecture_loss_match`` correctly
    # permits. Model/loss compatibility is decided in exactly one place; see
    # that validator. ``custom`` still defers to the plugin, which the live
    # gate expresses by falling through for any non-classification,
    # non-``smooth_l1`` loss type.

    @model_validator(mode="after")
    def enforce_custom_loss_name(self) -> LossConfig:
        """Custom mode requires ``loss_name``; non-custom modes forbid it.

        This pair of checks prevents two silent-failure modes:
          1. ``loss_type="custom"`` + ``loss_name=None`` → ``get_criterion``
             would crash trying to look up ``None`` in the registry.
          2. ``loss_type="focal"`` + ``loss_name="snr_weighted_mse"`` →
             the operator probably meant ``loss_type="custom"``; surfacing
             the inconsistency at validation time prevents the run from
             silently using focal loss instead of the custom one.
        """
        if self.loss_type == "custom" and not self.loss_name:
            raise ValueError(
                "loss_name is required when loss_type='custom'. "
                "Set loss_name to the PLUGIN_LOSS_TYPE key of the agent-generated loss "
                "(e.g. 'snr_weighted_mse')."
            )
        if self.loss_type != "custom" and self.loss_name:
            raise ValueError(
                f"loss_name must be None when loss_type != 'custom' "
                f"(got loss_type={self.loss_type!r}, loss_name={self.loss_name!r}). "
                f"If you meant to use a custom loss, set loss_type='custom'."
            )
        return self

    @model_validator(mode="after")
    def enforce_parameter_consistency(self) -> LossConfig:
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

        elif self.loss_type == "custom":
            # LossConfig is the routing layer only for custom losses — the
            # plugin's own PLUGIN_LOSS_CONFIG_CLASS carries the actual
            # hyperparameters. Nullify the built-in params so the agent
            # can't accidentally pass them through. See
            # ``docs/design/enable_loss_inventory.md`` § "Two-config design".
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

    # F-SCANA-1 — the default an OMITTED LLM `lr` key resolves to is the
    # paper-spec baseline value: TIDMAD train.py uses
    # `torch.optim.Adam(..., lr=0.0005)` for every model, and
    # `ml_models/legacy_baseline_configs.json` (the paper-spec source of
    # truth) pins `lr: 5e-4` throughout. Pre-fix this default was 1e-4, so a
    # plan that simply omitted the key departed 5x from spec THROUGH the
    # validation gate. The collapse-recovery prompt's "reset to the
    # known-working baseline: ... `lr=5e-4`" (agent/prompts.py) states the
    # same value; a regression test pins both surfaces to the paper literal.
    lr: float = Field(default=5e-4, ge=1e-6, le=1e-1)
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
    def validate_architecture_loss_match(self) -> ExperimentConfig:
        """
        Enforce the physical constraint: loss type must match model output type.

        **This is the SINGLE production authority for model/loss
        compatibility.** Do not add a second compatibility rule elsewhere —
        V21 PR A deleted exactly such a duplicate (``LossConfig.
        check_compatibility``), which had no production callers and whose
        name-keyed rule contradicted this one. Two answers to the same
        question is not a doubled safeguard; it guarantees one of them is
        wrong and nobody knows which.

        - Classifiers ([B, 256, T] output) use ce, focal, focal_cw.
        - Regressors ([B, T] output) use smooth_l1.

        Output type is looked up from BUILTIN_OUTPUT_TYPES (built-in models)
        or PLUGIN_OUTPUT_TYPE_REGISTRY (agent-generated plugins). A model in
        neither registry is a **validation failure** (V21 PR C1) — it is not
        assumed to be a classifier.

        Raises:
            ValueError: the model's output contract is not established.
                Pydantic surfaces this as a ``ValidationError`` on the model,
                which is this layer's typed refusal.
        """
        from ml_models.plugin_loader import (
            UnknownOutputContractError,
            get_output_type,
        )

        # Delegate to the shared authority — do not inline the rule here.
        # This is the BUILT-IN consumer; the generated-plugin consumer is
        # SandboxExecutor._validate_configs. Both must call the same function.
        try:
            output_type = get_output_type(self.model_type)
        except UnknownOutputContractError as e:
            # V21 PR C1 — translate the invariant failure into this layer's
            # idiom. A validator raising ValueError becomes a Pydantic
            # ValidationError, so the caller sees a typed config refusal
            # rather than a LookupError escaping from a registry.
            raise ValueError(str(e)) from e

        validate_output_loss_compatibility(
            output_type,
            self.loss_config.loss_type,
            model_type=self.model_type,
        )
        return self
