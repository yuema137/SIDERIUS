# Step 05c — Tuner execution contracts — detailed design

Part of **Step 05** (roadmap §15 step 5, §7c). Step 05's three submodule
designs jointly constitute the Step-05 acceptance entry (roadmap §19); the
Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **PR 05C DESIGN — FROZEN. OPERATOR APPROVED FOR IMPLEMENTATION.** Frozen 2026-08-15 (UTC) at revision 3: active census repaired, transport-vs-reconstruction decided (§3.2a), spec scope narrowed to the facts actually migrated (§1), encoding literals classified individually (§2.2), artifact equality defined (§4.1). **Remaining operator decisions: NONE.** Implementation NOT started — see §0.0 |
| Frozen semantic content | **`fe73f982ffa4b86aca1eb3e28d18ddacf3af5d32`** — the operator-approved design object |
| Design base | **re-anchored to `226d4e9f`** (master after 05a `cfb3b1c7` and 05b `5ce205d3` merged). Revision 1 was written against `13b08550`; §0.2 is the corrected anchor table and lists six citations that did not survive audit |
| Decomposition | **ONE PR**, internal semantic checkpoints **C0–C9** (§14) |
| Deliverable ownership | producer-side **provisional** extraction; final ownership **OPEN**; **Step 06** is the next mandatory confirm-or-say-why review (§3) |
| Depends on | **Step 02** (Dataset Profile: channels, `ValueEncoding`) · **Step 03** (`ModelIOContract` decode rule) |
| Roadmap row | §15.1 `§7c Tuner execution contracts` |
| Risk | **Highest of the three** — it changes real execution behavior |

---

## 0.0 Freeze record

| | |
|---|---|
| Status | **PR 05C DESIGN — FROZEN. OPERATOR APPROVED FOR IMPLEMENTATION.** |
| Frozen semantic design content SHA | `fe73f982ffa4b86aca1eb3e28d18ddacf3af5d32` |
| Design base | `226d4e9f` |
| Freeze date | **2026-08-15 (UTC)** |
| Decomposition | **ONE PR** |
| Internal semantic checkpoints | **C0–C9** (§14; also Checkpoints 0/A/B/C/D) |
| Deliverable ownership | producer-side **provisional** extraction; final ownership **OPEN**; **Step 06** is the next mandatory confirm-or-say-why ownership review |
| Remaining operator decisions | **NONE** (§16) |
| Implementation state | **NOT STARTED** — §15 ledger empty |

**The freeze does not itself begin implementation.** Implementation
authorization is a separate operator act and will be supplied in a fresh
session together with the filled Implementation Working Rules. Freezing the
design authorizes nothing to be built, tested or gated today.

**What this freeze does NOT fix.** These are implementation latitude and may
be decided at implementation time without a further operator decision:

- the exact **Git commit count** (§14 freezes the semantic sequence, not the
  number of commits);
- exact **helper / module placement**;
- exact **source line numbers** — every citation in this document is a reading
  aid captured at `226d4e9f`, not a contract (§14);
- exact **test-file decomposition**;
- exact **mutation implementation** — §14/C7 requires evidence per semantic
  failure family, deliberately **not** a frozen per-line mutation count.

**What this freeze DOES fix — binding on implementation:**

- the **process-boundary mechanism and its semantic behavior**: §3.2a
  **Option A, deterministic reconstruction**. The `DeliverableSpec` does not
  cross the process boundary; parent and child call one shared pure derivation
  over authorities that already cross (`--dataset_profile_json`,
  `--model_io_json`), which are **consumed, not re-plumbed**. No new argv, no
  serialization, no ambient module-global spec. Option B (a transient optional
  field on the existing per-`exp_id` profile JSON) is the recorded destination
  **only** via a MATERIAL DESIGN STOP;
- the **logical-artifact parity definition**: §4.1 **exact logical artifact
  equality**, explicitly not raw HDF5 binary equality; and §4.2 **exact ordered
  argv-list equality after explicitly documented normalization** of genuinely
  ephemeral values only;
- the **Stage-B claim**: §5's renamed-spec rung is supplied **in-process at the
  owned seams**. 05c must **NOT** claim the renamed template crosses the real
  subprocess;
- the **Checkpoint-C property**: a real production spawn in which the child
  **reconstructs the shipped default spec**; helper-only is insufficient. §6
  keeps Checkpoint C and Gate 2 semantically distinct;
- the **Gate disposition**: Gate 1 **NOT REQUIRED**; Gate 2 **REQUIRED and
  bounded**, its launch scope governed by the later filled Implementation
  Working Rules and the current Gate standard, not by a further operator
  design decision;
- the **ownership boundaries**: the spec owns only the producer-side facts
  §1/§3 explicitly migrate. Instrument attrs, sampling-frequency metadata,
  chunking, split mechanics, invalid-filename policy, completeness and
  scoreability stay outside it; input decode, model-output decode and
  persisted-output encoding remain separate authorities (§2.1, §2.2);
- **no user-authored `DeliverableSpec` config, no new top-level YAML or config
  hierarchy** (§3.1, §17);
- **historical / config replay requires no migration** (§3.3);
- scorer semantics, HealthGate semantics, cleanup policy and metric
  scoreability remain **out of scope** (§1, §11, §13).

**No checkpoint or commit inside this PR is an operator pause point** (§14.2).

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

> **The block above is revision 1's evidence, at base `13b08550`, kept
> unedited so the audit chronology survives. Several of its line numbers and
> two of its claims did not survive re-audit — §0.2 is the corrected table
> and is what implementation should read.**

### 0.2 Re-audit at `226d4e9f` (OD-05c-2) — six corrections

Every revision-1 citation was mechanically re-checked after 05a and 05b
merged. Line drift is expected and unremarkable; **four of these are not
drift, they are wrong claims**, and two enlarge the scope.

| Rev-1 citation / claim | Status at `226d4e9f` |
|---|---|
| encoding literals `:216-217`, `:305`, `:318` | **confirmed unchanged** — `+128` at `:216-217`, `argmax` at `:305`, `-128` at `:318` |
| `int8` buffers `:685-686, :759-760, :861-862` | **moved** to `:690-691`, `:764-765`, `:866-867`, `:911-912` (four sites, not three) |
| producer names `:615, :892, :897` | **moved** to `:620`, `:897`, `:902` — still exactly three constructions |
| PATH BUILDER `ml_hyperparameter_tune_agent.py:1083 _denoised_path` | **WRONG NAME AND LINE.** The function is **`_build_denoised_filename`** at `:1053` (keyword-only: `model_type, run_name, exp_id, file_index, base_dir`); its template literal is at `:1088` |
| READER — cleanup `sandbox_executor.py:2161` | **NOT A CLEANUP SITE.** `:2155` is the **pseudo-mode `score_vector` override**; `abra_*` appears only in its *docstring*. It already takes `denoised_filename_fn` as an injected parameter. The real second cleanup literal is the tuner's `:5548` |
| READER — health peeks (Step 08) | **HOLDS NO LITERAL.** Peeks call `ctx.get_denoised_path(i)` (`_multi_file_peek.py:207`, `pearson_dispersion.py:73`, `spectral_peak_ratio.py:69`) — already injected. There is nothing there for 05c to touch and nothing for Step 08 to inherit from this row |
| "channel identity CLOSED by Step 02" | **HALF TRUE — this is the scope-enlarging finding.** Closed on the **read** side (`inference_single.py:661,664` use `profile_channels.input_channel/.target_channel`). **The WRITE side is not**: `array2h5.py:49,63` hardcodes `channel0001`/`channel0002` |
| argv "byte-identical — EXISTING (spawn captures)" | **OVERSTATED.** What exists is **token-level**: `test_sandbox_executor.py` asserts individual flags via `_cli_token_after(cmd, "--flag")` (`:230,248,259,293`). No full-argv golden exists, so "byte-identical" needs a Checkpoint-0 capture (§4) |

**Site count survives the corrections.** Removing the mis-attributed
`sandbox_executor:2161` leaves exactly **seven** production sites, which is
what revision 1 claimed — the total was right, the composition was not.

### 0.3 `create_abra_file` — what it actually hardcodes (OD-05c-2)

Read in full (`execute_tools/array2h5.py:25-75`), the writer inlines more
than the census recorded:

| Inlined fact | Site | Disposition (OD-05c-2) |
|---|---|---|
| channel group names `channel0001` / `channel0002` | `:49`, `:63` | **DERIVE** from `DatasetProfile.channels` — closes the write side of the gap Step 02 opened |
| `sampling_frequency = 10000000` | `:53`, `:67` | **LEAVE LITERAL, RECORD** — note it **duplicates the already-declared `DatasetConfig.sampling_frequency` (10 MS/s)** |
| `voltage_range_mV`, `input_impedance_ohm`, `input_coupling`, `file_first_sample_index` | `:50-54`, `:64-68` | **LEAVE LITERAL, RECORD** as frozen TIDMAD instrument metadata |
| chunking constant `N = 2000000000` | `:26` | **LEAVE** — a write-mechanics constant, not a task fact |
| `indexed` suffix rule `_{i}.h5` | `:39-41` | **LEAVE** — carried by the spec's naming, not re-decided |
| invalid-filename handling: `print(...)` then `return None` | `:29-31` | **RECORD as a defect** — a silent no-write. Not fixed here (out of scope), but named so it is not mistaken for contract behaviour |

