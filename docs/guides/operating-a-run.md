# Operating a run

**Audience**: whoever is watching the GPU.
**Answers**: what a run is doing, how to steer it, and what its refusals mean.

---

## What one iteration does

```
interpret        read every record so far; say what the evidence supports
  ↓
literature review (optional)   surface recent papers as soft priors
  ↓
propose          an architecture + an explicit prediction about its behaviour
  ↓
implement        write the model plugin (and optionally a loss plugin)
  ↓
validate         load it, run its tests, check the contract, gradient flow, LLM review
  ↓
tune             N rounds, each: plan → train → infer → score → health → reflect
```

The tuner is where compute is spent. Each round the planner proposes
hyperparameters, the model trains, inference produces deliverables, the metric
scores them, health gates judge validity, and the reflector interprets the round.

**Trial versus formal.** Trial rounds are cheap explorations under a reduced
budget. A trial that looks promising is promoted to a formal round, which is what
produces a competing candidate. Delta gates suppress spurious promotions when a
new plan barely moves the score.

## Steering a run

| you want to | do |
|---|---|
| see what would happen, spend nothing | `--dry-run` |
| bound the work | `--num_iterations`, `--max_rounds`, `--max_proposal_attempts` |
| bound the wall time | `--trial_time_budget_minutes`, `--formal_time_budget_minutes` |
| bound memory | `--trial_vram_budget_gb`, `--formal_vram_budget_gb` |
| use only some of the data | `--data_scope 4-9` (+ in-scope `--health_gate_files`) |
| stop health gates blocking | `--healthgate_mode observe_only` |
| turn the health subsystem off | `--no-health_gate_enabled` |
| inject human guidance | `--human_advice_file` |

Time budgets matter more than they look. Without them, a badly chosen data
portion from the planner can produce multi-hour rounds.

## Resume

Auto-resume is **on by default**. Re-running the same command against the same
workspace continues from the first incomplete iteration; if all iterations are
complete it exits cleanly rather than redoing work.

```bash
--no_auto_resume     # force a fresh start regardless of workspace state
--start_iter N       # pin manually, overriding the inspector
```

## The invariants lock

At startup a run writes `{workspace}/run_invariants_lock.json`, pinning:

- the resolved data scope,
- whether health gates are enabled,
- the sha256 of the effective health configuration.

Resuming, seeding from, or reusing that workspace with any of these different
**fails at startup**. This is deliberate: aggregate scores are only comparable
within one scope and one health configuration. A workspace that silently accepted
a change would be producing numbers incomparable with its own history — and
nothing downstream would know.

If you need different settings, use a new workspace.

## Reading what happened

Every node writes its output record to
`{storage.local.workspace}/{node}_{run_name}.json`. These are **logs, not
channels** — nodes never read each other's files; data flows through typed
protocols in memory. Read them to understand a run, not to wire anything.

Records carry provenance: the composition fingerprint, the effective health
config hash, the resolved scope, and — for file-declared plugins — content
hashes. Two records with the same fingerprint were produced under the same
declared semantics.

The dashboard (`python dashboard/main.py`, then `http://localhost:8000`) browses
results interactively. For a remote run, tunnel it:
`ssh -L 8000:localhost:8000 <host>`.

## Failures and refusals

SIDERIUS distinguishes *failing* from *refusing*, and the distinction is worth
learning.

