# Design Proposal V2: Adaptive Scientific Discovery Framework for SIDERIUS

**Status**: Phase F complete — receptive-side infrastructure for external agents: `AgentCard` schema, `ProposalInput.agent_cards`, `VocabEntry.origin`, `render_agent_cards()`, `render_expert_context()` dedup + confidence sort, Contributors instruction in stage prompts, protocol `mindset`/`agent_cards` params. 977 unit tests passing. No external agent is implemented yet — Phase F is infrastructure only. Next: implement `ml_literature_review` (see `docs/external_agents_for_proposer.md`). Supersedes the V1 proposal at the bottom of this file.

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

**Implementation**: same node, three `LLMBridge` calls in a configurable pipeline. No new node, no new schema container. The pipeline is a list of stages — adding, removing, or reordering stages is a configuration change, not a code change. Individual stages can be routed to different models (e.g. comparison on `gemini-2.5-flash`, reasoning on `gemini-3.1-pro`) via `ProposalLLMConfig`.

#### The configurable pipeline

The reasoning pipeline is **configured at the workflow level** (not per-run), so a chain uses the same pipeline across all its iterations. The default is the 3-stage pipeline; customization is adding/removing/reordering entries in a list.

Key schemas (`agent/schemas/proposal.py`):
- **`ReasoningStage`** — one LLM call: `name`, `system_prompt_key`, `output_mode` (json/text), `enabled`. Stages can be disabled or added without touching the runner.
- **`ModelSelectionStrategy`** — pre-filter method (`top_n`, `all`, `feature_match`, `human_specified`) + method-specific params. Controls which past models the comparison stage sees.
- **`ReasoningPipelineConfig`** — workflow-level config: `stages` list, `model_selection`, `exploration_mode` (`auto`/`explore`/`exploit`), `policy: ResearchPolicy`.

#### Policy-Mechanism Decoupling

> **The architecture is the hardware; the policy layer is the software that defines the experiment's soul.**
>
> Every validator threshold, exploration trigger, and reasoning constraint in the pipeline is a **mechanism** — the structural capability to enforce a rule. The **policy** determines how aggressively that mechanism is applied. Different research strategies need different settings: a "high-risk discovery" run wants low `minimum_boldness` and aggressive vocabulary growth; a "safety-first validation" run wants high boldness thresholds and conservative promotion rules.
>
> The policy is NOT a separate config system — it lives inside `ReasoningPipelineConfig` as a `ResearchPolicy` object, tunable at the workflow level. Individual thresholds can also be overridden per-round via `ExpertContextItem(kind="strategy")`.

**`ResearchPolicy`** — the tunable knobs inside `ReasoningPipelineConfig.policy`. Defaults are conservative; override per-workflow or per-round via `ExpertContextItem(kind="strategy")`. Key fields: `minimum_boldness` (0.05), `max_citations` (5), `vocab_stagnation_threshold` (0.1), `min_runs_for_promotion` (3), `require_positive_delta` (deferred to Phase E).

**Override examples** (via workflow config or `ExpertContextItem`):
- **High-risk discovery run**: `policy.minimum_boldness = 0.15` (demand bold predictions), `policy.vocab_stagnation_threshold = 0.2` (aggressive vocabulary growth)
- **Safety-first validation**: `policy.minimum_boldness = 0.02` (accept conservative predictions), `policy.min_runs_for_promotion = 5` (strict promotion)
- **Per-round override**: inject `ExpertContextItem(kind="strategy", content="For this round, set minimum_boldness=0.2 — we need a definitive test.")` — the pipeline runner reads strategy items and applies them as temporary policy overrides

#### Strategy Performance Report (feedback loop)

After each iteration, the interpretation agent computes a **Strategy Performance Report** — prediction hit rate, average boldness, information gain, vocabulary growth, citation accuracy — formatted as an `ExpertContextItem(kind="strategy_report")` and injected into the next round's `expert_context`. The LLM sees its own track record and can adjust: "my physics-driven citations are being refuted — I should demand more empirical evidence."

*Phase*: E (reflector computes outcomes) + C (interpretation agent aggregates into report). Not yet implemented.

#### ExpertContextItem rendering hierarchy

The prompt template renders `expert_context` items grouped by `kind`, with clear labels that signal their epistemic status:

```
[EMPIRICAL FINDING] (from data_analysis_agent, confidence=0.9)
  Low-frequency files 0-4 show near-zero SNR across all models...

[THEORETICAL CONSTRAINT] (from physics_expert, confidence=0.7)
  The Nyquist limit at 5 MHz means...

[STRATEGY REPORT] (from interpretation_agent)
  Rounds 1-5 summary: hit rate 40%, boldness 0.12...

[HUMAN DIRECTIVE] (high priority)
  Focus on WaveNet variants only...
```

The grouping and labeling IS the priority system. No explicit `priority_weight` field — the LLM reasons about which sources to trust based on the `kind` labels, `confidence` scores, and the strategy report's track record analysis. The prompt instructs: "Empirical findings are weighted by their confidence. Theoretical constraints are treated as hard limits unless contradicted by empirical evidence. Human directives take precedence. Strategy reports inform your approach but do not override human directives."

**Customization examples**:
- **Skip comparison, just reason**: set `stages[0].enabled = False`
- **Add a physics check**: append `ReasoningStage(name="physics_check", system_prompt_key="PHYSICS_REVIEW")`
- **Only compare WaveNet variants**: set `model_selection = {"method": "feature_match", "params": {"feature": "dilated_causal_conv"}}`
- **Human says "focus on top 3"**: set `model_selection = {"method": "top_n", "params": {"n": 3}}`
- **Human says "only look at these two"**: set `model_selection = {"method": "human_specified", "params": {"models": ["wavenet", "gated_fno"]}}`

#### Design decisions

**`ProposalLLMConfig`** — each pipeline stage can route to a different LLM (comparison on flash, reasoning on pro). Mirrors the `TunerLLMConfig` planner/reflector pattern; lives in `WorkflowLLMConfig.propose`.

**`expert_context` flows through the protocol** — per the inter-node communication principle, `human_advice` and other expert context reaches the proposal agent via `local_full_context`, not by workflow-level injection. The protocol wraps `human_advice` into an `ExpertContextItem(source="human")`.

**Per-stage output mode** — stages support both JSON (`bridge.generate()`) and plain-text (`bridge.generate_text()`). Comparison and reasoning stages default to JSON (feeds the DiscoveryMemo); a future free-reasoning stage can use text.

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

**Non-selected models are not invisible.** Models outside the top-N still appear in the Stage 1 prompt as a `non_candidates_overview` list. Each entry contains `best_score`, `description`, `key_findings`, `bottlenecks`, `score_trend`, and `strategy_assessment` from `model_knowledge_cache` — but **no source code**. This tells the comparison LLM what was tried and why it fell short, without paying the token cost of reading the code. The two-tier split is intentional:

| Tier | Who | What the LLM receives | Purpose |
|---|---|---|---|
| **Candidates** (top-N) | High-scoring models | Full source code + all metadata | Deep analysis; borrow architectural ideas |
| **Non-candidates** (the rest) | Lower-scoring models | Text summary only (analysis + description) | Know what was tried; avoid re-proposing dead ends |

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

**In `auto` mode**, `resolve_exploration_mode()` (`nodes/proposal_helpers.py`) checks: (1) vocab stagnation — if `vocab_diversity_ratio < policy.vocab_stagnation_threshold`, force explore; (2) evidence depth — fewer than 5 agent-proposed models → explore; otherwise → exploit.

**The prompts change based on the mode**:

- **Exploration system prompt addition**: "You are in EXPLORATION mode. You have limited experimental evidence from this project. Your goal is NOT to beat the SOTA — it's to TEST a specific hypothesis. Propose a DIAGNOSTIC experiment that will confirm or refute one specific claim about a feature→capability link. Frame your prediction as 'IF [feature] enables [capability], THEN [metric] should change by [amount].' Be honest about what you don't know."

- **Exploitation system prompt addition**: "You are in EXPLOITATION mode. You have N confirmed patterns from previous rounds (hit rate: X%). Build on what works. Combine confirmed feature→capability links. Your prediction should be based on empirical evidence from this project, not generic ML knowledge. Reference specific prior rounds that confirmed the patterns you're building on."

