# External Agents — Architecture & Long-Term Vision

**Status**: design vision, not implementation plan. This document captures
the big-picture architecture for how external agents (literature review,
physics, data analysis, narrative, …) compose into the proposal pipeline.
It moves slowly; per-agent implementation specs (e.g.
[`external_agents_for_proposer.md`](external_agents_for_proposer.md))
evolve on their own cadence.

The job of this doc is to record the invariants that future agents must
respect and the deferred decisions that future agents will force us to
make. If something here turns out to be wrong, **update this doc first**,
then update the implementation spec — never the other way around.

---

## Document relationships

External agents are governed by three documents, each at a different layer:

- **Vision** — [`external_agents_architecture.md`](external_agents_architecture.md):
  invariants every external agent must respect (channel hierarchy, `AgentCard`
  trust calibration, when a manager layer is justified). Slow-moving.
- **Spec** — [`external_agents_for_proposer.md`](external_agents_for_proposer.md):
  the design of the first agent, `ml_literature_review` — schemas, verbosity
  levels, workflow integration. Evolves as implementation reveals reality.
- **Execution** — [`commit_plan_ml_literature_review.md`](commit_plan_ml_literature_review.md):
  the live `[ ]`/`[x]` checklist for rolling out `ml_literature_review`,
  commit by commit. Updates in lockstep with the code.

**You are here**: the **Vision** layer.

**Direction of truth**: when reality contradicts a doc, fix the highest
layer first (Vision → Spec → Plan), never the reverse.

---

## §1 What an external agent is (and is not)

An **external agent** is a node that feeds the proposal pipeline with
context the proposal agent cannot derive itself: prior art, physical
constraints, domain heuristics, narrative continuity. External agents are
peers of the in-pipeline analysis nodes (`result_interpretation_agent`,
etc.) but they sit *outside* the per-iteration measurement loop — they
read papers, files, or external APIs rather than experiment results.

What an external agent is **not**:

- Not a general-purpose tool / function-call registry. The proposal
  pipeline is the only consumer; the interface is purpose-built for it.
- Not a substitute for experimental evidence. Every external finding is a
  prior; only experiment runs count toward the vocabulary promotion and
  the falsifiable-prediction loop.
- Not a place to put workflow logic. External agents do not orchestrate
  the chain; they emit a single typed output per call and stop.

---

## §2 The universal contract

Every external agent — present and future — produces an
`ExternalAgentOutput`:

```python
class ExternalAgentOutput(BaseModel):
    agent_card: AgentCard
    findings: List[ExpertContextItem]
    new_vocab_candidates: List[VocabEntry]
    suggested_mindset: Optional[str]
```

Four channels into the proposer. Every concrete external agent populates
some subset; the channels it leaves empty are not bugs but deliberate
choices about scope and influence (§3).

The workflow folds many `ExternalAgentOutput`s into one `ProposalInput`
via `merge_external_agent_outputs`. The proposer reads the merged
`ProposalInput` and never knows which concrete agent produced which item.

This is the architectural invariant: **the proposer sees a flat list of
contributors, not a typed bus of differentiated agent kinds**. Adding a
new agent is an output schema + a protocol file + a workflow wiring
change. It is never a proposer-side change.

---

## §3 The channel hierarchy: influence scales with activation threshold

The four channels of `ExternalAgentOutput` are not equal. They differ in
how strongly each one steers the proposer, and the activation threshold
for each one must scale to match.

| Channel | Influence | Activation threshold | Typical population pattern |
|---|---|---|---|
| `ExpertContextItem` | soft suggestion | always-on | every run that has anything to say |
| `new_vocab_candidates` | mid: shifts the framing vocabulary | gated by VocabEntry-promotion maturity | rare; literature-driven candidates are deferred until the promotion mechanism handles `origin`-tagged entries safely |
| `suggested_mindset` | strong directional prior; overrides explore/exploit default | only when ≥N independent sources converge | rare; one agent should not unilaterally set a chain-wide mindset |
| `disallowed_patterns` *(future)* | hard architectural veto | human approval required to activate | rarest; never auto-write |

The rule: **the louder the channel, the higher the bar to use it.** A
literature agent freely populates `findings`; a physics agent populates
`findings` *and* may set `suggested_mindset` for strict physical
invariants; nothing auto-populates `disallowed_patterns` even in
principle.

---

## §4 Trust calibration via `AgentCard`

There is no hardcoded "physics is hard, literature is soft" logic
anywhere in the infrastructure. That calibration lives on the
`AgentCard` each agent emits, across two complementary fields:

- **`trust_level: Literal["hard_limit", "strong_prior", "soft_prior"]`**
  (introduced in Commit P-b) — the **machine-readable** calibration the
  proposer's synthesis rules read programmatically. Authoritative for
  routing decisions (rule application, synthesis weighting).
