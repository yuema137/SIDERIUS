# Step 05b — Tuner resource & time planning — detailed design

Part of **Step 05** (roadmap §15 step 5, §7d). Step 05's three submodule
designs jointly constitute the Step-05 acceptance entry (roadmap §19); the
Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **IMPLEMENTED — PR #211 OPEN, READY FOR OPERATOR REVIEW. NOT MERGED.** Semantic design content frozen at **`ce88012450b312fff6cee65ebfc7dff3220f4e68`** (revision 3); implemented from the freeze marker **`aa7e2131`** on branch `feat/generic-framework-step-05b-tuner-resource-time`. All nine semantic milestones C0-C8 complete; Checkpoints 0/A/B/C/D complete; Gate 1 and Gate 2 both **NOT REQUIRED**, each decided from recorded evidence (§18.2h). Live ledger: §18. |
| Frozen design content | **`ce880124`** — verified from Git at freeze time, not from a working copy. A stale external copy showing revision 2 exists; **repository truth at `ce880124` is authoritative** |
| Design base | **re-anchored to `82a548f8`** (master after 05a merged as `cfb3b1c7`). Revision 1 was written against `13b08550`; every source citation below has been re-verified and moved where it moved (§0.3) |
| Depends on | **Step 02** (Dataset Profile) · **Step 03** (`ModelIOContract`) · **Step 04a** (`model_io_probe_skill`, the shared probe-realization authority) |
| Blocks | nothing — see §7 |
| Roadmap row | §15.1 `§7d Tuner resource/time planning` |
| Decomposition | **ONE PR**, two internal capability phases (P = C1-C4, D = C5), nine semantic commits C0-C8 (§16). Re-tested at revision 3 — see §0.4. No child design doc |
| Operator decisions | **OD-05b-1** probe scope = additive parameterization of the 04a realizer (§0.2) · **OD-05b-2** re-anchor citations to current master (§0.3) · **OD-05b-3** ONE PR, two internal phases (§0.4) · **OD-05b-4** output-form authority inherited from Step 04a (§0.5) · **OD-05b-5** semantic run-bound contract transport, route chosen at C4 · **OD-05b-6** Stage-B = one rung, two subcases (§8) · **OD-05b-7** calibration preservation audit, not a pin campaign (C6) |

> **Revision 2 exists because revision 1's central claim did not survive
> source audit** (§0.2). **Revision 3 corrects four authority errors revision 2
> introduced** — output-form ownership (§0.5), contract acquisition (C4),
> Stage-B coverage (§8), and calibration evidence scope (C6) — and removes
> design wording that would have paused an authorized implementation session
> (§11, §16.1, §16.2). Read §0.2-§0.5 before §1.

### Freeze record

| Field | Value |
|---|---|
| Frozen semantic design content SHA | **`ce88012450b312fff6cee65ebfc7dff3220f4e68`** |
| Design base | **`82a548f8`** |
| Freeze date | **2026-08-14** |
| Decomposition | **ONE PR** |
| Internal capability phases | **Phase P** — `ModelIOContract` / probe realization / VRAM path (C1-C4) · **Phase D** — `DatasetProfile` / workload-time derivation (C5) |
| Remaining operator decisions | **NONE** (OD-05b-1 … OD-05b-7, §19) |

**Design freeze does NOT begin implementation.** Implementation authorization
is supplied separately, in a fresh implementation context with its own filled
Implementation Working Rules contract.

**What the freeze covers.** The semantic contract: §0.4 decomposition · §0.5
output-form authority · §1 capability · §2 classification · §8's one rung and
its two atomic subcases · §9's Checkpoint-C property · §11's Gate disposition
and its semantic condition · §15 stop conditions · §17 Definition of Done ·
§20 configuration-architecture preservation.

**What remains unfrozen engineering detail**, subject to that contract: exact
Git commit count · helper structure · source line numbers · test-file
decomposition · exact mutation implementation · **the exact transport
mechanics chosen at C4** · resolver/realizer call counts.

---

## 0. Source audit — what changed since the roadmap wrote §7d

Two findings materially re-scope this PR, one shrinking it and one giving it
a consumer the roadmap could not have predicted.

> **The two blocks below are revision 1's evidence, at base `13b08550`, kept
> unedited so the audit chronology survives.** Several of their line numbers
> are stale at `82a548f8`; **§0.3 is the corrected anchor table** and is what
> implementation should read. Do not act on the numbers inside these blocks.

```text
Previous assumption (roadmap §7d):
  "Couplings: ×256 logits/one-hot terms; PSD-unit
   `PSD_SEGMENT_LENGTH // seg_size` in 5+ places; seg defaults 40000/1000."

Audit evidence at 13b08550:
  The PSD-unit term is ALREADY derived from the Dataset Profile:
    execute_tools/workload_resolvers.py:36,49,139  -> resolve_dataset_profile()
    agent/skills/evaluate_time_skill/wrapper.py:65,92,357,767 -> same
  It is derived, but AMBIENTLY: the shape is
  `profile = profile or resolve_dataset_profile()`, an optional parameter
  with a singleton fallback — the same defect shape Step 02b removed from
  tuner selection.

  The `40_000` seg fallbacks are NOT mainly §7d's: they live in
    core/runtime_control/gpu_measurement_identity.py:214
    core/runtime_control/gpu_measurement_worker_main.py:254
    core/runtime_control/probe_production.py:220
    core/runtime_control/campaign.py (fixture roster)
  i.e. §7e measurement/verification — assigned to STEP 07, not Step 05.

Corrected understanding:
  §7d's PSD-unit work is largely done; what remains is converting ambient
  fallback into required injection. The seg-fallback item is an AUDIT
  obligation here and a FIX obligation mostly in Step 07.
```

```text
New evidence the roadmap could not have (Step 04a landed after it):
  Step 04a created agent/skills/model_io_probe_skill.py — ONE shared
  probe-realization authority (`build_model_input`, `build_loss_probe_pair`,
  `realize_shape`, `expected_output_shape`).

  Its production consumers today are exactly TWO:
    nodes/ml_model_implementor/ml_model_implementor.py:1840, :1995
    nodes/ml_code_validator_agent/ml_code_validator_agent.py:646
  and both receive the contract as an OPTIONAL parameter
  (`model_io_contract: ModelIOContract | None = None`) with a documented
  legacy fallback when it is absent.

  The LIVE VRAM probe does NOT use it and still builds TIDMAD-shaped
  tensors inline:
    agent/skills/evaluate_vram_skill/wrapper.py:248
        tgt = torch.zeros((batch_size, 256, seg_size), dtype=target_dtype)
    plus [B, 256, T] reasoning at :90, :196-205, :236 and
    batch_resolver.py:85.

Implementation consequence:
  05b's strongest capability is making the live resource gate the THIRD
  consumer of the existing probe authority.
```

### 0.2 What revision 1 got wrong — and the operator decision that resolves it

Revision 1 closed the passage above with *"This is not a new seam — the
authority exists, is proven by 04a's ladder, and this PR supplies a real
production consumer for it."* **Source audit at `82a548f8` refutes that on
two counts.** Both were found before any implementation planning, which is
why they change the design rather than surfacing mid-PR.

```text
Previous assumption (rev 1 §0):
  the VRAM gate can simply CALL the 04a authority; no new seam is needed.

Audit evidence at 82a548f8:

  (1) The 04a authority realizes at VALIDATION-PROBE extents, not at the
      candidate's extents. `realize_shape` is unparameterized
      (model_io_probe_skill.py:109-140):
          batch-role axis   -> PROBE_BATCH            = 1     (:68)
          symbolic/dynamic  -> PROBE_SYMBOLIC_EXTENT  = 64    (:75)
      and `build_loss_probe_pair` uses LOSS_PROBE_BATCH = 2 (:293),
      LOSS_PROBE_LENGTH = 100 (:294).
      The VRAM gate must build its target at the candidate's REAL
      batch_size and seg_size — that is the entire content of a capacity
      measurement. So `build_model_input` / `build_loss_probe_pair` cannot
      be consumed verbatim by this path.

  (2) No ModelIOContract reaches the VRAM gate today, and no plumbing
      exists to carry one. `evaluate_vram_skill/wrapper.py` imports no
      model-io module at all (:40-74); it receives `model_type` and derives
      the target shape from `get_output_type(model_type)` (:229). The tuner
      input schema carries no contract either — `grep model_io` over
      agent/schemas/hyperparam_tuning.py returns nothing.

  (3) The production pre-flight runs in a CHILD PROCESS
      (`run_production_preflight`, preflight_adapter.py:212 -> IsolatedProbeSpec
      -> preflight_worker_main.py:190), so any contract must cross a process
      boundary as well as a function boundary.

Corrected understanding:
  the probe half of 05b is a real seam extension, not a call. It needs
  (a) a way to realize declared shapes at caller-supplied extents, and
  (b) a contract transport to the resource path, in-process and across the
  pre-flight worker boundary.
```

**Operator decision OD-05b-1 — option A, "parameterize the 04a realizer".**

```text
model_io_probe_skill.py   (Step-04a owned; change is ADDITIVE + DEFAULTED)
    realize_shape(tensor, *, batch=None, symbolic=None)

        omitted / None   -> the existing Step-04a recipe default
                            (PROBE_BATCH / PROBE_SYMBOLIC_EXTENT)
        positive int     -> the supplied runtime extent
        zero or negative -> typed failure in the module's existing idiom

evaluate_vram_skill/wrapper.py
    _build_probe_tensors(..., model_io_contract=None)
        contract present -> realize_shape(declared_output_tensor(contract,
                                              <candidate declared form>),
                                batch=batch_size, symbolic=seg_size)
        contract absent  -> today's [B, 256, T]      (unchanged)

transport: an explicit run-bound contract reaches BOTH the in-process
           wrapper and the isolated pre-flight child (§0.4, C3, C4)
