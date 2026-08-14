# Step 05c — Tuner execution contracts — detailed design

Part of **Step 05** (roadmap §15 step 5, §7c). Step 05's three submodule
designs jointly constitute the Step-05 acceptance entry (roadmap §19); the
Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **DRAFT — READY FOR OPERATOR REVIEW. Not frozen. Implementation NOT authorized.** |
| Design base | `13b08550` |
| Depends on | **Step 02** (Dataset Profile: channels, `ValueEncoding`) · **Step 03** (`ModelIOContract` decode rule) |
| Roadmap row | §15.1 `§7c Tuner execution contracts` |
| Risk | **Highest of the three** — it changes real execution behavior |

---

## 0. Source audit

```text
Roadmap §7c assumption:
  "filename templates at the engines; +128/argmax/int8 in inference_single;
   ≥6 inlined deliverable template copies; no owner today."

Audit evidence at 13b08550 — SUBSTANTIALLY STILL TRUE, with one half closed:

  CLOSED by Step 02: channel identity is derived.
    inference_single.py:341  profile_channels = dataset_profile.channels
    :656, :659, :850, :853    input_channel / target_channel (no literals)
    :337-339                  load_dataset_profile(...) at the subprocess
                              boundary, resolve_dataset_profile() otherwise

  STILL OPEN: the value ENCODING is inlined even though ValueEncoding
  declares it.
    :216-217   inputarr.astype(np.int16) + 128 ; targetarr ... + 128
    :318       (output_seq - 128)
    :305       output.argmax(dim=1)
    :685-686, :759-760, :861-862   np.int8 buffers and casts

  STILL OPEN: the deliverable template is inlined at every production site.
```

**Production deliverable census** (`abra_validation_denoised_…`), the census
the §14 row needs:

| Role | Site | Owner after Step 05 |
|---|---|---|
| **PRODUCER** | `execute_tools/inference_single.py:615`, `:892`, `:897` (three separate constructions) | 05c |
| **PRODUCER** (layout/dtype/attrs) | `execute_tools/array2h5.py:create_abra_file` | 05c |
| **READER** — cleanup | `core/sandbox_executor.py:1761`, `:2161` | 05c |
| **READER** — cleanup | `ml_hyperparameter_tune_agent.py:5438` | 05c |
| **PATH BUILDER** | `ml_hyperparameter_tune_agent.py:1083` `_denoised_path` | 05c |
| **READER** — scorer | `execute_tools/denoising_score_single.py:163`, `:166`; `scoring_utils.py:364` | **Step 06 — NOT touched** |
| **READER** — health peeks | HealthGate peek paths | **Step 08 — NOT touched** |

Seven production sites are 05c's; the scorer and peek readers are not.

### 0.1 `scripts/*` census — classified by reproducibility role

`scripts/*` are **not** excluded merely for being "tooling". Each
deliverable-literal script is classified by whether it participates in
reproducing, resuming or replaying a run:

| Script | Role | Disposition |
|---|---|---|
| `finalize_recovered_diagnostic_round.py` | **canonical reconstruction** — rebuilds a round's artifacts | **MIGRATE** to the DeliverableSpec |
| `pregate_runtime_control_validation.py:214` | **production-adjacent** — pre-Gate validation globs live artifacts | **MIGRATE** |
| `v18_wave_summary.py:55,121` | **production-adjacent** — audits a workspace's artifact set against scope | **MIGRATE** |
| `fcnet_health_metrics_scan.py`, `fcnet_full_file_scan.py`, `fcnet_diversity_pearson_scan.py`, `investigate_pearson_feasibility.py`, `official_paper_health_scan.py` | **diagnostic-only** — one-off analyses over historical outputs, several already parameterized (`official_paper_health_scan.py:96` takes the template as a CLI default) | **RECORD, leave literal** — migrating adds no capability, and they must keep reading *historical* artifacts written before this PR |

Rationale for the split: a script that **reconstructs or validates a run**
must agree with the producer, or a renamed deliverable silently breaks
recovery. A script that **analyses historical files** must keep matching the
names those files already have — migrating it would be actively wrong.

