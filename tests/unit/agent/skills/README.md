# Agent skill tests

Skill implementations are under [`src/agent/skills`](../../../../src/agent/skills/); each skill directory owns its wrapper/config and manual. `test_arxiv_source.py` and `test_paper_resolver_skill.py` use mocked HTTP/PDF extraction to exercise mode/identifier validation, arXiv open-access fallback, verbosity short-circuit, DOI/OpenReview routing, tier cascades, and local-path safety. The calibration test covers realizer extents. No network or PDF service is contacted; wrapper errors and refusal boundaries are the intended defects.

`.venv/bin/python -m pytest tests/unit/agent/skills/test_paper_resolver_skill.py -q`
