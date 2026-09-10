# P0 work plan — Existing repository map and minimal entry readiness

## DESIGN FROZEN

Design revision: `p0-docs-v2` (C1/C2/C3 scope, invariants, acceptance and
execution contract; progress/evidence remain live).
Approval evidence: operator reviewed the plan, constrained P0 to structural
clarity without module-function changes, authorized continuation, and reaffirmed
"ok 那么我们继续推进吧" after confirming the single-PR document convention
on 2026-09-10. This records approval for the bounded documentation slice, not
source relocation or later development. Publication amendment, 2026-09-10:
the operator explicitly authorized commit and PR creation, reserving merge.
The earlier agent-imposed local-only endpoint is superseded: semantic commits,
branch push, PR creation/updates and in-scope validation repair are autonomous.
Scope and scientific invariants are unchanged; merge remains unauthorized.
Implementation base: `docs/organizing-cleanup-plan` at
`2091acdfcb24eb9c8d3953ee7ba1e3ba99926aa0` (recheck before execution).
Execution contract: the section below in this same document.
Lifecycle: IMPLEMENTING / C1 AND C2 COMPLETE; C3 NEXT.
Fresh implementation started 2026-09-10; the operator explicitly confirmed
p0-docs-v2 publication authority in this session. Existing planning edits
were preserved. C1 implementation, selected checks and logic review are complete.
Binding scope: [P0 overview](overall.md), corrected by the operator 2026-09-10.
This combines the step/PR design and live ledger; no later PR roadmap lives here.

Operator reading mirror: [Chinese explanation](step-01-user-map_zh.md).
This English document is the sole implementation authority. Mirror maintenance
follows CLAUDE's planning-document rule and does not freeze this design.

## Goal, scope and invariants

Locate what exists, distinguish current behavior from history, document how to
use the existing infra/exp pair and verify minimal existing entrypoints.
Only directly blocking repairs belong here. No scientific experiment design,
complete migration campaign, broad source cleanup or new infra capability.

Preserve source behavior, configs, scientific evidence and tests during the
documentation slice. Any required source repair gets an explicit bounded
addendum; material behavior/architecture changes require operator approval.

### Structural objective and change boundary — operator clarification, 2026-09-10

P0 organizes existing functionality into a clean, readable hierarchy; it does
not redesign how the modules work. Prefer a few meaningful responsibility
groups over either a flat list or artificial nesting. Elegance means a user
can locate a capability and its owner without following unnecessary layers.

Separate two deliverables explicitly:

- **Navigation hierarchy:** organize entrypoints and documentation around the
  existing modules. Show actual paths; label conceptual groupings as such,
  not as directories that already exist.
- **Physical layout proposal:** show a before/after tree and an old-to-new path
  map for any warranted directory adjustment. For each proposed move, identify
  imports, CLI/script callers, package/resource lookup, tests and exp consumers.
  Keep necessary path updates mechanical; do not alter module algorithms or
  contracts as part of a move. No specific source relocation is selected yet.

The currently listed C1/C2/C3 implementation slice remains documentation-only.
It must not claim that publishing a navigation tree completes physical cleanup.
If the proposed hierarchy requires source moves, amend the exact changed-path
scope and validation before executing them; do not treat this comment as a
blanket source-migration approval or silently redefine P0 as a codebase rewrite.

Preserve public behavior, task/plugin contracts, scientific treatment, execution
ordering and saved-state meaning. Do not split/reimplement modules, introduce
new abstractions, change experiments or delete functionality just to make a
tree look tidy. A public-path change is an interface impact even when function
bodies are unchanged; explain its compatibility plan before implementation.

For an approved move, compare the affected entrypoints and behavior before and
after, check packaging/resource resolution, synchronize affected exp callers,
and run focused plus bounded external-consumer checks. Documentation-only
checks cannot qualify source relocation. If a move needs substantial wrappers,
import indirection or runtime changes, stop and reconsider the layout rather
than accumulate compatibility machinery for appearance alone.

## Audited surfaces

- `README.md`, `docs/README.md`, `docs/agent-reference/README.md`:
  current navigation versus retired shipped-example claims.
- `sdsc_submission_scripts/run_chain.sh`, `run_one_iteration.py`,
  `workflows/model_exploration.py`: actual current entry chain.
- `nodes/`, `agent/schemas/protocols/`, `core/`, `execute_tools/`:
  capability, handoff, execution, scoring, resource and recovery map.
- `advice/README.md`, `ml_models/README.md`, `CLAUDE.md`:
  nonexistent artifact inventories, generated-library descriptions and
  obsolete instructions; audit source before correcting each claim.
- `core/generated_library.py`, model/loss loaders and exp launchers:
  actual paths, defaults and workspace authority.
- `scripts/`, `configs/`, `reports/`, integration tests:
  dated/mixed ownership candidates to classify, not delete wholesale.