**Finding surfaced, not silently absorbed**: the three migrated scripts add
~3 sites to 05c but no new responsibility (same contract, same authority,
same rollback). They do **not** justify a fourth PR.

## 1. Observable final capability

> The **engines write, name and clean deliverables through one explicit
> contract**, and the **value encoding they apply comes from the Dataset
> Profile's `ValueEncoding` and the `ModelIOContract` decode rule** — not
> from literals inlined at each site. Launch mechanics (argv, file IPC,
> sentinels) carry no task literals.

**Deliberately NOT claimed — the binding Step-06 boundary:**

- **scoring is NOT generic after Step 05.** Only its *launch plumbing* is.
  The scoring spawn keeps invoking `denoising_score_single.py`, TIDMAD-bound,
  and 05c never opens its internals. Scorer-side `abra_*` literals
  legitimately **remain**.
- not metric identity, direction, aggregation or scoreability (Step 06);
- not HealthGate peek semantics (Step 08);
- not cleanup *policy* (Step 11) — only that cleanup resolves names via the
  contract instead of an inlined glob.

## 2. Four-contract discipline

This PR touches exactly one of the four, and must not conflate them:

| Contract | Owner | 05c's relationship |
|---|---|---|
| **Input Dataset Contract** — what exists to read | Step 02 | **consumes** (channels, encoding) |
| **Model I/O Contract** — in-memory tensors | Step 03 | **consumes** (decode rule, already contract-keyed at `inference_single:262-273`) |
| **Deliverable Contract** — what an attempt persists | **§3 below** | **produces / proposes** |
| **Metric Scoreability Contract** — what makes a deliverable scoreable | Step 06 | **untouched** |

That TIDMAD happens to use int8 HDF5 for both its input and its deliverable
is a **coincidence of one task**, not evidence the contracts are one.

## 3. Deliverable Contract ownership — the material decision

The §14 row leaves ownership open between §7c (first producer-side need) and
§10 (scoreability reader). Deciding from the §0 census:

**Recommendation: option (C) — provisional extraction here; final ownership
confirmed by Step 06.**

Reasoning from source, not from execution order:

- 05c owns **all four producer-side facts** — naming, layout, dtype, attrs —
  and every production *writer* and *cleanup* site. That is a genuine
  ownership claim, and it is why the extraction happens here.
- But **completeness** and **identity/indexing** — what makes a deliverable
  set *scoreable*, and how a file maps to an input identity — are exercised
  only by the scorer and the peek readers, which are Step 06's and Step 08's.
  05c can neither test nor break those meanings.
- Choosing (A) "§7c owns it, finally" would settle a contract using evidence
  from **one side of it**, and would then require Step 06 to either accept a
  producer-shaped abstraction or re-open a supposedly settled row.

So 05c lands the **smallest provisional TIDMAD adapter** that the seven
production sites need, records an explicit future decision boundary, and
Step 06's design confirms or counter-proposes final ownership.

**Consequence for the contrast (§5)**: because the extraction is provisional,
05c must **NOT** claim arbitrary/non-HDF5 deliverable formats. The non-HDF5
rung belongs to whichever design wins final ownership — exactly as the §14
row already specifies.

**Ownership timing — one coherent rule** (replacing the earlier inconsistent
wording that said both "Step 06 confirms" and "the row completes at step 11"):

```text
Step 05c : producer-side PROVISIONAL extraction. Ownership stays OPEN.
Step 06  : the NEXT MANDATORY ownership review, now holding producer AND
           scorer/scoreability evidence. It MUST either
             (a) CONFIRM final ownership, or
             (b) record exactly which consumer evidence is still missing
                 and keep the row OPEN.
Steps 08/11 : may add later consumer evidence. Neither is predetermined as
           the final decision point.
```

Step 05 therefore does **not** promise that Step 06 will settle ownership —
only that Step 06 must decide-or-say-why. And it does not nominate Step 11
as the owner merely because later consumers exist there.

**This remains an operator decision to confirm** (§16), because it binds
Step 06's design surface.

### 3.1 What the provisional contract IS — frozen representation

The design must not leave "a new provisional contract module" ambiguous.
Classified against current source:

| Question | Answer |
|---|---|
| **USER-AUTHORED?** | **NO** |
| **PERSISTED?** | **NO** — not written as its own artifact |
| **SERIALIZED?** | **NO** new serialization format; it rides transports that already exist (§3.2) |
| **RUNTIME-ONLY?** | **YES** — an internal typed `DeliverableSpec` constructed at run scope |
| **REQUIRED FOR LEGACY RUNS?** | **NO** — legacy runs construct the identical TIDMAD spec from values they already carry |
| **DEFAULT / ADAPTER?** | the TIDMAD instance is the derived default; no declaration is needed to obtain it |
| **OWNER?** | provisionally 05c, ownership OPEN (§3) |

**No new YAML. No new top-level config file. No new task-config block. No new
train-config block.** A typed runtime value is not a configuration
architecture, and "DeliverableContract" being a useful concept name does not
authorize a user-facing format.

Its fields are **derived**, not declared: the naming template and layout come
from the existing TIDMAD compatibility values (today's inlined literals,
extracted verbatim); dtype and offset come from `DatasetProfile.encoding`,
which is already declared by Step 02 and already transported (§3.2).

If implementation finds a deliverable semantic that genuinely cannot be
derived this way, that is a **MATERIAL STOP** and a design review — not
permission to widen the config system (§13).

### 3.2 Subprocess transport — frozen, and it requires NO new argv

Mechanically traced parent → subprocess at `13b08550`:

```text
sandbox_executor._write_dataset_profile_config(exp_id)
    writes  configs/dataset_profile_{exp_id}.json = resolve_dataset_profile().model_dump()
    passes  --dataset_profile_json   at :1325 (training), :1661 (inference), :1908 (scoring)

inference_single.py:337-341
    dataset_profile = load_dataset_profile(args.dataset_profile_json)   # fails closed
    profile_channels = dataset_profile.channels
```

The parent's own docstring (`:1220-1238`) states the rule this PR follows:
*"One declaration, one file, three consumers … through the same config-file +
argv-flag mechanism already used for `--model_cfg` and friends."* Step 03
added `--model_io_json` by the same pattern, explicitly noting *"No new IPC is
introduced — §16 routes IPC to Step 11."*

**Consequences, and they are the reason argv parity is honest here:**

1. The **full `DatasetProfile` — including `ValueEncoding` — already crosses
   to all three subprocesses** and is already loaded at `:337`. The encoding
   derivation (`+128`/`int8`) therefore needs **no new argument**: the
   authority is already present and merely unconsulted.
2. The **`ModelIOContract` already crosses** (`--model_io_json`, omitted for a
   legacy prose-only contract — the existing Regime-A adapter), so the decode
   rule is available without new transport.
3. The deliverable **name** is composed from `denoising_model`, `run_name`,
   `exp_id` and `file_index` — all already argv items.

**Frozen acceptance**: one semantic source; **no ambient second resolution**
in the child (the subprocess must not call `resolve_dataset_profile()` when it
was given a profile path); no duplicate deliverable literals; and
**`--dataset_profile_json` / `--model_io_json` are NOT re-plumbed** — Step 05c
consumes the Step-02/Step-03 transports rather than adding a third.

Therefore §4's *"argv byte-identical"* is a genuine criterion, not an
aspiration. **If implementation nevertheless proves a new argument is
unavoidable, the Stage-A criterion must be honestly downgraded to
"argv identical except one additive, documented flag, with old-run behavior
stated" — it must not be claimed as byte-identical.** Adding an argument when
the existing transport already carries the authority is equally a defect.

### 3.3 Legacy run / config replay acceptance — MANDATORY before freeze

For a representative pre-Step-05 TIDMAD run, all of the following must load
**without migration** and resolve identically under 05c:

| Surface | Required property |
|---|---|
| existing **model config** JSON | loads unchanged; same effective model semantics |
| existing **loss config** JSON | loads unchanged; same effective loss semantics |
| existing **train config** | loads unchanged; same required defaults |
| existing **TrialConfig** / tuner config | loads unchanged; deep-equal |
| persisted execution input (`dataset_profile_{exp_id}.json`, `model_io_{exp_id}.json`) | loads unchanged |
| launch semantics | same argv (§3.2) |
| deliverable name / layout / dtype / attrs under TIDMAD | identical |