The human can override: `exploration_mode: "explore"` forces exploration even at round 20 (useful for testing a new direction); `exploration_mode: "exploit"` forces exploitation even at round 1 (useful when the human has strong prior knowledge via ExpertContextItem).

#### Stage 1: Comparison — "What do we know?"

Backward-looking systematic review of the pre-filtered candidate models. Produces one **`ModelComparison`** per model: `key_mechanism` (one sentence, must reference a specific feature), `strengths`/`weaknesses` (tied to `file_vector` evidence), `lesson_for_next_proposal`. The full list feeds into Stage 2 as context.

#### Stage 2: Reasoning — "What should we try?"

Forward-looking causal hypothesis, building on Stage 1's comparisons. Produces the **`DiscoveryMemo`** — the "Final Verdict" that Stage 3 is structurally tethered to. Key fields:
- `sota_mechanism` — WHY the current best model works (physical/architectural, not vague)
- `proposed_change` — what changes relative to SOTA, expressible as "replace X with Y" or "add Z"
- `causal_hypothesis` — why it should help: (a) SOTA mechanism preserved, (b) bottleneck relaxed, (c) new mechanism introduced
- `falsifiable_prediction` — `FalsifiablePrediction(metric, current_value, predicted_value, threshold_for_refutation)`. Metric is free-text: `denoising_score`, `mean(file_vector[0:5])`, `file_vector[17]`, etc.
- `predicted_failure_modes` — at least one way the proposal could fail (schema-enforced)
- `inherited_components`, `citation_sources` — lineage and attribution (§2B, §2D)

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

**`InheritedComponent`** (`agent/schemas/proposal.py`) — one building block carried over from a past winning run. Fields: `component` (canonical name from vocab, e.g. `dilated_causal_conv`), `from_model_type`, `from_run` (optional), `contribution_evidence` (one sentence, evidence-linked), `citation_source` (cite_id of the `ExpertContextItem` that motivated the inheritance, if any).

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

**`VocabEntry`** (`agent/schemas/proposal.py`) — one vocabulary entry. Adding a new `kind` (e.g. `failure_pattern`) requires no code changes — the engine treats all entries generically. Key fields:
- `name` — canonical snake_case identifier
- `kind` — `"feature"`, `"capability"`, or `"discovery"` (new kinds are free to add)
- `tier` — `"canonical"` (seed + promoted) or `"candidate"` (agent-proposed, not yet promoted)
- `related_to` — starts empty in the seed; populated through confirmed `ProposedVocabLink` hypotheses
- `pattern` — regex hint for features; used by the validator to verify claimed inheritance in code
- `seen_in_runs` — list of runs that have used this entry (drives promotion counting)
- `aliases` — spelling variants merged by `_dedup_promoted()` at promotion time

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

4. **Aggregation (Phase E — E.7)**: the interpretation agent collects all proposed links across rounds. Links that reach `confirmed` status in ≥2 runs get their `related_to` fields populated on the corresponding `VocabEntry` entries in the next round's `runtime_vocab`. This step depends on Phase E's reflector (E.3) evaluating link status after each experiment — until then, links stay `status="proposed"`.

**`ProposedVocabLink`** — a hypothesized `feature → capability` connection proposed by Stage 1, tested via `FalsifiablePrediction`, confirmed/refuted by the reflector (Phase E). Fields: `feature`, `capability`, `evidence` (experiment-grounded), `status` (`proposed`/`confirmed`/`refuted`). Lives in `DiscoveryMemo.proposed_vocab_links`. Confirmed links (≥2 runs) get promoted to `VocabEntry.related_to` by the interpretation agent (Phase E — E.7).

The `InheritedComponent.component` field references entries from this vocabulary. The proposal agent's prompt includes the full `runtime_vocab` (both tiers, both kinds, clearly labeled) and instructs: "Use canonical entries verbatim. When proposing a link between a feature and a capability, cite specific experimental evidence — do not guess from generic ML knowledge."

The comparison stage uses the vocabulary to structure its analysis:
> "Model A uses **dilated_causal_conv** (feature, canonical). Its file_vector shows strong scores on files 11-19 but weak on files 0-4. I propose the link `dilated_causal_conv → receptive_field` based on this evidence, but this needs experimental verification."

The reasoning stage uses confirmed links to justify proposals:
> "`dilated_causal_conv → receptive_field` was confirmed in rounds 2 and 4. I'm now combining it with `spectral_conv` to test whether `spectral_conv → frequency_resolution` holds."

#### Promotion rule (autonomous, conservative)

The interpretation agent, on each run, walks all candidates currently active in records and applies a **structural promotion criterion**. The full intended rule has four conditions — two are implemented in the current MVP, two are deferred to Phase E:

> **MVP (implemented):**
>   1. ✅ it has appeared in `seen_in_runs` of ≥3 distinct runs (`kind in {"feature", "capability"}`), AND
>   2. ✅ its description has been semantically deduplicated against existing canonical entries — the LLM (`_dedup_promoted()`) judges whether it's "really new" or a synonym; synonyms are merged via the `aliases` list rather than promoted.
>
> **Deferred to Phase E:**
>   3. ☐ at least one of those runs scored above the current SOTA (`require_positive_delta`) — needs per-run SOTA scores tracked alongside `seen_in_runs`, which `build_runtime_vocab` doesn't yet do.
>   4. ☐ either the candidate already carries a regex/AST hint, or the LLM can synthesize one — deferred until we have enough promoted entries to calibrate the pattern quality.

A candidate that fails condition 1 stays in candidate tier. A candidate that fails condition 2 (semantic dedup) is merged into an existing canonical entry as an alias. Conditions 3 and 4 will tighten the bar once we have real chain run data to calibrate thresholds.

The criterion is intentionally conservative: we want canonical promotion to be a **rare and meaningful event**, not noise.

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

#### Key implementation decisions

- **Candidate vs discovery separation** — `ProposalOutput.proposed_vocab_candidates` carries new feature/capability candidates; `proposed_discoveries` carries `kind="discovery"` empirical sentences. The two flow through different paths in the interpretation agent.
- **`seen_in_runs` injection** — the interpretation agent injects `proposed_by_run = previous_proposal["model_name"]` onto candidates before calling `build_runtime_vocab`. The proposal LLM never sets this field itself.
- **Validator inheritance check** — each claimed `inherited_component.component` is regex-matched against the plugin source. An unsubstantiated claim is a validation failure → implementor retry.
- **`component_leaderboard`** *(future)* — cross-round aggregation (appearance count, avg score, best run). Fully derivable from existing records, no separate file needed.

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

