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
synthesizes `findings` (+ a `reference_library`) for the proposer.

## Input

_TODO (Commit 2d): explain every `LiteratureReviewInput` field._ Fields:
`experiment_history`, `root_papers`, `dynamic_search` (`DynamicSearchConfig`),
`confidence_rubric`, `llm_provider` / `llm_model_id`,
`search_llm_provider` / `search_llm_model_id`, `storage`, `run_name`.

## Output

_TODO (Commit 2d)._ `LiteratureReviewOutput` (extends `ExternalAgentOutput`):
- `agent_card` — static self-description + confidence-rubric legend (trust calibration).
- `findings` — `ExpertContextItem`s: *what to try*, grounded in bottlenecks.
- `reference_library` — `PaperReference`s: *how to implement it* (raw `PaperExtract`
  per verbosity≥1 cited paper). See §5b.
- `retrieved_papers` — full audit trail; `search_rounds_used`; timestamps.

## Output contract for downstream consumers

_TODO (Commit 2d)._ How to consume this node's output:
- **findings** — read `content` (names the bottleneck + the concrete implication);
  `cite_id` attributes it to a paper; `confidence` interpreted per the rubric.
- **reference_library** — for a finding worth acting on, take its `cite_id` and
  look up the matching `PaperReference` for the original equations
  (`key_equations_md`), pseudocode (`pseudocode_md`), and architecture details.
  Pull channel — read only the entries you need.
- **confidence scores** — defined by `ConfidenceRubric` (single source of truth);
  the bands are surfaced to the proposer via `agent_card.trust_guidance`.
  `extraction_method` on each reference entry signals equation reliability.

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
- Equation content in `reference_library` is reliable only after Commit 2c's
  three-tier extraction lands (`extraction_method` is the trust signal).
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