- **`trust_guidance: str`** — the **human-readable** complement that
  renders alongside `trust_level` in the Contributors block. Authoritative
  for human review. Carries domain-specific framing the LLM benefits from
  but the structural rules don't need.

When the two appear to disagree, `trust_level` wins for the proposer's
synthesis rules. `trust_guidance` should always be consistent with the
chosen level; if you find yourself writing prose that contradicts the
declared level, the level is probably wrong — fix it.

Concretely:

- A literature agent declares `trust_level="soft_prior"` and the
  `trust_guidance` says *"Treat as promising priors; only experiment
  runs confirm applicability."*
- A physics agent declares `trust_level="hard_limit"` and the
  `trust_guidance` says *"Physical constraints are HARD LIMITS; do not
  override without explicit physics justification."*
- A narrative agent declares `trust_level="soft_prior"` (until evidence
  of stronger transfer) and the `trust_guidance` says *"Continuity
  signal for prompt framing; not evidence."*

The proposer's system prompt (`causal_reasoning_stage.md`'s
`## MANDATORY — Multi-source synthesis` block, landed in Commit P-c)
teaches the LLM to read the `## External Contributors` block first,
note each card's `Trust Level`, and apply the structural synthesis
rules. The rules are generic over `trust_level` values, not over agent
type names — the proposer does **not** pattern-match "Literature agents"
or "Physics agents". Any agent declaring a level routes through the
same rule.

If two agents at different `trust_level` values disagree on the same
`source_ref`, the proposer resolves by the structural rule: `hard_limit`
beats `strong_prior` beats `soft_prior`. Adjudication between two
sources at the **same** `trust_level` is a separate open question — see
§9 Q1.

**Implication**: trust composition between agents is the proposer's
problem, not the workflow's. Adding a new agent does not require
rewriting any priority rules — declare the right `trust_level`, write
a consistent `trust_guidance`, and stop.

### Human notes override misleading literature signals

`trust_guidance` calibrates *how strongly* to weight a source, but not *domain
incompatibilities the LLM cannot see*. A concrete case surfaced in the
`ml_literature_review` pilot: the TIDMAD paper benchmarks denoising models under
a **frequency-split** training setting, while SIDERIUS trains **full-spectrum**.
The paper's rankings therefore do not transfer — yet nothing in the paper *text*
flags this, so the compressing LLM cannot infer it unaided.

This is why the `notes` field on each root paper in `lit_review_config.yaml` is
**not optional decoration** — it is the mechanism by which human domain knowledge
**overrides** potentially misleading literature signals. When a human note
conflicts with paper content, the note wins. Correspondingly,
`AgentCard.limitations` for `ml_literature_review` must state explicitly:
*"findings from root papers reflect the experimental settings described in those
papers, which may differ from SIDERIUS's training setting; human notes in
lit_review_config.yaml are authoritative when they conflict with paper content."*

---

## §5 The manager layer: when and why

For a single external agent (v1), the workflow calls
`ml_literature_review.run(...)` directly, wraps the result in a one-item
list, and feeds it to `merge_external_agent_outputs`. No manager needed.

A thin `ExternalAgentManager` is justified when **any** of these three
conditions holds:

1. **Conditional triggering across multiple agents.** "Run lit-review
   only when vocab is stagnating; run physics only at exploration start"
   is the kind of policy that belongs in one place, not scattered across
   workflow conditionals.
2. **Dependency ordering.** "Physics constraints must be computed before
   the literature search runs so they can filter queries" requires the
   manager to topologically sequence agents.
3. **Inter-agent input feeding.** When one agent's output becomes part
   of another agent's input — e.g. physics-derived band limits scoping
   the literature agent's keyword set — only a layer above both can
   wire that.

If none of these three holds, **do not introduce the manager**. A
hardcoded sequence of two `.run()` calls is clearer than a manager that
only ever runs the same two agents in the same order.

### Manager-as-scheduler vs. manager-as-agent

When the manager exists, it can be one of two things:

- **Deterministic scheduler.** Reads `interp_output` and config, decides
  which agents to call, in what order, with what inputs. No LLM call
  inside the manager itself. Recommended default — SIDERIUS-specific
  physics constraints on SQUID systems are static and don't need
  re-derivation per iteration.
- **LLM-coordinated meta-agent.** The manager itself becomes an
  `ExternalAgentOutput`-producing agent whose internal reasoning decides
  which sub-agents to call. Only justified if agent selection itself
  needs context-sensitive reasoning that can't be expressed as static
  policy. **Do not build this unless a concrete dependency makes static
  scheduling impossible.**

---

## §6 The "insertable, not refactorable" property

The current single-agent shape is forward-compatible with the manager
layer by construction. Three properties make this true and **must be
preserved** by every future change:

1. **`ExternalAgentOutput` is the only thing the workflow consumes from
   any external agent.** Concrete agents may add extra fields (e.g.
   `LiteratureReviewOutput.retrieved_papers` for audit trail), but the
   workflow only reads the four base fields.
