"""Production executors + profile collection for the bounded probe (C6b).

Everything here touches heavy subsystems (torch, CUDA, the plugin
registry, the real dataset) and is therefore:

* imported lazily inside functions (no module-level heavy imports; the
  core layering rule from C4 applies);
* exercised for real ONLY in the operator-gated GPU smoke and the C12
  campaign — unit tests use the injected fakes of ``probe.py``.

F-1b: ``setup`` loads the ACTUAL implemented candidate from the LIVE
``MODEL_REGISTRY`` (the validator has just registered it) and recomputes
realized properties from the instantiated module — the LLM-authored
parameter estimate is never used here.

F-1a: the probe batch comes from the REAL dataset resolved through the
single source of truth (``execute_tools.data_paths.TIDMAD_DATA_DIR``)
when no explicit ``data_dir`` is given. A missing/unreadable dataset is
an explicit ``load_failure`` — never a silent synthetic fallback.
"""

from __future__ import annotations

from typing import Any

from core.runtime_control.probe import ProbeExecutors, RealizedModelProperties
from core.runtime_control.registry_schemas import (
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
)

_DTYPE_BYTES = {"float32": 4, "float16": 2, "bfloat16": 2, "float64": 8}


def collect_hardware_compatibility_profile() -> HardwareCompatibilityProfile:
    """§9.1 profile from the live environment (no hostname)."""
    import platform  # noqa: F401  (documents intent: platform NOT included)

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("hardware profile collection requires CUDA")
    props = torch.cuda.get_device_properties(0)
    cc = torch.cuda.get_device_capability(0)
    dtypes = ["float32", "float16"]
    if torch.cuda.is_bf16_supported():
        dtypes.append("bfloat16")
    return HardwareCompatibilityProfile(
        accelerator_vendor="NVIDIA",
        accelerator_model=props.name,
        gpu_count=torch.cuda.device_count(),
        vram_gb=props.total_memory / 2**30,
        compute_capability=f"{cc[0]}.{cc[1]}",
        driver_version=None,  # not exposed via torch; nvidia-smi optional
        cuda_version=torch.version.cuda,
        torch_version=torch.__version__,
        dtypes=tuple(sorted(dtypes)),
    )


def probe_device_vram_gb() -> float:
    """Total VRAM of the probe device — the D3 memory threshold input
    (``max(1 GiB, 10 % of VRAM)``). Raises rather than guessing: a probe
    that cannot see its device cannot classify contention (C8e)."""
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "device VRAM is required to classify contention (D3) and CUDA is "
            "unavailable — the caller must supply it explicitly"
        )
    return torch.cuda.get_device_properties(0).total_memory / 2**30


def collect_execution_environment_profile(
    *,
    installation_id: str,
    hardware_compatibility_id: str,
    concurrency_regime: str | None = None,
) -> ExecutionEnvironmentProfile:
    import os

    import psutil  # type: ignore[import-untyped]

    return ExecutionEnvironmentProfile(
        hardware_compatibility_id=hardware_compatibility_id,
        installation_id=installation_id,
        cpu_count=os.cpu_count(),
        ram_gb=psutil.virtual_memory().total / 2**30,
        concurrency_regime=concurrency_regime,  # type: ignore[arg-type]
    )