```

**`None`-sensitivity is part of the contract, not an implementation detail.**
The override must be written against `None`, never against falsiness:
`PROBE_BATCH if batch is None else batch`. A `batch or PROBE_BATCH` idiom
would let `0` silently resolve to the legacy default and produce a capacity
number for a tensor nobody asked for — the exact silent-fallback shape this
design forbids everywhere else. Zero and negative extents fail closed; the
concrete exception type follows the module's existing idiom and is chosen at
implementation time, not frozen here.

**Output FORM is not this PR's to decide.** Step 04a already settled it, and
`declared_output_tensor`'s docstring states the rule verbatim: *"the
DECLARATION selects the form, and the CONTRACT supplies every fact inside
it."* The VRAM probe inherits that rule unchanged — see §0.5.

Rejected alternatives, recorded so the choice is auditable:

| Option | Why not |
|---|---|
| **B** — derive only the class extent, keep local tensor construction | leaves rank and axis order hardcoded in the resource path, i.e. a *second* shape-realization site. That is this design's own failure class 5 (§10) |
| **C** — drop the probe half; ship only the profile tightening | smallest and safest, but 05b would deliver no Model-I/O capability at all and §7d's `×256` coupling would stay open with no owner |

**Why the additive parameterization is safe.** Both new keyword arguments
default to the existing module constants, so every current call site
(`build_model_input`, `expected_output_shape`, and the two node consumers)
resolves the identical shape it resolves today. A defaulted keyword cannot
change an existing caller's behaviour, and C1's acceptance criteria pin that
as a byte-equality assertion rather than an argument.

**Precedent for the transport.** A file-based `ModelIOContract` transport
already exists for the training subprocess — `train_engine_sandbox.py:1249`
declares `--model_io_json` and loads it with `load_model_io_contract`
(`agent/schemas/model_io_contract.py:312`). C3 follows that established
pattern rather than inventing one, and the pre-flight worker already receives
its inputs as a JSON spec (`IsolatedProbeSpec`, isolated_probe.py:168-182),
so the addition is one optional field beside `model_config_payload`,
`train_config` and `loss_config`.

### 0.3 Citation re-anchoring (OD-05b-2)

Revision 1 cited `13b08550`. Every site has been re-verified at `82a548f8`:

| Rev-1 citation | Status at `82a548f8` |
|---|---|
| `workload_resolvers.py:36,49,139` ambient fallback | **corrected** — the fallbacks are `:49` (in `_validate_seg`) and `:139` (in `resolve_inference_workload`). `:36` is the import line, not a fallback |
| `workload_resolvers.py:129` PSD-unit | **corrected** — the PSD unit is computed at `:50`; `:157` uses `psd_segment_length` for output bytes |
| `evaluate_time_skill/wrapper.py:65,92,357,767` | **corrected** — ambient reads are at `:92`, `:357`, `:767`. There is no ambient read at `:65` |
| `evaluate_vram_skill/wrapper.py:248` target literal | **confirmed unchanged**; the enclosing helper is `_build_probe_tensors` (`:176`), called once at `:588` |
| `inference_skill/estimator.py:79` ratio | **confirmed unchanged**; its ambient fallback is `:208` |
| `compute_intensity.py:40` `_MAX_BATCH_TIMESTEPS` | **confirmed unchanged** |
| `trigger_policy.py:34` `SEG_SIZE_BOUNDS` | **confirmed unchanged** |
| `core/sandbox_executor.py:114` RSS caps | **moved to `:121`** (`_ROLE_DEFAULT_RSS_GB`) |
| `core/runtime_control/*` seg fallbacks | **confirmed**: `gpu_measurement_identity.py:214`, `gpu_measurement_worker_main.py:254`, `probe_production.py:220` |
| probe-skill consumers `implementor:38`, `validator:56` | **corrected** — those are import lines; the call sites are `implementor:1840,:1995` and `validator:646` |

Implementation must still re-enumerate (the 05a precedent: line numbers drift,
capabilities do not). These anchors are reading aids, not contracts.

### 0.4 Decomposition — re-tested at revision 2, still ONE PR

Revision 2 enlarged 05b's scope (an additive change to a Step-04a module plus
an IPC transport), so the one-PR decision was **re-tested rather than
inherited**. It holds.

05b has two internal capability **phases**, not two PRs:

| Phase | Chain | Commits |
|---|---|---|
| **Phase P** — probe realization | `ModelIOContract` → concrete capacity probe → live VRAM gate | C1-C4 |
| **Phase D** — workload topology | run-bound `DatasetProfile` → workload/time derivation | C5 |

They stay one PR because they jointly establish **one** Step-05b capability:

> every task-shaped term used by resource/time planning derives from the
> authority that already owns it, while calibration and runtime values remain
> unchanged.

| Dimension | Shared by P and D |
|---|---|
| completion criterion | the Step-05b capability above |
| compatibility surface | one TIDMAD forecast / admission parity oracle |
| consumer family | resource & time planning |
| production evidence | one Checkpoint-C family through the real gate |
| configuration contract | one config/replay invariant (§20) |

**Why a split would ship an incoherent state.** Landing Phase P alone leaves a
planner that is generic along the Model-I/O axis and ambient along the dataset
axis; landing Phase D alone gives the mirror image. Either half is a resource
planner that derives one task dimension correctly and silently prices the
other against whatever singleton happens to be resolved — which is precisely
the half-migrated architecture Step 02b and Step 05a exist to eliminate.

That the two phases are separately revertible is a **rollback** property
(§13), not a decomposition argument. Internal checkpoints and phases carry the
ordering; child PRs are not used.

### 0.5 Output-form authority — inherited from Step 04a, not re-decided here

An earlier draft of this design made *"the contract's canonical output
semantic disagrees with `get_output_type(model_type)`"* an unconditional STOP.
**That was wrong, and it contradicted a landed decision.**

```text
Audit evidence (agent/skills/model_io_probe_skill.py:142-211,
`declared_output_tensor` docstring, verbatim):

  "the DECLARATION selects the form, and the CONTRACT supplies every fact
   inside it."

  "A candidate may legitimately declare `regressor` under a categorical task
   contract; three plugins in the live corpus do exactly that, and they pass
   today. Deriving the form from the task contract instead would start
   rejecting them, which is a verdict change under TIDMAD and therefore a
   Stage-A parity break."
```

So the rule 05b **inherits, unchanged**:

```text
candidate/plugin declaration  (get_output_type(model_type), or its current
                               canonical equivalent)
    -> selects the output FORM: classifier / regressor / legacy-hybrid

ModelIOContract
    -> supplies the facts INSIDE that form: axes, axis order, fixed extents,
       class cardinality, dtype requirements
```

The VRAM probe realizes through `declared_output_tensor` + `realize_shape`
rather than building a second resolution table. A categorical task contract
with a `regressor` candidate is a **supported compatibility surface**, not a
conflict.

**Fail closed only when:**

- the selected candidate form needs a contract fact the contract does not
  carry (04a's own case: a `classifier` form under a continuous contract with
  no class axis → `ProbeConstructionError`);
- the form/contract combination is not representable;
- `ProbeConstructionError` — or the current typed equivalent — is raised;
- an explicit contract is **lost or malformed in transport**.

A canonical-semantic difference alone is **never** a stop condition.

## 1. Observable final capability

> The tuner's **resource and time forecasts derive their task-shaped terms**
> — class/logit extent, decomposition (PSD) unit, and probe tensor shapes —
> from the authorities that already own them, instead of from literals
> inlined in the estimators. **Calibration and runtime values keep their
> current owners and current values**, and remain separately identifiable as
> calibration rather than task configuration.

**The authority split is precise, and no single authority is a general
"resource semantics" owner:**

| Fact | Authority |
|---|---|
| model/probe tensor **realization** | Step-04a `model_io_probe_skill` — a probe-realization **consumer seam**, nothing more |
| Model-I/O facts (class extent, output shape, decode rule) | **Step-03 `ModelIOContract`** |
| PSD / decomposition topology | **Step-02 `DatasetProfile`** |
| resource **calibration** (ratios, caps, batch table, overheads) | the existing calibration/runtime authority — unchanged |
| hardware capacity and operator budgets | the existing runtime **Hardware Context** / operator authority — unchanged |

It is wrong to say resource terms derive "through `model_io_probe_skill`":
the skill *realizes probe tensors* from a contract. The contract facts come
from Step 03, the topology from Step 02, and the calibration and hardware
facts from neither.

**Honest scope of the probe half (rev 2).** 05b does not merely *call* the
04a authority — it **extends** it, additively, so that one realization
authority can serve both validation-probe extents and capacity-probe extents
(§0.2). The capability claim is therefore:

> the live resource gate realizes its probe target from the **declared
> Model-I/O contract** — rank, axis order and the class extent — at the
> **candidate's own** batch and segment extents, through the same
> realization authority the implementor and validator already use, instead
> of from a `[B, 256, T]` literal.

When no contract is supplied the gate builds exactly the tensor it builds
today. That is not a hedge: it is the **legacy no-contract compatibility
path** every Step-02/03/04 seam has kept, and it is what makes the change
provable by byte-equality rather than by argument.

*(Terminology: this design says **legacy no-contract path** and
**explicit-contract path**. Roadmap "Regime A / Regime B" is reserved for the
Step-12 task-composition binding model, and the presence or absence of a
`model_io` declaration must not be made to stand in for that distinction.)*

**Deliberately NOT claimed:**

- not that resource *policy* changes — admission thresholds, retry and
  refusal semantics are untouched;
- not that calibration becomes generic or configurable;
- not measurement/verification identity (§7e → Step 07);
- not metric, planner or execution genericity.

## 2. The classification that governs this PR

The single most important discipline here: **a constant is not task
configuration merely because it is a constant.**

| Value | Site | Class | Disposition |
|---|---|---|---|
| `256` in probe targets | `evaluate_vram_skill/wrapper.py:248` (the literal), `:196-205`, `:236` (prose); `batch_resolver.py:85` (prose) | **TASK-SHAPED TERM** — the contract's class axis | **DERIVE** via the parameterized `realize_shape` (§0.2) |
| `PSD_SEGMENT_LENGTH // seg_size` | `workload_resolvers.py:50`; `inference_skill/estimator.py:210`; `evaluate_time_skill/wrapper.py:92,357,767` | **TASK-SHAPED TERM** | already DERIVE — **tighten** ambient→injected |
| `_INFERENCE_VS_TRAINING_RATIO = 2.7` | `inference_skill/estimator.py:79` | **CALIBRATION** — empirical median, measurement table at `:69-74` | **KEEP CALIBRATION**, value unchanged |
| `_MAX_BATCH_TIMESTEPS = 800_000` | `evaluate_vram_skill/compute_intensity.py:40` | **CALIBRATION/RUNTIME cap** | **KEEP**, unchanged |
| batch candidate table (64…1) | `evaluate_vram_skill` | **CALIBRATION** | **KEEP**, unchanged |
| RSS caps 40/60/24 GiB, overheads | `core/sandbox_executor.py:121` (`_ROLE_DEFAULT_RSS_GB`) etc. | **RUNTIME limits** | **KEEP** — and note CLAUDE.md pins the 60 GiB inference cap |
| `SEG_SIZE_BOUNDS = (2500, 40_000)` | `evaluate_time_skill/trigger_policy.py:34` | **CALIBRATION trigger policy** | **KEEP** — audit only |
| `segmentation_size` `40_000` fallbacks | `core/runtime_control/*` | **§7e — STEP 07 owned** | **AUDIT + RECORD**, do not fix here |

**Migrating any calibration value into task config is a stop condition.**

## 3. Seg-size fallback resolution (the §14 row's obligation)

The §14 ledger leaves *"Seg-size fallback defaults (40000/1000) … audit in
§7d design."* This design discharges that audit:

| Fallback | Meaning from source | Disposition |
|---|---|---|
| `model_config.get("segmentation_size", 40_000)` in `gpu_measurement_identity.py:214`, `gpu_measurement_worker_main.py:254`, `probe_production.py:220` | **planned-identity default** — a stand-in so a measurement identity can be keyed when the plan omits the field | **§7e / Step 07 owned.** Record; do not fix in Step 05 |
| `SEG_SIZE_BOUNDS` upper bound `40_000` | **calibration trigger policy** — when warm-up is required | **KEEP CALIBRATION** |
| `campaign.py` `40000` entries | **fixture roster** for a calibration campaign | **KEEP — test/campaign data** |

**Finding: there is no single semantic behind "40000".** The numbers
coincide because TIDMAD's usable segmentation happens to sit there. Per the
kickoff's own rule — *do not merge different defaults merely because the
numbers look related* — they stay separate and are **not** unified into one
resolver. The §14 row should be updated to record this, not to create the
"`§7d` resolver" it speculatively named.

## 4. Dead vs live estimators

The roadmap flagged analytic estimators as *"partly production-dead"*.
Implementation must classify **each** estimator before touching it:

```text
production live | diagnostic only | test-only | dead | fallback
```

**Binding rule for this PR**: an estimator that is dead or diagnostic-only is
**not** genericized. It is either left alone or recorded for a later cleanup.
Deriving a task term into a dead code path creates an abstraction whose only
consumer is dead code — a §0-rule-8 violation wearing a Step-05 badge. The
live surfaces this PR targets are the **VRAM probe / batch resolver** and the
**time aggregator**, both of which gate real admission decisions.

## 5. Upstream authorities / first production consumer

Consumes Step 02's `DatasetProfile`, Step 03's `ModelIOContract`, and Step
04a's `model_io_probe_skill`. **First production consumer: the live VRAM
probe and batch resolver** — the gate that admits or refuses a real attempt.
This is a consumer that exists and runs today.

## 6. Stage-A compatibility surfaces

| Surface | Criterion | Oracle status |
|---|---|---|
| forecast breakdowns (train/inference/scoring) | **deep-equal** under TIDMAD | EXISTING (PR-G parity-pin pattern) |
| admission/refusal decisions and their identities | **identical** | EXISTING |
| resolved batch size per candidate | **identical** | EXISTING but possibly **too low-level** — classify at Checkpoint 0 |
| probe tensor shapes/dtypes actually built | **identical** under TIDMAD | **MISSING — Checkpoint 0 captures it** |
| calibration constants | **unchanged values** | assert by pin |

## 7. Dependencies

Depends on Steps 02, 03, 04a — all merged. **Independent of 05a**: it
consumes `SampleSet` *values*, whose shape 05a is required to leave
byte-identical. **Independent of 05c.** Order is preference, not blocking.

## 8. Stage-B — ONE rung, two atomic subcases

**Rung `05b-B` — task-shaped resource/time terms derive from their owners.**
One capability, proven by two subcases because 05b migrates **two independent
authority families** (§0.4). A class-cardinality contrast alone cannot
discharge 05b: it would pass with Phase D still entirely ambient.

| Subcase | Varies ONLY | Held fixed | Proves |
|---|---|---|---|
| **B1 — Model-I/O probe realization** | the contract-owned class cardinality (or the equivalent Model-I/O fact) | `DatasetProfile`, calibration, hardware, policy, and the candidate's batch/segment extents except where they are themselves the observed probe | the **live** VRAM probe shape and the dependent forecast/admission terms follow the contract; **no local `[B, 256, T]` realization remains** |
| **B2 — dataset / decomposition topology** | the PSD/decomposition-relevant `DatasetProfile` fact | `ModelIOContract`, calibration, hardware, policy | the **live** workload/time resolution follows the **run-bound** profile; ambient fallback does not determine step counts or output-byte terms |

Why two and not one: the two halves fail independently and in opposite
directions. A single contrast that moved both facts at once would still pass
if either half were migrated and the other happened to agree — the
partial-derivation false green.

**B1 and B2 are atomic SUBCASES of one PR-level capability. They are not
separate rungs and not separate PRs.**

Do **not** build a contrast that varies topology *and* class count *and*
calibration at once.

## 9. Checkpoint C — live integration, minimum scenario set

**Frozen property**: Checkpoint C uses the **minimum deterministic
production-path scenario set** that exercises **both** 05b task-shaped
authority families through real resource/time control flow. A helper-only test
cannot discharge it.

Expected source-grounded shape:

| Scenario | Path | Proves |
|---|---|---|
| **C-P** | the real production VRAM pre-flight / admission path | it consumes the explicit run-bound contract and realizes the **actual candidate** probe |
| **C-D** | the real production workload/time path | it consumes the bound `DatasetProfile` |

If one production scenario proves both families, **use one and record why**.
If two paths are required by the production control flow, **the two scenarios
still constitute ONE Checkpoint C** — not two checkpoints and not two PRs.

Measurement may be deterministically controlled **at its existing boundary**,
provided the real production pricing/admission logic and the actual probe
realization are still exercised. Stubbing the measurement is legitimate;
stubbing the decision is not.

Under TIDMAD the decision and breakdown are unchanged; under each contrast the
derived terms move and the calibration values do not.

This evidence is what settles §11's semantic Gate-2 condition.

## 10. Failure classes

1. A calibration constant is migrated into task config → the framework
   silently claims empirical values are task declarations.
2. A **dead** estimator is genericized → consumer-less abstraction.
3. A derived term changes a TIDMAD forecast by even one unit → admission
   behavior shifts; every downstream attempt is priced differently.
4. Ambient re-resolution (`profile or resolve_dataset_profile()`) is left in
   place → a run bound to a contrast profile prices against the ambient one.
5. Probe realization is duplicated instead of delegated to
   `model_io_probe_skill` → a **second** probe authority, undoing 04a.

## 11. Gates

| Gate | Decision | Rationale / flip |
|---|---|---|
| **Gate 1** | **NOT REQUIRED** | no LLM-visible surface. **Flip**: if a resource literal reaches a prompt (cf. OD-S4-1's implementor capacity prose) |
| **Gate 2** | **CONDITIONAL — semantic rule below** | The changed surface **decides whether real attempts run**, and failure class 3 is not observable from a stubbed probe alone |

**The condition is semantic:**

```text
Checkpoint C must prove the LIVE production admission/pricing decision.

  deterministic production-path evidence fully exercises that decision
      -> Gate 2 NOT REQUIRED

  otherwise
      -> Gate 2 REQUIRED, under the CURRENT gate_testing_standard.md
```

Which branch holds is settled by implementation-time source evidence, not by
preference, and it is **decided at C7** (§16) with the evidence recorded.
Gate **launch choreography** — exact timing, exact bounded command, and cost
projection within the normal autonomous validation budget — belongs to the
Implementation Working Rules and current Gate policy, **not** to this design
and **not** to the operator's design review.

**What this design owns, and what it does not.** Frozen here: Gate 2's
semantic condition, the evidence Checkpoint C must produce, and the flip
condition. **Not** frozen here: launch permission, autonomous validation
budget, and timeout/cost ceilings — those belong to the filled Implementation
Working Rules and the current Gate standard.

```text
If C7 resolves Gate 2 to REQUIRED:
  run it under the CURRENT gate_testing_standard.md and the filled
  Implementation Working Rules.

  projected run inside the authorized bounded budget
      -> the implementation agent continues autonomously

  projected run materially exceeds that budget
      -> STOP with a cost/runtime projection
```

C0-C6 and C8 are fully deterministic; no commit depends on a Gate result to
be considered complete.

## 12. Validation budget

Mapped onto the commit plan (§16):

```text
C0  probe-shape capture + live/dead census
C1  parameterized realizer          -> byte-equality proof
C2  contract-accepting probe        -> no-contract equality proof
C3  transport                       -> arrival proof + drop mutation
C4  live wiring                     -> TIDMAD forecast/admission parity
C5  ambient -> injected profile     -> step-count + visited-sequence parity
C6  calibration pins + §3 audit     -> pin mutations
C7  Stage-B rung + Checkpoint C     -> family mutations + Gate-2 decision
C8  terminal regression + CI
```

**No local full suite. No real LLM.** Gate 2 only if §11's condition resolves
to REQUIRED at C7, bounded, and **never launched without operator
approval**.

## 13. Rollback boundary

Widened in revision 2 by OD-05b-1 — the probe half touches a Step-04a module
and the pre-flight IPC path:

| Surface | Commits |
|---|---|
| `agent/skills/model_io_probe_skill.py` (**additive only**) | C1 |
| `agent/skills/evaluate_vram_skill/` (`wrapper.py`, `isolated_probe.py`, `preflight_worker_main.py`, `preflight_adapter.py`) | C2, C3 |
| the tuner's VRAM pre-flight call site | C4 |
| `agent/skills/evaluate_time_skill/`, `agent/skills/inference_skill/estimator.py`, `agent/skills/training_skill/estimator.py`, `execute_tools/workload_resolvers.py`, `execute_tools/inference_single.py` | C5 |
| directly affected tests + node/skill docs | C0, C6-C8 |

Reverting C1-C4 restores the `[B, 256, T]` literal and the unparameterized
realizer; reverting C5 restores the ambient fallbacks. Nothing else.

**`core/runtime_control/` measurement identity is NOT touched** (Step 07).

## 14. Convergence-ledger implications

- **Model I/O contract / ForwardContract** — 05b adds a *third* production
  consumer of the probe authority. Disposition stays **RECORD ONLY**
  (OD-S4-4); a third consumer is more evidence for the recorded split, not a
  reason to merge the two representations.
- **Seg-size fallback defaults** — resolved in §3: **no single semantic; do
  not unify.** The row should record this and close, replacing its
  speculative "`§7d` resolver" owner.
- **SampleSet type + JSON key coercion** — 05b is the closest candidate for
  the "one consumer design" the row awaits, since `resolve_*_workload` reads
  SampleSets directly. Record the evidence; **do not** build the typed
  wrapper. Default remains RECORD FIRST.

## 15. Stop conditions

- A task term cannot be derived without inventing a new config field → STOP.
- Deriving a term changes a TIDMAD forecast by even one unit → STOP; that is
  failure class 3, not a tolerance.
- The work requires touching `core/runtime_control` measurement identity →
  STOP (Step 07).
- A calibration record store is required to migrate a constant → STOP; the
  roadmap defers calibration records, and this PR has no such consumer.

Added in revision 2, from the C1-C5 audit:

- **The selected candidate form needs a contract fact the contract does not
  carry**, the form/contract combination is not representable, or
  `ProbeConstructionError` (or its current typed equivalent) is raised → fail
  closed. *A canonical-semantic difference alone is NOT a stop condition —
  see §0.5.*
- **An explicit contract is lost or malformed in transport** → fail closed;
  never fall back to the literal shape.
- **Source cannot establish one safe explicit run-bound contract acquisition
  path** (C4 §6) → MATERIAL STOP; do not substitute an ambient re-read.
- **`realize_shape` would need per-axis extents** rather than one `symbolic`
  value (C1 §6) → STOP. That is a shape language, not a parameterization, and
  it belongs to whoever owns the contract schema.
- **A live profile consumer cannot be reached without changing a public
  signature 05b does not own** (C5 §6) → STOP.
- **The chosen contract-acquisition point would make an unrelated failure
  newly fatal on a pre-flight path that never read that source** (C4 §6) →
  STOP and reconsider the point; do not substitute an ambient re-read.

## 16. Commit plan — per-commit checklists

**Semantic sequence is frozen on approval; exact Git commit count is NOT.**
Also not frozen: helper structure, source line numbers, test-file
decomposition, exact mutation implementation. Implementation may merge or
split engineering commits provided the semantic sequence, the §17
Definition of Done, the Stage-B rung, the Checkpoint-C property and the Gate
disposition are unchanged.

Line references are **reading aids captured at `82a548f8`**, not contracts.
Re-read the touched source immediately before each commit.

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**Dependency chain.** `C0 → C1 → C2 → C3 → C4` is the probe seam, built
inert-first: C1 and C2 change no production behaviour (no caller supplies a
contract yet), C3 adds transport, and **C4 is the first commit where a real
run behaves differently** — and only under a task that declares `model_io`.
`C5` (profile tightening) is independent of C1-C4 and may land in either
order. `C6`-`C8` close.

---

### C0 — pre-edit baselines and the live/dead estimator census

**1. Goal.** Capture the compatibility surfaces that no existing oracle
covers, *before* any production edit, and settle by inspection which
estimators are production-live — because §4's binding rule forbids
genericizing a dead one, and that decision changes what C2-C5 are allowed to
touch. Separate commit because a baseline captured after an edit proves
nothing about that edit.

**2. Scope.**
- New tests under `tests/unit/agent/evaluate_vram_skill/` (or the existing
  VRAM test module — settle by inspection, do not invent a path).
- A written census recorded in §17 of this document.
- **Non-goals**: no production file changes at all; no new fixtures for facts
  Step 02/03/04a already pin; no forecast-parity oracle that already exists.
- Depends on: nothing.

**3. Implementation plan.**
- [x] Re-read `_build_probe_tensors` (`wrapper.py:176-249`) in full and
      record which inputs can move the built shape today (`loss_type`,
      `loss_name`, `model_type` → `get_output_type`).
- [x] Capture the probe tensor **shape and dtype** actually built under
      TIDMAD for each reachable branch: `classifier` (long target),
      `regressor` (`[B, T]` float), `hybrid`/legacy (`[B, 256, T]` float).
- [x] Classify **each** estimator on the resource path as
      `production live | diagnostic only | test-only | dead | fallback`,
      citing the caller that makes it live (or the absence of one).
- [x] Record the census in §17, including which estimators C2-C5 may touch.
- [x] Confirm by inspection which §6 oracles already exist (forecast
      breakdowns, admission identities, resolved batch size) and do **not**
      restate them.
- [x] Confirm no capture restates a Step-02/03/04a baseline.

**Explicitly NOT required**: baselining every branch of the VRAM wrapper
merely because it exists. A branch whose shape cannot move when a contract is
supplied is not evidence for this PR.

**4. Validation plan.**
- *Unit*: the new probe-shape baselines pass on unmodified production code.
- *Integration/pseudo*: none required at C0.
- *Negative*: include the `UnknownOutputContractError` → `ValueError` path
  (`wrapper.py:230-240`); a baseline of the happy path alone cannot detect a
  migration that silently stops raising.
- *Backward-compat*: this commit **is** the parity instrument.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [x] Baselines pass against production code that is **byte-unchanged**
      (`git status --porcelain` lists no production file in this commit).
- [x] The captured shapes are written as **hardcoded literals**, never
      re-derived from the code under test.
- [x] Every reachable target-shape branch has exactly one case.
- [x] The estimator census names, for each live estimator, the production
      caller that makes it live — a file:line, not a claim.
- [x] Every estimator classified `dead`/`diagnostic` is listed in §17 as
      **out of scope for C2-C5**.

**6. Failure and edge cases.**
- An estimator's liveness cannot be settled from source → record it as
  `UNKNOWN` and treat it as out of scope; do not guess it live.
- A probe branch cannot be reached without a GPU → record the reachability
  route found; if it genuinely requires hardware, it belongs to Checkpoint C
  / the §11 Gate question, and this document is updated to say so.

**7. Verification commands and evidence.**
- [x] **RUN AS**: `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill/test_step05b_c0_probe_baselines.py tests/unit/agent/evaluate_vram_skill/test_probe_target_contract.py -q` — the two modules that carry the baseline, rather than the whole directory, which restates unrelated pre-flight oracles
- [x] Recorded in §18.2: 16 passed in 1.04s (7 new + 9 existing); `git status --porcelain` listed exactly one path, the new test module.

**8. Commit boundary.** Tests and a written census only. Independently
reviewable as "what we promise not to change, and what we are allowed to
touch". No production edit.

---

### C1 — additive parameterization of the 04a realizer

**1. Goal.** Give `realize_shape` caller-supplied extents so ONE realization
authority can serve both validation probes and capacity probes (§0.2 option
A). Separate commit because it modifies a **Step-04a-owned module** and must
be provably behaviour-preserving on its own, before any new consumer exists
to confuse the evidence.

**2. Scope.**
- `agent/skills/model_io_probe_skill.py` — `realize_shape` signature and body
  (`:109-140`); docstring; `__all__` untouched.
- **Non-goals**: no change to `PROBE_BATCH` (`:68`), `PROBE_SYMBOLIC_EXTENT`
  (`:75`), `LOSS_PROBE_BATCH` (`:293`), `LOSS_PROBE_LENGTH` (`:294`) or
  `_LEGACY_LOSS_PROBE_CLASSES` (`:372`); no change to `build_model_input`,
  `build_loss_probe_pair`, `declared_output_tensor`, `expected_output_shape`
  or `input_index_extent` **behaviour**; no new consumer.
- Depends on: C0.

**3. Implementation plan.**
- [x] Re-read `realize_shape` and the `fixed → batch → symbolic` precedence
      it documents.
- [x] Add keyword-only `batch: int | None = None` and
      `symbolic: int | None = None`, defaulting to the existing constants.
- [x] Preserve the precedence exactly: a `fixed` extent is a DECLARED fact
      and must still win over both new parameters.
- [x] Update the docstring to state that omitting both arguments is
      byte-identical, and why a `fixed` axis ignores them.
- [x] Confirm no existing call site is edited in this commit.

**4. Validation plan.**
- *Unit*: for the shipped TIDMAD contract, `realize_shape(t)` returns the
  documented `(1, 256, 64)` output / `(1, 64)` input, unchanged.
- *Unit*: `realize_shape(t, batch=B, symbolic=T)` returns `(B, 256, T)` — the
  `fixed` class axis unmoved.
- *Negative*: a `fixed` axis is **not** overridden by `symbolic=`; **zero and
  negative extents raise** in the module's existing idiom rather than falling
  back. Do not invent a new error class — reuse the module's typed one.
- *Backward-compat*: `build_model_input`, `expected_output_shape` and both
  node consumers produce byte-identical shapes.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [x] With both arguments omitted, `realize_shape` returns a tuple **equal**
      to the pre-change return for every contract in the existing 04a test
      fixtures — asserted by equality, not by inspection.
- [x] With `batch=B, symbolic=T` supplied, a declared `fixed` class extent is
      still `256` in the returned tuple, and rank and axis order are those of
      the contract, not of any assumption in this module.
- [x] The four probe constants are unchanged, asserted by value.
- [x] **`None`-sensitivity, asserted explicitly**: `batch=None` /
      `symbolic=None` resolve to the existing Step-04a recipe defaults; a
      supplied **positive** extent is used verbatim; **zero or a negative
      extent fails** in the module's existing typed-error idiom and **never
      silently falls back**. A `0` that resolved to `PROBE_BATCH` would price
      a tensor nobody asked for.
- [x] Zero production call sites changed by this commit.
- [x] A mutation that makes the new parameter override a `fixed` axis is
      **RED**.
- [x] A mutation rewriting the override as `batch or PROBE_BATCH` is **RED**
      — caught by the zero case above.

**6. Failure and edge cases.**
- A contract with a batch-role axis that is *also* `fixed` → `fixed` wins;
  pin that precedence, since it is the one case where the two rules meet.
- A contract with more than one symbolic axis → **both** receive `symbolic`;
  record whether that is correct for the capacity probe, and if it is not,
  STOP rather than adding per-axis parameters (that would be a new shape
  language, not a parameterization).
- A caller passing `symbolic=` for a rank-2 input contract → must still be
  the input's own rank; nothing here may assume 3-D.

**7. Verification commands and evidence.**
- [x] **RUN AS**: `.venv/bin/python -m pytest tests/unit/agent/skills/test_step05b_c1_realizer_extents.py -q` plus the full 04a consumer sweep — see §18.2b. `-k model_io_probe` matches nothing: the 04a realizer tests live under the two node directories, not under a module-named file.
- [x] Recorded in §18.2b: 17 passed in 0.92s; 474 passed in 6.11s across every existing 04a consumer, none edited.

**8. Commit boundary.** One additive, defaulted signature change with zero
behaviour change, independently revertible. No consumer wiring bundled in.

---

### C2 — the VRAM probe accepts a contract (in-process, inert in production)

**1. Goal.** Let `_build_probe_tensors` derive its target from a supplied
contract, while every production caller still supplies none — so the seam is
reviewable before it is live. Separate from C3/C4 because "the helper can do
it" and "production does it" are different claims with different failure
modes, and Step 02b's precedent is explicit that a parameter with a `None`
default is invisible to every caller that never passes it.

**2. Scope.**
- `agent/skills/evaluate_vram_skill/wrapper.py` — `_build_probe_tensors`
  (`:176-249`) gains `model_io_contract: ModelIOContract | None = None`;
  `run_skill` (`:483`) accepts and forwards the same optional kwarg; the
  call site at `:588`.
- **Non-goals**: no caller supplies a contract yet; no transport; no change
  to dtype resolution (`get_target_torch_dtype`, `:214`), to the
  `UnknownOutputContractError` refusal (`:230-240`), or to any calibration.
- Depends on: C1.

**3. Implementation plan.**
- [x] Re-read `_build_probe_tensors` and `run_skill`'s kwargs contract
      (`:483-520`) — note it is `**kwargs`, so the addition is additive.
- [x] Add the optional parameter and thread it from `run_skill` to the
      `:588` call site.
- [x] With a contract: resolve the candidate's declared **form** exactly as
      validation does today (`get_output_type(model_type)`, or its current
      canonical equivalent), then derive the target shape via
      `declared_output_tensor(contract, form)` + the C1-parameterized
      `realize_shape(..., batch=batch_size, symbolic=seg_size)`. **Do not add
      a second form-resolution table** (§0.5).
- [x] Without a contract: take exactly today's path, including the
      `get_output_type` branch and the `[B, 256, T]` literal.
- [x] Decide and record where **dtype** comes from when a contract is
      supplied — the loss (today's rule) remains the dtype authority; the
      contract supplies shape only. Do not silently move dtype ownership.
- [x] Update `evaluate_vram_skill.md` for the new optional kwarg.

**4. Validation plan.**
- *Unit*: contract supplied → the built target equals `(B, 256, T)` for the
  TIDMAD contract at real `B`/`T`; contract omitted → byte-identical to the
  C0 baseline.
- *Unit*: a contrast contract with a different class extent moves the target
  shape and **nothing else** (dtype, input shape unchanged).
- *Negative*: the `UnknownOutputContractError` → `ValueError` path still
  raises when no contract is supplied; a malformed contract fails loudly
  rather than falling back to `[B, 256, T]` — **a silent fallback here is
  the defect this commit must not introduce**.
- *Backward-compat*: every C0 baseline passes unchanged.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [x] With `model_io_contract=None`, the returned `(input, target)` shapes
      and dtypes are **equal** to the C0 baseline for every branch.
- [x] With the shipped TIDMAD contract supplied, the target shape equals the
      no-contract shape **exactly** — this is the whole legacy-compatibility
      claim, and it is an equality assertion, not a narrative.
- [x] With a contrast contract, the class axis moves and `batch_size` /
      `seg_size` are honoured at their real values (not `1` / `64`).
- [x] Target **dtype** still comes from the loss in both paths.
- [x] **Form/fact authority matches Step 04a**: for each declared form
      (`classifier`, `regressor`, legacy) the VRAM path's realized output
      tensor is **equal** to what `declared_output_tensor` +
      `realize_shape` produce for the same contract and form — asserted
      against the 04a authority, not against a locally restated table.
- [x] A `regressor` candidate under a categorical contract is **accepted**
      and probed at the class-axis-dropped shape.
- [x] A `classifier` candidate under a contract carrying no class axis raises
      `ProbeConstructionError` (04a's own fail-closed case), and the VRAM
      path surfaces it rather than falling back to the literal.
- [x] No production caller passes a contract yet — asserted by inspection and
      recorded, so C4's evidence cannot be confused with C2's.

**6. Failure and edge cases.**
- Contract declares a `regressor` output → target is `[B, T]`; must agree
  with today's `get_output_type` branch under TIDMAD.
- The contract's canonical output semantic differs from the candidate's
  declared form — e.g. a `regressor` candidate under a categorical task
  contract → **SUPPORTED, not a conflict.** Step 04a preserves exactly this
  case (three live plugins rely on it), and `declared_output_tensor` already
  returns the continuous form with the class axis dropped. Rejecting it would
  be a TIDMAD verdict change and a Stage-A parity break (§0.5).
- Contract present but unrealizable (`ProbeConstructionError`) → propagate as
  the module's existing `ValueError` idiom; never fall back to the literal.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill -q`
- [x] Recorded in §18.2c: 304 passed in 22.97s; no-contract equality holds for all three reachable branches, and the shipped contract reproduces the legacy tensor exactly.

**8. Commit boundary.** One helper and one entry point, inert in production,
independently revertible. No transport, no tuner change.

---

### C3 — contract transport across the pre-flight worker boundary

**1. Goal.** Carry an optional contract from the parent to the isolated
pre-flight child, so the live production path (which is a subprocess) can use
what C2 added. Separate commit because it is IPC-shaped work with its own
failure mode — a field that serializes but never arrives — and because it is
still inert until C4 supplies a contract.

**2. Scope.**
- `agent/skills/evaluate_vram_skill/isolated_probe.py` — `IsolatedProbeSpec`
  (`:168-182`) gains one optional field beside `model_config_payload` /
  `train_config` / `loss_config`.
- `agent/skills/evaluate_vram_skill/preflight_worker_main.py` — rebuild and
  forward it into `run_skill` (`:190-205`).
- `agent/skills/evaluate_vram_skill/preflight_adapter.py` —
  `run_production_preflight` (`:212-223`) gains the matching optional
  parameter.
- **Non-goals**: no change to `HardwareSnapshot`'s six-attribute surface
  (a seventh read is pinned by an existing test); no change to
  `effective_cap_gb`, deadlines, or worker memory limits.
- Depends on: C2.

**3. Implementation plan.**
- [x] Re-read `IsolatedProbeSpec` and the worker's `spec.get(...)` rebuild.
- [x] Follow the established pattern: `train_engine_sandbox.py:1249`
      (`--model_io_json`) + `load_model_io_contract`
      (`model_io_contract.py:312`) — decide between an inline JSON field on
      the spec and a path, and record why. The spec is already a transient
      JSON IPC file, so an inline dump is the lower-ceremony option.
- [x] Thread parent → spec → worker → `run_skill`.
- [x] Confirm `None` remains legal end to end and produces today's behaviour.

**4. Validation plan.**
- *Unit*: a spec round-trips through JSON with the contract intact and
  revalidates to an **equal** `ModelIOContract`.
- *Integration/pseudo*: the worker path forwards the contract into
  `run_skill` — asserted at the `run_skill` boundary, not by reading the spec
  file back.
- *Negative*: absent field → `None` → today's behaviour; malformed contract
  in the spec → fails loudly in the child with a diagnostic naming the field,
  never a silent `None`.
- *Backward-compat*: an old spec JSON with no such field still loads.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [x] A contract placed on the spec **arrives at `run_skill`** in the child —
      proven by a test that fails if the forwarding line is deleted, not by a
      grep for the field name.
- [x] Spec JSON without the field validates and behaves exactly as today.
- [x] `HardwareSnapshot`'s attribute surface is unchanged (the existing
      six-attribute test still passes untouched).
- [x] A transport mutation — drop the field in the worker rebuild — is
      **RED**.

**6. Failure and edge cases.**
- Contract too large / non-JSON-native after dump → must fail at the parent
  with a clear diagnostic, not produce a truncated child spec.
- Worker launched by older tooling with a stale spec → absent field is legal
  and selects the legacy no-contract path.
- Propagation failure (child cannot rebuild the contract) → **fail the
  pre-flight loudly**; do not fall back to the literal shape, because a
  silently-wrong probe reports a capacity number for a different model.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill -q`
- [x] Recorded in §18.2d: 310 passed in 21.87s; M10/M11 RED first time, M12 survived and exposed an uncovered parent hop, RED after the fix.

**8. Commit boundary.** IPC only. No behaviour change while no caller
supplies a contract. No tuner change.

---

### C4 — a run-bound contract reaches the resource path (first live consumer)

**1. Goal.** Make the live resource gate the third production consumer of the
probe authority, fed by **one explicit run-bound `ModelIOContract`**. **This
is the first commit that can change a real run's behaviour**, and only for a
task that declares `model_io` — which is why it is isolated.

**2. Scope.**
- The tuner's pre-flight call path — `run_production_preflight`'s caller in
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
  (`run_production_preflight` imported at `:54`).
- Whatever minimum explicit transport the current caller chain supports
  (chosen in step 1 below, not pre-frozen here).
- **Non-goals**: no new **user-authored or persisted** configuration; no new
  YAML/config hierarchy; no new required CLI argument; no change to admission
  thresholds, retry or refusal semantics; no ambient contract lookup inside
  any resource consumer.
- Depends on: C3.

**3. Implementation plan.**

**The frozen property is semantic, not an engineering route:**

```text
- the resource path receives ONE explicit run-bound ModelIOContract
  semantic value;
- no VRAM/resource consumer independently re-reads an ambient or default
  task configuration as its own authority;
- the SAME run binding reaches the in-process wrapper and the isolated
  pre-flight worker.
```

- [x] Re-read **only** the caller chain needed to choose the minimum
      transport, and record the choice with its source evidence. Preferred
      order:
      1. **reuse an already-resolved contract** in the workflow/run context;
      2. if the tuner protocol lacks one, an **optional typed runtime input
         field** — when that is the smallest explicit transport;
      3. reuse an existing run-input/sidecar boundary where one already
         exists.
- [x] Bind it once per run, at a point that adds **no branch** to `run()`
      (CLAUDE.md: `run()` sits on pyright's strict complexity ceiling).
- [x] Pass it through `run_production_preflight` to both the in-process and
      child paths.
- [x] Confirm a task with no `model_io`, and a legacy caller that supplies
      nothing, both yield `None` and today's behaviour.
- [x] `evaluate_vram_skill.md` updated at C2. The tuner node doc is re-verified against merged source at C8, per the doc-sync rule.

> **`load_task_config()` inside the tuner is permitted only if source proves
> it is already the canonical run-bound input for that node and cannot
> diverge from the actual run binding.** It is otherwise a *second ambient
> acquisition* — it may happen to read the same file, but "happens to agree"
> is precisely the defect shape Step 02a/02b/05a removed. An **optional typed
> runtime protocol field is not a redesign of the configuration
> architecture** (§20), and the invariant protecting model/loss/train config
> must not be stretched into forbidding one.

**4. Validation plan.**
- *Unit*: with a contract bound for the run, it reaches `run_skill`; with a
  legacy caller, `None` does.
- *Integration/pseudo*: a real tuner pre-flight path — not a helper — carries
  the same binding to **both** the in-process wrapper and the child worker.
- *Negative*: a malformed/unresolvable contract fails at the existing
  resolution boundary before any probe runs; 05b adds no second resolution
  point.
- *Backward-compat*: under TIDMAD the **resolved batch size, the forecast
  breakdown and the admission/refusal decision are identical** to C0; old
  serialized configs and legacy callers keep working.
- *Gate*: see §11 — the condition is decided at C7, not here.

**5. Acceptance criteria.**
- [x] Under TIDMAD, admission decision, resolved batch size and forecast
      breakdown are **equal** to the C0 baseline — a single unit of drift in
      any breakdown term is failure class 3 and a **STOP**, not a tolerance.
- [x] A task with no `model_io`, and a legacy caller supplying nothing, both
      still run the gate on the legacy no-contract path.
- [x] **One run binding**: the contract observed by the in-process wrapper and
      the one observed in the child are the same semantic value — asserted
      semantically, never by a call count.
- [x] **No resource consumer performs its own ambient task-config
      resolution** — a transport mutation that makes one re-read a default
      task config is **RED**.
- [x] `run()` gains no new branch (verified by reading the diff, since the
      complexity ceiling is not observable from tests).
- [x] No new user-authored config, no new config hierarchy, no new required
      CLI argument; old serialized configs load without migration.
- [x] This commit makes **Stage-B B1** provable end to end: a contrast
      contract bound for the run moves the live probe shape.

**6. Failure and edge cases.**
- The chosen acquisition point would make an unrelated failure newly fatal on
  a pre-flight path that never read task config → **STOP** and reconsider the
  point.
- **Source cannot establish any safe explicit acquisition path** → **MATERIAL
  STOP**; do not fall back to an ambient re-read.
- A candidate whose declared form differs from the contract's canonical
  semantic → **supported**, per §0.5; not a failure here.
- Resume of a run started before this commit → nothing persisted changes, so
  resume is unaffected; assert it rather than assume it.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/agent/evaluate_vram_skill -q`
- [x] Recorded in §18.2e and §18.3 D-05b-1: 4,039 passed in 372.68s across the tuner, VRAM, workflow and core suites; transport chosen with its source evidence; M14 recorded OPEN until Checkpoint C.

**8. Commit boundary.** Production wiring only. No probe-logic change, no
transport-mechanism change, no unrelated cleanup.

---

### C5 — ambient → injected `DatasetProfile` on the live resource path

**1. Goal.** Remove the `profile or resolve_dataset_profile()` fallback shape
from the live resource path, so a run bound to a contrast topology cannot be
**priced** against the ambient one. Independent of C1-C4; grouped separately
because it is the Step-02b defect shape, not a Model-I/O concern.

**2. Scope.**
- `execute_tools/workload_resolvers.py` — `_validate_seg` (`:49`) and
  `resolve_inference_workload` (`:139`).
- `agent/skills/inference_skill/estimator.py:208`.
- `agent/skills/evaluate_time_skill/wrapper.py:92, :357, :767`.
- The four production callers that must now supply a profile:
  `evaluate_time_skill/wrapper.py:515`,
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:2914`,
  `agent/skills/training_skill/estimator.py:493`,
  `execute_tools/inference_single.py:563`.
- **Non-goals**: no change to strategies, portions, seeds, **ordering**, or
  `SampleSet` shape/serialization; no new CLI argument; `core/runtime_control`
  untouched (Step 07).
- Depends on: C0 (the estimator census says which of these are live).

**3. Implementation plan.**
- [x] Re-read each of the four call sites and record whether a resolved
      profile is already in scope.
- [x] `inference_single.py` **already loads one** (`:336-339`,
      `dataset_profile` / `profile_dataset`) and simply does not pass it to
      `resolve_inference_workload` at `:563` — thread it; this is a
      one-argument fix and the clearest instance of the defect.
- [x] For each remaining caller, thread the run-bound profile; where none is
      in scope, record the acquisition point rather than inventing one.
- [x] Decide per function whether the parameter becomes **required** or stays
      optional-with-fallback, and record the reason. Required is preferred
      where every production caller can supply it (the 05a precedent); a
      fallback that no production caller relies on is dead permission.
- [x] Leave `evaluate_time_skill/wrapper.py`'s reads consistent with whatever
      the enclosing function receives — do not create a second acquisition.

**4. Validation plan.**
- *Unit*: under a bound contrast profile, each migrated resolver returns the
  contrast-derived step/batch counts, not the TIDMAD ones.
- *Integration/pseudo*: a real pre-flight/time path prices against the bound
  profile.
- *Negative*: a caller that supplies no profile either fails loudly (if the
  parameter became required) or is proven to be a non-production caller.
- *Backward-compat / default-parity*: **under TIDMAD every step count,
  batch count and `output_bytes` value is identical to C0.**
- *Gate*: **none**.

**5. Acceptance criteria.**
- [x] Under TIDMAD, `resolve_training_workload`, `resolve_inference_workload`
      and `resolve_scoring_workload` return values **equal** to the C0
      baseline — field by field, including `detail["output_bytes"]`.
- [x] **Default-path invariance, asserted on the sequence and not on the
      config**: for the default (`shuffle`) ordering path, the *visited
      file/sample sequence*, the resolved seeds and the **total step count**
      are unchanged. 05b touches the step-count producer, so proving the
      configuration value unchanged would be proving the wrong thing.
- [x] **Stage-B B2 passes**: under a contrast profile varying only the
      PSD/decomposition fact, the derived step counts and output-byte terms
      move and no calibration constant does.
- [x] An ambient-regression mutation (restore `profile or
      resolve_dataset_profile()` at a migrated site) is **RED**.
- [x] `grep "profile or resolve_dataset_profile()"` over the live resource
      path returns zero — recorded as **supporting evidence only**; the
      semantic guard above is the property.

**6. Failure and edge cases.**
- **Scope mismatch**: a profile bound at the parent but absent in a
  subprocess → the subprocess must load its own explicitly
  (`inference_single.py:336-339` is the pattern) and **fail closed** when a
  path is supplied but unreadable — `load_dataset_profile` already does this;
  do not weaken it.
- **Legacy configuration**: a caller predating the transport must keep
  working *or* be proven non-production. Record which.
- **Resume**: step counts are recomputed, not persisted, so a resumed run
  must produce identical counts under TIDMAD — assert it.
- **Propagation failure**: if a profile cannot be threaded to a live site
  without changing a public signature that 05b does not own → **STOP**.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/agent/tune_ml_hyperparam_agent -q`
- [x] Recorded in §18.2f: 2,116 passed in 288.28s after the call-site migration; 10 new cases; M15/M16 RED.

**8. Commit boundary.** One defect family across its live call sites,
independently revertible. No Model-I/O work, no calibration change.

---

### C6 — calibration-preservation audit and the §3 seg-fallback record

**1. Goal.** Establish that **calibration values and their ownership did not
change**, and discharge the §14 ledger's seg-fallback audit obligation.
Separate commit because it is the anti-scope evidence: it exists to fail if a
later edit reclassifies an empirical constant as task configuration.

**2. Scope.**
- A written preservation audit recorded in §18.
- **At most a small number** of genuinely missing semantic pins (criteria
  below).
- §3 of this document + the §14 roadmap row (docs).
- **Non-goals**: no production change of any kind; no constant is moved,
  renamed or re-owned; **no repo-wide pin campaign**.
- Depends on: C5.

**3. Implementation plan.**

**Evidence order — use the cheapest sufficient layer, and stop there.** A new
literal pin is the *last* resort, not the default.

```text
1. an EXISTING semantic oracle already protects the value      -> cite it
2. TIDMAD forecast/admission deep equality would move if the
   value moved                                                 -> cite it
3. static touched-file diff proves the owner/value is untouched -> cite it
4. none of the above, AND this PR touches or could accidentally
   re-own the value                                            -> add ONE pin
```

- [x] For each calibration/runtime value in §2 — `_INFERENCE_VS_TRAINING_RATIO`
      (2.7), `_MAX_BATCH_TIMESTEPS` (800k), `SEG_SIZE_BOUNDS`,
      `_ROLE_DEFAULT_RSS_GB` (incl. the 60 GiB inference cap CLAUDE.md pins),
      the batch candidate table — record which layer above covers it.
- [x] Add a pin **only** where layer 4 applies, and say why layers 1-3 do
      not.
- [x] Record the three `core/runtime_control` seg fallbacks
      (`gpu_measurement_identity.py:214`,
      `gpu_measurement_worker_main.py:254`, `probe_production.py:220`) as
      **Step-07 owned, not fixed here**.
- [x] Update the §14 row to record *no single semantic behind "40000"* and
      retire its speculative "`§7d` resolver" owner.

**Explicitly NOT required**: a literal pin and a mutation for every untouched
constant. Most of these live in modules 05b does not modify; asserting that an
untouched constant still equals itself is the "test what a declaration already
enforces" pattern CLAUDE.md forbids, and it would bury the few pins that
matter.

**4. Validation plan.**
- *Unit*: each **added** pin asserts a hardcoded expected value.
- *Negative*: covered by the mutation below, not by a separate case.
- *Backward-compat*: n/a (no behaviour change).
- *Gate*: **none**.

**5. Acceptance criteria.**
- [x] Every §2 calibration/runtime value is accounted for by **one named
      evidence layer**, cited by file:line or test name.
- [x] Any pin added compares against a literal written in the test, never
      against the module attribute it guards.
- [x] Every pin added is justified by layer 4 — the justification is written
      down, and a pin that duplicates an existing oracle is **removed, not
      kept "for safety"**.
- [x] The §14 row no longer names a `§7d` resolver.
- [x] Zero production files modified by this commit.

**6. Failure and edge cases.**
- A constant is already asserted elsewhere → cite the existing pin; do not
  duplicate.
- A constant turns out to have a live *derivation* rather than a literal →
  record it; pinning a derived value would freeze the derivation by accident.
- A value has no oracle **and** 05b cannot touch it → it is out of scope;
  record it rather than inventing coverage for another PR's surface.

**7. Verification commands and evidence.**
- [x] **RUN AS**: `.venv/bin/python -m pytest tests/unit/agent/inference_skill -q` — exactly ONE pin was added, so the module that owns it is the selector.
- [x] Recorded in §18.2g: 32 passed in 0.88s; the five-row evidence-layer table; M17/M18 both RED.

**8. Commit boundary.** Audit record, minimal pins, and documentation only.

---

### C7 — Stage-B rung, Checkpoint C, and the Gate-2 decision

**1. Goal.** Prove the capability holds, cannot silently regress, and settle
§11's Gate-2 condition **from evidence**. Separate from C1-C5 so a reviewer
reads the behaviour change and the "what must never regress" decision
independently.

**2. Scope.**
- New/extended tests: the Stage-B contrast rung, the Checkpoint-C scenario,
  and the family mutations.
- §11 and §17 of this document.
- **Non-goals**: no production behaviour change in this commit.
- Depends on: C4, C5, C6.

**3. Implementation plan.**
- [x] Build **B1** (§8): vary only the contract-owned class cardinality;
      hold `DatasetProfile`, calibration, hardware and policy fixed. Prove
      the live VRAM probe shape and dependent forecast/admission terms follow
      the contract, and that no local `[B, 256, T]` realization remains.
- [x] Build **B2** (§8): vary only the PSD/decomposition-relevant
      `DatasetProfile` fact; hold `ModelIOContract`, calibration, hardware and
      policy fixed. Prove the live workload/time path follows the run-bound
      profile.
- [x] Prove across both that `2.7`, the intensity cap, the batch table and
      the hardware context stay byte-identical.
- [x] Build the **minimum** Checkpoint-C scenario set (§9): C-P and C-D, or
      one scenario if it provably reaches both families — record which and
      why.
- [x] Run the family mutations and record each observed result:
      probe-shape ambient regression; **profile ambient regression**;
      **contract-transport drop**; **ambient task-config re-read**;
      calibration drift.
- [x] **Decide the Gate-2 condition** (§11) and record the evidence:
      deterministic production-path evidence fully exercises the live
      admission decision → NOT REQUIRED; otherwise REQUIRED.

**4. Validation plan.**
- *Unit*: the contrast rung and the mutations.
- *Integration*: Checkpoint C through the real gate, not a helper.
- *Negative*: the guard must **not** fire on the legitimate single
  contract/profile binding.
- *Backward-compat*: TIDMAD parity unchanged by this commit (it adds no
  production change).
- *Gate*: **Gate 2 only if §11's condition resolves to REQUIRED**, run under
  the current Gate standard and the filled Implementation Working Rules —
  autonomously when the projected run is inside the authorized bounded
  budget, otherwise STOP with a projection (§11). Gate 1 remains NOT REQUIRED
  unless a resource literal reaches a rendered prompt.

**5. Acceptance criteria.**
- [x] **B1 and B2 both PASS**, each against its own baseline, each moving
      exactly one authority's fact.
- [x] Reintroducing ambient behaviour reds for **each** family — probe shape,
      profile, transport, ambient task-config re-read — with each mutation's
      site count asserted as exactly 1 before it is applied.
- [x] Every mutation is restored from clean source and the tree re-verified
      green.
- [x] Checkpoint C crosses the real production gate for **both** authority
      families (one scenario or two, per §9); a helper-only substitution is
      explicitly rejected in the record.
- [x] The Gate-2 branch is recorded with the **source evidence** that settled
      it, not a preference.
- [x] No production file is modified by this commit.

**6. Failure and edge cases.**
- A mutation **survives** → inspect the test architecture before adding an
  assertion; classify (real gap / equivalent / unreachable / wrong fixture).
- The live probe cannot run without a GPU → that is the §11 Gate-2 trigger,
  **not** a licence to weaken Checkpoint C into a helper test.
- The contrast contract moves a calibration value → the contrast is wrong;
  rebuild it single-axis.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
- [x] Recorded in §18.2h: 5 passed in 13.01s (Checkpoint C) and 374 passed in 21.54s; twelve mutations across five families, all RED and restored; **Gate 2 NOT REQUIRED**, with four recorded evidence items.

**8. Commit boundary.** Evidence only. No production change.

---

### C8 — terminal regression, docs, CI

**1. Goal.** Establish terminal evidence and leave the PR reviewable.

**2. Scope.** §17 ledger, the touched node/skill `.md` files, CI iteration.
**Non-goals**: no new capability; no scope expansion.
Depends on: C7.

**3. Implementation plan.**
- [x] Synchronize §17 with actual findings, deviations and evidence.
- [x] Update `evaluate_vram_skill.md` and the tuner node doc as the **last**
      pre-merge step, quoting each documented kwarg/default against merged
      source (CLAUDE.md doc-sync rule).
- [x] Run the terminal checks from a **clean tree**.
- [x] Open/update the PR; drive exact-final-head CI green.
- [x] Verify local HEAD == PR `headRefOid` == successful CI `headSha`.

**4. Validation plan.**
- Directly affected tests · focused integration · mutations · `ruff check` ·
  `ruff format --check` · required static/type checks · exact-head CI.
  **No local full suite by default.** Gate only if C7 decided REQUIRED.

**5. Acceptance criteria.**
- [x] Every verdict read from the **log file**, never a wrapper's exit
      status.
- [x] The three identities match, each read rather than reconstructed.
- [x] Working tree clean; §17 records every deviation.
- [x] If local pyright cannot run (the 05a precedent: host Node too old),
      that limitation is **recorded** and no local type claim is made.

**6. Failure and edge cases.**
- Full-suite/preflight guard reds on a dirty tree → commit the checkpoint
  first; never relax the guard.
- CI fails on an environment-only check → diagnose and fix autonomously; not
  a stop condition.

**7. Verification commands and evidence.**
- [x] The terminal command set, with counts and wall time recorded.
- [x] CI run id and exact `headSha`.

**8. Commit boundary.** Documentation and CI-driven fixes only.

---

### 16.1 Commit-boundary discipline (binding for every commit above)

Before each semantic commit, **record in the live ledger (§18)**: the exact
`git diff --stat`, the staged file list, the tests run with counts and wall
time, and any deviation from this plan. A commit whose evidence cannot be
written down that way is not ready.

**This is internal evidence discipline, not an operator pause.** The agent
records and continues.

Never mark a checklist item `[x]` before the evidence exists. An unperformed
exact command is recorded as **DEVIATED** or **SUPERSEDED** with what was
actually run — the 05a precedent (its §18 reconciliation).

### 16.2 Checkpoints are NOT operator pause points

**C0-C8 and Checkpoints 0/A/B/C/D are semantic evidence milestones inside ONE
autonomous PR implementation.** They are not separate PRs, not approval
boundaries, not context boundaries, and not reasons to stop.

After implementation authorization, ordinary findings follow:

```text
inspect -> classify -> record in the live ledger -> fix -> validate -> continue
```

Do not return progress merely because a commit landed, a checkpoint passed, a
mutation found something, the PR opened, or CI started. Only a **MATERIAL
STOP** (§15) — or a projected validation exceeding the authorized budget —
returns early. The operator does not approve movement between checkpoints.

## 17. Definition of Done — the authoritative checkpoint table

**This table governs.** Where any lower-level checklist in §16 diverges from
it, this table wins.

### CHECKPOINT 0 — pre-edit baselines — **COMPLETE** (§18.2)
- [x] probe tensor shape/dtype baseline captured for every reachable branch
- [x] live/dead estimator census recorded, each live one naming its caller
- [x] captured **BEFORE** any production edit
- [x] no duplication of existing Step-02/03/04a baselines

### CHECKPOINT A — TIDMAD / replay parity
- [x] forecast breakdowns **deep-equal** (train/inference/scoring)
- [x] admission/refusal decisions and identities identical
- [x] resolved batch size per candidate identical
- [x] probe tensor shapes/dtypes identical with no contract supplied
- [x] calibration constants unchanged, asserted by pin
- [x] step counts and the default-path visited sequence unchanged
- [x] model / loss / train / `TrialConfig` schemas unchanged; CLI unchanged
- [x] a representative historical TIDMAD configuration loads **without
      migration** and resolves to the same effective semantics

### CHECKPOINT B — generic consumption (ONE rung, TWO atomic subcases)
- [x] **B1** Model-I/O probe realization: class cardinality moves the live
      probe shape and dependent forecast/admission terms
- [x] **B2** dataset/decomposition topology: the PSD fact moves the live
      workload/time terms via the **run-bound** profile
- [x] each subcase varies exactly ONE authority's fact against its own
      baseline
- [x] calibration, hardware and policy provably fixed across both
- [x] family mutations red appropriately (probe shape · profile · transport ·
      ambient task-config re-read · calibration drift)
- [x] no ambient profile fallback and no ambient task-config re-resolution
      remains in a live resource consumer

### CHECKPOINT C — production path
- [x] the minimum deterministic production-path scenario set reaches **both**
      authority families through real resource/time control flow
- [x] the real production gate prices and admits a real attempt using derived
      terms; measurement may be controlled at its existing boundary, the
      decision may not
- [x] no helper-only substitution
- [x] §11's Gate-2 condition decided from recorded source evidence

### CHECKPOINT D — regression / static
- [x] directly affected deterministic tests
- [x] focused integration
- [x] mutations restored and re-verified green
- [x] `ruff check` + `ruff format --check`
- [x] required static/type checks — local pyright UNAVAILABLE (host Node
      v10.19.0), recorded in §18.2i; CI's blocking strict pyright reports
      **0 errors**
- [x] exact-final-head CI green
- [x] no local full suite by default

### GATES
- [x] **Gate 1 NOT REQUIRED** — re-verified at the final head; no LLM-visible
      surface changed, and the one operator-facing string touched
      (`_suggest_lever`) is pinned byte-identical under TIDMAD
- [x] **Gate 2 NOT REQUIRED** — decided at C7 from Checkpoint-C evidence
      (§18.2h): the live admission/pricing decision is fully exercised and
      shown load-bearing, nothing 05b changes is device-dependent, and
      failure class 3 cannot fire. No Gate was launched

### READY FOR OPERATOR REVIEW
- [x] Checkpoints 0/A/B/C/D complete
- [x] Gate disposition re-verified at the final head
- [x] node/skill docs synchronized as the last pre-merge step
- [x] PR opened/updated; exact-final-head CI green
- [x] local HEAD == PR `headRefOid` == successful CI `headSha`
- [x] working tree clean

## 18. Implementation ledger

**Implementation authorized 2026-08-14.** Branch
`feat/generic-framework-step-05b-tuner-resource-time`, created from the
freeze marker `aa7e2131aee17d0049b3b67837f2c8b6a139d4e0` (verified equal to
`origin/master` at kickoff; frozen semantic content `ce880124` verified
present in history; working tree clean).

### 18.1 Implementation-time source re-enumeration

Every §0.3 anchor re-verified at `aa7e2131`. Line numbers below are the
CURRENT ones; where they differ from §0.3 the correction is noted.

**Phase P — Model-I/O / VRAM**

| Site | Current location | Note |
|---|---|---|
| `realize_shape` | `model_io_probe_skill.py:109-139` | unparameterized; precedence `fixed` → `PROBE_BATCH` (`:68`, `1`) → `PROBE_SYMBOLIC_EXTENT` (`:75`, `64`) |
| `declared_output_tensor` | `:142-209` | the form/fact rule §0.5 quotes, verbatim in its docstring |
| `expected_output_shape` | `:212-217` | thin wrapper over the two above |
| `build_model_input` | `:254-285` | second `realize_shape` caller |
| `ProbeConstructionError` | `:90-101` | the typed fail-closed |
| probe-authority consumers | `ml_model_implementor.py:1840`, `:1995`; `ml_code_validator_agent.py:646` | **confirmed** — exactly two nodes, three call sites, all optional-contract |
| `_build_probe_tensors` | `evaluate_vram_skill/wrapper.py:176-249` | `[B, 256, T]` literal at `:248` — **confirmed unchanged** |
| its single call site | `wrapper.py:588` | **confirmed** |
| `run_skill` | `wrapper.py:483` | `**kwargs` — the addition is additive |
| target dtype authority | `wrapper.py:214` `get_target_torch_dtype(LossConfig(...))` | unchanged by 05b |
| unknown-output refusal | `wrapper.py:230-240` | `UnknownOutputContractError` → `ValueError` |
| `IsolatedProbeSpec` | `isolated_probe.py:157-182` | frozen, JSON-only, transient IPC |
| pre-flight parent | `preflight_adapter.run_production_preflight:212-250` | builds the spec |
| worker rebuild | `preflight_worker_main.py:190-208` | `spec.get(...)` → `run_skill` |
| tuner pre-flight call | `ml_hyperparameter_tune_agent.py:4654` (import at `:54`) | **confirmed** |

**Correction to §0.2 finding (2).** The tuner holds no `ModelIOContract`
today — re-confirmed: `grep model_io agent/schemas/hyperparam_tuning.py`
returns nothing, and `ml_hyperparameter_tune_agent.py` imports no
model-io module.

**Phase D — estimator liveness census (C0 obligation, §4)**

Every estimator on the resource path, classified, each live one naming the
production caller that makes it live:

| Site | Class | Production caller |
|---|---|---|
| `workload_resolvers._validate_seg:49` (`profile or resolve_dataset_profile()`) | **production live** | reached by both live resolvers below |
| `workload_resolvers.resolve_inference_workload:139` (same shape) | **production live** | `execute_tools/inference_single.py:563` |
| `workload_resolvers.resolve_training_workload:53` | **production live** | `evaluate_time_skill/wrapper.py:515`, `training_skill/estimator.py:493`, `ml_hyperparameter_tune_agent.py:2914` |
| `workload_resolvers.resolve_scoring_workload:178` | **test-only** | no production caller; only `tests/unit/core/test_total_assembly.py:223,239` |
| `workload_resolvers.resolve_formal_workloads:210` | **dead** | zero callers anywhere, tests included |
| `inference_skill/estimator._total_inference_steps:200` (ambient at `:208`) | **production live** | `:295` ← `estimate_wall_time_seconds` ← `evaluate_time_skill/wrapper.py:781` |
| `evaluate_time_skill/wrapper.py:92` (`_suggest_lever`) | **production live** | `wrapper.py:950`, the over-budget suggestion string |
| `evaluate_time_skill/wrapper.py:357` (`_measure_ms_per_step`) | **production live** | the warm-up measurement path |
| `evaluate_time_skill/wrapper.py:767` (`run_skill`) | **production live** | tuner imports the skill at `:51` |
| `training_skill/estimator._total_train_steps:475` | **production live** | `training_skill/estimator.py:596` |
| `core/runtime_control/*` `40_000` seg fallbacks | **Step-07 owned** | out of scope (§3) |

**Out of scope for C2-C5 by §4's binding rule**: `resolve_scoring_workload`
(test-only) and `resolve_formal_workloads` (dead). `resolve_formal_workloads`
additionally carries an ambient fallback it can never exercise, because it
does not forward a `profile` to any of the three resolvers it calls — it is
recorded as debt, not fixed here. Genericizing either would create an
abstraction whose only consumer is a test or nothing at all.

**Confirmed §6 oracle status (do not duplicate):**

| Surface | Existing oracle |
|---|---|
| probe tensor SHAPES, all four reachable branches | `tests/unit/agent/evaluate_vram_skill/test_probe_target_contract.py` — hardcoded literals |
| workload-resolver profile-following | `tests/unit/execute_tools/test_step02a_c2_profile_injection.py` |
| RT1 step-count parity vs the trainer | `tests/unit/agent/tune_ml_hyperparam_agent/test_rt1_step_resolver.py`, `tests/unit/execute_tools/test_workload_resolvers.py` |
| pre-flight IPC composition / adapter | `tests/unit/agent/evaluate_vram_skill/test_preflight_ipc_composition.py`, `test_preflight_adapter.py`, `test_isolated_preflight.py` |
| `HardwareSnapshot`'s six-attribute surface | `test_hardware_snapshot_satisfies_run_skill_surface` |
| probe tensor DTYPES | **MISSING** → captured at C0 |
| the unknown-output refusal at the VRAM call site | **MISSING** → captured at C0 |

### 18.2 C0 / CHECKPOINT 0 — pre-edit baselines

- [x] probe tensor shape/dtype baseline captured for every reachable branch
- [x] live/dead estimator census recorded, each live one naming its caller
- [x] captured **BEFORE** any production edit
- [x] no duplication of existing Step-02/03/04a baselines

**New module**: `tests/unit/agent/evaluate_vram_skill/test_step05b_c0_probe_baselines.py`
(7 cases). It captures exactly the three failure classes no existing oracle
covers — each one a migration C2 could plausibly perform while every shape
assertion in the repository stayed green:

| Class | Baseline captured | The defect only it catches |
|---|---|---|
| 1 | target dtype per branch, as hardcoded literals: `classifier`+`ce` → `torch.int64`, `classifier`+`focal` → `torch.int64`, `regressor`+`smooth_l1` → `torch.float32`, `hybrid`+`smooth_l1` → `torch.float32`, `model_type=None` → `torch.float32`; input always `torch.int64` | dtype ownership silently moving from the loss to the contract. The existing module asserts only `dtype != torch.long` for the float branches, so a contract-sourced dtype would pass it |
| 2 | an UNREGISTERED `model_type` with a long-target loss still builds `([B,T] int64, [B,T] int64)` | `_build_probe_tensors` returns at `wrapper.py:217` *before* consulting `model_type`. A C2 that resolved the contract above that early return would start refusing a model that is probed successfully today |
| 3 | an UNREGISTERED `model_type` with a float-target loss raises `ValueError` naming the model | the `wrapper.py:230-240` refusal ceasing to fire. Nothing in the repository exercised that conversion from this call site; a C2 that fell back to the literal on a contract failure would be invisible |

**Deliberately NOT captured**: the four target SHAPES, already pinned as
hardcoded literals by `test_probe_target_contract.py`; and any branch whose
shape cannot move when a contract is supplied.

**Verification (C0)**

```text
command:  .venv/bin/python -m pytest \
            tests/unit/agent/evaluate_vram_skill/test_step05b_c0_probe_baselines.py \
            tests/unit/agent/evaluate_vram_skill/test_probe_target_contract.py -q
purpose:  the new baselines pass against byte-unchanged production code
result:   16 passed in 1.04s  (7 new + 9 existing)
tree:     `git status --porcelain` listed exactly ONE path, the new test
          module — zero production files modified
```

### 18.2b C1 — additive realizer parameterization

**Production change**: `agent/skills/model_io_probe_skill.py` only.
`realize_shape(tensor, *, batch=None, symbolic=None)`, plus two private
helpers (`_positive_extent`, `_reject_ambiguous_symbolic_extent`) and a
widened `ProbeConstructionError` docstring. **Zero existing call sites
edited**; no recipe constant changed.

**Tests**: `tests/unit/agent/skills/test_step05b_c1_realizer_extents.py`
(17 cases), reusing `tests/helpers/step04a_fixtures.tidmad_model_io()` so a
contract edit cannot make 04a's oracles and 05b's disagree.

**Design item resolved — C1 §6, "more than one symbolic axis".** The design
asked implementation to record whether one scalar is correct for the capacity
probe and to STOP rather than add per-axis parameters if it is not.

```text
Question:
  is one `symbolic` scalar semantically correct for every contract the
  capacity probe can be handed?

Audit evidence:
  Dimension.symbolic is a NAME (model_io_contract.py:109), and §4e makes
  the name the alignment mechanism: `T` on the input and `T` on the output
  are the SAME extent. The shipped TIDMAD contract declares exactly one
  distinct non-batch symbol (`T`) on each tensor, so one scalar answers it
  exactly.

Corrected understanding:
  correctness is not a property of the AXIS COUNT but of the DISTINCT
  SYMBOL count. Two axes sharing `T` are one alignment and one scalar is
  right; `H` and `W` are two independent alignments and one scalar would be
  a guess.

Implementation consequence:
  NOT a STOP. One scalar is kept, and the unrepresentable case fails closed
  — §0.5's "the form/contract combination is not representable" branch,
  which is a refusal, not a shape language. Per-axis extents would belong to
  whoever owns the contract schema.

Validation consequence:
  the guard is reachable ONLY when `symbolic` is explicitly supplied, so the
  legacy path realizes any contract exactly as before — pinned by
  `test_the_legacy_path_still_realizes_it`.
```

**C1 acceptance criteria**

| Criterion | Evidence |
|---|---|
| both arguments omitted → equal to the pre-change return | `test_shipped_contract_realizes_the_pre_05b_shapes` (`(1, 256, 64)` / `(1, 64)` as hardcoded literals), `test_the_derived_step04_helpers_are_unchanged` |
| `batch=B, symbolic=T` → declared `fixed` class extent still `256`; rank and axis order from the contract | `test_a_fixed_class_axis_ignores_the_symbolic_override`, `test_rank_and_axis_order_still_come_from_the_contract` (class-LAST case) |
| the four probe constants unchanged, asserted by value | `test_the_recipe_constants_are_unchanged` |
| `None`-sensitivity: `None` → recipe default, positive → verbatim, zero/negative → typed failure, never a fallback | `test_explicit_none_resolves_the_recipe_default`, `test_a_non_positive_extent_refuses_instead_of_falling_back` (6 params) |
| zero production call sites changed | `git diff --stat` for C1 lists one production file; the 474-case 04a consumer run needed no test edited |
| the typed error is the module's existing one | `test_the_refusal_is_the_modules_existing_typed_error` |

**C1 mutations** — every one RED, every one restored from clean source and
the tree re-verified green (17 passed):

| # | Mutation | Expected | Observed |
|---|---|---|---|
| M1 | batch-role check moved ABOVE the `fixed` check | RED | RED — `test_a_fixed_batch_role_axis_ignores_the_batch_override` |
| M2 | `batch_extent = batch or PROBE_BATCH` | RED | RED — all three `batch` zero/negative params |
| M3 | `symbolic_extent = symbolic or PROBE_SYMBOLIC_EXTENT` | RED | RED — all three `symbolic` zero/negative params |
| M4 | `PROBE_SYMBOLIC_EXTENT` 64 → 128 (default drift) | RED | RED — 5 cases across three classes |
| M5 | ambiguity guard disabled | RED | RED — `test_one_scalar_for_two_distinct_symbols_refuses` |

Each mutation asserted **exactly one** site before it was applied, and
`agent/**/__pycache__` was cleared before and after, so no verdict came from
a stale `.pyc`.

**Verification (C1)**

```text
command:  .venv/bin/python -m pytest \
            tests/unit/agent/skills/test_step05b_c1_realizer_extents.py -q
