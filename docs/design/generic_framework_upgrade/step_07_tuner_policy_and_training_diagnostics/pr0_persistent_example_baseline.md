# Step 07 — PR0: Persistent Example Baseline (preflight) — detailed design

| Field | Value |
|---|---|
| Parent | `../step_07_tuner_policy_and_training_diagnostics.md` (revision 2 — APPROVED FOR FREEZE by the operator 2026-08-15) §8.1 — PR0 has **no semantic child letter** (Q2) |
| Roadmap | §22.23 (persistent example packs), §22.23.6 (PR0), §22.9a (frozen Track B/C specifications), §22.11a, §22.12 row 07; §15.1 step-7 rows |
| Design base | `d432cf05` (master). Rev 5.3 **Q4 FROZEN**, parent **FROZEN** and this child **FROZEN** (operator, 2026-08-15) — implementation may begin under a fresh Implementation Working Rules contract |
| Depends on | Steps 00–06 MERGED. No code dependency on 07a/07b/07c |
| Decomposition | ONE PR, four commits **C1 → C2 → C3 → C4** (§15) |
| Gates | Gate 1 NOT REQUIRED · Gate 2 NOT REQUIRED (§10) — no production code, no LLM-visible byte, no execution change |
| Status | **FROZEN — OPERATOR APPROVED 2026-08-15** (revision 2; the six review corrections of §0.5 applied; one non-semantic correction at freeze: C4 validation plan `(a)–(g)`). **IMPLEMENTED 2026-08-15 — C1–C4 landed on branch `step07-pr0-persistent-example-baseline` from base `d572445a` (C1 `248a227c` · C2 `c78a148b` · C3 `57031cd1` · C4 `f9398056` = final executable head, + this docs-sync commit = final PR head); **MERGED — PR #214, squash `79403b44` (2026-08-15T23:00:09Z; `git diff fd16de42 79403b44` empty), exact-head CI 31911929243 SUCCESS on `fd16de42`; operator-approved merge with the three bounded deviations accepted (§14.0/§14.1). PR0 COMPLETE / CLOSED; next = 07a design (fresh Implementation Working Rules contract).** §14 is the implementation ledger (§14.0 re-audit, §14.1–§14.4 per-commit evidence, §14.5 acceptance summary) |

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**What is frozen (operator approval 2026-08-15)**: the capability (§1), the
per-pack content classes, the "projection, never authority" rule and the
read-only-snapshot UX invariant (§3), the manifest derivation rules
(§3.2/§3.3 — DAVIS sequence-level only), the maturity-scoped nature of every
PR0-only guard (§3.5), the Stage-A criterion (§5), the declaration evidence
(§6), the validation-consumer statement (§4/§7), the failure classes (§8),
the Gate disposition (§10), the stop conditions (§13). **What is NOT frozen**:
exact file names inside a pack beyond the categories the roadmap names,
helper structure, test-file decomposition, source line numbers (reading
aids captured at `d432cf05`). Re-read the touched source immediately before
implementing each commit.

---

## 0. Pre-design source audit (at `d432cf05`)

Every fact below was read at the cited line (parent §2.5 + this child's own
reads); nothing is inferred from the roadmap.

### 0.1 Repository conventions that decide the layout

| Fact | Evidence | Consequence for PR0 |
|---|---|---|
| No `examples/` exists; `setuptools` include list excludes it | `pyproject.toml:35-41` | `examples/` is not importable as a package — the separability property (§22.23.9) holds by construction |
| ruff has NO include list (excludes only); pyright is an allowlist without `examples`; CI runs `pytest tests/unit/` | `pyproject.toml:69-81`, `pyrightconfig.json:2-13`, `.github/workflows/ci.yml:52-61` | no production `.py` under `examples/` (parent OD-S7-5); the pack generator lives under `tools/` (pyright-checked, ruff-checked, packaged); tests live under **`tests/unit/examples/`** so CI collects them |
| `test_step04b_task_description_single_source.py` rglobs `configs/*.yaml|yml` for a runtime `task_description` key | `tests/unit/workflows/test_step04b_task_description_single_source.py:174-187` | nothing PR0 writes goes under `configs/`; PR0 adds its own guard that no YAML under `examples/` declares a top-level `task_description` / `forward_contract` (a hand-written parallel copy — §22.23.1) |
| `test_repo_hygiene.py` scans the git index for mock paths / runtime artifacts | `tests/unit/test_repo_hygiene.py:33-58` | manifests + docs trip nothing |
| `.gitignore` has no `*.csv` / `*.json` / `*.h5` rule; ignores `*.pdf` | `.gitignore` | tracked manifests are fine; PROVENANCE must cite papers by URL/DOI, never ship a PDF |
| `docs/README.md` is a master index ("a row for every doc under docs/"), unenforced | `docs/README.md` header | C4 adds the row for this child |
| no `PROVENANCE`/`STATUS` convention; nearest precedent `reference_data/official_paper_result/README.md` | `reference_data/` | PR0 establishes the three-file convention for packs (README / PROVENANCE / STATUS) — the roadmap's categories, not new authority |
| test packages use `__init__.py` | `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/core/__init__.py` | `tests/unit/examples/__init__.py` |

### 0.2 The TIDMAD authorities a projection reads, and their serializers

