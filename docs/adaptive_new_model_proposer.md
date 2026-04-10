# Design Proposal V2: Adaptive Scientific Discovery Framework for SIDERIUS

**Status**: Phase B Groups 1+2 implemented (schemas, tests, vocab seed). Group 3 (prompt templates) next. Supersedes the V1 proposal at the bottom of this file.

## 0. The actual problem and the key design idea

SIDERIUS is currently stuck at a **scientific attribution failure**, not an engineering bottleneck:

- The agent can train and score models all day, but it cannot articulate **why** WaveNet is winning.
- Without that articulation, every new proposal is a guess. The exploration loop becomes a random walk over architecture space, with no compounding insight.
- Beating WaveNet therefore requires three capabilities the system does not yet have:
  1. **Comparative causal reasoning**: not "I propose X" but "X should beat WaveNet because the WaveNet mechanism Y is bottlenecked by Z, and X relaxes Z while preserving Y."
  2. **Component lineage**: knowing which architectural primitives (dilation, gating, residuals, …) come from which past winners, so successful primitives can be inherited rather than re-invented.
  3. **Scoped exploration**: when the human says "deep-dive on WaveNet", the agent must actually stay on WaveNet — not drift into transformers because that's where the LLM's prior wants to go.

### The key design idea: structured vocabulary as a constraint bridge

> **Natural language is diverse and messy. An LLM reasoning in free text will invent 50 different ways to say "dilated convolution" and lose the ability to track what it has tried. The V2 design solves this by introducing a structured vocabulary — currently features (concrete building blocks) and capabilities (measurable architectural properties) — as a constraint bridge that harnesses the LLM's reasoning process.**
>
> The vocabulary is NOT a database or a knowledge graph. It is a **shared language** that all pipeline stages use to refer to the same things consistently. The seed provides the terms (features like `dilated_causal_conv`, capabilities like `receptive_field`), but the **connections between them are discovered through experimentation** — the agent hypothesizes "dilated_causal_conv enables receptive_field", tests it, and confirms or refutes it. Without the vocabulary, the same insight would be expressed in different words at each stage, and the connection would be lost.
>
> The vocabulary is composable: adding a new type of constraint bridge (e.g. "failure_pattern", "physical_constraint") means adding entries with a new `kind` value — no code changes to the pipeline runner or the aggregation engine. The two-tier structure (canonical seed + agent-discovered candidates + structural promotion) keeps the vocabulary both stable enough for tracking and open enough for discovery.
>
> **This is the single most important design decision in V2.** Every other feature — the three-stage pipeline, the configurable stages, the expert context items, the falsifiable predictions — builds on the vocabulary as its foundation. If the vocabulary works, the LLM's reasoning compounds across iterations. If it doesn't, the system stays stuck in the random walk.
to 
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

### 2A. Three-stage configurable reasoning pipeline

**Goal**: The proposal agent must (1) systematically compare all previously tested models, (2) form a causal hypothesis about what to try next, and (3) produce a concrete architecture tethered to that reasoning. These are three distinct cognitive tasks, each implemented as one LLM call in a configurable pipeline.

**Implementation**: same node, three `LLMBridge` calls in a configurable pipeline, replacing the existing two-call pattern (`bridge.generate_text()` for free-text reasoning + `bridge.generate()` for structured JSON commit). No new node, no new schema container. The pipeline is a list of stages — adding, removing, or reordering stages is a configuration change, not a code change.

> **Codebase context (verified against PRs 22-24)**: the proposal agent (`nodes/ml_model_proposal_agent.py`) ALREADY makes two LLM calls — a free-text reasoning call and a structured commit call. Phase B replaces this 2-call pattern with a 3-stage pipeline. The existing Call 1 (free-text reasoning) roughly maps to Stages 1+2 (comparison + causal reasoning). The existing Call 2 (structured commit) maps to Stage 3 (proposing). The constructor currently takes `(provider, model_id)` and constructs `LLMBridge` internally; Phase B adds DI while preserving this interface for backward compat. The workflow constructs the agent via `MLModelProposalAgent(**llm_config.get("propose"))`.

> **Decision (locked)**: the three-stage approach is committed. Each stage costs one LLM call (~3× the proposal LLM cost; small fraction of total chain quota since most usage is in tuning rounds). The scientific-attribution benefit outweighs the cost. Individual stages MAY be routed to cheaper models (`gemini-2.5-flash`) if structured output quality holds; this is a per-stage implementation choice, not a design constraint.

#### The configurable pipeline

The reasoning pipeline is **configured at the workflow level** (not per-run), so a chain uses the same pipeline across all its iterations. The default is the 3-stage pipeline; customization is adding/removing/reordering entries in a list.

```python
class ReasoningStage(BaseModel):
    """One stage in the reasoning pipeline. Each stage is one LLM call
    that receives all prior stages' outputs as context."""
    name: str                    # e.g. "comparison", "causal_reasoning"
    system_prompt_key: str       # which prompt template to use
    output_mode: Literal["json", "text"] = "json"  # json → bridge.generate(), text → bridge.generate_text()
    enabled: bool = True         # disable per-workflow without removing

class ModelSelectionStrategy(BaseModel):
    """Pre-filter for which past models the comparison stage analyzes.
    Controls token cost (how many models) while expert_context controls
    focus (what to emphasize about those models)."""
    method: str = Field(
        default="top_n",
        description="Pre-filter strategy. Options: "
                    "'top_n' (N highest-scoring), "
                    "'all' (everything — expensive), "
                    "'feature_match' (models with a specific component), "
                    "'human_specified' (exact list from human advice)."
    )
    params: Dict[str, Any] = Field(
        default_factory=lambda: {"n": 10},
        description="Strategy-specific parameters. "
                    "top_n: {'n': 10}. "
                    "feature_match: {'feature': 'dilated_causal_conv'}. "
                    "human_specified: {'models': ['wavenet', 'gated_fno']}."
    )

class ReasoningPipelineConfig(BaseModel):
    """Configurable reasoning pipeline for the proposal agent.
    Lives at the workflow level (WorkflowLLMConfig or equivalent),
    not per-run, so a chain uses the same pipeline across all iterations."""
    stages: List[ReasoningStage] = Field(
        default_factory=lambda: [
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
        description="Ordered list of reasoning stages. Each stage is one LLM call. "
                    "The 'proposing' stage (architecture design) always runs last and "
                    "is not listed here — it's the fixed output stage. These stages "
                    "produce the DiscoveryMemo; the proposing stage consumes it."
    )
    model_selection: ModelSelectionStrategy = Field(
        default_factory=ModelSelectionStrategy,
        description="How to pre-filter past models before the comparison stage."
    )
    exploration_mode: Literal["auto", "explore", "exploit"] = Field(
        default="auto",
        description="Controls the reasoning tone and prompt templates. "
                    "'auto': system decides based on evidence depth (number of records, "
                    "distinct model types tested, falsifiable-prediction hit rate). "
                    "'explore': forced exploration — first few rounds or human override. "
                    "Prompts emphasize diagnostic experimentation and honest uncertainty. "
                    "'exploit': forced exploitation — later rounds or human override. "
                    "Prompts emphasize building on confirmed patterns and beating SOTA."
    )
```

