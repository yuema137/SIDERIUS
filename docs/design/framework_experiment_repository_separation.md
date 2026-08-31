# Framework and Experiment Repository Separation

**Status:** ACTIVE DESIGN AND WORK LEDGER
**Decision date:** 2026-08-29
**Implementation status:** In progress
**Repositories:** `SIDERIUS` (framework) and proposed private `siderius-exp` (experiments)

## 1. Purpose

SIDERIUS must be usable as a task-generic scientific machine-learning framework without carrying the private operational state of any particular scientific campaign. At the same time, the framework repository must remain independently executable and must prove its end-to-end contracts through lightweight examples.

This document defines the boundary between:

1. the reusable SIDERIUS infrastructure;
2. minimal examples that specify and test that infrastructure; and
3. real task packages, campaigns, deployments, and scientific results maintained in a separate private experiment repository.

It is also the work ledger for the separation. Design intent recorded here is not evidence that a migration has landed. Current capability must always be verified from source, tests, git ancestry, and published repository state.

## 2. Governing decision

The repository boundary is:

~~~text
SIDERIUS
  generic framework
  public task and plugin contracts
  lightweight minimal examples
  deterministic and pseudo end-to-end evidence

siderius-exp
  real scientific task packages
  campaign protocols and frozen treatments
  deployment and scheduler configuration
  experiment records, reports, and provenance
  exact dependency on a qualified SIDERIUS revision
~~~

`siderius-exp` is a consumer of SIDERIUS. It may use only supported caller-facing contracts. It must not depend on undeclared internal module layout, ambient files in a SIDERIUS checkout, or machine-specific paths hidden inside framework code.

Separation is not permission to replace task coupling with a new monolith.
Implementation slices must preserve responsibility-oriented modules, avoid
adding branches or persistence duties to already oversized functions, and use
the smallest existing seam that owns the behavior. A function growing toward
hundreds of lines or a file growing toward thousands is a design-review signal,
not an acceptable default. When a new responsibility cannot be explained and
tested independently, split the responsibility before extending it; do not add
an umbrella manager merely to make migration paths shorter.

## 3. What remains in SIDERIUS

SIDERIUS owns mechanisms whose meaning is independent of a particular scientific task or campaign:

- node input and output schemas;
- protocols and composition contracts;
- task-manifest parsing and validation;
- generic plugin interfaces and loading;
- training, inference, scoring, Health, and resource-admission infrastructure;
- persistence, provenance, resume, and comparability mechanisms;
- generic command-line and programmatic entry points;
- framework documentation;
- synthetic fixtures and minimal examples required to prove the framework contracts;
- tests for generic behavior, extension boundaries, portability, and fail-closed behavior.

Framework tests must not freeze or assert the declarations, fingerprints,
scientific policy, or runtime behavior of TIDMAD, Pets, DAVIS, Cancer Gene
Identification, or any future real task. Those assertions belong to
`siderius-exp`. Infrastructure tests use synthetic contracts; the only named
pack they may exercise directly is the framework-owned Quickstart example.

Framework code must not name a real task, dataset, campaign arm, pod, treatment, scientific baseline, or deployment. Compatibility adapters that predate this separation require an explicit migration or retirement decision; they do not become generic merely because they already exist.

## 4. Minimal-example requirement

SIDERIUS must retain a small collection of lightweight examples. They are executable specifications of the framework, not scientific experiments.

No single example must cover the whole system. The example set, taken together, must cover the complete supported lifecycle:

~~~text
declare
  -> interpret
  -> optional literature review
  -> propose
  -> implement
  -> validate
  -> tune and train
  -> infer
  -> check scoreability
  -> score
  -> evaluate Health
  -> record resource admission and provenance
~~~

The set must collectively exercise materially different contract shapes, including where supported:

- regression and classification;
- higher-is-better and lower-is-better metrics;
- at least one custom model, loss, metric, or Health plugin;
- a semantic target whose validity requires more than shape and dtype;
- declared data splits with executable non-overlap evidence;
- resource measurement and admission;
- standalone node invocation and composed execution.

Every minimal example must be:

- small enough for routine CPU execution;
- deterministic where the contract permits;
- independent of private datasets, credentials, and machine-specific paths;
- runnable from the current checkout;
- suitable for pseudo or deterministic LLM execution in ordinary CI;
- explicit when a real API or GPU path is optional;
- free of scientific-performance claims;
- bounded so it cannot grow into a campaign or benchmark suite.

Real task assets must not be retained merely to make framework tests convenient. When a framework regression requires a particular semantic shape, the main repository should use the smallest synthetic fixture that preserves that behavior.

The minimal examples are part of the framework repository rather than a
separate package or repository. They must remain isolated from production
framework modules: production code does not import an example, and each
example uses the same public contracts available to an external consumer.
Tests may exercise Quickstart directly; other minimal contracts should use
synthetic fixtures selected for the failure class under test.

## 5. What moves to `siderius-exp`

The private experiment repository owns anything whose meaning or operation belongs to a real scientific task, comparison, or deployment:

- TIDMAD, Pets, DAVIS, Cancer Gene Identification, and future real task packages;
- task-specific manifests, plugins, metrics, Health declarations, and scientific context;
- dataset acquisition instructions and data-location configuration;
- Gold and other formal campaign launchers;
- campaign arms, bands, iteration schedules, and frozen treatments;
- literature-review ON/OFF ablations;
- advice artifacts and prior-baseline context;
- task-specific budgets and resource allocations;
- pod, cluster, cloud, scheduler, and storage configuration;
- scientific baselines, checkpoints, scores, reports, and result tables;
- operator decisions and campaign ledgers;
- monitoring and experiment-control utilities;
- private reproduction receipts and provenance.

The experiment repository may contain task-specific code. That code must enter SIDERIUS through declared extension surfaces rather than through framework modifications.

## 6. Dependency and reproducibility contract

Every experiment lineage must pin an exact qualified SIDERIUS tag or commit SHA. A floating dependency on a branch such as `master` or `main` is insufficient for a scientific run.

Each run must record at least:

- SIDERIUS repository URL and exact commit SHA;
- `siderius-exp` commit SHA;
- resolved task-composition identity;
- hashes of task plugins, advice, and campaign configuration;
- environment and dependency lock identity;
- dataset identity without embedding private data in either repository;
- executable argv and resolved runtime budgets.

The preferred dependency direction is one-way:

~~~text
siderius-exp -> SIDERIUS
SIDERIUS     -X-> siderius-exp
~~~

SIDERIUS CI must not clone or inspect `siderius-exp`. Experiment qualification may install a pinned SIDERIUS revision and run additional integration or hardware checks.

### Runtime artifact ownership

The SIDERIUS checkout is immutable during ordinary execution. A run receives
one explicitly configured workspace, and every artifact created or mutated by
that run must live below that workspace. This includes generated models,
losses, tests, modules, skills, staged executable plugins, capability indexes,
run-local calibration, caches, records, provenance, and resume state.

Task packages remain read-only source inputs. A user-authored plugin may live
in `siderius-exp` or another external package, but the executable content used
by a run must be content-pinned and staged into the workspace. Datasets may
remain in external read-only storage; their resolved identity and provenance
are recorded rather than copying the data. Credentials remain external
secrets and are never copied into a workspace.

No run may implicitly absorb generated capabilities from another workspace,
the framework checkout, or a per-user home directory. Cross-run reuse is an
explicit export/import operation, not an ambient preload. Therefore the
checkout-level `agent_generated/` tree and the default
`~/.siderius/generated_library` are migration sources, not acceptable final
runtime authorities. Framework code currently stored under `agent_generated/`
must move to an ordinary package before the legacy tree is deleted.

The executable acceptance boundary is:

~~~text
read-only SIDERIUS checkout
  + read-only external task package
  + writable configured workspace
  -> generate, validate, train, score, persist and resume successfully
  -> no checkout or home-directory mutation
  -> no capability visibility across fresh workspaces
~~~

## 7. Boundary tests

The separation is successful only if it is executable rather than conventional.

Required evidence:

1. SIDERIUS installs and its minimal-example suite runs without `siderius-exp`.
2. `siderius-exp` installs against an exact SIDERIUS revision without copying or patching framework source.
3. A fresh external checkout can declare and execute a real task solely through supported contracts.
4. Repository scans reject experiment identifiers, deployment paths, and campaign-only assets from framework production code.
5. Minimal examples collectively traverse the supported lifecycle.
6. Experiment qualification records both repository SHAs and the resolved task identity.
7. A task that requires a new generic capability produces a focused SIDERIUS issue and framework change; the task must not work around the missing capability by importing private internals.

## 8. Initial migration inventory

The following current SIDERIUS surfaces require classification before movement. This is an initial inventory, not an authorization to delete files.

| Surface | Initial classification | Intended destination |
|---|---|---|
| `docs/campaign/**` | campaign decisions, evidence, and scientific protocol | `siderius-exp` |
| `sdsc_submission_scripts/gold_task/**` | real task package | `siderius-exp` |
| Gold campaign launch and stage scripts | campaign orchestration | `siderius-exp` |
| Gold campaign tests | experiment qualification | `siderius-exp` |
| generic chain and node entry points | reusable infrastructure | SIDERIUS |
| task-composition schemas and loaders | reusable infrastructure | SIDERIUS |
| real task examples and plugins | scientific consumers | `siderius-exp` |
| small synthetic task fixtures | executable framework specifications | SIDERIUS |
| historical task-specific design records | requires archival decision | pending classification |

The Phase-A ownership groups are:

| Group | Current representative paths | Action before removal |
|---|---|---|
| Gold campaign protocol and evidence | `docs/campaign/**`, `sdsc_submission_scripts/_gold_campaign_lib.sh`, `run_gold_campaign.sh`, `stage1_*`, `stage2_*` | copy the complete `v0.1.5` lineage into `siderius-exp`; preserve hashes and launch semantics |
| Gold task package | `sdsc_submission_scripts/gold_task/**` on the `v0.1.4`/`v0.1.5` lineage | bind from `siderius-exp` against a pinned SIDERIUS revision |
| Real example packs | `examples/tidmad/**`, `examples/oxford_iiit_pet/**`, `examples/davis_future_prediction/**` | move to `siderius-exp`; replace framework evidence before deletion |
| Real task manifests | `configs/task_composition/{tidmad,pets,davis}.yaml` and their task-owned config families | move with their packages and make paths experiment-repository-relative |
| Real task executable paths | `execute_tools/{tidmad,pets,davis}_data_path.py` | move behind existing task declaration and plugin loading; remove built-in bootstrap imports |
| Real task acquisition and execution helpers | task-specific modules under `tools/example_packs/**` and task-named Gate scripts | move; retain only generic tooling in SIDERIUS |
| Scientific references and analysis | `reference_data/**` and task-specific analysis/scoring scripts | move with provenance; do not treat them as framework defaults |
| Generic framework entry points | `run_chain.sh`, `run_one_iteration.py`, generic training/inference/scoring engines | retain; remove task bootstrap and defaults without changing their generic contracts |
| Framework contract tests | schema, registry, composition, fail-closed, subprocess-transport tests | retain and convert real-task fixtures to minimal synthetic fixtures where necessary |
| Experiment qualification tests | Gold arm, band, treatment, campaign identity, and scientific-policy tests | move to `siderius-exp` |
| Minimal example | `examples/quickstart/**` and `configs/task_composition/quickstart.yaml` | retain and mature; add only the smallest complementary synthetic example if the coverage matrix requires it |

Files must be classified by responsibility, not by directory name. A campaign directory may contain a genuinely generic mechanism, and an apparently generic directory may contain task assumptions. Migration must trace imports, CLI ownership, tests, packaging, and runtime data flow before moving anything.

### Phase-A baseline audit — 2026-08-29

The separation branch is based on `origin/master` at `ed61f961`. The published `v0.1.4` release is a separate descendant lineage, and the unpublished local `campaign/v0.1.5-gold-repair` branch adds two further Gold-only commits. Migration must therefore treat the lineages differently:

- framework cleanup starts from `origin/master`;
- the complete experiment-asset source is the `v0.1.5` Gold lineage, which contains the `v0.1.4` additions;
- no Gold-only commit is merged wholesale into the framework cleanup branch.

The first dependency census found that the boundary is deeper than top-level manifests and campaign documentation:

- training, inference, and scoring entry points directly import the TIDMAD, Pets, and DAVIS data-path modules;
- `pyproject.toml` currently justifies a framework dependency on Pillow through the Pets and DAVIS built-in paths;
- 53 tests directly reference a real-task data path, manifest, or example pack;
- Gold-specific surfaces include campaign documentation, launchers, stage scripts, and campaign qualification tests;
- the existing synthetic `quickstart` pack is the leading candidate to remain, but its current L2 maturity does not yet cover the complete lifecycle;
- Pets and DAVIS currently carry important cross-task genericity evidence, so they cannot be removed until equivalent minimal synthetic evidence exists.

This audit changes migration sequencing but not scope: direct task imports must be removed through the supported declared loading boundary, and regression value must be preserved through synthetic examples before real-task assets leave SIDERIUS.

## 9. Release consequence

The published `v0.1.4` release contains Gold-specific campaign assets. It remains an immutable historical release and must not be rewritten.

The current local `campaign/v0.1.5-gold-repair` lineage contains two Gold-specific changes:

- Trial/Formal batch-parity configuration for Gold;
- a fresh `v015` Gold campaign identity.

As of this decision, that lineage has no published `v0.1.5` tag or GitHub release. Gold-specific release work must pause while the repository boundary is established. Those changes belong with the Gold campaign in `siderius-exp` unless analysis identifies a separately justified generic framework defect.

The next SIDERIUS release must not be qualified by silently bundling a specific campaign. Version choice and compatibility policy will be decided after the migration surface is known.

## 10. Migration plan

### Execution principle

The migration changes repository ownership, not scientific treatment or framework behavior. Each step must prefer copying before deletion, existing extension contracts before new abstractions, and delta validation before broad validation. Refactoring unrelated code, redesigning orchestration, changing task semantics, or introducing a new packaging layer is outside scope.

The active priority is restoration and clarification, not polish. SIDERIUS must
carry the smallest generic mechanism required by currently supported execution;
an anticipated extension does not justify infrastructure until a real supported
consumer needs it. A repair is successful only when the previously working path
still works, the responsibility boundary is clearer, and the caller-facing
configuration or failure message is at least as understandable as before.
Cosmetic refinement and speculative extensibility must not displace executable
parity, external-consumer qualification, or removal of confirmed task coupling.

New defects discovered by external task use must be filed in SIDERIUS when the failed responsibility belongs to a generic contract. The experiment repository may preserve a reproduction but must not carry a task-specific workaround for a framework defect.

### Progress estimate and milestone map

**Estimated overall completion: approximately 58%.** This is a planning
estimate, not acceptance evidence. It measures completion of the separation,
replacement evidence, external execution, and release qualification together;
it does not attempt to measure whether the framework could be improved
indefinitely. A milestone is complete only when its exit evidence is recorded
in this ledger.

