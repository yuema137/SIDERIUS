# ml_literature_review — node README

> **STUB (Commit 2d).** This is the first instance of the node-README convention
> for CLI agent discoverability. Section headers + placeholders are in place now;
> the full content is filled in during Commit 2d implementation. See
> `docs/external_agents_for_proposer.md` (§5, §5a, §5b) and
> `docs/commit_plan_ml_literature_review.md` for the authoritative design.

## Purpose

_TODO (Commit 2d)._ The `ml_literature_review` node is the first external agent
feeding the proposal pipeline: it resolves root papers, runs a dynamic
Semantic-Scholar search loop grounded in the current iteration's
`InterpretationOutput`, deep-reads selected papers into `PaperExtract`s, and
synthesizes `findings` for the proposer.

## Input

_TODO (Commit 2d): explain every `LiteratureReviewInput` field._ Fields:
`experiment_history`, `root_papers`, `dynamic_search` (`DynamicSearchConfig`),
`confidence_rubric`, `llm_provider` / `llm_model_id`,
`search_llm_provider` / `search_llm_model_id`, `storage`, `run_name`.

## Output

_TODO (Commit 2d)._ `LiteratureReviewOutput` (extends `ExternalAgentOutput`):
- `agent_card` — static self-description + confidence-rubric legend (trust calibration).
- `findings` — `ExpertContextItem`s: *what to try*, grounded in bottlenecks.
  When a cited paper has Tier-1 `key_equations_md` / `pseudocode_md`, the
  synthesis LLM quotes the relevant equation / algorithm directly inside the
  finding's `content` (primarily in **Mechanism**); the equation reaches the
  proposer as a literal part of the finding string. See §5b of
  `docs/external_agents_for_proposer.md`.
- `retrieved_papers` — full audit trail; `search_rounds_used`; timestamps.

**Sole output channel to the proposer:** `findings`. There is no separate
`reference_library` output field — equations travel inline inside finding
`content` (per the 2d revision; see §5b for the channel-cancellation
rationale). The proposer-side schema (`ProposalInput`) is unchanged.

## Output contract for downstream consumers

_TODO (Commit 2d)._ How to consume this node's output:
- **findings** — read `content` (names the bottleneck + the concrete
  implication, and for Tier-1-cited papers carries the verbatim
  equation / pseudocode inline); `source_ref` attributes it to a paper;
  `confidence` interpreted per the rubric.
- **confidence scores** — defined by `ConfidenceRubric` (single source of
  truth); the bands are surfaced to the proposer via
  `agent_card.trust_guidance`. The cited paper's `extraction_method`
  drives whether the synthesis LLM quotes the equation verbatim
  (Tier-1 `arxiv_source`) or as a flagged paraphrase
  (Tier-2 `pdfplumber_llm`).

## LLM routing

_TODO (Commit 2d): full rationale._ Current decision: `deepseek-v4-pro` for all
three LLM steps (search-decision, compression, synthesis) — DeepSeek produced
cleaner search queries and more detailed/accurate compression than gpt-4o-mini.
`search_llm_provider` / `search_llm_model_id` allow routing the cheap, templated
search-decision step to a different model; they are dormant under the all-DeepSeek
default.

## Known limitations

_TODO (Commit 2d)._
- Escalation (mid-loop deep-reads) fires rarely: the search-decision LLM
  evaluates retrieved papers each round but applies a conservative
  "directly addresses a bottleneck with a specific actionable mechanism" bar, so
  verbosity≥1 findings arise mostly from root papers.
- Equation content quoted inline inside finding `content` is reliable only
  for Tier-1 (`arxiv_source`) papers — Commit 2c's two-tier extraction
  drives this. Tier-2 (`pdfplumber_llm`) equations are quoted as flagged
  paraphrases; `abstract_only` papers contribute no equations.
- Cannot run experiments or judge SQUID-specific applicability without empirical
  confirmation (findings are promising priors only).

## Configuration example

_TODO (Commit 2d): complete `configs/lit_review_config.yaml` with inline comments._

```yaml
# configs/lit_review_config.yaml (STUB — to be completed in Commit 2d)
# root_papers: foundational papers always resolved at agent start.
# root_papers:
#   - source_type: arxiv
#     identifier: "2406.04378"   # TIDMAD — the SQUID denoising benchmark
#     verbosity: 1               # deep-read (compressed PaperExtract)
# dynamic_search:
#   enabled: true
#   max_rounds: 3
#   ...
```

## Parameter Reference