**Operator decision OD-05c-2 (2026-08-15): derive the channel names; leave
the attrs literal.** Rationale: channel identity is a **declared Step-02
fact** that the writer contradicts, and no production consumer reads the
attrs at all — only `scripts/score_tidmad_official_{banded,wavenet}.py`
define their own copies for writing. Deriving the attrs would make 05c own
instrument metadata nothing reads, which is closer to declaring a format than
to extracting a contract. The duplication of `sampling_frequency` is recorded
as debt for whoever wins **final** ownership (§3).

**Production deliverable census** (`abra_validation_denoised_…`), the census
the §14 row needs:

**Corrected at revision 2 (§0.2).** Line numbers current at `226d4e9f`.

| # | Role | Site | Owner after Step 05 |
|---|---|---|---|
| 1-3 | **PRODUCER** — name | `execute_tools/inference_single.py:620`, `:897`, `:902` (three separate constructions) | **05c** |
| 4 | **PRODUCER** — writer: channel-group identity + persisted dtype | `create_abra_file` — `execute_tools/array2h5.py:25-75` (groups at `:49`, `:63`) | **05c** |
| 5 | **READER** — cleanup glob, watchdog partial-artifact | `TidmadSandbox.execute_inference` — `core/sandbox_executor.py:1767` | **05c** |
| 6 | **READER** — cleanup glob, `--cleanup_denoised` | tuner `run()` — `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:5548` | **05c** |
| 7 | **PATH BUILDER** | **`_build_denoised_filename`** — `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:1053`, template at `:1088` | **05c** |
| — | **READER** — scorer | `denoising_score_single.py:163`, `:166` (`scoring_utils.py:364` is a docstring only) | **Step 06 — NOT touched** |
| — | **READER** — health peeks | **no literal** — `ctx.get_denoised_path(i)`, already injected | **nothing to touch** |
| — | **CONSUMER** — pseudo `score_vector` | `core/sandbox_executor.py:2155` — takes `denoised_filename_fn`; `abra_*` in its docstring only | **nothing to touch** |

**The seven-site composition, stated so the total is mechanically auditable:**

```text
3   producer name constructions   inference_single.py:620, :897, :902
1   writer                        array2h5.py::create_abra_file
2   cleanup globs                 sandbox_executor.py:1767
                                  ml_hyperparameter_tune_agent.py:5548
1   path builder                  _build_denoised_filename (:1053/:1088)
--
7   production sites owned by 05c
```

**Deliberately NOT counted**, each for a stated reason:

| Not counted | Why |
|---|---|
| pseudo `score_vector` (`sandbox_executor.py:2155`) | `abra_*` appears in its **docstring** only; it already takes `denoised_filename_fn` by injection |
| HealthGate peek paths | **no literal** — `ctx.get_denoised_path(i)` is injected |
| scorer literals (`denoising_score_single.py:163,166`) | **Step 06** |
| historical diagnostic scripts | read artifacts already on disk (§0.1) |

The peek readers and the pseudo `score_vector` are the **injection precedent
05c generalizes**, not work it inherits.

*(Revision-1's table listed `_denoised_path:1083`, `sandbox_executor:1761`/
`:2161` and `:5438`. Those names and lines are superseded; the corrections are
recorded in §0.2 and the composition above is the active authority.)*

### 0.1 `scripts/*` census — classified by reproducibility role

`scripts/*` are **not** excluded merely for being "tooling". Each
deliverable-literal script is classified by whether it participates in
reproducing, resuming or replaying a run:

**Corrected at revision 2**: revision 1 listed 8 files; `grep -rl` finds
**11**. The three additions are marked.

| Script | Role | Disposition |
|---|---|---|
| **`run_comparison.py:445`, `:1280`, `:1386`** | **PRODUCTION LAUNCHER** — reconstructs the baseline deliverable path the producer writes, then scores it. **Omitted entirely by revision 1** | **MIGRATE** (OD-05c-3) — the rule below applies most sharply here: a renamed deliverable would break baseline scoring with nothing catching it |
| `finalize_recovered_diagnostic_round.py` | **canonical reconstruction** — rebuilds a round's artifacts | **MIGRATE** to the DeliverableSpec |
| `pregate_runtime_control_validation.py:214` | **production-adjacent** — pre-Gate validation globs live artifacts | **MIGRATE** |
| `v18_wave_summary.py:55,121` | **production-adjacent** — audits a workspace's artifact set against scope | **MIGRATE** |
| **`score_tidmad_official_banded.py:262`**, **`score_tidmad_official_wavenet.py:123`** | **historical replay** — score the official-paper runs; each also carries its own copy of the writer's attrs (`:80-84`, `:47-51`). **Omitted by revision 1** | **RECORD, leave literal** (OD-05c-3) — they must keep matching names the files on disk already have |
| `fcnet_health_metrics_scan.py`, `fcnet_full_file_scan.py`, `fcnet_diversity_pearson_scan.py`, `investigate_pearson_feasibility.py`, `official_paper_health_scan.py` | **diagnostic-only** — one-off analyses over historical outputs, several already parameterized (`official_paper_health_scan.py:96` takes the template as a CLI default) | **RECORD, leave literal** — migrating adds no capability, and they must keep reading *historical* artifacts written before this PR |

Rationale for the split: a script that **reconstructs or validates a run**
must agree with the producer, or a renamed deliverable silently breaks
recovery. A script that **analyses historical files** must keep matching the
names those files already have — migrating it would be actively wrong.

**Finding surfaced, not silently absorbed**: the migrated scripts add **six**
literal sites (`run_comparison.py` ×3 plus the three originally listed) but no
new responsibility — same contract, same authority, same rollback. They do
**not** justify a fourth PR.

**Operator decision OD-05c-3 (2026-08-15): migrate `run_comparison.py`; leave
both `score_tidmad_official_*` scripts literal.** The split follows the rule
already stated above, applied to files revision 1 had not seen.

## 1. Observable final capability

> **All CONTRACT-OWNED deliverable facts used by the migrated production
> sites resolve through ONE provisional producer-side `DeliverableSpec`** —
> name, cleanup matching, channel-group identity, and the persisted storage
> representation — instead of from literals inlined at each site. The
> persisted encoding is **derived from** `DatasetProfile.encoding` without
> making the Dataset Profile the deliverable contract. Launch mechanics
> (argv, file IPC, sentinels) carry no task literals.

**Deliberately NOT claimed — the honest scope of the provisional spec
(OD-05c-2). These are producer-side facts 05c leaves exactly where they are:**

| Left literal / unowned | Where |
|---|---|
| `sampling_frequency`, `voltage_range_mV`, `input_impedance_ohm`, `input_coupling`, `file_first_sample_index` | `array2h5.py:50-54`, `:64-68` — instrument metadata **no production consumer reads** |
| chunking constant `N = 2000000000` and the multi-file split | `array2h5.py:26`, `:32-37` |
| the `indexed` suffix rule | `array2h5.py:39-41` — already implied by the existing call |
| the silent `return None` on a non-`.h5` name | `array2h5.py:29-31` — recorded as a defect, not fixed |
| completeness and scoreability | Step 06 |

So 05c must **NOT** claim that the entire HDF5 format is contract-driven,
that all producer-side attrs are owned, or that every fact
`create_abra_file` writes moved into the spec. It claims exactly the
contract-owned facts the seven migrated sites use. **This narrowing does not
weaken the PR — it stops a provisional producer contract from silently
becoming an instrument-metadata schema.**

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

### 2.1 The encoding authority chain — frozen

```text
input dataset decoding / input-side representation
    -> DatasetProfile.encoding            (Input Dataset Contract, Step 02)

model-output semantic decoding
    -> ModelIOContract / the existing output-contract rule (I15)

persisted deliverable storage encoding
    -> DeliverableSpec                    (05c, provisional)

the TIDMAD DeliverableSpec itself
    -> DERIVED from DatasetProfile.encoding + existing compatibility facts,
       WITHOUT making DatasetProfile the deliverable contract
```

**The rule that makes this more than a diagram**: every persisted-output site
consumes the **`DeliverableSpec`**. It must not be the case that some
output-storage sites read the spec while others independently re-read
`DatasetProfile.encoding` — that would be two authorities agreeing by
coincidence, which is the defect shape Steps 02b/05a/05b removed elsewhere.

