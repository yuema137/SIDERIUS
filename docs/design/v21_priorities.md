# SIDERIUS V21 Priorities

**Status: OPEN, append-only during the V20 campaign.**
Created 2026-08-06 while V20 attempt 2 was running.

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
