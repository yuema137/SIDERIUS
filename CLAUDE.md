# SIDERIUS Contributor Rules

This file owns repository contribution policy. Detailed subsystem contracts
remain with their modules; source and tests establish implemented behavior.
Start with the [technical reference index](docs/agent-reference/index.md) for
the owners affected by a change.

## Repository and scientific ownership

SIDERIUS is a task-generic closed-loop research framework for supervised
scientific machine learning. The agent loop surrounds a deterministic core
that owns data selection, execution, scoring, validity and provenance.

Framework defaults follow the current generic contracts. A fix need not
preserve an erroneous old default. Historical scientific behavior belongs in
explicit, versioned experiment-owned configuration or compatibility profiles,
using generic framework interfaces where needed. Do not restore it as an
implicit framework default or rewrite archived evidence.

- Scientific tasks declare data, model I/O, objectives, metrics, Health checks,
  prompt guidance and plugins through a task composition manifest. Do not
  select a scientific task implicitly in framework source.
- Real tasks, experiment treatments, campaigns and scientific comparisons belong
  in the external consumer repository, siderius-exp. Framework Quickstart and
  synthetic examples specify generic behavior; they are not scientific defaults.
- Raw datasets, workspaces, generated models, caches and credentials stay
  outside the source tree. Preserve declared scientific identities and explicit
  run bindings; do not infer semantics from directory names.
