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
  equation / pseudocode inline); `cite_id` attributes it to a paper;
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

## CLI usage

_TODO (future): standalone CLI invocation placeholder._ Not yet implemented; this
section reserves the slot for the node's command-line entry point.
