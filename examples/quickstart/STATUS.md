# STATUS — `quickstart` (honest maturity)

The roadmap (`docs/design/siderius_generic_framework_upgrade.md`, ladder
§22.10) is the vocabulary authority; this file states what THIS pack can
honestly claim on the landed post-PR-12d source it now targets (integration
base `aec713dc`, master squash `84d74280`).

## Maturity: **L2 — executable components + composition-proven, plus a LIVE-WITNESSED composed chain through REAL TRAINING (2026-08-25, bounded 1×1 arms, `certify_minimal`): composition/lock, validation of generated models (implementor-geometry fix live), tuner leg with typed failure records, real training in the composed child, P1 generated-library provenance + out-of-checkout promotion, and the #258 recovery resume ALL WITNESSED. The SCORING leg (a `metric_result` record + a persisted deliverable) remains unwitnessed — pack codec fixed here; flagged framework focal-loss seam open — L3/L4 NOT claimed.**

This is a **demonstration pack**, not a benchmark track: the reference model
does not need to train well and no scientific claim rides on the numbers.
It is deliberately not one of the three persistent §22.9a tracks (which are
L4 on the landed source). The pack's bounded live-run budget WAS spent
(2026-08-25: two authorized launches on the first head, then the
final-witness arm + one sanctioned corrective relaunch on the integrated
candidate): what was witnessed and what was not are stated per-seam below
and shown with real outputs in notebook §9/§10/§12.

| seam | status on the landed source | evidence |
|---|---|---|
| dataset identity (seeded generator + pins) | **EXECUTABLE** — regenerated bit-identically, sha-pinned, materializer refuses drift | `test_quickstart_pack.py` (determinism + drift-refusal plant) |
| `DatasetProfile` (post-B2 generic + opaque topology) | **DECLARED + LOADED** through `load_dataset_profile` in a real composition | composition test |
| task config (`declared/task_config.yaml`, **with `model_io:`**) | **COMMITTED + COMPOSED** — bound by the shipped manifest, which is what legitimizes it under governance guard (a); prose fields DERIVED from the structured contract (F-12d-4 landed) | governance + landed-pin tests |
| `MetricSpec` accuracy (higher, `deliverable_presence`) | **DECLARED + COMPOSED**; implementation scored real payloads (1.0 / 0.0 / structured refusal) | composition + metric tests; notebook §6, §10 |
| `TaskDataPath` four methods | **EXECUTABLE (L2)** — real CSV→tensor materialization (exact-validation fail-closed), real deliverable write/read under the DECLARED naming (landed `input_identity` keyword) | dataset + codec tests; notebook §10 |
| `TaskScopeCapability` sibling | **EXECUTABLE (L2)** — snapshot/anchors/target construction, eval-shard isolation, canonical serialize/deserialize; the SHIPPED seam-A `config:` reaches the constructor (counterfactually proven) | scope + landed-pin tests; notebook §5 |
| run composition (`configs/task_composition/quickstart.yaml`) | **EXECUTABLE** — the SHIPPED manifest composes fail-closed with `bind_run_task_composition` + `verify_composition_is_bound`; semantic fingerprint pins THREE plugin content hashes (task, metric, reference model) | composition test; notebook §8 |
| `model_plugins:` route (seam P / D8a) | **COMPOSED** — `require: [quickstart_reference_mlp]` resolved and enforced (a missing type refuses at composition, by name) | landed-pin test |
| task health | `EXPLICIT_NONE` — a NAMED absence, deliberately; note composed runs fire ZERO health gates today (A1 declared debt, framework-wide) | manifest; notebook §8 |
| composed chain launch / lock / manifest lifecycle | **WITNESSED LIVE (2026-08-25)** — lock pins THAT RUN's fingerprint (`9645c218…`) and TRACKS pack edits: the codec fix moved it `ede74e70…` → `9645c218…`, so the old workspace's refusal-to-resume is the designed semantics. It is not equal to today's composition — the model plugin changed after that run and the fingerprint had drifted before it (`PROVENANCE.md`, fourth exception), the task-owned `resolved_data_scope [0,1,2,3]`, the reference-model content sha, and the P1 `generated_library {root, source: env}` provenance; honest `no_records` manifests; #258 replacement with set-aside + provenance on the recovery leg | notebook §9/§10/§12 (real outputs); `PROVENANCE.md` |
| composed chain propose→implement→validate | **WITNESSED PASSING (final witness)** — the earlier implementor `TEST_TEMPLATE` legacy-geometry debt is FIXED in the landed source: generated models validated in both final-witness arms; validated capabilities PROMOTED into the env-resolved generated library, repo checkout byte-identical | notebook §9; live-run logs; capability index under the recorded root |
| composed chain training | **WITNESSED LIVE** — real training in the composed child on the pack's data (cross-entropy attempt: avg loss 0.686106, val loss 0.708563 over 64 segments, checkpoint saved; both pack plugins loaded in the child) | notebook §9 (real excerpts) |
| composed chain inference → scoring | **NOT COMPLETED** — the trained attempt's inference was refused by THIS PACK's pre-convention codec (batch item A — FIXED here, mutation-proven regression test); every other attempt was refused pre-training by the resource probe under planner-chosen legacy focal loss (batch item B — FLAGGED framework seam: loss eligibility not contract-filtered for composed tasks; `permute(sparse_coo)` 2-dim vs 3-dim) or genuinely broken conv geometry (quality-only, weak certify model). NO `metric_result` record, NO persisted deliverable | notebook §9; live-run logs (locations in `PROVENANCE.md`) |
| L3 / L4 | **NOT CLAIMED** (they require a scored chain result) | — |

## Landed-boundary pins this pack maintains

The three pre-12d pins flipped exactly as designed when PR-12d landed
(3 failed / 10 passed on the integrated tree) and were RE-SCOPED to the
landed behaviour, each with a non-vacuity plant:

1. `model_plugins:` composes and `require:` refuses a missing type by name.
2. A composed `model_io:` task config composes (F-12d-4 fixed) and the
   model_io-vs-prose contradiction check is still alive.
3. Unknown SECTION keys refuse by name (`configs:` for `config:`), and the
   seam-A `config:` mapping demonstrably reaches the constructor.

A fourth pin was added by the 2026-08-25 live witness: the deliverable
codec accepts the composed inference child's POSITIONAL outputs paired
against `request.task_scope` (seam C/B7) and refuses a mis-paired length —
mutation-proven against the exact live failure
(`test_deliverable_codec_accepts_the_composed_childs_positional_outputs`).
