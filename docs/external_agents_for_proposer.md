# External Agents for the Proposal Pipeline

**Status**: design active. The proposal agent's receiving end is now in place
(see §0 below). The first external agent — `ml_literature_review` — is unbuilt;
this document is the implementation spec.

**Scope**: this revision is focused on building the *first* external agent.
Earlier drafts of this doc covered `ml_literature_review` and
`physics_literature_review` as parallel agents; the second agent has been
intentionally deferred and is referenced only as a future motivator for the
manager layer (§7). The receiving-end schema work that earlier drafts treated
as a prerequisite has landed and is summarised in §0.

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

**You are here**: the **Spec** layer (one specific agent: `ml_literature_review`).

**Direction of truth**: when reality contradicts a doc, fix the highest
layer first (Vision → Spec → Plan), never the reverse.

---

## §0 What's already landed (receiving end)

Earlier revisions of this doc described several schema additions as
"prerequisites." Those are now in `agent/schemas/proposal.py`. Nothing in this
list blocks the implementation order in §8.

| Item | Where it lives |
|---|---|
| `AgentCard` schema (static self-description of contributing agents) | `agent/schemas/proposal.py` |
| `ProposalInput.agent_cards: list[AgentCard]` | `agent/schemas/proposal.py` |
| `ProposalInput.mindset: str \| None` | `agent/schemas/proposal.py` |
| `VocabEntry.origin: str \| None` (decouples external vocab from `seen_in_runs` promotion) | `agent/schemas/proposal.py` |
| `ExpertContextItem.kind="literature"` literal | `agent/schemas/proposal.py` |

The proposal agent already consumes all four channels (`agent_cards`,
`expert_context`, `vocab_seed`, `mindset`) uniformly regardless of which
upstream agent produced them. Adding a new upstream agent requires a new
output schema, a new protocol file, and a workflow wiring change — but no
edits to the proposal agent itself.

One residual item to check during Step 5 of §8: the
`ml_result_interp_to_ml_model_propose` protocol's `local_full_context`
function may not yet thread `mindset` / `agent_cards` from caller kwargs into
the constructed `ProposalInput`. If not, that's a one-line addition; flag in
Step 5 and fix in place.

---

## §1 Overview and philosophy

The first external agent to implement is **`ml_literature_review`**. It reads
ML papers and distills findings into structured `ExpertContextItem` entries
that the proposal agent can use as priors when reasoning about the next
architectural step.

Two design invariants drive everything below.

**Stateless.** `ml_literature_review` keeps no persistent memory between
calls. Every run receives the full experiment history as part of its input
and uses that — not a hidden cache — to avoid re-suggesting directions the
chain has already explored. The only persisted state is the deterministic
root-paper extract cache (§4), which is a content-addressed lookup, not a
conversation history.

**Protocol-driven.** The proposal agent does not know or care which agent
produced a given `ExpertContextItem`. It receives a validated `ProposalInput`,
reads the `agent_cards` block to calibrate trust, and treats every finding
through the same uniform interface. This is the architectural invariant that
keeps the system extensible: adding a second or third external agent does not
change the proposal agent's reasoning logic.

---

## §2 First-version interfaces

The first version uses exactly two channels between external agents and the
proposer. A third is wired but stays empty, and a fourth is pre-identified
for future use.

### Active in v1

1. **`ExpertContextItem`** — structured findings with `source`, `kind`,
   `content`, `cite_id`, and optional `confidence`. The primary channel.
2. **`AgentCard`** — static self-description of the contributing agent
   (`agent_name`, `role`, `expertise_domain`, `coverage`, `limitations`,
   `trust_guidance`). Required so the proposal LLM can calibrate trust before
   reading findings. The card is *defined once in the agent* and emitted on
   every run.

### Wired but empty in v1