2. **`merge_external_agent_outputs(outputs: List[ExternalAgentOutput])`
   is a pure function over a list.** Adding agents is appending to the
   list, never restructuring the merge.
3. **The protocol file per agent maps that agent's output into
   `ProposalInput` channels — nothing else.** No agent-specific code in
   the proposer; no agent-specific code in the workflow's merge.

When the manager arrives, it replaces the workflow's direct `.run()`
calls with `manager.run(...) -> List[ExternalAgentOutput]`. The merge
function, the protocol files, and the proposer are untouched. That is
the design promise.

---

## §7 Taxonomy: agents we anticipate

Not a commitment to build any of these. A taxonomy to help reason about
which channel each future agent would populate and which manager
condition (§5) it would trigger.

| Agent (hypothetical) | Module prefix | Primary channel | Notable card text | Triggers manager when? |
|---|---|---|---|---|
| `ml_literature_review` | `ml_` | `findings` | soft priors | (v1 — single agent, no manager) |
| `phys_literature_review` (or `phys_constraint_extractor`) | `phys_` | `findings` + occasional `suggested_mindset` | hard limits | adds **condition 3**: feeds band limits into ml lit-review queries |
| `data_analysis_external` (cross-experiment / external dataset comparisons) | `data_` | `findings` | empirical priors | adds **condition 1**: conditional on cross-dataset relevance |
| `narrative_agent` (chain-continuity prompt scaffolding) | `narr_` (new prefix) | `suggested_mindset` only | continuity signal, not evidence | adds **condition 2**: must run after interpretation, before lit-review |

The new-prefix rule from `CLAUDE.md` applies — `ml_`, `phys_`, `data_`,
`narr_` etc. each define a distinct module scope. Don't reuse a prefix
across modules just because the name sounds close.

---

## §8 Cross-cutting concerns

Items that don't belong to any single agent and will need workflow- or
infrastructure-level treatment as the agent count grows.

### Item-volume management

With one external agent, `ProposalInput.expert_context` is bounded.
With three or four, it can blow the proposer's token budget. The
renderer (`render_expert_context`) already dedups by `source_ref` and
sorts by confidence, which softens this — but the workflow remains
responsible for token-budgeted trimming before the protocol runs.

The strategy to write when a second agent lands:

- Hard cap on total items per stage prompt.
- Trim policy: keep all items from agents whose card flags hard
  constraints, then fill remaining budget by confidence descending
  across the other agents.
- Surface the trim in a debug log so the proposer's behaviour stays
  auditable.

### `disallowed_patterns` interface

Pre-identified in `external_agents_for_proposer.md` §2. To specify:

- Schema field on `ExternalAgentOutput` (likely
  `disallowed_patterns: List[DisallowedPattern]` with `pattern`,
  `rationale`, `source_ref`).
- Wiring into the existing `disallowed_architectural_patterns`
  mechanism in `ProposalInput` (or a sibling field).
- Human-approval workflow: every disallowed pattern an external agent
  proposes is **logged for review, not auto-applied**. Operator
  promotes it explicitly. No agent ever writes a hard veto without a
  human in the loop.

### Cache and reproducibility across agents

Each external agent's deterministic outputs (e.g. literature-review
verbosity=1 extracts) live in committed caches under `reference_data/`.
Each agent owns its own subdirectory; no shared global cache. This
keeps cache invalidation per-agent and makes it obvious which agent's
state is stale when a result changes.

### Cost accounting

External agents make API calls. As the agent count grows, the chain's
per-iteration API cost becomes the sum of every agent's cost. The
manager (§5) is the natural place to surface a per-iteration budget
and short-circuit individual agents when they would exceed it — but
this is a v2+ concern and intentionally not pre-designed here.

---

## Scoring and rubric design invariants

Any numeric score produced by an LLM agent (confidence, relevance, quality,
etc.) must satisfy all four of the following invariants:

1. **Single source of truth.** The rubric defining what a score means is
   defined exactly once — as a Pydantic model in `agent/schemas/`. It is
   never duplicated or paraphrased in prompt text.

2. **Injected, not hardcoded.** Prompt templates (.md files) contain zero
   numeric thresholds or band definitions. Instead they contain a named
   placeholder (e.g. `{CONFIDENCE_RUBRIC}`) that is filled at render time
   from the Pydantic model. A number appearing directly in a .md file is
   a violation.

3. **Consistent interpretation.** Every agent that produces a score and
   every agent that consumes or acts on that score must use the same rubric
   object. If the proposer sorts findings by confidence, it must have access
   to the same rubric the lit-review agent used to assign those scores —
   so it knows what 0.65 actually means.

4. **Configurable, not hardcoded.** Rubric objects are fields on the relevant
   Input schema (e.g. `LiteratureReviewInput.confidence_rubric`) with a
   sensible default. A run or config can override the rubric without touching
   any prompt file. Thresholds (e.g. "omit below 0.40") live in the rubric
   object, not in prompt prose.

