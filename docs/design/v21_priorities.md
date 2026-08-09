# SIDERIUS V21 Priorities

**Status: OPEN, append-only during the V20 campaign.**
Created 2026-08-06 while V20 attempt 2 was running.

## Campaign state this ledger was written against (2026-08-07)

Three V20 launch attempts have been made. **None completed the campaign**, and
no band beyond 15-19 has ever been launched.

```text
attempt 1   SHA d8e21d1a   ABORTED   TypeError: unhashable type: 'list'
                                     agent/prompts.py:361 — fixed by #183
            ws /home/klz/Data/SIDEREIS_DATA/v20/                  EXCLUDED

attempt 2   SHA 0b9ec200   ABORTED   measurement worker CONFIG_REJECTED for
                                     every generated candidate — fixed by #184
            ws .../v20_attempt2_20260806_165521/                  EXCLUDED

attempt 3   SHA aea6d35e   STOPPED   operator_stop_requested, not a defect
            launched 2026-08-06 23:33:59, STOP observed 2026-08-07 06:37:57
            ws .../v20_attempt3_20260806_233242/
            v20_loss_15_19  6 iterations   stopped before iteration 7, EXIT=99
            v20_arch_15_19  4 iterations   stopped before iteration 5, EXIT=99
            chains 3-8 (bands 10-14, 4-9, 0-3) NEVER LAUNCHED
```

Attempt 3 is the only attempt that produced scored records: 38 at the last
audit snapshot (`reports/v20_20260806_233242/v21_scan_latest.json`,
2026-08-07T06:37:24) — 6 `success`, 12 `failed_mode_collapse`, 11
`skipped_infrastructure_failure`, 7 `error_training_oom`, 1 `error_training`,
1 `skipped_oom_risk`. Whether those records are scientifically usable is a
campaign-report question, not a question for this ledger.

P6.3's "three attempts in" and P6.4's OOM observations both come from this
state. Nothing here retires an entry: an aborted or stopped campaign cannot
close a capability gap, only fail to exercise it.

## What this document is

A record of **capability gaps and search-space limitations** exposed by
running V20 — not a design for fixing them, and not a set of scientific
conclusions.

V20 runs its frozen protocol to completion. Nothing here is implemented
mid-campaign, because changing the hypothesis space mid-flight would make
V20's own results incomparable with themselves and turn the experiment
into a moving target.

### The distinction that governs every entry

| class | example | action during V20 |
|---|---|---|
| **infrastructure defect** | `TypeError: unhashable type: 'list'` — a legal candidate cannot execute, and attempts are consumed by a crash | **stop, fix narrowly, restart if scientific state was contaminated** (this is what aborted attempt 1) |
| **capability / search-space limitation** | the system runs exactly as designed, but a scientifically reasonable hypothesis is unreachable | **record here, change nothing** |

The `smooth_l1` finding below is the second kind. The system is not
broken; it is bounded, and the boundary was not deliberately chosen.

### Entry format

Every entry states what was observed, the audited evidence, why nothing
changed during V20, and the question V21 must answer. It does **not**
state the answer — later V20 results may overturn an early reading.

### Two inference errors this document must not make

1. **A later success does not close a capability gap.** If V20 goes
   CE → focal → focal-works-well, that does **not** retire P1. The
   question is never "was `smooth_l1` ultimately necessary?" — it is
   "could the agent explore a legal, scientifically reasonable hypothesis
   on its own?" It could not, whatever wins.
2. **A later failure does not prove the unreachable path would have
   worked.** If focal keeps collapsing, that is **not** evidence that
   regression would have succeeded. V20 never tested regression.

Record capability gaps. Do not pre-announce scientific answers.

---

## P1 — The regression hypothesis space is artificially closed

**Observed in V20.** `v20_arch_15_19` iteration 1 round 1: a 24-block CE
WaveNet control collapsed — `unique_int8 = 4` on every file 15-19 against
a threshold of 25 — and the blocking HealthGate invalidated the round
(`failed_mode_collapse`, recorded score 0.9165).

**Evidence.** The paper's FCNet baseline, which this campaign is trying to
beat, uses **`smooth_l1` waveform regression**
(`ml_models/legacy_baseline_configs.json`). Auditing whether a V20
candidate could reach that:

```python
# ml_models/models_format_sandbox.py:374
def check_compatibility(self, model_type: str):
    if self.loss_type == "smooth_l1" and model_type != "fcnet":
        raise ValueError(
            f"Incompatible Pair: 'smooth_l1' is for waveform regression (AE/fcnet). "
            f"Model '{model_type}' is a classifier and requires 'ce' or 'focal'."
        )
```

The gate is a **string equality against the literal `"fcnet"`**. Every
agent-generated model has a generated name, so the condition is always
true and `smooth_l1` is always rejected.

Every other layer already supports regression:

| layer | state |
|---|---|
| `PLUGIN_OUTPUT_TYPE` | accepts `"classifier"` and `"regressor"`; the validator checks 3-dim vs 2-dim output (`ml_code_validator_agent.py:359-377`) |
| `LossConfig.loss_type` | `Literal["focal", "focal_cw", "ce", "smooth_l1", "custom"]` |
| target dtype resolution | `smooth_l1 → torch.float32` (regression head), implemented |
| proposer prompt | **offers** `smooth_l1` as a Branch-A option (`proposing_stage.md:65, 71, 147`) |

So the agent may *propose* `smooth_l1`, the schema accepts it, the loss
layer implements it — and execution rejects it on a model-name literal.

> ### Correction, 2026-08-07 — the root-cause attribution above is wrong
>
> **The conclusion stands; the causal explanation does not.** Regression
> remains unreachable for agent-generated models, but not for the reason
> given above. Audited during PR A scoping:
>
> **1. The cited gate is not production-reachable.**
> `LossConfig.check_compatibility` (`models_format_sandbox.py:372`) has
> **zero production callers** — only its own definition and one unit test
> (`tests/unit/ml_models/test_loss_functions.py:279`). Its docstring
> claims *"Called by Executor to prevent illegal combinations."* That
> claim is false.
>
> **2. A capability-based contract already exists and is live.**
> `ExperimentConfig.validate_architecture_loss_match`
> (`models_format_sandbox.py:484-515`), constructed in production at
> `core/sandbox_executor.py:1116`, resolves `get_output_type(model_type)`
> from `BUILTIN_OUTPUT_TYPES` / `PLUGIN_OUTPUT_TYPE_REGISTRY` and rejects
> `classifier + smooth_l1` and `regressor + ce/focal`, with `hybrid`
> (fcnet) accepting any loss. `plugin_loader` already reads
> `PLUGIN_OUTPUT_TYPE` from a plugin module (`:81`) and registers it
> (`:151`, `:237`). Verified empirically: after registration,
> `get_output_type("my_generated_regressor")` returns `regressor`.
>
> **3. The real blockers are upstream — metadata that can never be
> produced or validated:**
>
> ```text
> implementor hardcodes PLUGIN_OUTPUT_TYPE = "classifier"
>     (ml_model_implementor.py:264, inside PLUGIN_TEMPLATE)
>   -> no regressor plugin is ever emitted
>   -> and the validator would reject one anyway: the (1,256,64) shape
>      gate (ml_code_validator_agent.py:346-355) runs BEFORE the declared
>      type is read (:359), making the regressor branch (:375) unreachable
>   -> nothing ever registers as "regressor"
>   -> get_output_type falls through to its "classifier" DEFAULT
>   -> the live gate CORRECTLY rejects smooth_l1
> ```
>
> The live gate is not the defect. It is behaving correctly on metadata
> that the producer chain can never generate.
>
> **Consequence for the plan.** PR A is **not** "build a capability
> contract". It is **"make the existing contract reachable"** — a smaller
> and better-targeted change. See Part III PR A.

**V20 consequence.** Non-FCNet regression hypotheses are unreachable. The
agent can discover that CE is wrong (it did, within one round), but it
cannot reach the paper's actual answer. Its only available recovery is
CE → focal, which stays inside the classification family.

**Why not changed during V20.** Opening it mid-campaign changes the
hypothesis space and invalidates the comparison. It is also not a
one-line change: the correct predicate is a capability contract, and that
needs its own design and acceptance.

**V21 question.** Should loss/model compatibility be decided by the
plugin's declared **output contract** rather than its name?

```text
PLUGIN_OUTPUT_TYPE = regressor       -> regression-compatible losses allowed
PLUGIN_OUTPUT_TYPE = classifier      -> classification-compatible losses allowed
```

so that an agent can propose *WaveNet backbone + regression head +
`smooth_l1`* without having to reproduce FCNet.

---

## P2 — The prompt contract also biases the search toward classification

**Observed in V20.** Even with P1 removed, the proposer would still carry
a strong classification prior.

**Evidence.** `docs/design/enable_global_task_config.md` §64-66 already
catalogues the framing the agent receives:

```text
nodes/ml_model_implementor/ml_model_implementor.py:306-322
  "[B, T] int64", "[B, 256, T] float32", "256 denoising classes",
  "nn.Embedding(256, embed_dim)", "Conv1d(channels, 256, 1)"

nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:172-186
  "cross-entropy or focal loss: per-timestep 256-class classification"

agent/prompt_templates/proposal/proposing_stage.md:69-70
  "per-timestep logits over 256 classes"
```

`PLUGIN_OUTPUT_TYPE` also **defaults to `"classifier"`**
(`ml_code_validator_agent.py:359`), so a plugin that says nothing is a
classifier.

**V20 consequence.** The task is described to the agent as a
classification problem. Removing the P1 hard block alone would not
produce regression proposals.

**Why not changed during V20.** Prompt text is scientific policy. Editing
it mid-campaign changes what the agent is asked to solve.

**V21 question.** Should backbone, output representation and loss family
be **independent design dimensions** rather than one fused contract?
The same WaveNet backbone should be explorable as:

```text
WaveNet + classification + CE
WaveNet + classification + focal
WaveNet + regression     + smooth_l1
WaveNet + regression     + custom Huber-like
```

That is architecture/loss co-design; the current framing collapses it to
architecture search under a fixed output contract.

---

## P3 — The 120 s inspection budget may censor large candidates

**Observed in V20 (and V19, and attempt 1).** Attempt 1's very first
attempt ended with:

```text
InconclusivePreflight: VRAM pre-flight did not complete:
the bounded 'batch candidate' step at candidate batch 64
```

**Evidence.** Budgets are `single_candidate_seconds=120`,
`batch_search_seconds=600`, `preflight_total_seconds=1200`
(`agent/skills/evaluate_vram_skill/probe_budgets.py`). A 30-layer WaveNet
at batch 64 exceeded the per-candidate budget twice before V20 launched.

The current behaviour is **honest**: an over-budget inspection *stops*
rather than reporting a capacity verdict, and states explicitly that the
result is not a measurement of the model and not a reason to reduce
capacity. PR #156 made this the behaviour precisely so an inconclusive
inspection cannot teach the planner that large models are unsafe.

**V20 consequence.** A candidate that cannot be *inspected* within 120 s
is never *evaluated*. This is a selection effect on the search space that
correlates with model size — the same size regime FCNet occupies.

**Why not changed during V20.** The budget is part of the frozen posture
and appears in the advice text the agent reads. Raising it mid-campaign
changes both runtime behaviour and the agent's stated constraints.

**V21 question.** Does inspection cost systematically eliminate large
models? Answer with a **deterministic, no-LLM measurement**:

```text
model scale -> inspection wall time -> VRAM probe cost
```

Only then choose between an adaptive budget, a cheaper analytical
pre-flight, staged inspection, or a size-aware budget. **Do not simply
raise 120 to a larger number** — that treats the symptom without knowing
the curve.

---

## P4 — Proposal scale distribution vs the FCNet reference

**Observed in V20 attempt 2**, first iteration, both chains:

| candidate | realized params |
|---|---|
| `wavenet_full_spectrum_ce_control_24b` (arch) | 12,772,096 |
| second arch candidate | 663,488 |
| `wavenet40_ce_fullspectrum_control` (loss) | 8,409,280 |
| **FCNet reference** | **~323,000,000** |

So early V20 proposals sit at roughly **1/25 to 1/500** of the baseline
they are meant to beat. One realized model is under 1 M parameters.

**Evidence of intent to the contrary.** The V20 advice explicitly warns
against this — *"do not systematically undersize models relative to
established baselines"*, *"Exploring roughly the 10M-100M range is
encouraged"*, with FCNet's 323 M and its measured ~6.04 GiB peak quoted
so the agent knows a 323 M model fits inside the 12 GiB cap.

**V20 consequence.** The advice says one thing; the realized proposals
trend smaller. Whether this is the advice being outweighed, or a
downstream constraint (runtime budget, inspection budget, VRAM guidance,
implementor spec-fidelity, planner memory, prior failures) is **not yet
established** — three data points are not a distribution.

**Why not changed during V20.** P2-3 (model-scale trend reporting) is
already classified non-blocking for V20 in `v20_priorities.md` §13.1.
Nothing in the run currently *measures* this, which is itself the gap.

**V21 question.** Instrument the full funnel and quantify the bias:

```text
proposed params -> implemented params -> preflight-rejected params
                -> trained params     -> HealthGate-valid params
```

A systematic downsizing bias should be visible as attrition at a specific
stage, not inferred from anecdote.

---

## P5 — Unregistered inference batch for agent-generated models

**Observed in V20 attempt 2.**

```text
!!! [evaluate_time_skill] model_type 'wavenet_full_spectrum_ce_control_24b'
    has no registered inference batch in core/inference_defaults.py
    — using runtime fallback
```

**Evidence.** `core/inference_defaults.py` registers per-model inference
batch sizes (`wavenet: 25`, `punet: 25`, `fcnet: 25`, `transformer: 1`,
plus a fixed list of previously-generated architectures). An LLM-invented
model is never in that table and falls back to a conservative default.

