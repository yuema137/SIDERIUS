# MLLiteratureReviewAgent

> External-agent node that resolves root papers, dynamically searches Semantic Scholar grounded in the current iteration's bottlenecks, compresses each retrieved paper into a `PaperExtract`, and synthesizes a list of `findings` that the model-proposing agent reads alongside the experiment results.

## Position in the pipeline

- **Node type**: **workflow-only** — no CLI `main()`; `experiment_history` requires an `InterpretationOutput` assembled by the upstream interpretation node and threaded through `workflows/model_exploration.py`. (Programmatic Python-API use works but requires the caller to construct `LiteratureReviewInput` manually — used by the §10 diagnostic scripts and integration tests.)
- **Upstream**: `result_interpretation_agent` (provides `experiment_history: InterpretationOutput` — the current iteration's bottlenecks + key findings that ground every synthesized finding).
- **Downstream**: `ml_model_proposal_agent` (consumes this node's four channels via the proposer's `agent_cards` / `expert_context` / `mindset` / `vocab_seed` inputs).
- **Protocol**: `local_all_channels` in `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py` — maps `LiteratureReviewOutput.findings` / `new_vocab_candidates` / `agent_card` / `suggested_mindset` into the proposer's four kwargs. No `reference_library` channel — equations travel inline inside finding `content` (per the Commit 2d revision; see §5b of `docs/external_agents_for_proposer.md`).

## Input

**Schema**: `LiteratureReviewInput` in `agent/schemas/literature_review.py`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `experiment_history` | `InterpretationOutput` | Yes | — | Fresh interpretation output from this iteration. The synthesis prompt grounds every finding in one of `experiment_history.bottlenecks`; `key_findings` is PRIMARY input alongside bottlenecks. |
| `root_papers` | `list[PaperSource]` | No | `[]` | Foundational papers always resolved at agent start. Loaded from `configs/lit_review_config.yaml` in production. Per-paper extracts cache under `{root_cache_dir}` for free re-use across runs. |
| `dynamic_search` | `DynamicSearchConfig` | No | `DynamicSearchConfig()` | Knobs for the per-iteration Semantic Scholar search loop (sub-fields: `enabled`, `max_rounds`, `initial_verbosity`, `escalation_allowed`, `results_per_query`, `max_escalations_per_round`). See Parameter Reference for details. |
| `synthesis_config` | `SynthesisConfig` | No | `SynthesisConfig()` | Omission / transfer-tolerance knobs for the synthesis step (`transfer_tolerance` default `"moderate"`). |
| `findings_verbosity` | `Literal[0, 1]` | No | `1` | Per-finding content format. `1` = three-part Markdown (`**Implication:**` / `**Mechanism:**` / `**Adaptation:**` + closing rationale); `0` = single-paragraph backward-compat. Does not affect finding count. |
| `confidence_rubric` | `ConfidenceRubric` | No | `ConfidenceRubric()` | Defines what each confidence band means. Single source of truth — injected into the synthesis prompt at `{CONFIDENCE_RUBRIC}` and rendered into `AgentCard.trust_guidance`. Carries `omit_below` (default `0.40`) and `abstract_only_ceiling` (default `0.79`). |
| `llm_provider` | `str` | Yes | — | LLMBridge provider name for the compression + synthesis steps (e.g. `"deepseek"`, `"openai"`). |
| `llm_model_id` | `str` | Yes | — | LLMBridge model id for the compression + synthesis steps (e.g. `"deepseek-v4-pro"`). |
| `search_llm_provider` | `str \| None` | No | `None` | Optional separate provider for the cheap, templated search-decision step. Falls back to `llm_provider`. Lets the search loop run on a cheaper model while compression + synthesis stay on the main one. |
| `search_llm_model_id` | `str \| None` | No | `None` | Optional separate model id for the search-decision step. Falls back to `llm_model_id`. |

### Workflow-populated fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `storage` | `StorageConfig` | Yes | — | Where the node writes its output JSON. Populated by `workflows/model_exploration.py` from the run-level CLI config (workspace + per-iteration run_name). |
| `run_name` | `str` | Yes | — | Run identifier shared with the workflow. Used as the filename suffix on the output JSON. |

## Output

**Schema**: `LiteratureReviewOutput` in `agent/schemas/literature_review.py` (extends `ExternalAgentOutput`)

| Field | Type | Description |
|---|---|---|
| `agent_card` | `AgentCard` | Static self-description of this agent. Carries `trust_level="soft_prior"` (literature findings are inspirational priors; experiment data takes precedence on conflict). Read by the proposer's synthesis rules to weight this agent's contribution. |
| `findings` | `list[ExpertContextItem]` | The agent's primary output — each finding is grounded in a specific bottleneck (via its `content` Implication line), attributed to a paper (via `source_ref`), and weighted by `confidence` (per the rubric). For Tier-1 (`arxiv_source`) cited papers, the relevant equation is quoted verbatim inline inside `content` Mechanism; for Tier-2 (`pdfplumber_llm`), the equation is paraphrased with a flag word. |
| `new_vocab_candidates` | `list[VocabEntry]` | Vocabulary entries the agent proposes for the runtime vocab. Externally-sourced entries set `VocabEntry.origin` to this agent's name. **Wired-empty in v1** — always returns `[]`. |
| `suggested_mindset` | `str \| None` | Optional directional prior overriding the workflow's explore/exploit default. **Wired-empty in v1** — always returns `None`. |
| `retrieved_papers` | `list[RetrievedPaper]` | Full audit trail — every paper the agent resolved or peeked at this run (root papers + dynamic-search results). Not consumed by downstream nodes. |
| `search_rounds_used` | `int` | Number of dynamic-search rounds executed. Bounded by `DynamicSearchConfig.max_rounds`. |
| `run_name` | `str` | Echoed from input — for audit clarity in the dumped JSON. |
| `started_at` | `str` | ISO-8601 UTC timestamp at `agent.run(inp)` entry. |
| `finished_at` | `str` | ISO-8601 UTC timestamp at `agent.run(inp)` exit. |

## CLI usage

None — this node does not expose a standalone CLI (`main()` is not implemented). Invoke programmatically via the Python API below, or via the workflow integration in `workflows/model_exploration.py` (Commit 6+).

### CLI arguments

N/A.

## Python API usage

```python
from nodes.ml_literature_review.ml_literature_review import MLLiteratureReviewAgent
from agent.schemas.literature_review import (
    LiteratureReviewInput, PaperSource, DynamicSearchConfig, SynthesisConfig,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig

inp = LiteratureReviewInput(
    experiment_history=interp_output,  # from upstream result_interpretation_agent
    root_papers=[
        PaperSource(source_type="arxiv", identifier="2406.04378", verbosity=1),
    ],
    dynamic_search=DynamicSearchConfig(enabled=True, max_rounds=3),
    synthesis_config=SynthesisConfig(transfer_tolerance="moderate"),
    storage=StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="./workspace", run_name="iter_001"),
    ),
    run_name="iter_001",
    llm_provider="deepseek",
    llm_model_id="deepseek-v4-pro",
)
agent = MLLiteratureReviewAgent(root_cache_dir="reference_data/root_papers_cache")
output = agent.run(inp)  # -> LiteratureReviewOutput
```

The `root_cache_dir` ctor arg controls where per-paper extracts cache (default `"reference_data/root_papers_cache"`). Pre-populated caches make subsequent runs (with the same `root_papers` set) skip both S2 resolve + LLM compression for free.

## Storage outputs

- **Output JSON**: `{storage.local.workspace}/ml_literature_review_{run_name}.json` — the validated `LiteratureReviewOutput`, written at the end of `run()`. This is an audit log; the workflow does NOT read this back — downstream nodes receive data through the protocol function in memory.
- **Root-paper cache**: `{root_cache_dir}/{sanitized_paper_id}.json` — per-paper `RetrievedPaper` cache (default dir `reference_data/root_papers_cache/`). Hits skip S2 resolve + compression on subsequent runs; delete a file to force re-fetch + re-compression.

## Key behavioral notes

- **Bottleneck-grounding is the dominant finding-count gate.** The synthesis prompt requires every finding's Implication to address a specific current bottleneck. Papers transferable in principle but not addressing any current bottleneck are correctly omitted. The finding count is naturally bounded by the seed's stable-attractor count — typically `min(num_bottlenecks, corpus_size)`. See `docs/external_agents_for_proposer.md` §10.5.a for the calibration principle.
- **Equations travel inline inside finding `content`** (in Mechanism), not via a separate channel. For Tier-1 (`arxiv_source`) papers the equation is quoted verbatim from the source `.tex`. For Tier-2 (`pdfplumber_llm`) the equation is paraphrased with an explicit flag word ("approximate equation, reconstructed from a degraded PDF"). The Adaptation section MUST NOT contain raw equations (locked placement rule).
- **Soft-drop hooks silently drop LLM-emitted findings before they reach output.** Drop conditions, all inside `_synthesize`'s for-loop: missing `content` or non-dict payload; `source_ref` not in the retrieved set; `content_paper_id != source_ref` (the cite-id consistency hook from `ce67cd2`); schema validation failure on the `ExpertContextItem` constructor. See the Parameter Reference's "Validation / soft-drop hooks" subsection for the full list.
- **`abstract_only_ceiling=0.79`** clamps abstract-only-cited findings' confidence post-synthesis — papers the LLM never deep-read can never have a top-band (0.80+) finding. This is a clip, not a drop.
- **The dynamic-search loop is high-variance** (search queries differ run-to-run even at the same seed); the structural cap on findings (one per bottleneck) is the dominant gate. Search variance only affects WHICH paper fills any non-attractor slot, not whether a slot fills.
- **`new_vocab_candidates` and `suggested_mindset` are wired-empty in v1.** The schema reserves them for future extensions; current `_synthesize` populates only `findings`.

## Dependencies

- **LLM**: three distinct call sites per run, all via `LLMBridge.generate()` (returns a parsed dict; validation via `model_validate`):
  - **Compression** — one call per non-cache-hit paper at `verbosity ≥ 1`. System prompt: `paper_extract_system.md`. Label: `"lit_review.paper_extract"`. Uses `llm_provider` / `llm_model_id`.
  - **Search decision** — one call per dynamic-search round (≤ `dynamic_search.max_rounds`). System prompt: `search_decision_system.md`. Uses `search_llm_provider` / `search_llm_model_id` (falls back to `llm_provider` / `llm_model_id`).
  - **Synthesis** — exactly one call per run. System prompt: `synthesis_system.md`. Label: `"lit_review.synthesis"`. Uses `llm_provider` / `llm_model_id`.
- **GPU**: not required.
- **External services**:
  - **Semantic Scholar API** (`S2_API_KEY` env var; silent-degrade to unauthenticated pool if absent) — paper resolution + dynamic-search hits.
  - **arxiv.org/src/ HTTP** (no auth) — Tier-1 source download for arXiv-id papers.
  - **Publisher PDF URLs** (S2's `openAccessPdf` or arXiv fallback) — Tier-2 PDF download for `pdfplumber` extraction.

---

## Appendix — Parameter Reference

This appendix enumerates every knob that influences the `ml_literature_review` node's output, and where each one lives in the schema or code. Each row tags the effect category so a reader tuning a run (or debugging an artifact) can target the right lever.

**Effect categories used in the right-most column:**
- **finding count** — how many `ExpertContextItem`s reach `LiteratureReviewOutput.findings`
- **finding quality** — specificity / groundedness / equation accuracy of each finding
- **extraction quality** — how cleanly a paper's content reaches `PaperExtract` (Tier-1 verbatim vs Tier-2 best-effort)
- **search behavior** — which papers the dynamic-search loop retrieves
- **cost** — DeepSeek / S2 / pdfplumber calls per run
- **format** — content-string layout only, not what's IN the content
- **audit/log** — disk artifact path only, not the findings themselves

### Per-paper input (`PaperSource`, one entry per `root_papers[i]`)

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `source_type` | `agent/schemas/literature_review.py:42` | `Literal["arxiv", "doi", "openreview", "local"]` | required | Identifier scheme; selects resolver path. | extraction success |
| `identifier` | `agent/schemas/literature_review.py:43` | `str` | required | ArXiv ID / DOI / OpenReview URL / repo-relative path. | extraction success |
| `verbosity` | `agent/schemas/literature_review.py:46` | `Literal[0, 1, 2]` | `1` | Per-paper resolution depth. 0=metadata only (~200 tok), 1=compressed `PaperExtract` (~750 tok), 2=full text (~6-10k tok). | extraction quality, cost |

### Dynamic search loop (`LiteratureReviewInput.dynamic_search` → `DynamicSearchConfig`)

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `enabled` | `agent/schemas/literature_review.py:74` | `bool` | `True` | Master switch. `False` → skip dynamic search entirely; only root papers feed synthesis. | **finding count (huge)**, cost |
| `max_rounds` | `agent/schemas/literature_review.py:79` | `int >= 1` | `3` | Hard cap on search iterations. Loop terminates here even if the LLM never says "done". | finding count, cost |
| `initial_verbosity` | `agent/schemas/literature_review.py:85` | `Literal[0, 1, 2]` | `0` | Verbosity for first-round search hits. | finding quality, cost |
| `escalation_allowed` | `agent/schemas/literature_review.py:90` | `bool` | `True` | Whether the LLM may request per-paper verbosity escalation mid-loop. `False` keeps all search hits at `initial_verbosity`. | finding quality, cost |
| `results_per_query` | `agent/schemas/literature_review.py:96` | `int >= 1` | `10` | S2 hits requested per search query. >10 mostly adds low-relevance noise. | search behavior, cost |
| `max_escalations_per_round` | `agent/schemas/literature_review.py:104` | `int >= 0` | `2` | Per-round cap on verbosity escalations (deep-reads). `0` disables escalation regardless of `escalation_allowed`. | finding quality, cost |

### Synthesis behavior

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `synthesis_config` (container) | `agent/schemas/literature_review.py:445` | `SynthesisConfig` | `SynthesisConfig()` | Synthesis-step knobs container. | (see sub-fields) |
| └─ `transfer_tolerance` | `agent/schemas/literature_review.py:371` | `Literal["strict", "moderate", "liberal"]` | `"moderate"` | How readily synthesis emits a finding for a **cross-domain** paper. Selects the `{OMISSION_RULE}` block injected into the synthesis prompt. `strict` omits cross-domain papers; `moderate` emits with Adaptation transfer-caveat; `liberal` emits for any potentially relevant technique. | finding count (paper-set shifts), finding quality (cross-domain admission) |
| `findings_verbosity` | `agent/schemas/literature_review.py:436` | `Literal[0, 1]` | `1` | Format of `ExpertContextItem.content`. `1` = three-part Markdown (Implication / Mechanism / Adaptation + rationale); `0` = single-paragraph backward-compat. **Format only — does not affect count.** | format |

### Confidence rubric (`LiteratureReviewInput.confidence_rubric` → `ConfidenceRubric`)

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `confidence_rubric` (container) | `agent/schemas/literature_review.py:428` | `ConfidenceRubric` | `ConfidenceRubric()` | Single source of truth for confidence semantics. Injected into the synthesis prompt via `{CONFIDENCE_RUBRIC}`; also rendered into `AgentCard.trust_guidance` so the proposer interprets the same way. | (see sub-fields) |
| └─ `bands` | `agent/schemas/literature_review.py:295` | `list[ConfidenceBand]` | three bands — `0.80-1.00` (deep-read AND on-domain AND addresses a bottleneck), `0.60-0.79` (deep-read with clear mechanism transfer OR on-domain abstract with strong signal), `0.40-0.59` (abstract-only OR cross-domain with plausible transfer) | Band definitions the synthesis LLM must use to assign each finding's confidence. | finding quality (calibration), confidence distribution |
| └─ `omit_below` | `agent/schemas/literature_review.py:301` | `float` ∈ [0,1] | `0.40` | Findings with confidence < this threshold are omitted at synthesis time. **The omit threshold's single source of truth — never duplicated in prompt text.** | **finding count** |
| └─ `abstract_only_ceiling` | `agent/schemas/literature_review.py:309` | `float` ∈ [0,1] | `0.79` | Maximum confidence a finding may keep when its cited paper was never deep-read (`verbosity_achieved == 0`). Clamped node-side after synthesis. | confidence distribution (no findings dropped — just capped) |

### Grounding context (`LiteratureReviewInput.experiment_history` → `InterpretationOutput`)

The synthesis prompt requires every finding's **Implication** to ground in one of the listed `bottlenecks`. This makes the experiment seed itself a finding-count parameter — a corpus of 7 papers against 2 bottlenecks yields ~2 stable-attractor findings plus an intermittent third slot (per `docs/external_agents_for_proposer.md` §10.5.a; the 2026-06-09 run chain in `validation_suite_runs.md` is the empirical record).

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `experiment_history.bottlenecks` | `agent/schemas/interpretation.py` (InterpretationOutput) | `list[str]` | — (required, from upstream interpretation agent) | Open bottlenecks the proposer is working on. The synthesis prompt explicitly grounds each finding in one of these. | **finding count (the binding constraint via stable-attractor calibration)** |
| `experiment_history.key_findings` | `agent/schemas/interpretation.py` | `list[str]` | — | Findings carried from prior iterations. Provided to the synthesis LLM as PRIMARY input alongside bottlenecks. | finding quality (relevance) |
| `experiment_history.take_home_message` | `agent/schemas/interpretation.py` | `str` | — | One-line summary of current state. Surfaced near the top of the synthesis prompt. | finding quality (framing) |
| `root_papers` (count) | `agent/schemas/literature_review.py:400` length | `list[PaperSource]` length | `[]` | Locked starting set of papers. More roots = more candidate citations, more equations in scope. | finding count, finding quality |

### LLM routing

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `llm_provider` | `agent/schemas/literature_review.py:413` | `str` | required | Main provider — used for compression + synthesis. | finding quality, extraction quality |
| `llm_model_id` | `agent/schemas/literature_review.py:414` | `str` | required | Main model id. | finding quality, extraction quality |
| `search_llm_provider` | `agent/schemas/literature_review.py:415` | `str \| None` | `None` (falls back to `llm_provider`) | Optional separate provider for the cheap, templated query/escalate/done step. Lets the search loop run on a cheaper model while compression + synthesis stay on the main one. | search behavior, cost |
| `search_llm_model_id` | `agent/schemas/literature_review.py:423` | `str \| None` | `None` (falls back to `llm_model_id`) | Optional separate model id for the search-decision call. | search behavior, cost |

### Storage + run identity

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `storage` | `agent/schemas/literature_review.py:409` | `StorageConfig` | required | Where the run dumps its `LiteratureReviewOutput` JSON. | audit/log |
| `run_name` | `agent/schemas/literature_review.py:412` | `str` | required | Filename component for the dumped JSON. | audit/log |

### Code-level constants (override only by editing code)

| Constant | Location | Value | Controls | Affects |
|---|---|---|---|---|
| `MAX_RAW_TEXT_CHARS` | `agent/prompt_templates/literature_review/__init__.py:182` | `120_000` (~30k tokens at 4 chars/token) | Hard cap on raw paper text fed to the compression prompt. Beyond is replaced with `[...TRUNCATED...]`. | extraction quality (truncated papers lose content) |
| `DEFAULT_ROOT_CACHE_DIR` | `nodes/ml_literature_review/ml_literature_review.py:61` | `"reference_data/root_papers_cache"` | On-disk directory for root-paper extract cache. Override via `MLLiteratureReviewAgent(root_cache_dir=...)`. | cost (cache hit avoids re-resolve + re-compress) |
| `SIDERIUS_TASK` | `agent/prompt_templates/literature_review/__init__.py:188` | task-description string | Downstream task description injected into the compression + synthesis prompts. `render_paper_extract_prompt` accepts `task_description=` if generalizing beyond SQUID. | finding quality (relevance grounding), extraction quality (`relevance_to_task` field) |
| `S2_DEFAULT_TIMEOUT_S` / `S2_MIN_REQUEST_INTERVAL_S` / `S2_MAX_RETRIES` | `agent/skills/paper_resolver_skill/wrapper.py:46-51` | `30` / `1.1` / `3` | S2 network behavior. | extraction success rate |
| `_AGENT_CARD.trust_level` | `nodes/ml_literature_review/ml_literature_review.py:65` | `"soft_prior"` | Machine-readable trust calibration emitted on every run, read by the proposer's synthesis rules (P-b + P-c). Three valid levels: `hard_limit` (non-negotiable — physics-style constraints), `strong_prior` (weight comparably to experiment data — human directives), `soft_prior` (inspirational priors requiring experiment validation — literature). Lit-review is `soft_prior` by design. **Override only by changing the constant in code** — per-run override would defeat the calibration's role as a stable signal. | proposal weighting |

### Resolver-skill parameters NOT currently exposed via `LiteratureReviewInput`

These exist on the underlying `paper_resolver_skill` but the lit-review node never passes them today. Flagged as known unexposed levers for future tuning.

| Parameter | Where it lives | Why not exposed |
|---|---|---|
| `year` (search-mode filter) | `agent/skills/paper_resolver_skill/skill_config.json` | The dynamic-search loop builds queries without year filters. |
| `fields_of_study` | same | No field-of-study filter passed today. |
| `publication_types` | same | Same. |
| `min_citation_count` | same | Same. |

### Validation / soft-drop hooks (not user-tunable, but they affect finding count)

These run inside `_synthesize`'s for-loop and silently drop findings before they reach `LiteratureReviewOutput.findings`. Listing them here so the count-vs-quality picture is complete.

| Hook | Location | Drop condition |
|---|---|---|
| Missing content | `_synthesize` for-loop | `f.get("content")` is falsy or `f` is not a dict |
| Unmatched source_ref | `_synthesize` for-loop | `source_ref not in valid_ids` (cited paper not in the retrieved set) |
| `content_paper_id` consistency (post-2d cite-id fix) | `_validate_content_paper_id` | `content_paper_id` missing, not in `valid_ids`, or `!= source_ref` |
| Confidence clamp (`abstract_only_ceiling`) | `_clamp_abstract_only_confidence` | (clip, not drop) — v=0-cited finding's confidence is clipped to the ceiling |
| Heading normalisation (`_normalize_finding_content_headings`) | `_synthesize` for-loop | (transform, not drop) — rewrites known heading variants to canonical form |
| `ExpertContextItem` schema validation | constructor `try/except ValidationError` | Unexpected schema violation on the LLM payload |