- Exp task/experiment launchers, README/receipts, pin and validation records:
  actual consumer structure, dependency and available evidence.
- Paper's P0 and high-level capability boundaries: constraints only.
  Main-study configuration is excluded.

## Concrete hierarchy proposal — 2026-09-10

The operator authorized continuing P0. This is the layout-design checkpoint,
not implementation of C1/C2/C3. Read the following tree as navigation categories,
not a proposed set of new Python packages. The physical paths on its leaves
remain unchanged in the first documentation slice.

Current physical roots are peers; the existing README lists only part of them
and incorrectly includes a checkout-generated library and three shipped real
examples. The proposed reading order groups all 19 visible tracked directories
and `.github` by responsibility:

```text
SIDERIUS (navigation, not physical directories)
├── Start and operate
│   ├── examples/
│   ├── configs/ + llm_configs/
│   ├── sdsc_submission_scripts/
│   └── dashboard/
├── Agent capabilities and composition
│   ├── nodes/
│   ├── agent/
│   └── workflows/
├── Deterministic execution and extensions
│   ├── core/
│   ├── execute_tools/
│   └── ml_models/
├── Development and validation
│   ├── tests/
│   ├── tools/ + scripts/
│   ├── env_validation/
│   └── .github/
└── Documentation and retained material
    ├── docs/
    ├── advice/
    ├── reports/
    └── reference_data/
```

Do not imply that every file in a category is pure or current: `scripts/` and
`execute_tools/` remain mixed, `advice/` holds only a stale README, and
`reference_data/` remains executable scientific compatibility, not inert history.
List these exceptions next to the paths. `.structured-coding/` holds this new
planning effort; local workspaces, caches and generated libraries do not become
shipped roots merely because they exist on the machine.

Concrete before/after disposition for this slice:

| Before | After | Physical-path change |
| --- | --- | --- |
| Root README's partial flat list | Short responsibility tree linking to `docs/repository-map.md` | New documentation file only |
| Existing docs/agent/example indexes | Link the map; list both tracked synthetic examples | Existing files edited in place |
| Active modules at root | Same modules and same import paths, grouped in navigation | None |
| Current chain entry and exp launchers | Same command paths and arguments | None |
| Workspace-generated artifacts shown with source | Describe caller-owned storage separately | No artifact moved or deleted |
| Historical or mixed material | Explicit status and actual readers, not silent removal | None |

Why not select `src/siderius/` as a physical target in this PR? Source audit
shows three independent affected boundaries: `pyproject.toml` discovers the
current top-level packages; `core/sandbox_executor.py::child_script_path` is
called with `execute_tools/train_engine_sandbox.py`, `inference_single.py` and
`denoising_score_single.py`; external TIDMAD and SuperNEMO plugins import
`execute_tools` directly, and SuperNEMO's launcher resolves the chain beneath
`sdsc_submission_scripts/`. This is not proof that relocation is impossible;
it is proof that relocation would exceed a cosmetic/documentation change.
No compatibility-wrapper or import-rewrite implementation belongs in this slice.

The immediate implementation remains C1 -> C2 -> C3. Its handoff must explicitly
say that physical root consolidation was not performed. If physical reduction
of the root is required next, choose its exact path map and compatibility scope
before adding it to P0; do not call this navigation result that reduction.

Validation for this proposal: compare all tree leaves with `git ls-files`,
resolve the concrete owner/caller paths above, check English/Chinese command
and checkbox parity, links and fingerprints. These are static planning checks,
not a new qualification of either repository's runtime. A search initially
assumed a SuperNEMO `runtime/` directory and separate core path-helper modules;
those paths do not exist. File discovery resolved the real `plugins/` directory
and the helper inside `core/sandbox_executor.py`; absent paths are not evidence
that consumers are absent.

## C1 — Inventory and user navigation

1. **Goal:** make current responsibilities and entrypoints discoverable.
2. **Scope:** `README.md`, `docs/README.md`,
   `docs/agent-reference/README.md`, `examples/README.md`, and a new
   `docs/repository-map.md`; no source moves. This plan stays under
   `.structured-coding/`; the repository map is user documentation, not a plan.
3. **Implementation:**
   - [x] Classify every tracked visible root, separating ignored local artifacts.
   - [x] Map six nodes, protocols, scoring, resources and recovery to source.
   - [x] Map exp task/config/baseline/record/report locations and actual pin.
   - [x] Replace the root README's retired scientific-example paths with links
     to the two shipped synthetic packs and external-consumer evidence.
   - [x] Correct the "only one example" statements in the docs and example
     indexes; both Quickstart and synthetic masked regression are tracked.
   - [x] Link the new repository map from the root/docs/agent indexes; preserve
     the six tested node CLI citations, which still match their source lines.
   - [x] Separate retained real-run receipts from checks performed today;
     do not call old runs qualification of the current pair.
4. **Validation:**
   - [x] Check relative links, actual symbols and documented caller paths.
   - [x] Run existing document-contract tests; inspect no executable changes.
