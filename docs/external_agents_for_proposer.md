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
    title: str
    authors: str
    year: str
    core_idea: str
    architecture_details: str
    key_results: str
    relevance_to_task: str

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

## §5a Full-text and formula extraction strategy

> Supersedes the Commit-2 pilot finding **F3** ("no `key_equations` field;
> equations in prose") *conditionally*. F3's rationale — `pdfplumber` degrades
> math (`∑`→`(cid:88)`, flattened sub/superscripts) — holds only for the
> pdfplumber path. When a clean LaTeX/Markdown source is available (Tiers 1–2),
> equations and pseudocode are carried verbatim; prose-only applies to Tier 3.
> The Commit-3 compression prompt's instruction to "describe math in prose" now
> applies only to the Tier-3 path. For Tier-1 and Tier-2 inputs, the prompt
> variant must be equation-aware: it should extract equations directly into
> `key_equations_md` rather than paraphrasing them. This prompt variant is
> validated in Checkpoint F.

`verbosity ≥ 1` extraction is a **three-tier cascade**, tried best-first. Each
tier records how the text was obtained in a first-class `extraction_method`
field so every downstream consumer can calibrate trust.

**Tier 1 — arXiv LaTeX source (primary, ground truth).** For any paper whose
`externalIds` carry an ArXiv ID, download the source from
`https://arxiv.org/src/{arxiv_id}` (a `.tar.gz`), extract the main `.tex`, and
parse `equation` / `align` / `algorithm` / `figure` environments to clean
LaTeX/Markdown. This is the author's own source — **zero hallucination risk, no
GPU, no ML model** — and covers the large majority of ML papers.
`extraction_method="arxiv_source"`.

**Tier 2 — `marker` (fallback for non-arXiv).** For DOI/OpenReview papers with
no arXiv source, convert the PDF with `marker-pdf` (open-source, ~4 GB VRAM,
PDF→Markdown with LaTeX preserved; ~10.5/12 on equation extraction vs ~5/12 for
docling). The lab A100 makes VRAM a non-constraint.
`extraction_method="marker_pdf"`. Skipped gracefully (→ Tier 3) when `marker`
is not installed or no GPU exists.

**Tier 3 — `pdfplumber` + LLM reconstruction (last resort).** When neither
Tier 1 nor Tier 2 is available or succeeds, use the existing `pdfplumber` text
and let the node's compression call reconstruct equations in prose plus
*approximate* LaTeX. `extraction_method="pdfplumber_llm"` — the signal that
equation content here is lower-reliability.

When no PDF is obtainable at all: `extraction_method="abstract_only"`.

**Cascade (skill, `verbosity ≥ 1`):**

    if arxiv_id:       try Tier 1 → "arxiv_source"    (on fail ↓)
    if pdf available:  try Tier 2 → "marker_pdf"       (on fail / not installed ↓)
                       Tier 3      → "pdfplumber_llm"
    if no pdf:         "abstract_only"

The skill returns the extracted Markdown **and** `extraction_method` in its
response envelope. The node reads `extraction_method` to pick the compression
prompt variant: Tiers 1–2 (clean input) get equation-aware instructions that
populate `key_equations_md` / `pseudocode_md` directly; Tier 3 gets "describe
math in prose, attempt LaTeX only when structure is clear, treat
`key_equations_md` as unreliable".

**Output format.** All math is Markdown — display `$$…$$`, inline `$…$`;
pseudocode in fenced ` ```python ` / ` ```algorithm ` blocks. Example:

````markdown
## Key Equations

The SNR-aware loss is defined as:

$$\mathcal{L}_{\text{SNR}} = -\log\frac{\|s\|^2}{\|s - \hat{s}\|^2}$$

## Algorithm

```python
# Adaptive hard-sample reweighting
for segment in batch:
    weight = compute_snr_weight(segment, noise_floor)
    loss += weight * reconstruction_loss(pred, target)
```
````

**Schema impact** (finalized in Commit 2c; amends the Commit-3 locked 7-field
set). `PaperExtract` gains:
- `key_equations_md: Optional[str]` — display/inline LaTeX of core equations.
- `pseudocode_md: Optional[str]` — fenced pseudocode/algorithm blocks.
- `extraction_method: Literal["arxiv_source","marker_pdf","pdfplumber_llm","abstract_only"]`
  — first-class trust signal, default `"abstract_only"`.

**Why Tier-1-first, and why it matters for the `reference_library`.** The
`reference_library` (planned channel carrying the full `PaperExtract` for each
verbosity≥1 paper cited in `findings`) is only as useful as the math it carries.
For *recent* papers whose methods the proposer never saw in training, a finding
that names a method without its equations/pseudocode is unimplementable — the
proposer cannot describe or build a method it knows only by name. arXiv source
is Tier 1 because it is ground-truth author text: no OCR, no font-glyph loss, no
hallucination. `extraction_method` travels with the content so the proposer (and
coder) can weight equation fidelity accordingly.

---

## §5b reference_library channel

`findings` and `reference_library` are complementary channels:
- **`findings`** (`List[ExpertContextItem]`) — LLM-synthesized implications:
  *what to try*, grounded in the current bottlenecks. Always populated.
- **`reference_library`** (`List[PaperReference]`) — the raw `PaperExtract` for
  each cited paper: *how to implement it*, from the original source. Populated
  only for papers deep-read at verbosity ≥ 1.

A three-part finding tells the proposer a method exists and why it's relevant.
But for a *recent* paper the proposer never saw in training, that is not enough
to implement the method — it needs the original equations and pseudocode.
`reference_library` carries exactly that, looked up by `cite_id`.

**Schema** (`agent/schemas/literature_review.py`):

```python
class PaperReference(BaseModel):
    """A single reference_library entry: the full PaperExtract for a paper
    cited in findings, looked up by cite_id."""
    paper_id: str            # matches RetrievedPaper.paper_id
    cite_id: str             # matches ExpertContextItem.cite_id — the lookup key
    title: str
    year: str
    extract: PaperExtract    # full extract incl. key_equations_md, pseudocode_md
    verbosity_achieved: int  # always >= 1 for a reference_library entry
    extraction_method: str   # propagated from PaperExtract.extraction_method —
                             # equation-reliability signal for the proposer
```

**Population rule.** A `PaperReference` is emitted for exactly the papers that
are (a) cited by at least one `ExpertContextItem` in `findings` **and** (b) have
`verbosity_achieved >= 1`. Verbosity-0 (abstract-only) papers never appear — they
have no `PaperExtract` to contribute. An **empty `reference_library` is valid**
(every finding cited an abstract-only paper).

**Lookup pattern (pull, not push).** The proposer reads `findings` first; for any
finding it wants to act on, it takes that item's `cite_id` and looks up the
matching `PaperReference` for the original equations/pseudocode/architecture. It
is not required to read every entry — only the ones behind findings it builds on.

**Equation trust hierarchy** (`extraction_method`, descending reliability):
`arxiv_source` (ground-truth LaTeX) > `marker_pdf` (good) > `pdfplumber_llm`
(approximate) > `abstract_only` (not present — no reference_library entry).

**Relationship to Commit 2c.** The `reference_library` *structure* lands in
Commit 2d. Its equation *content* (`key_equations_md`, `pseudocode_md`) is
reliably populated only once Commit 2c's three-tier extraction lands; before
that, those fields are typically `None` — the structure is in place, content
improves when 2c lands.

**Example — a finding and its reference_library entry side by side:**

A finding (in `expert_context`):

    [LITERATURE REFERENCE] (from ml_literature_review, confidence=0.7,
     cite_id=arxiv:2503.18162)
      Given the optimization-to-metric mismatch, SNRAware's SNR-unit training
      aligns the loss with the SNR metric rather than a proxy — try an
      SNR-normalized reconstruction loss for the hard segments. (rationale:
      deep-read, on-domain denoising with a clear mechanism transfer.)

The matching reference_library entry (looked up by that `cite_id`):

    paper_id:           arxiv:2503.18162
    cite_id:            arxiv:2503.18162
    title:              SNRAware: Improved Deep Learning MRI Denoising ...
    year:               2025
    verbosity_achieved: 1
    extraction_method:  arxiv_source        # equations are ground truth
    extract.key_equations_md:
        The SNR-aware loss is:
        $$\mathcal{L}_{\text{SNR}} = -\log\frac{\|s\|^2}{\|s - \hat{s}\|^2}$$
    extract.architecture_details:
        Dual-branch denoiser with an SNR-unit normalization front-end ...

The proposer reads the finding to decide *whether* to pursue an SNR-aligned loss,
then reads the reference entry to get the *exact* loss form to implement.

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
6. **Compression word budgets are hardcoded in the prompt template.** The
   `PaperExtract` field word budgets (`core_idea ≤80`, `architecture_details
   ≤150`, `key_results ≤120`, `relevance_to_task ≤100`) are currently literal
   numbers in `paper_extract_system.md`. These are output-length constraints,
   not LLM-assigned scores, so they are lower-risk than scores — but for
   consistency they should move to a configurable `FieldWordBudgets` object
   following the same pattern as `ConfidenceRubric` (single source of truth in
   `agent/schemas/`, injected via a placeholder, no numbers in the .md). Deferred
   because changing them requires re-validating Checkpoint B. See the
   "Scoring and rubric design invariants" section in `external_agents_architecture.md`.

---

## §10 End-to-end validation suite

The permanent acceptance gate for the whole `ml_literature_review` system.

### §10.1 — Purpose and scope

This suite is the definitive answer to: *"does the system correctly extract
technical content from papers and produce actionable findings for the
proposer?"* It validates the **complete pipeline** end-to-end —
`paper_resolver_skill` → `PaperExtract` (compression) → synthesis →
`ExpertContextItem` findings → (Commit 2d) `reference_library` — on a fixed
corpus of real arXiv papers, with human review of every intermediate artifact.

It is a **permanent fixture, not a one-time checkpoint**. The corpus of seven
papers (§10.2) is *locked*: every future change to a prompt
(`paper_extract_system.md`, `search_decision_system.md`, `synthesis_system.md`),
a schema (`ConfidenceRubric`, `SynthesisConfig`, `PaperExtract`), or an
extraction tier (Commit 2c) must be re-validated against this same corpus, so
results are comparable across commits. Locking the corpus is what makes the
suite a regression gate rather than a moving target.

It complements, rather than replaces, the commit-gated checkpoints
(A/B/C/E/F — see §10.6). Those are *behavioral gates attached to a single
commit*; this suite is the *human-review acceptance standard* that spans
commits and can be triggered any time (§10.7). A checkpoint answers "did this
commit's change work?"; the suite answers "does the whole system still meet the
acceptance bar?"

Note: the suite is only *fully* runnable after Commits 2c + 2d — see the
runnability callout at the top of §10.4.

### §10.2 — Fixed test corpus

Seven locked papers, all real and arXiv-resolvable. `.tex` source availability
verified 2026-05-29 via `arxiv.org/src/{id}`.

| # | Track | arXiv ID | Title | Why selected | Has `.tex` source |
|---|-------|----------|-------|-------------|----------------|
| 1 | Main — architecture | `2312.00752` | Mamba: Linear-Time Sequence Modeling with Selective State Spaces | State-space / selective-SSM family; rich, specific `architecture_details` (selection mechanism, hardware-aware scan) | yes (Tier-1) |
| 2 | Main — architecture | `2211.14730` | A Time Series is Worth 64 Words (PatchTST) | Transformer/attention family; patching + channel-independence — a distinct architecture from #1 | yes (Tier-1) |
| 3 | Application — physics | `2511.20731` | Denoising gravitational wave with deep learning in the time-frequency domain | GW detector signal; tests `relevance_to_task` transfer to SQUID; prior extract data (Checkpoint B 5-paper check) | yes (Tier-1) |
| 4 | Application — physics | `1811.02695` | Seismic Signal Denoising and Decomposition Using Deep Neural Networks (DeepDenoiser) | Different physical 1-D signal (geophysics); transfer-relevance test | yes (Tier-1) |
| 5 | Denoising — architecture | `2501.04967` | Targeted Adversarial Denoising Autoencoders (TADA) for Neural Time Series Filtration | New 1-D neural-time-series denoising AE; prior data (canonical trace finding @0.50) | yes (Tier-1) |
| 6 | Denoising — loss/training | `2510.25800` | FreIE: Low-Frequency Spectral Bias in Neural Networks for Time-Series Tasks | 1-D frequency-domain / metric-aligned loss; on-domain high-confidence path; prior data (canonical trace finding @0.45) | yes (Tier-1) |
| 7 | Denoising — loss/training (cross-domain) | `2503.18162` | SNRAware: Improved Deep Learning MRI Denoising with SNR Unit Training and G-factor Map Augmentation | **PDF-only fallback-tier case.** SNR-aware training exemplar; richest prior data (root in canonical trace; cited @0.65 in the isolated moderate comparison). Tests the moderate-tolerance cross-domain-with-caveat path **and** the Tier-2/Tier-3 extraction fallback | **no — PDF-only** (Tier-2/3) |

**These papers are locked.** Do not substitute without updating this section and
re-running the full suite. Additions (e.g. an 8th paper for a new track) are
welcome but do not replace the seven core papers. **Two intentional design
choices:** #6 (FreIE) and #7 (SNRAware) both occupy the denoising loss/training
track because they exercise *different* behavioral paths — #6 the on-domain
high-confidence path (0.60–0.79+ band), #7 the cross-domain transfer-caveat path
(moderate tolerance) **and** the PDF-only extraction fallback (no `arxiv_source`).
If `arxiv.org/src` availability changes for any paper (e.g. a new version adds
source), re-verify and update the `.tex` column.

### §10.3 — Parameter reference table

These parameters control pipeline behavior during a suite run. Every run must
record which values were used.

**Table 1 — Verbosity parameters**

| Parameter | Location | Values | Default | Controls |
|-----------|----------|--------|---------|---------|
| `PaperSource.verbosity` | `LiteratureReviewInput.root_papers` | 0, 1, 2 | 1 | Root paper resolve depth: 0=metadata only, 1=full text + compression, 2=full text only (no compression) |
| `DynamicSearchConfig.initial_verbosity` | `LiteratureReviewInput.dynamic_search` | 0, 1, 2 | 0 | Initial verbosity for dynamic search results |
| `RetrievedPaper.verbosity_achieved` | `LiteratureReviewOutput.retrieved_papers` | 0, 1, 2 | — | Actual verbosity reached by resolver (output, not input) |
| `findings_verbosity` | `LiteratureReviewInput` | 0, 1 | 1 | Finding content format: 0=single paragraph, 1=three-part Implication/Mechanism/Adaptation |
| `extraction_method` | `PaperExtract` (Commit 2c+) | `arxiv_source`, `marker_pdf`, `pdfplumber_llm`, `abstract_only` | `abstract_only` | Extraction tier used, serves as trust signal for downstream consumers |

**Table 2 — Threshold and scoring parameters**

| Parameter | Location | Values | Default | Controls |
|-----------|----------|--------|---------|---------|
| `ConfidenceRubric.omit_below` | `LiteratureReviewInput.confidence_rubric` | float | 0.40 | Findings below this confidence are omitted from findings list |
| `ConfidenceRubric.abstract_only_ceiling` | `LiteratureReviewInput.confidence_rubric` | float | 0.79 | Confidence upper bound for verbosity=0 papers (node-side clamp) |
| `ConfidenceRubric` bands | `LiteratureReviewInput.confidence_rubric` | 0.80–1.00 / 0.60–0.79 / 0.40–0.59 / omit | standard | Evidence requirement per band: deep-read+on-domain / clear transfer / abstract-only / omit |
| `SynthesisConfig.transfer_tolerance` | `LiteratureReviewInput.synthesis_config` | `strict`, `moderate`, `liberal` | `moderate` | Threshold for generating findings from cross-domain papers |
| `DynamicSearchConfig.max_rounds` | `LiteratureReviewInput.dynamic_search` | int ≥ 1 | 3 | Maximum search loop rounds |
| `DynamicSearchConfig.max_escalations_per_round` | `LiteratureReviewInput.dynamic_search` | int | 2 | Maximum escalations per round |
| `DynamicSearchConfig.results_per_query` | `LiteratureReviewInput.dynamic_search` | int | 10 | S2 search results per query |

### §10.4 — Test procedure

> **Runnability — Commits 2c/2d dependency.** The suite is *fully* runnable only
> after Commits 2c (three-tier extraction → `key_equations_md`, `pseudocode_md`,
> `extraction_method`) and 2d (`reference_library`) land. Before then it is
> **partially runnable**: **runnable now** (Commit 4 shipped) — Step 1a (v0
> metadata), Step 1b for the seven core `PaperExtract` fields, and all of Phase 2
> (cite_id / confidence band / three-part content / Fix B / clamp); **requires
> Commit 2c** — Step 1b's `key_equations_md` / `pseudocode_md` /
> `extraction_method` checks; **requires Commit 2d** — Phase 2's
> `reference_library` sub-check.

Run in two phases; capture and human-review every intermediate artifact.

**Phase 1 — Paper resolver output (per paper, all 7).** Resolve each paper at two
verbosity levels and capture the full output.

*Step 1a — `verbosity=0` (metadata only):*
- Capture: `s2_metadata` fields (title, year, authors, abstract, citation count); `verbosity_achieved` (must be 0).
- Human review: is the abstract sufficient to understand the paper's core contribution? Would the abstract alone support a valid finding in synthesis?

*Step 1b — `verbosity=1` (full text + compression):*
- Capture: `verbosity_achieved` (should be 1; note if degraded to 0 and why); `extraction_method` (after Commit 2c — expect `arxiv_source` for #1–#6, `marker_pdf`/`pdfplumber_llm` for #7 SNRAware); full `PaperExtract` JSON (all fields).
- Human review per field:
  - `core_idea`: captures the central contribution in ≤80 words?
  - `architecture_details`: names specific layer types, connectivity, key design choices — specific enough that a proposer could learn a concrete design decision? *"Uses deep learning" is a fail; "dilated causal convolutions with exponentially increasing dilation rates and gated activations" is a pass.*
  - `key_results`: performance numbers carry regime qualifiers (dataset, metric, training regime — especially frequency-split vs full-spectrum)?
  - `relevance_to_task`: makes a specific argument about transfer to full-spectrum 1-D SQUID denoising, not generic?
  - `key_equations_md` (Commit 2c+): LaTeX correct? Cross-check against the `.tex` source when `extraction_method=arxiv_source` (#1–#6). For #7 (no `.tex`), judge the marker/pdfplumber-reconstructed equations against the PDF.
  - `pseudocode_md` (Commit 2c+): algorithm structure preserved?
  - No hallucinations: every claim traceable to the source paper?

**Phase 2 — Literature reviewer findings (all 7 as root papers).** Configure
`LiteratureReviewInput` with all 7 at `verbosity=1`, `findings_verbosity=1`,
`transfer_tolerance=moderate`, `max_rounds=3`; run the full node.

Per `ExpertContextItem` in `findings`, review:
- `cite_id`: matches a real retrieved paper?
- `confidence`: in the correct rubric band given the paper's verbosity + domain? Was it clamped by `abstract_only_ceiling` (if the cited paper was verbosity=0)?
- `content` three-part check:
  - **Implication** — names a specific bottleneck? concrete next step? ≤40 words?
  - **Mechanism** — specific layer types / loss terms / training regime? ≤80 words? carries regime qualifiers (e.g. frequency-split caveat)?
  - **Adaptation** — concrete adaptation step for the SQUID full-spectrum setting? ≤50 words?
  - `(rationale: …)` — present and honest?
- No frequency-split recommendations (Fix B must hold).
- Cross-domain papers (esp. #7 SNRAware): does the **Adaptation** explicitly state the transfer assumption?

Additionally, `reference_library` (after Commit 2d):
- Each verbosity=1 paper cited in findings appears in `reference_library`?
- Each `PaperReference.extract` matches the `PaperExtract` from Phase 1?
- `extraction_method` correctly propagated (incl. the non-`arxiv_source` value for #7)?

### §10.5 — Acceptance criteria

A run passes if **all** of the following hold.

**Paper resolver (Phase 1):**
- All 7 papers resolve at `verbosity_achieved=1` (no degradation to 0 unless the PDF/source is genuinely unavailable — document the reason).
- `architecture_details` specific enough for a proposer to learn a concrete design decision, on all 7.
- `key_results` carries regime qualifiers on every paper with training-regime-specific results.
- `key_equations_md` non-empty and LaTeX correct for all papers **with a `.tex` source** (#1–#6, after Commit 2c). For **#7 (PDF-only)**: Tier-2/Tier-3 produces a usable extract and `extraction_method` is correctly set to `marker_pdf`/`pdfplumber_llm` (not `arxiv_source`); equation content is judged best-effort, not held to ground-truth-LaTeX correctness.
- Zero hallucinations across all 7 extracts.

**Literature reviewer (Phase 2):**
- At least 4 of the 7 papers produce at least one finding (papers with no actionable bottleneck relevance may be correctly omitted — document which and why).
- All findings in the correct confidence band per the rubric.
- All findings in `findings_verbosity=1` mode have all three labeled sections present.
- Fix B holds: zero frequency-split recommendations.
- `reference_library` contains entries for all verbosity=1 papers that appear in findings (after Commit 2d).

**Failure response:**
- Phase 1 failure on `architecture_details` or `key_equations_md` → revise the compression prompt or extraction tier; re-run Checkpoints B / E / F.
- Phase 2 failure on finding quality → revise the synthesis prompt; re-validate with the three-way `transfer_tolerance` comparison.
- Systematic failure across multiple papers in the same track → the track may need a different paper; document the failure and escalate before substituting (the corpus is locked — substitution is a deliberate, documented act).

### §10.6 — Relationship to existing checkpoints

| Checkpoint | Scope | Relation to §10 suite |
|------------|-------|---------------------|
| Checkpoint A | Raw paper resolution, TIDMAD only | §10 Phase 1 extends this to 7 papers × 2 verbosities |
| Checkpoint B | LLM compression quality, 2 papers | §10 Phase 1 extends this to all 7 fixed papers |
| Checkpoint C | Dynamic search loop behavior | §10 Phase 2 uses the same synthesis evaluation criteria |
| Checkpoint E | Tier-1 formula extraction quality (Commit 2c) | §10 Phase 1 Step 1b includes `key_equations_md` review (#1–#6) |
| Checkpoint F | LLM compression for new fields (Commit 2c) | §10 Phase 1 Step 1b includes the equation/pseudocode field review |
| Checkpoint D | End-to-end proposer behavior change (Commit 6) | §10 is a **prerequisite** for Checkpoint D — the suite must pass before wiring into the workflow |

### §10.7 — When to run the suite

- Before opening the PR for **Commit 2c** (Checkpoints E + F).
- Before opening the PR for **Commit 2d** (`reference_library` population check).
- Before **Checkpoint D** (Commit 6) — must pass as a prerequisite.
- Any time a prompt file is modified (`synthesis_system.md`, `search_decision_system.md`, `paper_extract_system.md`).
- Any time `ConfidenceRubric` default values change.
- Any time `SynthesisConfig.transfer_tolerance` default changes.
