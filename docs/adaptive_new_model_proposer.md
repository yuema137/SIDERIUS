# Design Proposal V2: Adaptive Scientific Discovery Framework for SIDERIUS

**Status**: design — not yet implemented. Supersedes the V1 proposal at the bottom of this file.

## 0. The actual problem (re-framed)

SIDERIUS is currently stuck at a **scientific attribution failure**, not an engineering bottleneck:

- The agent can train and score models all day, but it cannot articulate **why** WaveNet is winning.
- Without that articulation, every new proposal is a guess. The exploration loop becomes a random walk over architecture space, with no compounding insight.
- Beating WaveNet therefore requires three capabilities the system does not yet have:
  1. **Comparative causal reasoning**: not "I propose X" but "X should beat WaveNet because the WaveNet mechanism Y is bottlenecked by Z, and X relaxes Z while preserving Y."
  2. **Component lineage**: knowing which architectural primitives (dilation, gating, residuals, …) come from which past winners, so successful primitives can be inherited rather than re-invented.
  3. **Scoped exploration**: when the human says "deep-dive on WaveNet", the agent must actually stay on WaveNet — not drift into transformers because that's where the LLM's prior wants to go.

The original V1 proposal (preserved at the bottom) names the right symptoms but bundles them with several premature abstractions and one architectural-invariant violation. V2 keeps the scientific ambition and discards the unnecessary scaffolding.

## 1. Design philosophy: minimalist architecture, maximalist reasoning

This is the operational principle for everything in V2.