- A user asking to configure their own task follows the
  [coding-agent setup route](README.md#start-with-your-coding-agent) and
  [repository setup skill](docs/agent-reference/siderius-setup-review/SKILL.md).
  Their task and run configuration belong in their external project. Such a
  request does not require changing framework source or knowing manifest files.

Before reporting ownership or revision, inspect the current checkout with
`git rev-parse --show-toplevel`, `git rev-parse --git-common-dir`,
`git branch --show-current` and `git remote get-url origin`. A temporary
worktree belongs to the repository identified by its Git metadata.

## Pull request scope and structured-coding workflow

These are binding project principles for implementation, documentation and
release preparation:

1. **One PR, one clearly defined problem.** A PR may cover a small set of issues
   only when they are tightly related and belong to the same reviewable change.
2. **Separate unrelated work.** Keep unrelated bug fixes, new features and
   documentation work in separate PRs. Documentation needed to explain the
   behavior changed by a PR belongs with that change. Record incidental findings
   as scoped issues instead of silently expanding the active PR.
3. **Merge dependencies incrementally.** Develop, independently review, validate
   and merge dependent changes in a deliberate sequence. Do not accumulate them
   into a giant release PR. Component reviews do not substitute for a reviewable
   final diff. Release preparation assembles already merged, validated revisions,
   tags and release notes.
4. **Declare scope before editing.** State the problem, affected boundaries,
   included issues, non-goals and required validation. If the scope materially
   grows, stop expanding the current PR, explain the change and split the work
   into separately reviewable steps before continuing.

Apply these principles at each structured-coding checkpoint:

- **Audit and plan:** read the affected code, define the bounded outcome and
  record the PR boundary and dependency order in the local plan.
- **Implement:** keep changes within that boundary; log adjacent findings as
  separate issues and keep necessary behavior documentation synchronized.
- **Ready for review:** compare the actual diff against the declared scope.
  Split unrelated changes before requesting independent review. Include the
  relevant validation and production/paper-compatibility impact.
- **Merge and close out:** fix review findings, complete the relevant checks,
  merge the bounded PR and update or close only the issues it actually resolves.
  Then proceed to the next dependent PR.

This section is the authority for PR scope; local structured-coding plans and
agent entrypoints must refer to it rather than maintain competing rules.

## Local planning and handoff

- Keep plans, step/PR designs and handoffs together under
  `.structured-coding/plans/<effort>/`, with one authoritative plan per effort.
  Keep `.structured-coding/` ignored and untracked; never commit, push or
  force-add it. Public documentation belongs in tracked README/docs files.
- Record scope, decisions, dependencies, acceptance criteria, validation,
  unresolved findings and the next bounded action. Before resuming after a
  handoff or compaction, read the applicable plan and verify the checkout,
  changed paths and revision. If required scope or approval is missing, obtain
  it from the operator rather than reconstructing it from status prose.
- Markdown owns any corresponding HTML rendering. Reading mirrors follow the
  authoritative document and must not introduce requirements or approval.
- Local workflow entrypoints refer to the PR-scope section above instead of
  maintaining another policy authority.

## Environment and launch credentials

- In the exact checkout that will execute, run `uv sync --group dev --frozen`,
  then use that checkout's `.venv/bin/python` for Python commands, tests,
  hardware qualification and campaigns.
- Never copy or borrow another checkout's virtualenv, editable install,
  `site-packages` or source through `PYTHONPATH`. System `python` /
  `python3` is unsupported. A container must use the committed `uv.lock`
  and execute the selected source/package revisions.
- Offline installation, offline tests and `--dry-run` need no API key. Before each
  effectful experiment, bind only the enabled providers' required credentials
  from a trusted external mode-600 file or managed secret to the launching
  process. Perform a name-only presence check in that same process environment.
  Never print, log, shell-trace, commit or upload secret values. A dotenv
  compatibility loader does not establish per-launch binding; key presence
  does not establish provider access. Follow the
  [installation contract](docs/getting-started/installation.md#api-keys).
- Use declared external data and workspace locations with the current
  [entrypoints](docs/reference/entrypoints.md); deployment images and launch
  wrappers must not add task defaults or replace the dependency authority.

## Portability

Code, scripts, tests and command examples must operate on the selected checkout
and explicitly configured resources. Do not assume a developer's username,
home directory, server or separate clone.

Derive repository paths from the current file or an established root helper.
Obtain data, workspace, cache and executable paths from configuration,
environment variables, fixtures or explicit parameters. Shell scripts resolve
from their own location or a supplied root; document intentional dependence on
the caller's working directory.

Tests must read their own checkout. Use `tmp_path` or standard temporary
directories. Declare external-resource requirements, validate supplied paths,
and skip or fail informatively according to the test contract; never silently
fall back to a developer's resources. For meaningful path risk, run a focused
check from an unrelated checkout path and prove which tree it reads. Merely
changing the working directory does not test absolute-path portability.

Clearly labelled deployment examples may name particular machines. Verify
local tool availability before claiming execution, and report environmental
limitations. When fixing a portability defect, inspect nearby uses, repair the
smallest confirmed scope, add a discriminating regression and track broader
findings separately.

## Coding standards

- Read the affected architecture, source, schemas and tests before editing.
  State uncertainty and resolve material contract ambiguity before choosing
  scientific semantics or changing a public interface.
- Prefer simple, explicit, modular code with typed inputs/results and bounded
  side effects. Use composition where behavior varies; avoid speculative
  abstraction, deep dependencies and task-specific branches in generic code.
  Keep docstrings, comments and errors precise.
- Validate every external configuration and LLM-generated execution input with
  a Pydantic schema before use. Execution reads the validated object, never
  the raw dictionary. Add a schema before introducing a new configuration
  category. See the [schema contract](src/agent/schemas/schema-contract.md).
- Split orchestration by responsibility: phase execution, policy, record
  construction, persistence and state transitions need explicit boundaries.
  Do not add another responsibility to an oversized orchestrator. Extract a
  typed, independently testable unit with production reachability evidence,
  then extend it; leave the orchestrator sequencing phases.
- Refactors must preserve public APIs, CLI/configuration and serialization
  contracts, task/plugin interfaces, phase order, retry/round behavior,
  timeout/signal semantics, statuses and scientific behavior. Demonstrate
  parity across affected paths. Keep semantic changes separately reviewable.
- Size and complexity trigger review, not mechanical splitting. Functions
  around 100–200 lines warrant a responsibility check; above 300 strongly
  favor decomposition, and above 500 require a documented reason. Modules
  around 1,000–2,000 lines warrant review; above 2,000 favor decomposition,
  and above 3,000 require a documented architectural reason. Generated,
  vendored and static-data files are exceptions. Nesting beyond three levels
  or cyclomatic complexity above 10 warrants review; above 15 strongly favors
  refactoring unless inherent to the domain.
- Refactor only where the active change would worsen an unhealthy boundary,
  existing structure makes the repair unsafe, or nearby duplication is
  accumulating. These standards do not authorize repository-wide cleanup.
- [pyrightconfig.json](pyrightconfig.json) owns checked scope and severities;
  the baseline is `basic` with its explicit overrides. A passing result does
  not prove strict coverage. Stronger checks require declared scope and a
  separately reviewed configuration change.

## Architecture and single authorities

Nodes exchange typed schema objects through protocols. Each node's input/output
models define its complete public data contract; protocols own field mapping,
including fan-in from multiple upstream outputs. A node writes its own storage
record for persistence and recovery. Peer-node files are not a communication
channel. Do not import another node's private implementation modules.

A new node needs a clear graph position, complete typed inputs/outputs,
implementation, protocols for its edges, adjacent documentation following the
[node template](src/nodes/NODE_TEMPLATE.md), focused node/protocol tests and
a connection audit. Include appropriate pseudo integration coverage and
separately scoped real-API qualification. Use module-specific snake_case node
names and the established directed-edge protocol naming. Follow the
[architecture contract](docs/architecture.md) for skills and graph structure;
do not treat a conceptual orchestration design as a shipped interface.

Use existing native contracts and their owners. Do not duplicate an authority
in a workflow, adapter, prompt, launcher or consumer:

| Boundary | Current owner and contract |
| --- | --- |
| LLM routing, provider construction and usage accounting | [LLM bridge](src/agent/llm_bridge.py), [agent contract](src/agent/agent-contract.md) |
| Task declarations and run-scoped composition | [manifest contract](docs/reference/task-composition.md), [composer](src/workflows/task_composition.py) |
| Task data, scope enforcement and verified scope transport | [data-path contract](docs/agent-reference/mechanisms/data-path-and-scope.md) |
| Evaluation identity, scoreability and direction | [metric contract](docs/agent-reference/mechanisms/metrics.md), [MetricOrder](src/execute_tools/metric_order.py) |
| Indexed deliverable naming and task-owned codec capability | [deliverable owner](src/execute_tools/deliverable_spec.py), [execution contract](docs/agent-reference/mechanisms/execution.md) |
| Native training and model capabilities | [shared training appendix](src/agent/prompt_templates/native_training.py), [model contract](src/ml_models/model-contract.md) |
| Deterministic execution and subprocess supervision | [execution module contract](src/execute_tools/execution-contract.md), [sandbox/core contract](src/core/core-contract.md) |
| Task objectives and training diagnostics | [training contract](docs/agent-reference/mechanisms/training-objective-and-diagnosis.md) |
| Health policy, task checks and validity | [Health contract](src/execute_tools/health_checks/health-contract.md), [composition and verdicts](docs/agent-reference/mechanisms/health-gates.md) |
| Plugin registration, identity and subprocess propagation | [plugin contract](docs/agent-reference/mechanisms/plugins.md) |
| Run invariants, resume and findings union | [persistence contract](docs/agent-reference/mechanisms/persistence-and-resume.md), [run lock](src/core/run_invariants.py), [resume owner](src/core/resume.py) |

Metric arithmetic and Health validity are distinct; do not bypass declared
scoreability or reinterpret direction from a metric name. Keep framework Health
policy separate from task-owned checks, thresholds and scientific guidance.
Preserve fail-closed scope and identity checks on execution, reuse and resume.
Resource limits remain explicit caller inputs; use the core's resource-ceiling
owner rather than guessing a host/task cap.

The native trainer owns optimization, validation and checkpoint lifecycle.
Model plugins supply their declared configuration and forward computation;
proposed training interventions need an actual supported execution path.
Render shared execution facts through the owning training appendix instead of
copying them into individual agent prompts. Distinguish runnable code from
faithful implementation of a scientific hypothesis.

## Validation and independent review

- Each test must name a real defect not already caught by a schema, static
  checker, another test or the relevant gate, and explain which assertion
  fails if that behavior breaks. Do not test Pydantic's declarations themselves
  or compare a value with an expectation read from the same implementation.
- Test cross-model concepts across their participating models. Preserve
  discriminating regression, production-path reachability and safety-prompt
  coverage. When consolidating tests, identify non-equivalent input classes,
  preserve their witnesses and explain why the replacement covers them.
- During implementation run targeted tests, relevant static checks and
  structural guards. Pseudo integration is the default; real API/GPU effects
  require the applicable launch scope and credentials. For affected failure
  classes, use the [gate standard](docs/gates/gate_testing_standard.md).
  Real-training gates must cold-start without `--seed_paths`, unless an
  explicitly authorized reproduction requires otherwise.
- Default to automatic PR CI for the final reviewable revision. Do not run a
  local full suite, split it into chunks, or manually dispatch duplicate CI
  without an explicit need. The [CI workflow](.github/workflows/ci.yml) and
  [CI contract](docs/testing/ci_parity.md) own selection and execution.
  Sequential dependent PRs each receive their own relevant validation.
- Record the exact checkout/revision, commands, tool exit status and test
  summary. Read the actual log; a pipeline wrapper's success is not a test
  verdict. Use `pipefail` or capture the test process status. Run final
  release/full-suite evidence from a clean committed tree; do not weaken
  clean-tree or identity guards to validate work in progress.
- Obtain independent review of the final bounded diff, address findings and
  rerun checks affected by changes. State production, paper and compatibility
  impact, distinguish source inspection from executed evidence, and report
  unresolved limitations.
- Before merge, synchronize changed node/skill contracts and operator-facing
  CLI/default/behavior documentation against the final source. Create the
  adjacent skill contract if absent. Put this check in the plan; a passing
  code test does not establish documentation accuracy.

## Documentation audience and review

This rule applies at every directory depth, including source, tests, examples,
deployments and archived documentation. Classify Markdown by filename,
case-insensitively:

- Only files named `README.md` (case-insensitively) are
  **human-facing**. Assume a technically literate reader who is new to this
  project. Lead with purpose and prerequisites, then give ordered steps,
  concrete commands, expected outputs and effects, and where to change inputs.
  Explain project-specific terms when they first matter; preserve exact CLI
  flags, filenames, schema fields and established technical terminology.
- All other Markdown files are **agent-facing technical references**. State
  scope, owners, interfaces, schemas, invariants, defaults, failure behavior,
  side effects, validation evidence and unresolved limitations as applicable.
  Use the same jargon and identifiers as the landed code. Be detailed and
  complete enough that an agent can implement or verify the contract without
  reconstructing missing decisions. Agent-facing does not mean opaque prose.

Tutorial notebooks (`.ipynb`) remain learner-facing. A Markdown filename
containing `tutorial` does not change its audience. Runtime prompt, skill and
advice Markdown also carries executable input meaning: changing its wording
requires the corresponding behavior and identity review, not only a prose review.

Keep navigation hierarchical: a repository README introduces its major areas;
each area's README introduces the next level and links to the owning technical
reference. Keep detailed contracts in non-README documents. Do not duplicate a
rule in several indexes or make a parent README enumerate every leaf document.

Every new or modified human-facing page must receive a readability and logic
review using the non-dialect parts of the
[DongbeiGPT skillset](https://github.com/yuema137/DongbeiGPT):
`clear-tech-explainer` for causal structure, `concrete-example` when a worked
trace helps, and `plain-chinese` for Chinese prose. Apply the clarity principles
to English pages without translating them or adding regional voice. Check
whether a new reader can identify what to do, in what order, which file owns
each choice, and how to recognize success. Simplification must preserve
technical conditions and distinctions.

For both audiences, compare behavior claims and commands against the exact
source revision and relevant tests: paths, flags, defaults, units, shapes,
parameter interactions, outputs and failure cases. Distinguish source review
from commands actually executed. Plans establish intended work; verify current behavior from source and tests.
Keep development chronology, incident narratives and status ledgers out of
contributor rules. Link to the owning contract instead of duplicating rules in README
files; keep each rule authoritative in one place.

Apply this review whenever a page is created or changed; this does not require
an unrelated repository-wide rewrite. Explicitly requested human reading
mirrors remain reading aids for the authoritative source, not separate rule
owners.

Public installation/download examples and current repository entry links use
`yuema137/SIDERIUS` and `yuema137/siderius-exp`. Development PRs remain in
Galileo-Sandbox. Changing documentation links does not authorize publishing or syncing a
release.