3. **`VocabEntry` injection (via `new_vocab_candidates`).** The `VocabEntry`
   promotion mechanism is experiment-driven by design ("only things confirmed
   by real runs count"). Letting external agents seed vocab candidates risks
   polluting the canonical vocabulary with unvalidated literature priors.
   The `origin` field already prevents promotion through the run-count
   criterion (external entries carry `proposed_by_run=None` and never enter
   `seen_in_runs`), but unvalidated vocab still shifts the proposer's
   framing. `ml_literature_review` will produce an empty
   `new_vocab_candidates` list in v1 and revisit once the VocabEntry
   mechanism itself is more mature.

4. **`mindset`.** The field stays in the output schema, but
   `ml_literature_review` will leave it as `None` by default. A `mindset`
   string is a strong directional prior — it overrides the default
   explore/exploit fallback in the causal-reasoning stage prompt — and is
   more appropriate for an agent that emits objective constraints (e.g. a
   future physics agent) than for one that summarises probabilistic
   literature findings.

### Pre-identified, not yet implemented

5. **`disallowed_patterns`.** For cases where the literature systematically
   shows a direction fails on similar tasks. Stronger than
   `ExpertContextItem`, approaches the existing
   `disallowed_architectural_patterns` mechanism. If the external agent is
   wrong, the cost is high (entire architectural family ruled out). Design
   decision: reserve the interface, require human approval to activate, and
   never allow automatic write-in. No schema field yet — to be specified
   alongside its human-approval workflow.

### Interface philosophy

The stronger the influence on the proposer, the higher the activation
threshold:

| Channel | Influence | Activation threshold |
|---|---|---|
| `ExpertContextItem` | soft suggestion | always-on |
| `mindset` | strong directional prior | only when ≥N papers converge |
| `disallowed_patterns` | hard architectural veto | human approval required |

---

## §3 Knowledge sources: root vs dynamic

Two categories of knowledge feed `ml_literature_review`.

### Root knowledge

Static, human-specified, loaded once per run from
`configs/lit_review_config.yaml` (new top-level `configs/` directory,
mirroring `tidmad_data_config.yaml`):

```yaml
root_papers:
  - source: arxiv
    id: "2406.04378"
    notes: >
      TIDMAD primary paper. Use for: dataset physical characteristics,
      signal injection protocol, scoring formula, noise floor properties.
      DO NOT use model performance rankings as architectural guidance —
      all benchmarked models except WaveNet use frequency-split training,
      which is incompatible with SIDERIUS's full-spectrum setting.
      WaveNet is the only directly comparable baseline.
    verbosity: 1
  - source: doi
    id: "10.1103/PhysRevD.XX"
    verbosity: 0
  - source: openreview
    url: "https://openreview.net/forum?id=XXXX"
    verbosity: 1
  - source: local
    path: "reference_data/domain_notes.pdf"
    notes: "Expert notes on SQUID noise"
    # verbosity ignored for local — always resolved at >=1; see §4.

dynamic_search:
  verbosity: 0     # starting floor for newly retrieved papers; in-loop LLM
                   # may upgrade individual papers to 1 or 2.
  max_rounds: 5
  results_per_query: 10
```

Supported source types:

| Source | Resolution path |
|---|---|
| `arxiv` | Semantic Scholar `/paper/ArXiv:{id}` |
| `doi` | Semantic Scholar `/paper/DOI:{doi}` |
| `openreview` | Semantic Scholar `/paper/URL:{url}`, fallback to OpenReview API |
| `local` | PDF via `pdfplumber` (or plain text if `.txt`/`.md`) |

### Dynamic knowledge

Retrieved at runtime by the agent itself based on task description + full
experiment history. The LLM-driven search loop (§5) generates queries, the
resolver skill returns metadata, and the LLM decides which results to
upgrade to verbosity=1.

Both sources produce the same internal data structure `RetrievedPaper`
(§4). The only difference is the `is_root: bool` flag.

---

## §4 Unified paper format and verbosity

All retrieved papers, regardless of source, use one internal schema:

```python
class PaperExtract(BaseModel):
    key_methods: str
    architecture_details: str
    key_results: str
    limitations: str
    relevance_to_squid: str

class RetrievedPaper(BaseModel):
    paper_id: str
    title: str
    authors: str
    year: Optional[int]
    venue: Optional[str]
    abstract: str
    citation_count: Optional[int]
    open_access_url: Optional[str]
    source_id: str                  # used as cite_id in ExpertContextItem
    is_root: bool
    human_notes: Optional[str]      # root papers only
    extract: Optional[PaperExtract] # populated at verbosity>=1
    full_text: Optional[str]        # populated at verbosity==2
    verbosity_achieved: int         # actual level reached after fallback
```

### Verbosity levels

| Level | Content | Approx tokens | How produced |
|---|---|---|---|
| 0 | Abstract + metadata | ~200 | Semantic Scholar API only |
| 1 | Structured LLM extract (`PaperExtract`) | ~750 | PDF download + LLM compression via `LLMBridge` |
| 2 | Full text | ~6 000 – 10 000 | PDF download, no compression |

### Fallback rule

If a higher level is requested but cannot be produced (e.g. no
`openAccessPdf`, no ArXiv fallback, PDF text extraction fails), the agent
silently degrades to the highest level it could achieve and records the
result in `verbosity_achieved`. The downstream `ExpertContextItem` is still
emitted from whatever level was reached.

### Local source rule

The `verbosity` field on a local-source entry is **ignored**. Local files
are always resolved at minimum verbosity=1 — a verbosity=0 entry would
return only a filename, which is useless. If text extraction from the local
file fails, the fallback rule still applies: `verbosity_achieved=0` and the
agent carries on with metadata only.

### Cache

Root paper verbosity=1 extracts are cached in
`reference_data/root_papers_cache/` (e.g. `arxiv_2406.04378_v1.json`).
This directory **is committed to the repo**: root papers are a stable
human-curated set, the verbosity=1 extracts are deterministic for a fixed
LLM, and committing them means CI and all machines work without
regeneration. Cache files are small JSON; no repo-bloat concern.

The cache is never auto-invalidated. To refresh an extract — for example
after a meaningful LLMBridge prompt change — delete the cache file
manually. Dynamic-search results are **never** cached, so the gitignore
story stays simple.

---

## §5 Component breakdown (Shape A architecture)

Following the existing node/skill split in the project: deterministic HTTP
and file operations live in the skill, LLM reasoning lives in the node. No
LLM call ever happens inside the skill.

### `agent/skills/paper_resolver_skill/`

Pure deterministic skill. Folder pattern (`skill_config.json` +
`wrapper.py`) matching the existing skills under `agent/skills/`.

Responsibilities:

- Parse a `PaperSource` (`arxiv` / `doi` / `openreview` / `local`) and fetch
  metadata from the Semantic Scholar API.
- If verbosity ≥ 1: download the PDF. Preference order: S2 `openAccessPdf`
  → arXiv PDF if `externalIds` carries an ArXiv ID → local file path for
  local sources.
- If verbosity = 2: attach raw text to `RetrievedPaper.full_text`.
- If verbosity = 1: return raw text in the skill response so the **node**
  can call `LLMBridge` to compress it into a `PaperExtract` — the LLM call
  stays in the node.
- On any failure: return `{"status": "error", "message": ...}`. Never
  raise — the node is responsible for fallback/degradation decisions.

Single-run S2 response caching is the skill's responsibility (see §9 open
question on rate limits).

