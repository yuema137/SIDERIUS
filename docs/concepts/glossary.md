# Glossary

Terms as SIDERIUS uses them. Where a word has a common ML meaning that differs
from the one here, the difference is stated.

---

**Attempt** — one try at a tuning round. A round may consume several attempts if
training fails or a plan is rejected; `--attempts_per_round` caps them.

**Blocking / observational** — effective Health gate roles. A task selects a
`blocking` or `recording` disposition; framework policy resolves the role and
actions. Blocking-role failures affect scientific eligibility even when an
observe-only policy does not enforce an action. Observational gates provide
evidence without deciding eligibility.

**Composition / composition manifest** — the YAML file that declares a task's
semantics, and the act of resolving it. Composing a run binds the task's data
path, dataset profile, metric, secondaries, health family and task config for the
whole run. Production execution requires explicit task authority; absent
bindings do not select a scientific default.

**Deliverable** — what a model produces for evaluation: the artefact written by
`write_deliverable` and read back by `read_evaluation_payload`. Naming is
declared by the task.

**DatasetProfile** — a task's generic topology declaration: how many partitions
exist, which anchor selection, which may be peeked at for health, plus an opaque
`topology` payload the framework carries and never interprets.

**Direction** — `higher` or `lower`: which way is better for a metric. Always
declared, never inferred. Interpreted by exactly one authority (`MetricOrder`).

**Formal round** — a full-budget evaluation round, as opposed to a *trial* round.
Trials are cheap explorations; formal rounds produce the candidates that compete.

**Forward contract** — the exact tensor contract a model must satisfy, declared in
the task config. Its resolved typed model I/O drives validation/probes; agent
prompt consumers render the fields they need.

**Golden metric** — a synonym for the *primary metric*.

**Health gate** — a validity check evaluated at round boundaries. Answers "is this
output valid enough to trust", not "is it good". See
[Health gates](health-gates.md).

**Inapplicable** — a health-check verdict meaning the check's declared inputs do
not exist for this task, so it was never evaluated. Never blocks; never counts as
a pass.

**Iteration** — one full trip around the agent loop: interpret → propose →
implement → validate → tune. Contains many *rounds*.

**Node** — one stage of the workflow with a typed input schema and output schema.
The current node map includes seven research capabilities; see the
[source node index](../../src/nodes/README.md).

**Objective** — what training minimises. Distinct from the evaluation metric by
*role*, even when the mathematics is the same.

**Plugin** — task-owned code loaded at run scope: a model, a loss, a data path, a
metric, a health check or a view provider. May be declared by importable module or
by file path; a file-declared plugin's content hash joins the run fingerprint.

**Primary metric** — the single scalar that decides which model is better. The
scientific ordering authority among eligible candidates.

**Protocol** — a typed function that assembles one node's input from upstream node
outputs. Protocols map typed schemas between nodes. Per-node storage records
evidence and recovery state; it is not another communication channel.

**Provenance** — the recorded identity of everything a result depended on: the
composition fingerprint, plugin content hashes, the effective health config hash,
the resolved data scope.

**Round** — one plan → train → infer → score → health → reflect cycle inside the
tuner.

**Run** — one workspace, one invariants lock, one resolved scope. Aggregate scores
are only comparable within a run's scope.

**Run invariants lock** — `{workspace}/run_invariants_lock.json`: pins the
resolved data scope, health-gate enablement and effective-config hash for a
workspace. A resume or reuse with different values fails at startup.

**Scope** — which subset of the data a run touches. `DataScope` is the framework's
partition-index form; a task may also build its own scopes via
`TaskScopeCapability`.

**Scoreability contract** — an executable check that runs *before* a metric's
arithmetic and decides whether the deliverable can be scored at all. A refusal is
a structured, recorded outcome.

**Secondary metric** — additional observational evidence. Recorded and shown to
the agents; never an operand of any ordering expression.

**Semantic fingerprint** — a hash over a composition's declared content, including
file-declared plugin contents but never absolute paths, so the same package at two
locations has one identity.

**Skill** — an atomic callable with typed input and output: training, inference,
scoring, a health check. Structurally indistinguishable from an agent to its
caller.

**Task package** — the set of declarations and plugins that describe one
scientific task. See [What a task must provide](task-package.md).

**TaskDataPath** — the frozen four-method interface through which the framework
reads a task's data and writes its deliverables.

**TaskScopeCapability** — an optional sibling capability on a data path: the
ability to build and serialise a task's own training and evaluation scopes.

**Trial round** — a cheap, reduced-budget round used to explore before committing
formal-budget compute.

**Workflow** — a deterministic, hardcoded path through the node graph. Distinct
from an *orchestrator*, which would choose its own path. SIDERIUS currently runs
workflows.