| outcome | meaning | what to do |
|---|---|---|
| **round invalidated** | a blocking health gate fired — the output was not valid enough to count | nothing; the loop already knows |
| **`not_scoreable`** | the metric's scoreability contract refused before arithmetic | check the deliverable was written and is readable |
| **validation failure** | the generated model failed a validator check | the loop retries with error feedback, up to `--max_proposal_attempts` |
| **over-budget proposal (advisory only)** | the proposer's static wall-time estimate exceeded the budget — since `e1a9efb7` (2026-07-30) this is a labelled `PREFLIGHT_ADVISORY` note (`nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:185-214`, provenance `static_uncalibrated`, `blocking_eligible=no`); no revision is requested | nothing at this stage. The real guard is measured GPU admission in the tuner (`core/runtime_control/admission.py:355 evaluate_gpu_admission`, driven by the pre-phase measurement); a refusal there consumes an attempt and is recorded as `skipped_resource_admission` / `skipped_infrastructure_failure` |
| **composition refused** | a manifest problem | see [define a task](define-a-task.md#when-it-refuses) |
| **startup lock mismatch** | this workspace was created under different invariants | use a new workspace |
| **exit code 2** | a formal launch without `--healthgate_mode` / `--result_authority` | supply both — they have no defaults on purpose |

A run that stops early on a streak of failed rounds is doing so by design
(`--max_fail_rounds`), not crashing.

## Cost control

- The planner and reflector can use different models
  (`--reflect_provider` / `--reflect_model_id`) — roughly halves top-tier quota
  use.
- `llm_configs/*.json` route each stage to a chosen provider and model.
- Trial rounds exist precisely so that formal-budget compute is spent on
  candidates that have already shown something.

## Health gates during a run

Gates fire at **tuner round boundaries**, not inside scoring. A blocking failure
resolves to one of `invalidate_round`, `skip_to_formal` or `skip_iter`; when
several fire, severity resolves
`skip_iter` > `skip_to_formal` > `invalidate_round` > `continue`.

Remember what a PASS means: nothing detectably invalid. Not "good". See
[health gates](../concepts/health-gates.md).

## Cross-hardware bring-up (H100 posture)

**Claim this section makes.** The campaign's resource posture on the H100 fleet
is declared, source-backed and provenance-labelled: every limit the runtime
enforces has a row below naming its source line, its current value, how that
value was derived, the surface that overrides it, and either its H100 value or
an explicit **MEASURE ON THE BOX** marker. Nothing here is guessed — the H100
host's RAM, per-user VRAM quota, driver and real card capacity are unknown to
this document and are recorded as measurements to take.

**Topology (v2, fleet ruling 2026-08-25): FOUR CO-RESIDENT BAND CHAINS PER
CARD.** One card per arm; each card runs the four band chains
(`0-3/4-9/10-14/15-19`) under an 18 GiB per-chain budget and a 72 GiB
aggregate ceiling, launched by `launch_band_fleet.sh`. The V19/V20 pair/queue
launchers (`v19_gate0_pair_runner.sh`, `v19_queue_runner.sh`,
`v20_queue_runner.py --max_active 2`) implement the old 5090 *pair* topology
and are still not used. (v1 of this posture declared one chain per card; the
author's fleet ruling supersedes it — see Table 1's `H100_MAX_ACTIVE_PER_CARD`
row.)

**The committed artifact.** `sdsc_submission_scripts/h100_posture.env`
(`H100_POSTURE_VERSION=1`) is the frozen contract with the campaign launcher,
which `source`s it after `--h100`. It (a) exports the environment the runtime
reads, and (b) defines `H100_CHAIN_ARGS`, a bash array of chain flags the
launcher splats **after** its own arguments — `_chain_common.sh`'s parser lets
a later flag override an earlier one (`:322-339`), so the posture wins. It
carries the resource and safety posture only; workload policy (time budgets,
rounds, portions, scope, LLM config) stays with the launcher.
`tests/unit/docs/test_h100_posture.py` fails when the file and Table 1
disagree, when an exported name is one no production module reads, or when a
flag is one the chain parser would reject.

### Derivation classes

| class | meaning |
|---|---|
| **hardware-derived** | a fraction of a figure the driver reports (`total_memory`) — moves with the card, not with opinion |
| **policy** | an operator choice; carried across hardware until a measurement says otherwise |
| **empirical** | measured once on a NAMED host and kept as a number (`measured`, `empirical_unverified`, `incident` in `core/execution_calibration.py`) |
| **learned** | adapted at runtime from observed steps; cold on a GPU name it has never seen |

### Measurements to take on the box before the pilot

Record the output of these on the H100 host in the pilot report; the MEASURE
rows below cannot be filled in from here.

- `nvidia-smi -L` — card count and UUIDs (one ARM per card; four band chains co-resident).
- `nvidia-smi --query-gpu=name,uuid,memory.total,driver_version --format=csv`
  — card capacity in MiB and the driver version.
- `free -g` — host RAM; the RSS ceilings and the pre-flight worker share it.
- `nproc`.
- `torch.cuda.get_device_properties(0)` from the project virtualenv — `name`
  and `total_memory` (bytes; divide by `1024**3` for GiB), the figure the
  0.80 safety fraction is applied to.

Then read the run's own view of the card: the `[Hardware]` line the VRAM
pre-flight prints (`agent/skills/evaluate_vram_skill/wrapper.py:671-674`,
`cap=… GB (PHYSICAL: 80% of … GB)`) and the manifest at
`{workspace}/{run_name}_hardware.json` (`core/hardware_context.py:28`). The
per-user VRAM quota, if the fleet enforces one, has no universal command —
ask the fleet operator and record the answer as a number and its unit.

### Table 1 — values shipped in `h100_posture.env` (machine-checked)

Column 2 is the value the file ships; the drift test reads this block by its
markers. `unset` means the file carries a commented placeholder and exports
nothing. All "GB" flags are implemented as GiB (`wrapper.py:87`, `_GB = 1024**3`).

<!-- h100-posture-table:begin -->
| surface | H100 value | class | source | why this value |
|---|---|---|---|---|
| `H100_POSTURE_VERSION` | `2` | policy | `sdsc_submission_scripts/h100_posture.env` | bumped on any value change so a run log can name the posture it ran under |
| `H100_MAX_ACTIVE_PER_CARD` | `4` | policy (topology) | `h100_posture.env`; consumed by `launch_band_fleet.sh` and the campaign preflight admission arithmetic | four co-resident band chains per card (author fleet ruling 2026-08-25, #261/#259 comments; supersedes v1's one-chain-per-card). The legacy pair/queue runners are still not used |
| `SIDERIUS_PAIR_VRAM_CEILING_GIB` | `72` | hardware-derived: 0.80 × 80 GB nominal | `core/runtime_control/pair_admission.py:43-45` default `28.0` (a 31.34 GiB RTX 5090 pair value), `:52` env name, `:91-108` resolver; consumed by `core/runtime_control/admission.py:485-492,513-517` as `effective = min(configured, measured capacity)` | left at the default, an 80 GB card is silently capped: a measured training requirement plus everything else on the card must fit under 28 GiB or the phase is refused `insufficient_headroom`. 72 = 4 chains × 18 GiB: the aggregate the admission layer may grant across the card's co-resident chains (v2, four-chain topology); the remaining ~7.6 GiB of a 79.6 GiB card is context/allocator headroom |
| `SIDERIUS_PREFLIGHT_WORKER_MEM_GIB` | `24` | policy (shipped default, restated) | `agent/skills/evaluate_vram_skill/isolated_probe.py:98-127` (env read `:118`); reused by the pre-phase GPU measurement worker (`nodes/ml_hyperparameter_tune_agent/runtime.py:375-386`) | host-RAM ceiling for ONE pre-flight worker. The default's arithmetic assumed two chains on a 61.8 GiB host; re-derive per host — **MEASURE**: `N_chains_on_host × (24 worker + 40 training child + ~1 parent) + ~4 OS` must fit `free -g`, else lower it in a posture bump |
| `SIDERIUS_SUBPROCESS_RSS_GB` | `unset` | — (global override) | `core/execution_calibration.py:45` name, `:152-213` two-layer resolution, `:199-212` malformed value REFUSED; consumer `core/sandbox_executor.py:123-139` | replaces the per-role 40 / 60 / 24 GiB ceilings for EVERY child role at once, so it cannot retune one role; `0` disables. Leave unset unless the host-RAM MEASURE row shows the declared roles cannot fit (see Table 2) |
| `SIDERIUS_GPU_VRAM_QUOTA_MIB` | `unset` | policy (deployment fact) — **MEASURE ON THE BOX** | `core/runtime_control/pair_admission.py:47-51` name (MiB), `:75-89` resolver, `:107-108` quota tightens the ceiling; never set in production (FU-B-5, `docs/design/v20_priorities/pr_b_gpu_aggregation_attribution.md:4385`) | unset means *unknown*, not unlimited. If the fleet enforces a per-user quota, export it in MiB in a posture bump — and also `SIDERIUS_GPU_VRAM_QUOTA_GB`, a SECOND reader of the same fact in GiB (`core/runtime_control/probe_subprocess.py:105-124`, capacity-attribution threshold). Two names for one deployment fact: reported to the admission owner (C12-P) |
| `SIDERIUS_GPU_VRAM_QUOTA_GB` | `18` | policy (per-chain, v2 topology) | `core/runtime_control/probe_subprocess.py:105-124` (per-worker capacity-attribution threshold, GiB) | exported = `H100_PER_CHAIN_VRAM_GB` so each of the four co-resident chains attributes capacity against its own 18 GiB slice, not the whole card. Deliberately NOT `SIDERIUS_GPU_VRAM_QUOTA_MIB`: that name is the per-USER total (`pair_admission.py:47-51`) — wiring 18 there would cap the whole card at 18 GiB and refuse every chain (named mis-wire hazard, posture v2 comment) |
| `--trial_vram_budget_gb` | `18` | hardware-derived: 0.80 × 80 GB nominal | `workflows/run_config.py:98`, `sdsc_submission_scripts/run_one_iteration.py:1344-1349`, `_chain_common.sh:105,338`; effective cap `wrapper.py:651-656` and `isolated_probe.py:230-245` = `min(budget, 0.80 × total)`, regimes `wrapper.py:662-669` | the per-attempt VRAM ceiling for trial rounds. A budget above the physical cap is a PHYSICAL VETO down to that cap, never up — so 64 can never exceed the safety ceiling; if the measured `usable_cap_gb` is below 64 the recorded `memory.vram_budget_gb` will show the physical cap instead. The launchers' 12 (`launch_v20_campaign.sh:185-186`, `v19_*`) and 16 (`launch_v18_wave1.sh:158`, `v18r_queue_runner.sh:73-74`, "sized for the H100 80GB box" — for a PAIR) were pair-topology values |
| `--formal_vram_budget_gb` | `18` | hardware-derived: 0.80 × 80 GB nominal | `workflows/run_config.py:99`, `run_one_iteration.py:1350-1355`, `_chain_common.sh:106,339` | same cap for formal rounds; each chain owns an 18 GiB slice of the card in both modes (v2 four-chain topology) |
| `--gpu_pair_ceiling_gib` | `72` | hardware-derived (same value as the exported ceiling) | `run_one_iteration.py:1334-1343`, `_chain_common.sh:104,337`, `HyperparamTuningInput.gpu_pair_ceiling_gib` (`agent/schemas/hyperparam_tuning.py:1987-1996`); read by the tuner's pre-phase admission at `nodes/ml_hyperparameter_tune_agent/runtime.py:266,323-331` | the flag is the value in the run's RECORDED input and the one pre-phase admission actually uses (`ceiling_gib` and `vram_cap_mib` both derive from it); the env var is consulted only when the flag is absent. Shipping both keeps the pair-admission CLI and the tuner on one number |
| `--gpu_admission_enforcement` | `enforce_resource_limits` | policy (V20 production posture, M5) | `run_one_iteration.py:1317-1333`, `_chain_common.sh:103,336`, `launch_v20_campaign.sh:188-189`, `hyperparam_tuning.py:1972-1985` | a resource verdict (`insufficient_headroom`) stops the phase and records an evidence gap; `observe_only` would record and proceed into the OOM this posture exists to prevent; `enforce` is the validation-harness posture, not a campaign one |
| `--runtime_watchdog` | `on` | policy (V20 posture, carried) | `run_one_iteration.py:1252-1257`, `_chain_common.sh:113,322`, `launch_v20_campaign.sh:179` | deadline-kills a training/inference subprocess group; the floor and factors below are meaningless without it |
| `--runtime_safety_factor` | `1.5` | policy (V18 posture, carried) | `run_one_iteration.py:1258-1264`, `_chain_common.sh:120,329`, `launch_v20_campaign.sh:180` | admission + watchdog deadline multiplier. Not lowered for the H100: the time estimator's learned correction is COLD on a new GPU name (Table 2), so the factors are what protects the first rounds |
| `--runtime_trial_safety_factor` | `3.0` | policy (V18r posture, carried) | `run_one_iteration.py:1265-1271`, `_chain_common.sh:121,330`, `launch_v20_campaign.sh:181` | trial-phase factor; wins over the base factor |
| `--runtime_formal_safety_factor` | `2.25` | policy (V19 posture, carried) | `run_one_iteration.py:1272-1278`, `_chain_common.sh:122,331`, `launch_v20_campaign.sh:182` | formal-phase factor |
| `--runtime_watchdog_safety_factor` | `3.5` | policy ("5090 posture", carried) | `run_one_iteration.py:1279-1286`, `_chain_common.sh:123,332`, `launch_v20_campaign.sh:183` | watchdog-only multiplier (V19 admission/watchdog split) |
| `--runtime_watchdog_floor_seconds` | `120` | policy (V18 posture, carried) | `run_one_iteration.py:1287-1293` (schema default 60), `_chain_common.sh:124,333`, `launch_v20_campaign.sh:184` | deadline floor so a tiny estimate cannot produce a deadline shorter than process start-up |
<!-- h100-posture-table:end -->

### Table 2 — limits that stay in source (H100 disposition)

| limit | source | current value | class | override surface | H100 disposition |
|---|---|---|---|---|---|
| host-RSS ceiling, training child | `core/execution_calibration.py:96-109`; consumer `core/sandbox_executor.py:123-139` | 40 GiB | empirical (`measured`, lilab RTX 5090 host, ~61.8 GiB RAM) | `SIDERIUS_SUBPROCESS_RSS_GB` (global, all roles) | carried unchanged. **MEASURE** host RAM: with FOUR chains per card and *N* cards per host, up to `4 × N × 40 GiB` of training-child VA may coexist (RSS is what matters — see the ~47 GB anon-RSS 4-chain OOM record and the preflight's host-RAM row) — if `free -g` cannot hold `N × (40 + 24 + ~1) + ~4`, the global override is the only knob and it lowers every role |
| host-RSS ceiling, inference child | `core/execution_calibration.py:110-130` | 60 GiB | empirical (`empirical_unverified`) | same | carried unchanged. **Lowering it without re-verifying full-scope baseline inference is a regression** (the value is known-good; its recorded arithmetic is retired) |
| host-RSS ceiling, scoring child | `core/execution_calibration.py:131-143` | 24 GiB | empirical (`incident`, 2026-04-20 OOM-kill at 36.9 GB anon-RSS) | same | carried unchanged (CPU path; VA ≈ RSS) |
| VRAM safety fraction | `core/hardware_context.py:51` `_SAFETY_FRACTION = 0.80`, applied to **TOTAL** memory `:145-152`; effective cap `:162-185` | 0.80 | hardware-derived (fraction) | none at runtime — a code edit plus its regression test; named debt F-12a-G2b (derives from TOTAL, not free) — do not change | 0.80 × the measured total. Nominal 80 GB → 64 GB; **MEASURE** `total_memory` (an "80 GB" H100 reports ≈ 79.6 GiB, so the physical cap is ≈ 63.7 GiB and the 64 GB budget lands in the PHYSICAL VETO regime — harmless by construction). The tuner's log strings still say "free×0.8" (`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:853-862`, `agent/skills/evaluate_vram_skill/skill_config.json:34`, `run_one_iteration.py:1348,1354`); they describe the pre-cap path and are stale, the cap is TOTAL-based |
| pair aggregate ceiling default | `core/runtime_control/pair_admission.py:43-45` `DEFAULT_PAIR_CEILING_GIB = 28.0` | 28 GiB | policy (compatibility default for the 5090 pair; `pr_b_gpu_aggregation_attribution.md:4462`) | `SIDERIUS_PAIR_VRAM_CEILING_GIB`, `--gpu_pair_ceiling_gib` | overridden to 64 by the posture (Table 1). Left alone it caps the card at 28 GiB |
| CUDA context / cuDNN workspace constants | `agent/skills/evaluate_vram_skill/overhead.py:50-53` | 185 MB / 50 MB | empirical (RTX 5090, torch 2.10.0+cu128) | none | carried; they feed the STATIC estimate only — admission uses the measured pre-flight peak, not these. **MEASURE** (the H100 context is larger; record the pre-flight's measured peak against the estimate in the pilot report) |
| time calibration `k(gpu_name, model_type)` | `agent/skills/evaluate_time_skill/calibration.py:9-16` (one JSON per GPU name), `:48-51` directory, `:80-99` empty table ⇒ `k = 1.0` | learned | learned | `$SIDERIUS_CALIBRATION_DIR` (default `~/.siderius`) | cold on the H100 — nothing to pre-set; the runtime safety factors carry the first rounds. Point `$SIDERIUS_CALIBRATION_DIR` at a path that persists across jobs (not job-local scratch) so what the pilot learns survives; record the H100 `gpu_name` slug and the resulting table |
| concurrency ceiling | `v20_queue_runner.py:198` `--max_active 2`, `core/campaign/slot_scheduler.py:59`; pair runners `v19_gate0_pair_runner.sh:85-87,148-151,369-375`, `v19_queue_runner.sh:190,546-547,835-836,873`; the FU-B-7 row at `pr_b_gpu_aggregation_attribution.md:4466` cites `MAX_CONC`, which no longer exists (deleted, D-E-3) | 2 per card (pair) | policy (campaign) | the runners' own parameters | NOT USED — concurrency is owned by `launch_band_fleet.sh` (4 band chains per card, `H100_MAX_ACTIVE_PER_CARD=4`) |
| pre-flight worker host-RAM | Table 1 | 24 GiB | policy | `SIDERIUS_PREFLIGHT_WORKER_MEM_GIB` | see Table 1 |
| baseline-harness prompt literal | `scripts/run_comparison.py:688,1518` — "RTX 5090 (32GB VRAM) … 10GB" | prose | hardcoded (tuner-only baseline harness, not the chain) | none | stale on the H100 and **not edited here** (two active branches touch that file). The chain path never reads it; a standalone `run_comparison.py` baseline on the H100 would tell the planner the wrong card |
| per-user VRAM quota | Table 1 | unset | deployment fact | `SIDERIUS_GPU_VRAM_QUOTA_MIB` (+ `SIDERIUS_GPU_VRAM_QUOTA_GB`) | **MEASURE ON THE BOX** |

### How the limits compose at runtime

```text
per-attempt VRAM cap      = min(--{trial,formal}_vram_budget_gb, 0.80 × total)      wrapper.py:651-656
pre-phase GPU admission   : measured training requirement + other occupancy
                            ≤ min(--gpu_pair_ceiling_gib | env | 28.0, measured capacity)   admission.py:485-535
                            (a peak above --gpu_pair_ceiling_gib is STOP_OVER_CAP)          prephase_admission.py:203,248
host RAM per child        : training 40 · inference 60 · scoring 24 GiB, or the global override
pre-flight / measurement worker host RAM: SIDERIUS_PREFLIGHT_WORKER_MEM_GIB
time deadlines            : estimate × factor (trial 3.0 · formal 2.25 · watchdog 3.5), floor 120 s
```

The invariants lock **records** the host-RSS ceilings a run executed under and
never compares them (`core/execution_calibration.py:216-219`), so a workspace
started on the 5090 host resumes legally on an H100 host; the VRAM measurements
do not carry over — a stored RTX 5090 figure is not an H100 figure
(`agent/skills/evaluate_vram_skill/evaluate_vram_skill.md`).

### Pilot acceptance — what "the posture holds" means

| predicate | how to read it |
|---|---|
| zero OOM | no `error_training_oom` / `error_inference_oom` record; no `CUDA out of memory` in any child log |
| zero contention kill | no attempt attributed `gpu_contention` (`core/runtime_control/failure_attribution.py:50,360`); no attempt attributed `gpu_contention` between the four co-resident band chains beyond the probe-measured 4-way factor (`nvidia-smi` shows only this arm's four chains on the card throughout) |
| admission evidence readable | every admitted training attempt's record carries `memory.vram_estimate_gb` and `memory.vram_budget_gb` (`records.py:1290-1291`, the latter = the effective cap, expected 18 under posture v2, or the physical cap); every refusal is a `skipped_resource_admission` or `skipped_infrastructure_failure` record whose `memory.admission_evidence` names the disposition (`runtime.py:341-359`); the pre-phase measurement artifacts sit in `{sandbox}/prephase_measurement/{exp_id}_training.json`. Known gap: the FU-B-17 ceiling triple (`configured_ceiling_gib` / `measured_device_capacity_gib` / `effective_ceiling_gib`, `admission.py:476-492`) reaches a record only on the in-subprocess refusal path (`runtime.py:151-164`), not on the pre-phase refusal path |
| measurements recorded | the MEASURE rows above filled in, then a posture version bump if any value moves |

---

## Next

- [Entrypoints and CLI](../reference/entrypoints.md)
- [Configuration map](../reference/configuration-map.md)
- [Health gates](../concepts/health-gates.md)