Measured on the first V20 iteration: `train_time_s 464.0` vs
`inference_time_s 1313.4` — inference cost **2.8×** training. Most of
that gap is explained by workload (training applies `train_portion=0.1`
*on top of* the 0.1 snapshot; inference does not) and by HDF5 I/O, but a
too-small inference batch is a compounding factor.

**V20 consequence.** An efficiency tax on **every novel candidate in all
eight chains** — which is every candidate V20 exists to produce. Scores
are unaffected; only wall-clock and campaign throughput.

**Why not changed during V20.** Inference batch size affects runtime
behaviour for every chain. Changing it mid-campaign alters the frozen
runtime posture.

**V21 question.** Should the inference batch be **derived** from the
candidate's measured memory profile (PR C already measures per-phase
requirements) rather than looked up from a hand-maintained name table
that can never contain a generated model?

---

## P6 — Findings emerging from V20

Append only when supported by concrete campaign evidence. Each entry uses
the format above. Do not record scientific conclusions here — those
belong in the campaign report.

### P6.1 — CE collapse reproduced on a real V20 candidate (2026-08-06)

**Observed.** First scored record of attempt 2:
`wavenet_full_spectrum_ce_control_24b_iter_001_001`, score 0.9165,
`failed_mode_collapse`, `unique_int8 = 4` on all of files 15-19.

**Evidence.** The blocking HealthGate refused it. The reason string
reports the counterfactual: *"score would be 5.5762667 via 2^17 FP
ratio"* — the class-127 phantom, a deterministic floating-point artifact
of a constant output (`execute_tools/scoring_utils.py:195-215`), which
the v17 NaN guard already prevents from entering aggregation.

**V20 interpretation.** Both defences worked: the scoring guard kept the
phantom out of the score, and the blocking gate invalidated the round.
Under V19's observe-only config this round would have resolved
`continue` and entered the record. This is P0-5 closed, demonstrated on
live data.

**Why not changed during V20.** Nothing to change — the mechanism
behaved as designed. Round 1 is the mandatory CE control baseline, and CE
collapse on this class-imbalanced data is anticipated by the advice.

**V21 question.** None yet from this observation alone. It becomes
evidence for P1 only in combination with the audit above: the agent
correctly diagnosed CE as the problem and pivoted to focal, but could not
have pivoted to regression even if it had reasoned its way there.

---

# Part II — Operator research direction for V21

**Operator, 2026-08-06, written while V20 attempt 2 was running.**

These are **hypotheses and candidate designs**, not findings. They are
recorded here so the reasoning survives the campaign, and they are
deliberately kept separate from Part I, which contains only audited
capability gaps.

Nothing here is evidence. V20 has tested none of it — that is precisely
the point of P1: the current system cannot test most of it.

## The central bet: fix the task formulation before scaling the model

The most promising route is **not a bigger WaveNet**. It is getting the
problem statement right.

```text
FCNet            waveform -> waveform regression        SmoothL1
V20 WaveNet      waveform -> 256-class classification   CE / focal
```

For continuous-waveform denoising, the first framing is more plausible.
Classification artificially discretises a continuous amplitude into 256
bins, and the near-zero bin dominates overwhelmingly. That creates a
direct path to the failure V20 is already exhibiting:

```text
predict the few most common bins
  -> CE still decreases
  -> waveform diversity collapses
```

Two collapsed rounds in `v20_arch_15_19` (`unique_int8` 4, then 2) are
consistent with this, though they do not establish it.

## V21-1 — Regression + SmoothL1 for non-FCNet models

The first thing to try is not a 300 M WaveNet. It is the **same
backbone** with the 256-class head replaced by a 1-channel regression
head emitting the waveform directly, trained with SmoothL1.

This admits an unusually clean experiment:

```text
same backbone · same data · same optimizer · same receptive field

A: CE classification
B: focal classification
C: SmoothL1 regression
```

which isolates output/loss formulation from architecture. **C is the
operator's leading hypothesis.**

This depends entirely on Part I P1 being resolved — today the execution
gate refuses `smooth_l1` for anything not literally named `fcnet`.

## V21-2 — Predict the residual, not the waveform

Possibly stronger than direct regression. Given `x = s + n`, do not train

```text
x -> clean s
```

but

```text
x -> predicted noise n̂,   output = x - n̂
```

or a learned correction `output = x + Δ(x)`.

For denoising, **identity is already a strong baseline**. The network
only has to learn what to remove. Consequences:

* whole-signal amplitude collapse becomes much harder;
* an untrained network sitting near identity already emits a sane output;
* the model never has to regenerate the waveform from scratch;
* it suits residual CNN / WaveNet / U-Net backbones naturally;
* SmoothL1 on a residual is a natural fit.

## V21-3 — Restore long context without FCNet's dense layers

FCNet's segment is **40,000**; the V20 WaveNet uses **8,000**.

This may matter a great deal. FCNet's architecture is unsophisticated but
it has one large advantage: it sees the entire 40 k waveform at once. If
the signal or noise carries long-timescale correlation, baseline drift or
low-frequency structure, an 8 k window is missing the information by
construction.

Reaching 40 k does **not** require 323 M dense parameters:

```text
40k input
  -> strided Conv1D / pooling
  -> multi-scale encoder
  -> dilated TCN bottleneck
  -> upsampling + skip connections
  -> 40k regression output
```

i.e. a 1D U-Net / Conv-TasNet-style multiscale regression network.
Receptive field covers the full 40 k while activations and parameters
stay controllable — more promising than simply enlarging the WaveNet.

## V21-4 — Add a spectral constraint, do not replace waveform loss

If the metric is sensitive to spectral structure, pointwise SmoothL1
alone may be insufficient:

```text
L = SmoothL1(time-domain waveform) + λ · spectral loss
```

with a multi-resolution FFT/STFT magnitude difference — short windows for
local/high-frequency structure, long windows for global/low-frequency.

SmoothL1 preserves waveform and amplitude; the spectral term prevents
flattening the spectrum. Both map onto what HealthGate already measures
(amplitude collapse, spectral peak ratio).

Start simple: **SmoothL1 + a small-weight multi-resolution spectral
term.** No perceptual loss initially.

## V21-5 — Optimization budget parity, or the comparison is not about architecture

```text
FCNet       10 epochs, all 20 files
V20 trial    1 epoch,  one 5-file band
```

A candidate collapsing under this budget does not show the architecture
is inadequate — and a classification model given one epoch is especially
prone to remaining stuck in the mode-collapse basin.

To genuinely answer "can this beat FCNet?", a promising candidate must
eventually receive **comparable optimization exposure** — matched
optimizer steps or seen examples rather than necessarily 10 epochs.
Otherwise the comparison measures

```text
architecture + loss + data volume + optimization budget
```

and attributes the result to architecture alone.

## V21-6 — Do not chase 323 M parameters

FCNet and WaveNet have opposite resource profiles:

```text
FCNet     parameter-heavy, activation-light, batch = 1
WaveNet   parameter-light, activation-heavy
          (long sequence x feature maps x many blocks)
```

So "FCNet is 323 M, therefore build a 300 M WaveNet" is a category error
and will likely exhaust VRAM. Explore **10 M / 30 M / 60 M / 100 M**
while recording, for each:

```text
params · peak training VRAM · inspection time · throughput · receptive field
```

A well-designed 30-80 M multiscale regression network could plausibly
outperform a 323 M FCNet. Parameter count alone is the wrong axis — which
is also why Part I P4 asks for the full funnel rather than a single
number.

## The first three V21 candidates, in order

**Candidate A — Residual TCN regression** *(leading bet)*

```text
40k context · multiscale downsampled dilated TCN
regression head · predict noise residual · SmoothL1
```

**Candidate B — 1D U-Net regression**

```text
40k waveform · encoder/downsampling · multi-scale bottleneck
skip connections · decoder · direct clean-waveform regression
SmoothL1 + small spectral loss
```

Possibly better suited to long context than WaveNet.

**Candidate C — Controlled WaveNet ablation** *(highest scientific value)*

Keep V20's WaveNet backbone entirely unchanged. Change only:

```text
classification head -> regression head
CE / focal          -> SmoothL1
```

Because it answers the question V20 cannot:

> Is the collapse a property of the WaveNet **architecture**, or of the
> **classification formulation**?

The operator's current suspicion is the latter.

## V21-7 — Training-data parity may be the largest hidden confound

```text
FCNet   all 20 files
V20     band 15-19 (5 files)
```

If the FCNet reference was trained on all 20 files while a candidate is
permanently restricted to 5, the candidate is at a substantial data
disadvantage before architecture is considered.

**V20 keeps its frozen band protocol** — this is not a mid-campaign
change. But once a V21 architecture looks promising on a band, it
warrants a dedicated **fair full-data confirmation**:

```text
FCNet  vs  new regression model
same 20 files · same evaluation · comparable optimization exposure
```

Only that answers "does the new architecture beat FCNet?"

## The recipe the operator would bet on

```text
40k full context
multi-scale residual 1D Conv / TCN
  -> predict noise residual
  -> SmoothL1 waveform loss + small multi-resolution spectral loss
batch 1-4, gradient accumulation if needed
training exposure comparable to FCNet
```

rather than

```text
a deeper 256-class WaveNet + focal
```

## Why this belongs in the V21 ledger

> **V20's most important contribution may be showing that however
> intelligently the agent optimises inside the classification search
> space, it may never reach a fundamentally better formulation.**

That is a statement about the system's capability, not about which loss
wins — which is exactly what Part I exists to record. The Part I rules
still apply to everything above: if focal eventually succeeds, these
hypotheses are not thereby refuted, and if focal keeps failing, they are
not thereby confirmed. They remain untested until a V21 campaign tests
them.

### P6.2 — Agent-generated models fall outside infrastructure that assumes a fixed model set (2026-08-07)

**Observed.** V20 launch attempt 2 aborted at the formal promotion
boundary. The isolated pre-phase measurement worker returned
`CONFIG_REJECTED: no config class registered for
'wavenet40_ce_fullspectrum_control'` for every agent-generated candidate,
15 consecutive attempts.

**Evidence.** `gpu_measurement_runner.py` spawned the worker with no
`env=`, so it inherited a parent environment that carries no
`SIDERIUS_PLUGIN_DIRS` — that variable is built per-sandbox for the
sandbox's own children. Fixed in PR #184.

**V20 consequence.** None remaining; attempt 3 runs on the fix. But this
is the **second** instance of one pattern, alongside P5:

| | infrastructure that assumes a known model set | effect on a generated model |
|---|---|---|
| P5 | `core/inference_defaults.py` name table | falls back to a conservative inference batch |
| P6.2 | measurement worker's plugin registry | could not resolve it at all |

Both are cases where a component was written when the model set was
fixed and finite, and an agent that invents architectures falls outside
it. P5 degrades performance; P6.2 blocked the campaign.

**Why not changed during V20.** P6.2 was an infrastructure defect and was
fixed. P5 remains an efficiency issue and stays frozen.

**V21 question.** Which other components enumerate model types by name?
An audit of name-keyed registries and lookup tables would find the rest of
this family before a campaign does. The general form: *anything keyed on
a model name is a latent failure for a system whose job is to invent
model names.*

### P6.3 — Proposal scale, three attempts in (2026-08-07)

**Observed.** Realized parameter counts across all V20 attempts on band
15-19:

```text
attempt 1   —
attempt 2   663,488 · 7,280,256 · 8,409,280 · 12,772,096
attempt 3   7,280,256 (x3) · 8,409,280 (x4)
```

**Evidence.** FCNet's reference is ~323,000,000. Every realized V20
candidate so far sits between **25x and 487x smaller**, despite advice
that explicitly encourages the 10M-100M range and states that a 323M
model fits inside the 12 GiB cap (measured at ~6.04 GiB peak).

**V20 interpretation.** Suggestive, not established. All observations come
from one band and the first iteration of each attempt, and the LLM
proposes different architectures each time. What *is* notable is that the
distribution has not once reached the encouraged range across three
independent campaign starts.

**Why not changed during V20.** P2-3 (model-scale trend reporting) is
classified non-blocking in `v20_priorities.md` §13.1, and nothing in the
run measures the funnel — which is the gap itself.

**V21 question.** Unchanged from P4: instrument
`proposed -> implemented -> preflight-rejected -> trained -> valid` and
locate the attrition, rather than inferring a bias from realized counts.

### P6.4 — Two concurrent chains can exceed the card (2026-08-07)

**Observed.** Attempt 3, three OOMs in the first 34 minutes across both
chains.

**Evidence.** The arch chain's candidate held **20.13 GiB** (18.79 GiB
PyTorch-allocated) and the loss chain's **13.45 GiB** — together ~33.6 GiB
against a 31.34 GiB card. A 250 MiB allocation then failed with 9.49 GiB
nominally free, i.e. fragmentation on top of genuine pressure.

Attribution is correct: these are real candidate allocations, not the V19
contention mis-attribution. Recording it because the *first* reading of
the message was wrong — "Process X has 1.43 GiB memory in use" is the
NON-PyTorch portion, and taken alone it makes a genuine OOM look like a
phantom one.

**V20 interpretation.** An operational consequence of `max_active = 2`
meeting candidates that individually approach the card. Both exceeded the
12 GiB per-chain VRAM budget during training.

**Why not changed during V20.** The concurrency policy and the VRAM budget
are both frozen.

**V21 question.** Is `--trial_vram_budget_gb` enforced during training, or
only consulted at admission? A candidate that is admitted under a 12 GiB
budget and then allocates 20 GiB has escaped the budget it was admitted
under — which is the same class as the V19 finding that an admission
estimate does not bound driver-visible reserved memory.