| Milestone | Rough progress | Completion boundary | Current evidence or remaining gap |
|---|---:|---|---|
| M1. Repository boundary and consumer foundation | 95% | The ownership rule is frozen; `siderius-exp` exists; real tasks and Gold source assets are preserved with provenance and repository-local paths. | All four task packages, ordinary qualification experiments, campaign package stubs, and the external Gold source lineage exist. The first direct-asset test audit classifies all 38 executable references; the broader source/provenance census remains open. |
| M2. Known generic blocker closure | 99% | Every currently reproduced external-consumer defect is fixed generically, has a focused regression, and passes its external witness. This means no **known material blocker**, not a claim that infrastructure is bug-free forever. | Issues #383--#387, #389--#393, #395, and #396 are repaired and externally accepted. The #388 setup-only watchdog repair is merged with focused evidence; its H100 replay was supportive but completed below the historical failure boundary, so counterfactual-discriminative external evidence remains before closure. Merge-candidate qualification remains in M7. |
| M3. Minimal framework examples cover the supported lifecycle | 100% | Small CPU/offline examples collectively cover declaration through provenance, including semantic targets, metric direction, scoreability, Health, and resource admission. | Quickstart's deterministic scored handoff passes and demonstrates framework-provided objective selection. Synthetic masked regression covers a task-owned objective, task-owned Health through the evaluation codec, task-valid probe data, matched H100 admission/refusal, bounded production training over semantic supervision, literature-review ON/OFF topology, deterministic production-workflow traversal, record-level primary-only selection, checkout-portable resume/refusal, and standalone typed node invocation. All eleven assigned generic-contract tests plus the corrected observable-declaration module now use only generic fixtures. |
| M4. Physical framework/experiment separation | 92% | SIDERIUS packages no real task, campaign, pod, deployment, or scientific-result asset; a read-only checkout plus one configured workspace supports the full lifecycle without ambient generated-capability state; all supported framework behavior remains covered by minimal examples and TIDMAD behavior parity. | Real example packs and task helper tools are removed after synthetic replacement coverage; Pets and DAVIS runtime implementations are task-local in `siderius-exp`; Gold and X9 launch ownership and tests are external; undeclared prompt guidance, Health science, reference evidence, literature settings, and task configuration now resolve absent instead of selecting TIDMAD. Literature configuration is caller-owned and its cache is workspace-owned; Stage-3 and Gold launch assets have external owners; 52 task-owned reference/result files are removed after exact external parity. The distribution excludes diagnostic scripts and the legacy checkout-level generated library. The anchor map remains until the legacy scoring CLI that selects it implicitly is migrated as one bounded unit. Remaining work includes that and other deeper legacy TIDMAD compatibility paths, historical documentation classification, final packaging scans, and exact-revision external qualification. |
| M5. TestPod external-task qualification | 75% | Pets, DAVIS, and Cancer Gene Identification each complete a bounded end-to-end run from `siderius-exp` against one exact SIDERIUS revision, with valid scoring and best-score-versus-iteration evidence. | A synchronized four-task matrix at SIDERIUS `3eb8fc67` / `siderius-exp` `b3bb1c2` proves two-iteration external execution, Formal behavior, metric direction, Health routing, and cross-iteration state. DAVIS and Cancer produced valid scientific scores; Pets and TIDMAD were correctly invalidated. Merge-candidate qualification and the remaining task-level scientific evidence stay open. |
| M6. Gold workflow portability and dry-run qualification | 55% | The Gold workflow runs from `siderius-exp`, uses the same qualified framework execution core, preserves four-band Stage 1 and Stage-2 refusal, and starts from a fresh campaign identity without inheriting invalidated state. | `siderius-exp` PR #9 requires an explicit SIDERIUS checkout, executes that checkout's existing chain, binds campaign-owned task and calibrated Health files, passes a separated Stage-1 dry-run, refuses a changed task config, and keeps Stage 2 unauthorized. The broader imported deployment preflight, campaign-only test migration, duplicate SIDERIUS asset removal, and final H100/release qualification remain. |
| M7. Integrated qualification and release | 0% | One final SIDERIUS merge-candidate passes canonical automatic CI; `siderius-exp` records both repository SHAs; release contents satisfy the boundary scan. | Intentionally deferred until M2--M6 produce the required evidence. |

Percentages are deliberately coarse and may move non-linearly. Finding a new
generic blocker can add work to M2 without invalidating completed evidence;
discovering an optional improvement does not reopen a milestone unless it is a
material correctness, portability, or supported-contract defect.

### Shared infrastructure and campaign-specific orchestration

GoldPod, TestPod, and different scientific tasks must use the same SIDERIUS
execution mechanisms wherever their responsibilities are the same:

~~~text
siderius-exp task declaration and campaign policy
  -> SIDERIUS composition and typed contracts
  -> shared training, inference, scoring, Health, resource, and provenance core
~~~

Their differences belong above that shared core:

| Concern | TestPod exploratory tasks | Gold campaign |
|---|---|---|
| task package and scientific metric | task-specific declarations in `siderius-exp` | frozen TIDMAD declarations in `siderius-exp` |
| search policy and budget | exploratory and task-sized | operator-approved frozen treatment and production budgets |
| literature review | controlled ON/OFF ablations are allowed | ON and frozen |
| Stage 1 topology | task-specific exploratory runs | four independent bands |
| result selection | task-specific best-score-versus-iteration evidence | per-band Stage-1 selection and later portfolio construction |
| Stage 2 | not applicable unless a task declares its own campaign | explicit operator authorization required; currently unauthorized |
| execution machinery | shared SIDERIUS core | the same shared SIDERIUS core |

Gold may own a unique orchestration workflow, but it must not fork training,
inference, scoring, Health, resource admission, or provenance mechanisms. A
Gold-only execution mechanism is a boundary defect unless an explicit frozen
requirement cannot be represented through the supported framework contracts.

### TIDMAD behavior-preservation track

Repository separation must not change TIDMAD scientific or campaign behavior.
The comparison authority is the frozen pre-separation TIDMAD/Gold lineage
recorded in this ledger, evaluated against the separated
`siderius-exp -> SIDERIUS` composition with the same declared inputs. A
separation change is not allowed to reinterpret a mismatch as an improvement;
any unexplained semantic delta stops removal or release qualification.

The following values require parity wherever the applicable frozen evidence
can exercise them:

- resolved task composition, model I/O contract, objective, primary metric,
  metric direction, secondary metrics, scoreability contract, and Health
  semantics;
- training and evaluation scope identities, sample order, target semantics,
  epoch and data-portion limits, Trial/Formal configuration, and candidate
  model/loss configuration;
- inference ordering, deliverable naming and content, scoring inputs, per-file
  values, aggregate score, Health routing, and persisted scientific records;
- declared resource budgets, admission policy, watchdog policy, and execution
  argv after normalizing only checkout-specific absolute paths;
- Gold literature review ON, four independent Stage-1 bands, per-band
  selection, fresh campaign identity, no inheritance from invalidated runs,
  and Stage-2 refusal without explicit operator authorization.

Not every quantity can or should be byte-identical. Absolute repository paths,
plugin locations, repository SHAs, timestamps, measured wall time, hardware
identity, and other provenance facts are expected to describe the new
environment. They may differ only in their owned fields and must not alter the
scientific treatment or execution decision. Randomized behavior is compared
under the same seed and declared scope; hardware-dependent measurements are
checked for policy and provenance correctness rather than false numeric
identity across devices.

Parity is enforced incrementally:

1. copy each TIDMAD or Gold asset with a content hash before deleting its
   framework copy;
2. classify every intentional portability edit separately from semantic code;
3. run a bounded old-versus-separated witness for the touched behavior before
   removing the old path;
4. compare resolved executable artifacts, not design prose or historical
   memory;
5. retain the old artifact and stop the migration step when a mismatch is
   unexplained;
6. before release, run one integrated TIDMAD dry-run and the smallest bounded
   execution needed to cover data loading, training, inference, deliverable
   writing, scoring, Health, and persistence through the separated boundary.

The bounded parity execution is engineering qualification, not a new Gold
campaign and not Stage 2. It must not resume, mutate, or inherit from any
invalidated campaign workspace.

### Phase A — inventory and freeze

- [x] Freeze the repository-separation principle.
- [x] Record the minimal-example requirement.
- [x] Record the current `v0.1.5` publication state.
- [ ] Produce a path-by-path ownership inventory.
- [ ] Identify imports and tests that cross the proposed boundary.
- [x] Define the minimal-example coverage matrix.

Validation:

- repository ownership inventory accounts for every proposed moved path;
- import and entry-point census identifies each cross-boundary dependency;
- no production files move or change behavior in this phase;
- `git diff --check` and document-link checks pass for the ledger update.

### Phase B — establish the consumer repository

- [x] Create the private `siderius-exp` repository.
- [x] Define its initial package, environment, and exact-SHA dependency layout.
- [x] Copy task and campaign assets without deleting the source copies yet.
- [x] Preserve provenance for the imported task and campaign batches.
- [x] Prove real tasks run against an unmodified pinned SIDERIUS checkout.

Validation:

- a clean `siderius-exp` checkout installs an exact SIDERIUS SHA;
- campaign and task dry-runs resolve all paths from the experiment checkout or explicit configuration;
- no experiment file is imported by SIDERIUS;
- copied artifacts retain content hashes or have an explicit, reviewed portability change;
- no source asset is deleted from SIDERIUS until the copied consumer path is demonstrated.

### Phase B.5 — repair generic blockers exposed by consumers

- [x] Reproduce SIDERIUS #383 from `siderius-exp` through public contracts.
- [x] Repair #383 in SIDERIUS without a task-name branch.
- [x] Reproduce SIDERIUS #384 from `siderius-exp` through public contracts.
- [x] Repair #384 in SIDERIUS without a task-name or loss-name branch.
- [x] Reproduce SIDERIUS #385 from `siderius-exp` through public contracts.
- [x] Repair #385 at the generic inference-to-deliverable boundary without a task-name or deliverable-format branch.
- [x] Reproduce SIDERIUS #386 while composing external non-TIDMAD tasks.
- [x] Repair #386 so generic workflow import resolves no task-specific data configuration.
- [x] Repair #387 so an absent optional preflight time estimate remains a declared absence rather than reaching `float(None)`.
- [x] Repair #388 so setup-only watchdog evidence cannot shorten a valid task run to the minimum deadline.
- [x] Repair #389 so task-owned variable-shape inference limits constrain both admission selection and execution.
- [x] Repair #390 so the normal chain launcher forwards a task-owned literature-review config.
- [x] Repair #393 so generic inference cannot write a summary dictionary to the legacy per-file timing sidecar.
- [x] Re-run the external #393 witness through persisted attempt construction without repeating an unchanged failed run.
- [ ] Pin `siderius-exp` to the qualified SIDERIUS repair revision.

Validation:

- each issue has one focused framework regression naming the exact defect;
- existing fail-closed behavior remains covered;
- targeted subsystem tests and relevant static checks pass in SIDERIUS;
- the external consumer reproduction passes without patching SIDERIUS or weakening task validation;
- unaffected lightweight framework probes retain their prior result;
- no full CI is run manually when the final SIDERIUS PR workflow will provide the same evidence.

The known issues are repaired after the consumer boundary exists but before source assets are removed from SIDERIUS. This ordering makes `siderius-exp` the external acceptance witness while keeping each repair owned and reviewed in the framework repository.

### Phase C — complete framework examples

- [x] Select the smallest set of examples that collectively covers the lifecycle.
- [x] Replace the bounded real-task test dependencies in this checkpoint with behavior-preserving synthetic fixtures.
- [x] Add a coverage matrix that maps each lifecycle contract to at least one example.
- [x] Verify CPU, offline, and checkout-portable execution.

#### Phase-C coverage audit — 2026-08-29

The target is **two** minimal packs, not one pack per removed real task:

1. mature the existing `quickstart` classification pack;
2. add one tiny synthetic masked-regression pack for the materially different
   contract shapes quickstart should not absorb.

A third pack is not authorized by this plan unless the executable matrix finds
a contract that cannot be represented honestly by those two. TIDMAD is not a
minimal framework example; it remains a real task in `siderius-exp` and is
protected by the separate behavior-preservation track above.

Current evidence and gaps:

| Capability | Current quickstart evidence | Required minimal owner | Gap before real-pack removal |
|---|---|---|---|
| task declaration and fail-closed composition | proven | quickstart | none |
| model plugin loading and content identity | proven | quickstart | none |
| task-owned train/eval scope construction and canonical serialization | proven | quickstart | none |
| deterministic split non-overlap | train and evaluation shards are distinct | quickstart | promote the existing fact into the final matrix |
| training dataset and scalar semantic class target | proven | quickstart | none |
| classification and higher-is-better primary metric | proven | quickstart | none |
| inference codec, declared naming, scoreability, and metric computation | deterministic production handoff proven with exact `37/64` score | quickstart | live agent-chain tuner record remains historical evidence, not a prerequisite for framework-example separation |
| interpret -> propose -> implement -> validate | live bounded evidence exists | synthetic masked regression | deterministic typed substitutes traverse the production workflow in exact order; no live LLM execution is claimed |
| tune and real CPU training | live bounded evidence exists | quickstart | retain a bounded deterministic component witness |
| optional literature-review invocation | an explicit non-default config invokes the offline advisor substitute and passes its four channels to the proposer; OFF neither reads a missing config nor invokes the advisor | synthetic masked regression workflow exercise | none for the framework topology; live retrieval is optional external evidence |
| explicit absence of task Health | proven as `EXPLICIT_NONE` | quickstart | retain; do not replace it with a Health roster |
| continuous regression and lower-is-better ordering | composed and scored deterministically | synthetic masked regression | none for the core metric path |
| custom objective with a semantic target beyond shape and dtype | masked MSE consumes `[truth, validity_mask]`; a `[B,1]` shape surrogate refuses; the production training engine completes one bounded CPU optimizer step and persists the model | synthetic masked regression | none |
| task-owned Health plugin and continuous view | constant task artifact FAILS; varied task artifact PASSES through the declared blocking gate | synthetic masked regression | none |
| secondary observational metric | composed masked MAE executes beside primary masked MSE; a conflicting MAE/MSE control proves persisted ranking selects only by masked MSE | synthetic masked regression | none |
| prediction-aligned source/target deliverable context | real minimal codec rematerializes source and persists aligned prediction/target/mask rows | synthetic masked regression | none |
| resource measurement and admission over a task-valid batch | isolated production worker materializes real `[B,3]` input plus semantic `[B,2]` target; matched H100 controls measured `0.229 GB`, admitted under `1.0 GB`, and refused under `0.001 GB` | synthetic masked regression | physical GPU evidence is recorded separately from ordinary CI; no remaining example gap |
| persistence, run identity, and resume/comparability refusal | byte-identical copies at unrelated roots share a fingerprint and validate one workspace; a declared-plugin edit changes the fingerprint and refuses without rewriting the lock | synthetic masked regression | none for the composition-identity boundary |
| standalone node invocation | the interpretation node accepts `InterpretationInput` and returns `InterpretationOutput` directly with no workflow state or LLM call on its deterministic cold-start path | synthetic masked regression | none for the public typed-call boundary |
| complete supported composition | no scored quickstart chain | both packs collectively | deterministic production-workflow traversal plus real component execution are proven separately; live LLM execution remains outside ordinary CI |