That the TIDMAD offset is `128` on **both** the input-decode and the
output-encode side is exactly such a coincidence made safe: the spec
**derives** its offset from `DatasetProfile.encoding`, so the two agree by
derivation rather than by two literals happening to match.

### 2.2 Per-literal classification — audited individually at `226d4e9f`

Revision 2's C5 said "replace each literal with its derived value" across
`:216-217`, `:305`, `:318` and the int8 sites. **That would have migrated
input-decode facts into the DeliverableSpec and broken the separation above.**
Each token was therefore re-read in context:

| Literal | Site | Class | 05c disposition |
|---|---|---|---|
| `np.dtype(np.int8)` ×2 | `inference_single.py:82-83` | **input decode** — dtype check on the SOURCE file's channels | **NOT migrated** |
| `.astype(np.int16)` ×2 | `:216-217` (`# 1. Base Pre-processing (ADC Offset)`) | **input decode** — compute dtype for the input array | **NOT migrated** |
| `+ 128` ×2 | `:216-217` | **input decode** — input value offset | **NOT migrated** |
| `argmax(dim=1)` | `:305` | **model-output decode** — already keyed on `output_type` (I15), inside the `is_regression` branch | **NOT migrated**; the branch stays contract-keyed |
| `- 128` ×2 | `:318` | **persisted-output encode** — returns to the stored ADC representation for H5 assembly | **DeliverableSpec** |
| `dtype=np.int8` ×2 | `:690-691`, `:866-867` | **persisted-output encode** — output buffers | **DeliverableSpec** |
| `.astype(np.int8)` ×4 | `:764-765`, `:911-912` | **persisted-output encode** — casts at the writer boundary | **DeliverableSpec** |
| `256` ×2 | `:273`, `:303` | **COMMENTS ONLY** — no executed literal | nothing to do |

**Two findings this classification produced:**

1. **`np.int16` and `+128` are input-side, not deliverable-side.** Migrating
   them would have moved an Input-Dataset-Contract fact into a producer
   contract. They stay.
2. **Both `256` occurrences are comments.** A "no `256` literal remains"
   acceptance criterion would have been vacuous or forced a pointless comment
   edit — see §8's replacement wording.

Legacy/`hybrid` behaviour is whatever Steps 03 and 05b already preserve; 05c
neither re-keys nor re-decides it.

## 3. Deliverable Contract ownership — the material decision

The §14 row leaves ownership open between §7c (first producer-side need) and
§10 (scoreability reader). Deciding from the §0 census:

**Recommendation: option (C) — provisional extraction here; final ownership
confirmed by Step 06.**

Reasoning from source, not from execution order:

- 05c owns the producer-side facts its sites actually consume — **naming,
  cleanup matching, channel-group identity and the persisted storage
  representation** — across every production *writer* and *cleanup* site.
  **Corrected at revision 3**: revision 2 said "all four producer-side facts
  — naming, layout, dtype, attrs". OD-05c-2 leaves the instrument **attrs**
  literal, so claiming them would overstate the extraction (§1).
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

**CONFIRMED BY THE OPERATOR (2026-08-15) and CLOSED** (§16). It binds Step
06's design surface, which is why it required an explicit decision rather
than an implementation choice. *(Status correction at freeze: this sentence
still read "remains an operator decision to confirm" while §16 already
recorded it as confirmed and closed. No semantic change — §16 was and remains
the decision register.)*

### 3.1 What the provisional contract IS — frozen representation

The design must not leave "a new provisional contract module" ambiguous.
Classified against current source:

| Question | Answer |
|---|---|
| **USER-AUTHORED?** | **NO** |
| **PERSISTED?** | **NO** — not written as its own artifact |
| **SERIALIZED?** | **NO** — and now decided, not assumed: under §3.2a's Option A the spec never crosses a boundary at all. Parent and child **reconstruct** an equal value from authorities that already cross. If Option B were ever adopted this row must flip to *transiently serialized inside an existing internal execution payload* |
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
   legacy prose-only contract — the existing **legacy no-contract path**), so
   the decode rule is available without new transport.
3. The deliverable **name** is composed from `denoising_model`, `run_name`,
   `exp_id` and `file_index` — all already argv items.

### 3.2a Transport vs reconstruction — **OPTION A, DETERMINISTIC RECONSTRUCTION**

Revision 2 left four claims that were not jointly defined: the spec is not
serialized; no new argv is added; a renamed spec is supplied through the
contract; and a real subprocess crosses the contract. Traced against current
source, they reconcile only one way.

**Decision: the spec does NOT cross the process boundary. Parent and child
each call ONE shared pure derivation.**

```text
derive_tidmad_deliverable_spec(
    dataset_profile,          # already crosses: --dataset_profile_json
    model_io_contract | None, # already crosses: --model_io_json
    run/model/file identifiers,
) -> DeliverableSpec
```

**Why current source supports this.** Every field OD-05c-2 leaves in the spec
is already available on both sides:

| Spec field | Parent has it | Child has it |
|---|---|---|
| channel identity | `run_profile` (05a, tuner `run()`) | `dataset_profile.channels`, `inference_single.py:341` |
| persisted storage dtype / value offset | `run_profile.encoding` | `dataset_profile.encoding`, loaded `:337` |
| output decode selector | `run_model_io` (05b) | `args._model_io`, `:329` |
| name identifiers | `model_type`, `run_name`, `exp_id`, `file_index`, `base_dir` | the same, all argv |

So the child reconstructs an **equal** spec from authorities that already
cross. **`--dataset_profile_json` and `--model_io_json` are consumed, not
re-plumbed**; no third transport is added.

**What this costs, stated plainly.** A **renamed** template is a frozen TIDMAD
compatibility literal, not a declared fact, so it is **not derivable** — it
therefore cannot reach the child by reconstruction. Consequences, and §6
depends on them:

- the real subprocess reconstructs the **shipped default** spec only;
- a **non-default** spec is injectable only in-process, at the owned seams;
- **05c must NOT claim that a renamed template crosses the real subprocess.**

**What replaces the loose wording.** Everywhere revision 2 said *"the
DeliverableSpec crosses the subprocess"*, the honest statement is:

> the subprocess **reconstructs an equal `DeliverableSpec` through the same
> derivation authority** — one function, two callers, no duplicated literal.

**Option B, considered and rejected.** A minimum transient transport was
available: `sandbox_executor._write_dataset_profile_config` already writes a
per-`exp_id` transient JSON that the child loads, and one optional field could
have ridden it. Rejected because (a) reconstruction already yields an equal
value for every field 05c actually owns, so the transport would buy only the
*test* contrast; (b) it would force §3.1's `SERIALIZED? NO` to flip to yes,
widening what a provisional producer-side extraction persists; and (c) the
frozen capability is *"one explicit contract"*, which one shared derivation
satisfies — a renamed template is a contrast device, not a production
capability. **If implementation finds a production need for a non-default spec
in the child, that is a MATERIAL DESIGN STOP and a return to Option B — not an
ad-hoc third mechanism.**

**Forbidden regardless of option:** an ambient module-global "current spec";
parent and child reproducing the TIDMAD literal at two sites; any third
implicit mechanism.

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
| training argv | **exact ordered argv-list equality after documented normalization** | **PARTIAL.** What exists is token-level (`test_sandbox_executor.py:230,248,259,293` via `_cli_token_after`). A full ordered-list golden is **MISSING — Checkpoint 0 captures it** |
| inference argv | **exact ordered argv-list equality after documented normalization** | **PARTIAL — same correction, same capture** |
| scoring argv plumbing | unchanged | untouched by design, so existing token-level coverage suffices |
| file IPC (sidecars, timing JSON, runtime-observation sidecar) | **deep-equal** | partially EXISTING — classify at Checkpoint 0 |
| sentinel protocol (`_OK_<exp_id>`, silent-crash detection) | **identical sequence** | EXISTING (`sandbox_executor:1498-1519`) |
| produced deliverable files | **EXACT LOGICAL ARTIFACT EQUALITY** (§4.1) | **MISSING — Checkpoint 0 must capture** |
| deliverable filename set | **identical** | **MISSING — Checkpoint 0** |
| post-cleanup filesystem set | **identical** | **MISSING — Checkpoint 0** |

The three missing captures are the highest-value Checkpoint-0 work in all of
Step 05: they are the only oracles that can prove a write/cleanup refactor
moved nothing. **Revision 2 adds a fourth**: the argv rows above claimed an
EXISTING byte-identical oracle, and re-audit found only token-level
assertions.

### 4.1 What "equal artifact" means — frozen definition

Revision 2 captured **logical** HDF5 content in C0 and then called the
criterion **byte-identical** in later sections. Those are different claims.
The frozen criterion is the strongest one that is honestly provable:

> **EXACT LOGICAL ARTIFACT EQUALITY**, over a canonical HDF5 inspection
> representation covering: relative filename · group paths · dataset names ·
> dataset dtypes · dataset shapes · **every persisted sample value** · every
> frozen attr key/value · the produced file set · the post-cleanup file set.

**This is deliberately NOT raw binary file equality.** HDF5 writes carry
library version, chunk layout and allocation details that are not guaranteed
byte-reproducible across environments; asserting a raw file hash would make
the oracle fail for reasons unrelated to this PR. A raw-byte or file-hash
criterion may be adopted **only** if implementation proves repeated writes are
physically deterministic across the supported HDF5 environment — and that
proof must be recorded, not assumed.

**"Every persisted sample value equal" is mandatory and non-negotiable for
C5**, which is the one commit that can move a written value (failure class 2).

### 4.2 argv parity — the criterion, precisely

Called **exact ordered argv-list equality after explicitly documented
normalization** — not "byte-identical argv".

- The C0 fixture must use **distinguishable deterministic values** so an
  ordering or substitution defect is visible.
- Normalize **only** what is intentionally ephemeral — e.g. a temporary
  workspace root — and document each normalization at the assertion.
- **Do not** freeze machine-specific temp directories into the golden.
- **Do not** weaken the oracle back to token-presence assertions; the whole
  point is that an inserted, removed or reordered token fails.

## 5. Stage-B atomic contrast

**One axis: deliverable naming/transport.** Under the TIDMAD profile, with a
**renamed deliverable template** supplied as one injected runtime
`DeliverableSpec`, the owned consumer seams must resolve names **exclusively**
through it — no inlined template executed in engine, cleanup or reconstruction
code.

**Where the renamed spec is supplied — and where it is NOT** (§3.2a, Option A):

```text
Stage-B rung        the owned seams accept ONE injected runtime spec and
                    move TOGETHER:
                      producer · path builder · cleanup · launcher
                    supplied IN-PROCESS at the seams.

Checkpoint C        the SHIPPED DEFAULT spec, reconstructed by the child
                    through the real subprocess boundary.

NOT CLAIMED         that the renamed template itself crosses the real
                    subprocess. Under Option A it cannot: a template is a
                    frozen compatibility literal, not a derivable fact.
```

Reds when any owned production site still executes its own literal. Scorer-side
TIDMAD literals remain explicitly **outside** the rung. 05c claims neither
arbitrary file formats nor user-authored naming.

Scorer-side literals remain and are explicitly **out of the assertion's
scope** — a "no `abra_*` anywhere" assertion is unsatisfiable at Step 05 and
would be a test-design error. Dataset-axis coverage comes from 05a; encoding
coverage is asserted separately against `ValueEncoding`.

## 6. Checkpoint C — live integration

A **real production training and inference spawn** must cross the contract:
the deliverable is written, named and cleaned through it, with the encoding
derived. A config- or helper-only test is explicitly **insufficient** here —
the whole failure class lives in the subprocess boundary.

**Checkpoint C and Gate 2 both exist and prove different things.** Keeping
them distinct is what stops one from being used to excuse the other:

| | **CHECKPOINT C** | **GATE 2** |
|---|---|---|
| nature | deterministic / controlled real subprocess boundary | one current canonical **bounded real attempt** |
| proves | spec reconstruction; real writer invocation; real naming; real encoding; real cleanup; **exact logical artifact equality** (§4.1) | the full real chain still trains, infers, writes, **scores** and cleans under actual runtime, data and hardware conditions |
| may use | a deterministic candidate, synthetic/small input, **CPU where source permits** | the current approved pro configuration, real data |
| may NOT be | helper-only | a matrix, a campaign, or an exploratory sizing attempt |

Checkpoint C is not a cheaper Gate 2, and Gate 2 is not a bigger Checkpoint C:
one proves the **seam is real**, the other proves the **chain still works**.

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
| any test asserting helper call order inside the engines | **DELETE** — implementation-detail pin with no compatibility meaning — **WITH ONE NAMED EXCEPTION, added at rev 2** |

**The exception, named so the rule above cannot delete it.**
`tests/unit/execute_tools/test_inference_single.py:172`
(`test_canonical_del_block_runs_before_create_abra_file`) asserts, by AST,
that the buffer-`del` block runs **before** `create_abra_file`. It reads like
a call-order pin, but `inference_single.py:751-756` and
`sandbox_executor.py:112-114` record why it exists: `create_abra_file` emits
transient `.flatten().astype(int8)` copies, and freeing the source buffers
first is what keeps the numpy peak inside the RSS cap. It guards a **measured
memory incident**, not an implementation detail. **KEEP.** C4 touches
`create_abra_file`'s signature and must leave this test passing unedited.

`create_abra_file` otherwise has **no behavioural test at all** — the C0
artifact golden is its first.

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

**Corrected at revision 2** — `_denoised_path` does not exist, and
`scripts/*` is no longer wholly excluded (OD-05c-3):

| Surface | Commits |
|---|---|
| the new provisional contract module | C1 |
| `nodes/ml_hyperparameter_tune_agent/…py` — `_build_denoised_filename` (`:1053`) and the `--cleanup_denoised` glob (`:5548`) | C2 |
| `core/sandbox_executor.py` — the watchdog partial-artifact glob (`:1767`) **only** | C2 |
| `execute_tools/inference_single.py` — three name constructions (C3), encoding literals (C5) | C3, C5 |
| `execute_tools/array2h5.py` — signature + channel-group derivation | C4 |
| `scripts/run_comparison.py` (`:445`, `:1280`, `:1386`) + the three reconstruction scripts | C6 |
| directly affected tests + docs | C0, C7-C9 |

**NOT** the scorer (`denoising_score_single.py`, `scoring_utils.py`); **NOT**
HealthGate peeks (they hold no literal); **NOT**
`score_tidmad_official_{banded,wavenet}.py` or the five diagnostic scans;
**NOT** cleanup policy; **NOT** `create_abra_file`'s attrs, `N` split or
its silent-`return` defect.

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

## 14. Commit plan — per-commit checklists

**05c remains ONE PR (operator decision).** Naming, writer layout, encoding,
cleanup and reconstruction tooling are **internal phases**, not child PRs,
because every one of them shares:

| Shared by all phases |
|---|
| one provisional `DeliverableSpec` |
| one persisted-artifact parity surface (§4.1) |
| one renamed-spec contrast (§5) |
| one real-spawn Checkpoint C (§6) |
| one required Gate 2 (§9) |
| one rollback objective — **producer, readers, cleanup and reconstruction agree on the artifact** |

A naming-only, encoding-only or scripts-only partial merge would leave a
producer/reader mismatch on disk: files written under one authority and
searched for under another. That is failure class 1, shipped deliberately.

**Semantic sequence is frozen on approval; exact Git commit count is NOT.**
Also not frozen: helper structure, source line numbers, test-file
decomposition, exact mutation implementation. Implementation may merge or
split engineering commits provided the semantic sequence, the §4 Stage-A
surfaces, the §5 Stage-B rung, the §6 Checkpoint-C property and the §9 Gate
disposition are unchanged.

Line references are **reading aids captured at `226d4e9f`**, not contracts.
Re-read the touched source immediately before each commit.

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**Dependency chain.** `C0 → C1` establishes the oracle and the inert seam.
`C2` (readers) precedes `C3`/`C4` (producers) because a reader migration is
reversible against artifacts that already exist, while a producer migration
changes what gets written. `C5` (encoding) is independent of C2-C4 and is
isolated because it is the one commit that can move a written **byte**. `C6`
is the launcher. `C7`-`C9` close.

**Ordering rationale, stated once:** readers first is not a preference. If a
producer migrated first and its spec were wrong, the run would write files
nothing could find or clean — and the failure would surface as a scoring
error, not a naming error (failure class 1).

---

### C0 — Checkpoint 0: capture the three missing oracles

**1. Goal.** Capture the compatibility surfaces that no existing oracle
covers, **before any production edit**, because a write/cleanup refactor can
only be proven inert against artifacts captured beforehand. §4 names three
missing captures; §0.2 found a fourth (argv is token-level only, not the
byte-identical oracle revision 1 assumed). Separate commit because a baseline
captured after an edit proves nothing about that edit.

**2. Scope.**
- New tests under `tests/unit/execute_tools/` and `tests/unit/core/` — settle
  exact module placement by inspection, do not invent a path.
- **Non-goals**: no production file changes at all; no new fixture for facts
  Step 02/03 already pin; no scorer-side assertion; no re-capture of the
  four existing `_build_denoised_filename` tests
  (`test_denoised_filename_helper.py`).
- Depends on: nothing.

**3. Implementation plan.**
- [ ] Re-read `create_abra_file` (`array2h5.py:25-75`) and record every
      fact it writes: group names, the 5 attrs per channel, dataset name,
      `chunks=True`, the `indexed` suffix rule, and the `N` split.
