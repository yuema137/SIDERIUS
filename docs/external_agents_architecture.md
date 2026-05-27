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
anywhere in the infrastructure. That calibration lives entirely in the
`AgentCard.trust_guidance` string each agent emits.

Concretely:

- A literature agent's card says *"Treat as promising priors; only
  experiment runs confirm applicability."*
- A physics agent's card says *"Physical constraints are HARD LIMITS;
  do not override without explicit physics justification."*
- A narrative agent's card says *"Continuity signal for prompt framing;
  not evidence."*

The proposer's system prompt teaches it to read the
`## External Contributors` block first and use each card's
`trust_guidance` to weight that agent's findings. If two agents disagree
on the same `cite_id`, the proposer adjudicates using the cards plus the
finding texts; we don't build a precedence resolver in code.

**Implication**: trust composition between agents is the proposer's
problem, not the workflow's. Adding a new agent does not require
rewriting any priority rules — write a clear card and stop.

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
renderer (`render_expert_context`) already dedups by `cite_id` and
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
  `rationale`, `cite_id`).
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

## §9 Open architectural questions (carry forward)

These are not implementation TODOs; they are open *design* questions
that the next external agent will force us to answer.

1. **Trust composition when agents disagree.** Two agents cite the same
   paper with contradictory framings. The proposer adjudicates today via
   the `AgentCard.trust_guidance` strings. Is that enough at three
   agents? At five? Open until tested in practice.
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
