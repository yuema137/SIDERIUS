# VRAM evaluation tests

The owner is the [`evaluate_vram_skill`](../../../../src/agent/skills/evaluate_vram_skill/) resource-admission package; its operator contract is in `evaluate_vram_skill.md`. `test_batch_resolver.py` drives mocked peak/intensity probes through descending candidate batches, semantic ceilings, exact boundaries, and distinct VRAM, intensity, or combined refusal errors. Sibling tests cover probe isolation, IPC composition, killer reports, and preflight adapters. Inputs are tiny synthetic modules; no CUDA probe runs unless an explicit integration gate opts in.

`.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill/test_batch_resolver.py -q`