The planned synthetic regression task is deliberately small: fixed generated
tabular or short-vector inputs, continuous outputs, an explicit supervision
mask, a lower-is-better metric, and a few CPU batches. It must not imitate
TIDMAD geometry, DAVIS video structure, a scientific dataset, or a campaign.
Its purpose is to preserve framework contract diversity, not task realism.

#### Real-task test disposition

A lexical census currently finds 54 Python test files naming Oxford-IIIT Pets,
49 naming DAVIS future prediction, and 262 naming TIDMAD. These counts are an
inventory signal, not a deletion count: one file may mention a task only in
historical prose, while another may own several non-equivalent behaviors.
Each test is classified by the defect it catches before it moves:

| Bucket | Destination | Rule |
|---|---|---|
| generic contract test using a real task as convenient input | SIDERIUS | replace only the fixture with quickstart or synthetic regression; preserve the original failure class |
| real dataset acquisition, task declaration, plugin, metric, Health threshold, baseline, or scientific result | `siderius-exp` | move with task provenance and qualify against a pinned framework revision |
| TIDMAD or Gold behavior required for migration parity | `siderius-exp` parity suite | compare frozen old and separated paths before deleting the old source |
| historical guard whose landed generic invariant has another authority | archive or retire after review | removal requires naming the surviving authority; test count reduction alone is not a reason |

The first direct-asset audit narrows the lexical census to 38 Python files that
actually reference a shipped real-task manifest, task Health file, legacy
machine-data config, Gold launcher, advice artifact, or baseline artifact.
This is the migration queue, not an authorization to delete. Its reviewed
disposition is:

| Disposition | Count | Files | Required action before removal |
|---|---:|---|---|
| move with experiment/campaign ownership | 18 | `tests/helpers/{health_task_config,step09_5a_llm_parity_capture}.py`; `tests/unit/agent/tune_ml_hyperparam_agent/test_dbud6_mode_aware_epoch_caps.py`; the five shipped-task declaration/quickstart modules under `tests/unit/examples/`; the seven directly matched Gold/data launcher modules under `tests/unit/sdsc_submission_scripts/`; `tests/unit/workflows/{test_step00_task_config_baselines,test_step12_pr12a_c7_proposal_blocks,test_step12_pr12d_checkpoint_b}.py` | Copy to `siderius-exp`, make every path consumer-repository-local, and pass against one pinned SIDERIUS SHA. TIDMAD behavior tests additionally require old-versus-separated parity. |
| keep in SIDERIUS after replacing the real fixture | 11 | `tests/unit/core/{test_fscanf1_formal_eval_portion_lock,test_advice_identity_lock}.py`; `tests/unit/execute_tools/health_checks/test_c12p_cp12_composition_cache_authority.py`; `tests/unit/execute_tools/test_step12_pr12d_f12d27_training_scope_transport.py`; `tests/unit/ml_models/test_step12_pr12d_dp_plugin_binding.py`; `tests/unit/tools/ci/{test_preflight,test_provenance}.py`; `tests/unit/workflows/{test_arxiv_286_neutral_start_census,test_step10_p2b_c1_secondary_declaration,test_step12_pr12d_d1_task_instance_config,test_step12_pr12d_f12d31_objective_authority}.py` | Preserve the named generic failure class while replacing task/campaign values with quickstart or synthetic-regression declarations. `test_step12_pr12d_f12d31_objective_authority.py` was initially blocked on the bounded production-training witness; that prerequisite is now satisfied, but its mixed generic and DAVIS-incident responsibilities must be split before replacement. |
| split mixed framework and real-task responsibilities | 7 | `tests/conftest.py`; `tests/unit/execute_tools/health_checks/test_config_loader.py`; `tests/unit/execute_tools/test_step12_pr12d_d4a_scoring_restructure.py`; `tests/unit/guardrails/test_step12_pr12d_d0_baselines.py`; `tests/unit/workflows/{test_step10_p56_c0_three_task_baseline,test_step10_p56_c5_wiring_closures,test_step12_pr12d_checkpoint_a}.py` | Keep generic schema, routing, subprocess, and aggregation guards in SIDERIUS; move exact TIDMAD/Pets/DAVIS declarations and historical parity assertions. Run both halves together before deleting the original mixed module. |
| lexical match only; no real-asset dependency | 1 | `tests/unit/tools/test_user_contract_docs_census.py` | Keep. The match is a deliberately forbidden documentation example, not an executable task binding. The observable-declaration module was incorrectly assigned here: it composed all shipped real-task manifests and has now been converted to Quickstart-only evidence. |

All eleven fixture replacements are complete. `test_step12_pr12d_f12d27_training_scope_transport.py`
now uses the synthetic masked-regression pack and generated temporary shards
instead of a machine-specific Pets data root. Its original failure class is
unchanged: composed training and evaluation scopes must reach the training
child when no legacy `SampleSet` exists. `test_advice_identity_lock.py`, renamed
from `test_gold_advice_identity_lock.py`, now uses task-neutral run/advice paths
and terminology while preserving the original five-row content-identity
comparability matrix. `test_fscanf1_formal_eval_portion_lock.py` now uses a
task-neutral bounded qualification fraction rather than naming the Gold
campaign; its compared-value, legacy-resume, persistence, and transport failure
classes are unchanged. `test_arxiv_286_neutral_start_census.py` now uses the
quickstart and a temporary declared-naming task variant as its positive,
negative-control, and omitted-naming witnesses instead of composing the shipped
TIDMAD and Pets assets. The census still searches for the exact anchor tokens,
and all composition calls now unwind through the existing registration scope so
the test cannot poison a later task registry.
`test_step12_pr12d_dp_plugin_binding.py` now derives its production-composition
witness from quickstart plus a generic declared-naming task-data-path fixture
instead of copying the shipped TIDMAD manifest and pinning TIDMAD's scientific
fingerprint. Omitted and explicit-none sections are compared counterfactually;
declared plugin content must still move the fingerprint, and every malformed
section keeps its named refusal. `test_provenance.py` now injects task-neutral
machine-config and external-resource declarations and asserts their exact
present/absent states instead of naming the current TIDMAD, Pets, and DAVIS
deployment resources. Production preflight defaults remain unchanged; moving
those defaults is a separate source-ownership step. `test_preflight.py` now
exercises machine-config presence and tracked-template
absence with task-neutral names. Its external-resource declaration guard keeps
the generic non-empty/measured invariant without freezing the current task
inventory or aggregate skip count. Production preflight defaults remain
unchanged. `test_step12_pr12d_d1_task_instance_config.py` now uses a temporary
external task-data-path plugin and framework-owned Quickstart declarations
instead of copying shipped scientific-task assets. All nineteen original
failure classes still enter through the production composition authority:
fail-closed section and constructor validation, task-owned reference
resolution, training/evaluation scope construction, registry precedence, and
semantic identity. The Health composition-cache module now uses two temporary
synthetic plugin families while preserving cold/warm parity, memo invalidation,
run-scope discrimination, and tuner-first resolution. The objective-authority
module now uses only Quickstart, synthetic masked regression, and temporary
plugins while preserving declaration precedence, fail-closed parsing, content
identity, relocation, shadow refusal, and fresh-process composition. Real-task
Health and objective parity landed first in `siderius-exp` PR #1. The
historical counts above remain the audit baseline
rather than being rewritten after each completion.

The 38-file queue is complete only for the explicit path families named above.
The broader 680-file lexical set remains a later source-removal census because
task names in prompts, comments, golden records, and legacy compatibility code
may still require ownership decisions even when they do not load a real asset.
No test moves merely because it appears in either count.

The first implementation checkpoint will cover quickstart only: make its
component evidence matrix explicit and close the deterministic composed
scoring gap without changing its task semantics. The synthetic regression pack
is the next checkpoint. Real-task files remain in SIDERIUS until both
replacement evidence and the applicable parity witness pass.

Validation:

- the coverage matrix maps every supported lifecycle phase to at least one example;
- each example passes independently on CPU with no network, API key, private data, or external repository;
- the combined pseudo or deterministic suite traverses the complete lifecycle;
- split-overlap checks, metric direction, scoreability, Health, and admission assertions fail when their owned behavior is deliberately broken;
- optional real-API or GPU evidence is kept separate from ordinary CI.

### Phase D — remove duplication from SIDERIUS

- [x] Move or retire Gold Stage-1/Stage-2 launchers and campaign-only tests in this checkpoint.
- [x] Move the four real task packages and their active package documentation.
- [x] Remove implicit task guidance, Health defaults, and Pets/DAVIS runtime imports from the touched framework surfaces.
- [x] Move the X9 two-arm launch, preflight, H100 posture, probe, and their campaign-only tests to `siderius-exp`.
- [ ] Preserve only explicitly approved historical records, with clear archive labeling.
- [ ] Run targeted boundary and packaging validation.

Validation:

- SIDERIUS package build contains no real task, campaign, pod, or deployment asset;
- source and packaging scans reject forbidden experiment identifiers and paths;
- SIDERIUS minimal examples pass without `siderius-exp` present;
- `siderius-exp` real-task dry-runs and selected bounded executions pass against the pinned SIDERIUS revision;
- public imports used by `siderius-exp` are documented supported surfaces;
- every removed TIDMAD/Gold surface has a recorded old-versus-separated parity witness, or a documented proof that it is provenance-only and execution-inert;
- removal commits contain no unrelated behavior change.

### Phase E — qualify and release

- [ ] Qualify SIDERIUS independently through its minimal examples.
- [ ] Qualify `siderius-exp` against an exact SIDERIUS revision.
- [ ] Record both repository SHAs in experiment evidence.
- [ ] Decide the next SIDERIUS version from the actual compatibility delta.
- [ ] Publish only after the repository boundary is verified.

Validation:

- targeted evidence from Phases B--D is recorded in this ledger;
- one canonical automatic SIDERIUS PR CI run passes on the final merge-candidate SHA;
- `siderius-exp` qualification records both repository SHAs and resolved task identities;
- Gold dry-run resolves the intended fresh campaign identity, Trial/Formal batch policy, frozen treatment, budgets, and Stage-2 refusal from `siderius-exp`;
- no Gold workload is required to prove repository packaging, while any later scientific launch remains subject to its own hardware qualification;
- release contents are inspected before tag and publication.

## 11. Decision log

| Date | Decision | Status |
|---|---|---|
| 2026-08-31 | Complete Phase D and then Phase E autonomously, keeping this ledger current and using bounded four-task qualification when it provides necessary evidence. Maintainability rules are critical-path guardrails: use bounded responsibility-oriented refactoring when a touched boundary is unsafe, but do not turn campaign readiness into a broad cleanup project. | ACTIVE OBJECTIVE |
| 2026-08-29 | Separate reusable infrastructure from real scientific tasks and campaigns using a private `siderius-exp` consumer repository. | FROZEN |
| 2026-08-29 | Keep lightweight minimal examples in SIDERIUS; collectively they must cover the supported end-to-end lifecycle. | FROZEN |
| 2026-08-29 | Minimal examples are executable framework specifications, not scientific benchmarks or campaigns. | FROZEN |
| 2026-08-29 | `siderius-exp` depends on an exact qualified SIDERIUS tag or SHA; SIDERIUS never depends on `siderius-exp`. | FROZEN |
| 2026-08-29 | GoldPod, TestPod, and all task packages share the same SIDERIUS execution core; campaign-specific topology and treatment remain in `siderius-exp`. | FROZEN |
| 2026-08-29 | Repository separation may change ownership and explicit paths but must preserve frozen TIDMAD scientific and campaign behavior through incremental old-versus-separated parity evidence. | FROZEN |
| 2026-08-29 | Two minimal packs are the default complete framework example set: mature quickstart plus one synthetic masked-regression contrast; a third requires an executable contract gap. | FROZEN |
| 2026-08-29 | Do not publish the current Gold-specific `v0.1.5` lineage before the separation is reconciled. | ACTIVE HOLD |
| 2026-08-29 | Gold is stopped. Current execution work is limited to TestPod; Gold portability remains a later separation milestone and no Gold workload may be resumed or launched during this hold. | ACTIVE HOLD |
| 2026-08-29 | Generic deliverable writing carries an optional typed source context so a task can rematerialize prediction-aligned values through its own validation data path. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | Active migration work prioritizes executable restoration and clearer caller boundaries over polish or speculative extension points; a repair must preserve the proven path and improve or retain the caller-facing failure/configuration surface. | FROZEN |
| 2026-08-29 | Generic workflow import performs no task selection; legacy TIDMAD/SIDERIUS machine configuration resolves lazily on first legacy value access. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | Round-level production-policy comparison must resolve under the composed run's task-owned Health binding; repaired without weakening plugin isolation. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | A composed run's VRAM worker must obtain one semantic training batch through the existing task-data contract; shape-and-dtype synthesis remains only for legacy runs without a task-owned scope. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-31 | Any run may enable the existing literature-review node only with an explicit caller-owned config; SIDERIUS ships no scientific literature default and stores the cache under the run workspace. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | Real-task qualification may use a smaller set of complete task instances, but formal scientific comparison must use the comparator's complete dataset and evaluation protocol. Cancer qualification uses complete `cpdb` and `ltg`; its formal workflow retains all eight networks. | FROZEN |
| 2026-08-29 | The framework transports generic sampling parameters through `TaskDataPath.training_dataset`; each task owns the meaning of its sampling units and may refuse unsupported fractional semantics. No universal sampler is introduced. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | A task selects a framework-provided objective through validated `objective.config`, or supplies new behavior through `objective.implementation`; exactly one form is allowed and both resolve to the existing `LossConfig` boundary. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | Health view providers consume the task-owned evaluation codec through a lazy context reader. They must not reconstruct artifact filenames or storage layouts owned by another task. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | A generic launch does not impose a Formal-only minimum batch size. A task or campaign may opt into an explicit floor, but Trial success is otherwise executable evidence for the same batch size in Formal. | IMPLEMENTED ON SEPARATION BRANCH |
| 2026-08-29 | Output representation is an explicit experiment lock when scientific comparability requires one. Pets qualification locks `classifier`; DAVIS and Cancer qualification lock `regressor`; the generic framework retains its intentionally unconstrained compatibility mode. | IMPLEMENTED IN `siderius-exp` |

## 12. Migration evidence ledger