result:   17 passed in 0.92s

command:  .venv/bin/python -m pytest tests/unit/agent/test_step04a_stage_b_ladder.py \
            tests/unit/agent/ml_code_validator_agent \
            tests/unit/agent/ml_model_implementor tests/unit/agent/skills -q
purpose:  every existing Step-04a consumer of the realizer, unchanged
result:   474 passed in 6.11s — no existing 04a test required editing

lint:     ruff check + ruff format --check clean on both touched files
```

### 18.2c C2 — the VRAM probe accepts a contract (inert in production)

**Production change**: `agent/skills/evaluate_vram_skill/wrapper.py` only.
New helper `_contract_target_shape`; `_build_probe_tensors` and `run_skill`
gain `model_io_contract: ModelIOContract | None = None`; the `:588` call site
forwards it. Plus `evaluate_vram_skill.md`. No production caller supplies a
contract yet — asserted, not claimed
(`test_no_production_caller_supplies_a_contract_yet`).

**Tests**: `tests/unit/agent/evaluate_vram_skill/test_step05b_c2_contract_aware_probe.py`
(19 cases), reusing the Step-04a frozen fixtures.

**Design item resolved — how `hybrid` is treated.** C2's plan says the
declared form selects the tensor and the contract supplies the facts. Source
audit found that one of the three declarable words is not a form at all.

```text
Previous assumption (C2 §3):
  resolve the form with get_output_type, then hand it to
  declared_output_tensor. Three words, three forms.

