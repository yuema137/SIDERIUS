# Paper resolver skill

The callable entry is run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py).
The exact two-mode declaration is [skill_config.json](skill_config.json), and
the extraction contract is described there. Use mode=resolve for one
arXiv/DOI/OpenReview/local identifier or mode=search for Semantic Scholar
keywords; verbosity controls full-text retrieval. Every path returns a
status/data/message envelope.

Resolve/search can call Semantic Scholar, download PDFs or arXiv source, and
extract text; local resolution is bounded to the checkout. Responses may be
cached per process, and failures become partial/error rather than raising. This
is an effectful network/filesystem skill, not a literature opinion generator.

Focused unit coverage: [test_paper_resolver_skill.py](../../../../tests/unit/agent/skills/test_paper_resolver_skill.py)
and [test_arxiv_source.py](../../../../tests/unit/agent/skills/test_arxiv_source.py);
live retrieval integration is separate at
[tests/integration/skills/test_paper_resolver_skill.py](../../../../tests/integration/skills/test_paper_resolver_skill.py).
