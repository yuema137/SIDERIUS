# Choose an LLM configuration

An **LLM profile** is a JSON file that says which provider and model serve each
role in a workflow: interpretation, data analysis, the three proposal stages,
implementation, validation, the tuning planner and reflector, and literature
review. This folder holds ready-made profiles. Copy one into your project
(the other pages call the copy `llm.json`), edit it if you like, and select it
for each run.

Start with a cheap **flow check**: can your task load data, create a model,
train, score and save results? A high score is not the goal of this first run.
Use a separate configuration when you start evaluating scientific ideas.

| Purpose | What to use | What it establishes |
| --- | --- | --- |
| Offline setup check | Installation checks, offline preparation, or the chain launcher's `--dry-run`; no API key or model call needed | Configuration and command preparation; no real model or training calls |
| Default / first real run | [`default.json`](default.json) | All workflow routes use GPT-5.6 Luna, with `medium` reasoning and no automatic 429/5xx retries; start with a small dataset and short workflow |
| Existing GPT-6 Luna demos | [`openai_smoke_luna.json`](openai_smoke_luna.json) | Every route uses GPT-6 Luna (`gpt-6-luna`); retained for experiments that already selected it |
| Production / scientific research | [`openai-moderate-v1.json`](openai-moderate-v1.json) | Our recommended research starting point: GPT-6 Astra for proposal and validation, GPT-5.6 Luna elsewhere; plan API costs separately |
| Custom model choices | Your own reviewed copy of a routing file | Select supported providers/models for each stage and your own budget |
| Paper history | The experiment's frozen config and compatibility packages in [siderius-exp](https://github.com/yuema137/siderius-exp) | Preserve the recorded experiment's information flow; this is a separate purpose, not a higher-quality tier |

The Luna profiles are for functional testing, not our recommended production
configuration or a promise of scientific quality. The moderate profile is a
research starting point, not a guarantee of better scores or lower total cost.
You may replace its routes with your own supported model choices.

Choosing the paper's **LLM routes** does not require historical compatibility
mode. Keep model/provider selection separate from planner strategies, runtime
policies, and archived experiment settings; those belong to the experiment.

## Copy a profile into your project

From your SIDERIUS checkout, copy the profile you chose (here the default) into
your project folder as `llm.json`. `cp -n` leaves an existing file untouched:

```bash
cp -n configs/llm/default.json /absolute/project/llm.json
```

