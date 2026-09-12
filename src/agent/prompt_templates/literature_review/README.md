# `literature_review/`

Owns the three named literature-review system prompt resources:
[`search_decision_system.md`](search_decision_system.md),
[`paper_extract_system.md`](paper_extract_system.md), and
[`synthesis_system.md`](synthesis_system.md). The literature-review node
selects these resources for its search, extraction, and synthesis phases;
`README.md` is not a model input.

This child has no task-block adapter or executable plugin. Prompt regressions
are pinned by [`test_step00_prompt_goldens.py`](../../../../tests/unit/agent/ml_literature_review/test_step00_prompt_goldens.py);
the paper lookup implementation and its network boundary are documented under
[`agent/skills/paper_resolver_skill`](../../skills/paper_resolver_skill/README.md).
