# VRAM-estimation skill

run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py) is the callable entry;
its exact argument declaration is [skill_config.json](skill_config.json), with
details in [evaluate_vram_skill.md](evaluate_vram_skill.md). It coordinates a
bounded structural preflight and returns predicted peak allocation, feasibility,
and (when feasible) an inference batch. Optional run-bound model-I/O contract,
probe samples, hardware context and budget are caller-supplied.

The production adapter may spawn the isolated preflight worker and inspect GPU
memory; this is an effectful resource probe, not a driver-visible measurement
or cross-machine authority. It runs bounded model-forward probes for resource
estimates, not a full candidate training/inference job or scientific scoring.
Formal admission policy decides how evidence may gate.

To understand a refusal, inspect `preflight_outcome` and
`static_preflight_evidence` in the stored record's `memory` object. The latter
contains the tested phase and batch, the exact estimate and cap in bytes, and
any compute-intensity comparison. For example, a static estimate of 8 GiB
against a 5 GiB cap means the **estimate** failed the configured check; it does
not mean a GPU measurement observed 8 GiB. A compute-intensity refusal can have
no VRAM estimate at all.

The next planner and proposer receive that distinction. Completed static
refusals still skip training and permit another attempt; this change does not
make the estimator less conservative. Accepted candidates retain their existing
diagnostic estimates and selected inference batch, with decision evidence stored
separately. CPU-only bypasses and older records have no such evidence. See the
[evidence contract](evaluate_vram_skill.md#static-decision-evidence) for fields,
validation, and compatibility limits.

Named declared-package integrity failures are terminal configuration/dependency
refusals, not VRAM measurements or model-size feedback. The existing worker and
parent boundaries preserve this distinction; see
[task-code transport and limits](../../../core/local_code/README.md).

Focused seams include [test_wrapper_contract.py](../../../../tests/unit/agent/evaluate_vram_skill/test_wrapper_contract.py)
and adjacent isolated-probe/contract tests. GPU probing is not run by docs
checks; pseudo tests cover transport only.