### P6.5 — A candidate score concentrated in one file, verified conformant (2026-08-07)

**This entry is not a metric-redesign proposal.** The metric is part of
the task definition. It is frozen for V20 and the operator has ruled that
it stays frozen for V21 as well: a result that looks strange is audited
for *how it was produced*, never used as an argument to change the
scorer. Everything below is an observation about one candidate under the
fixed metric, plus the conformance audit that established the score is
real.

**Observed.** `wavenet40_progressive_hardness_ce_control_iter_006_001`,
loss chain, band 15-19, trial round: `denoising_score = 10.708207242030124`
— a HealthGate-valid trial score, higher than FCNet's 6.9836 on the same
band, and the highest V20 has produced.

**The by-file structure.**

```text
 file       linear ratio   log_5.27   GT ceiling    % of band sum
   15              32.53     2.0952     10.3205           0.0000%
   16             345.87     3.5174     10.7090           0.0001%
   17           1,367.91     4.3447     11.2213           0.0005%
   18           2,321.08     4.6628     11.0215           0.0009%
   19     268,077,936.73    11.6766     10.5676          99.9985%
```

File 19 supplies 99.9985% of the linear sum. Within file 19, 3 of 20
sampled segments supply ~38% each; the other 17 contribute
`171`–`3,921` against those segments' `~2.5e9`.

**Why the aggregate behaves this way.** The frozen aggregation is
sum-in-linear-space, then a single `log_5.27`
(`scoring_utils.py:640-655`). Linear summation is dominated by its
largest term. This is the specified behaviour, not a deviation from it.

**Why the score exceeds the per-file ceiling.** The per-segment quantity
is `(snr_gt / s_max) * snr_denoised` (`scoring_utils.py:641`). It is
unbounded in `snr_denoised`. The "ground-truth ceiling" is the value
obtained when the denoised channel *equals* ground truth
(`scripts/compute_ground_truth.py:83`, `anchor²/s_max`) — a reference
point, **not a cap the scorer applies**. A prediction whose power at the
matched-filter bin exceeds ground truth's scores above it. Arithmetically
ordinary; no invariant is violated.

**Conformance audit (the only question that was open).**

| checked | method | result |
|---|---|---|
| file identity | `_denoised_fn(fi)` → `..._{file_index:04d}.h5` vs reference `abra_validation_{file_index:04d}.h5` | same key — conformant |
| reference channel | `_collect_raw_pairs` reads CH2 of the raw validation file | conformant |
| decoding | `argmax(dim=1) - 128` (`inference_single.py:256,269`) | conformant |
| index alignment | writer iterates `for psd_idx in psd_segment_indices`; scorer reads `enumerate(segment_indices)` — same list, same order, per file | conformant |
| normalization | trial `s_max` vs `segment_anchors.json` / ground-truth files: `295715680.14248306` | identical |
| aggregation + log | independent reimplementation of PSD → SNR → `(sg/s_max)*sq` → sum → `log_5.27` | reproduces the recorded value |
| scorer vs spec | `tests/unit/nodes/test_scoring_reference.py`, `test_scoring_helpers.py`, plus scorer-wide selection | 146 passed, 2 xfailed |

An independent reproduction from the surviving checkpoint (unseeded
sampling, so different segments) produced a file-19 mean of
**333,076,428** against the recorded **268,077,936** — same mechanism,
same order of magnitude.

**Verdict: `10.7082` is correctly computed under the frozen scorer.** It
is a real trial score. No implementation defect was found in file
identity, reference selection, decoding, alignment, normalization,
aggregation or the log transform.

**What the prediction actually is.** Recorded because it is what makes
the score interpretable, not because it implicates the metric:

```text
corr(denoised, ground_truth) : 0.000056, 0.000001, -0.000895, -0.000902
all-zeros input   -> uniq=111  std=52.116  range=[-74,73]
uniform-random    -> uniq=123  std=52.091  range=[-74,73]
                     (first 24 samples differ in 2 of 24 positions)
```

The output is near-independent of the input and carries a fixed spectral
line at 3,700,000 Hz with power `1.3252e+02`, identical to five
significant figures in every segment examined. The scorer measures the
denoised SNR at the *ground-truth* peak frequency. When the injected
signal sits at 3.7 MHz — one of the discrete TIDMAD frequencies present
in this band — the matched-filter bin lands on that line and the signal
term rises from `1.15e-04` to `1.3252e+02`. The noise window is
`~2.4e-08` in exploding and non-exploding segments alike, so this is a
signal-bin effect, not noise collapse, and the v17 subnormal guard
(`noise <= 1e-10`, written for class-127) does not apply.

Files 15-18 score 2.10-4.66 because their bands never contain 3.7 MHz.
The bimodality is fully explained by frequency coincidence.

**Why nothing changed during V20.** The metric is the task definition.
Changing aggregation, clipping a file, switching to a median, reweighting
files, adding a per-file penalty or altering normalization would change
the benchmark and destroy comparability with FCNet, with the published
TIDMAD numbers, and with every prior SIDERIUS campaign. None of that is
on the table. The candidate was likewise not tuned toward this behaviour.

**V21 question.** Not "how should the metric be fixed" — it should not
be. The open questions are:

1. Does the same concentration appear in other V20 trial scores, or is
   `iter_006` isolated? (Per-file contribution is already recorded in
   `file_vector`; it has never been summarized.)
2. Would a formal round — full segment coverage rather than a 10%
   snapshot — reproduce `10.7082`? The infrastructure defect meant this
   candidate never reached formal, so it is untested.
3. The per-file ceiling is computed over all 200 segments while a trial
   score samples 20. Any per-file comparison between the two is
   **not same-sample**, and past reporting has not said so. A
   same-sample ceiling is a reporting improvement, not a metric change.
4. Should the reflector see per-file contribution alongside the scalar?
   The `iter_006` reflection recorded *"a usable non-collapsed WaveNet40
   output"* from a scalar whose per-file vector shows otherwise. This is
   a question about what evidence the agent is shown — it changes no
   score.

---

# Part III — V21 execution plan (PR division, requirements, validation)

**Operator triage, 2026-08-07.** Sections P1-P6 above record what running
V20 exposed. They are **not** a uniform "fix before V21" list: they mix
capability blockers, runtime-reliability defects, and research questions
that must be measured before anything is changed. This section performs
that split and translates only the first class into reviewable PRs.

**This section authorizes no implementation.** It defines how each PR
must be audited, built, validated and merged.

## E.1 Triage

| Tier | Items | Action before V21 |
|---|---|---|
| **LAUNCH BLOCKER** | P1 + P2, P6.4, P6.2 family | V21 cannot start — PRs A, B, C |
| **BEFORE V21** | P6.5 (evidence only) | Not a hard blocker, but done first — PR D |
| **BEFORE FIRST V21 DATA** | P4 instrumentation | Observability prerequisite: without it the first results cannot be interpreted — PR E |
| **MEASURE FIRST** | P3, P4/P6.3 downsizing funnel | Instrument and measure; **do not tune** — PR F |
| **NICE TO FIX** | P5 | Real design debt, not a launch blocker — PR G |
| **V21 SCIENCE** | Part II candidates (V21-1 … V21-7) | Hypotheses to test, **not** infrastructure prerequisites |

The governing judgement: **V21 must not begin by adding more models. It
must begin by making the hypothesis space the agent can explore real,
symmetric and executable.** P1 + P2 is the highest-priority item in this
document.

Part II candidates are deliberately excluded from this plan. They are
what V21 *studies*; implementing A/B/C simultaneously would repeat V20's
error of changing several variables at once.

## E.2 Planning principles

Inherited verbatim from `v20_priorities.md` §20.1 and binding here:
gradual genericization (§1.4), minimal change, **one causal problem per
PR**, evidence before expansion, a per-PR design document reviewed and
operator-approved **before implementation**, and the **reachability
requirement** — every production feature ships with a test proving the
production call path reaches it.

Per-PR documents live in `docs/design/v21_priorities/`.

### Binding principle 1 — gradual genericization

**Operator decision, 2026-08-01, carried forward from
`v20_priorities.md` §1.4 and binding on every V21 PR.** This is not
background. It is a design, scope, review and acceptance constraint.

**Direction.** Reshape SIDERIUS from a TIDMAD-only repository into a
generic framework that can accommodate different datasets, scientific
tasks, metrics, execution environments and hardware configurations. This
happens by gradually separating TIDMAD-specific behaviour from generic
infrastructure and moving task-specific behaviour into explicit,
replaceable components.

**Mechanism — in-passing refactoring, never a big-bang rewrite.**
Whenever a module is touched for new development, that PR must also move
the touched surface toward the generic design **where doing so is
reasonably bounded and directly related to the touched code**. There is
no repository-wide mega-refactor PR. Genericization rides the normal
development ladder.

The standing review question for every PR:

> **Does the code this change touches still treat TIDMAD, the current
> task, or the current machine as the framework itself? If so, can that
> be moved outside the configuration or plugin boundary within this
> PR's reasonable scope?**

**V21 note.** PR A is the sharpest instance in this plan: the output
contract, the class count and the loss family are exactly the place
where the current task is currently *the framework*. But "reasonably
bounded" governs — see PR A's scope note on `num_classes`.

### Binding principle 2 — complete transport contract (V21 upgrade)

V20's reachability requirement was necessary and **not sufficient**. It
was satisfied, and the campaign still died twice at a process boundary.

> **Every V21 capability that crosses a schema, artifact, CLI, environment
> or subprocess boundary must declare and test its complete transport
> contract. Parent-process reachability is never evidence of subprocess
> reachability.**

Each such capability declares the full chain, and every hop is tested:

```text
producer
  -> typed schema
  -> caller
  -> CLI / env / subprocess boundary
  -> child reconstruction
  -> record
  -> artifact
  -> real production consumer
```

For a generated model specifically:

```text
generated plugin
  -> plugin dir
  -> worker spec
  -> subprocess env
  -> child import
  -> registry reconstruction
  -> config lookup
  -> measurement executor
```

**Testing that the environment variable arrives is not testing the
contract.** The V20 evidence is exact: PR #184 delivered
`SIDERIUS_PLUGIN_DIRS` to the worker and its tests proved a clean
subprocess *could* resolve the plugin — but the worker's own validation
path never imported the module whose import populates the registry, so
`get_config_class` returned `None` for every generated model and the
attempt produced 0 formal records. Closed only by PR #185 (`996a52ef`),
whose test calls the function the worker actually calls. Its docstring
states the rule: *"Both are required; neither implies the other."*

Corollary, binding on every PR below: a transport test must **fail when
any single hop is removed**, and a child process must never be permitted
to satisfy a test using an in-memory registry inherited from the parent.

### Binding principle 3 — the metric is frozen

> **The metric is frozen.** No PR in this plan may change the score
> formula, aggregation, normalization, anchoring or weighting. `10.7082`
> was proven correctly computed under the frozen scorer (P6.5). A result
> that looks strange is audited for *how it was produced* — never used
> as an argument to change the scorer. PR D changes **what the agent is
> shown**, nothing else.

## E.3 PR overview

The three blocking PRs answer three different questions, and the search
space the operator wants exists only when all three hold:

```text
PR A   "I can invent both kinds of model correctly."
PR C   "Anything I invent can execute everywhere it needs to."
PR B   "If it executes, resource control remains correct."
```

| PR | Title | Fixes | Depends on | Gate |
|---|---|---|---|---|
| **A** | Make the existing output contract reachable | P1 + P2 | none | **DELIVERED `0c4eb33e`** — awaiting merge |
| **B** | Resource-budget semantics and enforcement | P6.4 | none | **V21 launch blocker** |
| **C** | Generated-model production compatibility | P6.2 family | none | **V21 launch blocker** |
| **D** | Per-file evidence to reflector and planner | P6.5 | none | Before V21 |
| **E** | Proposal-scale funnel instrumentation | P4 | none | Before first V21 data |
| **F** | Inspection-cost scaling study (**measure only**) | P3 | E | Blocks only a **budget change** |
| **G** | Capability-derived inference batch | P5 | B | Non-blocking |

---

## E.3b Follow-up register — open items PR A deliberately deferred

Every item below was found and deferred **during PR A**, each with a
stated reason for being non-blocking. They are recorded here, not only in
the PR A document, so a later PR planning against this ledger sees them.

| ID | Item | Owner | Why deferred | Blocking? |
|---|---|---|---|---|
| **FU-A-1** | The validator's shape probe keeps the literal `256`. `configs/task_config.yaml:25` already declares `num_classes`, but it is consumed only for prompt rendering; the validator holds no task config and its caller passes only a file path | task-config genericization (`enable_global_task_config.md` § T2 territory) | Wiring it needs a **new transport**, not one existing typed boundary — the A2 conditional rule's "otherwise" branch | No |
| **FU-A-2** | `docs/design/enable_loss_inventory.md:559,576,605` still describes `check_compatibility`, deleted in A1 | doc hygiene | It is a *completed historical* design record. Historical records are not rewritten; `ml_models/` itself carries no stale reference | No |
| **FU-A-3** | A4's prompt token delta was never measured | prompt-budget work | ~20 lines added against prompts already 5-7k chars in the Gate logs; no Gate showed prompt-size trouble | No |

### Findings PR C produced for OTHER PRs — assigned at merge, 2026-08-08