**No new mandatory field may make a stored run unreadable.** The legacy
adapter property is explicitly testable and must be tested:

```text
old stored config  ->  the SAME TIDMAD DeliverableSpec
```

Proven by **deterministic config/launch resolution** — a full real training
run is not required for the replay property (Gate 2 exists for the execution
property, §9, which is a different question).

## 4. Stage-A compatibility surfaces

"Behavior unchanged" is not a criterion. The named surfaces:

| Surface | Criterion | Oracle status |
|---|---|---|
| training argv | **byte-identical** | EXISTING (spawn captures) |
| inference argv | **byte-identical** | EXISTING |
| scoring argv plumbing | **byte-identical** | EXISTING — and untouched by design |
| file IPC (sidecars, timing JSON, runtime-observation sidecar) | **deep-equal** | partially EXISTING — classify at Checkpoint 0 |
| sentinel protocol (`_OK_<exp_id>`, silent-crash detection) | **identical sequence** | EXISTING (`sandbox_executor:1498-1519`) |
| produced deliverable files | **byte-identical** artifacts | **MISSING — Checkpoint 0 must capture** |
| deliverable filename set | **identical** | **MISSING — Checkpoint 0** |
| post-cleanup filesystem set | **identical** | **MISSING — Checkpoint 0** |

The three missing captures are the highest-value Checkpoint-0 work in all of
Step 05: they are the only oracles that can prove a write/cleanup refactor
moved nothing.

## 5. Stage-B atomic contrast

**One axis: deliverable transport.** Under the TIDMAD profile, with a
**renamed deliverable template** supplied through the provisional contract,
the engines and cleanup must resolve names **exclusively** through the
contract — no inlined template executed in engine or cleanup code.

Reds when any of the seven production sites still executes its own literal.

Scorer-side literals remain and are explicitly **out of the assertion's
scope** — a "no `abra_*` anywhere" assertion is unsatisfiable at Step 05 and
would be a test-design error. Dataset-axis coverage comes from 05a; encoding
coverage is asserted separately against `ValueEncoding`.

## 6. Checkpoint C — live integration

A **real production training and inference spawn** must cross the contract:
the deliverable is written, named and cleaned through it, with the encoding
derived. A config- or helper-only test is explicitly **insufficient** here —
the whole failure class lives in the subprocess boundary.

## 7. Failure classes

1. A renamed deliverable is written by one site and cleaned by another using
   a stale literal → orphaned artifacts, silent disk growth, and a scorer that
   reads nothing.
2. Encoding derivation changes a written byte → every downstream score moves.
   **The deliverable is scientific evidence; a byte change is not a refactor.**
3. Scorer or peek semantics get pulled forward → Step 06/08 boundary breach.
4. A sentinel or argv ordering shifts → crash detection or reproducibility
   breaks in a way unit tests do not see.
5. The provisional contract is over-claimed as final → Step 06 inherits a
   producer-shaped abstraction it cannot use.

## 8. Test disposition

| Test family | Verdict |
|---|---|
| argv / spawn capture tests | **KEEP** — the parity oracle |
| tests pinning an inlined filename literal at a production site | **REWRITE** — they defend the duplication |
| `create_abra_file` layout/dtype tests | **UPGRADE** — assert through the contract |
| scorer-side tests | **KEEP UNCHANGED** — Step 06's surface |
| any test asserting helper call order inside the engines | **DELETE** — implementation-detail pin with no compatibility meaning |

Prefer observable evidence — actual argv, actual persisted artifact, actual
post-cleanup filesystem set — over private dict shapes.

## 9. Gates

| Gate | Decision | Rationale / flip |
|---|---|---|
| **Gate 1** | **NOT REQUIRED** | no LLM-visible surface. **Flip**: if any prompt or `LLMBridge` kwarg changes |
| **Gate 2** | **REQUIRED — bounded** | This PR changes **real execution behavior** at the subprocess boundary. Failure classes 1, 2 and 4 are precisely the ones that survive deterministic testing and appear only when a real spawn writes a real artifact and cleanup runs against it. The roadmap's own §17 note names §7c as a real-execution surface. Size the smallest case that trains, infers, writes, scores and cleans one attempt; read `docs/gates/gate_testing_standard.md` at implementation time and use the current approved pro LLM configuration |