Keep this copy with your experiment, so later changes to the shipped profiles
do not alter it. Keep `OPENAI_API_KEY` outside the repository and bind it at
launch as described in [API keys](../../docs/getting-started/installation.md#api-keys).

## Select the profile for a run

How you select the copy depends on the route:

| Route | How to select `llm.json` | Without a selection |
| --- | --- | --- |
| **`workflow.py`** (recommended; `tools.candidate_prepare`) | Set `llm_config_file` in the preparation request (`reusable-request.json`) to the copy's absolute path; see [getting started, step 2](../../docs/getting-started/README.md#2-save-the-preparation-request) | Not possible: `llm_config_file` is required, and preparation refuses a request without it |
| **Older chain launcher** (`scripts/launch/run_chain.sh`) | Pass `--llm_config /absolute/project/llm.json` | It uses the same routing as `default.json` automatically |

On the chain launcher, the automatic profile is built from the shared defaults,
so it also works in an installed package: every role uses OpenAI
`gpt-5.6-luna`, with `medium` reasoning and `max_retries: 1`. Explicit
profiles, including moderate, keep their own models. A partial file retains the
documented inheritance rules; it is not merged with the automatic profile.
Direct node APIs use the same model default, while retaining their existing
retry and reasoning options. For implementation details and how to update the
shared default, see the [default-routing reference](../../docs/reference/llm-defaults.md).

The default reduces accidental use of stronger models; it does not impose a
run-wide spending limit. Transport timeouts, content repairs and workflow
attempts have their own controls. Use small runs and explicit budgets for tests.

## Use the recommended research profile

`openai-moderate-v1.json` selects OpenAI `gpt-6-astra` for proposer comparison,
reasoning and proposing, and for validation. Interpretation, data analysis,
implementation, tuner planner/reflector and literature main/search use
`gpt-5.6-luna`. Every route uses `medium` reasoning and `max_retries: 1`.

To use it, copy it into your project as `llm.json` (as above, with
`configs/llm/openai-moderate-v1.json` as the source) and select it for your
route. Set `OPENAI_API_KEY` through the
[credential setup](../../docs/getting-started/installation.md#api-keys) and
verify access to both models before a paid run.

Each role can use its own supported model/provider; changing one does not
require editing workflow code. This template selects the native planner and
does not enable optional capabilities or choose training, retry-round or cost
budgets. The separate setup-review and external orchestration models are not
controlled by this workflow profile. Explicit research profiles and historical paper configurations remain unchanged.

## What the default profile covers

Selecting `default.json` needs no Gemini or DeepSeek key. Provider account access
and quota still need verification; the config does not prove either. Offline
route tests verify the model selection at the request boundary, not live model
access or successful training on your task.

The profile fills every workflow model slot: interpretation, data analysis,
all three proposal stages, implementation, validation, tuning planner and
reflector, and both literature stages. Enabling an optional capability does not
switch it to a more expensive model. The profile selects the framework's
native planner (`tune.planner_strategy: native-timing-v1`), so it runs on a
clean install without an experiment package. It does not select a paper
compatibility profile. It does not enable those capabilities
or set data size, training budgets, iteration count, or failed-round limits.

For the first flow check, explicitly set one iteration and few tuning rounds in
your experiment (in `workflow.py`; on the chain launcher, also
`--max_fail_rounds 1`), with a small task-supported data selection. Keep
training and measurement budgets large enough for that work.
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

## Trade waiting time for lower cost (OpenAI background windows)

Some runs are unattended, for example overnight. Their steps do not need an
answer within seconds. OpenAI can run such requests in the background and
charge lower token rates: 30% below Standard with a 2-hour completion window,
40% below with an 8-hour window. This applies to eligible models on Standard
processing; see OpenAI's [background mode guide](https://developers.openai.com/api/docs/guides/background).
The price of the discount is time: a step may wait hours for its answer.

You switch it on for one role at a time in `llm.json`. Here only the proposal
"proposing" stage waits, for up to 9 hours; every other role keeps its normal
request:

```json
"proposing": {
  "provider": "openai",
  "model_id": "gpt-6.1-terra",
  "openai_background": {"completion_window": "8h", "max_wait_seconds": 32400}
}
```

What happens on each call of that role:

1. SIDERIUS submits the request in the background and writes a
   `<label>.background_submitted` row with the request id to `token_usage.jsonl`.
2. It checks back regularly until OpenAI finishes, then continues with the
   answer as usual. The final row records the tokens and the window used.
3. If there is no answer after `max_wait_seconds`, SIDERIUS cancels the request
   and the step fails with `BackgroundWaitExpired`.

**Choose the wait deliberately.** `max_wait_seconds` is required. The window is
OpenAI's target, not a promise, so give it some margin (32400 s is 9 hours for
an 8-hour window).

**Budget the total time.** A workflow calls its roles one after another, so
the waits add up. Some roles run more than once per iteration: the tuning
planner and reflector run once per tuning round. Three calls on 8-hour windows
can stretch one iteration to a day or more. Make your outer limits cover that sum: the scheduler's wall time,
and `candidate_timeout_seconds` in the preparation request. SIDERIUS does not
check those limits for you; when it sees an internal deadline that is shorter
than the window, it refuses before sending anything.

**Before you start.**

- Only `provider: "openai"` routes accept the setting.
- Install the optional `pydantic-ai` extra, as in the
  [additional-provider setup](../../src/agent/llm_transport/README.md).
- Stopping or killing a run does not stop a request that OpenAI has already
  accepted. OpenAI keeps working on it and bills it. Look up the request id
  in the `background_submitted` row to find it in your OpenAI account.
- Token counts in `token_usage.jsonl` are what OpenAI reported. To price a row,
  use the discounted rate only when it shows `service_tier_served: "default"`
  and the model is eligible.

The exact request, polling, timing and failure rules are in the
[transport contract](../../src/agent/llm_transport/transport-contract.md#openai-background-completion-windows).

## Optional review and orchestration agents

The optional LLM setup review has its own model selection. Copy
[`reviewers/openai_smoke_luna.json`](reviewers/openai_smoke_luna.json) into the
`operation.llm` object of your [semantic-review request](../../src/tools/setup_review/README.md).
This is a **single reviewer configuration**, not a workflow `--llm_config` file.
You still specify that request's input size and time limits. Skipping this
optional review makes no reviewer call.

A separate coding or orchestration agent chooses its own model in its own
application. Your `llm.json` controls the SIDERIUS capabilities that agent
invokes; it does not change the agent's model. For an all-Luna test, select a
Luna model in the agent's application as well, and pass the same `llm.json` to
each capability invocation.

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
describes access, pricing and supported API features. `openai_smoke_luna.json` is for the
framework's current plain text/JSON calls; a custom Chat Completions tool-calling
workflow must follow the model's separate reasoning-effort requirements.
