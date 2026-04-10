# `tests/pseudo_data/` — canonical predefined responses for pseudo-mode tests

This directory holds the **predefined LLM responses and predefined subprocess
results** that pseudo-mode integration tests use as drop-in stand-ins for real
API calls and real training/inference/scoring runs. Each file is a single JSON
dict shaped exactly like what the real production code would return at the
corresponding boundary.

The full design rationale lives in
[`docs/pseudo_test_infra.md`](../../docs/pseudo_test_infra.md). This file is
the short-form reminder for anyone navigating into the tree to add or edit
canned data — and it leads with the **one invariant** you must internalize
before touching anything here.

---

## ⚠️ THE PROJECT INVARIANT (read this before editing any file in this tree)

> **The shape of every file in `tests/pseudo_data/` MUST exactly match the
> shape of the corresponding real production output. By design, this is the
> contributor's responsibility to maintain — no automated check enforces it.**

What this means in practice:

1. **A schema change is a two-file change.**
   When you modify any Pydantic schema that the pseudo data depends on
   (e.g. `agent/schemas/hyperparam_tuning.py`, `agent/schemas/proposal.py`,
   `ml_models/models_format_sandbox.py`), you **must** update every relevant
   JSON file in this tree in the same PR. Otherwise pseudo-mode tests will
   silently lie: they will pass against the old shape, while the real-mode
   tests fail against the new one.

2. **Pseudo data is post-parse, not wire-format.**
   The recording fakes do NOT strip markdown fences, do NOT call `json.loads`,
   do NOT do any transformation. The dict you write here is *exactly* the
   dict the agent will receive. If the real LLM today returns
   ` ```json\n{...}\n``` ` and the production code strips the fences before
   handing the parsed dict to the agent, then you write the parsed dict here
   directly — never the wrapped string.

3. **Pseudo mode is NOT a substitute for real-mode tests.**
   Pseudo mode covers everything *except* "did the real LLM produce a valid
   response". That is what real-mode tests (gated behind `--real-api-call`)
   exist for. Don't try to use pseudo mode to catch API quirks, schema drift
   on the LLM side, or response-format edge cases. You will fool yourself.

4. **No automated schema sync check.**
   We deliberately chose not to validate canned responses against their
   Pydantic schemas at test setup time. Doing so would (a) re-test the
   production schemas' own validators, (b) require importing every schema
   into the test helpers, (c) couple the recording fakes to a specific
   schema layer they shouldn't know about. The trade-off is project
   discipline over enforced fidelity. **The reviewer of any schema-changing
   PR must explicitly check that the corresponding `pseudo_data/*.json`
   files were updated in the same PR.**

If you take one thing from this README, take this: **pseudo data is a
mirror of the real schema, and mirrors break if the thing they reflect
changes without them**.

---

## Directory layout

```
tests/pseudo_data/
├── README.md                                    # this file
│
├── api_call_outputs/                            # canned LLM responses (post-parse dicts)
│   ├── ml_hyperparameter_tune_agent/
│   │   ├── generate.json                        # ExperimentPlan-shaped dict
│   │   └── reflect.json                         # {conclusion, key_factor, discovery, memory_update}
│   ├── ml_model_proposal_agent/                 # added when Phase B lands
│   │   └── ...
│   └── ...                                      # one folder per agent
│
└── train_outputs/                                # canned subprocess results
    ├── punet/
    │   ├── execute_training.json                # {status, results: {final_loss, loss_history, model_params}}
    │   ├── execute_inference.json               # {status, results: {}} — inference produces .h5 files in real mode
    │   └── execute_scoring.json                 # {status, results: {denoising_score, file_vector}}
    └── ...                                      # one folder per built-in or plugin model_type
```

### Naming conventions

- **`api_call_outputs/{agent_name}/`**: agent name follows the CLAUDE.md
  taxonomy (`ml_hyperparameter_tune_agent`, `ml_model_proposal_agent`, etc.).
- **`train_outputs/{model_type}/`**: built-in model type key
  (`punet`, `wavenet`, `fcnet`, `gated_fno`, ...) or agent-generated plugin name.
- **`{method}.json`**: file stem matches the `LLMBridge` method name
  (`generate.json`, `reflect.json`, `generate_text.json`, `tool_call.json`)
  or the `TidmadSandbox` method name (`execute_training.json`,
  `execute_inference.json`, `execute_scoring.json`). The recording fakes load
  every `*.json` in the directory and use the stem as the method name.

### When a method takes multiple distinct calls per run

If a single agent makes more than one call to the same method per run with
different expected response shapes (e.g. Phase B's proposal agent will make
two `generate(...)` calls — one for the reasoning sub-call and one for the
architecture sub-call), use **distinct files per logical sub-call**, not a
queue of dicts in one file:

```
ml_model_proposal_agent/
├── generate_reasoning.json
└── generate_architecture.json
```

The recording bridge's `for_agent()` classmethod will need a small extension
at that point to map sub-call names → which file to pop from. v1 stays
simple: one method per file, one call per round.

---

## How tests use this data

Tests typically construct a recording fake via the `for_agent()` /
`for_model()` classmethods:

```python
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.recording_sandbox import RecordingSandbox

def test_one_round_tuner(tmp_path):
    bridge = RecordingLLMBridge.for_agent("ml_hyperparameter_tune_agent")
    sandbox = RecordingSandbox.for_model("punet", base_dir=str(tmp_path))
    # ...
```

Both classmethods load every `*.json` in the corresponding directory and
return a fake pre-loaded with the canned responses, ready to be injected
into the agent.

If you need to register a non-canonical response for a one-off test (e.g. an
edge case the canonical data doesn't cover), construct the fake directly:

```python
bridge = RecordingLLMBridge(responses={"generate": {"action": "PUNET", ...}})
```

---

## Adding canned data for a new agent or model

1. Create the directory: `tests/pseudo_data/{api_call_outputs|train_outputs}/{name}/`.
2. For each method the recording fake needs to mock, write a `{method}.json`
   file containing a dict shaped exactly like the real API / subprocess output.
3. **Verify the shape against the real schema.** For LLM responses,
   `Schema.model_validate(canned_dict)` from a quick Python repl is the
   fastest check. For subprocess results, look at what `core/sandbox_executor.py`'s
   `execute_*` methods actually return.
4. Keep the dict minimal — just enough to drive the test you're writing.
   Schema-required fields must be present; optional fields can be omitted
   if the test doesn't depend on them.
5. Update [`docs/pseudo_test_infra.md`](../../docs/pseudo_test_infra.md)'s
   pseudo data table if the new directory should be listed.