| Authority | Accessor (production) | JSON form already produced by production |
|---|---|---|
| `DatasetProfile` (TIDMAD) | `execute_tools/dataset_config.py:596` `resolve_dataset_profile()`; `TIDMAD_PROFILE` `:571-587` | `core/sandbox_executor.py:1244-1266` `_write_dataset_profile_config` → `model_dump()` |
| `ModelIOContract` (TIDMAD, authored in YAML) | `workflows/task_config.py:196` `run_bound_model_io_contract()` (from `configs/task_config.yaml:20-45` via `load_task_config` `:86`) | `core/sandbox_executor.py:1214-1242` `_write_model_io_config` → `model_dump(mode="json")` |
| `DeliverableSpec` | `execute_tools/deliverable_spec.py:332` `derive_tidmad_deliverable_spec(profile)` (frozen models `:101,:224,:292`) | none by design (derived on both sides, `:337-339`) — the projection derives and dumps |
| `MetricSpec` | `execute_tools/evaluation_metric.py:549` `derive_tidmad_metric_spec(profile, deliverable_spec)`; `MetricSpec` `:355-387` (frozen, `extra="forbid"`, `scoreability: SerializeAsAny[ScoreabilityContract]`) | none — the projection derives and dumps (`model_dump(mode="json")`; `SerializeAsAny` keeps the concrete contract's fields) |
| task description / forward contract | `workflows/task_config.py:228` `get_task_description(load_task_config())`; the YAML itself is the declarative source | the pack REFERENCES `configs/task_config.yaml` (owning path); it does not copy it |
| health policy | `configs/health_checks.yaml` (`health_gates:` list) | the pack REFERENCES it; applicability semantics are Step 08's |

### 0.3 Representability of the two contrast tasks TODAY (honest per-contract audit)

| Contract | Pets (37-way RGB classification) | DAVIS (RGB 8→4 future frames) | Evidence |
|---|---|---|---|
| `ModelIOContract` | **DECLARABLE**: input `[B, 3, 144, 144] float32` (axes: `B` symbolic/batch, three fixed unrolled axes), output `[B, 37]` with the `class` role fixed 37 → `output_semantic = CATEGORICAL`, `class_cardinality = 37` | **DECLARABLE**: `[B, 3, 8, 128, 224] float32` → `[B, 3, 4, 128, 224] float32`, no `class` axis → `CONTINUOUS`; the input/output T extents differ (8 vs 4) — fixed dims, no shared symbol conflict | `agent/schemas/model_io_contract.py:60-130` (roles optional, `Dimension` fixed/symbolic/dynamic), `:220-300` (`output_semantic` derived from roles; contract is rank-agnostic — "rank/axes remain free") |
| `MetricSpec` | **DECLARABLE**: `accuracy` / `higher`, `macro_f1` / `higher` — scalar-only, `PresenceScoreabilityContract`; **`log_loss` REFUSED** by the lexical rule (D16) | **DECLARABLE**: `mse` / `lower` (global mean), `psnr` / `higher`, `mae` / `lower` — none loss-shaped | `evaluation_metric.py:115-143` (`_is_loss_shaped`, `_reject_loss_shaped`), `:215-243` (`PresenceScoreabilityContract`), `:355-387` |
| `DatasetProfile` | **NOT representable**: `DatasetConfig(psd_segment_length, segments_per_file, num_files, sampling_frequency, training/validation_file_pattern)`, `ChannelIdentity`, `ValueEncoding(int8…)` are 1-D segment / two-channel HDF5 semantics | same | `execute_tools/dataset_config.py:318-325, 439-470, 571-587` |
| `DeliverableSpec` | **NOT representable**: per-file HDF5 naming/storage | same | `execute_tools/deliverable_spec.py:285-300, 332-363` |
| task description / forward contract | the prose can be WRITTEN, but the single runtime authority is single-task (`configs/task_config.yaml`); a pack-level binding is Step 12 | same | `workflows/task_config.py:86-172` (memoized single path) |
| health config | not representable as applicability-by-declaration until Step 08 | same | `configs/health_checks.yaml`; roadmap §22.12 row 08 |

**Consequence (frozen)**: PR0 records exactly this table in each contrast
pack's STATUS — the two declarable contracts land as L0/L1 declarations
through the REAL schemas; the four non-representable rows are named as D14
(profile / deliverable / reader / plugin) and Step 12 (binding) / Step 08
(health) seams. Nothing is bent to fit.

### 0.4 Official metadata this PR may consume (bounded; nothing large committed)

| Track | Metadata artifact | Use | Provenance to record |
|---|---|---|---|
| Pets | `annotations.tar.gz` (~19 MB, official VGG page; contains `annotations/list.txt`, `trainval.txt`, `test.txt` — image id · class id (1–37) · species · breed id) | derive image-id · class · scope manifests | URL, fetch date, SHA-256 of the archive, line counts of the three lists |
| DAVIS | official 2017 sequence lists (`ImageSets/2017/train.txt` = 60, `val.txt` = 30) — from an official METADATA source (the challenge's published tooling / list files); PR0 reads NO archive body | sequence · scope manifest ONLY (clip identity → D14 in full, operator 2026-08-15) | source URL, fetch date, SHA-256 of the list bytes |

No image, frame or archive body is downloaded into the repository or the
workspace by this PR; the ~19 MB Pets annotation archive is fetched to a
temporary location, consumed by the generator, and NOT committed (only its
SHA-256 and the derived manifests are).

### 0.5 Operator review of revision 1 (2026-08-15) — corrections applied in this revision

| # | Correction | Where |
|---|---|---|
| 1 | Every PR0-only guard is **maturity-scoped** with a named relaxation owner — never a permanent repository rule; the three roots MUST exist, they are not the only examples SIDERIUS may ever contain | §3.5, C4 |
| 2 | Generated TIDMAD JSON = **read-only RESOLVED snapshot**, visibly identified (`resolved/`, DO-NOT-EDIT banner, "runtime does not read this file"); a migration rule so later real task bindings never coexist ambiguously with PR0 snapshots | §3.1, §3.6, C1 |
| 3 | DAVIS PR0 freezes **sequence-level identity only**; task semantics 8→4 / stride 1 fixed; ALL clip `(sequence, start_frame)` identity → D14; archive-listing machinery removed | §3.3, C3 (roadmap §22.9a / §22.23.5 annotated) |
| 4 | "First production consumer" replaced: PR0 creates **no production seam and no runtime consumer**; CI projection/declaration tests are the validation consumer; production authorities are the SOURCE — the consumer-less-seam rule is not implicated | §4, §7 |
| 5 | SHA-256 is an **integrity / provenance pin**, not by itself an immutability proof (canonical identity = frozen rule + official provenance + review + source hash) | §3.2, §3.3, §6, §8 |
| 6 | `tools/example_packs/` APPROVED as PR0 generation / projection **tooling**; later runtime / data-path designs (D14, Step 12) are NOT required to reuse it (OD-PR0-1) | §3.1, §13.1 |

---

## 1. Capability / final effect

> The repository holds three user-facing example packs —
> `examples/tidmad/`, `examples/oxford_iiit_pet/`,
> `examples/davis_future_prediction/` — each with README / PROVENANCE /
> STATUS at its HONEST maturity: TIDMAD projects the contracts production
> already resolves (verified equal by test, never a second authority);
> Pets and DAVIS carry SHA-256-pinned IDENTITY manifests derived from official
> metadata, L0/L1 declarations through the real `ModelIOContract` and
> `MetricSpec` schemas, and a STATUS that names exactly which seams D14 /
> Step 08 / Step 12 must land. `tests/unit/examples/` proves all of it in CI.
> **No production behaviour changes.**

The precise invariants:

1. **Projection, never authority.** Every semantic value in
   `examples/tidmad/` is either GENERATED from the owning production
   authority (and a test regenerates and deep-compares it) or a REFERENCE
   to the owning path. No hand-written parallel copy exists.
2. **Instance data is the pack's.** Manifests, provenance, checksums and
   the pack's own declared instance values (Pets/DAVIS contract and metric
   declarations) are owned by the pack (§22.23.1) — they interpret no rule.
3. **Honest maturity.** STATUS claims nothing that has not landed; the
   non-representable contracts are named as seams, not hidden.
4. **Nothing large, nothing executable — at PR0.** No raw data, no loader,
   no plugin, no launcher, no production `.py` under `examples/` (a PR0
   maturity pin, §3.5 — not a permanent rule).
5. **Snapshots are visibly read-only.** Generated projections are labelled
   resolved snapshots; nothing suggests editing them changes runtime.
6. **Tooling is tooling.** `tools/example_packs/` generates and projects;
   it is not a dataset loader, not a composition system, and no later design
   is obliged to reuse it.

---

## 2. Source evidence for the design decisions

- Layout & tooling: §0.1. Authorities & serializers: §0.2. Representability: §0.3.
- The frozen task specifications (values, scopes, objectives, metrics,
  optional metrics, licence wording): roadmap §22.9a — this child pins them
  as literals in tests (never read back from the pack).
- Manifest rules: §22.9a ("the manifest is the authority, the seed is
  provenance only; the three scopes are disjoint; runtime resampling is
  forbidden"; DAVIS "sequence-disjoint, never frame-level random splits").
- Data lifecycle: §22.23.10 (nothing prepared into the tracked tree; the
  machine-local data area is `tidmad_data_config.yaml`'s today, D14 decides
  its generalization).

---

## 3. Scope

### 3.1 Files / directories expected to change (categories are the roadmap's; names are this child's)

```text
examples/
  tidmad/
    README.md            task · objective · which contracts the pack demonstrates · owning paths
    PROVENANCE.md        TIDMAD data source (paper, official distribution), local data-root mechanism
                         (tidmad_data_config.yaml — reference, no path), reference_data/ pointers
    STATUS.md            maturity: production-backed for the projected contracts; what is NOT projected
    resolved/            GENERATED, READ-ONLY resolved snapshots (JSON) with a DO-NOT-EDIT banner
                         file: dataset_profile · model_io_contract · deliverable_spec · metric_spec ·
                         identity (file indices + file families derived from the profile) — each
                         regenerated + deep-compared by test; runtime never reads them (§3.6)
    data/README.md       how the data root is configured today (reference to the config mechanism)
  oxford_iiit_pet/
    README.md · PROVENANCE.md · STATUS.md
    data/manifests/      identity manifests (train / validation / final) + SHA256SUMS
    data/README.md       acquisition instructions (official URLs; nothing fetched by the framework)
    declared/            the pack's OWN L0/L1 declarations (JSON): model_io_contract · metric specs
                         (accuracy, macro_f1) — validated through the real schemas by test;
                         log_loss documented as D16-blocked (NOT declared through the schema).
                         Distinct from tidmad/resolved/: these are instance declarations the pack
                         owns (§22.23.1), not snapshots of a production authority
  davis_future_prediction/
    README.md · PROVENANCE.md · STATUS.md
    data/manifests/      sequence-level identity manifest ONLY (clip identity → D14)
    data/README.md
    declared/            model_io_contract · metric specs (mse, psnr, mae)
tools/example_packs/     PR0 generation / projection TOOLING (projection + manifest derivation +
                         declaration writers); pyright/ruff-checked; core NEVER imports it; the
                         tests import it; NOT a runtime component — D14 / Step 12 are free to
                         ignore it (OD-PR0-1)
tests/unit/examples/     acceptance tests (§4–§8)
docs/…                   this doc's ledger, README index rows, docs/README.md row, roadmap
                         §15.1 / §22.12 status sync at Checkpoint E
```

### 3.2 Pets identity-manifest derivation rule (FROZEN)

- Source: the official `annotations/trainval.txt` and `annotations/test.txt`
  (image id, class id 1–37).
- `final` scope = the official test list, verbatim.
- `train` / `validation` = a breed-stratified deterministic 80 / 20 of the
  official trainval list: for each class, sort image ids
  lexicographically; the entry at position `i` (0-based) goes to
  `validation` iff `i % 5 == 4`, else `train`. No RNG, no seed —
  the rule is the provenance.
- Manifest row: `image_id · class_index (0-based, = official class id − 1)
  · official_class_id · scope`. Scopes are pairwise disjoint; every trainval
  image appears exactly once in `train ∪ validation`.
- SHA-256 of each manifest file is pinned in `SHA256SUMS` and asserted by
  test as an **integrity / provenance pin** (it detects corruption and names
  the exact bytes reviewed; it does NOT by itself prove immutability — a
  manifest and its pin can change together). What makes the identity
  canonical is the frozen rule above + the official source's recorded SHA-256
  + review of any regeneration commit. Regeneration is an explicit operator
  act with provenance.

### 3.3 DAVIS identity-manifest derivation rule (FROZEN)

- Source: the official 2017 `train.txt` (60 sequences) and `val.txt` (30).
- `train` scope = the 60 official train sequences.
- `validation` / `final` = the 30 official val sequences sorted by name;
  position `i` (0-based) goes to `validation` iff `i % 2 == 0`, else
  `final` (15 / 15). Sequence-disjoint by construction.
- Manifest row: `sequence_name · scope`. SHA-256 pinned (integrity /
  provenance pin, as §3.2).
- **Task semantics fixed** (8 context → 4 future frames, stride 1, §22.9a).
  **Clip identity `(sequence_name, start_frame)` — ALL of it — is D14's**
  (operator decision at the PR0 design review 2026-08-15, superseding the
  "if feasible" branch of OD-S7-9): which windows materialize, how frame
  counts map to sample windows and how Gate subsets nest belong with the
  executable data path. PR0 writes NO clip manifest and NO archive-listing
  machinery; STATUS records "clip identity → D14".

### 3.4 Non-goals (must remain unchanged)

- No production code path; no change under `core/`, `agent/`, `nodes/`,
  `execute_tools/`, `workflows/`, `configs/`, `ml_models/`, `scripts/`,
  `sdsc_submission_scripts/`, `dashboard/`.
- No golden regenerated; no test outside `tests/unit/examples/` modified
  except an additive scan-target list if a guard is extended (none expected).
- No loader / reader / plugin / launcher / skill; no `.py` under `examples/`.
- No image, frame or archive body committed or cached into the tree.
- No resolution of D16 / D17 / D18; no `DatasetProfile` / `DeliverableSpec`
  extension (D14).
- No `examples/common/`.
- No DAVIS clip manifest, no archive-listing / HTTP-range machinery.

---

### 3.5 PR0-only guards are MATURITY PINS, not permanent repository rules (FROZEN)

The end state (§22.23.3/§22.23.11) has packs with `plugins/`, `configs/`,
`skills/` and — under Step 12's composition mechanism — a real bound
task-instance declaration. Every guard PR0 adds therefore carries a
retirement / relaxation owner and says so in its docstring:

```text
guard                                    valid through        relaxation owner
the three persistent roots MUST exist    permanent            —  (they are the mandatory
  (tidmad · oxford_iiit_pet ·                                     regression examples; ADDITIONAL
   davis_future_prediction)                                       roots are permitted later under
                                                                  normal example-pack governance —
                                                                  the guard asserts presence, NEVER
                                                                  "these are the only examples")
no .py under examples/                   PR0 / Step 07        D14 (first example-local plugin /
                                                              prepare tooling), re-scoped there
no top-level task_description /          before Step 12       Step 12 (task composition owns
  forward_contract YAML under examples/                       where a bound task declaration lives)
each pack has README/PROVENANCE/STATUS   permanent            —
STATUS names a maturity level            permanent            —
production packages never import         permanent            — (§22.23.9 separability)
  examples / tools.example_packs
```

A guard's docstring names its owner; relaxing it is that owner's explicit
act, recorded in that design — never a silent deletion, never a permanent
prohibition of what the roadmap intends.

### 3.6 Read-only resolved snapshots — UX invariant and migration rule (FROZEN)

- Generated projection artifacts MUST be visibly identified as read-only
  resolved snapshots, not authoring inputs: directory `resolved/`, a
  `README` / banner file in it stating `DO NOT EDIT · generated from
  <authority path> by tools/example_packs · the runtime does not read this
  file · regenerate with <command>`, and the same statement in the pack
  README and STATUS.
- Migration expectation (binding on the later owner): when Step 12 (or D14
  for the data-path facts) introduces a real user-editable task binding for
  a pack, the PR0 snapshot MUST NOT coexist with it as a second
  authoritative-looking config. The owner either replaces the snapshot with
  the real declaration, keeps it clearly under `resolved/` as a derived
  view, or keeps only the generation test. Cumulative evidence ≠ keeping
  every scaffold.

---

## 4. Consumers — PR0 introduces NO production consumer and NO production seam

Precisely: production authorities are the SOURCE of the TIDMAD projection;
the projection generator derives a tracked snapshot from them; **CI is the
validation consumer** (the projection tests regenerate from
`resolve_dataset_profile()`, `run_bound_model_io_contract()`,
`derive_tidmad_deliverable_spec()`, `derive_tidmad_metric_spec()`,
`load_task_config()` and deep-compare; the declaration tests construct the
real `ModelIOContract` / `MetricSpec`). No production code consumes the
packs, and no new runtime abstraction is created — therefore the
consumer-less-seam rule (§0 rule 8) is not implicated.

```text
production authorities  →  projection generator  →  tracked snapshot
                                                          ↑
                                                CI equality / validity tests
```

## 5. Stage-A parity (Checkpoint 0 / A)

- `git diff --stat` between the PR base and head touches ONLY
  `examples/`, `tools/example_packs/`, `tests/unit/examples/`, docs.
- Every existing golden and every existing test is untouched and green at
  the final head (Checkpoint D).
- Projection equality: for each generated TIDMAD projection file,
  `json.loads(tracked) == json.loads(json.dumps(regenerate_now()))`.

## 6. Stage-B — declaration evidence (L0/L1; not a rung)

- Pets/DAVIS `ModelIOContract` and `MetricSpec` instances construct through
  the real schemas with the §22.9a values, and their derived properties are
  what the roadmap says (`output_semantic`, `class_cardinality == 37`,
  `direction`).
- The D16 debt is pinned honestly: constructing a `MetricSpec(id="log_loss")`
  RAISES today (the test asserts the refusal, so the day D16 is narrowed the
  pack's documentation is forced to change).
- Manifests validate: counts, disjointness, class coverage (37 classes each
  present in train and validation), sequence counts (60 / 15 / 15), SHA-256
  integrity pins (§3.2 — integrity / provenance, not immutability).

## 7. Checkpoint C — deterministic validation, no live consumer to prove

No chain and no runtime consumer exists to integrate (§4). Checkpoint C is
satisfied by the CI validation consumer: the projection tests exercise the
production accessors as SOURCE end to end (`load_task_config` →
`run_bound_model_io_contract`; `resolve_dataset_profile` →
`derive_tidmad_deliverable_spec` → `derive_tidmad_metric_spec`) and the
declaration tests construct the real schemas.

## 8. Failure classes (design-time; each has a test or a stop rule)

| Failure | Behaviour |
|---|---|
| projection file drifts from the production authority | test FAILS (deep-compare); resolution is regeneration in the SAME commit as the intentional authority change, with provenance — never a silent update |
| a YAML under `examples/` declares a top-level `task_description` / `forward_contract` (parallel copy) | guard test FAILS |
| production package imports `examples` or `tools.example_packs` | guard test FAILS (separability §22.23.9) |
| manifest SHA-256 mismatch (corruption) / duplicate ids / non-disjoint scopes / class count ≠ 37 / missing class in a scope / sequence counts ≠ 60-15-15 | test FAILS (the rule tests + review, not the pin alone, guard identity) |
| official metadata source unavailable at implementation time | STOP the commit that needs it (C2 / C3); never fabricate; record in the ledger |
| DAVIS clip identity | not a PR0 concern — D14 in full (§3.3); STATUS says so |
| a schema must be bent to declare Pets/DAVIS | STOP; STATUS records "not representable" (§0.3 already predicts none for the two declarable contracts) |
| `log_loss` declared through the schema | impossible today (D16); the test asserts the refusal |
| any production file appears in the diff | STOP; the PR is docs + packs + tests only |

## 9. Test disposition

No existing test is touched. New family `tests/unit/examples/` (each test
names the defect only it catches: projection drift · parallel copy ·
separability · manifest integrity · declaration validity · D16 pin ·
§22.9a literal drift). No test asserts a value read back from the pack.

## 10. Gates — from the standard's table (`docs/gates/gate_testing_standard.md` §"Gate assignment by commit type")

| Commit type | Typical gate |
|---|---|
| Config files, YAML, schema-only | Unit only |
| New loader/renderer (pure Python) | Unit only |

Gate 1 **NOT REQUIRED**; Gate 2 **NOT REQUIRED**. Flip: any production
code path, LLM-visible byte or execution change → re-decide from the table.
No Gate is launched.

## 11. Validation budget

Targeted `tests/unit/examples/` per commit (seconds); the two guard families
once per commit; the FULL unit suite ONCE at the final executable head from a
clean tree; exact-head CI once. No real-LLM / real-training run.

## 12. Rollback boundary

Reverting the PR removes `examples/`, `tools/example_packs/`,
`tests/unit/examples/` and the doc rows; nothing else in the tree depends on
them (guarded).

## 13. Stop conditions

Any of §8's STOPs; a request to move `configs/task_config.yaml` or the
health config INTO a pack (that is Step-12 binding); pressure to add a
reader / plugin / launcher; a manifest that needs image or frame bytes; the
operator's freeze marks (Q4 + parent + this child) not present.

### 13.1 Operator decisions relevant to this child (already disposed in the parent §18)

OD-S7-5 (tests under `tests/unit/examples/`, no `.py` under `examples/`) ·
OD-S7-7 (D16 untouched; `log_loss` documented as blocked) · OD-S7-8 (Step-04
layout) · OD-S7-9 (metadata-only if feasible, else D14). **Disposed by the
operator (2026-08-15)**: **OD-PR0-1 APPROVED** — `tools/example_packs/` is
acceptable for PR0 generation / projection tooling; **D14 / Step 12 MUST NOT
be forced to reuse it as runtime infrastructure** (PR0 generator ≠ generic
dataset loader ≠ task composition system; any logic that genuinely belongs
in the framework migrates by convergence / source evidence). **OD-PR0-2
APPROVED** — the Pets breed-stratified RNG-free 80/20 rule and the DAVIS
15/15 sequence rule (§3.2/§3.3). **OD-S7-9 superseded for PR0**: clip
identity → D14 in full.

---

## 14. Implementation ledger

Implementation session opened 2026-08-15 under the operator's Implementation
Working Rules contract (interactive "stop and show before commit" cadence
OVERRIDDEN by the operator: evidence is recorded here before each autonomous
commit). Branch `step07-pr0-persistent-example-baseline` from base
`d572445a` (== `origin/master`, clean). Handoff initialised with
`tools/claude_hooks/init_pr_handoff.py`.

### 14.0 Pre-implementation re-audit at `d572445a` (source == frozen design)

- Accessors / serializers exactly as §0.2 (`resolve_dataset_profile`
  `dataset_config.py:596`; `run_bound_model_io_contract` `task_config.py:196`;
  `derive_tidmad_deliverable_spec` `deliverable_spec.py:332`;
  `derive_tidmad_metric_spec` `evaluation_metric.py:549`; sandbox dumps
  `sandbox_executor.py:1214-1266`). `DatasetProfile.model_dump()` ==
  `model_dump(mode="json")` (verified equal); `ModelIOContract` round-trips
  through `ModelIOContract(**dump)`.
- `load_task_config`'s default path is CWD-relative (`task_config.py:41`) →
  the generator and the tests pass an explicit checkout-root path.
- **Finding (bounded, affects C2/C3 tests — not C1):** `MetricSpec(**dump)`
  does NOT reconstruct from plain JSON — `scoreability` is typed as the
  abstract `ScoreabilityContract` base (`evaluation_metric.py:383`), so a
  dict validates as the base (`extra="forbid"` → rejects the concrete
  fields; the abstract class cannot be instantiated). No production path
  deserializes a `MetricSpec` from JSON (Step 06: the subprocess re-derives
  from `--dataset_profile_json`). Consequence: the C2/C3 "declaration
  validity" tests reconstruct the instance by supplying the concrete
  contract selected by `contract_id` (`PresenceScoreabilityContract`), and
  additionally rebuild the declaration from the §22.9a literals and
  deep-compare the JSON. No schema is bent; the pack's declared JSON is
  still the `model_dump(mode="json")` of a real `MetricSpec`.
- pyright cannot run on this host (Node v10.19.0 — the vendored pyright
  wrapper fails to load); pyright is CI-only for this PR (CLAUDE.md
  "Environment assumptions"). ruff check + ruff format run locally.

### 14.1 C1 — TIDMAD projection pack (evidence before commit)

- [x] Re-read the five authorities + dump forms (14.0).
- [x] `tools/example_packs/__init__.py` (tooling docstring: not a runtime
      component; OD-PR0-1), `_common.py` (repo root from `__file__`, stable
      JSON writer, SHA-256 helpers for C2/C3), `projection.py`
      (`project_tidmad(root)`, `project_identity`, `render_resolved_banner`,
      `write_pack`, `__main__`; reads ONLY the production accessors; the
      writer is the only I/O).
- [x] Generated `examples/tidmad/resolved/{dataset_profile,model_io_contract,
      deliverable_spec,metric_spec,identity}.json` + generated
      `resolved/README.md` banner (DO NOT EDIT · generated from · runtime does
      not read · regenerate command).
- [x] `examples/tidmad/{README,PROVENANCE,STATUS}.md`, `data/README.md`.
      PROVENANCE cites the paper (arXiv 2406.04378) and the official
      repository (github.com/jessicafry/TIDMAD; CC BY 4.0 per its README,
      verified 2026-08-15) — no PDF, no machine path.
- [x] Tests `tests/unit/examples/test_tidmad_projection.py` (a)–(d) with
      the two negatives, and `test_pack_governance.py` created now with guard
      (b) "no `.py` under `examples/`" + its negative (C4 extends this file;
      the guard is not duplicated in C1's file — one defect, one test).

**Deviation (bounded) — `.gitignore` line 11 `tidmad/` → `/tidmad/`.**
  Reason: the unanchored `tidmad/` (initial-commit "Virtual Environments"
  rule) also ignored `examples/tidmad/` — `git status` never showed the pack
  and a mirror of the checkout lacked it. Source evidence:
  `git check-ignore -v examples/tidmad/README.md` → `.gitignore:11:tidmad/`;
  no other `tidmad/` directory exists in the tree, no tracked path contains
  `/tidmad/`. Impact: none on production; the parent §8.1 leaves
  "`.gitignore` additions" to this child, so §5's file list is extended by
  exactly this one line (§0.1's audit had recorded only the absence of
  `*.json`/`*.csv` rules). Validation: the C4 three-root guard asserts the
  roots are TRACKED in the git index (not merely present on disk), which
  is the test that would have caught this class of defect.

Validation (C1):
  command: `.venv/bin/python -m pytest tests/unit/examples -q` → **17 passed
    in 0.10 s, rc=0** (log: scratchpad `pr0_c1.log`).
  portability: the tracked + untracked tree copied to a different absolute
    path (scratchpad `portable/`) → 17 passed (1 warning: the
    `tidmad_data_config.yaml` → `.example.yaml` fallback of
    `execute_tools/data_paths.py`, reached through the import chain of the
    profile accessor's neighbours; a warning, not a failure — C1 §6 asks to
    record which).
  static: `ruff check tools/example_packs tests/unit/examples` clean;
    `ruff format --check` clean (after one format pass); pyright: CI-only
    (14.0).
  negatives: mutated metric snapshot → deep-compare raises (test);
    banner without "does not read" → pin fails (test); `.py` in tmp mirror →
    guard finds it (test).
  Gates: none (as frozen).

C1 committed: `248a227c`.

### 14.2 C2 — Oxford-IIIT Pet pack (evidence before commit)

- [x] Bounded fetch (2026-08-15T21:57:55Z UTC, scratchpad only, NOT
      committed): `https://www.robots.ox.ac.uk/~vgg/data/pets/data/annotations.tar.gz`
      (301 → `https://thor.robots.ox.ac.uk/pets/annotations.tar.gz`), 19 173 078
      bytes, SHA-256 `52425fb6de5c424942b7626b428656fcbd798db970a937df61750c0f1d358e91`
      — **fetched twice, identical bytes** (C2 §6 reproducibility). Extracted
      only `annotations/{list,trainval,test}.txt` + `README` (SHA-256 of the
      three lists in PROVENANCE). Counts: trainval **3 680**, test **3 669**,
      list 7 349 entries; trainval ∩ test = ∅; class ids consistent with
      `list.txt`; 37 classes in each list; per-class trainval 93–100 (rule
      precondition ≥ 5 holds by a wide margin). Dataset page re-verified to
      state CC BY-SA 4.0; the archive README's "research purposes only /
      respect original websites' terms" note is recorded alongside.
- [x] Re-read `model_io_contract.py` (`Dimension` fixed/symbolic, roles
      optional, `output_semantic` derived) + `evaluation_metric.py:215-243,
      355-387`: float32 admissibility is `DtypeAdmissibility(admissible=("float32",))`.
- [x] `tools/example_packs/declarations.py` (schema-instance builders +
      `metric_spec_from_declared`: concrete `ScoreabilityContract` chosen by
      its declared default `contract_id` among the schema's own subclasses —
      the 14.0 finding; no registry restated) and
      `tools/example_packs/oxford_iiit_pet.py` (`parse_official_list`,
      `split_trainval` = the pure §3.2 rule, `derive_manifests`,
      `render/parse_manifest_csv`, `declare_model_io_contract`,
      `declare_metric_specs`, `declare_contracts`, `write_pack`, `__main__
      --annotations-dir`).
- [x] Manifest format decision (design left open): **CSV**, header
      `image_id,class_index,official_class_id,scope`, rows sorted by
      `(class_index, image_id)` (byte-deterministic regeneration); `final`
      = the official test list as a set, written in the same sort order.
      Result: train **2 946** · validation **734** (= 3 680) · final **3 669**.
      SHA-256 pins: train `b58e8791…46ea`, validation `6dfda127…7b16e`,
      final `f72580dc…7d070` (full values in `SHA256SUMS`, PROVENANCE and
      the test literals).
- [x] Declarations: `declared/model_io_contract.json`
      (`[B, 3, 144, 144] float32 → [B, 37] float32`; class axis fixed 37 →
      CATEGORICAL, `class_cardinality == 37`); `declared/metric_accuracy.json`
      (id `accuracy`, higher, aggregation
      `fraction_correct_over_final_eval_images`, `PresenceScoreabilityContract`);
      `declared/metric_macro_f1.json` (id `macro_f1`, higher, aggregation
      `unweighted_mean_of_per_class_f1_over_37_classes`). The aggregation
      identity strings are pack-owned instance values (§22.23.1) naming the
      §22.9a rule; no `log_loss` file — D16 refusal pinned by test.
- [x] `examples/oxford_iiit_pet/{README,PROVENANCE,STATUS}.md`,
      `data/README.md` (acquisition = explicit user action; D14 decides the
      machine-local location; nothing fetched by the framework).
- [x] Tests `tests/unit/examples/test_oxford_iiit_pet_pack.py`: SHA-256 pin
      (literal + `SHA256SUMS`) per manifest; official counts as literals;
      identity rule checks (uniqueness / disjointness / 37-class coverage /
      index consistency) + three negatives (duplicate id, overlap, missing
      class); **the tracked train/validation split re-derived by the frozen
      rule over the union of the two tracked manifests** (identity carried by
      the rule, no fetch needed); the rule on a synthetic list (positions,
      a class with < 5 ids, `final` verbatim); declared JSON deep-equals a
      fresh `declare_contracts()`; `ModelIOContract` renders / derives as
      frozen; both metrics reconstruct via `metric_spec_from_declared` with
      `direction == higher`; D16 pin (`MetricSpec(id="log_loss")` raises
      `names a training loss`; no `metric_log_loss.json`); STATUS seam pins;
      PROVENANCE source URL + archive SHA + licence phrase; no image /
      archive / extracted-annotation bytes under the pack.

Validation (C2):
  command: `.venv/bin/python -m pytest tests/unit/examples -q` → **35 passed
    in 0.14 s, rc=0** (17 C1 + 18 C2; log: scratchpad `pr0_c2.log`).
  static: `ruff check` clean, `ruff format --check` clean (tools/example_packs
    + tests/unit/examples); pyright CI-only (14.0).
  Deviations: NONE beyond the 14.0 reconstruction mechanism (bounded,
    recorded). Gates: none.

C2 committed: `c78a148b`.

### 14.3 C3 — DAVIS future-prediction pack (evidence before commit)

- [x] Official METADATA source located and used — NO archive body: the
      challenge's published tooling `github.com/davisvideochallenge/davis-2017`
      ships `data/db_info.yaml` (its only list file; the repo tree was
      enumerated via the GitHub API — no `ImageSets/*.txt` outside the
      archive). Fetched 2026-08-15T22:04:49Z from the pinned commit
      `97d08bf8b6201abf15509a67a985db3745a75ccd` (2017-06-07) — identical
      bytes at `master`; 12 688 bytes; SHA-256
      `b14a9c264d04ffc6f99a92985fe024a388a7ee08e115f65e4005b72527420c4b`.
      Content used: `name` + `set` for `set ∈ {train, val}` ONLY → **60 / 30**
      (design C3 §6: counts match; STOP not triggered); `test-dev` (30) and
      `num_frames` (clip-level) deliberately NOT consumed. The archive URL
      cited in `data/README.md` was HEAD-checked only (200, 832 766 765 B).
      Paper citation (arXiv 1704.00675) verified.
- [x] Re-read the model-I/O schema: differing fixed T extents (8 vs 4) are
      plain fixed dims; only `B` is shared → `_shared_symbols_are_consistent`
      passes; no class axis → CONTINUOUS, `class_cardinality is None`.
- [x] `tools/example_packs/davis_future_prediction.py` (`parse_db_info`,
      `parse_sequence_list`, `split_official_val` = the pure §3.3 rule,
      `derive_sequence_manifest` (refuses duplicate / cross-listed names —
      reports, never repairs), CSV render/parse, `declare_model_io_contract`,
      `declare_metric_specs`, `declare_contracts`, `write_pack`, `__main__
      --db-info | --lists`).
- [x] Manifest: `data/manifests/sequences.csv` (`sequence_name,scope`;
      rows by scope order then name) — **90 rows: 60 train / 15 validation /
      15 final**; SHA-256 `56ddf30f…56b2` in `SHA256SUMS`, PROVENANCE and the
      test literal. **No clip manifest** (asserted by test).
- [x] Declarations: `declared/model_io_contract.json`
      (`[B, 3, 8, 128, 224] float32 → [B, 3, 4, 128, 224] float32`);
      `metric_mse.json` (lower; aggregation
      `global_mean_squared_error_over_clips_x_C_x_T_x_H_x_W` — the frozen
      global mean); `metric_psnr.json` (higher; SAME aggregation, transform
      `psnr_db`, `transform_params={"data_range": 1.0}` — decomposed exactly
      as TIDMAD's own spec decomposes linear grand mean + `log` transform);
      `metric_mae.json` (lower). All construct (none loss-shaped).
- [x] `examples/davis_future_prediction/{README,PROVENANCE,STATUS}.md`,
      `data/README.md`; PROVENANCE carries the §22.9a licence / provenance
      wording VERBATIM (BSD statement · CC BY 4.0 annotations · RGB frames
      not masks · no single licence claimed · D14 MUST verify and pin the
      TrainVal-480p terms); STATUS records "clip identity → D14".
- [x] Tests `tests/unit/examples/test_davis_future_prediction_pack.py`
      (16 tests): SHA pin; 60/15/15 + disjointness; the tracked val/final
      split re-derived by the rule over its own union; the rule on a
      synthetic list; inconsistent official lists refused; negatives (overlap,
      a sequence outside the official 90); `parse_db_info` ignores
      `test-dev` / frame counts; no clip manifest / frame bytes; declared JSON
      deep-equals fresh; contract renders + CONTINUOUS / `None`; three
      metrics with frozen directions; MSE aggregation is the frozen global
      mean and PSNR carries `data_range == 1.0`; STATUS seams incl. "clip
      identity"; PROVENANCE licence sentences + source hash.

Validation (C3):
  command: `.venv/bin/python -m pytest tests/unit/examples -q` → **51 passed
    in 0.15 s, rc=0** (17 + 18 + 16; log: scratchpad `pr0_c3.log`).
  static: `ruff check` / `ruff format --check` clean; pyright CI-only (14.0).
  Deviations: NONE. Gates: none.

C3 committed: `57031cd1`.

### 14.4 C4 — cross-pack governance guards + docs / governance sync (Checkpoint E, pre-merge half)

- [x] `tests/unit/examples/test_pack_governance.py` — guards (a)–(g), each a
      pure function of a root so its `tmp_path` negative proves it fires:
      (a) [MATURITY PIN, owner Step 12] no YAML under `examples/` with a
      TOP-LEVEL `task_description` / `forward_contract` key (+ negative:
      top-level key flagged; prose and nested key not);
      (b) [MATURITY PIN, owner D14] no `.py` under `examples/` — on disk AND
      in the git index (+ negative);
      (c) [PERMANENT] AST scan of `core/ agent/ nodes/ execute_tools/
      workflows/ ml_models/ dashboard/ scripts/ sdsc_submission_scripts/`:
      no `import examples…`, `from tools.example_packs…`, `from tools import
      example_packs` (+ negative with three importer forms flagged, prose
      not);
      (d) [PERMANENT] README / PROVENANCE / STATUS present per pack; STATUS
      names an `L0`–`L4` level; TIDMAD also "production-backed resolved
      projection";
      (e) [PERMANENT] every README cites the roadmap document + §22.9/§22.23;
      (f) [PERMANENT] the three persistent roots exist AND are tracked (`git
      ls-files`) — presence, never exclusivity (a tmp mirror with an EXTRA
      root passes; a missing root fails);
      (g) [PERMANENT] every `resolved/` under any pack carries the read-only
      banner (+ negative: missing banner / banner without pins flagged).
- [x] `git ls-files examples | grep '\.py$'` empty (asserted by (b)).
- [x] Docs sync (this commit): this header + §14; parent §0 status + §8.1
      "landed" note; `generic_framework_upgrade/README.md` row 07/PR0;
      `docs/README.md` row for this child; roadmap §15.1 step-7 row (`§7a`)
      + §22.12 row 07 "PR0 landed (examples at honest maturity)". Merge SHA
      / MERGED status are the post-merge finalizer's (Step-06 precedent) —
      the rows say "landed on branch, awaiting merge" until then.
- [x] Push · PR #214 · exact-head CI **31911929243 SUCCESS** on final PR HEAD
      `fd16de42` (recorded in the PR body + handoff; no trailing docs-only
      push) → READY FOR OPERATOR REVIEW (2026-08-15) → operator review:
      APPROVED, deviations 1–3 accepted → **squash-merged `79403b44`**
      (2026-08-15T23:00:09Z; squash parity `git diff fd16de42 79403b44` empty).
      Post-merge finalizer (this docs-only commit on master): status mirrors
      → MERGED; no production / example / test semantics touched.

Validation (C4):
  targeted: `.venv/bin/python -m pytest tests/unit/examples -q` → **61 passed
    in 0.53 s, rc=0** (17 + 18 + 16 + 10; log: scratchpad `pr0_c4.log`).
  static (repo-wide, as CI): `ruff check .` clean (rc=0); `ruff format
    --check .` clean (915 files, rc=0); pyright: CI-only on this host (14.0).
  C4 guards commit: `f9398056` = **final executable HEAD** (the docs-sync
    commit that follows changes no executable file).
  FULL suite (ONCE, clean tree, final executable HEAD `f9398056`):
    `.venv/bin/python -m pytest tests/unit -m "not real_run" -q` →
    **9482 passed, 3 skipped, 0 failed in 585.03 s (0:09:45), rc=0** — verdict
    read from the log file (`pr0_full.log`), pytest's own status captured.
  Gates: none (as frozen; no production code path, no LLM-visible byte, no
    execution change — the flip conditions of §10 were not reached).

### 14.5 Stage-A parity / acceptance summary (§5, §22.23.13)

- `git diff --stat d572445a..f9398056` touches ONLY `examples/`,
  `tools/example_packs/`, `tests/unit/examples/`, `docs/…` and the one
  `.gitignore` line (14.1). No file under `core/ agent/ nodes/
  execute_tools/ workflows/ configs/ ml_models/ scripts/
  sdsc_submission_scripts/ dashboard/`; no golden touched.
- Projection equality: five TIDMAD snapshots deep-equal a fresh
  `project_tidmad()` (test); banner generated.
- Declaration evidence (§6): Pets `[B, 3, 144, 144] float32 → [B, 37]
  float32` categorical / 37; DAVIS `[B, 3, 8, 128, 224] float32 → [B, 3, 4,
  128, 224] float32` continuous / `None`; metrics construct with the frozen
  directions; `log_loss` refusal pinned.
- Manifests: Pets 2 946 / 734 / 3 669 (∪ = 3 680), 37 classes in every
  scope, disjoint, rule re-derived over the tracked union; DAVIS 90 = 60 /
  15 / 15, disjoint, rule re-derived; SHA-256 pins asserted from literals.
- No raw image / frame / archive / extracted-annotation bytes tracked (tests
  + `git ls-files`); no DAVIS archive body read (HEAD only).
- Separability guarded (c); three roots tracked (f); honest STATUS (d/e);
  read-only snapshots (g).

---

## 15. Commit plan — per-commit checklists

**Four commits.** C1 TIDMAD projection pack + generator + tests · C2 Pets
pack (manifests, declarations, tests) · C3 DAVIS pack · C4 cross-pack guards,
docs/index rows, governance sync (Checkpoint E). Each commit is
independently reviewable and leaves the tree green.

Before every commit: stop and show the exact diff summary, staged file list,
tests run (with counts / wall time from the log, never a wrapper's exit
code) and any deviation from this design.

---

### C1 — `examples/tidmad/`: read-only resolved-snapshot pack, generator, projection tests

**1. Goal.**
Establish the first example root as a READ-ONLY projection of what
production already resolves for TIDMAD — profile, model-I/O contract,
deliverable spec, metric spec, identity (file indices + file families) —
plus README / PROVENANCE / STATUS, so that "TIDMAD is projected too"
(§22.23.2) is true from the first PR and the projection-equality mechanism
exists before any contrast pack reuses the generator.
*Why this commit and not another*: it creates the generator and the
projection-equality test pattern the contrast packs (C2/C3) build on, and it
touches no metadata source, so it can land even if a fetch is unavailable.

**2. Scope.**
- NEW `tools/example_packs/__init__.py`, `tools/example_packs/projection.py`
  — `project_tidmad() -> dict[str, dict]` returning JSON-ready dicts for
  `dataset_profile` (`resolve_dataset_profile().model_dump(mode="json")`),
  `model_io_contract` (`run_bound_model_io_contract().model_dump(mode="json")`),
  `deliverable_spec` (`derive_tidmad_deliverable_spec(profile).model_dump(mode="json")`),
  `metric_spec` (`derive_tidmad_metric_spec(profile, deliverable_spec).model_dump(mode="json")`),
  `identity` (file indices `0..num_files-1` and the two file-name families
  rendered from the profile's patterns); a `write_pack(root)` writer; a
  `__main__` entry to regenerate. Reads ONLY production accessors (§0.2).
- NEW `examples/tidmad/README.md`, `PROVENANCE.md`, `STATUS.md`,
  `data/README.md`, `resolved/*.json` (generated) + `resolved/README.md`
  (the DO-NOT-EDIT banner: generated from <authority>, by which command,
  the runtime does not read these files — §3.6).
- NEW `tests/unit/examples/__init__.py`,
  `tests/unit/examples/test_tidmad_projection.py`.
- Non-goals: no change to any accessor; no copy of `configs/task_config.yaml`
  or `configs/health_checks.yaml` (referenced by path in README); no
  `identity` beyond what the profile derives.
- Dependencies: none.

**3. Implementation plan.**
- [ ] Re-read `execute_tools/dataset_config.py:571-616`,
      `workflows/task_config.py:86-225`, `execute_tools/deliverable_spec.py:285-363`,
      `execute_tools/evaluation_metric.py:355-387, 549-590`,
      `core/sandbox_executor.py:1214-1266` (the production dump forms) and
      confirm `model_dump(mode="json")` round-trips each (incl. `SerializeAsAny`
      scoreability).
- [ ] Implement `tools/example_packs/projection.py` (`project_tidmad`,
      `write_pack`, `__main__`); no import from `examples`; no I/O except the
      writer.
- [ ] Generate `examples/tidmad/resolved/*.json` with the writer (tracked)
      and the `resolved/README.md` banner (generated too, so it cannot drift).
- [ ] Write README (task, objective, contracts demonstrated, OWNING PATHS for
      task description / forward contract / health config / data root; an
      explicit "`resolved/` is a read-only snapshot — to change the task edit
      the owning path, not these files" statement),
      PROVENANCE (paper + official distribution URL, `reference_data/`
      pointers, `tidmad_data_config` mechanism — no machine path),
      STATUS (production-backed projection; NOT projected: launcher, plugins,
      skills, run instructions beyond the existing operator docs; Step-07
      history/policy/rendering rows to be advanced by 07a/07b), `data/README.md`.
- [ ] Tests: (a) each tracked projection deep-equals a fresh
      `project_tidmad()`; (b) the metric projection's `id ==
      TIDMAD_METRIC_ID` and `direction == "higher"` pinned as literals;
      (c) README cites the owning paths (string presence of
      `configs/task_config.yaml`, `configs/health_checks.yaml`); (d) the
      `resolved/` banner and the README/STATUS carry the read-only statement
      (string pins: "DO NOT EDIT", "does not read"); (e) no `.py` under
      `examples/` — docstring: PR0 maturity pin, relaxation owner D14 (§3.5).

**4. Validation plan.**
- Unit: `tests/unit/examples/test_tidmad_projection.py` (a–d above).
- Pseudo/integration: none needed (the accessors are the production path).
- Negative: mutate one tracked JSON value in a tmp copy → (a) fails; a
  `.py` dropped under a tmp `examples/` mirror → (e) fails; a banner
  without the read-only statement → (d) fails (tests operate on
  the checkout root derived from `__file__`, CLAUDE.md portability).
- Backward-compat: existing goldens/tests untouched (Checkpoint D).
- Gates: none.

**5. Acceptance criteria.**
- `examples/tidmad/resolved/{dataset_profile,model_io_contract,deliverable_spec,metric_spec,identity}.json`
  exist and each `json.loads(file) == project_tidmad()[key]` in the test;
  `resolved/README.md` states DO NOT EDIT / generated-from / runtime does
  not read.
- `metric_spec.json["id"] == "tidmad_denoising_score"`, `["direction"] == "higher"`;
  `model_io_contract.json` renders `[B, T] int64 → [B, 256, T] float32`
  semantics (assert `class` axis fixed 256 in the projected JSON).
- No file outside `examples/tidmad/`, `tools/example_packs/`,
  `tests/unit/examples/` in the diff.
- ruff + pyright (strict, `tools/` is in the allowlist) clean on the generator.

**6. Failure and edge cases.**
- `run_bound_model_io_contract()` returns `None` (legacy prose-only task) →
  generator writes NO `model_io_contract.json` and STATUS says so; test
  asserts presence because the current `configs/task_config.yaml` declares
  `model_io` (`:20-45`) — a regression there is caught.
- `tidmad_data_config.yaml` absent → `resolve_dataset_profile()` must not
  need it (verify; the Step-06 §20.11 import-chain debt is not touched here);
  if it does, the test still passes on the tracked `.example.yaml` fallback
  (a `warnings.warn`, not a failure) — record which.
- Projection drift → test red; fix by regenerating IN THE SAME COMMIT as the
  authority change with provenance in the message; never in a follow-up.

**7. Verification commands and evidence.**
- `.venv/bin/python -m pytest tests/unit/examples -q > /tmp/pr0_c1.log 2>&1; rc=$?; tail -20 /tmp/pr0_c1.log`
- `.venv/bin/ruff check tools/example_packs tests/unit/examples && .venv/bin/ruff format --check tools/example_packs tests/unit/examples`
- `.venv/bin/pyright tools/example_packs`
- Evidence recorded in §14: counts, wall time, rc.

**8. Commit boundary.**
- Independently reviewable: yes (one pack + its generator + its tests).
- No unrelated cleanup; no contrast-pack content; the generator is
  documented as tooling (module docstring: not a runtime component; D14 /
  Step 12 not obliged to reuse it).
- Stop and show diff summary / staged files / test log before committing.

---

### C2 — `examples/oxford_iiit_pet/`: identity manifests, L0/L1 declarations, STATUS

**1. Goal.**
Fix Track B's IDENTITY at PR0 (§22.23.5) — which images belong to train /
validation / final — derived from the official annotation lists by the
frozen rule (§3.2), SHA-256 pinned; declare through the REAL schemas what is
declarable today (`ModelIOContract`, `MetricSpec` accuracy / macro_f1) and
record honestly what is not (§0.3), including the D16-blocked `log_loss`.
*Why this commit and not another*: it is the first bounded metadata fetch;
isolating it keeps C1 fetch-free and C3's DAVIS listing question separate.

**2. Scope.**
- NEW `tools/example_packs/oxford_iiit_pet.py` — `derive_manifests(annotations_dir) -> Manifests`
  (typed rows; the §3.2 rule), `declare_contracts() -> dict` (the
  `ModelIOContract` and the two `MetricSpec` instances built from the
  §22.9a values, dumped `mode="json"`), `write_pack(root, manifests)`;
  a `__main__` that takes the local path of the extracted annotation lists.
- NEW `examples/oxford_iiit_pet/{README,PROVENANCE,STATUS}.md`,
  `data/README.md`, `data/manifests/{train,validation,final}.csv` (or JSON —
  decide at implementation, record), `data/manifests/SHA256SUMS`
  (integrity / provenance pin — §3.2),
  `declared/{model_io_contract,metric_accuracy,metric_macro_f1}.json`
  (the pack's OWN declarations, distinct from `tidmad/resolved/`).
- NEW `tests/unit/examples/test_oxford_iiit_pet_pack.py`.
- Non-goals: no images; no `DatasetProfile` / `DeliverableSpec` /
  preprocessing declaration (D14); no `log_loss` through the schema; no
  Gate-subset selection (D14 sizes them, §22.9a).
- Dependencies: C1 (generator package + test package exist).

**3. Implementation plan.**
- [ ] Bounded fetch (implementation time, recorded): official
      `annotations.tar.gz` → temp dir; record URL, date, SHA-256, sizes; DO
      NOT commit the archive or its extraction.
- [ ] Re-read `agent/schemas/model_io_contract.py` (`TensorAxis`,
      `TensorContract`, `DtypeAdmissibility`, `Dimension`) and
      `execute_tools/evaluation_metric.py:215-243, 355-387` before writing
      the declarations; confirm the float32 admissibility form for a
      `[B, 3, 144, 144]` input.
- [ ] Implement `derive_manifests` (rule §3.2) and `declare_contracts`;
      write the pack; compute and write `SHA256SUMS`.
- [ ] Write README (task per §22.9a; what the framework can/cannot do
      today; owning paths), PROVENANCE (official URLs, licence text as
      frozen in §22.9a: CC BY-SA 4.0 dataset page statement, copyright with
      image owners; archive SHA-256; the derivation rule; regeneration
      instructions), STATUS (L0/L1: contract + metric declared; D14 seams:
      profile, deliverable, reader/preprocessing, plugin, Gate subsets;
      Step 12: binding; Step 08: health; D16: `log_loss` blocked).
- [ ] Tests: manifest integrity (SHA-256 pins; row schema; 37 classes;
      each class present in train and validation; disjointness across the
      three scopes; `train ∪ validation` = 3 680 rows if the official
      trainval count is confirmed — pin the confirmed counts as literals);
      declaration validity (`ModelIOContract(**json)` constructs;
      `output_semantic == CATEGORICAL`; `class_cardinality == 37`;
      `MetricSpec(**json)` constructs for accuracy/macro_f1 with
      `direction == "higher"`); D16 pin (`MetricSpec(id="log_loss", …)`
      raises `ValueError`); the §3.2 rule reproduces the tracked manifests
      from a small in-test synthetic list (rule test, independent of the
      fetch); no `.py` under the pack.

**4. Validation plan.**
- Unit: `test_oxford_iiit_pet_pack.py` as above.
- Negative: a manifest row with a duplicate `image_id` in a tmp copy →
  integrity test fails; a scope overlap → fails; a class missing from
  validation → fails; `MetricSpec(id="log_loss")` must raise.
- Backward-compat: nothing outside the pack changes.
- Gates: none.

**5. Acceptance criteria.**
- Three manifest files + `SHA256SUMS`; the test recomputes each SHA-256 and
  matches the pinned value (integrity); the RULE test + review carry
  identity; scopes pairwise disjoint; every trainval image id
  appears exactly once in `train ∪ validation`; `final` equals the official
  test list; class indices are `0..36`.
- `declared/model_io_contract.json` constructs into a `ModelIOContract`
  whose derived `output_semantic` is CATEGORICAL and `class_cardinality` is
  37; the two metric JSONs construct into `MetricSpec` with `direction ==
  "higher"`.
- STATUS lists the seams exactly as §0.3 (test asserts the presence of the
  seam names as strings, e.g. `DatasetProfile`, `DeliverableSpec`, `D14`,
  `D16`).
- No production file in the diff.

**6. Failure and edge cases.**
- Official page/URL unavailable or archive SHA-256 not reproducible across
  two fetches → STOP C2; do not derive from a mirror; record.
- The official lists' counts differ from the roadmap's approximate figures
  (~7 400 images) → pin the OFFICIAL counts, note the difference in
  PROVENANCE (the roadmap said "~"); never adjust the rule to hit a number.
- A class with fewer than 5 trainval images → the modulo rule still yields
  ≥ 0 validation rows; the "every class present in validation" test would
  fail → STOP and report (this would be an operator decision on the rule);
  expected not to occur (≈100 trainval per class).
- Any temptation to store the extracted annotation files → forbidden;
  only derived manifests + SHA-256.

**7. Verification commands and evidence.**
- as C1, plus `sha256sum` outputs recorded in §14 and in PROVENANCE.

**8. Commit boundary.**
- Independently reviewable: one pack + its module + its tests.
- No DAVIS content; no changes to C1 files except an additive export in
  `tools/example_packs/__init__.py` if needed.
- Stop and show before committing.

---

### C3 — `examples/davis_future_prediction/`: sequence-level identity, declarations, STATUS

**1. Goal.**
Fix Track C's SEQUENCE-LEVEL identity (train 60 / validation 15 / final 15
by the §3.3 rule) from the official lists, SHA-256 pinned; keep the task
semantics fixed (8 → 4, stride 1); record "clip identity → D14" in STATUS;
declare the `ModelIOContract` and the metric specs (mse ↓ golden; psnr ↑,
mae ↓ optional) through the real schemas; record the DAVIS licence /
provenance wording exactly as frozen in §22.9a.
*Why this commit and not another*: a second, independent metadata source
(the DAVIS lists) — kept apart from the Pets fetch so either can stop
without blocking the other.

**2. Scope.**
- NEW `tools/example_packs/davis_future_prediction.py` —
  `derive_sequence_manifest(train_list, val_list)` (rule §3.3),
  `declare_contracts()`, `write_pack(...)`.
- NEW `examples/davis_future_prediction/{README,PROVENANCE,STATUS}.md`,
  `data/README.md`, `data/manifests/sequences.{csv|json}`,
  `data/manifests/SHA256SUMS`,
  `declared/{model_io_contract,metric_mse,metric_psnr,metric_mae}.json`.
- NEW `tests/unit/examples/test_davis_future_prediction_pack.py`.
- Non-goals: no frames, no archive body, NO clip manifest, no
  archive-listing / HTTP-range machinery, no window materialization /
  resize / decode rule (D14); no `DatasetProfile` / `DeliverableSpec`.
- Dependencies: C1.

**3. Implementation plan.**
- [ ] Obtain the official 2017 sequence lists (`train.txt` 60 / `val.txt`
      30) from an official METADATA source (the challenge's published
      tooling / list files) — record URL, date, SHA-256 of the list bytes.
      If no official metadata source exists apart from the archive body →
      STOP C3 and report (D14 will hold the archive anyway; PR0 never reads
      an archive body).
- [ ] Re-read the model-I/O schema before writing the `[B,3,8,128,224] →
      [B,3,4,128,224] float32` declaration (differing fixed T extents; no
      shared symbol other than `B`).
- [ ] Implement `declare_contracts` (mse/lower — aggregation identity names
      the global mean over clips × C × T × H × W as frozen; psnr/higher with
      `transform_params={"data_range": 1.0}`; mae/lower); write the pack;
      SHA-256 pins.
- [ ] Write README / PROVENANCE (the §22.9a licence wording VERBATIM: DAVIS
      repository states BSD; challenge-created annotations CC BY 4.0; this
      task consumes RGB frames, not masks; no single licence claimed for
      every artifact; D14 MUST pin the terms of the downloaded TrainVal-480p
      artifact) / STATUS (L0/L1 declared; D14 seams incl. "clip identity →
      D14").
- [ ] Tests: sequence manifest (60/15/15; disjoint; SHA-256 integrity pin;
      the §3.3 rule reproduces the split from an in-test synthetic list);
      STATUS contains "clip identity" and "D14"; declaration validity (`output_semantic == CONTINUOUS`,
      `class_cardinality is None`, `mse.direction == "lower"`,
      `psnr.direction == "higher"`, `mae.direction == "lower"`; none
      loss-shaped — assert construction succeeds); PROVENANCE contains the
      frozen licence sentences (string pins); no `.py` under the pack.

**4. Validation plan.** as C2, adapted; negative: overlapping sequence
scopes → fails; a sequence not in the official 90 → fails; a clip manifest
present under the pack → fails (PR0 must not carry one).

**5. Acceptance criteria.**
- `sequences` manifest: exactly 90 rows, 60 `train` / 15 `validation` / 15
  `final`, pairwise disjoint, SHA-256 pinned and re-verified by test.
- No clip manifest exists; STATUS contains "clip identity" and "D14".
- Contract JSON constructs; `output_semantic == CONTINUOUS`; three metric
  JSONs construct with the pinned directions.
- PROVENANCE contains the four frozen licence sentences.
- No production file in the diff.

**6. Failure and edge cases.**
- Lists unavailable from an official metadata source → STOP (never derive
  the split from memory, papers or a mirror).
- Counts ≠ 60 / 30 in the obtained lists → STOP and report (identity
  mismatch with §22.9a); do not "fix" the list.

**7. Verification commands and evidence.** as C2.

**8. Commit boundary.** one pack + module + tests; stop and show before
committing.

---

### C4 — Cross-pack guards, doc/index rows, governance sync (Checkpoint E)

**1. Goal.**
Make the acceptance criteria of §22.23.13 machine-checkable across the three
packs (no second authority · separability · honest STATUS mirrors · the PR0
maturity pins) — **each PR0-only guard maturity-scoped with a named
relaxation owner (§3.5), never a permanent prohibition** — and synchronize
the governance surfaces so the next PR (07a) starts from an accurate index.
*Why this commit and not another*: the guards span all three packs and are
only meaningful once all exist; the docs sync is Checkpoint E.

**2. Scope.**
- NEW `tests/unit/examples/test_pack_governance.py` — each guard's docstring
  states its validity window and relaxation owner per §3.5:
  (a) **[maturity pin — owner Step 12]** no YAML under `examples/` declares
  a top-level `task_description` / `forward_contract` (a hand-written
  parallel copy before task composition owns binding);
  (b) **[maturity pin — owner D14]** no `.py` anywhere under `examples/`
  (until an owner introduces example-local plugins / prepare tooling);
  (c) **[permanent]** no module under `core/`, `agent/`, `nodes/`,
  `execute_tools/`, `workflows/`, `ml_models/`, `dashboard/`, `scripts/`,
  `sdsc_submission_scripts/` imports `examples` or `tools.example_packs`
  (AST/regex over `rglob("*.py")`, checkout-root derived from `__file__`);
  (d) **[permanent]** each pack has README / PROVENANCE / STATUS and STATUS
  names a maturity level `L0`–`L4` (TIDMAD: "production-backed resolved
  projection");
  (e) **[permanent]** each pack's README cites its owning paths / roadmap
  section;
  (f) **[permanent]** the three persistent roots `tidmad`,
  `oxford_iiit_pet`, `davis_future_prediction` EXIST — the guard asserts
  presence and NEVER that they are the only roots (additional examples are
  permitted later under normal pack governance);
  (g) **[permanent]** `examples/tidmad/resolved/` carries the read-only
  banner (§3.6).
- Docs: this child's §14 ledger + header status; parent §0 status +
  §8.1 → "C1–C4 landed"; `generic_framework_upgrade/README.md` row 07 /
  PR0; `docs/README.md` row for this child; roadmap §15.1 step-7 rows and
  §22.12 row 07 "PR0 landed (examples at honest maturity)" — same PR.
- Non-goals: no new production guard beyond (c); no CI workflow change.
- Dependencies: C1–C3.

**3. Implementation plan.**
- [ ] Implement `test_pack_governance.py` (a)–(g); each test docstring names
      the defect only it catches AND (for a/b) its validity window +
      relaxation owner.
- [ ] Negative self-checks in the same file using `tmp_path` mirrors
      (a parallel `task_description:` YAML; a `.py`; a fake importer) to
      prove each guard fires.
- [ ] Update docs (list above); ledger §14 with counts / wall time / rc per
      commit and the full-suite terminal run.
- [ ] Full unit suite once at the final executable head from a clean tree
      (`pytest tests/unit -m "not real_run" -q > /tmp/pr0_full.log 2>&1;
      rc=$?; tail -20 /tmp/pr0_full.log`); exact-head CI green (id recorded
      in the PR body — no trailing docs-only push).

**4. Validation plan.** unit (a)–(g) + their negatives; full suite once;
CI once. Gates: none.

**5. Acceptance criteria.**
- All seven guards green on the checkout and each fires on its tmp
  negative; guards (a)/(b) carry the maturity-pin docstring; guard (f)
  passes with an EXTRA root present in a tmp mirror (proves it asserts
  presence, not exclusivity).
- `git ls-files examples | grep '\.py$'` empty.
- Full-suite log shows 0 failed; CI run id recorded.
- Roadmap / README / docs index rows read "PR0 landed" with the merge SHA
  filled at Checkpoint E.

**6. Failure and edge cases.**
- A guard scans a directory that does not exist on a fresh clone → guard
  must derive the root from `__file__` and skip nothing silently (assert the
  root layout it expects).
- A future pack file legitimately containing the string `task_description`
  in prose (README) → guard (a) inspects YAML top-level KEYS only.
- A later owner (D14 / Step 12) legitimately introducing a plugin or a bound
  task declaration → relaxes guard (b)/(a) in ITS design by explicit act;
  the docstring tells that owner where the pin came from.

**7. Verification commands and evidence.** as above; recorded in §14.

**8. Commit boundary.** guards + docs only; stop and show before committing.

---

### Deferred to later PRs (NOT in PR0)

- DAVIS clip identity `(sequence, start_frame)`, execution-level manifests,
  preprocessing / decode / window rules, tensor hashes, Gate-subset sizing,
  reference plugins, data acquisition into a workspace — **D14**.
- Relaxing the PR0 maturity pins (`.py` under `examples/`; a bound task
  declaration inside a pack) — **D14 / Step 12** by explicit act (§3.5).
- History / diagnosis semantics in the packs — **07a**; direction / policy /
  rendering — **07b**.
- Health applicability — **Step 08**; interpreter evidence — **Step 09**;
  binding / launcher — **Steps 10 / 12**; D16 narrowing — **Step 12**.

### Explicitly NOT re-opened

Step 06 semantics; `configs/task_config.yaml` as the single runtime task
authority; the frozen §22.9a task specifications (values are pinned, not
re-derived); the D14 placement.