- [ ] Capture the **exact logical artifact golden** (§4.1): write one small
      deliverable through the current `create_abra_file` and record, as
      hardcoded expectations, a canonical inspection representation — group
      paths, dataset names, dtypes, shapes, **every persisted sample value**
      and every attr key/value.
- [ ] Capture the **filename set** produced by all three producer
      constructions (`inference_single.py:620`, `:897`, `:902`) for a fixed
      `(model, run_name, exp_id, file_index)` tuple, as hardcoded strings.
- [ ] Capture the **post-cleanup filesystem set**: seed a directory with
      matching and non-matching files, run each cleanup glob
      (`sandbox_executor.py:1767`, tuner `:5548`), record exactly which files
      survive.
- [ ] Capture an **ordered argv-list golden** (§4.2) for the training and
      inference spawns — the whole `cmd` list, not individual tokens. Use
      distinguishable deterministic fixture values; normalize **only**
      intentionally ephemeral values (e.g. a temporary workspace root) and
      document each normalization at the assertion. Do not bake a
      machine-specific temp directory into the golden.
- [ ] Classify the file-IPC surfaces §4 marks "partially EXISTING": which of
      the sidecar / timing / runtime-observation writes already have
      deep-equal oracles and which do not.
- [ ] Record the classification and every captured value in §15.

**4. Validation plan.**
- *Unit*: every new capture passes against unmodified production code.
- *Integration/pseudo*: none required at C0.
- *Negative*: include the cleanup glob's **non-matching** files, so a later
  widened glob that deletes too much is caught, not just one that deletes too
  little.
- *Backward-compat*: this commit **is** the parity instrument.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] `git status --porcelain` lists **no production file** in this commit.
- [ ] Captured values are written as **hardcoded literals**, never re-derived
      by calling the code under test.
- [ ] The artifact golden asserts group paths, dataset names, dtypes, shapes,
      **every persisted sample value** and all 10 attr key/value pairs — not
      merely "the file opens".
- [ ] The cleanup capture asserts both the deleted set **and** the surviving
      set.
- [ ] The argv golden compares the **entire ordered list** after documented
      normalization, so an inserted, removed or reordered token fails; and it
      contains no machine-specific path.
- [ ] Each capture is traceable to the production site it guards, by
      `file:line`.

**6. Failure and edge cases.**
- A capture cannot be taken without a GPU or real HDF5 input → use a
  synthetic array through the real writer; record the substitution. If a
  surface genuinely needs real data, it belongs to Checkpoint C / Gate 2 and
  this document is updated to say so.
- `create_abra_file` returns `None` silently on a non-`.h5` name
  (`:29-31`) → capture that behaviour as-is; **do not fix it here** (§0.3).
- The `N = 2000000000` split path is unreachable at test scale → record it as
  uncaptured rather than pretending coverage.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q`
      *(narrow to the real modules at implementation time)*
- [ ] Record: test count, wall time, and explicit confirmation that zero
      production files were modified.

**8. Commit boundary.** Tests and a written census only. Independently
reviewable as "what we promise not to change". No production edit, no
refactor, no cleanup of neighbouring tests.

---

### C1 — the provisional `DeliverableSpec` (runtime-only, inert)

**1. Goal.** Introduce the typed runtime value §3.1 froze — derived, not
declared — with its TIDMAD instance, and **no consumer**. Separate commit
because "the type exists and is correct" and "production uses it" are
different claims with different failure modes, and Step 02b's precedent is
explicit that an unused parameter is invisible to every caller.

**2. Scope.**
- One new module holding the spec (placement settled by inspection).
- **Non-goals**: **no** YAML, **no** task-config block, **no** train-config
  field, **no** persisted artifact, **no** new argv (§3.2); no production
  call site; no change to any of the seven sites.
- Depends on: C0.

**3. Implementation plan.**
- [ ] Re-read `DatasetConfig.validation_file_name` (`dataset_config.py:142`)
      — the **precedent**: Step 02 solved the *input* filename with one
      declared field plus one accessor. Record why the deliverable differs
      (it is what SIDERIUS *produces*, not a property of the input dataset),
      so choosing a runtime spec over a profile field is a reasoned choice
      and not an inconsistency.
- [ ] Define the spec with **exactly** the fields §1 scopes it to: name
      resolution, cleanup/name matching, channel-group identity, persisted
      storage dtype, persisted value offset, and any model-output decode
      selector the producer path genuinely needs. Each is **derived** from
      existing values; none is newly declared. **The instrument attrs, `N`,
      the split mechanics and the indexed-suffix policy are NOT fields of
      this spec** (OD-05c-2).
- [ ] Implement it as the ONE shared pure derivation §3.2a froze
      (`derive_tidmad_deliverable_spec(...)`), callable identically by parent
      and child, so no ambient module-global "current spec" exists and no
      literal is reproduced at two sites.
- [ ] Provide the TIDMAD derivation from `DatasetProfile` + the existing
      inlined literals, extracted **verbatim**.
- [ ] Provide the name-resolution accessor the readers and producers will
      call, and the glob-pattern accessor the two cleanup sites need.
- [ ] Confirm by inspection that no production module imports it yet.

**4. Validation plan.**
- *Unit*: the TIDMAD instance resolves names **byte-identical** to the C0
  filename golden, for every `(model, run_name, exp_id, file_index)` in it.
- *Unit*: the glob accessor matches exactly the C0 cleanup capture's deleted
  set and none of its surviving set.
- *Negative*: a spec missing a required derivation fails at construction,
  typed — it must not resolve a partial or empty name.
- *Backward-compat*: constructing the spec from a legacy run's values
  (§3.3) yields the identical TIDMAD spec.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] Every name the spec resolves is **equal** to the corresponding C0
      hardcoded literal — asserted against the capture, not re-derived.
- [ ] The glob accessor's match set is **equal** to C0's deleted set.
- [ ] The spec is constructible **without** any new configuration input: a
      legacy run's existing values suffice (§3.1's "REQUIRED FOR LEGACY
      RUNS? NO").
- [ ] `grep` proves **zero** production importers — so C2-C6 evidence cannot
      be confused with C1's.
- [ ] No file under `configs/` changed; no schema gained a field.

**6. Failure and edge cases.**
- A needed deliverable semantic turns out not to be derivable from existing
  values → **MATERIAL STOP** and design review (§3.1), not a new config key.
- The spec would need a scoreability or metric fact → **STOP**; that is
  Step 06 (§13).
- Two producer sites disagree about the name they build today → capture both
  in C0 and record which is canonical **before** unifying.

**7. Verification commands and evidence.**
- [ ] The targeted selector for the new module plus the C0 captures.
- [ ] Record counts, wall time, and the zero-importer confirmation.

**8. Commit boundary.** One new typed value and its TIDMAD derivation,
inert, independently revertible. No call-site migration.

---

### C2 — migrate the READERS (path builder + two cleanup sites)

**1. Goal.** Make the three name **consumers** resolve through the spec.
Readers first because the migration is reversible against artifacts that
already exist on disk: if the spec were wrong, a reader finds nothing —
loudly and without destroying anything — whereas a wrong producer writes
files that nothing can find or clean (failure class 1).

**2. Scope.**
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` —
  `_build_denoised_filename` (`:1053`, template at `:1088`).
- `core/sandbox_executor.py:1767` — the watchdog partial-artifact glob.
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:5548`
  — the `--cleanup_denoised` glob.
- **Non-goals**: no producer change; **no cleanup POLICY change** — which
  files are deleted, and when, must not move (§13, Step 11 owns policy); no
  change to `denoised_filename_fn`'s injected-callable shape, which already
  works and is the pattern being generalized.
- Depends on: C1.

**3. Implementation plan.**
- [ ] Re-read all three sites and record how each obtains
      `model_type`, `run_name`, `exp_id`, `base_dir` today.
- [ ] Thread the run's spec to each; resolve names/globs through it.
- [ ] Keep `_build_denoised_filename`'s **keyword-only signature and return
      type** unchanged — its four existing tests must pass untouched.
- [ ] Confirm the tuner's `_denoised_fn` closure (`:5272-5285`) still
      produces the same absolute path, since the peek helpers use its result
      verbatim (`_peek.py:21`).
- [ ] Confirm the watchdog glob still runs **only** on the kill path.

**4. Validation plan.**
- *Unit*: each migrated site resolves the C0-captured name/glob exactly.
- *Integration/pseudo*: a pseudo-mode round reaches `score_vector` with a
  `denoised_filename_fn` whose output is unchanged.
- *Negative*: a spec that resolves a **different** template causes all three
  sites to move **together** — proving they share one authority rather than
  three coincidentally-equal literals.
- *Backward-compat*: `test_denoised_filename_helper.py` passes **unedited**;
  the post-cleanup filesystem set equals the C0 capture.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] Post-cleanup filesystem set is **equal** to the C0 capture — both the
      deleted set and the surviving set.
- [ ] The four existing `_build_denoised_filename` tests pass **with no
      edit**; if any needs editing, that is a signature change and a
      **STOP**.
- [ ] Under a renamed spec, **all three** sites move together (the §5
      Stage-B property, observed early here).
- [ ] Cleanup **policy** is untouched: same trigger conditions, same
      ordering, same log lines.
- [ ] No producer site changed in this commit — asserted and recorded.

**6. Failure and edge cases.**
- A cleanup glob is broadened and deletes a file the C0 capture proved must
  survive → **STOP**; this is a data-loss defect, not a naming refactor.
- The tuner's absolute-path contract with the peek helpers breaks → **STOP**;
  `_peek.py:20-24` states the path is used verbatim.
- The spec is unavailable at a cleanup site because cleanup runs on a failure
  path where the run context is gone → record the acquisition point rather
  than inventing one; if none exists, **STOP**.
- Resume: a resumed run must clean artifacts written by the pre-resume
  process — assert it, do not assume it.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/core -q`
