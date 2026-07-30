# O1a + O2 — Operator Tooling: Runtime Hardware Provenance and Selective Chain Launching

- **Status**: IMPLEMENTED (2026-07-29) — design approved by the
  operator same day (recommended options confirmed: duplicates
  rejected; canonical order; queue runner excluded; driver probe
  included; CPU/RAM extras skipped); validation evidence in §6.
  PR merge pending operator review.
- **Parent**: `../v19_priorities.md` §3 items 1a (O1a) and 2 (O2) +
  §2.0 parallel operational track. Both are deterministic,
  non-agent-behavior operator-tooling items; neither blocks V19
  required-scope completion (PR 1-3).
- **Branch**: `feat/v19-operator-provenance-launch-selection` (from
  post-PR#145 master).
- **Shared constraints (binding)**: no agent prompt changes; no
  HealthGate changes; no scoring changes; no training-policy changes;
  no default-behavior change when the new options are absent; no
  unrelated infrastructure redesign; no real LLM or training in
  validation (pseudo/deterministic only).

## 1. O1a — run-level runtime/hardware provenance (recording-only)

### 1.1 Existing-provenance inventory (audit 2026-07-29, code-traced)

| Source | Type | Level | Fields | Notes |
|---|---|---|---|---|
| `core/hardware_context.py::HardwareContext` | **typed (Pydantic, frozen)** | **run-level**, canonical manifest `{workspace}/{run_name}_hardware.json` | `device_name`, `total_memory_bytes`, `compute_capability`, `multiprocessor_count`, `cuda_runtime_version`, `torch_version`, `hostname`, `device_available`, `discovered_at` | self-declared "single source of truth for every physical-device lookup"; cross-process IPC for sandbox subprocesses; `get_or_create` regenerates on host/device mismatch (workspace-move path); **device 0 only** |
| `core/runtime_control/provenance.py::capture_environment_provenance` | dict | **per-observation** (runtime-control setup measurements) | hostname, platform, python, torch, cuda, gpu_name(0), timestamp | best-effort, degrades to None; sample-level context for P/M/A records — NOT a run manifest |
| `agent/schemas/run_metadata.py::EnvInfo` | typed | run-metadata record | `gpu_name` (+ git info in `GitInfo`) | summary-level |
| `scripts/run_comparison.py` | ad-hoc | script log | `nvidia-smi --query-gpu=driver_version,name,memory.total` | the repo's existing driver-version precedent (scripts only) |
| `core/run_invariants.py` | — | — | no hardware fields | hardware is deliberately NOT an invariant |

Answers to the audit questions: recording exists and is typed at run
level (HardwareContext) but is single-device and misses driver /
`CUDA_VISIBLE_DEVICES` / platform / python / repo commit / error
status; GPU info is available via PyTorch (always, when CUDA present)
and nvidia-smi (driver version only — optional); collection happens
once per run at manifest creation (correct granularity — stable facts,
not live monitoring); the runtime-control per-observation dict is the
transient-context channel and stays as is; provenance is NOT locked in
run invariants and must not be — `get_or_create`'s documented
workspace-move regeneration is the intended behavior, and locking
hardware would break legitimate server moves (recorded decision).

### 1.2 Design — EXTEND the existing canonical schema (no new artifact)

One canonical source, per the module's own principle: extend
`HardwareContext` with **optional, defaulted, typed** fields (old
manifests keep loading; regeneration policy unchanged; the existing 9
fields and the VRAM-cap property are untouched):

```python
class GpuDeviceProvenance(BaseModel):        # new, frozen
    logical_index: int                        # deterministic order key
    name: str
    total_memory_bytes: int
    compute_capability: tuple[int, int]

class HardwareContext(BaseModel):             # existing + new optional fields
    ...existing 9 fields unchanged...
    platform: str | None = None               # platform.platform()
    python_version: str | None = None
    cuda_visible_devices: str | None = None   # raw env value; None if unset
    visible_device_count: int | None = None
    devices: list[GpuDeviceProvenance] = []   # ALL visible devices, by logical index
    driver_version: str | None = None         # best-effort nvidia-smi, see 1.3
    repo_commit: str | None = None            # best-effort git rev-parse HEAD
    collection_errors: list[str] = []         # explicit per-probe failures
```

Location decision: **manifest only** (`{run_name}_hardware.json` — the
existing canonical artifact). No `runtime_provenance.json`, no
duplication into iteration manifests or run_config; `EnvInfo.gpu_name`
and the runtime-control dict remain as summaries/references. Stable
facts only — no utilization, temperature, power, or environment dumps;
no secrets (the only env var recorded is `CUDA_VISIBLE_DEVICES`, a
device-index list); no user paths beyond what the manifest already
implies.

### 1.3 Collection strategy (bounded best-effort)

Extend `discover()`: each new probe wrapped individually; any failure
appends `"{probe}: {error}"` to `collection_errors` and leaves the
field `None`/empty — **collection failure never aborts the run** and
never fabricates values. Probes: `platform`/`python` (stdlib, cannot
fail meaningfully); per-device loop over
`range(torch.cuda.device_count())` (deterministic logical order; under
`CUDA_VISIBLE_DEVICES` logical indices are the mapped subset — the raw
env value is recorded alongside so physical identity is recoverable);
`driver_version` via `nvidia-smi --query-gpu=driver_version
--format=csv,noheader` with a short timeout, first line, `None` on any
failure (missing binary, timeout, malformed output — NOT a blocking
dependency); `repo_commit` via `git rev-parse HEAD` with timeout,
`None` outside a repo. CPU-only: existing stub behavior +
`devices=[]`, `visible_device_count=0`, new fields still populated
where meaningful. No repeated probing: `discover()` is already
called once per manifest lifecycle.

### 1.4 Compatibility and tests

Old manifests load (new fields defaulted) — regression test with a
committed pre-extension fixture. Mismatch-regeneration semantics
unchanged (still keyed on `device_name` + `hostname` only — new fields
never trigger regeneration; recorded decision). Tests (all
deterministic, mocked `torch.cuda`/subprocess): single GPU; multi-GPU
deterministic ordering; CPU-only; CUDA unavailable; nvidia-smi
missing/timeout/malformed; `CUDA_VISIBLE_DEVICES` set/unset;
`collection_errors` populated on induced failure without abort; stable
JSON serialization round-trip; backward-compat load; no-secret-env
scan (only the one whitelisted env var appears in the dump);
`test_no_hardcoded_device_literals` still green.

## 2. O2 — selective chain launching (`--only`)

### 2.1 Audit (2026-07-29, code-traced)

- **Launched unit: CHAINS (`run_name`s), not models/tasks.**
  `launch_v18_wave1.sh {1a|1b}` launches a fixed per-phase ROSTER
  (bash array `"run_name:scope:files:flavor"`, 2 chains per phase);
  this matches the locked O2 definition in `v19_priorities.md` §3
  item 2 (motivating incident: the Wave-1A loss restart needed a
  hand-mirrored `run_chain.sh` command because one chain of a pair
  could not be relaunched alone). The `--only fcnet`-style
  model-selection reading does not match the audited launcher — model
  sets are a different surface (`run_all_models*.sh` groups), out of
  O2 scope.
- **Canonical ordered list**: the `WAVE1A`/`WAVE1B` arrays in the
  launcher itself. Existing selectors: the phase argument only, plus
  `--dry-run` and the `V18_RESUME` env gate. No internal name filter
  exists.
- **`v18r_queue_runner.sh`** has a separate `QUEUE` array with
  index-file progress (`next_index`); name-selection there would
  interact with the index bookkeeping. **Scope decision: O2 targets
  `launch_v18_wave1.sh` only** (the documented pain point); a
  queue-runner selector is recorded as a possible follow-up, not
  designed here.
- **Manifest/invariants/resume**: the launcher writes no manifest;
  each chain's workspace, run-invariants lock, and resume semantics
  are per-chain and UNAFFECTED by which chains the launcher starts.
  Launch selection is operational, not scientific scope → **not a
  run-invariants item; no resume interaction beyond the existing
  per-workspace `V18_RESUME` rule.** The resolved selection is echoed
  in the launch output (the launcher's only record surface) and each
  launched chain's own artifacts identify it fully.

### 2.2 Design

Syntax: `launch_v18_wave1.sh {1a|1b} [--only <name[,name...]>]
[--dry-run]` (order-independent flags).

Rules (side-effect-free `filter_roster()` function in
`_chain_common.sh`, directly testable without GPU/screen/launch):

- omitted `--only` → the full phase roster, byte-identical prior
  behavior;
- names are matched against the ACTIVE PHASE's roster run_names;
  unknown names **fail before any launch**, listing the valid names;
- empty selection (empty string, only commas/whitespace, or a filter
  that matches nothing) fails before any launch;
- duplicates are **rejected** with a clear error (not deduplicated —
  a duplicate is operator confusion worth surfacing);
- whitespace around names is trimmed;
- **canonical roster order is preserved** regardless of the order
  names were given (launch stagger and topology assumptions follow
  roster order; user-order override is rejected as a non-goal —
  presented as the recommended option, operator may override);
- the resolved selection is echoed as `[selection] ...` before
  preflight, and no hidden fallback to "all" exists on any error
  path;
- shell behavior is the only behavior (the launcher is pure bash; no
  Python CLI twin exists for this surface — parity requirement is
  N/A, recorded).

### 2.3 Tests

Pytest-driven bash tests (pattern: existing shell-consistency tests),
invoking `filter_roster()` by sourcing `_chain_common.sh` — no GPU, no
screen, no launch: omitted (identity, order); one name; both names in
reverse order (canonical order preserved); unknown name (fails, lists
valid names); empty / whitespace-only (fails); duplicate (fails);
plus a launcher-level `--dry-run` argument-parsing test where
environment permits, and a grep-level guard that the non-`--only`
invocation path is unchanged.

## 3. Proposed commits (natural boundaries from the audit)

```text
OA — docs(v19): design runtime provenance and selective launching   (this doc)
OB — feat(runtime): record run-level hardware provenance            (schema + collector + tests)
OC — feat(launcher): add selective --only launch filtering          (filter_roster + launcher + tests)
OD — docs(v19): document provenance and selective launch usage      (running_chain_test.md + launcher headers + tracker O1a/O2 checkpoints)
OV — test(v19): close O1a/O2 compatibility evidence                 (compatibility matrix + full-suite record; may fold into OD if trivial)
```

## 4. Deterministic validation plan

Focused: new O1a/O2 tests + `tests/unit/core/test_hardware_context.py`
+ hardware-context consumers (`tune_ml_hyperparam_agent`,
`ml_model_proposal_agent` hardware-block tests) + shell-consistency
suite + run-invariants/resume suites (prove untouched). Then the full
unit suite, relevant pseudo integrations, `ruff check .` +
`ruff format --check .` (pyright via CI). Compatibility matrix
(operator §11): no GPU → run continues with explicit unavailable
provenance; one GPU → correct typed record; multi-GPU → deterministic
device records; no `--only` → exact old launch set; valid subset →
only selected chains; invalid name → fail before execution; resume
semantics unchanged (per-workspace, selection-independent — recorded
as N/A rather than a new rejection surface).

## 5. Unresolved options for the operator

1. **O2 duplicate handling**: reject (recommended, designed above) vs
   deduplicate.
2. **O2 ordering**: canonical roster order (recommended) vs
   user-specified order.
3. **O2 queue-runner selector**: excluded from this PR (recommended)
   vs included despite the index-progress interaction.
4. **O1a driver probe**: include the bounded nvidia-smi driver lookup
   (recommended; precedent in `run_comparison.py`) vs PyTorch-only.
5. **O1a optional extras**: CPU model / total RAM — cheap via
   `platform`/`/proc/meminfo`; include or skip (default: skip unless
   requested).

## 6. OV — final validation evidence (2026-07-29)

Commits: OA `d6cb0c2` (design) → OB `ab339ea` (O1a provenance) → OC
`4b3f469` (O2 selection) → OD `c16e405` (operator docs + tracker) →
OV (this record). Branch `feat/v19-operator-provenance-launch-selection`
from post-PR#145 master `e3b75ce`.

- Focused: hardware-context suite 19 passed (incl. 9 new provenance
  tests); O2 selection suite 13 passed; core + hardware-context
  consumers 1206 passed; shell-parity + sdsc suites 131 passed.
- Full unit suite: **4692 passed, 4 xfailed** (pre-existing), 3:44.
- Pseudo integration (affected surface, zero-LLM):
  tests/integration/execute_tools 64 passed.
- Static: `ruff check .` + `ruff format --check .` clean (544 files);
  strict pyright via CI on the pushed head (source of truth).
- One defect caught and fixed during implementation: sourcing
  `_chain_common.sh` after flag parsing would have let the library's
  plain-assignment `DRY_RUN=0` clobber the parsed flag — the source
  now precedes parsing (commit OC message records it).

### Compatibility matrix

| Condition | Expected behavior | Test evidence | Result |
|---|---|---|---|
| no GPU | run continues; explicit unavailable provenance (devices=[], count=0, driver None — not probed) | `test_provenance_cpu_only_explicit_unavailable` | ✅ |
| one GPU | correct typed record | `test_discover_on_fake_rtx_5090` + provenance suite | ✅ |
| multi-GPU | deterministic logical-index device records | `test_provenance_multi_gpu_deterministic_order` | ✅ |
| probe failure | recorded gap, never abort, never fabricate | nvidia-smi missing/malformed/nonzero + device-probe-failure tests | ✅ |
| pre-O1a manifest | loads with defaults; regeneration keys unchanged | `test_provenance_backward_compatible_manifest_load` | ✅ |
| no `--only` | exact old launch set, original order | `test_omitted_only_is_identity_in_order` | ✅ |
| valid subset | only selected chains, canonical order | single/reversed/all-names tests | ✅ |
| invalid name / duplicate / blank | fail before execution, valid names listed, no fallback | filter + launcher error-path tests (pre-preflight) | ✅ |
| resume | unchanged — selection is operational, not workspace scope (design §2.1) | shell-parity + sdsc suites green; no invariants surface touched | ✅ (N/A by design) |