### `nodes/ml_literature_review.py` + `agent/schemas/literature_review.py`

LLM-driven node. The schema file holds:

```python
class ExternalAgentOutput(BaseModel):
    """Base contract for any external agent feeding the proposer."""
    agent_card: AgentCard
    findings: List[ExpertContextItem]
    new_vocab_candidates: List[VocabEntry]   # empty in ml_literature_review v1
    suggested_mindset: Optional[str]         # None in ml_literature_review v1

class LiteratureReviewInput(BaseModel):
    task_description: str
    experiment_history: List[ExperimentRecord]
    root_papers: List[PaperSource]
    dynamic_search_config: DynamicSearchConfig

class LiteratureReviewOutput(ExternalAgentOutput):
    retrieved_papers: List[RetrievedPaper]   # full audit trail
```

Node responsibilities:

1. Load `configs/lit_review_config.yaml`, resolve root papers. For each
   root paper: check `reference_data/root_papers_cache/` first, call the
   resolver skill on cache miss.
2. For verbosity=1 root papers: call `LLMBridge` to produce the
   `PaperExtract`, write to cache.
3. Run the dynamic-search loop up to `dynamic_search.max_rounds`:
   - `LLMBridge` generates the next query from task description +
     experiment history + results-so-far.
   - Call the resolver skill with the query → list of `RetrievedPaper` at
     starting verbosity (typically 0).
   - `LLMBridge` decides: done? upgrade any paper to verbosity=1? next
     query?
   - If upgrade requested: resolver-skill round-trip plus `LLMBridge`
     compression.
4. Final `LLMBridge` call: synthesise all root + dynamic results into a
   `LiteratureReviewOutput` — populate `findings` (with stable `cite_id`s
   matching `RetrievedPaper.source_id`), leave `new_vocab_candidates=[]`
   and `suggested_mindset=None` per §2.

### `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`

Maps `LiteratureReviewOutput` into `ProposalInput`:

| Source field | Target field |
|---|---|
| `agent_card` | appended to `ProposalInput.agent_cards` |
| `findings` | appended to `ProposalInput.expert_context` |
| `new_vocab_candidates` | appended to `ProposalInput.vocab_seed` (empty in v1, wired for future) |
| `suggested_mindset` | `ProposalInput.mindset` (None in v1) |

Per `CLAUDE.md` protocol naming convention: include a `database_*`
placeholder raising `NotImplementedError` alongside the `local_*` function.

---

## §6 Workflow integration

Two small additions to `workflows/model_exploration.py`.

### Merge helper

```python
def merge_external_agent_outputs(
    outputs: List[ExternalAgentOutput],
) -> tuple[List[ExpertContextItem], List[VocabEntry], List[AgentCard], Optional[str]]:
    all_context, all_vocab, all_cards = [], [], []
    mindset = None
    for output in outputs:
        all_context.extend(output.findings)
        all_vocab.extend(output.new_vocab_candidates)
        all_cards.append(output.agent_card)
        if output.suggested_mindset:
            mindset = output.suggested_mindset   # last-non-None wins
    return all_context, all_vocab, all_cards, mindset
```

Pure function over `List[ExternalAgentOutput]`. The workflow then folds
the four returned values into the `ProposalInput` it already constructs
from the interpretation protocol's output.

### Trigger hook

```python
def should_run_literature_review(interp_output: InterpretationOutput) -> bool:
    # v1: always run. The S2 free tier (100 requests / 5 min) and the
    # deterministic root-paper cache keep per-iteration cost low enough
    # that unconditional execution is acceptable during development and
    # early production. Future condition will read
    # interp_output.vocab_diversity_ratio < THRESHOLD.
    return True
```

**Tradeoff acknowledged.** Unconditional execution costs API quota per
iteration but keeps the v1 implementation small. The conditional-trigger
field (`vocab_diversity_ratio`) already exists on `InterpretationOutput`,
so flipping to a real condition later is a body-only change.

---

## §7 Extensibility: path to multiple external agents and a manager layer

> The big-picture vision for *all* external agents — taxonomy, manager
> layer, channel hierarchy, cross-cutting concerns — lives in
> [`external_agents_architecture.md`](external_agents_architecture.md).
> This section is the short version, focused on what is forward-compatible
> in the current single-agent implementation.

The current single-agent design is already extensible. Two facts make that
true:

1. **`ExternalAgentOutput` is the common base.** All external agents
   produce the same shape; the workflow and protocol layer never need to
   know which concrete agent produced a given output.
2. **`merge_external_agent_outputs` is a pure function over
   `List[ExternalAgentOutput]`.** Adding a second agent is one line:
   `outputs.append(physics_agent.run(...))`.
3. **`AgentCard.trust_guidance` carries calibration semantics.** The
   proposer reads it to know how to weight each source. There is no
   hardcoded "physics = hard limit, literature = soft prior" logic
   anywhere in the infrastructure — it lives in the card text.

### When to introduce a manager layer

**Not until a second external agent exists.** When it does, extract a thin
class:

```python
class ExternalAgentManager:
    def run(
        self,
        task_description: str,
        experiment_history: List[ExperimentRecord],
        interp_output: InterpretationOutput,
    ) -> List[ExternalAgentOutput]:
        # v1 of manager: just calls lit_review unconditionally.
        # future: conditional triggering, dependency ordering between agents,
        # possibly feeding one agent's output into another's input.
        ...
```

The workflow then calls only `ExternalAgentManager.run()`. The manager
decides which agents to call, in what order, and whether one agent's
output should inform another's input.

**The manager is "insertable", not "refactorable".** Because the workflow
already calls `merge_external_agent_outputs(outputs)` over a list,
introducing the manager only requires replacing direct agent calls with
`manager.run()`. The merge helper, the protocol files, and the proposer
are untouched.

### Concrete future motivator: a physics agent

A natural second external agent is a `physics_literature_review` (or
similar `phys_*`-prefixed) agent emitting hard physical constraints on
SQUID systems — things ML literature would never cover. Such an agent
would use the same `ExternalAgentOutput` interface, set `AgentCard.
trust_guidance` to flag its findings as hard limits, and possibly
populate `suggested_mindset` when a strong domain invariant applies
(e.g. strict causality, band-limit). The interesting addition would be
inter-agent dependency: physics constraints filtering the literature
agent's search queries. That dependency is what would justify the
manager layer's existence — and is why the manager is deferred until a
second agent actually arrives, rather than being built speculatively.

---

## §8 Implementation order