| finding | routed to | reason |
|---|---|---|
| **FU-C-1** — `TransformerConfig` declares `nhead=4` but the estimator falls back to `2`, under-counting attention memory ~2x whenever the config dict omits the key (train 536,592,000 → 1,048,592,000 bytes at C3's parity shape) | **PR B**, as sub-item **B-2** | *Resource-estimation / admission correctness*, not throughput: `wrong estimate → admission too optimistic → possible OOM`. **Not PR G.** Not reopened in PR C either — C3's parity claim is that built-ins are byte-identical, and `2 → 4` would force that claim to be redefined. Currently **pinned by test** so it cannot drift |
| **Authority stamp never reaches the record** — CLI `--healthgate_mode blocking --result_authority diagnostic`, record stamps `null / null → legacy_authority_unknown`, `authoritative: false` | **PR D** (its existing owner) — and **promoted to a V21 scientific-campaign LAUNCH BLOCKER** | **Two independent observations** now (PR A Gate 2C, PR C C5b), so this is causal evidence rather than an artifact oddity. Without it, a formal round that runs correctly still produces a record whose authority is unknown, breaking incumbent-selection and aggregation semantics downstream. That is more than the ordinary observability improvement PR D was scoped as |
| `inference_batch_for`'s actual batch selection | **PR G** | Inference **throughput only**, confirmed by C3b's audit: planning and runtime call the same function, so the forecast never diverges from what runs |
| **No mechanical guardrail exists** for the import-side-effect defect class | none — recorded | Deciding statically whether a registry read is reachable without its populating import is a whole-program reachability question over lazy imports. Stated rather than faked; enforced by C4's real-subprocess fixture instead |

### Findings PR A produced for OTHER PRs — recorded, not absorbed

| Finding | Owner | Detail |
|---|---|---|
| `get_output_type` returns `"classifier"` for an unregistered model, so a **registration failure silently acquires classifier semantics** | **PR C** | Confirmed live in `test_registry_default_would_hide_a_dropped_declaration`. This is why PR A asserts its transport hop by hop rather than end to end only — a dropped declaration does not raise |
| **V20's `CONFIG_REJECTED` defect is genuinely CLOSED** | **PR C** | Verified during Gate 2: with `SIDERIUS_PLUGIN_DIRS` set, a generated plugin resolves in a clean subprocess (`get_config_class` returns its class). PR #185's fix holds. **`STOP_INFRASTRUCTURE_FAILURE` has multiple causes** — do not re-chase a fixed bug on the signature alone |
| Generated models have **no `core/inference_defaults.py` entry**, so inference batch falls back to 25 and the wall-time estimate is uncalibrated | **PR G** (P5) | Observed live in Gate 2C/2R, correctly reported as best-effort rather than silently guessed |
| The iteration **manifest** carries the declared `healthgate_mode` / `result_authority`, but the tuner's per-experiment record stamps `scientific_authority` with `None/None` → `legacy_authority_unknown` | **PR D** | Declaration reaches the manifest, not the record stamp. Does not affect PR A's boundary. Observed at `gate2c_ws3/iter_001` |
| `max_active` bounds chains, not GPU phases | **PR B** (P6.4) | PR A ran its Gates **sequentially** for this reason; it did not test concurrency |

## E.3c Q-B-1 FROZEN — resource-budget semantics, operator decision 2026-08-08

Recorded here because it governs more than PR B: every future consumer of
`vram_budget_gb` inherits it. Full reasoning and the evidence it rests on
are in `v21_priorities/pr_b_resource_budget_semantics.md` (§B0.E).

> **Q-B-1 FROZEN — S3. `vram_budget_gb` denotes an admission threshold,
> not a guaranteed production runtime usage cap. Admission may enforce the
> threshold against the strongest available candidate-specific pre-phase
> evidence, including a forecast or a bounded measured probe. After
> admission, realized threshold exceedance is recorded and surfaced as an
> operator-visible escalation, but exceedance alone does not automatically
> terminate the phase, invalidate the scientific result, or alter the
> score. Peer usage remains context, never candidate evidence.**

What this settles, and what it deliberately does not:

| | |
|---|---|
| **Settled** | The threshold is an *admission* concept. A bounded pre-phase probe exceeding it may still refuse admission — that is admission acting on measured evidence, not runtime hard-cap enforcement |
| **Settled** | `evaluate_vram_skill` (forecast) and `isolated_probe` (measured) are **not** rival semantics; they are one rule over two grades of evidence |
| **Settled** | After admission: record + expose. Never auto-kill, auto-invalidate or rescore on exceedance alone |
| **NOT settled** | The escalation *mechanism*. It remains an output of PR B's B3 audit — freezing the semantics authorises no watchdog, kill path or flag |
| **NOT settled** | Any upgrade to S2. Available later **with evidence**, once B2's telemetry has produced a real exceedance distribution |

**PR B merged 2026-08-08** — PR #188, merge commit `0aae3f4b`, CI green
on `a3d88b51`. Operator classification of its follow-ups, none blocking:
**FU-B-1** delegation cleanup (not a correctness gap — parity-pinned);
**FU-B-2** typed `cap_note`, tracked; **FU-B-3** `reset_process_peak`
audit; **FU-B-4** live formal confirmation, due before the first full V21
production campaign.

Two findings promoted out of PR B by this decision:

| Finding | Owner | Detail |
|---|---|---|
| An omitted `epochs` **defeats the `--max_epochs` hard bound** — `tuner:4052` reads `.get("epochs", 1)` before the clamp while the trainer's `TrainConfig(**t_data)` yields `10`, so a plan omitting the key trains 10 epochs under `--max_epochs 1` | **PR B / B1b** (approved 2026-08-08) | Violates "the harness owns the bounds, not the planner". Fixed on the *resolved* configuration, with the effective value reaching the trainer — not only the clamp |
| **No realized-vs-admitted distribution exists**, and none can be reconstructed from V20 | **PR B → V21 campaign** | Zero observations, because no telemetry existed before B2. Any future budget-policy argument must cite post-B2 data, not the three V20 OOMs |

## PR A — Make the existing output contract reachable

> ## STATUS: MERGED 2026-08-08 — PR #186, merge commit `b9f88ae5`
>
> Operator-merged from `feat/pr-a-reachable-output-contract` (validated
> head `0c4eb33e`, final PR head `88aafd8b`, production tree
> `79d7071ab68c9d84`); CI SUCCESS on the merge commit. Full record:
> [`v21_priorities/pr_a_reachable_output_contract.md`](./v21_priorities/pr_a_reachable_output_contract.md).
>
> ### What PR A actually did
>
> An agent can now propose, implement, validate, register and **execute**
> either formulation, and the choice is a declared field rather than an
> assumption:
>
> ```text
> proposal.output_type : Literal["classifier","regressor"]   independent of loss_type
>   -> protocol -> implementor -> generated PLUGIN_OUTPUT_TYPE
>   -> validator (expected shape DERIVED from the declaration)
>   -> plugin registry -> get_output_type
>   -> ONE shared rule: validate_output_loss_compatibility(...)
> ```
>
> | commit | what it changed |
> |---|---|
> | `452b1022` A1 | deleted `LossConfig.check_compatibility` — a name-keyed rule with **zero** production callers whose logic *contradicted* the live one |
> | `5f97984d` A2 | validator reads `PLUGIN_OUTPUT_TYPE` **before** applying a shape expectation (both arms of the old check were dead code) |
> | `625b0159` A2b | the pair rule now governs the **generated-plugin** branch too — `_validate_configs` bypassed `ExperimentConfig`, so the only kind of model the agent invents was governed by no rule at all |
> | `be8d4d46` A3 | explicit typed `output_type` transported proposal → live rule |
> | `a4bede52` A3b | the producer's own smoke check and generated test artifact honour the declaration |
> | `187d02ac` A4b | the proposer is *asked* for `output_type` and the parser *reads* it — **found by Gate 1R** |
> | `3d39dfe7` A4 | proposer-facing contract is symmetric, not classifier-only |
> | `e70a60dd` A3c | VRAM probe target shape follows the contract — **found by Gate 2R** |
>
> ### Proven by real Gates, not only unit tests
>
> ```text
> Gate 1C  real LLM   classifier + focal      -> forward (1,256,64), validator PASS
> Gate 1R  real LLM   regressor  + smooth_l1  -> forward (1,64),     validator PASS
> Gate 2C  real GPU   classifier              -> denoising_score -2.727240835313264
> Gate 2R  real GPU   regressor               -> train+infer+frozen scorer executed,
>                                                file_vector persisted, scalar withheld
>                                                by blocking HealthGate (PASS)
> ```
>
> **The first regression model in SIDERIUS history to traverse the
> production path.** 7892 unit tests pass, 6/6 mutations caught, 82/82
> existing plugins still validate, pyright unchanged at 0 errors.
>
> ### The lesson worth carrying into PR B and PR C
>
> Every deterministic checkpoint was green while **three** consumers still
> treated the classifier contract as universal — the validator (A2), the
> producer's own test artifacts (A3b) and the VRAM probe (A3c). Two of the
> three were found only by running real Gates.
>
> > A rule, a schema or a contract existing in source is not evidence that
> > every production consumer honours it. Audit consumers as consumers, not
> > as prose — and a transport contract must start at the **real producer**,
> > not at the first typed object in the chain.

> **Scope corrected 2026-08-07 after code audit.** This PR was originally
> written as "build a capability-based compatibility contract". That
> contract **already exists and is live**. See the Correction block in
> Part I §P1. The corrected objective is smaller: make the producer chain
> able to emit and validate the metadata the existing contract consumes.

### Objective

Make `backbone`, `output contract` and `loss family` three independent
design dimensions **by making the existing contract reachable**, so a
generated regression model can be emitted, validated, registered, and
accepted by the live gate.

### Confirmed evidence (audited 2026-08-07)

**Already correct, and not to be rebuilt:**

- `ExperimentConfig.validate_architecture_loss_match`
  (`models_format_sandbox.py:484-515`) is the **single live production
  compatibility authority**, constructed at `core/sandbox_executor.py:1116`.
- `plugin_loader` reads `PLUGIN_OUTPUT_TYPE` (`:81`) and registers it
  (`:151`, `:237`); `get_output_type` (`:158`) resolves
  `BUILTIN_OUTPUT_TYPES` → `PLUGIN_OUTPUT_TYPE_REGISTRY`.
- `LossConfig.loss_type` accepts `smooth_l1`; target dtype resolution
  maps `smooth_l1 → float32`; `proposing_stage.md:65` already offers it.

**The three defects this PR fixes:**

1. **Dead, contradictory rule.** `LossConfig.check_compatibility`
   (`models_format_sandbox.py:372`) is a name-literal gate with **zero
   production callers**, whose logic *conflicts* with the live gate (it
   would reject `regressor + smooth_l1`, which the live gate permits) and
   whose docstring falsely claims the Executor calls it. Left in place it
   is an invitation for a future implementer to re-wire the wrong rule.

2. **Producer cannot emit regressor metadata.**
   `ml_model_implementor.py:264` hardcodes
   `PLUGIN_OUTPUT_TYPE = "classifier"` inside `PLUGIN_TEMPLATE` (`:232`,
   applied at `:1220`), and the forward contract is restated as a literal
   at `:259` and `:1726`.

3. **Validator cannot accept regressor metadata.**
   `_check_instantiation_and_gradient`
   (`ml_code_validator_agent.py:313`, called at `:452`) probes with
   `torch.randint(0, 256, (1, 64))` and fails unless
   `out.shape == (1, 256, 64)` (`:346-355`) — **before** the declared
   type is read at `:359`. The `regressor` branch at `:375` is therefore
   unreachable: if the shape gate passes, the output is 3-dim and the
   regressor branch raises "expected 2 dims". **No plugin declaring
   `regressor` can pass validation today.**

### Scope

```text
1. delete dead contradictory LossConfig.check_compatibility (+ its test)
2. validator reads PLUGIN_OUTPUT_TYPE before applying shape expectations
3. classifier fixture [B,256,T] -> PASS   (parity, unchanged behaviour)
4. regressor  fixture [B,T]     -> PASS   (fails on current main)
5. proposal schema carries an EXPLICIT typed output contract
   (Literal["classifier","regressor"]) transported
   proposal -> protocol -> implementor -> generated PLUGIN_OUTPUT_TYPE
            -> validator -> registry -> live gate
6. ExperimentConfig.validate_architecture_loss_match remains the single
   production compatibility authority — unchanged
7. fixed typed regressor proposal + smooth_l1 reaches a scored bounded
   trial (deterministic; the LLM is never the acceptance oracle)
8. scorer untouched
```

**Operator decision, 2026-08-07 — do not infer the output contract from
the loss family.** `smooth_l1 -> regressor` / `ce -> classifier` would
re-couple output representation to loss, relocating the very binding this
PR removes. The two are declared independently and the live gate checks
the pair.

### The real requirement — four layers must agree

Supporting two losses in code is not the goal. The goal is that a
proposal's **scientific intent survives, unaltered, all the way to the
model that actually trains**:

```text
Proposer
  declares three INDEPENDENT dimensions
      backbone     = WaveNet
      output_type  = regressor        <- never inferred from loss
      loss_type    = smooth_l1
  ↓
Implementor
  generates the matching HEAD, not just the metadata
  ↓
Validator
  three separate checks (below)
  ↓
Plugin registry
  records the declared contract
  ↓
ExperimentConfig live compatibility gate
  ↓
training
```

The failure mode this replaces:

```text
agent says regression
  -> implementor silently generates a classifier
  -> validator only accepts classifier shape
  -> runtime sees a classifier
  -> smooth_l1 rejected
```

### Defence in depth — the proposer is not trusted to be correct

The prompt must state the legal combinations plainly:

```text
classifier   output [B,C,T]   losses: ce / focal / focal_cw
regressor    output [B,T]     losses: smooth_l1
```

so the agent proposes legal pairs **by design**. But an LLM may always
err, so legality is **enforced**, never assumed:

```text
Proposer          proposes a legal combination
Validator/runtime GUARANTEES the combination is legal
```

### The validator checks three distinct things

These are different questions and must not be collapsed:

| # | Question | Owner |
|---|---|---|
| 1 | Is the declaration itself legal? (`output_type ∈ {classifier, regressor}`) | validator |
| 2 | Does the built model match **its own declaration**? declared `regressor` must emit `[B,T]`; declared `classifier` must emit `[B,C,T]` | validator |
| 3 | Is the (output contract, loss) **pair** legal? | **existing live gate** — `ExperimentConfig.validate_architecture_loss_match`. Do **not** duplicate this table in the validator |

Check 2 is what catches the dangerous case: `PLUGIN_OUTPUT_TYPE =
"regressor"` on a model whose forward still returns `[B,256,T]`.

### Acceptance — a 2 × production-path matrix, plus negatives

PR A is accepted only if **both** formulations traverse the full
production path from a fixed typed proposal to a scored bounded trial:

```text
PATH 1   backbone=WaveNet  output_type=classifier  loss=focal
PATH 2   backbone=WaveNet  output_type=regressor   loss=smooth_l1

each:  proposal -> implementor -> generated plugin -> validator PASS
       -> registry reports the declared contract -> live gate PASS
       -> bounded scored trial
```

and these are **refused**:

```text
classifier + smooth_l1   REFUSE
regressor  + ce          REFUSE
regressor  + focal       REFUSE
```

Path 1 proves opening regression did not break classification. Path 2
proves regression is genuinely executable rather than merely present in a
schema. The negatives prove the live gate still holds.

**Capability after PR A:**

```text
                 ┌─ classification   CE / focal
any backbone ────┤
                 └─ regression       SmoothL1
```

Full commit-level plan: `v21_priorities/pr_a_reachable_output_contract.md`.

Reorder the validator so the declared contract is read **first** and the
shape probe is derived from it. Make the implementor template and the
proposer prompt state both contracts symmetrically.

**Class count — bounded, not a redesign.** `configs/task_config.yaml:25`
already declares `num_classes: 256`, but it is consumed only for prompt
rendering (`workflows/task_config.py:209`); execution derives the class
count from tensor shape (`inputs.shape[1]`). Wiring the existing field
into the validator's shape probe is therefore **in scope and bounded**.
Introducing a new generic class-count abstraction is **not** — do not
force a class-count redesign in order to obtain regression capability.

### Division of labour with PR C — do not let this PR grow

```text
PR A proves the regression hypothesis is EXPRESSIBLE
       in the agent and runtime contract
PR C proves a novel regression model is EXECUTABLE
       across every production subprocess
```

PR A must not expand into a general infrastructure audit. If a name-keyed
or process-boundary defect is found while doing PR A, record it for PR C
rather than fixing it here.

### Out of scope

Changing the metric; changing FCNet's baseline configuration; adding new
loss implementations; deciding which formulation wins; a generic
class-count redesign; any name-keyed sweep beyond the dead predicate
(that is PR C); **rebuilding the live compatibility gate**; and — by
operator decision, 2026-08-07 — **changing what `get_output_type` does
for an unknown model**. Today it silently defaults to `"classifier"`.
That default should eventually fail closed, but it affects every model
absent from both registries, so the audit and the change belong to
**PR C** (registration integrity), not here.

### Requirements

- The minimum reachable set becomes
  `WaveNet + classifier + CE/focal` **and** `WaveNet + regressor + SmoothL1`.
- No production path decides loss/model compatibility from a model name.
- The proposer prompt presents classification and regression as
  symmetric options, with neither as an unexamined default.

### Validation

- **Deterministic:** a compatibility matrix test over
  `{classifier, regressor} × {ce, focal, smooth_l1}` asserting the
  legal/illegal set, with the name-keyed predicate proven absent by an
  AST/token guardrail (extend
  `tests/unit/guardrails/test_no_model_name_branches.py`).
- **Reachability:** a generated-plugin fixture declaring `regressor` and
  emitting `[B, T]` passes `ml_code_validator_agent` end to end. This
  test **fails on current main** — that is the acceptance signal.
- **Real, bounded:** one cold-start trial round on band 15-19 training a
  regression WaveNet to a scored result. Success = a scored round, not a
  good score.
- **Parity:** an existing FCNet + `smooth_l1` run and a classifier +
  `focal` run produce byte-identical records to pre-PR.

### Merge criteria

All three blocker sites closed; the regressor reachability test passing;
FCNet parity byte-identical; no name-keyed compatibility predicate
remaining in production.

---

## PR B — Resource-budget semantics and enforcement

> ## STATUS: **MERGED** — PR #188, merge commit `0aae3f4b`, 2026-08-08.
>
> Operator serialization **A → C → B → D → E**. All three launch blockers
> are now merged: PR A (`b9f88ae5`), PR C (`cac86c94`), PR B (`0aae3f4b`).
> Full implementation record in
> `docs/design/v21_priorities/pr_b_resource_budget_semantics.md`.
>
> **What PR B established, in the operator's corrected wording:**
>
> > PR B establishes **one evidence-graded S3 resource semantics at
> > admission**; all currently retained comparison paths are
> > **parity-checked** against it. Realized memory is recorded and
> > operator-visible without becoming scientific evidence or an automatic
> > kill signal, and peer usage remains context rather than candidate
> > attribution.
>
> Deliberately *not* "one implementation" — `evaluate_vram_skill` retains
> its own comparison, mechanically pinned by a 7-cell parity test. That
> makes FU-B-1 de-duplication, **not a correctness gap**.
>
> **Delivered**
>
> | Unit | Result |
> |---|---|
> | B1 | Estimator inputs resolve from declarations, not literals (`resolve_model_field` / `resolve_train_field` / `resolve_loss_type`, 8 sites) |
> | B1b | Harness hard bounds apply to the **resolved** configuration — closes the `--max_epochs` bypass and its `max_steps_per_attempt` twin |
> | B2 | Realized memory measured in-subprocess, transported by the existing sidecar, recorded semantics-neutral |
> | B0 | **Q-B-1 FROZEN as S3** (§E.3c) |
> | B3 | Stage A audit → Stage B armed the graded threshold at one site → Stage C operator-visible notice |
> | B4a | Rung 1 deterministic (15 cases); rung 2 **live** on an RTX 5090 |
> | B4b | Rung 3 production edge (12 cases, 3 mutations); **rung 4 NOT RUN, justified** |
>
> **Evidence:** `pytest rc=0`, 8087 passed / 2 skipped / 1 xfailed, clean
> tree; ruff + format clean; pyright 0 errors 4 warnings; CI SUCCESS on
> `a3d88b51`. Mutations: **40 attempted, 39 behaviour-changing → 39
> caught, 1 equivalent → classified.** No scorer, metric or SNR file
> appears anywhere in the diff.
>
> **The audits overturned most of the PR's own premises**, which is where
> its value sits:
>
> | Prior claim | Verdict |
> |---|---|
> | The `segmentation_size` fallback is a 40x *optimistic* under-estimate | **Backwards** — never optimistic; neutral to 40x conservative |
> | FU-C-1 (`nhead` 4→2) is an active admission defect | **Latent** — the analytic VRAM estimator has had no production caller since `8b6c4ba8` |
> | Enforcement enforced a wrong number, so B1 may explain P6.4 | **False for VRAM** — the admission number comes from a probe |
> | The phases record realized peaks but nothing compares them | **Half wrong** — they never measured them |
> | B3 must build an enforcement mechanism | **No** — the graded rule already existed at `decision_policy.py:285` and was inert because nothing populated `budget.vram_gb` |
>
> **Negative findings, recorded so the sweep's completeness is visible:**
> `num_layers`, `batch_size`, `optimizer_type` and the
> `validation_max_portion` clamp were **not** defects.
>
> **Permanent caveat on citing PR B.** No realized-vs-admitted
> distribution exists; zero observations, and V20 cannot be
> reconstructed. PR B delivers the **capability to collect** one.
>
> ```text
> MAY be written    "PR B makes forecast error measurable"
> MUST NOT be       "PR B showed typical forecast error is X%"
> ```
>
> **Follow-ups, none blocking (operator classification 2026-08-08):**
> **FU-B-1** delegate `evaluate_vram_skill` to the shared policy —
> architecture cleanup, not correctness. **FU-B-2** typed `cap_note` —
> tracked; reopens PR B only if threshold correctness changes.
> **FU-B-3** `reset_process_peak()` counter-consumer audit.
> **FU-B-4** live formal confirmation — due **before the first full V21
> production campaign**, or satisfied by an explicitly bounded first run
> that naturally traverses the path, and **never** by adding workload
> until an exceedance appears.
>
> ### PR B gained a second, independent sub-item at PR C's merge
>
> PR B now covers **two** resource-correctness problems. They are related
> in kind and must not be merged into one commit:
>
> ```text
> B-1  budget SEMANTICS      is 12 GiB an enforced cap or an admission
>                            estimate? (the original scope, below)
>
> B-2  FU-C-1                a built-in resource model uses the wrong
>                            fallback, so admission is too optimistic
> ```
>
> ### B-2 — FU-C-1, reassigned from PR C by operator decision 2026-08-08
>
> ```text
> TransformerConfig.nhead = 4
> estimator fallback      = 2      -> attention memory under-counted ~2x
> ```
>
> **Owner: PR B.** Classification: *resource-estimator correctness*. Its
> consequence is not throughput —
>
> ```text
> wrong estimate -> admission too optimistic -> admit -> possible OOM
> ```
>
> — so it is emphatically **not PR G**, and its only relationship to PR C
> is that C3's 18-cell parity capture is what discovered it.
>
> **It was deliberately not fixed inside PR C.** C3's backward-compatibility
> claim is that built-in estimates are byte-identical; changing `2 → 4`
> there would have forced that claim to be redefined mid-PR. The wrong
> value is currently **pinned by a test** asserting `(2, 2)` in
> `tests/unit/agent/test_estimator_predicates_not_names.py`, so it cannot
> drift silently before PR B corrects it — **that test must be updated as
> part of B-2, not deleted.**
>
> **Current state:** a conservative invariant is violated in the
> *optimistic* direction.
>
> **Required audit (before any change):**
>
> - determine the canonical source of `nhead`
> - distinguish an **absent** value from an **explicit override**
> - update the training **and** inference estimators consistently — both
>   read the shared `attention_shape` helper introduced by C3
> - sweep for any **other** config-default vs estimator-fallback mismatch;
>   `nhead` is unlikely to be the only one
>
> **Acceptance:**
>
> - `TransformerConfig` default `nhead=4` → the estimator uses **4**
> - an explicit `nhead=N` → the estimator uses **N**
> - a generated attention model remains **property-derived**, not
>   name-keyed (C3's guarantee must survive)
> - admission becomes **no more optimistic** anywhere; every changed cell
>   is recorded with its before/after value, as C3 did
>
> ### Also inherited from PR C
>
> `max_active` bounds **chains, not GPU phases** — recorded in §E.3b during
> PR A, and the reason PR A and PR C both ran their Gates **sequentially**.
> Neither PR tested concurrency; PR B is where that is answered.

### Objective

Make the VRAM budget mean one stated thing, and make a sustained breach
of it detectable.

### Confirmed evidence

P6.4: attempt 3 observed ~20.13 GiB (arch) and ~13.45 GiB (loss) on a
31.34 GiB card, with three OOMs in 34 minutes, while every chain declared
a 12 GiB budget. `core/runtime_control/pair_admission.py:45` defines
`DEFAULT_PAIR_CEILING_GIB = 28.0` with an env override
(`SIDERIUS_PAIR_VRAM_CEILING_GIB`); `max_active = 2` bounds **chains**,
not GPU phases.

### The question this PR must answer first

Is the per-chain 12 GiB figure an **enforced cap** or an **admission
estimate**? Today it behaves as the latter while being named like the
former. The audit decides which it should be; the PR then makes the name,
the schema field and the runtime behaviour agree.

### Required sequence — no design before the audit

```text
audit semantics
  -> freeze semantics (operator decision, written)
  -> implement enforcement consistent with THAT semantics
```

**This PR must not pre-commit to an enforcement mechanism.** Whether the
answer is dynamic enforcement, a watchdog, re-measurement, pair/aggregate
accounting over concurrent phases, or admission-envelope semantics with
honest reporting is an **output** of the audit, not an input. The plan
deliberately states no preferred mechanism.

### Scope

Unambiguous budget semantics in schema and manifest; detection when
realized phase memory exceeds what was admitted; enforcement consistent
with the frozen semantics.

### Out of scope

Raising or lowering any threshold without measured justification;
changing `max_active` policy before the audit; per-candidate rejection
based on peer pressure (P6.4 is explicit that contention is not candidate
evidence); choosing the enforcement mechanism before the semantics are
frozen.

### Requirements

- A candidate's realized phase memory cannot persistently exceed its
  admitted budget without the system recording it.
- A breach is attributed to the **process that caused it**, never to a
  peer candidate.
- Whatever the chosen semantics, the manifest states it in words.

### Validation

**Escalation ladder — real training is never the discovery tool.** Each
rung must pass before the next is attempted:

```text
1. synthetic accounting        replay attempt-3 numbers, no GPU
2. controlled allocator holder deliberate CUDA reservation, no training
3. production admission path   reachability under the real code path
4. minimal real GPU confirm    smallest run that can demonstrate it
```

- **Rung 1:** synthetic two-chain accounting tests over the observed
  attempt-3 numbers (17.46 + 13.45 GiB, 149 MiB free) asserting the
  intended admit/refuse decision under the frozen semantics.
- **Rung 2:** a controlled process holding a known CUDA reservation —
  no model, no training — confirming detection and attribution.
- **Rung 3:** a test proving the production admission path consults the
  aggregate, failing if a future edit bypasses it.
- **Rung 4:** the **smallest** real co-residency run that demonstrates
  the behaviour. Not two full scientific chains, and not a deliberate
  card-exhaustion campaign.

### Merge criteria

Semantics documented and implemented consistently; breach detected and
correctly attributed in a live two-chain run; no peer-caused rejection.

---

## PR C — Generated-model production compatibility

> ## STATUS: MERGED 2026-08-08 — PR #187, merge commit `cac86c94`
>
> Operator-merged from `feat/pr-c-generated-model-production-compat`
> (validated code head `1bf697bf`, 10 commits); CI *Lint + Type + Unit
> Tests* SUCCESS. Production tree `b079f66539f91560` identical at the
> validated head and on master — every commit after `1bf697bf` was
> documentation only. Full record:
> [`v21_priorities/pr_c_generated_model_production_compat.md`](./v21_priorities/pr_c_generated_model_production_compat.md).
>
> ### What PR C actually did
>
> A generated model no longer depends on any of the four things that
> silently decided its fate:
>
> ```text
> BEFORE                                   AFTER
> a silent output default                  UnknownOutputContractError, C1
> lucky import order                       self-healing lookup, C2
> hardcoded built-in estimator names       model properties, C3
> parent-process registry contamination    real-subprocess proof, C4
>
> and: valid trial winner -> formal plan is mechanically proven, C5a
> ```
>
> | commit | what it changed |
> |---|---|
> | `f16f02fd` C1 | an unestablished contract **fails closed**; five consumers each translate it into their own layer's typed refusal. A *fifth* consumer (`agent/prompts.py`) existed that the first census missed — it was built from the execution path, and prompt rendering is not on it |
> | `6335c7cb` C2 | **#185 never fixed `get_config_class`** — it fixed one *call site*. The function still returned `None` **silently** for a plugin valid on disk (measured 0 of 82 in a clean process). Fixed at the lookup authority; `sandbox_executor`'s two direct reads closed too |
> | `2b53fe8e` C3 | the five estimator name branches are **three different kinds of thing**, and only the `transformer` attention branch ever harmed a generated model — it charged **zero**, the *optimistic* direction. Replaced by declared contract / declared attention params / constructor signature |
> | `5e7365f3` C3b | O-C-2 answered: a missing inference-batch entry is **already harmless** (planning and runtime call the same function; the flag reaches only `warnings`, which nothing branches on). Pinned rather than rewritten |
> | `019f440a` C4 | the transport chain enforced hop by hop in a **real spawned subprocess**, both contracts, with a deletion matrix and a parent-contamination test |
> | `0d5616bf` C5a | the head PR A never exercised, proven **deterministically** — `is_valid_candidate` is a pure predicate, so a valid trial is *constructed*, never trained for |
> | `1bf697bf` C5b | live on RTX 5090: a generated **regressor** measured (1824 MiB), **admitted**, run formally, formal record persisted with `formal_validity: "valid"` |
>
> ### Evidence composition — never claimed as one run
>
> ```text
> C5a   valid trial -> winner -> params inherited      DETERMINISTIC
> C4    novel plugin -> clean subprocess -> resolution REAL SUBPROCESS
> PR A  measurement -> admission -> formal -> record   REAL GPU (classifier)
> C5b   the same tail                                  REAL GPU (regressor)
>
> NOT PROVEN LIVE BY ANY RUN: valid trial -> formal in one execution.
> ```
>
> C5b's real trial **collapsed** (diversity 7, std 0.092 mV). Per the
> operator's rule that is a **scientific outcome, not a PR C failure**, and
> the workload was not changed to obtain a better one.
>
> ### Validation at `1bf697bf`
>
> ```text
> unit suite   7951 passed, 2 skipped, 1 xfailed   (baseline 7892)
> PR C battery   69 passed
> ruff / format  clean / 757 files
> pyright      0 errors, 4 warnings   (unchanged)
> mutations    15 applied / 15 caught
> scorer files 0 changed
> ```
>
> ### The guardrail's "9 violations" were never 9 code branches
>
> It exempted docstrings but scanned `#` comments, so the tracked count
> mixed real branches with prose (`inference_defaults`' two were **both**
> comments). Explaining a removed branch *raised* the count, making "stop
> explaining which model a formula came from" the cheapest way to pass.
> Made precise via `tokenize`. `_PENDING_CLEANUP` is now **empty**, because
> a listed label downgraded a *reintroduced* branch from `failed` to
> `xfail` — the guard detected the regression and then tolerated it.
>
> ### Follow-ups assigned at merge (operator, 2026-08-08)
>
> | finding | owner | why |
> |---|---|---|
> | **FU-C-1** transformer attention under-counted ~2x | **PR B** | It is *resource-estimation / admission correctness*, not throughput, so **not PR G**. Its consequence is `wrong estimate -> admission too optimistic -> possible OOM`. Not reopened in PR C either: C3 proved 18-cell built-in parity, and changing `2 -> 4` now would force that backward-compatibility claim to be redefined |
> | **Authority-stamp defect** | its existing designated follow-up (**PR D**) | Two independent observations now, so this is causal evidence rather than an artifact oddity. Promoted to a **V21 scientific-campaign launch blocker**: without it a correct formal run still stamps `legacy_authority_unknown`, breaking incumbent/aggregation authority semantics downstream |
> | `inference_batch_for` | **PR G** | Inference **throughput only** |
>
> ### The two PRs together
>
> ```text
> PR A   the agent can invent classification AND regression correctly
> PR C   what it invents is a production first-class citizen
> ```

> **Two audit findings that change this section**, both measured at
> `b9f88ae5`:
>
> 1. **Scope (b) needs a different verb than "restore".** PR A's Gate 2C
>    persisted a *formal* record for a generated model
>    (`scientific_authority` present, `is_trial` absent — the stamp is
>    `if not trial_config.is_trial`, `ml_hyperparameter_tune_agent.py:5554`),
>    score `-2.727240835313264`. So measurement → admission → formal →
>    record already works. But it ran on the **planner's unvalidated
>    plan**: the run logged *"no successful trial round is
>    HealthGate-valid in this iteration"* (`:1798`), meaning no trial
>    winner existed. The untested segment is the **head**, `valid trial →
>    winner → formal`, not the tail. Open question **O-C-1**.
>    *(Note for whoever writes the Gate: `[FORMAL OVERRIDE]` is a
>    misnomer — `:1834` prints it on the healthy winner path too. Only
>    the `:1798` WARNING variant is the pathology.)*
> 2. **Scope (a) is far smaller than assumed.** The `get_output_type`
>    fallback has **zero** current dependants: 88 registered models =
>    6 `BUILTIN_OUTPUT_TYPES` + 82 `PLUGIN_OUTPUT_TYPE_REGISTRY`, none
>    relying on `unknown → "classifier"`. Failing closed cannot affect a
>    healthy path; it fires only where registration already failed.
>
> **Inherited from PR A (2026-08-07) — read before scoping.** See the
> follow-up register in §E.3b. Two items land directly here:
>
> 1. `get_output_type` returning `"classifier"` for an unregistered model
>    is now a **demonstrated** silent-default, pinned by a test, not a
>    hypothesis.
> 2. **V20's `CONFIG_REJECTED` defect is CLOSED** — PR A verified a
>    generated plugin resolves in a clean subprocess. Do not re-chase it:
>    `STOP_INFRASTRUCTURE_FAILURE` has several distinct causes, and PR A
>    hit a different one (an unset `data_dir`, correctly refused with
>    *"no silent synthetic fallback"*).
>
> PR A also supplies a reusable pattern for PR C's own Gate: a
> deterministic fixture that writes a generated plugin to disk and drives
> the **real** production path over it, rather than asserting on template
> strings.

### Objective

Find and close the places where infrastructure written for a **fixed
model set** breaks a system whose job is to **invent model names**.

### Confirmed evidence

**The P6.2 defect took two PRs to close, and the first one looked
complete.** This history is the specification for this PR:

```text
#184 (db688c48)  worker spawned without env= -> SIDERIUS_PLUGIN_DIRS absent
                 FIXED THE TRANSPORT. Tests proved a clean subprocess
                 COULD resolve the plugin. Attempt 3 still produced
                 0 formal records.

#185 (996a52ef)  get_config_class reads PLUGIN_CONFIG_REGISTRY, populated
                 as an IMPORT SIDE EFFECT of ml_models.models_sandbox.
                 build_production_components imported it -> resolved
                 validate_candidate_configs did not      -> returned None
                 Two paths in one file, one import apart, disagreeing
                 about whether a model exists.
```

So the environment arrived and **the consumer never used it**. The
generated-model path was closed only when a test called the function the
worker actually calls.

The **pattern** remains live and is already tracked:
`tests/unit/guardrails/test_no_model_name_branches.py` carries **three
xfail groups = nine pending violations** —
`agent/skills/training_skill/estimator.py` (4),
`agent/skills/inference_skill/estimator.py` (3, including
`if model_type == "transformer"`), and `core/inference_defaults.py` (2).

### Scope

A **bounded, targeted** audit of six surfaces: model-name lookup tables;
config registries; inference defaults; hardcoded compatibility
predicates; subprocess plugin loading and environment propagation;
model-specific branching. Close only what makes a generated model
**non-executable**.

Sweep specifically for the `#185` shape — **state reconstructed by import
side effect, where two paths in the same process disagree** — since that
class is invisible to both transport tests and parent-process tests.

**Additionally in scope (operator decision, 2026-08-07):**

**(a) Unknown output type must not silently acquire classifier
semantics.** `get_output_type` (`plugin_loader.py:158`) returns
`"classifier"` for any model in neither registry. That default is exactly
why a *registration failure* is silently converted into *wrong scientific
semantics* rather than an error. The target semantics are:

```text
known classifier  -> classifier
known regressor   -> regressor
unknown           -> explicit unknown / fail closed
```

This PR must **audit before changing**: which built-in or historical
models rely on the fallback; whether legacy artifacts exist with no
registered output type; which subprocess/reload paths can produce
`unknown`; and at which layer `unknown` should be refused. Then implement
the minimal compatible change.

**(b) Restore formal promotion, and prove it.** PR A makes regression
*expressible*; PR C must make a generated model *executable across the
process boundary* — which is what actually blocked formal promotion in
V20 attempt 3. Code that merely looks correct is not evidence. Required:
a **deterministic generated-model fixture** traversing

```text
generated plugin
  -> clean measurement worker
  -> config registration
  -> measurement succeeds
  -> formal phase becomes reachable
```

**No good score and no real training are required** — only that the
formal phase becomes reachable for a generated model.

### What is NOT forbidden

A model name as **identity, logging key, registry key or artifact
provenance** is legitimate and stays. `registry[model_name]` and
`artifact.model_name` are not defects.

What is forbidden is an unknown model name changing **correctness,
reachability or scientific semantics**:

```text
FORBIDDEN   if model_type == "transformer": correctness_behaviour = X
            else:                           correctness_behaviour = Y

FINE        registry[model_name]
            artifact.model_name
```

Throughput-only consequences of a missing name entry belong to PR G, not
here.

### Out of scope

Repository-wide refactor; renaming schemas; rewriting the estimators
beyond removing name-keyed branching; anything that only affects
throughput (that is PR G).

### Requirements

- A newly generated model name reaches every production stage —
  registry, measurement worker, estimators, inference defaults — without
  requiring a pre-registered name entry for **correctness or
  reachability**.
- Each of the nine tracked violations is either closed or carries a
  written follow-up ID with a stated reason.
- The full generated-model transport chain (Binding principle 2) is
  declared and tested hop by hop.

### Validation

- **Deterministic:** the three xfail groups convert to passing, or the
  remainder is explicitly re-scoped in the guardrail with a follow-up ID.
- **Transport, clean subprocess — the primary gate:** a fixture with a
  never-before-seen generated model traverses
  plugin dir → worker spec → subprocess env → child import → registry
  reconstruction → config lookup → measurement executor, **in a real
  spawned subprocess**. Two non-negotiable properties:
  1. the child must **not** be able to satisfy the test using an
     in-memory registry inherited from the parent;
  2. **removing any single hop must fail the test** — including the
     import whose side effect populates the registry.
- **Real, bounded:** one cold-start iteration whose generated name is
  novel, reaching a scored trial round **and** a formal promotion
  boundary (the exact point where attempt 3 died).

### Merge criteria

Clean-subprocess transport test passes and fails on every hop deletion;
novel-name fixture reaches formal promotion; **no unexplained name-keyed
correctness or reachability dependency remains on the generated-model
production path.**

---

## E.3d What A, B and C proved — binding on every remaining PR

Written 2026-08-08, after all three launch blockers merged (`b9f88ae5`,
`cac86c94`, `0aae3f4b`). These are not style notes; each is a defect that
actually shipped and was found by audit.

### E.3d.1 The recurring defect shape: a correct rule that nothing calls

Three PRs, three instances, same shape:

```text
PR A   SIDERIUS_PLUGIN_DIRS reached the subprocess -- which never read it
       (#184, then #185 fixed the call site and left the function)
PR C   get_config_class read a registry nobody had populated
       -> 0 of 82 plugins resolved in a clean subprocess
PR B   RuntimeBudget.vram_gb: declared, evidence-graded, unit-tested,
       and never supplied by any production caller
```

**Every remaining PR must ask, before building: does this already exist
and lie inert?** PR B's Stage A turned a "build an enforcement mechanism"
commit into a one-line wiring change by asking it.

The corollary is PR A's rule, restated: **audit consumers as consumers.**
A rule existing in source is not evidence that any consumer honours it.

### E.3d.2 Establish reachability before calling a defect active

Two findings were downgraded by audit, not by opinion:

- **FU-C-1** (`nhead` 4→2) is arithmetically real and reaches **no
  admission decision** — its only callers are orphaned.
- `inference_batch_uncalibrated` is **observability-only** — every use of
  `warnings` in the runtime package is a producer, none a predicate.

Classify each finding `ACTIVE` / `LATENT` / `NOT A DEFECT` / `UNKNOWN`
with evidence. Do not imply a latent defect caused observed behaviour.

### E.3d.3 A value that is only printed is not evidence

`cap_note` (`wrapper.py:538-545`) computes exactly the three cap regimes
B3 needed — into a **log string**. Same class as PR C's finding that a
guardrail scanned `#` comments as live code. If a fact matters, it must be
typed and persisted, not rendered.

### E.3d.4 Absent, explicit-default, explicit-override and explicit-invalid
are four different states

B1's resolver exists because they were being collapsed. B1b showed the
consequence at a bound: **an omitted key let planner silence decide a
harness-owned bound** — a plan without `epochs` trained ten under
`--max_epochs 1`. An explicitly *invalid* value must not silently become
a fallback either.

### E.3d.5 Observation must be provably decision-free

B2's template, reusable by any PR adding evidence: a typed model,
**semantics-neutral field names** (a test fails on `breach` / `violation`
/ `over_budget`), missing evidence recorded as **unknown rather than
compliant**, attribution to the owning process, and a guard test that
fails if any decision path reads the new field.

### E.3d.6 Do not claim a distribution you have not collected

B0 froze S3 on **zero** realized-vs-admitted observations, and said so.
The capability to measure is not the measurement.

### E.3d.7 Mutation results are reported by category, not as a percentage

```text
N attempted
N-k behaviour-changing -> must all be caught
  k equivalent         -> classified, no missing acceptance signal
```

A surviving mutant is classified (real gap / equivalent / unreachable /
wrong fixture) **before** any test is written for it. Two of PR B's own
mutations turned out invalid — one was semantically equivalent, one
targeted a harness that reimplemented production instead of calling it.

### E.3d.8 Validation hygiene, now in CLAUDE.md

Commit before the full suite (the PR3-L2 preflight refuses uncommitted
production edits, by design), and never take a pytest verdict from a
pipe's exit code.

---

## E.3e Correction, 2026-08-08 — PR D's premise withdrawn after a code-grounded audit

Append-only: nothing below is deleted. P6.5 and the original PR D section
are preserved as the historical record; this block states what a
code-and-artifact audit of `master @ 667ab359` established instead.

**1. The claimed per-file-evidence gap is not real.**
`ScoreComparisonTable` already computes a per-file `linear_weight` and
renders it as a **`Weight %`** column, and `{SCORE_COMPARISON_TABLE}` is
substituted into **both** the planner and reflector prompts. This has been
live since `5c8f76c4` (**2026-05-01**), three months before V20 ran.

```text
file_vector -> build_score_table          execute_tools/scoring_helpers.py:106
            -> PerFileRow.linear_weight   agent/schemas/score_table.py:82
            -> "Weight %" column          scoring_helpers.py:478, :496
            -> {SCORE_COMPARISON_TABLE}   agent/prompts.py:215, :267
            -> planner + reflector        agent/llm_bridge.py:866, :950
```

**2. The cited artifact refutes the causal claim.** The real
`iter_006_001` record carries both `file_vector` and a `score_table`; its
stored `linear_weight` for file 19 is `0.999984827817748`, matching the
ledger's 99.9985% exactly, and its rendered markdown shows file 19 at
`100.0%`. The reflection's "non-collapsed" phrase originates in
`all_records[0].memory.discovery` and is grounded in **per-file** evidence
("unique int8 values stayed high across files 15-19"), while the next
record's hypothesis names **"over-focus risk"** on file 19 and says
improvement "should be judged by both aggregate score and per-file
changes". The agent saw the concentration and reasoned about it.

```text
"per-file evidence was not shown to the agent"   FALSE
"the scalar alone misled the reflector"          NOT SUPPORTED
```

**3. The original PR D causal premise is therefore WITHDRAWN.** This is
not "PR D was partially implemented" — the problem statement was wrong.

**4. The authority-transport defect assigned to PR D is ACTIVE and
launch-blocking, and PR D is re-scoped around it.** Second audit narrowed
it beyond the multi-iteration chain:

```text
run_one_iteration        NO      run_one_iteration.py:1846 (run_workflow)
run_comparison           NO      scripts/run_comparison.py:690
run_exploration_test     NO      run_exploration_test.py:151
model_exploration main   NO      model_exploration.py:2994
bg_admission_validation  NO      scripts/bg_admission_validation.py:571
manual tuner CLI         YES     ml_hyperparameter_tune_agent.py:6722-6723
```

> **No formal record produced through any current SIDERIUS launcher can
> become authoritative, because every production launcher omits
> `healthgate_mode` and `result_authority` when constructing or invoking
> the tuner. The authority mechanism itself is live and correct; only the
> hand-invoked tuner CLI currently supplies it.**

The same defect shape as A/B/C (§E.3d.1): correct mechanism, correct
schema, correct consumer, **nobody on the production path supplies it**.

**5. Frozen-scorer clarification — documentation only, no behaviour
changes.** The production aggregation (`execute_tools/scoring_utils.py:638-655`)
is the **grand mean over sampled segments in linear space, then one
`log_5.27`** — not an unnormalised sum:

```text
v_f    = (1/|S_f|) * Σ_{i∈S_f} (snr_sg[f,i] / s_max) * snr_squid[f,i]      :645-646
score  = log_5.27( Σ_f |S_f|·v_f  /  Σ_f |S_f| )                            :653-655
```

The ledger's "sum-in-linear-space, then a single log" is classified
**IMPRECISE BUT SEMANTICALLY CONSISTENT**: the omitted divisions are
constants that cancel in any contribution ratio, so the 99.9985%
concentration conclusion stands. It would become *incorrect* only if used
to describe the aggregate's magnitude.

**Assumption worth recording permanently** — the displayed share is

```text
linear_weight_f = v_f / Σ_j v_j            scoring_helpers.py:305
```

which equals the true contribution to the pre-log aggregate **only while
every sampled file has the same segment count**. That invariant holds
today (`scoring_helpers.py:258-264` documents it; `iter_006_001` confirms
it empirically), so `99.9985%` is exact. The general form weights by
`|S_f| · v_f`. **This is a genericization assumption to carry forward, not
a reason to touch the frozen metric.**

---

## PR D — Make the existing scientific-authority contract reachable

> **RE-SCOPED 2026-08-08 by operator decision, after the audit in §E.3e.**
> The former scope ("Per-file evidence to reflector and planner") is
> **SUPERSEDED BY AUDIT** and preserved verbatim below for the record.
>
> Naming follows PR A deliberately, because the defect is the same shape:
>
> ```text
> PR A   Make the existing output contract reachable
> PR D   Make the existing scientific-authority contract reachable
> ```

### Objective

Make a launcher's **declared** scientific authority reach the formal
record, so that authority-bearing downstream decisions act on the
declaration instead of on `legacy_authority_unknown`.

**Not** to design authority semantics — `core/scientific_authority.py`
already exists, is correct, and is unit-tested. PR D adds no rule and
changes no verdict table.

### The defect (§E.3e.4)

```text
launcher declares  --healthgate_mode blocking --result_authority scientific
  -> validated at launch                      run_one_iteration.py:1557
  -> written to the manifest                  :620-629        PRESERVED
  -> run_workflow(...)                        :1846           ** DROPPED **
  -> HyperparamTuningInput defaults to None   hyperparam_tuning.py:1749, :1761
  -> ScientificAuthority.from_context(None, None, ...)
                                              tuner:5745-5752
  -> formal record: authoritative=False, primary_basis=legacy_authority_unknown
```

Deterministically reproduced with production objects, no LLM/GPU:
`blocking + scientific + valid` is the **only** combination yielding
`authoritative=True`, and no launcher supplies it.

**Decision-bearing consequences, both confirmed reachable in code:**

| Consumer | Effect today | Evidence |
|---|---|---|
| chain incumbent admission | returns `False` — the record *"cannot become the chain incumbent"* | `core/resume.py:678-694` |
| scientific aggregation | `included=0`; `per_model_formal` filtered to **empty** | `result_interpretation_agent.py:1052-1056`, populated from the record at `:2120` |

### Scope

```text
IN    make the declaration reach ScientificAuthority.from_context on every
      launcher-driven production path
IN    reachability + mutation evidence at each transport hop
IN    the launcher census as a published artifact, including paths
      deliberately left unchanged and why

OUT   authority SEMANTICS — the verdict table is frozen for this PR
OUT   the metric, scorer, aggregation, HealthGate semantics
OUT   per-file evidence work (withdrawn premise, §E.3e.1-3)
OUT   trial records — they carry no authority block by design
      (tuner:5744 `if not trial_config.is_trial`)
```

### Requirements

1. A launcher-declared posture reaches `from_context` unchanged on every
   production path that can create a formal record.
2. Every path in the §E.3e.4 census is either wired or **explicitly
   recorded as deliberately not wired, with the reason** — the standard
   B3 Stage A set for itself.
3. The existing verdict table is preserved exactly:
   `blocking+scientific+valid → authoritative`; every other declared
   posture keeps its current `ScientificAuthority` semantics.
4. An **undeclared** posture must remain distinguishable from a declared
   one. `legacy_authority_unknown` stays the honest answer for a run that
   genuinely declared nothing — this PR must not manufacture a default.

### Validation

- **Deterministic, no LLM/GPU:** a launcher-shaped declaration produces a
  formal record with the matching verdict; the undeclared case still
  produces `legacy_authority_unknown`.
- **Reachability/mutation — each must turn a test red:**

  ```text
  drop the field at the launcher
  drop it at the workflow transport
  drop it at the protocol / tuner input
  ```

- **Downstream behaviour:** with a declared `blocking+scientific+valid`
  record, the incumbent predicate admits and `partition_for_aggregation`
  includes it; both currently refuse.
- **Non-behavioural:** no change to trial records, to the verdict table,
  or to any score.

### Merge criteria

Declared authority reaches the formal record on every launcher-driven
path; the census is published including deliberate exclusions; all three
transport mutations are caught; the verdict table and every score are
unchanged.

### Follow-ups reclassified out of PR D (none launch-blocking)

| Item | Status |
|---|---|
| `ml_model_proposal_agent.py:866` strips `score_table`; `:882` drops `per_model_score_tables` — so the **proposer** does not receive per-file evidence | **OPEN DESIGN QUESTION.** Unknown whether this is a deliberate context-budget decision, and unknown whether the proposer already receives sufficient synthesised evidence via `result_interpretation_agent`. Not called a defect |
| `0.999984827817748` renders as `100.0%`, `8.66e-06` as `0.0%` (`_fmt_pct`) | Reporting-precision issue. Not launch-blocking |
| A 5-file, 10%-portion trial is compared against a **full-file** ground-truth ceiling and rendered as "Recovery: 98.7% of ceiling" with no not-same-sample label | The most real of the three. Candidate for a small, separately designed **evidence-labelling** PR; may need only an honest scope label, not a same-sample reference |
| Trial segment indices are **not** persisted (only strategy/portion/count) | Recorded. Blocks any future same-sample reference; `UNKNOWN` whether the sampling seed makes them regenerable |

---

## SUPERSEDED BY AUDIT — original PR D (Per-file evidence to reflector and planner)

> Retained per the append-only rule. Its causal premise was withdrawn on
> 2026-08-08 (§E.3e); do not implement from this section.


> **Updated 2026-08-08 from A/B/C (§E.3d).** PR D is **B2-shaped**: it adds
> an observation that must change no decision. Reuse B2's template rather
> than inventing one — typed model, semantics-neutral names, and a guard
> test that fails if any decision path reads the new field
> (`test_realized_vs_admitted_memory.py::TestObservationOnly` is the
> worked example).
>
> Three specific carry-overs:
>
> - **C1's lesson applies directly.** A missing per-file vector must
>   **fail loudly or record `unknown`** — never default into a value that
>   reads as real. C1 removed exactly such a default
>   (`get_output_type` → `"classifier"`), and PR A's hop-by-hop transport
>   exists because a dropped declaration did not raise.
> - **"The agent sees it" must be proven at the real prompt.** PR A's A3
>   declared its contract from the first typed object and missed the LLM's
>   raw JSON parse; PR C found a fifth `get_output_type` consumer in
>   `agent/prompts.py` that the execution-path census had not looked at.
>   Prompt rendering is a consumer.
> - **The metric stays frozen.** PR B changed no scorer file and proved it
>   by diff. PR D should hold itself to the same check: per-file evidence
>   is *reporting*, and the aggregate it sits beside must be
>   byte-identical.
>
> Also inherited: **§E.3d.2** — before claiming the scalar misled the
> agent, establish that the reflector actually read it, rather than
> inferring from the text it produced.

### Objective

Give the agent the per-file evidence it already produces, so it stops
drawing bad scientific conclusions from a legal scalar.

### Confirmed evidence

P6.5: `iter_006_001` scored `10.7082` with file 19 supplying **99.9985%**
of the linear sum, and the reflection called it *"a usable non-collapsed
WaveNet40 output"*. The per-file vector is **already recorded** —
`file_vector` on `ExperimentRecord`
(`agent/schemas/hyperparam_tuning.py:381`, `:611`) and
`best_valid_file_vector` (`:2532`). It has never been summarized to the
agent.

### Scope

Surface per-file contribution share (and, where meaningful, a same-sample
per-file reference) to the reflector and planner prompts. Add a
concentration summary to the interpretation record.

### Out of scope — **absolutely**

```text
score            unchanged
aggregation      unchanged
normalization    unchanged
weighting        unchanged
anchoring        unchanged
```

This PR changes **what the agent sees**, not what is computed. A diff
touching the scorer is out of scope by definition.

**The same-sample per-file reference is reporting and evidence ONLY.** It
must never become any of the following, in this PR or a later one that
cites it:

```text
NOT a HealthGate input
NOT a filter
NOT a penalty
NOT a reweighting
NOT a new score input
```

The goal is narrow and worth stating exactly: **stop the agent from
seeing the single scalar `10.7082` and concluding the whole waveform is
good.** It is not to tell the metric that `10.7082` should not exist —
P6.5 proved it is correctly computed under the frozen scorer.

### Requirements

- The agent sees per-file contribution alongside every aggregate it is
  asked to interpret.
- Trial-vs-formal sampling differences are labelled where a per-file
  comparison is shown — a 20-segment trial and a 200-segment ceiling are
  **not same-sample**, and past reporting did not say so.

### Validation

- **Frozen-metric proof:** replay the full V20 attempt-3 record set
  before and after; every `denoising_score` and `file_vector`
  **byte-identical**. This is the primary merge gate.
- **Deterministic:** a rendering test on the real `iter_006` vector
  asserting the concentration is stated in the prompt.
- **Layer-2 (optional, dual-mode):** does the reflector's characterization
  change when concentration is shown? Descriptive only — no behavioural
  claim is required for merge.

### Merge criteria

Byte-identical scores; concentration visible in the reflector prompt on
the real `iter_006` fixture; no scorer file in the diff.

---

## PR E — Proposal-scale funnel instrumentation

> **Updated 2026-08-08 from A/B/C (§E.3d).** PR E's whole purpose —
> "convert an impression into measurable data **without** correcting it" —
> is the property B2 had to defend, so B2 is the template.
>
> - **§E.3d.6 is the binding constraint here.** B0 froze a semantics on
>   *zero* observations and said so plainly. PR E may ship the
>   instrumentation and claim the capability; it may **not** report a
>   funnel distribution until one has been collected. The same sentence
>   that governs PR B governs PR E: *the capability to measure is not the
>   measurement.*
> - **Check what already exists first (§E.3d.1).** PR E's own note says
>   `parameter_count_estimate` is not forwarded. Before building new
>   instrumentation, audit whether the value already reaches a boundary
>   and is dropped — that was true in all three merged PRs.
> - **Semantics-neutral naming.** "Undersizing" is a verdict. Record the
>   measured quantities and let the analysis interpret them, exactly as
>   B2 separated `realized − estimated` (forecast error) from
>   `realized − threshold` (headroom consumed) rather than collapsing
>   them into one judged number.

### Objective

Convert "the agent seems to systematically undersize" from an impression
into measurable data — **without** attempting to correct it.

### Confirmed evidence

P4/P6.3: realized candidates span 663,488 - 12,772,096 parameters against
FCNet's ~323 M, across three independent campaign starts, never entering
the advice-encouraged 10M-100M range. But **parameter count is not a VRAM
proxy**, so the causal claim is not yet supportable. One known
mechanical contributor: `parameter_count_estimate` is not forwarded to
the tuner (V18r §13g — the implementor thinned a compliant 348k proposal
to 88,672 and the validator passed it in prose).

**Correction, 2026-08-07.** An earlier draft of this plan called
`ml_model_proposal_agent.py:283` (*"keep `parameter_count_estimate` under
~100M"*) a **contradiction** of the advice files' encouraged 10M-100M
range. It is not: an encouraged range of 10-100M and an upper bound of
~100M are consistent. The real question is a **search-space policy**
question, and it is not this PR's to answer:

> Why is there a hard-ish ~100M proposal prior when the reference FCNet
> is ~323M and the system separately tells the agent that 323M fits in
> the VRAM budget (measured ~6.04 GiB)?

That question is answered **after** the funnel data exists — not by
editing a prompt inside an instrumentation PR.

### Scope

Record the full funnel per candidate:

```text
proposed params
  -> implemented params
  -> preflight disposition (admitted / rejected + typed reason)
  -> trained
  -> HealthGate valid
```

### Candidate identity — required, and it does not exist today

The funnel **cannot** be joined on `model_name`. Generated identity and
registration are precisely the fragile region (P6.2), and a name is not
guaranteed stable or unique across the five stages. Verified 2026-08-07:
no `proposal_id`, `candidate_id` or `lineage_id` field exists anywhere in
`agent/schemas/`.

This PR therefore adds a **minimal immutable candidate identity**,
transported end to end:

```text
proposal -> implementation -> validation -> preflight -> trial
         -> ExperimentRecord
```

subject to Binding principle 2 (every hop tested; deleting a hop fails
the test). Without it the outcome is the familiar one: five stages of
data that cannot be reliably joined — *produced but not delivered*.

### Out of scope

**Any corrective action.** Do not change advice text to push size, do not
alter admission thresholds, do not add a size floor, **and do not edit
the `~100M` proposal prior.** The purpose is measurement; every
correction is decided after the data exists.

### Requirements

- Every candidate carries all five funnel stages with param counts.
- Where a stage drops a candidate, the typed reason is recorded.
- The funnel is queryable across iterations without log parsing.
- All five stages join on the immutable candidate identity, not on name.

### Validation

- **Deterministic:** funnel-completeness test — no candidate reaches a
  terminal state with a missing stage.
- **Backfill check:** the instrumentation reproduces the known
  attempt-3 distribution from stored records.
- **Real, bounded:** one iteration produces a complete funnel record.

### Merge criteria

Complete funnel on a live iteration; prompt contradiction resolved; no
corrective change to advice or thresholds in the diff.

---

## PR F — Inspection-cost scaling study (measure only)

> **Updated 2026-08-08 from A/B/C (§E.3d).** A measure-only study is
> governed by the minimum-bounded-validation rule, and by one practical
> fact PR B hit at Gate time:
>
> - **The GPU is shared.** B4a rung 2 ran while six training jobs
>   belonging to another user held 8.1 GiB, and B4b rung 4 was **not run**
>   partly for that reason. A scaling study must plan around foreign
>   occupancy rather than assume the card — and must never enlarge a
>   workload to force an effect.
> - **Attribution (§E.3d.5).** If inspection cost is measured on a shared
>   card, peer usage is context. B2's per-process counters and
>   `owning_process_pid` are the existing mechanism; do not re-derive one.
> - **Honest absence.** PR F's premise is already that a timeout reports
>   *inconclusive*, never "model too big". Preserve that: an unmeasured
>   candidate is `unknown`, never "fits".

### Objective

Decide whether the 120 s inspection budget censors large candidates —
**before** changing it.

### Confirmed evidence

P3: large candidates time out more often, and the current behaviour is
already honest (a timeout reports *inconclusive*, never "model too big" —
that repair landed in V19). So there is no correctness defect to fix,
only an unquantified censoring risk.

### Scope

A deterministic, **no-LLM** sweep:

```text
architecture x params x batch x segment
  -> inspection wall time
  -> peak VRAM
```

### Out of scope

**Changing the budget.** `120 → 300` is explicitly forbidden until the
curve exists. Adaptive budgets, staged inspection, analytical estimates
and size-aware budgets are all candidate *outcomes*, not inputs.

### Requirements

- Reproducible, seeded, no LLM calls, no scientific records produced.
- Output is a curve plus a written recommendation, not a code change.

### Validation

Deterministic re-run reproduces the curve; the report states which
candidate classes the current budget would censor, with the P6.3
distribution overlaid.

### Merge criteria

Study merged as evidence + recommendation. **A budget change is a
separate, later PR** justified by this data.

### Gate status — explicitly not a V21 launch blocker

P3 has **no correctness defect today**: a 120 s timeout already reports
*inconclusive* and never tells the planner the model is too big. So V21
may start without this study. What it blocks is narrower and absolute:

```text
PR F is a PREREQUISITE FOR CHANGING THE INSPECTION BUDGET,
not a prerequisite for launching V21.
```

---

## PR G — Capability-derived inference batch

> **Updated 2026-08-08 from A/B/C (§E.3d). This is the PR most changed by
> what B and C found.**
>
> - **The measurement PR G wants may already exist (§E.3d.1).** PR G's
>   objective is to derive the batch from a candidate's **measured**
>   memory profile. PR B established that `ProbeResult.peak_vram_gb` is
>   populated by the bounded probe (`probe.py:554`), survives into
>   `RuntimeEstimate`, and reaches the shared policy. **Audit that path
>   before designing a new derivation** — B3 collapsed from "build a
>   mechanism" to "wire one" by asking exactly this.
> - **C3b already pinned the property PR G must preserve.** Planning and
>   runtime call the *same* `inference_batch_for`, so an unregistered
>   model is forecast with the batch it will actually run with, and
>   `inference_batch_uncalibrated` reaches **observability surfaces only**
>   — never a predicate. If PR G makes the batch capability-derived, that
>   flag must not become a pricing or admission input.
> - **Prove parity per built-in before switching off the name table
>   (§E.3d.7 discipline).** B3's parity matrix caught a real divergence in
>   the PHYSICAL VETO regime that source reading had missed. The
>   `_INFERENCE_BATCH_SIZES` entries are calibrated — `transformer` is 1
>   rather than 25 *for a memory reason* — so a derived batch must be
>   compared against each entry and any difference explained, not
>   averaged away. Deleting the table to silence the flag is the lazy
>   over-fix C3b's test already guards against.
> - **Ownership unchanged.** O-C-2 assigned throughput to PR G and
>   admission to PR C; PR B did not move that line.

### Objective

Derive the inference batch from a candidate's **measured** memory profile
rather than a name-keyed table.

### Confirmed evidence

P5: generated models have no name-table entry and fall back to a
conservative batch, slowing inference. `core/inference_defaults.py`
carries two of the nine tracked name-keyed violations.

### Why not a launch blocker

It does not change any score, does not change hypothesis reachability,
and does not produce a wrong scientific conclusion. It costs throughput.

### Scope / Out of scope

Derive batch from measured phase requirements; remove the name-keyed
fallback. Do not change inference numerics or scoring.

### Validation

Deterministic equivalence on the six shipped models (same batch chosen as
the table would give); one bounded real inference on a generated model
showing improved throughput at unchanged output — outputs byte-identical.

### Merge criteria

Byte-identical inference outputs; name table removed from the path.

---

## E.4 Global checkpoints before V21 launch

| # | Checkpoint | Satisfied by | Status |
|---|---|---|---|
| 1 | Regression hypothesis reachable end to end by a generated model | PR A | **DONE** `b9f88ae5` |
| 2 | Resource semantics correct — S3 frozen, admission graded, realization observable | PR B | **DONE** `0aae3f4b` |
| 3 | Novel model name executes through every production stage, proven in a clean subprocess | PR C | **DONE** `cac86c94` |
| 4 | **Declared scientific authority reaches formal records and governs downstream consumers correctly** | PR D | **TODO** |
| 5 | Proposal-scale funnel measurable across all five stages, joined on candidate identity | PR E | **TODO** |
| 6 | Acceptance evidence complete (see below); no new name-keyed correctness/reachability dependency | all | ongoing |

> **Checkpoint 4 replaced 2026-08-08** (§E.3e). It formerly read *"Agent
> sees per-file evidence; scores byte-identical"*, which the audit showed
> is **already the state of master** — per-file `Weight %` has reached the
> planner and reflector prompts since 2026-05-01. A checkpoint that is
> already satisfied cannot gate a launch, and the real launch-blocking
> defect on PR D's plate is the authority-transport break.

**PR F and PR G are explicitly NOT launch checkpoints.** PR F blocks only
a future change to the inspection budget — P3 has no correctness defect
today (a timeout already reports *inconclusive* and never claims the
model is too big), so it cannot block V21 from starting.

### What "acceptance evidence complete" means

**Not** "CI is green." SIDERIUS's configured full CI is **unit + static
by design** — `ruff check`, `ruff format --check`, `pyright`, and
`pytest tests/unit/ -m "not real_run"`. The workflow step is literally
named *"Unit tests — pytest (no real_run, no integration)"*. A green CI
therefore proves **nothing** about any production seam, which is the
exact assumption that let V20's two process-boundary defects reach a
campaign.

Acceptance for every V21 PR is:

```text
configured full CI green
  +
that PR's targeted production-reachability / transport tests green
  +
that PR's bounded real validation, where the plan requires one
```

Never the first line alone.

## E.5 Execution order

```text
A, B, C, E   independent — may proceed in parallel after design review
D            independent, but merge after A (record shape settles)
F            after E (funnel data makes the sweep interpretable)
G            after B (needs measured phase requirements)
```

Recommended serialization if capacity is limited: **A → C → B → D → E**,
then F, then G. A is first because every V21 scientific question depends
on the hypothesis space being open; C is second because a generated model
that cannot execute makes every later validation ambiguous.

## E.6 First V21 experiment, once A-E are merged

The cleanest first experiment remains Part II's Candidate C, unchanged:

```text
same WaveNet backbone · same data · same optimizer · same budget

A: classification + CE
B: classification + focal
C: regression + SmoothL1
```

It answers V20's largest open question directly: **is collapse a property
of the WaveNet architecture, or of the classification formulation?** V20
never tested regression, so no V20 result bears on it (see "Two inference
errors this document must not make", above).

Do not implement Part II Candidates A/B/C simultaneously.

## E.7 PR review template

Every V21 PR fills in the `v20_priorities.md` §20.11 template verbatim,
plus two V21-specific lines:

```
Metric-frozen proof:            <- byte-identical score replay, or "does not touch scoring"
Name-keyed dependency added:    <- correctness/reachability only; must be "none"
Transport contract:             <- full chain per Binding principle 2, each hop tested
Subprocess evidence:            <- clean-spawn proof, or "crosses no process boundary"
Acceptance evidence:            <- full CI + this PR's reachability/transport tests
```