**Current implementation**: `ConfidenceRubric` in
`agent/schemas/literature_review.py`, injected into
`agent/prompt_templates/literature_review/synthesis_system.md` via
`{CONFIDENCE_RUBRIC}`. The omit threshold (< 0.40) is a field on the rubric,
not a hardcoded number in the prompt.

**Applies to**: any future score introduced anywhere in the system —
proposal quality scores, interpretation confidence, tuner reward signals,
external agent trust scores. Before adding a new numeric score, ask:
where is the rubric defined? who injects it? who consumes it? are they
using the same object?

---

## Mathematical content travels inline inside findings

Mathematical frameworks and pseudocode are **load-bearing content**, not
decoration. A proposer reading an `ExpertContextItem` for a paper it has
**never seen in training** depends entirely on the accuracy of the
equations and algorithm fragments it sees: if those are wrong or absent,
the proposer can at best repeat the paper's name, not implement its
method. Structural prose ("uses a dual-branch SNR-aware design") tells the
proposer *that* a mechanism exists; only the equations and pseudocode tell
it *what the mechanism is*.

Mathematical content reaches the proposer **inside `ExpertContextItem.content`**,
not via a separate channel. The lit-review agent's synthesis LLM has access
to each cited paper's `key_equations_md` / `pseudocode_md` and quotes the
relevant snippet directly inside the finding's Mechanism section (and
Adaptation, where the equation IS the adaptation). The proposer reads one
channel — `expert_context` — and the math travels with the citation.

The `PaperExtract.extraction_method` field is the **trust signal** the
synthesis LLM uses to decide *how* to quote. In descending reliability:
`arxiv_source` (ground-truth LaTeX) > `pdfplumber_llm` (degraded text + LLM
reconstruction) > `abstract_only` (none). The synthesis prompt instructs the
LLM to quote Tier-1 equations verbatim and to flag Tier-2 equations as
paraphrases. See "Full-text and formula extraction strategy" (§5a of
`docs/external_agents_for_proposer.md`) for the tier definitions and
"Equations and pseudocode in findings" (§5b of the same doc) for the
synthesis-prompt design.

Earlier drafts of this architecture proposed a parallel `reference_library`
pull-channel — typed `list[PaperReference]` on the lit-review output,
mapped into the proposer via the protocol. That design was cancelled
because the same end-to-end value (equations and pseudocode in front of
the proposer) is delivered by extending the existing `findings` content,
without any new schema on either side of the boundary.

---

## §9 Open architectural questions (carry forward)

These are not implementation TODOs; they are open *design* questions
that the next external agent will force us to answer.

1. **Trust composition when agents disagree.** *(Partially resolved by
   Commits P-b + P-c — 2026-06-05.)* The cross-`trust_level` case is
   resolved structurally: `hard_limit` beats `strong_prior` beats
   `soft_prior`, applied as a synthesis rule generic over
   `trust_level` values (see §4). Adjudication between two sources at
   the **same** `trust_level` is deferred — this scenario requires
   multiple `strong_prior` or `hard_limit` agents to be active
   simultaneously, which is not the case until a second external agent
   is added.
2. **`suggested_mindset` collision.** §6 of the proposer-spec uses
   *last-non-None wins*. With two agents both populating mindset (e.g.
   physics + narrative), is the last-wins rule acceptable? Likely needs
   replacement with a precedence reading off `AgentCard` — but only
   once two agents actually populate the field.
3. **Manager-as-agent threshold.** §5 keeps the manager as a
   deterministic scheduler by default. What concrete pattern would
   justify upgrading it to an LLM-coordinated meta-agent? Need a
   triggering example before designing this.
4. **Cross-iteration agent memory.** Today every external agent is
   stateless and re-runs from scratch each iteration. Some agents (e.g.
   a slow physics literature crawl) might benefit from
   chain-persistent state. If so: where does it live, and how does it
   stay compatible with the stateless contract? Open.

---

## §10 Pointers

- Per-agent implementation spec for the first external agent:
  [`external_agents_for_proposer.md`](external_agents_for_proposer.md).
- Schema home for shared types (`AgentCard`, `ExpertContextItem`,
  `VocabEntry`, `ProposalInput`): `agent/schemas/proposal.py`.
- Inter-node communication invariants: `CLAUDE.md` — *Inter-Node
  Communication Principle* and *Graph Architecture — Adding a New Node*.
- Agent skill / tool universal contract: `CLAUDE.md` — *Skill
  Architecture (Universal Callable Contract)*.

---

## §11 Reflections from Checkpoint L (2026-06-22 → 2026-06-24)

