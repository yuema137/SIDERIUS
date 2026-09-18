# literature-review: native schema field inventory

Reference snapshot: SIDERIUS `2df46e2298c017d9df850a85f870a55fbd40723d`. Derived from the actual
Pydantic `model_fields`; the installed classes remain the execution authority.
Defaults below describe the generic API, not permission to override the
frozen task, information treatment, budget, or candidate-selection contract.
Custom validators can impose cross-field requirements not expressible by a
required-field flag. Use `model_validate` / `model_validate_json` before execution.

Return to the [capability guide](../agents/literature-review.md).

## LiteratureReviewInput

Import: `agent.schemas.literature_review.LiteratureReviewInput`.

| Field | Python type | Required / default | Constraints | Meaning |
| --- | --- | --- | --- | --- |
| interpretation_evidence | agent.schemas.literature_review.LiteratureReviewInterpretationEvidence | required | [] | Bounded current-state evidence projected from InterpretationOutput. |
| data_analysis_evidence | agent.schemas.literature_review.LiteratureReviewDataEvidence \| None | None | [] | Optional bounded observations projected from DataAnalysisReport. Reasoning context only: it grants no data access or execution authority. |
| root_papers | list[agent.schemas.literature_review.PaperSource] | factory: list | [] | Foundational papers always resolved at agent start. Supplied by the caller's task or experiment config. Per-paper extracts are cached under the run workspace. |
| dynamic_search | agent.schemas.literature_review.DynamicSearchConfig | factory: DynamicSearchConfig | [] |  |
| storage | agent.schemas.storage.StorageConfig | required | [] | Where the node writes ml_literature_review_{run_name}.json. |
| run_name | str | required | [] | Run identifier shared with the workflow. |
| llm_provider | str | required | [] | LLMBridge provider name (e.g. 'openai'). |
| llm_model_id | str | required | [] | LLMBridge model id (e.g. 'gpt-4o-mini'). |
| llm_reasoning_effort | str \| None | None | [] | Explicit OpenAI main-bridge reasoning effort. |
| search_llm_provider | str \| None | None | [] | Optional separate LLMBridge provider for the dynamic-search DECISION call only (the cheap, templated query/escalate/done step). When None, llm_provider is used. Lets the templated search step run on a cheaper model (e.g. 'deepseek') while compression + synthesis stay on llm_provider/llm_model_id. Mirrors LLMBridge.reflect_provider. |
| search_llm_model_id | str \| None | None | [] | Optional separate model id for the search-decision call (e.g. 'deepseek-v4-pro'). When None, llm_model_id is used. |
| search_llm_reasoning_effort | str \| None | None | [] | Explicit OpenAI search-bridge reasoning effort. |
| confidence_rubric | agent.schemas.literature_review.ConfidenceRubric | factory: ConfidenceRubric | [] | Rubric defining what a finding's confidence score means. Injected into the synthesis prompt; the single source of truth for confidence semantics (see 'Scoring and rubric design invariants' in docs/external_agents_architecture.md). Override to retune without touching any prompt file. |
| findings_verbosity | Literal[0, 1] | 1 | [] | Detail level for each finding's 'content' string. 1 = structured three-part Markdown ('**Implication:**' / '**Mechanism:**' / '**Adaptation:**' + closing '(rationale: ...)'), the canonical proposer-facing format. 0 = single-paragraph backward-compat. Only the synthesis prompt's content format changes; the ExpertContextItem schema is unchanged either way. |
| synthesis_config | agent.schemas.literature_review.SynthesisConfig | factory: SynthesisConfig | [] | Omission / transfer-tolerance knobs for the synthesis step. Default tolerance is 'moderate' — cross-domain papers with a transferable mechanism yield a finding carrying an explicit Adaptation transfer caveat, rather than being omitted. See SynthesisConfig. |
| task_description | str | '' | [] | The research task this lit-review run is supporting. Injected into the {TASK_DESCRIPTION} placeholder of every lit-review prompt (paper-extract, search-decision, synthesis). Callers should set this from their task declaration to specialize the agent for their problem domain. When empty, the {TASK_DESCRIPTION} placeholder is filled with the empty string, leaving the prompt section bare — the LLM gets no task-domain anchor. |

Read the complete nested JSON Schema from the same public class:

```python
import json
from agent.schemas.literature_review import LiteratureReviewInput
print(json.dumps(LiteratureReviewInput.model_json_schema(), indent=2))
```

This inspection uses the selected installation and does not instantiate an
agent or call a model provider. It does not grant access to a dataset.

## LiteratureReviewOutput

Import: `agent.schemas.literature_review.LiteratureReviewOutput`.

| Field | Python type | Required / default | Constraints | Meaning |
| --- | --- | --- | --- | --- |
| agent_card | agent.schemas.proposal.AgentCard | required | [] | Static self-description of the producing agent. Tells the proposal LLM how to weight this agent's findings relative to experiment results and other sources. |
| findings | list[agent.schemas.proposal.ExpertContextItem] | factory: list | [] | Soft contextual signal — facts, citations, recommendations. The always-on channel: every external agent populates this whenever it has anything to say. |
| new_vocab_candidates | list[agent.schemas.vocab.VocabEntry] | factory: list | [] | Vocabulary entries the agent proposes for the runtime vocab. Externally-sourced entries must set VocabEntry.origin to the agent_name and never count toward seen_in_runs (see VocabEntry docstring). |
| suggested_mindset | str \| None | None | [] | Optional directional prior overriding the workflow's explore/exploit default. Populate only with high-confidence evidence (e.g. a physical constraint), not a literature hint. |
| retrieved_papers | list[agent.schemas.literature_review.RetrievedPaper] | factory: list | [] | Full list of papers the agent looked at this run — root papers plus dynamic-search results. Audit trail only; the workflow merge does not consume this field. |
| search_rounds_used | int | 0 | [Ge(ge=0)] | Number of dynamic-search rounds executed. Bounded by DynamicSearchConfig.max_rounds. |
| search_decisions | list[agent.schemas.literature_review.SearchDecisionRecord] | factory: list | [] | Audit trail of LLM decisions inside the dynamic-search loop — one record per LLM call. Empty when the search loop did not run (dynamic_search.enabled=False) or the LLM call raised before any decision was logged. See SearchDecisionRecord. |
| run_name | str | required | [] |  |
| started_at | str | required | [] | ISO-8601 UTC timestamp. |
| finished_at | str | required | [] | ISO-8601 UTC timestamp. |

Read the complete nested JSON Schema from the same public class:

```python
import json
from agent.schemas.literature_review import LiteratureReviewOutput
print(json.dumps(LiteratureReviewOutput.model_json_schema(), indent=2))
```

This inspection uses the selected installation and does not instantiate an
agent or call a model provider. It does not grant access to a dataset.