def production_probe_executors(
    *,
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    loss_config: dict[str, Any],
    data_dir: str | None = None,
    device: str = "cuda",
) -> ProbeExecutors:
    """Real executors over the implemented candidate. All state lives in
    the closure; ``setup`` must run first (engine guarantees ordering)."""
    state: dict[str, Any] = {}

    def _setup() -> RealizedModelProperties:
        import torch

        from ml_models.models_format_sandbox import (
            LossConfig,
            TrainConfig,
            get_config_class,
        )
        from ml_models.models_sandbox import MODEL_REGISTRY  # live registry (F-1b)

        if model_type not in MODEL_REGISTRY:
            raise RuntimeError(
                f"model_type {model_type!r} is not in the live MODEL_REGISTRY — "
                "the probe must run AFTER validation/registration"
            )
        if device.startswith("cuda"):
            torch.cuda.reset_peak_memory_stats()
        config_cls = get_config_class(model_type)
        if config_cls is None:
            raise RuntimeError(f"no config class registered for {model_type!r}")
        cfg = config_cls(**model_config)
        model = MODEL_REGISTRY[model_type](cfg).to(device)
        n_params = sum(p.numel() for p in model.parameters())
        n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
        dtype = str(next(model.parameters()).dtype).replace("torch.", "")
        bytes_per = _DTYPE_BYTES.get(dtype, 4)

        # F-1a: real data through the single source of truth.
        resolved_dir = data_dir
        if not resolved_dir:
            from execute_tools.data_paths import TIDMAD_DATA_DIR

            resolved_dir = TIDMAD_DATA_DIR
        import os

        if not resolved_dir or not os.path.isdir(resolved_dir):
            raise RuntimeError(
                f"dataset directory unavailable for the probe: {resolved_dir!r} "
                "(no silent synthetic fallback — F-1a)"
            )
        seg = int(model_config.get("segmentation_size", 40_000))
        bs = int(train_config.get("batch_size", 1))
        from execute_tools.probe_data import load_probe_batch  # C6b helper

        batch = load_probe_batch(data_dir=resolved_dir, batch_size=bs, segment_length=seg).to(
            device
        )

        # Optimizer switch mirrors execute_tools/train_engine_sandbox.py
        # (§verified 2026-07-30: AdamW default w/ weight_decay, Adam, SGD).
        train_cfg = TrainConfig(**train_config)
        opt_type = getattr(train_cfg, "optimizer_type", "adamw")
        if opt_type == "adam":
            optimizer = torch.optim.Adam(model.parameters(), lr=train_cfg.lr)
        elif opt_type == "sgd":
            optimizer = torch.optim.SGD(model.parameters(), lr=train_cfg.lr)
        else:
            optimizer = torch.optim.AdamW(
                model.parameters(),
                lr=train_cfg.lr,
                weight_decay=getattr(train_cfg, "weight_decay", 0.0),
            )
        from ml_models.loss_models_sandbox import get_criterion

        state.update(
            model=model,
            batch=batch,
            optimizer=optimizer,
            loss_fn=get_criterion(LossConfig(**loss_config)),
            torch=torch,
        )
        return RealizedModelProperties(
            parameter_count=n_params,
            trainable_parameter_count=n_train,
            parameter_memory_gb=n_params * bytes_per / 2**30,
            dtype=dtype,
        )

    def _train_step() -> float:
        import time as _time

        torch = state["torch"]
        model, batch = state["model"], state["batch"]
        optimizer, loss_fn = state["optimizer"], state["loss_fn"]
        use_cuda = device.startswith("cuda")
        if use_cuda:
            torch.cuda.synchronize()
        t0 = _time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        logits = model(batch)
        loss = loss_fn(logits, batch)
        loss.backward()
        optimizer.step()
        if use_cuda:
            torch.cuda.synchronize()
        return (_time.perf_counter() - t0) * 1000.0

    def _inference_batch() -> float:
        import time as _time

        torch = state["torch"]
        model, batch = state["model"], state["batch"]
        use_cuda = device.startswith("cuda")
        if use_cuda:
            torch.cuda.synchronize()
        t0 = _time.perf_counter()
        with torch.no_grad():
            model(batch)
        if use_cuda:
            torch.cuda.synchronize()
        return (_time.perf_counter() - t0) * 1000.0

    def _peak_vram_gb() -> float | None:
        torch = state.get("torch")
        if torch is None or not device.startswith("cuda"):
            return None
        return float(torch.cuda.max_memory_allocated()) / 2**30 or None

    return ProbeExecutors(
        setup=_setup,
        train_step=_train_step,
        inference_batch=_inference_batch,
        peak_vram_gb=_peak_vram_gb,
    )