This section is **retrospective**, not prescriptive. It captures
what we learned by shipping the first agent that depended on the
proposer's external-agent receiving end —
`ml_literature_review` — and by then forcing that agent's output
through the full proposer → implementor → tuner → training loop
in Checkpoint L. Many of the lessons are not specific to
lit-review; they are about **the shape of external agents in
general**. Future agents (physics, data analysis, narrative, …)
will hit the same patterns. Use this section as a checklist
before designing the next one.

The corresponding concrete fix log lives in
`docs/design/enable_loss_inventory.md` § "Issues discovered during
Checkpoint L execution (2026-06-22/23)" (I1–I11) plus the L6c bug
report (Bugs #1–#3). This doc summarises the *architectural*
patterns; that doc captures the commits.

### §11.1 Failure patterns we kept hitting

Across 14 issues over three days, four patterns recurred:

**Pattern A — Silent field drop at translation boundaries.** A new
schema field (e.g. `ProposalOutput.custom_loss_spec`) was added
upstream, but the downstream call site that constructed the next
artifact didn't enumerate it. Pydantic accepted the missing field
because of a sensible default (`None` / `""`), so nothing raised;
the field just disappeared. *I8* (proposer dropped `custom_loss_spec`
from the LLM raw output for ~3 weeks before Gate 3 surfaced the
issue) and *L6c Bug #3* (`_promote_loss_to_global` dropped
`mathematical_definition` in the `replace()` call) are the same
defect at two different layers. **The risk is universal to every
boundary an external agent's output crosses.**

**Pattern B — Source-vs-consumer registry asymmetry.** The proposer
node was registry-aware after L5; the tuner planner was not until
L6b — yet both consume the same `CapabilityRegistry`. The proposer
emitted Branch C custom losses correctly; the tuner planner then
overwrote `loss_type="custom"` to `"ce"` because the planner's
prompt didn't mention custom as a legal value. *I9* (tuner planner
needs registry awareness) and *Concern 2* (proposer silently
dropped low-confidence findings without rejection rationale) are
the same family: **every consumer of an external agent's output
needs the same shape of awareness the producer assumes**. Adding
a producer is the easy half; sweeping the consumer surface is the
hard one.

**Pattern C — In-process vs subprocess access asymmetry.** L6a
copied the loss plugin file to the workspace-scoped loss
directory, which the *training subprocess* could read via
`SIDERIUS_LOSS_DIRS`. But the *in-process VRAM pre-flight check*
lived in the workflow's own Python process, which had no
`SIDERIUS_LOSS_DIRS` set. *I12* (the in-process loader silently
fell back to the global library which was empty after our cleanup)
was caused by treating "loaded from disk in a subprocess" and
"loaded from disk in the workflow process" as the same code path
when they have different environments. **An external agent's
outputs that load via side-channels (env vars, filesystem, MCP
servers) need a unified loading contract that works regardless of
who's calling.**

**Pattern D — Type-confusion silent failures.** *L6c Bug #1*
passed a directory path to `register_loss_in_memory` where it
expected a file path. Python typed it as `str` either way;
`importlib.util.spec_from_file_location` returned `None` on the
directory case; `register_loss_in_memory` returned `None`; the
`if _registered_loss is not None` print never fired; `LOSS_REGISTRY`
was never populated. **Three layers of silent fallback masked the
bug for an entire Gate 2 run**, which then false-positive-passed
by the tuner reverting to `ce`. The recurring lesson: **functions
that return `None` on failure are a debugging nightmare across
boundaries**. Either raise, or return an explicit `Result[...]` /
dataclass with a status field.

### §11.2 Architectural principles to avoid these patterns

These are not best-effort suggestions; they are the principles we
should hold the next external agent's design to before merging it.

1. **Schema is the boundary, not the implementation. Enumerate
   every field listed in the schema at every translation site.** If
   `ProposalOutput` adds a field, every call site that constructs
   `ProposalOutput` must extract it from its source. The translation
   layer (e.g. an agent's `run()` method, a workflow's
   `_register_*`) is structurally identical to a protocol function
   — it must be complete. Use `model_dump()` round-tripping or
   `model_copy(update=...)` over manual field enumeration whenever
   possible; both give Pydantic the chance to catch dropped fields
   at validation time.

2. **Symmetric registry awareness for producers and consumers.**
   When an external agent emits items that feed into multiple
   downstream nodes, every consumer must see the same items
   rendered through the same prompt-template helper. The
   `render_available_losses(registry)` helper landed in L5a for the
   proposer; it is now also called by `LLMBridge.plan` for the
   tuner (L6b). **The shared helper is the anti-asymmetry
   mechanism.** Future external agents must publish
   `render_available_X(registry)` helpers and the workflow must
   call them at every consumer node, not just the original target.

