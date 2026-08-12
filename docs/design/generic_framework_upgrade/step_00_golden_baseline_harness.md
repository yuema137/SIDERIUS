# Step 00 — Golden Baseline Harness — detailed design

## Status

**IMPLEMENTED — PR OPEN, AWAITING CI + OPERATOR REVIEW — NOT
MERGED.** All six semantic commits (0A.1/0A.2/0B/0C/0D/0E + this 0F
closeout) landed on
`feat/generic-framework-step-00-golden-baseline-harness`; Checkpoint 0
MET (§20); zero production diff proven mechanically (no changed file
outside `tests/` and `docs/` across the whole branch).
Original authorization record: Design FROZEN at commit `0b92cd60`; the operator confirmed
the §22.1-22.3 audit results and issued the final OD-1..5 decisions
verbatim (all APPROVED: OD-1 ≤3-history capture + >3 deferral +
step-07a two-site predecessor, PYTHONHASHSEED rejected; OD-2 outcome A
corrected final form — `_emit_record` seam via RecordingSandbox,
pinned length-20 vector, no `_pseudo_origin`, no test-side
normalization, sub-fixtures schema-shape only; OD-3 numeric/mechanism
split, no committed HDF5, zero scorer change; OD-4 delete
`test_calculate_score_coarse`+`test_calculate_score_fine`, keep
`test_score_vector_legacy_mode_fine` as NUM-7, fix merge-gate wording,
retire FU-P2-4 xfail; OD-5 outcome A — test-only k9 assertion
migration, no print restoration, green before WF-4, STOP if the gate
no longer fires). Implementation branch:
`feat/generic-framework-step-00-golden-baseline-harness`, base =
frozen design commit `0b92cd60` (clean tree at branch creation).
The implementation PR is TEST-ONLY with ZERO production behavior
change. Adversarially reviewed 2026-08-11 (§23); operator-reconciled
2026-08-12 (§23a).

Created 2026-08-11 on branch `docs/generic-framework-step-00-design`
from a six-area parallel source/test audit (A prompts/LLM-boundary,
B config/dataset, C records/resume/plugins, D scorer/references,
E choreography/nondeterminism, F test/fixture/CI conventions), with
load-bearing claims re-verified in source by the main auditor.

## 0. Relationship to the frozen overall roadmap

This is the Step-00 detailed design required by the FROZEN roadmap
(`docs/design/siderius_generic_framework_upgrade.md`, operator approved
2026-08-11; O1 confirmed). Binding inheritances: no big-bang rewrite;
module-by-module migration; local config first; TIDMAD as the golden
compatibility profile with per-surface strongest criteria (roadmap §2);
no consumer-less seam; minimum sufficient evidence; Step 00 precedes
ANY production extraction; the six-checkpoint model (roadmap §17 —
Step 00 passes 0/D/E only); the §15.1 completion-contract matrix as
the single status authority. Step-00's frozen final effect:

> every behavior later extraction PRs claim to preserve has a
> trustworthy, reviewable baseline BEFORE production refactoring
> begins.

## 1. Objective and final effect

CAPTURE CURRENT TRUTH BEFORE EXTRACTION. Concretely: for each Stage-A
surface that roadmap steps 01-12 will claim parity against, Step 00
either (a) captures a new named baseline, (b) registers an existing
test as the baseline, or (c) records an explicit, justified deferral.
The §15 coverage manifest makes the mapping reviewable, so no later
module can claim parity against a baseline that was never captured.

## 2. Non-goals

Not a genericization implementation, second benchmark, cleanup PR,
scorer redesign, prompt refactor, config extraction, task-composition
implementation, whole-repository snapshot, or a device to freeze every
historical defect forever (defects are classified in §6 and NOT blessed
as permanent contracts). Zero production diff; no live LLM/API calls;
no model-output snapshots.

## 3. Audit record and recovery provenance

Six parallel read-only source/test audits were dispatched 2026-08-11 and
ALL SIX COMPLETED, but the designing session exhausted its context while
consolidating them (B, E, F and A were consolidated in-context only;
nothing past §2 of this document reached disk). A continuity-rescue
session (2026-08-11, same working tree, HEAD `66f19df3`) recovered all
six final audit reports verbatim from the session's durable subagent
transcripts (`~/.claude/projects/-home-yuema137-SIDERIUS/
f2a7ffe4-067a-4be6-b119-f8760e552061/subagents/`, agents:
A=`ab8d866ce632a706a`, B=`a4445ce6ca342b1f7`, C=`ac6f072c552406190`,
D=`a517260a23fe757f2`, E=`ac05154236a900013`, F=`a231866dc53a7a235`)
and synthesized the load-bearing findings into §§4-9 below.

Verification status per area (what the rescue session re-checked in
source, beyond trusting the recovered reports):

