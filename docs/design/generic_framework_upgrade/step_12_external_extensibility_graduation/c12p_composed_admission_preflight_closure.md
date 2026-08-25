# C12-P — Composed Admission / Preflight Closure

**STATUS: CONFIRMATION MATRIX ACCEPTED BY THE OPERATOR (2026-08-24). DESIGN
BOUNDED. SPECULATIVE IMPLEMENTATION AUTHORIZED WHERE DISJOINT FROM ACTIVE
PR-12d. CANONICAL MERGE AFTER LANDED-12d RECONCILIATION. DO NOT MERGE.**

A bounded corrective prerequisite unit between landed PR-12d and canonical
PR-12e, per `pr_12e_out_of_tree_graduation.md` §U.8. Parallel to `C12-I`.

```text
                   PR-12d LAND
          ┌─────────────┴─────────────┐
       C12-P                       C12-I
 admission / preflight        objective identity
          └─────────────┬─────────────┘
               12e §T reconciliation → FINAL 12e FREEZE → G-12e
```

---

## A. Source anchors

| anchor | value |
|---|---|
| `LANDED_MASTER_SHA` | **`c991d6f65e156d0ad48c7e35bbfa4733ef33d8e9`** |
| `CURRENT_PR12D_HEAD` | **`d2095f6ca70c0e1ecb883110f0f1ddfc3ffe05a1`** (moved from `dd369f3b` during this session — it moves; re-read before any reconciliation) |
| `CURRENT_PR12E_DESIGN_HEAD` | `09d696be80ba4f7b4df477d446fb09e54042d726` |
| `CURRENT_PR12E_SPECULATIVE_HEAD` | `c94709eecc4663f69d6abe992b37a2fa9e9ee84b` |
| 12e speculative base (where the audit ran) | `bbc35d7654e95efe83135cb407b0519eff13608c` |
| `LANDED_PR12D_SHA` | **NOT YET** — §K governs |