1. `agent/schemas/literature_review.py` — `RetrievedPaper`,
   `PaperExtract`, `ExternalAgentOutput`, `LiteratureReviewInput`,
   `LiteratureReviewOutput`, `DynamicSearchConfig`, `PaperSource`.
2. `agent/skills/paper_resolver_skill/skill_config.json` +
   `wrapper.py` — deterministic HTTP / file resolution, no LLM call,
   per-run S2 response caching.
3. `nodes/ml_literature_review.py` — LLM-driven root-paper resolution,
   dynamic-search loop, final synthesis. (No `ProposalInput` schema work
   needed — §0 already landed it. During wiring, audit
   `local_full_context` in
   `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`
   and add `mindset` / `agent_cards` kwargs if not already plumbed.)
4. `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`
   — protocol with `local_*` plus the required `database_*`
   `NotImplementedError` placeholder.
5. `workflows/model_exploration.py` — add
   `merge_external_agent_outputs`, `should_run_literature_review`, and
   wire the new node into the per-iteration loop.
6. `configs/lit_review_config.yaml` (new top-level `configs/` directory)
   + `reference_data/root_papers_cache/` directory with a README
   explaining cache format and manual invalidation.
7. Tests:
   - Unit: `tests/unit/agent/paper_resolver_skill/` (mock HTTP, mock
     file IO).
   - Unit: `tests/unit/nodes/ml_literature_review/` (mock LLMBridge,
     mock skill).
   - Unit: protocol tests under
     `tests/unit/agent/protocols/test_ml_literature_review_to_ml_model_propose.py`.
   - Optional Tier-1 integration: `tests/integration/nodes/test_ml_literature_review.py`
     (`@real_run`, real LLMBridge + live S2 against the TIDMAD root paper).
8. Connection audit (step 7 of the standard 8-step node checklist): every
   field required by `ProposalInput` is populated from
   `LiteratureReviewOutput` via the protocol; every field required by
   `LiteratureReviewInput` is populated from the workflow's upstream
   context (task description + experiment history + config).

---

## §9 Open questions

Resolved since the last revision (see body sections for the resolution):

- **Knowledge source split (root vs dynamic).** Resolved — §3.
- **Verbosity strategy.** Resolved — §4 (three levels + fallback + local
  override + cache committed).
- **Manager-layer timing.** Resolved — defer until second external agent
  exists, see §7.
- **`VocabEntry` injection by external agents.** Resolved for v1 —
  deferred per §2.
- **Schema prerequisites on the receiving end.** Resolved — §0.

Still open:

1. **Semantic Scholar rate limits.** The free tier is 100 requests /
   5 min. The resolver skill must cache S2 responses *within a single
   agent run* to avoid quota exhaustion when the dynamic-search loop
   re-asks for already-seen papers. Cross-run caching is not in scope.
2. **Full-text availability rate.** Many papers will not have
   `openAccessPdf`, even with the arXiv-PDF fallback. The actual
   fallback rate on the SQUID/denoising paper corpus is unknown —
   measure it on a representative dynamic-search session before
   committing to verbosity=1 as the *default* for root papers in
   `configs/lit_review_config.yaml`. If the rate is high, v=0 may be
   the right default for everything except hand-picked seminal papers.
3. **`disallowed_patterns` interface design.** Pre-identified in §2 but
   not yet specified. Needs a concrete schema field on
   `ExternalAgentOutput`, a corresponding `ProposalInput` field (or
   reuse of `disallowed_architectural_patterns`), and a
   human-approval workflow before any agent is allowed to populate it.
4. **Item-volume management.** With one external agent this is fine; with
   two or more, `expert_context` can grow large. The workflow-level
   curation strategy — token-budgeted trimming, confidence sorting,
   dedup by `cite_id` — is TBD when a second external agent is wired.
   Existing renderer-side dedup and confidence sorting in
   `render_expert_context` are already in place to soften this.
5. **OpenReview source type has no fallback when S2 does not index the URL.**
   S2 coverage of workshop/under-review papers is inconsistent. Until a fallback
   to the OpenReview API is implemented, `source: openreview` entries in
   `lit_review_config.yaml` should only be used for papers confirmed to be
   indexed by S2. (The URL-encoding bug that truncated `?id=…` before it reached
   S2 is fixed — see `docs/paper_resolver_pilot.md` — so the limiter is genuine
   S2 coverage, not request construction. Confirmed in the Commit 2 pilot: a
   correctly-encoded ICLR forum URL still returns 404.)
