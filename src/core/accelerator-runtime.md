# Accelerator runtime facts

Owner: `core.hardware_context`. This contract describes installed build facts
and fresh device observations. It grants no launch permission.

## Public report and effects

`inspect_gpu_runtime() -> GpuRuntimeFacts` returns a frozen, extra-forbid report:

| Field | Meaning |
| --- | --- |
| `installed_backend` | `rocm` when `torch.version.hip` is present, otherwise `cuda` when `torch.version.cuda` is present, otherwise `none` |
| `runtime_version` | Selected HIP or CUDA runtime build version; null without either backend |
| `hardware` | Fresh `HardwareContext` from the existing `discover()` owner |
| `implemented_accounting_adapter` | `nvidia-smi` for the CUDA implementation; null when no adapter is implemented |
| `limitations` | Explicit experimental, untested and missing-implementation boundaries |

`none` describes this PyTorch build, not the host's physical accelerator. A CUDA
build with inaccessible devices remains `cuda`, while
`hardware.device_available` is false. Neither state permits a CPU fallback.
HIP takes precedence because ROCm also exposes PyTorch's `torch.cuda` namespace.

The operation calls existing property and bounded provenance probes. It does
not allocate a tensor, synchronize a kernel, load a dataset/model, call an LLM,
read credentials or write a run manifest. Property-query failures propagate;
the caller must report them rather than substitute a fabricated report. It
never loads an old workspace manifest or creates a workspace.

## Identity and readiness

Visible devices follow PyTorch logical indices. NVIDIA UUID-to-physical-index
mapping remains UUID-based: a physical device remapped to logical zero is not
assumed to be physical zero. Arbitrary NVIDIA model names are accepted as facts.
These facts do not prove that installed kernels can execute that architecture.

ROCm discovery does not call NVIDIA driver probes or prefix an AMD identifier
with `GPU-`. Until a driver identity/accounting adapter exists, driver version,
UUID and physical mapping remain absent, with an explicit collection error.
The existing accounting identity adapter therefore returns no identity, rather
than treating an index or model name as one. Unknown is not an empty GPU.

An implemented adapter is not proof that its executable exists, the driver is
accessible, a sample is coherent or headroom is adequate. Existing measurement,
admission and runtime protection remain responsible for those checks. A caller
whose selected path requires an absent capability must refuse before scientific
or provider effects, naming the missing capability. Do not silently disable
protection or isolation to make a backend appear supported.

## Support and installation boundary

CUDA has a driver-accounting implementation; actual hardware qualification is
device/environment-specific. AMD/ROCm compatibility is experimental and has
not been hardware-tested. Its tensor API can expose properties, but protected
execution requiring driver/process accounting is not currently supported.
Intel GPU execution is not currently supported.

This report installs no software. Current frozen locks still select the CUDA
environment. A future explicit ROCm dependency selection must be reviewed and
locked in both infra and exp; neither a wheel substitution nor this report is
installation qualification. No ROCm installation command is supplied here.

## History and verification

`HardwareContext` fields, defaults and serialization are unchanged. Under fixed
inputs, CUDA discovery keeps the same complete serialized payload. Existing
workspace cache/matching rules are unchanged; the new report intentionally uses
fresh discovery. Historical configuration and input reconstruction remain
exp-owned, and an old manifest is not evidence of current hardware readiness.

Focused mocked tests cover logical mapping, HIP precedence, absent access,
no NVIDIA probe/identity fabrication on ROCm, fresh discovery, property failures,
no allocation/persistence and legacy CUDA payload parity. These are CPU tests,
not AMD or additional NVIDIA hardware qualification.
