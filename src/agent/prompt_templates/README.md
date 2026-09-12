# `src/agent/prompt_templates/`

Model-facing resources and the typed adapters that splice task-owned guidance
into prompts. The named Markdown files are runtime inputs only when an explicit
renderer selects their filename; `README.md` is documentation and is not a
template or task declaration. Task meaning enters through validated manifest
and schema values, not through edits to these resources.

Children map to the five prompt families: [implementor](implementor/README.md),
[interpretation](interpretation/README.md),
[literature review](literature_review/README.md), [proposal](proposal/README.md),
and [tuner](tuner/README.md). Shared YAML loading mechanics live in
[_task_blocks_loader.py](_task_blocks_loader.py); each family retains its own
Pydantic block schema.

For the source-level boundary, see [the loader](_task_blocks_loader.py) and
the family renderers linked by each child guide. Prompt byte contracts are
covered by the relevant `tests/unit/agent/*/test_step00_prompt_goldens.py` and
task-block adapters by `tests/unit/workflows/`.