Audit evidence:
  ml_models/models_format_sandbox.py:472-475 — "`hybrid` is never PRODUCED
  by the projection because it is not a tensor semantic (§8c) ... Inventing
  tensor semantics for it is forbidden."
  output_semantic_from_legacy() answers None for it (:491-514).
  ml_models/models_sandbox.py:355-365 — `fcnet` returns [B, T] under
  `smooth_l1` and [B, C, T] otherwise: its emitted shape is chosen by the
  LOSS.
  declared_output_tensor's else-branch is the CONTINUOUS form, so passing
  "hybrid" through it would return [B, T] — and today's hybrid target is
  [B, 256, T]. That is a TIDMAD parity break, failure class 3.

Corrected understanding:
  the contract governs where the DECLARATION carries a canonical tensor
  semantic. `hybrid` names an adapter whose shape depends on a fact
  (`loss_type`) that no Model-I/O contract owns, so there is nothing for the
  contract to supply.

Implementation consequence:
  `_contract_target_shape` asks the EXISTING projection
  (`output_semantic_from_legacy`) rather than restating a table, and returns
  None for `hybrid`/unrecognised — the shipped target, preserved exactly.
  This is an authority statement, not a fallback: the alternative is
  inventing a tensor semantic Step-03 §8c forbids.

