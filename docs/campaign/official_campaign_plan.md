# SIDERIUS Official Scientific Campaign — Configuration Plan

**This document is the single human-readable source of truth for the design and
configuration of the official SIDERIUS scientific campaign.**

It is written for a reader who did not participate in the planning
conversations. Every frozen decision records WHAT it is, its VALUE, WHY it was
chosen, WHO controls it, WHETHER the two formal arms differ, and HOW it will be
verified before launch.

It is a protocol document, not a chat log. A short decision history is kept in
§20; the body always describes CURRENT authority.

* Created: 2026-08-26
* Maintained by: the campaign planning authority (planning only — this lane
  does not modify framework production code, does not launch scientific
  workloads, and does not merge)
* Machine-readable companion: `docs/campaign/official_campaign_decisions.yaml`

---

## 0. Status vocabulary

Every configuration item in this document carries exactly one status. A pending
value is never written so that it looks decided.

| status | meaning |
|---|---|
| `FROZEN` | Operator has ruled. The value is binding on the campaign. |
| `PROVISIONALLY_AGREED` | Direction agreed in discussion, not yet ruled. May still change. |
| `PENDING_OPERATOR_DECISION` | Awaiting an operator ruling. No default may be assumed. |
| `PENDING_RELEASE_IMPLEMENTATION` | The decision depends on release behaviour that does not exist or is not stable yet. |
| `PENDING_TESTPOD_QUALIFICATION` | The value must come from a measurement on qualified hardware. It must not be guessed. |
| `HARDWARE_DERIVED` | Value comes from qualified hardware evidence; the evidence is cited. |
| `NOT_APPLICABLE` | Concept does not apply to this campaign; the reason is recorded. |
| `EXPLICITLY_DISABLED` | Feature is deliberately off, and the campaign config materialises the "off" explicitly rather than relying on a default. |
| `PENDING_IMPLEMENTATION` | The scientific decision is FROZEN; the code/config work that realises it is outstanding. Does **not** reopen the decision. |
| `PENDING_LAUNCH_AUDIT` | The scientific decision is FROZEN; the evidence that proves it holds is collected at launch. Does **not** reopen the decision. |
| `FROZEN_POLICY_PENDING_IMPLEMENTATION_AUDIT` | The scientific decision is FROZEN; current code behaviour is still being verified against it. Does **not** reopen the decision. |
| `PROVISIONALLY_FROZEN` | Decided, subject to one named measurement. Not open for re-argument — only the measurement can move it. |
| `PENDING_AUDIT` | The *fact* a decision depends on is not yet mechanically established. |
| `PENDING_RUNTIME_EVIDENCE` | The decision needs a measured runtime witness before it can close. |
| `PARTIALLY_FROZEN` | Some sub-decisions in the area are frozen; one or more are explicitly left open and named. |
| `VERIFIED_DISABLED` / `VERIFIED_ABSENT` | An audit proved the mechanism does not exist or cannot fire. |

The last two statuses exist so that implementation and audit dependencies of a
frozen decision can be tracked without ever making the decision itself look
open. A `PENDING_IMPLEMENTATION` item is work, not a question.

---

## 1. Campaign naming — FROZEN

**What.** The canonical operator-facing names for the three execution pods.

**Value.**

| name | role | part of the formal scientific comparison? |
|---|---|---|
| `testpod` | H100 qualification, engineering rehearsal, calibration and support pod | **No.** |
| `goldpod` | the formal `WITH_ADVICE` arm — receives advice and prior TIDMAD baseline information | Yes |
| `blindpod` | the formal `WITHOUT_ADVICE` arm — receives neither | Yes |

**Why.** The prior GPU-A / GPU-B / GPU-C labels named hardware, not scientific
role, and were routinely mis-read across sessions and documents. A pod name
must state what the pod is FOR.

**Who controls it.** Operator. Frozen.

**Gold/blind difference.** Naming only.

**How verified.** Documentation and launch-artifact convention. Historical
aliases, recorded once and not to be used going forward:

```text
testpod   = former GPU-C
goldpod   = former Arm A / WITH_ADVICE   (repo lineage: "with-prior-art")
blindpod  = former Arm B / WITHOUT_ADVICE (repo lineage: "without-prior-art")
```

Note the repo lineage names are recorded for traceability only. The repo's
existing arm *semantics* do **not** match this campaign's frozen treatment —
see §5.11, which records the implementation work that gap requires.

---

## 2. Control-plane architecture — FROZEN

**What.** The authority hierarchy for the campaign.

**Value.**

```text
Operator
  -> RTX 5090 Supervisor            (single release / control-plane authority)
     -> per-pod execution coordinator   (testpod / goldpod / blindpod)
        -> local pod workers, chains, processes
```

**Supervisor owns:** release routing · merge and tag authority · final release
acceptance · campaign-config acceptance · blocker disposition · v0.1.0
promotion · operator escalation.

**Pod coordinators own:** local execution · local scheduling · CPU/GPU
utilisation · local worker lifecycle · local evidence collection · local
heartbeat and monitoring.

**Why.** A pod coordinator that can also make release decisions can silently
change what the campaign is running. Separating release authority from
execution authority makes "which code produced this result" answerable.

**Who controls it.** Operator. Frozen.

**Gold/blind difference.** None. Both arms sit under the same Supervisor.

**How verified.** Pod coordinators have no merge/tag capability; the launched
release SHA is recorded per pod and must equal the Supervisor's tagged
`v0.1.0`.

---

## 3. Central configuration principle — FROZEN

**What.** The rule governing every behaviourally relevant setting in the
campaign.

**Value.** Every behaviourally relevant setting must be classified as exactly
one of:

| control class | meaning |
|---|---|
| `EXPERIMENT_FIXED` | Held constant, identical in both arms. |
| `TREATMENT` | The deliberate difference between goldpod and blindpod. |
| `AGENT_CONTROLLED` | The agent decides at run time within a declared, symmetric action space. |
| `HARDWARE_DERIVED` | Determined by qualified hardware measurement, with cited evidence. |
| `EXPLICITLY_DISABLED` | Off, and materialised as off. |

and the resulting semantics must be **explicitly materialised** in the campaign
configuration.

* If a value is intentionally null — write `null` explicitly.
* If a feature is intentionally disabled — disable it explicitly.
* If a value is agent-controlled — state the allowed authority and action space
  explicitly.
* If a value is hardware-derived — record the qualifying evidence.

The campaign must NOT rely on: parser defaults · schema defaults · environment
inheritance · "that is what the framework happens to do today".

**Why.** A future change to a framework default must not retroactively change
the meaning of the frozen campaign. If the campaign's semantics live in
defaults, then the campaign's semantics live outside the campaign record, and
the experiment is not reproducible from its own manifest.

**Who controls it.** Operator. Frozen.

**Gold/blind difference.** None — the principle applies identically to both.

**How verified.** §19 freeze checklist: the effective campaign configuration is
mechanically rendered and every campaign-relevant field must resolve to an
explicitly recorded source.

---

## 4. What we fix, and what we deliberately do not — FROZEN

**What.** The line between fixing the ENVIRONMENT and fixing the AGENT'S
OUTCOME.

Reproducibility here does not mean forcing both arms to make the same
scientific choices. It means giving both arms the same opportunity.

| generally FIXED | generally NOT fixed |
|---|---|
| task · data · splits · budgets · available tools and action space · metrics · HealthGates · resource limits · LLM authority · randomness where appropriate | architecture the proposer selects · loss the proposer selects · tuning path · proposal sequence · scientific strategy · hyperparameters reached through legitimate agent-controlled search |

The governing phrase: **same opportunity and authority, not same resulting
decision.** A difference produced by an AGENT_CONTROLLED decision is an
experimental OUTCOME. A difference produced by configuration is a CONFOUND.

**Who controls it.** Operator. Frozen.

**How verified.** Every field in §12's inventory is assigned a control class
before freeze; a difference between arms is legitimate only if the field's
class is `TREATMENT`.

---

## 5. DECISION AREA 1 — TREATMENT DEFINITION — **FROZEN**

**Status: FROZEN.** Operator ruling, 2026-08-26.

This section defines the experimental variable of the campaign. **It is not to
be reopened unless the operator explicitly reopens it.**

Some items below carry `PENDING_IMPLEMENTATION` or `PENDING_LAUNCH_AUDIT`.
Those are *work*, not *questions*: they are the code, configuration and
evidence dependencies of a decision that is already made. They must never be
read as reopening the treatment definition.

### 5.1 goldpod treatment

**What.** goldpod is the `WITH_ADVICE` arm. At **every proposer round**, the
proposer receives:

* **A.** the same immutable **general optimization-advice artifact**;
* **B.** the same immutable **prior-TIDMAD-baseline-information artifact**.

**Intent.** To provide useful prior information and encourage strong
optimization and exploration **without prescribing a specific solution**.

**Who controls it.** Operator. Frozen.

**Gold/blind difference.** Yes — this IS the treatment.

**How verified.** §5.8 goldpod positive witness + §5.7 blindpod negative
witness, both required.

### 5.2 General optimization advice

**What.** The semantics the advice artifact must communicate.

**Value — the advice communicates:**

* The objective is to achieve the **best possible primary scientific score**
  within all frozen validity, resource and campaign constraints.
* Make **full and productive use** of the available proposal, tuning, training
  and **runtime** budgets.
* **Explore broadly** rather than converging prematurely on one familiar model
  family.
* In particular, actively consider:
  * new model architectures;
  * new loss / objective functions;
  * architecture + loss combinations;
  * **materially different scientific / ML strategies** where allowed by the
    frozen action space.
* Models roughly in the **10M–500M parameter** range are acceptable and
  encouraged for exploration when compatible with the frozen resource and
  runtime constraints.

**Interpretation of the parameter range — all four clauses are binding:**

| clause | meaning |
|---|---|
| 10M–500M is **NOT a hard minimum** | a smaller proposal is not thereby non-compliant |
| 10M–500M is **NOT a target model size** | the agent is not being asked to hit this number |
| **Smaller models remain fully allowed** | the range narrows nothing |
| **Larger models are not automatically allowed merely because they might fit** | fitting in memory is not authorisation |

All candidates remain subject to the frozen resource / admission / runtime
authorities, without exception.

**The advice must NOT prescribe:**

* a particular architecture
* a particular loss
* a particular optimizer
* a particular **scheduler**
* a particular training recipe

**The goal is broad, score-oriented exploration, not imitation of a known
solution.**

**Why.** The experiment asks whether prior information plus optimization
guidance improves autonomous scientific search. Guidance that names the answer
would measure obedience rather than search.

**Who controls it.** Operator. Semantics FROZEN; the artifact bytes are
`PENDING_IMPLEMENTATION` (§5.9).

**How verified.** §5.8.

### 5.3 Prior TIDMAD baseline information

**What.** goldpod also receives the previously **recomputed official TIDMAD
baseline evaluation information**.

**Value.** The artifact contains the **verified result-level evidence**,
including where available:

baseline identity · overall / aggregate primary score · per-file score vector ·
secondary metric results · HealthGate / health-check results · metric
definitions and metadata · score direction · aggregation rule · evaluation
scope · number of evaluated files / items · evaluation authority and version ·
provenance · content hash.

**Character.** Quantitative and descriptive.

**Constraint — the artifact must NOT add strategic recommendations** such as:

> "the baseline is weak on file X, therefore try method Y"

unless the operator separately approves such content as part of the advice.

**Why.** The treatment supplies prior *information*. Interpretation smuggled
into a data artifact would silently make the treatment a different, undeclared
variable.

**Who controls it.** Operator. Semantics FROZEN; artifact bytes
`PENDING_IMPLEMENTATION` (§5.9).

**Gold/blind difference.** Yes — treatment.

**How verified.** Content review against the field list; content hash frozen
and pinned (§5.9).

### 5.4 Baseline assets EXCLUDED from the treatment

goldpod does **NOT** receive, as part of this treatment:

| excluded asset | interpretation |
|---|---|
| **pretrained official-baseline weights / checkpoints** | Existing learned model parameters that could be loaded, fine-tuned, distilled, **evaluated directly**, or otherwise reused. |
| **executable official-baseline implementation code** | The prior baseline's implementation / training code that could simply be copied, executed, or modified. |
| **exact reconstructable architecture recipe** | Architectural information detailed enough to reconstruct the prior baseline directly rather than independently explore the allowed design space. |
| **exact historical training recipe** | The concrete optimizer / hyperparameter / training procedure used to obtain the historical result. |

**The treatment is therefore:**

```text
      prior result-level information  +  broad optimization advice

  and NOT

      a ready-made model / implementation / recipe
```

**Who controls it.** Operator. Frozen.

**Gold/blind difference.** Neither arm receives these — not a treatment axis.

**How verified.** Content review of the prior-baseline artifact; the §5.7 audit
also searches for baseline-code and architecture-recipe fingerprints, not only
for scores.

### 5.5 Injection location and timing

**What.** Where and when the treatment enters the graph.

**Injected DIRECTLY into: the Proposer only. Every round.**

Every proposer round receives the **same immutable** advice artifact and the
**same immutable** prior-baseline artifact.

**The treatment artifacts must NOT be directly injected into:**

* Implementor
* Validator
* Tuner
* Reflector
* Interpretation

unless the operator explicitly reopens this decision later.

Those nodes may naturally receive information propagated through the normal
typed workflow from the proposal and from subsequent execution. **They must not
receive an additional direct copy of the gold treatment artifact.**

**Intended treatment channel:**

```text
immutable advice + prior-baseline artifacts
        |
        v
    PROPOSER            (every round, byte-identical artifacts)
        |
        v
  normal SIDERIUS typed workflow
```

**Why.** A clean, single-point treatment channel. Five simultaneous direct
injections would be five interventions, none of them individually attributable.

**Who controls it.** Operator. Frozen.

**How verified.** Per-node rendered-context census: the artifacts' unique
tokens appear in the proposer's context and in no other node's.

> **Implementation dependency — see §5.10.** The shipped two-arm launcher
> currently REFUSES advice in both arms, and the launch-blocking symmetry
> checker does not allowlist an advice-shaped asymmetry. That is
> `PENDING_IMPLEMENTATION` release work. It does not reopen §5.

### 5.6 blindpod treatment

**What.** blindpod is the `WITHOUT_ADVICE` arm. It must explicitly have:

```text
advice                             = DISABLED
prior_TIDMAD_baseline_information  = DISABLED
```

**Binding constraints:**

* Do **not** implement this merely through omission.
* Do **not** rely on any framework default.
* The final frozen configuration **and effective argv** must **explicitly
  materialize the absence of both treatment components**.

**Why.** An absence produced by omission is indistinguishable from an absence
produced by a dropped flag, a launcher bug, or a future default change. Only an
explicitly recorded "off" is auditable.

**Who controls it.** Operator. Frozen.

**Gold/blind difference.** Yes — treatment.

**How verified.** §5.7.

### 5.7 blindpod leakage audit — formal launch gate

**What.** Before formal campaign launch, mechanically prove that blindpod does
not receive the treatment.

**Audit at least these layers:**

1. effective configuration
2. treatment / artifact paths
3. rendered proposer prompt / context
4. runtime context / transcript evidence

**Discriminative negative controls, where practical — search for:**

* treatment artifact hash
* prior-baseline artifact hash
* unique advice phrases
* unique baseline score / value(s)
* baseline artifact name / path

**The decisive requirement:**

> The blindpod audit must demonstrate absence **from the actual model-visible
> context**, not merely that a Boolean configuration field is `false`.

**Why.** A `false` flag proves what the configuration intended, not what the
model saw. Only the rendered context proves what reached the model. And a
search for a generic term can come back empty for the wrong reason — a
discriminative control is a check that could actually have failed.

**Status.** `CONDITIONAL_ON_BLIND_EXECUTION` (corrected 2026-08-26). This
remains a **formal gate on BLIND**, in full and unweakened — but the campaign is
**GOLD-ONLY**, so **it does not gate the Gold launch** and its absence neither
blocks nor invalidates completed Gold. It reactivates if and when Blind is
executed. `PENDING_LAUNCH_AUDIT` at that point.

**Who controls it.** Supervisor executes; operator accepts.

### 5.8 goldpod positive treatment audit — formal launch gate

**What.** The positive side must also be mechanically proven:

* **every** goldpod proposer round receives the intended immutable advice
  artifact and prior-baseline artifact;
* the artifact **hashes match the frozen campaign authority**;
* **no round silently omits or mutates the treatment.**

**Why.** A treatment that silently stopped being injected at round 4 would
produce a null result indistinguishable from a true null result. Absence of
evidence of leakage is not evidence of treatment.

**The treatment audit therefore contains BOTH:**

```text
goldpod positive witness   +   blindpod negative witness
```

Neither alone is sufficient.

**Status.** Formal launch gate. `PENDING_LAUNCH_AUDIT`.

**Who controls it.** Supervisor executes; operator accepts.

### 5.9 Artifact immutability

**What.** Before formal launch, **freeze and content-hash**:

* the general advice artifact
* the recomputed TIDMAD prior-baseline artifact

**Requirements:**

* Record their **exact hashes** in this campaign plan and in the
  machine-readable campaign manifest.
* Do **not** dynamically rewrite either artifact between rounds, bands, or
  chains.
* **All four goldpod chains receive byte-identical treatment artifacts.**

**Why.** An artifact that varies between bands makes the four goldpod chains
four different experiments. A hash recorded in the manifest is what makes
"the treatment was constant" a checkable claim rather than an assertion.

**Status.** Decision FROZEN; the artifacts are not yet authored, so the hashes
are `PENDING_IMPLEMENTATION`. Hash values will be written into this section and
into the manifest when the artifacts are frozen.

| artifact | sha256 | status |
|---|---|---|
| general optimization advice | *(not yet authored)* | PENDING_IMPLEMENTATION |
| recomputed TIDMAD prior-baseline information | *(not yet authored)* | PENDING_IMPLEMENTATION |

### 5.10 Fairness / control principle

Outside the frozen treatment difference, goldpod and blindpod must have **the
same experiment-fixed authorities and the same allowed agent action space**.

Differences that arise later because agents make different legitimate
`AGENT_CONTROLLED` scientific decisions are **campaign outcomes, not
configuration asymmetries**.

The experiment intends to compare:

```text
      same opportunity  +  different prior information

  and NOT

      different engineering capability
```

**Status.** FROZEN.

### 5.11 Implementation dependency — the shipped arm definition differs

**This does not reopen §5. It records the work §5 requires.**

The repository already ships a two-arm harness whose treatment variable is
**different** from the frozen Decision Area 1.

