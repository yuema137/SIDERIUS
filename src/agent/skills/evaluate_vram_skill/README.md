# VRAM-estimation skill

run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py) is the callable entry;
its exact argument declaration is [skill_config.json](skill_config.json), with
details in [evaluate_vram_skill.md](evaluate_vram_skill.md). It coordinates a
bounded structural preflight and returns predicted peak allocation, feasibility,
and (when feasible) an inference batch. Optional run-bound model-I/O contract,
probe samples, hardware context and budget are caller-supplied.

The production adapter first runs structural inspection in an isolated worker.
If training checks pass and VRAM is the only failing inference check, the native
policy measures at most three real evaluation batches in one additional worker.
The [task-composition policy](../../../../docs/reference/task-composition.md#inference-refusal-verification)
sets that bound or explicitly selects static-only behavior. Measurement uses
the remaining preflight time and existing memory limits. It does not train the
candidate or calculate a scientific score.

To understand a refusal, inspect `preflight_outcome` and
`static_preflight_evidence` in the stored record's `memory` object. The latter
contains the tested phase and batch, the exact estimate and cap in bytes, and
any compute-intensity comparison. For example, a static estimate of 8 GiB
against a 5 GiB cap means the **estimate** failed the configured check; it does
not mean a GPU measurement observed 8 GiB. A compute-intensity refusal can have
no VRAM estimate at all.

Also inspect `memory.inference_verification` when present. For example, the
8 GiB estimate above may refuse while a measured 4 GiB workload fits the 5 GiB
cap. Complete, identity-checked evidence can permit that measured batch; the
original 8 GiB estimate stays recorded as a refused estimate. A measured excess
skips training, while missing or inconsistent evidence stops as inconclusive.
A few measured batches cannot guarantee every later input will fit.

The next planner and proposer receive that distinction. Native accounting counts registered
parameters and buffers, including state that a forward-call listing misses.
For example, calling one layer eight times no longer prices its parameters eight
times. Estimated bytes and the selected inference batch can therefore change.

For a historical experiment, select its qualified estimation plugin explicitly
in a copied task manifest, declare `inference_preflight: {mode: static_only}`,
and use a new workspace. The experiment repository
owns that plugin and its installation instructions; installing it alone does not
change normal runs. New evidence records the selected estimator's identity, so a
missing or different worker installation fails clearly. CPU-only runs
carry a separate `static_preflight_bypass` record with the estimator identity
and the reason for skipping. Older records may have neither form of evidence. See the
[evidence contract](evaluate_vram_skill.md#static-decision-evidence) for fields,
validation, and compatibility limits.

Named declared-package integrity failures are terminal configuration/dependency
refusals, not VRAM measurements or model-size feedback. The existing worker and
parent boundaries preserve this distinction; see
[task-code transport and limits](../../../core/local_code/README.md).

Focused seams include [test_wrapper_contract.py](../../../../tests/unit/agent/evaluate_vram_skill/test_wrapper_contract.py)
and adjacent isolated-probe/contract tests. GPU probing is not run by docs
checks; pseudo tests cover transport only.
