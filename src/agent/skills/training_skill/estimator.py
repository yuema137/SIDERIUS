"""
agent/skills/training_skill/estimator.py

Per-phase VRAM and wall-time estimator for the TRAINING phase of a
proposed experiment. Lifted from ``evaluate_vram_skill.wrapper._estimate_bytes``
and the step-count × ms/step logic in
``evaluate_time_skill.wrapper.run_skill`` during Phase K.2.5 so the two
resource aggregators (``evaluate_vram_skill`` = peak over phases;
``evaluate_time_skill`` = sum over phases) can compose training +
inference + scoring without each owning a copy of the training-phase
formulas.

Contract (K.2.5 Commit 2):
  * ``estimate_peak_bytes(model_type, model_config, train_config,
    loss_config, num_params)`` — worst-case float32 training memory:
    weights + grads + Adam m + v + output logits + backward activations
    + optional focal one_hot + optional transformer self-attention.
    Returns ``{"phase": "training", "total_bytes", "breakdown"}``.
  * ``estimate_wall_time_seconds(model_type, model_config, train_config,
    sample_set, *, train_portion, ms_per_step, gpu_name, num_params,
    loss_type)`` — total_steps × ms/step × SAFETY_MULTIPLIER. Returns
    ``{"phase": "training", "seconds", "breakdown"}``. When
    ``ms_per_step`` is not supplied, the static formula is used —
    mirrors the wrapper's pre-K.2.5 fallback so callers without a live
    warmup signal still get an order-of-magnitude estimate, stamped
    ``formal_execution_eligible: False``.

    OPERATOR DECISION 2026-08-03: the live ``ms_per_step`` of THIS
    candidate is the SOLE runtime evidence here. A legacy per-GPU
    historical ``k`` used to multiply into this formula; it is gone, and
    ``gpu_name`` is now recorded for provenance only. The only remaining
    multiplier is ``SAFETY_MULTIPLIER``, which is configured policy, not
    learned experience.

The estimator is pure (no side effects other than CPU model
instantiation for ``_count_params``): the real-dataset warmup stays in
the aggregator, keeping this module cheap and test-friendly.

See docs/resource_estimator_implement.md §10.5 + §10.14 Commit 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import torch

from ml_models.models_format_sandbox import resolve_training_drop_last

if TYPE_CHECKING:  # pragma: no cover - typing only
    from execute_tools.dataset_config import DatasetProfile

# NOTE: `agent.skills.evaluate_time_skill.calibration` is deliberately NOT
# imported here. This module produces the production runtime estimate, and the
# operator decision of 2026-08-03 makes the current live measurement its sole
# runtime evidence. The absence of this import is asserted by
# `test_live_timing_is_the_sole_runtime_evidence.py` — re-adding it fails.

# ── constants (mirror the legacy wrapper verbatim) ───────────────────────────

_BYTES_F32 = 4
_BYTES_I64 = 8

# Mirrors ``LossConfig.loss_type`` (models_format_sandbox.py:458). Declared
# here rather than imported so this module keeps its lazy-import discipline
# — a top-level import of the sandbox config module would pull torch model
# code into every estimator caller.
LossTypeName = Literal["focal", "focal_cw", "ce", "smooth_l1", "custom"]
_LEGAL_LOSS_TYPES: tuple[LossTypeName, ...] = (
    "focal",
    "focal_cw",
    "ce",
    "smooth_l1",
    "custom",
)


def _output_contract(model_type: str) -> str:
    """The model's declared output contract, or ``"classifier"`` if unknown.

    V21 PR C3. Estimators run at **planning** time, sometimes for a model
    that is not registered yet (proposer-side pre-flight), so unlike the
    execution path this helper must not fail closed — a refusal here would
    turn a missing estimate into a rejected candidate.

    The fallback is safe in the only direction that matters: ``"classifier"``
    reproduces the pre-C3 behaviour exactly, and the classifier contract is
    the memory-heavier of the two, so an unresolvable model is estimated
    conservatively rather than optimistically. This is deliberately NOT the
    silent default C1 removed from ``get_output_type`` — there, the value
    decided scientific semantics; here it only widens a forecast.
    """
    from ml_models.plugin_loader import UnknownOutputContractError, get_output_type

    try:
        return get_output_type(model_type)
    except UnknownOutputContractError:
        return "classifier"


def _declared_default(config_cls: Any, field: str) -> Any | None:
    """The default a Pydantic config class declares for ``field``.

    ``None`` when the class is unknown, does not declare the field, or
    declares it as required (a required field has no default to stand in
    for an absent key).
    """
    fields = getattr(config_cls, "model_fields", None) or {}
    declared = fields.get(field)
    if declared is None or declared.is_required():
        return None
    return declared.default


def _usable(value: Any) -> bool:
    """Whether a **non-None** value can be used as a resolved input.

    Callers do the ``is not None`` check themselves so the narrowing is
    visible to the type checker; this predicate answers only the second
    question.

    A non-positive number is unusable: every field served here is
    declared ``ge=1``, so such a config cannot train. Treating it as
    absent keeps the estimate finite instead of silently pricing a
    zero-sized attention term — while an explicit ``None`` is likewise
    treated as absent rather than as a crash, because a refused estimate
    at planning time becomes a rejected candidate (C3's precedent).

    ``bool`` is excluded deliberately: ``True`` is an ``int`` in Python
    and is not a segmentation size.
    """
    return not (isinstance(value, int | float) and not isinstance(value, bool) and value <= 0)


def resolve_model_field(
    model_type: str,
    model_config: dict[str, Any],
    field: str,
    *,
    safety_margin: int,
) -> int:
    """Resolve a model-config input the way the model itself will resolve it.

    V21 PR B1. The resolution order is the one the *production run*
    already follows, and that is the whole point:

    ```text
    caller's dict          the explicit value, including one equal to the default
    config class default   what Pydantic will substitute for the absent key
    safety_margin          only when nothing declares the field
    ```

    **Why the class default is canonical, proven rather than assumed.**
    ``estimate_wall_time_seconds`` already calls ``_count_params`` →
    ``config_cls(**model_config)``, so Pydantic resolves the *same absent
    key* to the class default in the *same call* in which ``.get()``
    resolved it to a literal. Before B1 the function contradicted itself:
    the model whose parameters were counted at ``seg=40000`` had its steps
    priced at ``seg=1000``. See the PR B design doc §0.6.6.

    ``safety_margin`` is reached only for a model whose config class
    declares nothing — a generated plugin, typically. It is deliberately
    **phase-specific** and is a margin, NOT a claim about the model's
    default: memory is conservative when ``seg`` is over-stated, wall
    time when it is under-stated, so the two phases pass opposite values.
    Forcing them equal would necessarily make one phase more optimistic.
    """
    supplied = model_config.get(field)
    if supplied is not None and _usable(supplied):
        return int(supplied)

    from ml_models.models_format_sandbox import get_config_class

    declared = _declared_default(get_config_class(model_type), field)
    if declared is not None and _usable(declared):
        return int(declared)
    return safety_margin


class SegmentationDimensionUnavailableError(ValueError):
    """A legacy temporal analytic consumer lacks required task geometry."""


def require_declared_segmentation_size(
    model_type: str, model_config: dict[str, Any], *, consumer: str
) -> int:
    """Resolve a temporal size or refuse without inventing one."""
    supplied = model_config.get("segmentation_size")
    if supplied is not None and not _usable(supplied):
        raise ValueError(
            f"{consumer} received invalid segmentation_size={supplied!r}; "
            "explicit invalidity cannot be treated as absence."
        )
    resolved = resolve_optional_segmentation_size(model_type, model_config)
    if resolved is None:
        raise SegmentationDimensionUnavailableError(
            f"{consumer} requires a declared temporal segmentation_size; "
            "the task omitted it. Use the task-owned scope/probe interface "
            "for fixed-shape inputs."
        )
    return resolved


def resolve_optional_segmentation_size(model_type: str, model_config: dict[str, Any]) -> int | None:
    """Resolve a declared segmentation size without inventing a fallback.

    Unlike :func:`resolve_model_field`, this resolver has no safety margin.
    ``None`` is meaningful: callers may use a task-owned concrete probe that
    does not have a temporal axis.  It must never be replaced by tensor width
    or a historical task constant.
    """
    supplied = model_config.get("segmentation_size")
    if supplied is not None and _usable(supplied):
        return int(supplied)

    from ml_models.models_format_sandbox import get_config_class

    declared = _declared_default(get_config_class(model_type), "segmentation_size")
    if declared is not None and _usable(declared):
        return int(declared)
    return None


def resolve_train_field(train_config: dict[str, Any], field: str, *, safety_margin: int) -> int:
    """``resolve_model_field`` for the training config.

    Same contract, against ``TrainConfig`` — the class
    ``sandbox_executor`` and ``train_engine_sandbox`` build from this
    very dict, so its declared default is what an absent key will
    actually run as.
    """
    supplied = train_config.get(field)
    if supplied is not None and _usable(supplied):
        return int(supplied)

    from ml_models.models_format_sandbox import TrainConfig

    declared = _declared_default(TrainConfig, field)
    if declared is not None and _usable(declared):
        return int(declared)
    return safety_margin


def resolve_loss_type(loss_config: dict[str, Any]) -> LossTypeName:
    """The loss the run will actually use, for an absent ``loss_type``.

    V21 PR B1, closing the last member of the config-default vs
    estimator-fallback class found by the §22 final audit.
    ``LossConfig`` declares ``"focal"``; every estimator substituted
    ``"ce"``, so a plan omitting the key was priced — and warmed up — for
    a different loss than the one it would train with.

    Reachable at three sites, not merely latent: the warm-up builds the
    real criterion and the real model from this value
    (``evaluate_time_skill/wrapper.py:385``), and ``fcnet``'s head shape
    depends on it, so both the measured ms/step and the parameter count
    were being taken for the wrong configuration.

    Direction: ``"focal"`` adds the ``[B, 256, T] × 8 B`` one-hot term to
    the memory estimate that ``"ce"`` omits, so the correction is the
    conservative one.

    The literal ``"ce"`` remains only as a last-resort margin for the
    case where ``LossConfig`` declares nothing — it is a margin, not a
    claim about the default.
    """
    supplied = loss_config.get("loss_type")
    for name in _LEGAL_LOSS_TYPES:
        if supplied == name:
            return name

    from ml_models.models_format_sandbox import LossConfig

    declared = _declared_default(LossConfig, "loss_type")
    for name in _LEGAL_LOSS_TYPES:
        if declared == name:
            return name
    return "ce"


def attention_shape(model_type: str, model_config: dict[str, Any]) -> tuple[int, int] | None:
    """``(nhead, num_layers)`` if the architecture has attention, else ``None``.

    V21 PR C3 — replaces ``if model_type == "transformer"`` in both the
    training and inference estimators. The attention term models the
    ``[B, nhead, T, T]`` score matrices, which exist iff the architecture
    HAS attention, so the truthful predicate is whether the model declares
    attention parameters.

    **Why the config CLASS is consulted and not only the passed dict.** A
    first attempt read ``model_config.get("nhead")`` alone and silently
    dropped the attention term whenever a caller passed a partial dict —
    the old code used ``.get("nhead", 2)`` and so still charged for
    attention. That made the estimate *more optimistic* for a built-in
    transformer, which is the one direction an estimator must never move
    by accident. It was caught by the built-in parity capture, not by a
    unit test, which is why that capture exists.

    So the *declaration* comes from the class and the *value* from the
    caller: a model whose config class declares ``nhead`` has attention even
    if this particular dict omits it.

    **FU-C-1, closed by V21 PR B1.** C3 deliberately pinned the
    omitted-value fallback at the pre-C3 literal ``2`` while
    ``TransformerConfig`` declares ``nhead=4`` — a 2× under-count of
    built-in transformer attention whenever the dict omits the key
    (536,592,000 → 1,048,592,000 bytes at the parity fixture's shape).
    Correcting a calibrated built-in estimate needed operator approval,
    which Q-B-2 granted. The value now comes from the declaration.

    B1's audit also established that this correction is **latent**: the
    only callers of ``attention_shape`` are the two ``estimate_peak_bytes``
    functions, and neither has had a production caller since commit
    ``8b6c4ba8`` replaced the analytic VRAM estimate with a probe. The
    under-count was real arithmetic that reached no admission decision.
    See the PR B design doc §0.6.2.

    Returns ``None`` for the five non-attention built-ins and for any
    generated model that declares no attention parameters.
    """
    from ml_models.models_format_sandbox import get_config_class

    declares_attention = "nhead" in model_config
    if not declares_attention:
        config_cls = get_config_class(model_type)
        fields = getattr(config_cls, "model_fields", None) or {}
        declares_attention = "nhead" in fields

    if not declares_attention:
        return None

    # Safety margins apply only to a model declaring `nhead` with no
    # class-level default — a generated attention plugin. They keep the
    # pre-B1 literals, now honestly labelled as margins rather than as
    # "the model default".
    nhead = resolve_model_field(model_type, model_config, "nhead", safety_margin=2)
    num_layers = resolve_model_field(model_type, model_config, "num_layers", safety_margin=2)
    return nhead, num_layers


def _instantiate_for_param_count(model_type: str, config_obj: Any, loss_type: str) -> Any:
    """Build a model purely to count parameters.

    V21 PR C3 replaced ``if model_type == "fcnet"`` here with signature
    introspection. Step 07 / PR 07c C3 (Q-07c-3) PROMOTED that introspection
    to ``ml_models.models_sandbox.construct_registered_model``, beside the
    registry it reads, because the pre-phase measurement worker needed the
    same answer and was still carrying the name branch. This function keeps
    its name and its own responsibility — building a model purely to count
    parameters — and delegates the construction rule.
    """
    from ml_models.models_sandbox import construct_registered_model

    return construct_registered_model(model_type, config_obj, loss_type=loss_type)


# Safety margin applied on top of ms/step. Raised from 1.1 to 2.0 for the
# static fallback path (Phase 6.8 §4.2): the original 1.1 was calibrated for
# warmup variance (~10%), but the static formula itself is 2-5x wrong for novel
# architectures, so the multiplier must absorb formula error, not just variance.
# Recalibrated 2026-04-30 from 2.0 → 1.3: V7 empirical data shows the warmup-
# measured ms/step path is consistently 1.7-3× over actual training time, and
# the 2.0 multiplier was causing the gate to skip configs that would have fit.
# 1.3 keeps a margin for warmup variance without compounding the formula's
# structural over-prediction. It is a CONFIGURED margin: the 2026-08-03
# removal of historical scaling deliberately did not touch it, because
# removing history is not removing safety.
SAFETY_MULTIPLIER: float = 1.3

# Static ms/step fallback used when the aggregator cannot supply a warmup-
# measured ms_per_step (CPU-only hosts, unit tests, failed warmup).
# Raised from 6e-10 to 3e-9 (Phase 6.8 §4.2): the original coefficient was
# calibrated on seed models (punet, wavenet) with efficient GPU utilisation;
# novel architectures (dilated conv, SSM scans, multi-rate upsampling) are
# 3-5x less efficient per FLOP.
_STATIC_MS_PER_FLOP: float = 3e-9

# Minimum ms/step floor (Phase 6.8 §4.2): CUDA kernel launch + synchronisation
# + DataLoader fetch cost ~1-3 ms per step regardless of model size. Without
# this floor, tiny models get sub-millisecond estimates that undercount the
# fixed overhead by 10-100x.
#
# RT1 rev 4 (docs/design/runtime_estimation_and_watchdog.md §1): the static
# formula is a PRELIMINARY RISK SCREEN only — its output is stamped
# ``formal_execution_eligible: False``. The 2026-07-23 V18 incident measured
# 44.3 ms/step where this path priced 2.00 ms/step (22x under): per-step
# overhead is environment-specific (GPU, driver, torch version, sync
# behaviour, batch/seg regime) and MUST NOT be a hardcoded constant. The
# final runtime prediction for formal execution comes exclusively from an
# adaptive warm-up measurement of the actual configuration (RT2); no
# silent static fallback is permitted on formal paths.
_MIN_MS_PER_STEP: float = 2.0


# ── VRAM ─────────────────────────────────────────────────────────────────────


def estimate_peak_bytes(
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    loss_config: dict[str, Any],
    num_params: int,
) -> dict[str, Any]:
    """Estimate peak training-phase VRAM for the given config.

    Worst-case float32 training memory:

      * ``num_params × 16 B``   (weights 4 + grads 4 + Adam m 4 + v 4)
      * output logits            (B × 256 × T × 4)
      * backward activations     (~2 × output_logits; 1× for fcnet)
      * focal one_hot            (B × 256 × T × 8; focal loss only)
      * transformer attention    (B × nhead × T² × 4 × num_layers; transformer only)

    Args:
        model_type:   Model architecture key (e.g. ``"rnn"``, ``"transformer"``).
        model_config: Model configuration dict (``segmentation_size`` etc.).
        train_config: Training configuration dict (``batch_size`` etc.).
        loss_config:  Loss configuration dict (``loss_type``).
        num_params:   Exact parameter count from a prior CPU instantiation.

    Returns:
        ``{"phase": "training", "total_bytes": int, "breakdown": {...}}``.
    """
    # V21 PR B1 — resolved against the model's own declaration. The
    # margin is the memory-conservative direction (a larger `seg` costs
    # more), and applies only where nothing declares the field.
    seg_size = require_declared_segmentation_size(
        model_type, model_config, consumer="training peak-memory estimator"
    )
    batch_size = train_config.get("batch_size", 1)  # B1: matches TrainConfig's declared 1
    loss_type = resolve_loss_type(loss_config)

    # weights (4) + grads (4) + Adam m (4) + Adam v (4) = 16 bytes per param.
    model_overhead = num_params * 16 * _BYTES_F32 // 4

    output_logits = batch_size * 256 * seg_size * _BYTES_F32

    # V21 PR C3 — the branch this replaced read ``1 if model_type == "fcnet"
    # else 2``. The name was standing in for the model's OUTPUT CONTRACT:
    # ``fcnet`` is the only "hybrid" model, and it stores one activation
    # tensor rather than two because its head adapts to the loss. Asking the
    # contract directly is the same question without the hardcoded name, and
    # it is byte-identical for all six built-ins (fcnet is hybrid, the other
    # five are classifiers).
    act_factor = 1 if _output_contract(model_type) == "hybrid" else 2
    activations = act_factor * output_logits

    # I16 — focal one_hot allocation also covers classifier-style custom
    # losses (e.g. EMD / ordinal) that build ``F.one_hot(targets, 256)``
    # internally. Detection: ``loss_type == "custom"`` AND the plugin
    # declares ``PLUGIN_LOSS_TARGET_DTYPE = "long"`` (the classifier
    # contract). A pre-flight before the loss plugin is registered
    # (e.g. proposer-side estimation) falls back to the helper's
    # ``"long"`` default — over-counts a regressor custom loss by one
    # ``[B, 256, T] × 8 B`` chunk, which is the safe direction.
    from ml_models.loss_models_sandbox import get_target_torch_dtype
    from ml_models.models_format_sandbox import LossConfig

    loss_name = loss_config.get("loss_name")
    try:
        _cfg = LossConfig(
            loss_type=loss_type, loss_name=loss_name if loss_type == "custom" else None
        )
        _uses_long_targets = get_target_torch_dtype(_cfg) == torch.long
    except Exception:
        # If LossConfig validation fails (malformed dict), assume the
        # classifier contract for the estimate — safe over-count.
        _uses_long_targets = True
    _one_hot_loss = loss_type == "focal" or (loss_type == "custom" and _uses_long_targets)
    focal_onehot = batch_size * 256 * seg_size * _BYTES_I64 if _one_hot_loss else 0

    # V21 PR C3 — the branch this replaced read ``if model_type ==
    # "transformer"``. The term models the attention matrices, which exist
    # iff the architecture HAS attention, so the truthful predicate is
    # whether the model's own config declares attention parameters.
    #
    # Built-in parity: ``transformer`` is the only built-in declaring
    # ``nhead``, so all six estimates are unchanged.
    #
    # Direction of change for generated models: strictly MORE conservative.
    # Before, an agent-invented attention model was not named "transformer"
    # and so received a **zero** attention term — an optimistic estimate
    # that could admit a candidate which then OOMs. It can now only gain the
    # term, never lose it.
    transformer_attn = 0
    _attn = attention_shape(model_type, model_config)
    if _attn is not None:
        nhead, num_layers = _attn
        transformer_attn = batch_size * nhead * seg_size * seg_size * _BYTES_F32 * num_layers

    total = model_overhead + output_logits + activations + focal_onehot + transformer_attn

    return {
        "phase": "training",
        "total_bytes": total,
        "breakdown": {
            "model_overhead_bytes": model_overhead,
            "output_logits_bytes": output_logits,
            "activations_bytes": activations,
            "focal_onehot_bytes": focal_onehot,
            "transformer_attn_bytes": transformer_attn,
        },
    }


# ── Wall time ────────────────────────────────────────────────────────────────


def _total_train_steps(
    sample_set: dict[str, list[int]],
    seg_size: int,
    batch_size: int,
    train_portion: float | None,
    epochs: int,
    profile: DatasetProfile,
    *,
    drop_last: bool = True,
) -> int:
    """Total fwd+bwd step count across the whole training run.

    RT1 step-count resolver: mirrors the trainer's realized step math
    exactly (per-file ``max(1, round(portion × n))`` subsample +
    ``drop_last`` floor). RT2-A colocated the authoritative math with
    the production engine — this delegates to
    ``execute_tools.workload_resolvers.resolve_training_workload`` so
    there is exactly ONE resolver (§1.2 of the runtime-control design).
    """
    from execute_tools.workload_resolvers import resolve_training_workload

    return resolve_training_workload(
        sample_set,
        seg_size=seg_size,
        profile=profile,
        batch_size=batch_size,
        train_portion=train_portion,
        epochs=epochs,
        drop_last=drop_last,
    ).unit_count


def _static_ms_per_step(num_params: int, seg_size: int, batch_size: int) -> float:
    """Coarse static estimate of ms per training step — uncalibrated prior.

    Order-of-magnitude only; known to underestimate sync-bound tiny-batch
    regimes by >20x (V18 incident). Serves as a cheap preliminary risk
    screen and warm-up-safety check — NEVER as the final runtime
    prediction for formal execution (rev 4 contract; the caller must
    check ``formal_execution_eligible`` on the breakdown).
    """
    return max(num_params * seg_size * batch_size * _STATIC_MS_PER_FLOP, _MIN_MS_PER_STEP)


def _count_params(model_type: str, model_config: dict, loss_type: str) -> int:
    """Instantiate the model on CPU to get an exact parameter count.

    Module-level so tests can monkeypatch it without importing torch, and
    so the aggregator (commit 6) can pre-compute and pass ``num_params``
    to both ``estimate_peak_bytes`` and ``estimate_wall_time_seconds``
    without duplicating the instantiation.
    """
    from ml_models.models_format_sandbox import get_config_class

    config_cls = get_config_class(model_type)
    if config_cls is None:
        raise ValueError(
            f"_count_params: unknown model_type={model_type!r} — "
            f"get_config_class returned None (no plugin or built-in config registered)."
        )
    config_obj = config_cls(**model_config)
    model = _instantiate_for_param_count(model_type, config_obj, loss_type)
    return sum(p.numel() for p in model.parameters())


def estimate_wall_time_seconds(
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    sample_set: dict[str, list[int]],
    *,
    train_portion: float = 1.0,
    ms_per_step: float | None = None,
    gpu_name: str | None = None,
    num_params: int | None = None,
    loss_type: str = "ce",
    dataset_profile: DatasetProfile,
) -> dict[str, Any]:
    """Estimate training-phase wall-time in seconds.

    Computes ``total_steps × ms/step × SAFETY_MULTIPLIER``.

    This was ``total_steps × ms/step × k(gpu, model_type) ×
    SAFETY_MULTIPLIER`` until 2026-08-03, when the operator removed the
    historical ``k`` so the current live measurement is the sole runtime
    evidence in the production time decision.

    Args:
        ms_per_step:   Warmup-measured ms per fwd+bwd step — the live
                       measurement, and the only runtime evidence used.
                       ``None`` → static prior (``max(params × seg × bs ×
                       _STATIC_MS_PER_FLOP, _MIN_MS_PER_STEP)``) stamped
                       ``formal_execution_eligible: False`` (rev 4). There is
                       deliberately NO historical fallback.
        gpu_name:      CUDA device name (e.g. ``"NVIDIA RTX 5090"``). Recorded
                       in the breakdown for provenance only — it no longer
                       selects a historical correction and does not affect the
                       returned seconds.
        num_params:    Exact parameter count. Needed only when ``ms_per_step``
                       is ``None`` (static fallback). If not provided, the
                       model is instantiated internally via ``_count_params``.
        loss_type:     Only used by the optional internal ``_count_params`` for
                       ``fcnet`` (which takes ``loss_type`` at construction).
        dataset_profile: the RUN-BOUND Dataset Profile (Step 05b). Required:
                       the step count depends on the decomposition geometry,
                       and resolving it here would price the run against
                       whatever singleton happened to be bound rather than
                       against the topology this run declared.

    Returns:
        ``{"phase": "training", "seconds": float, "breakdown": {...}}``.
    """
    # V21 PR B1. Both were resolved against literals that contradicted the
    # declarations this same function instantiates the model from:
    #
    #   segmentation_size  1000 vs the class default (40000, or 20000 for
    #                      transformer) — neutral-to-40x CONSERVATIVE, never
    #                      optimistic (design doc §0.6.3)
    #   epochs             1 vs TrainConfig's declared 10 — a 10x OPTIMISTIC
    #                      forecast, linear in epochs with nothing to cancel
    #                      it, and the one active optimistic defect in this
    #                      class (§0.6.4)
    #
    # The margin here is the time-conservative direction (a smaller `seg`
    # means more steps), opposite to the VRAM phase's, and is reached only
    # for a model whose config class declares nothing.
    seg_size = require_declared_segmentation_size(
        model_type, model_config, consumer="training wall-time estimator"
    )
    batch_size = int(train_config.get("batch_size", 1))
    epochs = resolve_train_field(train_config, "epochs", safety_margin=1)

    total_steps = _total_train_steps(
        sample_set,
        seg_size,
        batch_size,
        train_portion,
        epochs,
        dataset_profile,
        drop_last=resolve_training_drop_last(train_config),
    )

    if ms_per_step is not None and ms_per_step > 0:
        ms_source = "real_dataset_warmup"
    else:
        if num_params is None:
            num_params = _count_params(model_type, model_config, loss_type)
        ms_per_step = _static_ms_per_step(num_params, seg_size, batch_size)
        ms_source = "static_uncalibrated"

    # V20 PR C1, operator decision 2026-08-03: the current live measurement of
    # THIS candidate is the sole runtime evidence in the production time
    # decision. The legacy per-GPU historical `k` (an asymmetric EMA over past
    # runs) used to multiply in here; it is gone. Runtime depends on current
    # machine conditions, GPU contention and caching, so a stored correction
    # prices today's work with yesterday's clock.
    #
    # What REMAINS is configured policy, not history: SAFETY_MULTIPLIER is a
    # fixed operator-set margin, and the operator's time budget is applied by
    # the caller. Removing history does not mean removing safety.
    total_ms = total_steps * ms_per_step * SAFETY_MULTIPLIER
    seconds = total_ms / 1000.0

    return {
        "phase": "training",
        "seconds": seconds,
        "breakdown": {
            "total_train_steps": total_steps,
            "ms_per_step": round(ms_per_step, 4),
            "ms_source": ms_source,
            # rev 4 contract: only a measured (warm-up) step time may back
            # the runtime prediction that admits a formal execution. The
            # static prior is a risk screen — enforcement lands in RT2/RT3;
            # this field is the interface they consume.
            "formal_execution_eligible": ms_source == "real_dataset_warmup",
            # `k_correction` was removed, not pinned to 1.0. A field left at a
            # neutral value is a socket: it reads as "no correction applied
            # today" and invites one tomorrow. Its absence is the contract.
            "safety_multiplier": SAFETY_MULTIPLIER,
            "gpu_name": gpu_name,
        },
    }