| Future agent | Module prefix | Produces | Kind of context |
|---|---|---|---|
| `data_analysis_agent` | `data_` | Empirical findings about the raw signals — noise distributions, SQUID-specific artifacts, per-frequency-band SNR, observed periodicities, unexplained peaks | **empirical** |
| `ml_literature_review` | `ml_` | Architecture ideas synthesized from recent ML papers (Semantic Scholar, OpenReview) | **literature** |
| `physics_literature_review` | `phys_` | Physical constraints on SQUID systems — symmetries, mass-range / energy bounds, causality, band limits. First agent with `phys_` prefix; establishes that module convention. | **theoretical** |
| `research_narrative_agent` (optional) | `ml_` | Meta-summary of what's been tried; plateau detection; strategic suggestions | **narrative** |
| Human expert | — | Hand-written advice (today's `human_advice`) | **human** |

Full design for `ml_literature_review` and `physics_literature_review` — including output schemas, protocol files, trigger conditions, and implementation checklist — is in `docs/external_agents_for_proposer.md`.

Crucially, these agents differ in *what* they say but not in *how* they say it — they all produce typed structured advice that the proposal agent should weigh against past experiment records when forming its `DiscoveryMemo`. V2's design principle here is **don't invent an umbrella container**. The V1 proposal called for an `InquiryContext` / `UnifiedContextAssembler` to hold all these sources — V2 explicitly rejected that as premature abstraction. Instead, V2 reuses the existing pattern: schemas + protocols. Each upstream agent has its own output schema, and a protocol function (`{source}_to_ml_model_propose`) maps that output into the proposal agent's input. The proposal agent treats all of them through one minimal polymorphic field.

#### The polymorphic field: `ExpertContextItem`

**`ExpertContextItem`** (`agent/schemas/proposal.py`) — the single typed interface all upstream sources go through. Fields: `source` (free-text producer id), `kind` (`empirical`/`theoretical`/`literature`/`human`/`narrative`), `content` (max 4 KB), `cite_id` (stable id for `DiscoveryMemo.citation_sources`), `produced_at`, `confidence`. Lives in `ProposalInput.expert_context: List[ExpertContextItem]`.

The migration is non-breaking: legacy `human_advice` strings are wrapped at the protocol boundary into `ExpertContextItem(source="human", kind="human")`. Adding a new upstream agent = emitting more items through its own protocol function — no schema changes needed.

This is the V2 minimalist principle in action: **one small new field unlocks N future upstream agents**. We are not creating an `InquiryContext` container or a `UnifiedContextAssembler` orchestrator. We are extending a list.

#### Agent name cards — epistemic calibration

`ExpertContextItem` conveys *what* an agent found. It does not tell the proposal LLM *who* the agent is, what domain it covers, or how much to trust it. Without this context, the LLM treats `source="ml_literature_review"` and `source="data_analysis_agent"` identically — but they have very different epistemic statuses: one is experimental ground truth on TIDMAD data, the other is a literature prior that may not transfer.

The fix is an **`AgentCard`** — a static self-description each external agent emits alongside its findings. An `AgentCard` carries: `agent_name`, `role` (one sentence), `expertise_domain`, `coverage` (data sources and time range), `limitations`, and `trust_guidance` (how the proposal LLM should weight this agent's findings). The proposal agent collects these into `ProposalInput.agent_cards: List[AgentCard]` and renders them as a "Contributors" section *before* the `ExpertContextItem` list in each stage prompt — so the LLM reads *who is contributing* before it reads *what they found*.

Key design principle: **findings are the evidence; the name card is the calibration**. The `AgentCard` is defined once in the external agent's implementation (it is static knowledge about what the agent is) and passed through every run via its output schema.

The system prompt instruction in `comparison_stage.md` and `causal_reasoning_stage.md` will tell the LLM:
- Literature agents: treat as promising priors. Only experiment runs confirm applicability to TIDMAD.
- Physics agents: physical constraints are hard limits. Do not propose architectures that violate them.
- Human directives: always take precedence.

Phase F (§7) implements `AgentCard`, `ProposalInput.agent_cards`, `render_agent_cards()`, and the system prompt instructions.

#### Receiving-end gaps to fix before wiring external agents

Three small gaps in the current code that would cause problems as soon as the first external agent is wired:

1. **`VocabEntry.proposed_by_run` overloading**: this field is currently used for both attribution (who suggested the term) and promotion counting (injected into `seen_in_runs`, promotion fires at count ≥ 3). If an external agent sets `proposed_by_run="ml_literature_review"`, that string enters `seen_in_runs` and the term gets promoted after 3 literature scans — without experimental validation. Fix: add `origin: Optional[str]` to `VocabEntry`. External agents set `origin=` and leave `proposed_by_run=None`. Promotion stays experiment-driven.

2. **`render_expert_context` has no deduplication**: two agents may independently cite the same paper (`cite_id` collision). Fix: deduplicate by `cite_id` before rendering (last occurrence wins).

3. **`render_expert_context` has no confidence-based ordering**: within a `kind` group, items are in insertion order. Fix: sort each group by `confidence` descending; items with `confidence=None` sort last.

Phase F (§7) implements all three fixes alongside the `AgentCard` additions.

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
| **C** | Add `VocabEntry`-based lineage validator (`check_inherited_components` for features). Implement the vocabulary feedback loop: prediction evaluation, discovery generation, `seen_in_runs` accumulation, candidate promotion (count-only MVP, ≥3 runs), semantic dedup (`_dedup_promoted()`). Two-tier model context (`non_candidates_overview`). O(1) LLM call count via `model_knowledge_cache`. `ProposedVocabLink` promotion (`confirmed → VocabEntry.related_to`) completed in Phase E. | medium | Vocabulary compounds across iterations. Each round's discoveries feed the next proposal. Lineage claims are validated in code. |
| **E** | ✅ **Complete.** SOTA-based `evaluate_prediction()`: compares actual score against the SOTA at proposal time (`FalsifiablePrediction.current_value`), not the LLM's predicted value (which is unreliable). Outcomes: `confirmed` (beat SOTA), `partial` (within 5%), `refuted` (clearly below). `delta_from_sota` quantifies the gap. `scientific_accuracy` + `prediction_outcomes_history` carry-forward fields track hit rates across iterations. `update_vocab_link_confirmations()` helper: `confirmed` predictions accumulate per-run counts for each `feature:capability` link; links confirmed in ≥3 distinct runs are promoted to `VocabEntry.related_to`. All evaluation lives in `result_interpretation_agent` — architecturally cleaner than the original plan (which put it in the tuning agent reflector). 939 unit tests passing. | small | The proposal agent's scientific accuracy is now a measurable, monitorable quantity. `ProposedVocabLink` hypotheses graduate to established facts after sufficient empirical confirmation. |
| **F** | ✅ **Complete (infrastructure only).** Receptive-side readiness: `AgentCard` schema + `ProposalInput.agent_cards`; `VocabEntry.origin`; `render_agent_cards()` + Contributors section in stage prompts; `render_expert_context()` dedup + confidence sort; `local_full_context` accepts `mindset`/`agent_cards`. 977 unit tests. **No external agent is built here** — Phase F is the receiving end only. First real test will be `ml_literature_review` (see `docs/external_agents_for_proposer.md`). | small | After Phase F, wiring a new upstream agent = output schema + one protocol file. Nothing in the proposal node changes. |

Each phase has its own tests. Each is independently revertable. Each is small enough to commit and PR cleanly.

## 6. Open questions

1. **Falsifiable prediction granularity**. ~~Predicting one regime score is the minimum.~~ (Phase A regime_scores reverted — see §Phase A above.) The `metric` field is now free-text, so the LLM can predict on any measurable quantity: `denoising_score`, `mean(file_vector[0:5])`, a specific `file_vector[i]`, etc. Open question: should we constrain the metric to a known set of patterns (easier to evaluate programmatically) or leave it fully free-text (more flexible but harder for the reflector to parse)? **Recommendation**: start free-text with a few documented examples in the prompt; add pattern constraints only if the reflector can't reliably evaluate free-form metrics.
2. **Vocabulary seeding** — Done. 21 entries (11 features + 10 capabilities) in `agent/schemas/vocab_seed.json`. All `related_to` fields start empty.

2a. **Promotion tuning** — the MVP threshold (≥3 runs, semantic dedup) is conservative but unvalidated. After the first chain run with promotion live, tune: SOTA threshold strictness, dedup LLM stability, and whether to add a `vocab_promotion_mode: "review"` flag if autonomous promotion misbehaves.
3. **Component pattern matching**. `COMPONENT_PATTERNS` (regex per primitive) is the weakest part of §2B's validator integration — regex against PyTorch source is fragile. Alternative: use AST inspection (`ast.parse` on the plugin file) and look for specific class/function calls. More work, more reliable.
4. **Guided-mode escape hatches**. Should there be a way for the LLM to formally request a relaxation of the directive (e.g. "I think the constraint is impossible to satisfy because of Y; please review")? Otherwise stuck states could waste rounds. But adding an escape hatch risks defeating the point of guided mode.
5. **Hit rate as feedback to the planner**. Phase E is in place — `scientific_accuracy` is now computed and carried forward in `InterpretationOutput`. Next step: surface it in the Phase 2 synthesis prompt alongside `cumulative_information_gain`, so the LLM can see its own track record. Risk: the LLM becomes overconfident or defensive in response to low hit rates.

6. **First non-human upstream agents — Literature Review Agents**. Phase B introduces the `ExpertContextItem` polymorphic input slot and Phase F makes the receiving end fully ready. The first real external agents are `ml_literature_review` and `physics_literature_review` (see `docs/external_agents_for_proposer.md` for the full design). Open questions for those future PRs:
   - How do agents produce `cite_id` values that are stable across re-runs of the same analysis? Hash of the finding content? Timestamped slug? A stable `cite_id` is required for the citation audit trail to work across rounds.
   - How do we evaluate whether a literature agent's findings are actually useful — citation hit rate (per §2D) is the right metric, but it requires Phase E's `prediction_outcome` to be populated before we can cross-reference citations with confirmed hypotheses.
   - Should physics agent findings be persisted into the records or live only in memory per chain? Persisting them turns the records into a growing knowledge base; not persisting keeps the chain stateless.


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

**Why it was reverted**: the low/mid/high frequency band division is **domain knowledge**, not infrastructure. Hardcoding it into `REGIME_DEFINITIONS` and baking it into `ExperimentRecord` violated the V2 design principle: domain knowledge should come from external expert advice (the `advice/{single_agent,workflow}/*.json` files, or the future Data Analysis Agent via `ExpertContextItem` in §2D), not from the codebase.

**What stays**:
- `file_vector: Optional[List[Optional[float]]]` on `ExperimentRecord` — the raw 20-element per-file score array. This is the source of truth. The LLM already sees it in the prompt, and it already contains all per-frequency-band information.
- The existing "FILE VECTOR AND SCORING" prompt section — explains what `file_vector` is without imposing any frequency-band interpretation.
- `advice/single_agent/gated_fno_freq_band_aware_v1.json` — the file-to-frequency mapping as expert advice. This is exactly where domain knowledge belongs: external, editable, per-experiment, not baked into the schema.

**The extension point for the Data Analysis Agent** is now `ExpertContextItem` (§2D), NOT a hardcoded field on `ExperimentRecord`. When the Data Analysis Agent wants to provide aggregated regime scores, it emits them as an `ExpertContextItem` with `kind="empirical"` — the same interface every other upstream agent uses. No schema migration needed.

**Lesson learned**: infrastructure provides containers (`file_vector`, `ExpertContextItem`). Domain knowledge fills those containers (expert advice files, agent-generated findings). Don't mix the two.

---

### Phase B — Three-stage reasoning pipeline + `ExpertContextItem`

**Goal**: replace the proposal agent's existing two-call pattern with the three-stage configurable pipeline from §2A (comparison → reasoning → proposing), add the `ExpertContextItem` polymorphic input slot from §2D, and wire the `ModelSelectionStrategy` pre-filter. After Phase B, every proposal is backed by a structured `DiscoveryMemo` that systematically compares past models, forms a causal hypothesis, and makes a falsifiable prediction.

**Depends on**: nothing (Phase A was reverted). The `FalsifiablePrediction` references free-text metrics derived from `file_vector` and expert advice, not from `regime_scores`.

**What was built:** `ProposalLLMConfig` (per-stage LLM routing), `DiscoveryMemo`, `FalsifiablePrediction`, `InheritedComponent`, `ExpertContextItem`, `ReasoningStage`, `ModelSelectionStrategy`, `ReasoningPipelineConfig` schemas; a vocab seed file (21 canonical entries — 11 features + 10 capabilities, all `related_to` empty pending Phase E link discovery); 3 prompt templates (`comparison_stage.md`, `causal_reasoning_stage.md`, `proposing_stage.md`) each with explore/exploit mode variants; `select_candidate_models()` pre-filter; `resolve_exploration_mode()` auto-detector; `_run_pipeline()` 3-stage runner; constructor DI on `MLModelProposalAgent`. Backward compat: empty `ReasoningPipelineConfig.stages` preserves legacy 2-call mode.

**Validated end-to-end** (`lilab_chain_v2`): pipeline proposed `attn_wavenet` — inherits all 4 wavenet features, adds attention. Validator passed all 9 checks including inheritance verification. Key design principle confirmed: system prompts are generic (the hardware); advice files inject model-specific knowledge (the software). Different model families get different advice files — no prompt changes needed.

**Deferred:** B.22 (memo validation failure → retry) moved to Phase C hardening. B.9 (protocol wiring) moved to pre-chain-run.

---

### Pre-chain-run — Workflow wiring for the 3-stage pipeline

Before the first real chain run with the 3-stage pipeline, the protocol
and workflow must carry the new fields to the proposal agent.

- ☑ B.9 Protocol: `local_full_context` now carries `expert_context`, `vocab_seed`, `reasoning_pipeline`, `human_advice`. Legacy `human_advice` wrapped into `ExpertContextItem(source="human")`. All params optional — 11 existing protocol tests pass unchanged. **Done**.
- ☑ Workflow: `_load_vocab_seed()` loads seed at start; `_get_reasoning_pipeline()` extracts pipeline from `ProposalLLMConfig`. Both passed through protocol to the agent. **Done**.

---

### Phase C — Vocabulary lifecycle + lineage verification

**Goal**: the vocabulary system becomes a living, accumulating knowledge base. Each round of the exploration loop runs the same pipeline; the vocabulary gets richer as records accumulate. Claimed inheritance is verified. Confirmed feature→capability links are promoted. The system learns what works and why.

**Depends on**: Phase B (the DiscoveryMemo is where `inherited_components` and `proposed_vocab_links` live).

**Core principle**: the pipeline is iterative and repeatable. Every round produces the same kinds of outputs (comparisons, links, predictions). The difference between round 1 and round 20 is the **accumulated memory** — more records, more candidates, more confirmed links, richer runtime vocabulary. Phase C builds the infrastructure for this accumulation. All tasks below contribute to a single repeatable loop; they are ordered by implementation priority, not by a rigid schedule.

Already done (in Phase B):
- ☑ C.1-seed: Vocab seed file (B.6a — 21 entries, human-reviewed).
- ☑ C.9: Prompt rendering of vocab (pipeline runner renders from `inp.vocab_seed`).
- ☑ C.8: Protocol carries `vocab_seed` (B.9 pre-chain-run wiring).

**Sub-tasks** (ordered by priority):

**Validator — verify claimed inheritance in code:**
- ☑ C.2 `_check_inherited_components()` — regex-matches each claimed component's pattern from the vocab seed against plugin source. Unknown entries soft-skipped. Case-insensitive. **Done** — `nodes/ml_code_validator_agent.py`.
- ☑ C.3 Wired as check #8 in the validator's `run()`. Only active when `inherited_components` is non-empty. Also added `inherited_components` to `ProposalOutput` (copied from DiscoveryMemo) and `ValidatorInput`. **Done**.
- ☑ C.10 9 unit tests: valid pass, missing fail, unknown skip, capability skip, empty list, mixed, no vocab, case insensitive, simple source fails. **Done** — `tests/unit/agent/ml_code_validator_agent/test_inheritance_check.py`.

**Chain test validated (end-to-end):**

The full pipeline was validated in a real chain test (`lilab_chain_v2`):
- 3-stage proposal pipeline produces `attn_wavenet` — inherits all 4 wavenet features, adds attention
- Implementor receives reference code from ancestor models as template
- Validator passes all 9 checks including inheritance verification
- Tuner runs successfully with trial mode

Key fixes discovered during chain testing:
- ☑ Validator gradient check: dead parameters → warning, not failure (common in residual architectures)
- ☑ Validator regex: `re.DOTALL` for cross-line pattern matching
- ☑ Validator LLM reviewer: standard engineering enhancements are acceptable deviations
- ☑ Proposal agent constructor: accepts `**kwargs` for ProposalLLMConfig per-stage kwargs
- ☑ Source code enrichment: comparison stage receives actual model source code, not just descriptions
- ☑ Reference code: implementor receives ancestor model code as template via `reference_code` field on `ImplementorInput`
- ☑ Generic prompts: model-specific knowledge removed from system prompts, moved to advice files
- ☑ Advice file: `advice/workflow/chain_v2_proposer_advice.json` — external model-specific knowledge for proposer + implementor

**Design principle confirmed**: system prompts are generic (the hardware); advice files inject model-specific knowledge (the software). Different model families get different advice files — no prompt changes needed.

**Pipeline hardening:**
- ☐ B.22 Memo validation failure → retry in the proposal agent. Deviation notes handling when Stage 3 flags inconsistencies.

---

### The vocabulary as memory — core design for C.4+

> **The vocabulary system is the agent's long-term memory.** It has three kinds of entries, each playing a different role:
>
> - **Features** (`kind="feature"`): concrete architectural building blocks the agent can point to in code. Short names. E.g. `dilated_causal_conv`, `multi_head_attention`.
> - **Capabilities** (`kind="capability"`): measurable architectural properties that features may provide. Short names. E.g. `receptive_field`, `frequency_resolution`.
> - **Discoveries** (`kind="discovery"`): empirical findings from experiments — sentences/phrases that capture what the agent has learned. These are the "valuable discoveries" that accumulate over iterations. E.g. `"WaveNet scores 5.57 overall with dominant high-freq performance (files 17-19 > 50k). No other model exceeds 4.3."`, `"Adding multi_head_attention to wavenet (attn_wavenet) did NOT improve low-freq scores (files 0-5 remained near zero). Attention alone does not solve the low-frequency gap."`
>
> Features and capabilities are short identifiers used as **constraint bridges** — they force the LLM to use consistent terminology. Discoveries are longer phrases that capture **what the agent has learned** from experiments. Together they form the agent's accumulated memory that grows over iterations.
>
> The interpretation agent produces a **structured lab report** that MUST reference vocabulary terms. It cannot say random things — it must map every finding to specific features, capabilities, and discoveries. This constrains the LLM's reasoning to be grounded in the maintained vocabulary.
>
> The proposal agent **maintains the vocabulary** — it proposes new candidates (features, capabilities, discoveries), proposes feature→capability links, and reviews what was confirmed or refuted. The interpretation agent **reads the vocabulary** and uses it to structure its analysis.

### Data flow for the vocabulary feedback loop

```
Long-term memory carried into iteration N (four Python variables in run_workflow):
  model_knowledge_cache : dict[model → {Phase 1 LLM text + _stats}]  (all models ever seen)
  runtime_vocab         : List[VocabEntry]  (seed + accumulated candidates + discoveries)
  previous_proposal     : Optional[dict]   (serialized ProposalOutput from iter N-1)
  latest_new_summary    : Optional[ModelRunSummary]  (just-tuned model this iter only)

─────────────────────────────────────────────────────────────────────
Iteration N:
─────────────────────────────────────────────────────────────────────

  Interpret(latest_new_summary, model_knowledge_cache, runtime_vocab, previous_proposal)

    Phase 1 — per-model summarization (cache-first, O(1) LLM calls/iter):
      Cache hit  → copy entry unchanged, 0 LLM calls
      Cache miss → 1 LLM call → build {LLM text + _stats}
        _stats contains: best_denoising_score, formal_score, worst_denoising_score,
                         best_file_vector, best_model_params, completed_rounds, best_config

    Phase 2 — cross-model synthesis (1 LLM call, skipped if only 1 model):
      Input: all models' Phase 1 text + per_model_best + per_model_formal
             + runtime_vocab injected as "established discoveries"
      Renders "Formal score: X (best above may be from a trial round)" when
      formal_score ≠ best_denoising_score for a cached model

    Phase C — vocabulary feedback (0 LLM calls, fully deterministic):
      evaluate_prediction()    → confirmed/refuted/partial using previous_proposal prediction
      generate_discoveries()   → uses max(stale_sota, overall_best_score) as baseline
      inject proposed_by_run   → sets proposed_by_run = previous_proposal["model_name"]
                                  on all vocab candidates (LLM never sets this itself)
      build_runtime_vocab()    → merges incoming + discoveries + candidates,
                                  extends seen_in_runs per candidate (no duplicates)
      promote_candidates()     → tier="candidate" + kind∈{feature,capability}
                                  + len(seen_in_runs) >= 3 → tier="canonical"
      _dedup_promoted()        → 1 LLM call per newly promoted entry (rare);
                                  synonym merged into existing canonical via aliases

    Produces: updated model_knowledge_cache, runtime_vocab, prediction_evaluation,
              new_discoveries, vocab_changes
    ↓

  Propose(InterpretationOutput, accumulated runtime_vocab)

    Pre-filter — two-tier context:
      Tier 1 (top-N by score): full source code + all metadata
                               → comparison LLM can borrow architectural ideas
      Tier 2 (remaining):      text-only (key_findings, bottlenecks, score_trend,
                               strategy_assessment, description — no source code)
                               → prevents re-proposing known-dead directions

    3-stage pipeline:
      Stage 1 Comparison   (1 LLM call): both tiers in context → ModelComparison list
                                         proposes new vocab candidates
      Stage 2 Reasoning    (1 LLM call): causal hypothesis + FalsifiablePrediction
      Stage 3 Proposing    (1 LLM call): ProposalOutput with model_name, baseline_config,
                                         proposed_vocab_candidates, falsifiable_prediction
    ↓

  Implement → Validate → Tune
    Produces: HyperparamTuningOutput (best_denoising_score, formal_score, file_vector, ...)
    ↓

  Update long-term memory:
    model_knowledge_cache = interpretation.model_knowledge_cache
    runtime_vocab         = interpretation.runtime_vocab
    previous_proposal     = proposal.model_dump()
    latest_new_summary    = tuning_output_to_model_run_summary(tune_output)
                            with .model_description = proposal.model_description
```

### Sub-tasks

**Vocabulary feedback loop — all done.** Three Python variables carry long-term memory between iterations: `model_knowledge_cache` (Phase 1 LLM text + `_stats` per model, written once per model ever), `runtime_vocab` (seed + accumulated candidates + discoveries), `previous_proposal` (serialized `ProposalOutput` from the prior iteration). The interpretation agent runs three phases per iteration: Phase 1 (per-model summarization, cache-first, O(1) new LLM calls), Phase 2 (cross-model synthesis with `runtime_vocab` as established context), Phase C (deterministic — evaluate prediction, generate discoveries, track `seen_in_runs`, promote, dedup). Protocol carries `runtime_vocab` from `InterpretationOutput` to `ProposalInput.vocab_seed`.

- ☐ **C.16** Vocabulary-constrained lab report — update interpretation agent prompt to require every finding to reference vocabulary terms. *(Deferred — current prompts work; this is a prompt quality improvement.)*

**O(1) LLM call count — done.** Separates raw archive (debug-only, never re-read) from long-term memory (fed to every iteration). Phase 1 called exactly once per model ever. Iterations 2+ make exactly 2 LLM calls (1 new Phase 1 + 1 Phase 2 synthesis), regardless of how many models exist in the cache.

**Promotion — done.** Feature/capability candidates flow separately from `kind="discovery"` entries. `promote_candidates()` fires when `len(seen_in_runs) >= 3` (count-only MVP; `require_positive_delta` deferred). `_dedup_promoted()` makes 1 LLM call per newly promoted entry to check for synonyms with existing canonicals.

**Post-implementation bugs fixed (2026-04-15):**

- ☑ **Bug 1 — `proposed_by_run` never injected.** The proposal LLM outputs candidates without `proposed_by_run`, so `seen_in_runs` was always `[]` — silently breaking the entire promotion pipeline. Fix: interpretation agent injects `proposed_by_run = previous_proposal["model_name"]` before calling `build_runtime_vocab`. 3 unit tests.

- ☑ **Bug 2 — stale SOTA in `generate_discoveries()`.** Discovery sentences used `prediction_eval["current_value"]` as the SOTA baseline, which could be outdated. Fix: `generate_discoveries()` accepts `overall_best_score` and uses `max(stale_sota, overall_best_score)`. 3 unit tests.

- ☑ **Bug 3 — `formal_score` missing from `_stats`.** Trial-mode `best_denoising_score` can exceed `formal_score`; after caching, Phase 2 synthesis could only see the inflated trial score. Fix: `formal_score` stored in `_stats` at cache-miss time; synthesis prompt shows "Formal score: X" warning when they differ. 5 unit tests.

**Centrifugal metrics (after promotion is working):**
- ✅ Vocabulary diversity metric — `vocab_diversity_ratio` computed post-Phase-C, carried into `resolve_exploration_mode()`. *(Concern #1)*
- ✅ Cumulative information gain — `cumulative_information_gain` accumulated per iteration, surfaced to Phase 2 synthesis prompt. *(Concern #2)*
- ☐ Component delta scoring. *(Concern #4)*
- ☐ Strategy Performance Report. *(Feedback loop)*

**Pipeline hardening (can be done in parallel):**
- ☑ B.22 Memo validation failure → retry. Stages 1+2 not re-run; error injected into `accumulated["proposing_stage_errors"]` so the LLM sees its own mistake; up to 3 total attempts. **Done** — `nodes/ml_model_proposal_agent.py`.

**Verify**:
- ✅ **Automated (pseudo mode)**: `test_vocab_grows_across_two_iterations` in `tests/integration/workflows/test_vocab_accumulation.py` (@dual_mode, Phase 4 of `docs/pseudo_test_infra.md`). Verifies: `runtime_vocab` grows monotonically across two iterations (iter1=2 entries → iter2=4), no entries dropped, REFUTED/CONFIRMED discoveries generated correctly, protocol maps discoveries into `vocab_seed`. Passes in pseudo mode (0.2s) and real-LLM mode (73s).
- ✅ **Automated (pseudo mode)**: `test_vocab_candidate_promotion_across_three_iterations` in `tests/integration/workflows/test_vocab_accumulation.py` (@dual_mode, PR #43/#44). Verifies the full promotion pipeline across 3 iterations using fake `ModelRunSummary` objects (no GPU). Asserts: `spectral_gating` accumulates `seen_in_runs` correctly across iterations (1→2→3), `promote_candidates()` fires at count=3, `_dedup_promoted()` runs and keeps the entry, `tier` flips to `"canonical"`, and `vocab_changes` logs the event. Cache hits in iter 2/3 confirm O(1) new LLM calls per iteration.
- ☐ **Manual (real chain)**: Run 2+ real chain iterations. Check that the proposal agent's reasoning prompt references discovery entries from the previous round — i.e., that the LLM actually uses the accumulated vocabulary to constrain its proposals (not currently testable deterministically).

---

### Phase E — Falsifiable prediction retrospective + scientific accuracy metric ✅

**Goal**: every prediction made in `DiscoveryMemo.falsifiable_prediction` gets checked against actual results; the agent's hit rate becomes a measurable, monitorable quantity.

**Depends on**: Phase B (FalsifiablePrediction lives in DiscoveryMemo). Phase A dependency removed (reverted).

**Architecture note**: evaluation lives in `result_interpretation_agent`, not `ml_hyperparameter_tune_agent`. This is cleaner — the interpretation agent already holds `previous_proposal` (the prediction) and all the actual scores, so no data needs to be threaded into the tuning agent. `prediction_outcome` is **not** on `ExperimentRecord`; it lives in `InterpretationOutput.prediction_evaluation`.

**Files changed**:
- `nodes/interpretation_helpers.py` — `evaluate_prediction()` rewritten (SOTA-based, not predicted-value-based); new `update_vocab_link_confirmations()` helper.
- `nodes/result_interpretation_agent.py` — wires both E.4 and E.7 after `promote_candidates`; prints scientific accuracy and link promotion events.
- `agent/schemas/interpretation.py` — new fields on `InterpretationInput`: `prediction_outcomes_history`, `vocab_link_confirmations`; new fields on `InterpretationOutput`: `scientific_accuracy`, `prediction_outcomes_history`, `vocab_link_confirmations`.
- `tests/unit/agent/result_interpretation_agent/test_vocab_feedback.py` — `TestEvaluatePrediction` fully rewritten (15 tests); `TestUpdateVocabLinkConfirmations` added (12 tests). 61 tests total.

**Design changes from original plan**:
- `evaluate_prediction()` baseline changed from `predicted_value` to `current_sota` (= `FalsifiablePrediction.current_value`, the SOTA at proposal time). LLMs cannot reliably predict exact scores; the meaningful question is whether the model beat the bar it was designed to beat.
- Outcome labels (preset, never LLM-generated): `confirmed` (actual > SOTA), `partial` (within 5% margin below SOTA), `refuted` (clearly below SOTA). The 5% margin acknowledges near-competitive results.
- `ProposedVocabLink` confirmation uses the **prediction outcome as a proxy**: when a run is `confirmed`, all proposed links from that run gain one confirmation count. Links confirmed in ≥ `min_runs_for_promotion` (default 3) distinct runs are promoted to `VocabEntry.related_to`.

**Sub-tasks**:
- ☑ E.1 `evaluate_prediction()` rewritten — SOTA-based comparison, `delta_from_sota` output key.
- ☑ E.2 Call site wired: `sota_at_proposal = prev_prediction.get("current_value")`; print shows `delta_from_sota`.
- ☑ E.3 Schema description updated; `prediction_evaluation` field documents new keys.
- ☑ E.4 `scientific_accuracy` + `prediction_outcomes_history` carry-forward in interpretation agent.
- ☑ E.5 Unit tests: 15 tests for `evaluate_prediction`, 12 for `update_vocab_link_confirmations`.
- ☑ E.7 `update_vocab_link_confirmations()` — confirmation tracking, `VocabEntry.related_to` promotion, immutability guarantee.

**Verify**:
- ✅ `uv run pytest tests/unit/agent/result_interpretation_agent/test_vocab_feedback.py -q` — 61 passed.
- ✅ `uv run pytest tests/unit/ -q` — 939 passed, 0 failures.
- ✅ H.4 pseudo mode: `uv run pytest tests/integration/workflows/test_vocab_accumulation.py::test_scientific_accuracy_and_vocab_links_accumulate -v -s` — REFUTED iter produces `scientific_accuracy={"confirmed": 0.0, "refuted": 1.0}`; CONFIRMED iter updates to `{"confirmed": 0.5, "refuted": 0.5}`; `vocab_link_confirmations={"dilated_causal_conv:receptive_field": ["spectral_net"]}` after 1 confirmation (not yet promoted, threshold=3).
- ✅ H.4 real-LLM: `uv run pytest tests/integration/workflows/test_vocab_accumulation.py::test_scientific_accuracy_and_vocab_links_accumulate -v -s --real-llm` — PASSED (2m04s, Gemini 2.5 Flash). Iter 1 REFUTED: `delta_from_sota=-7.085`, `scientific_accuracy={"confirmed":0.0,"refuted":1.0}`, no link added. Iter 2 CONFIRMED: `delta_from_sota=0.524`, `scientific_accuracy={"confirmed":0.5,"refuted":0.5}`, `vocab_link_confirmations={"dilated_causal_conv:receptive_field":["spectral_net"]}`.

---

---

### Phase F — Receptive-side external agent readiness ✅

**Goal**: make the proposal agent fully ready to *accept* external upstream agents without any further changes to its node, prompts, or schemas. After Phase F, wiring a new external agent = write its output schema + one protocol file. Nothing else changes.

**Scope clarification — what Phase F is and is NOT**:

Phase F is **infrastructure only**. It prepares the proposal agent's receiving end.
No external agent is built here — those come in later phases.
The new channels (`agent_cards`, `mindset`, `origin`) are fully wired but carry no data yet
in production runs: `agent_cards=[]` (default), `mindset=None` (default), `origin=None` (default).
All existing runs are unaffected — every new field is backward-compatible with a sensible default.

| What Phase F does | What Phase F does NOT do |
|---|---|
| `AgentCard` schema + `ProposalInput.agent_cards` field | Build `ml_literature_review` agent |
| `VocabEntry.origin` field | Build `physics_literature_review` agent |
| `render_agent_cards()` renderer | Write any protocol file for a new agent |
| `render_expert_context()` dedup + confidence sort | Trigger any external agent from a workflow |
| Contributors instruction in stage prompts | Validate that external context reaches the LLM |
| `local_full_context` accepts `mindset` + `agent_cards` | |

The first real test of these channels will be in the phase that implements `ml_literature_review`
(see `docs/external_agents_for_proposer.md` §2.1).

**Depends on**: Phase B (ExpertContextItem, ProposalInput schemas in place).

**PR size**: small.

**Files changed**:
- `agent/schemas/proposal.py` — new `AgentCard` schema; `VocabEntry.origin` field; `ProposalInput.agent_cards` field.
- `agent/prompt_templates/proposal/__init__.py` — new `render_agent_cards()`; updated `render_expert_context()` (dedup by `cite_id`, sort by `confidence` desc).
- `agent/prompt_templates/proposal/comparison_stage.md` — "Contributors" instruction in "What you receive".
- `agent/prompt_templates/proposal/causal_reasoning_stage.md` — same.
- `nodes/ml_model_proposal_agent.py` — inject `agent_cards_block` before `expert_context_block` in both per-stage and proposing-stage user prompts.
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — `mindset` and `agent_cards` params added to `local_full_context`.
- `tests/unit/agent/ml_model_proposal_agent/test_agent_cards.py` (new, 26 tests).

**Sub-tasks**:
- ☑ F.1 Add `AgentCard` schema to `agent/schemas/proposal.py`.
- ☑ F.2 Add `ProposalInput.agent_cards: List[AgentCard] = []`.
- ☑ F.3 Add `VocabEntry.origin: Optional[str] = None`.
- ☑ F.4 Implement `render_agent_cards()` — returns empty string when `agent_cards` is empty (no noise in single-agent runs).
- ☑ F.5 Update `render_expert_context()`: (a) deduplicate by `cite_id` before grouping; (b) sort each group by `confidence` descending, `None` last.
- ☑ F.6 Inject `agent_cards_block` in `_run_pipeline()` before `expert_context_block`.
- ☑ F.7 Add contributor instruction block to `comparison_stage.md` and `causal_reasoning_stage.md`.
- ☑ F.8 Add `mindset` and `agent_cards` parameters to `local_full_context` in the protocol file.
- ☑ F.9 Unit tests: 26 tests covering all new schema fields, both renderers, dedup, confidence sorting, and protocol pass-through.

**Verify**:
- ✅ `uv run pytest tests/unit/agent/ml_model_proposal_agent/test_agent_cards.py -v` — 26 passed.
- ✅ `uv run pytest tests/unit/ -q` — 977 passed, 0 failures.

**What comes next** (not Phase F):
- Implement `ml_literature_review` node — follows the 8-step node checklist in CLAUDE.md.
  See `docs/external_agents_for_proposer.md` §2.1 for full spec (schema, protocol, trigger conditions).
- Implement `physics_literature_review` node — see §2.2 in the same doc.
- Both agents will be the first real test of the `AgentCard` + `agent_cards` channel.

---

### Cross-phase verification gates

After each phase ships and is committed:

1. **Full unit suite green**: `uv run pytest tests/unit/ -q` — all 700+ tests still pass.
2. **Singleton invariant intact**: `uv run pytest tests/unit/agent/test_llm_bridge_singleton.py -q` — no rogue `OpenAI()` constructors.
3. **Tier-1 integration smoke**: at least one real-LLM Tier-1 test passes for the affected node.
4. **Backward compatibility**: at least one tuner run with no new fields populated (legacy path) completes successfully.
5. **No invariant violation**: no new sidecar markdown files, no new shared mutable state files, no inter-node communication that bypasses protocols.

After **all six phases** ship, run the Tier-3 chain test as a final verification:
```bash
uv run pytest -m real_run -v -s \
    tests/integration/workflows/test_full_exploration_loop.py::TestFullExplorationLoop::test_chained_iterations
```
This exercises the full proposal → implement → validate → tune loop with the new reasoning machinery and citation tracking end-to-end.

---

---

## 5. Critical concern: prompt scalability and LLM attention drift

### The problem

As the exploration loop runs for N iterations, naive implementations will accumulate unbounded context:
- Raw experiment records: N iterations × 5 rounds × ~3KB each → **150KB+ after 10 iterations**
- Model descriptions and source code: grows with each new agent-generated model
- Vocabulary: grows with candidates and discoveries

When the prompt exceeds ~30-50K tokens, two things happen:
1. **Cost**: each LLM call becomes expensive (billed per input token)
2. **Attention drift**: the LLM's ability to attend to specific details degrades with prompt length. Critical information (the SOTA score, the vocabulary constraints, the prediction to evaluate) gets lost in a sea of historical records. This is the "lost in the middle" problem — LLMs attend strongly to the beginning and end of the prompt but poorly to the middle.

### The solution: vocabulary IS compressed memory

The vocabulary system IS the compression mechanism. The interpretation agent does NOT re-read all raw records every iteration.

**Core assumption: iterations 0 through N-2 are fully summarized in the vocabulary.**

The vocabulary (features + capabilities + discoveries) is the compressed representation of everything the agent has learned from all previous experiments. If the vocabulary is good, you don't need the raw records — the vocabulary tells you what works, what doesn't, and why.

This means:
- Iteration N's interpretation agent receives: **vocabulary (memory of 0..N-2) + new records (iteration N-1 only) + previous proposal (to evaluate)**
- It does NOT receive raw records from iterations 0..N-2
- Everything worth knowing from those iterations is already in the vocabulary — especially `kind="discovery"` entries which capture empirical findings as sentences

**What the interpretation agent receives each round:**

| Input | Size | Grows? | Purpose |
|-------|------|--------|---------|
| Runtime vocabulary (features + capabilities + discoveries) | ~10KB | Slowly (bounded) | Compressed memory of iterations 0..N-2 |
| New records (from iter N-1 tuning only) | ~5-15KB | No — fixed per iteration | What happened in the latest experiment |
| Previous proposal (`ProposalOutput` with prediction + links) | ~3KB | No — one per iteration | What was predicted, to evaluate against results |

**Total prompt: ~20-30KB per iteration**, regardless of how many iterations have run.

Each round, the interpretation agent:
1. Reads the vocabulary (compressed memory of all previous iterations)
2. Reads the latest experiment data (iteration N-1 only)
3. Evaluates the previous prediction (confirmed/refuted?)
4. Produces new discovery entries (what we just learned)
5. Updates the runtime vocabulary (existing + new discoveries)

### Critical dependency: vocabulary quality determines memory fidelity

> **This design only works if the vocabulary faithfully represents what we've learned.** If important findings are lost during compression (not captured as discoveries, or captured imprecisely), the agent loses information across iterations and may repeat failed experiments.
>
> This creates a **co-evolution requirement** between two capabilities:
>
> **Vocabulary extraction** (interpretation agent): how well do we capture findings from each experiment as vocabulary entries? If the interpretation agent misses a critical finding (e.g., "attention doesn't help low-freq"), that knowledge is lost forever — it won't be in the vocabulary for the next round.
>
> **Vocabulary usage** (proposal agent): how well does the proposal agent use the vocabulary to constrain its reasoning? If it ignores discoveries, then even perfect extraction is wasted.
>
> **Both must improve together** — improving extraction without improving usage is wasted work, and vice versa. In practice:
>
> 1. **Start simple**: first implementation captures basic discoveries (prediction confirmed/refuted, which features were used, what scores resulted). Good enough for the first 5-10 iterations.
> 2. **Improve extraction when we see memory loss**: if the agent repeats a failed experiment, the discovery for that failure was either missing or poorly worded. Fix the interpretation prompt.
> 3. **Improve usage when we see drift**: if the proposal agent ignores discoveries in its reasoning, strengthen the vocabulary constraint in the comparison/reasoning stage prompts.
> 4. **Alternate improvements**: each chain batch reveals whether the bottleneck is extraction (agent doesn't capture the right findings) or usage (agent captures findings but ignores them). Fix the weaker link first, then switch to the other.
>
> **This is NOT a one-time implementation** — it's an ongoing quality improvement loop that runs in parallel with the experiment loop itself. The vocabulary system gets better as we tune its prompts, just like the ML models get better as we tune their hyperparameters.

### Two-layer persistence design

**Layer 1 — Raw archive (debug only, never re-read).** Each node writes its full output to disk per iteration for human inspection and crash recovery. The agent never reads these files in the hot path.

**Layer 2 — Long-term memory (fed to every iteration, O(1) size).** Three Python variables:

| Variable | Content | Update rule |
|----------|---------|-------------|
| `model_knowledge_cache` | Per-model Phase 1 LLM text + `_stats` (scores, file_vector, params) | Once per model, ever |
| `runtime_vocab` | Growing list of typed discoveries | Every iteration (append only) |
| `previous_proposal` | Latest `ProposalOutput` dict | Every iteration (replace) |

**What flows into each LLM call per iteration (N > 1):**

| LLM call | Receives |
|----------|---------|
| Phase 1 (new model only, 1 call) | New model's `ModelRunSummary` + description |
| Phase 2 — synthesis (1 call) | All models' Phase 1 text (cache + new) + all `_stats` + **`runtime_vocab`** |
| Proposer reasoning + commit (2–3 calls) | Full `InterpretationOutput` + `runtime_vocab` |

`runtime_vocab` goes to **both Phase 2 and the proposer** so they share the same knowledge base. `previous_proposal` is evaluated deterministically → generates a discovery → enters `runtime_vocab`.

**Result: O(1) LLM calls per iteration**, independent of history depth. Iter 1 builds the cache (N_seed Phase 1 calls + 1 synthesis). Every subsequent iteration: exactly 1 Phase 1 call + 1 Phase 2 synthesis.

### How vocabulary bounds the growth

- **Features and capabilities**: bounded by the promotion rules. Most candidates never get promoted. The canonical seed stays at ~20 entries. Candidates churn — new ones appear, unused ones fade. Total stays ~30-50 entries.
- **Discoveries**: the most growth-prone kind. Each iteration may add 1-3 discoveries. After 20 iterations: ~40-60 discoveries. At ~100 chars each: ~5-6KB. Manageable.
- **If discoveries grow too large**: the interpretation agent can **summarize** older discoveries into higher-level findings. E.g., 5 individual "attention didn't help X" discoveries → 1 summary discovery "Attention mechanisms have not improved low-frequency performance across 5 experiments." This is a future concern, not immediate.

### Proposal agent prompt budget

The proposal agent receives even more context (comparison stage gets source code). Budget:

| Input | Size | Notes |
|-------|------|-------|
| Candidate models (top N, with source code) | ~15-20KB | Bounded by ModelSelectionStrategy.top_n |
| Runtime vocabulary | ~10KB | Same as interpretation |
| Expert context (advice + strategy report) | ~5KB | Fixed |
| Accumulated pipeline stages (comparison + reasoning) | ~5-10KB | Fixed per pipeline run |

**Total: ~15-25KB per proposal at the n=5 default** (lowered from n=10 in Phase 5 E of `docs/aggregated_score_table_awareness.md` once full `rendered_markdown` tables started being embedded). Measured baseline: **13 513 chars ≈ 3 378 tokens** for the full 5-candidate pipeline-stage user prompt. The source code + rendered score tables are the biggest costs, both controlled by the `top_n` pre-filter. Experiments that want more history can bump `n_candidates` via `run_workflow` / `_get_reasoning_pipeline` without touching the schema; if we routinely push ≥10 models we should either truncate source code or only include code for the SOTA + the model being modified.

### Design rules to prevent prompt explosion

1. **Every step makes O(1) LLM calls, independent of iteration count.** The interpretation agent caches per-model Phase 1 summaries (C.19a) and only calls the LLM for new models. The vocabulary/discovery pipeline already runs O(1) calls. The proposal agent's pipeline is fixed at 3 calls. No stage should grow call count with history depth.
2. **The vocabulary is the memory.** Everything worth remembering is in the vocabulary (features, capabilities, discoveries). If it's not in the vocabulary, it's not remembered. `runtime_vocab` is fed to both Phase 2 (synthesis) and the proposer so both are on the same knowledge base — Phase 2 confirms/contradicts established discoveries; the proposer uses them to constrain its reasoning.
3. **Source code is pre-filtered.** Only top N models get their source code included. The `ModelSelectionStrategy` controls this budget.
4. **Discoveries can be summarized.** If the discovery list grows beyond ~50 entries, the interpretation agent consolidates older ones into summaries.
5. **Each agent has a token budget.** The pipeline runner should estimate prompt size before calling the LLM and warn if it exceeds a threshold (e.g., 40K tokens).

---

## 8. Centrifugal concerns — implementation status

These five concerns apply across all phases of the system lifecycle.
See §2A "Centrifugal forces" for the full design rationale of each.

| Concern | Risk | Mitigation | Status |
|---------|------|------------|--------|
| **#1 — Innovation Stagnation** | Vocabulary safe harbor: LLM reuses only canonical terms, never proposes new features. | `vocab_diversity_ratio` = n_candidates / n_feature_capability_total. Below `policy.vocab_stagnation_threshold` (default 0.1) → `resolve_exploration_mode()` forces `"explore"`. Ratio surfaced to Phase 2 synthesis prompt with `[LOW]` annotation. | ✅ Done — `interpretation_helpers.compute_vocab_diversity_ratio`, `InterpretationOutput.vocab_diversity_ratio`, `proposal_helpers.resolve_exploration_mode`. |
| **#2 — Predictive Risk Aversion** | `FalsifiablePrediction` grading incentivizes trivially safe predictions to maximize hit rate. | `boldness` property on `FalsifiablePrediction` (`abs(predicted−current)/current`). `information_gain = boldness × (1 if confirmed else 0)` per iteration. `cumulative_information_gain` accumulated across iterations and shown to Phase 2 synthesis LLM. `minimum_boldness` threshold (schema validator, default 0.05). | ✅ Done — `evaluate_prediction()` computes info gain per round; `InterpretationInput.cumulative_information_gain` carries it forward; `InterpretationOutput.cumulative_information_gain` stores the running total. |
| **#3 — Error Propagation** | Stage 3 implements Stage 1 hallucinations. | `ProposalOutput.memo_consistency_notes` — Stage 3 flags inconsistencies between DiscoveryMemo and implementability. Validator surfaces as warnings (not veto). Experiment is the primary error-corrector. | ✅ Done (Phase B) — schema field exists, validator surfaces it. |
| **#4 — Promotion Spuriousness** | Vocab entry promoted because it co-occurred with high scores, not caused them. | Component delta: `avg_score_with − avg_score_without`. Requires ablation runs where the component is absent. `require_positive_delta` flag in `ResearchPolicy` (default True, deferred until ablation data exists). | ☐ Deferred — `require_positive_delta` field exists in schema but is not yet enforced in `promote_candidates()`. Needs ablation run data. |
| **#5 — Citation Pollution** | LLM cites every `ExpertContextItem` to appear rigorous. | `DiscoveryMemo.citation_sources` capped at `max_length=5`. Validator: each cited `cite_id` must appear verbatim in `causal_hypothesis` or `proposed_change`. | ✅ Done (Phase B) — schema cap + validator check implemented. |

---

## 9. Possible future development — `ResearchDirective` guided mode

**Why deferred**: the `mindset: Optional[str]` field on `ProposalInput` (Phase F) already covers the prompt-layer use case. Writing `mindset = "Deep-dive on WaveNet — all proposals must be WaveNet variants"` injects that instruction into the causal reasoning stage system prompt. For current usage this is sufficient. The extra structural layers below are only warranted if LLM drift is observed in practice during focused deep-dive experiments.

**What `mindset` does not cover** (the value of a future `ResearchDirective`):

| Layer | Mechanism | Covered by `mindset`? |
|---|---|---|
| 1 — Prompt | `[GUIDED MODE DIRECTIVE]` block in system prompt | ✅ `mindset` already does this |
| 2 — Memo anchor | Python code **forces** `DiscoveryMemo.sota_model_type = base_model` before the LLM call — the LLM cannot choose a different anchor | ✗ |
| 3 — Validator | Hard code checks: `check_base_model_inheritance` (plugin must inherit from base) and `check_forbidden_components` (regex rejects forbidden patterns in source code) | ✗ |

**Design** (from §2C, preserved here for reference):

```python
class ResearchDirective(BaseModel):
    mode: Literal["autonomous", "guided"] = "autonomous"
    base_model: Optional[str] = None        # e.g. "wavenet"
    target_components: List[str] = []       # must appear in inherited_components
    forbidden_components: List[str] = []    # e.g. ["attention"] → regex-rejected in code
    rationale: Optional[str] = None
```

Attach as `ProposalInput.research_directive` (default = autonomous, fully backward compatible).

**When to implement**: when focused deep-dive experiments are planned and the team has observed the LLM ignoring `mindset`-level guidance. Until then, `mindset` is the right tool.

**Estimated effort**: medium (new schema, memo override logic in proposal agent, two new validator checks, unit + integration tests).