This section enumerates every knob that influences the `ml_literature_review`
node's output, and where each one lives in the schema or code. Each row tags
the effect category so a reader tuning a run (or debugging an artifact) can
target the right lever.

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
| └─ `transfer_tolerance` | `agent/schemas/literature_review.py:371` | `Literal["strict", "moderate", "liberal"]` | `"moderate"` | How readily synthesis emits a finding for a **cross-domain** paper. Selects the `{OMISSION_RULE}` block injected into the synthesis prompt. `strict` omits cross-domain papers; `moderate` emits with Adaptation transfer-caveat; `liberal` emits for any potentially relevant technique. | **finding count**, finding quality (cross-domain admission) |
| `findings_verbosity` | `agent/schemas/literature_review.py:436` | `Literal[0, 1]` | `1` | Format of `ExpertContextItem.content`. `1` = three-part Markdown (Implication / Mechanism / Adaptation + rationale); `0` = single-paragraph backward-compat. **Format only — does not affect count.** | format |

### Confidence rubric (`LiteratureReviewInput.confidence_rubric` → `ConfidenceRubric`)

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `confidence_rubric` (container) | `agent/schemas/literature_review.py:428` | `ConfidenceRubric` | `ConfidenceRubric()` | Single source of truth for confidence semantics. Injected into the synthesis prompt via `{CONFIDENCE_RUBRIC}`; also rendered into `AgentCard.trust_guidance` so the proposer interprets the same way. | (see sub-fields) |
| └─ `bands` | `agent/schemas/literature_review.py:295` | `list[ConfidenceBand]` (each `ConfidenceBand`: `lower` ∈ [0,1], `upper` ∈ [0,1], `criteria: str`) | three bands — `0.80-1.00` (deep-read AND on-domain AND addresses a bottleneck), `0.60-0.79` (deep-read with clear mechanism transfer OR on-domain abstract with strong signal), `0.40-0.59` (abstract-only OR cross-domain with plausible transfer) | Band definitions the synthesis LLM must use to assign each finding's confidence. | finding quality (calibration), confidence distribution |
| └─ `omit_below` | `agent/schemas/literature_review.py:301` | `float` ∈ [0,1] | `0.40` | Findings with confidence < this threshold are omitted at synthesis time. **The omit threshold's single source of truth — never duplicated in prompt text.** | **finding count** |
| └─ `abstract_only_ceiling` | `agent/schemas/literature_review.py:309` | `float` ∈ [0,1] | `0.79` | Maximum confidence a finding may keep when its cited paper was never deep-read (`verbosity_achieved == 0`). Clamped node-side after synthesis. | confidence distribution (no findings dropped — just capped) |

### Grounding context (`LiteratureReviewInput.experiment_history` → `InterpretationOutput`)

The synthesis prompt requires every finding's **Implication** to ground in
one of the listed `bottlenecks`. This makes the experiment seed itself a
finding-count parameter — a corpus of 7 papers against 2 bottlenecks rarely
produces more than 2-4 distinct findings.

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `experiment_history.bottlenecks` | `agent/schemas/interpretation.py` (InterpretationOutput) | `list[str]` | — (required, from upstream interpretation agent) | Open bottlenecks the proposer is working on. The synthesis prompt explicitly grounds each finding in one of these. | **finding count (often the binding constraint when only 1-2 bottlenecks exist)** |
| `experiment_history.key_findings` | `agent/schemas/interpretation.py` | `list[str]` | — | Findings carried from prior iterations. Provided to the synthesis LLM as PRIMARY input alongside bottlenecks. | finding quality (relevance) |
| `experiment_history.take_home_message` | `agent/schemas/interpretation.py` | `str` | — | One-line summary of current state. Surfaced near the top of the synthesis prompt. | finding quality (framing) |
| `root_papers` (count) | `agent/schemas/literature_review.py:400` length | `list[PaperSource]` length | `[]` | Locked starting set of papers. More roots = more candidate citations, more equations in scope. | finding count, finding quality |

### LLM routing

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `llm_provider` | `agent/schemas/literature_review.py:413` | `str` (LLMBridge provider name) | required | Main provider — used for compression + synthesis. | finding quality, extraction quality |
| `llm_model_id` | `agent/schemas/literature_review.py:414` | `str` (LLMBridge model id) | required | Main model id. | finding quality, extraction quality |
| `search_llm_provider` | `agent/schemas/literature_review.py:415` | `str \| None` | `None` (falls back to `llm_provider`) | Optional separate provider for the cheap, templated query/escalate/done step. Lets the search loop run on a cheaper model while compression + synthesis stay on the main one. | search behavior, cost |
| `search_llm_model_id` | `agent/schemas/literature_review.py:423` | `str \| None` | `None` (falls back to `llm_model_id`) | Optional separate model id for the search-decision call. | search behavior, cost |