- [ ] Record counts, wall time, the filesystem-set equality, and confirmation
      that no existing helper test required editing.

**8. Commit boundary.** Three consumer sites, one authority, reversible. No
producer work, no encoding work, no script work.

---

### C3 — migrate the three PRODUCER name constructions

**1. Goal.** Make `inference_single.py` compose the deliverable name through
the spec at all three construction sites, so producer and consumer share one
authority. Separate from C4 because naming and file **layout** are different
facts with different oracles.

**2. Scope.**
- `execute_tools/inference_single.py:620` (formal), `:897` and `:902`
  (trial — note these build **two different** paths, `out_dir`-relative and
  base-relative; the difference is pre-existing and must be preserved).
- **Non-goals**: no layout/attr change (C4); no encoding change (C5); **no
  new argv** — §3.2 established the spec is derivable from values already
  crossing the boundary.
- Depends on: C2.

**3. Implementation plan.**
- [ ] Re-read `:600-640` and `:880-915` and record exactly which identifiers
      each construction uses and how they differ.
- [ ] Confirm the child **reconstructs an equal spec** (§3.2a) from what
      already crosses: `dataset_profile` (loaded `:337`), `args._model_io`
      (`:329`), and the argv identifiers `denoising_model` / `run_name` /
      `exp_id` / `file_index`. The spec itself does **not** cross; parent and
      child call the same derivation.
- [ ] Replace all three constructions with spec resolution, preserving the
      `out_dir` vs base distinction.
- [ ] Confirm **no ambient second resolution** appears in the child (§3.2's
      frozen acceptance): the subprocess must not call
      `resolve_dataset_profile()` when given a profile path.

**4. Validation plan.**
- *Unit*: each site's resolved name equals its C0 golden.
- *Integration/pseudo*: an inference spawn writes files whose **names** equal
  the C0 filename set.
- *Negative*: a malformed/absent spec fails loudly in the child; it must not
  fall back to an inlined name.
- *Backward-compat*: **argv byte-identical** to the C0 full-argv golden.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] The produced filename set is **equal** to the C0 capture.
- [ ] The training and inference argv lists are **equal** to the C0 ordered
      goldens after the documented normalization — no added, removed or
      reordered token. If a new argument proves unavoidable, §3.2 requires
      the Stage-A claim be **downgraded in writing**, not quietly restated.
- [ ] Parent and child resolve the **same** spec value — asserted
      semantically, and asserted to come from **one** derivation rather than
      two matching literals.
- [ ] The `out_dir`-relative and base-relative trial paths remain **distinct**
      and each unchanged.
- [ ] No `abra_` literal is executed in `inference_single.py` for the
      deliverable name — the input-file name (`validation_file_name`,
      `:641`) is **not** in scope and must remain.
- [ ] Zero calls to `resolve_dataset_profile()` added in the child.

**6. Failure and edge cases.**
- Trial and formal paths disagree about the spec → they must resolve from the
  **same** value; a per-branch spec is two authorities.
- `--model_io_json` absent (legacy prose-only contract) → the spec must still
  construct; the decode rule is a separate fact (C5).
- The child receives no profile path (a caller predating the transport) →
  preserve today's behaviour; do not make it newly fatal.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/core -q`
- [ ] Record counts, wall time, the filename-set equality and the argv
      equality result.

**8. Commit boundary.** Three constructions in one module. No writer change,
no encoding change.

---

### C4 — `create_abra_file` writes through the spec; channel identity derived

**1. Goal.** Make the writer take the spec and derive its **channel group
names** from `DatasetProfile.channels`, closing the write side of a gap Step
02 left half-open (§0.3). Separate commit because it changes the **bytes of
the file structure**, which is a different risk class from naming.

**2. Scope.**
- `execute_tools/array2h5.py::create_abra_file:25-75` — signature plus the
  group-name construction at `:49` and `:63`.
- Its two call sites, `inference_single.py:762` and `:909`.
- **Non-goals per OD-05c-2**: the 5 attrs per channel stay **literal**;
  `N = 2000000000` stays; the `indexed` suffix rule stays; the silent
  `return None` on a bad filename (`:29-31`) is **not** fixed here.
- Depends on: C3.

**3. Implementation plan.**
- [ ] Re-read `create_abra_file` in full and confirm the C0 artifact golden
      covers every fact it writes.
- [ ] Add the spec parameter, defaulted so existing callers are unaffected
      until migrated.
- [ ] Derive the two group names from `DatasetProfile.channels.input_channel`
      / `.target_channel`; under TIDMAD these resolve to `channel0001` /
      `channel0002`, so the written bytes do not move.
- [ ] Migrate both call sites.
- [ ] Record in §15 that `sampling_frequency` here duplicates
      `DatasetConfig.sampling_frequency` and is **left literal by OD-05c-2**.

**4. Validation plan.**
- *Unit*: the written HDF5 structure satisfies **exact logical artifact
  equality** (§4.1) against the C0 golden under TIDMAD — group paths, dataset
  names, dtypes, shapes, every sample value, all 10 attrs.
- *Unit*: under a contrast profile naming different channels, the **group
  names move** and nothing else does.
- *Negative*: a spec whose channel identity is missing fails loudly rather
  than writing a file with default group names.
- *Backward-compat*: a caller passing no spec produces the pre-05c file
  exactly.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] Under TIDMAD the artifact satisfies **exact logical artifact equality**
      against the C0 golden. A single differing attr, dtype, shape or sample
      value is failure class 2 and a **STOP**, not a tolerance.
- [ ] Under a contrast channel identity, exactly the two group names change —
      asserted by diffing the written structure against the TIDMAD golden.
- [ ] The five attrs per channel are **unchanged and still literal**;
      `sampling_frequency` remains `10000000` (OD-05c-2).
- [ ] `array2h5.py` contains **no** `channel0001`/`channel0002` literal.
- [ ] `test_inference_single.py:172`'s `del`-before-`create_abra_file`
      ordering test still passes — see §8's amendment; it guards a real
      memory incident and must **not** be deleted as a "call-order pin".

**6. Failure and edge cases.**
- Writing through the spec changes chunking or dataset order → **STOP**;
  those are file bytes.
- A profile declares only one channel (no target) → `array2h5` already
  supports `array2=None`; assert the single-channel path is unchanged.