Validation consequence:
  `test_hybrid_keeps_its_legacy_target_under_a_contract` pins it, including
  under a 16-class contrast contract. Recorded as a documented residue in
  §18.5, with Step 03 as its owner.
```

**Where the float branch is reachable, and why B1 uses the classifier form.**
`_build_probe_tensors` reaches the contract at all only for a float target
dtype. `validate_semantic_loss_compatibility` forbids CATEGORICAL + a
REGRESSION loss, but `loss_type="custom"` is in neither
`CLASSIFICATION_LOSSES` nor `REGRESSION_LOSSES`
(`models_format_sandbox.py:384-387`), so a `classifier` candidate with a
custom float-target loss is permitted — and that is the one reachable case
whose target actually carries the class alphabet. The `regressor` form drops
the class axis, so its target is `[B, T]` regardless of cardinality. B1's
observed fact is therefore the class extent under the **classifier** form.

**C2 acceptance criteria**

| Criterion | Evidence |
|---|---|
| `model_io_contract=None` → shapes and dtypes equal to the C0 baseline, every branch | `TestTheLegacyPathIsUntouched` (3 params) |
| shipped TIDMAD contract → target equals the no-contract shape **exactly** | `test_classifier_form_reproduces_the_broadcast_target`, `test_regressor_form_reproduces_the_two_d_target` (asserted against the legacy build, not a literal) |
| contrast contract → the class axis moves; `batch_size`/`seg_size` honoured at real values, not `1`/`64` | `test_the_target_equals_what_the_04a_authority_realizes` (4 params), `test_the_candidates_real_extents_are_honoured` |
| target dtype still from the loss in both paths | `test_a_contract_declaring_another_dtype_does_not_move_the_target` — the only case where the two answers differ, since under TIDMAD both are float32 |
| form/fact authority matches Step 04a — asserted against the authority, not a restated table | `test_the_target_equals_what_the_04a_authority_realizes` compares to `declared_output_tensor` + `realize_shape` |
| a `regressor` under a categorical contract is ACCEPTED at the class-axis-dropped shape | `test_a_regressor_under_a_categorical_contract_is_accepted` |
| a `classifier` under a contract with no class axis raises `ProbeConstructionError`, surfaced not swallowed | `test_a_classifier_under_a_contract_with_no_class_axis_refuses` |
| no production caller passes a contract yet | `test_no_production_caller_supplies_a_contract_yet` — a source assertion over `preflight_adapter` and `preflight_worker_main`, so C4's evidence cannot be confused with C2's |

**C2 mutations** — all RED, all restored, tree re-verified green (19 passed):

| # | Mutation | Observed |
|---|---|---|
| M6 | contract failure swallowed → fall back to the literal | RED — both refusal cases |
| M7 | realize at validation extents (`realize_shape(...)` with no overrides) | RED — 8 cases |
| M8 | dtype taken from `contract.output.dtype` instead of the loss | RED — the dtype-disagreement case |
| M9 | a local `classifier -> (B, 256, T)` table short-circuits the authority | RED — the 16-class case and the fail-closed case |

**Verification (C2)**

```text
command:  .venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill -q
purpose:  the whole VRAM subsystem, including every pre-existing oracle
result:   304 passed in 22.97s  (285 before C2 + 19 new)
lint:     ruff check + ruff format --check clean
```

### 18.2d C3 — contract transport across the pre-flight worker boundary

**Production change**: `isolated_probe.py` (`IsolatedProbeSpec` gains one
optional typed field), `preflight_worker_main.py` (rebuild + forward),
`preflight_adapter.py` (`run_production_preflight` gains the matching
optional parameter). Still inert: no production caller supplies a contract.

**Representation chosen — inline, not a path.** The `--model_io_json`
precedent uses a path because the training child is launched with argv and
has no other document to carry it on. `IsolatedProbeSpec` is *already* a
transient JSON IPC document with no manifest and no reader beyond its worker
(`isolated_probe.py:157-162`), so an inline typed field adds no second
lifetime to manage. The omit-vs-broken rule is the same one
`sandbox_executor.py:1309-1314` documents: **absence is legal and selects
the legacy path; present-but-unrebuildable fails loudly.**

**Tests**: `tests/unit/agent/evaluate_vram_skill/test_step05b_c3_contract_transport.py`
(6 cases). Two candidate cases were deliberately dropped as decoration: a
malformed contract on the PARENT side is rejected by the spec's own typed
field (a declaration already enforces it), and `HardwareSnapshot`'s read
surface is already pinned by `test_hardware_snapshot_satisfies_run_skill_surface`.

**A surviving mutation found a real gap — recorded because the fix is the
point.**

```text
Mutation M12 (first run):
  run_production_preflight builds the spec with model_io_contract=None.