| Area | Status | Re-verified by rescue session |
|---|---|---|
| A prompts/LLM boundary | recovered + KEY CLAIMS RE-VERIFIED | API-boundary sites (`agent/llm_bridge.py:1328-1336`), `RecordingLLMBridge` plan/reflect raw-arg capture and missing `**kwargs` on `generate_text` (`tests/helpers/recording_llm_bridge.py:72,83,124,127`), frozenset-iteration sites (`agent/prompts.py:852,867,896,899,980`), and the cross-process nondeterminism EMPIRICALLY RE-CONFIRMED (3 fresh processes, 3 distinct key orders) |
| B config/dataset | recovered; spot-consistent with sources | (relied on report's in-source verification; no contradiction found) |
| C records/resume/plugins | recovered + spot-verified | duplicate `file_vector` declaration (`agent/schemas/hyperparam_tuning.py:385` and `:615`) confirmed |
| D scorer/numeric | recovered + spot-verified | the 5 CI scalar pins (`tests/unit/nodes/test_scoring_reference_default.py:29-38`), frozen raw filename literals (`execute_tools/scoring_utils.py:389,444`) confirmed |
| E choreography/nondeterminism | recovered; one claim CORRECTED (see §10.3) | reconciliation of its "no PYTHONHASHSEED exposure" claim against Audit A |
| F test/fixture/CI | recovered; spot-consistent with sources | (no contradiction found) |

The full raw reports remain recoverable from the subagent transcripts
named above; this document carries the synthesized, verified subset that
the design depends on.

## 4. Audit A — prompt / LLM boundary

### 4.1 The true deterministic boundary

The last deterministic point is the final `(system_prompt, user_prompt)`
string pair immediately before `client.chat.completions.create`. Three
literal call sites, all building the same 2-element message list:
`_chat_json` (`agent/llm_bridge.py:1327-1337`, adds
`response_format={"type":"json_object"}`), `generate_text`
(`:1507-1516`), `tool_call` (`:1571-1586`, adds `tools` +
`tool_choice="auto"`). No temperature / max_tokens / top_p / seed / stop
is ever set; no wrapping, no truncation, no cache mutation inside the
bridge; retries re-send the identical payload.

Because `generate` / `generate_text` / `tool_call` are byte-pass-through,
capturing at the public method entry is byte-identical to capturing at
the API call for those three. It is NOT equivalent for `plan()` and
`reflect()`, which render their prompts INSIDE the bridge
(`llm_bridge.py:864-919` planner, `:949-967` reflector).

### 4.2 Capture-layer defect (design-consequential)

`RecordingLLMBridge` (`tests/helpers/recording_llm_bridge.py`) records
`plan` as `("plan", memory_history, expert_advice, force_model,
recorded_kwargs)` (`:124`) and `reflect` as raw args (`:83`) — the
rendered prompt strings are never produced. Consequence: **zero exact
planner/reflector prompt-string coverage exists anywhere at the true API
boundary today.** Additional holes: `generate` drops `label`/`components`
(swallowed `**kwargs`, `:64-72`); `generate_text` has NO `**kwargs`
(`:127`) so a production-style `label=` call would `TypeError`;
no `set_run_context` method. The closest existing boundary recorder is
`scripts/render_proposer_prompts_for_audit.py:468-481` (class-level
patch capturing `(label, system, user)`).

**Fourth render-executing surface (adversarial review F3)**:
`StubLLMBridge` (`agent/llm_bridge.py:1657`) SUBCLASSES `LLMBridge` and
inherits `plan()`/`reflect()` unmodified — only
`_chat_json`/`generate_text`/`tool_call` are overridden (its own
docstring states this). Two consequences: (1) the production pseudo
path (`run_one_iteration.py` `--is_pseudo_llm` →
`bridge_factory = StubLLMBridge`) executes the REAL planner render,
so the §4.4 hash-seed exposure exists on that production path too
whenever history > 3; (2) the stub's `_chat_json` override RECEIVES
the final rendered `(system, user)` pair, making it a legitimate
low-cost capture vehicle for PB-1/PB-2 alongside the class-level-patch
pattern.

### 4.3 Prompt inventory and existing coverage

23 production prompt sites / 20 distinct labels (planner, reflector,
proposer legacy ×2 + pipeline ×5, implementor ×6, validator,
interpretation ×3, cache consolidator, lit review ×3 — full table with
producers and call sites in the recovered Area-A report). Exactly 4
exact-equality goldens exist
(`tests/unit/agent/{result_interpretation_agent,ml_model_proposal_agent}/goldens/`),
covering 3 of ~40 prompt strings; the proposer golden covers the LEGACY
path, which is NOT the production path under the standard workflow
(pipeline dispatch at `nodes/ml_model_proposal_agent/
ml_model_proposal_agent.py:1328-1334`; the workflow always builds a
2-stage pipeline, `workflows/model_exploration.py:215-223`). Zero
goldens for: pipeline proposer, planner, reflector, implementor,
validator, synthesis, dedup, consolidator, all three lit-review prompts.
All other prompt tests are substring/structural pins; no pin anywhere
asserts on `label=`/`components=` crossing `generate()`.

### 4.4 Nondeterminism (empirically confirmed twice)

`agent/prompts.py:896` and `:899` build dict entries by iterating
frozensets (`_CONDENSED_KEYS` `:852`, `_CONDENSED_MEMORY_KEYS` `:867`)
whose key order feeds `json.dumps(windowed, indent=2)` at `:980` — the
planner user prompt's condensed-history block. Frozenset iteration order
depends on PYTHONHASHSEED, so **the `tuner.planner` user prompt is not
byte-stable across processes whenever `len(memory_history) > 3`** (the
`full_window` cutoff at `:878,890`). Stable within one process.
Empirically confirmed by the original audit (5 processes, 5 orders) and
re-confirmed by the rescue session (3 processes, 3 orders). These are
the only set-iteration-into-output sites found across the prompt-render
modules; all other set usages are membership-only or `sorted()`.
Disposition: CLOSED as OD-1 (§22) — ≤3-record fixture now; two-site
ordering fix as the step-07a predecessor.

Environment/filesystem couplings that a planner/proposer golden must pin
(deterministic given a pinned environment, not given a fixture alone):
`agent_generated/losses/*.py` existence, live `MODEL_REGISTRY`,
`_capability_index.json` + `created_at` sort, model source read from
disk, `inspect.getsource(config_cls)`, live output-type registries
(which can RAISE during prompt construction,
`agent/prompts.py:1018,1032`), an absolute workspace path embedded in
the synthesis prompt (`result_interpretation_agent.py:641-645`). No
time/random/uuid in any prompt render.

### 4.5 Feasibility verdict (from the audit, adopted as design input)

Exact equality feasible today given fixtures: reflector, legacy
proposer ×2, implementor ×6, validator, per-model interp, dedup,
consolidator, lit review ×3. Feasible with a pinned workspace path:
synthesis. Feasible with pinned registry + pinned `agent_generated/`
tree + `MODEL_REGISTRY` stub: pipeline proposer ×5. Requires resolving
§11.1 (plus pinned registry/plugin tree): planner.

## 5. Audit B — config / task / dataset baselines

- `workflows/task_config.py` returns a plain mutable CACHED dict
  (`:44,103-104,144-146`); the validated `ForwardContract` instance is
  discarded (`:142`); `task_description` is stripped by the loader while
  the three note fields keep trailing `\n` and are stripped only in the
  renderer (`:201-205`). Default config path is CWD-RELATIVE (`:39,101`)
  while the provenance snapshot helper anchors on `SIDERIUS_ROOT` — the
  two disagree when cwd ≠ repo root.
- The shipped rendered `{FORWARD_CONTRACT}` block (sha256[:16]
  `ed34ede6803eb6f8`) is pinned by NOTHING: renderer tests use a
  synthetic contract that differs from the shipped file; the
  committed-config test asserts only `task_description` truthy +
  `num_classes == 256`. A deep-equal baseline needs BOTH the resolved
  dict and the two rendered strings (the strip asymmetry lives in the
  renderer).
- TIDMAD `DatasetConfig` (`execute_tools/dataset_config.py:292-299`):
  `SEGMENT_LENGTH/SEGMENTS_PER_FILE/NUM_FILES` are pinned;
  `sampling_frequency`, `validation_file_pattern`, and the exact
  36-element `valid_segmentation_sizes()` list are UNPINNED.
- SampleSet sha16 goldens
  (`tests/unit/execute_tools/test_sample_set_builder.py:239-249`)
  reproduce exactly today; they bind to CPython's `random.sample`
  implementation, cover 3 trial strategies at one (seed, portion), full
  scope only; normal mode and partial scope have no digest.
- `data_shape_class` current value `psd10000000_seg200_files20`
  (`execute_tools/data_paths.py:89-97`); the format is pinned by no
  assertion (appears only as a fixture literal).
- Health checks: the two shipped-config LEGACY body sha256s (gate_role
  stripped) are pinned (`tests/unit/execute_tools/health_checks/
  test_honest_gate_labels.py:183-192`) and reproduce; the CURRENT
  (gate_role-included) body shas are pinned nowhere. Thresholds 25 /
  [3,10,17] pinned indirectly; `min_std_mv 1.0` only as a drift-test
  literal; `0.95` and the `peek_samples` values unpinned.
- `configs/lit_review_config.yaml:48-52` duplicates
  `configs/task_config.yaml`'s `task_description` byte-identically on a
  SEPARATE load path that never touches `task_config.py`
  (`workflows/model_exploration.py:2134-2142,575-638`); no test compares
  the two files — silent drift is possible.
- Environment state that must be EXCLUDED from task-semantic goldens:
  `tidmad_data_config.yaml` (gitignored; import-time fallback to the
  EXAMPLE template with a UserWarning, `data_paths.py:24-40`, untested),
  hardware manifests, all runtime-control environment identities,
  workspace paths, materialized `health_checks_effective.yaml`, and the
  environment-derived fields of `ResolvedMeasurementCapability` (only
  `task_identity`/`dataset_adapter`/`data_shape_class` are
  task-semantic).

## 6. Audit C — records / resume / plugins

- `ExperimentRecord` (`agent/schemas/hyperparam_tuning.py:294`): 54
  fields via 55 declarations — **`file_vector` is declared TWICE
  (`:385` and `:615`; Pydantic keeps the last; nothing pins this)** —
  verified by the rescue session. The key-set pin suite DELIBERATELY
  exempts `ExperimentRecord` and `HyperparamTuningInput`
  (`tests/unit/agent/schemas/test_pr_e_stage_contract_pins.py:16-21`;
  its "53 fields" docstring is already stale).
- Volatile fields (byte-replay impossible): `timestamp` (7 production
  sites), `exp_id` (embeds run_name; stable FORMAT
  `{model}_{run}_{NNN}` — format asserted nowhere), all `timing.*`,
  measured `memory.*` fields, LLM free text, `gpu_evidence` (PIDs +
  wall-clock + GPU UUID), `health_gate_results[].metrics.per_file[]
  .file.path` (ABSOLUTE paths — 21 in one real record).
- Load-bearing consumption: `core/resume.py` reads
  `exp_id, denoising_score, is_trial, logical_round,
  health_gate_enabled, health_gate_results, model_type, eval_strategy,
  eval_portion, train_portion, scientific_authority` — PLUS `status`,
  read indirectly through `classify_candidate_health`
  (`execute_tools/health_checks/candidate_eligibility.py:161` —
  `status != "success"` → INVALID; a status-vocabulary change flips
  every candidate; adversarial review F4). The TUNER additionally
  reads record fields back into the planner prompt:
  `memory.vram_estimate_gb`, `memory.time_estimate_minutes`,
  `memory.time_mode`, `params.train_config.batch_size`
  (`ml_hyperparameter_tune_agent.py:4132-4137`); `per_file_best.py`
  copies `timestamp` into its emitted artifact (`:330,352` —
  pass-through, value never decided on). The interpreter and funnel
  consumption sets are enumerated in the recovered Area-C report.
- **No serialized-record golden exists anywhere**; every record in
  tests is an inline Python dict. Committed real-capture precedent
  exists (`tests/fixtures/c2_lite_*.json` with hostnames/PIDs/foreign
  absolute paths).
- Record-fixture source options (measured): pseudo-mode k9 emits all
  54 keys, a real `score_table` from committed `reference_data/`, zero
  absolute paths, ~14.8 KB/record — but structurally cannot populate
  `health_gate_results` / `gpu_evidence` / `failure_attribution`; the
  newest real production record (`.gate_artifacts/pr_g_gate_20260810_r2/`)
  validates against the current schema, costs ~70 KB (75% =
  `health_gate_results`), embeds 21 `/home/yuema137/` paths; the only
  real success record with a populated `score_table` in
  `siderius_workspace/` FAILS the current schema
  (`headroom_vs_gt >= 0`, `agent/schemas/score_table.py:67-69`) —
  a known defect that must NOT be blessed (§2). Fixture-source choice
CLOSED as OD-2 outcome A (§22.1).
- Resume replay: `RestoredState` (13 fields) reconstructed from
  `iter_NNN/manifest.json` (+ sha256 integrity), run_output,
  `plugins/iter_NNN/*.py`, interpretation digest, proposal JSON,
  `run_invariants_lock.json`. Minimal committed replay workspace =
  2 mandatory files (manifest + valid run_output) + 5 independently
  degradable optional ones. Today NO test uses a committed on-disk
  workspace fixture (all synthesized under `tmp_path`).
- Plugins: contract + loader semantics in
  `ml_models/plugin_loader.py` (returns None, never raises; later dir
  shadows earlier; `sorted(os.listdir)`). Exactly two committed plugin
  files exist (`tests/pseudo_data/plugins/pe_wavenet_delta.py`,
  `agent_generated/_stub_plugin_template.py`); `agent_generated/models/*`
  is gitignored, so a prior-plugin loadability baseline must copy
  content into `tests/`. **No test loads a committed real generated
  plugin from disk.**
- Pseudo/production record parity (CORRECTED by adversarial review
  F2): the VALIDATED key sets are identical (54), but the ON-DISK
  pseudo record has **55 keys** — `StubSandbox.save_record` stamps
  `_pseudo_origin="stub_sandbox"` BEFORE the raw-dict json-dump
  (`core/sandbox_executor.py:2095-2097`), and the stub's
  `score_vector` emits a **length-9** `file_vector`
  (`:2080`) where production emits 20. Value-level pseudo gaps:
  `health_gate_results=[]`, `gpu_evidence=null`,
  `failure_attribution=null`. ANY pseudo-derived fixture must
  therefore be normalized to production shape (strip
  `_pseudo_origin`; replace `file_vector` with a typed length-20
  value) with each normalization recorded in the fixture provenance —
  see OD-2.

## 7. Audit D — scorer / numeric baselines

- CI numeric surface: the ONLY CI pins on real committed reference
  values are 5 scalars at tolerance 1e-3
  (`tests/unit/nodes/test_scoring_reference_default.py:29-38`) —
  `s_max=295715680.14248306`, raw/gt file-0 logs, raw/gt full scalars.
  On-disk values carry ~4 more significant digits than the pins
  protect. CI (`.github/workflows/ci.yml`) runs `tests/unit/` only.
- Real-run-only evidence: `tests/integration/scoring/
  test_legacy_parity.py` (1e-10) is STALE — two of its three tests call
  `_calculate_score` without the now-required `s_max` and would
  `TypeError` even on the data machine; the cited alignment doc
  `docs/align_denoising_score.md` DOES NOT EXIST.
  `test_anchor_map_consistency.py` reads the DATA-DIR anchor map, not
  the committed one (out-of-band: they are byte-identical today;
  asserted nowhere).
- `score_vector` facts for a replay: it accepts but NEVER reads
  `anchor_map` in its body; requires `s_max` (any float) in non-legacy
  mode; the RAW filename is frozen to `abra_validation_{i:04d}.h5`
  (`scoring_utils.py:389,444` — verified) while the denoised filename
  is caller-supplied. `score_vector(legacy_mode=False)` — the
  production path — has NO test anywhere, real or synthetic;
  `get_one_sec_psd`/`find_peak` are mocked everywhere off `real_run`;
  the `parallel=True` spawn path is untested; `StubSandbox.score_vector`
  returns a random length-9 vector (violating the length-20 contract).
- Fixture arithmetic (measured): every scored segment needs ≥10 M
  samples; minimal 1-file/1-segment HDF5 fixture = 20 MB uncompressed
  (~10-13 MB gzipped; current git pack is 12.1 MiB; zero .h5 tracked;
  no size policy exists). Alternative: monkeypatching `SEGMENT_LENGTH`
  shrinks the fixture arbitrarily but changes the frequency grid
  (Nyquist literal `5*1e6` at `scoring_utils.py:179` does not track
  `sampling_frequency`) — validity is §11.3. A raw fixture must carry a
  `channel0001` attrs group even when only CH2 is scored; int16 CH2
  would silently mis-scale (int8 range assumed at `:164`).
- Out-of-band arithmetic verified by the audit (asserted NOWHERE in
  repo, all additive candidates): all 40 per-file JSONs satisfy
  `score == log_5.27(linear_sum/n_segments)` exactly; the committed
  ground-truth set is EXACTLY reproducible from the committed anchor
  map; the raw scalar reproduces exactly; the FU-P2-4 xfail refers to a
  stale `/home/klz` copy — the COMMITTED reference_data already
  satisfies it (the xfail is stale).
- What Step 00 may add without touching the frozen scorer (from the
  audit's gap list): full-precision pins on all 40 per-file scores +
  both scalars; anchor-map value/shape/digest pins; the two
  pure-arithmetic reproducibility assertions above; the
  three-expressions-of-log-base cross-module identity; a CI-runnable
  `legacy_mode=False` replay (per §11.3's resolution); repair-or-delete
  decision on the stale legacy-parity test.
- Float determinism: numpy pinned at 2.4.3 by `uv.lock` + `uv sync
  --frozen` in CI; `pyproject.toml` has no upper bound; the float64
  upcast before `rfft` and time-domain scaling order are load-bearing
  (`scoring_utils.py:44-51,164-177`); NO cross-platform/cross-version
  FFT bit-stability evidence exists in the repo.

## 8. Audit E — choreography / nondeterminism

- k9 + l_fail (`tests/integration/workflows/test_k9_invented_model_
  dual_mode.py`, `test_l_fail_round_abort_dual_mode.py`) are the only
  end-to-end round/attempt state-machine choreographies through the
  production tuner; the roadmap already names them as the Stage-A
  choreography baseline. Pinned vs unpinned transitions are enumerated
  in the recovered Area-E report; notable UNPINNED: `consecutive_fails`
  reset across a formal round, mid-round resume
  (`attempt_in_round > 1`), executed `SKIP_TO_FORMAL`
  `completed_rounds` jump, `exp_id` numbering across resume, all
  time-gate transitions (both choreographies disable time budgets), and
  gate-enabled round transitions (both set `health_gate_enabled=False`
  — the M9 pseudo-gate gap: the pseudo stack writes no denoised HDF5s).
  k9 currently FAILS at HEAD on `assert "Feasible" in stdout` —
  pre-existing, proven at base (commit `844a329f`).
- Type-5 "same kwargs reach LLMBridge" feasibility: `plan()` has 25
  parameters excl. `self` (CORRECTED by review F11: the audit said
  24; the call site passes `memory_history` POSITIONALLY plus 24 by
  keyword), all passed explicitly by the sole production call site
  (`ml_hyperparameter_tune_agent.py:4162-4197`);
  `RecordingLLMBridge.plan` captures the full kwarg surface
  transitively, but only ONE test asserts on any of it (k9, 3 keys);
  `label`/`components` are structurally uncapturable today (§4.2);
  `registry` is a live object and `memory_history` is stored by
  reference — a naive deep-equal kwargs golden cannot serialize them.
  Five test files use ad-hoc bridges with a DIFFERENT tuple shape.
- Protocols: 12/12 functions have output-mapping tests; two named
  nondeterminism entries (`recent_gate_exhaustions` order contract is
  pinned; `candidate_id` is uuid4-minted and behaviourally inert by
  test).
- Pseudo-vs-real sandbox shape divergences (three doubles disagree):
  `runtime_verification` (production/Stub have it, pseudo JSON lacks
  it), inference `results` key (pseudo invents it, production omits),
  `execute_scoring` merged keys + Stub's injected
  `is_degenerate`/`failure_reason`, `_pseudo_origin` stamp
  (Stub-only), DataScope validation (absent from RecordingSandbox).
  Pseudo-fixture fidelity is DECLARED unenforced by design
  (`tests/pseudo_data/README.md:19-24,48-56`).
- Enumerated nondeterminism on the pseudo iteration path: wall-clock
  timestamps (7 tuner sites + workflow + chain-runner), measured
  `*_time_s` timings, `uuid.uuid4()` (candidate_id, request_id,
  calibration ids), `datetime.now(UTC)` (invariants, campaign,
  probe, provenance), host/GPU environment (VRAM probes — the
  hand-calibrated `trial_vram_budget_gb=0.3` ceilings are
  machine-dependent), live-object kwargs. Deterministic: fixture load
  order, plugin scan order, `exp_id` composition, stub RNG (string-
  seeded), tuner set→list conversions (all `sorted`), dict insertion
  order.

## 9. Audit F — test / fixture / CI conventions

- Golden conventions today: 4 `.txt` goldens, layout
  `tests/unit/agent/<pkg>/goldens/<surface>_<scenario>.txt`, bare
  `assert rendered == GOLDEN.read_text()` (no `encoding=`, no diff
  helper); TWO goldens lack a trailing newline and nothing protects
  that byte (no .gitattributes/pre-commit). Provenance lives in test
  docstrings and capture commits (`23c3fbe5`, `66efed87`), and is
  ALREADY STALE once: `a5a2d9de` regenerated the proposer golden but
  the docstring still names `2052fa2`.
- **No regeneration mechanism exists**: no script, no
  `--update-goldens`, no snapshot library (dev deps are exactly
  pyright/pytest/ruff), no documented procedure, and no rule forbidding
  silent regeneration. Step 00 must DEFINE the convention; precedents
  to mirror: test-only capture commits + the `SOURCE_COMMITS` stamp in
  `scripts/render_proposer_prompts_for_audit.py:66-73`.
- CI: single job, `timeout-minutes: 15`, runs ruff ×2 + pyright strict
  + `pytest tests/unit/ -m "not real_run" -q`; 8,281 unit tests
  collected, ~440 s recorded wall time — a new baseline family that
  must stay in CI has to be plain-unit, offline, and O(seconds).
  `tests/integration/` (incl. all `dual_mode`) NEVER runs in CI.
  `dual_mode` is registered in `tests/conftest.py:97-103`, not
  `pyproject.toml` — a vocabulary split not to replicate.
- Fixture hygiene: zero binary fixtures tracked (no .h5/.npy/.pth);
  `*.h5` is NOT gitignored; the de-facto size policy is an incident
  docstring in `tests/unit/test_repo_hygiene.py`, not a numeric limit.
  Portability rules (CLAUDE.md) bind all new fixture paths.
- Determinism conventions: explicit per-call seeds (no global seeding,
  no pytest-randomly); `RealSubprocessEscape` autouse guard; NO network
  isolation of any kind (the only real-API protection is the `real_run`
  collection hook + per-test mocking).
- `docs/pseudo_test_infra.md` DOES NOT EXIST despite being cited as
  the authority at 5+ sites (`tests/conftest.py:65,75,94,107`,
  `tests/helpers/recording_llm_bridge.py:6`,
  `tests/pseudo_data/README.md:10-11`).

## 10. Corrected premises (cross-audit reconciliation)

### 10.1 Planner/reflector capture layer

Previous assumption: existing tests capture prompts at the LLM
boundary, so planner/reflector prompt equality can be asserted through
`RecordingLLMBridge`.
Audit evidence: `plan()`/`reflect()` render INSIDE `LLMBridge`
(`agent/llm_bridge.py:864-919,949-967`); `RecordingLLMBridge` records
raw arguments pre-render (`tests/helpers/recording_llm_bridge.py:83,124`)
— re-verified in source by the rescue session.
Corrected understanding: for planner/reflector, public-method capture
is the WRONG layer; only a boundary recorder at (or equivalent to) the
final `(system, user)` pair gives exact-prompt coverage.
Design consequence: the Step-00 capture mechanism for planner/reflector
must hook the render output (e.g. class-level patch as in
`render_proposer_prompts_for_audit.py`) or the bridge internals — not
`RecordingLLMBridge.calls` as it exists.
Validation consequence: any claimed planner/reflector prompt baseline
must be shown to fail when the RENDER changes, not merely when the
arguments change.

### 10.2 Planner prompt byte-stability

Previous assumption: prompt rendering is deterministic given fixed
inputs, so exact goldens are directly capturable.
Audit evidence: frozenset-iteration dict construction feeds
`json.dumps` (`agent/prompts.py:896,899,980`); empirically byte-unstable
across processes when `len(memory_history) > 3` — confirmed twice
(original audit ×5 processes; rescue ×3).
Corrected understanding: the planner user prompt is the ONE prompt
surface with real cross-process nondeterminism; everything else is
deterministic given pinned fixtures/environment/registry.
Design consequence: the planner baseline requires an explicit
disposition decision (§11.1) before capture.
Validation consequence: a planner golden captured without resolving
§11.1 would be flaky-by-construction in CI.

### 10.3 Audit E's "no PYTHONHASHSEED exposure" claim (scope correction)

Previous claim (Area E): "no PYTHONHASHSEED exposure found on the
pseudo path".
Audit evidence: Area A's confirmed sites live in the PLANNER RENDER
(`agent/prompts.py:896,899`), which the pseudo path never executes —
`RecordingLLMBridge.plan` returns canned output without rendering.
Corrected understanding: both findings are true at their own layers,
but the "pseudo path bypasses the render" claim holds ONLY for
`RecordingLLMBridge` (canned `plan()` override). `StubLLMBridge`
inherits the real `plan()`/`reflect()` (§4.2) — so the k9/l_fail
choreographies (RecordingLLMBridge) are hash-seed-clean, while the
`--is_pseudo_llm` production path and any `StubLLMBridge`-based test
execute the real render and ARE exposed (adversarial review F3). E's
grep pattern (`for x in set(...)`) also could not see A's
dict-comprehension form.
Design consequence: RecordingLLMBridge-based choreography goldens are
safe as-is; any baseline that executes the real `LLMBridge.plan`
render — including via `StubLLMBridge` — inherits §11.1.
Validation consequence: "pseudo suite green" is not evidence of planner
prompt byte-stability.

### 10.4 Existing proposer golden vs the production path

Previous assumption: the existing proposer prompt golden protects the
production proposer.
Audit evidence: the only proposer golden covers the LEGACY reasoning
path; the standard workflow always takes the 2-stage PIPELINE path
(`workflows/model_exploration.py:215-223`,
`ml_model_proposal_agent.py:1328-1334`). Whether ANY shipped config
reaches the legacy path is UNKNOWN (Area A UNKNOWN-1).
Corrected understanding: the production proposer prompt surface (5
pipeline sites) has zero exact coverage.
Design consequence: the pipeline proposer is a first-class capture
target for Step 00; the legacy golden's disposition (keep/annotate)
is part of the baseline inventory.
Validation consequence: pipeline-proposer goldens must be captured
under a pinned registry + pinned `agent_generated/` tree +
`MODEL_REGISTRY` stub (§4.5).

## 11. Genuine open design/policy questions

HISTORICAL (kept as the audit-time statement of the questions): each
was carried to §22 as OD-1..OD-5 (item 1 → OD-1, 2 → OD-2, 3 → OD-3,
4 → OD-4, 5 → OD-5). **All five are now CLOSED** — OD-1/OD-3 by
direct operator approval (2026-08-12), OD-2/OD-4/OD-5 by the
operator-directed narrow source audits recorded in §22.1-22.3.

1. **Planner-history nondeterminism disposition** (§4.4, §10.2). A
   genuine choice remains among: (a) FIXTURE CONSTRAINT — capture the
   planner golden with ≤3 history records so the condensed branch never
   runs (cheap; leaves the >3-record branch — the interesting one —
   uncovered); (b) HARNESS PIN — run the capture/assert under
   `PYTHONHASHSEED=0` (covers the branch; bakes a hash-seed-dependent
   byte order into a golden; CI must then pin the env var for that
   test); (c) PREDECESSOR CORRECTION — a one-line deterministic
   ordering fix (e.g. sorted iteration) in `agent/prompts.py` as a
   separate operator-approved production PR BEFORE Step-00 capture
   (cleanest baseline; violates Step-00's zero-production-diff rule
   unless sequenced as its own predecessor hotfix; changes rendered
   bytes for >3-record histories, i.e. it is itself a
   behavior-affecting change to the surface being frozen); or (d) defer
   exact planner coverage from Step 00 with a justified deferral
   (§1(c)). NOT silently decided here.
2. **Record-fixture source policy** (§6): pseudo-k9-derived record
   (54 keys, path-free, 3 structurally-empty fields) vs real production
   record (complete but ~70 KB with 21 absolute paths needing
   scrubbing/masking policy) vs a fresh bounded real capture. Also
   whether the schema-invalid historical record (`headroom_vs_gt < 0`)
   is documented as a known defect only.
3. **Scorer replay fixture policy** (§7): commit a ~20 MB HDF5 fixture
   (no size policy exists; triples the pack) vs a
   `SEGMENT_LENGTH`-monkeypatched shrunken replay (changes the
   frequency grid and every SNR — is that a valid baseline of the
   FROZEN scorer?) vs arithmetic-only pins (no `legacy_mode=False`
   execution coverage). Interacts with the frozen-scorer rule: the
   Nyquist literal `5*1e6` at `scoring_utils.py:179` must not be
   "fixed" to enable a fixture.
4. **Stale legacy-parity test disposition** (§7): repair the two
   signature-broken `_calculate_score` calls, or delete tests 1-2 and
   keep test 3 — a test-only change, but it alters the documented
   "canonical merge gate", so it needs an explicit design statement.
5. **Baseline for the k9 pre-existing failure**: k9 fails at HEAD
   (`assert "Feasible" in stdout`, proven pre-existing at base). Step
   00 must either register k9 as-is with the failure documented, or
   the failure is fixed first (production print relocation — out of
   Step-00 scope). Not blessing the failure as a golden (§2).

## 12. Baseline taxonomy and selection rules

Six baseline types. Every inventory entry (§13) declares exactly one
primary type; the type fixes the comparison criterion and the
regeneration semantics (§17).

| Type | Name | Criterion | Regeneration trigger |
|---|---|---|---|
| 1 | Exact golden | byte equality of a committed text artifact (incl. whitespace, ordering, trailing newline) | only an intentional change to the producing surface |
| 2 | Deep-equal object | structural equality of a serialized object against a committed JSON/derived expectation, after a JUSTIFIED volatile-field exclusion list | intentional semantic change |
| 3 | Schema key-set pin | exact (ordered, where meaningful) key/field list of a schema or serialized artifact | intentional schema change |
| 4 | Numeric pin | full-precision (repr-exact or ≤1e-12) equality of committed reference numbers | intentional recomputation of the reference artifacts |
| 5 | Boundary-capture invariant | what crosses a production boundary (kwargs, labels, choreography transitions, mechanism behavior) is captured and compared; values may be synthetic | intentional boundary change |
| 6 | Operational replay | a committed on-disk artifact set is consumed by the real production loader/loader-chain and the reconstructed state matches a pinned projection | intentional loader/layout change |

Selection rules:

1. **Strongest applicable criterion** (roadmap §2): prefer Type 1 where
   the surface is a deterministic string; degrade to Type 2/3 only with
   a recorded reason (nondeterminism, volatile content, live objects).
2. **Small, named, reviewable artifacts** — never one monolithic
   snapshot. Each baseline is separately diffable and separately
   updatable.
3. **Production path only**: a baseline captures the output of the real
   production producer (real render path, real loader, real schema),
   never a test-side re-assembly. Deleting or renaming the producer
   must break the baseline test (import/call failure), so a baseline
   can never stay green against dead production code. **Labeled
   exemption (review F8)**: Type-4 ARTIFACT-CONSISTENCY pins that
   assert internal consistency of committed reference artifacts may
   compute expected values arithmetically, but MUST route every
   formula that has a production implementation through that
   implementation (e.g. the log-base helpers) so the pin still breaks
   with the producer; pure test-side formula duplication is forbidden.
4. **No consumer-less baseline**: every baseline names the roadmap
   step(s) that will consume it in a Stage-A parity claim (§15). A
   baseline no step consumes is not captured.
5. **Volatile exclusions are justified by enumeration, not
   convenience**: every excluded field appears in the audited
   nondeterminism enumerations (§6, §8) and the exclusion must be
   shown unable to hide a compatibility break (the remaining compared
   surface still pins the semantics).

### 12.1 What must NOT be goldened (binding exclusion classes)

1. **Volatile environment state**: timestamps, PIDs, hostnames, GPU/
   driver/torch identities, measured durations, VRAM probes, absolute
   workspace/data paths, `tidmad_data_config.yaml`-derived values,
   hardware manifests (§5, §6, §8 enumerations).
2. **LLM output**: no live API calls; no model-output snapshots.
   Pseudo-mode canned responses are test INPUTS, not baselines.
3. **Known defects**: classified and registered (§13.8), never blessed
   as permanent contracts — the duplicate `file_vector` declaration,
   the frozenset render nondeterminism, the schema-invalid historical
   record, the k9 pre-existing failure, the stale legacy-parity calls,
   the pseudo/production sandbox-shape divergences, the
   `RecordingLLMBridge` capture holes.
4. **Whole-file/workspace dumps** whose bulk is volatile (e.g. a full
   real production record with 21 absolute paths): pin a projection,
   not the blob.
5. **Machine-calibrated tuning values inside choreography fixtures**
   (e.g. `trial_vram_budget_gb=0.3` ceilings): accepted as fixture
   inputs, never asserted as contracts.
6. **MIGRATION PARITY surfaces are labeled as such** — a baseline that
   pins a TIDMAD-era accident (duplicated `task_description`,
   absolute-path embedding in the synthesis prompt, the raw
   `abra_validation_{i:04d}.h5` filename literal) carries the label
   `MIGRATION PARITY — NOT FINAL FRAMEWORK CONTRACT`: it exists to
   catch silent drift DURING migration and is expected to be retired
   or replaced by the owning module's Stage-B design.

## 13. Baseline inventory

**IMPLEMENTATION RECONCILIATION (0F, 2026-08-12): every row below is
LANDED.** Test-file map: PB → `tests/unit/agent/{llm_bridge,
ml_model_proposal_agent,ml_model_implementor,ml_code_validator_agent,
result_interpretation_agent,ml_literature_review}/
test_step00_prompt_goldens.py` (44 goldens); CFG/DS/HC/TC →
`tests/unit/workflows/test_step00_task_config_baselines.py`,
`tests/unit/execute_tools/test_step00_dataset_baselines.py`,
`.../health_checks/test_step00_health_config_baseline.py`,
`test_sample_set_builder.py` (STR); REC/RES/PLG →
`tests/unit/agent/tune_ml_hyperparam_agent/
test_step00_record_baselines.py`, `tests/unit/core/
test_step00_resume_replay.py` (+ committed workspace fixture),
`tests/unit/ml_models/test_step00_prior_plugin_loadability.py`
(+ byte-identical `.py.txt` plugin); NUM →
`tests/unit/execute_tools/test_step00_numeric_baselines.py` +
`tests/unit/nodes/test_scoring_reference_default.py` (STR) +
retired-xfail replacement in `test_scoring_helpers.py` + OD-4-scoped
`tests/integration/scoring/test_legacy_parity.py`; WF →
`tests/unit/agent/tune_ml_hyperparam_agent/
test_step00_choreography_baselines.py` + the OD-5-migrated k9.
Shared infrastructure: `tests/helpers/{golden,llm_boundary_recorder,
step00_pseudo_iteration}.py` + the widened `recording_llm_bridge.py`.
71 committed golden/fixture files, all text, total well under 1 MB.
Per-commit evidence lives in the §18 checklists; deferrals in §15.2.

Legend — Status: NEW (captured by Step 00), REG (existing test
registered as the baseline, unchanged), STR (existing test
strengthened). Deferrals are not inventory rows — they live in §15.2.
Producers/consumers, fixtures, exclusions and hazards are per-family
(§§13.1-13.7); global location/update rules are §16/§17. All NEW/STR
tests are plain-unit CI tier unless marked. REG rows marked "verify
strength" require the implementation to READ the registered test and
strengthen it to the stated criterion if weaker — recorded per §18's
inspect-first rule.

| ID | Surface | Type | Status | Criterion / artifact |
|---|---|---|---|---|
| PB-0 | 4 existing prompt goldens (legacy proposer reasoning, interp per-model ×2 + system) | 1 | REG | kept byte-identical |
| PB-1 | planner (system + user) at the true render boundary | 1 | NEW | ≤3-record fixture variant; `force_model` variant; >3-record condensed branch DEFERRED (§11.1 / OD-1) |
| PB-2 | reflector (system + user) | 1 | NEW | real bridge render |
| PB-3 | proposer PIPELINE stages ×5 (comparison, causal, proposing; explore + exploit blocks) | 1 | NEW | pinned registry + pinned `agent_generated/` view + `MODEL_REGISTRY` stub |
| PB-4 | proposer legacy commit prompt | 1 | NEW | plain string + user render |
| PB-5 | implementor prompts ×6 (model/loss × reasoning/code/repair) | 1 | NEW | |
| PB-6 | validator code_review (system + user) | 1 | NEW | |
| PB-7 | interpreter synthesis + dedup + per-model flag-ON variant | 1 | NEW | workspace path pinned by fixture; path embedding labeled MIGRATION PARITY |
| PB-8 | cache-consolidator list_merge | 1 | NEW | |
| PB-9 | lit-review paper_extract / search_decision / synthesis, minimal branch variants | 1 | NEW | per audit-A branch map, not a combinatorial matrix |
| CFG-1 | resolved shipped task-config dict (`load_task_config()`) | 2 | NEW | deep-equal incl. stripped description |
| CFG-2 | the two rendered task strings (`get_task_description`, `render_forward_contract`) for the SHIPPED file | 1 | NEW | current sha256[:16] `ed34ede6803eb6f8` |
| CFG-3a | lit-review config task_description byte-equals task_config's | 1 | NEW | MIGRATION PARITY (duplication collapses at step 04) |
| CFG-3b | lit-review config's own task-semantic fields | 2 | NEW | root paper, dynamic_search, verbosity, rubric bands — pinned by nothing today |
| TC-1 | resolved trial/formal `TrialConfig` JSON for pinned planner inputs | 2 | NEW | roadmap step-05a A-surface ("trial_config JSON deep-equal"); producer = the tuner's trial-decision resolution into `TrialConfig` (`agent/schemas/hyperparam_tuning.py`) |
| DS-1 | TIDMAD `DatasetConfig`: all six fields + exact 36-entry `valid_segmentation_sizes()` + filename renders + full-scope resolve | 2 | NEW+REG | existing partial pins registered |
| DS-2 | `data_shape_class` exact string `psd10000000_seg200_files20` + `MeasurementIdentity.components()` order | 2 | NEW | steps 02/07b key stability |
| DS-3 | SampleSet sha16 selection digests | 4 | REG+STR | existing 3 digests registered; ADD one normal-mode + one partial-scope digest |
| HC-1 | shipped `health_checks.yaml` resolved config | 2 | NEW | deep-equal of `load_health_gates_config().model_dump(mode="json")`; values MIGRATION PARITY, mechanism REQUIRED |
| REC-1 | `ExperimentRecord` + `HyperparamTuningOutput` ordered full field lists | 3 | NEW | closes the deliberate key-set-pin exemption for migration purposes; duplicate `file_vector` registered as defect |
| REC-2 | canonical record deep-equal projection (load-bearing subset incl. resume-consumed fields + `status` + tuner-read fields) | 2 | NEW | fixture captured from a RecordingSandbox pseudo iteration at the `_emit_record` seam with a length-20 fixture vector (§22.1 outcome A); typed-schema gate/gpu sub-fixtures pin shapes only; StubSandbox NEVER a source |
| REC-3 | artifact key sets: manifest.json (3 status branches), run_output (46), interpretation (35), summary shape | 3 | NEW | producers §6/audit-C |
| REC-4 | `exp_id` format `{model}_{run}_{NNN}` at BOTH production sites | 5 | NEW | pins `:4089` and `:4440` render identically; the `:03d` padding is SEMANTIC — `core/resume.py:438-441` breaks score ties lexicographically on `exp_id` (review F12) |
| RES-1 | resume replay from a COMMITTED minimal workspace fixture → `RestoredState` projection | 6 | NEW | 2 mandatory + degradable optional files; exercises the real `restore_prior_state` |
| RES-2 | replay integrity (tamper → `ReplayIntegrityError`) | 6 | REG | `test_resume_incumbent.py:428` |
| RES-3 | existing resume/cold-start/fingerprint suites | 6 | REG | registered as the behavioral floor |
| PLG-1 | committed real generated plugin loads via `_load_plugin` → registries → forward contract `[B,T]→[B,256,T]` on tiny CPU tensor | 6 | NEW | plugin copied into `tests/` (gitignore precedent) |
| PLG-2 | plugin loader semantics suite | 6 | REG | `test_plugin_loader.py` |
| NUM-1 | ALL 40 per-file reference scores + both scalars + `s_max` at full precision | 4 | STR | replaces the 5-value/1e-3 surface with repr-exact pins |
| NUM-2 | committed anchor map: `s_max` exact, 20×200 shape, canonical-JSON sha256 | 4 | NEW | today only key-existence is checked |
| NUM-3 | ground-truth set exactly reproducible from committed anchor map (pure arithmetic) | 4 | NEW | holds exactly today, asserted nowhere |
| NUM-4 | `score == log_5.27(linear_sum/n_segments)` across all 40 per-file JSONs | 4 | NEW | |
| NUM-5 | log-base cross-module identity (scoring_utils inline ≡ scoring_helpers ≡ `per_file_best._log`) | 4 | NEW | bit-equal over representative values |
| NUM-6 | `score_vector(legacy_mode=False)` MECHANISM replay on synthetic tiny-N HDF5 | 5 | NEW | aggregation choreography only (grand-mean, `-inf` sentinels, `None` gaps, NaN drop, `channel0001` attrs read, frozen raw filename) — explicitly NOT numeric parity (OD-3); `parallel=False`; files under `tmp_path`, never committed |
| NUM-7 | real-data numeric evidence tier (anchor consistency; legacy-parity test 3 `test_score_vector_legacy_mode_fine`) | 4 | REG | `real_run` higher-tier evidence, never claimed as CI; GREEN-BEFORE-CITE — a Stage-A claim citing NUM-7 attaches a fresh green data-machine log (§22.2); legacy-parity tests 1-2 DELETED per OD-4 |
| NUM-8 | `per_file_best` emitted-artifact key set incl. `metric_id` | 3 | NEW | roadmap step-06 A-surface; producer `execute_tools/per_file_best.py:357-360` |
| MD-1 | builtin model forwards + `MODEL_REGISTRY` contents | 3+5 | REG "verify strength" | roadmap step-03 A-surface; `tests/unit/ml_models/test_models_forward.py` + registry-population suite; strengthen to an exact registry key-set pin if absent |
| FC-1 | runtime forecast deep-equal breakdowns (PR-G pattern) | 2 | REG | roadmap step-05b A-surface; the PR-G estimator test family (`tests/unit/agent/{training_skill,inference_skill,denoising_score_skill}/test_estimator.py` + estimator-resolution suites) |
| EXE-1 | sandbox launch surface: subprocess argv construction, env transport (`SIDERIUS_PLUGIN_DIRS`), sentinel/artifact naming | 5 | REG "verify strength" | roadmap step-05c/11 A-surfaces; `test_generated_model_transport_chain.py`, `test_sdsc_argument_forwarding.py`, sentinel tests in `test_sandbox_executor.py`; strengthen to byte-level argv pins where weaker |
| EXE-2 | role rlimits resolve to TIDMAD values (train 40 / inference 60 / scoring 24 GiB) | 4 | REG "verify strength" | roadmap step-11 A-surface; `tests/unit/core/test_sandbox_rlimit.py`; the 60 GiB inference value is a CLAUDE.md-documented invariant |
| WF-1 | full `plan()` kwarg surface (25 params excl. `self`: `memory_history` POSITIONAL + 24 keyword) reaches the bridge | 5 | NEW | deep-equal of serializable subset; the positional binding of `memory_history` is part of the captured surface (review F11); `registry` (live object → type/identity pin) and `memory_history` (content pinned via K.9) excluded with justification |
| WF-2 | `reflect()` kwarg surface at its sole call site | 5 | NEW | positional-name latency registered as known-latent break |
| WF-3 | label/components inventory crossing `generate`/`generate_text` | 5 | NEW | requires widening `RecordingLLMBridge` (test helper) to record `(method, system, user, label, components)`; its own tuple-shape pins updated in the same commit per §17 |
| WF-4 | k9 + l_fail choreographies, attempt-budget pins, 12/12 protocol mappings, incumbent chain, stub determinism | 5 | REG+STR | k9's stale stdout assertion migrated to structured evidence in commit 0E (§22.3 outcome A); WF-4 is registered/citable ONLY once k9 is green |

### 13.1 Prompt family (PB) — capture design

Boundary ground truth (§4): the golden unit is the final
`(system_prompt, user_prompt)` STRING PAIR per call site — not a
message-list serialization, not a typed request object. `label=`/
`components=` cross the method boundary, not the API payload → WF-3,
not prompt goldens. `tool_call` has zero production call sites —
registered, not goldened.

Capture-point rule: for `generate`/`generate_text` the public-method
entry IS the API boundary (byte-pass-through). For `plan()`/`reflect()`
capture MUST hook the real render output (class-level patch at the
`_chat_json`/`generate` boundary — the proven pattern of
`scripts/render_proposer_prompts_for_audit.py:468-481`), never
`RecordingLLMBridge.calls` (§10.1) and never a test-side re-assembly of
the substitution chain (the audited anti-pattern in
`test_planner_prompt_task_config.py:80-96`).

Rules: no LLM calls; deterministic typed fixtures extending the
existing fixture-builder modules; failure output is a unified diff via
the shared helper (§16); template-layer ABSENCE/anti-hardcode tests are
preserved separately (they prove template properties; rendered-TIDMAD
goldens prove output properties — neither replaces the other);
Branch-B implementor and skipped-interpretation paths produce NO prompt
(audited) — registered as no-baseline-needed, their `emit_marker`
labels covered by WF-3. The planner `force_model` variant notes that
`get_output_type` can RAISE during render (live-registry coupling) —
the fixture pins the registry view.

Two further binding rules (adversarial review F13/F14):
- **No production source text in goldens**: the planner/proposer
  renders embed `inspect.getsource(config_cls)`
  (`agent/prompts.py:553`, threaded at tuner `:4120,4169`). If
  `config_cls` resolved to a production class, any comment/format edit
  to that production file would red the golden. PB-1/PB-3 fixtures
  MUST resolve `config_cls` (and any other source-embedding input) to
  TEST-OWNED frozen classes/modules committed under `tests/`.
- **Affirmative no-network guard**: `LLMBridge` constructs a live
  client with no API key, and the repo has no socket isolation — a
  mis-targeted patch on a machine with a real key set would issue a
  billable call. Every PB capture/assert must (a) assert the boundary
  patch fired ≥1 time and (b) patch the retry/HTTP entry point to
  raise, so a capture miss fails loudly offline (§14).

### 13.2 Config/dataset family (CFG/DS/HC)

The loader returns a dict and the renderer strips differently (§5), so
the resolved dict (CFG-1) and the rendered strings (CFG-2) are DISTINCT
drift surfaces and both are pinned. Exclusions: everything in §12.1
class 1. Hazards binding the implementation: baseline tests pass
EXPLICIT config paths (the default path is cwd-relative); never mutate
the shared cached dict; never import-couple to the `data_paths`
example-fallback. DS-3's digests bind to CPython's `random.sample` —
accepted and documented, not fixed. HC-1 inherits BOTH hazards itself
(review F9): `load_health_gates_config`'s default path is ALSO
cwd-relative (`execute_tools/health_checks/config.py:28`) and the
result is process-cached (`:264-272`) — HC-1 passes an explicit path
and uses the existing `clear_health_gates_config_cache()` fixture
(the `test_config_loader.py:36-38` precedent) to be order-independent.

### 13.3 Record/resume/plugin family (REC/RES/PLG)

REC-2's projection = the audited load-bearing consumption set —
resume's 11 fields PLUS `status` (§6), the tuner-read fields
(`memory.vram_estimate_gb` / `time_estimate_minutes` / `time_mode`,
`params.train_config.batch_size`), and the interpreter/funnel-consumed
fields — plus the stable-semantics fields. Excluded BY VALUE: the §6
volatile enumeration (timestamps, exp_id VALUES — format pinned by
REC-4 —, timing, measured memory VALUES, LLM free text, gpu_evidence,
absolute paths). The honest exclusion claim (review F4): **every field
whose VALUE drives a production decision is compared; pass-through and
measured-volatile fields are excluded by value but pinned by PRESENCE
via REC-1/REC-3** (a renamed/dropped key still fails; only the
measured number itself is free). Fixture source per OD-2 outcome A
(§22.1): the record is captured from a RecordingSandbox-driven pseudo
tuner iteration AT the production `_emit_record` seam (the validated
record, pre-serialization), with the capture fixture supplying a
typed length-20 score vector — the fixture is the output of the REAL
production record assembly under pinned inputs, no normalization step
required. StubSandbox-derived records are NEVER a fixture source.
`PersistedHealthGateResult` / gpu-evidence sub-fixtures constructed
through their typed schemas give the three structurally-empty pseudo
fields SHAPE coverage (Type-3 evidence, no producer-parity claim)
without committing absolute paths.

RES-1 is a **rewritten-header replay**, not byte-consumption of a
production artifact (review F10): production manifests carry an
ABSOLUTE `output_path` that `restore_prior_state` requires to exist
(`core/resume.py:273-290`), so the test stages the committed fixture
into `tmp_path`, rewrites `output_path` (and recomputes/writes
`run_output_sha256` consistently with the integrity check at
`:1250-1268`), then runs the real loader chain. The optional-file
degradation ladder (missing plugin → warning; missing digest → empty
carry-over) is asserted as part of the replay projection.

PLG-1 commits the real generated plugin
(`compact_wavenet_ce_coldstart_v1.py`, 3.9 KB) as a **`.py.txt` data
file** byte-identical to the on-disk original; the test copies it to
`tmp_path/<name>.py` and loads through the real
`extend_registries`/`_load_plugin` path. Rationale (review F5): a
`.py` copy under `tests/` would enter ruff's scope (only
`agent_generated` is excluded, `pyproject.toml:62-63`) and fails
`I001` today — reformatting would destroy the byte-identity that IS
the baseline. The `pe_wavenet_delta.py` precedent stays as-is (it is
hand-written and lint-clean).

### 13.4 Scorer/numeric family (NUM)

The frozen-scorer rule is absolute: zero scorer diff, including NOT
"fixing" the Nyquist literal to enable fixtures. NUM-1..5 are
committed-artifact arithmetic (no HDF5, no scorer execution beyond
loaders) — but per §12 rule 3's exemption clause (review F8), NUM-3/
NUM-4/NUM-5 compute their expected values THROUGH the production
helpers where they exist (`scoring_helpers`' log/grand-mean functions,
`per_file_best._log`), never by re-implementing the formula test-side,
so deleting or rewriting the production aggregation breaks the pins. NUM-6 is the taxonomy resolution of §11.3: a shrunken-N
replay CANNOT be a numeric baseline of the frozen scorer (it changes
the frequency grid and every SNR) but IS a valid Type-5 mechanism
baseline for the aggregation/IO choreography of
`score_vector(legacy_mode=False)` — today covered by NOTHING. Its
synthetic HDF5 is generated at test time under `tmp_path` (int8, both
channels, `channel0001` attrs present; monkeypatched `SEGMENT_LENGTH`
with `parallel=False` — the spawn path is a registered deferral).
Committing a ≥20 MB real-shape HDF5 is REJECTED (footprint rule §16;
no repo size policy exists; pack today is 12.1 MiB). Full-scale
numeric replay remains `real_run`-tier (NUM-7).

### 13.5 Choreography family (WF)

WF-1/2 capture at the production call sites through one bounded pseudo
tuner iteration (unit tier — the pseudo infrastructure is importable
outside `tests/integration/`). WF-3 is the ONLY test-helper change in
Step 00, and it closes ALL FOUR audited signature holes in
`RecordingLLMBridge` (review F18): record `label`/`components` on
`generate`; add `**kwargs` to `generate_text` AND `tool_call` (both
have the latent `TypeError`); align `reflect`'s parameter names with
production's (`actual_results`, `reflection_context`) — the sole
production call site passes positionally today, which is exactly the
latent break WF-2 registers. The helper's own tuple-shape pins are
updated in the same commit — an explicit, justified golden update per
§17, recorded in the commit message. The five ad-hoc bridges with
divergent tuple shapes are NOT unified in Step 00 (cleanup, not
baseline — registered).

### 13.6 Determinism ground truth consumed by §19

The pseudo path has no hash-ordering exposure (all set→list conversions
sorted; fixture/plugin load order sorted; exp_id pure; stub RNG seeded
from the run-id string) — BECAUSE it bypasses the planner render
(§10.3). The production render's single nondeterminism is §4.4. The
enumerated volatile fields (§6, §8) ARE the record-projection exclusion
list — each exclusion justified by enumeration.

### 13.7 Pseudo↔production fidelity boundary

Declared unenforced by design (`tests/pseudo_data/README.md`). Step 00
does NOT build a fidelity/schema-sync checker (new mechanism, no
current consumer); it REGISTERS the audited sandbox-double
divergences (`runtime_verification` key; inference `results` key;
`is_degenerate`/`_pseudo_origin` stamps; the stub's length-9
`file_vector`) in the §13.8 known-defect register as KNOWN DEFECT —
NOT BLESSED, so no later Stage-A claim can cite a pseudo shape as
production truth (§15.2 defers only the CHECKER). Whether a fidelity checker is worth building is
deferred to step 05c's design (owner of the execution-contract shapes).

### 13.8 Known-defect register (classified, never blessed)

| Defect | Evidence | Disposition |
|---|---|---|
| planner frozenset→json key order | §4.4, confirmed twice | OD-1; >3-record branch deferred |
| duplicate `file_vector` declaration | §6 | registered; fix belongs to a later schema PR (D1 territory). NOTE (review F16): the two declarations are byte-identical and the field keeps its first-declaration position, so REC-1 can neither detect the duplicate nor its removal — the register entry is the only guard |
| `StubSandbox` length-9 `file_vector` + on-disk `_pseudo_origin` 55th key | §6 (corrected), `core/sandbox_executor.py:2080,2095-2097` | registered NOT BLESSED; fixtures normalize (OD-2); checker deferred to step 05c |
| `RecordingLLMBridge` capture holes | §4.2 | WF-3 fixes the helper (test-only) |
| stale key-set docstring "53 fields" | §6 | corrected by REC-1's commit docs |
| schema-invalid historical record (`headroom_vs_gt < 0`) | §6 | documented only; never a fixture |
| k9 `assert "Feasible"` failure | §8, pre-existing at base | RESOLVED §22.3: test-only assertion migration in 0E; green before WF-4 registration; escalation guard if the gate proves not to fire |
| stale legacy-parity calls (missing `s_max`) + missing `docs/align_denoising_score.md` citation | §7 | RESOLVED §22.2: tests 1-2 deleted in 0D (property obsolete by intentional frozen decisions); test 3 kept as NUM-7 with green-before-cite; docstring re-scoped |
| stale FU-P2-4 xfail (committed copy already satisfies it) | §7 | retired in 0D with pointer to NUM-1 (§22.2) |
| pseudo sandbox-shape divergences | §8 | registered NOT BLESSED; checker deferred to step 05c |
| dangling `docs/pseudo_test_infra.md` citations | §9 | out of scope; registered |
| `validation_file_pattern` unwired (raw filename frozen literal) | §7 | MIGRATION PARITY label on NUM-6's filename pin; owning module step 02/06 (roadmap D10) |

## 14. Capture and regeneration mechanics

- **Boundary recorder**: a small test-side helper (in `tests/helpers/`,
  never production) that class-level-patches the bridge boundary and
  records `(label, system, user)` — the
  `render_proposer_prompts_for_audit.py` pattern promoted to a reusable
  test helper. Used by PB-1/PB-2 (and any golden whose render is inside
  the bridge); plain method-entry capture for the pass-through methods.
- **Capture script**: a `scripts/` dev helper MAY be added to
  regenerate goldens with a `SOURCE_COMMITS`-style provenance stamp;
  never imported by tests, never run in CI. Decided finally in the
  implementation's first commit; the convention is fixed here.
- **Comparison ergonomics**: golden reads use
  `read_text(encoding="utf-8")`; all comparisons go through one shared
  assert helper producing a readable unified diff on failure; no
  snapshot library is added (dev deps stay pyright/pytest/ruff);
  trailing newlines are preserved exactly as captured (two existing
  goldens lack one — kept as-is; they ARE the baseline).
- **No-network guard** (review F14): the boundary recorder patches the
  HTTP/retry entry point to RAISE and asserts it captured ≥1 render —
  a mis-targeted patch fails loudly offline instead of issuing a
  billable API call (the repo has no socket isolation; `LLMBridge`
  constructs a live client without an API key).

## 15. Coverage manifest

### 15.1 Roadmap step → Step-00 baselines

Rebuilt after adversarial review F1: the "A-surface" column below is
TRANSCRIBED from the roadmap §15.1 matrix's `A (parity)` column (not
re-worded), then each surface is mapped to baseline IDs or an explicit
§15.2 deferral. Every A-surface of steps 01-12 is accounted for.

| Step | Roadmap A-surface (transcribed) | Coverage |
|---|---|---|
| 01 | "rendered proposer prompts (all 3 stages incl. commit) EXACT-equal for TIDMAD + same kwargs reach LLMBridge" | PB-0, PB-3, PB-4 (prompts); WF-3 (label/components kwargs at proposer `generate` sites); CFG-1/2, CFG-3a/b (task-description channel) |
| 02 | "resolved profile deep-equals the TIDMAD singleton; SampleSet sha16 goldens; filename renders byte-identical" | DS-1 (constants + filename renders), DS-2, DS-3 (sha16 digests); NUM-6 (frozen raw-filename/IO mechanism) |
| 03 | "builtin forwards byte-identical; registry contents identical; guardrail targets extended; PRIOR ON-DISK GENERATED PLUGINS remain loadable" | MD-1 (builtin forwards + registry contents), PLG-1 (prior generated plugin loadability), PLG-2; REC-1 (`model_params` presence); "guardrail targets extended" is Stage-A WORK of step 03 itself, not a step-00 pinnable surface |
| 04 | "generated plugin byte-identical for a fixed spec; validator verdicts identical; ALL remaining rendered prompts EXACT-equal + same kwargs reach LLMBridge; prior-plugin loadability" | PB-5, PB-6, PB-9 (prompts); WF-3 (kwargs); PLG-1 (loadability); CFG-3a (duplication collapse guard); WF-4 (protocol mappings); "generated plugin byte-identical for a fixed spec" = DEFERRED (§15.2 — requires an LLM-output fixture pipeline that step 04's own design owns) |
| 05a | "SampleSet hashes + trial_config JSON deep-equal" | DS-3 (hashes); TC-1 (trial_config deep-equal) |
| 05b | "forecasts byte-identical under TIDMAD (deep-equal breakdowns, PR-G pattern); policy identities unchanged" | FC-1 (forecast breakdowns); the runtime/policy identity strings are pinned via `run_invariants_lock` consistency (registered in FC-1's scope — verify strength) |
| 05c | "argv/file-IPC byte-identical; artifacts byte-identical; sentinels untouched" | EXE-1 (argv/env/sentinels — REG verify strength); REC-3 (artifact key sets); byte-level artifact-content pins = DEFERRED (§15.2) |
| 06 | "frozen-formula pins + offline scalar baseline + legacy parity (real_run); per_file_best metric_id key-set pin" | NUM-1..6 (formula + offline scalars + mechanism), NUM-7 (real_run legacy parity — OD-4), NUM-8 (per_file_best key-set) |
| 07a | "planner/reflector prompts EXACT-equal + same kwargs reach LLMBridge; override-chain resolution deep-equal; record fields unchanged" | PB-1 (+OD-1 deferral of the >3 branch), PB-2, WF-1, WF-2, WF-3; REC-1/REC-2 (record fields); override-chain resolution deep-equal = DEFERRED (§15.2) |
| 07b (§7e) | "identity hashes/comparability unchanged (PR-G 0.R.12 pattern); store keys stable" | DS-2 (identity component order); the PR-G 0.R.12 identity-hash tests registered under FC-1's family |
| 08 | "TIDMAD verdicts identical on fixture outputs; sha-pin MECHANISM untouched" | HC-1 (config), REC-2 gate sub-fixture + REC-3 (result shapes); gate-verdicts-on-fixture-outputs = registered existing health-check unit suites (REG); the M9 pseudo-gate choreography gap stays DEFERRED (§15.2) |
| 09 | "3 existing interpreter goldens + new ones EXACT-equal + same kwargs reach LLMBridge" | PB-0 (the 3 interp goldens), PB-7, PB-8, WF-3; REC-3 (interpretation keys), RES-1 (knowledge carry-over) |
| 10 | "k9/l_fail choreographies pass unmodified; resume inventory field-stable" | WF-4 (with OD-5's green-before-cite rule), RES-1..3, REC-3 |
| 11 | "argv/IPC/sentinels byte-identical; rlimits resolve to same TIDMAD values" | EXE-1, EXE-2 |
| 12 | "regime-A callers byte-unchanged" | CFG-1, CFG-2, REC-1; plus the whole §13 inventory (regime-A behavior IS the sum of these baselines) |

### 15.2 Justified deferrals (the §1(c) register)

| Deferred surface | Why | Owner |
|---|---|---|
| planner >3-record condensed-history branch | §4.4 nondeterminism; disposition OD-1 | OD-1 / step 07a |
| full-scale numeric `score_vector` replay | needs real ≥20 MB data; `real_run` tier only (NUM-7) | step 06 design |
| `parallel=True` spawn scoring path | mocks/patches cannot cross spawn; needs real files or module-level fake | step 06 design |
| gate-enabled round choreography (M9 pseudo-gate gap) | pseudo stack writes no denoised HDF5s | step 08 design |
| time-budget round transitions | both choreographies disable budgets; behavior test, not baseline | step 05a design |
| mid-round resume, executed SKIP_TO_FORMAL jump, consecutive_fails reset | behavior tests, not baselines | step 05a design |
| pseudo↔production fidelity checker | new mechanism; no current consumer | step 05c design |
| `tool_call` boundary | zero production call sites | none (registered) |
| legacy proposer path reachability (UNKNOWN A.1) | whether any shipped config reaches it is unknown; PB-0 kept either way | step 01 design |
| "generated plugin byte-identical for a fixed spec" (step-04 A) | requires an LLM-output fixture pipeline; owned by step 04's own design | step 04 design |
| byte-level sandbox artifact-content pins (step-05c A) | artifact CONTENT is run-dependent; key sets pinned by REC-3; content pins need 05c's deliverable-contract fixtures | step 05c design |
| tuner override-chain resolution deep-equal (step-07a A) | resolution spans planner plan + operator overrides; needs 07a's fixture design | step 07a design |
| training-argv full byte pin (step-05c/11 A) | EXE-1 covers env transport/forwarding/sentinels; the byte pin IS step 05c's own A-checkpoint — no earlier consumer (0E verify-strength verdict) | step 05c design |

## 16. Fixture and artifact organization

Extends existing conventions; no new mechanism where one exists:

- Goldens: `tests/unit/<area>/goldens/<surface>_<scenario>.txt`
  (generalizing the existing agent-package layout, sibling to the
  consuming test). JSON expectations sit beside them as `.json`.
- All fixture INPUTS are constructed through typed schemas in Python
  (the `_health_feedback_fixtures.py` precedent — never a
  hand-simplified dict); committed EXPECTATIONS are text artifacts.
- Size: every committed baseline artifact is text (txt/json/yaml/py),
  reviewable in diff; total Step-00 fixture footprint well under 1 MB;
  zero binary fixtures (no `.h5`/`.npy`/`.pth`) — NUM-6 generates its
  HDF5 at test time under `tmp_path`.
- Execution tiers — THREE, stated explicitly (review F6):
  1. **Plain-unit CI tier**: all NEW/STR Step-00 baseline tests (no
     marker, offline, deterministic).
  2. **Registered dual-mode choreography tier** (WF-4: k9/l_fail):
     NEVER runs in CI (`tests/integration/` is outside the CI
     command). Invocation contract: run manually; any Stage-A claim
     citing WF-4 must attach a FRESH GREEN run log of the cited
     choreography — a red or unexecuted registration cannot be cited
     (OD-5).
  3. **`real_run` evidence tier** (NUM-7): real data/API; registered
     as higher-tier evidence, never claimed as CI; same
     green-before-cite rule as tier 2 — a Stage-A claim citing it
     attaches a fresh green data-machine log (§22.2).
  No new marker vocabulary; the `dual_mode` registration split is not
  replicated.
- Budget: the whole family adds O(seconds) — target < 30 s on top of
  the ~440 s unit suite (dominant costs: the WF pseudo iteration and
  PLG-1's tiny forward pass; everything else is milliseconds).
- Portability: CLAUDE.md rules bind — repo-root derived from file
  location; explicit paths; no developer-specific locations.

## 17. Golden update policy (binding; no convention existed — audit F)

1. Tests NEVER regenerate expected artifacts; CI NEVER updates goldens;
   there is no accept-all mechanism and no snapshot library.
2. Every expected artifact is tracked in git and reviewed as a diff.
3. Regeneration is an explicit developer act: a golden is CAPTURED in a
   test-only commit whose message states provenance ("captured at
   <sha>, clean tree" — the 23c3fbe5/66efed87 precedent); it is
   REGENERATED only in the same commit as the intentional production
   change that invalidates it, with the message stating (a) the
   intended behavior change, (b) the affected future compatibility
   surfaces, (c) why the old golden is no longer authoritative.
4. Provenance lives IN the artifact where the format allows: JSON
   baselines carry a `_captured_at: {commit: <sha>}` key (excluded from
   comparison); `.txt` prompt goldens stay content-only (they ARE the
   bytes) with provenance in the capture commit + a manifest entry —
   fixing the audited stale-docstring drift pattern (a5a2d9de).
5. A baseline test failure is NEVER resolved by regeneration alone: the
   diff is first classified (production drift / intentional change /
   fixture rot) per §19.3.

## 18. Implementation phasing (authorized only on operator approval)

**One test-only PR** on a dedicated branch, six semantic commits —
matching the one-PR-per-tier precedent. Commits 0A-0D are mutually
independent; 0E depends on 0A (helper widening); 0F closes.
Checkpoint 0 is complete at PR merge.

Prerequisite state: OD-1..5 are CLOSED (§22); implementation begins
only on the operator's explicit implementation authorization. Step 01
is BLOCKED on the implementation PR merging (a §15.2 deferral counts
as baseline resolution).

Standing rules for every commit below (reconciled 2026-08-12 with the
Implementation Working Rules — semantic commits are AUTONOMOUS):
- `[ ]` = not finished; `[x]` = implemented AND verified with recorded
  evidence. All boxes are `[ ]` now — NOTHING is implemented.
- Inspect the relevant code before finalizing each commit's low-level
  steps; the checklists below are specific enough to track but
  deliberately do not invent implementation details ahead of
  inspection.
- Per commit: inspect source before editing → update this live design
  ledger continuously → inspect the diff and staged file list before
  committing → record tests, decisions and deviations here → COMMIT
  AUTONOMOUSLY → continue to the next phase. Commits 0A-0F do NOT
  require individual operator approval.
- STOP only for: a material design/scope deviation; validation
  exceeding the approved cost envelope; an unresolved operator policy
  question; PR READY FOR OPERATOR REVIEW; merge approval (never
  merge).
- Update this document immediately after each implementation or test
  checkpoint — never batched at the end.
- Verification evidence = test counts + wall time recorded here after
  execution; any test that could not run is recorded with the reason,
  never claimed as passed.
- **Minimum-sufficient test cadence (operator, 2026-08-12)** — per
  semantic commit: targeted new tests + directly affected existing
  suites + mutation/adversarial checks + ruff/format on touched
  files; broader suites only where a shared-helper blast radius
  justifies them (run autonomously and record why). The FULL
  `pytest tests/unit/ -m "not real_run"` + ruff + `ruff format
  --check` + pyright strict + terminal CI run ONCE, at the final
  executable head (0F). Do not mechanically run the ~8k-test suite
  after every commit.
- No real-training Gates arise anywhere in this PR (test-only, no
  execution-behavior change); if any commit turns out to need one,
  that is a material deviation — stop for operator approval.
- Acceptance criteria are observable conditions; "tests pass" alone is
  never a criterion. Where a baseline claims to capture a boundary,
  the evidence is the recorded mutation turning it red (§19), not the
  green run.

### 18.1 Commit 0A — capture infrastructure + prompt goldens (PB)

**Goal.** Zero exact prompt coverage exists at the true LLM boundary
for the production paths (§4.3); this commit creates the capture
mechanics (boundary recorder, shared diff helper, no-network guard)
and lands the PB family. It is first because 0E's WF captures reuse
the widened helper, and every other golden uses the diff helper.

**Scope.**
- New: `tests/helpers/` boundary recorder + diff-assert helper;
  `tests/unit/<area>/goldens/*.txt` for PB-1..PB-9; capture fixtures
  (test-owned frozen `config_cls` modules per §13.1); optionally a
  `scripts/` capture tool with `SOURCE_COMMITS` stamp (§14).
- Changed (test-helper ONLY): `tests/helpers/recording_llm_bridge.py`
  per WF-3's four signature holes (§13.5) + its tuple-shape pin tests
  in the same commit.
- Non-goals: zero production diff (`agent/`, `nodes/`, `workflows/`,
  `execute_tools/`, `core/`, `ml_models/` untouched); no LLM calls;
  PB-1's >3-record branch stays deferred per OD-1; existing PB-0
  goldens byte-untouched.
- Depends on: the operator's implementation authorization (OD-1..5
      are CLOSED, §22).

**Implementation plan.**
- [x] Recorder mechanism chosen and landed:
      `tests/helpers/llm_boundary_recorder.py::BoundaryRecorderBridge`
      subclasses the production `LLMBridge` and overrides ONLY the three
      create-owning methods (`_chat_json`/`generate_text`/`tool_call`) —
      plan()/reflect()/generate() bodies run unmodified, so capture is
      one layer BELOW method entry (exactly the API payload).
- [x] `tests/helpers/golden.py::assert_golden` — utf-8 reads, unified
      diff, explicit trailing-newline divergence message, §19.3 triage
      text, capture instructions on missing golden.
- [x] No-network guard: both clients replaced with a raising sentinel
      (`NetworkEscapeError`) after construction; dummy api_key so env
      keys are never read; tests assert the recorder fired.
- [x] `RecordingLLMBridge` widened (all 4 holes): generate records its
      kwargs dict (4th elem); generate_text + tool_call gain **kwargs
      (accepted AND recorded — closes the audited latent TypeError);
      reflect renamed to production `actual_results`/`reflection_context`.
      Pin suite updated + 4 new WF-3 regression pins in the same commit.
      Blast radius: zero unit-tier consumers beyond the pin suite
      (verified by grep); integration consumers exercised at 0E.
- [x] Test-owned frozen values for every source-embedding input:
      implementor reference_code + descriptions; proposer plugin source
      via a patched `_SIDERIUS_ROOT` tmp tree (unpatched, builtin
      candidates embed `ml_models/models_sandbox.py` class bodies —
      confirmed by recon); frozen validator error strings (live errors
      carry pydantic version URLs/abs paths/unseeded torch values).
- [x] PB-1 captured (2 variants: auto + force_model=punet classifier
      branch; system prompt proven force_model-independent and shared)
      and PB-2 captured, through the REAL bridge renders
      (`tests/unit/agent/llm_bridge/test_step00_prompt_goldens.py` + 5
      goldens). OD-1 deferral recorded mechanically
      (`test_pb1_full_window_boundary_is_the_deferral_line`). Ledger
      note: the force_model variant's `get_output_type` import
      auto-scans the machine-local gitignored plugin tree (stdout noise
      only) — rendered bytes depend only on the BUILTIN punet output
      type; CI tree is empty; recorded as accepted coupling.
- [x] PB-3 captured: full production pipeline via run() with canned
      schema-valid stage JSON (exact label sequence asserted; 3 explore
      + 3 exploit system goldens + 3 MODE-INVARIANT user goldens —
      invariance asserted); env fully pinned (_SIDERIUS_ROOT,
      _GLOBAL_LOSS_DIR, MODEL_REGISTRY stub, tmp capability index).
      CAPTURE-TIME DEFECT CAUGHT: candidate selection reads
      per_model_best_valid (not per_model_best) — first capture had
      "Candidates: []" and the source-embedding block silently vanished;
      fixture corrected and the reason documented in the test.
- [x] PB-4 captured (commit system constant + 2-input user render).
- [x] PB-5 captured: reasoning/code via run() with an aborting recorder
      (stops before the env-coupled smoke test), loss reasoning/code via
      _generate_loss, repair ×2 variants + loss repair via real
      producers with frozen error strings; system constants goldened
      (13 goldens).
- [x] PB-6 captured: clean + frozen-error branches via the real
      _llm_review wrapper (3 goldens).
- [x] PB-7 captured: per-model FLAG-ON user+system (system's structural
      identity flag-OFF + HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS also
      asserted), synthesis system+user (workspace pinned to a FROZEN
      literal — verbatim interpolation labeled MIGRATION PARITY), dedup
      via agent._dedup_promoted (6 goldens).
- [x] PB-8 captured via the real consolidate() (bottlenecks empty side
      pins the exactly-one-call branch; 2 goldens).
- [x] PB-9 captured: extract (arxiv_source + pdfplumber system, user),
      search_decision (first-round via _run_search_loop with
      max_rounds=1 — no network reachable; prior/escalation/coverage
      via the real producer), synthesis (v1/moderate + v0 + strict
      systems, user with equations-present/pseudocode-empty) — 9
      goldens. All node drives bypass run() (disk caches/network);
      root_cache_dir pinned to tmp_path.
- [x] PB-0 registered: the 4 existing goldens byte-untouched; their
      suites re-run green alongside the new families (19 passed).
      (Stale-docstring correction is a doc concern tracked at 0F.)

**Validation plan.**
- [ ] Unit: every golden asserts byte equality via the shared helper.
- [ ] Negative/invalid: no-network guard test (mis-targeted patch →
      loud offline failure); recorder fires-≥1 assertion test.
- [x] Mutation C (md-template loader path): token swap in
      `agent/prompt_templates/proposal/comparison_stage.md` (site
      count 1) → BOTH PB-3 system-variant tests red; restored; green.
- [x] Mutation A (template token, `agent/prompts.py` force_model
      constraint text, site count 1): RED exactly on the force_model
      variant golden; restored; green. Mutation B (render substitution:
      swapped plugin_source_excerpt/exploration_checklist append order
      inside `plan()`, args unchanged): RED on BOTH planner goldens —
      proves capture at the render output (§10.1); restored; green.
      __pycache__ cleared around each; backups verified.
- [x] Negative control: mutating `label="tuner.planner"` fails ONLY
      the capture-site label integrity assert — both golden byte
      comparisons unaffected (prompt bytes provably label-independent;
      the label surface belongs to WF-3). Restored; green.
- [ ] Backward-compat: the widened helper's DIRECT consumer suites
      green (`test_recording_fakes.py`, the five ad-hoc-bridge test
      files, and every suite importing `recording_llm_bridge`) — this
      is the shared-helper blast radius that justifies a broader run
      under the cadence rule.

**Acceptance criteria.**
- [ ] Every §13 PB row exists as a committed golden + test, or is in
      §15.2 (only the PB-1 >3 branch).
- [ ] The two §19.1 PB mutations are recorded red→reverted→green.
- [ ] `git diff --stat` for the commit touches only `tests/` (+
      optional `scripts/` capture tool).
- [ ] The recorder's captured pair for one pass-through site is shown
      byte-equal to the method-entry arguments (proves §4.1's
      pass-through claim on the implementation, not just the audit).

**Failure/edge cases.**
- Registry/`get_output_type` RAISE during render (§13.1): the fixture
  registry view must make renders total; a raising render is a test
  failure, not a skip.
- Missing golden file → the helper reports capture instructions, not
  a bare FileNotFoundError.
- Accidental real-API attempt → no-network guard raises (stop, never
  warn).

**Verification commands (evidence recorded after execution).**
- [ ] `pytest tests/unit/<pb test paths> -q` → counts + wall time.
- [ ] Helper blast-radius suites (direct consumers of the widened
      recording bridge) → counts + wall time.
- [ ] `ruff check`/`ruff format --check` on touched files.

**Commit boundary.** Independently reviewable (capture mechanics + PB
only); no unrelated cleanup (the five ad-hoc bridges stay); inspect
diff summary + staged list, record deviations in this ledger, commit
autonomously.

### 18.2 Commit 0B — config / dataset / health-config baselines

**Goal.** Pin the resolved-config and dataset-constant surfaces
(CFG-1/2/3a/3b, DS-1/2/3 additions, HC-1, TC-1) — the §5 audit showed
the shipped rendered strings and most constants are pinned by nothing.

**Scope.** New tests + JSON/txt expectations under
`tests/unit/{workflows,execute_tools,...}/goldens/`; no production or
config-file changes; DS-3 adds two digests without touching the
existing three. Depends on: 0A's diff helper only.

**Implementation plan.**
- [x] Producers inspected. LEDGER CORRECTION (TC-1): the tuner's
      TrialConfig composition is INLINE in run() (tuner:4362), not
      unit-invokable — TC-1 pins the SCHEMA-resolution surface
      (model_validate + model_dump with defaults materialized; the
      validated schema object is the declared single source of truth),
      with in-run stamps pinned by REC-2 and selection by DS-3. Also
      pinned as fact: the three sampling seeds are REQUIRED fields.
- [x] CFG-1/CFG-2/CFG-3a/CFG-3b landed
      (`tests/unit/workflows/test_step00_task_config_baselines.py` + 4
      goldens). CFG-2's forward-contract render sha256[:16] verified at
      capture == `ed34ede6803eb6f8` (the audit-B value, exact).
- [x] DS-1 (six-field deep-equal, exact 36-entry segmentation list,
      filename renders, module constants, full-scope resolve) + DS-2
      (`resolve_tidmad_measurement_capability` with explicit
      dataset_root → shape-class string; MeasurementIdentity 8-tuple
      component order + identity_key join) in
      `tests/unit/execute_tools/test_step00_dataset_baselines.py`;
      DS-3 +2 digests (normal `1cdcc3997db777b1`, partial-scope
      `70481a8ad4ddeecb`) appended to `test_sample_set_builder.py`.
- [x] HC-1 deep-equal with explicit path + autouse cache-clear
      (`tests/unit/execute_tools/health_checks/
      test_step00_health_config_baseline.py` + JSON golden, 5.6 KB).
- [x] TC-1: two goldens (trial-mode full inputs; formal-mode minimal
      inputs with defaults materialized).

**Validation plan.**
- [x] Unit: 52 passed (family + full sample-set suite, 0.8 s);
      `assert_json_golden` added to the shared helper (Type-2 variant,
      `_captured_at` provenance excluded per §17 rule 4).
- [x] Invalid-input: N/A — no new mechanism added (existing loader
      suites own invalid-input behavior).
- [x] Mutations red→green: M1 output_description in shipped YAML →
      CFG-1 AND CFG-2 both red (two-distinct-surfaces criterion; first
      attempt was an invalid mutation — token absent, classified and
      re-aimed); M2 health threshold 25→26 → HC-1 red; M3
      segments_per_file 200→100 (temp production mutation, restored) →
      11 red incl. DS-1 and both new digests; M4 TrialConfig
      trial_portion default 0.02→0.021 (line-anchored; block text
      appears twice in the schema file) → TC-1 formal-defaults golden
      red. All restored; family green after each.
- [x] Negative control: full family run from `/tmp` cwd — 15 passed
      (explicit-path/cwd-independence + cache isolation).

**Acceptance criteria.**
- [ ] Every CFG/DS/HC/TC §13 row landed; the §19.1 CFG mutation shows
      BOTH CFG-1 and CFG-2 failing (two distinct surfaces proven).
- [ ] DS-3's two new digests recorded with (seed, portion, scope)
      provenance in-artifact.
- [ ] Commit touches only `tests/`.

**Failure/edge cases.** Shared-cache leakage between tests (cache-
clear fixtures mandatory); cwd-relative default paths (never used);
the gitignored `tidmad_data_config.yaml` machine fallback (excluded
surface — tests must not import-couple, §13.2).

**Verification commands.**
- [ ] Family pytest run + directly affected loader suites +
      ruff/format on touched files (cadence rule; no full suite).

**Commit boundary.** Config/dataset pins only; no prompt or record
content; inspect diff, record in ledger, commit autonomously.

### 18.3 Commit 0C — record / resume / plugin baselines

**Goal.** No serialized-record golden, no committed replay workspace,
and no committed-plugin load test exist (§6); this commit lands
REC-1..4, RES-1 (registering RES-2/3), PLG-1 (registering PLG-2).

**Scope.** New: normalized pseudo-derived record fixture + typed
sub-fixtures (OD-2 outcome A, §22.1); committed minimal replay workspace
(text files only); the `.py.txt` plugin fixture (§13.3). No schema or
production changes; the duplicate `file_vector` and the stale "53
fields" docstring are NOT fixed here (register only; the docstring
correction rides REC-1's commit message context, the file itself is a
test file — inspect first and if it is production-adjacent, leave it).
Depends on: 0A's diff helper.

**Implementation plan.**
- [x] REC-1: ExperimentRecord 54-field ordered list inline;
      HyperparamTuningOutput/InterpretationOutput/TrialConfig ordered
      lists as a JSON golden (capture-time assert proved the inline
      list matches the live schema exactly).
- [x] OD-2 fixture path landed BETTER than specified: a shared
      bounded pseudo-iteration helper
      (`tests/helpers/step00_pseudo_iteration.py`) runs the REAL tuner
      (RecordingSandbox + RecordingLLMBridge, k9-shaped input) so
      records flow through the live `_emit_record` seam; the pseudo
      score fixture already carries length-20 vectors and
      RecordingSandbox stamps nothing — ZERO normalization needed.
      IMPLEMENTATION DISCOVERY: the tuner package's autouse unit guard
      forbids the real isolated pre-flight worker; per its sanctioned
      pattern the boundary is stubbed with
      `fixtures/step00_preflight_results.json` — the three legacy
      dicts captured from the REAL `run_production_preflight` during a
      live pseudo run (path-free, machine-independent; also removes
      k9's machine-calibrated-ceiling fragility from this test).
      Typed gate/gpu sub-fixtures: deferred as unnecessary — the
      three structurally-empty fields are presence-pinned by the
      projection and shape-owned by their schemas' own suites
      (recorded deviation, schema-shape claim unchanged).
- [x] REC-2: formal-success AND OOM-skip projections as JSON goldens
      (path-free, verified zero /home //tmp strings); volatile fields
      presence-only; in-test negative control proves volatile-only
      changes project identically.
- [x] REC-3: manifest key sets for all 3 status branches via the
      REAL `write_manifest` (completed branch consumes the pseudo
      run's actual HyperparamTuningOutput); schema field lists (above);
      summary artifact: LEDGER CORRECTION — `save_record` json-dumps
      the RAW construction-site dict, so on-disk summary entries carry
      the producing site's insertion-order key subset, NOT the 54-key
      dump (previous assumption falsified by the first test run);
      pinned as per-entry key-list golden + model_validate parse
      contract.
- [x] REC-4: format + zero-padding + strict ordering asserted on the
      live-path records (both production sites render the same
      f-string; tie-break dependency documented in the test).
- [x] RES-1: committed workspace fixture
      (`tests/unit/core/fixtures/step00_replay_workspace/`, 4 JSON
      files, relative placeholders) staged + header-rewritten + sha
      inserted; real `restore_prior_state` chain; full RestoredState
      projection asserted; degradation ladder (no plugin + no digest →
      UserWarning + empties). Plugin copied from the TRACKED
      pe_wavenet_delta at stage time (no new committed .py).
- [x] PLG-1: byte-identical `.py.txt` copy of the real PR-G campaign
      plugin (sha256-verified against `.gate_artifacts` original at
      staging and in-test); staged via SIDERIUS_PLUGIN_DIRS (the real
      env transport) → extend_registries → config+model classes →
      forward [1,64] int64 → [1,256,64] float32.

**Validation plan.**
- [x] Unit: 11 passed (0C family, 1.5 s incl. the bounded pseudo
      iteration); directly affected suites (resume, cold-start,
      plugin-loader, hyperparam schemas, recording fakes + family):
      200 passed, 2.5 s.
- [x] Negative/invalid: M3 sha tamper → ReplayIntegrityError; M4
      layout break (iteration_001 renamed) → ResumeError; M5
      PLUGIN_MODEL_CLASS strip → loader skips, zero loaded.
- [x] Backward-compat: summary entries model_validate in-test; the
      staged run_output parses through the real loader.
- [x] Negative control: volatile-only record variant projects
      identically (in-test, §19.2).

**Acceptance criteria.**
- [ ] REC-2's compared projection provably contains every §6
      consumption field incl. `status` and the tuner-read fields
      (assert the projection key list against a literal in the test).
- [ ] RES-1 runs the REAL `restore_prior_state` (no mocking of the
      loader chain) — shown by the mutation turning it red.
- [ ] PLG-1's staged bytes are identical to the committed fixture
      (hash-compare in-test); ruff/format green (the fixture is
      `.py.txt`, outside lint scope).
- [ ] Commit touches only `tests/`.

**Failure/edge cases.** Absolute `output_path` in manifests (staged +
rewritten, §13.3); sha integrity interplay when rewriting; missing
optional workspace files (warning-path assertions, not failures);
plugin `sys.modules` registration/rollback (use the real loader's
semantics, assert no residue).

**Verification commands.** [x] Family + affected suites: 200 passed
(2.5 s); mutations M1 (schema field rename → REC-1 red), M2 (canned
plan lr → both REC-2 projections red), M3/M4/M5 above — all restored,
family green after each; ruff check+format clean on touched files.

**Commit boundary.** Record/resume/plugin only; inspect diff, record
in ledger, commit autonomously.

### 18.4 Commit 0D — scorer / numeric baselines

**Goal.** The CI numeric surface is 5 scalars at 1e-3 and the
production `score_vector(legacy_mode=False)` path has zero tests (§7);
this commit lands NUM-1..6, NUM-8, registers NUM-7, and applies the
APPROVED OD-4 legacy-parity disposition (§22.2).

**Scope.** New tests under `tests/unit/{nodes,execute_tools}/`;
strengthens `test_scoring_reference_default.py` (STR — inspect before
editing); the §22.2 disposition in
`tests/integration/scoring/test_legacy_parity.py` (delete tests 1-2,
keep test 3, re-scope the "canonical merge gate" docstring, retire
the FU-P2-4 xfail); zero scorer/production change (frozen-scorer rule
§13.4). Depends on: 0A's diff helper. OD-3/OD-4: RESOLVED (§22).

**Implementation plan.**
- [ ] NUM-1 full-precision pins (all 40 + 2 scalars + s_max) —
      routed through `nodes/scoring_reference.py` loaders.
- [ ] NUM-2 anchor-map pins (s_max exact, 20×200 shape, canonical
      digest).
- [ ] NUM-3/NUM-4/NUM-5 via production helpers per §12-rule-3
      exemption (inspect `scoring_helpers`/`per_file_best` first).
- [x] NUM-6: 6 mechanism tests on runtime-generated tiny-N HDF5
      (real TIDMAD group layout `timeseries/chNNNN/timeseries` —
      discovered at first run; attrs on the group): length-20 vector +
      None gaps + GRAND-MEAN aggregation proven with unequal per-file
      counts against the production log helper; bit-identical
      determinism; empty-set -inf; NaN-drop on a MIXED good/degenerate
      fixture; frozen raw-filename FileNotFoundError (MIGRATION
      PARITY); partial-segment reshape ValueError (discovery: an EMPTY
      slice reshapes cleanly to (0,N) and silent-drops — only a
      partial tail errors; both documented as the frozen mechanism).
- [x] NUM-8: real `build_table` over the RES-1 staged workspace →
      `metric_id == "tidmad_denoising_score"` + sorted key-set golden
      (10 keys).
- [x] NUM-7 registered + OD-4 APPLIED: legacy-parity tests 1-2
      DELETED with the §22.2 justification in the re-scoped file
      docstring (dead doc citation removed); the FU-P2-4 xfail RETIRED
      — replaced by a LIVE exact-equality test against the COMMITTED
      reference_data (also fixing its hardcoded /home/klz portability
      violation).

**Validation plan.**
- [x] Unit: 46 passed (NUM family + strengthened reference test +
      scoring_helpers incl. the retired-xfail replacement, 2.3 s);
      scoring-affected suites 95 passed.
- [x] Invalid-input: partial-segment reshape ValueError pinned.
- [x] Mutations red→green: artifact one-digit → NUM-1 AND NUM-4 red;
      anchor value → NUM-2 AND NUM-3 red; aggregation flip (count
      files not segments) → NUM-6 grand-mean red; NaN-drop skip —
      first target (`:231` subnormal guard) SURVIVED, CLASSIFIED
      EQUIVALENT for synthesizable fixtures (zero-PSD → 0/0 NaN caught
      by the downstream isfinite drop), re-aimed at the REAL drop site
      (`_collect_raw_pairs`) with a strengthened mixed fixture → RED.
      All restored; family green.
- [x] Backward-compat: the strong pins strictly imply the old 1e-3
      pins (replaced in place per the keep-only-strong rule).

**Acceptance criteria.**
- [ ] Every committed reference number is pinned at full precision;
      perturbing ONE digit of ONE artifact fails ≥2 named baselines
      (NUM-1 + NUM-4 for per-file; NUM-2 + NUM-3 for anchors).
- [ ] NUM-6 executes the REAL `score_vector` body (shown by the
      aggregation-flip mutation), with zero committed binary files.
- [ ] Commit touches only `tests/` (+ the OD-4 file if approved).

**Failure/edge cases.** int16 CH2 mis-scaling trap (fixture is int8
by construction, asserted); spawn-path exclusion documented in-test;
numpy-version sensitivity recorded as limitation (§21.4), not
asserted.

**Verification commands.** Family pytest run + directly affected
scoring suites + ruff/format on touched files (cadence rule; no full
suite).

**Commit boundary.** Numeric family only; the OD-4 deletions
(approved, §22.2) are called out separately in the commit message
citing §22.2; inspect diff, record in ledger, commit autonomously.

### 18.5 Commit 0E — choreography / kwargs baselines (WF)

**Goal.** The plan/reflect kwarg surfaces and the label inventory are
uncaptured (§8, §4.2); this commit lands WF-1/WF-2 (kwargs), the
WF-3 label-inventory baseline (the helper widening itself landed in
0A), and registers WF-4, MD-1, FC-1, EXE-1, EXE-2 with
strength-verification.

**Scope.** New unit-tier tests driving one bounded pseudo tuner
iteration; registration entries (docstring/manifest cross-refs) for
the REG rows incl. reading each registered test and recording its
actual assert strength (§13 legend); the §22.3 TEST-ONLY k9 assertion
migration in `tests/integration/workflows/
test_k9_invented_model_dual_mode.py`. No production change. Depends
on: 0A (widened helper).

**Implementation plan.**
- [x] Harness = the shared 0C bounded pseudo iteration (real tuner
      call sites crossed; RecordingLLMBridge records transitively).
- [x] WF-1: round-1 plan() surface deep-equal golden (path-leak
      checked at capture: zero) + kwarg key-set golden asserted
      identical across all 3 calls (22 kwargs + expert_advice/
      force_model + positional memory_history = the 25-param surface);
      registry pinned by type name (CapabilityRegistry),
      memory_history by type/length (content owned by WF-4/k9).
- [x] WF-2: both reflect calls' surfaces (exp_id presence,
      hypothesis type, actual_results/reflection_context sorted key
      sets) as a JSON golden.
- [x] WF-3 disposition (bounded deviation, recorded): the recording
      capability landed in 0A (helper widened + 4 regression pins);
      label COVERAGE is realized as the explicit per-surface label
      asserts distributed across the PB/boundary tests (tuner.planner,
      tuner.reflector, proposer.comparison/causal_reasoning/proposing,
      implementor ×4 captured labels + 2 repair constants, validator.
      code_review, interpretation.per_model/synthesis/dedup,
      cache_consolidator.list_merge, lit_review.paper_extract/
      search_decision/synthesis) — a single-run consolidated inventory
      would require executing every node in one test, duplicating all
      PB fixtures for no added sensitivity; the audited 20-label table
      remains in §4.3.
- [x] Verify-strength verdicts (each test read):
      MD-1 SUFFICIENT — builtin→class identity mapping pinned
      (`test_models_forward.py:44-49`) + per-builtin forward shape
      contract; exact registry key-set equality is structurally
      impossible while the registry auto-extends from the machine
      plugin tree (subset + identity mapping is the honest pin).
      FC-1 SUFFICIENT — estimator suites pin breakdown key sets and
      exact byte arithmetic (e.g. `weights_bytes == 100_000*4`,
      `inference_batch == 25`).
      EXE-2 SUFFICIENT — `test_sandbox_rlimit.py` pins scoring 24 /
      training 40 / inference 60 GiB on BOTH the function and the
      table, plus env override + zero-disable.
      EXE-1 PARTIAL → env transport (SIDERIUS_PLUGIN_DIRS subprocess
      asserts), CLI forwarding, and sentinel recognition are
      registered; the full training-argv BYTE pin is moved to §15.2
      as an explicit deferral owned by step 05c (whose own
      A-checkpoint IS "argv/file-IPC byte-identical" — pinning it in
      Step 00 would duplicate that checkpoint with no earlier
      consumer).
- [x] k9 migration DONE (test-only): the stale stdout assert
      replaced by equivalent-strength structured evidence — ≥1 record
      carrying a gate verdict (skipped_oom_risk OR
      memory.vram_estimate_gb) with the escalation guard in the
      failure message; Layer 2 keeps the strong pseudo taxonomy.
      Migration discovery: production does NOT stamp vram_estimate_gb
      on the FORMAL record (the gate runs — its preflight was captured
      live in 0C — but the stamp is trial-scoped); a per-record
      assertion was therefore stronger than the original property and
      was corrected, documented in the test. k9 GREEN: 1 passed,
      11.7 s (rc=0 from the log). l_fail GREEN: 1 passed, 72.7 s
      (rc=0). The gate FIRES (skip record + trial evidence) — the
      §22.3 escalation case did not arise.
- [x] WF-4 REGISTERED (k9 + l_fail fresh green logs recorded above;
      tier-2 invocation contract per §16 — citing Stage-A claims must
      attach fresh green runs).

**Validation plan.**
- [x] Unit: 3 passed (WF family, 1.4 s).
- [x] Mutation: deleted the `max_epochs=` line at the production plan
      call site → BOTH WF-1 tests red (surface + key-set); restored;
      green. (Label-separation control was recorded at 0A: label
      mutation fails only the capture-site integrity assert, golden
      bytes green.)
- [x] Determinism: family run twice back-to-back — 3 passed both
      (module-scoped fresh iterations each run).
- [x] Cost: bounded pseudo iteration ≈1.4 s per module run (well
      inside the §16 budget).

**Acceptance criteria.**
- [ ] Dropping any single VALUE-carrying plan kwarg at the call site
      is proven red (one representative mutation recorded; the
      deep-equal covers all).
- [ ] The label inventory equals the audited 20-label set or the
      difference is explained in the test docstring.
- [ ] Each REG "verify strength" row has a recorded verdict
      (sufficient as-is / strengthened here).
- [ ] k9 is GREEN under the migrated assertions (fresh log recorded
      here) — WF-4's registration is invalid without it.
- [ ] Commit touches only `tests/`.

**Failure/edge cases.** Live-object kwargs (excluded by rule, §13's
WF-1 row); positional `memory_history` binding (asserted); the
reflect param-name latency (registered known-latent break — NOT fixed
in production here).

**Verification commands.** Family pytest run ×2 (determinism) + the
migrated k9 run (green log recorded) + directly affected suites +
ruff/format on touched files (cadence rule; no full suite).

**Commit boundary.** Choreography family + registrations + the k9
test-only migration; inspect diff, record in ledger, commit
autonomously.

### 18.6 Commit 0F — manifest closeout

**Goal.** Make Checkpoint 0 checkable: reconcile this document's §13
inventory and §15 manifest against what actually landed, finalize the
known-defect register, and assemble the §19 evidence dossier.

**Scope.** Docs (this file + folder README + roadmap matrix row per
Checkpoint E) + at most a manifest cross-check test (asserting every
§13 baseline ID has a landed test — inspect feasibility first; if it
would be decoration per the test-value rule, record N/A instead).
Depends on: 0A-0E.

**Implementation plan.**
- [ ] Reconcile every §13 row's status ([x] with evidence or moved to
      §15.2).
- [ ] Record the full §19.1/§19.2 evidence table (mutation, red
      output excerpt, revert, green).
- [ ] Update roadmap §15.1 step-0 row + folder README + docs index.
- [ ] Final `git diff master --stat` scope proof (tests/ + docs/ +
      the declared helper + optional scripts/ tool only).

**Validation plan.**
- [ ] Full unit suite + ruff (check+format) + pyright strict on the
      final head, from a CLEAN tree (commit checkpoint first).
- [ ] CI green on the PR head.

**Acceptance criteria.**
- [ ] §20's Checkpoint-0 and Checkpoint-D bullets all check.
- [ ] No §13 row is left in an undeclared state.
- [ ] PR description carries the evidence dossier and the
      "MIGRATION PARITY" labels list.

**Failure/edge cases.** A baseline that cannot land as designed →
material deviation → stop for operator decision (never silently
re-scope).

**Verification commands.**
- [ ] `pytest tests/unit/ -m "not real_run" -q > /tmp/pytest.log;
      rc=$?; tail -20 /tmp/pytest.log` — verdict from the LOG.
- [ ] CI status from the exact final head.

**Commit boundary.** Closeout only; no new baselines enter here.

## 19. Validation design — mutation battery and failure diagnostics

Executed during implementation as recorded evidence (mutation applied
locally, test observed red, mutation reverted, baseline re-verified
green — the mutation-proof hygiene rules apply: cache clear, count==1,
baseline re-run). Not committed as always-on tests.

### 19.1 Per-family mutations (each must turn its baseline RED)

| Family | Mutation | Expected failure |
|---|---|---|
| PB | swap two lines in one prompt template; change one token | unified diff naming the golden + surface |
| PB (render layer) | alter the planner render's substitution (not its inputs) | PB-1 fails — proves capture is at the render, not the args (§10.1's validation consequence) |
| WF-1 | drop/rename one of the 24 keyword params (or the positional binding) at the tuner call site | deep-equal fails naming the kwarg |
| WF-3 | change one production `label=` string | label-inventory diff |
| CFG | perturb `num_classes` / a note field in the shipped YAML | CFG-1 and CFG-2 both fail (two distinct surfaces) |
| HC-1 | perturb one threshold in `configs/health_checks.yaml` | HC-1 deep-equal diff naming the gate + field |
| TC-1 | perturb one resolved trial-decision field | deep-equal diff |
| MD-1/EXE-1/EXE-2 | remove one registry entry / one argv element / change one rlimit value | registered (strengthened) pin fails — recorded during 0E's verify-strength pass |
| NUM-8 | drop `metric_id` from the per_file_best artifact | key-set pin fails |
| DS | remove one entry from the 36-divisor list logic; change a filename render | DS-1 fails |
| REC | add/remove/reorder one `ExperimentRecord` field | REC-1 ordered-list diff |
| REC-2 | change a load-bearing field value in the fixture pipeline | projection diff |
| RES | corrupt `run_output_sha256` in the committed manifest | `ReplayIntegrityError` (RES-2 path) |
| RES | break the workspace layout (rename `plugins/iter_001/`) | RES-1 projection mismatch (warning-path assertion) |
| PLG | strip `PLUGIN_MODEL_CLASS` from the fixture plugin | loader returns None → PLG-1 fails |
| NUM | perturb one digit in one committed per-file JSON | NUM-1 and NUM-4 fail |
| NUM | perturb one anchor value | NUM-2 (digest) and NUM-3 (derivability) fail |
| NUM-6 | flip the aggregation to mean-of-means; skip the NaN drop | mechanism replay fails |

### 19.2 Negative controls (volatile changes must NOT fire baselines)

- A fresh capture differing ONLY in timestamp / exp_id run-name /
  absolute path / timing values validates against REC-2 unchanged.
- Changing a `label=` string does NOT fail any PB golden (label is
  WF-3's surface, proving the separation is real).
- Re-running the full unit suite twice yields byte-identical baseline
  verdicts (no hidden wall-clock/hash coupling) — the §13.6 ground
  truth makes this expected, the run makes it evidence.

### 19.2a Executed mutation dossier (0F closeout — all restored, family green after each)

| # | Mutation (site count verified) | Result |
|---|---|---|
| PB-A | prompts.py force_model constraint token | RED on exactly the force_model golden |
| PB-B | plan() render-order swap (args unchanged) | RED on both planner goldens (capture is at the render — §10.1) |
| PB-C | md-template token (comparison_stage.md) | RED on both PB-3 system tests |
| PB-NC | label string mutation | goldens GREEN; only the capture-site integrity assert fired (§19.2 separation) |
| CFG | shipped-YAML output_description | RED on CFG-1 AND CFG-2 (two distinct surfaces) |
| HC | health threshold 25→26 | RED on HC-1 |
| DS | segments_per_file 200→100 (temp production) | 11 RED incl. DS-1 + both new digests |
| TC | TrialConfig trial_portion default 0.02→0.021 (line-anchored; block text ×2 in file) | RED on the formal-defaults golden |
| REC-1 | schema field rename | RED on the ordered field list |
| REC-2 | canned-plan lr value | RED on both record projections |
| RES | staged-manifest sha tamper | ReplayIntegrityError |
| RES | workspace layout break | ResumeError |
| PLG | PLUGIN_MODEL_CLASS strip | loader skips; zero loaded |
| NUM | one digit in one per-file artifact | RED on NUM-1 AND NUM-4 |
| NUM | one anchor value | RED on NUM-2 AND NUM-3 |
| NUM | aggregation flip (count files, not segments) | RED on the NUM-6 grand-mean test |
| NUM | NaN-drop skip | first target (`:231` subnormal guard) SURVIVED → CLASSIFIED EQUIVALENT for synthesizable fixtures (0/0→NaN caught downstream); re-aimed at the REAL drop site with a strengthened mixed fixture → RED |
| WF | max_epochs kwarg deleted at the plan call site | RED on both WF-1 tests |
| Global-NC | volatile-only record variant | projections identical (REC-2 in-test control) |
| Global-NC | /tmp-cwd family run | 15 passed (path/cache isolation) |
| Global-NC | WF family run twice | byte-identical verdicts |

By category: 16 behavior-changing mutations caught; 1 equivalent
mutation classified with evidence and re-aimed; 0 surviving
behavior-changing mutations; 3 negative controls green.

### 19.3 Failure diagnostics and ownership

Every baseline failure message names: the baseline ID, the producing
surface (module:line at capture), and shows a unified diff. Triage
contract (documented in the test docstrings): (1) production drift —
unintended change upstream: fix production, never the golden; (2)
intentional change — regenerate per §17 rule 3 in the SAME commit; (3)
fixture rot — environment leaked into a fixture: fix the fixture and
record why the exclusion list missed it.

## 20. Checkpoint acceptance criteria (roadmap §17: Step 00 passes 0, D, E)

- **Checkpoint 0 — PRIMARY STEP-00 ACCEPTANCE CHECKPOINT — MET at the
  0F head** (every §13 row landed NEW/STR/REG per the reconciliation
  preamble; every §15.1 A-surface maps to landed baselines or §15.2
  deferrals incl. the two added during implementation; WF-4 and NUM-7
  carry green-before-cite; k9 is GREEN). Definition (corrected
  2026-08-12: creating trustworthy baselines IS this step's mission,
  so this checkpoint is its principal acceptance, not a formality):
  every §13 inventory row is landed as NEW/STR/REG, or moved to §15.2
  with justification; the §15.1 manifest holds (each step 01-12 row
  maps to existing baselines or registered deferrals); no later
  Stage-A claim can cite a missing or red baseline (the WF-4/NUM-7
  green-before-cite rules are part of this checkpoint).
- **Checkpoint D (regression)**: full unit suite + ruff (check+format)
  + pyright strict green in CI on the exact final head; the §19.1
  mutation battery executed with recorded red/green evidence in the PR;
  the §19.2 negative controls recorded; zero production diff proven by
  `git diff --stat` scope (tests/ + docs/ only, plus the single
  declared test-helper widening).
- **Checkpoint E (roadmap sync)**: the roadmap §15.1 matrix row for
  step 0 updated in the same PR or an immediately-merged docs
  follow-up BEFORE any step-01 PR opens; this document's status moved
  to reflect the merged state; folder README + docs index rows
  current.

## 21. Risks and limitations

1. **Golden brittleness vs drift blindness**: Type-1 goldens fail on
   ANY intentional prompt edit. Accepted deliberately — during
   migration, silent drift is the failure mode being bought out;
   the §17 policy makes intentional updates cheap and reviewed.
2. **Registry/plugin-tree coupling of PB-3/PB-1**: pipeline-proposer
   and planner renders read live registries and the `agent_generated/`
   tree; fixtures pin views of them, so a future registry-shape change
   fails these goldens with a fixture-rot signature (§19.3 class 3)
   rather than a production-drift one. Documented in the test
   docstrings. **Source-text coupling** (review F13) is the sharper
   form: renders embed `inspect.getsource` of config classes — hence
   the §13.1 rule that all source-embedding inputs resolve to
   test-owned frozen modules; a golden must never embed production
   source text.
3. **CPython coupling of DS-3** (`random.sample`) — accepted,
   documented; a Python-version bump that changes digests is an
   intentional-change regeneration with provenance.
4. **numpy unpinned upper bound**: CI is `uv.lock`-frozen at 2.4.3
   today; NUM baselines are arithmetic-only so version drift surfaces
   first in `real_run` evidence, not CI — recorded limitation, no
   cross-version FFT bit-stability evidence exists.
5. **WF pseudo-iteration cost**: the bounded pseudo iteration is the
   most expensive new unit test; if it exceeds the O-seconds budget,
   the implementation narrows the iteration, never markers it out of
   CI.
6. **Step 00 must not become a benchmark**: baselines pin
   compatibility, not quality; no score thresholds, no performance
   assertions anywhere in the family.

## 22. Operator decisions — FINAL STATES (reconciliation 2026-08-12)

All five are now CLOSED. OD-1/OD-3 were approved by the operator
directly; OD-2/OD-4/OD-5 were closed by the narrow source audits the
operator directed (evidence in §22.1-22.3), pending only the
operator's confirmation of those three audit results.

| OD | Final state |
|---|---|
| OD-1 | **APPROVED (operator, 2026-08-12)**: Step 00 captures the planner golden with the deterministic ≤3-history fixture; the >3 condensed-history branch is explicitly DEFERRED. Before Step 07a: a separate operator-approved deterministic-ordering correction for BOTH frozenset-derived render sites (`agent/prompts.py:896,899` / constants `:852,867`) lands as a predecessor PR, then the >3-history planner golden is captured BEFORE tuner knowledge/prompt extraction. PYTHONHASHSEED pinning REJECTED. |
| OD-2 | **RESOLVED — outcome A** (§22.1): same production record producer on both paths; capture via a RecordingSandbox-based pseudo iteration at the `_emit_record` seam; StubSandbox-derived records are NEVER a fixture source. |
| OD-3 | **APPROVED (operator, 2026-08-12)** as recommended: numeric/mechanism split; NUM-1..5 committed numeric pins; NUM-6 runtime-generated shrunken-N Type-5 MECHANISM replay only; NUM-7 real-data higher tier; no committed large HDF5; zero frozen-scorer change. |
| OD-4 | **RESOLVED per-test** (§22.2): tests 1-2 DELETE (property obsolete by three intentional frozen decisions; coverage owned elsewhere); test 3 KEEP and register as NUM-7 with a green-before-cite rule. |
| OD-5 | **RESOLVED — outcome A** (§22.3): test-only assertion migration inside commit 0E; k9 must be GREEN before WF-4 is registered/citable; "register red as-is" is withdrawn. |

### 22.1 OD-2 — record-producer path audit (source-grounded)

The eight operator questions, answered from source:

1. **Which function builds the final record dict?** The production
   tuner's record-construction sites, all funneled through the single
   validate-and-persist seam `_emit_record`
   (`ml_hyperparameter_tune_agent.py:560-588`): attach runtime
   evidence (when an executor status exists) → stamp `candidate_id` →
   `ExperimentRecord.model_validate` → `sandbox.save_record`.
2. **Identical on pseudo and production?** YES. The sandbox and
   bridge enter by constructor dependency-injection (`:3533-3540`,
   `:3750`); grep of the tuner for `pseudo` finds only docstrings and
   DI comments — ZERO pseudo branches in record assembly.
3. **Fields from common assembly**: all identity/round/status/plan-
   derived/DataScope/ordering fields and the record STRUCTURE.
4. **Differences introduced only by doubles**: VALUE-level — canned
   plan/train/score results; absent `gpu_evidence` /
   `failure_attribution`; empty `health_gate_results` when gates are
   disabled. Plus, for **StubSandbox only**, two serialization-layer
   artifacts: the `_pseudo_origin` stamp added in its `save_record`
   AFTER common assembly+validation (`core/sandbox_executor.py:
   2095-2097`) and the length-9 fake scorer vector (`:2080`).
5. **Bypass/reimplementation?** NONE found. `RecordingSandbox`
   (`tests/helpers/recording_sandbox.py:193`) appends the validated
   record verbatim (no stamp) and mirrors the summary write;
   `score_vector` (`:102-117`) returns the FIXTURE-defined
   `(file_vector, scalar)` — shape is capture-input-controlled.
6. **`_pseudo_origin` post-assembly?** YES (StubSandbox only; after
   `model_validate`, at serialization).
7. **Length-9 the only score-shape difference?** For StubSandbox yes;
   for RecordingSandbox the shape is whatever the fixture defines —
   the capture fixture supplies a typed length-20 vector, so no
   post-hoc replacement is needed.
8. **Typed gate/gpu sub-fixtures**: they pin SCHEMA SHAPES only
   (Type-3 evidence); they claim no production-producer parity —
   production-value parity for `health_gate_results`/`gpu_evidence`
   remains deferred with the gate-enabled choreography (§15.2).

**Frozen outcome A**: REC-2's fixture is captured from a
RecordingSandbox-driven pseudo tuner iteration AT the `_emit_record`
seam (the validated record, pre-serialization) with a length-20
fixture score vector — the record is the output of the REAL production
assembly given pinned inputs, so §12 rule 3 is satisfied without any
normalization step. StubSandbox-derived records are NEVER used as a
fixture source (its two serialization artifacts stay in the §13.8
register). REC-3 separately pins the SERIALIZATION-layer key sets
against the production writers.

### 22.2 OD-4 — legacy-parity tests, audited by name

File: `tests/integration/scoring/test_legacy_parity.py`
(`pytestmark = real_run`; reference = `tests/fixtures/legacy_scoring.py`,
verbatim legacy + one-line float64 patch).

| Test | Intended property | Verdict |
|---|---|---|
| `TestLegacyParity::test_calculate_score_coarse` (:88) | `compute_raw_baseline._calculate_score(coarse=True)` reproduces patched-legacy `calculateBenchmark` bit-for-bit (1e-10) via `process_segment` | **DELETE** |
| `TestLegacyParity::test_calculate_score_fine` (:106) | same, fine scan (n=200) | **DELETE** |
| `TestLegacyParity::test_score_vector_legacy_mode_fine` (:124) | `score_vector(legacy_mode=True)`, `sample_set={0: range(200)}` — the production entry point reproduces legacy | **KEEP** (= NUM-7) |

Mechanical justification for DELETE (not "broken therefore
worthless" — the property itself is obsolete by THREE intentional
frozen decisions, documented in `_calculate_score`'s own docstring,
`scripts/compute_raw_baseline.py:69-133`):
- normalization ruler: legacy divides by the FILE-LOCAL
  `np.amax(snr_sg)` (`legacy_scoring.py:169`); current
  `_calculate_score` divides by the GLOBAL anchor `s_max` — the
  deliberate one-ruler alignment with `score_vector` and the ceiling;
- quantization: legacy applies `np.round(·, decimals=2)`
  (`legacy_scoring.py:170`); removed intentionally;
- offset: legacy adds `+ 1e-10` (`:170`); removed intentionally.
Bit-parity at 1e-10 against the legacy scalar is therefore
unsatisfiable by design (the round alone quantizes to 2 decimals);
even repairing the missing-`s_max` signature cannot restore a
scientifically valid property. Unique coverage accounting: the
still-valid properties of `_calculate_score` are owned by
`tests/unit/test_compute_raw_baseline.py` (1e-12 aggregation pins,
mocked `process_segment`), NUM-1 (full-precision pins on this exact
function's committed outputs), NUM-4 (artifact self-consistency), and
NUM-5 (log-base identity). The LEGACY-reproduction property survives
solely through test 3, whose `legacy_mode=True` path re-derives the
file-local `np.amax` internally (`scoring_utils.py:615-627`) —
signature-valid and semantically coherent today.

Consequences: (a) tests 1-2 deleted in commit 0D with this section
cited in the commit message; (b) the "canonical merge gate" docstring
wording is re-scoped in the same commit to test 3 + the NUM family
(the file docstring's three-comparison framing and the dead
`docs/align_denoising_score.md` citation are corrected); (c) the
stale FU-P2-4 `xfail` is retired in 0D with a pointer to NUM-1;
(d) NUM-7 inherits a **green-before-cite rule** (same governance as
WF-4): test 3's last real execution is not recoverable from the tree,
so any Stage-A claim citing NUM-7 must attach a fresh green
`real_run` log from the data machine.

### 22.3 OD-5 — k9 red-baseline contradiction, resolved

Audited failure path: the ONLY failing assertion is
`assert "Feasible" in stdout` (`test_k9_invented_model_dual_mode.py:268`,
Layer 1 "gate stdout"); the run completes and writes its `run_output`
first (Area-C measurement). The string is printed by the VRAM/time
gate wrappers (`agent/skills/evaluate_vram_skill/wrapper.py:700,733`,
`evaluate_time_skill/wrapper.py:956`); at HEAD that print no longer
reaches the parent stdout on this path. The wrappers RETURN a
structured dict (`{"status", "feasible", "verdict", "suggestion",
...}` — `wrapper.py:701-705`) that the tuner consumes, and the
choreography's outcome is already production-owned structured
evidence: the record taxonomy (one `skipped_oom_risk` + two
`success`) that the test's own Layer 2 asserts.

**Frozen outcome A — test-only assertion migration**: commit 0E
replaces the stale stdout assertion with assertions on the structured
evidence (gate verdict via the records/status taxonomy in both modes),
preserving and still EXECUTING the same production choreography, with
no production print restored or moved. k9 must then be GREEN before
WF-4 is registered or cited by any Stage-A claim; the §15.1 step-10
row's use of WF-4 is conditional on that green registration.
Escalation guard: if the migrated assertions reveal the gate itself no
longer fires on this path (no `skipped_oom_risk` record), that is a
MATERIAL FINDING — stop, reclassify to outcome B (deferral) or C
(predecessor PR), operator decision. "Register the red baseline
as-is" is withdrawn. Whether the verdict PRINT should be restored is a
step-05a question, out of Step-00 scope.

### 22.4 Original decision table (superseded record)

| OD | Question | Options (§11) | Recommendation |
|---|---|---|---|
| OD-1 | planner-history nondeterminism disposition | (a) ≤3-record fixture now, >3 branch deferred; (b) PYTHONHASHSEED-pinned capture — NOTE this CANNOT be a `monkeypatch.setenv` (the var is read at interpreter start): it requires a CI-level env pin or a subprocess-launched capture; (c) deterministic-ordering production fix — TWO comprehension sites (`agent/prompts.py:896` AND `:899`, or equivalently the two frozenset constants `:852`/`:867`), NOT one line — as a separate operator-approved predecessor PR; (d) defer all exact planner coverage | (a) for Step-00 capture — deterministic without environment tricks and zero production diff; carry (c) as the recommended PREDECESSOR for step 07a so the interesting branch gets a clean baseline before tuner-knowledge extraction. (b) rejected: bakes a hash-seed-dependent byte order into a golden and an env knob into CI. Note the exposure ALSO exists on the production `--is_pseudo_llm` path via `StubLLMBridge` (§4.2) — (c) fixes that too |
| OD-2 | record-fixture source | pseudo-derived-NORMALIZED vs scrubbed real record vs fresh capture | pseudo-derived record normalized to production shape (strip the on-disk `_pseudo_origin` 55th key; replace the stub's length-9 `file_vector` with a typed length-20 value — normalizations recorded in fixture provenance) + typed-schema sub-fixtures for the three structurally-empty fields — full key/shape coverage, zero absolute paths, no scrubbing policy needed; the schema-invalid historical record documented as defect only. The un-normalized pseudo shape is NEVER committed (review F2) |
| OD-3 | scorer replay policy | commit ~20 MB HDF5 vs shrunken-N replay vs arithmetic-only | taxonomy resolution §13.4: shrunken-N as Type-5 MECHANISM baseline (never numeric), arithmetic Type-4 pins for numerics, real_run registered as the numeric-execution tier; HDF5 commit rejected. Confirm |
| OD-4 | stale legacy-parity test | repair the 2 broken calls vs delete tests 1-2 keep test 3 | delete tests 1-2 (file-local vs global `s_max` — no longer parity-comparable even if repaired), keep test 3; update the "canonical merge gate" doc wording in the same commit; also retire the stale FU-P2-4 xfail with a pointer to NUM-1 |
| OD-5 | k9 pre-existing failure | register as-is (failure documented) vs fix first | register as-is with the failure documented AND the binding rule (review F6): a RED or unexecuted WF-4 choreography cannot be cited by any Stage-A claim — the citing step must attach a fresh green run log, so the k9 fix (a production print relocation, out of Step-00 scope, tracked for step 05a) must land before step 05a/10 cite it |

## 23. Adversarial design review record (2026-08-11)

A fresh read-only reviewer attacked the completed draft along the 13
operator questions, source-verifying every criticism. 18 findings (2
BLOCKER, 6 MAJOR, 7 MINOR, 3 NIT) — ALL reconciled into this document;
the load-bearing ones were independently re-verified by the main
designer before adoption (roadmap A-column transcription; `StubLLMBridge`
inheriting the real `plan()`/`reflect()`; the stub's on-disk 55-key /
length-9-vector record shape; the `status` read in
`candidate_eligibility.py:161`; `plan()`'s 25-parameter surface):

F1 §15.1 rebuilt against the roadmap's literal A column (new baselines
TC-1, MD-1, FC-1, EXE-1, EXE-2, NUM-8; three new §15.2 deferrals) ·
F2 pseudo-record shape corrected in §6 + OD-2 (normalize, never commit
the pseudo shape) · F3 `StubLLMBridge` added as fourth render surface
(§4.2) + §10.3 re-scoped · F4 REC-2 consumption set extended (`status`,
tuner-read fields) + exclusion claim restated honestly (§6, §13.3) ·
F5 PLG-1 stored as `.py.txt` (ruff scope) · F6 third execution tier +
green-before-cite rule (§16, OD-5) · F7 WF family given its own commit
0E · F8 §12-rule-3 exemption + NUM-3/4/5 routed through production
helpers · F9 HC-1 path/cache hazards (§13.2) + §19.1 row · F10 RES-1
declared a rewritten-header replay (§13.3) · F11 WF-1 25 params,
positional binding captured · F12 REC-4 pins both sites + tie-break
justification · F13 no production source text in goldens (§13.1,
§21.2) · F14 affirmative no-network guard (§13.1, §14) · F15 OD-1
option texts corrected (two-site fix; env-pin mechanics) · F16
REC-1-pins-duplicate claim dropped (§13.8) · F17 cross-references
fixed (§1→§15; CFG-3 split; DEF legend; §13.7→§13.8; WF-3 added to
steps 01/04/09 rows) · F18 WF-3 widened to all four helper signature
holes. Attacks that found nothing (boundary rule, missed prompt sites,
monolithic snapshots, real-data-as-CI claims, consumer-less baselines,
hidden production changes, benchmark drift) are recorded in the review
transcript; the reviewer's sampled factual claims all verified.

## 23a. Operator review + final reconciliation record (2026-08-12)

The operator reviewed the design: architecture, taxonomy, inventory,
coverage-manifest approach and phasing APPROVED IN PRINCIPLE; OD-1 and
OD-3 approved directly; three narrow source audits directed and
completed (§22.1-22.3: record-producer path → outcome A; legacy-parity
per-test audit → delete 2 / keep 1; k9 → test-only assertion
migration). Governance corrections applied in the same pass: §18
realigned with the Implementation Working Rules (autonomous semantic
commits; stop only for material deviation / cost envelope / policy
question / PR-ready / merge); minimum-sufficient test cadence (full
suite + static + CI once at the 0F final head, targeted+affected
suites per commit); Checkpoint 0 re-titled PRIMARY STEP-00 ACCEPTANCE
CHECKPOINT. Mechanical path/status verification at HEAD: roadmap
FROZEN; canonical folder `docs/design/generic_framework_upgrade/`;
canonical filename `step_00_golden_baseline_harness.md`; zero live
references to `docs/design/generic_framework/` or
`pr0_golden_baseline_harness.md` (the operator's uploaded snapshot was
stale — repository truth verified, no edit needed).

## 24. Design + implementation status

**IMPLEMENTED — PR OPEN, AWAITING CI + OPERATOR REVIEW — NOT MERGED —
DO NOT MERGE (operator-owned).** The operator authorized
implementation 2026-08-12 with OD-1..5 final; six semantic commits
landed (0A.1 capture infra + PB-1/2 + WF-3 widening; 0A.2 PB-3..9;
0B CFG/DS/HC/TC; 0C REC/RES/PLG per OD-2 outcome A; 0D NUM + OD-4
dispositions; 0E WF + OD-5 k9 migration GREEN + verify-strength) plus
this 0F closeout. §18's checklists carry per-commit evidence; §19.2a
is the executed mutation dossier; §13's reconciliation preamble maps
every inventory row to its landed test; Checkpoint 0 MET, Checkpoint
D/E complete at the final head per §20. No Step-01 work.
