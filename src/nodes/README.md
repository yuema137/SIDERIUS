# `nodes/` — the agent nodes of the graph

**Start here if you need to understand a graph node or create one.** **Authority**:
the source, and per node its `<node>/<node>.md` contract doc.
Template for those docs: [`NODE_TEMPLATE.md`](NODE_TEMPLATE.md). Directory
map template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../../docs/agent-reference/MODULE_README_TEMPLATE.md).

## Purpose

One directory per LLM-powered node of the SIDERIUS graph. Each node is one
well-scoped agent — flexible *within* its task, never general-purpose; cross-
node flexibility belongs to the workflow and the protocols, not to any agent.
Nodes communicate **only** through schema, storage and protocols (CLAUDE.md);
nothing in this package reads a peer's output file as a channel.

## Public interface

Exactly two files per node are public — `<node>.py` (the class with
`run(input) -> output`) and `<node>.md` (the contract doc):

| node | class role | contract doc |
|---|---|---|
| `ml_literature_review/` | evidence corpus → expert context | [`ml_literature_review.md`](ml_literature_review/ml_literature_review.md) |
| `result_interpretation_agent/` | prior records → interpretation | [`result_interpretation_agent.md`](result_interpretation_agent/result_interpretation_agent.md) |
| `ml_model_proposal_agent/` | interpretation + evidence → architecture proposal | [`ml_model_proposal_agent.md`](ml_model_proposal_agent/ml_model_proposal_agent.md) |
| `ml_model_implementor/` | proposal → model plugin code | [`ml_model_implementor.md`](ml_model_implementor/ml_model_implementor.md) |
| `ml_code_validator_agent/` | plugin code → validation verdict | [`ml_code_validator_agent.md`](ml_code_validator_agent/ml_code_validator_agent.md) |
| `ml_hyperparameter_tune_agent/` | validated model → tuned, scored, health-gated records | [`ml_hyperparameter_tune_agent.md`](ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md) |

Everything else inside a node directory is **private** (the tuner's
`contracts` / `planning` / `execution` / `records` / `runtime` / `policy` /
`feedback` / `cli` / `scope_acquisition` decomposition; the proposer's
`evidence_rendering`). The boundary is an executable rule —
`tests/unit/nodes/test_node_public_boundary.py` fails an import of a node's
private modules from outside it.

Package-level helpers shared across nodes: `agent_data_stream.py`,
`interpretation_helpers.py`, `proposal_helpers.py`, `scoring_reference.py`.
The top-level [tuner page](ml_hyperparameter_tune_agent.md) is a **legacy
pointer** kept for old links; the real contract doc lives inside the node
directory, and the pointer links to the preserved historical body.

## Inputs

Each node's typed `*Input` from [`agent/schemas/`](../agent/schemas/README.md),
assembled by a protocol function — never by reading another node's files.

## Outputs

Each node's typed `*Output`, plus a per-node record
`{workspace}/{node}_{run_name}.json` — **a log for humans and recovery, never
a communication channel**.

## Owned semantics

- **Node lifecycle.** The tuner's `run()` reads as one lifecycle: plan →
  admission → train → infer/score/health → reflect → build record → emit →
  finalize. Health gates fire at **tuner round boundaries**, not inside
  scoring.
- **Fail-closed inputs.** A score-bearing input without a metric spec is a
  named refusal, never a re-derivation of direction.
- **Candidate role identity**: `record.is_trial` is the one authority for
  trial/formal role (see the tuner's contract doc, "Candidate role
  identity").

## Non-owned semantics

- Prompt rendering and LLM transport → [`agent/`](../agent/README.md).
- Deterministic execution and task seams →
  [`execute_tools/`](../execute_tools/README.md) via `core/sandbox_executor`.
- The path through the graph → [`workflows/`](../workflows/README.md).
- Edge field-mapping → `agent/schemas/protocols/`.

## Extension points

Adding a node is the **eight-step checklist** in CLAUDE.md ("Graph
Architecture — Adding a New Node"): graph placement → implementation →
protocols → unit tests → protocol tests → Tier-1/Tier-2 integration tests →
connection audit. Name it with its module's prefix (`ml_`, `data_`, …) and a
specific descriptor. There is no plugin mechanism for nodes — a node is a
framework change.

## State and filesystem effects

Per-node output records under the workspace; the tuner additionally owns its
working directory (round records, configs, cached models — layout in
[workspaces and resume](../../docs/guides/workspaces-and-resume.md)).

## Failure modes

Typed refusals at input validation; the tuner's structured failure records
(`error_training`, `error_scoring` with `failure_type="not_scoreable"`, …)
persist rather than crash; a node never silently substitutes a default for a
missing upstream field — the protocol must supply it.

## Files normally edited

A node's private modules under its own design doc; its `<node>.md` in the
same PR as any behaviour change (the doc-sync-before-merge rule).

## Files normally NOT edited

`<node>.py` public signatures without updating every protocol touching the
node; `NODE_TEMPLATE.md` structure; anything that would grow a giant
orchestrator function (the responsibility-oriented decomposition rule is
binding).

## Minimal example

```python
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    HyperparamTuningAgent,
)
# constructed and driven by workflows/model_exploration.py — see that module
```

## Related tests

`tests/unit/agent/<node_name>/` (mocked-LLM node suites),
`tests/unit/nodes/` (public-boundary guard), `tests/integration/nodes/`
(Tier 1) and `tests/integration/protocols/` (Tier 2), dual-mode workflow
tests under `tests/integration/workflows/`.