Expected: RED.
Observed: GREEN — 24 passed.

Diagnosis (real gap, not an equivalent mutant):
  every transport assertion started from a spec that ALREADY carried the
  contract, so the PARENT hop — caller argument -> spec field — was never
  exercised. This is precisely the "serializes but never arrives" failure
  the module's docstring names, one hop earlier than where it was guarded.

Fix:
  test_the_parent_puts_it_on_the_spec — calls the real
  run_production_preflight with run_isolated_preflight stubbed to capture
  the constructed spec.

Re-run: M12 RED.
```

**C3 acceptance criteria**

| Criterion | Evidence |
|---|---|
| a contract placed on the spec ARRIVES at `run_skill` in the child, proven by a test that fails if the forwarding line is deleted | `test_the_worker_forwards_it_to_run_skill` (mutation M10 RED) |
| the caller's argument reaches the spec that crosses the boundary | `test_the_parent_puts_it_on_the_spec` (mutation M12 RED) |
| spec JSON without the field validates and behaves exactly as today | `test_a_spec_json_written_before_the_field_existed_validates`, `test_an_absent_field_forwards_none` |
| `HardwareSnapshot`'s attribute surface unchanged | the existing six-attribute test still passes untouched (310-case run) |
| a transport mutation is RED | M10, M11, M12 — all RED |

**C3 mutations**

| # | Mutation | Observed |
|---|---|---|
| M10 | worker forwards `None` instead of the rebuilt contract | RED |
| M11 | a malformed contract degrades to `None` instead of failing | RED |
| M12 | parent drops the field when constructing the spec | **survived first**, then RED after the gap above was closed |

**Verification (C3)**

```text
command:  .venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill -q
result:   310 passed in 21.87s
lint:     ruff check + ruff format clean across agent/ and tests/
```

**Test disposition — one C2 case UPGRADED, not deleted.**
`test_no_production_caller_supplies_a_contract_yet` grepped
`preflight_adapter`/`preflight_worker_main` for the field name, so C3's
legitimate transport made it RED. Its functional intent — *nothing acquires
a contract implicitly* — is durable; its implementation was a point-in-time
source grep that C3 was always going to invalidate and that never proved the
property anyway. Replaced by
`test_no_resource_consumer_resolves_a_contract_of_its_own`, which asserts
that no module in `agent/skills/evaluate_vram_skill/` reaches for
`load_task_config`, `resolve_model_io_contract` or `load_model_io_contract`.
That is the frozen invariant ("no live 05b resource consumer independently
re-reads an ambient source"), and it stays true and load-bearing through C4.

### 18.2e C4 — one run-bound contract reaches the resource path (first live consumer)

**Production change**: `workflows/task_config.py` (new
`run_bound_model_io_contract`), `core/sandbox_executor.py`
(`_write_model_io_config` delegates to it),
`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` (binds
it once in `run()` beside `run_profile`, passes it to
`run_production_preflight`).

**Transport chosen and why the design's first preference was unavailable** —
full evidence in §18.3 D-05b-1. In short: production launches the tuner node
as a subprocess and builds `HyperparamTuningInput` from argv alone, so no
parent holds a resolved contract that reaches it, and an optional schema
field would be `None` on the production chain. The design's conditional for
`load_task_config` is satisfied because the SAME expression already runs in
the same process to feed every training and inference child, and
`load_task_config` memoizes per absolute path — divergence is structurally
impossible, not merely unlikely. C4 extracts that expression into ONE
acquisition point so the claim is structural rather than a coincidence of
the cache.

**`run()` gains no new branch** — verified by reading the diff: one
assignment and one keyword argument, no conditional. This matters because
`run()` sits on pyright's strict complexity ceiling (CLAUDE.md), where the
259th branch node silently un-verifies every annotation in the function.

**Tests**: `tests/unit/agent/tune_ml_hyperparam_agent/test_step05b_c4_run_bound_contract.py`
(5 cases).

**C4 acceptance criteria**

| Criterion | Evidence |
|---|---|
| under TIDMAD the admission decision, resolved batch and forecast breakdown are unchanged | the bound value IS the shipped declaration (`test_the_bound_contract_is_the_shipped_declaration`), and C2 proved the shipped contract reproduces the legacy tensor exactly — so there is no term left that could move. Confirmed empirically by the 4,039-case run below |
| a task with no `model_io`, and a legacy caller supplying nothing, both take the legacy path | `test_a_prose_only_task_config_binds_no_contract`; `test_an_absent_field_forwards_none` (C3) |
| ONE run binding — the in-process wrapper and the child observe the same semantic value | the only production entry to the gate is `run_production_preflight` (audited: every other `evaluate_vram_skill` reference outside the package is a script or a comment), and the child's `run_skill` IS the in-process wrapper. C3's parent→spec→worker→`run_skill` chain carries one value end to end |
| no resource consumer performs its own ambient task-config resolution | `test_no_resource_consumer_resolves_a_contract_of_its_own` |
| `run()` gains no new branch | diff inspection, as the design requires |
| no new user-authored config, no new config hierarchy, no new CLI argument; old configs load unmigrated | `test_no_new_persisted_or_user_authored_field`, `test_the_tuner_cli_gained_no_argument`; `configs/task_config.yaml` is byte-unchanged |

**C4 mutations**

| # | Mutation | Expected | Observed |
|---|---|---|---|
| M13 | `_write_model_io_config` re-derives the contract itself instead of using the acquisition point | RED | RED — `test_the_training_child_receives_exactly_the_bound_contract` |
| M14 | the tuner passes `model_io_contract=None` to `run_production_preflight` | RED | **SURVIVED at C4 — see below** |

```text
Mutation M14 survivor — classified, not patched over.