| Date | Repository | Commit or issue | Evidence and disposition |
|---|---|---|---|
| 2026-08-31 | SIDERIUS / `siderius-exp` | `b6734073` / `14da21f` | Removed the committed scientific task default and made no-argument task loading fail closed unless a composition binding is active. Run snapshots now serialize the bound declaration rather than copying repository science. The copyable example is synthetic. Wheel ownership excludes diagnostic scripts and the checkout-level generated library; direct wheel inspection found 312 files and no file under either forbidden tree. Focused framework validation passes 35 tests; external task/boundary validation passes 53 tests and Gold campaign validation passes 116 tests against the exact pin. A safety review correctly refused premature deletion of `reference_data/segment_anchors.json`: the legacy scoring CLI still selects it implicitly, so the artifact and CLI remain one pending migration unit. Official Codex documentation exposes compaction guidance but no supported post-compaction command hook; `CLAUDE.md` therefore carries the enforceable repository instruction to reread this ledger after compaction instead of pretending a runtime hook exists. |
| 2026-08-30 | `siderius-exp` | `bd2ec37` | Pinned the consumer repository to SIDERIUS `63b98b58bd18b91ee840b8d1326bb292ef8cd893` after task-default and duplicate-asset retirement. The external task, startup, extension-boundary, and campaign suite passes 135 tests against that exact checkout; task-package Ruff, formatting, and diff integrity pass. Historical provenance records retain the framework revisions they actually exercised. |
| 2026-08-30 | SIDERIUS / `siderius-exp` | task-default and duplicate-asset retirement checkpoint | Removed the four in-framework real task packs, Pets/DAVIS runtime implementations and Gate launchers, and duplicate Gold Stage-1/Stage-2 launch ownership after their external replacements landed. Undeclared interpretation, proposal, implementation, and Health inputs now resolve to empty validated values rather than TIDMAD science; explicit task declarations remain fail-closed. Generic Health execution, chain compatibility, synthetic examples, and task-neutral plugin contracts remain in SIDERIUS. The final changed-file suite passes 336 tests; the focused default/boundary suite passes 214 with 11 environment-independent skips; collection discovers 14,128 tests without errors; Ruff, formatting, and diff integrity pass. Stage-3/reference assets and deeper legacy TIDMAD compatibility remain separate later slices. |
| 2026-08-30 | SIDERIUS | workspace bytecode boundary repair | The supported chain and direct one-iteration entrypoints now disable Python bytecode writes before importing framework modules, so external task execution cannot place ignored cache files in the SIDERIUS checkout. A focused launcher witness covers the preflight probes, and a source-order regression protects direct invocation. No task semantics, generated-module location, or workspace artifact contract changed. |
| 2026-08-29 | `siderius-exp` | `108dea0` | Private consumer repository created with one-way SIDERIUS dependency, explicit directory ownership, exact `v0.1.4` commit pin, and migration provenance rules. |
| 2026-08-29 | `siderius-exp` | `6a71218` | Gold campaign documents, task overlays, launchers, and state helpers imported byte-identically from SIDERIUS `624e1a93`; per-file SHA256 manifest recorded. Imported assets are explicitly not yet portable or launch-qualified. |
| 2026-08-29 | `siderius-exp` | `4ec9177` | TIDMAD, Oxford-IIIT Pet, DAVIS future prediction, and Cancer Gene Identification task packages imported from their recorded source revisions; no framework source was deleted. |
| 2026-08-29 | `siderius-exp` | `3b1dded` | Repository ignore rules narrowed to root data directories so task-owned data manifests remain versioned; the omitted TIDMAD runtime implementation was restored and added to the import hash record. |
| 2026-08-29 | `siderius-exp` | `748824f` | Four real task manifests changed to package-local references and existing file-based loading; all four composed successfully against a clean checkout of pinned SIDERIUS `98610b8d`. No framework source change was needed. The unsuppressed TIDMAD import warning produced issue #386. |
| 2026-08-29 | `siderius-exp` | `8845087` | External issue #383 witness preserved. It fails against pinned SIDERIUS `98610b8d` with the task-owned Pets plugin roster followed by a legacy empty-roster request, and passes against repair `f23c4e7f`. No dataset or training is involved. |
| 2026-08-29 | `siderius-exp` | `0962876` | External issue #384 witness preserved with a temporary task-valid graph fixture. It fails against pinned SIDERIUS `98610b8d` before capacity evaluation because the synthesized zero target has no labeled rows, and passes through isolated resource measurement against repair `c6ce7640`. |
| 2026-08-29 | SIDERIUS | `49f3f8be` | Separation design and work ledger established on `refactor/framework-exp-separation`. |
| 2026-08-29 | SIDERIUS | #383 | Composed task Health binding was lost during round evaluation; reproduced externally and repaired by `f23c4e7f`. |
| 2026-08-29 | SIDERIUS | #384 | VRAM admission probes could not construct task-valid semantic targets; reproduced externally and repaired by `c6ce7640`. |
| 2026-08-29 | SIDERIUS | #385 | Generic inference dropped the physical source needed by some valid scientific deliverables; reproduced externally and repaired by `26c1cbd8`. |
| 2026-08-29 | `siderius-exp` | `8b197d5` | External issue #385 witness preserved with a temporary source-aware task. It fails against pinned SIDERIUS `98610b8d` because the writer receives no physical source, and passes against `26c1cbd8` with prediction/target order preserved. |
| 2026-08-29 | SIDERIUS | #386 | Generic workflow import selected and read legacy TIDMAD machine configuration before task composition; reproduced externally and repaired by `e26718db`. |
| 2026-08-29 | SIDERIUS | #387 | The proposer preflight converted an explicitly absent optional estimate with `float(None)`; repaired by `52e3e8e0` without inventing a fallback estimate. |
| 2026-08-29 | SIDERIUS | #388 | Setup-only watchdog evidence collapsed a valid task deadline to the 120-second minimum. The external failure record remains the reproduction; focused repair evidence is recorded at `b6990340`, with external replay still required before closure. |
| 2026-08-29 | SIDERIUS | #389 | Generic inference selected a batch without consulting task-owned variable-shape constraints, then attempted to stack complete graphs with different record counts; repaired by `60fffb1e`. |
| 2026-08-29 | SIDERIUS | #390 | The chain launcher exposed literature-review topology flags but rejected the iteration runner's existing task-owned config flag; repaired by `384cc9e8`. |
| 2026-08-29 | SIDERIUS | #391 | Composed generic inference eagerly retained every raw prediction before task persistence. A 5,000-sample TIDMAD classification scope could approach 80 GiB of host memory and was killed before writing. Repaired by `a4e63655` using the existing iterable writer contract. |
| 2026-08-29 | SIDERIUS | #392 | The time warmup constructed `execute_tools.tidmad_data_path.TidmadScope` even when the active binding came from an external task plugin. Repaired by `d53ac914` using the attempt's existing task-owned scope and existing `max_samples` materialization bound. |
| 2026-08-29 | SIDERIUS | #393 | Generic inference wrote its summary dictionary to the legacy per-file timing sidecar. Scoring and Health completed, but attempt persistence sliced the dictionary as a list and failed with `KeyError`. Repaired and externally accepted by `7476bf44`; the issue is closed. |
| 2026-08-29 | `siderius-exp` | `9db069d` | External issue #386 witness preserved. It promotes the TIDMAD missing-config warning to an exception, fails against `98610b8d`, and composes Cancer Gene Identification successfully against `e26718db`. |
| 2026-08-29 | SIDERIUS | `f23c4e7f` | Issue #383 repaired by carrying the existing task Health binding into round-level production-policy composition. The run-scope guard remains unchanged. Focused Health tests pass: 22 passed. |
| 2026-08-29 | SIDERIUS | `c6ce7640` | Issue #384 repaired by transporting the resolved task manifest identity and serialized training scope to the existing isolated worker, which materializes one full batch through `TaskDataPath.training_dataset`. No task or loss name appears in framework logic; legacy synthetic probes and CPU-only behavior remain. Focused resource and node-boundary tests pass: 122 passed; Ruff and `git diff --check` pass. Local pyright was unavailable and remains assigned to final PR CI. |
| 2026-08-29 | SIDERIUS | `26c1cbd8` | Issue #385 repaired by adding an optional typed source context to the existing deliverable-write request. Generic inference supplies the physical data root, sample count, and fixed validation-dataset ordering contract; tasks remain responsible for rematerialization and mismatch refusal. The frozen four-method data-path contract and prediction-only behavior remain unchanged. Focused compatibility tests pass: 76 passed; Ruff and `git diff --check` pass. |
| 2026-08-29 | SIDERIUS | `e26718db` | Issue #386 repaired by deferring legacy TIDMAD/SIDERIUS machine-config resolution until a legacy value is actually requested. Generic workflow import and explicit composed-root refusal no longer consult task-specific configuration; historical constant imports and legacy warning/failure semantics remain. Focused tests pass: 100 passed; Ruff and `git diff --check` pass. |
| 2026-08-29 | SIDERIUS | `52e3e8e0` | Issue #387 repaired at the optional-estimate boundary. The proposer preflight preserves `None` instead of converting it to a float; focused tests and static checks pass. |
| 2026-08-29 | SIDERIUS | `60fffb1e` | Issue #389 repaired through an optional task-owned inference batching protocol. The isolated probe carries the declared maximum, the generic batch resolver selects only within it, and execution rechecks it before materialization. Focused validation passes: 61 tests, Ruff, and `git diff --check`. A two-network real-data checkpoint witness selected batch 1, emitted two batches, and reproduced mean validation AUPRC `0.2677163024212869`. |
| 2026-08-29 | SIDERIUS | `384cc9e8` | Issue #390 repaired by transporting the iteration runner's existing `--ml_lit_review_config` flag through `_chain_common.sh`. Five focused chain-forwarding tests, shell syntax, external dry-run, and `git diff --check` pass. |
| 2026-08-31 | SIDERIUS + `siderius-exp` | pending | Removed SIDERIUS's task-owned literature YAML and repository cache location. Enabled runs now require an explicit caller config before any LLM/GPU work, and the node cache resolves under the run workspace. Focused node/workflow tests pass (98), Ruff passes, and the external startup/TIDMAD ownership/frozen-treatment witnesses pass (15) against this checkout. |
| 2026-08-29 | `siderius-exp` | `6b30404` | The TIDMAD quickstart ran from the external package through literature review, proposal, implementation, seven validation checks, and tuner admission on an RTX 5090. Training refused before model execution because the child pre-imported SIDERIUS's built-in `tidmad` registration while the parent pinned the byte-identical external implementation; their content digests match, but their implementation module identities deliberately differ. This is direct evidence for M4's planned removal of built-in task bootstrap imports, not permission to weaken identity verification. |
| 2026-08-29 | SIDERIUS | `5ccecd4f` | Real-task modules no longer mutate the task-data-path registry merely by import. Composed children resolve the transported manifest and verify its parent-pinned identity; explicitly uncomposed callers retain one bounded legacy TIDMAD bootstrap. Focused validation: 109 tests, external child-process identity witness, Ruff, and diff checks. |
| 2026-08-29 | SIDERIUS | `a4e63655` | Issue #391 repaired without adding a capability family: generic inference enters the existing task writer before the first forward pass and yields detached predictions as they are produced. Writers that do not consume the declared sample count fail explicitly. Targeted generic, quickstart, and synthetic regressions: 57 passed; Ruff and diff checks pass. |
| 2026-08-29 | SIDERIUS | `d53ac914` | Issue #392 repaired without a new scope adapter. Composed warmup uses the attempt's already-built task scope and bounds it through `EpochSamplingParams.max_samples`; uncomposed callers retain the legacy scope construction. Targeted validation: 50 passed, 3 skipped; Ruff and diff checks pass. A real external TIDMAD scope and generated model produced a two-batch median warmup of `48.1323 ms`. |
| 2026-08-29 | SIDERIUS | `7476bf44` | Issue #393 repaired without a generic timing abstraction. Generic inference has no framework-owned file or PSD unit, so it emits the existing empty per-file measurement representation instead of an incompatible summary dictionary. Legacy per-file timing remains unchanged and record construction uses its existing absent-measurement fallback. Targeted validation: 104 passed; Ruff and diff checks pass. |
| 2026-08-29 | `siderius-exp` | `7299c3e` qualification | A fresh external TIDMAD chain exercised the task-owned warmup repair through production: measured `47.12 ms` per step, trained 2,500 steps in 163 seconds, streamed 5,000 predictions in 157 batches and 54.93 seconds, wrote and scored four deliverables, and correctly invalidated constant-output collapse through Health. Attempt persistence then exposed #393. The unchanged retry was stopped, so the run remains diagnostic rather than authoritative. |
| 2026-08-29 | `siderius-exp` | `06aaf4e` | Fresh external #393 acceptance completed measured warmup, 2,500 training steps in 124 seconds, 5,000 streamed predictions in 157 batches and 60.70 seconds, scoring, Health, and attempt persistence. The timing sidecar was `[]`, and the record persisted as `failed_mode_collapse`. Formal admission then exposed an experiment-launcher mismatch: the bounded quickstart left evaluation at the production 100% default, so even a 10,593-parameter model priced above 190 minutes. The experiment-only quickstart now pins `--formal_eval_portion 0.02`; shell syntax, source-authority checks, and the production dry-run resolve that value. No framework policy changed. |
| 2026-08-29 | `siderius-exp` | `4f96461` | TIDMAD's task-owned writer now consumes streamed raw predictions, performs the same classification/regression decode and storage offset as the proven legacy path, and persists one file at a time. A package-local regression pins classification decode and injected-target alignment. The RTX 5090 delta witness reused the failed attempt's checkpoint and exact 5,000-sample scope at inference batch 32: 157 batches and four deliverables in 74.99 seconds, followed by finite anchor-normalized score `-10.509863893769241`. The stopped original chain remains non-authoritative. |
| 2026-08-29 | SIDERIUS | `bebe1f0b` | Phase-C coverage audit selected a two-pack minimal set: mature quickstart plus one synthetic masked-regression contrast. The matrix assigns every supported lifecycle and contract-diversity requirement, records quickstart's scored-chain gap, and classifies real-task tests by responsibility before movement. No source asset was removed. |
| 2026-08-29 | SIDERIUS | `92d25e00` | Quickstart's production generic-inference handoff now persists the task-declared artifact, decodes it through the task reader, and returns the composed metric's hand-computed `37/64 = 0.578125`. One task-owned naming authority serves both supported call shapes. Historical live-run records remain unchanged, and no TIDMAD or other real-task asset moved. |
| 2026-08-29 | SIDERIUS | `f6786cef` | Added the synthetic masked-regression pack's core deterministic vertical slice: disjoint generated shards, continuous `[B,1]` output, semantic `[truth, mask]` supervision, source-aligned persistence, lower-is-better masked MSE, and observational masked MAE. Focused and adjacent CPU/offline checks pass; Health and resource admission remain the next checkpoint. |
| 2026-08-29 | SIDERIUS | `0b28d6ae` | Added task-owned Health over valid predictions with fixed constant-FAIL and varied-PASS controls. The isolated resource worker now has example-owned evidence that a full batch preserves `[truth, mask]` supervision and that an oversized batch refuses explicitly. No GPU measurement is claimed. |
| 2026-08-29 | SIDERIUS | `1acfe3bb` | The first H100 preflight exposed `PLUGIN_LOSS_REDUCTION = "mean_over_valid_elements"` as unsupported comparability metadata. The objective still computed correctly, but the loader treated its normalization as undeclared. The declaration now uses the supported `mean` vocabulary, with a focused loader/comparability regression. |
| 2026-08-29 | SIDERIUS | `e1aa5e9b` | Fresh TestPod H100 production-preflight qualification at `1acfe3bb`: one 41-parameter candidate and task-valid `[8,3]` / `[8,2]` batch measured `0.229 GB`; the `1.0 GB` control admitted and the otherwise-identical `0.001 GB` control refused as `MEASURED_PEAK_ABOVE_VRAM_CAP`. Compact receipt and integrity test landed; full transient logs remain outside framework source. |
| 2026-08-29 | SIDERIUS | `4f7e6760` | Closed the next minimal-example evidence checkpoint. The synthetic manifest traverses the production workflow in the exact interpret, propose, implement, validate, tune order using typed deterministic substitutes. A deliberately conflicting candidate pair proves persisted selection follows lower-is-better masked MSE even when observational masked MAE prefers the other candidate. Targeted adjacent regression: 78 passed; focused pack: 9 passed; Ruff and diff checks pass. |
| 2026-08-29 | SIDERIUS | `db5c3ba4` | Added checkout-portable persistence and standalone-node evidence. Two byte-identical synthetic-package copies at unrelated roots derive one fingerprint and validate one workspace lock; editing the declared metric plugin moves the fingerprint, refuses resume, and leaves the lock byte-identical. The interpretation node runs directly through its typed public contract with no workflow state and no LLM call on cold start. The combined run exposed and repaired test-only Health registry leakage without weakening production run-scope refusal. Targeted adjacent regression: 54 passed, 1 skipped; Ruff and diff checks pass. |
| 2026-08-29 | SIDERIUS | `6106a151` | Audited the 38 Python files that directly reference a shipped real-task or Gold asset: 18 move with experiment ownership, 11 retain their generic failure class after fixture replacement, 7 require responsibility-level splitting, and 2 are non-executable lexical matches. The audit names every cohort and explicitly blocks DAVIS objective-authority removal until the synthetic task reaches the production training engine. No source or test was removed. |
| 2026-08-29 | SIDERIUS | `dab6c116` | Closed the two remaining minimal lifecycle evidence gaps. The production trainer completes one bounded CPU optimizer step over the synthetic task's real `[truth, mask]` supervision through its custom objective and persists the model. The production workflow now has both legacy and composed offline literature-review ON/OFF evidence: composed ON requires an explicit non-default config and passes advisor channels to the proposer, while OFF neither reads a missing path nor invokes the advisor. The shipped TIDMAD config remains refused on composed runs. Targeted validation: 28 passed; Ruff and diff checks pass. |
| 2026-08-29 | SIDERIUS | `e463fddc` | Replaced the first machine-specific real-task framework fixture. The training-scope transport regression now generates the minimal synthetic pack's shards under `tmp_path` instead of requiring `/home/klz/...` Pets data, while preserving the decisive no-legacy-`SampleSet` subprocess shape. The first run correctly exposed that validation-row argv construction materializes the evaluation scope in the parent; generating the declared shards repaired the fixture without changing production code. Targeted transport validation: 45 passed; Ruff and diff checks pass. |
| 2026-08-29 | SIDERIUS | `4dd303a4` | Generalized the advice-content workspace-lock test from Gold-labelled fake paths to task-neutral run/advice fixtures and renamed the module accordingly. The production invariant and all five comparability rows are unchanged: identical content resumes across paths, changed/added/removed advice refuses, and path remains provenance rather than canonical identity. Targeted lock validation: 46 passed; Ruff and diff checks pass. |
| 2026-08-29 | `siderius-exp` | `a06da73` | Pinned SIDERIUS `8be2874d`, replaced the Cancer placeholder boundary witness with official HDF5 identity, split-disjointness, and task-data materialization checks, separated the two-network qualification and eight-network formal compositions, and made the quickstart consume an explicit SIDERIUS checkout. Both compositions and the resolved production dry-run pass. |
| 2026-08-29 | SIDERIUS | `b107baec` | Added three narrow task-extension boundaries without a task-specific core branch: task-owned evaluation decoding for Health, validated selection of existing built-in objectives alongside the existing custom-objective plugin route, and documentation of the existing task-owned sampling contract. Quickstart demonstrates built-in categorical cross-entropy while synthetic masked regression demonstrates custom objective and Health behavior. Focused validation: 20 passed; Ruff and diff checks pass. Local pyright remains unavailable because the host Node runtime cannot parse the installed pyright bundle and remains assigned to final PR CI. |
| 2026-08-29 | `siderius-exp` | `bd42822` | Pinned SIDERIUS `b107baec`; Pets now declares categorical cross-entropy and full-epoch sampling, while Pets and DAVIS Health providers decode their task-owned payloads instead of assuming indexed TIDMAD-style filenames. Six external startup and extension-boundary witnesses pass. This is interface evidence only; fresh two-iteration GPU qualification remains pending. |
| 2026-08-29 | `siderius-exp` | `253a944` | Separated TIDMAD's bounded qualification entrypoint from Gold Stage 1 and Gold Stage 2 ownership. Qualification now resolves from `workflows/qualification/composition.yaml` and defaults to two chain iterations with one Trial plus one Formal round per iteration. Gold Stage 1 stores the calibrated D-HEALTH-1 treatment with `amplitude_collapse` as the sole blocking check; diversity and output standard deviation remain record-only. Gold Stage 2 has no executable launcher and remains unauthorized. The exact SIDERIUS `7476bf44` dry-run resolves both iterations and externally fixed Formal scope/evaluation. |
| 2026-08-29 | `siderius-exp` | `23a6cc5` | Pets, DAVIS, and Cancer qualification entrypoints now require an explicit SIDERIUS checkout and resolve only experiment-repository compositions. Each defaults to two chain iterations and two tuner rounds with Trial/Formal batch parity, externally fixed Formal exposure, and task-sized VRAM limits. Exact-SHA dry-runs pass for all three real data roots. Composition loading confirms primary ordering is Pets `accuracy` higher, DAVIS `mse` lower, and Cancer `mean_auprc` higher. No additional GPU workload was launched while the TIDMAD witness was active. |
| 2026-08-29 | `siderius-exp` | `7d776db`, `7846bbf` | Added and recorded a bounded non-LLM Cancer GPU witness. One complete `cpdb` graph trained and validated for one epoch on the `ligroup` RTX 5090 through the external task data path, model plugin, masked objective, CUDA trainer, checkpoint, and result writer; train loss was `0.702394`, validation loss `0.702044`, and the step took `25.62s`. A separate full-chain attempt stopped before proposal because `OPENAI_API_KEY` was absent and correctly produced no authoritative result. Inference, scoring, TestPod reproduction, and scientific performance remain unproven. |

