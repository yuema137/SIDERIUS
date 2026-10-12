# Choose an LLM configuration

Start with a cheap **flow check**: can your task load data, create a model,
train, score and save results? A high score is not the goal of this first run.
Use a separate configuration when you start evaluating scientific ideas.

| Purpose | What to use | What it establishes |
| --- | --- | --- |
| Offline setup check | Installation checks and the launcher's `--dry-run`; no API key or model call needed | Configuration and command preparation; no real model or training calls |
| First real run / tutorial demo | [`openai_smoke_luna.json`](openai_smoke_luna.json) | All workflow LLM routes use GPT-6 Luna, with `medium` reasoning; use a small dataset and short workflow |
| Production / scientific research | [`openai-moderate-v1.json`](openai-moderate-v1.json) | Our recommended research starting point: Astra for proposal and validation, Luna elsewhere; plan API costs separately |
| Custom model choices | Your own reviewed copy of a routing file | Select supported providers/models for each stage and your own budget |
| Paper history | The experiment's frozen config and compatibility packages in [siderius-exp](https://github.com/yuema137/siderius-exp) | Preserve the recorded experiment's information flow; this is a separate purpose, not a higher-quality tier |

The Luna profile is for functional testing, not our recommended production
configuration or a promise of scientific quality. The moderate profile is a
research starting point, not a guarantee of better scores or lower total cost.
You may replace its routes with your own supported model choices.

Choosing the paper's **LLM routes** does not require historical compatibility
mode. Keep model/provider selection separate from planner strategies, runtime
policies, and archived experiment settings; those belong to the experiment.

## Use the recommended research profile

`openai-moderate-v1.json` selects OpenAI `gpt-6-astra` for proposer comparison,
reasoning and proposing, and for validation. Interpretation, data analysis,
implementation, tuner planner/reflector and literature main/search use
`gpt-5.6-luna`. Every route uses `medium` reasoning and `max_retries: 1`.

From your infra checkout, copy it once into a new file in your external project:

```bash
mkdir -p /absolute/path/to/your-workspace/llm
cp -i configs/llm/openai-moderate-v1.json /absolute/path/to/your-workspace/llm/openai-moderate-v1.json
```

Pass
`--llm_config /absolute/path/to/your-workspace/llm/openai-moderate-v1.json` to
your task's launch command. Keep this saved copy with your experiment so future
profile changes do not alter its configuration. Set `OPENAI_API_KEY` through the
[credential setup](../../docs/getting-started/installation.md#api-keys) and
verify access to both models before a paid run.

Each role can use its own supported model/provider; changing one does not
require editing workflow code. This template selects the native planner and
does not enable optional capabilities or choose training, retry-round or cost
budgets. The separate setup-review and external orchestration models are not
controlled by this workflow profile. Existing defaults and historical paper
configurations remain unchanged.

## Start with the smoke profile

From your infra checkout, copy the file to your own workspace:

```bash
mkdir -p /absolute/path/to/your-workspace/llm
if [ -e /absolute/path/to/your-workspace/llm/agents.json ]; then
  echo "agents.json already exists; choose a new filename or workspace" >&2
else
  cp configs/llm/openai_smoke_luna.json /absolute/path/to/your-workspace/llm/agents.json
fi
```

Pass `--llm_config /absolute/path/to/your-workspace/llm/agents.json` to your
[task's launch command](../../docs/getting-started/first-run.md).
Keep `OPENAI_API_KEY` outside the repository and
[check it in the launch process](../../docs/getting-started/installation.md#api-keys).
Selecting this profile needs no Gemini or DeepSeek key. Provider account access
and quota still need verification; the config does not prove either. Offline
route tests verify the model selection at the request boundary, not live model
access or successful training on your task.

The profile fills every workflow model slot: interpretation, data analysis,
all three proposal stages, implementation, validation, tuning planner and
reflector, and both literature stages. Enabling an optional capability does not
switch it to a more expensive model. The file selects `native-timing-v1`, so no
paper compatibility package is needed. It does not enable those capabilities
or set data size, training budgets, iteration count, or failed-round limits.

For the first flow check, explicitly set one iteration, one round and
`--max_fail_rounds 1` in your experiment, with a small task-supported data
selection. Keep training and measurement budgets large enough for that work.
Inspect the resolved model routes in the optional
[setup review](../../src/tools/setup_review/README.md) before launching.

**Model routing is not a spending limit.** `max_retries: 1` means one transport
attempt, including the initial request, on every configured workflow route.
The planner, reflector and literature stages honor their own explicit limits.
An omitted reflector limit inherits the planner's; an omitted literature-search
limit inherits the main literature limit. Explicit `null` means unbounded
retryable-status attempts for that route. Content-repair attempts and workflow retries are separate, and
this JSON does not impose an output-token limit or a total API-cost ceiling.
Use your provider/project controls and an external run limit for paid tests.
Never switch to a stronger model automatically after a failed flow check.
See the [retry contract](../../src/agent/retry-policy.md) for exact inheritance and limits.

## Optional review and orchestration agents

The optional LLM setup review has its own model selection. Copy
[`reviewers/openai_smoke_luna.json`](reviewers/openai_smoke_luna.json) into the
`operation.llm` object of your [semantic-review request](../../src/tools/setup_review/README.md).
This is a **single reviewer configuration**, not a workflow `--llm_config` file.
You still specify that request's input size and time limits. Skipping this
optional review makes no reviewer call.

A separate coding/orchestration agent chooses its model in its own application
or runner. `agents.json` controls the SIDERIUS capabilities it invokes; it does
not change the outside agent's model. Select GPT-6 Luna there as well for an
all-Luna test, and pass the smoke config to each capability invocation.

## Existing experiment routing examples

These remain examples to inspect and adapt, not onboarding defaults or
comparative quality recommendations:

| File | Providers to prepare |
| --- | --- |
| [`openai_tiered_v1.json`](openai_tiered_v1.json) | OpenAI; **DeepSeek for enabled literature review** |
| [`openai_tiered_pro.json`](openai_tiered_pro.json) | OpenAI; **DeepSeek for enabled literature review** |
| [`deepseek_tiered_pro.json`](deepseek_tiered_pro.json) | DeepSeek |
| [`certify_minimal.json`](certify_minimal.json) | Historical internal certification example: OpenAI and optional DeepSeek literature; use the Luna profile for new flow checks |

Do not infer the complete provider list from a filename. These files explicitly
select `native-timing-v1`; they are not substitutes for paper-history configs.
See [planner strategy selection](../../docs/reference/planner-strategies.md)
for the boundary between native planning and exp-owned history.

The [official GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
describes access, pricing and supported API features. This profile is for the
framework's current plain text/JSON calls; a custom Chat Completions tool-calling
workflow must follow the model's separate reasoning-effort requirements.
