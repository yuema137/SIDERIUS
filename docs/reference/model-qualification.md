# Supported providers and models

![Models tested with SIDERIUS: workflow use and new provider integrations](../assets/model-capabilities.svg)

<p align="center">
  <a href="#tested-models">Tested models</a> ·
  <a href="#provider-notes">Provider notes</a> ·
  <a href="../getting-started/installation.md#api-keys">API keys &amp; setup</a>
</p>

These providers and models have been used or tested with SIDERIUS. Choose the
model that fits your workflow, then configure its API key and model ID.

## Tested models

| Provider | Models | Validation |
| --- | --- | --- |
| <img src="../assets/providers/openai.svg" width="28" height="28" alt="OpenAI logo"> **OpenAI** | GPT models, including `gpt-5.4`, `gpt-5.6-luna`, `gpt-6-astra` | ✅ Workflow use |
| <img src="../assets/providers/gemini-color.svg" width="28" height="28" alt="Gemini logo"> **Gemini** | Gemini models | ✅ Workflow use |
| <img src="../assets/providers/deepseek-color.svg" width="28" height="28" alt="DeepSeek logo"> **DeepSeek** | DeepSeek models, including `deepseek-v4-pro` | ✅ Workflow use |
| <img src="../assets/providers/claude-color.svg" width="28" height="28" alt="Claude logo"> **Claude** | `claude-sonnet-5-5` | ✅ Integration tested |
| <img src="../assets/providers/kimi-color.svg" width="28" height="28" alt="Kimi logo"> **Kimi** | `kimi-k3` | ✅ Integration tested |
| <img src="../assets/providers/zai.svg" width="28" height="28" alt="Z.AI logo"> **GLM** | `glm-5.3` | ✅ Integration tested |

**Workflow use** means used in SIDERIUS research workflows.
**Integration tested** means verified through SIDERIUS's model interface.
Family names summarize prior use; use a specific model ID in your configuration.

## Provider notes

<details>
<summary>OpenAI · GPT</summary>

Use `provider: openai` and `OPENAI_API_KEY`. GPT models have been used across
workflow roles, including model design, implementation and tuning.

</details>

<details>
<summary>Google · Gemini</summary>

Use `provider: gemini` and `GEMINI_API_KEY`. Gemini has been used in historical
SIDERIUS workflows.

</details>

<details>
<summary>DeepSeek</summary>

Use `provider: deepseek` and `DEEPSEEK_API_KEY`. DeepSeek has been used in
SIDERIUS workflows, including literature-review roles.

</details>

<details>
<summary>Anthropic · Claude Sonnet 5.5</summary>

Use `provider: anthropic`, `model_id: claude-sonnet-5-5` and `ANTHROPIC_API_KEY`.
Integration tested on 2026-10-28. Install the [additional-provider dependency](../../src/agent/llm_transport/README.md).

</details>

<details>
<summary>Moonshot · Kimi K3</summary>

Use `provider: moonshot`, `model_id: kimi-k3` and `MOONSHOT_API_KEY`.
Integration tested on 2026-10-28 against the official international endpoint.
One request was rate-limited and passed on retry. Install the
[additional-provider dependency](../../src/agent/llm_transport/README.md).

</details>

<details>
<summary>Z.AI · GLM 5.3</summary>

Use `provider: zai`, `model_id: glm-5.3` and `ZAI_API_KEY`.
Integration tested on 2026-10-28. Install the [additional-provider dependency](../../src/agent/llm_transport/README.md).

</details>

## Use a model in your workflow

Follow [API keys and setup](../getting-started/installation.md#api-keys), then
select provider and model IDs in your experiment's LLM routing configuration.
Different roles can use different models.

For adapter development or testing another model, see the
[integration test notes](model-qualification-evidence.md) and
[transport contract](../../src/agent/llm_transport/transport-contract.md).