- The `N`-split multi-file path is unreachable at test scale → record it as
  uncaptured; do not refactor what is not covered.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools -q`
- [ ] Record counts, wall time, and the byte-equality result against the C0
      artifact golden.

**8. Commit boundary.** One writer, one derived fact. No naming change, no
encoding change, no attr change.

---

### C5 — derive the value encoding from `ValueEncoding` + the decode rule

**1. Goal.** Replace the inlined `+128` / `-128` / `int8` / `argmax`
literals with derivations from `DatasetProfile.encoding` and the Model-I/O
decode rule. Isolated because it is the **only** commit that can change a
written byte, and failure class 2 says a byte change is not a refactor — it
moves every downstream score.

**2. Scope — the PERSISTED-OUTPUT ENCODE sites only** (§2.2's
classification, audited individually):
- `execute_tools/inference_single.py` — `-128` at `:318`; `np.int8` buffers at
  `:690-691`, `:866-867`; `.astype(np.int8)` casts at `:764-765`, `:911-912`.
- **Non-goals — these are NOT deliverable facts and must NOT be migrated**:
  the input dtype check `:82-83`, and `.astype(np.int16) + 128` at `:216-217`
  (both **input decode**, Input Dataset Contract); `argmax` at `:305`
  (**model-output decode**, already keyed on `output_type` via I15). The two
  `256` occurrences (`:273`, `:303`) are **comments**. No scorer change. No
  new argv (§3.2a).
- Depends on: C4.

**3. Implementation plan.**
- [ ] Re-read `:196-320` and re-confirm §2.2's classification against
      current source **before** touching anything — the classification, not
      the token, decides what moves.
- [ ] Route the persisted-output sites through the **`DeliverableSpec`**, not
      through `DatasetProfile.encoding` directly: every output-storage site
      must read the SAME authority (§2.1). A mixture — some sites on the
      spec, others re-reading the profile — is the defect this commit exists
      to prevent.
- [ ] Leave the input-decode sites (`:82-83`, `:216-217`) exactly as they
      are, and record in §15 that they were audited and deliberately kept.
- [ ] Leave the `argmax` branch keyed on the output contract; do not re-key
      it on the loss, a model name, or the spec.
- [ ] Confirm offset symmetry holds **by derivation**: the input side reads
      `DatasetProfile.encoding`, the output side reads the spec, and the spec
      derives from the profile — so they agree structurally rather than by
      two matching literals (§2.1).

**4. Validation plan.**
- *Unit*: for the TIDMAD encoding, every derived value equals its former
  literal — asserted against hardcoded numbers.
- *Unit*: under a contrast `ValueEncoding` (different offset and dtype) the
  written buffer dtype and the offset arithmetic both follow it.
- *Negative*: an encoding whose `storage_dtype` cannot hold the offset range
  fails loudly rather than silently wrapping.
- *Backward-compat*: **the written artifact is byte-identical** to the C0
  golden under TIDMAD — the single most important assertion in this PR.
- *Gate*: this is the change Gate 2 exists to confirm (§9).

**5. Acceptance criteria.**
- [ ] Under TIDMAD the deliverable satisfies **exact logical artifact
      equality** against the C0 golden, **including every persisted sample
      value** — mandatory here, not merely the same dtype.
- [ ] **No persisted-output encoding fact owned by `DeliverableSpec` is
      independently restated in the migrated producer path.** This replaces
      revision 2's *"no `128`, `int8` or `256` literal remains"*, which was
      a token ban: both `256` occurrences are comments, and `128`/`int16`
      legitimately remain on the **input-decode** path.
- [ ] A structural guard targets the **classified persisted-output sites**,
      not every occurrence of those tokens in the module.
- [ ] The `:82-83` and `:216-217` input-side sites are **unchanged** and
      recorded as Input-Dataset-Contract scope.
- [ ] Legacy/`hybrid` behaviour is unchanged — whatever Steps 03 and 05b
      already preserve.
- [ ] The decode branch is still keyed on the output contract (I15), not
      re-keyed on the loss or a model name.
- [ ] Round-trip symmetry is asserted: encode-then-decode returns the
      original values for the TIDMAD encoding.

**6. Failure and edge cases.**
- Deriving the offset changes one sample value → **STOP** (§13's first stop
  condition, verbatim).
- `compute_dtype` promotion differs from the current `astype(np.int16)` →
  the intermediate dtype is part of the arithmetic; assert it explicitly.
- A legacy run with no `--model_io_json` → the decode rule falls back exactly
  as today; the encoding still derives from the profile.
- Overflow/clipping behaviour at the int8 boundary must be preserved
  exactly — capture it in C0 if the golden does not already cover it.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools -q`
- [ ] Record counts, wall time, and the byte-level artifact comparison.

**8. Commit boundary.** Encoding only, one module. No naming, no layout, no
scorer.

---

### C6 — migrate `scripts/run_comparison.py` (OD-05c-3)

**1. Goal.** Make the production chain launcher resolve the baseline
deliverable path through the same spec the producer writes with. Separate
commit because it is the operator-facing launcher, not an engine, and it
should be revertible independently.

**2. Scope.**
- `scripts/run_comparison.py:445`, `:1280`, `:1386`.
- The three already-listed reconstruction scripts
  (`finalize_recovered_diagnostic_round.py`,
  `pregate_runtime_control_validation.py:214`, `v18_wave_summary.py:55,121`).
- **Non-goals per OD-05c-3**: `score_tidmad_official_{banded,wavenet}.py`
  and the five diagnostic scans stay literal — they read **historical**
  artifacts and migrating them would be actively wrong.
- Depends on: C3.

**3. Implementation plan.**
- [ ] Re-read each of the three `run_comparison.py` sites and record whether
      it builds a path to **write**, to **read**, or to **glob**.
- [ ] Resolve each through the spec, preserving the baseline `run_name` /
      `exp_id` values each site already uses.
- [ ] Migrate the three reconstruction scripts the same way.
- [ ] Confirm no CLI argument of `run_comparison.py` changed.

**4. Validation plan.**
- *Unit*: each migrated site resolves the C0-captured name.
- *Integration/pseudo*: none required — these are path constructions.
- *Negative*: a renamed spec moves the launcher **and** the producer
  together; a test that pins only one of them would not catch the drift this
  commit exists to prevent.
- *Backward-compat*: `run_comparison.py --help` output and argv unchanged.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] All three `run_comparison.py` sites resolve names **equal** to the C0
      capture.
- [ ] Under a renamed spec, launcher and producer move **together** —
      asserted in one test, not two independent ones.
- [ ] The two `score_tidmad_official_*` scripts are **unmodified**, and §15
      records why.
- [ ] No CLI surface of `run_comparison.py` changed.

**6. Failure and edge cases.**
- A script site needs the spec but has no run context → record the
  acquisition point; if it needs a new CLI argument, that is a **STOP**
  (§3.2).
- A historical-artifact reader is migrated by mistake → it would stop
  matching files already on disk; the two excluded scripts are the test of
  this rule.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/scripts -q`
- [ ] Record counts, wall time, and the unmodified status of the two excluded
      scripts.

**8. Commit boundary.** Scripts only. No engine change.

---

### C7 — Stage-B transport rung, per-site mutations, Checkpoint C

**1. Goal.** Prove the capability holds and cannot silently regress, and
cross the contract with a **real** production spawn (§6). Separate from
C2-C6 so a reviewer reads the behaviour change and the "what must never
regress" evidence independently.

**2. Scope.**
- The Stage-B rung (§5), one mutation per production site, and the
  Checkpoint-C scenario.
- **Non-goals**: no production behaviour change in this commit.
- Depends on: C2, C3, C4, C5, C6.

**3. Implementation plan.**
- [ ] Build the §5 rung: with a **renamed** template supplied as ONE injected
      runtime spec **in-process at the owned seams**, assert producer, path
      builder, cleanup and launcher move **together** — one axis, nothing
      else varied. Per §3.2a this rung does **not** claim the renamed
      template crosses the real subprocess.
- [ ] Assert the scorer-side literals are **out of scope** explicitly, so no
      future reader mistakes the rung for "no `abra_*` anywhere" (§5).
- [ ] Run mutation evidence for **every independently failing semantic
      family** — the exact count is deliberately NOT frozen:

      ```text
      producer naming
      reader / path resolution
      cleanup glob
      writer channel / layout
      persisted value encoding
      reconstruction / launcher path
      ```

      Implementation may add finer per-site mutations **where they supply
      unique evidence**, and should not add them where they do not.
- [ ] Add a **structural guard**: no owned production surface executes an
      inlined deliverable-template authority. This is what catches a NEW site
      added later, which no value-level mutation can — it does not know the
      site exists.
- [ ] Build the Checkpoint-C scenario (§6): a real training and inference
      spawn in which the child **reconstructs the shipped default spec** and
      writes, names and cleans a deliverable through it, with the encoding
      derived, satisfying **exact logical artifact equality** (§4.1). Use a
      deterministic candidate and small/synthetic input; CPU is acceptable
      where source permits. A helper-only substitute is **insufficient**.
- [ ] Restore every mutation from clean source and re-verify green.

**4. Validation plan.**
- *Unit*: the rung and the per-site mutations.
- *Integration*: Checkpoint C through the real spawn boundary, not a helper.
- *Negative*: the rung must **not** fire on the legitimate single-spec
  binding.
- *Backward-compat*: TIDMAD parity unchanged by this commit (it adds no
  production change).
- *Gate*: **Gate 2 is REQUIRED (§9) and is C8** — not launched here.

**5. Acceptance criteria.**
- [ ] The rung reds for **every semantic family** above, and each failure
      message names the family (and the site, where the mutation was
      per-site).
- [ ] The structural guard reds when any owned surface re-inlines a
      deliverable-template authority.
- [ ] Each mutation's site count is asserted as exactly 1 before it is
      applied, and every mutation is restored from clean source with the tree
      re-verified green.
- [ ] A **surviving** mutation is classified (real gap / equivalent /
      unreachable / wrong fixture) **before** the oracle is strengthened.
- [ ] Checkpoint C crosses a **real spawn**, and the child's reconstructed
      spec is proven **equal** to the parent's; a helper-only substitution is
      explicitly rejected in the record.
- [ ] The artifact written by that spawn satisfies §4.1 equality.
- [ ] The post-cleanup filesystem set after the real spawn equals the C0
      capture's shape.
- [ ] No production file is modified by this commit.

**6. Failure and edge cases.**
- A mutation **survives** → inspect the test architecture before adding an
  assertion; classify as real gap / equivalent / unreachable / wrong fixture.
- The real spawn cannot run without a GPU → record it; that is §9's Gate-2
  trigger.
- Checkpoint C leaves artifacts behind → assert cleanup ran, and do not let
  the test's own tmp dir hide a production cleanup failure.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit tests/integration -q`
      *(narrow at implementation time)*
