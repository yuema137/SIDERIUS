# Optional setup-review model

Copy the contents of [`openai_smoke_luna.json`](openai_smoke_luna.json) into
`operation.llm` in a [semantic-review request](../../../src/tools/setup_review/README.md).
This selects GPT-6 Luna for that optional review only. Set the request's input
and time limits separately. Do not pass this leaf configuration as a workflow
`--llm_config`; choose the [workflow smoke profile](../README.md) for that.
