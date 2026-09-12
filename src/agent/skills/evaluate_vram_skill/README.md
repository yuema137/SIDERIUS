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

Focused seams include [test_wrapper_contract.py](../../../../tests/unit/agent/evaluate_vram_skill/test_wrapper_contract.py)
and adjacent isolated-probe/contract tests. GPU probing is not run by docs
checks; pseudo tests cover transport only.