### Storage + run identity

| Parameter | Location | Type / values | Default | Controls | Affects |
|---|---|---|---|---|---|
| `storage` | `agent/schemas/literature_review.py:409` | `StorageConfig` (backend, `local.workspace`, `local.run_name`) | required | Where the run dumps its `LiteratureReviewOutput` JSON. | audit/log |
| `run_name` | `agent/schemas/literature_review.py:412` | `str` | required | Filename component for the dumped JSON. | audit/log |

### Code-level constants (override only by editing code)

| Constant | Location | Value | Controls | Affects |
|---|---|---|---|---|
| `MAX_RAW_TEXT_CHARS` | `agent/prompt_templates/literature_review/__init__.py:182` | `120_000` (~30k tokens at 4 chars/token) | Hard cap on raw paper text fed to the compression prompt. Text beyond is replaced with `[...TRUNCATED...]`. | extraction quality (truncated papers lose content) |
| `DEFAULT_ROOT_CACHE_DIR` | `nodes/ml_literature_review.py:61` | `"reference_data/root_papers_cache"` | On-disk directory for root-paper extract cache. Override via `MLLiteratureReviewAgent(root_cache_dir=...)`. | cost (cache hit avoids re-resolve + re-compress) |
| `SIDERIUS_TASK` | `agent/prompt_templates/literature_review/__init__.py:188` | task-description string | Downstream task description injected into the compression + synthesis prompts. `render_paper_extract_prompt` accepts a `task_description=` kwarg if generalizing beyond SQUID. | finding quality (relevance grounding), extraction quality (`relevance_to_task` field) |
| `S2_DEFAULT_TIMEOUT_S` / `S2_MIN_REQUEST_INTERVAL_S` / `S2_MAX_RETRIES` | `agent/skills/paper_resolver_skill/wrapper.py:46-51` | `30` / `1.1` / `3` | S2 network behavior (per-request timeout, throttle interval, retry count on 429/5xx). | extraction success rate |
| `_AGENT_CARD.trust_level` | `nodes/ml_literature_review.py:65` | `"soft_prior"` | Machine-readable trust calibration emitted on every run, read by the proposer's synthesis rules (P-b + P-c). Three valid levels: `hard_limit` (non-negotiable — physics-style constraints), `strong_prior` (weight comparably to experiment data — human directives), `soft_prior` (inspirational priors requiring experiment validation — literature). Lit-review is `soft_prior` by design: findings expand the design space but require experiment confirmation. **Override only by changing the constant in code** — overriding per-run would defeat the calibration's role as a stable signal the proposer can trust. | proposal weighting (the proposer's synthesis rules treat soft_prior findings as inspirational; experiment data takes precedence on conflict) |

### Resolver-skill parameters NOT currently exposed via `LiteratureReviewInput`

These exist on the underlying `paper_resolver_skill` but the lit-review node
never passes them today. Flagged as known unexposed levers for future tuning.

| Parameter | Where it lives | Why not exposed |
|---|---|---|
| `year` (search-mode filter) | `agent/skills/paper_resolver_skill/skill_config.json` | The dynamic-search loop builds queries without year filters. |
| `fields_of_study` | same | Same — no field-of-study filter passed today. |
| `publication_types` | same | Same. |
| `min_citation_count` | same | Same. |

### Validation / soft-drop hooks (not user-tunable, but they affect finding count)

These run inside `_synthesize`'s for-loop and silently drop findings before
they reach `LiteratureReviewOutput.findings`. Listing them here so the
count-vs-quality picture is complete.

| Hook | Location | Drop condition |
|---|---|---|
| Missing content | `_synthesize` for-loop | `f.get("content")` is falsy or `f` is not a dict |
| Unmatched source_ref | `_synthesize` for-loop | `source_ref not in valid_ids` (cited paper not in the retrieved set) |
| `content_paper_id` consistency (post-2d cite-id fix) | `_validate_content_paper_id` (`nodes/ml_literature_review.py`) | `content_paper_id` missing, not in `valid_ids`, or `!= source_ref` |
| Confidence clamp (`abstract_only_ceiling`) | `_clamp_abstract_only_confidence` | (clip, not drop) — v=0-cited finding's confidence is clipped to the ceiling |
| Heading normalisation (`_normalize_finding_content_headings`) | `_synthesize` for-loop | (transform, not drop) — rewrites known heading variants to canonical form |
| `ExpertContextItem` schema validation | constructor `try/except ValidationError` | Unexpected schema violation on the LLM payload |

## CLI usage

_TODO (future): standalone CLI invocation placeholder._ Not yet implemented; this
section reserves the slot for the node's command-line entry point.