**Customization examples**:
- **Skip comparison, just reason**: set `stages[0].enabled = False`
- **Add a physics check**: append `ReasoningStage(name="physics_check", system_prompt_key="PHYSICS_REVIEW")`
- **Only compare WaveNet variants**: set `model_selection = {"method": "feature_match", "params": {"feature": "dilated_causal_conv"}}`
- **Human says "focus on top 3"**: set `model_selection = {"method": "top_n", "params": {"n": 3}}`
- **Human says "only look at these two"**: set `model_selection = {"method": "human_specified", "params": {"models": ["wavenet", "gated_fno"]}}`

#### Design decisions (verified against codebase after PRs 22-24)

> **Decision 1 — Where does `ReasoningPipelineConfig` live?**
>
> Currently `WorkflowLLMConfig.propose` is a single `NodeLLMConfig` (one provider + one model_id). For the 3-stage pipeline, each stage might want its own model (comparison on flash, reasoning on pro). Following the precedent set by PR #22's `TunerLLMConfig` (which nests `planner` and `reflector` as separate `NodeLLMConfig` slots), the proposal agent gets a **`ProposalLLMConfig`** nested in `WorkflowLLMConfig`:
>
> ```python
> class ProposalLLMConfig(BaseModel):
>     """Per-stage LLM routing for the proposal agent's reasoning pipeline.
>     Mirrors TunerLLMConfig's planner/reflector pattern from PR #22."""
>     comparison: NodeLLMConfig = Field(default_factory=lambda: NodeLLMConfig(
>         provider="gemini", model_id="gemini-2.5-flash"))  # cheap, data-heavy
>     reasoning: NodeLLMConfig = Field(default_factory=lambda: NodeLLMConfig(
>         provider="gemini", model_id="gemini-3.1-pro-preview"))  # needs strong reasoning
>     proposing: NodeLLMConfig = Field(default_factory=lambda: NodeLLMConfig(
>         provider="gemini", model_id="gemini-3.1-pro-preview"))  # needs precise JSON
>     pipeline: ReasoningPipelineConfig = Field(default_factory=ReasoningPipelineConfig)
> ```
>
> `WorkflowLLMConfig.propose` changes from `Optional[NodeLLMConfig]` to `Optional[ProposalLLMConfig]`. The `get()` method on `WorkflowLLMConfig` flattens this for backward compat (same pattern as the tuner's planner/reflector flattening).

> **Decision 2 — How does `expert_context` reach the proposal agent?**
>
> Currently, `human_advice` is NOT carried by the protocol (`local_full_context`). It's injected by the workflow code separately. Per CLAUDE.md's inter-node communication principle ("schemas + protocols only"), `expert_context` should flow **through the protocol**, not be injected by the workflow as a side channel.
>
> The `local_full_context` protocol function gains an `expert_context` parameter:
> ```python
> def local_full_context(
>     output: InterpretationOutput,
>     storage: StorageConfig,
>     expert_context: List[ExpertContextItem] | None = None,
>     human_advice: ExpertAdviceInput | None = None,  # legacy, wrapped into expert_context
> ) -> ProposalInput:
> ```
> The workflow passes `human_advice` (from CLI args or chain config) to the protocol, which wraps it into an `ExpertContextItem` with `source="human", kind="human"` and includes it in `expert_context`. This is the single clean path — no more workflow-level injection.
>
> Note: `ProposalInput.human_advice` is currently typed `Optional[ExpertAdviceInput]` (not `str`). The `ExpertContextItem` wrapping must handle both plain strings and structured `ExpertAdvice` objects.

> **Decision 3 — Pipeline stages support both JSON and plain-text output modes.**
>
> The existing proposal agent uses `bridge.generate_text()` (plain text, no JSON constraint) for reasoning and `bridge.generate()` (JSON mode) for the structured commit. The pipeline runner must support both modes per stage. Each `ReasoningStage` carries an `output_mode`:
> ```python
> class ReasoningStage(BaseModel):
>     name: str
>     system_prompt_key: str
>     output_mode: Literal["json", "text"] = "json"  # json → bridge.generate(), text → bridge.generate_text()
>     enabled: bool = True
> ```
> Stages 1 (comparison) and 2 (reasoning) default to JSON (structured output that feeds into the DiscoveryMemo). But a future "free reasoning" stage could use text mode if needed.

#### Execution flow

```
ProposalInput
  ├── reasoning_pipeline: ReasoningPipelineConfig (workflow-level)
  ├── expert_context: List[ExpertContextItem]
  └── all_records (seeds + previously proposed models)
          │
          ▼
  [Pre-filter] ← model_selection strategy (deterministic Python)
          │ candidate_models (e.g. top 10 by score)
          ▼
  [Stage 1: Comparison] ← COMPARATIVE_ANALYSIS prompt + candidates + expert_context
          │ List[ModelComparison] — per-model strengths/weaknesses/lessons
          ▼
  [Stage 2: Reasoning] ← CAUSAL_REASONING prompt + comparisons + expert_context
          │ DiscoveryMemo core fields (hypothesis, prediction, failure modes)
          ▼
  [Stage 3: Proposing] ← ARCHITECTURE_DESIGN prompt + full DiscoveryMemo
          │ ProposalOutput (model name, config, code)
          ▼
  Validator → Implementor → Tuner
```

Each `[Stage N]` is one `bridge.generate()` call. **Each stage receives ALL prior stages' outputs as context** — so Stage 2 sees Stage 1's comparisons, and Stage 3 sees both. The pipeline runner is a simple loop:

```python
def produce_discovery_memo(self, context: dict, pipeline: ReasoningPipelineConfig) -> DiscoveryMemo:
    """Run the reasoning pipeline. Each enabled stage enriches the context."""
    accumulated = dict(context)
    for stage in pipeline.stages:
        if not stage.enabled:
            continue
        system_prompt = PROMPTS[stage.system_prompt_key]
        result = self.bridge.generate(system_prompt, json.dumps(accumulated))
        accumulated[stage.name] = result  # next stage sees this stage's output
    return DiscoveryMemo.model_validate(accumulated)
```

Adding a stage = appending to the list. The surrounding code never changes.

#### Smart, adaptive model selection

The model selection has two layers:

**Layer 1 — Pre-filter (deterministic Python, before the LLM call)**: reduces ALL past models to a candidate set based on `ModelSelectionStrategy`. Controls **token cost** — passing 50 full model records to the LLM is expensive; passing 10 is reasonable.

**Layer 2 — Focus (inside the LLM call, driven by expert_context)**: the expert advice tells the LLM what to emphasize **within** the candidate set. The same 10 models can be analyzed with different emphasis depending on the advice:
- Human says "focus on low-frequency performance" → comparison emphasizes `file_vector[0:5]` per model
- Human says "compare gating mechanisms" → comparison emphasizes models that use gating
- No advice → default balanced comparison

The pre-filter is the **budget control** (how many). The expert advice is the **focus control** (what to emphasize). Both are configurable, neither is hardcoded.

#### Dynamic vocabulary growth — the comparison stage as a contributor

The vocabulary doesn't just flow INTO the pipeline — the pipeline **grows** it. Specifically, the comparison stage has a dual role:

1. **Consumer**: it uses the current vocabulary (canonical + candidates) to structure its analysis — "Model A uses **dilated_causal_conv** (feature). I hypothesize this enables **receptive_field** (capability) based on its strong high-frequency scores."
2. **Contributor**: it identifies patterns in the experiment records that suggest a NEW feature or capability not yet in the vocabulary, AND proposes candidate links between features and capabilities as testable hypotheses (via `ProposedVocabLink`).

The candidate enters the vocabulary pool through the comparison's output (stored in the DiscoveryMemo, persisted in the experiment record, aggregated by the interpretation agent). Future rounds can reference it by name. If it appears in ≥3 runs and meets the promotion criteria, it becomes canonical.

This means:
- **Round 1**: vocabulary = canonical seed only (features + capabilities, no links). Comparison can reference seed entries and propose initial link hypotheses (`ProposedVocabLink`) based on the seed models' descriptions.
- **Round N**: vocabulary = canonical seed + confirmed links from rounds 1 to N-1 + all candidates. Comparison has a richer language AND confirmed feature→capability links to build on.
- **The vocabulary compounds over iterations** in two dimensions: new entries (candidates) and new links (confirmed feature→capability connections). Each round adds both language and empirical relationships for the next round to build on.

#### Exploration vs exploitation — the cold-start problem

**The problem**: in round 1, the system has seed model baselines but zero agent-proposed models, zero confirmed/refuted hypotheses, zero empirical evidence about what features/capabilities actually matter for TIDMAD performance. Forcing the full reasoning pipeline would produce **confidently wrong** causal claims — the LLM would state hypotheses as if evidence-based when they're actually just prior beliefs. This is worse than no reasoning, because it creates false rigor.

**The solution**: the pipeline's `exploration_mode` controls the reasoning tone and prompt templates. The system explicitly distinguishes between two phases:

| Mode | When (in `auto`) | Goal | Pipeline behavior |
|---|---|---|---|
| **Exploration** | Few records (<5 agent-proposed models), no confirmed patterns | Test hypotheses, gather evidence | Comparison is honest about uncertainty ("we have only seed baselines, no experimental evidence yet"). Reasoning proposes **diagnostic experiments** — "I want to test WHETHER receptive_field matters, so I'll compare a wide vs narrow model." Predictions are framed as conditional: "IF receptive_field matters, THEN file_vector[0:5] should improve by >0.1." |
| **Exploitation** | Many records (≥5 agent-proposed), confirmed patterns exist | Build on what works, beat SOTA | Comparison leverages the full vocabulary + evidence base. Reasoning builds on confirmed patterns: "receptive_field was confirmed to matter in rounds 2, 4, and 6 (hit rate 75%). I'm now combining it with frequency_band_gating which was confirmed in round 5." Predictions reference prior evidence. |

**In `auto` mode**, the pipeline runner checks before each iteration:
```python
def _resolve_exploration_mode(records, pipeline) -> str:
    if pipeline.exploration_mode != "auto":
        return pipeline.exploration_mode
    agent_proposed = [r for r in records if r.get("source") != "seed"]
    if len(agent_proposed) < 5:
        return "explore"
    # Could also check hit_rate, vocabulary growth rate, etc.
    return "exploit"
```

**The prompts change based on the mode**:

- **Exploration system prompt addition**: "You are in EXPLORATION mode. You have limited experimental evidence from this project. Your goal is NOT to beat the SOTA — it's to TEST a specific hypothesis. Propose a DIAGNOSTIC experiment that will confirm or refute one specific claim about a feature→capability link. Frame your prediction as 'IF [feature] enables [capability], THEN [metric] should change by [amount].' Be honest about what you don't know."

- **Exploitation system prompt addition**: "You are in EXPLOITATION mode. You have N confirmed patterns from previous rounds (hit rate: X%). Build on what works. Combine confirmed feature→capability links. Your prediction should be based on empirical evidence from this project, not generic ML knowledge. Reference specific prior rounds that confirmed the patterns you're building on."

The human can override: `exploration_mode: "explore"` forces exploration even at round 20 (useful for testing a new direction); `exploration_mode: "exploit"` forces exploitation even at round 1 (useful when the human has strong prior knowledge via ExpertContextItem).

#### Stage 1: Comparison — "What do we know?"

Backward-looking systematic review of the pre-filtered candidate models. One `ModelComparison` per model.

```python
class ModelComparison(BaseModel):
    """Structured analysis of one previously tested model."""
    model_type: str
    source: str = Field(
        description="'seed' (from the initial seed records) or "
                    "'proposed_iter_N' (proposed by the agent in iteration N)."
    )
    best_score: float
    key_mechanism: str = Field(
        max_length=300,
        description="One sentence: what makes this model tick (or not). "
                    "Must reference a specific architectural feature, not vague language."
    )
    strengths: List[str] = Field(
        description="What this model does well, tied to file_vector or score evidence."
    )
    weaknesses: List[str] = Field(
        description="Where this model fails, tied to file_vector or score evidence."
    )
    lesson_for_next_proposal: str = Field(
        max_length=300,
        description="What to inherit or avoid from this model in the next proposal."
    )
```

The comparison stage's output is a `List[ModelComparison]` that feeds into Stage 2 as context.

#### Stage 2: Reasoning — "What should we try?"

Forward-looking causal hypothesis, building on the comparisons from Stage 1. This is where the DiscoveryMemo's core scientific fields are produced.

```python
class DiscoveryMemo(BaseModel):
    """The structured output of the reasoning pipeline (stages 1+2).
    The 'Final Verdict' — forces the LLM to articulate WHY before WHAT.
    Stage 3 (proposing) is structurally tethered to this memo."""

    # --- Comparative analysis (Stage 1 output) ---
    comparative_analysis: List[ModelComparison] = Field(
        description="Systematic comparison of selected past models. "
                    "Produced by the comparison stage, consumed by the reasoning stage."
    )
    sota_model_type: str = Field(
        description="The current best-scoring model, identified from the comparisons."
    )
    sota_score: float
    sota_mechanism: str = Field(
        max_length=600,
        description="WHY does the SOTA work? Must reference physical/architectural "
                    "mechanism, not vague language."
    )

    # --- Causal reasoning (Stage 2 output) ---
    proposed_change: str = Field(
        max_length=400,
        description="What the new proposal changes RELATIVE TO the SOTA. "
                    "Must be expressible as 'replace X with Y' or 'add Z'. "
                    "Forbidden: 'completely new architecture'."
    )
    causal_hypothesis: str = Field(
        max_length=600,
        description="WHY the proposed change should improve the score. "
                    "Must reference (a) the SOTA mechanism it preserves, "
                    "(b) the SOTA bottleneck it relaxes, (c) the new mechanism. "
                    "Vague language forbidden."
    )

    # --- Falsifiable prediction ---
    falsifiable_prediction: FalsifiablePrediction = Field(
        description="Concrete numerical prediction. The reflector checks it."
    )

    # --- Devil's advocate ---
    predicted_failure_modes: List[str] = Field(
        min_length=1, max_length=3,
        description="At least one way the proposal could fail."
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
                    "shaped this memo. Empty = driven purely by records."
    )


class FalsifiablePrediction(BaseModel):
    metric: str = Field(
        description="What to measure. Free-text, guided by expert advice. "
                    "Examples: 'mean(file_vector[0:5])', 'denoising_score', "
                    "'file_vector[17]'."
    )
    current_value: float
    predicted_value: float
    threshold_for_refutation: float
    rationale: str
```

#### Stage 3: Proposing — "How exactly do we build it?"

The proposing stage receives the complete `DiscoveryMemo` and produces the `ProposalOutput` (model name, model_config, train_config, loss_config, code). Its system prompt forces it to:

- Reference the memo's `proposed_change` verbatim.
- Use the memo's `inherited_components` as a checklist — every listed component must appear in the proposed `model_config`.
- Reference specific `ModelComparison` entries from Stage 1 when justifying architectural choices ("I'm using dilated convolutions because wavenet's comparison showed this was its key strength").
- Justify every architectural choice that is NOT in the memo with a "deviation note". A high deviation count is a red flag the validator surfaces.

The result: the architecture is **structurally tethered to the reasoning**. The LLM cannot quietly drift from "I'm modifying WaveNet's gating" in the memo to "I'm writing a transformer" in the config — the validator catches the mismatch.

#### Why this is "scientific peer review" and not just "longer prompts"

Four structural teeth:

1. **Systematic comparison**: every previously tested model is analyzed before any new proposal is made. The LLM can't ignore past failures or silently re-propose something that already failed.
2. **Falsifiable prediction**: every proposal commits to a numerical outcome. The reflector checks it. Over time the hit rate becomes measurable.
3. **Devil's advocate clause**: at least one failure mode must be named. Empty or trivial lists are rejected.
4. **Architectural tethering**: Stage 3 cannot diverge from Stages 1+2 without deviation notes. Drift is visible.

None of these requires a new node, a new agent, or a sidecar file. They are all schema constraints + prompt constraints + a configurable list of LLM calls.

#### Centrifugal forces — preventing collapse into conservative local optima

The four structural teeth above are **centripetal** — they pull the agent toward rigor, consistency, and evidence-based reasoning. But unchecked, they create five failure modes where the agent games the system by being *too* conservative. The following architectural mitigations counterbalance each one.

**1. Innovation Stagnation (Centripetal Drift)**

*Risk*: The vocabulary system creates a safe harbor — reusing canonical terms guarantees validation passes, so the LLM never proposes new features or capabilities.

*Mitigation (Architecture + Advice)*:
- The validator treats canonical and candidate vocab entries **equally**. Candidates are never penalized; canonicals are never rewarded. Both are valid for `inherited_components`.
- The interpretation agent computes a **vocabulary diversity metric**: `n_candidate_entries_proposed / n_total_entries_referenced` across recent rounds. If this drops below a threshold (e.g., 0.1), the exploration mode resolver signals "vocabulary stagnation" and switches to `explore` mode.
- The comparison stage prompt in explore mode explicitly asks: "Are there patterns in these models that suggest a NEW feature or capability not yet in the vocabulary?"
- *Phase*: B (exploration resolver) + C (diversity metric in interpretation).

**2. Predictive Risk Aversion (Metric Gaming)**

*Risk*: The `FalsifiablePrediction` grading (confirmed/refuted) incentivizes trivial predictions (e.g., "score improves by 0.001") to maximize hit rate.

*Mitigation (Architecture)*:
- `FalsifiablePrediction` gains a computed `boldness` property: `abs(predicted - current) / max(abs(current), 1e-6)`. The reflector tracks both `prediction_outcome` and `information_gain = boldness × (1 if confirmed else 0)`.
- The interpretation agent reports **average information gain** alongside hit rate. Bold confirmed predictions score higher than timid ones.
- Schema validator: `minimum_boldness` threshold (default 0.05). Predictions below this are rejected as "too conservative to be informative."
- *Phase*: B (boldness validator on schema) + E (information gain in reflector).

**3. Error Propagation in Serial Reasoning**

*Risk*: The 3-stage pipeline tethers Stage 3 to Stage 1's output. If Stage 1 hallucinates a SOTA mechanism, Stage 3 implements the hallucination.

*Mitigation (Mostly Advice, small Architecture)*:
- The experiment itself is the primary error-correction: hallucinated mechanisms lead to refuted `FalsifiablePrediction`s, which the next round's comparison stage can see.
- `ProposalOutput` gains `memo_consistency_notes: List[str] = []`. The proposing stage (Stage 3) lists inconsistencies it noticed between the DiscoveryMemo and what's physically implementable. The validator surfaces these as warnings.
- This is a **flag**, not a veto. A cross-verification loop would add LLM quota cost and create recursion problems (who vetos the veto?).
- *Phase*: B (add field to ProposalOutput).

**4. Promotion Spuriousness**

*Risk*: A vocabulary entry is promoted because it co-occurred with high scores, not because it caused them. The promotion rule (≥3 runs + beating SOTA) is correlational.

*Mitigation (Architecture)*:
- The interpretation agent computes a **component delta** for each entry: `avg_score_with - avg_score_without`. This compares scores of runs that used the component vs runs that didn't.
- Updated promotion rule adds two requirements: `delta > 0` (positive contribution when present vs absent) AND low confounding (≤2 other components changed between with/without runs).
- The comparison stage prompt in exploit mode asks for **ablation suggestions**: "Which component should we remove from the SOTA to test whether it's actually contributing?" Ablation evidence is stronger than correlational evidence.
- *Phase*: C (component delta in interpretation, ablation-aware promotion) + B (ablation prompt in comparison stage).

**5. Citation Pollution (Over-citation)**

*Risk*: The LLM cites every `ExpertContextItem` to appear rigorous, diluting the signal of which upstream findings actually mattered.

*Mitigation (Architecture + Advice)*:
- `DiscoveryMemo.citation_sources` gains `max_length=5` — hard cap on citations per memo.
- Validator check: each `cite_id` in `citation_sources` must appear verbatim in either `causal_hypothesis` or `proposed_change` text. If you cite it, you must reference it in your reasoning.
- Prompt: "Cite ONLY items that materially changed your hypothesis. If removing a citation would not change your proposal, do not include it."
- *Phase*: B (validator + prompt).

---

### Composability principle (applies to §2A pipeline + §2B vocabulary + future extensions)

> **The runner is generic; the content is specific.**
>
> Both the reasoning pipeline (§2A) and the vocabulary system (§2B) follow the same architectural pattern: a **generic engine** that doesn't know about any specific domain concept, plus **pluggable content** that fills the engine with specific behavior. This is not runtime configuration (no YAML file) — it's code-level composability. Adding a new vocabulary type or a new pipeline stage means writing a new module and plugging it into an existing interface, NOT modifying existing code.
>
> Concretely:
> - **Pipeline stages** conform to a single interface: `(system_prompt, accumulated_context) → stage_output`. The pipeline runner just loops. It doesn't know the difference between "comparison" and "physics_check" — both are entries in a list. Adding a stage = adding one entry + one prompt template. The runner's code doesn't change.
> - **Vocabulary entries** conform to a single schema: `VocabEntry(name, kind, description, related_to, ...)`. The aggregation/promotion engine doesn't know the difference between a "feature" and a "capability" — both are entries with a `kind` field. Adding a new vocabulary type = adding entries with a new `kind` value. The engine's code doesn't change.
> - **The combination** of vocabularies × stages is composable: any stage's prompt template can reference any vocabulary kind. The comparison stage uses both features and capabilities today; a future "physics_check" stage could use a "physical_constraint" vocabulary kind. No wiring code changes.
>
> This composability is what makes the system extensible without accumulating technical debt. Every new capability is an additive plugin, not a cross-cutting modification.

---

### 2B. Vocabulary system — features, capabilities, and lineage

**Goal**: track the building blocks of model design at two levels of abstraction — **features** (concrete architectural primitives you can point to in code) and **capabilities** (measurable architectural properties that features provide) — and let the agent **discover the connections between them through experimentation**. The seed provides the vocabulary (names + definitions); the agent hypothesizes, tests, and confirms which features produce which capabilities.

**Where the source of truth lives**: in the per-record `DiscoveryMemo.inherited_components`, NOT in `MODEL_REGISTRY`. Reasoning:

- The registry is loaded at import time and is awkward to mutate from agent code.
- Records are already append-only, schema-validated, and the natural unit of "what we tried and what happened".
- The registry as a permanent metadata store would be an inter-node communication channel by another name (you'd be reading state out of `MODEL_REGISTRY` during proposal generation, which the records-via-protocol path already provides cleanly).

**Schema**:

```python
class InheritedComponent(BaseModel):
    """One building block carried over from a past winning run. Can be a
    concrete feature ('dilated_causal_conv') or a capability
    ('receptive_field') — both are tracked in the unified vocabulary."""

    component: str = Field(
        description="Short canonical name from the vocabulary. "
                    "E.g. 'dilated_causal_conv' (feature) or 'receptive_field' (capability). "
                    "Drawn from the unified vocabulary (see VocabEntry below) "
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

**Open vocabulary with structured promotion** (unified `VocabEntry` — replaces the earlier `PRIMITIVE_VOCAB` concept with a broader system that tracks both features and capabilities):

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
class VocabEntry(BaseModel):
    """A single vocabulary entry — either a concrete feature or a capability.
    Both live in the same two-tier vocabulary (canonical + candidate)
    and use the same promotion mechanism. The `kind` field distinguishes them;
    the `related_to` field is populated through experimentation (starts empty).

    Adding a new kind (e.g. 'failure_pattern', 'physical_constraint') requires
    NO code changes — just add entries with the new kind value to the seed file
    or let the agent propose them as candidates. The aggregation engine, the
    promotion rules, and the pipeline stages all treat VocabEntry generically.
    This is the composability principle in action.
    """
    name: str = Field(description="Canonical snake_case name.")
    kind: str = Field(
        description="What type of knowledge this entry represents. "
                    "Current kinds: 'feature' (concrete architectural building block, "
                    "e.g. 'dilated_causal_conv') and 'capability' (measurable architectural "
                    "property, e.g. 'receptive_field'). New kinds can be added without "
                    "code changes — just add entries with the new kind value."
    )
    description: str = Field(max_length=200, description="One-sentence definition.")
    related_to: List[str] = Field(
        default_factory=list,
        description="Names of other VocabEntry items this entry is connected to. "
                    "**Starts empty in the seed.** Populated through experimentation: "
                    "the agent proposes ProposedVocabLink hypotheses, tests them, and "
                    "confirmed links get promoted here by the interpretation agent."
    )
    tier: Literal["canonical", "candidate"] = "candidate"
    pattern: Optional[str] = Field(
        default=None,
        description="AST/regex hint for features — the validator uses it to verify "
                    "that a claimed inheritance actually appears in the code. "
                    "Not applicable to capabilities (set to None)."
    )
    proposed_by_run: Optional[str] = None  # candidates only
    seen_in_runs: List[str] = []           # all runs that have used this entry
    aliases: List[str] = []                # observed spelling variants the aggregator collapsed
```

**Seed file** (`agent/schemas/vocab_seed.json`):

The seed contains features and capabilities with **empty `related_to`**. The connections between features and capabilities are NOT pre-assumed — they are **hypotheses that the agent proposes, tests, and verifies** through the experiment loop. This is a core design principle: the seed provides the vocabulary (what things are called), but the agent discovers the relationships (what causes what).

```json
[
  {"name": "dilated_causal_conv", "kind": "feature", "description": "Causal convolution with exponentially increasing dilation factors", "related_to": [], "pattern": "dilation\\s*="},
  {"name": "gated_activation", "kind": "feature", "description": "Sigmoid-gated element-wise multiplication of two conv branches", "related_to": [], "pattern": "sigmoid.*\\*"},
  {"name": "spectral_conv", "kind": "feature", "description": "Learnable complex-valued weights applied in Fourier domain (RFFT)", "related_to": [], "pattern": "rfft|fft|spectral"},
  {"name": "receptive_field", "kind": "capability", "description": "How far back in time the model can see per layer", "related_to": []},
  {"name": "frequency_resolution", "kind": "capability", "description": "The model's ability to distinguish different frequency bands", "related_to": []},
  {"name": "selective_frequency_processing", "kind": "capability", "description": "Ability to attenuate or amplify specific frequency bands independently", "related_to": []}
]
```

#### Feature → capability link discovery (the hypothesis-test-verify loop)

The `related_to` graph is **not pre-loaded** — it is built through experimentation:

1. **Stage 1 (Comparison)**: the agent reads model descriptions + experiment results and **proposes candidate links** as hypotheses. E.g., "wavenet uses `dilated_causal_conv` and scores well on high-frequency files — I hypothesize that `dilated_causal_conv` → `receptive_field`." These go into `DiscoveryMemo.proposed_vocab_links`.

2. **Stage 2 (Reasoning)**: the agent designs a proposal that **specifically tests** a proposed link. E.g., "if `dilated_causal_conv` truly enables `receptive_field`, then increasing dilation depth should improve low-freq scores." The test is captured in the `FalsifiablePrediction`.

3. **After the experiment**: the reflector evaluates the prediction. If confirmed, the link's status changes to `confirmed`. If refuted, `refuted`.

4. **Aggregation (Phase C)**: the interpretation agent collects all proposed links across rounds. Links that reach `confirmed` status in ≥2 runs get their `related_to` fields populated on the corresponding `VocabEntry` entries in the next round's `runtime_vocab`.

```python
class ProposedVocabLink(BaseModel):
    """A hypothesized connection between a feature and a capability.

    Proposed by the comparison stage, tested via FalsifiablePrediction,
    confirmed or refuted by the reflector. Only confirmed links get
    promoted to VocabEntry.related_to (via the interpretation agent).
    """
    feature: str = Field(
        description="The feature entry name, e.g. 'dilated_causal_conv'."
    )
    capability: str = Field(
        description="The capability entry name, e.g. 'receptive_field'."
    )
    evidence: str = Field(
        max_length=300,
        description="Why the agent thinks this link exists — must reference "
                    "specific model results or architectural analysis."
    )
    status: Literal["proposed", "confirmed", "refuted"] = Field(
        default="proposed",
        description="Lifecycle: proposed → confirmed/refuted after experiment."
    )
```

This schema is added to `DiscoveryMemo.proposed_vocab_links: List[ProposedVocabLink]` and to `ExperimentRecord` (for cross-round aggregation).

The `InheritedComponent.component` field references entries from this vocabulary. The proposal agent's prompt includes the full `runtime_vocab` (both tiers, both kinds, clearly labeled) and instructs: "Use canonical entries verbatim. When proposing a link between a feature and a capability, cite specific experimental evidence — do not guess from generic ML knowledge."

The comparison stage uses the vocabulary to structure its analysis:
> "Model A uses **dilated_causal_conv** (feature, canonical). Its file_vector shows strong scores on files 11-19 but weak on files 0-4. I propose the link `dilated_causal_conv → receptive_field` based on this evidence, but this needs experimental verification."

The reasoning stage uses confirmed links to justify proposals:
> "`dilated_causal_conv → receptive_field` was confirmed in rounds 2 and 4. I'm now combining it with `spectral_conv` to test whether `spectral_conv → frequency_resolution` holds."

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

#### Empirical extension point — `file_vector` + `ExpertContextItem` (replaces the reverted `regime_scores`)

> **Phase A was reverted** — see §Phase A in the implementation checklist (§5). The `regime_scores` field no longer exists. The extension point for the Data Analysis Agent is now `ExpertContextItem`, not a hardcoded field on `ExperimentRecord`.

The raw 20-element `file_vector` on `ExperimentRecord` is the per-experiment empirical data. It is **orthogonal** to `expert_context` (which is per-iteration, dataset-global advice) — the two compose naturally:

- `file_vector` = "here is what happened" (per-experiment raw scores, no interpretation)
- `ExpertContextItem` = "here is what this means" (expert-provided frequency mapping, regime definitions, anomaly flags)

When the Data Analysis Agent comes online, it provides interpretation of `file_vector` via `ExpertContextItem`:

- **Propose named regimes** — e.g. "files 0-4 are the low-frequency kHz band (1.1–9.0 kHz), files 11-19 are the MHz band" — as an `ExpertContextItem` with `kind="empirical"`. The proposal agent reads the raw `file_vector` AND the expert's regime definition, and reasons across both.
- **Flag anomalies** — e.g. "file 3 has a persistent 50 Hz artifact that makes its score unreliable" — as another `ExpertContextItem`. The proposal agent's `DiscoveryMemo` can then cite this finding.
- **Compute derived metrics** — e.g. "mean score for files 0-4 is 0.15, which is the worst regime" — as structured content inside the `ExpertContextItem`. This is the SAME information that `regime_scores` used to provide, but now it lives in the expert context where it belongs, not in the schema.

No schema migration is needed when the Data Analysis Agent adds new regime definitions. The `file_vector` stays fixed; the interpretation is layered on top via the existing `ExpertContextItem` interface.

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
| Splitting the proposal agent into two graph **nodes** (`Scientific_Reasoning_Subnode` and `Architectural_Design_Subnode`) | Replaced by a **three-stage configurable pipeline inside one node** (§2A). Same scientific benefit, no graph surgery. Escalate to a node split only if a future Literature Agent needs to feed into a specific stage independently. |
| `MemorySummarizer` as a new LLM agent | Replaced by the deterministic `component_leaderboard` derived field on `InterpretationOutput` (§2B). No new LLM call per round; quota stays flat. |
| `UnifiedContextAssembler` | Already exists, called `protocols/`. Renaming would not add value. |
| `Research_Journal.md` sidecar markdown file | **Hard veto.** Violates the "schemas + storage + protocols ONLY" invariant in `CLAUDE.md`. The same narrative can be derived from records on demand or live in one node's output schema. |

## 5. Implementation phasing (incremental, each phase shippable on its own)

| Phase | Change | Effort | Unlocks |
|---|---|---|---|
| **A** | ~~`regime_scores`~~ **REVERTED** — see §Phase A below. No code changes remain from Phase A. The 20-element `file_vector` on `ExperimentRecord` stays as the raw source of truth. Any frequency-band interpretation belongs in expert advice, not in the schema. | — | — |
| **B** | Replace the proposal agent's existing two-call pattern with the **three-stage configurable pipeline** from §2A: (1) comparison — systematic review of selected past models, (2) causal reasoning — forward-looking hypothesis building on comparisons, (3) proposing — concrete architecture tethered to the memo. Add `ReasoningPipelineConfig` at the workflow level. Add `ModelSelectionStrategy` for smart pre-filtering of candidate models. Add `ExpertContextItem` (§2D) for polymorphic upstream input. Add DI (`bridge_factory`) to the proposal agent. | large | Every proposal is backed by a structured `DiscoveryMemo` that compares past models, forms a causal hypothesis, and makes a falsifiable prediction. The pipeline is configurable — adding/removing/reordering stages is a config change, not a code change. The polymorphic input slot for future upstream agents is in place. |
| **C** | Add `VocabEntry`-based lineage validator (`check_inherited_components` for features). Add `component_leaderboard` to `InterpretationOutput`. Implement the promotion engine for both vocab entries and feature→capability links (`ProposedVocabLink` confirmed → `VocabEntry.related_to` populated). Note: the `VocabEntry` schema and seed file land in Phase B (B.6a); Phase C adds the validator + interpretation aggregation + link promotion on top. | medium | Lineage tracking is end-to-end. Feature→capability links are empirically validated. |
| **D** | Add `ResearchDirective` schema and the three guardrail layers in §2C. | medium | Guided mode actually constrains the search. |
| **E** | Add the `falsifiable_prediction` retrospective check inside the reflector: confirmed / refuted / partial label, written into the record. Aggregate the hit rate in `InterpretationOutput`. | small | The proposal agent's scientific accuracy becomes a measurable, monitorable quantity. |

Each phase has its own tests. Each is independently revertable. Each is small enough to commit and PR cleanly.

## 6. Open questions

1. **Falsifiable prediction granularity**. ~~Predicting one regime score is the minimum.~~ (Phase A regime_scores reverted — see §Phase A above.) The `metric` field is now free-text, so the LLM can predict on any measurable quantity: `denoising_score`, `mean(file_vector[0:5])`, a specific `file_vector[i]`, etc. Open question: should we constrain the metric to a known set of patterns (easier to evaluate programmatically) or leave it fully free-text (more flexible but harder for the reflector to parse)? **Recommendation**: start free-text with a few documented examples in the prompt; add pattern constraints only if the reflector can't reliably evaluate free-form metrics.
2. **Vocabulary seeding** (now `VocabEntry`, unified features + capabilities). **Done** — 21 entries (11 features + 10 capabilities) in `agent/schemas/vocab_seed.json`. All `related_to` fields start empty — connections are discovered through the `ProposedVocabLink` hypothesis-test-verify loop.

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

7. ~~**Regime vocabulary consolidation**~~. **Withdrawn** — Phase A reverted. Regime definitions now live in expert advice (`ExpertContextItem`), not in the schema. There is no regime vocabulary to consolidate. If the Data Analysis Agent eventually proposes named regimes, they flow through the same `ExpertContextItem` interface as all other expert context — no separate vocabulary mechanism needed.

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

### Phase A — ~~`regime_scores`~~ REVERTED

**Status**: ❌ **implemented then reverted** (commit `c836904` → revert `392ef6b` / `06b70a0`).

**What was built**: a `regime_scores: Dict[str, float]` field on `ExperimentRecord` with hardcoded frequency-band definitions (`low_freq_kHz` = files 0-4, `mid_freq_10kHz` = files 5-10, `high_freq_MHz` = files 11-19, `global` = all). A new `execute_tools/regime_aggregator.py` module computed these from `file_vector`. Planner and reflector prompts were extended with regime-aware sections.

**Why it was reverted**: the low/mid/high frequency band division is **domain knowledge**, not infrastructure. Hardcoding it into `REGIME_DEFINITIONS` and baking it into `ExperimentRecord` violated the V2 design principle: domain knowledge should come from external expert advice (the `tuner_advice/*.json` files, or the future Data Analysis Agent via `ExpertContextItem` in §2D), not from the codebase.

**What stays**:
- `file_vector: Optional[List[Optional[float]]]` on `ExperimentRecord` — the raw 20-element per-file score array. This is the source of truth. The LLM already sees it in the prompt, and it already contains all per-frequency-band information.
- The existing "FILE VECTOR AND SCORING" prompt section — explains what `file_vector` is without imposing any frequency-band interpretation.
- `tuner_advice/gated_fno_freq_band_aware_v1.json` — the file-to-frequency mapping as expert advice. This is exactly where domain knowledge belongs: external, editable, per-experiment, not baked into the schema.

**The extension point for the Data Analysis Agent** is now `ExpertContextItem` (§2D), NOT a hardcoded field on `ExperimentRecord`. When the Data Analysis Agent wants to provide aggregated regime scores, it emits them as an `ExpertContextItem` with `kind="empirical"` — the same interface every other upstream agent uses. No schema migration needed.

**Lesson learned**: infrastructure provides containers (`file_vector`, `ExpertContextItem`). Domain knowledge fills those containers (expert advice files, agent-generated findings). Don't mix the two.

---

### Phase B — Three-stage reasoning pipeline + `ExpertContextItem`

**Goal**: replace the proposal agent's existing two-call pattern with the three-stage configurable pipeline from §2A (comparison → reasoning → proposing), add the `ExpertContextItem` polymorphic input slot from §2D, and wire the `ModelSelectionStrategy` pre-filter. After Phase B, every proposal is backed by a structured `DiscoveryMemo` that systematically compares past models, forms a causal hypothesis, and makes a falsifiable prediction.

**Depends on**: nothing (Phase A was reverted). The `FalsifiablePrediction` references free-text metrics derived from `file_vector` and expert advice, not from `regime_scores`.

**PR size**: large (the biggest phase — introduces multiple new schemas, 3 new prompts, the pipeline runner, the model selection pre-filter, and DI on the proposal agent).

**Files**:
- `agent/schemas/proposal.py` — add `ModelComparison`, `DiscoveryMemo`, `FalsifiablePrediction`, `InheritedComponent`, `ExpertContextItem`, `ReasoningStage`, `ModelSelectionStrategy`, `ReasoningPipelineConfig`. Add `expert_context: List[ExpertContextItem]` and `reasoning_pipeline: ReasoningPipelineConfig` to `ProposalInput`. Keep `human_advice: str` deprecated for backward compat.
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — update the protocol to wrap legacy `human_advice` strings into a single `ExpertContextItem` with `source="human", kind="human", cite_id="human_advice"`.
- `nodes/ml_model_proposal_agent.py` — replace the existing two-call pattern with `produce_discovery_memo(context, pipeline)` (the configurable pipeline runner from §2A) + the proposing stage. Add constructor DI (`bridge_factory`) for pseudo-mode testing. Implement the `ModelSelectionStrategy` pre-filter as a deterministic Python function.
- `workflows/llm_config.py` (or `workflows/model_exploration.py`) — attach `ReasoningPipelineConfig` at the workflow level so the chain uses the same pipeline across all iterations.
- `agent/prompts.py` — add `COMPARATIVE_ANALYSIS_SYSTEM_PROMPT`, `CAUSAL_REASONING_SYSTEM_PROMPT`, update `PROPOSAL_SYSTEM_PROMPT` to require references to the memo and comparisons.
- `tests/unit/agent/proposal_agent/test_discovery_memo_schema.py` (new) — schema validation tests for all new schemas.
- `tests/unit/agent/proposal_agent/test_reasoning_pipeline.py` (new) — unit tests for the pipeline runner and model selection pre-filter.
- `tests/pseudo_data/api_call_outputs/ml_model_proposal_agent/` (new) — predefined responses for comparison, reasoning, and proposing stages.
- `tests/integration/nodes/test_ml_model_proposal_agent.py` — add a `@dual_mode` test exercising the 3-stage pipeline in pseudo mode.

**Sub-tasks** (reordered to reflect actual implementation sequence):

#### Group 1 — Schemas + workflow config (DONE)

- ☑ B.1 `FalsifiablePrediction` schema. **Done** — `agent/schemas/proposal.py`, commit `abbba2c`.
- ☑ B.2 `InheritedComponent` schema. **Done** — same commit.
- ☑ B.3 `ExpertContextItem` schema. **Done** — same commit.
- ☑ B.4 `ModelComparison` schema. **Done** — same commit.
- ☑ B.5 `DiscoveryMemo` schema with validators. **Done** — same commit. Also added `proposed_vocab_candidates`.
- ☑ B.6 `ReasoningStage`, `ModelSelectionStrategy`, `ReasoningPipelineConfig`. **Done** — same commit.
- ☑ B.6a `VocabEntry` schema. **Schema done** — same commit. Seed file is Group 2.
- ☑ B.7 `expert_context` + `reasoning_pipeline` on `ProposalInput`. **Done** — same commit.
- ☑ B.8 `ProposalLLMConfig` + `WorkflowLLMConfig.propose` update. **Done** — `workflows/llm_config.py`, commit `c5059ef`.

#### Group 2 — Schema tests + vocab seed (DONE)

- ☑ B.18 Schema unit tests — 40 tests covering validators and cross-field checks for all Group 1 schemas. **Done** — `tests/unit/agent/ml_model_proposal_agent/test_phase_b_schemas.py`, commit `0c485bd`.
- ☑ B.6a-seed `agent/schemas/vocab_seed.json` — 21 canonical entries: 11 features + 10 capabilities drawn from all 6 built-in models. All `related_to` fields are **empty** — feature→capability connections are discovered through experimentation via `ProposedVocabLink`. Added `vocab_seed: List[VocabEntry]` to `ProposalInput` (vocabulary flows as protocol data, not file reads). Added `ProposedVocabLink` schema and `proposed_vocab_links` field to `DiscoveryMemo`.

#### Group 2b — Centrifugal-force schema additions (NEXT)

Schema and validator additions that prevent the system from collapsing into conservative local optima. See "Centrifugal forces" section in §2A for the full analysis.

- ☐ B.24 Add `minimum_boldness` validator to `FalsifiablePrediction` (default 0.05). Predictions with `boldness < minimum_boldness` are rejected. Add computed `boldness` property. *(Concern #2: Predictive Risk Aversion)*
- ☐ B.25 Add `max_length=5` to `DiscoveryMemo.citation_sources`. Add validator: each `cite_id` must appear verbatim in `causal_hypothesis` or `proposed_change` text. *(Concern #5: Citation Pollution)*
- ☐ B.26 Add `memo_consistency_notes: List[str] = []` to `ProposalOutput`. Stage 3 flags inconsistencies between the DiscoveryMemo and what's physically implementable. *(Concern #3: Error Propagation)*
- ☐ B.27 Unit tests for the new validators (boldness, citation inclusion, consistency notes).

#### Group 3 — Prompt templates (as separate .md files)

Prompt templates live in `agent/prompts/proposal/` as `.md` files, NOT in `prompts.py`. The pipeline runner loads them at runtime. This keeps complex multi-paragraph prompts readable and version-controlled separately.

- ☐ B.14 `agent/prompts/proposal/comparison_stage.md` — COMPARATIVE_ANALYSIS prompt. Instructs the LLM to produce `List[ModelComparison]` + `List[ProposedVocabLink]` hypotheses. Includes vocabulary-contributor sub-task and **ablation suggestion** sub-task ("which component should we remove to test its isolated contribution?"). Two variants: exploration mode (honest uncertainty, diagnostic, demand vocabulary growth) and exploitation mode (leverage confirmed links, reference prior ablation evidence).
- ☐ B.15 `agent/prompts/proposal/causal_reasoning_stage.md` — CAUSAL_REASONING prompt. Four structural teeth: comparison-backed, falsifiable, devil's advocate, architectural tethering. **Bold prediction requirement**: "your prediction must have boldness ≥ 0.05 — timid predictions are rejected." Two mode variants.
- ☐ B.16 `agent/prompts/proposal/proposing_stage.md` — ARCHITECTURE_DESIGN prompt. Requires references to memo's `proposed_change` and `inherited_components`. Must populate `memo_consistency_notes` if any physical impossibilities are noticed. **Citation discipline**: "cite ONLY items that materially changed your hypothesis." Two mode variants.
- ☐ B.16a `_resolve_exploration_mode(records, pipeline)` — auto-detection logic. Checks evidence depth (agent-proposed records, distinct model types) AND **vocabulary diversity** (candidate/canonical ratio — stagnation triggers explore mode). *(Concern #1: Innovation Stagnation)*
- ☐ B.17 Labeled-block rendering of `expert_context` items in all three stage prompts.

#### Group 4 — Pipeline runner + model selection + DI

- ☐ B.10 `ModelSelectionStrategy` pre-filter — deterministic Python function. Input: all records + strategy config. Output: filtered candidate models.
- ☐ B.11 `produce_discovery_memo(context, pipeline) -> DiscoveryMemo` — configurable pipeline runner. Each enabled stage calls `bridge.generate()` with accumulated context.
- ☐ B.12 Proposing stage — receives DiscoveryMemo, returns `ProposalOutput` tethered to the memo.
- ☐ B.13 Constructor DI (`bridge_factory`) on `MLModelProposalAgent`, following PR #24's pattern.
- ☐ B.9 Update `local_full_context` protocol to carry `expert_context`. Wrap legacy `human_advice` into `ExpertContextItem`.
- ☐ B.19 Unit tests for pipeline runner + model selection pre-filter (mocked LLM).

#### Group 5 — Integration testing (deferred)

These are important for long-term robustness but not blocking for the initial pipeline implementation. Mock tests + running real loops directly is sufficient during active development.

- ☐ B.20 Predefined pseudo data for proposal agent stages.
- ☐ B.21 `@dual_mode` integration test for the 3-stage pipeline.
- ☐ B.22 Mocked-LLM unit tests: memo validation failure → retry, deviation notes, backward-compat with empty `expert_context`.
- ☐ B.23 Tier-1 integration test: real LLM produces valid memo + proposal with tethered `proposed_change`.

**Verify** (after Group 4):
- All unit tests pass: `uv run pytest tests/unit/agent/ml_model_proposal_agent/ -q`.
- Manual: run the agent on real interpretation output, inspect the `DiscoveryMemo` JSON, confirm it references specific `file_vector` evidence and vocabulary entries in `causal_hypothesis`.

---

### Phase C — Vocabulary promotion + lineage validator + centrifugal metrics

**Goal**: claimed inheritance becomes verifiable; the system grows its vocabulary by structural promotion across runs; confirmed `ProposedVocabLink` entries populate `VocabEntry.related_to`; centrifugal metrics prevent conservative collapse.

**Depends on**: Phase B (the memo is where `inherited_components` and `proposed_vocab_links` live).

**Centrifugal-force items from Phase B analysis (deferred to Phase C)**:
- Component delta scoring: `avg_score_with - avg_score_without` for each vocabulary entry. Promotion requires `delta > 0` AND low confounding. *(Concern #4: Promotion Spuriousness)*
- Vocabulary diversity metric: `n_candidates / n_total` tracked by interpretation agent, surfaced to proposal agent. Stagnation triggers explore mode. *(Concern #1: Innovation Stagnation)*
- `ProposedVocabLink` aggregation: links confirmed in ≥2 runs get promoted to `VocabEntry.related_to`. *(Hypothesis-test-verify loop from §2B)*
- Information gain metric: `boldness × (1 if confirmed else 0)` tracked alongside hit rate. *(Concern #2: Predictive Risk Aversion — Phase E primary, Phase C aggregation)*

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

**Depends on**: Phase B (FalsifiablePrediction lives in DiscoveryMemo). Phase A dependency removed (reverted).

**PR size**: small.

**Files**:
- `agent/schemas/hyperparam_tuning.py` — add `prediction_outcome: Optional[Literal["confirmed", "refuted", "partial"]]` to `ExperimentRecord`.
- `nodes/ml_hyperparameter_tune_agent.py` — in the reflector path, look up the previous round's `DiscoveryMemo.falsifiable_prediction` (if any), compute the predicted metric from the current round's `file_vector` and `denoising_score`, label the outcome, write into the record.
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