3. **Unified loading contract across process boundaries.** The
   loss plugin lives at three loading surfaces: (a) workflow-
   process in-memory `LOSS_REGISTRY`, (b) workflow-process
   filesystem fallback via `_resolve_loss_dirs`, (c) training
   subprocess `SIDERIUS_LOSS_DIRS` env var. L6c unified these by
   making `_load_custom_loss` check the in-memory registry first
   and fall through to the filesystem if absent, with the env var
   being just one of multiple resolved directories. **Future
   external agents that produce loadable artifacts (plugins,
   configs, knowledge bases) must mirror this three-tier
   pattern.** A naïve implementation that only sets an env var
   will leak the I12 failure mode again.

4. **Audit-trail-or-it-didn't-happen.** Any time an item gets
   dropped (a finding ignored, a Branch C reused-as-B, a config
   rejected, a field silently defaulted), the dropping site must
   log *what* and *why*. The L6c bugs were invisible because the
   registration code printed only on success; the failure path
   was silent. *Concern 2* from the Gate 3 audit caught the
   proposer silently dropping 3 low-confidence findings without
   explaining the rejection. Both are the same defect class:
   **silent decisions are bugs unless explicitly documented as
   no-ops**.

5. **Default-to-raise, not default-to-None, at the agent
   boundary.** When in doubt about whether a function should
   return `None` or raise, prefer raise. The L6c file-vs-directory
   bug existed because three layers chose to return `None` rather
   than crash. The downstream code couldn't tell whether the file
   was missing, the plugin was malformed, or the input was the
   wrong type — all three produced the same silent `None`.
   External agents that emit structured findings should raise on
   malformed input (not silently omit a field), and their callers
   should let those raises propagate rather than swallowing them.

### §11.3 What abilities an external agent must have

These are the **minimum capabilities** for a callable to count as
an external agent in the SIDERIUS sense. Checkpoint L verified
that lit-review meets all eight; we should require the same of
the next agent.

| # | Capability | Why it matters | Lit-review's instance |
|---|---|---|---|
| 1 | **Typed input schema** | Avoids "prompt-shaped" inputs that drift | `LiteratureReviewInput` |
| 2 | **Typed output schema** | Enables aggregation + schema validation | `LiteratureReviewOutput` with `findings: list[ExpertContextItem]` |
| 3 | **Mandatory confidence field per item** | Required by aggregation rules + trust composition | `ExpertContextItem.confidence: float ∈ [0, 1]` |
| 4 | **Mandatory `source_ref` per item** | Citation discipline, dedup, no-hallucination check | `source_ref: str` matching `^[a-z_]+:[^\s]+$` |
| 5 | **Mandatory three-part content structure** | Auditability — separates *what we learned*, *how it works*, *how to use it* | `Implication / Mechanism / Adaptation` enforced by `findings_verbosity=1` |
| 6 | **AgentCard with trust band** | Trust composition rules need a known band per agent | `AgentCard.trust_level ∈ {hard_limit, strong_prior, soft_prior}` |
| 7 | **Bounded cost (operator-set cap)** | Long-horizon chains need predictable budget | `dynamic_search.max_rounds`, `max_escalations_per_round` |
| 8 | **Idempotent given same input** | Caching is possible; same prompt → same output | Cached extracts under `reference_data/root_papers_cache/` |

Two soft-but-strongly-recommended capabilities that lit-review has
and that future agents should have unless we have a reason not to:

- **Stable-attractor concept and verification (§10 of the
  lit-review spec).** Across multiple runs of the same input,
  certain findings should reappear — a deterministic core
  surrounded by stochastic variation. If the agent never produces
  the same finding twice, its output is noise.
- **Trust clamping by evidence depth** (e.g. `abstract_only_ceiling`
  in the confidence rubric). The agent should not be allowed to
  emit high-confidence claims backed by shallow evidence.

### §11.4 Stable performance — anchoring useful information

Three patterns proved to make lit-review's output stably useful
for the proposer, surviving Gate 3 with a substantive citation
verdict:

- **Structured output drives downstream behavior.** The three-part
  `Implication / Mechanism / Adaptation` format is what made the
  Gate 3 proposer's Branch C citation substantive rather than
  decorative — the proposer extracted a *mechanism* (FFT + CWT
  gating), adapted it (transition-magnitude weighting), and
  preserved the source_ref verbatim. A free-prose finding would
  have invited paraphrase loss.

- **Confidence rubric anchored in evidence type, not vibes.** The
  bands at `0.80–1.00 = deep-read + on-domain + bottleneck-aligned`,
  `0.60–0.79 = deep-read with mechanism transfer OR strong
  on-domain abstract`, `0.40–0.59 = abstract-only OR cross-domain`
  are defensible by the operator and consistent across LLM
  stochasticity.

- **Operator-overridable thresholds.** `omit_below: 0.40` and
  `abstract_only_ceiling: 0.79` are tunable in the YAML. The
  operator can shift the noise floor without retraining anything.

For the next external agent, the YAML pattern should generalize:
every agent gets an operator-visible config that controls noise
floor, ceiling clamping, and bounded cost. The lit-review config
file is the prototype to copy.

