# Workflow declaration examples

Use these examples to review literature, choose useful findings, and run a small
research loop that can ask you for input. They use the synthetic
[Quickstart classification task](../quickstart/README.md), not a scientific
benchmark. A declaration describes the nodes and their typed connections; a
prepared request binds that declaration to files, model routes and a workspace.

The two-step scenario is:

1. **Run A:** three literature reviews → a debate judge → one merged review →
   one proposal, implementation and validation.
2. **Operator handoff:** read the merged findings and paste a concise, reviewed
   summary into run B's `proposal_advice`.
3. **Run B:** interpretation → proposal → implementation → validation → training,
   repeated at most three times. A completed iteration without improvement requests
   input when another iteration remains. You can resume with advice.

Run A is a concrete v1 request generator in
[`literature_debate_judged.py`](literature_debate_judged.py). Its judge strategy
cannot be parsed as a reusable `workflow.py`. Run B is the reusable v2 source in
[`research_loop_request_input.py`](research_loop_request_input.py). These execution
profiles cannot be combined into one graph. File-backed `expert_context` is not
supported by reusable preparation; the handoff deliberately uses declared advice.

Both runs spend real API money, and run B also consumes GPU time.
For planning, allow roughly 15–25 LLM calls for run A and 20–40 for all three
iterations of run B; these are source-based estimates, not measured totals or caps.
Early termination reduces the count; repairs, additional loss implementations,
interpretation history and tuning reflection can increase it.

## Prerequisites

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

The remaining examples are smaller starting points:
[`native_training.py`](native_training.py) writes concrete four-stage inputs;
[`reusable_candidate.py`](reusable_candidate.py),
[`managed_reusable_candidate.py`](managed_reusable_candidate.py), and
[`reusable_training.py`](reusable_training.py) show reusable declarations.

## 1. Create data and select external directories

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

## 2. Prepare and run the judged literature example

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

## 3. Review the findings and declare run B's advice

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

## 4. Prepare the reusable loop

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

## 5. Launch, inspect and pause

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

## 6. Resume with advice

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