| Where we are minimalist | Where we are maximalist |
|---|---|
| Adding new nodes (don't, unless a new edge truly exists) | Structuring the LLM's reasoning output (force comparative, falsifiable, lineage-aware memos) |
| Adding new files / sidecars (don't — schemas + storage + protocols only) | Validating that the proposal is internally consistent before any code is written |
| Adding new LLM calls per round (each one costs quota) | Using the LLM calls we already have to demand richer, more structured output |
| Inventing new umbrella schemas (`InquiryContext`, `UnifiedContextAssembler`) for things that already exist | Adding *narrowly-scoped* fields that capture causal, lineage, and directive information |

The two columns translate into a single design constraint: **every new field we add must be either (a) directly consumed by an LLM prompt to constrain its reasoning, or (b) directly consumed by a validator to enforce a constraint the prompt asks for**. No abstractions for hypothetical future agents.

## 2. The three concrete designs

### 2A. Two-stage reasoning as forced scientific peer review

**Goal**: The proposal agent must perform a comparative causal analysis between its new hypothesis and the current SOTA *before* any code is written, and the architecture stage must be structurally tethered to that analysis.

**Lightweight implementation**: same node, two `LLMBridge` calls (mirroring the planner/reflector split that already works in the tuner). No new node, no new schema container — just a new sub-call in `ml_model_proposal_agent` and a new typed output for the first sub-call.

> **Decision (locked)**: the two-stage approach is committed despite costing one additional LLM call per proposal attempt (~2× the proposal LLM cost; small fraction of total chain quota since most usage is in tuning rounds, not proposal). The scientific-attribution benefit outweighs the cost. The reasoning sub-call MAY be routed to a cheaper model (`gemini-2.5-flash`) in Phase B if structured output quality holds; this is left as a Phase B implementation choice, not a design constraint.

#### Stage 1: `Scientific_Reasoning` sub-call → `DiscoveryMemo`

This is the "peer review of own hypothesis" stage. The sub-call's system prompt explicitly frames the LLM as a reviewer who must shoot down its own proposal before defending it.

```python
class DiscoveryMemo(BaseModel):
    """The structured output of the reasoning sub-call. Forces the LLM
    to articulate WHY before WHAT.
    """

    # --- Comparative anchor ---
    sota_model_type: str = Field(
        description="The current best-scoring model in the seed records. "
                    "Identified deterministically by the proposal agent before the LLM call."
    )
    sota_score: float
    sota_mechanism: str = Field(
        max_length=600,
        description="One paragraph: WHY does the SOTA work on TIDMAD? "
                    "Must reference physical/architectural mechanism, not vague language. "
                    "E.g. 'dilated causal convolutions cover a receptive field of "
                    "~16k samples, matching the lowest injected signal period of 0.9 ms.'"
    )

    # --- The proposal as a delta against the SOTA ---
    proposed_change: str = Field(
        max_length=400,
        description="One paragraph: what does the new proposal change "
                    "RELATIVE TO the SOTA? Must be expressible as 'replace X with Y' "
                    "or 'add Z'. Forbidden: 'completely new architecture'."
    )
    causal_hypothesis: str = Field(
        max_length=600,
        description="One paragraph: WHY the proposed change should improve the score. "
                    "Must reference (a) the SOTA mechanism it preserves, "
                    "(b) the SOTA bottleneck it relaxes, and (c) the new mechanism "
                    "it introduces. Vague language ('better', 'more powerful') is "
                    "forbidden — the next round's validator will flag empty causal claims."
    )

    # --- Falsifiable prediction (the peer-review teeth) ---
    falsifiable_prediction: FalsifiablePrediction = Field(
        description="A concrete numerical prediction tied to regime_scores. "
                    "The next round's reflector checks this prediction and "
                    "labels the hypothesis 'confirmed' / 'refuted' / 'partial'."
    )

    # --- Devil's advocate clause ---
    predicted_failure_modes: List[str] = Field(
        min_length=1, max_length=3,
        description="At least one way the proposal could fail. The reasoning "
                    "is rejected if this list is empty or if all entries are "
                    "trivially low-probability."
    )

    # --- Lineage (see §2B) ---
    inherited_components: List[InheritedComponent] = Field(
        default_factory=list,
        description="Architectural primitives reused from past winning runs."
    )

    # --- Citation attribution (see §2D) ---
    citation_sources: List[str] = Field(
        default_factory=list,
        description="cite_id values of ExpertContextItems that materially "
                    "shaped this memo's reasoning. The proposal agent is "
                    "instructed to populate this honestly — not every item "
                    "in expert_context need be cited, only the ones that "
                    "actually influenced the proposal. Empty list = the "
                    "memo was driven purely by past experiment records."
    )


class FalsifiablePrediction(BaseModel):
    regime: Literal["low_freq_kHz", "mid_freq_10kHz", "high_freq_MHz", "global"]
    current_value: float          # from SOTA's regime_scores
    predicted_value: float        # what the new model should achieve
    threshold_for_refutation: float  # below this → hypothesis refuted
    rationale: str                # why this specific number
```

#### Stage 2: `Architectural_Design` sub-call → existing `ProposalOutput` (extended)

The second sub-call is given the validated `DiscoveryMemo` as part of its prompt context, and its system prompt forces it to:

- Reference the memo's `proposed_change` verbatim when describing what the architecture does.
- Use the memo's `inherited_components` as a checklist — every listed component must appear in the proposed `model_config`.
- Justify every architectural choice that is NOT in the memo, with a one-line "deviation note". A high deviation count is a red flag the validator surfaces.

The result: the architecture stage is structurally tethered to the reasoning stage. The LLM cannot quietly drift from "I'm going to add gating to WaveNet" in the memo to "I'm going to write a transformer" in the config — the validator will catch the mismatch.

#### Why this is "peer review" and not just "longer prompts"

Three structural teeth, in order of importance:

1. **Falsifiable prediction**: every proposal commits to a numerical outcome. The next round's reflector marks it confirmed/refuted/partial. Over time the agent's hit rate becomes a measurable quantity ("the proposal agent is right about its causal predictions 38% of the time"). That's the ground truth for whether scientific reasoning is improving.
2. **Devil's advocate clause**: at least one failure mode must be named. Empty or trivial lists are rejected, forcing the LLM to actually consider downside.
3. **Architectural tethering**: the second sub-call cannot diverge from the first without a deviation note. Drift is visible.

None of these requires a new node, a new agent, or a sidecar file. They are all schema constraints + prompt constraints + one new sub-call.

---

### 2B. Component lineage and inheritance

**Goal**: track which architectural primitives ("dilated causal conv", "gated activation", "residual skip", "log-spaced FNO gates") come from which past winners, so successful primitives can be inherited explicitly rather than re-invented.

**Where the source of truth lives**: in the per-record `DiscoveryMemo.inherited_components`, NOT in `MODEL_REGISTRY`. Reasoning:

- The registry is loaded at import time and is awkward to mutate from agent code.
- Records are already append-only, schema-validated, and the natural unit of "what we tried and what happened".
- The registry as a permanent metadata store would be an inter-node communication channel by another name (you'd be reading state out of `MODEL_REGISTRY` during proposal generation, which the records-via-protocol path already provides cleanly).

**Schema**:

```python
class InheritedComponent(BaseModel):
    """One architectural primitive carried over from a past winning run."""

    component: str = Field(
        description="Short canonical name. E.g. 'dilated_causal_conv', "
                    "'gated_activation', 'log_spaced_fno_gates', 'residual_skip'. "
                    "Drawn from a controlled vocabulary (see PRIMITIVE_VOCAB below) "
                    "to make aggregation possible."
    )
    from_model_type: str = Field(
        description="The ancestor model_type, e.g. 'wavenet'."
    )
    from_run: Optional[str] = Field(
        default=None,
        description="The specific run (run_name) where this component first proved out, "
                    "if known. Optional — built-in models like 'wavenet' have no run."
    )
    contribution_evidence: str = Field(
        max_length=300,
        description="One sentence linking the component to its measured benefit. "
                    "E.g. 'gave wavenet a +0.15 lift on low_freq_kHz in run hpt_full_v1.'"
    )
    citation_source: Optional[str] = Field(
        default=None,
        description="cite_id of the ExpertContextItem (see §2D) that motivated "
                    "inheriting this component. None means the inheritance was "
                    "driven purely by past experiment records, not by an upstream "
                    "agent's finding."
    )
```

**Open vocabulary with structured promotion** (`PRIMITIVE_VOCAB`):

A pure fixed vocabulary blocks discovery; a pure free-text vocabulary destroys aggregation through spelling drift. The compromise is a **two-tier vocabulary that grows by structural promotion**:

- **Tier 1 — `canonical`**. A small (~20 entry) hand-curated seed list, drawn from WaveNet, U-Net, FNO, and the existing built-in models. Each entry has a one-sentence definition and (where relevant) an AST/regex pattern the validator uses to verify that a claimed inheritance actually appears in the implementation. The seed list is tracked in the repo as `agent/schemas/primitive_vocab.json` and is **immutable to agents** — only humans edit it via PRs.
- **Tier 2 — `candidate`**. Open-vocabulary entries the agent introduces when no canonical entry fits its proposal. Each candidate carries a `name`, `description`, the `proposed_by_run`, and (optionally) a regex hint the agent suggests for future validation. Candidates are NOT stored in `primitive_vocab.json`; they live as fields inside the per-run experiment records, exactly like every other piece of agent-generated state. **There is no shared mutable file** — the seed is tracked + read-only, the runtime extension is derived from records on every interpretation pass. This avoids the same write-conflict / git-pull-clobbering class of bug we just fixed for the YAML configs.

The full runtime vocabulary that the proposal agent sees in any given round is:
```
runtime_vocab = canonical_seed                       # tracked, immutable to agents
              ∪ promoted_from_records                # candidates the interpretation agent has marked promoted
              ∪ active_candidates_from_records       # unpromoted candidates (with usage stats)
```

The interpretation agent computes this union from records, marks promotions in its output schema, and the protocol passes it to the proposal agent. No shared state.

#### Schema additions

```python
class PrimitiveVocabEntry(BaseModel):
    """A single primitive — either canonical (from the tracked seed file)
    or candidate (proposed by the agent and present in records)."""
    name: str = Field(description="Canonical snake_case name.")
    description: str = Field(max_length=200, description="One-sentence definition.")
    tier: Literal["canonical", "candidate"] = "candidate"
    pattern: Optional[str] = Field(
        default=None,
        description="AST/regex hint the validator uses to verify implementations. "
                    "Mandatory for canonical entries, optional for candidates."
    )
    proposed_by_run: Optional[str] = None  # candidates only
    seen_in_runs: List[str] = []           # all runs that have used this primitive
    aliases: List[str] = []                # observed spelling variants the aggregator collapsed
```

The existing `InheritedComponent.component` field continues to be a free-text name, but the proposal agent's prompt now includes the full `runtime_vocab` (both tiers, clearly labeled) and is instructed: "Prefer canonical entries verbatim. Use a candidate only if no canonical entry fits, and provide a one-sentence description and an optional regex hint when you do."

#### Promotion rule (autonomous, conservative)

The interpretation agent, on each run, walks all candidates currently active in records and applies a **structural promotion criterion**:

> A candidate is promoted to canonical if **all** of:
>   1. it has appeared in `inherited_components` of ≥3 distinct runs, AND
>   2. at least one of those runs scored above the current SOTA, AND
>   3. its description has been semantically deduplicated against existing canonical entries (the LLM judges whether it's "really new" or a synonym for an existing one — synonyms are merged via the `aliases` list rather than promoted), AND
>   4. either the candidate already carries a regex/AST hint, or the LLM can synthesize one from the records that used it.

A candidate that fails (1) or (2) stays in candidate tier. A candidate that fails (3) is **merged** into an existing canonical entry as an alias (the candidate name is added to `aliases`, and future LLM runs will see it as canonical via the alias). A candidate that fails (4) is held until enough information exists.

The criterion is intentionally strict: we want canonical promotion to be a **rare and meaningful event**, not noise. We will tune the thresholds (3 runs, SOTA-beating) after the first batch of real chain runs.

#### Why no human review gate by default

The interpretation agent's output schema has a structured `vocab_changes` field listing every promotion / merge / alias decision made in that round. Humans see these in the dashboard and via PR review of the next chain output, but they do not block the loop. Rationale: a blocking human review point would turn every iteration into a synchronous handoff, defeating the chain's autonomy. If the autonomous criterion misbehaves, the fix is to tighten thresholds, not to insert a human in the critical path.

If we need a human-gated mode later, it is a one-line config change: `vocab_promotion_mode: Literal["auto", "review"]` on the interpretation agent's input. Defer until evidence shows we need it.

#### Validator integration with candidates

The §2B validator check for `InheritedComponent` already short-circuits unknown vocab entries with "can't check". Candidates land in the same path: their pattern (if present) is opportunistically checked, and a missing pattern means the claim is recorded but unverified. When a candidate is promoted to canonical, its pattern (now mandatory) is added to the validator's known patterns map. **No special-casing is needed in the validator.**

#### Three concrete examples

| Scenario | What happens |
|---|---|
| Agent proposes a wavenet variant with `dilated_causal_conv` | `dilated_causal_conv` is in the canonical seed → recorded as a verified inheritance, pattern matched against the .py source. |
| Agent proposes a "log-spaced FNO gates" variant, name not in any tier yet | Recorded as a candidate, with the LLM-supplied description and an optional regex hint. seen_in_runs gets one entry. |
| Three rounds later, "log_spaced_fno_gates" has appeared in 4 distinct runs and 2 scored above SOTA | The interpretation agent promotes it to canonical, adds it to the next round's `runtime_vocab` with `tier=canonical`, and writes a `vocab_changes` event. The seed file in the repo is unchanged; promotion is reconstructible from records on any future run. |

**Validator integration** (cheap, high-leverage):

The `ml_code_validator_agent` already loads the proposed plugin file. Add one new check:

```python
def check_inherited_components(plugin_source: str, claimed: List[InheritedComponent]) -> List[str]:
    """Verify each claimed inherited_component appears in the implementation.
    Returns a list of unsubstantiated claims (empty = all good)."""
    missing = []
    for ic in claimed:
        if ic.component not in COMPONENT_PATTERNS:
            continue  # unknown vocab entry, can't check
        pattern = COMPONENT_PATTERNS[ic.component]  # e.g. r"dilation\s*=\s*[2-9]"
        if not re.search(pattern, plugin_source):
            missing.append(ic.component)
    return missing
```

Unsubstantiated claims become a validation failure → the implementor retries. This closes the loop: claiming an inherited component now requires actually using it.

**Cross-round aggregation** (handled by the interpretation agent, no new node):

The interpretation agent already aggregates records. Add one new derived field to `InterpretationOutput`:

```python
component_leaderboard: Dict[str, ComponentStats]
```

where `ComponentStats` tracks: how many times each primitive has appeared, the average score of runs that used it, the best-scoring run that used it, and which model_types it has shown up in. The proposal agent's next-round prompt receives this leaderboard verbatim. **Empirical inheritance becomes the dominant signal**: "log_spaced_fno_gates appeared in 4 of the top 5 runs across gated_fno and one wavenet variant" is far more useful than the raw record dump.

**Lineage as a graph**: each new model points to ≥1 ancestor via `inherited_components.from_model_type`. The dashboard can render this as a tree later (out of scope for now). The graph is fully derived from existing records — no separate `lineage.json` file.

---

### 2C. Guided mode: prompt + schema + validator guardrails

**Goal**: when the human says "deep-dive on WaveNet", the agent must actually stay on WaveNet. The current `human_advice` field is a soft hint that the LLM routinely ignores.

**Schema**: one new optional field on `ProposalInput`.

```python
class ResearchDirective(BaseModel):
    mode: Literal["autonomous", "guided"] = "autonomous"

    # The next four fields are only meaningful in guided mode.
    base_model: Optional[str] = Field(
        default=None,
        description="The model_type the agent must treat as its starting point. "
                    "All proposals must be expressible as a delta against this model."
    )
    target_components: List[str] = Field(
        default_factory=list,
        description="Components the agent IS allowed to modify. "
                    "Drawn from PRIMITIVE_VOCAB. Empty = no restriction. "
                    "E.g. ['dilation', 'gating', 'residual_skip']."
    )
    forbidden_components: List[str] = Field(
        default_factory=list,
        description="Components the agent MUST NOT introduce. "
                    "E.g. ['attention', 'transformer', 'fno']. "
                    "Validator rejects proposals that violate this."
    )
    rationale: str = Field(
        max_length=400,
        description="The human's reasoning for the constraint, surfaced in the "
                    "agent's system prompt so the LLM understands the WHY, not just the WHAT."
    )

    @model_validator(mode="after")
    def _guided_requires_base(self):
        if self.mode == "guided" and not self.base_model:
            raise ValueError("guided mode requires base_model")
        return self


class ProposalInput(BaseModel):
    # ... existing fields ...
    research_directive: ResearchDirective = Field(
        default_factory=ResearchDirective,  # autonomous by default
    )
```

**Three guardrail layers**, in order of strictness:

1. **Prompt layer (soft)**. In guided mode, the proposal agent's system prompt is conditionally extended with a clearly-labeled `[GUIDED MODE DIRECTIVE]` block:
   ```
   [GUIDED MODE DIRECTIVE]
   You are operating under a human-issued constraint:
     - Base model:        {base_model}
     - You MAY modify:    {target_components or "any component of the base model"}
     - You MUST NOT add:  {forbidden_components or "(no forbidden components)"}
     - Human's reasoning: "{rationale}"

   This is not a hint. Proposals that violate these constraints will be
   rejected by the validator and you will be asked to retry. Stay on
   the base model. Do not propose architectures from a different family
   no matter how attractive they appear.
   ```

2. **Discovery Memo layer (medium)**. The reasoning sub-call's `DiscoveryMemo.sota_model_type` is **forcibly set** to `directive.base_model` in guided mode (not chosen by the LLM). The `proposed_change` field must therefore be expressed as a delta against the chosen base. The LLM physically cannot frame the proposal as "a fresh transformer" because the comparative anchor is fixed.

3. **Validator layer (hard)**. `ml_code_validator_agent` gets two new checks, only active in guided mode:
   - **`check_base_model_inheritance`**: the proposed plugin must `import` from or structurally resemble the `base_model`'s module. (Concretely: at least one `inherited_components` entry must have `from_model_type == directive.base_model`.)
   - **`check_forbidden_components`**: each entry in `directive.forbidden_components` is mapped to a regex in `FORBIDDEN_PATTERNS` (e.g. `attention` → `nn\.MultiheadAttention|self_attention`) and matched against the plugin source. Any hit fails validation.

Failures from layers 2 and 3 trigger the existing implementor retry loop with a clear error message. The LLM gets up to N retries to comply; after that, the iteration is marked failed and the orchestrator is notified.

**What this buys us**: in guided mode, drift is structurally impossible at layer 3 even if the LLM ignores the prompt at layer 1. In autonomous mode, all of these fields default to empty/None and the existing behavior is preserved bit-for-bit. Backward compatible by construction.

> **Decision (locked)**: guided mode defaults to **OFF** (`mode="autonomous"`). Today's chains, today's CLI commands, today's tests all behave identically after Phase D. Guided mode is opt-in via a new optional flag on the chain orchestrators and on `ProposalInput.research_directive`. We will only flip to guided mode by explicit human action — never automatically.

---

### 2D. Multi-agent extensibility — Expert Context Sources

**Goal**: the proposal agent will not be the only LLM in the system forever. SIDERIUS's roadmap includes several specialized upstream agents, each producing a different *kind* of context the proposal agent should treat as ground truth. V2 must accept any of them through a single polymorphic interface, with no per-agent special-casing in the proposal node.

#### The future agents we're designing for

| Future agent | Produces | Kind of context |
|---|---|---|
| `data_analysis_agent` | Empirical findings about the raw signals — noise distributions, SQUID-specific artifacts, per-frequency-band SNR, observed periodicities, unexplained peaks | **empirical** |
| `physics_expert_agent` | Theoretical constraints — symmetries, conservation laws, mass-range / energy bounds, allowed coupling structures | **theoretical** |
| `literature_review_agent` | Architecture ideas synthesized from recent ML / physics papers | **literature** |
| `research_narrative_agent` (optional) | Meta-summary of what's been tried; plateau detection; strategic suggestions | **narrative** |
| Human expert | Hand-written advice (today's `human_advice`) | **human** |

Crucially, these agents differ in *what* they say but not in *how* they say it — they all produce typed structured advice that the proposal agent should weigh against past experiment records when forming its `DiscoveryMemo`. V2's design principle here is **don't invent an umbrella container**. The V1 proposal called for an `InquiryContext` / `UnifiedContextAssembler` to hold all these sources — V2 explicitly rejected that as premature abstraction. Instead, V2 reuses the existing pattern: schemas + protocols. Each upstream agent has its own output schema, and a protocol function (`{source}_to_ml_model_propose`) maps that output into the proposal agent's input. The proposal agent treats all of them through one minimal polymorphic field.

#### The polymorphic field: `ExpertContextItem`

Replace today's free-form `human_advice: str` field on `ProposalInput` (and on the other consuming nodes once they catch up) with a typed list:

```python
class ExpertContextItem(BaseModel):
    """One piece of upstream context. The proposal agent treats human-written
    advice and machine-generated analysis through the same interface — only
    the `source` and `kind` fields distinguish them. New upstream agents are
    added by emitting more of these items, NOT by adding new schema fields."""
    source: str = Field(
        description="Identifier of the producer. E.g. 'human', "
                    "'data_analysis_agent', 'physics_expert_agent', "
                    "'literature_review_agent'. Conventionally the agent's "
                    "CLAUDE.md taxonomy name, but free-text so future agents "
                    "don't require a schema change to register."
    )
    kind: Literal["empirical", "theoretical", "literature", "human", "narrative"]
    content: str = Field(
        max_length=4000,
        description="The actual advice / finding / constraint. Markdown allowed."
    )
    cite_id: str = Field(
        description="Short stable ID the proposal agent can reference in its "
                    "DiscoveryMemo.citation_sources. E.g. "
                    "'data_2026_04_09_psd_50hz_peak'. Used for lineage attribution."
    )
    produced_at: Optional[str] = None  # ISO timestamp
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Optional self-reported confidence from the producing agent. "
                    "Lets the proposal agent down-weight low-confidence claims."
    )


class ProposalInput(BaseModel):
    # ... existing fields ...
    expert_context: List[ExpertContextItem] = Field(default_factory=list)
    # human_advice: str  ← deprecated; the protocol layer wraps any legacy
    #                       string into an ExpertContextItem with
    #                       source='human', kind='human', cite_id='human_advice'.
```

The migration is non-breaking: legacy code that passes `human_advice: "..."` is wrapped at the protocol boundary. Any future agent (data analysis, physics, literature, narrative) emits `ExpertContextItem`s through its own protocol function — no schema invention required, no proposal-agent code changes needed to support the new source.

This is the V2 minimalist principle in action: **one small new field unlocks N future upstream agents**. We are not creating an `InquiryContext` container or a `UnifiedContextAssembler` orchestrator. We are extending a list.

#### How the Discovery Memo consumes Expert Context

The reasoning sub-call (§2A) iterates over `expert_context` and renders each item as a labeled block in its prompt:

```
[CONTEXT]
─── source: data_analysis_agent (empirical, confidence=0.92, cite_id=data_2026_04_09_psd_50hz_peak) ───
The validation set shows a strong periodic contamination at exactly 50 Hz across
all 20 files, with sidebands at ±0.5 Hz. This is consistent with mains pickup
and is unrelated to the injected axion signals. Models that attempt to fit it
will overfit; models that filter it out should improve low_freq_kHz scores.

─── source: physics_expert_agent (theoretical, confidence=0.85, cite_id=phys_2026_04_08_axion_mass_bounds) ───
Axion-like particle masses below 10⁻¹⁰ eV correspond to oscillation frequencies
above 24 Hz. Signal contributions below 24 Hz are unphysical for the target
model and should be ignored or down-weighted in scoring.

─── source: human (human, cite_id=human_advice) ───
Stick with WaveNet-family modifications this iteration; no transformers.
```

The proposal agent's reasoning is then explicitly required to **cite** the items that influenced its memo via `DiscoveryMemo.citation_sources`. Continuing the example, a memo motivated by the 50 Hz finding would set `citation_sources=["data_2026_04_09_psd_50hz_peak"]` and would justify the proposed gating layer in `causal_hypothesis` by referencing that specific empirical fact.

#### Why citation matters

The user's research goal is scientific attribution. Citation is the audit trail:

1. **Provenance per decision**. Every architectural choice can be traced to either past records (no citation) or a specific upstream finding (cited). "We added a 50 Hz notch because the data analysis agent observed `data_2026_04_09_psd_50hz_peak`" is a defensible scientific claim; "we added a 50 Hz notch because the LLM thought it might help" is not.

2. **Empirical value of each upstream agent**. The interpretation agent aggregates citations across all rounds: "of the 12 successful proposals in this exploration, 7 cited `data_analysis_agent` and 4 cited `physics_expert_agent`." Over time this becomes the metric for whether a given upstream agent is worth its quota cost. An agent whose citations correlate with successful runs earns its place; one whose citations correlate with refuted hypotheses gets its trust weight reduced.

3. **Closing the falsification loop**. When the §2A `falsifiable_prediction` is refuted in a later round, the reflector can also flag the cited sources: "this prediction was refuted, and it cited `data_analysis_agent#psd_50hz_peak` — that finding may be misleading." This is the only mechanism that lets SIDERIUS tell apart "the LLM was wrong" from "the upstream evidence was wrong".

#### Phase-A regime_scores as the empirical extension point

`regime_scores` (Phase A in §5) is per-experiment, per-frequency-band performance breakdown. It is **orthogonal** to `expert_context` (which is per-iteration, dataset-global advice) — but the two are deliberately structured to compose.

`regime_scores` is `Dict[str, float]`, not a fixed schema. The current seed regimes are `{low_freq_kHz, mid_freq_10kHz, high_freq_MHz, global}`, mirroring the per-file frequency band map. When the Data Analysis Agent comes online, it can:

- **Propose new regime keys** — e.g. `harmonic_50hz`, `mains_pickup`, `psd_drift_window` — by emitting an `ExpertContextItem` whose content is "I recommend adding the regime `harmonic_50hz` defined as files X, Y, Z."
- **Recompute regime_scores under the new definitions** retroactively from existing records (regime aggregation is deterministic Python on `file_vector`, so re-aggregation is cheap).
- **Cite the new regime in its findings** — "the model's `harmonic_50hz` regime score has been below 0.4 for the last 5 rounds; this is the dominant remaining error."

Regime definitions themselves should be canonicalized via the same two-tier vocabulary mechanism we set up for `PRIMITIVE_VOCAB` in §2B (seed + open candidates + structural promotion). This is a pleasant symmetry: the same machinery handles both architectural primitives and empirical regimes. We call this out in §6 as a future consolidation rather than a Phase-A requirement, because Phase A only needs the `Dict[str, float]` shape, not the full vocabulary mechanism.

**Phase A is therefore extensible by construction**: the schema is a dict, the aggregation is deterministic Python over per-file scores, and any new regime the Data Analysis Agent later proposes can be added without a schema migration. We do not need to design Data Analysis Agent integration in Phase A — we only need to NOT box ourselves out of it, which the dict shape ensures.

---

## 3. What stays the same

These existing pieces are doing their job and need no change:

| Piece | Status |
|---|---|
| `LLMBridge` and the planner/reflector split | Reused as-is. The new reasoning sub-call is just another `bridge.generate(...)` call. |
| The retry policy (5 retries, 2.5–40s backoff) | Applies automatically to the new sub-call. |
| `protocols/` for inter-node communication | Already does the "merge multiple upstream outputs" job. The V1 `UnifiedContextAssembler` is a rename of this; we don't need it. |
| `human_advice` plumbing | Reused as the carrier for `ResearchDirective.rationale` and as the carrier for autonomous-mode advice. |
| `MODEL_REGISTRY` and `description.md` files | Reused as the source of "what does each built-in model do" for the SOTA mechanism description. No new metadata fields on the registry. |
| The dashboard | Reused as-is. A future enhancement can render the lineage tree. |

## 4. What we explicitly drop from V1, and why

| V1 idea | Drop reason |
|---|---|
| `InquiryContext` umbrella schema | Three of its four sub-fields already exist as `seed_records`, `human_advice`, and `description.md`. The fourth (Literature Agent) doesn't exist yet. Wrapping existing fields in a new container adds a layer without adding capability. **Defer until the Literature Agent appears**, then add it as a 4th typed field on `ProposalInput`. |
| `Research Directive` as a prose field | Replaced by the structured `ResearchDirective` schema in §2C. Free-text directives are why the LLM currently ignores them. |
| Splitting the proposal agent into two graph **nodes** (`Scientific_Reasoning_Subnode` and `Architectural_Design_Subnode`) | Replaced by two LLM **sub-calls inside one node** (§2A). Same scientific benefit, no graph surgery. Escalate to a node split only if a future Literature Agent needs to feed into the reasoning sub-call independently. |
| `MemorySummarizer` as a new LLM agent | Replaced by the deterministic `component_leaderboard` derived field on `InterpretationOutput` (§2B). No new LLM call per round; quota stays flat. |
| `UnifiedContextAssembler` | Already exists, called `protocols/`. Renaming would not add value. |
| `Research_Journal.md` sidecar markdown file | **Hard veto.** Violates the "schemas + storage + protocols ONLY" invariant in `CLAUDE.md`. The same narrative can be derived from records on demand or live in one node's output schema. |

## 5. Implementation phasing (incremental, each phase shippable on its own)

| Phase | Change | Effort | Unlocks |
|---|---|---|---|
| **A** | Add `regime_scores: Dict[str, float]` (deterministic aggregation of `file_vector`) to `ExperimentRecord`. Reflector and proposal prompts read it. **Crucially, the dict shape is the extension point for the future Data Analysis Agent (§2D): new regime keys can be added without a schema migration.** Phase A only commits to the shape, not the full vocabulary mechanism. | small | The LLM gets a structured "gradient" instead of raw arrays. Foundation for §2A's `FalsifiablePrediction` AND for §2D's empirical extensibility. |
| **B** | Add `DiscoveryMemo` schema and the reasoning sub-call inside `ml_model_proposal_agent`. Architecture sub-call is given the validated memo. Falsifiable prediction is recorded but not yet checked. Add `ExpertContextItem` (§2D) and the protocol-layer wrapping of legacy `human_advice` strings. The proposal agent's reasoning prompt iterates over `expert_context` instead of reading `human_advice`. | medium | Scientific peer review is now structurally enforced. Each proposal commits to a causal claim. **The polymorphic input slot for future upstream agents is in place.** |
| **C** | Add `InheritedComponent` schema, `PRIMITIVE_VOCAB`, and the `check_inherited_components` validator check. Add `component_leaderboard` to `InterpretationOutput`. | medium | Lineage tracking is end-to-end. Empirical inheritance becomes the dominant signal in the next round's prompt. |
| **D** | Add `ResearchDirective` schema and the three guardrail layers in §2C. | medium | Guided mode actually constrains the search. |
| **E** | Add the `falsifiable_prediction` retrospective check inside the reflector: confirmed / refuted / partial label, written into the record. Aggregate the hit rate in `InterpretationOutput`. | small | The proposal agent's scientific accuracy becomes a measurable, monitorable quantity. |

Each phase has its own tests. Each is independently revertable. Each is small enough to commit and PR cleanly.

## 6. Open questions

1. **Falsifiable prediction granularity**. Predicting one regime score is the minimum. Should we also force a prediction on `global_score`? Risk: redundancy. Benefit: catches proposals that improve one regime at the cost of overall performance.
2. **PRIMITIVE_VOCAB seeding**. We need an initial ~20-entry list for the canonical tier. Should it be hand-curated by the human, mined from the existing `description.md` files, or extracted by a one-off LLM pass over the registry? Hand-curated is most reliable but slowest. **Recommendation**: hand-curate the first ~10 from WaveNet + UNet + FNO descriptions to set the quality bar, then let the open-vocabulary promotion mechanism grow it organically.

2a. **Promotion thresholds**. The default rule is "≥3 distinct runs AND at least one above SOTA AND semantic dedup AND pattern present". The numbers are guesses. After the first chain run with the vocabulary mechanism live, we should look at the candidate distribution and tune. Open question: should the SOTA threshold be "above the current iteration's best" (strict, raises the bar over time) or "above the seed-run baseline" (loose, freezes the bar)?

2b. **Semantic dedup judge**. The promotion rule's step 3 asks an LLM to decide whether a candidate is "really new" or a synonym for an existing canonical entry. This is fragile — the same LLM might judge differently on different invocations. **Mitigation**: deduplication runs only at promotion time (rare), uses the reflector model for stability (cheap, quota-friendly), and the merge decision is recorded in `vocab_changes` so a human can override after the fact.

2c. **Promotion-mode flag**. The doc proposes autonomous promotion as the default. A `vocab_promotion_mode: Literal["auto", "review"]` flag on the interpretation agent input would let us flip to human-gated mode if autonomous misbehaves. Defer adding the flag until we see autonomous behavior in practice.
3. **Component pattern matching**. `COMPONENT_PATTERNS` (regex per primitive) is the weakest part of §2B's validator integration — regex against PyTorch source is fragile. Alternative: use AST inspection (`ast.parse` on the plugin file) and look for specific class/function calls. More work, more reliable.
4. **Guided-mode escape hatches**. Should there be a way for the LLM to formally request a relaxation of the directive (e.g. "I think the constraint is impossible to satisfy because of Y; please review")? Otherwise stuck states could waste rounds. But adding an escape hatch risks defeating the point of guided mode.
5. **Hit rate as feedback to the planner**. Once Phase E is in place, the planner could be told its own historical accuracy ("your causal predictions have been confirmed 38% of the time"). Self-knowledge of fallibility might improve future memos. Risk: the LLM becomes overconfident or defensive.

6. **First non-human upstream agent — Data Analysis Agent**. Phase B introduces the `ExpertContextItem` polymorphic input slot, but it does not introduce any new producer of those items beyond the human-advice wrapper. The first real test of the §2D design will be when we wire up the Data Analysis Agent. Open questions for that future PR:
   - Where does the Data Analysis Agent run in the workflow — once at exploration start (cheap, static), once per iteration (more expensive, can adapt to new findings), or on demand from the proposal agent?
   - Should its findings be persisted into the records or live only in memory between runs? (Persisting them turns the records into a growing knowledge base; not persisting keeps the chain stateless.)
   - How does it produce `cite_id` values that are stable across re-runs of the same analysis? Hash of the finding content? Timestamped slug?
   - How do we evaluate whether its findings are actually useful — citation hit rate (per §2D) is the right metric, but Phase B doesn't yet collect it.

7. **Regime vocabulary consolidation**. `regime_scores` (Phase A) is a `Dict[str, float]` whose keys are currently hand-set. The natural symmetry with `PRIMITIVE_VOCAB` (§2B) suggests using the same two-tier seed-plus-promotion mechanism for regime keys: a hand-curated seed (`low_freq_kHz`, `mid_freq_10kHz`, `high_freq_MHz`, `global`) plus open candidates that the Data Analysis Agent can introduce and the interpretation agent can promote. Defer until Phase A's seed regimes have been stress-tested by real chain runs — premature consolidation would just be the V1 mistake under a different name.

---

## 7. Implementation checklist

This section breaks each phase from §5 into concrete sub-tasks, the files they touch, and the verification gates that must pass before moving to the next phase. The phases are designed so that **each one is independently shippable as a single PR**: at any cut point the system is fully functional, just with fewer features than the next phase would add.

**Conventions**:
- ☐ unchecked, ☑ checked. The doc author updates these as the work lands.
- "**Verify**" entries are commands to run, expected outputs to see, or unit tests to pass.
- "**Files**" lists every path the phase touches. New files are marked `(new)`.
- "**Depends on**" lists the prior phase(s) the current phase needs in place.
- Estimated PR size is rough (small = <300 LOC, medium = 300–1000, large = >1000).

---

### Phase A — `regime_scores` foundation

**Goal**: every experiment record carries a deterministic per-regime breakdown of `file_vector`, so the LLM gets a structured "gradient" instead of a raw 20-element array. Establishes the dict shape that §2D will later extend.

**Depends on**: nothing. This is the first phase.

**PR size**: small.

**Files**:
- `agent/schemas/hyperparam_tuning.py` — add `regime_scores` field to `ExperimentRecord` (and `BestExperimentRecord` if it exists).
- `execute_tools/scoring_utils.py` (or a new `regime_aggregator.py`) — add the deterministic aggregation function.
- `nodes/ml_hyperparameter_tune_agent.py` — call the aggregator after scoring, write the result into the record before validation.
- `agent/prompts.py` — extend the planner and reflector prompts to render `regime_scores` cleanly when present.
- `tests/unit/agent/tune_ml_hyperparam_agent/test_regime_aggregation.py` (new) — unit tests for the aggregator.
- `tests/unit/agent/tune_ml_hyperparam_agent/test_hyperparam_schemas.py` — extend with `regime_scores` round-trip tests.

**Sub-tasks**:
- ☐ A.1 Define seed regime keys: `{"low_freq_kHz", "mid_freq_10kHz", "high_freq_MHz", "global"}`. The mapping from `file_index` to regime is documented inline (file 0–4 → low_freq_kHz, file 5–10 → mid_freq_10kHz, file 11–19 → high_freq_MHz, all files → global). Mirrors `tuner_advice/gated_fno_freq_band_aware_v1.json`.
- ☐ A.2 Implement `aggregate_regime_scores(file_vector: List[Optional[float]]) -> Dict[str, float]`. Skips `None` entries. Returns `0.0` (not `None`) for regimes with all-None inputs so downstream code never has to None-check.
- ☐ A.3 Add `regime_scores: Dict[str, float] = Field(default_factory=dict)` to `ExperimentRecord`. Default-empty for backward compatibility with existing records.
- ☐ A.4 Wire the aggregator into the tuner's scoring path so every successful round populates `regime_scores`. Skipped/failed rounds default to `{}`.
- ☐ A.5 Update the planner prompt template to render `regime_scores` as a small markdown table when non-empty.
- ☐ A.6 Update the reflector prompt template the same way.
- ☐ A.7 Unit tests: aggregator on (a) all-valid file_vector, (b) all-None, (c) mixed, (d) empty list. Schema round-trip with and without the field.
- ☐ A.8 Smoke test: run a 1-round tuner on lilab and grep the resulting record JSON for `regime_scores`. Confirm the four seed keys all appear.

**Verify**:
- `uv run pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q` — all tests pass including the new ones.
- `uv run python nodes/ml_hyperparameter_tune_agent.py --max_rounds 1 --force_model punet --is_trial --run_name regime_smoke` — completes; the record contains a non-empty `regime_scores` dict.

---

### Phase B — `DiscoveryMemo` + `ExpertContextItem` (the polymorphic input slot)

**Goal**: every proposal commits to a structured causal hypothesis with a falsifiable prediction; the proposal agent's input slot becomes polymorphic so future upstream agents can plug in without schema invention.

**Depends on**: Phase A (the falsifiable prediction needs `regime_scores` to refer to).

**PR size**: medium.

**Files**:
- `agent/schemas/proposal.py` — add `DiscoveryMemo`, `FalsifiablePrediction`, `InheritedComponent`, `ExpertContextItem`. Add `expert_context: List[ExpertContextItem]` to `ProposalInput`. Keep `human_advice: str` deprecated for backward compat.
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — update the protocol to wrap legacy `human_advice` strings into a single `ExpertContextItem` with `source="human", kind="human", cite_id="human_advice"`.
- `nodes/ml_model_proposal_agent.py` — split the LLM call into two `bridge.generate(...)` sub-calls. First call returns a `DiscoveryMemo`; second call receives the validated memo and returns the existing `ProposalOutput`.
- `agent/prompts.py` — add `DISCOVERY_MEMO_SYSTEM_PROMPT` (with the peer-review framing) and update `PROPOSAL_SYSTEM_PROMPT` to require references to the memo.
- `tests/unit/agent/proposal_agent/test_discovery_memo_schema.py` (new) — schema validation tests.
- `tests/unit/agent/proposal_agent/test_proposal_agent.py` — extend with mocked-LLM tests for the two-stage flow.
- `tests/integration/nodes/test_ml_model_proposal_agent.py` — extend Tier-1 test with a real LLM call producing a valid memo + proposal.

**Sub-tasks**:
- ☐ B.1 Define `FalsifiablePrediction` schema. Validator: `predicted_value` must differ from `current_value` by a meaningful margin; `threshold_for_refutation` must be on the correct side of `current_value`.
- ☐ B.2 Define `InheritedComponent` schema with `citation_source: Optional[str] = None`.
- ☐ B.3 Define `ExpertContextItem` schema. Validator: `cite_id` must be unique within a single `expert_context` list (no duplicate IDs).
- ☐ B.4 Define `DiscoveryMemo` schema with all fields from §2A. Validator: `predicted_failure_modes` must have ≥1 entry; `causal_hypothesis` cannot be empty after stripping whitespace.
- ☐ B.5 Add `expert_context: List[ExpertContextItem]` to `ProposalInput`, default empty list. Mark `human_advice: str` as deprecated in the field description.
- ☐ B.6 Update `ml_result_interp_to_ml_model_propose` protocol to wrap legacy `human_advice` strings. Existing test cases continue to pass without changes.
- ☐ B.7 Implement reasoning sub-call in `ml_model_proposal_agent`. Inputs: SOTA records, expert_context, prior interpretation. Output: validated `DiscoveryMemo`.
- ☐ B.8 Implement architecture sub-call. Inputs: validated `DiscoveryMemo`, the same context. Output: existing `ProposalOutput` schema, with the memo serialized into it for downstream consumers.
- ☐ B.9 Write `DISCOVERY_MEMO_SYSTEM_PROMPT` with the three peer-review teeth (causal anchor, devil's advocate, falsifiable prediction).
- ☐ B.10 Update the architecture sub-call's prompt to render the memo as labeled context and require explicit memo references in the architecture's reasoning.
- ☐ B.11 Add the labeled-block rendering of `expert_context` items (per §2D worked example) to both sub-call prompts.
- ☐ B.12 Schema unit tests for all new schemas.
- ☐ B.13 Mocked-LLM unit tests for the two-stage flow, including (a) memo validation failure → retry, (b) architecture deviation note presence, (c) backward-compat with empty `expert_context`.
- ☐ B.14 Tier-1 integration test: real LLM produces a valid memo + valid proposal; the memo's `proposed_change` actually appears in the architecture's `model_config` description.

**Verify**:
- All unit tests pass: `uv run pytest tests/unit/agent/proposal_agent/ -q`.
- Tier-1 integration: `uv run pytest tests/integration/nodes/test_ml_model_proposal_agent.py -m real_run -v`.
- Manual: inspect a generated `DiscoveryMemo` JSON and confirm it cites `regime_scores` fields by name in `causal_hypothesis`.

---

### Phase C — `PRIMITIVE_VOCAB` + lineage validator + open-vocabulary promotion

**Goal**: claimed inheritance becomes verifiable; the system grows its primitive vocabulary by structural promotion across runs.

**Depends on**: Phase B (the memo is where `inherited_components` lives).

**PR size**: medium.

**Files**:
- `agent/schemas/primitive_vocab.json` (new, tracked) — hand-curated seed list of canonical entries.
- `agent/schemas/primitive_vocab.py` (new) — `PrimitiveVocabEntry` schema, `load_seed_vocab()`, `COMPONENT_PATTERNS` regex/AST map.
- `nodes/ml_code_validator_agent.py` — add `check_inherited_components` to the existing 7-check flow (becoming 8 checks).
- `nodes/result_interpretation_agent.py` — implement open-vocabulary aggregation: walk all records, extract candidates, apply the structural promotion rule, emit `vocab_changes` events in the output.
- `agent/schemas/interpretation.py` — add `current_canonical_vocab`, `current_candidates`, `vocab_changes` to `InterpretationOutput`.
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — pass the runtime vocab union into `ProposalInput`.
- `tests/unit/agent/code_validator_agent/test_inheritance_check.py` (new) — validator unit tests with positive/negative cases.
- `tests/unit/agent/result_interpretation_agent/test_vocab_promotion.py` (new) — promotion rule unit tests.

**Sub-tasks**:
- ☐ C.1 **Draft the seed `primitive_vocab.json` for human review.** Claude proposes ~10–15 canonical entries drawn from the existing built-in models (`punet`, `wavenet`, `fcnet`, `transformer`, `rnn`, `gated_fno`) — reading each model's `description.md` and extracting the architectural primitives it relies on. The draft is then submitted to the human for review and editing BEFORE any of the rest of Phase C lands. The seed sets the canonical quality bar and is the most consequential single artifact in the whole vocabulary mechanism, so the human gets the final word. Each entry needs `name`, `description`, `pattern` (regex or AST hint).
- ☐ C.2 Implement `check_inherited_components(plugin_source, claimed_components, runtime_vocab)` in the validator. Returns the list of unsubstantiated claims; empty list = pass.
- ☐ C.3 Wire the new check into `ml_code_validator_agent`'s existing check sequence as check #8.
- ☐ C.4 Implement the runtime vocab aggregator in the interpretation agent: walks all records, collects all `inherited_components` entries, deduplicates against seed canonical entries by name and alias.
- ☐ C.5 Implement the structural promotion rule (≥3 distinct runs ∧ ≥1 above SOTA ∧ semantic dedup ∧ pattern present). Promotion produces a `vocab_changes` event in the output but does NOT mutate `primitive_vocab.json`.
- ☐ C.6 Implement the semantic dedup step: a small reflector-model LLM call that compares a candidate's description against existing canonical entries and returns "novel" / "synonym of X" / "ambiguous". Fall back to "ambiguous → keep as candidate" on failure.
- ☐ C.7 Add `current_canonical_vocab`, `current_candidates`, `vocab_changes` to `InterpretationOutput`.
- ☐ C.8 Update the propose protocol to pass these into `ProposalInput`.
- ☐ C.9 Update the proposal agent's reasoning prompt to render the runtime vocab as a labeled list (canonical + candidate tiers).
- ☐ C.10 Validator unit tests: claim valid component → pass; claim component not in source → fail with clear message; unknown vocab entry → soft skip.
- ☐ C.11 Promotion rule unit tests: candidate with 2 runs → not promoted; with 3 runs but no above-SOTA → not promoted; with 3 runs + above-SOTA + dedup-novel → promoted; with 3 runs + dedup-synonym → merged as alias.
- ☐ C.12 Tier-1 integration test: a synthetic chain of 4 records with one repeated candidate → interpretation agent emits a promotion event for it.

**Verify**:
- `uv run pytest tests/unit/agent/code_validator_agent tests/unit/agent/result_interpretation_agent -q` — passes.
- Manual: hand-curate the seed file and grep for at least one canonical entry per built-in model (`punet`, `wavenet`, `fcnet`, `gated_fno`).
- Manual: examine an interpretation output JSON after a real chain run and confirm `vocab_changes` is present (may be empty initially).

---

### Phase D — `ResearchDirective` guided mode

**Goal**: when a human specifies "deep-dive on WaveNet", the agent structurally cannot drift into unrelated architectures.

**Depends on**: Phase B (guided mode forcibly sets `DiscoveryMemo.sota_model_type`); Phase C (the validator gains two more checks that build on `check_inherited_components`).

**PR size**: medium.

**Files**:
- `agent/schemas/proposal.py` — add `ResearchDirective` schema, attach to `ProposalInput`.
- `nodes/ml_model_proposal_agent.py` — branch on `directive.mode` in the reasoning sub-call. In guided mode, force `DiscoveryMemo.sota_model_type = directive.base_model` and block free choice.
- `agent/prompts.py` — add the `[GUIDED MODE DIRECTIVE]` block conditionally to the proposal system prompts.
- `nodes/ml_code_validator_agent.py` — add `check_base_model_inheritance` and `check_forbidden_components` (active only in guided mode).
- `agent/schemas/primitive_vocab.py` — add `FORBIDDEN_PATTERNS` map (e.g. `attention` → `nn\.MultiheadAttention|self_attention`).
- `tests/unit/agent/proposal_agent/test_guided_mode.py` (new).
- `tests/unit/agent/code_validator_agent/test_guided_validators.py` (new).

**Sub-tasks**:
- ☐ D.1 Define `ResearchDirective` schema with `mode`, `base_model`, `target_components`, `forbidden_components`, `rationale`. Validator: `mode == "guided"` requires `base_model`.
- ☐ D.2 Attach `research_directive: ResearchDirective` to `ProposalInput`, default = autonomous.
- ☐ D.3 In `ml_model_proposal_agent`, when in guided mode, override the `sota_model_type` field on the memo BEFORE the LLM call (the LLM is told its anchor, not asked to pick one).
- ☐ D.4 Add the `[GUIDED MODE DIRECTIVE]` block to the proposal system prompt template, interpolating `base_model`, `target_components`, `forbidden_components`, `rationale`.
- ☐ D.5 Implement `check_base_model_inheritance`: at least one entry in `inherited_components` must have `from_model_type == directive.base_model`.
- ☐ D.6 Implement `check_forbidden_components`: define `FORBIDDEN_PATTERNS = {"attention": r"nn\.MultiheadAttention|self_attention", ...}`. Match against the plugin source. Any hit → fail.
- ☐ D.7 Wire both new checks into the validator, gated on `directive.mode == "guided"`.
- ☐ D.8 Unit tests: autonomous mode → none of the new checks fire; guided mode with valid proposal → both checks pass; guided mode with proposal omitting base inheritance → fails check D.5; guided mode with proposal containing a forbidden component → fails check D.6.
- ☐ D.9 Tier-1 integration test: guided run with `base_model="wavenet"` and `forbidden_components=["attention"]`, real LLM → proposal stays on wavenet variants; intentionally adversarial prompt that asks for attention → validator rejects.

**Verify**:
- `uv run pytest tests/unit/agent/proposal_agent tests/unit/agent/code_validator_agent -q`.
- Manual: run a guided-mode tuner round and confirm the agent does not drift.

---

### Phase E — Falsifiable prediction retrospective + scientific accuracy metric

**Goal**: every prediction made in `DiscoveryMemo.falsifiable_prediction` gets checked against actual results; the agent's hit rate becomes a measurable, monitorable quantity.

**Depends on**: Phase A (regime_scores), Phase B (FalsifiablePrediction lives in DiscoveryMemo).

**PR size**: small.

**Files**:
- `agent/schemas/hyperparam_tuning.py` — add `prediction_outcome: Optional[Literal["confirmed", "refuted", "partial"]]` to `ExperimentRecord`.
- `nodes/ml_hyperparameter_tune_agent.py` — in the reflector path, look up the previous round's `DiscoveryMemo.falsifiable_prediction` (if any), compare to the current round's `regime_scores`, label the outcome, write into the record.
- `nodes/result_interpretation_agent.py` — aggregate the hit rate across all records into `InterpretationOutput.scientific_accuracy: Dict[str, float]` (e.g. `{"confirmed": 0.38, "partial": 0.22, "refuted": 0.40}`).
- `tests/unit/agent/tune_ml_hyperparam_agent/test_prediction_retrospective.py` (new).

**Sub-tasks**:
- ☐ E.1 Add `prediction_outcome` to `ExperimentRecord`.
- ☐ E.2 Implement `evaluate_prediction(prediction: FalsifiablePrediction, actual: Dict[str, float]) -> Literal[...]`. Logic: confirmed if actual ≥ predicted; refuted if actual ≤ refutation_threshold; partial otherwise.
- ☐ E.3 Wire the evaluator into the reflector path. If no prior prediction exists (e.g. round 1, or memo missing), set outcome to `None`.
- ☐ E.4 Aggregate hit-rate stats in the interpretation agent.
- ☐ E.5 Unit tests for `evaluate_prediction` covering all branches.
- ☐ E.6 Manual smoke test: run a 3-round trial, confirm rounds 2 and 3 have `prediction_outcome` populated.

**Verify**:
- `uv run pytest tests/unit/agent/tune_ml_hyperparam_agent/test_prediction_retrospective.py -q`.
- Manual: inspect a 3-round summary record and confirm the field is populated for rounds 2+.

---

### Cross-phase verification gates

After each phase ships and is committed:

1. **Full unit suite green**: `uv run pytest tests/unit/ -q` — all 700+ tests still pass.
2. **Singleton invariant intact**: `uv run pytest tests/unit/agent/test_llm_bridge_singleton.py -q` — no rogue `OpenAI()` constructors.
3. **Tier-1 integration smoke**: at least one real-LLM Tier-1 test passes for the affected node.
4. **Backward compatibility**: at least one tuner run with no new fields populated (legacy path) completes successfully.
5. **No invariant violation**: no new sidecar markdown files, no new shared mutable state files, no inter-node communication that bypasses protocols.

After **all five phases** ship, run the Tier-3 chain test as a final verification:
```bash
uv run pytest -m real_run -v -s \
    tests/integration/workflows/test_full_exploration_loop.py::TestFullExplorationLoop::test_chained_iterations
```
This exercises the full proposal → implement → validate → tune loop with the new reasoning machinery and citation tracking end-to-end.

---

# Appendix: Original V1 proposal

The V1 proposal (preserved for context — superseded by V2 above) is below. V2 keeps V1's scientific ambition, drops the premature abstractions, and replaces the sidecar journal with a schema-and-protocols approach.

> ## 1. Vision: Dual-Mode Research Strategy
> The architecture must support two distinct operational modes without changing the core logic:
> * **Autonomous Discovery**: The agent explores the architectural space freely, generating novel hypotheses from data patterns.
> * **Guided Deep-Dive (Mentor-Guided)**: The agent follows high-level human intuition (e.g., "Deep-dive into WaveNet's gating mechanism") to perform systematic, narrow-field optimization and ablation.
>
> ## 2. Structural Evolution: The "Research Strategy" Layer
>
> ### A. Modular "Inquiry Context" (Pre-requisite for Literature Agent)
> Currently, the `proposal_agent` only sees its own history. We need to modularize the **Knowledge Input** so that in the future, a **Literature Agent** or a **Human Expert** can plug in "External Priors."
> * **Action**: Implement an `InquiryContext` schema that aggregates:
>     1.  **Internal History** (Past experiments in SIDERIUS).
>     2.  **External Priors** (Human Advice or future Literature Agent summaries).
>     3.  **Benchmark SOTA** (Permanent reference to models like WaveNet).
>
> ### B. Meta-Instruction via "Research Directive"
> To solve the "stuck at WaveNet" problem, the system needs a `ResearchDirective` field in the `System Prompt`.
> * **If Autonomous**: The directive is: "Explore diversity and identify new physical symmetries."
> * **If Guided (e.g., "Dead-lock on WaveNet")**: The directive is: "Treat WaveNet as the baseline. Perform systematic modification on its [Dilation/Gating/Residual] components. Do not deviate from the backbone until the mechanism is fully understood."
>
> ## 3. Implementation Plan for Claude Code
>
> ### Task 1: Decouple Reasoning from Implementation
> * **Current State**: `proposal_agent` often jumps to code/config too fast.
> * **New Design**: Split the Proposal Node into **`Scientific_Reasoning_Subnode`** and **`Architectural_Design_Subnode`**.
>     * The Reasoning subnode must output a **"Discovery Memo"** that compares the best model (WaveNet) vs. the proposed idea *before* any code is written.
>
> ### Task 2: Multi-Dimensional Physics Feedback
> * **Action**: Enhance the `ScoringOutput` to include a **`Performance_Profile`**.
>     * Instead of just `score: 0.85`, it should output:
>         ```json
>         {
>           "global_score": 0.85,
>           "regime_scores": {"high_freq": 0.92, "low_freq": 0.71, "high_snr": 0.95, "low_snr": 0.62},
>           "failure_modes": ["Phase distortion in low-frequency ripples"]
>         }
>         ```
>     * This provides the "gradient" for the agent to know *what* to fix in WaveNet.
>
> ### Task 3: The "Comparative Memory" Summarizer
> * **Action**: Instead of dumping raw JSON history, create a `MemorySummarizer` skill.
>     * It should produce a "Leaderboard Analysis" that explicitly tells the Agent: *"You've tried WaveNet with Attention 3 times; each time it failed with OOM. Your best gain came from increasing the dilation factor in Iteration 4."*
>
> ## 4. Future-Proofing for Literature Agent
> * **Design Invariant**: All input to the `proposal_agent` must pass through a **`UnifiedContextAssembler`**.
> * When the Literature Agent is ready, its output (e.g., "Recent papers suggest FNO is better for SQUID data") will simply be another stream into the `UnifiedContextAssembler`, treated with the same priority as `Human Advice`.
>
> ---
>
> ### Discussion Points for Claude Code:
> 1.  **Schema Refactoring**: How to modify `ProposalInput` to accept `InquiryContext` without breaking existing workflows?
> 2.  **System Prompt Caching**: How to structure the SOTA model descriptions (WaveNet) into the System Prompt to leverage long-context caching?
> 3.  **Stateful Memory**: Should we introduce a `Research_Journal.md` file that the agents update each round to maintain a high-level narrative of the "Search for Truth"?