| | Decision Area 1 (FROZEN, operator 2026-08-26) | repository as shipped (arXiv X9 / issue #255, ruling 2026-08-25) |
|---|---|---|
| treatment | advice artifact + prior TIDMAD baseline information, injected at the proposer every round | literature-review topology on/off, plus `--baseline_isolation` on the WITHOUT arm |
| advice | goldpod: injected every round | **REFUSED in BOTH arms** |
| lit review | not mentioned by Decision Area 1 | THE variable |

Repository evidence:

* `sdsc_submission_scripts/launch_prior_baseline_experiment.sh` header states:
  *"Advice: NEITHER arm receives an advice file … `--advice` /
  `--human_advice_file` are therefore REFUSED as passthrough in both arms."*
  The arm flags it sets are `--ml_lit_review_enabled` /
  `--no-ml_lit_review_enabled --baseline_isolation`.
* `sdsc_submission_scripts/campaign_arm_symmetry.py` — the launch-blocking
  symmetry checker — allowlists exactly five policy keys as legitimately
  asymmetric: `experiment_arm`, `lit_review_enabled`,
  `lit_review_config_path`, `lit_review_config_sha256`, `baseline_isolation`.
  Nothing advice-shaped is allowlisted, so **under the current checker an
  advice-bearing goldpod would FAIL arm symmetry.**

**Consequent work items:**

| id | item | status | owner |
|---|---|---|---|
| T-IMPL-1 | Launcher must accept and inject the treatment artifacts into goldpod's proposer, and explicitly materialise their absence for blindpod | `PENDING_IMPLEMENTATION` | release lane, routed via the Supervisor |
| T-IMPL-2 | `campaign_arm_symmetry.py` must allowlist and **positively assert** the advice-shaped asymmetry (an expected asymmetry that is absent is also a failure) | `PENDING_IMPLEMENTATION` | release lane, routed via the Supervisor |
| T-IMPL-3 | The §5.7 audit must gain the rendered-context and transcript layers; the current checker covers only resolved-config JSON and child argv | `PENDING_IMPLEMENTATION` | release lane, routed via the Supervisor |

**Consequent open questions — these are NOT part of Decision Area 1 and belong
to later decision areas:**

| id | question | decision area |
|---|---|---|
| Q-LIT-1 | Is the literature-review topology part of the campaign at all, and if so is it now `EXPERIMENT_FIXED` (identical in both arms)? Decision Area 1 does not mention it; left unruled, the campaign would carry two simultaneous variables. | 6 (proposal authority) — must be ruled before topology (14) |
| Q-ISO-1 | Does `--baseline_isolation` remain on blindpod? It removes the bundled baseline description, the baseline-naming prompt literal and the built-in candidate — plausibly the right mechanism for §5.6's explicit absence, but it was designed for a different arm definition. | 6 / 14 |

## 6. Release boundary

Campaign planning proceeds **in parallel** with release hardening. Planning does
not wait for remediation, adversarial audit, or H100 qualification.

However:

| stage | requirement |
|---|---|
| planning | may begin now |
| configuration freeze | only when the required semantic authorities are stable |
| formal launch | only from the final qualified `v0.1.0` authority |

Values that depend on unresolved release behaviour are marked
`PENDING_RELEASE_IMPLEMENTATION`. Values that depend on testpod measurement are
marked `PENDING_TESTPOD_QUALIFICATION`. Neither category is ever guessed.

Known dependencies at the time of writing (external state, recorded for
context, not owned by this lane):

* `v0.1.0-rc.N` freeze — Supervisor-owned; not yet cut.
* H100 platform and framework qualification — GitHub issue #314, rows Q1–Q9;
  BLOCKED pending the rc freeze.
* `H100_CORESIDENCY_FACTOR` in `sdsc_submission_scripts/h100_posture.env` —
  must be probe-measured; a banded H100 launch is refused by name while it is
  empty.

---

## 7. Decision order

Topics are decided one at a time, in this order, unless the operator requests
otherwise. Downstream choices are not silently frozen ahead of their turn.

| # | topic | status |
|---|---|---|
| 1 | Treatment definition | **FROZEN** (§5) |
| 2 | LLM configuration **+ execution concurrency** | **FROZEN** with named audit residuals (§8 census; §9 decisions; §9A cross-section consequence) |
| 3 | Randomness / seeds / ordering | **FROZEN** (§10); four `PENDING_AUDIT` implementation items |
| 4 | Task and data semantics | **FROZEN** except evaluation-portion semantics (§16); `A4-1`…`A4-5` |
| 5 | Model / loss / optimizer / scheduler action space | **FROZEN** (§17); `A5-1`…`A5-6` |
| 6 | Proposal / tuning / reflection authority | PENDING_OPERATOR_DECISION |
| 7 | Training budgets | **OPERATOR-FROZEN** (§19) |
| 8 | LLM / token / call budgets | **FROZEN** — inherited from Part 2 (§19.15) |
| 9 | Metrics and scientific scoring | **OPERATOR-FROZEN** (§20A) |
| 10 | HealthGate roster and thresholds | **FROZEN** (§20A.2, §20A.3) |
| 11 | H100 resource / admission / runtime calibration | PENDING_TESTPOD_QUALIFICATION |
| 12 | Persistence / checkpoint / resume semantics | **OPERATOR-FROZEN** (§20B.3, §20B.7) |
| 13 | Failure / retry / resume / restart semantics | **OPERATOR-FROZEN** (§20B); `A8-1`…`A8-14` |
| 14 | Formal arm topology / chain mapping | PENDING_OPERATOR_DECISION (blocked on §5.8) |
| 15 | Output / reporting / provenance requirements | PENDING_OPERATOR_DECISION |
| 16 | testpod rehearsal protocol | PENDING_OPERATOR_DECISION |
| 17 | goldpod / blindpod launch protocol | PENDING_OPERATOR_DECISION |
| 18 | Final symmetry audit | **`CONDITIONAL_ON_BLIND_EXECUTION`** — not a Gold-only requirement |
| 19 | Campaign freeze checklist | PENDING_OPERATOR_DECISION |

---

## 8. LLM configuration — MECHANICAL CENSUS (repository facts)

**Everything in this section is a repository fact, established by reading the
source at the current checkout. Recommendations are separated into §9.**

Census performed 2026-08-26 against branch `fix/failure-honesty-exit-status`,
HEAD `df3f1c04`.

### 8.1 Where LLM configuration lives

| authority | file | role |
|---|---|---|
| role→model routing schema | `workflows/llm_config.py` | `WorkflowLLMConfig` — Pydantic; per-node/per-sub-call provider + model_id |
| shipped routing files | `llm_configs/*.json` | four files; the production one is `openai_tiered_pro.json` |
| the client itself | `agent/llm_bridge.py` (2,467 lines) | `LLMBridge` — constructs `OpenAI(...)` clients, owns retry/timeout, makes every call |
| CLI entry | `sdsc_submission_scripts/run_one_iteration.py --llm_config` | default `None`; supersedes the deprecated `--llm_model` |
| chain forwarding | `sdsc_submission_scripts/launch_prior_baseline_experiment.sh` | `--llm_config` is in the `identity_flags()` passthrough allowlist |

### 8.2 Roles that take an independent LLM configuration

There are **six top-level slots**, and three of them fan out into sub-call
slots — **eleven independently configurable call sites in total**:

| slot | sub-slots | consumer |
|---|---|---|
| `interpret` | — | interpretation agent |
| `propose` | `comparison`, `reasoning`, `proposing` | proposal agent's three-stage pipeline |
| `implement` | — | implementor agent |
| `validate` | — | validator agent (JSON alias `validate`, field `validate_model`) |
| `tune` | `planner`, `reflector` | tuner; flattened to `provider`/`model_id` + `reflect_provider`/`reflect_model_id` |
| `lit_review` | `main`, `search` | literature-review node |

### 8.3 The shipped routing files, verbatim

| slot / sub-slot | `openai_tiered_pro.json` (production) | `openai_tiered_v1.json` | `deepseek_tiered_pro.json` | `certify_minimal.json` |
|---|---|---|---|---|
| `interpret` | openai / **gpt-5.5** | openai / gpt-5.4 | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `propose.comparison` | openai / **gpt-5.5** | openai / gpt-5.4-mini | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `propose.reasoning` | openai / **gpt-5.5** | openai / gpt-5.4 | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `propose.proposing` | openai / **gpt-5.5** | openai / gpt-5.4 | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `implement` | openai / **gpt-5.5** | openai / gpt-5.4 | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `validate` | openai / **gpt-5.5** | openai / gpt-5.4-mini | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `tune.planner` | openai / **gpt-5.5** | openai / gpt-5.4 | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `tune.reflector` | openai / **gpt-5.5** | openai / gpt-5.4-nano | deepseek / deepseek-v4-pro | openai / gpt-4o-mini |
| `lit_review.main` | **deepseek / deepseek-v4-pro** | deepseek / deepseek-v4-pro | deepseek / deepseek-v4-pro | deepseek / deepseek-v4-pro |
| `lit_review.search` | **deepseek / deepseek-v4-pro** | deepseek / deepseek-v4-pro | deepseek / deepseek-v4-pro | deepseek / deepseek-v4-pro |

**Fact worth stating plainly:** in `openai_tiered_pro.json` — the file the V20
campaign launcher and the Pets quickstart both pin — every slot is `gpt-5.5`
**except literature review, which is `deepseek-v4-pro` on a different
provider.** That is the only role that receives a different model/config from
the others.

`openai_tiered_v1.json` is a genuinely tiered file (frontier / mini / nano by
cognitive demand). `openai_tiered_pro.json` is flat.

### 8.4 Sampling parameters — NOT SET ANYWHERE

The API call site is `agent/llm_bridge.py:1594-1602`:

```python
client.chat.completions.create(
    model=model_name,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ],
    response_format={"type": "json_object"},
)
```

| parameter | occurrences in `agent/llm_bridge.py` | effective value |
|---|---|---|
| `temperature` | **0** | provider default (implicit) |
| `top_p` | **0** | provider default (implicit) |
| `max_tokens` / `max_completion_tokens` / `max_output_tokens` | **0** | provider default (implicit) |
| `reasoning_effort` | **0** | provider default (implicit) |
| `verbosity` | **0** | provider default (implicit) |
| `seed` | **0** | not requested |
| `response_format` | set | `{"type": "json_object"}` on the JSON path |

**No sampling parameter is set by SIDERIUS on any call.** Every one of them is
whatever the provider currently defaults to, for the model id currently
resolved, at the moment the call is made. None is recorded anywhere.

### 8.5 Timeout, retry and backoff — set, and documented

These ARE explicit, in `agent/llm_bridge.py`:

| knob | value | source | notes |
|---|---|---|---|
| `DEFAULT_REQUEST_TIMEOUT_SECONDS` | **600.0 s** | module constant | Deliberately raised from 120 s (operator decision 2026-08-17) after a real Gate proved 120 s was killing legitimate implementor generations ten times consecutively. Equals the OpenAI SDK's own default. |
| `DEFAULT_TIMEOUT_RETRIES` | **3** total attempts | module constant | Bounded, and deliberately separate from `max_retries`: a timeout is not a "try again shortly" signal, and unbounded timeout retry is a loop that cannot make progress. |
| `max_retries` (429 / 5xx / connection) | **`None` = retry indefinitely** | `LLMBridge.__init__` default | Intentional: the process owner (Slurm wall time, Ctrl-C) is the natural timeout; the operator tops up balance and the chain resumes. Overridable per slot via `NodeLLMConfig.max_retries`. |
| SDK-level retries | **0** (disabled) | client constructors | Replaced by the bridge's own backoff loop. |
| backoff schedule | 2.5 s, 5 s, 10 s, 20 s, 40 s (~77 s) | `_chat_json` retry loop | Chosen after the SDK's ~25 s total gave up too fast under provider saturation. |
| content-retry budget | `_CONTENT_RETRY_BUDGET` (empty content / JSON decode error) | `_chat_json` | Separate from transport retry. |

**`NodeLLMConfig.max_retries` is declared per slot** but is only forwarded for
some slots: the tuner uses `planner.max_retries` (reflector's is dropped — one
bridge), the proposer uses `reasoning.max_retries` (comparison's and
proposing's are dropped), and `lit_review`'s branch forwards **no**
`max_retries` at all. None of the shipped `llm_configs/*.json` files sets it,
so in practice every production slot runs the `None` = infinite-retry policy.

### 8.6 Providers

`_KNOWN_PROVIDERS` (`agent/llm_bridge.py:121-144`):

| provider | base_url | api key env | default_model (used only if `model_id` is unset) |
|---|---|---|---|
| `openai` | SDK default | `OPENAI_API_KEY` | `gpt-4o` |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `GEMINI_API_KEY` | `gemini-3.1-flash-lite-preview` |
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-v4-pro` |

`claude` is present but commented out (non-standard auth). `NodeLLMConfig`'s
`provider` field is `Literal["gemini","openai","deepseek"]`.

### 8.7 Schema defaults that apply when a slot is ABSENT

If `--llm_config` is omitted entirely, or a slot key is missing from the JSON,
the Pydantic schema defaults apply. These are **gemini** defaults:

| slot | schema default if absent |
|---|---|
| `NodeLLMConfig` base | gemini / `gemini-3.1-flash-lite-preview` |
| `tune.planner` | gemini / `gemini-3.1-pro-preview` |
| `tune.reflector` | gemini / `gemini-2.5-flash` |
| `propose.comparison` | gemini / `gemini-2.5-flash` |
| `propose.reasoning` | gemini / `gemini-3.1-pro-preview` |
| `propose.proposing` | gemini / `gemini-3.1-pro-preview` |
| `lit_review.main` / `.search` | deepseek / `deepseek-v4-pro` |
| top-level slot = `None` | `.get()` returns `{}` → the node falls back to its own built-in default |
| `lit_review` absent | **falls back to the `interpret` slot's provider/model**, with `search_llm_*` left absent |

`--llm_config` itself defaults to `None` in `run_one_iteration.py:1227`.

The four shipped files all populate all six top-level slots, so under a shipped
file none of these fallbacks fires. They matter only as the failure mode if a
slot is dropped, mistyped, or a future slot is added.

### 8.8 Provenance — what is recorded about the LLM configuration

**Nothing.** `core/run_invariants.py` — the run-invariants lock that pins
data scope, health-config sha256, task composition fingerprint, arm label and
`baseline_isolation` — contains **zero** occurrences of `llm`, `model_id` or
`provider`.

Consequences, stated as fact:

* The routing file's path and content hash are not pinned in the lock.
* The resolved per-role model ids are not pinned in the lock.
* No prompt version or prompt hash is pinned in the lock (a repo-wide search
  finds prompt-shape assertions only in tests and one Gate script).
* Per-call token usage IS recorded (`token_usage.jsonl` via
  `LLMBridge._record_usage`, with run_id / run_name / iter / label /
  model_name / provider). That is telemetry, not a pinned invariant — it
  records what happened, and cannot refuse a resume whose routing changed.

The arm-symmetry checker (`campaign_arm_symmetry.py`) diffs the child argv, and
`--llm_config` is not in its allowlist — so a *path* difference between arms
would be caught. A difference in the *contents* of the same path, or a
provider-side model change behind a stable model id, would not.

### 8.9 Campaign-side LLM preflight that already exists

`sdsc_submission_scripts/campaign_llm_smoke.py` fires a bounded N-way parallel
burst (default 8, matching two fleets of four co-resident band chains) through
the repository's own `WorkflowLLMConfig` + `LLMBridge` against the **tuner
planner** slot, and reports success count and p95 latency. It uses
`max_retries=2` so a smoke cannot inherit the infinite quota retry.

Its own docstring states what it is not: "a green burst proves the key,
endpoint, model id and N-way concurrency are LIVE right now, nothing more."

---

## 9. DECISION AREA 2 — FORMAL LLM CONFIGURATION + EXECUTION CONCURRENCY

**Operator rulings, 2026-08-26.** Part 1 (§5) is untouched and remains FROZEN.

Statuses used in this section are precise. A `FROZEN` scientific decision is
never downgraded to `PENDING` because its implementation still needs
verification — those are separate axes:

| status | axis |
|---|---|
| `FROZEN` | the campaign decision is made |
| `FROZEN_POLICY_PENDING_IMPLEMENTATION_AUDIT` | decision made; current code behaviour still being verified against it |
| `PROVISIONALLY_FROZEN` | decision made subject to a named measurement |
| `PENDING_AUDIT` | the *fact* the decision depends on is not yet established |
| `PENDING_IMPLEMENTATION` | decision made; code does not yet realise it |
| `NOT_APPLICABLE` | concept does not exist on this execution path |

Audit basis: branch `fix/failure-honesty-exit-status`, HEAD `df3f1c04`,
read-only source/config inspection. No training run, no LLM call, no launch.

### 9.1 OpenAI configuration authority — FROZEN, exact authority resolved

**Decision.** The formal campaign uses the repository's existing OpenAI Pro
configuration. goldpod and blindpod use the **exact same** LLM configuration
authority.

**Resolved by census — this is the record that must survive a same-name edit:**

| field | value |
|---|---|
| config path | `llm_configs/openai_tiered_pro.json` |
| filename | `openai_tiered_pro.json` |
| **content SHA256** | `fc3d95ec26c2ca3eb554f031b9b6a2a765495a9a8d1d35616d9beafcc7199475` |
| size | 865 bytes |
| last touched by | `2da0ca10` — *"feat(launch): the V20 production posture belongs to the repository"* |
| schema authority | `workflows/llm_config.py::WorkflowLLMConfig` (Pydantic) |
| CLI entry | `run_one_iteration.py --llm_config` (default `None`) |
| **API mode** | **OpenAI Chat Completions** — `client.chat.completions.create` at `agent/llm_bridge.py:1595`, `:1775`, `:1839`. **All three call paths. The Responses API is never used.** |
| endpoint (openai) | SDK default (`base_url=None` in `_KNOWN_PROVIDERS`) |
| endpoint (deepseek) | `https://api.deepseek.com` |

**Role mapping — preserved as-is for operator review, NOT flattened:**

| slot | provider | model |
|---|---|---|
| `interpret` | openai | `gpt-5.5` |
| `propose.comparison` | openai | `gpt-5.5` |
| `propose.reasoning` | openai | `gpt-5.5` |
| `propose.proposing` | openai | `gpt-5.5` |
| `implement` | openai | `gpt-5.5` |
| `validate` | openai | `gpt-5.5` |
| `tune.planner` | openai | `gpt-5.5` |
| `tune.reflector` | openai | `gpt-5.5` |
| `lit_review.main` | **deepseek** | **`deepseek-v4-pro`** |
| `lit_review.search` | **deepseek** | **`deepseek-v4-pro`** |

The file is flat `gpt-5.5` across all eight workflow slots. **Literature review
is the only role on a different provider and model.** Its disposition depends
on Q-LIT-1 (§5.11), which is still open.

**Explicit request parameters sent:** `model`, `messages`, `response_format`
(JSON path only), and `tools` + `tool_choice` on the tool path — which has no
production caller (§9.13).

**Omitted / provider-defaulted:** `temperature`, `top_p`, `max_tokens`,
`reasoning_effort`, `verbosity`, `seed`, `n`, `stop`, `presence_penalty`,
`frequency_penalty`, `logprobs`, `stream`.

**Environment overrides:** `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` (credentials
only — no model or parameter override reaches the bridge from the environment).

**PENDING_IMPLEMENTATION — F-LLM-1.** The config SHA256 above is recorded *in
this document*. It is **not** pinned into the run identity:
`core/run_invariants.py` contains zero occurrences of `llm`, `model_id` or
`provider`. `campaign_arm_symmetry.py` compares `--llm_config` by **path** via
argv, so both arms could name the same path whose contents changed between the
two launches and the checker would pass. Closing this requires release-lane
work. Reported, not patched.

### 9.2 Gold/blind LLM symmetry — FROZEN

For every corresponding workflow role, `goldpod LLM authority == blindpod LLM
authority`: provider, model, reasoning configuration, sampling behaviour,
request construction, timeout, retries, concurrency authority, prompt version,
context policy.

**The Part 1 treatment is the ONLY approved systematic model-visible
difference.**

### 9.3 Model fallback — FROZEN: DISABLED — **VERIFIED_DISABLED**

**Decision.** `fallback_model = DISABLED`. A transient service or API failure
must never change the model used by that scientific workflow call.

**Audit result: VERIFIED_DISABLED.** No fallback model or provider path exists.

* `_call_with_retry(fn, label)` retries the **same closure**
  (`agent/llm_bridge.py:1264-1322`). The closure captures `model=model_name`
  from the enclosing scope; nothing in the retry loop can rebind it.
* An unknown provider raises `ValueError` at construction — it does not degrade
  to a default (`llm_bridge.py:500-512`).
* Every string match for `fallback` in `llm_bridge.py`, `llm_config.py` and
  `model_exploration.py` is unrelated: lit-review config-slot inheritance,
  `agent_generated/` read-only lookup, and comments. **Zero model-substitution
  sites.**

The one *configuration*-level inheritance that does exist —
`WorkflowLLMConfig.get("lit_review")` falling back to the `interpret` slot when
`lit_review` is absent (`llm_config.py:318-332`) — is resolved **once at
config-load time**, never on failure, and does not fire under
`openai_tiered_pro.json`, which populates the slot explicitly.

### 9.4 Reasoning effort — **FROZEN: HIGH** — implementation `PENDING_IMPLEMENTATION`

**Operator ruling, 2026-08-26.** GPT-5.5 reasoning effort is frozen at **HIGH**
for all workflow roles, identical in both arms. The current omission is
explicitly **not** the desired formal-campaign semantics.

**Live probe evidence — bounded, 3 calls, exact production request shape
(`chat.completions` + `gpt-5.5` + `response_format={"type":"json_object"}`):**

| request | HTTP | resolved model | `reasoning_tokens` |
|---|---|---|---|
| `reasoning_effort="high"` | **200 accepted** | `gpt-5.5-2026-04-23` | **9** |
| `reasoning_effort="low"` | **200 accepted** | `gpt-5.5-2026-04-23` | **0** |
| **omitted** (current production shape) | 200 | `gpt-5.5-2026-04-23` | **6** |

Three facts this settles, none of which was inferable from the repository:

1. **`reasoning_effort` IS accepted on Chat Completions for `gpt-5.5`.** It is
   not a Responses-API-only control. The `gpt-5-pro` documentation cited
   earlier does not govern this model or this endpoint.
2. **It IS effective, not ignored.** `high` and `low` produce different
   `reasoning_tokens` counts, so the field changes behaviour.
3. **Omitted is NOT high.** The omitted case lands *between* `low` and `high`,
   confirming the operator's reading that the current default is an
   intermediate level. The campaign was silently running at less than the
   intended reasoning depth.

**Required change — `PENDING_IMPLEMENTATION`, routed to the Supervisor:**

The value must reach `client.chat.completions.create(...)` at all three call
sites in `agent/llm_bridge.py` (`:1595` `_chat_json`, `:1775` `generate_text`,
`:1839` `tool_call`). Because the bridge is provider-generic and `deepseek` is
also routed through the same code path, the field must be emitted only for
providers/models that accept it — a blanket addition would break the
`lit_review` slot. The planning lane did **not** patch this.

**Status: decision `FROZEN`; implementation `PENDING_IMPLEMENTATION`
(F-LLM-5).**

### 9.5 Temperature / top_p — **FROZEN** — and a correction to the earlier record

**Decision unchanged.** Do not campaign-tune sampling. Preserve native
behaviour. Add no artificial parameter.

**Correction.** §9.5 previously recorded these as "omitted → provider default
applies", and inferred from that a drift risk. The live probe shows the
situation is materially better, and the earlier characterisation was
incomplete:

| request | HTTP | result |
|---|---|---|
| `temperature=0.7` | **400** | `unsupported_value` — *"'temperature' does not support 0.7 with this model. Only the default (1) value is supported."* |
| `temperature=1` | 200 | accepted |
| `top_p=0.9` | **400** | `unsupported_parameter` — *"'top_p' is not supported with this model."* |

**What this means for the campaign:**

* **`temperature` is not tunable on `gpt-5.5` at all** — the model accepts only
  its fixed default of `1`. There is no temperature to choose, and no
  provider-side temperature default that could drift between the two arm
  launches.
* **`top_p` is not a supported parameter on this model** — the concept does not
  exist on this path.

So the frozen policy is satisfied not merely by SIDERIUS's restraint but by the
**model's own contract**. Omitting both is the only legal request shape.

**Consequence for §9.15.** The "provider-owned sampling regime" limitation I
recorded earlier is substantially narrower than stated: on the two classic
sampling axes there is nothing to own. §9.15 is corrected accordingly.

**Effective state, recorded:**

```text
temperature : NOT TUNABLE (model accepts only its fixed default 1); omitted by SIDERIUS
top_p       : UNSUPPORTED PARAMETER on this model; omitted by SIDERIUS
```

**Status: FROZEN, effective state VERIFIED by live probe.**

### 9.6 LLM random seed — **FROZEN: `PROVIDER_CONTROLLED_STOCHASTICITY`**

**Authorized bounded probe executed** (operator ruling item 2): two identical
requests on the exact production path — `chat.completions`, `gpt-5.5`,
`response_format={"type":"json_object"}` — differing in nothing, both carrying
`seed=20260826`.

**Exact request parameters used:**

```json
{ "model": "gpt-5.5",
  "messages": [{"role":"system","content":"You are a reachability probe. Follow the instruction exactly."},
               {"role":"user","content":"Reply with a JSON object {\"n\": <one random integer 1-1000000>}."}],
  "response_format": {"type":"json_object"},
  "seed": 20260826 }
```

**Result:**

| call | HTTP | resolved model | `system_fingerprint` | content |
|---|---|---|---|---|
| 1 | 200 | `gpt-5.5-2026-04-23` | **`null`** | `{"n":482917}` |
| 2 | 200 | `gpt-5.5-2026-04-23` | **`null`** | `{"n":472913}` |

**Verdict: the seed is ACCEPTED BUT INERT.** The request does not fail, so a
naive audit would call the field "supported" — but identical seeded requests
produced **different outputs**, and the API returns **no `system_fingerprint`**
at all, so there is not even a backend-identity signal to pin. This is exactly
the accepted-but-inert field the operator instructed must not be invented.

**Recorded decision:**

```text
LLM_RANDOMNESS = PROVIDER_CONTROLLED_STOCHASTICITY
```

No seed is sent. No matched gold/blind seed mapping is implemented at the LLM
layer, because there is no mechanism to match. Any such field would assert a
reproducibility property this API path demonstrably does not provide.

**This is scoped to the LLM layer only.** Training-side RNG (Decision Area 3)
is a separate question and the matched-band CRN policy there is untouched.

**Status: FROZEN, on live evidence. No broad eval was run — 2 calls, 143 total
tokens.**

### 9.7 LLM token / spend budget — FROZEN: NONE — **VERIFIED ABSENT**

**Decision.**

```text
campaign_total_token_cap = NONE
campaign_total_spend_cap = NONE
```

The agent may use the LLM resource freely. The operator controls spending
externally via the platform account spend limit. Usage is recorded for
provenance and accounting, but **cumulative token consumption is not a
scientific stopping criterion.**

**Rationale recorded for the future reader:** the treatment is not compared
under fixed-token efficiency. Both arms are given the same agent/runtime
framework opportunity and asked for the best science score.

**Audit result: no contradicting limit exists.** A repository-wide search for
`token_budget`, `max_total_tokens`, `spend_limit`, `cost_limit`,
`budget_exceeded`, `max_llm_calls`, `call_budget` across production code
returns exactly three hits, none of them a campaign-level cap:

* `nodes/ml_literature_review/ml_literature_review.py:557` — `budget_exceeded`
  is the lit-review node's internal **search-round** decision label, not a
  token or spend cap;
* `agent/schemas/literature_review.py:551` — the schema documenting that label;
* `scripts/checkpoint_s_runner.py:187` — a comment.

Token usage **is** recorded (`token_usage.jsonl` via
`LLMBridge._record_usage`, carrying run_id / run_name / iter / label /
model_name / provider), which is exactly the provenance-without-enforcement
posture the decision requires.

**Unavoidable provider constraints remain and are not overridden:** model
context window, API maximum output size, provider rate limits, account limits.

**Status: FROZEN, implementation VERIFIED consistent.**

### 9.8 Context / history / truncation — **PENDING AUDIT (partial result)**

**What is established.**

*Statelessness.* Every production request is **stateless**. All three call
sites build a fresh two-message array — `[{system}, {user}]` — per call
(`llm_bridge.py:1597`, `:1777`, `:1841`). There is **no** `previous_response_id`
and **no** conversation object; the only `conversation` string in the module is
a docstring. History therefore reaches the model only by being **rendered into
the prompt text** by the calling node, never by provider-side chaining.

*Truncation exists, and it is framework-owned, character-based, and applied
before the request.* Confirmed sites:

| site | what it truncates | bound |
|---|---|---|
| `agent/prompts.py:516,543` | plugin source excerpt | `_PLUGIN_SOURCE_EXCERPT_MAX_CHARS`, comment states 4000 gives "~2-3x headroom" |
| `agent/cache_consolidator.py:160,168` | research-memory statements and narrative | schema char caps, **silent** by design |
| `agent/schemas/proposal.py:582` | a proposal field, middle-truncated | schema cap |

**These are character caps enforced by SIDERIUS, not token-budget management
against a context window.** No component computes a token count against a model
context limit; no `context_window` / `max_context` / `token_limit` symbol
exists in production code.

**What is NOT established, and why I am not closing this.** Your required
invariant is that the Part 1 treatment may add gold-specific context but must
not cause asymmetric loss of the **common** workflow information. Answering
that needs two things I do not have:

1. **The token size of an actual rendered proposer prompt** at realistic
   campaign depth (late iteration, accumulated research memory, full score
   tables). I can measure it — `scripts/render_proposer_prompts_for_audit.py`
   exists — but rendering a representative late-campaign context requires a
   workspace with real accumulated state, which this planning lane does not
   have and should not manufacture.
2. **The treatment artifacts themselves**, which are not yet authored
   (D-TREAT-8), so the gold-side context overhead is currently unmeasurable.

**The good news, stated precisely:** because SIDERIUS truncates by *character
cap per component* and never by *total token budget*, there is no mechanism by
which adding gold's treatment artifact would evict common workflow content —
the caps are per-component and independent of what else is in the prompt.
Asymmetric loss would require a total-context-budget allocator, and none
exists. That is a structural argument, and it is strong, but it is not the
mechanical margin measurement your instruction asks for.

**Status: `PENDING_AUDIT`.** Closure requires: author the treatment artifacts →
render a representative late-campaign proposer prompt for both arms → tokenize
→ record the margin to the `gpt-5.5` context window. I did not change context
behaviour and did not guess the margin.

### 9.9 API retry policy — FROZEN policy — **audit shows ONE material divergence**

**Frozen policy.** Retryable API/infrastructure failures retry indefinitely
until the same intended request completes, preserving the same model authority,
with no fallback model, and without consuming a scientific proposal attempt.
Deterministic, non-recoverable request defects must **fail closed** rather than
spin forever.

**Audit result — the current implementation, exactly** (`llm_bridge.py:1264-1322`):

| failure class | current behaviour | matches frozen policy? |
|---|---|---|
| 429 rate limit / quota | **retry indefinitely** (`max_retries=None`), honours the API-suggested `RetryInfo` delay when present | ✅ |
| 5xx server errors | **retry indefinitely** | ✅ |
| other 4xx — auth, bad request, model not found, unsupported parameter | **raised immediately**, `raise` before the retry bookkeeping | ✅ **exactly the fail-closed behaviour you specified** |
| **timeout (`APITimeoutError`)** | **bounded at 3 total attempts**, then raises | ❌ **diverges** |
| **connection failure (`APIConnectionError`)** | **bounded at 3 total attempts**, then raises | ❌ **diverges** |
| content-level failure (HTTP 200, empty or non-JSON body) | bounded, `_CONTENT_RETRY_BUDGET = 3`, waits 2 s → 16 s | separate axis, not addressed by the frozen policy |

**Backoff:** `2.5 → 5 → 10 → 20 → 40 → 60 → 60 …`, doubling to a **60 s cap**
(`_RETRY_INITIAL_WAIT = 2.5`, `_RETRY_MAX_WAIT = 60.0`). **No jitter.** SDK-level
retry is disabled (`max_retries=0`) so this loop is the single authority.

**The divergence — F-LLM-2 — and why it is not simply a bug.** Your frozen
policy lists "connection failure" and "transient timeout/network failures" as
retry-indefinitely classes. The implementation deliberately bounds them, and
the code carries the reasoning at the declaration:

> *"A timeout is not a 'try again shortly' signal: it says the request did not
> fit the configured budget, and repeating it unchanged reproduces the same
> outcome. Left unbounded — as it was until 2026-08-17 — `timeout=120s` plus
> `max_retries=None` became a loop that killed a legitimate 150 s request
> forever, made no progress, and billed every attempt. A real Gate run hit
> exactly that, ten times, and never reached the phase it was testing."*

That is the same principle as your own "do NOT blindly retry forever on
deterministic, non-recoverable defects" — a request that cannot fit a fixed
timeout is deterministic with respect to that timeout, not transient. The
current 600 s timeout makes the pathological case far less likely than the
120 s that produced the incident.

**This needs your ruling, and I am not resolving it.** Three options:

| option | effect |
|---|---|
| **A** — ratify current behaviour | Amend the frozen policy to name timeout/connection as bounded-with-cause. Zero code change. |
| **B** — raise `timeout_retries` | Keep the mechanism, widen the budget (e.g. 3 → 10). Small config change; preserves the anti-pathological-loop property. |
| **C** — unbounded | Matches the policy as literally written, and reinstates exactly the 2026-08-17 incident shape if a request ever legitimately exceeds 600 s. |

My recommendation is **B**, and it is a recommendation, not a decision: it
honours your intent (a transient network blip must never burn a scientific
attempt) without discarding evidence bought by a real Gate failure.

**`API retry != scientific attempt` — PARTIALLY VERIFIED.** A distinct record
status `skipped_infrastructure_failure` exists
(`nodes/ml_hyperparameter_tune_agent/records.py:313`) alongside
`TERMINAL_INFRASTRUCTURE_FAILURE` (`runtime.py:66`), so the framework does
classify infrastructure failure separately from scientific failure. What I have
**not** traced end-to-end is whether a raised `LLMBridge` exception reaches that
classification on every path, or whether some path lets it consume a tuner
attempt. That trace is bounded but real work. **`PENDING_AUDIT` — F-LLM-3.**

**Status: `FROZEN_POLICY_PENDING_IMPLEMENTATION_AUDIT`.** Not patched here.

### 9.10 Execution concurrency / band scheduling — **SUPERSEDED by §21** (2026-08-26)

> **SUPERSEDED.** Max-2-per-pod with dynamic backfill is replaced by four
> exclusive H100 GPUs, one band each. Retained below as history.


**Decision — this supersedes the four-way posture for the formal campaign.**

```text
maximum_active_bands_per_pod = 2
```

Initial active pair: **`10-14`** and **`15-19`**. The remaining two bands are
queued. Dynamic backfill: when an active band **completely terminates**, the
next queued band starts immediately in the freed slot; when the other slot
frees, the final queued band starts. **Never more than two active bands on one
pod.**

A band is **not** complete merely because one round ended, one training
subprocess ended, or one log went idle. The terminal chain/band authority
decides.

**The queue and its order must be identical between goldpod and blindpod.**

**Audit result — band identities RESOLVED.** The operator's names map exactly
onto the repository's formal band identifiers, with no reinterpretation needed:

```bash
# sdsc_submission_scripts/launch_band_fleet.sh:64
FLEET_BANDS=("0-3" "4-9" "10-14" "15-19")
```

| role | band | mapping |
|---|---|---|
| initial slot 1 | `10-14` | exact match |
| initial slot 2 | `15-19` | exact match |
| queued | `0-3`, `4-9` | the remaining two |

**Queue order — FROZEN (operator ruling, 2026-08-26):**

```text
initial active : 10-14, 15-19
queued         : 0-3, 4-9        (in that order)
max active     : 2
on terminal    : immediately launch the next queued band in the freed slot
```

Identical in both arms.

Each band resolves to the DS8-mandatory pair `--data_scope <band>` +
`--health_gate_files <band files>`, and enters run identity as
`${ARM}_band${BAND}` for both workspace and run_name, so two chains can never
share a workspace. **The queue order for the two queued bands is not yet ruled**
— see §9.16.

**PENDING_IMPLEMENTATION — F-BAND-1. The capability does not exist.**
`launch_band_fleet.sh` launches **all four bands at once**: it loops
`FLEET_BANDS`, `nohup`s each launcher, separates them only by
`H100_FLEET_STAGGER_SECONDS=60`, and prints *"4 band chains launched"*. There
is **no** max-concurrency limiter, **no** queue, **no** terminal-state watcher,
and **no** backfill. It writes a PID manifest and exits.

Max-2 dynamic backfill therefore requires new scheduling capability:
a slot-limited supervisor that watches for terminal band state and launches the
next queued band. That is release-lane work, reported not patched.

**Status: concurrency policy `FROZEN`; band identities `VERIFIED`;
scheduler `PENDING_IMPLEMENTATION`.**

### 9.11 Per-band VRAM admission — **SUPERSEDED by §21.4** (36 GiB → 60 GB)

> **SUPERSEDED.** Retained below as history.


**Decision.** Provisional target **36 GiB per active band**. Final value is
`HARDWARE_DERIVED`, pending a bounded testpod witness using the actual **two-way**
formal topology.

**Audit result — your arithmetic checks out against the shipped posture
constants, exactly.** `sdsc_submission_scripts/h100_posture.env` (v3) declares:

```bash
H100_MAX_ACTIVE_PER_CARD=4
H100_CORESIDENT_CHAINS=4
H100_PER_CHAIN_VRAM_GB=18
H100_QUAD_AGGREGATE_VRAM_GIB=$((4 * 18))   # = 72
H100_CARD_TOTAL_VRAM_GB=80
H100_MIN_CARD_VRAM_HEADROOM_GB=6
```

So the current four-way posture already commits **72 GiB aggregate** with 8 GB
nominal remaining. Your two-way proposal is `36 × 2 = 72` — **the identical
aggregate**, redistributed. It satisfies the preflight's own admission
arithmetic (`72 + 6 = 78 < 80`) with the same margin the shipped posture
already accepts.

That is a materially better position than a new number would have been: the
aggregate ceiling and its headroom are unchanged, so only the *per-chain*
attribution moves. It also does exactly what you intended for 10M–500M
exploration — a chain's VRAM ceiling doubles from 18 GiB to 36 GiB.

**Four posture values are wired to the per-chain figure and would all move
together** (recorded so the change is not made piecemeal):

| symbol | current | under two-way |
|---|---|---|
| `--trial_vram_budget_gb` / `--formal_vram_budget_gb` | 18 | 36 |
| `SIDERIUS_GPU_VRAM_QUOTA_GB` (per-worker attribution threshold) | 18 | 36 |
| `SIDERIUS_PAIR_VRAM_CEILING_GIB` / `--gpu_pair_ceiling_gib` (aggregate) | 72 | **72 — unchanged** |
| `H100_CORESIDENT_CHAINS` | 4 | 2 |

**Named hazard preserved from the posture file.** `SIDERIUS_GPU_VRAM_QUOTA_MIB`
is deliberately NOT set: it is a per-**user** total that *clamps* the aggregate
ceiling, and setting it to a per-chain value would refuse every chain's
admission. That hazard is unchanged by the two-way switch and must not be
"tidied up" during it.

**Status: `PROVISIONALLY_FROZEN`. Final value `HARDWARE_DERIVED /
PENDING_TWO_WAY_TESTPOD_WITNESS`.** If the witness shows 35 GiB is the stable
figure, 35 is the answer — the number is not to be defended for its own sake.

### 9.12 LLM / provider concurrency — FROZEN fairness principle

**Decision.** goldpod and blindpod must have equivalent LLM/API concurrency
opportunity. Neither arm may receive systematically greater API concurrency or
retry opportunity.

> **`CONDITIONAL_ON_BLIND_EXECUTION` (2026-08-26).** The between-arm fairness
> requirement is preserved in full and reactivates if Blind runs. Under the
> Gold-only campaign there is no second arm to be unfair to, so this does not
> gate the Gold launch. **The headroom finding below is unaffected and still
> applies to Gold's own four concurrent bands.**

**Audit result — the concurrency shape changes materially under §9.10.** The
existing preflight smoke (`campaign_llm_smoke.py`) fires **8** parallel calls,
sized for *"eight co-resident band chains (two fleets of four)"*. Under max-2
per pod the campaign-wide simultaneous chain count drops from 8 to **4**. Under
the Gold-only §21 topology it is **4 concurrent Gold bands on one host** rather
than 2 pods x 2 bands — the peak count is unchanged, so the headroom conclusion
stands. (Historical derivation follows: 2
pods × 2 bands), so the smoke's default N is now an over-estimate rather than a
match. It is a probe default, not a limiter, so nothing breaks — but it should
be re-sized so the preflight tests the shape the campaign will actually have.

**Constraint mechanism.** SIDERIUS imposes no LLM concurrency limiter of its
own; concurrency is emergent from how many chains are active. Rate limiting is
entirely provider-side.

**RESOLVED — F-LLM-4 CLOSED. There is large mechanical headroom; no fairness
scheduler is needed.**

Per the operator's ruling item 5, the expected burst was audited against the
**actual account rate-limit authority**, read from live response headers on the
production endpoint:

```text
x-ratelimit-limit-requests        10000        (RPM)
x-ratelimit-limit-tokens          4000000      (TPM)
```

**Expected campaign demand**, from real telemetry
(`reports/gate2_evidence_pr07c/**/token_usage.jsonl`, 25 observed production
calls on `gpt-5.5`):

| label | n | avg prompt | avg output | **max prompt** |
|---|---|---|---|---|
| `proposer.proposing` | 3 | 151,395 | 3,305 | **151,459** |
| `tuner.planner` | 10 | 26,630 | 3,257 | 33,326 |
| `tuner.reflector` | 1 | 17,809 | 1,039 | 17,809 |
| `proposer.causal_reasoning.correction` | 3 | 8,591 | 1,349 | 8,651 |
| `proposer.causal_reasoning` | 3 | 7,096 | 3,157 | 7,105 |
| `proposer.comparison` | 3 | 3,416 | 388 | 3,416 |
| `validator.code_review` | 2 | 2,447 | 428 | 2,603 |

**Arithmetic.** A chain is internally sequential — one LLM call in flight at a
time — so the campaign-wide concurrency is exactly the active chain count:
**2 pods × 2 active bands = 4 concurrent requests.**

| measure | campaign demand | account limit | headroom |
|---|---|---|---|
| peak concurrent requests | **4** | 10,000 RPM | **~2,500×** |
| absolute worst-case token burst — all 4 chains firing their largest observed call at the same instant | 4 × 151,459 ≈ **606k** | 4,000,000 TPM | **6.6×** |
| sustained, pessimistic — each chain completing a full observed LLM cycle (859,570 tokens) every 10 min | ≈ **344k TPM** | 4,000,000 TPM | **11.6×** |

The sustained figure is deliberately pessimistic: it assumes an iteration's
entire LLM workload repeats every ten minutes, whereas real iterations are
**training-bound**, with LLM calls occupying a small fraction of wall time.

**Conclusion.** Even the worst case sits at ~15% of one minute's token budget
and ~0.04% of the request budget. Whether goldpod and blindpod share one
`OPENAI_API_KEY` is therefore **immaterial to fairness at this scale** — a
rate-limit event is not a realistic contention mode. **No limiter was invented,
and none is warranted.** The shared-vs-separate credential question no longer
needs an operator decision on fairness grounds; it remains a free operational
choice (separate project keys would give cleaner per-arm cost attribution,
which is an accounting convenience, not a scientific requirement).

**One consequential note:** the largest observed prompt is **151,459 tokens**
and it **succeeded**, which is direct evidence that the effective context
window on this path is at least ~155k. That is now the anchor for the §9.8
context audit.

**Status: principle `FROZEN`; mechanism `VERIFIED — ample headroom`.**

### 9.13 OpenAI tool calling — **NOT_APPLICABLE (proven)**

**Audit result. Your belief is confirmed mechanically.** The production OpenAI
request exposes **no provider-side tools**.

* `tools=` and `tool_choice="auto"` appear at exactly one place in the entire
  codebase: inside `LLMBridge.tool_call()` (`llm_bridge.py:1849-1850`).
* **`tool_call()` has ZERO production callers.** Every call site is a test
  (`tests/unit/agent/test_llm_bridge.py`, `test_record_usage.py`,
  `test_force_crash.py`, `test_stub_llm_bridge.py`, `tests/helpers/`), plus the
  stub bridge's own `NotImplementedError` message.
* The two production paths — `_chat_json` (JSON-mode, used by every node) and
  `generate_text` — send `model`, `messages`, and on the JSON path
  `response_format`. No `tools` key.

So the execution mode is unambiguously:

```text
SIDERIUS workflow node
  -> constructs prompt + schema
  -> direct OpenAI Chat Completions request (no tools)
  -> parses response, validates through Pydantic
  -> the FRAMEWORK executes the resulting capability
```

and **not** an OpenAI-side autonomous tool-calling agent with filesystem,
shell, web or code-execution access. No such tool is defined anywhere.

**Record: `OPENAI_TOOL_AVAILABILITY = NOT_APPLICABLE`.** Model/plugin/loss/
optimizer action space belongs to the later action-space decision area (topic
5), not to Part 2. Removed from further Part 2 consideration.

### 9.14 Common prompt / workflow versioning — FROZEN

**Decision.** All non-treatment prompt and workflow authorities are identical
between goldpod and blindpod, content-hashed, with the exact version recorded:
system prompts, proposer base prompt, implementor prompt, validator prompt,
tuner prompt, reflector prompt, interpretation prompt, workflow templates, and
any other model-visible static instruction.

**The only approved model-visible proposer difference:**

```text
gold  :  common proposer context + frozen advice artifact + frozen prior-baseline artifact
blind :  the same common proposer authority + explicitly no treatment
```

**Before formal launch, perform an effective/rendered context comparison — not
merely source-file equality.**

**PENDING_IMPLEMENTATION — F-PROMPT-1.** No prompt hash or prompt version is
pinned anywhere in the run identity. A repository-wide search finds
prompt-shape assertions only in tests
(`test_step12_pr12a_c0_legacy_parity.py`) and one Gate script
(`scripts/step12_pr12a_gate1.py`). Today the release SHA is the only transitive
guarantee, and rendered-context comparison machinery does not exist — the same
gap as T-IMPL-3 in §5.11, and the two should be closed together.

### 9.15 Recorded limitations of Decision Area 2 — **CORRECTED after live probe**

The earlier draft of this section overstated the sampling limitation. The live
probe (§9.4, §9.5) narrows it substantially. Corrected record:

1. **Sampling regime — NOT a live risk on the two classic axes.** `temperature`
   is not tunable on `gpt-5.5` (only its fixed default `1` is accepted) and
   `top_p` is an unsupported parameter on this model. There is no
   provider-side value on either axis that could drift between the two arm
   launches. **Reasoning effort** *is* a real control, and once the §9.4
   implementation lands it will be **explicitly pinned to `high`** rather than
   left to an intermediate default — closing the axis that actually mattered.
2. **LLM sampling is non-deterministic and the campaign says so.** The seed is
   accepted but inert and no `system_fingerprint` is returned (§9.6). Recorded
   as `PROVIDER_CONTROLLED_STOCHASTICITY`, not papered over.
3. **A stable model id is not a stable model — MITIGATED by §9.17.** Pinning
   the immutable snapshot `gpt-5.5-2026-04-23` removes alias drift as a
   campaign risk. What remains unmitigable is a provider-side change to a
   snapshot itself, which is out of anyone's control and vanishingly less
   likely than alias movement.

**Residual mitigation — CORRECTED 2026-08-26.** This previously read *"launch
goldpod and blindpod within a narrow time window."* **That mitigation is void:
the campaign is GOLD-ONLY (`D-CAMP-1`) and there is no paired launch.**

The residual exposure is now **intra-Gold**, and it is real: Gold runs **four
bands × up to 20 iterations, concurrently, potentially over days**, against a
**mutable alias**. A provider update mid-campaign means different bands — or
different iterations of the *same* band — run against different models. **See
§21.7 for the precise statement of what that does and does not contaminate.**
Limitations 2 and 3's residue must still be stated explicitly in the campaign
manifest rather than left implied.

### 9.16 Decision Area 2 — status summary (updated after operator ruling + live probe)

| item | status | value |
|---|---|---|
| OpenAI config authority | **FROZEN** | `llm_configs/openai_tiered_pro.json`, sha256 `fc3d95ec…9475`, Chat Completions |
| gold/blind LLM symmetry | **FROZEN** | identical for every role |
| model fallback | **FROZEN** | DISABLED — **VERIFIED_DISABLED** |
| **reasoning effort** | **FROZEN: HIGH** | probe-confirmed accepted + effective; omitted ≠ high. Implementation `PENDING_IMPLEMENTATION` (F-LLM-5) |
| **temperature / top_p** | **FROZEN** | probe-confirmed **not tunable / unsupported** on `gpt-5.5`; omission is the only legal shape |
| **LLM seed** | **FROZEN** | `PROVIDER_CONTROLLED_STOCHASTICITY` — probe-confirmed accepted but inert, no `system_fingerprint` |
| token / spend budget | **FROZEN** | NONE — **VERIFIED ABSENT** |
| context / truncation | **PENDING_AUDIT** | stateless; per-component char caps; largest observed prompt **151,459 tok, succeeded** |
| API retry | **FROZEN_POLICY_PENDING_IMPLEMENTATION_AUDIT** | one divergence; four options in §9B |
| max active bands per pod | ~~2, dynamic backfill~~ **SUPERSEDED by §21** | 4 exclusive GPUs, one band each |
| **band queue order** | **FROZEN** | active `10-14`, `15-19`; queued `0-3`, `4-9` |
| band scheduler | ~~`F-BAND-1`~~ **MOOT under §21** | exclusive one-band-per-GPU needs no backfill queue |
| per-band VRAM | ~~36 GiB~~ **SUPERSEDED by §21.4** | **60 GB**, `HARDWARE_DERIVED` |
| **LLM concurrency fairness** | **FROZEN / VERIFIED** | 10,000 RPM · 4,000,000 TPM vs 4 concurrent chains — **F-LLM-4 CLOSED**. Under §21 the derivation changes (1 pod × 4 bands, not 2 × 2) but the peak count is unchanged at 4, so the headroom conclusion stands |
| OpenAI tool availability | **NOT_APPLICABLE** | proven — zero production callers |
| common prompt versioning | **FROZEN** | hash-identical; pinning `PENDING_IMPLEMENTATION` (F-PROMPT-1) |
| **model alias vs snapshot** | **PENDING_OPERATOR_DECISION** | `gpt-5.5` → `gpt-5.5-2026-04-23`; §9C |

**Operator inputs still required:** retry option A/B/C/**D** (§9B) · alias vs
snapshot pin, plus the `gpt-5.5` vs `gpt-5.5-pro` confirmation (§9C) ·
Q-LIT-1 option L1/L2/L3 (§9D) · Q-ISO-1 option I1/I2/I3/I4 (§9E).

**Closed since the last report:** reasoning effort · temperature/top_p · seed ·
queue order · LLM concurrency fairness.

---

## 9B. API TIMEOUT AND RETRY — **FROZEN** (operator ruling, 2026-08-26)

**Campaign decision — FROZEN:**

```text
request timeout = 600 seconds
model authority = unchanged on retry
fallback model  = FORBIDDEN
scientific proposal/attempt budget = must NOT be consumed merely because
                                     transport/API infrastructure temporarily failed

retry indefinitely   : 429 / rate limit · 5xx provider failures · connection
                       failures · transient network failures · retryable
                       timeout failures · temporary provider outages
fail closed          : malformed request · unsupported parameter · invalid
                       configuration · deterministic client programming error ·
                       permanently invalid credentials
```

### 9B.1 Current implementation vs the frozen policy

| policy class | current behaviour | verdict |
|---|---|---|
| request timeout 600 s | `DEFAULT_REQUEST_TIMEOUT_SECONDS = 600.0` | ✅ **already exact** |
| 429 → indefinite | indefinite; honours API-suggested `RetryInfo` delay | ✅ satisfied |
| 5xx → indefinite | indefinite | ✅ satisfied |
| deterministic 4xx → fail closed | `raise` fires before retry bookkeeping | ✅ satisfied |
| model authority unchanged | retry re-invokes the same closure; `model` captured from enclosing scope, unbindable | ✅ satisfied |
| fallback forbidden | no fallback path exists anywhere | ✅ **VERIFIED_DISABLED** |
| **connection failures → indefinite** | **bounded at 3 attempts** | ❌ **gap** |
| **retryable timeout failures → indefinite** | **bounded at 3 attempts** | ❌ **gap** |
| attempt budget not consumed by transport failure | `skipped_infrastructure_failure` / `TERMINAL_INFRASTRUCTURE_FAILURE` exist, but the raise-to-record path is not traced end-to-end | ⚠️ **unverified** |

### 9B.2 Backoff semantics — preserved, reported exactly

```text
schedule : 2.5s → 5s → 10s → 20s → 40s → 60s → 60s → …   (doubling, capped)
cap      : _RETRY_MAX_WAIT = 60.0 s
initial  : _RETRY_INITIAL_WAIT = 2.5 s
jitter   : NONE
SDK retry: disabled (max_retries=0) — the bridge's loop is the sole authority
429 delay: an API-supplied RetryInfo delay OVERRIDES the schedule for that
           attempt only; the next attempt resumes the normal schedule
```

This is compatible with the frozen policy and is **retained unchanged**.

### 9B.3 Implementation gaps

**F-LLM-2 — timeout/connection retries are bounded.** `DEFAULT_TIMEOUT_RETRIES
= 3` bounds `APITimeoutError` and `APIConnectionError`, then raises. The frozen
policy requires indefinite retry for both. `PENDING_IMPLEMENTATION`, routed to
the Supervisor.

**A design constraint the implementer must honour, stated once.** The bound
exists because of a real 2026-08-17 incident: with `timeout=120s` and unbounded
retry, a legitimate 150 s request was killed and re-issued forever, making no
progress and billing every attempt. The operator has frozen the timeout at
600 s rather than raising it further, so that failure mode is not structurally
impossible — merely much less likely.

The frozen policy's own wording is what resolves this: it says **"retryable
timeout failures"**, not "all timeout failures". The implementation must
therefore distinguish them rather than retry every timeout forever. The
discriminator that matters is whether the request could ever fit the budget:
a request that times out at 600 s **every time, identically**, is deterministic
with respect to that budget and must fail closed with an operator-visible
message, exactly as the current code's raise-path message already does. The
risk case is concrete and known — `proposer.proposing` already carries a
**151,459-token** prompt (§9.12), and prompt size grows over a campaign.

**F-LLM-3 — attempt-budget interaction unverified.** `PENDING_AUDIT`. Under the
frozen policy this is load-bearing: it decides whether the retry policy
protects scientific work or merely delays its loss.

---

## 9C. MODEL SNAPSHOT PINNING — **FROZEN POLICY** (operator ruling, 2026-08-26)

**Campaign decision — FROZEN:**

> Formal campaign model authorities must be pinned to **immutable model
> snapshots/revisions wherever the provider exposes such an authority.** A
> mutable alias must not be used for the formal campaign when an immutable
> snapshot is available.

### 9C.1 OpenAI — snapshot exists, pin it

Mechanically determined from the live models endpoint **and** confirmed from
the `model` field of actual completion responses (5 probe calls, all agreeing):

| field | value |
|---|---|
| provider | `openai` |
| currently configured alias | `gpt-5.5` (mutable) |
| **immutable snapshot** | **`gpt-5.5-2026-04-23`** |
| alias → snapshot mapping | verified live; every probe response returned `gpt-5.5-2026-04-23` |

**Minimal required config change — one file, eight strings, no code change:**

```text
llm_configs/openai_tiered_pro.json
    8 × "model_id": "gpt-5.5"  ->  "model_id": "gpt-5.5-2026-04-23"
        (interpret · propose.comparison · propose.reasoning · propose.proposing
         · implement · validate · tune.planner · tune.reflector)
```

The file's sha256 changes with it, so §9.1's recorded
`fc3d95ec…9475` must be updated in the same change. Nothing else in the
repository hardcodes `gpt-5.5` — the routing file is the single authority,
which is why the change is this small.

**Status: `PENDING_IMPLEMENTATION`** — routed to the Supervisor, not patched
here.

**One confirmation still owed by the operator.** The config is named
`openai_tiered_pro.json` and has been called "the OpenAI Pro config", but it
pins **`gpt-5.5`, not `gpt-5.5-pro`.** The `_pro` denotes the config *tier* (the
frontier routing file, versus `certify_minimal.json`), not the `-pro` model
variant. A separate `gpt-5.5-pro` / `gpt-5.5-pro-2026-04-23` pair exists in the
account. Pinning the wrong family would freeze a mistake, so this should be
confirmed before the pin lands.

### 9C.2 DeepSeek — **no immutable snapshot exists: recorded provenance limitation**

Per the ruling's instruction to record external mutability explicitly rather
than treat an alias as immutable. Queried live with the campaign credential:

```text
GET https://api.deepseek.com/models   ->  HTTP 200
    deepseek-v4-pro
    deepseek-v4-flash
    deepseek-v4-flash-vision-exp
```

**Every DeepSeek identifier is a mutable alias. The provider exposes no dated
or immutable revision at all.** There is nothing to pin.

**Recorded as an explicit provenance limitation:**

```text
PROVENANCE_LIMITATION — lit_review.main / lit_review.search
    provider  : deepseek
    model     : deepseek-v4-pro   (MUTABLE ALIAS — no immutable revision offered)
    exposure  : the model behind this identifier may change at any time,
                including between the goldpod and blindpod launches, with no
                signal available to SIDERIUS or to the campaign record.
    mitigable : NO — not by configuration; the provider offers no alternative.
```

**Scope note.** This limitation exists **only if literature review is part of
the campaign.** `lit_review` is the sole non-OpenAI authority in the frozen
configuration. If §9D resolves to disabling lit-review, the limitation
disappears entirely and the campaign becomes wholly snapshot-pinned. That makes
the two decisions related, and §9D should be settled first.

---

## 9D. LITERATURE REVIEW AND TIDMAD PRIOR ISOLATION — frozen intent, **no mechanism exists**

**Campaign decision — FROZEN scientific intent (operator ruling, 2026-08-26):**

> Literature review must NOT independently recover TIDMAD-specific prior
> information that belongs to the treatment.
>
> **Both** goldpod and blindpod retain the **same general literature-review
> capability**, but TIDMAD-specific prior / official-baseline retrieval is
> excluded from that channel for **both** arms.
>
> goldpod receives TIDMAD prior ONLY through the frozen Part 1 treatment
> artifact. blindpod receives no TIDMAD prior through either channel.
>
> **Do not solve this by giving blindpod a weaker literature-review capability
> than goldpod.**

Excluded-information classes, at minimum: official TIDMAD baseline results ·
historical baseline score · historical per-file result vector · official
baseline HealthGate/health-check result · exact historical baseline
architecture/recipe · any other TIDMAD-specific prior evidence that would
materially reproduce the Part 1 treatment information.

This supersedes the earlier L1/L2/L3 options with a fourth, better-specified
one: **symmetric capability, asymmetric-free corpus.**

### 9D.1 Mechanical audit of the current path

| question | answer |
|---|---|
| **whether it runs** | Available on the formal path; ships `enabled: false`; resolution priority **CLI > YAML > False**. `launch_prior_baseline_experiment.sh` turns it ON for the WITH arm and explicitly OFF for the WITHOUT arm |
| **when it runs** | Inside the iteration loop (`workflows/model_exploration.py:2634`), after interpretation, before proposal |
| **how often** | **Every iteration, unconditionally.** The gate function is `del interp_output; return enabled` — content-based gating is declared "reserved for future" and not implemented. No cadence control exists |
| **provider / model** | `deepseek` / `deepseek-v4-pro` for both sub-slots (`main` = compression + synthesis, `search` = search-decision). **The only non-OpenAI authority in the campaign** — and a mutable alias (§9C.2) |
| **search mechanism** | Semantic Scholar Graph API, `https://api.semanticscholar.org/graph/v1`; throttled to ≥ 1.1 s between requests; `S2_MAX_RETRIES = 3`; per-process cache |
| **query generation** | **LLM-authored.** The search-decision call emits queries anchored on the task description, which is resolved from `configs/task_config.yaml` — i.e. from the TIDMAD task statement itself |
| **accessible corpus** | The whole of Semantic Scholar. `max_rounds: 3`, `results_per_query: 10`, `escalation_allowed: true`, `max_escalations_per_round: 2` |
| **what reaches the proposer** | `findings` → `expert_context` (synthesised, **equations and pseudocode inline in `content`**) and `agent_card` → `agent_cards`. `new_vocab_candidates` and `suggested_mindset` are empty in v1. `retrieved_papers` is audit-trail only and explicitly never crosses the edge |
| **can TIDMAD prior be recovered today?** | **YES — directly and by configuration.** |

### 9D.2 How TIDMAD prior is recovered today

`configs/lit_review_config.yaml` declares:

```yaml
root_papers:
  - source_type: arxiv
    identifier: "2406.04378"          # TIDMAD primary paper
    verbosity: 1                      # full PaperExtract
```

**arXiv 2406.04378 is the TIDMAD primary paper.** As a *root paper* it is
resolved **at agent start, on every iteration, at full-extract verbosity** —
delivering the official baseline architectures, their reported scores and their
training setup straight into synthesis, and from there into the proposer's
`expert_context`.

### 9D.3 The enforcement problem — **no mechanism exists, and config alone cannot close it**

**There is no denylist, blocklist, or exclusion mechanism anywhere** in the
paper resolver (`agent/skills/paper_resolver_skill/`) or the lit-review node.
A repository-wide search for `denylist` / `deny_list` / `blocklist` /
`exclude` / `forbidden` across both returns nothing relevant.

Enforcing the frozen invariant therefore requires **new capability**, and it
decomposes into two problems of very different difficulty:

**Problem 1 — the root paper. Easy, config-only.** Removing the
`2406.04378` entry from `root_papers` stops the deterministic, guaranteed
delivery. This is a one-line config change and it closes the dominant path.

**Problem 2 — dynamic search rediscovery. Hard, and it is the honest blocker.**
Queries are **LLM-authored from the TIDMAD task description**, and the corpus
is all of Semantic Scholar. A search anchored on "broadband signal denoising,
axion detection, SQUID time series" is *reasonably likely* to surface the TIDMAD
paper and its successors on its own merits — that is the search working
correctly. Removing it from `root_papers` does not prevent the search from
finding it.

Closing Problem 2 requires an exclusion enforced at the **paper-resolution
boundary** — a campaign-level identifier denylist (arXiv id, S2 paper id, DOI,
and title match) applied to *every* resolution path: root papers, search hits,
and escalations alike, with each refusal recorded so the exclusion is
auditable rather than assumed. Symmetric by construction: the same denylist in
both arms, so capability stays identical and only the corpus is trimmed.

**Residual honesty, which the operator should see before this is called
closed.** An identifier denylist cannot exclude a *different* paper that
restates TIDMAD's baseline numbers — a survey, a citing work, a successor
paper. Exclusion by identifier is enforceable and auditable; exclusion by
*semantic content* is not, without an additional judgement layer that would
itself become an unreviewed campaign variable. The achievable guarantee is
therefore: **no TIDMAD-identified source reaches either arm's lit-review
channel**, not **no TIDMAD-derived fact can possibly appear**.

### 9D.4 Disposition

| element | status |
|---|---|
| scientific intent (symmetric capability, TIDMAD prior excluded both arms) | **FROZEN** |
| lit-review enabled state for the formal campaign | **PENDING_OPERATOR_DECISION** — the frozen intent says both arms keep the capability, which implies ON in both; the shipped default is OFF in both and the shipped launcher makes it the arm variable. This needs an explicit ruling |
| root-paper removal (Problem 1) | `PENDING_IMPLEMENTATION` — config-only |
| resolution-boundary denylist (Problem 2) | `PENDING_IMPLEMENTATION` — **new capability**, no mechanism exists |
| `reference_data/root_papers_cache/` | `PENDING_IMPLEMENTATION` — the cold-start checklist RETAINS this cache by default; if it holds a TIDMAD extract from a prior run, removal from config does **not** evict it. Must be cleared for the formal campaign |
| semantic-restatement residue | **accepted limitation**, to be stated in the campaign manifest |

**Reported per the ruling's instruction** ("if clean symmetric exclusion is not
possible with the current architecture, stop and report the options"): clean
symmetric exclusion **is** achievable at the identifier level and is not
achievable at the semantic level. The operator should decide whether the
identifier-level guarantee is sufficient, or whether disabling lit-review in
both arms is preferred as the only exclusion that needs no new machinery and no
residual caveat.

---

## 9E. `--baseline_isolation` SEMANTIC CENSUS — **semantic mismatch reported**

Traced from producer through every consumer to runtime behaviour, without
inferring anything from the flag name.

### 9E.1 Producer chain

```text
launch_prior_baseline_experiment.sh:167   --arm without-prior-art => --baseline_isolation
  -> _chain_common.sh:370       parses to BASELINE_ISOLATION=1
  -> _chain_common.sh:651       re-emits --baseline_isolation onto the child argv
  -> run_one_iteration.py:1698 (flag) / :1826 (LaunchIdentity)
  -> workflows/run_config.py:143
  -> core/run_invariants.py:184,553   pinned into run_invariants_lock.json
  -> run_one_iteration.py:740   written into the iteration manifest when True
```

Recorded **positively**: `run_invariants.py:406` drops the key when `False`, so
`True` is an explicit, resumable, tamper-evident fact.

### 9E.2 Everything it changes — five distinct behaviours

**(1) Bundled model descriptions are refused — in three nodes.**
`ml_models/model_descriptions.py:79-128`. `get_model_description()` normally
searches four locations; under isolation the bundled
`ml_models/{model_type}/description.md` is **removed from the search list
entirely**. Plugin and workspace descriptions resolve unchanged; the
`FileNotFoundError` gains a `Refused under baseline_isolation (not searched)`
line. Threaded from the **proposer** (`:1812,1836,1941,2038,2097`), the
**interpreter** (`result_interpretation_agent.py:326`) and the **tuner**
(`ml_hyperparameter_tune_agent.py:1224`).

**(2) Proposer prompt example literals change.**
`agent/prompt_templates/proposal/__init__.py:40-62`:

```python
LEGACY_EXAMPLE_LITERALS   = {"example_model_type": "wavenet",  "example_sota_score": "5.57", …}
ISOLATED_EXAMPLE_LITERALS = {"example_model_type": "exemplar", "example_sota_score": "1.23", …}
```

Note `5.57` is a **genuine TIDMAD baseline score appearing as a prompt
literal** — which is precisely why the substitution exists.

**(3) The built-in architecture branch is removed from the offered action
space.** `render_available_models()` (`:399-465`) changes the branch sentence
from *"OR **propose** a new architecture OR **use a built-in** model_type"* to
*"OR **propose** a new architecture — bundled built-in model types are not
available in this run"*, and swaps the empty-registry fallback.

**(4) A proposal reaching for a bundled model is REFUSED, fail-closed.**
`workflows/model_exploration.py:1059-1104` raises `BaselineIsolationViolation`
when `proposal.model_name` **or** `baseline_config.model_config.model_name`
names any member of `BUNDLED_MODEL_TYPES`. Refused before the attempt directory
is renamed, before the implementor runs, long before the tuner. The attempt loop
converts the raise into `previous_failures` feedback, and an iteration that
never yields a compliant candidate **ends with no candidate at all**.

**(5) Pinned in the run-invariants lock and the iteration manifest.**

### 9E.3 The semantic mismatch — reported, not resolved

Effects **(1)** and **(2)** are *information* suppression and align with the
frozen blind boundary. Effects **(3)** and **(4)** are **action-space
restriction** — a different thing entirely.

Under `--baseline_isolation`, blindpod **cannot propose, reuse, train or tune
any shipped baseline architecture**, and burns proposal attempts when it tries.
goldpod, without the flag, keeps all of them.

Part 1 §5.10, **frozen**, states:

> *Outside the frozen treatment difference, goldpod and blindpod must have the
> same experiment-fixed authorities and the same allowed agent action space.*

**Enabling `--baseline_isolation` on blindpod alone therefore violates a frozen
Part 1 principle.** A goldpod win could be explained by *"goldpod was allowed to
use WaveNet and blindpod was not"* — an engineering-capability difference,
which is exactly the confound §5.10 exists to exclude.

This was coherent under the shipped #255 design, where the arm variable was
"prior art" broadly construed. It is **not** automatically coherent under Part
1's narrower treatment definition. Per the ruling — *"If it also changes
unrelated behavior, do NOT simply enable it by name. Report the exact semantic
mismatch for operator review."* — it is reported here and **not enabled**.

### 9E.4 Options for operator review

| option | blindpod effect | §5.10 fairness |
|---|---|---|
| **I1** — OFF both arms | full built-in action space both sides | ✅ satisfied. ⚠️ but `wavenet` / `5.57` literals and bundled descriptions then reach **both** arms — blindpod would see a real TIDMAD baseline name and score |
| **I2** — ON both arms | neither arm may use a shipped baseline; both get neutral literals | ✅ satisfied — symmetric restriction; also removes the `5.57` literal from blindpod. ⚠️ narrows the hypothesis space for both |
| **I3** — ON blindpod only (shipped behaviour) | blindpod loses built-ins | ❌ **violates frozen §5.10** |
| **I4** — split the flag: apply information effects (1)(2) symmetrically, drop action-space effects (3)(4) | blindpod keeps capability, loses prior information | ✅ scientifically cleanest. ❌ requires new capability — the flag is monolithic today |

**Recommendation (not a decision): I2 now, I4 if implementation effort is
acceptable.** I2 is symmetric, needs no code change, and costs little: goldpod's
frozen advice already tells it to *"explore new architectures … avoid
converging prematurely on a single familiar model family"*, so a goldpod leaning
on a shipped WaveNet is arguably not doing what the treatment asks. I4 is the
precise answer — blindpod should be denied prior *information*, not *capability*
— but splitting a monolithic flag is release-lane work with its own review.

---

## 9F. COLD-START AUTHORITY — frozen intent and the census

**Campaign decision — FROZEN (operator ruling, 2026-08-26):**

```text
blindpod : cold execution state  +  NO treatment information seed
goldpod  : cold execution state  +  the frozen Part 1 treatment information seed
```

**Terminology, frozen and binding.** *"goldpod is seeded"* means
**TREATMENT-seeded**, through the Part 1 information artifacts. It does **not**
mean pretrained-weight warm start, checkpoint warm start, inherited
research-memory state, or inherited previous-campaign state. Those remain
excluded from **both** arms unless the operator explicitly reopens Part 1.

**Neither arm may inherit:** prior TIDMAD baseline information · prior campaign
research memory · prior proposal/tuning history · prior run artifacts ·
persisted scientific conclusions · prior plugins/models created by an earlier
campaign run · treatment artifacts (blindpod) · warm-start checkpoints/weights.

### 9F.1 The cold-start authority already exists

`docs/gates/gate_testing_standard.md` — "Partial-scope rules", cold-start
checklist (arXiv U3, #259). It is explicit that cold start is **more than
omitting `--seed_paths`**: several caches survive a fresh workspace and silently
carry evidence or capability between runs. Worked **in order**:

| # | state | prescribed cold-start action | campaign note |
|---|---|---|---|
| 1 | chain workspace (`--workspace DIR`) | **CLEAR** — fresh/absent; a reused workspace resumes against its `run_invariants_lock.json` instead of starting cold | operator manual step |
| 2 | `--seed_paths` | **OMIT** entirely | launcher already refuses |
| 3 | `agent_generated/models/` + `_capability_index.json` | **CLEAR** — the proposer advertises this registry (Branch B) and the loader registers every `.py` at import; leftover plugins are prior evidence | operator manual step |
| 4 | `${SIDERIUS_CHAIN_WORKSPACE}/plugins/` | cleared by step 1 | — |
| 5 | `reference_data/root_papers_cache/` | **RETAIN by default** | ⚠️ **must be CLEARED for this campaign** — see §9D.4; it can hold a TIDMAD extract that config removal does not evict |
| 6 | runtime-calibration store (`$SIDERIUS_CALIBRATION_DIR`) | **RETAIN** — host calibration, not task evidence | ✅ consistent with cold *scientific* state |
| 7 | advice file (`--advice` / `--human_advice_file`) | **OMIT** for a cold run; the launcher refuses advice in **both** arms | ⚠️ **collides with Part 1** — goldpod's treatment *is* an advice-shaped artifact; T-IMPL-1 |

### 9F.2 Findings

**Items 1 and 3 are manual operator pre-launch steps** — the launcher does not
perform them. For a two-arm campaign they must be performed identically and
verifiably on both pods, which argues for making them a recorded preflight row
rather than a remembered habit. `PENDING_IMPLEMENTATION`.

**Item 5 must be overridden for this campaign.** The checklist's default is
RETAIN, on the reasoning that root-paper extracts are deterministic inputs
rather than run evidence. Under the frozen §9D isolation invariant that
reasoning no longer holds for the TIDMAD extract specifically.

**Item 7 is the Part 1 collision already tracked as T-IMPL-1.** The cold-start
discipline says omit advice; Part 1 requires goldpod to receive an immutable
advice artifact. These are reconciled by the artifact being a **frozen,
content-hashed campaign input** rather than an operator-authored run hint — but
the launcher's blanket refusal must still be changed for goldpod, and must
remain in force for blindpod.

**Not yet established:** whether any *other* persisted scientific state
(interpreter prediction pools, `vocab_link_confirmations`, accumulated key
findings, per-file-best tables, promotion/calibration provenance) survives a
fresh workspace. The checklist does not enumerate them. `PENDING_AUDIT` —
deferred to the audit register per the workflow update.

## 9A. CROSS-SECTION CONSEQUENCE — four-way → max-two — **SUPERSEDED by §21.10**

> **SUPERSEDED.** Both prior topologies are now non-applicable; §21.10 carries
> the current evidence relevance map. Retained below as history.


**This is a formal campaign design decision with consequences outside Decision
Area 2, recorded immediately per the operator's instruction.**

### 9A.1 Semantic relevance map for existing H100 evidence

Existing evidence is **not** invalidated wholesale. It is classified:

| evidence | class | still valid? |
|---|---|---|
| Q1 import provenance | platform | **valid** — topology-independent |
| Q2 hardware-profile resolution | platform | **valid** |
| Q3 platform execution / storage | platform | **valid** |
| Q4 minimum real lifecycle | platform | **valid** |
| **Q5 four-way co-residency calibration** | **topology-specific** | **NOT the formal campaign's admission authority** |
| Q6 watchdog calibration (#261) | **topology-specific** | regime-keyed — see 9A.2 |
| Q7 campaign topology semantics | **topology-specific** | must be re-read against max-2 |
| Q8 failure / restart witness | platform | **valid** |
| Q9 A/B launch rehearsal + arm symmetry | **topology-specific** | must rehearse the max-2 shape |

**Why Q5 specifically cannot carry over.** `gpu_c_coresidency_probe.sh` measures
a **QUAD** leg by construction: `PROBE_BANDS=("0-3" "4-9" "10-14" "15-19")`,
leg 2 = *"QUAD co-resident chains, started together"*. The value it produces,
`H100_CORESIDENCY_FACTOR`, is a **four-way wall-time slowdown factor**. A
two-way campaign has a different contention profile, and the posture file's own
warning against reusing a factor measured under a different topology (it
records the RTX 5090 pairwise figure as *"a STALE LOWER BOUND … must never be
reused here"*) applies with equal force in this direction.

**Do not interrupt an authoritative Q5 measurement in progress.** Its platform
value stands, and re-running it later is cheap relative to disturbing a live
qualification.

### 9A.2 Mechanisms that assume four-way and would need attention

| mechanism | assumption | consequence under max-2 |
|---|---|---|
| `h100_posture.env` v3 | `H100_MAX_ACTIVE_PER_CARD=4`, `H100_CORESIDENT_CHAINS=4`, `H100_PER_CHAIN_VRAM_GB=18` | needs a posture bump (§9.11) |
| `--execution_regime four_way_coresident` (passed by the posture) | regime label | **`dual_coresident` already exists** — `ExecutionRegime = Literal["single","dual_coresident","four_way_coresident"]` (`core/runtime_control/watchdog_profile.py:56`). The vocabulary needs no extension; the posture declares the wrong member. |
| watchdog profile resolution | keyed on `(device, regime)` | a max-2 run resolves a **different** key, so any H100 profile calibrated as `four_way_coresident` would not apply — which is the correct fail-safe, and means #261's H100 overlay work must target the regime the campaign actually declares |
| `launch_band_fleet.sh` | launches all four | §9.10 F-BAND-1 |
| `campaign_preflight.sh` R4 | requires a filled `H100_CORESIDENCY_FACTOR` | still required; the value must be the **two-way** one |
| `campaign_llm_smoke.py` default N=8 | two fleets of four | now over-sized; 4 matches the new shape |
| `H100_EXPECTED_QUAD_HOST_ANON_RSS_GB=47` | four-chain host RSS | two chains should need less; the check would simply be conservative, not wrong |
| `SIDERIUS_PREFLIGHT_WORKER_MEM_GIB=24` | worst case 4 simultaneous probe workers | worst case becomes 2 — the existing note already says this value was never re-derived for four |

### 9A.3 Required new evidence

```text
TWO_WAY_FORMAL_TOPOLOGY_REHEARSAL
    2 concurrent bands
    36 GiB admission each
    the same actual campaign launch shape
    dynamic backfill exercised (a terminal band must trigger a real slot refill)
```

This is a **topology-specific rehearsal, not a repeat qualification**. It
should be raised with the Supervisor **now**, so the four-way
`H100_CORESIDENCY_FACTOR` is never mechanically transplanted into a two-way
campaign posture.

## 10. DECISION AREA 3 — RANDOMNESS / SEEDS / ORDERING — **FROZEN**

**Operator ruling, 2026-08-26.** Parts 1 and 2 are unaffected.

The four `PENDING_AUDIT` items in §10.10 are implementation facts, not open
decisions. They do not reopen anything below.

### 10.1 Training ordering — FROZEN

```text
ordering  = sequential
shuffle   = false
```

**Rationale (operator).** Preserve the training-order semantics used by the
original TIDMAD paper.

**Consequence worth stating.** With `shuffle = false`, data *ordering* carries
no randomness at all — it is fully determined. The seed hierarchy below
therefore governs the remaining stochastic surfaces (initialization, stochastic
layers, any subsampling), not the sample sequence. The two decisions are
complementary, not redundant.

### 10.2 Gold/blind pairing — FROZEN

Corresponding goldpod and blindpod bands use **matched RNG seed authorities**.

### 10.3 Across-band randomness — FROZEN

Each band uses a **different fixed seed**. `A`, `B`, `C`, `D` are distinct and
**frozen before launch**.

```text
gold 0-3    <->  blind 0-3     same seed A
gold 4-9    <->  blind 4-9     same seed B
gold 10-14  <->  blind 10-14   same seed C
gold 15-19  <->  blind 15-19   same seed D
```

The literal values are `PENDING_IMPLEMENTATION` — they must be chosen and
recorded in the campaign manifest before launch.

### 10.4 Round-level randomness — FROZEN

Use **deterministic derived per-round seeds**. Conceptually:

```text
seed = f(campaign_seed, band_id, round_id, purpose)
```

**Do not reset every round to one identical seed.**

The derivation must be a pure function of those four inputs, so that a given
`(band, round, purpose)` is reproducible from the campaign seed alone and is
identical across arms by construction rather than by bookkeeping.

### 10.5 RNG authority — FROZEN

All framework- and training-controlled stochasticity derives from the explicit
campaign seed hierarchy, including where applicable:

* Python `random`
* NumPy
* PyTorch CPU
* PyTorch CUDA
* DataLoader workers / generators
* model initialization
* stochastic layers
* subsampling / augmentation

### 10.6 Model initialization — FROZEN

Corresponding gold/blind `(band, round)` executions use **matched
initialization seed authority**.

**Explicitly permitted divergence.** If architectures differ — which they
generally will, since architecture is `AGENT_CONTROLLED` — the resulting
parameter realizations need not be comparable. Both still derive from the
**same paired seed authority**. The guarantee is on the authority, not on the
realized tensors.

### 10.7 Agent scientific trajectory — `AGENT_CONTROLLED`

**Do not synchronize:** proposal sequence · architecture choices · loss
choices · tuner decisions · scientific search trajectory.

**Divergence here is an intended experimental outcome**, not a configuration
asymmetry. This is frozen §4 applied to Decision Area 3.

### 10.8 File / subset authority — `EXPERIMENT_FIXED`

Training files, splits, portions and subset-selection rules are
**EXPERIMENT_FIXED and identical across arms**.

If any subsampling is stochastic, corresponding gold/blind selections use
**matched seed authority**. Within the selected training data, the sequential
ordering of §10.1 is preserved.

### 10.9 Deterministic GPU kernels — **EXPLICITLY NOT REQUIRED**

Strict bitwise-deterministic CUDA/PyTorch execution is **not** required.

**Required instead:**

* explicit RNG provenance
* matched seed authority
* frozen environment

**Do not sacrifice H100 performance merely to obtain bitwise-identical GPU
kernels.**

The campaign therefore claims **seeded, provenance-complete, paired
randomness** — not bit-reproducibility. That claim must be stated as such in
the campaign manifest.

### 10.10 Part 3 audit items — `PENDING_AUDIT`

Deferred to the audit register per the planning-workflow update. None of these
reopens a decision above; each asks only whether the implementation already
satisfies it.

| id | question |
|---|---|
| **A3-1** | Can the current TIDMAD loader actually run `shuffle=false`, is it doing so today, and does that genuinely correspond to the original paper's sequence behaviour? |
| **A3-2** | Are Python `random`, NumPy, Torch CPU, Torch CUDA, DataLoader workers/generators and model init **all** genuinely governed by one unified seed authority — or does any of them fall back to an ambient/global seed? |
| **A3-3** | Does any stochastic subset/portion selection **bypass** the matched-seed authority? |
| **A3-4** | Do any current deterministic / CUDA flags **hiddenly change** the semantics just frozen above? |

**Context for A3-1, recorded so the auditor does not have to rediscover it.**
`CLAUDE.md` documents two known structural divergences between SIDERIUS and the
TIDMAD paper that bear directly on "training-order semantics": the paper trains
**four separate models per architecture** via a frequency-band split
(`ifile_checkpoint = [0, 4, 10, 15, 20]` in `train.py`) whereas SIDERIUS trains
a **single generalist model across all files**, and the paper
**re-initializes the optimizer per file** inside its `for ifile` loop whereas
SIDERIUS uses a single optimizer. A3-1 should report whether `shuffle=false`
alone reproduces the intended paper semantics given those differences, or
whether the correspondence is partial. **This is a reporting obligation, not a
challenge to the frozen decision** — §10.1 stands either way; the audit only
determines how the rationale should be worded in the manifest.

## 11. Hardware-derived values

The following must **not** be invented. They are `PENDING_TESTPOD_QUALIFICATION`
until testpod returns authoritative measurements:

* `H100_CORESIDENCY_FACTOR`
* H100 watchdog values
* H100 runtime calibration
* formal VRAM headroom
* any hardware-derived wall-time number

When qualification returns a measurement, record: the value · its provenance ·
the qualification row it satisfies · the evidence artifact · and the exact
RC/SHA on which it was measured.

---

## 12. Configuration inventory that must eventually be explicit

The frozen plan must cover, at minimum, every item below. Each will be assigned
a control class (§3) and an explicit materialised value before freeze. None is
decided yet.

**Release / environment** — exact v0.1.0 SHA · Python version · dependency lock
· environment identity · imports · CUDA / Torch · device profile · relevant
environment variables.

**Task / data** — task identity · problem type · data root authority · exact
files · train / validation / final split · hashes · portions · ordering ·
shuffle · sampling · scope semantics.

**Randomness** — global seeds · Python · NumPy · Torch CPU · CUDA · DataLoader ·
worker seed behaviour · proposer / tuner randomness where applicable · matched
gold/blind mapping · deterministic flags.

**Agent action space** — allowed model mechanisms · allowed plugin roots ·
architecture authority · loss authority · optimizer authority · scheduler
authority · batch-size authority · other tunable hyperparameters ·
unavailable / disallowed mechanisms.

**Training** — epoch limits · per-round training limits · early stopping ·
batch-size policy · precision · gradient behaviour · checkpoint policy ·
validation cadence · training objective · data portions · wall-time limits.

**Agent budgets** — max rounds · proposal attempts · tuning attempts ·
reflection behaviour · LLM call budget · token budget · retry budget.

**LLM** — provider · model by role · reasoning level · temperature · top_p ·
max output tokens · context policy · timeout · retry · backoff · concurrency ·
fallback · tool availability · system prompt version · node prompt versions.
(Census: §8.)

**Metrics** — Golden Metric · score direction · aggregation · secondary metrics
· diagnostics · validation metrics · training objective vs evaluation metric
separation.

**HealthGate** — exact roster · blocking vs recording · threshold values ·
evidence units · failure disposition · non-finite handling · collapse handling ·
plugin authority.

**Hardware / runtime** — H100 co-residency factor · VRAM admission · headroom ·
watchdog thresholds · runtime profile · process limits · CPU / thread limits ·
concurrency.

**Persistence** — cold start · restore policy · checkpoint semantics · research
memory · plugin persistence · cross-round state · cross-chain isolation ·
cross-arm isolation.

**Failure policy** — invalid candidate · invalid training result · framework
crash · child-process crash · chain failure · pod loss · API failure · LLM
timeout · retry semantics · restart semantics · same-seed restart behaviour.

**Treatment** — exact gold advice artifact · exact prior-baseline artifact ·
injection node · injection timing · immutable hashes · blind absence semantics ·
leakage audit. (Semantics frozen: §5.)

**Output / provenance** — run ID · arm ID · band ID · chain ID · exact release
SHA · effective config · child argv · environment manifest · treatment manifest
· RNG manifest · artifact hashes · reports · failure status.

---

## 13. Configuration freeze process

```text
DRAFT  ->  OPERATOR-REVIEWED  ->  FROZEN
```

Before `FROZEN`, the actual effective campaign configuration is mechanically
rendered, and the following must be proven:

1. no campaign-relevant implicit defaults remain;
2. no unapproved environment inheritance remains;
3. no goldpod/blindpod difference exists outside `TREATMENT` — **`CONDITIONAL_ON_BLIND_EXECUTION`**; not a Gold-only freeze condition;
4. every `AGENT_CONTROLLED` field grants equal authority in both arms;
5. every `HARDWARE_DERIVED` field cites its evidence;
6. every `EXPLICITLY_DISABLED` feature is genuinely disabled, not merely
   absent.

The frozen plan must name an exact machine-readable campaign manifest.

---

## 14. testpod rehearsal

After the final release candidate and the campaign configuration are frozen,
testpod runs a **bounded engineering rehearsal**.

The rehearsal may verify: launch plumbing · treatment injection · effective
config · band identity · resource admission · persistence · restart behaviour ·
reporting · failure semantics. **Blind-absence verification is
`CONDITIONAL_ON_BLIND_EXECUTION`** and is not required for a Gold-only
rehearsal.

**The rehearsal's scientific scores must NOT be used** to optimise advice,
scientific thresholds, the action space, model choices, loss choices, or
campaign budgets — unless the operator explicitly reopens the campaign design.

Rehearsal is engineering evidence. It is not a tuning pilot, and testpod results
are never part of the formal gold/blind comparison.

---

## 15. Formal launch preconditions — **GOLD-ONLY** (corrected 2026-08-26)

> **SUPERSEDED SHAPE.** This section previously required a *paired* Gold+Blind
> launch and listed Blind-dependent gates among the preconditions for launching
> at all. **The current official campaign is GOLD-ONLY.** The old policy is
> retained as history in §15.3 and is not deleted.

### 15.1 GOLD launch preconditions — the operative list

Launch of the Gold campaign requires **all** of:

* final exact qualified release, tagged `v0.1.0`
* campaign plan `FROZEN`
* machine-readable campaign manifest `FROZEN`
* testpod rehearsal PASS
* **goldpod POSITIVE treatment audit PASS** (§5.8) — every Gold proposer round
  receives the intended immutable artifacts, hashes match the frozen authority,
  no round silently omits or mutates the treatment
* Gold host topology verified (§21.2, `A-HW-VERIFY-1` — **DISCHARGED**)
* canonical data present and manifest-verified at the destination (`D-DATA-2`)

**No Blind-dependent condition gates the Gold launch.**

### 15.2 BLIND preconditions — `CONDITIONAL_ON_BLIND_EXECUTION`

The following are **preserved in full** and **reactivate if and only if** Blind
is executed for a formal quantitative treatment comparison. **They do not block
or invalidate completed Gold, and if Blind is never run none of them applies:**

* blindpod NEGATIVE leakage audit PASS (§5.7)
* gold/blind effective-config symmetry PASS
* all expected treatment asymmetries PRESENT, no unexpected asymmetries
* the §21.6 temporal-separation provenance record, including per-arm resolved
  model snapshots and concurrent host baseline load
* arm-comparability apparatus in `D-ARM-1`

### 15.3 Superseded — the previous paired-launch policy (history)

The earlier text required: *"gold/blind treatment audit PASS · gold/blind
effective-config symmetry PASS · all expected treatment asymmetries PRESENT · no
unexpected asymmetries"* as launch preconditions, and *"goldpod and blindpod are
launched within a narrow time window where practical."* **Both are superseded by
the Gold-only ruling and by §21.3's Gold-first execution order.** Retained so the
change is visible rather than silent.

---

## 16. DECISION AREA 4 — TASK & DATA SEMANTICS — **FROZEN** (except evaluation-portion execution semantics)

**Operator ruling, 2026-08-26.**

```text
STATUS: FROZEN except exact evaluation-portion execution semantics,
        which remain PENDING_AUDIT / PENDING_RUNTIME_EVIDENCE.
```

### 16.1 Task semantics — FROZEN

```text
task_family     = regression
scientific_task = waveform denoising
```

**Do not auto-detect the task type.**

### 16.2 Input / target semantics — FROZEN

Preserve the existing canonical TIDMAD input/target contract **exactly**. Do
not redefine the scientific task for the campaign.

### 16.3 Gold / blind data authority — FROZEN

goldpod and blindpod use exactly the same: dataset authority · files · hashes ·
preprocessing / data interpretation · train and validation authorities.

### 16.4 Dataset split — FROZEN

Preserve the official / canonical TIDMAD train/validation split. **Do not
randomly repartition data for the campaign.**

### 16.5 Run-level trial authority — FROZEN

```text
is_trial = true
```

for the formal campaign runs, **explicitly materialized** rather than relying
on the current default (frozen §3).

> ### ⚠️ The final formal phase does NOT set `is_trial = false`
>
> The run-level `is_trial = true` authority **remains in place for the entire
> campaign, including the final formal phase.**
>
> "Trial" versus "formal" in §16.6 refers to the **data-portion override /
> lifecycle phase**, NOT to the run-level `is_trial` flag.
>
> **Why this is called out.** Flipping `is_trial` to `false` for a final
> evaluation would re-enter the anchor / HealthGate lifecycle semantics that
> this project has already been bitten by. The phase change is a portion
> change, nothing more. Any implementation that reaches for `is_trial=false`
> to express "now do the formal evaluation" is implementing this decision
> incorrectly.

### 16.6 Data portions — **PARTIALLY FROZEN**

#### Trial phase — intended policy (FROZEN as intent)

```text
trial_portion = 0.1
train_portion = 0.1
eval_portion  = 0.1
```

**Intended scientific meaning:**

| quantity | intended value |
|---|---|
| effective training data | `0.1 × 0.1` = **1 %** of total training authority |
| intended evaluation data | **10 %** of the full evaluation authority |

**The evaluation figure MUST be audited.** Current framework semantics may
compose `eval_portion` with another portion or scope, in which case the
realized evaluation fraction is not 10 %. **This is not assumed either way.**

#### Final formal phase — intended training policy (FROZEN as intent)

```text
trial_portion = 1.0
train_portion = 0.1
```

Intended effective training data: **10 %** of total training authority.

#### Final formal phase — evaluation policy (NOT FROZEN)

Preferred, if computationally reasonable:

```text
eval_portion = 1.0    ->  evaluate on 100% of the official evaluation authority
```

**Exact evaluation policy remains `PENDING_AUDIT` and
`PENDING_RUNTIME_EVIDENCE`.**

#### Required audit (A4-1 … A4-5)

| id | requirement |
|---|---|
| **A4-1** | Mechanically derive the exact current semantics of `trial_portion`, `train_portion` and `eval_portion` — **including every multiplication, nesting and override**. Specifically: does `eval_portion` act independently, or is it composed with `train_portion` / `trial_portion` / `data_scope`? |
| **A4-2** | Inspect the exact **v19 and v20 effective settings** |
| **A4-3** | Determine how much training and evaluation data v19/v20 **actually used** — from realized behaviour, **not from nominal config values** |
| **A4-4** | Determine what the **original TIDMAD paper** used for training/evaluation scope, where reproducibly knowable |
| **A4-5** | Estimate/measure runtime on **testpod** for 1 % / 10 % / 100 % evaluation, using the **minimum useful witness** |

**Do not silently alter the frozen training portions based on this audit.**

#### Conditional evaluation fallback — operator decides, not the audit

If 100 % evaluation of the final formal candidate is reasonably affordable,
prefer:

```text
trial rounds      : intended eval scope = 10%
final formal round: eval scope = 100%
```

If full evaluation is materially too expensive — e.g. order-hours and
meaningfully damaging campaign throughput — prepare for operator confirmation
the alternative:

```text
trial rounds                     : eval scope = 1%  of total evaluation data
final/formal candidate selection : eval scope = 10%
selected best/champion result    : ONE final 100% evaluation
                                   -> the authoritative formal score
```

> **Do NOT choose between these two policies autonomously.** Return the
> measured runtime and the exact semantics to the operator.

### 16.7 Band `data_scope` semantics — FROZEN

Preserve the existing semantics of `0-3`, `4-9`, `10-14`, `15-19`. **Do not
redefine the bands.** Corresponding gold/blind bands use identical `data_scope`
authority.

### 16.8 Preprocessing — FROZEN

Preserve the existing TIDMAD preprocessing / data interpretation. **No new
campaign preprocessing action space is introduced.**

The framework does not currently expose preprocessing freedom to the agent, and
none is to be added for this campaign.

### 16.9 Dataset augmentation — FROZEN

**No new dataset-level augmentation capability is introduced.** If the current
canonical pipeline has no augmentation, it stays disabled.

### 16.10 Agent control over data — FROZEN

Agents may **NOT** alter:

```text
train/validation split · file membership · data_scope
trial_portion · train_portion · eval_portion
label/target semantics · dataset authority
```

These are campaign-level **`EXPERIMENT_FIXED` overrides**, not
`AGENT_CONTROLLED` decisions.

### 16.11 What remains genuinely open in Part 4

Exactly one campaign decision:

> **10 % → 100 % evaluation, or 1 % → 10 % → champion-only 100 %?**

It is deliberately deferred until A4-1 … A4-5 return, because choosing now
would mean guessing both the realized portion semantics and the runtime cost.


---

## 17. DECISION AREA 5 — AGENT ACTION SPACE — **FROZEN**

**Operator ruling, 2026-08-26.** 5.6 was confirmed in a follow-up and is
frozen; the whole area is now closed.

**Governing principle of this area, in the operator's own framing:**

> Architecture, loss, optimizer, scheduler and most training hyperparameters
> are **free for the agent to explore**. Segmentation size, data semantics,
> evaluation / HealthGate authority and the software environment are **locked
> as the external experimental boundary.**

**goldpod and blindpod receive an identical action space throughout.** Any
asymmetry here would be an engineering-capability confound, not a treatment
effect (frozen §5.10).

### 17.1 Architecture — `AGENT_CONTROLLED`

Agents may freely explore architectures within the frozen task, validity and
resource contracts, including: new architectures · modifications of existing
architectures · hybrids and combinations · materially different model families.

Same architecture action space in both arms.

### 17.2 Model size — FROZEN

**10M–500M is a soft exploration encouragement only. There is no campaign hard
parameter-count bound.**

Actual hard admission is governed by: VRAM · runtime / resource authority ·
framework validity constraints. **Smaller models remain allowed.**

This is consistent with the Part 1 advice semantics (§5.2), which frames the
range as encouraged, not a floor, target, or licence to bypass admission.

### 17.3 Pretrained weights — **EXPLICITLY_DISABLED**

```text
external pretrained weights   = DISABLED
external checkpoint warm-start = DISABLED
```

Formal scientific candidates must train from **campaign-controlled
initialization**.

**Part 1 gold treatment information does NOT constitute model-weight warm
start.** This restates the §9F terminology binding: goldpod is *treatment*-
seeded, never weight-seeded.

### 17.4 Loss / objective — `AGENT_CONTROLLED`

Agents may explore: existing losses · new losses · spectral / frequency losses ·
composite losses · weighted objectives · architecture-loss combinations.

**Constraint:** every training objective must remain compatible with the frozen
regression / waveform-denoising task contract (§16.1).

**The evaluation authority remains fixed separately** (§17.11) — a free
training objective does not imply a free scoring rule.

Validator / runtime enforcement of the compatibility constraint: **`A5-1`,
`PENDING_AUDIT`.**

### 17.5 Optimizer — `AGENT_CONTROLLED` within current support

Use whatever optimizers the current generic framework legitimately supports.

**Do NOT expand the optimizer catalog merely for this campaign.**

### 17.6 Scheduler — `AGENT_CONTROLLED` within current support — **FROZEN**

Scheduler configuration is `AGENT_CONTROLLED`. The agent may freely
modify/select any scheduler options already exposed by the current supported
loss/training configuration, including:

* selecting among currently supported schedulers
* changing their exposed hyperparameters
* **choosing no scheduler, if currently supported**

**The campaign does NOT add new scheduler mechanisms solely for this
experiment.** goldpod and blindpod receive the exact same scheduler action
space.

### 17.7 Training hyperparameters — `AGENT_CONTROLLED`, with one exception

Agent-controlled within frozen constraints: batch size · learning rate · weight
decay · optimizer parameters · scheduler parameters · architecture dimensions ·
dropout · other legitimate model/training hyperparameters.

> #### Exception — SEGMENTATION SIZE IS `EXPERIMENT_FIXED`
>
> Use **exactly the segmentation size from the canonical / original TIDMAD
> FCNet authority. Agents may NOT modify it.**
>
> **Exact numeric value: `PENDING_AUDIT` (`A5-2`).** It must be mechanically
> recovered from the canonical authority and **explicitly materialized before
> campaign freeze** — it cannot be left to a framework default (§3).

### 17.8 New / existing model and loss implementations — FROZEN

Agents **may**: implement entirely new architectures/losses · modify existing
architectures · modify existing losses · combine architecture and objective
innovations. Existing implementations may be used as starting points.

**However — an unchanged existing architecture with ONLY hyperparameter tuning
is not an acceptable architectural proposal.**

Reusing an existing architecture **is** allowed when the proposal introduces a
substantive scientific/modelling change, for example: a materially new
loss/objective · architectural modification · meaningful architecture-loss
combination.

**All implementation must use the existing SIDERIUS generic plugin/workflow
mechanisms. No proposal may require modifying the generic SIDERIUS framework
merely to make that candidate work.**

Enforcement mechanism for the "not merely hyperparameter tuning" rule:
**`A5-5`, `PENDING_AUDIT`.**

### 17.9 Ensembles — **EXPLICITLY_DISABLED**

`ensemble capability = NOT INTRODUCED`. The current framework does not provide
it and the campaign will not add it.

### 17.10 Preprocessing — FROZEN

Do not introduce new dataset/canonical preprocessing capabilities. Canonical
TIDMAD preprocessing remains fixed. No new preprocessing action space is added
for this campaign. (Consistent with §16.8.)

### 17.11 Evaluation authority — `EXPERIMENT_FIXED`

Agents may **NOT** modify: Golden Metric · secondary evaluator authority ·
evaluation data · metric implementation · HealthGate · HealthGate thresholds ·
validity criteria.

```text
training objective    : AGENT_CONTROLLED
scientific evaluation : EXPERIMENT_FIXED
```

**The Python workflow should structurally enforce this boundary.** Exact
enforcement: **`A5-3`, `PENDING_AUDIT`.**

### 17.12 Software / environment mutation — **EXPLICITLY_DISABLED**

During formal campaign execution:

```text
runtime pip/conda installs       = DISABLED
dependency mutation              = DISABLED
external checkpoint download     = DISABLED
external model/code asset download = DISABLED
environment mutation             = DISABLED
```

Agents may write new model/loss code **using the already frozen software
environment.**

### 17.13 Part 5 audit items — `PENDING_AUDIT`

| id | question |
|---|---|
| **A5-1** | How is the loss/objective ↔ task-contract compatibility constraint (§17.4) actually enforced — validator, runtime, schema, or prompt only? |
| **A5-2** | **Recover the exact segmentation-size numeric value** from the canonical/original TIDMAD FCNet authority, and identify where it must be explicitly materialized so it cannot fall back to a framework default. **Blocks campaign freeze.** |
| **A5-3** | Does the workflow *structurally* enforce that agents cannot reach the Golden Metric, secondary evaluators, evaluation data, metric implementation, HealthGate, HealthGate thresholds or validity criteria — or is the boundary conventional? |
| **A5-4** | **Census and explicitly materialize the currently supported optimizer and scheduler action spaces** (see the note below). |
| **A5-5** | How is §17.8's "unchanged architecture with only hyperparameter tuning is not acceptable" rule enforced — prompt-level guidance, validator check, or nothing? |
| **A5-6** | Are §17.12's five mutation prohibitions genuinely enforced at runtime, or merely absent by convention? Under §3 an absent capability must still be materialized as explicitly disabled. |

> #### Note on `A5-4` — why "currently supported" needs materializing
>
> §17.5 and §17.6 define the optimizer and scheduler action spaces **by
> reference** to what the framework currently supports. That is a pointer, not
> a value.
>
> Frozen §3 states the campaign must not rely on *"current framework behavior
> merely because that is what happens today"*, precisely so a later
> framework-default change cannot alter the meaning of the frozen campaign. A
> framework change that adds or removes an optimizer would silently widen or
> narrow the agent's action space **after** freeze.
>
> The decision itself is unaffected — the operator has ruled that the action
> space is whatever the framework legitimately supports, and the campaign adds
> nothing. `A5-4` only requires **recording the resolved list** in the campaign
> manifest, so the frozen action space is a stated fact rather than a
> late-bound lookup.


---

## 18. EVALUATION LIFECYCLE + OBSERVABLE METRICS — Part 4/6 rulings (2026-08-26)

### 18.1 Candidate evaluation lifecycle — **PROVISIONALLY_FROZEN**

Operator-preferred policy, recorded pending final confirmation now that the
mechanism audit has returned:

```text
TRIAL                     effective train scope = 1%    intended eval scope = 1%
FORMAL                    effective train scope = 10%   intended eval scope = 10%
AFTER CHAMPION SELECTION  ONE 100% evaluation of the ALREADY-SELECTED champion
                          -> authoritative final score, per-file vector,
                             secondary metrics, HealthGate result
```

Two binding constraints:

* **The champion must be selected BEFORE the 100 % evaluation.**
* **The 100 % result must NOT feed back into proposal / tuning / search.**

### 18.2 How `eval_portion` reaches E1 / E2 / E3 — mechanism audit

`eval_portion` builds ONE `eval_sample_set`
(`planning.py:592-601`, `build_sample_set(trial_portion=trial_config.eval_portion)`),
and that single set is consumed by all three events.

**TIDMAD scale** (`segments_per_file = 200`, `psd_segment_length = 10,000,000`):

| `eval_portion` | segments/file | samples/file | 5-file band |
|---|---|---|---|
| 0.01 | 2 | 20,000,000 | 100,000,000 |
| 0.10 | 20 | 200,000,000 | 1,000,000,000 |
| 1.00 | 200 | 2,000,000,000 | 10,000,000,000 |

| event | what it is | scope | scales with `eval_portion`? | runtime contribution |
|---|---|---|---|---|
| **E1** per-epoch validation | forward-only pass **inside the training subprocess**, computing the **training objective (a loss)** — not the Golden Metric | the full `eval_sample_set` | **YES — linearly**, and multiplied by epochs: workload is declared as `validation_requested_rows × epochs` (`train_engine_sandbox.py:1428`) | With `max_epochs = 1`: one extra full pass over the eval scope per attempt |
| **E2** Golden Metric | inference over `eval_sample_set` → deliverable → `evaluate_metric` → `score_vector` | the full `eval_sample_set` | **YES — linearly**, twice over (inference then scoring both traverse it) | The dominant eval cost |
| **E3** HealthGate | prefix peeks into the **denoised deliverable**, `timeseries/<channel>/timeseries[:peek_samples]` (`_peek.py`) | only the `health_gate_files`, and only `peek_samples` of each | **NO — constant** | 100,000–1,000,000 samples per health-gate file |

**Combined: the eval scope is traversed `epochs + 1` times per attempt** (E1 once
per epoch, then inference), plus a scoring traversal.

**Decisive finding for the proposed policy — E3 evidence does NOT degrade at
1 %.** TIDMAD's largest peek is 1,000,000 samples; even at `eval_portion = 0.01`
each file's deliverable holds **20,000,000** samples. The peek is a *prefix*
slice capped at dataset end, so what a health check sees is **identical at 1 %,
10 % and 100 %**. Reducing trial evaluation to 1 % costs nothing in HealthGate
sensitivity.

**Cost consequence.** E1 + E2 scale linearly, so trial evaluation at 1 % instead
of 10 % is a **10× reduction** in the dominant per-attempt eval cost, and formal
at 10 % instead of the current v19/v20 100 % is a further **10×**. E3 is flat
throughout.

### 18.3 Champion 100 % re-evaluation — minimum generic implementation

**Feasible. The prerequisite holds: model checkpoints survive.** `--cleanup_denoised`
removes **deliverables**, not weights; the trainer writes
`{sandbox_models_dir}/model_{type}_{exp_id}_agent.pth` and nothing deletes it.
The deliverable does not survive, so the champion pass must **re-run inference**.

Required stages, all on existing authorities — **no new scientific mechanism**:

| # | stage | existing authority to reuse | new work |
|---|---|---|---|
| 1 | select champion from persisted records | `execute_tools/per_file_best.py` (already a pure table over persisted `file_vector` scores) + `core/scientific_authority.py` | selection **rule** must be declared; the table exists and today has no consumer |
| 2 | rebuild full-scope eval set | `build_sample_set(trial_portion=1.0, scope=…)` | none — call it with 1.0 |
| 3 | re-run inference with the champion's saved weights | inference skill + `sandbox.execute_inference` | a loader that resolves `exp_id → .pth` **and its plugin source** |
| 4 | score | `sandbox.evaluate_metric(run_metric, sample_set=full)` — **unchanged authority** | none |
| 5 | secondary metrics | `_evaluate_secondary_metrics` — fires wherever the primary does | none |
| 6 | HealthGate | `execute_tools/health_checks/runner.evaluate_gate` | none |
| 7 | persist | — | **a terminal artifact OUTSIDE the record stream** |

**Stage 7 is the isolation requirement and the only real design constraint.**
The planner's `memory_history` is built from the workspace record stream; writing
the champion result there would feed a 100 % score back into search, violating
the second binding constraint. The champion artifact must live at a distinct
path and must never be read by `run_workflow`.

**Timing:** the pass must run only after every band reaches its terminal state,
so no live chain can observe it.

**Two dependencies to confirm before implementation** (`PENDING_AUDIT`):

* **`A6-1`** — plugin-source availability at champion time. Weights alone cannot
  reconstruct an agent-generated architecture; the plugin `.py` must also
  resolve. Plugins live under `{workspace}/plugins/` per iteration and
  `agent_generated/models/`, which `D-COLD-1` clears at cold start. Confirm the
  champion's plugin is still resolvable after the campaign ends.
* **`A6-2`** — champion **granularity**, below.

### 18.4 ⚠️ Champion granularity is a campaign-design question, not an implementation detail

The four bands cover **disjoint file sets** (`0-3`, `4-9`, `10-14`, `15-19`).
Under the standing invariant that *aggregate scalars are only comparable within
one scope*, **scores from different bands are not comparable**, so a single
cross-band champion cannot be selected by score.

That forces the structure:

```text
per-band champion   ->  4 champions per arm  ->  4 paired 100% evaluations per arm
                        gold band N  vs  blind band N   is the comparable unit
```

A single per-arm champion would require an aggregation rule across
non-comparable scopes, which the frozen metric authority does not provide.

**This needs an operator ruling** — it determines how many 100 % evaluations the
campaign performs (4 per arm, 8 total) and what the headline gold-vs-blind
comparison actually is (four paired comparisons, not one).

### 18.5 Observable metrics — **REQUIRED FOR v0.1.0**

**Operator ruling: generic task-declarable dynamic/static observable metrics are
REQUIRED FOR v0.1.0. They are not optional future work.**

**Required contract — all five levels must hold:**

| level | requirement |
|---|---|
| 1 | **declarable by task** — a manifest key the task owns |
| 2 | **typed dynamic vs static semantics** — the distinction is a type, not a convention |
| 3 | **real runtime producer** — production code populates it during a real run |
| 4 | **persistence** — it survives into the record |
| 5 | **downstream / report exposure** — a consumer actually reads it |

**Evidence rule, binding:** `TrainingHistory.observations` schema support and
hand-authored fixtures **do not count as implementation evidence**.

**Current state, audited:**

| capability | status |
|---|---|
| typed dynamic/static distinction | **NOT_IMPLEMENTED** — `dynamic_metric`, `static_metric`, `observation_metrics` all return **0 hits**; `observable` appears only as English prose |
| task declaration of observables | **NOT_IMPLEMENTED** — `_MANIFEST_KEYS` is a **closed 13-key allowlist** that hard-refuses unknown keys; no observable key exists |
| `TrainingHistory.observations` | **SCHEMA_ONLY** — verified: **169 occurrences across 165 real artifact files, every one `{}`**; zero production producers (`grep observations=` → none); zero consumers |
| training-loss curve (per-epoch) | `FULLY_IMPLEMENTED` — but this is the training **objective**, not a declarable observable |
| validation-loss curve (per-epoch, R3) | `FULLY_IMPLEMENTED` — same caveat |
| per-step / per-batch curve | `NOT_IMPLEMENTED` — named a permanent gap at `run_report.py:1088-1090` |
| validation **metric** curve (Golden Metric per epoch) | `NOT_IMPLEMENTED` — R3 computes the objective only |
| secondary metrics (static-like) | `FULLY_IMPLEMENTED` — declarable, produced, persisted, consumed — **but only on 2 of 3 scoring routes** |

**Gap to close for v0.1.0:** levels 1 and 2 do not exist at all, and level 3 does
not exist for the `observations` carrier. The nearest working precedent is
`secondary_metrics:` — declarable, typed, produced, persisted, consumed — which
is the shape a `dynamic_observables:` / `static_observables:` pair should follow.

**Owner:** release lane, routed through the Supervisor. Recorded as
`R-OBS-1`, blocking v0.1.0.


---

## 19. DECISION AREA 6 — BUDGET — **OPERATOR-FROZEN**

**Operator ruling, 2026-08-26.** Recorded from the decided design; no new audit.

```text
STATUS: OPERATOR-FROZEN — no remaining operator decisions.
        P6-A / P6-B / P6-C(-&gt;P7-D) were closed 2026-08-26; see §19.17 and §20A.13.
```

### 19.1 Budget philosophy — FROZEN

Equal **opportunity / limits** across goldpod and blindpod. **Not** equal
realized GPU-hours or wall-clock.

Identical to corresponding gold/blind bands: iteration count · round count ·
attempt ceilings · epoch ceilings · time ceilings · VRAM ceilings · data scopes.

Agents may legitimately consume different actual compute because they choose
different architectures, losses, batch sizes and strategies. **That divergence
is an experimental outcome. Do not introduce an exact-compute-matching
mechanism.**

### 19.2 Outer iteration budget — **FROZEN at 20** (corrected 2026-08-26)

```text
num_iterations = 20 per band          MAXIMUM OUTER HORIZON
```

**Corrected from `10`.** The v19/v20 value was preserved by inheritance; the
standing operator directive supersedes it and states explicitly that `10` must
not be kept merely because v19/v20 used it.

This is the outer SIDERIUS search trajectory used for reporting (score by
iteration; cumulative best HealthGate-valid **formal** score by iteration —
§20A.7). **Not to be confused with training epochs.**

`20` is a **maximum**, not a target: a band may terminate earlier under §19.2a.

#### 19.2a Success-based band-local early stop — **PENDING**, blocked on `A2-FCNET`

The directive authorises a success-based band-local early stop against an
**FCNet + 2** target, *"once its exact FCNet-reference scope is mechanically
confirmed."* That confirmation has now run, and it returns a blocker rather than
a value.

**Audited (`A2-FCNET`):**

* The FCNet paper reproduction is **four band-split checkpoints** —
  `FCNet_0_4.pth`, `FCNet_4_10.pth`, `FCNet_10_15.pth`, `FCNet_15_20.pth` —
  whose deliverables are **pooled and scored in ONE `score_vector` call over all
  20 files** (`scripts/score_tidmad_official_banded.py`, and
  `docs/design/paper_and_collapse_reference_baselines.md` §2.1).
* **The recorded FCNet reference is therefore a FULL-SCOPE (0..19) number.**
* **No per-band FCNet reference score exists anywhere in the repository.** The
  preserved artefacts carry diversity metrics (`unique_int8`, `std_mv`,
  `mode_fraction`, `pearson`) and `fcnet_reference_params = 323,000,000` — but
  not a per-band `denoising_score`.

**Why this blocks the rule as stated.** A campaign band's formal score is a
**band-scope** scalar (e.g. files `4-9` only). FCNet's reference is a
**full-scope** scalar. Under the standing invariant that *aggregate scalars are
only comparable within one scope*, **"band beats FCNet + 2" is not computable
today** — the two numbers do not live in the same scope, and `scoring_utils` §3
forbids deriving one from the other by any averaging.

**What would make it computable, using only the sanctioned construction.** The
FCNet deliverables are preserved
(`/home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/fcnet/full_20_files/`). Four
per-band FCNet reference scores can be produced by calling `score_vector` on a
**scoped SampleSet** per band — explicitly the construction `scoring_utils` §3
sanctions (*"or call score_vector on a scoped SampleSet"*). That yields four
band-scope FCNet references, each directly comparable to that band's formal
score. **No new aggregation rule, no new authority.**

**Status.** `num_iterations = 20` is **FROZEN**. The early-stop rule is
**PENDING** until the four per-band FCNet reference scores are produced and
recorded. Until then a band runs its full 20-iteration horizon.

**Open for the operator, and deliberately not assumed:** whether "+2" is
measured against a **per-band** FCNet reference (the only comparable form) or
against the **full-scope** FCNet reference applied to the composed-best result
(§20A.9), which would be a *campaign-terminal* stop rather than a band-local
one. These are different rules with different stopping behaviour.

### 19.3 Round structure — FROZEN

`max_rounds = 3`. A healthy iteration is trial round 1 · trial round 2 · formal
round. **The formal round is the LAST of the three — not an additional fourth.**
Run-level `is_trial = true` remains governed by §16.5; round-level formal
semantics stay separate.

### 19.4 Attempt budgets — FROZEN

```text
attempts_per_round        = 3
attempts_per_formal_round = 5
max_fail_rounds           = 3
max_proposal_attempts     = 3
max_impl_attempts         = 3
```

All preserved from v19/v20. **Do NOT introduce a generic
`max_tuning_attempts` abstraction** — the existing Python workflow already
defines the tuning/search opportunity. Identical in both arms.

### 19.5 Tuning workflow — FROZEN

Preserve the v19/v20 tuning state machine: one tuner/brain planning lifecycle
per attempt within the fixed round structure.

The agent decides **how** to use its scientific opportunity. It may **not**
expand: rounds · attempt ceilings · proposal ceilings · implementation ceilings
· campaign data portions · epoch ceilings · time ceilings.

```text
scientific / model choices  ->  AGENT_CONTROLLED   (Part 5)
workflow budget             ->  EXPERIMENT_FIXED
```

### 19.6 Training epochs — FROZEN, **INTENTIONAL CHANGE FROM v19/v20**

```text
trial  max_epochs = 2
formal max_epochs = 1
```

**Historical v19/v20 used one mode-agnostic `max_epochs = 1` for both.** The
current implementation therefore does **not** represent the frozen campaign
semantics. → `PENDING_IMPLEMENTATION`.

These are **ceilings / workflow authorities. Agents may NOT increase them.** Any
legitimate existing training-validity mechanism may terminate an invalid run
earlier; the agent may not change the ceiling. Independent of the
iteration-level best-score trajectory.

### 19.7 Trial data / evaluation budget — FROZEN

```text
trial_portion = 0.10     train_portion = 0.10     eval_portion = 0.01

effective training   : 0.10 x 0.10 = 0.01  =  1% of total training authority
effective evaluation : 0.01                =  1% of full evaluation authority
```

The audit established that `eval_portion` directly controls the shared eval
sample set used by the expensive validation/scoring paths.

**`EXPERIMENT_FIXED` campaign override. The planner/tuner must NOT replace it
with LLM-generated values.** Current trial-portion authority wiring is known to
violate this → `PENDING_IMPLEMENTATION`.

### 19.8 Formal data / evaluation budget — FROZEN

```text
trial_portion = 1.0      train_portion = 0.10     eval_portion = 0.10

effective training   : 10% of total training authority
effective evaluation : 10% of full evaluation authority
```

Campaign-controlled, not agent-controlled.

> **Implementation note — the flag mapping differs from today in BOTH terms.**
> The formal round resolves from `agent_input.formal_*`
> (`policy.py:1183-1189`): `formal_portion` → the `trial_portion` slot,
> `formal_train_portion` → `train_portion`, `formal_eval_portion` →
> `eval_portion`. So the frozen policy above requires:
>
> ```text
>                          v19/v20 today      frozen campaign
> --formal_portion              0.1        ->      1.0
> --formal_train_portion        1.0        ->      0.10
> --formal_eval_portion         1.0        ->      0.10
> ```
>
> The training **volume** is 10 % either way, but the **sampling changes**:
> today it is *10 % of segments, all used every epoch*; the frozen policy is
> *100 % of segments in scope, 10 % sampled per epoch*. Evaluation drops 100 %
> → 10 %. Both are deliberate.

### 19.9 Terminal champion evaluation — FROZEN

**Champion selection occurs PER BAND.** There is no cross-band champion because
the four bands use different data scopes and their scalar scores are not
currently defined as directly cross-comparable.

Each arm therefore produces **four band champions**: `0-3` · `4-9` · `10-14` ·
`15-19`.

After the search for a band is terminal:

```text
select the already-determined band champion
freeze champion selection
load the champion weights
evaluate on 100% of that band's evaluation authority
compute : Golden Metric · per-file vector · secondary metrics · HealthGate · provenance
persist : AUTHORITATIVE_FINAL_EVALUATION
```

**The 100 % evaluation is FINAL MEASUREMENT ONLY.** It must NOT feed back into
proposer · tuner · reflector · research memory · candidate selection · another
scientific search opportunity.

Champion full re-evaluation does not exist today → `PENDING_IMPLEMENTATION`.

### 19.10 Evaluation lifecycle / cost model — FROZEN CONCEPT

**Do NOT model evaluation as an unrelated free-standing budget item.** The
established workflow contains embedded evaluation events:

| | what | scaling (audit-established) |
|---|---|---|
| **E1** | per-epoch validation inside training — the training objective/loss on the eval sample set | scales with `eval_portion` **and epochs** |
| **E2** | round-end inference / deliverable / Golden Metric | scales with `eval_portion` |
| **E3** | HealthGate evidence | bounded prefix peeks — **does not materially scale** at TIDMAD campaign scopes |

The selected **trial 1 % / formal 10 % / champion 100 %** policy is intended to
make screening inexpensive while preserving a final full-scope authoritative
score.

Runtime/admission estimation must account honestly for the expensive phases,
especially E1 and E2. Known validation-cost under-accounting →
`PENDING_IMPLEMENTATION`. **Do not "solve" it merely by inflating watchdog
limits.**

### 19.11 Trial / formal time budget — FROZEN, **INTENTIONAL CHANGE FROM v19/v20**

```text
trial_time_budget_minutes  = 30      (v19/v20: 20)
formal_time_budget_minutes = 120     (v19/v20: 120 — unchanged)
```

**Rationale.** The trial ceiling rises 20 → 30 because the official campaign
permits substantially more per-band VRAM and broader model exploration. The
formal ceiling stays at 120 rather than 180 because: 180 min/formal attempt
would make the worst-case iteration envelope unnecessarily permissive; **the
time budget is a safety ceiling, not a target duration**; and large-model
exploration should be enabled primarily through resource admission and honest
runtime prediction, not a very loose wall-clock ceiling.

**These must be explicitly materialized in the final campaign launcher/manifest.
Do not rely on profile absence or defaults.**

### 19.12 VRAM budget — **SUPERSEDED by §21.4** (36 GiB → 60 GB)

> **SUPERSEDED.** Retained below as history.


```text
trial_vram_budget_gb  = 36
formal_vram_budget_gb = 36
max active bands/pod  = 2
nominal aggregate     = 36 + 36 = 72 GB on the 80 GB H100
```

Intended so the agent has room to explore materially larger architectures.

Final acceptance is contingent on the dedicated **testpod `dual_coresident`
witness** → `HARDWARE_DERIVED / PENDING_HARDWARE_EVIDENCE`.

**Do not transplant `four_way_coresident` calibration into the
`dual_coresident` campaign topology.**

### 19.13 Watchdog — FROZEN POLICY, current H100 state is a **BLOCKING GAP**

A runtime watchdog is **REQUIRED**. The current H100 band-fleet path **must not
run with watchdog enforcement silently OFF.** The formal campaign must
explicitly establish the qualified H100 `dual_coresident` runtime/watchdog
authority, covering the expensive lifecycle consistently.

Audit facts carried forward: historical v19/v20 watchdog enforcement covered
**training and inference**, and after later fixes **validation**; **scoring was
never watchdog-wrapped**. Current coverage must therefore be
audited/remediated so the actual expensive formal workflow is bounded
consistently.

Preserve the established safety model where appropriate: predicted runtime ·
safety factors · operator hard ceiling · bounded termination. Exact H100
runtime/calibration factors → `PENDING_HARDWARE_EVIDENCE`.

### 19.14 Scientific vs infrastructure failure — FROZEN

**Scientific failures legitimately consume the relevant scientific
opportunity** — malformed/invalid proposal after its allowed structural
recovery · validator scientific refusal · implementation failure caused by the
candidate · candidate invalidity · HealthGate scientific failure.

**Infrastructure failures must NOT consume scientific opportunity** —
API/network transport failure · transient provider failure · H100/pod
infrastructure failure · framework infrastructure failure unrelated to the
scientific candidate.

The audit established that **API/network/infrastructure failure currently
consumes a proposal attempt in the production proposal loop.** That contradicts
the frozen policy → `PENDING_IMPLEMENTATION`.

Infrastructure retry/recovery must preserve the same intended scientific
opportunity. Inherits Part 2's no-fallback-model, transient API retry policy,
and 600-second request timeout.

### 19.15 LLM token / spend budget — FROZEN, inherited from Part 2

No SIDERIUS campaign-level total token cap or total spend cap. The operator
controls spending externally. **Do not reintroduce a campaign LLM cap in Part
6.** The fixed workflow structure still bounds scientific opportunities.

### 19.16 Observable metrics — cross-reference only

**Do not redefine observable metrics as a Part 6 budget mechanism.** Compute
consequence only: dynamic observables may execute during training; static
observables execute from the trained model/data after training.

A generic task-declarable dynamic/static observable capability is **REQUIRED for
v0.1.0** (§18.5, `R-OBS-1`). Current train/validation loss history alone is
insufficient. Implementation tracked separately.

### 19.17 Part 6 control values — **FROZEN** (operator ruling, 2026-08-26)

The three items previously left open here are now decided. Full statement in
§20A.13.

| id | value | note |
|---|---|---|
| **P6/P7-A** `skip_formal_min_delta` | **−2.0** | was v19 `0.0` / v20 `−1.0` / band-fleet `−1.0` |
| **P6/P7-B** `bypass_formal_time_budget_min_delta` | **+0.5** | matches v19/v20; band-fleet default `0.0` is superseded |
| **P6/P7-D** first-formal / no-incumbent | worst sentinel until a valid FORMAL result exists — **explicit policy, not an accident** | renamed from P6-C |

**Part 6 is now OPERATOR-FROZEN with no remaining operator decisions.**

---

## 20A. DECISION AREA 7 — SCORING, VALIDITY, OBSERVABLES, FINAL SELECTION — **OPERATOR-FROZEN**

**Operator ruling, 2026-08-26.** Recorded from the decided design; no new audit.

```text
STATUS: OPERATOR-FROZEN — no remaining operator decisions.
        P6/P7-A..D were all closed 2026-08-26; see §20A.13.
```

### 20A.1 Golden Metric authority — FROZEN

The **sole scientific ranking authority** is the SIDERIUS Golden Metric — the
numerically stabilized/corrected implementation of the TIDMAD metric,
preserving the intended TIDMAD scientific metric while improving numerical
stability.

**Only the Golden Metric controls:** better/worse · formal incumbent · champion
selection · composed/strict ranking.

**NOT ranking authorities:** training objective · training loss · validation
loss · secondary metrics · observable metrics · HealthGate diagnostics.

**No hidden tie-break objective is permitted.**

### 20A.2 HealthGate is an independent validity authority — FROZEN

```text
Golden Metric  =  quality / ordering
HealthGate     =  validity
```

A candidate is eligible for official ranking **only** when it satisfies the
required HealthGate validity condition. For TIDMAD: **all required blocking
gates must pass.**

Preserve the current blocking/recording roster and **all previously calibrated
numeric thresholds. No adaptive threshold tuning. No post-hoc threshold
tuning.**

Trial, formal and terminal 100 % evaluation use **identical gate definitions and
thresholds**.

### 20A.3 TIDMAD blocking-check per-file aggregation — FROZEN, **INTENTIONAL CHANGE**

```text
per-file aggregation = all_pass          (shipped config today: any_pass)
```

The operator **rejects the lenient `any_pass` semantics**. Threshold values
remain unchanged.

A bounded retrospective census may be run as an implementation/qualification
sanity witness — **it is NOT a threshold recalibration exercise.**

→ `PENDING_IMPLEMENTATION`.

### 20A.4 Generic cross-gate composition — **NOT REQUIRED for arXiv / v0.1.0**

The framework hardcodes cross-blocking-gate AND semantics. The operator does
**not** require configurable AND / OR / N-of-M cross-gate composition for the
arXiv release.

**Recorded as an ICLR blocker / future roadmap item.** Do not expand arXiv
implementation scope for this feature.

### 20A.5 Trial best vs formal best — FROZEN

**ITERATION-LOCAL TRIAL BEST** — selected only from HealthGate-valid **trial**
results; trial eval scope **1 %**; a cheap search/control signal. May influence:
whether formal compute is worth spending · score-based SkipFormal · score-based
BypassFormalTimeBudget · interpretation and next-step reasoning.
**It is NOT official global ranking authority.**

**FORMAL BEST / GLOBAL CHAMPION** — selected only from HealthGate-valid
**formal** results; formal eval scope **10 %** during search. Controls the
formal incumbent, the global champion and the official search best.

> **A trial score may NEVER directly replace the formal incumbent or champion.**

### 20A.6 Cross-scope trial/formal control heuristic — FROZEN CONCEPT

The operator **explicitly accepts** that a 1 %-scope trial score and a
10 %-scope formal incumbent score are not identical-scope scientific
measurements — and that the trial score nonetheless has legitimate value as a
**compute-allocation heuristic**.

Score-based **SkipFormal** and **BypassFormalTimeBudget** are therefore
retained.

> Their cross-scope comparison must **NEVER** be represented as official
> scientific aggregation, champion comparison, or final result comparison. It is
> **solely a search-budget / promotion heuristic.**

A poor trial result can avoid wasting expensive formal compute. A sufficiently
promising HealthGate-valid trial result can justify spending extra formal
compute.

**Bypass semantics — the operator intends bypass to be REAL.** A qualifying
promising trial candidate must be able to bypass not only the pre-flight formal
runtime estimate but also the **normal formal execution ceiling**.

However: **watchdog protection must remain armed · bypass must remain bounded ·
no unbounded execution is permitted.** This requires a **separate / elevated
operator-controlled bypass execution ceiling** or equivalent authority
(`P6/P7-C`).

### 20A.7 Official search trajectory — FROZEN

```text
x-axis : outer SIDERIUS iteration
y-axis : cumulative best HealthGate-valid FORMAL Golden Metric so far
```

If an iteration produces no formal result, a skipped formal, an invalid formal
result, or no improvement — **carry forward the previous cumulative best. Do not
insert a sentinel into the main scientific trajectory.**

Iteration-local trial-best scores may be preserved and displayed **separately**
as search diagnostics / control evidence. They are **not** part of the official
cumulative-best curve.

### 20A.8 Observables — two orthogonal axes — FROZEN

**Do NOT conflate acquisition semantics with scientific/workflow role.**

| Axis 1 — ACQUISITION | Axis 2 — ROLE |
|---|---|
| **DYNAMIC** — must be collected during the training/execution trajectory | ranking · diagnostic · interpretation · search_feedback · reporting |
| **STATIC** — computable after training from the trained model + fixed data | |

A metric/observable can independently occupy positions on both axes.

**Architecture, per the completed audit:**

```text
static observables        ->  existing secondary_metrics authority
dynamic observables       ->  TrainingHistory.observations authority, to be completed
common downstream bundle  ->  existing ModelRunSummary
```

**Do not force dynamic trajectories into static `secondary_metrics`.**

**TIDMAD loss curves — frozen classification:**

| | acquisition | ranking | diagnostic | interpretation | search_feedback | reporting |
|---|---|---|---|---|---|---|
| **train loss curve** | dynamic | **no** | yes | yes | yes | yes |
| **validation loss curve** | dynamic | **no** | yes | yes | yes | yes |

These curves may improve interpreter/reflector understanding and may influence
subsequent proposal reasoning. **They do not directly determine official
candidate ordering.**

### 20A.9 COMPOSED BEST — FROZEN

Four independent band searches: `0-3` · `4-9` · `10-14` · `15-19`. Select one
HealthGate-valid **formal** winner per band.

> **The four band-level `denoising_score` scalars MUST NOT be averaged.**
> Explicitly prohibited: arithmetic mean of four band scores · mean of per-band
> log scores · mean of pre-aggregated linear band means.

**The authoritative construction:**

```text
collect each band winner's deliverables / segment-level scoring authority
compose the complete 20-file result
invoke the existing official score_vector EXACTLY ONCE over
    resolved data scope = 0..19
-> the resulting single full-scope Golden Metric IS the COMPOSED BEST
```

**This does not introduce a new aggregation rule.** It applies the existing
frozen scoring authority at the correct full scope — the same construction
`scripts/score_tidmad_official_banded.py` already uses for the paper's own
band-split checkpoints.

### 20A.10 STRICT BEST — FROZEN

Strict Best tests whether **ONE COMPLETE CANDIDATE DESIGN** succeeds across all
four bands. **The fixed object is the ENTIRE candidate design, not merely the
architecture.**

Freeze all `AGENT_CONTROLLED` scientific choices belonging to that candidate, as
applicable: model architecture/config · loss · optimizer · scheduler · learning
rate · batch size · weight decay · other candidate scientific hyperparameters.

For every candidate design selected as one of the four band winners:

```text
retrain INDEPENDENTLY FROM SCRATCH on 0-3, 4-9, 10-14, 15-19
  using the frozen campaign formal-training authority
  -> each band has its OWN independently trained weights

DO NOT reopen: proposer · tuner · architecture selection
               loss selection · hyperparameter optimization

then: collect the four terminal full-evaluation deliverables
      compose the complete 20-file result
      call the official score_vector ONCE over 0..19
-> one authoritative full-scope score per candidate design
```

Compare those full-scope scores using the Golden Metric. The best valid design
is **STRICT BEST**. **Do not average four band-level Golden scalars.**

### 20A.11 Terminal full evaluation — FROZEN (cross-reference §19.9)

Search-level champion selection uses **formal 10 %** evaluation. After selection
freezes, **terminal per-band champion evaluation = 100 %**.

Terminal measurement may **NOT** feed back into proposer · tuner · reflector ·
candidate selection · another search opportunity. **Terminal results require
structural isolation from normal workflow / research-memory readers.**

For Strict Best, these frozen final-measurement authorities construct each
candidate's complete full-scope scoring artifact.

### 20A.12 Part 7 implementation gaps — recorded, not fixed here

`PENDING_IMPLEMENTATION`:

1. mixed trial/formal best fields currently used by interpreter/ranking
2. official champion/ranking must use **formal-only valid** authority
3. behaviourally relevant eval portions missing from run/resume invariants
4. HealthGate-invalid formal score can affect chain termination
5. composed-task trial validity can use the wrong TIDMAD gate roster
6. TIDMAD per-file blocking aggregation `any_pass` → `all_pass`
7. generic dynamic-observable declaration / producer / persistence
8. composed-best production finalization
9. strict-best cross-band finalization
10. structural terminal-final-evaluation isolation
11. generic HealthGate dead/misleading config cleanup

**FUTURE / ICLR:** configurable cross-gate AND / OR / N-of-M composition.

### 20A.13 P6/P7 control values — **ALL FROZEN** (operator ruling, 2026-08-26)

#### P6/P7-A — skip formal

```text
skip_formal_min_delta = -2.0

TIDMAD higher-is-better intended semantics:
    run formal when   best_valid_trial_score >= formal_incumbent - 2.0
    skip on score     best_valid_trial_score <  formal_incumbent - 2.0
```

Implementation must remain **direction-aware through the existing `MetricOrder`
authority**, not hard-coded higher-is-better. **Only a HealthGate-valid trial
winner** may provide this compute-allocation signal.

*Mechanism note: the existing code already expresses this — the threshold is
`order.toward_better(reference, delta)` and the skip fires on
`order.is_better(threshold, winner_score)`. Only the value changes.*

#### P6/P7-B — bypass formal time budget

```text
bypass_formal_time_budget_min_delta = +0.5
```

Once a **finite** valid formal incumbent exists, a HealthGate-valid trial winner
qualifies for the elevated formal-compute path when it improves on the formal
incumbent by **at least 0.5 Golden-Metric units**, direction-aware through
`MetricOrder`.

**Explicitly a COMPUTE-ALLOCATION HEURISTIC.** The 1 %-scope trial score is not
an authoritative scientific comparison against the 10 %-scope formal score and
**must never replace the formal incumbent or champion.**

#### P6/P7-D — formal incumbent cold start

```text
formal_incumbent initial authority = worst sentinel / -infinity   (TIDMAD higher-is-better)
```

The incumbent stays at the sentinel **until a HealthGate-valid FORMAL result
exists**. The following do **NOT** establish or update it: trial results ·
HealthGate-invalid formal results · skipped formal rounds · infrastructure
failures.

Therefore, while no valid formal result yet exists, **any HealthGate-valid trial
winner intentionally qualifies for the bypass path.**

> **This is now an EXPLICIT CAMPAIGN POLICY, not an accidental sentinel side
> effect.**

Once the first valid formal score exists, the normal **+0.5** bypass threshold
applies relative to that finite incumbent.

#### P6/P7-C — normal vs bypass formal execution ceiling

```text
normal formal attempt          formal_time_budget_minutes        = 120
                               watchdog ceiling                  = 120 min

bypass-qualified formal attempt bypass_formal_time_budget_minutes = 200
                               watchdog ceiling                  = 200 min
```

(or the closest existing typed authority with equivalent semantics)

**The bypass must affect BOTH** the pre-flight/admission runtime feasibility
**and** the execution watchdog hard ceiling. **It must NOT disable watchdog
protection.**

**The elevated 200-minute budget is available ONLY to a score-qualified bypass
formal attempt. Do not globally raise all formal attempts to 200 minutes.**

> **Implementation gap — `PENDING_IMPLEMENTATION`.** Today the bypass mutates
> `time_check["feasible"] = True` in place (`execution.py:617`) — it overrides
> the **forecast only**. `operator_budget_seconds` stays
> `formal_time_budget × 60` (`runtime.py:1263`), so **a bypass does not move
> the watchdog ceiling at all.** Realising this ruling requires a
> bypass-qualified attempt to select the elevated budget for *both* the
> admission check and the watchdog deadline. No such typed authority exists.

**Part 7 is now OPERATOR-FROZEN with no remaining operator decisions.**

---

## 20B. DECISION AREA 8 — FAILURE / RETRY / RESUME / RESTART — **OPERATOR-FROZEN**

**Operator ruling, 2026-08-26.** No remaining campaign-design decisions are open
in Part 8.

> Any later discrepancy between production behaviour and these semantics is an
> **implementation gap**, a **release defect**, or an **audit finding** — **not
> an invitation to silently modify the frozen campaign policy.**

### 20B.1 Failure taxonomy — FROZEN

Four classes, at minimum.

**A. `SCIENTIFIC_FAILURE`** — the scientific candidate itself fails the
legitimate experiment/workflow contract: scientific validator refusal ·
implementation failure attributable to the candidate · invalid/NaN scientific
output · HealthGate blocking failure · candidate legitimately exceeding its
allowed scientific resource ceiling · other candidate-specific invalidity.
**Consumes the appropriate scientific opportunity.**

**B. `TRANSIENT_INFRA_FAILURE`** — the candidate has **not** been scientifically
disproven; execution was interrupted by transient infrastructure unrelated to
candidate quality: transient API/network failure · temporary provider failure ·
transient pod/process failure · temporary CUDA/runtime infrastructure failure ·
transient filesystem/I-O failure · any infrastructure interruption unrelated to
the candidate. **Consumes NO scientific opportunity.**

**C. `PERSISTENT_ENVIRONMENT_OR_CONFIG_FAILURE`** — the environment/configuration
cannot honestly execute the frozen campaign semantics: invalid credentials ·
missing required dataset · incompatible campaign manifest · corrupt
dependency/environment · unsupported execution configuration · wrong release
authority. **Must fail closed / pause execution. NOT counted as a scientific
candidate failure.**

**D. `EVIDENCE_OR_PROVENANCE_FAILURE`** — partial artifacts may exist, but the
framework cannot prove the result is authoritative: missing required artifact ·
incomplete required provenance · manifest/hash mismatch · inconsistent run
identity · partial output presented as terminal success · evidence-channel
failure. **NOT a scientific success. Fails closed until evidence is
reconstructed or the affected opportunity is safely rerun.**

### 20B.2 Infrastructure retry semantics — FROZEN

A transient infrastructure failure **retries the SAME scientific opportunity.**

**Identity that must be preserved:** same candidate design · same campaign ·
same arm · same band · same outer iteration · same round · same scientific
attempt identity · same campaign-controlled RNG authority.

**The retry does NOT decrement:** proposal opportunity · implementation
opportunity · scientific attempt budget · failure-round budget.

> **Infrastructure retry must not silently become a new scientific candidate.**

### 20B.3 Clean attempt restart — no mid-training scientific resume — FROZEN

**The official campaign does NOT introduce a mid-training checkpoint resume
contract.**

If transient infrastructure interrupts training or another scientifically
stateful phase before authoritative completion: **discard the partial scientific
result and restart the SAME scientific attempt from its clean attempt
boundary** — same candidate design, same campaign-controlled seed authority,
same frozen execution semantics.

**Do not** attempt to reconstruct a partially completed epoch, optimizer step,
DataLoader position, CUDA RNG stream, or other in-progress scientific state,
unless a future separately audited checkpoint/resume contract is introduced.

Already completed and **atomically persisted, evidence-complete** phases need
not be repeated unnecessarily. **However: partial scientific state is never
treated as completed merely to save compute.**

### 20B.4 Watchdog / resource-ceiling failure classification — FROZEN

**Classification depends on ROOT CAUSE, not on which process killed the job.**

**Candidate legitimately exhausts its frozen execution/resource authority** —
trial normal hard ceiling · formal normal hard ceiling · bypass-qualified
elevated formal hard ceiling · legitimate VRAM/resource ceiling — ⇒ classify as
**SCIENTIFIC / RESOURCE_INFEASIBLE FAILURE** and **consume** the appropriate
scientific attempt.

Examples: a trial candidate legitimately exceeding its 30-minute ceiling · a
normal formal candidate exceeding 120 minutes · a bypass-qualified formal
candidate exceeding its 200-minute elevated ceiling.

**By contrast** — wrong runtime profile · watchdog malfunction · H100/pod
infrastructure stall · unrelated service outage · filesystem failure · framework
infrastructure defect ⇒ **infrastructure/environment failure; do NOT consume the
scientific opportunity.**

### 20B.5 Attempt / round failure progression — FROZEN

```text
scientific failure  -> consumes the relevant attempt
                    -> workflow may use the next legitimate attempt in the round
attempts exhausted  -> round fails
                    -> consecutive scientific fail-round count advances
successful round    -> resets the consecutive fail-round count
max_fail_rounds     =  3          (already frozen in Part 6)
```

> **Infrastructure failures do NOT increment scientific attempt counters or
> consecutive fail-round counters. Only scientific failure advances scientific
> failure accounting.**

### 20B.6 Failure locality — FROZEN

**Failure stays local to the narrowest scientifically valid scope.** A terminal
failure in one band does **not** automatically terminate or pause other bands in
the same arm, the paired band in the other arm, or the other campaign arm.

```text
gold band 4-9 -> scientifically exhausts its legal search -> terminal FAILED
    does NOT stop:  gold 0-3 · gold 10-14 · gold 15-19
                    blind 4-9 · other blind bands
```

The final campaign report must represent missing/failed paired evidence
**honestly**. **Do not kill healthy work merely to force wall-clock symmetry.**

Gold/blind symmetry concerns **frozen opportunity · scientific authorities ·
budget authorities · treatment difference** — **not** identical realized
wall-clock timing.

A transient outage on one pod likewise does not automatically require pausing a
healthy independent pod, unless continued execution would become scientifically
incomparable.

### 20B.7 Resume authority — FROZEN

**Persistent evidence-complete records are authoritative. In-memory process
state is NOT.**

After a process / coordinator / machine / pod restart, resume must reconstruct
state from persisted authoritative records, and must first verify the exact
canonical campaign/run identity: release SHA · campaign manifest · treatment
authority · data authority and resolved data scope · train/eval portions ·
Golden Metric authority · HealthGate authority · seed hierarchy ·
model/provider authority · other canonical RunInvariant fields.

```text
completed, evidence-complete opportunity        -> do NOT rerun
partial / uncommitted opportunity               -> NOT completed; restart per §20B.3
incompatible provenance / manifest / authority  -> REFUSE RESUME
```

> **Do not use "close enough" configuration compatibility. Resume is
> provenance-exact and fail-closed.**

### 20B.8 Transactional success — FROZEN

**Scientific success must be evidence-complete and transactional.** A
candidate/attempt may be committed as SUCCESS only when all required
authoritative outputs exist — at minimum, where applicable: execution/training
completed · required deliverable exists · Golden Metric result exists · required
HealthGate result exists · required provenance exists · required artifacts pass
integrity checks · scientific authority internally consistent.

**NOT sufficient evidence of success, alone:**

```text
process exit code 0        launcher exit code 0
model file exists          one JSON record exists
partial log exists         subprocess reached the end of one phase
```

If failure occurs before the success transaction completes: **status = partial /
incomplete / retryable as appropriate — NOT success.**

> **This policy is intended to eliminate false-success launcher behaviour.**

### 20B.9 Operator intervention — FROZEN

The operator **may** repair infrastructure/environmental failures without
converting the scientific opportunity into a new candidate: pod repair ·
credentials repair · filesystem repair · API connectivity repair · broken
launcher repair · environment repair · framework infrastructure repair.

The operator **may NOT** modify the scientific candidate in place and continue
to call it the same attempt. Scientific changes that cannot be silently applied
to an existing attempt: architecture · model configuration · loss · optimizer ·
learning rate · batch size · scientific preprocessing · Golden Metric ·
HealthGate threshold · campaign data portions · candidate scientific
hyperparameters.

If scientific semantics must change: **terminate/invalidate the old attempt and
use a new legitimate scientific opportunity**, or explicitly refreeze/restart
the affected campaign authority.

**All material operator interventions must be persisted in provenance/event
history.**

### 20B.10 Terminal 100 % champion evaluation failure — FROZEN

Terminal full evaluation occurs **only AFTER champion selection is already
frozen.**

**Infrastructure failure** ⇒ retry the **same final measurement**, same
already-selected champion, same data scope, same scientific authority. **No new
scientific selection opportunity is created.**

**Scientific / validity failure** — the champion was valid under formal search
evaluation but fails validity/HealthGate at 100 % ⇒ **champion selection remains
frozen**, and the terminal authoritative outcome records `INVALID /
FAILED_FULL_EVAL` (or the closest exact typed terminal state).

> **Do NOT automatically select the second-place candidate.** Do not create
> `champion #1 fails -> try #2 -> try #3 -> …` — that would turn final
> measurement into an additional hidden selection loop.

**The full-evaluation failure must be reported honestly. No search is
reopened.**

### 20B.11 Campaign-wide pause / abort — FROZEN

Reserved for failures that invalidate the **scientific comparability or
evidentiary authority** of the campaign:

1. a framework/release defect that invalidates already-produced evidence;
2. corruption or semantic change in the dataset authority, Golden Metric
   authority, HealthGate authority, or campaign manifest;
3. gold/blind symmetry violation outside the intended treatment difference;
4. shared environment/provider failure making continued execution scientifically
   incomparable;
5. operator explicit stop.

**Do NOT automatically abort campaign-wide for:** individual candidate failure ·
individual round failure · individual iteration failure · single-band scientific
failure · one pod transient outage · transient API failure · one terminal
champion full-evaluation failure.

**If a framework defect is discovered mid-campaign: produce an INVALIDATION
MAP.** Determine exactly which previously produced records are semantically
affected. **Rerun only evidence whose authority is invalidated. Do not
mechanically rerun unaffected campaign work.**

### 20B.12 Failure accounting principle — FROZEN

```text
Scientific failure consumes scientific budget.
Infrastructure failure consumes no scientific budget.
Infrastructure retry repeats the same scientific opportunity.
Partial work is never success.
Resume is provenance-exact and fail-closed.
Legitimate candidate resource exhaustion is scientific failure.
Infrastructure-caused interruption is infrastructure failure.
Failure stays local to the narrowest scientifically valid scope.
Final measurement does not reopen search.
Campaign-wide abort is reserved for evidence-invalidating,
  symmetry-invalidating, or operator-directed conditions.
```

### 20B.13 Part 8 implementation / audit dependencies

Not resolved in the planning lane. Recorded for later Supervisor routing.

| id | item |
|---|---|
| `A8-1` | infrastructure failures currently consuming proposal/scientific attempts |
| `A8-2` | exact typed failure-classification propagation across proposer · implementor · trainer · evaluator · HealthGate · launcher · coordinator |
| `A8-3` | clean retry preserving scientific attempt identity |
| `A8-4` | prevention of infrastructure retries incrementing scientific failure counters |
| `A8-5` | exact transactional-success boundary |
| `A8-6` | elimination of false-success launcher paths |
| `A8-7` | resume invariant completeness |
| `A8-8` | partial-artifact handling |
| `A8-9` | correct distinction between resource-infeasible scientific failure and infrastructure failure |
| `A8-10` | final 100 % evaluation retry semantics |
| `A8-11` | invalidation-map mechanism for mid-campaign framework defects |
| `A8-12` | operator intervention provenance |
| `A8-13` | band-local terminal failure behaviour |
| `A8-14` | coordinator restart/recovery behaviour |

> **Do not assume a schema/status name proves the runtime implements the
> semantic distinction. Require producer → persistence → consumer evidence
> where later audited.**


---

## 21. FORMAL HARDWARE DISPOSITION — **FROZEN** (operator ruling, 2026-08-26)

**Provenance: operator ruling, relayed by the RTX 5090 Supervisor under standing
directive §11 (required relay).** Recorded as operator authority. The relay path
is stated so provenance is honest.

**This supersedes both the 8-GPU simultaneous Gold/Blind option AND the
`dual_coresident` formal topology.**

### 21.1 Frozen status block — verbatim

```text
FORMAL_GPU_COUNT                                    = 4
FORMAL_GPU_TYPE                                     = H100_SXM
GPU_RESIDENCY                                       = EXCLUSIVE_SINGLE_BAND
ARM_EXECUTION_ORDER   = GOLD_FIRST, BLIND_AFTER_GOLD_IF_RESOURCES_ALLOW
GOLD_REQUIRED                                       = true
BLIND_REQUIRED_FOR_GOLD_COMPLETION                  = false
SCIENTIFIC_VRAM_CEILING                             = 60GB
TRIAL_TIME_CEILING                                  = 30min
FORMAL_TIME_CEILING                                 = 120min
BYPASS_FORMAL_TIME_CEILING                          = 200min
TIME_CEILINGS_REQUIRE_FINAL_H100_SINGLE_RESIDENT_QUALIFICATION = true
```

### 21.2 Band-to-GPU assignment — Stage G-A

```text
GPU 0  ->  band 0-3
GPU 1  ->  band 4-9
GPU 2  ->  band 10-14
GPU 3  ->  band 15-19
```

**One exclusive GPU per Gold band. No two scientific band searches co-reside.**

> **✅ VERIFIED 2026-08-26 — `A-HW-VERIFY-1` DISCHARGED.** Measured on the Gold
> host `7b18f5b84834`: **4 × NVIDIA H100 80GB HBM3**, 81559 MiB each, 700 W
> each, four distinct UUIDs · `nproc = 224` · RAM 2015 G total / 1909 G
> available · `/workspace` = `/dev/md127` xfs **2.0 T** · `/` = overlay 30 G
> (**data must NOT live there**) · `rsync` present.
>
> Verified execution facts: one Gold host · four H100 GPUs · **shared
> `/workspace` filesystem** · one immutable `/workspace/DATA` copy · one
> exclusive GPU per band · four isolated writable band workspaces.

> **⚠️ Exclusive GPUs are not an isolated host — AND THE HOST IS SHARED WITH
> OTHER TENANTS.** Measured on the freshly-started Gold pod with **nothing of
> ours running**: loadavg **60.17 / 59.00 / 56.23 on 224 cores ≈ 27 % of the
> host CPU already consumed by other tenants.** testpod's exp1 baseline was
> ~50 on 208 cores ≈ 24 % — the same order.
>
> The four bands share host CPU, RAM and filesystem *and* share the physical
> machine with neighbours we do not control. The unexplained 2.389× occurred at
> 7–20 % GPU utilisation with 82–90 % CPU idle, so GPU contention was almost
> certainly not its cause — and **neighbour load is now a live candidate for
> part of it** (`A-HOST-1`, §21.11).

### 21.3 Execution order

Gold runs **first**. **Gold finalization follows Gold Stage A — it does NOT wait
for Blind.** Blind runs afterward **only if resources permit**.

### 21.4 VRAM ceiling 36 GB → 60 GB — **causal, not cosmetic**

The revision is an explicit resource-policy change **caused by** the move from
co-resident to exclusive-GPU execution.

* Use the repository's **existing canonical VRAM authority**. **Do NOT create a
  second budget mechanism.**
* **Do NOT silently change GB/GiB semantics.** (Note the shipped flags are
  implemented as GiB — `agent/skills/evaluate_vram_skill/wrapper.py`,
  `_GB = 1024**3`. The unit question must be settled explicitly at
  implementation, not assumed.)
* The candidate must **not** treat the full physical 80 GB as scientific budget.
  The remainder is headroom for framework overhead, transient allocator
  behaviour, CUDA context and safety margin.
* **Blind, if run, gets the same 60 GB.**

### 21.5 Time ceilings — nominally frozen, requalification REQUIRED

`30 / 120 / 200` remain **nominally frozen** and **require fresh
exclusive-H100 single-resident qualification**.

**The operator explicitly refused to raise them merely because the topology
changed, and the reasoning is load-bearing:** single-resident *removes* the dual
penalty, but post-#320 uses the true frozen trial scope and 60 GB permits larger
candidates. **Those push in opposite directions, so no existing evidence can
establish whether 30/120/200 are too loose or too tight.**

> **A 1.5× proportional expansion to 45 / 180 / 300 was named by the operator as
> a natural candidate for DISCUSSION and is explicitly NOT FROZEN. Do not adopt
> it, plan against it, or treat it as likely.**

Witness status: `PENDING_HARDWARE_EVIDENCE`. Values stay frozen meanwhile.

### 21.6 Temporal asymmetry — a **provenance requirement**, not a scheduling note

The operator accepts Gold-first / Blind-later as a **cost decision**.

If Blind is ever used for a formal quantitative treatment-comparison claim,
**exact provenance of the temporal separation and of all provider / hardware /
release authorities must be preserved.**

```text
Sequential execution must NEVER be described as simultaneous.
If Blind cannot be completed it is reported as unavailable / incomplete,
  honestly — no fabricated symmetry evidence.
Completed Gold is NOT invalidated or delayed by Blind's absence.
```

This statement must appear **explicitly** in the standalone campaign runbook,
not be left implicit.

### 21.7 Provider drift — **INTRA-GOLD**, and `D-LLM-13` is a GOLD LAUNCH PRECONDITION

**Two reclassifications, in sequence, both recorded rather than edited away.**

**First**, this lane called `D-LLM-13` *"the ONLY remaining defence against a
provider-side model change between the two arms"* and asked for
**release-blocking** treatment. Under Gold-only that rested on a comparison the
campaign is not making. **Withdrawn.**

**Second**, this lane then proposed demoting it to *provenance hygiene*. **That
was too far in the other direction**, and the Supervisor supplied the stronger
residual argument:

> Gold runs **four bands × up to 20 iterations, concurrently, potentially over
> days**, against a **mutable alias**. If the provider updates `gpt-5.5`
> mid-campaign, different bands — or different iterations of the *same* band —
> execute against **different models**.

**Final disposition, adopted:**

```text
D-LLM-13 : NOT a v0.1.0 release blocker
           FORMAL GOLD LAUNCH PRECONDITION
```

It does not gate the code release. **It gates launching a campaign whose own
internal comparisons are meant to mean something.** Eight strings in one file,
no code change.

#### 21.7a Being precise about what alias drift does and does not contaminate

The Supervisor's framing was *"Composed Best and Strict Best both compare
candidates across bands and iterations, so an alias change contaminates the two
selections the campaign exists to produce."* **That is right in direction and
worth tightening, because two of those computations are actually robust:**

| computation | contaminated by mid-campaign alias drift? |
|---|---|
| Golden Metric arithmetic, HealthGate verdicts | **NO** — they measure a trained model, not the proposer |
| **Composed Best** pooling (§20A.9) | **NO** — one `score_vector` call over four already-selected deliverables; the arithmetic is indifferent to who proposed them |
| **Strict Best** comparison (§20A.10) | **NO** — it compares four **fixed designs** retrained under identical frozen authority, with **no proposer involved** |
| **the candidate POOL those selections draw from** | **YES** — the four band searches would have been conducted by materially different agents |
| **the official iteration trajectory (§20A.7)** | **YES, and this is the sharpest instance** |
| the campaign's central scientific claim | **YES** |

**The strongest single case is not cross-band — it is within-band.** §20A.7
freezes the campaign's headline quantitative artifact as *"cumulative best
HealthGate-valid FORMAL Golden Metric by iteration."* That curve is read as **one
agent's progress over 20 iterations.** If iterations 3 and 17 of the same band
ran against different models, **the curve silently plots two agents and is
presented as one.** No amount of correct scoring arithmetic repairs that,
because the defect is in what the x-axis means.

And the campaign's claim is of the form *"an LLM agent, given prior information,
found X."* **If the agent changed mid-run, "the agent" is not one thing** — which
is a claim-integrity defect, not a computational one.

**So the argument for pinning survives the removal of the between-arm reading
completely, and would exist even if Blind had never been designed.** It is
cheap enough that the argument barely has to hold; it holds comfortably.

**`D-PROV-1` follows the same reasoning.** DeepSeek exposes no immutable
revision, so the same intra-campaign exposure applies — **confined to
`lit_review`'s 2 of 10 roles**, and **removed entirely** if `Q-LIT-1` resolves
OFF.

**Unchanged requirement.** §21.6's provenance records must capture the
**resolved model snapshot**, not the configured alias.

### 21.8 Preserved unchanged by this ruling

Explicitly untouched: max outer iterations **20** · band-local FCNet+2.0 early
stop (pending `A2-FCNET`) · frozen trial/formal portions · frozen epoch
semantics · `skip_formal_min_delta = −2.0` ·
`bypass_formal_time_budget_min_delta = +0.5` · formal incumbent cold-start
semantics · Golden Metric authority · HealthGate authority and `all_pass` ·
failure / retry / resume semantics · candidate-design action space ·
composed / strict scoring mathematics.

### 21.9 What this ruling SUPERSEDES

| superseded | by |
|---|---|
| §9.10 max 2 active bands per pod + dynamic backfill | §21.1–21.2 — four exclusive GPUs, one band each |
| §9.11 / §19.12 36 GiB per active band | §21.4 — 60 GB |
| `dual_coresident` formal topology | `EXCLUSIVE_SINGLE_BAND` |
| §9A's four-way → max-two consequence map | §21.10 — **both** prior topologies are now wrong |
| `D-HW-3` two-way formal-topology rehearsal | single-resident qualification |

### 21.10 Evidence relevance map — **updated**

Q5's four-way co-residency factor was already not the campaign authority. **The
2.389× dual measurement is now also not the campaign authority.** Neither
topology is the formal one.

| evidence | class | status under §21 |
|---|---|---|
| Q1–Q4, Q8 | platform | **still valid** — topology-independent |
| Q5 four-way co-residency factor | topology-specific | **not applicable** |
| 2.389× dual-coresident measurement | topology-specific | **not applicable to the formal campaign** |
| Q6 watchdog calibration | topology-specific | must target **single-resident** |
| Q7 campaign topology semantics | topology-specific | must be re-read against §21 |
| Q9 A/B launch rehearsal | topology-specific | must rehearse **Gold-first, exclusive-GPU** |

**`F-H100-WD-1` is unchanged in substance and narrowed in target:**
`configs/runtime_profiles.yaml` still has one row
(`nvidia_geforce_rtx_5090/single`), so the watchdog remains disabled on every
H100 path. The row now required is **H100 single-resident**, not
`dual_coresident`. `ExecutionRegime` already types `single` first-class, so no
vocabulary extension is needed.


---

### 21.11 Shared host + fixed wall-clock ceilings — **GOLD RUNTIME / RESOURCE-SELECTION RISK**

> **RECLASSIFIED 2026-08-26.** First recorded as a treatment-axis confound
> (`F-CONFOUND-2`). Under the Gold-only ruling it is **not presently a
> Gold-vs-Blind confound**, because there is no Blind to be biased against. The
> **measurement stands and the mechanism stands** — only the claim about what it
> biases changes.

**Measured.** Gold host baseline with **all four GPUs at 0 % and nothing of ours
running**: loadavg **66.88 / 51.09 / 51.60 on 224 cores**, having read
**60.17 / 59.00 / 56.23** minutes earlier. **~23–30 % of the host is consumed by
other tenants, and it MOVES between readings.** testpod's exp1 baseline was ~50
on 208 ≈ 24 % — the same order.

**Time-variance is the property that matters**, and it is now **measured, not
assumed**.

**The mechanism, unchanged.** Ceilings are wall-clock and fixed; neighbour load
is uncontrolled and varies; `D-FAIL-4` classifies a ceiling breach as
**SCIENTIFIC / RESOURCE_INFEASIBLE**, which **consumes a scientific attempt**.
Therefore **host load can affect which Gold candidates survive.**

**The amplification argument survives — as a WITHIN-GOLD selection effect**,
which is arguably the more directly actionable framing. Candidates pushed toward
the ceiling by the advice and the 60 GB budget sit closest to breach, so **a busy
neighbour preferentially removes exactly the large candidates the treatment
exists to encourage.** That distorts *which science Gold gets to do*, whether or
not a second arm ever exists.

Illustrative only:

| ceiling | host at 1.0× | at 1.2× | at 1.5× |
|---|---|---|---|
| trial 30 min | fits ≤ 30 solo-min | ≤ 25 | ≤ 20 |
| formal 120 min | ≤ 120 solo-min | ≤ 100 | ≤ 80 |

**Required response — provenance, not a policy change.** Record **concurrent
host baseline load per attempt**, so that `A-HOST-1` can separate our four-band
contention from a neighbour's, and so a resource-infeasible attempt can later be
attributed to a large candidate rather than a busy host. **Without that record
those two causes are indistinguishable after the fact.**

**Reactivates as a treatment-axis concern** if Blind is executed — at which
point the arms' differing host conditions become a between-arm confound as
originally written.

**Open hypothesis, not a claim.** Two hosts' baselines are the same order, so
**neighbour load is a live candidate for part of the unexplained 2.389×**.
`A-HOST-1` can now rule it in or out.

## 20. Decision history

| date | decision | recorded in |
|---|---|---|
| 2026-08-26 | Campaign naming frozen: testpod / goldpod / blindpod | §1 |
| 2026-08-26 | Control-plane hierarchy frozen | §2 |
| 2026-08-26 | No-implicit-default principle frozen | §3 |
| 2026-08-26 | Fix-environment-not-outcome principle frozen | §4 |
| 2026-08-26 | **Decision Area 1 — Treatment definition — FROZEN** in full: goldpod advice semantics incl. the four parameter-range qualifiers and the five prescription prohibitions; prior-TIDMAD-baseline artifact; four excluded baseline assets; proposer-only injection every round; blindpod explicit materialised absence; blindpod negative leakage audit AND goldpod positive treatment audit, both formal launch gates; artifact immutability with frozen content hashes and byte-identical artifacts across all four goldpod chains; fairness/control principle | §5 |
| 2026-08-26 | Implementation dependency recorded: the shipped arXiv X9 / #255 arm definition uses a different treatment variable and refuses advice in both arms. Recorded as work (T-IMPL-1/2/3) and two downstream questions (Q-LIT-1, Q-ISO-1). Does **not** reopen §5. | §5.11 |
| 2026-08-26 | LLM configuration census performed | §8 |
| 2026-08-26 | **Decision Area 2 — Formal LLM configuration + execution concurrency — FROZEN**: OpenAI Pro config authority pinned by sha256 with Chat Completions established as the production API path; gold/blind LLM symmetry; model fallback DISABLED (verified); reasoning effort effective HIGH (API semantics pending); temperature/top_p not campaign-tuned (both verified omitted); no campaign token or spend cap (verified absent); API retry policy with fail-closed on deterministic defects; **max 2 active bands per pod with dynamic backfill**; 36 GiB per band provisional; OpenAI tool availability NOT_APPLICABLE (proven); common prompts hash-identical | §9 |
| 2026-08-26 | **Topology change recorded: four simultaneous bands → maximum two active + dynamic backfill.** Semantic relevance map produced for existing H100 evidence; Q5's four-way co-residency factor is explicitly NOT the formal campaign's admission authority; `TWO_WAY_FORMAL_TOPOLOGY_REHEARSAL` raised as required new evidence | §9A |
| 2026-08-26 | **Part 2 operator ruling.** Reasoning effort FROZEN at HIGH (implementation `PENDING_IMPLEMENTATION`, F-LLM-5) · band queue order FROZEN (`10-14`,`15-19` active; `0-3`,`4-9` queued) · bounded live seed probe authorized and executed | §9.4, §9.6, §9.10 |
| 2026-08-26 | **Bounded live probe on the production path** (`chat.completions` + `gpt-5.5`, 7 calls, ~250 tokens): `reasoning_effort` accepted AND effective, omitted ≠ high · `temperature` **not tunable** (only default 1) · `top_p` **unsupported** · `seed` accepted but **inert**, no `system_fingerprint` · alias resolves to `gpt-5.5-2026-04-23` · account limits 10,000 RPM / 4,000,000 TPM | §9.4–9.6, §9.12, §9C |
| 2026-08-26 | **Correction to §9.15.** The recorded "provider-owned sampling regime" limitation was overstated: temperature and top_p are not tunable on this model, so there is no drift risk on those axes | §9.15 |
| 2026-08-26 | **F-LLM-4 CLOSED** — expected 4-chain burst audited against live account limits; ~6.6× token headroom worst case, ~2,500× request headroom. No fairness scheduler warranted; shared-vs-separate key is not a fairness question at this scale | §9.12 |
| 2026-08-26 | Retry options reproduced untruncated; **Option D added** (unbounded retry + substantially raised timeout) after the operator lifted the timeout constraint. Recommendation upgraded B → D | §9B |
| 2026-08-26 | New operator decision opened: **GPT-5.5 alias vs immutable snapshot**; minimal pin identified (8 strings, one file). Flagged that `openai_tiered_pro.json` pins `gpt-5.5`, **not** `gpt-5.5-pro` | §9C |
| 2026-08-26 | **Q-LIT-1 audit complete.** Lit-review runs EVERY iteration when enabled; its root paper is **arXiv 2406.04378 — the TIDMAD primary paper** at full-extract verbosity, which can deliver exactly the baseline architecture/training recipes §5.4 excludes, through an unhashed channel. Options L1/L2/L3 presented | §9D |
| 2026-08-26 | **Q-ISO-1 census complete.** `--baseline_isolation` does far more than suppress treatment artifacts: it also **removes built-in architectures from the action space** and fail-closed refuses any proposal reaching for one. Enabling it on blindpod alone **violates the frozen §5.10 fairness principle**. Options I1/I2/I3/I4 presented | §9E |

---
| 2026-08-26 | **Decision Area 3 — Randomness / seeds / ordering — FROZEN**: sequential ordering with `shuffle=false` (TIDMAD paper semantics) · matched gold/blind band seed authorities · four distinct frozen per-band seeds A/B/C/D · deterministic derived per-round seeds `f(campaign_seed, band_id, round_id, purpose)` · unified RNG authority across 8 surfaces · matched initialization authority with permitted realization divergence · agent trajectory `AGENT_CONTROLLED` · file/subset `EXPERIMENT_FIXED` · **bitwise-deterministic CUDA explicitly NOT required** | §10 |
| 2026-08-26 | **Planning workflow changed**: campaign-design decisions are now separated from implementation audit. Areas 3–8 proceed sequentially without per-area mechanical audits; a consolidated `PENDING_AUDIT_REGISTER` is handed to the Supervisor for parallel execution after Part 8 freezes | §7 |
| 2026-08-26 | **Decision Area 4 — Task & data semantics — FROZEN except evaluation-portion execution semantics**: regression / waveform denoising, no auto-detect · canonical TIDMAD input-target contract, split and preprocessing preserved · identical data authority both arms · **`is_trial = true` for the WHOLE campaign — the final formal phase must NOT flip it to false** · trial portions 0.1/0.1/0.1 (1 % effective training) · final formal training 1.0/0.1 (10 %) · bands unchanged · no augmentation · data parameters are `EXPERIMENT_FIXED`, never agent-controlled | §16 |
| 2026-08-26 | **Left deliberately open in Part 4**: whether final evaluation is 10 % → 100 % or 1 % → 10 % → champion-only 100 %. Deferred behind `A4-1`…`A4-5` because choosing now would mean guessing both the realized portion composition and the runtime cost | §16.6, §16.11 |
| 2026-08-26 | **Decision Area 5 — Agent action space — FROZEN**: architecture, loss, optimizer, scheduler and most training hyperparameters are `AGENT_CONTROLLED`; 10M–500M is soft encouragement with no hard parameter bound · pretrained weights and checkpoint warm-start `EXPLICITLY_DISABLED` · **segmentation size is `EXPERIMENT_FIXED` from the canonical TIDMAD FCNet authority, exact value `PENDING_AUDIT` and blocking freeze** · unchanged architecture + hyperparameter tuning alone is not an acceptable proposal · no proposal may require modifying the generic framework · ensembles, preprocessing expansion and all environment mutation `EXPLICITLY_DISABLED` · evaluation/HealthGate authority `EXPERIMENT_FIXED` | §17 |
| 2026-08-26 | 5.6 scheduler confirmed and frozen in follow-up: `AGENT_CONTROLLED` within currently supported options including "no scheduler"; no new mechanisms added; identical action space both arms | §17.6 |
| 2026-08-26 | **Part 4/6 rulings**: candidate evaluation lifecycle `PROVISIONALLY_FROZEN` (trial 1 %/1 %, formal 10 %/10 %, champion 100 %) with the E1/E2/E3 mechanism audit attached — **E3 is portion-invariant, so 1 % trial evaluation costs nothing in HealthGate sensitivity** · champion re-evaluation scoped as `R-CHAMP-1` (feasible; weights survive `--cleanup_denoised`; the only real constraint is persisting outside the record stream) · **observable metrics recorded as REQUIRED FOR v0.1.0** (`R-OBS-1`) | §18 |
| 2026-08-26 | **Decision Area 6 — Budget — OPERATOR-FROZEN except P6-A/B/C**: philosophy of equal opportunity not equal compute · 10 iterations · 3 rounds with formal last · attempt ceilings 3/5/3/3/3 preserved · **trial 2 / formal 1 epochs (intentional change from v19/v20's mode-agnostic 1)** · trial 0.10/0.10/0.01 · formal 1.0/0.10/0.10 · per-band champion 100 % terminal evaluation · **trial time budget raised 20 → 30 min, formal held at 120** · 36 GiB/band · watchdog REQUIRED (current H100 state a blocking gap) · infrastructure failure must not consume scientific opportunity | §19 |
| 2026-08-26 | Part 6 left deliberately open: **P6-A** `skip_formal_min_delta` (v19 0.0 vs v20 −1.0) · **P6-B** `bypass_formal_time_budget_min_delta` (v19/v20 0.5 vs band-fleet 0.0) · **P6-C** first-formal sentinel bypass | §19.17 |
| 2026-08-26 | **Decision Area 7 — Scoring, validity, observables, final selection — OPERATOR-FROZEN**: Golden Metric is the sole ranking authority with no hidden tie-break · HealthGate is an independent validity authority, thresholds frozen, no adaptive or post-hoc tuning · **TIDMAD per-file blocking aggregation `any_pass` → `all_pass`** (intentional change; thresholds unchanged) · generic cross-gate composition NOT required for arXiv, recorded as an ICLR item · trial best is a control signal only, never global ranking authority · cross-scope trial/formal comparison retained explicitly as a compute-allocation heuristic, never as scientific aggregation · **bypass is REAL and must also lift the normal formal execution ceiling, bounded, watchdog armed** · official trajectory = cumulative best HealthGate-valid FORMAL Golden Metric, carry-forward, no sentinels · observables frozen on two orthogonal axes with train/validation curves classified dynamic + non-ranking · **COMPOSED BEST and STRICT BEST both defined as ONE `score_vector` call over scope 0..19 — never an average of four band scalars** · terminal 100 % evaluation structurally isolated | §20A |
| 2026-08-26 | Part 7 left open: **P6/P7-A** `skip_formal_min_delta` · **P6/P7-B** `bypass_formal_time_budget_min_delta` · **P6/P7-C** elevated bypass execution hard ceiling (new) · **P6/P7-D** first-formal behaviour with no real incumbent (renamed from P6-C). Values must not be inferred from v19/v20/band-fleet defaults or worst-sentinel behaviour | §20A.13 |
| 2026-08-26 | **P6/P7 control values ALL FROZEN**: `skip_formal_min_delta = −2.0` (run formal when trial ≥ incumbent − 2.0, direction-aware via MetricOrder, HealthGate-valid winners only) · `bypass_formal_time_budget_min_delta = +0.5` against a finite incumbent, explicitly a compute-allocation heuristic · formal incumbent cold-starts at the worst sentinel and is established only by a HealthGate-valid FORMAL result, making the first-formal bypass **explicit policy rather than an accidental side effect** · **normal formal ceiling 120 min / bypass-qualified ceiling 200 min, affecting BOTH admission feasibility AND the watchdog deadline, watchdog never disabled, elevated budget never global** | §19.17, §20A.13 |
| 2026-08-26 | **Decision Area 8 — Failure / retry / resume / restart — OPERATOR-FROZEN**: four-class failure taxonomy (scientific · transient-infra · persistent-env/config · evidence/provenance) · infrastructure retry repeats the SAME scientific opportunity and decrements nothing · **no mid-training checkpoint resume contract — restart from a clean attempt boundary; partial state is never treated as complete to save compute** · ceiling failures classified by ROOT CAUSE, so legitimate exhaustion of a 30/120/200-minute ceiling is scientific while a watchdog malfunction or pod stall is not · only scientific failure advances attempt and fail-round accounting · **failure stays band-local; healthy work is never killed for wall-clock symmetry** · resume is provenance-exact and fail-closed · **transactional success — exit code 0, a model file, or one JSON record are NOT success** · operator may repair infrastructure but never mutate a candidate in place · terminal 100 % failure does not reopen search or fall through to second place · campaign-wide abort reserved for evidence- or symmetry-invalidating conditions, with an INVALIDATION MAP rather than a blanket rerun | §20B |
| 2026-08-26 | Part 8 recorded 14 audit items (`A8-1`…`A8-14`) under the binding rule that a schema or status NAME does not prove the runtime implements the semantic distinction — producer → persistence → consumer evidence is required | §20B.13 |

