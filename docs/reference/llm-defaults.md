# Default model routing

## Authority and ownership

`agent.llm_settings.DEFAULT_LLM_PROVIDER` and `DEFAULT_LLM_MODEL` own omitted
agent routing. `KNOWN_PROVIDERS` owns provider-specific omitted-model resolution.
An explicit Gemini or DeepSeek provider never inherits an OpenAI model ID.

`WorkflowLLMConfig.default()` builds the complete standard first-run profile.
`configs/llm/default.json` is its downloadable export, checked for drift by
`test_economical_defaults.py`; it is not a second runtime authority. To regenerate:

```python
import json
from pathlib import Path
from workflows.llm_config import WorkflowLLMConfig
Path("configs/llm/default.json").write_text(
    json.dumps(WorkflowLLMConfig.default().model_dump(
        mode="json", by_alias=True, exclude_none=True), indent=2) + "\n"
)
```

Change the central model identifier and regenerate this export for a future
model migration. Previously saved explicit profiles remain pinned intentionally.
No runtime code loads the example JSON by a checkout-relative path.

## Resolution and compatibility

The standard entry gives explicit `--llm_config` first priority. An explicit
legacy `--llm_model` keeps its Gemini routing and legacy reflector behavior.
With neither flag, the complete economical profile is selected. Shell launchers
forward omission rather than embedding another model default.

Explicit JSON is parsed without overlaying the default profile. Missing analysis
and literature routes retain interpreter inheritance. Direct node constructors,
input schemas and protocol mappers resolve omitted models through the provider
registry. Partial configs retain their retry/reasoning omission semantics.

The automatic workflow profile selects medium reasoning and one transport
attempt for retryable status responses. Timeout/connection retry policy, content
repair attempts, workflow attempts and cumulative spending limits are distinct.
Direct node retry behavior is unchanged. The automatic profile and its export
select `tune.planner_strategy: native-timing-v1`, the framework's native planner,
so a clean install with no `siderius.planner_strategy_defaults` provider resolves
exactly one planner (issue #1034). The deprecated `--llm_model` profile and the
`python -m workflows.model_exploration` module CLI's `--provider`/`--model_id`
profile both come from `WorkflowLLMConfig.uniform()` and select the same native
planner. No historical strategy is selected here;
scientific historical behavior belongs to exp profiles, not model defaults.
An explicit JSON file that omits `tune.planner_strategy` still resolves the
installed default declaration, as described in
[planner strategies](planner-strategies.md).

Historical paper configurations explicitly set their models. Source assembly
qualification is still required for historical plugin acceptance after changing
fingerprinted modules; unchanged routing alone is not proof of prompt replay.
