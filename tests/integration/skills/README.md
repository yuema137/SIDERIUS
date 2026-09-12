# tests/integration/skills

Paper resolver integration exercises live Semantic Scholar/arXiv resolution;
it is an opt-in `real_run` route requiring network credentials and is skipped
otherwise.

## Source and route

`.venv/bin/python -m pytest tests/integration/skills/test_paper_resolver_skill.py -q`

Owner: `src/agent/skills/paper_resolver_skill/wrapper.py`; collecting the command alone
does not perform a live resolution. See the [integration map](../README.md).
