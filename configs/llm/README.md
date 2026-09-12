# configs/llm

Per-stage routing inputs are [`certify_minimal.json`](certify_minimal.json),
[`deepseek_tiered_pro.json`](deepseek_tiered_pro.json),
[`openai_tiered_pro.json`](openai_tiered_pro.json), and
[`openai_tiered_v1.json`](openai_tiered_v1.json). The launcher passes the
selected file to `agent.llm_bridge`; credentials remain external.

See [the parent guide](../README.md) for child ownership and the focused validation route.
