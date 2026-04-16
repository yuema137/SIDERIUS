# External Agents for the Proposal Pipeline

**Status**: Design only — no implementation started. The proposal agent's receiving end is mostly ready; the gaps and prerequisites described here must be fixed before any external agent is wired.

---

## §1 Context

The proposal agent (`ml_model_proposal_agent`) already supports four incoming channels via its `ProposalInput` schema:

| Channel | Schema field | What it carries |
|---------|-------------|-----------------|
| Agent identification | `agent_cards: List[AgentCard]` | Who is contributing, their expertise, and how to weight them *(field to be added — see §8)* |
| Factual findings | `expert_context: List[ExpertContextItem]` | Per-iteration findings with source, kind, confidence, cite_id |
| New terminology | `vocab_seed: List[VocabEntry]` | Vocabulary candidates from external sources |
| Strategic direction | `mindset: Optional[str]` | Free-text injected into the causal reasoning prompt |

The proposal agent consumes all four uniformly, regardless of which agent produced them. Adding a new upstream agent requires zero changes to the proposal agent's reasoning logic — only an output schema, a protocol file, and an `AgentCard` definition per directed edge.

---

## §2 Agents to build

### 2.1 `ml_literature_review`

**Purpose**: mine ML papers for architectural techniques relevant to SQUID denoising. Translates paper findings into the four channels above.

**Data sources**:
- Semantic Scholar API — structured paper metadata, citation graphs, abstracts
- OpenReview API — ICLR/NeurIPS/ICML full papers and reviews

**Module prefix**: `ml_` (machine learning pipeline — this agent directly informs architectural decisions).

**Output schema** (`agent/schemas/ml_literature_review.py`):

```python
class MLLiteratureReviewOutput(BaseModel):
    agent_card: AgentCard
    # Static self-description — defined once in the agent, passed through every run.
    # Example:
    #   AgentCard(
    #     agent_name="ml_literature_review",
    #     role="Scans ML papers for architectural techniques applicable to SQUID denoising",
    #     expertise_domain="Signal processing architectures, deep learning for time-series",
    #     coverage="arXiv + OpenReview 2018–present, filtered by relevance to SQUID/denoising",
    #     limitations="Cannot assess physics feasibility; benchmarks may not transfer to TIDMAD",
    #     trust_guidance="Treat as promising priors — lower exploration cost, but only "
    #                    "experiment runs confirm applicability.",
    #   )

    findings: List[ExpertContextItem]
    # kind="literature" entries: paper-specific findings with cite_id=arxiv/openreview ID
    # Example: "Gated spectral convolution achieves 15% improvement on 1-10 kHz SQUID
    #   signals. cite_id=arxiv_2024_1234"

    new_vocab_candidates: List[VocabEntry]
    # Terms recognized in papers that aren't in the current vocab.
    # Each entry: kind="feature"/"capability", origin="ml_literature_review",
    #             proposed_by_run=None (NOT set — not an experiment run).
    # Example: VocabEntry(name="learnable_filterbank", kind="feature",
    #                     origin="ml_literature_review", ...)

    suggested_mindset: Optional[str]
    # Only populated when ≥N papers converge strongly on a direction.
    # Example: "5 recent papers use dilated causal conv + spectral normalization for
    #   low-SNR signal recovery — prioritize this combination."
```

**Protocol file**: `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`

The protocol extracts `agent_card` into `ProposalInput.agent_cards`, merges `findings` into the workflow's accumulated `expert_context` list, extends the `vocab_seed` with `new_vocab_candidates` (setting `origin` correctly), and optionally maps `suggested_mindset` to `ProposalInput.mindset`.

**Node code** (for protocol file naming): `ml_lit_review`

---

### 2.2 `physics_literature_review`

**Purpose**: read physics papers on SQUID/dark matter detection to extract hard physical constraints and domain knowledge that the ML literature would never contain.

**Data sources**:
- arXiv `hep-ex`, `cond-mat.supr-con`, `astro-ph.IM` categories
- Domain-specific databases (e.g. INSPIRE-HEP)
- Possibly a curated local corpus of key SQUID papers

**Module prefix**: `phys_` — this agent belongs to a physics domain module, not the ML pipeline. A new prefix is warranted here (analogous to `data_` for data processing). First agent with this prefix; establishes the convention.

**Output schema** (`agent/schemas/phys_literature_review.py`):

