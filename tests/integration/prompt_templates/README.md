# tests/integration/prompt_templates

The paper-extract integration route resolves a paper and validates a rendered
compression prompt through the real LLM bridge. It is `real_run`, requires
provider/network credentials, and is skipped by default.

## Source and route

`.venv/bin/python -m pytest tests/integration/prompt_templates/test_paper_extract_compression.py -q`

Owner: `src/agent/prompt_templates` and `src/skills/paper_resolver_skill.py`.
The command above collects but does not claim a live run without `-m real_run`.