Classification: REAL GAP at C4, by design, closed at Checkpoint C.

The tuner-to-pre-flight hop is a single call site inside `run()`, a ~2,500
line orchestrator. Exercising it means driving real production control flow,
which is exactly what Checkpoint C is defined to do (§9: "the real
production VRAM pre-flight / admission path ... it consumes the explicit
run-bound contract"). Adding a source-shape assertion here would produce a
green tick without an execution, and would then be cited as coverage the
project does not have.

So M14 is recorded as OPEN at C4 and re-run at Checkpoint C. C4's own claim
is narrower and true: the acquisition point is single (M13), and the value
it yields is the shipped declaration.
```

**Verification (C4)**

```text
command:  .venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent \
            tests/unit/agent/evaluate_vram_skill tests/unit/workflows \
            tests/unit/core -q
purpose:  the first commit that can change a real run's behaviour, against
          every suite that owns the touched surfaces
result:   4039 passed, 2 skipped in 372.68s

command:  .venv/bin/python -m pytest \
            tests/unit/agent/tune_ml_hyperparam_agent/test_step05b_c4_run_bound_contract.py -q
result:   5 passed in 1.23s
```

### 18.2f C5 — run-bound `DatasetProfile` on the live workload/time path

**Production change** — the ambient `profile or resolve_dataset_profile()`
shape is gone from every production-live resource/time consumer, and the
parameter is **required** at each one:

| Site | Before | After |
|---|---|---|
| `workload_resolvers._validate_seg` | `profile: … = None`, ambient fallback | `profile: DatasetProfile`, required |
| `workload_resolvers.resolve_training_workload` | optional | required keyword |
| `workload_resolvers.resolve_inference_workload` | optional + its own ambient read | required keyword |
| `inference_skill/estimator._total_inference_steps` | optional, ambient fallback | required |
| `inference_skill/estimator.estimate_wall_time_seconds` | no parameter | required `dataset_profile` |
| `training_skill/estimator._total_train_steps` | no parameter | required `profile` |
| `training_skill/estimator.estimate_wall_time_seconds` | no parameter | required `dataset_profile` |
| `evaluate_time_skill/wrapper._suggest_lever` | ambient read | `psd_segment_length` supplied |
| `evaluate_time_skill/wrapper._measure_ms_per_step` | ambient read | required `profile` |
| `evaluate_time_skill/wrapper._store_reuse_decision` | (via the resolver) | required `profile` |
| `evaluate_time_skill/wrapper.run_skill` | ambient read | **required `dataset_profile` kwarg**, typed-checked at entry |

**Required, not optional-with-fallback** — every production caller can supply
it (the 05a precedent), so a fallback would be permission no production
caller exercises, and the one place it *would* be exercised is the defect.
Pinned by `test_the_profile_is_required_not_optional_with_a_fallback`.

**Production callers now supplying it**

| Caller | Source of the value |
|---|---|
| `ml_hyperparameter_tune_agent._run_time_preflight` | `run_profile`, the run's ONE profile bound at `run()` (05a) |
| `ml_hyperparameter_tune_agent._check_and_record_guardrail_skip` → `_resolve_guardrail_steps` | the same `run_profile` |
| `execute_tools/inference_single.py` | the profile the subprocess already loaded at its argv boundary (`:334-339`) — **the one-argument fix**: the value was in scope and simply was not passed |
| `agent/utils/proposer_preflight.estimate_proposal_time` | acquires at its own boundary — see the liveness finding below |

**Liveness finding — `estimate_proposal_time` is NOT production-live.**

```text
Previous assumption:
  the proposer's advisory pre-flight is a live consumer, so it needs the
  run-bound profile threaded to it.

Audit evidence:
  its only non-test caller is production_estimator_factory._static
  (core/runtime_control/estimator.py:236-250), which is reached ONLY through
  DefaultRuntimeEstimator.estimate(). `grep "\.estimate("` over core/, nodes/,
  agent/, workflows/ and scripts/ finds NO production call — only tests.
  Every production consumer of shared_runtime_components() reads
  `estimator.identity` and the policy, never the estimate; the estimator's
  own docstring (:215-226) says consumers with better evidence bypass it.

Corrected understanding:
  test-only. §4's binding rule therefore forbids genericizing it, and
  threading a run-bound profile to it would also require editing
  core/runtime_control — explicitly OUT OF SCOPE.

Implementation consequence:
  it acquires at its own boundary in one line and says so in a comment. Not
  genericized; not left broken either.
```

**Out of scope, recorded**: `resolve_scoring_workload` (test-only) and
`resolve_formal_workloads` (dead — zero callers anywhere). The latter is
given a `profile` parameter it forwards, for signature coherence with the
callees it would break against; that is not genericization, and it is
recorded rather than deleted.

**Four `profile or resolve_dataset_profile()` sites remain in the
repository**, all outside 05b's rollback boundary and all on data/execution
paths rather than resource/time ones: `train_engine_sandbox.py:93`, `:344`,
`:868` and `scoring_utils.py:602`. Recorded as Step-02/05a surfaces; not
touched here.

**Tests**: `tests/unit/execute_tools/test_step05b_c5_run_bound_profile.py`
(10 cases). ~100 call sites across 19 existing modules were updated to supply
the now-required argument.

**Two existing contrast tests were UPGRADED rather than mechanically
patched** — the distinction matters, because patching them with
`TIDMAD_PROFILE` would have silently destroyed what they test:

| Test | Why a mechanical patch was wrong | Disposition |
|---|---|---|
| `test_step02a_c2_profile_injection._workload_ml_per_psd` | it binds a CONTRAST profile and asserts the geometry follows; hardcoding `TIDMAD_PROFILE` would return the TIDMAD answer under the contrast and the rung would silently stop testing anything | now calls `resolve_dataset_profile()` and passes the result. Same property; the acquisition is where 05b puts it — at the caller, once, explicitly |
| `test_step02a_c5_legality_dedup.test_the_time_skill_message_follows_a_contrast_declaration` | same shape, and it FAILED loudly when patched with `TIDMAD_PROFILE` (`'2,048,000' in '…10,000,000…'`) — the contrast caught its own mis-patch | same fix |

Both now prove *"the consumer follows the declaration it is given"*; the
binding half — *"the production caller gives it the run-bound one"* — is
subcase B2 and Checkpoint C.

**C5 acceptance criteria**

| Criterion | Evidence |
|---|---|
| under TIDMAD the resolvers return values equal to the C0 baseline, field by field including `detail["output_bytes"]` | `TestTidmadParity` — hardcoded expectations (480,000 steps; 960,000 samples/epoch; 8,000 ML/PSD; 15,000 inference batches; `output_bytes = 120 × 10,000,000 × 2`) |
| Stage-B B2 passes: a PSD-only contrast moves the derived terms and no calibration constant | `TestDerivedTermsFollowTheBoundProfile` (3 cases) |
| an ambient-regression mutation is RED | M15, M16 below |
| `grep "profile or resolve_dataset_profile()"` over the live resource path returns zero | `test_no_live_resource_consumer_resolves_a_profile_of_its_own` — the semantic guard is the property, this is its supporting form |
| default visited sequence, seeds and ordering unchanged | C5 touches no strategy, portion, seed or ordering code; the tuner, sample-set and DataScope suites are green in the C5 run |

**C5 mutations**

| # | Mutation | Observed | Note |
|---|---|---|---|
| M15 | restore `profile = profile or resolve_dataset_profile()` in `_validate_seg` | RED | caught by the ARCHITECTURAL guard only — and that is the honest result. With the argument still supplied, `x or ambient` returns the supplied value, so no value assertion can see it. This is exactly why the two guard shapes both exist |
| M16 | `output_bytes` reads the ambient profile instead of the bound one | RED | caught by both the architectural guard and the B2 output-byte case |

**Verification (C5)**

```text
command:  .venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent \
            tests/unit/execute_tools tests/unit/agent/test_estimator_input_resolution.py \
            tests/unit/agent/test_estimator_predicates_not_names.py \
            tests/unit/agent/inference_skill tests/unit/agent/training_skill \
            tests/unit/agent/utils -q
result:   2116 passed, 1 skipped in 288.28s   (after the call-site migration)

command:  .venv/bin/python -m pytest \
            tests/unit/execute_tools/test_step05b_c5_run_bound_profile.py -q
result:   10 passed in 0.83s
lint:     ruff check + ruff format clean across tests/unit
```

### 18.2g C6 — calibration-preservation audit

**Zero production files modified.** One test module, one roadmap row.

**The evidence ladder, applied — and it stopped early almost everywhere.**

| §2 value | Layer | Evidence |
|---|---|---|
| `_MAX_BATCH_TIMESTEPS` = `800_000` | **1 — existing oracle** | `tests/unit/agent/evaluate_vram_skill/test_compute_intensity.py:26` — `assert _MAX_BATCH_TIMESTEPS == 800_000`, a hardcoded literal |
| batch candidate table `(64, 32, 16, 8, 4, 2, 1)` | **1 — existing oracle** | `tests/unit/agent/evaluate_vram_skill/test_batch_resolver.py:291` — literal tuple |
| `_ROLE_DEFAULT_RSS_GB` 40 / 60 / 24 GiB | **1 — existing oracle** | `tests/unit/core/test_sandbox_rlimit.py:115` — parametrized against hardcoded per-role values, including the 60 GiB inference cap CLAUDE.md pins |
| `SEG_SIZE_BOUNDS` = `(2500, 40_000)` | **3 — static diff** | `evaluate_time_skill/trigger_policy.py` is not in 05b's touched-file list. The PR cannot re-own a constant in a file it does not open |
| `_INFERENCE_VS_TRAINING_RATIO` = `2.7` | **4 — one pin added** | see below |

**The one pin, and why layer 4 genuinely applied.** No test in the
repository asserts the ratio's VALUE. Several import the symbol and multiply
by it, which passes for any number it holds. And Step 05b **edits the module
it lives in** — C5 gave `_total_inference_steps` and
`estimate_wall_time_seconds` a required Dataset Profile, three and ~180
lines from the constant. An empirical median from a two-architecture
calibration table, documented as blunt and awaiting more data, sitting in a
file a genericization PR is editing, with no oracle on its value: that is
precisely the case the ladder reserves layer 4 for.

`tests/unit/agent/inference_skill/test_step05b_c6_calibration_pin.py`, two
cases. The second is **reachability, not decoration**: a pinned constant
nothing multiplies by is a value, not a calibration, so if a refactor
stopped applying the ratio the value pin would stay green while every
inference forecast silently changed.

| # | Mutation | Observed |
|---|---|---|
| M17 | `2.7` → `3.1` | RED — both cases |
| M18 | the static formula stops multiplying by the ratio | RED — the reachability case only, which is exactly its job |

**Explicitly NOT done**: a pin and a mutation for every untouched constant.
Asserting that a constant in a module 05b never opens still equals itself is
the "test what a declaration already enforces" pattern CLAUDE.md forbids,
and it would bury the one pin that matters.

**§14 roadmap row — the speculative owner retired.** `docs/design/
siderius_generic_framework_upgrade.md:1232` named a *"§7d resolver"* as the
owner of a convergence that §3's audit refutes. The row now records the
finding: three unrelated semantics (planned-identity default, calibration
trigger bound, campaign fixture data) share a number because TIDMAD's usable
segmentation happens to sit there, the measurement-identity defaults are
Step-07 owned, and **no resolver is introduced**. The row's narrative
counterpart at `:1550` already carried this finding from design time; only
the table was stale.

*(Convention note: 05a synced the roadmap post-merge in its own docs-only
commit. This edit is made here because C6's scope names the row explicitly
and the finding is frozen design content, not an implementation outcome —
the table is being brought into line with prose already on master.)*

**Verification (C6)**

```text
command:  .venv/bin/python -m pytest tests/unit/agent/inference_skill -q
result:   32 passed in 0.88s  (30 existing + 2 new)
tree:     zero production files modified by this commit
```

### 18.2h C7 — Stage-B rung, Checkpoint C, and the Gate-2 decision

**Zero production files modified.** Evidence only.

#### Checkpoint C — the real production control flow

`tests/integration/nodes/test_step05b_checkpoint_c.py`, 5 cases,
**13.0 s**. Placed in `tests/integration/` deliberately: C-P spawns a real
worker process, and `tests/unit/agent/tune_ml_hyperparam_agent/conftest.py`
exists to forbid exactly that in the unit suite — a test that spawns the
worker under a stub that stopped intercepting *hangs* rather than fails. CI
is unit + static by design; this module is run locally and recorded here.

**C-P — the real VRAM pre-flight, pricing and admission.** Nothing that
makes a decision is stubbed, and **the measurement is not stubbed either**:

```text
run_production_preflight            the tuner's own production adapter
  -> IsolatedProbeSpec              real, typed, frozen
  -> spec.json                      real JSON IPC
  -> subprocess.Popen               a REAL spawned worker
  -> preflight_worker_main          real contract rebuild
  -> run_skill                      real
  -> _build_probe_tensors           REAL realization from the run-bound contract
  -> probe_activation_footprint     REAL forward + backward (CPU)
  -> _compose_training_peak         real
  -> resolve_inference_batch        real, all 7 candidates
  -> admission verdict              real, against the parent's frozen cap
```

The CPU probe costs ~2 s for a bounded candidate, so full fidelity was
affordable and no measurement boundary needed controlling at all.

**C-P is also B1 at production scale, single-axis.** ONE candidate (punet,
16 classes, `seg=1024`, `B=1`), one snapshot, one cap, one loss. The ONLY
variable is the run-bound contract:

| Contract | Outcome |
|---|---|
| 16-class, bound | probe realizes `[1, 16, 1024]`; `status=success`, `feasible=True`, `0.23 GB ≤ 8.0 GB` |
| absent | legacy `[B, 256, T]` literal against a 16-logit model → `RuntimeError: The size of tensor a (16) must match the size of tensor b (256) at non-singleton dimension 1` |

The second outcome is the **V21 PR A defect verbatim** — a contract defect
wearing a resource-error costume. Reproducing it is what proves the contract
is *load-bearing* rather than merely present: a transport that dropped it
anywhere between the tuner and the worker would make the first call fail
exactly like the second.

**C-D — the real workload/time path.** The real `HyperparamTuningAgent.run()`
reaches its real `_run_time_preflight`, and the recorded call sites show
both run-bound values leaving the tuner (the contract to the pre-flight, the
profile to the time gate). The real `evaluate_time_skill.run_skill` then
resolves real workloads from that profile and returns a real verdict.

```text
Deviation (bounded):
  the live time gate is invoked from the captured production arguments
  rather than nested inside run().

Reason:
  the fake plan's candidate is a full-scale punet at seg_size=40000 and the
  tuner harness patches os.path.exists -> True, so a real invocation nested
  in run() enters the warm-up path and reads real HDF5 files. That is a
  HARNESS artefact, not production behaviour.

Impact:
  the chain is established in two halves that meet at the same values — the
  tuner PASSES the run-bound profile to the live gate, and the live gate
  RESOLVES real workloads from it. Neither half is a helper; both are
  production entry points.
```

**A defect this checkpoint found in its own first draft, recorded because
the fix is the point.** The first C-D version delegated the time gate to the
package's shared `_mock_run_skill`, which has no `evaluate_time_skill` entry
— so the tuner received `{"status": "error"}` and raised `Time check error:
unknown skill`, aborting the round *after* the capture. The transport
assertions passed anyway. Under mutation M14 the test then went RED for the
abort rather than for the missing contract: a mutation "caught" for the
wrong reason is not evidence. Fixed by returning a well-formed verdict and
asserting `output.status == "completed"`, so a later mutation cannot red for
an unrelated abort. Run time also fell from 161 s to 13 s.

#### Stage-B rung `05b-B`

`tests/unit/agent/test_step05b_stage_b_rung.py`, 5 cases. The observations
live where the behaviour lives (C2, C5, Checkpoint C); what this module adds
is the **rung** property — that each contrast is single-axis — because a
contrast that quietly moved a second fact would make every observation pass
while proving nothing about which authority the term followed.

| Subcase | Machine-checked atomicity |
|---|---|
| **B1** | `_diff(tidmad_model_io(256), tidmad_model_io(16)) == ["output.axes[1].dimension.fixed"]` — exactly ONE leaf |
| **B2** | `_diff(TIDMAD_PROFILE, contrast) == ["dataset.psd_segment_length"]` — exactly ONE leaf |
| both | `_INFERENCE_VS_TRAINING_RATIO`, `_MAX_BATCH_TIMESTEPS`, the batch table, `SEG_SIZE_BOUNDS` and `_ROLE_DEFAULT_RSS_GB` asserted at their literal values |

#### Mutation families — all five RED

| Family | Mutations | Result |
|---|---|---|
| probe-realization regression | M7 (validation extents), M9 (a local form table) | RED |
| contract-transport drop | M10 (worker), M11 (malformed → `None`), M12 (parent spec), **M14 (the tuner call site)** | RED |
| ambient profile regression | M15 (`_validate_seg` fallback), M16 (`output_bytes`), **M19 (the tuner's time-gate argument)** | RED |
| ambient task-config re-read | M20 (`load_task_config` inside the VRAM package) | RED |
| calibration drift | M17 (`2.7` → `3.1`), M18 (ratio no longer applied) | RED |

**M14 is closed.** C4 recorded it OPEN because the tuner→pre-flight hop is a
single line inside a ~2,500-line orchestrator and a source-shape assertion
would have been a green tick with no execution behind it. Checkpoint C-D
executes it, and M14 now reds on the assertion that names the defect.

**Mutation hygiene incident, recorded.** A batch that mutated two sites in
the same file was interrupted before its restore ran, leaving
`dataset_profile=TIDMAD_PROFILE if False else run_profile` on disk. It was
caught by `git diff` before any test verdict was taken from it, the file was
restored from the index, and M19 was re-run against the correct site. This
is the stale-mutation hazard the project's own hygiene rule names; the guard
that worked was checking `git status` between mutations rather than trusting
the harness's restore.

#### GATE-2 DECISION — **NOT REQUIRED**

§11's condition is semantic: *deterministic production-path evidence fully
exercises the live admission/pricing decision → Gate 2 NOT REQUIRED.*

**The evidence that settles it, not a preference:**

1. **The decision itself is real and unstubbed.** C-P executes the entire
   production chain above, including a spawned worker, a real probe forward
   and backward, real peak composition, real batch resolution and the real
   admission comparison. The design permits controlling the measurement at
   its existing boundary; **nothing needed controlling** — the probe runs.
2. **The decision is shown to be load-bearing**, not merely reached: the
   same candidate with the contract dropped fails with the exact V21 PR A
   shape error. A Gate could not demonstrate that more sharply.
3. **Nothing 05b changes is device-dependent.** The PR changes (a) which
   SHAPE the probe target is realized at and (b) which profile the workload
   resolvers read. The shape is realized before any `.to(device)`, and the
   workload math is integer arithmetic. Every device-dependent term —
   `cuda_context_bytes`, the cudnn workspace, the RSS caps, the intensity
   cap — is calibration this PR provably does not touch (C6).
4. **Failure class 3 cannot fire.** Under TIDMAD the shipped contract
   reproduces the legacy tensor *by equality* (C2), and the profile
   threading is value-identical (C5 parity, hardcoded expectations). There
   is no term left that a real run could move.

A real-hardware Gate would re-measure CUDA context and allocator behaviour —
quantities 05b does not touch and whose values are pinned elsewhere. It
would add cost and no unique evidence.

**Gate 1 — re-verified NOT REQUIRED.** No LLM-visible surface changed. The
one operator-facing string 05b touches is `_suggest_lever`'s advisory, whose
bytes are pinned byte-identical under TIDMAD by the existing
`test_the_time_skill_message_is_byte_identical_under_tidmad`. The §11 flip
condition — *a resource literal reaching a rendered prompt* — did not occur.

**Verification (C7)**

```text
command:  .venv/bin/python -m pytest tests/integration/nodes/test_step05b_checkpoint_c.py -q
result:   5 passed in 13.01s

command:  .venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill \
            tests/unit/agent/test_step05b_stage_b_rung.py \
            tests/unit/execute_tools/test_step05b_c5_run_bound_profile.py \
            tests/unit/agent/skills/test_step05b_c1_realizer_extents.py \
            tests/unit/agent/inference_skill -q
result:   374 passed in 21.54s
mutations: M7, M9, M10, M11, M12, M14, M15, M16, M17, M18, M19, M20 — all RED,
           all restored, tree verified clean, baselines re-run green
```

### 18.2i C8 / CHECKPOINT D — terminal validation, docs, CI

**Doc sync (the last pre-merge step).** `evaluate_vram_skill.md` documents the
new optional kwarg, the three deliberate non-changes (dtype stays with the
loss, the class-index branch returns first, `hybrid` keeps its shipped
target) and the fail-loud rule. The tuner node doc gains a *"Resource and
time planning (Step-05b)"* section beside the existing Step-02b
selection-topology one — the same rule applied to two questions: what a round
may SELECT and what the gates may PRICE. Every documented symbol was verified
present in the merged source, not quoted from memory.

**Terminal validation, from a clean tree** (`git status --porcelain` empty
before the run — the PR3-L2 preflight guard reds on a dirty tree, and it did
exactly that earlier in this PR, which is the guard working):

```text
command:  .venv/bin/python -m pytest tests/unit -q -p no:randomly
result:   9254 passed, 3 skipped in 586.98s

command:  .venv/bin/python -m pytest tests/integration/nodes/test_step05b_checkpoint_c.py -q
result:   5 passed in 13.01s

command:  .venv/bin/python -m ruff check .          -> All checks passed
command:  .venv/bin/python -m ruff format --check . -> 881 files already formatted
```

**Local pyright — UNAVAILABLE, recorded, not claimed.** `pyright-python`
resolves this host's Node and dies with `SyntaxError: Unexpected token =`;
`node --version` is **v10.19.0**. This is the 05a precedent verbatim. No
local type-check claim is made anywhere in this PR; the authority is CI's
blocking strict pyright.

**Exact-final-head CI**

```text
PR:        #211
run:       31851753764
headSha:   d4a5414198235c1b57d62e72df43da0a68c4e4fb
conclusion: success

  ruff check / ruff format          pass
  pyright (strict, BLOCKING)        0 errors, 4 warnings
                                    — all four pre-existing, in
                                      core/runtime_control/bootstrap.py,
                                      core/runtime_control/gpu_requirement.py
                                      and scripts/legacy_fcnet_timing.py,
                                      none of which this PR touches
  pytest (unit, no integration)     9228 passed, 26 skipped in 669.09s
```

The local and CI counts differ (9,254/3 vs 9,228/26) because CI deselects the
markers this project's CI is defined to exclude — `real_run` and integration.
Both are green; the scope of each claim is stated rather than merged.

### 18.3 Decisions taken during implementation

**D-05b-1 — the explicit run-bound `ModelIOContract` transport (C4).**

*Question.* C4's preferred order is (1) reuse an already-resolved contract in
the run/workflow context, (2) a minimum optional typed runtime field,
(3) an existing run-sidecar/spec boundary. Which does current source support?

*Evidence.*

```text
scripts/run_comparison.py:688-700
    production launches the TUNER NODE AS A SUBPROCESS, argv only.

ml_hyperparameter_tune_agent.py:6862-6965  (main())
    builds `input_dict` from argv alone. `task_description` is never set
    there and stays at its "" default — so the one existing precedent for a
    task-config-derived field on HyperparamTuningInput is populated ONLY on
    the in-process workflow path (workflows/model_exploration.py:2674).

core/sandbox_executor.py:1196-1218  (_write_model_io_config)
    ForwardContract(**load_task_config()["forward_contract"]).model_io
    — executed IN THE TUNER'S OWN PROCESS, and materialized to
    --model_io_json for training (:1344) and inference (:1686).

workflows/task_config.py:120-123
    load_task_config memoizes per ABSOLUTE PATH in a process-level _CACHE.

workflows/task_config.py:163-176
    resolve_model_io_contract is called THERE — the existing resolution
    boundary.
```

*Corrected understanding.* Route 1 is unavailable: no parent process holds a
resolved contract that reaches the production tuner. Route 2 (an optional
field on `HyperparamTuningInput`) would be `None` on the production chain
unless the tuner itself read the task config — i.e. the same acquisition
question moved one hop, plus a schema field that production never populates.

*Choice.* The tuner binds the contract ONCE per run from the SAME expression
that already produces the run's binding for every training and inference
child, and threads it explicitly through
`run_production_preflight → IsolatedProbeSpec → worker → run_skill`.

*Why this satisfies C4's conditional* — *"permitted only if source proves it
is already the canonical run-bound input for that node and cannot diverge
from the actual run binding"*: the same expression already runs in the same
process, and `load_task_config`'s per-path memoization makes both reads
return the same parsed object. Divergence is structurally impossible, not
merely unlikely. Resolution already happened at the existing boundary, so
05b adds no second resolution point.

*Strengthening.* To make the single-authority claim structural rather than
coincidental, the expression is extracted into ONE helper and
`_write_model_io_config` delegates to it. See DEV-1.

*Failure-ordering analysis (§15's "unrelated failure newly fatal" check).*
Binding at `run()` moves a `load_task_config` failure earlier — from the
first `execute_training` to tuner startup. No run that previously SUCCEEDED
can now fail: every production run that trains already executes that exact
expression. The one behavioural delta is a degenerate run in which every
candidate is refused at pre-flight and no training ever starts; such a run
would previously have completed with all-skipped records despite an
unreadable task config, and will now refuse at startup. That is the
designed fail-closed direction (§0.5: an explicit contract lost or malformed
in transport fails loudly), and the source in question is the *related* one
— after C4 the pre-flight genuinely consumes it. Recorded, not treated as a
MATERIAL STOP.

**D-05b-2 — only the FLOAT target branch is contract-derived (C2).**

`_build_probe_tensors` returns early at `wrapper.py:217-218` for a long
target dtype with a `[B, T]` class-index target. That branch carries no
`256` and no contract-owned extent, and §2's classification table names
exactly one task-shaped site — the `[B, 256, T]` literal at `:248`. Routing
the long branch through `declared_output_tensor` would add behaviour surface
with no §2 mandate and would make an unregistered model with `ce` newly
refusable (C0 class 2 pins that it must not). Bounded scope decision.

### 18.4 Deviations

**DEV-1 (bounded).** §13's rollback table does not list
`workflows/task_config.py` or `core/sandbox_executor.py`. C4 adds one shared
run-bound-contract helper in `workflows/task_config.py` and delegates
`SandboxExecutor._write_model_io_config` to it, behaviour-identical.
*Reason*: without it the tuner and the training/inference children would
read the same expression at two sites, and "cannot diverge" would rest on
the memoization cache rather than on there being one acquisition point.
*Impact*: two files added to the rollback boundary; both changes are
additive and revert with C4. *Validation*: the delegation is covered by the
existing `--model_io_json` transport tests plus a C4 case asserting the
tuner and the sandbox writer resolve the same contract value.

## 19. Remaining operator decisions

**NONE outstanding.** Two were raised by the revision-2 audit and are now
decided:

| Decision | Resolution |
|---|---|
| **OD-05b-1** — how the resource gate consumes the probe authority, given that `realize_shape` realizes at validation extents and no contract reaches the gate | **Option A**: additively parameterize `realize_shape` and plumb an optional contract (§0.2). Options B and C recorded as rejected, with reasons |
| **OD-05b-2** — whether to re-anchor rev-1's `13b08550` citations | **Yes**: §0.3 is the corrected table; the original blocks are preserved as chronology |

Revision 3 added five more, all decided:

| Decision | Resolution |
|---|---|
| **OD-05b-3** — decomposition, re-tested after the scope grew | **ONE PR**, two internal phases P and D (§0.4). Not child PRs |
| **OD-05b-4** — output-form authority when contract and candidate differ | **Inherit Step 04a unchanged** (§0.5): the declaration selects the form, the contract supplies the facts. A canonical-semantic difference is a supported compatibility surface, never a stop condition |
| **OD-05b-5** — how the contract reaches the resource path | Freeze the **semantic** property (one explicit run-bound value, no ambient re-read, same binding parent and child); the transport is chosen at C4 from current source. An optional typed runtime field is permitted (§20) |
| **OD-05b-6** — Stage-B coverage | **ONE rung, TWO atomic subcases** B1/B2 (§8), because 05b migrates two independent authority families |
| **OD-05b-7** — calibration evidence | **Preservation audit with a cheapest-sufficient evidence ladder** (C6); no repo-wide pin campaign |

Everything else is resolved from source: the classification table (§2) by the
constants' documented derivations, the seg-fallback disposition (§3) by the
sites' differing meanings, and the Gate disposition (§11) by a semantic
condition that implementation evidence settles at C7.

## 20. Configuration-architecture preservation (Step-05 cross-cutting invariant)

Binding for this PR (roadmap §15.1a). **Ambient → injected derivation does
NOT mean copying authorities into persisted configuration.** The required
architecture is:

```text
already-resolved DatasetProfile / ModelIOContract
    -> runtime typed/function transport
    -> resource consumer
```

Explicitly forbidden without a MATERIAL STOP and design review:

- a `dataset_profile` copy inside train config;
- a `model_io` copy inside resource config;
- a new persisted workload-term config;
- any new **user-authored or persisted** configuration hierarchy for resource
  terms.

**What this invariant does NOT forbid.** An **optional typed runtime
transport** — a node-input field, a function parameter, or a field on a
transient IPC spec — is the *implementation* of "runtime typed/function
transport" above, not a breach of it. The distinction is authorship and
persistence:

| Shape | Verdict |
|---|---|
| a new user-authored YAML block / CLI argument / persisted config key | **forbidden** |
| a new **required** field on an existing user-facing config | **forbidden** |
| an **optional** typed runtime field on a node protocol, defaulting to `None` and preserving legacy callers | **allowed** — it is transport |
| a field on the transient `IsolatedProbeSpec` IPC document (no manifest, no reader beyond its worker) | **allowed** — it is transport |

C4 chooses the minimum explicit transport from current source. Stretching this
invariant to forbid a typed node input would leave only *ambient re-reads* as
the available mechanism — which is the defect the invariant exists to prevent.

Frozen compatibility:

| Surface | 05b effect |
|---|---|
| model config | **unchanged — legacy loads** |
| loss config | **unchanged — legacy loads** |
| train config | **unchanged — legacy loads** |
| `TrialConfig` / tuner config | **unchanged** |
| calibration constants | **values unchanged**, ownership unchanged |
| CLI / argv | **unchanged**, unless the current resource boundary already differs — recorded if so |
| historical run replay | **preserved — no migration required** |

Stage-A property: *a representative historical TIDMAD serialized
configuration loads under post-05b code without migration and resolves to the
same effective model/loss/train/tuner semantics*, provable by deterministic
config resolution.

If implementation proves a new field is genuinely unavoidable, that is a
**MATERIAL STOP**, not permission to widen the config system.