5. **Acceptance:** reader can locate existing launch, extensions, environment,
   data/workspace requirements, evidence and history without guessing ownership.
6. **Edges:** mixed is not dead; old task names are not proof of obsolescence;
   a recovery branch is not master; a recovered score is not full provenance.
7. **Commands/evidence:** use the CPU doc command below; record source anchors.
8. **Boundary/review:**
   - [x] Follow the map from a new user's perspective and inspect exact diff.
   - [x] Commit only authorized C1 documentation and its ledger.

## C2 — Bounded instruction corrections

1. **Goal:** remove misleading current directions that obstruct P0 use.
2. **Scope:** `advice/README.md`, `ml_models/README.md`, and targeted `CLAUDE.md`
   passages; depends on C1's current source map. No broad history rewrite,
   archive migration or production cleanup.
3. **Implementation:**
   - [x] In the model README, describe `bind_generated_library_to_workspace`,
     the unbound home-library default, and the unbound legacy read fallback;
     do not claim every standalone call has workflow isolation.
   - [x] In the advice README, remove nonexistent file inventories and retired
     `scripts/run_comparison.py` invocations; keep the six-key validation
     contract from `load_advice_artifact`. New advice belongs to the caller.
   - [x] Mark CLAUDE's dated "Current State" entries as history with a pointer
     to the P0 ledger. Correct only audited obsolete current instructions;
     preserve incident evidence and binding invariants. Do not promote the
     entire 1,400-line document to a newly audited current specification.
   - [x] Point new plans to `.structured-coding/plans/<effort>/` without
     duplicating standing rules (planning-location correction below).
4. **Validation:**
   - [x] Check changed prose against source and existing doc/rule guards.
   - [x] Confirm runtime/config/test/pin/scientific artifact diff remains empty.
5. **Acceptance:** documented paths and guarantees match existing behavior;
   historical instructions cannot masquerade as current execution requirements.
6. **Edges:** explicit overrides differ from defaults; preserving history does
   not mean recommending retired commands; don't fix behavior through prose.
7. **Commands/evidence:** existing doc/rule checks below, with actual outcomes.
8. **Boundary/review:**
   - [x] Review for overstated guarantees or accidental new policy.
   - [x] Record findings, staged paths and commit only authorized C2 scope.

## C3 — Minimal entry checks and P0 handoff

1. **Goal:** establish the starting environment, not qualify a new campaign.
2. **Scope:** existing installation/import/launch paths and directly affected exp
   consumers. No new interfaces or experiment treatments.
3. **Implementation:**
   - [ ] Record actual interpreter, installed source and infra/exp revisions.
   - [ ] Verify current minimal entry commands from an explicit workspace/data
     root; separate no-execution dry-run from any actual lifecycle witness.
   - [ ] Use the smallest existing-task check needed to expose an entry blocker,
     without running every task for two iterations as an unconditional gate.
   - [ ] If a confirmed P0 blocker requires repair, record the exact owner,
     smallest fix and affected exp counterpart before implementation.
   - [ ] Update directly affected exp docs/callers and pin only when needed.
4. **Validation:**
   - [ ] Record commands, stages reached, runtime and PASS/FAIL/NOT RUN honestly.
   - [ ] For a repair, add focused/adjoining regression evidence and a bounded
     paired check; do not infer successful training from a dry-run.
5. **Acceptance:** reproducible entry/environment instructions, correct data and
   output authority, no unresolved blocker to the defined minimal P0 checks.
6. **Edges:** unavailable data/hardware does not count as passed; no invisible
   old-checkout fallback; material repairs pause for operator choice.
7. **Commands/evidence:** use the audited TIDMAD dry-run and six isolated
   compositions below. A fresh real-data training qualification is NOT claimed
   by either. If a source repair becomes necessary, specify its additional
   evidence before editing; these checks cannot certify a changed lifecycle.
8. **Boundary/review:**
   - [ ] Review exact diff, exp impact and evidence limitations.
   - [ ] Close P0 for review; do not advance into G0 or later development.

## Execution contract boundary

Canonical checkout `/home/yuema137/SIDERIUS`; planning branch
`docs/organizing-cleanup-plan`; starting master `2091acdf`.
The bounded documentation design is frozen by the approval recorded above.
The fresh implementation-session boundary remains required by v0.1.2;
this planning conversation cannot become that session by relabeling it.
The fresh session must read CLAUDE, this plan, its parent and the full mandatory
upstream route listed below. Keep the handoff alongside this plan, not at root.

CPU documentation/read-only checks are appropriate now; no full local CI, GPU,
paid LLM, campaign or destructive cleanup is authorized by the planning action.
Specify the smallest additional P0 validation budget when an actual entry check
needs it, using existing authorization where applicable. Material changes stop
for a detailed operator decision. Merge remains explicitly operator-controlled.

### Frozen documentation implementation contract