- [ ] Record counts, wall time, each mutation's expected vs observed result,
      and the restored-green re-run.

**8. Commit boundary.** Evidence only. No production change.

---

### C8 — bounded Gate 2 (REQUIRED)

**1. Goal.** Confirm on real hardware what deterministic testing structurally
cannot: that a real attempt trains, infers, **writes a real artifact**,
scores it and cleans it, with names and encoding resolved through the
contract. Failure classes 1, 2 and 4 are precisely the ones that survive
deterministic tests (§9).

**2. Scope.**
- One bounded real attempt. **Non-goals**: not a matrix, not a campaign, not
  a comparison against a baseline score (§10).
- Depends on: C7 green, and a clean tree at the exact head.

**3. Implementation plan.**
- [ ] Read `docs/gates/gate_testing_standard.md` **at implementation time**
      and follow the then-current standard; do not rely on this document's
      summary of it.
- [ ] Use the current approved pro LLM configuration
      (`llm_configs/openai_tiered_pro.json` per the standing operator
      decision — re-verify it is still current).
- [ ] Size the **smallest** case that trains, infers, writes, scores and
      cleans one attempt.
- [ ] Write the Gate-readiness packet **before** launching: the one property
      proved, the exact PASS artifact, the bounded wall-clock/round/epoch
      limits owned by the harness, and the failure-classification scheme.
- [ ] Run it under the **current** `gate_testing_standard.md` and the filled
      Implementation Working Rules. When the projected cumulative validation
      is inside the authorized bounded budget, **continue autonomously**;
      when it materially exceeds that budget, **STOP with a cost/runtime
      projection**.
- [ ] After the run: record actual runtime, cost, the exact result, and any
      deviation from the planned execution.

**4. Validation plan.**
- *Gate*: one bounded real attempt, **listed separately from every
  deterministic test above**.
- All deterministic tests, lint, format and locally available static checks
  must already be green at the exact head before it is launched, and the
  executable head must be committed with a clean tree.

**5. Acceptance criteria.**
- [ ] The run writes a real deliverable whose **name** was resolved through
      the spec and whose **encoding** was derived — both verified from the
      artifact on disk, not from a log line.
- [ ] The scorer reads that artifact successfully — proving producer and the
      untouched Step-06 reader still agree.
- [ ] Cleanup removes it, and the post-run filesystem set matches
      expectation.
- [ ] Actual wall time and cost are recorded against the projection.
- [ ] A failure is classified against the pre-declared scheme, not
      re-interpreted after the fact.

**6. Failure and edge cases.**
- The Gate fails for a diagnosed in-scope defect → repair, record, re-run the
  **minimum** necessary retry.
- It fails for a harness or transient reason → one bounded rerun only, and
  only when the fix does not change the tested SHA.
- Projected or cumulative cost exceeds the authorized budget → **STOP** with
  a projection before launching.

**7. Verification commands and evidence.**
- [ ] The exact bounded launch command, recorded before the run.
- [ ] Record: runtime, cost, artifact paths, PASS/FAIL, and the full log
      location. Never claim a Gate passed from an exit code alone.

**8. Commit boundary.** Gate evidence and its ledger entry only.

---

### C9 — terminal validation, docs, CI

**1. Goal.** Establish terminal evidence and leave the PR reviewable.

**2. Scope.** §15 ledger, the touched node/skill/module docs, CI iteration.
**Non-goals**: no new capability; no scope expansion.
Depends on: C8 (or C7, if Gate 2 is re-dispositioned by evidence).

**3. Implementation plan.**
- [ ] Synchronize §15 with actual findings, deviations and evidence.
- [ ] Update the touched docs as the **last** pre-merge step, quoting each
      documented flag/default against merged source (CLAUDE.md doc-sync rule).
- [ ] Run the terminal checks from a **clean tree**.
- [ ] Open/update the PR; drive exact-final-head CI green.
- [ ] Verify local HEAD == PR `headRefOid` == successful CI `headSha`.

**4. Validation plan.**
- Directly affected tests · focused integration · mutations · `ruff check` ·
  `ruff format --check` · required static/type checks · exact-head CI.
  **No local full suite by default.**

**5. Acceptance criteria.**
- [ ] Every verdict read from the **log file**, never a wrapper's exit status.
- [ ] The three identities match, each read rather than reconstructed.
- [ ] Working tree clean; §15 records every deviation.
- [ ] If local pyright cannot run (the 05a/05b precedent: host Node too old),
      that limitation is **recorded** and no local type claim is made.

**6. Failure and edge cases.**
- The full-suite/preflight guard reds on a dirty tree → commit the checkpoint
  first; never relax the guard.
- CI fails on an environment-only check → diagnose and fix autonomously; not
  a stop condition.

**7. Verification commands and evidence.**
- [ ] The terminal command set, with counts and wall time recorded.
- [ ] CI run id and exact `headSha`.

**8. Commit boundary.** Documentation and CI-driven fixes only.

---

### 14.1 Commit-boundary discipline (binding for every commit above)

Before each semantic commit, **record in the live ledger (§15)**: the exact
`git diff --stat`, the staged file list, the tests run with counts and wall
time, and any deviation from this plan. A commit whose evidence cannot be
written down that way is not ready.

**This is internal evidence discipline, not an operator pause.** The agent
records and continues.

Never mark a checklist item `[x]` before the evidence exists. An unperformed
exact command is recorded as **DEVIATED** or **SUPERSEDED** with what was
actually run — the 05a/05b precedent.

### 14.2 C0-C9 and Checkpoints 0/A/B/C/D are NOT operator pause points

They are semantic evidence milestones inside ONE autonomous PR
implementation. They are not child PRs, not approval boundaries and not
reasons to stop.

After implementation authorization, ordinary findings follow:

```text
inspect -> classify -> record in the live ledger -> fix -> validate -> continue
```

Do not return progress merely because a commit landed, a checkpoint passed, a
mutation found something, the PR opened, or CI started. Only a **MATERIAL
STOP** (§13) — or a projected validation exceeding the authorized budget —
returns early. Gate **launch scope** is not an operator design decision: it
belongs to the filled Implementation Working Rules and the current Gate
standard.

### 14.3 Out of scope for these commits

Two things are **not** implementation work and require separate evidence and
operator approval:

- **planner exposure** — nothing in this PR may surface the deliverable
  contract to the LLM planner;
- **production-default changes** — the TIDMAD deliverable name, layout,
  attrs and encoding are the shipped defaults and do not move.

Do not design the future empirical comparison campaign here. Only the
validation needed to implement the feature safely is in scope.

## 15. Implementation ledger

*(empty — populated at implementation kickoff)*

## 16. Remaining operator decisions

1. **Deliverable Contract provisional ownership and its timing rule (§3)** —
   **CONFIRMED BY OPERATOR (2026-08-15). CLOSED.**

   ```text
   Step 05c    producer-side PROVISIONAL DeliverableSpec extraction;
               final ownership remains OPEN.
   Step 06     next MANDATORY ownership review. It must either
                 CONFIRM final ownership, or
                 record exactly what consumer evidence is still missing
                 and keep the row OPEN.
   Steps 08/11 may add later evidence; NEITHER is predetermined as the
               final owner.
   ```

Revision 2 raised two more from the re-audit; **both are now decided:**

| Decision | Resolution |
|---|---|
| **OD-05c-2** — how far the writer migration goes, given that `create_abra_file` hardcodes channel groups **and** 5 instrument attrs, one duplicating `DatasetConfig.sampling_frequency` | **Derive the channel names; leave the attrs literal** (2026-08-15). Channel identity is a declared Step-02 fact the writer contradicts; the attrs are read by **no** production consumer, so deriving them would make 05c own metadata nothing reads. The `sampling_frequency` duplication is recorded as debt for final ownership (§0.3) |
| **OD-05c-3** — the three scripts revision 1 never censused | **Migrate `run_comparison.py`; leave both `score_tidmad_official_*` scripts literal** (2026-08-15). The launcher reconstructs the producer's path, so a rename would break baseline scoring silently; the official-paper scripts read **historical** artifacts and must keep matching names already on disk (§0.1) |

**Remaining operator decisions: NONE.**

Gate **launch scope** is explicitly not an operator design decision — Gate 2
is REQUIRED (§9), its shape is "the minimum bounded real attempt" under the
current Gate standard, and its cost/runtime limits belong to the filled
Implementation Working Rules. Gate-2 *scope* is **not** an operator design decision:
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
