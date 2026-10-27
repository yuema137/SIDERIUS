# Additional model providers

Use this adapter when a research workflow needs Anthropic, Moonshot/Kimi, or
Z.AI/GLM. Existing OpenAI, Gemini, and DeepSeek routes keep their default
Chat Completions path. Nodes continue to call `LLMBridge`.

## Configure a route

1. Install the extra in the checkout you will run:

   ```bash
   uv sync --group dev --extra pydantic-ai --frozen
   ```

   Package consumers can install `siderius[pydantic-ai]` instead.

2. Bind the selected provider's credential to your launching process, following
   the [installation guide](../../../docs/getting-started/installation.md#api-keys).
   Use `ANTHROPIC_API_KEY`, `MOONSHOT_API_KEY`, or `ZAI_API_KEY`. Never put the
   secret value in workflow JSON.

3. Set the provider and an actual model ID in your project's LLM configuration.
   For example, this config routes the implementation node to Anthropic:

   ```json
   {
     "implement": {
       "provider": "anthropic",
       "model_id": "YOUR_ENABLED_MODEL_ID",
       "max_output_tokens": 16384
     }
   }
   ```

   Replace the model placeholder with one your account can use. The output
   limit is optional; Anthropic requests default to 8192 output tokens. Choose
   a supported limit large enough for the generated code or structured result.

Pass that file through your workflow's `--llm_config` option. A successful
request returns through the existing node interface and contributes to the
normal usage record. Provider errors remain errors; the adapter never silently
switches models.

## What to verify

Provider support does not mean every model supports every operation. This
adapter currently handles one-shot text, JSON, and single-tool selection. It
uses native JSON-object output when the model adapter declares support; otherwise
JSON uses a result tool and requires compatible tool support. Truncated
results are rejected rather than accepted as complete artifacts.

Before a campaign, test the actual model and operations your workflow needs.
Offline adapter tests do not establish account access, quotas, or scientific
quality. See the [transport contract](transport-contract.md) for protocol
selection, output conversion, usage accounting, and limitations.