- Project / PR: P0 inventory, navigation and minimal existing-entry readiness;
  one infra docs PR, number not assigned. No runtime implementation PR is hidden
  inside it. Exp remains an independent consumer repository.
- Primary design: this combined step/PR document. Binding parent: `overall.md`,
  CLAUDE, and the Paper plan's P0 sections. No later Paper phase is binding scope.
- Base / prerequisites: `docs/organizing-cleanup-plan` at `2091acdf` (merged
  PR #422). Recheck master before execution/publication; preserve unrelated work.
- Invariants / sequence: the goal section and C1 -> C2 -> C3 above.
- Validation envelope: CPU-only, at most 60 seconds per diagnostic subprocess,
  at most 10 minutes of check execution for this docs slice, no GPU, datasets
  modified, metered API calls, campaigns, destructive cleanup or environment
  rebuild. These bound the approved checks, not additional workloads.
- Gate 1: NOT REQUIRED; no LLM-facing runtime semantics change.
- Gate 2: NOT REQUIRED for the docs-only diff. Source identity, composition and
  command-construction checks are required; they are not training Gates.
- Static/Unit: link and source-reference audit, tracked-file ownership census,
  docs/rule guards, library-resolution contracts. No new redundant unit tests.
- Terminal validation: finish the intended documentation/evidence, commit it,
  then verify required affected checks against that exact candidate. For earlier
  working-tree checks, record base HEAD and changed/untracked fingerprints and
  verify identical content before associating evidence with a commit. No local
  full suite or manual remote dispatch merely to validate prose. Inspect actual
  PR check state; use the operator-approved local CI fallback when remote CI is
  unavailable due to billing, recording exact commands, candidate and limitations.
  Never claim remote-green or alter branch protection to conceal missing CI.
- Publication: semantic commits, pushing the scoped branch, opening/updating
  this PR, inspecting its diff and repairing ordinary in-scope validation issues
  are authorized. Do not pause for approval of each commit or PR operation.
  Never push directly to master, enable auto-merge or merge without explicit
  operator approval of the candidate. This is not release/tag authorization.
- Handoff: `handoff.md` beside this file, not an additional plan authority.
- Stop: PR READY FOR OPERATOR REVIEW: C1/C2/C3 implemented, reviewed and
  validated, scoped branch published, PR opened/updated and inspected, current
  ledger/mirror/handoff, exact-candidate CI or approved local fallback evidence,
  and clean working tree. Local tests passing or opening a PR alone is not the
  endpoint. Stop earlier only for a genuine blocker/material decision. No merge,
  G0, future capabilities, data preparation or main-study configuration.

The mandatory v0.1.2 entry route is [skill entrypoint] -> [agent workflow] and
[adaptation guide] -> the phase-specific full [working rules], [test rules]
and [PR design requirements]. Read the applicable resources completely, including
truncated/paginated continuations; these links are not a condensed substitute.
Resolve an installed matching skill if available, otherwise use this explicitly
pinned manual route. Report missing reads instead of asserting compliance.
This project contract narrows the prompts' example permissions. No automatic
read-completeness guard or hook is installed; upstream issue
[structured-coding #25](https://github.com/yuema137/structured-coding/issues/25)
tracks that enhancement. One PR still uses this combined step/PR document;
do not create a duplicate merely because it lacks a `pr-` filename.

[skill entrypoint]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/SKILL.md
[agent workflow]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/references/agent-workflow.md
[adaptation guide]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/references/adaptation.md

[working rules]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/prompts/implementation-working-rules.md
[test rules]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/prompts/test-ci-gate-rules.md
[PR design requirements]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/prompts/pr-design-requirements.md

## Planning and baseline evidence

2026-09-10: Initial overbroad cleanup proposal corrected after operator direction.
Only P0 remains active. No paper MD/HTML/TeX, runtime code, exp configs or pins
were changed. No main-study plan is part of this work.

Pre-implementation baseline:

```bash
env -u PYTHONPATH -u VIRTUAL_ENV CUDA_VISIBLE_DEVICES='' \
  .venv/bin/python -m pytest -p no:cacheprovider \
  tests/unit/docs/test_node_docs_contract.py \
  tests/unit/guardrails/test_gate_standard_contract.py \
  tests/unit/test_repo_hygiene.py -q --tb=short
```

24 passed in 2.69 seconds, exit 0, canonical checkout own venv. This validates
the existing baseline, not the planned corrections or real scientific workflows.
At that baseline, only untracked plan documents differed from master.
No full CI or real task ran.

2026-09-10: At the operator's request, adopted structured-coding v0.1.2's
`.structured-coding/plans/<effort>/` default. Moved both P0 documents from
`docs/plan/organizing-cleanup/` to this directory, repaired the historical-ledger
link, and added the planning entry in CLAUDE. This is a planning-location
correction, not execution of C1/C2/C3 or a design freeze. Historical design
documents remain in place; no hooks or tooling were installed or upgraded.

Validation after the location correction: the same CPU documentation command
above passed 24 tests in 2.81 seconds (exit 0). A local link/whitespace check
resolved all three relative links in these two plans, confirmed no v0.1.1
references remain in them, and confirmed the old plan directory is absent.
`git diff --check` passed. Review confirmed the changed scope is CLAUDE's
planning pointer and these two plan documents only: no runtime, exp, pin,
paper, scientific treatment or hook changes. This is not full CI or P0
implementation acceptance.

## P0 source inventory — 2026-09-10

This is planning evidence against infra `2091acdf` and exp `ae12ae1`, not
completed C1 documentation. Counts below come from `git ls-files`, not an
unfiltered disk walk. There are 19 tracked visible root directories plus
`.github`; ignored caches/workspaces/old clones are not shipped functionality
and have not been deleted. No claim of complete task-authority removal follows
from PR #422 having merged.

| Infra root | Tracked files | Current role / disposition |
| --- | ---: | --- |
| `agent/` | 106 | LLM gateway, schemas, protocols, prompt templates, atomic skills; active |
| `nodes/` | 42 | Six public capability implementations and their internal helpers; active |
| `workflows/` | 9 | Deterministic composition, task binding and carried-state orchestration; active |
| `core/` | 78 | Execution isolation, resources, identity, records and recovery; active |
| `execute_tools/` | 60 | Training/inference/scoring interfaces and children; mixed with retained scientific helpers |
| `ml_models/` | 14 | Built-in architectures/configs and model/loss plugin loaders; active, stale README |
| `configs/` | 8 | Policy, runtime profiles, synthetic manifests and dated review material; mixed |
| `llm_configs/` | 4 | Provider/model routing configuration; not scientific experiment policy |
| `sdsc_submission_scripts/` | 9 | Chain/iteration entrypoints, environment authority and scheduler support; active |
| `dashboard/` | 14 | Result browser; separate from execution, not changed here |
| `examples/` | 27 | Two synthetic packs: Quickstart and masked regression; index undercounts them |
| `env_validation/` | 1 | Environment/API diagnostic; not an offline-only smoke command |
| `tests/` | 999 | Unit/integration/helpers; a tracked test's presence is not proof it runs in CI |
| `tools/` | 28 | CI selection/execution, reports and optional session tooling; not all runtime |
| `scripts/` | 35 | Live inspection/resume utilities plus dated harnesses; do not remove as a group |
| `reference_data/` | 1 | Tracked `segment_anchors.json`, read by retained anchor helper; not an empty archive |
| `advice/` | 1 | README only; listed advice subdirectories/artifacts are absent |
| `reports/` | 12 | Retained point-in-time evidence, not new run storage |
| `docs/` | 164 | User/agent documentation and historical design evidence; mixed freshness |
| `.github/` | 1 | CI workflow; no change proposed |

### Six nodes and their connections

Each row's implementation lives at `nodes/<directory>/<directory>.py`.
The six `main()` citations in `docs/agent-reference/README.md` are still correct
and pass their existing guard. Standalone-callability is not proof that absent
workflow context is reconstructed.

| Directory | Public class | Input -> output |
| --- | --- | --- |
| `result_interpretation_agent` | `ResultInterpretationAgent` | `InterpretationInput` -> `InterpretationOutput` |
| `ml_literature_review` | `MLLiteratureReviewAgent` | `LiteratureReviewInput` -> `LiteratureReviewOutput` |
| `ml_model_proposal_agent` | `MLModelProposalAgent` | `ProposalInput` -> `ProposalOutput` |
| `ml_model_implementor` | `MLModelImplementor` | `ImplementorInput` -> `ImplementorOutput` |
| `ml_code_validator_agent` | `MLCodeValidatorAgent` | `ValidatorInput` -> `ValidatorOutput` |
| `ml_hyperparameter_tune_agent` | `HyperparamTuningAgent` | `HyperparamTuningInput` -> `HyperparamTuningOutput` |

Actual reusable authorities:

- `agent/schemas/protocols/`: six edge modules, including optional literature
  to proposal; `workflows/model_exploration.py::run_workflow` selects the
  traversal rather than the nodes naming their next caller.
- `workflows/task_composition.py::compose_run_task_bindings`: external manifest
  resolution. `execute_tools/task_data_path.py`: typed data, scope, storage and
  inference-batching interfaces, not an implicit dataset loader.
- `execute_tools/evaluation_metric.py`: primary/secondary metric declarations
  and scoreability; `execute_tools/metric_order.py`: direction interpreter.
  `denoising_score_single.py` is now a composed scoring child despite its old
  filename. Renaming it is outside P0.
- `core/sandbox_executor.py`, `execute_tools/train_engine_sandbox.py`,
  `execute_tools/inference_single.py`: process and execution paths.
- `core/runtime_control/`: admission, probing, measurement, records and
  watchdog owners. P0 maps them; it does not adjust budgets or enable overlays.
- `nodes/ml_hyperparameter_tune_agent/round_health.py` and
  `execute_tools/health_checks/`: round validity and declared checks. The tuner
  calls `run_inference_scoring_health`; the old blanket statement that composed
  runs never reach Health is not a current source description.
- `core/chain_state.py`, `core/resume.py`, `core/run_invariants.py`,
  `core/iteration_manifest.py`, `scripts/inspect_run_state.py`: carried state,
  comparability and recovery. There is no `core/workspace_layout.py`; workspace
  validation is in `core/resume.py::validate_workspace_layout`.

### Exp inventory and evidence ownership

Exp is a separate Git repository at `/home/yuema137/siderius-exp-current`.
Its recovery branch is clean; this inspection does not merge it or certify
remote master. `SIDERIUS_REVISION`, `pyproject.toml` and `uv.lock` all pin
`66d3edf2`; that pin's tracked tree equals infra master `2091acdf`.

| Exp surface | Audited owner / concrete examples |
| --- | --- |
| task definitions | `tasks/{tidmad,oxford_iiit_pet,davis_future_prediction,cancer_gene_identification,supernemo_signal_background,majorana_low_avse}/compositions/` plus declarations/plugins |
| data access | TIDMAD/Pets/DAVIS `runtime/*data_path.py`; Cancer `_cancer_gene_task.py`; SuperNEMO `_supernemo_data.py` / `_supernemo_task.py`; MAJORANA `_majorana_data.py` / `_majorana_task.py` |
| baseline tools | `tasks/tidmad/tools/run_comparison.py`; `tasks/supernemo_signal_background/tools/run_baseline.py`; other tasks' declared reference-model plugins are not thereby independent baseline campaigns |
| experiment selection | `experiments/*/launch.sh` or `experiments/*/two_iteration_qualification/launch.sh`; SuperNEMO also has `baseline_study/` |
| campaign/deployment | `campaigns/` and `deployments/`; not changed or launched by P0 |
| run evidence | `experiments/*/qualification_2026-09-02.md`, recovered trajectory receipts, and `provenance/validation/2026-09-09_pr422_candidate_pin.md` |
| reporting | `reporting/metric_dashboard.py`; HTML/raw outputs remain in configured server storage |

The retained PR #422 receipt reports 40 migration checks and 37 pin/six-task
checks at the pin, plus the merged framework CI outcome. These are historical
records, not tests rerun today. The SuperNEMO demo recovery record explicitly
states that the deleted RunPod's exact executable provenance is unavailable;
do not upgrade recovered plots into a fully reproducible run claim.

Launchers take `--siderius-checkout`, `--workspace`, `--data_dir`. TIDMAD's
qualification launcher checks for training/validation HDF5 names. SuperNEMO's
launcher additionally requires four process files and four event indexes and
creates the workspace even when forwarding `--dry-run`. Do not describe all
exp dry-runs as filesystem-side-effect-free. The local TIDMAD data directory
exists; no local SuperNEMO dataset was established by this audit. No data is
downloaded or staged as part of this plan.

### Findings and bounded dispositions

| Finding | Source/evidence | P0 disposition |
| --- | --- | --- |
| Root README claims three shipped real tasks and no composed Health | README versus tracked examples and tuner execution call | Correct navigation/prose in C1; no task reruns to recreate historical scores |
| Docs/example indexes claim only Quickstart | `git ls-files examples` also contains synthetic masked regression | Include both; do not add a new example |
| Advice lists missing files and recommends adding them here | Only `advice/README.md` is tracked | C2 format/ownership correction; preserve validator semantics |
| Model README claims checkout writes and outdated fallback order | `core/generated_library.py`, `plugin_loader.py::_resolve_plugin_dirs`, `model_descriptions.py::get_model_description` | C2 state exact bound/unbound behavior, no loader change |
| Scientific compatibility remains executable | Health role map, issue #423; retained scoring/anchor helpers and exp dependencies | Name remaining separation exception; no deletion or broad relocation in P0 |
| Installed package omits default policy resources | Existing open issue #424, independently read this round | Do not claim wheel-only readiness; P0 uses the documented exact checkout, not a packaging fix |
| Baseline standalone composition loads ambient generated models | First six-manifest check logged two unrelated generated models | Keep first result qualified; repeat with workspace binding before composition, as below |
| Exp and infra interpreters differ | Own exp environment is Python 3.14.3, infra is its Python 3.12 environment | Record separately; neither copy nor borrow a venv. Do not call these identical environments |

Issues #423 and #424 are already open in the framework repository; this read-only
review did not create duplicates. No newly discovered runtime defect was patched.
Retained script comments and other historical manuals also need future review;
their presence does not authorize a full documentation or source sweep in C1/C2.

## Fresh baseline evidence for the P0 design

1. Docs/rule/library checks: the baseline pytest command above plus
   `tests/unit/core/test_generated_library.py`: **40 passed, 2.67 seconds,
   exit 0**. Infra own venv: torch 2.10.0, Pydantic 2.12.5, pytest 9.0.2,
   NumPy 2.4.3. No full suite, GPU or LLM.
2. Six external manifests: **6/6 composed, 10.24 seconds**, each in a new
   subprocess using exp's own pinned installed distribution. Explicitly removed
   ambient `SIDERIUS_*`, `PYTHONPATH` and `VIRTUAL_ENV`; called
   `bind_generated_library_to_workspace` on a distinct temporary workspace
   before importing composition. The two unrelated model-load messages from
   the first unbound check disappeared. Informational model-loader skips of
   loss/metric files remained; composition itself succeeded.
3. TIDMAD external launcher dry-run: **PASS, 0.45 seconds** from an unrelated
   working directory with the real `/home/klz/Data/TIDMAD` directory. Exactly
   two child commands used the canonical infra `.venv/bin/python` and external
   bounded manifest. The fresh workspace was not created. This checks filename
   presence, environment authority and command construction, not HDF5 contents,
   training, scoring, Health or iteration-2 feedback.

Observed composed metrics (the selected Cancer manifest is eight-network,
not an MTG campaign restart):

| Task | Metric | Direction |
| --- | --- | --- |
| TIDMAD | `tidmad_denoising_score` | higher |
| Pets | `accuracy` | higher |
| DAVIS | `mse` | lower |
| Cancer, `eight_network.yaml` | `mean_auprc` | higher |
| SuperNEMO | `energy_matched_roc_auc` | higher |
| MAJORANA | `energy_matched_roc_auc` | higher |

To repeat the isolated composition check, run the following from the exp root
using its own environment (shell environment cleanup is local to each child).
The audit additionally checked the installed framework's `direct_url.json`
commit against `SIDERIUS_REVISION` and its import path beneath that venv.

```bash
env -u PYTHONPATH -u VIRTUAL_ENV CUDA_VISIBLE_DEVICES='' PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python - <<'PY'
import os, subprocess, sys, tempfile
from pathlib import Path
manifests = [
    'tidmad/compositions/bounded_qualification.yaml',
    'oxford_iiit_pet/compositions/bounded_qualification.yaml',
    'davis_future_prediction/compositions/bounded_qualification.yaml',
    'cancer_gene_identification/compositions/eight_network.yaml',
    'supernemo_signal_background/compositions/signal_background.yaml',
    'majorana_low_avse/compositions/low_avse.yaml',
]
code = '''import sys
from core.generated_library import bind_generated_library_to_workspace
bind_generated_library_to_workspace(sys.argv[2])
from workflows.task_composition import compose_run_task_bindings
c = compose_run_task_bindings(sys.argv[1])
print(c.task_data_path.task_data_path_id, c.metric.spec.id, c.metric.spec.direction)
'''
env = {k: v for k, v in os.environ.items() if not k.startswith('SIDERIUS_')}
with tempfile.TemporaryDirectory(prefix='siderius-p0-compose-') as work:
    for i, name in enumerate(manifests):
        subprocess.run(
            [sys.executable, '-c', code, 'tasks/' + name, str(Path(work) / str(i))],
            env=env, check=True, timeout=45,
        )
PY
```

Reproduction of the audited launcher check, from any working directory (the
data location is an explicit local-deployment example, not a hidden fallback):

```bash
bash /home/yuema137/siderius-exp-current/experiments/tidmad/two_iteration_qualification/launch.sh \
  --siderius-checkout /home/yuema137/SIDERIUS \
  --workspace /absolute/fresh/p0-dry-run-workspace \
  --data_dir /home/klz/Data/TIDMAD --dry-run
```

The actual wrapper allocated a `tempfile.TemporaryDirectory` and asserted no
workspace was created and exactly two expected child commands were printed.
Temporary diagnostic paths were removed; existing data and results were untouched.
The internal framework code at master is tree-equal to the exp pin; this dry-run
does not satisfy a separate test that requires HEAD string equality to the pin.

Adversarial planning review: rejected four overclaims before handoff — one
example rather than two; a callable old-named scorer being obsolete by name;
manifest parsing implying a successful scientific lifecycle; and a historical
receipt implying a fresh qualification. No constructor, config, runtime source,
test assertion, dependency pin or scientific treatment was changed this turn.

Plan validation: all relative links resolve, no trailing whitespace in the
effort's Markdown, and `git diff --check` passes. Tracked changed-path census
still contains only the prior CLAUDE planning pointer; this turn edits only
the untracked planning documents. At that checkpoint, detailed design freeze
and fresh-session implementation remained pending under the selected workflow.

2026-09-10: Operator requested same-name `_zh.md` reading mirrors for step
documents, using DongbeiGPT's explanatory style. Added the standing convention
to CLAUDE and a Chinese mirror for this active step; English remains the sole
implementation authority. This documentation-only addition does not change the
scope, check statuses, acceptance, publication authority or validation evidence
above. Mirror consistency checks cover source fingerprint, links, command blocks
and checkbox parity; semantic review checks that translation adds no decision.

## Implementation evidence — 2026-09-10

### Startup and publication amendment

Read CLAUDE, this full design, overall, handoff and Paper Phase 0 / §21 P0
INFRA/EXP; all six pinned v0.1.2 entry/workflow/adaptation/prompt resources
were read completely via the manual route. No matching installed skill or
standards/hooks was found. Web cache misses and sandbox DNS failure were
resolved by approved read-only curl; no missing-read claim is hidden.
Branch/base/HEAD and all four initial fingerprints matched the handoff.
Exp is still clean at `ae12ae13abb6e2c1618f0f185ba468d669868399`.
The process view exposes only this session, not host campaigns; none were
launched or stopped. Infra frozen offline sync audited 95 packages without
changes (a preceding dry-run confirmed no rebuild was needed).

While reading, another session amended English/mirror/parent to v2 publication
authority. Preserved the amendment, asked only about this newly changed
permission, and the operator explicitly adopted v2 and reaffirmed commit/push/PR
through review readiness. No scope or scientific invariant changed; no merge.

### C1 — implemented, validated and reviewed

Changed `README.md`, `docs/README.md`, `docs/agent-reference/README.md`,
`examples/README.md`; added `docs/repository-map.md`. The map accounts for
20 tracked roots (19 visible plus `.github`), six public classes and schemas,
six protocol edges, deterministic owners, infra/exp launch paths, data/output
ownership and the actual exp pin. Counts describe base `2091acdf`, before new
documentation is tracked. The five responsibility groups are conceptual;
physical root consolidation was not performed.

Root instructions now use the frozen own-checkout environment, label the API
diagnostic as optional/online, avoid presenting all integration tests as an
offline millisecond smoke, and link both synthetic packs. These bounded entry
corrections remain inside C1's README scope. Existing node CLI citations are
unchanged. Retained scientific receipts, current source reachability and fresh
checks have separate descriptions; compatibility and package issues stay open.

Validation: the exact three-file docs/rule/hygiene pytest command in the baseline
section, with `PYTHONDONTWRITEBYTECODE=1` and `timeout 60`, passed **24 tests in
2.57 seconds**, exit 0, own infra venv, CPU-only. A transient source/link audit
passed **235 relative links/anchors, all 20 tracked roots and six public class
names**; whitespace and `git diff --check` passed. No tests were added and no
runtime/config/test/pin/scientific files changed. Corrected a stray `+` in the
new launch-chain prose during diff review; it had no effect on contract tests.

Logic review followed the map as a new user: synthetic entry → explicit
manifest/data/workspace → current source owner → external receipt. Rejected
claims of complete task-neutral source, wheel-only readiness, a current-pair
real training qualification and physical relocation. C1's commit groups its
five user-doc paths with the pre-existing CLAUDE planning conventions and the
four live effort documents. The staged diff contains documentation only.

### C2 — implemented, validated and reviewed

C1 committed as `efbef63e`. C2 changes only `advice/README.md`,
`ml_models/README.md`, targeted CLAUDE passages and synchronized live records.
Advice now describes the actual six-key loader, sparse/nonempty text,
underscore-prefixed inert metadata, digest binding and flag precedence;
nonexistent inventories and retired infra comparison commands are removed.
The retained rejection table is unchanged. The external comparison reader was
verified at `tasks/tidmad/tools/run_comparison.py` and remains distinct.

Model docs now follow `core/generated_library.py`,
`plugin_loader.py::_resolve_plugin_dirs`, `loss_plugin_loader.py::_resolve_loss_dirs`
and `model_descriptions.py::get_model_description`: bound workspace library,
unbound override/home default, unbound-only legacy reads, model-root selection
versus loss-directory union, and actual description order/baseline isolation.
No loader was modified. A search initially assumed `_iteration_advice.py`;
file discovery established the actual inline authority in `run_one_iteration.py`.

CLAUDE marks dated status as history, preserves its entire historical body
byte-for-byte, marks the unlanded `agent/tools/` rename as a proposal, and
reconciles the old separation-ledger pointer with the existing P0 planning
rule. Incident invariants are preserved; this is no whole-document recertification.

Validation: baseline docs/rule/hygiene command plus
`tests/unit/core/test_generated_library.py`, with bytecode/cache writes disabled
and `timeout 60`: **40 passed in 2.65 seconds**, exit 0, own infra venv,
CPU-only. Source comparison confirms the historical status body is byte-identical
and the complete diff from `2091acdf` is Markdown-only. No runtime, test, config,
exp pin or scientific artifact changed. Link/mirror/whitespace checks passed.
Logic review checked override versus default, model versus loss precedence,
unbound callers versus supported entrypoints, and historical authority versus
current instructions. No new policy or runtime guarantee was inferred.