### §11.5 Aggregation across multiple agents — the open frontier

Gate 3 ran with exactly one external agent (lit-review).
Aggregation across N agents is the unanswered question. The
pieces we have:

- §4 Trust-level precedence rule (`hard_limit > strong_prior >
  soft_prior`) handles cross-trust-level conflict generically.
- `source_ref` discipline gives a stable join key for dedup
  across agents (two agents citing the same arXiv paper produce
  findings with the same `source_ref`).
- The `## External Contributors` block renders all agents'
  `AgentCard`s into one panel; the `## Expert Context` block
  flattens all `ExpertContextItem`s into one ranked list.

What we don't yet have:

- **Within-trust-level conflict resolution.** Two `strong_prior`
  agents disagreeing on the same `source_ref` is currently
  underspecified. The proposer's prompt does not tell it how to
  weight conflicting `strong_prior` claims, and we have no
  precedence rule. This is fine while only one `strong_prior`
  agent is active. The moment we add a physics agent at
  `strong_prior`, this must be resolved.

- **Confidence reconciliation when multiple agents reference the
  same source.** If lit-review emits `arxiv:X` at `conf=0.7` and
  a future physics agent emits `arxiv:X` at `conf=0.9`, which
  wins? Options: max, weighted-by-trust, explicit-list-both-in-
  prompt. None tested.

- **Cross-agent dedup vs intentional overlap.** If two agents
  independently surface the same paper, that's a *signal*
  (multiple evidence sources agree). If we silently dedup, we
  lose the agreement signal. If we keep both, the proposer sees
  the same citation twice. The right design likely involves
  grouping by `source_ref` and stacking per-agent perspectives
  underneath — see §12.3 of the proposer-spec for the rendering
  proposal.

These three are the natural Checkpoint M scope. Until then, the
single-agent design is stable.

### §11.6 Dynamic orchestration — beyond the fixed workflow

The current workflow calls `ml_literature_review` at a fixed
point in every iteration (after interpretation, before proposer
reasoning). This is the simplest possible orchestration:
always-on, always-here. It is also a ceiling — for some
iterations, lit-review is wasted budget (the proposer already
has high-confidence direction); for others, it's underused (the
proposer needs domain-specific math that lit-review can't
surface).

Four orchestration options exist, each with non-trivial
tradeoffs.

**Option A — New orchestrator node, in-process.** Add an
`ExternalAgentOrchestrator` agent between interpretation and
proposer reasoning. It receives the iteration state and decides
which subset of `{lit_review, physics, data_analysis, …}` to
call, with what arguments. It calls them sequentially (or via
`workflow()` fanout) and emits an `OrchestrationOutput` that
contains all called agents' results plus a rationale field
explaining the call decisions.
  - **Pros**: stays in-process, fast (no subprocess spawn),
    composes cleanly with the existing skill contract, audit
    trail in `OrchestrationOutput.rationale`, deterministic-
    with-LLM-stochasticity (caching possible if same iteration
    state).
  - **Cons**: adds another LLM call to every iteration (cost +
    latency); the orchestrator itself needs prompt engineering
    and can become a new failure point; the orchestrator's
    decisions need their own audit (we are adding a meta-decision
    layer, which is recursively the same problem we already have
    with the proposer).
  - **When to choose**: when the orchestration decisions are
    well-typed and a small LLM can make them reliably (e.g.
    "lit-review only when proposer reasoning needs a citation",
    "physics only when the proposal involves spectral content").