```python
class PhysicsLiteratureReviewOutput(BaseModel):
    agent_card: AgentCard
    # Static self-description — defined once in the agent.
    # Example:
    #   AgentCard(
    #     agent_name="physics_literature_review",
    #     role="Extracts physical constraints on SQUID systems from physics literature",
    #     expertise_domain="SQUID magnetometry, dark matter detection, superconducting circuits",
    #     coverage="Physics papers on SQUID/axion detection; curated local corpus + arXiv",
    #     limitations="Does not evaluate ML feasibility; constraint values assume ideal conditions",
    #     trust_guidance="Physical constraints are HARD LIMITS — do not override without "
    #                    "explicit physics justification. Domain knowledge is HIGH confidence.",
    #   )

    findings: List[ExpertContextItem]
    # kind="theoretical" entries: physics constraints and domain knowledge
    # Example: "Axion-photon coupling implies signal amplitude 10⁻¹⁸–10⁻¹⁵ V/Hz^0.5
    #   at 1–100 kHz. cite_id=phys_review_2023_axion"

    new_vocab_candidates: List[VocabEntry]
    # Physics-derived concepts that should enter the architectural vocabulary.
    # Example: VocabEntry(name="thermal_noise_floor", kind="capability",
    #                     origin="physics_literature_review",
    #                     description="Physical lower bound on noise achievable for SQUID at T=4K")

    suggested_mindset: Optional[str]
    # Rarely populated — only for strong domain invariants.
    # Example: "SQUID signal is strictly causal and band-limited below 500 kHz —
    #   any architecture with non-causal ops or global frequency mixing will fail."
```

**Protocol file**: `agent/schemas/protocols/phys_literature_review_to_ml_model_propose.py`

**Node code**: `phys_lit_review`

---

## §3 Protocol gap to fix before wiring

`local_full_context` (in `ml_result_interp_to_ml_model_propose.py`) currently has no `mindset` or `agent_cards` parameters. When external agents are wired in, the workflow needs to pass both through to `ProposalInput`.

**Changes required**:
- Add `mindset: Optional[str] = None` parameter — map to `ProposalInput.mindset`.
- Add `agent_cards: Optional[List[AgentCard]] = None` parameter — map to `ProposalInput.agent_cards`.

Both are one-line additions, backward compatible (default `None`).

---

## §4 Trigger conditions

Literature review agents are expensive (API calls, paper parsing). They should not run every iteration.

| Agent | When to call |
|-------|-------------|
| `physics_literature_review` | **Once at exploration start**, then cached. Physical constraints on SQUID systems do not change between iterations. |
| `ml_literature_review` | **Triggered conditionally** — when `vocab_diversity_ratio` drops below threshold (vocabulary stagnation) or when `cumulative_information_gain` is low for N consecutive iterations. Both signals are already computed and present in `InterpretationOutput`. |

The workflow checks these signals after each interpretation run and triggers a fresh literature scan when the condition is met, rather than running every round.

---

## §5 Multi-source merging

When both `result_interpretation_agent` and one or more external agents produce context, the workflow aggregates all four channels before calling the protocol.

```
workflow:
  # Findings
  interp_items   = [... from result_interpretation_agent ...]
  ml_lit_items   = [... from ml_literature_review ...]   # if triggered
  phys_items     = [... from physics_literature_review ...]  # if triggered
  all_context    = interp_items + ml_lit_items + phys_items

  # Vocabulary
  merged_vocab   = vocab from interp_output + ml_lit_candidates + phys_candidates
  # (each external candidate has origin= set, proposed_by_run=None)

  # Name cards
  all_cards      = [ml_lit_output.agent_card, phys_output.agent_card]  # if triggered

  # Mindset: last non-None value wins (physics > ml_lit > default)
  mindset        = phys_output.suggested_mindset or ml_lit_output.suggested_mindset or None

  proposal_input = local_full_context(interp_output, storage,
                                      expert_context=all_context,
                                      vocab_seed=merged_vocab,
                                      agent_cards=all_cards,
                                      mindset=mindset)
```

Merging is the workflow's responsibility. The protocol just passes the already-merged inputs through.

---

## §6 Implementation checklist (per agent)

Both agents follow the standard 8-step node checklist from `CLAUDE.md`. For reference:

| Step | Artefact |
|------|----------|
| 0 | Graph placement — draw edges `ml_lit_review → ml_model_propose` and `phys_lit_review → ml_model_propose` |
| 1 | Node implementation: `nodes/ml_literature_review.py` / `nodes/physics_literature_review.py` |
| 2 | Protocol files (one per directed edge): `ml_literature_review_to_ml_model_propose.py`, `phys_literature_review_to_ml_model_propose.py` |
| 3 | Node unit tests (mocked API calls) |
| 4 | Protocol unit tests |
| 5 | Node integration test (Tier 1 — real API, one node in isolation) |
| 6 | Protocol integration test (Tier 2 — real API, literature agent → proposal agent) |
| 7 | Connection audit — verify `AgentCard` fields populated, every `ExpertContextItem` has `source`/`cite_id`, vocab candidates have `origin` set and `proposed_by_run=None` |