## 10. Validation budget

Checkpoint 0 (three missing artifact/filesystem captures — **before any
production edit**) → deterministic contract tests → argv/IPC/sentinel parity
→ Stage-B transport rung with a mutation per production site → Checkpoint C →
**bounded Gate 2** → exact-head CI.

Deliberately larger than 05a/05b, and deliberately not a campaign: one
bounded real attempt, not a matrix.

## 11. Rollback boundary

`execute_tools/inference_single.py`, `execute_tools/array2h5.py`,
`core/sandbox_executor.py` (cleanup/naming only), the tuner's `_denoised_path`
and cleanup glob, the new provisional contract module, and directly affected
tests. **Not** the scorer, **not** HealthGate peeks, **not** `scripts/*`.

## 12. Convergence-ledger implications

- **Deliverable Contract** — 05c supplies the producer-side census (§0) and
  the provisional runtime extraction (§3.1). Row stays **OPEN**, owner
  **still TBD**. Per §3's timing rule, **Step 06 is the next mandatory
  ownership review** and must confirm-or-say-why; steps 08/11 may add
  consumer evidence but are **not** predetermined decision points. The
  row's earlier "completes at step 11" phrasing should be corrected to
  match.
- **Value encoding (+128/int8/256)** — the row is already SETTLED (§4
  declares, §5 derives). 05c is a **consumer** of that settlement; it adds no
  authority and creates no shared config.
- **Model I/O contract** — 05c consumes the decode rule already keyed at
  `inference_single:262-273`. **RECORD ONLY** disposition unchanged.

## 13. Stop conditions

- Preserving byte-identical deliverables requires changing the encoding
  semantics → STOP.
- The provisional contract cannot serve the seven sites without importing a
  scoreability or metric semantic → STOP; that is Step 06.
- Cleanup cannot be made contract-driven without changing cleanup *policy* →
  STOP; policy is Step 11.
- A sentinel or argv change becomes necessary → STOP and surface it; those
  are frozen compatibility surfaces.

## 14. Implementation milestones (semantic)

1. Checkpoint 0: capture artifacts, filename set, post-cleanup filesystem set.
2. Extract the provisional Deliverable Contract; migrate the two cleanup
   readers and `_denoised_path` (readers first — they are reversible).
3. Migrate the three producer sites and `create_abra_file`.
4. Derive the value encoding from `ValueEncoding` + the contract decode rule.
5. Stage-B transport rung + per-site mutations; Checkpoint C.
6. Bounded Gate 2.

## 15. Implementation ledger

*(empty — populated at implementation kickoff)*

## 16. Remaining operator decisions

1. **Deliverable Contract provisional ownership and its timing rule (§3)** —
   the recommendation is: provisional extraction here, ownership OPEN, Step 06
   as the next mandatory confirm-or-say-why review. This binds Step 06's
   design surface, so it should be confirmed rather than assumed.

That is the only one. Gate-2 *scope* is **not** an operator design decision:
Gate 2 is REQUIRED (§9), its shape is "the minimum bounded real attempt" under
the current Gate standard, and its cost/runtime limits belong to the
Implementation Working Rules, not to this design.

## 17. Configuration-architecture preservation (Step-05 cross-cutting invariant)

Binding for this PR (roadmap §15.1a):

- **model config remains model config; loss config remains loss config; train
  config remains train config.** They are not replaced by an
  "ExecutionConfig" or "TaskExecutionContract", and a new task/dataset keeps
  using these established categories wherever their semantics apply.
- `DatasetProfile` and `ModelIOContract` are **consumed, never copied** into
  train/model/loss/tuner config.
- No existing required key is renamed or restructured.
- Deliverable semantics stay a **distinct concept** — they are genuinely not
  the input dataset contract, the Model-I/O contract, or metric scoreability
  — but conceptual distinctness does **not** authorize a user-facing config
  format (§3.1).
- Any genuinely unavoidable new declaration must be **additive**, must
  preserve legacy interpretation and loading, and must state its adapter
  boundary. Discovering one is a **MATERIAL STOP**, not silent widening.
