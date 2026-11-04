# Workflow declaration examples

A **workflow declaration** (`workflow.py`) is the file that describes one
SIDERIUS experiment: which research steps run, how their results connect, what
advice each step gets, the training budgets and, optionally, a research loop
with stop conditions. This folder holds ready-made declarations to copy into
your project. They use the synthetic [Quickstart classification task](../quickstart/README.md),
not a scientific benchmark.

To prepare and run a copied file, follow
[Write and run a workflow declaration](../../docs/getting-started/README.md#write-and-run-a-workflow-declaration).

## Choose a starting point

| File | What it runs | Use it when |
| --- | --- | --- |
| [`reusable_training.py`](reusable_training.py) | Propose → Implement → Validate → Train & tune, once | Your first training run on your own task |
| [`research_loop_request_input.py`](research_loop_request_input.py) | Interpret → Propose → Implement → Validate → Train & tune, repeated up to three times; it pauses for your input after an iteration that does not improve | You want a research loop |
| [`managed_reusable_candidate.py`](managed_reusable_candidate.py) | Propose → Implement → Validate, no training | You only want to check that generated models are valid |
| [`reusable_candidate.py`](reusable_candidate.py) | Like the previous one, but reads one input from a file you supply | Learning the format; it cannot be prepared as is |
| [`native_training.py`](native_training.py), [`literature_debate_judged.py`](literature_debate_judged.py) | Python scripts that *write* an older, fully concrete request (every input as a JSON file) | The advanced scenario below |

The first four are **reusable** declarations, the recommended format:
preparation generates their inputs from your task package and LLM profile, so
one file serves many runs. The first three are ready to prepare;
`reusable_candidate.py` shows the same format with one file-backed input. The older **concrete** format names every input file
itself and is only needed for the literature-debate step below.

## How a workflow.py is built

SIDERIUS reads `workflow.py` without running it as a program: the file may only
import names from `workflows.definition` and build one `document = ...` value
from them. A mistake is reported with its line and field before anything runs.
Check a file offline with:

```bash
.venv/bin/python -m workflows.definition to-json --input /absolute/project/workflow.py
```

Here is `research_loop_request_input.py`, shortened (`...` marks omitted lines)
and annotated:

```python
document = ReusableWorkflowDocument(
    definition=ReusableWorkflowDefinition(
        # 1. Which task: the task package manifest and the data folder,
        #    relative to your project folder.
        task=ReusableTaskReferences(manifest="task.yaml", data_root="data"),

        # 2. Outside inputs ("externals"): values that come from outside the
        #    steps. "Managed" ones are generated at preparation from your task,
        #    LLM profile and the settings below.
        externals=(
            ManagedCandidateBinding(id="initial", contract="interpretation.input"),
            ManagedCandidateBinding(id="advice", contract="optional.expert-advice"),
            ManagedCandidateBinding(id="training", contract="native-training.settings"),
            ...
        ),

        # 3. Steps ("nodes"): each runs one research capability: interpretation,
        #    literature, proposal, implementation, validation or tuning
        #    (shown in the console as Train & tune).
        nodes=(
            NodeInstance(id="interpretation", capability="interpretation",
                         request=ExternalRequest(binding="initial")),
            NodeInstance(
                id="proposal",
                capability="proposal",
                # 4. Typed connections ("protocols"): a named protocol maps
                #    earlier results and outside inputs into this step's input.
                request=ProtocolRequest(
                    protocol="interpretation-to-proposal",
                    arguments=(
                        ArgumentBinding(name="output", source=ResultSource(node="interpretation")),
                        ArgumentBinding(name="human_advice", source=ExternalSource(binding="advice")),
                        ...
                    ),
                ),
            ),
            ...  # implementation, validation, then tuning
        ),

        # 5. Research loop: repeat the steps up to final_iteration times, feed
        #    the training result back to interpretation, and stop early when a
        #    stop condition is met.
        loop=AuthoredLoop(
            final_iteration=3,
            feedback=LoopFeedback(source=ResultSource(node="tuning"), target="interpretation",
                                  protocol="tuning-to-interpretation", history="native-research/v1"),
            stop_conditions=(NoImprovementStop(completed_bodies=1, on_met="request_input"),),
        ),
    ),
    execution_profile="native-interpretation-candidate/v1",  # which runner executes this shape

    # 6. Advice to each step, and which kinds of model the proposer may produce.
    preparation_options=CandidatePreparationOptions(
        proposal_advice="Start with a small four-feature classifier. ...",
        implementation_advice="Keep the Quickstart model interface and diagnostics explicit.",
        validation_advice="Check feature and class dimensions before training.",
        allowed_output_types=("classifier",),
    ),

    # 7. Training budgets and result rules for Train & tune.
    training_settings={
        "launch": {
            "healthgate_mode": "observe_only",   # "blocking" lets Health checks invalidate a result
            "result_authority": "diagnostic",    # "scientific" lets valid results count
            "max_rounds": 2,                     # tuning rounds per iteration
            "trial_time_budget_minutes": 2.0,
            "formal_time_budget_minutes": 5.0,
            ...
        },
    },
)
```

Read it as seven decisions:

1. **Task**: `ReusableTaskReferences` points at your task package and data.
2. **Outside inputs**: every input that does not come from another step is
   declared once in `externals`.
3. **Steps**: each `NodeInstance` runs one capability.
4. **Connections**: a `ProtocolRequest` names a typed protocol, such as
   `interpretation-to-proposal`, and binds each argument to an earlier step's
   result (`ResultSource`) or an outside input (`ExternalSource`). SIDERIUS
   refuses a connection whose types do not match.
5. **Loop and stop conditions**: `AuthoredLoop` sets the iteration limit
   (`final_iteration`). A stop condition ends the loop early, or with
   `on_met="request_input"` pauses it and waits for you.
   `NoImprovementStop` reacts to iterations without improvement;
   `MetricThresholdStop` to a target score; `JudgeStop` to an LLM judge's
   decision.
6. **Advice**: `preparation_options` gives each step your guidance.
7. **Budgets and result rules**: `training_settings["launch"]` sets tuning
   rounds, Trial/Formal time budgets and epochs, and whether Health is
   enforced (`healthgate_mode`) and results count scientifically
   (`result_authority`). The examples use `observe_only` and `diagnostic`,
   which suit a demonstration; for results you intend to compare, use
   `blocking` and `scientific`.

The [workflow declarations guide](../../docs/guides/workflow-declarations.md)
lists every field, protocol, stop condition and which features combine. The
[declaration contract](../../src/workflows/definition/definition-contract.md)
is the full reference.

## Advanced scenario: a literature review that feeds a research loop

This scenario chains two runs. Use it after you have run a single workflow.

1. **Run A:** three literature reviews → a debate judge → one merged review →
   one proposal, implementation and validation.
2. **Operator handoff:** read the merged findings and paste a concise, reviewed
   summary into run B's `proposal_advice`.
3. **Run B:** interpretation → proposal → implementation → validation → training,
   repeated at most three times. A completed iteration without improvement requests
   input when another iteration remains. You can resume with advice.

Run A is written by the script [`literature_debate_judged.py`](literature_debate_judged.py)
in the concrete format, because its judge step is not available in a reusable
`workflow.py`. Run B is the reusable declaration
[`research_loop_request_input.py`](research_loop_request_input.py). The two
cannot be combined into one declaration, so the handoff carries the findings as
declared advice.

Both runs spend real API money, and run B also consumes GPU time.
For planning, allow roughly 15–25 LLM calls for run A and 20–40 for all three
iterations of run B; these are source-based estimates, not measured totals or caps.
Early termination reduces the count; repairs, additional loss implementations,
interpretation history and tuning reflection can increase it.

### Prerequisites

- Run commands from the selected checkout root, using its own `.venv` after
  `uv sync --group dev --frozen`.
- Use Linux with working [bubblewrap isolation](../../src/tools/workspace_sandbox/README.md).
  Preparation is offline; actual runs need provider credentials and network access.
  Run A also retrieves papers through the literature resolver.
- Run B trains models in Trial/Formal mode (`is_trial=True`) and needs a
  supported NVIDIA GPU/CUDA setup. Select its
  device paths explicitly; the sample paths below must match your host.
- Choose an OpenAI model available to your account. This example uses that model
  for every route and passes only `OPENAI_API_KEY` to candidate processes.
  Bind that key from a trusted external mode-600 file or managed secret in each
  launching shell, following [API key setup](../../docs/getting-started/installation.md#api-keys).
  Do not place credentials inside the scenario directory.

### 1. Create data and select external directories

Choose a fresh directory outside the checkout. All generated files remain there.
Set `MODEL` to your selected OpenAI model ID before running these commands.

```bash
uv sync --group dev --frozen
export REPO="$PWD"
export SCENARIO="$(mktemp -d /tmp/siderius-scenario.XXXXXX)"
export MODEL="your-openai-model-id"
export GPU_DEVICES='["/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"]'

.venv/bin/python - <<'PY'
import os
import runpy
from pathlib import Path
root = Path(os.environ["SCENARIO"])
repo = Path(os.environ["REPO"])
module = runpy.run_path(str(repo / "examples/quickstart/plugins/_quickstart_task.py"))
print(module["materialize_run_bundle"](repo / "examples/quickstart", root))
(root / "task.yaml").symlink_to(repo / "configs/task_composition/quickstart.yaml")
(root / "runs").mkdir()
PY
```

Expected: four hash-checked CSV shards under `$SCENARIO/data`. The `task.yaml`
link resolves to this checkout's Quickstart manifest, preserving its relative
plugin references. Keep this checkout and the link available throughout both runs.

### 2. Prepare and run the judged literature example

```bash
.venv/bin/python examples/workflow_declarations/literature_debate_judged.py \
  --project "$SCENARIO/run-a-inputs" --data "$SCENARIO/data" \
  --workspace "$SCENARIO/run-a" --model "$MODEL"
```

This offline command writes `workflow.json`, `llm.json`, the proposal/storage and
three review inputs, and `candidate_request.json`. It preserves existing files.
Inspect them before launch. To change the papers/search, edit `review_settings`
in the generator and generate into fresh directories. The shipped reviews use
separate optimization and regularization root papers, then a third review with
one dynamic search round; there is no per-review advice field.

`S2_API_KEY` is optional: without a key, Semantic Scholar paper lookup uses the
unauthenticated pool and may be rate-limited. To use your key, add `S2_API_KEY`
to `environment_names` in the generated `candidate_request.json` before launch
and bind it in the launching shell alongside `OPENAI_API_KEY`; do not put the
key value in the request. The generator passes only `OPENAI_API_KEY` by default.

The `judge` adaptor uses `DebateJudgeStrategy(judge_output="synthesize",
synthesize_count=1)`, `AllSelect` and `SingleDistribute`. It emits one merged
review, which can contain several findings, rather than choosing one winning
review. Its `judge.debate` route and `max_judge_calls=5` cover one round of three
advocates, one critic and a final synthesis. That cap does not cover literature,
proposal, implementation or validation calls; the request's timeout is 3600 seconds.

After binding credentials in this shell, check their presence without printing
values, then launch:

```bash
.venv/bin/python -c 'import os; assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY missing"'
.venv/bin/python -m tools.candidate_worker \
  --request "$SCENARIO/run-a-inputs/candidate_request.json" \
  > "$SCENARIO/run-a-receipt.json"
```

Inspect the receipt's `status`, `error` and `graph_trace`. An accepted run has
completed validation; rejection or provider/retrieval failure is possible.
The synthesis output is
`$SCENARIO/run-a/candidate_run/adaptors/judge.out.result.json`.
Its sibling `judge.json` records adaptor evidence, and `judge.judge/` contains
the debate evidence. Run A has no loop and no pause/resume interface. Rerun it
with fresh inputs/workspace if you want a new literature decision.

### 3. Review the findings and declare run B's advice

Extract a reading copy, retaining the complete synthesis JSON as evidence:

```bash
.venv/bin/python - <<'PY'
import os
from pathlib import Path
from agent.schemas.literature_review import LiteratureReviewOutput
root = Path(os.environ["SCENARIO"])
result = LiteratureReviewOutput.model_validate_json(
    (root / "run-a/candidate_run/adaptors/judge.out.result.json").read_bytes()
)
text = "\n\n".join(f"{item.content}\nSource: {item.source_ref}" for item in result.findings)
(root / "findings-review.txt").write_text(text + "\n", encoding="utf-8")
print(root / "findings-review.txt")
PY
cp examples/workflow_declarations/research_loop_request_input.py "$SCENARIO/workflow.py"
```

Read `findings-review.txt` alongside the full JSON, then edit the
`preparation_options.proposal_advice` string literal in `$SCENARIO/workflow.py`.
Paste a summary of the relevant mechanisms, source references, disagreements and
transfer caveats. Select and rewrite; do not blindly truncate a citation or caveat.
Treat the findings as suggestions for this four-feature, two-class task.

For this example, keep the summary between 1 and 4000 characters so it also fits
Resume advice. The declaration's `proposal_advice` field itself has no explicit
length bound; the native advice item has a 100000-character content limit, while
Resume enforces 4000 characters after trimming. Avoid control/format characters.
A concise summary also leaves room when Resume advice is appended.

The declaration explicitly binds `human_advice` to a managed external generated
from `proposal_advice`. Merely writing advice without that protocol argument
would not deliver it to the loop's proposer. The original synthesis file is not
automatically consumed by run B, and no `expert_context` external is declared.

### 4. Prepare the reusable loop

Generate a preparation request after editing `workflow.py`. This captures its
current SHA-256, so later edits require a fresh request and run ID.

```bash
.venv/bin/python - <<'PY'
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from tools.candidate_operations import OperationStoreConfig
from tools.candidate_prepare import ReusableCandidatePreparationRequest
root = Path(os.environ["SCENARIO"]).resolve()
repo = Path(os.environ["REPO"]).resolve()
source = root / "workflow.py"
request = ReusableCandidatePreparationRequest(
    source_path=str(source), project_root=str(root),
    expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    runs_root=str(root / "runs"), run_id=uuid4(), run_name="research_loop",
    llm_config_file=str(root / "run-a-inputs/llm.json"),
    preparation_timeout_seconds=120, candidate_timeout_seconds=3600,
    task_read_only=(str(repo),), candidate_network=True,
    candidate_devices=tuple(json.loads(os.environ["GPU_DEVICES"])),
    candidate_environment_names=("OPENAI_API_KEY",),
)
store = OperationStoreConfig(
    state_root=str(root / "operations"),
    preparation_roots=(str(root / "runs"),), candidate_roots=(str(root / "runs"),),
)
for name, value in (("b-prepare.json", request), ("store.json", store)):
    with (root / name).open("x", encoding="utf-8") as stream:
        stream.write(value.model_dump_json(indent=2) + "\n")
PY
.venv/bin/python -m tools.candidate_prepare \
  --reusable-request "$SCENARIO/b-prepare.json" > "$SCENARIO/b-prepared.json"
```

Require `status="prepared"`. The receipt names the fresh `envelope` under
`runs/<UUID>` and the `candidate_request_path`. The envelope holds `workflow.py.snapshot`;
its `inputs/` holds the resolved declaration, generated inputs and LLM profile,
and its future `workspace/` holds run outputs. No LLM or training runs during preparation. Inspect the prepared
`external.advice.json` to confirm your summary before submitting.

### 5. Launch, inspect and pause

Create an operation submission from the verified preparation. An operation is a
detached process with a persistent ID, which makes pause/resume possible.

```bash
.venv/bin/python - <<'PY'
import os
from pathlib import Path
from uuid import uuid4
from tools.candidate_operations import CandidateOperation
from tools.candidate_prepare import (
    ReusablePreparationReceipt, select_reusable_preparation, verify_reusable_preparation,
)
root = Path(os.environ["SCENARIO"])
receipt = ReusablePreparationReceipt.model_validate_json((root / "b-prepared.json").read_bytes())
assert receipt.status == "prepared", receipt.error
selection = select_reusable_preparation(receipt.envelope)
verified = verify_reusable_preparation(selection)
submission = CandidateOperation(
    request_id=uuid4(), request=verified.request, reusable_preparation=selection,
)
with (root / "b-submit.json").open("x", encoding="utf-8") as stream:
    stream.write(submission.model_dump_json(indent=2) + "\n")
PY
.venv/bin/python -c 'import os; assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY missing"'
.venv/bin/python -m tools.candidate_operations submit \
  --store-config "$SCENARIO/store.json" --request "$SCENARIO/b-submit.json"
```

Set `SEGMENT` to the returned `operation_id`, then inspect progress:

```bash
export SEGMENT="paste-operation-id-here"
.venv/bin/python -m tools.candidate_operations status \
  --store-config "$SCENARIO/store.json" --operation-id "$SEGMENT"
# Optional manual pause while an iteration is running:
.venv/bin/python -m tools.candidate_operations pause-loop \
  --store-config "$SCENARIO/store.json" --operation-id "$SEGMENT"
```

Pause waits for an iteration boundary. The declared
`NoImprovementStop(completed_bodies=1, on_met="request_input")` also pauses after
one completed iteration without a strict incumbent improvement, if another iteration
remains. A first valid result establishes the incumbent; it is not automatically
a plateau. Improvements can carry the run all the way to iteration 3 without
requesting input. Validation/training failures can end a run earlier.

Look for `receipt.status="paused"` and `process.status="exited"` before Resume.
The receipt's `loop_trace` describes the completed iterations and stop/input decision;
node outputs and training evidence are beneath the envelope's `workspace/`.
The pause summary contains numbers, not a fresh scientific narrative. Use the
recorded outputs to decide the next experiment. These diagnostic Quickstart
runs do not establish scientific validity.

### 6. Resume with advice

Write `$SCENARIO/resume-advice.txt` as UTF-8 text. You may reuse your trimmed
findings summary and add a concrete next experiment. Resume accepts 1..4000
characters after trimming surrounding whitespace; it refuses control and format
characters. Rebind credentials in this shell if needed, then:

```bash
.venv/bin/python -m tools.candidate_operations write-loop-resume \
  --store-config "$SCENARIO/store.json" --operation-id "$SEGMENT" \
  --advice-file "$SCENARIO/resume-advice.txt" --output "$SCENARIO/resume.json"
.venv/bin/python -c 'import os; assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY missing"'
.venv/bin/python -m tools.candidate_operations submit \
  --store-config "$SCENARIO/store.json" --request "$SCENARIO/resume.json"
```

`write-loop-resume` reviews the paused segment and writes a request; `submit`
launches it. Follow the returned **new** operation ID. Advice augments the
captured declaration's proposal advice for the resumed segment; changing the
source file does not change an already prepared run. Resume preserves history
and the three-iteration ceiling. Use a new output filename for each later Resume;
retry a lost submission response using its existing request unchanged. A
completed, stopped or failed terminal run cannot use this paused-loop route.

For the authoritative controls, see the
[loop-control CLI contract](../../src/tools/candidate_operations/candidate-operations-contract.md#control-an-authored-loop-from-code-or-the-cli).

These small-task settings use `formal_portion=1.0` and `max_rounds=2`; see [Trial and Formal training](../../src/tools/candidate_console/README.md#trial-and-formal-training) for scope, round limits and framework defaults.