| 2026-08-29 | SIDERIUS / `siderius-exp` | external Pets qualification at `7476bf44` / `23a6cc5` | The fresh TestPod Pets chain refused both planned iterations before any GPU work. `load_task_health_plugins` first recorded an empty process-global plugin set and then refused the task-declared `_pets_health_views.py` set as a cross-run change. This is a framework lifecycle defect exposed by a task-owned Health plugin, not an H100 or experiment-budget failure. The failed workspace is non-authoritative and will be discarded after this evidence is recorded; the repair must preserve refusal after a genuinely non-empty plugin set has registered process-global checks. |
| 2026-08-29 | `siderius-exp` | interrupted TIDMAD qualification at `7476bf44` / `253a944` | The bounded RTX 5090 chain reached iteration 1, tuner round 2, completed 2,500 training steps and streamed four inference deliverables before the operator requested a clean coordinated restart. It was interrupted during scoring. The workspace is non-authoritative and will be discarded; no result or campaign state will be inherited by the replacement run. |
| 2026-08-29 | SIDERIUS / `siderius-exp` | external Pets qualification at `29d91556` / `23a6cc5` | The repaired launch crossed task-owned Health plugin binding, proving the preceding startup fix. Run-invariants then falsely classified Pets' complete `range(370)` qualification scope as partial because `validate_health_scope` consulted the not-yet-bound legacy 20-partition dataset profile instead of the composition's already-resolved `partition_count=370`. Both iterations were refused before LLM or GPU work. The repair threads the resolved partition count through the existing invariant-materialization path; it does not add a Pets override or weaken partial-scope refusal. |
| 2026-08-29 | SIDERIUS / `siderius-exp` | H100 qualification at `b107baec` / `bd42822` | Three fresh external chains passed source authority, composition, runtime self-test, proposal, implementation, and validation. Pets executed Trial and Formal in iteration 1 and correctly invalidated one-class collapse. DAVIS completed a valid Trial with MSE `0.01661713817420464`, then the forced-Formal winner selector re-resolved the default Health family instead of consuming the run-scoped DAVIS roster and raised `HealthPluginRunScopeError`. Cancer repeatedly reached isolated resource preflight, where the autograd tape probe called dense storage access on a saved sparse tensor and raised `NotImplementedError: Cannot access storage of SparseTensorImpl`. All three chains exited; their workspaces are preserved as diagnostic evidence and no 5090 TIDMAD run was started. |
| 2026-08-29 | SIDERIUS | `a5b144c2` | Repaired both H100 findings through existing authorities. `_best_trial_winner` now consumes `RunBindings.run_scientific_gate_ids`; the autograd tape probe counts COO and compressed sparse tensors through their physical index/value buffers. Composed task-data-path binding is limited to composed runs, preserving the legacy un-composed path. Targeted and adjacent validation: 113 passed; Ruff and diff checks pass. H100 delta evidence: the real persisted DAVIS Trial is selected under `davis_dispersion_blocking` at MSE `0.016617138174`, and a CUDA sparse COO graph reports three storages and 84 bytes without error. |
| 2026-08-29 | `siderius-exp` | `aa73036` | Pinned the exact repaired SIDERIUS revision `a5b144c2`. No task treatment, workflow budget, dataset scope, or preserved diagnostic artifact changed. |
| 2026-08-29 | SIDERIUS | `b67756ab` | Landed the behavior-authority repair described by the following qualification row. |
| 2026-08-29 | `siderius-exp` | `0472a3e` | Pinned SIDERIUS `b67756ab` and made qualification output representation explicit: Pets permits only `classifier`; DAVIS and Cancer permit only `regressor`. Shell syntax and diff checks pass. |
| 2026-08-29 | SIDERIUS / `siderius-exp` | H100 qualification at `a5b144c2` / `aa73036` | The synchronized restart exposed a second run-scope Health leak in `finalize_run_output`: trial-validity feedback re-resolved the process-default gate family instead of consuming `RunBindings.run_scientific_gate_ids`. DAVIS iteration 1 therefore failed after a valid Trial MSE of `0.016732`. Pets also proved that a persisted `failed_mode_collapse` record was misreported to the next proposer as an execution failure. Cancer reached iteration 2 before the synchronized batch was stopped. All artifacts remain diagnostic and no 5090 TIDMAD run was started. |
| 2026-08-29 | SIDERIUS | pending behavior-authority repair | Trial-validity feedback now consumes the already-resolved run-scoped gate set and classifies `failed_mode_collapse` as scientific invalidity rather than execution failure. Chain resume preserves resource and Health feedback in chronological order so the next subprocess's proposer receives both. The generic chain and iteration parsers no longer inject `min_formal_batch_size=4`; the existing guard remains available as an explicit opt-in. Focused behavior validation passes: 333 tests; an additional 126 Formal-policy tests passed before an unrelated migrated TIDMAD fingerprint fixture assertion. Ruff, shell syntax, and diff checks pass. |
| 2026-08-29 | SIDERIUS / `siderius-exp` | parameter-rule interface in progress | Added one typed, composition-owned dotted-path rule surface with `exact`, inclusive `range`, `allowed`, and registered deterministic `predicate` forms. Omission remains agent-controlled; rules execute after Formal inheritance, participate in the composition fingerprint, and appear in execution provenance. Task-declared objectives retain sole ownership of `loss_config`. Cancer qualification and formal compositions now lock `train_config.batch_size=1` through this interface. Focused schema, composition, and workflow regression checks pass; H100 relaunch remains intentionally blocked until the exact infra/experiment revisions are committed and synchronized. |
| 2026-08-29 | SIDERIUS / `siderius-exp` | `4968d061` / `8e0bf16` | Parameter rules are committed and synchronized to the dedicated TestPod checkouts. Local focused validation passes 177 tests; TestPod passes 64 focused tests and resolves the external Cancer composition with the exact batch lock in its semantic fingerprint. The first v4 launch batch failed before LLM work because the dedicated checkout intentionally carried no `.env`; those workspaces remain startup diagnostics and are not resumed. Fresh v5 Pets, DAVIS, and Cancer chains source the existing TestPod environment without copying or printing secrets and are running in independent tmux sessions and new workspaces. No 5090 TIDMAD run has started. |
| 2026-08-30 | SIDERIUS / `siderius-exp` | H100 qualification at `4968d061` / `8e0bf16` | The v5 batch exited without operator intervention. Pets completed two iterations; both candidates were scientifically invalidated by task-owned Health, so the infrastructure path passed but no incumbent was established. Cancer completed two iterations and recorded best mean AUPRC `0.385523263398698`. DAVIS completed iteration 1 with Trial MSE `0.013112756706556063`, then exposed two framework defects: planner score-table selection omitted the run-scoped scientific gate IDs, and the tuner re-materialized the chain's already-effective Health YAML, dropping resolved-plugin provenance and changing `health_config_sha256`. |
| 2026-08-30 | SIDERIUS | `72be1d1c` | Planner history classification now consumes `RunBindings.run_scientific_gate_ids`. Chain and tuner Health materialization now start from the same original operator source plus the same task binding rather than treating an effective artifact as a new source. Focused Health, composition, planning, and restore validation passes: 31 passed, 1 skipped; Ruff and diff checks pass. Fresh external DAVIS acceptance remains required. |
| 2026-08-30 | `siderius-exp` | `83f9957` | Cancer proposer and implementor prompt blocks now state that the workflow owns a fixed masked binary-cross-entropy objective and that no custom loss should be generated. This is a non-authoritative efficiency correction; deterministic objective ownership remains the scientific lock. All four external cold-start witnesses pass. The broader unified advice / generation-constraint / execution-lock declaration design is tracked in SIDERIUS issue #394. |
| 2026-08-30 | SIDERIUS / `siderius-exp` | H100 DAVIS acceptance at `0e092302` / `83f9957` | A fresh two-iteration chain completed without Health identity refusal. Iteration 1 recorded Trial MSE `0.023089394119636064` and Formal MSE `0.029764309801557073`; iteration 2 restored the iteration-1 incumbent under the identical Health SHA-256, recorded Trial MSE `0.016087474146372772`, and recorded Formal MSE `0.016089017514105866`. Both manifests are `completed` with one successful Formal record. The Formal lower-is-better curve improved from `0.029764309801557073` to `0.016089017514105866`. Issue #395 carries this external evidence and is closed. The deterministic DAVIS exact-L1 objective correctly overrode an agent-generated `dense_rgb_mse` loss, while the unnecessary generated loss confirms the declaration-layer design gap tracked by #394. |
| 2026-08-30 | SIDERIUS | issue #396 | The fresh two-iteration RTX 5090 TIDMAD qualification exposed a generic negative-feedback transport defect. Iteration 1 persisted four attempts and explicit Health/gate-exhaustion feedback, but because every executed candidate was scientifically invalid its manifest became `no_records` with `output_path=null`. Resume skipped output absorption, and iteration 2 reported a cold start instead of receiving the bounded failure evidence. The issue freezes the smallest repair boundary: preserve negative feedback without promoting an invalid model, manufacturing a score, weakening Health, or changing the manifest status vocabulary. |
| 2026-08-30 | SIDERIUS / `siderius-exp` | RTX 5090 TIDMAD qualification at `0e092302` / `83f9957` | A fresh two-iteration chain completed from the separated qualification composition in 2 hours 44 minutes. Iteration 1 completed two tuner rounds and persisted four attempts, but every executed candidate failed the task-owned blocking Health checks for near-constant output; its manifest correctly reports `no_records` and no scientific incumbent. Iteration 2 proposed the 2,174,384-parameter `hybrid_spectral_tcn_compact`. Its Trial used batch 1, 20,000 optimizer steps, 80,000 validation samples, and 0.353 GiB allocator peak, then was scientifically invalidated for constant output. Its Formal used batch 16, 5,000 optimizer steps, 80,000 validation samples, 0.02 evaluation scope, and 4.846 GiB allocator / 5.312 GiB reserved peak under the 16 GiB envelope. Formal training took 810.13 seconds, validation 344.27 seconds, inference 563.3 seconds, and scoring 21.1 seconds. It passed every blocking Health check and produced the first valid qualification score, `-0.5314745777130531`. The negative value is a valid measured reference, not evidence of useful denoising or comparison with the production regression campaign. The run also proved that `min_formal_batch_size=1` did not block a valid Formal execution. |
| 2026-08-30 | SIDERIUS | `e31da5c7` | A `no_records` manifest now carries only the already-validated, bounded `gate_exhaustion` and `trial_validity_feedback` objects when they exist. Resume verifies the write-once manifest, revalidates those objects at the subprocess boundary, and restores them only into the negative-feedback carrier. It still does not parse a run output, restore a plugin, add a source path, establish an incumbent, or change the manifest status. Focused local validation passes 163 tests; the two producer/consumer regressions and targeted Ruff checks pass locally, and the same regressions pass on H100. |
| 2026-08-30 | SIDERIUS / `siderius-exp` | H100 Pets acceptance at `e31da5c7` / `83f9957` | A fresh external two-iteration chain completed in a new workspace. Both candidates were scientifically invalidated by task-owned categorical Health checks, so both manifests correctly remain `no_records` with `output_path=null` and no source paths. Iteration 1 persisted typed `trial_validity_feedback`; iteration-2 resume reported `restored negative feedback` and pre-seeded one cross-iteration negative-feedback summary for the proposer while restoring no model or plugin. This is the external acceptance for #396. It proves feedback continuity, not a valid Pets score. |
| 2026-08-30 | SIDERIUS | neutral-start census fixture replacement | Replaced the shipped TIDMAD negative control and Pets omitted-naming witness in `test_arxiv_286_neutral_start_census.py` with temporary generic quickstart/declared-naming variants. The exact anchor-residue and omitted-declaration failure classes remain unchanged. Combined validation also exposed and repaired a test-scaffolding leak: every composition now uses the existing `run_registration_scope`, so this module cannot leave a task-data-path registration behind for later tests. The focused module passes 4 tests; related suites pass 38 tests together; quickstart and census pass in both file orders, 19 tests each; Ruff and diff checks pass. No production code or task behavior changed. |
| 2026-08-30 | SIDERIUS | model-plugin composition fixture replacement | Replaced the TIDMAD manifest copy and frozen TIDMAD fingerprint in `test_step12_pr12d_dp_plugin_binding.py` with a quickstart-derived generic composition and the declared-naming task-data-path fixture. The test still drives `compose_run_task_bindings`, proves omitted/explicit-none equivalence, requires declared plugin resolution, proves plugin content changes semantic identity, and preserves all malformed-section refusals. The focused module passes 45 tests; the related quickstart, declared-naming, and plugin-binding suites pass 79 tests in both file orders; Ruff and diff checks pass. No production code, scientific declaration, or task behavior changed. |
| 2026-08-30 | SIDERIUS | provenance fixture replacement | Replaced hardcoded TIDMAD/Pets/DAVIS resource names in `test_provenance.py` with injected generic config and resource declarations. The test now proves exact present and absent states for both provenance axes while remaining independent of current deployment inventory. The focused module passes 6 tests; provenance and preflight pass 29 tests in both file orders; Ruff and diff checks pass. Production preflight declarations and behavior are unchanged. Review also classified the secondary-metric declaration module as mixed generic/scientific responsibility, so it remains pending until its parity assertions move rather than being flattened into a generic fixture. |
| 2026-08-30 | SIDERIUS | preflight fixture replacement | Replaced the TIDMAD machine-config and tracked-template examples in `test_preflight.py` with generic local-runtime names. The resource-declaration test now protects the non-empty roster and positive measured skip counts without pinning task names or the current aggregate. The focused module passes 23 tests; preflight and provenance pass 29 tests in both file orders; Ruff and diff checks pass. No production code, function, module, or runtime default changed. The separation design now also records the operator's modularity boundary: migration must not grow monolithic functions/files or add umbrella managers in place of task coupling. |
| 2026-08-30 | `siderius-exp` | `58acaeb` | Added a 116-line external secondary-metric parity module. Against an explicit SIDERIUS checkout, each real task composes in its own cold subprocess: TIDMAD declares no secondaries; Pets declares `macro_f1` higher then `log_loss` lower; DAVIS declares `psnr` higher then `mae` lower. Primary identities, declaration provenance, order, and source-checkout authority are also verified. The parity module and four-task startup witnesses pass 7 tests; Ruff and diff checks pass. This intentionally lands the experiment-owned half before shrinking the 423-line mixed infra module, so one change does not simultaneously move parity, redesign generic fixtures, and delete historical locks. |
| 2026-08-30 | SIDERIUS | secondary-metric parity ownership split | Removed the five experiment-owned roster, direction, order, and provenance assertions from the mixed infrastructure module after the external witness landed. The generic fail-closed, additive fingerprint, run-scoped binding, unwind, and single-owner tests remain. The redundant TIDMAD no-secondary fingerprint row was retired rather than re-recording a real-task implementation hash in infrastructure; the synthetic zero-secondary case preserves that failure class. A broader focused run exposed separate pending migration debt: stale real-task fingerprint locks, a stale shipped-manifest census, parameter-rule branching added directly to `prepare_attempt`, and one temporary legacy TIDMAD bootstrap increasing a module-level structural baseline. None was hidden by widening a baseline in this slice. |
| 2026-08-30 | SIDERIUS | parameter-rule planning decomposition | Extracted the interaction between composition-owned parameter rules, the declared objective, and the independent epoch ceiling from `prepare_attempt` into one typed planning helper. The orchestrator still sequences the same authorities in the same order and records the same `parameter_rules` resolution step. Generic reachability tests now prove an exact lock reaches planning and that neither objective ownership nor the epoch safety ceiling can be bypassed. The focused parameter-rule, planning, and structural checks pass 46 tests; Ruff and diff checks pass. Local pyright remains unavailable because the installed Node runtime cannot parse the bundled pyright JavaScript, so exact-head static evidence remains assigned to PR CI. |
| 2026-08-30 | SIDERIUS | observable fingerprint fixture correction | Corrected the audit classification of `test_robs1_c1_observable_declaration.py`: its real-task names were executable composition and fingerprint dependencies, not lexical examples. Removed the shipped real-task roster and three real-task fingerprint locks. The framework-owned Quickstart example now carries the undeclared-observable baseline, while synthetic observable plugins continue to prove type discrimination, manifest order, additive identity, content-digest identity, name uniqueness, and child resolution. The focused module passes 25 tests; both execution orders with the adjacent secondary-metric module pass 47 tests; external real-task parity passes 7 tests; Ruff and diff checks pass. No production code or task declaration changed. |
| 2026-08-30 | SIDERIUS | secondary-metric fixture replacement | Replaced the remaining TIDMAD, Pets, and DAVIS composition fixtures in the generic secondary-metric module with one synthetic external-task package. Test-only declarations cover zero, one, and two secondaries with opposing directions; the original duplicate, primary-collision, malformed-entry, inherited-refusal, import-refusal, additive-identity, ordering, relocation, nested-binding, unwind, and active-binding failure classes remain. The first run exposed an absolute configured-reference error in the new fixture; package-relative declarations repaired portability without production changes. The focused module passes 21 tests, both execution orders with observable declaration pass 46 tests, external scientific parity passes 7 tests, and the changed files contain no real-task identifier. Ruff and diff checks pass. |
| 2026-08-30 | SIDERIUS | composition-cache ownership classification | The cache-authority module is not an ordinary real-fixture replacement. Its generic half protects binding-aware memoization, recomposition after reset, run-scope discrimination, and tuner-first resolution; its other half freezes the built-in legacy TIDMAD default and exact Pets/DAVIS families. The generic half remains assigned to synthetic Health families. The legacy-default half must retire with the bounded legacy task bootstrap after external parity is recorded; it must not be copied into `siderius-exp` as a permanent framework contract or preserved through a new compatibility abstraction. No source or test changed in this classification step. |
| 2026-08-30 | SIDERIUS | workspace-owned implementor defaults | Replaced the standalone implementor's checkout-relative `agent_generated/models`, `tests`, and `losses` defaults with one workspace-derived `generated/{run_name}` tree. Explicit directories remain authoritative, so the reference workflow's existing per-attempt isolation is byte-for-byte unchanged. Two-workspace and non-local-backend regressions prevent ambient fallback. Focused schema, protocol, and implementor validation passes 35 tests with 4 environment-dependent skips; Ruff and diff checks pass. The capability index and promotion library still resolve through ambient per-user state and are the next migration slice. |
| 2026-08-30 | SIDERIUS | workspace-owned capability library | Supported workflow, chain, proposer, implementor, and tuner entry points now bind the existing generated-library transport to `{workspace}/generated_library` before any registry construction. Capability index writes, model/loss promotion, preload, source and description lookup, and proposer inventory share that root. Workspace-bound execution excludes the per-user library and checkout fallbacks; unbound low-level callers retain the legacy read path during migration. The workflow-level witness proves an unrelated operator library remains untouched, all four generated artifact families land below the workspace, run provenance records that root, and the checkout tree remains byte-identical. Adversarial review found the first chain binding was later than preflight invariant construction; moving it immediately after argument normalization makes preflight, resume, and workflow resolve one identity. Related infrastructure validation passes 286 tests plus 35 workflow/guardrail tests and 148 chain-runner tests; order-reversal isolation passes 107 tests in each order; four external task startups and real-task secondary parity pass 7 tests. |
| 2026-08-30 | SIDERIUS | PR #397 local CI repair | Automatic PR CI was unable to start because GitHub reported an account billing/spending-limit failure, so the repository's exact local bulk harness became the executable fallback. Its first clean-head run found four shared failure classes: workspace environment leakage between tests, Health witnesses still constructing filename-only contexts after payload decoding became task-owned, historical real-task fingerprint locks conflicting with the separation boundary, and structural growth in orchestration/resume functions. The repair restores both generated-library environment variables after every test, passes task-decoded evaluation payloads through the Health context, retires redundant scientific fingerprint assertions while preserving generic additivity and semantic checks, extracts no-records feedback restoration/seeding into focused helpers, groups Health materialization inputs into one typed carrier, and keeps the Formal-only batch floor disabled consistently in shell and Python defaults. Focused reruns cover the complete original failure roster; Ruff, formatting, structural budgets, selector reachability, and documentation line guards pass. Final clean-head bulk and sensitive-lane results remain the merge boundary. |
| 2026-08-30 | SIDERIUS | PR #397 final-bulk delta | The first post-repair clean-head bulk run completed all four shards and narrowed the result to four stale contract tests: one expected `run_workflow` to inline both negative-feedback fields after their typed extraction, while three still required every child import to register all in-tree real task implementations. The first test now proves the helper reads both fields and that the workflow calls the helper. The child contract now proves transported-manifest resolution plus the explicit uncomposed legacy adapter, and importable children are reloaded to prove they do not mutate the task registry. The focused delta passes 86 tests with one environment-independent skip; no production source changed in this delta. One final clean-head bulk rerun is still required before merge. |
| 2026-08-30 | SIDERIUS | PR #397 merged at `fb86f3dc` | The exact final PR head `264f0196` passed the authorized local fallback after automatic GitHub checks again failed before executing because of the repository billing limit. Ruff check and format, diff integrity, and pyright passed with zero errors and 26 configured warnings. The four bulk shards completed with 14,776 passed and 21 skipped; all six sensitive lanes passed. PR #397 then merged without replaying unrelated workload qualification. |
| 2026-08-30 | SIDERIUS | `ec575894` | Replaced the task-instance configuration module's shipped scientific fixtures with one temporary external task-data-path plugin composed over framework-owned Quickstart declarations. The same nineteen failure classes still prove fail-closed section and constructor validation, manifest-relative task references, real training/evaluation scope construction, configured-over-registered precedence, authored-reference identity, relocation stability, and registry isolation. The focused module passes 19 tests; both orders with Quickstart and registration lifecycle pass 53 tests; Ruff, formatting, diff integrity, and a zero-real-task-identifier scan pass. Production code and runtime behavior are unchanged. Review confirms #388 is an independent setup-only watchdog defect and remains outside this fixture-only checkpoint. |
| 2026-08-30 | `siderius-exp` | PR #1 / `b3bb1c2` | Extended the cold-process startup witness so all four external task packages own their exact objective type/name and blocking Health gate identities. The witness also moved to the current typed `RunHealthMaterialization` boundary. All 10 external tests pass against SIDERIUS `b6990340`; Ruff, changed-file formatting, and diff integrity pass. |
| 2026-08-30 | SIDERIUS | `b6990340` | Repaired #388 without disabling the watchdog or adding an estimator. A measured component sum may tighten an explicit operator budget only when the current subprocess has measurement-backed evidence; training also waits for declared non-zero validation, and inference waits for its own prediction. The exact external failure numbers now retain 1,200 seconds under setup-only or training-only evidence instead of collapsing to the 120-second floor. Focused watchdog, authority, safety-split, and executor validation passes 98 tests. |
| 2026-08-30 | SIDERIUS | `df8fdb9e` | Completed the final two generic-fixture replacements after experiment-owned parity landed. Health cache authority now uses two temporary synthetic plugin families; objective authority now uses Quickstart, synthetic masked regression, and temporary plugins. Cold/warm cache parity, memo invalidation, run-scope discrimination, tuner-first resolution, objective precedence, typed refusal, content identity, relocation, shadow refusal, and fresh-process composition remain covered. The two focused modules pass 26 tests; the adjacent Health, composition, objective-loader, watchdog, and authority set passes 174 tests. The changed infra tests contain no real-task identifier. |
| 2026-08-30 | `siderius-exp` | `6a8d740a` (PR #9) | Moved TIDMAD Gold Stage-1/Stage-2 workflow ownership into the campaign package; required an explicit SIDERIUS checkout; bound campaign-owned task and calibrated Health assets onto the existing chain; added task-config drift refusal, an external Stage-1 dry-run, and Stage-2 refusal evidence. The local external suite passes 37 tests. No workload was launched. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #10 / Gold advice test retirement | Replaced the 304-line in-framework Gold advice-identity module with a 235-line campaign-owned module. Six behavior-level tests preserve the distinct failure classes: campaign-versus-band byte drift, direct and control-arm identity, reserved-argument refusal, real band-boundary refusal, four-band inheritance, and launch-manifest identity. The external campaign and ownership modules pass 12 tests; the historical module passed all 15 tests immediately before removal. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #11 / Gold band-selection test retirement | Moved the pure Gold `--only` responsibility from the monolithic campaign-entrypoint module into a 137-line campaign-owned module. The replacement preserves all valid subsets, canonical ordering, the empty all-band default, named duplicate/unknown/empty refusals, and real entrypoint reachability; the three adjacent external Gold modules pass 28 tests. Review also found that `campaign_preflight.sh` still combines Gold and X9 while its external Gold copy lacks three X9-owned siblings. That mixed preflight remains intact and is assigned to a later responsibility split rather than copying X9 assets into the Gold package. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #12 / Gold GPU-map test retirement | Added campaign-owned evidence that the real four-band Stage-1 dry-run resolves bands `0-3`, `4-9`, `10-14`, and `15-19` to physical GPUs `0`, `1`, `2`, and `3`, and that an unknown band has no assignment. The adjacent external Gold modules pass 30 tests. SIDERIUS retires only the duplicated Gold GPU assertion; the remaining X9 monitored-file parity assertion is renamed to expose its still-pending experiment ownership. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #13 / Gold retention responsibility split | Added an 84-line campaign-owned module proving that every real Stage-1 band dry-run types `--no-cleanup_denoised` and that a caller cannot override the frozen policy with `--cleanup_denoised`; the four adjacent external Gold modules pass 32 tests. SIDERIUS removes only those two campaign assertions and retains the three generic compatibility checks for exploratory cleanup, typed cleanup suppression, and SDSc refusal under the explicit `TestGenericRetentionCompatibility` name. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #14 / Gold boundary-refusal test retirement | Added a 106-line campaign-owned module exercising the real external entrypoint against four refusal classes: X9 arm labels entering Gold identity, missing treated-arm advice, advice supplied to the control arm, and caller override of a frozen training-scope flag. The five adjacent external Gold modules pass 37 tests. SIDERIUS retires the complete campaign-only refusal class after that evidence lands. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #15 / Gold Stage-1 LLM binding test retirement | Moved the frozen Gold role-to-model routing values into `campaigns/tidmad_gold/config/llm_routing.json`, while retaining SIDERIUS as the generic `WorkflowLLMConfig` parser authority. The real external Stage-1 dry-run proves all four bands bind the campaign-owned absolute path, and a campaign-owned identity test pins every role, provider, and model value; the five adjacent external Gold modules pass 38 tests. SIDERIUS retires only the duplicated Stage-1 binding assertion. Stage-2 binding, parser reachability, missing-config refusal, override refusal, and non-campaign optional-config behavior remain in SIDERIUS until their responsibilities are separately reconciled. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #16 / Gold LLM refusal test retirement | Added campaign-owned real-entrypoint witnesses for the remaining LLM refusal classes: a caller-supplied `--llm_config` cannot replace frozen routing, and a copied campaign package without its routing file refuses before dispatch while naming the silent all-Gemini consequence. The five adjacent external Gold modules pass 40 tests. SIDERIUS retires only those two duplicated campaign assertions; Stage-2 binding, real parser transport, the historical relative-path authority, and generic non-campaign optional-config behavior remain pending separate responsibility decisions. No production code or workload changed. |
| 2026-08-30 | SIDERIUS | Gold LLM path-authority test retirement | Retired the remaining assertion that treated SIDERIUS `llm_configs/openai_tiered_pro.json` as the Gold campaign's permanent relative-path authority. `siderius-exp` PR #15 already proves that all four external Stage-1 bands bind `campaigns/tidmad_gold/config/llm_routing.json` and pins the complete role/provider/model mapping. The old SIDERIUS path remains only as a historical fixture for still-retained Stage-2 and parser-transport tests, not as the forward campaign contract. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #17 / Gold Stage-1 runtime-profile test retirement | Added a focused campaign-owned module that exercises the real external Stage-1 entrypoint across complete and absent declarations, seven incomplete or malformed declaration shapes, and all three reserved child-level override spellings. It proves all four band argv and the operator-visible dry-run row agree; the six adjacent external Gold modules pass 52 tests. SIDERIUS retires only the five matching Stage-1 campaign assertions. The separate Stage-2 binding witness remains until Stage 2 ownership is reconciled, and generic profile parsing/consumption remains framework-owned. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #18 / Gold Stage-1 VRAM policy and provenance repair | Reconciled an imported contradiction after the operator confirmed the frozen Gold default is Trial=40 / Formal=40. The external campaign now records one resolved pair and source, so dry-run output, all four Stage-1 child argv, and live launch manifests agree for both `campaign_default` and `operator_supplied`; paired override, malformed-input, last-wins refusal, and single-numeric-authority witnesses pass. The seven adjacent external Gold modules pass 65 tests. SIDERIUS retires only the contradicted Stage-1 campaign policy, manifest, and no-default assertions; the independent Stage-2 builder, real chain-to-typed-config transport, and generic non-campaign empty default remain. No workload was launched, and the executable 40/40 values did not change. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #19 / Gold Stage-1 frozen-treatment test retirement | Added an external witness over the real campaign launcher that pins the current twenty-value Stage-1 treatment across all four bands, including the 180-minute Formal ceiling, `min_formal_batch_size=1`, the resolved 240-minute bypass ceiling, blind-arm identity, and literature review ON. The eight adjacent external Gold modules pass 67 tests. SIDERIUS retires only the duplicated Stage-1 concrete-value, band-identity, and exact-table assertions; the table-mutation witness, generic bypass transport checks, Stage-2 bindings, and generic workflow-budget source checks remain. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PRs #20--#21 / Gold shell-integrity test retirement | Added campaign-owned parsing and source-inertness checks for all external Gold shell entrypoints, preserved the 2026-07-31 source-time launcher incident identity, added direct-execution refusal for the shared library, an isolated-copy mutation witness that deletes one required frozen row and drives the real external dry-run to a named refusal, and campaign-local coverage for the 180/240 budget defaults plus explicit overrides. The nine adjacent external Gold modules pass 87 tests. SIDERIUS retires only the matching historical source-safety, frozen-row mutation, and campaign budget seam tests; generic bypass transport, Stage-2, X9 parity, and workflow-budget source checks remain. No production code or workload changed. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PR #22 / Gold Stage-2 builder ownership | Added a read-only direct Stage-2 dry-run witness without changing the entrypoint authorization refusal. It pins the 4-design by 4-band unit product, fixed-candidate one-iteration retrain, full Formal evaluation, routing, runtime-profile identity, retention, resume skip, registry refusal, and incumbent-gate switch. The operator confirmed that Stage 2 deliberately omits Stage-1 search VRAM ceilings because model, loss, and training design are selected in Stage 1. No Stage-2 workload was launched. |
| 2026-08-30 | `siderius-exp` | PR #23 / external Gold state-helper checkout repair | Fixed a transferred-path defect: `gold_campaign_state.py` derived the framework root from its old in-repository location, which points at the campaign directory after separation and breaks real resume/finalization outside dry-run. It now requires and validates `SIDERIUS_CHECKOUT`; focused witnesses prove empty-band state through the selected checkout and refuse implicit checkout resolution. Winner, Health, stop, and finalization algorithms are unchanged. |
| 2026-08-30 | `siderius-exp` / SIDERIUS | `siderius-exp` PRs #24--#25 / remaining Gold test ownership | Moved persisted Formal-role interpretation (#316 B2), metric direction, missing-stamp refusal, FCNet stop, horizon, force-fresh, workspace-pinned Health (F-4), band-scoped atomic Stage-2 finalization (Q-S3-2), X9 band-file parity, incumbent-gate binding, and all fixed workflow-budget refusals to campaign-owned external witnesses. The complete external campaign suite passes 110 tests. SIDERIUS retires the superseded pure-campaign classes and keeps only generic consumer and compatibility evidence until the duplicate launch assets themselves are removed. No workload was launched. |

| 2026-08-30 | SIDERIUS / `siderius-exp` | Stage-3, Gold asset, explicit-task, and reference boundary | Moved Gold Stage-3 writers, campaign launchers, campaign documents, decision report, and their witnesses to external ownership. SIDERIUS supported entrypoints now require explicit task composition and data roots. The remaining implicit low-level tuner behavior is retired: an undeclared reference source now produces a named absence instead of selecting TIDMAD data, while synthetic injection continues to exercise generic score-table construction. The external task-owned loader reproduces all 20 raw values, all 20 ceiling values, and the exact frozen ruler and aggregate scalars before SIDERIUS deletes 52 task-owned reference/result files and obsolete default-path tests. External reference plus complete Gold campaign validation passes 260 tests; framework boundary validation passes 283 tests with 3 environment-independent skips; collection discovers 13,941 tests without error. Adversarial review retained `segment_anchors.json` because the legacy scoring CLI still selects it implicitly; that CLI and artifact must migrate together in a later bounded slice rather than leaving a broken default. |
| 2026-08-31 | `siderius-exp` / SIDERIUS | `883fe41`, `fa84f93` / `b8d1ffb2` | Moved the X9 two-arm launcher, four-band fleet launcher, H100 posture, preflight, arm-symmetry tools, co-residency probe, and all seven campaign-only test modules into `campaigns/tidmad_x9`. Every launcher now requires `SIDERIUS_CHECKOUT`; both arms pass real no-workload dry-runs against the selected framework and the complete external X9 suite passes 166 tests. The H100 posture table is now experiment-owned and its drift test no longer reads framework documentation. Adversarial review caught and reversed an over-broad move of `_import_resolution_probe.py`: that probe is required by the generic `run_chain.sh`, so X9 copies it from the explicit framework checkout instead of owning a duplicate. SIDERIUS retires only the transferred X9 assets and two now-external assertions; generic chain entry and spawn-hygiene coverage remains. Historical X9 prose and deeper legacy TIDMAD runtime/scoring compatibility remain separately classified work. |
| 2026-08-31 | SIDERIUS | post-X9 distribution audit | A local wheel built successfully with `uv build --wheel --no-build-isolation` using a temporary cache. It contains no campaign launcher, pod, deployment, `scripts/`, or checkout-level generated-library asset. The audit found one explicit real-task module still packaged: `execute_tools/tidmad_data_path.py`; content review also confirms that legacy TIDMAD scoring, profile, naming, and data-root compatibility remains inside generically named modules. These are an unresolved M4 boundary, not hidden by a filename-only allowlist. Historical X9 operator prose is now labelled archived and active entrypoint tables route task campaigns to their experiment repository. The next removal unit must first replace the remaining generic-production imports and external Gold metric/topology imports; deleting the module alone would break supported execution and is forbidden. |
| 2026-08-31 | SIDERIUS | explicit task-data-path resolution slice | The operator confirmed that uncomposed execution must not select TIDMAD. `resolve_task_data_path(None)` and unbound `resolve_bound_task_data_path()` now refuse by naming the missing task composition instead of consulting a compatibility registration. The temporary explicitly called TIDMAD bootstrap remains only for the old child entrypoints while those entrypoints are migrated; generic resolution never reaches it. Obsolete tests asserting silent uncomposed child argv were retired because task configuration already refuses before child launch. Explicit binding, transported identity, scope reset, unknown-id refusal, and negative controls pass 83 tests with one environment-independent skip; Ruff passes. This is the first bounded compatibility-retirement slice, not completion of the TIDMAD runtime migration. |
| 2026-08-31 | `siderius-exp` / SIDERIUS | `67c9c40` / pending | Moved the two HDF5-shaped runtime-verification witnesses for streaming training and inference from framework tests into `tests/tasks/tidmad`. Their synthetic file factory is now task-owned, the training witness binds the external `TidmadTaskDataPath` and passes an external `TidmadScope`, and both modules pass 10 tests against the pinned framework. A broader adjacent-test run exposed a separate pending cohort: several nominally generic runtime-verification and observable tests still use the TIDMAD-shaped two-family fixture and therefore depended on the retired implicit resolver. They must move or receive a genuinely synthetic binding before final qualification; this slice does not misreport them as surviving generic evidence. A deletion-first attempt correctly failed because the moved direct training witness had relied on the former implicit resolver. The test was repaired through explicit external binding before any production bootstrap was removed. |
| 2026-08-31 | SIDERIUS / `siderius-exp` | explicit child task ownership slice | The training, inference, and scoring child entrypoints now refuse an absent task-data-path identity instead of explicitly bootstrapping TIDMAD. The external task composition, startup, dry-run, and moved TIDMAD runtime suite passes 37 tests across all four task packages against the modified checkout; Ruff and diff integrity pass. No training, inference, scoring, metric, or Health algorithm changed. The remaining top-level TIDMAD compatibility imports and task-shaped framework tests are a visible later cohort; this slice removes only executable default selection. |
| 2026-08-31 | SIDERIUS / `siderius-exp` | explicit task-scope execution slice | The streaming trainer no longer constructs `TidmadScope` from legacy sample-set arguments and no longer imports the TIDMAD dataset implementation. Training and validation now require opaque task-owned scopes from the active composition; sequential ordering reads an explicitly selected dataset capability without naming a task class. The exact external 37-test task/startup/runtime matrix and the 28-test framework task-boundary/synthetic matrix pass; Ruff and diff integrity pass. Adversarial review confirms that old framework tests using the TIDMAD-shaped two-family fixture now refuse at the intended boundary, so they remain a test-ownership migration cohort rather than evidence for restoring the compatibility path. |
| 2026-08-31 | SIDERIUS / `siderius-exp` | declared HDF5 reuse extraction | Inference no longer imports the TIDMAD data-path module to validate resumable output files. The existing shape, dtype, channel, and boundary-read checks moved into a 34-line generic HDF5 deliverable helper that consumes the already-resolved storage declaration. The historical import name remains a thin compatibility wrapper while its task-shaped tests are classified. Focused framework inference/encoding validation passes 29 tests, external inference/startup/task validation passes 25 tests across all four packages, and Ruff plus diff integrity pass. The extraction changes ownership only; reuse decisions remain byte-for-byte equivalent for the same declared storage. |
| 2026-08-31 | SIDERIUS | task-owned warmup scope slice | Device warmup no longer imports `TidmadScope`, reconstructs a sample-set slice, or refuses every task without TIDMAD topology. It requires the attempt's opaque task-owned scope and bounds materialization through the existing generic `EpochSamplingParams.max_samples` field. A new foreign-profile reachability witness fails if a task-name/topology applicability gate returns; the focused estimator and warmup suite passes 75 tests with three environment-dependent skips. Two obsolete tests that asserted the retired TIDMAD-only applicability distinction were removed rather than weakened. Ruff and diff integrity pass. This is mechanism genericization, not a change to any task's scope bytes or training exposure. |
| 2026-08-31 | SIDERIUS / `siderius-exp` | TIDMAD runtime module retirement validated | Production imports of `execute_tools.tidmad_data_path` reached zero, so the 538-line duplicate framework module, its dead compatibility bootstrap, and six task-shaped framework witness modules were removed. The external TIDMAD runtime now owns its identifier without import-time registry mutation, and four non-redundant transferred witness modules plus a self-contained synthetic helper preserve scope transport, composed Formal validation, sample-set behavior, and the task capability contract. Two copied modules were retired after adversarial review showed that they asserted obsolete uncomposed compatibility or generic source shape already covered by surviving framework controls. The exact-checkout external matrix passes 124 tests; focused framework boundaries pass 63 tests with one environment-independent skip; framework collection remains clean at 13,611 tests. Adversarial review also caught a false-green risk: an editable install can import an older worktree unless external validation sets both `PYTHONPATH` and `SIDERIUS_CHECKOUT` to the selected checkout. All acceptance evidence for this slice was rerun with both authorities explicit. No execution, scoring, or Health algorithm changed. |
| 2026-08-31 | SIDERIUS | post-runtime guardrail ownership cleanup | Removing the framework-owned TIDMAD runtime exposed three guard modules that still treated its former construction sites, compatibility bootstrap, and transferred child-loading tests as permanent framework authorities. The task-specific construction and fallback assertions were retired; the surviving guards now enforce the generic properties that still belong here: explicit binding reachability, no real-task implementation imports, no task-name dispatch, opaque scope transport, duplicate-id refusal, and distribution ownership. Adversarial review preserved the active generic checks rather than deleting the files wholesale. The focused guardrail matrix passes 34 tests. This is test-ownership cleanup only and changes no runtime behavior. |
| 2026-08-31 | SIDERIUS / `siderius-exp` | `5fa7bd05` / `a1ad7d8` | Retired the tracked TIDMAD machine-config template and every supported production fallback to its dataset/output constants. Training, inference, scoring, anchor construction, sandbox initialization, and the one-iteration launcher now require the caller-selected physical root. The already-resolved `ResolvedMeasurementCapability` crosses the validator-to-tuner typed protocol and is reused for bounded probes and calibration identity; generic tuning no longer reconstructs TIDMAD identity from a path. The task-owned comparison tool and its three witness modules moved to `siderius-exp`, where it requires `SIDERIUS_CHECKOUT`, an explicit dataset root, and an experiment workspace root. Focused framework validation passes 63 tests; framework collection discovers 13,584 tests without error; the moved tool suite passes 15 tests and the exact-checkout external task/boundary matrix passes 165 tests; Ruff and diff integrity pass. Adversarial review found and removed obsolete tests that required uncomposed argv or machine-local fallback while preserving explicit-root transport, refusal-before-work, and identity-reachability witnesses. No training, inference, scoring, Health, or scientific policy changed. |
| 2026-08-31 | `siderius-exp` | `f60924c` | The bounded TIDMAD composition now loads `tasks/tidmad/runtime/scoring.py::TidmadDenoisingMetric` through the existing public metric-implementation seam instead of selecting the task-specific handle from SIDERIUS. The handle delegates exactly once to the task-owned frozen `score_vector`, while the generic `EvaluationMetric.evaluate()` authority still runs declared scoreability before arithmetic and constructs the unchanged result schema. Exact-checkout startup, metric-direction, package, streaming, inference, and task-local delegation evidence passes 23 focused tests; the broader adjacent external matrix passes 19 tests; Ruff and diff integrity pass. Adversarial review proved the loaded class source is the external task file and identified the next separate boundary: TIDMAD scoreability deserialization and the legacy uncomposed metric fallback still live in SIDERIUS. They were not pulled into this checkpoint because persisted `MetricSpec` values currently rebind through the framework contract vocabulary; deleting that vocabulary without a replacement would break record replay. This checkpoint changes ownership of executable arithmetic, not the formula, scoreability order, declaration, result schema, or scientific treatment. |
| 2026-08-31 | SIDERIUS / `siderius-exp` | `da5d1097` / `0cace7f` | The production tuner now requires the primary metric already bound by the active task composition; an uncomposed call refuses instead of deriving the TIDMAD metric from framework-owned geometry. The tuner retains one metric acquisition site and adds no branch or replacement default. Three focused refusal/acquisition witnesses pass, Ruff and diff integrity pass, and the exact-checkout startup plus all four external package contracts pass 26 tests after `siderius-exp` pins the new framework SHA. Adversarial review confirmed that the external SHA guards rejected the advanced but unpinned checkout before the dependency pin changed; the guards were preserved and the pin was updated only after the framework checkpoint existed. Two old Step-00 pseudo-tuner reachability tests still depend on multiple already-retired uncomposed scientific defaults and are not cited as evidence for this slice; they remain part of the framework-test ownership cleanup rather than justification for restoring a TIDMAD fallback. No metric arithmetic, direction, scoreability order, result serialization, task manifest, or scientific treatment changed. |
| 2026-08-31 | SIDERIUS / `siderius-exp` | `a0cde8be` / `58aa385` | Replaced the stale tuner metric witness that depended on an uncomposed TIDMAD handle with a framework-owned Quickstart composition witness. The surviving test proves that the run resolver returns the exact metric object bound by the composition; child-process metric execution remains covered by the external task source/delegation evidence rather than by a pseudo sandbox route that production composed tasks no longer use. The conversion removed 85 lines of task-shaped setup and obsolete contrast choreography, introduced no helper abstraction, and leaves the scoring-failure record tests generic through synthetic metric and contract identities. Nine focused framework witnesses pass, the file contains no real-task identifier, Ruff and diff integrity pass, and the exact-checkout four-task startup/package matrix passes 26 tests after the external dependency pin advanced. Adversarial review caught that merely entering the binding context did not reproduce the workflow's explicit `TaskCompositionRef` transport and, more importantly, that the old test observed `evaluate_metric` while composed production scoring uses the child `execute_scoring` route; the invalid oracle was removed rather than making the test double pretend the old route was current. No production code or scientific behavior changed. |
| 2026-08-31 | SIDERIUS | `7ff57261` | The scoring child now refuses at its production entry unless the caller supplies a task manifest, task-data-path identity, resolved dataset profile, and the complete transported evaluation-scope pair. Consequently supported execution can reach only the existing task-owned scoring route; it cannot fall through to an implicit TIDMAD metric or topology. Fifteen focused framework scoring/naming witnesses and 20 external composition, metric, and scope-transport witnesses pass; Ruff and diff integrity pass. Adversarial review preserved the public argv surface for now, added a reachability test proving `main()` performs the refusal before resolving any scientific default, and identified the now-unreachable legacy body plus its TIDMAD parity tests as the next physical-removal unit. The dead body was not mixed into this fail-closed checkpoint so intake behavior and source deletion remain independently reviewable. No composed metric arithmetic, scoreability ordering, secondary evaluation, output persistence, or scientific treatment changed. |

Qualification evidence matrix (latest complete run per task):

| Task | Exact revisions (SIDERIUS / `siderius-exp`) | Two iterations | Formal execution | Scientific result | Direction / trajectory | Cross-iteration state | Qualification reading |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Oxford-IIIT Pet | `3eb8fc67` / `b3bb1c2` | yes | Trial and Formal executed in both iterations | no valid score; all four candidates were Health-invalid at accuracy `0.02702702702702703` | accuracy, higher; no valid curve | iteration 2 consumed iteration-1 collapse feedback and proposed an anti-collapse variant | infrastructure PASS; scientific candidates invalid; manifest `no_records` is the correct scientific-authority outcome |
| Cancer Gene Identification | `3eb8fc67` / `b3bb1c2` | yes | iteration 1 produced one valid Formal after seven failed Formal attempts; iteration 2 exhausted fifteen Formal attempts under the task VRAM cap | best valid mean AUPRC `0.44797222164665007` from iteration 1; iteration-2 Trial scored `0.32718416507856324` | mean AUPRC, higher; the valid Formal trajectory has one point | iteration 2 restored the verified iteration-1 Formal incumbent | infrastructure PASS with bounded retry behavior; iteration-2 Formal failures are model/task-budget VRAM failures, not watchdog kills |
| DAVIS future prediction | `3eb8fc67` / `b3bb1c2` | yes | Trial and Formal succeeded in both iterations after one first-attempt Trial watchdog kill recovered through the existing retry path | valid Formal MSE in both iterations | MSE, lower; `0.01582557971089261` to `0.016200793074869296` (slightly worse) | iteration 2 consumed iteration-1 records under the same composed task identity | infrastructure PASS; lower-is-better ordering, Formal execution, retry recovery, Health, persistence, and two-iteration continuity are proven |
| TIDMAD qualification | `3eb8fc67` / `b3bb1c2` | yes | Trial and Formal executed in both iterations | no valid score; all four candidates produced constant-output collapse | TIDMAD score, higher; invalid Formal scalars were `-3.091274633731049` and `-14.259092650952104` and do not form a valid curve | iteration 2 explicitly consumed iteration-1 collapse evidence and tested CE after the focal-loss collapse | infrastructure PASS; scientific candidates invalid; this is a bounded classification-contract qualification, not Gold regression-treatment evidence |

This is the first synchronized four-task qualification against one exact
framework/experiment pair. It proves the separated multi-task execution
boundary at SIDERIUS `3eb8fc67` and `siderius-exp` `b3bb1c2`; it does not by
itself qualify Gold campaign treatment or scientific competitiveness.

Additional synchronized-run findings:

- the #388 Cancer workload produced a successful Formal attempt with the
  explicit 1,200-second budget preserved and no watchdog kill, but the H100
  completed that attempt below the historical 120-second failure boundary;
  the replay is therefore supportive but not counterfactual-discriminative,
  and #388 remains open;
- Cancer iteration 2 repeatedly exceeded its declared 16-GiB task envelope
  despite abundant physical H100 memory. This is correct budget enforcement
  over a model whose graph activations are large, not evidence that the pod had
  only 16 GiB available;
- TIDMAD failed every blocking qualification gate with one observed symbol,
  zero output standard deviation, and dominant-mode fraction `1.0`. The
  amplitude gate alone would still reject these candidates, so the outcome is
  unchanged by the separate Gold amplitude-only ruling;
- the synchronized TIDMAD workflow exercises the classification contract and
  may not be cited as evidence for the frozen Gold continuous-regression
  treatment;
- five ignored Python bytecode files were written into the SIDERIUS checkout
  during external execution. No tracked source changed, but a future boundary
  slice must prevent or redirect interpreter bytecode writes so the framework
  checkout remains physically read-only during consumer runs.

Current operational state:

- real task packs, task helper tools, Pets/DAVIS runtime implementations, and
  duplicate Gold Stage-1/Stage-2 launch assets have been removed from the
  separation branch after external ownership and replacement evidence landed;
- undeclared prompt guidance and Health science resolve to an explicit empty
  value. Quickstart remains an example only and is not a scientific fallback;
- Gold is operator-stopped; all synchronized H100 qualification chains have
  exited, and the remaining M6 deployment and release qualification stays
  deferred without being removed from the separation scope;
- no Gold workload has been launched from `siderius-exp`;
- the external Gold launcher no longer assumes repository co-location; it
  requires an explicit SIDERIUS checkout and has passed separated dry-run
  qualification, but not H100 launch or release qualification;
- all four imported real task manifests pass composition-only external validation; Cancer additionally has distinct two-network qualification and complete eight-network formal compositions;
- issue #383 has an external failing witness, a focused framework repair, and passing external acceptance evidence;
- issue #384 has an external failing witness proving the failure precedes any capacity decision, a generic isolated-worker repair, and passing external acceptance evidence;
- issue #385 has an external failing witness, a typed source-context repair, and passing compatibility evidence;
- issue #386 has an external failing witness, lazy legacy-config repair, and passing workflow/data-root compatibility evidence;
- issues #383--#387 and #389--#393 are repaired and closed with their
  published commits and validation evidence. The setup-only watchdog defect
  (#388) has a focused generic repair included in `3eb8fc67`; its synchronized
  Cancer replay succeeded without a watchdog kill but completed below the old
  120-second boundary, so a counterfactual-discriminative external witness is
  still required before issue closure;
- issue #396 is repaired by `e31da5c7`, externally accepted by a fresh
  two-iteration H100 Pets chain, and closed without promoting either invalid
  candidate;
- the prior RTX 5090 TIDMAD witness remains historical evidence. The latest
  synchronized H100 qualification supersedes it for merge-candidate
  compatibility and produced no Health-valid candidate;
- Cancer's real NatureBench files are verified outside the repositories. The
  synchronized H100 chain completed two LLM-driven iterations with valid
  Trial inference/scoring in both iterations and one valid Formal in iteration
  1; iteration 2 exhausted its bounded Formal retries under the declared VRAM
  cap;
- all eleven safe generic-fixture replacements are complete: the final Health cache and objective authority modules now use only synthetic or framework-owned example evidence, while real-task Health and objective parity is owned by `siderius-exp` PR #1;
- the two-pack minimal-example coverage matrix is frozen; quickstart's deterministic composed-scoring gap is closed, and synthetic masked regression now covers core scoring, task-owned Health, task-valid resource measurement, bounded production training over semantic supervision, offline literature-review ON/OFF topology, deterministic production-workflow traversal, record-level primary-only selection, checkout-portable resume/refusal, and standalone typed node invocation. The direct 38-file dependency audit is complete. The next checkpoint continues the safe generic-fixture cohort one responsibility at a time; no blocked or mixed file moves early. No real-task source removal begins before its assigned replacement evidence passes;
- Gold Stage-1/Stage-2 workflow ownership now lives under the external
  campaign package. `siderius-exp` PR #9 (merge `6a8d740a`) requires an
  explicit framework checkout, resolves campaign-owned task and calibrated
  Health files, passes a separated Stage-1 dry-run, rejects task-config drift,
  and preserves the Stage-2 authorization refusal. This is path and treatment
  evidence, not H100 launch qualification; deployment preflight and duplicate
  SIDERIUS campaign removal remain;
- the synchronized H100 run completed two iterations for Pets, DAVIS, Cancer,
  and TIDMAD. All four tmux sessions exited, no qualification workload remains
  active, and infrastructure validity is reported separately from scientific
  candidate validity.

## 13. Work-ledger rule

Every migration PR or operational step governed by this design must update this document with:

- the paths classified or moved;
- the responsibility decision and rationale;
- the commit or PR that landed the change;
- the targeted evidence run;
- any newly discovered coupling;
- any amendment to the migration plan.

Completed checkboxes without a commit, PR, or reproducible evidence reference are planning statements, not completion evidence.