Worktrees (all created by this session; none touches PR-12d's live checkout):

```
/home/yuema137/siderius-c12p-preflight-audit   c12p-composed-admission-preflight  (design + integration)
/home/yuema137/siderius-c12p-12dref            dd369f3b detached                  (READ-ONLY 12d reference)
/home/yuema137/siderius-c12p-w1-b7b11          c12p-w1-b7b11                      (stream W1)
/home/yuema137/siderius-c12p-w2-b3             c12p-w2-b3                         (stream W2)
/home/yuema137/siderius-c12p-w3-b1b2           c12p-w3-b1b2                       (stream W3)
```

### A.0 ⚠️ REGISTER COLLISION — binding on every implementer

**PR-12d has its OWN blocker register `B0…B11` (its §D, doc line 350ff), and it
is a COMPLETELY DIFFERENT register from PR-12e §U.1's `B1…B11`.**

| id | **PR-12d §D** means | **PR-12e §U.1** means |
|---|---|---|
| `B1` | composition loader cannot hand a task its scope authority — CLOSED | wall-time pre-flight is TIDMAD-only |
| `B2` | legacy `build_sample_set` unconditional — CLOSED | VRAM pre-flight prices at TIDMAD's `T=40000` |
| `B4` | no trial anchoring ⇒ legacy scoring branch — CLOSED | second reachability of the probe batch builder |
| `B10` | `DeliverableNaming` mandates `file_index` — CLOSED | mode fallthrough (= F-12d-26) |
| `B12` | pre-phase GPU probe (= F-12d-25) — CLOSED by `bbc35d76` | *(not in 12e's register)* |

**Every `B<n>` in this document means PR-12e §U.1's register.** An instruction
citing a bare `B<n>` from any other document must be rejected as ambiguous.

### A.1 ⚠️ Environment hazard that invalidates execution evidence

`/home/yuema137/SIDERIUS/.venv` carries an editable install
(`__editable__.siderius-0.1.0.pth` + `__editable___siderius_0_1_0_finder.py`)
mapping every SIDERIUS package to `/home/yuema137/SIDERIUS` — PR-12d's live
checkout. A probe run without `PYTHONPATH=<worktree>` silently imports the
**wrong tree** and reports 12d's unlanded behaviour as master's. One forensic
agent hit this and caught it; all were re-instructed and re-verified.
**Every executed claim in this document was produced with `PYTHONPATH` pinned
and `module.__file__` asserted.**

---

## B. The corrective claim — as ruled by the operator

> **Close the bounded generic-runtime defect family demonstrated by the
> confirmed matrix:**
>
> 1. **task-specific data-shape/state must not accidentally control
>    task-neutral runtime admission / observation / policy / watchdog
>    behaviour;**
> 2. **TIDMAD-only resource/topology assumptions must not be applied to
>    unrelated composed tasks without explicit applicability;**
> 3. **composed foreign tasks must not silently produce or consume
>    TIDMAD-identified calibration/runtime state.**

### B.1 Non-goals — each is a thing a reader will assume and must not

| non-goal | authority |
|---|---|
| Complete runtime redesign | operator §1 |
| Making every subsystem task-composable | operator §1 |
| A new generic **measurement-identity capability family** | operator §4 — recorded as future debt |
| Making the TIDMAD workload resolvers task-composable | 12d already recorded this as "Option A … explicit post-Step-12 debt" |
| A production fix for **B8** | operator §10 — sentinel + debt note only |
| Any task-name dispatch, task catalog, or topology catalog | operator §7 of the brief; and the predicate already exists |
| Repairing PR-12d's own `B10`/F-12d-26 | `OWNER: PR-12d`; closed by `a9b943d5`, which is **docs-only** — no production line exists to duplicate |
| Any LLM-facing prompt or schema-description change | routed to a separate Gate-1 unit — §H |
| Claiming any repair through `resolve_scoring_workload` | operator §12 — it has **no production caller**; recorded separately as dead capability |
| A repo-wide exception-style cleanup | operator §11 — the anti-pattern conversion stays bounded to the confirmed subsystem |

---

## C. Confirmed disposition matrix

Operator-accepted, 2026-08-24. Every verdict below was independently
re-derived from source by the integration owner, not taken from a report.

| id | defect | verdict | loud/silent | 12d overlap |
|---|---|---|---|---|
| **B1** | wall-time pre-flight is TIDMAD-only | **CONFIRMED** | loud, **misattributed to the LLM's configuration** | DISJOINT owners; the gate file overlaps |
| **B2** | VRAM prices from a raw `40000` while the model is built from the config CLASS | **CONFIRMED** | divergence silent; refusal loud + names a dead knob | OVERLAPS |
| **B3** | `ProposalOutput` applies TIDMAD's PSD divisibility to every task | **CONFIRMED** | loud, wrong error text | DISJOINT |
| **B4** | second reachability of the probe batch builder | **CONFIRMED as a loud RAISE path** | loud, misattributed to the **candidate model** | DISJOINT |
| **B5** | composed runs write calibration under `task_identity="tidmad_denoise"` into `~/.siderius` | **CONFIRMED** | **SILENT, EXIT 0** | DISJOINT owners; write site overlaps |
| **B6** | task/data-shape state gates task-neutral runtime safety machinery | **CONFIRMED and materially broader than reported** | **SILENT, EXIT 0** | OVERLAPS (12d authored part of it) |
| **B7** | `--max_steps_per_attempt` inert on the composed route | **CONFIRMED** | **fully silent — zero output** | OVERLAPS |
| **B8** | `order_strategy="sequential"` crashes the composed training child | **NOT CURRENTLY REACHABLE** | n/a | — |
| **B11** | TIDMAD-scale defaults on the generic path | **CONFIRMED and broader than reported** | silent | mixed |

**B8 is removed from production-fix scope** (operator §10) and becomes a
latent-risk sentinel — §I C8.

---

## D. Corrections the confirmation made to the §U.1 register

A design that silently repairs its source's errors teaches nothing.

| # | §U.1 said | source says | consequence |
|---|---|---|---|
| **E1** | the tuner's twin of the B3 rule *"IS composition-gated"* | that describes **PR-12d**. On master `nodes/…/planning.py:377-381` calls `_validate_data_config(…, tidmad_topology(run_profile).dataset)` **ungated** | the proposer-vs-tuner asymmetry is **created by 12d**; post-12d the finding is *sharper*, not stale |
| **E2** | B4 fails with `ProbeInfrastructureError → ABORT` | the applicability `ValueError` is raised inside `executors.setup()` and downgraded by `core/runtime_control/probe.py:417-420` to `ProbeResult(status="load_failure", error="candidate load failed: …")`. `ProbeInfrastructureError` is never involved | the record **blames the candidate model**. A falsifier must assert on `probe_status`, never on an exception type |
| **E3** | *(unstated)* | **B4 fires BEFORE 12d's B12 guard** — `execution.py:439` runs inside `run_admission_preflight`; `execution.py:608` runs later | landing 12d does **not** make a composed formal round with a time budget survive. It still dies earlier, at B4 |
| **E4** | B1's blast radius framed as the Gate path | the frozen 12d commands set no budget (§F) — but **CLAUDE.md's own standard launch command sets both** | B1's real blast radius is *the documented operator surface* |
| **E5** | B1 *"dies at `[Pre-flight 2/2]`"* | the `RuntimeError` is caught by the **attempt-level** handler (`ml_hyperparameter_tune_agent.py:1522`) and recorded as `attempt_failure`, `failure_type="RuntimeError"`, `failure_stage="time_estimation"`, `counts_toward_attempt_budget=True`, with the memory line *"Do not repeat the failing configuration unchanged."* | profile-invariant ⇒ **every** attempt fails identically until the budget is exhausted, **while durably teaching the LLM that its configuration was at fault** |
| **E6** | B5's guard *"tests only that the fields are non-blank"* | the guard is a **TAUTOLOGY** — `task_identity` and `data_shape_class` are `str = Field(min_length=1)` (`core/runtime_control/measurement_capability.py:53,59`), so the clauses can never be False; `probe_available` is never consulted | the only real condition is `uuid`. The guard's own comment promises an outcome the type system makes unreachable |
| **E7** | B5 *"a later TIDMAD run reads a foreign task's timings as its own"* | **not reachable today** — historical duration is barred from every execution decision by operator decision 2026-08-02, guarded by two negative test files; `as_estimate` has **zero** production callers | state the harm honestly as **permanent corruption of an append-only machine-global corpus** + an armed trap. Overstating it invites the fix being judged against a failure that cannot be demonstrated |
| **E8** | B7 *"one `(non-fatal)` line"* | the mechanism is a **silent early return** — `nodes/…/runtime.py:906-907` `if train_sample_set is None: return None`. The swallowed-`ValueError` path is **unreachable for this cause** | there is **no log line to grep for**. Zero output |
| **E9** | B8 intermittent, *"a Gate could pass three times and fail the fourth"* | `--order_strategy` is emitted **inside** `if sample_set is not None:` and so never crosses for a composed run | **not currently reachable.** The live defect is a **false provenance record**: `resolved_order_strategy` records `"sequential"` as executed while the child ran `"shuffle"` |
| **E10** | *(unstated)* | **B1 and B2 are LATENT on master and ARMED by PR-12d.** Master ships only `tidmad.yaml`; its non-TIDMAD fixtures are in the legacy TIDMAD wire form and do not trip the predicate. 12d ships `pets.yaml`/`davis.yaml` and the generic-form profiles | **C12-P must branch from landed 12d, not master** — §N.0 |

---

## E. Prior art — C12-P is a CONFIRMATION, not a discovery

**PR-12d's own pre-Gate reachable-path census `D-12d-52` (its doc line 4021,
written 2026-08-24) had already found and dispositioned as DEBT almost every
item 12e later re-discovered:**

| 12e §U.1 | 12d `D-12d-52` row | 12d's own words |
|---|---|---|
| B1 **and** B4 | **A7 / D1** | *"DEBT — but a LAUNCH CONSTRAINT … not reached by the frozen command, which sets no time budget"* |
| B2 | **A5** | *"DEBT — did NOT bite"* |
| B5 | **A4** | *"durable FALSE PROVENANCE, wrapped in try/except so silent"* — and it already recorded **"145 of 241 existing records"** |
| B6, B7 | the watchdog/sidecar row | *"DEBT … unfixed by design"* |
| B8 | **D1–D3** | *"DEBT — LAUNCH CONSTRAINTS"* |
| **B3, B11** | — | **genuinely new to the 12e audit** |

⇒ **The §U.8 ruling does not overrule PR-12d. It ratifies, and gives an owner
to, a triage PR-12d had already made in writing.** C12-P cites `D-12d-52` as
prior art rather than re-deriving it.

---

## F. The B1 operational-blocker question — ANSWERED: **NO**

§U.8 item 2 required one determination: *do 12d's remaining frozen Pets/DAVIS
launch commands set a non-null wall-time budget?*

**NO. 12d records B1, does not expand scope, and C12-P owns it.** Three
independent layers:

1. The frozen §D8a.1 commands pass neither flag.
2. **No default can substitute one.** `nodes/…/cli.py:246-263` — both
   `default=None`; `cli.py:613-616` **omits the key entirely** when absent, so
   no schema coercion can reach it; `agent/schemas/hyperparam_tuning.py:1821,1833`
   — both `default=None`; `execution.py:411` gates the whole block on
   `if chosen_time_budget is not None:`. No YAML default exists.
3. **Executed**: the three most recent real G-12d logs contain `[Pre-flight 1/2]`
   and **zero** `[Pre-flight 2/2]`.

12d had already declined it in writing (`D-12d-52` A7/D1: *"an explicit
do-not-do for these tracks"*).

### F.1 One residual trap PR-12d should close, docs-only
12d §D8a.1 contains the hedge *"the exact … **time-budget** values are set at
launch time"*, which invites the exact flag `D-12d-52` forbids and would
detonate B1 on a contrast track. **Recommendation to PR-12d (not C12-P's
edit): strike "time-budget" from that sentence.**

---

## G. Root-cause clusters — FINAL

Nine routed items reduce to **four defects, one ownership-boundary defect, and
one meta-defect**.

### Cluster A — APPLICABILITY IS NEVER DECIDED
*A TIDMAD-physical mechanism is reachable from generic orchestration for every
composed task because nothing on the path asks the membership question.*
Members: **B1** (+ its masked sibling sites), **B4**, **B3**'s applicability half.

### Cluster B — A TASK-OWNED VALUE IS NOT PROPAGATED, AND A TIDMAD LITERAL FILLS THE GAP
*A generic consumer reads a RAW dict with a TIDMAD-scale fallback while a
validated authority for the same value is in scope.*
Members: **B2**, **B11**. This is a direct violation of a standing CLAUDE.md
rule — *"execution code reads from the schema, not from raw dicts"* — so it
needs no new architecture, only removal of the fallback.

### Cluster C — ONE SCIENTIFIC RULE, SEVERAL IMPLEMENTATIONS, DIVERGENT GUARDS
Member: **B3** (and its prompt-layer twin, routed out — §H).

### Cluster D — GLOBAL-STATE IDENTITY CONTAMINATION
Member: **B5**. Highest severity *by kind*: silent, exit 0, durable, outside
the workspace, on an append-only store with **no TTL, no delete path and no
task invalidation**.

### Cluster B′ — A LEGACY ARTIFACT'S **PRESENCE** USED AS A CAPABILITY PREDICATE
*The dominant finding of the confirmation, and the operator's §2 ruling.*

The code asks *"did a TIDMAD SampleSet arrive?"* where the question is *"does
this run have a scope / does it want runtime control?"* — at **five** sites in
`core/sandbox_executor.py` (master): `:1582`, `:1647`, `:1940`, `:1982`, `:2044`.

A composed contrast run has `sample_set is None` **by construction** under
PR-12d. Everything nested under that predicate is therefore silently not
emitted:

| flag | consequence when dropped |
|---|---|
| `--runtime_observation_out` | **no runtime session in either child** |
| `--runtime_policy_json` | **no in-subprocess admission decision** |
| watchdog wiring | **`--runtime_watchdog` is a complete no-op for BOTH phases** |
| `--timing_out_json` | no inference timing sidecar |
| `--train_portion` | the LLM's value silently ignored |
| `--train_base_seed` | child falls back to `hash(exp_id) % 2**31` — `PYTHONHASHSEED`-randomized ⇒ **per-epoch subsampling is not reproducible** |
| `--order_strategy` / `--file_order_json` | LLM ordering silently ignored (this is why **B8 is unreachable**) |

Members: **B6** (materially broader than reported — it is *both* children, not
just inference), **B7**, and the reachability half of **B8**.

The operator's statement of the principle, which is the design's north star:

> **task/data-shape state must not serve as applicability authority for
> task-neutral runtime safety machinery.**

PR-12d itself named and fixed this exact shape one predicate over
(`_has_scope_to_train_from`: *"asks 'did a legacy TIDMAD SampleSet arrive?' when
the question it needs answered is 'do I have a scope to train from at all?'"*).
That function is the **canonical seam** for the parent-side twin.

### Cluster F — THE META-DEFECT: THE ENFORCEMENT CENSUS CANNOT SEE THIS SURFACE

`tests/unit/execute_tools/test_step12_pr12bc_b2_topology_contract.py:177-187`
declares `GENERIC_CORE_MODULES` — **nine** modules that must never decode the
opaque topology. **Not one is an admission, pre-flight, runtime-control or
proposer module.** Meanwhile **nineteen** production modules call
`tidmad_topology()` / `resolve_tidmad_topology()`, including every module
Cluster A names.

⇒ **The census that exists to prevent exactly this defect is green because its
file set omits the directory where the defect lives.** Third census-blindness
shape (F-12bc-9's, one subsystem over) — and the best single explanation for
Cluster A surviving 12a, 12bc and into 12d.

**Measured on the PR-12d head as well, and it has got worse, not better:**

| | master `c991d6f6` | 12d `d2095f6c` |
|---|---|---|
| modules named in `GENERIC_CORE_MODULES` | 9 | **9 — unchanged** |
| production modules decoding the opaque topology | 19 | **21** |

PR-12d added two more decoders and extended the census by zero. The gap is
structural and widening, which is why Cluster F's fix — deriving the census
file set from composed reachability instead of hand-listing it — is the
highest-leverage deliverable in this unit: it is the only one that catches the
*next* member of Clusters A–E for free.

Two corroborating instances:
- `agent/utils/proposer_preflight.py:169-174` asserts in-source *"This entry
  point is NOT production-live"*. **False** at both `c991d6f6` and `d2095f6c`
  — `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:48,248` calls it.
- `tests/unit/execute_tools/test_step02a_c5_legality_dedup.py:87-91` asserts
  `agent/schemas/proposal.py` contains `"valid_segmentation_sizes()"`, docstring
  *"were already correct"* — **actively certifying B3**. It names a SYMBOL, so
  it cannot see *which dataset* is consulted.

---

## H. The routing decision that keeps this unit bounded

12d's `D-12d-52` rows **A2/A3** record that the planner prompt and
`check_config_format_skill` inject TIDMAD science into **every** planner prompt,
composed included. This session found the same shape in the proposer
(`ml_model_proposal_agent.py:51,1653` → TIDMAD's divisor list and
*"16384 is INVALID / 16000 is the nearest valid neighbour"*).

**These are not C12-P's**, on a standing rule rather than a preference: an
LLM-facing prompt change requires **Gate 1**
(`docs/gates/gate_testing_standard.md`, *"New LLM-facing system prompt → Gate 1"*),
and a PR split point is a Gate boundary.

```text
C12-P    non-LLM-facing admission / preflight / runtime / global-state
         → deterministic evidence only; Gate 1 NOT REQUIRED
C12-P-P  the prompt-contamination unit (12d A2/A3 + the proposer twin)
         → Gate 1 REQUIRED; separate unit
```

B3 sits on the boundary and is split correctly: the **validator** (accepts or
rejects a structure) is C12-P's; the **prompt block** is not.

---

## I. ⛔ THE B5/B6 ATOMIC-LANDING INVARIANT

**This is the hardest constraint in the unit, and it is proven, not asserted.**

### I.1 The masking chain, from source

```text
core/sandbox_executor.py:1582   if sample_set is not None:              ← B6's predicate
core/sandbox_executor.py:1630       cmd.extend(["--runtime_observation_out", rv_sidecar_path])
        │  composed contrast run ⇒ sample_set is None ⇒ flag NEVER emitted
        ▼
   the child is never told where to write ⇒ no sidecar file exists
        ▼
core/sandbox_executor.py:1684   "runtime_verification": _read_runtime_observation_sidecar(...)  → None
        ▼
nodes/…/ml_hyperparameter_tune_agent.py:1488-1490
        _derive_calibration_from_observation(rv_block=final_record["runtime_verification"])   → None
        ▼
nodes/…/runtime.py:1516         if not rv_block: return                 ← B5's write NEVER happens
```

⇒ **B6 is the only thing preventing B5 from firing.**

### I.2 The empirical witness

The live machine-global store corroborates the chain exactly. Independently
counted this session (read-only, stdlib only):

```
~/.siderius/runtime_calibration_v2/observations : 241 records
   task_identity  : {"tidmad_denoise": 145, None: 96}
   data_shape_class: {"psd10000000_seg200_files20": 145, None: 96}
   newest record  : 2026-08-22T19:22:35
```

**PR-12d's composed Pets/DAVIS Gate launches ran on 2026-08-24 and wrote
NOTHING** — two days after the newest record. That is the masking, observed.
(The count also matches `D-12d-52`'s independently recorded "145 of 241".)

### I.3 The invariant

> **If B6 is repaired first, B5 becomes live immediately, and a composed
> foreign task writes `task_identity="tidmad_denoise"` into machine-global
> `~/.siderius/`.**

Therefore:

```text
B5 protections COMPLETE  →  then B6 enablement  →  then joint tests
canonical integration must NEVER expose a state where B6 is fixed and B5 is not
```

- Implementation commits may be semantically ordered, but **B5+B6 are ONE
  atomic landing unit**.
- **Do not run real composed validation on an intermediate B6-only head.**

### I.4 A second ordering trap inside B6 — do NOT hoist the argv block first

Un-gating the `sample_set is not None` block also un-gates **`--train_portion`**,
whose `ExperimentPlan` default is **0.1**, and **both contrast packs REFUSE
`< 1.0` by name**. A naive hoist converts a silent gap into a **100%-reproducible
crash on the first attempt of every composed contrast run.** The pack refusal
must be reconciled **in the same commit**.

Likewise `trial_strategy`/`eval_strategy = "anchors"` is refused by both packs
and is **reachable today, parent-side** — an LLM-triggerable attempt-burner.

### I.5 Structural budgets bind the fix — measured, not assumed

`execute_training` / `execute_inference` carry structural baselines
(`tests/unit/core/test_step12_pr12bc_b0_baselines.py:565-566` on master;
`tests/unit/guardrails/test_step12_pr12d_d0_baselines.py:699-700` on 12d).

**Correction to an earlier reading**: these are **budgeted ceilings, not
freezes**. `test_step12_pr12bc_b0_baselines.py:589-591`:

```python
MAX_BRANCH_GROWTH = 3
MAX_LOC_GROWTH    = 80
MAX_PARAM_GROWTH  = 1
```

and the assertions are `current - baseline <= budget`, per function.

| function | master baseline | 12d baseline | 12d already spent |
|---|---|---|---|
| `execute_training` | `(92, 39, 358, 14)` | `(93, 39, 364, 15)` | +1 branch, +6 LOC, **+1 param** |
| `execute_inference` | `(69, 28, 254, 9)` | `(69, 28, 255, 9)` | +1 LOC |

Consequences for C7:
- a bounded **inline** widening of the five predicates is *feasible* within
  +3 branches per function — it is not structurally forbidden;
- but **`MAX_PARAM_GROWTH = 1`** is the real constraint: threading a
  scope/profile parameter into both spawn functions consumes the entire
  parameter budget, and `execute_training` has already spent its equivalent
  once under 12d;
- each PR re-baselines in its own file, so C12-P is measured against **12d's**
  numbers with a fresh budget — re-measure at the landed head, never assume.

**Extraction remains the preferred shape** (it is what the responsibility rule
asks for, and it leaves the budget unspent for the next change), but the
decision is now an engineering trade-off with measured headroom rather than a
hard prohibition.

---

## J. B5's bounded fix — operator-ruled

**No new generic measurement-identity capability family.** The full future
capability (an arbitrary composed task declares its own calibration identity)
is **outside** this scope and is recorded as debt.

The bounded fail-closed rule:

```text
no applicable declared measurement/calibration identity under the existing
supported contract  ⇒  DO NOT EXPORT calibration state for that task
```

> **absence of a valid calibration identity ≠ silently call it TIDMAD**

- Preserve TIDMAD behaviour where genuinely applicable.
- Never synthesize a foreign task identity just to make the write happen.
- Absence at this write site is **already first-class**: `identity=None` →
  `QuarantinedDerivation` → a physically separate `quarantine/` directory →
  the tuner prints and continues. Nothing breaks.

**Do not gate the *probe* site the same way**: `runtime.py:677-716` turns an
unavailable capability into `admission="not_admitted"` and `return "skip"` for
a formal scientific round, so making the capability merely "absent" would
**refuse every composed formal scientific attempt**. Write site and probe site
need different dispositions — see Q-C12P-1.

---

## K. The applicability idiom — binding

**The mechanism exists and is PR-12d's.** `execute_tools/dataset_config.py:824-839`
@ 12d:

```python
def declares_tidmad_topology(profile: DatasetProfile) -> bool:
    return all(s in profile.topology for s in ("dataset", "channels", "encoding"))
```

Its docstring states the rule **binding on C12-P**:

> *"The MEMBERSHIP question that must be asked before `tidmad_topology`, never
> inferred from catching its `ValueError` — that function raises for two
> different reasons, and conflating them would silently accept a MALFORMED
> TIDMAD topology as 'this task simply declares none.'"*

Applied by 12d at **seven** production sites. ⇒ **C12-P applies a landed
predicate at the remaining ungated sites. It invents nothing.**

### K.1 The canonical NOT-APPLICABLE template, already in production
`nodes/…/runtime.py:235-305` @ 12d (its B12 fix):

```text
decide applicability BEFORE spawning / before opening any artifact
  → print "NOT APPLICABLE … this is an applicability decision, not a failure"
  → return the already-supported measurement-absent outcome
  → never fabricate a TIDMAD input; never suppress a failing APPLICABLE mechanism
  → run_profile is None (Regime A) stays applicable ⇒ TIDMAD bit-identical
```

### K.2 Two idioms that must NOT be copied — operator §11
1. **`try: tidmad_topology(...) except ValueError:`** — live at
   `agent/skills/evaluate_time_skill/wrapper.py:383-387` and
   `workflows/model_exploration.py:1607-1614`. It silently reclassifies a
   **malformed** TIDMAD profile as foreign. Convert the ones inside the touched
   subsystem; **do not start a repo-wide cleanup**.
2. **A caller-side predicate replicated per call site.** B4 has **six**
   reachabilities and three hold no profile object at all. **The predicate has
   one owner; the response legitimately differs per caller.**

---

## L. Write set and PR-12d overlap classification

PR-12d head `d2095f6c`; 48 production files changed. Classification per
operator §14.

### L.0 ⚠️ Branch from landed 12d, not master
Two reasons: **(a)** B1/B2 are latent on master and armed by 12d (E10); **(b)**
the applicability predicate C12-P consumes is introduced by 12d in
`execute_tools/dataset_config.py`, which **is** in 12d's write set — so a
master-targeting fix would either conflict or create a second authority for the
section names.

### L.1 DISJOINT_FROM_ACTIVE_12D — speculative production edits authorized now

```
agent/schemas/proposal.py                      B3
agent/skills/evaluate_time_skill/**            B1, K.2 anti-pattern
agent/skills/inference_skill/estimator.py      B1      (wrapper.py OVERLAPS — estimator.py does not)
agent/skills/training_skill/estimator.py       B1, B11 (resolve_model_field's home)
execute_tools/workload_resolvers.py            B1
execute_tools/data_paths.py                    B5
core/runtime_control/**                        B4, B5, B11
agent/utils/proposer_preflight.py              B1 sibling
nodes/ml_model_implementor/**                  B11
```

### L.2 OVERLAPS_ACTIVE_12D — falsifiers + design now, production hunk DEFERRED

```
core/sandbox_executor.py                       B6   (the five predicates)
execute_tools/inference_single.py              B6   (12d AUTHORED the composed route)
execute_tools/generic_inference.py             B6   (new file, 12d's)
nodes/ml_hyperparameter_tune_agent/runtime.py  B5 write site, B7
nodes/ml_hyperparameter_tune_agent/execution.py B1 gate
nodes/ml_hyperparameter_tune_agent/planning.py B11  (12d rewrote ~40 lines above :447)
agent/skills/evaluate_vram_skill/wrapper.py    B2
execute_tools/dataset_config.py                the predicate — CONSUME, never edit
```

### L.3 The predicate dependency — an honest constraint
Several hunks sit in a **disjoint FILE** but consume the **12d-introduced
predicate**. Those cannot land before 12d without either duplicating the
authority or inlining the section names. **They are classified DEFERRED
regardless of file disjointness**, and this is called out because file-level
disjointness alone would have given a falsely permissive answer.

---

## M. Semantic commit DAG

Operator-specified order (§13). Semantic order ≠ wall-clock order; disjoint
streams develop concurrently in isolated worktrees.

```text
C1  B7 + B11          cheap, independent of the B5/B6 coupling      [stream W1]
      ↓
C2  B2                earliest candidate-denial gate                [stream W3-B]
      ↓
C3  B1 + ALL confirmed masked sibling sites, ONE authority rule     [stream W3-A]
      ↓
C4  B3 / applicable profile resolution                              [stream W2]
      ↓
C5  B4 + B5 lane-1 protection
      ↓
C6  B5 lane-2 / remaining calibration protection
      ↓            ⛔ B5 COMPLETE BEFORE B6 — §I
C7  B6 task-neutral runtime boundary repair
      ↓
C8  B8 latent-risk sentinel + debt note (NO production fix)
      ↓
    one authoritative exact-head CI  →  operator review  →  DO NOT MERGE
```

**Invariants**: B5 protection before B6; **B5+B6 in the same canonical
landing**; B4 closed before final B6 enablement, with the **B1/B4 chain tested
together** (B1 currently masks B4, so a B1-only repair is not an adequate
production state).

---

## N. Falsifier matrix

Operator §15. **No real GPU Gate is needed for any of these mechanical
properties.** Every test states which defect it alone catches and how it fails
on regression; expectations are hardcoded, never read back from the thing under
test.

| # | property | witness | why it is RED today |
|---|---|---|---|
| N1 | B3 skipped for a task with no physical geometry | **Pets, `segmentation_size=144`** — operator-mandated; DAVIS's 128 passes by coincidence and would be green against a broken fix | `ValidationError … must exactly divide psd_segment_length (10000000). Remainder: 64` |
| N2 | B3 Regime-A parity | nothing bound + a TIDMAD-illegal value ⇒ still raises, byte-identical diagnostic | catches "fixed by deleting the rule" |
| N3 | malformed-but-present TIDMAD topology stays **LOUD** | present-but-invalid sections ⇒ still raises | catches an `except ValueError` implementation (K.2) |
| N4 | B1 full sibling-site census | one census over the whole confirmed family + its shared authority | catches "the defect moved 50 lines downstream" |
| N5 | B2 four cases | key present · key absent · foreign composed task · applicable TIDMAD | `feasible=False` + `binding_cap="compute_intensity"` at `bs=32` |
| N6 | B2 loud failure preserved for a genuinely invalid **applicable** config | TIDMAD over-cap ⇒ still refuses | catches "fixed by suppressing the gate" |
| N7 | B4 every reachability consults the predicate | AST census over all six routes + a pinned manifest | 6/6 RED on master; 5/6 RED on 12d |
| N8 | B4 not-applicable ≠ `probe_status="load_failure"` | assert the disposition, never an exception type (E2) | today: `load_failure` / `ABORT` |
| N9 | B5 no `tidmad_denoise` record for a composed foreign task | `SIDERIUS_CALIBRATION_DIR` redirected — **never delete real state** | today every derived record carries it |
| N10 | B5 genuine TIDMAD calibration still valid | TIDMAD run under the same redirect | catches "fixed by disabling calibration" |
| N11 | B5 task separation is structural | two records identical on all 7 `bucket_components`, differing task ⇒ different bucket | `task_identity` is **not** in the bucket key |
| N12 | B6 foreign task **with `--runtime_watchdog` configured** produces runtime evidence | sidecar exists; `components` carry prediction + actual | flag accepted, enforcement absent, exit 0 |
| N13 | B6 the five predicates never test `sample_set` alone | structural guard over `core/sandbox_executor.py` | 5/5 RED |
| N14 | B7 guardrail actually fires | composed fixture, `max_steps_per_attempt=1` ⇒ `status=="skipped_time_risk"`, `verification_stage=="guardrail"` | silent early return ⇒ no record at all |
| N15 | B11 census, file set **including** `nodes/`, `core/runtime_control/`, `agent/skills/`, `agent/schemas/` | plus a non-vacuity plant | a census omitting the defect's directory is self-evidencing |
| N16 | B11 no framework-authored value in `task_parameters` | plan without `segmentation_size` ⇒ TIDMAD's own named `ValueError`, not a silent `10000` | the framework guesses on TIDMAD's behalf one layer above the code that refuses to guess |
| N17 | **B8 remains unreachable under today's transport contract** | sentinel — must fail or demand reconsideration when a future change (the recorded D3 transported-scope follow-up) makes the path reachable | operator §10: document the assumption, create no dead production code |

Existing tests that **assert the defect** and must be **UPGRADED, never
deleted** (they encode genuine properties): `test_step02a_c5_legality_dedup.py:87-91`
(certifies B3 as correct), `tests/unit/core/test_measurement_capability_reachability.py:57-69,96-104`
and `test_pr07c_capability_routing.py:95-96,110` (pin the V20 C-C3b routing that
generic code must not choose a dataset).

---

## N.1 Stream W3 results — B1's family is SEVEN sites, not four

Branch `c12p-w3-b1b2`, 3 commits, clean tree, nothing pushed. Falsifiers:
**7 failed / 5 passed** (`PYTEST_RC=1`, read from the log), ruff clean.

**The confirmed family.** Every site resolves step counts through ONE authority
chain — `workload_resolvers.py:56 _validate_seg` → `tidmad_topology(profile)` →
fail-closed at `dataset_config.py:839`.

| # | site | trigger | inside a handler? | failure mode |
|---|---|---|---|---|
| 1 | `evaluate_time_skill/wrapper.py:770` | any non-null time budget | yes | `status="error"` → tuner `raise RuntimeError` |
| 2 | `wrapper.py:818` | same | yes | same — **masked by #1** |
| 3 | `wrapper.py:830` → `inference_skill/estimator.py:215` | same | yes | same — **masked by #1** |
| 4 | `wrapper.py:1009` | over-budget projection only | **NO — outside the handler** | **raw `ValueError` escapes `run_skill`**, past the tuner's `status=="error"` branch, as an unhandled crash |
| 5 | **`execute_tools/sample_set_builder.py:118`** | non-null proposal budget | no | raw `ValueError` — **the proposer's ACTUAL first raise** |
| 6 | `proposer_preflight.py:175` → both estimators | same | no | raw `ValueError` — **masked by #5** |
| 7 | `execute_tools/inference_single.py:643` | `runtime_session is not None` | — | same family, inference child. **In 12d's write set — flagged, not touched** |

**Correction to this design's own brief**: site 5 was not listed. The
production caller passes no `sample_set`, so `build_sample_set` raises before
either estimator is reached. `sample_set_builder.py` is **disjoint** from 12d's
write set.

**Verified by AST**: `run_skill`'s `try:` opens at ~`:711` and its
`except Exception` closes at ~`:842`; `:1009` is past it. The falsifier reports
`unguarded == [1009]`.

**Shared semantic authority**: `declares_tidmad_topology(profile)` — one rule
(*the wall-time pre-flight family is TIDMAD-topology-only; every entry point
asks the predicate and refuses BY NAME*), not seven exceptions.

### N.1a The anti-pattern — a distinguishing rule, and two sites that stay

Only **one** of the three candidate sites is the forbidden shape:

| site | catches | claims | verdict |
|---|---|---|---|
| `wrapper.py:383-387` | *only* `tidmad_topology`'s `ValueError` | a **membership conclusion** (*"SKIPPED — this is not TIDMAD"*) | **anti-pattern — CONVERT** |
| `wrapper.py:563-566` | `Exception` (store I/O, torch) | *"check failed, warming up"* — degrades to doing MORE work | different contract — leave |
| `runtime.py:941-943` | `Exception` (resolver, config) | *"(non-fatal)"* best-effort | same shape, different contract — leave (and it is 12d's file) |

> **The rule: claiming a MEMBERSHIP conclusion from a caught exception is
> forbidden; claiming "unknown failure, degrade conservatively" is not.**

Bounded to this subsystem. No repo-wide exception sweep started.

### N.1b Correction to a constraining claim this design made
This design asserted *"no Protocol, no ABC, zero registration sites."* The
Protocol and registration claims hold. **The ABC claim was wrong**:
`core/runtime_control/verifier.py:38 RuntimePhaseVerifier` is an ABC with an
abstract `resolve_workload()`, exported from `core/runtime_control/__init__.py`.
It has **zero production subclasses** and is unrelated to pre-flight — dead
scaffolding. The conclusion (workload is unobtainable for a non-TIDMAD task, so
propagation would be a new capability family and therefore a STOP) **stands
unchanged**; a future audit grepping for an ABC will find this one.

### N.1c B2 trigger frequency — measured, not launched (operator §7)
17,101 files parsed across `/home/klz/Data/SIDEREIS_DATA/` (127 run dirs),
`siderius_workspace/`, `reports/`, `.gate_artifacts/` and all 476 `.log` files.
`plan_*.json` does not exist as a family; the record-bearing artifacts are
`run_output_*.json` and `records/<run>/<exp_id>.json`, whose
`record.params.model_config` **is** the raw planner dict.

Deduplicated planner population **N = 1,844**:

| | `batch_size < 21` | `batch_size ≥ 21` |
|---|---|---|
| `segmentation_size` present | 1,764 | 73 |
| `segmentation_size` **ABSENT** | 6 | **0** |

**The joint trigger has occurred ZERO times** in every population (raw planner
0/5,500 · post-validation 0/1,032 · proposer 0/339). Of 7 omissions only one is
substantive. **N = 1 substantive omissions — no rate is extrapolated from that.**

Two facts that keep B2 live anyway, and matter more than the rate: the
**proposer** omits the key **58/339 = 17 %** of the time and its
`baseline_config` seeds the tuner; and persisted **Pets** plans show **5 of 7
batch sizes already ≥ 21**. The joint is rare because composed contrast runs are
new, not because the shapes are incompatible — and 12d's F-12d-24 removes the
crash that masked it.

## N.2 Stream W2 results — B3 closed, with one declared deviation

Branch `c12p-w2-b3`, 3 commits, clean tree, nothing pushed. Every anchor in the
brief verified correct; nothing in it was wrong.

**The fix** (`agent/schemas/proposal.py`): the module-scope
`TIDMAD as DATASET_CONFIG` import is **removed** — it had exactly one consumer
and no re-export consumers. The validator now resolves the applicable profile
at validation time and gates the divisibility half on the membership predicate:

```python
profile = resolve_dataset_profile()
if not declares_tidmad_topology(profile):
    return self
dataset = tidmad_topology(profile).dataset
psd = dataset.psd_segment_length
```

The **generic positive-int check stays outside the gate** (it is task-neutral).
No task-name branching. Regime-A parity is proven *at the source*, not merely by
message match: `TIDMAD == tidmad_topology(resolve_dataset_profile()).dataset` by
value, by `model_dump()`, and by `valid_segmentation_sizes()`.

### N.2a ⚠️ DECLARED DEVIATION — an edit in the DEFERRED zone

`execute_tools/dataset_config.py` **is in PR-12d's write set**, so §L classifies
it DEFERRED. W2 edited it anyway, adding `declares_tidmad_topology`, and stated
why:

- literal option (a) — importing a function that does not exist on master —
  makes the hunk dead code and makes the operator-**mandated** anti-vacuity
  witness **unrunnable**, so red→green could not have been demonstrated;
- literal option (b) — inlining the three section names in `agent/schemas/proposal.py`
  — creates the forbidden second authority in a module with no business owning them.

**Mitigation, verified by the integration owner**: the added function is
**byte-identical** to PR-12d's (`ast.get_source_segment` comparison against
`dd369f3b` returns equal). So reconciliation is a merge conflict whose
resolution is *"keep either"*, and a bad auto-merge yields a duplicate `def`
that **ruff F811** catches.

**This is the operator's call.** Reverting is deleting one commit; the
`proposal.py` hunk is unchanged either way.

### N.2b Falsifiers — the non-vacuity split is the evidence
`tests/unit/agent/ml_model_proposal_agent/test_c12p_b3_segmentation_applicability.py`,
9 cases, all driven through the production `ProposalOutput` constructor, all
expectations hardcoded. Against **pre-fix** source: **4 failed / 5 passed** —
and the split is the point. The 4 reds are the defect rows; the 5 greens are
parity and negative-control rows that **must** be green in both states.

| case | pre-fix |
|---|---|
| **Pets 144 under a geometry-less profile ⇒ ACCEPTED** (the mandated witness) | RED |
| Pets 16384 ⇒ ACCEPTED — the skip is total, not a widened divisor list | RED |
| malformed-but-present TIDMAD topology + 16384 ⇒ RAISES | RED |
| malformed topology + **16000** ⇒ RAISES — blocks a lazily-decoding fix that would make corruption visibility depend on the LLM's hyperparameter choice | RED |
| Regime A ×2 (unbound / TIDMAD-bound) + 16384 ⇒ raises, `Remainder: 5760` + divisor list | green |
| TIDMAD 16000 still passes | green |
| generic positive-int rule stays unguarded (`-100`, `0`, `"16000"`) | green |
| **DAVIS 128 — NEGATIVE CONTROL**, asserting `10**7 % 128 == 0`, docstring stating it can never discriminate the defect | green |

The malformed-topology rows are the *sole* reason applicability cannot be an
`except` clause — **every other case in the file passes under an
`except`-based implementation.**

### N.2c Test disposition
`test_step02a_c5_legality_dedup.py` — **UPGRADE, not delete.** Its assertion
encodes a genuine property (neither site may re-inline the divisor range) and is
kept; its docstring, which certified the site as *"already correct"*, is
corrected to state the half it is structurally blind to. A **new sibling** test
guards that blind half: `proposal.py` may not name `DATASET_CONFIG`, and must
call `resolve_dataset_profile` + `declares_tidmad_topology`.
`test_baseline_config_validators.py` (10 cases) and
`test_pipeline_runner.py::TestSegmentationSizeRetryIntegration` — **KEEP
unchanged**: every case runs in Regime A, which the fix leaves byte-identical,
and they are the load-bearing evidence that the rule was not deleted.

### N.2d Checks
ruff `check` and `format --check` clean on all four changed files. Targeted
pytest **1240 passed, rc=0**, read from the log file.
**pyright NOT run** — it cannot execute in this environment (Node v10.19.0;
the vendored bundle raises `SyntaxError`). Recorded as a limitation rather than
claimed; **CI is the only environment that can run it.** A directory-wide run
was *abandoned, not failed*, because three parallel streams were starving each
other; the targeted run covers every file the change touches.

### N.2e The prompt-layer twin — analysis only, correctly out of scope
`ml_model_proposal_agent.py:51` → `:1653`
`_format_known_constraints_block(DATASET_CONFIG)` fills
`{known_constraints_block}` at `agent/prompt_templates/proposal/proposing_stage.md:108`,
emitting TIDMAD's `psd_segment_length (10,000,000)`, *"Powers of 2 such as
16384, 8192, 4096 are INVALID"* and the 16000-neighbour advice into **every**
composed run's proposing prompt.

The minimal fix is **call-site only** — the renderer already declares
`dataset_config=None → ""` as its backward-compat contract, so a local helper
returning `tidmad_topology(profile).dataset` when applicable and `None`
otherwise gives byte-identical Regime-A prompts and an empty block for a
geometry-less task.

**Why it stays a separate Gate-1 unit**: it removes an entire
`## SYSTEM-ENFORCED DATASET CONSTRAINTS` section from a contrast task's prompt.
Whether the model still authors a legal `baseline_config` without it — or
whether the task needs its *own* declared constraints in its place — is a
question no byte assertion can answer.

## N.3 Stream W1 results — B7 + B11, and a pairing invariant that nearly bit

Branch `c12p-w1-b7b11`, 3 commits, clean tree, nothing pushed.

### N.3a The near-miss worth reading first
The "obvious" B11 fix — route `gpu_measurement_identity.py:214` through
`resolve_model_field` — **would have been a regression.**
`build_planned_identity`'s own docstring (`gpu_measurement_identity.py:203-209`)
declares a pairing invariant, verified verbatim:

> *"The defaults for `seg_size` and `batch_size` are **the same ones the
> measurement worker will apply**, so the two sides cannot disagree because one
> of them filled a blank differently."*

The worker side is `gpu_measurement_worker_main.py:272`
(`...get("segmentation_size", 40_000)`) — **a site the brief did not list.**
Fixing the parent alone makes it resolve the config-class default (the
transformer declares `20000`) while the worker still fills `40000`, so the
identity the parent pins stops describing what the worker measured. W1 fixed
the **triad** together. *A single-site fix inside a declared pairing invariant
is a regression wearing a cleanup's clothes.*

### N.3b Census — five sites beyond the brief

| site | value | disposition |
|---|---|---|
| `planning.py:380` · `planning.py:447` | `10000` | confirmed, **DEFERRED** (12d overlap) |
| `probe_production.py:234` | `40_000` | **FIXED** |
| `gpu_measurement_identity.py:214` | `40_000`, hashed into `config_hash12` | **FIXED** |
| **`gpu_measurement_worker_main.py:272`** | `40_000` | **FIXED — pairing-critical, §N.3a** |
| `evaluate_vram_skill/wrapper.py:641` | `40000` | W3's (finding B2) |
| **`runtime.py:737`** | `...get(..., 0)` into the probe request's `workload.segment_length` | **NEW** — durable false provenance on the exact field D4 buckets and C7 applicability ranges key on. DEFERRED (12d) |
| **`bootstrap.py:460`** | same `0` sentinel, for *"the workload the probe ACTUALLY ran"* | **NEW** — recorded, deliberately not folded in: after the probe fix the probe runs at the resolved size while bootstrap still records `0`. **Needs its own decision** |
| **`ml_model_implementor.py:1194, :1418`** | `40000` | **NEW and worse than a fallback** — `:1418` feeds `PLUGIN_TEMPLATE.format(segmentation_size=...)` whose line `:293` is `segmentation_size: int = Field(default={segmentation_size}, ge=1)`, so the literal is **baked into the generated plugin's own declared class default**. Permanent, not transient. **Unowned by any C12-P stream** |

Deliberately excluded as non-offenders: `campaign.py`, `scripts/runtime_bootstrap.py`,
`scripts/runtime_replay`, `estimator.py:243` (explicit declarations, not
fallbacks); `evaluate_time_skill/wrapper.py:361` and `verify_iter005_estimator.py:147`
(subscripts — fail-closed).

### N.3c Falsifiers — RED with output, and green controls that bound the fix
The census test lists all seven remaining offenders by file and line. Its file
set covers `nodes/`, `core/`, `agent/`, `execute_tools/`, `ml_models/`,
`workflows/`, `scripts/`, `tools/`, `dashboard/`, with **two anti-blindness
guards**: every declared root asserted to have actually walked files, and the
four required directories asserted covered **by name**. Non-vacuity is proven
with a planted flat literal **and a planted nested literal** — the implementor's
shape, which a detector reading only the outer default would call clean — plus
five legitimate shapes proven *not* flagged, including `resolve_model_field`
itself.

Green controls matter as much as the reds: `min_formal_batch_size` still fires
(so the B7 fix cannot pass by widening its blast radius), and a **declared**
`segmentation_size=8000` still travels unchanged (which is where
"behaviour-preserving" is actually measured).

### N.3d ⚠️ B7's reachability — a correction, and a STOP candidate
**On landed master a composed non-TIDMAD run cannot reach the guardrail at
all**: `planning.py` calls `tidmad_topology(run_profile)` and `build_sample_set`
unconditionally and dies first, so `train_sample_set is None` means only
*legacy single-file*. **The `None` state B7 describes is created by PR-12d's
planning seam B**, and 12d's `runtime.py` diff touches only
`_handle_prephase_gpu_measurement` — so **B7 is live at the 12d head, not on
master.** W1's falsifiers therefore drive the emitting boundary with the exact
state 12d produces and say so; *an end-to-end composed fixture on master would
have gone red for the wrong reason.*

**B7's fix is not one line.** `AttemptScopes.training` is opaque `Any`, and
`resolve_training_workload` is thoroughly TIDMAD-physical (PSD segments,
`ml_per_psd`). A generic step count needs **either a new declared capability
(a training-sample count on the scope) or an explicit loud refusal** — the same
fork as B1, and the capability branch is a **§S STOP**. The falsifiers are
written fix-shape-agnostic for exactly that reason.

### N.3e Backward compatibility — stated, not claimed away
The three sites W1 fixed are behaviour-preserving whenever the key is present,
which is every production plan. **Dropping the `10000` fallback at
`planning.py:447` is NOT.** Today a legacy TIDMAD run whose plan omits
`segmentation_size` **scopes its data at `10000` while the model trains at the
class default `40000`** — silently, with a plausible number on both sides. That
is a **correction of an existing latent TIDMAD defect**, and no byte-identical
legacy claim is made for it.

Two non-equivalent fix shapes remain open there and the choice is deliberately
not pre-empted: *omit the key* (the task refuses by name; a currently-working
plan starts dying) versus *resolve via `resolve_model_field`* (the scope matches
the model that will be built). W1's primary assertion holds under both; the
refusal test holds only under the first and its docstring flags that it needs
explicit retirement if the second is chosen.

### N.3f Checks
`ruff check` / `ruff format --check` clean on `core/runtime_control/` (54 files).
Targeted regression across 19 files covering every consumer of the three changed
authorities: **551 passed**; tuner node + guardrail suites **48 passed** beside
the intended reds. **pyright not run** — Node v10.19.0, vendored bundle raises
`SyntaxError`. Not claimed; CI must confirm. No full suite (validation economy),
no push, no merge.

---

## O. Validation economy

| class | use |
|---|---|
| deterministic call-path unit test | every Cluster A/B/C item |
| census / plant-and-catch | Cluster F, B4's six reachabilities, B11 |
| subprocess test | the clean-child ambient lookup |
| registry-root-redirected state test | B5 — **never** by deleting real `~/.siderius` state; `SIDERIUS_CALIBRATION_DIR` exists, and `tests/conftest.py:139-176` already isolates the suite |
| composed-fixture integration | B6's end-to-end evidence property |
| **Gate 1** | **NOT REQUIRED** — the one item that would have required it is routed out (§H) |
| **Gate 2** | **NOT REQUIRED for the mechanical properties** (operator §15). See Q-C12P-5 |

**Evidence reuse**: `D-12d-52` is cited as prior art, not re-derived. 12d's B12
applicability tests are the template, not a thing to duplicate.

---

## P. Open operator questions

### Q-C12P-1 — What does "not applicable" MEAN on the admission path? *(blocks C3/C5/C7)*
Two production sites already **disagree**:

| site | not-applicable behaviour |
|---|---|
| `runtime.py:295` (12d's B12) | `PrephaseOutcome.PROCEED` — measurement optional, admission continues |
| `runtime.py:689-709` (capability unavailable, scientific ∧ formal) | `admission="not_admitted"`, `feasible=False`, **`return "skip"`** — attempt refused, and `is_evidence_refusal` blocks the formal time-budget bypass |

Routing B4 into the existing "unavailable" lane would **refuse every composed
formal scientific round**. 12d's census already recorded the downstream witness:
*"`--gpu_admission_enforcement enforce` would refuse a composed formal round"*.

The distinction the fix must encode — Step 08a's `CheckVerdict`
(`PASSED`/`FAILED`/`INAPPLICABLE`/`ERROR`, where *"INAPPLICABLE … never counts
as a pass"*) is the in-repo precedent:

```text
NOT_APPLICABLE  this task has no such measurement concept    → proceed, recorded
NOT_AVAILABLE   this task COULD be measured, environment can't → today's refusal
FAILED          an applicable mechanism ran and failed       → stays loud
INVALID         the declaration itself is malformed          → stays loud
```

**Question:** may a composed non-TIDMAD **formal, scientific-authority** round
proceed with **no** measured runtime evidence — and must that be recorded as a
first-class run property rather than an absence?
*Recommendation: yes, proceed AND record. Otherwise C12-P trades a loud wrong
failure for a silent gap.*

### Q-C12P-2 — Who owns B6's `inference_single` hunk?
The composed-route line is code **PR-12d wrote in this branch**, in a file and
function 12d newly owns, and 12d dispositioned it *"DEBT … unfixed by design"*.
The operator's own principle (*"a finding's discoverer is not automatically its
owner, and neither is the nearest open PR"*) cuts both ways.
**Question:** 12d completion item, or C12-P's? (B7 rides with it — same
`D-12d-52` row.)

### Q-C12P-3 — Confirm the prompt-contamination split (§H)
*Recommendation: confirm.* Keeping it out is what keeps C12-P Gate-1-free.

### Q-C12P-4 — B5 remediation of EXISTING records
The write is a defect regardless. What changes is whether **remediation of the
241 existing records** is also required.

Confirmed: the contaminated fields (`task_identity`, `data_shape_class`) are
**not in the bucket key at all** — the key is 7 components and task is not one
of them; the read path (`as_estimate`) has **zero production callers**; but
`collect_calibration_state` aggregates the **whole store** with no task filter
and feeds the operator's calibration report.

**Correction, measured directly by the integration owner** (an earlier draft of
this section repeated a "38 of 86 buckets hold divergent identities" figure that
overstates the case):

```
buckets total                                : 86
buckets holding >1 distinct MeasurementIdentity : 38   ← mostly candidate_config_hash,
                                                        which the key EXCLUDES BY DESIGN
                                                        so one bucket aggregates candidates
buckets mixing task_identity incl. None      : 14   ← probe records (identity=None)
                                                        pooled with identified ones
buckets mixing two or more NON-NULL task ids :  0
distinct non-null task ids in the whole store: ['tidmad_denoise']
```

⇒ **No cross-task contamination exists today and none can be demonstrated from
the live store.** The honest statement is: the mechanism is armed, the key
cannot separate tasks, and 14 buckets already pool identified with unidentified
records — but the 38 figure is not evidence of task mixing and must not be
quoted as such.

**Question:** does C12-P also remediate/quarantine existing records, or only
stop the write? *Recommendation: only stop the write.* Remediation has no
demonstrated corruption to repair, and deleting or rewriting an append-only
evidence corpus is a larger and riskier act than the defect currently warrants.

### Q-C12P-6 — Where does the not-applicable DECISION live? *(raised by stream W3)*

W3's falsifiers commit to `run_skill` returning `status="not_applicable"` with
**no `feasible` key** — fabricating a feasibility verdict for a task whose
workload cannot be priced is exactly the honesty failure Step 08a corrected.

That requires the tuner to grow an explicit branch. Today
`execution.py:~434` raises only on `status == "error"`, and
`time_check.get("feasible", True)` at `:490` would let an unrecognised status
fall through as **feasible by default**. **That fall-through works by accident,
not by contract**, and W3 deliberately did not build on it.

Two shapes, same authority, different split:

| shape | where the decision lives | cost |
|---|---|---|
| **A — skill-side** (what W3's falsifiers assume) | the skill returns `not_applicable`; the tuner gains a branch | touches `execution.py`, which **overlaps 12d** |
| **B — caller-side** (12d's B12 precedent) | the tuner asks `declares_tidmad_topology` and never invokes the skill | matches the landed template exactly; the skill stays untouched |

**Question:** A or B? *Recommendation: B* — it reuses the precedent the
operator already ratified for the sibling probe, keeps the refusal before the
work rather than after it, and avoids relying on a default that holds by
accident.

### Q-C12P-5 — Any real Gate at all?
§O says the mechanical properties need none. The only property no deterministic
test establishes is that a **real** composed contrast run launched **with** a
wall-time budget completes end to end — the configuration `D-12d-52` currently
forbids by name. **Question:** one bounded post-12d Pets Gate 2, or deterministic
evidence only? ⚠️ Either way, a real launch needs **scoped operator
authorization at launch time** — the `require_launch_approval` hook blocks all
launches regardless of any frozen approval in a design document.

---

## Q. Found, confirmed, deliberately NOT taken

| finding | why not C12-P |
|---|---|
| 12d census **A1** — HealthGate evaluation lives only inside the `ANCHOR_NORMALIZED` branch ⇒ a composed run fires **ZERO** gates | Health authority, not admission. Silent and serious; needs its own owner |
| 12d census **A2/A3** + the proposer prompt twin | LLM-facing ⇒ Gate 1 ⇒ separate unit (§H) |
| `resolved_action` **dead** since the C7 decomposition — `SKIP_ITER`/`SKIP_TO_FORMAL` inert on **all** routes, TIDMAD included | not TIDMAD-specific; carries a standing "operator decision required" note from the Step-07b ledger |
| `agent_generated/{losses,models,_capability_index.json}` — checkout-global, name-keyed, **no task column**, promoted regardless of training outcome, and it feeds LLM prompts | a second HIGH global-state cluster, outside admission/preflight. Record and route separately |
| `_CACHED_GATES` (`execute_tools/health_checks/config.py:355`) — an unkeyed process-wide cache of the TIDMAD-composed health roster | Health authority |
| composed runs get **non-reproducible per-epoch subsampling** (`--train_base_seed` dropped ⇒ `hash(exp_id)`, `PYTHONHASHSEED`-randomized) | rides with B6's argv reconciliation; flag explicitly so it is not lost |
| `trial_strategy="anchors"` — refused by both packs, **reachable today**, burns an attempt | plan-normalization concern; record for the owning unit |
| `resolve_scoring_workload` has **no production caller** | operator §12 — record as dead capability, claim nothing |
| `sandbox_executor.py:1185-1187` collapses "declared absence" and "use the default" | `DeliverableNaming`'s authority; bounded and currently harmless |
| `Q-07c-6` — admission prices `phase="training"` only | open since Step 07c |
| Option A — making TIDMAD-physical mechanisms task-composable | post-Step-12 debt, recorded by 12d |

---

## R. PR-12d landing reconciliation — REQUIRED before freeze

1. fetch; record `LANDED_PR12D_SHA` (**the head moves** — it went `dd369f3b` →
   `d2095f6c` during this session alone);
2. re-run every falsifier against landed source;
3. mark each item `RESOLVED_BY_12D` / `STILL_REQUIRED` / `CHANGED_NONMATERIALLY`
   / `MATERIAL_ASSUMPTION_CHANGE`;
4. drop resolved items — **do not preserve work merely because it was done**;
5. rebase every stream onto landed 12d (§L.0);
6. **STOP for operator review** if 12d materially changed
   `declares_tidmad_topology`, `scope_acquisition.project_attempt_topology_facts`,
   or the composed inference route.

### R.1 12d is NOT close to landing — plan for it
Two operator decisions gate its acceptance: `D-12d-49` (Track-1 corrective
sequencing; the fix lives on `fix/run-baseline-datascope-parity` @ `c1c6e511`
and the cherry-pick was blocked by the commit-approval hook) and `D-12d-54`
(whether steering DAVIS's objective via `--human_advice` is configuration or
forbidden Gate-only science). Launch budgets on both contrast tracks are at or
near exhaustion. **Assume 12d does not land soon.**

---

## S. STOP conditions

- a **new capability family** would be required (§K says none is — if that
  proves wrong it is a STOP, not a design choice);
- task-name dispatch, a task catalog or a topology catalog becomes necessary;
- closing an item would require making a TIDMAD-physical mechanism
  task-composable (Option A / post-Step-12 debt);
- applicability cannot be distinguished from degraded validation at a site;
- 12d's landing materially changes the consumed authorities (§R item 6);
- the work would touch an LLM-facing prompt (⇒ wrong unit, §H);
- **any state where B6 is fixed and B5 is not** would become reachable (§I).

**Merge is never performed by this unit.**

---

## T. Ledger

- [x] forensic confirmation of B1–B8/B11 (six read-only agents, every
      load-bearing claim re-verified by the integration owner)
- [x] operator ruling received and encoded (2026-08-24)
- [x] B5/B6 masking chain proven from source **and** corroborated by the live
      store's timestamps (§I)
- [x] PR-12d write set refreshed at `d2095f6c`; overlap classified (§L)
- [x] isolated worktrees created for streams W1/W2/W3
- [x] **C8 — B8 latent-risk sentinel** (`tests/unit/core/test_c12p_b8_latent_reachability_sentinel.py`,
      commit `0fcff456`). Two paired tests: the transport gate is pinned so a
      cluster-B-prime hoist turns it RED naming the fix; the consumer hazard is
      pinned so a future safe cast demands RETIREMENT rather than passing while
      guarding nothing. **Mutation-proven** — hoisting the emission out of the
      gate gives `1 failed / 3 passed`; tree reverted and verified
      byte-identical; baseline re-run green (4 passed). ruff check + ruff
      format --check clean. **No production source touched.**
- [x] **W1 — B7 falsifiers + B11 census and disjoint fix** (branch `c12p-w1-b7b11`, 3 commits). Census found FIVE sites beyond the brief, one of them pairing-critical (§N.3a). Three disjoint sites fixed through `resolve_model_field`; 551 + 48 passed targeted, ruff clean, pyright unrunnable locally. Falsifiers RED with output plus two green controls. **B7 reachability corrected: live at the 12d head, NOT on master; and its fix may need a new capability — STOP candidate (§N.3d).**
- [x] **W2 — B3 fix + Pets/144 anti-vacuity witness** (branch `c12p-w2-b3`, 3 commits). Fix is the operator-approved shape; falsifiers 4 failed / 5 passed pre-fix with the correct non-vacuity split (§N.2b). ruff clean, 1240 passed rc=0; pyright unrunnable locally (Node v10.19.0) and recorded as such. **DECLARED DEVIATION**: an edit in the DEFERRED zone (`execute_tools/dataset_config.py`), byte-identical to 12d's — operator call, §N.2a.
- [x] **W3 — B1 sibling-site family + B2 frequency evidence** (branch `c12p-w3-b1b2`, 3 commits). Family is SEVEN sites, not four (§N.1); `:1009` is outside the handler; the proposer's first raise is `sample_set_builder.py:118`. Falsifiers 7 failed / 5 passed, proven RED with output. B2 joint trigger measured ZERO across 1,844 planner configs (§N.1c). One comment-only hunk landed (`091accc9`); all other hunks DEFERRED on the 12d predicate. Raised Q-C12P-6.
- [x] **integration check** — 18 commits across 4 local branches, every tree
      clean, **nothing pushed** (`git ls-remote --heads origin 'c12p*'` = 0),
      nothing merged. **Six production files touched in total**, five of them
      in the DISJOINT zone; the sixth is W2's declared deviation (§N.2a).
- [ ] operator answers to `Q-C12P-1` … `Q-C12P-6`
- [ ] landed-12d reconciliation (§R)
- [ ] design FROZEN
- [ ] C5/C6/C7 — the B5+B6 atomic unit
- [ ] C8 — B8 sentinel
- [ ] node/skill `.md` doc sync
- [ ] ONE authoritative exact-head CI
- [ ] READY FOR OPERATOR REVIEW — DO NOT MERGE

---

## U. Terminal status

```text
C12-P DESIGN/FALSIFIERS COMPLETE
SPECULATIVE IMPLEMENTATION COMPLETE WHERE DISJOINT
WAITING FOR LANDED PR-12d RECONCILIATION
DO NOT MERGE
```

**Total production write set across all streams — six files:**

| file | stream | zone |
|---|---|---|
| `core/runtime_control/probe_production.py` | W1 | DISJOINT |
| `core/runtime_control/gpu_measurement_identity.py` | W1 | DISJOINT |
| `core/runtime_control/gpu_measurement_worker_main.py` | W1 | DISJOINT |
| `agent/schemas/proposal.py` | W2 | DISJOINT |
| `agent/utils/proposer_preflight.py` | W3 | DISJOINT — **AST-proven execution-inert** |
| `execute_tools/dataset_config.py` | W2 | **OVERLAPS — declared deviation, §N.2a** |

18 commits, four local branches, every tree clean, nothing pushed, nothing
merged.

### U.1 What still blocks canonical implementation

1. **PR-12d must land** — and it is not close (§R.1). Everything in the
   DEFERRED zone waits on it, including all of C5/C6/C7.
2. **Six operator questions** (§P), of which `Q-C12P-1` blocks three commits.
3. **One STOP candidate**: B7's generic step count may require a new declared
   capability (§N.3d) — the same fork as B1, and the capability branch is a §S
   STOP rather than a design choice.
4. **pyright is unverified locally** in every stream (Node v10.19.0 cannot
   execute the vendored bundle). CI is the only environment that can check it,
   and no stream claims otherwise.

### U.2 Findings recorded here that no C12-P stream owns

- `ml_model_implementor.py:1194, :1418` — the TIDMAD literal **baked into the
  generated plugin's own declared class default** (permanent, not transient).
- `bootstrap.py:460` — records `segment_length` from a `0` sentinel for *"the
  workload the probe ACTUALLY ran"*; after W1's probe fix the probe runs at the
  resolved size while bootstrap still records `0`. Needs its own decision.
- The prompt-contamination unit `C12-P-P` (§H) — 12d census A2/A3 plus the
  proposer twin, Gate 1 required.
- Everything in §Q.

---

## V. Operator rulings — 2026-08-24 (second ruling, post-consolidated-report)

The consolidated report was ACCEPTED. The forensic phase is closed: **do not
broaden the census further merely because more adjacent literals or structural
differences can be found.**

### V.1 W2 deviation — REVERTED (§1)
**Executed.** `execute_tools/dataset_config.py` restored byte-identical to
`c991d6f6`. Byte-equivalence to PR-12d's predicate did **not** justify a second
semantic authority in a DEFERRED zone, and *the anti-vacuity test does not
justify duplicating the authority.*

Recorded as a **forward commit** (`74dab0a9`), not a history rewrite; `dc0e4000`
and `8bf651ca` remain in the branch history as ordered. **No local copy of the
predicate was substituted.**

**Necessary consequence, decided and reported rather than worked around**: the
ruling named only `dataset_config.py`, but `agent/schemas/proposal.py` imports
and calls the predicate (`:30`, `:1287`) and is not independently viable without
it — leaving it would `ImportError` on every import of the proposal schema. **The
B3 production hunk is therefore also reverted** and moves to the DEFERRED zone
alongside the predicate it consumes.

Falsifiers **preserved** and correctly RED again — `5 failed / 13 passed`, read
from the log. The four B3 defect rows fail exactly as pre-fix, the new sibling
test fails, and the 13 green are the parity and negative-control rows that must
be green in **both** states — which re-confirms the non-vacuity split a second
time. They bind to the canonical landed predicate during reconciliation.

### V.2 `NOT_APPLICABLE` — DEFINED (§2, closes Q-C12P-1)

> **`NOT_APPLICABLE` means explicit semantic non-membership of the current
> resolved task/workload in a subsystem's domain of applicability.**

It does **NOT** mean: a required artifact happens to be absent · `sample_set is
None` · a TIDMAD field lookup raised `ValueError` · a file/path happens not to
exist · a legacy argument was not transported.

```text
semantically OUTSIDE the subsystem              -> NOT_APPLICABLE
semantically INSIDE but malformed/incomplete    -> ERROR / loud refusal
semantically INSIDE and valid                   -> APPLICABLE
```

**A malformed TIDMAD profile must remain loud.** Never silently reclassify
malformed *applicable* input as `NOT_APPLICABLE`. This ratifies §K's membership
rule and retires the `except ValueError` shape at
`evaluate_time_skill/wrapper.py:383-387`.

### V.3 Applicability authority lives CALLER-SIDE (§3, closes Q-C12P-6)

> The layer that already owns the resolved task/workload/profile context makes
> the applicability decision **ONCE** and passes the resolved result downward.

```text
resolved task / composition / workload
    -> explicit applicability / resolved-workload decision
        -> child subsystem consumes it
```

Leaf modules must **not** independently rediscover applicability through
exception catching · artifact presence · `sample_set` presence · task-name
literals · duplicated topology predicates.

**One resolved authority, not a new central task catalog. No task-name
dispatch.** This selects shape **B** of Q-C12P-6 and supersedes W3's
skill-side `status="not_applicable"` assumption — W3's falsifiers were written
fix-shape-agnostic and survive the change; the `execution.py` branch they
implied is no longer needed.

### V.4 B7 — ISOLATED material-stop candidate (§4, §5)

**Do NOT invent a new generic step-count / workload-identity capability inside
C12-P yet.** After 12d lands, run **one bounded source-grounded authority
check**:

> Does the landed generic workload/runtime contract already contain an
> authoritative **task-neutral** value from which B7's required step count can
> be derived **without inventing a second scientific/runtime authority**?

Inspect the existing resolved-training-workload / workload-transport mechanisms
— **but do not assume their sufficiency from names alone.** Then classify:

| verdict | action |
|---|---|
| **A — EXISTING AUTHORITY SUFFICIENT** | wire B7 to it · add anti-vacuity tests · continue inside C12-P |
| **B — NEW GENERIC CAPABILITY REQUIRED** | **MATERIAL STOP for B7 ONLY** · do not invent it · report the exact missing semantic contract |

**A B7 stop does NOT stop B1, B2, B3, B4, B5, B6, B11, the B8 sentinel, or the
landed-source reconciliation of those independent units. Keep the stop local.**

**B7 validation must use LANDED-12d source (§5).** B7 is live at the 12d head
and **not** on master, so a master-only composed fixture is **not** an
authoritative RED baseline — it can fail for the wrong reason. Build the
anti-vacuity witness on landed source, prove the real production call path,
*then* decide sufficiency. **Do not make a pre-12d fixture artificially
reproduce future reachability.**

### V.5 B11 — preserve parent/working identity semantics (§6)

W1's correction is **accepted**: the obvious *"just propagate the parent value"*
repair is **NOT authorized**. `build_planned_identity` already encodes a
parent/working distinction, and the fix must preserve:

> **the identity pinned in planning == the identity the worker actually
> measures / executes**

Do not simplify to *always parent* or *always working* without source-backed
authority.

**Required before B11 is considered closed** — a falsifier that:
1. constructs a case where parent and working values **differ**;
2. proves planned/pinned and worker-observed identity remain semantically
   synchronized;
3. **plants the naive parent-only fix and requires the test to go RED.**

### V.6 B5 + B6 atomicity — UNCHANGED and hard (§7)

The final consumable candidate must **never** expose *B6 enabled + incomplete
B5 protection*. **PR-12e will reject a B6-only intermediate head.** The final
candidate must prove all five:

- a foreign composed task does **not** export TIDMAD-labelled calibration;
- applicable TIDMAD calibration still works;
- lack of a valid measurement/calibration identity **fails closed**;
- **no** new generic measurement-identity capability is claimed;
- B6's task-neutral runtime machinery is no longer gated by `sample_set`
  presence.

### V.7 B8 (§8) and the census (§9)
B8 stays `NOT CURRENTLY REACHABLE / LATENT / REACHABILITY SENTINEL`. The
mutation-proven sentinel is **accepted as the correct evidence shape**; do not
reclassify B8 as fixed.

The "38 of 86" correction is accepted. **No repository-wide remediation of
structural/literal divergence, and no broad cleanup PR.** The census existed to
find concrete semantic authority leaks, not to make modules structurally
uniform. Keep only confirmed production defects and bounded sentinels.

### V.8 Disposition of Q-C12P-2 … Q-C12P-5 (§10)

| # | disposition |
|---|---|
| **Q-C12P-2** — who owns B6's `inference_single` hunk, 12d or C12-P? | **SUPERSEDED / NO OPERATOR RULING REQUIRED.** §7 assigns the proof obligation *"B6's task-neutral runtime machinery is no longer gated by `sample_set` presence"* to the final **C12-P** candidate, which settles ownership. B7 rides with it per the same `D-12d-52` row. |
| **Q-C12P-4** — does C12-P remediate the 241 existing calibration records? | **SUPERSEDED / NO OPERATOR RULING REQUIRED.** §7's enumeration of what the final candidate must prove contains **no** remediation obligation, and §9 forbids broad remediation. Combined with the measured finding that **zero** buckets mix non-null task ids, the answer is: **stop the write, do not remediate.** |
| **Q-C12P-3** — prompt-contamination split | **STILL LOAD-BEARING** — exact text returned with this report. |
| **Q-C12P-5** — any real Gate | **STILL LOAD-BEARING** — exact text returned with this report. |

---

## W. Operator rulings — 2026-08-24 (third: Q-C12P-3 and Q-C12P-5 resolved)

The W2 revert is **accepted**, and so is the consequent reversion of the
dependent `proposal.py` B3 hunk: *once the canonical predicate is deferred to
landed PR-12d, keeping a consumer that imports the removed local authority
would be an invalid split state.* **Do not recreate a local predicate.**

```text
C12-P CORE
SPECULATIVE DISJOINT WORK COMPLETE
DEFERRED OVERLAPS REMOVED
WAITING FOR LANDED PR-12d
DO NOT MERGE
```

### W.1 Q-C12P-3 — RULED: SPLIT (closes the question)

The LLM-facing prompt contamination becomes a separate **child unit**:

> **`C12-P-P` — Composed Prompt Contamination Closure**

**Not absorbed into the mechanical C12-P core.** Reason: the affected bytes are
LLM-facing prompt semantics, changing them triggers the repository's Gate-1
requirement, and that must not turn an otherwise deterministic
admission/preflight corrective into a mixed mechanical + prompt-semantics PR.

**This existing C12-P top-level session is the parent/orchestrator. No new
top-level session.** A bounded child subagent/worktree is spawned when useful —
`/home/yuema137/siderius-c12pp-prompts`, branch `c12pp-prompt-contamination`.

**The bounded C12-P-P claim:**

> A foreign composed task must not receive TIDMAD-specific scientific
> constraints / model facts merely because it traverses the shared planner or
> proposer prompt path — while existing TIDMAD / Regime-A prompt semantics
> remain **byte-equivalent** unless a separately justified change is required.

**Design principle**: a call-site / resolved-task boundary solution. The generic
prompt system RECEIVES task-appropriate declared constraints; it never infers
them from task names. Forbidden: task-name branches · a central task catalog ·
deleting useful TIDMAD guidance from genuine TIDMAD runs · replacing TIDMAD
literals with **guessed** foreign-task science.

Minimal acceptable semantic contrast:

```text
TIDMAD run           -> current legitimate TIDMAD constraints PRESERVED
foreign composed run -> TIDMAD-only scientific constraints ABSENT
```

If no generic task-owned constraint channel exists and a new capability family
would be required to *replace* the removed constraints, **do not invent it**.
Omitting the irrelevant TIDMAD-specific section from the foreign-task prompt is
explicitly acceptable, with **Gate 1** evaluating whether that remains
operationally acceptable.

**Timing**: PR-12d has touched planning surfaces, so no canonical production
prompt edits against a moving 12d authority. Before landing — census, exact
pre-fix prompt capture, anti-vacuity fixtures, design, Gate-1 protocol prep.
After landing — reconcile, smallest bounded call-site change, freeze prompt
bytes, deterministic prompt-diff tests, then Gate 1.

### W.2 Q-C12P-5 — RULED: ONE bounded real Pets Gate 2 IS REQUIRED

**Deterministic evidence alone is NOT the final C12-P core acceptance.** Most
individual properties are mechanical and must still be proven deterministically,
but the core corrective changes the real composed-task admission/runtime path
that was previously hidden behind TIDMAD assumptions and artifact-presence
guards.

**After** landed-12d reconciliation and **after** all deterministic falsifiers
are GREEN: run **exactly ONE** bounded real Pets Gate 2 changed-path witness.
**Integration witness only — not scientific-quality proof.** It must
intentionally exercise the repaired path, **not** reuse the configuration that
bypassed B1/B4 in PR-12d's DAVIS run.

**Required shape** (where supported by the final reconciled contract):

- a **NON-NULL bounded time budget**, so the repaired B1/B4 applicability path
  is actually traversed;
- runtime-control / watchdog configuration that **exercises** the repaired
  B6/B7 transport rather than leaving it dormant;
- real Pets task scope;
- bounded workload inside the authorized wall-time envelope;
- no scientific-quality threshold beyond existing health/safety acceptance;
- **no task-name workaround.**

> ⛔ **Before launch, prove MECHANICALLY that the intended command actually
> reaches the changed production sites. If the changed sites are not reached,
> DO NOT spend the Gate — fix the validation configuration, not the product
> semantics.**

This pre-Gate reachability proof is a **required artifact**, not a formality:
the whole reason this Gate exists is that the previous contrast launches
*bypassed* these paths.

**Acceptance — the witness establishes ONLY:**

- a foreign composed task reaches the repaired admission/preflight path;
- applicability is **explicit**, not inferred from TIDMAD artifacts;
- runtime observation / policy / watchdog machinery is **armed when
  configured**;
- **no TIDMAD-labelled calibration is exported** for the foreign task;
- **B5 protection is active before B6 exposure**;
- task-owned / runtime values are propagated rather than filled with TIDMAD
  literals;
- the composed run completes the required bounded chain.

**It must NOT be used to claim**: scientific superiority · generic
measurement-identity extensibility · that B8 is fixed · that every future task
is validated.

### W.3 Gate authorization discipline (§8) — binding

This ruling authorizes the **design requirement** for one Gate-2 witness. It
**does not** populate or modify the local launch-authorization ledger.

**Before any physical launch**: return the exact frozen command + `run_name`
and the required **human-authored** launch-authorization entry.
**An implementation agent must never infer or write its own authorization.**

There is exactly **ONE** planned C12-P core real Gate witness. Any retry after a
failed physical launch follows the standing launch-budget policy and requires
diagnosis — **no blind reruns.**

### W.4 Evidence boundaries stay separate (§9)

```text
C12-P core   deterministic falsifiers + ONE bounded Pets Gate 2
C12-P-P      prompt byte/semantic tests + ONE bounded Gate 1
```

**Neither Gate may be used as ceremonial evidence for the other's claim.**

### W.5 Downstream dependency (§10)

PR-12e §T reconciliation must consume: **final atomic C12-P core** + **successful
C12-P-P closure** + **landed-source C12-I verification**, after landed PR-12d.

⇒ **C12-P-P is a real precondition for the final external-task `G-12e`
witness**: the external task must not graduate while receiving known TIDMAD-only
scientific prompt contamination.

### W.6 Post-landing unified report — the required contents

After PR-12d lands, ONE unified landed-source reconciliation reporting:

1. `C12-P CORE RECONCILIATION RESULT`
2. `C12-P-P IMPLEMENTATION READINESS`
3. `B7 AUTHORITY RESULT` (per §V.4's A/B classification)
4. the proposed exact Pets Gate-2 command
5. the proposed Gate-1 plan

---

## X. C12-P-P preparation result — and a CROSS-UNIT ORDERING INVARIANT

The C12-P-P child ran its preparation phase and was interrupted by a session
limit after three commits. Its work was reviewed and extended by the parent;
**zero production source is touched** on `c12pp-prompt-contamination`.

### X.1 ⛔ P1 and B3 MUST MOVE TOGETHER — a coupling the split did not anticipate

The child's central finding, **re-verified executably by the parent** in the
correct tree (`module: …/siderius-c12pp-prompts/agent/schemas/proposal.py`):

```
seg=   224 (plausible Pets/DAVIS spatial size)  -> REJECTED
seg=    37 (Pets class count)                   -> REJECTED
seg=   144 (Pets' OWN declared default)         -> REJECTED
seg= 20000 (TIDMAD divisor)                     -> ACCEPTED
```

The TIDMAD constraint block in the proposing prompt is **not gratuitous**: it
accurately describes a gate the foreign task really hits, because
`ProposalOutput._validate_baseline_segmentation_size` enforces the *same* rule
from the *same* module-scope constant. **That validator is C12-P core's B3** —
whose fix was reverted per §V.1 and deferred to landed 12d.

Therefore:

| what lands | effect on a foreign composed task |
|---|---|
| **prompt fix ALONE (P1)** | ⛔ **strictly WORSE than today.** The proposal is still rejected by a `ValidationError` naming a quantity the task does not have — but the guidance that would have prevented it has been deleted, burning retries |
| **validator fix alone (B3)** | tolerable: the task is no longer blocked, though the prompt still teaches it a false rule |
| **both** | correct |

> **INVARIANT: C12-P core's B3 must land BEFORE or WITH C12-P-P's P1. P1 must
> never land alone.** A prompt-only fix here is a regression disguised as a
> cleanup.

This is a second atomicity constraint, structurally identical to §I's B5/B6 one
but spanning the two *units* the operator separated. **It does not dissolve the
split** — the Gate boundary is still correct, because P1 changes LLM-facing
bytes and B3 does not — but it does constrain the landing order across them,
and PR-12e §T consumes both anyway (§W.5).

### X.2 The channel question — answered, and it is NOT `proposal_blocks`
PR-12a's `ProposalTaskBlocks` is **free prose rendered verbatim**. The P1 block
is **computed** (`psd = dataset_config.psd_segment_length`;
`valid = dataset_config.valid_segmentation_sizes()`) and must stay in lockstep
with an executable validator. Declaring it as prose would put the *stated* rule
and the *enforced* rule in two unrelated authorities — the duplicate-authority
failure this codebase has repeatedly paid for. **Its natural authority is the
run's already-composed dataset declaration**, i.e. the same resolved value B3's
fix reads. One run-scoped value, read by both halves.

### X.3 Two vacuity defects found in the child's own evidence, and fixed
Both are recorded because they are the shapes this repository keeps paying for.

1. **The parity guard silently did not run.** The six Regime-A byte-parity
   cases `pytest.skip()`-ed when `OPENAI_API_KEY` was unset — and by the
   module's own reasoning those are *the only* assertions that fail when a fix
   strips the block from **both** regimes instead of just the foreign one. CI
   runs unit + static with no API keys **by design**, so the single most
   important guard would have been absent exactly where it is relied upon.
   Replaced with an autouse fixture supplying a non-credential-shaped value;
   sound because the key is read only for eager client construction and both
   generate methods are patched with a `side_effect`. **Verified with the key
   explicitly unset: 8 passed, ZERO skipped.**
   **Mutation-proven**: planting the naive both-regimes fix turns
   `test_tidmad_regime_a_prompt_is_byte_identical_to_baseline[03_proposer_proposing__system]`
   RED; `agent/prompts.py` reverted and verified byte-identical.
2. **The contamination test observed a checked-in file, not production.** It
   read the committed pre-fix baseline, so **no production change could ever
   turn it green** — only re-capturing the artifact could, which would make it
   certify a ceremony, and it would then pass while production still emitted
   the markers if anyone re-captured without fixing. That is this repository's
   own recorded F-12bc-7 lesson. It now renders **live**, with a guard
   asserting the expected stage is present so it cannot pass by looking at
   nothing. It is RED for the production reason, naming six markers.

### X.4 A contamination site no suppression channel can reach
`[B, 256, T]` is hardcoded in the **stage template itself**
(`agent/prompt_templates/proposal/proposing_stage.md`), with **no
placeholder** — so no declared channel can suppress it. `256` is TIDMAD's int8
ADC amplitude axis and is false for a 37-class classification or a regression
task. Recorded as part of P1's surface, not as a new capability need.

### X.5 Why an existing test never caught this — verified
`tests/unit/agent/ml_model_proposal_agent/test_known_constraints_block.py`
covers this block in nine cases, and **every one supplies the dataset config
where production hardcodes it** (verified: eight `_format_known_constraints_block(TIDMAD)`
calls plus one `None`). It therefore certifies the *renderer* perfectly and can
never observe that the *call site* is unconditional.

> **The rule this suggests: a test that supplies an argument the production
> call site hardcodes is testing a function, not a behaviour.**

Corroboration in the other direction, also verified: the un-composed PB-3
goldens `pb3_proposing_{explore,exploit}_system.txt` **do** contain the block,
so Regime-A parity is independently guarded — a second reason the fix must not
alter the un-composed leg.

### X.6 Status
`c12pp-prompt-contamination`, 4 commits, clean tree, **no production edits**,
nothing pushed, nothing merged, no Gate run. Byte-exact baselines captured for
both regimes; census, fix design and Gate-1 protocol drafted. Canonical
implementation waits for landed 12d per §W.1's timing discipline.

An untracked `docs/proposer_prompt_audit.md` — a side-effect regeneration from
an unrelated audit script — was moved to the session scratchpad rather than
deleted, and is not part of any deliverable.

---

## Y. Operator ruling — 2026-08-24 (fourth: P1↔B3 coupling FROZEN, unit PARKED)

The C12-P-P preparation packet is **accepted**. No further C12-P core
implementation is requested before landed PR-12d.

```text
C12-P CORE PARKED CLEANLY
C12-P-P PREPARATION COMPLETE
WAITING FOR LANDED PR-12d
DO NOT MERGE
```

### Y.1 The P1↔B3 coupling is FROZEN

The finding is accepted as load-bearing: **TIDMAD's prompt guidance is
currently compensating for an executable validator that imposes the same
TIDMAD-specific scientific constraint on foreign tasks.** Removing only the
guidance leaves the foreign task subject to the same invalid executable rule
while deleting the text that helps the model work around it. Strictly worse.

```text
B3 closes FIRST   or   B3 and P1 land in the SAME integrated source stack
                but
            P1 MUST NEVER LAND ALONE
```

**This does NOT collapse C12-P-P back into the mechanical core.** The
evidence/Gate boundary remains valid — B3 is mechanical validator closure with
deterministic evidence; P1 is an LLM-facing prompt change needing deterministic
prompt evidence **plus Gate 1**. Two separate semantic units, one hard
landing-order dependency.

### Y.2 `proposal_blocks` is NOT the authority — confirmed
Do **not** move the scientific constraint into `proposal_blocks` merely to
preserve the text; that duplicates the executable rule into a second authority.
**The final design must preserve ONE semantic authority.** If landed 12d
exposes an existing task-owned constraint channel, inspect it. Otherwise the
bounded P1 fix may simply **suppress** the irrelevant TIDMAD-only guidance for
foreign tasks **after** B3 no longer imposes the rule. **Do not invent a new
constraint capability family solely for P1.**

### Y.3 Evidence repairs accepted — all four conditions VERIFIED

The operator conditioned acceptance of the parity fixture on four properties.
Each is now proven, not asserted:

| condition | evidence |
|---|---|
| does not issue a real provider call | **Proven at the transport layer**: re-ran with `socket.connect`, `connect_ex` and `create_connection` monkeypatched to raise. Results identical — `1 failed, 8 passed`, no `NETWORK CALL ATTEMPTED`. Not merely inferred from the patches |
| supplies only the minimum constructor environment | the fixture sets exactly one variable, `OPENAI_API_KEY`, and only when it is absent; a real key already present is left untouched |
| key explicitly unset in the test environment | every verification run above used `env -u OPENAI_API_KEY` |
| zero critical parity tests skipped | `8 passed`, **0 skipped**, with the key unset |

Mutation proof **preserved**: removing/changing the Regime-A protection turns
`test_tidmad_regime_a_prompt_is_byte_identical_to_baseline[03_proposer_proposing__system]`
RED.

The live-render contamination test is confirmed as **the correct authority**;
snapshot-only evidence must not replace it. Preserve the live production
render, the six-marker RED baseline, and the anti-vacuity evidence.
`test_known_constraints_block.py` remains a **renderer-level control only** —
it must never be claimed as proof of the production call site.

### Y.4 ⚠️ Sequencing refinement — do NOT over-serialize P1 behind B7

**This corrects the parent's own closing statement in the previous report**,
which proposed sequencing the Gate-1 protocol after the B7 authority result.
That ordering was ceremony, not a dependency.

P1's Gate 1 is **hard-blocked by**: landed PR-12d **+ B3 closure** — because
the Gate must evaluate real *post-B3* foreign-task behaviour. It is **NOT**
automatically blocked by the separate B7 authority decision.

```text
B3 closure -> P1 implementation + deterministic prompt checks -> Gate 1
        may proceed IN PARALLEL with the B7 authority analysis
```

Serialize P1 behind B7 **only if** landed-source evidence proves B7 affects the
same Gate-1 execution path or makes the Gate semantically invalid. **Do not
introduce dependency ordering merely for ceremony.**

### Y.5 Parked state — what is preserved

All clean local branches · the P1/B3 coupling finding · live RED contamination
evidence · non-vacuous Regime-A parity evidence · the exact child commits · **no
Gate execution**.

| branch | commits | production files |
|---|---|---|
| `c12p-composed-admission-preflight` | 14 | 0 |
| `c12p-w1-b7b11` | 3 | 3 (DISJOINT) |
| `c12p-w2-b3` | 4 | 0 (reverted per §V.1) |
| `c12p-w3-b1b2` | 3 | 1 (AST-proven execution-inert) |
| `c12pp-prompt-contamination` | 4 | **0** |

Nothing pushed (`git ls-remote --heads origin 'c12p*'` = 0). Nothing merged.

**No further operator report before PR-12d lands**, unless a genuinely new
capability-family question appears. The next report is
`C12-P LANDED-SOURCE RECONCILIATION COMPLETE`, carrying: B3 landed-source
result · B7 authority result · P1 implementation readiness · the final B5/B6
atomic candidate · the proposed exact Gate-2 witness · the proposed Gate-1
witness.

---

## Z. LIVE WITNESS — PR-12d TIDMAD attempt 5 (record only; unit remains PARKED)

**Operator-supplied, 2026-08-24.** A real PR-12d **TIDMAD** run independently
confirmed the already-owned time-budget / runtime-probe finding (the 12d census
**A7 / D1** entry, this document's **B1/B4**). Observed:

```text
tuner reached successfully
time-budget path ARMED
core/runtime_control/probe_production.py terminated the chain
bounded live probe -> status=load_failure
                      "no dataset directory was supplied to the probe"
PR-12d has NO source diff in this subsystem
```

**No fix is implemented. No Gate, merge or production write is requested.**
Preserved as landed-source reconciliation evidence, to be folded into the
B1/B4/runtime-control falsifier packet when the unit wakes.

### Z.1 The witness hit a DIFFERENT raise than the forensics predicted

This is the load-bearing detail, and it is why the witness is worth more than a
confirmation.

| | predicted by the audit | **observed live** |
|---|---|---|
| site | `probe_production.py:249-254` — `build_bounded_probe_batch` → `tidmad_topology` | **`probe_production.py:226-231`** — `if not resolved_dir:` |
| trigger | a composed task declaring no TIDMAD topology | **an absent `data_dir`** |
| task | foreign (Pets/DAVIS) | **TIDMAD** |
| order | after the model is built and moved to GPU | **before** the batch builder is ever called |

Both raise inside `production_probe_executors._setup`, so both are swallowed by
`core/runtime_control/probe.py:417-420` into the *same*
`ProbeResult(status="load_failure")` → `ABORT` → chain termination. **The
status the operator observed is exactly the misattribution §D/E2 records** —
`load_failure` is the label for "the candidate model failed to load", and
neither of these is that.

### Z.2 ⚠️ The finding is WIDER than "foreign tasks break"

The witness fired on **TIDMAD**, with no composition involved. So the B1/B4
blast radius is not confined to composed foreign tasks.

The mechanism is a contract contradiction **inside** the runtime-control
subsystem, between two places that both describe `data_dir=None`:

| authority | what `data_dir=None` means |
|---|---|
| `nodes/…/cli.py:265-270` — `--data_dir`, `default=None` | *"None makes the skill fall back to its **static formula**."* |
| `nodes/…/ml_hyperparameter_tune_agent.py:826-831` | `None` *"keeps its meaning of 'no warmup, use the static-formula estimate'"* |
| `core/runtime_control/probe_production.py:226-231` | **hard `RuntimeError`**, terminating the chain |

⇒ Whenever a time budget is armed **and** `--data_dir` is not passed, a
documented, supported configuration ("no warmup requested") is converted into a
chain-terminating probe failure — **on any task, TIDMAD included.**

### Z.3 What the corrective must NOT do — recorded before anyone is tempted

The absent-`data_dir` refusal is **deliberate**. Its own comment records that
07c C4 removed a `TIDMAD_DATA_DIR` fallback that used to fill in there,
because *"it was a task assumption inside generic runtime-control: on any other
task it resolved somebody else's dataset."*

> **Restoring that fallback would re-introduce the exact defect 07c C4 removed
> and would undo one of this subsystem's genuine repairs. It is forbidden.**

The defect is **not** the refusal. It is that the refusal is *reached at all*
when the caller never asked for a measurement, and that it **terminates the
chain** instead of degrading to the static formula the CLI documents.

Against the operator's own §V.2 taxonomy, "no `data_dir` because no warmup was
requested" is **not** `ERROR` (nothing is malformed) and **not** `APPLICABLE`.
It is the caller declaring the measurement out of scope for this run — which
§V.3 says must be decided **caller-side, once**, and passed down, rather than
rediscovered by a leaf module raising from the absence of an artifact.

### Z.4 Consequences for the reconciliation packet

1. **Add this exact production failure mode to the B1/B4 falsifier packet** and
   verify the final corrective catches it — an armed time budget with no
   `--data_dir`, on **TIDMAD**, must not terminate the chain.
2. The B1/B4 corrective must therefore handle **two distinct absences** —
   *no task topology* (semantic non-membership) and *no measurement requested*
   (caller scope) — and must not collapse them into one branch, nor into
   `ERROR`.
3. The existing falsifiers assert on `probe_status`, not on an exception type
   (§D/E2). **That choice is vindicated**: this witness produces the same
   `load_failure` status from a completely different raise, so a
   type-based assertion would have missed it.
4. `probe_production.py` remains **DISJOINT** from 12d's write set — confirmed
   again by the operator's note that 12d has no source diff in this subsystem —
   so this hunk stays landable without waiting on the predicate.

**Status unchanged: C12-P PARKED, WAITING FOR LANDED PR-12d, DO NOT MERGE.**

---

## AA. OWNERSHIP TRANSFER from PR-12d — the `data_dir` transport (record only; PARKED)

**Operator, 2026-08-24.** PR-12d attempts 5 and 6 isolated the runtime-control
failure to **one missing transport**:

```text
scripts/run_comparison.py  does not propagate data_dir into the tuner
        =>  agent_input.data_dir = None
```

**One root defect, two consumers, two independent fail-closed witnesses:**

| | attempt 5 | attempt 6 |
|---|---|---|
| time budget | **armed** | **deliberately not armed** |
| consumer | `core/runtime_control/probe_production.py:226` | `core/runtime_control/gpu_measurement_worker_main.py:269` |
| observed | `load_failure: no dataset directory supplied` | `dataset directory unavailable for the measurement: None` |

Both verified against source by the integration owner. The second consumer is
the **pre-phase GPU measurement worker** — a different lane from §Z's probe, so
arming or disarming the time budget only chooses *which* consumer reports it.

**PR-12d has formally classified its frozen §J rows 4/5 as `NOT PROVEN` /
`BLOCKED_EXTERNAL` / `DEFERRED_TO_C12P`.**

### AA.1 C12-P's two new obligations

1. **Correct the bounded generic `data_dir` transport** across the legacy
   launcher → tuner boundary, **without inventing a task-specific fallback.**
2. **After that fix, re-prove PR-12d's deferred §J rows 4/5** with a bounded
   framework witness.

⚠️ This is a **material ownership expansion**: C12-P now owes evidence for
another PR's frozen acceptance rows. Recorded explicitly so it is not absorbed
silently — it enlarges the unit's acceptance surface, not just its write set.

### AA.2 The fix is an APPLICATION of an existing authority, not an invention

Verified from source, and this is the decisive fact for §AA.1's *"without
inventing a fallback"* constraint:

| fact | evidence |
|---|---|
| a single launch-boundary authority **already exists** | `execute_tools/data_paths.py` — `resolve_dataset_dir(...)` + `DatasetDirectoryUnavailable`; its own comment calls it *"exactly ONE"* such rule |
| the SDSC launcher **already honours it** | `sdsc_submission_scripts/run_one_iteration.py:1779` — `args.data_dir = resolve_dataset_dir(args.data_dir, purpose="this chain iteration")` |
| `scripts/run_comparison.py` **does neither** | zero calls to `resolve_dataset_dir`; and **zero** `data_dir` occurrences among its `cmd.extend([...])` tuner-spawn arguments |

⇒ The corrective is to apply the **same** authority at the **second** launch
boundary, exactly as the first one already does. **No new capability, no
default, no synthetic directory, no task-name dispatch** — the constraint is
satisfied by construction rather than by discipline.

### AA.3 ⚠️ This exact failure was already paid for once — and the guard's scope missed

`tests/unit/sdsc_submission_scripts/test_gate_data_dir_resolution.py` exists
**because of this precise failure string**, observed during **PR 04a's** Gate
validation. Its docstring, verbatim:

> *"a canonical Gate launch omits `--data_dir` … the value travels to the tuner
> as `None`, and the pre-phase GPU measurement fails closed with **"dataset
> directory unavailable for the measurement: None"** — **after** a real LLM had
> already generated, validated and registered a candidate. Roughly ten minutes
> of paid work, discarded, for a fact knowable at launch."*

and it pins exactly the invariant now being re-learned:

```text
launch configuration
  -> ONE existing authority for the physical dataset location
  -> resolved AND validated BEFORE any expensive work
  -> the same resolved value reaches every downstream consumer
```

**The guard is correct, states the right invariant, and lives under
`tests/unit/sdsc_submission_scripts/` — so its scope covers the SDSC launcher
and not `scripts/run_comparison.py`, the launcher CLAUDE.md documents as
standard.** This is the census-blindness family one launcher over: not a wrong
assertion, an omitted member of the set the assertion should quantify over.

⇒ **The re-proof of §J rows 4/5 must assert the invariant across EVERY launch
boundary, not add a second launcher-specific test.** Otherwise the same defect
reappears at launcher three.

### AA.4 Mandatory regression falsifiers for the reconciliation packet

Both witnesses become required cases, and both directions must be pinned:

| case | required behaviour |
|---|---|
| **missing authoritative `data_dir`** | stays **loud / fail-closed** — the refusal is deliberate (§Z.3, 07c C4) and must not be softened |
| **valid authoritative `data_dir` transported** | **both** runtime consumers receive it — `probe_production.py` *and* `gpu_measurement_worker_main.py` — and §J rows 4/5 become reachable |
| launcher coverage | asserted for **every** launch boundary, per §AA.3 |

Explicitly forbidden: a synthetic/default dataset directory · task-name
dispatch · reinterpreting any of this as a model-quality issue.

### AA.5 Overlap classification — this hunk WAITS

`scripts/run_comparison.py` **is in PR-12d's production write set** (confirmed
in the refreshed set at §L). So despite the fix being a one-line application of
an existing authority, it is **OVERLAPS_ACTIVE_12D ⇒ DEFERRED**. Design and
falsifiers may be prepared; the production hunk lands only after
landed-source reconciliation.

The two *consumer* modules remain **DISJOINT** and unchanged by 12d.

**Status unchanged: C12-P PARKED, WAITING FOR LANDED PR-12d, DO NOT MERGE.**
Next action remains: wait for the exact landed SHA.

---

## AB. LANDED-SOURCE RECONCILIATION — checkpoint 1

**PR-12d LANDED.** `PR #274` · `FINAL_EXECUTABLE_SHA a1d5c101` ·
**`LANDED_SHA = 84d74280fdda6637afb6dad353f882501196ea98`** = `origin/master`,
verified. A **squash** merge directly onto `c991d6f6`, this unit's base — so
the entire 12d delta is one commit above our anchor, with no interleaving.

12d disposition (recorded, **not** reinterpreted as failures): Pets **PASS**,
DAVIS **PASS**, TIDMAD §J row 3 **PROVEN**, §J rows 4/5 **NOT PROVEN /
BLOCKED_EXTERNAL / DEFERRED_TO_C12P**.

Working branch: `c12p-landed` at `/home/yuema137/siderius-c12p-landed`.

### AB.1 Reconciled write set — 12d vs C12-P's owned files

51 production `.py` files changed by landed 12d. Against C12-P's set:

| file | 12d | consequence |
|---|---|---|
| `core/runtime_control/probe_production.py` | **untouched** | W1 fix applies unchanged |
| `core/runtime_control/gpu_measurement_identity.py` | **untouched** | " |
| `core/runtime_control/gpu_measurement_worker_main.py` | **untouched** | " |
| `agent/schemas/proposal.py` | **untouched** | B3 fix applies unchanged |
| `agent/utils/proposer_preflight.py` | **untouched** | W3 comment applies unchanged |
| `agent/prompts.py` | **untouched** | C12-P-P baselines still valid |
| `execute_tools/dataset_config.py` | **CHANGED** | supplies `declares_tidmad_topology` — **this is what closes B3** |
| `scripts/run_comparison.py` | **CHANGED** | only `file_index`→`input_identity`; the `data_dir` gap is untouched |

### AB.2 Speculative-commit disposition

| unit | verdict | evidence |
|---|---|---|
| W2 `dc0e4000` (vendored predicate) | **ALREADY ABSORBED BY LANDED 12d** | landed predicate is **byte-identical** to the reverted copy (`ast.get_source_segment` comparison). The operator's revert was exactly right — keeping it would have been a second authority for nothing |
| W2 `8bf651ca` (B3 fix) | **STILL REQUIRED — now CLOSED** | applies cleanly; **22 tests pass on landed source** |
| W1 `b9e1e840` (B11 triad) | **STILL REQUIRED — applied** | applies cleanly; census offender list drops 8 → 5 files |
| W1 / W3 falsifiers | **STILL REQUIRED** | apply cleanly; B1/B2/B7/B11 remain RED against landed source |
| W3 `091accc9` (comment) | **STILL REQUIRED** | execution-inert; applies cleanly |
| C8 B8 sentinel | **STILL REQUIRED — premise HOLDS** | landed `sandbox_executor.py:1556-1557` still gates `--order_strategy` inside the `:1528` `sample_set` block |
| C12-P-P (4 commits) | **STILL REQUIRED** | `agent/prompts.py` and the templates untouched by 12d |
| — | **obsolete / conflict** | **none.** Every patch applied cleanly; nothing needed re-derivation |

**No patch was mechanically replayed without checking its premise**: each
target file's 12d status was verified first, and the B6/B8/B11 preconditions
were re-asserted against landed source before porting.

### AB.3 The `data_dir` transport — FIXED (highest-priority inherited obligation)

Source path, end to end:

```text
main()  --data_dir override (new, optional)
   |    resolve_dataset_dir(args.data_dir, purpose=...)      <- the ONE authority
   |    ORDERED AFTER pure-CLI validation, BEFORE any expensive work
   v
run_agent(..., data_dir=resolved_data_dir)
   |    cmd.extend(["--data_dir", data_dir])                 <- the missing transport
   v
tuner: agent_input.data_dir
   |-> runtime.py:353  getattr(agent_input,"data_dir",None)  -> consumer 2 (attempt 6)
   `-> bindings.time_data_dir -> execution.py:429/449        -> consumer 1 (attempt 5)
```

Requirements 1–5, each satisfied and how: **(1)** no synthetic/default — the
value comes from the operator override or the gitignored per-machine config,
via an authority that raises rather than substituting; **(2)** no task-name
dispatch anywhere on the path; **(3)** unresolvable root ⇒
`DatasetDirectoryUnavailable` ⇒ `SystemExit` **at launch**; **(4)** both
consumers verified to read the transported value, by their two **different**
paths; **(5)** attempts 5/6 are the falsifiers, below.

**An ordering defect I introduced and corrected.** Resolving *before* the
pure-CLI validation made a malformed `--data_scope` report a missing data
directory, and made the startup guards untestable without a per-machine config.
Diagnosed from the three red `test_run_comparison_data_scope` guards —
**my ordering was wrong, not the tests** — and moved after them.

**Falsifiers**: `tests/unit/scripts/test_c12p_data_dir_launch_transport.py`,
9 cases, built as a **census over launch boundaries** rather than a third
launcher-specific test (§AA.3). Mutation-proven against pristine landed source:
**2 RED** (the `run_comparison.py` census case and the transport assertion),
**9 green** with the fix — and the **SDSC case passes in both states**, so the
census discriminates rather than being uniformly red.

### AB.4 B7 AUTHORITY RESULT — **VERDICT A: EXISTING AUTHORITY SUFFICIENT**

The operator's question: *does landed source already contain an authoritative
task-neutral value from which B7's step count can be derived without inventing
a second scientific/runtime authority?*

**Yes, and it is already in production for the sibling leg.**
`execute_tools/scope_artifact.py:371-372` (landed):

```python
dataset = bound.validation_dataset(evaluation, EvalMaterializationParams(data_dir=data_dir))
return ["--validation_requested_rows", str(len(dataset))]
```

That derives a **task-neutral cardinality** from a **frozen four-method
`TaskDataPath`** method plus `len()`. `training_dataset(scope, params:
EpochSamplingParams) -> Dataset[Any]` (`task_data_path.py:363`) is the frozen
sibling with the identical shape, and
`steps = (len // batch_size) * epochs` mirrors `resolve_training_workload`'s
own arithmetic. ⇒ **no new capability family, no new protocol method, no
second authority. B7 continues inside C12-P; no MATERIAL STOP.**

Two honest caveats, recorded rather than glossed:
- construction verifies per-row file existence (`_PetsManifestDataset`:
  *"Decoding is lazy per item; EXISTENCE of every named file is verified at
  construction"*), so the cost is bounded I/O proportional to rows — **the same
  cost the eval leg already pays in production**, not a new one;
- the derivation needs `data_dir`, **which is exactly what §AB.3 just
  repaired.** B7's fix was therefore blocked by the transport defect, and is
  now unblocked by it.

### AB.5 Status of the standing obligations

| item | status |
|---|---|
| **`data_dir` transport** | **FIXED**, falsifiers mutation-proven |
| **B3** | **CLOSED on landed source** — 22 pass, using the canonical landed predicate |
| **B7** | **verdict A**, unblocked; implementation next |
| **B11** | disjoint triad **fixed**; census offenders 8 → 5 files. The `planned == measured` pairing invariant is **preserved by construction** (the triad moved together); its dedicated plant-the-naive-fix falsifier (§V.5) is still owed |
| **B1 / B2** | falsifiers **RED against landed source**; fixes are the next units |
| **B5 + B6** | not started — the atomic unit, still governed by §I |
| **B8** | sentinel green; premise re-verified on landed source; **stays NOT REACHABLE** |
| **P1 / C12-P-P** | prep complete; **still coupled to B3** (§X.1). B3 is now closed, so the coupling's precondition is **satisfied** — P1 may proceed once its own reconciliation runs |
| **§J rows 4/5** | repro plan below |

### AB.6 §J rows 4/5 repro plan

The transport fix removes the blocker. The bounded **framework** witness:

1. deterministic first — the 9 transport falsifiers already prove the resolved
   root reaches the tuner argv and that both consumers read it;
2. then the bounded real witness, under §W.2/§W.3 authorization rules, with the
   **non-null time budget** that makes the repaired B1/B4 path reachable —
   the configuration `D-12d-52` previously recorded as a deterministic crash;
3. acceptance is **reachability of rows 4/5**, not model quality. **No epochs,
   data, tuning or retries may be added to improve scientific quality.**

⚠️ Rows 4/5 additionally depend on **B1/B4 being fixed**, not only on the
transport: with a non-null budget the run now reaches the wall-time pre-flight,
which is still TIDMAD-only. **Sequence: B1/B4 fix → then the rows 4/5 witness.**

### AB.7 MATERIAL STOP — none

No new capability family is required. B7 resolved to verdict A. No task-name
dispatch, task catalog or topology catalog was needed anywhere.

**One environmental fact, so it is never misread as a landed-master defect**:
`tests/unit/scripts` + `tests/unit/sdsc_submission_scripts` show **52 failures
on pristine landed master** in a git worktree. Cause: shell-invoking tests
expect `<worktree>/.venv/bin/python`, which exists only in the primary
checkout. **Not a defect, and not C12-P's.** All C12-P verdicts here are
computed as a **delta** against that pristine baseline, which is currently
**zero**.

---

## AC. CHECKPOINT 2 — B1/B2/B4 closed, rows 4/5 unblocked and AWAITING AUTHORIZATION

Branch `c12p-landed`, 7 commits above `84d74280`. Tree clean. Nothing pushed.

### AC.1 Closed since checkpoint 1

| item | evidence |
|---|---|
| **B2** | `ae4a63fd`. VRAM gate prices from the declaration via `resolve_model_field`. Falsifiers RED→GREEN (348 passed); the B11 census independently corroborates by dropping the file from its offender list (5 → 4) |
| **B1 + B4** | `ea003b37`, ONE semantic unit. `wall_time_preflight_applicable` decides once caller-side; B4's probe lane is only reachable through B1's gate, so one decision covers both |
| **malformed loudness** | same commit. The DECLARATION boundary is hoisted **above** the broad operational fallback, so a malformed declaration propagates instead of degrading to a static estimate |
| **B11 pairing falsifier** | `611a39d0`. §V.5's required plant-and-catch |

### AC.2 The malformed-loudness fix was source-grounded before editing
There is **no existing typed exception** for a malformed topology —
`tidmad_topology` raises plain `ValueError` for *both* absence and
malformation. So rather than invent a type, match a message, or make all
`ValueError` fatal (all forbidden), the validation boundary moved **above** the
broad catch. W3's distinction is preserved exactly: unknown operational failure
still degrades conservatively; known semantic invalidity does not.

Four behaviours, observably distinct, in one test:
`A foreign → NOT_APPLICABLE` · `B valid → normal path` · `C malformed → LOUD
ValueError, no fallback` · `D operational → conservative fallback`.
C and D are separated by a real condition (a data dir that exists but holds no
TIDMAD shards), not a stub. **Mutation-proven**: reintroducing the swallow
turns C RED.

### AC.3 A vacuity defect in my OWN falsifier, found and fixed
The first §V.5 structural guard asserted the substring
`'"segmentation_size", 40000'` was absent. The planted regression wrote
`40_000` — the same integer to Python, a different string to `in` — so **the
plant PASSED**. That is the "census matches a token exactly" blindness shape
this repository has already been burned by. The guard now walks the AST for a
`.get("segmentation_size", <int>)` call, and the plant correctly turns it RED.
Recorded because the lesson is the deliverable: *a plant that passes is not a
green test, it is an untested test.*

### AC.4 Rows 4/5 — the blocker is removed; the witness is NOT yet run

**What rows 4/5 require** (landed 12d §J): row 4 = TIDMAD scored through the
tuner's ROUTE DECISION (`resolve_scoring_route`); row 5 = cleaned up through
the naming authority (`run_deliverable_naming.experiment_glob`). Both are
downstream of admission, so both need a round that actually **trains**.

**Mandatory pre-Gate mechanical reachability proof — PASSED** (§W.2 requires
this before spending the Gate):

```text
main() resolves via resolve_dataset_dir(args.data_dir)      True
main() passes data_dir=resolved_data_dir to run_agent       True
run_agent emits ["--data_dir", data_dir]                    True
tuner CLI declares --data_dir                               True
consumer 2 (prephase) reads agent_input.data_dir            True
consumer 1 (probe) threaded data_dir=time_data_dir          True
row 4 site  resolve_scoring_route          present downstream
row 5 site  run_deliverable_naming.experiment_glob   present downstream
```

⇒ the transport defect that blocked attempts 5 and 6 is removed, and the two
row sites are reachable once a round trains.

**⛔ NOT LAUNCHED.** Per §W.3 the design requirement does not populate the
launch-authorization ledger, and an implementation agent must never infer or
write its own authorization. The exact command and the required human-authored
entry are returned to the operator with this checkpoint.

**Acceptance is framework reachability only** — row 4's route decision executes
and row 5's cleanup runs through the naming authority. **No tuning, no added
epochs, no added data, no quality retries**, and no scientific threshold.

### AC.5 Remaining

| item | state |
|---|---|
| rows 4/5 witness | blocked on operator authorization only |
| **B5 + B6** | not started — the atomic unit, §I governs; B5 protection before B6 exposure, same landing |
| **B11** production sites | `planning.py` (2), `runtime.py`, `bootstrap.py`, `ml_model_implementor` (2) — census offenders, 4 files |
| C12-P-P / P1 | precondition satisfied (B3 closed); reconciliation not yet run |

**MATERIAL STOP: none.**

---

## AD. §J ROWS 4/5 — PROVEN BY C12-P LANDED-SOURCE FOLLOW-UP

**Witness**: `run_name c12p_j_smoke_a5` · HEAD `b7b085860af719efc9863fefa6533199c374bdec`
· ~16 min · 125 optimizer steps · exit *"Comparison run completed successfully."*
Frozen §J command **unmodified**; `--data_scope 6 --health_gate_files 6`;
**no `--baseline_workspace`**; `--cleanup_denoised` ON.

### AD.1 ROW 4 — the scoring ROUTE DECISION executed. **PASS**
From the run's own production chain, not from exit code:

```
L27   "Trial mode enabled: anchor map loaded."      anchor_map_data is NOT None
      execution.py:1068  resolve_scoring_route(...) sits UNCONDITIONALLY
                         immediately before the scoring try-block
      policy.py:1268     first branch -> ANCHOR_NORMALIZED
L221  "[Step 3/3] Scoring..."                        scoring block ENTERED
L222/223 [MEM] pre_score / post_score                block RAN TO COMPLETION
L224  "[HEALTH CHECK] output_diversity_blocking"     health consumed the SCORED output
```

The decision executed **and** selected `ANCHOR_NORMALIZED`. This satisfies BOTH
candidate readings of the frozen row — interpretation A (the decision executes)
and incidentally B (the TIDMAD route was the one selected) — so the A-vs-B
ambiguity recorded earlier is **MOOT for this witness** and needs no ruling.

### AD.2 ROW 5 — the cleanup glob executed through the naming authority. **PASS**
```
L219  HDF5 ".../abra_validation_denoised_..._006_0006.h5" created successfully
L225  "Cleaned up 1 denoised files (3.7 GB freed)"
```
`run_deliverable_naming.experiment_glob(exp_id=...)` matched and deleted the
**real artifact produced by this round**. Not a vacuous sweep over an empty set.

### AD.3 The three evidence classes, deliberately NOT collapsed
| class | outcome |
|---|---|
| **route mechanics** | row 4 PASS · row 5 PASS |
| **scientific quality** | `output_diversity` FAILED (file_6 = 3 unique int8 vs threshold > 25) · `gate_action=invalidate_round` · `status=failed_mode_collapse` · `denoising_score=None`. The deliberately tiny 125-step model collapsed. **NOT a rows-4/5 failure.** |
| **prerequisite provenance** | CP-13 **CASE A** — compatibility provable |

### AD.4 CP-13 — CASE A, and the enforcement gap that remains
Reused baseline vs this run: `model_type` wavenet == wavenet · scope `[6]` ==
`[6]` · `health_gate_enabled` True == True · formal == formal ·
**`health_config_sha256` = `39e13e2d5df7003bb39d43b8fe306122ae863b8b8a4d7715f2c92520ea9cd426`
IDENTICAL**.

⚠️ But production checked **none** of that. `scripts/run_comparison.py:1396-1410`
reuses by **existence alone** (`if history: baseline_record = history[0]`), and
that branch is taken precisely because the frozen command must omit
`--baseline_workspace` — which is simultaneously the SOLE trigger for
`validate_phase1_baseline` (`:1447`) and the thing that blocks the AGENT round.
**The flag that would validate the baseline is the flag that prevents the
witness from working.** Compatibility here holds by provenance, not by
enforcement. Recorded as **CP-13 → FAMILY_FOLLOWUP**; the witness stands.

### AD.5 Why 125 steps — classification **C**
`1 file × ceil(0.01×200)=2 PSD × (10,000,000/40000)=250 = 500 samples;
batch_size 4 ⇒ 125 steps.` Every factor is a frozen command parameter or an
LLM-planned hyperparameter — **none is a §J requirement**. A future equivalent
witness could validly use fewer. Recorded for future witnesses only; this one is
closed and must not be re-optimised.

### AD.6 The validation-design lesson, permanent
The first attempt ran a **1,000,000-step** full-scope baseline and was
**structurally incapable** of proving these rows (it armed `--baseline_workspace`).
The frozen command proved both in **~16 minutes and 125 steps** — ~8000× less
compute and *stronger* evidence, because it actually reached the rows.
**A framework-graduation witness must be bounded by the invariant it proves,
never inherit the task's scientific workload — and the frozen command must be
recovered BEFORE the first launch, not after the third.**

### AD.7 Disposition
```
PR-12d §J row 4 : NOT PROVEN / DEFERRED_TO_C12P  ->  PROVEN BY C12-P FOLLOW-UP
PR-12d §J row 5 : NOT PROVEN / DEFERRED_TO_C12P  ->  PROVEN BY C12-P FOLLOW-UP
provenance chain: PR-12d deferral -> C12-P repair -> witness c12p_j_smoke_a5 @ b7b08586
```
PR-12d's historical record is **NOT** rewritten as having passed originally.
**BANKED ONCE. NOT RERUN.**

### AD.8 Non-blocking observation, deliberately not investigated
The log line *"iteration ended without ever training; … 5 time-gated"* sits
beside a completed `Epoch 0`, a real `final_loss`, a `training_history` and a
produced deliverable. Provisional class: **observability / per-attempt
accounting inconsistency**. Neither frozen row depends on it. Not on the
critical path; reopen only if source shows a real lifecycle defect.

> **SUPERSEDED by §AE.1** — the 5-minute audit was subsequently run and the
> provisional class was WRONG in one respect that matters: this is not a
> display-only line. Its disposition is now recorded in the family ledger.

---

## AE. FAMILY FOLLOW-UP LEDGER

**Governing rule (operator, 2026-08-25):**

```
A FINDING MAY LEAVE THE CRITICAL PATH, BUT IT MAY NOT LEAVE THE LEDGER.
```

`NON-BLOCKING` means **tracked debt with deferred sequencing**. It never means
waived. Allowed final states: `FIXED` · `RECLASSIFIED / NOT A DEFECT` ·
`SUPERSEDED WITH EVIDENCE` · explicitly `ACCEPTED LIMITATION` with rationale
and owner. Not allowed: *"non-blocking, forgotten."*

### AE.1 `F-C12P-OBS-1` — advisory-feedback observability bug

| field | value |
|---|---|
| **identifier** | `F-C12P-OBS-1` |
| **class** | ADVISORY-FEEDBACK OBSERVABILITY BUG (not logging-only) |
| **evidence** | witness `c12p_j_smoke_a5` @ `b7b08586`: prose claims the iteration ended *"without ever training"* while attempt 6 genuinely trained 125 optimizer steps and then failed HealthGate with `failed_mode_collapse` |
| **mechanism** | emitted at `nodes/ml_hyperparameter_tune_agent/records.py:918-925`, driven by `_build_gate_exhaustion` (`feedback.py:249`). The predicate is **iteration-wide** — *"no record has `status == "success"`"* over `records=all_records`. It is therefore TRUE for a trained-then-invalidated attempt, while the rendered prose says training never occurred |
| **owner** | proposal / feedback observability surface |
| **affected authority** | `_build_gate_exhaustion` predicate ↔ its rendered prose |
| **blast radius** | sole non-display consumer is `_format_recent_gate_exhaustions_block`, which injects it into the **next proposal-agent prompt** → can misdirect LLM recovery reasoning |
| **does NOT control** | `record.status` · artifact validity · provenance · downstream routing · §J row-4/row-5 mechanics |
| **blocking for C12-P core** | **NO** |
| **reason deferred** | source-disjoint from every C12-P core authority; repairing it inside the core candidate would widen the write set for zero semantic gain |
| **required closure point** | **BEFORE the final G12e live graduation witness** |
| **allowed sequencing** | off-critical-path parallel repair if the minimal fix is source-disjoint and small |
| **required falsifier** | at least one attempt genuinely trains **and** no attempt reaches `status == "success"` ⇒ feedback MUST NOT claim training never occurred. The genuine zero-training case must remain correctly reported |
| **preferred correction** | distinguish *no successful training outcome* from *no training occurred*. Do **not** rewrite prose without testing the trained-but-failed case |
| **scope guard** | do NOT broaden into general logging cleanup |
| **final disposition** | **FIXED** — `a59e3a1e`. Predicate/prose reconciled; the trained-but-failed and genuine-no-training cases are both under test. Blocking for G12e launch is DISCHARGED. |

### AE.2 `F-C12P-CP12-1` — warm cache can define composition authority

| field | value |
|---|---|
| **identifier** | `F-C12P-CP12-1` |
| **class** | pre-existing health/composition debt |
| **evidence** | Test-Infra audit packet, evidence HEAD `216920fa` (consume **READ-ONLY**; do not merge or cherry-pick Test Infra to read it) |
| **mechanism** | BIND #1 = framework/default health configuration, **empty** plugin set; BIND #2 = composed Pets task, **one** plugin; the run-scope binding refuses the mismatch. A **warm** process masks BIND #1 through `_CACHED_GATES` (`execute_tools/health_checks/config.py:397-403` short-circuits before composition and discards `_plugins`), while a **cold** process executes it |
| **consequence** | cache state can change observable composition binding |
| **hard invariant owed** | cold-process composition semantics **==** warm-cache composition semantics. The cache may optimize; it may **not** define composition authority |
| **owner** | C12-P family (product repair). Test Infra owns the **diagnostic evidence only** |
| **blocking for C12-P core** | **NO** — does not block §J and does not block core landing |
| **classification** | `FAMILY_FOLLOWUP_BEFORE_TEST-INFRA_AUTHORITY` |
| **required closure point** | **MUST close before Test Infra's new sharded harness becomes authoritative** |
| **minimum validation** | zero dataset · zero training · zero GPU · zero LLM · deterministic process tests |
| **final disposition** | OPEN |

### AE.3 `F-C12P-CP13-1` — baseline reuse enforces existence, not compatibility

| field | value |
|---|---|
| **identifier** | `F-C12P-CP13-1` |
| **class** | framework provenance / enforcement defect |
| **evidence** | `scripts/run_comparison.py:1396-1410` reuses a baseline by EXISTENCE alone (`if history: baseline_record = history[0]`). CP-13's read-only comparison proved the *actual* reused artifact was compatible — `wavenet == wavenet`, baseline `file_index=6` vs `resolved_data_scope=[6]`, `health_config_sha256` byte-identical `39e13e2d…a5cd426`, `health_gate_enabled True == True`, `mode formal == formal` ⇒ **CASE A** |
| **the defect that remains** | compatibility was *provable*, not *enforced*. Production skips retraining without checking it |
| **must not be erased by** | "the current artifact happened to match." CASE A validates the §J witness; it does not close the enforcement gap |
| **owner** | C12-P family / baseline-reuse provenance surface |
| **blocking for C12-P core** | **NO** — the §J witness remains authoritative; do NOT retrain, do NOT rerun §J |
| **required closure point** | explicit closure point owed; to be set with the operator when the enforcement surface is next opened |
| **final disposition** | OPEN |

### AE.4 `F-C12P-12BC-1` — a 12bc guard pinned prose and is now anchored by accident

| field | value |
|---|---|
| **identifier** | `F-C12P-12BC-1` |
| **class** | structural-guard fragility (census "matches a token exactly" shape) |
| **evidence** | `tests/unit/guardrails/test_step12_pr12bc_f_checkpoint.py:163-166` computes `guard = src.index("tidmad_topology(profile)")` and asserts `"measurement SKIPPED" in src[guard:guard+600]` |
| **mechanism** | C12-P's B1 fix introduced `declares_tidmad_topology(profile)` at `evaluate_time_skill/wrapper.py:359`, whose text **contains** the searched substring. `src.index` therefore now anchors on the **membership test**, not on the raising `tidmad_topology(profile)` call at `:366`; and the named reason at `:361` reads `NOT APPLICABLE` under C12-P's operator-frozen NOT_APPLICABLE taxonomy, not the pinned `measurement SKIPPED` |
| **why this is an UPGRADE, not a weakening** | the guard's real safety property is `guard < build` (the refusal precedes the construction it protects) and that still holds. The pinned sentence was a witness for *"skips with a named reason"*, not itself a safety control. Left as-is the guard is ALSO fragile in the dangerous direction: removing the membership test would silently slide the window to `:366` and it could pass for the wrong reason |
| **owner** | C12-P core (the PR that changed the vocabulary owns the guard's re-anchoring) |
| **blocking for C12-P core** | **YES** — it is one of the failures at the core candidate and must be green before freeze |
| **required closure point** | before `C12P_CORE_CANDIDATE_SHA` |
| **final disposition** | **FIXED** — first site `4e25e0c9`, SECOND site `43373031` (see §AE.11). Both re-anchored, mutation-proven in both directions. |

### AE.5 `F-C12P-B11-2` — B11's omit-the-key repair regressed runs that omit the key

| field | value |
|---|---|
| **identifier** | `F-C12P-B11-2` |
| **class** | regression introduced by C12-P, against landed master |
| **evidence** | `tests/unit/workflows/test_step12_pr12a_c7_prompt_science.py`: pristine master `84d74280` **13 passed**; core candidate **2 failed**. Reproduced in core alone, so not the child's |
| **mechanism** | B11 removed the framework's `10000` literal so an omitted `segmentation_size` stays omitted and `tidmad_data_path` refuses it. The refusal is CORRECT and fires. But the key is legitimately optional (`agent/schemas/proposal.py:1247` — *"some architectures don't have one"*), so a run whose plan omits it now dies at scope construction on **every** attempt, exhausts the round, and never reaches the reflector |
| **why the two failing tests look unrelated** | they fail TRANSITIVELY — the run dies before rendering. Not a prompt defect |
| **proposed repair** | branch `c12p-b11-regression-fix` @ `686abada`. Resolve through the ONE authority (`resolve_model_field`, order: supplied → config-class default → margin), with `safety_margin=0` as the "nothing declares this" sentinel and `or None` restoring absence — so the task's refusal stays REACHABLE for a model that genuinely declares nothing. `model_type` hoisted, not duplicated; B11's "model type not known yet" objection was an ordering artifact |
| **what it costs** | retires `test_the_task_gets_to_refuse_an_undeclared_seg_size` and `test_an_omitted_size_is_not_validated_as_10000`, which encode the omit-the-key design. The first says so itself: *"if C12-P instead resolves through `resolve_model_field` this test must be retired by an **explicit decision** rather than by drift"* |
| **blocking for C12-P core** | **YES** — the candidate is not publishable while a landed test that passed on master fails |
| **final disposition** | **FIXED** — operator ruling 2026-08-25 approved the resolver chain; repair merged at `e2c393b8`, rulings applied at `44343808`, boundary extracted at `e3aef91d`. Three regimes green, mutation-proven both ways. |

### AE.6 `F-C12P-METHOD-1` — symbol-grep cannot see transitive blast radius

| field | value |
|---|---|
| **identifier** | `F-C12P-METHOD-1` |
| **class** | validation-method limitation (process, not code) |
| **evidence** | `F-C12P-B11-2` was missed by an affected-surface set derived by grepping the touched symbols. The regressed file names neither `segmentation_size` nor `prepare_attempt`; it fails only because a run *dies* upstream |
| **why it matters here** | grep-derived affected-surface selection was used by every implementation lane in this family, and is the method the validation-economy rule leans on to avoid full-suite runs |
| **mitigation** | when a change can make a RUN FAIL rather than compute a different value, the affected set must include the end-to-end run/workflow tests, which no symbol grep will reach. Cheap proxy: `tests/unit/workflows/` whenever the tuner lifecycle is touched |
| **owner** | C12-P family (method), carried into Step-12 practice |
| **blocking** | NO |
| **final disposition** | OPEN — promoted to a BINDING impact-selection rule (§AE.9/§AE.10, three sibling incidents recorded). No new design cycle. |

### AE.7 Operator rulings 2026-08-25, and the dispositions they produced

**Ruling 1 / 1A / 1C — `F-C12P-B11-2` APPROVED.** The authority chain is
`explicit plan value -> resolve_model_field(...) -> legitimate absence`. B11
must NOT restore the framework-level `10000`. **A proposal omitting the key does
not mean the model has no declared segmentation geometry — that distinction is
load-bearing.** `safety_margin=0` is acceptable ONLY as an internal
no-authority-declared sentinel and must never escape as a real
`segmentation_size`, runtime identity, fingerprint, argv or persisted semantic
value; proved in
`tests/unit/core/test_c12p_b11_2_zero_sentinel_never_escapes.py`. The two
reserved tests are **reworked, not deleted** — the refusal assertion is intact
and only the state reaching it changed. `F-C12P-B11-2` → **FIXED**.

> **A correction this produced.** B11's comments justify the `0` sentinel by
> saying *"the request side declares `Field(gt=0)`"*. That is **not true of
> `ProbeRequest`**, whose `workload` is an unconstrained `dict[str, Any]`. The
> constraint is real but lives one layer on (`estimate_types.py:222`,
> `gpu_measurement_data.py:54`). The sentinel is safe for the stated reason at a
> **different boundary than the comment names**, and the probe sites' actual
> protection is unreachability, not that constraint.

**Ruling 2 — `PRE_C7_SHA` is IMMUTABLE.** It is historical pre-C7 evidence and
P1-B must not rewrite history. No silent temporal repin, and no overloading of
that name with a post-P1-B meaning. If current validation needs a
post-P1-B/current-candidate authority it must be a NEW, explicitly named
reference, or derived mechanically from the actual parent. If mechanical
inspection proves the constant is merely an ephemeral fixture rather than
historical evidence, it must be **renamed to its true semantics first** and only
then updated. **Open, owned by the child.**

**Ruling 3 — the `xfail(strict=True)` conversion is VETOED and REVERTED.** The
preferred terminal state for current required behaviour is **PASS**, and a
strict xfail may not turn a newly exposed regression into an accepted result.

> Reverting to the hard RED was not the answer either: the universal it asserted
> — *no authored default survives anywhere* — **is not true of this
> repository**. Both surviving sites are in `ml_model_implementor`, which runs
> BEFORE the model exists, so `get_config_class` returns `None` by construction,
> nothing is being overridden, and the literal is a genuine fallback (routing it
> through the authority is a provable no-op — same value in, same value out).
> The test now asserts the rule that IS true: *every surviving default lives
> where no declaration can exist*, paired with a reachability test proving that
> premise so the exemption cannot decay into a rationalisation.
> `F-C12P-12BC-1`-style prose-pinning avoided; terminal state **PASS**.

**Ruling 6 — impact-selection rule, now binding.** `F-C12P-METHOD-1` is
promoted from observation to rule:

```text
if a semantic change can affect
    run reachability · admission/refusal · stage transition ·
    fallback behaviour · absence/default behaviour
then test-impact selection MUST include the workflow / control-flow surface.
```

Symbol-grep over the changed identifier is **not sufficient** for deletion and
absence semantics — those require behaviour-based dependency reasoning, because
the regressed test need not contain the changed symbol at all. Cheap standing
proxy: include `tests/unit/workflows/` whenever the tuner lifecycle is touched.
**No new dependency analyzer is to be built on the critical path.**

**Ruling 7 — banked evidence stays banked.** §J rows 4/5, CP-13 CASE A, B5+B6,
B7 and the `F-C12P-12BC-1` evidence are **not** invalidated by the discovery of
an omitted workflow regression; each has independent evidence. Only evidence
whose semantic dependency intersects the B11 repair is rerun. What IS
invalidated is any stronger claim that the grep-derived surfaces were
*complete*.

**Ruling 8 — `F-C12P-OBS-1` banked as FIXED**, conditional on the deterministic
trained-but-unsuccessful and genuine-no-training cases being green (297 passed /
0 failed on its affected surface). This clears the known advisory-feedback
blocker for G12e once the fix is present in the exact final run tree.

### AE.8 `F-C12P-ENV-1` — a test assumes `.venv` exists inside its own checkout

| field | value |
|---|---|
| **identifier** | `F-C12P-ENV-1` |
| **class** | portability (CLAUDE.md "Repository and Environment Portability") |
| **evidence** | `tests/unit/scripts/test_sdsc_argument_forwarding.py::TestPythonIsTheSingleValidator::test_an_unknown_flag_fails_the_runner_loudly` fails with `FileNotFoundError: '<checkout>/.venv/bin/python'` when run from a **git worktree**. Reproduced identically on **pristine master `84d74280`**, so it is NOT a C12-P regression |
| **mechanism** | the interpreter path is derived from the checkout root. A worktree has no `.venv` of its own — only the main checkout does — so the path resolves to something that does not exist |
| **why it matters** | CLAUDE.md requires that executable paths come from configuration, environment or fixtures, and that a test declare and validate a machine-specific resource rather than assume it. This one assumes. It passes in the main checkout and fails in every worktree, which is the "local green says nothing" hazard that rule exists to prevent |
| **owner** | scripts / test-infrastructure |
| **blocking for C12-P core** | **NO** — pre-existing, environment-shaped, and unrelated to any C12-P authority |
| **required closure point** | when the SDSC runner surface is next opened, or with the Test-Infra harness work that owns runner invocation |
| **final disposition** | OPEN |

### AE.9 The EPOCH-TRANSITION MODEL — generalized by operator ruling, 2026-08-25

Ruling 2 produced a pattern that outlived its own question. It is recorded here
because three separate guards in this family hit the same failure mode, and the
next one will too.

**The failure mode.** A golden constant is captured from a historical commit to
prove that some past change was *behaviour-preserving*. It then keeps
constraining the CURRENT tree forever. That is correct only while nothing ever
intentionally changes those bytes — and it silently becomes a **temporal
overload** the moment a later PR legitimately does. The guard then reads as
"someone broke parity" when the truth is "a later, approved change happened".

**The model** — three parts, and the third is the one that matters:

```text
epoch-1 authority   IMMUTABLE. the recorded past. never silently repointed.
epoch-2 authority   SEPARATELY NAMED. derived MECHANICALLY from the parent —
                    apply the declared edit to epoch-1's bytes and verify the
                    result equals the hardcoded value. NEVER "whatever the
                    tree hashes to".
bridge assertion    enumerates the permitted delta as (post, pre) pairs, and
                    asserts that REVERSING the declared edit lands back on
                    epoch-1's digest.
```

**Why the bridge is not optional.** Each sha alone is individually satisfiable
by *any* bytes. Only the bridge distinguishes "the recorded past plus exactly
one declared change" from "something else entirely". Proven, not argued: a
mutation planting an **undeclared edit together with a silently repointed
epoch-2 pin** is ABSORBED by the epoch-2 pin and caught ONLY by the bridge.

**A bare "re-freeze the golden to the new bytes" is forbidden silent repin** —
even when the guard's own failure message suggests it, as
`test_step12_pr12a_c0_legacy_parity.py`'s does. That instruction predates the
possibility of a legitimate change and is not satisfiable once one occurs.

**Applied in this family to**: `PRE_C7_SHA` (`03ed8e73`), `PROMPT_SOURCE_SHA`,
the PB3 / P3-C0 prompt baselines, and the two `tier_ii_*` shape-column tests.

#### AE.9a The `tier_ii_*` boundary, ruled explicitly

These are NOT sha constants, and the operator drew the line precisely. The
surviving invariant is **not** *"the old TIDMAD-specific `[B,256,T]` bytes must
remain forever."* It is:

> the relevant shape/proposal guidance remains **explicit / static** prompt
> content, and P1-B does **not** introduce a new **dynamic task-specific
> injection channel**.

Forbidden: restoring `[B,256,T]` · introducing dynamic shape injection ·
removing the structural assertion · silently repinning historical authority.

**Both halves verified mechanically** (`git show bca52bca^:<file>` vs
`bca52bca:<file>`), not asserted:

- P1-B's ENTIRE template delta is **3 lines** — `:41`, `:70`, `:71` — replacing
  `[B, 256, T]` / `[B, T]` with static prose ("a per-class score axis",
  "continuous values") plus a static pointer to the forward contract.
- **Zero new substitution tokens.** `{CLASSIFIER_LOSS_LIST}`,
  `{REGRESSOR_LOSS_LIST}`, `{OUTPUT_CONTRACT_GUIDANCE}` byte-unchanged.
- **`{forward_contract}` sits at line 130 and PRE-DATES P1-B**, untouched by it.

So P1-B removed a hardcoded literal that **duplicated an already-rendered
section**, and replaced it with static text. It did not create a channel; it
stopped restating what the existing one already carried. An earlier phrasing of
mine — *"now sourced from `{forward_contract}`"* — was imprecise in exactly the
way the ruling guards against, and is corrected here.

### AE.10 `F-C12P-METHOD-1` — three sibling incidents, one root cause

Recorded under the EXISTING finding per operator instruction; **no new design
cycle**. All three are the same failure: a scan narrower than the failure set,
reported as if complete.

| # | incident | how it was missed | cost |
|---|---|---|---|
| 1 | `F-C12P-B11-2` — removing a value killed the run | affected-surface set derived by **symbol grep**; the regressed workflow test names no touched symbol and fails only transitively | a candidate reported validated while a landed test that passed on master was red |
| 2 | **P1-B's own commit message undercounted** — reported "two other tests red" when there were **six**; `03ed8e73` repeated the figure | the count came from a **narrower scan than the failure set** | two sessions reasoned from a wrong blast radius |
| 3 | **`F-C12P-12BC-1` second site** — two more guards pinned the retired prose | `tests/unit/execute_tools/` was in **neither** the core packet nor the combined run; and a `grep` for the retired string **did surface the file**, which was then dismissed by register name without reading it | **both candidates were published as qualified while red** |

**Incident 3 is the sharpest, and the lesson is not "grep harder".** The census
was RUN and its output was READ. It was dismissed because the filename said
`b7_satellites` and C12-P's B7 is a different register from PR-12bc's B7 — a
true fact used to answer a question it does not answer. *A census one runs and
then explains away is worse than one never run, because it manufactures
confidence.*

**Standing consequences** (rules, not aspirations):

```text
1. a hand-chosen test-tree set is a CLAIM about blast radius; state which
   directories were NOT covered whenever reporting a qualification
2. when a change is guarded by a structural/census test, run the census's OWN
   directory -- guards for a change do not live near the change
3. a census hit is dismissed only after READING the site, never on the
   strength of its filename or register
```

Both packets in this family omitted `tests/unit/execute_tools/`, which is where
the scope ABI and the `evaluate_time_skill` satellites live — the same
directory F-12bc-9 had already been burned by, for the same reason.

### AE.11 `F-C12P-12BC-1` second site — closed, and a structural lesson

`tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py` carried **two**
defects, and only the first is the prose one:

1. **Pinned prose** — both tests asserted the retired sentence
   `"measurement SKIPPED"`. Fixed as at the first site: accept either spelling
   through one shared tuple, because the safety control is *declining with a
   named reason*, never the English used.
2. **A fixed-size window** — `test_it_guards_the_tidmad_geometry_before_using_it`
   sliced **2000 characters backwards** from the geometry use and asserted three
   strings landed inside it. C12-P's B1 fix **hoisted** the membership refusal
   above the broad `except Exception` — deliberately, so a malformed TIDMAD
   declaration stays loud instead of being swallowed — which moved the refusal
   out of that window **while making the guard stronger**. The test went red for
   a change that improved exactly what it protects.

**A byte-distance is not an invariant.** The guard now asserts ORDERING —
`membership < use`, and `named refusal < use` — which is what "guards the
geometry *before* using it" always meant. Mutation-proven: strip the named
reason ⇒ 3 RED; delete the membership test ⇒ 2 RED; restore ⇒ 39 passed,
byte-identical.

**Ownership note**: the fix belongs to **CORE**, not the child, because it
guards a core production change (`evaluate_time_skill/wrapper.py`, B1). It was
first committed child-side and relocated once that was noticed — otherwise core
would have landed red between the two landings, with the child carrying the fix
for core's own defect.

### AE.12 CANDIDATE LINEAGE — two heads RETIRED after a qualification gap

Operator ruling, 2026-08-25. Recorded so the retired SHAs are never mistaken
for authoritative, and so the reason is legible without reading this whole
document.

```text
RETIRED_AFTER_QUALIFICATION_GAP / INVALIDATED_BY_ATTRIBUTABLE_REGRESSION
  CORE      2ebe87ef3dd68f5a9e459d526567bfa6e93656b5
  COMBINED  d4e09b27ee890a911cce273fbdb355979bff5b93

AUTHORITATIVE
  C12P_CORE_CANDIDATE_SHA      43373031c2f662ce0670bcc605a8d2a2952ba185
  C12PP_COMBINED_CANDIDATE_SHA 4b0973cd59a7454a64d51e773dafafad131e9b95
```

**Their history is NOT rewritten.** They remain reachable and are part of the
record; they are simply not authoritative.

**Why this is not post-freeze scope expansion.** The freeze was *conditional*
on a stated qualification: *zero C12-P/C12-P-P-attributable failures*. That
premise was later disproven — the supplemental pass over
`tests/unit/execute_tools/` found **two attributable failures on both heads**
(`test_step12_pr12bc_b7_satellites.py`, the second `F-C12P-12BC-1` site).
Preserving a SHA as authoritative *because it had once been called frozen*,
after its precondition was shown false, would elevate a label over the evidence
the label was supposed to summarise. This is correction of a false
qualification claim, not discretionary reopening.

**The repair is bounded and validated**: `execute_tools/` +
`evaluate_vram_skill/` + `protocols/` ⇒ 2678 passed / 2 skipped / **0 failed**;
child surface 923 passed; ruff clean. Delta from the retired combined head is
exactly two files — the guard fix and this document.

**Not CP-12.** This correction is unrelated to `F-C12P-CP12-1`, which remains
**OPEN** and owned, with its closure required before Test Infra's sharded
harness becomes authoritative. Nothing here may be read as closing it.

### AE.13 `F-C12P-CONT-1` — a stop hook resolved another lane's handoff

| field | value |
|---|---|
| **identifier** | `F-C12P-CONT-1` |
| **class** | continuity infrastructure (non-blocking) |
| **evidence** | this session (C12-P family, working in `siderius-c12p-*` worktrees) was blocked by `stop_continuation_guard.py` presenting next actions belonging to a DIFFERENT live PR: `PROJECT / PR: Test Infra — CI Parity & Hermetic Test Harness`, `IMPLEMENTATION BRANCH: infra/ci-parity-hermetic-harness`, `CONTEXT STATE: ACTIVE`. Its objectives (`CP12_RESOLUTION_SHA`, "the local workflow candidate", "eight GitHub-only objectives") are that lane's, not C12-P's |
| **mechanism** | the guard resolves `before_end_memory.md` from the **main checkout**, which is checked out on another PR's branch, while this session's work lives in sibling worktrees. Handoff identity is resolved by location, not by the session's actual working set |
| **why it matters** | the hook's own escape hatch instructs the blocked session to *write* that file. Following it would have overwritten a live lane's continuity record. The correct response was to refuse — but the refusal has to be reasoned out each time rather than being structural |
| **owner** | continuity hooks (`tools/claude_hooks`) |
| **blocking** | NO — it did not prevent required continuation, only delayed it |
| **required closure point** | when the continuity-hook surface is next opened |
| **final disposition** | OPEN |

### AE.14 Ledger status at the landing head

Synced as part of the pre-landing audit, because a ledger whose dispositions
lag the tree is the same failure this family kept hitting one level up: a
summary trusted in place of the evidence it summarises.

| finding | disposition |
|---|---|
| `F-C12P-OBS-1` | **FIXED** — `a59e3a1e` |
| `F-C12P-B11-2` | **FIXED** — `e2c393b8` / `44343808` / `e3aef91d` |
| `F-C12P-12BC-1` | **FIXED** — both sites, `4e25e0c9` + `43373031` |
| `F-C12P-CP12-1` | **OPEN** — C12-P family owns it; separate lane `c12p-cp12-followup`; closure required before Test Infra's sharded harness becomes authoritative. **NOT closed by this PR.** |
| `F-C12P-CP13-1` | **OPEN** — baseline reuse enforces existence, not compatibility |
| `F-C12P-METHOD-1` | **OPEN** — promoted to a binding impact-selection rule; three sibling incidents recorded |
| `F-C12P-ENV-1` | **OPEN** — base-reproduced, routed to scripts/test-infra |
| `F-C12P-CONT-1` | **OPEN** — continuity hooks |

Three FIXED, five OPEN, **zero waived**.

### AE.15 `F-C12P-GPU-1` — five tests silently required a CUDA host, and two were vacuous because of it

Found by the FIRST canonical CI run of #295/#296, which is exactly where a
GPU-dev-box blind spot should be found and exactly what local green could not
tell us.

| field | value |
|---|---|
| **identifier** | `F-C12P-GPU-1` |
| **class** | portability (CLAUDE.md "Repository and Environment Portability") — **attributable to C12-P**, not pre-existing |
| **evidence** | CI: `5 failed, 13027 passed`, captured stdout `[runtime_control] calibration derivation failed (non-fatal): hardware profile collection requires CUDA`. Reproduced locally and exactly with `CUDA_VISIBLE_DEVICES=""` ⇒ the same 5 |
| **mechanism** | `probe_production.py:46-47` raises `RuntimeError` when `torch.cuda.is_available()` is false. Four tests reach it through `_derive_calibration_from_observation`; the fifth hits a DIFFERENT accelerator gate (`evaluate_time_skill/wrapper.py:333`) sitting ahead of the membership test — same class, different site |
| **why local green meant nothing** | this dev box has GPUs; CI runners do not. The tests passed because of the machine, not the code — the precise hazard the portability rule names |
| **repair** | MOCKED, not skipped (`tests/helpers/hardware_profile_stub.py`, class-autouse). A skip would make these vacuous on exactly the machine CI runs, silently retiring the B5/B6 and B1 guards this PR exists to establish |

**The part that matters more than the red.** The crash was not only failing
tests — it was making NEGATIVE tests pass **for the wrong reason**. With the B5
defect planted on a CPU host,
`test_a_composed_foreign_task_exports_no_tidmad_labelled_calibration` **PASSED**:
its registry was empty because the probe crashed, not because the guard refused.
Same for `test_absent_identity_still_fails_closed_to_quarantine`. **Two tests
were decoration on CI while reporting green** — which is why the fixtures cover
the whole class, not only the three that were red.

**And a third, found while fixing them.**
`test_a_foreign_profile_is_skipped_without_an_exception_handler` — the declared
*other half* of B1's biconditional — passed `data_dir="/nonexistent"`, returning
at `wrapper.py:325` before the membership test at `:359` ever ran. Its
assertions are what that guard returns for **any** profile, so it would have
stayed green with the foreign refusal deleted outright, on CPU **and** GPU. It
is the identical defect its sibling's docstring records as defect (1) — fixed
there with a real directory, never fixed here. **A biconditional with a vacuous
half is not a biconditional.** Now uses a real directory and asserts the ROUTE
TAKEN; proven by plant (deleting the refusal turns it RED, where before it did
not).

**Sibling of `F-C12P-METHOD-1`**: three incidents there were scans narrower than
the failure set; this is the same shape in the ENVIRONMENT dimension — a host
capability standing in for coverage.

| **final disposition** | **FIXED** — `bc120c24` (mock) + `be408048` (de-vacuified biconditional) |
