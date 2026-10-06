# configs/llm

Per-stage routing inputs are [`certify_minimal.json`](certify_minimal.json),
[`deepseek_tiered_pro.json`](deepseek_tiered_pro.json),
[`openai_tiered_pro.json`](openai_tiered_pro.json), and
[`openai_tiered_v1.json`](openai_tiered_v1.json). The launcher passes the
selected file to `agent.llm_bridge`; credentials remain external.

These framework examples explicitly select `native-timing-v1` in
`tune.planner_strategy`, so they work without an experiment compatibility
package. This selection uses the new timing guidance. To preserve an existing
experiment's historical strategy, use that experiment's LLM configuration and
its declared compatibility package instead; see
[planner strategy selection](../../docs/reference/planner-strategies.md).

See [the parent guide](../README.md) for child ownership and the focused validation route.