Prerequisites before either agent is wired (all in §8–§9):
- `AgentCard` schema added to `agent/schemas/proposal.py`
- `ProposalInput.agent_cards` field added
- `render_agent_cards()` implemented in `agent/prompt_templates/proposal/__init__.py`
- System prompt instructions updated (comparison + causal reasoning stages)
- `VocabEntry.origin` field added
- `render_expert_context` dedup + confidence sorting added

---

## §7 Open questions

1. **`physical_constraint` as a new `ExpertContextItem.kind`?** Physics constraints (e.g. causality, band limits) are qualitatively different from theoretical findings — they cannot be overridden. Should `ExpertContextItem.kind` have a `physical_constraint` value, and should the proposal agent treat these as hard filters rather than soft guidance? The `trust_guidance` field in `AgentCard` partially handles this, but a distinct `kind` would make it structural rather than advisory.

2. **Caching strategy for physics agent**: run-level JSON file in workspace? Or a shared file in `agent_generated/physics_context/` that persists across runs within an experiment?

3. **Paper corpus for physics agent**: live arXiv API calls per trigger, or a curated local corpus updated periodically? Local corpus is more reproducible but requires maintenance.

4. **Semantic Scholar rate limits**: the free tier allows 100 requests/5 minutes. The ML literature agent must paginate carefully and cache results to avoid quota exhaustion across long chains.

5. **System prompt update scope**: should the name card section and the instruction to read it go into the base system prompt (all runs see it) or only when `agent_cards` is non-empty? Rendering conditionally (only when cards are present) is cleaner — no noise in single-agent runs.

---

## §8 Agent name cards

### The problem

Without a name card, the proposal LLM sees `source="ml_literature_review"` on ten `ExpertContextItem` entries but has no idea what that source is — whether it represents a systematic review or a keyword search, whether its domain matches this task, and how much to trust it relative to empirical experiment results. The `kind` field alone (`"literature"`, `"theoretical"`) is not enough: it describes the *type* of finding, not the *epistemic status* of the agent that produced it.

### What a name card is

A name card is the agent's **static self-description** — defined once in the agent, passed through its output schema on every run. It tells the proposal LLM:
- What this agent is and what it does
- What domain it covers and how current its knowledge is
- What it cannot know or do (limitations)
- How to calibrate trust in its findings

The key principle: **findings are the evidence; the name card is the calibration**. The LLM reads the name cards *before* reading the `ExpertContextItem` list, so it knows how to weight each source before it encounters any specific claim.

### `AgentCard` schema

New schema to add to `agent/schemas/proposal.py`:

```python
class AgentCard(BaseModel):
    """Static self-description of an external contributing agent.

    Defined once in the agent's implementation, emitted on every run.
    Collected into ProposalInput.agent_cards and rendered as a 'Contributors'
    section near the top of each stage prompt — before the Expert Context block.
    """
    agent_name: str = Field(
        description="Stable identifier matching ExpertContextItem.source values "
                    "this agent produces. E.g. 'ml_literature_review'."
    )
    role: str = Field(
        max_length=200,
        description="One sentence: what this agent does in the pipeline."
    )
    expertise_domain: str = Field(
        max_length=300,
        description="What this agent knows well — the domain its findings are grounded in."
    )
    coverage: str = Field(
        max_length=300,
        description="Scope of its knowledge: time range, data sources, filtering criteria."
    )
    limitations: str = Field(
        max_length=300,
        description="What this agent cannot assess or may get wrong."
    )
    trust_guidance: str = Field(
        max_length=400,
        description="One or two sentences instructing the proposal LLM how to weight "
                    "this agent's findings relative to experiment results and other sources. "
                    "E.g. 'Treat as promising priors — only experiment runs confirm applicability.' "
                    "For physics agents: 'Physical constraints are HARD LIMITS.'"
    )
```

### `ProposalInput.agent_cards`

New field to add to `ProposalInput` in `agent/schemas/proposal.py`:

```python
agent_cards: List[AgentCard] = Field(
    default_factory=list,
    description="Self-descriptions of all external agents contributing context this round. "
                "Rendered as a 'Contributors' section before the Expert Context block. "
                "The proposal LLM reads these first to calibrate trust in each source. "
                "Empty = no external agents this round (internal-only run).",
)
```

### `render_agent_cards()`

New function to add to `agent/prompt_templates/proposal/__init__.py`:

```python
def render_agent_cards(cards: list) -> str:
    """
    Render agent name cards as a labeled 'Contributors' section.

    Called before render_expert_context() so the LLM reads who is
    contributing before it reads their specific findings.
    """
    if not cards:
        return ""
    lines = ["## External Contributors\n",
             "Read each contributor's role and trust guidance before reading their findings.\n"]
    for card in cards:
        name = card.get("agent_name") if isinstance(card, dict) else card.agent_name
        lines.append(f"### {name}")
        for field in ("role", "expertise_domain", "coverage", "limitations", "trust_guidance"):
            val = card.get(field) if isinstance(card, dict) else getattr(card, field, "")
            if val:
                lines.append(f"  {field.replace('_', ' ').title()}: {val}")
        lines.append("")
    return "\n".join(lines)
```

### System prompt instruction

The comparison stage and causal reasoning stage system prompts (`comparison_stage.md`, `causal_reasoning_stage.md`) need an instruction block added to the "What you receive" section:

```markdown
- **Contributors** (when present): external agents contributing findings this round.
  Read the Contributors section before the Expert Context. Each contributor's
  `Trust guidance` field tells you how to calibrate their findings:
  - Literature agents: treat as promising priors that lower exploration cost.
    Only experiment runs confirm applicability to TIDMAD.
  - Physics agents: physical constraints are HARD LIMITS. Do not propose
    architectures that violate them without explicit physics justification.
  - Human directives: always take precedence over agent findings.
```

### Rendering order in the user prompt

The user prompt passed to each pipeline stage currently concatenates:
1. `accumulated` context (candidates, interpretation summary, etc.)
2. `expert_context_block` (from `render_expert_context`)
3. `vocab_block`

With name cards, the order becomes:
1. `accumulated` context
2. **`agent_cards_block`** (from `render_agent_cards`) ← new, before findings
3. `expert_context_block`
4. `vocab_block`

This ensures the LLM reads *who is contributing* before it reads *what they found*.

---

## §9 Receiving-end gaps to fix before wiring

Three small gaps in the current receiving-end code that would cause problems as soon as external agents are wired.

### Gap 1 — `VocabEntry.proposed_by_run` is semantically overloaded

**Problem**: `proposed_by_run` currently serves two purposes:
1. Attribution — who first suggested this entry
2. Promotion counting — its value is injected into `seen_in_runs`, and promotion fires when `len(seen_in_runs) >= 3`

If an external agent sets `proposed_by_run="ml_literature_review"`, that string enters `seen_in_runs`. After 3 literature review passes, the term gets promoted — without a single experimental validation. Scientifically wrong.

**Fix**: add `origin: Optional[str] = None` to `VocabEntry`. External agents set `origin="ml_literature_review"` (or `"physics_literature_review"`) and leave `proposed_by_run=None`. The `build_runtime_vocab()` function already only injects `proposed_by_run` into `seen_in_runs` — so as long as external entries don't set `proposed_by_run`, promotion stays experiment-driven. No changes to `promote_candidates()` needed.

The `origin` field also makes it visible in the prompt (via `_render_vocabulary`) where a term came from — the LLM can see "this term was suggested by the literature agent, not yet confirmed experimentally."

```python
# Addition to VocabEntry in agent/schemas/proposal.py
origin: Optional[str] = Field(
    default=None,
    description="Source agent for externally-contributed entries. "
                "E.g. 'ml_literature_review', 'physics_literature_review'. "
                "None = proposed during an experiment run (proposed_by_run carries the run name). "
                "When set, proposed_by_run must be None — external contributions do not "
                "count toward seen_in_runs and cannot be promoted via the run-count criterion.",
)
```

### Gap 2 — `render_expert_context` has no deduplication

**Problem**: two agents may independently cite the same paper or produce identical findings (same `cite_id`). Currently both appear in the rendered block.

**Fix**: deduplicate by `cite_id` before rendering — last occurrence wins (most recent agent's version is kept). Three lines in `render_expert_context`.

### Gap 3 — `render_expert_context` has no confidence-based ordering

**Problem**: within a `kind` group, items are in insertion order. With 15 literature items from two agents, the most confident ones may be buried.

**Fix**: sort each group by `confidence` descending before rendering. Items with `confidence=None` sort last. Two lines in `render_expert_context`.

### Gap 4 — item volume (workflow-level, no code change)

**Design decision**: `render_expert_context` renders all items. With many agents producing many items, the prompt grows unbounded. This is intentionally handled at the **workflow level** — the workflow knows the token budget and should trim/prioritize before passing items to the protocol. No change to the renderer. The workflow's curation strategy is TBD when a second external agent is wired.
