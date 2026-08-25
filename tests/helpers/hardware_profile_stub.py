"""The GPU hardware-profile probe, stubbed — one authority for the unit layer.

WHY THIS EXISTS. ``core/runtime_control/probe_production.py`` reads the live
accelerator::

    if not torch.cuda.is_available():
        raise RuntimeError("hardware profile collection requires CUDA")

``_derive_calibration_from_observation`` calls it unconditionally on the way to
the calibration registry, so every test that exercises the derivation reaches
CUDA transitively. On a GPU developer box that is invisible; on the CPU-only CI
runner the collection raises, the derivation's own broad ``except`` degrades it
to ``[runtime_control] calibration derivation failed (non-fatal): hardware
profile collection requires CUDA``, and **nothing is ever written**.

That is worse than a plain failure. A test asserting "an eligible record WAS
exported" goes red — honest, if confusing. A test asserting "nothing was
exported" goes GREEN while the behaviour it guards never ran: the run wrote
nothing because the probe crashed, not because the guard refused. Both shapes
live side by side in the B5 falsifiers, so the CPU host turns half of them into
decoration.

Mocking rather than skipping is what the project rule requires — unit tests mock
every heavy subsystem (LLM, training, scoring, VRAM probe, hardware context) —
and it is the only option that keeps the falsifiers armed on the machine CI
actually runs on. A ``skipif(not torch.cuda.is_available())`` would disarm them
there permanently.

WHAT IS AND IS NOT STUBBED. Only the accelerator read. The registry, the
identity construction, the eligibility policy, the quarantine decision and the
on-disk write are all the real production code — those are the subjects under
test. ``collect_execution_environment_profile`` is left alone: it reads
``os.cpu_count()`` and ``psutil``, which work anywhere.
"""

from __future__ import annotations

from core.runtime_control.registry_schemas import HardwareCompatibilityProfile

#: A fixed, plausible accelerator. The values are arbitrary but must be
#: *stable*: ``profile_id`` is a content hash, so the whole calibration bucket
#: identity derives from these bytes. Changing them changes every bucket a test
#: writes — which is fine within one ``tmp_path`` registry, and exactly why no
#: test here may assert a hard-coded ``hardware_compatibility_id``.
STUB_HARDWARE_PROFILE = HardwareCompatibilityProfile(
    accelerator_vendor="NVIDIA",
    accelerator_model="STUB-GPU",
    gpu_count=1,
    vram_gb=32.0,
    compute_capability="12.0",
    driver_version=None,
    cuda_version="12.8",
    torch_version="stub",
    dtypes=("bfloat16", "float16", "float32"),
)


def stub_hardware_profile_collection(monkeypatch) -> HardwareCompatibilityProfile:
    """Patch the accelerator probe at the boundary production actually calls.

    ``_derive_calibration_from_observation`` imports
    ``collect_hardware_compatibility_profile`` *inside* its own body, so the
    name is resolved from the defining module at call time — patching the
    attribute on ``core.runtime_control.probe_production`` is therefore the one
    interception point that covers every consumer, present and future.

    Returns the profile the stub hands back, so a caller can assert against it.
    """
    from core.runtime_control import probe_production

    monkeypatch.setattr(
        probe_production,
        "collect_hardware_compatibility_profile",
        lambda: STUB_HARDWARE_PROFILE,
    )
    return STUB_HARDWARE_PROFILE