**Option B — CLI orchestrator (Claude Code, Codex, or operator
script).** A long-running external orchestrator process sees the
chain state (workspace JSON artifacts) and decides at iteration
boundaries which agents to call. The orchestrator is itself a
SIDERIUS-aware entity, but lives outside the chain process. It
mutates the chain's input via filesystem (e.g. writes a
`pending_agents.json` that the workflow reads at iteration start).
  - **Pros**: more powerful (can call out-of-band tools, fetch
    external data, ask the operator), fully observable (its own
    log), can be paused/resumed independently, naturally supports
    multi-tool composition (an orchestrator might call lit-review,
    then a web-search tool, then a math-checker).
  - **Cons**: out-of-process complexity, filesystem-IPC fragility,
    slower (orchestrator decisions happen at iter boundaries, not
    sub-iteration), more difficult to reproduce a run (the
    orchestrator's decisions are a hidden second LLM history),
    operator can be in or out of the loop in unstable ways.
  - **When to choose**: when iteration decisions need to draw on
    information the chain process cannot see (e.g. operator
    feedback, external dashboards, multi-chain comparison).

**Option C — Reactive policy on workflow state.** A deterministic
function `decide_agents(state) → list[AgentCall]` that fires
based on workflow metrics (e.g. "if vocabulary growth < threshold
this round, call lit-review", "if the proposer just rejected 3
proposals, call data_analysis"). No LLM.
  - **Pros**: deterministic (perfect reproducibility), fast (no
    extra LLM call), easy to reason about, easy to test, audit
    trail is just the policy's outputs.
  - **Cons**: requires good metrics to drive the policy — these
    metrics may not exist or may be over-tuned to the current
    task; the policy itself is a maintenance burden that grows
    with each new agent; brittle when adding novel agents whose
    triggers don't yet exist.
  - **When to choose**: when the orchestration decisions are
    *simple* and a clear set of trigger conditions exists. The
    existing `should_run_literature_review` function in the
    workflow is a degenerate case (always-on); a policy-driven
    version would add conditional logic.

**Option D — Hybrid (fixed early, dynamic late).** Run a small
set of foundational agents at fixed points (always); allow
dynamic orchestration only for incremental agents that augment
the foundation. Concretely: lit-review and a future physics
agent fire every iteration; data-analysis, narrative, debugger
agents fire only on orchestrator decision.
  - **Pros**: keeps the foundation stable, allows experimentation
    on incremental agents without risking the foundation; fixed-
    stage cost is predictable, dynamic-stage cost is explicitly
    capped by the orchestrator's budget; supports introducing
    new agents without redesigning the workflow.
  - **Cons**: requires deciding which agents are "foundational" —
    a decision that may need revisiting; doubles the surface
    area (two orchestration mechanisms to maintain).
  - **When to choose**: this is the **default**. Start with
    everything fixed; promote agents to "foundational" only when
    their value is proven; introduce a dynamic orchestrator
    (Option A or B) only when the number of optional agents
    exceeds 3–4.

All four options leave the **skill contract intact**: every agent
remains a typed callable with `{name, description, input_schema,
output_schema}`. Orchestration is composition, not modification.
This is the universal-callable property from `CLAUDE.md` paying
off — moving from fixed to dynamic orchestration does NOT require
changing any agent's contract.

What is open: how to **audit the orchestrator itself**. An LLM
orchestrator (Option A or B) is a new source of decisions that
can go wrong. The right pattern is probably: the orchestrator's
output schema includes `called_agents: list[str]` and
`rationale: str`, both rendered into the proposer's prompt at low
trust (e.g. displayed but not enforced), so the proposer can flag
obviously bad orchestrator decisions in `memo_consistency_notes`.
We will know the right design only after running a multi-agent
chain.

### §11.7 Long-term generalization beyond TIDMAD

Checkpoint L's `task_description` field is full-text SQUID
context. The current confidence rubric was tuned with TIDMAD in
mind. The forward contract is hardcoded to `[B, 256, T] → [B, T]`.
If SIDERIUS is to serve "various ML tasks" as the long-term
horizon, **none of these can be hardcoded into agent contracts**.

Three areas where agent contracts must become task-agnostic:

1. **Task description as a structured payload, not a string.** A
   task description should carry: input modality, target modality,
   metric definition, dataset characteristics, evaluation protocol.
   Lit-review's current `task_description` is a free-text
   paragraph; future agents (e.g. a metric-validator agent) need
   structured access to the dataset's loss-of-interest, not just
   prose. `agent/schemas/task_config.py` is the natural home; the
   `ForwardContract` already lives there as a structured field.

2. **Confidence rubrics as a per-domain config.** The 0.80/0.60/0.40
   bands are tuned for general-ML literature with TIDMAD as the
   bottleneck. A medical-imaging task might use a stricter rubric
   (deep-read required for any conf ≥ 0.5). A pure ML benchmark
   task might use a looser rubric (abstract-only OK at 0.7). The
   `confidence_rubric` block in `lit_review_config.yaml` is the
   prototype; future agent configs should follow the same
   per-domain overridable pattern.

3. **`source_ref` namespacing per agent type.** Today we have
   `arxiv:`, `doi:`, `physics:`, `human:`, `experiment:`. A
   data-analysis agent might emit `dataset:`, `feature:`,
   `outlier:`. The namespacing is currently uncodified — each
   agent decides its own prefix. **Codify**: a registry of
   `source_ref` prefixes mapping prefix → agent type → format
   spec, so the citation-discipline check (§11 of the proposer
   doc) can validate cross-agent citations without each agent
   re-inventing the rule.

The unifying intent: **anything that varies per task should be in
a config file or a registry, not in agent code**. Agent code
should operate on schemas; schemas should accept task-specific
parameters. Today's lit-review-on-TIDMAD is the first concrete
instance of this discipline; it must generalize.

### §11.8 What this section is NOT

This is not an implementation plan. The principles here will be
revisited as the next external agent surfaces new failure modes.
We expect at least one of §11.5's open questions to need redoing
once a second `strong_prior` agent is active.

This section also does not bind the next agent's design. It
binds *the review process* for the next agent: any external-agent
PR should reference the abilities table in §11.3 and the
principles in §11.2 explicitly, and explain how the new agent
honors each. The author should be able to point to a line in
their PR for each checklist item.
