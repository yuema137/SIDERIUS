# VRAM feedback integration fixture contract

`test_vram_awareness.py` covers two workflow iterations with finite recording
agents and a synthetic hardware identity. The first tuner output supplies a
legacy `PhysicalRejection` with `estimated_gb=29.1` and no measured/static
preflight evidence. The second proposer receives the rejection and hardware
context through the real workflow/protocol path.

`workflows.model_exploration._render_physical_rejection` owns the transported
text. Its legacy rendering includes `Recorded estimate: 29.1 GiB`; the schema
field name `estimated_gb` is retained. The witness asserts this literal recorded
estimate, not a measured GPU peak. It also preserves assertions for model/layer
identity, hardware context, operator budget, prompt inclusion and reduced model
width in the next proposal. Hardware-context text has its own renderer; this
fixture repair does not change that renderer's labels or formatting.

`tests/unit/workflows/test_render_physical_rejection.py` covers the rendering
owner; the integration witness covers transport into the subsequent proposal.
Run both through their covering suites without real provider/GPU execution.
This fixture does not establish resource estimates or scientific performance,
and its integration module remains outside CI selection.
